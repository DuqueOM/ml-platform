# QA procedures

Implements [ADR-005](../decisions/ADR-005-agentic-governance.md) rule L:
**quality procedures are executable, not remembered.** Each procedure below has
a matching skill in `agentic/skills/`, so it can be invoked rather than recalled
— which matters most during an incident, when recall is worst.

A procedure states its **preconditions**, its **evidence requirements**, and its
**STOP points**. A step that cannot produce evidence is not a QA step; it is a
habit.

## Authorisation model

Inherited from the agent behaviour protocol and binding on every procedure here.

| Mode | Meaning |
|---|---|
| **AUTO** | Proceed and report |
| **CONSULT** | Present the plan and its evidence; wait for a decision |
| **STOP** | Halt. Requires explicit human authorisation to continue, and the authorisation is recorded |

The mode is a property of the *action*, not of confidence in it. Being certain
does not downgrade a STOP.

---

## QA-1 — Change verification (AUTO)

Runs on every change before it is proposed for review.

**Preconditions**: a clean working tree at a known commit.

**Steps**

1. Run the gates the change touches, from
   [quality-gates.md](quality-gates.md). Path-filtered CI decides which; when
   in doubt, run more.
2. For a change to `libs/`, run **every dependent project's** suite. This is
   the monorepo's whole value proposition and the step most often skipped.
3. Confirm each new test **fails without the change**. A test that passes
   against unmodified code tests nothing.
4. Update the documents the change makes stale — in the same round, not later
   (ADR-005 rule C).

**Evidence**: gate commands with their actual output, not a summary of it.

**STOP**: never. If a gate fails, the change is not ready; that is not a stop,
it is the gate working.

---

## QA-2 — Test authoring (AUTO)

Applied whenever tests are written. Implements ADR-005 rule J.

**The question a test must answer**: *what regression would this catch?* If the
answer is "none specific", the test is coverage theatre and should be replaced.

**Requirements**

1. **Name or docstring states the failure being prevented.** `test_handles_none`
   says nothing; `test_missing_credential_raises_rather_than_calling_unauthenticated`
   says exactly what breaking looks like.
2. **Verified to fail without the fix.** Non-negotiable, and the step most
   commonly skipped because the test passes and passing feels like success.
3. **Test doubles implementing a production interface inherit a shared contract
   stub.** Four hand-written doubles of one interface will drift away from it
   one file at a time, and each will keep passing while doing so.
4. **Boundaries and error paths before happy paths.** The happy path is what
   the implementation was written against; the error path is where the defects
   are.
5. **No assertion on incidental output.** Asserting a log message tests the log
   message.

**Evidence**: for each new test, the failing run before the fix and the passing
run after.

---

## QA-3 — Quality metric review (CONSULT)

Runs when a gate threshold is proposed for change, and on a recurring cadence.

**Steps**

1. Verify every README claim has a row in
   [quality-gates.md](quality-gates.md), and every row's command exists and
   runs. Gaps in either direction are findings.
2. For each threshold, confirm the recorded reason still holds. A threshold
   whose justification has expired is a number nobody owns.
3. Identify gates that have **never failed**. Either the risk is absent, or the
   gate does not work. Verify by running against known-bad input.
4. Identify gates bypassed more than once — mis-specified, not
   under-enforced.

**STOP**: lowering a threshold. It is always allowed and never automatic; it
requires a recorded reason and a named decision-maker, because the alternative
is thresholds that decay toward whatever currently passes.

---

## QA-4 — Independent audit (AUTO within its session)

Implements ADR-005 rule B. **Runs in a separate session from the work it
audits.** Self-review cannot find an error its author made confidently, and
running it in the authoring session makes it self-review regardless of intent.

**Method**

1. **Verify by executing, never by reading.** "142 tests pass" → run them.
   "No type errors" → run the checker. A claim that cannot be executed cannot
   be audited, and should be reported as such.
2. **Check measurements for provenance.** A number without its method is
   unverified however precise it looks. A number from a single observation of a
   varying quantity is an anecdote. A benchmark run under the assumption it is
   cited to support has tested nothing.
3. **Report what works, with its evidence.** An audit reporting only problems
   has not shown it examined anything else.
4. **Document/code divergence is a finding even when the code is right.** The
   false document is the defect.
5. **Non-interference.** Read-only plus verification commands. Never fix, never
   commit, never touch another session's working tree. Corrections are a
   separate round. An auditor that edits has destroyed the evidence it was sent
   to collect.

**Evidence format** — every finding:

```
[P0|P1|P2|P3] <one-line claim>
  file:line
  $ <command>
  <actual output>
  Fix: <specific correction>
```

| Severity | Meaning |
|---|---|
| P0 | Something promised is broken |
| P1 | Security or data risk |
| P2 | Real debt with a cost |
| P3 | Cosmetic |

**Closing verdict**: one sentence — are the audited claims trustworthy?

**High-yield surfaces** (updated as findings accumulate, so the audit learns):

- "Verified" claims in plans and status documents, against reality.
- Measurements presented without their sampling method.
- Benchmarks whose configuration presupposes their conclusion.
- Status markers set without evidence in CI.
- Configuration that *appears* active — keys absent from the tool's schema.
- Test doubles whose contract has drifted from the real implementation.
- Truthiness comparisons against string environment variables.

---

## QA-5 — Documentation coherence (AUTO)

**Step 0, always first**: run the mechanical check.

```bash
uv run python scripts/check_doc_coherence.py
```

It covers what is greppable: ADR index completeness, dangling `ADR-NNN`
references, version consistency, agentic surface counts, claim/gate
traceability, staleness of the independent-audit marker.

What it cannot cover is judgement, and that is the rest of this procedure:

1. **Source-of-truth map.** Each documentary role has exactly one canonical
   location. If a change moves which document owns a fact, the map updates in
   the same round.
2. **Claim provenance.** A statement about code is verified by reading or
   running the code; about a third party, by executing against it. A diagnosis
   from an error message alone is written as `hypothesis` — literally, so it is
   greppable — until executed.
3. **Expiring facts.** Status markers, "blocked on X", "next up" are claims with
   a shelf life. Re-evaluate any that the round touches.
4. **Nothing left hanging.** Anything at P0/P1 lands in a tracked item, never
   only in commit prose or a code comment. A comment referencing a tracked item
   requires that item to exist.
5. **ADR integration, not ADR count.** An accepted ADR is referenced from the
   architecture document *and* its pending work is sequenced in the plan. An
   ADR that exists only as a file is not integrated.

**STOP**: rewriting a dated CHANGELOG entry, renumbering or deleting an ADR, or
editing an accepted ADR's original claims. History is immutable; corrections are
appended (see the ADR format conventions).

---

## QA-6 — Release (CONSULT, with STOP points)

**Preconditions**

- Every applicable gate green **on the release commit** — not on an ancestor,
  not on a similar branch.
- CI verified green by reading CI, not by inference from a local run.
- CHANGELOG reflects the actual commit range.
- Model cards current for every deployed model.

**STOP points**

1. Releasing with any gate red.
2. Releasing without verified-green CI.
3. Any change to a production model's promotion status.

**Evidence**: the CI run URL, gate outputs, and the diff range being released.

---

## QA-7 — Incident and rollback (STOP)

Every step requires authorisation. The procedure's purpose is to make the fast
path also the recorded path — under incident pressure, an unrecorded action is
the one nobody can undo.

1. Stabilise first; diagnose second. Rollback precedes root cause.
2. Capture evidence **before** mutating state. A restarted pod has destroyed
   the evidence.
3. Record every action with its timestamp, as it happens.
4. Blameless post-mortem with action items, each carrying an owner and a date.
   An action item without both is a wish.

---

## Cadence

| Procedure | When |
|---|---|
| QA-1 Change verification | Every change |
| QA-2 Test authoring | Whenever tests are written |
| QA-5 Doc coherence | Every round that touches documentation |
| QA-3 Metric review | Every threshold change; recurring |
| QA-4 Independent audit | Before each phase completion, and before any milestone |
| QA-6 Release | Every release |
| QA-7 Incident | On incident |

QA-4's cadence is deliberately tied to **phase boundaries** rather than to
elapsed time: the risk being managed is a phase declared complete on claims
nobody executed.
