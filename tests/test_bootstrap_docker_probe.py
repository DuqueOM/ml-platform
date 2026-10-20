"""`bootstrap.sh --check` reports a wedged Docker daemon instead of hanging on it.

On 2026-10-20 Docker Desktop stopped answering its API under WSL while the
kind node kept running. `docker info` never returned, and because
`scripts/check_implementation_status.py` runs `bootstrap.sh --check` as a
component's evidence, the status generator hung for its whole per-command
limit — and `make verify` failed with a timeout naming neither Docker nor the
script. The probe is bounded now; these run the real script against a fake
`docker` that hangs, refuses, or answers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.sh"

_FAKE_DOCKER = """#!/usr/bin/env bash
case "$1" in
  --version) echo "Docker version 0.0.0, build fake" ;;
  info)
    case "$FAKE_DOCKER_MODE" in
      hang) sleep 60 ;;
      refuse) exit 1 ;;
      *) exit 0 ;;
    esac ;;
esac
"""

pytestmark = pytest.mark.skipif(shutil.which("timeout") is None, reason="the bound needs coreutils `timeout`")


def _check(tmp_path: Path, mode: str) -> tuple[str, float]:
    fake = tmp_path / "bin"
    fake.mkdir()
    docker = fake / "docker"
    docker.write_text(_FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_MODE": mode,
        "BOOTSTRAP_DOCKER_PROBE_SECONDS": "1",
    }
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(BOOTSTRAP), "--check"], capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=120
    )
    return result.stdout + result.stderr, time.monotonic() - started


def test_a_wedged_daemon_is_reported_within_the_bound(tmp_path: Path) -> None:
    output, elapsed = _check(tmp_path, "hang")
    assert "daemon NOT answering — no reply within 1s" in output
    assert elapsed < 55, f"the check waited {elapsed:.0f}s on a daemon that never answers — the fake sleeps 60"


def test_an_unreachable_daemon_is_reported_as_unreachable(tmp_path: Path) -> None:
    output, _ = _check(tmp_path, "refuse")
    assert "daemon NOT reachable" in output


def test_a_reachable_daemon_is_reported_as_reachable(tmp_path: Path) -> None:
    output, _ = _check(tmp_path, "answer")
    assert "daemon reachable" in output
    assert "NOT" not in output.split("daemon reachable")[0].splitlines()[-1]
