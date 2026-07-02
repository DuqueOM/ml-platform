#!/usr/bin/env python3
"""Minimal doc-coherence gate (AUDIT R8-04) — the calibrated port of
template_MLOps rule 16 to this repo's scale.

Facts that live in more than one place drift unless a gate compares them.
This script asserts the coherence facts this repo has already gotten wrong
at least twice (versions frozen at 0.2.0 while the CHANGELOG shipped 0.5.0;
six git tags existed with zero GitHub Releases — AUDIT R9-06):

  C1. core/__init__.py::__version__ matches the latest released CHANGELOG
      heading (``## [X.Y.Z] - date``).
  C2. pyproject.toml sources its version dynamically from core.__version__
      (no re-hardcoded ``version = "..."`` under [project]).
  C3. app/ contains no hardcoded semver string literal — the FastAPI
      surface must import ``core.__version__``.
  C4. Every ADR file in docs/decisions/ is indexed in its README.md.
  C5. Every git tag matching ``v*`` has a corresponding GitHub Release
      (not just a tag). Best-effort: requires the ``gh`` CLI AND
      authentication; skips silently (not a failure) when either is
      unavailable, so a contributor's local, unauthenticated run never
      false-fails — the real backstop is the CI job, which always has
      ``GITHUB_TOKEN``.
  C6. Documentation language + private-reference guard (AUDIT R10,
      2026-07-02): every file under docs/ and every root-level *.md must
      be English-only and must never name a known private/personal repo.
      Excludes usecases/**, which legitimately serves Spanish-speaking
      WhatsApp customers — that is product content, not documentation
      about this repo. Ported from template_MLOps's check_doc_coherence.py
      C7 (same repo where the AUDIT R10 finding originated); see that
      script's module docstring for why this is a word list rather than a
      raw accented-character scan.

Deliberately NOT the full template system (7 checks + cascade map): at
~2k LOC that would be over-engineering; these checks cover every
coherence defect this repo has actually exhibited.

Exit code 0 = coherent; 1 = drift (each violation printed with evidence).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEMVER_LITERAL = re.compile(r'"\d+\.\d+\.\d+"')

# Case-insensitive, whole-word Spanish markers — see template_MLOps's
# scripts/check_doc_coherence.py for the full rationale (word list, not a
# character scan, to avoid flagging legitimate accented proper nouns; the
# accent is REQUIRED on every entry, never optional, because e.g.
# "decisión" minus its accent spells exactly the English word "decision").
_SPANISH_MARKERS = re.compile(
    r"\b(aunque|también|además|cuáles?|cuándo|dónde|"
    r"sin embargo|por lo tanto|así como|deberían?|realiza|actualiza|"
    r"hallazgo|auditoría|alcance|fecha|integración|ingeniería|"
    r"según|entrevista|corrección(?:es)?|revisión|preguntas?|"
    r"respuesta|veredicto|decisión(?:es)?|información|"
    r"configuración|documentación|implementación|validación|"
    r"verificación|generación|resumen|conclusión|introducción|"
    r"adopción|credibilidad|infraestructura|estratégicos?|"
    r"desbalance|sobre-ingeniería)\b",
    re.IGNORECASE,
)

# Private/personal repos that must never be named in this public repo's
# documentation (AUDIT R10, 2026-07-02 — see the sibling template's
# ADR-040 for the incident this closes). Extend if another private
# companion repo is ever referenced. Safe to keep as a literal here: this
# file is Python, not Markdown, so it is never itself in C6's own scan
# scope (see _doc_scan_files below).
_FORBIDDEN_REPO_REFS = ("guia_mlops",)


def _fail(msgs: list[str], text: str) -> None:
    msgs.append(f"[coherence] FAIL — {text}")


def check_version_matches_changelog(errors: list[str]) -> None:
    """C1: core.__version__ == latest released CHANGELOG heading."""
    init_text = (ROOT / "core" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not m:
        _fail(errors, "core/__init__.py has no __version__ string")
        return
    core_version = m.group(1)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    if not heading:
        _fail(errors, "CHANGELOG.md has no released '## [X.Y.Z]' heading")
        return
    latest = heading.group(1)

    if core_version != latest:
        _fail(
            errors,
            f"core.__version__ = {core_version!r} but latest CHANGELOG heading is [{latest}] "
            "— bump one of them in the same PR",
        )


def check_pyproject_is_dynamic(errors: list[str]) -> None:
    """C2: pyproject must not re-hardcode the version (SSoT = core)."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'dynamic = ["version"]' not in pyproject:
        _fail(errors, 'pyproject.toml [project] must declare dynamic = ["version"]')
    if not re.search(r'version\s*=\s*\{\s*attr\s*=\s*"core\.__version__"\s*\}', pyproject):
        _fail(errors, "pyproject.toml must source version from core.__version__ (tool.setuptools.dynamic)")
    if re.search(r'^\s*version\s*=\s*"\d+\.\d+\.\d+"', pyproject, re.MULTILINE):
        _fail(errors, "pyproject.toml re-hardcodes a version string — remove it (SSoT is core.__version__)")


def check_app_has_no_hardcoded_version(errors: list[str]) -> None:
    """C3: the FastAPI surface imports the version, never restates it."""
    for path in sorted((ROOT / "app").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SEMVER_LITERAL.search(line):
                _fail(
                    errors,
                    f"{path.relative_to(ROOT)}:{lineno} hardcodes a semver literal "
                    "— import core.__version__ instead",
                )


def check_adr_index_complete(errors: list[str]) -> None:
    """C4: every ADR file appears in docs/decisions/README.md."""
    decisions = ROOT / "docs" / "decisions"
    index_text = (decisions / "README.md").read_text(encoding="utf-8")
    for adr in sorted(decisions.glob("ADR-*.md")):
        if adr.name not in index_text:
            _fail(errors, f"docs/decisions/README.md does not index {adr.name}")


def check_tags_have_releases(errors: list[str]) -> None:
    """C5: every ``v*`` tag has a GitHub Release, not just a tag (R9-06).

    Best-effort by design: no ``gh`` on PATH, or no authenticated session,
    means this check cannot run and is skipped WITHOUT failing — the
    authoritative enforcement is the CI job, which always has
    ``GITHUB_TOKEN`` available. A skip here must never block a local,
    offline `python scripts/check_coherence.py` run.
    """
    gh = shutil.which("gh")
    if gh is None:
        print("[coherence] C5 skipped — `gh` CLI not found (CI enforces this check).")
        return

    try:
        auth = subprocess.run([gh, "auth", "status"], capture_output=True, timeout=10)
        if auth.returncode != 0:
            print("[coherence] C5 skipped — `gh` not authenticated (CI enforces this check).")
            return

        tags_proc = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True, cwd=ROOT, timeout=10)
        tags = sorted(t for t in tags_proc.stdout.splitlines() if t.strip())
        if not tags:
            return

        releases_proc = subprocess.run(
            [gh, "release", "list", "--json", "tagName", "--limit", "200"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=15,
        )
        if releases_proc.returncode != 0:
            print("[coherence] C5 skipped — `gh release list` failed (no repo access?).")
            return
        released = {r["tagName"] for r in json.loads(releases_proc.stdout)}
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        print(f"[coherence] C5 skipped — could not query GitHub ({exc}).")
        return

    missing = [t for t in tags if t not in released]
    if missing:
        _fail(
            errors,
            f"tag(s) without a GitHub Release: {missing}. Every `v*` tag MUST have a "
            "published Release (not just a tag) — run `gh release create <tag> "
            "--notes-file releases/<tag>.md`, or let .github/workflows/release-on-tag.yml "
            "publish it on the next push to that tag.",
        )


def _doc_scan_files() -> list[Path]:
    """``docs/**/*.md`` plus root-level ``*.md``, tracked-only, minus ``usecases/``.

    ``usecases/**`` (prompts, policies) is excluded because it legitimately
    serves Spanish-speaking WhatsApp customers — that is product content,
    not documentation about this repo, and translating it would break the
    product. Uses ``git ls-files`` (not a filesystem walk) so it can never
    scan an untracked/gitignored local file.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "*.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        tracked = {ROOT / line for line in out.splitlines() if line}
    except (OSError, subprocess.CalledProcessError):
        tracked = set((ROOT / "docs").rglob("*.md")) | set(ROOT.glob("*.md"))

    def _in_scope(p: Path) -> bool:
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            return False
        if rel.parts[0] == "usecases":
            return False
        return rel.parts[0] == "docs" or len(rel.parts) == 1

    return sorted(p for p in tracked if p.is_file() and _in_scope(p))


def check_doc_language_and_privacy(errors: list[str]) -> None:
    """C6 — docs/ and root docs must be English-only, and name no private repo."""
    for path in _doc_scan_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()

        spanish_hits = sorted({m.group(1).lower() for m in _SPANISH_MARKERS.finditer(text)})
        if spanish_hits:
            shown = ", ".join(spanish_hits[:5])
            more = f" (+{len(spanish_hits) - 5} more)" if len(spanish_hits) > 5 else ""
            _fail(
                errors,
                f"{rel} contains Spanish word(s): {shown}{more}. "
                "This repo's documentation is English-only (AUDIT R10).",
            )

        lowered = text.lower()
        for forbidden in _FORBIDDEN_REPO_REFS:
            if forbidden in lowered:
                _fail(
                    errors,
                    f"{rel} references '{forbidden}', a private/personal repo that must "
                    "never be named in this public repo's documentation (AUDIT R10).",
                )


def main() -> int:
    errors: list[str] = []
    check_version_matches_changelog(errors)
    check_pyproject_is_dynamic(errors)
    check_app_has_no_hardcoded_version(errors)
    check_adr_index_complete(errors)
    check_tags_have_releases(errors)
    check_doc_language_and_privacy(errors)

    if errors:
        print("\n".join(errors))
        print(f"[coherence] {len(errors)} violation(s).")
        return 1
    print(
        "[coherence] OK — all checks pass (version SSoT, pyproject dynamic, app clean, "
        "ADR index, tag/release parity, doc language + privacy)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
