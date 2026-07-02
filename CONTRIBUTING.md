# Contributing

Thanks for your interest in improving the platform. This guide keeps
contributions consistent and reviewable for teams.

## Ground rules

- **English only** for all code, comments, docstrings and documentation. The
  one exception is *use-case content* (customer-facing prompts/data), which may
  be in the use-case's target language — e.g. the `tienda` prompts are Spanish
  because the store serves Spanish-speaking customers.
- **Never fork `core/` for a new domain.** A new use-case is a new
  `usecases/<name>/` folder. If you find yourself editing `core/` to support a
  domain, that's a signal the seam is wrong — open an issue first.
- **Document non-trivial decisions** with an ADR in `docs/decisions/`.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # or: pip install -r requirements-dev.txt
pytest                          # unit tests (no model required)
```

## Adding a new use-case

See the full authoring guide: **[docs/usecases.md](docs/usecases.md)** (contract,
consumption modes, bring-your-own-models, no-scaffold-yet note).

In short: a new domain is a new `usecases/<name>/` folder (config + prompts +
grammar + `tools.py` with `build_registry` + data + policies + budgets + evals).
**Never fork or edit `core/`.** Run it with `AGENT_USECASE=<name> python -m app.main`.

## Quality gates (must pass before review)

- `pytest` green.
- `black .` and `isort .` (line length 120) — full repo surface, including
  `conftest.py`, `evals/`, `scripts/` (AUDIT R8-06; the old CI scope let
  these drift unnoticed).
- `flake8 .` and `mypy core app` clean.
- `python scripts/check_coherence.py` clean (version SSoT, ADR index,
  tag/release parity).
- Routing eval gate for your use-case: `python evals/run.py <set>.jsonl --usecase <name>`
  must score **≥ 90 %** intent accuracy (a ratio, not an absolute count —
  AUDIT R8-07; the runner exits non-zero on failure).

### Coverage policy (AUDIT R9 Anexo B — measure, don't gate, at this scale)

CI reports coverage (`pytest --cov`) as a build artifact; it does **not**
fail below a threshold. Rationale: at ~2k LOC with a single active
maintainer and a behavior-first test culture (119 tests exercising
contracts — the event-loop AST check, the policy gate, the reflection
notes channel — not line coverage), a numeric gate would either be
ceremony (already-high coverage) or an invitation to game it (padding
tests without real assertions to clear the bar). Instead:

- **Every PR with new code brings tests.** The reviewer evaluates
  coverage of the DIFF, not the global percentage.
- **The first gate, when one is warranted, will be diff-coverage** (e.g.
  ≥ 80 % of changed lines), never a global-percentage threshold — it
  protects new code without Goodhart-ing the existing suite.
- **Triggers to revisit this policy**: a second regular contributor joins,
  or a real bug ships that a coverage gate would have caught. Absent
  either signal, this stays a report, not a gate — the same calibration
  principle the sibling template applies everywhere else in this
  ecosystem.

## Commit / PR conventions

- Conventional-commit style subjects (`feat:`, `fix:`, `docs:`, `refactor:`…).
- Keep PRs focused. Describe what changed and how you verified it.
- CI runs unit tests + lint only. **Model-dependent evals run locally** by
  design (CI runners have no GPU/model access).

## What CI does NOT do

CI never runs the local LLM tiers. Self-hosted runners on a personal machine
over a public repo are a known attack vector and are intentionally avoided.
Model-quality evidence is produced locally and committed under `evals/reports/`
and `bench/RESULTS.md`.
