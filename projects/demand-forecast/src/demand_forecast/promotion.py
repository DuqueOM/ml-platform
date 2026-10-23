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
- **No volume decile harmed** (F-19b): in none may the baseline beat the model
  by more than fold-to-fold variation explains, at `GROUP_HARM_CONFIDENCE`.
- **Five folds, horizon 168 hours, seed 42.** Five is the design that includes
  the losing folds; the model card's +12.9% is a five-fold figure.

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

#: The coverage floor every volume decile must reach, not only the aggregate
#: (F-19, decided 2026-10-23). One global conformal quantile covered 89.6% of
#: all hours while covering 37.7% of the busiest decile's, and staffing is
#: decided per zone. The same floor as the marginal one; no per-decile
#: ceiling, because the quietest zones' counts are integers and mostly zero, so
#: their over-coverage is partly discreteness rather than miscalibration — it is
#: reported in the backtest summary, not gated.
MIN_GROUP_COVERAGE = 0.85

#: The confidence at which a volume decile counts as HARMED: the seasonal-naive
#: baseline beats the model there by more than fold-to-fold variation explains
#: (F-19b, decided 2026-11-13). A harmed decile refuses the model whatever the
#: aggregate skill, because staffing is decided per zone. The rule is "refuse on
#: evidence of harm" — the lower bound of the per-decile MAE difference above
#: zero — chosen over a non-inferiority margin, which on the measured folds
#: discriminated the two candidate models only inside an 8.4-10.3% band and so
#: would have been fitted to this sample. MIN_SKILL keeps the burden of proof
#: on the model in aggregate. A LOWER confidence refuses more readily, so a
#: rise is a loosening: watched as a ceiling by `scripts/check_thresholds.py`.
GROUP_HARM_CONFIDENCE = 0.95


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


#: How close to a bound still counts as AT it — binary fractions only, never a
#: margin. Watched as a ceiling by `scripts/check_thresholds.py`: widening it is
#: lowering every floor at once (QA-4 round seventeen).
FLOAT_TOLERANCE = 1e-12


def _at_least(value: float, bound: float) -> bool:
    """`value >= bound`, inclusive despite binary fractions: 0.85 is not 0.8499999999999999's victim."""
    return value >= bound or math.isclose(value, bound, rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)


def worst_group_harm(report: BacktestReport) -> float:
    """The most harmed volume decile's bound (see :meth:`BacktestReport.group_harm`); NaN if any is unknown."""
    harm = report.group_harm(GROUP_HARM_CONFIDENCE)
    if not harm or any(math.isnan(value) for value in harm.values()):
        return math.nan
    return max(harm.values())


def verdict(skill: float, coverage: float, group_coverage: float, group_harm: float) -> PromotionVerdict:
    """Judge a backtest's numbers against the rule. Every failure is reported, not the first.

    An operator who fixes skill only to meet the coverage failure on the next
    run has paid for two cycles to learn one thing.
    """
    reasons = []
    # Required, never defaulted: a caller that forgot the per-decile figure
    # would otherwise promote on the marginal one alone, which is the defect.
    if math.isnan(group_coverage):
        reasons.append("no volume decile's coverage was measured, so conditional coverage is unknown")
    elif not _at_least(group_coverage, MIN_GROUP_COVERAGE):
        reasons.append(
            f"the worst volume decile's interval coverage {group_coverage:.4f} is below {MIN_GROUP_COVERAGE}: "
            "the intervals fail the zones that decile holds, whatever the aggregate says"
        )
    if math.isnan(group_harm):
        reasons.append("some volume decile was scored in fewer than two folds, so harm to it cannot be judged")
    elif not _at_least(0.0, group_harm):
        reasons.append(
            f"the seasonal-naive baseline beats the model in a volume decile by at least {group_harm:.4f} trips an "
            f"hour at {GROUP_HARM_CONFIDENCE:.0%} confidence: the zones it holds are better served by the baseline"
        )
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


def check(skill: float, coverage: float, group_coverage: float, group_harm: float) -> None:
    """Raise :class:`PromotionRefusedError` naming every rule the model misses; return when it may ship."""
    result = verdict(skill, coverage, group_coverage, group_harm)
    if not result.promote:
        raise PromotionRefusedError("quality gate failed: " + "; ".join(result.reasons))
