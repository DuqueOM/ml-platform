# Retrieval over this platform's documentation: the measurement

Phase 1e was approved on the condition that it be *"gated on evidence rather
than on expectation"*, with the plan stating in advance:

> If semantic retrieval over this corpus cannot beat lexical overlap by the
> 0.05 margin on the gold set, it does not ship, and the measurement is
> published either way.

**It did not clear the margin. No index ships.** This document is the
measurement, published as promised.

## Result

Corpus: 1,205 sections from 121 tracked markdown files, 92,000 words. Gold
set: 26 questions with a verified section-level answer, written in the
vocabulary of someone who has *not* read the document that answers them.

| Retriever | recall@5 | MRR | Margin over baseline |
| --- | --- | --- | --- |
| Lexical overlap (baseline) | 15.4% | 0.049 | — |
| TF-IDF → SVD, 192 dims (LSA) | 15.4% | 0.046 | **+0.000** |

`beats_baseline(margin=0.05)` returns `False`. Under
[ADR-004](../decisions/ADR-004-tooling-triage.md) this places latent-semantic
retrieval at **Demonstrated**, not Adopted: one narrow use, with its reason
recorded, and no gate claiming it works.

Reproduce with:

```bash
uv run pytest libs/llm-core -q -k retrieval
```

## What the numbers mean, and what they do not

**15.4% recall@5 is poor in absolute terms**, and both retrievers share it.
Random selection from 1,205 sections would return the right one about 0.4% of
the time, so both are doing something — just not enough to be useful.

The diagnosis is more informative than the headline. Inspecting the returned
sections shows a consistent pattern:

> **The right document, the wrong section.** Asked *"the stack came up but I
> do not know whether it actually works"*, the baseline returns three sections
> of `QUICK_START.md` — and not the one that answers it.

That is not a retrieval failure of the usual kind. It is a *granularity*
mismatch: adjacent sections of a well-written document are near-substitutes
for each other, and a metric with one correct answer per question scores a
near-miss identically to nonsense.

Two honest readings follow, and they point in opposite directions:

1. **The metric is stricter than the use case.** An agent handed
   `QUICK_START.md#Before you start` when it wanted
   `#Check that it fits before creating anything` has been helped, and the
   score says it has not.
2. **The metric is exactly right.** The plan's case for retrieval was the
   adopter who cannot name what they need. Handing that person the wrong
   section of the right file is how they conclude the answer is not written
   down.

This document does not resolve that. Loosening the metric after seeing the
number is how a measurement becomes a justification, and the margin was fixed
in the plan before any of this was built.

## One corpus defect found, and what it cost

`CHANGELOG.md#Added` is a single section of several thousand words listing
every change ever made. It matches every query and answers none.

| Corpus | Lexical recall@5 | LSA recall@5 |
| --- | --- | --- |
| With `CHANGELOG.md` (1,214 sections) | 15.4% | 7.7% |
| Without it (1,205 sections) | 15.4% | **15.4%** |

Excluding it **doubled** LSA and left the baseline untouched. That asymmetry
is the interesting part: one oversized section dominates the term
co-occurrence structure the SVD is fitted on, so it distorts the entire latent
space rather than merely occupying a result slot. Lexical overlap has no
shared structure to distort, so it only ever lost one slot.

**The exclusion was decided after observing this, which is stated rather than
quietly applied.** The argument for it does not rest on the improvement: a
changelog section is not an answerable unit, on the same grounds as the
per-tool pointer files already excluded from the corpus. But it was *found*
because the number moved, and a reader deserves to know which order those
happened in.

## Why not a sentence encoder

The obvious next step is a transformer encoder, and it is not taken here:

- **It would have to be downloaded.** A gate that reaches the network fails
  when the network does, and a retrieval score depending on which model
  version a runner fetched is not reproducible.
- **ADR-004 would not admit it.** Adopted tier requires an ADR, a gate and a
  runbook. An encoder that cannot run offline in CI cannot have the gate.
- **The measured failure is not one embeddings obviously fix.** The problem is
  section granularity, not vocabulary mismatch — the retrievers already find
  the right document. A better encoder that still returns the wrong section of
  the right file scores the same.

## What would change the answer

Concrete and observable, so this can be revisited on evidence rather than
enthusiasm:

1. **Retrieve at document level, then at section level within it.** The
   measured behaviour says stage one already works. This is the cheapest
   change with the strongest prior.
2. **Overlapping windows instead of heading splits**, so an answer spanning a
   heading boundary is retrievable from either side.
3. **A gold set with graded relevance**, which needs a different report type —
   `RetrievalReport` deliberately scores one correct answer per query to keep
   recall unambiguous.
4. **An encoder that runs offline**, if one can be vendored reproducibly.

## What was built, and what was not

Built, and kept, because the measurement has to be repeatable:

- `libs/llm-core/doc_corpus.py` — the corpus, enumerated by `git ls-files`
- `libs/llm-core/doc_questions.py` — the 30-question gold set
- `libs/llm-core/semantic_index.py` — the LSA retriever, seeded and offline

**Not built, deliberately: `scripts/check_doc_index_freshness.py`.** The plan
lists it as a deliverable, conditional on an index shipping. No index ships,
so a freshness gate would guard nothing — a mechanism with no substance behind
it, which is the exact defect this repository's gates exist to catch. It is
written the day the margin exists, and not before.

## Related

- `docs/architecture/technical-plan.md` — Phase 1e, and the margin fixed in advance
- `docs/decisions/ADR-004-tooling-triage.md` — the tier this result assigns
- `libs/llm-core/src/llm_core/retrieval_eval.py` — the instrument, dependency-free
- `llms.txt` — the deterministic, diffable alternative this had to beat
