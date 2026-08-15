# Validation log

Dated record of what was actually executed against this repository, the layer
each run earns, and what it proved. One line per validation event.

## Why this file is not the status document

`docs/architecture/implementation-status.md` answers *what is true now*. It is
regenerated from the filesystem on every commit, so it has no memory: a
component that was green last month and is green today looks identical to one
that has never been anything else.

This file is the other half — *what was run, when, and by whom*. It is written
by hand and appended to, never regenerated, because its value is precisely
that it records events a derived document cannot reconstruct. A cluster
rollout leaves nothing in the tree; a cloud deployment leaves nothing in the
tree; the only trace either can have is one somebody wrote down.

The two disagree if either is wrong, and that disagreement is the point.

## The layers

Identical to `docs/architecture/implementation-status.md`, deliberately — a
second vocabulary for the same distinction would let a claim be upgraded by
translation.

| Layer | Proves | Where it can run |
| --- | --- | --- |
| **L1** | Contract: the test suite passes | CI |
| **L2** | Component: the thing executes — a generator renders, a gate runs, a build completes | CI |
| **L3** | Cluster: it starts and answers in kind | A machine with Docker |
| **L4** | Cloud: a real rollout on GKE or EKS | A cloud account |

**The layer is derived from the command that ran, never chosen.** An entry
recording L3 must name a command that requires a cluster. An entry recording
L4 must name a command that requires an account and produces a bill. This is
the rule the whole log rests on; without it the column is an opinion with a
letter in front of it.

## How to add an entry

Append a row. Do not edit an existing one — a validation that turned out to
prove less than it claimed gets a new row saying so, dated, with the old row
left standing. The error is usually more instructive than the correction, and
a log that can be edited silently is a log nobody can rely on.

Each row needs:

- **Date** — ISO, the day the command ran, not the day it was written up.
- **Commit** — the short SHA the command ran against. A validation with no
  commit is a memory.
- **Command** — verbatim and runnable. Not a description of it.
- **Layer** — derived from that command.
- **Result** — what it proved, or what it failed to prove. "Green" is not a
  result; "the pod reached Ready against the probes it declares" is.

## Log

| Date | Commit | Command | Layer | Result |
| --- | --- | --- | --- | --- |
| 2026-08-14 | `27bcd0a` | independent audit, QA-4 round three (separate session) | — | Third audit. Found probes naming routes the service does not serve, metrics nobody collected, and `check_thresholds` unable to fail in CI. Recorded in `AGENTS.md`; C7 counts drift from this commit. |
| 2026-08-14 | `1e359bd` | `uv run python scripts/check_implementation_status.py --check` | L2 | The verification pool runs 42 commands concurrently and produces one document across three runs. Exposed a test writing a probe file into the repository other tests were reading. |
| 2026-08-14 | `f5ec6cb` | `git -C <upstream checkout> ls-files`, inside and outside a commit hook | L2 | 840 paths against 1025: the parity gate's upstream read obeyed an inherited `GIT_DIR` and reported on this repository. Fixed and pinned by a test. |

## What is not here, and why that is the useful part

**L4 is not validated, and no row claims otherwise.** Nothing has run in a
cloud; zero components sit at L4. The
Terraform for GKE and EKS renders and validates offline and has never
provisioned anything; there is no deploy workflow; the six cloud overlays have
never been applied. `docs/environment-promotion.md` names the five things that
must exist before an L4 row can honestly be written.

**The six cloud overlays are not validated at L3 either**, for the same
reason. `local` is the only overlay with a path to L3, through
`make local-verify`.

An empty column is evidence. A log that fills its bottom rows by lowering what
they mean has stopped being one.

## Related

- `docs/architecture/implementation-status.md` — what is true now, derived
- `docs/environment-promotion.md` — the path an L4 row would have to travel
- `docs/PROGRESSION.md` — which stage produces which layer
- `AGENTS.md` — the independent audit marker C7 measures drift against
