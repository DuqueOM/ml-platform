"""Features for hourly demand, every one of them backward-looking.

The rule this module exists to hold: **a feature for hour *t* may read hour
*t - k* and nothing else.** Break it and the model learns from data that will
not exist at prediction time, the backtest reports a skill nobody gets, and
nothing raises — the frame still has the right shape and the right dtypes.

Two ways the rule gets broken quietly, both guarded here:

**A centred window.** `rolling_mean(window)` in most libraries is
backward-looking, but a centred one straddles *t* and leaks the future by half
a window. The rolling features here shift before aggregating, so the value at
*t* is computed from rows strictly before *t*.

**A statistic fitted on the whole series.** Standardising by the global mean, or
encoding a category by its overall target average, folds the test period into
every training row. Nothing here computes a statistic across the full frame;
whatever a model needs fitted is fitted inside the fold, in `train.py`.

`LONGEST_LAG` is exported because the backtest's gap must be at least this
large. A gap smaller than the feature window lets training reach into the test
window through the features while the timestamps look disjoint.
"""

from __future__ import annotations

import polars as pl

#: Lags in hours. 1 is the immediate past, 24 is the same hour yesterday, 168
#: the same hour last week — daily and weekly seasonality is what actually
#: drives ride demand, so these are chosen rather than swept.
LAGS = (1, 2, 3, 24, 168)

#: Rolling windows in hours, each computed over rows strictly before t.
WINDOWS = (24, 168)

#: The furthest back any feature reaches. The backtest gap must be at least
#: this, or training leaks into test through the feature window.
LONGEST_LAG = max(max(LAGS), max(WINDOWS))

FEATURE_COLUMNS = (
    [f"lag_{lag}" for lag in LAGS]
    + [f"roll_mean_{window}" for window in WINDOWS]
    + [f"roll_std_{window}" for window in WINDOWS]
    + ["hour", "day_of_week", "is_weekend"]
)


def build_features(demand: pl.DataFrame, *, entity: str = "zone_id") -> pl.DataFrame:
    """Attach backward-looking features to an hourly demand frame.

    Args:
        demand: Output of :func:`demand_forecast.ingest.to_hourly_demand`,
            carrying ``zone_id``, ``event_time`` and ``trip_count``.
        entity: Column identifying the series. Lags are computed WITHIN each
            entity: a lag that crosses a zone boundary attaches one zone's
            history to another's present, which is not leakage but is nonsense,
            and it does not show up in any aggregate metric.

    Returns:
        The frame sorted by ``(entity, event_time)`` with feature columns added
        and the first :data:`LONGEST_LAG` rows per entity dropped — those have
        no history, and imputing them invents the past.
    """
    ordered = demand.sort([entity, "event_time"])

    lag_exprs = [pl.col("trip_count").shift(lag).over(entity).alias(f"lag_{lag}") for lag in LAGS]

    rolling_exprs = []
    for window in WINDOWS:
        # shift(1) BEFORE rolling: without it the window includes row t itself,
        # so the mean of the last 24 hours contains the value being predicted.
        shifted = pl.col("trip_count").shift(1).over(entity)
        rolling_exprs.append(shifted.rolling_mean(window).over(entity).alias(f"roll_mean_{window}"))
        rolling_exprs.append(shifted.rolling_std(window).over(entity).alias(f"roll_std_{window}"))

    calendar_exprs = [
        pl.col("event_time").dt.hour().alias("hour"),
        pl.col("event_time").dt.weekday().alias("day_of_week"),
        (pl.col("event_time").dt.weekday() >= 6).cast(pl.Int8).alias("is_weekend"),
    ]

    featured = ordered.with_columns([*lag_exprs, *rolling_exprs, *calendar_exprs])

    # Rows without full history are dropped, not imputed. A filled lag is a
    # fabricated observation, and the model cannot tell it from a real one.
    return featured.drop_nulls(subset=[f"lag_{max(LAGS)}", f"roll_mean_{max(WINDOWS)}"])


def seasonal_naive(demand: pl.DataFrame, *, season: int = 168, entity: str = "zone_id") -> pl.Series:
    """The baseline every forecast must beat: last week, same hour.

    A model reported without a baseline cannot be judged. An MAE of 13 is
    excellent or embarrassing depending entirely on what repeating last week
    scores, and for hourly demand that is a genuinely strong reference —
    weekly seasonality dominates.

    Args:
        demand: Hourly demand, sorted or not.
        season: Hours back. 168 is one week; 24 is the weaker daily variant.
        entity: Series identifier, so the baseline does not cross zones.

    Returns:
        Predictions aligned to the sorted frame, null where no history exists.
    """
    return demand.sort([entity, "event_time"]).select(pl.col("trip_count").shift(season).over(entity))["trip_count"]
