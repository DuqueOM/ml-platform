# ADR-005 — Agentic governance: verification, coherence, testing and QA as executable procedure

- **Status**: Accepted
- **Date**: 2026-08-05

## Context

Most of this repository's code will be written with agent assistance. That is
not a risk to be mitigated by prose in a CONTRIBUTING file; it is an operating
condition, and it fails in specific, repeatable ways:

- **Documentation drifts from code silently.** Nothing breaks when a document
  becomes false, so nothing reports it.
- **A claim gets written down as verified when it was inferred.** The most
  expensive defects are not wrong code — they are correct-looking documents
  asserting things nobody executed.
- **Self-review does not detect what the author believed.** An agent reviewing
  its own work cannot find an error it made confidently.
- **Findings evaporate into prose.** A problem noticed in a commit message, a
  code comment or the body of an ADR has no owner and no due date.
- **Tests get written to pass rather than to falsify.** Coverage rises while the
  suite's ability to detect a regression does not.

### The founding evidence

These are not hypothetical. During the work that produced this repository, an
ADR was written in the sibling agent platform declaring a hardware memory budget
as **measured**, and rejecting a candidate model as too slow, citing a benchmark.

Both claims were wrong, and both had the same shape:

- The memory figure was **one sample of a fluctuating quantity**. Sampled
  repeatedly, the true value differed by more than a gigabyte.
- The benchmark cited had been run **under the very assumption it was used to
  justify** — partial GPU offload, chosen because the model was believed not to
  fit. Re-run without that assumption, the model was 3.3× faster and passed the
  gate it had supposedly failed by 11%.

The code was fine. The documents were wrong, and they were wrong in the
direction of confidence. That is the failure this ADR exists to make
structurally difficult.

## Decision

Adopt a four-plane agentic surface, vendor-neutral and canonical in `agentic/`,
with thin per-tool adapters. Beyond the inherited AUTO/CONSULT/STOP behaviour
protocol, the following invariants are binding.

### A. Claim provenance — how a claim was verified travels with it

Every assertion about state carries the method that established it:

| Claim about | Verified by | Never by |
|---|---|---|
| Code behaviour | Reading the code, or running it | An error message, or a memory of it |
| Third-party behaviour | Executing against it | Its documentation alone |
| A measurement | **Repeated** observation, with the sampling method recorded | A single reading |
| A benchmark result | A run whose configuration does not presuppose the conclusion | A prior run under different assumptions |

A conclusion drawn from a symptom rather than an execution is written as
`hypothesis` — literally, so it is greppable — until executed. A number written
without its sampling method is treated as unverified regardless of how precise
it looks.

### B. Self-review is not review

The agent that wrote the documentation cannot be its only verifier. Coherence
checking is self-review by construction and will not detect a fact its author
believed. Therefore an **independent audit runs in a separate session**, against
executed evidence, and the repository carries a `Last independent audit:` marker
that the coherence gate flags when stale.

### C. Facts with an expiry date

Status markers — ✅/🟡, "blocked on X", "next up" — are claims that **expire**.
Any round touching their area re-evaluates them. A status that is merely old is
indistinguishable from a status that is wrong.

### D. Nothing left hanging

Anything found at P0/P1 severity — a bug, a debt, a decision with a trigger —
lands in a tracked item. Never only in commit prose, a code comment, or an ADR
body. If a comment references a tracked item, that item must exist; a dangling
reference is a finding.

### E. Audit verifies by execution, never by reading

If a document claims "142 tests pass", the audit runs them. If it claims "no
type errors", it runs the type checker. Reading a claim is not verification of
it, and a claim that cannot be executed is a claim that cannot be audited.

### F. Evidence has a fixed shape

Every finding: **severity** (P0 breaks something promised · P1 security or data
risk · P2 real debt · P3 cosmetic) · **file:line** · **command and its actual
output** · **suggested correction**. A finding without a reproducible command is
an opinion.

### G. What works is reported too

An audit that reports only problems has not demonstrated that it examined
anything else. Verified-correct surfaces are listed with their evidence.

### H. Doc/code divergence is a finding on its own

Even when the code is correct. **The document asserting something false is
itself the defect** — that is the whole content of the founding evidence above.

### I. Non-interference

Audits are read-only plus verification commands. They never fix, commit, or
touch another session's working tree. Corrections are a separate round with
their own record. An auditor that edits has destroyed the evidence it was
sent to collect.

### J. Tests are written to falsify

A test's value is the regression it would catch, not the line it covers. Each
test states, in its name or docstring, **what breaking would look like**. Test
doubles that implement a production interface inherit a shared contract stub, so
they cannot drift away from that interface one file at a time. Coverage is a
floor, never evidence of adequacy.

### K. Quality metrics are gates or they are decoration

Every published quality claim maps to a check that can fail a build. A metric
that is measured and reported but cannot fail is removed or promoted — it is
otherwise a number that reassures without constraining. The mapping lives in
`docs/governance/quality-gates.md` and is itself checked for completeness.

### L. QA procedures are executable, not remembered

Release, promotion, incident response and rollback are skills with explicit
preconditions, evidence requirements and STOP points — not checklists a human
is expected to recall under pressure.

### The surface

| Plane | Answers | Example |
|---|---|---|
| **Rules** | "What is always true here?" | Dependency direction; no credentials in config |
| **Skills** | "How is this procedure performed?" | `doc-coherence`, `enterprise-audit`, `test-authoring`, `quality-metrics`, `qa-procedure` |
| **Workflows** | "What does this slash command run?" | `/audit`, `/document-changes`, `/qa` |
| **Gates** | "What fails the build?" | Coherence check, dependency-direction test, SLO load gate |

Skills are procedures; gates are enforcement. **A skill without a gate is
advice.** Where an invariant above can be mechanised, it is a gate first and a
skill second.

## Consequences

### Positive

- The failure mode that produced the founding evidence becomes structurally
  harder: rule A would have flagged the single-sample measurement, rule E the
  benchmark citation, rule H the document that outlived its truth.
- Procedures survive context loss. A new session inherits the operating
  discipline instead of reconstructing it.
- Rule K converts the README from a set of assertions into a set of claims with
  addresses.

### Negative

- This is process, and process erodes under schedule pressure. The counterweight
  is that the mechanisable parts are gates — they fail builds rather than
  relying on discipline.
- Rule B costs a separate audit session at intervals, which is real time spent
  finding nothing most of the time. That is what an audit is.
- Rule A makes writing slower. It is meant to: the cost is paid by the writer
  instead of by the reader who later trusts a false statement.

### Neutral

- The surface is portable by construction (canonical `agentic/`, thin adapters),
  so tool churn costs an adapter rather than a rewrite.

## Revisit triggers

- An independent audit finds a P0 that the coherence gate could have caught
  mechanically — that check is missing and should be added.
- A rule is bypassed twice for the same reason — it is mis-specified, not
  under-enforced.
- Quality-gate traceability (rule K) develops gaps — either the claim or the
  gate is missing, and both are defects.

## Related

- [ADR-000](ADR-000-charter-and-scope.md) — the "agent-operable" commitment.
- [ADR-001](ADR-001-monorepo-topology.md) — the uniform project layout that
  makes one skill work across every project.
- `docs/governance/quality-gates.md` — rule K's traceability table.
- `docs/governance/qa-procedures.md` — rule L's executable procedures.
