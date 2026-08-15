# Progression: the order to take this platform in

`docs/ADOPTION.md` answers *what is this and should I use it*. `QUICK_START.md`
answers *how do I get something running in the first hour*. This answers the
question between them: **in what order do I take the pieces, and how do I know
a stage is actually finished rather than merely set up?**

Six stages. Each names what you take, what it unlocks, and — the part that
matters — a command whose passing is the evidence you have finished it. A
stage you cannot demonstrate with a command is a stage you have read about.

Stages are cumulative and skippable in one direction only. Skipping ahead is
allowed and sometimes correct; skipping back to fill a gap costs more than
doing it in order, because later stages assume the earlier ones' guarantees.

---

## Stage 0 — Run the gates you did not write

**Take:** nothing. Clone and run.

```bash
uv sync --all-packages --all-extras
make verify
```

**Unlocks:** a baseline. Everything after this is measured as a change from a
suite you have seen pass on your own machine.

**Finished when:** `make verify` is green and you have read
`docs/architecture/implementation-status.md`. That document is generated from
the filesystem, not maintained by hand, so it is the one place where what the
repository claims and what it contains cannot drift apart.

**What goes wrong here:** treating a green suite as evidence about *your*
problem. It is evidence about the substrate. At this stage you have proven
that somebody else's tests pass.

---

## Stage 1 — One vertical, with your numbers in it

**Take:** the copier generator.

```bash
uvx copier copy --vcs-ref HEAD --trust templates/project projects/my-project
uv run pytest tests/test_project_contract.py -q
```

**Unlocks:** the contract in `docs/PROJECT_CONTRACT.md`. Six of its seven
requirements are satisfied the moment the generator finishes.

The seventh is not, deliberately: `projects/<name>/evals/gates.yaml` ships
with `threshold: TODO`. A threshold copied from an example is an undocumented
decision, and the first time it blocks something legitimate, whoever is
blocked lowers it — with nothing recording that a decision was reversed.
Choose each number from the cost of error in your problem, name the check that
computes it, and write down why.
`projects/demand-forecast/evals/gates.yaml` is the worked example, including
two gates that were *removed* with the reason recorded.

**Finished when:** the contract test passes with no exemption you cannot argue
for, and every threshold has a number and a sentence.

**What goes wrong here:** copying `projects/demand-forecast/` instead of
generating. A copied directory has no `.copier-answers.yml`, so later fixes to
the generator never reach it. That is a fork with extra steps, and
`docs/EXPORTING.md` exists to prevent it.

---

## Stage 2 — A pod that answers, on your machine

**Take:** the local stack.

```bash
make local-preflight   # does it fit in memory before creating anything?
make local-up
make local-serve
make local-verify
```

**Unlocks:** L3 evidence — the first claim you can make that is about a
running system rather than a passing test.

**Finished when:** `make local-verify` passes. Note what that target asserts:
that the stack *works*, not that it *started*. The distinction is not
pedantic. Six overlays in this repository rendered green for weeks while their
readiness probes named routes the service does not serve, so no pod could ever
have reached Ready — and every check that looked at them passed, because they
all asked whether the manifest was valid and none asked whether the route
existed.

**What goes wrong here:** stopping at `make local-up`. A stack that is up is
a stack that consumed memory.

---

## Stage 3 — A gate of yours has failed and stopped something

**Take:** authorship of the guardrails.

Add a gate to `scripts/`, declare it, wire it into CI, and — the step that is
usually skipped — **write the test that breaks what it guards**. Construct the
bad condition and assert your gate fails on it.

**Unlocks:** the difference between a test suite and a guardrail. This
repository names the failure mode P-09: *a gate that passes because the thing
it checks is absent*. Every gate here has been caught doing it at least once,
which is why the rule is now that a gate is not accepted until it has been
seen to fail.

**Finished when:** a gate you wrote has blocked a commit you wanted to make,
and you did not weaken it. Until that happens, this stage is incomplete no
matter how many gates you have added.

**What goes wrong here:** a gate that cannot fail, and the six spellings of CI
suppression — step-level `continue-on-error`, job-level `continue-on-error`,
`soft_fail`, `exit-code: "0"`, `if: false`, and a trailing `|| true`. All six
turn a red check green while leaving the badge intact.
`tests/test_security_controls.py` knows all six because each was found in use.

---

## Stage 4 — A second vertical that needed nothing from you

**Take:** the generator again, for a different problem shape.

**Unlocks:** the actual claim of a platform. One vertical proves a project;
two verticals that share a substrate without either bending it prove the
substrate.

**Finished when:** you generated a second vertical and changed **nothing**
under `libs/` or `platform/` to make it work. If you did have to change
something, the contract is missing a requirement — say which one, in
`docs/PROJECT_CONTRACT.md`, rather than patching around it locally.

**What goes wrong here:** the abstraction pulled forward. Extracting a shared
module while exactly one consumer exists produces a library shaped like one
caller, and the second caller then bends around it. Wait for the second
consumer; the duplication is cheaper than the wrong seam.

---

## Stage 5 — Cloud

**Take:** `docs/environment-promotion.md`, and read its first section before
anything else.

**Nothing in this repository has ever run in a cloud.** Zero components at L4.
The Terraform for GKE and EKS renders and validates offline and has never
provisioned anything, there is no deploy workflow, and the six cloud overlays
have never been applied. That is a deliberate sequencing choice — cloud is
where discovery is most expensive, and a defect found at L1 is a defect not
found at L4 with a bill attached — but it means this stage is the one where
you are ahead of the platform rather than following it.

**Finished when:** you have walked `docs/environment-promotion.md`'s five
prerequisites: a deploy workflow that pins images by digest, environment
protection rules, per-environment Terraform state, a *rehearsed* rollback, and
cloud identity with no static credentials.

**What goes wrong here:** promoting by tag. The `:latest` that passed in
staging is not necessarily the `:latest` that starts in production.

---

## How to tell whether the whole thing is working for you

Three signals, in ascending order of how much they mean. They are the same
three as in `docs/ADOPTION.md`, restated here as an endpoint rather than an
introduction:

1. **A gate you added has failed and stopped something.** Stage 3's finish
   condition, and the first real one.
2. **A vertical you generated needed no substrate changes.** Stage 4.
3. **A derived document disagreed with someone's belief, and the document was
   right.** This is the design paying off, and it is the only signal that
   cannot be manufactured by adding more checks.

If none of the three has happened after a few months, the honest reading is
that the governance layer costs more than it returns at your scale. The
calibration rule this repository holds itself to — match solution complexity
to problem scale — applies to adopting it as much as to building it.

## Related

- `docs/ADOPTION.md` — what you are adopting, and what it refuses to claim
- `QUICK_START.md` — stages 0 through 2, as one continuous session
- `docs/PROJECT_CONTRACT.md` — the seven requirements every vertical meets
- `docs/EXPORTING.md` — duplicating a vertical without forking it
- `docs/environment-promotion.md` — stage 5 in full
- `RUNBOOK.md` — what to do when a gate fails
