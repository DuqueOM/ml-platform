"""Which warehouse a process writes to is declared, never defaulted.

QA-4 F-23. Every public lakehouse function took `catalog: Catalog | None = None`
and fell back to `local_catalog()` — MinIO on localhost with a literal
credential. The Airflow DAG passed no catalogue at all, so wherever it ran it
wrote to a laptop's object store; in a cloud deployment the first symptom
would have been a connection error that reads as the network being down.

Separate from test_lakehouse.py on purpose: those need a running MinIO and are
skipped without one, and the choice of catalogue must be tested everywhere.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from demand_forecast import lakehouse
from demand_forecast.lakehouse import CATALOG_VARIABLE, catalog_from_environment


def test_an_unset_catalogue_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The only safe default for "which warehouse am I writing to" is none."""
    monkeypatch.delenv(CATALOG_VARIABLE, raising=False)
    with pytest.raises(RuntimeError, match=CATALOG_VARIABLE):
        catalog_from_environment()


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_catalogue_is_no_catalogue(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv(CATALOG_VARIABLE, blank)
    with pytest.raises(RuntimeError):
        catalog_from_environment()


def test_local_is_chosen_only_when_declared(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Declared, it works — against a throwaway SQLite catalogue, not the repository's."""
    monkeypatch.setenv(CATALOG_VARIABLE, "local")
    monkeypatch.setenv("ICEBERG_CATALOG_URI", f"sqlite:///{tmp_path / 'catalog.db'}")
    catalog = catalog_from_environment()
    assert type(catalog).__name__ == "SqlCatalog"


@pytest.mark.parametrize("cloud", ["glue", "biglake", "GLUE"])
def test_a_cloud_catalogue_without_an_adapter_says_so(monkeypatch: pytest.MonkeyPatch, cloud: str) -> None:
    """Not a silent fall-back to local: the gap is named."""
    monkeypatch.setenv(CATALOG_VARIABLE, cloud)
    with pytest.raises(NotImplementedError, match="no adapter"):
        catalog_from_environment()


def test_an_unknown_catalogue_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CATALOG_VARIABLE, "hive")
    with pytest.raises(ValueError, match="Supported: local"):
        catalog_from_environment()


@pytest.mark.parametrize("function", ["write_demand", "read_demand", "snapshots", "delete_before"])
def test_no_public_function_chooses_a_catalogue_for_its_caller(function: str) -> None:
    """The class, not the instance: a default here is how the DAG reached localhost."""
    parameter = inspect.signature(getattr(lakehouse, function)).parameters["catalog"]
    assert parameter.default is inspect.Parameter.empty, (
        f"{function} defaults its catalogue again — a caller that forgets one will write wherever that points"
    )
