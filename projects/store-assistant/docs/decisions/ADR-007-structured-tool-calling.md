# ADR-007: Structured tool-calling contract

- **Status**: Accepted
- **Date**: 2026-06-21
- **Deciders**: Project owner
- **Supersedes**: the free-text tool-call parser introduced with I-5
  (`_split_args`/`_coerce` in `core/controller.py`), now demoted to a fallback.
- **Related**: ADR-006 (tool capability contract), the Tier-0 routing grammar
  (the proven precedent this ADR generalises).

## Context

The Tier-0 router emits **grammar-constrained JSON** validated against
`core.schemas.Route` — a structural contract that passed the routing gate
(20/20 intent accuracy). Tool-calling, by contrast, was the one path still built
on free-text parsing: the planner emitted lines like
`inventory_lookup(product_id="SKU-1")` which `extract_tool_calls` parsed with a
hand-rolled tokenizer (`_split_args`) and type-coercer (`_coerce`), then
validated defensively with the per-tool Pydantic `args_model` (I-5, ADR-006).

That ordering is backwards relative to the rest of the platform:

```
planner (free text) -> brittle regex/heuristic parse -> Pydantic (defensive)
```

The regex parser is the weakest link in the loop. On a small local model it is
exactly where malformed output appears (unbalanced brackets, stray prose,
multiple calls on one line), and every malformed call becomes an
`invalid_args`/dropped call — which then costs a retry (ADR-/I-1) or pushes the
request past its latency budget (I-3). The mature pattern (and the one this repo
already trusts for routing) is to make the model's output **structurally valid
by construction**, not valid-if-we-parse-it-right.

## Decision

Make tool-calling structured, mirroring the router:

```
planner (JSON constrained by a schema built from the registry)
    -> json.loads -> envelope validation -> per-tool args_model (defence in depth)
```

1. **Closed-set envelope contract.** The planner emits
   `{"tool_calls": [{"tool": "<name>", "args": { … }}, …]}` (or an empty list).
   `tool` is constrained to the **enum of registered tool names** — the same
   "closed set" discipline as `allowed_intents` for the router.
2. **Schema generated from the registry, not hand-written.** A static grammar
   file cannot work because the tool set is dynamic per use-case.
   `ToolRegistry.planner_json_schema()` derives the JSON schema (tool-name enum +
   `args` object) from the registered specs at agent-build time. No new authoring
   burden: tools already declare an optional `args_model` (ADR-006).
3. **Server-side constraint via `json_schema`.** The planner tier call passes a
   top-level `json_schema` field (llama.cpp converts it to a grammar internally),
   exactly as the router passes a top-level `grammar`. Consistent mechanism, one
   mental model.
4. **JSON parse replaces the regex parser.** `extract_tool_calls` now parses
   JSON and validates the envelope. The legacy text parser is **kept as a
   fallback** (a server without `json_schema` support, or a stray non-JSON line)
   so the change is strictly additive and cannot regress an existing deployment.
5. **Pydantic stays as defence in depth.** Per-tool `args_model` validation in
   `ToolRegistry.run` is unchanged — belt and suspenders, just like the policy
   gate survives ADR-006.

## Consequences

**Positive**
- Tool-calling now matches the architecture's proven, grammar-first pattern;
  one fewer bespoke mechanism to reason about.
- The brittle text parser is off the happy path → fewer malformed calls on small
  models → fewer retries/degradations (compounds with I-1/I-3).
- Multiple, nested arguments are handled by `json.loads`, not hand-rolled
  bracket counting.
- The contract is self-describing: `planner_json_schema()` is the single source
  of truth shared by the constraint and the validator.

**Negative / costs**
- Adds a JSON-schema builder and a structured parse path (covered by tests).
- Use-case `plan` prompts must instruct JSON output (updated for `tienda`).
- `json_schema` support depends on the model server; mitigated by the retained
  text fallback and the fact that llama.cpp (the supported server) supports it.

## Alternatives considered

- **Pydantic discriminated union per tool, emitted as full JSON schema with
  `$ref`s**: maximal type-safety, but llama.cpp's `json_schema → grammar`
  conversion handles `$ref`/`oneOf` unevenly. Rejected as premature; the enum +
  per-tool `args_model` validation already closes the gap. Listed as a future
  tightening once needed.
- **Hand-written GBNF for tool calls (like `route.gbnf`)**: cannot express a
  per-use-case dynamic tool set without code-generating the grammar; the
  `json_schema` route is simpler and server-supported.
- **Keep free-text + Pydantic only (status quo, I-5)**: rejected — leaves the
  weakest link on the happy path.

## Acceptance gate

- Unit tests: schema builder reflects the registered tool names; structured
  parse handles single/multiple/empty/invalid envelopes and unknown tools; the
  legacy text format still parses (back-compat); per-tool validation still fires.
- Full suite green; flake8/mypy/black/isort clean.
- A planner eval set (mirroring the routing gate) is the follow-up gate before
  the text fallback is removed entirely.

## Revisit triggers

- A use-case needs strict per-tool argument typing at the grammar level →
  introduce the discriminated-union schema.
- The text fallback records zero hits across a sustained window → delete it and
  make structured output mandatory.
