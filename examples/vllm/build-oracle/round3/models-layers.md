# Round-3 in-build oracle: models-layers

| Test | Scenario | Verdict | Cause |
|---|---|---|---|
| `tests/models/language/pooling_mteb_test/test_intfloat.py:55` test_embed_models_mteb | `oracle-r3-models-layers-intfloat-embed` | pass (model-level part) | BertModel → `bert.BertEmbeddingModel` and XLMRobertaModel → `roberta.RobertaEmbeddingModel` resolve from the embedding table as pooling models (`registry.py:215, 247`). The MTEB score is numerical, so it is untranslatable. The pooler type, attn_type and prefix-caching checks belong to config-platform's ModelConfig. |
| `tests/utils_/test_tensor_schema.py:127` test_tensor_schema_inconsistent_shapes_in_list | `oracle-r3-models-layers-tensor-schema-inconsistent` | pass | Newly modeled as `phi3v-image-pixel-inputs.validate` (TensorSchema `_validate_field`, `tensor_schema.py:100-149`), with shapes given as lists. |
| `tests/model_executor/test_ernie45_vl_mrope.py:84` test_get_mrope_input_positions_single_image | `oracle-r3-models-layers-ernie-mrope-single-image` | pass | Newly modeled as `ernie45-vl-moe-for-conditional-generation.get-mrope-input-positions` (`ernie45_vl.py:1496-1560`). It returns exact positions and delta. |
| `tests/models/multimodal/processing/test_h2ovl.py:149` test_processor_override | none | untranslatable | The expected patch count comes from the pixel dimensions of a real image asset and from H2OVL's dynamic-tiling HF processor. The test then checks the length of a tensor (`pixel_values_flat.shape[0]`) and counts tokenizer ids. The model only has placeholder counts per item (`base-multi-modal-processor.apply`), not image tiling. |
| `tests/models/kimi_k3/test_amd_kda_decode.py:238` test_fused_kda_decode_without_output_norm | none | untranslatable | Compares a Kimi-K3 AMD KDA decode kernel's output tensors with a reference implementation, which is kernel numerics. Kimi-K3 is registry-level only. |
| `tests/models/transformers/fusers/test_moe.py:278` test_moe_fuser_matches_grouped_router | none | untranslatable | `MoEBlockFuser.match` inspects a meta-device `nn.Module` tree and the router's traced operations (group masking before top-k). That is Python module introspection with no counterpart in the model. |

Passing: 3 of 6. The other 3 are untranslatable for the reasons above.
