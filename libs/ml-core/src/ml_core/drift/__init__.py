"""The drift contract — see :mod:`ml_core.drift.contract` for the definitions.

Split out of this file rather than left in it. `check_implementation_status.py`
treats a package holding only `__init__.py` as a placeholder — "counting it as
implementation is how a skeleton comes to look finished" — and it is right to:
that heuristic is why an empty scaffold cannot report as built. A 380-line
contract living entirely in `__init__.py` is the exception that made the
heuristic wrong, so the package took the conventional shape instead of the
generator taking an exception for it.
"""

from ml_core.drift.contract import (
    Action,
    Direction,
    DriftResponse,
    DriftSignal,
    ReferenceWindow,
    Verdict,
    worst_action,
)

__all__ = [
    "Action",
    "Direction",
    "DriftResponse",
    "DriftSignal",
    "ReferenceWindow",
    "Verdict",
    "worst_action",
]
