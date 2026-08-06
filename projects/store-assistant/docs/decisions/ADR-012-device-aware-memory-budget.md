# ADR-012 — "Local" is two budgets, not one: device-aware memory invariant

- **Status**: Accepted
- **Date**: 2026-08-05
- **Amends**: [ADR-011](ADR-011-hybrid-tier-topology.md). The topology decision
  stands; the invariant it introduced was the wrong shape.

## Context

ADR-011 introduced `limits.max_local_tiers` to prevent a resident-memory
overcommit, justified with measurements of **system RAM**: 16 GB host, 9.7 GB
visible to WSL2, 4.0 GB available. That framing was incomplete, and the gap was
found by asking a question the ADR could not answer: *is the idle GPU memory
worth using?*

Measuring the machine rather than reasoning about it produced a different
picture:

| Resource | Measured (2026-08-05) |
|---|---|
| GPU | NVIDIA RTX 5070 Laptop, 8151 MiB total |
| VRAM held by the Windows desktop | 1905 MiB (persistent) |
| **VRAM actually free** | **5987 MiB** |
| System RAM available to WSL2 | 4.0 GB |
| CUDA available inside WSL | yes (`libcuda.so` present) |
| Docker NVIDIA runtime | available |

Against the models on disk:

| Model | Size | Fits in 5987 MiB VRAM |
|---|---|---|
| `gemma-4-E4B-it-Q4_K_M` (Tier 0) | **5.0 GB** | Yes — barely, and it is already there |
| `gemma-4-12B-it-Q4_K_M` | 6.9 GB | No |
| `gemma-4-26B-A4B-it-Q4_K_M` | 16 GB | No |
| `gemma-4-31B-it-Q4_K_M` | 18 GB | No |

`bench/RESULTS.md` (2026-06-15) had already measured the consequence: the E4B
router fully offloaded (`-ngl 99 -c 8192`) reaches **43.19 tok/s**, clearing its
≥25 tok/s gate by 72%. The 12B at `-ngl 20` reaches 8.87 tok/s and **fails** its
gate by 11%; the 26B at `-ngl 10` reaches 2.53 tok/s and fails by 68%.

Two conclusions follow, and they point in opposite directions.

**The VRAM is not idle.** It is fully committed to Tier 0, and that commitment
is what makes the router viable. Nothing else in the tier ladder fits beside a
5.0 GB resident model in 5987 MiB — which the June benchmark had already
established empirically for every larger model on disk.

**But ADR-011's invariant cannot express any of this.** It counts local tiers
against a single budget. A model on the GPU and a model in system RAM do not
compete for the same memory, have different capacities, and fail differently:
exceeding VRAM makes llama.cpp fall back to partial offload — slow but alive —
while exceeding system RAM makes the host swap or the OOM killer fire.

The gap is not theoretical. `docker-compose.yml` passed `-ngl 99` (offload every
layer to the GPU) with the device-reservation block commented out. A container
with no GPU reservation has no GPU to offload to, so llama.cpp falls back to
CPU — where 5.0 GB of weights meet 4.0 GB of available RAM and the host swaps.
The benchmarked 43 tok/s was obtained from a bare `llama-server`, never through
Docker. `max_local_tiers` counts one either way and reports success.

## Decision

**Make the memory invariant device-aware.** A local tier declares *where* its
weights are resident and *how large* they are; budgets are per device.

1. `TierEndpoint` gains `device` (`gpu` | `cpu`, local tiers only) and
   `weights_gb`. `memory_pool` returns the device for local tiers and `None`
   for remote ones — a remote tier costs tokens, not memory, and must not
   consume a budget.
2. `limits.memory_budget_gb` declares a budget per device. Config load sums the
   declared weights per device and fails when a budget is exceeded, naming both
   numbers.
3. Budgets are **measured, not estimated**, and the config records how each was
   obtained. `gpu: 5.8` is 5987 MiB free minus KV-cache headroom; `cpu: 4.0` is
   what WSL2's default host allocation leaves.
4. An undeclared `weights_gb` means *unmeasured*, not *free*: the check is
   skipped for that tier rather than passing it. A use-case that has not
   measured its model is not blocked, but it also gets no guarantee.
5. `docker-compose.yml` reserves the GPU (`gpus: all`) so the containerised path
   matches the benchmarked one, and passes `AGENT_TIER0_DEVICE` so that removing
   the reservation makes the budget check fail loudly instead of the host
   swapping quietly.

`max_local_tiers` is retained. The two checks answer different questions —
*how many models are resident* versus *do they fit where they are placed* — and
the Docker case shows that passing the first tells you nothing about the second.

### What was evaluated and rejected

Asking whether the VRAM could hold more was the right question; the measurements
answer it negatively for every candidate:

| Candidate | Verdict |
|---|---|
| A second reasoning tier beside Tier 0 | ~1 GB remains after E4B weights and its KV cache. Nothing useful fits |
| Promote Tier 1 to a local 12B | 6.9 GB against 5987 MiB free. Benchmarked at `-ngl 20`: 8.87 tok/s, fails its gate by 11% |
| Swap Tier 0 for a larger GPU-resident model, route remotely | Loses GBNF grammar constraints on routing — the exact weakening ADR-011 identifies as disqualifying `all-remote` from the quality-gated path |
| Move Tier 0 to CPU, put a bigger model on the GPU | 5.0 GB of weights against 4.0 GB available RAM. This is the Docker bug, adopted deliberately |
| A small embedding model in the residual VRAM | Genuinely fits (~0.3–1 GB) and would upgrade retrieval from BM25-only to hybrid. **Deferred, not rejected** — it is a retrieval-quality decision that needs its own evaluation evidence, not a memory decision |

## Correction (2026-08-05, same day)

Two claims above were wrong. Both came from the same methodological error —
treating a single observation as a measurement — and they are preserved rather
than edited away, because the error is more instructive than the numbers.

### Wrong claim 1: the VRAM budget

The `5987 MiB free` figure was **one sample of a fluctuating quantity**. The
desktop's hold on the dGPU varies with compositor activity; sampled repeatedly
it sits at **241–252 MiB**, with the ~1900 MiB reading an outlier captured
during a burst.

| | Claimed | Measured (repeated sampling) |
|---|---|---|
| VRAM held by desktop | 1905 MiB (fixed) | 241–252 MiB steady, transient spikes to ~1970 |
| VRAM free | 5987 MiB | **~7650 MiB** |

`limits.memory_budget_gb.gpu` is corrected from `5.8` to `7.4`.

### Wrong claim 2: that the 12B does not fit

The rejection table stated the 12B "fails its gate by 11%", citing
`bench/RESULTS.md`. That June measurement used **`-ngl 20`** — partial offload,
where most layers stream across PCIe. It was never a measurement of whether the
model *fits*; it was a measurement of what happens when you assume it does not.

Re-measured with `llama-bench -ngl 99`, both models under one method:

| Model | Size | Params | pp128 | tg128 | Gate ≥10 tok/s |
|---|---|---|---|---|---|
| E4B Q4_K_M | 4.95 GiB | 7.52 B | 407.09 t/s | **70.37 t/s** | — (router gate ≥25) |
| 12B Q4_K_M | 6.86 GiB | 11.91 B | 746.47 t/s | **29.53 t/s** | **passes by 195%** |

The 12B fits fully in VRAM and is **3.3× faster** than the June figure. Peak
observed during the run: 7635 MiB used, 257 MiB free — tight, but it holds.

### What this does and does not change

**Does not change the topology.** The two models are 4.95 + 6.86 = 11.81 GiB
against ~7.65 GiB free: they cannot be co-resident, so `max_local_tiers: 1`
stands. And a 12B serving the whole loop breaks the interactive SLA at the
measured rates — routing ~80 tokens at 29.53 t/s is 2.7 s and generation ~150
tokens is 5.1 s, which with the planning station exceeds the 8000 ms budget.
E4B does the same work in roughly 4.3 s.

**Does change what the 12B is for.** At 29.53 tok/s it is a viable *local*
tier for latency-tolerant work — nightly evaluation runs, offline verification,
batch scoring — where `bench/RESULTS.md` had concluded only the 26B-at-2.5-tok/s
batch path was available. That is a materially better option than it recorded,
and it costs no cloud spend.

**Makes the discrete-GPU switch a non-lever.** Routing the display to the
integrated Intel UHD adapter would free ~243 MiB. At this scale that is noise.
The constraint was never the desktop's VRAM; it was `-ngl`.

### The methodological lesson

Both errors have the same shape: a number was read once and written down as
*measured*. A single reading of a fluctuating quantity is an anecdote, and a
benchmark run under an assumption cannot test that assumption. Where a budget
or a gate depends on a measurement, the measurement must be repeated, and the
conditions it was taken under must be recorded next to it — which is why the
corrected budgets below carry their sampling method, not just their value.

## Consequences

### Positive

- The invariant now expresses the constraint that actually binds. The Docker
  CPU-fallback would have been caught at config load rather than by the machine
  swapping.
- Budgets carry their measurement provenance in the config, so revising one
  requires re-measuring rather than guessing.
- The containerised path and the benchmarked path now agree, which makes
  `bench/RESULTS.md` a claim about the shipped system rather than about a
  local experiment.

### Negative

- `weights_gb` is hand-declared and can drift from the file it describes.
  Deriving it from the GGUF at startup would be stronger; not done, because it
  requires reading the model file before the server is up. The skip-when-absent
  rule keeps drift from becoming a false guarantee.
- `device` states an *intent*. If llama.cpp silently falls back to partial
  offload despite the reservation, the config still says `gpu`. Detecting the
  actual placement requires querying the server after start-up.
- Two memory checks instead of one is more configuration surface for a
  single-model deployment.

### Neutral

- Reserving the GPU in Docker adds a hard dependency on the NVIDIA Container
  Toolkit. Documented with its fallback rather than silently assumed.

## Revisit triggers

- A GPU with enough VRAM to hold two models — the residual-capacity analysis
  above is re-run rather than assumed to still hold.
- llama.cpp exposes actual layer placement over its HTTP API — `device` can
  become verified rather than declared.
- Retrieval evaluation shows BM25 missing cases that embeddings would catch —
  the deferred embedding model gets its own ADR with that evidence.

## Related

- [ADR-011](ADR-011-hybrid-tier-topology.md) — the topology this amends.
- [ADR-002](ADR-002-calibrated-infrastructure.md) — the same principle:
  calibrate to the measured machine, not to the reference architecture.
- `bench/RESULTS.md` — the June measurements this ADR reinterprets.
- `docs/workstation-memory-budget.md` — the operational companion.
- `tests/test_tier_topology.py` — the executable form of the invariant.
