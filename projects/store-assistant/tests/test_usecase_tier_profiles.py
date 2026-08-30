"""Tier-topology behaviour of the use-case's OWN committed configuration.

ADR-011: one config serves the local-only, hybrid and all-remote profiles, and
the environment decides which is active. These cases drive that through this
project's `config.yaml` — they are assertions about the configuration this
project ships, so they live with it. The profile MECHANISM is exercised against
a synthetic use-case in `libs/llm-core/tests/test_tier_topology.py`, which is
where a library's tests belong.
"""

from __future__ import annotations

import pytest
from llm_core.config import expand_env, load_usecase
from llm_core.tiers import MissingCredentialError
from store_assistant import USECASE_ROOT

_REMOTE_VARS = [f"AGENT_TIER{tier}_{suffix}" for tier in (1, 2, 3) for suffix in ("URL", "MODEL", "API_KEY")] + [
    "AGENT_TIER0_URL",
    "AGENT_TIER0_KIND",
    "AGENT_TIER0_MODEL",
    "AGENT_TIER0_API_KEY_ENV",
]


@pytest.fixture(autouse=True)
def _clean_topology_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _REMOTE_VARS:
        monkeypatch.delenv(var, raising=False)


def _enable_tier(monkeypatch: pytest.MonkeyPatch, tier: int, *, model: str = "provider-model-id") -> None:
    monkeypatch.setenv(f"AGENT_TIER{tier}_URL", f"https://provider.example/t{tier}/chat/completions")
    monkeypatch.setenv(f"AGENT_TIER{tier}_MODEL", model)
    monkeypatch.setenv(f"AGENT_TIER{tier}_API_KEY", "sk-test")


# --- environment expansion --------------------------------------------------


def test_expand_env_uses_value_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_VAR", "actual")
    assert expand_env("${SOME_VAR}") == "actual"
    assert expand_env("${SOME_VAR:-fallback}") == "actual"


def test_expand_env_falls_back_and_blanks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABSENT_VAR", raising=False)
    assert expand_env("${ABSENT_VAR:-fallback}") == "fallback"
    assert expand_env("${ABSENT_VAR}") == ""
    assert expand_env("prefix-${ABSENT_VAR:-x}-suffix") == "prefix-x-suffix"


def test_expand_env_leaves_plain_strings_alone() -> None:
    assert expand_env("http://127.0.0.1:8091/v1") == "http://127.0.0.1:8091/v1"


# --- profiles ---------------------------------------------------------------


def test_bare_environment_yields_local_only_profile() -> None:
    """No provider variables exported -> higher tiers drop out entirely.

    This is the profile a 16 GB workstation runs: one resident model, no
    credentials, and escalation that resolves downward instead of failing.
    """
    config = load_usecase(USECASE_ROOT)

    assert config.topology_profile == "local-only"
    assert sorted(config.tier_endpoints) == [0]
    assert config.local_tiers == [0]
    assert config.tier_endpoints[0].is_local


def test_exporting_provider_variables_yields_hybrid_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    for tier in (1, 2, 3):
        _enable_tier(monkeypatch, tier)

    config = load_usecase(USECASE_ROOT)

    assert config.topology_profile == "hybrid"
    assert sorted(config.tier_endpoints) == [0, 1, 2, 3]
    assert config.local_tiers == [0]  # the memory bill is still one model
    assert config.tier_endpoints[2].model == "provider-model-id"
    assert config.tier_endpoints[2].api_key_env == "AGENT_TIER2_API_KEY"


def test_partial_export_enables_only_the_configured_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tiers are independently switchable; a gap resolves down at call time."""
    _enable_tier(monkeypatch, 2)

    config = load_usecase(USECASE_ROOT)

    assert sorted(config.tier_endpoints) == [0, 2]
    assert config.topology_profile == "hybrid"


def test_all_remote_profile_has_no_resident_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TIER0_URL", "https://provider.example/t0/chat/completions")
    monkeypatch.setenv("AGENT_TIER0_KIND", "remote")
    monkeypatch.setenv("AGENT_TIER0_MODEL", "small-router-model")
    monkeypatch.setenv("AGENT_TIER0_API_KEY_ENV", "AGENT_TIER0_API_KEY")
    _enable_tier(monkeypatch, 2)

    config = load_usecase(USECASE_ROOT)

    assert config.topology_profile == "all-remote"
    assert config.local_tiers == []
    # GBNF is unavailable off llama.cpp — the router must fall back (ADR-011).
    assert config.tier_endpoints[0].supports_grammar is False


def test_remote_tiers_are_charged_to_no_device_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A remote tier costs tokens, not memory — it must not consume a budget."""
    _enable_tier(monkeypatch, 1)

    config = load_usecase(USECASE_ROOT)

    assert config.tier_endpoints[1].memory_pool is None
    assert config.tier_endpoints[0].memory_pool == "gpu"


def test_container_rehost_preserves_device_and_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLAMA_HOST rewrites the host only; losing `device` would silently
    disarm the budget check inside the container."""
    monkeypatch.setenv("LLAMA_HOST", "llama-e4b")

    endpoint = load_usecase(USECASE_ROOT).tier_endpoints[0]

    assert "llama-e4b" in endpoint.url
    assert endpoint.device == "gpu"
    assert endpoint.weights_gb == 4.95


def test_preflight_passes_when_credentials_are_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_tier(monkeypatch, 1)
    load_usecase(USECASE_ROOT).preflight()  # must not raise


def test_preflight_fails_when_a_declared_credential_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TIER1_URL", "https://provider.example/t1/chat/completions")
    monkeypatch.setenv("AGENT_TIER1_MODEL", "provider-model-id")
    monkeypatch.delenv("AGENT_TIER1_API_KEY", raising=False)

    config = load_usecase(USECASE_ROOT)  # loading stays pure — no credential needed

    with pytest.raises(MissingCredentialError, match="AGENT_TIER1_API_KEY"):
        config.preflight()


def test_local_only_profile_needs_no_credentials() -> None:
    load_usecase(USECASE_ROOT).preflight()  # must not raise
