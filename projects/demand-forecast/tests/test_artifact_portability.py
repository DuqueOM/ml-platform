"""The artifact must be readable where no workspace package is installed.

ADR-008 records that the generated service cannot serve this project. QA-4
round eleven found a second, independent reason, one no version check could
see: the artifact pickled `demand_forecast.persist.ForecastModel` wrapping
`ml_core.conformal.SplitConformalRegressor`, and the serving image installs
neither — `services/demand-forecast-serving/requirements.txt` names no
workspace library. Loading it there fails with `ModuleNotFoundError` before
numpy's version is ever compared.

So this asserts the property the container actually needs: **the bytes of the
artifact reference no workspace module.** That is checked against the file,
not against what this interpreter happens to be able to import — in the test
process both packages ARE importable, so an import-based check would pass on
the defect it exists to catch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import polars as pl
import pytest
from demand_forecast.persist import ForecastModel, fit_final, load, save

#: Package names that must not appear in the artifact. Byte strings, because
#: that is how a pickle records a module it will import on load.
WORKSPACE_PACKAGES = (b"demand_forecast", b"ml_core", b"data_contracts", b"feature_defs", b"serving_core")


def _demand(n_hours: int = 1200, zones: int = 2, seed: int = 0) -> pl.DataFrame:
    """Enough signal to fit, and no more.

    Deliberately smaller and simpler than `test_persist.py`'s generator:
    portability is a property of the file's shape, not of how well the model
    predicts, and a test that needs a good model to check a serialisation
    property would fail for reasons unrelated to its subject.
    """
    generator = np.random.default_rng(seed)
    frames = []
    for zone in range(1, zones + 1):
        index = np.arange(n_hours)
        counts = 60 + 10 * zone + 15 * np.sin(2 * np.pi * index / 24) + generator.normal(0, 3, n_hours)
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


@pytest.fixture(scope="module")
def artifact(tmp_path_factory: pytest.TempPathFactory) -> Path:
    model = fit_final(_demand(), seed=3)
    path = tmp_path_factory.mktemp("artifact") / "model.joblib"
    save(model, path)
    return path


@pytest.mark.parametrize("package", WORKSPACE_PACKAGES)
def test_the_artifact_names_no_workspace_package(artifact: Path, package: bytes) -> None:
    """The finding itself. Fails against the previous artifact shape."""
    assert package not in artifact.read_bytes(), (
        f"the artifact references {package.decode()}, so loading it requires that package installed. "
        f"The serving image installs no workspace library, so the model cannot be read there at all"
    )


def test_the_artifact_does_name_the_libraries_the_image_does_install(artifact: Path) -> None:
    """The converse, so the test above cannot pass by the artifact being empty.

    scikit-learn is in the image's requirements, and the estimator is the one
    object that still travels as an object — deliberately, because rebuilding
    a fitted gradient booster from data is not a serialisation format anyone
    should write by hand.
    """
    assert b"sklearn" in artifact.read_bytes()


def test_predictions_survive_the_round_trip(artifact: Path) -> None:
    """Portability is worthless if the numbers change."""
    from demand_forecast.features import build_features
    from demand_forecast.train import select_modellable_zones

    restored = load(artifact)
    featured = build_features(select_modellable_zones(_demand()))
    point, lower, upper = restored.predict(featured)

    assert np.all(np.isfinite(point))
    assert np.all(lower <= point)
    assert np.all(point <= upper)


def test_the_payload_a_container_would_read_needs_only_sklearn(artifact: Path) -> None:
    """What a serving image does with this file, done here without the model class.

    No `demand_forecast` import: the estimator predicts and the quantile is
    added and subtracted. If this ever needs a workspace import again, the
    artifact has stopped being portable whatever the test above says.
    """
    payload = joblib.load(artifact)
    assert set(payload) >= {"estimator", "conformal_quantile", "feature_columns", "schema"}

    matrix = np.zeros((3, len(payload["feature_columns"])), dtype=np.float64)
    point = payload["estimator"].predict(matrix)
    lower = point - payload["conformal_quantile"]
    upper = point + payload["conformal_quantile"]

    assert point.shape == (3,)
    assert np.all(upper - lower == pytest.approx(2 * payload["conformal_quantile"]))


def test_a_reconstructed_model_matches_the_one_that_was_saved(artifact: Path) -> None:
    """`load` rebuilds rather than unpickles, so the rebuild must be faithful."""
    restored = load(artifact)
    payload = joblib.load(artifact)

    assert isinstance(restored, ForecastModel)
    assert restored.conformal.quantile == payload["conformal_quantile"]
    assert restored.conformal.n_calibration == payload["conformal_n_calibration"]
    assert restored.feature_columns == tuple(payload["feature_columns"])
    assert restored.conformal.alpha == payload["alpha"]
