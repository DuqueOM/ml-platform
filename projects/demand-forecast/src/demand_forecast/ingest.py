"""Ingest NYC TLC trips, validate at the boundary, aggregate to demand.

The trip-level work — validating, cleaning and aggregating a month — runs in
DuckDB, which streams and spills under a memory limit; the hourly panel it
produces is Polars' (ADR-011). Polars held the month in memory to validate it,
and peaked at 850-896 MB where DuckDB peaks at 293-297 MB. ADR-004 places
Spark at Demonstrated for the historical backfill only, and requires the
crossover threshold to be **measured** rather than asserted — see
:mod:`demand_forecast.crossover`.

Validation happens at ingest, not later. A contract enforced downstream reports
a violation after the bad rows have already entered three aggregates, and by
then the question is which of them to recompute.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import duckdb
import polars as pl
from data_contracts import ContractViolation
from data_contracts.duckdb_relation import admits, validate_relation
from duckdb import ColumnExpression, ConstantExpression, FunctionExpression

from demand_forecast.contracts.trips import TRIPS_RAW


@dataclass(frozen=True)
class IngestReport:
    """What one ingest run actually did.

    Attributes:
        source: File ingested.
        rows_read: Rows in the source.
        rows_written: Rows that survived validation and cleaning.
        violations: Contract violations found. Non-empty does not mean failure —
            see ``reject_rate``.
        reject_rate: Fraction of rows dropped. Reported because a run that
            silently discards 40% of its input is a different event from one
            that discards 0.01%, and both look like "success" without it.
    """

    source: str
    rows_read: int
    rows_written: int
    violations: list[ContractViolation]
    #: Rows dropped because the pickup fell outside the file's own month.
    #: Counted separately from ordinary cleaning: an out-of-month timestamp is
    #: a corrupt record, not a row that merely failed a bound, and it moves the
    #: series' apparent start by years.
    out_of_month: int = 0

    @property
    def reject_rate(self) -> float:
        return 1.0 - (self.rows_written / self.rows_read) if self.rows_read else 0.0

    def __str__(self) -> str:
        return (
            f"{self.source}: {self.rows_read:,} read, {self.rows_written:,} written "
            f"({self.reject_rate:.2%} rejected), {len(self.violations)} contract violation(s)"
            + (f", {self.out_of_month} out-of-month timestamp(s)" if self.out_of_month else "")
        )


#: A run dropping more than this is treated as a data incident rather than
#: routine cleaning. Chosen from the observed reject rate on 2024-01/02, which
#: is well under 1%: an order of magnitude above the normal rate is a change in
#: the data, not in the cleaning.
MAX_REJECT_RATE = 0.05


class IngestRejectedError(Exception):
    """Raised when a run would discard more rows than the contract tolerates."""


_MONTH_IN_NAME = re.compile(r"(\d{4})-(\d{2})")


def month_of(path: Path) -> tuple[datetime, datetime] | None:
    """The half-open month window a TLC file is supposed to contain.

    TLC publishes one file per month, named `yellow_tripdata_YYYY-MM.parquet`,
    so the file itself declares which hours are legitimate. Returns ``None``
    when the name carries no month — a caller with a differently-named file
    gets no bound rather than a wrong one.
    """
    match = _MONTH_IN_NAME.search(path.stem)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)
    return start, end


#: The memory DuckDB's buffer manager may hold during an ingest; past it, the
#: operators spill to a temporary directory rather than fail. Half the 512 MB
#: workload slice of the local stack's budget (`crossover.measure`'s default),
#: because the process also holds Python, the Arrow hand-off and the densified
#: panel. Measured on 2024-01 at this limit, the whole process peaked at
#: 293-297 MB; Polars, which held the month in memory to validate it, peaked at
#: 850-896 MB (ADR-011).
DUCKDB_MEMORY_LIMIT = "256MB"

#: The order rows had in the source. Every aggregate is summed in it: unordered,
#: a month's fare totals differed in their last digits from run to run, so the
#: same file did not produce the same panel twice (measured, ADR-011). It also
#: makes a violation's example the first one in the file, as Polars reports it.
_ROW = "file_row_number"

#: The hourly aggregate, in DuckDB's dialect. Static text — no value is ever
#: formatted into it; what varies (paths, bounds, the month) reaches DuckDB as
#: expressions or parameters.
_HOURLY = (
    "PULocationID AS zone_id, "
    "date_trunc('hour', tpep_pickup_datetime) AS event_time, "
    "count(*)::UINTEGER AS trip_count, "
    "avg(trip_distance ORDER BY file_row_number) AS mean_distance, "
    "sum(fare_amount ORDER BY file_row_number) AS total_fare"
)
_HOURLY_KEYS = "PULocationID, date_trunc('hour', tpep_pickup_datetime)"


@contextmanager
def _connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """A DuckDB connection bounded in memory, spilling to a private directory, with no way to fetch code.

    Extensions are neither autoloaded nor autoinstalled: an ingest that read an
    `s3://` path would otherwise download httpfs at run time — an unpinned
    binary from the network, which no lock or scan covers. The configuration is
    locked once set, so nothing later in the run can loosen it.
    """
    with tempfile.TemporaryDirectory(prefix="ingest-spill-") as spill:
        connection = duckdb.connect(
            config={
                "memory_limit": DUCKDB_MEMORY_LIMIT,
                "temp_directory": spill,
                "preserve_insertion_order": False,
                "autoload_known_extensions": False,
                "autoinstall_known_extensions": False,
            }
        )
        try:
            connection.execute("SET lock_configuration = true")
            yield connection
        finally:
            connection.close()


def _from_frame(connection: duckdb.DuckDBPyConnection, frame: pl.DataFrame) -> duckdb.DuckDBPyRelation:
    return connection.from_arrow(frame.with_row_index(_ROW).to_arrow())


def _count(relation: duckdb.DuckDBPyRelation) -> int:
    return int(relation.aggregate([FunctionExpression("count_star")]).fetchall()[0][0])


def _admitted(relation: duckdb.DuckDBPyRelation) -> duckdb.DuckDBPyRelation:
    """The rows the contract admits, and whose dropoff is not before their pickup.

    Derived from `TRIPS_RAW`, so the bounds that drop a row and the bounds that
    report a violation are one list. They were two: this function restated
    seven of the contract's eight rules by hand and left out `passenger_count`,
    whose bounds the contract declares. Measured on 2024-01/02, no row has a
    `passenger_count` outside them, so the panel is unchanged — the next feed
    that carries one is now held to the contract it is reported against.

    Dropoff before pickup is a clock error, not a short trip; it stays out of
    the contract because it is a RELATION between columns, which a per-column
    rule cannot express.
    """
    return relation.filter(
        admits(TRIPS_RAW) & (ColumnExpression("tpep_dropoff_datetime") >= ColumnExpression("tpep_pickup_datetime"))
    )


def _in_month(relation: duckdb.DuckDBPyRelation, window: tuple[datetime, datetime] | None) -> duckdb.DuckDBPyRelation:
    if window is None:
        return relation
    pickup = ColumnExpression("tpep_pickup_datetime")
    return relation.filter((pickup >= ConstantExpression(window[0])) & (pickup < ConstantExpression(window[1])))


def _observed_hourly(relation: duckdb.DuckDBPyRelation) -> pl.DataFrame:
    """Trips counted, averaged and summed per zone and hour — only the hours that had a trip."""
    return cast(pl.DataFrame, relation.aggregate(_HOURLY, _HOURLY_KEYS).pl())


def drop_out_of_month(frame: pl.DataFrame, window: tuple[datetime, datetime] | None) -> tuple[pl.DataFrame, int]:
    """Remove rows whose PICKUP falls outside the file's month.

    The real 2024-01/02 feed carries pickups stamped 2002, 2008 and 2009 — 18
    rows out of 151,920, or 0.012%. They are far below the reject-rate alarm,
    they pass every column bound, and they moved the observed start of the
    series from January 2024 to December 2002. Any backtest computing a span
    from min/max then reads a 21-year history that contains 60 days of data.

    Bounded on pickup only. A trip starting at 23:50 on the last day of the
    month and ending in the next is legitimate and belongs to this file.

    Returns:
        The filtered frame and the number of rows removed.
    """
    if window is None:
        return frame, 0
    with _connection() as connection:
        kept = _in_month(_from_frame(connection, frame), window).order(_ROW).project(*frame.columns).pl()
    return kept, frame.height - kept.height


def clean(frame: pl.DataFrame) -> pl.DataFrame:
    """Drop rows the contract cannot admit — the same rule the file ingest applies (see `_admitted`).

    Deliberately narrow: it removes rows that violate a BOUND, and does not
    impute, clip or otherwise invent values. Clipping an implausible distance
    to the maximum would keep the row and corrupt the aggregate it enters,
    which is harder to notice than a missing row.
    """
    with _connection() as connection:
        return cast(pl.DataFrame, _admitted(_from_frame(connection, frame)).order(_ROW).project(*frame.columns).pl())


def ingest_hourly(
    path: Path, *, strict: bool = True, limit_rows: int | None = None
) -> tuple[pl.DataFrame, IngestReport]:
    """Validate one month of trips, clean them, and aggregate them to hourly demand — without loading the month.

    Every step runs in DuckDB under `DUCKDB_MEMORY_LIMIT`, reading the file
    once per question it asks: the contract's violations
    (`data_contracts.duckdb_relation`, the same verdict `DataContract.validate`
    gives), the admitted rows, the month window, and the hourly aggregate. Only
    the aggregate reaches Python, where it is densified (ADR-011).

    Args:
        path: A TLC parquet file, local. With extensions off, a remote URL is
            refused rather than fetched (see `_connection`).
        strict: Raise when the reject rate exceeds :data:`MAX_REJECT_RATE`.
        limit_rows: Read only the file's first rows, in file order — for a
            measurement at increasing scale (`crossover.measure`), never for
            a production run.

    Returns:
        The dense hourly panel and a report of what happened.

    Raises:
        IngestRejectedError: If ``strict`` and too many rows were discarded.
    """
    with _connection() as connection:
        raw = connection.read_parquet(str(path), file_row_number=True)
        if limit_rows is not None:
            raw = raw.filter(ColumnExpression(_ROW) < ConstantExpression(limit_rows))
        # enforce is not an option here: the answer is a report, not a crash.
        # The contract describes a third-party feed that will violate it
        # occasionally, and the decision to stop belongs to the reject-rate
        # check below — which knows how MUCH is wrong, not merely that
        # something is.
        violations = validate_relation(TRIPS_RAW, raw, schema=pl.read_parquet_schema(path), order_by=_ROW)
        admitted = _admitted(raw)
        kept = _in_month(admitted, month_of(path))
        rows_read, rows_admitted, rows_kept = _count(raw), _count(admitted), _count(kept)
        observed = _observed_hourly(kept)

    report = IngestReport(
        source=path.name,
        rows_read=rows_read,
        rows_written=rows_kept,
        violations=violations,
        out_of_month=rows_admitted - rows_kept,
    )
    if strict and report.reject_rate > MAX_REJECT_RATE:
        raise IngestRejectedError(
            f"{report}\nReject rate exceeds {MAX_REJECT_RATE:.0%}. This is a change in the "
            f"data, not in the cleaning — investigate the source before widening the bound."
        )
    return _panel(observed), report


def _panel(observed: pl.DataFrame) -> pl.DataFrame:
    if observed.is_empty():
        return observed.sort(["zone_id", "event_time"])
    return densify(observed)


def to_hourly_demand(trips: pl.DataFrame) -> pl.DataFrame:
    """Aggregate trips to demand per zone per hour — the modelling target.

    The pickup timestamp is truncated to the hour, which makes the resulting
    ``event_time`` the START of the interval. That matters for point-in-time
    correctness downstream: a feature computed at 14:30 must not attach to the
    14:00 bucket, because at 14:00 it did not exist yet.

    **The result is a DENSE hourly grid per zone, and that is not cosmetic.**

    `group_by` emits a row only for hours that had a trip, so an hour with zero
    demand disappears. Everything downstream then counts ROWS where it means
    HOURS: `features.py` builds every lag with `shift(n).over(zone)` and the
    seasonal-naive baseline with `shift(168)`. On a sparse panel those are not
    "24 hours ago" and "same hour last week" — they are "24 rows ago" and "168
    rows ago", which reach back an arbitrary and varying distance.

    Measured on a synthetic panel with 40% of hours empty, before this fix:

        lag_24   -> median 41 h, p90 48 h, max 62 h
        shift(168) -> median 286 h, max 304 h

    It is not leakage — every value still comes from the past — and that is
    what makes it hard to see. It is a units error, and it flatters the model:
    the seasonal baseline degrades faster than the model does, so reported
    skill inflates. This repository's own trail shows the shape, +12.2% skill
    on synthetic data against +55.8% on real data, and the synthetic fixture in
    `test_training.py` is a perfectly contiguous grid, which is why no test
    could see it.

    Re-measured after this fix, on the same two months and the same three-fold
    design that produced it, +55.8% became +23.0%. The inflation was real and
    it was large: the broken baseline was about twice as easy to beat.

    A zero-trip hour is also a real observation. Dropping it biases the model
    upward by training only on hours that happened to have demand.

    `mean_distance` stays NULL on a densified hour rather than 0.0: the mean of
    no trips is undefined, and writing zero would state that trips occurred and
    were short. `total_fare` is 0.0, which is the true sum of an empty set.
    """
    with _connection() as connection:
        observed = _observed_hourly(_from_frame(connection, trips))
    return _panel(observed)


def densify(demand: pl.DataFrame) -> pl.DataFrame:
    """Every hour of each zone's span, with the hours that had no trips as zero demand.

    Per zone, from its own first observed hour to its own last. A global
    calendar would invent zeros for a zone before it existed in the data, which
    is a different falsehood from the one being fixed.

    **Applied again wherever history is assembled, not only at ingest (F-19).**
    `to_hourly_demand` makes one month dense, and the training DAG ingests one
    month at a time, so a zone's quiet hours between its last trip of one month
    and its first of the next were never filled. On January and February 2024
    that left 345,804 rows where one grid over both months has 357,426, and the
    lag features — `shift(n).over(zone)` — read "n rows ago" across every month
    boundary, the units error this function exists to remove. The backtest
    measured on one grid, so the deployed path and the evaluated one differed:
    skill +11.9% against +12.4% on the same trips. `train.evaluate` and
    `persist.fit_final` densify the panel they are given, which is idempotent on
    a frame that is already dense.

    ``trip_count`` and ``total_fare`` are zero on a filled hour — the true count
    and sum of no trips. Every other column stays null: the mean of no trips is
    undefined, and writing zero would state that trips occurred.
    """
    if demand.is_empty() or "zone_id" not in demand.columns:
        return demand
    spans = demand.group_by("zone_id").agg(
        pl.col("event_time").min().alias("first_hour"),
        pl.col("event_time").max().alias("last_hour"),
    )
    grid = (
        spans.with_columns(
            pl.datetime_ranges(pl.col("first_hour"), pl.col("last_hour"), interval="1h").alias("event_time")
        )
        # `empty_as_null=False`: a zone with a single observed hour yields a
        # one-element range, never an empty one, so the two behaviours agree
        # here — pinned rather than inherited, because polars 2.0 changes the
        # default and a silent change to how rows appear is the kind of drift
        # this panel cannot afford.
        .explode("event_time", empty_as_null=False)
        .select("zone_id", pl.col("event_time").cast(demand.schema["event_time"]))
    )
    zeros = [
        pl.col(name).fill_null(0).cast(demand.schema[name])
        for name in ("trip_count", "total_fare")
        if name in demand.columns
    ]
    return (
        grid.join(demand, on=["zone_id", "event_time"], how="left").with_columns(zeros).sort(["zone_id", "event_time"])
    )
