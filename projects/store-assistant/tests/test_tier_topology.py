"""Tier topology and resident-memory invariant (ADR-011).

These tests cover the config layer rather than the HTTP layer: which tiers a
given environment ends up with, whether the resident-memory cap is enforced,
and whether a serving process refuses to boot without the credentials its
topology needs.

The controlling idea is that ONE committed use-case config must serve every
profile. The environment — not a YAML edit — decides whether the deployment is
local-only, hybrid or all-remote, so these tests drive `load_usecase` through
`monkeypatch.setenv` exactly as a deployment would.
"""

from __future__ import annotations

import pytest
import yaml

from core.config import expand_env, load_usecase
from core.tiers import MissingCredential

# Every remote tier variable the shipped use-case reads. Tests clear them so a
# developer's real .env can never make an assertion pass or fail by accident.
_REMOTE_VARS = [f"AGENT_TIER{tier}_{suffix}" for tier in (1, 2, 3) for suffix in ("URL", "MODEL", "API_KEY")] + [
    "AGENT_TIER0_URL",
    "AGENT_TIER0_KIND",
    "AGENT_TIER0_MODEL",
    "AGENT_TIER0_API_KEY_ENV",
]


@pytest.fixture(autouse=True)
def _clean_topology_env(monkeypatch):
    for var in _REMOTE_VARS:
        monkeypatch.delenv(var, raising=False)


def _enable_tier(monkeypatch, tier: int, *, model: str = "provider-model-id") -> None:
    monkeypatch.setenv(f"AGENT_TIER{tier}_URL", f"https://provider.example/t{tier}/chat/completions")
    monkeypatch.setenv(f"AGENT_TIER{tier}_MODEL", model)
    monkeypatch.setenv(f"AGENT_TIER{tier}_API_KEY", "sk-test")


# --- environment expansion --------------------------------------------------


def test_expand_env_uses_value_then_default(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "actual")
    assert expand_env("${SOME_VAR}") == "actual"
    assert expand_env("${SOME_VAR:-fallback}") == "actual"


def test_expand_env_falls_back_and_blanks(monkeypatch):
    monkeypatch.delenv("ABSENT_VAR", raising=False)
    assert expand_env("${ABSENT_VAR:-fallback}") == "fallback"
    assert expand_env("${ABSENT_VAR}") == ""
    assert expand_env("prefix-${ABSENT_VAR:-x}-suffix") == "prefix-x-suffix"


def test_expand_env_leaves_plain_strings_alone():
    assert expand_env("http://127.0.0.1:8091/v1") == "http://127.0.0.1:8091/v1"


# --- profiles ---------------------------------------------------------------


def test_bare_environment_yields_local_only_profile():
    """No provider variables exported -> higher tiers drop out entirely.

    This is the profile a 16 GB workstation runs: one resident model, no
    credentials, and escalation that resolves downward instead of failing.
    """
    config = load_usecase("tienda")

    assert config.topology_profile == "local-only"
    assert sorted(config.tier_endpoints) == [0]
    assert config.local_tiers == [0]
    assert config.tier_endpoints[0].is_local


def test_exporting_provider_variables_yields_hybrid_profile(monkeypatch):
    for tier in (1, 2, 3):
        _enable_tier(monkeypatch, tier)

    config = load_usecase("tienda")

    assert config.topology_profile == "hybrid"
    assert sorted(config.tier_endpoints) == [0, 1, 2, 3]
    assert config.local_tiers == [0]  # the memory bill is still one model
    assert config.tier_endpoints[2].model == "provider-model-id"
    assert config.tier_endpoints[2].api_key_env == "AGENT_TIER2_API_KEY"


def test_partial_export_enables_only_the_configured_tiers(monkeypatch):
    """Tiers are independently switchable; a gap resolves down at call time."""
    _enable_tier(monkeypatch, 2)

    config = load_usecase("tienda")

    assert sorted(config.tier_endpoints) == [0, 2]
    assert config.topology_profile == "hybrid"


def test_all_remote_profile_has_no_resident_model(monkeypatch):
    monkeypatch.setenv("AGENT_TIER0_URL", "https://provider.example/t0/chat/completions")
    monkeypatch.setenv("AGENT_TIER0_KIND", "remote")
    monkeypatch.setenv("AGENT_TIER0_MODEL", "small-router-model")
    monkeypatch.setenv("AGENT_TIER0_API_KEY_ENV", "AGENT_TIER0_API_KEY")
    _enable_tier(monkeypatch, 2)

    config = load_usecase("tienda")

    assert config.topology_profile == "all-remote"
    assert config.local_tiers == []
    # GBNF is unavailable off llama.cpp — the router must fall back (ADR-011).
    assert config.tier_endpoints[0].supports_grammar is False


def test_remote_tier_without_model_fails_at_load(monkeypatch):
    monkeypatch.setenv("AGENT_TIER1_URL", "https://provider.example/t1/chat/completions")
    monkeypatch.setenv("AGENT_TIER1_API_KEY", "sk-test")
    # AGENT_TIER1_MODEL deliberately unset

    with pytest.raises(ValueError, match="requires a 'model'"):
        load_usecase("tienda")


# --- resident-memory invariant ---------------------------------------------


def _write_usecase(tmp_path, monkeypatch, tier_endpoints: dict, limits: dict | None = None):
    """Materialise a minimal use-case so invariants can be tested in isolation."""
    root = tmp_path / "usecases" / "probe"
    (root / "prompts").mkdir(parents=True)
    (root / "grammars").mkdir()
    (root / "policies").mkdir()
    (root / "data").mkdir()
    (root / "prompts" / "router.md").write_text("route it")
    (root / "grammars" / "route.gbnf").write_text("root ::= object")
    (root / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "probe",
                "allowed_intents": ["smalltalk"],
                "tier_endpoints": tier_endpoints,
                "limits": limits or {},
            }
        )
    )
    monkeypatch.setattr("core.config.USECASES_ROOT", tmp_path / "usecases")


def test_second_local_tier_is_rejected(tmp_path, monkeypatch):
    """Two resident models is the failure this invariant exists to prevent.

    A workstation cannot hold two quantised models; without this gate the
    overcommit is discovered by the OOM killer mid-request instead of by a
    config error at boot.
    """
    _write_usecase(
        tmp_path,
        monkeypatch,
        {
            0: {"url": "http://127.0.0.1:8091/v1", "kind": "local"},
            1: {"url": "http://127.0.0.1:8092/v1", "kind": "local"},
        },
    )

    with pytest.raises(ValueError, match="max_local_tiers"):
        load_usecase("probe")


def test_extra_local_tiers_allowed_when_the_cap_is_raised_deliberately(tmp_path, monkeypatch):
    _write_usecase(
        tmp_path,
        monkeypatch,
        {
            0: {"url": "http://127.0.0.1:8091/v1", "kind": "local"},
            1: {"url": "http://127.0.0.1:8092/v1", "kind": "local"},
        },
        limits={"max_local_tiers": 2},
    )

    config = load_usecase("probe")

    assert config.local_tiers == [0, 1]


def test_weights_exceeding_the_device_budget_are_rejected(tmp_path, monkeypatch):
    """The measured failure: a 5.0 GiB model placed on a 4.0 GiB CPU budget.

    This is what a container running `-ngl 99` with no GPU reservation
    actually does — llama.cpp falls back to CPU and the host swaps. Counting
    resident tiers cannot catch it, because the count is still one.
    """
    _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "cpu", "weights_gb": 5.0}},
        limits={"memory_budget_gb": {"gpu": 5.8, "cpu": 4.0}},
    )

    with pytest.raises(ValueError, match=r"5\.0 GiB of weights on device 'cpu'"):
        load_usecase("probe")


def test_same_weights_fit_on_the_gpu_budget(tmp_path, monkeypatch):
    """Identical model, different device, different verdict — the whole point."""
    _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "gpu", "weights_gb": 5.0}},
        limits={"memory_budget_gb": {"gpu": 5.8, "cpu": 4.0}},
    )

    config = load_usecase("probe")

    assert config.tier_endpoints[0].device == "gpu"
    assert config.tier_endpoints[0].memory_pool == "gpu"


def test_device_budget_check_is_skipped_when_weights_are_undeclared(tmp_path, monkeypatch):
    """Absent `weights_gb` means "unknown", not "zero-cost" — but it must not
    block a use-case that has not measured its model yet."""
    _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "cpu"}},
        limits={"memory_budget_gb": {"cpu": 4.0}},
    )

    assert load_usecase("probe").tier_endpoints[0].weights_gb == 0.0


def test_unknown_device_is_rejected(tmp_path, monkeypatch):
    _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "tpu"}},
    )

    with pytest.raises(ValueError, match="device must be one of"):
        load_usecase("probe")


def test_remote_tiers_are_charged_to_no_device_budget(monkeypatch):
    """A remote tier costs tokens, not memory — it must not consume a budget."""
    _enable_tier(monkeypatch, 1)

    config = load_usecase("tienda")

    assert config.tier_endpoints[1].memory_pool is None
    assert config.tier_endpoints[0].memory_pool == "gpu"


def test_container_rehost_preserves_device_and_weights(monkeypatch):
    """LLAMA_HOST rewrites the host only; losing `device` would silently
    disarm the budget check inside the container."""
    monkeypatch.setenv("LLAMA_HOST", "llama-e4b")

    endpoint = load_usecase("tienda").tier_endpoints[0]

    assert "llama-e4b" in endpoint.url
    assert endpoint.device == "gpu"
    assert endpoint.weights_gb == 4.95


def test_missing_tier_zero_is_rejected(tmp_path, monkeypatch):
    """Tier 0 is the router and the degradation floor — never optional."""
    _write_usecase(tmp_path, monkeypatch, {2: {"url": "http://127.0.0.1:8093/v1", "kind": "local"}})

    with pytest.raises(ValueError, match="no Tier 0 endpoint"):
        load_usecase("probe")


# --- startup preflight ------------------------------------------------------


def test_preflight_passes_when_credentials_are_present(monkeypatch):
    _enable_tier(monkeypatch, 1)
    load_usecase("tienda").preflight()  # must not raise


def test_preflight_fails_when_a_declared_credential_is_absent(monkeypatch):
    monkeypatch.setenv("AGENT_TIER1_URL", "https://provider.example/t1/chat/completions")
    monkeypatch.setenv("AGENT_TIER1_MODEL", "provider-model-id")
    monkeypatch.delenv("AGENT_TIER1_API_KEY", raising=False)

    config = load_usecase("tienda")  # loading stays pure — no credential needed

    with pytest.raises(MissingCredential, match="AGENT_TIER1_API_KEY"):
        config.preflight()


def test_local_only_profile_needs_no_credentials():
    load_usecase("tienda").preflight()  # must not raise
