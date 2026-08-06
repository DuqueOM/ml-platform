---
name: doc-coherence
description: Keep the repository's documents from diverging from each other and from reality — ADR index, plan status, gate traceability, agentic counts — driven by check_doc_coherence.py plus the judgement rules a script cannot mechanise.
when_to_use: >
  After closing a round of work, adding or retiring an ADR, changing a phase
  status, or when two documents contradict each other. Examples: 'sync the
  docs', 'I added an ADR — propagate it', 'the plan says something different
  from the README'.
mode: AUTO for markdown drift; STOP for immutable history
---

# doc-coherence

The governing rule: **the plan and the code do not diverge in silence.** This
skill makes that mechanical where it can be, and explicit where it cannot.

## Step 0 — always run the script first

```bash
uv run python scripts/check_doc_coherence.py
```

Covers what is greppable: ADR index completeness, dangling `ADR-NNN`
references, accepted-ADR integration, gate traceability, agentic surface
counts, private-reference and language guards, independent-audit staleness.
Exits 1 on failure. **Pass it before declaring a round complete.**

## The gap the script cannot close

The script compares documents **with each other**. It cannot know whether what
a document says is *true*. Every serious documentation defect found so far has
been of that second kind — correspondence with reality, not consistency between
files. These rules cover the gap.

### Rule A — claim provenance

How a claim was established travels with it.

| Claim about | Verified by | Never by |
| --- | --- | --- |
| Code behaviour | Reading or running the code | An error message, or a memory of one |
| Third-party behaviour | Executing against it | Its documentation alone |
| A measurement | **Repeated** observation, method recorded | A single reading |
| A benchmark | A run whose configuration does not presuppose the conclusion | A prior run under other assumptions |

A conclusion drawn from a symptom rather than an execution is written as
`hypothesis` — literally, so it is greppable — until executed.

**The incident this comes from.** An ADR recorded a hardware memory budget as
*measured*, from one reading of a quantity that fluctuated by more than a
gigabyte; and rejected a candidate as too slow, citing a benchmark that had been
run under the very assumption it was used to justify. Re-measured properly, the
budget was wrong and the candidate was 3.3× faster — it passed the gate it
supposedly failed. The code was fine. The documents were wrong, in the
direction of confidence.

### Rule B — self-review is not review

This skill is self-review. By design it will not detect a fact its author
believed was true. Before any phase completion or milestone, run
`enterprise-audit` **in a separate session**, against executed evidence, and
update the `Last independent audit:` marker. Check C7 flags it when stale.

### Rule C — facts with an expiry date

Status markers (✅/🟡/⬜), "blocked on X", "next up" are claims with a shelf
life. Any round touching their area re-evaluates them. A status that is merely
old is indistinguishable from one that is wrong.

### Rule D — nothing left hanging

Anything at P0/P1 — a bug, a debt, a decision with a trigger — lands in a
tracked item. Never only in commit prose, a code comment, or an ADR body. If a
comment references a tracked item, that item must exist; a dangling reference is
a finding.

At the close of a round, re-read what was discussed and confirm every pending
thing has a home.

### Rule E — ADR integration, not ADR count

The script checks that an accepted ADR is *referenced*. Judgement checks that
it is *integrated*: its pending work is sequenced in the technical plan at the
right phase, and the architecture document reflects it. An ADR that exists only
as a file has not been accepted in any operational sense.

## Coherence points to verify by hand

1. **Source-of-truth map** — each documentary role has exactly one canonical
   location: decisions → ADRs; sequencing → technical plan; claims → README
   with rows in quality-gates; contract for agents → AGENTS.md. If a change
   moves which document owns a fact, the map updates in the same round.
2. **README claims ↔ gate rows.** Both directions. A claim with no gate is
   decoration; a gate for a claim nobody makes is dead weight.
3. **Phase statuses ↔ acceptance commands.** A phase marked ✅ whose commands
   were not run is the exact failure mode rule A exists for.
4. **CHANGELOG `[Unreleased]` ↔ the actual commit range** since the last tag.
5. **Counts** — ADRs, gates, skills, rules, workflows — wherever they are
   stated in prose.

## Authorisation

- Fixing markdown drift: **AUTO**.
- Changing a gate threshold or a phase status: **CONSULT** — it is a claim about
  the system, not a documentation edit.
- Rewriting a dated CHANGELOG entry, renumbering or deleting an ADR, or editing
  an accepted ADR's original claims: **STOP**. History is immutable.
  Corrections are **appended** as a dated `## Correction` section stating what
  replaced the claim and why. The error is usually more instructive than the
  number.
