# ADR-010 — `libs/llm-core` is authoritative for the agent core; `agent-local` is a one-way export of it

- **Status**: Accepted. Four of its claims were false when it was written —
  one measurement and three guarantees; see
  [Correction, 2026-09-23](#correction-2026-09-23). The decision stands.
- **Date**: 2026-09-23

## Context

[ADR-002](ADR-002-absorbing-agent-local.md) vendored `agent-local` into this
repository with its history. Its dated correction of 2026-09-22 reversed the
decision to archive the source repository, and deliberately left one question
open: when this repository's `libs/llm-core/` and `agent-local`'s `core/`
describe the same code differently, which one is correct?
[ADR-003](ADR-003-service-template-consumption.md) answered the analogous
question for `ml-service-template` in one line. Nothing answered it here.

That correction also set a revisit trigger — *the two cores diverge in
behaviour rather than only in packaging; the authority ADR is then overdue, not
optional* — and it was written without measuring whether the condition already
held. It did. Measured on 2026-09-23 against `main` and `agent-local@c95e331`:

| | `libs/llm-core` here | `agent-local/core` |
| --- | --- | --- |
| Commits since the migration | 9 | 0 (last: 2026-08-05) |
| Python lines | 3,043 | 2,159 |
| Modules present only here | 4 (retrieval evaluation, ~764 lines) | 0 |
| Shared files that are identical | 1 of 12 (`policy.py`) | |

The differences are behavioural, not import paths: `tools.py` alone carries 70
lines of logic `agent-local` does not have. Two API changes landed here and not
there — `load_agent(name)` became `build_agent(config, registry)` because a
library that imports `usecases.<name>` knows where its callers live, which
[ADR-001](ADR-001-monorepo-topology.md) forbids; and `MissingCredential` became
`MissingCredentialError`.

So the correction's description of `agent-local` as "the business-agnostic
upstream" was inaccurate on the day it was written. Nothing flows from it. It is
the original, frozen at the moment of migration, and the actively developed
version is the one that consumed it.

Two further facts shape the decision, and the second corrects an argument that
was first made for it:

- **The policy gate has not diverged.** `policy.py` is byte-identical in both.
  The one file whose drift would be a safety defect rather than a feature gap is
  still in sync, which makes this the cheapest moment to establish a single
  source of truth.
- **The dependency-direction test guarantees less agnosticism than it was
  credited with.** `tests/test_dependency_direction.py` enforces that `libs/`
  never *imports* `projects/`. It does not see data: `doc_corpus.py` and
  `doc_questions.py` enumerate this repository's own documentation by path —
  `docs/ADOPTION.md#...`, `implementation-status.md` — which would describe
  files `agent-local` does not have. `libs/llm-core` is agnostic at the import
  level and not uniformly at the data level. That is why the export below is an
  allowlist, not the package.

## Decision

**`libs/llm-core` is authoritative for the agent core. `agent-local/core/` is a
one-way export of it, produced only by `scripts/export_llm_core.py`.**

This is the pattern large monorepos use to publish a standalone repository from
a subdirectory: the monorepo is the source of truth, the public repository
receives a transformed copy, and provenance records exactly which commit it came
from. Nothing flows back. A change made in `agent-local/core/` is a change made
in the wrong place.

1. **An allowlist of twelve modules.** `__init__`, `agent`, `circuit`,
   `config`, `controller`, `policy`, `retrieval`, `router`, `schemas`,
   `telemetry`, `tiers`, `tools` — the agent core, which is exactly the set
   `agent-local` already ships. The four retrieval-evaluation modules stay here.
   A module added to `libs/llm-core` later is *not* exported until someone
   decides it should be: the safe default for a public distribution.
2. **Imports are rewritten.** `from llm_core.x` becomes `from .x`; the package
   ships as `core` downstream.
3. **ADR citations are re-namespaced for the destination's index.** A citation
   means one decision in one index, and the two repositories number
   independently — this is the defect the namespace qualification that precedes
   this ADR fixed here. `store-ADR-NNN` becomes bare `ADR-NNN` there, because
   those are `agent-local`'s own records. A bare `ADR-NNN` here becomes
   `platform-ADR-NNN` there, because left bare it would resolve to
   `agent-local`'s decision of the same number. `template-ADR-NNN` is unchanged.
4. **`__init__.py`'s docstring is replaced and its version preserved.** The
   docstring here describes this repository — its migration, its Phase 1e
   instruments, this ADR-001 — and exported verbatim it would make claims that
   are false downstream. `__version__` belongs to the distribution:
   `agent-local`'s own coherence check ties it to `agent-local`'s CHANGELOG. The
   library's version is recorded in the provenance file instead.
5. **Provenance, with no timestamp.** `core/EXPORTED_FROM.json` records the
   source commit, the library version and a SHA-256 of every exported file. The
   same commit exports byte-identical output, which is what lets `--check`
   mean something.
6. **The export is guarded downstream.** `agent-local` carries a test that
   recomputes every hash against the provenance file and fails on a hand edit
   or a stray module — without needing this repository to be reachable.
7. **Exports come from `main`.** A commit that can be rewritten by a squash or
   rebase is not provenance. The script refuses uncommitted source outright.

Consumer adaptation is `agent-local`'s, not this library's: its tests, its app
and its evaluation runner compose `build_agent(load_usecase(root), registry)` at
the edge. The app — the composition root — is the only place that still
resolves a use-case by name, which is where [ADR-001](ADR-001-monorepo-topology.md)
says that knowledge belongs.

## Consequences

### Positive

- One place to fix the agent core. A correction to the policy gate or the tool
  contract reaches `agent-local` on the next export instead of never.
- `agent-local` receives the platform's more agnostic core — the one that no
  longer imports its callers by name — together with every fix made here since
  August.
- The description of `agent-local` becomes true: a pinned, provenance-carrying
  distribution of this library, rather than an "upstream" nothing flowed from.
- Authority sits with the repository that has branch protection, a required CI
  lane and an independent-audit cadence.

### Negative

- `agent-local` stops being developed independently. A contributor who opens a
  pull request against its `core/` must be redirected here.
- The first export is a breaking change downstream — `load_agent` and
  `MissingCredential` are gone — paid once by the consumers.
- A second artefact to keep correct: the exporter's transforms are code, and
  code that rewrites citations can rewrite them wrongly. Its tests exist for
  that reason.

### Neutral

- Nothing about how this repository uses `libs/llm-core` changes.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| `agent-local` authoritative, consumed here the way [ADR-003](ADR-003-service-template-consumption.md) consumes the template | The symmetry is real and it is the wrong way round for this code. It would first require moving ~900 lines and the `tools.py` changes back into `agent-local`, reversing the direction in which all the work since August has flowed; it moves authority to the repository with no branch protection; and [ADR-002](ADR-002-absorbing-agent-local.md) already rejected publishing `llm-core` as a package at one consumer, for version skew |
| A deliberate, permanent fork with no synchronisation | Zero coordination, and the policy gate — the one file still identical — would drift. A security fix in one copy would never reach the other, and `agent-local` would become a museum piece, which undercuts the reason it was kept public |
| Archive `agent-local` after all | The maintainer decided on 2026-09-22 to keep it standalone. The stasis measured above is real but seven weeks old; it is covered by a revisit trigger rather than by reversing that decision a day later |
| Export the whole `llm_core` package | Two of its modules enumerate this repository's documentation by path. Exported, they would describe files that do not exist downstream |

## Revisit triggers

- **A consumer of `libs/llm-core` appears outside both repositories.** Publishing
  it as a versioned package — the alternative [ADR-002](ADR-002-absorbing-agent-local.md)
  rejected at one consumer — becomes worth its overhead.
- **`agent-local` receives a change that cannot originate here**, such as an
  external contribution to `core/`. A one-way flow then needs a documented return
  path, or the contribution is lost.
- **An allowlisted module acquires a reference to this repository's own
  files.** The allowlist was drawn on the assumption that these twelve modules
  are data-agnostic; the first such reference means it needs redrawing.
- **Twelve months pass without an export.** The distribution is then dead in
  fact, and archiving it returns to the table with the reasoning it never
  received — the trigger ADR-002's correction already set, inherited here.

## Related

- [ADR-001](ADR-001-monorepo-topology.md) — why the core stopped resolving use-cases by name.
- [ADR-002](ADR-002-absorbing-agent-local.md) — the migration, and the correction whose open question this answers.
- [ADR-003](ADR-003-service-template-consumption.md) — the same question for the template, answered the other way, for reasons that do not transfer.
- `scripts/export_llm_core.py` — the only path code takes from here to `agent-local`.

## Correction, 2026-09-23

**The decision stands. One number had no method, and three of the guarantees
in the Decision were not true of the code that shipped with it.** QA-4 round
twelve found all four by execution. The text above is left as written; this
section is what is true.

### The measured table: "Commits since the migration — 9"

No command was recorded next to the number, and none that fits its label
reproduces it. 9 is the count of every commit on `main` that touches
`libs/llm-core/src/llm_core`, whatever its date:

```text
$ git log --oneline origin/main -- libs/llm-core/src/llm_core | wc -l
9
```

Six of those predate the agent core's arrival in `c7131a1` (2026-08-29) and
went mostly to the retrieval-evaluation modules that are not exported; one is
`c7131a1` itself. The count the row's label asks for is:

```text
$ git log --oneline c7131a1..origin/main -- libs/llm-core/src/llm_core/{__init__,agent,circuit,config,controller,policy,retrieval,router,schemas,telemetry,tiers,tools}.py
7dfec65 chore: archive the agent-local history as a tag, and delete the branch (#73)
01e122d fix: QA-4 rounds nine to eleven — DNS denied in every cloud overlay, and gates that could not fail (#58)
```

**2 commits to the exported modules since the core landed.** The conclusion
does not rest on this row: the divergence is carried by the line counts and by
one file of twelve being identical, both of which the audit reproduced.

### §5: "The same commit exports byte-identical output"

False as shipped, for two reasons. The script did not include itself in its
own clean-tree check, so an uncommitted edit to the exporter was stamped with a
clean commit — the audit produced two different exports of one commit that
way. And the output depends on the destination's `__version__`, which §4
preserves. What holds now: **the same commit, exported into a destination with
the same version, produces byte-identical output.** `scripts/export_llm_core.py`
counts itself as source, and its tests export twice from a scratch repository
and compare.

### §7: "Exports come from `main`. The script refuses uncommitted source outright"

Neither was enforced. `--allow-dirty` wrote a real export stamped
`<sha>-dirty`, and nothing checked where the commit came from; the first export
ran from a branch commit that the squash merge would orphan. Both are enforced
now: `--allow-dirty` is refused without `--check`, and a write is refused
unless `HEAD` is an ancestor of `origin/main`. `--check` still runs anywhere,
because comparing never publishes anything.

### §6: "fails on a hand edit or a stray module"

Overstated. `agent-local`'s test recomputes each hash against
`EXPORTED_FROM.json` — a file in the directory it is validating. An edit to
`policy.py` that also updates that file's hash passes, and so does a new module
listed in it. That test detects **an edit that does not also update the
manifest**, nothing more. The guard that binds runs in `agent-local`'s CI: it
checks out this repository at the commit `EXPORTED_FROM.json` names and runs
`export_llm_core.py --check` against the tree, so the verdict comes from the
source rather than from the thing being judged. It lands with the first export.

### Why these were missed

Each claim was written from the design, and the tests covered only the pure
transforms. Nothing ran `main()`. The audit's five mutations of the exporter
(the multi-line import rewrite, the dirty check, the stray-module refusal,
`--check`'s drift report, the provenance hashes) all passed the original 17
tests. The present suite runs the script end to end against a scratch git
repository, and it kills those five mutations and six more: the three guards
above, and three weakenings of the boundary detector. That is the same defect
[ADR-005](ADR-005-agentic-governance.md) rule A names for numbers: a claim with
no execution behind it.

The boundary test named in the third revisit trigger had the same gap. It
recognised a host file only as a quoted string beginning `docs/`, which let
five of six ways of naming one through. It now walks every string literal in
the exported modules, f-string parts included, and flags a `docs` path
component or the name of any document at the root of this repository or in
`docs/`.
