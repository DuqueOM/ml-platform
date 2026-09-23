# Changelog

All notable changes are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Backfilled at commit 18, before the first tag.** A CHANGELOG is for consumers
upgrading between versions, so the real deadline is the first release, not the
first commit — by that standard this was not late. What backfilling did cost is
the reasoning: written retroactively, entries are reconstructed from commit
messages and record what changed rather than why it mattered. Check C8 keeps
`[Unreleased]` current so the next version is not written the same way.

Recorded here rather than quietly written as though it had always been
maintained.

Pre-1.0: minor versions may change contracts. Every such change is called out.

## [Unreleased]

### Changed — the agent-local history is a tag now, not a branch

- The 31 rewritten commits moved from the `history/agent-local` **branch** to
  the `archive/agent-local` annotated **tag**, and the branch is deleted. The
  ref is as immutable and as reachable as before — `git log archive/agent-local`
  — without a long-lived branch that reads as work in progress next to `main`.
  ADR-002's requirement is unchanged: the commits are evidence and they are
  kept.
- The command documented in `projects/store-assistant/docs/decisions/README.md`
  was wrong in two ways and returned nothing: it named the branch, and it looked
  under `docs/decisions/` when `git-filter-repo` had rewritten those paths onto
  this repository's topology, under `projects/store-assistant/`. Both corrected.

### Added

- **The Copier render root is parsed, so a stray delimiter cannot break the
  generator for everyone.** `scripts/check_template_render_safety.py`, gate P15,
  ported from `ml-service-template`. `copier.yml` sets `_templates_suffix: ""`,
  which makes **every** file under `templates/project/` a Jinja template — not
  only the ones that look like one. A file that happens to contain the
  delimiters therefore does not render oddly; it aborts `copier copy`, and
  whoever ran the generator gets nothing at all.

  **What it adds to the render test — corrected, see Fixed.**
  `tests/test_project_generator.py` renders the payload for real and remains
  the authority on behaviour. A render exercises only the branches its answers
  select; a parse examines every branch of every file for any answers, and costs
  milliseconds rather than a render — which is why it can also run in
  pre-commit.

  **Three deliberate departures from upstream, recorded rather than silent.**
  Path *segments* are parsed as well as file bodies: copier renders those too,
  and this render root has one, `src/{@ project_slug @}/`, which the original
  would not have examined. The single function was decomposed and a `--root`
  flag added, so each defect class is watched failing against a temporary tree
  — breaking the real payload to prove the gate works would put shared state
  under three other checks and a concurrent render test, which is the defect
  class this repository has now found four times. And `jinja2` moved from a
  transitive of the `orchestration` extra to a declared dependency: the gate
  would otherwise have worked on a machine that had run `uv sync --all-extras`
  and raised `ImportError` on a base sync, which is a verdict replaced by an
  environment error.

  The delimiters are read from `copier.yml` `_envops`, never hardcoded, and
  they are not Jinja's defaults — this repository uses `{@ … @}` so a generated
  project's GitHub Actions `${{ … }}` does not collide. That choice removes the
  Actions hazard and introduces a quieter one the gate now names in its failure
  output: bash's `"${@}"` contains `{@`, and `${#array[@]}` opens `{#`, the
  comment token. Both are reproduced in
  `tests/test_template_render_safety.py`.

- **Fairness metrics promoted to `libs/ml-core`, rewritten rather than copied.**
  `ml_core.fairness` — disparate impact ratio, equal opportunity difference,
  demographic parity difference and the equalized-odds FPR gap, over
  `GroupOutcome` counts. The platform had **no fairness implementation at all**
  while Phase 4 promises fairness gates and `AGENTS.md` carries an escalation
  trigger keyed to a disparate impact ratio — a governance rule with nothing to
  govern. Nothing in the inventory tracked it either, so nothing could report
  it absent.

  **Rewritten, and the distinction matters.** `ml-service-template`'s version
  was correct arithmetic wrapped in things ADR-001 excludes from `ml-core`:
  `PROTECTED_ATTRIBUTES` TODOs naming features, pandas DataFrames, JSON file
  output, logging, and a second `calibration_error` beside the one
  `ml_core.decision` already exports. ADR-003 makes the template authoritative
  on **service-level** concerns and its point 3 assigns multi-project libraries
  here, so this is not a local patch of upstream.

  **The design problem was never the arithmetic.** Every one of these metrics
  has inputs on which it cannot be computed, and the dangerous outcome is
  `None` reaching a gate that reads absence as absence-of-finding. So an
  undefined ratio **escalates rather than passing**: a model that selects
  nobody has no defined disparate impact, and the obvious implementations
  either return 1.0 or omit the key — both report the most discriminatory
  possible model as the fairest. `demand-forecast`'s gates file already named
  that failure in prose ("a gate that passes by being uncomputable") as its
  reason for deleting a fairness gate rather than keeping a plausible one; it
  is now executable.

  A group too small to be reliable is **reported and does not escalate** —
  making a rare category a STOP blocks every audit that has one, and the
  blocked party's cheapest fix is deleting the category, which destroys the
  evidence rather than the disparity.

  `Action` is imported from `ml_core.drift` rather than redefined: a fairness
  finding and a drift finding both end in a human decision or they do not, and
  `agent-ops` consumes them through one enum. 32 tests, 100% line and branch
  coverage.

- **The drift contract exists, four months after ADR-007 specified it.**
  `libs/ml-core/src/ml_core/drift/` — `ReferenceWindow`, `DriftSignal`,
  `DriftResponse`, `Verdict`, `Action`, `Direction`, `worst_action`. The
  inventory declared `drift-contract` at Core tier with a detector pointing at
  that path; the path did not exist, which is the same defect DVC carried.

  The module computes almost nothing. Its value is that four ways of producing
  a worthless drift number are now impossible to express: a measurement with no
  method (ADR-005 rule A, refused); a baseline that moved with no record
  (`ReferenceWindow.roll` links what it replaced, because ADR-007 permits
  rolling and forbids rolling *silently*); a verdict with no declared response
  (`DriftResponse` has no defaults — a field with a default is a field nobody
  fills in); and a direction left implicit.

  **`Direction` is the one that would have bitten.** PSI, embedding distance
  and cost-per-request drift upward; recall@5, accuracy and interval coverage
  drift downward. A contract assuming one silently inverts the verdict for
  every metric of the other kind — toward "stable", which is the half nobody
  checks. 0.55 is a WARNING against a recall floor and DRIFTED against a PSI
  ceiling, and a test asserts exactly that.

  **AGENTS.md's escalation trigger is encoded, not restated.** "Drift PSI above
  TWICE the configured threshold" becomes `escalate_at`, defaulting to
  `2 x drifted_at` for an upward metric and **refused** for a downward one:
  doubling a recall floor of 0.5 gives 1.0, putting the STOP boundary at
  perfect performance where it can never fire. Escalation only ever raises, so
  a project declaring a milder response does not opt out of a STOP.

  35 tests, 100% line and branch coverage. The four detectors remain
  per-project and absent, correctly: their inventory rows point at
  `projects/credit-risk`, `projects/doc-intelligence` and `projects/agent-ops`.

- **The tool registry publishes its capability surface as data.**
  `ToolRegistry.manifest()` and `mutating_tools()` — tools register by import
  side effect, so "what can this agent do, and what may it mutate" was
  answerable only by running the program, which is the one method unavailable
  to a reviewer or an audit. It is the move this repository already made twice:
  thresholds became data in `evals/gates.yaml`, dataset bytes in
  `datasets.lock.json`.

  Descriptions default to the tool's docstring summary, so the five existing
  store tools gained descriptions with zero changes at any call site — and a
  tool with neither shows as an empty string in the manifest rather than being
  absent from it. The idea is adapted from the plugin-manifest convention in
  `deepseek-ai/deepseek-harness`, evaluated and **not** forked: a
  TypeScript/pnpm runtime in a uv workspace is the second-toolchain argument
  ADR-004 has already rejected five times.

- **Data versioning got an owner per class of data, and the pin got
  committed** ([ADR-009](docs/decisions/ADR-009-data-versioning-ownership.md)).
  `dvc` sat at Core tier in the technology inventory with `detect: [".dvc",
  "dvc.yaml"]` matching nothing, `AGENTS.md` carried a permissions row for a
  tool no checkout could run, and `docs/datasets/register.md` claimed datasets
  were versioned by "a download script plus a DVC pointer". Half of that was
  true.

  **The defect was narrower and worse than "DVC is missing".** `fetch.py` has
  computed a SHA-256 per file since it was written — into `manifest.json`,
  which lives under `data/`, which is gitignored. `git ls-files data/` returned
  nothing. The digests proved *this machine keeps getting the same bytes* and
  could not prove *everyone gets the same bytes*, which is the entire value of
  a pin. A source re-publishing different content under a stable URL would have
  moved every downstream number with no diff anywhere.

  **Three mechanisms, one mechanical criterion each**, so assignment is not a
  judgement call: Iceberg owns pipeline tables; `docs/datasets/datasets.lock.json`
  owns third-party downloads, because an authoritative URL can re-serve the
  bytes and a digest is therefore sufficient; DVC owns data with no such URL —
  generated, derived, curated or labelled here — because for those a digest
  records with cryptographic precision that the data was lost.

  Built: the committed lock (263 MB across 3 files pinned), `fetch.py --verify`
  and `--write-lock`, `tests/test_dataset_lock.py` (8 tests), and `.dvc/` with
  an S3-protocol remote and analytics disabled. `--verify` was **proven able to
  fail** by falsifying a pin, which is the check ADR-005 rule K asks for and the
  one most often skipped. The inventory now reports `dvc` Built because the
  artifacts exist — the YAML was not edited to make that happen.

  **A correction this work forced.** An earlier reading of this area claimed
  the retrieval gold set was unversioned data gating promotion. It is not: it
  is `libs/llm-core/src/llm_core/doc_questions.py`, Python source in git,
  labelled by `path#heading` so a heading added elsewhere cannot silently
  re-point it, with `test_doc_retrieval.py` failing when a label stops
  resolving. Moving it to DVC would have made it less reviewable, not more.

- **The agent core landed, four months after ADR-002 decided it.**
  `agent-local` — multi-tier routing, a deterministic policy gate whose rules
  are versioned data, a fail-closed tool capability contract, cross-tier
  verification, decision telemetry with PII redaction, per-tier circuit
  breakers — was still a separate repository on disk while this one carried
  quality-gate rows written against its tests. `core/` is now `libs/llm-core`
  and `usecases/tienda/` is `projects/store-assistant`, exactly the placement
  ADR-002 wrote.

  **History first.** The 31 commits were rewritten onto this repository's
  topology with `git-filter-repo` and pushed as `history/agent-local`. ADR-002
  asks for the commits because history is evidence; branch protection requires
  linear history, so a subtree merge is impossible and an archived ref
  satisfies the intent without a policy exception.

  **Two boundary defects the move exposed, both fixed.** `load_usecase(name)`
  resolved against `REPO_ROOT / "usecases"`, so the library knew that projects
  exist and where; it takes the directory now. `load_agent(name)` imported
  `usecases.<name>` through `importlib`; `build_agent(config, registry)` takes
  the registry from the caller. Both were dependency-direction violations, and
  the inversion is a better statement of what a use-case is.

  The suite split along the same line, which is how the boundary was verified
  rather than asserted: everything needing the store's prompts, policy data or
  tools moved to the project, and what the library kept runs against a
  synthetic use-case built in a temporary directory. 156 tests across the two.

  `store-assistant` satisfies the project contract — README, `evals/gates.yaml`
  with three blocking gates each naming a test that resolves, and a model card
  whose limitations section says plainly that the model's judgement is not a
  control. P1 is a recorded deviation with its cost, like `rag-assistant`'s:
  a migrated project has no answers file.

### Changed

- **The demand-forecast model card no longer has four TODO sections.** Intended
  use, fairness, failure modes and human oversight (QA-4 R11-5), written from
  what this repository already measures rather than from what a model card
  usually says.

  The fairness section records that fairness is **not measured**, which is the
  finding: the subgroup that matters is geographic, a staffing decision is
  taken per zone, and 89.6% marginal interval coverage is an average over 255
  zones that cannot answer whether any particular one is systematically
  under-covered. It names what would close it, and that six zones receive no
  forecast at all.

  The failure-modes table separates the failures with a mechanism — an unknown
  zone raises, a schema mismatch refuses to load, a gate below threshold blocks
  promotion — from the ones with none, which is where the drift contract's
  absence and the unmeasured conditional coverage are listed.

- **The model artifact stopped carrying workspace objects, so a container can
  read it.** `ARTIFACT_SCHEMA` is 2 (QA-4 R11-3). Schema 1 pickled
  `ForecastModel` wrapping `SplitConformalRegressor`, which meant loading it
  required `demand_forecast` and `ml_core` installed. The serving image
  installs neither, so the artifact could not be read there at all — before any
  numpy or scikit-learn version was compared, which is why gate P14 could not
  see it.

  The file now holds a scikit-learn estimator and data. The conformal regressor
  travels as the two numbers calibration produces — its quantile and the size
  of the calibration set, both now public on the class — and `load` rebuilds it
  through `SplitConformalRegressor.from_calibration`. A reader needs
  scikit-learn, numpy and joblib; `test_artifact_portability.py` asserts the
  artifact's bytes name no workspace package, and separately that a
  container-shaped reader gets predictions and intervals without importing
  anything from this repository.

  A schema-1 file is refused with a message saying why rather than converted:
  a conversion would have to trust fields whose meaning is what changed.
  ADR-008 keeps `Status: Proposed` — the classification-schema half is
  untouched, and flipping it would lift P14's exemptions over version straddles
  nobody has fixed.

- **The headline forecast metric was re-measured, and it fell by more than half.**
  Densifying the panel fixed the P0 but nothing re-ran the backtest, so
  **+55.8% skill** — published against the mis-specified baseline — stood as
  this platform's primary claim while being known-invalid with no replacement.
  It is replaced here rather than corrected in place; the dated `[0.1.0]` entry
  keeps the number it published, because the error is the more instructive half.

  Measured from the two registered months (`yellow_tripdata_2024-01/02`,
  checksums verified against `data/nyc-tlc/manifest.json`) rather than from
  `read_demand()`, which would have reproduced the old sparse shape and
  reported it as the new one:

  | | Dated entry | Corrected |
  | --- | --- | --- |
  | Hourly rows | 151,904 | **357,426** |
  | Modellable zones | 140 of 261 | **255 of 261** |
  | Skill, 3 folds | +55.8% | **+23.0%** |
  | Skill, 5 folds (current default) | not measured | **+12.6%** |
  | Coverage, 5 folds | 89.8% | **89.6%** against 90% nominal |

  **Both fold designs are reported because the dated entry used three folds and
  `evaluate()` now defaults to five.** Comparing +55.8% against +12.6% would
  charge a design change to the defect. Like for like, at three folds, the
  correction is **+55.8% → +23.0%**: the broken baseline was roughly twice as
  easy to beat, not three times.

  Fold design: expanding window cut on TIME, 168-hour test horizon, gap of
  `LONGEST_LAG` (168h) so training cannot reach the test window through the
  lags, conformal calibration on the last 168 hours of each training window,
  `seed=42`. Each figure is two readings at the same seed, byte-identical —
  a single reading is not a measurement.

  **Modellable zones nearly doubled, and that is the same units error one scale
  down.** `MIN_ZONE_HOURS` is documented as hours and counts rows; on a sparse
  panel those differ, so 115 zones with enough history were excluded for
  lacking rows they did in fact have. Densification made rows and hours the
  same thing, and the threshold started measuring what it says.

  Both figures clear the floors that gate them — `MIN_SKILL = 0.05` and
  `MIN_COVERAGE = 0.85`. No threshold was moved, and lowering one to fit a
  measurement is STOP.

- **The Iceberg table was re-ingested to the fixed shape**, 151,891 sparse rows
  replaced by 357,426 dense ones, at snapshot `5953582871017899527`. Time
  travel to the pre-fix snapshot `1293138664020475634` still returns the
  151,891-row panel, so the correction added history rather than rewriting it.

### Fixed

- **A maintainer's personal email address was hard-coded in a public
  repository.** QA-4 finding F-22. `rag_assistant.ingest` sent it to EDGAR as
  the `User-Agent` SEC requires. The address now comes from
  `EDGAR_USER_AGENT`, resolved before the first request or directory is
  created, and there is no default: SEC blocks the IP of a scraper sending a
  generic contact, so a plausible-looking default would either publish
  somebody's address or earn a ban that surfaces later as a network error.

  `projects/rag-assistant/tests/test_ingest_contact.py` covers the refusal
  (unset, blank, whitespace), the configured value, and that the message says
  which variable to export. It also greps the module for any address at all,
  which fails against the previous revision. Addresses at the domains RFC 2606
  reserves for documentation are exempt — the error message carries one so the
  fix can be copied — and that exemption exists because the guard flagged it on
  its first run.

  Unchanged, and deliberately: the security contact published in `SECURITY.md`.
  A reporting channel has to be reachable; an address baked into code that runs
  is a different thing.

- **Five documents stated closed gaps as open, or a possible check as
  impossible.** QA-4 round eleven, P2 and P3. `docs/COMPLIANCE_MAPPING.md`
  reported the cloud overlays as carrying no Pod Security label, the image as
  `:latest` and the policies README as describing Kyverno — all three closed.
  It and three other places — the policies README, the local overlay's comment
  and the manifest tests' docstrings — said kind cannot enforce NetworkPolicy,
  which round eleven disproved on a live cluster. The policies README omitted
  the egress policy beside it. The audit brief listed five shipped Phase 1
  components as not done, restated a figure its own rule says not to restate,
  and its round-eleven draft omitted open findings.

  All are corrected, and what remains open is no longer implicit:
  `docs/governance/remediation-work-order.md` gains a *Round eleven* section
  giving each open item its mode, what it waits on and its closing condition —
  the namespace-label contract, local enforcement evidence, the artifact the
  container cannot import, the hand-written serving seam, the model card, an
  unread configuration field and three small items. W-3 and W-4 are marked done
  with the commits that did them.

- **The egress test could not fail, and it checked the wrong port.** QA-4
  rounds ten and eleven, P2. `_permits` matched a substring of the serialised
  rule, so the metadata server's `ipBlock` satisfied the HTTPS assertion:
  deleting the `0.0.0.0/0` rule left the test green. And it asserted the
  metadata server on 443, which no cloud metadata service uses, while nothing
  asserted 80, which GCP's metadata server, AWS IMDS and Azure IMDS all serve.

  The assertion is now structural — exact CIDR or namespace, exact port — and
  checks 80 is admitted and 443 is not. The policy itself dropped 443 on the
  metadata server, which admitted a port nothing needs. Watched failing in a
  throwaway worktree: removing the HTTPS rule fails all six cloud cells, and so
  does moving the metadata server back to 443.

- **One subprocess in twenty-five had a bound, and no CI job but one had a
  timeout.** QA-4 round eleven, P3. A gate waiting on a wedged git or a hung
  verification command does not fail; it holds the runner until GitHub's
  six-hour default and reports nothing about why.

  Every call in `scripts/` is now bounded. Git and grep calls take a
  per-script `SUBPROCESS_TIMEOUT_SECONDS` and fail closed — a gate that could
  not finish must not read as one that passed. The local preflight treats a
  probe that times out as "not running", because `docker info` against a
  wedged daemon never returns, which is common under WSL.
  `tests/test_subprocess_bounds.py` checks every call from the AST, so the next
  unbounded one is a red test.

  **The status generator needed more than a keyword, and the first
  explanation of why was wrong.** `subprocess.run(shell=True, timeout=)`
  kills only the shell. The comment first claimed the call then blocks on the
  pipe the grandchild holds open; measured, it returns on time and the
  grandchild keeps running. Here that grandchild is `uv run pytest`, an orphan
  still writing probes into the repository after the document recorded it as
  timed out. `_verify` now runs each command in its own process group and
  kills the group; the test demonstrates both halves — `run` leaving a
  survivor, `_verify` leaving none. Its comments no longer describe the
  verification pool removed in *perf(status): remove the verification pool, which cost 37% and bought nothing* as current.

  Every CI job carries `timeout-minutes`, sized from the last five green runs
  rather than guessed: 75 for repository invariants (47.4 min measured at its
  slowest), 10 to 20 for the rest. The Scorecard job was bounded only after
  reading the verifier that decides whether its published results are
  accepted.

- **The residue guard watched a hand-written list, and the list was already
  stale.** QA-4 round eleven, P2. `tests/test_gate_scripts.py` checked that it
  restored seven named paths. Removing the ADR restore from a test's `finally`
  left `docs/decisions/ADR-007-*.md` deleted on disk and the module passed —
  that path was never listed, and neither were five others the module writes.
  A list of what a module touches goes stale exactly when a probe is added,
  which is when it is needed.

  The helpers now record every write: `temporarily()` stores each path's bytes
  before the first write and removes every directory it had to create, and a
  new `temporarily_absent()` covers deletion. The four probes that wrote
  directly now go through them. That also fixes a leak the hand-written
  cleanup had: it removed `probe/` and left `.terraform/` behind. Three tests
  guard the guard: `_residue()` as a pure function against every shape of
  unrestored write, the helpers leaving no directory behind, and an AST check
  that fails on any write in the module that bypasses them — so an unrecorded
  probe is now a red test rather than an unwatched path. The auditor's
  reproduction was re-run in a throwaway worktree with the restore sabotaged:
  the module fails naming the deleted ADR.

- **The serving-seam gate made a promise it could not keep, read its ADR from
  the wrong place, and had no test.** QA-4 round eleven, P2 and P3, in P14.

  It said it goes red "the moment a fourth straddle appears". It cannot:
  `SEAM` compares numpy, scikit-learn and joblib, all three are exempt, and a
  straddle in any other package is never compared — the audit added scipy and
  pandas straddles to the container's requirements and got OK. The docstring,
  the CI comment and the P14 row now state what turns it red (the ADR being
  decided, or an exemption outliving its straddle) and what it does not see.
  An exemption for a package outside `SEAM` is now itself a failure, since it
  could never be reported as outlived.

  Its ADR status check searched the whole document, so an accepted ADR quoting
  `- **Status**: Proposed` in its history kept the exemption, and a
  reformatted `**Status:** Proposed` lifted it while the ADR was undecided.
  Only the header is read now, in both bold placements, failing safe when no
  status is readable.

  `tests/test_artifact_compatibility.py` covers every path against temporary
  lock, requirements and ADR files. Five of its tests fail against the previous
  script and pass against this one; the other eleven cover paths it already
  honoured.

  Round eleven also found the container cannot import the artifact at all: it
  pickles `ml_core` types and the image installs no workspace library. That is
  not a version question, so it is not P14's to catch; it is recorded in
  ADR-008, whose Context also carried three statements the repository
  contradicts — that nothing calls `joblib.dump`, an image tagged `:latest`,
  and readiness on `/health/ready`. All three are corrected there.

- **The render-safety gate was justified by a claim that was false, and could
  pass over nothing.** Three findings from QA-4 round eleven, all in P15.

  Its justification — in the script, the gate row, the parity ledger and this
  CHANGELOG — said `tests/test_project_generator.py` renders a single answer
  set. It renders three of the four project kinds; the claim came from a grep
  that found the default `ANSWERS` and missed the parametrize overriding
  `project_kind`. The kind it really omitted, `agent`, is now rendered, and the
  four documents now make the argument that survives: a parse covers every
  branch for any answers, a render only the branches its answers select.

  It printed `OK — 0 file(s)` with exit 0 for an empty render root, and for a
  checkout living under any directory named like a cache, because `SKIP_DIRS`
  was matched against absolute path components. A render root with no payload
  file is now a setup error, and skip rules apply only inside the root. Both
  are reproduced in `tests/test_template_render_safety.py`.

- **Every cloud overlay denied DNS, and the only assertion checked a name.**
  All seven kustomizations — and the base — used `commonLabels`, which adds
  labels to SELECTORS as well as to resources, including selectors that point
  at pods the kustomization does not own. `allow-dns`'s peer selector
  `{k8s-app: kube-dns}` therefore rendered as `{cloud, environment, k8s-app}`,
  which no CoreDNS pod carries, so under `default-deny` every lookup in all six
  cloud overlays timed out. QA-4 round ten found it by rendering; round eleven
  proved it on a live kind cluster — `;; connection timed out; no servers could
  be reached` with the rendered policies, resolution restored with the selector
  as written. `tests/test_gitops_manifests.py` asserted that a policy NAMED
  `allow-dns` existed, which it did.

  Replaced with `labels:` using `includeSelectors: false` and
  `includeTemplates: true`, in the base and every overlay. Rendered before and
  after, field by field: the only changes are selectors — the DNS peer, the two
  serving policies, and the Deployment, Service and PDB, all now `{app:
  demand-forecast}` — while resource metadata and pod-template labels are
  unchanged, so anything selecting pods by `environment` or `cloud` still
  matches.

  **The Deployment selector changed, and `spec.selector` is immutable.** On a
  cluster running the old manifests an apply is rejected and the Deployment has
  to be recreated. Nothing has been deployed (L4 evidence is zero), so this is
  the cheapest moment this change will ever have; it is stated because the next
  one will not be.

  Three tests, each watched failing: a ban on `commonLabels` anywhere under
  `platform/`, parsed rather than grepped; exact equality on the rendered DNS
  peer, because containment would accept the extra keys that were the defect;
  and every workload and policy selector checked against the labels the pod
  actually carries — the opposite failure, a selector matching nothing, which
  applies cleanly. The first two fail on the previous tree; the third passed
  there, because commonLabels kept selectors aligned with their own pods, so it
  was proven separately against a mistyped policy selector.

An independent audit found three defects that every existing gate passed over.
All three are closed here, each watched failing before and passing after.

- **[P0] Every lag and the seasonal-naive baseline were computed by ROW offset,
  not hour offset.** `to_hourly_demand()` used `group_by`, which emits a row
  only for hours that had a trip, so an hour with zero demand vanished.
  `features.py` then builds every lag with `shift(n).over(zone)` and the
  baseline with `shift(168)` — row offsets, on a panel whose rows are not
  hours. Reproduced independently on a synthetic panel with 40% of hours
  empty: **`lag_24` reached back a median of 41 hours** (p90 48, max 62) and
  **the weekly baseline 286** instead of 168.

  It is not leakage — every value still comes from the past, which is exactly
  why no leakage test could see it. It is a units error, and it flatters the
  model: the baseline degrades faster than the model does, so reported skill
  inflates. This repository's own trail shows the shape, +12.2% skill on
  synthetic data against +55.8% on real data, and the fixture in
  `test_training.py` is a perfectly contiguous grid — which is why no test
  could have caught it.

  The panel is now densified to a complete hourly grid per zone, within each
  zone's own observed span. After the fix `lag_24` reaches back exactly 24
  hours and the baseline exactly 168. A densified hour keeps `mean_distance`
  NULL rather than 0.0: the mean of no trips is undefined, and zero would state
  that trips occurred and were short.

- **[P1] A DAG task read two attributes that do not exist.**
  `demand_forecast_training.py` logged `report.rejected` and `report.total`;
  `IngestReport` has `rows_read`, `rows_written`, `violations` and
  `reject_rate`. It would have raised `AttributeError` on the first real run.
  Three things had to be true for it to hide, and all three are fixed: nine DAG
  tests import the graph without executing a task body, **`orchestration/` was
  outside the type gate**, and **the projects shipped no `py.typed`**, so mypy
  would have seen an untyped import even inside the gate. Widening the scope
  immediately surfaced a second instance of the same class —
  `WarehouseValidation.failed_expectations`, which is `failed`.

- **[P1] The production overlay provisioned an identity and a secret that
  nothing used, and advertised a scrape the cluster refused.** The Deployment
  named no ServiceAccount, so it ran as `default` — which cannot carry a
  Workload Identity or IRSA binding, while the repository's own invariant reads
  "ALWAYS IRSA / Workload Identity". The ExternalSecret resolved two remote
  keys into a Secret no container referenced. And the pod annotated
  `prometheus.io/scrape` on port 8000 while the only ingress rule admitted
  `ingress-nginx`, so under `default-deny` the scrape was denied and the SLO
  rules rested on a series that would never arrive. Six overlays, all
  rendering green — an annotation is a request and a NetworkPolicy is the
  answer, and nothing compared them.

- **A pre-commit battery nobody can afford to run.** The same audit measured
  the suite from the other end: `pytest libs` and `pytest projects` finish in
  about **eight seconds each**, and `pytest tests` takes **over thirty
  minutes**. Reproduced here, and the mechanism narrowed to one number: the
  status generator runs **41 verification commands** — most of them
  `uv run pytest` — and **five test files invoke it**. Timed on an otherwise
  idle machine, `pytest tests/test_status_layers.py` alone exceeds ten
  minutes; `pre-commit run --files CHANGELOG.md`, on a one-file documentation
  change, did the same.

  A first reading of this blamed the generator for invoking itself
  recursively. It does not: no component's verification command runs a test
  file that executes it, checked rather than assumed, and the fix that
  diagnosis produced was reverted before it landed.

  Moved to the manual stage. It is still a gate — CI runs it on every push and
  `make verify` runs it locally — but a hook that costs ten minutes on a typo
  is a hook people route around, and they route around the whole battery,
  including the checks that catch real defects in seconds.

- **[P1] `terraform destroy` would have refused.** `google_container_cluster`
  did not set `deletion_protection`, and `hashicorp/google ~> 6.0` defaults it
  to true. The technical plan makes destroy the cost control — *"the phase is
  not complete until the billing export shows zero standing spend"* — so the
  one control the greenfield posture depends on was disabled by a provider
  default. Now explicit, with the reasoning, and asserted as EXPLICIT rather
  than as a particular value. AWS is not symmetric and the test says why:
  `aws_eks_cluster` gained the argument in provider 6.x, so under the pinned
  `~> 5.0` demanding it would produce invalid Terraform — the test reads the
  pin instead of remembering it.

- **Gate A5 passed by selecting nothing, and A3 and S3 with it.**
  `uv run pytest -k tool_contract` matched no test in this repository and
  **exited 0** — pytest deselects rather than fails — while the row carried no
  PENDING marker. The selectors had been written against `agent-local`'s suite,
  which is why they looked arbitrary here.

  The instance is closed by the migration; the class is closed by C4, which now
  rejects a `pytest -k` selector matching no test name or module in the tree.
  **It found a third on its first run**: S3, "Serving invariants", whose
  selector `serving_contract` appears nowhere in the repository and never did.
  That row is now PENDING with the reason — `serving-core` is deliberately
  empty until a second serving consumer exists, so there is nothing for those
  invariants to hold over yet.

  A4 was worse in a quieter way: its command was `--check cost`, a fragment of
  a command line rather than one, so nothing could have run it. Marked PENDING
  with what closing it means.
- **The L1/L2 coverage gate measured a run that no longer executes the
  library.** After the migration split the agent core's tests by ownership,
  `pytest libs/` reported 76.48% lines and 57.85% branches while the suite that
  actually runs the code reported 92.70%. The floors did not move; which runs
  count did, and the alternative — a library suite duplicating a project's — is
  the duplication ADR-001 exists to avoid.
- **C6 suppressed its `ok` line for one of its two failures, and the test could
  not tell.** The round-seven fix made a denylisted-name FAIL and a
  non-public-link FAIL both suppress the reassuring summary above them. Only
  the link half did: `before = len(failures)` was snapshotted AFTER
  `_check_forbidden_names`, so the guard could see only what the link scan
  added, and the denylisted name — the standing absolute constraint, and the
  more serious of the two — kept printing `ok` directly above its own `FAIL`.

  It shipped green because the regression test used a link probe: **the same
  half the fix touched**. That is the finding worth keeping. The one-line
  reorder is closed by a sibling test that probes the denylist half instead,
  confirmed failing before it and passing after.

  Writing that test found a second instance of the same shape. C6 tokenises
  every file git knows about, this repository's own tests included, so a probe
  token spelled out in the test source made the gate report the TEST FILE —
  and the vacuity guard, which asked only whether some FAIL appeared, was then
  satisfied by the fixture rather than by the probe. The token is assembled
  across two statements so the pair never forms, and the guard now requires
  the probe file to be named.
- **C2 read a project's own ADR numbering as dangling references.** The twelve
  migrated records are `store-ADR-NNN` now, with the mapping and the reasoning
  in their index, and the check was generalised from "a `template-` prefix" to
  "any namespace prefix" so a third set never needs the gate edited. A file
  PATH naming another repository's record is no longer read as a citation either — the
  migrated records cite `ml-service-template` files by name.

- **`rag-assistant` now clears charter criterion C1**, the precondition the
  technical plan puts on Phase 4: *"must reuse ≥3 shared libraries with no
  fork."* It reused two. The third arrived as work the project needed rather
  than a line in a manifest — `abstention.py`, which decides when the assistant
  should refuse to answer.

  A RAG system with no abstention answers confidently when the evidence never
  reached its context, and on filings a fabricated figure reads exactly like a
  correct one. Where to put that cut-off is a question about **relative cost**,
  which is what `ml_core.decision` already answers for the tabular track:
  `choose_threshold` searches the observed probabilities rather than a grid,
  because the cost function is piecewise constant. Writing a second answer here
  is the fork C1 exists to detect, and it would have lost that detail silently.

  The costs are recorded as a decision — a wrong answer costs eight times a
  refusal, in analyst-hours, with the reasoning beside the numbers — because
  `ErrorCosts` refuses two zero costs and a 1:1 ratio is the same evasion
  spelled differently.

  **The confidence signal is measured, not assumed.** There are no retrieval
  scores to work with (the retriever interface returns indices, deliberately),
  so confidence is how far the candidate retriever and the lexical baseline
  agree — computable at serving time, needing no labels. Whether that separates
  the queries whose answer was retrieved from those whose was not is a
  hypothesis, so the policy reports it: **+0.185 at k=3 and +0.215 at k=5** over
  the repository's own 1,270-section corpus and 30-question gold set, and
  **no separation** on a 12-document fixture where the retriever hits 11 of 12.
  A policy fitted on a signal that does not separate is marked unusable and
  `should_answer` raises rather than falling back to answering everything.

- **The Phase 4 precondition is now a ratchet, not a sentence.** Nothing could
  enforce it while the project was mid-phase — a gate that goes red for
  legitimately unfinished work gets disabled rather than satisfied, which is
  why `check_library_reuse.py` reported the count without failing on it. With
  the floor reached, the question a gate answers changes from "has it got there
  yet" to "has it dropped back", and the second is answerable on every commit.
  `MINIMUM_REUSE` records it, `check_thresholds.py` watches the floor itself,
  and both ways of losing it — dropping the declaration, deleting the module
  that imports it — were watched failing.

- **Expanding-window backtesting** for `demand-forecast`, with a gap sized to
  the longest feature lag — training up to the first test hour leaks through
  the lag window even when the timestamps look disjoint.
- **`random_split_folds`, kept deliberately as a counter-example.** Same model,
  same data, both splitters: the shuffled split scores MAE 6.26 against the
  honest 13.18, so a random split makes this model look **52% better than it
  is**. Measured in `test_backtest.py` rather than asserted in prose, and
  guarded by a test that nothing in the pipeline imports it.
- **Backward-only feature engineering**: lags, shifted rolling windows and
  calendar terms, computed within each zone. The decisive test mutates the
  future of the series and asserts every earlier feature row is unchanged — a
  lookahead bug survives shape checks, dtype checks and reading the code.
- **Model training with a baseline gate and conformal intervals.** Seasonal
  naive (last week, same hour) is the reference an MAE is meaningless without.
  On synthetic seasonal data the model reports skill **+12.2%** over that
  baseline with **88.7% empirical coverage against 90% nominal**. A model that
  loses to repeating last week fails `beats_baseline()` rather than being
  reported as a metric to interpret generously.
- **The backtest now runs on the real NYC TLC feed**: 151,904 hourly rows,
  140 zones with enough history to model, three one-week folds. **Skill +55.8%
  over seasonal naive, coverage 89.8% against 90% nominal.**
- **Panel-aware splitting** (`expanding_window_folds_by_time`). Cutting a
  261-zone frame by row position trains on some zones and tests on others — a
  cross-entity split wearing the shape of a temporal one, with every fold still
  well-formed. The positional splitter is kept for single series and its
  failure on panel data is a test.

- **Great Expectations at the warehouse boundary** (ADR-004), as a complement
  to the contracts at the function boundary rather than a second copy of them.
  Every expectation checks something a per-frame contract structurally cannot:
  duplicate `(zone, hour)` rows from a repeated append, timestamps outside the
  feed's own epoch, implausible counts, unknown zones. Each carries a prose
  `meta.reason`, because the audience ADR-004 names for Data Docs will never
  read the Python. Optional extra, matching its `demonstrated` tier.
- **KFP v2 training pipeline** (`ingest → validate → backtest → gate`),
  authored with the SDK that ADR-004 admits — Kubeflow the platform is Rejected
  there. Components call the project's tested functions rather than restating
  them, and every step pins one built image instead of installing packages at
  run time, which would make each run depend on what the index served that
  minute. **Compilation is verified; execution is not** — that needs a managed
  backend and is Phase 2. The tests assert the specification and claim nothing
  about a run.
- **One correlated trace across ingest, validation and training.** ADR-004
  justifies OpenTelemetry with an artifact rather than a principle, so the unit
  of value here is the TRACE, not the span: three stages emitting three
  unrelated traces produce the same log lines and answer none of the questions
  a trace exists for. Verified by exporting a real run and reading it back from
  Jaeger's API — 4 spans, one trace id, carrying `skill` and `coverage` as
  attributes. An absent collector disables tracing and says so, rather than
  raising or going quietly no-op.
- **Phase 2 groundwork, creating zero cloud resources.** Terraform for GKE and
  EKS from one shared module, both `terraform validate` green, with partial
  backends and a separate state bucket per environment — a prefix typo inside a
  shared bucket reads another environment's state, and the first symptom is a
  plan proposing to destroy production.
- **The multi-cloud difference is measured, not asserted.**
  `scripts/measure_cloud_surface.py` reports **68% of Terraform is
  cloud-specific** (183 of 268 significant lines) against a 75% ceiling, and
  the check is a CI gate. The number is uncomfortable and that is its value: at
  this scale "one definition, two clouds" means two adapters agreeing on an
  interface, not a large shared body.
- **GitOps matrix**: a base plus six overlays (2 clouds x 3 environments),
  each building to Deployment, Service, PodDisruptionBudget and three
  NetworkPolicies, driven by ONE ArgoCD ApplicationSet generator rather than
  six hand-written Applications — six drift the moment someone edits five.
  Production does not auto-sync and nothing prunes: with prod auto-syncing the
  promotion gate stops being a gate, and prune deletes what a human added
  during an incident at the moment it is load-bearing.
- **External Secrets**, split on the same boundary as the Terraform adapters:
  the `ExternalSecret` is shared because what a pod needs is a Secret with
  known keys, and the `SecretStore` is per-overlay because where the values
  come from is a property of the cloud. Both authenticate by identity —
  Workload Identity and IRSA — so neither carries a bootstrap key that never
  rotates. A test asserts no committed credential lacks the
  `local-only-not-a-secret` marker, which fails a real password even inside
  `platform/local/`; excluding that path was the first thing I reached for and
  would have allowed exactly the leak the check exists to prevent.
- **Default-deny NetworkPolicies**, with the DNS egress that a default-deny
  namespace breaks first and that is suspected last.
- **What local validation cannot prove, tested as such**: kind runs kindnet,
  which accepts a NetworkPolicy and enforces nothing. Applying one here and
  watching it succeed is the most convincing false evidence available, because
  every command reports success — so a test asserts the CNI is still kindnet
  and will fail when that stops being true.
- **A bare-environment guard** for the gates. Three times this session CI went
  red on a working copy where everything was green, and every time the cause was
  the same shape: state my machine had and a runner does not — gitignored
  provider binaries, unstaged new directories, a sibling checkout. The test
  builds a sandbox from `git ls-files` alone, with no siblings, and runs the
  gates there. Confirmed to catch the sibling-checkout case by reverting that
  fix and watching it fail.
- **Adopted ml-service-template v0.26.0**, which closes at the ROOT the trap
  four previous releases had been pinning around: the frozen `v1.x` audit
  snapshots are renamed `archive/v1.x`, and copier filters tags through a
  PEP 440 check before sorting, so a non-version tag is invisible to
  resolution. Measured against the current template, pinned and unpinned now
  agree — 627 files, `_commit: v0.26.0` either way. Both upstream defects this
  repository reported are fixed there: the `scaffold-update` WORKFLOW is pinned
  and the pre-rename repository name is gone from every generated file.
- **`libs/llm-core`: retrieval evaluation with a baseline that has to be
  beaten.** A RAG system is usually judged by reading a few answers and finding
  them plausible, which measures the reader rather than the retriever — an
  answer built from documents that lack the fact reads exactly like one built
  from documents that have it. Recall@k gates and MRR informs, because a
  retriever that ranks the answer third still answers and one that misses it
  cannot. `lexical_overlap_baseline` is the seasonal-naive of retrieval: word
  counting, deterministic, and genuinely hard to beat on short factual text. A
  vector store that does not clear it by a margin is an index, a latency and a
  bill bought for a difference inside the noise.
- **`projects/rag-assistant`: sentence-aligned chunking.** Chunking is usually
  treated as a parameter; it is where retrieval quality is decided. A window
  that cuts "revenue of 4.2 billion dollars" leaves one half stating a quantity
  with no unit and the other a unit with no subject — both retrieve plausibly
  and answer nothing, and every metric stays green except recall against a
  known answer. The sentence boundary deliberately does not split on `.` alone,
  because `4.2 billion` and `U.S. GAAP` are single sentences. Overlap is by
  whole sentences, since overlapping by characters reintroduces the mid-sentence
  cut the split just avoided.
- **The retrieval gate, closed end to end.** `evaluate_corpus` chunks a
  corpus once and scores the candidate and the baseline over the SAME chunks —
  re-chunking between them would compare two retrievers over two corpora and
  blame the retriever. The gold set records answers as TEXT, not chunk
  indices, because indices move the moment anyone tunes the chunker, which is
  the main reason to run this. An answer found in no chunk is refused (the
  chunker split a fact) and so is one found in several (overlap made the label
  ambiguous): both would produce a number measuring the fixture.
- **A density check** — distinct hours against the hours the span implies —
  kept outside the suite because an expectation suite has no vocabulary for a
  shape the rows collectively have.
- **`delete_before`** on the lakehouse, for the case fixing an ingest cannot
  reach: rows already stored outside every ingested month. Reversible, since
  Iceberg records it as a snapshot — which is why EXPIRY is the STOP operation
  and this is not.

QA-4 round seven audited `35ffdec` and reported **1 P0, 6 P2, 4 P3**. Its
verdict names the pattern better than any of the individual entries: *the
audited claims are trustworthy about what the gates check and not yet
trustworthy about what they cover* — four hand-maintained scope lists and one
coverage measurement quietly described more ground than they held. All eleven
are closed below; each fix was watched failing before and passing after.

- **[P0] Documentation counted as implementation, for the third time.**
  `check_technology_inventory.py` excluded `docs/`, three named files and any
  `README.md` from its content search — a list of PLACES, where the rule is
  about a KIND of file. A sentence in `libs/NOTES.md` flipped `feast` from ⬜
  to ✅, falsifying the legend the generator prints in its own output. The
  earlier two instances were closed by adding another entry to that list;
  markdown is now excluded by SUFFIX wherever it lives, `_has_substance` uses
  the same rule (measured: byte-identical output today), and
  `tests/test_technology_inventory.py` exists — the script had no test file at
  all, reachable only through a generic sweep that runs it and checks the exit
  code.
- **[P2] The fork detector could not see a conditional definition.**
  `reimplemented()` read `tree.body`, which expresses "not nested in anything"
  rather than the "module level, never a method" its docstring claims — so
  `try: from llm_core import x / except ImportError: def x(...)`, the canonical
  vendoring shape, was invisible while the import kept the reuse count honest.
  Now it recurses through control flow and never through a `def` or a `class`,
  and a closure is still not a fork. Found while verifying that fix: two files
  forking the same symbol collapsed to one finding, because the result was
  keyed by symbol name.
- **[P2] `make verify` claimed to be "what CI runs" and ran 10 of 26**, with
  `mypy libs/` where CI checks `libs/ scripts/ projects/…` — the narrow type
  gate this repository had already found, fixed in the workflow and left in the
  Makefile, so the local command reported green on exactly the code the fix was
  about. `verify` is now a superset and `tests/test_verify_parity.py` fails
  when it stops being one, with the four CI-only commands listed and reasoned.
- **[P2] A whole project was outside the type gate.**
  `projects/rag-assistant/src/` — five modules including the `ingest.py` whose
  silent row-dropping was the data-loss defect fixed in `ac852ab` — was checked
  by nothing. It passes strict, so this was an omission rather than debt; the
  defect is that nothing would have said so. The scope is now asserted against
  every first-party source root derived from the filesystem.
- **[P2] A lowered threshold went invisible after one more commit.**
  `check_thresholds.py` compared against `HEAD~1`, whose reasoning holds only
  for a single-commit change. CI was largely protected by the merge-commit
  checkout; the LOCAL invocation — the one someone runs before pushing — gave a
  confident all-clear on any branch with two commits. Now the merge base with
  the default branch, falling back to the parent on `main` itself, where the
  merge base IS `HEAD` and would restore the original defect.
- **[P2] C6's link scan read 233 files of 1312.** Markdown only, `projects/`
  excluded, so a link to a non-public repository passed in any `.py`, any YAML
  and anywhere under `projects/`. Widening it surfaced 21 links to third-party
  repositories and none was a leak, which exposed the second half: the check
  read "not one of OUR public repos" as "private". The OWNER is what makes a
  link a privacy question, and that only looked correct while the scan could
  not see outside markdown.
- **[P2] The coverage gate measured its own test suite** — 397 of 846
  statements at 99.26%, lifting the published figure by ~2.3 points. Excluded;
  the floors are unchanged and the honest figures clear them. And L2's ">=80%
  branches" had no command that could fail on branches alone:
  `--cov-fail-under` tests one combined figure. `scripts/check_branch_coverage.py`
  now reads the two rates separately, and fails when branch data is absent
  rather than reporting a missing number as a passing one.
- **[P3] The auditor's brief carried a status figure** three paragraphs after
  declaring it carries none, and it was stale. Deleted.
- **[P3] CI labelled a step "L3"**, which names both a pending public-API gate
  in `quality-gates.md` and the cluster tier of the L1–L4 evidence taxonomy.
  The scripts-coverage ratchet is now **P12**, a platform gate, declared as a
  row rather than living only in a step name.
- **[P3] The type-gate test misattributed `hide_error_codes`** as "mypy failed
  to run", sending a reader to debug a broken install instead of to the config
  line. It now distinguishes "no diagnostics" from "diagnostics whose codes
  cannot be parsed".
- **[P3] C6 printed `ok` directly above its own `FAIL`**, with a count from one
  scan and a label naming the other.

Four more, found while closing those:

- **bandit flagged the new coverage gate's XML parsing** (B314, entity
  expansion). Answered with `defusedxml`, which is the remedy the tool names,
  rather than a `# nosec` — the input is a file our own coverage step writes,
  so the practical risk is small, and adding a suppression for a small risk is
  how a scanner becomes decorative. `.security-baselines/` holds zero
  suppressions on purpose. The type gate then insisted the parsed root is
  optional, which was also right: an empty report would have raised
  `AttributeError`, and a gate that dies is indistinguishable from one that was
  never wired.

- **Widening C6 past `*.md` put binary files in its path**, and the first one
  crashed the whole checker with a `UnicodeDecodeError` — nine checks reported
  nothing because the tenth met a PNG. The link scan now decodes lossily, the
  way `_check_forbidden_names` has read the same set since it was written. It
  passed locally and failed on the runner, where one untracked file differed:
  the tree that broke it was not the tree it was written on.

- **`check_thresholds.py` anchored two of its patterns on a step label**, so
  renaming CI's "L3" step to P12 — the fix for the P3 above — broke both
  thresholds at once. The gate reported it correctly (*a threshold that cannot
  be found cannot be watched*), which is the only reason it did not land
  silently. Both now anchor on `--cov=libs` and `--cov=scripts`: what is
  measured, rather than prose anyone may reword.
- **A comment naming an enforcing test that has never existed.** `THRESHOLDS`
  said adding a gate means adding its number "enforced by
  `test_every_gated_number_is_watched`". There is no such test. Same defect as
  the `check_library_reuse.py` docstring found in round five — a promise of
  enforcement is a gate that cannot fail, one layer earlier. Corrected to state
  what is actually enforced, and the two new coverage floors are now watched.

- **C7's marker cleared the gate with nothing behind it.** The
  independent-audit marker is one editable line in `AGENTS.md`, and editing it
  resets the check. Round six was audited and the marker moved to `5c02411` —
  clearing C7 — while `ops/audit.jsonl` received no entry. Nobody forged
  anything; the point is that for a week nothing could have told the
  difference. The round is now recorded, marked as backfilled and dated
  honestly, and C7 requires an `independent-audit` entry in the hash-chained
  trail naming the same commit. `RUNBOOK.md`'s recording step named
  `--action audit --outcome completed`, which no round has ever used and which
  the gate does not accept; corrected, along with a stale example output and a
  claim that C7 "fails right now".
- **Two quality-gate rows published thresholds their CI steps cannot
  enforce.** P7 (Checkov) runs with `soft_fail: true` and P8 (Kubescape) with
  `continue-on-error: true`, while the table gave both a blocking threshold —
  the third option `quality-gates.md` says does not exist, in the document that
  says it. Marked ⚠️ advisory with the reason rather than deleted, so the gap
  stays visible; promoting them is a triage commit against a standing backlog,
  not a flag flip.
- **A residue check that watched three of five files and failed on clean
  work.** `test_the_probes_left_no_residue` ran `git diff --name-only` over
  `VERSION`, `pyproject.toml` and `llms.txt`. A dirty working tree is the
  normal state of anyone editing `pyproject.toml`, so it reported "a probe was
  not restored" for edits the probes never touched, and it watched three of the
  five locations the version gate actually compares — a leak into `CHANGELOG.md`
  or `docs/architecture/technical-plan.md` passed silently, confirmed by
  disabling `_mutated`'s restore and watching both files stay at 0.0.9 while the
  check said nothing. Replaced by a module-scoped autouse fixture that reads
  every location the gate reports through `--show` and compares bytes at
  teardown, so it distinguishes a leak from work in progress on a dirty tree, a
  detached HEAD, or outside a git checkout. The named test remains and asserts
  the fixture is wired: an autouse fixture is invisible at the call site, so
  dropping `autouse=True` would remove the guarantee with every test still
  passing.
- **A probe that measured the shape of the history, not the thing it named.**
  `test_a_marker_naming_a_lightweight_tag_still_measures` tagged `HEAD~1` and
  expected the drift counter to return exactly 1 — true on a linear local
  branch, false on a runner, where `actions/checkout` builds a merge commit
  whose first parent is the base. It passed on a one-commit pull request and
  went red on the next, reporting a fault in the counter that was not there.
  Asserted as an equivalence instead: a lightweight tag must measure exactly
  what the SHA it points at measures. Verified against a locally reconstructed
  merge commit, the shape that broke it.
- **`actions/setup-python` was listed twice** in `pr-evidence-check.yml`, the
  first without the `with:` block that pins `.python-version` — a stray line
  from the commit that pinned eight actions to commit SHAs.

- **`strict = true` was declared in a place mypy does not honour as written,
  and three documents described the result.** It sat in a
  `[[tool.mypy.overrides]]` section naming the five shared libraries, under a
  comment saying `libs/` was checked strictly "while `projects/` is allowed to
  be looser". mypy hoists `strict` out of a per-module section, applies it
  globally, and reports that section's module list as unused. Measured with a
  controlled experiment — known-bad code in a module the list does not name
  drew all six strict diagnostics; deleting that one section dropped it to the
  two options set globally; identical under mypy 1.20.2 and 2.3.1. Nothing got
  weaker: the tree already passed strict everywhere, which is exactly why the
  misdeclaration was invisible for the repository's whole history.

  Two consequences worth stating plainly. The entry below claiming
  **"`feature_defs` was missing from the mypy strict allow-list"** recorded a
  fix that changed nothing — the list was never what was in force — and
  `tests/test_type_gate_scope.py` had been asserting that a name appeared in
  that list, i.e. checking a declaration rather than a behaviour, which is the
  same family of defect it was written to catch. The option now sits at
  `[tool.mypy]`, the test asserts no override may re-narrow it, and
  `tests/test_type_gate_enforces_its_config.py` runs known-bad code through the
  real config so every option the gate claims is watched failing before it is
  trusted. Found while reviewing the mypy 1.x -> 2.x bump, where the question
  was not whether the repository still passes but whether the checker still
  *reports* — a checker gone quieter is indistinguishable from a clean build.

Three defects that synthetic single-series data could not expose, found within
minutes of pointing the backtest at the real feed:

- **The conformal calibration slice selected one zone, not recent hours.**
  Holding out the last N row positions of a panel sorted by `(zone, hour)`
  takes the tail of the LAST zone, so the residual quantile came from a single
  zone's scale and was applied to all of them. Empirical coverage was **53.8%
  against a 90% target**; cutting the window on time instead gives 89.8%.
- **The baseline was silently `nan`.** Forward-filling `seasonal_naive` bled
  one zone's last value into the next zone's first rows and left nan at the
  start, which propagated into the aggregate. The report printed
  `baseline nan`, `skill +nan%` and `beats_baseline: False` — the comparison
  had stopped existing while every test passed.
- **Corrupt pickup timestamps reached the lakehouse.** The real 2024-01/02
  feed carries pickups stamped 2002, 2008 and 2009 — 33 rows across the two
  files. They pass every column bound, so the reject rate stayed at **0.00%**
  and no alarm could fire, yet they moved the observed start of the series
  from January 2024 to December 2002: a backtest computing its span from
  min/max saw a 21-year history containing 60 days of data. The ingest now
  bounds pickups to the month the FILE declares in its own name, counts them
  separately from ordinary cleaning, and the bound is on pickup only so a trip
  crossing midnight into the next month is kept.
- **The first warehouse timestamp expectation was circular.** It took its
  bounds from `expected_window(demand)` — the min and max of the column it was
  validating — so every value lay inside its own range and the suite passed on
  a table containing pickups stamped 2002. This is the same defect the
  independent audit found in the MCP registry gate: a threshold supplied by the
  thing it judges. Committed again, in new code, three weeks later. The floor
  is now a constant, and a test asserts it stays one.
- **Fixing the ingest did not clean the warehouse.** `write_demand(overwrite=True)`
  is scoped to the months present in the incoming data, so a full reingestion
  left 16 rows stamped 2002-2009 untouched — correct behaviour of the earlier
  data-loss fix, with a consequence worth stating rather than discovering.
- **The pipeline's quality gate was handed its own verdict.** `coverage_ok=True`
  was passed as a literal, so the calibration half of the gate could not fail
  whatever the model did. That is the THIRD time this repository has written a
  gate whose threshold comes from outside the thing it judges — the MCP
  registry, a warehouse expectation, and now this. The backtest component now
  returns both verdicts and a test fails if either becomes a constant.
- **Both regression tests were vacuous on the first attempt.** They recomputed
  the selection instead of calling the production code, so they passed with the
  defects deliberately reintroduced. `calibration_split` was extracted to be
  callable, and both tests were then confirmed failing against each bug.

- **QA-4 round eight: two published claims of enforcement that enforced
  nothing.** Both were found by an independent session, neither by a gate.

  **`Component.why_unverifiable` was required by a docstring and a CHANGELOG
  entry, and by nothing that runs.** The comment said *"Required whenever
  `verify` is None; see `test_status_components.py`"* — a file that had never
  existed — and 5 of the 7 such components lacked the field. This is a verbatim
  recurrence: `tests/test_empty_libraries_say_so.py` exists because round five
  found the same shape in `check_library_reuse.py`, and the recurrence landed
  four commits after that test was cited as precedent.

  The test now exists, and the invariant is **narrower than the docstring
  claimed**: a component that renders 🟡 must say why. Requiring it of ⬜ rows
  would demand a reason from three projects that do not exist — "why is there
  no verification command" has no content for a thing with no files — and would
  produce five ceremonial strings that teach everyone the field is boilerplate.
  Proven able to fail by stripping the reason from `serving-core`.

  **A detector regex that could not match its own text.** `_as_word` accepted a
  leading hyphen and wrapped it in `\b`, and `\b-` is unsatisfiable: a hyphen
  is not a word character. `\b--cov-fail-under\b` never matched
  `--cov-fail-under`, so `coverage` and `coverage-gate` reported NOT BUILT while
  both flags sat in `ci.yml`. **The headline understated the built count by
  two: 53 of 121 was really 55.** Anchoring is now conditional on the first and
  last character, and `ray` still does not match inside `NDArray` — the
  false-positive this function was written for.

  The gap that let it through was the test suite: it exercised the function
  with the bare word `feast` only. There is now a sweep over every `pattern:`
  detector in the committed inventory, asserting each can match its own literal
  text, which fails on the old implementation.

  **A weaker exemption list than the one it cited as its model.**
  `datasets.lock.json`'s `unfetched` section carried a reason and nothing that
  could expire it, while `test_project_contract.py` — named in its own docstring
  as the model — re-evaluates each deviation's condition. Lock version 2 pairs
  the reason with `blocked_on`, the repo-relative path whose appearance ends the
  exemption, so the condition is machine-checkable in CI with no data present.
  `load_lock` migrates v1 in memory: a format bump that forced everyone to
  re-download 263 MB to regenerate their pins would be a lockfile working
  against the reproducibility it exists for.

  Also corrected: the drift CHANGELOG entry said 34 tests where `pytest`
  collects 35. Wrong when written.

## [0.1.0] - 2026-08-07

First tagged release. Cut deliberately early, and not because the platform is
finished — Phase 1 is not complete and the technology inventory says so. It is
cut because the release path had never executed, and an untested release path
fails once, in public, on the tag that matters. Better a 0.1.0 with no
consumers.

Pre-1.0: minor versions may change contracts.

### Added

- **Charter and governance.** Eight ADRs fixing scope, monorepo topology, the
  absorption of `agent-local`, consumption of `ml-service-template`, tooling
  triage, agentic governance, edge protection and drift detection. Each carries
  rejected alternatives and observable revisit triggers.
- **Agentic surface**: 23 rules, 29 skills, 22 workflows, rendered to four tool
  surfaces (`.claude`, `.cursor`, `.codex`, `.devin`) from one canonical store —
  74 artifacts × 4 = 296 GENERATED files. The surface roots also hold
  hand-written files (`.codex/mcp.example.json`), which are not counted here.
  `.devin` is a full mirror because it cannot follow pointers, and is therefore
  drift-checked byte for byte.
- **AUTO / CONSULT / STOP** inherited in full, extended with platform-scoped
  operations: expiring lakehouse snapshots is STOP, materialising features to
  the production online store is CONSULT, bypassing GitOps with `kubectl` is
  STOP.
- **Anti-patterns**: D-01…D-38 and Q-01…Q-08 referenced from the template
  (never restated — two documents describing one thing will disagree), plus
  P-01…P-25 owned here. Six of the P-entries came from real failures in this
  repository's own construction.
- **13 active gates**, each verified to FAIL on known-bad input before being
  trusted, plus 15 declared but not yet runnable and marked ⏳ PENDING with the
  phase that delivers them. The earlier count conflated the two:
  dependency direction, agentic surface sync and integrity, documentation
  coherence, CI references, MCP registry, technology inventory, implementation
  status, audit-trail chain, lint, format, types, tests.
- **Derived documents that cannot drift**: `implementation-status.md` and
  `technology-inventory.md` are generated from the filesystem and checked in
  CI. Detectors never match documentation, because the easiest way to appear
  finished is to write about being finished.
- **`libs/ml-core`**: deterministic seeding that reports which sources it
  reached, split conformal prediction with finite-sample correction, and
  cost-based decision thresholds with the calibration they require.
- **`libs/feature-defs`**: point-in-time-correct `as_of_join`, a leakage
  detector, and `naive_join` kept deliberately so the detector can be shown to
  catch something real.
- **`libs/data-contracts`**: versioned contracts with an explicit compatibility
  rule; violations carry a column, a count and an example.
- **`projects/demand-forecast`**: NYC TLC ingestion with contract enforcement
  at the boundary, hourly demand aggregation, Iceberg tables partitioned by
  month with verified time travel, and a measured single-node scaling curve.
- **Phase 1b local stack**: kind cluster with Postgres+pgvector, MinIO, OTel
  Collector, Jaeger, Prometheus and Grafana, memory-budgeted and enforced.
  Its README lists what local validation **cannot** prove.
- **Project generator** (`copier.yml`), emitting kind-specific quality gates
  with mandatory rationale fields.
- **Dataset acquisition** with per-source licence and redistribution terms
  enforced in code; raw data never committed.
- **Supply chain**: dependabot with grouping and `versioning-strategy:
  increase`, Trivy, bandit, gitleaks, OpenSSF Scorecard, codecov.
- **`ops/audit.jsonl`**: append-only operational memory with a hash chain, so
  a modified entry is detectable rather than merely deniable.

### Fixed

Defects found in this repository's own construction, each by running something
rather than reading it:

- A mypy strict override matching **zero modules** while its CI step stayed
  green.
- A coherence filter matching absolute paths that examined **zero files** and
  passed.
- Eight documented directories absent from a clean clone, because git does not
  track empty directories.
- CI red for several commits while local was green: the workflow used
  `uv sync --all-extras` where workspace members need `--all-packages`.
- Three defects in the local stack on first run: occupied host ports,
  containers violating restricted Pod Security, and a resource quota that made
  rolling updates impossible.
- A vendored script fixed in one copy but not the other, caught by the
  template's own drift guard.
- **The type gate did not check the gates.** `mypy` ran against `libs/` only,
  while `scripts/` — which enforces every other claim here — carried 26 errors
  behind a green step. Scope widened to `libs/ scripts/ projects/*/src/`, and
  the widened gate was verified to fail on injected bad input.
- **`feature_defs` was missing from the mypy strict allow-list** while all four
  siblings were present. It owns the point-in-time join and the leakage
  detector, so it was the library where loose checking mattered most. An
  allow-list is silent about what is absent from it; `tests/test_type_gate_scope.py`
  now derives the list from the filesystem and fails on omission.
- **No library shipped a `py.typed` marker.** Internal strictness reached no
  consumer: mypy skipped `data_contracts` entirely inside `demand-forecast` and
  reported it only as a note. Markers added for all five libraries, guarded by
  a test.

### Changed

- **A yellow marker in the implementation status now has to say why it is
  yellow.** `Component.why_unverifiable` is required whenever a component has
  no verify command. Two rows — the local validation stack, whose only
  candidate command reads host state and so returns different markers from the
  same commit, and `libs/serving-core`, deliberately empty with one serving
  consumer — carried their reasons as comments in the generator, where no
  reader of the generated document could see them. Both markers were correct;
  the document could not distinguish either from an oversight.

  One of those comments also cited "ADR-001 rule 3" for a claim that ADR does
  not make — rule 3 is *"`libs/` packages may depend on each other,
  acyclically"*. The citation is dropped rather than corrected to another
  number, because no ADR states the premature-abstraction rule that three other
  places also attribute to it.

- Corrections are **appended, never applied in place**. A wrong claim in an
  accepted ADR stays, with a dated `## Correction` section — the error is
  usually more instructive than the number.

### Fixed — independent audit remediation

QA-4 ran in a separate session against `f580c4f` (ADR-005 rule B) and a cloud
multi-agent review against `859f5d7`. Findings and evidence:
`docs/governance/QA-4-independent-audit.md`. The two implementations flagged as
most suspicious — conformal prediction and point-in-time correctness — were
verified CORRECT under randomised adversarial testing. What failed was the
documents.

- **`write_demand(overwrite=True)` deleted the entire table.** `Table.overwrite`
  defaults to `AlwaysTrue()`, so a backfill of one month against a year of
  history destroyed the other eleven and returned a snapshot id as if it had
  worked. The predicate is now scoped to the months present, non-contiguous
  months do not delete the gap, and an empty frame is refused rather than
  selecting everything. The covering test had written one row twice and
  asserted one row remained — which holds equally under total deletion — and
  was marked `integration`, so it never ran in CI.
- **CI had never executed 7 of its 18 steps.** One red gate aborted the job
  under `bash -e`; the steps below it were `skipped`, not green. Each gate now
  runs independently of the others while still requiring setup to succeed.
- **The coverage gate that ran was not the one declared.** L1/L2 declare ≥90%
  for `libs/`; CI measured `libs + scripts + projects` against the same number.
  Split into two gates: `libs/` at 90 (93.45%) and `scripts/` at a 74 ratchet
  floor. No threshold was lowered — `scripts/` never had one, which is how two
  of its files reached 0%.
- **The MCP gate read its own strictness from the file it validates.** One
  commit could add an unassessed server and delete the check that would catch
  it. The required fields and valid modes now live in the script; a registry
  that disagrees fails.
- **The audit trail was silently truncatable.** The hash chain detects editing;
  nothing committed to its length, so deleting entries left a valid chain.
  `--verify` now also compares against `git show HEAD:ops/audit.jsonl`.
- **C6 could not catch a bare private name in prose** — the only form that fits
  in a sentence. It scanned 105 of 331 markdown files and matched URLs only.
  Now every git-tracked file is tokenised against a committed SHA-256 denylist,
  so the forbidden name is enforced without ever being written down.
- **Four declared gate commands named scripts that were never written**, while
  C4 checked only that the row contained a backtick.
- **`feast` was reported implemented on a directory name.** With `pandera`,
  `contract-testing` and `model-cards`, four false ✅ removed: 44 → 40 of 117.
  A `filled:` detector now refuses to count a document whose sections are TODO.

## Cadence note

The first independent audit ran on 2026-08-06 (`f580c4f`). Check C7 previously
treated the absence of an audit as passing, indefinitely — a gate designed to
pass, anti-pattern P-09 — and now fails once the repository has meaningful
history.

The audit's most useful result was not any single finding but the split: every
executable claim in `libs/` survived adversarial testing, and the documents
describing the system did not. The suspicion ranking written for the auditor
was wrong in both directions, which is the argument for the procedure rather
than against it.
