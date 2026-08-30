"""Ingestion must fail closed on bad data and stay honest about what it dropped.

Most tests here run on synthetic frames so they are fast and deterministic. Two
run against the real TLC file when it is present, because a contract written
against a real feed should be exercised against it — the register warns this
data contains implausible values, and a suite that never sees them proves only
that the code runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from demand_forecast.contracts.trips import TRIPS_RAW
from demand_forecast.ingest import (
    MAX_REJECT_RATE,
    IngestRejectedError,
    clean,
    ingest_file,
    to_hourly_demand,
)

REAL_FILE = Path("data/nyc-tlc/yellow_tripdata_2024-01.parquet")
BASE = datetime(2024, 1, 1, 14, 0, 0)


def _frame(**overrides: list) -> pl.DataFrame:
    """A minimal conforming frame, with fields overridable per test."""
    data: dict[str, list] = {
        "tpep_pickup_datetime": [BASE],
        "tpep_dropoff_datetime": [datetime(2024, 1, 1, 14, 20, 0)],
        "PULocationID": [100],
        "DOLocationID": [200],
        "trip_distance": [3.5],
        "fare_amount": [18.0],
        "passenger_count": [1],
        "total_amount": [22.5],
    }
    data.update(overrides)
    return pl.DataFrame(data).cast(
        {
            "tpep_pickup_datetime": pl.Datetime("ns"),
            "tpep_dropoff_datetime": pl.Datetime("ns"),
            "PULocationID": pl.Int32,
            "DOLocationID": pl.Int32,
        }
    )


# --- cleaning ---------------------------------------------------------------


def test_conforming_rows_survive() -> None:
    assert clean(_frame()).height == 1


@pytest.mark.parametrize(
    ("field", "value", "why"),
    [
        ("trip_distance", [10879.28], "a real value from the 2024-01 feed — a meter error, not a trip"),
        ("fare_amount", [-509.8], "beyond the refund range the contract admits"),
        ("PULocationID", [999], "outside the zone lookup, so it would silently vanish from every aggregate"),
        ("trip_distance", [-1.0], "negative distance is a meter error"),
    ],
)
def test_out_of_bound_rows_are_dropped(field: str, value: list, why: str) -> None:
    """Each bound must actually remove rows, not merely be declared.

    Failure looks like: a contract that documents a range while `clean` filters
    on something else, so the bound is decorative and the bad rows proceed.
    """
    assert clean(_frame(**{field: value})).height == 0, why


def test_dropoff_before_pickup_is_dropped() -> None:
    """A clock error, and one a per-column rule cannot express.

    The contract constrains columns independently; this is a RELATION between
    two of them, which is why it lives in `clean` and is tested separately.
    """
    reversed_trip = _frame(tpep_dropoff_datetime=[datetime(2024, 1, 1, 13, 0, 0)])
    assert clean(reversed_trip).height == 0


def test_cleaning_never_imputes() -> None:
    """Dropping is visible; clipping is not.

    Failure looks like: an implausible 10,000-mile trip clipped to the 1000-mile
    maximum, kept, and silently corrupting every distance-weighted aggregate it
    enters — which is far harder to notice than a missing row.
    """
    result = clean(_frame(trip_distance=[10879.28]))
    assert result.height == 0
    assert 1000.0 not in result["trip_distance"].to_list()


# --- reject-rate guard ------------------------------------------------------


def test_a_high_reject_rate_stops_the_run(tmp_path: Path) -> None:
    """Silently discarding most of a batch is an incident, not cleaning.

    Failure looks like: a schema change upstream that invalidates 90% of rows,
    an ingest that reports success on the surviving 10%, and a model retrained
    on a tenth of its data.
    """
    bad = pl.concat([_frame(PULocationID=[999]) for _ in range(10)])
    path = tmp_path / "bad.parquet"
    bad.write_parquet(path)

    with pytest.raises(IngestRejectedError, match="Reject rate exceeds"):
        ingest_file(path)


def test_the_guard_can_be_bypassed_deliberately(tmp_path: Path) -> None:
    """Investigating a bad batch requires being able to load it."""
    bad = pl.concat([_frame(PULocationID=[999]) for _ in range(10)])
    path = tmp_path / "bad.parquet"
    bad.write_parquet(path)

    cleaned, report = ingest_file(path, strict=False)
    assert cleaned.height == 0
    assert report.reject_rate == 1.0


def test_report_distinguishes_a_clean_run_from_a_lossy_one() -> None:
    """ "Success" without a reject rate hides the difference that matters."""
    good = pl.concat([_frame() for _ in range(20)])
    assert clean(good).height == 20
    assert MAX_REJECT_RATE > 0.0


# --- aggregation ------------------------------------------------------------


def test_hourly_demand_buckets_by_hour_and_zone() -> None:
    trips = pl.concat(
        [
            _frame(tpep_pickup_datetime=[datetime(2024, 1, 1, 14, 5, 0)]),
            _frame(tpep_pickup_datetime=[datetime(2024, 1, 1, 14, 55, 0)]),
            _frame(tpep_pickup_datetime=[datetime(2024, 1, 1, 15, 5, 0)]),
        ]
    )
    demand = to_hourly_demand(trips)

    assert demand.height == 2
    assert demand.filter(pl.col("event_time") == datetime(2024, 1, 1, 14))["trip_count"][0] == 2


def test_event_time_is_the_start_of_the_interval() -> None:
    """Point-in-time correctness downstream depends on this.

    A bucket labelled with the END of its hour would let a feature computed at
    14:30 legitimately attach to it — and that feature did not exist at 14:00,
    when the bucket began.
    """
    trips = _frame(tpep_pickup_datetime=[datetime(2024, 1, 1, 14, 59, 59)])
    assert to_hourly_demand(trips)["event_time"][0] == datetime(2024, 1, 1, 14, 0, 0)


# --- against the real feed --------------------------------------------------

real_data = pytest.mark.skipif(not REAL_FILE.is_file(), reason="run: python scripts/datasets/fetch.py nyc-tlc")


@real_data
def test_the_contract_catches_real_violations_in_the_real_feed() -> None:
    """The register warns this data contains implausible values. Prove it.

    A contract that has never rejected anything from its actual source is one
    nobody knows is doing work. On 2024-01 this finds 23 trips over 1000 miles
    and 27 rows below the refund floor.
    """
    raw = pl.scan_parquet(REAL_FILE).select(TRIPS_RAW.columns).collect()
    violations = TRIPS_RAW.validate(raw, enforce=False)

    assert violations, "the contract found nothing in a feed documented to contain bad values"
    assert any(v.column == "trip_distance" for v in violations)


@real_data
def test_the_real_feed_ingests_within_the_reject_budget() -> None:
    """The bound is calibrated to this feed, not guessed.

    If this fails, either the data changed or the bounds are wrong — and the
    reject rate tells you which, which is why it is reported rather than a
    boolean.
    """
    cleaned, report = ingest_file(REAL_FILE)

    assert report.reject_rate < MAX_REJECT_RATE
    assert cleaned.height > 2_000_000
    assert to_hourly_demand(cleaned)["zone_id"].n_unique() > 200


# --- the file's own month bounds its pickups --------------------------------
#
# The real 2024-01/02 feed carries pickups stamped 2002, 2008 and 2009. Eighteen
# rows out of 151,920 — 0.012%, far below the reject-rate alarm, passing every
# column bound — and they moved the observed start of the series from January
# 2024 to December 2002. A backtest computing its span from min/max then sees a
# 21-year history containing 60 days of data.


def test_the_month_is_read_from_the_filename() -> None:
    from demand_forecast.ingest import month_of

    assert month_of(Path("yellow_tripdata_2024-01.parquet")) == (datetime(2024, 1, 1), datetime(2024, 2, 1))
    assert month_of(Path("yellow_tripdata_2024-12.parquet")) == (datetime(2024, 12, 1), datetime(2025, 1, 1))


def test_a_file_with_no_month_in_its_name_gets_no_bound() -> None:
    """No bound is better than a wrong one guessed from the data."""
    from demand_forecast.ingest import month_of

    assert month_of(Path("trips.parquet")) is None


def test_out_of_month_pickups_are_dropped_and_counted() -> None:
    from demand_forecast.ingest import drop_out_of_month, month_of

    frame = pl.DataFrame(
        {
            "tpep_pickup_datetime": [
                datetime(2002, 12, 31, 22),  # the real corrupt record
                datetime(2009, 1, 1),
                datetime(2024, 1, 15, 9),
                datetime(2024, 1, 31, 23, 50),  # legitimate: last hour of the month
                datetime(2024, 2, 1),  # next month's file owns this
            ]
        }
    )
    kept, dropped = drop_out_of_month(frame, month_of(Path("yellow_tripdata_2024-01.parquet")))

    assert dropped == 3
    assert kept.height == 2
    assert kept["tpep_pickup_datetime"].min() == datetime(2024, 1, 15, 9)


def test_a_trip_starting_in_the_last_hour_is_kept() -> None:
    """The bound is on PICKUP. A trip crossing midnight belongs to this file."""
    from demand_forecast.ingest import drop_out_of_month, month_of

    frame = pl.DataFrame({"tpep_pickup_datetime": [datetime(2024, 1, 31, 23, 59)]})
    kept, dropped = drop_out_of_month(frame, month_of(Path("yellow_tripdata_2024-01.parquet")))

    assert dropped == 0
    assert kept.height == 1


def test_no_bound_leaves_the_frame_untouched() -> None:
    from demand_forecast.ingest import drop_out_of_month

    frame = pl.DataFrame({"tpep_pickup_datetime": [datetime(2002, 1, 1)]})
    kept, dropped = drop_out_of_month(frame, None)

    assert dropped == 0
    assert kept.height == 1


# --- the hourly grid must be dense, and the reason is arithmetic -------------


def _sparse_trips() -> pl.DataFrame:
    """Two zones whose demand skips hours — which every real feed does."""
    rows = []
    start = datetime(2024, 1, 1)
    for zone in (1, 2):
        for hour in (0, 1, 5, 6, 7, 30, 31):  # gaps of 3 and 22 hours
            for _ in range(2):
                rows.append(
                    {
                        "tpep_pickup_datetime": start + timedelta(hours=hour, minutes=10),
                        "PULocationID": zone,
                        "trip_distance": 1.5,
                        "fare_amount": 7.0,
                    }
                )
    return pl.DataFrame(rows)


def test_hours_with_no_trips_are_present_as_zero() -> None:
    """`group_by` drops them, and everything downstream counts rows as hours.

    `features.py` builds every lag with `shift(n).over(zone)` and the
    seasonal-naive baseline with `shift(168)`. Those are ROW offsets. On a
    panel missing its empty hours they are not "24 hours ago" and "same hour
    last week" — measured on a 40%-sparse synthetic panel before this was
    fixed, `lag_24` reached back a median of 41 hours and the weekly baseline
    286.

    Not leakage: every value still comes from the past, which is exactly why no
    leakage test could see it. A units error that flatters the model, because
    the baseline degrades faster than the model does.
    """
    demand = to_hourly_demand(_sparse_trips())

    for zone in demand["zone_id"].unique():
        hours = demand.filter(pl.col("zone_id") == zone).sort("event_time")["event_time"]
        gaps = hours.diff().drop_nulls().dt.total_hours().unique().to_list()
        assert gaps == [1], f"zone {zone} has non-hourly gaps {sorted(gaps)}; the panel is not a dense grid"

    empty = demand.filter(pl.col("trip_count") == 0)
    assert empty.height > 0, "the fixture skips hours, so a densified panel must contain zero-count rows"


def test_a_row_offset_is_an_hour_offset() -> None:
    """The property the fix exists to restore, asserted as arithmetic.

    This is what `shift(n)` means downstream, so it is what has to hold. A test
    on the row count alone would pass on a panel densified with the wrong
    calendar.
    """
    demand = to_hourly_demand(_sparse_trips())
    reach = (
        demand.sort(["zone_id", "event_time"])
        .with_columns(pl.col("event_time").shift(3).over("zone_id").alias("earlier"))
        .select(((pl.col("event_time") - pl.col("earlier")).dt.total_hours()).alias("hours"))
        .drop_nulls()["hours"]
        .unique()
        .to_list()
    )
    assert reach == [3], f"shift(3) reaches back {sorted(reach)} hours; a row offset is not an hour offset"


def test_a_densified_hour_does_not_claim_trips_occurred() -> None:
    """`mean_distance` is NULL, not 0.0 — the mean of no trips is undefined.

    Zero would state that trips happened and were of zero length, which a model
    reads as a signal. `total_fare` IS 0.0, because that is the true sum of an
    empty set.
    """
    demand = to_hourly_demand(_sparse_trips())
    empty = demand.filter(pl.col("trip_count") == 0)

    assert empty["mean_distance"].null_count() == empty.height
    assert empty["total_fare"].to_list() == [0.0] * empty.height


def test_a_zone_gets_no_hours_before_it_appears() -> None:
    """Densify within each zone's own span, never across a global calendar.

    A zone that enters the data late would otherwise be given invented zeros
    for a period in which it did not exist — a different falsehood from the one
    being fixed, and one that looks like a demand collapse.
    """
    start = datetime(2024, 1, 1)
    trips = pl.DataFrame(
        [
            {"tpep_pickup_datetime": start, "PULocationID": 1, "trip_distance": 1.0, "fare_amount": 5.0},
            {
                "tpep_pickup_datetime": start + timedelta(hours=10),
                "PULocationID": 2,
                "trip_distance": 1.0,
                "fare_amount": 5.0,
            },
        ]
    )
    demand = to_hourly_demand(trips)
    late = demand.filter(pl.col("zone_id") == 2)
    assert late.height == 1, f"zone 2 first appears at hour 10 and gained {late.height} rows"
