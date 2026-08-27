"""Retrieval evaluation, a document corpus, a semantic index — and the agent core.

The agent platform ADR-002 describes has landed: tier routing, a deterministic
policy gate whose rules are versioned data, a fail-closed tool capability
contract, cross-tier verification, decision telemetry and per-tier circuit
breakers. This docstring named those before they existed and said so; it names
them now because they are here, and `git log history/agent-local` carries the
31 commits that built them.

Alongside them, the instrument Phase 1e needed: `retrieval_eval` (recall@k, MRR
and a lexical baseline allowed to win), `doc_corpus` (this repository's own
documentation, enumerated by git), and `semantic_index` (TF-IDF into truncated
SVD, seeded, offline).

**One adaptation is load-bearing and worth naming here.** The source
repository's `load_agent(name)` imported `usecases.<name>` at runtime — a
library importing a project by convention. ADR-001 forbids exactly that, and
`tests/test_dependency_direction.py` enforces it, so the wiring is inverted:
the caller builds its registry and hands it over. A library that cannot name a
use-case is the boundary the monorepo is for.

Prompts and domain policy content belong to the consuming project, never here.
"""

from __future__ import annotations

from llm_core.agent import Agent
from llm_core.config import UsecaseConfig, load_usecase
from llm_core.tools import ToolRegistry

__version__ = "0.2.0"

__all__ = ["Agent", "ToolRegistry", "UsecaseConfig", "build_agent", "load_usecase"]


def build_agent(config: UsecaseConfig, registry: ToolRegistry) -> Agent:
    """Wire an agent from a loaded configuration and the caller's tools.

    Replaces the source repository's `load_agent(name)`, which resolved
    `usecases.<name>` through `importlib` and therefore required this library
    to know that projects exist and where. The inversion is small and the
    boundary it restores is not: a tool registry is domain content, and domain
    content belongs to the project.

    Args:
        config: From :func:`load_usecase`, given the use-case directory.
        registry: The project's tools, already registered.

    Returns:
        A ready :class:`Agent`.
    """
    return Agent(config, registry)
