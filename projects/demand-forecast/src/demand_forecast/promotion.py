"""What a model must show before it is published — defined once, for every orchestrator.

**Why this module exists (W-14).** The Airflow DAG and the KFP pipeline each
carried their own copy of the promotion gate, and the copies disagreed:

| | DAG | pipeline |
| --- | --- | --- |
| skill | `>= 0.05` | `> 0` |
| interval coverage | `>= 0.85`, one-sided | within 0.05 of 0.90 |
| backtest | 5 folds | 3 folds |

So the same model could be promoted by one and refused by the other, and QA-4
round fifteen showed the backtests themselves differed: on the same data the
DAG measured skill +12.4% and the pipeline +23.0%, because three folds drop
folds 0 and 1 — the two the model loses. Both module docstrings warned that a
step reimplementing the logic it orchestrates becomes a second copy that
drifts; the gate was the one piece each reimplemented.

**The rule, decided:**

- **Skill at least 0.05** against the seasonal-naive baseline. A positive floor,
  not `> 0`: the gate exists to catch a broken pipeline, and a model that ties
  "same hour last week" has not earned a deployment.
- **Interval coverage within [0.85, 0.95]** of the 0.90 nominal, both bounds
  inclusive. Two-sided: under-coverage is an interval claiming certainty it
  does not have, and over-coverage is uncertainty the model has not quantified —
  intervals far wider than asked for make every downstream decision timid.
- **Five folds, horizon 168 hours, seed 42.** Five is the design that includes
  the losing folds; the model card's +12.4% is a five-fold figure.

Both orchestrators call :func:`backtest` and :func:`check` — nothing else
decides promotion. Every number here is watched by `scripts/check_thresholds.py`.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import polars as pl

from demand_forecast.train import ALPHA, BacktestReport, evaluate

#: Skill is `1 - model_mae / baseline_mae` against seasonal naive. A floor, and
#: deliberately low: it catches a broken pipeline, it does not express an
#: ambition. Raising it is a threshold change.
MIN_SKILL = 0.05

#: The accepted band for empirical interval coverage, around the
#: `1 - ALPHA` = 0.90 nominal. Symmetric by construction, and held so by
#: `tests/test_promotion.py`.
MIN_COVERAGE = 0.85
MAX_COVERAGE = 0.95


@dataclass(frozen=True)
class BacktestDesign:
    """The backtest every promotion decision is made on.

    Attributes:
        n_folds: Expanding-window evaluations. Fewer folds drop the OLDEST
            ones first, and for this model those are the folds it loses — so
            this is a floor, watched as one.
        horizon: Hours scored per fold — one week, the forecast's horizon.
        seed: Fixed, so two runs on one snapshot reach one verdict.
    """

    n_folds: int = 5
    horizon: int = 168
    seed: int = 42


DESIGN = BacktestDesign()


@dataclass(frozen=True)
class PromotionVerdict:
    """Whether to promote, and every reason not to."""

    promote: bool
    reasons: tuple[str, ...]


class PromotionRefusedError(ValueError):
    """Raised by :func:`check`. The run fails, so nothing downstream publishes."""


def backtest(demand: pl.DataFrame) -> BacktestReport:
    """Backtest ``demand`` the one way promotion is decided on."""
    return evaluate(demand, **asdict(DESIGN))


def _at_least(value: float, bound: float) -> bool:
    """`value >= bound`, inclusive despite binary fractions: 0.85 is not 0.8499999999999999's victim."""
    return value >= bound or math.isclose(value, bound, rel_tol=0.0, abs_tol=1e-12)


def verdict(skill: float, coverage: float) -> PromotionVerdict:
    """Judge a backtest's two numbers against the rule. Every failure is reported, not the first.

    An operator who fixes skill only to meet the coverage failure on the next
    run has paid for two cycles to learn one thing.
    """
    reasons = []
    if not _at_least(skill, MIN_SKILL):
        reasons.append(f"skill {skill:+.4f} is below {MIN_SKILL} against the seasonal-naive baseline")
    if not _at_least(coverage, MIN_COVERAGE):
        reasons.append(f"interval coverage {coverage:.4f} is below {MIN_COVERAGE}: the intervals claim false certainty")
    if not _at_least(MAX_COVERAGE, coverage):
        reasons.append(
            f"interval coverage {coverage:.4f} is above {MAX_COVERAGE}: the intervals are wider than the "
            f"{1 - ALPHA:.0%} asked for, uncertainty the model has not quantified"
        )
    return PromotionVerdict(promote=not reasons, reasons=tuple(reasons))


def check(skill: float, coverage: float) -> None:
    """Raise :class:`PromotionRefusedError` naming every rule the model misses; return when it may ship."""
    result = verdict(skill, coverage)
    if not result.promote:
        raise PromotionRefusedError("quality gate failed: " + "; ".join(result.reasons))
