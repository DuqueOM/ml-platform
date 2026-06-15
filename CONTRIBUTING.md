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

1. Create `usecases/<name>/` with:
   - `config.yaml` (endpoints, `allowed_intents`, policy rules, prompt templates)
   - `prompts/router.md`, `grammars/route.gbnf`
   - `tools.py` exposing `build_registry(config) -> ToolRegistry`
   - `data/` fixtures (or real API clients in Phase 2), `policies/*.md`
   - `budgets.yaml`, `evals/sets/*.jsonl`
2. Add `usecases/<name>/__init__.py` re-exporting `build_registry`.
3. Run it: `AGENT_USECASE=<name> python -m app.main`.

## Quality gates (must pass before review)

- `pytest` green; coverage should not regress.
- `black .` and `isort .` (line length 120).
- `flake8 .` and `mypy core app` clean.
- Routing eval gate for your use-case: `python evals/run.py <set>.jsonl --usecase <name>`
  must score **≥ 18/20** intent accuracy.

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
