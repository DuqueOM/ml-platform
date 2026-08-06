# Dataset register

Every dataset used by this platform, with its licence, access method and the
reason it was chosen over alternatives. A dataset enters a project only after it
has an entry here.

Two rules:

- **Raw data is never committed.** Datasets are versioned by reference — a
  download script plus a DVC pointer to object storage. Several sources below
  permit use but not redistribution, and the distinction matters.
- **The reason for selection is recorded.** "It was convenient" is a valid
  reason; leaving it unstated is not, because the next person cannot tell a
  deliberate choice from an accident.

---

## Primary — tabular, temporal

### NYC TLC Trip Records

| | |
| --- | --- |
| **Project** | `demand-forecast` (Phase 1) |
| **Access** | Public HTTPS parquet, monthly partitions. Also mirrored in the public data catalogues of both target clouds |
| **Licence** | Public domain / open data. No redistribution restriction |
| **Scale** | Billions of rows accumulated across the full history |
| **Refresh** | Monthly |

**Why this one.** Four properties that alternatives lack simultaneously:

1. **Real temporal drift, not injected.** The series contains a pandemic
   collapse and recovery, fare structure changes, and the 2025 Manhattan
   congestion pricing regime. Drift detection can be demonstrated against
   distribution shifts that actually happened, which is a materially stronger
   claim than showing PSI respond to noise a script added.
2. **Genuinely partitioned.** Monthly parquet files make backfill, incremental
   ingest and time-travel queries real operations rather than simulated ones.
3. **Large enough to justify the Spark/DuckDB contrast** that
   [ADR-004](../decisions/ADR-004-tooling-triage.md) requires — the full
   history warrants distributed compute while the monthly increment does not,
   and the crossover is measurable.
4. **Present in both clouds' public catalogues**, so the same dataset feeds the
   GCP and AWS paths. Multi-cloud parity is demonstrated on identical data
   instead of on two similar datasets.

**Known hazards.** Schema evolves across years (column renames, added fields) —
which is a feature for exercising Iceberg schema evolution, and a trap for
anyone assuming a stable schema. Some months contain records with implausible
coordinates or durations; cleaning rules are part of the contract, not
preprocessing folklore.

---

## Fairness and distribution shift

### Folktables (ACS PUMS)

| | |
| --- | --- |
| **Project** | `credit-risk` (Phase 4) |
| **Access** | `folktables` Python package over US Census ACS microdata |
| **Licence** | US Census public use |

**Why this one.** It is partitioned by state and by year, which means
distribution shift is **built into the data** rather than manufactured by
splitting. It carries genuine demographic attributes, so fairness gates operate
on real subgroups. It is the modern replacement for the UCI "Adult" dataset,
whose well-known preprocessing artifacts make published results hard to compare.

**Known hazards.** Fairness results are sensitive to the prediction task and
threshold chosen; the task definition must be documented in the model card, not
inherited silently from an example.

### Home Credit Default Risk

| | |
| --- | --- |
| **Project** | `credit-risk` (Phase 4) |
| **Access** | Kaggle competition data; download script, not committed |
| **Licence** | Competition terms — **use permitted, redistribution not**. Never commit derived files without checking |

**Why this one.** Multiple related tables with historical records per applicant,
which is the shape that makes **point-in-time correctness** a real requirement
rather than a lecture. A naive feature build leaks future information, and a
test that fails on that naive build is worth more than a paragraph explaining
leakage.

---

## Relational / operational

### Olist Brazilian E-Commerce

| | |
| --- | --- |
| **Project** | Feature-store and CDC demonstrations |
| **Access** | Kaggle; loaded into managed Postgres |
| **Licence** | CC BY-NC-SA — **non-commercial**, attribution required |

**Why this one.** Nine related tables with genuine order, delivery and review
timestamps — enough relational structure to make as-of joins meaningful, small
enough to load into a free-tier database.

---

## Documents / deep learning

### FUNSD · CORD · DocVQA

| | |
| --- | --- |
| **Project** | `doc-intelligence` (Phase 5) |
| **Access** | Public research downloads |
| **Licence** | Per-dataset research terms — check each before publishing derived artifacts |

**Why these.** Standard document-understanding benchmarks with published
baselines, so a fine-tuning result is comparable rather than self-reported. Small
enough for LoRA fine-tuning within the available ~7.6 GiB of VRAM.

---

## Retrieval / LLM

### SEC EDGAR filings

| | |
| --- | --- |
| **Project** | `rag-assistant` (Phase 3) |
| **Access** | Public EDGAR full-text search and bulk endpoints |
| **Licence** | US public record |

**Why this one.** Real enterprise documents: long, inconsistently formatted, and
containing verifiable numeric facts. That last property is what makes
**evaluation with ground truth** possible — a retrieval answer about a reported
figure is checkable, unlike a summarisation judged by another model.

**Known hazards.** EDGAR requires a declared user agent and enforces rate
limits; the ingestion client must honour both.

### BEIR / MS MARCO / HotpotQA

| | |
| --- | --- |
| **Project** | `rag-assistant` retrieval benchmarking |
| **Licence** | Per-dataset research terms |

**Why these.** Published retrieval baselines, so recall@k and nDCG figures are
comparable to a literature number rather than to nothing.

---

## Considered and not adopted

| Dataset | Why not |
| --- | --- |
| UCI Adult | Superseded by Folktables, which has real shift and cleaner provenance |
| Criteo 1TB click logs | Scale would justify Spark, but the features are anonymised integers — no interpretability, fairness or feature-engineering story |
| MIMIC-IV / eICU | Excellent for a clinical governance track, but requires CITI training and a signed data use agreement. Revisit if healthcare becomes a target domain |
| Pagila / Chinook / Northwind | Useful for testing migrations and database branching; too small to carry an ML project |
| Synthetic generators | Cannot demonstrate drift detection credibly. A detector tuned on drift a script injected has only been shown to detect that script |
