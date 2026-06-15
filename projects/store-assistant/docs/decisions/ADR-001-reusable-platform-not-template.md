# ADR-001: Reusable platform (core + use-cases), not a copy template

- **Status**: Accepted
- **Date**: 2026-06-15
- **Deciders**: Project owner

## Context

`agent-local` began as a single WhatsApp store assistant ("tienda"). The goal
is broader: teams should adopt it and reuse it across **multiple** domains
(other stores, other assistant verticals) with professional/enterprise rigor,
the same way the sibling `ML-MLOps-Production-Template` is adopted.

Two reuse models were on the table:

1. **Copy template** — scaffold a new repo per use-case (copy-paste-and-own).
   Each copy diverges; there is no central source of truth for the agent logic.
2. **Reusable platform** — a business-agnostic core consumed by thin per-domain
   configurations, distributed as a package and/or run as a service.

The valuable, hard-to-get-right assets are the **loop, the policy gate, the
objective escalation, and the grammar-constrained routing**. Those must stay
consistent across domains; divergence there is a liability, not a feature.

## Decision

Adopt the **reusable platform** model with a three-layer structure:

```
core/                 # business-agnostic engine (single source of truth)
usecases/<name>/      # thin config: prompts, grammar, tools, data, budgets, evals
app/                  # FastAPI transport; loads a use-case by AGENT_USECASE
```

- `core/` never contains domain text. It is config-driven via
  `core.config.UsecaseConfig` (prompts, grammar, tier endpoints, budgets,
  policy rules, prompt templates).
- A new domain is a **new `usecases/<name>/` folder** plus a `build_registry`
  function — never a fork of `core/`.
- Consumption paths: `from core import load_agent` (in-process) or HTTP (other
  apps call the running service / the local llama.cpp tiers on their ports).
- This repo stays **independent** from `ML-MLOps-Production-Template`. Merging
  the LLM-serving product into the tabular-ML template would contaminate both;
  a future "LLM-serving template variant" is a separate, post-1.0 track.

## Consequences

**Positive**
- Single source of truth for safety-critical logic (policy gate, loop).
- Adding a domain is cheap and low-risk; `core/` is reused, not copied.
- Clear seam enables packaging (`pip install`) and independent versioning.
- Tests isolate core contracts from use-case wiring.

**Negative / costs**
- Slightly more indirection than a flat app (a config layer + a loader).
- Use-cases must respect the contract (`build_registry`, `config.yaml` shape).

## Alternatives considered

- **Copy template**: rejected — divergence of safety logic across copies.
- **Merge into the MLOps template**: rejected — different product, lifecycle,
  dependencies and audience; the plan treats them as separate repos.

## Revisit triggers

- A second real use-case reveals that `core/` still needs domain edits → the
  seam is wrong; redesign the config contract.
- Demand for scaffolding new use-cases quickly → add an *optional* generator
  **on top of** the platform (not instead of it).
