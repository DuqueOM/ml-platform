#!/usr/bin/env python3
"""Create the local object store's buckets — run by `make local-up`, idempotent.

The lakehouse writes to `s3://lakehouse/` and DVC's remote to
`s3://ml-platform-data/`, and nothing created either. They existed only while
someone had made them by hand: when a memory-limit change recreated the store's
pod, both were gone and every integration test that needs them failed (R15-20's
remediation). So the stack provisions what its consumers address, and reads
the names from those consumers rather than restating them:

- the warehouse from `demand_forecast.lakehouse.LOCAL_WAREHOUSE`;
- the DVC remote from `.dvc/config`'s default remote URL.

    uv run python scripts/local/provision_object_store.py
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from pyarrow import fs

REPO_ROOT = Path(__file__).resolve().parents[2]
DVC_CONFIG = REPO_ROOT / ".dvc" / "config"

ENDPOINT = os.environ.get("OBJECT_STORE_ENDPOINT", "http://localhost:19000")
ACCESS_KEY = os.environ.get("OBJECT_STORE_ACCESS_KEY", "mlplatform")
SECRET_KEY = os.environ.get("OBJECT_STORE_SECRET_KEY", "local-only-not-a-secret")


def _bucket(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"{uri!r} is not an s3:// URI naming a bucket")
    return parsed.netloc


def dvc_bucket(config_path: Path = DVC_CONFIG) -> str:
    """The bucket of DVC's default remote, from the committed `.dvc/config`."""
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    remote = config.get("core", "remote", fallback=None)
    section = f"'remote \"{remote}\"'"
    if not remote or not config.has_section(section):
        raise ValueError(f"{config_path} names no default remote with a section of its own")
    return _bucket(config.get(section, "url"))


def buckets() -> list[str]:
    """Every bucket the local stack's consumers address, in a stable order."""
    sys.path.insert(0, str(REPO_ROOT / "projects" / "demand-forecast" / "src"))
    from demand_forecast.lakehouse import LOCAL_WAREHOUSE

    return sorted({_bucket(LOCAL_WAREHOUSE), dvc_bucket()})


def provision(store: fs.FileSystem, names: list[str]) -> list[str]:
    """Create each bucket that does not exist; return the ones created."""
    created = []
    for name in names:
        if store.get_file_info(name).type == fs.FileType.NotFound:
            store.create_dir(name)
            created.append(name)
    return created


def main() -> int:
    store = fs.S3FileSystem(
        endpoint_override=ENDPOINT,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        region="us-east-1",
        allow_bucket_creation=True,
    )
    names = buckets()
    created = provision(store, names)
    kept = [name for name in names if name not in created]
    print(f"[object-store] {ENDPOINT}: created {created or 'none'}, already present {kept or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
