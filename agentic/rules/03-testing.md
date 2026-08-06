# 04 — Testing

**Authority**: `AGENTS.md` + [ADR-005](../../docs/decisions/ADR-005-agentic-governance.md) rule J
**Applies to**: `**/tests/**`, `**/test_*.py`
**Skill**: `test-authoring`

## A test states the regression it catches

If it catches nothing specific, it is coverage theatre. Coverage is a floor,
never evidence of adequacy — a suite at 95% asserting nothing meaningful is
worse than one at 85% that falsifies, because the number invites trust.

## A test is verified to fail without the fix

Non-negotiable, and the step most often skipped, because the test passes and
passing feels like success. The same applies to a gate: run it against
known-bad input. A guard nobody has watched fail is a guard nobody knows works.

## Test doubles share a contract stub

Several hand-written doubles of one production interface drift away from it one
file at a time, and each keeps passing while doing so. Put the shared surface
in one stub and inherit it.

## The pyramid: which level, and when it is REQUIRED

Unit tests are the default and are never optional. The other two levels are
required by a **trigger**, not by taste — "when it feels necessary" is how they
never get written.

| Level | Required when | Proves what unit tests cannot |
|---|---|---|
| **Unit** | Always | Logic in isolation |
| **Integration** | Code crosses a boundary it does not own: a database, an object store, a message broker, a cloud API, another service | That the boundary behaves as assumed. A mocked boundary tests the mock |
| **End-to-end** | A user-visible path exists: request → feature lookup → inference → response, or a pipeline from raw data to a promoted model | That the pieces compose. Every unit and integration test can pass while the chain is broken |

Three rules that keep the upper levels honest:

1. **An integration test that mocks its integration is a unit test with a
   misleading name.** It must run against the real dependency — locally that is
   the Phase 1b stack, which exists precisely so this is cheap.
2. **An end-to-end test asserts the OUTCOME, not the steps.** Asserting that
   each stage was called re-tests the code's structure; asserting the final
   prediction, artifact or persisted row tests that it works.
3. **Both levels state what they would catch that the level below would not.**
   If the answer is nothing, the test belongs one level down, where it is
   faster and more precise.

Integration and end-to-end tests are marked (`-m integration`, `-m e2e`) and
excluded from the default run, so the fast suite stays fast. Excluded from the
default run is **not** excluded from CI: a level nobody runs is a level nobody
maintains.

## Gates report what they examined

Not only their verdict. A check reporting "0 files examined" has passed without
testing anything, and only the count reveals it.
