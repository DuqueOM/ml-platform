# rag-assistant

Retrieval over real SEC filings, evaluated against a lexical baseline it has to
beat before anything is promoted.

## What it does

`ingest` fetches filings from EDGAR (rate-limited, with the `User-Agent` the
SEC requires), `chunking` splits them at sentence boundaries, and `evaluation`
scores retrieval against gold answers keyed by TEXT rather than by chunk index —
so a re-chunk does not silently invalidate the gold set.

The gates live in `libs/llm-core/src/llm_core/retrieval_eval.py`: recall@k
blocks, MRR informs, and `beats_baseline` requires a 0.05 margin over a lexical
overlap baseline. A retrieval system that cannot beat word overlap has not
earned its embedding model, and the margin is watched against git HEAD by
`scripts/check_thresholds.py`.

## Run it

```bash
uv sync --all-packages
uv run pytest projects/rag-assistant -q
```

## Known limitation, measured

The chunker is **broken on real filings** and the test says so rather than
hiding it: against a target of 800 characters, real 10-K documents produced a
median of 1,588 and a largest chunk of 1,087,381, with 1,234 of 3,411 chunks
oversized. SEC filings are SGML with tables and long runs of non-prose, and a
sentence-boundary splitter has nothing to split on there.

Recorded as `xfail(strict)` in `tests/test_chunking.py`, which means the day it
is fixed the test fails and someone has to remove the marker. Fixing it needs a
second boundary for non-prose and probably SGML stripping before chunking.

## Contract deviations

This project was built by hand rather than generated, so it has no
`.copier-answers.yml` and is outside `copier update`. That and two other gaps
are recorded in `KNOWN_DEVIATIONS` in `tests/test_project_contract.py`, with
what would close each. See `docs/PROJECT_CONTRACT.md`.
