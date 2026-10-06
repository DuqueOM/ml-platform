#!/usr/bin/env python3
"""Resolve the serving image's requirements to exact versions, so a scanner can read them.

`services/demand-forecast-serving/requirements.txt` pins with `~=`, and Trivy's
pip analyser reads only `==`: it skipped the image's dependencies entirely, and
`pyarrow 18.0.0` — inside CVE-2026-25087's affected range — was in the image
with no gate able to see it (QA-4 round sixteen, P1). Resolving is also the
honest form of the question: a `~=` range is not what the image runs, the
versions pip picks on the next build are.

The image installs in two steps, as `scripts/check_artifact_compatibility.py`
reads them: the base requirements, then `requirements-<cloud>.txt` for the
provider it is built for. So there is one resolution per image the Dockerfile
can produce — base alone, and base plus each provider — each written as
`<out>/serving-<variant>/requirements.txt`, the file name Trivy recognises.

Resolved for the Dockerfile's own Python and a Linux x86_64 platform, so the
versions are those a build on the runner's architecture would install.

    uv run python scripts/resolve_serving_requirements.py            # -> .trivy-resolved/
    uv run python scripts/resolve_serving_requirements.py --out DIR
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / ".trivy-resolved"

#: Bounded: a resolution is seconds against a warm index; this turns a hang into a failure.
RESOLVE_TIMEOUT_SECONDS = 300


def variants() -> dict[str, list[Path]]:
    """Every image the Dockerfile can build, as the requirement files it installs, in order."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_artifact_compatibility import CLOUD_PROVIDERS, READER

    found = {"base": [READER]}
    for provider in CLOUD_PROVIDERS:
        found[provider] = [READER, READER.parent / f"requirements-{provider}.txt"]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="directory to write the resolutions under")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_artifact_compatibility import image_environment

    python = image_environment()["python_version"]
    out = Path(args.out)
    for variant, files in variants().items():
        missing = [str(path) for path in files if not path.is_file()]
        if missing:
            print(f"  FAIL [serving-resolve] {variant}: {missing} do not exist")
            return 1
        target = out / f"serving-{variant}" / "requirements.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--quiet",
                "--no-header",
                "--python-version",
                python,
                "--python-platform",
                "x86_64-manylinux_2_28",
                *map(str, files),
                "-o",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=RESOLVE_TIMEOUT_SECONDS,
            check=False,
        )
        if done.returncode != 0:
            print(f"  FAIL [serving-resolve] {variant} did not resolve:\n{done.stderr}")
            return 1
        pins = sum(1 for line in target.read_text(encoding="utf-8").splitlines() if "==" in line)
        print(f"  ok   [serving-resolve] {variant}: {pins} pinned packages on Python {python} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
