"""Business-agnostic agent platform core.

Phase 1 stack: FastAPI + Pydantic + httpx + BM25, multi-tier llama.cpp routing.

A use-case is loaded by name; the core wires the router, tier clients, tool
registry, retrieval index and policy gate from the use-case configuration.
"""

from __future__ import annotations

import importlib

from .agent import Agent
from .config import UsecaseConfig, load_usecase
from .tools import ToolRegistry

__version__ = "0.4.0"

__all__ = ["Agent", "UsecaseConfig", "ToolRegistry", "load_usecase", "load_agent"]


def load_agent(name: str) -> Agent:
    """Load a fully-wired :class:`Agent` for a use-case by name.

    The use-case package (``usecases.<name>``) must expose
    ``build_registry(config) -> ToolRegistry``.

    Args:
        name: Use-case folder/package name (e.g. ``"tienda"``).

    Returns:
        A ready-to-use :class:`Agent`.
    """
    config = load_usecase(name)
    module = importlib.import_module(f"usecases.{name}")
    if not hasattr(module, "build_registry"):
        raise AttributeError(f"usecases.{name} must expose build_registry(config) -> ToolRegistry")
    registry = module.build_registry(config)
    return Agent(config, registry)
