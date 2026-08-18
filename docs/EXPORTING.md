# Exporting: duplicating a vertical

This monorepo is consumed by **duplicating a vertical**, not by forking the
repository. You generate the vertical you want as many times as you need, and
the shared substrate — `libs/`, `platform/`, `agentic/`, the gates — stays one
copy, shared by all of them.

That is the whole design. A fork gives you a snapshot; a duplicated vertical
stays connected to the generator that made it.

## What a vertical is

A directory under `projects/` holding one deployable ML system: its ingestion,
features, training, quality gates, contracts, tests and model card. What it is
**not** is a copy of the platform — it declares dependencies on `libs/` and
gets everything else by living in the monorepo.

`docs/PROJECT_CONTRACT.md` states the seven requirements every vertical meets.

## Duplicate one

```bash
uvx copier copy --vcs-ref HEAD --trust . projects/my-project
```

Answer the prompts — `project_slug`, `project_kebab`, `project_name`,
`project_kind`, `dataset_key`, `owner` — and you have a conforming vertical.

`project_kind` selects the quality gates that apply: `tabular` adds fairness
and calibration, `llm` and `agent` add retrieval quality and cost per request,
`deep-learning` adds inference latency. Choosing it wrongly gives you gates
that cannot be computed for your problem, which is worse than having none.

Then wire it into the derived documents:

```bash
uv run python scripts/check_implementation_status.py --write
uv run python scripts/check_technology_inventory.py --write
uv run pytest tests/test_project_contract.py -q
```

## What you get, and what is homework

Verified, not asserted:
`tests/test_project_generator.py::test_a_generated_vertical_satisfies_the_contract`
renders the template and runs the contract against the output.

| | On arrival |
| --- | --- |
| **P1** answers file, so `copier update` reaches it | ✅ |
| **P2** dependencies declared, none on a sibling project | ✅ |
| **P3** package named after the slug | ✅ |
| **P4** a test suite | ✅ |
| **P5** README | ✅ |
| **P7** model card | ✅ |
| **P6** quality gates | ❌ **deliberately** |

P6 is the homework, and it is deliberate. The generator ships
`threshold: TODO`, because a threshold copied from an example is an
undocumented decision — the first time it blocks something legitimate, whoever
is blocked lowers it, and nothing records that a decision was reversed.

Choose each number from **the cost of error in your problem**, name the check
that computes it, and write down why. `test_the_generated_gates_are_deliberately_unfilled`
asserts the TODOs are still there, so nobody can quietly fill the template with
plausible defaults to make new projects look compliant on arrival.

`projects/demand-forecast/evals/gates.yaml` is a worked example, including two
gates that were **removed** with the reason recorded — the generator's tabular
block gave it a disparate-impact gate, and a demand forecast has no protected
attribute for the ratio to divide.

## Do not copy the directory

`cp -r projects/demand-forecast projects/my-project` produces something that
looks right and is a fork. It has an answers file pointing at the wrong
project, so `copier update` will either refuse or merge the wrong thing, and
every generator improvement from then on has to be applied by hand.

The contract catches the obvious version of this (P1), not the subtle one. Use
the generator.

## Staying up to date

The generator improves. Pull those improvements into an existing vertical:

```bash
cd projects/my-project && uvx copier update --vcs-ref HEAD --trust
```

`--vcs-ref` is not optional. A bare `copier update` resolves to the
highest-sorting tag, which is how a service in the sibling template repository
was once updated to a frozen snapshot and destroyed. Check C9 in the coherence
gate fails on any unpinned copier command documented in this repository,
including the ones on this page.

## Taking a vertical out of the monorepo

You can, and you lose things. The vertical depends on `libs/` by workspace
path, so extracting it means either vendoring those libraries or publishing
them. It also leaves behind the shared substrate: the gates, the agentic
surface, the local stack, the CI that runs all of it.

The recommendation is to keep the monorepo and delete the verticals you do not
want. That keeps one copy of the substrate and one place where a fix lands.
