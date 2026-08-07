"""Both adapters must be valid, consume the same module, and stay measurable.

The plan's Phase 2 claim is not "it runs on two clouds" — anything runs on two
clouds if you write it twice. It is that the difference is isolated and
COUNTED. So these tests assert the structure that makes the count meaningful,
not the count itself: a number nobody can interpret is a number nobody acts on.

`terraform validate` needs no credentials and creates nothing, which is what
lets this run while the cloud work is deliberately paused (constraint S3).
"""

from __future__ import annotations

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
