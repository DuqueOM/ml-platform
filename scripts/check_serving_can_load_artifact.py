#!/usr/bin/env python3
"""The serving image's environment can load the model artifact and predict with it.

P14 (`check_artifact_compatibility.py`) compares VERSION SPECIFIERS across the
serving seam, and #108 holds its package list to what the artifact's pickle
names. Neither loads the artifact. QA-4 round fifteen did, in a virtual
environment built from `services/demand-forecast-serving/requirements.txt`
alone on the image's Python, and it failed:

    ValueError: <class 'numpy.random._pcg64.PCG64'> is not a known BitGenerator module.

R11-3 had been closed on the strength of the bytes naming no workspace
package, which was true and was not the property that mattered. This gate
checks the property that matters, the way the auditor did:

1. Fit a model on synthetic demand with this workspace and save it with
   `persist.save` — the code path the DAG publishes with.
2. Build a fresh environment with `uv`, on the Python the Dockerfile's `FROM`
   names, from the service's `requirements.txt` and nothing else.
3. In that environment, `joblib.load` the artifact and predict, and compare the
   predictions with the writer's on the same inputs.

It also asserts the environment cannot import `demand_forecast` or `ml_core`,
so a pass cannot come from a workspace package leaking into the reader.

It does NOT build the image: no Docker on the runner path this gate takes, and
the environment the image builds from is what decides whether the file loads.
It does not exercise the service's own loading code either: that code expects a
classification pipeline, which is the half of ADR-008 still undecided.

    uv run python scripts/check_serving_can_load_artifact.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE = REPO_ROOT / "services" / "demand-forecast-serving"
REQUIREMENTS = SERVICE / "requirements.txt"

#: Generous: a cold `uv pip install` of the service's requirements on a runner.
INSTALL_TIMEOUT_SECONDS = 900
#: Loading and predicting take seconds; this bound turns a hang into a failure.
READER_TIMEOUT_SECONDS = 120

#: Run by the SERVING environment's interpreter. Prints JSON, or exits non-zero.
_READER = """
import json, sys
import importlib.util
leaked = [name for name in ("demand_forecast", "ml_core") if importlib.util.find_spec(name) is not None]
import joblib, numpy, sklearn
payload = joblib.load(sys.argv[1])
features = numpy.asarray(json.loads(sys.argv[2]), dtype=float)
print(json.dumps({
    "leaked": leaked,
    "python": sys.version.split()[0],
    "numpy": numpy.__version__,
    "sklearn": sklearn.__version__,
    "joblib": joblib.__version__,
    "predictions": payload["estimator"].predict(features).tolist(),
}))
"""


def _synthetic_demand(n_hours: int = 2400, zones: int = 2):  # type: ignore[no-untyped-def]
    """Hourly demand with weekly and daily seasonality, a trend and noise — enough history to fit."""
    import numpy as np
    import polars as pl

    generator = np.random.default_rng(0)
    frames = []
    for zone in range(1, zones + 1):
        index = np.arange(n_hours)
        counts = (
            80
            + 20 * zone
            + 0.02 * index
            + 30 * np.sin(2 * np.pi * index / 168)
            + 18 * np.sin(2 * np.pi * index / 24)
            + generator.normal(0, 4, n_hours)
        )
        frames.append(
            pl.DataFrame(
                {
                    "zone_id": [zone] * n_hours,
                    "event_time": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in index],
                    "trip_count": np.clip(counts, 0, None),
                }
            )
        )
    return pl.concat(frames)


def _image_python() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_artifact_compatibility import image_environment

    return image_environment()["python_version"]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    # The serving environment must see none of this workspace: no inherited
    # virtualenv, no PYTHONPATH pointing at the workspace's sources.
    env = {key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "PYTHONPATH"}}
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=env)


def main() -> int:
    import numpy as np
    from demand_forecast.persist import fit_final, save

    python = _image_python()
    with tempfile.TemporaryDirectory() as scratch:
        artifact = Path(scratch) / "model.joblib"
        model = fit_final(_synthetic_demand(), seed=7)
        save(model, artifact)
        features = np.random.default_rng(3).normal(size=(20, len(model.feature_columns)))
        expected = model.estimator.predict(features)

        venv = Path(scratch) / "serving"
        for step, command in (
            ("create", ["uv", "venv", "--quiet", "--python", python, str(venv)]),
            (
                "install",
                ["uv", "pip", "install", "--quiet", "--python", str(venv / "bin" / "python"), "-r", str(REQUIREMENTS)],
            ),
        ):
            done = _run(command, INSTALL_TIMEOUT_SECONDS)
            if done.returncode != 0:
                print(f"  FAIL [serving-load] could not {step} the serving environment:\n{done.stderr}")
                print("\n[serving-load] FAILED")
                return 1

        read = _run(
            [str(venv / "bin" / "python"), "-c", _READER, str(artifact), json.dumps(features.tolist())],
            READER_TIMEOUT_SECONDS,
        )

    if read.returncode != 0:
        last = read.stderr.strip().splitlines()[-1] if read.stderr.strip() else "no output"
        print(f"  FAIL [serving-load] the serving environment cannot load the artifact: {last}")
        print("\n[serving-load] FAILED")
        return 1

    result = json.loads(read.stdout)
    failures = []
    if result["leaked"]:
        failures.append(f"the serving environment can import {result['leaked']}, so this check proves nothing")
    if not np.allclose(result["predictions"], expected, rtol=1e-9, atol=1e-9):
        failures.append("the serving environment's predictions differ from the writer's on the same inputs")

    versions = (
        f"Python {result['python']}, numpy {result['numpy']}, "
        f"scikit-learn {result['sklearn']}, joblib {result['joblib']}"
    )
    if failures:
        for failure in failures:
            print(f"  FAIL [serving-load] {failure}")
        print(f"\n[serving-load] FAILED ({versions})")
        return 1
    print(f"  ok   [serving-load] loaded and predicted identically under the image's requirements ({versions})")
    print("\n[serving-load] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
