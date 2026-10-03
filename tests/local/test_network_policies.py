"""The NetworkPolicies are enforced, and the selector that was wrong is watched failing.

Every claim this repository made about its NetworkPolicies was about YAML.
They rendered; `kubectl kustomize` exited zero; no packet had ever been
dropped because of them. Worse, two documents said this could not be measured
locally — that kind's CNI accepts a policy and enforces nothing — and QA-4
round eleven disproved it on a live cluster.

This file is that measurement, kept. It is the difference between "the policy
is well-formed" and "the cluster drops what it should".

**The mutation matters more than the happy path.** `commonLabels` once
rewrote `allow-dns`'s peer selector into one no CoreDNS pod carries, which
denied DNS in all six cloud overlays while every offline check passed. That
defect is reproduced here against the running cluster, then undone.

Propagation is not instant. Measured on kindnetd v20250512: a correct policy
took 3s to take effect once and 41s another time, so every assertion polls
rather than sleeping — a fixed short sleep reports a denial that is really a
policy not yet in force, which is how the first attempt at this measurement
fooled its author.

    make local-up && make local-serve
    uv run pytest tests/local/test_network_policies.py -q -m local
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

CONTEXT = "kind-ml-platform-local"
NAMESPACE = "demand-forecast-local"
MONITORING_NAMESPACE = "ml-platform"
REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES = REPO_ROOT / "platform" / "policies"

#: Generous against the 41s observed, because the cost of being wrong is
#: asymmetric: too short reports a false denial, too long only makes a green
#: test slower.
PROPAGATION_TIMEOUT_SECONDS = 150

PROBE = "netpolicy-probe"


def _kubectl(*args: str, namespace: str = NAMESPACE, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", "--context", CONTEXT, "-n", namespace, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


#: Long enough for busybox's resolver to exhaust its own retries when the
#: answer is being dropped, short enough that a denied lookup does not stall
#: the poll. The bound is applied to `kubectl exec` from OUTSIDE the container,
#: and that is not a stylistic choice — see `_resolves`.
LOOKUP_TIMEOUT_SECONDS = 15


def _policies_in_force() -> bool:
    result = _kubectl("get", "netpol", "default-deny", "-o", "name", timeout=30)
    return result.returncode == 0


pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(
        not _policies_in_force(),
        reason="policies not applied — run `make local-up && make local-serve`",
    ),
]


@pytest.fixture(scope="module")
def probe() -> Iterator[str]:
    """A shell in the namespace, satisfying Pod Security `restricted`.

    The real serving container has no shell, and a probe that cannot be
    exec'd into cannot answer the question.

    It carries its OWN label, deliberately not `app: demand-forecast`.
    `default-deny` and `allow-dns` select every pod in the namespace
    (`podSelector: {}`), so what this measures for DNS is exactly what the
    serving pod experiences — while a probe labelled as the serving app would
    be swept up by `test_service_runs.py`, which asserts that every pod
    matching that label is Ready and has never restarted. It was, and that test
    failed on this probe rather than on the service: one test's fixture
    breaking another's subject.

    `restartPolicy: Never` and a teardown that waits, for the same reason: a
    probe that lingers is a probe that appears in someone else's query.
    """
    _kubectl("delete", "pod", PROBE, "--ignore-not-found", "--wait=true", timeout=120)
    manifest = yaml.safe_dump(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": PROBE, "namespace": NAMESPACE, "labels": {"app": PROBE}},
            "spec": {
                # Never, so a container that exits cannot silently come back as
                # a different one mid-measurement; the fixture deletes any
                # leftover first, because `kubectl apply` cannot change a Pod's
                # restartPolicy in place.
                "restartPolicy": "Never",
                "containers": [
                    {
                        "name": "probe",
                        "image": "busybox:1.36",
                        "command": ["sh", "-c", "sleep 3600"],
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "runAsNonRoot": True,
                            "runAsUser": 10001,
                            "capabilities": {"drop": ["ALL"]},
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                    }
                ],
            },
        }
    )
    subprocess.run(
        ["kubectl", "--context", CONTEXT, "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
        timeout=90,
    )
    ready = _kubectl("wait", "--for=condition=ready", f"pod/{PROBE}", "--timeout=120s")
    if ready.returncode != 0:
        pytest.skip(f"the probe pod never became ready: {ready.stdout}{ready.stderr}")
    yield PROBE
    _kubectl("delete", "pod", PROBE, "--ignore-not-found", "--wait=true", timeout=120)


def _resolves(probe_name: str) -> bool:
    """One DNS attempt from inside the namespace, through whatever policy is in force.

    The FQDN, not `kubernetes.default`: busybox's nslookup does not apply the
    search domains, so the short name fails even with no policy at all — which
    cost the first attempt at this measurement a false baseline.

    **The lookup is bounded from outside, and the reason is measured.** The
    first version ran `timeout 5 nslookup` INSIDE the container. busybox's
    `timeout` signals the whole process group, so the first denied lookup sent
    SIGTERM to PID 1 — the `sleep` holding the pod open — and the container
    exited 0. With `restartPolicy: Never` it stayed dead, every later exec
    failed, and the negative control read that as "DNS denied" while its
    restore step waited for a recovery no dead pod could report. Reproduced
    directly: attempt 1 returned 143 (SIGTERM), attempt 2 found the pod
    `Succeeded`.

    **A failed exec is not a denial, and conflating them cost the second
    attempt.** When the probe pod vanished mid-module, every `nslookup`
    returned non-zero, the negative control read that as "DNS denied" and its
    restore step then waited 150 seconds for a recovery that could never be
    observed. So reachability is established first, and a probe that cannot be
    reached raises instead of quietly answering False.
    """
    alive = _kubectl("exec", probe_name, "--", "true", timeout=30)
    if alive.returncode != 0:
        raise RuntimeError(
            f"the probe pod {probe_name} is not usable, so nothing here is measuring a policy: "
            f"{(alive.stdout + alive.stderr).strip()[:400]}"
        )
    try:
        result = _kubectl(
            "exec",
            probe_name,
            "--",
            "nslookup",
            "kubernetes.default.svc.cluster.local",
            timeout=LOOKUP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _converges(probe_name: str, *, expected: bool) -> float | None:
    """Seconds until DNS reaches `expected`, or None if it never does."""
    started = time.monotonic()
    while time.monotonic() - started < PROPAGATION_TIMEOUT_SECONDS:
        if _resolves(probe_name) is expected:
            return time.monotonic() - started
        time.sleep(3)
    return None


def test_the_policies_the_overlay_ships_are_the_ones_in_force(probe: str) -> None:
    """The overlay includes them; this asserts the cluster agrees."""
    listed = _kubectl("get", "netpol", "-o", "jsonpath={range .items[*]}{.metadata.name}{'\\n'}{end}")
    names = set(listed.stdout.split())
    assert {"default-deny", "allow-dns", "allow-serving-ingress", "allow-serving-egress"} <= names, names


def test_dns_resolves_under_the_policies(probe: str) -> None:
    """`default-deny` plus `allow-dns` must leave resolution working."""
    elapsed = _converges(probe, expected=True)
    assert elapsed is not None, (
        f"DNS never resolved within {PROPAGATION_TIMEOUT_SECONDS}s with the shipped policies in force. "
        f"A default-deny namespace that cannot resolve breaks every lookup, and the symptom is a timeout "
        f"that reads as the dependency being down"
    )


def test_rewriting_the_dns_peer_selector_denies_dns(probe: str) -> None:
    """The round-eleven defect, reproduced against the cluster and then undone.

    `commonLabels` added the overlay's labels to this peer selector, which no
    CoreDNS pod carries. Offline, everything passed.
    """
    original = (POLICIES / "allow-dns.yaml").read_text(encoding="utf-8")
    broken = yaml.safe_load(original)
    broken["spec"]["egress"][0]["to"][0]["podSelector"]["matchLabels"].update({"cloud": "none", "environment": "local"})
    try:
        applied = subprocess.run(
            ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, "apply", "-f", "-"],
            input=yaml.safe_dump(broken),
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert applied.returncode == 0, applied.stderr
        denied = _converges(probe, expected=False)
        assert denied is not None, (
            "DNS still resolved with a peer selector no CoreDNS pod carries. Either the CNI stopped "
            "enforcing NetworkPolicy, or something else is permitting it — both make every other "
            "assertion in this file meaningless"
        )
    finally:
        restored = subprocess.run(
            ["kubectl", "--context", CONTEXT, "-n", NAMESPACE, "apply", "-f", str(POLICIES / "allow-dns.yaml")],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert restored.returncode == 0, restored.stderr
        assert _converges(probe, expected=True) is not None, "the cluster was left without DNS"


def test_prometheus_scrapes_the_pod_through_the_monitoring_role(probe: str) -> None:
    """The ingress half, and what the namespace role contract is for.

    `allow-serving-ingress` admits 8000 from namespaces carrying the monitoring
    role. Before that contract existed it named `app.kubernetes.io/name:
    monitoring`, which nothing carried — so the pod advertised a scrape the
    cluster refused, and no series ever arrived.
    """
    address = _kubectl(
        "get", "pod", "-l", "app=demand-forecast", "-o", "jsonpath={.items[0].status.podIP}"
    ).stdout.strip()
    assert address, "no serving pod found — run `make local-serve`"

    deadline = time.monotonic() + PROPAGATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        scrape = _kubectl(
            "exec",
            "deploy/prometheus",
            "-c",
            "prometheus",
            "--",
            "timeout",
            "6",
            "wget",
            "-q",
            "-O-",
            f"http://{address}:8000/metrics",
            namespace=MONITORING_NAMESPACE,
        )
        if scrape.returncode == 0 and "# HELP" in scrape.stdout:
            return
        time.sleep(5)
    pytest.fail(
        f"Prometheus could not scrape {address}:8000 within {PROPAGATION_TIMEOUT_SECONDS}s. The pod "
        f"advertises the scrape and the policy must admit it from the monitoring role"
    )
