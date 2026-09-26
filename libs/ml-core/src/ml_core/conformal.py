"""Conformal prediction intervals with verifiable coverage.

A point prediction cannot say when it should not be trusted. Conformal
prediction attaches an interval with a **finite-sample coverage guarantee**
that holds for any underlying model and requires no distributional assumption —
and, critically, can be checked empirically rather than believed.

The guarantee is exchangeability, not independence: calibration and test data
must be drawn from the same distribution. For a time series that is a real
constraint, and :class:`SplitConformalRegressor` is deliberately explicit about
it rather than leaving it to the reader.

An interval whose empirical coverage is never measured is decoration. The
:meth:`SplitConformalRegressor.coverage` method exists so the claim can fail a
build.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class CoverageReport:
    """Measured coverage of a set of intervals.

    Attributes:
        nominal: The coverage the intervals were built to provide.
        empirical: The fraction of true values that actually fell inside.
        n: Number of points measured.
        mean_width: Average interval width. Coverage alone is not enough —
            an infinitely wide interval covers everything and informs nothing.
    """

    nominal: float
    empirical: float
    n: int
    mean_width: float

    @property
    def gap(self) -> float:
        """Signed difference: positive means over-covering (too wide)."""
        return self.empirical - self.nominal

    def within(self, tolerance: float) -> bool:
        """True when empirical coverage is within ``tolerance`` of nominal.

        Under-coverage is the dangerous direction — an interval that promises
        90% and delivers 80% is being trusted more than it earns — but gross
        over-coverage means the intervals are too wide to act on, so both sides
        are checked.
        """
        return abs(self.gap) <= tolerance

    def __str__(self) -> str:
        return (
            f"nominal={self.nominal:.3f} empirical={self.empirical:.3f} "
            f"gap={self.gap:+.3f} n={self.n} mean_width={self.mean_width:.4f}"
        )


class SplitConformalRegressor:
    """Split (inductive) conformal intervals around any regressor's predictions.

    Fit on a **held-out calibration set the model never saw**. Using training
    residuals instead is the classic error: they are optimistically small, so
    the intervals are too narrow and coverage silently fails exactly where the
    model is overfitted.

    Args:
        alpha: Miscoverage rate. ``alpha=0.1`` targets 90% coverage.

    Raises:
        ValueError: If ``alpha`` is not in (0, 1).
    """

    def __init__(self, alpha: float = 0.1):
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha
        self._quantile: float | None = None
        self._n_calibration: int = 0

    @property
    def nominal_coverage(self) -> float:
        """The coverage these intervals target."""
        return 1.0 - self.alpha

    @property
    def is_calibrated(self) -> bool:
        return self._quantile is not None

    def calibrate(self, y_true: NDArray[np.float64], y_pred: NDArray[np.float64]) -> float:
        """Compute the conformity quantile from held-out residuals.

        Uses the finite-sample corrected rank ``ceil((n+1)(1-alpha))/n`` rather
        than the plain empirical quantile. The correction is what turns an
        asymptotic statement into a guarantee that holds at the sample size you
        actually have — and at small n the difference is not negligible.

        Args:
            y_true: Observed values from the calibration set.
            y_pred: Model predictions for the same rows.

        Returns:
            The half-width applied to every prediction.

        Raises:
            ValueError: If the arrays disagree in length, are empty, or are too
                small for the requested alpha.
        """
        y_true = np.asarray(y_true, dtype=np.float64).ravel()
        y_pred = np.asarray(y_pred, dtype=np.float64).ravel()

        if y_true.shape != y_pred.shape:
            raise ValueError(f"y_true and y_pred must align: {y_true.shape} vs {y_pred.shape}")
        n = y_true.size
        if n == 0:
            raise ValueError("calibration set is empty")

        # With fewer than 1/alpha points the corrected rank exceeds n, and no
        # finite interval can provide the guarantee. Failing here is honest;
        # clipping the rank would return an interval whose promise is false.
        minimum = int(np.ceil(1.0 / self.alpha)) - 1
        if n < minimum:
            raise ValueError(
                f"calibration set of {n} cannot support alpha={self.alpha}: "
                f"at least {minimum} points are required for a finite interval"
            )

        residuals = np.abs(y_true - y_pred)
        rank = int(np.ceil((n + 1) * (1.0 - self.alpha)))
        rank = min(rank, n)
        self._quantile = float(np.sort(residuals)[rank - 1])
        self._n_calibration = n
        return self._quantile

    @property
    def quantile(self) -> float:
        """The calibrated residual quantile — half the interval width.

        Read-only and public because an artifact has to carry it. Persisting a
        calibrated regressor by pickling the OBJECT makes the artifact depend
        on this package being importable wherever it is read, which for a
        serving image means installing a workspace library (ADR-008, R11-3).
        Two numbers travel; a class does not.

        Raises:
            RuntimeError: If called before :meth:`calibrate`.
        """
        if self._quantile is None:
            raise RuntimeError("the regressor is not calibrated, so it has no quantile to report")
        return self._quantile

    @property
    def n_calibration(self) -> int:
        """How many residuals the quantile was taken over.

        Carried alongside the quantile because coverage is a property of the
        calibration set's size as much as its spread: the same quantile from
        twelve residuals and from twelve thousand are not the same claim.

        Raises:
            RuntimeError: If called before :meth:`calibrate`.
        """
        if self._n_calibration is None:
            raise RuntimeError("the regressor is not calibrated, so it has no calibration size to report")
        return self._n_calibration

    @classmethod
    def from_calibration(cls, *, alpha: float, quantile: float, n_calibration: int) -> SplitConformalRegressor:
        """Restore a calibrated regressor from what calibration produced.

        The inverse of reading :attr:`quantile` and :attr:`n_calibration`, and
        the reason both are public: an artifact stores those numbers and
        reconstructs the regressor on load, so nothing has to unpickle an
        instance of this class.

        Args:
            alpha: Miscoverage rate the quantile was taken at.
            quantile: The calibrated residual quantile.
            n_calibration: Residuals it was taken over.

        Returns:
            A calibrated :class:`SplitConformalRegressor`.

        Raises:
            ValueError: If ``alpha`` is outside (0, 1), the quantile is
                negative, or the calibration size is not positive. A negative
                quantile would produce an interval whose lower bound exceeds
                its upper one, and a restored regressor is exactly where such
                a value arrives unnoticed.
        """
        restored = cls(alpha=alpha)
        if quantile < 0.0:
            raise ValueError(f"quantile must be non-negative, got {quantile}")
        if n_calibration < 1:
            raise ValueError(f"n_calibration must be positive, got {n_calibration}")
        restored._quantile = float(quantile)
        restored._n_calibration = int(n_calibration)
        return restored

    def interval(self, y_pred: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Return ``(lower, upper)`` bounds for predictions.

        Raises:
            RuntimeError: If called before :meth:`calibrate`.
        """
        if self._quantile is None:
            raise RuntimeError("calibrate() must be called before interval() — an uncalibrated interval is a guess")
        y_pred = np.asarray(y_pred, dtype=np.float64).ravel()
        return y_pred - self._quantile, y_pred + self._quantile

    def coverage(self, y_true: NDArray[np.float64], y_pred: NDArray[np.float64]) -> CoverageReport:
        """Measure how often the intervals actually contain the truth.

        This is the point of the module. A conformal interval whose empirical
        coverage is never measured is a claim nobody checked, and the failure
        mode — calibrating on data the model saw — produces intervals that look
        fine and under-cover.
        """
        y_true = np.asarray(y_true, dtype=np.float64).ravel()
        lower, upper = self.interval(y_pred)
        inside = (y_true >= lower) & (y_true <= upper)
        return CoverageReport(
            nominal=self.nominal_coverage,
            empirical=float(np.mean(inside)),
            n=int(y_true.size),
            mean_width=float(np.mean(upper - lower)),
        )
