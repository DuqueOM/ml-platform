# ADR-006: Tool capability contract (fail-closed, phase-gated)

- **Status**: Accepted
- **Date**: 2026-06-20
- **Deciders**: Project owner
- **Plan ref**: §F1.4, ARCH_REVIEW §7 (two-person rule for new mutations)

## Context

In Phase 1 every tool is read-only and `order_create` is forced to dry-run.
That invariant (SECURITY.md, principle #2: "the model never mutates critical
state without the policy gate") was enforced only *reactively*: each tool
hardcoded its own safety (`order_create` set `dry_run=True` internally) and the
deterministic policy gate (`core/policy.py`) inspected the *output* afterwards.

Nothing structurally prevented a future use-case from registering a *mutating*
tool that runs in Phase 1. `ToolRegistry` was a bare `name -> callable` dict:
the model naming a tool was sufficient to execute it. The leaked Claude Code
source (`Tool.ts` `buildTool`) shows the mature pattern — every tool declares
`isReadOnly` / `isDestructive` with **fail-closed defaults** and a permission
check runs before execution.

## Decision

1. **Tools carry a capability contract** (`core/tools.ToolSpec`):
   `read_only`, `destructive`, `dry_run_only`, and an optional `args_model`.
2. **Fail-closed defaults**: a tool is assumed to mutate state
   (`read_only=False`) unless it declares otherwise. Registering a tool without
   capabilities is treated as "unsafe until proven safe".
3. **Phase gate in the single execution seam** (`ToolRegistry.run`): while the
   registry is in `read_only_mode` (Phase 1, sourced from
   `UsecaseConfig.read_only_mode`, i.e. `phase < 2`), a tool that is neither
   `read_only` nor `dry_run_only` is refused with a structured
   `Observation(ok=False, error="tool_not_permitted_phase1")`. The model cannot
   mutate state by merely naming a tool.
4. **Defence-in-depth, not replacement**: the deterministic policy gate
   (ADR-003) remains the second, independent line of defence. The capability
   gate is the *first* — at the tool layer, before any output exists.
5. **Optional per-tool input validation** (`args_model`, a Pydantic model):
   `ToolCall.args` is validated before execution; failures surface as
   `invalid_args: <detail>` so the model can correct itself instead of crashing
   the loop.
6. **Phase is config-driven**: a use-case lifts the gate by setting `phase: 2`
   in `config.yaml` once its mutating backends and their evals exist — never by
   editing `core/`.

## Consequences

**Positive**
- The read-only invariant is now **structural**, not convention: a mis-declared
  mutating tool fails closed.
- Auditable: a tool's capabilities are declared at registration, in one place.
- The contract is backwards-compatible — defaults fill in; existing tools only
  add keyword flags (`read_only=True`, `dry_run_only=True`).
- Argument validation turns deep `TypeError`s into structured, model-readable
  observations.

**Negative / costs**
- Tool authors must now declare capabilities (the fail-closed default makes the
  *safe* omission the loud one — a forgotten flag blocks the tool, never opens
  it).

## Alternatives considered

- **Keep relying on the policy gate only**: rejected — it inspects output after
  the fact; a mutating tool would already have run.
- **A full permission/hook framework (Claude Code `checkPermissions` + hooks)**:
  rejected as premature at one use-case (over-engineering, see the
  `CLAUDE_CODE_IMPROVEMENT_PLAN` deferral I-6). The capability flags capture the
  90% that matters now.

## Revisit triggers

- A second use-case needs per-tool runtime permission prompts (human approval) →
  introduce a `check_permissions(input, ctx)` hook on `ToolSpec`.
- Phase 2 mutating tools land → add the "two-person rule" (a new mutating tool
  ships `dry_run`-forced until its eval passes and a human signs the PR).
