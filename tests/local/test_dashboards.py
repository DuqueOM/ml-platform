"""Every panel must be backed by a series that exists.

A dashboard fails silently by design. Rename a metric, change a label, ship a
service that never gets scraped, and the panel renders a flat line — which
reads as "no traffic", the most reassuring possible display of a broken
pipeline. Nothing errors, nothing pages, and the graph is still there.

That is not hypothetical here. Before the annotations were added,
`platform/kubernetes/base/deployment.yaml` had no `prometheus.io/scrape`, the
local Prometheus discovered pods only in `ml-platform` while the service runs
in `demand-forecast-local`, and the result was measured: two scrape targets,
neither of them the service, and zero `demand_forecast_*` series. Every panel
built on those metrics would have been empty.

So these tests do two things a JSON schema cannot: run each panel's expression
against the running Prometheus, and check that every metric NAME it references
is one Prometheus actually holds.

    make local-serve && make local-dashboards
    uv run pytest tests/local -q -m local
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARDS = sorted((REPO_ROOT / "platform" / "observability" / "dashboards").glob("*.json"))
CONTEXT = "kind-ml-platform-local"
PROMETHEUS_PORT = 19092

#: A PromQL metric name: the identifier that is not a function call and not a
#: label. Matching `name{` or a bare `name` while excluding anything followed
#: by `(` keeps `sum`, `rate` and `histogram_quantile` out.
_METRIC = re.compile(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\b(?!\s*\()")

#: PromQL keywords that survive the pattern above and are not metrics.
_NOT_METRICS = {"by", "without", "le", "on", "ignoring", "group_left", "group_right", "offset", "bool", "and", "or"}


def _stack_running() -> bool:
    try:
        result = subprocess.run(
            ["kubectl", "--context", CONTEXT, "-n", "ml-platform", "get", "deploy", "prometheus"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(not _stack_running(), reason="local stack not running — run `make local-up`"),
]


@contextmanager
def _prometheus() -> Iterator[str]:
    process = subprocess.Popen(
        ["kubectl", "--context", CONTEXT, "-n", "ml-platform", "port-forward", "svc/prometheus",
         f"{PROMETHEUS_PORT}:9090"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", PROMETHEUS_PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise AssertionError("port-forward to prometheus never opened")
        yield f"http://127.0.0.1:{PROMETHEUS_PORT}"
    finally:
        process.terminate()
        process.wait(timeout=10)


def _api(base: str, path: str) -> dict:  # type: ignore[type-arg]
    with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
        return json.loads(response.read())


def _expressions() -> list[tuple[str, str, str]]:
    """Every `(dashboard, panel title, expression)` across all dashboards."""
    found = []
    for path in DASHBOARDS:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        for panel in dashboard.get("panels", []):
            for target in panel.get("targets", []):
                if expression := target.get("expr"):
                    found.append((path.stem, panel["title"], expression))
    return found


def _metric_names(expression: str) -> set[str]:
    candidates = set(_METRIC.findall(expression)) - _NOT_METRICS
    # Label VALUES and quoted strings are not metric names.
    return {name for name in candidates if f'"{name}"' not in expression and f"'{name}'" not in expression}


def test_there_is_at_least_one_panel_to_check() -> None:
    """An empty dashboard directory would make every test below vacuous."""
    assert _expressions(), f"no panel expression found under {DASHBOARDS}"


def test_the_service_is_actually_being_scraped() -> None:
    """The precondition for every panel, and the one that was false.

    Asserted on the TARGET rather than on a series: a series can linger after a
    target stops being scraped, so a metric existing does not prove collection
    is still happening.
    """
    with _prometheus() as base:
        targets = _api(base, "/api/v1/targets?state=active")["data"]["activeTargets"]

    serving = [t for t in targets if ":8000" in t["scrapeUrl"]]
    assert serving, f"the service is not a scrape target; Prometheus has {[t['scrapeUrl'] for t in targets]}"
    for target in serving:
        assert target["health"] == "up", f"{target['scrapeUrl']} is {target['health']}: {target.get('lastError')}"


@pytest.mark.parametrize(
    ("dashboard", "title", "expression"),
    _expressions(),
    ids=[f"{d}-{t}" for d, t, _ in _expressions()],
)
def test_every_panel_expression_is_valid_promql(dashboard: str, title: str, expression: str) -> None:
    """A malformed expression renders as an error nobody is watching for."""
    with _prometheus() as base:
        try:
            result = _api(base, f"/api/v1/query?query={urllib.request.quote(expression)}")
        except urllib.error.HTTPError as error:
            raise AssertionError(f"{dashboard} / {title}: {json.loads(error.read()).get('error')}") from error

    assert result["status"] == "success", f"{dashboard} / {title}: {result}"


@pytest.mark.parametrize(
    ("dashboard", "title", "expression"),
    _expressions(),
    ids=[f"{d}-{t}" for d, t, _ in _expressions()],
)
def test_every_metric_a_panel_names_exists(dashboard: str, title: str, expression: str) -> None:
    """The check a valid-PromQL test cannot make.

    `sum(rate(a_metric_that_was_renamed[5m]))` parses perfectly and returns an
    empty result, which is indistinguishable from a quiet system. Comparing the
    names against what Prometheus holds is what separates the two.
    """
    with _prometheus() as base:
        known = set(_api(base, "/api/v1/label/__name__/values")["data"])

    missing = sorted(_metric_names(expression) - known)
    assert not missing, (
        f"{dashboard} / {title} charts {missing}, which Prometheus does not have. "
        f"The panel would render empty, and an empty panel reads as no traffic."
    )
