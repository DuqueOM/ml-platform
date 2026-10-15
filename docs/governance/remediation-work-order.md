# Remediation work order — what survived round one

**Base**: `main` @ `c7131a1` · **Source**: independent audit of `16b4711`, re-verified 2026-09-03
**Audience**: an agent session picking up remediation work in this repository.

The 2026-08-29 round closed the P0 and three of the six P1s, each with a gate
that closes the defect class rather than the instance. This document is the
remainder: twenty-four findings it did not touch, written as executable work
with the [AGENTS.md](../../AGENTS.md) AUTO / CONSULT / STOP protocol applied to
each.

Read [AGENTS.md](../../AGENTS.md) and
[ADR-005](../decisions/ADR-005-agentic-governance.md) before starting. This
document states tasks; it does not restate policy, and where the two disagree
AGENTS.md is correct and this file is a defect.

---

## Before you start — five house rules that will reject correct work

1. **Regenerate derived documents last, and stage first.** The generators
   derive from files git knows about, so a new directory is invisible until it
   is staged. Reversing this order has failed three times:

   ```bash
   git add -A
   uv run python scripts/check_implementation_status.py --write
   uv run python scripts/check_technology_inventory.py --write
   uv run python scripts/measure_cloud_surface.py --write
   uv run python scripts/check_doc_coherence.py
   git add -A
   ```

2. **Corrections are appended, never applied in place.** Rewriting a dated
   `CHANGELOG` entry, renumbering or deleting an ADR, or editing an accepted
   ADR's original claims is **STOP**. W-1 depends on getting this right.

3. **Every gate you add must be watched failing.** Break the thing on purpose,
   confirm the gate goes red, restore, confirm green. A gate nobody has seen
   fail is anti-pattern P-09, and the pull request template asks which
   known-bad input you tried.

4. **Lowering a threshold is STOP; adding one means registering it.** New
   numeric floors go in `THRESHOLDS` in `scripts/check_thresholds.py` as a
   `Threshold(name, file, regex)`, or nothing watches them. Every published
   quality claim also needs a row in
   [quality-gates.md](quality-gates.md) whose command resolves — C4 enforces
   that.

5. **Never hand-edit a file under `.claude/`, `.cursor/`, `.codex/` or
   `.devin/`.** Edit the canonical body in `agentic/` and re-render with
   `scripts/sync_agentic_adapters.py`. And your pull request body must name a
   runnable command for every evidence layer it claims —
   `scripts/check_pr_evidence.py` blocks an L3 claim backed only by a `pytest`.

---

## Wave 1 — close the audit honestly

Two items, both small, both about this repository's own integrity claims. Do
them first: until W-1 lands the platform has no valid measurement of its
primary metric, and until W-2 lands the hash-chained trail carries no record
that any of this happened.

### W-1 — Re-measure the forecast and publish the corrected figure

**Mode**: AUTO · **Closes**: the last third of F-01 · **Size**: ~1h

`to_hourly_demand()` was fixed to densify the panel, but nothing re-ran the
backtest. `CHANGELOG.md` still carries **+55.8% skill** as the platform's
headline claim, and that number was produced by the mis-specified baseline. It
is now known-invalid with no replacement.

**The Iceberg table is stale in the same way.** `data/iceberg/catalog.db`
points at a snapshot written before the fix, so it holds the sparse panel. Do
not measure from `read_demand()` without re-ingesting first — that reproduces
the old shape and reports it as the new one.

Steps:

1. Fetch the two months the register declares (`2024-01`, `2024-02`).
   `data/raw/` is empty as of this writing.

   ```bash
   uv run python scripts/datasets/fetch.py nyc-tlc
   ```

2. Measure from the files rather than from the lakehouse — this needs no
   Docker and no MinIO:

   ```bash
   uv run python -c "
   from pathlib import Path
   import polars as pl
   from demand_forecast.ingest import ingest_file, to_hourly_demand
   from demand_forecast.train import evaluate
   frames = [ingest_file(p)[0] for p in sorted(Path('data/nyc-tlc').glob('yellow_tripdata_2024-0*.parquet'))]
   demand = to_hourly_demand(pl.concat(frames))
   print(evaluate(demand).summary())
   "
   ```

   Run it **twice** with the same seed and confirm the numbers are identical.
   AGENTS.md is explicit that a single reading is not a measurement.

3. Re-ingest the lakehouse so the stored table matches the fixed shape, then
   confirm time travel still reaches the previous snapshot. This needs
   `make local-up`. Record the new snapshot id.

4. Publish by **appending** a new `[Unreleased]` entry stating the corrected
   skill and coverage, the row count, the number of modellable zones and the
   fold design. Leave the dated `+55.8%` entry untouched.

5. Update `projects/demand-forecast/model-card.md` with the new figures, then
   run the derived-document sequence from the house rules above.

**Expect the number to fall, possibly a lot.** The correct baseline is roughly
three times stronger than the broken one. If the corrected skill lands under
`MIN_SKILL = 0.05`, that is a real result rather than a failure of this task —
report it and stop. **Lowering `MIN_SKILL` to make it pass is STOP** and
requires a recorded decision-maker.

**Acceptance**: a new CHANGELOG entry names the corrected skill and coverage,
both produced by a command pasted into the pull request body; the dated entry
is byte-identical to before; `uv run pytest projects/demand-forecast -q` and
`uv run python scripts/check_doc_coherence.py` both pass.

### W-2 — Record the audit and its remediation in the hash-chained trail

**Mode**: AUTO · **Size**: ~15min

`ops/audit.jsonl` ends at Round 7 (2026-08-27). `AGENTS.md` still reads
`Last independent audit: 2026-08-27 (35ffdec)`. A round that produced a P0 and
four closed findings has no corroboration in the record — which is exactly the
gap the Round 6 entry was *backfilled* to close, and this repository treated
that as a finding worth recording rather than quietly repairing.

Steps:

1. Append two entries — the audit, then its remediation. Keep them separate:
   they happened at different times, and one is evidence about the other.

   ```bash
   uv run python scripts/audit_record.py \
     --action independent-audit \
     --target "ml-platform @ 16b4711" \
     --mode CONSULT \
     --outcome "1 P0, 6 P1, 13 P2, 9 P3" \
     --evidence "Read-only, executed. P0: lags and the seasonal-naive baseline computed by row offset on a panel never densified to an hourly grid — reproduced at 40% sparsity, lag_24 median 43h and the weekly baseline 293h, reported skill +21.8% to +75.5% on the same generator. P1s: a DAG task body raised AttributeError; the production overlay had no ServiceAccount and consumed no secret; egress was DNS-only; GKE deletion_protection unset so terraform destroy refuses; the serving seam broken by interface AND by a numpy/sklearn version straddle; Terraform provisions no VPC, IAM, storage, database or state backend."
   ```

2. Then the remediation entry, naming what was closed and what was not.

3. Update the `AGENTS.md` line to `2026-08-29 (16b4711)`. The convention is
   explicit: **record the commit the auditor read, not the commit that writes
   the line.**

4. Verify the chain: `uv run python scripts/audit_record.py --verify`.

**Acceptance**: `--verify` reports an unbroken chain; `check_doc_coherence.py`
C7 recomputes drift against `16b4711` and passes.

---

## Wave 2 — the deploy path

F-04 half-done, and the one half of F-06 that is not blocked on another
repository. Both are authoring work needing no cluster.

### W-3 — Give the pod the egress it needs, including the metadata server

> **Status: done** on `fix/c6-ok-above-name-failure` — *feat(k8s): give the serving pod the egress it needs, including the metadata server* added the policy; *fix(k8s): stop commonLabels rewriting the DNS policy's peer selector* fixed the rendered DNS
> selector (round eleven P1); *fix(k8s): the egress test could not fail, and asserted the wrong metadata port* made the egress assertion able to fail and dropped the unused 443 on the
> metadata server. The `monitoring` namespace selector it relies on is round-eleven item R11-1.

**Mode**: AUTO · **Closes**: F-04 · **Size**: ~2h

The Prometheus half was fixed — `allow-serving-ingress` now admits the
`monitoring` namespace on 8000. Egress is still `allow-dns` and nothing else,
so the pod cannot fetch its model, reach Postgres, or export a span.

What the pod actually needs to reach:

| Target | Why | Shape of the rule |
| --- | --- | --- |
| kube-dns | name resolution | already allowed |
| **169.254.169.254** | **Workload Identity and IRSA both mint tokens here.** Without it, the identity the last round wired up fails to authenticate | `ipBlock: 169.254.169.254/32`, TCP 80/443 |
| Object storage | the model artifact and the Iceberg table | GCS and S3 are public endpoints, and NetworkPolicy cannot match a hostname — so an `ipBlock` to 443, or a Private Service Connect / VPC endpoint CIDR |
| OTLP collector | `tracing.py` exports spans over gRPC | namespace selector on the observability namespace, port 4317 |
| Postgres | online store and pgvector when they land | namespace selector, port 5432 — add it now, or leave a comment recording that it is deferred. Silence is what F-04 was |

The ExternalSecret is resolved by the External Secrets controller in *its*
namespace, not by the pod, so no secret-manager egress is needed here. Say so
in a comment; the next reader will ask.

**The gate.** Follow the pattern the last round established. Add to
`tests/test_gitops_manifests.py`, beside
`test_an_advertised_scrape_port_is_reachable`, a test asserting that a rendered
overlay whose pod declares an egress dependency carries a policy permitting it.
The cheapest honest version: assert the rendered policy set is not
egress-DNS-only whenever the Deployment names an external endpoint in its
environment.

**Correct the neighbouring comment while you are here.**
`platform/kubernetes/overlays/local/kustomization.yaml` calls
`platform/policies/` "Kyverno policies, and kind ships no Kyverno". They are
`networking.k8s.io/v1` NetworkPolicies. The conclusion — do not apply them
locally — still holds, for a different reason: kind's default CNI does not
enforce NetworkPolicy at all, so applying them would report success while
enforcing nothing.

**Acceptance**: `kubectl kustomize platform/kubernetes/overlays/gcp-prod`
renders egress rules for every row above; the new gate is watched failing by
deleting one rule; `uv run pytest tests/test_gitops_manifests.py -q` passes
across all seven overlays.

### W-4 — Gate the version straddle across the serving seam

> **Status: done** on `fix/c6-ok-above-name-failure` — *feat(gates): gate the version straddle across the serving seam* added P14; *fix(gates): P14 promised a red it could not give and read its ADR wrongly* gave it tests, scoped its ADR
> status check to the header, and withdrew a promise it could not keep. What it cannot see is R11-3 and R11-4.

**Mode**: AUTO · **Closes**: the unblocked half of F-06 · **Size**: ~2h

ADR-008's interface half is CONSULT and belongs to a human — see
[Not for an agent](#not-for-an-agent). The runtime half is not blocked and
nobody has written it. The platform fits and pickles models with **numpy
2.4.6, scikit-learn 1.9.0, joblib 1.5.3**; the container installs **numpy
~=1.26.0, scikit-learn ~=1.5.0, joblib ~=1.4.0**. The container's own
requirements file carries the comment `numpy 2.x silently corrupts joblib
models`. Both sides know the hazard; nothing compares them.

Steps:

1. Write `scripts/check_artifact_compatibility.py`. It resolves the workspace
   versions of numpy, scikit-learn and joblib from `uv.lock`, parses the
   specifiers in `services/demand-forecast-serving/requirements.txt`, and fails
   when the resolved writer version does not satisfy the reader's specifier.
2. Read `services/` and never write to it — it is byte-identical to what the
   template produces, and editing it is a fork
   ([ADR-003](../decisions/ADR-003-service-template-consumption.md)).
3. Wire it into `ci.yml`, into `make verify`, and add its row to
   [quality-gates.md](quality-gates.md).
4. Watch it fail: it should be red on the tree as it stands today. That is the
   point — **this gate goes in red**, so land it together with either a
   `PENDING` marker on its quality-gates row or a documented exemption that
   expires when ADR-008 is accepted.

**Acceptance**: the script reports the three straddles by name; its
quality-gates row resolves under C4; the pull request body states plainly that
the gate is red by design and names the ADR that closes it.

---

## Wave 3 — point the gates at the code

The audit's central theme: the governance is excellent and aimed almost
entirely at documents. Five tasks that aim it at the machine learning.

### W-5 — Coverage floors for the ML code and the orchestration layer

> **Status: done** — *feat(gates): coverage floors per package, from one measured run*. CI runs the suite once
> under `coverage run` over all four scopes instead of twice, and `check_coverage_floors.py` (replacing
> `check_branch_coverage.py`) applies every floor: the libs aggregate (90, unrounded) and L1/L2 per library, P12 at
> 86, and P17 — a line and branch floor per ML package at the measurement, rounded down. Step 1 departs from the
> letter of this task on purpose: a third coverage STEP would have been a third half-hour run of the suite, and
> measured on `main` the single run reproduces the two old figures exactly (libs 94.45%, scripts 86.33%).
> Orchestration went from 34%/0% to 100% with tests that run the task bodies, which found the two promotion gates
> disagreeing (W-14). Acceptance: every floor is in `check_thresholds.py --show`; the gate on `main`'s data fails 7
> floors, and on this branch's data with `test_persist.py` deleted it fails demand-forecast; `check_thresholds.py`
> reports none loosened. `feature_defs` was already at 90% branches when this landed — the F-25 tests had raised
> it — and is at 100% now. The project gaps are W-15.

**Mode**: AUTO · **Closes**: F-11 · **Size**: ~1h

CI measures `--cov=libs` (floor 90) and `--cov=scripts` (floor 74).
`projects/` — roughly 1,500 lines of training, features, ingest, backtest,
persist and lakehouse — is measured by nothing, and so is `orchestration/`,
where the DAG defect lived. Within `libs/`, `check_branch_coverage.py` reads
only the report's root attributes, so `feature_defs` sits at **70.00% branch
coverage against a declared 80% floor** with the gate green.

1. Add a third coverage step for `--cov=projects --cov=orchestration`, with the
   floor set at **today's measurement**, not an aspiration. Measure first, then
   write the number down: a floor above the measurement is a red build, not a
   standard.
2. Make `check_branch_coverage.py` read per-package rates and fail on any
   package under either floor. Expect `feature_defs` to go red; raising its
   branch coverage is part of this task.
3. Register every new floor in `THRESHOLDS` in `scripts/check_thresholds.py`,
   and add the corresponding quality-gates rows.

**Acceptance**: every new floor appears in `check_thresholds.py` output; a
deliberately deleted test in `projects/` turns the new step red;
`uv run python scripts/check_thresholds.py` reports no loosening.

### W-6 — Make the plan's acceptance commands resolve, and gate them

**Mode**: AUTO · **Closes**: F-08 and F-09 · **Size**: ~2h

Two problems, one fix.

First, [technical-plan.md](../architecture/technical-plan.md)'s Phase 3
acceptance block contains `uv run python tests/test_dependency_direction.py`.
That file has no `__main__` guard, so it exits 0 having executed zero
assertions — while guarding charter criterion C1, which AGENTS.md marks
STOP-class. Change it to
`uv run pytest tests/test_dependency_direction.py -q`.

Second, nothing checks the plan's acceptance blocks at all. C4 covers
[quality-gates.md](quality-gates.md) and `check_ci_references.py` covers the
workflow; the plan — the canonical statement of intent, whose own rule 1 is
"a phase is complete only when every acceptance command exits zero" — is
ungated. Phase 1 currently names `projects/demand-forecast/tests/load.js` and
`demand_forecast.pipeline`, and neither is present in the tree.

1. Add a check to `check_doc_coherence.py` (a new C-number) that extracts every
   `bash` fence line from the plan's acceptance blocks and resolves the file
   paths and `-m` module targets they name.
2. Future-phase commands need a `PENDING` marker. Reuse the self-cleaning shape
   the parity ledger already uses, so a marker for something since built fails
   the suite.
3. Mark Phase 1's two missing commands PENDING rather than deleting them.
   Deleting a target after missing it is how a plan stops being one.

**Acceptance**: the new check reports how many commands it resolved; adding a
command that names a nonexistent script turns it red.

### W-7 — Stop the status document from being complete only where someone remembered

**Mode**: AUTO · **Closes**: the rest of F-15 · **Size**: ~1h

[implementation-status.md](../architecture/implementation-status.md) is derived
and gated, which is the right mechanism — but it derives over `COMPONENTS`, a
hand-written list in `scripts/check_implementation_status.py`. Anything missing
from that list is not marked ⬜; it is invisible. Drift detection — the
`DriftSignal` contract and PSI detector that
[ADR-007](../decisions/ADR-007-drift-detection-per-project-kind.md) and Phase 1
both name as deliverables — has **no row at all**.

> **Correction, 2026-09-05.** This step was written when the contract did not
> exist, and both of its particulars have since stopped being true. It named
> `libs/ml-core/src/ml_core/drift.py`; what landed is the package
> `libs/ml-core/src/ml_core/drift/`, so the original path would have created a
> detector matching nothing — the same defect QA-4 round nine found in
> `_as_word`, reintroduced by the instruction written to prevent its class. And
> the row no longer renders ⬜: the contract has 35 tests, so it carries a
> verify command and renders ✅. Step 1 is done in the commit carrying this
> correction. **Step 2 is untouched and is the valuable half.**

1. ~~Add the missing row, so the absence becomes visible~~ — done:

   ```python
   COMPONENTS = [
       # ...
       Component(
           "1",
           "Drift contract (ADR-007)",
           ["libs/ml-core/src/ml_core/drift"],
           "uv run pytest libs/ml-core/tests/test_drift.py -q",
       ),
   ]
   ```

2. Then close the class: add a test asserting that every deliverable bullet in
   the technical plan maps to a `COMPONENTS` row. This is the same defect the
   status document exists to prevent, relocated one level up, and it will find
   more than drift.

**Acceptance**: the regenerated document shows drift as ⬜ and its totals move;
the new test fails when a plan deliverable has no component.

### W-8 — Two mutable references inside a repository that pins everything else

> **Status: done** — *fix(ci): pin the scanner this repository downloads, and widen the gate that missed it*. The
> image tag half closed earlier with the placeholder tag. The kubescape half was worse than recorded: the asset
> had been renamed upstream, so `releases/latest/download/kubescape-ubuntu-latest` 404s and the advisory step
> reported that as success. Pinned to v4.0.14 with its published sha256, install split from scan so the tool can
> fail, and gate P10 widened to moving download URLs — watched reporting the old line against `origin/main`.

**Mode**: AUTO · **Closes**: F-12 · **Size**: ~1.5h

1. **An unpinned executable in CI.** The `iac-security` job runs
   `curl -sSL .../releases/latest/download/kubescape-ubuntu-latest -o kubescape`,
   then `chmod +x` and executes it. `scripts/check_action_pins.py` matches only
   `uses:` lines, so a downloaded binary is outside its scope entirely. Pin
   kubescape to a release tag and verify a checksum, or remove the step — it
   also carries both `continue-on-error: true` and `|| true`, so it cannot fail
   a build either way, and a scanner that can never fail is decoration.
2. **Widen the gate**, so `run:` blocks that fetch and execute are in scope.
   Fixing the instance and leaving the class open is the pattern this
   repository keeps finding.
3. **A `:latest` the parity work missed.**
   `orchestration/pipelines/demand_forecast_pipeline.py` sets
   `BASE_IMAGE = "ghcr.io/duqueom/ml-platform/demand-forecast:latest"`, in a
   file whose own comment argues against non-reproducible component images. The
   technical plan records "the deployment image on `:latest`" as a *closed*
   finding — the fix reached the six overlays and not this file, because the
   gate that closed it reads manifests. Use the same unresolvable placeholder
   the base Deployment uses, and extend the image scan to KFP components.

**Acceptance**: the widened pin gate reports the kubescape line before the fix
and passes after; a `:latest` reintroduced into either a manifest or a KFP
component turns the image scan red.

### W-9 — Alert on the gates that already exist

**Mode**: AUTO · **Closes**: F-13 · **Size**: ~3h

Searching the whole tree for `PrometheusRule` returns nothing. The one
dashboard has five panels and the fourth is *prediction score distribution* — a
classifier panel. Nothing shows forecast MAE, interval coverage, drift or
latency, and no SLO is stated anywhere, though Phase 1's acceptance requires
"p99 within stated SLO".

1. Write `PrometheusRule` definitions for conditions this repository already
   holds thresholds for: skill below `MIN_SKILL`, interval coverage below
   `MIN_COVERAGE`, ingest reject rate above `MAX_REJECT_RATE`, pod not ready.
   Reuse the constants rather than restating them — a number restated outside
   the thing that derives it will diverge from it.
2. Replace or supplement the dashboard with forecast panels.
   `scripts/check_dashboard_inventory.py` already gates dashboards; make sure
   the new ones satisfy it.
3. State an SLO somewhere a gate can read it, or record explicitly that none is
   set yet. Silence is what this finding is.

**Acceptance**: rules parse under `promtool check rules`, or under the YAML
gate if promtool is unavailable in CI; `check_dashboard_inventory.py` passes;
no alert restates a threshold constant.

---

## Wave 4 — cheap and overdue

Four small items. Any of them fits in a single focused pull request; together
they are under a day.

### W-10 — Verify the digest the model artifact already records

> **Status: done** — *feat(demand-forecast): verify the digest the artifact already recorded*. The sidecar now
> carries the FULL sha256 (`version` carried a 12-character label), `load` verifies it before unpickling, and an
> artifact without its sidecar is refused — the pair is the artifact. Watched failing: a flipped byte, a
> truncation and a missing sidecar all load cleanly on the previous revision.
>
> **Narrowed by QA-4 round fifteen (R15-6): integrity against corruption is done; tamper resistance is open.**
> The digest lives beside the artifact under the same write permission, so whoever can replace the artifact can
> replace both — the auditor did, and the payload executed before `load` refused it. And the reader that matters
> never calls the check: the generated service loads with `joblib.load` directly. F-14 named the tampering threat,
> so F-14 is not closed. What closes it is R15-6 below.

**Mode**: AUTO · **Closes**: F-14 · **Size**: ~30min

`persist.save()` computes `sha256` over the artifact's bytes and writes it into
the sidecar's `version` field. `persist.load()` calls `joblib.load(path)` and
only then checks the object's type and schema — both checks happen after the
pickle has executed, and the recorded digest is never compared. Loading a
pickle is arbitrary code execution with the serving identity: low-risk on a
developer's disk, and not low-risk the moment the path is an object-storage
URI whose write permissions are broader than the reader's.

Compare the digest **before** `joblib.load`, and raise in the same "re-fit
rather than reading it" register the schema check already uses. Bandit has no
joblib rule, so no scanner covers this; the test is the only guard.

**Acceptance**: a test flips one byte of a saved artifact and asserts `load()`
raises before unpickling.

### W-11 — Let the RAG chunker's known defect announce its own fix

**Mode**: AUTO · **Closes**: F-17 · **Size**: ~1h

`test_chunking_survives_a_real_filing` records a measured defect precisely —
1,234 oversized chunks of 3,411, the largest 1,087,381 characters, because a
10-K's SGML and XBRL carry no sentence boundary — and marks it `xfail(strict)`
so that "when the chunker is fixed this test fails as XPASS and must be
un-marked."

It is also marked `@pytest.mark.integration`, and `addopts` deselects that
marker everywhere; the string appears in no workflow. It would additionally
`skip` with no filings present, which is the CI condition. So the self-cleaning
property — the whole reason for choosing xfail over deletion — is inert.

Commit a small real filing as a fixture so the test runs in CI without a
network fetch, or add an `-m integration` lane. The reasoning behind the marker
is right; only its wiring is missing.

**Acceptance**: the test executes in a default CI run and reports `xfail`,
rather than `skip` or being deselected.

### W-12 — Four documents that have drifted from their own machinery

> **Status: done** — *fix(docs): four documents that disagreed with their own machinery*. The contract's deviation
> table is generated from `KNOWN_DEVIATIONS` (gate P16); the plan's `no-commit-to-branch` item is marked resolved
> and kept as the record; the inventory distinguishes `environment:` from code detectors, so `pgvector` renders 🧩
> rather than ✅ and the headline moved 55→54; SECURITY.md no longer claims image scanning.

**Mode**: AUTO · **Closes**: F-18 and F-20 · **Size**: ~1.5h

- **[PROJECT_CONTRACT.md](../PROJECT_CONTRACT.md)** says the test is the
  authority, then narrates "Current deviations" as a single item.
  `KNOWN_DEVIATIONS` in `tests/test_project_contract.py` holds four:
  store-assistant P1, rag-assistant P1, P6 and P7. Derive the prose from the
  dictionary, or delete the prose section — do not maintain a second copy.
- **The technical plan's "Still open" list** leads with "`no-commit-to-branch`
  contradicts the actual flow… this repository's history is direct commits to
  `main`." Main's recent history is squash-merged pull requests (#44 … #47).
  The finding is resolved and the plan still asserts it — the plan's own rule
  2, that status markers expire, applied to the plan.
- **The technology inventory** marks `pgvector` ✅ at Core tier on the strength
  of an image name in a local manifest, while the plan lists pgvector retrieval
  as open Phase 3 work. Separate "declared in an environment" from "consumed by
  code" in the detector's vocabulary.
- **[SECURITY.md](../../SECURITY.md)** labels the Trivy row "Dependency and
  *image* vulnerabilities" while its own note says filesystem — and nothing in
  this repository builds an image, so no image is scanned. The rest of that
  document is scrupulously accurate; this row overstates by one word.

**Acceptance**: `check_doc_coherence.py` passes, and the deviations prose can
no longer disagree with `KNOWN_DEVIATIONS` without a test failing.

### W-13 — The small correctness and hygiene items, in one pass

**Mode**: AUTO · **Closes**: F-19, F-21, F-22, F-23, F-25, F-28, F-29 ·
**Size**: ~2h

| ID | Item |
| --- | --- |
| F-19 | Report per-zone or per-decile conformal coverage alongside the marginal figure. One global residual quantile across 140 heterogeneous zones gives valid marginal coverage and poor conditional coverage — and staffing, the stated use, is decided per zone. Consider grouped conformal keyed on a volume bucket. Also: `expanding_window_folds_by_time` silently skips a degenerate fold while the positional splitter raises for the same condition; make them agree. And `MIN_ZONE_HOURS` is documented as hours while counting rows — the same units confusion as F-01, one scale down |
| ~~F-21~~ | **Done** — *fix: two figures that flattered their subject*. Both errors on the rows that carry a baseline; re-measured on the real files at +12.4%, the figure the model card had predicted |
| ~~F-22~~ | **Done** — *fix(rag-assistant): read the EDGAR contact from the environment*. Read from `EDGAR_USER_AGENT`, no default, refusing before the first request; the guard test greps the module for any address and fails against the previous revision |
| ~~F-23~~ | **Done** — *fix(demand-forecast): the lakehouse no longer defaults to a laptop*. Worse in practice than recorded: the training DAG called the lakehouse with no catalogue, so it relied on the fallback. The catalogue is required now, resolved from `LAKEHOUSE_CATALOG` with no default; unset is a refusal |
| ~~F-25~~ | **Done** — same commit. The leak rate divides by the rows that could be checked, and unexamined rows are named in the report; `is_clean` keeps the existing decision that a missing feature is a coverage problem |
| F-28 / F-29 | Shadow-mode sampling uses the unseeded global `random`, which `seed_everything` also seeds. `DEFAULT_ENDPOINT` in `tracing.py` reads its environment variable at import time, so a test cannot monkeypatch it afterwards |

**F-16 and F-24 are deliberately excluded from this list.** The agent core's
connection reuse and shared breaker state (F-16) need a benchmark and a
decision about the replica count; the policy gate's keyword matching (F-24) is
a design question about detection efficacy rather than a defect. Both belong in
a round with a human in it.

### W-14 — The two promotion gates disagree about what earns a deployment

> **Status: done** — *feat: one promotion rule for both orchestrators, and an artifact the serving image can
> load*. As recommended: `demand_forecast.promotion` defines the rule (skill ≥ 0.05; coverage within
> [0.85, 0.95], both bounds inclusive) and the backtest it is judged on (5 folds, horizon 168, seed 42), and both
> the DAG and the pipeline call it. The pipeline takes no backtest parameters any more, so no run can choose its
> own design. Every predecessor threshold is claimed by the merged one (`renamed_from` names each of them), the
> fold count is watched as a floor, and `tests/test_promotion_agreement.py` runs 34 metric pairs — the auditor's
> four disagreements among them — through both orchestrators' gates and asserts one verdict. The DAG is stricter
> on over-coverage than it was: a model at coverage 0.97, which it promoted, is now refused.
>
> **Qualified by QA-4 round seventeen:** done *in-process*. Both orchestrators call one rule and reach one
> verdict where their tests run them — the workspace environment. The KFP components run in an image that does
> not exist yet, and until this round's remediation they named the SERVING image, which holds neither kfp nor `demand_forecast`;
> they now name their own (`…/demand-forecast-train`), held apart from the serving image by a test. Building
> that image, and proving the rule importable in it, is R17-1.

**Mode**: CONSULT · **Source**: found while writing W-5's tests for both gates ·
**Size**: ~1h once decided

The same backtest can be promoted by one orchestrator and refused by the other,
because each carries its own copy of the gate:

| | Airflow DAG (`check_quality_gate`) | KFP pipeline (`check_quality_gate`) |
| --- | --- | --- |
| Skill | `skill >= MIN_SKILL` (0.05) | `skill > 0` |
| Interval coverage | `coverage >= MIN_COVERAGE` (0.85), one-sided | `intervals_are_calibrated()`: within 0.05 of 0.90, **both** sides |

A model at skill 0.03 passes the pipeline and fails the DAG; one at coverage
0.97 passes the DAG and fails the pipeline. Both module docstrings warn against
exactly this — "a pipeline step that reimplements the logic it orchestrates is
a second copy that drifts" — and the gate is the one piece each reimplements.
W-5's tests pin both behaviours as they are, so neither can move without a red
test, but pinning a disagreement does not resolve it.

**Decision needed**: which semantics is the promotion policy. The
recommendation is one function in `demand_forecast` that both orchestrators
call — skill `>= 0.05` (a positive floor, as the DAG argues: the gate catches a
broken pipeline, not a near-tie) and calibration two-sided (as the pipeline and
`BacktestReport.intervals_are_calibrated` argue: over-coverage is uncertainty
the model has not quantified). That makes the DAG stricter on over-coverage,
which can fail a run the DAG passes today, and is why this is CONSULT.

**Understated, per QA-4 round fifteen (R15-2).** The table above compares
thresholds only. The two orchestrators also gate **different backtests**: the
DAG calls `evaluate(read_demand())` with its default of 5 folds, the pipeline
defaults to `n_folds=3`. On the same lock-verified data the DAG measures skill
+12.4% and the pipeline +23.0%, because the 3-fold design drops folds 0 and 1 —
the two the model loses (−18.3%, −1.2%), which the model card warns the average
hides. And "the thresholds still watched" was never true for the pipeline:
only the DAG's two constants were in `THRESHOLDS`. The round-fifteen
remediation registers the pipeline's two numbers and pins both orchestrators'
backtest arguments in their tests, so neither can drift while this waits; it
does not choose between them.

The recommendation extends to the folds: **5**, the design that sees the losing
folds, owned by the same function as the thresholds.

**Acceptance**: one definition of the gate AND of the backtest parameters,
imported by both orchestrators; every threshold watched by
`check_thresholds.py`; a test that runs the same metrics through both and
asserts the same verdict.

### W-15 — Raise the project floors toward the library floors

> **Status: done** — every file in the table below is at or above 90% lines and 80% branches: `crossover.py`
> from 0%, `store_assistant/tools.py` and `backtest`, `tracing`, `train` and `warehouse_checks` at 100%. CI measured
> `projects/demand-forecast` at 98.47% / 93.86%, `projects/store-assistant` at 100% / 100% and `projects/` at
> 97.40% combined, and P17's floors are raised to 98/93, 100/100 and 97 in the same commit. Each new property is a
> catalogue entry (W15-1..8). Two defects surfaced: a bounds `break` in the expanding-window splitter that its own
> size check made unreachable — removed, with the invariant swept across designs — and a `stage()` docstring
> promising attributes set on exit, which the code never did.

**Mode**: AUTO · **Source**: W-5's measurement · **Size**: ~3h, after #106

P17 holds `demand-forecast` at 79% lines / 65% branches and `store-assistant` at
85% / 57%, against 90 / 80 for a library. The gap is concentrated, not spread:

| File | Measured | What is missing |
| --- | --- | --- |
| `demand_forecast/crossover.py` | 0% of 59 statements | Nothing tests it. The scaling curve and the projection are pure arithmetic over measured points and can be tested on synthetic ones |
| ~~`demand_forecast/lakehouse.py`~~ | ~~51%~~ | **Done** in the dependency round: the seven lakehouse tests also run against `local_catalog()` with a `file://` warehouse on every build, and demand-forecast's floors were ratcheted to 83% lines / 71% branches |
| `store_assistant/tools.py` | 79%, 4 partial branches | Lines 52, 66, 76, 93 and 110–114: the refusal paths of the tools |
| `demand_forecast/train.py`, `tracing.py`, `backtest.py` | 85–89% | A handful of guard clauses each |

**Acceptance**: each file above at or over 90% lines and 80% branches, or a
written reason it cannot be; the P17 floors raised to the new measurement in
the same commit.

---

## Round eleven — what stays open, and why each one waits

QA-4 round eleven audited `0fe7343` — rebased onto `main` as `8897281` — and
reported 1 P1, 5 P2 and 6 P3. Commits below are cited by subject, not SHA:
this repository merges by squash, which rewrites every SHA on a branch, and
ten SHAs this section first cited stopped resolving at the rebase before the
merge had even happened. What closed, on `fix/c6-ok-above-name-failure`: the P1 (*fix(k8s): stop commonLabels rewriting the DNS policy's peer selector*), the render-safety
gate's false justification and zero-file pass (*fix(gates): P15 was justified by a false claim and could pass over nothing*), the serving-seam
gate's untested paths and ADR parsing (*fix(gates): P14 promised a red it could not give and read its ADR wrongly*), the hand-written residue
list (*fix(tests): record what the gate probes write instead of listing it by hand*), unbounded subprocesses and CI jobs (*fix(gates): bound every subprocess and every CI job*), the egress
assertion (*fix(k8s): the egress test could not fail, and asserted the wrong metadata port*), and the compliance mapping, policies README, local
overlay comment and audit brief, which stated closed gaps as open or open ones
as impossible.

What follows did not close. None is urgent in the sense of harming anything
running — nothing is deployed — and each waits on something named. Where the
wait is a decision, the mode is CONSULT and the decision is the user's.

### R11-1 — The serving policies select namespaces nothing provisions

> **Status: done** — *feat(k8s): declare the namespace roles the policies depend on*. Option A as recommended:
> `platform/policies/namespace-contract.yaml` declares each role, who provisions it in cloud and locally, and
> whether the local stack fulfils it; the policies select `role.ml-platform.io/<role>`; the local namespace
> carries the monitoring role it genuinely fulfils and not the ingress one it does not;
> `tests/test_namespace_contract.py` fails on a selector nobody declared, a role nobody provisions, and a local
> claim no manifest backs.

**Mode**: CONSULT · **Source**: round ten P2, open through round eleven · **Size**: ~2h once decided

`allow-serving-ingress` admits `app.kubernetes.io/name: ingress-nginx` and
`monitoring`; `allow-serving-egress` admits `monitoring` for OTLP. No Namespace
in this repository carries either label — the local stack runs entirely in
`ml-platform` and has no ingress controller, and no cloud namespace is
provisioned. Under `default-deny` the pod can therefore be neither reached nor
scraped, and every render and test passes.

**Waits on**: choosing the selector contract.

| Option | Trade-off |
| --- | --- |
| **A. Label contract (recommended)** — the platform declares the namespaces it provides and their labels; the local stack creates `monitoring` with it; a test asserts every `namespaceSelector` matches a Namespace this repository provisions | Agnostic: the label is the platform's, the namespace name is the provider's. Requires the platform to provision those namespaces, which Phase 2 must do anyway |
| B. Select by `kubernetes.io/metadata.name`, as `allow-dns` does | Set by Kubernetes itself and impossible to forget, but couples policy to names that differ per provider (`gmp-system` on GKE, others on EKS) |
| C. Per-overlay patches with each cloud's real names | Most exact today; adds cloud-specific surface that gate P6 counts |

**Closes when**: a test fails for any `namespaceSelector` with no provisioned match, and passes.

### R11-2 — Local enforcement evidence for the NetworkPolicies

> **Status: done** — *feat(k8s): prove the NetworkPolicies are enforced, on a cluster*. The local overlay includes
> `../../../policies`; `tests/local/test_network_policies.py` asserts the four policies are in force, DNS resolves
> under them, a rewritten peer selector denies DNS, and Prometheus scrapes the pod through the monitoring role.
> Measured on kindnetd v20250512, polling rather than sleeping: propagation took 3s once and 41s another time.

**Mode**: AUTO after R11-1 · **Source**: round eleven P2 · **Size**: ~3h

Round eleven proved kindnetd enforces NetworkPolicy, disproving the claim four
documents made. The claim is corrected; the evidence is not collected. The local
overlay does not apply the policies, and
`test_the_local_cluster_cannot_validate_networkpolicies` asserts only that a
kindnet daemonset exists.

**Waits on**: R11-1 (applying the policies locally without a labelled
`monitoring` namespace cuts Prometheus off the pod), and a running Docker —
unavailable on the machine where this was written.

**Closes when**: the local overlay includes the policies, and a `local`-marked
test resolves DNS under them, fails to when the peer selector is mutated, and
Prometheus still scrapes the pod.

### R11-3 — The container cannot import the model artifact at all

> **Status: REOPENED by QA-4 round fifteen (R15-1).** *feat(demand-forecast): the artifact carries data, not
> workspace objects* fixed the half it targeted — the artifact's bytes name no workspace package, asserted per
> package — and was recorded as closing this item. It did not: an environment built from the service's
> `requirements.txt` alone (numpy 1.26.4) still cannot load the artifact, because the fitted estimator carries a
> numpy-2 `Generator`. Its own "Closes when" was never met: P14 does not check what the pickle imports, and no
> test loads the artifact under the reader's versions. Options and recommendation: R15-1 below.
>
> **Status: done again, on the property that matters** — *feat: an artifact the serving image can load, checked by
> loading it* (R15-1, option A). `persist` drops the fitted estimator's fit-time random state, which prediction
> never reads, and gate P18 (`scripts/check_serving_can_load_artifact.py`, in CI's Fast gates job) fits and
> saves a model, builds an environment from the service's `requirements.txt` alone on the Dockerfile's Python,
> and loads and predicts there — identical predictions under numpy 1.26.4, scikit-learn 1.9.1, joblib 1.6.0. The
> numpy straddle itself remains, exempted against ADR-008: this artifact loads across it, which is not the same as
> the straddle being gone (option B).

**Mode**: CONSULT · **Source**: round eleven P2 · **Size**: depends on the decision

`persist.py` pickles `ml_core` types; the service image installs no workspace
library; loading fails with `ModuleNotFoundError: No module named 'ml_core'`
before any version is compared. Recorded in ADR-008.

**Waits on**: ADR-008's interface decision — the image installs the workspace
libraries the artifact references, or the artifact stops pickling workspace
types (for example, exporting to a format that carries no project classes).

**Closes when**: ADR-008 is decided, and gate P14 also asserts that every
module root the pickle references is importable in the image.

### R11-4 — The serving-seam gate compares a hand-written package list

> **Status: done** — *fix(gates): hold the serving-seam package list to the artifact itself*. The portability test
> records every module the loader resolves while reading a real artifact and fails if one belongs to a package
> `SEAM` does not compare. Measured: scikit-learn, numpy, joblib — exactly `SEAM`. Runtime-only imports (scipy
> under scikit-learn) are out of scope by decision, and the gate says so.

**Mode**: AUTO after R11-3 · **Source**: round eleven P2 · **Size**: ~2h

`SEAM` names numpy, scikit-learn and joblib. A straddle in any other package
the artifact pulls in — scipy under scikit-learn, for one — is not compared.
The gate now says so instead of promising otherwise.

**Waits on**: R11-3, because the object graph to derive it from changes with
that decision.

**Closes when**: `SEAM` is derived from the module roots of a real pickled
artifact, and a straddle in a package that is not listed by hand fails the gate.

### R11-5 — The demand-forecast model card is four TODO sections

> **Status: done** — *docs(demand-forecast): write the four model-card sections that read TODO*. Intended use,
> fairness, failure modes and human oversight, written from what the repository already measures. Fairness is
> recorded as NOT measured, with the subgroup that matters (zone, borough, volume decile), why the marginal
> coverage figure cannot answer it, and what would close it (F-19). The owner still has to review it.

**Mode**: AUTO to draft, CONSULT to sign · **Source**: round ten P2 · **Size**: ~2h

Intended use, fairness, failure modes and human oversight all read TODO, while
the model cards skill renders from `store-assistant`.

**Waits on**: nothing to draft — conformal intervals, the expanding-window
backtest and `ml_core.fairness` supply the facts, with zones as the natural
subgroup. Signing it waits on the model's owner.

**Closes when**: no section reads TODO, each claim cites the test or report
that measures it, and the owner has reviewed it.

### R11-6 — A configured language that nothing reads

**Mode**: AUTO · **Source**: parity ledger, `check_config_is_read.py` pending · **Size**: ~3h

`UsecaseConfig.language` is declared, documented, loaded from YAML and set to
`es` by store-assistant, and read by nothing outside its module.

**Closes when**: `language` reaches the customer-facing surface, then
`check_config_is_read.py` is ported against llm-core's config with a ratchet
on unwired fields, and the ledger entry moves to `adopted`.

### R11-7 — Small items, one pass

> **Status: done.** Of its three items, only one needed work here. `CODECOV_TOKEN` is documented in
> `docs/ADOPTION.md` with every setting a fork must reproduce, and *docs: what a fork must configure* adds a test
> that fails on any workflow secret the guide does not name. The sandbox test that failed when run alone passes on
> `main` — fixed by a later change, not this one — and the 46-minute invariants lane was split into fast and slow
> lanes by #83.

**Mode**: AUTO · **Size**: under 1h together

- `CODECOV_TOKEN` is read by CI and documented nowhere. Its step cannot fail a
  build, so an unset token silently means no coverage upload.
- `tests/test_gates_in_a_bare_environment.py::test_the_sandbox_really_lacks_the_sibling_checkout`
  fails when run alone (`ModuleNotFoundError: No module named 'scripts'`) and
  passes in the full suite by collection order.
- **Observation, not a finding**: the Repository invariants job takes 46.5 min
  median over five green runs. `timeout-minutes: 75` bounds it; nothing yet
  measures where those minutes go.

## Round twelve — what stays open, and why each one waits

QA-4 round twelve audited `6a4bfe2` — `main` plus the two pull requests that
qualified the agent core's foreign ADR citations and added
[ADR-010](../decisions/ADR-010-agent-core-authority.md) — and reported 1 P0,
7 P2 and 6 P3. Its hypothesis was that negative controls chosen by the author
test what the author already believed, and six of the eight it attacked
failed. Commits are cited by subject, as above.

What closed, on the same branch as the work it corrects:

- C2's extension, whose tests missed both of the auditor's mutations; the nine
  citations it could not see in YAML and JSONL; the double read; the RUNBOOK
  row that overstated it (*fix(gates): QA-4 round twelve, P2 — C2's new guards
  could not fail, and it could not read YAML*).
- The exporter's provenance guarantees, its transform-only tests, the boundary
  test that saw one form of host reference in six, and ADR-010's unmeasured
  commit count (*fix(export): QA-4 round twelve, P2 — the exporter's guarantees
  were written, not enforced*).
- The link check's missing scheduled sweep (*fix(ci): QA-4 round twelve, P3 —
  the link check promised a scheduled sweep it did not have*).

Each fix was verified against the auditor's own mutations, not only its
author's: 11 of 11 killed for C2, 11 of 11 for the exporter.

What follows did not close. The findings in code this session did not write are
kept to separate pull requests, so each is reviewed on its own.

### R12-1 — agent-local's drift guard takes its verdict from the directory it validates

**Mode**: AUTO · **Source**: round twelve P2-5 · **Size**: ~1h · **Closed** by DuqueOM/agent-local#1 (`a40bf38`): its CI job `export-provenance` re-runs this exporter at the recorded commit, refuses a commit not on `main`, and fails both of the audit's edits

`tests/test_core_is_exported.py` in `agent-local` recomputes hashes against
`EXPORTED_FROM.json`, which sits in the directory being checked. A hand edit to
`policy.py` passes if the same commit updates its hash.

**Waits on**: this change reaching `main`. The export must name a commit that
a squash cannot orphan, and the exporter now refuses to write from any other.

**Closes when**: `agent-local`'s CI checks out this repository at the commit
`EXPORTED_FROM.json` names and runs `export_llm_core.py --check` against its
tree. The auditor's edit, with the manifest updated to match, must fail it.

### R12-2 — Claude Code registers none of the 29 skills

**Mode**: AUTO · **Source**: round twelve P0-1 · **Size**: ~2h · **Closed** by *fix(agentic): QA-4 round twelve, P0 — render every surface where its tool looks*, which found Cursor and Codex broken the same way and fixed all three

The adapter renders `.claude/skills/<id>.md`; Claude Code discovers
`.claude/skills/<id>/SKILL.md` with frontmatter. `sync_agentic_adapters.py
--check` and `validate_agentic_surface.py --strict` both stay green, because
each checks the layout the adapter writes rather than the one the tool reads.
The base template already renders the right layout.

**Closes when**: skills render as `<id>/SKILL.md` with `name` and
`description` frontmatter, command pointers carry a `description`, and a
validator check fails on the flat layout. The Cursor and Codex surfaces get
the same test against their own tool's discovery rules.

### R12-3 — Two negative controls that pass with the guard broken

**Mode**: AUTO · **Source**: round twelve P2-6, P3-3 · **Size**: ~1h · **Closed** by *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate*

- `test_workflow_bounds`' negative control recomputes which jobs lack a bound
  instead of calling the guard, so it passes with the guard broken. It also
  accepts a boolean as a timeout.
- The rag-assistant ingest tests pin `user_agent()` but not that the request
  sends it: replacing the header with a constant passes.

**Closes when**: each test fails under the auditor's mutation (W1/W2 for the
first, the header replacement for the second).

### R12-4 — Documents that describe a different gate

**Mode**: AUTO · **Source**: round twelve P2-7, P3-2, P3-5 · **Size**: ~1h · **Closed** by *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate*

- `agentic/rules/23-doc-coherence.md` lists checks that do not match
  `check_doc_coherence.py`; in it, C7 is the private-reference guard.
- The audit brief still says two projects and 28 gates.
- `RUNBOOK.md:95` links to a heading in the technical plan that was renamed.

**Closes when**: the rule's list is generated from, or tested against, the
checks the script runs, and the two stale facts and the anchor are corrected.

### R12-5 — Four coherence checks print `ok` above their own failure

**Mode**: AUTO · **Source**: found while fixing C2 in round twelve · **Size**: under 1h · **Closed** by *fix: QA-4 round twelve — two negative controls that passed with the guard broken, and a rule describing another gate*, filtering at print time rather than per check

C3, C4, C5 and C9 print `ok` unconditionally, the defect round seven removed
from C6 and round twelve from C2.

**Closes when**: each prints `ok` only when it added no failure, with a test
per check that drives one failure and asserts no `ok` line for it.

### R12-6 — Nothing checks anchors

**Mode**: AUTO · **Source**: round twelve P3-2 · **Size**: ~2h · **Closed** by *fix(gates): QA-4 round twelve, R12-6 — C10 checks that every markdown anchor names a heading*, offline, in the coherence gate

The link check reads every file and fails a dead file link, but a link to a
heading that does not exist passes. The workflow now says so.

**Closes when**: a link to a missing heading fails CI. Either a checker that
validates fragments, or a small pass in the coherence script over relative
links, which avoids network flakiness. The auditor's mutation B must fail it.

## Round thirteen — what stays open, and why each one waits

QA-4 round thirteen audited `96128c0` and reported 0 P0, 0 P1, 5 P2 and 6 P3.
The round-twelve remediation held against the real remote and CI. But 12 of
31 mutations neither party had chosen survived its tests, and one bypass of
agent-local's export check was found. Commits are cited by subject.

What closed, in *fix: QA-4 round thirteen — what the round-twelve fixes
claimed held only for the mutations tried*:

- the exporter's blindness to subpackages and other strays (P2-1);
- the twelve surviving mutations, each with the test it lacked, and the
  harness committed as `tests/mutations.yaml` (P2-2);
- V7's missing Cursor compatibility paths and the false "listed once" (P2-3);
- V8 for nested surfaces (P2-4, detection);
- C6's links in generated directories (P2-5);
- C10's other link and heading forms (P3-1);
- the `note` channel (P3-2);
- V6's `ok` above a warning (P3-3);
- the brief's C1 sentence (P3-4);
- the derived generated-surface set (P3-5).

What follows did not close in that change. Each is under way in its own
repository, and each was approved by the maintainer on 2026-09-26.

### R13-1 — `services/demand-forecast-serving` still carries the template's pre-§9 skill layout

**Mode**: CONSULT, approved · **Source**: round thirteen P2-4 · **Size**: a template release plus a `copier update` · **Closed** by *chore(services): demand-forecast-serving at ml-service-template v0.30.2*: template v0.30.0 was released, then v0.30.1 and v0.30.2 (fake secrets in a test fixture, which GitHub and this repository's hook reported), and the service regenerated at v0.30.2. V8 reports no flat pointers; the 19 name collisions remain as reported, as expected

V8 now reports it on every run: 38 flat pointers no tool loads, and 19 skill
names that collide with the root's. ADR-003 lets it change only through
`copier update`, and the template fix (ml-service-template#238) is in no
release yet.

**Waits on**:

- a template release that contains template-ADR-027 §9;
- a `copier update` of the service to that release, which spans more than a
  hundred template commits.

**Closes when**: V8 reports no flat pointers under `services/`. The name
collisions will remain. They are inherent to a service that ships its own
skills, and V8 reports them as such rather than as a defect to fix.

### R13-2 — agent-local's export check is advisory

**Mode**: CONSULT, approved · **Source**: round thirteen P3-6, and P2-1's downstream half · **Size**: ~1h · **Closed** by DuqueOM/agent-local#2 (the stray rule, weekly schedule) and #3 (re-export from `7f1867c`), and by protecting agent-local `main` on 2026-09-26 with `export-provenance` required, `enforce_admins` on

agent-local's `main` is unprotected, so a red `export-provenance` does not
block a merge. The job also runs only on agent-local's own events, so a
history rewrite in this repository is not noticed until agent-local's next
push. Its hash test still uses the top-level `*.py` pattern that P2-1 showed
blind.

**Closes when**:

- `export-provenance` is a required check on agent-local `main`;
- the job also runs on a weekly schedule;
- agent-local's test refuses the same strays as the exporter.

### R13-3 — The template's template-ADR-027 §9 repeats the "listed once" claim

**Mode**: AUTO · **Source**: round thirteen P2-3, upstream half · **Size**: ~1h · **Closed** by DuqueOM/ml-service-template#239 (template-ADR-027 §10, `skill_reach`), released in v0.30.0

ml-service-template#238 made the same choice as this repository and wrote the
same false sentence. Its validator's table also omits Cursor's compatibility
paths.

**Closes when**: the template's ADR carries a dated correction, and its
validator requires the copies one tool reaches to agree.

## Round fourteen — what stays open, and why each one waits

QA-4 round fourteen audited `f8b9d27` and reported 0 P0, 0 P1, 4 P2 and 5 P3.
Round thirteen's remediation held under direct attack. But five of the
auditor's nine new mutations survived, C6, C9 and the artifact gate each missed
a realistic input, and the published `scripts/` coverage figure left out two
scripts no test ran.

What closed, in *fix: QA-4 round fourteen — three gates that each missed a
realistic input, and a coverage figure that left two scripts out*:

- C6's other link forms (P2-1);
- C9's tokenising, copier's source rules and every code-block shape (P2-2);
- the artifact gate's name normalisation and one-minor-series rule (P2-3);
- the two uncounted scripts, counted and tested, with the floor unchanged
  (P2-4);
- the secret hooks' view of the generated directories (P3-1);
- the harness's uncommitted entries and `CRASH` verdict (P3-2);
- the thresholds baseline (P3-3);
- V8's tree walk and its copy/collision split (P3-4, detection);
- `service_name` recorded upstream (DuqueOM/ml-service-template#254,
  released in v0.31.0) and the service regenerated with it (P3-5).

One item stays open. Opening an issue in another repository is outward-facing,
so the agent drafts it and the maintainer files it.

### R14-1 — Two of the template's skills share a name with a different root skill

**Mode**: STOP for an agent beyond this proposal · **Source**: round fourteen P3-4, upstream half · **Size**: a template rename plus a `copier update`

`services/demand-forecast-serving` ships 19 skills whose names the root also
defines. 17 are copies. Two are different skills:

- `doc-coherence`: the template's covers version, CHANGELOG, `llms.txt` and
  schemas (rule 16, template-ADR-031). The root's covers the ADR index, plan
  status and gate traceability.
- `enterprise-audit`: the template's is a 23-domain ISO audit. The root's is a
  staff-level verification audit.

In the service's directory, which one a tool runs depends on where it was
invoked. V8 fails on this, except for the two pairs recorded in `V8_EXEMPT`,
and fails on an exemption once its collision is gone.

**Proposed issue text for ml-service-template** (for the maintainer to file):

> **Two skill names collide with the adopting repository's own skills.**
> A service generated into a repository that has its own agentic surface
> (ml-platform) ships `doc-coherence` and `enterprise-audit` under the same
> names as the adopter's skills with different purposes. Cursor and Claude
> Code load nested skill directories, so inside the service the tool picks
> one. These names are generic enough to collide with any adopter.
> Proposal: prefix the template's service-scoped skills, for example
> `service-doc-coherence` and `service-enterprise-audit`, or document the
> collision as an adopter decision in template-ADR-027. Either is a template
> decision (ADR-003 downstream).

**Closes when**: the template renames them, or records the collision as the
adopter's to resolve, and the service is updated to that release. V8 then
fails on the two stale exemptions until they are deleted.

---

## Round fifteen — what stays open, and why each one waits

QA-4 round fifteen audited `98a4359` and reported 0 P0, 0 P1, 8 P2 and 11 P3;
the report is committed as [`qa4/round-15.txt`](qa4/round-15.txt). Its verdict:
the claims hold where they were measured — #112's coverage figures, #104's
re-measured skill and per-fold table, #78's workspace-free pickle all reproduce
exactly — and do not hold where a closure was declared beyond what was
executed: R11-3, W-10 as a close of F-14, Codecov as a Core gate, and W-14's
account of the disagreement.

What closed, in *fix: QA-4 round fifteen*:

| ID | Finding | Closed by |
| --- | --- | --- |
| R15-3 | `check_thresholds.py` skipped a threshold that moved file or changed label, so #112 could have lowered every coverage floor with it green | Compared by NAME against the watch list the baseline itself declared; `renamed_from` with a unit factor; dropping a watch entry fails. The auditor's exact attack now fails on all four floors |
| R15-4 | C6 missed six host-less forms of a repository name | Autolinks, `uses:`, `gh:`, `gh` arguments, `repos/`, Pages; elided names pass only as the prefix of a public repository |
| R15-7 | Three tests failed under parallel load | The tag probe moved to a `--shared` clone; the status generator's test budget derived from its own bound; the determinism test prints the rows that differ. The determinism failure's cause was not captured — the next occurrence names it |
| R15-8 | The release workflow's coverage step always failed at 0% | Step 2 is `make verify`; C4 now resolves `--cov=` and `--source=` paths, in gate rows and in agentic workflows |
| R15-9 | C9 missed `uvx copier@x`, list-item and blockquoted fences, `<pre>`, and took `--vcs-ref HEAD` as a pin | All five; a remote source needs a tag or a commit, a placeholder documents a pin, a local source is exempt |
| R15-10 | The artifact gate ignored environment markers and the image's second install | Markers evaluated against the Dockerfile's Python; the cloud requirement files read; the provider list held to the Dockerfile |
| R15-11 | A probe module escaped the coverage-omit guard | Renamed to the convention; the guard matches any underscore-prefixed probe module |
| R15-12 | The serving-core exemption counted statements | The package's AST: docstring, `__version__` and `__future__` only |
| R15-13 | `intervals_are_calibrated` refused 0.85 and accepted 0.95 | Inclusive at both bounds, compared with a float tolerance |
| R15-15 | Local-stack images pinned by tag | Five of six pinned by digest and held there by a test; the sixth is R15-20 |
| R15-16 | C10's slugs differed from GitHub's in five shapes | Code spans literal, images dropped, entities and escapes resolved |
| R15-17 | The audit brief and Q-05 described coverage the old way | Both rewritten; Q-05 names the floors table and the rename rule |
| R15-18 | Rounds twelve to fourteen existed only in a home directory | Rounds 12–15 committed under `qa4/`; the earlier rounds' absence is stated in `QA-4-independent-audit.md` |
| R15-19 | Parity `pending` entries carried no date | `expires:` required, at most 100 days out (watched as a ceiling); all eight dated 2026-12-31 |

Also corrected in place, because the documents were false: R11-3 is reopened,
W-10 is narrowed to integrity, W-14 records the fold design, ADR-008 carries a
dated correction, `persist.py`'s docstring no longer says the image can read
the artifact, and the inventory reports Codecov as not built. The pipeline's
two promotion thresholds are now watched, and both orchestrators' backtest
designs are pinned by tests so neither drifts while W-14 waits.

### R15-1 — The serving image cannot load the artifact

> **Status: A done; B open as ADR-008's decision** — *feat: an artifact the serving image can load, checked by
> loading it*. The fit-time `Generator` is dropped in `persist._payload` (a test asserts its absence and that the
> estimator still predicts identically), and P18 loads a freshly saved artifact under the image's requirements on
> every CI run — the step that would have caught R11-3's false close. P18 failing is what reopens
> this.

**Mode**: CONSULT · **Reopens**: R11-3 · **Size**: ~1h for A; cross-repository for B

Measured in the remediation session as well as by the auditor: the fitted
`HistGradientBoostingRegressor` keeps scikit-learn's fit-time
`_feature_subsample_rng`, a numpy-2 `Generator`, and numpy 1.26 — the image's
pin — refuses it. With that one attribute removed the same artifact loads AND
predicts under the image's exact requirements.

- **A.** Drop fit-time random state from the artifact in `persist._payload`,
  and add a CI step that builds a virtual environment from
  `services/demand-forecast-serving/requirements.txt` alone and loads a freshly
  saved artifact. Closes the reader half now; the numpy straddle stays exempt.
- **B.** Move the image to numpy 2 in `ml-service-template` (the straddle's
  root, ADR-008), then lift P14's numpy exemption.

**Recommendation**: A now, B as the ADR-008 decision. A alone makes the
artifact load by removing state it does not need; only B removes the straddle.

### R15-5 — Codecov has never received an upload

**Mode**: CONSULT · **Size**: ~15min once decided

Every upload is rejected for want of credentials (`CODECOV_TOKEN` is empty), so
none of `codecov.yml`'s statuses has run. The inventory now reports it ⬜ with
that note; L1/L2/P12/P17 are enforced by `check_coverage_floors.py` either way.
Decide: OIDC (`use_oidc: true`, `id-token: write`; no secret to rotate — the
recommendation, and what the inventory detector looks for), a token secret, or
removing Codecov and `codecov.yml`.

### R15-6 — The artifact digest does not resist tampering

**Mode**: CONSULT · **Narrows**: W-10 · **Size**: ~2h

The digest is written beside the artifact under the same permission, and the
service loads with `joblib.load` without calling the check. Verify against a
digest the writer cannot also write — the promotion record, a registry entry,
a signed sidecar, or a `sha256` pinned in the deploy manifest — in the code
that actually loads the file. Which of those is a deployment decision, and the
service side is generated code (ADR-003).

### R15-14 — The DAG trains and publishes on later reads than it validated

> **Status: done** — *fix(orchestration): the DAG trains on the snapshot it validated, and the model records
> it*. Every read after ingest names the run's `snapshot_id`; `persist.save` records it as `source_snapshot`
> (`null` when the input was not the lakehouse); the test stub refuses any other read. The auditor's R15-DAG6
> is killed, with three more mutations beside it.

**Mode**: AUTO · **Size**: ~1h · **After**: #106, which rewrites the same reads

`ingest_month` returns `snapshot_id` and every later task calls `read_demand()`
without it. Pass the snapshot through every read, record it in the published
sidecar, and make the test stub assert it (auditor mutation R15-DAG6).

### R15-20 — The local stack's object store cannot be pulled

> **Status: done** — decided 2026-10-08: replace it. The store is RustFS 1.0.1 (Apache-2.0), pinned by digest.
> Candidates were tested by running the lakehouse's integration tests against each: RustFS passed all 15 unchanged;
> SeaweedFS refused the key without an identity file; VersityGW's POSIX gateway answered HeadObject with a 400.
> The component is `object-store`, not "minio", and the lakehouse reads `OBJECT_STORE_*` rather than
> `AWS_*`, so a real cloud key in the same shell is never sent to it. `make local-up` removes the retired MinIO
> objects.
>
> Fixing it found two more defects. The store ran over `emptyDir`, so a pod restart — the memory-limit change
> in round eighteen was enough — emptied it while the catalogue still named its files. And nothing created the
> buckets the lakehouse and DVC write to, so they existed only while someone had made them by hand. The store
> is now on a persistent volume, and `scripts/local/provision_object_store.py` creates both buckets on every
> `make local-up`, reading their names from the lakehouse module and `.dvc/config`. The limit is 320Mi, against
> peaks of 153–222 MiB measured with the integration tests writing. That measurement also showed `--write`
> replacing a busier run's peak with a quieter one, so recorded peaks now ratchet per image.

**Mode**: CONSULT · **Found by**: round fifteen's remediation, pinning digests ·
**Size**: ~2h

`minio/minio:RELEASE.2025-04-22T22-12-26Z` no longer resolves anonymously:
Docker Hub answers 401 for every `minio/minio` tag (Prometheus, the control,
answers 200), and Quay requires authentication. A clean machine cannot run
`make local-up`. Decide the replacement: another S3-compatible store that
publishes images (the lakehouse needs only the S3 API), or authenticated pulls.
`tests/test_local_stack_images.py` carries the exception, which fails the day
it no longer applies.

### Not closed by a commit

- **R15-2** stays W-14: which promotion rule and which fold design is a
  decision, now with both halves watched and pinned.
- **R15-19**'s second half: a `pending` entry still flips to `adopted` when its
  file exists, whatever the file holds. Whether the content meets the closing
  condition is a review judgement; the date makes someone look.

## Round sixteen — what stays open, and why each one waits

QA-4 round sixteen audited `aea1410` and reported 0 P0, 1 P1, 4 P2 and 10 P3;
the report is committed as [`qa4/round-16.txt`](qa4/round-16.txt). Its verdict:
every figure #121 and round fifteen's remediation published reproduces, and
the dependency gate #121 made blocking examined 150 of the 275 packages in the
lock — so it could fail, but not on most of what this repository installs.

What closed, in *fix(gates): QA-4 round sixteen remediation*:

| ID | Finding | Closed by |
| --- | --- | --- |
| P1 | Trivy treated every workspace member's closure as a dev dependency and skipped it, and could not read the serving image's `~=` requirements at all | `TRIVY_INCLUDE_DEV_DEPS` on every Trivy fs step, held there by a test; the image's requirements resolved to exact pins per variant (`scripts/resolve_serving_requirements.py`); `scripts/check_scan_coverage.py` fails a scan that did not examine every registry package in `uv.lock` and every resolved pin. Locally: 149 of 268 before, 268 of 268 after. The HIGH and MEDIUM findings it then surfaced are fixed by upgrade (virtualenv, mako, multidict, gitpython, oauthlib) except R16-1 |
| P2 | `check_thresholds.py` was beaten by a flipped direction, a retargeted pattern, a decoy comment, a doctored `renamed_from` factor, and an unresolvable baseline | Value and direction read through the BASELINE's definition; patterns anchored at line start and required to match once; factors restricted to 1 and 100; an unresolvable or unloadable baseline fails. All seven of the auditor's attacks now fail |
| P2 | Bandit never scanned `orchestration/` and ran unpinned through `uvx` | Declared in the dev extra so `uv.lock` pins it; CI and `make verify` scan the mypy roots, held equal by a test |
| P2 | `test_security_controls.py` let any step that MENTIONED a tool vouch for it | A control is matched to the steps that RUN it (action or invoked binary); every running step must block unless listed as advisory with a reason |
| P2 | C6 passed the private account behind github.dev, vscode.dev, ghcr.io, shields, codecov, deepwiki, a root-relative link and `%2F` | The account matched behind any host; home directories and gists excluded by what precedes them. The per-host link pattern it superseded is removed — narrowing it no longer changed anything |
| P3 | KFP components pip-installed kfp at every step start, into `:latest` | `install_kfp_package=False`; the image is the base Deployment's unresolvable placeholder; the compiled spec is asserted to install nothing and to name a digest or the placeholder. W-8 recorded "the image tag half" closed; this was the half it missed |
| P3 | `delete_before` refused an aware cutoff and reported a no-op as the previous write's snapshot | Aware cutoffs converted to naive UTC; a delete that commits nothing returns `None`; rows counted at the two named snapshots; the boundary, three zones and the no-op tested on the filesystem backend (kills R16-LH2) |
| P3 | `write_demand` reported whatever snapshot a `refresh()` found, so a concurrent writer's commit became this run's | The id is read from the commit's own response metadata; a test forces the interleaving in both modes |
| P3 | The pre-commit mypy hook checked three of CI's six roots and was not triggered by `orchestration/` | The hook's entry is CI's `run:` line, `files:` covers every root, and a test holds both — and AGENTS.md's and CONTRIBUTING's documented commands, which also differed |
| P3 | C9 exempted `cd projects/../`, read the first `--vcs-ref`, and skipped `.markdown` | Directory normalised, the last ref read, both extensions scanned |
| P3 | The serving-core exemption and the coverage omit list skipped any `tests/` directory, including one inside the import package | Only the distribution's own `tests/` is skipped or omitted; a test reads the omit list with coverage's own matcher |
| P3 | P10 accepted a digest check of another file, `\|\| true`, a commented-out check, a branch on raw.githubusercontent.com, and `curl \| sh` | The check must name each downloaded file and not be swallowed; comments are not read; a branch URL is moving; a download piped to a shell fails |
| P3 | COMPLIANCE_MAPPING said no cluster had observed the NetworkPolicies enforced; this file and the local README said one had | The README and R11-2 are right: PR.PS and PR.IR now cite #105's measurement. The rest of that document is R16-2 |
| P3 | The override comment said the test fails "the day the pinning package admits" the fix | It fails once the newest LOCKED kfp does; the comment says so |
| P3 | Two statements in the audit prompt were wrong | See below; the next prompt states alert counts per tool and the measured suite time |

All thirteen of the auditor's mutations are in the catalogue, re-anchored
where this round moved their code, and all are killed — including the four that
survived the audit (R16-SEC1, R16-SEC2, R16-LH2, R16-CF4). Every fix above
carries at least one mutation of its own.

**The prompt's two wrong statements.** "Code scanning shows 0 open CVE alerts"
was true of Trivy alone, and only because of the P1: Scorecard's
VulnerabilitiesID alert listed 11. "A full suite takes ~25 min" was not
measured — 15m45s under parallel load. The next prompt gives the alert count per
tool and treats Scorecard's VulnerabilitiesID as a finding source.

### R16-1 — The serving image ships pyarrow 18.0.0 (CVE-2026-25087)

> **Status: done** — ml-service-template v0.32.0 (#268, released by #276) pins `pyarrow ~= 25.0.1` in all three
> files, verified on the image's Python 3.13 beside `numpy ~= 1.26.0` with an exact parquet round trip. The service
> is regenerated at v0.32.0 (a v0.31.0 regeneration first showed no local change to lose), the
> `.trivyignore` entry is deleted, and every set resolves to pyarrow 25.0.1. Closed 28 days before its expiry.

**Mode**: CONSULT · cross-repository · **Expires**: 2026-11-05 · **Size**: ~30min upstream, ~30min here

The resolution the P1 fix added made the image's dependencies visible, and the
first thing visible was `pyarrow ~= 18.0.0` from
`services/demand-forecast-serving/requirements.txt` — inside CVE-2026-25087's
range, fixed in 23.0.1. The workspace runs 25.0.1; only the generated service
is affected — its image, and, as QA-4 round seventeen found once every
requirement set was scanned, its `requirements-dev.txt`, `requirements-train.txt`
and `eda/requirements*.txt`, which pin the same range (this text first said
"only the image").
`services/` is generated (ADR-003), and ml-service-template pins `~= 18.0.0`
at its HEAD, so the fix cannot be taken here without forking.

Accepted in `.security-baselines/.trivyignore` for thirty days, not the
quarter the policy allows: the fix is one line upstream. **Closes when** the
template moves pyarrow to `>= 23.0.1`, a release is tagged, and this service is
updated to it with `copier update --vcs-ref <tag>` — then the entry is deleted,
and the expiry test fails if it is not.

### R16-2 — COMPLIANCE_MAPPING is stale beyond the row the audit named

**Mode**: AUTO · **Size**: ~3h

Correcting PR.PS meant reading the rest, and five other statements are no
longer true — Bandit "invoked by no workflow", Trivy "cannot fail a build",
`.security-baselines/` "holds zero entries", branch protection "two of four",
C7 "red at 37 commits" and "55 audit entries". Each is listed, dated, in a
notice at the top of that document, so none is read as current meanwhile. All
understate the controls. Re-verify every row against the tree and re-run
every command in its re-derive section; then build
`scripts/check_compliance_mapping.py` (quality-gates C3) at least for the
figures that section derives, which is the only thing that stops this
recurring.

### R16-3 — diskcache 5.6.3 has an advisory with no fixed release

**Mode**: CONSULT · **Size**: none until a fix exists

CVE-2025-69872 (MODERATE): an attacker who can write to a diskcache directory
can execute code when the cache is read, through pickle. Reached only through
`dvc-data`, whose cache lives in the repository's own `.dvc/` directory, owned by
the user who runs DVC — so the attacker the advisory needs already has that
user's files. Below the gate's HIGH threshold, so it does not block, and no
release fixes it. Revisit when diskcache publishes a fix (Dependabot proposes
it) or a scanner rates it HIGH, at which point the gate fails and decides it.

## Round seventeen — what stays open, and why each one waits

QA-4 round seventeen audited `f89a910` — #124's head, which landed during the
audit as `71528ad` with an identical tree — and reported 0 P0, 0 P1, 4 P2 and
9 P3; the report is committed as [`qa4/round-17.txt`](qa4/round-17.txt). Its
verdict: #122 and #123 hold where measured — the dependency scan reads what it
claims and matches a real pip install, the artifact loads in the image's
environment on real data, every round-sixteen attack on the thresholds gate
fails — and the README standard did not: its gate read layout, not the rules,
and five README sentences were false.

What closed, in *fix(gates): QA-4 round seventeen remediation*, with
ml-service-template's matching half:

| ID | Finding | Closed by |
| --- | --- | --- |
| P2 | Bandit's own `--exit-zero`, in CI and the Makefile, disarmed it with 250 tests green | `_blocks` reads the tools' own exit-zeroing flags and `set +e`; the Makefile's verify recipe is held to the same; CI's Bandit line is RUN against a planted finding and must exit non-zero, so an unlisted spelling still fails |
| P2 | The KFP components named the serving image, which cannot run them | Their own image path, held apart from the Deployment's by a test; W-14 qualified as in-process; building the image is R17-1 |
| P2 | P19 passed setext, indented and HTML headings, unlinked and in-section badges, chained or unfenced commands; never read a version; nothing held the standard identical across the repositories | `scripts/readme_standard.py`, byte-identical in both repositories: a CommonMark-faithful reading (held to markdown-it-py on an adversarial corpus), limits read from the standard, quick-start commands split on `&&`, `;` and pipes and checked for pins, the standard pinned by SHA-256 in both, and a sibling comparison when both are checked out. Copier is locked (`dev` extra) and every instruction runs `uv run copier`, held by a test |
| P2 | Five README statements were false | Corrected; the claim that the catalogue breaks every gate is now true — entries name their `gates`, the seven gates none broke have one, and a test fails an implemented gate with none. The thresholds gate, which had no row, is P20 |
| P3 | `check_thresholds` read text, not the bound value | Python thresholds read by value: the single binding of a constant, a field as its constructor sets it, a function default, a dict entry; a second binding of any kind is refused. The promotion comparison tolerance is a watched constant |
| P3 | The promotion agreement test checked a grid | A seeded sweep of 3,000 pairs near every bound, and a spy that both gates hand the rule exactly their inputs |
| P3 | `delete_before` miscounted under a concurrent commit | The count comes from the delete's own snapshot summary; a forced interleaving and a straddling-file case are tested, and so is the one-snapshot-per-delete assumption |
| P3 | A loaded artifact could not continue a warm start | `load` restores the generator as scikit-learn derives it; continuation from the artifact and from memory agree exactly while `max_features=1.0`, this model's setting — with feature subsampling it is reproducible, not identical (qualified in round eighteen) |
| P3 | R16-2's notice corrected one claim with another false one | Corrected (Checkov and tfsec baselines are empty) and the stale ADR count added, without typed counts |
| P3 | The scan omitted the image's pip/setuptools/wheel, the service's dev/train/EDA sets, and non-registry lock entries | All resolved and expected; R16-1's text widened to the four files that pin pyarrow 18 |
| P3 | Scorecard's filelock alert | A false positive: osv-scanner transitively resolves `requirements-dev.txt` to filelock 3.19.1; a real resolution gets 4.0.12, and the scan now reads that resolution |
| P3 | C6 missed `&#47;`, a zero-width space, a fullwidth slash, and home-directory paths | Text is read as rendered (entities decoded, NFKC, invisible characters dropped, look-alike slashes and backslashes folded); in a home path only a container directory is skipped |
| P3 | P10 accepted a check before the download, and `set +e` | The check must follow the download; a downloading step under `set +e` fails |
| P3 | ml-service-template's wording guard read README.md only | It reads `docs/CAPABILITIES.md` too (ml-service-template, same session) |

All thirteen of the auditor's mutations are in the catalogue, re-anchored
where this round moved their code; the five that survived the audit
(R17-BAN1, R17-W14a, R17-THR1, R17-THR2, R17-LH4) are killed.

### R17-1 — The KFP components' image does not exist

**Mode**: CONSULT · **Phase**: 2 · **Size**: ~1 day

The components name `ghcr.io/duqueom/ml-platform/demand-forecast-train` behind
an unresolvable placeholder, and nothing builds it: no Dockerfile in this
repository installs kfp, `demand_forecast`, polars and pyiceberg together.
Until it exists, W-14's "one verdict" holds where the tests run the gates, not
where KFP would. **Closes when** a Dockerfile builds that image from the lock,
CI builds it, and a P18-style gate imports `kfp`, `demand_forecast.promotion`,
polars and pyiceberg in it and runs the quality-gate component's function.
Deciding where it is built and pushed is the CONSULT half; it is the first
image this repository would build itself rather than generate.

### R17-2 — The service's heavy EDA set cannot be installed on the image's Python

> **Status: done** — ml-service-template v0.32.0 moved the set to ydata-profiling `~= 4.17` (the first release
> without htmlmin that supports 3.13), `matplotlib ~= 3.10` (4.13+ caps it at 3.10.0) and `setuptools ~= 80.10`.
> The last was a second defect found while fixing the first: ydata-profiling imports `pkg_resources` without
> declaring setuptools, so the set could not be IMPORTED on any Python whose venv lacks it — 3.12 included. A new
> upstream lane installs the set on the Dockerfile's Python and builds a report. Here `PYTHON_FOR` is empty: every
> set resolves on 3.13.

**Mode**: CONSULT · cross-repository · **Size**: ~30min upstream

`services/demand-forecast-serving/eda/requirements-heavy.txt` pins
`ydata-profiling~=4.6`, which pulls in `htmlmin 0.1.12`, whose build imports
`cgi` — removed in Python 3.13, the Python the Dockerfile's `FROM` names. On a
clean machine the set does not install there at all; it resolved in this
repository's first runs only from a warm uv cache, and CI's cold runner failed
on it (round seventeen's remediation, found by its own CI). It installs on
3.12 and 3.11, so the scan resolves it on 3.12
(`scripts/resolve_serving_requirements.py`, `PYTHON_FOR`) rather than skipping
it. **Closes when** ml-service-template moves the heavy EDA set to a profiling
release that does not need `htmlmin`, or states the Python it supports, and
this service is updated; then the override leaves `PYTHON_FOR`.

## Round eighteen — what stays open, and why each one waits

QA-4 round eighteen audited `746d6d6` — the first round to run L3, against the
local kind stack — and reported 2 P0, 0 P1, 3 P2 and 7 P3; the report is
committed as [`qa4/round-18.txt`](qa4/round-18.txt). Its verdict: the
NetworkPolicies, the serving path and every round-seventeen form hold where
measured, and two things did not run at all — the thresholds gate crashed
against any baseline at or after `746d6d6`, and Grafana was OOM-killed on every
start of the local stack.

What closed, in *fix(gates): QA-4 round eighteen remediation*, with
ml-service-template's matching half:

| ID | Finding | Closed by |
| --- | --- | --- |
| P0 | The thresholds gate's baseline loader serialised four fields of `Threshold` and dropped `symbol`, so every value-read threshold came back with an empty pattern and the gate crashed — and six catalogue kills came from that crash, not their properties | The loader serialises every field (`dataclasses.asdict`) and rebuilds through `_rebuild`, which refuses a field this gate does not know and reads every historical `renamed_from` shape; verified against the baselines `746d6d6`, `71528ad`, `aea1410` and `98a4359`, and against its own definitions. The six entries and R18-PV1 are now each killed by the test of their own property |
| P0 | Grafana 13.2.2 was OOM-killed at the 200Mi limit chosen for Grafana 11, so `make local-up`, `local-dashboards` and `local-verify` failed, and the bump had merged "verified against the suite", which never starts the stack | `platform/local/measured-memory.yaml`, generated by `scripts/local/measure_memory.py --write` on a running stack, records each component's image and peak working set; a test fails when a manifest's image is not the one measured, or its limit leaves less than 25% over the peak, or the manifests, the budget and the namespace quota disagree. Grafana's limit is 512Mi (measured 395), MinIO's 384Mi (measured 226). `make local-up` names only the deployments that are not available, with each pod's reason |
| P2 | An expression-valued `continue-on-error: ${{ true }}` disarmed Bandit, gitleaks and the Trivy gate with 79 tests green | `_blocks` treats any `continue-on-error` value but a literal false as non-blocking, accepts only the `if:` conditions it lists with their reasons, and reads `\|\| :`, `\|\| echo`, `if !` without an exit, `set +eu` and `soft_fail_on` |
| P2 | P19's parser missed images in heading lines, reference definitions inside containers or across lines, `<pre>` and fences under list items; `unpinned()` passed every spelling it did not list; the cross-repository pin ran only where both repositories were checked out | `scripts/readme_standard.py` (shared) is CommonMark's block algorithm with an inline pass and GitHub's tables, held to markdown-it-py on an adversarial corpus and 400 seeded generated documents, and to GitHub's renderer where the two differ. Quick-start commands are denied by default: each passes only when a rule reads it and finds what it runs pinned, and a range only when CI installs exactly that range. CI checks the template's two files out at a pinned commit and compares them byte for byte; a weekly job compares with the template's `main` |
| P2 | C6 passed `/home/<account>/projects/<private-repo>`, a Markdown-escaped slash, an empty inline tag inside the account, and a Cyrillic `O` in it | Every container directory in a home path is skipped and the next segment is read as a repository (`template_MLOps/` read as ml-service-template); the text is read twice, as written and as Markdown renders it; Cyrillic and Greek look-alikes are folded |
| P3 | `python_value` did not see a store through a subscript or attribute, `globals()`, `setattr`, a star import or `__post_init__` | Each is refused as a change made without a second binding, as are mutating methods, `exec`, `del`, an inherited or decorated class, and a function's rebound `__defaults__` |
| P3 | The `gates:` coverage test was satisfied by a label | An entry counts for a gate only when what it runs is that gate — its command, its script, or a test that executes it; tool gates name their holders. The four pre-commit mirror entries no longer claim P2 or P3 |
| P3 | Eight runnable copier commands ran whatever copier is on PATH, and the lock test admitted `uvx copier@latest` | All go through the lock — `uv run --project "$(git rev-parse --show-toplevel)" copier update` inside a service, which has a `pyproject.toml` of its own; the test reads every rendering copier command in a code block, a script, the Makefile, a workflow or a hook |
| P3 | `check_upstream_parity` read a worktree sibling as unreachable | `.git` may be a file; a checkout git cannot list fails rather than skips. Reading the sibling found `docs/CAPABILITIES.md` undecided since upstream's #265; it is rejected in the ledger, with the reason |
| P3 | P10 accepted a digest check run in the background, or consumed by `if !` without an exit | A check counts only when its failure fails the step: not swallowed by `\|\|`, backgrounded, consumed by a condition that does not exit, or followed by `&&` before more commands |
| P3 | The work order said warm-start continuation from the artifact and from memory "agree exactly" | They agree exactly while `max_features=1.0`, which is this model's setting; with feature subsampling the continuation is reproducible, not identical. `persist.py` states the same qualifier |
| P3 | Two statements in the audit prompt were wrong | Recorded here for the next prompt: state the stack's measured condition (`kubectl -n ml-platform get deploy`) rather than "already runs the full stack", and say which sibling-dependent checks run — C2, the README comparison and now the parity online half — rather than "the sibling-comparison tests" |

All eleven of the auditor's mutations are in the catalogue, re-anchored where
this round moved their code; the two that survived the audit (R18-BLK1,
R18-RS1) are killed.

**A Dependabot bump of a local-stack image now needs a person.** The memory
test fails until the new image has been started and measured, which no
runner here can do: run `make local-up`, then
`uv run python scripts/local/measure_memory.py --write`, and commit the ledger
with the bump. That is the point — round eighteen's defect was a bump nobody
ran — and RUNBOOK.md says so where an operator meets it.

## Not for an agent

Three items where doing the work autonomously would itself be the error,
whatever the confidence.

| Item | Mode | Why, and what an agent may do instead |
| --- | --- | --- |
| ADR-008's resolution (F-06, interface half) | **STOP** | The recommendation is a change to `ml-service-template` — a `task_type` copier question. AGENTS.md makes publishing anything outside this repository STOP, and [ADR-003](../decisions/ADR-003-service-template-consumption.md) §2 keeps the template authoritative, so the fix cannot be brought inside. **An agent may**: write the upstream issue text and the copier-question design as a proposal in this repository, and land W-4's gate. It may not touch the sibling repository, and it may not move [ADR-008](../decisions/ADR-008-serving-a-forecast-from-a-classification-scaffold.md) to Accepted — that is the human decision this is waiting on, and it has been waiting since 2026-08-10 |
| Terraform buildout (F-07) | **CONSULT** | Network, IAM, object storage, database and remote state are a design round with real cost implications, and constraints S1–S3 hold that no cloud resource exists yet. **An agent may**: author the definitions and run `terraform validate` and `terraform plan`, both read-only and both AUTO, and write down which prerequisites remain manual and how `terraform destroy` accounts for them. It may not `apply` anything: dev is AUTO only once a project exists, staging is CONSULT, prod is STOP |
| Branch protection on `main` | **CONSULT** | A repository-settings change rather than a code change, and it interacts with the single-maintainer flow — requiring reviews is unsatisfiable while requiring all four CI jobs is not. `scripts/setup_branch_protection.sh` exists; running it is the maintainer's call |

---

## Suggested pull request order

One pull request per task, in this order. The dependencies are few and real.

| # | Pull request | Depends on | Why here |
| --- | --- | --- | --- |
| 1 | W-2 — audit trail | — | Fifteen minutes, and it makes every pull request after it auditable |
| 2 | W-1 — re-measure and publish | — | The platform has no valid primary metric until this lands. Do it before anything reads that number again |
| 3 | W-3 — egress | — | Completes the deploy-path work the last round started; same files, same reviewer context |
| 4 | W-5 — coverage floors | W-1 | After W-1, so the new floors are measured against the fixed code rather than the broken one |
| 5 | W-4 — version gate | — | Lands red by design, so it needs its own pull request where the redness is discussed rather than buried |
| 6 | W-6, W-7 — plan and status gates | — | Both touch `check_doc_coherence.py`; sequence them to avoid a conflict |
| 7 | W-8 — pins | — | Independent |
| 8 | W-10 … W-13 | — | Small and independent; batch or split as convenient |
| 9 | W-9 — alerts | W-1 | Last, because the thresholds it alerts on may move when W-1 republishes the metric |

---

## One closing instruction

Every task above states what to fix and then what **class** to close. That
second half is not decoration, and it is the difference between this round and
the last one: the 2026-08-29 remediation fixed four defects and added four
gates, and widening the type gate immediately surfaced a second instance nobody
had looked for. Where a task offers a choice between fixing the instance and
closing the class, close the class — and if the class turns out to be wider
than the finding described, say so in the pull request rather than narrowing
the fix to match this document.
