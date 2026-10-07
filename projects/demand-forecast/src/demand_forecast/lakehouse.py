"""Write hourly demand into an Iceberg table, partitioned by month.

The table format is what makes "retrain on the data as it stood on date D" a
query rather than an archaeological exercise. Two properties earn it here:

**Time travel.** A model is reproducible only if its inputs are. Git recovers
the code; nothing recovers the data unless the table keeps its history. Every
write creates a snapshot, and a snapshot id is a citable fact — which is why
:func:`write_demand` returns one rather than ``None``.

**Schema evolution.** The dataset register warns that the TLC feed changes
schema across years. A format that requires rewriting history on a column
addition makes that change expensive enough to be avoided, and avoided schema
changes become undocumented preprocessing.

Locally the warehouse is MinIO over the same S3 API the cloud path uses, so
only the endpoint differs (ADR-004). Nothing here knows which it is talking to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl
import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import MonthTransform
from pyiceberg.types import DoubleType, IntegerType, LongType, NestedField, TimestampType

NAMESPACE = "demand_forecast"
TABLE = "hourly_demand"
QUALIFIED = f"{NAMESPACE}.{TABLE}"

#: Field ids are explicit and must never be reused. Iceberg tracks columns by
#: id, not by name: renaming a column keeps its id and stays compatible, while
#: reusing a retired id silently reinterprets old data as the new column.
DEMAND_SCHEMA = Schema(
    NestedField(1, "zone_id", IntegerType(), required=True),
    NestedField(2, "event_time", TimestampType(), required=True),
    NestedField(3, "trip_count", LongType(), required=True),
    NestedField(4, "mean_distance", DoubleType(), required=False),
    NestedField(5, "total_fare", DoubleType(), required=False),
)

#: Partition by month of the event. Matches how the source arrives (one file
#: per month) so a backfill rewrites exactly the partitions it touches, and
#: matches how the data is queried — a forecast reads recent months, never the
#: whole history.
DEMAND_PARTITION = PartitionSpec(
    PartitionField(source_id=2, field_id=1000, transform=MonthTransform(), name="event_month")
)


@dataclass(frozen=True)
class WriteResult:
    """What one write produced, in terms that can be cited later.

    Attributes:
        snapshot_id: The snapshot this write created. A model card that records
            it can reconstruct its exact training input; one that records only
            a date cannot, because the date's contents may have been rewritten.
        rows: Rows written, or for a delete, rows removed.
        mode: ``append``, ``overwrite`` or ``delete``.
    """

    snapshot_id: int
    rows: int
    mode: str

    def __str__(self) -> str:
        return f"{self.mode} {self.rows:,} rows -> snapshot {self.snapshot_id}"


def local_catalog(warehouse_uri: str | None = None, catalog_db: str | None = None) -> SqlCatalog:
    """A catalogue backed by MinIO, using the same S3 API as the cloud path.

    The SQL catalogue is a local-only choice: in cloud this is Glue or BigLake.
    The TABLE format is identical either way, which is the point — schema,
    partitioning and snapshots are exercised here exactly as they behave there.

    Args:
        warehouse_uri: S3 URI for table data. Defaults to the local bucket.
        catalog_db: SQLite file holding table metadata pointers.
    """
    return SqlCatalog(
        "local",
        **{
            "uri": catalog_db or os.environ.get("ICEBERG_CATALOG_URI", "sqlite:///data/iceberg/catalog.db"),
            "warehouse": warehouse_uri or os.environ.get("ICEBERG_WAREHOUSE", "s3://lakehouse/"),
            "s3.endpoint": os.environ.get("MINIO_ENDPOINT", "http://localhost:19000"),
            # Local-only credentials, matching platform/local/manifests. The
            # cloud path resolves these from a secret manager via External
            # Secrets — never from a literal (rule 06-security-governance).
            "s3.access-key-id": os.environ.get("MINIO_ROOT_USER", "mlplatform"),
            "s3.secret-access-key": os.environ.get("MINIO_ROOT_PASSWORD", "local-only-not-a-secret"),
        },
    )


#: The one variable that decides which catalogue a process talks to.
CATALOG_VARIABLE = "LAKEHOUSE_CATALOG"

#: Catalogues with no adapter yet. Named, so asking for one fails with a
#: sentence about what is missing rather than falling back to a laptop.
_PLANNED = {"glue": "AWS Glue", "biglake": "GCP BigLake"}


def catalog_from_environment() -> Catalog:
    """The catalogue this process is configured for, or a refusal.

    **Why this exists (QA-4 F-23).** Every public function here used to take
    `catalog: Catalog | None = None` and fall back to :func:`local_catalog` —
    a MinIO on localhost with a literal credential. The Airflow DAG called
    `write_demand(...)` and `read_demand()` with no catalogue at all, so
    wherever it ran it wrote to and read from a laptop's object store, and in a
    cloud deployment the first symptom would have been a connection error that
    reads as the network being down.

    Now the catalogue is a required argument and this is how a process that
    does not construct one chooses it: from `LAKEHOUSE_CATALOG`, declared, with
    no default. Unset is a refusal, because the only safe default for "which
    warehouse am I writing to" is none.

    Raises:
        RuntimeError: If `LAKEHOUSE_CATALOG` is unset or blank.
        NotImplementedError: If it names a cloud catalogue with no adapter yet.
        ValueError: If it names anything else.
    """
    choice = os.environ.get(CATALOG_VARIABLE, "").strip().lower()
    if not choice:
        raise RuntimeError(
            f"{CATALOG_VARIABLE} is unset, so there is no catalogue to use. Nothing falls back to a local one: "
            f"a pipeline that silently writes to localhost looks, from the cloud, like a network failure. "
            f"Set {CATALOG_VARIABLE}=local for the local stack."
        )
    if choice == "local":
        return local_catalog()
    if choice in _PLANNED:
        raise NotImplementedError(
            f"{CATALOG_VARIABLE}={choice} ({_PLANNED[choice]}) has no adapter yet. The table format is identical "
            f"everywhere; the catalogue that points at it is cloud work that has not been written."
        )
    raise ValueError(
        f"{CATALOG_VARIABLE}={choice!r} is not a catalogue this code knows. Supported: local. "
        f"Planned, not built: {', '.join(sorted(_PLANNED))}."
    )


def ensure_table(catalog: Catalog) -> Table:
    """Create the table if absent, otherwise return the existing one.

    Idempotent on purpose: an ingestion that must be told whether it is the
    first run is one that behaves differently on a rerun, and a rerun is the
    normal case after a failure.
    """
    catalog.create_namespace_if_not_exists(NAMESPACE)
    try:
        return catalog.load_table(QUALIFIED)
    except NoSuchTableError:
        return catalog.create_table(QUALIFIED, schema=DEMAND_SCHEMA, partition_spec=DEMAND_PARTITION)


def _to_arrow(demand: pl.DataFrame) -> pa.Table:
    """Convert to the exact Arrow types the Iceberg schema declares.

    Polars produces ns-precision timestamps and its own integer widths; Iceberg
    declares us-precision and specific widths. Letting the conversion happen
    implicitly is how a write succeeds with a silently different type, which
    then reads back wrong.
    """
    arrow = demand.select(
        pl.col("zone_id").cast(pl.Int32),
        pl.col("event_time").cast(pl.Datetime("us")),
        pl.col("trip_count").cast(pl.Int64),
        pl.col("mean_distance").cast(pl.Float64),
        pl.col("total_fare").cast(pl.Float64),
    ).to_arrow()
    return arrow.cast(DEMAND_SCHEMA.as_arrow())


def _months_present(demand: pl.DataFrame) -> list[datetime]:
    """First instant of every month appearing in ``demand``, ascending.

    Months are enumerated individually rather than spanned min-to-max: data
    covering January and March must not delete February, and a gap like that
    is normal when a backfill re-ingests a non-contiguous set of files.
    """
    starts = demand.select(pl.col("event_time").dt.truncate("1mo").unique().sort()).to_series().to_list()
    return [datetime(start.year, start.month, 1) for start in starts]


def overwrite_filter(demand: pl.DataFrame) -> str:
    """A predicate matching exactly the months the incoming data covers.

    Without this, ``Table.overwrite`` defaults to ``AlwaysTrue()`` and deletes
    every data file in the table before writing. A backfill of one month
    against a year of history would silently destroy the other eleven, when the
    caller asked only to replace what it was re-ingesting.

    Returned as a string because pyiceberg accepts either that or a
    ``BooleanExpression``, and the string form is checkable without a
    catalogue — which is what lets this be a unit test rather than an
    integration one that never runs in CI.
    """
    clauses = [
        f"(event_time >= '{month.isoformat()}' and event_time < '{_next_month(month).isoformat()}')"
        for month in _months_present(demand)
    ]
    return " or ".join(clauses)


def _next_month(month: datetime) -> datetime:
    return datetime(month.year + (month.month == 12), (month.month % 12) + 1, 1)


def write_demand(demand: pl.DataFrame, catalog: Catalog, *, overwrite: bool = False) -> WriteResult:
    """Write hourly demand, returning the snapshot it created.

    Args:
        demand: Output of :func:`demand_forecast.ingest.to_hourly_demand`.
        catalog: Defaults to the local MinIO-backed catalogue.
        overwrite: Replace the months present in ``demand`` instead of
            appending to them. Use for a backfill of a month already present;
            appending there would double every count silently. Months NOT
            present in ``demand`` are left untouched.

    Returns:
        A :class:`WriteResult` carrying the snapshot id.

    Raises:
        ValueError: If ``overwrite`` is requested with an empty frame. The
            months to replace are derived from the data, so an empty frame
            names no scope — and the pyiceberg default for "no scope" is
            "every row in the table".
    """
    if overwrite and demand.is_empty():
        raise ValueError("overwrite requires a non-empty frame: an empty one selects no months to replace")

    table = ensure_table(catalog)
    arrow = _to_arrow(demand)
    head = table.metadata.current_snapshot_id

    if overwrite:
        table.overwrite(arrow, overwrite_filter=overwrite_filter(demand))
    else:
        table.append(arrow)

    snapshot_id = _committed_head(table, head)
    if snapshot_id is None:
        # Not an assert: `python -O` strips those, and this guards the one
        # value the caller uses to find the data again. A stripped guard
        # returns a WriteResult with no snapshot id and no complaint.
        raise RuntimeError("a write produced no snapshot; the table did not commit")
    return WriteResult(snapshot_id=snapshot_id, rows=demand.height, mode="overwrite" if overwrite else "append")


def _committed_head(table: Table, head: int | None) -> int | None:
    """The snapshot THIS table object's last commit produced, or None if it produced none.

    Read from the metadata the commit itself returned — pyiceberg replaces
    ``table.metadata`` with the catalogue's commit response — and NOT from a
    ``refresh()``. A refresh reads the catalogue's head at that moment, and
    another writer (a manual ingest, a second DAG run) can commit between this
    commit and that read; the caller would then validate, train on and record
    the other writer's snapshot, rows included. QA-4 round sixteen forced
    exactly that interleaving and got the other writer's id back.

    ``head`` is the snapshot the table stood at before the operation. An
    operation that commits nothing leaves the head where it was, and reporting
    that id would label the previous write's snapshot as this one's.
    """
    current = table.metadata.current_snapshot_id
    return None if current is None or current == head else current


def read_demand(catalog: Catalog, *, snapshot_id: int | None = None) -> pl.DataFrame:
    """Read the table, optionally as it stood at a given snapshot.

    ``snapshot_id`` is the time-travel path. Passing the id recorded in a model
    card reconstructs that model's exact training input — which is what makes
    "retrain on the data as of date D" mechanical instead of archaeological.
    """
    table = ensure_table(catalog)
    scan = table.scan(snapshot_id=snapshot_id) if snapshot_id is not None else table.scan()
    return pl.from_arrow(scan.to_arrow())  # type: ignore[return-value]


def snapshots(catalog: Catalog) -> list[tuple[int, datetime]]:
    """Every snapshot, newest last, as ``(id, committed_at)`` in UTC.

    Timezone-aware deliberately: a naive local-time timestamp compared
    against anything else in this repository — all of which is UTC — is
    wrong by the local offset without ever raising.
    """
    table = ensure_table(catalog)
    return [(s.snapshot_id, datetime.fromtimestamp(s.timestamp_ms / 1000, tz=UTC)) for s in table.metadata.snapshots]


def delete_before(cutoff: datetime, catalog: Catalog) -> WriteResult | None:
    """Delete rows whose ``event_time`` precedes ``cutoff``.

    The operation that exists because fixing an ingest does NOT clean what the
    ingest already stored. `write_demand(overwrite=True)` is scoped to the
    months present in the incoming data — deliberately, so a backfill of one
    month cannot destroy the others — which means rows stamped outside every
    ingested month survive a full reingestion untouched. Sixteen pickups
    stamped 2002-2009 did exactly that.

    Reversible, and that is the point of doing it here rather than by rewriting
    files: Iceberg records the delete as a new snapshot, so the previous state
    stays readable through `read_demand(snapshot_id=...)` until snapshots are
    expired. Expiring them is the irreversible step, which is why the agent
    protocol makes EXPIRY a STOP operation and this one merely CONSULT.

    Args:
        cutoff: Rows strictly before this instant are removed. Naive values
            are read as UTC, as ``event_time`` is stored; aware values are
            converted to it. :func:`snapshots` and ``datetime.now(UTC)`` both
            give aware instants, and the column is a naive timestamp, so
            passing one straight to pyiceberg raised ("Zone offset provided,
            but not expected") — round sixteen.
        catalog: Defaults to the local MinIO-backed catalogue.

    Returns:
        A :class:`WriteResult` naming the snapshot the delete produced, or
        ``None`` when no row precedes ``cutoff``. Iceberg commits no snapshot
        for a delete that matches nothing, and this used to return the
        previous write's snapshot labelled ``delete`` — a citation of an
        operation that did not happen.
    """
    if cutoff.tzinfo is not None:
        cutoff = cutoff.astimezone(UTC).replace(tzinfo=None)

    table = ensure_table(catalog)
    head = table.metadata.current_snapshot_id

    table.delete(delete_filter=f"event_time < '{cutoff.isoformat()}'")

    snapshot_id = _committed_head(table, head)
    if snapshot_id is None:
        return None
    return WriteResult(snapshot_id=snapshot_id, rows=_rows_removed(table, snapshot_id), mode="delete")


def _rows_removed(table: Table, snapshot_id: int) -> int:
    """Rows the delete's own snapshot removed, from the summary Iceberg wrote for it.

    Not "rows at the head we loaded minus rows now". pyiceberg retries a commit
    that lost a race ON TOP of the other writer's snapshot, so between the head
    this function loaded and the snapshot it committed sit the other writer's
    rows — QA-4 round seventeen forced that interleaving and got "delete -3
    rows" where 4 were deleted. The snapshot's summary counts only what this
    commit did: `deleted-records` from the files it dropped or rewrote, less
    `added-records` it wrote back when a file straddled the cutoff.

    pyiceberg 0.12 commits a delete as ONE snapshot, measured for whole-file
    and partial deletes; `tests/test_lakehouse.py` holds that, so a release
    that splits it fails a test instead of undercounting here.
    """
    snapshot = table.snapshot_by_id(snapshot_id)
    summary = snapshot.summary if snapshot is not None else None
    if summary is None or "deleted-records" not in summary.additional_properties:
        raise RuntimeError(f"snapshot {snapshot_id} records no deleted-records; the delete cannot be counted")
    properties = summary.additional_properties
    return int(properties["deleted-records"]) - int(properties.get("added-records", 0))
