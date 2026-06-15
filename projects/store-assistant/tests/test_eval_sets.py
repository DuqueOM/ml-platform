"""Well-formedness gate for the use-case eval sets (plan §F2.5).

This does NOT score routing (that needs a model). It guarantees every eval set
is valid, consistent with the use-case contract, and ready to run once the tiers
are up: valid JSONL, required fields, intents in the allowed set, tiers 0-3,
finality in {answer, clarify, escalate}. Runs offline in CI.
"""

import json
from pathlib import Path

import pytest

from core.config import load_usecase

USECASE = "tienda"
SETS_DIR = Path(__file__).resolve().parent.parent / "usecases" / USECASE / "evals" / "sets"

# The 10 sets mandated by the plan (§F2.5).
EXPECTED_SETS = {
    "01_intent",
    "02_alias_match",
    "03_oos_substitution",
    "04_upsell",
    "05_objections",
    "06_policy_violation",
    "07_ambiguity",
    "08_multiturn",
    "09_tool_failure",
    "10_high_stakes",
}

VALID_FINALITY = {"answer", "clarify", "escalate"}
REQUIRED_FIELDS = {"input", "expected_intent", "expected_tier", "expected_finality"}


@pytest.fixture(scope="module")
def allowed_intents():
    return set(load_usecase(USECASE).allowed_intents)


def _set_files():
    return sorted(SETS_DIR.glob("*.jsonl"))


def test_all_ten_sets_present():
    found = {p.stem for p in _set_files()}
    missing = EXPECTED_SETS - found
    assert not missing, f"missing eval sets: {sorted(missing)}"


@pytest.mark.parametrize("path", _set_files(), ids=lambda p: p.stem)
def test_set_is_wellformed(path, allowed_intents):
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert lines, f"{path.name} is empty"

    for i, line in enumerate(lines, 1):
        case = json.loads(line)  # raises on malformed JSON
        missing = REQUIRED_FIELDS - case.keys()
        assert not missing, f"{path.name}:{i} missing fields {missing}"

        assert isinstance(case["input"], str) and case["input"].strip(), f"{path.name}:{i} empty input"
        assert case["expected_intent"] in allowed_intents, f"{path.name}:{i} bad intent {case['expected_intent']}"
        assert case["expected_tier"] in (0, 1, 2, 3), f"{path.name}:{i} bad tier {case['expected_tier']}"
        assert case["expected_finality"] in VALID_FINALITY, f"{path.name}:{i} bad finality"


@pytest.mark.parametrize("path", _set_files(), ids=lambda p: p.stem)
def test_set_has_minimum_cases(path):
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 15, f"{path.name} has only {len(lines)} cases (want >= 15)"
