"""Fix round 4 (coverage): the functions kernels-ops' tests call that the model did not cite.

Registers interfaces into hand2.I (and host behaviors into hand2.OP_BEHAVIORS) and exports
COMPONENTS, COMPONENT_PATCHES, CONFIGS, SCENARIOS for build.py."""
from common import findline, src
from hand import cfg, comp, DC, IR, ENVS
from hand2 import I, OP_BEHAVIORS, iface, count  # noqa: F401
from ops import LATENCY

AIT = "vllm/_aiter_ops.py"
ROCM = "vllm/platforms/rocm.py"
CNT = "vllm/compilation/counter.py"
MU = "vllm/utils/math_utils.py"
NU = "vllm/utils/network_utils.py"
SU = "vllm/utils/system_utils.py"
DG = "vllm/utils/deep_gemm.py"
IU = "vllm/utils/import_utils.py"
FI = "vllm/utils/flashinfer.py"
HCM = "vllm/kernels/helion/config_manager.py"
HREG = "vllm/kernels/helion/register.py"
IPASS = "vllm/compilation/passes/inductor_pass.py"
TACT = "vllm/kernels/triton/activation.py"
IRACT = "vllm/ir/ops/activation.py"
IRLN = "vllm/ir/ops/layernorm.py"
TOPK = "csrc/topk.cu"
CTOPK = "csrc/cooperative_topk.cu"
STOPK = "csrc/sampled_topk.cuh"
CUDA_PLAT = "vllm/platforms/cuda.py"

ERR = lambda *codes: [{"code": c, "status": 0, "retryable": False} for c in codes]
BOOL = {"type": "object", "properties": {"enabled": {"type": ["boolean", "null"]}}}
EMPTY = {"type": "object", "properties": {}}

COMPONENTS = []
COMPONENT_PATCHES = {}
SCENARIOS = []

# ====================================================================== compilation counter
COUNTERS = ["num_models_seen", "num_graphs_seen", "num_piecewise_graphs_seen", "num_piecewise_capturable_graphs_seen",
            "num_backend_compilations", "num_gpu_runner_capture_triggers", "num_cudagraph_captured", "num_inductor_compiles",
            "num_eager_compiles", "num_cache_entries_updated", "num_compiled_artifacts_saved", "num_compiled_artifacts_loaded",
            "num_aot_compiles", "num_aot_artifacts_saved", "num_aot_artifacts_loaded", "stock_torch_compile_count"]
COMPONENTS.append(comp(
    "compilation-counter", "CompilationCounter", "module",
    "The process-global compilation_counter: how many graphs, compiles, cache entries, artifacts and CUDA graphs this worker saw. Tests snapshot it with expect().",
    [src(CNT, "class CompilationCounter:")], parent="compilation",
    state={"schema": {"type": "object", "properties": {"counters": {"type": "object"}}}, "initial": {"counters": {c: 0 for c in COUNTERS}}},
    capacity={"concurrency": 1}))

iface("compilation-counter", "increment", kind="function", latency_ms=0,
      summary="compilation_counter.<field> += by, done inline by the compile, cache and capture code.",
      sources=[src(CNT, "class CompilationCounter:", span=33)],
      request={"type": "object", "required": ["field"], "properties": {"field": {"type": "string", "enum": COUNTERS}, "by": {"type": "integer", "default": 1}}},
      response={"type": "object", "properties": {"value": {"type": "integer"}}},
      behavior=[{"set": {"= 'state.counters.' + input.field": "= state.counters[input.field] + input.by"},
                 "title": "Add to the dataclass field", "source": src(CNT, "num_models_seen: int = 0")},
                {"return": {"value": "= state.counters[input.field]"}}])

iface("compilation-counter", "clone", kind="function", latency_ms=0,
      summary="CompilationCounter.clone: a deep copy of every counter (the 'before' snapshot of expect()).",
      sources=[src(CNT, "    def clone(self) -> \"CompilationCounter\":", span=1)],
      response={"type": "object", "properties": {"counters": {"type": "object"}}},
      behavior=[{"return": {"counters": "= state.counters"}, "title": "copy.deepcopy(self)", "source": src(CNT, "return copy.deepcopy(self)")}])

iface("compilation-counter", "expect", kind="function", latency_ms=0,
      summary="CompilationCounter.expect(**kwargs) exit check: each named counter must have grown by exactly the expected amount since the snapshot.",
      sources=[src(CNT, "    def expect(self, **kwargs: Any) -> Generator[None, None, None]:", span=9)],
      request={"type": "object", "required": ["before", "expected"], "properties": {
          "before": {"type": "object", "description": "the clone() taken when the with-block was entered"},
          "expected": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string", "enum": COUNTERS}, "diff": {"type": "integer"}}}}}},
      errors=ERR("assertion-error"),
      behavior=[
          {"foreach": "= input.expected", "as": "e", "title": "for k, v in kwargs.items()", "source": src(CNT, "for k, v in kwargs.items():"),
           "steps": [{"if": "state.counters[vars.e.field] - input.before[vars.e.field] != vars.e.diff",
                      "title": "getattr(self, k) - getattr(old, k) == v", "source": src(CNT, "assert getattr(self, k) - getattr(old, k) == v, ("),
                      "then": [{"fail": {"code": "assertion-error",
                                         "message": "= vars.e.field + ' not as expected, before it is ' + string(input.before[vars.e.field]) + ', after it is ' + string(state.counters[vars.e.field]) + ', expected diff is ' + string(vars.e.diff)"}}]}]},
          {"return": {"ok": True}},
      ])

# ====================================================================== support_torch_compile decoration and init
TS = ["torch.Tensor", "torch.Tensor | None", "torch.FloatTensor", "torch.FloatTensor | None", "IntermediateTensors", "IntermediateTensors | None"]
iface("support-torch-compile", "decorate", kind="function", latency_ms=0,
      summary="@support_torch_compile(cls, dynamic_arg_dims=...): infer the dynamic dims from forward()'s tensor annotations unless given, and validate them.",
      sources=[src(DC, "    def cls_decorator_helper(cls: type[_T]) -> type[_T]:", span=42),
               f"{DC}:{findline(DC, '@overload')}-{findline(DC, 'def support_torch_compile(cls: type[_T]) -> type[_T]: ...')}",
               f"{DC}:{findline(DC, 'def support_torch_compile(', nth=6)}-{findline(DC, '    return cls_decorator_helper', nth=1)}"],
      request={"type": "object", "properties": {
          "has_forward": {"type": "boolean", "default": True},
          "forward_params": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "annotation": {"type": "string"}}},
                             "examples": [[{"name": "input_ids", "annotation": "torch.Tensor | None"}, {"name": "positions", "annotation": "torch.Tensor"},
                                           {"name": "intermediate_tensors", "annotation": "IntermediateTensors | None"}, {"name": "inputs_embeds", "annotation": "torch.Tensor | None"}]]},
          "dynamic_arg_dims": {"type": ["object", "null"], "default": None, "description": "explicit {arg: dim}; null infers"},
          "is_encoder": {"type": "boolean", "default": False}}},
      response={"type": "object", "properties": {"dynamic_args": {"type": "array", "items": {"type": "string"}}, "is_encoder": {"type": "boolean"}}},
      errors=ERR("type-error", "value-error"),
      behavior=[
          {"if": "!input.has_forward", "title": "The class needs a forward method", "source": src(DC, 'raise TypeError("decorated class should have a forward method.")'),
           "then": [{"fail": {"code": "type-error", "message": "decorated class should have a forward method."}}]},
          {"set": {"vars.names": "= input.dynamic_arg_dims != null ? input.dynamic_arg_dims.map(k, k) : input.forward_params.filter(p, p.annotation in " + str(TS) + ").map(p, p.name)"},
           "title": "Explicit dims as given; else every Tensor / Optional[Tensor] / IntermediateTensors argument is dynamic in dim 0", "source": src(DC, "inferred_dynamic_arg_dims[k] = 0")},
          {"if": "size(vars.names) == 0", "title": "Nothing dynamic: refuse", "source": src(DC, "if len(inferred_dynamic_arg_dims) == 0:"),
           "then": [{"fail": {"code": "value-error", "message": "No dynamic dimensions found in the forward method. Please provide dynamic_arg_dims explicitly."}}]},
          {"foreach": "= vars.names", "as": "k", "title": "Every named argument must exist in forward()", "source": src(DC, "if k not in sig.parameters:"),
           "steps": [{"if": "!input.forward_params.exists(p, p.name == vars.k)",
                      "then": [{"fail": {"code": "value-error", "message": "= 'Argument ' + vars.k + ' not found in the forward method'"}}]}]},
          {"return": {"dynamic_args": "= vars.names", "is_encoder": "= input.is_encoder"},
           "title": "Wrap the class (_support_torch_compile)", "source": src(DC, "return _support_torch_compile(")},
      ])

iface("support-torch-compile", "ignore-torch-compile", kind="function", latency_ms=0,
      summary="@ignore_torch_compile: mark a subclass so the inherited @support_torch_compile does not compile its forward.",
      sources=[src(DC, "def ignore_torch_compile(cls: type[_T]) -> type[_T]:", span=17), src(DC, "def _should_ignore_torch_compile(cls: type[_T]) -> bool:", span=2)],
      request={"type": "object", "required": ["cls"], "properties": {"cls": {"type": "string", "examples": ["MyDraftModel"]}}},
      behavior=[{"set": {"= 'state.ignored.' + input.cls": True}, "title": "setattr(cls, IGNORE_COMPILE_KEY, True)", "source": src(DC, "setattr(cls, IGNORE_COMPILE_KEY, True)")},
                {"return": {"ignored": True}}])

iface("support-torch-compile", "init", kind="function", latency_ms=0,
      summary="The decorated __init__: run the model's __init__, then decide do_not_compile (mode NONE/STOCK_TORCH_COMPILE, @ignore_torch_compile, or enable_if false); otherwise count the model.",
      sources=[src(DC, "enable_compile = enable_if is None or enable_if(vllm_config)", span=12)],
      request={"type": "object", "properties": {"cls": {"type": "string", "default": "LlamaModel"}, "enable_if": {"type": "boolean", "default": True, "description": "enable_if(vllm_config); true when no enable_if"}}},
      response={"type": "object", "properties": {"do_not_compile": {"type": "boolean"}}},
      behavior=[
          {"set": {"vars.dnc": "= config['compilation-mode'] == 0 || config['compilation-mode'] == 1 || (input.cls in state.ignored && state.ignored[input.cls]) || !input.enable_if"},
           "title": "do_not_compile = mode in [NONE, STOCK_TORCH_COMPILE] or ignored or not enable_compile", "source": src(DC, "self.do_not_compile = (")},
          {"if": "vars.dnc", "title": "Nothing else to set up", "source": src(DC, "        if self.do_not_compile:"),
           "then": [{"return": {"do_not_compile": True}}]},
          count("num_models_seen", source=src(DC, "compilation_counter.num_models_seen += 1")),
          {"return": {"do_not_compile": False}},
      ])
COMPONENT_PATCHES["support-torch-compile"] = {"ignored": {}}

# ====================================================================== math utils
COMPONENTS.append(comp("math-utils", "Math utils", "module", "Integer helpers the kernels' shape logic uses (ceil division, powers of two, round up).",
                       [src(MU, "def cdiv(a: int, b: int) -> int:")], parent="kernels-ops"))
INT2 = {"type": "object", "required": ["a", "b"], "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}
iface("math-utils", "cdiv", kind="function", latency_ms=0, summary="cdiv(a, b): ceiling division -(a // -b).",
      sources=[src(MU, "def cdiv(a: int, b: int) -> int:", span=2)], request=INT2, errors=ERR("zero-division-error"),
      response={"type": "object", "properties": {"value": {"type": "integer"}}},
      behavior=[{"if": "input.b == 0", "title": "Python floor division by zero", "source": src(MU, "return -(a // -b)"),
                 "then": [{"fail": {"code": "zero-division-error", "message": "integer division or modulo by zero"}}]},
                {"set": {"vars.q": "= (-input.a) / input.b"}, "title": "Python // floors; CEL / truncates, so fix up the negative remainder"},
                {"return": {"value": "= -(((-input.a) % input.b != 0 && ((-input.a < 0) != (input.b < 0))) ? vars.q - 1 : vars.q)"}}])
iface("math-utils", "next-power-of-2", kind="function", latency_ms=0, summary="next_power_of_2(n): 1 for n < 1, else the smallest power of two >= n.",
      sources=[src(MU, "def next_power_of_2(n: int) -> int:", span=2)],
      request={"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}},
      response={"type": "object", "properties": {"value": {"type": "integer"}}},
      behavior=[{"if": "input.n < 1", "title": "n < 1 gives 1", "source": src(MU, "return 1 if n < 1 else 1 << (n - 1).bit_length()"), "then": [{"return": {"value": 1}}]},
                {"return": {"value": "= [1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32768,65536,131072,262144,524288,1048576,2097152,4194304,8388608,16777216,33554432,67108864,134217728,268435456,536870912,1073741824,2147483648,4294967296].filter(p, p >= input.n)[0]"},
                 "title": "1 << (n - 1).bit_length()"}])
iface("math-utils", "round-up", kind="function", latency_ms=0, summary="round_up(x, y): x rounded up to a multiple of y.",
      sources=[src(MU, "def round_up(x: int, y: int) -> int:", span=2)],
      request={"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}},
      response={"type": "object", "properties": {"value": {"type": "integer"}}},
      behavior=[{"return": {"value": "= ((input.x + input.y - 1) / input.y) * input.y"}, "title": "((x + y - 1) // y) * y", "source": src(MU, "return ((x + y - 1) // y) * y")}])

SCENARIOS.append({
    "id": "kernels-ops-math-utils", "name": "cdiv rounds up (also for negatives), next_power_of_2 is inclusive and 1 below 1, round_up to a multiple",
    "description": "vllm/utils/math_utils.py as tests/kernels call it for grid and block sizes.",
    "fixtures": ["tp1-llama-8b"],
    "steps": [{"interface": "math-utils.cdiv", "caller": "gpu-worker", "as": "c1", "input": {"a": 8193, "b": 16}},
              {"interface": "math-utils.cdiv", "caller": "gpu-worker", "as": "c2", "input": {"a": 8192, "b": 16}},
              {"interface": "math-utils.cdiv", "caller": "gpu-worker", "as": "c3", "input": {"a": -7, "b": 2}},
              {"interface": "math-utils.cdiv", "caller": "gpu-worker", "as": "c0", "input": {"a": 1, "b": 0}},
              {"interface": "math-utils.next-power-of-2", "caller": "gpu-worker", "as": "p1", "input": {"n": 14336}},
              {"interface": "math-utils.next-power-of-2", "caller": "gpu-worker", "as": "p2", "input": {"n": 4096}},
              {"interface": "math-utils.next-power-of-2", "caller": "gpu-worker", "as": "p3", "input": {"n": 0}},
              {"interface": "math-utils.round-up", "caller": "gpu-worker", "as": "r", "input": {"x": 4097, "y": 256}}],
    "expect": ["steps.c1.result.value.value == 513", "steps.c2.result.value.value == 512", "steps.c3.result.value.value == -3",
               "!steps.c0.result.ok && steps.c0.result.error.code == 'zero-division-error'",
               "steps.p1.result.value.value == 16384", "steps.p2.result.value.value == 4096", "steps.p3.result.value.value == 1",
               "steps.r.result.value.value == 4352"]})

# ====================================================================== ROCm AITER gating (rocm_aiter_ops)
FLAGS = [  # (config id, env var, class attr, deployed default)
    ("vllm-rocm-use-aiter", "VLLM_ROCM_USE_AITER", "_AITER_ENABLED", False),
    ("vllm-rocm-use-aiter-custom-ar", "VLLM_ROCM_USE_AITER_CUSTOM_AR", "_CUSTOM_ALL_REDUCE_ENABLED", True),
    ("vllm-rocm-use-aiter-linear", "VLLM_ROCM_USE_AITER_LINEAR", "_LINEAR_ENABLED", True),
    ("vllm-rocm-use-aiter-moe", "VLLM_ROCM_USE_AITER_MOE", "_FMOE_ENABLED", True),
    ("vllm-rocm-use-aiter-mha", "VLLM_ROCM_USE_AITER_MHA", "_MHA_ENABLED", True),
    ("vllm-rocm-shuffle-kv-cache-layout", "VLLM_ROCM_SHUFFLE_KV_CACHE_LAYOUT", "_SHUFFLE_KV_CACHE_ENABLED", False),
    ("vllm-rocm-use-aiter-triton-rope", "VLLM_ROCM_USE_AITER_TRITON_ROPE", "_TRITON_ROTARY_EMBED", False),
    ("vllm-rocm-use-aiter-fusion-shared-experts", "VLLM_ROCM_USE_AITER_FUSION_SHARED_EXPERTS", "_MOE_SHARED_EXPERTS_ENABLED", False),
]
CONFIGS = []
for cid, env, attr, dflt in FLAGS:
    CONFIGS.append(cfg(cid, "boolean", dflt, dflt, f"{env}: read by rocm_aiter_ops into {attr} at import and again by refresh_env_variables().",
                       [src(ENVS, f'"{env}": lambda: (')], env, env=True))
CONFIGS += [
    cfg("vllm-use-deep-gemm", "boolean", True, True, "VLLM_USE_DEEP_GEMM: allow DeepGEMM where the arch and package support it.",
        [src(ENVS, '"VLLM_USE_DEEP_GEMM": lambda: bool(int(os.getenv("VLLM_USE_DEEP_GEMM", "1"))),')], "VLLM_USE_DEEP_GEMM", env=True),
    cfg("vllm-use-deep-gemm-e8m0", "boolean", True, True, "VLLM_USE_DEEP_GEMM_E8M0: use E8M0 scales when DeepGEMM is used.",
        [src(ENVS, '"VLLM_USE_DEEP_GEMM_E8M0": lambda: bool(')], "VLLM_USE_DEEP_GEMM_E8M0", env=True),
]
COMPONENT_PATCHES["aiter-ops"] = {
    "aiter_found": False, "gcn_arch": "",
    "flags": {attr: dflt for _, _, attr, dflt in FLAGS},
}
FLAG_STATE = {"type": "object", "properties": {"aiter_found": {"type": "boolean"}, "gcn_arch": {"type": "string"}, "flags": {"type": "object"}}}

iface("aiter-ops", "is-aiter-found", kind="function", latency_ms=0,
      summary="is_aiter_found: find_spec('aiter'); evaluated once at import into IS_AITER_FOUND.",
      sources=[src(AIT, "def is_aiter_found() -> bool:", span=4), src(AIT, "IS_AITER_FOUND = is_aiter_found()")],
      response={"type": "object", "properties": {"found": {"type": "boolean"}}},
      behavior=[{"return": {"found": "= state.aiter_found"}, "title": "importlib.util.find_spec('aiter') is not None", "source": src(AIT, 'return find_spec("aiter") is not None')}])

iface("aiter-ops", "is-aiter-found-and-supported", kind="function", latency_ms=0,
      summary="is_aiter_found_and_supported: ROCm, aiter importable and a CDNA3+ device (gfx942, gfx950); env vars are not consulted.",
      sources=[src(AIT, "def is_aiter_found_and_supported() -> bool:", span=20), src(ROCM, "def get_cdna_version() -> int:", span=10)],
      response={"type": "object", "properties": {"supported": {"type": "boolean"}, "cdna_version": {"type": "integer"}}},
      behavior=[
          {"if": "config['vllm-target-device'] != 'rocm' || !state.aiter_found", "title": "Not ROCm, or no aiter package", "source": src(AIT, "if current_platform.is_rocm() and IS_AITER_FOUND:", nth=2),
           "then": [{"return": {"supported": False, "cdna_version": 0}}]},
          {"set": {"vars.cdna": "= state.gcn_arch == 'gfx90a' ? 2 : (state.gcn_arch == 'gfx942' ? 3 : (state.gcn_arch == 'gfx950' ? 4 : (state.gcn_arch == 'gfx1250' ? 5 : 0)))"},
           "title": "get_cdna_version: gfx90a 2, gfx942 3, gfx950 4, gfx1250 5, else 0", "source": src(ROCM, "def get_cdna_version() -> int:")},
          {"return": {"supported": "= vars.cdna > 2", "cdna_version": "= vars.cdna"}, "title": "CDNA 3 or newer", "source": src(AIT, "return get_cdna_version() > 2")},
      ])

iface("aiter-ops", "refresh-env-variables", kind="function", latency_ms=0,
      summary="rocm_aiter_ops.refresh_env_variables: re-read the VLLM_ROCM_* variables into the class attributes (they are otherwise frozen at import).",
      sources=[src(AIT, "    def refresh_env_variables(cls):", span=26)],
      response={"type": "object", "properties": {"flags": {"type": "object"}}},
      behavior=[{"set": {f"state.flags.{attr}": f"= config['{cid}']" for cid, _, attr, _ in FLAGS},
                 "title": "cls._AITER_ENABLED = envs.VLLM_ROCM_USE_AITER, ...", "source": src(AIT, "cls._AITER_ENABLED = envs.VLLM_ROCM_USE_AITER")},
                {"return": {"flags": "= state.flags"}}])

GATED = [  # (name, method, expression over state.flags)
    ("is-enabled", "is_enabled", "f._AITER_ENABLED"),
    ("is-linear-enabled", "is_linear_enabled", "f._AITER_ENABLED && f._LINEAR_ENABLED"),
    ("is-fused-moe-enabled", "is_fused_moe_enabled", "f._AITER_ENABLED && f._FMOE_ENABLED"),
    ("is-fusion-moe-shared-experts-enabled", "is_fusion_moe_shared_experts_enabled", "f._AITER_ENABLED && f._FMOE_ENABLED && f._MOE_SHARED_EXPERTS_ENABLED"),
    ("is-mha-enabled", "is_mha_enabled", "f._AITER_ENABLED && f._MHA_ENABLED"),
    ("is-custom-all-reduce-enabled", "is_custom_all_reduce_enabled", "f._AITER_ENABLED && f._CUSTOM_ALL_REDUCE_ENABLED"),
    ("is-shuffle-kv-cache-enabled", "is_shuffle_kv_cache_enabled", "f._SHUFFLE_KV_CACHE_ENABLED"),
    ("is-triton-rotary-embed-enabled", "is_triton_rotary_embed_enabled", "f._AITER_ENABLED && f._TRITON_ROTARY_EMBED"),
]
for name, meth, expr in GATED:
    ln = findline(AIT, f"    def {meth}(cls) -> bool:")
    iface("aiter-ops", name, kind="function", latency_ms=0,
          summary=f"rocm_aiter_ops.{meth}: @if_aiter_supported gate (None when AITER is not usable here), then the cached env flags.",
          sources=[f"{AIT}:{ln - 2}-{ln + 1}", src(AIT, "def if_aiter_supported(func: Callable) -> Callable:", span=13)],
          response=BOOL,
          behavior=[
              {"call": "aiter-ops.is-aiter-found-and-supported", "input": {}, "as": "s", "title": "if_aiter_supported: check the platform first",
               "source": src(AIT, "        if is_aiter_found_and_supported():")},
              {"if": "!vars.s.value.supported", "title": "Unsupported: the wrapper returns None without calling the method", "source": src(AIT, "        return None", start=findline(AIT, "def if_aiter_supported(")),
               "then": [{"return": {"enabled": None}}]},
              {"set": {"vars.f": "= state.flags"}},
              {"return": {"enabled": "= " + expr.replace("f.", "vars.f.")}, "title": f"{meth} reads the class attributes", "source": f"{AIT}:{ln + 1}"},
          ])

# the Python-side wrappers of the registered rocm_aiter_* ops
iface("aiter-ops", "rms-norm", kind="kernel", latency_ms=LATENCY["token"], request="KernelsOpsTokenShape",
      summary="rocm_aiter_ops.rms_norm: aiter.rms_norm(x, weight, epsilon) straight into the aiter library (no vLLM custom op).",
      sources=[src(AIT, '        """RMSNorm via AITER kernel."""', span=3)])
iface("aiter-ops", "fused-moe", kind="function", latency_ms=0, request="KernelsOpsMoeShape",
      summary="rocm_aiter_ops.fused_moe: forwards its 30 arguments to torch.ops.vllm.rocm_aiter_fused_moe.",
      sources=[src(AIT, "    def fused_moe(", span=65)],
      behavior=[{"call": "aiter-ops.rocm-aiter-fused-moe", "input": "= input", "title": "torch.ops.vllm.rocm_aiter_fused_moe(...)",
                 "source": src(AIT, "return torch.ops.vllm.rocm_aiter_fused_moe(")}, {"return": {"op": "vllm::rocm_aiter_fused_moe"}}])
iface("aiter-ops", "grouped-topk", kind="function", latency_ms=0, request="KernelsOpsMoeShape",
      summary="rocm_aiter_ops.grouped_topk: torch.ops.vllm.rocm_aiter_grouped_topk writes topk_weights/topk_ids in place.",
      sources=[src(AIT, "    def grouped_topk(", span=21)],
      behavior=[{"call": "aiter-ops.rocm-aiter-grouped-topk", "input": "= input", "source": src(AIT, "torch.ops.vllm.rocm_aiter_grouped_topk(")}, {"return": {"op": "vllm::rocm_aiter_grouped_topk"}}])
QREQ = {"type": "object", "properties": {"num_tokens": {"type": "integer", "examples": [16]}, "hidden_size": {"type": "integer", "examples": [4096]},
                                         "dtype_bytes": {"type": "integer", "examples": [2]}, "scale_given": {"type": "boolean", "default": False},
                                         "group_size": {"type": "integer", "default": 128}}}
iface("aiter-ops", "per-tensor-quant", kind="function", latency_ms=0, request=QREQ,
      summary="rocm_aiter_ops.per_tensor_quant: dynamic when no scale is given (a 1-element float32 scale is allocated), static otherwise.",
      sources=[src(AIT, "    def per_tensor_quant(", span=11)],
      response={"type": "object", "properties": {"is_dynamic": {"type": "boolean"}, "out_shape": {"type": "array"}}},
      behavior=[{"set": {"vars.dyn": "= !input.scale_given"}, "title": "is_dynamic = scale is None", "source": src(AIT, "is_dynamic = scale is None")},
                {"call": "aiter-ops.rocm-aiter-per-tensor-quant", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"},
                 "source": src(AIT, "torch.ops.vllm.rocm_aiter_per_tensor_quant(out, x, scale, is_dynamic)")},
                {"return": {"is_dynamic": "= vars.dyn", "out_shape": "= [input.num_tokens, input.hidden_size]"}}])
iface("aiter-ops", "per-token-quant", kind="function", latency_ms=0, request=QREQ,
      summary="rocm_aiter_ops.per_token_quant: torch.ops.vllm.rocm_aiter_per_token_quant (one scale per token).",
      sources=[src(AIT, "    def per_token_quant(", span=6)],
      response={"type": "object", "properties": {"scale_shape": {"type": "array"}}},
      behavior=[{"call": "aiter-ops.rocm-aiter-per-token-quant", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"},
                 "source": src(AIT, "return torch.ops.vllm.rocm_aiter_per_token_quant(x, quant_dtype, scale)")},
                {"return": {"scale_shape": "= [input.num_tokens, 1]"}}])
iface("aiter-ops", "group-fp8-quant", kind="function", latency_ms=0, request=QREQ,
      summary="rocm_aiter_ops.group_fp8_quant: only group size 128; one FP8 scale per 128 columns.",
      sources=[src(AIT, "    def group_fp8_quant(", span=10)],
      response={"type": "object", "properties": {"scale_shape": {"type": "array"}}},
      errors=ERR("assertion-error"),
      behavior=[{"if": "input.group_size != 128", "title": "assert group_size == 128", "source": src(AIT, 'assert group_size == 128, "Group size must be 128"'),
                 "then": [{"fail": {"code": "assertion-error", "message": "Group size must be 128"}}]},
                {"call": "aiter-ops.rocm-aiter-group-fp8-quant", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"},
                 "source": src(AIT, "return torch.ops.vllm.rocm_aiter_group_fp8_quant(", nth=1)},
                {"return": {"scale_shape": "= [input.num_tokens, (input.hidden_size + 127) / 128]"}}])
iface("aiter-ops", "get-group-quant-op", kind="function", latency_ms=0,
      summary="rocm_aiter_ops.get_group_quant_op: the OpOverload fusion passes match on.",
      sources=[src(AIT, "    def get_group_quant_op() -> OpOverload:", span=1)],
      response={"type": "object", "properties": {"op": {"type": "string"}}},
      behavior=[{"return": {"op": "vllm::rocm_aiter_group_fp8_quant.default"}, "source": src(AIT, "return torch.ops.vllm.rocm_aiter_group_fp8_quant.default")}])
iface("aiter-ops", "shuffle-weights", kind="function", latency_ms=0,
      summary="rocm_aiter_ops.shuffle_weight(s): aiter.ops.shuffle.shuffle_weight on each tensor into a (16, 16) block layout (weight load time).",
      sources=[src(AIT, "    def shuffle_weights(", span=21), src(AIT, "    def shuffle_weight(", span=6)],
      request={"type": "object", "properties": {"num_tensors": {"type": "integer", "default": 1}, "layout": {"type": "array", "default": [16, 16]}}},
      response={"type": "object", "properties": {"count": {"type": "integer"}, "layout": {"type": "array"}}},
      behavior=[{"return": {"count": "= input.num_tensors", "layout": "= input.layout"}, "title": "tuple(shuffle_weight(t, layout=layout) for t in tensors)",
                 "source": src(AIT, "return tuple(shuffle_weight(tensor, layout=layout) for tensor in tensors)")}])

ROCM_ST = lambda found, arch: {"aiter-ops@rank0": {"aiter_found": found, "gcn_arch": arch, "flags": {attr: d for _, _, attr, d in FLAGS}}}
SCENARIOS += [
    {"id": "kernels-ops-aiter-gate-cuda", "name": "On the CUDA deployment AITER is never supported: every @if_aiter_supported method returns None",
     "description": "tests/kernels/** gate ROCm paths with is_aiter_found_and_supported() and rocm_aiter_ops.is_*_enabled() (vllm/_aiter_ops.py:202-222, 283-288).",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "aiter-ops.is-aiter-found-and-supported", "caller": "gpu-worker", "as": "sup"},
               {"interface": "aiter-ops.is-fused-moe-enabled", "caller": "gpu-worker", "as": "moe"},
               {"interface": "aiter-ops.is-aiter-found", "caller": "gpu-worker", "as": "found"}],
     "expect": ["steps.sup.result.ok && !steps.sup.result.value.supported", "steps.moe.result.ok && steps.moe.result.value.enabled == null",
                "!steps.found.result.value.found"]},
    {"id": "kernels-ops-aiter-refresh-env", "name": "MI300X (gfx942) with aiter: VLLM_ROCM_USE_AITER=1 is only seen after refresh_env_variables",
     "description": "Unit tests monkeypatch VLLM_ROCM_USE_AITER and then call rocm_aiter_ops.refresh_env_variables(); before that the import-time class attribute (False) wins.",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "rocm", "vllm-rocm-use-aiter": True},
     "state": ROCM_ST(True, "gfx942"),
     "steps": [{"interface": "aiter-ops.is-enabled", "caller": "gpu-worker", "as": "before"},
               {"interface": "aiter-ops.refresh-env-variables", "caller": "gpu-worker", "as": "refresh"},
               {"interface": "aiter-ops.is-enabled", "caller": "gpu-worker", "as": "after"},
               {"interface": "aiter-ops.is-fused-moe-enabled", "caller": "gpu-worker", "as": "moe"},
               {"interface": "aiter-ops.is-fusion-moe-shared-experts-enabled", "caller": "gpu-worker", "as": "shared"},
               {"interface": "aiter-ops.is-shuffle-kv-cache-enabled", "caller": "gpu-worker", "as": "shuffle"},
               {"interface": "aiter-ops.is-triton-rotary-embed-enabled", "caller": "gpu-worker", "as": "rope"},
               {"interface": "aiter-ops.is-mha-enabled", "caller": "gpu-worker", "as": "mha"},
               {"interface": "aiter-ops.is-custom-all-reduce-enabled", "caller": "gpu-worker", "as": "car"}],
     "expect": ["steps.before.result.value.enabled == false", "steps.refresh.result.value.flags._AITER_ENABLED",
                "steps.after.result.value.enabled == true", "steps.moe.result.value.enabled == true", "steps.shared.result.value.enabled == false",
                "steps.shuffle.result.value.enabled == false", "steps.rope.result.value.enabled == false", "steps.mha.result.value.enabled == true", "steps.car.result.value.enabled == true", "state['aiter-ops@rank0'].flags._AITER_ENABLED"]},
    {"id": "kernels-ops-aiter-gate-old-arch", "name": "MI250 (gfx90a, CDNA2) with aiter installed is not supported; RDNA/unknown arch neither",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "rocm", "vllm-rocm-use-aiter": True}, "state": ROCM_ST(True, "gfx90a"),
     "steps": [{"interface": "aiter-ops.is-aiter-found-and-supported", "caller": "gpu-worker", "as": "sup"},
               {"interface": "aiter-ops.is-linear-enabled", "caller": "gpu-worker", "as": "lin"}],
     "expect": ["!steps.sup.result.value.supported && steps.sup.result.value.cdna_version == 2", "steps.lin.result.value.enabled == null"]},
    {"id": "kernels-ops-aiter-wrappers", "name": "rocm_aiter_ops wrappers: dynamic vs static per-tensor quant, per-token scale shape, group quant only at 128",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "rocm"},
     "steps": [{"interface": "aiter-ops.per-tensor-quant", "caller": "gpu-worker", "as": "dyn", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2}},
               {"interface": "aiter-ops.per-tensor-quant", "caller": "gpu-worker", "as": "stat", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "scale_given": True}},
               {"interface": "aiter-ops.per-token-quant", "caller": "gpu-worker", "as": "tok", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2}},
               {"interface": "aiter-ops.group-fp8-quant", "caller": "gpu-worker", "as": "g128", "input": {"num_tokens": 16, "hidden_size": 7168, "dtype_bytes": 2}},
               {"interface": "aiter-ops.group-fp8-quant", "caller": "gpu-worker", "as": "g64", "input": {"num_tokens": 16, "hidden_size": 7168, "dtype_bytes": 2, "group_size": 64}},
               {"interface": "aiter-ops.get-group-quant-op", "caller": "gpu-worker", "as": "op"},
               {"interface": "aiter-ops.fused-moe", "caller": "gpu-worker", "as": "moe", "input": {"num_tokens": 16, "num_experts": 8, "topk": 2, "n": 14336, "k": 4096, "dtype_bytes": 2}},
               {"interface": "aiter-ops.grouped-topk", "caller": "gpu-worker", "as": "topk", "input": {"num_tokens": 16, "num_experts": 256, "topk": 8, "n": 1, "k": 7168, "dtype_bytes": 4}},
               {"interface": "aiter-ops.shuffle-weights", "caller": "gpu-worker", "as": "sh", "input": {"num_tensors": 2}},
               {"interface": "aiter-ops.rms-norm", "caller": "gpu-worker", "as": "rms", "input": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2}}],
     "expect": ["steps.dyn.result.value.is_dynamic && !steps.stat.result.value.is_dynamic", "steps.tok.result.value.scale_shape == [16, 1]",
                "steps.g128.result.value.scale_shape == [16, 56]", "!steps.g64.result.ok && steps.g64.result.error.code == 'assertion-error'",
                "steps.op.result.value.op == 'vllm::rocm_aiter_group_fp8_quant.default'", "steps.moe.result.ok && steps.topk.result.ok",
                "steps.sh.result.value.count == 2 && steps.sh.result.value.layout == [16, 16]", "steps.rms.result.ok"]},
]

# ====================================================================== import probes (deep_gemm, deep_ep, flashinfer, triton_kernels)
PROBE_REQ = {"type": "object", "properties": {
    "installed": {"type": "array", "items": {"type": "string"},
                  "default": ["flashinfer", "triton_kernels", "vllm.third_party.triton_kernels"],
                  "description": "importable top-level modules (ASSUMPTION: the CUDA wheel's requirements install flashinfer-python; deep_gemm and deep_ep are optional extras)"},
    "flashinfer_cubin": {"type": "boolean", "default": False}, "nvcc": {"type": "boolean", "default": True}, "ninja": {"type": "boolean", "default": True},
    "flashinfer_moe_symbols": {"type": "boolean", "default": True},
    "device_capability": {"type": "integer", "default": 90}}}
COMPONENT_PATCHES.setdefault("import-utils", {})
iface("import-utils", "has-module", kind="function", latency_ms=0,
      summary="_has_module(name): find_spec, then a trial import; any failure counts as unavailable. has_deep_gemm (external or vendored), has_deep_ep and has_triton_kernels are built on it.",
      sources=[src(IU, "def _has_module(module_name: str) -> bool:", span=19), src(IU, "def has_deep_gemm() -> bool:", span=8), src(IU, "def has_deep_ep() -> bool:", span=2),
               src(IU, "def has_triton_kernels() -> bool:", span=7)],
      request={"type": "object", "required": ["probe"], "properties": {"probe": {"type": "string", "enum": ["deep_gemm", "deep_ep", "triton_kernels"]}, **PROBE_REQ["properties"]}},
      response={"type": "object", "properties": {"available": {"type": "boolean"}}},
      behavior=[
          {"if": "input.probe == 'deep_gemm'", "title": "deep_gemm: an external install wins, else the vendored copy", "source": src(IU, 'return _has_module("deep_gemm") or _has_module("vllm.third_party.deep_gemm")'),
           "then": [{"return": {"available": "= 'deep_gemm' in input.installed || 'vllm.third_party.deep_gemm' in input.installed"}}]},
          {"if": "input.probe == 'deep_ep'", "source": src(IU, 'return _has_module("deep_ep")'),
           "then": [{"return": {"available": "= 'deep_ep' in input.installed"}}]},
          {"set": {"vars.a": "= 'triton_kernels' in input.installed || 'vllm.third_party.triton_kernels' in input.installed"},
           "title": "triton_kernels: external or vendored; when present it is imported right away", "source": src(IU, "is_available = _has_module(\"triton_kernels\") or _has_module(")},
          {"return": {"available": "= vars.a"}},
      ])
iface("deep-gemm-utils", "is-deep-gemm-supported", kind="function", latency_ms=0,
      summary="is_deep_gemm_supported (cached): Hopper (SM90) or Blackwell (SM100/SM120) family, VLLM_USE_DEEP_GEMM, and the deep_gemm package.",
      sources=[src(DG, "def is_deep_gemm_supported() -> bool:", span=6), src(CUDA_PLAT, "def support_deep_gemm(cls) -> bool:", span=6)],
      request=PROBE_REQ, response={"type": "object", "properties": {"supported": {"type": "boolean"}}},
      behavior=[{"set": {"vars.arch": "= input.device_capability == 90 || (input.device_capability >= 100 && input.device_capability < 110) || (input.device_capability >= 120 && input.device_capability < 130)"},
                 "title": "current_platform.support_deep_gemm()", "source": src(DG, "is_supported_arch = current_platform.support_deep_gemm()")},
                {"call": "import-utils.has-module", "input": {"probe": "deep_gemm", "installed": "= input.installed"}, "as": "h"},
                {"return": {"supported": "= vars.arch && config['vllm-use-deep-gemm'] && vars.h.value.available"},
                 "source": src(DG, "return is_supported_arch and envs.VLLM_USE_DEEP_GEMM and has_deep_gemm()")}])
iface("deep-gemm-utils", "is-deep-gemm-e8m0-used", kind="function", latency_ms=0,
      summary="is_deep_gemm_e8m0_used (cached): DeepGEMM supported, its fp8_gemm_nt entry point found, and VLLM_USE_DEEP_GEMM_E8M0.",
      sources=[src(DG, "def is_deep_gemm_e8m0_used() -> bool:", span=22)],
      request=PROBE_REQ, response={"type": "object", "properties": {"used": {"type": "boolean"}, "reason": {"type": "string"}}},
      behavior=[{"call": "deep-gemm-utils.is-deep-gemm-supported", "input": "= input", "as": "s"},
                {"if": "!vars.s.value.supported", "title": "DeepGEMM not supported on this system", "source": src(DG, "if not is_deep_gemm_supported():", nth=1),
                 "then": [{"return": {"used": False, "reason": "not-supported"}}]},
                {"if": "config['vllm-use-deep-gemm-e8m0']", "title": "E8M0 enabled", "source": src(DG, "if envs.VLLM_USE_DEEP_GEMM_E8M0:"),
                 "then": [{"return": {"used": True, "reason": "enabled"}}]},
                {"return": {"used": False, "reason": "disabled"}, "source": src(DG, 'logger.info_once("DeepGEMM E8M0 disabled on current configuration.")')}])
COMPONENTS.append(comp("deep-gemm-utils", "DeepGEMM utils", "module", "DeepGEMM availability and scale-format probes (vllm/utils/deep_gemm.py).",
                       [src(DG, "def is_deep_gemm_supported() -> bool:")], parent="kernels-ops"))
iface("flashinfer", "has-flashinfer", kind="function", latency_ms=0,
      summary="has_flashinfer (cached): the flashinfer package is present, and either flashinfer-cubin is installed or nvcc and ninja are there for its JIT.",
      sources=[src(FI, "def has_flashinfer() -> bool:", span=19)],
      request=PROBE_REQ, response={"type": "object", "properties": {"available": {"type": "boolean"}}},
      behavior=[{"if": "!('flashinfer' in input.installed)", "title": "find_spec('flashinfer') is None", "source": src(FI, 'if importlib.util.find_spec("flashinfer") is None:'),
                 "then": [{"return": {"available": False}}]},
                {"if": "!input.flashinfer_cubin && (!input.nvcc || !input.ninja)", "title": "No cubins and no JIT toolchain: kernels disabled", "source": src(FI, "if not has_flashinfer_cubin() and ("),
                 "then": [{"return": {"available": False}}]},
                {"return": {"available": True}}])
iface("flashinfer", "has-flashinfer-fused-moe", kind="function", latency_ms=0,
      summary="has_flashinfer_trtllm_fused_moe / has_flashinfer_cutlass_fused_moe: FlashInfer MoE available and every required symbol importable.",
      sources=[src(FI, "def has_flashinfer_trtllm_fused_moe() -> bool:", span=16), src(FI, "def has_flashinfer_cutlass_fused_moe() -> bool:", span=18)],
      request={"type": "object", "properties": {"kind": {"type": "string", "enum": ["trtllm", "cutlass"], "default": "trtllm"}, **PROBE_REQ["properties"]}},
      response={"type": "object", "properties": {"available": {"type": "boolean"}}},
      behavior=[{"call": "flashinfer.has-flashinfer", "input": "= input", "as": "h", "title": "has_flashinfer_moe() needs FlashInfer first", "source": src(FI, "if not has_flashinfer_moe():", nth=1)},
                {"if": "!vars.h.value.available", "then": [{"return": {"available": False}}]},
                {"return": {"available": "= input.flashinfer_moe_symbols"}, "title": "Every (module, attr) pair resolves", "source": src(FI, "if not mod or not hasattr(mod, attr_name):", nth=1)}])
iface("flashinfer", "lazy-import-wrapper", kind="function", latency_ms=0,
      summary="_lazy_import_wrapper(module, attr, fallback): call the FlashInfer function when has_flashinfer() and the attribute resolve, else the fallback (which raises by default).",
      sources=[src(FI, "def _lazy_import_wrapper(", span=19)],
      request={"type": "object", "properties": {"attr": {"type": "string", "examples": ["fp4_quantize"]}, "attr_present": {"type": "boolean", "default": True}, **PROBE_REQ["properties"]}},
      response={"type": "object", "properties": {"impl": {"type": "string"}}},
      errors=ERR("runtime-error"),
      behavior=[{"call": "flashinfer.has-flashinfer", "input": "= input", "as": "h", "source": src(FI, "if not has_flashinfer():", nth=1), "title": "_get_impl: FlashInfer present?"},
                {"if": "!vars.h.value.available || !input.attr_present", "title": "No implementation: the fallback runs (_missing raises)", "source": src(FI, "return fallback_fn(*args, **kwargs)"),
                 "then": [{"fail": {"code": "runtime-error", "message": "FlashInfer backend is not available. Please install the package to enable FlashInfer kernels: https://github.com/flashinfer-ai/flashinfer"}}]},
                {"return": {"impl": "= 'flashinfer.' + input.attr"}, "source": src(FI, "return impl(*args, **kwargs)")}])
SCENARIOS += [
    {"id": "kernels-ops-import-probes-h100", "name": "H100 CUDA wheel: FlashInfer usable, triton_kernels present, no DeepGEMM package so DeepGEMM and E8M0 are off, no DeepEP",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "flashinfer.has-flashinfer", "caller": "gpu-worker", "as": "fi"},
               {"interface": "flashinfer.has-flashinfer-fused-moe", "caller": "gpu-worker", "as": "fimoe", "input": {"kind": "cutlass"}},
               {"interface": "import-utils.has-module", "caller": "gpu-worker", "as": "tk", "input": {"probe": "triton_kernels"}},
               {"interface": "import-utils.has-module", "caller": "gpu-worker", "as": "ep", "input": {"probe": "deep_ep"}},
               {"interface": "deep-gemm-utils.is-deep-gemm-supported", "caller": "gpu-worker", "as": "dg"},
               {"interface": "deep-gemm-utils.is-deep-gemm-e8m0-used", "caller": "gpu-worker", "as": "e8"}],
     "expect": ["steps.fi.result.value.available && steps.fimoe.result.value.available", "steps.tk.result.value.available", "!steps.ep.result.value.available",
                "!steps.dg.result.value.supported", "!steps.e8.result.value.used && steps.e8.result.value.reason == 'not-supported'"]},
    {"id": "kernels-ops-import-probes-deep-gemm", "name": "DeepGEMM installed: supported on SM90 and SM100, not on SM80; VLLM_USE_DEEP_GEMM_E8M0=0 turns E8M0 off",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-use-deep-gemm-e8m0": False},
     "steps": [{"interface": "deep-gemm-utils.is-deep-gemm-supported", "caller": "gpu-worker", "as": "h100", "input": {"installed": ["deep_gemm"]}},
               {"interface": "deep-gemm-utils.is-deep-gemm-supported", "caller": "gpu-worker", "as": "b200", "input": {"installed": ["vllm.third_party.deep_gemm"], "device_capability": 100}},
               {"interface": "deep-gemm-utils.is-deep-gemm-supported", "caller": "gpu-worker", "as": "a100", "input": {"installed": ["deep_gemm"], "device_capability": 80}},
               {"interface": "deep-gemm-utils.is-deep-gemm-e8m0-used", "caller": "gpu-worker", "as": "e8", "input": {"installed": ["deep_gemm"]}}],
     "expect": ["steps.h100.result.value.supported && steps.b200.result.value.supported && !steps.a100.result.value.supported",
                "!steps.e8.result.value.used && steps.e8.result.value.reason == 'disabled'"]},
    {"id": "kernels-ops-flashinfer-no-toolchain", "name": "FlashInfer without cubins and without nvcc: unavailable, and a lazily wrapped function raises",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "flashinfer.has-flashinfer", "caller": "gpu-worker", "as": "fi", "input": {"nvcc": False}},
               {"interface": "flashinfer.lazy-import-wrapper", "caller": "gpu-worker", "as": "w", "input": {"attr": "fp4_quantize", "nvcc": False}},
               {"interface": "flashinfer.lazy-import-wrapper", "caller": "gpu-worker", "as": "ok", "input": {"attr": "fp4_quantize"}}],
     "expect": ["!steps.fi.result.value.available", "!steps.w.result.ok && steps.w.result.error.code == 'runtime-error'", "steps.ok.result.value.impl == 'flashinfer.fp4_quantize'"]},
]

# ====================================================================== network and env helpers
COMPONENTS.append(comp("network-utils", "Network utils", "module", "Port selection and ZMQ/TCP address helpers (vllm/utils/network_utils.py).",
                       [src(NU, "def get_open_port() -> int:")], parent="kernels-ops"))
COMPONENTS.append(comp("system-utils", "System utils", "module", "Process environment helpers (vllm/utils/system_utils.py).",
                       [src(SU, "def update_environment_variables(envs_dict: dict[str, str]):")], parent="kernels-ops",
                       state={"schema": {"type": "object", "properties": {"environ": {"type": "object"}}}, "initial": {"environ": {}}}, capacity={"concurrency": 1}))
OFFS = list(range(0, 24))
iface("network-utils", "get-open-port", kind="function", latency_ms=0,
      summary="get_open_port: bind from VLLM_PORT upwards (or let the OS pick), skipping the 10 ports reserved for the data-parallel master.",
      sources=[src(NU, "def get_open_port() -> int:", span=13), src(NU, "def _get_reserved_port_range() -> range:", span=5), src(NU, "def _get_open_port(", span=31)],
      request={"type": "object", "properties": {
          "vllm_port": {"type": ["integer", "null"], "default": None, "description": "VLLM_PORT (config-platform's vllm-port)"},
          "dp_master_port": {"type": ["integer", "null"], "default": None, "description": "VLLM_DP_MASTER_PORT when set in the environment"},
          "ports_in_use": {"type": "array", "items": {"type": "integer"}, "default": []},
          "os_free_port": {"type": "integer", "default": 41000, "description": "the port the kernel hands out for bind(('', 0)) (stand-in)"}}},
      response={"type": "object", "properties": {"port": {"type": "integer"}}},
      errors=ERR("runtime-error"),
      behavior=[
          {"set": {"vars.lo": "= input.dp_master_port == null ? -1 : input.dp_master_port", "vars.hi": "= input.dp_master_port == null ? -1 : input.dp_master_port + 10"},
           "title": "Reserved range [VLLM_DP_MASTER_PORT, +10) when the variable is set", "source": src(NU, "return range(dp_master_port, dp_master_port + 10)")},
          {"set": {"vars.port": "= input.os_free_port"}, "title": "No VLLM_PORT: bind port 0 and take what the OS gives", "source": src(NU, 's.bind(("", 0))', nth=1)},
          {"if": "input.vllm_port != null", "title": "VLLM_PORT set: try it, then +1, ... until bind() succeeds", "source": src(NU, "port += 1  # Increment port number if already in use"),
           "then": [{"set": {"vars.port": "= " + str(OFFS) + ".map(i, input.vllm_port + i).filter(p, !(p in input.ports_in_use))[0]"}}]},
          {"if": "vars.port >= vars.lo && vars.port < vars.hi", "title": "Collides with the DP master's ports: search again from the end of the range (up to 1000 attempts)",
           "source": src(NU, "port = _get_open_port(start_port=reserved_port_range.stop, max_attempts=1000)"),
           "then": [{"set": {"vars.port": "= " + str(OFFS) + ".map(i, vars.hi + i).filter(p, !(p in input.ports_in_use))[0]"}}]},
          {"return": {"port": "= vars.port"}},
      ])
iface("system-utils", "update-environment-variables", kind="function", latency_ms=0,
      summary="update_environment_variables: write each key into os.environ, warning when an existing different value is overwritten.",
      sources=[src(SU, "def update_environment_variables(envs_dict: dict[str, str]):", span=10)],
      request={"type": "object", "required": ["envs"], "properties": {"envs": {"type": "object", "examples": [{"CUDA_VISIBLE_DEVICES": "0,1"}]}}},
      response={"type": "object", "properties": {"overwritten": {"type": "array", "items": {"type": "string"}}}},
      behavior=[{"set": {"vars.over": "= input.envs.map(k, k).filter(k, k in state.environ && state.environ[k] != input.envs[k])"},
                 "title": "Keys already set to another value are logged as overwritten", "source": src(SU, "if k in os.environ and os.environ[k] != v:")},
                {"set": {"state.environ": "= merge(state.environ, input.envs)"}, "title": "os.environ[k] = v", "source": src(SU, "os.environ[k] = v")},
                {"return": {"overwritten": "= vars.over"}}])
SCENARIOS += [
    {"id": "kernels-ops-get-open-port", "name": "get_open_port: VLLM_PORT taken moves up; a port in the DP master's reserved range is skipped; no VLLM_PORT asks the OS",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "network-utils.get-open-port", "caller": "gpu-worker", "as": "up", "input": {"vllm_port": 8000, "ports_in_use": [8000, 8001]}},
               {"interface": "network-utils.get-open-port", "caller": "gpu-worker", "as": "dp", "input": {"vllm_port": 29500, "dp_master_port": 29500, "ports_in_use": [29510]}},
               {"interface": "network-utils.get-open-port", "caller": "gpu-worker", "as": "os"}],
     "expect": ["steps.up.result.value.port == 8002", "steps.dp.result.value.port == 29511", "steps.os.result.value.port == 41000"]},
    {"id": "kernels-ops-update-environment-variables", "name": "update_environment_variables overwrites, and reports only keys whose value changed",
     "fixtures": ["tp1-llama-8b"], "state": {"system-utils@rank0": {"environ": {"CUDA_VISIBLE_DEVICES": "0", "NCCL_DEBUG": "INFO"}}},
     "steps": [{"interface": "system-utils.update-environment-variables", "caller": "gpu-worker", "as": "u",
                "input": {"envs": {"CUDA_VISIBLE_DEVICES": "0,1", "NCCL_DEBUG": "INFO", "VLLM_HOST_IP": "10.0.0.2"}}}],
     "expect": ["steps.u.result.value.overwritten == ['CUDA_VISIBLE_DEVICES']", "state['system-utils@rank0'].environ['CUDA_VISIBLE_DEVICES'] == '0,1'",
                "state['system-utils@rank0'].environ['VLLM_HOST_IP'] == '10.0.0.2'"]},
]

# ====================================================================== Helion registry helpers
iface("helion-config-manager", "get-instance", kind="function", latency_ms=0,
      summary="ConfigManager.get_instance / reset_instance / ConfigManager(base_dir): a process singleton bound to one base dir.",
      sources=[src(HCM, "    def get_instance(cls) -> ConfigManager:", span=7), src(HCM, "    def reset_instance(cls) -> None:", span=4), src(HCM, "    def __new__(cls, base_dir: str | Path | None = None) -> ConfigManager:", span=17)],
      request={"type": "object", "properties": {"op": {"type": "string", "enum": ["get", "create", "reset"], "default": "get"},
                                                "base_dir": {"type": "string", "default": "vllm/kernels/helion/configs"}}},
      response={"type": "object", "properties": {"base_dir": {"type": ["string", "null"]}}},
      errors=ERR("runtime-error", "value-error"),
      behavior=[
          {"if": "input.op == 'reset'", "title": "reset_instance (tests only)", "source": src(HCM, "cls._instance = None", nth=1),
           "then": [{"set": {"state.instance_base_dir": None}}, {"return": {"base_dir": None}}]},
          {"if": "input.op == 'get' && state.instance_base_dir == null", "title": "get_instance before construction", "source": src(HCM, "if cls._instance is None:", nth=1),
           "then": [{"fail": {"code": "runtime-error", "message": "ConfigManager instance has not been created. Call ConfigManager(base_dir=...) first to initialize."}}]},
          {"if": "input.op == 'get'", "then": [{"return": {"base_dir": "= state.instance_base_dir"}}]},
          {"if": "state.instance_base_dir != null && state.instance_base_dir != input.base_dir", "title": "A second base dir is refused",
           "source": src(HCM, "if cls._instance_base_dir != resolved_base_dir:"),
           "then": [{"fail": {"code": "value-error", "message": "= \"ConfigManager singleton already exists with base_dir '\" + state.instance_base_dir + \"', cannot create with different base_dir '\" + input.base_dir + \"'\""}}]},
          {"set": {"state.instance_base_dir": "= input.base_dir"}, "title": "First construction binds the base dir", "source": src(HCM, "cls._instance_base_dir = resolved_base_dir")},
          {"return": {"base_dir": "= input.base_dir"}},
      ])
COMPONENT_PATCHES["helion-config-manager"] = {"instance_base_dir": None}
iface("helion-kernel-wrapper", "get-registered-kernels", kind="function", latency_ms=0,
      summary="get_registered_kernels: a copy of the _REGISTERED_KERNELS map.",
      sources=[src(HREG, "def get_registered_kernels() -> dict[str, HelionKernelWrapper]:", span=1)],
      response={"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}}},
      behavior=[{"return": {"names": "= state.registered.map(k, k)"}, "source": src(HREG, "return _REGISTERED_KERNELS.copy()")}])
SCENARIOS += [
    {"id": "kernels-ops-helion-config-manager-singleton", "name": "Helion ConfigManager: get before create fails, a second base dir is refused, reset frees it",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "helion-config-manager.get-instance", "caller": "gpu-worker", "as": "g0"},
               {"interface": "helion-config-manager.get-instance", "caller": "gpu-worker", "as": "c1", "input": {"op": "create", "base_dir": "/tmp/a"}},
               {"interface": "helion-config-manager.get-instance", "caller": "gpu-worker", "as": "c2", "input": {"op": "create", "base_dir": "/tmp/b"}},
               {"interface": "helion-config-manager.get-instance", "caller": "gpu-worker", "as": "g1"},
               {"interface": "helion-config-manager.get-instance", "caller": "gpu-worker", "as": "r", "input": {"op": "reset"}},
               {"interface": "helion-config-manager.get-instance", "caller": "gpu-worker", "as": "c3", "input": {"op": "create", "base_dir": "/tmp/b"}}],
     "expect": ["!steps.g0.result.ok && steps.g0.result.error.code == 'runtime-error'", "steps.c1.result.ok",
                "!steps.c2.result.ok && steps.c2.result.error.code == 'value-error'", "steps.g1.result.value.base_dir == '/tmp/a'",
                "steps.c3.result.ok && steps.c3.result.value.base_dir == '/tmp/b'", "state['helion-config-manager@rank0'].instance_base_dir == '/tmp/b'"]},
    {"id": "kernels-ops-helion-registered-kernels", "name": "get_registered_kernels lists what register_kernel added",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "helion-kernel-wrapper.get-registered-kernels", "caller": "gpu-worker", "as": "before"},
               {"interface": "helion-kernel-wrapper.register-kernel", "caller": "gpu-worker", "as": "reg", "input": {"op_name": "silu_mul_fp8", "device_name": "NVIDIA H100 80GB HBM3"}},
               {"interface": "helion-kernel-wrapper.get-registered-kernels", "caller": "gpu-worker", "as": "after"}],
     "expect": ["size(steps.before.result.value.names) == 0", "steps.reg.result.ok", "steps.after.result.value.names == ['silu_mul_fp8']", "!state['helion-kernel-wrapper@rank0'].registered['silu_mul_fp8'].disabled"]},
]

# ====================================================================== Inductor pass context
COMPONENTS.append(comp("inductor-pass", "Inductor pass context", "module", "The PassContext (current compile range) that post-grad passes read while a range compiles.",
                       [src(IPASS, "class PassContext:")], parent="compilation",
                       state={"schema": {"type": "object", "properties": {"stack": {"type": "array"}}}, "initial": {"stack": []}}, capacity={"concurrency": 1}))
iface("inductor-pass", "pass-context", kind="function", latency_ms=0,
      summary="pass_context(compile_range): install a PassContext for the with-block (enter) and restore the previous one (exit).",
      sources=[src(IPASS, "def pass_context(compile_range: Range) -> Generator[None, None, None]:", span=11), src(IPASS, "class PassContext:", span=6)],
      request={"type": "object", "properties": {"phase": {"type": "string", "enum": ["enter", "exit"]}, "range_start": {"type": "integer", "default": 1}, "range_end": {"type": "integer", "default": 8192}}},
      behavior=[{"if": "input.phase == 'enter'", "title": "_pass_context = PassContext(compile_range), remembering the previous one", "source": src(IPASS, "_pass_context = PassContext(compile_range)"),
                 "then": [{"set": {"state.stack": "= state.stack + [{'start': input.range_start, 'end': input.range_end}]"}}, {"return": {"depth": "= size(state.stack)"}}]},
                {"set": {"state.stack": "= state.stack.size() > 0 ? state.stack.slice(0, size(state.stack) - 1) : []"}, "title": "finally: restore prev_context", "source": src(IPASS, "_pass_context = prev_context")},
                {"return": {"depth": "= size(state.stack)"}}])
iface("inductor-pass", "get-pass-context", kind="function", latency_ms=0,
      summary="get_pass_context: the innermost PassContext; asserts one is installed.",
      sources=[src(IPASS, "def get_pass_context() -> PassContext:", span=3)],
      response={"type": "object", "properties": {"range_start": {"type": "integer"}, "range_end": {"type": "integer"}}},
      errors=ERR("assertion-error"),
      behavior=[{"if": "size(state.stack) == 0", "title": "assert _pass_context is not None", "source": src(IPASS, "assert _pass_context is not None"),
                 "then": [{"fail": {"code": "assertion-error", "message": "no pass context"}}]},
                {"return": {"range_start": "= state.stack[size(state.stack) - 1].start", "range_end": "= state.stack[size(state.stack) - 1].end"}}])
SCENARIOS.append(
    {"id": "kernels-ops-pass-context-nesting", "name": "pass_context nests and restores; get_pass_context outside any context asserts",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "inductor-pass.get-pass-context", "caller": "gpu-worker", "as": "none"},
               {"interface": "inductor-pass.pass-context", "caller": "gpu-worker", "as": "e1", "input": {"phase": "enter", "range_start": 1, "range_end": 8192}},
               {"interface": "inductor-pass.pass-context", "caller": "gpu-worker", "as": "e2", "input": {"phase": "enter", "range_start": 16, "range_end": 16}},
               {"interface": "inductor-pass.get-pass-context", "caller": "gpu-worker", "as": "inner"},
               {"interface": "inductor-pass.pass-context", "caller": "gpu-worker", "as": "x2", "input": {"phase": "exit"}},
               {"interface": "inductor-pass.get-pass-context", "caller": "gpu-worker", "as": "outer"}],
     "expect": ["!steps.none.result.ok && steps.none.result.error.code == 'assertion-error'", "steps.inner.result.value.range_end == 16",
                "steps.outer.result.value.range_start == 1 && steps.outer.result.value.range_end == 8192", "size(state['inductor-pass@rank0'].stack) == 1"]})

# ====================================================================== vLLM IR: generate_inputs, set_priority, supports_args
DT = {1: "float8", 2: "bfloat16", 4: "float32"}
iface("ir-op", "generate-inputs", kind="function", latency_ms=0,
      summary="IrOp.generate_inputs(**kwargs): the op's registered input generator; RuntimeError when none is registered. gelu_and_mul_sparse makes x [T, 2H] plus std_multiplier and approximate='tanh'; rms_norm makes x [T, H], weight [H], epsilon.",
      sources=[src(IR, "    def generate_inputs(self, **kwargs: Any) -> tuple[Any, ...]:", span=6), src(IRACT, "def _gelu_and_mul_sparse_input_generator(", span=8),
               src(IRLN, "def _rms_norm_input_generator(", span=10)],
      request={"type": "object", "required": ["op"], "properties": {"op": {"type": "string"}, "num_tokens": {"type": "integer", "examples": [8]},
                                                                    "hidden_size": {"type": "integer", "examples": [4096]}, "dtype_bytes": {"type": "integer", "default": 2},
                                                                    "has_generator": {"type": "boolean", "default": True}}},
      response="KernelsOpsIrCall",
      errors=ERR("runtime-error"),
      behavior=[
          {"if": "!input.has_generator", "title": "No input generator registered", "source": src(IR, "if self._input_generator is None:", nth=1),
           "then": [{"fail": {"code": "runtime-error", "message": "= \"No input generator registered for op '\" + input.op + \"'. Use @ir.ops.\" + input.op + \".register_input_generator\""}}]},
          {"if": "input.op == 'gelu_and_mul_sparse'", "title": "x = randn(T, 2H); std_multiplier 1.645; approximate 'tanh'", "source": src(IRACT, "x = torch.randn(num_tokens, hidden_size * 2, dtype=dtype)"),
           "then": [{"return": {"op": "= input.op", "num_tokens": "= input.num_tokens", "hidden_size": "= 2 * input.hidden_size", "dtype_bytes": "= input.dtype_bytes",
                                "approximate": "tanh", "contiguous": True, "ndim": 2, "device_type": "= config['vllm-target-device']", "variance_size": 0, "weight_dtype_matches": True}}]},
          {"return": {"op": "= input.op", "num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes",
                      "approximate": "none", "contiguous": True, "ndim": 2, "device_type": "= config['vllm-target-device']", "variance_size": 0, "weight_dtype_matches": True},
           "title": "rms_norm / fused_add_rms_norm: x [T, H] (and residual), weight [H], epsilon 1e-5", "source": src(IRLN, "x = torch.randn(num_tokens, hidden_size, dtype=dtype, device=device)", nth=1)},
      ])
iface("ir-op", "impl-supports-args", kind="function", latency_ms=0,
      summary="IrOpImpl.supported / supports_args for one provider: the static platform check, then the provider's argument predicate (None means all args).",
      sources=[src(IR, "    def supports_args(self, *args, **kwargs) -> bool:", span=5), src(IR, "    def supports_all_args(self) -> bool:", span=3),
               src(TACT, "def _supports_gelu_and_mul_sparse(", span=16), src(TACT, '    supported=HAS_TRITON and current_platform.is_cuda(),')],
      request={"type": "object", "required": ["provider", "args"], "properties": {"provider": {"type": "string", "enum": ["native", "vllm_c", "oink", "triton"]}, "args": {"type": "object", "description": "the op's call arguments as KernelsOpsIrCall describes them"}}},
      response={"type": "object", "properties": {"supported": {"type": "boolean"}, "supports_args": {"type": "boolean"}}},
      behavior=[
          {"set": {"vars.p": "= input.provider", "vars.a": "= merge({'num_tokens': 16, 'hidden_size': 4096, 'dtype_bytes': 2, 'variance_size': 0, 'weight_dtype_matches': true, 'contiguous': true, 'ndim': 2, 'approximate': 'none', 'device_type': 'cuda'}, input.args)"}, "title": "Unspecified argument properties take the common case"},
          {"set": {"vars.supported": "= " + "(vars.p == 'native') || (vars.p == 'vllm_c' && config['vllm-target-device'] in ['cuda', 'rocm', 'xpu']) || (vars.p == 'triton' && config['vllm-target-device'] == 'cuda') || (vars.p == 'oink' && config['vllm-target-device'] == 'cuda')"},
           "title": "Static support (e.g. triton: HAS_TRITON and current_platform.is_cuda())", "source": src(TACT, '    supported=HAS_TRITON and current_platform.is_cuda(),')},
          {"if": "vars.p == 'triton'", "title": "_supports_gelu_and_mul_sparse: CUDA, fp16/bf16/fp32, contiguous, ndim > 0, tanh, even last dim with half <= 32768",
           "source": src(TACT, "last_dim > 0 and last_dim % 2 == 0 and last_dim // 2 <= _MAX_INTERMEDIATE_SIZE"),
           "then": [{"return": {"supported": "= vars.supported",
                                "supports_args": "= vars.a.op == 'gelu_and_mul_sparse' && vars.a.device_type == 'cuda' && (vars.a.dtype_bytes == 2 || vars.a.dtype_bytes == 4) && vars.a.contiguous && vars.a.ndim > 0 && vars.a.approximate == 'tanh' && vars.a.hidden_size > 0 && vars.a.hidden_size % 2 == 0 && vars.a.hidden_size / 2 <= 32768"}}]},
          {"if": "vars.p == 'vllm_c'", "source": src(IR, "return self._supports_args(*args, **kwargs)"),
           "then": [{"return": {"supported": "= vars.supported", "supports_args": "= vars.a.op != 'gelu_and_mul_sparse' && vars.a.variance_size == 0 && vars.a.weight_dtype_matches"}}]},
          {"if": "vars.p == 'oink'", "then": [{"return": {"supported": "= vars.supported", "supports_args": "= vars.a.op != 'gelu_and_mul_sparse' && vars.a.ndim == 2 && vars.a.contiguous"}}]},
          {"return": {"supported": True, "supports_args": True}, "title": "native: supports_args is None, so every call is supported", "source": src(IR, "if self._supports_args is None:", nth=1)},
      ])
iface("ir-op", "set-priority", kind="function", latency_ms=0,
      summary="IrOp.set_priority(priority) / set_default: filter the list to supported providers (native appended when some provider is conditional) and dispatch with it; set_priority restores the old list on exit.",
      sources=[src(IR, "    def set_priority(self, priority: list[str]):", span=12), src(IR, "    def set_default(self, priority: list[str]) -> None:", span=10)],
      request={"type": "object", "required": ["op", "priority", "args"], "properties": {"op": {"type": "string"}, "priority": {"type": "array", "items": {"type": "string"}}, "args": {"type": "object", "description": "the op's call arguments as KernelsOpsIrCall describes them"}}},
      response={"type": "object", "properties": {"provider": {"type": "string"}, "restored": {"type": "array"}}},
      behavior=[
          {"set": {"vars.old": "= input.op in config['ir-op-priority'] ? config['ir-op-priority'][input.op] : []"}, "title": "old_priority_impls = self._priority_impls",
           "source": src(IR, "old_priority_impls = self._priority_impls")},
          {"title": "Inside the with-block the op dispatches with the new priority", "source": src(IR, "self._priority_impls = self._filter_priority_impls(priority)", nth=2),
           "call": "ir-op.call", "input": "= merge(merge({'num_tokens': 16, 'hidden_size': 4096, 'dtype_bytes': 2, 'variance_size': 0, 'weight_dtype_matches': true, 'contiguous': true, 'ndim': 2, 'approximate': 'none', 'device_type': 'cuda'}, input.args), {'op': input.op, 'priority_override': input.priority})", "as": "d"},
          {"return": {"provider": "= vars.d.value.provider", "restored": "= vars.old"}, "title": "finally: self._priority_impls = old_priority_impls", "source": src(IR, "self._priority_impls = old_priority_impls")},
      ])

# ====================================================================== persistent_topk / cooperative_topk host checks
TOPK_REQ = {"type": "object", "properties": {
    "num_rows": {"type": "integer", "default": 4}, "k": {"type": "integer", "default": 2048}, "max_seq_len": {"type": "integer", "default": 8192},
    "row_stride": {"type": "integer", "default": 8192, "description": "logits.stride(0): the padded row length"},
    "lengths_numel": {"type": ["integer", "null"], "default": None, "description": "null: equal to num_rows"},
    "output_cols": {"type": ["integer", "null"], "default": None, "description": "null: equal to k"},
    "logits_dtype": {"type": "string", "default": "float32"}, "workspace_bytes": {"type": "integer", "default": 67108864},
    "device_major": {"type": "integer", "default": 9, "description": "compute capability major of the device (H100: 9)"},
    "num_tokens": {"type": "integer", "default": 4}, "hidden_size": {"type": "integer", "default": 8192}, "dtype_bytes": {"type": "integer", "default": 4}}}
CHECKS = lambda f: [
    {"if": "config['vllm-target-device'] == 'rocm'", "title": "Not built for ROCm", "source": src(f, "is not supported on ROCm"),
     "then": [{"fail": {"code": "runtime-error", "message": "= '" + ("persistent_topk" if f == TOPK else "cooperative_topk") + " is not supported on ROCm'"}}]},
    {"if": "input.logits_dtype != 'float32'", "title": "Only float32 logits", "source": src(f, '"Only float32 supported");'),
     "then": [{"fail": {"code": "runtime-error", "message": "Only float32 supported"}}]},
    {"if": "(input.lengths_numel == null ? input.num_rows : input.lengths_numel) != input.num_rows", "title": "One length per row", "source": src(f, 'STD_TORCH_CHECK(lengths.numel() == num_rows, "lengths size mismatch");'),
     "then": [{"fail": {"code": "runtime-error", "message": "lengths size mismatch"}}]},
    {"if": "(input.output_cols == null ? input.k : input.output_cols) != input.k", "title": "Output is [num_rows, k]", "source": src(f, '"output size mismatch");'),
     "then": [{"fail": {"code": "runtime-error", "message": "output size mismatch"}}]},
    {"if": "!(input.k in [512, 1024, 2048])", "title": "k is one of 512, 1024, 2048", "source": src(f, "k == 512 || k == 1024 || k == 2048,"),
     "then": [{"fail": {"code": "runtime-error", "message": "= '" + ("persistent_topk" if f == TOPK else "cooperative_topk") + " supports k=512, k=1024, or k=2048, got k=' + string(input.k)"}}]},
]
H100_SMEM = 232448  # sharedMemPerBlockOptin on H100 (227 KiB); ASSUMPTION for the fixture's device
OP_BEHAVIORS["torch-bindings.persistent-topk"] = {
    "request": TOPK_REQ,
    "response": {"type": "object", "properties": {"path": {"type": "string"}, "kernel": {"type": "string"}, "vec_size": {"type": "integer"}}},
    "errors": ERR("runtime-error"),
    "behavior": CHECKS(TOPK) + [
        {"set": {"vars.min_sampled": "= input.k == 512 ? 98304 : 65536"}, "title": "kMinSampledLength<K>", "source": src(STOPK, "constexpr int kMinSampledLength = K == 512 ? 98304 : 65536;")},
        {"if": f"input.num_rows > 64 && input.max_seq_len >= vars.min_sampled && {H100_SMEM} >= 144 * 1024",
         "title": "Many long rows: one CTA per row, sampled top-k", "source": src(TOPK, "if (num_rows > 64 &&"),
         "then": [{"return": {"path": "sampled", "kernel": "sampled_topk_kernel", "vec_size": 0}}]},
        {"if": f"input.num_rows > 32 && {H100_SMEM} >= 128 * 1024", "title": "More than 32 rows: FilteredTopK ragged transform", "source": src(TOPK, "} else if (num_rows > 32 && max_smem_per_block >= 128 * 1024) {"),
         "then": [{"return": {"path": "filtered", "kernel": "FilteredTopKUnifiedKernel", "vec_size": 0}}]},
        {"set": {"vars.vec": "= input.row_stride % 4 == 0 ? 4 : (input.row_stride % 2 == 0 ? 2 : 1)"}, "title": "Vector width from the row stride", "source": src(TOPK, "if (stride % 4 == 0)")},
        {"return": {"path": "persistent", "kernel": "persistent_topk_kernel", "vec_size": "= vars.vec"},
         "title": "Few rows: the cooperative persistent kernel over row chunks", "source": src(TOPK, "uint32_t ctas_per_group =")},
    ]}
OP_BEHAVIORS["torch-bindings.cooperative-topk"] = {
    "request": TOPK_REQ,
    "response": {"type": "object", "properties": {"cluster_size": {"type": "integer"}}},
    "errors": ERR("runtime-error"),
    "behavior": CHECKS(CTOPK) + [
        {"if": "input.num_rows > 64", "title": "At most 64 rows", "source": src(CTOPK, "num_rows <= 64,"),
         "then": [{"fail": {"code": "runtime-error", "message": "cooperative_topk supports <=64 rows; use persistent_topk for larger batches"}}]},
        {"if": "input.row_stride % 4 != 0", "title": "TMA needs the row stride to be a multiple of 4", "source": src(CTOPK, "STD_TORCH_CHECK(stride % 4 == 0,"),
         "then": [{"fail": {"code": "runtime-error", "message": "= 'cooperative_topk: stride must be multiple of 4 for TMA alignment, got stride (max_model_len)=' + string(input.row_stride)"}}]},
        {"set": {"vars.sm100": "= input.device_major >= 10"}, "title": "Cluster 16 needs SM100+", "source": src(CTOPK, "const bool supports_cluster16 = get_device_prop()->major >= 10;")},
        {"return": {"cluster_size": "= input.num_rows <= 4 && vars.sm100 ? 16 : (input.num_rows <= 8 ? 8 : (input.num_rows <= 33 ? 4 : 2))"},
         "title": "Cluster size by row count", "source": src(CTOPK, "if (num_rows <= 4 && supports_cluster16) {")},
    ]}
SCENARIOS.append(
    {"id": "kernels-ops-topk-host-checks", "name": "persistent_topk / cooperative_topk: path by row count, k and dtype checks, cooperative limits",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "torch-bindings.persistent-topk", "caller": "gpu-worker", "as": "few", "input": {"num_rows": 4, "row_stride": 16390, "max_seq_len": 16390}},
               {"interface": "torch-bindings.persistent-topk", "caller": "gpu-worker", "as": "mid", "input": {"num_rows": 48}},
               {"interface": "torch-bindings.persistent-topk", "caller": "gpu-worker", "as": "many", "input": {"num_rows": 256, "max_seq_len": 163840, "row_stride": 163840}},
               {"interface": "torch-bindings.persistent-topk", "caller": "gpu-worker", "as": "badk", "input": {"k": 256}},
               {"interface": "torch-bindings.persistent-topk", "caller": "gpu-worker", "as": "bf16", "input": {"logits_dtype": "bfloat16"}},
               {"interface": "torch-bindings.cooperative-topk", "caller": "gpu-worker", "as": "coop", "input": {"num_rows": 2}},
               {"interface": "torch-bindings.cooperative-topk", "caller": "gpu-worker", "as": "rows", "input": {"num_rows": 65}},
               {"interface": "torch-bindings.cooperative-topk", "caller": "gpu-worker", "as": "stride", "input": {"num_rows": 4, "row_stride": 2063}}],
     "expect": ["steps.few.result.value.path == 'persistent' && steps.few.result.value.vec_size == 2", "steps.mid.result.value.path == 'filtered'",
                "steps.many.result.value.path == 'sampled'", "!steps.badk.result.ok && steps.badk.result.error.message.contains('got k=256')",
                "!steps.bf16.result.ok", "steps.coop.result.value.cluster_size == 8",
                "!steps.rows.result.ok && steps.rows.result.error.message.contains('<=64 rows')", "!steps.stride.result.ok && steps.stride.result.error.message.contains('stride')"]})

# ====================================================================== compile cache key and counter scenarios
SCENARIOS += [
    {"id": "kernels-ops-compile-cache-dir-full", "name": "Full deployment: the compile cache dir carries its config hash",
     "description": "oracle2 config-platform fix request 3 (kernels-ops half): VllmBackend.__call__ hashes [env, config, code, compiler] into the cache dir (backends.py:1065-1086).",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "vllm-backend.call", "caller": "gpu-worker", "as": "be", "input": {"num_layers": 2, "prefix": "backbone", "config_hash": "cfg-full"}}],
     "expect": ["steps.be.result.ok && steps.be.result.value.local_cache_dir == '~/.cache/vllm/torch_compile_cache/env0-cfg-full-code0-inductor/rank_0_0/backbone'",
                "'~/.cache/vllm/torch_compile_cache/env0-cfg-full-code0-inductor/rank_0_0/backbone/vllm_compile_cache.py' in state['torch-compile-cache@rank0'].files"]},
    {"id": "kernels-ops-compile-cache-dir-lm-only", "name": "language_model_only changes ModelConfig.compute_hash, so the LM-only deployment compiles into another dir",
     "description": "tests/config/test_multimodal_config.py::test_language_model_only_affects_model_hash, compile-cache half: a different config hash gives a different directory.",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "vllm-backend.call", "caller": "gpu-worker", "as": "be", "input": {"num_layers": 2, "prefix": "backbone", "config_hash": "cfg-lm-only"}}],
     "expect": ["steps.be.result.value.cache_dir == '~/.cache/vllm/torch_compile_cache/env0-cfg-lm-only-code0-inductor'",
                "!('~/.cache/vllm/torch_compile_cache/env0-cfg-full-code0-inductor/rank_0_0/backbone/vllm_compile_cache.py' in state['torch-compile-cache@rank0'].files)"]},
    {"id": "kernels-ops-compile-cache-dir-from-vllm-config-hash", "name": "Without a given config hash the backend keys the cache dir by VllmConfig.compute_hash of the resolved config",
     "description": "backends.py: config_hash = vllm_config.compute_hash(), one of the four factors of the cache dir name (config-platform's vllm-config.compute-hash).",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"flow": "config-create-engine-config", "as": "cfg"},
               {"flow": "config-compile-cache-key", "as": "key"},
               {"interface": "vllm-backend.call", "caller": "gpu-worker", "as": "be", "input": {"num_layers": 2, "prefix": "backbone"}}],
     "expect": ["steps.be.result.ok && steps.be.result.value.cache_dir == '~/.cache/vllm/torch_compile_cache/env0-' + steps.key.result.value.hash + '-code0-inductor'",
                "calls['vllm-config.compute-hash'] == 2",
                "('~/.cache/vllm/torch_compile_cache/env0-' + steps.key.result.value.hash + '-code0-inductor/rank_0_0/backbone/vllm_compile_cache.py') in state['torch-compile-cache@rank0'].files"]},
    {"id": "kernels-ops-compile-cache-dir-explicit", "name": "compilation_config.cache_dir set: used as is, with the rank directory below it",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "vllm-backend.call", "caller": "gpu-worker", "as": "be", "input": {"num_layers": 2, "prefix": "backbone", "cache_dir": "/mnt/cc", "rank": 1}}],
     "expect": ["steps.be.result.value.local_cache_dir == '/mnt/cc/rank_1_0/backbone'", "'/mnt/cc/rank_1_0/backbone/vllm_compile_cache.py' in state['torch-compile-cache@rank0'].files"]},
    {"id": "kernels-ops-compilation-counter-cold-compile", "name": "compilation_counter.expect around a cold Llama-3.1-8B compile: 1 graph, 65 pieces, 33 compiled and saved",
     "description": "tests/compile/** wrap compiles in `with compilation_counter.expect(...)`; the model's counter is incremented where the code increments it.",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "compilation-counter.clone", "caller": "gpu-worker", "as": "before"},
               {"interface": "vllm-backend.call", "caller": "gpu-worker", "as": "be", "input": {"num_layers": 32, "prefix": "backbone"}},
               {"interface": "compilation-counter.expect", "caller": "gpu-worker", "as": "ok", "input": {"before": {c: 0 for c in COUNTERS}, "expected": [
                   {"field": "num_graphs_seen", "diff": 1}, {"field": "num_piecewise_graphs_seen", "diff": 65}, {"field": "num_piecewise_capturable_graphs_seen", "diff": 33},
                   {"field": "num_backend_compilations", "diff": 33}, {"field": "num_inductor_compiles", "diff": 33}, {"field": "num_cache_entries_updated", "diff": 33},
                   {"field": "num_compiled_artifacts_saved", "diff": 33}, {"field": "num_cudagraph_captured", "diff": 0}]}},
               {"interface": "compilation-counter.expect", "caller": "gpu-worker", "as": "bad", "input": {"before": {c: 0 for c in COUNTERS}, "expected": [{"field": "num_cudagraph_captured", "diff": 1}]}}],
     "expect": ["steps.before.result.value.counters.num_graphs_seen == 0", "steps.ok.result.ok",
                "!steps.bad.result.ok && steps.bad.result.error.code == 'assertion-error' && steps.bad.result.error.message.contains('num_cudagraph_captured not as expected')",
                "state['compilation-counter@rank0'].counters.num_compiled_artifacts_saved == 33"]},
    {"id": "kernels-ops-support-torch-compile-decorate", "name": "@support_torch_compile infers dims from tensor annotations, refuses none or unknown names; init honours @ignore_torch_compile and enable_if",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "llama"},
               {"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "nodims", "input": {"forward_params": [{"name": "x", "annotation": "int"}]}},
               {"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "unknown", "input": {"dynamic_arg_dims": {"y": 0}, "forward_params": [{"name": "x", "annotation": "torch.Tensor"}]}},
               {"interface": "support-torch-compile.decorate", "caller": "gpu-worker", "as": "noforward", "input": {"has_forward": False}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "compiled"},
               {"interface": "support-torch-compile.ignore-torch-compile", "caller": "gpu-worker", "as": "ign", "input": {"cls": "MyDraftModel"}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "ignored", "input": {"cls": "MyDraftModel"}},
               {"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "disabled", "input": {"enable_if": False}},
               {"interface": "compilation-counter.clone", "caller": "gpu-worker", "as": "cnt"}],
     "expect": ["steps.llama.result.value.dynamic_args == ['input_ids', 'positions', 'intermediate_tensors', 'inputs_embeds']",
                "!steps.nodims.result.ok && steps.nodims.result.error.code == 'value-error'",
                "!steps.unknown.result.ok && steps.unknown.result.error.message.contains('Argument y not found')",
                "!steps.noforward.result.ok && steps.noforward.result.error.code == 'type-error'",
                "!steps.compiled.result.value.do_not_compile && steps.ignored.result.value.do_not_compile && steps.disabled.result.value.do_not_compile",
                "steps.cnt.result.value.counters.num_models_seen == 1", "state['support-torch-compile@rank0'].ignored['MyDraftModel']"]},
    {"id": "kernels-ops-support-torch-compile-init-eager", "name": "Mode NONE (enforce_eager): do_not_compile, nothing counted",
     "fixtures": ["tp1-llama-8b"], "config": {"compilation-mode": 0},
     "steps": [{"interface": "support-torch-compile.init", "caller": "gpu-worker", "as": "i"}, {"interface": "compilation-counter.clone", "caller": "gpu-worker", "as": "cnt"}],
     "expect": ["steps.i.result.value.do_not_compile", "steps.cnt.result.value.counters.num_models_seen == 0"]},
    {"id": "kernels-ops-ir-generate-inputs-supports-args", "name": "vllm.ir: generated gelu_and_mul_sparse inputs are [T, 2H] tanh; Triton supports them on CUDA up to 32768, refuses exact GELU; set_priority dispatches and restores",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "ir-op.generate-inputs", "caller": "gpu-worker", "as": "gen", "input": {"op": "gelu_and_mul_sparse", "num_tokens": 8, "hidden_size": 13824}},
               {"interface": "ir-op.impl-supports-args", "caller": "gpu-worker", "as": "tri",
                "input": {"provider": "triton", "args": {"op": "gelu_and_mul_sparse", "num_tokens": 8, "hidden_size": 27648, "dtype_bytes": 2, "approximate": "tanh", "contiguous": True, "ndim": 2, "device_type": "cuda"}}},
               {"interface": "ir-op.impl-supports-args", "caller": "gpu-worker", "as": "big",
                "input": {"provider": "triton", "args": {"op": "gelu_and_mul_sparse", "num_tokens": 8, "hidden_size": 65538, "dtype_bytes": 2, "approximate": "tanh", "contiguous": True, "ndim": 2, "device_type": "cuda"}}},
               {"interface": "ir-op.impl-supports-args", "caller": "gpu-worker", "as": "exact",
                "input": {"provider": "triton", "args": {"op": "gelu_and_mul_sparse", "num_tokens": 8, "hidden_size": 4096, "dtype_bytes": 2, "approximate": "none", "contiguous": True, "ndim": 2, "device_type": "cuda"}}},
               {"interface": "ir-op.impl-supports-args", "caller": "gpu-worker", "as": "native",
                "input": {"provider": "native", "args": {"op": "rms_norm", "variance_size": 64}}},
               {"interface": "ir-op.generate-inputs", "caller": "gpu-worker", "as": "nogen", "input": {"op": "rms_norm", "has_generator": False}},
               {"interface": "ir-op.set-priority", "caller": "gpu-worker", "as": "prio",
                "input": {"op": "rms_norm", "priority": ["vllm_c", "native"], "args": {"num_tokens": 16, "hidden_size": 4096, "dtype_bytes": 2, "variance_size": 0, "ndim": 2, "approximate": "none", "device_type": "cuda"}}}],
     "expect": ["steps.gen.result.value.hidden_size == 27648 && steps.gen.result.value.approximate == 'tanh'",
                "steps.tri.result.value.supported && steps.tri.result.value.supports_args", "!steps.big.result.value.supports_args",
                "!steps.exact.result.value.supports_args", "steps.native.result.value.supports_args",
                "!steps.nogen.result.ok && steps.nogen.result.error.code == 'runtime-error'",
                "steps.prio.result.value.provider == 'vllm_c' && steps.prio.result.value.restored == ['native']"]},
]

# ====================================================================== ROCm AITER fusion passes (pattern-level, like the CUDA passes)
RAF = "vllm/compilation/passes/fusion/rocm_aiter_fusion.py"
CFG_C = "vllm/config/compilation.py"
CFG_V = "vllm/config/vllm.py"
CONFIGS += [
    cfg("fuse-act-padding", "boolean", False, None,
        "pass_config.fuse_act_padding: -O2 uses enable_norm_pad_fusion (AITER fused_add_rms_norm first and hidden size 2880, i.e. gpt-oss); false on the CUDA fixture.",
        [src(CFG_C, "    fuse_act_padding: bool = None"), src(CFG_V, "def enable_norm_pad_fusion")], "compilation_config.pass_config.fuse_act_padding", default_null=True),
    cfg("fuse-mla-dual-rms-norm", "boolean", False, None,
        "pass_config.fuse_mla_dual_rms_norm: -O2 uses enable_mla_dual_rms_norm_fusion (rocm_aiter_ops.is_enabled()); false on the CUDA fixture.",
        [src(CFG_C, "    fuse_mla_dual_rms_norm: bool = None"), src(CFG_V, "def enable_mla_dual_rms_norm_fusion")], "compilation_config.pass_config.fuse_mla_dual_rms_norm", default_null=True),
]


def pat(cls, method="    def pattern(", nth=1):
    """Citation of a pattern class: from the class line through its pattern closure."""
    start = findline(RAF, f"class {cls}")
    return f"{RAF}:{start}-{findline(RAF, method, start=start, nth=nth) + 8}"


RQ_TABLE = [  # (graph pattern, fused op, condition, pattern class) in registration order (Double first)
    ("rms_norm+2x_group_fp8_quant", "vllm::rocm_aiter_rmsnorm_fp8_group_quant", "true", "DoubleAiterRMSFp8GroupQuantPattern"),
    ("rms_norm+view+2x_group_fp8_quant", "vllm::rocm_aiter_rmsnorm_fp8_group_quant", "true", "DoubleAiterRMSFp8GroupQuantViewPattern"),
    ("rms_norm+group_fp8_quant", "vllm::rocm_aiter_rmsnorm_fp8_group_quant", "true", "AiterRMSFp8GroupQuantPattern"),
    ("fused_add_rms_norm+group_fp8_quant", "vllm::rocm_aiter_rmsnorm_with_add_fp8_group_quant", "true", "AiterFusedAddRMSFp8GroupQuantPattern"),
    ("rms_norm+per_token_fp8_quant", "vllm::rocm_aiter_rmsnorm_fused_dynamic_quant", "!(has(input.rdna) && input.rdna)", "AiterRMSNormDynamicQuantPattern"),
    ("fused_add_rms_norm+per_token_fp8_quant", "vllm::rocm_aiter_rmsnorm_fused_add_dynamic_quant", "!(has(input.rdna) && input.rdna)", "AiterFusedAddRMSNormDynamicQuantPattern"),
    ("rms_norm_gated+group_fp8_quant", "vllm::fused_rms_gated_fp8_group_quant", "has(input.gdn_head_dims) && 128 in input.gdn_head_dims && (!has(input.gdn_triton_kernels) || input.gdn_triton_kernels)", "AiterRMSNormGatedFp8GroupQuantPattern"),
]
TBL = "[" + ", ".join(f"{{'p': '{p}', 'op': '{op}', 'on': {cond}}}" for p, op, cond, _ in RQ_TABLE) + "]"
iface("rocm-aiter-rms-norm-quant-fusion-pass", "call", kind="function", latency_ms=0,
      summary="RocmAiterRMSNormQuantFusionPass: replace AITER rms_norm / fused_add_rms_norm followed by a group or per-token FP8 quant with one fused AITER op (double-quant fan-outs first; per-token patterns not on RDNA4; gated-norm only for 128-wide GDN heads).",
      sources=[src(RAF, "class RocmAiterRMSNormQuantFusionPass(VllmPatternMatcherPass):", span=125)] + [pat(c, "def pattern(" if c not in ("AiterRMSNormGatedFp8GroupQuantPattern",) else "def pattern(") for *_, c in RQ_TABLE],
      request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}},
                                                "rdna": {"type": "boolean", "default": False, "description": "rocm_aiter_ops.is_rdna_aiter_enabled(): native quant matchers only"},
                                                "gdn_head_dims": {"type": "array", "items": {"type": "integer"}, "default": [], "description": "head_v_dim of the model's GatedDeltaNet layers"},
                                                "gdn_triton_kernels": {"type": "boolean", "default": True}}},
      response={"type": "object", "properties": {"replaced": {"type": "integer"}, "fused_ops": {"type": "array", "items": {"type": "string"}}}},
      behavior=[
          {"set": {"vars.m": f"= {TBL}.filter(t, t.on && t.p in input.graph_patterns)"},
           "title": "Registered patterns (eps 1e-5 and 1e-6) that occur in the graph", "source": src(RAF, "for epsilon in [1e-5, 1e-6]:", nth=1)},
          {"if": "size(vars.m) > 0", "title": "patterns.apply(graph) replaces every match", "source": src(RAF, "self.matched_count = self.patterns.apply(graph)", nth=1),
           "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + vars.m.map(t, t.op)"}}]},
          {"return": {"replaced": "= size(vars.m)", "fused_ops": "= vars.m.map(t, t.op)"}},
      ])
iface("rocm-aiter-silu-mul-fp8-group-quant-fusion-pass", "call", kind="function", latency_ms=0,
      summary="RocmAiterSiluMulFp8GroupQuantFusionPass: silu_and_mul + group FP8 quant -> vllm::rocm_aiter_act_mul_and_fp8_group_quant.",
      sources=[src(RAF, "class RocmAiterSiluMulFp8GroupQuantFusionPass(VllmFusionPatternMatcherPass):", span=17), pat("AiterSiluMulFp8GroupQuantPattern"),
               src("vllm/compilation/passes/vllm_inductor_pass.py", "class VllmPatternReplacement(ABC, Generic[P, R]):", span=40),
               src("vllm/compilation/passes/vllm_inductor_pass.py", "    def register(self, pr: VllmPatternReplacement) -> None:", span=9)],
      request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}}},
      response={"type": "object", "properties": {"replaced": {"type": "integer"}}},
      behavior=[{"if": "'silu_and_mul+group_fp8_quant' in input.graph_patterns", "title": "VllmFusionPatternMatcherPass.register(pattern, replacement); apply replaces the match",
                 "source": src(RAF, "AiterSiluMulFp8GroupQuantPattern(match_aiter_quant_op=match_aiter_quant_op)"),
                 "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + ['vllm::rocm_aiter_act_mul_and_fp8_group_quant']"}}, {"return": {"replaced": 1}}]},
                {"return": {"replaced": 0}}])
iface("rocm-aiter-triton-add-rms-norm-pad-fusion-pass", "call", kind="function", latency_ms=0,
      summary="RocmAiterTritonAddRMSNormPadFusionPass: AITER fused_add_rms_norm + pad of a 2880-wide hidden (gpt-oss) to a multiple of 128 or 256 -> vllm::rocm_aiter_triton_add_rmsnorm_pad.",
      sources=[src(RAF, "class RocmAiterTritonAddRMSNormPadFusionPass(VllmPatternMatcherPass):", span=29), pat("AddAiterRMSNormPadPattern")],
      request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}, "hidden_size": {"type": "integer", "default": 2880},
                                                "pad_to_multiple": {"type": "integer", "default": 256}}},
      response={"type": "object", "properties": {"replaced": {"type": "integer"}}},
      behavior=[{"if": "'fused_add_rms_norm+pad' in input.graph_patterns && (has(input.hidden_size) ? input.hidden_size : 2880) == 2880 && (has(input.pad_to_multiple) ? input.pad_to_multiple : 256) in [128, 256]",
                 "title": "Patterns exist only for hidden size 2880 padded to 128 (gfx942) or 256 (gfx950)", "source": src(RAF, "for x_pad_to_multiple in [128, 256]:"),
                 "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + ['vllm::rocm_aiter_triton_add_rmsnorm_pad']"}}, {"return": {"replaced": 1}}]},
                {"return": {"replaced": 0}}])
iface("mla-dual-rms-norm-fusion-pass", "call", kind="function", latency_ms=0,
      summary="MLADualRMSNormFusionPass: the paired q/kv-latent RMSNorms of MLA attention -> fused_mla_dual_rms_norm, or with the q-latent's FP8 per-token / group quant -> the _per_token_quant / _group_quant variants.",
      sources=[src(RAF, "class MLADualRMSNormFusionPass(VllmFusionPatternMatcherPass):", span=18), pat("MLADualRMSNormPattern"), pat("MLADualRMSPerTokenQuantPattern"), pat("MLADualRMSGroupQuantPattern")],
      request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}}},
      response={"type": "object", "properties": {"replaced": {"type": "integer"}, "fused_ops": {"type": "array", "items": {"type": "string"}}}},
      behavior=[{"set": {"vars.m": "= [{'p': 'mla_dual_rms_norm', 'op': 'vllm::fused_mla_dual_rms_norm'}, {'p': 'mla_dual_rms_norm+per_token_fp8_quant', 'op': 'vllm::fused_mla_dual_rms_norm_per_token_quant'}, {'p': 'mla_dual_rms_norm+group_fp8_quant', 'op': 'vllm::fused_mla_dual_rms_norm_group_quant'}].filter(t, t.p in input.graph_patterns)"},
                 "title": "Three patterns per epsilon", "source": src(RAF, "self.register(MLADualRMSNormPattern(epsilon))")},
                {"if": "size(vars.m) > 0", "title": "Replace each match", "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + vars.m.map(t, t.op)"}}]},
                {"return": {"replaced": "= size(vars.m)", "fused_ops": "= vars.m.map(t, t.op)"}}])
for c in ("rocm-aiter-rms-norm-quant-fusion-pass", "rocm-aiter-silu-mul-fp8-group-quant-fusion-pass", "rocm-aiter-triton-add-rms-norm-pad-fusion-pass", "mla-dual-rms-norm-fusion-pass"):
    COMPONENTS.append(comp(c, c.replace("-", " ").title().replace("Rocm Aiter", "ROCm AITER").replace("Mla", "MLA").replace("Rms", "RMS").replace("Fp8", "FP8"), "module",
                           "A post-grad ROCm AITER fusion pass (vllm/compilation/passes/fusion/rocm_aiter_fusion.py).", [src(RAF, "class " + {
                               "rocm-aiter-rms-norm-quant-fusion-pass": "RocmAiterRMSNormQuantFusionPass", "rocm-aiter-silu-mul-fp8-group-quant-fusion-pass": "RocmAiterSiluMulFp8GroupQuantFusionPass",
                               "rocm-aiter-triton-add-rms-norm-pad-fusion-pass": "RocmAiterTritonAddRMSNormPadFusionPass", "mla-dual-rms-norm-fusion-pass": "MLADualRMSNormFusionPass"}[c])],
                           parent="post-grad-pass-manager"))

ROCM_ON = {"aiter-ops@rank0": {"aiter_found": True, "gcn_arch": "gfx950", "flags": {**{attr: d for _, _, attr, d in FLAGS}, "_AITER_ENABLED": True}}}
SCENARIOS += [
    {"id": "kernels-ops-rocm-aiter-fusion-passes", "name": "MI355X (gfx950) with AITER on: the pass manager adds the AITER norm+quant, act+quant, pad and MLA dual-norm passes and they fuse",
     "description": "PostGradPassManager.configure adds the ROCm AITER passes when rocm_aiter_ops.is_enabled() (vllm/compilation/passes/pass_manager.py:160-202).",
     "fixtures": ["tp1-llama-8b"], "config": {"vllm-target-device": "rocm", "fuse-norm-quant": True, "fuse-act-quant": True, "fuse-act-padding": True, "fuse-mla-dual-rms-norm": True},
     "state": ROCM_ON,
     "steps": [{"interface": "post-grad-pass-manager.call", "caller": "gpu-worker", "as": "pm",
                "input": {"graph_patterns": ["rms_norm+2x_group_fp8_quant", "fused_add_rms_norm+per_token_fp8_quant", "silu_and_mul+group_fp8_quant", "fused_add_rms_norm+pad", "mla_dual_rms_norm+group_fp8_quant"]}}],
     "expect": ["steps.pm.result.ok",
                "ctx.fused == ['vllm::rocm_aiter_triton_add_rmsnorm_pad', 'vllm::rocm_aiter_rmsnorm_fp8_group_quant', 'vllm::rocm_aiter_rmsnorm_fused_add_dynamic_quant', 'vllm::rocm_aiter_act_mul_and_fp8_group_quant', 'vllm::fused_mla_dual_rms_norm_group_quant']"]},
    {"id": "kernels-ops-rocm-aiter-fusion-off-on-cuda", "name": "On the CUDA fixture with fuse_norm_quant on, only the CUDA RMSNorm+quant pass runs",
     "fixtures": ["tp1-llama-8b"], "config": {"fuse-norm-quant": True},
     "steps": [{"interface": "post-grad-pass-manager.call", "caller": "gpu-worker", "as": "pm", "input": {"graph_patterns": ["rms_norm+static_fp8_quant"]}}],
     "expect": ["steps.pm.result.ok", "!trace.exists(e, e.type == 'call.start' && e.interface == 'rocm-aiter-rms-norm-quant-fusion-pass.call')",
                "trace.exists(e, e.type == 'call.start' && e.interface == 'rms-norm-quant-fusion-pass.call')"]},
    {"id": "kernels-ops-rocm-aiter-rms-quant-rdna", "name": "RDNA4: per-token patterns are not registered; the gated-norm pattern needs a 128-wide GDN head",
     "fixtures": ["tp1-llama-8b"],
     "steps": [{"interface": "rocm-aiter-rms-norm-quant-fusion-pass.call", "caller": "gpu-worker", "as": "rdna",
                "input": {"graph_patterns": ["rms_norm+per_token_fp8_quant", "rms_norm+group_fp8_quant"], "rdna": True}},
               {"interface": "rocm-aiter-rms-norm-quant-fusion-pass.call", "caller": "gpu-worker", "as": "gdn64",
                "input": {"graph_patterns": ["rms_norm_gated+group_fp8_quant"], "gdn_head_dims": [64]}},
               {"interface": "rocm-aiter-rms-norm-quant-fusion-pass.call", "caller": "gpu-worker", "as": "gdn128",
                "input": {"graph_patterns": ["rms_norm_gated+group_fp8_quant"], "gdn_head_dims": [128]}},
               {"interface": "rocm-aiter-triton-add-rms-norm-pad-fusion-pass.call", "caller": "gpu-worker", "as": "pad4096",
                "input": {"graph_patterns": ["fused_add_rms_norm+pad"], "hidden_size": 4096}}],
     "expect": ["steps.rdna.result.value.fused_ops == ['vllm::rocm_aiter_rmsnorm_fp8_group_quant']", "steps.gdn64.result.value.replaced == 0",
                "steps.gdn128.result.value.fused_ops == ['vllm::fused_rms_gated_fp8_group_quant']", "steps.pad4096.result.value.replaced == 0"]},
]
