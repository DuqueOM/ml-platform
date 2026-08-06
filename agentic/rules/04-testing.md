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

## Gates report what they examined

Not only their verdict. A check reporting "0 files examined" has passed without
testing anything, and only the count reveals it.
