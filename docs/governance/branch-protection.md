# Branch protection: the configuration, and what it does not buy

`scripts/setup_branch_protection.sh` is the authority — this document explains
what it applies and, more usefully, where the protection stops.

## What is configured on `main`

| Setting | Value | What it means |
| --- | --- | --- |
| `required_status_checks` | all four CI jobs | A red job blocks the merge |
| `strict` | true | The branch must be current with `main` before merging |
| `enforce_admins` | **true** | The rules apply to the repository owner too |
| `required_approving_review_count` | **0** | No human approval is required |
| Force pushes | blocked | History on `main` cannot be rewritten |
| Deletions | blocked | `main` cannot be deleted |

Apply it with:

```bash
bash scripts/setup_branch_protection.sh          # dry run, prints the payload
bash scripts/setup_branch_protection.sh --apply  # idempotent
```

## The part worth reading: a review requirement with one reviewer is not a control

`required_approving_review_count` is 0, and this repository has **one
maintainer**. Those two facts interact in a way that is easy to state and easy
to forget:

**Raising the count to 1 would not add a control.** The only person who could
approve is the person who wrote the change. A review requirement that its own
subject satisfies is a mechanism with the shape of a control and none of the
substance — and the shape is the dangerous half, because a reader seeing
"reviews required: 1" concludes something false.

So the count stays at 0, deliberately, and the honest statement is here rather
than in a setting.

**What carries the weight instead** is `required_status_checks` with
`enforce_admins: true`. The gates cannot be waved through by the owner, and
they are the thing that has actually caught defects: probes naming routes the
service does not serve, a threshold gate unable to fail, six spellings of CI
suppression, a security baseline gate reading one key of three. None of those
would have been caught by a second pair of eyes on the diff, and all of them
were caught by a command.

**What is genuinely missing** is independent review, and it is supplied by a
different mechanism: check C7 forces an independent audit in a separate
session, and fails once too many commits land behind the last one. That is the
control that does what a review count cannot, and it is the one to defend if
this ever needs to be traded off.

## When this changes

Add `required_approving_review_count: 1` **the day a second maintainer
exists**, and not before. Until then the setting would record an intention
rather than enforce a rule.

If this repository ever accepts outside contributions, revisit before the
first one merges — an external PR is the case where a review count stops being
theatre.

## Related

- `scripts/setup_branch_protection.sh` — the applied configuration
- `docs/governance/qa-procedures.md` — QA-4, the independent audit
- `RUNBOOK.md` — C7, and why you cannot clear it yourself
- `SECURITY.md` — which checks block and which only report
