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
        # Checked through `is_calibrated`, not `_n_calibration is None`: the
        # constructor initialises the count to 0, so the None check never
        # fired and an uncalibrated regressor reported a calibration size of
        # 0 instead of refusing. Found by the test for this branch, which the
        # change that added the property did not have.
        if not self.is_calibrated:
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


class MondrianConformalRegressor:
    """Group-conditional (Mondrian) split conformal: one calibrated quantile per group.

    :class:`SplitConformalRegressor` guarantees coverage on AVERAGE over every
    point it is applied to, and nothing about any subset of them. Over
    heterogeneous groups — busy and quiet series, large and small accounts —
    one global residual quantile is too wide for the groups whose residuals
    are small and too narrow for those whose residuals are large, while the
    aggregate lands on target. Measured on this repository's first consumer,
    one quantile over 255 zones covered 100% of the quietest zones' hours and
    37.7% of the busiest decile's, against 90% nominal and a marginal 89.6%.

    Calibrating each group on its own residuals (Vovk et al., *Algorithmic
    Learning in a Random World*, the Mondrian taxonomy) gives the
    finite-sample guarantee WITHIN every group, under exchangeability within
    the group. Which taxonomy to use is the caller's decision; it must be
    fixed before the calibration labels are seen, or the guarantee is gone.

    Args:
        alpha: Miscoverage rate, the same in every group.

    Raises:
        ValueError: If ``alpha`` is not in (0, 1).
    """

    def __init__(self, alpha: float = 0.1):
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha
        self._groups: dict[int, SplitConformalRegressor] = {}

    @property
    def nominal_coverage(self) -> float:
        return 1.0 - self.alpha

    @property
    def is_calibrated(self) -> bool:
        return bool(self._groups)

    def calibrate(
        self, y_true: NDArray[np.float64], y_pred: NDArray[np.float64], groups: NDArray[np.int_]
    ) -> dict[int, float]:
        """Calibrate one quantile per group from held-out residuals.

        Every group must be large enough on its own: a group too small for
        ``alpha`` is refused by :meth:`SplitConformalRegressor.calibrate`, named,
        rather than merged into another, because a merged group's guarantee is
        the merged group's, not its own.

        Returns:
            ``{group: quantile}``.

        Raises:
            ValueError: If the arrays disagree in length, are empty, or a group
                is too small for ``alpha``.
        """
        y_true = np.asarray(y_true, dtype=np.float64).ravel()
        y_pred = np.asarray(y_pred, dtype=np.float64).ravel()
        groups = np.asarray(groups).ravel()
        if not y_true.shape == y_pred.shape == groups.shape:
            raise ValueError(f"y_true, y_pred and groups must align: {y_true.shape}, {y_pred.shape}, {groups.shape}")
        if y_true.size == 0:
            raise ValueError("calibration set is empty")
        calibrated: dict[int, SplitConformalRegressor] = {}
        for group in np.unique(groups):
            rows = groups == group
            regressor = SplitConformalRegressor(alpha=self.alpha)
            try:
                regressor.calibrate(y_true[rows], y_pred[rows])
            except ValueError as error:
                raise ValueError(f"group {int(group)}: {error}") from error
            calibrated[int(group)] = regressor
        self._groups = calibrated
        return self.quantiles

    @property
    def quantiles(self) -> dict[int, float]:
        """``{group: quantile}`` — what an artifact carries, as plain numbers."""
        if not self._groups:
            raise RuntimeError("the regressor is not calibrated, so it has no quantiles to report")
        return {group: regressor.quantile for group, regressor in sorted(self._groups.items())}

    @property
    def n_calibration(self) -> dict[int, int]:
        """``{group: residuals}``: a quantile's claim depends on how many it was taken over."""
        if not self._groups:
            raise RuntimeError("the regressor is not calibrated, so it has no calibration sizes to report")
        return {group: regressor.n_calibration for group, regressor in sorted(self._groups.items())}

    @classmethod
    def from_calibration(
        cls, *, alpha: float, quantiles: dict[int, float], n_calibration: dict[int, int]
    ) -> MondrianConformalRegressor:
        """Restore from what calibration produced — the inverse of :attr:`quantiles` and :attr:`n_calibration`.

        Raises:
            ValueError: If the two maps name different groups, or any group's
                values are invalid (see :meth:`SplitConformalRegressor.from_calibration`).
        """
        if set(quantiles) != set(n_calibration):
            raise ValueError(
                f"quantiles and n_calibration name different groups: {sorted(quantiles)} vs {sorted(n_calibration)}"
            )
        if not quantiles:
            raise ValueError("no group to restore")
        restored = cls(alpha=alpha)
        restored._groups = {
            int(group): SplitConformalRegressor.from_calibration(
                alpha=alpha, quantile=quantiles[group], n_calibration=n_calibration[group]
            )
            for group in quantiles
        }
        return restored

    def interval(
        self, y_pred: NDArray[np.float64], groups: NDArray[np.int_]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """``(lower, upper)``, each prediction widened by its own group's quantile.

        Raises:
            RuntimeError: If called before :meth:`calibrate`.
            ValueError: If a prediction's group was never calibrated. It has no
                guarantee, and borrowing another group's quantile would give it
                one it has not earned.
        """
        if not self._groups:
            raise RuntimeError("calibrate() must be called before interval() — an uncalibrated interval is a guess")
        y_pred = np.asarray(y_pred, dtype=np.float64).ravel()
        groups = np.asarray(groups).ravel()
        if y_pred.shape != groups.shape:
            raise ValueError(f"y_pred and groups must align: {y_pred.shape} vs {groups.shape}")
        unknown = sorted(set(np.unique(groups).tolist()) - set(self._groups))
        if unknown:
            raise ValueError(f"groups {unknown} were never calibrated, so their intervals carry no guarantee")
        half_width = np.array([self._groups[int(group)].quantile for group in groups], dtype=np.float64)
        return y_pred - half_width, y_pred + half_width

    def coverage(
        self, y_true: NDArray[np.float64], y_pred: NDArray[np.float64], groups: NDArray[np.int_]
    ) -> dict[int, CoverageReport]:
        """Measured coverage per group — the claim this class exists to make, checked."""
        y_true = np.asarray(y_true, dtype=np.float64).ravel()
        groups = np.asarray(groups).ravel()
        lower, upper = self.interval(y_pred, groups)
        inside = (y_true >= lower) & (y_true <= upper)
        return {
            int(group): CoverageReport(
                nominal=self.nominal_coverage,
                empirical=float(np.mean(inside[groups == group])),
                n=int((groups == group).sum()),
                mean_width=float(np.mean((upper - lower)[groups == group])),
            )
            for group in np.unique(groups)
        }
