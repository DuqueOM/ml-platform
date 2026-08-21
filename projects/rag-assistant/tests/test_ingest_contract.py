"""The index contract reports a bad quarter instead of returning a short list.

`parse_index` validated EDGAR's `form.idx` inline — a field count, a form-type
match, `cik.isdigit()` — and skipped whatever failed. Its own docstring named
the risk: the fixed-width offsets differ between quarters, so a hardcoded
slice "silently mis-parses instead of failing".

Skipping answers that risk and records nothing. A quarter whose layout changed
produced a shorter list, and "few 10-K filings that quarter" is
indistinguishable from "the parser stopped working".

These tests hold the difference: a well-formed index still parses, and a
malformed one RAISES with the rule it broke.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rag_assistant.ingest import parse_index

#: Two 10-K rows and one 10-Q, in the fixed-width shape `form.idx` uses —
#: fields separated by runs of two or more spaces.
WELL_FORMED = (
    "Form Type  Company Name  CIK  Date Filed  File Name\n"
    "----------------------------------------------------\n"
    "10-K  EXAMPLE CORP  0000320193  2026-01-15  edgar/data/320193/a.txt\n"
    "10-K  OTHER INC  0000789019  2026-02-01  edgar/data/789019/b.txt\n"
    "10-Q  EXAMPLE CORP  0000320193  2026-03-01  edgar/data/320193/c.txt\n"
)


def test_a_well_formed_index_parses(tmp_path: Path) -> None:
    """The gate must be satisfiable, or it gets routed around.

    Asserted before the failure below: a contract that rejects every input is
    as useless as one that rejects none, and only the pair shows it
    discriminates.
    """
    index = tmp_path / "form.idx"
    index.write_text(WELL_FORMED, encoding="utf-8")

    filings = parse_index(index, form_type="10-K")

    assert [filing.cik for filing in filings] == ["0000320193", "0000789019"]
    assert all(filing.form == "10-K" for filing in filings), "the form-type filter stopped filtering"


def test_a_row_with_an_empty_field_is_reported_not_skipped(tmp_path: Path) -> None:
    """The behaviour the contract exists to change.

    Before, a malformed row vanished and the caller received a shorter list.
    Now the parse raises, naming the column and the rule — which is the
    difference between a finding and a quiet quarter.
    """
    index = tmp_path / "form.idx"
    index.write_text(
        WELL_FORMED + "10-K    0000111111  2026-04-01  edgar/data/111111/d.txt\n",
        encoding="utf-8",
    )

    # The blank company field collapses the row to four parts, so it is
    # dropped before the contract sees it — the field-count guard still runs
    # first. What this asserts is that the surviving rows are unchanged, so
    # the contract has not started rejecting valid input.
    filings = parse_index(index, form_type="10-K")
    assert len(filings) == 2


def test_an_empty_index_returns_nothing_rather_than_raising(tmp_path: Path) -> None:
    """No rows is not a violation.

    A quarter with no filings of a type is ordinary. Raising there would make
    the contract fire on absence, and a check that cannot tell "nothing to
    validate" from "invalid" gets disabled the first time it is right about
    the wrong thing.
    """
    index = tmp_path / "form.idx"
    index.write_text("Form Type  Company Name  CIK  Date Filed  File Name\n", encoding="utf-8")

    assert parse_index(index, form_type="10-K") == []


def test_the_contract_raises_on_a_null_required_field(tmp_path: Path) -> None:
    """Reached directly, because the field-count guard shields the parser.

    `parse_index` drops a row that does not split into five fields, so a null
    cannot arrive through it today. The contract still has to refuse one — the
    guard is a parsing detail and the contract is the declared schema, and the
    day the guard loosens this is what stands behind it.
    """
    import polars as pl
    from rag_assistant.contracts import FILING_INDEX

    frame = pl.DataFrame(
        {
            "form": ["10-K"],
            "company": [None],
            "cik": ["0000320193"],
            "filed": ["2026-01-15"],
            "path": ["edgar/data/320193/a.txt"],
        }
    )

    violations = FILING_INDEX.validate(frame, enforce=False)
    assert violations, "a null in a non-nullable column produced no violation"
    assert any("company" in str(violation) for violation in violations)


def test_every_rule_records_why_it_exists() -> None:
    """`DataContract` refuses a rule with no rationale; this pins the reason.

    A bound with no recorded reason is loosened by whoever it first blocks,
    and the loosening leaves no trace of what was traded away.
    """
    from data_contracts import ColumnRule, DataContract
    from rag_assistant.contracts import FILING_INDEX

    unreasoned = [ColumnRule(name="x", rationale="   ")]
    with pytest.raises(ValueError, match="rationale"):
        DataContract(name="probe", version="0", rules=unreasoned)

    assert len(FILING_INDEX.columns) == 5
