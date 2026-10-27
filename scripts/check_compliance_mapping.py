#!/usr/bin/env python3
"""The compliance mapping states only what the tree supports, and nothing goes stale silently.

Quality gate C3. `docs/COMPLIANCE_MAPPING.md` is a NIST CSF 2.0 self-assessment, and
for two months nothing generated or checked it. QA-4 round sixteen found one
row still denying a measurement that had been taken, and reading the rest for
that correction found six more statements the tree had overtaken: Bandit
"invoked by no workflow" while CI ran it blocking, Trivy "cannot fail a build"
while it blocked on HIGH, `.security-baselines/` "holds zero entries", C7 "red
at 37 commits", "55 audit entries", "9 ADRs". Every one understated the
controls, which is the direction nobody notices — and a mapping is read by
someone deciding what they inherit, so a false picture costs them either way.

The figures are therefore not typed. This reads the mapping against the tree in
six ways, each a way it has already been wrong:

- **Structure** — every one of CSF 2.0's 22 Categories has exactly one row
  with exactly one of the three verdicts, and the counted summary agrees with
  the rows.
- **Derived figures** — a generated block lists every figure the mapping rests
  on, each computed here from the file that owns it. `--write` regenerates it;
  the check fails when the committed block differs.
- **Quoted figures** — a count in the prose ("23 rules", "11 ADRs",
  "**0 at L4**") must equal the derived one, so the prose cannot keep a number
  the block has moved past.
- **Dated measurements** — a figure this cannot derive offline (a Checkov run)
  or that moves with every commit (C7's count, the audit trail's length) may
  appear only in a paragraph that carries the ISO date it was measured on. An
  undated one reads as current forever. `SECURITY.md` and `docs/ADOPTION.md`
  quote the same Checkov measurement, so they are held to this rule too.
- **Scanner claims** — a sentence saying a scanner blocks, or does not, must
  agree with the Blocking column of `SECURITY.md`, which
  `tests/test_security_controls.py` checks against every workflow step.
- **Evidence** — a `path::name` citation names a function or class that exists
  in that file. Paths alone are checked by `tests/test_documentation_set.py`.

Deterministic and offline: no network, no subprocess, no clock.

    uv run python scripts/check_compliance_mapping.py            # check (CI)
    uv run python scripts/check_compliance_mapping.py --write    # regenerate the derived block
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_doc_coherence import agentic_counts  # the C5 count, so both gates count alike
from validate_quality_gates import _GATE_ROW, GATES_TABLE

REPO_ROOT = Path(__file__).resolve().parent.parent
MAPPING = REPO_ROOT / "docs" / "COMPLIANCE_MAPPING.md"
SECURITY = REPO_ROOT / "SECURITY.md"
STATUS_DOC = REPO_ROOT / "docs" / "architecture" / "implementation-status.md"
DECISIONS = REPO_ROOT / "docs" / "decisions"
BASELINES = REPO_ROOT / ".security-baselines"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
BRANCH_PROTECTION = REPO_ROOT / "scripts" / "setup_branch_protection.sh"

#: Documents that quote the same scanner measurement as the mapping. The
#: Checkov count stood undated in all three — "currently finds 114" — and was
#: 104 when re-measured, so the dated-measurement rule holds them too.
QUOTE_THE_SAME_MEASUREMENTS = (SECURITY, REPO_ROOT / "docs" / "ADOPTION.md")

BEGIN = "<!-- BEGIN DERIVED FIGURES -->"
END = "<!-- END DERIVED FIGURES -->"

#: NIST CSF 2.0's 22 Categories, by Function. Fixed by the framework, not by
#: this repository — a row for an id outside this set cites a control that
#: does not exist, and a missing one is a control nobody assessed.
CATEGORIES = (
    "GV.OC",
    "GV.RM",
    "GV.RR",
    "GV.PO",
    "GV.OV",
    "GV.SC",
    "ID.AM",
    "ID.RA",
    "ID.IM",
    "PR.AA",
    "PR.AT",
    "PR.DS",
    "PR.PS",
    "PR.IR",
    "DE.CM",
    "DE.AE",
    "RS.MA",
    "RS.AN",
    "RS.CO",
    "RS.MI",
    "RC.RP",
    "RC.CO",
)
VERDICTS = ("Satisfied", "Partial", "Not satisfied")

_CATEGORY_ROW = re.compile(r"^\|\s*\*\*([A-Z]{2}\.[A-Z]{2})\*\*")
_COUNTED = "## The result, counted"
_ISO_DATE = re.compile(r"\b20\d{2}-[01]\d-[0-3]\d\b")
_SYMBOL_CITATION = re.compile(r"`([A-Za-z0-9_./-]+\.py)::([A-Za-z_][A-Za-z0-9_]*)")

_LAYERS = re.compile(
    r"\*\*Proven in CI: (\d+) at L1 · (\d+) at L2\.\*\* Evidence available but NOT run here: (\d+) at L3, (\d+) at L4\."
)
_STATUS_ROW_LAYER = re.compile(r"^\|\s*\S+\s*\|\s*(L[0-4])\s*\|", re.MULTILINE)

#: Steps that would build, sign, attest or describe an image. Matched on the
#: action a step `uses:` and on the commands its `run:` invokes — never on a
#: step's name or a comment, which describe intent.
_IMAGE_ACTIONS = (
    "docker/build-push-action",
    "sigstore/cosign-installer",
    "actions/attest-build-provenance",
    "anchore/sbom-action",
)
_IMAGE_COMMANDS = re.compile(r"(?:^|[\s;&|(])(?:docker\s+(?:build|buildx)|podman\s+build|cosign|syft)\s", re.MULTILINE)


# --- derived figures --------------------------------------------------------


@dataclass(frozen=True)
class Figure:
    """One number the mapping rests on, and where it comes from."""

    key: str
    label: str
    value: str
    source: str


def _security_controls(text: str) -> dict[str, bool]:
    """`{tool: blocks}` from SECURITY.md's controls table.

    Read rather than re-derived from the workflows: that table's Blocking
    column is already compared with every workflow step by
    `tests/test_security_controls.py`, so this inherits that comparison
    instead of keeping a second, weaker copy of it.
    """
    start = text.find("## What this repository does about security")
    if start < 0:
        return {}
    controls: dict[str, bool] = {}
    for line in text[start:].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] == "Control" or set(cells[1]) <= {"-", ":"}:
            continue
        controls[cells[1]] = cells[2].replace("*", "").strip().lower() == "yes"
    return controls


def _baseline_entries() -> dict[str, int]:
    """Accepted findings per baseline file: the scanner's own suppression list, counted."""
    entries: dict[str, int] = {}
    trivy = BASELINES / ".trivyignore"
    if trivy.is_file():
        lines = (line.split("#", 1)[0].strip() for line in trivy.read_text(encoding="utf-8").splitlines())
        entries["Trivy"] = sum(1 for line in lines if line)
    for name, path, key in (("Checkov", "checkov.yml", "skip-check"), ("tfsec", "tfsec.yml", "exclude")):
        file = BASELINES / path
        if file.is_file():
            document = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            entries[name] = len(document.get(key) or [])
    return entries


def _workflow_steps() -> list[dict]:  # type: ignore[type-arg]
    steps: list[dict] = []  # type: ignore[type-arg]
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (document.get("jobs") or {}).values():
            steps.extend(job.get("steps") or [])
    return steps


def _image_steps() -> int:
    """Workflow steps that build, sign, attest or inventory a container image."""
    found = 0
    for step in _workflow_steps():
        action = str(step.get("uses", "")).split("@", 1)[0]
        commands = "\n".join(
            line for line in str(step.get("run", "")).splitlines() if not line.lstrip().startswith("#")
        )
        if action in _IMAGE_ACTIONS or _IMAGE_COMMANDS.search(commands + "\n"):
            found += 1
    return found


def _required_checks() -> tuple[list[str], int]:
    """The status checks and approving-review count the protection payload requires."""
    text = BRANCH_PROTECTION.read_text(encoding="utf-8")
    block = re.search(r"REQUIRED_CHECKS=\((.*?)\)", text, re.DOTALL)
    checks = re.findall(r'"([^"]+)"', block.group(1)) if block else []
    reviews = re.search(r'"required_approving_review_count":\s*(\d+)', text)
    return checks, int(reviews.group(1)) if reviews else -1


def _merge_waits_on() -> tuple[int, int, list[str]]:
    """CI jobs a merge waits on, of all CI jobs, and those it does not wait on.

    A job waits the merge if its name is a required check, or if a required
    job needs it AND asserts its result — `needs` alone is not enough, because
    an aggregator running `if: always()` succeeds over a failed dependency
    unless its own step reads `needs.<job>.result`.
    """
    required, _ = _required_checks()
    jobs = (yaml.safe_load(CI.read_text(encoding="utf-8")) or {}).get("jobs") or {}
    covered = {key for key, job in jobs.items() if job.get("name", key) in required}
    for key in list(covered):
        job = jobs[key]
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        body = "\n".join(str(step.get("run", "")) for step in job.get("steps") or [])
        covered.update(dependency for dependency in needs if f"needs.{dependency}.result" in body)
    missing = sorted(str(jobs[key].get("name", key)) for key in jobs if key not in covered)
    return len(covered & set(jobs)), len(jobs), missing


def derive() -> list[Figure]:
    """Every figure the mapping rests on, computed from the file that owns it."""
    counts = agentic_counts()
    adrs = sum(1 for path in DECISIONS.glob("ADR-*.md") if re.match(r"^ADR-\d{3}-", path.name))
    gate_rows = [line for line in GATES_TABLE.read_text(encoding="utf-8").splitlines() if _GATE_ROW.match(line)]
    pending = sum(1 for row in gate_rows if "⏳" in row.split("|")[1])

    status = STATUS_DOC.read_text(encoding="utf-8")
    layers = _LAYERS.search(status)
    displayed = _STATUS_ROW_LAYER.findall(status)
    shown_at_l4 = sum(1 for layer in displayed if layer == "L4")
    l4_evidence = layers.group(4) if layers else "unreadable"

    controls = _security_controls(SECURITY.read_text(encoding="utf-8"))
    blocking = sorted(tool for tool, blocks in controls.items() if blocks)
    advisory = sorted(tool for tool, blocks in controls.items() if not blocks)
    baselines = _baseline_entries()
    checks, reviews = _required_checks()
    waited, jobs, unwaited = _merge_waits_on()

    return [
        Figure("rules", "Agentic rules", str(counts["rules"]), "`agentic/rules/*.md`"),
        Figure("skills", "Agentic skills", str(counts["skills"]), "`agentic/skills/*/`"),
        Figure("workflows", "Agentic workflows", str(counts["workflows"]), "`agentic/workflows/*.md`"),
        Figure("adrs", "ADRs", str(adrs), "`docs/decisions/ADR-*.md`"),
        Figure("gates", "Declared gates", str(len(gate_rows)), "`docs/governance/quality-gates.md`"),
        Figure("pending_gates", "Declared gates marked ⏳ PENDING", str(pending), "the same table"),
        Figure(
            "l4",
            "Components shown at L4 (a real cloud rollout)",
            str(shown_at_l4),
            "`docs/architecture/implementation-status.md`, generated",
        ),
        Figure("l4_evidence", "Components with L4 evidence written down", l4_evidence, "the same document"),
        Figure("blocking", "Security controls that block a merge", ", ".join(blocking) or "none", "`SECURITY.md`"),
        Figure("advisory", "Security controls that only report", ", ".join(advisory) or "none", "`SECURITY.md`"),
        *(
            Figure(f"baseline_{name.lower()}", f"Accepted {name} findings", str(count), "`.security-baselines/`")
            for name, count in sorted(baselines.items())
        ),
        Figure(
            "image_steps",
            "Workflow steps that build, sign or attest an image",
            str(_image_steps()),
            "`.github/workflows/*.yml`",
        ),
        Figure("required_checks", "Required status checks", str(len(checks)), "`scripts/setup_branch_protection.sh`"),
        Figure(
            "merge_waits_on",
            "CI jobs a merge waits on",
            f"{waited} of {jobs}" + (f" (not: {', '.join(unwaited)})" if unwaited else ""),
            "`.github/workflows/ci.yml`, through the required checks",
        ),
        Figure("reviews", "Approving reviews required", str(reviews), "`scripts/setup_branch_protection.sh`"),
    ]


def render(figures: list[Figure]) -> str:
    rows = "\n".join(f"| {figure.label} | {figure.value} | {figure.source} |" for figure in figures)
    return (
        f"{BEGIN}\n"
        "<!-- Generated by scripts/check_compliance_mapping.py --write. Do not edit by hand. -->\n\n"
        "| Figure | Value | Derived from |\n"
        "| --- | :-: | --- |\n"
        f"{rows}\n"
        f"{END}"
    )


def _replace(text: str, block: str) -> str | None:
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        return None
    return text[:start] + block + text[end + len(END) :]


# --- the checks -------------------------------------------------------------


def check_structure(text: str) -> list[str]:
    """22 Categories, one row each, one verdict each, and a summary that agrees."""
    failures = []
    verdicts: dict[str, str] = {}
    for line in text.splitlines():
        match = _CATEGORY_ROW.match(line)
        if not match:
            continue
        category = match.group(1)
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        verdict = cells[2] if len(cells) > 2 else ""
        if category not in CATEGORIES:
            failures.append(f"row {category} is not a NIST CSF 2.0 Category — it cites a control that does not exist")
        elif category in verdicts:
            failures.append(f"{category} has two rows; a Category assessed twice is assessed neither way")
        if verdict not in VERDICTS:
            failures.append(f"{category} has verdict {verdict!r}; the three verdicts are {', '.join(VERDICTS)}")
        verdicts.setdefault(category, verdict)

    for category in CATEGORIES:
        if category not in verdicts:
            failures.append(f"{category} has no row — a Category nobody assessed reads as one that passed")

    start = text.find(_COUNTED)
    if start < 0:
        failures.append(f"no {_COUNTED!r} section — the summary a reader reads first is missing")
        return failures
    summary: dict[str, set[str]] = {}
    for line in text[start:].split("\n## ", 1)[0].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] in VERDICTS:
            listed = {item.strip() for item in cells[2].split(",") if item.strip()}
            summary[cells[0]] = listed
            if not cells[1].isdigit() or int(cells[1]) != len(listed):
                failures.append(f"summary row {cells[0]} says {cells[1]} and lists {len(listed)}")
    for verdict in VERDICTS:
        actual = {category for category, given in verdicts.items() if given == verdict}
        stated = summary.get(verdict, set())
        if actual != stated:
            failures.append(
                f"summary row {verdict} lists {sorted(stated)} but the rows say {sorted(actual)} — "
                f"the count a reader quotes is not the assessment"
            )
    return failures


#: A count the prose may quote, and the derived figure it must equal.
QUOTED = (
    (re.compile(r"\b(\d+) rules\b"), "rules"),
    (re.compile(r"\b(\d+) skills\b"), "skills"),
    (re.compile(r"\b(\d+) workflows\b"), "workflows"),
    (re.compile(r"\b(\d+) ADRs\b"), "adrs"),
    (re.compile(r"\b(\d+) declared gates\b"), "gates"),
    (re.compile(r"\*\*(\d+) at L4\*\*"), "l4"),
)

#: Figures that cannot be derived here or that move with every commit. Each
#: may stand only beside the date it was measured on.
DATED = (
    (re.compile(r"\b\d+ commits\b"), "a commit count moves with every merge; C7 prints the current one"),
    (re.compile(r"\b\d+ (?:audit )?entries\b"), "the audit trail grows with every recorded decision"),
    (re.compile(r"\b\d+ (?:failed checks|Checkov findings|findings)\b"), "a scanner count needs the scanner"),
)


def _prose(text: str) -> str:
    """The document with the generated block removed — the figures there are the source, not a quotation."""
    start, end = text.find(BEGIN), text.find(END)
    return text if start < 0 or end < start else text[:start] + text[end + len(END) :]


def check_quoted_figures(text: str, figures: dict[str, str]) -> list[str]:
    failures = []
    prose = _prose(text)
    for pattern, key in QUOTED:
        for match in pattern.finditer(prose):
            if match.group(1) != figures[key]:
                failures.append(
                    f"the prose says {match.group(0)!r}; the tree says {figures[key]} (the derived block's {key!r})"
                )
    return failures


def check_dated_measurements(text: str, name: str) -> list[str]:
    """A figure nothing here can re-derive stands only beside the date it was measured on."""
    failures = []
    for paragraph in re.split(r"\n\s*\n", _prose(text)):
        if _ISO_DATE.search(paragraph):
            continue
        for pattern, reason in DATED:
            for match in pattern.finditer(paragraph):
                failures.append(
                    f"{name}: {match.group(0)!r} carries no date. {reason}; state the date it was "
                    f"measured in the same paragraph, or cite the command instead of the number"
                )
    return failures


#: Phrases that, in the clause after a scanner's name, claim it does or does
#: not fail a build. Present tense only: the record of what WAS true is kept
#: in the past tense, and a past-tense sentence is not a claim about today.
_ADVISORY_CLAIM = re.compile(
    r"\b(?:cannot fail|can ?not fail|cannot block|does not block|do not block|doesn't block|is advisory|"
    r"are advisory|is not blocking|never fails|reports and does not block|invoked by no workflow|"
    r"wired to no workflow|runs in no workflow|cannot fail a build)\b",
    re.IGNORECASE,
)
_BLOCKING_CLAIM = re.compile(
    r"\b(?:blocks|is blocking|are blocking|fails the build|fails a build|can fail a build)\b", re.IGNORECASE
)
_CLAUSE_END = re.compile(r"(?<=[.;!?])\s|\||\n\s*\n")


def check_scanner_claims(text: str, controls: dict[str, bool]) -> list[str]:
    """A sentence about a scanner's blocking agrees with SECURITY.md's Blocking column.

    The clause read for each mention runs from the scanner's name to the end of
    its sentence or table cell, or to the next scanner's name — so "Bandit and
    Trivy block; Checkov and Kubescape report" assigns each claim to the names
    it follows, not to every name in the sentence.
    """
    failures = []
    prose = _prose(text)
    names = sorted(controls, key=len, reverse=True)
    if not names:
        return ["SECURITY.md's controls table could not be read — no scanner claim can be checked"]
    mention = re.compile(r"\b(" + "|".join(re.escape(name) for name in names) + r")\b")
    mentions = list(mention.finditer(prose))
    for index, match in enumerate(mentions):
        stop = len(prose)
        boundary = _CLAUSE_END.search(prose, match.end())
        if boundary:
            stop = boundary.start()
        if index + 1 < len(mentions):
            stop = min(stop, mentions[index + 1].start())
        clause = prose[match.end() : stop]
        tool = match.group(1)
        says_advisory = _ADVISORY_CLAIM.search(clause)
        says_blocking = None if says_advisory else _BLOCKING_CLAIM.search(clause)
        if controls[tool] and says_advisory:
            failures.append(
                f"{tool!r} is said not to block ({says_advisory.group(0)!r}), and SECURITY.md — checked "
                f"against the workflows — says it blocks: {(tool + clause).strip()[:120]!r}"
            )
        elif not controls[tool] and says_blocking:
            failures.append(
                f"{tool!r} is said to block ({says_blocking.group(0)!r}), and SECURITY.md — checked "
                f"against the workflows — says it only reports: {(tool + clause).strip()[:120]!r}"
            )
    return failures


def check_symbol_citations(text: str, root: Path = REPO_ROOT) -> list[str]:
    """`file.py::name` names a function or class defined in that file."""
    failures = []
    for path, name in sorted(set(_SYMBOL_CITATION.findall(text))):
        file = root / path
        if not file.is_file():
            failures.append(f"`{path}::{name}` cites a file that does not exist")
            continue
        source = file.read_text(encoding="utf-8")
        if not re.search(rf"^\s*(?:async\s+def|def|class)\s+{re.escape(name)}\b", source, re.MULTILINE):
            failures.append(f"`{path}::{name}` — {path} defines no {name}; the evidence cited is not there")
    return failures


def check(text: str, figures: list[Figure], controls: dict[str, bool]) -> list[str]:
    failures = []
    if _replace(text, render(figures)) is None:
        failures.append(f"no derived-figures block ({BEGIN} … {END}) — run with --write")
    elif _replace(text, render(figures)) != text:
        failures.append("the derived-figures block is stale — the tree moved; run with --write and reread the rows")
    failures += check_structure(text)
    failures += check_quoted_figures(text, {figure.key: figure.value for figure in figures})
    failures += check_dated_measurements(text, MAPPING.name)
    for document in QUOTE_THE_SAME_MEASUREMENTS:
        failures += check_dated_measurements(document.read_text(encoding="utf-8"), document.name)
    failures += check_scanner_claims(text, controls)
    failures += check_symbol_citations(text)
    return failures


def _display(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="regenerate the derived-figures block")
    args = parser.parse_args(argv)

    figures = derive()
    controls = _security_controls(SECURITY.read_text(encoding="utf-8"))
    text = MAPPING.read_text(encoding="utf-8")
    if args.write:
        updated = _replace(text, render(figures))
        if updated is None:
            print(f"  FAIL [compliance] {_display(MAPPING)} has no {BEGIN} … {END} block to regenerate")
            return 1
        if updated != text:
            MAPPING.write_text(updated, encoding="utf-8")
            print("[compliance] derived-figures block regenerated")
        text = updated

    failures = check(text, figures, controls)
    if failures:
        for failure in failures:
            print(f"  FAIL [compliance] {failure}")
        print(f"\n[compliance] FAILED — {_display(MAPPING)} states what the tree does not support")
        return 1
    print(f"[compliance] OK — {len(CATEGORIES)} Categories assessed, {len(figures)} figures derived and current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
