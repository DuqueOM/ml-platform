# Model card — store-assistant

## What this is

A multi-tier agent, not a trained model. There are no weights in this
repository and nothing here was fitted to data. What the card describes is the
**system**: which models it routes to, what it is allowed to do with their
output, and where it fails.

That distinction is the first limitation, and it is the important one. A model
card for a fine-tuned classifier documents a thing you control. This documents
a thing you rent, wrapped in a thing you built — and only the wrapper carries
guarantees.

## Components

| Tier | Role | Model |
| --- | --- | --- |
| 0 | Routing and guardrail, grammar-constrained | A small local model over llama.cpp |
| 1 | Mid reasoning | Configured per environment |
| 2 | Main assistant | Configured per environment |
| 3 | Verification judge | Configured per environment |

No model is named here on purpose: `config.yaml` selects them per environment
and [store-ADR-011](docs/decisions/store-ADR-011-hybrid-tier-topology.md)
describes the three profiles. A card that named one would be wrong in two of
the three.

## Intended use

Answering customer questions about a store's inventory, prices, orders and
policies, over data the tools return. **Read-only by default**: the tool
registry refuses a mutating tool unless the use-case declares phase 2
(`store-ADR-006`), and order creation is hard-coded dry-run.

## Out of scope

Anything the tools do not cover, and anything requiring a commitment: delivery
promises, discounts, and availability claims are checked against what a tool
actually returned, not against what the model believes.

## What is guaranteed, and by what

The guarantees are the deterministic layer's, never the model's:

- **A claim needs evidence.** A price, a stock assertion or a promotion in the
  response requires a successful matching tool call in the same turn, or the
  response is replaced by a safe fallback.
- **Banned commitments are banned outright**, independent of how the model was
  persuaded.
- **Self-contradiction is detected** — asserting availability and
  unavailability of the same thing is a verdict, not a style issue.
- **Tools fail closed**: an unregistered tool name, or arguments that fail
  validation, are refused before anything executes.

Each is asserted with a model that has already been fooled — a scripted double
emitting the injected instruction — so what the tests measure is containment,
never the model's judgement.

## Limitations, measured

- **The model's judgement is not a control.** Nothing here makes the model
  truthful; the policy gate makes an untruthful answer undeliverable in the
  cases it recognises. Cases it does not recognise pass.
- **The rule data is domain-specific and finite.** The keyword lists in
  `policies/policy.yaml` were written for this store's vocabulary. A claim
  phrased outside them is not caught, which is the cost of rules that are data
  rather than a model.
- **Verification is bounded.** Self-consistency runs at k=1 for high-risk
  routes only (`store-ADR-004`) — a deliberate cost decision, and it means a
  confident wrong answer at low risk reaches the policy gate as the only check.
- **Retrieval is BM25 over the use-case's own documents.** No embeddings, no
  reranking; a question phrased in vocabulary the documents do not use will
  retrieve nothing relevant and the assistant will say so rather than invent.
- **Language.** Prompts and rules are Spanish. Behaviour in another language is
  undefined and untested.

## Data

Fixture files under `src/store_assistant/data/` — inventory, prices, orders and
aliases. They are synthetic and small, chosen so the suite runs offline. **No
customer data has ever been in this repository**, and the telemetry sink
redacts PII at write time (`store-ADR-005`) rather than after.

## Evaluation

`evals/gates.yaml` declares three blocking gates, each naming the test that
computes it. They measure containment and contract, not answer quality:
answer-quality evaluation needs a live model and is gate A2 in
`docs/governance/quality-gates.md`, recorded there as pending for exactly that
reason.
