"""Tool registry — the APP executes tools, the model only names them.

The registry mechanism is generic platform code. Concrete tools (inventory,
pricing, orders, …) live in the use-case package and register themselves
against a :class:`ToolRegistry` instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from .schemas import Observation, ToolCall


@dataclass(frozen=True)
class ToolSpec:
    """A registered tool plus its capability contract (ADR-006).

    Capabilities are **fail-closed**: a tool is assumed to mutate state unless
    it declares ``read_only=True`` (or ``dry_run_only=True``). The registry uses
    this to enforce the Phase-1 read-only invariant structurally, independent of
    (and in addition to) the deterministic policy gate.

    Attributes:
        fn: The callable that performs the tool action and returns an Observation.
        read_only: True if the tool never mutates external state.
        destructive: True if the tool performs irreversible operations.
        dry_run_only: True if the tool always simulates (never commits) — allowed
            in Phase 1 even though it is not strictly read-only.
        args_model: Optional Pydantic model validating ``ToolCall.args`` before
            execution (I-5). Validation failures surface as a structured error.
    """

    fn: Callable[..., Observation]
    read_only: bool = False
    destructive: bool = False
    dry_run_only: bool = False
    args_model: type[BaseModel] | None = None


class ToolRegistry:
    """A named collection of capability-typed tools returning Observations.

    Each use-case owns one registry, keeping tool namespaces isolated.

    Args:
        read_only_mode: When True (the fail-closed default, i.e. Phase 1), the
            registry refuses to run a tool that is neither ``read_only`` nor
            ``dry_run_only``. Wire this from ``UsecaseConfig.read_only_mode``.
    """

    def __init__(self, read_only_mode: bool = True) -> None:
        self._registry: dict[str, ToolSpec] = {}
        self.read_only_mode = read_only_mode

    def tool(
        self,
        name: str,
        *,
        read_only: bool = False,
        destructive: bool = False,
        dry_run_only: bool = False,
        args_model: type[BaseModel] | None = None,
    ) -> Callable:
        """Decorator that registers a function as a tool under ``name``."""

        def decorator(fn: Callable[..., Observation]) -> Callable[..., Observation]:
            self.register(
                name,
                fn,
                read_only=read_only,
                destructive=destructive,
                dry_run_only=dry_run_only,
                args_model=args_model,
            )
            return fn

        return decorator

    def register(
        self,
        name: str,
        fn: Callable[..., Observation],
        *,
        read_only: bool = False,
        destructive: bool = False,
        dry_run_only: bool = False,
        args_model: type[BaseModel] | None = None,
    ) -> None:
        """Register a tool callable imperatively (non-decorator form)."""
        self._registry[name] = ToolSpec(
            fn=fn,
            read_only=read_only,
            destructive=destructive,
            dry_run_only=dry_run_only,
            args_model=args_model,
        )

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def names(self) -> list[str]:
        """Return the sorted list of registered tool names."""
        return sorted(self._registry)

    def spec(self, name: str) -> ToolSpec | None:
        """Return the :class:`ToolSpec` for a tool name, or ``None``."""
        return self._registry.get(name)

    def run(self, call: ToolCall) -> Observation:
        """Single execution point for tools — the fail-closed enforcement seam.

        Order of checks: unknown tool -> Phase-1 capability gate -> argument
        validation -> execution. Every failure is a structured Observation, so
        the model can react instead of crashing the loop.

        Args:
            call: A :class:`ToolCall` naming the tool and its arguments.

        Returns:
            The tool's :class:`Observation`, or an error observation if the tool
            is unknown, not permitted, given invalid args, or raises.
        """
        spec = self._registry.get(call.tool)
        if spec is None:
            return Observation(tool=call.tool, ok=False, data={}, error="unknown_tool")

        # Fail-closed phase gate (ADR-006): a mutating tool cannot run in a
        # read-only phase just because the model named it.
        if self.read_only_mode and not spec.read_only and not spec.dry_run_only:
            return Observation(tool=call.tool, ok=False, data={}, error="tool_not_permitted_phase1")

        args = call.args
        if spec.args_model is not None:
            try:
                args = spec.args_model(**call.args).model_dump()
            except ValidationError as exc:
                detail = "; ".join(f"{e['loc'][0] if e['loc'] else '?'}: {e['msg']}" for e in exc.errors())
                return Observation(tool=call.tool, ok=False, data={}, error=f"invalid_args: {detail}")

        try:
            return spec.fn(**args)
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured observation
            return Observation(
                tool=call.tool,
                ok=False,
                data={},
                error=f"exception: {type(exc).__name__}: {exc}",
            )
