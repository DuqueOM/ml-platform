# Model card — Demand Forecast

**Owner**: platform-team · **Kind**: tabular · **Dataset**: `nyc-tlc`

## Intended use

TODO — and, more importantly, the uses this model is **not** fit for. An
unstated limit is one a consumer will discover by violating it.

## Data

Source and licence: see `docs/datasets/register.md` for `nyc-tlc`.

**Redistribution**: check the registry before publishing any derived artifact.
Several registered sources permit use but forbid redistribution, and that
distinction is a licence term, not a style preference.

**What the figures below were measured on.** `yellow_tripdata_2024-01.parquet`
and `yellow_tripdata_2024-02.parquet`, checksums verified against
`data/nyc-tlc/manifest.json` — 5,971,957 trips surviving the contract (reject
rate 0.0038% and 0.0027%), aggregated to a **dense** hourly grid per zone of
357,426 rows across 261 zones, spanning 2024-01-01 00:00 to 2024-02-29 23:00.

Measured from the files, not through `read_demand()`. The Iceberg table now
carries the same shape at snapshot `5953582871017899527`, but that is stated as
provenance for the TABLE, not as the input to this evaluation — citing a
snapshot a number did not come from is the kind of claim this card exists to
prevent.

## Evaluation

Thresholds and their rationale live in `evals/gates.yaml`. This section records
what was **measured**, with the method:

| Metric | Value | How it was measured |
| --- | --- | --- |
| Skill over seasonal naive | **+12.6%** | `evaluate(demand)` at its default 5 folds. Two readings at `seed=42`, byte-identical. Gate: `MIN_SKILL = 0.05` |
| Skill, 3-fold design | **+23.0%** | Same call at `n_folds=3`, reported because the superseded `+55.8%` used three folds and the comparison is otherwise not like for like |
| Interval coverage | **89.6%** against 90% nominal | Split conformal, `ALPHA = 0.1`, calibrated on the last 168 hours of each training window. Gate: `MIN_COVERAGE = 0.85` |
| Model MAE | 3.34 trips/zone/hour | Mean over 5 folds |
| Baseline MAE | 3.82 trips/zone/hour | Seasonal naive — same hour last week — on the rows where a baseline exists |
| Modellable zones | 255 of 261 | `select_modellable_zones`, `MIN_ZONE_HOURS = 336` (two feature windows) |

**Method.** Expanding-window backtest cut on TIME, not row position: a
positional cut on a 261-zone panel trains on some zones and tests on others.
168-hour test horizon per fold, gap of `LONGEST_LAG` (168h) so training cannot
reach the test window through the feature lags, `seed=42` passed to both
`seed_everything` and the estimator. Reproduce with:

```bash
uv run python -c "
from pathlib import Path
import polars as pl
from demand_forecast.ingest import ingest_file, to_hourly_demand
from demand_forecast.train import evaluate
frames = [ingest_file(p)[0] for p in sorted(Path('data/nyc-tlc').glob('yellow_tripdata_2024-0*.parquet'))]
print(evaluate(to_hourly_demand(pl.concat(frames))).summary())
"
```

**These figures replace `+55.8%`**, which was produced against a baseline
computed by row offset on a panel that was never densified to an hourly grid.
That claim is superseded, not amended: the `[0.1.0]` CHANGELOG entry keeps it.

**One known bias in the number above, quantified rather than mentioned.**
`evaluate()` computes `model_mae` over every test row but `baseline_mae` only
over rows carrying a baseline. Those sets differ in folds 0 and 1 (99.31% and
99.54% of rows), so the asymmetry is live, not latent. Masking both the same
way gives **+12.4%** — the reported figure is inflated by **0.20 percentage
points**, and the direction favours the model. Both sides of the comparison
clear `MIN_SKILL`.

## Fairness

TODO — which subgroups, on which attribute, measured how. Aggregate metrics
average away the subgroup where a model fails systematically.

## Failure modes

TODO — what this model does when it is wrong, and what the system does about
it. A model with no stated failure mode has an undocumented one.

## Human oversight

TODO — which decisions require a human, and how that is enforced rather than
expected.
