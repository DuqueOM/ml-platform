# Operations runbook

Operating the platform itself: what to do when a gate fails, how to read the
documents that are generated rather than written, and where the record of what
happened lives.

This is not a runbook for a deployed service — nothing here has ever run in a
cloud, and `docs/runbooks/` holds the per-technology recovery procedures as
each Core-tier tool lands. This is the runbook for the repository.

New here? [`QUICK_START.md`](QUICK_START.md) first. Committing?
[`CONTRIBUTING.md`](CONTRIBUTING.md) has the cadence and the order that bites.

## Quick reference

| Operation | Command |
| --- | --- |
| Install | `uv sync --all-packages --all-extras` |
| Full suite | `uv run pytest -q` |
| Repository gates | `make verify` |
| Regenerate derived documents and agentic surfaces | `make sync` |
| List the entry points | `make help` |
| Local stack up / down | `make local-up` / `make local-down` |
| Service into the local cluster | `make local-serve` |
| Assert the local stack works | `make local-verify` |
| Cluster-level tests only | `uv run pytest tests/local -q -m local` |
| Watched thresholds | `uv run python scripts/check_thresholds.py --show` |
| Audit trail integrity | `uv run python scripts/audit_record.py --verify` |

## When a gate fails

`make verify` runs the gates in sequence and stops at the first failure. **It
is a subset of CI, not a mirror of it**, despite what its help text says: CI
additionally runs `uv lock --check`, the upstream-parity ledger, clock
isolation, both coverage floors, the cloud-surface budget, `kubectl kustomize`
over every overlay, the threshold gate, the MCP registry, the project
generator, Checkov, Kubescape and gitleaks over full history. It also runs
`mypy` over `libs/ scripts/ projects/demand-forecast/src/`, where `make verify`
checks only `libs/` — `scripts/` holds the code enforcing every other claim
here, and 26 type errors once sat in it while the step reported green.
`.github/workflows/ci.yml` is the authority on what must pass.

`make verify` also **cannot currently reach the end**, because check C7 is red
by design (below). Run the individual gate you care about instead of reading a
red `make verify` as a verdict on your change.

| Gate | Command | A failure means |
| --- | --- | --- |
| Lint / format | `uv run ruff check .` · `uv run ruff format --check .` | Mechanical. `ruff check --fix` and `ruff format` |
| Types | `uv run mypy libs/ scripts/ projects/demand-forecast/src/` | `libs/` is strict; an error there reaches every consumer |
| Agentic surfaces stale | `uv run python scripts/sync_agentic_adapters.py --check` | A canonical body changed without re-rendering. Fix with `make sync`, never by editing a rendered file |
| Agentic surface integrity | `uv run python scripts/validate_agentic_surface.py --strict` | V1–V6: missing surface, drifted mirror, policy text in a pointer, or a **de-escalated mode** |
| Documentation coherence | `uv run python scripts/check_doc_coherence.py` | C1–C9; see the table below |
| Derived document stale | `uv run python scripts/check_implementation_status.py --check` | The committed table no longer matches the filesystem. Regenerate — never hand-edit |
| Technology inventory stale | `uv run python scripts/check_technology_inventory.py --check` | Same, for detected technology use |
| Cloud surface | `uv run python scripts/measure_cloud_surface.py --check` | The cloud-specific share of Terraform moved, or the report is stale |
| CI references | `uv run python scripts/check_ci_references.py` | A workflow names a script that no longer exists — a step that stopped testing anything while staying green |
| Clock isolation | `uv run python scripts/check_test_clock_isolation.py` | A test reads the wall clock, or production code hands git a bare `--since` date |
| Thresholds | `uv run python scripts/check_thresholds.py` | A gated number moved in the weakening direction. STOP |
| Upstream parity | `uv run python scripts/check_upstream_parity.py` | An artifact `ml-service-template` has that this repository has not decided about |
| MCP registry | `uv run python scripts/check_mcp_registry.py` | A server without a declared risk mode or minimum scope |

### Documentation coherence, check by check

`scripts/check_doc_coherence.py` prints every check it ran, passing or failing,
with what it examined. That output is the point: a filter here once matched
against absolute paths, examined **zero files**, and passed.

| Check | What it enforces | When it fails |
| --- | --- | --- |
| C1 | Every ADR on disk is in the index, and none vanished since HEAD | Add the index row. A deletion or renumber is STOP — supersede instead |
| C2 | No document cites an ADR number that does not exist | Fix the citation. Inherited numbering is namespaced `template-ADR-NNN` |
| C3 | An accepted ADR is referenced from the plan or the index | Integrate the decision, or it is a document nobody will find |
| C4 | Every quality-gate row carries a command that resolves and a threshold rationale | Add the command, or delete the claim. A metric that cannot fail is decoration |
| C5 | The agentic counts in `AGENTS.md` match the filesystem | Update the count after adding a rule, skill or workflow |
| C6 | Public-repo hygiene: no link to a non-public repository, no denylisted private name | Remove the reference. The name is never printed — printing it would publish it in the CI log |
| C7 | The independent-audit marker is fresh | See below. Not clearable from the session doing the work |
| C8 | `CHANGELOG.md` has a non-empty `[Unreleased]` while commits accumulate | Write the entry |
| C9 | Every copier command in a fenced block names a `--vcs-ref` | Pin it. Unpinned, copier resolves to the highest-sorting tag; upstream that destroyed a real service, deleting 582 files including the answers file it would have needed to recover |

C6 and C9 scan **fenced blocks and tracked markdown**, including this file, so
a command you document here is held to the same rule as one you run.

### C7, and why you cannot clear it here

C7 fails right now, deliberately, and a fresh clone will show it failing:

```text
FAIL [C7] 37 commits since the audit on 2026-08-08 (grace: 10).
Recording an audit resets the counter, not a 90-day silence.
```

**Coherence checking is self-review by construction.** It compares documents
with each other and with the filesystem; it cannot detect a claim that is
internally consistent and false, which is the class of defect that produced
this repository's governance rules in the first place — a memory budget
recorded from one sample of a fluctuating quantity, and a benchmark cited to
justify the assumption its own configuration encoded. Both documents were
coherent. Both were wrong, in the direction of confidence.

So [`ADR-005`](docs/decisions/ADR-005-agentic-governance.md) **rule B** requires
the audit to run in a **separate session** from the work it audits. An agent
reviewing its own output cannot find an error it made confidently, and running
the audit inside the authoring session makes it self-review regardless of
intent. That is why no amount of work in the session that wrote the code can
turn C7 green: clearing it requires a second party, not a second command.

The check measures **commit drift before age**: 10 commits since the recorded
audit, then a 90-day ceiling. Drift comes first because a marker dated last
week says nothing about the 37 commits that landed behind it.

To clear it:

1. Run **QA-4** ([`docs/governance/qa-procedures.md`](docs/governance/qa-procedures.md))
   in a separate session, starting from
   [`docs/governance/audit-brief.md`](docs/governance/audit-brief.md), which is
   written for the auditor: what was asked, what was built, and a ranked list
   of where the author's confidence is weakest. The audit verifies by
   **executing**, reports what works as well as what does not, and is
   **read-only** — an auditor that edits has destroyed the evidence it was sent
   to collect.
2. Record it: `uv run python scripts/audit_record.py --action audit --target
   ml-platform --mode AUTO --outcome completed --evidence "<findings and the
   commit audited>"`.
3. Update `Last independent audit: YYYY-MM-DD` in `AGENTS.md`.

Note that the test suite **tolerates a C7-only failure and the gate does not**.
`tests/test_gate_scripts.py` skips when every reported failure carries `[C7]`,
so `uv run pytest -q` stays green on a checkout where nobody can run a second
session — while `make verify` and CI still fail. If that skip ever fires
alongside another `[C7]`-free failure, the suite reports it normally.

## The derived documents

Three documents are generated from the repository and **must never be
hand-edited**. Editing a tick into a status table does not make something true,
and the gate notices.

| Document | Derived from | Regenerate | Check |
| --- | --- | --- | --- |
| `docs/architecture/implementation-status.md` | the filesystem plus each component's verification command | `uv run python scripts/check_implementation_status.py --write` | `--check` |
| `docs/architecture/technology-inventory.md` | detected **use** of each declared technology | `uv run python scripts/check_technology_inventory.py --write` | `--check` |
| `docs/architecture/cloud-surface.md` | the ratio of cloud-specific to cloud-agnostic Terraform | `uv run python scripts/measure_cloud_surface.py --write` | `--check` |

`make sync` runs the first two together with the agentic re-render. The third
is a separate call because it needs a `terraform` binary.

**Stage before regenerating.** The generators derive from what git knows about,
so a new directory is invisible until it is staged. The full cadence and the
reason it is ordered that way are in
[`CONTRIBUTING.md`](CONTRIBUTING.md#the-cadence-in-this-order); the short
version is that regenerating first produces a document describing a repository
without your newest work, and CI then calls the committed copy stale.

### How to read the status document

Three markers, and one column most status tables do not have.

`✅` exists and its gate passes · `🟡` exists and something named below it is
missing · `⬜` **absent**, not "planned".

The **Layer** column carries how far the evidence reaches, and it is derived
from the command that ran rather than declared: a `pytest` proves the contract
(L1), anything else that executes proves the component (L2), a kind cluster
proves it starts and answers (L3), a real rollout proves the cloud (L4).

| Layer | Proves | Runs where |
| --- | --- | --- |
| L1 | the test suite passes | CI |
| L2 | the thing itself executes — a generator renders, a gate runs, a build completes | CI |
| L3 | it starts and answers in kind | a machine with Docker |
| L4 | a real rollout on GKE or EKS | a cloud account |

**No row generated in CI can ever display L3 or L4**, because CI has neither a
cluster nor a cloud. Where higher-layer evidence exists, the row names the
command that produces it and marks it *not run here* — for example
`make local-up && uv run pytest tests/local/test_local_stack.py -q -m local`.
Running that command locally is how you produce L3 evidence; the document still
will not claim it, because the document reports what CI executed.

This distinction was not academic. Six Kubernetes overlays rendered green for
weeks while their probes pointed at routes the service does not serve, so no
pod could ever have reached Ready. Everything about them was L2-correct.

L4 is printed at zero on purpose. A taxonomy that hides its empty top row is
how "we deploy to two clouds" goes unchallenged.

## Adding a threshold

Any number a gate fails on must be watched, or it can be lowered in the same
commit as the change that made it fail — every gate green, the standard quietly
moved.

1. Write the gate, then **break what it guards and watch it fail**, then put it
   back. Record that in the commit message. A coherence filter matching
   absolute paths examined zero files and passed; a mypy override matching no
   modules enforced nothing and stayed green. Neither would have been found any
   other way.
2. Add a `Threshold(...)` entry to `THRESHOLDS` in
   `scripts/check_thresholds.py`: the name an operator would use, the
   repo-relative file, a regex with **one** capturing group around the number,
   and `higher_is_stricter`. Get that last flag right — it is `True` for a
   coverage floor and `False` for a ceiling such as the cloud-surface budget,
   and backwards it makes the check applaud the weakening.
3. Confirm it is found: `uv run python scripts/check_thresholds.py --show`
   prints every watched number with its direction and file. A pattern that
   stops matching is reported as a failure, because deleting a threshold is the
   cheapest way to lower it.
4. Record the reason for the value in
   [`docs/governance/quality-gates.md`](docs/governance/quality-gates.md).
   A threshold copied from an example is an undocumented decision, and the
   first time it blocks something legitimate whoever is blocked will lower it
   with nothing recording that a decision was reversed.

The baseline is **git HEAD**, not a committed list of expected values — a list
is another literal, editable in the same commit as the threshold it claims to
protect.

Lowering one is a **STOP** operation. It is not forbidden, it is made visible:
re-run with `--accept "<reason>"` and record the decision in the audit trail.
A gate nobody can ever change is one people route around.

## The audit trail

`ops/audit.jsonl` — one JSON object per line, **append-only and hash-chained**.
A session ends and its context is gone; what remains is what was written down.
Without it, "who promoted that model, and on what evidence" is answered by
reconstructing commit messages.

```bash
uv run python scripts/audit_record.py --action promote --target demand-forecast \
  --mode CONSULT --outcome approved --evidence "gates green at <sha>"
uv run python scripts/audit_record.py --verify
```

`--evidence` is required and refuses to be empty: an entry without it records a
claim, and the trail exists to hold evidence rather than claims. `--mode` is
one of AUTO, CONSULT, STOP.

Each entry hashes itself together with the previous one, so editing any entry
breaks every hash after it and `--verify` reports **where** history diverged
rather than merely that it did. The chain alone cannot detect **truncation** —
dropping entries off the end leaves every remaining link valid — so `--verify`
also compares the file against its committed form in git.

`--verify` reported `55 entries, chain intact` at commit `284efe7`.

Record here anything consequential and not otherwise reconstructable: a
threshold accepted downward, an independent audit, a dependency review that
rejected a proposed upgrade, a promotion. Entries are never edited or deleted.

## The local stack

`platform/local/` is a single-node kind cluster carrying Postgres with
pgvector, MinIO, an OTel collector, Jaeger, Prometheus and Grafana.
[`QUICK_START.md`](QUICK_START.md#part-two--a-pod-answering-a-request) has the
first run; [`platform/local/README.md`](platform/local/README.md) has the
component-by-component reasoning and — more usefully — the explicit table of
what a local run **cannot** prove.

Two operational rules worth repeating outside that document:

**The memory budget is enforced twice.** Every limit in
`platform/local/budget.yaml` is also a Kubernetes limit, so a component that
exceeds its share dies with an attributable cause instead of the node evicting
something else — an eviction names the victim, not the culprit. Raising
`max_utilisation` to make `make local-preflight` pass converts a clear refusal
into an OOM kill minutes later, aimed at your IDE.

**The quota is exactly the declared budget, so rolling updates cannot fit.**
Every deployment there uses `strategy: Recreate`. A `RollingUpdate` needs the
old and new pod to coexist — double the memory — and each of these is a
single replica over `emptyDir`, so a rolling update buys no availability while
costing twice the budget. If you add a component, give it `Recreate` and a
limit, and raise the budget deliberately rather than raising the ceiling.

`make local-verify` asserts these rather than assuming them; all three
historical failures it encodes were found on the stack's first run.

## Adding a vertical

Generate it, never copy a directory: a copied project has an answers file
pointing at the wrong template, so `copier update` can never reach it again and
every generator improvement has to be applied by hand.
[`docs/EXPORTING.md`](docs/EXPORTING.md) is the procedure and
[`docs/PROJECT_CONTRACT.md`](docs/PROJECT_CONTRACT.md) is what the result must
satisfy. Note that P6 — the quality gates — arrives unsatisfied **on purpose**,
and that a test asserts the `TODO`s are still there so nobody can quietly fill
them with plausible defaults.

## Where a fact lives

One place, and everything else points at it. A number restated outside the
thing that derives it will diverge from it.

| Question | Canonical source |
| --- | --- |
| What is built, per component, and at which layer | `scripts/check_implementation_status.py` |
| Which technologies are actually used | `scripts/check_technology_inventory.py` |
| What each phase means and must deliver | `docs/architecture/technical-plan.md` |
| How far along a phase is | the status script — never the plan |
| Which gates exist and what each claims | `docs/governance/quality-gates.md` |
| Which gates are green | `scripts/check_doc_coherence.py` and CI |
| What must pass before a merge | `.github/workflows/ci.yml` |
| What happened, and on what evidence | `ops/audit.jsonl` |
| Everything else | [`AGENTS.md`](AGENTS.md) |
