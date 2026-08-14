---
description: Restore and verify cross-document coherence — version, CHANGELOG, ADRs, READMEs, llms.txt, agentic surface counts (rule 16, template-ADR-031)
---

# /doc-coherence Workflow

Run after any change that touches a fact restated across documents (a new ADR,
a new rule/skill/workflow, an anti-pattern, a version bump). The gate is the
authority; this workflow is the procedure that makes it green.

## 1. Run the coherence gate

```bash
python3 scripts/check_doc_coherence.py
```

// turbo

Exit 0 → done. Exit 1 → note each `[C1..C5]` violation and continue.

## 2. Apply the cascade map (rule 16)

For each violation, fix the SSoT first, then propagate to mirrors:

These are the checks `scripts/check_doc_coherence.py` performs **in this
repository**. The list here previously described ml-service-template's
numbering, carried across unchanged when the workflow was ported: an agent
following it would have looked for a version check under C1 and a `D-NN`
count under C3, and found neither. Same identifiers, different meanings,
which is worse than no list.

- **C1** ADRs on disk ⇄ the index, and none removed since git HEAD.
- **C2** no document references an ADR number that does not exist.
- **C3** accepted ADRs are integrated rather than orphaned.
- **C4** every quality-gate row carries a command that resolves — a script that
  exists, or a tool some workflow actually invokes.
- **C5** the agentic surface counts, and every skill has a `SKILL.md`.
- **C6** no private name appears in any file, matched against hashes.
- **C7** the independent audit has not gone stale (ADR-005 rule B).
- **C8** `[Unreleased]` in the CHANGELOG covers the commits since the last tag.
- **C9** every documented `copier` command names a pinned template version.

Version consistency across `VERSION`, `pyproject.toml`, `llms.txt`, the
CHANGELOG and the plan header is a SEPARATE gate:
`scripts/check_version_consistency.py`. It exists because the line above
claimed C1 did that job and nothing did.

> Prefer the `doc-coherence` skill — it knows the cascade map and the
> CONSULT/STOP boundaries (never renumber an ADR; never rewrite a released heading).

## 3. Regenerate adapters (if `agentic/` changed)

```bash
python3 scripts/sync_agentic_adapters.py
```

## 4. Verify everything is green

```bash
python3 scripts/check_doc_coherence.py            # [doc-coherence] OK
python3 scripts/sync_agentic_adapters.py --check  # adapter parity
python3 scripts/validate_agentic_manifest.py --strict
```

## 5. Commit with traceability

Reference the ADR / PR in the commit body so the change stays relatable
end-to-end (decision → ADR → CHANGELOG → release → VERSION).

## Related

- Rule: `23-doc-coherence` · Skill: `doc-coherence` · template-ADR-031
- Workflow: `release` (downstream — consumes a coherent tree)
- Workflow: `new-adr` (upstream — produces an ADR that this workflow propagates)
