# vLLM v0.32.0: stage-1 inventory audit

Snapshot: `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0` (read-only).
Command: `go run ./internal/devtools/inventory --code $CODE --out examples/vllm/inventory.json`.
Auto-detect turns on the `python-gpu` plugin, because the root has `csrc/`. The base `python`
scanner also runs; its kind is `python-cli` below (`cron` comes from the YAML scan, which always
runs). Use `--lang python-gpu` to run the plugin without the base Python scanner, which drops
`python-cli`.

Total: 2,580 entries over 13 kinds.

## Counts by kind

| kind | count | via (count) | detail |
|---|---:|---|---|
| triton-kernel | 627 | triton-jit | `autotune` / `heuristics` when stacked |
| torch-op | 457 | torch-library 272; direct-register 175; custom-op-decorator 10 | the C++ op schema plus impls by dispatch key (`impl CUDA=TORCH_BOX(&fn)`), or the Python impl function |
| model-registry | 391 | registry-table | `module.Class (table)`, for example `llama.LlamaForCausalLM (_TEXT_GENERATION_MODELS)` |
| python-cli | 305 | py-main 297; argparse-subcommand 6; pyproject-scripts 2 | base scanner: 280 are `__main__` scripts in benchmarks/, examples/ and tools/ |
| torch-op-wrapper | 258 | torch-ops-call | the `torch.ops._C*.op` calls the wrapper makes |
| cuda-kernel | 202 | cuda-global | |
| python-api | 111 | package-export 98; package-export-inherited 13 | `vllm.AsyncLLMEngine = vllm.v1.engine.async_llm.AsyncLLM`, and the mixin a method comes from |
| http-route | 81 | fastapi 79; fastapi-add-route 2 | handler function |
| engine-rpc | 71 | collective_rpc 52; utility 19 | the defining worker or engine-core classes and the call sites. The entry sits on the definition when one is found (70 of 71) |
| busy-loop | 44 | thread-target 16; loop-function 15; while-true 11; engine-step 2 | the loop condition |
| cli-command | 17 | cli-subcommand | `vllm bench latency` and similar, with the `CLISubcommand` class |
| plugin | 14 | plugin-group 7; builtin-plugin 5; pyproject-entry-point 2 | the entry point target or the loader call |
| cron | 2 | gha-schedule | base YAML scanner |

## Precision

I read a seeded sample of 40 entries (`shuf -n 40 --random-source=<(yes 42)`) against the code.
All 40 were true: 9 busy loops, 7 model-registry entries, 6 Triton kernels, 6 op wrappers, 4 torch
ops, 2 routes, 2 API methods, 2 plugins, 1 engine RPC and 1 python-cli script. I checked busy loops
in the sample for being long-running loops, not drains or retries (for example
`MoRIIOWrapper._async_wait`, a listener thread started with `threading.Thread(target=...)`).

**Measured precision: 40/40 (1.00).**

Targeted reviews of the weakest heuristics:

- **busy-loop.** I read all 44.
  - 1 false positive: `MooncakeConnectorWorker.receive_kv_from_single_worker`, a receive loop
    inside `async with`.
  - The rest are thread targets, `*_loop` functions, the `run_busy_loop` pair and the two
    `EngineCore.step*` functions.
  - The audit removed drain, retry and startup-wait loops (a `while` nested in `for` or `if`, or a
    condition without a stop or running flag) and same-name thread targets from other files.
- **engine-rpc.** All 71 method names are real targets. The defining class is ranked `Worker` or
  `WorkerBase` (or `EngineCore`) first, and `*Client` classes are excluded.
  `collective_rpc reinitialize_distributed` has no definition in the repo; it is a Ray actor method.
- **python-cli** (base scanner) is true but mostly out of product scope: 280 of 305 are scripts
  under `benchmarks/`, `examples/` and `tools/`. Make it a profile skip rule, or run with
  `--lang python-gpu`.

## Recall

Recall is measured against a grep or AST walk of each pattern over the same sources. Tests,
examples, docs, benchmarks/, tools/, `third_party` and generated code are left out.

| pattern | grep | found | recall | what the rest are |
|---|---:|---:|---:|---|
| `@router/app.get/post/...(` | 79 | 79 | 1.000 | |
| `.add_api_route(` | 3 | 2 | 0.667 | 1 non-literal path (`route.path`, a dynamic re-registration that disables routes) |
| `class X(*Subcommand*)` | 19 | 17 | 0.895 | 2 abstract bases without a `name`: 1.00 adjusted |
| `collective_rpc` / `call_utility` method names (unique) | 71 | 71 | 1.000 | |
| `def *busy_loop` | 3 | 3 | 1.000 | |
| `while True:` (all, as context) | 105 | 37 | 0.35 | by design: most are parsing, retry, drain or polling-in-request loops |
| `ops.def(` in csrc | 272 | 272 | 1.000 | |
| `direct_register_custom_op(` | 177 | 175 | 0.989 | 1 dynamic `op_name=self.op_name` (helion), 1 duplicate name in a file |
| `__global__` (sites) | 234 | 202 | 0.863 | all 32 are duplicates: forward declarations, enable_if overloads and per-platform copies of the same kernel in one file |
| `__global__` (unique file + kernel) | 203 | 202 | 0.995 | 1 is my grep reading `__attribute__` as a name. The kernels stamped out by `#define` macros are skipped on purpose |
| `@triton.jit` (AST, unique file + function) | 619 | 619 | 1.000 | 4 raw grep hits are platform-conditional redefinitions, merged |
| module-level defs calling `torch.ops._<ns>.*` (AST) | 258 | 258 | 1.000 | |
| model table keys in `registry.py` (unique) | 391 | 391 | 1.000 | the 399 grep lines hold 8 keys repeated across tables, merged into one entry each |
| public methods of `LLM` / `AsyncLLMEngine` / `LLMEngine` | | | | all methods of the class and its in-repo mixins. `LLM.generate`, `chat`, `encode`, `embed`, `score`, `classify` and `beam_search` are present |

## Known misses and limits

- **Busy loops** are found by shape:
  - a function named `*loop*`;
  - a thread or process target in the same file whose main statement is a `while` with a
    running/stop condition (nested only in `with` or `try`);
  - a `while True` main loop in a function named like background work.

  Loops in functions handed to executors or `asyncio.create_task` under another name are missed,
  unless their names match.
- **The scheduler.** `Scheduler.schedule()` is reached from `EngineCore.step*` and is not listed
  itself. The step functions are, as `engine-step`.
- **Engine RPC** targets passed as variables (the `/collective_rpc` dev route forwards
  `method=method`) and nested `elastic_ep_execute` sub-commands (`args=("commit_scale_up",)`) are
  not split out.
- **Torch ops.**
  - `TORCH_EXTENSION_NAME` is replaced with the directory's extension (`_rocm_C` under `rocm/`,
    `_moe_C` under `moe/`, else `_C`). This is a guess at the CMake target.
  - Ops registered by external libraries (`torch.ops.aiter`, `fbgemm`, `zentorch`) are only seen
    at call sites. They are not listed.
- **Op wrappers.** Only module-level wrappers of `torch.ops._*` (C++ extension) ops are listed.
  Python-registered ops (`torch.ops.vllm.*`) appear as `torch-op` at their
  `direct_register_custom_op` site instead.
- **CUDA kernels** produced by `#define` macros, and launches of kernels from third-party headers,
  are not listed.
- **Platform plugins.** Out-of-tree plugins appear only as their groups (`group
  vllm.platform_plugins` and five other groups). The in-tree ones are the five
  `builtin_platform_plugins`.
- **The Rust frontend** (`rust/`) and the gRPC server's service methods are not scanned.
