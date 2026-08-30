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

from pathlib import Path
from typing import Any

import pytest
import yaml
from llm_core.config import expand_env, load_usecase

# Every remote tier variable the shipped use-case reads. Tests clear them so a
# developer's real .env can never make an assertion pass or fail by accident.
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


def _write_usecase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tier_endpoints: dict[int, dict[str, Any]],
    limits: dict[str, Any] | None = None,
) -> Path:
    """Materialise a minimal use-case so invariants can be tested in isolation.

    Returns the directory: `load_usecase` takes a path now, because the library
    stopped resolving use-cases by name against a repository layout it had no
    business knowing (ADR-001).
    """
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
    return root


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


def test_second_local_tier_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two resident models is the failure this invariant exists to prevent.

    A workstation cannot hold two quantised models; without this gate the
    overcommit is discovered by the OOM killer mid-request instead of by a
    config error at boot.
    """
    root = _write_usecase(
        tmp_path,
        monkeypatch,
        {
            0: {"url": "http://127.0.0.1:8091/v1", "kind": "local"},
            1: {"url": "http://127.0.0.1:8092/v1", "kind": "local"},
        },
    )

    with pytest.raises(ValueError, match="max_local_tiers"):
        load_usecase(root)


def test_extra_local_tiers_allowed_when_the_cap_is_raised_deliberately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_usecase(
        tmp_path,
        monkeypatch,
        {
            0: {"url": "http://127.0.0.1:8091/v1", "kind": "local"},
            1: {"url": "http://127.0.0.1:8092/v1", "kind": "local"},
        },
        limits={"max_local_tiers": 2},
    )

    config = load_usecase(root)

    assert config.local_tiers == [0, 1]


def test_weights_exceeding_the_device_budget_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The measured failure: a 5.0 GiB model placed on a 4.0 GiB CPU budget.

    This is what a container running `-ngl 99` with no GPU reservation
    actually does — llama.cpp falls back to CPU and the host swaps. Counting
    resident tiers cannot catch it, because the count is still one.
    """
    root = _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "cpu", "weights_gb": 5.0}},
        limits={"memory_budget_gb": {"gpu": 5.8, "cpu": 4.0}},
    )

    with pytest.raises(ValueError, match=r"5\.0 GiB of weights on device 'cpu'"):
        load_usecase(root)


def test_same_weights_fit_on_the_gpu_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical model, different device, different verdict — the whole point."""
    root = _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "gpu", "weights_gb": 5.0}},
        limits={"memory_budget_gb": {"gpu": 5.8, "cpu": 4.0}},
    )

    config = load_usecase(root)

    assert config.tier_endpoints[0].device == "gpu"
    assert config.tier_endpoints[0].memory_pool == "gpu"


def test_device_budget_check_is_skipped_when_weights_are_undeclared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent `weights_gb` means "unknown", not "zero-cost" — but it must not
    block a use-case that has not measured its model yet."""
    root = _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "cpu"}},
        limits={"memory_budget_gb": {"cpu": 4.0}},
    )

    assert load_usecase(root).tier_endpoints[0].weights_gb == 0.0


def test_unknown_device_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_usecase(
        tmp_path,
        monkeypatch,
        {0: {"url": "http://127.0.0.1:8091/v1", "kind": "local", "device": "tpu"}},
    )

    with pytest.raises(ValueError, match="device must be one of"):
        load_usecase(root)


def test_missing_tier_zero_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier 0 is the router and the degradation floor — never optional."""
    root = _write_usecase(tmp_path, monkeypatch, {2: {"url": "http://127.0.0.1:8093/v1", "kind": "local"}})

    with pytest.raises(ValueError, match="no Tier 0 endpoint"):
        load_usecase(root)


# --- startup preflight ------------------------------------------------------
