"""Iceberg gives reproducibility only if time travel actually works.

These run against the local MinIO stack and are skipped when it is absent, so
the default suite stays runnable without Docker. They are integration tests by
rule 03-testing's trigger — the code crosses a boundary it does not own — and
they use the REAL object store rather than a mock, because a mocked S3 tests
the mock.
"""

from __future__ import annotations

import socket
from datetime import datetime

import polars as pl
import pytest


def _minio_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 19000), timeout=2):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _minio_up(), reason="local stack not running — run `make local-up`"),
]


def _demand_at(zone: int, when: datetime, count: int) -> pl.DataFrame:
    """Like :func:`_demand` but with the month under the test's control.

    Needed to prove that overwriting one month leaves the others alone; a
    fixture pinned to a single month cannot express that property.
    """
    return pl.DataFrame(
        {
            "zone_id": [zone],
            "event_time": [when],
            "trip_count": [count],
            "mean_distance": [2.5],
            "total_fare": [18.0],
        }
    )


def _demand(zone: int, hour: int, count: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_id": [zone],
            "event_time": [datetime(2024, 3, 1, hour)],
            "trip_count": [count],
            "mean_distance": [2.5],
            "total_fare": [30.0],
        }
    )


@pytest.fixture
def catalog(tmp_path):  # type: ignore[no-untyped-def]
    """A catalogue isolated per test, so one test cannot see another's writes."""
    from demand_forecast.lakehouse import local_catalog

    return local_catalog(
        warehouse_uri="s3://lakehouse/",
        catalog_db=f"sqlite:///{tmp_path}/catalog.db",
    )


def test_a_write_returns_a_citable_snapshot(catalog) -> None:  # type: ignore[no-untyped-def]
    """A snapshot id is what makes a training input reconstructable.

    Failure looks like: a model card recording only a DATE. The date's contents
    can be rewritten by a later backfill, so the card names something that no
    longer exists.
    """
    from demand_forecast.lakehouse import write_demand

    result = write_demand(_demand(1, 8, 100), catalog)

    assert result.snapshot_id > 0
    assert result.rows == 1
    assert result.mode == "append"


def test_time_travel_returns_the_table_as_it_stood(catalog) -> None:  # type: ignore[no-untyped-def]
    """The property the whole module exists for.

    Failure looks like: `snapshot_id` accepted and ignored, so a "reproducible"
    retrain silently reads today's data and nobody notices until the numbers
    disagree with the model card.
    """
    from demand_forecast.lakehouse import read_demand, write_demand

    first = write_demand(_demand(1, 8, 100), catalog)
    write_demand(_demand(2, 9, 200), catalog)

    assert read_demand(catalog).height == 2
    past = read_demand(catalog, snapshot_id=first.snapshot_id)
    assert past.height == 1, "time travel returned the current table, not the historical one"
    assert past["zone_id"].to_list() == [1]


def test_every_write_creates_a_distinct_snapshot(catalog) -> None:  # type: ignore[no-untyped-def]
    """Without distinct snapshots there is no history to travel to."""
    from demand_forecast.lakehouse import snapshots, write_demand

    a = write_demand(_demand(1, 8, 100), catalog)
    b = write_demand(_demand(2, 9, 200), catalog)

    assert a.snapshot_id != b.snapshot_id
    assert [s[0] for s in snapshots(catalog)] == [a.snapshot_id, b.snapshot_id]


def test_ensure_table_is_idempotent(catalog) -> None:  # type: ignore[no-untyped-def]
    """A rerun after a failure is the normal case, not the exception.

    Failure looks like: an ingestion that raises on its second run because the
    table already exists, so every retry needs a human to decide.
    """
    from demand_forecast.lakehouse import ensure_table

    assert ensure_table(catalog).name() == ensure_table(catalog).name()


def test_overwrite_does_not_double_count(catalog) -> None:  # type: ignore[no-untyped-def]
    """Re-ingesting a month must replace it, never append to it.

    Failure looks like: a backfill run twice, every trip_count doubled, and a
    model trained on demand that never happened — with nothing raising.
    """
    from demand_forecast.lakehouse import read_demand, write_demand

    # Two DIFFERENT months. The previous version of this test wrote the same
    # single row twice and asserted height == 1, which holds just as well when
    # overwrite deletes the entire table first — it distinguished nothing, and
    # the table-wiping bug lived underneath it.
    write_demand(_demand_at(1, datetime(2024, 3, 1, 8), 100), catalog)
    write_demand(_demand_at(1, datetime(2024, 4, 1, 8), 50), catalog)
    write_demand(_demand_at(1, datetime(2024, 3, 1, 8), 100), catalog, overwrite=True)

    table = read_demand(catalog)
    assert table.height == 2, f"overwrite appended instead of replacing: {table.height} rows"

    april = table.filter(pl.col("event_time") == datetime(2024, 4, 1, 8))
    assert april.height == 1, "overwriting March deleted April — the filter is unscoped"
    assert april["trip_count"][0] == 50, "April survived but was altered"


def test_partitioning_is_declared_on_the_event_month(catalog) -> None:  # type: ignore[no-untyped-def]
    """Partitioning by event month is what keeps a backfill bounded.

    Failure looks like: an unpartitioned table where reprocessing one month
    rewrites the entire history.
    """
    from demand_forecast.lakehouse import ensure_table

    spec = ensure_table(catalog).spec()
    assert len(spec.fields) == 1
    assert spec.fields[0].name == "event_month"


def test_types_survive_the_round_trip(catalog) -> None:  # type: ignore[no-untyped-def]
    """A silent type change writes fine and reads back wrong.

    Polars produces ns timestamps; Iceberg declares us. Letting that convert
    implicitly is how a timestamp loses precision without any error.
    """
    from demand_forecast.lakehouse import read_demand, write_demand

    write_demand(_demand(7, 14, 42), catalog)
    row = read_demand(catalog).row(0, named=True)

    assert row["zone_id"] == 7
    assert row["trip_count"] == 42
    assert row["event_time"] == datetime(2024, 3, 1, 14)
