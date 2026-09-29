"""`scripts/local/preflight.py`, with the host replaced.

QA-4 round fourteen found this file outside the published `scripts/` coverage
figure — no `__init__.py`, so coverage never discovered it, and no test ran
it. It cannot run for real in CI (it needs docker, kind and a machine whose
memory it is budgeting), so every host probe is substituted: tool lookup,
`subprocess.run`, `/proc/meminfo`, and the port probe. What is tested is the
decision the script makes from those readings, which is the part that can be
wrong.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "local"))

import preflight  # noqa: E402

_BUDGET = {
    "max_utilisation": 0.5,
    "components": [{"name": "small", "limit_mb": 100}, {"name": "large", "limit_mb": 300}],
    "host_ports": [{"port": 8080, "service": "gateway"}],
}


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode, self.stdout = returncode, stdout


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A host with every tool, a live daemon, 1000 MB free and no cluster."""
    state: dict[str, Any] = {
        "missing": set(),
        "docker": 0,
        "clusters": "",
        "memory": [1000],
        "taken": set(),
        "budget": dict(_BUDGET),
    }
    budget = tmp_path / "budget.yaml"
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(preflight, "BUDGET", budget)
    monkeypatch.setattr(preflight.time, "sleep", lambda _s: None)
    monkeypatch.setattr(preflight.shutil, "which", lambda t: None if t in state["missing"] else f"/usr/bin/{t}")

    def run(argv: list[str], **_: Any) -> _Completed:
        if argv[:2] == ["docker", "info"]:
            if state["docker"] == "hang":
                raise subprocess.TimeoutExpired(argv, preflight.PROBE_TIMEOUT_SECONDS)
            return _Completed(state["docker"])
        if state["clusters"] == "hang":
            raise subprocess.TimeoutExpired(argv, preflight.PROBE_TIMEOUT_SECONDS)
        return _Completed(0, state["clusters"])

    monkeypatch.setattr(preflight.subprocess, "run", run)
    readings = iter(())

    def available() -> int:
        nonlocal readings
        try:
            return next(readings)
        except StopIteration:
            readings = iter(state["memory"])
            return next(readings)

    monkeypatch.setattr(preflight, "_available_mb", available)

    class _Probe:
        def __enter__(self) -> _Probe:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def settimeout(self, _t: float) -> None:
            return None

        def connect_ex(self, address: tuple[str, int]) -> int:
            return 0 if address[1] in state["taken"] else 111

    monkeypatch.setattr(preflight.socket, "socket", lambda *_a: _Probe())

    def write_budget() -> None:
        if state["budget"] is not None:
            budget.write_text(yaml.safe_dump(state["budget"]), encoding="utf-8")

    state["write"] = write_budget
    return state


def _main(host: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    host["write"]()
    monkeypatch.setattr(sys, "argv", ["preflight.py", "--samples", "3", "--interval", "0", *argv])
    return preflight.main()


def test_a_stack_that_fits_passes_with_its_headroom(host, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    assert _main(host, monkeypatch) == 0
    out = capsys.readouterr().out
    assert "budget allowed  : 500 MB" in out
    assert "fits with 100 MB of headroom" in out
    assert "1 host port(s) free" in out


def test_the_budget_is_checked_against_the_minimum_sample_not_the_mean(host, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    host["memory"] = [2000, 700, 2000]  # the mean fits; the minimum does not
    assert _main(host, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "min 700 MB" in out
    assert "memory is fluctuating widely" in out
    assert "Short by 50 MB" in out
    assert out.index("300 MB  large") < out.index("100 MB  small")


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ({"missing": {"kind"}}, "missing required tools: kind"),
        ({"docker": 1}, "docker is installed but not responding"),
        ({"docker": "hang"}, "docker is installed but not responding"),
        ({"budget": None}, "FAIL  missing budget.yaml"),
        ({"taken": {8080}}, "8080  wanted by gateway"),
    ],
    ids=["tool-missing", "daemon-down", "daemon-wedged", "no-budget", "port-taken"],
)
def test_each_refusal_says_why(host, monkeypatch, capsys, setup: dict[str, Any], message: str) -> None:  # type: ignore[no-untyped-def]
    host.update(setup)
    assert _main(host, monkeypatch) == 1
    assert message in capsys.readouterr().out


def test_a_running_cluster_holding_its_own_ports_is_not_a_collision(host, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    host.update(taken={8080}, clusters=f"other\n{preflight.CLUSTER_NAME}\n")
    assert _main(host, monkeypatch) == 0
    assert "already exists — port check not applicable" in capsys.readouterr().out


def test_a_wedged_kind_is_not_a_cluster(host) -> None:  # type: ignore[no-untyped-def]
    host["clusters"] = "hang"
    assert preflight.cluster_exists() is False


def test_no_ports_declared_skips_the_port_check(host, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    host["budget"] = {k: v for k, v in _BUDGET.items() if k != "host_ports"}
    assert _main(host, monkeypatch) == 0
    assert "host port" not in capsys.readouterr().out


def test_available_memory_is_read_from_memavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 8192000 kB\nMemFree: 1 kB\nMemAvailable: 4096000 kB\n", encoding="utf-8")
    real_path = preflight.Path
    monkeypatch.setattr(preflight, "Path", lambda p: meminfo if p == "/proc/meminfo" else real_path(p))
    assert preflight._available_mb() == 4000
    meminfo.write_text("MemTotal: 8192000 kB\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="MemAvailable"):
        preflight._available_mb()


def test_the_real_port_probe_sees_a_listening_socket() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert preflight.occupied_ports([{"port": port, "service": "probe"}]) == [(port, "probe")]
