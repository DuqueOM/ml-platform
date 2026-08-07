"""Tracing must correlate, and must not require a collector to exist.

ADR-004 justifies OpenTelemetry with an artifact rather than a principle: one
correlated trace across stage boundaries. Emitting spans is easy; emitting
spans that share a trace id is the part that answers "where did the time go on
which run", so the tests assert correlation, not span count.

The unit tests here need no collector. The round trip through a real one is
`test_a_real_trace_reaches_jaeger`, marked `local`, and it is the only place
that proves a span actually leaves the process.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.request
import uuid

import pytest
from demand_forecast.tracing import (
    configure_tracing,
    flush,
    pipeline_run,
    stage,
)

JAEGER_API = "http://localhost:16686/api/traces"
OTLP_ENDPOINT = "http://localhost:14317"


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


# --- works without a collector ----------------------------------------------


def test_an_absent_collector_disables_tracing_instead_of_raising() -> None:
    """A library that refuses to run without a collector gets wrapped in a
    try/except by its first caller, and then nothing is instrumented anywhere.
    """
    setup = configure_tracing("http://127.0.0.1:9", require=False)

    assert not setup.enabled
    assert setup.reason is not None
    assert "9" in setup.reason


def test_the_absence_is_reported_not_silent() -> None:
    """A silent no-op is what has an operator staring at an empty Jaeger."""
    setup = configure_tracing("http://127.0.0.1:9", require=False)
    assert "disabled" in str(setup)


def test_require_raises_rather_than_pretending() -> None:
    """The integration test needs this: a silent no-op would pass and prove nothing."""
    with pytest.raises(RuntimeError, match="no OTLP collector"):
        configure_tracing("http://127.0.0.1:9", require=True)


def test_spans_nest_under_one_trace_without_any_collector() -> None:
    """Correlation is a property of the SDK, testable with no network at all."""
    ids = []
    with pipeline_run("unit-test") as parent:
        ids.append(parent.get_span_context().trace_id)
        for name in ("read", "validate", "backtest"):
            with stage(name) as child:
                ids.append(child.get_span_context().trace_id)

    assert len(set(ids)) == 1, f"stages emitted {len(set(ids))} traces; they must share one"


def test_flush_is_safe_when_nothing_is_configured() -> None:
    """Every pipeline step calls it; it must never be the thing that fails."""
    assert flush(1000) in (True, False)


# --- the round trip, which is the only proof a span leaves the process ------


@pytest.mark.local
@pytest.mark.skipif(not _listening(16686), reason="local stack not running — run `make local-up`")
def test_a_real_trace_reaches_jaeger() -> None:
    """Export a trace and read it back from Jaeger's API.

    The assertion that matters is the single trace id. Four spans arriving as
    four separate traces would look identical in any log and be useless for the
    question a trace exists to answer.
    """
    if not _listening(14317):
        pytest.skip("OTLP not reachable on 14317; needs the port mapping or `kubectl port-forward`")

    configure_tracing(OTLP_ENDPOINT, require=True)
    run_id = f"test-{uuid.uuid4().hex[:8]}"

    with pipeline_run(run_id, seed=1) as parent:
        for name in ("read", "validate", "backtest"):
            with stage(name, rows=1):
                pass
        trace_id = format(parent.get_span_context().trace_id, "032x")

    assert flush(10_000), "spans were still buffered; a short-lived process would drop them"
    time.sleep(4)

    with urllib.request.urlopen(f"{JAEGER_API}/{trace_id}", timeout=15) as response:
        payload = json.load(response)

    spans = payload["data"][0]["spans"]
    assert len(spans) == 4, f"expected the parent plus three stages, got {len(spans)}"
    assert len({span["traceID"] for span in spans}) == 1, "the stages did not correlate"

    names = {span["operationName"] for span in spans}
    assert names == {"pipeline.run", "pipeline.read", "pipeline.validate", "pipeline.backtest"}

    parent_tags = next(
        {tag["key"]: tag["value"] for tag in span["tags"]} for span in spans if span["operationName"] == "pipeline.run"
    )
    assert parent_tags["pipeline.run_id"] == run_id, "the run id is not on the parent span"
