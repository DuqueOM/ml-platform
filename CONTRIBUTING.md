# Contributing

The unusual thing about this repository is not its stack. It is that **most of
its rules are executable**, so contributing mostly means running them and
reading what they say.

## Before anything

```bash
uv sync --all-packages --all-extras
uv run pytest -q
```

If that does not pass on a clean checkout, that is a bug and worth reporting on
its own.

## The cadence, in this order

Order matters and the reason is specific.

```bash
git add -A                                              # 1. stage FIRST
uv run python scripts/check_implementation_status.py --write
uv run python scripts/check_technology_inventory.py --write
uv run python scripts/measure_cloud_surface.py --write
uv run ruff format . && uv run ruff check . && uv run mypy libs/ scripts/
uv run pytest -q
uv run python scripts/check_doc_coherence.py
uv run python scripts/check_upstream_parity.py
```

**Stage before regenerating.** The derived documents are built from what git
knows about, so generating before `git add` describes a repository without your
new directories — and CI, where they are tracked, then calls the committed
document stale. That failure has happened here, and the diff it produced was
confusing enough to be worth this paragraph.

## What the derived documents are

Three documents are generated and must never be hand-edited:

| Document | Derived from |
| --- | --- |
| `docs/architecture/implementation-status.md` | The filesystem plus each component's verification command |
| `docs/architecture/technology-inventory.md` | Detected use of each declared technology |
| `docs/architecture/cloud-surface.md` | The ratio of cloud-specific to cloud-agnostic code |

The technical plan states **intent**; the status document states **what
exists**. When they disagree, the derived one is correct. Editing a tick into
the status table does not make something true, and CI will notice.

## Adding a gate

A gate is only worth having if it can fail. So:

1. Write it.
2. **Break the thing it guards, and watch it fail.** Then put it back.
3. Record that verification in the commit message.

This is not ceremony. A coherence filter that matched absolute paths examined
zero files and passed; a mypy override that matched no modules enforced nothing
and stayed green. Both were found by trying to make them fail, and neither
would have been found any other way.

If your gate has a threshold, add it to `scripts/check_thresholds.py`. Numbers
that gate a build may rise and may not fall — lowering one is a STOP operation
and needs a recorded reason.

## Adding a project

Generate it; do not copy a directory. `docs/EXPORTING.md` has the procedure and
`docs/PROJECT_CONTRACT.md` has the seven requirements every vertical meets. A
copied project has an answers file pointing at the wrong thing, so
`copier update` can never reach it again.

## AUTO, CONSULT, STOP

Changes are classified by blast radius, and the classification decides whether
you proceed alone.

| Class | Meaning |
| --- | --- |
| **AUTO** | Reversible and local. Proceed. |
| **CONSULT** | Crosses a boundary — a public API in `libs/`, another repository, a cloud resource. Propose, then wait. |
| **STOP** | Lowering a quality gate, deleting or renumbering an ADR, anything destructive. Needs a recorded decision with a name on it. |

The two checkable STOP cases have gates behind them. The rest is judgement, and
the honest guidance is: if you are wondering which class it is, it is at least
CONSULT.

## Decisions

Anything non-trivial gets an ADR in `docs/decisions/`, with the alternatives
you rejected and why. An ADR is never deleted or renumbered — a decision that
turns out wrong is **superseded** by a new one, so the reasoning survives. The
coherence gate enforces this against git history, not against the index, because
the index can be edited in the same commit as the deletion.

Write the trade-off you actually made, including the one that looks bad. An ADR
that only lists advantages is a decision nobody can revisit.

## Style

Ruff for lint and format, line length 120. Mypy strict on `libs/`. Google-style
docstrings, type hints on public functions, `~=` for ML pins — `numpy 2.x`
corrupts joblib artifacts, which is the kind of thing a pin exists for.

Comments explain **why**, not what. The what is in the code; the why is the
part that gets lost, and it is usually the measurement that led to the choice.

## Language

English, everywhere in the repository. It is public, and a mixed-language
codebase is one that half its readers can only half read.

## Reporting a vulnerability

See [SECURITY.md](SECURITY.md). Please do not open a public issue for one.
