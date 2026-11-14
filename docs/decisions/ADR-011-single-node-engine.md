# ADR-011 — DuckDB is the single-node engine for trip-level work; Polars holds the panel

- **Status**: Accepted
- **Date**: 2026-11-14

## Context

[ADR-004](ADR-004-tooling-triage.md) placed "DuckDB / Polars" at Core for
incremental transformation, and made the Spark decision depend on a measured
threshold: *the measured data volume crosses the threshold where DuckDB stops
being sufficient for the incremental path*. Two facts contradicted that, found
in the dependency round of 2026-10-27 (work order, DEP27-D1):

- **DuckDB ran nowhere.** `libs/ml-core` declared it and nothing in the tree
  imported it. The technology inventory marked it implemented, because its only
  detection rule matched the declaration. That is the defect class
  [ADR-005](ADR-005-agentic-governance.md) rule H names.
- **The threshold was measured on the wrong engine.** `crossover.py` measured
  Polars holding the whole month in memory and projected its RAM linearly. The
  result is the limit of an in-memory engine. An out-of-core engine does not
  hit a RAM wall, so the number answered a question ADR-004 did not ask.

The obvious fix in each direction was rejected as forcing an answer. Deleting
DuckDB would make the documents agree by shrinking the claim. Wiring DuckDB in
"because ADR-004 says so" would add a second engine with no job. The question
had to be measured: **does this platform have work that one engine does
measurably better than the other?**

## The measurement

**Workload**: the ingest exactly as it runs:

- each file's month window;
- the contract's row rules;
- the dropoff-after-pickup relation;
- the hourly aggregate.

**Data and design**:

- the real NYC TLC files for 2024-01 and 2024-01/02;
- one engine per process, the same 4 threads for each;
- peak resident memory from `/usr/bin/time -v`;
- three runs each.

**Result**: every engine's output was identical to Polars eager. The keys and
counts were equal; the fares differed in their last digits, discussed below.
The two-month grid had 357,426 rows, as in the model card. The streaming plan
was checked with `explain` and runs fully streaming, with nothing falling back
to memory. The commands and their raw output are in the pull request that
landed this ADR. The equivalence they rest on is not left to it:
`test_ingest_engine.py` holds it on every build.

| Engine | Peak, 1 month (MB) | Peak, 2 months (MB) | Wall (s) |
| --- | --- | --- | --- |
| Polars eager (the ingest before this ADR) | 850 – 896 | 1447 – 1698 | 0.8 – 3.1 |
| Polars streaming | 536 – 546 | 738 – 765 | 0.6 – 1.0 |
| **DuckDB** | **294 – 300** | **399 – 403** | 0.8 – 1.6 |
| DuckDB, `memory_limit = 256MB` | 293 – 297 | 314 – 354 | 0.9 – 1.1 |

The local stack gives the workload 512 MB (`crossover.measure`'s budget).

- **One month**, the DAG's unit of work: Polars eager needs 1.7 times that budget, and Polars streaming is just over it. Only DuckDB fits.
- **Two months**: only DuckDB fits, with room to spare.
- **Wall time** is equivalent across all three.

Two further measurements decided the design:

- **Aggregates must be ordered.** Summed in no particular order, the same
  month's hourly fares differed in their last digits between three runs: three
  different digests. With the sum ordered by the file's row number, the three
  digests were identical, at about 0.5 s per month.
- **Deriving the cleaning rule from the contract changes no row.** `clean`
  restated seven of the contract's eight rules by hand and left out
  `passenger_count`. On 2024-01/02 no row is outside that column's bounds: 0
  of 5,972,150, with 325,772 null, which the contract allows.

## Decision

**DuckDB does trip-level work: validating, cleaning and aggregating a month
of trips. Polars holds the hourly panel built from it.** One engine for each
role, not two engines for one role:

- `demand_forecast.ingest.ingest_hourly` reads the file, counts the contract's
  violations, keeps the admitted rows in the month, and aggregates them, all
  in DuckDB. Only the hourly aggregate reaches Python, where Polars densifies
  it. `clean` and `to_hourly_demand` keep their signatures for in-memory
  frames and run through the same DuckDB rule, so one implementation remains.
- **The contract is the only list of bounds.**
  `data_contracts.duckdb_relation` builds the DuckDB predicates from
  `DataContract`'s rules. It returns the verdict `DataContract.validate`
  gives, rule for rule and example for example; its tests hold that against
  Polars. It is an optional extra (`data-contracts[duckdb]`) and never
  imports anything above the library.
- **Bounded, and unable to fetch code.** The ingest runs with
  `memory_limit = 256MB` and spills to a private temporary directory beyond
  it. Extensions are neither autoloaded nor autoinstalled, so an `s3://` path
  is refused rather than satisfied by downloading httpfs. The configuration
  is locked once set.
- **Deterministic.** Every aggregate is summed in the file's row order.
- **The dependency lives where it is used:** `projects/demand-forecast`
  declares `duckdb`, and `libs/ml-core` no longer does.

**Polars streaming is rejected for this role.** It used 1.8 to 1.9 times
DuckDB's memory at the same speed, and validating the contract in it would
still have needed a second pass over the data.

## Consequences

### Positive

- One month ingests in about 300 MB, inside the local workload budget, where
  it used 870 MB. The DAG's unit of work fits the machine the stack is sized
  for.
- The ingest produces the same bits every run.
- The bounds that report a violation and the bounds that drop a row are one
  list. They had already drifted apart, by one column.
- The ingest's parity check against the real feed found that contract 1.0.0
  declared the timestamps at nanosecond resolution, while the 2024 files
  carry microseconds. Every run had reported both columns as a dtype violation
  over 100% of rows. Contract 1.0.1 declares what the feed carries.

### Negative

- Each run starts a second engine in the process. The Arrow hand-off of the
  aggregate is a copy, small at about 180,000 rows a month.
- An ingest that must read remote storage now needs a decision. Enabling an
  extension is a supply-chain change: it has to be pinned and has to be
  scanned. Today every caller passes a local path, and on Vertex AI that is
  the bucket's `/gcs/` mount.
- The 1e-11 difference between engines in summed fares is real. The equivalence
  test bounds it at 1e-9 and holds keys and counts exactly.

### Neutral

- **The Spark threshold is still not measured.** For an out-of-core engine it
  is throughput over the backfill window, not memory, and it needs more data
  than two months: twelve, pinned in the dataset lock (P13).
  `crossover.measure` now measures the DuckDB ingest, samples its peak while it
  runs, and says so in its output. Until the twelve-month run exists, the
  projection is labelled a projection, and the measurement is PENDING in the
  plan.

## Alternatives considered

- **Remove DuckDB and move it out of Core in ADR-004.** Rejected. The
  measurement showed a job it does best: holding a month inside the local
  budget. Removing it would have made the documents true by making the
  platform worse.
- **Polars streaming.** Rejected above, on the measurement.
- **DuckDB's Iceberg extension, for reading the lakehouse.** Not needed.
  `pyiceberg` already pushes partition and column filters down, and the
  extension is a run-time download.
- **Feast's DuckDB offline store, as DuckDB's reason to exist.** Not a reason
  today. It reads Parquet and Delta, not Iceberg; its maturity is not declared
  in Feast's documentation; and Feast is not wired in. It is a revisit
  trigger.

## Revisit triggers

- **The twelve-month throughput measurement exists.** If a backfill of the
  full history cannot finish within its window on one node, Spark moves from
  Demonstrated to Core, as ADR-004 states.
- **An ingest must read remote storage directly.** Then decide on a pinned,
  scanned extension, or on a staged local copy, in an amendment to this ADR.
- **Feast is wired in.** Evaluate its DuckDB offline store against the
  lakehouse's format at that point.
- **A second project ingests trip-level data.** `data_contracts.duckdb_relation`
  is already shared. The connection settings in `demand_forecast.ingest`
  would then move to a library.

## Related

- [ADR-004](ADR-004-tooling-triage.md): the tier this corrects, in its
  dated Correction.
- [ADR-005](ADR-005-agentic-governance.md): rule H, a declaration counted as
  use.
- `projects/demand-forecast/tests/test_ingest_engine.py`: equivalence with
  the Polars path, and determinism.
- `libs/data-contracts/tests/test_duckdb_relation.py`: the same verdict,
  rule for rule.
