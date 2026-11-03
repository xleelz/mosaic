# Brief: build the vLLM 0.32 (built from code) ontology from code

You are one of 9 area agents building a mosaic ontology of **vllm-project/vllm at
v0.32.0** directly from its source code. Each agent writes one fragment. The fragments
are merged with `skeleton.yaml` and `fixtures.yaml` into one ontology. Then the repo's own tests
are translated into scenarios against it, and independent judges test it against well-known
behavior of the system. Model what the code does, not what you remember about the system. Where
they differ, the code wins, and you record the difference in your notes.

Contracts, naming and the shared worlds are fixed before you start. Coverage is measured against
an inventory of entry points. Citations are checked mechanically and then by a judge.

## Rules

1. **Source of truth.** The code at `/home/lbethay/.cache/mosaic-bench/vllm-0.32.0` (`v0.32.0`, `5df63a7203cdb9328d824a27b682e77c7b9928be`).
   It is read-only: never modify, build or run anything in it.
2. **Independence.** Read only these: the code, `skeleton.yaml`, `fixtures.yaml`, the inventory,
   your own files, and, for contracts only, an owner's fragment when you call another area. Never
   read `other areas' notes`, `BENCHMARK.md`, `judge/**`, `oracle/**` or (none).
3. **Evidence.** Every component, interface, config and narrated step cites code, as
   path:line or path:line-end, relative to snapshot.path, one source per string. Use **one source per string**, and the `sources` list when you need
   several. Cite files, not directories. Cite **the method's own lines**, because coverage and
   judges match them; a citation near an entry point doesn't cover it. `**/*.md`, `docs/**`, `tests/**`, `benchmarks/**`, `examples/**`, `tools/**`, `.github/**`, `docker/**`
   may orient you, but they are not evidence. Cite them only in your notes.
4. **Deployed config decides modes.** Code defaults aren't always what runs. The deployed values
   come from | path | role | format |
|---|---|---|
| vllm/config/*.py (pydantic Field defaults) and vllm/engine/arg_utils.py (EngineArgs defaults) | default | code |
| the fixture's deployment (engine args given to `vllm serve`) | deployed | fixture |, in that order. Every value a behavior reads is a **config
   entity**, read as `config['<id>']`, durations included:
   `timeout_ms: "= config['write-request-timeout-ms']"` (`deadline_ms`, `after_ms`, `every_ms`,
   `stagger_ms`, `count` and `join.need` take templates too). A config belongs to the area whose
   code reads it:
   - **you own it**: define it in your fragment, named by the engine arg in kebab-case (max_num_seqs -> max-num-seqs; gpu_memory_utilization -> gpu-memory-utilization); attributes.key holds the original, with the deployed
     `value`, the code `default`, and both lines in `sources`. For the shared values in
     | key | owner |
|---|---|
| max_num_seqs | scheduler-kv |
| max_num_batched_tokens | scheduler-kv |
| enable_chunked_prefill | scheduler-kv |
| enable_prefix_caching | scheduler-kv |
| block_size | scheduler-kv |
| gpu_memory_utilization | worker-runner |
| max_model_len | config-platform |
| tensor_parallel_size | distributed |
| scheduling_policy | scheduler-kv | that the profile assigns to you, `fixtures.yaml` holds a reference;
     your definition replaces it, and you fix its value if the reference is wrong;
   - **another area owns it**: use the reference in `fixtures.yaml`, or add your own copy marked
     `attributes: {boundary: true, owner: <area>}`. An unmarked copy that differs is a merge error.
   Record every place where the deployed value and the default differ.
5. **Secrets.** Never open `**/*.env*`, `**/*.age`, `**/*.pem`, `**/*.key`, `**/credentials*`, `**/.netrc`. Never copy a token, key, password or internal
   hostname into the ontology.
6. **Your files only.** Write `fragments/<area>.yaml`, `notes/<area>.md` and `skips/<area>.json`
   under `examples/vllm/`. Edit nothing else. Don't commit. You may read your own
   `build-oracle/<area>.json`, and no other file there.

## Areas and ownership

An area owns the code under its paths. Where paths overlap, the more specific glob wins. The
overrides below beat paths.

| Area | Module | Owns | Except | Typical entry points |
|---|---|---|---|---|
| serving-api | api-server | `vllm/entrypoints/**`, `vllm/renderers/**`, `vllm/tool_parsers/**`, `vllm/reasoning/**`, `vllm/parser/**`, `vllm/tokenizers/**`, `vllm/transformers_utils/**`, `vllm/inputs/**`, `vllm/outputs.py`, `vllm/sampling_params.py`, `vllm/pooling_params.py` |  | OpenAI-compatible routes (chat completions, completions, embeddings, responses, models, health), the CLI (vllm serve, bench), LLM.generate/chat/encode, request validation, tokenization, detokenization and streaming |
| engine-core | engine-core | `vllm/v1/engine/**`, `vllm/engine/**`, `vllm/v1/executor/**`, `vllm/v1/metrics/**`, `vllm/v1/fault_tolerance/**`, `vllm/v1/request.py`, `vllm/v1/outputs.py`, `vllm/v1/serial_utils.py`, `vllm/v1/utils.py` |  | AsyncLLM / LLMEngine and their client, the EngineCore process and its busy loop, add/abort request, output processing, executors (uniproc, multiproc, ray), shutdown and fault tolerance |
| scheduler-kv | engine-core | `vllm/v1/core/**`, `vllm/v1/kv_offload/**`, `vllm/v1/simple_kv_offload/**`, `vllm/v1/kv_hints/**`, `vllm/v1/hisparse/**`, `vllm/v1/structured_output/**` |  | scheduler step (continuous batching, chunked prefill, preemption), KV cache manager and block pool, prefix caching, KV offload, structured output grammar bookkeeping |
| worker-runner | gpu-worker | `vllm/v1/worker/**`, `vllm/v1/sample/**`, `vllm/v1/spec_decode/**`, `vllm/v1/pool/**`, `vllm/v1/watermarking/**`, `vllm/device_allocator/**`, `vllm/v1/cudagraph_dispatcher.py` |  | worker init/load model/determine KV cache size/execute_model, the GPU model runner (input prep, CUDA graphs, sampling), speculative decoding, pooling |
| attention | gpu-worker | `vllm/v1/attention/**`, `vllm/attention/**`, `vllm/vllm_flash_attn/**`, `csrc/attention/**` |  | attention backends and their selection, metadata builders, paged attention and FlashAttention calls |
| distributed | gpu-worker | `vllm/distributed/**`, `csrc/custom_all_reduce*`, `csrc/custom_all_gather_reduce_scatter*`, `csrc/custom_collective_common.cuh` |  | parallel state (TP/PP/DP groups), collective ops (all-reduce, all-gather), the custom all-reduce, KV transfer connectors (disaggregated prefill), expert parallel |
| models-layers | gpu-worker | `vllm/model_executor/**`, `vllm/models/**`, `vllm/lora/**`, `vllm/multimodal/**` |  | the model registry and loader (weights download/load, quantization), model forward for representative architectures (Llama, Qwen, DeepSeek MoE), layers (linear, rotary, MoE, sampler logits), LoRA, multimodal processing |
| kernels-ops | gpu-worker | `csrc/**`, `vllm/_custom_ops.py`, `vllm/_xpu_ops.py`, `vllm/_aiter_ops.py`, `vllm/_*.py`, `vllm/kernels/**`, `vllm/triton_utils/**`, `vllm/compilation/**`, `vllm/ir/**`, `vllm/cute_utils/**`, `vllm/utils/**` | `csrc/attention/**`, `csrc/custom_all_reduce*`, `csrc/custom_all_gather_reduce_scatter*` | torch custom ops and their Python wrappers, CUDA and Triton kernels (as latency models), torch.compile integration and CUDA graph capture |
| config-platform | control | `vllm/config/**`, `vllm/platforms/**`, `vllm/plugins/**`, `vllm/envs.py`, `vllm/logging_utils/**`, `vllm/profiler/**`, `vllm/snapshot/**`, `vllm/assets/**`, `vllm/benchmarks/**`, `setup.py`, `pyproject.toml` |  | EngineArgs to VllmConfig resolution and validation, platform detection and plugins, environment variables, profiling |

**Overrides (owned by function, not by file):**

| Symbol | Area | Reason |
|---|---|---|
| EngineArgs (vllm/engine/arg_utils.py) | config-platform | argument parsing and config resolution belong with the config it builds |
| Scheduler.update_from_output | scheduler-kv | the scheduler owns request state transitions after each step |

`Requests flow serving-api -> engine-core (AsyncLLM.add_request -> EngineCoreClient) -> engine-core busy loop -> scheduler-kv (schedule) -> engine-core executor -> worker-runner (execute_model) -> models-layers (forward) -> attention / kernels-ops; outputs flow back through the engine core's output processor to serving-api.`, `Kernels are modeled as interfaces of kind kernel whose latency_ms is a CEL expression of the token/batch shape; their bodies are not simulated.`, `Tensor-parallel ranks are instances of gpu-worker; collectives are parallel joins (join: all) owned by distributed.`

## Naming (fixed, so callers can predict the owner's ids)

- **Components:** the class in kebab-case (EngineCoreProc -> engine-core-proc); a module of functions takes its file name (_custom_ops.py -> custom-ops). Put every component under your skeleton module, or under
  another of your components.
- **Interfaces:** the method or function in kebab-case (add_request -> add-request); routes are <method>-<path slug> (POST /v1/chat/completions -> post-v1-chat-completions).
- **Routes and messages:** <method>-<path>: lowercase, {param} -> param, other chars -> -, cut to 64 engine-core client messages (ADD, ABORT, UTILITY) are interfaces on engine-core-proc named handle-<type>
- **Schemas:** area prefix in PascalCase (ServingChatRequest, SchedKvBlockTable); shared contracts keep the owner's name. A shared contract keeps its owner's name, and only the owner
  defines it.
- **Configs:** the engine arg in kebab-case (max_num_seqs -> max-num-seqs; gpu_memory_utilization -> gpu-memory-utilization); attributes.key holds the original. **Instances:** rank0..rank7 for GPU workers; dp0.. for data-parallel engine cores; api0 for API server processes.
- **Scenarios:** <area>-<flow>-<case>.
- Ids are globally unique across all areas. Never use bare generic names: `handler`, `manager`, `service`, `worker`, `client`, `request`, `result`, `error`, `model`, `util`.

Worked examples: | entry | component | interface |
|---|---|---|
| http-route POST /v1/chat/completions | openai-serving-chat | openai-serving-chat.post-v1-chat-completions |
| engine-rpc execute_model | gpu-worker-impl | gpu-worker-impl.execute-model |
| torch-op paged_attention_v1 | custom-ops | custom-ops.paged-attention-v1 |

## Contracts (fixed before fan-out)

- **The owner's definition is the contract.** Each interface has one owner: the area that owns
  its code. When you call another area's interface:
  1. if `skeleton.yaml` predeclares it (a boundary stub with `owner`), copy that stub exactly;
  2. else, if the owner's fragment exists, copy its request, response, kind and errors (including
     `retryable`), and read that fragment for nothing else;
  3. else, use the shared shapes below, declare only what your call site really sends and reads,
     and expect to align in the reconciliation round.
  Never invent a different `kind`, response type or error status for someone else's interface.
- **Shared shapes.** Use these field names everywhere, so stubs merge cleanly:

  - `request_id`: string, the engine request id (chatcmpl-..., cmpl-...)
- `prompt_token_ids`: list of int
- `num_tokens`: int
- `sampling_params`: object: temperature, top_p, max_tokens, stop, n, seed, ignore_eos
- `finish_reason`: string: stop \| length \| abort \| null
- `block_ids`: list of int, KV cache block ids

  Shared schemas, defined once in `skeleton.yaml`: | id | owner | fields |
|---|---|---|
| EngineCoreRequest | engine-core | `request_id`, `prompt_token_ids`, `sampling_params`, `arrival_time`, `priority` |
| SchedulerOutput | scheduler-kv | `scheduled_new_reqs`, `scheduled_cached_reqs`, `num_scheduled_tokens`, `total_num_scheduled_tokens`, `finished_req_ids` |
| ModelRunnerOutput | worker-runner | `req_ids`, `sampled_token_ids` |.
  HTTP routes take {path, body, headers}; responses are the OpenAI JSON body
- **Errors.** the exception class in kebab-case (ValueError -> value-error, EngineDeadError -> engine-dead-error); OpenAI routes use the OpenAI error type (invalid_request_error, ...) with the HTTP status; the status is the HTTP status for routes; 0 elsewhere. The fixed table:

  | Code | Status | Retryable | Source |
|---|---|---|---|
| invalid_request_error | 400 | false | vllm/entrypoints/openai/protocol.py |
| engine-dead-error | 500 | false | vllm/v1/engine/exceptions.py |

  Check any code you add against `vllm/entrypoints/openai/protocol.py`, `vllm/v1/engine/exceptions.py` and the code that throws it.
- **Stubs merge by union.** When several areas stub the same boundary interface, the merge combines
  their properties, required lists, enums and errors, keeps the first value of any scalar, and
  warns about every disagreement. The owner's definition wins over every stub. So declare every
  field your code really reads, and copy the owner's scalars.
- **Shared infrastructure.** | id | kind | interface_kind | naming |
|---|---|---|---|
| gpu-memory | datastore | io | gpu-memory.<op> (allocate, free, profile-peak) |
| hf-hub | external | http | hf-hub.<op> (download-config, download-weights) |
| local-disk | datastore | io | local-disk.<op> |: calls to them are boundary-stub interfaces
  named after the operation, with one kind for all areas. Stateful storage that scenarios must
  inspect belongs on the owner's own component, as `store` interfaces.

## The world: fixtures, instances and config

- **Use the shared fixtures. Never seed a private world.** `fixtures.yaml` defines
  | id | summary | extends |
|---|---|---|
| tp1-llama-8b | one 80 GB GPU (rank0), Llama-3.1-8B-Instruct, the default engine args (block 16, max_num_seqs 128, max_num_batched_tokens 2048, chunked prefill and prefix caching on) |  |
| tp4-llama-70b | four GPUs (rank0..rank3), Llama-3.1-70B-Instruct, TP 4 | `tp1-llama-8b` |
| small-batch-limits | tp1 with max_num_seqs 2 and max_num_batched_tokens 64 | `tp1-llama-8b` |
| prefix-caching-off | tp1 with prefix caching off | `tp1-llama-8b` |. Every scenario lists `fixtures: [...]` and adds only the state its case
  needs on top. Use the canonical names (- `model`: meta-llama/Llama-3.1-8B-Instruct
- `served_model_name`: llama-8b
- `request_id_prefix`: chatcmpl-) in inputs and in your
  schemas' `examples`, so fake entry data lands in the seeded world. Never seed another area's
  state under names of your own; if the fixture lacks something your case needs, ask the
  coordinator to add it, and record the request in your notes.
- **Unknown keys fail.** A behavior that looks up a table, key, tenant or route that isn't there
  fails with the code's real error. It never logs and skips.
- **Instances, not `to` fields.** Copies of the same code (| component | default | summary |
|---|---|---|
| gpu-worker | `rank0` | a GPU worker process (one per tensor-parallel rank) |) are instances.
  Address a peer with `on: <instance>` on the `call`, `emit` or `publish`, not with a `to` or
  `endpoint` field in the request. A behavior knows where it runs from `self`. Per-instance state
  is keyed `<component>@<instance>`. Entries run on `rank0` unless a step
  says `on:`.
- **Shared data has one owner.** Each datum several areas touch has one owner, which keeps the
  only copy in its own component's state:

  | Datum | Owner | Readers |
|---|---|---|
| KV cache blocks and block tables | scheduler-kv | `worker-runner`, `attention`, `engine-core` |
| request state (status, num_computed_tokens, output tokens) | scheduler-kv | `engine-core`, `worker-runner` |
| the loaded model weights | models-layers | `worker-runner` |
| the resolved VllmConfig | config-platform | `all` |

  If you're a reader, read and change it only by calling the owner's interfaces (copy their
  contracts as for any other seam), and seed it only through the owner's fixtures. Never keep a
  copy of your own, under any name: two copies drift, and edits through one never reach the
  other. If you own it, give the readers the interfaces they need.
- **Time.** Every timestamp derives from `now`. The fixture sets the clock's epoch. Never write a
  wall-clock literal. Deadlines and timeouts read config
  (`deadline_ms: "= config['read-request-timeout-ms']"`), and periodic work uses timers (`emit`
  or `publish` with `every_ms` and `count`) or `entry.repeat`.

## How to model

Read these first: `.claude/skills/mosaic-ontology/SKILL.md` with its
`references/document-format.md` and `references/modeling-codebases.md`; then
`.claude/skills/mosaic-simulation/SKILL.md` with its `references/behavior-language.md` and
`references/recipes.md`. Ignore their CLI instructions: you verify with the check tool below.

- **Fragment header.** `schema_version: 1`, `id: vllm`, then your entities. Don't redefine
  skeleton components, configs or fixtures.
- **Depth.** Go down to the smallest components that make a decision or own state. Behaviors
  follow the real control flow: refusals with the real codes; retries with their real triggers;
  timeouts and deadlines from config; fallbacks and state transitions; capacity limits
  (`capacity`) where the code bounds concurrency; background work as timers, events or repeated
  flows.
- **Fan-out is `parallel` with a join, not a sequential `foreach`.** When the code sends to
  several peers at once and waits for some of them, model it with `parallel` and `join:
  {need: ...}`, a `timeout_ms` or deadline, and `stagger_ms` for hedged or speculative requests.
  Keep `foreach` for loops the code really runs one after another.
- **Events.** Listeners and subscribers use `subscribe:` on the interface and `publish:` at the
  source, with `delivery: sync` when the code calls listeners inline.
- **Boundary stubs.** When your behavior calls an interface another area owns, declare it in your
  fragment with `attributes: {boundary: true, owner: <area>}`, give it the owner's shapes, and
  leave out the behavior. Never model another area's internals.
- **No mocks.** Your scenarios drive branches with inputs, fixtures, `state`, `config`,
  `choices`, `faults` and `steps`. `mocks` are refused by the gate. If a branch depends on another
  area's answer, set that area's state through the fixture or `state`, so the real seam runs.
- **Flows** come from the inventory's entry points. Each modeled flow has an `entry` and
  scenarios: a happy path plus one per significant branch, each with `expect` that proves the
  branch and its cause.
- **Write, then read.** Every flow that writes state carries `tags: [writes]` and has at least one
  multi-step scenario that writes and then reads the effect back through the system's own read
  path (`steps: [{flow: <write>}, {flow: <read>}]`), asserting on the read's result. `--lint
  hollow` reports a `writes` flow without one. Steps never overlap; concurrency inside a step is
  `parallel`. Assert on `state` or `trace` in every scenario that writes, never only on `result.ok`.
- **Assert on your own calls and the outcome**, not on how many times another area's internal
  interfaces are called.
- **Scale.** Breadth first. Rough target per area: - `components`: `15`, `80`
- `flows`: `5`, `14`
- `scenarios`: `25`, `60`. Quality over volume, but
  every entry point is accounted for.

## Coverage: every entry point is modeled or skipped with a reason

The inventory is at `examples/vllm/inventory.json` (2580 entries: 627 triton-kernel, 457 torch-op, 391 model-registry, 305 python-cli, 258 torch-op-wrapper, 202 cuda-kernel, 111 python-api, 81 http-route, 71 engine-rpc, 44 busy-loop, 17 cli-command, 14 plugin, 2 cron). Each entry is
`{kind, name, file, line}`. Ownership and coverage per kind:

| Kind | Owner | What covers it | Level |
|---|---|---|---|
| http-route | path | an interface on the serving component named <method>-<path slug> citing the route |  |
| cli-command | path | a cli interface citing the subcommand |  |
| python-api | path | an interface on the API class named after the method |  |
| engine-rpc | path | the worker/engine method's interface, called via collective_rpc or the engine-core client |  |
| busy-loop | path | a flow with entry.repeat or timers that cites the loop |  |
| torch-op | path | the op's interface (kind kernel) citing its registration; latency as a CEL expression of the shapes | registered |
| torch-op-wrapper | path | the Python wrapper's interface calling the op |  |
| cuda-kernel | path | named in the launching op's behavior narrative (citation) | registered |
| triton-kernel | path | named in the launching function's behavior narrative (citation) | registered |
| model-registry | models-layers | an entry in the model registry state, resolved by model-registry.resolve | registered |
| plugin | path | the plugin loader's behavior cites it |  |
| python-cli | path | a flow citing the main |  |

Skip rules already decided: | kinds | match | reason |
|---|---|---|
| `python-cli` | examples/**, benchmarks/**, tools/** | not an entry point of the product: example, benchmark or repo tooling script |.

For every entry your area owns:
- **model it**: a flow-reachable interface or component cites the entry's own lines, or is named
  after it by the rules above. Covering an entry can be cheap: an entry interface whose behavior
  calls an already modeled component, with one happy-path scenario;
- **or skip it**: with a one-line reason. Heuristic false positives are skips too ("not an entry
  point: ...").

**Group skips go into `skips/<area>.json`, machine-readable.** Write a JSON array of
`{"kind", "name", "file", "line", "reason"}`, one object per inventory entry. Expand each group
into its exact entries, copying `kind`, `name`, `file` and `line` from the inventory. Your notes
keep the grouped, human-readable form ("the 212 getters in `FooMBean`: reads of config or
metrics, no behavior").

**A skip that says another entity covers the entry must name it**, in `"covered_by": "<kind>:<id>"`
(for example `"interface:git-service.commit"`). The coordinator's `assign_inventory.py` rejects a
reason that says "covered by" without the field, and a `covered_by` that names no entity in the
merged fragments. A rejected skip counts as uncovered.

**Thin behaviors don't count.** An interface whose behavior only returns, or sets a field or two
with no call, branch, `fail`, `emit`, `publish` or store, is **trivial**. It registers the entry but
doesn't model it: the check tool lists it under `--lint trivial`, leaves it out of the
**substantive** count, and fails your area when more than 35% of your entry-citing interfaces are
trivial (`--max-trivial 0.35`) or fewer than half your unskipped entries are substantive
(`--min-substantive 0.5`). Model the real control flow, or skip the entry with a reason.

## Oracle in the build (stage 4b)

`examples/vllm/build-oracle/<area>.json` lists 3 tests from your own paths
(`[{file, line, name}]`, drawn by the coordinator). Before hand-off, translate each one into a
scenario in your own fragment, with id `oracle-build-<area>-<n>`:
- the test's arrange step becomes `fixtures` and `state`; its act steps become `steps`; its
  asserts become `expect` over `result`, `state`, `steps` and `trace`;
- read the test, never run it;
- each must pass. When one fails, the model is wrong: fix the model, never the scenario. If the
  test checks something below the model's level, or needs a feature mosaic lacks, keep no
  scenario and record it in your notes as `untranslatable` (say what) or `sim-gap` (name the
  feature).

The final oracle (stage 6) draws a different sample, so these tests don't count twice.

## Verify before hand-off

```sh
cd <mosaic repo>
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
go run ./internal/devtools/check \
  -f examples/vllm/skeleton.yaml -f examples/vllm/fixtures.yaml -f examples/vllm/fragments/<area>.yaml \
  --code /home/lbethay/.cache/mosaic-bench/vllm-0.32.0 --strict-citations --inventory examples/vllm/inventory.json \
  --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35 \
  --behavior-coverage --lint hollow,trivial --no-mocks -v
# debugging one scenario:
go run ./internal/devtools/check -f ... --scenario '^<id>$' --trace
```

Hand off only when:
1. **0 errors, 0 failed scenarios, 0 scenario warnings, 0 mocks.** Warnings are usually a stub
   that guessed a shape.
2. **Citations resolve** (`--strict-citations`), and **support their claims**: run
   `--cite-sample 15 --seed <n>` twice with different seeds and read each
   sampled claim next to its code. Fix every bad one.
3. **No merge warnings that mention your fragment.**
4. **Coverage.** Every entry you own is covered in the `-v` output or listed in
   `skips/<area>.json`, and at least half the entries you own that aren't skipped are modeled
   (`--min-modeled 0.5`). Covered means registered: something reachable cites the entry. Modeled
   means an interface that cites the entry or is named for it has a behavior or a `store`, and
   some scenario calls it. At least half are **substantive** (`--min-substantive 0.5`): modeled by
   a non-trivial interface. At most 35% of your entry-citing interfaces are trivial
   (`--max-trivial 0.35`). Every "covered by" skip names its entity in `covered_by`.
5. **Hollow lint clean**, and **behavior coverage** at least 0.85
   for your area, with every `fail` and `if` branch run by some scenario or explained in your notes.
6. **Write-then-read**: every flow that writes state is tagged `writes` and has its read-back
   scenario (part of the hollow lint).
7. **In-build oracle**: each test in `build-oracle/<area>.json` is a passing
   `oracle-build-<area>-<n>` scenario, or is recorded in your notes as `untranslatable` or
   `sim-gap`.
8. **Shared data**: you hold no copy of a datum another area owns.

## Independent review

After hand-off, your fragment is merged, the repo's tests are run against it as scenarios, and
judges who didn't build it check it against the code. Their findings come back to you as fixes,
not suggestions. Write your notes so that a stranger can check them.

## Notes file (`notes/<area>.md`)

1. Entry points: each inventory entry in your area, with the flow or interface that covers it, or
   its skip reason (grouped).
2. The components you modeled, with code references.
3. The boundary stubs you declared, and whose contract you copied (skeleton, owner fragment, or
   shared shapes).
4. The config you read: deployed value and default, with references, and where they differ.
   Configs you own, and the owners of those you reference.
5. Fixture requests: state your cases needed that the shared fixtures lack.
6. What the code didn't settle, and the assumptions you made.
7. Where the docs, or common knowledge, disagree with the code.
8. **Simulator gaps**: behavior you couldn't express in mosaic, or only approximately. Give each
   an example and the code line.
9. Known gaps.
10. In-build oracle: one row per sampled test (test, scenario, verdict, cause).

## Report back (≤200 words)

Entity counts; the check tool's final lines (validation, citations, coverage, behavior coverage,
hollow lint, trivial lint, substantive, mocks); the in-build oracle verdicts; the flows you modeled; entries covered and skipped; fixture requests; the
top modeling gaps and simulator gaps.

## vLLM specifics

- **Processes and ranks.** Three kinds of process:
  - `api-server`: FastAPI, the OpenAI routes, tokenization and detokenization, AsyncLLM and its
    output processor;
  - `engine-core`: its own process, with the busy loop, scheduler, KV cache manager and executor;
  - `gpu-worker` instances `rank0..rankN`: the worker, model runner, model, attention and kernels.

  Calls that cross a process boundary are `rpc` interfaces called with `on:`:
  - ZMQ requests from AsyncLLM to the engine core;
  - `collective_rpc` from the executor to the workers, a `parallel` with `join: all` over the
    ranks.
- **Time is the point.** Model latency as CEL expressions of the batch shape, so scenarios can
  show batching, chunked prefill and throughput:
  - a prefill forward pass costs roughly `num_tokens * per_token_prefill_us / 1000`;
  - a decode step costs `base_ms + num_seqs * per_seq_decode_us / 1000`;
  - all-reduce costs grow with hidden size and TP degree.

  Put the coefficients in config entities, and cite where the code or docs suggest them. When
  the code gives no number, say so in your notes, and use an honest, labeled assumption.
- **Kernels.** A CUDA or Triton kernel is an interface of kind `kernel` on its op's component,
  with a latency expression and no simulated body. The inventory counts kernels as
  registered-level, so cite the kernel's own lines from the launching function.
- **The step loop.** The engine-core busy loop is a repeating flow (`entry.repeat`, or a timer)
  whose step is:
  1. `scheduler.schedule()`;
  2. `executor.execute_model` on the ranks;
  3. `scheduler.update_from_output`;
  4. outputs back to the API server.

  Requests arriving while a step runs land in the input queue, and are picked up at the next
  step. Use overlapping scenario steps (`at_ms`, `await: false`) to show this.
- **The KV cache is shared data owned by scheduler-kv.** The block pool, the per-request block
  tables and the prefix-cache hash map live on scheduler-kv's components. The worker and
  attention receive block tables in the `SchedulerOutput`, and never keep their own copy.
- **Cancellation.** Client disconnects and aborts use cancellation tokens (`token`, `cancel`).
- **Concurrency in time** (DESIGN §13.1 item 14) is opt-in per run.
  - A scenario switches it on by using `await: false` on a step, a `token` and `cancel`, a
    `restart`, or `max_virtual_ms`. Then steps, timers and `parallel` branches interleave in
    virtual time.
  - Use it wherever the code overlaps work: requests arriving during a step, an abort mid-stream,
    a worker dying mid-step.
  - Other new helpers: `eval(expr, vars)`, `replace` and `matches` in CEL, and dynamic `set`
    paths (`"= 'state.reqs.' + vars.id"`).
