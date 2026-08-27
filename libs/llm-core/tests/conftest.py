"""Shared test fixtures and doubles.

Telemetry isolation: every test redirects the decision-telemetry sink to a
temporary file via ``AGENT_TELEMETRY_PATH`` so the suite never writes to the
repo's ``ops/`` directory.
"""

from pathlib import Path

import pytest
import yaml
from llm_core import Agent, ToolRegistry, build_agent, load_usecase


class TierResolutionStub:
    """Gives a tier-client double the resolution half of the client contract.

    Since ADR-011 the controller asks the tier client to collapse a requested
    tier onto the topology that is actually configured before consulting the
    circuit breaker. A double has no topology, so it resolves every tier to
    itself — leaving existing call/tier assertions meaningful.

    Inherit this in every ``FakeTiers``; that keeps the four doubles in the
    suite from drifting away from the client contract one file at a time.
    """

    def resolve(self, tier: int) -> tuple[int, None]:
        """Identity resolution: the requested tier is the effective tier."""
        return tier, None


@pytest.fixture(autouse=True)
def _isolate_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TELEMETRY_PATH", str(tmp_path / "telemetry.jsonl"))


# --- a use-case the library can be tested against without knowing a domain ---


@pytest.fixture
def probe_usecase(tmp_path: Path) -> Path:
    """A minimal, synthetic use-case directory.

    The source repository's tests wired their agent with `load_agent("tienda")`
    — the store use-case — because the library resolved use-cases from the
    repository layout. Neither half of that survives ADR-001's boundary: a
    library must not know where projects live, and its tests must not depend on
    one existing.

    Nothing here is domain content. Every test that used `tienda` used it only
    to obtain a wired agent whose parts it then replaced with doubles, so a
    synthetic use-case measures exactly what those tests were measuring, and
    measures it without a project.
    """
    root = tmp_path / "usecases" / "probe"
    (root / "prompts").mkdir(parents=True)
    (root / "grammars").mkdir()
    (root / "policies").mkdir()
    (root / "docs").mkdir()
    (root / "prompts" / "router.md").write_text("route it", encoding="utf-8")
    (root / "grammars" / "route.gbnf").write_text("root ::= object", encoding="utf-8")
    (root / "docs" / "note.md").write_text("A document the retrieval tool can index.\n", encoding="utf-8")
    # Rules are DATA and belong to the project; the engine is generic. So the
    # probe carries the file's SHAPE with empty keyword lists — enough for the
    # gate to run, carrying no domain. Omitting it left the tone thresholds at
    # their defaults and the judge rejected every answer, which read as a
    # verifier bug and was a missing fixture.
    (root / "policies" / "policy.yaml").write_text(
        yaml.safe_dump(
            {
                "version": "1.0.0",
                "product_keywords": [],
                "stock_claim_words": [],
                "price_keywords": [],
                "illegal_promises": [],
                "promo_keywords": [],
                "unavailable_words": [],
                "max_caps_ratio": 0.9,
                "max_exclamation_runs": 3,
            }
        ),
        encoding="utf-8",
    )
    (root / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "probe",
                "allowed_intents": ["smalltalk", "lookup", "unknown"],
                "phase": 1,
                # The four-tier shape ADR-011 describes — one local router and
                # three remote reasoning tiers — because that TOPOLOGY is
                # platform structure, not domain content. A single-tier probe
                # made every escalation resolve back to tier 0, and six
                # verification tests failed for a reason that was about the
                # fixture rather than the code.
                "tier_endpoints": {
                    0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "gpu", "weights_gb": 1.0},
                    1: {"url": "http://127.0.0.1:8092/v1", "kind": "remote", "model": "probe-mid"},
                    2: {"url": "http://127.0.0.1:8093/v1", "kind": "remote", "model": "probe-main"},
                    3: {"url": "http://127.0.0.1:8094/v1", "kind": "remote", "model": "probe-verify"},
                },
                "retrieval": {"dir": "docs"},
                # Cross-tier verification is platform behaviour (ADR-004), so
                # the probe declares it: without the block, four verification
                # tests failed against a default that disables the judge.
                "verification": {
                    "enabled": True,
                    "judge_tier_offset": 1,
                    "self_consistency_k": 1,
                    "self_consistency_high_only": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def probe_agent(probe_usecase: Path) -> Agent:
    """A wired agent over the synthetic use-case, with an empty tool registry.

    `build_agent` replaces the source repository's `load_agent(name)`, which
    imported `usecases.<name>` through `importlib`. The registry is the
    caller's to supply, which is the whole point of the inversion.
    """
    return build_agent(load_usecase(probe_usecase), ToolRegistry())
