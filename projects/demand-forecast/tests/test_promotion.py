"""The promotion rule, held to what W-14 decided.

Before this module the rule existed twice, once per orchestrator, and the two
copies disagreed on skill (`>= 0.05` against `> 0`), on coverage (one-sided
against two-sided) and on the backtest itself (5 folds against 3). These tests
pin the single definition; `tests/test_promotion_agreement.py` runs the same
metrics through both orchestrators' gates and asserts one verdict.
"""

from __future__ import annotations

import pytest
from demand_forecast import promotion, train


@pytest.mark.parametrize(
    ("skill", "coverage", "refusals"),
    [
        pytest.param(0.124, 0.896, [], id="the-model-card-figures"),
        pytest.param(0.05, 0.90, [], id="skill-at-its-floor"),
        pytest.param(0.12, 0.85, [], id="coverage-at-its-floor"),
        pytest.param(0.12, 0.95, [], id="coverage-at-its-ceiling"),
        # The two copies split on this one: the pipeline's `> 0` promoted it,
        # the DAG's `>= 0.05` refused it.
        pytest.param(0.03, 0.90, ["skill"], id="positive-but-below-the-floor"),
        pytest.param(0.0, 0.90, ["skill"], id="a-tie-with-the-baseline"),
        pytest.param(0.12, 0.849, ["below 0.85"], id="claims-false-certainty"),
        # The DAG promoted this one: it had no ceiling.
        pytest.param(0.12, 0.97, ["above 0.95"], id="wider-than-asked"),
        pytest.param(-0.18, 0.99, ["skill", "above 0.95"], id="both-reported-at-once"),
    ],
)
def test_the_rule(skill: float, coverage: float, refusals: list[str]) -> None:
    result = promotion.verdict(skill, coverage)

    assert result.promote is (not refusals)
    assert len(result.reasons) == len(refusals)
    for expected, reason in zip(refusals, result.reasons, strict=True):
        assert expected in reason


def test_the_floors_hold_their_values() -> None:
    """Pinned, not only probed: the cases above sit at and beside each floor, so a floor moved by less
    than the gap between two probes passes them. QA-4 round sixteen set `MIN_SKILL = 0.0` and 34 DAG tests
    passed, because they derived their probes from the constant; `check_thresholds.py` watches a change,
    and this states the decision.
    """
    assert (promotion.MIN_SKILL, promotion.MIN_COVERAGE, promotion.MAX_COVERAGE) == (0.05, 0.85, 0.95)


def test_check_raises_with_every_reason_and_returns_when_the_model_may_ship() -> None:
    """Raising is the mechanism: the task or step fails, so nothing downstream publishes."""
    assert promotion.check(0.124, 0.896) is None

    with pytest.raises(promotion.PromotionRefusedError, match="quality gate failed") as refused:
        promotion.check(-0.18, 0.99)
    assert "skill" in str(refused.value)
    assert "above 0.95" in str(refused.value)


def test_the_band_is_symmetric_around_the_nominal_coverage() -> None:
    """[0.85, 0.95] around 1 - ALPHA, and the same width the backtest summary reports against.

    `BacktestReport.intervals_are_calibrated` keeps its own default tolerance
    for the printed summary; the two must not drift into a summary that says
    "calibrated" about a model this rule refuses.
    """
    import inspect

    nominal = 1 - train.ALPHA
    tolerance = inspect.signature(train.BacktestReport.intervals_are_calibrated).parameters["tolerance"].default

    assert pytest.approx(nominal - tolerance) == promotion.MIN_COVERAGE
    assert pytest.approx(nominal + tolerance) == promotion.MAX_COVERAGE


def test_the_backtest_is_the_design_and_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five folds of a week each, seed 42 — the design that includes the folds the model loses."""
    received: dict[str, object] = {}

    def evaluate(demand: object, **kwargs: object) -> str:
        received.update(kwargs, demand=demand)
        return "report"

    monkeypatch.setattr(promotion, "evaluate", evaluate)

    assert promotion.backtest("table") == "report"  # type: ignore[arg-type]
    assert received == {"demand": "table", "n_folds": 5, "horizon": 168, "seed": 42}
    assert promotion.BacktestDesign(n_folds=5, horizon=168, seed=42) == promotion.DESIGN
