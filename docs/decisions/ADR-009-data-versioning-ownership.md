# ADR-009 — Three data-versioning mechanisms, one criterion each

- **Status**: Accepted
- **Date**: 2026-09-03

## Context

The technology inventory listed `dvc` at **Core** tier with
`detect: [".dvc", "dvc.yaml"]`. Neither path existed. `AGENTS.md` carried a
permissions row — `dvc add` a data artifact → AUTO — for a tool no checkout
could run. `docs/datasets/register.md` stated:

> Datasets are versioned by reference — a download script plus a DVC pointer to
> object storage.

Half of that was true. The download script exists and is good:
`scripts/datasets/fetch.py` computes a SHA-256 for every file it fetches and
writes it to `manifest.json`. There was no DVC pointer, and there never had
been.

This is ADR-005 rule K — a published claim with no command behind it — in the
one area where the claim is about reproducibility itself.

### The defect was narrower and worse than "DVC is missing"

`data/` is gitignored, and `manifest.json` is written *inside* it. So the
digests were computed, recorded, and then placed where no reviewer, no CI job
and no second machine could ever read them:

```text
git ls-files data/
(no output — every manifest is behind the gitignore)
```

The manifest proved *"this machine keeps getting the same bytes"*. It could not
prove *"everyone gets the same bytes"*, and the difference is the entire value
of a pin. A third-party source that quietly re-published different content
under a stable URL would have changed every downstream number with no diff
anywhere in the repository.

Installing DVC would not, by itself, have fixed that. It would have added a
second copy of a digest the fetcher already computed correctly.

### What was already versioned, and was wrongly reported as not

An earlier reading of this area claimed the retrieval gold set was unversioned
data gating promotion. **That was wrong, and the correction matters because it
changes what DVC is for.** The gold set is
`libs/llm-core/src/llm_core/doc_questions.py` — Python source in git, labelled
by `path#heading` rather than by corpus index precisely so a heading added
elsewhere cannot silently re-point it, with `test_doc_retrieval.py` failing
when a label stops resolving. The corpus it scores against is enumerated by
`git ls-files`, not by walking the filesystem, so it cannot vary by host.

Both are already reproducible by the strongest mechanism available — git — and
moving them to DVC would make them *less* reviewable, not more.

## Decision

**Three mechanisms own data in this platform. Each has one mechanical
assignment criterion, and no datum is owned by two.**

| Mechanism | Owns | Criterion | Evidence it works |
| --- | --- | --- | --- |
| **Iceberg** | Pipeline tables | Has a schema, grows by append, is queried by snapshot | `lakehouse.py`; snapshot 1 returns 77,539 January rows while the table holds 151,920 |
| **`datasets.lock.json`** (git) | Third-party downloads | **An authoritative URL exists that can re-serve the same bytes** | `fetch.py --verify`; 3 files, 263 MB, verified against the pin |
| **DVC** | Data we produce | **No authoritative URL exists** — generated, derived, curated or labelled here | `.dvc/config`, remote on the S3 protocol |

Everything else stays in git as source: gold sets, fixtures, thresholds,
schemas. Git is the strongest mechanism of the four and the only one that makes
a change *reviewable line by line*. Data leaves git only when its size or its
licence forces it out — never for tidiness.

### Why the criterion is "does an authoritative URL exist"

It is the only question whose answer determines what recovery actually
requires.

When a URL exists, a digest is sufficient: the bytes can be re-fetched and
checked. Storing a second copy buys nothing and costs a bucket to operate, a
bill, and a synchronisation that can fail. NYC TLC and SEC EDGAR are in this
class.

When no URL exists, a digest is worthless. Hashing a dataset nobody else can
obtain records that it was lost with cryptographic precision. Content-addressed
storage is the only mechanism that can return the bytes, and that is DVC's job
here. A dataset generated, scraped, labelled or hand-curated for this platform
is in this class — including any that arrives from work done outside this
repository.

The criterion is deliberately not "size" and not "is it text". Both are
proxies, both have exceptions, and neither tells you what you need to do to get
the data back.

### What was built

- **`docs/datasets/datasets.lock.json`** — the committed pin. Carries digest,
  URL, byte count, licence and redistribution term per file. It deliberately
  carries **no timestamp**: `fetched_at` is a per-machine fact, and a file that
  diffs on every run trains reviewers to skim the one file whose value is that
  a diff means something.
- **`fetch.py --write-lock`** — pins every dataset present locally, preserving
  entries for datasets this machine has not fetched. Running it on a partial
  checkout must not silently unpin the rest.
- **`fetch.py --verify`** — recomputes digests on disk and compares. Reports
  *unpinned*, *missing* and *MISMATCH* separately, because the response to each
  differs. Verified against 263 MB of real data; **proven to fail** by
  falsifying a pin, which is the check ADR-005 rule K asks for and the one most
  often skipped.
- **`tests/test_dataset_lock.py`** — the CI gate, 8 tests.
- **`.dvc/` with an S3-protocol remote** — MinIO locally, cloud object storage
  later, one code path. Analytics disabled: this repository does not phone home
  without a recorded decision.

### What the CI gate does and does not prove

Stated here because the boundary is the honest part of the claim.

CI has no data. `test_dataset_lock.py` therefore hashes nothing. It checks the
lock's *internal coherence*: every pin names a registered dataset, at a URL the
registry declares, under the licence the registry states, with a well-formed
digest, and every fetchable dataset is either pinned or carries a written
reason why it is not.

Byte verification is `--verify`, which needs the data and runs where the data
is. A test that downloaded 263 MB per commit to close that gap would trade a
real cost for a failure mode — a source changing underneath a stable URL — that
the committed lock already surfaces as a reviewable diff.

The `unfetched` section carries the same expiry discipline as
`test_project_contract.py::test_no_deviation_outlives_its_cause`: an entry for a
dataset that later gets pinned fails the suite until it is deleted.

## Consequences

### Positive

- A third-party source that changes what it serves is now a **diff in a
  reviewed file**, not a silent shift in every downstream measurement.
- `dvc` reports **Built** in the inventory because the artifacts exist, derived
  from the filesystem — the YAML was not edited to make that happen.
- The register's claim is true for the first time.
- A dataset produced outside this repository now has a documented home and a
  one-command path in: `dvc add`, then commit the pointer.
- The three mechanisms can be *assigned* by anyone, without a judgement call,
  which is what stops the boundaries eroding.

### Negative

- A third dependency to keep current, and DVC's release cadence is brisk. It is
  a dependency **group** (`data-versioning`) rather than an extra, so it is
  absent from a default `uv sync` and from CI's `uv sync --all-extras` — no CI
  step imports dvc, and adding ~40 packages to every build for a path glob
  would be cost with no consumer.
- The DVC remote has never been pushed to. `.dvc/config` is configuration, not
  evidence; no L3 or L4 row is claimed for it, and none should be until a real
  `dvc push` runs against the local stack.
- `--verify` cannot run in CI, so the *byte* check depends on somebody running
  it. That is written above rather than papered over.

### Neutral

- Two files now carry the same digests: `manifest.json` (per-machine, with a
  timestamp) and the lock (committed, without one). The duplication is
  deliberate — they answer different questions — and the lock is generated from
  the manifest, so they cannot disagree without the generator being wrong.

## Alternatives considered

| Alternative | Why it lost |
| --- | --- |
| **`dvc add` everything under `data/`** | Would re-pin bytes `fetch.py` already hashes correctly, and require operating a remote from day one to store data that is a `curl` away. Two mechanisms pinning one file is how they drift |
| **Demote `dvc` to Studied; ship only the lock** | Honest, cheap, and leaves data with no authoritative URL — the class that motivated the review — with nowhere to live. It solves the reporting defect and not the operational one |
| **Git LFS instead of DVC** | Adequate for large files, but has no concept of a pipeline stage or a remote per environment, and puts the data in the git host's billing. DVC's `dvc.yaml` is the reason to prefer it, even though nothing uses that yet |
| **lakeFS instead of DVC** | Git-like semantics over the whole object store, which is genuinely better at the branch-a-dataset workflow — and requires operating a server. ADR-004 rejects operated dependencies where a file-based tool suffices; the same argument that keeps Vault out |
| **Iceberg for everything** | Iceberg versions *tables*. A directory of PDFs, a set of prompts or a labelled CSV has no schema to evolve and no partition to travel through. Forcing them into a table format would mean inventing one |
| **Nothing; keep the manifest as-is** | The manifest is unreadable by anyone who did not run the fetch. That is the defect |

## Revisit triggers

- **A `dvc push` runs against the local stack.** The remote stops being
  configuration and earns an L3 row in `VALIDATION_LOG.md`. Until then no row
  should exist.
- **A dataset needs branching rather than pinning** — two labelling passes
  compared side by side. That is lakeFS's shape, not DVC's, and re-opens the
  alternative above.
- **A third-party source is caught changing its bytes.** Record it: it is the
  first evidence the lock earns its runtime, and it should change how often
  `--verify` is run.
- **The `unfetched` section stops shrinking as phases land.** An exemption list
  that only grows has become the place the lock goes to die.
- **`dvc.yaml` pipeline stages get used.** The Git LFS comparison above turns
  on that and should be re-read once it is no longer hypothetical.

## Related

- [ADR-004](ADR-004-tooling-triage.md) — the Core/Demonstrated/Studied tiers
  this decision moves `dvc` within, and the operated-dependency argument that
  rules out lakeFS and Vault alike.
- [ADR-005](ADR-005-agentic-governance.md) — rule K, the claim/gate mapping
  this ADR closes; and rule A, why `--verify` had to be proven able to fail.
- `docs/datasets/register.md` — why each dataset was chosen.
- `scripts/datasets/registry.py` — how each dataset is obtained.
- `docs/datasets/datasets.lock.json` — which exact bytes.
- `projects/demand-forecast/src/demand_forecast/lakehouse.py` — the Iceberg
  half of the split.
