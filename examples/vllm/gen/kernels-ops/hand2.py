"""Hand-written interfaces with behaviors (compilation, CUDA graphs, IR dispatch,
multi-op wrappers and host-side dispatch of a few ops)."""
from common import findline, src
from hand import (ACT, AQF, ARF, BK, CG, CI, CLEAN, CLONE, CP, DC, FIXF, IR, LN, LOWER, MON, NOOP, OINK,
                  PM, PW, QKV, RQF, TACT, TU, VC, WR, XPU)
from ops import LATENCY

I = {}


def iface(comp, name, **kw):
    d = {"component": comp, "name": name}
    d.update(kw)
    I[f"{comp}.{name}"] = d
    return d


def count(field, by=1, source=None, title=None):
    """compilation_counter.<field> += by (the global CompilationCounter)."""
    d = {"call": "compilation-counter.increment", "input": {"field": field, "by": by}}
    if source:
        d["source"] = source
    d["title"] = title or f"compilation_counter.{field} += {by if isinstance(by, int) else 'n'}"
    return d


RUNNABLE = "= input.wrapper_mode == 'FULL' ? 'support-torch-compile.call' : 'piecewise-backend.call'"
RUNNABLE_T = ["support-torch-compile.call", "piecewise-backend.call"]

# ---------------------------------------------------------------- CUDA graphs
iface("cuda-graph-wrapper", "call", kind="function", latency_ms=0,
      summary="CUDAGraphWrapper.__call__: capture a CUDA graph for a new batch descriptor, replay it afterwards, or run eagerly.",
      sources=[src(CG, "def __call__(self, *args: Any, **kwargs: Any) -> Any | None:", span=127)],
      request="KernelsOpsGraphCall",
      response={"type": "object", "properties": {"path": {"type": "string"}, "key": {"type": "string"}}},
      errors=[{"code": "runtime-error", "status": 0, "retryable": False}, {"code": "assertion-error", "status": 0, "retryable": False}],
      behavior=[
          {"title": "No forward context: run the wrapped runnable without CUDA graphs", "source": src(CG, "if not is_forward_context_available():"),
           "if": "!input.forward_context",
           "then": [{"call": RUNNABLE, "targets": RUNNABLE_T, "input": "= input"},
                    {"return": {"path": "eager", "key": ""}}]},
          {"title": "Runtime mode NONE or not this wrapper's mode: run eagerly", "detail": "Profile and warmup runs, or the nested wrapper of the other mode.",
           "source": src(CG, "cudagraph_runtime_mode == CUDAGraphMode.NONE"),
           "if": "input.runtime_mode == 'NONE' || input.runtime_mode != input.wrapper_mode",
           "then": [{"call": RUNNABLE, "targets": RUNNABLE_T, "input": "= input"},
                    {"return": {"path": "eager", "key": ""}}]},
          {"set": {"vars.key": "= 'n' + string(input.num_tokens) + (input.uniform_decode ? '_uniform' : '_mixed')"},
           "title": "Look up the entry for this batch descriptor", "source": src(CG, "if batch_descriptor not in self.concrete_cudagraph_entries:")},
          {"if": "!(vars.key in state.entries)",
           "title": "First use of this batch descriptor: capture", "source": src(CG, "if entry.cudagraph is None:"),
           "then": [
               {"title": "Capture must be legal now", "source": src(CG, "validate_cudagraph_capturing_enabled()"),
                "call": "compilation-monitor.validate-cudagraph-capturing-enabled", "input": {}},
               {"title": "Run the runnable once under torch.cuda.graph in the global graph pool", "source": src(CG, "output = self.runnable(*args, **kwargs)"),
                "call": RUNNABLE, "targets": RUNNABLE_T, "input": "= input", "as": "run"},
               {"wait": "= config['cudagraph-capture-overhead-ms']"},
               {"title": "Keep only a weak reference to the output", "source": src(CG, "entry.output = weak_ref_tensors(output)"),
                "call": "torch-utils.weak-ref-tensor", "input": {"numel": "= input.num_tokens"}},
               {"set": {"= 'state.entries.' + vars.key": {"captured": True, "gpu_ms": "= vars.run.duration_ms", "input_addresses": "= input.input_addresses"},
                        "state.num_cudagraph_captured": "= state.num_cudagraph_captured + 1"},
                "title": "Store the entry; count the capture", "source": src(CG, "compilation_counter.num_cudagraph_captured += 1")},
               count("num_cudagraph_captured", source=src(CG, "compilation_counter.num_cudagraph_captured += 1")),
               {"return": {"path": "capture", "key": "= vars.key"}},
           ]},
          {"if": "input.debug && state.entries[vars.key].input_addresses != input.input_addresses",
           "title": "Debug logging: replay inputs must sit at the captured addresses", "source": src(CG, "assert new_input_addresses == entry.input_addresses"),
           "then": [{"fail": {"code": "assertion-error", "message": "= 'Input addresses for cudagraphs are different during replay. Expected [' + state.entries[vars.key].input_addresses.map(a, string(a)).join(', ') + '], got [' + input.input_addresses.map(a, string(a)).join(', ') + ']'"}}]},
          {"title": "Replay the captured graph", "detail": "Replays the recorded kernels without Python launch overhead; the GPU time recorded at capture.",
           "source": src(CG, "entry.cudagraph.replay()"), "wait": "= state.entries[vars.key].gpu_ms"},
          {"return": {"path": "replay", "key": "= vars.key"}},
      ])

iface("compilation-monitor", "validate-cudagraph-capturing-enabled", kind="function", latency_ms=0,
      summary="Raise if CUDA graph capture happens outside the capture phase.",
      sources=[src(MON, "def validate_cudagraph_capturing_enabled", span=9)],
      errors=[{"code": "runtime-error", "status": 0, "retryable": False}],
      behavior=[{"if": "!state.cudagraph_capturing_enabled", "source": src(MON, "if not cudagraph_capturing_enabled:"),
                 "title": "Capture is disabled",
                 "then": [{"fail": {"code": "runtime-error", "message": "CUDA graph capturing detected at an inappropriate time. This operation is currently disabled."}}]}])

iface("compilation-monitor", "set-cudagraph-capturing-enabled", kind="function", latency_ms=0,
      summary="Turn CUDA graph capture on or off (the model runner turns it off after capturing).",
      sources=[src(MON, "def set_cudagraph_capturing_enabled", span=2)],
      request={"type": "object", "properties": {"enabled": {"type": "boolean", "default": False}}},
      behavior=[{"set": {"state.cudagraph_capturing_enabled": "= input.enabled"}}])

iface("torch-utils", "weak-ref-tensor", kind="function", latency_ms=0,
      summary="weak_ref_tensor: alias a non-empty tensor's storage without keeping it alive.",
      sources=[src(TU, "def weak_ref_tensor(", span=9)],
      request={"type": "object", "properties": {"numel": {"type": "integer", "examples": [16]}}},
      response={"type": "object", "properties": {"weak": {"type": "boolean"}}},
      behavior=[
          {"if": "input.numel > 0", "title": "Non-empty tensor: torch.ops._C.weak_ref_tensor", "source": src(TU, "return torch.ops._C.weak_ref_tensor(tensor)"),
           "then": [{"call": "= config['vllm-target-device'] == 'cpu' ? 'cpu-torch-bindings.weak-ref-tensor' : 'torch-bindings.weak-ref-tensor'",
                     "targets": ["torch-bindings.weak-ref-tensor"], "input": {"device": 0}},
                    {"return": {"weak": True}}]},
          {"title": "0-size tensors allocate nothing and are returned as is", "source": src(TU, "return tensor", start=findline(TU, "def weak_ref_tensor(")),
           "return": {"weak": False}},
      ])

iface("torch-utils", "get-accelerator-view-from-cpu-tensor", kind="function", latency_ms=0,
      summary="get_accelerator_view_from_cpu_tensor: a device view of a pinned CPU tensor through UVA.",
      sources=[src(TU, "def get_accelerator_view_from_cpu_tensor", span=26)],
      request={"type": "object", "properties": {"numel": {"type": "integer", "examples": [16]}, "pinned": {"type": "boolean", "default": True}}},
      errors=[{"code": "value-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "config['vllm-target-device'] == 'xpu'", "title": "XPU: pin the tensor first if needed", "source": src(TU, "if current_platform.is_xpu():", start=findline(TU, "def get_accelerator_view_from_cpu_tensor")),
           "then": [
               {"if": "input.numel == 0", "source": src(TU, "if cpu_tensor.numel() == 0:"), "then": [{"return": {"device": "xpu", "copied": False}}]},
               {"call": "vllm-xpu-kernels.get-xpu-view-from-cpu-tensor", "input": {"device": 0}, "source": src(TU, "return torch.ops._C.get_xpu_view_from_cpu_tensor(cpu_tensor)"), "title": "torch.ops._C.get_xpu_view_from_cpu_tensor"},
               {"return": {"device": "xpu", "copied": "= !input.pinned"}}]},
          {"if": "config['vllm-target-device'] == 'cuda' || config['vllm-target-device'] == 'rocm'", "title": "CUDA-alike: torch.ops._C.get_cuda_view_from_cpu_tensor",
           "source": src(TU, "return torch.ops._C.get_cuda_view_from_cpu_tensor(cpu_tensor)"),
           "then": [{"call": "torch-bindings.get-cuda-view-from-cpu-tensor", "input": {"device": 0}}, {"return": {"device": "cuda", "copied": False}}]},
          {"title": "Other platforms are unsupported", "source": src(TU, "`get_accelerator_view_from_cpu_tensor` is currently"),
           "fail": {"code": "value-error", "message": "= '`get_accelerator_view_from_cpu_tensor` is currently not supported in: ' + config['vllm-target-device']"}},
      ])

# ---------------------------------------------------------------- piecewise backend
iface("piecewise-backend", "call", kind="function", latency_ms=0,
      summary="PiecewiseBackend.__call__: pick the compiled range entry for the runtime token count and run it.",
      sources=[src(PW, "def __call__(self, *args: Any) -> Any:", span=22), src(PW, "def _find_range_for_shape", span=14)],
      request="KernelsOpsGraphCall",
      response={"type": "object", "properties": {"range_start": {"type": "integer"}, "range_end": {"type": "integer"}}},
      errors=[{"code": "assertion-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "input.num_tokens in config['compile-sizes']", "title": "A compile size: the range entry compiled for exactly this size",
           "source": src(PW, "if runtime_shape in self.compile_sizes:"),
           "then": [{"return": {"range_start": "= input.num_tokens", "range_end": "= input.num_tokens"}}]},
          {"if": "input.num_tokens >= 1 && input.num_tokens <= config['max-num-batched-tokens']",
           "title": "Inside the general range [1, max_num_batched_tokens]", "source": src(PW, "if runtime_shape in range:"),
           "then": [{"return": {"range_start": 1, "range_end": "= config['max-num-batched-tokens']"}}]},
          {"title": "No compiled range covers this shape", "source": src(PW, 'f"Shape: {runtime_shape} out of considered ranges: "'),
           "fail": {"code": "assertion-error", "message": "= 'Shape: ' + string(input.num_tokens) + ' out of considered ranges: [(1, ' + string(config['max-num-batched-tokens']) + ')]'"}},
      ])

iface("piecewise-backend", "compile-all-ranges", kind="function", latency_ms=0,
      summary="PiecewiseBackend.compile_all_ranges: compile this piece for every compile range up front.",
      sources=[src(PW, "def compile_all_ranges(self) -> None:", span=27)],
      request={"type": "object", "properties": {"graph_index": {"type": "integer", "examples": [0]}, "num_graphs": {"type": "integer", "examples": [33]}, "graph_patterns": {"type": "array", "items": {"type": "string"}}}},
      behavior=[
          {"set": {"vars.ranges": "= [{'start': 1, 'end': config['max-num-batched-tokens']}] + config['compile-sizes'].map(s, {'start': s, 'end': s})"},
           "title": "Range entries: the compile ranges plus one single-size range per compile size", "source": src(PW, "for range in self.compile_ranges:")},
          {"foreach": "= vars.ranges", "as": "r", "source": src(PW, "for range_entry in self.range_entries.values():"), "title": "Compile each range entry",
           "steps": [{"call": "compiler-manager.compile",
                      "input": {"graph_index": "= input.graph_index", "num_graphs": "= input.num_graphs", "range_start": "= vars.r.start", "range_end": "= vars.r.end", "graph_patterns": "= input.graph_patterns"}}]},
      ])

# ---------------------------------------------------------------- compiler manager and cache
CM_REQ = {"type": "object", "properties": {"graph_index": {"type": "integer", "examples": [0]}, "num_graphs": {"type": "integer", "examples": [33]},
                                           "range_start": {"type": "integer", "examples": [1]}, "range_end": {"type": "integer", "examples": [8192]},
                                           "graph_patterns": {"type": "array", "items": {"type": "string"}}}}
CACHE_KEY = "= 'r' + string(input.range_start) + '_' + string(input.range_end) + '_g' + string(input.graph_index) + '_inductor_standalone'"

iface("compiler-manager", "initialize-cache", kind="function", latency_ms=0,
      summary="CompilerManager.initialize_cache: load vllm_compile_cache.py from the cache dir unless the cache is disabled.",
      sources=[src(BK, "    def initialize_cache(", span=50)],
      request={"type": "object", "properties": {"disable_cache": {"type": "boolean", "default": False}, "cache_dir": {"type": "string", "examples": ["rank_0_0/backbone"]}}},
      behavior=[
          {"set": {"state.disable_cache": "= input.disable_cache", "state.cache": {}}},
          {"if": "!input.disable_cache", "title": "Read vllm_compile_cache.py if it exists", "source": src(BK, "if not disable_cache and os.path.exists(self.cache_file_path):"),
           "then": [{"call": "torch-compile-cache.read-file", "input": {"path": "= input.cache_dir + '/vllm_compile_cache.py'"}, "as": "f", "on_error": "continue"},
                    {"if": "vars.f.ok", "title": "The file exists: parse it with ast.literal_eval", "source": src(BK, "cache = ast.literal_eval(f.read())"),
                     "then": [{"set": {"state.cache": "= vars.f.value.content"}}]}]},
      ])

iface("compiler-manager", "compile", kind="function", latency_ms=0,
      summary="CompilerManager.compile: load the graph from the cache or compile it with Inductor and record the handle.",
      sources=[src(BK, "    def compile(", span=130)],
      request=CM_REQ,
      response={"type": "object", "properties": {"source": {"type": "string"}}},
      behavior=[
          count("num_backend_compilations", source=src(BK, "compilation_counter.num_backend_compilations += 1")),
          {"set": {"vars.key": CACHE_KEY}},
          {"if": "vars.key in state.cache", "title": "Cache hit: load the compiled artifact by handle", "source": src(BK, "compiled_graph = self.load(graph, example_inputs, graph_index, compile_range)"),
           "then": [{"call": "inductor-standalone-adaptor.load", "input": {"handle": "= state.cache[vars.key].graph_handle"}},
                    {"return": {"source": "cache"}}]},
          {"title": "Miss: compile with Inductor (post-grad passes run inside)", "source": src(BK, "compiled_graph, handle = self.compiler.compile("),
           "call": "inductor-standalone-adaptor.compile", "input": {"key": "= 'artifact_compile_range_' + string(input.range_start) + '_' + string(input.range_end) + '_subgraph_' + string(input.graph_index)", "graph_patterns": "= input.graph_patterns", "save": "= !state.disable_cache"}, "as": "c"},
          {"if": "!state.disable_cache", "title": "Store the handle when the compile cache is enabled", "source": src(BK, "if is_compile_cache_enabled(additional_inductor_config) and handle is not None:"),
           "then": [{"set": {"state.cache": "= merge(state.cache, {vars.key: {'graph_handle': vars.c.value.handle}})", "state.is_cache_updated": True}},
                    count("num_cache_entries_updated", source=src(BK, "compilation_counter.num_cache_entries_updated += 1"))]},
          {"return": {"source": "compiled"}},
      ])

iface("compiler-manager", "save-to-file", kind="function", latency_ms=0,
      summary="CompilerManager.save_to_file: write the cache index unless disabled or unchanged.",
      sources=[src(BK, "    def save_to_file(self) -> None:", span=6)],
      request={"type": "object", "properties": {"cache_dir": {"type": "string", "examples": ["rank_0_0/backbone"]}}},
      behavior=[
          {"if": "state.disable_cache || !state.is_cache_updated", "source": src(BK, "if self.disable_cache or not self.is_cache_updated:"),
           "title": "Nothing to save", "then": [{"return": {"saved": False}}]},
          {"call": "torch-compile-cache.write-file", "input": {"path": "= input.cache_dir + '/vllm_compile_cache.py'", "content": "= state.cache"},
           "title": "Write vllm_compile_cache.py", "source": src(BK, "with open(self.cache_file_path, \"w\") as f:")},
          {"return": {"saved": True}},
      ])

iface("torch-compile-cache", "read-file", kind="io", latency_ms=1,
      summary="Read a file under the torch.compile cache dir (missing files read as null).",
      sources=[src(BK, "with open(self.cache_file_path) as f:")],
      request={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
      errors=[{"code": "not_found", "status": 404, "retryable": False}],
      store={"table": "files", "op": "get", "key": "= input.path"})
iface("torch-compile-cache", "write-file", kind="io", latency_ms=1,
      summary="Write a file under the torch.compile cache dir.",
      sources=[src(BK, "with open(self.cache_file_path, \"w\") as f:")],
      request={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "content": {"type": "object"}}},
      store={"table": "files", "op": "put", "key": "= input.path", "value": "= {'path': input.path, 'content': input.content}"})
iface("torch-compile-cache", "load-aot-artifact", kind="io", latency_ms=1,
      summary="Look up an AOT-compiled model artifact (VLLM_CACHE_ROOT/torch_compile_cache/torch_aot_compile/<hash>/rank_i_j/model).",
      sources=[src(DC, "loaded_fn = _try_load_aot_compiled_fn(self, aot_compilation_path)")],
      request={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
      errors=[{"code": "not_found", "status": 404, "retryable": False}],
      store={"table": "aot", "op": "get", "key": "= input.path"})
iface("torch-compile-cache", "save-aot-artifact", kind="io", latency_ms=1,
      summary="Persist the AOT-compiled model artifact.",
      sources=[src(DC, "def save_aot_compiled_function", span=12)],
      request={"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "num_graphs": {"type": "integer"}}},
      store={"table": "aot", "op": "put", "key": "= input.path", "value": "= {'path': input.path, 'num_graphs': input.num_graphs}"})

iface("inductor-standalone-adaptor", "compile", kind="function",
      latency_ms="= config['inductor-compile-ms-per-graph']",
      summary="InductorStandaloneAdaptor.compile: torch._inductor.standalone_compile of one subgraph; vLLM's post-grad passes run as Inductor's custom pass.",
      sources=[src(CI, "    def compile(", nth=2, span=40)],
      request={"type": "object", "properties": {"key": {"type": "string"}, "graph_patterns": {"type": "array", "items": {"type": "string"}},
                                                "save": {"type": "boolean", "default": True, "description": "is_compile_cache_enabled: save the artifact"}}},
      response={"type": "object", "properties": {"handle": {"type": "string"}}},
      behavior=[
          count("num_inductor_compiles", source=src(CI, "compilation_counter.num_inductor_compiles += 1")),
          {"title": "Inductor runs the post-grad custom pass", "source": src(PM, "    def __call__(self, graph: fx.Graph) -> None:"),
           "call": "post-grad-pass-manager.call", "input": {"graph_patterns": "= has(input.graph_patterns) ? input.graph_patterns : []"}},
          {"if": "input.save", "title": "Cache enabled: save the compiled artifact", "source": src(CI, "compiled_graph.save(path=path, format=self.save_format)"),
           "then": [count("num_compiled_artifacts_saved", source=src(CI, "compilation_counter.num_compiled_artifacts_saved += 1"))]},
          {"return": {"handle": "= input.key"}},
      ])
iface("inductor-standalone-adaptor", "load", kind="function", latency_ms="= config['inductor-load-ms-per-graph']",
      summary="InductorStandaloneAdaptor.load: deserialize a compiled artifact by handle.",
      sources=[src(CI, "    def load(", span=20)],
      request={"type": "object", "properties": {"handle": {"type": "string"}}},
      behavior=[count("num_compiled_artifacts_loaded", source=src(CI, "compilation_counter.num_compiled_artifacts_loaded += 1"))])

# ---------------------------------------------------------------- VllmBackend
iface("vllm-backend", "call", kind="function", latency_ms=0,
      summary="VllmBackend.__call__: cache dir from hashed factors, split the graph, compile all pieces, save the cache, build the runtime callable.",
      sources=[src(BK, "    def __call__(self, graph: fx.GraphModule, example_inputs: Sequence[Any]) -> Any:", span=60)],
      request="KernelsOpsCompileCall",
      response={"type": "object", "properties": {"num_piecewise_graphs": {"type": "integer"}, "copy_inputs": {"type": "boolean"}, "cache_dir": {"type": "string"}, "local_cache_dir": {"type": "string"}}},
      errors=[{"code": "assertion-error", "status": 0, "retryable": False}],
      behavior=[
          count("num_graphs_seen", source=src(BK, "compilation_counter.num_graphs_seen += 1"), title="Dynamo handed a graph to the backend"),
          {"title": "No configured cache_dir: hash the env, config, traced-code and compiler factors into the directory name",
           "detail": "sha256(str([env_hash, config_hash, code_hash, compiler_hash]))[:10]; the model joins the four factor strings instead of hashing them, so any factor change (e.g. ModelConfig.compute_hash with language_model_only) gives another directory.",
           "source": src(BK, "factors = [env_hash, config_hash, code_hash, compiler_hash]"),
           "set": {"vars.f": "= {'cache_dir': '', 'cache_root': '~/.cache/vllm', 'env_hash': 'env0', 'config_hash': 'cfg0', 'code_hash': 'code0', 'compiler_hash': 'inductor', 'rank': 0, 'dp_rank': 0}"}},
          {"set": {"vars.f": "= merge(vars.f, input.transformMap(k, v, v != null, v))"}, "title": "Arguments the caller gave override the defaults"},
          {"if": "!has(input.config_hash) || input.config_hash == null",
           "then": [
               {"title": "config_hash = vllm_config.compute_hash() (config-platform)", "source": src(BK, "config_hash = vllm_config.compute_hash()"),
                "call": "vllm-config.compute-hash", "input": {}, "as": "ch", "on_error": "continue"},
               {"if": "vars.ch.ok",
                "then": [{"set": {"vars.f": "= merge(vars.f, {'config_hash': vars.ch.value.hash})"}}],
                "else": [{"title": "No VllmConfig was resolved in this world (the engine config was never created): the default key",
                          "set": {"vars.f": "= merge(vars.f, {'config_hash': 'cfg0'})"}}]}]},
          {"set": {"vars.base": "= vars.f.cache_dir != '' ? vars.f.cache_dir : vars.f.cache_root + '/torch_compile_cache/' + vars.f.env_hash + '-' + vars.f.config_hash + '-' + vars.f.code_hash + '-' + vars.f.compiler_hash"}},
          {"title": "Per-rank local cache dir: <cache_dir>/rank_<rank>_<dp_rank>/<prefix>", "source": src(BK, 'local_cache_dir = os.path.join(cache_dir, f"rank_{rank}_{dp_rank}", self.prefix)'),
           "set": {"vars.cache_dir": "= vars.base + '/rank_' + string(vars.f.rank) + '_' + string(vars.f.dp_rank) + '/' + input.prefix"}},
          {"title": "Initialize the compiler manager's cache (disabled by VLLM_DISABLE_COMPILE_CACHE)", "source": src(BK, "self.compiler_manager.initialize_cache("),
           "call": "compiler-manager.initialize-cache", "input": {"disable_cache": "= config['vllm-disable-compile-cache']", "cache_dir": "= vars.cache_dir"}},
          {"if": "state.called", "title": "Each backend instance compiles once", "source": src(BK, 'assert not self._called, "VllmBackend can only be called once"'),
           "then": [{"fail": {"code": "assertion-error", "message": "VllmBackend can only be called once"}}]},
          {"title": "Split at the splitting ops (attention): one piece per layer boundary", "source": src(BK, "self.split_gm, self.piecewise_graphs = split_graph(graph, fx_split_ops)"),
           "set": {"vars.n": "= config['use-inductor-graph-partition'] ? 1 : input.num_layers + 1"}},
          count("num_piecewise_graphs_seen", by="= config['use-inductor-graph-partition'] ? 1 : 2 * input.num_layers + 1",
                source=src(BK, "compilation_counter.num_piecewise_graphs_seen += len(self.piecewise_graphs)"), title="Count every piece, splitting ops included"),
          count("num_piecewise_capturable_graphs_seen", by="= vars.n", source=src(BK, "compilation_counter.num_piecewise_capturable_graphs_seen += 1"),
                title="Count the compiled (CUDA-graph capturable) pieces"),
          {"title": "PiecewiseCompileInterpreter compiles every non-splitting piece", "source": src(BK, "PiecewiseCompileInterpreter(", nth=2),
           "foreach": "= [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199].slice(0, vars.n)", "as": "g", "max": 200,
           "steps": [{"call": "piecewise-backend.compile-all-ranges", "input": {"graph_index": "= vars.g", "num_graphs": "= vars.n", "graph_patterns": "= input.graph_patterns"}}]},
          {"title": "Save the compiler manager cache", "source": src(BK, "self.compiler_manager.save_to_file()"),
           "call": "compiler-manager.save-to-file", "input": {"cache_dir": "= vars.cache_dir"}},
          {"set": {"state.called": True}, "title": "Mark the backend used", "source": src(BK, "self._called = True")},
          {"if": "config['cudagraph-mode'] == 'NONE' || !config['cudagraph-copy-inputs']", "source": src(BK, "or not self.compilation_config.cudagraph_copy_inputs"),
           "title": "Return the runtime callable directly",
           "then": [{"return": {"num_piecewise_graphs": "= vars.n", "copy_inputs": False, "cache_dir": "= vars.base", "local_cache_dir": "= vars.cache_dir"}}]},
          {"title": "Wrap with copy_and_call so symbolic-shape inputs go to static buffers", "source": src(BK, "copy_and_call = make_copy_and_call("),
           "return": {"num_piecewise_graphs": "= vars.n", "copy_inputs": True, "cache_dir": "= vars.base", "local_cache_dir": "= vars.cache_dir"}},
      ])

# ---------------------------------------------------------------- torch.compile entry points
iface("torch-compile-with-no-guards-wrapper", "call", kind="function", latency_ms=0,
      summary="TorchCompileWithNoGuardsWrapper.__call__: first call compiles through Dynamo and the vLLM backend; later calls jump to the compiled bytecode.",
      sources=[src(WR, "    def __call__(self, *args: Any, **kwargs: Any) -> Any:", span=32)],
      request="KernelsOpsGraphCall",
      behavior=[
          {"if": "state.compiled_bytecode && config['vllm-use-bytecode-hook']", "title": "Bytecode hook: dispatch straight to the compiled code, no guards",
           "source": src(WR, "with self._dispatch_to_compiled_code():"),
           "then": [{"call": "piecewise-backend.call", "input": "= input"}, {"return": {"path": "compiled"}}]},
          {"if": "state.compiled_bytecode", "title": "No bytecode hook: the torch.compile frame reuses the compiled code (fail_on_recompile after the first compile)",
           "source": src(WR, 'else torch.compiler.set_stance("fail_on_recompile")'),
           "then": [{"set": {"ctx.guard_stance": "fail_on_recompile"}}, {"call": "piecewise-backend.call", "input": "= input"}, {"return": {"path": "compiled"}}]},
          {"title": "First call: Dynamo traces forward and hands the graph to VllmBackend", "source": src(WR, "torch._dynamo.eval_frame.remove_from_cache(self.original_code_object())"),
           "wait": "= config['dynamo-trace-ms']"},
          {"call": "vllm-backend.call", "input": {"num_layers": "= input.num_layers", "num_tokens": "= input.num_tokens", "prefix": "backbone", "graph_patterns": [], "config_hash": "= has(input.config_hash) ? input.config_hash : null"}},
          {"set": {"state.compiled_bytecode": True}, "title": "Record the compiled code (bytecode hook)", "source": src(WR, "def bytecode_hook(self, old_code: CodeType, new_code: CodeType) -> None:")},
          {"call": "piecewise-backend.call", "input": "= input"},
          {"return": {"path": "compiled-first"}},
      ])

iface("support-torch-compile", "call", kind="function", latency_ms=0,
      summary="The @support_torch_compile __call__: eager when compilation is off, else load an AOT artifact, run the compiled code, or compile on first call.",
      sources=[src(DC, "    def __call__(self: type[_T], *args: Any, **kwargs: Any) -> Any:", span=100)],
      request="KernelsOpsGraphCall",
      response={"type": "object", "properties": {"path": {"type": "string"}}},
      behavior=[
          {"if": "config['compilation-mode'] == 0 || config['compilation-mode'] == 1",
           "title": "do_not_compile (mode NONE or STOCK_TORCH_COMPILE): plain forward", "source": src(DC, "if self.do_not_compile or torch.compiler.is_compiling():"),
           "then": [{"set": {"ctx.forward": "eager"}, "title": "self.forward runs as plain PyTorch (models-layers' LlamaModel.forward, called by the model runner)",
                     "source": src(DC, "return self.forward(*args, **kwargs)")},
                    {"return": {"path": "eager"}}]},
          {"if": "state.aot_compiled_fn", "title": "AOT-compiled function already loaded: call it", "source": src(DC, 'if getattr(self, "aot_compiled_fn", None) is not None:'),
           "then": [{"call": "piecewise-backend.call", "input": "= input"}, {"return": {"path": "aot"}}]},
          {"set": {"vars.aot_path": "= 'torch_aot_compile/' + string(input.num_layers) + '/rank_0_0/model'"}},
          {"if": "config['vllm-use-aot-compile'] && !config['vllm-disable-compile-cache']", "title": "AOT mode: try the artifact on disk",
           "source": src(DC, "if not envs.VLLM_DISABLE_COMPILE_CACHE:"),
           "then": [{"call": "torch-compile-cache.load-aot-artifact", "input": {"path": "= vars.aot_path"}, "as": "aot", "on_error": "continue"},
                    {"if": "vars.aot.ok", "title": "Loaded from disk: no Dynamo, no Inductor", "source": src(DC, "self.was_aot_compile_fn_loaded_from_disk = True"),
                     "then": [{"set": {"state.aot_compiled_fn": True, "state.was_aot_compile_fn_loaded_from_disk": True}},
                              {"call": "piecewise-backend.call", "input": "= input"},
                              {"return": {"path": "aot-loaded"}}]}]},
          {"if": "state.compiled", "title": "Already compiled: guard-free dispatch", "source": src(DC, "return TorchCompileWithNoGuardsWrapper.__call__(self, *args, **kwargs)", nth=1),
           "then": [{"call": "torch-compile-with-no-guards-wrapper.call", "input": "= input"}, {"return": {"path": "compiled"}}]},
          {"title": "First call: mark dynamic dims and compile", "source": src(DC, "# This is the path for the first compilation."),
           "set": {"state.num_compiles": "= state.num_compiles + 1"}},
          {"if": "config['vllm-use-aot-compile']", "title": "AOT compile, save the artifact, run it", "source": src(DC, "self.aot_compiled_fn = self.aot_compile(*args, **kwargs)"),
           "then": [{"wait": "= config['dynamo-trace-ms']"},
                    {"call": "vllm-backend.call", "input": {"num_layers": "= input.num_layers", "num_tokens": "= input.num_tokens", "prefix": "backbone", "graph_patterns": [], "config_hash": "= has(input.config_hash) ? input.config_hash : null"}, "as": "be"},
                    {"call": "torch-compile-cache.save-aot-artifact", "input": {"path": "= vars.aot_path", "num_graphs": "= vars.be.value.num_piecewise_graphs"},
                     "title": "save_aot_compiled_function", "source": src(DC, "self.save_aot_compiled_function()")},
                    {"set": {"state.aot_compiled_fn": True, "state.compiled": True}},
                    {"call": "piecewise-backend.call", "input": "= input"},
                    {"return": {"path": "aot-compiled"}}]},
          {"title": "JIT: torch.compile through the guard-free wrapper", "source": src(DC, "output = TorchCompileWithNoGuardsWrapper.__call__("),
           "call": "torch-compile-with-no-guards-wrapper.call", "input": "= input"},
          {"set": {"state.compiled": True}, "source": src(DC, "self.compiled = True"), "title": "Mark compiled"},
          {"return": {"path": "jit-compiled"}},
      ])

# ---------------------------------------------------------------- post-grad passes
def pass_iface(comp, path, cls, summary, behavior):
    iface(comp, "call", kind="function", latency_ms=0, summary=summary,
          sources=[src(path, f"class {cls}")],
          request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}}},
          response={"type": "object", "properties": {"replaced": {"type": "integer"}}},
          behavior=behavior)


def fuse(pattern, fused, path, needle):
    return [
        {"if": f"'{pattern}' in input.graph_patterns", "title": f"Replace {pattern} with {fused}", "source": src(path, needle),
         "then": [{"set": {"ctx.fused": f"= (has(ctx.fused) ? ctx.fused : []) + ['{fused}']"}}, {"return": {"replaced": 1}}]},
        {"return": {"replaced": 0}},
    ]


pass_iface("noop-elimination-pass", NOOP, "NoOpEliminationPass", "Remove no-op views and slices.",
           [{"if": "'noop_reshape' in input.graph_patterns", "title": "Drop the no-op reshape", "source": src(NOOP, "class NoOpEliminationPass"),
             "then": [{"set": {"ctx.noops_removed": True}}]}, {"return": {"replaced": 0}}])
pass_iface("rms-norm-quant-fusion-pass", RQF, "RMSNormQuantFusionPass", "Fuse RMSNorm + static FP8 quant.",
           fuse("rms_norm+static_fp8_quant", "_C::rms_norm_static_fp8_quant", RQF, "class RMSNormQuantFusionPass"))
pass_iface("activation-quant-fusion-pass", AQF, "ActivationQuantFusionPass", "Fuse SiLU-and-mul + FP8 quant.",
           fuse("silu_and_mul+static_fp8_quant", "_C::silu_and_mul_quant", AQF, "class ActivationQuantFusionPass"))
pass_iface("all-reduce-fusion-pass", ARF, "AllReduceFusionPass", "Fuse all-reduce + RMSNorm.",
           fuse("all_reduce+rms_norm", "vllm::flashinfer_trtllm_fused_allreduce_norm", ARF, "class AllReduceFusionPass"))
RKVF = "vllm/compilation/passes/fusion/rope_kvcache_fusion.py"
iface("rope-kv-cache-fusion-pass", "call", kind="function", latency_ms=0,
      summary="RopeKVCacheFusionPass: per attention layer that supports fused rope+KV cache, register the static-Q FP8 pattern (when the static quant op exists) and the plain rope+reshape pattern; apply them and count matches.",
      sources=[src(RKVF, "class RopeKVCacheFusionPass", span=55)],
      request={"type": "object", "properties": {
          "graph_patterns": {"type": "array", "items": {"type": "string"}},
          "layer_supports_fused_rope_kvcache": {"type": "boolean", "default": True},
          "static_q_fp8_quant_supported": {"type": "boolean", "default": True}}},
      response={"type": "object", "properties": {"matched_count": {"type": "integer"}, "replaced_with": {"type": "string"}, "static_quant_remains": {"type": "boolean"}}},
      behavior=[
          {"if": "has(input.layer_supports_fused_rope_kvcache) && !input.layer_supports_fused_rope_kvcache", "title": "No attention layer supports the fused kernel: no pattern registered",
           "source": src(RKVF, "if layer.impl.fused_rope_kvcache_supported():"),
           "then": [{"return": {"matched_count": 0, "replaced_with": "", "static_quant_remains": "= 'rope+static_fp8_quant+kv_cache_update' in input.graph_patterns"}}]},
          {"if": "'rope+static_fp8_quant+kv_cache_update' in input.graph_patterns",
           "title": "rope -> static Q FP8 quant -> KV cache update", "source": src(RKVF, "if _supports_static_q_fp8_quant_fusion():"),
           "then": [
               {"if": "!has(input.static_q_fp8_quant_supported) || input.static_q_fp8_quant_supported",
                "title": "RopeStaticQQuantKVCachePattern matches; its replacement keeps the static quant", "source": src(RKVF, "class RopeStaticQQuantKVCachePattern:"),
                "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + ['vllm::fused_rope_and_unified_kv_cache_update']"}},
                         {"return": {"matched_count": 1, "replaced_with": "vllm::fused_rope_and_unified_kv_cache_update", "static_quant_remains": True}}]},
               {"title": "Without the static-Q pattern the generic rope+KV pattern cannot match through the quant",
                "source": src(RKVF, "class RopeReshapeKVCachePattern:"),
                "return": {"matched_count": 0, "replaced_with": "", "static_quant_remains": True}}]},
          {"if": "'rope+kv_cache_update' in input.graph_patterns", "title": "RopeReshapeKVCachePattern", "source": src(RKVF, "class RopeReshapeKVCachePattern:"),
           "then": [{"set": {"ctx.fused": "= (has(ctx.fused) ? ctx.fused : []) + ['vllm::fused_rope_and_unified_kv_cache_update']"}},
                    {"return": {"matched_count": 1, "replaced_with": "vllm::fused_rope_and_unified_kv_cache_update", "static_quant_remains": False}}]},
          {"return": {"matched_count": 0, "replaced_with": "", "static_quant_remains": False}},
      ])

for comp_, path_, cls_ in [("post-cleanup-pass", CLEAN, "PostCleanupPass"), ("vllm-ir-lowering-pass", LOWER, "VllmIRLoweringPass"),
                           ("unsafe-clone-elimination-pass", CLONE, "UnsafeCloneEliminationPass"), ("fix-functionalization-pass", FIXF, "FixFunctionalizationPass")]:
    iface(comp_, "call", kind="function", latency_ms=0, summary=f"{cls_}.__call__", sources=[src(path_, f"class {cls_}")],
          request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}}})

STEP = lambda comp_, needle: {"call": f"{comp_}.call", "input": {"graph_patterns": "= input.graph_patterns"}, "source": src(PM, needle)}
iface("post-grad-pass-manager", "call", kind="function", latency_ms=0,
      summary="PostGradPassManager.__call__: the configured passes, then cleanup, IR lowering, clone elimination, cleanup and fix functionalization.",
      sources=[src(PM, "    def __call__(self, graph: fx.Graph) -> None:", span=30), src(PM, "    def configure(self, config: VllmConfig) -> None:", span=85)],
      request={"type": "object", "properties": {"graph_patterns": {"type": "array", "items": {"type": "string"}}, "compile_range_end": {"type": "integer", "examples": [8192]}}},
      behavior=[
          dict(STEP("noop-elimination-pass", "self.passes += [NoOpEliminationPass(config)]"), **{"when": "config['eliminate-noops']", "title": "eliminate_noops"}),
          {"call": "aiter-ops.is-enabled", "input": {}, "as": "aiter", "title": "rocm_aiter_ops.is_enabled() decides the ROCm AITER passes (None off ROCm)",
           "source": src(PM, "rocm_aiter_ops.is_enabled() or rocm_aiter_ops.is_rdna_aiter_enabled()", nth=1)},
          {"set": {"vars.aiter_on": "= vars.aiter.value.enabled == true"}},
          dict(STEP("rocm-aiter-triton-add-rms-norm-pad-fusion-pass", "self.passes += [RocmAiterTritonAddRMSNormPadFusionPass(config)]"),
               **{"when": "config['fuse-act-padding'] && vars.aiter_on", "title": "fuse_act_padding with AITER: RMSNorm+pad before AR+RMS"}),
          dict(STEP("all-reduce-fusion-pass", "self.passes += [AllReduceFusionPass(config)]"), **{"when": "config['fuse-allreduce-rms']", "title": "fuse_allreduce_rms"}),
          dict(STEP("rocm-aiter-rms-norm-quant-fusion-pass", "RocmAiterRMSNormQuantFusionPass(config),"),
               **{"when": "config['fuse-norm-quant'] && vars.aiter_on", "title": "fuse_norm_quant with AITER: the AITER norm+quant pass first"}),
          dict(STEP("rms-norm-quant-fusion-pass", "self.passes += [RMSNormQuantFusionPass(config)]"), **{"when": "config['fuse-norm-quant']", "title": "fuse_norm_quant"}),
          dict(STEP("activation-quant-fusion-pass", "self.passes += [ActivationQuantFusionPass(config)]"), **{"when": "config['fuse-act-quant']", "title": "fuse_act_quant"}),
          dict(STEP("rocm-aiter-silu-mul-fp8-group-quant-fusion-pass", "self.passes += [RocmAiterSiluMulFp8GroupQuantFusionPass(config)]"),
               **{"when": "config['fuse-act-quant'] && vars.aiter_on", "title": "fuse_act_quant with AITER: SiLU-mul + group quant"}),
          dict(STEP("mla-dual-rms-norm-fusion-pass", "self.passes += [MLADualRMSNormFusionPass(config)]"),
               **{"when": "config['fuse-mla-dual-rms-norm'] && vars.aiter_on", "title": "fuse_mla_dual_rms_norm with AITER"}),
          dict(STEP("rope-kv-cache-fusion-pass", "self.passes += [RopeKVCacheFusionPass(config)]"),
               **{"when": "config['fuse-rope-kvcache'] && (!has(input.compile_range_end) || input.compile_range_end <= config['rope-kvcache-fusion-max-token-num'])",
                  "title": "fuse_rope_kvcache, only for compile ranges ending at or below rope_kvcache_fusion_max_token_num"}),
          dict(STEP("post-cleanup-pass", "self.post_cleanup(graph)"), **{"title": "post cleanup"}),
          dict(STEP("vllm-ir-lowering-pass", "self.ir_lowering(graph)"), **{"title": "lower vLLM IR ops"}),
          dict(STEP("unsafe-clone-elimination-pass", "self.clone_elimination(graph)"), **{"title": "clone elimination"}),
          dict(STEP("post-cleanup-pass", "self.post_cleanup(graph)", ), **{"title": "post cleanup again"}),
          dict(STEP("fix-functionalization-pass", "self.fix_functionalization(graph)"), **{"title": "fix functionalization (always last)"}),
      ])

# ---------------------------------------------------------------- vLLM IR dispatch
IMPL = ("{'vllm_c': {'rms_norm': 'vllm-c.rms-norm', 'fused_add_rms_norm': 'vllm-c.fused-add-rms-norm'},"
        " 'oink': {'rms_norm': 'oink-ops.rms-norm', 'fused_add_rms_norm': 'oink-ops.fused-add-rms-norm'},"
        " 'triton': {'gelu_and_mul_sparse': 'kernels-triton-activation.gelu-and-mul-sparse-triton'},"
        " 'native': {'rms_norm': 'ir-ops-layernorm.rms-norm', 'fused_add_rms_norm': 'ir-ops-layernorm.fused-add-rms-norm', 'gelu_and_mul_sparse': 'ir-ops-activation.gelu-and-mul-sparse'}}")
IMPL_T = ["vllm-c.rms-norm", "vllm-c.fused-add-rms-norm", "oink-ops.rms-norm", "oink-ops.fused-add-rms-norm",
          "kernels-triton-activation.gelu-and-mul-sparse-triton", "ir-ops-layernorm.rms-norm", "ir-ops-layernorm.fused-add-rms-norm",
          "ir-ops-activation.gelu-and-mul-sparse"]
SUPPORTS = ("(vars.p == 'vllm_c' && input.op != 'gelu_and_mul_sparse' && input.variance_size == 0 && input.weight_dtype_matches)"
            " || (vars.p == 'oink' && input.op != 'gelu_and_mul_sparse' && input.ndim == 2 && input.contiguous)"
            " || (vars.p == 'triton' && input.op == 'gelu_and_mul_sparse' && input.device_type == 'cuda' && input.contiguous && input.approximate == 'tanh' && input.hidden_size % 2 == 0 && input.hidden_size / 2 <= 32768)"
            " || vars.p == 'native'")
SUPPORTED = ("(vars.p == 'native') || (vars.p == 'vllm_c' && config['vllm-target-device'] in ['cuda', 'rocm', 'xpu'])"
             " || (vars.p == 'triton' && config['vllm-target-device'] == 'cuda') || (vars.p == 'oink' && config['vllm-target-device'] == 'cuda')")

iface("ir-op", "call", kind="function", latency_ms=0,
      summary="IrOp.__call__ -> dispatch: the first provider in the op's priority list that is supported and supports the args; native otherwise.",
      sources=[src(IR, "    def __call__(self, *args, **kwargs) -> Any:", span=5), src(IR, "    def dispatch(self, *args, **kwargs) -> \"IrOpImpl\":", span=37)],
      request="KernelsOpsIrCall",
      response={"type": "object", "properties": {"provider": {"type": "string"}}},
      errors=[{"code": "attribute-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "!(input.op in ['rms_norm', 'fused_add_rms_norm', 'gelu_and_mul_sparse'])", "title": "vllm.ir.ops has no such op",
           "source": src("vllm/ir/ops/__init__.py", "from"),
           "then": [{"fail": {"code": "attribute-error", "message": "= \"module 'vllm.ir.ops' has no attribute '\" + input.op + \"'\""}}]},
          {"set": {"vars.priority": "= has(input.priority_override) ? input.priority_override : (input.op in config['ir-op-priority'] ? config['ir-op-priority'][input.op] : [])"},
           "title": "The priority set at worker start (KernelConfig.set_default)", "source": src(IR, "    def set_default(self, priority: list[str]) -> None:")},
          {"if": "size(vars.priority) == 0", "title": "Priority not set: native implementation", "source": src(IR, "if not self._priority_impls:"),
           "then": [{"call": "= " + IMPL + "['native'][input.op]", "targets": IMPL_T, "input": "= input"},
                    {"set": {"ctx.ir_provider": "native"}}, {"return": {"provider": "native"}}]},
          {"foreach": "= vars.priority", "as": "p", "title": "Walk the priority list", "source": src(IR, "for impl in self._priority_impls:"),
           "steps": [
               {"if": "!(" + SUPPORTED + ")", "title": "Unsupported providers were filtered out when the priority was set", "source": src(IR, "if not impl.supported:", nth=2),
                "then": [{"continue": True}]},
               {"if": SUPPORTS, "title": "supports_args holds: use this provider", "source": src(IR, "if impl.supports_args(*args, **kwargs):"),
                "then": [{"call": "= " + IMPL + "[vars.p][input.op]", "targets": IMPL_T, "input": "= input"},
                         {"set": {"ctx.ir_provider": "= vars.p"}},
                         {"return": {"provider": "= vars.p"}}]},
           ]},
          {"title": "No listed provider supports every arg: native was appended by _filter_priority_impls", "source": src(IR, 'filtered_impls.append(self.impls["native"])'),
           "call": "= " + IMPL + "['native'][input.op]", "targets": IMPL_T, "input": "= input"},
          {"set": {"ctx.ir_provider": "native"}},
          {"return": {"provider": "native"}},
      ])

TOKEN_LAT = LATENCY["token"]
iface("ir-ops-layernorm", "rms-norm", kind="kernel", latency_ms=TOKEN_LAT, request="KernelsOpsIrCall",
      summary="Native rms_norm (PyTorch ops; under Inductor a generated Triton kernel).", sources=[src(LN, "def rms_norm(", span=12)])
iface("ir-ops-layernorm", "fused-add-rms-norm", kind="kernel", latency_ms=TOKEN_LAT, request="KernelsOpsIrCall",
      summary="Native fused_add_rms_norm.", sources=[src(LN, "def fused_add_rms_norm(", span=19)])
iface("ir-ops-activation", "gelu-and-mul-sparse", kind="kernel", latency_ms=TOKEN_LAT, request="KernelsOpsIrCall",
      summary="Native gelu_and_mul_sparse.", sources=[src(ACT, "def gelu_and_mul_sparse(", span=12)])
iface("oink-ops", "rms-norm", kind="kernel", latency_ms=TOKEN_LAT, request="KernelsOpsIrCall",
      summary="Oink rms_norm provider (external kernels).", sources=[src(OINK, "def rms_norm(", span=25)])
iface("oink-ops", "fused-add-rms-norm", kind="kernel", latency_ms=TOKEN_LAT, request="KernelsOpsIrCall",
      summary="Oink fused_add_rms_norm provider (external kernels).", sources=[src(OINK, "def fused_add_rms_norm(", span=11)])

iface("kernels-triton-activation", "gelu-and-mul-sparse-triton", kind="kernel", latency_ms=TOKEN_LAT, request="KernelsOpsIrCall",
      summary="triton_op vllm::gelu_and_mul_sparse_triton: one program per row launching _gelu_and_mul_sparse_kernel.",
      sources=[src(TACT, "def gelu_and_mul_sparse_triton(", span=4), src(TACT, '"vllm::gelu_and_mul_sparse_triton",', span=24), src(TACT, "def _gelu_and_mul_sparse_kernel(", span=36)],
      response={"type": "object", "properties": {"launched": {"type": "boolean"}, "d": {"type": "integer"}, "block_size": {"type": "integer"}, "num_warps": {"type": "integer"}}},
      errors=[{"code": "assertion-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "input.approximate != 'tanh'", "title": "The Triton impl only implements the tanh approximation", "source": src(TACT, 'assert approximate == "tanh"'),
           "then": [{"fail": {"code": "assertion-error", "message": ""}}]},
          {"set": {"vars.d": "= input.hidden_size / 2"}, "title": "d = x.shape[-1] // 2; output [..., d]", "source": src(TACT, "output = torch.empty((*x.shape[:-1], d), dtype=x.dtype, device=x.device)")},
          {"if": "input.num_tokens == 0", "title": "Empty output: nothing to launch", "source": src(TACT, "if output.numel() == 0:"),
           "then": [{"return": {"launched": False, "d": "= vars.d", "block_size": 0, "num_warps": 0}}]},
          {"set": {"vars.bs": "= [1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32768,65536,131072].filter(p, p >= vars.d).size() > 0 ? [1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32768,65536,131072].filter(p, p >= vars.d)[0] : vars.d"},
           "title": "BLOCK_SIZE = triton.next_power_of_2(d): one program covers a whole row (d <= 32768 by supports_args)",
           "source": src(TACT, "block_size = triton.next_power_of_2(d)")},
          {"set": {"vars.warps": "= vars.bs / 256 < 1 ? 1 : (vars.bs / 256 > 8 ? 8 : vars.bs / 256)"},
           "title": "num_warps = min(max(BLOCK_SIZE // 256, 1), 8)", "source": src(TACT, "num_warps = min(max(block_size // 256, 1), 8)")},
          {"title": "Launch _gelu_and_mul_sparse_kernel over n_rows programs", "source": src(TACT, "wrap_triton(_gelu_and_mul_sparse_kernel)[grid]("),
           "set": {"ctx.triton_kernel": "_gelu_and_mul_sparse_kernel"}},
          {"return": {"launched": True, "d": "= vars.d", "block_size": "= vars.bs", "num_warps": "= vars.warps"}},
      ])

iface("qkv-padded-fp8-quant", "quantize-fp8-pad-head-dim-triton", kind="kernel",
      latency_ms=LATENCY["token"], request="KernelsOpsTokenShape",
      summary="quantize_fp8_pad_head_dim_triton: FP8-quantize Q/K/V and pad head_dim to a multiple of 16 with _quantize_pad_fp8_kernel.",
      sources=[src(QKV, "def quantize_fp8_pad_head_dim_triton(", span=50), src(QKV, "def _quantize_pad_fp8_kernel(", span=54), src("vllm/utils/math_utils.py", "def round_up(x: int, y: int) -> int:", span=2)],
      errors=[{"code": "runtime-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "config['vllm-target-device'] == 'cpu'", "title": "Triton is required", "source": src(QKV, "if not HAS_TRITON:"),
           "then": [{"fail": {"code": "runtime-error", "message": "Triton is required to quantize with head_dim padding."}}]},
          {"title": "Launch _quantize_pad_fp8_kernel on a (rows/BLOCK_M, padded_D/BLOCK_N) grid", "source": src(QKV, "_quantize_pad_fp8_kernel[grid]("),
           "set": {"ctx.triton_kernel": "_quantize_pad_fp8_kernel"}},
          {"return": {"padded_head_dim": "= ((input.hidden_size + 15) / 16) * 16"}, "title": "padded_head_dim = round_up(D, 16)", "source": src(QKV, "padded_head_dim = round_up(D, 16)")},
      ])

iface("xpu-ops", "selective-scan-fwd", kind="kernel", latency_ms=LATENCY["token"], request="KernelsOpsTokenShape",
      summary="xpu_ops.selective_scan_fwd: Triton selective scan for Mamba on XPU (_selective_scan_fwd_kernel, softplus via _softplus).",
      sources=[src(XPU, "    def selective_scan_fwd(", span=8), src(XPU, "def _selective_scan_fwd_kernel(", span=10), src(XPU, "def _softplus(x):", span=2)],
      behavior=[
          {"if": "input.num_tokens == 0", "title": "No tokens: nothing to scan", "source": src(XPU, "    def selective_scan_fwd("),
           "then": [{"return": {"launched": False}}]},
          {"title": "Launch _selective_scan_fwd_kernel (delta_softplus applies _softplus inside)", "source": src(XPU, "_selective_scan_fwd_kernel[grid]("),
           "set": {"ctx.triton_kernel": "_selective_scan_fwd_kernel"}},
          {"return": {"launched": True}},
      ])

# vllm_c providers (inventory wrappers in vllm/kernels/vllm_c.py)
iface("vllm-c", "rms-norm", kind="function", latency_ms=0, request="KernelsOpsIrCall",
      summary="vllm_c provider of vllm.ir.ops.rms_norm: torch.ops._C.rms_norm into a fresh output.",
      sources=[src(VC, "def rms_norm(", span=22)],
      behavior=[
          {"if": "config['vllm-target-device'] == 'rocm' && (input.ndim > 2 || !input.contiguous)", "title": "ROCm: flatten to a contiguous 2D tensor first",
           "source": src(VC, "if IS_ROCM and (x.dim() > 2 or not x.is_contiguous()):"), "then": [{"set": {"ctx.rocm_reshaped": True}}]},
          {"title": "torch.ops._C.rms_norm", "source": src(VC, "torch.ops._C.rms_norm(output, x, weight, epsilon)", nth=2),
           "call": "= config['vllm-target-device'] == 'cpu' ? 'cpu-torch-bindings.rms-norm' : 'torch-bindings.rms-norm'",
           "targets": ["torch-bindings.rms-norm", "cpu-torch-bindings.rms-norm"], "input": "= input", "fill": True},
      ])
iface("vllm-c", "fused-add-rms-norm", kind="function", latency_ms=0, request="KernelsOpsIrCall",
      summary="vllm_c provider of vllm.ir.ops.fused_add_rms_norm (in place).",
      sources=[src(VC, "def fused_add_rms_norm(", span=27)],
      behavior=[
          {"if": "config['vllm-target-device'] == 'rocm' && !input.contiguous", "title": "ROCm, non-contiguous: fall back to the native impl and copy back",
           "source": src(VC, 'output, residual = ir.ops.fused_add_rms_norm.impls["native"].impl_fn('),
           "then": [{"call": "ir-ops-layernorm.fused-add-rms-norm", "input": "= input"}, {"return": {"fallback": "native"}}]},
          {"title": "torch.ops._C.fused_add_rms_norm", "source": src(VC, "torch.ops._C.fused_add_rms_norm(x, x_residual, weight, epsilon)", nth=2),
           "call": "= config['vllm-target-device'] == 'cpu' ? 'cpu-torch-bindings.fused-add-rms-norm' : 'torch-bindings.fused-add-rms-norm'",
           "targets": ["torch-bindings.fused-add-rms-norm", "cpu-torch-bindings.fused-add-rms-norm"], "input": "= input", "fill": True},
          {"return": {"fallback": "none"}},
      ])

# ---------------------------------------------------------------- multi-op and branching wrappers
FP8_START = findline(CP, "def scaled_fp8_quant(")
iface("custom-ops", "scaled-fp8-quant", kind="function", latency_ms=0, request="KernelsOpsFp8QuantCall",
      summary="scaled_fp8_quant: static per-tensor/group, dynamic per-tensor or dynamic per-token FP8 quantization.",
      sources=[src(CP, "def scaled_fp8_quant(", span=68)],
      response={"type": "object", "properties": {"rows": {"type": "integer"}, "cols": {"type": "integer"}, "scale_shape": {"type": "array", "items": {"type": "integer"}}, "kernel": {"type": "string"}}},
      errors=[{"code": "assertion-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "input.ndim != 2", "title": "Input must be 2D [M, N]", "source": src(CP, "assert input.ndim == 2", start=FP8_START),
           "then": [{"fail": {"code": "assertion-error", "message": "input.ndim == 2"}}]},
          {"if": "input.has_output && input.num_token_padding > 0", "title": "Padding is not supported with a caller-provided output",
           "source": src(CP, 'assert num_token_padding is None, "padding not supported if output passed in"', start=FP8_START),
           "then": [{"fail": {"code": "assertion-error", "message": "padding not supported if output passed in"}}]},
          {"set": {"vars.rows": "= input.num_token_padding > input.num_tokens ? input.num_token_padding : input.num_tokens"},
           "title": "Output rows: max(num_token_padding, M)", "source": src(CP, "shape = (max(num_token_padding, input.shape[0]), shape[1])", start=FP8_START)},
          {"if": "input.has_scale", "title": "Scale given: static quantization", "source": src(CP, "torch.ops._C.static_scaled_fp8_quant(output, input, scale, group_shape)", start=FP8_START),
           "then": [{"call": "torch-bindings.static-scaled-fp8-quant", "input": {"num_tokens": "= vars.rows", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
                    {"return": {"rows": "= vars.rows", "cols": "= input.hidden_size", "scale_shape": [1], "kernel": "static_scaled_fp8_quant"}}]},
          {"if": "input.use_per_token_if_dynamic", "title": "Dynamic per-token: one scale per row (bounded by scale_ub)",
           "source": src(CP, "torch.ops._C.dynamic_per_token_scaled_fp8_quant(", start=FP8_START),
           "then": [{"call": "torch-bindings.dynamic-per-token-scaled-fp8-quant", "input": {"num_tokens": "= vars.rows", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
                    {"set": {"ctx.scale_ub_applied": "= input.has_scale_ub"}},
                    {"return": {"rows": "= vars.rows", "cols": "= input.hidden_size", "scale_shape": ["= vars.rows", 1], "kernel": "dynamic_per_token_scaled_fp8_quant"}}]},
          {"title": "Dynamic per-tensor: one scale", "source": src(CP, "torch.ops._C.dynamic_scaled_fp8_quant(output, input, scale)", start=FP8_START),
           "call": "torch-bindings.dynamic-scaled-fp8-quant", "input": {"num_tokens": "= vars.rows", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
          {"return": {"rows": "= vars.rows", "cols": "= input.hidden_size", "scale_shape": [1], "kernel": "dynamic_scaled_fp8_quant"}},
      ])

I8_START = findline(CP, "def scaled_int8_quant(")
iface("custom-ops", "scaled-int8-quant", kind="function", latency_ms=0, request="KernelsOpsInt8QuantCall",
      summary="scaled_int8_quant: static per-tensor (with optional azp) or dynamic per-token INT8 quantization; XPU uses a reference path.",
      sources=[src(CP, "def scaled_int8_quant(", span=54)],
      errors=[{"code": "assertion-error", "status": 0, "retryable": False}, {"code": "not-implemented-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "config['vllm-target-device'] == 'xpu'", "title": "XPU has no _C int8 quant op", "source": src(CP, "if current_platform.is_xpu():", start=I8_START),
           "then": [{"if": "!input.symmetric", "source": src(CP, "raise NotImplementedError(", start=I8_START),
                     "then": [{"fail": {"code": "not-implemented-error", "message": "asymmetric int8 activation quantization is unsupported on XPU"}}]},
                    {"return": {"kernel": "torch-reference", "has_azp": False}}]},
          {"if": "input.has_scale", "title": "Static per-tensor quantization", "source": src(CP, "torch.ops._C.static_scaled_int8_quant(output, input, scale, azp)", start=I8_START),
           "then": [{"if": "input.symmetric == input.has_azp", "source": src(CP, '"azp must only be provided for asymmetric quantization."', start=I8_START),
                     "then": [{"fail": {"code": "assertion-error", "message": "azp must only be provided for asymmetric quantization."}}]},
                    {"call": "= config['vllm-target-device'] == 'cpu' ? 'cpu-torch-bindings.static-scaled-int8-quant' : 'torch-bindings.static-scaled-int8-quant'",
                     "targets": ["torch-bindings.static-scaled-int8-quant", "cpu-torch-bindings.static-scaled-int8-quant"],
                     "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
                    {"return": {"kernel": "static_scaled_int8_quant", "has_azp": "= input.has_azp"}}]},
          {"title": "Dynamic per-token quantization (azp when asymmetric)", "source": src(CP, "torch.ops._C.dynamic_scaled_int8_quant(", start=I8_START),
           "call": "= config['vllm-target-device'] == 'cpu' ? 'cpu-torch-bindings.dynamic-scaled-int8-quant' : 'torch-bindings.dynamic-scaled-int8-quant'",
           "targets": ["torch-bindings.dynamic-scaled-int8-quant", "cpu-torch-bindings.dynamic-scaled-int8-quant"],
           "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
          {"return": {"kernel": "dynamic_scaled_int8_quant", "has_azp": "= !input.symmetric"}},
      ])

ON_START = findline(CP, "def onednn_scaled_int8_quant(")
iface("custom-ops", "onednn-scaled-int8-quant", kind="function", latency_ms=0, request="KernelsOpsInt8QuantCall",
      summary="onednn_scaled_int8_quant (CPU oneDNN path): static or dynamic INT8 quantization.",
      sources=[src(CP, "def onednn_scaled_int8_quant(", span=35)],
      behavior=[
          {"if": "input.has_scale", "title": "Static quantization", "source": src(CP, "torch.ops._C.static_scaled_int8_quant(", start=ON_START),
           "then": [{"call": "cpu-torch-bindings.static-scaled-int8-quant", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
                    {"return": {"kernel": "static_scaled_int8_quant"}}]},
          {"title": "Dynamic quantization", "source": src(CP, "torch.ops._C.dynamic_scaled_int8_quant(", start=ON_START),
           "call": "cpu-torch-bindings.dynamic-scaled-int8-quant", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}},
          {"return": {"kernel": "dynamic_scaled_int8_quant"}},
      ])

MX_START = findline(CP, "def fusedQuantizeMx(")
iface("custom-ops", "fused-quantize-mx", kind="function", latency_ms=0,
      request={"type": "object", "properties": {"num_tokens": {"type": "integer", "examples": [16]}, "hidden_size": {"type": "integer", "examples": [4096]}, "dtype_bytes": {"type": "integer", "examples": [2]}, "method": {"type": "string", "examples": ["abs_max"]}}},
      summary="fusedQuantizeMx: QuTLASS MXFP4 quantization with the abs-max or quest method.",
      sources=[src(CP, "def fusedQuantizeMx(", span=35)],
      errors=[{"code": "value-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "input.method == 'abs_max'", "title": "abs_max", "source": src(CP, "torch.ops._qutlass_C.fusedQuantizeMxAbsMax", start=MX_START),
           "then": [{"call": "qutlass.fused-quantize-mx-abs-max", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}}, {"return": {"method": "abs_max"}}]},
          {"if": "input.method == 'quest'", "title": "quest", "source": src(CP, "torch.ops._qutlass_C.fusedQuantizeMxQuest", start=MX_START),
           "then": [{"call": "qutlass.fused-quantize-mx-quest", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= input.hidden_size", "dtype_bytes": "= input.dtype_bytes"}}, {"return": {"method": "quest"}}]},
          {"fail": {"code": "value-error", "message": "= \"invalid method '\" + input.method + \"', must be 'quest' or 'abs_max'\""}, "title": "Unknown method", "source": src(CP, "raise ValueError(f\"invalid method", start=MX_START)},
      ])

SMM_START = findline(CP, "def cutlass_scaled_mm(")
iface("custom-ops", "cutlass-scaled-mm", kind="function", latency_ms=0, request="KernelsOpsScaledMmCall",
      summary="cutlass_scaled_mm: CUTLASS scaled GEMM when B's dims are multiples of 16 on CUDA, Triton scaled_mm otherwise.",
      sources=[src(CP, "def cutlass_scaled_mm(", span=47)],
      errors=[{"code": "assertion-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "!(input.out_dtype in ['bfloat16', 'float16'])", "title": "Output dtype must be bf16 or fp16", "source": src(CP, "assert out_dtype is torch.bfloat16 or out_dtype is torch.float16", start=SMM_START),
           "then": [{"fail": {"code": "assertion-error", "message": "out_dtype must be bfloat16 or float16"}}]},
          {"if": "config['vllm-target-device'] == 'rocm' || input.k % 16 != 0 || input.n % 16 != 0", "title": "ROCm or B not 16-aligned: Triton scaled_mm",
           "source": src(CP, "if current_platform.is_rocm() or not cutlass_compatible_b:", start=SMM_START),
           "then": [{"set": {"ctx.scaled_mm_backend": "triton"}, "title": "triton_scaled_mm (compressed-tensors, models-layers) computes the GEMM",
                     "source": src(CP, "out = triton_scaled_mm(a, b, scale_a, scale_b, out_dtype, bias)", start=SMM_START)},
                    {"return": {"backend": "triton"}}]},
          {"title": "torch.ops._C.cutlass_scaled_mm", "source": src(CP, "torch.ops._C.cutlass_scaled_mm(out, a, b, scale_a, scale_b, bias)", start=SMM_START),
           "call": "torch-bindings.cutlass-scaled-mm", "input": {"m": "= input.m", "n": "= input.n", "k": "= input.k", "dtype_bytes": "= input.dtype_bytes"}},
          {"return": {"backend": "cutlass"}},
      ])
# convert_weight_packed_scale_zp: the CPU op computes the blocked layout (oracle 3)
iface("custom-ops", "convert-weight-packed-scale-zp", kind="function", latency_ms=0, request="KernelsOpsAwqPackCall",
      summary="convert_weight_packed_scale_zp: torch.ops._C.convert_weight_packed_scale_zp (CPU int4 W4A8 weight packing).",
      sources=[src(CP, "def convert_weight_packed_scale_zp(", span=11)],
      behavior=[{"title": "Call torch.ops._C.convert_weight_packed_scale_zp", "source": src(CP, "return torch.ops._C.convert_weight_packed_scale_zp("),
                 "call": "cpu-torch-bindings.convert-weight-packed-scale-zp", "input": "= input", "as": "r"},
                {"return": "= vars.r.value"}])

GQ = "csrc/quantization/gptq/q_gemm.cu"
CPUACT = "csrc/cpu/activation.cpp"


def cpu_gate(fn):
    return {"response": {"type": "object", "properties": {"num_tokens": {"type": "integer"}, "d": {"type": "integer"}, "act": {"type": "string"}}},
            "request": {"type": "object", "properties": {"num_tokens": {"type": "integer", "examples": [16]}, "hidden_size": {"type": "integer", "examples": [8192]},
                                                         "dtype_bytes": {"type": "integer", "examples": [2]},
                                                         "scalar_type": {"type": "string", "default": "Float8_e4m3fn", "description": "the 1-byte input's ScalarType name, as AT_DISPATCH prints it"}}},
            "errors": [{"code": "not-implemented-error", "status": 0, "retryable": False}],
            "behavior": [
                {"if": "input.dtype_bytes == 1", "title": "VLLM_DISPATCH_FLOATING_TYPES: only float, bfloat16 and half",
                 "source": src(CPUACT, f'VLLM_DISPATCH_FLOATING_TYPES(input.scalar_type(), "{fn}_impl"' if fn != "gelu_tanh_and_mul" else 'input.scalar_type(), "gelu_tanh_and_mul_impl", [&] {'),
                 "then": [{"fail": {"code": "not-implemented-error", "message": f"= '\"{fn}_impl\" not implemented for \\'' + (has(input.scalar_type) ? input.scalar_type : 'Float8_e4m3fn') + '\\''"}}]},
                {"title": "num_tokens = numel / size(-1); d = size(-1) / 2; one activation_kernel pass", "source": src(CPUACT, f"void {fn}(torch::Tensor& out"),
                 "return": {"num_tokens": "= input.num_tokens", "d": "= input.hidden_size / 2", "act": fn}},
            ]}

CPU_I4 = "csrc/cpu/sgl-kernels/gemm_int4.cpp"
OP_BEHAVIORS = {
    "cpu-torch-bindings.silu-and-mul": cpu_gate("silu_and_mul"),
    "cpu-torch-bindings.gelu-and-mul": cpu_gate("gelu_and_mul"),
    "cpu-torch-bindings.gelu-tanh-and-mul": cpu_gate("gelu_tanh_and_mul"),
    "cpu-torch-bindings.convert-weight-packed-scale-zp": {
        "request": "KernelsOpsAwqPackCall",
        "response": {"type": "object", "properties": {"blocked_w_dims": {"type": "integer"}, "blocked_s_dim0": {"type": "integer"}, "blocked_zp_dim0": {"type": "integer"}}},
        "latency_ms": "= (double(config['kernel-launch-overhead-us']) + 2.0 * double(input.n) * double(input.k) / 2.0 / (double(config['gpu-hbm-bandwidth-gbps']) * 1000.0)) / 1000.0",
        "behavior": [
            {"set": {"vars.block_n": 32}, "title": "block_size_n() = 2 * TILE_N = 32", "source": src("csrc/cpu/sgl-kernels/gemm.h", "constexpr int block_size_n() {", span=2)},
            {"if": "input.num_experts > 0", "title": "3D MoE weight: [E, Nc, Kc, bytes] blocks per expert", "source": src(CPU_I4, "if (_qweight.dim() == 3) {"),
             "then": [{"return": {"blocked_w_dims": 4, "blocked_s_dim0": "= input.num_experts", "blocked_zp_dim0": "= input.num_experts"}}]},
            {"title": "2D weight: blocked per Nc = N / block_n column blocks", "source": src(CPU_I4, "auto res_ = convert_int4_weight_packed_with_compensation(_qweight, _scales, _qzeros);"),
             "return": {"blocked_w_dims": 3, "blocked_s_dim0": "= input.n / vars.block_n", "blocked_zp_dim0": "= input.n / vars.block_n"}},
        ]},
    "torch-bindings.gptq-shuffle": {
        "request": "KernelsOpsGptqShuffleCall",
        "behavior": [
            {"set": {"vars.kernel": "= input.bit == 2 ? 'shuffle_2bit_kernel' : (input.bit == 3 ? 'shuffle_3bit_kernel' : (input.bit == 8 ? 'shuffle_8bit_kernel' : 'shuffle_4bit_kernel'))"},
             "title": "Pick the shuffle kernel by bit width (anything else uses the 4-bit kernel)", "source": src(GQ, "auto shuffle_kernel = shuffle_4bit_kernel;", span=7)},
            {"if": "input.rows * 32 / input.bit < 1", "title": "Height = rows * 32 / bit", "source": src(GQ, "q_weight.size(0) * 32 / bit,"),
             "then": [{"return": {"kernel": "= vars.kernel", "height": 0}}]},
            {"set": {"ctx.gptq_shuffle_kernel": "= vars.kernel"}, "title": "Launch with grid (cols / THREADS_X)", "source": src(GQ, "shuffle_kernel<<<gridDim, blockDim, 0, stream>>>(q_weight, height, width);")},
            {"return": {"kernel": "= vars.kernel", "height": "= input.rows * 32 / input.bit"}},
        ]},
}

AR_START = findline(CP, "def all_reduce(")
iface("custom-ops", "all-reduce", kind="function", latency_ms=0, request="KernelsOpsCollectiveShape",
      summary="all_reduce: torch.ops._C_custom_ar.all_reduce, whose body is distributed's CustomAllreduce::allreduce.",
      sources=[src(CP, "def all_reduce(", span=7)],
      behavior=[{"title": "Call torch.ops._C_custom_ar.all_reduce (registered in csrc/torch_bindings.cpp; body in csrc/custom_all_reduce.cu)",
                 "source": src(CP, "torch.ops._C_custom_ar.all_reduce(fa, inp, out, reg_buffer, reg_buffer_sz_bytes)", start=AR_START),
                 "call": "custom-allreduce-cuda.all-reduce", "input": {"bytes": "= input.num_bytes", "world_size": "= input.world_size"}}])
iface("custom-allreduce-cuda", "all-reduce", kind="function",
      summary="Boundary (distributed): the _C_custom_ar all_reduce op body and CustomAllreduce::allreduce.",
      sources=["csrc/custom_all_reduce.cu:70-116"],
      attributes={"boundary": True, "owner": "distributed"},
      request={"type": "object", "required": ["bytes", "world_size"], "properties": {
          "bytes": {"type": "integer", "examples": [1048576]}, "world_size": {"type": "integer", "examples": [4]},
          "num_collectives": {"type": "integer", "default": 1}, "registered": {"type": "boolean", "default": False},
          "dtype": {"type": "string", "default": "bfloat16"}}},
      response={"type": "object", "properties": {"algorithm": {"type": "string"}}},
      errors=[{"code": "runtime-error", "status": 0, "retryable": False}])

# XPU host registration ops (torch.ops._C on the XPU build, provided by vllm-xpu-kernels), called by scheduler-kv's KV offload
HR = "vllm/v1/kv_offload/cpu/host_register.py"
iface("vllm-xpu-kernels", "xpu-host-register", kind="kernel",
      summary="torch.ops._C.xpu_host_register(ptr, num_bytes) -> bool: pin a host range for DMA on XPU (vllm-xpu-kernels; no code in this repo).",
      description="Only reached when current_platform.is_xpu(); a false result makes host_register log a warning and fall back to pageable memory. Latency: ASSUMPTION, page-locking cost proportional to the range.",
      sources=[src(HR, "if not torch.ops._C.xpu_host_register(ptr, num_bytes):")],
      attributes={"op": "_C::xpu_host_register", "external": True, "platform": "xpu"},
      request={"type": "object", "required": ["ptr", "num_bytes"], "properties": {"ptr": {"type": "integer", "examples": [140000000000]}, "num_bytes": {"type": "integer", "examples": [68719476736]}}},
      response={"type": "object", "properties": {"ok": {"type": "boolean", "default": True}}},
      latency_ms="= (double(config['kernel-launch-overhead-us']) + double(input.num_bytes) / 1073741824.0 * double(config['xpu-host-register-us-per-gib'])) / 1000.0")
iface("vllm-xpu-kernels", "xpu-host-unregister", kind="kernel",
      summary="torch.ops._C.xpu_host_unregister(ptr) -> bool: release a range pinned by xpu_host_register (vllm-xpu-kernels).",
      description="A false result only logs a warning in host_unregister.",
      sources=[src(HR, "if not torch.ops._C.xpu_host_unregister(ptr):")],
      attributes={"op": "_C::xpu_host_unregister", "external": True, "platform": "xpu"},
      request={"type": "object", "required": ["ptr"], "properties": {"ptr": {"type": "integer", "examples": [140000000000]}}},
      response={"type": "object", "properties": {"ok": {"type": "boolean", "default": True}}},
      latency_ms="= double(config['kernel-launch-overhead-us']) / 1000.0")

# ---------------------------------------------------------------- Helion kernels (vllm/kernels/helion)
HREG = "vllm/kernels/helion/register.py"
HCM = "vllm/kernels/helion/config_manager.py"
HUT = "vllm/kernels/helion/utils.py"
HCK = "vllm/kernels/helion/case_key.py"
HSM = "vllm/kernels/helion/ops/silu_mul_fp8.py"
IU = "vllm/utils/import_utils.py"

iface("import-utils", "has-helion", kind="function", latency_ms=0,
      summary="has_helion: whether the optional helion package imports (find_spec, then a trial import).",
      sources=[src(IU, "def has_helion() -> bool:", span=13), src(IU, "def _has_module(module_name: str) -> bool:", span=19)],
      request={"type": "object", "properties": {"installed": {"type": "boolean", "default": True}}},
      response={"type": "object", "properties": {"available": {"type": "boolean"}}},
      behavior=[{"if": "!input.installed", "title": "find_spec('helion') is None, or the trial import failed", "source": src(IU, "if importlib.util.find_spec(module_name) is None:"),
                 "then": [{"return": {"available": False}}]},
                {"return": {"available": True}}])

iface("helion-utils", "get-canonical-gpu-name", kind="function", latency_ms=0,
      summary="get_canonical_gpu_name: lower-case the device name, join separators with '_', map known variants (H100 80GB HBM3 -> nvidia_h100).",
      sources=[src(HUT, "def canonicalize_gpu_name(name: str) -> str:", span=16), src(HUT, "_GPU_NAME_ALIASES: dict[str, str] = {", span=14)],
      request={"type": "object", "properties": {"device_name": {"type": "string", "examples": ["NVIDIA H100 80GB HBM3"]}}},
      response={"type": "object", "properties": {"platform": {"type": "string"}}},
      errors=[{"code": "value-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "input.device_name.trim() == ''", "title": "Empty GPU name", "source": src(HUT, "if not name or not name.strip():"),
           "then": [{"fail": {"code": "value-error", "message": "GPU name cannot be empty"}}]},
          {"set": {"vars.name": "= replace(input.device_name.lowerAscii(), '[\\\\s/-]+', '_')"}, "title": "Lower-case; whitespace, '/' and '-' become '_'",
           "source": src(HUT, 'name = re.sub(r"[\\s/-]+", "_", name.lower())')},
          {"set": {"vars.aliases": {"nvidia_h100_pcie": "nvidia_h100", "nvidia_h100_sxm5": "nvidia_h100", "nvidia_h100_80gb_hbm3": "nvidia_h100", "nvidia_h100_nvl": "nvidia_h100",
                                    "nvidia_h200_nvl": "nvidia_h200", "nvidia_h200_141gb_hbm3e": "nvidia_h200",
                                    "nvidia_a100_sxm4_80gb": "nvidia_a100", "nvidia_a100_sxm4_40gb": "nvidia_a100", "nvidia_a100_pcie_80gb": "nvidia_a100"}}},
          {"return": {"platform": "= vars.name in vars.aliases ? vars.aliases[vars.name] : vars.name"},
           "title": "Known variants map to the canonical platform", "source": src(HUT, "if name in _GPU_NAME_ALIASES:")},
      ])

iface("helion-config-manager", "get-platform-configs", kind="io", latency_ms=0.05,
      summary="ConfigManager.get_platform_configs: load configs/<kernel>/<platform>.json; a missing file yields no configs.",
      sources=[src(HCM, "    def get_platform_configs(", span=11), src(HCM, "    def _load_platform_file(self, kernel_name: str, platform: str) -> Any:", span=10)],
      request={"type": "object", "required": ["key"], "properties": {"key": {"type": "string", "examples": ["silu_mul_fp8/nvidia_h100"]}}},
      errors=[{"code": "not_found", "status": 404, "retryable": False}],
      store={"table": "configs", "op": "get", "key": "= input.key"})

PICK = ("vars.isz = vars.cfg.keys.map(k, k.intermediate); "
        "vars.best_isize = vars.isz.filter(s, vars.isz.all(t, math.abs(s - input.intermediate_size) <= math.abs(t - input.intermediate_size)))[0]")
iface("helion-kernel-wrapper", "register-kernel", kind="function", latency_ms=0,
      summary="@register_kernel -> HelionKernelWrapper.__init__: load this platform's pre-tuned configs; a ValueError (no configs) disables the kernel instead of failing.",
      sources=[src(HREG, "def register_kernel(", span=10), src(HREG, "class HelionKernelWrapper:", span=43), src(HREG, "    def _load_platform_configs(self) -> None:", span=12)],
      request={"type": "object", "properties": {"op_name": {"type": "string", "examples": ["silu_mul_fp8"]}, "device_name": {"type": "string", "examples": ["NVIDIA H100 80GB HBM3"]},
                                                "helion_installed": {"type": "boolean", "default": True}}},
      response={"type": "object", "properties": {"disabled": {"type": "boolean"}, "platform": {"type": "string"}}},
      errors=[{"code": "import-error", "status": 0, "retryable": False}, {"code": "value-error", "status": 0, "retryable": False}],
      behavior=[
          {"call": "import-utils.has-helion", "input": {"installed": "= input.helion_installed"}, "as": "h",
           "title": "register.py refuses to import without helion", "source": src(HREG, "if not has_helion():")},
          {"if": "!vars.h.value.available", "then": [{"fail": {"code": "import-error", "message": "register module requires helion to be installed. Install it with: pip install helion"}}]},
          {"if": "input.op_name in state.registered", "title": "One registration per op name", "source": src(HREG, "if final_op_name in _REGISTERED_KERNELS:"),
           "then": [{"fail": {"code": "value-error", "message": "= \"Helion kernel '\" + input.op_name + \"' is already registered. Use a different op_name or check for duplicate registrations.\""}}]},
          {"call": "helion-utils.get-canonical-gpu-name", "input": {"device_name": "= input.device_name"}, "as": "p",
           "title": "Platform = canonical GPU name", "source": src(HREG, "self.platform = get_canonical_gpu_name()")},
          {"call": "helion-config-manager.get-platform-configs", "input": {"key": "= input.op_name + '/' + vars.p.value.platform"}, "as": "c", "on_error": "continue"},
          {"if": "!vars.c.ok", "title": "No configs for this platform: ValueError, caught, kernel disabled with the reason", "source": src(HREG, "self._disabled_reason = str(e)"),
           "then": [{"set": {"= 'state.registered.' + input.op_name": {"disabled": True, "platform": "= vars.p.value.platform",
                                                                          "reason": "= \"No configs available for kernel '\" + input.op_name + \"' on platform '\" + vars.p.value.platform + \"'\""}}},
                    {"return": {"disabled": True, "platform": "= vars.p.value.platform"}}]},
          {"set": {"= 'state.registered.' + input.op_name": {"disabled": False, "platform": "= vars.p.value.platform", "configs": "= input.op_name + '/' + vars.p.value.platform"}},
           "title": "Registered in _REGISTERED_KERNELS", "source": src(HREG, "_REGISTERED_KERNELS[final_op_name] = kernel_wrapper")},
          {"return": {"disabled": False, "platform": "= vars.p.value.platform"}},
      ])

iface("helion-kernel-wrapper", "call", kind="function", latency_ms=0,
      summary="HelionKernelWrapper.__call__: refuse when disabled; else the config selector picks the pre-tuned CaseKey and the configured kernel runs.",
      sources=[src(HREG, "    def __call__(self, *args, **kwargs):", nth=2, span=17), src(HREG, "    def _create_config_selector(self, key_computer):", span=22)],
      request={"type": "object", "properties": {"op_name": {"type": "string", "examples": ["silu_mul_fp8"]}, "num_tokens": {"type": "integer", "examples": [16]},
                                                "intermediate_size": {"type": "integer", "examples": [14336]}}},
      response={"type": "object", "properties": {"case_key": {"type": ["string", "null"]}, "intermediate": {"type": "integer"}, "numtokens": {"type": "integer"}}},
      errors=[{"code": "runtime-error", "status": 0, "retryable": False}],
      behavior=[
          {"if": "!(input.op_name in state.registered)", "title": "Not a registered Helion kernel",
           "source": src(HREG, "def get_kernel_by_name(kernel_name: str) -> HelionKernelWrapper | None:"),
           "then": [{"return": {"case_key": None}, "title": "get_kernel_by_name returns None for a name never registered (no exception)"}]},
          {"if": "state.registered[input.op_name].disabled", "title": "Disabled kernels raise", "source": src(HREG, "if self._disabled:"),
           "then": [{"fail": {"code": "runtime-error", "message": "= \"Helion kernel '\" + input.op_name + \"' is disabled: \" + state.registered[input.op_name].reason"}}]},
          {"call": "helion-config-manager.get-platform-configs", "input": {"key": "= state.registered[input.op_name].configs"}, "as": "cf"},
          {"set": {"vars.cfg": "= vars.cf.value"}},
          {"set": {"vars.isz": "= vars.cfg.keys.map(k, k.intermediate)"},
           "title": "pick_silu_mul_fp8_config: closest intermediate size", "source": src(HSM, "best_isize = min(by_isize, key=lambda s: abs(s - intermediate_size))")},
          {"set": {"vars.best_isize": "= vars.isz.filter(s, vars.isz.all(t, math.abs(s - input.intermediate_size) <= math.abs(t - input.intermediate_size)))[0]"}},
          {"set": {"vars.avail": "= vars.cfg.keys.filter(k, k.intermediate == vars.best_isize).map(k, k.numtokens)"}},
          {"set": {"vars.ge": "= vars.avail.filter(n, n >= input.num_tokens)"},
           "title": "then the smallest tuned num_tokens >= the batch, else the largest", "source": src(HSM, "best_ntokens = next((n for n in available if n >= num_tokens), available[-1])")},
          {"set": {"vars.ntok": "= size(vars.ge) > 0 ? vars.ge.filter(n, vars.ge.all(m, n <= m))[0] : vars.avail.filter(n, vars.avail.all(m, n >= m))[0]"}},
          {"set": {"vars.key": "= '{\"intermediate\":' + string(vars.best_isize) + ',\"numtokens\":' + string(vars.ntok) + '}'"},
           "title": "CaseKey string: sorted-key compact JSON", "source": src(HCK, "self._str = json.dumps(dict(self), sort_keys=True, separators=(\",\", \":\"))")},
          {"call": "silu-mul-fp8.silu-mul-fp8", "input": {"num_tokens": "= input.num_tokens", "hidden_size": "= 2 * input.intermediate_size", "dtype_bytes": 2},
           "title": "The configured kernel runs with the selected config", "source": src(HREG, "return self._configured_kernel(*args, **kwargs)")},
          {"return": {"case_key": "= vars.key", "intermediate": "= vars.best_isize", "numtokens": "= vars.ntok"}},
      ])

iface("silu-mul-fp8", "silu-mul-fp8", kind="kernel", latency_ms=LATENCY["token"], request="KernelsOpsTokenShape",
      summary="Helion kernel silu_mul_fp8: SiLU(gate) * up quantized to FP8 (memory-bound over [T, 2I]).",
      sources=[src(HSM, "def silu_mul_fp8(input: torch.Tensor, scale: torch.Tensor) -> torch.Tensor:", span=4)])
