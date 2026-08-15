# Releasing

What a release is in this repository, what happens mechanically when a tag is
pushed, and what must be true before one is.

This document describes **this** repository. Where it states a mechanism, the
mechanism was read from the file that implements it, and the file is named. The
sibling `ml-service-template` has its own `docs/RELEASING.md` with a longer
policy shaped by a release-discipline audit it went through; that policy is not
transplanted here, because most of it governs a scaffolding surface this
repository does not have.

## What a release means when nothing has been deployed

Start here, because it changes what every later section is for.

Nothing in this repository runs anywhere. `docs/architecture/implementation-status.md`
prints **0 components at L4** — no cloud rollout has ever happened. No container
image is built by any workflow. No package is published to an index; the five
libraries under `libs/` are uv workspace members, not distributions. So a tag
here does not ship software to anybody, and pretending otherwise would make
every checklist below theatre.

What a tag actually is, concretely:

**An immutable ref a generated project can update against.** This is the one
consumer-visible function that is real today. `templates/project/` is a copier
generator, and `docs/EXPORTING.md` is the procedure; a project generated from
`--vcs-ref=vX.Y.Z` keeps its `.copier-answers.yml` and can later be brought
forward with `copier update`. Check C9 in `scripts/check_doc_coherence.py` fails
the build on any documented copier command against a versioned source that
carries no `--vcs-ref` — 14 such commands are pinned today. The `v0.1.0` tag's
own annotation says this in as many words: *"What this tag establishes is that
the release path works, and a copier ref that a generated project can update
against."*

**A bounded evidence snapshot.** A gate result is only meaningful against a
commit. A tag lets a claim — which gates were green, how many components were
done, and that L4 was still zero — be attached to a ref instead of to "main, at
some point".

**A documented commit range.** The `CHANGELOG.md` section for the version is
what a reader gets instead of reading 51 commits.

What a tag is **not**, and must not be written as: a deployment, a support
commitment, a statement that anything runs, or an assertion that a phase of the
technical plan is complete.

## What actually happens when you push a tag

`.github/workflows/release-on-tag.yml`, in full, is:

1. It triggers on `push` of any tag matching `v*`. Nothing else triggers it, and
   it declares `permissions: contents: write` — the only workflow here that can
   write to the repository.
2. It checks out with `fetch-depth: 0`.
3. It extracts the release notes with `awk`, taking the lines after
   `## [<tag without its leading v>]` and stopping at the **next level-2
   heading of any kind**. That last detail is a fix: an earlier version stopped only at the
   next `## [` version heading, so the non-version `## Cadence note` section did
   not terminate the notes and publishing `v0.1.0` would have carried every
   following section into the public release. There is no `|| true` on the awk;
   a failure there fails the release rather than producing an empty file.
4. If the extracted file is empty it fails with an error. A tag with no CHANGELOG
   section is a release nobody described, and an empty release is worse than a
   late one because it looks complete.
5. It publishes with `gh release create "$TAG" --title "$TAG" --notes-file
   release-notes.md --verify-tag`.

Three consequences worth stating plainly, because each is a place where
expectation and mechanism diverge.

**The workflow does not check CI.** It has no `needs:`, it does not query the
commit's check status, and it runs on the tag push alone. If `main` is red at
the tagged commit, the Release is published anyway. "Green before tagging" is a
human precondition — `docs/governance/qa-procedures.md` §QA-6 — not a machine
one. Nothing will stop you.

**The heading must match the tag exactly.** The workflow strips the leading `v`
and looks for `## [0.2.0]`. A tag pushed before the CHANGELOG heading is renamed
extracts nothing and fails the release, which is the correct failure but a
noisy, public one. Rename first, tag second.

**`--title` is not decoration.** Without it, `gh` publishes a release whose name
is the empty string; the web UI falls back to displaying the tag, so it looks
correct there while the API, the Atom feed and anything consuming the Releases
list receive a blank. `v0.1.0` shipped that way, which is how the flag came to
be there, and `tests/test_release_notes.py::test_the_publish_step_sets_a_title`
is the regression guard.

Nothing passes `--prerelease` or `--latest`, so GitHub's defaults apply and the
newest release becomes "Latest".

### The dry run

`tests/test_release_notes.py` exercises the extraction **using the awk script
read out of the workflow file itself**, not a copy — a copy would let the two
drift and the test would then pass while covering something else. It runs the
real CHANGELOG with `[Unreleased]` renamed to the current `VERSION`, which is
exactly what the release commit does. Run it before every tag:

```bash
uv run pytest tests/test_release_notes.py -q
```

## Where the version number lives

Four places, and only two of the links between them are gated.

| File | Holds | Checked by |
| --- | --- | --- |
| `VERSION` | `0.1.0` | `tests/test_release_notes.py` — semver shape, and that `CHANGELOG.md` has either `[Unreleased]` or a heading for it |
| `pyproject.toml` `[project].version` | `0.1.0` | `scripts/check_version_consistency.py`, in CI |
| `llms.txt` line 5 | `Version: 0.1.0` | `tests/test_llms_txt.py::test_the_version_matches_the_package` — must equal the **pyproject** version |
| `CHANGELOG.md` heading | `## [0.1.0] - 2026-08-07` | check C8, and the release workflow's extraction |

The gap is the second row: `VERSION` and `pyproject.toml` can disagree and
nothing reports it. Since `llms.txt` is gated against `pyproject.toml` and the
release workflow keys off `VERSION`, a bump applied to one and not the other
produces a release whose notes are correct and whose agent entry point states
the previous version. Change all four in one commit.

The five `libs/*/pyproject.toml` files each carry their own `version = "0.1.0"`.
Nothing checks them against anything. They are not part of the release today
because nothing publishes them; if that changes, this table grows.

## What must be green before a tag

`docs/governance/qa-procedures.md` §QA-6 states the preconditions and its STOP
points: releasing with any gate red, releasing without verified-green CI, and
any change to a production model's promotion status. Concretely, here:

**All four CI jobs on the release commit** — `Repository invariants`,
`IaC and Kubernetes security`, `Supply chain`, `Secret scan` — read from the CI
run for that commit, not inferred from a local run. Note that this is a stricter
bar than "mergeable": `scripts/setup_branch_protection.sh` requires only
`Repository invariants` and `Secret scan`, so a release commit can be merged
with the other two jobs in any state.

```bash
gh run list --commit "$(git rev-parse HEAD)" --json name,conclusion
```

**`make verify` is not a substitute.** It narrows the type gate to `mypy libs/`
where CI runs `mypy libs/ scripts/ projects/demand-forecast/src/` — and
`scripts/` is where every other gate lives, which is exactly the scope that once
carried 26 type errors behind a green step. It also omits `uv lock --check`, the
`kubectl kustomize` render of every overlay, and both coverage floors. Its
`pytest -q` does reach the test wrappers for thresholds, clock isolation, the
MCP registry, cloud surface and upstream parity, so the gap is narrower than it
looks — but it is not zero. Use it while working; use CI to decide.

**Today, one gate is red and it blocks a release.** `scripts/check_doc_coherence.py`
fails check C7: 37 commits have landed since the independent-audit marker dated
2026-08-08, against a grace of 10. C7 is not advisory and QA-6's first STOP point
is "releasing with any gate red", so **the next release requires running QA-4
first**. That is the mechanism working as designed — the audit exists because
self-review cannot find a fact its author believed, and a release is exactly when
that matters — but it is a real precondition and not a formality to be waived.

## Version policy

Semantic versioning, with the `0.y.z` allowance that `CHANGELOG.md` already
states: *"Pre-1.0: minor versions may change contracts. Every such change is
called out."* Called out means a named entry in the version's CHANGELOG section
saying what breaks and what the reader must do — the smaller number does not
reduce what a consumer is owed.

**The versioned surface is what a consumer of this repository can depend on**,
not every commit. Internal refactors that leave all of the following unchanged
are PATCH:

- The output of `templates/project/` — file list, rendered contents, default
  answers, and the `.copier-answers.yml` it writes.
- The seven requirements in `docs/PROJECT_CONTRACT.md` and the shape of the
  deviations mechanism that lets a vertical record an exemption.
- The public API of the five `libs/` packages, each of which ships `py.typed`
  and is therefore type-visible to consumers.
- The procedure in `docs/EXPORTING.md`.
- The names of `make` targets documented as entry points.
- The AUTO/CONSULT/STOP mode declared for any operation in `AGENTS.md`.
- Any quality-gate threshold in `docs/governance/quality-gates.md`. A threshold
  that rises is at least a MINOR, because a consumer's build can newly fail on
  unchanged code. One can never fall: `scripts/check_thresholds.py` enforces
  that against git history rather than against a committed list, because a list
  of expected values is another literal editable in the same commit as the
  threshold it is supposed to constrain.

**MINOR** adds to that surface backward-compatibly: a new library, a new gate, a
new ADR, a new contract requirement that generated projects already satisfy, a
new rule or skill. **A change that breaks any bullet above is a MAJOR-class
change**, and while the line is pre-1.0 it ships as a MINOR carrying the full
MAJOR obligation: an explicit breaking-changes block in the CHANGELOG section
with one entry per break mapped to a manual action, **and** a row in
`MIGRATION.md` carrying the same break from the consumer's side. Two places, on
purpose: the CHANGELOG is read by someone deciding whether to upgrade, and
`MIGRATION.md` is read by someone already halfway through it. Its table is empty
today because `v0.1.0` is the only release, and the rule is written before it is
needed rather than invented while somebody's build is red.

### What 1.0.0 is reserved for

`1.0.0` claims stability, and stability is a claim about something that runs.
Two conditions, both derived from constraints this repository has already fixed
elsewhere rather than invented here:

1. **At least one component proven at L4** — a real rollout on GKE or EKS, with
   the evidence recorded in `docs/architecture/implementation-status.md`. Every
   Partial verdict in `docs/COMPLIANCE_MAPPING.md` under PROTECT, and every
   verdict under DETECT, RESPOND and RECOVER, is capped by this single fact.
2. **The project contract stable across at least two generated verticals**, with
   no substrate change required to generate the second. `docs/ADOPTION.md` names
   that as the signal that the platform is a platform.

Both are deliberately far off: technical-plan constraint S1 defers cloud
deployment until everything else is finished, and S2 puts `ml-service-template`'s
first deployment ahead of this one. A long 0.x line is the intended state, not a
backlog.

This reservation is recorded here and is not yet ratified by an ADR. If it is
still the policy when the first cloud evidence lands, it should become one, so
that changing it costs a superseding decision rather than an edit.

## Versions and the plan's phases are two different axes

`docs/architecture/technical-plan.md` runs Phase 0 through Phase 6. It is
tempting to map one phase to one MINOR. Do not.

A **phase** completes when every one of its acceptance commands exits zero. A
**version** is cut when there is something a consumer would want to pin to.
These coincide sometimes and are not the same event. `v0.1.0` is the proof: its
annotation states it was *"cut early on purpose. Phase 1 is incomplete"* — it was
tagged to establish that the release path works and to give the generator a
resolvable ref, both of which were worth having before Phase 1 finished.

The practical rules that follow:

- Never write "Phase N complete" in a release note unless
  `docs/architecture/implementation-status.md` shows it, since that document is
  derived from the filesystem and the plan is only a statement of intent. When
  the two disagree the derived one is correct.
- A phase completing is a good reason to cut a MINOR. It is not the only reason,
  and it is not sufficient on its own.
- The `**Status**` and `**Version**` line at the top of `technical-plan.md` is
  hand-maintained and no gate checks it. It currently reads "Phase 0 in
  progress · Version: 0.1.0" while Phase 0's rows are green and Phase 1d work
  has landed. Correct it in the release commit; nothing else will.

## The procedure

The ordering matters, and it bites in one specific place: the workflow extracts
the notes from the CHANGELOG **as it exists at the tagged commit**, so every
document change lands before the tag.

1. **Run QA-4 if C7 is red.** See "What must be green" above. Record the audit
   and update the `Last independent audit:` marker in `AGENTS.md`.
2. **Write the version section.** Rename `## [Unreleased]` to
   `## [X.Y.Z] - YYYY-MM-DD` and open a fresh, empty `## [Unreleased]` above it.
   Review the entries against the actual commit range — C8 checks that the
   section exists and is non-trivial, never that it is true.
3. **Bump all four version locations** in the same commit: `VERSION`,
   `pyproject.toml`, `llms.txt`, and the plan's header line.
4. **Regenerate the derived documents**: `make sync`, which re-renders the
   agentic surfaces and rewrites the technology inventory and implementation
   status from the filesystem.
5. **Verify locally, then verify in CI.** `make verify` first because it is
   fast; then push and read the CI run for the release commit. All four jobs.
6. **Dry-run the release notes**: `uv run pytest tests/test_release_notes.py -q`.
7. **Tag, annotated, on the merged release commit.**

   ```bash
   git tag -a "v$(cat VERSION)" -m "Release v$(cat VERSION): <one line>"
   git push origin "v$(cat VERSION)"
   ```

   Annotation is convention rather than an enforced rule — nothing checks it —
   and it is worth keeping because the annotation is the only place the release's
   own framing lives at the ref itself, readable by `git tag -n20` without
   network access. `v0.1.0`'s annotation is the reason this document can quote
   what that release was for.

8. **Verify the publication**, and do not patch over it by hand:

   ```bash
   gh release view "v$(cat VERSION)"
   ```

   If the published Release looks wrong, the bug is in the workflow or in the
   CHANGELOG section. Fixing it with `gh release edit` leaves the defect in place
   for the next release and removes the evidence that it existed.

## What check C8 does and does not do

C8 in `scripts/check_doc_coherence.py` compares the CHANGELOG against the commit
range. Read it precisely, because it is easy to over-trust:

**It checks** that `CHANGELOG.md` exists, that a `## [Unreleased]` section is
present, and that the section holds at least 80 characters of content. It
tolerates an empty `[Unreleased]` in exactly two states that are legitimate: when
a `## [VERSION]` heading matching the `VERSION` file already exists — the release
commit, before its tag — and when zero commits have landed since the last tag.
Both were previously failures, which made it a gate a correct repository could
not satisfy.

**It does not check** whether any entry is accurate, whether every commit is
represented, or whether the bump level matches what changed. Its own docstring
says the check is deliberately coarse and that accuracy is QA-5's judgement step.

One thing to read carefully in its output: the passing message
`CHANGELOG [Unreleased] present, 77 commits on this branch` prints the **total**
commit count, not the unreleased range. The range `[Unreleased]` should describe
is `git rev-list --count v0.1.0..HEAD`, which is 51.

The reason C8 exists is in its docstring: this repository reached eighteen
commits with no CHANGELOG at all while already shipping a release workflow that
requires one section per version and would have failed on the first tag. Nothing
reported it, because nothing was looking.

## The inherited `/release` workflow is only partly about this repository

`agentic/workflows/release.md` is adapted from the template and only its first
three steps apply here. Steps 4 through 12 build and push images to two cloud
registries, `kubectl apply -k k8s/overlays/...`, smoke-test endpoints and roll
back — describing a deployment that has never happened, against a path
(`k8s/overlays/`) that does not exist in this repository, which uses
`platform/kubernetes/overlays/`. Step 2's `pytest --cov=src --cov-fail-under=90`
names a `src/` directory that does not exist at the root; the real gates are
`--cov=libs` at 90 and `--cov=scripts` at a 74 ratchet floor.

Treat steps 1 through 3 as current and the rest as inherited text awaiting the
cloud work. This document, not that workflow, is the release procedure for this
repository today.

## History

| Version | Tag | Date | What it was for |
| --- | --- | --- | --- |
| 0.1.0 | `v0.1.0`, annotated, at `3c9bd22` | 2026-08-07 | Platform foundations, governance, and the gates that enforce them. Cut mid-Phase-1 on purpose, to establish that the release path works and to give generated projects a resolvable ref. The missing `--title` was found by publishing it |

Fifty-one commits have landed since, accumulated in `[Unreleased]`.

This repository has exactly one tag, which means the copier hazard that
`ml-service-template` carries — frozen `v1.x` audit snapshots outranking the
active `v0.x` line, so an unpinned command silently scaffolds a months-old
snapshot — does not exist here. That safety is a property of having one tag, not
of anything this repository does, and it stops being true the moment the tag
namespace has a shape. C9 requires pins regardless.

## Related

- `docs/governance/qa-procedures.md` §QA-6 — the release procedure's authority,
  including its STOP points.
- `docs/EXPORTING.md` — what a tag is for, from the consumer's side.
- `docs/architecture/implementation-status.md` — what is actually done, derived
  rather than declared, and where L4 stays at zero.
- `docs/COMPLIANCE_MAPPING.md` — the self-assessed control posture a release
  inherits.
- `CHANGELOG.md` — the record itself, including the note explaining that it was
  backfilled at commit 18 and what that cost.
