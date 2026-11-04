# Round-5 in-build oracle: models-layers

Run: the merged `-f` list plus `-f examples/vllm/build-oracle/round5/models-layers.yaml --scenario '^oracle-r5-models'` (4 passed).

| Test | Scenario | Verdict | Notes |
|---|---|---|---|
| tests/lora/test_sequence_classification.py:70 `test_native_classification_model_with_modules_to_save` | oracle-r5-models-layers-native-cls-modules-to-save | partial: passes | Translated the adapter side: `_validate_modules_to_save` accepts a `score` full module of shape (1, 1024) against the native classifier's head, and refuses a wider or misnamed module with the code's messages (`vllm/lora/model_manager.py:1273-1313`, called from `worker_manager.py:158`). The classify logits are numeric and untranslatable. |
| tests/models/multimodal/test_cohere_asr.py:74 `test_get_num_audio_tokens_streaming_estimate` | oracle-r5-models-layers-cohere-asr-streaming-estimate | pass | `cohere-asr-for-conditional-generation.get-num-audio-tokens`: 13, 125 and 375 tokens (`cohere_asr.py:2189-2203`). |
| tests/quantization/test_int8_moe_oracle.py:94 `test_scaled_int8_quant_is_available_on_xpu` | none | untranslatable | An XPU-only check of `ops.scaled_int8_quant`'s output tensor (dtype, shape, returned scale). The op is kernels-ops' `_custom_ops`, and the assertions are tensor-level. |
| tests/models/kimi_k3/test_kda_metadata.py:788 `test_cudagraph_capture_metadata_avoids_device_to_host_copy` | none | untranslatable | Checks that the KDA metadata builder doesn't synchronize the device (monkeypatched tensor `.tolist`/D2H copies). Kimi K3 is registry-level, and device synchronization is below the model's level. |
| tests/quantization/test_config_utils.py:83 `test_find_matching_patterns_for_fused_regexes` | oracle-r5-models-layers-fused-regex-patterns | pass | `quant-config-utils.find-matching-patterns`: both parametrizations give one match per shard set; also the direct/per-shard distinction and opt-in fnmatch (`config_utils.py:344-412`). |
| tests/quantization/test_online.py:570 `test_online_overlay_requires_normalized_quantization_config` | oracle-r5-models-layers-online-overlay-normalized | pass | `weight-utils.get-quant-config` with a raw-dict `online_args` over a compressed-tensors checkpoint fails `assertion-error` in `maybe_compose_online_quantization` (`weight_utils.py:214-224`); normalized args compose. |

Result: 4 of 6 pass (one of them partial), 2 untranslatable.
