"""Both adapters must be valid, consume the same module, and stay measurable.

The plan's Phase 2 claim is not "it runs on two clouds" — anything runs on two
clouds if you write it twice. It is that the difference is isolated and
COUNTED. So these tests assert the structure that makes the count meaningful,
not the count itself: a number nobody can interpret is a number nobody acts on.

`terraform validate` needs no credentials and creates nothing, which is what
lets this run while the cloud work is deliberately paused (constraint S3).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TERRAFORM = REPO_ROOT / "platform" / "terraform"
ADAPTERS = ("gcp", "aws")

pytestmark = pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")


def _validate(directory: Path) -> subprocess.CompletedProcess[str]:
    subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        cwd=directory, capture_output=True, text=True, timeout=180, check=True,
    )  # fmt: skip
    return subprocess.run(["terraform", "validate"], cwd=directory, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_each_adapter_is_valid_terraform(adapter: str) -> None:
    result = _validate(TERRAFORM / adapter)
    assert result.returncode == 0, f"{adapter} does not validate:\n{result.stdout}\n{result.stderr}"


def test_the_shared_module_is_valid_on_its_own() -> None:
    """It must not depend on an adapter to be coherent."""
    result = _validate(TERRAFORM / "modules" / "service-runtime")
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_each_adapter_consumes_the_shared_module(adapter: str) -> None:
    """Two configs that share no code are two configs, not one definition."""
    source = (TERRAFORM / adapter / "main.tf").read_text(encoding="utf-8")
    assert 'source = "../modules/service-runtime"' in source


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_no_adapter_hardcodes_its_state_bucket(adapter: str) -> None:
    """A hardcoded bucket is how a dev apply mutates production state.

    The backend is a partial configuration; the bucket arrives per environment
    from `backend-configs/<env>.hcl`.
    """
    source = (TERRAFORM / adapter / "main.tf").read_text(encoding="utf-8")
    assert 'backend "gcs" {}' in source or 'backend "s3" {}' in source

    configs = sorted((TERRAFORM / adapter / "backend-configs").glob("*.hcl"))
    assert {path.stem for path in configs} == {"dev", "staging", "prod"}

    buckets = {
        line.split("=", 1)[1].strip().strip('"')
        for path in configs
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("bucket")
    }
    assert len(buckets) == 3, f"environments share a state bucket: {buckets}"


def test_the_shared_module_names_no_cloud() -> None:
    """The moment a provider appears in `modules/`, it stops being shared.

    `size_map` names both clouds as KEYS — that is the recorded translation
    between one intent and two vocabularies, and it is the point. What must not
    appear is a provider block or a resource.
    """
    module = TERRAFORM / "modules" / "service-runtime"
    for path in module.glob("*.tf"):
        source = path.read_text(encoding="utf-8")
        assert "provider " not in source, f"{path.name} declares a provider; it is not shared"
        assert 'resource "' not in source, f"{path.name} declares a resource; it is not shared"


def test_the_measured_surface_is_current_and_within_budget() -> None:
    """The derived report must match the filesystem, like every other one here."""
    result = subprocess.run(
        ["python3", str(REPO_ROOT / "scripts" / "measure_cloud_surface.py"), "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout


def test_the_ceiling_can_actually_be_exceeded() -> None:
    """A budget nothing can breach is not a budget.

    Guards the arithmetic rather than the current value: if `adapter_share`
    were ever computed against the wrong denominator, the ceiling would become
    unreachable and this check would go quiet forever.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from measure_cloud_surface import MAX_ADAPTER_SHARE, Surface

    leaking = Surface(shared=1, per_adapter={"gcp": 50, "aws": 50})
    assert not leaking.within_budget
    assert leaking.adapter_share > MAX_ADAPTER_SHARE

    healthy = Surface(shared=100, per_adapter={"gcp": 5, "aws": 5})
    assert healthy.within_budget


def test_a_destroyable_cluster_says_so_explicitly() -> None:
    """`terraform destroy` is this plan's only cost control, and it refuses by default.

    `hashicorp/google ~> 6.0` defaults `google_container_cluster` to
    `deletion_protection = true`, so `destroy` declines to delete the cluster.
    The technical plan makes that the acceptance criterion: *"infrastructure
    exists only inside validation windows; `terraform destroy` is an acceptance
    criterion, not a follow-up, and the phase is not complete until the billing
    export shows zero standing spend."* A cluster that cannot be destroyed
    leaves the bill running — the one failure the greenfield posture exists to
    prevent, and the plan would have discovered it at teardown.

    Asserted as EXPLICIT rather than as `false`: a repository that later runs a
    cluster outliving a window should set it to `true` here, and the defect is
    inheriting a default that decides this either way.
    """
    gcp = "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "platform" / "terraform" / "gcp").glob("*.tf")
    )
    assert "deletion_protection" in gcp, (
        "gcp: google_container_cluster does not set `deletion_protection`, and the pinned provider defaults it "
        "to true — `terraform destroy` then refuses, leaving the bill running."
    )

    # AWS is not symmetric, and the asymmetry is the provider's rather than
    # this repository's. `aws_eks_cluster` gained `deletion_protection` in
    # hashicorp/aws 6.x; under the pinned `~> 5.0` the argument does not exist
    # and `terraform validate` would reject it. Nothing blocks destroy there
    # today — but a version bump changes that silently, so the condition is
    # read from the pin rather than remembered.
    aws = "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "platform" / "terraform" / "aws").glob("*.tf")
    )
    pinned_six = re.search(r'source\s*=\s*"hashicorp/aws"\s*\n\s*version\s*=\s*"~>\s*([6-9]|\d{2,})', aws)
    if pinned_six:
        assert "deletion_protection" in aws, (
            "aws: the provider pin moved to 6.x, where `aws_eks_cluster` has `deletion_protection` — state it "
            "explicitly, for the same reason as GCP."
        )
