"""What can be checked about a dashboard without a cluster.

`tests/local/test_dashboards.py` runs every panel expression against a live
Prometheus, which is the real check — and it only runs where a cluster exists.
CI has none, so the failures reachable from a JSON file alone are checked here
and run on every commit.

The one that matters most is the datasource uid. A provisioned dashboard whose
panels name a uid the datasource does not have renders every panel empty, with
no error anywhere: Grafana provisions it happily, and the graph is present and
flat. That is the same silent shape as a renamed metric, reached by a different
route.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "platform" / "observability" / "dashboards"
DASHBOARDS = sorted(DASHBOARD_DIR.glob("*.json"))
LOCAL_METRICS = REPO_ROOT / "platform" / "local" / "manifests" / "40-metrics.yaml"


def _provisioned_datasource_uids() -> set[str]:
    """The uids Grafana will actually have, read from the manifest that creates them."""
    uids = set()
    for document in yaml.safe_load_all(LOCAL_METRICS.read_text(encoding="utf-8")):
        if not isinstance(document, dict) or document.get("kind") != "ConfigMap":
            continue
        raw = document.get("data", {}).get("datasources.yaml")
        if not raw:
            continue
        for source in yaml.safe_load(raw).get("datasources", []):
            if "uid" in source:
                uids.add(source["uid"])
    return uids


def test_there_are_dashboards_to_check() -> None:
    """Otherwise every parametrised test below collects zero cases and passes."""
    assert DASHBOARDS, f"no dashboard JSON under {DASHBOARD_DIR}"


def test_the_manifest_pins_at_least_one_datasource_uid() -> None:
    """Guard the parser: an empty uid set makes the next test vacuous."""
    assert _provisioned_datasource_uids(), "no datasource uid is pinned in the local metrics manifest"


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.stem)
def test_dashboard_is_valid_json_with_a_stable_uid(path: Path) -> None:
    """The uid is the dashboard's identity across re-provisions.

    Without one, every sync creates a NEW dashboard, and links people saved
    point at the previous copy — which keeps rendering, from stale panels.
    """
    dashboard = json.loads(path.read_text(encoding="utf-8"))

    assert dashboard.get("uid"), f"{path.name} has no uid"
    assert dashboard.get("title"), f"{path.name} has no title"
    assert dashboard.get("panels"), f"{path.name} has no panels"


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.stem)
def test_every_panel_points_at_a_datasource_that_will_exist(path: Path) -> None:
    known = _provisioned_datasource_uids()
    dashboard = json.loads(path.read_text(encoding="utf-8"))

    for panel in dashboard["panels"]:
        uid = panel.get("datasource", {}).get("uid")
        assert uid in known, (
            f"{path.name} / {panel['title']} names datasource uid {uid!r}, "
            f"but provisioning creates {sorted(known)}. Every panel would render empty."
        )
        for target in panel.get("targets", []):
            target_uid = target.get("datasource", {}).get("uid")
            assert target_uid in known, f"{path.name} / {panel['title']} has a target on datasource {target_uid!r}"


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.stem)
def test_every_panel_says_what_it_is_for(path: Path) -> None:
    """A panel with no description is a number nobody can act on.

    The reader of a dashboard at 3am is not its author. "Inference concurrency"
    means nothing without "touching capacity means requests are queueing on the
    executor" — the second half is the part that turns a graph into a decision.
    """
    dashboard = json.loads(path.read_text(encoding="utf-8"))

    undocumented = [panel["title"] for panel in dashboard["panels"] if not panel.get("description", "").strip()]
    assert not undocumented, f"{path.name}: panels with no description: {undocumented}"
