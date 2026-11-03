# Reconciliation round (vLLM)

All 9 fragments pass on their own. Merged with `worlds.yaml`, the model has:
- 385 components, 1,717 interfaces, 157 flows and 855 scenarios;
- 0 validation errors, and all 5,283 citations resolving;
- 77% of entries modeled, all substantive;
- **1.4% trivial**, against VS Code's 24%: the stage-4b gates worked.

But:
- **80 scenarios fail**: worker-runner 39, engine-core 19, serving-api 15, config-platform 5, and
  one each for kernels-ops and models-layers.
- There are **16 stub-vs-owner differences**, **8 hollow failures**, and **1 config conflict**.
- **models-layers is at 48% modeled**, because 479 skips were rejected.

The rules in `BRIEF.md` still apply. Your inputs are `reconcile/<area>.txt` (your failures and
warnings) and `reconcile/merged-check.txt`. You may read other fragments for their contracts and
state. You may not read their notes, `BENCHMARK.md`, `judge/` or `oracle/`.

## Decisions (binding)

1. **The owner's contract wins.** Callers align to the owner's request, response, kind and
   errors. Owners don't loosen a contract to fit a guess, unless the contract is wrong about the
   code; then the owner fixes it and says so.
2. **Attention metadata.** `flash-attention-metadata-builder.build` aborts on a missing `aot`
   (24 failures). Attention owns the contract.
   - Attention: make fields optional with the code's defaults where the code has defaults.
   - Worker-runner and models-layers: send the real metadata (block tables from the scheduler
     output, sequence lengths, `num_actual_tokens`), not just shapes.
3. **Parallel state.** `parallel-state.ensure-model-parallel-initialized` aborts on its input
   (14). Distributed owns the contract, and worker-runner and engine-core send its shape.
4. **Collectives use `rendezvous`** (DESIGN §13.1 item 17, now implemented).
   - Each rank's model forward calls `tensor-model-parallel.all-reduce` once, on its own rank.
   - Distributed's interface meets the other ranks with
     `rendezvous: "= 'tp-allreduce:' + string(input.layer)"`, `count: config['tensor-parallel-size']`,
     and the backend's latency. Distributed replaces the per-call `parallel` fan-out, so N ranks
     make N calls, not N × N.
   - The executor's `collective_rpc` stays a `parallel` with `join: all` over the ranks
     (worker-runner and engine-core).
5. **The KV block count flows from the worker to the scheduler.**
   - Worker-runner's `determine-available-memory` gives 28,488 blocks for the default world.
   - Engine-core calls `initialize-from-config` with `num_blocks` (not `num_gpu_blocks`).
   - Scheduler-kv's block pool is initialized from that call, not from a seed of 2,000.
   - With the V2 runner, `execute-model` returns null, so engine-core calls `sample-tokens` next.
6. **Scheduler-kv's contract additions.**
   - `finish-requests` accepts `request_ids: null`, meaning all requests (`finish_requests(None)`).
   - New interfaces: `has-requests`, `pause-state` and `set-pause-state`.
   - Engine-core reads scheduler-kv's real state in merged runs. The "has work" choice stays only
     for engine-core's standalone scenarios.
7. **Config ownership.**
   - `gpu-hbm-bandwidth-gbps` belongs to kernels-ops (H100 SXM: 3350). Models-layers marks a
     boundary copy.
   - `quantization` and `model-impl` belong to config-platform.
   - `async-scheduling` belongs to scheduler-kv, and config-platform keeps a boundary copy.
   - `kv-cache-dtype`, `decode-context-parallel-size` and `dcp-comm-backend` belong to attention.
   - Config-platform defines the configs worker-runner reads that nobody owns (worker-runner's
     notes list 15: enforce-eager, enable-sleep-mode, the speculative-decoding settings, ...).
   - `vllm-target-device` belongs to config-platform; kernels-ops drops its own `attributes`.
8. **Kernel wrappers.** Kernels-ops owns `custom-ops.<name>` (kind `function`; the op interface
   carries the latency). Callers copy those contracts. Kernels-ops' `custom-ops.all-reduce` calls
   distributed's `custom-allreduce-cuda.all-reduce`. Kernels-ops drops its guessed
   `llama-model.forward` and `triton-scaled-mm` stubs, or copies models-layers' contracts.
9. **Real latencies.** Time is now in microseconds (DESIGN §13.1 item 16). Kernels and per-layer
   work use real µs latencies (fractional `latency_ms`); don't charge one layer for all of them.
   Models-layers may still run one representative layer, but its latency must be per layer times
   the number of layers, computed exactly.
10. **Seeds.** Each area defines an `<area>-seed` fixture in its own fragment. Use plain component
    keys for state on your own components (e.g. scheduler-kv's block pool, worker-runner's device
    facts, models-layers' registry), and `@rankN` keys only when ranks differ. Even an empty seed
    is fine. The coordinator regenerates `worlds.yaml` (`full-*`), so every area's state is
    present in merged runs. Use `full-*` worlds in cross-area scenarios.
11. **Skips.**
    - Models-layers: the 263 per-architecture packages get `covered_by: component:model-registry`
      (or the registry's real id). The other 216 need a valid reason (not an entry point,
      developer or internal tooling, platform-only, owned elsewhere with the area named), or get
      modeled. Reach modeled ≥ 50%.
    - Distributed: reword or model the 6 rejected skips (the encoder-cache transfer loops and the
      RL weight-sync loops).
12. **Serving-api and engine-core.**
    - The engine-dead state is engine-core's: `async-llm.errored` reads a state that a worker
      failure sets. Serving-api seeds it, not a fault.
    - A client disconnect cancels through a token, so `AsyncLLM.generate` aborts the request in
      the engine core (DESIGN §13.1 item 14).
    - Engine-core fixes the loop-budget exhaustion in `sync-mp-client` (the offline path).
    - `openai-serving-completion`'s parent is serving-api's; config-platform drops its copy's
      parent.
13. **Models-layers.**
    - The loader records the weights in `gpu-memory` (`weights_bytes`).
    - `llama-for-causal-lm.init` aborts in merged runs (4); align to config-platform's resolved
      config.
14. **Tests that belong elsewhere.** `test_expert_placement_various_sizes` is models-layers'.
    The spec-decode auto-detection test is config-platform's. The receiving area adds them as
    in-build oracle scenarios if they're translatable.

## Verify

```sh
cd /home/lbethay/workplace/mosaic
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
python3 .claude/skills/mosaic-generate/scripts/assign_inventory.py examples/vllm --worlds
F=""; for f in examples/vllm/fragments/*.yaml; do F="$F -f $f"; done
go run ./internal/devtools/check -f examples/vllm/skeleton.yaml -f examples/vllm/fixtures.yaml -f examples/vllm/worlds.yaml $F \
  --code /home/lbethay/.cache/mosaic-bench/vllm-0.32.0 --strict-citations --inventory examples/vllm/inventory.json \
  --behavior-coverage --lint hollow,trivial --no-mocks --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35
```

Run `assign_inventory.py` after you change your skips or seed. It's idempotent, and other agents
run it too.

**Exit criteria for your area:**
- none of your scenarios fail in the merged run;
- no merge warning or hollow failure names your fragment;
- modeled and substantive coverage ≥ 50%, and trivial ≤ 35%;
- 0 mocks, and citations ok.

A failure caused by another area's unfinished fix isn't yours: name it, and don't work around it.

## Report (≤120 words)

Report:
- the failures and warnings you fixed, and those remaining, with their cause and the area each
  one waits on;
- your modeled coverage before and after;
- the seed and other fixtures you defined;
- the final gate lines.
