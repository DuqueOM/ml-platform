"""A :class:`DataContract`'s verdict on a DuckDB relation, without loading the rows.

`DataContract.validate` reads a Polars frame, so validating a month of trips
meant holding the month in memory: the ingest's memory floor was the contract,
not the aggregate (ADR-011). This answers the same question inside DuckDB,
whose operators stream and spill, and returns the same
:class:`ContractViolation` list.

**The same verdict, rule for rule** — `tests/test_duckdb.py` holds it against
`DataContract.validate` on frames that break every kind of rule:

- a rule's column absent from the relation is one violation over every row;
- nulls in a non-nullable column are counted;
- a bound counts the non-null values outside it, as Polars' comparison does
  (a null is neither below nor above anything);
- an allowed set counts the non-null values outside it;
- a primary key counts rows beyond the distinct key tuples, nulls equal;
- the example is the first violating value in ``order_by``'s order.

**Types are read from the source, not the relation.** DuckDB reads a parquet
nanosecond timestamp as microseconds, so a dtype check against the relation
would report a violation the file does not have. The caller passes the
source's own schema (`polars.read_parquet_schema`, or the frame's).

No SQL is written as text: every predicate is a DuckDB expression built from
the rule, so a column name or a bound can never change the query's shape.

Optional: `uv add 'data-contracts[duckdb]'`. Importing this module without
DuckDB installed is an ImportError naming the extra. Named `duckdb_relation`,
not `duckdb`, so it can never shadow the engine it adapts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import polars as pl

try:
    import duckdb
    from duckdb import ColumnExpression, ConstantExpression, FunctionExpression
except ImportError as error:  # pragma: no cover - exercised only without the extra
    raise ImportError("data_contracts.duckdb needs the extra: install data-contracts[duckdb]") from error

from data_contracts.contract import ColumnRule, ContractViolation, DataContract


def _first(relation: duckdb.DuckDBPyRelation) -> tuple[Any, ...] | None:
    """The relation's first row. DuckDB 2.0 relations keep no result between calls, so no `fetchone`."""
    rows = relation.limit(1).fetchall()
    return tuple(rows[0]) if rows else None


def _count(relation: duckdb.DuckDBPyRelation) -> int:
    row = _first(relation.aggregate([FunctionExpression("count_star")]))
    return int(row[0]) if row else 0


def _column(name: str) -> duckdb.Expression:
    """The column as an identifier object — never parsed as SQL, so no name can change the query."""
    return ColumnExpression(name)


def _outside(rule: ColumnRule) -> list[tuple[str, duckdb.Expression]]:
    """Each bound or set check a rule carries, as (rule text, predicate on a non-null value)."""
    column = _column(rule.name)
    checks: list[tuple[str, duckdb.Expression]] = []
    if rule.minimum is not None:
        checks.append((f"below minimum {rule.minimum}", column < ConstantExpression(rule.minimum)))
    if rule.maximum is not None:
        checks.append((f"above maximum {rule.maximum}", column > ConstantExpression(rule.maximum)))
    if rule.allowed is not None:
        allowed = [ConstantExpression(value) for value in sorted(rule.allowed)]
        checks.append(("value outside the allowed set", column.isnotin(*allowed)))
    return checks


def admits(contract: DataContract) -> duckdb.Expression:
    """The predicate a row satisfies when no rule of ``contract`` rejects it.

    A non-nullable column must be present; a bound or a set applies to every
    non-null value. The row-level counterpart of :func:`validate_relation`,
    for a caller that keeps the admissible rows rather than counting the rest.
    """
    predicate: duckdb.Expression = ConstantExpression(True)
    for rule in contract.rules:
        column = _column(rule.name)
        for _, outside in _outside(rule):
            predicate = predicate & (column.isnull() | ~outside)
        if not rule.nullable:
            predicate = predicate & column.isnotnull()
    return predicate


def validate_relation(
    contract: DataContract,
    relation: duckdb.DuckDBPyRelation,
    *,
    schema: Mapping[str, pl.DataType],
    order_by: str,
) -> list[ContractViolation]:
    """The violations `contract.validate` would report for the same rows. Never raises on a violation.

    Args:
        contract: The contract to hold the rows to.
        relation: The rows. Read once for every count, and once more per
            violated rule for its example.
        schema: The SOURCE's column types, which the dtype rules are checked
            against (see the module docstring).
        order_by: A column of ``relation`` giving the source's row order, so
            the example is the first violating row, as Polars reports it.
    """
    present = set(relation.columns)
    checks: list[tuple[ColumnRule, str, duckdb.Expression]] = []
    violations: list[ContractViolation] = []
    total = _count(relation)

    for rule in contract.rules:
        if rule.name not in present:
            violations.append(ContractViolation(rule.name, "column is absent", total, total, rule.rationale))
            continue
        found = schema.get(rule.name)
        if rule.dtype is not None and found != rule.dtype:
            violations.append(ContractViolation(rule.name, f"expected dtype {rule.dtype}, found {found}", total, total))
        if not rule.nullable:
            checks.append((rule, "unexpected nulls", _column(rule.name).isnull()))
        checks += [(rule, text, predicate) for text, predicate in _outside(rule)]

    counts = _first(relation.aggregate([FunctionExpression("count_if", p) for _, _, p in checks])) if checks else ()
    for (rule, text, predicate), failing in zip(checks, counts or (), strict=True):
        if not failing:
            continue
        example = None
        if text != "unexpected nulls":
            first = _first(relation.filter(predicate).order(order_by).project(_column(rule.name)))
            example = str(first[0]) if first else None
        violations.append(ContractViolation(rule.name, text, int(failing), total, example))

    violations = _in_contract_order(contract, violations)
    if contract.primary_key:  # last, as `DataContract.validate` reports it
        keys = [_column(name) for name in contract.primary_key]
        distinct = _count(relation.project(*keys).distinct())
        if total - distinct:
            violations.append(
                ContractViolation(",".join(contract.primary_key), "primary key is not unique", total - distinct, total)
            )
    return violations


def _in_contract_order(contract: DataContract, violations: list[ContractViolation]) -> list[ContractViolation]:
    """Ordered as `DataContract.validate` emits them: by rule, then absent, dtype, nulls, min, max, set."""
    rank = {rule.name: index for index, rule in enumerate(contract.rules)}
    kinds = (
        "column is absent",
        "expected dtype",
        "unexpected nulls",
        "below minimum",
        "above maximum",
        "value outside",
    )

    def key(violation: ContractViolation) -> tuple[int, int]:
        kind = next((index for index, prefix in enumerate(kinds) if violation.rule.startswith(prefix)), len(kinds))
        return rank.get(violation.column, len(rank)), kind

    return sorted(violations, key=key)
