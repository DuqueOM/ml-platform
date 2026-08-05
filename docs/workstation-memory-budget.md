# Workstation memory budget

Operational companion to
[ADR-011](decisions/ADR-011-hybrid-tier-topology.md). The ADR decides *what*
the topology is; this document is *how* to make a constrained machine actually
run it.

## Why this exists

The platform's binding constraint on a developer workstation is resident
memory, not token cost or CPU. A single mid-size model quantised to Q4_K_M
occupies roughly 4–5 GB; the KV cache for an 8192-token context adds several
hundred megabytes more. Two such models do not fit in a 16 GB laptop that is
also running an IDE, a browser and Docker.

ADR-011 removes the need for more than one. This document removes the other
avoidable losses.

## Step 1 — reclaim RAM from WSL2 (largest single win)

WSL2 defaults to allocating roughly 50% of host RAM. On a 16 GB machine that
means Linux sees about 8 GB and the remaining 8 GB is reserved for Windows
whether Windows needs it or not.

Measured on this project's reference workstation before tuning:

```
Host physical RAM     16 GB
Visible to WSL2       9.7 GB
Available             4.0 GB
Swap                  16 GB   (in use — thrashing, not headroom)
```

Create `C:\Users\<your-user>\.wslconfig` on the **Windows** side:

```ini
[wsl2]
memory=12GB
swap=8GB
processors=6
```

Then, from a Windows terminal:

```bash
wsl --shutdown
```

Reopen the WSL terminal and confirm with `free -h`. Expect roughly 4 GB more
available than before. Leave at least 4 GB for Windows; going higher trades
Linux headroom for desktop responsiveness and usually nets out worse.

## Step 2 — keep exactly one model resident

This is enforced, not advisory: `limits.max_local_tiers` (default `1`) fails
config load if a use-case declares a second `kind: local` tier. Verify what a
given environment resolves to:

```bash
python -c "from core.config import load_usecase; c=load_usecase('tienda'); print(c.topology_profile, sorted(c.tier_endpoints), 'local:', c.local_tiers)"
```

A bare shell should print `local-only [0] local: [0]`.

Never run two `llama-server` processes side by side to "compare models". Stop
one first — a partially swapped model server is slower than the smaller model
you were trying to avoid.

## Step 3 — move the higher tiers off the machine

Export the remote-tier variables (see `.env.example`) to switch to the
`hybrid` profile. Resident memory does not change — Tier 0 is still the only
local model — but reflection, generation and verification stop competing for
it.

```bash
export AGENT_TIER2_URL=https://<provider-host>/v1/chat/completions
export AGENT_TIER2_MODEL=<provider-model-id>
export AGENT_TIER2_API_KEY=...
```

Unset variables mean the tier is simply not configured; escalation resolves
downward rather than failing. There is no separate "local mode" to switch on.

## Step 4 — do not run the full local stack at once

Postgres, Redis, an observability stack and a model server on one 16 GB
machine will not leave room for the model. Preferred substitutions:

| Local service | Replace with | Local RAM saved |
|---|---|---|
| Postgres container | A managed Postgres free tier | ~0.3–1 GB |
| Vector store container | `pgvector` on that same managed Postgres | ~0.5–2 GB |
| Prometheus + Grafana | A hosted metrics free tier | ~1 GB |
| Local embedding model | An embeddings API, or a ~90 MB ONNX model | ~0.5–2 GB |

BM25 retrieval (`core/retrieval.py`) is already in-process and costs no model
memory — prefer it while developing, and reserve semantic retrieval for cases
where lexical matching demonstrably fails.

## Step 5 — bound the containers

`docker-compose.yml` sets `mem_limit` on both services. The point is not to
save memory but to **localise the failure**: a container that exceeds its
limit dies with an attributable cause, whereas an unbounded overcommit lets
the host OOM killer choose a victim — often the IDE, rarely the culprit.

Override per machine without editing the file:

```bash
LLAMA_MEM_LIMIT=6g AGENT_MEM_LIMIT=1g docker compose up
```

## Verifying the budget

```bash
free -h                                    # host headroom
docker stats --no-stream                   # per-container resident size
python -m pytest -q                        # must pass with no model running
```

The last one is the real check. The test suite runs under `local-only` with no
model server and no credentials; if it needs either, something has reintroduced
a hard dependency that ADR-011 exists to prevent.
