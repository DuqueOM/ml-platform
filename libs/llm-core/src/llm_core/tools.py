"""Tool registry — the APP executes tools, the model only names them.

The registry mechanism is generic platform code. Concrete tools (inventory,
pricing, orders, …) live in the use-case package and register themselves
against a :class:`ToolRegistry` instance.
"""
from __future__ import annotations

from typing import Callable

from .schemas import Observation, ToolCall


class ToolRegistry:
    """A named collection of callable tools returning :class:`Observation`.

    Each use-case owns one registry, keeping tool namespaces isolated.
    """

    def __init__(self) -> None:
        self._registry: dict[str, Callable[..., Observation]] = {}

    def tool(self, name: str) -> Callable:
        """Decorator that registers a function as a tool under ``name``."""

        def decorator(fn: Callable[..., Observation]) -> Callable[..., Observation]:
            self._registry[name] = fn
            return fn

        return decorator

    def register(self, name: str, fn: Callable[..., Observation]) -> None:
        """Register a tool callable imperatively (non-decorator form)."""
        self._registry[name] = fn

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def names(self) -> list[str]:
        """Return the sorted list of registered tool names."""
        return sorted(self._registry)

    def run(self, call: ToolCall) -> Observation:
        """Single execution point for tools (future: centralised logging).

        Args:
            call: A :class:`ToolCall` naming the tool and its arguments.

        Returns:
            The tool's :class:`Observation`, or an error observation if the
            tool is unknown or raises.
        """
        fn = self._registry.get(call.tool)
        if fn is None:
            return Observation(tool=call.tool, ok=False, data={}, error="unknown_tool")
        try:
            return fn(**call.args)
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured observation
            return Observation(
                tool=call.tool,
                ok=False,
                data={},
                error=f"exception: {type(exc).__name__}: {exc}",
            )
