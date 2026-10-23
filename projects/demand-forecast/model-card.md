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
| Skill over seasonal naive | **+12.9%** | `evaluate(demand)` at its default 5 folds, `seed=42`, both errors on the rows that carry a baseline. Gate: `MIN_SKILL = 0.05` |
| Skill, 3-fold design | **+21.0%** | Same call at `n_folds=3`, reported because the superseded `+55.8%` used three folds and the comparison is otherwise not like for like |
| Interval coverage | **92.0%** against 90% nominal | Mondrian conformal — one residual quantile per volume decile — `ALPHA = 0.1`, calibrated on the last 168 hours of each training window. Over nominal because the quietest deciles over-cover; see Fairness. Gate: `MIN_COVERAGE = 0.85`, `MAX_COVERAGE = 0.95` |
| Coverage, worst volume decile | **88.7%** (decile 5) | Every decile between 88.7% and 98.4%; see Fairness. Gate: `MIN_GROUP_COVERAGE = 0.85` |
| Harm, worst volume decile | **−0.0082** trips/zone/hour (decile 0) | Lower 95% bound of model MAE minus baseline MAE, Student's t over the 5 folds: negative in every decile, so in none does the baseline serve the zones better. Gate: `GROUP_HARM_CONFIDENCE = 0.95`, refused above zero (F-19b) |
| Model MAE | 3.33 trips/zone/hour | Mean over 5 folds, on the same rows as the baseline. Fitted under absolute error, so the point forecast is the per zone-hour **median** (F-19b) |
| Baseline MAE | 3.83 trips/zone/hour | Seasonal naive — same hour last week — on the rows where a baseline exists |
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

**The skill figure was +12.6% until 2026-09-29, and the card said why it was
wrong before the code did.** `evaluate()` took `model_mae` over every test row
and `baseline_mae` only over rows carrying a baseline — two means over two
populations, in a result type whose docstring promised "the same rows". This
card measured the effect as 0.20 percentage points in the model's favour and
predicted +12.4% like-for-like. The fix (QA-4 F-21) scores both on the rows
with a baseline, and re-measuring on the same files gave **+12.4%** — the
prediction, confirmed rather than assumed. Folds 0 and 1 compare 99.31% and
99.54% of their rows; the other three compare all of theirs, which is why the
3-fold figure did not move.

**The average hides a fold the model loses.** Per fold, at `seed=42`, under
the absolute-error loss (F-19b), with the squared-error figures it replaced:

| Fold | Skill | Coverage | Skill, squared error |
| --- | --- | --- | --- |
| 0 | **−8.7%** | 92.8% | −18.3% |
| 1 | +0.9% | 93.6% | −1.2% |
| 2 | +13.7% | 92.1% | +14.3% |
| 3 | +30.2% | 91.2% | +30.9% |
| 4 | +18.1% | 90.2% | +22.9% |

Re-measured on 2026-11-13 on the same files, design and seed, after the loss
changed from squared to absolute error, and again on polars 2.1 with the same
result to the last digit. The loss narrowed the earliest folds' deficit and
cost the latest two a few points.

Re-measured on 2026-10-23 with Mondrian intervals (F-19) on the same files,
design and seed. Skill is unchanged at +12.4%: the intervals changed, not the
point forecast. The baseline MAE moved from 3.82 to 3.83 because 855 test rows
are no longer scored. They belong to zones a fold's training rows never saw,
and the deployed model refuses a zone it was not fitted on, so the backtest
does not score one either.

The expanding window gives the earliest folds the least history, and in fold
0 the model still does worse than repeating last week. The per-decile gate
pools the folds, so it does not see this either: in deciles 8 and 9, folds 0
and 1 lose to the baseline (+0.74, +2.84 and +1.05 trips an hour) under the
absolute-error loss too. It clears the promotion skill floor
(`promotion.MIN_SKILL`) on the mean,
not in every fold — which matters for anyone reading +12.9% as "better than
the baseline, always".

## Fairness

**Measured by volume decile, on 2026-10-23 (F-19). By borough, not yet.**

The subgroup that matters here is **geographic**. A staffing decision is taken
per zone, so a model that is systematically worse in low-volume zones
under-supplies exactly the areas with the least service — and the headline
figures cannot show it, because they are means over 255 zones. Zones are
grouped into deciles by mean demand, ranked on each fold's **training** rows
only, so the test period cannot decide which group a zone is judged in.

**Interval coverage was the failure, and it is fixed.** Split conformal with
one global residual quantile gives valid marginal coverage by construction and
says nothing about any group. Measured on these files before the fix, it
covered **100%** of the quietest six deciles' hours and **63.9%** and
**37.7%** of the two busiest — while the aggregate read 89.6%. The intervals
were far too wide where demand is low and far too narrow where it is high,
which is where staffing volume is. The model now uses **Mondrian conformal**:
one quantile per decile, each calibrated on that decile's own residuals, which
gives the coverage guarantee within each group.

| Volume decile | Coverage, one global quantile | Coverage, Mondrian, squared error | Model MAE, squared error | Coverage, Mondrian, absolute error | Model MAE, absolute error | Baseline MAE |
| --- | --- | --- | --- | --- | --- | --- |
| 0 (quietest) | 100.0% | 92.8% | **0.16** | 98.4% | 0.01 | 0.02 |
| 1 | 100.0% | 89.4% | **0.22** | 92.5% | 0.08 | 0.14 |
| 2 | 100.0% | 89.3% | **0.28** | 94.2% | 0.15 | 0.24 |
| 3 | 100.0% | 89.5% | **0.36** | 96.3% | 0.23 | 0.33 |
| 4 | 100.0% | 88.4% | **0.46** | 92.7% | 0.35 | 0.45 |
| 5 | 100.0% | 89.0% | 0.61 | 88.7% | 0.52 | 0.65 |
| 6 | 99.7% | 89.0% | 0.88 | 91.4% | 0.83 | 0.99 |
| 7 | 96.4% | 88.9% | 2.00 | 89.1% | 1.98 | 2.36 |
| 8 | 63.9% | 88.6% | 8.13 | 88.9% | 8.19 | 9.38 |
| 9 (busiest) | **37.7%** | 89.0% | 19.78 | 89.1% | 20.32 | 22.87 |

Errors are in trips per zone per hour, absolute rather than relative: in decile
0 the baseline's error is 0.02, and a ratio over it turned 0.14 trips an hour
into "−840.5% skill".

**The stated tolerance is a floor of 0.85 per decile**, decided on 2026-10-23
and enforced by the promotion gate (`MIN_GROUP_COVERAGE`): a model whose worst
decile covers less is refused, whatever the aggregate says. There is no
per-decile ceiling. The quietest zones' counts are integers and mostly zero,
so their over-coverage — 98.4% in decile 0 under the current loss — is partly
discreteness rather than miscalibration. It is reported, not gated. It is also
why the aggregate coverage reads 92.0%, inside the accepted band but above the
90% asked for: the intervals there are wider than they need to be.

**The point forecast lost the quietest half of zones, and the cause was the
loss, not the model (F-19b, decided 2026-11-13).** Fitted under squared error
— which estimates the MEAN — and judged by MAE — which rewards the MEDIAN — the
model lost to the seasonal-naive baseline in deciles 0–4 (0.16 against 0.02
trips an hour in decile 0) while the aggregate read +12.4%. Those zones are at
zero most hours: the mean is above zero and the median, like last week, is
zero. A scoring function must be consistent with the functional it scores
(Gneiting, 2011), so the forecast is now the **median per zone-hour**
(`train.POINT_LOSS = "absolute_error"`), and the service level a staffing
decision needs is read from the interval's upper bound, not from the point.
Under it the model beats the baseline in all ten deciles. Two alternatives were
measured and not taken: serving the baseline where it wins treats the symptom
and needs a second predictor and a re-calibration; and a relative skill floor
per decile divides by 0.02.

**The stated tolerance: no decile harmed.** The promotion gate refuses a model
when, in any volume decile, the baseline beats it by more than fold-to-fold
variation explains — the lower 95% bound of the MAE difference above zero
(`GROUP_HARM_CONFIDENCE`). Under the absolute-error loss the worst bound is
−0.0082 trips an hour (decile 0); under squared error it was +0.110, and the
model would have been refused. The folds overlap, so the interval is
approximate, and the gate is used to refuse on evidence of harm, not to certify
its absence; `MIN_SKILL` still requires the model to win in aggregate.

**Still not measured**:

- **By borough.** It needs a zone-to-borough mapping, which the registered
  datasets do not carry yet.
- **The six excluded zones.** They have less than 336 hours of history and
  receive no forecast at all. That is a distributional decision, even though it
  is made on data volume rather than on any protected attribute.
- **`ml_core.fairness` does not apply as-is.** It measures selection and error
  parity for classifiers. The regression analogue is the per-decile table
  above, which lives in `demand_forecast.train.BacktestReport.by_volume`.

## Failure modes

What it does when it is wrong, and what the system does about it.

| Failure | How it shows | What catches it today |
| --- | --- | --- |
| **Staleness** | Demand shifts and the model keeps predicting the old regime | `trained_through` on the artifact is the staleness clock — the timestamp of the last training row, not the file's mtime. Nothing alerts on it automatically |
| **A zone it does not cover** | A caller asks for a zone with too little history | `predict` fails rather than extrapolating from other zones. A loud failure, by design |
| **Intervals too narrow for a group of zones** | Coverage is met on average while a group is routinely outside its band | **The promotion gate**: Mondrian intervals are calibrated per volume decile, and a model whose worst decile covers below `MIN_GROUP_COVERAGE` (0.85) is refused. An individual zone inside a well-covered decile is still not guaranteed; see Fairness |
| **Distribution shift** | Inputs move away from what was fit — a new fare regime, a closed zone | `ml_core.drift` provides the contract and PSI comparison; it is **not wired to this model**. Stated rather than implied |
| **Silent metric inflation** | A comparison that flatters the model | **Corrected**, not only documented: skill was inflated 0.20pp because the model and the baseline were scored on different rows. Both are scored on the rows with a baseline now (`_score_fold`); a test built so the old calculation fails it, and mutation SF1 in the harness, hold that. The same re-measurement showed folds 0 and 1 losing to the baseline — see Evaluation |
| **No prediction at all** | The system cannot serve a forecast | The current state, by ADR-008. It is the honest headline failure mode: there is no endpoint |

The pattern worth naming: the failures with a mechanism behind them fail
**loudly** — an unknown zone raises, a schema mismatch refuses to load, a gate
below threshold blocks promotion. The ones with no mechanism are the quiet
ones, and they are listed here for that reason.

## Human oversight

Which decisions require a human, and what enforces that rather than expecting
it.

- **Promotion is gated on measurements, in code, by one rule.**
  `demand_forecast/promotion.py` refuses a model whose skill is below
  `MIN_SKILL = 0.05` or whose interval coverage falls outside
  `[MIN_COVERAGE, MAX_COVERAGE] = [0.85, 0.95]`, judged on a five-fold backtest
  (the design that includes the two folds this model loses). It reports every
  failure rather than the first — an operator who fixes skill to find coverage
  was failing all along has been told half the truth. The retraining DAG and
  the KFP pipeline both call it; each used to carry its own copy, and the
  copies disagreed on all three (W-14).
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
