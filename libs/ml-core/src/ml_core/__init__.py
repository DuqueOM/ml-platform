"""Determinism, evaluation, calibration, model persistence and metric contracts.

Business-agnostic by construction: nothing here may know a feature name, a
dataset or a project. That constraint is what makes it reusable, and it is
enforced by ``tests/test_dependency_direction.py`` rather than by review.
"""

__version__ = "0.1.0"
