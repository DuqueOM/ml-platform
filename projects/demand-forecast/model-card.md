# Model card — Demand Forecast

**Owner**: platform-team · **Kind**: tabular · **Dataset**: `nyc-tlc`

## Intended use

**What it is for.** Short-horizon hourly demand per taxi zone, as an input to
supply positioning and staffing. The unit of decision is a zone-hour, which is
the unit the model was fit and scored on; the figures below were measured over
a 168-hour test horizon per fold, and nothing here was measured beyond it.

It produces a point forecast **and an interval**. The interval is the product,
not decoration: a staffing decision taken on the point estimate alone discards
the only signal the model gives about its own uncertainty.

**What it is NOT fit for**, stated because an unstated limit is one a consumer
discovers by violating it:

- **Anything about a person.** The input is trip counts aggregated to a
  zone-hour grid. There is no rider, no driver, and no individual trip in this
  model, and a claim about any of them cannot be derived from its output.
- **Pricing.** Demand was neither fit against price nor scored on a pricing
  objective, and a forecast used to set the price changes the demand it
  forecast — the feedback this evaluation does not model.
- **Zones it does not cover.** 255 of 261 zones are modellable;
  `select_modellable_zones` drops those below `MIN_ZONE_HOURS = 336` hours.
  `ForecastModel.zones` records the covered set and `predict` fails for a zone
  outside it rather than extrapolating from its neighbours.
- **Horizons beyond a week.** The backtest measures 168 hours ahead. Longer is
  not "probably a little worse"; it is unmeasured.
- **Live serving.** Nothing serves this model today
  ([ADR-008](../../docs/decisions/ADR-008-serving-a-forecast-from-a-classification-scaffold.md)):
  the generated service's prediction path is binary classification. The
  artifact is portable and loadable; there is no endpoint behind it.

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

**Not measured. That is the finding, and this section is not a placeholder for
it.**

The subgroup that matters here is **geographic**: the zone, and zones grouped
by borough and by volume decile. A staffing decision is taken per zone, so a
model systematically worse in low-volume zones under-supplies exactly the areas
with the least service — and the headline figures cannot show it, because they
are means over 255 zones.

Three things are known and none of them is a fairness measurement:

- **Coverage is marginal, not conditional.** 89.6% against 90% nominal is an
  average over all zone-hours. Split conformal with one global residual
  quantile gives valid marginal coverage by construction and says nothing about
  any particular zone; the interval can be systematically too narrow in some
  and too wide in others while the aggregate lands on target.
- **Six zones are excluded outright** for having less than 336 hours of
  history. They receive no forecast at all, which is a distributional decision
  even though it is made on data volume rather than on any protected
  attribute.
- **`ml_core.fairness` exists and does not apply as-is.** It measures selection
  and error parity for classifiers — disparate impact, equal opportunity. The
  regression analogue needed here is parity of **error and interval coverage**
  across zone groups, which is not implemented.

**What would close this**: per-zone and per-decile coverage and MAE reported
alongside the marginal figures, with a stated tolerance for how far a group may
deviate before the model is not fit for that group. That is recorded as an open
item (F-19) in
[the remediation work order](../../docs/governance/remediation-work-order.md);
until it is measured, this card does not claim the model is fair, and nobody
should infer it from the aggregate.

## Failure modes

What it does when it is wrong, and what the system does about it.

| Failure | How it shows | What catches it today |
| --- | --- | --- |
| **Staleness** | Demand shifts and the model keeps predicting the old regime | `trained_through` on the artifact is the staleness clock — the timestamp of the last training row, not the file's mtime. Nothing alerts on it automatically |
| **A zone it does not cover** | A caller asks for a zone with too little history | `predict` fails rather than extrapolating from other zones. A loud failure, by design |
| **Intervals too narrow for a particular zone** | Coverage is met on average while a zone is routinely outside its band | **Nothing.** Coverage is measured marginally; see Fairness |
| **Distribution shift** | Inputs move away from what was fit — a new fare regime, a closed zone | `ml_core.drift` provides the contract and PSI comparison; it is **not wired to this model**. Stated rather than implied |
| **Silent metric inflation** | A comparison that flatters the model | Found and quantified: the skill figure is inflated 0.20pp by an asymmetric baseline mask, documented above rather than corrected away |
| **No prediction at all** | The system cannot serve a forecast | The current state, by ADR-008. It is the honest headline failure mode: there is no endpoint |

The pattern worth naming: the failures with a mechanism behind them fail
**loudly** — an unknown zone raises, a schema mismatch refuses to load, a gate
below threshold blocks promotion. The ones with no mechanism are the quiet
ones, and they are listed here for that reason.

## Human oversight

Which decisions require a human, and what enforces that rather than expecting
it.

- **Promotion is gated on measurements, in code.** The retraining DAG refuses
  to promote a model whose skill is below `MIN_SKILL = 0.05` or whose interval
  coverage is below `MIN_COVERAGE = 0.85`, and it reports **both** failures
  rather than the first — an operator who fixes skill to find coverage was
  failing all along has been told half the truth.
- **Lowering any threshold is STOP.** `evals/gates.yaml` declares each
  threshold with the reason it holds that value, and changing one requires a
  recorded reason and a named decision-maker ([AGENTS.md](../../AGENTS.md)).
  `scripts/check_thresholds.py` additionally watches the numbers that live in
  code against git HEAD, so a quiet edit is a failed build rather than a
  smaller gate.
- **Nothing promotes to serving, because there is no serving.** Today a human
  is between this model and any use by construction (ADR-008). That is not a
  control, it is an absence — and when the serving path lands, the control has
  to be built rather than inherited from this sentence.
- **The owner is `platform-team`**, recorded in `evals/gates.yaml` and in this
  card's header. Fairness is unmeasured (above), so any use of this model for a
  decision that distributes service across zones needs that gap answered first,
  by that owner.
