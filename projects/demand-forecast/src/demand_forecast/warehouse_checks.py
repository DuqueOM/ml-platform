"""Great Expectations at the warehouse boundary — a different layer, not a second copy.

ADR-004 admits Great Expectations for one reason: Pandera-style contracts sit
at the *function* boundary and check a frame passing through, while this checks
the *table* that was stored. Restating the column bounds here would be a second
implementation of the same rule, and two implementations of one rule disagree
eventually — so every expectation in this suite checks something the ingest
contract structurally cannot.

What the contract cannot see:

**Duplicates.** A contract validates a frame in isolation. `write_demand`
appends by default, so running an ingestion twice doubles every count with no
row violating any bound. Only the stored table knows.

**Coverage.** A month can be present, contract-valid and half empty — an
interrupted load leaves 300 hours where 744 belong. Every surviving row is
fine; the table is not.

**Distribution.** Whether this month's demand resembles last month's is a
property of the table across time, invisible to a per-frame check.

**Corrupt-but-valid timestamps.** The 33 pickups stamped 2002-2009 passed every
column bound at 0.00% reject rate. The ingest now bounds them by filename; this
is the independent second layer, and it would have caught them without knowing
the file's name.

Data Docs are the other half of the argument (ADR-004): the suite is meant to
be readable by someone who does not read Python, which is why every expectation
carries a `meta.reason` in prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import great_expectations as gx
import polars as pl
from great_expectations.data_context import AbstractDataContext

#: Distinct hours present divided by the hours the table's span implies.
#: A contiguous load sits near 1.0; a single outlier timestamp collapses it,
#: because the span stretches by years while the hour count does not move.
MIN_HOUR_DENSITY = 0.90

#: The feed's plausible ceiling for one zone in one hour. Manhattan midtown
#: peaks in the low hundreds; an order of magnitude above that is a unit error
#: or a duplicated load, not a busy evening.
MAX_TRIPS_PER_ZONE_HOUR = 2000

#: The earliest hour the TLC yellow-taxi feed can legitimately describe. The
#: published series begins in 2009, so anything before it is a corrupt stamp
#: rather than old data.
#:
#: FIXED, not derived from the table. The first version of this expectation
#: took its bounds from `expected_window(demand)` — the min and max of the very
#: column it was validating — which is circular: every value lies inside its
#: own range, so it passed on a table containing pickups stamped 2002. A gate
#: whose threshold comes from the thing it judges cannot fail, which is the
#: same defect an independent audit found in the MCP registry gate, committed
#: again three weeks later.
FEED_EPOCH = datetime(2009, 1, 1)


@dataclass(frozen=True)
class WarehouseValidation:
    """The outcome, in terms a caller can gate on.

    Attributes:
        success: Whether every expectation held.
        failed: Names of the expectations that did not.
        checked: How many were evaluated.
        docs_path: Where Data Docs were written, when they were built.
    """

    success: bool
    failed: tuple[str, ...]
    checked: int
    docs_path: str | None = None

    def __str__(self) -> str:
        if self.success:
            return f"[warehouse] OK — {self.checked} expectation(s) held"
        return f"[warehouse] FAILED — {len(self.failed)} of {self.checked}: {', '.join(self.failed)}"


def expected_window(demand: pl.DataFrame) -> tuple[datetime, datetime]:
    """The months the table claims to cover, from the data itself.

    Derived rather than configured: a hardcoded window becomes wrong the first
    time a month is added, and a window nobody updates is a check nobody trusts.
    """
    return demand["event_time"].min(), demand["event_time"].max()  # type: ignore[return-value]


def build_suite(context: AbstractDataContext, demand: pl.DataFrame) -> gx.ExpectationSuite:
    """Declare the expectations, each with a prose reason.

    `meta.reason` is not decoration. Data Docs render it, and the audience ADR-004
    names for those docs is someone who will never read this file — an
    expectation they cannot interpret is one they will ask an engineer about,
    which removes the reason for publishing them.
    """
    suite = gx.ExpectationSuite(name="hourly_demand_warehouse")

    suite.add_expectation(
        gx.expectations.ExpectCompoundColumnsToBeUnique(
            column_list=["zone_id", "event_time"],
            meta={
                "reason": (
                    "One row per zone per hour. write_demand appends by default, so "
                    "re-running an ingestion doubles every count without any single row "
                    "breaking a rule. Only the stored table can see this."
                )
            },
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="event_time",
            min_value=FEED_EPOCH,
            max_value=datetime.now(),
            meta={
                "reason": (
                    "The TLC yellow-taxi series begins in 2009, and no legitimate pickup is in "
                    "the future. The feed ships stamps from 2002 that satisfy every column "
                    "bound at a 0.00% reject rate and move the series' apparent start by 21 "
                    "years. Bounds are FIXED, not read from the table — a range derived from "
                    "the column it validates contains every value in it by construction."
                )
            },
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="trip_count",
            min_value=0,
            max_value=MAX_TRIPS_PER_ZONE_HOUR,
            meta={
                "reason": (
                    f"A zone-hour above {MAX_TRIPS_PER_ZONE_HOUR} trips is a unit error or a "
                    "duplicated load rather than a busy evening; the busiest real cells sit in "
                    "the low hundreds."
                )
            },
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="trip_count",
            meta={"reason": "The modelling target. A null target row trains nothing and scores nothing."},
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="zone_id",
            min_value=1,
            max_value=265,
            meta={"reason": "TLC publishes 265 taxi zones. Anything else is a join against the wrong lookup."},
        )
    )
    # `context.suites.add_or_update` — 1.x. The 0.x spelling was
    # `context.add_or_update_expectation_suite`, which is what most material
    # still found in the wild uses. ADR-004 budgeted for exactly this: GX broke
    # compatibility aggressively at 1.0, so a copied snippet fails at runtime
    # rather than at install.
    return context.suites.add_or_update(suite)


def validate_warehouse(demand: pl.DataFrame, *, build_docs: bool = False) -> WarehouseValidation:
    """Run the suite against a stored demand table.

    Args:
        demand: The table as read back, not as written. Validating the frame
            about to be written checks the writer's intention; validating what
            comes back checks the warehouse.
        build_docs: Render Data Docs. Off by default because writing HTML in a
            unit test is noise; CI turns it on and publishes the result.

    Returns:
        A :class:`WarehouseValidation`.
    """
    context = gx.get_context(mode="ephemeral")
    suite = build_suite(context, demand)

    source = context.data_sources.add_pandas("demand")
    asset = source.add_dataframe_asset("hourly_demand")
    batch = asset.add_batch_definition_whole_dataframe("all")

    validation = context.validation_definitions.add(
        gx.ValidationDefinition(data=batch, suite=suite, name="hourly_demand_warehouse")
    )
    result = validation.run(batch_parameters={"dataframe": demand.to_pandas()})

    failed = tuple(
        str(outcome["expectation_config"]["type"]) for outcome in result["results"] if not outcome["success"]
    )

    docs_path = None
    if build_docs:
        context.build_data_docs()
        docs_path = str(next(iter(context.get_docs_sites_urls()), {}).get("site_url", ""))

    return WarehouseValidation(
        success=bool(result["success"]),
        failed=failed,
        checked=len(result["results"]),
        docs_path=docs_path,
    )


def check_density(demand: pl.DataFrame, *, minimum: float = MIN_HOUR_DENSITY) -> tuple[bool, float]:
    """Distinct hours present, against the hours the table's span implies.

    The signature of an outlier timestamp, and it needs no configured window —
    so it stays non-circular while still being derived. A table holding two
    months has ~1,440 distinct hours across a ~1,440-hour span: density 1.0. A
    single pickup stamped 2002 stretches the span to 186,000 hours while the
    distinct-hour count barely moves, and density collapses to under 0.01.

    This is what an earlier `check_coverage` was reaching for and missing: it
    counted (zone, hour) CELLS against the span, so a table of quiet zones and
    a table with corrupt stamps both scored low and could not be told apart.

    Kept OUTSIDE the expectation suite deliberately. GX expectations describe
    rows that exist; this describes a shape the rows collectively have, and an
    expectation suite has no vocabulary for it.

    Returns:
        ``(ok, density)``.
    """
    start, end = expected_window(demand)
    span_hours = int((end - start).total_seconds() // 3600) + 1
    density = demand["event_time"].n_unique() / span_hours if span_hours else 0.0
    return density >= minimum, density
