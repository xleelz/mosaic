# Oracle 4: distributed

Snapshot: vLLM v0.32.0 (`/home/lbethay/.cache/mosaic-bench/vllm-0.32.0`). Model: `examples/vllm/vllm.json`.
Fragment: `oracle4/distributed.yaml` (no runnable scenarios; each test is explained below).

| Test | Behavior | Scenario | Verdict | Entity at fault / missing feature | Evidence |
|---|---|---|---|---|---|
| `tests/distributed/test_eplb_fused_moe_layer.py:265` `test_eplb_fml` | After `rearrange_expert_weights_inplace(old=identity, new=random perm)` across 2 EP ranks, rank r's local expert slot e of every MoE layer holds the weights (and scales, column- or row-major, stride preserved) of global expert `new[r*nle+e]` | none | model-bug | distributed: no EPLB weight rearrangement in the model. `eplb-state` has only `add-model` and `start-async-loop`; there is no `EplbState.rearrange` / `rearrange_expert_weights_inplace` / `transfer_layer` / EPLB communicator, and no per-rank expert placement state to assert on | Code: `vllm/distributed/eplb/rebalance_execute.py:642` (`rearrange_expert_weights_inplace`), `:551` (`transfer_layer`), `:275`/`:474` (move to/from buffer), `vllm/distributed/eplb/eplb_state.py:758` (`EplbState.rearrange`), `vllm/distributed/eplb/eplb_communicator.py:702` (`create_eplb_communicator`). Model search for `rearrange`/`eplb` finds only `eplb-controller.load`, `eplb-state.add-model`, `eplb-state.start-async-loop`, router EPLB hooks |
| `tests/v1/kv_connector/nixl_integration/test_accuracy_rocm.py:33` `test_rocm_pd_accuracy` | ROCm P/D disaggregation (NIXL, AITER unified attention): GSM8K accuracy through a P/D proxy matches upstream, and the decoder's `prompt_tokens_by_source{source=external_kv_transfer}` and `nixl_bytes_transferred` counters rise during the run | none | untranslatable | The asserted outcome is model accuracy (GSM8K) on ROCm/AITER kernels, below the model. Note: the secondary transfer-counter check would also have no target: the model has no end-to-end P/D proxy flow and no `vllm:prompt_tokens_by_source` / `nixl_bytes_transferred` metrics | `tests/v1/kv_connector/rocm_pd_accuracy_utils.py:209-265`; `vllm/v1/metrics/loggers.py:757-766`, `vllm/v1/metrics/stats.py:432-444` |
| `tests/distributed/test_context_parallel.py:290` `test_cp_generation` | A server with TP x PP x DCP (decode context parallel) and the given interleave size reaches GSM8K accuracy >= the model's threshold | none | untranslatable | Model accuracy (lm_eval GSM8K exact match) is below the model | `tests/distributed/test_context_parallel.py:164-286` (only assertion: `accuracy >= min_accuracy`) |
| `tests/v1/kv_connector/unit/test_moriio_transfer_completion.py:40` `test_timeout_must_be_positive_and_finite` | `_positive_finite_timeout(name, v)` raises `ValueError("... must be finite and greater than zero")` for 0, -1, inf, nan; it guards `transfer_timeout`, `defer_timeout` and `recv_abort_timeout` from `kv_connector_extra_config` when MoRIIOConfig is built | none | model-bug | distributed: MoRIIO config construction is missing. No interface builds MoRIIOConfig from `kv_connector_extra_config` (backend check, port math, the three timeouts); `moriio-writer` takes `defer_timeout_ms` as seeded state with no validation, and `transfer_timeout` / `recv_abort_timeout` do not exist | Code: `vllm/distributed/kv_transfer/kv_connector/v1/moriio/moriio_common.py:49-53` (validator), `:345-368` (the three uses in the config factory), `:338-343` (backend check). Model: grep for `transfer_timeout`, `recv_abort`, `finite and greater` in `vllm.json` finds none for MoRIIO |
| `tests/v1/kv_connector/unit/test_hf3fs_connector.py:48` `TestHf3fsMockClient::test_init_creates_file` | The file-backed HF3FS mock client creates its backing file at the given size on init | none | untranslatable | Checks a file's existence and byte size on the local filesystem, created by the debug/test mock client (`f.truncate(size)`); below the model's level | `vllm/distributed/kv_transfer/kv_connector/v1/hf3fs/utils/hf3fs_mock_client.py:15-28` |

Totals: pass 0, model-bug 2, test-mismatch 0, sim-gap 0, untranslatable 3.

## Fix requests

### distributed

1. **EPLB rearrangement.** Add `eplb-state.rearrange` (EplbState.rearrange, `eplb_state.py:758`) and
   `rebalance-execute.rearrange-expert-weights-inplace` (`rebalance_execute.py:642`): per layer,
   compute the old/new physical-to-logical maps, the experts each EP rank must send and receive
   (`get_ep_ranks_with_experts_batch`, `:67`), move through the expert buffer and the communicator
   (`create_eplb_communicator`, `eplb_communicator.py:702`, backends torch_nccl/torch_xccl/gloo/pynccl/nixl),
   and record per-rank `expert_slots[layer][local_idx] = logical expert id` so a scenario can assert
   that after `rearrange(old, new)` rank r slot e holds `new[r * num_local_experts + e]`. Model the
   all-to-all as calls per peer rank so traces show which rank sent what.
2. **MoRIIO config validation.** Add `moriio-config.from-vllm-config` (`moriio_common.py:318-390`):
   reject a backend other than `rdma`/`xgmi`, and reject `transfer_timeout`, `defer_timeout` and
   `recv_abort_timeout` (and the deprecated `VLLM_MORIIO_TRANSFER_TIMEOUT_S`) that are not finite and
   > 0 with `ValueError("kv_connector_extra_config.<name> must be finite and greater than zero")`;
   feed the accepted values into `moriio-writer` (`defer_timeout_ms`) and the wrapper's wait/abort
   timeouts instead of seeding them as state.
