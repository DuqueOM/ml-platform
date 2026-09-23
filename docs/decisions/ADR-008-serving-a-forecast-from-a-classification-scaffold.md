# ADR-008 — The generated service cannot serve this platform's first project

- **Status**: Proposed
- **Date**: 2026-08-10

## Context

Phase 1c of the technical plan exists because rendering a manifest is not
running a service. Its first step was going to be a `Dockerfile`. Before
writing one, the thing it would containerise was read — and it does not fit
the project it is deployed for.

`services/demand-forecast-serving/` is scaffolded from `ml-service-template`
and is authoritative for serving under ADR-003 §2. Its prediction path is
binary classification, not by default but by construction:

| Where | What it commits to |
| --- | --- |
| `app/schemas.py`, `PredictionRequest` | `feature_a: float`, `feature_b: float`, `feature_c: str` — the template's example row |
| `app/schemas.py`, `PredictionResponse` | `prediction_score: float = Field(ge=0, le=1)` and `risk_level: LOW/MEDIUM/HIGH` |
| `app/fastapi_app.py` | `_model_pipeline.predict_proba(...)[:, 1]` in inference, in warm-up, and in the SHAP wrapper |

`projects/demand-forecast/` predicts hourly demand per zone: a **regression
over time**, evaluated by expanding-window backtest, with a conformal
prediction interval. A probability bounded to `[0, 1]` cannot carry a taxi
count, and `risk_level` has no meaning for it.

Two further facts, both verifiable:

- **A model artifact exists, and the container cannot load it.** This bullet
  said nothing calls `joblib.dump`; `projects/demand-forecast/src/demand_forecast/persist.py`
  does, pickling a `ForecastModel` that wraps
  `ml_core.conformal.SplitConformalRegressor`. The service image installs no
  workspace library — `services/demand-forecast-serving/requirements.txt`
  names no `ml-core` — so loading fails with `ModuleNotFoundError: No module
  named 'ml_core'` before any version is compared. QA-4 round eleven
  reproduced it against an image built from the service's own Dockerfile.
  This is a second, independent reason the service cannot serve this project,
  and it belongs to the interface decision below: either the image installs
  the workspace libraries the artifact references, or the artifact stops
  pickling workspace types. `scripts/check_artifact_compatibility.py` (gate
  P14) compares versions across that seam and does not detect it.
- **The manifests already name the image.** `platform/kubernetes/base/deployment.yaml`
  deploys `ghcr.io/duqueom/ml-platform/demand-forecast:set-by-deploy-pipeline`
  — a placeholder tag, not an image — with readiness on `/ready` and liveness
  on `/health`, across six overlays. This bullet said `:latest` and
  `/health/ready`, neither of which the base Deployment carries. All of it renders. None of it has
  ever run.

This is the shape every audit of this repository has found: the declared
mechanism is not the operating mechanism. It was found here by trying to
start the thing, which is exactly what Phase 1c was added to force.

## Decision

**Proposed, not accepted — the resolution is a cross-repository change and
that is a CONSULT-class decision.** What follows is the recommendation.

1. **The template stays authoritative.** ADR-003 §2 is not renegotiated
   because it is inconvenient. A serving loop for regression belongs in
   `ml-service-template`, reached by a copier question (`task_type:
   classification | regression`) that selects the response schema, the
   `predict` vs `predict_proba` call, and the SHAP explainer. The service is
   then **regenerated**, not edited.
2. **`libs/serving-core` does not grow a serving loop.** ADR-003 §4 makes that
   the definition of the boundary failing, and "the template did not support
   our case yet" is precisely the pressure it was written to resist.
3. **The scaffold is not hand-edited into a forecaster.** Filling in the
   example feature names is the customisation the template invites. Replacing
   `predict_proba` with `predict` in three places, changing the response
   contract and swapping the explainer is not customisation; it is a fork that
   `copier update` would fight on every upgrade.
4. **Persisting the trained model is platform work and is not blocked.**
   Under every option above, `train.py` must write a versioned artifact that
   something can load. That proceeds now.

## Consequences

### Positive

- Phase 1c stops being blocked by an unstated assumption and becomes blocked
  by a named one, with an owner.
- The template gains regression support, which every later project in this
  platform that is not a classifier will need.

### Negative

- Phase 1c cannot complete until the upstream change lands. That is a real
  delay and it is the price of ADR-003 rather than a surprise.
- The six overlays and the Deployment stay unproven for longer. They are
  already unproven; only the documentation of that changes.

### Neutral

- The `local` validation stack and the Dockerfile remain useful work, and both
  are reachable before the upstream change — an image that starts and reports
  `/ready` against a stub is still the first time anything here starts.

## Alternatives considered

- **Serve the forecast through the classification contract**, mapping demand
  into `[0, 1]`. Rejected: it distorts the problem to fit the tool, and the
  first person to read `prediction_score` would take it for a probability.
- **A second serving stack in `libs/serving-core`.** Rejected by ADR-003 §4.
  It is also how a platform ends up with two serving loops and one of them
  untested.
- **Make the platform's first deployable a classifier instead.** Rejected: it
  would make the mismatch disappear from view without resolving it, and the
  next project would rediscover it.

## Progress, 2026-09-22 — the artifact is portable; the schema mismatch is not resolved

**Status stays `Proposed`, deliberately.** One half of what this ADR records
has been fixed, and flipping the status would assert the other half was too —
and would lift the exemptions gate P14 holds against this document, turning it
red on straddles nobody has addressed.

What changed: the artifact no longer pickles workspace objects. It carried
`demand_forecast.persist.ForecastModel` wrapping
`ml_core.conformal.SplitConformalRegressor`, so reading it required both
packages installed, and the serving image installs neither — the load failed
with `ModuleNotFoundError` before any version was compared. It now carries a
scikit-learn estimator and data: the conformal regressor travels as the two
numbers calibration produces, and `load` rebuilds it. A reader needs
scikit-learn, numpy and joblib, which the image has.
`projects/demand-forecast/tests/test_artifact_portability.py` asserts that the
artifact's BYTES name no workspace package, and that a container-shaped reader
gets predictions and intervals without importing anything from here.

What has not changed, and is what keeps this Proposed: the scaffold's
prediction path is still binary classification, its response schema still
carries `prediction_score` bounded to [0, 1] and `risk_level`, and a demand
forecast still does not fit through it. That is a cross-repository change and
a CONSULT-class decision, exactly as recorded above.

## Revisit triggers

- `ml-service-template` gains a `task_type` question — this ADR moves to
  Accepted and Phase 1c unblocks.
- A second non-classification project is added here before that lands, which
  would raise the cost of waiting above the cost of a documented override.

## Related

- [ADR-003](ADR-003-service-template-consumption.md) — the template is upstream
  for serving; this is the first case where its scope does not cover a project.
- [ADR-004](ADR-004-tooling-triage.md) — Adopted tooling needs a gate; a
  serving path with no running instance has none.
- `docs/architecture/technical-plan.md`, Phase 1c.
