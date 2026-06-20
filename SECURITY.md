# Security Policy

## Supported Versions

This is a pre-1.0 platform. Only the latest `main` is supported.

## Reporting a Vulnerability

Please open a **private** security advisory via GitHub
("Security" tab → "Report a vulnerability") rather than a public issue.
Include reproduction steps and impact. We aim to acknowledge within 72 hours.

## Security Model & Invariants

This project follows cloud-native, defense-in-depth practices:

- **No hardcoded credentials.** Never commit `.env`, tokens, or keys. Local
  development uses `.env.local` (gitignored). Production secrets are delivered
  by the platform secret store, never by literals in code or manifests.
- **No model artifacts in images.** Models are mounted as volumes (see
  `docker-compose.yml`); the application image is code-only.
- **Deterministic policy gate.** No model response reaches a customer without
  passing `core/policy.py` — a non-LLM gate that blocks unverified stock/price
  claims, illegal promises, and forces `order_create` to dry-run in Phase 1.
- **Fail-closed tool capability contract.** Tools declare their capabilities
  (`read_only` / `destructive` / `dry_run_only`) and the registry **refuses** to
  run a mutating tool while the use-case is read-only (Phase 1) — the model
  cannot mutate state by merely naming a tool. This is enforced at the tool
  layer, *before* output exists, as a first line of defence independent of the
  policy gate (see [ADR-006](docs/decisions/ADR-006-tool-capability-contract.md)).
- **PII redaction at write time.** Decision telemetry scrubs emails and
  phone-like digit runs before any line touches disk; machine identifiers
  (`trace_id`, timestamps) are preserved for traceability (ADR-005).
- **Read-only by default.** Phase 1 tools never mutate external state; the
  capability gate above makes this structural, not merely conventional.
- **Local-first.** The router runs locally; any cloud overflow is explicit and
  budgeted (`usecases/<name>/budgets.yaml`).

## Out of Scope

- The example `tienda` use-case ships with **fixtures**, not real customer
  data. Do not load real PII into `usecases/*/data/`.
- WhatsApp signature validation is a Phase 2 item (the webhook is a stub).
