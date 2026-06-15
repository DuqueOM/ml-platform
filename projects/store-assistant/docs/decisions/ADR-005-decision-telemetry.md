# ADR-005: Decision telemetry as a contract (JSONL, PII-redacted, OTel-aligned)

- **Status**: Accepted
- **Date**: 2026-06-15
- **Deciders**: Project owner
- **Plan ref**: §F3

## Context

Without per-decision telemetry, every later improvement (prompts, verifier,
escalation thresholds, retrieval) is guesswork. We need a record of *why* each
request was routed, escalated, and approved — but it must not leak PII, must not
become a maintenance burden, and must not lock us into a vendor.

## Decision

1. **Telemetry is a contract, not a nicety**: every request emits exactly one
   `TelemetryEntry` (a Pydantic model in `core/schemas.py`). A request that
   cannot produce a valid entry is a bug, not a silent skip. The controller emits
   it in `release()` (the final phase), so success AND degraded paths are logged.
2. **PII redacted at write time, never after** (`core/telemetry.py`): emails and
   phone-like digit runs are scrubbed recursively before the JSONL line touches
   disk. The schema deliberately logs tool *names*, not tool payloads, so PII
   exposure is structurally minimal; redaction is defence-in-depth.
3. **OTel-aligned naming** (`trace_id` per request): adopting OpenTelemetry later
   is a transport swap, not a remodelling. Trigger to adopt: team > 1 or > 1 host.
4. **Shadow mode** (`shadow_sample_rate`, plan §F3.6): a fraction of requests
   record what a higher tier *would* route. The sampling decision and intended
   shadow tier are recorded now; the actual comparison call is gated behind model
   availability (deferred until the reasoning tiers run).
5. **Provenance for the F4 flywheel**: each entry carries
   `{source, reviewer, quarantine}`. Nothing leaves quarantine into a training
   set without batch human review (raw retained 30 days, curated indefinitely).
6. **Sink is calibrated**: a JSONL file (`ops/telemetry.jsonl`, gitignored), not
   a database or streaming pipeline. `AGENT_TELEMETRY_PATH` overrides the path
   (tests redirect to a tmp file for isolation).

## Consequences

**Positive**
- Data-driven refinement of prompts/verifier/escalation becomes possible.
- Privacy-safe by construction; auditable provenance.
- Cheap and local; OTel migration is a clean future step.

**Negative / costs**
- One file append per request (negligible at this scale; single-worker).
- Shadow comparison is only half-implemented until models run (documented).

## Alternatives considered

- **OpenTelemetry/OTLP now**: rejected — over-engineered for 1 host; naming is
  pre-aligned so adoption is a transport swap.
- **Log to a database**: rejected at this scale — JSONL + weekly offline analysis
  is sufficient (engineering calibration).
- **Redact in a later batch job**: rejected — violates "redact at write time".

## Revisit triggers

- Team > 1 or > 1 host → adopt OpenTelemetry (swap transport).
- Telemetry volume large / queries frequent → move to a columnar store.
- Reasoning tiers running → complete the shadow comparison call.
