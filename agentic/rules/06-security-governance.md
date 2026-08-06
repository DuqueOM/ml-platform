# 03 — Security and secrets

**Authority**: `AGENTS.md`
**Applies to**: every committed file

## Credentials

- **No credential in any committed file.** Configuration references a
  **variable name**; the value lives in the environment or a secret manager.
  A config naming `PROVIDER_API_KEY` is correct; one containing a key is a P1.
- **Workload identity federation only** — no static cloud keys.
- Secrets are validated at **startup**, not at first use. A missing credential
  discovered per-request is absorbed by degradation paths, and the service
  looks healthy while serving nothing.
- Secret scanning runs **over commits, not the working tree**. The working tree
  cannot show what history already published.

## Supply chain

Images pinned by digest, signed, SBOM-attested, verified at admission. An
unverifiable image forfeits the entire chain.

## This repository is public

No private business context, personal project, client data, or internal URL.
Documentation is English; non-English content is permitted only where it is
product content serving a non-English audience, under `projects/`.
