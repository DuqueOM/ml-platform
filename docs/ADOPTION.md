# Adopting this platform

Who this is for, what arrives working, what is yours to do, and what it
deliberately does not claim.

Read `llms.txt` first if you are an agent. Read this if you are deciding
whether to build on it.

## What you are adopting

A monorepo where several ML systems share one substrate and each system is a
**vertical** under `projects/`. You adopt it by keeping the substrate and
generating the verticals you need — not by forking and diverging.

| Layer | You get | You own |
| --- | --- | --- |
| `libs/` | Five libraries: conformal prediction, data contracts, point-in-time feature joins, retrieval evaluation | Extending them, downward-only |
| `platform/` | Terraform for two clouds, Kustomize overlays, a kind-based local stack, policies | Your accounts, your networks, your identities |
| `orchestration/` | Airflow for business flow, KFP for ML compute | Your schedules and your gates' numbers |
| `agentic/` | 23 rules, 29 skills, 22 workflows, rendered to four tool surfaces | Nothing — edit the canonical source, never a rendered pointer |
| `scripts/` | The gates | Adding yours; they must be able to fail |
| `projects/` | Two worked verticals | Every vertical you generate |

## The three things that make it different

**Duplication, not forking.** `templates/project/` is a copier generator, and
`docs/EXPORTING.md` is the procedure. A duplicated vertical keeps its
`.copier-answers.yml`, so a later fix to the generator reaches it through
`copier update`. A copied directory does not, and is a fork with extra steps.

**A contract every vertical meets.** `docs/PROJECT_CONTRACT.md` states seven
requirements, enforced by `tests/test_project_contract.py`. It is what makes
`projects/` a platform rather than three folders that look similar. Deviations
are recorded with what would close them, and they expire: an exemption for
something now satisfied fails the suite.

**Claims carry the layer they are proven at.** L1 contract, L2 component,
L3 cluster, L4 cloud — derived from the command that ran, never declared. The
status document cannot display L3 or L4, because CI has neither. This matters
to you specifically: it means you can read what is genuinely proven instead of
inferring it from a green badge.

## What arrives working, and what is homework

Generate a vertical and it satisfies six of the seven contract requirements
immediately. The seventh does not, on purpose.

A generated `projects/<name>/evals/gates.yaml` ships with
`threshold: TODO`. A threshold copied from an example is an undocumented decision — the first time it blocks something
legitimate, whoever is blocked lowers it, and nothing records that a decision
was reversed. **Choose each number from the cost of error in your problem**,
name the check that computes it, and write down why.

`projects/demand-forecast/evals/gates.yaml` is the worked example, including
two gates that were **removed** with the reason recorded: the generator's
tabular block gave it a disparate-impact gate, and a demand forecast has no
protected attribute for the ratio to divide. Removing an inapplicable gate is
not lowering a standard; keeping it would have been a gate that passes by being
uncomputable.

## Tool adoption is tiered, and the tier is the point

`docs/decisions/ADR-004-tooling-triage.md` classifies every technology:

- **Adopted** — needs an ADR, a gate and a runbook
- **Demonstrated** — one narrow use, with its reason
- **Studied** — documented, not used

Adopt broadly at *Demonstrated*. A tool promoted to Adopted without a gate is a
dependency with no owner, and the count of technologies in a stack is not a
quality signal — this repository has 31 declared gates and tracks the ones that
have no coverage rather than hiding them.

## What this does NOT claim

Stated plainly, because a platform that hides its gaps costs you the time you
spend discovering them.

**Nothing here has ever run in a cloud.** Zero components at L4. The Terraform
for GKE and EKS renders and validates offline; it has never provisioned
anything. The sequencing constraint in the technical plan says it will not
until everything else is finished, and that is a deliberate choice about where
discovery happens, not an oversight.

**Checkov reports and does not block.** 114 findings under `platform/`, roughly
36 of them a scan-scope artifact and the rest real gaps in both clouds'
Terraform — no private nodes, no master authorized networks, no network policy,
no binary authorization, no EKS secrets encryption. `SECURITY.md` lists which
controls block and which are advisory, and a test compares that table against
the workflows on every commit.

**The generated service is a binary classifier.** `services/` comes from
`ml-service-template`, whose serving path is classification by construction.
`demand-forecast` is a regression with a conformal interval, so the two do not
meet — recorded in `docs/decisions/ADR-008-serving-a-forecast-from-a-classification-scaffold.md`
as Proposed, because the resolution is an upstream change. If your first
project is a classifier, this does not affect you.

**The independent audit is overdue.** Check C7 fails, by design: an audit must
run in a session separate from the work, because self-review cannot find a fact
its author believed. A red C7 is the mechanism working, not a broken build —
but it is red, and you should know before you rely on the governance claims.

## Whether it is working for you

Three signals, in order of how much they mean:

1. **A gate you added has failed and stopped something.** Until that happens
   you have a test suite, not a guardrail.
2. **A vertical you generated needed no substrate changes.** If it did, the
   contract is missing a requirement — say which.
3. **The derived documents disagreed with someone's belief, and the documents
   were right.** That is the whole design paying off.

If none of the three has happened after a few months, the honest reading is
that the governance layer is costing more than it returns for your scale.
`docs/architecture/technical-plan.md` states the calibration rule this repo
holds itself to: match solution complexity to problem scale. It applies to
adopting this as much as to building it.

## Getting started

```bash
uv sync --all-packages --all-extras
uv run pytest -q
uvx copier copy --vcs-ref HEAD --trust templates/project projects/my-project
uv run pytest tests/test_project_contract.py -q
```

`CONTRIBUTING.md` has the cadence and the order that bites,
`docs/EXPORTING.md` how to duplicate a vertical properly, and
`docs/PROJECT_CONTRACT.md` what every vertical must expose.

`QUICK_START.md` is the first ten minutes, `RUNBOOK.md` what to do when a gate
fails. For what is still owed rather than done, read
`docs/governance/upstream-parity.yaml` — it decides every artifact this
platform's upstream has, as adopted, pending or rejected with the argument.
