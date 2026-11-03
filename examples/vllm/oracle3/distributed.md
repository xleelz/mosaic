# Oracle round 3: distributed

| Test | Behavior | Scenario | Verdict | At fault / missing | Evidence |
|---|---|---|---|---|---|
| tests/distributed/test_kv_cache_events.py:102 `test_block_stored_default_group_idx_is_none` | `BlockStored.group_idx` defaults to None (`vllm/distributed/kv_events.py:82`) | `oracle-distributed-block-stored-default-group-idx-is-none` | pass | none | A BlockStored without group_idx goes through `kv-event-aggregator` and comes back with group_idx null (default in `DistKvCacheEvent`) |
| tests/v1/kv_connector/unit/test_scheduler_kv_connector_override.py:120 `test_connector_receives_block_hashes` | With a KV connector, `schedule()` builds the connector metadata from a block state covering the scheduled requests, and requests carry their full-block hashes. The block state is stripped before dispatch (`scheduler.py:1459-1547`) | `oracle-distributed-connector-receives-block-hashes` | pass | none | With ExampleConnector, each 48-token request has 3 hashes. `build-connector-meta` gets each new request's block ids, equal to `scheduled_new_reqs`. The output has `kv_connector_metadata` and no `kv_connector_block_state`. The plugin overriding `Scheduler._build_kv_connector_meta` and the DummyKVConnector are test code and untranslatable. Caveat: the model passes `scheduled_new_reqs`, not a block state over every scheduled request (`scheduler.py:1464-1472`), which this test doesn't separate |
| tests/distributed/test_distributed_oot.py:7 `test_distributed_oot` | With a plugin-registered OOT architecture, TP=2 serves a chat completion whose text is only the forced first token | `oracle-distributed-oot-model-tp2` | untranslatable | none | The assertion is on text from `MyOPTForCausalLM.compute_logits`, which zeroes the logits: below the model. The registry part passes (register-model, then resolve-model-cls to MyOPTForCausalLM). Side finding for config-platform: `plugins.load-general-plugins` targets only the resolvers and calls them with no input. So a general plugin calling `ModelRegistry.register_model`, the test's real path, can't be expressed |
| tests/distributed/test_torchrun_example.py:55 `test_consistent_across_ranks` | Under torchrun (`external_launcher`), ranks with different `gpu_memory_utilization` agree on num_gpu_blocks, because `determine_available_memory` all-reduces MIN over the world CPU group (`vllm/v1/executor/uniproc_executor.py:161-207`) | `oracle-distributed-torchrun-consistent-across-ranks` | model-bug | engine-core: `executor` / `uni-proc-executor` for ExecutorWithExternalLauncher | Startup fails: only rank0 runs, the profile run's TP all-reduce waits for absent ranks, and it fails with `dist-backend-error` at 600 s. No MIN all-reduce of the budget exists |

Verdicts: 2 pass, 1 model-bug, 1 untranslatable.

## Fix requests

**engine-core**
1. Model ExecutorWithExternalLauncher (`uniproc_executor.py:161-207`) as one engine per launcher rank, each with its own worker (`env://` rank/local_rank), rather than UniProcExecutor's rank0 only. Its `determine_available_memory` all-reduces the budget with MIN over the world CPU group (`group-coordinator.all-reduce`), so every rank's `initialize-kv-caches` sizes the same num_gpu_blocks.

**config-platform** (side finding, from test_distributed_oot)
2. Let `plugins.load-general-plugins` run a plugin that registers models. It needs `model-registry.register-model` in targets, plus a per-entry-point input, for example `{model_arch, model_cls}` from the entry-point state (`vllm/plugins/__init__.py:77-90`).
