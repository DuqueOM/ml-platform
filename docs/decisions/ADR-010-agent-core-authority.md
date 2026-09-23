# ADR-010 — `libs/llm-core` is authoritative for the agent core; `agent-local` is a one-way export of it

- **Status**: Accepted
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
