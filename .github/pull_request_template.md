<!-- Four questions. CI already reports lint, types, coverage, doc coherence and
     agentic-surface drift, so none of them are asked again here — this template
     asks only for what a machine cannot check for you. -->

## What and why

<!-- One paragraph. The "what" is in the diff; the "why" is the part review
     cannot reconstruct later, and it is usually the measurement that led to the
     choice. If the decision was non-trivial, link the ADR that records it. -->

## Class

<!-- CONTRIBUTING.md § "AUTO, CONSULT, STOP". Keep one line, delete the others.
     If you are wondering which it is, it is at least CONSULT. -->

- **AUTO** — reversible and local.
- **CONSULT** — crosses a boundary: a public API in `libs/`, `services/` (upstream by ADR-003), another repository, a cloud resource. Say what you proposed and what came back.
- **STOP** — lowers a quality gate, deletes or renumbers an ADR, or is destructive. Link the recorded decision, with a name on it.

## Evidence

Paste the command you ran and enough of its real output to be checkable. Not a description of a run, and not "tests pass" — CI says that itself.

```text
$
```

**Layer this evidence reaches** — see `docs/architecture/implementation-status.md` § "The layer a claim is proven at":

- [ ] **L1** — contract: the test suite passes
- [ ] **L2** — component: the thing itself executed — a generator rendered, a gate ran, a build completed
- [ ] **L3** — cluster: it started and answered in kind
- [ ] **L4** — cloud: a real rollout on GKE or EKS

CI has no cluster and no cloud, so L3 and L4 cannot be produced by this PR's checks. Ticking one means naming where it ran; an unattributed L3 is an L2 with ambition. Six overlays here were green for weeks with probes pointing at routes the service does not serve, which is precisely the gap between L1 and L3.

## If this adds or changes a gate

A gate is only worth having if it can fail. Two in this repository passed while examining zero files — a coherence filter matching absolute paths, and a mypy override matching no modules — and both were found only by trying to break them.

- **What you broke to make it fail**:
- **The failure it produced** (paste it):
- **Commit that records the verification**:

## Derived documents

If this adds a component, a technology, or cloud-specific code, regenerate them — `git add -A` **first**, because the generators read what git knows about and generating before staging describes a repository without your new directories.
