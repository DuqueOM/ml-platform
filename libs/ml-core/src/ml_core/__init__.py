"""Determinism, uncertainty, calibration and cost-based decisions.

Business-agnostic by construction: nothing here may know a feature name, a
dataset or a project. That constraint is what makes it reusable, and it is
enforced by ``tests/test_dependency_direction.py`` rather than by review.

    from ml_core import (
        seed_everything,          # reproducibility that reports what it reached
        SplitConformalRegressor,  # intervals whose coverage can be measured
        ErrorCosts, choose_threshold,  # thresholds in business units, not F1
        calibration_error,        # the precondition cost-based thresholds need
    )
"""

from ml_core.conformal import CoverageReport, SplitConformalRegressor
from ml_core.decision import ErrorCosts, ThresholdChoice, calibration_error, choose_threshold, expected_cost
from ml_core.determinism import SeedReport, seed_everything, stable_hash

__version__ = "0.1.0"

__all__ = [
    "CoverageReport",
    "ErrorCosts",
    "SeedReport",
    "SplitConformalRegressor",
    "ThresholdChoice",
    "calibration_error",
    "choose_threshold",
    "expected_cost",
    "seed_everything",
    "stable_hash",
]
