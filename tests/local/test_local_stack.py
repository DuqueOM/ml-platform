"""Assert the local stack WORKS, not merely that its pods reported Ready.

`kubectl wait --for=condition=available` proves a container started and its
probe answered. It does not prove Postgres accepts a connection, that pgvector
is installed, that MinIO will take a bucket, or that a span sent to the
collector reaches Jaeger. Those are the properties Phase 1b exists to
establish before any cloud resource is created, and each one has failed in
practice while the pod stayed green.

Marked `local` and skipped automatically when the cluster is absent, so the
default suite stays runnable on a machine with no Docker.

    make local-up
    uv run pytest tests/local -q -m local
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.local

CONTEXT = "kind-ml-platform-local"
NAMESPACE = "ml-platform"


def _kubectl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _cluster_available() -> bool:
    try:
        return _kubectl("get", "ns", timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(not _cluster_available(), reason="local cluster not running — run `make local-up`"),
]


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 10.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


# --- the stack is present ---------------------------------------------------


def test_every_declared_deployment_is_available() -> None:
    """A component silently missing from the apply is worse than one crashing."""
    result = _kubectl("get", "deploy", "-o", "json")
    assert result.returncode == 0, result.stderr

    deployments = {
        item["metadata"]["name"]: item.get("status", {}).get("availableReplicas", 0)
        for item in json.loads(result.stdout)["items"]
    }
    expected = {"postgres", "minio", "otel-collector", "jaeger", "prometheus", "grafana"}

    missing = expected - set(deployments)
    assert not missing, f"declared but not deployed: {sorted(missing)}"

    unavailable = [name for name, ready in deployments.items() if not ready]
    assert not unavailable, f"deployed but not available: {unavailable}"


def test_every_container_declares_a_memory_limit() -> None:
    """An unbounded container is how a budgeted stack stops being budgeted.

    Failure looks like: a component added without a limit, which then grows
    until the node evicts something else — and the eviction names the victim,
    not the cause.
    """
    result = _kubectl("get", "pods", "-o", "json")
    assert result.returncode == 0, result.stderr

    unbounded: list[str] = []
    for pod in json.loads(result.stdout)["items"]:
        for container in pod["spec"]["containers"]:
            if not container.get("resources", {}).get("limits", {}).get("memory"):
                unbounded.append(f"{pod['metadata']['name']}/{container['name']}")

    assert not unbounded, f"containers without a memory limit: {unbounded}"


def test_namespace_enforces_restricted_pod_security() -> None:
    """The local namespace ENFORCES what the cloud overlays enforce.

    This started as `baseline` and was raised to `restricted` after the local
    stack reported that every container in it — written by the same hand as
    this test — lacked runAsNonRoot, allowPrivilegeEscalation: false, dropped
    capabilities and a seccomp profile. Under `baseline` those were warnings;
    in production they are rejections. Catching that here is the entire reason
    Phase 1b runs before Phase 2.
    """
    result = _kubectl("get", "ns", NAMESPACE, "-o", "json")
    labels = json.loads(result.stdout)["metadata"]["labels"]
    assert labels.get("pod-security.kubernetes.io/enforce") == "restricted"


def test_every_container_satisfies_restricted_pod_security() -> None:
    """Enforcement covers new pods; this covers what is actually running.

    A namespace can be raised to `restricted` while pods admitted under the
    old level keep running — enforcement is checked at admission, not
    continuously. Without this, the label says restricted and the workload is
    not.
    """
    result = _kubectl("get", "pods", "-o", "json")
    assert result.returncode == 0, result.stderr

    violations: list[str] = []
    for pod in json.loads(result.stdout)["items"]:
        pod_sc = pod["spec"].get("securityContext", {})
        name = pod["metadata"]["name"]
        if not pod_sc.get("runAsNonRoot"):
            violations.append(f"{name}: runAsNonRoot not set")
        if (pod_sc.get("seccompProfile") or {}).get("type") != "RuntimeDefault":
            violations.append(f"{name}: seccompProfile not RuntimeDefault")
        for container in pod["spec"]["containers"]:
            sc = container.get("securityContext", {})
            if sc.get("allowPrivilegeEscalation") is not False:
                violations.append(f"{name}/{container['name']}: allowPrivilegeEscalation not false")
            if "ALL" not in (sc.get("capabilities", {}).get("drop") or []):
                violations.append(f"{name}/{container['name']}: capabilities not dropped")

    assert not violations, "running pods violate restricted PSS:\n" + "\n".join(violations)


def test_deployments_use_recreate_so_the_quota_stays_honest() -> None:
    """A rolling update needs double a component's memory to coexist.

    The namespace quota is deliberately set to exactly the declared budget, so
    a RollingUpdate cannot fit — and buys nothing here, since every service is
    single-replica over emptyDir and the old pod's data is discarded anyway.
    The tempting fix was raising the quota; that would have made the budget
    stop meaning what it says.
    """
    result = _kubectl("get", "deploy", "-o", "json")
    wrong = [
        item["metadata"]["name"]
        for item in json.loads(result.stdout)["items"]
        if item["spec"].get("strategy", {}).get("type") != "Recreate"
    ]
    assert not wrong, f"deployments not using Recreate: {wrong}"


# --- the stack functions ----------------------------------------------------


def test_postgres_accepts_connections_and_has_pgvector() -> None:
    """Ready is not the same as usable.

    The probe runs `pg_isready`; it says nothing about whether the extension
    the online store and the RAG project both depend on is actually available.
    """
    assert _port_open(15432), "postgres port not reachable on the host"

    result = _kubectl(
        "exec",
        "deploy/postgres",
        "--",
        "psql",
        "-U",
        "mlplatform",
        "-d",
        "mlplatform",
        "-tAc",
        "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname FROM pg_extension WHERE extname='vector';",
    )
    assert result.returncode == 0, result.stderr
    assert "vector" in result.stdout, f"pgvector not available: {result.stdout!r}"


def test_minio_is_reachable_and_healthy() -> None:
    assert _port_open(19000), "minio API port not reachable on the host"
    assert _http_ok("http://localhost:19000/minio/health/live")


def test_prometheus_is_scraping_targets() -> None:
    """Running is not scraping.

    A Prometheus with a broken relabel config runs happily and collects
    nothing, which looks identical from the outside.
    """
    assert _http_ok("http://localhost:19090/-/ready")

    with urllib.request.urlopen("http://localhost:19090/api/v1/targets", timeout=15) as response:
        payload = json.load(response)

    active = payload["data"]["activeTargets"]
    assert active, "prometheus has no active targets — discovery is misconfigured"
    healthy = [t for t in active if t["health"] == "up"]
    assert healthy, f"no healthy targets: {[(t['labels'], t['health']) for t in active]}"


def test_jaeger_ui_answers() -> None:
    assert _port_open(16686), "jaeger UI port not reachable on the host"
    assert _http_ok("http://localhost:16686/")


def test_grafana_reports_healthy() -> None:
    assert _port_open(13000), "grafana port not reachable on the host"
    assert _http_ok("http://localhost:13000/api/health")


def test_a_span_sent_to_the_collector_reaches_jaeger() -> None:
    """The end-to-end property local observability exists to prove.

    Each hop can be green while the chain is broken: the collector accepts
    OTLP and drops it, or exports to an endpoint nothing is listening on. Only
    sending a span and then finding it proves the path.
    """
    service_name = f"local-verify-{int(time.time())}"
    span_id, trace_id = "0102030405060708", "0102030405060708090a0b0c0d0e0f10"
    now_ns = time.time_ns()

    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service_name}}]},
                "scopeSpans": [
                    {
                        "scope": {"name": "local-verify"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "verify-trace-path",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns),
                                "endTimeUnixNano": str(now_ns + 1_000_000),
                            }
                        ],
                    }
                ],
            }
        ]
    }

    forward = subprocess.Popen(
        ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, "port-forward", "svc/otel-collector", "4318:4318"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not _port_open(4318):
            time.sleep(0.5)
        assert _port_open(4318), "could not port-forward the collector"

        request = urllib.request.Request(
            "http://localhost:4318/v1/traces",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            assert response.status == 200, f"collector rejected the span: {response.status}"
    finally:
        forward.terminate()
        forward.wait(timeout=10)

    # The collector batches; poll rather than assuming immediate delivery.
    deadline = time.time() + 40
    services: list[str] = []
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:16686/api/services", timeout=10) as response:
                services = json.load(response).get("data") or []
        except (urllib.error.URLError, TimeoutError, OSError):
            services = []
        if service_name in services:
            return
        time.sleep(2)

    pytest.fail(f"span never reached jaeger; services seen: {services}")
