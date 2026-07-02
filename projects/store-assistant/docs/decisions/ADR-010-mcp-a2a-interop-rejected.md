# ADR-010 — MCP / A2A Interoperability: Rejected (with revisit triggers)

- **Status**: Rejected (with explicit revisit triggers — not a closed door)
- **Date**: 2026-07-02
- **Context source**: `docs/audit/ACTION_PLAN_R9_ENTERPRISE_BENCHMARK.md`,
  Anexo A. Also answers a direct question the maintainer asked about
  Google Cloud's 2026 "data agents" guidebook, which frames MCP as the
  industry's de-facto connector standard.

## Context

Two distinct integration questions were raised after installing
`codebase-memory-mcp` (a dev-tooling MCP server used to audit this repo)
and reading Google's 2026 agent-platform guidance, which positions the
Model Context Protocol (MCP) as *"the standard connector"* and
Agent-to-Agent (A2A) as the multi-agent network layer:

1. Should `core/tools.ToolRegistry` be exposed as an MCP **server**, so
   other agents/clients could discover and call this platform's tools?
2. Should this platform become an MCP **client**, consuming external MCP
   tool servers (databases, APIs) instead of hand-writing per-tool
   integrations in `usecases/<name>/tools.py`?

Both were evaluated against this platform's actual architecture, not
against MCP's general merits (which are real — it is a genuinely useful
standard for the problem it solves).

## Decision

**Reject both, for now**, and record why precisely enough that a future
revisit does not have to re-derive the reasoning.

### As a server: rejected — creates a second, ungoverned door

The value of this platform is that `core/tools.ToolRegistry.run` is **the
only path** a tool can execute through: router → budget → fail-closed
capability gate (ADR-006) → argument validation → execution → policy gate
→ telemetry. Exposing the registry as an MCP server means an external
caller invokes a tool by name+args over the wire — bypassing the router,
the budget, the policy gate, and the telemetry contract entirely, unless
each of those is re-implemented INSIDE every tool (which defeats the
point of having a single enforcement seam in the first place).

The only version of "server" that doesn't break this: expose
`Agent.handle()` itself — the whole admit/execute/release loop — as a
single MCP tool. That is architecturally sound, but it adds nothing that
the existing REST endpoint (`POST /dev/message`) doesn't already provide.
There is no scenario today where "the same thing, but MCP-shaped" is worth
a new protocol surface.

### As a client: rejected — the annotation trust model conflicts with ADR-006

MCP tool annotations (`readOnlyHint`, `destructiveHint`, etc.) are how an
MCP server *describes* its own tools' risk profile. The specification is
explicit that these are hints an untrusted server can misreport: *"clients
MUST consider tool annotations to be untrusted unless they come from
trusted servers"* ([MCP Tool Annotations blog,
2026-03-16](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)).

ADR-006's fail-closed contract requires a tool's `read_only`/`dry_run_only`
capability to be **declared and verifiable by the registry itself**, not
self-reported by the tool's own author. To integrate an MCP server while
honoring ADR-006, every consumed MCP tool would need a manually-audited,
hand-maintained allow-list of verified capabilities — at which point the
integration is back to being per-tool, by hand, exactly like
`usecases/tienda/tools.py` today. The only things actually gained are
costs: a new supply-chain surface (tool-poisoning via a malicious or
compromised MCP server is a documented attack class in the ecosystem), a
subprocess-latency tax against an 8-second channel SLA, and a protocol
dependency in a platform whose entire pitch is "small, local, auditable."

### Where MCP legitimately fits in this ecosystem

`codebase-memory-mcp` — installed as a **developer tool** for the human(s)
building this repo, consumed by Claude Code / other coding agents during
development — is exactly the right shape of MCP adoption: dev-tooling,
never product runtime. That line (dev-side yes, product-runtime no) is
what this ADR draws, not a blanket rejection of MCP as a technology.

## Consequences

### Positive
- No new protocol dependency, no new supply-chain surface, no
  subprocess-latency tax against the latency budget.
- ADR-006's fail-closed guarantee stays enforceable exactly as designed —
  a single seam, not one seam plus a bypass.
- The decision (and its reasoning) is now citable instead of an implicit,
  undocumented "we just didn't do it."

### Negative
- Future use-cases needing many external integrations pay the
  per-tool-by-hand cost `usecases/tienda/tools.py` already pays. This is
  accepted, not free — see revisit triggers.
- Diverges from the direction some platform vendors (Google's agent
  guidebook, among others) present as the default path — a deliberate,
  reasoned divergence, not an oversight.

### Neutral
- `A2A` (multi-agent coordination) was not separately evaluated in depth:
  this platform is single-agent-with-usecases (ADR-001), not
  multi-agent-by-design, so A2A answers a question this repo does not
  currently ask. Revisit if that scope changes.

## Revisit triggers

- A real use-case needs **three or more** integrations that already exist
  as mature, provenance-verified MCP servers from a trusted publisher —
  the per-tool-by-hand cost starts to dominate.
- MCP's specification promotes tool-capability annotations from "hint,
  untrusted by default" to a **normatively verifiable contract** (multiple
  Specification Enhancement Proposals were active in this direction as of
  2026-03) — this would remove the ADR-006 conflict this ADR is built on.
- An enterprise adopter makes MCP interoperability a contractual
  requirement.
- A concrete multi-agent coordination need arises (a use-case that must
  hand off to or discover an independently-built agent) — evaluate A2A on
  its own merits at that point, separately from this MCP decision.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| MCP server exposing the tool registry directly | Creates a second, ungoverned execution path around router/budget/policy/telemetry (see Decision) |
| MCP server exposing only `Agent.handle()` | Architecturally sound but adds nothing over the existing REST endpoint |
| MCP client with a manual per-tool capability allow-list | Converges back to hand-written per-tool integration — all of MCP's cost, none of its "no custom integration" benefit |
| Wait-and-see with no documented decision | The status quo before this ADR — the plan explicitly flagged that documented NO decisions are as important as documented YES decisions for an enterprise-recommendable repo |

## Related

- `docs/decisions/ADR-006-tool-capability-contract.md` — the fail-closed
  contract this decision protects.
- `docs/audit/ACTION_PLAN_R9_ENTERPRISE_BENCHMARK.md` — Anexo A, the full
  original analysis this ADR formalizes.
- template_MLOps `docs/decisions/ADR-029-agentic-adoption-contract.md` —
  the sibling repo's own "tools adapt to our canon, not the reverse"
  principle, which this ADR applies to a different surface (product
  runtime vs. agentic governance store).
