"""Deterministic execution.

Reproducibility claims are cheap to make and expensive to verify later. This
module makes the claim checkable: one call seeds every source of randomness the
platform actually uses, and reports which ones it could not reach.

The reporting matters. A seeding helper that silently skips a library nobody
installed produces runs that differ for reasons no one can reconstruct — and
the difference surfaces as an unexplained metric change three weeks later.
"""

from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SeedReport:
    """What was actually seeded, and what was not.

    Attributes:
        seed: The seed applied.
        seeded: Sources successfully seeded.
        unavailable: Known sources absent from this environment. Not an error —
            but recorded, because "deterministic" means something different
            depending on which of these was present.
    """

    seed: int
    seeded: tuple[str, ...]
    unavailable: tuple[str, ...]

    def __str__(self) -> str:
        parts = [f"seed={self.seed}", f"seeded={list(self.seeded)}"]
        if self.unavailable:
            parts.append(f"unavailable={list(self.unavailable)}")
        return " ".join(parts)


def seed_everything(seed: int, *, warn_on_missing: bool = False) -> SeedReport:
    """Seed every random source this platform uses.

    Args:
        seed: The seed. Must be non-negative and fit in 32 bits, because that
            is the range every downstream library accepts — a seed that some
            libraries truncate is one that produces different runs per library.
        warn_on_missing: Emit a warning for each unavailable source.

    Returns:
        A :class:`SeedReport` naming what was seeded and what was absent.

    Raises:
        ValueError: If the seed is outside the range every source accepts.
    """
    if not 0 <= seed < 2**32:
        raise ValueError(f"seed must be in [0, 2**32), got {seed} — larger values are truncated inconsistently")

    seeded: list[str] = []
    unavailable: list[str] = []

    # PYTHONHASHSEED only takes effect at interpreter start. Setting it here
    # affects CHILD processes, not this one — recorded as such rather than
    # claimed as a seeded source, because claiming it would be false for the
    # current process.
    os.environ["PYTHONHASHSEED"] = str(seed)
    seeded.append("pythonhashseed(children)")

    random.seed(seed)
    seeded.append("python")

    np.random.seed(seed)
    seeded.append("numpy")

    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
            seeded.append("torch.cuda")
        seeded.append("torch")
    except ImportError:
        unavailable.append("torch")

    try:
        import tensorflow as tf

        tf.random.set_seed(seed)
        seeded.append("tensorflow")
    except ImportError:
        unavailable.append("tensorflow")

    if warn_on_missing and unavailable:
        import warnings

        warnings.warn(
            f"seed_everything could not seed: {unavailable}. "
            "Runs are deterministic only with respect to the sources listed as seeded.",
            RuntimeWarning,
            stacklevel=2,
        )

    return SeedReport(seed=seed, seeded=tuple(seeded), unavailable=tuple(unavailable))


def stable_hash(*parts: object) -> int:
    """A hash that is stable across processes and Python versions.

    ``hash()`` is randomised per process unless ``PYTHONHASHSEED`` is fixed at
    interpreter start, which cannot be guaranteed for an already-running
    process. Anything that must partition data reproducibly — a train/test
    split, a shard assignment, an A/B bucket — needs this instead.

    Args:
        *parts: Values to hash. Converted via ``repr`` so that ``1`` and
            ``"1"`` do not collide.

    Returns:
        A non-negative 64-bit integer, identical for identical inputs in any
        process.
    """
    digest = hashlib.sha256("\x1f".join(repr(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")
