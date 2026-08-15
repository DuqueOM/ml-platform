# Migrating between versions

What changes for you when this platform's version number moves, and what you
have to do about it.

Read [`docs/RELEASING.md`](docs/RELEASING.md) for what a release *is* here and
how one is cut. This file is the other side of that: the consumer's side, where
a version number turns into work.

## The state today, stated first because it changes how you read the rest

**There is exactly one release, and therefore no version-to-version migration
to describe.** `VERSION` reads `0.1.0`, `v0.1.0` is the only tag, and the
commits since it are accumulating under `## [Unreleased]` in
[`CHANGELOG.md`](CHANGELOG.md). The table at the bottom of this file has no
rows, and that is a fact about this repository rather than an omission in the
document.

What this file does today, then, is state the guarantees that hold **from the
first release onward**, so that the first release which breaks one has
somewhere to say so — written before it is needed, because the alternative is
inventing a policy while somebody's build is red.

## How you consume this repository, and where a version reaches you

You do not fork it. You keep the substrate — `libs/`, `platform/`,
`orchestration/`, `agentic/`, `scripts/` — and generate the verticals you need
under `projects/`. [`docs/EXPORTING.md`](docs/EXPORTING.md) is the procedure and
[`docs/ADOPTION.md`](docs/ADOPTION.md) is the argument for it.

A version therefore reaches you through exactly two channels:

**1. The generator, through `copier update`.** Every generated vertical carries
a `.copier-answers.yml` recording the generator commit and the answers given.
That file is the whole reason an update is possible: it lets a later run replay
your answers and merge generator improvements without discarding your changes.

```bash
cd projects/my-project && uvx copier update --vcs-ref HEAD --trust
```

**`--vcs-ref` is not optional, and the reason is a measured incident rather
than a principle.** Copier resolves an unpinned git source to the
highest-sorting tag. In the sibling `ml-service-template` that is a frozen
`v1.x` audit snapshot sitting above the active `v0.x` line, and a bare
`copier update` there rewrote a live service backwards: 627 files to 435, 582
deleted, `.copier-answers.yml` among them — which is the record `update`
reads, so the service could not then recover on its own. Check C9 in
`scripts/check_doc_coherence.py` fails the build on any unpinned copier command
documented in this repository, including the one above.

Pin to `HEAD` while working inside the monorepo, where the source is the
working tree. Pin to a tag — `--vcs-ref v0.1.0` — when you want the generator
as it was at a release.

**2. The substrate, by pulling the repository.** `libs/` is consumed by
workspace path, not by version, so a change there reaches every vertical the
moment you pull. That is the monorepo's value and its cost: one fix lands
everywhere, and so does one break. The versioned surface below is what bounds
that cost.

## What a version number promises

`docs/RELEASING.md` § "Version policy" holds the authoritative list, and it is
not repeated here — a second copy would drift from it, and the copy is always
the one somebody reads. In summary: the versioned surface is the generator's
output, the seven requirements in `docs/PROJECT_CONTRACT.md`, the public API of
the five `libs/` packages, the procedure in `docs/EXPORTING.md`, the documented
`make` entry points, the AUTO/CONSULT/STOP mode of any operation in
`AGENTS.md`, and every threshold in `docs/governance/quality-gates.md`.

Two rules follow that you can rely on from `0.1.0` onward:

**A threshold may rise and may never fall.** `scripts/check_thresholds.py`
enforces it against git history rather than against a committed list of
expected values, because such a list is another literal editable in the same
commit as the threshold it is meant to constrain. A rise is at least a MINOR,
because your build can newly fail on unchanged code.

**A break is written down before it ships, with the manual action beside it.**
The line is pre-1.0, so a MAJOR-class change ships as a MINOR — and it carries
the full MAJOR obligation: one entry per break, in the version's `CHANGELOG.md`
section and as a row in the table below, each mapped to something you do rather
than something you are told. A smaller leading digit does not reduce what a
consumer is owed.

## What is explicitly not guaranteed yet

Stated plainly, because the cost of discovering these yourself is the time this
document exists to save.

**Nothing here has ever run in a cloud.** `docs/architecture/implementation-status.md`
prints 0 components at L4. The Terraform for GKE and EKS renders and validates
offline and has provisioned nothing. Any expectation that a version bump has
been exercised against a real cluster or a real account is unfounded, and will
stay unfounded until that document says otherwise.

**Nothing is published.** No workflow builds a container image, and the five
`libs/` packages are uv workspace members rather than distributions. There is
no artifact for you to pin, so "upgrading" means moving the repository you
already have — and it means the supply-chain guarantees that would attach to a
published artifact, signing and provenance among them, do not exist to be
inherited. `docs/governance/quality-gates.md` rows S4 and C1 record both as
outstanding for that reason.

**The five `libs/*/pyproject.toml` versions are not part of this.** They each
read `version = "0.1.0"` and nothing compares them to anything. Do not resolve
a library version from them.

**`VERSION` and `pyproject.toml` can disagree.** Only the second is gated
against `llms.txt`, and only the first is read by the release workflow. A
half-applied bump therefore produces correct release notes beside a stale agent
entry point. `docs/RELEASING.md` names the four locations that move together.

**A pre-1.0 minor may change a contract.** `CHANGELOG.md` has said so since it
was written. Read the version's section before updating, not after.

## The migration table

One row per release that requires an adopter to do something. A release absent
from this table required nothing — recorded as a rule so that an empty table
reads as "no breaks", not as "nobody wrote them down".

| From → to | What changed | What you do |
| --- | --- | --- |
| — | `v0.1.0` is the first release. There is no earlier version to come from | Nothing |

## Writing the next row

When a release breaks something on the versioned surface:

1. Write the row **in the release commit**, not after it. The release workflow
   extracts notes from `CHANGELOG.md` as it exists at the tagged commit, and a
   migration note written later is one the person who needed it never saw.
2. State the manual action as a command or a file to edit. "Review your
   configuration" is not an action.
3. If you shipped the break already, say that too, and say how to recover. The
   sibling repository's most useful migration entry is the one that begins "if
   you already ran a bare `copier update`" — because by the time that entry is
   read, somebody has.

## Related

- [`docs/RELEASING.md`](docs/RELEASING.md) — what a release is, and the version
  policy this file consumes.
- [`docs/EXPORTING.md`](docs/EXPORTING.md) — the consumption model, from the
  generator's side.
- [`docs/ADOPTION.md`](docs/ADOPTION.md) — what arrives working, what is
  homework, and what the platform does not claim.
- [`CHANGELOG.md`](CHANGELOG.md) — the record itself, per version.
