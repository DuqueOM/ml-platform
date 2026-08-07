"""The GitOps matrix must build, and must not quietly lose a member.

`kubectl kustomize` renders without a cluster and provisions nothing, so this
runs while the cloud work is deliberately paused (constraint S3).

One thing these tests deliberately do NOT claim: that the NetworkPolicies
work. The local cluster runs kindnet, which accepts a NetworkPolicy and
enforces nothing — see `test_the_local_cluster_cannot_validate_networkpolicies`.
Applying one here and watching it succeed would be the most convincing kind of
false evidence, because the API server reports success.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAYS = REPO_ROOT / "platform" / "kubernetes" / "overlays"
APPLICATIONSET = REPO_ROOT / "platform" / "gitops" / "applicationset.yaml"

CLOUDS = ("gcp", "aws")
ENVIRONMENTS = ("dev", "staging", "prod")

pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")


def _build(overlay: Path) -> list[dict]:  # type: ignore[type-arg]
    result = subprocess.run(["kubectl", "kustomize", str(overlay)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{overlay.name} does not build:\n{result.stderr}"
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_the_matrix_is_complete() -> None:
    """Six overlays: two clouds by three environments.

    Asserted against the product, not against a count. A count passes when
    someone adds `gcp-qa` and deletes `aws-prod`, which is the change most
    likely to go unnoticed and most expensive to discover.
    """
    expected = {f"{cloud}-{env}" for cloud in CLOUDS for env in ENVIRONMENTS}
    found = {path.name for path in OVERLAYS.iterdir() if path.is_dir()}
    assert found == expected, f"matrix is incomplete: missing {expected - found}, extra {found - expected}"


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_builds(cloud: str, env: str) -> None:
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    kinds = {doc["kind"] for doc in documents}
    assert {"Deployment", "Service", "PodDisruptionBudget", "NetworkPolicy"} <= kinds


@pytest.mark.parametrize("cloud", CLOUDS)
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_every_overlay_carries_default_deny(cloud: str, env: str) -> None:
    """An allow-list without a deny changes nothing: the traffic already flowed."""
    documents = _build(OVERLAYS / f"{cloud}-{env}")
    policies = {doc["metadata"]["name"] for doc in documents if doc["kind"] == "NetworkPolicy"}
    assert "default-deny" in policies
    assert "allow-dns" in policies, "a default-deny namespace with no DNS egress breaks every lookup"


@pytest.mark.parametrize("cloud", CLOUDS)
def test_production_runs_more_replicas_than_dev(cloud: str) -> None:
    """The overlays must actually differ; identical ones are six copies of one."""

    def replicas(env: str) -> int:
        documents = _build(OVERLAYS / f"{cloud}-{env}")
        return next(doc["spec"]["replicas"] for doc in documents if doc["kind"] == "Deployment")

    assert replicas("prod") > replicas("dev")


def test_the_applicationset_generates_the_same_matrix() -> None:
    """ArgoCD's generator and the overlay directories must not disagree.

    A generated Application whose path does not exist syncs to nothing and
    reports Healthy, which is the failure mode of a matrix that drifted.
    """
    spec = yaml.safe_load(APPLICATIONSET.read_text(encoding="utf-8"))
    matrix = spec["spec"]["generators"][0]["matrix"]["generators"]

    clouds = {element["cloud"] for element in matrix[0]["list"]["elements"]}
    environments = {element["env"] for element in matrix[1]["list"]["elements"]}

    assert clouds == set(CLOUDS)
    assert environments == set(ENVIRONMENTS)

    for cloud in clouds:
        for env in environments:
            assert (OVERLAYS / f"{cloud}-{env}").is_dir(), (
                f"the ApplicationSet generates {cloud}-{env}, which has no overlay to sync"
            )


def test_production_does_not_auto_sync() -> None:
    """Pull-based reconciliation applies whatever reaches main.

    With prod auto-syncing, the promotion gate stops being a gate: the model
    is deployed by the act of merging.
    """
    spec = yaml.safe_load(APPLICATIONSET.read_text(encoding="utf-8"))
    elements = spec["spec"]["generators"][0]["matrix"]["generators"][1]["list"]["elements"]
    autosync = {element["env"]: element["autosync"] for element in elements}

    assert autosync["prod"] == "false"
    assert autosync["dev"] == "true"


def test_nothing_prunes_automatically() -> None:
    """Prune deletes resources absent from git — including ones a human added
    during an incident, at the moment they are load-bearing."""
    spec = yaml.safe_load(APPLICATIONSET.read_text(encoding="utf-8"))
    assert spec["spec"]["template"]["spec"]["syncPolicy"]["automated"]["prune"] is False


@pytest.mark.local
def test_the_local_cluster_cannot_validate_networkpolicies() -> None:
    """States what local validation CANNOT prove, and checks the reason holds.

    kind's default CNI is kindnet, which has no NetworkPolicy implementation:
    the API server accepts the object and nothing enforces it. Applying a
    default-deny here and watching traffic still flow — or watching the apply
    succeed and concluding it works — is the most convincing false evidence
    available, because every command reports success.

    If this ever fails, kind has gained a policy-capable CNI and the local
    stack CAN start proving something it currently cannot.
    """
    result = subprocess.run(
        ["kubectl", "get", "daemonset", "-n", "kube-system", "-o", "name"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    if result.returncode != 0:
        pytest.skip("no cluster reachable")

    assert "kindnet" in result.stdout, (
        "the CNI is no longer kindnet; NetworkPolicy enforcement may now be testable locally"
    )
