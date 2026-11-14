"""The DuckDB ingest produces the panel and the report the Polars ingest did — and the same bits every run.

ADR-011 moved validation, cleaning and aggregation into DuckDB so a month is
never held in memory (Polars peaked at 850-896 MB on one month, DuckDB at
293-297 MB). A faster ingest that reports a different reject rate, drops a
different row or yields a different hourly frame would change every number the
model card publishes, so this holds the new path to a Polars reference — the
previous implementation, kept here as the test's oracle — on a file that breaks
every rule the ingest applies.

Measured on the real 2024-01/02 files before this test was written: identical
schemas, identical zone/hour/count keys, identical reports with identical
violation examples, and fares within 4e-11.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import polars as pl
import pytest
from demand_forecast import ingest
from demand_forecast.contracts.trips import TRIPS_RAW
from demand_forecast.ingest import IngestReport, densify, ingest_hourly, month_of

START = datetime(2024, 1, 10, 0, 0, 0)


def _month(path: Path) -> Path:
    """A January file that breaks every rule: bounds, nulls, a relation, the month, and gaps between hours."""
    rows = 300
    pickups = [START + timedelta(minutes=37 * i) for i in range(rows)]
    frame = pl.DataFrame(
        {
            "tpep_pickup_datetime": pickups,
            "tpep_dropoff_datetime": [p + timedelta(minutes=9) for p in pickups],
            "PULocationID": [100 + i % 7 for i in range(rows)],
            "DOLocationID": [200 + i % 3 for i in range(rows)],
            "trip_distance": [0.3 + (i % 11) * 1.17 for i in range(rows)],
            "fare_amount": [4.5 + (i % 13) * 2.31 for i in range(rows)],
            "passenger_count": [None if i % 9 == 0 else i % 5 for i in range(rows)],
            "total_amount": [7.0 + (i % 13) * 2.31 for i in range(rows)],
        }
    )
    broken = {
        3: {"trip_distance": 10879.28},  # above the distance bound
        8: {"fare_amount": -509.8},  # below the refund floor
        13: {"PULocationID": 999},  # an unjoinable zone
        21: {"tpep_dropoff_datetime": START - timedelta(hours=1)},  # dropoff before pickup
        34: {"tpep_pickup_datetime": datetime(2009, 1, 1, 3)},  # out of the file's month
        55: {"tpep_pickup_datetime": None},  # a null event time
        89: {"passenger_count": 12},  # a nullable column out of its bounds
    }
    for index, values in broken.items():
        for column, value in values.items():
            frame = frame.with_columns(
                pl.when(pl.int_range(pl.len()) == index).then(pl.lit(value)).otherwise(pl.col(column)).alias(column)
            )
    frame.cast({"PULocationID": pl.Int32, "DOLocationID": pl.Int32}).write_parquet(path)
    return path


def _reference(path: Path) -> tuple[pl.DataFrame, IngestReport]:
    """The ingest as Polars ran it before ADR-011, rule for rule — the oracle, not production code."""
    raw = pl.read_parquet(path).select(TRIPS_RAW.columns)
    violations = TRIPS_RAW.validate(raw, enforce=False)
    admitted = raw.filter(
        pl.col("tpep_pickup_datetime").is_not_null()
        & pl.col("tpep_dropoff_datetime").is_not_null()
        & pl.col("PULocationID").is_between(1, 265)
        & pl.col("DOLocationID").is_between(1, 265)
        & pl.col("trip_distance").is_between(0.0, 1000.0)
        & pl.col("fare_amount").is_between(-500.0, 5000.0)
        & pl.col("total_amount").is_between(-500.0, 5000.0)
        & (pl.col("passenger_count").is_null() | pl.col("passenger_count").is_between(0, 9))
        & (pl.col("tpep_dropoff_datetime") >= pl.col("tpep_pickup_datetime"))
    )
    start, end = month_of(path)  # type: ignore[misc]
    kept = admitted.filter(pl.col("tpep_pickup_datetime").is_between(start, end, closed="left"))
    observed = (
        kept.with_columns(pl.col("tpep_pickup_datetime").dt.truncate("1h").alias("event_time"))
        .group_by(["PULocationID", "event_time"])
        .agg(
            pl.len().alias("trip_count"),
            pl.col("trip_distance").mean().alias("mean_distance"),
            pl.col("fare_amount").sum().alias("total_fare"),
        )
        .rename({"PULocationID": "zone_id"})
    )
    report = IngestReport(path.name, raw.height, kept.height, violations, admitted.height - kept.height)
    return densify(observed), report


@pytest.fixture
def month(tmp_path: Path) -> Path:
    return _month(tmp_path / "yellow_tripdata_2024-01.parquet")


def test_the_report_is_the_one_polars_gave(month: Path) -> None:
    _, report = ingest_hourly(month, strict=False)
    _, expected = _reference(month)
    assert report == expected
    assert report.out_of_month == 1
    assert report.rows_read - report.rows_written == 7, "every broken row is dropped, and only those"
    assert {v.column for v in report.violations} >= {"trip_distance", "fare_amount", "PULocationID", "passenger_count"}


def test_the_panel_is_the_one_polars_built(month: Path) -> None:
    panel, _ = ingest_hourly(month, strict=False)
    expected, _ = _reference(month)
    assert panel.schema == expected.schema
    keys = ["zone_id", "event_time", "trip_count"]
    assert panel.select(keys).equals(expected.select(keys))
    for column in ("mean_distance", "total_fare"):
        assert panel[column].is_null().equals(expected[column].is_null())
        assert (panel[column] - expected[column]).abs().max() < 1e-9  # type: ignore[operator]
    assert (panel["trip_count"] == 0).any(), "the probe has empty hours; the panel must be dense"


def test_every_float_aggregate_is_summed_in_file_order() -> None:
    """A 300-row probe cannot show the run-to-run drift a real month did, so the order is held by construction."""
    import re

    floats = re.findall(r"\b(avg|sum)\(([^)]*)\)", ingest._HOURLY)
    assert floats, "the aggregate has no float sums to order"
    for function, argument in floats:
        assert argument.endswith("ORDER BY file_row_number"), f"{function}({argument}) is summed in no fixed order"


def test_the_same_file_gives_the_same_bits_every_run(month: Path) -> None:
    """Unordered, a month's fare totals differed in their last digits from run to run (measured on 2024-01)."""
    first, _ = ingest_hourly(month, strict=False)
    for _ in range(3):
        again, _ = ingest_hourly(month, strict=False)
        assert again.equals(first)


def test_a_frame_and_its_file_are_cleaned_by_one_rule(month: Path) -> None:
    """`clean` on a frame and the file ingest share `_admitted`; neither restates a bound."""
    frame = pl.read_parquet(month).select(TRIPS_RAW.columns)
    cleaned = ingest.clean(frame)
    assert cleaned.schema == frame.schema
    assert cleaned.height == frame.height - 6, "six rows break a rule; the seventh is only out of the month"
    in_month, _ = ingest.drop_out_of_month(cleaned, month_of(month))
    assert ingest.to_hourly_demand(in_month).equals(ingest_hourly(month, strict=False)[0])


def test_the_first_rows_are_the_file_s_first_rows(month: Path) -> None:
    _, report = ingest_hourly(month, strict=False, limit_rows=30)
    assert report.rows_read == 30


def test_the_engine_cannot_fetch_code_or_loosen_its_limits() -> None:
    """Extensions off — an `s3://` read would download httpfs at run time — and the configuration locked."""
    with ingest._connection() as connection:
        settings = dict(
            connection.sql(
                "SELECT name, value FROM duckdb_settings() WHERE name IN "
                "('autoload_known_extensions', 'autoinstall_known_extensions', 'memory_limit', 'lock_configuration')"
            ).fetchall()
        )
        assert settings["autoload_known_extensions"] == "false"
        assert settings["autoinstall_known_extensions"] == "false"
        assert settings["lock_configuration"] == "true"
        assert settings["memory_limit"] != "", "no memory limit, so no spill before the process is killed"
        with pytest.raises(duckdb.Error, match="locked"):
            connection.execute("SET memory_limit = '8GB'")
    # The value ADR-011 measured against: half the local stack's 512 MB workload slice.
    assert ingest.DUCKDB_MEMORY_LIMIT == "256MB"
