"""Fit a final model and write it down, so something other than a test can use it.

Until now training only backtested. :func:`demand_forecast.train.evaluate`
returns a :class:`BacktestReport` and fits a model **per fold**, each thrown
away when the fold ends — an honest evaluation that leaves nothing to serve.
`MODEL_PATH` in the deployment manifests pointed at a file no code had ever
written, which ADR-008 records along with the rest of that gap.

A backtest answers "would this have worked". A persisted model answers "what
do we predict now", and the two are fit on different data: the backtest never
trains on the most recent window, because it must hold it out. The final model
must, because that window is the freshest thing it knows.

What is written is not a bare regressor. A point forecast without its interval
is a number with no admission of uncertainty, and the interval only means
anything with the calibration that produced it — so the estimator, the
conformal calibration, the exact feature columns and the training window travel
together as one artifact. A frame that cannot supply one of those features is
refused by name, which is the only check worth making here: polars selects by
name, so the caller's column ORDER is not a contract and pretending it is
produces a false one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import polars as pl
from ml_core.conformal import SplitConformalRegressor
from ml_core.determinism import seed_everything
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor

from demand_forecast.features import FEATURE_COLUMNS, build_features
from demand_forecast.train import ALPHA, CALIBRATION_HOURS, select_modellable_zones

#: Bumped when the artifact's SHAPE changes — a field added, a field's meaning
#: changed. Loading an artifact from a different schema fails rather than
#: unpickling into a dataclass whose fields no longer mean what they did.
ARTIFACT_SCHEMA = 1


@dataclass(frozen=True)
class ForecastModel:
    """A regressor, its conformal calibration, and what it was fit on.

    Attributes:
        estimator: Fit on every row up to ``calibrated_from``.
        conformal: Calibrated on the held-out tail, which the estimator never saw.
        feature_columns: The names the estimator was fit on, in its order.
            A frame is selected by these names, never by position.
        trained_through: Latest ``event_time`` in the training data. What makes
            a forecast stale is this timestamp, not the file's mtime.
        calibrated_from: First ``event_time`` in the calibration tail.
        n_train_rows: Rows the estimator saw.
        zones: Series the model covers. A zone absent here has no model, and
            asking for one must fail rather than extrapolate from other zones.
        alpha: ``1 - alpha`` is the nominal interval coverage.
        seed: Reproduces the fit.
        schema: :data:`ARTIFACT_SCHEMA` at write time.
    """

    estimator: HistGradientBoostingRegressor
    conformal: SplitConformalRegressor
    feature_columns: tuple[str, ...]
    trained_through: str
    calibrated_from: str
    n_train_rows: int
    zones: tuple[int, ...]
    alpha: float
    seed: int
    schema: int = ARTIFACT_SCHEMA

    def predict(self, featured: pl.DataFrame) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
        """Point forecast with its lower and upper bound.

        Args:
            featured: Output of :func:`demand_forecast.features.build_features`.

        Returns:
            ``(point, lower, upper)``, aligned with ``featured``'s rows.

        Raises:
            ValueError: If the frame does not carry every feature the estimator
                was fit on.
        """
        missing = [column for column in self.feature_columns if column not in featured.columns]
        if missing:
            raise ValueError(
                f"feature contract violated: model expects {list(self.feature_columns)}, frame is missing {missing}"
            )

        # Selected BY NAME, in the model's order. The frame's own column order
        # is not part of the contract and must not be: `build_features` emits
        # `roll_mean_24, roll_std_24, roll_mean_168` while `FEATURE_COLUMNS`
        # groups the means before the deviations, and both are correct. What
        # would be a silent off-by-one column is passing a bare matrix, which
        # this signature does not accept.
        matrix = featured.select(list(self.feature_columns)).to_numpy().astype(np.float64)
        point: NDArray[np.float64] = self.estimator.predict(matrix)
        lower, upper = self.conformal.interval(point)
        return point, lower, upper


def fit_final(
    demand: pl.DataFrame,
    *,
    seed: int = 42,
    calibration_hours: int = CALIBRATION_HOURS,
    alpha: float = ALPHA,
) -> ForecastModel:
    """Fit on all available history, calibrating on its most recent tail.

    The calibration split is by **time**, not by row position. Splitting a
    panel positionally selected whole zones instead of a recent window and
    reported 53.8% coverage against a nominal 90% — the same defect this
    repository already paid for once in the backtest.

    Args:
        demand: Hourly demand from :func:`demand_forecast.ingest.to_hourly_demand`.
        seed: Reproduces the fit.
        calibration_hours: Length of the held-out tail, in hours.
        alpha: ``1 - alpha`` is the nominal coverage.

    Returns:
        A :class:`ForecastModel`.

    Raises:
        ValueError: If no zone has enough history, or if the tail leaves too
            few rows on either side to fit or to calibrate.
    """
    seed_everything(seed)

    modellable = select_modellable_zones(demand)
    if modellable.is_empty():
        raise ValueError("no zone has enough history to be modelled")

    featured = build_features(modellable)
    times = featured["event_time"].to_numpy().astype("datetime64[h]")
    cutoff = times.max() - np.timedelta64(calibration_hours, "h")

    fit_rows = np.flatnonzero(times <= cutoff)
    calibrate_rows = np.flatnonzero(times > cutoff)
    if len(fit_rows) < 2 or len(calibrate_rows) < 2:
        raise ValueError(
            f"a {calibration_hours}h calibration tail splits {len(featured)} rows into "
            f"{len(fit_rows)} fit and {len(calibrate_rows)} calibration; the history is too short"
        )

    matrix = featured.select(FEATURE_COLUMNS).to_numpy().astype(np.float64)
    target = featured["trip_count"].to_numpy().astype(np.float64)

    estimator = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=seed)
    estimator.fit(matrix[fit_rows], target[fit_rows])

    conformal = SplitConformalRegressor(alpha=alpha)
    conformal.calibrate(target[calibrate_rows], estimator.predict(matrix[calibrate_rows]))

    return ForecastModel(
        estimator=estimator,
        conformal=conformal,
        feature_columns=tuple(FEATURE_COLUMNS),
        trained_through=str(times[fit_rows].max()),
        calibrated_from=str(times[calibrate_rows].min()),
        n_train_rows=len(fit_rows),
        zones=tuple(sorted(int(zone) for zone in featured["zone_id"].unique().to_list())),
        alpha=alpha,
        seed=seed,
    )


def save(model: ForecastModel, path: Path) -> dict[str, Any]:
    """Write the artifact and a readable metadata sidecar.

    The sidecar is not decoration. Everything an operator needs to answer "what
    is deployed and is it stale" — the training window, the zones, the version —
    is otherwise only readable by unpickling the model, which requires this
    package installed and is not something a runbook step can do.

    Args:
        model: From :func:`fit_final`.
        path: Destination for the joblib artifact. The sidecar is written
            beside it with a ``.json`` suffix.

    Returns:
        The metadata written, including ``version``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)

    # Version derived from the artifact's BYTES. A hand-set version string is
    # one edit away from labelling two different models the same, and the first
    # symptom is a rollback that changes nothing.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    metadata = {
        "version": f"{model.trained_through}+{digest}",
        "schema": model.schema,
        "trained_through": model.trained_through,
        "calibrated_from": model.calibrated_from,
        "n_train_rows": model.n_train_rows,
        "n_zones": len(model.zones),
        "nominal_coverage": 1.0 - model.alpha,
        "feature_columns": list(model.feature_columns),
        "seed": model.seed,
    }
    path.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def load(path: Path) -> ForecastModel:
    """Read an artifact back, refusing one written by a different schema.

    Args:
        path: The joblib artifact written by :func:`save`.

    Returns:
        The :class:`ForecastModel`.

    Raises:
        ValueError: If the artifact is not a :class:`ForecastModel`, or its
            schema is not :data:`ARTIFACT_SCHEMA`.
    """
    model = joblib.load(path)
    if not isinstance(model, ForecastModel):
        raise ValueError(f"{path} holds {type(model).__name__}, not a ForecastModel")
    if model.schema != ARTIFACT_SCHEMA:
        raise ValueError(
            f"{path} was written with artifact schema {model.schema}, this code reads {ARTIFACT_SCHEMA}. "
            "Re-fit rather than reading it: the fields do not mean the same thing."
        )
    return model
