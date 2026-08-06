# Model card — {@ project_name @}

**Owner**: {@ owner @} · **Kind**: {@ project_kind @} · **Dataset**: `{@ dataset_key @}`

## Intended use

TODO — and, more importantly, the uses this model is **not** fit for. An
unstated limit is one a consumer will discover by violating it.

## Data

Source and licence: see `docs/datasets/register.md` for `{@ dataset_key @}`.

**Redistribution**: check the registry before publishing any derived artifact.
Several registered sources permit use but forbid redistribution, and that
distinction is a licence term, not a style preference.

## Evaluation

Thresholds and their rationale live in `evals/gates.yaml`. This section records
what was **measured**, with the method:

| Metric | Value | How it was measured |
|---|---|---|
| TODO | TODO | TODO — a number without its method is unverified |

## Fairness

TODO — which subgroups, on which attribute, measured how. Aggregate metrics
average away the subgroup where a model fails systematically.

## Failure modes

TODO — what this model does when it is wrong, and what the system does about
it. A model with no stated failure mode has an undocumented one.

## Human oversight

TODO — which decisions require a human, and how that is enforced rather than
expected.
