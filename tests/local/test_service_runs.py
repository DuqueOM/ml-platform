"""The service starts, reaches Ready, and answers from outside the cluster.

Every claim this repository made about serving until now was about YAML. Six
overlays rendered; `kustomize build` exited zero; nothing had ever started. The
probes in the base Deployment pointed at `/health/ready` and `/health/live`,
which the service does not serve — so a pod could never have become Ready, and
no amount of rendering would have said so.

This file is the difference between "the manifest is well-formed" and "the
container serves a request", and it is deliberately end-to-end: build → `kind
load` → apply → Ready → HTTP over a port-forward. Anything less re-tests the
manifest.

What it does NOT claim: that a demand forecast is served. ADR-008 records why —
the scaffold is a binary classifier and no forecast artifact exists — and
`test_the_response_is_a_classification_which_is_adr_008` asserts that gap
rather than papering over it, so the day it closes, this test fails and has to
be rewritten.

    make local-serve
    uv run pytest tests/local -q -m local
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

CONTEXT = "kind-ml-platform-local"
NAMESPACE = "demand-forecast-local"
PORT = 18081


def _kubectl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _service_deployed() -> bool:
    try:
        result = _kubectl("get", "deploy", "demand-forecast", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(not _service_deployed(), reason="service not deployed — run `make local-serve`"),
]


@contextmanager
def _port_forward() -> Iterator[str]:
    """A port-forward that is torn down even when the test fails.

    On its own port, not the stack's: two forwards on one port produce a
    connection that succeeds against the WRONG service, and the test then
    passes while proving nothing.
    """
    process = subprocess.Popen(
        ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, "port-forward", "svc/demand-forecast", f"{PORT}:80"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise AssertionError(f"port-forward never opened on {PORT}")
        yield f"http://127.0.0.1:{PORT}"
    finally:
        process.terminate()
        process.wait(timeout=10)


def _get(url: str, timeout: float = 15.0) -> tuple[int, dict]:  # type: ignore[type-arg]
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read())


def _post(url: str, payload: dict, timeout: float = 30.0) -> tuple[int, dict]:  # type: ignore[type-arg]
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


VALID_REQUEST = {
    "entity_id": "zone-42",
    "feature_a": 37.0,
    "feature_b": 1200.0,
    # The scaffold's Pandera contract restricts this to category_A/B/C. Sending
    # a plausible-looking `weekday` returns 422, which is the validation layer
    # working — worth encoding, because the obvious payload is the rejected one.
    "feature_c": "category_A",
}


def test_the_pod_is_ready_and_has_not_restarted() -> None:
    """Ready once is not the claim. Ready without restarts is.

    A pod that reaches Ready and is then killed by liveness cycles through
    Ready repeatedly, and a snapshot check catches it in the good half of the
    cycle. The restart count is what distinguishes the two.
    """
    result = _kubectl("get", "pod", "-l", "app=demand-forecast", "-o", "json")
    assert result.returncode == 0, result.stderr

    pods = json.loads(result.stdout)["items"]
    assert pods, "no pod matches app=demand-forecast"

    for pod in pods:
        conditions = {c["type"]: c["status"] for c in pod["status"].get("conditions", [])}
        assert conditions.get("Ready") == "True", f"{pod['metadata']['name']} is not Ready: {conditions}"
        for container in pod["status"]["containerStatuses"]:
            assert container["restartCount"] == 0, (
                f"{pod['metadata']['name']}/{container['name']} restarted "
                f"{container['restartCount']}x — a probe is failing after startup"
            )


def test_readiness_and_liveness_answer_over_http() -> None:
    """The paths kubelet probes, called the way kubelet calls them."""
    with _port_forward() as base:
        live_status, live_body = _get(f"{base}/health")
        ready_status, ready_body = _get(f"{base}/ready")

    assert live_status == 200
    assert live_body["status"] == "healthy"
    assert ready_status == 200
    assert ready_body["status"] == "ready"
    assert ready_body["model_loaded"] is True
    assert ready_body["warmed_up"] is True, "traffic must be gated until warm-up completes (D-23)"


def test_the_service_answers_a_prediction_from_outside_the_cluster() -> None:
    """The first request this repository has ever served."""
    with _port_forward() as base:
        status, body = _post(f"{base}/predict", VALID_REQUEST)

    assert status == 200, body
    assert "prediction_id" in body, "every response must correlate with a prediction log entry (D-20)"
    assert body["model_version"]


def test_an_invalid_category_is_rejected_rather_than_scored() -> None:
    """A model asked to score a value it never saw returns a confident number.

    The validation layer is what stops that, and it is only worth having if it
    actually fires — so this sends the plausible-looking value that is not in
    the contract.
    """
    with _port_forward() as base:
        status, _ = _post(f"{base}/predict", {**VALID_REQUEST, "feature_c": "weekday"})

    assert status == 422


def test_metrics_carry_the_service_prefix() -> None:
    """`SERVICE_METRIC_PREFIX` is set by the overlay, not baked into the image.

    An unresolved prefix produces metric names that no dashboard or alert rule
    matches, and the symptom is a Grafana panel that is simply empty — which
    reads as "no traffic" rather than as a misconfiguration.
    """
    with _port_forward() as base:
        request = urllib.request.Request(f"{base}/metrics")
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode()

    assert "demand_forecast_" in body, "metrics are not carrying the overlay's prefix"


def test_the_response_is_a_classification_which_is_adr_008() -> None:
    """This test exists to FAIL the day ADR-008 is resolved.

    The scaffold serves `prediction_score` in `[0, 1]` with a `risk_level`,
    because it is a binary classifier; demand-forecast is a regression with a
    conformal interval. Asserting the current shape means the gap cannot be
    quietly forgotten — when the template gains a regression path and this
    service starts returning a forecast with an interval, this fails loudly and
    whoever fixed it gets to delete it.
    """
    with _port_forward() as base:
        _, body = _post(f"{base}/predict", VALID_REQUEST)

    assert 0.0 <= body["prediction_score"] <= 1.0
    assert body["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    resolved = "the response now carries an interval — ADR-008 appears to be resolved, so rewrite this test "
    resolved += "to assert the forecast contract instead of the classification one"
    assert "interval" not in body, resolved
    assert "lower" not in body, resolved
