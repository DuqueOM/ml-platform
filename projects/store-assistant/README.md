# store-assistant

A WhatsApp store assistant, and the reference consumer of `libs/llm-core`.

It answers customer questions about inventory, prices, orders and store policy
over fixture data. What makes it worth reading is not the domain: it is that
**every mechanism comes from the library and every piece of content comes from
here**, so the boundary `libs/` claims is demonstrated rather than asserted.

## Run it

```bash
uv sync --all-packages --all-extras
uv run pytest projects/store-assistant -q
```

The suite needs no model, no network and no keys. Every tier client is a
scripted double, which is the point: what this project promises is what the
loop does when the model is wrong, and that has to be assertable without one.

To drive the real loop you need llama.cpp endpoints; see
[store-ADR-011](docs/decisions/store-ADR-011-hybrid-tier-topology.md) for the
three profiles (local-only, hybrid, all-remote) and the environment variables
that select between them. One committed configuration serves all three.

## What lives here, and what does not

| Here | In `libs/llm-core` |
| --- | --- |
| `config.yaml` — tiers, budgets, intents, prompts | Tier routing and the client |
| `policies/policy.yaml` — the rules, as versioned data | The policy ENGINE that evaluates them |
| `tools.py` — inventory, pricing, alias and order tools | The registry and its capability contract |
| `prompts/`, `grammars/`, `data/` | Verification, telemetry, circuit breakers |

The split is [ADR-002](../../docs/decisions/ADR-002-absorbing-agent-local.md)'s
placement decision. It is also the test
[ADR-001](../../docs/decisions/ADR-001-monorepo-topology.md) rule 3 asks for:
*"a library shaped by one caller is a library the second caller bends around."*
This project takes the library unchanged — no subclassing, no patching, no
import of a private name.

## The gates

`evals/gates.yaml` declares three, all blocking, each naming the test that
computes it:

- **injection_containment** — zero bypasses, driven by a model that has already
  been fooled;
- **tool_capability_contract** — zero mutating tools reachable without
  approval, fail-closed by construction;
- **policy_rules_are_versioned** — the policy file carries a semver version, so
  its diff is a dated record of what the assistant may say.

## Its own decision records

Twelve, in `docs/decisions/`, numbered `store-ADR-NNN`. They were written in
`agent-local` before the migration and renumbered into this project's namespace
because their blast radius is this project, not the platform. The mapping and
the reasoning are in [that directory's README](docs/decisions/README.md), and
the original commits are on the `history/agent-local` branch.

## Language

The prompts and policy content are **Spanish on purpose** — this use-case
serves Spanish-speaking customers. That is use-case content, not engineering
documentation, and the distinction matters here: the platform's own
documentation is English without exception.
