"""Measure where the single-node path stops being sufficient.

ADR-004 places DuckDB/Polars at Core for the incremental path and Spark at
Demonstrated for the historical backfill, and requires the **threshold to be
measured**, not assumed. The interesting artifact of that decision is not
"we used Spark" — it is the number at which one stops working and the other
starts earning its operating cost.

This measures the single-node side honestly and states plainly what it cannot
measure. Running Spark on a 4 GB workstation to produce a comparison number
would produce a number about the workstation, not about Spark — which is
precisely the class of measurement this repository has already been burned by
(a benchmark run under partial GPU offload, then cited as proof a model did not
fit).

So: the DuckDB/Polars side is measured on real data at increasing scale. The
Spark side is declared UNMEASURED until a cloud window, and the extrapolation
carries its assumptions in the output rather than in someone's head.
"""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScalePoint:
    """One measured point on the single-node scaling curve.

    ``working_mb`` is the memory the WORKLOAD used, excluding the interpreter
    and loaded libraries. Measuring total resident size instead produced a
    projection that contradicted itself — a limit of 2M rows immediately after
    processing 2.96M — because the baseline dominated the smallest slice.
    """

    rows: int
    seconds: float
    working_mb: float

    @property
    def rows_per_second(self) -> float:
        return self.rows / self.seconds if self.seconds else 0.0


@dataclass(frozen=True)
class CrossoverEstimate:
    """Where the single-node path is projected to stop being viable.

    Attributes:
        points: The measured curve.
        memory_budget_mb: The ceiling the projection is against.
        projected_row_limit: Rows at which the projection reaches the budget.
        assumptions: Stated in the object, not implied. A projection whose
            assumptions live only in the author's head cannot be disputed, and
            an undisputable number is not evidence.
    """

    points: tuple[ScalePoint, ...]
    memory_budget_mb: float
    projected_row_limit: int
    assumptions: tuple[str, ...]

    def __str__(self) -> str:
        lines = [
            "Single-node scaling (DuckDB/Polars), measured on real NYC TLC data:",
            f"  {'rows':>12}  {'seconds':>8}  {'rows/s':>12}  {'working MB':>10}",
        ]
        lines += [
            f"  {p.rows:>12,}  {p.seconds:>8.2f}  {p.rows_per_second:>12,.0f}  {p.working_mb:>8.1f}"
            for p in self.points
        ]
        lines += [
            "",
            f"Projected single-node limit: ~{self.projected_row_limit:,} rows "
            f"against a {self.memory_budget_mb:.0f} MB budget.",
            "",
            "Assumptions (dispute these, not the number):",
        ]
        lines += [f"  - {assumption}" for assumption in self.assumptions]
        lines += [
            "",
            "NOT MEASURED: the Spark side. A Spark benchmark on this workstation would",
            "measure the workstation, not Spark. The comparison completes in a cloud",
            "window, and until then the crossover is a PROJECTION, not a finding.",
        ]
        return "\n".join(lines)


def _resident_mb() -> float:
    """CURRENT process resident size in MB, from /proc.

    Deliberately VmRSS and not VmHWM. VmHWM is the peak ever reached and is
    monotonic, so successive measurements in one process each inherit every
    earlier peak — every point after the first measures the largest point
    before it.
    """
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def measure(
    source: Path, fractions: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0), memory_budget_mb: float = 512.0
) -> CrossoverEstimate:
    """Time the aggregation at increasing fractions of a real file.

    Args:
        source: A real TLC parquet file. Synthetic data would measure the
            generator's distribution, not the workload's.
        fractions: Fractions of the file to process.
        memory_budget_mb: The ceiling to project against. Defaults to the
            workload slice of the local stack budget.

    Returns:
        A :class:`CrossoverEstimate` carrying its own assumptions.
    """
    from demand_forecast.ingest import clean, read_trips, to_hourly_demand

    full = read_trips(source).collect()
    points: list[ScalePoint] = []

    for fraction in fractions:
        rows = int(full.height * fraction)
        slice_ = full.head(rows)

        # Settle allocations and take the baseline immediately before the
        # operation, so what is measured is the WORKLOAD rather than the
        # process that hosts it.
        gc.collect()
        baseline = _resident_mb()

        start = time.perf_counter()
        result = to_hourly_demand(clean(slice_))
        elapsed = time.perf_counter() - start

        working = max(_resident_mb() - baseline, 0.0)
        del result
        points.append(ScalePoint(rows=rows, seconds=elapsed, working_mb=working))

    # Project linearly from the LARGEST measured point, whose baseline noise is
    # proportionally smallest — a projection anchored on a small slice measures
    # noise rather than the workload.
    #
    # Linear is the honest choice and is stated as an assumption: the
    # aggregation is a group-by whose memory grows with distinct keys rather
    # than rows, so the true curve is flatter and this projection is
    # CONSERVATIVE. Erring optimistic would be worse than not projecting at
    # all, because it would delay adopting Spark past the point it was needed.
    largest = points[-1]
    mb_per_row = largest.working_mb / largest.rows if largest.rows else 0.0
    projected = int(memory_budget_mb / mb_per_row) if mb_per_row > 0 else 0

    return CrossoverEstimate(
        points=tuple(points),
        memory_budget_mb=memory_budget_mb,
        projected_row_limit=projected,
        assumptions=(
            "Memory scales linearly with rows. The group-by's memory actually grows with "
            "DISTINCT KEYS, so the real curve is flatter and this projection is conservative.",
            "Working memory is measured as the RSS delta around the operation, which "
            "excludes the interpreter but includes allocator slack.",
            "One month of TLC data is ~3M rows; the full history is ~2 orders of magnitude "
            "larger, which is where the Spark question actually arises.",
            "Measured on a single machine with a fixed memory budget; a larger machine moves "
            "this number without changing the shape.",
        ),
    )


def main() -> int:
    """Print the measurement. Wired into the project's Makefile target."""
    source = Path("data/nyc-tlc/yellow_tripdata_2024-01.parquet")
    if not source.is_file():
        print(f"missing {source} — run: python scripts/datasets/fetch.py nyc-tlc")
        return 1
    print(measure(source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
