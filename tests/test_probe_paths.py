"""A probe must name a route the service actually serves.

`platform/kubernetes/base/deployment.yaml` probed `/health/ready` and
`/health/live`. The service exposes `/health` and `/ready`. Both probes would
have 404ed: readiness never passes, so the pod never receives traffic, and
liveness restarts it forever — a crash loop whose cause is in a YAML file
nobody suspects.

Six overlays rendered that manifest without complaint, because `kustomize
build` validates structure and has no idea what the container serves. Nothing
in CI could catch it either: the paths are strings, and both files were
internally consistent.

So this test reads the routes the app declares and the paths the manifests
probe, and requires the second to be a subset of the first. It is the cheapest
possible stand-in for starting the container, and it runs in milliseconds on
every commit — including the ones made on a machine with no Docker.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE_APP = REPO_ROOT / "services" / "demand-forecast-serving" / "app"
MANIFESTS = sorted((REPO_ROOT / "platform" / "kubernetes").rglob("*.yaml"))

_PROBES = ("startupProbe", "readinessProbe", "livenessProbe")


def _declared_routes() -> set[str]:
    """Every path the generated service registers, read from its source.

    Parsed with `ast` rather than by importing the app: importing it pulls
    FastAPI, joblib and the service's whole dependency tree into this
    repository's test run, and the generated service is tested upstream. What
    is needed here is only the set of strings it decorates routes with.
    """
    routes: set[str] = set()
    for source in sorted(SERVICE_APP.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            # Matches `@app.get("/health")` and `@router.post("/predict")`, and
            # deliberately not `requests.get("http://...")` — the attribute's
            # OWNER has to look like an app or a router.
            if not isinstance(function, ast.Attribute) or function.attr not in {"get", "post"}:
                continue
            owner = function.value
            if not isinstance(owner, ast.Name) or owner.id not in {"app", "router"}:
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                routes.add(node.args[0].value)
    return routes


def _probed_paths() -> list[tuple[Path, str, str]]:
    """Every `(manifest, probe kind, path)` in the platform's Kubernetes tree."""
    found = []
    for manifest in MANIFESTS:
        text = manifest.read_text(encoding="utf-8")
        for document in yaml.safe_load_all(text):
            if not isinstance(document, dict):
                continue
            spec = document.get("spec", {}).get("template", {}).get("spec", {})
            for container in spec.get("containers", []):
                for kind in _PROBES:
                    http = container.get(kind, {}).get("httpGet")
                    if http and "path" in http:
                        found.append((manifest, kind, http["path"]))
    return found


def test_the_service_declares_the_routes_this_test_reasons_about() -> None:
    """Guard the parser itself.

    If the AST walk stops matching — a decorator style changes, the app object
    is renamed — every assertion below would pass against an EMPTY set of
    routes and this file would enforce nothing while staying green. That has
    happened twice in this repository to other checks.
    """
    routes = _declared_routes()
    assert {"/health", "/ready", "/metrics"} <= routes, f"route parser found only {sorted(routes)}"


def test_at_least_one_probe_is_declared() -> None:
    """Same guard, other side: an empty probe list would vacuously pass."""
    assert _probed_paths(), "no httpGet probe found in platform/kubernetes/ — the parser or the manifests moved"


@pytest.mark.parametrize(
    ("manifest", "kind", "path"),
    [pytest.param(m, k, p, id=f"{m.parent.name}-{k}-{p}") for m, k, p in _probed_paths()],
)
def test_every_probe_path_is_a_route_the_service_serves(manifest: Path, kind: str, path: str) -> None:
    routes = _declared_routes()
    assert path in routes, (
        f"{manifest.relative_to(REPO_ROOT)} probes {path!r} on {kind}, which the service does not serve. "
        f"It serves {sorted(routes)}. A readiness probe on a 404 never passes and a liveness probe on one "
        f"restarts the pod forever."
    )


def test_readiness_and_liveness_are_not_the_same_path() -> None:
    """They answer different questions and must not be wired to one answer.

    Liveness asks "is this process alive"; readiness asks "should it receive
    traffic". Pointing both at the same handler means a pod that is alive but
    not warmed up either takes traffic too early or gets restarted for being
    slow — and which one you get depends on a race.
    """
    by_manifest: dict[Path, dict[str, str]] = {}
    for manifest, kind, path in _probed_paths():
        by_manifest.setdefault(manifest, {})[kind] = path

    for manifest, probes in by_manifest.items():
        if "readinessProbe" in probes and "livenessProbe" in probes:
            assert probes["readinessProbe"] != probes["livenessProbe"], (
                f"{manifest.relative_to(REPO_ROOT)} points readiness and liveness at {probes['readinessProbe']!r}"
            )
