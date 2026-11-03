# Coordinator's running list for the vLLM reconciliation

1. **Batch-limit fixture fixed (done).** `vllm serve` on an H100 resolves 1024 / 8192
   (`arg_utils.py:2934-2941`), and the fixture names the GPU (reported by config-platform).
2. **Skeleton (done).** `prompt_token_ids` lost `maxItems: 64`, which had forced scheduler-kv's
   `prompt_segments` workaround. Scheduler-kv may switch back to real token lists.
3. **KV block count.** The tp1 "2000 blocks" isn't shared state. Scheduler-kv seeds its pool,
   but on a real H100 with Llama-8B it's about 28,000. Worker-runner's KV sizing at startup
   should compute it, and scheduler-kv's pool should take it from that, not from a seed.
4. **`async-scheduling` config.** Both scheduler-kv and config-platform read it, so give it one
   owner.
5. **Engine backlog from vLLM:**
   - **Latency resolution.** Latency is whole milliseconds, which is too coarse for GPU kernels
     (a 2 MiB copy is about 0.1 ms). Consider float ms or microseconds.
   - **`foreach` caps.** The 1,000-item cap per loop and the 10,000 run budget truncate long
     prefix hits.
   - **`entry.repeat` inside a multi-step scenario** (config-platform and scheduler-kv).
   - **Null config values** vanish from `config`.
6. **Kernel and wrapper contracts.** Kernels-ops' wrappers are `custom-ops.<name>` with
   `kind: function`, and the op interface carries the latency. Other areas stub them as
   `kind: kernel` with their own shapes, so callers align to kernels-ops (the owner).
   Kernels-ops guessed `llama-model.forward` and `triton-scaled-mm` for models-layers; they
   align to models-layers' definitions.
7. **Engine: microsecond time (DESIGN §13.1 item 16).** In progress; it fixes "every kernel
   rounds to 0 ms". After it lands, areas can set real latencies (`rms_norm` is about 5 µs, an
   FP8 GEMM about 120 µs).
8. **Attention.**
   - **New owners:** attention now owns `kv-cache-dtype`, `decode-context-parallel-size` and
     `dcp-comm-backend`.
   - **Collectives:** calls send `group_name` and `ranks`, per distributed's contract.
   - **Defaults for models-layers:** the FA forward and KV-write interfaces fill in defaults
     because models-layers sends only shapes. Models-layers should send real metadata.
   - **Missing interface:** config-platform needs `get-attn-backend-cls`.
   - **Fixture requests:** a DCP=2 world and an SM100 world; the GPU is now named H100 (SM90).
9. **Config conflict.** `gpu-hbm-bandwidth-gbps` is defined by both kernels-ops and
   models-layers. Give it one owner: kernels-ops, since the throughput coefficients are its
   assumptions.
10. **Stray instance.** An engine-core scenario warns about instance `rank9`.
11. **Models-layers.**
    - **Fixtures added (done):** Mixtral-8x7B and the FP8 Llama checkpoint on hf-hub;
      `intermediate_size` and rope parameters on Llama; a `lora-adapter-on-disk` fixture.
    - **Skips to review under the skip rules:** 479. The 263 per-architecture packages are
      covered by registry rows, so they need `covered_by`. The rest (MoE, quantization, Mamba,
      MLA and LoRA variants) need valid reasons, or count as uncovered.
    - **Config owners:** `quantization` and `model-impl` belong to config-platform; models-layers
      marks boundary copies.
    - **Per-layer workaround:** one representative layer charges for all layers. Revisit once
      microsecond time lands.
12. **Distributed.**
    - **Parenting:** scheduler-role connector components sit under engine-core. That's
      accepted: the code runs them in the engine-core process.
    - **Test reassignment:** `test_expert_placement_various_sizes` goes to models-layers
      (`expert_map_manager.py`).
    - **All-reduce wiring:** kernels-ops' `custom-ops.all-reduce` wrapper should call
      distributed's `custom-allreduce-cuda.all-reduce`.
    - **Fixture requests:** a P/D world (a NixlConnector producer and consumer), and the GPU
      capability (sm90) in fixture state.
13. **Engine backlog: rendezvous / collective semantics.** When every rank calls all-reduce,
    each rank's call fans out again (N × N). Collectives need a meeting point: a step that
    blocks until N participants arrive, then completes for all of them. That's generic
    (barriers, collectives, consensus rounds). Proposal: `rendezvous: <name>, count: <n or
    =cel>, as: <var>`. It needs the cooperative scheduler.
14. **Skill doc fixed (done):** the `transformMap` example is now `transformMapEntry`.
15. **Engine-core.**
    - **`finish_requests(None)` means all requests.** Scheduler-kv extends its contract
      (nullable `request_ids`) and defines `has-requests`, `pause-state` and `set-pause-state`.
    - **Fixture request:** a DP fixture; data parallelism is uncovered (5 skips).
    - **A choice stands in for state:** in isolation, the "has work" answer is pinned through a
      choice. That's a mock in disguise, and it must use scheduler-kv's real state in the merged
      world.
    - **Busy loop:** utility calls run on arrival; the busy loop should run them, using the
      cooperative scheduler.
16. **Worker-runner.**
    - **KV sizing:** 28,488 blocks, in `gpu-worker-impl@rankN.num_gpu_blocks` and
      `get-num-gpu-blocks`. Scheduler-kv's pool reads it instead of its seed of 2,000.
    - **gpu-memory fields (done):** `non_torch_bytes`, `other_process_bytes`,
      `cudagraph_bytes`, `device_name` and `compute_capability` are in the skeleton and fixture.
    - **Weights:** models-layers' loader allocates the weights in `gpu-memory`.
    - **Config-platform:** defines the 15 unowned configs (enforce-eager, enable-sleep-mode,
      the speculative-decoding settings, ...).
    - **Engine-core:**
      - with the V2 runner, `execute-model` returns null, so engine-core calls
        `sample-tokens`;
      - `initialize-from-config` takes `num_blocks`, but engine-core sends `num_gpu_blocks`.
    - **Spec-decode auto-detection test:** belongs to config-platform.
    - **Simulator gap:** integer configs need `int()` in CEL, because YAML numbers decode as
      doubles. Check the engine's config typing (Config.Type integer should yield int64).
