"""Point-in-time correct feature retrieval.

The correctness property that separates a training pipeline from a demo: each
feature takes the value it had AT the labelled event, never a later one.

    from feature_defs import as_of_join, detect_leakage

``naive_join`` is exported deliberately — it is the mistake everyone writes
first, kept so the leakage detector can be shown to catch something real. Never
call it from a pipeline.
"""

from feature_defs.point_in_time import LeakageReport, as_of_join, detect_leakage, naive_join

__version__ = "0.1.0"

__all__ = ["LeakageReport", "as_of_join", "detect_leakage", "naive_join"]
