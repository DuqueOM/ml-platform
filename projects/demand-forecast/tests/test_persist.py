"""A saved model must be the same model when it comes back.

The interesting failures here are not "the file did not write". They are the
ones that leave a loadable artifact that predicts something different from what
was fit: a calibration window selected by row position instead of by time, a
feature list that round-trips as a set and loses its order, a version string
that labels two different models identically so a rollback changes nothing.

Each of those has a test below, and each is written to fail on the defect
rather than on its absence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from demand_forecast.features import FEATURE_COLUMNS, build_features
from demand_forecast.persist import ARTIFACT_SCHEMA, ForecastModel, fit_final, load, save
from demand_forecast.train import select_modellable_zones


def _demand(n_hours: int = 2400, zones: int = 2, seed: int = 0) -> pl.DataFrame:
    """Hourly demand with weekly and daily seasonality, a trend, and noise."""
    generator = np.random.default_rng(seed)
    rows = []
    for zone in range(1, zones + 1):
        index = np.arange(n_hours)
        level = 80 + 20 * zone + 0.02 * index
        weekly = 30 * np.sin(2 * np.pi * index / 168)
        daily = 18 * np.sin(2 * np.pi * index / 24)
        noise = generator.normal(0, 4, n_hours)
        counts = np.clip(level + weekly + daily + noise, 0, None)
        rows.append(
            pl.DataFrame(
                {
                    "zone_id": [zone] * n_hours,
                    "event_time": [datetime(2024, 1, 1) + timedelta(hours=int(i)) for i in index],
                    "trip_count": counts,
                }
            )
        )
    return pl.concat(rows)


@pytest.fixture(scope="module")
def model() -> ForecastModel:
    return fit_final(_demand(), seed=7)


def _sidecar_for(artifact: Path) -> None:
    """Write the digest sidecar `load` now requires.

    These tests build artifacts by hand to exercise a refusal further down —
    a wrong schema, a pickled object. `load` verifies the recorded digest
    before it unpickles anything (QA-4 W-10), so without this they would all
    fail on the missing sidecar and stop testing what they are named for.
    """
    import hashlib
    import json

    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.with_suffix(".json").write_text(json.dumps({"sha256": digest}), encoding="utf-8")


def test_a_saved_model_predicts_identically_when_loaded(model: ForecastModel, tmp_path: Path) -> None:
    """Round-trip equality, byte for byte.

    Asserted with `array_equal` rather than `allclose`: a persistence layer that
    changes the tenth decimal is still a persistence layer that changed the
    answer, and tolerating it hides exactly the dtype narrowing this would
    otherwise catch.
    """
    featured = build_features(select_modellable_zones(_demand(seed=1)))
    before = model.predict(featured)

    artifact = tmp_path / "model.joblib"
    save(model, artifact)
    after = load(artifact).predict(featured)

    for original, restored in zip(before, after, strict=True):
        assert np.array_equal(original, restored)


def test_the_calibration_window_is_the_recent_tail_not_a_slice_of_rows(model: ForecastModel) -> None:
    """The defect this repository already paid for once.

    Splitting a PANEL by row position selects whole zones, not a recent window:
    the model is then calibrated on a zone it never trained on, and coverage
    came out at 53.8% against a nominal 90%. The split must be by time, so the
    calibration window starts after the last training hour.
    """
    assert model.calibrated_from > model.trained_through
    assert len(model.zones) == 2, "both zones must be present on BOTH sides of a time split"


def test_a_frame_missing_a_feature_is_refused(model: ForecastModel) -> None:
    featured = build_features(select_modellable_zones(_demand())).drop(FEATURE_COLUMNS[0])

    with pytest.raises(ValueError, match="frame is missing"):
        model.predict(featured)


def test_column_order_in_the_frame_does_not_change_the_prediction(model: ForecastModel) -> None:
    """Selection is by NAME, so the caller's column order is not a contract.

    Written after the first version of `predict` compared the frame's physical
    order against the model's and refused a perfectly valid frame:
    `build_features` emits `roll_mean_24, roll_std_24, roll_mean_168` while
    `FEATURE_COLUMNS` groups the means first. Both are correct, and a check
    that rejects one of them is a false contract — the kind that gets loosened
    under pressure and takes the real check with it.
    """
    featured = build_features(select_modellable_zones(_demand()))
    swapped = [*FEATURE_COLUMNS[1:2], *FEATURE_COLUMNS[0:1], *FEATURE_COLUMNS[2:]]
    reordered = featured.select([*swapped, "zone_id", "event_time", "trip_count"])

    for straight, shuffled in zip(model.predict(featured), model.predict(reordered), strict=True):
        assert np.array_equal(straight, shuffled)


def test_the_version_changes_when_the_model_does(tmp_path: Path) -> None:
    """Two different models must not carry the same version.

    A hand-set version is one edit away from labelling both the same, and the
    first symptom is a rollback that deploys the identical artifact.
    """
    first = save(fit_final(_demand(seed=1), seed=1), tmp_path / "a.joblib")
    second = save(fit_final(_demand(seed=2), seed=2), tmp_path / "b.joblib")

    assert first["version"] != second["version"]


def test_the_sidecar_answers_what_is_deployed_without_unpickling(model: ForecastModel, tmp_path: Path) -> None:
    """An operator with no Python environment still has to read this."""
    import json

    artifact = tmp_path / "model.joblib"
    save(model, artifact)
    sidecar = json.loads(artifact.with_suffix(".json").read_text(encoding="utf-8"))

    assert sidecar["trained_through"] == model.trained_through
    assert sidecar["nominal_coverage"] == pytest.approx(1.0 - model.alpha)
    assert sidecar["feature_columns"] == list(FEATURE_COLUMNS)
    assert sidecar["n_zones"] == 2


def test_an_artifact_from_another_schema_is_refused(model: ForecastModel, tmp_path: Path) -> None:
    """Reading a payload whose fields changed meaning is worse than failing."""
    import joblib
    from demand_forecast.persist import _payload

    stale = {**_payload(model), "schema": ARTIFACT_SCHEMA + 1}
    artifact = tmp_path / "stale.joblib"
    joblib.dump(stale, artifact)
    _sidecar_for(artifact)

    with pytest.raises(ValueError, match="artifact schema"):
        load(artifact)


def test_an_artifact_that_pickled_the_model_object_is_refused(model: ForecastModel, tmp_path: Path) -> None:
    """Schema 1 wrote the object itself, and that is exactly what R11-3 removed.

    Such a file is readable only where `demand_forecast` and `ml_core` are
    installed — which the serving image is not. It is refused with a message
    that says so, rather than converted: a conversion would have to trust
    fields whose meaning is what changed.
    """
    import joblib

    artifact = tmp_path / "schema1.joblib"
    joblib.dump(model, artifact)
    _sidecar_for(artifact)

    with pytest.raises(ValueError, match="not an artifact payload"):
        load(artifact)


def test_a_history_shorter_than_the_calibration_tail_fails_clearly() -> None:
    """Not a crash inside sklearn about an empty array."""
    with pytest.raises(ValueError, match=r"too short|enough history"):
        fit_final(_demand(n_hours=400), calibration_hours=100_000)


def test_the_interval_covers_at_close_to_its_nominal_rate(model: ForecastModel) -> None:
    """Coverage on data the model has not seen, which is the only kind that counts.

    The band is wide (80% to 97% against a nominal 90%) on purpose: this asserts
    the calibration is WIRED, not that a particular sample lands on the nose.
    A tight bound here would fail on the seed rather than on the defect.
    """
    unseen = build_features(select_modellable_zones(_demand(seed=99)))
    point, lower, upper = model.predict(unseen)
    truth = unseen["trip_count"].to_numpy().astype(np.float64)

    covered = float(np.mean((truth >= lower) & (truth <= upper)))
    assert 0.80 <= covered <= 0.97, f"coverage {covered:.3f} against a nominal {1 - model.alpha:.2f}"
    assert np.all(upper > point)
    assert np.all(lower < point)


def test_a_flipped_byte_is_refused(model: ForecastModel, tmp_path: Path) -> None:
    """The artifact recorded its own digest and nobody checked it (QA-4 W-10).

    One byte, in the middle of the file: a truncated copy, a partial download
    or an edited artifact all look like this, and all loaded cleanly before.
    """
    artifact = tmp_path / "model.joblib"
    save(model, artifact)

    raw = bytearray(artifact.read_bytes())
    middle = len(raw) // 2
    raw[middle] ^= 0xFF
    artifact.write_bytes(bytes(raw))

    with pytest.raises(ValueError, match="does not match the digest"):
        load(artifact)


def test_a_truncated_artifact_is_refused(model: ForecastModel, tmp_path: Path) -> None:
    """The failure an interrupted copy produces, caught on the digest rather than inside joblib."""
    artifact = tmp_path / "model.joblib"
    save(model, artifact)
    raw = artifact.read_bytes()
    artifact.write_bytes(raw[: len(raw) // 2])

    with pytest.raises(ValueError, match="does not match the digest"):
        load(artifact)


def test_an_artifact_without_its_sidecar_is_refused(model: ForecastModel, tmp_path: Path) -> None:
    """The pair is the artifact. Half of it cannot prove what it is."""
    artifact = tmp_path / "model.joblib"
    save(model, artifact)
    artifact.with_suffix(".json").unlink()

    with pytest.raises(ValueError, match="no metadata sidecar"):
        load(artifact)


def test_the_sidecar_records_the_whole_digest_not_a_label(model: ForecastModel, tmp_path: Path) -> None:
    """`version` carries twelve characters to tell artifacts apart; verification needs all of it."""
    import hashlib
    import json

    artifact = tmp_path / "model.joblib"
    metadata = save(model, artifact)
    sidecar = json.loads(artifact.with_suffix(".json").read_text(encoding="utf-8"))

    assert len(sidecar["sha256"]) == 64
    assert sidecar["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert sidecar["sha256"].startswith(metadata["version"].split("+")[1])


def test_an_intact_artifact_still_loads(model: ForecastModel, tmp_path: Path) -> None:
    """The converse, so the four refusals above cannot pass by refusing everything."""
    artifact = tmp_path / "model.joblib"
    save(model, artifact)

    assert load(artifact).trained_through == model.trained_through
