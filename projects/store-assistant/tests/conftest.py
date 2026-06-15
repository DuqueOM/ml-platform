"""Shared test fixtures.

Telemetry isolation: every test redirects the decision-telemetry sink to a
temporary file via ``AGENT_TELEMETRY_PATH`` so the suite never writes to the
repo's ``ops/`` directory.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))
