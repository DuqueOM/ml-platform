#!/usr/bin/env python3
"""Gate DECLARATIONS are data, and nothing validated them as data.

Upstream `ml-service-template` validates one file — `configs/quality_gates.yaml`
— against a JSON Schema. This repository declares gates in two notations
instead, and the schema approach does not reach either of them:

* `docs/governance/quality-gates.md` — the platform traceability table, 32
  rows of markdown, which is what check C4 in `check_doc_coherence.py` reads.
* `projects/*/evals/gates.yaml` — per-project thresholds, whose shape is fixed
  by requirement P6 of `docs/PROJECT_CONTRACT.md`.

**What this does NOT check, so the boundary is a decision rather than an
overlap.** C4 owns command resolution: whether a `scripts/*.py` named in a row
exists, and whether a third-party binary appears in some workflow. Re-checking
it here would create two gates that can disagree about the same row. This
script owns what C4 does not look at.

Three findings it was written against, all present when it was written:

1. **`P6` was the id of two different rows** — "Cloud-specific surface" and
   "Dependencies resolve reproducibly". Ids are how gates are cited: `codecov.yml`
   cites L1, `.github/workflows/ci.yml` cites L1/L2, `docs/COMPLIANCE_MAPPING.md`
   cites S4 and C3. A citation that resolves to two rows with two different
   thresholds is a compliance record pointing at nothing in particular. Nothing
   checked uniqueness because uniqueness is not visible one row at a time,
   which is the general reason this script is not a per-row test.

2. **C4's docstring claims it checks "a command and a threshold rationale" and
   it never reads the rationale column.** The document's own rule 4 says the
   threshold "is recorded here with the reason it has that value". That rule
   had no gate. A declared check that does not exist is the defect this
   repository keeps finding under new names — most recently the `⏳` glyph that
   made C4 skip 15 of its 29 rows while reporting success.

3. **A PENDING row was exempt from everything.** C4 `continue`s on any row
   containing PENDING, so such a row could carry no threshold, no reason and a
   duplicate id. A gate declared for a later phase is still a commitment about
   what will be required; `**PENDING — Phase 3**` on its own is a schedule, not
   a reason.

On the YAML side the complement is narrower and precise. `tests/test_project_contract.py`
already enforces P6 — but per project, and it SKIPS any project listed in
`KNOWN_DEVIATIONS`. `rag-assistant` is exempt from P6 today, so if it ever grew
a malformed `evals/gates.yaml` the deviation would keep skipping it and the
file would be validated by nothing. An exemption from "must declare gates as
data" is not an exemption from "the data must be well formed". This validates
every gates file that EXISTS, deviation or not.

`templates/project/evals/gates.yaml` is excluded: it is Jinja generator source,
not valid YAML in place, and its `TODO` placeholders are the point — they are
what the person generating a project is required to replace. It is verified by
rendering, in `tests/test_project_generator.py`.

    uv run python scripts/validate_quality_gates.py
    uv run python scripts/validate_quality_gates.py --report   # what was examined
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GATES_TABLE = REPO_ROOT / "docs" / "governance" / "quality-gates.md"
PROJECTS_DIR = REPO_ROOT / "projects"

#: A gate row in the traceability table. The id may be followed by anything —
#: `| L3 ⏳ |` is a real row, and requiring whitespace after the id is exactly
#: how C4 came to skip half the table while reporting that it had read it.
_GATE_ROW = re.compile(r"^\|\s*([PLSMAC]\d+)[^|]*\|")

#: A reason that names only a phase. `**PENDING — Phase 3**` says WHEN the gate
#: arrives, never why its threshold holds the value written beside it. The
#: other four pending compliance rows say both, which is the evidence that this
#: is a reachable standard rather than a rule invented for one row.
_BARE_SCHEDULE = re.compile(r"^\*{0,2}PENDING\s*[—-]\s*Phase\s*\d+\*{0,2}$")

#: Below this a "reason" is a restatement of the threshold. Set at the length
#: the shortest genuine reason in the table already clears ("ADR-005 rules C,
#: D, H mechanised", 32) rather than at a round number nobody measured.
MIN_REASON_CHARS = 30

#: Fields every entry in an `evals/gates.yaml` carries, from PROJECT_CONTRACT
#: requirement P6. `check` is the one that does the work: without it the file
#: is a list of intentions, which is how `demand-forecast` came to ship
#: `threshold: TODO` on its primary metric while its DAG enforced a real floor
#: in code.
REQUIRED_GATE_FIELDS = ("metric", "threshold", "rationale", "check")

failures: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    """Record a finding. Every finding fails the run."""
    failures.append(message)


def ok(message: str) -> None:
    """Record what was examined, which is reported whether or not it passed.

    Anti-pattern P-20: a gate that does not say what it looked at cannot be
    distinguished from one whose filter matched nothing.
    """
    notes.append(message)


def _cells(row: str) -> list[str]:
    """Split one markdown table row into its trimmed cells."""
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _reason_of(cells: list[str]) -> str:
    """The threshold's justification, from either table shape.

    The platform, library, service, model and agent tables carry five columns
    and put the reason in its own `Why this value` column. The compliance table
    carries four and folds the reason into the threshold cell after a `·`.
    Reading only the last cell would treat the compliance table's threshold as
    its own justification, which passes every row by construction.
    """
    if len(cells) >= 5:
        return cells[4]
    if len(cells) == 4 and "·" in cells[3]:
        return cells[3].split("·", 1)[1].strip()
    return ""


def _threshold_of(cells: list[str]) -> str:
    """The threshold, with any folded-in reason removed."""
    if len(cells) < 4:
        return ""
    threshold = cells[3]
    if len(cells) == 4 and "·" in threshold:
        threshold = threshold.split("·", 1)[0]
    return threshold.strip()


def check_gate_table() -> None:
    """The platform traceability table, held to the four rules it states."""
    if not GATES_TABLE.is_file():
        fail(f"missing {GATES_TABLE.relative_to(REPO_ROOT)} — there is no traceability table to check")
        return

    rows = [line for line in GATES_TABLE.read_text(encoding="utf-8").splitlines() if _GATE_ROW.match(line)]
    if not rows:
        fail("the traceability table declares no gate rows — every check below would pass over nothing")
        return

    seen: dict[str, str] = {}
    for row in rows:
        match = _GATE_ROW.match(row)
        if match is None:  # pragma: no cover — the rows were selected by this pattern
            continue
        gate_id = match.group(1)
        cells = _cells(row)
        claim = cells[1] if len(cells) > 1 else "<no claim>"

        if gate_id in seen:
            fail(
                f"gate id {gate_id} is used twice: {seen[gate_id]!r} and {claim!r}. "
                f"Ids are how gates are cited from CI, codecov and the compliance mapping — "
                f"a citation that resolves to two thresholds resolves to neither"
            )
        else:
            seen[gate_id] = claim

        threshold = _threshold_of(cells)
        if not threshold:
            fail(f"gate {gate_id} declares no threshold — there is nothing for it to fail against")
        elif "TODO" in threshold:
            fail(
                f"gate {gate_id} has a TODO threshold. A TODO reads as coverage while gating nothing, "
                f"which is worse than an absent gate (PROJECT_CONTRACT P6)"
            )

        reason = _reason_of(cells)
        if _BARE_SCHEDULE.match(reason):
            fail(
                f"gate {gate_id} gives a phase where a reason belongs: {reason!r}. That says WHEN the "
                f"gate arrives, never why the threshold holds its value — and the threshold is what "
                f"someone will be tempted to lower"
            )
        elif len(reason) < MIN_REASON_CHARS:
            fail(
                f"gate {gate_id} records no reason for its threshold ({len(reason)} chars). "
                f"quality-gates.md rule 4: a threshold inherited from an example is an undocumented "
                f"decision, and the first person it blocks will lower it"
            )

    # Descriptive, never a verdict. An `ok` line asserting "ids unique" prints
    # alongside a duplicate-id failure and contradicts it in the same output,
    # which teaches a reader to skim past both.
    ok(f"traceability table: {len(rows)} gate rows examined, {len(seen)} distinct ids")


def _gates_files() -> list[Path]:
    """Every `evals/gates.yaml` that exists under `projects/`.

    Deliberately NOT filtered by whether the project is exempt from P6.
    `tests/test_project_contract.py` skips a deviated project entirely, so a
    malformed gates file inside one is validated by nothing at all.
    """
    if not PROJECTS_DIR.is_dir():
        return []
    return sorted(PROJECTS_DIR.glob("*/evals/gates.yaml"))


def check_project_gates() -> None:
    """Every declared project gate is computable and carries its reason."""
    files = _gates_files()
    if not files:
        fail(
            f"no evals/gates.yaml under {PROJECTS_DIR.relative_to(REPO_ROOT)}/ — either the verticals "
            f"lost their gate declarations, or this check is looking in the wrong place"
        )
        return

    total = 0
    for path in files:
        rel = path.relative_to(REPO_ROOT)
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            fail(f"{rel}: not parseable as YAML — {error}")
            continue
        if not isinstance(document, dict):
            fail(f"{rel}: top level is {type(document).__name__}, not a mapping")
            continue

        entries = document.get("gates") or []
        if not entries:
            fail(f"{rel}: declares no gates. A gates file with no gates reads as coverage and is none")
            continue

        ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                fail(f"{rel}: a gate entry is {type(entry).__name__}, not a mapping")
                continue
            total += 1
            gate_id = str(entry.get("id") or "<no id>")
            if gate_id in ids:
                fail(f"{rel}: gate id {gate_id!r} appears twice — one of the two is invisible")
            ids.add(gate_id)

            for field in REQUIRED_GATE_FIELDS:
                value = entry.get(field)
                if value is None:
                    fail(f"{rel}: gate {gate_id!r} has no {field}")
                elif "TODO" in str(value):
                    fail(f"{rel}: gate {gate_id!r} still carries TODO in {field}")

            check = entry.get("check")
            if not check or "TODO" in str(check):
                continue
            target, _, symbol = str(check).partition("::")
            resolved = REPO_ROOT / target
            if not resolved.is_file():
                fail(
                    f"{rel}: gate {gate_id!r} names check {target}, which does not exist. "
                    f"A path that is merely non-empty lets a plausible-looking filename satisfy the "
                    f"contract while computing nothing"
                )
            elif symbol and symbol not in resolved.read_text(encoding="utf-8"):
                fail(f"{rel}: gate {gate_id!r} names {symbol!r}, which is absent from {target}")

    ok(f"project gates: {total} gate(s) across {len(files)} file(s), each naming a check that resolves")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="list what was examined and exit 0")
    args = parser.parse_args(argv)

    check_gate_table()
    check_project_gates()

    if args.report:
        for note in notes:
            print(f"  ok   [gates] {note}")
        for failure in failures:
            print(f"  note [gates] would fail: {failure}")
        return 0

    for note in notes:
        print(f"  ok   [gates] {note}")
    for failure in failures:
        print(f"  FAIL [gates] {failure}")

    if failures:
        print(f"\n[gates] FAILED — {len(failures)} finding(s)")
        return 1
    print("\n[gates] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
