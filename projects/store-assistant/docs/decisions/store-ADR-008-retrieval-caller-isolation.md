# store-ADR-008: Retrieval and tier surface is caller-isolated, not server-isolated

- **Status**: Accepted
- **Date**: 2026-07-01
- **Deciders**: Project owner
- **Related**: store-ADR-001 (reusable platform), store-ADR-006 (tool capability contract);
  template-ADR-037 (dual-namespace retrieval separation), template-ADR-018 (operational memory plane), `ACTION_PLAN_LLM_AGENT.md` §L-2/§L-2b.

## Context

The tier endpoints (E4B/12B/26B-A4B/31B, OpenAI-compatible over HTTP) were
designed for **one** caller: the `tienda` use-case's in-process loop, via
`core/agent.py`'s `Agent` (one `BM25Index` + one `ToolRegistry` per use-case,
per store-ADR-001).

A second class of caller now exists. `ml-service-template`'s own maintenance-plane
scripts already call a tier endpoint (E4B, port 8091) directly over HTTP from
**outside** this repo's process, for retrieval-augmented summarization over
`ml-service-template`'s own operational evidence (`ops/audit.jsonl`, incidents, drift
reports — `ACTION_PLAN_LLM_AGENT.md` §L-2, `scripts/memory_query.py`).
`ml-service-template` is now adding a **second** external caller of the same shape: a
pedagogical/onboarding RAG over `ml-service-template`'s own teaching content plus,
optionally, an adopter's long-form documentation corpus
(`ACTION_PLAN_LLM_AGENT.md` §L-2b; template-ADR-037).

Both external callers are legitimate and low-risk (read-only summarization),
and both reuse the same E4B tier — but they operate on fundamentally
different, never-to-mix corpora (operational evidence vs. teaching material).
Nothing about the tier server distinguishes between them: it does not know or
care who is asking, by design (`core/` is business-agnostic, store-ADR-001). That
means the responsibility for keeping "operational" and "pedagogical"
retrieval separate does **not** live inside agent-local — and that has to be
written down explicitly, or a future contributor could reasonably (and
wrongly) assume the tier boundary itself provides an isolation it does not.

## Decision

State the isolation contract explicitly, in both directions:

1. **The tier endpoints are stateless per request.** `llama-server` holds no
   corpus, no retrieval index, and no memory of a prior request (plan §F0.2).
   Calling the same E4B endpoint from two unrelated retrieval namespaces is
   exactly as safe as calling it from two unrelated `tienda` conversations —
   the tier accumulates no cross-request state that could leak between
   callers. This is what makes *sharing* the tier endpoint across the
   operational and pedagogical namespaces (template-ADR-037) a
   deliberate, safe reuse, not a shortcut that weakens separation.
2. **Corpus/index isolation is the CALLER's responsibility, never the
   tier's.** This repo will not add request-level namespace/ACL parameters to
   the tier client (`core/tiers.py`) or the router (`core/router.py`) to
   enforce this — that would imply the tier server needs to know about
   corpora it never touches, which it structurally cannot verify. The
   enforcement point is wherever the `BM25Index` (or equivalent) is
   constructed. Inside agent-local, that is the `usecases/<name>/` boundary
   (store-ADR-001): one `BM25Index` object per use-case, never shared, wired in
   `core/agent.py`. Outside agent-local, in `ml-service-template`'s maintenance-plane
   scripts, the equivalent discipline is specified in `ml-service-template`'s own
   template-ADR-037: disjoint scripts, disjoint hard-coded corpus roots, disjoint index
   objects, mandatory citation-path validation.
3. **agent-local's own in-process guarantee is unaffected and unchanged.**
   `usecases/tienda/`'s `BM25Index` (business policy docs) and any future
   in-process use-case remain isolated exactly as store-ADR-001 and
   `core/retrieval.py` already provide — this ADR modifies no code in `core/`.
   If agent-local ever grows an in-process pedagogical use-case
   (`usecases/pedagogy/`) instead of, or alongside, the external-script
   approach, **this** ADR is the one that governs its isolation guarantee —
   and it gets that guarantee for free from the existing `usecases/<name>/`
   contract (a new folder, a new `BM25Index` instance, a new `ToolRegistry`;
   see `docs/usecases.md`), not from anything new.
4. **No new code ships with this ADR.** This is a contract clarification, not
   a feature. It exists so the multi-caller reality (one tier server, two
   external retrieval namespaces) has a written answer for "whose job is
   separation?" before a second caller existed to make the question urgent.

## Consequences

### Positive

- Closes a documentation gap before it becomes an incident: without this, a
  contributor debugging "a pedagogical answer cited an ops file" would have no
  ADR to check for whose contract was violated.
- Keeps `core/` free of speculative multi-tenancy machinery (request-scoped
  ACLs, namespace headers) that no current use-case needs — consistent with
  "the simplest loop that works" and store-ADR-001's "never fork `core/` for a
  domain concern."
- Gives template-ADR-037 a stable foundation to cite ("the tier is
  safe to share, here is why") instead of re-deriving it inline.

### Negative / costs

- One more ADR to keep in sync if the tier client ever does grow
  request-scoped behavior (see Revisit triggers).

## Alternatives considered

- **Add a `namespace` parameter to the tier client/router, enforced
  server-side**: rejected. The tier has no way to verify a caller's claimed
  namespace is honest — it is not an authentication boundary — so this would
  be a false sense of security. Real enforcement has to happen where the
  corpus is assembled, not where completions are generated. Revisit only if
  agent-local ever serves genuinely untrusted/multi-tenant external callers
  (not the case today: both current external callers are `ml-service-template`'s own
  scripts).
- **Require external callers to run a separate tier server instance per
  namespace**: rejected as wasteful. The tier holds no state to protect;
  doubling GPU/RAM-resident model processes for a property (statelessness)
  that already holds spends real hardware budget (this repo's fixed VRAM
  ceiling, plan §0) for zero additional safety.

## Acceptance gate

- No code change is required to close this ADR — it is satisfied by this
  document plus template-ADR-037 existing and cross-referencing it.
- Future gate: if `core/tiers.py` or `core/router.py` ever gains a parameter
  that could plausibly be mistaken for cross-caller access control, that PR
  must update this ADR in the same commit.

## Revisit triggers

- agent-local's tier endpoints become reachable by a caller outside the
  maintainer's own repos (genuine multi-tenant/external customers) → re-open
  this ADR; server-side enforcement stops being optional.
- A second in-process use-case is added to agent-local itself (e.g.
  `usecases/pedagogy/`) → confirm it still gets isolation "for free" from the
  `usecases/<name>/` contract; if not, the contract has a gap this ADR must be
  updated to reflect.
