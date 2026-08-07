"""One correlated trace across ingest, validation and training.

ADR-004 justifies OpenTelemetry with a specific artifact, not a general
principle: *one correlated trace from request through feature lookup to
inference is what proves the system is observable rather than merely
instrumented.* The distinction matters, because emitting spans is easy and
emitting spans that share a trace id across stage boundaries is the part that
actually answers "where did the time go, and on which run".

So the unit of value here is the TRACE, not the span. `pipeline_run` opens one
parent span and every stage nests under it; `test_tracing.py` asserts the three
stages share a trace id, because three unrelated traces would look identical in
a log and be useless in Jaeger.

**Absent collector is not an error.** `configure_tracing` falls back to a no-op
provider when nothing is listening, so a unit test, a CI job and a laptop
without the local stack all run unchanged. A library that refuses to work
without a collector gets wrapped in a try/except by its first caller, and then
nothing is instrumented anywhere.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "demand-forecast"

#: Where spans go. Defaults to the host mapping declared in kind-cluster.yaml;
#: in cluster it is the collector service, in cloud the managed endpoint. Only
#: the endpoint changes, which is the property that makes the local stack worth
#: having (ADR-004).
DEFAULT_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:14317")


@dataclass(frozen=True)
class TracingSetup:
    """What tracing was actually configured, reported rather than assumed.

    Attributes:
        enabled: Whether spans will reach a collector.
        endpoint: Where they were sent, when enabled.
        reason: Why it is disabled, when it is. A silent no-op is the failure
            mode that has an operator staring at an empty Jaeger for an hour.
    """

    enabled: bool
    endpoint: str | None = None
    reason: str | None = None

    def __str__(self) -> str:
        return f"tracing -> {self.endpoint}" if self.enabled else f"tracing disabled ({self.reason})"


def _reachable(endpoint: str, timeout: float = 1.0) -> bool:
    """Whether something is listening, checked BEFORE spans are buffered.

    The OTLP gRPC exporter is happy to accept spans for an endpoint that does
    not exist and retries in the background, so the process exits reporting
    success with every span dropped. Checking first turns that into a fact the
    caller can print.
    """
    parsed = urlparse(endpoint if "//" in endpoint else f"//{endpoint}")
    host, port = parsed.hostname or "localhost", parsed.port or 4317
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def configure_tracing(endpoint: str | None = None, *, require: bool = False) -> TracingSetup:
    """Point the tracer at a collector, or fall back to a no-op.

    Args:
        endpoint: OTLP gRPC endpoint. Defaults to :data:`DEFAULT_ENDPOINT`.
        require: Raise instead of falling back. For the integration test that
            exists to prove the trace arrives — there, a silent no-op would
            make the test pass while proving nothing.

    Returns:
        A :class:`TracingSetup` naming what happened.

    Raises:
        RuntimeError: If ``require`` and no collector is listening.
    """
    target = endpoint or DEFAULT_ENDPOINT

    if not _reachable(target):
        if require:
            raise RuntimeError(f"no OTLP collector at {target}; start the local stack with `make local-up`")
        return TracingSetup(enabled=False, reason=f"nothing listening at {target}")

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=target, insecure=True)))
    trace.set_tracer_provider(provider)
    return TracingSetup(enabled=True, endpoint=target)


def tracer() -> trace.Tracer:
    """The tracer for this service. A no-op one when nothing is configured."""
    return trace.get_tracer(SERVICE_NAME)


@contextmanager
def pipeline_run(run_id: str, **attributes: str | int | float) -> Iterator[trace.Span]:
    """The parent span every stage nests under.

    Correlation is the whole point: three stages emitting three unrelated
    traces produce the same log lines and answer none of the questions a trace
    exists for. Attributes go on the PARENT so a filter finds the run, not one
    of its stages.
    """
    with tracer().start_as_current_span("pipeline.run") as span:
        span.set_attribute("pipeline.run_id", run_id)
        for key, value in attributes.items():
            span.set_attribute(f"pipeline.{key}", value)
        yield span


@contextmanager
def stage(name: str, **attributes: str | int | float) -> Iterator[trace.Span]:
    """One pipeline stage, nested under whatever span is current.

    Attributes are set on the way OUT as well as in, because the interesting
    numbers — rows written, skill, coverage — are only known once the stage has
    run, and a span recording only its inputs describes an intention.
    """
    with tracer().start_as_current_span(f"pipeline.{name}") as span:
        for key, value in attributes.items():
            span.set_attribute(f"{name}.{key}", value)
        yield span


def flush(timeout_millis: int = 5000) -> bool:
    """Force-export buffered spans, returning whether the flush completed.

    `BatchSpanProcessor` exports on a timer, so a short-lived process — every
    pipeline step, every test — exits with its spans still in the buffer. This
    is the line whose absence produces an empty Jaeger and a long afternoon.
    """
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    return bool(force_flush(timeout_millis)) if force_flush else False
