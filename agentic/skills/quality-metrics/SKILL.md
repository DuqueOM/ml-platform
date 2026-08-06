---
name: quality-metrics
description: Keep every published quality claim tied to a command that can fail a build — audit the claim/gate mapping in both directions, verify gates actually fail, and treat threshold changes as recorded decisions.
when_to_use: >
  When adding or changing a quality claim or a gate threshold, when a metric is
  reported but nothing depends on it, or on the recurring metric review.
  Examples: 'add a coverage gate', 'lower this threshold', 'do our metrics
  mean anything?'.
mode: AUTO to audit; CONSULT to add a gate; STOP to lower a threshold
---

# quality-metrics

Implements [ADR-005](../../../docs/decisions/ADR-005-agentic-governance.md)
rule K and procedure QA-3.

## The rule

> **Every published quality claim maps to a command that can fail a build.**

A metric that is measured and reported but cannot fail is **decoration**: it
reassures without constraining. There are only two valid responses to one —
remove the claim, or promote the metric to a gate. There is no third option,
because the third option is a number nobody is accountable for.

For any claim of the form "this repository does X well":

1. A **command** evaluates X.
2. It **exits non-zero** when X is not true.
3. It runs in **CI**, not only locally.
4. Its **threshold** is recorded with the reason it holds that value.

## Auditing the mapping — both directions

Run the script first:

```bash
uv run python scripts/check_doc_coherence.py     # check C4
```

Then check what it cannot:

| Direction | Finding when it fails |
| --- | --- |
| README claim → gate row | An unenforced claim. Either remove it or gate it |
| Gate row → command exists and runs | A row referencing a command nobody can run is worse than no row: it looks like coverage |
| Gate → actually runs in CI | A local-only gate is a suggestion |
| Threshold → recorded reason | A number nobody owns; it will be lowered by whoever it first blocks |

## Gates that have never failed

For each, decide which is true:

- **The risk is genuinely absent** — record that, and consider whether the gate
  earns its runtime.
- **The gate does not work.**

Distinguish them by running the gate against known-bad input. This is the
single highest-yield check in this skill, because a broken gate is
indistinguishable from a passing one until the day it matters.

A real example of the second case: a documentation check filtered files by
matching a directory name against the **absolute** path. The repository lived
under a directory with that name, so every file was excluded and the check
passed while examining nothing. Its output — "0 files checked" — was the only
evidence, and only because the count was printed.

**Gates should report what they examined, not only their verdict.** A count of
zero is a finding.

## Thresholds are decisions

Every threshold carries the reason it holds its value. A threshold inherited
from an example is an undocumented decision, and the first time it blocks
something legitimate it will be lowered by whoever is blocked — with no record
that a decision was reversed.

Good reasons are external or derived:

- `disparate impact ratio ≥ 0.80` — the four-fifths rule, a recognised
  reference rather than a number chosen here.
- `libs/ coverage ≥ 90%` — widest blast radius; an untested path reaches every
  consumer.
- `p99 < X ms` — the SLO published to users.

Bad reasons: "it is what we currently pass", or silence.

### Lowering a threshold is STOP

Always allowed, never automatic. Requires a recorded reason and a named
decision-maker. The alternative is thresholds that decay toward whatever
happens to pass, which is how a quality bar disappears without anyone deciding
to remove it.

Raising a threshold is CONSULT: confirm it does not turn normal variation into
a false failure, which trains people to bypass gates.

## Adding a gate

1. Write the claim as a sentence someone could dispute.
2. Write the command that would settle the dispute.
3. **Verify it fails on known-bad input.**
4. Add the row to `docs/governance/quality-gates.md` with the threshold's
   rationale.
5. Wire it into CI.

Step 3 is the one that gets skipped and the one that matters.

## Output

- Claims with no gate, and gates with no claim.
- Gates that have never failed, with the result of running each against
  known-bad input.
- Thresholds whose recorded reason has expired.
- Gates bypassed more than once — mis-specified, not under-enforced.
