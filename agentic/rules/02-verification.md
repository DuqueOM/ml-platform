# 02 — Verification

**Authority**: `AGENTS.md` + [ADR-005](../../docs/decisions/ADR-005-agentic-governance.md)
**Applies to**: every claim written anywhere in this repository

## Claims carry their provenance

| Claim about | Verified by | Never by |
| --- | --- | --- |
| Code behaviour | Reading or running the code | An error message, or a memory of one |
| Third-party behaviour | Executing against it | Its documentation alone |
| A measurement | **Repeated** observation, method recorded | A single reading |
| A benchmark | A run whose configuration does not presuppose the conclusion | A prior run under other assumptions |

A conclusion drawn from a symptom rather than an execution is written as
`hypothesis` — literally, so it is greppable — until executed.

## A single reading is not a measurement

A number written without its sampling method is unverified however precise it
looks. Where a budget or a gate depends on a measurement, record the command
that produced it next to the value, so revising it forces re-measuring the same
way.

## A benchmark cannot test its own assumption

If a run was configured because of what it was expected to show, it has
measured that expectation. Check the flags before citing the result.

## Never report unexecuted work as done

If tests fail, say so with the output. If a step was skipped, say which. If
something is verified, state it plainly with the command.
