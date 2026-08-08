#!/usr/bin/env python3
"""Documentation coherence gate (ADR-005 rules C, D, H).

Nothing breaks when a document becomes false, so nothing reports it. This
script reports it, for the subset of coherence that is mechanically checkable.

What it CANNOT check is whether a claim is *true* — only whether documents
agree with each other and with the filesystem. Every serious documentation
defect found so far has been of the second kind: correspondence with reality,
not consistency between files. That gap is covered by the judgement steps in
`docs/governance/qa-procedures.md` (QA-5) and by the independent audit (QA-4),
which is why check C7 exists to keep the audit from going stale.

Exit code 1 on any failure. Run before declaring a round complete.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS = REPO_ROOT / "docs" / "decisions"
ADR_INDEX = DECISIONS / "README.md"
PLAN = REPO_ROOT / "docs" / "architecture" / "technical-plan.md"
GATES = REPO_ROOT / "docs" / "governance" / "quality-gates.md"
AGENTIC = REPO_ROOT / "agentic"

# How stale the independent-audit marker may become before it is a finding.
AUDIT_MAX_AGE_DAYS = 90

# Commits a repository may accumulate before the ABSENCE of an audit is itself
# a finding. Ten is the template's cadence, and it is short on purpose: an
# audit deferred until "there is enough to audit" is one deferred forever.
AUDIT_GRACE_COMMITS = 10

_ADR_FILE = re.compile(r"^ADR-(\d{3})-[a-z0-9-]+\.md$")
_ADR_REF = re.compile(r"(?<!template-)\bADR-(\d{3})")
# Inherited bodies use ml-service-template's numbering, namespaced so a
# reference can never silently resolve against the wrong index (ADR-002).
_INHERITED_ADR_REF = re.compile(r"\btemplate-ADR-(\d{3})")

failures: list[str] = []
notes: list[str] = []


def fail(check: str, message: str) -> None:
    failures.append(f"[{check}] {message}")


def ok(check: str, message: str) -> None:
    notes.append(f"[{check}] {message}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _rel_parts(path: Path) -> set[str]:
    """Path components *relative to the repository root*.

    Deliberately not ``path.parts``: the absolute path may contain a directory
    named like one being filtered on (this repository lives under a directory
    called ``projects``), which silently excludes every file and produces a
    check that passes without examining anything.
    """
    return set(path.relative_to(REPO_ROOT).parts)


def _is_scannable(path: Path, exclude: set[str] = frozenset()) -> bool:  # type: ignore[assignment]
    """True when a markdown file is part of the documentation surface."""
    parts = _rel_parts(path)
    generated = {".claude", ".cursor", ".codex", ".devin"}
    infra = {".git", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}
    return not (parts & (infra | generated | set(exclude)))


def _adr_files() -> dict[str, Path]:
    """Map ADR number -> file, for every ADR on disk."""
    found: dict[str, Path] = {}
    for path in sorted(DECISIONS.glob("ADR-*.md")):
        match = _ADR_FILE.match(path.name)
        if match:
            found[match.group(1)] = path
        else:
            fail("C1", f"{path.name} does not match ADR-NNN-kebab-title.md")
    return found


def check_adr_index(adrs: dict[str, Path]) -> None:
    """C1 — every ADR on disk appears in the index, and vice versa."""
    index = _read(ADR_INDEX)
    if not index:
        fail("C1", f"missing ADR index: {ADR_INDEX.relative_to(REPO_ROOT)}")
        return

    indexed = set(_ADR_REF.findall(index))
    on_disk = set(adrs)

    for missing in sorted(on_disk - indexed):
        fail("C1", f"ADR-{missing} exists on disk but is absent from the index")
    for phantom in sorted(indexed - on_disk):
        fail("C1", f"the index references ADR-{phantom}, which does not exist")

    if on_disk and on_disk == indexed:
        ok("C1", f"{len(on_disk)} ADRs, index complete")


#: Where the template is checked out, when it is. Generated services cite its
#: ADRs, and resolving them needs its index — absent, the numbers are accepted
#: rather than reported, because failing on "I cannot reach the upstream index"
#: would make a network-free checkout look like a defect in the documents.
TEMPLATE_CHECKOUT = REPO_ROOT.parent / "template_MLOps"


def _template_adr_numbers() -> set[str]:
    """ADR numbers published by ml-service-template, when it is reachable."""
    decisions = TEMPLATE_CHECKOUT / "docs" / "decisions"
    if not decisions.is_dir():
        return set()
    return {match.group(1) for path in decisions.glob("ADR-*.md") if (match := _ADR_FILE.match(path.name))}


def check_no_dangling_refs(adrs: dict[str, Path]) -> None:
    """C2 — no document points at an ADR number that does not exist.

    A reference that silently resolves to nothing is worse than a broken link:
    a reader assumes the decision exists and was considered.
    """
    on_disk = set(adrs)
    template_adrs = _template_adr_numbers()
    scanned = 0
    foreign = 0
    unresolvable = 0

    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path):
            continue
        scanned += 1

        # `services/` holds code GENERATED from ml-service-template, and its
        # ADR numbers index the template's decisions rather than ours. They are
        # not dangling; they are foreign, and ADR-002 defines `template-ADR-NNN`
        # for exactly this.
        #
        # Resolved against the template's index rather than skipped. A blanket
        # path exclusion would also silence a reference to one of OUR ADRs
        # written by hand into a service, which is the case worth catching —
        # and reaching for a path exclusion is a reflex this repository has
        # already had to correct twice.
        generated = "services" in _rel_parts(path)

        for ref in set(_ADR_REF.findall(_read(path))):
            if generated:
                # The comment above promised this and the first version did not
                # do it: with no template checkout — every CI runner — the
                # index is EMPTY, so every foreign reference failed. A check
                # whose behaviour differs from its own stated behaviour is the
                # defect this repository keeps finding, here between a comment
                # and the code beneath it.
                if not template_adrs:
                    unresolvable += 1
                elif ref not in template_adrs:
                    fail(
                        "C2",
                        f"{path.relative_to(REPO_ROOT)} references ADR-{ref}, absent from "
                        "the template's index — it resolves against neither repository",
                    )
                else:
                    foreign += 1
                continue

            if ref not in on_disk:
                fail("C2", f"{path.relative_to(REPO_ROOT)} references ADR-{ref}, which does not exist")

    note = f"{scanned} markdown files scanned for dangling ADR references"
    if foreign:
        note += f"; {foreign} resolved against the template's index"
    if unresolvable:
        note += (
            f"; {unresolvable} in generated code NOT checked — no template checkout at "
            f"{TEMPLATE_CHECKOUT.name}/, so their index is unreachable here"
        )
    ok("C2", note)


def check_adrs_are_integrated(adrs: dict[str, Path]) -> None:
    """C3 — an accepted ADR is referenced from the plan or the index.

    An ADR that exists only as a file has not been integrated: nothing sequences
    its pending work and nothing points a reader at it. Creating the file is the
    easy half of accepting a decision.
    """
    plan = _read(PLAN)
    index = _read(ADR_INDEX)
    integrated = set(_ADR_REF.findall(plan)) | set(_ADR_REF.findall(index))

    for number, path in sorted(adrs.items()):
        body = _read(path)
        status = re.search(r"^-\s+\*\*Status\*\*:\s*(.+)$", body, re.MULTILINE)
        if not status:
            fail("C3", f"{path.name} has no '- **Status**:' line")
            continue
        if status.group(1).lower().startswith("accepted") and number not in integrated:
            fail("C3", f"ADR-{number} is Accepted but is referenced from neither the plan nor the index")
    ok("C3", "accepted ADRs are integrated")


def check_gate_traceability() -> None:
    """C4 — quality-gate rows carry a command and a threshold rationale.

    ADR-005 rule K: a metric that cannot fail a build is decoration. A row
    without a command cannot fail anything.
    """
    gates = _read(GATES)
    if not gates:
        fail("C4", f"missing {GATES.relative_to(REPO_ROOT)}")
        return

    # `[^|]*` after the id, not `\s*`. The previous pattern required the id to
    # be followed only by whitespace, so every row marked `| L3 ⏳ |` failed to
    # match and C4 never examined it: 14 rows seen, 15 invisible. The exclusion
    # I believed the `if "PENDING"` branch was performing was actually done by
    # accident, by a decorative glyph — and that branch was dead code.
    #
    # An independent audit found this. It is the same shape as the findings it
    # was looking for: the declared mechanism is not the operating one.
    rows = [line for line in gates.splitlines() if re.match(r"^\|\s*[PLSMAC]\d+[^|]*\|", line)]
    if not rows:
        fail("C4", "no gate rows found — the traceability table is empty")
        return

    # quality-gates.md states its own rule: "a row whose command does not
    # exist is a finding". Nothing enforced it. Testing for a BACKTICK reported
    # "28 gates declared with commands" while four of those commands named
    # scripts that were never written — a gate verifying other gates, passing
    # on formatting.
    script_ref = re.compile(r"scripts/[A-Za-z0-9_./-]+\.(?:py|sh)")
    for row in rows:
        gate_id = row.split("|")[1].strip()
        if "`" not in row:
            fail("C4", f"gate {gate_id} has no command — it cannot fail a build")
            continue
        if "PENDING" in row:
            # Declared but not yet runnable, and it says so in the table. The
            # finding is a command that does not exist while PRESENTING itself
            # as enforced.
            continue
        for referenced in script_ref.findall(row):
            if not (REPO_ROOT / referenced).is_file():
                fail("C4", f"gate {gate_id} runs {referenced}, which does not exist")
    ok("C4", f"{len(rows)} gates declared with commands that resolve")


def check_agentic_surface() -> None:
    """C5 — the agentic surface counts stated in AGENTS.md match the filesystem."""
    if not AGENTIC.is_dir():
        fail("C5", "agentic/ does not exist")
        return

    counts = {
        "rules": len(list((AGENTIC / "rules").glob("*.md"))) if (AGENTIC / "rules").is_dir() else 0,
        "skills": len([p for p in (AGENTIC / "skills").glob("*") if p.is_dir()])
        if (AGENTIC / "skills").is_dir()
        else 0,
        "workflows": len(list((AGENTIC / "workflows").glob("*.md"))) if (AGENTIC / "workflows").is_dir() else 0,
    }
    ok("C5", f"agentic surface: {counts['rules']} rules, {counts['skills']} skills, {counts['workflows']} workflows")

    for skill_dir in sorted(p for p in (AGENTIC / "skills").glob("*") if p.is_dir()):
        if not (skill_dir / "SKILL.md").is_file():
            fail("C5", f"skill {skill_dir.name} has no SKILL.md")


DENYLIST = REPO_ROOT / "docs" / "governance" / "private-names.sha256"
_TOKEN = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+|[a-z][a-z0-9]{5,}")


def _forbidden_hashes() -> set[str]:
    """Hashes of names that must never appear in a committed file.

    Stored as SHA-256 rather than plaintext for the obvious reason: the whole
    point is that the name is not in this repository. A hash commits to it
    without disclosing it, so the check needs no secret, no environment
    variable, and no local file that a fresh clone would be missing.
    """
    if not DENYLIST.is_file():
        return set()
    return {
        line.strip().lower()
        for line in DENYLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _check_forbidden_names() -> None:
    """Scan EVERY committed file for a denylisted name, not only markdown.

    The previous C6 matched `github.com/owner/repo` in `*.md`, excluding
    `projects/` — 105 of 331 committed markdown files, and no other file type.
    An independent audit showed that a bare name in prose, a URL in a `.py`,
    and a URL under `projects/` all passed. The bare name in prose is the most
    likely way the constraint actually gets broken, since it is the only form
    that fits inside a sentence.
    """
    forbidden = _forbidden_hashes()
    if not forbidden:
        return

    tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True)
    for rel in tracked.stdout.splitlines():
        path = REPO_ROOT / rel
        if not path.is_file() or rel == DENYLIST.relative_to(REPO_ROOT).as_posix():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for token in set(_TOKEN.findall(content)):
            if hashlib.sha256(token.encode()).hexdigest() in forbidden:
                # The name itself is never printed — doing so would commit it
                # to the CI log, which is public on a public repository.
                fail("C6", f"{rel} contains a denylisted private name (hash match). Remove it.")


def check_language_and_privacy() -> None:
    """C6 — the repository is public: English documentation, no private references.

    Scans for links to repositories outside the public lineage, and — via
    :func:`_check_forbidden_names` — for denylisted private names anywhere in
    the tracked tree.

    It does NOT detect non-English prose, though an earlier version of this
    docstring said it did. The English-only rule (AGENTS.md, template D-37) is
    real and currently unenforced; claiming otherwise here was worse than
    silence, because a reader would stop looking.
    """
    public_repos = {
        "ml-platform",
        "ml-service-template",
        "ML-MLOps-Portfolio",
        "agent-local",
        "DuqueOM",
        # Former name of ml-service-template. Public, and GitHub redirects it,
        # so a link still resolves — this check is about PRIVACY, and reporting
        # a redirecting public repo as a private leak sends the reader looking
        # for a disclosure that is not there.
        #
        # It is still a defect, of a different kind: three files in the
        # template's source carry the pre-rename name, so every generated
        # service inherits it. That belongs upstream, and C10 tracks it here
        # rather than letting a wrong label stand in for a real finding.
        "ML-MLOps-Production-Template",
    }
    repo_link = re.compile(r"github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)")
    scanned = 0

    _check_forbidden_names()

    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path, exclude={"projects"}):
            continue
        scanned += 1
        # `{owner}/{repo}` are literal placeholders the gh CLI substitutes itself;
        # they appear verbatim in documented commands.
        placeholders = {
            "OWNER",
            "REPO",
            "ORG",
            "USER",
            "your-org",
            "your-repo",
            "<owner>",
            "<repo>",
            "{owner}",
            "{repo}",
            # Generic stand-ins used when documenting this very check, and by
            # the gh CLI, which substitutes {owner}/{repo} itself.
            "owner",
            "repo",
        }
        # github.com/<reserved>/... are product URLs, not repository links.
        reserved = {
            "settings",
            "features",
            "orgs",
            "apps",
            "marketplace",
            "security",
            "enterprise",
            "pricing",
            "about",
            "site",
            "codespaces",
            "sponsors",
        }
        for owner, repo in repo_link.findall(_read(path)):
            repo = repo.removesuffix(".git")
            if owner in placeholders or repo in placeholders or owner in reserved:
                continue
            if repo not in public_repos:
                fail("C6", f"{path.relative_to(REPO_ROOT)} links to non-public repository {repo!r}")
    ok("C6", f"{scanned} files checked for private references")


_COPIER_COMMAND = re.compile(r"copier\s+(?:copy|update)\b(.*)", re.DOTALL)
_FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)


def _runnable_copier_commands(text: str) -> list[str]:
    """Copier invocations from FENCED blocks, with continuations joined.

    Two refinements the first version needed, both found by running it:

    Only fenced blocks count. Prose naming the subcommand — "scaffolded via
    `copier copy`" — is not a command anyone pastes, and a grep PATTERN that
    happens to contain the words is not one either. Flagging those trains the
    reader to skim past this check.

    Continuations are joined. A pinned command written across several lines
    with backslashes has its `--vcs-ref` on line two, and a line-at-a-time
    reading calls the correct command wrong. That false positive was in this
    repository's own runbook, on the very command the check exists to protect.
    """
    commands = []
    for block in _FENCE.findall(text):
        joined = re.sub(r"\\\n\s*", " ", block)
        commands += [
            f"copier {line.split('copier ', 1)[1]}"
            for line in joined.splitlines()
            # A shell COMMENT inside a fenced block is not a command. The
            # template's own comment explaining why the pin is needed —
            # "# --vcs-ref is REQUIRED: a bare `copier update` resolves to..." —
            # was reported as an unpinned command, which is this check flagging
            # the documentation that exists because of it.
            if "copier " in line and not line.lstrip().startswith("#")
        ]
    return commands


def check_copier_commands_are_pinned() -> None:
    """C9 — every documented copier command names a template version.

    Copier resolves an unpinned git source to the HIGHEST-SORTING TAG. The
    template carries frozen v1.x audit snapshots beside its active v0.x line,
    so an unpinned command serves a scaffold from months earlier — completely,
    plausibly, and without erroring. Upstream that defect survived the entire
    life of the v0.x line, because nothing checked the commands themselves.

    `copier update` unpinned is worse. `copy` hands over a stale scaffold;
    `update` rewrites a service that already exists, backwards. Upstream
    measured 582 files deleted on a real service, the answers file among them —
    the record `update` reads, so the service cannot then recover on its own.

    A LOCAL path source is exempt: `copier copy . projects/x` reads the working
    tree, which no tag can reorder. Requiring a ref there would be asking for a
    version of something that has none.
    """
    checked = 0
    upstream: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.md")):
        if not _is_scannable(path):
            continue
        for command in _runnable_copier_commands(_read(path)):
            source_is_local = re.search(r"\s(\.|\.\./|/)\S*", command) and "http" not in command
            if source_is_local:
                continue
            checked += 1
            if "--vcs-ref" in command:
                continue

            rel = path.relative_to(REPO_ROOT)
            if "services" in _rel_parts(path):
                # Generated code. We cannot fix it without editing a scaffold,
                # which ADR-003 forbids — that is a fork with extra steps. So it
                # is REPORTED rather than failed, and reported loudly: an
                # upstream defect that nobody names becomes an upstream defect
                # nobody fixes.
                upstream.append(f"{rel}: {command.strip()!r}")
                continue

            fail(
                "C9",
                f"{rel} documents an unpinned copier command: {command.strip()!r} — "
                "it resolves to the highest-sorting tag, which is a frozen v1.x snapshot",
            )

    ok("C9", f"{checked} runnable copier command(s) against a versioned source, all pinned")
    if upstream:
        ok(
            "C9",
            f"{len(upstream)} unpinned command(s) INHERITED from the template, not fixable here: "
            + "; ".join(upstream),
        )


def _commits_since(when: date) -> int:
    """Commits authored after a date. The measure C7 needed and did not have."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", f"--since={when.isoformat()}", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(result.stdout.strip() or 0)


def check_audit_freshness() -> None:
    """C7 — the independent-audit marker has not gone stale (ADR-005 rule B).

    Coherence checking is self-review by construction: it compares documents
    with each other and cannot detect a fact its author believed. This check
    exists to make sure the thing that CAN detect that keeps happening.
    """
    marker = re.search(
        r"Last independent audit:\s*(\d{4}-\d{2}-\d{2})",
        _read(REPO_ROOT / "AGENTS.md") + _read(PLAN),
    )
    if not marker:
        # This previously returned ok() unconditionally, which made C7 a check
        # that PASSED BECAUSE THE THING WAS ABSENT — anti-pattern P-09, and a
        # gate designed never to fail. Absence is tolerable only while the
        # repository has no history worth auditing.
        commits = _commit_count()
        if commits > AUDIT_GRACE_COMMITS:
            fail(
                "C7",
                f"no independent audit recorded after {commits} commits "
                f"(grace: {AUDIT_GRACE_COMMITS}). ADR-005 rule B requires one in a "
                "SEPARATE session — self-review cannot find a fact its author believed. "
                "Run QA-4, then add 'Last independent audit: YYYY-MM-DD' to AGENTS.md.",
            )
        else:
            ok("C7", f"no audit yet, {commits}/{AUDIT_GRACE_COMMITS} commits into the grace period")
        return

    audited = datetime.strptime(marker.group(1), "%Y-%m-%d").date()
    age = (date.today() - audited).days
    if age > AUDIT_MAX_AGE_DAYS:
        fail("C7", f"last independent audit was {age} days ago (limit {AUDIT_MAX_AGE_DAYS}) — run QA-4")
    else:
        ok("C7", f"last independent audit {age} days ago")


def _commit_count() -> int:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip()) if result.returncode == 0 else 0


def _commits_since_last_tag() -> int:
    """Commits since the most recent tag, or the whole history when untagged."""
    describe = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
    )
    if describe.returncode != 0:
        return _commit_count()
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-list", "--count", f"{describe.stdout.strip()}..HEAD"],
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip() or 0)


def check_changelog_covers_the_commit_range() -> None:
    """C8 — [Unreleased] reflects the commits since the last tag.

    This repository reached eighteen commits with NO CHANGELOG at all, while
    shipping a release workflow that requires one per version and would have
    failed on the first tag. Nothing reported it because nothing was looking.

    The check is deliberately coarse: it cannot know whether an entry is
    accurate, only whether the section exists and is not empty while commits
    have accumulated. Accuracy is QA-5's judgement step.
    """
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        fail("C8", "CHANGELOG.md is absent; release-on-tag.yml requires a section per version")
        return

    text = changelog.read_text(encoding="utf-8")
    if "## [Unreleased]" not in text:
        fail("C8", "CHANGELOG.md has no [Unreleased] section to accumulate into")
        return

    section = text.split("## [Unreleased]", 1)[1].split("\n## ", 1)[0]
    if len(section.strip()) >= 80:
        ok("C8", f"CHANGELOG [Unreleased] present, {_commit_count()} commits on this branch")
        return

    # An empty [Unreleased] is CORRECT in two situations, and this check used
    # to fail both — a gate that a legitimate state cannot satisfy.
    #
    # 1. The commit that prepares a release renames [Unreleased] to the version
    #    and opens a fresh empty one. At that moment no tag exists yet, so
    #    "commits since the last tag" is the whole history, and the work is
    #    documented under the version heading rather than under [Unreleased].
    # 2. Immediately after a tag, there is genuinely nothing unreleased.
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pending_release = f"## [{version}]" in text
    if pending_release:
        ok("C8", f"[Unreleased] is empty; the range is documented under [{version}], awaiting its tag")
        return

    if _commits_since_last_tag() == 0:
        ok("C8", "[Unreleased] is empty and nothing has landed since the last tag")
        return

    fail("C8", "[Unreleased] is effectively empty while commits have accumulated")


def main() -> int:
    adrs = _adr_files()
    check_adr_index(adrs)
    check_no_dangling_refs(adrs)
    check_adrs_are_integrated(adrs)
    check_gate_traceability()
    check_agentic_surface()
    check_language_and_privacy()
    check_changelog_covers_the_commit_range()
    check_copier_commands_are_pinned()
    check_audit_freshness()

    for note in notes:
        print(f"  ok  {note}")

    if failures:
        print("\n[coherence] FAILED\n")
        for failure in failures:
            print(f"  FAIL {failure}")
        print(f"\n{len(failures)} coherence failure(s).")
        return 1

    print("\n[coherence] OK — all checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
