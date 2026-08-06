"""The NYC TLC trip contract.

Written against the real schema — 19 columns, 2.96M rows for 2024-01 — not
against the documentation, which describes fields the files do not always
carry.

Every bound below has a rationale, because a bound without one is loosened by
whoever it first blocks. Several exist specifically because this dataset
contains them: the register warns that "some months contain implausible
coordinates and durations", and cleaning rules belong here rather than in
undocumented preprocessing.
"""

from __future__ import annotations

import polars as pl
from data_contracts import ColumnRule, Compatibility, DataContract

#: Valid NYC taxi zone identifiers. 264 zones plus 265 ("Outside of NYC") and
#: 264 ("Unknown"), which the feed genuinely uses.
_MAX_ZONE_ID = 265

TRIPS_RAW = DataContract(
    name="nyc_tlc_trips_raw",
    version="1.0.0",
    compatibility=Compatibility.BACKWARD,
    rules=[
        ColumnRule(
            name="tpep_pickup_datetime",
            dtype=pl.Datetime(time_unit="ns"),
            rationale=(
                "The event time. Everything downstream is point-in-time correct with "
                "respect to THIS column; a null here makes a row unusable rather than "
                "merely incomplete."
            ),
        ),
        ColumnRule(
            name="tpep_dropoff_datetime",
            dtype=pl.Datetime(time_unit="ns"),
            rationale="Needed to derive duration, which is a leakage-safe feature only when both ends are present.",
        ),
        ColumnRule(
            name="PULocationID",
            dtype=pl.Int32,
            minimum=1,
            maximum=_MAX_ZONE_ID,
            rationale=(
                "The entity key for demand forecasting. A zone outside 1-265 cannot join "
                "to the zone lookup, and an unjoinable key silently drops the row from "
                "every aggregate rather than raising."
            ),
        ),
        ColumnRule(
            name="DOLocationID",
            dtype=pl.Int32,
            minimum=1,
            maximum=_MAX_ZONE_ID,
            rationale="Same join constraint as pickup; used for origin-destination features.",
        ),
        ColumnRule(
            name="trip_distance",
            dtype=pl.Float64,
            minimum=0.0,
            maximum=1000.0,
            rationale=(
                "Zero is legitimate (a cancelled or immediately-ended trip). Negative is a "
                "meter error. Above 1000 miles is not a NYC taxi trip — the register warns "
                "this feed carries implausible values, and an unbounded distance skews every "
                "distance-weighted aggregate it enters."
            ),
        ),
        ColumnRule(
            name="fare_amount",
            dtype=pl.Float64,
            minimum=-500.0,
            maximum=5000.0,
            rationale=(
                "Negative fares are REAL in this feed: they are refunds and disputed trips. "
                "Excluding them would silently bias revenue features upward, so the contract "
                "admits them within a bound and the modelling decides how to treat them."
            ),
        ),
        ColumnRule(
            name="passenger_count",
            dtype=pl.Int64,
            nullable=True,
            minimum=0.0,
            maximum=9.0,
            rationale=(
                "Nullable because the feed genuinely omits it when the driver did not enter "
                "one. Treating that null as zero would invent a fact; the contract records "
                "that it is unknown."
            ),
        ),
        ColumnRule(
            name="total_amount",
            dtype=pl.Float64,
            minimum=-500.0,
            maximum=5000.0,
            rationale="Same refund reasoning as fare_amount.",
        ),
    ],
)
"""Raw trips as they arrive from the TLC feed.

BACKWARD compatible: the feed adds columns across years (Airport_fee appeared
later), and a consumer written against an older version must keep reading newer
files. Removing a column here would be BREAKING and requires a coordinated
migration — which is exactly the kind of change the compatibility field exists
to make someone declare out loud.
"""
