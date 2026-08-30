"""Use-case configuration loader.

The platform core is business-agnostic. Everything domain-specific (router
prompt, output grammar, tier endpoints, per-intent budgets, policy rules and
the agent prompt templates) lives in a use-case directory under ``usecases/``
and is loaded into an immutable :class:`UsecaseConfig` at startup.

This is the seam that turns the Phase 1 store assistant into a reusable
platform: a new domain is a new ``usecases/<name>/`` folder plus its tools,
never a fork of ``core/``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from .tiers import LOCAL, REMOTE, TierEndpoint

# Repository root (…/agent-local). ``core`` lives one level below it.
# No `USECASES_ROOT`. The source repository resolved use-cases against its own
# layout — `REPO_ROOT / "usecases" / name` — which made this library know where
# projects live. ADR-001 places that squarely on the wrong side of the boundary
# (`llm-core` must not know a feature name, let alone a directory tree), and
# `tests/test_dependency_direction.py` enforces it: a library reaching into
# `projects/` is the coupling the monorepo exists to prevent.
#
# So the caller passes the directory. That is also what makes the library
# testable without a domain: the tests here build a synthetic use-case in a
# temporary directory rather than depending on whichever one happens to exist.

# ``${VAR}`` / ``${VAR:-default}`` substitution for endpoint URLs and model ids,
# so one committed config serves every topology profile (ADR-011) and no
# deployment-specific value has to be edited into version control.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: str) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` references in a config string.

    An unset variable with no default expands to the empty string, which the
    endpoint validators then reject with a precise message.
    """

    def _sub(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return os.environ.get(name) or (default if default is not None else "")

    return _ENV_REF.sub(_sub, value)


@dataclass(frozen=True)
class PolicyRules:
    """Deterministic policy-gate inputs, sourced from a versioned policy file.

    The policy *engine* is generic (``core/policy.py``); the *rules* are data
    (plan §F2.2). ``version`` is emitted on every verdict for the audit trail.
    """

    version: str = "0.0.0"
    product_keywords: list[str] = field(default_factory=list)
    stock_claim_words: list[str] = field(default_factory=list)
    price_keywords: list[str] = field(default_factory=list)
    illegal_promises: list[str] = field(default_factory=list)
    promo_keywords: list[str] = field(default_factory=list)
    unavailable_words: list[str] = field(default_factory=list)
    max_caps_ratio: float = 0.5
    max_exclamation_runs: int = 1


@dataclass(frozen=True)
class UsecaseConfig:
    """Immutable contract describing a single agent use-case.

    Attributes:
        name: Use-case identifier (matches the folder name).
        root: Absolute path to ``usecases/<name>/``.
        language: ISO language code of the customer-facing surface.
        allowed_intents: Closed set of intents the router may emit.
        tier_endpoints: Map of tier number to :class:`TierEndpoint` (ADR-011).
        router_prompt: System prompt for the Tier-0 router.
        router_grammar: GBNF grammar constraining the router JSON.
        budgets: Per-intent request budgets (raw dict, typed by RequestBudget).
        policy_rules: Deterministic policy-gate rule data.
        prompts: Agent prompt templates (plan/generate/reflect/critic).
        retrieval_dir: Directory of ``*.md`` docs indexed by BM25.
        fixtures_dir: Directory of JSON fixtures used by the use-case tools.
        verification: Cross-tier verifier settings (plan §F2.3): ``enabled``,
            ``judge_tier_offset``, ``self_consistency_k``,
            ``self_consistency_high_only``.
        telemetry: Decision-telemetry settings (plan §F3): ``enabled``, ``path``,
            ``source``, ``shadow_sample_rate``.
        tier_retry: Transient-failure retry settings for tier/router HTTP calls
            (``max_retries``, ``base_delay``, ``max_delay``, ``jitter``).
        phase: Lifecycle phase (1 = read-only fixtures). Drives the fail-closed
            tool phase gate via :attr:`read_only_mode`.
        observation_max_chars: Per-observation cap when injecting tool results
            into a prompt (bounds small-model context).
        retrieval_max_chars: Per-document cap for BM25 retrieval results.
        structured_tool_calls: When True (default), the planner is constrained to
            emit the schema-validated JSON tool-call envelope (ADR-007). Set to
            False only for a model server lacking ``json_schema`` support; the
            text-format fallback parser still works either way.
        max_local_tiers: Resident-memory invariant (ADR-011) — how many tiers
            may be ``kind: local`` at once. Enforced at load time.
    """

    name: str
    root: Path
    language: str
    allowed_intents: list[str]
    tier_endpoints: dict[int, TierEndpoint]
    router_prompt: str
    router_grammar: str
    budgets: dict[str, Any]
    policy_rules: PolicyRules
    prompts: dict[str, str]
    retrieval_dir: Path
    fixtures_dir: Path
    verification: dict[str, Any] = field(default_factory=dict[str, Any])
    telemetry: dict[str, Any] = field(default_factory=dict[str, Any])
    tier_retry: dict[str, Any] = field(default_factory=dict[str, Any])
    phase: int = 1
    observation_max_chars: int = 4000
    retrieval_max_chars: int = 2000
    structured_tool_calls: bool = True
    max_local_tiers: int = 1

    @property
    def read_only_mode(self) -> bool:
        """True while the use-case is read-only (Phase 1). Fail-closed default.

        The tool registry refuses to execute a non-read-only, non-dry-run tool
        while this holds (see ADR-006). Phase 2 (real mutating backends) sets
        ``phase: 2`` in ``config.yaml`` to lift the gate per tool contract.
        """
        return self.phase < 2

    @property
    def local_tiers(self) -> list[int]:
        """Tiers that consume local resident memory, ascending."""
        return sorted(tier for tier, ep in self.tier_endpoints.items() if ep.is_local)

    @property
    def topology_profile(self) -> str:
        """Name the ADR-011 profile this configuration represents.

        Returns:
            ``"local-only"`` (no remote tiers), ``"all-remote"`` (no local
            tiers) or ``"hybrid"`` (both).
        """
        has_local = bool(self.local_tiers)
        has_remote = any(not ep.is_local for ep in self.tier_endpoints.values())
        if has_local and not has_remote:
            return "local-only"
        if has_remote and not has_local:
            return "all-remote"
        return "hybrid"

    def preflight(self) -> None:
        """Fail fast if the process cannot actually serve this configuration.

        Checks what :func:`load_usecase` deliberately cannot: whether every
        credential a remote tier names is present in *this* environment.
        Config loading stays pure so tests and offline tooling can read a
        hybrid config without holding provider keys; serving entrypoints call
        this at startup so a missing key surfaces as a boot failure instead of
        a per-request degradation to the safe fallback.

        Raises:
            MissingCredentialError: If a remote tier's ``api_key_env`` is unset.
        """
        for tier in sorted(self.tier_endpoints):
            self.tier_endpoints[tier].auth_headers()


def load_usecase(root: Path) -> UsecaseConfig:
    """Load a use-case configuration from its directory.

    Args:
        root: The use-case directory, holding `config.yaml` and the prompt,
            grammar and policy files it names. Passed explicitly rather than
            resolved from a name — see the note where `USECASES_ROOT` used to
            be.

    Returns:
        A fully-populated, immutable :class:`UsecaseConfig`.

    Raises:
        FileNotFoundError: If the use-case folder or its ``config.yaml`` is
            missing, or if a referenced prompt/grammar file does not exist.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"Use-case folder not found: {root}")

    # The directory name still identifies the use-case in error messages — it
    # is what a reader recognises. What changed is that it is DERIVED from the
    # path the caller gave rather than used to find it.
    name = root.name

    config_path = root / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing use-case config: {config_path}")

    raw = yaml.safe_load(config_path.read_text())

    router_cfg = raw.get("router", {})
    prompt_file = root / router_cfg.get("prompt_file", "prompts/router.md")
    grammar_file = root / router_cfg.get("grammar_file", "grammars/route.gbnf")
    for required in (prompt_file, grammar_file):
        if not required.is_file():
            raise FileNotFoundError(f"Referenced file not found: {required}")

    budgets_file = root / raw.get("budgets_file", "budgets.yaml")
    budgets = yaml.safe_load(budgets_file.read_text()) if budgets_file.is_file() else {}

    retrieval_dir = root / raw.get("retrieval", {}).get("docs_dir", "policies")
    fixtures_dir = root / raw.get("fixtures_dir", "data")

    # Policy rules live in a versioned file (plan §F2.2); fall back to an inline
    # ``policy:`` block for use-cases that have not migrated yet.
    policy_file = root / raw.get("policy_file", "policies/policy.yaml")
    policy_raw = yaml.safe_load(policy_file.read_text()) if policy_file.is_file() else raw.get("policy", {})
    tone = policy_raw.get("tone", {})
    policy_rules = PolicyRules(
        version=policy_raw.get("version", "0.0.0"),
        product_keywords=policy_raw.get("product_keywords", []),
        stock_claim_words=policy_raw.get("stock_claim_words", []),
        price_keywords=policy_raw.get("price_keywords", []),
        illegal_promises=policy_raw.get("illegal_promises", []),
        promo_keywords=policy_raw.get("promo_keywords", []),
        unavailable_words=policy_raw.get("unavailable_words", []),
        max_caps_ratio=tone.get("max_caps_ratio", 0.5),
        max_exclamation_runs=tone.get("max_exclamation_runs", 1),
    )

    # Tier endpoint keys come from YAML as ints already, but normalise to be safe.
    # ``LLAMA_HOST`` lets containerised deployments retarget the default
    # 127.0.0.1 host (e.g. a sibling llama.cpp service) without editing config.
    # Only LOCAL endpoints are rewritten — a remote provider URL must never be
    # silently repointed at a container host.
    llama_host = os.environ.get("LLAMA_HOST")
    tier_endpoints: dict[int, TierEndpoint] = {}
    for key, spec in raw.get("tier_endpoints", {}).items():
        if isinstance(spec, dict):
            spec = {k: (expand_env(v) if isinstance(v, str) else v) for k, v in spec.items()}
            declared_url = str(spec.get("url", "")).strip()
        elif isinstance(spec, str):
            spec = expand_env(spec)
            declared_url = spec.strip()
        else:
            raise ValueError(f"tier {key} endpoint must be a URL string or a mapping, got {type(spec).__name__}")

        # A tier whose URL expands to nothing is *not configured* in this
        # environment — drop it rather than fail. This is what lets one
        # committed config serve every ADR-011 profile: with no provider
        # variables exported the higher tiers vanish and `TierClient.resolve`
        # collapses the topology onto Tier 0 (local-only).
        if not declared_url:
            continue

        endpoint = TierEndpoint.from_raw(spec)
        if llama_host and endpoint.is_local:
            rehosted = endpoint.url.replace("127.0.0.1", llama_host).replace("localhost", llama_host)
            endpoint = replace(endpoint, url=rehosted)
        tier_endpoints[int(key)] = endpoint

    # Tier 0 is the routing floor: every escalation resolves down to it and the
    # router binds to it directly, so its absence is never a valid topology.
    if 0 not in tier_endpoints:
        raise ValueError(
            f"use-case {name!r} has no Tier 0 endpoint after environment expansion. "
            "Tier 0 is required — it is the router and the degradation floor (ADR-011)."
        )

    # Resident-memory invariant (ADR-011). A workstation cannot hold several
    # GGUF models at once, so exceeding the cap is a configuration error, not a
    # runtime surprise discovered when the OOM killer fires.
    limits = raw.get("limits", {})
    max_local_tiers = int(limits.get("max_local_tiers", 1))
    local_tiers = sorted(tier for tier, ep in tier_endpoints.items() if ep.is_local)
    if len(local_tiers) > max_local_tiers:
        raise ValueError(
            f"use-case {name!r} declares {len(local_tiers)} local tiers {local_tiers} "
            f"but limits.max_local_tiers is {max_local_tiers} (ADR-011). "
            f"Switch the surplus tiers from kind: {LOCAL} to kind: {REMOTE}, "
            f"or raise limits.max_local_tiers deliberately."
        )

    # Per-device memory budget (ADR-012). Counting resident tiers is not enough:
    # the same model that fits in VRAM may not fit in system RAM, and the two
    # paths fail differently — VRAM overflow degrades to partial offload, system
    # RAM overflow swaps or invokes the OOM killer. Declaring weights and
    # budgets turns "it silently ran on the wrong device" into a load error.
    memory_budget_gb = {str(k).lower(): float(v) for k, v in (limits.get("memory_budget_gb") or {}).items()}
    charged: dict[str, float] = {}
    for tier in local_tiers:
        endpoint = tier_endpoints[tier]
        charged[endpoint.device] = charged.get(endpoint.device, 0.0) + endpoint.weights_gb
    for device, required in charged.items():
        budget = memory_budget_gb.get(device)
        if budget is not None and required > budget:
            raise ValueError(
                f"use-case {name!r} places {required:.1f} GiB of weights on device {device!r} "
                f"but limits.memory_budget_gb.{device} is {budget:.1f} GiB (ADR-012). "
                f"Move the tier to another device, use a smaller quantisation, "
                f"or raise the budget after re-measuring the machine."
            )

    return UsecaseConfig(
        name=raw.get("name", name),
        root=root,
        language=raw.get("language", "en"),
        allowed_intents=raw.get("allowed_intents", []),
        tier_endpoints=tier_endpoints,
        router_prompt=prompt_file.read_text(),
        router_grammar=grammar_file.read_text(),
        budgets=budgets,
        policy_rules=policy_rules,
        prompts=raw.get("prompts", {}),
        retrieval_dir=retrieval_dir,
        fixtures_dir=fixtures_dir,
        verification=raw.get("verification", {}),
        telemetry=raw.get("telemetry", {}),
        tier_retry=raw.get("tiers", {}).get("retry", {}),
        phase=int(raw.get("phase", 1)),
        observation_max_chars=int(raw.get("limits", {}).get("observation_chars", 4000)),
        retrieval_max_chars=int(raw.get("limits", {}).get("retrieval_chars", 2000)),
        structured_tool_calls=bool(raw.get("structured_tool_calls", True)),
        max_local_tiers=max_local_tiers,
    )
