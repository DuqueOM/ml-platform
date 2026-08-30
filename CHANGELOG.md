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

### Added

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

### Fixed

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
