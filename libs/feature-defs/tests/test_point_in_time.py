"""Point-in-time correctness, demonstrated rather than asserted.

The technical plan requires this as EVIDENCE: the naive join must be shown to
leak, not described as leaking. `test_naive_join_leaks_future_information` is
the one that matters — if it ever passes, the leakage detector has stopped
detecting and every other test here becomes meaningless.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest
from feature_defs.point_in_time import as_of_join, detect_leakage, naive_join

BASE = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def events() -> pl.DataFrame:
    """Two labelled events for one entity, an hour apart."""
    return pl.DataFrame(
        {
            "zone_id": ["A", "A", "B"],
            "event_time": [BASE, BASE + timedelta(hours=1), BASE],
            "label": [10.0, 20.0, 30.0],
        }
    )


@pytest.fixture
def features() -> pl.DataFrame:
    """Feature history straddling the events, including a FUTURE value.

    The last row for zone A is timestamped after both events. A naive join
    attaches it to them; a correct one never can.
    """
    return pl.DataFrame(
        {
            "zone_id": ["A", "A", "A", "B"],
            "feature_time": [
                BASE - timedelta(hours=1),  # before both events
                BASE + timedelta(minutes=30),  # between them
                BASE + timedelta(hours=5),  # AFTER both — the trap
                BASE - timedelta(hours=1),
            ],
            "rolling_demand": [1.0, 2.0, 999.0, 5.0],
        }
    )


# --- the correct path -------------------------------------------------------


def test_as_of_join_never_attaches_a_future_value(events: pl.DataFrame, features: pl.DataFrame) -> None:
    """The property the whole module exists to provide.

    Failure looks like: a training row for a 12:00 event carrying a feature
    computed at 17:00. Validation improves, production collapses, and the cause
    is several transformations from the symptom.
    """
    joined = as_of_join(events, features, entity="zone_id")

    assert detect_leakage(joined).is_clean
    assert 999.0 not in joined["rolling_demand"].to_list(), "the future value was attached"


def test_as_of_join_picks_the_most_recent_prior_value(events: pl.DataFrame, features: pl.DataFrame) -> None:
    """Most recent AT OR BEFORE — not merely any earlier value.

    Failure looks like: silently taking the oldest match, so the features are
    correct in the leakage sense and stale in every other one.
    """
    joined = as_of_join(events, features, entity="zone_id").sort(["zone_id", "event_time"])
    # Keyed on the PAIR: two entities share the BASE instant, and keying on
    # time alone silently collapses them — which is how this test first failed.
    values = {
        (zone, time): value
        for zone, time, value in zip(
            joined["zone_id"].to_list(),
            joined["event_time"].to_list(),
            joined["rolling_demand"].to_list(),
            strict=True,
        )
    }

    # The 12:00 event predates the 12:30 feature, so it must take the 11:00 one.
    assert values[("A", BASE)] == 1.0
    # The 13:00 event may take the 12:30 feature — the latest not in its future.
    assert values[("A", BASE + timedelta(hours=1))] == 2.0


def test_entities_do_not_borrow_each_others_features(events: pl.DataFrame, features: pl.DataFrame) -> None:
    """Cross-entity contamination is leakage of a different shape.

    Failure looks like: zone B's row carrying zone A's demand because the join
    ignored the entity key under some code path.
    """
    joined = as_of_join(events, features, entity="zone_id")
    zone_b = joined.filter(pl.col("zone_id") == "B")

    assert zone_b["rolling_demand"].to_list() == [5.0]


def test_unsorted_input_still_produces_a_correct_result(events: pl.DataFrame, features: pl.DataFrame) -> None:
    """An as-of join on unsorted input returns WRONG data, not an error.

    That combination — silently wrong — is why the function sorts internally
    instead of documenting a precondition the caller will eventually miss.
    """
    shuffled_events = events.sample(fraction=1.0, shuffle=True, seed=7)
    shuffled_features = features.sample(fraction=1.0, shuffle=True, seed=13)

    joined = as_of_join(shuffled_events, shuffled_features, entity="zone_id")

    assert detect_leakage(joined).is_clean
    assert 999.0 not in joined["rolling_demand"].to_list()


# --- the failure the plan requires demonstrated -----------------------------


def test_naive_join_leaks_future_information(events: pl.DataFrame, features: pl.DataFrame) -> None:
    """THE test. The naive join must leak, and be caught leaking.

    This is the evidence the technical plan requires for training-serving skew:
    the mistake demonstrated, not described. If this ever passes cleanly, the
    detector has stopped detecting and every other test in this file is
    vacuous.
    """
    joined = naive_join(events, features, entity="zone_id")
    report = detect_leakage(joined)

    assert not report.is_clean, (
        "the naive join must leak. If it no longer does, detect_leakage() is "
        "broken and the correctness tests above prove nothing."
    )
    assert report.leaking_rows >= 1
    # The trap value reached the training rows, which is the concrete harm.
    assert 999.0 in joined["rolling_demand"].to_list()
    # Five hours of future information, on an event an hour earlier.
    assert report.max_leak_seconds >= 4 * 3600


def test_the_two_joins_disagree(events: pl.DataFrame, features: pl.DataFrame) -> None:
    """If both joins agreed, the fixture would not exercise the difference.

    Guards the test data itself: a fixture where naive and correct coincide
    would let a broken as_of_join pass every assertion above.
    """
    correct = as_of_join(events, features, entity="zone_id").sort(["zone_id", "event_time"])
    leaky = naive_join(events, features, entity="zone_id").sort(["zone_id", "event_time"])

    assert correct["rolling_demand"].to_list() != leaky["rolling_demand"].to_list()


# --- the detector itself ----------------------------------------------------


def test_detector_reports_the_worst_offender() -> None:
    """A rate alone does not tell you whether it is a bug or a rounding edge."""
    frame = pl.DataFrame(
        {
            "event_time": [BASE, BASE],
            "feature_time": [BASE - timedelta(seconds=1), BASE + timedelta(hours=2)],
        }
    )
    report = detect_leakage(frame)

    assert report.leaking_rows == 1
    assert report.max_leak_seconds == pytest.approx(7200.0)
    assert report.leak_rate == pytest.approx(0.5)


def test_a_feature_exactly_at_the_event_time_is_not_leakage() -> None:
    """The boundary. "At or before" includes AT.

    Failure looks like: a strict comparison that discards a feature computed in
    the same instant as the event, quietly starving the model of its most
    recent legitimate input.
    """
    frame = pl.DataFrame({"event_time": [BASE], "feature_time": [BASE]})
    assert detect_leakage(frame).is_clean


def test_rows_with_no_matching_feature_are_not_counted_as_leakage() -> None:
    """A null feature is a coverage problem, not a leakage one.

    Conflating them sends whoever reads the report looking for a time-travel
    bug when the actual issue is a missing entity.
    """
    frame = pl.DataFrame(
        {"event_time": [BASE, BASE], "feature_time": [BASE - timedelta(hours=1), None]},
        schema={"event_time": pl.Datetime, "feature_time": pl.Datetime},
    )
    assert detect_leakage(frame).is_clean


def test_missing_columns_are_refused(events: pl.DataFrame, features: pl.DataFrame) -> None:
    with pytest.raises(ValueError, match="missing"):
        as_of_join(events.drop("event_time"), features, entity="zone_id")

    with pytest.raises(ValueError, match="must carry"):
        detect_leakage(events)
