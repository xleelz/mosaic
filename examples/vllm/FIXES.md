# Fix round (vLLM, after judging)

The model passes every gate, but the judges and the test oracle found wrong claims and missing
features (`RESULTS.md`, `judge/*.md`, `oracle/*.md`). This round fixes them.

- The rules in `BRIEF.md` and the decisions in `RECONCILE.md` still apply.
- **You may now read `judge/` and `oracle/`** files that concern your area, because they're your
  fix list. Fix the model, never the judges' or the oracle's scenarios.

## New tools since your build (DESIGN §13.1 items 18–19)

- **Streams:**
  - `yield` steps on the callee;
  - `stream: true` with `on_item` on the call.
- **Channels:**
  - `put` and `receive`, with a timeout and a capacity;
  - `channel_len()` in CEL.
- **Kills:** a `kill` fault or step. Peers get `peer-killed`, and `restart` revives the instance.
- **CEL cost limit:** now 10M by default, and configurable per scenario.
- **Features:** `profile.yaml` lists 28 features, each with an owner. For each one you own, model
  it with a flow tagged `feature:<id>` that a scenario runs, or skip it in
  `skips/<area>.features.json` with a valid reason (not "not modeled").
- **Test reach:** `check --tests examples/vllm/test-targets.json` reports how many of vLLM's test
  files have their code under test reached by a scenario. Raise yours.

## Fix list by area

| Area | Fix |
|---|---|
| serving-api | The chat route passes all sampling params to the engine (`stop`, `top_p`, `seed`, `include_stop_str_in_output`, stream flags) (V7). A missing temperature takes the model's generation_config (0.6 / 0.9 for Llama-3.1). Streaming yields one SSE chunk per engine step (`yield`, V2). Structured outputs and parser `adjust_request`. `/score` with queries and documents. `LLM.encode` through the real add-request path. Multimodal and `prompt_embeds` parts. Features: streaming, tool-calling, reasoning-outputs, multimodal-inputs, pooling-embeddings |
| engine-core | `n>1` children merge into one output (E6, parallel-sampling). Offline outputs carry external ids and all tokens, sorted in input order, with per-prompt params (E5). `collective_rpc` waits only on the output rank (X2, X5). Executor shutdown stops the workers, and SIGTERM ordering is client first, HTTP last (E4); use `kill` for the SIGKILL grace. The busy loop blocks on an input `receive` instead of polling (E2). The DP client fan-out (data-parallel). Features: parallel-sampling, offline-llm, data-parallel, graceful-shutdown |
| scheduler-kv | With prefix caching off, nothing is hashed or cached (K7). The `max_model_len` capacity check at startup (X3, with worker-runner). Spec tokens scheduled and rejected tokens rolled back (X6). Connector hooks in `schedule` and `add-request` (`kv_transfer_params`, `WAITING_FOR_REMOTE_KVS`), and external computed tokens in `allocate-slots`. Hybrid and Mamba managers. Structured-output regex validation. Features: structured-outputs, kv-cpu-offload, hybrid-kv-cache |
| worker-runner | Greedy sampling is deterministic, using a deterministic token from the logits stand-in (V6). Sampling on non-last PP ranks. Only the output rank replies. Spec-decode verification. Features: pipeline-parallel, speculative-decoding, sleep-mode |
| distributed | Disaggregated prefill end to end: NIXL remote prefill with the scheduler hooks, and MoRIIO `split_block_groups`. Feature: disaggregated-prefill |
| models-layers | EPLB and `enable-eplb` (with config-platform). Quantization and NVFP4 detection (with config-platform). Features: expert-parallel, lora, quantization |
| attention | `get-attn-backend-cls` keeps the probe-failure reasons and catches only `ImportError`/`OSError` |
| config-platform | Quantization and NVFP4 detection, `fuse_act_quant`, `VLLM_OBJECT_STORAGE_SHM_BUFFER_NAME`, `enable-eplb` |
| kernels-ops | Features: cuda-graphs, torch-compile (tag your existing flows) |

## Verify

The gate is the RECONCILE.md command plus
`--tests examples/vllm/test-targets.json --features examples/vllm/profile.yaml`. Also re-run the
judge and oracle scenarios for your area against the merged model:

```sh
go run ./internal/devtools/check -q -f examples/vllm/skeleton.yaml -f examples/vllm/fixtures.yaml -f examples/vllm/worlds.yaml $F \
  -f examples/vllm/judge/scenarios/<CASE>.yaml --scenario '^bench'
```

**Exit criteria:**
- the gate passes, and your judge and oracle cases that were `fail` or `model-bug` now pass, or
  are explained;
- no feature you own is missing;
- your test reach goes up.

## Report (≤150 words)

Report:
- the fixes, with code citations;
- the judge and oracle cases now passing;
- your feature status and test reach, before and after;
- what's still open.
