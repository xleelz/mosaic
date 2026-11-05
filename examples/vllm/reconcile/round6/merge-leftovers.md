# Round 6: cross-area leftovers for the merge agent (coordinator)

Collected from area reports after each area finished.

- serving-api: judge4 S4-7 and L4-8a (models-layers' report); re-accept is blocked on worker-runner's
  logprobs and models-layers' lints.
- models-layers says moving multimodal processing to the API process, as the code does, breaks 32
  scenarios and left it open. Breaking changes toward the code are welcome: do it if the code runs it
  there, and route the 32 scenarios.
- models-layers: online scales unmodeled; ValueError reasons missing.
- kernels-ops: `split_graph` and pass UUIDs unmodeled; models-layers' FP8 `choice` was removed.
- attention: judge4 P4-8c, config-platform's prefix; P4-8 a/b log lines.
- distributed: policy single-node only; async worker inline; migration batching; no dense TP2 world.
- scheduler-kv: Mamba blocks under deferred free.
- worker-runner: internal-assertions share over the gate; hollow scenarios.
- Remove the untracked `reconcile/coverage-*` and `reconcile/coverage.json` files coverage_gaps wrote
  (they are generated), and don't commit them.
- models-layers: `_normalize_arch` for oracle4's classification test (config-platform).
- serving-api / engine-core: read config-platform's `api-server-count`; peers read `seed`.
- config-platform: generate-runner refusal omitted; registry cache taken as warm.
- oracle4 BAAI test: config-platform says it fails on the oracle's `e.ok`; check it against the code.
- engine-core / worker-runner: `collective-rpc` still joins every rank, so no fail-fast on a rank-0
  failure under TP (judge4 P4-2d). Worker-runner says it is engine-core's; find the owner in the code
  and fix it.
- judge4 P4-7c needs `MultiModalBudget`; Q4-6d (config-platform row merge plus worker-runner's dtype).
- Qwen warmup: oracle4 `qwen_vl_triton_warmup` still fails because Qwen3 isn't loaded in the world.
- worker-runner: DP MoE EP group; the wrapper's `clear_all_graphs`.
