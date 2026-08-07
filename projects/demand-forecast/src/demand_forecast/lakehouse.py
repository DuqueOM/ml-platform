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
        rows: Rows written.
        mode: ``append`` or ``overwrite``.
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


def ensure_table(catalog: Catalog):  # type: ignore[no-untyped-def]
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


def write_demand(demand: pl.DataFrame, catalog: Catalog | None = None, *, overwrite: bool = False) -> WriteResult:
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

    table = ensure_table(catalog or local_catalog())
    arrow = _to_arrow(demand)

    if overwrite:
        table.overwrite(arrow, overwrite_filter=overwrite_filter(demand))
    else:
        table.append(arrow)

    table.refresh()
    snapshot = table.current_snapshot()
    assert snapshot is not None, "a write always produces a snapshot"
    return WriteResult(
        snapshot_id=snapshot.snapshot_id, rows=demand.height, mode="overwrite" if overwrite else "append"
    )


def read_demand(catalog: Catalog | None = None, *, snapshot_id: int | None = None) -> pl.DataFrame:
    """Read the table, optionally as it stood at a given snapshot.

    ``snapshot_id`` is the time-travel path. Passing the id recorded in a model
    card reconstructs that model's exact training input — which is what makes
    "retrain on the data as of date D" mechanical instead of archaeological.
    """
    table = ensure_table(catalog or local_catalog())
    scan = table.scan(snapshot_id=snapshot_id) if snapshot_id is not None else table.scan()
    return pl.from_arrow(scan.to_arrow())  # type: ignore[return-value]


def snapshots(catalog: Catalog | None = None) -> list[tuple[int, datetime]]:
    """Every snapshot, newest last, as ``(id, committed_at)`` in UTC.

    Timezone-aware deliberately: a naive local-time timestamp compared
    against anything else in this repository — all of which is UTC — is
    wrong by the local offset without ever raising.
    """
    table = ensure_table(catalog or local_catalog())
    return [(s.snapshot_id, datetime.fromtimestamp(s.timestamp_ms / 1000, tz=UTC)) for s in table.metadata.snapshots]


def delete_before(cutoff: datetime, catalog: Catalog | None = None) -> WriteResult:
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
        cutoff: Rows strictly before this instant are removed.
        catalog: Defaults to the local MinIO-backed catalogue.

    Returns:
        A :class:`WriteResult` naming the snapshot the delete produced.
    """
    table = ensure_table(catalog or local_catalog())
    before = len(table.scan().to_arrow())

    table.delete(delete_filter=f"event_time < '{cutoff.isoformat()}'")

    table.refresh()
    snapshot = table.current_snapshot()
    assert snapshot is not None, "a delete always produces a snapshot"
    after = len(table.scan().to_arrow())
    return WriteResult(snapshot_id=snapshot.snapshot_id, rows=before - after, mode="delete")
