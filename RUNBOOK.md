# Operations runbook

Operating the platform itself: what to do when a gate fails, how to read the
documents that are generated rather than written, and where the record of what
happened lives.

This is not a runbook for a deployed service — nothing here has ever run in a
cloud, and `docs/runbooks/` holds the per-technology recovery procedures as each
Core-tier tool lands. This is the runbook for the repository.

New here? [`QUICK_START.md`](QUICK_START.md) first. Committing?
[`CONTRIBUTING.md`](CONTRIBUTING.md) has the cadence and the order that bites.
Tagging? [`docs/RELEASING.md`](docs/RELEASING.md).

## Quick reference

| Operation | Command |
| --- | --- |
| Install | `uv sync --all-packages --all-extras` |
| Full suite | `uv run pytest -q` |
| Repository gates | `make verify` |
| Regenerate derived documents and agentic surfaces | `make sync` |
| List the entry points | `make help` |
| Is every tool present, and what does each absence cost | `bash scripts/bootstrap.sh --check` |
| Are the git hooks installed and wired | `bash scripts/dev-setup.sh --check` |
| Local stack up / down | `make local-up` / `make local-down` |
| Service into the local cluster | `make local-serve` |
| Assert the local stack works | `make local-verify` |
| Cluster-level tests only | `uv run pytest tests/local -q -m local` |
| Watched thresholds | `uv run python scripts/check_thresholds.py --show` |
| Audit trail integrity | `uv run python scripts/audit_record.py --verify` |

Both `--check` scripts are read-only and say so in their closing line. They are
the fastest way to find out why a gate behaves differently on your machine than
in CI, and neither installs anything.

## Run the gates directly

**`uv run python scripts/<gate>.py` is the reliable way to run any gate**, and
the table below is the full list. Prefer it over both wrappers:

- `make verify` is a **subset of CI, not a mirror of it**, despite what its
  help text says (see below), and it stops at the first failure — which is
  currently C7, so it cannot reach the end.
- `pre-commit` invokes a *differently scoped* copy of several of the same
  checks (see below), so a red hook is not evidence that a gate is red.

Running the gate you care about, by itself, is the only invocation whose result
means exactly one thing.

### What `make verify` leaves out

CI additionally runs `uv lock --check`, the upstream-parity ledger, clock
isolation, both coverage floors, the cloud-surface budget, `kubectl kustomize`
over every overlay, the threshold gate, the MCP registry, the project
generator, Checkov, Kubescape, Trivy and gitleaks over full history. It also
runs `mypy` over `libs/ scripts/ projects/demand-forecast/src/`, where
`make verify` checks only `libs/` — and `scripts/` is where the code enforcing
every other claim in this document lives. A type gate that covers less than it
appears to is this repository's most-repeated defect;
`tests/test_type_gate_scope.py` exists because it had already happened three
times. `.github/workflows/ci.yml` is the authority on what must pass.

### Where pre-commit fits

The hooks are installed by `bash scripts/dev-setup.sh` and verified by
`bash scripts/dev-setup.sh --check`, which reports whether
`.git/hooks/pre-commit` and `.git/hooks/commit-msg` are wired to pre-commit.
That much is worth having: the conventional-commit check and the formatters
catch cheap mistakes at the cheapest moment.

`pre-commit run --all-files` is **red on a clean checkout**, and the count is
not the point — the composition is. Measured on `main`, three hooks fail for a
scope defect and one fails correctly: `no-commit-to-branch` blocks `main`,
which is the hook working, not a finding. Confusing the two is how a correct
hook gets disabled alongside a broken one.

The three scope defects are recorded as open findings, each hook named and its
cause diagnosed, in
[`docs/architecture/technical-plan.md`](docs/architecture/technical-plan.md#open-findings-from-the-parity-work--measured-not-yet-fixed).
The common shape: the hook's file scope was never given the exclusions that
ruff, coverage and the CI steps were argued into having, so it lints generator
source that is Jinja rather than YAML, and type-checks a directory set CI does
not.

That is a defect in the hook configuration, and the fix belongs in
`.pre-commit-config.yaml` — bringing each hook's scope into line with the CI
step it shadows. **A hook set that cannot pass is one people route around**,
and the routes around it are worse than the hooks: skipping verification
wholesale to get past a check that was never about your change. So this
document does not print one. If a hook disagrees with the gate it shadows, run
the gate directly, then fix the hook's scope.

### What skipping the hooks costs, measured

`--no-verify` is available and this document does not tell you never to use
it. It tells you what it costs, because the cost is counter-intuitive and was
paid seven times in one working session before anyone wrote it down.

The `implementation-status` hook takes about nine minutes: it runs 42
verification commands to derive the document. Skipping it to save those nine
minutes cost fifteen every time, because **the hook does not only check the
derived documents — it is what keeps them current.** Bypass it and the commit
carries a status document describing the tree as it was before your change,
which CI reports twenty minutes later.

So the rule is an ORDER, not a prohibition:

1. Make the change.
2. Make every small fix it needs — the lint, the format, the conflict.
3. **Then** regenerate the derived documents, over a tree that has stopped
   moving.
4. Verify with `--check`, read the result, and only then commit and push.

Step 3 is the one that gets inverted. Regenerating and *then* fixing a lint
invalidates what you just generated, and the generation takes minutes, so any
edit inside that window lands in the output. That is how a derived document
came to record `Version consistency` as FAILING while it passed: it was
generated during the window in which the failure was being fixed, and it
preserved a state that no longer existed.

Step 4 is the one that gets chained. `verify && push` in one command means you
act before reading the result, which is the same mistake as step 3 wearing a
shell operator.

**When a bypass is defensible.** When the hook blocks work for a reason
unrelated to the change — C7 red on accumulated drift, say — and the bypass is
declared in the commit message with its reason. CI runs the same checks, so
nothing is smuggled past; what a declared bypass buys is that the next reader
knows it happened and why. An undeclared one is indistinguishable from an
oversight.

## When a gate fails

| Gate | Command | A failure means |
| --- | --- | --- |
| Lint / format | `uv run ruff check .` · `uv run ruff format --check .` | Mechanical. `ruff check --fix` and `ruff format` |
| Types | `uv run mypy libs/ scripts/ projects/demand-forecast/src/` | `strict` applies to everything in scope, not only `libs/` — the per-module override that appeared to narrow it never did (mypy applies `strict` globally) |
| Agentic surfaces stale | `uv run python scripts/sync_agentic_adapters.py --check` | A canonical body changed without re-rendering. Fix with `make sync`, never by editing a rendered file. Passing, it reports the artifact and surface counts it checked — 74 across 4 |
| Agentic surface integrity | `uv run python scripts/validate_agentic_surface.py --strict` | V1–V6: missing surface, drifted mirror, policy text in a pointer, an unresolvable authority, or a **de-escalated mode** |
| Documentation coherence | `uv run python scripts/check_doc_coherence.py` | C1–C9; see the table below |
| Derived document stale | `uv run python scripts/check_implementation_status.py --check` | The committed table no longer matches the filesystem. Regenerate — never hand-edit |
| Technology inventory stale | `uv run python scripts/check_technology_inventory.py --check` | Same, for detected technology use |
| Cloud surface | `uv run python scripts/measure_cloud_surface.py --check` | The cloud-specific share of Terraform moved past its ceiling, or the report is stale. Needs a `terraform` binary, which is why it is not in `make verify` |
| CI references | `uv run python scripts/check_ci_references.py` | A workflow names a script that no longer exists — a step that stopped testing anything while staying green |
| Clock isolation | `uv run python scripts/check_test_clock_isolation.py` | A test reads the wall clock, or production code hands git a bare `--since` date. Exemptions are reviewed, not silent — it reports how many it honoured |
| Thresholds | `uv run python scripts/check_thresholds.py` | A gated number moved in the weakening direction. STOP |
| Upstream parity | `uv run python scripts/check_upstream_parity.py` | An artifact `ml-service-template` has that this repository has not decided about. It compares against a ledger of adopted / pending / rejected, so "pending" is a decision recorded, not a gap |
| MCP registry | `uv run python scripts/check_mcp_registry.py` | A server without a declared risk mode or minimum scope, or a committed example config carrying a credential |

**Do not run a gate while the suite is running.** `tests/test_gate_scripts.py`
proves each gate can fail by breaking the repository and putting it back, in
the working tree. A gate run concurrently sees that mutation and reports a
failure that will not reproduce. This is easy to lose an hour to: two derived
documents were reported stale here, and both passed cleanly the moment the
suite finished.

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

C7 fails right now, deliberately, and a fresh clone will show it failing. Run
today, on a tree 38 commits past the recorded audit:

```text
FAIL [C7] 38 commits since the audit on 2026-08-08 (grace: 10).
Recording an audit resets the counter, not a 90-day silence.
```

**Coherence checking is self-review by construction.** It compares documents
with each other and with the filesystem; it cannot detect a claim that is
internally consistent and false, which is the class of defect that produced
this repository's governance rules in the first place — a memory budget
recorded from one sample of a fluctuating quantity, and a benchmark cited to
justify the assumption its own configuration encoded. Both documents were
coherent. Both were wrong, in the direction of confidence.

So [`ADR-005`](docs/decisions/ADR-005-agentic-governance.md) **rule B** —
*self-review is not review* — requires the audit to run in a **separate
session**, against executed evidence. An agent reviewing its own work cannot
find an error it made confidently, and running the audit inside the authoring
session makes it self-review regardless of intent. That is why no amount of
work in the session that wrote the code can turn C7 green: clearing it requires
a second party, not a second command.

The check measures **commit drift before age**: 10 commits since the recorded
audit, then a 90-day ceiling. Drift comes first because a marker dated last
week says nothing about the commits that landed behind it. The drift count
itself is computed by walking every commit date and comparing strings, not by
handing git a `--since` date — `--since` fills the missing time from the
current clock, and the same commit once measured 18 commits at 13:33 and 10 at
21:19, which is a gate that passes on its own late in the evening.

To clear it:

1. Run **QA-4** ([`docs/governance/qa-procedures.md`](docs/governance/qa-procedures.md))
   in a separate session, starting from
   [`docs/governance/audit-brief.md`](docs/governance/audit-brief.md), which is
   written for the auditor: what was asked, what was built, and a ranked list of
   where the author's confidence is weakest. The audit verifies by
   **executing** (rule E — reading a claim is not verification of it), reports
   what works as well as what does not, and is **read-only**. An auditor that
   edits has destroyed the evidence it was sent to collect;
   [`docs/governance/QA-4-independent-audit.md`](docs/governance/QA-4-independent-audit.md)
   is the previous one, and shows the form.
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
is a separate call because it needs a `terraform` binary — it reports the split
it measured (run here: 183 of 268 significant lines cloud-specific, 85 shared,
so **68% adapter**) and fails against the 0.75 ceiling in the threshold list.

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
from the command that ran rather than declared.

| Layer | Proves | Runs where |
| --- | --- | --- |
| L1 | the test suite passes — the contract holds | CI |
| L2 | the thing itself executes — a generator renders, a gate runs, a build completes | CI |
| L3 | it starts and answers in kind | a machine with Docker |
| L4 | a real rollout on GKE or EKS | a cloud account |

**No row generated in CI can ever display L3 or L4**, because CI has neither a
cluster nor a cloud. Where higher-layer evidence exists, the row names the
command that produces it and marks it *not run here* — for example
`make local-up && uv run pytest tests/local/test_local_stack.py -q -m local`.
Running that command locally is how you produce L3 evidence; the document still
will not claim it, because the document reports what CI executed.

That is the operational consequence worth internalising: **L3 is a thing you go
and do**, on a machine with Docker, and it leaves no trace in the derived
document. If you want it recorded, it goes in the audit trail with the commit
it was produced at.

This distinction was not academic. Six Kubernetes overlays rendered green for
weeks while their probes pointed at routes the service does not serve, so no
pod could ever have reached Ready. Everything about them was L2-correct.

L4 is printed at zero on purpose. A taxonomy that hides its empty top row is
how "we deploy to two clouds" goes unchallenged.

## Adding a threshold

Any number a gate fails on must be watched, or it can be lowered in the same
commit as the change that made it fail — every gate green, the standard quietly
moved. Nine numbers are watched today, from coverage floors to the audit grace
in commits; `--show` prints the list.

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
also compares the file against its committed form in git. Run here it reported
`OK — 56 entries, chain intact`.

Record anything consequential and not otherwise reconstructable: a threshold
accepted downward, an independent audit, an L3 run and what it proved, a
dependency review that rejected a proposed upgrade, a promotion. Entries are
never edited or deleted.

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
old and new pod to coexist — double the memory — and each of these is a single
replica over `emptyDir`, so a rolling update buys no availability while costing
twice the budget. If you add a component, give it `Recreate` and a limit, and
raise the budget deliberately rather than raising the ceiling.

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
| What is known-broken and not yet fixed | the open-findings section of the technical plan |
| What happened, and on what evidence | `ops/audit.jsonl` |
| Everything else | [`AGENTS.md`](AGENTS.md) |
