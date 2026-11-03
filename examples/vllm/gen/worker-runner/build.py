#!/usr/bin/env python3
"""Build examples/vllm/fragments/worker-runner.yaml and skips/worker-runner.json.

Hand-written parts live next to this script (parts/*.yaml). This script adds
the kernel interfaces (kind kernel), whose sources are taken from the
inventory so every Triton kernel cites its own lines, and writes the skips.

Run: python3 -I examples/vllm/gen/worker-runner/build.py <mosaic repo root>
"""
import glob
import json
import os
import sys

import yaml

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
HERE = os.path.join(ROOT, "examples/vllm/gen/worker-runner")
INV = os.path.join(ROOT, "examples/vllm/inventory.json")
OUT = os.path.join(ROOT, "examples/vllm/fragments/worker-runner.yaml")
SKIPS = os.path.join(ROOT, "examples/vllm/skips/worker-runner.json")

# Kernel latencies are in ms with microsecond precision (DESIGN 13.1 item 16). The input
# preparation, sampling and spec-decode kernels here are launch-bound: about 5 us each
# (labeled assumption; the code gives no number).
KERNEL_US = 0.005

# (component, interface, [(file suffix, kernel name), ...], latency_ms, summary)
# The first kernel is the launched one; the rest are @triton.jit device helpers
# it calls, which have no launch of their own.
W = "vllm/v1/worker/gpu/"
KERNELS = [
    # input preparation and post-update (V2 model runner)
    ("input-batch", "prepare-prefill-inputs-kernel", [(W + "input_batch.py", "_prepare_prefill_inputs_kernel")], 0, "Copies the next prefill chunk's token ids into the input buffer."),
    ("input-batch", "prepare-pos-seq-lens-kernel", [(W + "input_batch.py", "_prepare_pos_seq_lens_kernel")], 0, "Computes positions and seq_lens from num_computed_tokens and query_start_loc."),
    ("input-batch", "combine-sampled-and-draft-tokens-kernel", [(W + "input_batch.py", "_combine_sampled_and_draft_tokens_kernel")], 0, "Writes the last sampled token and the draft tokens into input_ids and returns logits_indices."),
    ("input-batch", "get-num-sampled-and-rejected-kernel", [(W + "input_batch.py", "_get_num_sampled_and_rejected_kernel")], 0, "Counts sampled tokens per request; a chunked prefill that has not reached its prefill length samples none."),
    ("input-batch", "post-update-kernel", [(W + "input_batch.py", "_post_update_kernel")], 0, "Advances num_computed_tokens, records last sampled tokens, output bin counts and all_token_ids after sampling."),
    ("input-batch", "post-update-num-computed-tokens-kernel", [(W + "input_batch.py", "_post_update_num_computed_tokens_kernel")], 0, "Advances num_computed_tokens without sampling (pooling and non-last PP ranks)."),
    ("input-batch", "expand-idx-mapping-kernel", [(W + "input_batch.py", "_expand_idx_mapping_kernel")], 0, "Expands the request index mapping to one row per logit when draft tokens are scheduled."),
    ("block-tables", "gather-block-tables-kernel", [(W + "block_table.py", "_gather_block_tables_kernel")], 0, "Gathers the scheduled requests' block-table rows into the attention input buffer."),
    ("block-tables", "compute-slot-mappings-kernel", [(W + "block_table.py", "_compute_slot_mappings_kernel")], 0, "Maps each token position to its KV cache slot (block id * block size + offset), padding with PAD_SLOT_ID."),
    ("staged-write-tensor", "apply-write-kernel", [(W + "buffer_utils.py", "_apply_write_kernel"), (W + "buffer_utils.py", "_load_ptr")], 0, "Applies staged per-request CPU writes to the GPU tensor in one launch."),
    # sampling
    ("gumbel", "gumbel-sample-kernel", [
        (W + "sample/gumbel.py", "_gumbel_sample_kernel"), (W + "sample/gumbel.py", "gumbel_block_argmax"),
        (W + "sample/gumbel.py", "gumbel_noised_argmax"), (W + "sample/gumbel.py", "murmur3_uniform32"),
        (W + "sample/gumbel.py", "murmur3_uniform64"), (W + "sample/gumbel.py", "_uniform64_from_random53"),
        (W + "sample/gumbel.py", "murmur3_hash32"), (W + "sample/gumbel.py", "_murmur3_mix"),
        (W + "sample/gumbel.py", "_murmur3_rotl32"), (W + "sample/gumbel.py", "_murmur3_fmix32"),
        (W + "sample/gumbel.py", "_log1p_neg_stable"), (W + "sample/gumbel.py", "tl_rand32")],
        "= has(input.num_rows) ? 0.02 + double(input.num_rows) * 0.0005 : 0.02", "Gumbel-max sampling: argmax over logits plus seeded murmur3 Gumbel noise (plain argmax at temperature 0)."),
    ("gumbel", "temperature-kernel", [(W + "sample/gumbel.py", "_temperature_kernel")], 0, "Divides logits by each row's temperature."),
    ("min-p", "min-p-kernel", [(W + "sample/min_p.py", "_min_p_kernel")], 0, "Masks tokens whose probability is below min_p times the top probability."),
    ("topk-topp-triton", "topk-topp-kernel", [
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topk_topp_kernel"),
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_update_min_larger_stats")], 0, "Monolithic top-k / top-p truncation kernel."),
    ("topk-topp-triton", "topp-split-kernels", [
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topp_sb_stats_kernel"),
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topp_sb_step_kernel"),
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topp_sb_mask_kernel"),
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topp_sb_row_stats"),
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topp_sb_ladder"),
        ("vllm/v1/sample/ops/topk_topp_triton.py", "_topp_sb_combine")], 0, "Split-row top-p pipeline (stats, step, mask) used for small batches without an active top-k."),
    ("penalties-state", "penalties-kernel", [(W + "sample/penalties.py", "_penalties_kernel")], 0, "Applies repetition, frequency and presence penalties from prompt and output bin counts."),
    ("penalties-state", "bincount-kernel", [(W + "sample/penalties.py", "_bincount_kernel")], 0, "Counts prompt tokens per vocabulary id for a newly added penalised request."),
    ("logit-bias-state", "bias-kernel", [(W + "sample/logit_bias.py", "_bias_kernel")], 0, "Applies allowed_token_ids, logit_bias and the min_tokens stop-token mask."),
    ("bad-words-state", "bad-words-kernel", [(W + "sample/bad_words.py", "_bad_words_kernel")], 0, "Sets -inf on a bad word's last token where the committed output plus drafts end with its prefix."),
    ("logprob", "topk-log-softmax-kernel", [(W + "sample/logprob.py", "_topk_log_softmax_kernel")], 0, "Log-softmax of the requested token ids."),
    ("logprob", "ranks-kernel", [(W + "sample/logprob.py", "_ranks_kernel")], 0, "Rank of the sampled token among the vocabulary."),
    ("logprob", "fill-logprob-token-ids-kernel", [(W + "sample/logprob.py", "_fill_logprob_token_ids_kernel")], 0, "Fills per-request extra logprob token ids."),
    ("prompt-logprobs-worker", "prompt-logprobs-token-ids-kernel", [(W + "sample/prompt_logprob.py", "_prompt_logprobs_token_ids_kernel")], 0, "Gathers the prompt's next-token ids for prompt logprobs."),
    ("sampling-mask-tensors", "compact-sampling-mask-kernel", [(W + "sample/output.py", "_compact_sampling_mask_kernel")], 0, "Compacts the kept-token mask after top-k / top-p for return_sampling_mask."),
    ("gpu-logits-metrics", "num-nans-kernel", [(W + "metrics/logits.py", "_num_nans_kernel")], 0, "Counts NaN logits per row (VLLM_COMPUTE_NANS_IN_LOGITS)."),
    ("structured-outputs-worker", "apply-grammar-bitmask-kernel", [(W + "structured_outputs.py", "_apply_grammar_bitmask_kernel")], 0, "Masks logits outside the grammar bitmask of structured-output requests."),
    ("thinking-budget-state", "thinking-budget-kernel", [
        (W + "sample/thinking_budget.py", "_thinking_budget_kernel"),
        (W + "sample/thinking_budget.py", "_load_effective_token")], 0, "Forces the end-of-thinking marker once a request's thinking token budget is spent."),
    ("thinking-budget-state", "update-committed-marker-cache-kernel", [(W + "sample/thinking_budget.py", "_update_committed_marker_cache_kernel")], 0, "Tracks whether each request has committed the thinking start/end markers."),
    ("trace-replay-state", "trace-replay-kernel", [(W + "sample/trace_replay.py", "_trace_replay_kernel")], 0, "Overwrites sampled tokens with the replay trace."),
    ("gpu-watermark-sampler", "philox-gumbel-kernel", [
        (W + "sample/watermark.py", "_philox_gumbel_kernel"), (W + "sample/watermark.py", "philox_gumbel_block_argmax"),
        (W + "sample/watermark.py", "_philox_context_state"), (W + "sample/watermark.py", "_philox_candidate_words"),
        (W + "sample/watermark.py", "_philox4x32_10"), (W + "sample/watermark.py", "_mulhilo32"),
        (W + "sample/watermark.py", "_uint32_to_uniform"), (W + "sample/watermark.py", "_philox_gumbel_from_logits"),
        (W + "sample/watermark.py", "_gumbel_value"), (W + "sample/watermark.py", "_select_max")], 0,
        "Watermarked Gumbel sampling keyed by a Philox hash of the preceding context."),
    ("gpu-watermark-sampler", "repeated-context-mask-kernel", [(W + "sample/watermark.py", "_repeated_context_mask_kernel")], 0, "Marks rows whose watermark context repeats an earlier one (deduplicate_contexts)."),
    ("batch-sharder", "build-shard-plan-kernel", [(W + "sample/batch_shard.py", "_build_shard_plan_kernel")], 0, "Assigns requests to TP ranks for batch-sharded sampling."),
    ("batch-sharder", "pack-sampler-output-kernel", [(W + "sample/batch_shard.py", "_pack_sampler_output_kernel")], 0, "Packs this rank's sampler output for the all-gather."),
    ("batch-sharder", "unpack-gathered-output-kernel", [(W + "sample/batch_shard.py", "_unpack_gathered_output_kernel")], 0, "Unpacks the gathered sampler outputs into global batch order."),
    ("batch-sharder", "pack-logprobs-kernel", [(W + "sample/batch_shard.py", "_pack_logprobs_kernel")], 0, "Packs logprobs for the all-gather."),
    ("batch-sharder", "unpack-logprobs-kernel", [(W + "sample/batch_shard.py", "_unpack_logprobs_kernel")], 0, "Unpacks gathered logprobs."),
    # KV cache and model-specific state
    ("kv-block-zeroer", "zero-kv-blocks-kernel", [("vllm/v1/worker/utils.py", "_zero_kv_blocks_kernel")], 0, "Zeroes freshly allocated KV cache blocks so stale data cannot reach attention."),
    ("cp-utils", "dcp-local-seq-lens-kernel", [(W + "cp_utils.py", "_dcp_local_seq_lens_kernel"), (W + "cp_utils.py", "cp_local_slot")], 0, "Per-rank sequence lengths under decode context parallelism."),
    ("rope-state", "prepare-rope-positions-kernel", [(W + "mm/rope.py", "_prepare_rope_positions_kernel")], 0, "M-RoPE positions for multimodal requests."),
    ("mamba-hybrid-model-state", "scatter-num-accepted-kernel", [(W + "model_states/mamba_hybrid.py", "_scatter_num_accepted_kernel")], 0, "Scatters accepted-token counts into the Mamba state slots."),
    ("mamba-hybrid-model-state", "fill-num-accepted-kernel", [(W + "model_states/mamba_hybrid.py", "_fill_num_accepted_kernel")], 0, "Fills accepted-token counts for non-speculative steps."),
    ("mamba-utils", "preprocess-mamba-align-fused-kernel", [("vllm/v1/worker/mamba_utils.py", "preprocess_mamba_align_fused_kernel")], 0, "Resets per-request Mamba state indices at block boundaries before the forward."),
    ("mamba-utils", "precopy-mamba-align-fused-kernel", [("vllm/v1/worker/mamba_utils.py", "precopy_mamba_align_fused_kernel")], 0, "Copies recurrent state across block boundaries before the forward (align mode)."),
    ("mamba-utils", "postprocess-mamba-fused-kernel", [
        ("vllm/v1/worker/mamba_utils.py", "postprocess_mamba_fused_kernel"),
        ("vllm/v1/worker/mamba_utils.py", "_copy_mamba_state_block"),
        ("vllm/v1/worker/mamba_utils.py", "_memcpy_u64_tiled")], 0, "Copies the final recurrent state into the cached block after the forward."),
    ("mamba-utils", "batch-memcpy-kernel", [("vllm/v1/worker/mamba_utils.py", "batch_memcpy_kernel")], 0, "Batched device memcpy of Mamba state blocks."),
    ("mamba-utils", "get-aligned-state-indices-multi-group-kernel", [("vllm/v1/worker/mamba_utils.py", "get_aligned_state_indices_multi_group_kernel")], 0, "Computes the aligned state-block index per request and KV cache group."),
    ("prompt-embeds-state", "apply-prompt-embeds-kernel", [(W + "model_states/prompt_embeds.py", "_apply_prompt_embeds_kernel")], 0, "Overlays user-supplied prompt embeddings onto inputs_embeds."),
    ("recover-ssm-state", "postprocess-recoverssm-align-kernel", [(W + "model_states/recoverssm.py", "_postprocess_recoverssm_align_kernel")], 0, "Commits recovered SSM state for KDA models."),
    ("late-interaction-runner", "maxsim-rerank-kernel", [("vllm/v1/pool/flash_maxsim/flash_maxsim_rerank.py", "_maxsim_rerank_kernel")], 0, "Fused MaxSim late-interaction scoring of one shared query against many documents."),
    # speculative decoding (V2)
    ("rejection-sampler", "flatten-sampled-kernel", [(W + "spec_decode/rejection_sampler.py", "_flatten_sampled_kernel")], 0, "Flattens accepted tokens for logprob computation."),
    ("rejection-sampler", "gather-draft-sampled-kernel", [(W + "spec_decode/rejection_sampler.py", "_gather_draft_sampled_kernel")], 0, "Gathers the target's samples at draft positions."),
    ("rejection-sampler", "compute-local-logits-stats-kernel", [
        (W + "spec_decode/rejection_sampler_utils.py", "_compute_local_logits_stats_kernel"),
        (W + "spec_decode/rejection_sampler_utils.py", "_compute_max_and_sumexp")], 0, "Per-chunk max and sum-exp of target and draft logits."),
    ("rejection-sampler", "compute-cumulative-log-p-kernel", [(W + "spec_decode/rejection_sampler_utils.py", "_compute_cumulative_log_p_kernel")], 0, "Cumulative draft log-probabilities."),
    ("rejection-sampler", "compute-local-residual-mass-kernel", [(W + "spec_decode/rejection_sampler_utils.py", "_compute_local_residual_mass_kernel")], 0, "Residual probability mass max(0, p - q) per chunk."),
    ("rejection-sampler", "rejection-kernel", [
        (W + "spec_decode/rejection_sampler_utils.py", "_rejection_kernel"),
        (W + "spec_decode/rejection_sampler_utils.py", "_compute_global_logsumexp"),
        (W + "spec_decode/rejection_sampler_utils.py", "_compute_global_residual_mass"),
        (W + "spec_decode/rejection_sampler_utils.py", "_compute_global_target_argmax"),
        (W + "spec_decode/rejection_sampler_utils.py", "_compute_global_logprobs_and_logsumexp")], 0,
        "Accepts each draft token with probability min(1, p/q), or by argmax match when greedy, stopping at the first rejection."),
    ("rejection-sampler", "resample-kernel", [
        (W + "spec_decode/rejection_sampler_utils.py", "_resample_kernel"),
        (W + "spec_decode/rejection_sampler_utils.py", "_seeded_resample_argmax")], 0, "Resamples the rejected position from the residual distribution (or the bonus token)."),
    ("rejection-sampler", "insert-resampled-kernel", [(W + "spec_decode/rejection_sampler_utils.py", "_insert_resampled_kernel")], 0, "Writes the resampled token after the accepted prefix."),
    ("target-dependent-ar-speculator", "prepare-prefill-inputs-kernel", [(W + "spec_decode/target_dependent_ar/speculator.py", "_prepare_prefill_inputs_kernel")], 0, "Shifts the target's tokens and hidden states into the drafter's first step."),
    ("target-dependent-ar-speculator", "prepare-decode-inputs-kernel", [(W + "spec_decode/target_dependent_ar/speculator.py", "_prepare_decode_inputs_kernel")], 0, "Prepares the drafter's decode-step inputs."),
    ("target-dependent-ar-speculator", "update-draft-inputs-kernel", [(W + "spec_decode/target_dependent_ar/speculator.py", "_update_draft_inputs_kernel")], 0, "Feeds each draft token back as the next draft step's input."),
    ("standalone-ar-speculator", "prepare-prefill-inputs-kernel", [(W + "spec_decode/standalone_ar/speculator.py", "_prepare_prefill_inputs_kernel")], 0, "Prepares the independent draft model's prefill inputs."),
    ("dflash-speculator", "prepare-dflash-inputs-kernel", [(W + "spec_decode/dflash/speculator.py", "_prepare_dflash_inputs_kernel")], 0, "Builds DFlash's parallel-draft query block and context slots."),
    ("dflash2-speculator", "selector-walk-kernel", [(W + "spec_decode/dflash2/speculator.py", "_selector_walk_kernel")], 0, "Walks the candidate tree to pick DFlash2 drafts."),
    ("dflash2-speculator", "cache-draft-logits-kernel", [(W + "spec_decode/dflash2/speculator.py", "_cache_draft_logits_kernel")], 0, "Caches draft logits for probabilistic verification."),
    ("multi-module-mtp-speculator", "prepare-input-buffers-kernel", [(W + "spec_decode/multi_module_mtp/speculator.py", "_prepare_input_buffers_kernel")], 0, "Prepares the MTP modules' input buffers."),
    ("multi-module-mtp-speculator", "prepare-input-hidden-states-and-embeddings-kernel", [(W + "spec_decode/multi_module_mtp/speculator.py", "_prepare_input_hidden_states_and_embeddings_kernel")], 0, "Gathers hidden states and embeddings for each MTP module."),
    ("multi-module-mtp-speculator", "pad-trailing-draft-slots-kernel", [(W + "spec_decode/multi_module_mtp/speculator.py", "_pad_trailing_draft_slots_kernel")], 0, "Pads unused trailing draft slots."),
    ("multi-module-mtp-speculator", "cache-inputs-kernel", [(W + "spec_decode/multi_module_mtp/speculator.py", "_cache_inputs_kernel")], 0, "Caches the next step's MTP inputs."),
    ("multi-module-mtp-speculator", "shift-input-ids-kernel", [(W + "spec_decode/multi_module_mtp/speculator.py", "_shift_input_ids_kernel")], 0, "Shifts input ids by one draft position."),
    ("multi-module-mtp-speculator", "shift-input-embeds-kernel", [(W + "spec_decode/multi_module_mtp/speculator.py", "_shift_input_embeds_kernel")], 0, "Shifts input embeddings by one draft position."),
    ("ngram-gpu-speculator", "ngram-scan-kernel", [(W + "spec_decode/ngram/speculator.py", "_ngram_scan_kernel")], 0, "Scans each request's tokens for the latest n-gram match."),
    ("ngram-gpu-speculator", "ngram-finalize-kernel", [(W + "spec_decode/ngram/speculator.py", "_ngram_finalize_kernel")], 0, "Emits the tokens that followed the match as drafts."),
    ("online-acceptance-estimator", "accumulate-kernel", [(W + "spec_decode/acceptance_estimator.py", "_accumulate_kernel")], 0, "Accumulates acceptance statistics."),
    ("online-acceptance-estimator", "refit-kernel", [(W + "spec_decode/acceptance_estimator.py", "_refit_kernel")], 0, "Refits the acceptance model."),
    ("online-acceptance-estimator", "local-max-sumexp-kernel", [(W + "spec_decode/acceptance_estimator.py", "_local_max_sumexp_kernel")], 0, "Partial max and sum-exp of draft logits."),
    ("online-acceptance-estimator", "predict-kernel", [(W + "spec_decode/acceptance_estimator.py", "_predict_kernel")], 0, "Predicts per-position acceptance to size the next draft."),
    # V1 model runner path
    ("block-table", "compute-slot-mapping-kernel", [("vllm/v1/worker/block_table.py", "ComputeSlotMappingKernel.kernel")], 0, "V1 slot mapping from block tables."),
    ("rejection-sampler-v1", "rejection-greedy-sample-kernel", [("vllm/v1/sample/rejection_sampler.py", "rejection_greedy_sample_kernel")], 0, "V1 greedy draft verification."),
    ("rejection-sampler-v1", "rejection-random-sample-kernel", [("vllm/v1/sample/rejection_sampler.py", "rejection_random_sample_kernel")], 0, "V1 probabilistic draft verification."),
    ("rejection-sampler-v1", "expand-kernel", [("vllm/v1/sample/rejection_sampler.py", "expand_kernel")], 0, "V1 expansion of per-request values to per-token rows."),
    ("rejection-sampler-v1", "sample-recovered-tokens-kernel", [("vllm/v1/sample/rejection_sampler.py", "sample_recovered_tokens_kernel")], 0, "V1 recovered-token sampling from the residual distribution."),
    ("spec-decode-utils", "eagle-step-slot-mapping-metadata-kernel", [("vllm/v1/spec_decode/utils.py", "eagle_step_slot_mapping_metadata_kernel")], 0, "V1 EAGLE per-step slot mapping metadata."),
    ("spec-decode-utils", "eagle-prepare-inputs-padded-kernel", [("vllm/v1/spec_decode/utils.py", "eagle_prepare_inputs_padded_kernel")], 0, "V1 EAGLE padded input preparation."),
    ("spec-decode-utils", "eagle-prepare-next-token-padded-kernel", [("vllm/v1/spec_decode/utils.py", "eagle_prepare_next_token_padded_kernel")], 0, "V1 EAGLE next-token preparation."),
    ("spec-decode-utils", "copy-and-expand-eagle-inputs-kernel", [("vllm/v1/spec_decode/utils.py", "copy_and_expand_eagle_inputs_kernel")], 0, "V1 EAGLE parallel-drafting input expansion."),
    ("spec-decode-utils", "copy-and-expand-dflash-inputs-kernel", [("vllm/v1/spec_decode/utils.py", "copy_and_expand_dflash_inputs_kernel")], 0, "V1 DFlash input expansion."),
]

SKIP_REASONS = {
    ("torch-op-wrapper", "_xpu_memcpy_sync"): "not deployed: XPU-only sleep-mode allocator copy (vllm/device_allocator/xpumem.py); the modeled deployment is CUDA, whose sleep mode is cu-mem-allocator",
}


def fix_on(x):
    """PyYAML (YAML 1.1) reads the key `on` as True; mosaic uses YAML 1.2."""
    if isinstance(x, dict):
        return {("on" if k is True else k): fix_on(v) for k, v in x.items()}
    if isinstance(x, list):
        return [fix_on(v) for v in x]
    return x


def main():
    inv = json.load(open(INV))["entries"]
    mine = [e for e in inv if e.get("area") == "worker-runner"]
    by_key = {}
    for e in mine:
        by_key[(e["file"], e["name"])] = e

    doc = {"schema_version": 1, "id": "vllm"}
    lists = ["configs", "components", "interfaces", "schemas", "flows", "fixtures", "scenarios"]
    for k in lists:
        doc[k] = []
    for p in sorted(glob.glob(os.path.join(HERE, "parts", "*.yaml"))):
        part = fix_on(yaml.safe_load(open(p)) or {})
        for k in lists:
            doc[k].extend(part.get(k) or [])

    # Boundary config copies follow their owner's definition when the owner's fragment has one
    # (RECONCILE decision 1): same type, value, default and attributes, plus boundary/owner.
    owners = {}
    for f in glob.glob(os.path.join(ROOT, "examples/vllm/fragments/*.yaml")):
        if f.endswith("worker-runner.yaml"):
            continue
        for c in (yaml.safe_load(open(f)) or {}).get("configs") or []:
            if not (c.get("attributes") or {}).get("boundary"):
                owners[c["id"]] = c
    for c in doc["configs"]:
        a = c.get("attributes") or {}
        if a.get("boundary") and c["id"] in owners:
            o = owners[c["id"]]
            for k in ("type", "value", "default"):
                if k in o:
                    c[k] = o[k]
                elif k in c and k != "value":
                    del c[k]
            c["attributes"] = dict(o.get("attributes") or {}, boundary=True, owner=a["owner"])

    used = set()
    for comp, name, ks, lat, summary in KERNELS:
        srcs = []
        for f, kname in ks:
            e = by_key[(f, kname)]
            used.add((f, kname))
            end = e.get("end_line") or e["line"]
            srcs.append(f"{f}:{e['line']}-{end}" if end > e["line"] else f"{f}:{e['line']}")
        doc["interfaces"].append({
            "component": comp,
            "name": name,
            "kind": "kernel",
            "summary": summary,
            "sources": srcs,
            "attributes": {"triton_kernels": [k for _, k in ks]},
            "request": {"type": "object", "properties": {"num_tokens": {"type": "integer", "examples": [16]}, "num_rows": {"type": "integer", "examples": [4]}}},
            "latency_ms": KERNEL_US if lat == 0 else lat,
        })

    for k in lists:
        if not doc[k]:
            del doc[k]
    with open(OUT, "w") as f:
        f.write("# worker-runner fragment of the vLLM v0.32.0 ontology (gpu-worker module).\n")
        f.write("# Generated by examples/vllm/gen/worker-runner/build.py from parts/*.yaml plus\n")
        f.write("# the kernel table in build.py. Edit the sources, not this file.\n")
        yaml.safe_dump(doc, f, sort_keys=False, width=110, allow_unicode=True)

    skips = []
    for e in mine:
        key = (e["kind"], e["name"])
        if key in SKIP_REASONS:
            skips.append({"kind": e["kind"], "name": e["name"], "file": e["file"], "line": e["line"], "reason": SKIP_REASONS[key]})
    with open(SKIPS, "w") as f:
        json.dump(skips, f, indent=1)
        f.write("\n")

    missing = [e for e in mine if e["kind"] == "triton-kernel" and (e["file"], e["name"]) not in used]
    for e in missing:
        print("kernel not in table:", e["file"], e["name"], file=sys.stderr)
    print(f"wrote {OUT}: {sum(len(doc.get(k, [])) for k in lists)} entities; {len(skips)} skips; {len(missing)} kernels missing")


if __name__ == "__main__":
    main()
