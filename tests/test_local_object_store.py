"""The local object store keeps what is written to it, and `make local-up` creates what its consumers address.

R15-20 replaced MinIO, whose image could no longer be pulled anonymously, and
its remediation found two more things wrong with the store: it ran over
`emptyDir`, so any pod restart emptied it while the lakehouse catalogue still
named its files; and nothing created the buckets the lakehouse and DVC write
to, so they existed only while someone had made them by hand. These hold both
without a cluster; tests/local proves them on one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from pyarrow import fs

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "platform" / "local" / "manifests" / "20-object-store.yaml"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "local"))

import provision_object_store as provision  # noqa: E402


def _documents() -> dict[str, dict[str, Any]]:
    return {doc["kind"]: doc for doc in yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")) if doc}


def test_the_store_keeps_its_data_across_a_pod_restart() -> None:
    """Over emptyDir, a memory-limit change was enough to empty it."""
    documents = _documents()
    claim = documents["PersistentVolumeClaim"]["metadata"]["name"]
    pod = documents["Deployment"]["spec"]["template"]["spec"]
    (volume,) = [v for v in pod["volumes"] if v["name"] == "data"]

    assert volume.get("persistentVolumeClaim", {}).get("claimName") == claim, "the data volume is not the claim"
    assert "emptyDir" not in volume


def test_local_up_provisions_the_buckets() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile[makefile.index("\nlocal-up:") : makefile.index("\n.PHONY: local-endpoints")]

    assert "scripts/local/provision_object_store.py" in recipe


def test_the_buckets_are_read_from_their_consumers() -> None:
    """Not restated: the warehouse from the lakehouse module, the remote from DVC's committed config."""
    from demand_forecast.lakehouse import LOCAL_WAREHOUSE

    assert provision.buckets() == sorted({LOCAL_WAREHOUSE.removeprefix("s3://").strip("/"), "ml-platform-data"})


def test_a_dvc_config_without_its_default_remote_is_refused(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text("[core]\n    remote = gone\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no default remote"):
        provision.dvc_bucket(config)


def test_a_remote_that_is_not_an_s3_bucket_is_refused(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text("[core]\n    remote = here\n['remote \"here\"']\n    url = /mnt/dvc\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not an s3:// URI"):
        provision.dvc_bucket(config)


def test_provisioning_creates_what_is_missing_and_leaves_the_rest(tmp_path: Path) -> None:
    """Idempotent: `make local-up` runs it every time, on a store that may already hold the buckets."""
    store = fs.SubTreeFileSystem(str(tmp_path), fs.LocalFileSystem())
    store.create_dir("lakehouse")

    assert provision.provision(store, ["lakehouse", "ml-platform-data"]) == ["ml-platform-data"]
    assert provision.provision(store, ["lakehouse", "ml-platform-data"]) == []
    assert (tmp_path / "ml-platform-data").is_dir()
