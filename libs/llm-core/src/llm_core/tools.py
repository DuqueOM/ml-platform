"""Tool registry — the APP executes tools, the model only names them.

The registry mechanism is generic platform code. Concrete tools (inventory,
pricing, orders, …) live in the use-case package and register themselves
against a :class:`ToolRegistry` instance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .schemas import Observation, ToolCall


def _first_line(docstring: str | None) -> str:
    """The summary line of a docstring, or an empty string.

    Deriving the description from the docstring rather than requiring a second
    declaration keeps the two from disagreeing. A tool whose docstring says one
    thing and whose registered description says another is worse than one with
    no description, because the manifest would publish the stale half.
    """
    if not docstring:
        return ""
    for line in docstring.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


@dataclass(frozen=True)
class ToolSpec:
    """A registered tool plus its capability contract (store-ADR-006).

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
        description: One line saying what the tool does. Defaults to the first
            line of the function's docstring, so a tool that documents itself
            needs no second declaration — and one that does not is visible as an
            empty string in the manifest rather than absent from it.
    """

    fn: Callable[..., Observation]
    read_only: bool = False
    destructive: bool = False
    dry_run_only: bool = False
    args_model: type[BaseModel] | None = None
    description: str = ""


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
        description: str = "",
    ) -> Callable[..., Any]:
        """Decorator that registers a function as a tool under ``name``."""

        def decorator(fn: Callable[..., Observation]) -> Callable[..., Observation]:
            self.register(
                name,
                fn,
                read_only=read_only,
                destructive=destructive,
                dry_run_only=dry_run_only,
                args_model=args_model,
                description=description,
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
        description: str = "",
    ) -> None:
        """Register a tool callable imperatively (non-decorator form)."""
        self._registry[name] = ToolSpec(
            fn=fn,
            read_only=read_only,
            destructive=destructive,
            dry_run_only=dry_run_only,
            args_model=args_model,
            description=description or _first_line(fn.__doc__),
        )

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def names(self) -> list[str]:
        """Return the sorted list of registered tool names."""
        return sorted(self._registry)

    def spec(self, name: str) -> ToolSpec | None:
        """Return the :class:`ToolSpec` for a tool name, or ``None``."""
        return self._registry.get(name)

    def manifest(self) -> list[dict[str, Any]]:
        """The capability surface as reviewable data, one entry per tool.

        Tools register by import side effect, so until now the only way to
        answer "what can this agent do, and what is it allowed to mutate" was
        to import the package and read decorator arguments. That makes the
        capability contract discoverable by execution, which is the one method
        unavailable to a reviewer, a diff, or an audit.

        This is the same move this repository already made twice: thresholds
        became data in ``evals/gates.yaml``, dataset bytes became data in
        ``datasets.lock.json``. A claim that can be read as data can be gated;
        one that can only be reached by running the program cannot.

        The idea is adapted from the plugin-manifest convention in
        `deepseek-ai/deepseek-harness`, which was evaluated and NOT forked
        (ADR-004's argument against a second toolchain). Its discovery
        convention is worth having; its runtime is not.

        Deliberately excluded: ``fn``. A callable is not serialisable and its
        identity is not stable across runs, so including it would make two
        manifests of the same registry compare unequal.

        Returns:
            Entries sorted by name, each JSON-serialisable, carrying the name,
            the description, all three capability flags and the argument schema
            where one is declared.
        """
        return [
            {
                "name": name,
                "description": spec.description,
                "read_only": spec.read_only,
                "destructive": spec.destructive,
                "dry_run_only": spec.dry_run_only,
                "args_schema": spec.args_model.model_json_schema() if spec.args_model is not None else None,
            }
            for name, spec in sorted(self._registry.items())
        ]

    def mutating_tools(self) -> list[str]:
        """Names of tools this registry would refuse to run in a read-only phase.

        The complement of the fail-closed gate in :meth:`run`, exposed so a test
        or an audit can assert over the set rather than by attempting each call.
        A tool is mutating unless it declares otherwise — absence of a
        declaration is not a claim of safety.
        """
        return sorted(name for name, spec in self._registry.items() if not spec.read_only and not spec.dry_run_only)

    def planner_json_schema(self) -> dict[str, Any]:
        """JSON schema for the planner's structured tool-call output (store-ADR-007).

        Constrains the planner to emit ``{"tool_calls": [{"tool", "args"}, …]}``
        where ``tool`` is restricted to the registered names — a closed set, the
        same discipline the router applies to ``allowed_intents``. Per-tool
        argument typing is enforced afterwards by each tool's ``args_model``
        (defence in depth, store-ADR-006). This object is the single source of truth
        shared by the server-side constraint and the parser's validation.
        """
        return {
            "type": "object",
            "properties": {
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string", "enum": self.names()},
                            "args": {"type": "object"},
                        },
                        "required": ["tool", "args"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["tool_calls"],
            "additionalProperties": False,
        }

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

        # Fail-closed phase gate (store-ADR-006): a mutating tool cannot run in a
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
        except Exception as exc:
            return Observation(
                tool=call.tool,
                ok=False,
                data={},
                error=f"exception: {type(exc).__name__}: {exc}",
            )
