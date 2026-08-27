"""Shared doubles and the wired agent, for the use-case that owns the content.

These tests came from `agent-local` with the code they exercise. What changed
is how the agent is built: `store_agent` resolved a use-case by name
through the library, and ADR-001 does not let a library know that projects
exist. The project passes its own directory instead, which is both the fix and
a better statement of what a use-case is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from llm_core import build_agent, load_usecase
from store_assistant import USECASE_ROOT, build_registry


class TierResolutionStub:
    """Gives a tier-client double the resolution half of the client contract.

    Since ADR-011 the controller asks the tier client to collapse a requested
    tier onto the topology that is actually configured before consulting the
    circuit breaker. A double has no topology, so it resolves every tier to
    itself — leaving existing call/tier assertions meaningful.
    """

    def resolve(self, tier: int) -> tuple[int, None]:
        """Identity resolution: the requested tier is the effective tier."""
        return tier, None


@pytest.fixture(autouse=True)
def _isolate_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may write to the repository's `ops/` directory."""
    monkeypatch.setenv("AGENT_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))


@pytest.fixture
def store_agent() -> Any:
    """The agent this project ships, wired from its own configuration."""
    config = load_usecase(USECASE_ROOT)
    return build_agent(config, build_registry(config))
