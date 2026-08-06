"""Point-in-time correct feature retrieval.

When building a training set, each feature must take the value it had **at the
instant of the labelled event** — never a later value. Violating that is data
leakage, and it is the most expensive mistake in applied ML because it does not
look like a mistake: validation metrics improve.

The failure is asymmetric in a way that matters. A model with leakage reports
excellent offline performance and collapses in production, and by then the
leak is several transformations away from the symptom. Nothing in a normal test
suite catches it, because the code is correct — it is the *join semantics* that
are wrong.

So this module offers exactly two functions, one correct and one deliberately
wrong, and the test suite asserts that the wrong one leaks. A leakage guard
that has never been shown to fire is a guard nobody knows works.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class LeakageReport:
    """Evidence that a feature set does or does not contain future information.

    Attributes:
        total_rows: Rows examined.
        leaking_rows: Rows whose feature timestamp is AFTER the event.
        max_leak_seconds: The worst offender, in seconds into the future.
    """

    total_rows: int
    leaking_rows: int
    max_leak_seconds: float

    @property
    def is_clean(self) -> bool:
        return self.leaking_rows == 0

    @property
    def leak_rate(self) -> float:
        return self.leaking_rows / self.total_rows if self.total_rows else 0.0

    def __str__(self) -> str:
        if self.is_clean:
            return f"clean: no future information in {self.total_rows} rows"
        return (
            f"LEAKAGE: {self.leaking_rows}/{self.total_rows} rows ({self.leak_rate:.2%}) "
            f"carry future information, worst {self.max_leak_seconds:.0f}s ahead"
        )


def as_of_join(
    events: pl.DataFrame,
    features: pl.DataFrame,
    *,
    entity: str,
    event_time: str = "event_time",
    feature_time: str = "feature_time",
) -> pl.DataFrame:
    """Attach to each event the most recent feature value **at or before** it.

    This is the correct join for building a training set. For every event it
    finds the latest feature row for the same entity whose timestamp does not
    exceed the event's — so the training row contains only what was knowable
    when the event happened.

    Args:
        events: Labelled events. Must carry ``entity`` and ``event_time``.
        features: Feature history. Must carry ``entity`` and ``feature_time``.
        entity: Join key present in both frames.
        event_time: Timestamp column in ``events``.
        feature_time: Timestamp column in ``features``.

    Returns:
        One row per event, with the feature values as of that event.

    Raises:
        ValueError: If a required column is missing from either frame.
    """
    for frame, name, required in (
        (events, "events", (entity, event_time)),
        (features, "features", (entity, feature_time)),
    ):
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"{name} is missing {missing}")

    # join_asof requires both sides sorted by the join key. Sorting here rather
    # than trusting the caller: an unsorted input produces a WRONG result, not
    # an error, which is the worst combination.
    return events.sort([entity, event_time]).join_asof(
        features.sort([entity, feature_time]),
        left_on=event_time,
        right_on=feature_time,
        by=entity,
        strategy="backward",
        # Polars cannot verify sortedness across `by` groups and warns.
        # Suppressed because the precondition is satisfied two lines above,
        # not because the warning is inconvenient — the sort is the reason
        # it is safe to assert this.
        check_sortedness=False,
    )


def naive_join(
    events: pl.DataFrame,
    features: pl.DataFrame,
    *,
    entity: str,
) -> pl.DataFrame:
    """Join on the entity alone, ignoring time. **This leaks.**

    Kept in the library on purpose. It is the join everyone writes first, and
    the only way to prove a leakage detector works is to run it against
    something that actually leaks. Referenced by
    ``tests/test_point_in_time.py``; never call it from a pipeline.

    Attaching the entity's *latest* feature value to a historical event means
    the training row contains information from after the label was determined.
    """
    latest = features.sort("feature_time").group_by(entity).last()
    return events.join(latest, on=entity, how="left")


def detect_leakage(
    frame: pl.DataFrame, *, event_time: str = "event_time", feature_time: str = "feature_time"
) -> LeakageReport:
    """Report whether any row carries a feature timestamped after its event.

    This is the check that makes point-in-time correctness verifiable rather
    than asserted. It runs on the *joined* frame, so it catches the mistake
    regardless of which join produced it — including a hand-written one that
    never went through :func:`as_of_join`.
    """
    if event_time not in frame.columns or feature_time not in frame.columns:
        raise ValueError(f"frame must carry both {event_time!r} and {feature_time!r} to check for leakage")

    present = frame.drop_nulls([event_time, feature_time])
    if present.height == 0:
        return LeakageReport(total_rows=frame.height, leaking_rows=0, max_leak_seconds=0.0)

    leak_seconds = (
        present.select(((pl.col(feature_time) - pl.col(event_time)).dt.total_seconds()).alias("ahead"))
        .filter(pl.col("ahead") > 0)
        .get_column("ahead")
    )

    # Series.max() is typed as returning any Polars scalar; the column is
    # float64 by construction (a duration in seconds), so narrow explicitly
    # rather than suppressing the checker.
    worst = leak_seconds.max()
    return LeakageReport(
        total_rows=frame.height,
        leaking_rows=int(leak_seconds.len()),
        max_leak_seconds=float(worst) if isinstance(worst, (int, float)) else 0.0,
    )
