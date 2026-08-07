"""The overwrite predicate must name months, never everything.

`Table.overwrite(arrow)` with no filter defaults to `AlwaysTrue()`: pyiceberg
deletes every data file in the table and then writes the new rows. The public
docstring promised the opposite — "replace matching rows … use for a backfill
of a month already present" — so a backfill of January against a year of
history destroyed February through December, silently, and returned a snapshot
id as if it had worked.

The test that was supposed to cover this wrote one row, wrote it again with
`overwrite=True`, and asserted the table held one row. That assertion holds
just as well when the table is wiped first, so it distinguished nothing. It was
also marked `integration`, which means it is deselected by default and never
ran in CI at all.

These tests are deliberately UNIT tests. They assert the predicate, not the
round trip, so they run everywhere — including in the CI job where the
integration suite is deselected. An integration test that never executes is not
a safety net.
"""

from __future__ import annotations

import re
from datetime import datetime

import polars as pl
import pytest
from demand_forecast.lakehouse import _months_present, _next_month, overwrite_filter


def _frame(*timestamps: datetime) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_id": [1] * len(timestamps),
            "event_time": list(timestamps),
            "trip_count": [10] * len(timestamps),
            "mean_distance": [2.0] * len(timestamps),
            "total_fare": [15.0] * len(timestamps),
        }
    )


def test_filter_is_never_unconditional() -> None:
    """The regression guard for the data-loss defect itself.

    Anything that matches every row — an empty predicate, `AlwaysTrue`, `1=1` —
    reintroduces the bug in a form that still looks like a filter.
    """
    predicate = overwrite_filter(_frame(datetime(2024, 3, 1, 8)))

    assert predicate.strip(), "an empty predicate means AlwaysTrue: the whole table is deleted"
    assert "event_time" in predicate
    assert "alwaystrue" not in predicate.lower().replace(" ", "")


def test_filter_bounds_a_single_month_on_both_sides() -> None:
    """A half-open month range. An unbounded upper edge deletes the future."""
    predicate = overwrite_filter(_frame(datetime(2024, 3, 15, 8)))

    assert "event_time >= '2024-03-01T00:00:00'" in predicate
    assert "event_time < '2024-04-01T00:00:00'" in predicate


def test_non_contiguous_months_do_not_delete_the_gap() -> None:
    """January and March must not take February with them.

    A min-to-max span would, and a non-contiguous backfill is the normal case
    when re-ingesting a chosen set of source files.
    """
    predicate = overwrite_filter(_frame(datetime(2024, 1, 5), datetime(2024, 3, 5)))

    # Asserted on the LOWER bounds, not on substring presence: 2024-02-01 must
    # appear as January's exclusive upper edge, so `"2024-02-01" not in
    # predicate` would fail against correct output. The property that matters
    # is that no clause SELECTS February.
    selected = sorted(re.findall(r"event_time >= '([^']+)'", predicate))
    assert selected == ["2024-01-01T00:00:00", "2024-03-01T00:00:00"]
    assert " or " in predicate


def test_months_are_deduplicated_and_ordered() -> None:
    rows = _frame(datetime(2024, 5, 30), datetime(2024, 4, 1), datetime(2024, 5, 2))
    assert _months_present(rows) == [datetime(2024, 4, 1), datetime(2024, 5, 1)]


def test_december_rolls_into_the_next_year() -> None:
    """The off-by-one that turns an upper bound into month 13."""
    assert _next_month(datetime(2024, 12, 1)) == datetime(2025, 1, 1)
    assert _next_month(datetime(2024, 1, 1)) == datetime(2024, 2, 1)


def test_empty_frame_is_refused_rather_than_matching_everything() -> None:
    """An empty frame names no months, and "no scope" would mean "all rows".

    Failing loudly is the only safe reading: the caller asked to replace
    something and provided nothing to replace it with.
    """
    from demand_forecast.lakehouse import write_demand

    empty = _frame().clear()
    with pytest.raises(ValueError, match="non-empty"):
        write_demand(empty, catalog=object(), overwrite=True)  # type: ignore[arg-type]
