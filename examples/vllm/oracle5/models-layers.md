# Oracle 5: models-layers

Run with `check -f vllm.json -f oracle5/models-layers.yaml --no-mocks --lint hollow -v`: validation
0 errors, 1 scenario passed, 5 failed, 0 mocks. The hollow lint has one advisory, on the Triton
scenario's warmup flow.

Entries in the sample: 7. Rows: 7.

| Verdict | Count |
|---|---|
| pass | 1 |
| model-bug | 5 |
| test-mismatch | 0 |
| sim-gap | 0 |
| untranslatable | 1 |

The validator refuses a scenario that names an unknown interface. So the three tests whose code has
no entity at all (Triton, Gemma4, decoder replay) run a real nearby entity and assert that the
missing interface was reached. Their failure shows absence only; it isn't a behavior comparison.

## Results

| Test | Behavior and code under test | Scenario | Verdict | Entity at fault | Evidence |
|---|---|---|---|---|---|
| `tests/models/kimi_k3/test_amd_kda_checkpoint.py:110` | A prefill checkpoint names the last aligned boundary: offsets [192, 64], state indices [2, 4]. `KimiK3ROCmKDAMetadataBuilder.build` (`vllm/models/kimi_k3/amd/kda_metadata.py:96`), `MambaPrefillCheckpointBuilder.build` (`vllm/model_executor/layers/mamba/checkpoint.py:101`) | `oracle-models-layers-kda-checkpoint-last-aligned-boundary` | model-bug | `gdn-attention-metadata-builder.build` | The trace takes "Plain path" and returns no `checkpoint`. The request has no `seq_lens`. Hand evaluation of the code agrees with the test: `get_mamba_prefill_checkpoint_position` gives 192 and 64, `cdiv(seq_len, 64) - 2` gives columns 2 and 0, and the arange table gives blocks 2 and 4. |
| `tests/models/language/pooling_mteb_test/test_nemotron.py:47` | The embed model resolves to `LlamaBidirectionalModel` with MEAN pooling, encoder_only attention, no prefix caching and no chunked prefill. `LlamaBidirectionalConfig.verify_and_update_model_config` (`vllm/model_executor/models/config.py:601`), called from `VllmConfig.try_verify_and_update_config` (`vllm/config/vllm.py:2629`, called at `:1443`) | `oracle-models-layers-nemotron-embed-model-config` | model-bug | `vllm-config.post-init`; no hook interface exists | The architecture assertion passes. Seq pooling, attn_type and both support properties fail. No interface cites the hook or `MODELS_CONFIG_MAP`, so `is_causal` stays at its default and the registry row's LAST default stands. The code sets `is_causal = False` and maps `pooling: avg` to MEAN. MTEB score and embedding values are untranslatable and left out. |
| `tests/model_executor/test_jit_warmup.py:120` | An integer maps to the representative of its Triton cache-key class (14 parameters). `triton_scalar_specialization_rep` (`vllm/model_executor/warmup/jit_warmup_triton_helper.py:135`) | `oracle-models-layers-triton-scalar-specialization-rep` | model-bug (missing, low severity) | no entity | No interface cites the helper; `gpu-worker-impl.compile-or-warm-up-model` only sets `ctx.jit_warmup`. The code's three ranges and `value % 16` agree with the test's table, which is in the scenario's description. The inputs fit the simulator (`$bigint`, `uint`), so this isn't a sim gap. Judgment call: it is plain integer logic, so I didn't call it untranslatable, but it is the closest of the five to being below the model's level. |
| `tests/models/multimodal/test_conformer_encoder.py:83` | The baddbmm `RelPosMultiHeadAttention.forward` matches the pre-baddbmm reference numerically, with the right shapes and contiguous outputs. `vllm/model_executor/models/conformer_encoder.py:188` | none | untranslatable | none | `torch.testing.assert_close` on tensors, shapes and `is_contiguous()`: kernel numerics and memory layout. |
| `tests/models/multimodal/processing/test_gemma4_unified.py:24` | `Gemma4ImagePixelInputs` accepts list items of different patch counts, since `np` is dynamic. `vllm/model_executor/models/gemma4_mm.py:127`, `TensorSchema._validate_field` (`vllm/utils/tensor_schema.py:100`) | `oracle-models-layers-gemma4-image-schema-variable-patch-counts` | model-bug (missing) | no entity; nearest is `phi3v-image-pixel-inputs.validate` | The registry row resolves to `gemma4_mm`, and nothing validates its inputs. The only TensorSchema interface is fixed to Phi3V's fields and requires channel dim 3, so it can't stand in. |
| `tests/models/test_qwen3_5_mtp_config.py:55` | Text-only Qwen3.5 types map to the same MTP architectures as the multimodal ones. `SpeculativeConfig.hf_config_override` (`vllm/config/speculative.py:917-937`) | `oracle-models-layers-mtp-override-text-only-types` | pass | none | All 4 parameters match, and the trace takes the "Qwen3.5 counts mtp_num_hidden_layers" row at the code's line range. |
| `tests/models/test_deepseek_v41_decoder_replay_layers.py:69` | Every row's KV is written once, then the layers run on the replay rows under the replay context, the outer context is restored, and trimmed rows stay zero. `DecoderReplayLayers.__call__` and `_run` (`vllm/models/deepseek_v41/decoder_replay_layers.py:70`, `:108`) | `oracle-models-layers-decoder-replay-run-gathers-states` | model-bug (missing) | no entity | `DeepseekV41ForCausalLM` is only a registry row. The test's `MagicMock` and closure are callback arguments, so real collaborators could drive this once the entity exists. The tensor equality in the test is left out as untranslatable. |

`inventory.json` marks `vllm/models/kimi_k3` code as architecture-specific and covered by
`model-registry`, with forward modeled in depth only for Llama and Mixtral. That makes the KDA gap a
scope decision (I didn't check for an equivalent entry for `deepseek_v41`). The tests still can't run
on the model, so the verdict stands.

Not in the sample, read but not run: `speculative-config.hf-config-override` sets `n_predict` to null
when `mtp_num_hidden_layers` is only in `text_config`. The code falls back to `get_hf_text_config`
(`vllm/config/speculative.py:928-931`), which
`test_mtp_override_extracts_n_predict_from_multimodal_wrapper` covers.

## Fix requests

### config-platform

1. Add `VllmConfig.try_verify_and_update_config` with the `MODELS_CONFIG_MAP` dispatch
   (`vllm/config/vllm.py:2629-2667`, `vllm/model_executor/models/config.py:1090`), with
   `LlamaBidirectionalConfig` as a row: it sets `is_causal = False`, maps `pooling` avg, cls and last
   to MEAN, CLS and LAST, and raises `ValueError` on a missing or unknown `pooling`.
   Keep the code's order: the hook runs in `VllmConfig.__post_init__`, after
   `engine-args.set-default-chunked-prefill-and-prefix-caching-args` reads the properties
   (`vllm/engine/arg_utils.py:2990`).

### attention

2. Give `gdn-attention-metadata-builder.build` the prefill checkpoint: take `seq_lens`, build
   `MambaPrefillCheckpointBuilder.build` (`vllm/model_executor/layers/mamba/checkpoint.py:101-157`),
   and return `checkpoint` with offsets and state indices. Model
   `get_mamba_prefill_checkpoint_position` and `is_mamba_prefill_checkpoint_valid`
   (`vllm/v1/kv_cache_interface.py:1110-1146`).

### models-layers

3. Add `KimiK3ROCmKDAMetadataBuilder.build`, which rebuilds the checkpoint on the prefill rows
   (`vllm/models/kimi_k3/amd/kda_metadata.py:96-147`), once request 2 is done.
4. Add `DecoderReplayLayers`: `__call__`, `uses_replay_batch`, `_run` and the graph break
   (`vllm/models/deepseek_v41/decoder_replay_layers.py`).
5. Add a TensorSchema validation that takes a field's declared shape and dynamic dims, and declare
   `Gemma4ImagePixelInputs` on it (`vllm/model_executor/models/gemma4_mm.py:127-150`,
   `vllm/utils/tensor_schema.py`).
6. Add `triton_scalar_specialization_rep` to the warmup components
   (`vllm/model_executor/warmup/jit_warmup_triton_helper.py:135-168`). Low priority.
