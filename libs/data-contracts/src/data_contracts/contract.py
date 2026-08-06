"""Schema contracts with versioning and an explicit compatibility rule.

Pandera validates a frame against a schema. This adds the part that matters
across a monorepo: **who breaks when the schema changes, and is the change
allowed?**

A contract is not a schema. A schema says what the data looks like now; a
contract says what consumers may rely on and what a producer may change without
asking. Without the second, a producer removes a column, every consumer breaks
at once, and the postmortem concludes that the producer "should have known".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import polars as pl


class Compatibility(StrEnum):
    """How a schema change relates to the version before it.

    The direction matters and is easy to get backwards:

    - **BACKWARD** — new schema reads old data. Safe for the *consumer* to
      upgrade first. Adding an optional column is backward compatible.
    - **FORWARD** — old schema reads new data. Safe for the *producer* to
      upgrade first. Removing an optional column is forward compatible.
    - **FULL** — both. The only kind that can be deployed in any order.
    - **BREAKING** — neither. Requires a coordinated migration, and saying so
      is the entire point of recording it.
    """

    BACKWARD = "backward"
    FORWARD = "forward"
    FULL = "full"
    BREAKING = "breaking"


@dataclass(frozen=True)
class ContractViolation:
    """One way the data failed its contract.

    Carries the column and a count rather than a boolean, because "validation
    failed" sends someone to read logs while "3.7% of `fare_amount` is
    negative" sends them to the right place.
    """

    column: str
    rule: str
    failing_rows: int
    total_rows: int
    example: str | None = None

    @property
    def failure_rate(self) -> float:
        return self.failing_rows / self.total_rows if self.total_rows else 0.0

    def __str__(self) -> str:
        text = f"{self.column}: {self.rule} — {self.failing_rows}/{self.total_rows} rows ({self.failure_rate:.2%})"
        return f"{text}, e.g. {self.example}" if self.example else text


class ContractError(Exception):
    """Raised when data violates a contract in enforcing mode.

    Attributes:
        violations: Every violation found, not just the first. Failing on the
            first hides the shape of the problem, and the shape is usually what
            tells you whether it is a bad batch or a bad schema.
    """

    def __init__(self, contract: str, violations: list[ContractViolation]):
        self.contract = contract
        self.violations = violations
        detail = "\n  ".join(str(violation) for violation in violations)
        super().__init__(f"{contract} violated by {len(violations)} rule(s):\n  {detail}")


@dataclass(frozen=True)
class ColumnRule:
    """One constraint on one column.

    Attributes:
        name: Column name.
        dtype: Expected Polars dtype. ``None`` skips the type check.
        nullable: Whether nulls are permitted.
        minimum / maximum: Inclusive bounds, for ordered types.
        allowed: Closed set of permitted values.
        rationale: **Why this constraint exists.** Required, and not
            decoration: a bound with no recorded reason is loosened by whoever
            it first blocks, exactly like an unexplained gate threshold.
    """

    name: str
    rationale: str
    dtype: pl.DataType | type[pl.DataType] | None = None
    nullable: bool = False
    minimum: float | None = None
    maximum: float | None = None
    allowed: frozenset[str] | None = None


class DataContract:
    """A versioned, enforceable agreement about a dataset.

    Args:
        name: Stable identifier, used in errors and lineage.
        version: Semantic version of the contract itself, not of the data.
        rules: Column constraints.
        compatibility: How this version relates to the previous one.
        primary_key: Columns that must be unique together, if any.
    """

    def __init__(
        self,
        name: str,
        version: str,
        rules: list[ColumnRule],
        *,
        compatibility: Compatibility = Compatibility.FULL,
        primary_key: tuple[str, ...] = (),
    ):
        if not rules:
            raise ValueError(f"contract {name!r} declares no rules — it constrains nothing")
        missing_rationale = [rule.name for rule in rules if not rule.rationale.strip()]
        if missing_rationale:
            raise ValueError(
                f"contract {name!r}: columns {missing_rationale} have no rationale. "
                "A constraint with no recorded reason is loosened by whoever it first blocks."
            )
        self.name = name
        self.version = version
        self.rules = rules
        self.compatibility = compatibility
        self.primary_key = primary_key

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.rules)

    def validate(self, frame: pl.DataFrame, *, enforce: bool = True) -> list[ContractViolation]:
        """Check a frame against the contract.

        Args:
            frame: The data.
            enforce: Raise on violation. Set False to collect violations for a
                report — used at the warehouse boundary, where the answer is a
                data-quality artifact rather than a crash.

        Returns:
            Every violation found. Empty when the data conforms.

        Raises:
            ContractError: If ``enforce`` and any violation was found.
        """
        violations: list[ContractViolation] = []
        total = frame.height

        for rule in self.rules:
            if rule.name not in frame.columns:
                violations.append(ContractViolation(rule.name, "column is absent", total, total, rule.rationale))
                continue

            column = frame[rule.name]

            if rule.dtype is not None and column.dtype != rule.dtype:
                violations.append(
                    ContractViolation(rule.name, f"expected dtype {rule.dtype}, found {column.dtype}", total, total)
                )

            if not rule.nullable:
                nulls = int(column.null_count())
                if nulls:
                    violations.append(ContractViolation(rule.name, "unexpected nulls", nulls, total))

            if rule.minimum is not None:
                below = int(frame.filter(pl.col(rule.name) < rule.minimum).height)
                if below:
                    example = str(frame.filter(pl.col(rule.name) < rule.minimum)[rule.name][0])
                    violations.append(
                        ContractViolation(rule.name, f"below minimum {rule.minimum}", below, total, example)
                    )

            if rule.maximum is not None:
                above = int(frame.filter(pl.col(rule.name) > rule.maximum).height)
                if above:
                    example = str(frame.filter(pl.col(rule.name) > rule.maximum)[rule.name][0])
                    violations.append(
                        ContractViolation(rule.name, f"above maximum {rule.maximum}", above, total, example)
                    )

            if rule.allowed is not None:
                outside = int(frame.filter(~pl.col(rule.name).is_in(list(rule.allowed))).height)
                if outside:
                    example = str(frame.filter(~pl.col(rule.name).is_in(list(rule.allowed)))[rule.name][0])
                    violations.append(
                        ContractViolation(rule.name, "value outside the allowed set", outside, total, example)
                    )

        if self.primary_key:
            duplicates = total - int(frame.select(list(self.primary_key)).unique().height)
            if duplicates:
                violations.append(
                    ContractViolation(",".join(self.primary_key), "primary key is not unique", duplicates, total)
                )

        if enforce and violations:
            raise ContractError(f"{self.name} v{self.version}", violations)
        return violations
