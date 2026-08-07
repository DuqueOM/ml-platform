"""Ingest NYC TLC trips, validate at the boundary, aggregate to demand.

The incremental path is DuckDB/Polars. ADR-004 places Spark at Demonstrated for
the historical backfill only, and requires the crossover threshold to be
**measured** rather than asserted — see :mod:`demand_forecast.crossover`.

Validation happens at ingest, not later. A contract enforced downstream reports
a violation after the bad rows have already entered three aggregates, and by
then the question is which of them to recompute.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl
from data_contracts import ContractViolation

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


def read_trips(path: Path) -> pl.LazyFrame:
    """Lazily read a TLC parquet file, projecting only contracted columns.

    Projection matters at this size: the feed carries 19 columns and the
    contract constrains 8. Reading all of them costs memory that the local
    validation budget does not have.
    """
    return pl.scan_parquet(path).select(TRIPS_RAW.columns)


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
    start, end = window
    kept = frame.filter(pl.col("tpep_pickup_datetime").is_between(start, end, closed="left"))
    return kept, frame.height - kept.height


def clean(frame: pl.DataFrame) -> pl.DataFrame:
    """Drop rows the contract cannot admit.

    Deliberately narrow: it removes rows that violate a BOUND, and does not
    impute, clip or otherwise invent values. Clipping an implausible distance
    to the maximum would keep the row and corrupt the aggregate it enters,
    which is harder to notice than a missing row.
    """
    return frame.filter(
        pl.col("tpep_pickup_datetime").is_not_null()
        & pl.col("tpep_dropoff_datetime").is_not_null()
        & pl.col("PULocationID").is_between(1, 265)
        & pl.col("DOLocationID").is_between(1, 265)
        & pl.col("trip_distance").is_between(0.0, 1000.0)
        & pl.col("fare_amount").is_between(-500.0, 5000.0)
        & pl.col("total_amount").is_between(-500.0, 5000.0)
        # Dropoff before pickup is a clock error, not a short trip. Kept out of
        # the contract because it is a RELATION between columns, which a
        # per-column rule cannot express.
        & (pl.col("tpep_dropoff_datetime") >= pl.col("tpep_pickup_datetime"))
    )


def ingest_file(path: Path, *, strict: bool = True) -> tuple[pl.DataFrame, IngestReport]:
    """Read, validate and clean one month of trips.

    Args:
        path: Parquet file from the TLC feed.
        strict: Raise when the reject rate exceeds :data:`MAX_REJECT_RATE`.

    Returns:
        The cleaned frame and a report of what happened.

    Raises:
        IngestRejectedError: If ``strict`` and too many rows were discarded.
    """
    raw = read_trips(path).collect()
    rows_read = raw.height

    # enforce=False: the answer here is a report, not a crash. The contract is
    # describing a third-party feed that will violate it occasionally, and the
    # decision to stop belongs to the reject-rate check below — which knows how
    # MUCH is wrong, not merely that something is.
    violations = TRIPS_RAW.validate(raw, enforce=False)
    cleaned = clean(raw)
    cleaned, out_of_month = drop_out_of_month(cleaned, month_of(path))

    report = IngestReport(
        source=path.name,
        rows_read=rows_read,
        rows_written=cleaned.height,
        violations=violations,
        out_of_month=out_of_month,
    )

    if strict and report.reject_rate > MAX_REJECT_RATE:
        raise IngestRejectedError(
            f"{report}\nReject rate exceeds {MAX_REJECT_RATE:.0%}. This is a change in the "
            f"data, not in the cleaning — investigate the source before widening the bound."
        )
    return cleaned, report


def to_hourly_demand(trips: pl.DataFrame) -> pl.DataFrame:
    """Aggregate trips to demand per zone per hour — the modelling target.

    The pickup timestamp is truncated to the hour, which makes the resulting
    ``event_time`` the START of the interval. That matters for point-in-time
    correctness downstream: a feature computed at 14:30 must not attach to the
    14:00 bucket, because at 14:00 it did not exist yet.
    """
    return (
        trips.with_columns(pl.col("tpep_pickup_datetime").dt.truncate("1h").alias("event_time"))
        .group_by(["PULocationID", "event_time"])
        .agg(
            pl.len().alias("trip_count"),
            pl.col("trip_distance").mean().alias("mean_distance"),
            pl.col("fare_amount").sum().alias("total_fare"),
        )
        .rename({"PULocationID": "zone_id"})
        .sort(["zone_id", "event_time"])
    )
