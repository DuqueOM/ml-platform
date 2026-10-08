"""Every local-stack limit is held to what its image was MEASURED to use, on the image it was measured with.

QA-4 round eighteen: Grafana 13.2.2 was OOMKilled on every start at a 200Mi
limit chosen for Grafana 11. The bump merged "verified against the suite", which
never starts the stack, and nothing noticed for two weeks. These tests run in
CI without a cluster and still make that impossible to repeat:

- a manifest's image must be the one `platform/local/measured-memory.yaml`
  records — so a bump, Dependabot's included, fails until someone has started
  the new image and measured it (`scripts/local/measure_memory.py --write`);
- each limit must exceed the measured peak by the ledger's headroom;
- the manifest, the budget preflight sums and the namespace quota must agree.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL = REPO_ROOT / "platform" / "local"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "local"))

import measure_memory  # noqa: E402

#: Budget components that are not a pod in the ml-platform namespace.
NOT_A_STACK_POD = {"kind-control-plane", "workload"}


def _documents() -> list[dict[str, Any]]:
    found = []
    for path in sorted((LOCAL / "manifests").glob("*.yaml")):
        found += [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]
    return found


def _mib(quantity: str) -> int:
    assert quantity.endswith("Mi"), f"memory {quantity!r} is not in Mi; this test reads Mi only"
    return int(quantity[:-2])


def _deployments() -> dict[str, dict[str, Any]]:
    """Deployment name → its one container's image and memory limit."""
    found = {}
    for doc in _documents():
        if doc.get("kind") != "Deployment":
            continue
        (container,) = doc["spec"]["template"]["spec"]["containers"]
        found[doc["metadata"]["name"]] = {
            "image": container["image"],
            "limit": _mib(container["resources"]["limits"]["memory"]),
        }
    return found


def _budget() -> dict[str, int]:
    budget = yaml.safe_load((LOCAL / "budget.yaml").read_text(encoding="utf-8"))
    return {component["name"]: component["limit_mb"] for component in budget["components"]}


LEDGER = yaml.safe_load((LOCAL / "measured-memory.yaml").read_text(encoding="utf-8"))


def test_every_stack_pod_is_measured_on_the_image_it_runs() -> None:
    deployments = _deployments()
    measured = LEDGER["components"]
    assert set(deployments) == set(measured), (
        f"deployed {sorted(deployments)} but measured {sorted(measured)}; run the stack and "
        f"`uv run python scripts/local/measure_memory.py --write`"
    )
    stale = {
        name: (deployments[name]["image"], measured[name]["image"])
        for name in deployments
        if deployments[name]["image"] != measured[name]["image"]
    }
    assert not stale, (
        f"images changed since they were measured: {stale}. Start the stack at the new image "
        f"(`make local-up`) and record it (`uv run python scripts/local/measure_memory.py --write`) — "
        f"a limit chosen for one image is a guess about the next"
    )


def test_every_limit_clears_its_measured_peak_with_headroom() -> None:
    headroom = float(LEDGER["headroom"])
    tight = {
        name: f"limit {spec['limit']} Mi < {headroom} x {LEDGER['components'][name]['peak_mib']} Mi"
        for name, spec in _deployments().items()
        if spec["limit"] < math.ceil(LEDGER["components"][name]["peak_mib"] * headroom)
    }
    assert not tight, f"limits that would not survive their measured working set: {tight}"
    assert headroom >= measure_memory.HEADROOM, "the ledger was written with less headroom than the script requires"


def test_the_manifests_and_the_budget_agree() -> None:
    budget = _budget()
    differ = {
        name: (spec["limit"], budget.get(name))
        for name, spec in _deployments().items()
        if spec["limit"] != budget.get(name)
    }
    assert not differ, f"manifest limit vs budget.yaml limit_mb (preflight sums the budget): {differ}"


def test_the_quota_is_the_sum_of_this_namespaces_budget() -> None:
    (quota,) = [doc for doc in _documents() if doc.get("kind") == "ResourceQuota"]
    in_namespace = sum(limit for name, limit in _budget().items() if name not in NOT_A_STACK_POD)
    assert _mib(quota["spec"]["hard"]["limits.memory"]) == in_namespace


# --- the measurement script ---------------------------------------------------


def _cluster(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pods: dict[str, Any], peaks: dict[str, int]) -> Path:
    ledger = tmp_path / "measured-memory.yaml"
    monkeypatch.setattr(measure_memory, "LEDGER", ledger)
    monkeypatch.setattr(measure_memory, "_pods", lambda: pods)
    monkeypatch.setattr(measure_memory, "measure", lambda samples, interval: peaks)
    return ledger


def _pod(image: str, *, ready: bool = True, reason: str | None = None) -> dict[str, Any]:
    return {"image": image, "restarts": 3 if reason else 0, "last_reason": reason, "ready": ready}


def test_an_oom_killed_component_is_not_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    ledger = _cluster(
        monkeypatch, tmp_path, {"grafana": _pod("g:13", ready=False, reason="OOMKilled")}, {"grafana": 199}
    )

    assert measure_memory.main(["--write"]) == 1
    assert "UNHEALTHY" in capsys.readouterr().out
    assert not ledger.exists()


def test_a_limit_without_headroom_is_not_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ledger = _cluster(monkeypatch, tmp_path, {"grafana": _pod("g:13")}, {"grafana": 450})

    assert measure_memory.main(["--write"]) == 1
    assert not ledger.exists()


def test_a_node_restart_is_not_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Restarts whose last reason is `Unknown` are the node restarting under Docker, not the process failing."""
    ledger = _cluster(monkeypatch, tmp_path, {"jaeger": _pod("j:1", reason="Unknown")}, {"jaeger": 16})

    assert measure_memory.main(["--write"]) == 0
    assert yaml.safe_load(ledger.read_text(encoding="utf-8"))["components"]["jaeger"] == {
        "image": "j:1",
        "peak_mib": 16,
    }


def test_a_quieter_run_does_not_lower_what_a_busier_one_measured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The first rewrite replaced Grafana's 395 MiB with an idle 267; a limit could then have been cut below it."""
    ledger = _cluster(monkeypatch, tmp_path, {"jaeger": _pod("j:1")}, {"jaeger": 40})
    assert measure_memory.main(["--write"]) == 0

    monkeypatch.setattr(measure_memory, "measure", lambda samples, interval: {"jaeger": 20})
    assert measure_memory.main(["--write"]) == 0
    assert yaml.safe_load(ledger.read_text(encoding="utf-8"))["components"]["jaeger"]["peak_mib"] == 40

    monkeypatch.setattr(measure_memory, "_pods", lambda: {"jaeger": _pod("j:2")})
    assert measure_memory.main(["--write"]) == 0
    recorded = yaml.safe_load(ledger.read_text(encoding="utf-8"))["components"]["jaeger"]
    assert recorded == {"image": "j:2", "peak_mib": 20}, "a new image must be measured afresh"


# --- `make local-up` names only what is down ------------------------------------


def test_only_the_unavailable_deployment_is_named_with_its_reason() -> None:
    """Round eighteen: five components Available, Grafana OOMKilled — and the message named all six."""
    import explain_unavailable

    def deployment(name: str, available: int) -> dict[str, Any]:
        return {
            "metadata": {"name": name},
            "spec": {"selector": {"matchLabels": {"app": name}}},
            "status": {"availableReplicas": available} if available else {},
        }

    names = ["postgres", "object-store", "otel-collector", "jaeger", "prometheus"]
    deployments = {"items": [deployment(name, 1) for name in names] + [deployment("grafana", 0)]}
    grafana = {
        "metadata": {"labels": {"app": "grafana"}},
        "status": {
            "containerStatuses": [
                {
                    "name": "grafana",
                    "restartCount": 3,
                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                    "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
                }
            ]
        },
    }

    lines = explain_unavailable.unavailable(deployments, {"items": [grafana]})

    assert lines == ["grafana: grafana: CrashLoopBackOff (last: OOMKilled), restarts 3"]
