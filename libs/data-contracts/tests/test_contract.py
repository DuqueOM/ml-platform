"""Contracts must fail closed, and fail informatively.

A validator that reports "validation failed" sends someone to read logs. One
that reports "3.7% of fare_amount is negative, e.g. -12.5" sends them to the
right place. These tests pin the second behaviour, because the first is what a
validator degrades into when nobody checks.
"""

from __future__ import annotations

import polars as pl
import pytest
from data_contracts import ColumnRule, Compatibility, ContractError, DataContract


def _contract(
    *,
    compatibility: Compatibility = Compatibility.FULL,
    primary_key: tuple[str, ...] = (),
) -> DataContract:
    """The fixture contract. Explicit parameters rather than **kwargs so the
    type checker can verify the call — a helper that needs a type: ignore to
    build its own subject is a helper that can pass while constructing
    something the production code would reject."""
    return DataContract(
        name="trips",
        version="1.0.0",
        rules=[
            ColumnRule(name="zone_id", rationale="join key for features", dtype=pl.String),
            ColumnRule(
                name="distance_km",
                rationale="a non-positive distance is a recording error, not a short trip",
                minimum=0.001,
                maximum=500.0,
            ),
        ],
        compatibility=compatibility,
        primary_key=primary_key,
    )


def _valid_frame() -> pl.DataFrame:
    return pl.DataFrame({"zone_id": ["A", "B"], "distance_km": [1.5, 20.0]})


def test_conforming_data_produces_no_violations() -> None:
    assert _contract().validate(_valid_frame()) == []


def test_a_missing_column_is_a_violation_not_a_crash() -> None:
    """A dropped column is the most common breaking change.

    Failure looks like: a KeyError three transformations downstream, where the
    stack trace names a function that never knew about the contract.
    """
    frame = _valid_frame().drop("distance_km")
    with pytest.raises(ContractError, match="column is absent"):
        _contract().validate(frame)


def test_violations_carry_a_count_and_an_example() -> None:
    """The difference between a usable report and a log-reading exercise."""
    frame = pl.DataFrame({"zone_id": ["A", "B", "C", "D"], "distance_km": [1.5, -3.0, 20.0, -7.5]})

    violations = _contract().validate(frame, enforce=False)

    assert len(violations) == 1
    violation = violations[0]
    assert violation.column == "distance_km"
    assert violation.failing_rows == 2
    assert violation.total_rows == 4
    assert violation.failure_rate == pytest.approx(0.5)
    assert violation.example is not None


def test_every_violation_is_reported_not_just_the_first() -> None:
    """Stopping at the first hides the shape of the problem.

    The shape is what distinguishes a bad batch from a bad schema, and that
    distinction decides whether you reprocess or renegotiate.
    """
    frame = pl.DataFrame({"zone_id": [None, "B"], "distance_km": [-1.0, 900.0]})

    violations = _contract().validate(frame, enforce=False)

    rules = {violation.rule for violation in violations}
    assert "unexpected nulls" in rules
    assert any("below minimum" in rule for rule in rules)
    assert any("above maximum" in rule for rule in rules)


def test_enforce_false_collects_instead_of_raising() -> None:
    """The warehouse-boundary mode: the answer is a report, not a crash."""
    frame = pl.DataFrame({"zone_id": ["A"], "distance_km": [-1.0]})
    assert len(_contract().validate(frame, enforce=False)) == 1


def test_a_wrong_dtype_is_caught() -> None:
    """Silent coercion is how a join key stops matching.

    Failure looks like: zone_id arriving as an integer, every join returning
    zero rows, and the pipeline reporting success on an empty result.
    """
    frame = pl.DataFrame({"zone_id": [1, 2], "distance_km": [1.5, 20.0]})
    violations = _contract().validate(frame, enforce=False)
    assert any("expected dtype" in violation.rule for violation in violations)


def test_primary_key_uniqueness_is_checked() -> None:
    """A duplicated key silently multiplies rows in every downstream join."""
    contract = _contract(primary_key=("zone_id",))
    frame = pl.DataFrame({"zone_id": ["A", "A"], "distance_km": [1.0, 2.0]})

    violations = contract.validate(frame, enforce=False)

    assert any("primary key" in violation.rule for violation in violations)


def test_a_rule_without_a_rationale_is_refused() -> None:
    """The same discipline as a gate threshold.

    A bound with no recorded reason is loosened by whoever it first blocks,
    with no record that a decision was reversed.
    """
    with pytest.raises(ValueError, match="no rationale"):
        DataContract("x", "1.0.0", [ColumnRule(name="a", rationale="   ")])


def test_a_contract_with_no_rules_is_refused() -> None:
    """It would validate everything, which is indistinguishable from absent."""
    with pytest.raises(ValueError, match="constrains nothing"):
        DataContract("x", "1.0.0", [])


def test_compatibility_is_recorded_on_the_contract() -> None:
    """Declaring a change BREAKING is the entire value of the field.

    Failure looks like: a producer removing a column, every consumer breaking
    at once, and the postmortem concluding they "should have known".
    """
    contract = _contract(compatibility=Compatibility.BREAKING)
    assert contract.compatibility is Compatibility.BREAKING
    assert str(contract.compatibility) == "breaking"


def test_error_message_names_the_contract_and_version() -> None:
    """During an incident, "which contract, which version" is the first question."""
    frame = pl.DataFrame({"zone_id": ["A"], "distance_km": [-1.0]})
    with pytest.raises(ContractError, match=r"trips v1\.0\.0"):
        _contract().validate(frame)
