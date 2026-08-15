#!/usr/bin/env python3
"""A pull request may not claim an evidence layer it names no command for.

`docs/architecture/implementation-status.md` states the rule this enforces:
**the layer is derived from the command that ran, never declared.** The derived
status document obeys it because a script writes it. A pull request body is
written by hand, so nothing obeyed it there — and review time is exactly when
the claim is made, believed, and merged.

The failure this exists to catch is already recorded in this repository. Six
Kubernetes overlays were green for weeks with probes pointing at routes the
service does not serve, so no pod could ever have reached Ready. Every check
that looked at them passed, because every check ran at L1 and the belief being
held was about L3. A body that says "verified in the cluster" and names only a
`pytest` invocation reproduces that gap in the one place a human still reads.

What is checked, and — as importantly — what is not:

**Checked.** The body names at least one runnable command. Every layer it
claims is accompanied by one. A claim of L3 needs a command that requires a
cluster, and a claim of L4 needs one that requires a cloud account.

**Not checked: L1 against L2.** Both are produced in CI, so mistaking one for
the other neither overstates a guarantee nor hides a gap; the asymmetry is
deliberate and is the same one `tests/test_security_controls.py` applies to the
Blocking column. L3 and L4 are different: CI has no cluster and no cloud, so a
claim at either layer is a claim about somewhere else, and it is the direction
in which a PR can be wrong at a cost.

**Not checked: prose.** Whether the pasted output is real, whether it came from
this commit, whether the machine named is the machine used. A check that
guesses at prose produces false positives, and a check that cries wolf is one
reviewers learn to skim past — which costs more than it saves.

    python scripts/check_pr_evidence.py --body-file body.md
    PR_BODY="$(gh pr view 12 --json body -q .body)" python scripts/check_pr_evidence.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

#: Layers, in the order the status document defines them. L1 and L2 are both
#: reachable in CI; L3 and L4 are not, and that split is the whole reason the
#: rules below treat them differently.
LAYERS = ("L1", "L2", "L3", "L4")

#: Commands that cannot run without a real cloud account. Kept identical to
#: `_CLOUD_TOOLS` in `scripts/check_implementation_status.py`, and
#: `tests/test_pr_evidence.py` asserts the two agree — two lists of what "cloud"
#: means, maintained apart, is how one of them quietly stops matching.
CLOUD_TOOLS = ("gcloud ", "aws ", "eksctl ", "terraform apply")

#: Commands that need a running cluster. `kubectl` is here with one exception
#: below: `kubectl kustomize` is an offline renderer and CI already runs it over
#: every overlay, so counting it as cluster evidence would hand out L3 for a
#: step that proves nothing about a pod ever starting.
CLUSTER_TOOLS = ("kubectl ", "kind ", "helm ", "minikube ", "make local", "-m local")

#: First words that make a line a command rather than a sentence. An allow-list,
#: because the alternative — "a line inside a fence is a command" — reads the
#: pasted OUTPUT as commands too, and output is mostly what a good evidence
#: block contains.
RUNNABLE = (
    "uv",
    "uvx",
    "make",
    "pytest",
    "python",
    "python3",
    "bash",
    "sh",
    # `git` is deliberately absent. It manipulates the tree rather than
    # verifying it, and the one git command in `.github/pull_request_template.md`
    # — `git add -A`, in the paragraph about regenerating derived documents —
    # made the UNEDITED template satisfy "a command was named". A template that
    # passes its own gate means every pull request passes on arrival.
    "gh",
    "kubectl",
    "kustomize",
    "terraform",
    "docker",
    "kind",
    "helm",
    "ruff",
    "mypy",
    "pre-commit",
    "curl",
    "aws",
    "gcloud",
    "eksctl",
    "minikube",
)

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"```[a-zA-Z0-9]*\n(.*?)```", re.DOTALL)
_INLINE = re.compile(r"`([^`\n]+)`")

#: The three forms a layer claim takes in this repository's merged pull
#: requests, plus the checkbox the template offers. Read from real bodies rather
#: than invented: `**L1.**` (PR 12), `**L1/L2.**` (PR 13), `L1 (contract)`
#: (PR 14), and `- [x] **L1**` from `.github/pull_request_template.md`.
#:
#: Narrow on purpose. The template's own explanatory sentence — "CI has no
#: cluster and no cloud, so L3 and L4 cannot be produced by this PR's checks" —
#: names two layers and claims neither, and a looser pattern would read the
#: template's honesty as an over-claim.
_BOLD_CLAIM = re.compile(r"\*\*(L[1-4](?:\s*/\s*L[1-4])*)\.?\*\*")
_NAMED_CLAIM = re.compile(r"\b(L[1-4])\s*\((?:contract|component|cluster|cloud)\)", re.IGNORECASE)
_TICKED_BOX = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(.+)$", re.MULTILINE)
_ANY_BOX = re.compile(r"^\s*[-*]\s*\[[ xX]\].*$", re.MULTILINE)

_EVIDENCE_HEADING = re.compile(r"^#{2,4}\s*Evidence\b", re.IGNORECASE)
_ANY_HEADING = re.compile(r"^#{1,4}\s")


def strip_comments(body: str) -> str:
    """Remove HTML comments — the template is mostly guidance inside them."""
    return _HTML_COMMENT.sub("", body)


def evidence_section(body: str) -> str | None:
    """The `## Evidence` section, or None when the body has none.

    Scoping matters more than it looks, and it was measured rather than
    assumed. Reading the WHOLE body for commands passed pull request 13, whose
    evidence is two conclusions and no command: its narrative names
    ``uv run pytest`` while explaining what the slow CI step had been running,
    and ``uv run`` while explaining a virtualenv race. Both are prose about
    commands, in the section that describes the problem — neither is evidence
    of anything, and counting them let the one body this gate was built for
    pass it.

    Headings inside a fenced block are ignored, because a shell comment starts
    with the same character as a heading and the evidence block is exactly
    where shell lives.
    """
    text = strip_comments(body)
    lines = text.splitlines()

    start = None
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if start is None:
            if _EVIDENCE_HEADING.match(line):
                start = index + 1
        elif _ANY_HEADING.match(line):
            return "\n".join(lines[start:index])

    return None if start is None else "\n".join(lines[start:])


def claimed_layers(body: str) -> set[str]:
    """Layers the body asserts, by the forms this repository actually writes."""
    text = strip_comments(body)
    claims: set[str] = set()

    for match in _TICKED_BOX.finditer(text):
        claims.update(re.findall(r"\bL[1-4]\b", match.group(1)))

    # Checkbox lines are removed before the prose patterns run, because the
    # template writes its four options as `- [ ] **L1**` … `- [ ] **L4**`. The
    # bold pattern read every one of them as an assertion, so the unedited
    # template claimed all four layers at once — a check that fires on the
    # unfilled form is one whose first output everybody learns to ignore.
    prose = _ANY_BOX.sub("", text)
    for match in _BOLD_CLAIM.finditer(prose):
        claims.update(re.findall(r"L[1-4]", match.group(1)))
    for match in _NAMED_CLAIM.finditer(prose):
        claims.add(match.group(1).upper())

    return claims


def commands(text: str) -> list[str]:
    """Runnable commands in a passage, from fenced blocks and code spans.

    Called on the evidence section, never on the whole body — see
    :func:`evidence_section` for why.

    The `$ ` prompt is stripped. A bare `$` — which is what the pull request
    template ships in its empty evidence block — reduces to nothing and is
    therefore not a command, so an unedited template fails rather than passes.
    """
    candidates: list[str] = []

    for block in _FENCE.findall(text):
        joined = re.sub(r"\\\n\s*", " ", block)
        candidates.extend(joined.splitlines())
    candidates.extend(_INLINE.findall(text))

    found = []
    for candidate in candidates:
        tokens = candidate.strip().removeprefix("$").strip().split()
        if len(tokens) < 2 or tokens[0] not in RUNNABLE:
            # A bare tool name is a mention, not an invocation. `uv run` on its
            # own is the clearest case: it appears in prose here describing what
            # a wrapper does, and it executes nothing.
            continue
        if tokens[0] in ("uv", "uvx") and tokens[1] == "run" and len(tokens) < 3:
            continue
        found.append(" ".join(tokens))
    return found


def derive_layer(command: str) -> str:
    """The layer a command reaches, by what it needs in order to run.

    The same rule the status generator applies, extended to the two layers that
    generator can never emit. Order matters: a cluster test invoked through
    `pytest` is cluster evidence, not contract evidence, so the environmental
    requirements are tested before the runner.
    """
    if any(tool in command for tool in CLOUD_TOOLS):
        return "L4"
    # `kubectl kustomize` renders manifests offline. Treating it as cluster
    # evidence would award L3 to a command CI already runs on every commit.
    if re.search(r"\bkubectl\s+kustomize\b", command):
        return "L2"
    if any(tool in command for tool in CLUSTER_TOOLS):
        return "L3"
    if "pytest" in command:
        return "L1"
    return "L2"


def check(body: str) -> list[str]:
    """Return one finding per rule broken. Empty means the body carries its evidence."""
    findings: list[str] = []
    text = strip_comments(body).strip()

    if not text:
        return ["the pull request body is empty — there is nothing to review against"]

    section = evidence_section(body)
    if section is None:
        return [
            "the body has no `## Evidence` section. `.github/pull_request_template.md` asks four "
            "questions and this is the one a machine can check — without the heading there is "
            "nowhere for the claim and its command to be read together"
        ]

    claims = claimed_layers(section)
    named = commands(section)
    reached = {derive_layer(command) for command in named}

    if not claims:
        findings.append(
            "no evidence layer is claimed. Say which of L1-L4 the evidence reaches, in the form the "
            "pull request template uses — the layer is what tells a reviewer whether a green check "
            "means the contract holds or that something actually ran"
        )

    if not named:
        findings.append(
            "no runnable command is named. Paste the command that produced the evidence; "
            "'tests pass' is what CI says for itself, and it says nothing about where it ran"
        )

    # The asymmetric half. Claiming L1 where the command proves L2 costs
    # nothing — both run in CI. Claiming L3 or L4 asserts something happened
    # somewhere CI cannot reach, and no command in the body would have produced it.
    for layer, requirement, examples in (
        ("L3", ("L3", "L4"), "make local-up, kubectl against a live context, a `-m local` suite"),
        ("L4", ("L4",), "gcloud, aws, eksctl, terraform apply"),
    ):
        if layer in claims and not (reached & set(requirement)):
            needs = "a cloud account" if layer == "L4" else "a cluster"
            findings.append(
                f"{layer} is claimed and no command in the body needs {needs}. "
                f"CI has neither, so {layer} is a claim about somewhere else and has to name the command that ran "
                f"there ({examples}). Commands found: {sorted(named) or 'none'}"
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--body-file", type=Path, help="read the body from a file instead of $PR_BODY")
    args = parser.parse_args()

    # The workflow passes the body through the ENVIRONMENT, never through the
    # `run:` block. A body is attacker-controlled text on a public repository,
    # and `${{ github.event.pull_request.body }}` interpolated into a shell
    # script is arbitrary code execution on the runner with the job's token.
    body = args.body_file.read_text(encoding="utf-8") if args.body_file else os.environ.get("PR_BODY", "")

    findings = check(body)
    section = evidence_section(body) or ""
    claims = sorted(claimed_layers(section))
    named = commands(section)

    print(f"  ok   [pr-evidence] layers claimed: {', '.join(claims) or 'none'}")
    print(f"  ok   [pr-evidence] commands named: {len(named)}")
    for command in named:
        print(f"       {derive_layer(command)}  {command}")

    if findings:
        print("\n[pr-evidence] FAILED\n")
        for finding in findings:
            print(f"  FAIL {finding}")
        print("\nSee .github/pull_request_template.md and docs/architecture/implementation-status.md")
        return 1

    print("\n[pr-evidence] OK — every layer claimed is backed by a named command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
