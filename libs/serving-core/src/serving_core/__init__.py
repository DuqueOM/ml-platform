"""What this platform adds AROUND a generated service.

Shared metric names, OpenTelemetry wiring, and the health contract the
platform's observability expects. Deliberately NOT the serving loop itself —
that comes from ``ml-service-template`` (ADR-003). If the serving loop appears
here, the boundary has failed.
"""

__version__ = "0.1.0"
