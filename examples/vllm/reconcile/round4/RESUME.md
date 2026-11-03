# Coverage round (vLLM fix round 4): where it stopped

Every agent was cut off by the weekly usage limit on 2026-11-02 at about 19:00 UTC. The limit
resets on 2026-11-04 at 15:00 UTC. Each agent's work is saved. Resume each one with SendMessage
("continue from where you stopped, then stage and report") rather than starting a new agent;
the agent ids are in the coordinator session's transcript.

Brief: `examples/vllm/FIXES4.md`. Coverage inputs are in `reconcile/round4/by-owner/`, ranked
by code owner. Blind measures, ready and never shown to builders: `BENCHMARK3.md` + `oracle3/`.

## vLLM (round 4)

| Area | State | Owner reach | Left |
|---|---|---|---|
| kernels-ops | done | 13% -> 16% | call config-platform's new `vllm-config.compute-hash` (do at merge) |
| distributed | done, staged | 12% -> 18% | MultiConnector and HiSparse dispatch |
| attention | done, staged | 45% -> 52% | CPU prefill fix applied by the coordinator (rebuilt) |
| models-layers | done | 4% -> 7% | per-model numerics declined (refinement work) |
| engine-core | done, not staged | 34% -> 49% | blocked on serving-api; spec-decode metrics (P3c) |
| config-platform | done, not staged | 23% -> 35% | blocked on attention's CPU call (now fixed) |
| scheduler-kv | cut off | 15% -> 36% | was writing the last 6 top-25 rows (Mamba split, RSWA, block sizes, kv-cache config, chunked-local hit) |
| worker-runner | cut off | ? | adding components; owes: grammar bitmask before sampling, distributed's worker connector calls, MLA spec routing, 2 unknown inputs |
| serving-api | cut off | ? | editing score/pooling returns; owes: logprobs, lora_request, cache_salt, min>max refusal, elastic-ep Ray, engine-core's stub kinds, media-io merge call, CLI engine args |

## After every area reports

1. Merge; accept all areas' stages together (last-good snapshots are stale across
   areas). Wire kernels-ops -> `vllm-config.compute-hash`.
2. Full gates; keep thresholds; re-run `coverage_gaps.py` for before/after reach.
3. Blind measures with fresh agents: judge3 + oracle3.
4. RESULTS (vLLM round 4); commit; update memory.

## Tooling found this round

- `coverage_gaps.py` doesn't credit Next.js `[trpc]` paths (bracketed directories).
- Open from before: a cited spec-divergence exemption for conformance; `calls[a] + calls[b]` typed as
  bytes; error faults ignore `latency_ms`; a scenario can't close a session; Temporal replay.
