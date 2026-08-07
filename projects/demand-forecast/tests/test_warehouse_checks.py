"""Each warehouse expectation must fail on the thing it exists to catch.

A suite that passes on the current table proves only that the table is
currently fine. Every expectation here is therefore shown failing against an
injected defect, because the first version of the timestamp expectation took
its bounds from `expected_window(demand)` — the min and max of the very column
it validated — and so passed on a table containing pickups stamped 2002. A
range derived from a column contains every value in that column by
construction.

That is the same defect an independent audit found in the MCP registry gate
three weeks earlier: a threshold supplied by the thing it judges. Finding it
again, in new code, is why these tests assert failure rather than success.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest
from demand_forecast.warehouse_checks import (
    FEED_EPOCH,
    MAX_TRIPS_PER_ZONE_HOUR,
    check_density,
    validate_warehouse,
)


def _table(hours: int = 400, zones: int = 3) -> pl.DataFrame:
    rows = []
    for zone in range(1, zones + 1):
        rows.append(
            pl.DataFrame(
                {
                    "zone_id": [zone] * hours,
                    "event_time": [datetime(2024, 1, 1) + timedelta(hours=i) for i in range(hours)],
                    "trip_count": [10 + zone] * hours,
                    "mean_distance": [2.5] * hours,
                    "total_fare": [18.0] * hours,
                }
            )
        )
    return pl.concat(rows)


def test_a_clean_table_passes() -> None:
    """The baseline. Without it, every failure below could be a broken suite."""
    result = validate_warehouse(_table())
    assert result.success, result
    assert result.checked == 5


def test_a_duplicated_load_is_caught() -> None:
    """The defect no per-frame contract can see.

    `write_demand` appends by default, so running an ingestion twice doubles
    every count while every individual row remains valid.
    """
    doubled = pl.concat([_table(), _table()])
    result = validate_warehouse(doubled)

    assert not result.success
    assert "expect_compound_columns_to_be_unique" in result.failed


def test_a_corrupt_timestamp_is_caught() -> None:
    """The regression for the circular bound.

    One row stamped 2002 among 1,200 clean ones. It satisfies every column
    bound, which is exactly how 33 of them reached the real warehouse at a
    0.00% reject rate.
    """
    table = _table()
    corrupt = table.head(1).with_columns(pl.lit(datetime(2002, 12, 31, 22)).alias("event_time"))
    result = validate_warehouse(pl.concat([table, corrupt]))

    assert not result.success, "a 2002 pickup passed; the bound is derived from the data again"


def test_a_future_timestamp_is_caught() -> None:
    """The other end of the same bound, which a data-derived range never checks."""
    table = _table()
    future = table.head(1).with_columns(pl.lit(datetime.now() + timedelta(days=400)).alias("event_time"))
    result = validate_warehouse(pl.concat([table, future]))

    assert not result.success


def test_an_implausible_count_is_caught() -> None:
    table = _table()
    spike = table.head(1).with_columns(pl.lit(MAX_TRIPS_PER_ZONE_HOUR * 10).cast(pl.Int64).alias("trip_count"))
    result = validate_warehouse(pl.concat([table, spike]))

    assert not result.success
    assert "expect_column_values_to_be_between" in result.failed


def test_an_out_of_range_zone_is_caught() -> None:
    """TLC publishes 265 zones; anything else is a join against the wrong lookup."""
    table = _table()
    bad_zone = table.head(1).with_columns(pl.lit(9999).cast(table.schema["zone_id"]).alias("zone_id"))
    result = validate_warehouse(pl.concat([table, bad_zone]))

    assert not result.success


def test_a_null_target_is_caught() -> None:
    table = _table()
    nulled = table.head(1).with_columns(pl.lit(None).cast(pl.Int64).alias("trip_count"))
    result = validate_warehouse(pl.concat([table, nulled]))

    assert not result.success
    assert "expect_column_values_to_not_be_null" in result.failed


def test_the_bounds_are_not_read_from_the_table() -> None:
    """The property directly, not only through its symptom.

    Asserting only that a 2002 row fails would let someone reintroduce a
    data-derived bound and satisfy the test by coincidence on some other
    fixture. The floor is a constant, and it must stay one.
    """
    assert isinstance(FEED_EPOCH, datetime)
    assert datetime(2009, 1, 1) == FEED_EPOCH


# --- density: a shape the rows collectively have ----------------------------


def test_a_contiguous_table_is_dense() -> None:
    ok, density = check_density(_table())
    assert ok
    assert density == pytest.approx(1.0)


def test_one_outlier_timestamp_collapses_density() -> None:
    """The signature of a corrupt stamp, needing no configured window.

    The span stretches by decades while the distinct-hour count barely moves.
    This is what an earlier `check_coverage` was reaching for: it counted
    (zone, hour) cells against the span, so a table of quiet zones and a table
    with corrupt stamps both scored low and could not be told apart.
    """
    table = _table()
    outlier = table.head(1).with_columns(pl.lit(datetime(2009, 1, 1)).alias("event_time"))

    ok, density = check_density(pl.concat([table, outlier]))
    assert not ok
    assert density < 0.01
