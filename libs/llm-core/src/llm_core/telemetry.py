"""Decision telemetry — a CONTRACT, not a nicety (plan §F3).

Every request emits a :class:`core.schemas.TelemetryEntry` as one JSONL line.
Three hard rules (plan §F3):

1. **Telemetry is a contract**: a request that cannot produce a valid entry is a
   bug. The schema is validated by Pydantic before it is written.
2. **OTel-aligned naming** (``trace_id`` propagated): adopting OpenTelemetry later
   is a transport swap, not a remodelling.
3. **PII redacted at write time, never after**: :func:`redact_obj` scrubs known
   PII patterns from every string before the line touches disk.

The entry schema deliberately excludes raw customer text (it logs tool *names*,
not tool payloads), so PII exposure is structurally minimised; redaction is a
defence-in-depth safety net for anything that slips through (e.g. provenance).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schemas import TelemetryEntry

_REDACTED = "[REDACTED]"

# Conservative PII patterns. Order matters (email before phone-like digits).
_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # email
    re.compile(r"\+?\d[\d\s().-]{6,}\d"),  # phone / long digit runs (>= 8 digits)
]


# Machine-generated identifiers that are never PII. They contain digit runs
# (UUIDs, ISO timestamps, semver) that the phone pattern would otherwise mangle,
# which would destroy the very traceability the telemetry contract promises
# (ADR-005). They are excluded from redaction by key.
_SAFE_KEYS = frozenset({"trace_id", "decision_id", "policy_version", "ts"})


def redact(text: str) -> str:
    """Redact known PII patterns (emails, phone-like digit runs) from a string."""
    for pattern in _PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def redact_obj(obj):
    """Recursively redact PII from strings inside dicts/lists/scalars.

    String values under a key in :data:`_SAFE_KEYS` are passed through verbatim
    so machine-generated identifiers (trace_id, timestamps) are never corrupted.
    """
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: (v if k in _SAFE_KEYS else redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


class TelemetrySink:
    """Appends redacted :class:`TelemetryEntry` records as JSONL.

    Args:
        path: Destination file (created on first write). ``None`` disables disk
            output (the entry is still built and returned — useful in tests).
        enabled: Master switch; when ``False`` nothing is written.
    """

    def __init__(self, path: Path | None = None, enabled: bool = True):
        self.path = path
        self.enabled = enabled and path is not None

    def emit(self, entry: TelemetryEntry) -> dict:
        """Serialize, redact and (if enabled) append the entry. Returns the dict."""
        record = redact_obj(entry.model_dump(mode="json"))
        if self.enabled and self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
