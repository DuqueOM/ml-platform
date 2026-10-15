"""The single-node crossover projection is arithmetic over measured points, and states its assumptions.

ADR-004 requires the DuckDB/Polars-to-Spark threshold to be measured. Nothing
tested the module that measures it (W-15: 0% of 59 statements), so a change
to the projection — anchoring it on the smallest slice, which measures noise,
or letting a negative memory delta through — would have printed a confident
wrong number. The memory reader is made deterministic here; the parsing, the
slicing and the projection run for real on a small TLC-shaped file.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from demand_forecast import crossover
from demand_forecast.crossover import CrossoverEstimate, ScalePoint


def _tlc_file(path: Path, rows: int) -> Path:
    """A conforming TLC month with ``rows`` trips across one day's hours."""
    start = datetime(2024, 1, 10, 0, 0, 0)
    pl.DataFrame(
        {
            "tpep_pickup_datetime": [start + timedelta(minutes=7 * i) for i in range(rows)],
            "tpep_dropoff_datetime": [start + timedelta(minutes=7 * i + 12) for i in range(rows)],
            "PULocationID": [100 + i % 5 for i in range(rows)],
            "DOLocationID": [200] * rows,
            "trip_distance": [3.5] * rows,
            "fare_amount": [18.0] * rows,
            "passenger_count": [1] * rows,
            "total_amount": [22.5] * rows,
        }
    ).cast(
        {
            "tpep_pickup_datetime": pl.Datetime("ns"),
            "tpep_dropoff_datetime": pl.Datetime("ns"),
            "PULocationID": pl.Int32,
            "DOLocationID": pl.Int32,
        }
    ).write_parquet(path)
    return path


def _resident(monkeypatch: pytest.MonkeyPatch, readings: list[float]) -> None:
    """Make the RSS reader return ``readings`` in order: baseline, after, baseline, after, …"""
    values = iter(readings)
    monkeypatch.setattr(crossover, "_resident_mb", lambda: next(values))


def test_throughput_is_rows_over_seconds_and_zero_without_time() -> None:
    assert ScalePoint(rows=1_000, seconds=2.0, working_mb=1.0).rows_per_second == 500.0
    assert ScalePoint(rows=1_000, seconds=0.0, working_mb=1.0).rows_per_second == 0.0


def test_the_projection_is_anchored_on_the_largest_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The smallest slice is mostly baseline noise; anchoring there projected 2M rows after processing 2.96M."""
    source = _tlc_file(tmp_path / "yellow_tripdata_2024-01.parquet", rows=200)
    # Slice of 50 rows uses 50 MB (noise), slice of 200 rows uses 4 MB: only the latter may set the slope.
    _resident(monkeypatch, [100.0, 150.0, 100.0, 104.0])

    estimate = crossover.measure(source, fractions=(0.25, 1.0), memory_budget_mb=512.0)

    assert [point.rows for point in estimate.points] == [50, 200]
    assert [point.working_mb for point in estimate.points] == [50.0, 4.0]
    assert estimate.projected_row_limit == int(512.0 / (4.0 / 200))  # 25,600 rows
    assert all(point.seconds >= 0 for point in estimate.points)


def test_a_negative_memory_delta_counts_as_none_and_projects_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allocator can return memory mid-measurement; a negative 'working set' must not become a slope."""
    source = _tlc_file(tmp_path / "yellow_tripdata_2024-01.parquet", rows=40)
    _resident(monkeypatch, [100.0, 90.0])

    estimate = crossover.measure(source, fractions=(1.0,))

    assert estimate.points[0].working_mb == 0.0
    assert estimate.projected_row_limit == 0, "no measured slope, so no projection"


def test_the_estimate_prints_its_assumptions_and_what_it_did_not_measure() -> None:
    estimate = CrossoverEstimate(
        points=(ScalePoint(rows=3_000_000, seconds=1.5, working_mb=120.0),),
        memory_budget_mb=512.0,
        projected_row_limit=12_800_000,
        assumptions=("Memory scales linearly with rows.",),
    )

    text = str(estimate)

    assert "3,000,000" in text
    assert "~12,800,000 rows against a 512 MB budget" in text
    assert "- Memory scales linearly with rows." in text
    assert "NOT MEASURED: the Spark side" in text


def test_every_estimate_carries_the_assumptions_it_rests_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _tlc_file(tmp_path / "yellow_tripdata_2024-01.parquet", rows=20)
    _resident(monkeypatch, [10.0, 11.0])

    assumptions = " ".join(crossover.measure(source, fractions=(1.0,)).assumptions)

    for stated in ("linearly", "DISTINCT KEYS", "RSS delta", "single machine"):
        assert stated in assumptions


def test_resident_memory_is_read_from_proc() -> None:
    if not Path("/proc/self/status").is_file():
        pytest.skip("no /proc on this platform")
    assert crossover._resident_mb() > 0


def test_resident_memory_is_zero_when_proc_has_no_vmrss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmPeak:\t1 kB\n", encoding="utf-8")
    monkeypatch.setattr(crossover, "Path", lambda _: status)

    assert crossover._resident_mb() == 0.0


def test_main_names_the_fetch_command_when_the_data_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    assert crossover.main() == 1
    assert "python scripts/datasets/fetch.py nyc-tlc" in capsys.readouterr().out


def test_main_prints_the_measurement_when_the_data_is_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "nyc-tlc").mkdir(parents=True)
    _tlc_file(tmp_path / "data" / "nyc-tlc" / "yellow_tripdata_2024-01.parquet", rows=40)
    _resident(monkeypatch, [10.0, 11.0] * 4)

    assert crossover.main() == 0
    assert "Projected single-node limit" in capsys.readouterr().out
