"""Assemble examples/vllm/fragments/attention.yaml and skips/attention.json.

Run: python3 -I examples/vllm/gen/attention/build.py   (reads the vLLM snapshot, read-only)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml  # noqa: E402

import core  # noqa: E402
import core2  # noqa: E402
import core3  # noqa: E402
import lib  # noqa: E402
import scen  # noqa: E402
import tail  # noqa: E402
import round3  # noqa: E402
import round4  # noqa: E402
import round4b  # noqa: E402

OUT = os.path.join(lib.HERE, "..", "..")

SKIP_RULES = [
    ("vllm/v1/attention/ops/rocm_aiter_mla_sparse.py", "ROCm-only (AMD aiter) sparse-MLA kernels for DeepSeek on MI300/MI355; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/backends/mla/rocm_aiter_mla_sparse.py", "ROCm-only (AMD aiter) sparse-MLA backend kernels; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/backends/mla/rocm_aiter_mla.py", "ROCm-only (AMD aiter) MLA backend kernel; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/backends/rocm_aiter_fa.py", "ROCm-only (AMD aiter) FlashAttention backend kernels; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/rocm_paged_mxfp4_indexer.py", "ROCm-only MXFP4 paged indexer; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/rocm_aiter_mla_merge.py", "ROCm-only aiter MLA segment merge; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/flydsl_", "ROCm-only FlyDSL decode path (TurboQuant/UltraQuant on AMD); the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/xpu_mla_sparse.py", "Intel XPU-only sparse MLA kernel; the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/segmented_attention.py", "used only by the ROCm segmented-attention backend (rocm_segmented_attn.py); the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/chunked_prefill_paged_decode.py", "used only by the ROCm attention backend (rocm_attn.py); the fixtures deploy on CUDA"),
    ("vllm/v1/attention/ops/prefix_prefill.py", "launched only from chunked_prefill_paged_decode, i.e. the ROCm attention backend; the fixtures deploy on CUDA"),
]
SKIP_EXACT = {
    ("vllm/v1/attention/ops/turboquant_soa/triton_turboquant_decode.py", "_tq_decode_stage1"):
        "not an entry point: launched only by turboquant_soa.triton_turboquant_decode_attention, which nothing in vLLM calls (the backend uses the SoA unified kernel)",
}


def main():
    comps = core.boundary_components() + core.components() + tail.tail_components() + round3.components() + round4.boundary_components() + round4.components() + round4b.components()
    ifaces = (core.boundary_interfaces() + core.selection_interfaces() + core2.fa_interfaces() + core2.fa_interface_module()
              + core2.merge_interfaces() + core2.triton_interfaces() + core3.dcp_interfaces() + core3.vit_interfaces()
              + core3.mla_prefill_interfaces() + core3.cpu_interfaces() + tail.tail_interfaces() + round3.interfaces()
              + round4.interfaces() + round4b.interfaces())
    # Every internal call with an explicit input is filled over the callee's request defaults.
    def fill(steps):
        for st in steps or []:
            if not isinstance(st, dict):
                continue
            if "call" in st and "input" in st and not st["call"].startswith("cuda-platform."):
                st.setdefault("fill", True)
            for k in ("then", "else", "steps", "on_error"):
                if isinstance(st.get(k), list):
                    fill(st[k])
    for i in ifaces:
        fill(i.get("behavior"))
    # Entry points other areas call with partial inputs (models-layers passes only the shape):
    # merge the request defaults first, so the behavior reads complete arguments.
    import re as _re

    def rebind(v, key=None):
        if isinstance(v, list):
            return [rebind(x) for x in v]
        if isinstance(v, dict):
            return {k: rebind(x, k) for k, x in v.items()}
        if isinstance(v, str) and (v.startswith("=") or key in ("if", "when")):
            return _re.sub(r"\binput\b", "vars.i", v)
        return v
    md = ("{'num_actual_tokens': n, 'num_reqs': 1, 'max_query_len': n, 'max_seq_len': n, 'seq_lens': [n], 'block_table': [[0]],"
          " 'slot_mapping': lists.range(n), 'causal': true, 'causal_is_tensor': false, 'has_scheduler_metadata': false,"
          " 'max_num_splits': 0, 'max_dcp_context_kv_len': 0, 'num_decode_reqs': 0, 'num_prefill_reqs': 0, 'seq_threshold_3D': 16}")
    defaults = {
        "flash-attention-impl.forward": ("{'attn_type': 'decoder', 'num_tokens': 1, 'num_heads': 32, 'num_kv_heads': 8, 'head_size': 128,"
                                         " 'kv_cache_dtype': 'auto', 'fa_version': 3, 'dcp_world_size': 1, 'has_output_scale': false,"
                                         " 'has_output_block_scale': false, 'has_alibi': false, 'has_sinks': false, 'profiling_run': false,"
                                         " 'kv_quant_mode': 'none', 'metadata': " + md + "}"),
        "flash-attention-metadata-builder.build": ("{'fast_build': false, 'fa_version': 3, 'use_full_cuda_graph': true, 'max_cudagraph_size': 512,"
                                                   " 'dcp_world_size': config['decode-context-parallel-size'], 'batch_invariant': false, 'sliding_window_configs': 1,"
                                                   " 'common': {'causal': true, 'causal_is_tensor': false, 'causal_tensor_dtype': 'int32', 'common_prefix_len': 0,"
                                                   " 'has_cpu_seq_lens_upper_bound': false, 'decode_query_threshold': 1}}"),
        "mla-attention.get-kv-cache-spec": "{'kv_cache_dtype': config['kv-cache-dtype'], 'head_size': 576, 'model_dtype_bytes': 2, 'sliding_window': 0, 'has_indexer': false, 'non_causal_multi_token_decode': false}",
        "attention-backend-utils.get-supported-kv-cache-layouts": "{'backend_layouts': []}",
        "attention-backend-utils.record-kv-cache-layout": "{'existing_layout': ''}",
        "flash-attention-impl.do-kv-cache-update": ("{'attn_type': 'decoder', 'num_tokens': n, 'num_kv_heads': 8, 'head_size': 128,"
                                                    " 'kv_cache_dtype': 'auto', 'kv_quant_mode': 'none', 'slot_mapping': lists.range(n),"
                                                    " 'device_capability_major': 9}"),
    }
    for i in ifaces:
        key = i["component"] + "." + i["name"]
        if key in defaults:
            n = "(has(input.num_tokens) ? input.num_tokens : 1)"
            guard = []
            if key == "flash-attention-metadata-builder.build":
                guard = [{"if": "!has(input.common)",
                          "then": [{"title": "common_attn_metadata is a required argument of build()",
                                    "source": lib.Cfn(core.FA, "build", lib.ln(core.FA, r"^class FlashAttentionMetadataBuilder")),
                                    "fail": {"code": "type-error", "message": "build() missing 1 required positional argument: 'common_attn_metadata'"}}]}]
                i.setdefault("errors", []).append({"code": "type-error", "status": 0, "retryable": False, "summary": "called without common_attn_metadata"})
            i["behavior"] = guard + [{"title": ("Arguments not passed by the caller take the code's defaults (FA3 on SM90, full CUDA graphs up to 512 tokens)" if key.endswith("build") else
                                       "Arguments not passed by the caller take their usual values (a one-request decode step)" if key.startswith("flash-attention-impl") else
                                       "Arguments the caller leaves out take the function's defaults (no sliding window, no indexer; no declared backend layouts; no layout resolved yet)"),
                              "set": {"vars.i": "= merge(" + defaults[key].replace("lists.range(n)", "lists.range(" + n + ")").replace(": n", ": " + n).replace("[n]", "[" + n + "]") + ", input)"}}] + rebind(i["behavior"])
    flows, scenarios = scen.flows_and_scenarios()
    f2, s2 = scen.tail_flows_and_scenarios()
    flows += f2 + round3.flows() + round4.flows()
    scenarios += s2 + round3.scenarios() + round4.scenarios() + round4b.scenarios()
    with open(os.path.join(OUT, "build-oracle", "round3", "attention.yaml"), "w") as fh:
        fh.write("# Round-3 build-oracle scenarios for attention. Generated by examples/vllm/gen/attention/build.py.\n")
        yaml.safe_dump(round3.oracle_doc(), fh, sort_keys=False, width=200, allow_unicode=True)
    with open(os.path.join(OUT, "build-oracle", "round4", "attention.yaml"), "w") as fh:
        fh.write("# Round-4 build-oracle scenarios for attention. Generated by examples/vllm/gen/attention/build.py.\n")
        yaml.safe_dump(round4.oracle_doc(), fh, sort_keys=False, width=200, allow_unicode=True)
    seed = {"id": "attention-seed", "summary": "Attention's own state: empty backend-selection cache, the modeled backends' capabilities, an empty CPU MLA latent cache.",
            "state": {c["id"]: c["state"]["initial"] for c in comps if "state" in c}}
    doc = {"schema_version": 1, "id": "vllm", "fixtures": [seed], "components": comps, "interfaces": ifaces, "schemas": core.schemas(),
           "configs": core.configs() + round4.configs(), "flows": flows, "scenarios": scenarios}
    # sanity: unique ids
    seen = set()
    for i in ifaces:
        k = i["component"] + "." + i["name"]
        assert k not in seen, k
        seen.add(k)
    cids = {c["id"] for c in comps}
    assert len(cids) == len(comps)
    with open(os.path.join(OUT, "fragments", "attention.yaml"), "w") as fh:
        fh.write("# Attention area fragment (vLLM v0.32.0). Generated by examples/vllm/gen/attention/build.py.\n")
        yaml.safe_dump(doc, fh, sort_keys=False, width=200, allow_unicode=True)
    skips = []
    missing = []
    for e in lib.INV:
        key = (e["file"], e["name"])
        reason = SKIP_EXACT.get(key)
        if reason is None:
            for pre, r in SKIP_RULES:
                if e["file"].startswith(pre):
                    reason = r
                    break
        if reason and key in lib.USED:
            reason = None  # round 4: a skipped file's entry the tests exercise is now modeled
        if reason:
            skips.append({"kind": e["kind"], "name": e["name"], "file": e["file"], "line": e["line"], "reason": reason})
        elif key not in lib.USED:
            missing.append(key)
    with open(os.path.join(OUT, "skips", "attention.json"), "w") as fh:
        json.dump(skips, fh, indent=1)
        fh.write("\n")
    print(f"components {len(comps)} interfaces {len(ifaces)} flows {len(flows)} scenarios {len(scenarios)}")
    print(f"inventory {len(lib.INV)} modeled-cited {len(lib.USED)} skipped {len(skips)} missing {len(missing)}")
    for m in missing:
        print("  missing", m)


if __name__ == "__main__":
    main()
