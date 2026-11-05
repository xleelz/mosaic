"""Hand-written parts of the kernels-ops fragment: configs, compilation, CUDA
graphs, the vLLM IR op dispatch, multi-op wrappers and their scenarios.
Citations are located by searching the code, so line numbers stay exact."""
from common import defline, findline, src

CP = "vllm/_custom_ops.py"
CG = "vllm/compilation/cuda_graph.py"
BK = "vllm/compilation/backends.py"
PW = "vllm/compilation/piecewise_backend.py"
DC = "vllm/compilation/decorators.py"
WR = "vllm/compilation/wrapper.py"
CI = "vllm/compilation/compiler_interface.py"
MON = "vllm/compilation/monitor.py"
PM = "vllm/compilation/passes/pass_manager.py"
IR = "vllm/ir/op.py"
LN = "vllm/ir/ops/layernorm.py"
ACT = "vllm/ir/ops/activation.py"
VC = "vllm/kernels/vllm_c.py"
OINK = "vllm/kernels/oink_ops.py"
TACT = "vllm/kernels/triton/activation.py"
QKV = "vllm/kernels/triton/qkv_padded_fp8_quant.py"
TU = "vllm/utils/torch_utils.py"
XPU = "vllm/_xpu_ops.py"
CFG_C = "vllm/config/compilation.py"
CFG_V = "vllm/config/vllm.py"
ENVS = "vllm/envs.py"
PERF = "vllm/v1/metrics/perf.py"
CUDA_PLAT = "vllm/platforms/cuda.py"
RQF = "vllm/compilation/passes/fusion/rms_quant_fusion.py"
AQF = "vllm/compilation/passes/fusion/act_quant_fusion.py"
ARF = "vllm/compilation/passes/fusion/allreduce_rms_fusion.py"
NOOP = "vllm/compilation/passes/utility/noop_elimination.py"
LOWER = "vllm/compilation/passes/ir/lowering_pass.py"
FIXF = "vllm/compilation/passes/utility/fix_functionalization.py"
CLEAN = "vllm/compilation/passes/utility/post_cleanup.py"
CLONE = "vllm/compilation/passes/ir/clone_elimination.py"

ZERO = 0

def _helion_configs():
    import json as _j, os as _o
    out = {}
    base = "/home/lbethay/.cache/mosaic-bench/vllm-0.32.0/vllm/kernels/helion/configs/silu_mul_fp8"
    for fn in sorted(_o.listdir(base)):
        d = _j.load(open(_o.path.join(base, fn)))
        keys = [x["key"] for x in d if x["key"]]
        out["silu_mul_fp8/" + fn[:-5]] = {"keys": keys, "has_default": any(not x["key"] for x in d)}
    return out


HELION_CONFIGS = _helion_configs()


def cfg(id_, type_, value, default, summary, sources, key, **attrs):
    a = {"key": key}
    a.update(attrs)
    d = {"id": id_, "type": type_, "value": value, "summary": summary, "sources": sources, "attributes": a}
    if default is not None or "default_null" in attrs:
        d["default"] = default
    a.pop("default_null", None)
    return d


# ------------------------------------------------------------------ configs
def configs():
    return [
        cfg("kernel-launch-overhead-us", "integer", 5, None,
            "ASSUMPTION: host launch overhead of one kernel in microseconds (the code gives no number).",
            [src(CFG_V, "Capturing enables")], "kernel_launch_overhead_us", assumption=True),
        cfg("gpu-hbm-bandwidth-gbps", "integer", 3350, None,
            "ASSUMPTION: HBM bandwidth of the fixture's 80 GB GPU, taken as an H100 SXM (3.35 TB/s peak). Memory-bound kernels divide bytes moved by it.",
            [src(PERF, 'read_bytes["qkv_weight"]')], "gpu_hbm_bandwidth_gbps", assumption=True),
        cfg("gpu-bf16-dense-tflops", "integer", 989, None,
            "ASSUMPTION: dense BF16 tensor-core peak of an H100 SXM; FP8 doubles it. GEMM kernels divide 2*m*n*k flops by it, as vllm/v1/metrics/perf.py counts flops.",
            [src(PERF, '"qkv_proj": int(2 * T * D')], "gpu_bf16_dense_tflops", assumption=True),
        cfg("gpu-nvlink-bandwidth-gbps", "integer", 450, None,
            "ASSUMPTION: per-direction NVLink bandwidth of an H100 SXM node (900 GB/s bidirectional).",
            [src("vllm/_custom_ops.py", "def all_reduce(")], "gpu_nvlink_bandwidth_gbps", assumption=True),
        cfg("gpu-pcie-bandwidth-gbps", "integer", 50, None,
            "ASSUMPTION: effective host<->device PCIe Gen5 x16 bandwidth used by swap_blocks.",
            [src(CP, "def swap_blocks(")], "gpu_pcie_bandwidth_gbps", assumption=True),
        cfg("xpu-host-register-us-per-gib", "integer", 1000, None,
            "ASSUMPTION: cost of page-locking 1 GiB of host memory with xpu_host_register (the code gives no number).",
            [src("vllm/v1/kv_offload/cpu/host_register.py", "if not torch.ops._C.xpu_host_register(ptr, num_bytes):")], "xpu_host_register_us_per_gib", assumption=True),
        cfg("inductor-compile-ms-per-graph", "integer", 700, None,
            "ASSUMPTION: Inductor standalone_compile time of one piecewise subgraph for one compile range (the code only logs the measured time).",
            [src(BK, "Compiling a graph for compile range")], "inductor_compile_ms_per_graph", assumption=True),
        cfg("inductor-load-ms-per-graph", "integer", 60, None,
            "ASSUMPTION: time to load one cached compiled subgraph from the compile cache.",
            [src(BK, "Directly load the compiled graph(s)")], "inductor_load_ms_per_graph", assumption=True),
        cfg("dynamo-trace-ms", "integer", 5000, None,
            "ASSUMPTION: Dynamo bytecode transform time for a Llama decoder stack (logged, not configured).",
            [src(BK, "Dynamo bytecode transform time")], "dynamo_trace_ms", assumption=True),
        cfg("cudagraph-capture-overhead-ms", "integer", 2, None,
            "ASSUMPTION: fixed cost of one torch.cuda.graph capture on top of running the captured work once.",
            [src(CG, "with torch.cuda.graph(")], "cudagraph_capture_overhead_ms", assumption=True),
        cfg("compilation-mode", "integer", 3, None,
            "compilation_config.mode: deployed VLLM_COMPILE (3); the field default is None and -O2 (the default optimization level) resolves it to 3. enforce_eager or -O0 gives NONE (0).",
            [src(CFG_C, "    mode: CompilationMode = None"), src(CFG_V, "self.compilation_config.mode = CompilationMode.VLLM_COMPILE")],
            "compilation_config.mode", default_null=True),
        cfg("cudagraph-mode", "string", "FULL_AND_PIECEWISE", None,
            "compilation_config.cudagraph_mode: the field default is None; -O2 resolves it to FULL_AND_PIECEWISE.",
            [src(CFG_C, "    cudagraph_mode: CUDAGraphMode = None"), src(CFG_V, '"cudagraph_mode": CUDAGraphMode.FULL_AND_PIECEWISE')],
            "compilation_config.cudagraph_mode", default_null=True),
        cfg("compile-sizes", "array", [], None,
            "compilation_config.compile_sizes: default None, normalized to [] in post-init, so only the general range [1, max_num_batched_tokens] is compiled.",
            [src(CFG_C, "    compile_sizes: list[int | str] | None = None"), src(CFG_C, "self.compile_sizes = computed_compile_sizes")],
            "compilation_config.compile_sizes", default_null=True),
        cfg("cudagraph-copy-inputs", "boolean", False, False,
            "compilation_config.cudagraph_copy_inputs: when false VllmBackend returns the runtime callable without input copies.",
            [src(CFG_C, "    cudagraph_copy_inputs: bool = False")], "compilation_config.cudagraph_copy_inputs"),
        cfg("use-inductor-graph-partition", "boolean", False, None,
            "compilation_config.use_inductor_graph_partition: -O2 sets False, so the FX graph is split at splitting_ops before Inductor.",
            [src(CFG_C, "    use_inductor_graph_partition: bool = None"), src(CFG_V, '"use_inductor_graph_partition": False', nth=3)],
            "compilation_config.use_inductor_graph_partition", default_null=True),
        cfg("eliminate-noops", "boolean", True, True,
            "compilation_config.pass_config.eliminate_noops.",
            [src(CFG_C, "eliminate_noops: bool = Field(default=True)")], "compilation_config.pass_config.eliminate_noops"),
        cfg("fuse-norm-quant", "boolean", False, None,
            "pass_config.fuse_norm_quant: -O2 uses enable_norm_fusion, false for an unquantized Llama under inductor (custom ops 'none', rms_norm IR priority native).",
            [src(CFG_V, "def enable_norm_fusion"), src(CFG_V, '"fuse_norm_quant": enable_norm_fusion', nth=2)],
            "compilation_config.pass_config.fuse_norm_quant", default_null=True),
        cfg("fuse-act-quant", "boolean", False, None,
            "pass_config.fuse_act_quant: -O2 uses enable_act_fusion, false for an unquantized Llama under inductor.",
            [src(CFG_V, "def enable_act_fusion"), src(CFG_V, '"fuse_act_quant": enable_act_fusion', nth=2)],
            "compilation_config.pass_config.fuse_act_quant", default_null=True),
        cfg("fuse-allreduce-rms", "boolean", False, None,
            "pass_config.fuse_allreduce_rms: -O2 enables it only with TP > 1 on Hopper/Blackwell with FlashInfer; false for the tp1 fixture.",
            [src(CFG_V, "def enable_allreduce_rms_fusion"), src(CFG_V, '"fuse_allreduce_rms": enable_allreduce_rms_fusion', nth=1)],
            "compilation_config.pass_config.fuse_allreduce_rms", default_null=True),
        cfg("ir-op-priority", "object",
            {"rms_norm": ["native"], "fused_add_rms_norm": ["native"], "gelu_and_mul_sparse": ["triton", "native"]},
            None,
            "kernel_config.ir_op_priority after platform defaults: with VLLM_COMPILE + inductor the CUDA platform puts 'native' first (Inductor generates the kernel); with no codegen it is ['vllm_c', 'native'].",
            [src(CUDA_PLAT, "def get_default_ir_op_priority"), src(CUDA_PLAT, 'default = ["native"] if using_inductor else ["vllm_c", "native"]')],
            "kernel_config.ir_op_priority"),
        cfg("fuse-rope-kvcache", "boolean", False, None,
            "pass_config.fuse_rope_kvcache: -O2 uses enable_rope_kvcache_fusion, which needs ROCm AITER; false on the CUDA fixture.",
            [src(CFG_C, "    fuse_rope_kvcache: bool = None"), src(CFG_V, "def enable_rope_kvcache_fusion")],
            "compilation_config.pass_config.fuse_rope_kvcache", default_null=True),
        cfg("rope-kvcache-fusion-max-token-num", "integer", 256, 256,
            "pass_config.rope_kvcache_fusion_max_token_num: RoPE+KV-cache fusion applies only to compile ranges ending at or below it.",
            [src(CFG_C, "    rope_kvcache_fusion_max_token_num: int = 256")], "compilation_config.pass_config.rope_kvcache_fusion_max_token_num"),
        cfg("vllm-use-aot-compile", "boolean", True, True,
            "VLLM_USE_AOT_COMPILE: defaults to on with torch >= 2.10 (the CUDA requirements pin torch 2.13) unless the compile cache is disabled.",
            [src(ENVS, "def use_aot_compile"), src("requirements/cuda.txt", "torch==")], "VLLM_USE_AOT_COMPILE"),
        cfg("vllm-disable-compile-cache", "boolean", False, False,
            "VLLM_DISABLE_COMPILE_CACHE.", [src(ENVS, 'return bool(int(os.getenv("VLLM_DISABLE_COMPILE_CACHE", "0")))')],
            "VLLM_DISABLE_COMPILE_CACHE"),
        cfg("vllm-use-bytecode-hook", "boolean", True, True,
            "VLLM_USE_BYTECODE_HOOK: TorchCompileWithNoGuardsWrapper dispatches to the compiled bytecode directly.",
            [src(ENVS, '"VLLM_USE_BYTECODE_HOOK": lambda: bool(')], "VLLM_USE_BYTECODE_HOOK"),
        {"id": "vllm-target-device", "type": "string", "value": "cuda", "default": "cuda",
         "summary": "VLLM_TARGET_DEVICE, lower-cased; 'cpu' short-circuits platform detection to the CPU platform",
         "sources": ["vllm/envs.py:91", "vllm/envs.py:621"], "attributes": {"key": "VLLM_TARGET_DEVICE", "env": True}},
    ]


# ------------------------------------------------------------------ components
def comp(id_, name, kind, summary, sources, parent="gpu-worker", **extra):
    d = {"id": id_, "name": name, "kind": kind, "layer": extra.pop("layer", "kernels"), "parent": parent,
         "summary": summary, "sources": sources, "attributes": {"owner": "kernels-ops"}}
    if "capacity" in d or "capacity" in extra:
        pass
    d.update(extra)
    if "capacity" in d:
        d["description"] = "Capacity 1: each GPU worker process runs compilation and model execution on a single thread (Worker.execute_model), so calls never overlap."
    return d


def components():
    cs = [
        comp("kernels-ops", "Kernels and ops", "module",
             "Torch custom ops, their Python wrappers, CUDA/Triton kernels, torch.compile integration and CUDA graph capture inside a GPU worker.",
             [src(CP, "current_platform.import_kernels()")]),
        # op libraries
        comp("torch-bindings", "Torch op library _C (CUDA build)", "module",
             "STABLE_TORCH_LIBRARY fragments _C, _C_cache_ops, _C_cuda_utils and _C_custom_ar of the CUDA/ROCm extension.",
             [src("csrc/torch_bindings.cpp", "STABLE_TORCH_LIBRARY_FRAGMENT(_C, ops)")], parent="kernels-ops"),
        comp("moe-torch-bindings", "Torch op library _moe_C", "module", "MoE routing and expert GEMM ops.",
             [src("csrc/moe/torch_bindings.cpp", "TORCH_LIBRARY")], parent="kernels-ops"),
        comp("cpu-torch-bindings", "Torch op library _C (CPU build)", "module",
             "The _C extension of the CPU build: CPU implementations of shared op names plus CPU-only ops.",
             [src("csrc/cpu/torch_bindings.cpp", "TORCH_LIBRARY_EXPAND")], parent="kernels-ops"),
        comp("rocm-torch-bindings", "Torch op library _rocm_C", "module", "ROCm-only skinny GEMMs, RDNA3 GPTQ GEMMs and paged attention.",
             [src("csrc/rocm/torch_bindings.cpp", "TORCH_LIBRARY")], parent="kernels-ops"),
        comp("quickreduce-torch-bindings", "Quick reduce op library", "module", "ROCm quick all-reduce ops (namespace _C_custom_ar on ROCm builds).",
             [src("csrc/rocm/quickreduce/torch_bindings.cpp", "TORCH_LIBRARY_FRAGMENT")], parent="kernels-ops"),
        comp("flashkda-registration", "Torch op library _flashkda_C", "module", "FlashKDA kernels.",
             [src("csrc/flashkda_registration.cpp", "fwd")], parent="kernels-ops"),
        comp("aiter-ops", "ROCm AITER ops", "module", "rocm_aiter_ops and the torch.ops.vllm.rocm_aiter_* custom ops it registers once.",
             [src("vllm/_aiter_ops.py", "class rocm_aiter_ops")], parent="kernels-ops"),
        comp("xpu-ops", "XPU ops", "module", "xpu_ops and the torch.ops.vllm.xpu_* custom ops wrapping vllm-xpu-kernels; also Triton selective scan.",
             [src(XPU, "class xpu_ops")], parent="kernels-ops"),
        comp("flashinfer", "FlashInfer helpers", "module", "FlashInfer availability checks and the torch.ops.vllm.flashinfer_* custom ops.",
             [src("vllm/utils/flashinfer.py", "def has_flashinfer")], parent="kernels-ops"),
        comp("custom-ops", "Custom op wrappers (_custom_ops.py)", "module",
             "Python wrappers that allocate outputs, pick a variant and call torch.ops._C* ops.", [src(CP, "current_platform.import_kernels()")], parent="kernels-ops"),
        comp("vllm-c", "vllm_c IR provider", "module", "IR op implementations backed by vLLM's own C kernels (provider 'vllm_c').",
             [src(VC, "current_platform.import_kernels()")], parent="kernels-ops"),
        comp("oink-ops", "Oink IR provider", "module", "IR op implementations backed by the external oink kernels (provider 'oink').",
             [src(OINK, "def has_oink_op")], parent="kernels-ops"),
        comp("silu-mul-fp8", "Helion silu_mul_fp8 op", "module", "Helion kernel for SiLU-mul + FP8 quant with a vLLM C baseline.",
             [src("vllm/kernels/helion/ops/silu_mul_fp8.py", "def silu_mul_fp8_baseline")], parent="kernels-ops"),
        comp("helion-kernel-wrapper", "HelionKernelWrapper registry", "module", "Registered Helion kernels (_REGISTERED_KERNELS): per-op disabled flag, platform and config set.",
             [src("vllm/kernels/helion/register.py", "_REGISTERED_KERNELS: dict[str, HelionKernelWrapper] = {}")], parent="kernels-ops",
             state={"schema": {"type": "object", "properties": {"registered": {"type": "object"}}}, "initial": {"registered": {}}}, capacity={"concurrency": 1}),
        comp("helion-config-manager", "Helion ConfigManager", "datastore", "Pre-tuned Helion configs shipped under vllm/kernels/helion/configs/<kernel>/<platform>.json.",
             [src("vllm/kernels/helion/config_manager.py", "class ConfigManager:")], parent="kernels-ops", layer="storage",
             state={"schema": {"type": "object", "properties": {"configs": {"type": "object"}}}, "initial": {"configs": HELION_CONFIGS}}),
        comp("helion-utils", "Helion utils", "module", "GPU name canonicalization for Helion platform configs.", [src("vllm/kernels/helion/utils.py", "def get_canonical_gpu_name")], parent="kernels-ops"),
        comp("import-utils", "Import utils", "module", "Optional-dependency probes (has_helion, has_deep_gemm, ...).", [src("vllm/utils/import_utils.py", "def _has_module(module_name: str) -> bool:")], parent="kernels-ops"),
        comp("cpu-triton-utils", "CPU replacements for Triton kernels", "module",
             "CPU implementations of the model runner's Triton helpers (slot mapping, EAGLE input prep, rejection sampling), each calling a _C CPU op.",
             [src("vllm/utils/cpu_triton_utils.py", "def _compute_slot_mapping_kernel_impl")], parent="kernels-ops"),
        comp("torch-utils", "Torch utilities", "module", "weak_ref_tensor(s) and the UVA CPU-tensor view used by CUDA graphs and the model runner.",
             [src(TU, "def weak_ref_tensor(")], parent="kernels-ops"),
        comp("kernels-triton-activation", "Triton activation kernels", "module", "Triton gelu_and_mul_sparse provider for the IR op.",
             [src(TACT, "def _gelu_and_mul_sparse_kernel(")], parent="kernels-ops"),
        comp("qkv-padded-fp8-quant", "Triton padded FP8 quant", "module", "Triton FP8 quantization that pads head_dim to a multiple of 16.",
             [src(QKV, "def quantize_fp8_pad_head_dim_triton(")], parent="kernels-ops"),
        comp("vllm-xpu-kernels", "vllm-xpu-kernels (external)", "external", "The vllm-xpu-kernels package providing torch.ops._xpu_C and the XPU _C ops.",
             [src(XPU, "torch.ops._C.gemma_rms_norm(")], parent="kernels-ops", layer="external"),
        comp("qutlass", "QuTLASS (external)", "external", "The qutlass package providing torch.ops._qutlass_C MXFP4/NVFP4 kernels.",
             [src(CP, "torch.ops._qutlass_C.matmul_mxf4_bf16_tn")], parent="kernels-ops", layer="external"),
        # vLLM IR
        comp("ir-op", "vLLM IR op dispatcher", "module",
             "IrOp: a functional op with a native implementation and provider implementations chosen by priority and supports_args at dispatch.",
             [src(IR, "class IrOp:")], parent="kernels-ops"),
        comp("ir-ops-layernorm", "IR layernorm ops", "module", "Native (PyTorch) implementations of vllm.ir.ops.rms_norm and fused_add_rms_norm.",
             [src(LN, "def rms_norm(")], parent="kernels-ops"),
        comp("ir-ops-activation", "IR activation ops", "module", "Native implementation of vllm.ir.ops.gelu_and_mul_sparse.",
             [src(ACT, "def gelu_and_mul_sparse(")], parent="kernels-ops"),
        # compilation
        comp("compilation", "torch.compile integration", "module", "vLLM's torch.compile integration: decorator, guard-free wrapper, VllmBackend, piecewise compile and CUDA graphs.",
             [src(BK, "class VllmBackend:")], parent="kernels-ops"),
        comp("support-torch-compile", "@support_torch_compile model", "module",
             "The decorator-patched model class: decides eager vs compiled, loads or saves AOT artifacts, and compiles on first call.",
             [src(DC, "def _support_torch_compile(")], parent="compilation",
             state={"schema": {"type": "object", "properties": {
                        "modules": {"type": "object", "description": "per decorated module instance (by class): its do_not_compile, decided in __init__"},
                        "compiled": {"type": "object", "description": "module -> self.compiled (absent: False, as __init__ sets it)"},
                        "aot_compiled_fn": {"type": "object", "description": "module -> it holds an AOT-compiled function"},
                        "was_aot_compile_fn_loaded_from_disk": {"type": "object", "description": "module -> the AOT function came from disk"},
                        "current": {"type": ["string", "null"], "description": "the module built last (the one the model runner calls)"},
                        "num_compiles": {"type": "integer", "description": "first-call compilations on this rank, all modules"}}},
                    "initial": {"modules": {}, "current": None, "compiled": {}, "aot_compiled_fn": {}, "was_aot_compile_fn_loaded_from_disk": {}, "num_compiles": 0}}, capacity={"concurrency": 1}),
        comp("torch-compile-with-no-guards-wrapper", "TorchCompileWithNoGuardsWrapper", "module",
             "Wraps forward in torch.compile with the vLLM backend and, with the bytecode hook, dispatches straight to the compiled bytecode (no guard evaluation).",
             [src(WR, "class TorchCompileWithNoGuardsWrapper:")], parent="compilation",
             state={"schema": {"type": "object", "properties": {"compiled_bytecode": {"type": "object", "description": "per decorated module: its wrapper has compiled code"}}}, "initial": {"compiled_bytecode": {}}}, capacity={"concurrency": 1}),
        comp("vllm-backend", "VllmBackend", "module",
             "The torch.compile backend: hashes factors into a cache dir, splits the graph at splitting ops, compiles each piece and builds the runtime callable.",
             [src(BK, "class VllmBackend:")], parent="compilation",
             state={"schema": {"type": "object", "properties": {"called": {"type": "object", "description": "per decorated module: its backend instance was called (self._called)"}}}, "initial": {"called": {}}}, capacity={"concurrency": 1}),
        comp("compiler-manager", "CompilerManager", "module",
             "Caches compiled graphs keyed (compile_range, graph_index, compiler name), loads from the cache file and compiles misses.",
             [src(BK, "class CompilerManager:")], parent="compilation",
             state={"schema": {"type": "object", "properties": {"cache": {"type": "object"}, "is_cache_updated": {"type": "boolean"}, "disable_cache": {"type": "boolean"}}},
                    "initial": {"cache": {}, "is_cache_updated": False, "disable_cache": False}}, capacity={"concurrency": 1}),
        comp("inductor-standalone-adaptor", "InductorStandaloneAdaptor", "module",
             "Compiles a subgraph with torch._inductor.standalone_compile and saves or loads the artifact.",
             [src(CI, "class InductorStandaloneAdaptor(CompilerInterface):")], parent="compilation"),
        comp("piecewise-backend", "PiecewiseBackend", "module",
             "One compiled piece of the split graph: compiles every compile range up front and dispatches by runtime token count.",
             [src(PW, "class PiecewiseBackend:")], parent="compilation"),
        comp("cuda-graph-wrapper", "CUDAGraphWrapper", "module",
             "Captures a CUDA graph per batch descriptor on first use and replays it afterwards; runs eagerly when the runtime mode does not match.",
             [src(CG, "class CUDAGraphWrapper:")], parent="compilation",
             state={"schema": {"type": "object", "properties": {"entries": {"type": "object"}, "num_cudagraph_captured": {"type": "integer"}}},
                    "initial": {"entries": {}, "num_cudagraph_captured": 0}}, capacity={"concurrency": 1}),
        comp("compilation-monitor", "Compilation monitor", "module", "Global flag that makes CUDA graph capture illegal outside the capture phase.",
             [src(MON, "cudagraph_capturing_enabled: bool = True")], parent="compilation",
             state={"schema": {"type": "object", "properties": {"cudagraph_capturing_enabled": {"type": "boolean"}}}, "initial": {"cudagraph_capturing_enabled": True}}),
        comp("torch-compile-cache", "torch.compile cache directory", "datastore",
             "Files under VLLM_CACHE_ROOT/torch_compile_cache: vllm_compile_cache.py (the CompilerManager index) and AOT-compiled model artifacts. Survives a worker restart.",
             [src(BK, '"torch_compile_cache", hash_key')], parent="compilation", layer="storage",
             state={"schema": {"type": "object", "properties": {"files": {"type": "object"}, "aot": {"type": "object"}}}, "initial": {"files": {}, "aot": {}}}),
        comp("post-grad-pass-manager", "PostGradPassManager", "module",
             "Runs vLLM's custom Inductor post-grad passes in order: no-op elimination, enabled fusions, cleanup, IR lowering, clone elimination, fix functionalization.",
             [src(PM, "class PostGradPassManager(CustomGraphPass):")], parent="compilation"),
        comp("noop-elimination-pass", "NoOpEliminationPass", "module", "Removes no-op reshapes, slices and views.",
             [src(NOOP, "class NoOpEliminationPass")], parent="post-grad-pass-manager"),
        comp("rms-norm-quant-fusion-pass", "RMSNormQuantFusionPass", "module", "Fuses rms_norm (+residual) followed by FP8 quant into one fused norm+quant op.",
             [src(RQF, "class RMSNormQuantFusionPass")], parent="post-grad-pass-manager"),
        comp("activation-quant-fusion-pass", "ActivationQuantFusionPass", "module", "Fuses silu_and_mul followed by FP8/FP4 quant.",
             [src(AQF, "class ActivationQuantFusionPass")], parent="post-grad-pass-manager"),
        comp("all-reduce-fusion-pass", "AllReduceFusionPass", "module", "Fuses tensor-parallel all-reduce with the following RMSNorm (FlashInfer TRT-LLM kernel).",
             [src(ARF, "class AllReduceFusionPass")], parent="post-grad-pass-manager"),
        comp("rope-kv-cache-fusion-pass", "RopeKVCacheFusionPass", "module",
             "Fuses RoPE (+ static Q FP8 quant) with the KV cache update into vllm::fused_rope_and_unified_kv_cache_update for small batches (ROCm AITER).",
             [src("vllm/compilation/passes/fusion/rope_kvcache_fusion.py", "class RopeKVCacheFusionPass")], parent="rope-kvcache-fusion"),
        comp("vllm-ir-lowering-pass", "VllmIRLoweringPass", "module", "Lowers vllm.ir ops to the implementation their priority selects.",
             [src(LOWER, "class VllmIRLoweringPass")], parent="post-grad-pass-manager"),
        comp("fix-functionalization-pass", "FixFunctionalizationPass", "module", "Re-inplaces functionalized custom ops so they mutate their outputs.",
             [src(FIXF, "class FixFunctionalizationPass")], parent="post-grad-pass-manager"),
        comp("post-cleanup-pass", "PostCleanupPass", "module", "Dead-code elimination after the fusions.",
             [src(CLEAN, "class PostCleanupPass")], parent="post-grad-pass-manager"),
        comp("unsafe-clone-elimination-pass", "UnsafeCloneEliminationPass", "module", "Removes clones introduced around in-place IR ops.",
             [src(CLONE, "class UnsafeCloneEliminationPass")], parent="post-grad-pass-manager"),
        # boundary
        {"id": "custom-all-gather-reduce-scatter-ops", "name": "Custom all-gather / reduce-scatter ops", "kind": "module",
         "summary": "Boundary: _C_custom_ar all-gather and reduce-scatter ops registered in csrc/custom_all_gather_reduce_scatter_ops.cpp.",
         "sources": [src("csrc/custom_all_gather_reduce_scatter_ops.cpp", "STABLE_TORCH_LIBRARY_FRAGMENT(_C_custom_ar")],
         "attributes": {"boundary": True, "owner": "distributed"}},
        {"id": "custom-allreduce-cuda", "name": "CustomAllreduce (C++)", "kind": "module", "layer": "kernels",
         "summary": "Boundary: the C++ CustomAllreduce behind the _C_custom_ar ops.",
         "sources": ["csrc/custom_all_reduce.cu:70-116"], "attributes": {"boundary": True, "owner": "distributed"}},
    ]
    for c in cs:
        if c["kind"] == "datastore" or "state" in c:
            pass
    return cs


SCHEMAS_HAND = {
    "KernelsOpsIrCall": {"summary": "A call of a vllm.ir op: which op and the argument properties that supports_args checks.",
        "schema": {"type": "object", "required": ["op"], "properties": {
            "op": {"type": "string", "examples": ["rms_norm"]},
            "num_tokens": {"type": "integer", "examples": [16]},
            "hidden_size": {"type": "integer", "examples": [4096]},
            "dtype_bytes": {"type": "integer", "examples": [2]},
            "variance_size": {"type": "integer", "examples": [0], "description": "0 means None"},
            "weight_dtype_matches": {"type": "boolean", "default": True},
            "contiguous": {"type": "boolean", "default": True},
            "ndim": {"type": "integer", "examples": [2]},
            "approximate": {"type": "string", "examples": ["tanh"]},
            "device_type": {"type": "string", "examples": ["cuda"]},
        }}},
    "KernelsOpsGraphCall": {"summary": "A call into a compiled or captured graph: the batch it runs and the forward-context fields the wrapper reads.",
        "schema": {"type": "object", "properties": {
            "num_tokens": {"type": "integer", "examples": [16]},
            "uniform_decode": {"type": "boolean", "default": True},
            "runtime_mode": {"type": "string", "enum": ["NONE", "PIECEWISE", "FULL"], "examples": ["FULL"]},
            "wrapper_mode": {"type": "string", "enum": ["PIECEWISE", "FULL"], "examples": ["FULL"]},
            "forward_context": {"type": "boolean", "default": True},
            "debug": {"type": "boolean", "default": False},
            "input_addresses": {"type": "array", "items": {"type": "integer"}, "examples": [[140000000]]},
            "num_layers": {"type": "integer", "examples": [32]},
            "config_hash": {"type": ["string", "null"], "default": None, "description": "VllmConfig.compute_hash() of the deployment; null: the backend computes it (config-platform's vllm-config.compute-hash)"},
            "module": {"type": ["string", "null"], "default": None, "examples": ["LlamaModel"], "description": "the decorated module (class name) being called; null: the model built last"},
            "skip_compiled": {"type": "boolean", "default": False, "description": "forward_context.skip_compiled (encoder-decoder models bypass the compiled graph)"},
        }}},
    "KernelsOpsCompileCall": {"summary": "A compile request: the model's layer count decides how many pieces the split graph has.",
        "schema": {"type": "object", "properties": {
            "num_layers": {"type": "integer", "examples": [32]},
            "num_tokens": {"type": "integer", "examples": [8192]},
            "prefix": {"type": "string", "examples": ["backbone"]},
            "graph_patterns": {"type": "array", "items": {"type": "string"}, "examples": [["rms_norm", "silu_and_mul"]]},
            "config_hash": {"type": ["string", "null"], "default": None, "description": "VllmConfig.compute_hash(): ModelConfig, ParallelConfig, CompilationConfig, ... factors (language_model_only among them); null: the backend calls config-platform's vllm-config.compute-hash"},
            "env_hash": {"type": "string", "default": "env0", "description": "hash_factors(envs.compile_factors())"},
            "code_hash": {"type": "string", "default": "code0", "description": "sha256 of the traced source files"},
            "compiler_hash": {"type": "string", "default": "inductor", "description": "CompilerManager.compute_hash (torch/Inductor version and config)"},
            "module": {"type": ["string", "null"], "default": None, "description": "the decorated module whose wrapper owns this backend; null: LlamaModel"},
            "cache_dir": {"type": "string", "default": "", "description": "compilation_config.cache_dir; empty means derive it from the factors"},
            "cache_root": {"type": "string", "default": "~/.cache/vllm", "description": "VLLM_CACHE_ROOT"},
            "rank": {"type": "integer", "default": 0},
            "dp_rank": {"type": "integer", "default": 0},
        }}},
    "KernelsOpsFp8QuantCall": {"summary": "scaled_fp8_quant arguments that pick the kernel.",
        "schema": {"type": "object", "properties": {
            "num_tokens": {"type": "integer", "examples": [16]},
            "hidden_size": {"type": "integer", "examples": [4096]},
            "dtype_bytes": {"type": "integer", "examples": [2]},
            "has_scale": {"type": "boolean", "default": False},
            "use_per_token_if_dynamic": {"type": "boolean", "default": False},
            "has_scale_ub": {"type": "boolean", "default": False},
            "num_token_padding": {"type": "integer", "examples": [0]},
            "has_output": {"type": "boolean", "default": False},
            "ndim": {"type": "integer", "examples": [2]},
        }}},
    "KernelsOpsInt8QuantCall": {"summary": "scaled_int8_quant arguments that pick the kernel.",
        "schema": {"type": "object", "properties": {
            "num_tokens": {"type": "integer", "examples": [16]},
            "hidden_size": {"type": "integer", "examples": [4096]},
            "dtype_bytes": {"type": "integer", "examples": [2]},
            "has_scale": {"type": "boolean", "default": False},
            "has_azp": {"type": "boolean", "default": False},
            "symmetric": {"type": "boolean", "default": True},
        }}},
    "KernelsOpsScaledMmCall": {"summary": "cutlass_scaled_mm arguments.",
        "schema": {"type": "object", "properties": {
            "m": {"type": "integer", "examples": [16]},
            "n": {"type": "integer", "examples": [4096]},
            "k": {"type": "integer", "examples": [4096]},
            "dtype_bytes": {"type": "integer", "examples": [1]},
            "out_dtype": {"type": "string", "examples": ["bfloat16"]},
            "has_bias": {"type": "boolean", "default": False},
        }}},
    "KernelsOpsAwqPackCall": {"summary": "convert_weight_packed_scale_zp arguments (AWQ int4 checkpoint packed as int32).",
        "schema": {"type": "object", "properties": {
            "k": {"type": "integer", "examples": [128]},
            "n": {"type": "integer", "examples": [128]},
            "group_size": {"type": "integer", "examples": [128]},
            "dtype_bytes": {"type": "integer", "examples": [4]},
            "quant_method": {"type": "string", "enum": ["AWQ", "GPTQ"], "examples": ["AWQ"]},
            "num_experts": {"type": "integer", "examples": [0], "description": "0 for a 2D (dense) weight, E for a 3D MoE weight"},
        }}},
    "KernelsOpsGptqShuffleCall": {"summary": "gptq_shuffle arguments: the packed int32 weight [rows, cols] and the bit width.",
        "schema": {"type": "object", "properties": {
            "rows": {"type": "integer", "examples": [1792]},
            "cols": {"type": "integer", "examples": [4096]},
            "bit": {"type": "integer", "examples": [4]},
            "n": {"type": "integer", "examples": [4096]},
            "k": {"type": "integer", "examples": [14336]},
            "dtype_bytes": {"type": "integer", "examples": [4]},
        }}},
}


def S(path, needle, **kw):
    return src(path, needle, **kw)
