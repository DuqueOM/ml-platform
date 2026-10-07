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
provider it is built for — after the Dockerfile's own
`pip install --upgrade pip setuptools wheel`, whose three unpinned packages
are resolved into every image variant too. So there is one resolution per
image the Dockerfile can produce — base alone, and base plus each provider —
each written as `<out>/serving-<variant>/requirements.txt`, the file name
Trivy recognises.

**And every other requirement set the service ships**, one resolution each:
development, training, EDA. They are not in the image, and they are what the
service tells its users to install — QA-4 round seventeen found pyarrow 18.0.0
(CVE-2026-25087) in every one of them, while R16-1 said "only the image is
affected". Discovered by globbing `requirements*.txt` under the service, so
a set added upstream is scanned the day it arrives.

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


#: The packages the Dockerfile upgrades before installing anything, unpinned.
IMAGE_TOOLING = ("pip", "setuptools", "wheel")

#: Requirement sets that cannot be installed on the image's Python at all, each
#: with the Python they ARE installable on and why. Resolved there, so they are
#: still scanned, rather than skipped. A set listed here that resolves on the
#: image's Python again should leave the list — R17-2 tracks the one below.
PYTHON_FOR = {
    "eda-heavy": (
        "3.12",
        "htmlmin 0.1.12, which ydata-profiling pulls in, imports `cgi` in its build; Python 3.13 removed `cgi`, "
        "so this set does not install on the image's Python (upstream, R17-2)",
    ),
}


def variants() -> dict[str, list[Path]]:
    """Every image the Dockerfile can build, as the requirement files it installs, in order."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_artifact_compatibility import CLOUD_PROVIDERS, READER

    found = {"base": [READER]}
    for provider in CLOUD_PROVIDERS:
        found[provider] = [READER, READER.parent / f"requirements-{provider}.txt"]
    return found


def requirement_sets() -> dict[str, list[Path]]:
    """Every OTHER requirement file the service ships, each resolved on its own: dev, train, EDA."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_artifact_compatibility import READER

    service = READER.parent
    in_images = {path for files in variants().values() for path in files}
    found = {}
    for path in sorted(service.rglob("requirements*.txt")):
        if path in in_images or ".venv" in path.parts:
            continue
        relative = path.relative_to(service)
        kind = relative.stem.removeprefix("requirements").lstrip("-")
        found["-".join(part for part in (*relative.parts[:-1], kind) if part)] = [path]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="directory to write the resolutions under")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_artifact_compatibility import image_environment

    python = image_environment()["python_version"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tooling = out / "image-tooling.in"
    tooling.write_text("\n".join(IMAGE_TOOLING) + "\n", encoding="utf-8")
    plan = {variant: [*files, tooling] for variant, files in variants().items()} | requirement_sets()
    for variant, files in plan.items():
        missing = [str(path) for path in files if not path.is_file()]
        if missing:
            print(f"  FAIL [serving-resolve] {variant}: {missing} do not exist")
            return 1
        target = out / f"serving-{variant}" / "requirements.txt"
        resolve_on = PYTHON_FOR.get(variant, (python, ""))[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--quiet",
                "--no-header",
                "--python-version",
                resolve_on,
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
        note = f" — {PYTHON_FOR[variant][1]}" if variant in PYTHON_FOR else ""
        print(f"  ok   [serving-resolve] {variant}: {pins} pinned packages on Python {resolve_on} -> {target}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
