"""`validate_relation` reaches `DataContract.validate`'s verdict, rule for rule, on the same rows.

The DuckDB path exists so a month of trips can be validated without loading it
(ADR-011). If it reported a different count, a different example or a missing
rule, the reject-rate alarm would read a different number depending on the
engine — so every kind of rule is broken here, and the two lists compared whole.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest
from data_contracts import ColumnRule, ContractViolation, DataContract
from data_contracts.duckdb_relation import admits, validate_relation

CONTRACT = DataContract(
    name="probe",
    version="1.0.0",
    rules=[
        ColumnRule(name="id", dtype=pl.Int64, rationale="the key"),
        ColumnRule(name="amount", dtype=pl.Float64, minimum=-5.0, maximum=50.0, rationale="a bounded amount"),
        ColumnRule(name="count", dtype=pl.Int64, nullable=True, minimum=0, maximum=9, rationale="nullable, bounded"),
        ColumnRule(name="kind", dtype=pl.String, allowed=frozenset({"a", "b"}), rationale="a closed set"),
        ColumnRule(name="missing", rationale="absent from every probe"),
    ],
    primary_key=("id",),
)


def _probe(**overrides: list[object]) -> pl.DataFrame:
    columns: dict[str, list[object]] = {
        "id": [1, 2, 3, 4, 5],
        "amount": [1.0, 2.0, 3.0, 4.0, 5.0],
        "count": [1, None, 2, 3, 4],
        "kind": ["a", "b", "a", "b", "a"],
    }
    columns.update(overrides)
    return pl.DataFrame(columns)


def _both(
    frame: pl.DataFrame, contract: DataContract = CONTRACT
) -> tuple[list[ContractViolation], list[ContractViolation]]:
    polars_verdict = contract.validate(frame, enforce=False)
    connection = duckdb.connect()
    relation = connection.from_arrow(frame.with_row_index("__row").to_arrow())
    duckdb_verdict = validate_relation(contract, relation, schema=frame.schema, order_by="__row")
    return list(polars_verdict), list(duckdb_verdict)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="only-the-absent-column"),
        pytest.param({"id": [1, None, 3, 4, None]}, id="nulls-in-a-required-column"),
        pytest.param({"amount": [99.0, -7.0, 3.0, 88.0, -9.0]}, id="both-bounds-first-example-in-row-order"),
        pytest.param({"count": [None, 12, None, -1, 3]}, id="a-nullable-column-out-of-bounds"),
        pytest.param({"kind": ["a", "z", None, "y", "a"]}, id="outside-the-allowed-set-nulls-not-counted"),
        pytest.param({"id": [1, 1, 2, 2, 2]}, id="a-duplicate-key"),
        pytest.param({"amount": [1, 2, 3, 4, 5]}, id="the-wrong-dtype"),
    ],
)
def test_the_two_engines_report_the_same_violations(overrides: dict[str, list[object]]) -> None:
    polars_verdict, duckdb_verdict = _both(_probe(**overrides))
    assert duckdb_verdict == polars_verdict
    assert polars_verdict, "every probe breaks at least the absent column, or this compares two empty lists"


def test_the_example_is_the_first_violating_row_not_any() -> None:
    _, verdict = _both(_probe(amount=[1.0, 77.0, 66.0, 99.0, 2.0]))
    (above,) = [violation for violation in verdict if violation.rule.startswith("above")]
    assert above.example == "77.0"


def test_types_are_judged_from_the_source_schema_not_the_relation() -> None:
    """DuckDB reads a parquet nanosecond timestamp as microseconds; the file's own type is the fact."""
    contract = DataContract(
        name="clock", version="1", rules=[ColumnRule(name="at", dtype=pl.Datetime("ns"), rationale="event time")]
    )
    frame = pl.DataFrame({"at": [0]}).with_columns(pl.col("at").cast(pl.Datetime("ns")))
    relation = duckdb.connect().from_arrow(frame.with_row_index("__row").to_arrow())
    assert validate_relation(contract, relation, schema=frame.schema, order_by="__row") == []
    claimed = {"at": pl.Datetime("us")}
    (violation,) = validate_relation(contract, relation, schema=claimed, order_by="__row")
    assert violation.rule.startswith("expected dtype")


def test_admits_keeps_exactly_the_rows_no_rule_rejects() -> None:
    contract = DataContract(name="probe", version="1", rules=CONTRACT.rules[:4])
    frame = _probe(id=[1, None, 3, 4, 5], amount=[1.0, 2.0, 99.0, 4.0, 5.0], count=[None, 1, 2, 12, 3], kind=["a"] * 5)
    kept = duckdb.connect().from_arrow(frame.to_arrow()).filter(admits(contract)).pl()
    # Row 2 has a null id, row 3 an amount above 50, row 4 a count above 9; row 1's null count is admitted.
    assert kept["id"].to_list() == [1, 5]


def test_a_column_name_is_an_identifier_never_sql() -> None:
    contract = DataContract(
        name="probe", version="1", rules=[ColumnRule(name='x" OR 1=1 --', maximum=1.0, rationale="hostile name")]
    )
    frame = pl.DataFrame({'x" OR 1=1 --': [0.0, 2.0]})
    polars_verdict, duckdb_verdict = _both(frame, contract)
    assert duckdb_verdict == polars_verdict
    assert duckdb_verdict[0].failing_rows == 1
