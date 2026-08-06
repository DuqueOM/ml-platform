"""Reproducibility that reports what it reached.

The failure this guards: a seeding helper that silently skips an uninstalled
library produces runs differing for reasons nobody can reconstruct, and the
difference surfaces weeks later as an unexplained metric change.
"""

from __future__ import annotations

import random

import numpy as np
import pytest
from ml_core.determinism import seed_everything, stable_hash


def test_the_same_seed_reproduces_the_same_draws() -> None:
    """The baseline claim. Without it nothing else here matters."""
    seed_everything(42)
    first = (random.random(), np.random.rand(3).tolist())
    seed_everything(42)
    assert (random.random(), np.random.rand(3).tolist()) == first


def test_different_seeds_diverge() -> None:
    """Guards the reverse error: a helper that ignores its argument.

    Failure looks like: every run identical regardless of seed, so an
    experiment that varies the seed varies nothing.
    """
    seed_everything(1)
    first = np.random.rand(5).tolist()
    seed_everything(2)
    assert np.random.rand(5).tolist() != first


def test_the_report_names_what_was_seeded() -> None:
    """ "Deterministic" means something different depending on what was reached."""
    report = seed_everything(7)
    assert "python" in report.seeded
    assert "numpy" in report.seeded
    assert report.seed == 7


def test_absent_frameworks_are_reported_not_hidden() -> None:
    """An unseeded source must appear somewhere, not vanish.

    torch and tensorflow are optional here; whichever is missing must be listed
    as unavailable so a later reader knows the guarantee's actual scope.
    """
    report = seed_everything(7)
    assert set(report.seeded) & {"python", "numpy"}
    assert all(source not in report.seeded for source in report.unavailable)


def test_str_surfaces_unavailable_sources() -> None:
    report = seed_everything(7)
    if report.unavailable:
        assert "unavailable" in str(report)
    assert "seed=7" in str(report)


def test_warn_on_missing_emits_a_warning_when_something_is_absent() -> None:
    report = seed_everything(7)
    if not report.unavailable:
        pytest.skip("every optional framework is installed here")
    with pytest.warns(RuntimeWarning, match="could not seed"):
        seed_everything(7, warn_on_missing=True)


@pytest.mark.parametrize("seed", [-1, 2**32, 2**40])
def test_out_of_range_seeds_are_refused(seed: int) -> None:
    """Libraries truncate large seeds INCONSISTENTLY.

    Failure looks like: one library seeding on the low 32 bits and another on
    the full value, so a single "seed" produces two different streams.
    """
    with pytest.raises(ValueError, match="seed must be"):
        seed_everything(seed)


def test_stable_hash_is_identical_across_processes() -> None:
    """hash() is per-process randomised; a data split cannot use it.

    Failure looks like: a train/test split that reshuffles between runs, so a
    "held-out" set silently contains rows the model trained on earlier.
    """
    import subprocess
    import sys

    expected = stable_hash("zone", 42)
    result = subprocess.run(
        [sys.executable, "-c", "from ml_core.determinism import stable_hash; print(stable_hash('zone', 42))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert int(result.stdout.strip()) == expected


def test_stable_hash_distinguishes_types() -> None:
    """1 and "1" must not collide, or two different entities share a bucket."""
    assert stable_hash(1) != stable_hash("1")
    assert stable_hash("a", "b") != stable_hash("ab")
