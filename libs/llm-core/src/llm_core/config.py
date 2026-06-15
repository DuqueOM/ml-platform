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

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Repository root (…/agent-local). ``core`` lives one level below it.
REPO_ROOT = Path(__file__).resolve().parent.parent
USECASES_ROOT = REPO_ROOT / "usecases"


@dataclass(frozen=True)
class PolicyRules:
    """Deterministic policy-gate inputs, sourced from use-case config.

    The policy *engine* is generic (``core/policy.py``); the *rules* are data.
    """

    product_keywords: list[str] = field(default_factory=list)
    stock_claim_words: list[str] = field(default_factory=list)
    price_keywords: list[str] = field(default_factory=list)
    illegal_promises: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UsecaseConfig:
    """Immutable contract describing a single agent use-case.

    Attributes:
        name: Use-case identifier (matches the folder name).
        root: Absolute path to ``usecases/<name>/``.
        language: ISO language code of the customer-facing surface.
        allowed_intents: Closed set of intents the router may emit.
        tier_endpoints: Map of tier number to llama.cpp completions URL.
        router_prompt: System prompt for the Tier-0 router.
        router_grammar: GBNF grammar constraining the router JSON.
        budgets: Per-intent request budgets (raw dict, typed by RequestBudget).
        policy_rules: Deterministic policy-gate rule data.
        prompts: Agent prompt templates (plan/generate/reflect/critic).
        retrieval_dir: Directory of ``*.md`` docs indexed by BM25.
        fixtures_dir: Directory of JSON fixtures used by the use-case tools.
    """

    name: str
    root: Path
    language: str
    allowed_intents: list[str]
    tier_endpoints: dict[int, str]
    router_prompt: str
    router_grammar: str
    budgets: dict
    policy_rules: PolicyRules
    prompts: dict[str, str]
    retrieval_dir: Path
    fixtures_dir: Path


def load_usecase(name: str) -> UsecaseConfig:
    """Load a use-case configuration by name.

    Args:
        name: Folder name under ``usecases/`` (e.g. ``"tienda"``).

    Returns:
        A fully-populated, immutable :class:`UsecaseConfig`.

    Raises:
        FileNotFoundError: If the use-case folder or its ``config.yaml`` is
            missing, or if a referenced prompt/grammar file does not exist.
    """
    root = USECASES_ROOT / name
    if not root.is_dir():
        raise FileNotFoundError(f"Use-case folder not found: {root}")

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

    policy_raw = raw.get("policy", {})
    policy_rules = PolicyRules(
        product_keywords=policy_raw.get("product_keywords", []),
        stock_claim_words=policy_raw.get("stock_claim_words", []),
        price_keywords=policy_raw.get("price_keywords", []),
        illegal_promises=policy_raw.get("illegal_promises", []),
    )

    # Tier endpoint keys come from YAML as ints already, but normalise to be safe.
    tier_endpoints = {int(k): v for k, v in raw.get("tier_endpoints", {}).items()}

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
    )
