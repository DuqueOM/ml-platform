"""Iceberg gives reproducibility only if time travel actually works.

Every test runs against TWO backends of the same `local_catalog()`:

- **filesystem** — the SQL catalogue with a `file://` warehouse under
  `tmp_path`. Real pyiceberg, real pyarrow, real Parquet and real snapshots;
  only the object store is a directory. It runs in every suite, CI included.
- **object-store** — the local stack's S3 endpoint (RustFS). An integration
  test by rule 03-testing's trigger (the code crosses a boundary it does not
  own), skipped when the stack is absent. A mocked S3 would test the mock, so
  there is none. Its bucket is created by `make local-up`.

The filesystem half exists because the S3 half ran nowhere: CI deselects
`integration`, and the stack's MinIO image could no longer be pulled (R15-20,
since replaced). So a
pyiceberg 0.11 -> 0.12 and pyarrow 21 -> 25 upgrade had no test that wrote a
table — this module's seven properties were verified by nothing on any build.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta, timezone

import polars as pl
import pytest


def _object_store_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 19000), timeout=2):
            return True
    except OSError:
        return False


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


@pytest.fixture(
    params=[
        pytest.param("filesystem"),
        pytest.param(
            "object-store",
            marks=[
                pytest.mark.integration,
                pytest.mark.skipif(not _object_store_up(), reason="local stack not running — run `make local-up`"),
            ],
        ),
    ]
)
def catalog(request, tmp_path):  # type: ignore[no-untyped-def]
    """A catalogue isolated per test, so one test cannot see another's writes."""
    from demand_forecast.lakehouse import LOCAL_WAREHOUSE, local_catalog

    warehouse = f"file://{tmp_path}/warehouse" if request.param == "filesystem" else LOCAL_WAREHOUSE
    return local_catalog(warehouse_uri=warehouse, catalog_db=f"sqlite:///{tmp_path}/catalog.db")


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


# --- what QA-4 round sixteen found with no behavioural test -----------------


def _three_months(catalog) -> None:  # type: ignore[no-untyped-def]
    """January, the first instant of February, and March: the cutoff's boundary is the middle row."""
    from demand_forecast.lakehouse import write_demand

    write_demand(
        pl.concat(
            [
                _demand_at(1, datetime(2024, 1, 5), 1),
                _demand_at(2, datetime(2024, 2, 1), 2),
                _demand_at(3, datetime(2024, 3, 5), 3),
            ]
        ),
        catalog,
    )


@pytest.mark.parametrize(
    "cutoff",
    [
        pytest.param(datetime(2024, 2, 1), id="naive-utc"),
        pytest.param(datetime(2024, 2, 1, tzinfo=UTC), id="aware-utc"),
        pytest.param(datetime(2024, 2, 1, 1, tzinfo=timezone(timedelta(hours=1))), id="aware-plus-one"),
    ],
)
def test_delete_before_removes_strictly_earlier_rows(catalog, cutoff: datetime) -> None:  # type: ignore[no-untyped-def]
    """Strictly before, at the boundary, whatever zone the cutoff is written in.

    Failure looks like: a row stamped exactly at the cutoff deleted with the
    ones before it (`<` read as `<=`), or an aware cutoff — which is what
    `snapshots()` and `datetime.now(UTC)` give — refused by pyiceberg with
    "Zone offset provided, but not expected". `09:00+01:00` and `08:00` UTC are
    the same instant; the stored column is naive UTC.
    """
    from demand_forecast.lakehouse import delete_before, read_demand, snapshots

    _three_months(catalog)
    ((written, _),) = snapshots(catalog)

    result = delete_before(cutoff, catalog)

    assert result is not None
    assert result.mode == "delete"
    assert result.rows == 1
    assert sorted(read_demand(catalog)["zone_id"].to_list()) == [2, 3], "the boundary row went with the earlier one"
    assert snapshots(catalog)[-1][0] == result.snapshot_id
    # Reversible: the state before the delete is still a readable snapshot.
    assert read_demand(catalog, snapshot_id=written).height == 3


def test_a_delete_that_matches_nothing_reports_nothing(catalog) -> None:  # type: ignore[no-untyped-def]
    """No snapshot committed, so no snapshot reported.

    Failure looks like: the previous write's snapshot returned as this delete's
    — a citation of an operation that did not happen, which a caller would
    record as "cleaned at snapshot N" when N is the uncleaned table.
    """
    from demand_forecast.lakehouse import delete_before, snapshots

    _three_months(catalog)
    history = snapshots(catalog)

    assert delete_before(datetime(2023, 1, 1), catalog) is None
    assert snapshots(catalog) == history


@pytest.mark.parametrize("overwrite", [False, True], ids=["append", "overwrite"])
def test_a_write_reports_its_own_snapshot_when_another_writer_follows_it(  # type: ignore[no-untyped-def]
    catalog, monkeypatch: pytest.MonkeyPatch, overwrite: bool
) -> None:
    """The id is the one THIS write committed, not whatever the catalogue holds next.

    Forces the interleaving round sixteen used: a second writer commits
    immediately after this write's commit and before anything else runs. The
    DAG validates, trains on and records the id `write_demand` returns, so
    returning the other writer's id would put its rows — `trip_count=999`
    here — into the model's training input under this run's name.
    """
    from demand_forecast.lakehouse import read_demand, snapshots, write_demand
    from pyiceberg.table import Table

    write_demand(_demand_at(1, datetime(2024, 1, 5), 1), catalog)

    real_commit = Table._do_commit
    interleaved: list[int] = []

    def commit_then_let_another_writer_in(self: Table, *args: object, **kwargs: object) -> None:
        real_commit(self, *args, **kwargs)  # type: ignore[arg-type]
        if not interleaved:
            interleaved.append(1)
            write_demand(_demand_at(3, datetime(2024, 3, 5), 999), catalog)

    monkeypatch.setattr(Table, "_do_commit", commit_then_let_another_writer_in)
    ours = write_demand(_demand_at(2, datetime(2024, 2, 5), 7), catalog, overwrite=overwrite)
    monkeypatch.undo()

    ids = [snapshot_id for snapshot_id, _ in snapshots(catalog)]
    assert interleaved, "the second writer never ran; the test proves nothing"
    assert ours.snapshot_id == ids[-2], (
        f"reported {ours.snapshot_id}, committed {ids[-2]}; the other writer's is {ids[-1]}"
    )
    assert 999 not in read_demand(catalog, snapshot_id=ours.snapshot_id)["trip_count"].to_list()


def test_delete_before_counts_only_what_it_deleted_when_another_writer_commits_first(  # type: ignore[no-untyped-def]
    catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-4 round seventeen: a writer between our load and our commit made the count "delete -3 rows".

    pyiceberg retries the delete on top of the other writer's snapshot, so a
    count taken against the head we loaded mixes their rows into ours.
    """
    from demand_forecast import lakehouse
    from demand_forecast.lakehouse import delete_before, write_demand

    _three_months(catalog)
    real_ensure = lakehouse.ensure_table
    interleaved: list[int] = []

    def load_then_let_another_writer_in(given):  # type: ignore[no-untyped-def]
        table = real_ensure(given)
        if not interleaved:
            interleaved.append(1)
            write_demand(
                pl.concat([_demand_at(z, datetime(2024, 3, 9), 9) for z in (7, 8, 9)]),
                catalog,
            )
        return table

    monkeypatch.setattr(lakehouse, "ensure_table", load_then_let_another_writer_in)
    result = delete_before(datetime(2024, 2, 1), catalog)
    monkeypatch.undo()

    assert interleaved, "the second writer never ran; the test proves nothing"
    assert result is not None
    assert result.rows == 1, f"one row preceded the cutoff; the delete reported {result.rows}"


def test_a_delete_is_one_snapshot_whose_summary_counts_a_straddling_file(catalog) -> None:  # type: ignore[no-untyped-def]
    """The count reads the delete's own snapshot summary, which holds only if pyiceberg commits ONE snapshot.

    January's file straddles the cutoff, so the delete rewrites it: three
    records dropped, one written back — two removed.
    """
    from demand_forecast.lakehouse import delete_before, ensure_table, snapshots, write_demand

    write_demand(
        pl.concat(
            [
                _demand_at(1, datetime(2024, 1, 3), 1),
                _demand_at(2, datetime(2024, 1, 20), 2),
                _demand_at(4, datetime(2024, 1, 25), 4),
                _demand_at(3, datetime(2024, 2, 5), 3),
            ]
        ),
        catalog,
    )
    before = [snapshot_id for snapshot_id, _ in snapshots(catalog)]

    result = delete_before(datetime(2024, 1, 22), catalog)

    after = [snapshot_id for snapshot_id, _ in snapshots(catalog)]
    assert result is not None
    assert after[:-1] == before, "the delete committed more than one snapshot; the summary count would undercount"
    assert ensure_table(catalog).snapshot_by_id(result.snapshot_id).parent_snapshot_id == before[-1]
    assert result.rows == 2
