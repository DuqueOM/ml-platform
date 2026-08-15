"""The YAML verifier must cover the repository, not the diff.

`scripts/ci_verify_yaml.py` was adopted because `check-yaml` — the hook that
made it look redundant — is a pre-commit hook, and pre-commit hands its hooks
the staged file list. A YAML file that no commit has touched since it was
written has never been parsed by it, and no workflow invokes it at all.

So the property under test is not "the verifier parses YAML". It is:

  1. it examines files a diff-scoped check would not have reached,
  2. it catches the duplicate key PyYAML accepts in silence,
  3. it reads the tagged file the pre-commit hook had to exclude by name,
  4. it cannot pass by examining nothing.

Point 4 is the one this repository has already shipped a live instance of: a
coherence filter matching absolute paths examined zero files and reported OK.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci_verify_yaml.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)


@contextmanager
def probe(path: Path, content: str) -> Iterator[None]:
    """Place a file, then remove it — including when the assertion fails.

    A test that leaves a broken manifest in the tree makes every later test in
    the session suspect, and the next person debugs the residue instead of the
    code.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def test_the_verifier_passes_on_the_current_tree() -> None:
    """The baseline. A red here is a broken manifest, not a broken test."""
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_it_reports_how_many_files_it_examined() -> None:
    """A gate that does not say what it examined cannot be caught examining nothing.

    Anti-pattern P-20, and the reason the count is in the success line rather
    than only in the failure path — the failure path is not the one that runs
    for months without anybody reading it.
    """
    result = _run()
    assert "file(s) parsed" in result.stdout
    count = int(result.stdout.split("—")[1].strip().split()[0])
    assert count > 100, f"only {count} files examined; the enumeration or the exclusion has collapsed"


def test_broken_yaml_outside_the_diff_is_caught() -> None:
    """The gap that moved this script from `rejected` to `pending`.

    The probe is written and NEVER staged, which is exactly the state a file is
    in when `check-yaml` skips it. A verifier that only sees staged content
    would pass here.
    """
    with probe(REPO_ROOT / "platform" / "kubernetes" / "_gate_probe.yaml", "kind: ConfigMap\n  bad: [unclosed\n"):
        result = _run()

    assert result.returncode == 1
    assert "_gate_probe.yaml" in result.stdout


def test_a_duplicate_key_is_caught() -> None:
    """PyYAML keeps the last value and drops the first without a word.

    In a Kubernetes manifest that is a repeated `resources:` silently discarding
    the limits somebody reviewed — the object that deploys differs from the file
    that was approved, and nothing anywhere reports it. `safe_load` accepts
    this, which is why the verifier installs its own mapping constructor.
    """
    manifest = "apiVersion: v1\nkind: ConfigMap\ndata:\n  a: '1'\ndata:\n  b: '2'\n"
    with probe(REPO_ROOT / "platform" / "kubernetes" / "_gate_probe.yaml", manifest):
        result = _run()

    assert result.returncode == 1
    assert "duplicate key" in result.stdout


def test_a_multi_document_file_is_parsed_past_the_first_document() -> None:
    """Kustomize output is multi-document; `load` would read one and stop.

    The break is placed in the SECOND document deliberately. A verifier calling
    `load` instead of `load_all` passes this file while having read a third of
    it, and would keep passing over every overlay in the repository.
    """
    two = "kind: ConfigMap\n---\nkind: Service\nports: [unclosed\n"
    with probe(REPO_ROOT / "platform" / "kubernetes" / "_gate_probe.yaml", two):
        result = _run()

    assert result.returncode == 1


def test_the_python_name_tag_is_read_rather_than_excluded() -> None:
    """`check-yaml` excludes mkdocs.yml by name; the verifier reads it.

    `!!python/name:...` is valid for the loader mkdocs uses and refused by
    `safe_load`. Excluding the file is how a parser gap becomes permanent — the
    exclusion outlives the reason, and nothing ever revisits it. BaseLoader
    treats the tag as a tagged scalar, so the file is covered.
    """
    import ci_verify_yaml

    tagged = "markdown_extensions:\n  - pymdownx.superfences:\n      format: !!python/name:pymdownx.fence_code\n"
    with probe(REPO_ROOT / "platform" / "kubernetes" / "_gate_probe.yaml", tagged):
        assert ci_verify_yaml.verify(["platform/kubernetes/_gate_probe.yaml"]) == []


def test_an_empty_file_list_fails_rather_than_passes() -> None:
    """The failure this repository has already shipped once.

    A filter that stops matching reports success over zero files, and success
    is what everybody reads. `verify([])` returning no findings is correct in
    isolation; `main` treating that as OK is not, so the emptiness is caught
    where the verdict is formed.
    """
    import ci_verify_yaml

    original = ci_verify_yaml.repository_yaml_files
    ci_verify_yaml.repository_yaml_files = lambda: []  # type: ignore[assignment]
    try:
        assert ci_verify_yaml.main() == 1
    finally:
        ci_verify_yaml.repository_yaml_files = original  # type: ignore[assignment]


def test_only_generator_source_is_excluded() -> None:
    """The exclusion must stay a named directory, not a growing habit.

    `templates/project/` holds un-rendered copier source — `{@ project_slug @}`
    is not YAML — and it is verified by rendering it in
    `tests/test_project_generator.py`. Every other YAML in the repository is
    parsed. This asserts the exclusion covers that one prefix and nothing else,
    so widening it is a visible edit to a test rather than a quiet one to a
    tuple.
    """
    import ci_verify_yaml

    assert ci_verify_yaml.EXCLUDED_PREFIXES == ("templates/project/",)

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    all_yaml = {path for path in tracked if path.endswith((".yaml", ".yml"))}
    examined = set(ci_verify_yaml.repository_yaml_files())

    assert all_yaml - examined == {
        "templates/project/.copier-answers.yml",
        "templates/project/evals/gates.yaml",
    }


def test_the_probe_left_no_residue() -> None:
    """Runs last by name. Residue from a gate test poisons every gate after it."""
    assert not (REPO_ROOT / "platform" / "kubernetes" / "_gate_probe.yaml").exists()
