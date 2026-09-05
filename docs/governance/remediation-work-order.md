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

1. Add the missing row, so the absence becomes visible:

   ```python
   COMPONENTS = [
       # ...
       Component("1", "Drift detection (DriftSignal + PSI)", ["libs/ml-core/src/ml_core/drift.py"]),
   ]
   ```

   With no files present it renders ⬜, which is the correct and honest state.

2. Then close the class: add a test asserting that every deliverable bullet in
   the technical plan maps to a `COMPONENTS` row. This is the same defect the
   status document exists to prevent, relocated one level up, and it will find
   more than drift.

**Acceptance**: the regenerated document shows drift as ⬜ and its totals move;
the new test fails when a plan deliverable has no component.

### W-8 — Two mutable references inside a repository that pins everything else

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
| F-21 | `model_mae` is computed over all test rows while `baseline_mae` is masked to rows carrying a baseline. Currently latent — the mask measures 100% true after the densification fix — but it goes live the moment the drop subset or the season changes independently. Mask both or neither |
| F-22 | A personal email address is hard-coded as the EDGAR `User-Agent` in a public repository, with no environment override. SEC requires a real contact, so read it from an environment variable with a clear failure when unset |
| F-23 | `local_catalog()` defaults to a localhost MinIO endpoint with a literal credential and no environment guard. Outside local, an unset variable resolves to a wrong endpoint instead of failing closed |
| F-25 | `detect_leakage` divides `leaking_rows`, counted over non-null rows, by `total_rows`, counted over all of them — understating the leak rate when nulls are present |
| F-28 / F-29 | Shadow-mode sampling uses the unseeded global `random`, which `seed_everything` also seeds. `DEFAULT_ENDPOINT` in `tracing.py` reads its environment variable at import time, so a test cannot monkeypatch it afterwards |

**F-16 and F-24 are deliberately excluded from this list.** The agent core's
connection reuse and shared breaker state (F-16) need a benchmark and a
decision about the replica count; the policy gate's keyword matching (F-24) is
a design question about detection efficacy rather than a defect. Both belong in
a round with a human in it.

---

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
