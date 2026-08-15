"""Every failure here is one a per-file test structurally cannot reach.

`tests/test_dashboards_structure.py` is parametrised over one dashboard at a
time. It can assert that a dashboard HAS a uid; it can never assert that two
dashboards have DIFFERENT uids, because it never sees two at once. Grafana keys
on uid, so a collision means one file silently replaces the other in whatever
order the ConfigMap enumerates — no error, no log, and a bookmarked dashboard
now showing another service's panels.

`make local-dashboards` provisions the directory wholesale
(`--from-file=platform/observability/dashboards/`), which is what makes the
directory rather than the file the unit worth checking: anything dropped in
there is a deploy.

The sandbox tests below build a directory in `tmp_path` rather than mutating the
real one wherever the shape allows it. The two that must touch the real tree add
a file and delete it; none edits the dashboard that is actually shipped.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_dashboard_inventory.py"
PROVISIONED = REPO_ROOT / "platform" / "observability" / "dashboards"
REGISTER = REPO_ROOT / "platform" / "observability" / "README.md"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO_ROOT, timeout=120
    )


def _dashboard(uid: str, title: str) -> str:
    return json.dumps(
        {
            "uid": uid,
            "title": title,
            "panels": [{"id": 1, "title": "p", "description": "d", "datasource": {"uid": "prometheus"}}],
        }
    )


@contextmanager
def planted(path: Path, content: str) -> Iterator[None]:
    """Add a file to a real directory, then remove it.

    Restores on failure too. Adding is used rather than editing because the one
    dashboard in the provisioned directory is a shipped artifact, and a probe
    that corrupts it and dies leaves the local stack broken.
    """
    assert not path.exists(), f"{path} already exists; the probe would destroy it"
    path.write_text(content, encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _sandbox(tmp_path: Path, files: dict[str, str], register: str) -> tuple[Path, Path]:
    directory = tmp_path / "dashboards"
    directory.mkdir()
    for name, body in files.items():
        (directory / name).write_text(body, encoding="utf-8")
    register_path = tmp_path / "README.md"
    register_path.write_text(register, encoding="utf-8")
    return directory, register_path


def test_the_current_inventory_passes() -> None:
    """The baseline, run exactly as CI runs it — no arguments."""
    result = _run()
    assert result.returncode == 0, result.stdout


def test_it_reports_what_it_examined_including_what_it_does_not_gate() -> None:
    """The upstream-owned dashboards are reported, never failed on.

    `services/` is generated from ml-service-template and stays byte-identical
    to what the template produces (ADR-003), so a defect there is upstream's to
    fix. Reporting the five keeps their absence from the local stack a recorded
    fact rather than something the next reader rediscovers.
    """
    result = _run()
    assert "provisioned: 1 file(s)" in result.stdout
    assert "upstream-owned: 5 dashboard(s)" in result.stdout


def test_two_dashboards_sharing_a_uid_fail(tmp_path: Path) -> None:
    """The silent replacement, and the reason this check is not a per-file test.

    Both files provision. Grafana keys on uid, so the second one written wins,
    and which one that is depends on ConfigMap key ordering rather than on
    anything a reviewer would look at.
    """
    directory, register = _sandbox(
        tmp_path,
        {"a.json": _dashboard("shared", "A"), "b.json": _dashboard("shared", "B")},
        "a.json and b.json",
    )
    result = _run("--dir", str(directory), "--register", str(register))

    assert result.returncode == 1
    assert "both claim uid 'shared'" in result.stdout


def test_two_dashboards_sharing_a_title_fail(tmp_path: Path) -> None:
    """Both appear in the picker, indistinguishable, at 3am."""
    directory, register = _sandbox(
        tmp_path,
        {"a.json": _dashboard("a", "Serving"), "b.json": _dashboard("b", "Serving")},
        "a.json and b.json",
    )
    result = _run("--dir", str(directory), "--register", str(register))

    assert result.returncode == 1
    assert "share the title 'Serving'" in result.stdout


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('{"title": "T", "panels": [1]}', "no uid"),
        ('{"uid": "u", "panels": [1]}', "no title"),
        ("{not json", "not valid JSON"),
        ("[]", "not a JSON object"),
    ],
)
def test_a_malformed_dashboard_fails(tmp_path: Path, body: str, expected: str) -> None:
    """Everything in the directory ships, so everything in it must be a dashboard."""
    directory, register = _sandbox(tmp_path, {"probe.json": body}, "probe.json")
    result = _run("--dir", str(directory), "--register", str(register))

    assert result.returncode == 1
    assert expected in result.stdout


def test_a_non_json_file_in_the_provisioned_directory_fails(tmp_path: Path) -> None:
    """`--from-file` does not filter by extension.

    An editor backup or a stray fixture reaches Grafana as a dashboard whatever
    it actually is, and a malformed one takes its ConfigMap key with it.
    """
    directory, register = _sandbox(
        tmp_path, {"a.json": _dashboard("a", "A"), "notes.txt": "scratch"}, "a.json and notes.txt"
    )
    result = _run("--dir", str(directory), "--register", str(register))

    assert result.returncode == 1
    assert "is in the provisioned directory and is not JSON" in result.stdout


def test_an_empty_directory_fails_rather_than_passing_over_nothing(tmp_path: Path) -> None:
    """Anti-pattern P-09, asserted directly.

    Every check in this script iterates the directory's files. With none, all of
    them are satisfied — which is not a green dashboard set, it is no dashboards.
    """
    directory, register = _sandbox(tmp_path, {}, "nothing here")
    result = _run("--dir", str(directory), "--register", str(register))

    assert result.returncode == 1
    assert "P-09" in result.stdout


def test_a_register_entry_with_no_dashboard_fails(tmp_path: Path) -> None:
    """The converse direction: a register describing something nobody would see."""
    directory, register = _sandbox(tmp_path, {"a.json": _dashboard("a", "A")}, "a.json and ghost.json")
    result = _run("--dir", str(directory), "--register", str(register))

    assert result.returncode == 1
    assert "registers ghost.json" in result.stdout


def test_an_unregistered_dashboard_fails_in_the_real_tree() -> None:
    """Shipped and registered have to be the same word.

    Run against the real directory and the real register, because the sandbox
    tests would keep passing if the default paths were pointed somewhere wrong —
    which is how a check comes to examine a directory nobody deploys.
    """
    probe = PROVISIONED / "_probe_unregistered.json"
    with planted(probe, _dashboard("probe-unregistered", "Probe — unregistered")):
        result = _run()

    assert result.returncode == 1
    assert "_probe_unregistered.json is provisioned and is not named in" in result.stdout


def test_a_uid_collision_with_the_shipped_dashboard_is_caught() -> None:
    """The real case: a second vertical copied from the first without a new uid."""
    probe = PROVISIONED / "_probe_collision.json"
    body = _dashboard("demand-forecast-serving", "Probe — collision")
    with planted(probe, body):
        result = _run()

    assert result.returncode == 1
    assert "both claim uid 'demand-forecast-serving'" in result.stdout


def test_the_probes_left_no_residue() -> None:
    """A probe that survives its test provisions to Grafana on the next sync."""
    residue = sorted(PROVISIONED.glob("_probe_*"))
    assert not residue, f"probe files were left in the provisioned directory: {residue}"
    assert REGISTER.is_file()
