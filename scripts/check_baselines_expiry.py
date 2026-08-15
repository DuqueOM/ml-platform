#!/usr/bin/env python3
"""`.security-baselines/README.md` states a four-part contract. Nothing enforced it.

Every entry in a scanner baseline must carry, all four: the finding ID exactly
as the tool reports it and never a wildcard; the reason it is accepted rather
than fixed; an owner as a GitHub handle, a person rather than a team; and an
expiry date no more than one quarter out. The README also says, in its own
words, that "an expired entry is a finding in itself — not a warning, not a
nag". That sentence had no gate behind it, which is the same shape as the
`install_mode` rule the MCP registry declared and never checked.

**Every baseline file here is currently empty, and that is exactly why the way
this is written matters.** A check that walks an empty directory and prints OK
is anti-pattern P-09: it passes because the thing it guards is absent, and it
will keep passing on the day the first suppression lands badly annotated. So:

* The summary always states the count it found — "3 file(s), 0 entr(ies)" —
  because a zero that is printed can be noticed, and a zero that is implied by
  a green tick cannot.
* Entries in the YAML baselines are read with the YAML parser, from the same
  `skip-check` / `exclude` keys the scanners read. A regex that stopped
  matching would produce a silent zero; the parser cannot, because it is the
  scanner's own view of what is suppressed.
* `tests/test_baselines_expiry.py` plants each malformed shape — expired, no
  expiry, no owner, expiry beyond a quarter, wildcard ID — and requires a
  non-zero exit for every one. The gate has been watched failing on all five.

Annotations sit as comments directly above or beside the entry, which is the
form the README documents:

    skip-check:
      # expiry: 2026-11-13  owner: @handle
      # reason: <why this cannot be fixed now, and what would make it fixable>
      - CKV_GCP_20

    uv run python scripts/check_baselines_expiry.py
    uv run python scripts/check_baselines_expiry.py --as-of 2026-12-01   # dry-run a date
    uv run python scripts/check_baselines_expiry.py --dir path/to/baselines
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / ".security-baselines"

#: YAML baseline -> the key the scanner reads its suppressions from. Reading the
#: scanner's own key means "how many entries are there" is answered by the
#: parser rather than by a pattern that could quietly stop matching.
#: File -> every key under which that scanner accepts a suppression.
#:
#: One key per file was the original shape, and QA-4 round four found what it
#: cost: Checkov also honours `skip-path`, which silences an entire directory
#: rather than one rule, and the gate could not see it. An entry there
#: produced "0 entr(ies) examined" and exit 0 — the gate reporting that it had
#: nothing to check while a BROADER suppression than any it does check sat one
#: line away.
#:
#: That is worse than an ordinary gap because of what the gate says next:
#: "armed, not satisfied" is the strongest anti-P-09 language in this
#: repository, and it was overstating its own coverage.
YAML_BASELINES: dict[str, tuple[str, ...]] = {
    "checkov.yml": ("skip-check", "skip-path"),
    "tfsec.yml": ("exclude",),
}

#: Checkov's third form: `# checkov:skip=CKV_XXX_NN:reason` at the resource.
#: `.security-baselines/checkov.yml` RECOMMENDS it in preference to a
#: repository-wide skip — and nothing read it, so the form the documentation
#: pushes people toward was the one form with no expiry, no owner and no
#: review date.
INLINE_SKIP = re.compile(r"#\s*checkov:skip=(?P<check>CKV[\w]*)(?::(?P<reason>[^\n]*))?")

#: Where an inline skip can legitimately appear. Restricted to infrastructure
#: so the scan does not read every Python file looking for a comment shape.
INLINE_SCAN_ROOTS = ("platform", "projects", "services")

#: Trivy takes a plain list: one ID per line, `#` for comments.
TRIVY_BASELINE = ".trivyignore"

#: The longest an acceptance may run before it is re-argued. The README says
#: "no more than one quarter out"; a quarter is 90 to 92 days, and 100 leaves
#: room for an entry written for the end of next quarter without turning a
#: good-faith date into a calendar argument. Raising this is a loosening, and
#: it is watched by scripts/check_thresholds.py.
MAX_EXPIRY_DAYS = 100

_EXPIRY = re.compile(r"#.*?\bexpiry:\s*(\S+)", re.IGNORECASE)
_OWNER = re.compile(r"#.*?\bowner:\s*(\S+)", re.IGNORECASE)
_REASON = re.compile(r"#.*?\breason:\s*(\S.*)", re.IGNORECASE)
_HANDLE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]{0,38}$")

failures: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    """Record a finding. Every finding fails the run."""
    failures.append(message)


def ok(message: str) -> None:
    """Record what was examined, printed whether or not the run passed."""
    notes.append(message)


def _annotation_window(lines: list[str], index: int) -> str:
    """The comment text an entry's annotation may occupy.

    The entry's own line, plus the unbroken run of comment lines immediately
    above it. Stopping at the first non-comment line is what keeps one entry
    from borrowing the annotation of the entry before it — which would let a
    single well-documented suppression legitimise every one that followed.
    """
    window = [lines[index]]
    cursor = index - 1
    while cursor >= 0 and lines[cursor].strip().startswith("#"):
        window.append(lines[cursor])
        cursor -= 1
    return "\n".join(window)


def _check_annotation(where: str, entry: str, window: str, today: dt.date) -> None:
    """Hold one entry to the four things the README says every entry carries."""
    if "*" in entry or "?" in entry:
        fail(
            f"{where}: {entry!r} is a wildcard. A rule that fires once today fires on new code "
            f"tomorrow, and a pattern here silences both — suppress the finding, not the rule"
        )

    reason = _REASON.search(window)
    if not reason or len(reason.group(1).strip()) < 10:
        fail(f"{where}: {entry!r} has no `reason:`. 'Fixing it is work' is not one, and neither is silence")

    owner = _OWNER.search(window)
    if not owner:
        fail(f"{where}: {entry!r} has no `owner:`. An acceptance with nobody to ask is one nobody revisits")
    elif not _HANDLE.match(owner.group(1)):
        fail(
            f"{where}: {entry!r} names owner {owner.group(1)!r}, which is not a GitHub handle. "
            f"A team or a role is not a person, and a role cannot be asked why"
        )

    expiry = _EXPIRY.search(window)
    if not expiry:
        fail(
            f"{where}: {entry!r} has no `expiry:`. A suppression with no expiry outlives the deadline, "
            f"the release and usually the person, and every reader after that assumes it was considered"
        )
        return

    try:
        date = dt.date.fromisoformat(expiry.group(1))
    except ValueError:
        fail(f"{where}: {entry!r} has expiry {expiry.group(1)!r}, which is not an ISO YYYY-MM-DD date")
        return

    if date < today:
        fail(
            f"{where}: {entry!r} expired on {date.isoformat()}. Reaching the date means the acceptance "
            f"was never revisited, and an unrevisited acceptance is indistinguishable from an unnoticed one"
        )
    elif (date - today).days > MAX_EXPIRY_DAYS:
        fail(
            f"{where}: {entry!r} expires on {date.isoformat()}, {(date - today).days} days out. The "
            f"README caps an acceptance at one quarter ({MAX_EXPIRY_DAYS} days) so that extending it "
            f"costs a minute of thought and leaves a trace in the diff"
        )


def _scan_yaml(path: Path, key: str, today: dt.date) -> int:
    """Check one YAML baseline. Returns the number of entries examined."""
    import yaml

    text = path.read_text(encoding="utf-8")
    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        fail(f"{path.name}: not parseable as YAML — {error}. The scanner cannot read it either")
        return 0
    if not isinstance(document, dict):
        fail(f"{path.name}: top level is {type(document).__name__}, not a mapping")
        return 0

    entries = document.get(key) or []
    if not isinstance(entries, list):
        fail(f"{path.name}: `{key}` is {type(entries).__name__}, not a list")
        return 0

    lines = text.splitlines()
    for entry in entries:
        name = str(entry)
        # Located by the entry's own text, so the annotation read is the one
        # written next to THAT entry rather than the file's first comment.
        index = next((i for i, line in enumerate(lines) if line.strip().startswith("-") and name in line), None)
        if index is None:
            fail(f"{path.name}: {name!r} is suppressed but its line cannot be located, so its annotation is unreadable")
            continue
        _check_annotation(path.name, name, _annotation_window(lines, index), today)
    return len(entries)


def _scan_trivy(path: Path, today: dt.date) -> int:
    """Check the Trivy ignore file. Returns the number of entries examined."""
    lines = path.read_text(encoding="utf-8").splitlines()
    count = 0
    for index, raw in enumerate(lines):
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        count += 1
        _check_annotation(path.name, entry, _annotation_window(lines, index), today)
    return count


def check_baselines(directory: Path, today: dt.date) -> None:
    """Every baseline file in `directory`, held to the README's contract."""
    if not directory.is_dir():
        fail(
            f"missing {directory} — the baselines directory is where an accepted finding is recorded "
            f"with its reason and its date. Without it, the only way to quiet a scanner is to weaken it"
        )
        return

    readme = directory / "README.md"
    if not readme.is_file():
        fail(f"{directory.name}/README.md is missing — the contract every entry is held to lives there")

    examined = 0
    files = 0
    for name, keys in YAML_BASELINES.items():
        path = directory / name
        if not path.is_file():
            fail(f"{name} is declared in the baselines README and is absent, so its findings have nowhere to go")
            continue
        files += 1
        for key in keys:
            examined += _scan_yaml(path, key, today)

    trivy = directory / TRIVY_BASELINE
    if trivy.is_file():
        files += 1
        examined += _scan_trivy(trivy, today)
    else:
        fail(f"{TRIVY_BASELINE} is declared in the baselines README and is absent")

    inline = _scan_inline_skips(directory.parent)
    examined += inline

    # Stated, never implied. A green tick over an empty directory is the
    # pass-because-absent shape; a printed zero is a fact a reader can act on.
    ok(f"{files} baseline file(s), {examined} entr(ies) examined as of {today.isoformat()} ({inline} inline)")
    if examined == 0 and not failures:
        ok("no suppressions exist, so none can be expired — this gate is armed, not satisfied")


def _scan_inline_skips(repo_root: Path) -> int:
    """Count `# checkov:skip=` comments, and fail any that carries no reason.

    These cannot expire: the form has nowhere to put a date or an owner. That
    is precisely why they need reporting rather than ignoring — a suppression
    with no review date is permanent by construction, and this one is the form
    `.security-baselines/checkov.yml` tells people to PREFER.

    So the contract enforced here is the strongest the syntax allows: a reason
    must be present, and every inline skip is counted into the total so the
    gate's headline number stops implying that the YAML files are the whole
    suppression surface.

    Requiring an expiry would mean requiring a comment convention Checkov does
    not parse, which is a defensible next step and a different decision from
    this one. It is not made here.
    """
    found = 0
    for root in INLINE_SCAN_ROOTS:
        directory = repo_root / root
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in {".tf", ".yaml", ".yml", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in INLINE_SKIP.finditer(text):
                found += 1
                if not (match.group("reason") or "").strip():
                    fail(
                        f"{path.relative_to(repo_root)}: inline `{match.group('check')}` skip carries no reason. "
                        f"An inline skip cannot expire, so the reason is the only thing a reviewer has"
                    )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="baselines directory to check")
    parser.add_argument("--as-of", default=None, help="ISO date to evaluate against, to dry-run a future date")
    args = parser.parse_args(argv)

    try:
        today = dt.date.fromisoformat(args.as_of) if args.as_of else dt.datetime.now(dt.UTC).date()
    except ValueError:
        print(f"[baselines] --as-of {args.as_of!r} is not an ISO YYYY-MM-DD date")
        return 2

    check_baselines(args.dir, today)

    for note in notes:
        print(f"  ok   [baselines] {note}")
    for failure in failures:
        print(f"  FAIL [baselines] {failure}")

    if failures:
        print(f"\n[baselines] FAILED — {len(failures)} finding(s)")
        print("  Fix the underlying issue and delete the entry, or write a fresh justification with a")
        print("  fresh date and a fresh look at whether the reason still holds (.security-baselines/README.md).")
        return 1
    print("\n[baselines] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
