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

### Added — C10: every markdown link to a heading names a heading that exists

- **Nothing checked anchors** (QA-4 round twelve, P3-2; R12-6). The link
  checker reads files and fails a dead one. It cannot see an anchor, so a link
  to `#no-such-heading` passed, and `RUNBOOK.md` had linked to a heading
  renamed months earlier.
- **C10 in `check_doc_coherence.py`.** It resolves every relative link that
  carries a fragment against the headings of the markdown file it names, using
  GitHub's slug: rendered text, lower-cased, punctuation dropped, repeats
  numbered. Explicit `<a id>` anchors count too. Links inside code are
  examples and are skipped. It runs offline in Fast gates, because the anchors
  are this repository's own headings and a network request would add only
  flakiness. There are 19 such links today, and all resolve.
- **Watched failing.** Round twelve's mutation B and the real `RUNBOOK.md`
  anchor each fail it. Six weakenings of the check each fail a test:
  - unregistered;
  - never failing;
  - repeated headings not numbered;
  - code not skipped;
  - explicit ids ignored;
  - emphasis kept in the slug.

  The emphasis weakening first survived: the only case used `*`, which the
  punctuation filter drops anyway. An `_emphasised_` case now pins it.
- `.agents/`, the skills directory Cursor and Codex share since #89, joins the
  generated surfaces the coherence checks skip.

### Fixed — QA-4 round twelve: two negative controls that passed with the guard broken, and a rule describing another gate

- **The workflow-bounds control recomputed what it checked** (P2-6). It
  selected unbounded jobs with its own expression instead of calling the
  contract's. With the contract weakened to a default of 60 and an unbounded
  job added, all 15 tests passed. `timeout-minutes: true` also passed: YAML
  loads it as a bool, and a bool is an int in Python. Both tests now call one
  `problem()` function. It rejects any type other than `int`, and the control
  probes the six shapes a bound can take. The audit's two mutations, and a
  revert to `isinstance`, each fail.
- **The EDGAR contact was pinned in `user_agent()` and never in the request**
  (P3-3). Replacing the header with a constant passed all 36 of the
  project's tests. A test now captures the `Request` that `fetch_filings`
  hands to `urlopen` and asserts the header on it. It runs with no network
  and no sleep.
- **Rule 23 described ml-service-template's coherence gate** (P2-7). That
  rule is rendered to every tool surface. Its C1–C7 meant the template's
  checks, so an overdue audit here (C7) read as a private-name leak. The rule
  now points at the one list in `agentic/workflows/doc-coherence.md`.
  `tests/test_doc_coherence_ids.py` checks that list against the identifiers
  the script reports, and fails any other agentic body that defines one. The
  rule's release section described the template's `releases/vX.Y.Z.md`
  flow; it now describes this repository's CHANGELOG-driven one. The
  workflow's C2 line now states C2's current scope.
- **C3, C4, C5 and C9 printed `ok` above their own `FAIL`** — the defect
  rounds seven and twelve removed from C6 and C2, one check at a time. The
  lines are now filtered once, when they are printed. The first version of
  this fix guarded inside `ok()`, and the test written for C5 caught it: C5
  reports `ok` before the loop that can fail it.
- **A C2 test from round twelve asserted the whole gate green**, so it went
  red when #87's squash made C7 fail. That breaks the rule round nine
  recorded for exactly this. It now runs `--only C2`.
- The audit brief no longer states two projects and 28 gates. It names the
  command that gives the count. `RUNBOOK.md:95` linked to a heading that was
  renamed.

### Fixed — QA-4 round twelve, P0: no tool could find a single skill, and both surface checks were green

- **Claude Code registered none of the 29 skills.** They were rendered as
  `.claude/skills/<id>.md`; Claude Code reads `.claude/skills/<id>/SKILL.md`,
  and lists a skill by its front-matter, which the pointers did not have. The
  STOP-mode `secret-breach-response` was among them. The base template renders
  this layout correctly; the port flattened it.
- **Checking the other two tools against their documentation, as the audit
  asked, found both broken the same way.** Codex discovers repository skills
  only under `.agents/skills/<id>/SKILL.md` — never `.codex/skills/` — so it
  saw none. Cursor reads skills as `<id>/SKILL.md` under `.cursor/skills/` or
  `.agents/skills/`, and commands as plain `.md`; this repository gave it flat
  `.mdc` files for both, so it saw no skill and no command.
- **Rendered where each tool looks.** The manifest's layout is now a path
  pattern per kind instead of one directory per surface, because the tools do
  not agree on shape. Cursor and Codex share `.agents/skills/`, the open Agent
  Skills directory both read, and each shared file is rendered once, naming
  both. A second copy under `.cursor/skills/` would list every skill twice in
  Cursor. Skills carry `name`, and `description` with their mode appended.
  Claude's commands carry `description`: without it Claude listed all 22 by
  their first line, the "generated — do not edit" marker. Nothing else is
  copied. `allowed-tools` stays in the canonical body, where pre-approving a
  tool is reviewed.
- **Why both checks stayed green: they compared the surfaces with the manifest,
  and the manifest was wrong.** New check V7 in `validate_agentic_surface.py`
  compares them with the tools instead. It uses a table of what Claude Code,
  Cursor and Codex read, each row citing that tool's documentation, kept
  separate from the manifest on purpose. It fails:
  - an artifact that is not where its tool looks;
  - a surface whose own layout its tool does not read, even when another
    surface's copy happens to be there;
  - missing or mismatched front-matter, and a description over 1,024
    characters;
  - a new surface that arrives with no discovery contract.

  With the shipped flat layout, V1 passes and V7 fails. That pair is pinned
  as a test.
- **Three canonical workflows had no `description`** (`/metrics`, `/qa`,
  `/tests`). They have one now. The renderer refuses to render a body without
  one, rather than publishing a command a tool would list by its first line.
- **The renderer removes files a layout left behind.** Everything under a
  layout directory is the render's. A file carrying the generated marker
  anywhere under a surface root is the render's too, which is what removed the
  flat skill files from directories no layout uses any more. `--clean` removes
  the layout directories instead of the surface roots. It had been deleting
  the committed `.codex/mcp.example.json`, which nothing renders.
- **Watched failing against mutations, not only written.** Eighteen, each
  killed:
  - five manifest regressions, re-rendered and caught by the gate CI runs —
    the flat Claude layout among them;
  - thirteen weakenings of V7, V1 and the renderer, each caught by a test.

  The first run found a survivor: V7 accepted Codex pointed at the wrong
  directory, because Cursor's copy was there. The own-layout rule is the fix.
- **Upstream, recorded and not acted on:** `ml-service-template` renders
  Cursor's skills flat under `.cursor/skills/` and Codex's under
  `.codex/skills/`, the same two defects. Changing that repository is the
  maintainer's call.

### Added — ADR-010: this repository is authoritative for the agent core, and exports it

- **The authority question ADR-002's correction left open is answered.**
  `libs/llm-core` is authoritative; `DuqueOM/agent-local` is a one-way export of
  it, produced only by the new `scripts/export_llm_core.py`. Measured first,
  because the correction's own trigger said the answer was overdue once the two
  copies diverged in behaviour — and they had: nine commits here against none
  there since 2026-08-05, eleven of twelve shared files different, four modules
  only here. The policy gate is still byte-identical in both, which made now the
  cheapest moment to pick one source of truth.
- **The exporter is an allowlist, not the package.** Twelve modules — exactly
  the set agent-local already ships. `doc_corpus` and `doc_questions` stay here
  because they enumerate this repository's documentation by path; exported,
  they would describe files agent-local does not have. That coupling is also why
  the dependency-direction test was credited with more than it guarantees: it
  sees imports, not data.
- **Citations are re-namespaced on the way out, in one pass.** `store-ADR-NNN`
  becomes bare `ADR-NNN` downstream, where those are native; a bare reference to
  one of *our* decisions becomes `platform-ADR-NNN`, because left bare it would
  resolve to agent-local's decision of the same number. One pass is
  load-bearing: two sequential substitutions map a store citation twice.
- **Provenance without a timestamp.** `core/EXPORTED_FROM.json` records the
  source commit and a SHA-256 of every file, so one commit exports
  byte-identical output and `--check` means something. The script refuses
  uncommitted source.
- `tests/test_export_llm_core.py` pins every transform against the inputs that
  are easy to get wrong, and turns ADR-010's third revisit trigger — an
  allowlisted module naming this repository's files — into a failing test
  rather than a thing to remember.
- ADR-002 gains a second dated correction: "the business-agnostic upstream" was
  inaccurate — nothing flowed from agent-local — and the revisit trigger that
  should have caught it was written without measuring.
- `llm_core/agent.py` told readers to construct an agent with `load_agent`,
  which no longer exists here. It now names `build_agent`.
- **Corrected by QA-4 round twelve** (entry below): "The script refuses
  uncommitted source" was false for the script itself, `--allow-dirty` wrote a
  real export, and "one commit exports byte-identical output" held only for one
  destination version. The "nine commits" counted every commit to the package
  since its founding; 2 touched the exported modules after the core landed.
  ADR-010 carries a dated correction.

### Fixed — the agent core cited another repository's decisions, and C2 could not see code

- **48 references in `libs/llm-core` and `projects/store-assistant` pointed at
  agent-local's ADRs by bare number.** The code was migrated from agent-local
  (ADR-002), where the bare number for *hybrid tier topology* was eleven —
  `store-ADR-011` here. This index runs 000 to 009, so every citation of an
  agent-local number above nine pointed at nothing: 26 of them. The other 22
  were worse: they **resolved, silently, to a different decision**.
  `test_controller.py` cited `ADR-009` for "the reflection note leaked into the
  verifier's evidence" — agent-local's reflection-channel decision — and it
  resolved to this repository's ADR-009, *data versioning*. `ADR-006` (tool
  capability contract) resolved to *edge protection*; `ADR-004` (cross-tier
  verification) to *tooling triage*.
- **Qualified as `store-ADR-NNN`**, the convention the store decisions README
  already defines. Classified line by line rather than by search-and-replace,
  because the same number means this repository's decision on one line and
  agent-local's on the next: 43 by exact match against agent-local's original
  source, 5 by reading lines that were rewritten after migration but still cite
  the original decision, and 12 left bare because they genuinely mean ours.
- **Why it survived: C2 scanned markdown only.** Extended to Python under
  `libs/` and `projects/`, where a comment documents a design decision.
  `scripts/` and `tests/` stay out — every reference there already resolves
  here, and tests write a deliberately nonexistent reference on purpose, to
  prove the gate can fail.
- **A namespaced reference is now checked, not just skipped.** The lookbehind
  that stopped `store-ADR-006` reading as our ADR-006 also stopped it being
  checked at all, so a store reference to a number the store never recorded
  passed. Namespaces are discovered from
  `projects/*/docs/decisions/<ns>-ADR-NNN-*.md`, so no project is named in the
  gate — the reason the generalisation was made in the first place. Only a
  *known* namespace is a claim: the first version failed on a `pre-` prefix
  in a real store ADR, which is English for "before that decision", not a
  namespace called `pre`.
- **What this cannot catch, stated rather than implied.** C2 checks that a
  number exists, not that it means what the sentence says. The 22 silent
  mis-resolutions would have passed any existence check. The protection against
  that class is the namespace prefix itself; the gate only guards its louder
  half.
- Watched failing: against the pre-fix tree the extended C2 reports 11 distinct
  dangling references in code; after, it passes and resolves 69 project-scope
  references against their own index. Three regression tests in
  `tests/test_gate_scripts.py` hold it there.
- **Corrected by QA-4 round twelve.** The count was 57, not 48: nine more
  agent-local citations lived in a YAML config and a JSONL eval set that C2
  never read. And "the gate only guards its louder half" was too generous —
  its three tests passed with two of its own halves removed. See the entry
  below.

### Fixed — QA-4 round twelve: C2's new guards could not fail, and it could not read YAML

- **Round twelve removed two halves of the C2 extension and its tests stayed
  green.** Dropping `projects/` from the code scan passed, because the only
  code probe lived under `libs/`; deleting the namespaced check from the code
  loop passed, because the only namespaced probe was markdown. Each test
  exercised the half its author had touched. The auditor also put #86's own
  defect back — bare `ADR-009` and `ADR-006` in the store tests — and C2 stayed
  green.
- **Nine citations remained, one file type over.** `config.yaml` (7) and
  `11_injection.jsonl` (2) in the store assistant still cited
  `store-ADR-006`, `store-ADR-007`, `store-ADR-011` and `store-ADR-012` by bare
  number — two resolving to the wrong decision here, the rest to nothing. Qualified. C2 now reads `.py`, `.yaml`,
  `.yml`, `.jsonl` and `.toml` under `libs/` and `projects/`.
- **A bare number in a tree migrated from agent-local is now ambiguous, not
  valid.** agent-local's records 001-012 share numbers with this repository's,
  so existence cannot tell the two apart — which is how 22 citations resolved
  to the wrong decision without failing anything, and why a bare ADR-010,
  which exists since ADR-010 landed, would have done the same. In
  `libs/llm-core` and `projects/store-assistant` only the numbers checked to
  mean ours may appear bare (001-004); any other fails and must be qualified.
- **An unknown or malformed namespace now fails.** The earlier rule skipped any
  namespace nobody had defined, so a misspelt one passed. English prefixes
  (`pre-`, `non-`) are skipped case-insensitively, because `Pre-ADR-011` opens
  a sentence in the agent core's own tests. A namespace must be lower-case and
  a number three digits; the pattern is deliberately broader than a valid
  citation so that a malformed one is seen and failed.
- **C2 printed `ok` above its own FAIL lines** — the defect round seven removed
  from C6. It now prints `ok` only when it found nothing. C3, C4, C5 and C9
  still print it unconditionally; that is recorded for a separate change.
- Each markdown file is now read once, not twice.
- **Watched failing against the auditor's mutations, not the author's.** Eleven
  mutations — M-C2a and M-C2b from the audit, plus one per new rule — each
  killed by the test written for it. The re-introduced defect now fails C2 on
  both files, naming the fix.

### Fixed — QA-4 round twelve: the exporter's guarantees were written, not enforced

- **Three of ADR-010's guarantees were false of the code that shipped with
  them.** The exporter left itself out of its clean-tree check, so an
  uncommitted edit to it was stamped with a clean commit — one commit, two
  different exports. `--allow-dirty` wrote a real export stamped `-dirty`.
  Nothing checked where the commit came from, and the first export ran from a
  branch commit a squash would orphan. Now the script counts itself as source,
  `--allow-dirty` is refused without `--check`, and a write is refused unless
  `HEAD` is an ancestor of `origin/main`. `--check` still runs anywhere.
- **The tests covered the transforms and never ran the script.** Five of the
  auditor's mutations passed all 17. One of them, dropping `re.MULTILINE`, ships
  a `core/__init__.py` that still imports `llm_core`, so it cannot be imported.
  The suite now builds a scratch git repository with the exporter and the
  twelve modules and runs the real script against it. It imports the export
  with `llm_core` blocked and recomputes every provenance hash. It also checks
  that `--check` passes on a fresh export and reports drift after a one-byte
  edit, and that a stray module, uncommitted source, an uncommitted exporter,
  `--allow-dirty` alone, a commit off `main` and an unknown `origin/main` are
  each refused.
- **The boundary test saw one way of naming a host file out of six.** It
  matched a quoted string starting `docs/` and missed the other forms:
  `Path("docs") / ...`, concatenation, f-strings, a bare `QUICK_START.md` and a
  backtick-quoted path. It now walks every string literal in the exported
  modules. It flags a `docs` path component or the name of a document at this
  repository's root or in `docs/`. Its first draft also flagged the word "docs"
  in prose, in two modules, so prose negatives are now pinned too.
- **Watched failing against the auditor's mutations, not the author's.** Eleven
  mutations, each killed: E1-E5 from the audit, the three new guards, and three
  ways to weaken the boundary detector. The first run found a survivor: no
  fixture named the `docs` directory alone. That fixture was then added.
- ADR-010 gains a dated correction. It gives the method for its commit count,
  and it corrects §5, §6 and §7.

### Fixed — QA-4 round twelve: the link check promised a scheduled sweep it did not have

- `docs-quality.yml` said "the scheduled run below is the one that sweeps
  everything", and it had no `schedule:`. The full sweep ran only when a push to
  `main` touched a markdown file, so external link rot was never looked for on
  its own. It now also runs weekly (Mondays 06:00 UTC, the template's cadence)
  and on manual dispatch. A change to the workflow or to the link-check config
  now triggers it too.
- The step now says what it does not check: anchors. The audit pointed a link
  at a heading that does not exist and the lane stayed green. It also found one
  real dead anchor, `RUNBOOK.md:95`, which is fixed separately with the other
  findings outside this change.

### Fixed — the link checker was configured but never run, and it had 17 dead links to find

- **`.github/markdown-link-check.json` has existed since August and nothing
  ever invoked it.** `tests/test_governance_files.py` asserts the config parses
  and that every ignore pattern carries an argued comment — it does, and it
  passes — so `implementation-status.md` rendered "Repository governance
  (CODEOWNERS, PR template, **link check**)" as ✅ at L1. What was proven is
  that a configuration file is valid configuration. **No link had ever been
  checked.** The same failure this repository has already recorded twice: "a
  mypy override matching zero modules, and a coherence filter examining zero
  files, both stayed green."
- **`docs-quality.yml` asserted the capability in its own header** — "A broken
  link or a malformed table in an ADR is a defect in the thing the ADR exists
  to be" — while running markdownlint only.
- **Wired it**, reusing the config that was already written and the same
  action at the same commit pin as `ml-service-template`'s link-check lane
  (ADR-003: upstream owns what it already solved). Diff-scoped on pull
  requests, full sweep on push to `main`, so third-party flakiness does not
  become this repository's red build.
- **It failed on first run, against real content: 17 dead links**, one in each
  of `agentic/rules/10` through `25`. Every one pointed at
  `ml-service-template/blob/main/docs/decisions/ADR-003-service-template-consumption.md`
  → **404**. That document is *this repository's* ADR-003; the template's
  ADR-003 is `ADR-003-feast-integration-pattern.md`, an unrelated decision. The
  two numbering namespaces had been conflated, and the link was labelled
  `template-ADR-003`.
- **Why it survived both existing gates, which is the part worth keeping.**
  Check C2 resolves ADR *identifiers* against the template's index, and
  `template-ADR-003` resolves — the template does have an ADR-003. Nothing
  validated that the *URL* resolved. The defect lived in the gap between a
  gate that checks names and a gate that checks addresses, and only the second
  kind finds it.
- Corrected to `[ADR-003](../../docs/decisions/ADR-003-service-template-consumption.md)`,
  the convention already used correctly by one file in the same directory, and
  propagated to the four tool surfaces by `sync_agentic_adapters.py`.
- **Corrected by QA-4 round twelve** (entry above): the workflow's own comment
  promised a scheduled sweep that did not exist, and the check never looked at
  anchors — neither of which this entry said.

### Changed — `agent-local` stays public; ADR-002's archival is reversed

- **[ADR-002](docs/decisions/ADR-002-absorbing-agent-local.md) carried a false
  claim and now carries a dated correction.** Its § Disposition said the source
  repository was "archived on GitHub — read-only with a banner". It was never
  archived, and `DuqueOM/agent-local` is public today. Under
  [ADR-005](docs/decisions/ADR-005-agentic-governance.md) rule H that made the
  ADR itself a defect while every line of code it governs was correct — which
  is exactly the class of failure rule H exists to name.
- **The decision it reverses was never argued.** The alternatives table
  evaluated "keep both repositories" exactly once, in the form *publish
  `llm-core` to a registry* — a packaging question. Whether a business-agnostic
  agent core serves a reader that this platform's single governed use does not
  is a scope question, and it was never asked. Absorbing the code and retiring
  the repository were bundled as one decision; only the first had reasoning
  behind it.
- **The migration itself stands** and the correction says so explicitly: the 31
  commits on `archive/agent-local`, the `core/` → `libs/llm-core/` placement,
  the `usecases/tienda/` → `projects/store-assistant/` move and the
  renumbering all happened as written. Only the disposition changed.
- **Authority between the two is deliberately left open.** ADR-003 fixed the
  analogous question for `ml-service-template` in one line — the template wins
  for service-level concerns — and no equivalent line exists for the agent
  core. Deciding it inside a correction, without its own alternatives and
  revisit triggers, would repeat the failure the correction is about. It needs
  its own ADR.
- **A second, smaller falsehood in the same document**: § Related points at
  `docs/architecture/adr-migration-map.md`, "written during the migration".
  That file does not exist and nothing replaced it at that path. The mapping
  shipped as the identifier itself — record `006` became `store-ADR-006` —
  documented in `projects/store-assistant/docs/decisions/README.md`. The
  mapping is real; only its address was wrong.
- Three revisit triggers added, all observable rather than dispositional:
  behavioural divergence between `libs/llm-core/` and `agent-local`'s `core/`;
  a consumer of `agent-local` that is not a human reading it; twelve months
  without a commit there.

### Changed — the invariants lane is split, and the status document stops calling a decision a constraint

- **`Repository invariants` was one job with 39 steps, and it measured 1h 2m
  48s on a two-file documentation change.** The 25 fast gates — lint, types,
  coherence, action pins, inventory checks — completed in roughly the first
  four minutes and then waited on a test suite none of them depend on. With
  `strict: true` on `main`, every time `main` moves the whole hour is paid
  again. Split into **`Fast gates`** (bounded at 15 min) and **`Tests and
  coverage`** (bounded at 75, unchanged, because nothing was removed from that
  half and a tighter bound would need re-measuring).
- **`Repository invariants` survives as an aggregator, and keeps its name.**
  That string is a required status check on `main`; renaming it would mean
  editing branch protection, which `AGENTS.md` classes as STOP and which needs
  a PR amending `docs/governance/branch-protection.md`. Splitting a lane for
  faster feedback does not need that, so it does not take it. The job runs
  `if: always()` and asserts both halves succeeded by name, rather than relying
  on bare `needs` — a skipped required check reads differently from a failed
  one in the merge box, and this one says which half broke.
- **`docs/architecture/implementation-status.md` claimed CI *cannot* reach
  L3.** It read: "CI has no cluster and no cloud — so no row here can ever
  display L3 or L4, whatever anyone believes about it." That states a choice as
  a law of nature, and `ml-service-template` — this repository's own upstream —
  disproves it: `golden-path.yml`, `golden-path-extended.yml` and
  `kyverno-smoke.yml` each stand up `helm/kind-action` on a hosted runner and
  reach L3 there.
- **The decision itself was already recorded and is unchanged.**
  `docs/governance/upstream-parity.yaml` rejects all three of those lanes,
  because the equivalent here is `make local-serve` plus `tests/local` and a
  cluster smoke belongs to Phase 2. That reasoning never needed the stronger
  claim. The document now says no row displays L3 **because no lane provisions
  a cluster, by decision** — revisitable at Phase 2, and pointing at the ledger
  that holds the decision. L4 stays constrained by the four ordering rules, and
  stays printed at zero.

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

- **"Every CI job carries `timeout-minutes`" stopped being true a week after
  it was written.** The auto-merge workflow arrived with no bound, which is not
  a slow build: GitHub cancels a job after six hours, so a wedged step holds a
  runner that long and the log ends without saying why.

  The job is bounded at five minutes — two API calls, no checkout — and
  `tests/test_workflow_bounds.py` now reads every workflow as data and fails on
  any job without a bound, or with one outside the range GitHub can apply. The
  previous round bounded eight jobs by hand and wrote the claim down; nothing
  kept it true, which is the difference between a convention and a gate.

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
