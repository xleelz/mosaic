package main

import (
	"encoding/json"
	"os"
	"sort"
	"strings"
	"testing"
)

// TestScanUnchanged pins the auto-detected output on the original fixtures
// (Go, TS, Python, Java) to what it was before the plugins existed: the
// plugin fixture directories sit under the same root, and neither their
// markers (which auto-detect reads at the root only) nor their files may
// change it.
func TestScanUnchanged(t *testing.T) {
	got, err := Scan("../testdata/inventory", Options{})
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile("../testdata/inventory/golden-auto.json")
	if err != nil {
		t.Fatal(err)
	}
	var want []Entry
	if err := json.Unmarshal(b, &want); err != nil {
		t.Fatal(err)
	}
	gj, _ := json.MarshalIndent(got, "", "  ")
	wj, _ := json.MarshalIndent(want, "", "  ")
	if string(gj) != string(wj) {
		t.Errorf("auto-detected output changed:\n%s", diffLines(string(wj), string(gj)))
	}
}

func diffLines(a, b string) string {
	al, bl := strings.Split(a, "\n"), strings.Split(b, "\n")
	var out []string
	for i := 0; i < len(al) || i < len(bl); i++ {
		var x, y string
		if i < len(al) {
			x = al[i]
		}
		if i < len(bl) {
			y = bl[i]
		}
		if x != y {
			out = append(out, "- "+x, "+ "+y)
		}
		if len(out) > 20 {
			break
		}
	}
	return strings.Join(out, "\n")
}

type check struct {
	key         string // "kind name"
	file        string
	line, end   int
	via, detail string
}

func scanKeys(t *testing.T, root string, opt Options) (map[string]Entry, []string) {
	t.Helper()
	got, err := Scan(root, opt)
	if err != nil {
		t.Fatal(err)
	}
	have := map[string]Entry{}
	var keys []string
	for _, e := range got {
		k := e.Kind + " " + e.Name
		have[k] = e
		keys = append(keys, k+" @"+e.File)
	}
	sort.Strings(keys)
	return have, keys
}

func expect(t *testing.T, have map[string]Entry, keys, want, bad []string, checks []check) {
	t.Helper()
	for _, w := range want {
		if _, ok := have[w]; !ok {
			t.Errorf("missing %q", w)
		}
	}
	if len(keys) != len(want) {
		t.Errorf("got %d entries, want %d:\n%s", len(keys), len(want), strings.Join(keys, "\n"))
	}
	for _, k := range keys {
		for _, b := range bad {
			if strings.Contains(k, b) {
				t.Errorf("unexpected entry %q", k)
			}
		}
	}
	for _, c := range checks {
		e := have[c.key]
		if e.File != c.file || e.Line != c.line || e.EndLine != c.end || e.Via != c.via || e.Detail != c.detail {
			t.Errorf("%s = %+v,\n want file %s line %d-%d via %s detail %q", c.key, e, c.file, c.line, c.end, c.via, c.detail)
		}
	}
}

func TestScanTSFrontend(t *testing.T) {
	const root = "../testdata/inventory/ts-frontend"
	have, keys := scanKeys(t, root, Options{})
	want := []string{
		"vscode-command foo.refresh",
		"vscode-command foo.open",
		"vscode-command foo.navigateLeft",
		"vscode-command foo.treeMode",
		"vscode-command foo.reveal",
		"vscode-command _foo.internal",
		"vscode-command foo.collapse",
		"vscode-command testing.runAll",
		"vscode-command editor.action.bar",
		"vscode-command editor.bar.accept",
		"workbench-contribution FooContribution",
		"workbench-contribution LegacyFooContribution",
		"workbench-contribution BarController",
		"extension-point fooViews",
		"service IFooService",
		"ipc-channel foo",
		"ipc-channel fooRemote",
		"exthost-rpc MainThreadFooShape.$registerFoo",
		"exthost-rpc MainThreadFooShape.$unregisterFoo",
		"exthost-rpc MainThreadFooShape.$queryFoo",
		"exthost-rpc ExtHostFooShape2.$acceptFoo",
		"exthost-customer MainThreadFoo",
		"extension-api vscode.commands.registerCommand",
		"extension-api vscode.commands.executeCommand",
		"extension-api vscode.comments.createCommentController",
		"extension-command fooext.run",
		"extension-command fooext.stop",
		"activation-event fooext onCommand:fooext.run",
		"activation-event fooext onLanguage:foo",
		"process-main src/main",
		"process-main src/vs/platform/foo/node/fooMain",
		"cli-command code tunnel",
		"cli-command code ext",
		"cli-command code status",
		"cli-command code tunnel prune",
		"cli-command code tunnel rename",
	}
	// Comments, strings, tests, helper wrappers with parameter ids,
	// declarations, other registries, non-shape interfaces, const API
	// members, storage "Main" classes and test extensions.
	bad := []string{"hidden.comment", "FakeInString", "test.only", "test.named", "descriptor", "not.a.vscode", "notRpc",
		"onDidExecute", "storageMain", "api.test", "channelName", "Disposable.dispose"}
	checks := []check{
		{"vscode-command foo.refresh", "src/vs/workbench/contrib/foo/browser/foo.contribution.ts", 7, 16, "action2", "class RefreshFooAction"},
		{"vscode-command foo.navigateLeft", "src/vs/workbench/contrib/foo/browser/foo.contribution.ts", 31, 35, "action2", "anonymous BaseNavAction subclass"},
		{"vscode-command foo.treeMode", "src/vs/workbench/contrib/foo/browser/foo.contribution.ts", 48, 0, "action2", "class TreeModeAction"},
		{"vscode-command foo.reveal", "src/vs/workbench/contrib/foo/browser/foo.contribution.ts", 50, 0, "commands-registry", "handler (inline function)"},
		{"vscode-command foo.collapse", "src/vs/workbench/contrib/foo/browser/foo.contribution.ts", 55, 59, "keybinding-rule", "handler collapseAll"},
		{"vscode-command editor.bar.accept", "src/vs/editor/contrib/bar/browser/bar.ts", 11, 15, "editor-command", "class BarCommand"},
		{"workbench-contribution FooContribution", "src/vs/workbench/contrib/foo/browser/foo.contribution.ts", 69, 0, "workbench-contribution2", "id workbench.contrib.foo, WorkbenchPhase.AfterRestored"},
		{"service IFooService", "src/vs/platform/foo/common/foo.ts", 1, 0, "create-decorator", "id fooService; registerSingleton FooService (src/vs/workbench/services/foo/common/fooService.ts:4)"},
		{"ipc-channel fooRemote", "src/vs/platform/foo/node/fooMain.ts", 4, 0, "register-channel", "channel new FooChannel(service)"},
		{"exthost-rpc MainThreadFooShape.$queryFoo", "src/vs/workbench/api/common/extHost.protocol.ts", 4, 0, "rpc-shape", "implemented by MainThreadFoo (src/vs/workbench/api/browser/mainThreadFoo.ts)"},
		{"exthost-customer MainThreadFoo", "src/vs/workbench/api/browser/mainThreadFoo.ts", 1, 6, "extHostNamedCustomer", "MainContext.MainThreadFoo"},
		{"extension-command fooext.run", "extensions/fooext/package.json", 11, 0, "package-json", "extension fooext; handler extensions/fooext/src/extension.ts:2"},
		{"cli-command code ext", "cli/src/commands/args.rs", 16, 0, "clap-subcommand", "Commands"},
		{"cli-command code tunnel rename", "cli/src/commands/args.rs", 35, 0, "clap-subcommand", "TunnelSubcommand"},
	}
	expect(t, have, keys, want, bad, checks)

	// Only the plugin: --lang ts-frontend alone runs it; --lang ts does not.
	if h, _ := scanKeys(t, root, Options{Langs: []string{"ts"}}); len(h) != 0 {
		t.Errorf("--lang ts should not run the ts-frontend plugin: %v", h)
	}
	if h, _ := scanKeys(t, root, Options{Langs: []string{"ts-frontend"}}); len(h) != len(want) {
		t.Errorf("--lang ts-frontend found %d entries, want %d", len(h), len(want))
	}
}

func TestScanPythonGPU(t *testing.T) {
	const root = "../testdata/inventory/python-gpu"
	have, keys := scanKeys(t, root, Options{})
	want := []string{
		"http-route POST /v1/chat/completions",
		"http-route GET /health",
		"http-route GET /ping",
		"http-route POST /ping",
		"http-route POST /abort",
		"cli-command vllm serve",
		"cli-command vllm bench",
		"cli-command vllm bench latency",
		"python-api LLM.generate",
		"python-api LLM.chat",
		"python-api LLM.encode",
		"python-api AsyncLLMEngine.generate",
		"python-api AsyncLLMEngine.abort",
		"engine-rpc collective_rpc init_device",
		"engine-rpc collective_rpc load_model",
		"engine-rpc collective_rpc get_model_inspection",
		"engine-rpc utility add_lora",
		"engine-rpc utility abort_requests",
		"busy-loop EngineCore.step",
		"busy-loop EngineCoreProc.run_busy_loop",
		"busy-loop EngineCoreProc.process_input_sockets",
		"torch-op _C::rms_norm",
		"torch-op _C::fused",
		"torch-op vllm::silu_fused",
		"torch-op-wrapper rms_norm",
		"torch-op-wrapper fused",
		"cuda-kernel rms_norm_kernel",
		"cuda-kernel plain_kernel",
		"triton-kernel _silu_kernel",
		"triton-kernel _tuned_kernel",
		"model-registry LlamaForCausalLM",
		"model-registry MistralForCausalLM",
		"plugin vllm.platform_plugins fake_platform",
		"plugin console_scripts vllm",
		"plugin vllm.general_plugins lora_resolver",
		"plugin builtin_platform_plugins cuda",
		"plugin group vllm.platform_plugins",
	}
	// Comments, strings, tests, examples, private and property methods,
	// abstract mixin methods, base subcommands without a name, nested drain
	// loops, numba jit, Python-registered op calls, macro kernels, the
	// TORCH_LIBRARY #define, superseded models and dynamic routes.
	bad := []string{"commented", "in-string", "test-only", "example_kernel", "_private", "tokenizer", "must_override",
		"BenchmarkSubcommandBase", "_drain", "not_triton", "uses_python_op", "helper", "fake_in_string", "kernel name",
		"OldForCausalLM", "route.path", "TORCH_EXTENSION"}
	checks := []check{
		{"http-route POST /v1/chat/completions", "vllm/entrypoints/openai/api_router.py", 9, 11, "fastapi", "handler create_chat_completion"},
		{"http-route POST /abort", "vllm/entrypoints/openai/api_router.py", 26, 0, "fastapi-add-route", "handler abort_requests"},
		{"cli-command vllm bench latency", "vllm/entrypoints/cli/benchmark/latency.py", 4, 6, "cli-subcommand", "class BenchmarkLatencySubcommand"},
		{"python-api LLM.chat", "vllm/entrypoints/llm.py", 24, 25, "package-export", "vllm.LLM"},
		{"python-api LLM.encode", "vllm/entrypoints/pooling.py", 5, 6, "package-export-inherited", "vllm.LLM (from PoolingMixin)"},
		{"python-api AsyncLLMEngine.abort", "vllm/v1/engine/async_llm.py", 5, 6, "package-export", "vllm.AsyncLLMEngine = vllm.v1.engine.async_llm.AsyncLLM"},
		{"engine-rpc collective_rpc load_model", "vllm/v1/worker/gpu_worker.py", 5, 6, "collective_rpc", "defined on Worker, GPUModelRunner; called at vllm/v1/executor/abstract.py:4"},
		{"engine-rpc utility add_lora", "vllm/v1/engine/core.py", 8, 9, "utility", "defined on EngineCore; called at vllm/v1/engine/core_client.py:3"},
		{"busy-loop EngineCoreProc.process_input_sockets", "vllm/v1/engine/core.py", 25, 26, "thread-target", "while True"},
		{"torch-op _C::fused", "csrc/torch_bindings.cpp", 6, 0, "torch-library", "fused(Tensor a, Tensor b) -> Tensor"},
		{"torch-op _C::rms_norm", "csrc/torch_bindings.cpp", 5, 0, "torch-library", "rms_norm(Tensor! out, Tensor input, Tensor weight, float eps) -> (); impl CUDA=TORCH_BOX(&rms_norm)"},
		{"torch-op vllm::silu_fused", "vllm/model_executor/layers/act.py", 12, 0, "direct-register", "impl _silu_impl"},
		{"torch-op-wrapper rms_norm", "vllm/_custom_ops.py", 4, 5, "torch-ops-call", "torch.ops._C.rms_norm"},
		{"cuda-kernel rms_norm_kernel", "csrc/kernels.cu", 6, 0, "cuda-global", ""},
		{"triton-kernel _tuned_kernel", "vllm/model_executor/layers/act.py", 24, 27, "triton-jit", "autotune"},
		{"model-registry MistralForCausalLM", "vllm/model_executor/models/registry.py", 4, 0, "registry-table", "llama.LlamaForCausalLM (_TEXT_GENERATION_MODELS)"},
	}
	expect(t, have, keys, want, bad, checks)

	// The base python scanner lists FastAPI routes itself; everything else
	// is the plugin's.
	h, _ := scanKeys(t, root, Options{Langs: []string{"python"}})
	for k, e := range h {
		if e.Kind != KindHTTP {
			t.Errorf("--lang python should not run the python-gpu plugin: %s", k)
		}
	}
	if len(h) != 5 {
		t.Errorf("--lang python: %d FastAPI routes, want 5: %v", len(h), h)
	}
}

func TestDetectPlugin(t *testing.T) {
	cases := []struct {
		root, plugin string
		want         bool
	}{
		{"../testdata/inventory/ts-frontend", "ts-frontend", true},
		{"../testdata/inventory/ts-frontend", "python-gpu", false},
		{"../testdata/inventory/python-gpu", "python-gpu", true},
		{"../testdata/inventory/python-gpu", "ts-frontend", false},
		{"../testdata/inventory", "ts-frontend", false},
		{"../testdata/inventory", "python-gpu", false},
	}
	for _, c := range cases {
		if got := detectPlugin(c.plugin, c.root); got != c.want {
			t.Errorf("detectPlugin(%s, %s) = %v, want %v", c.plugin, c.root, got, c.want)
		}
	}
}

func TestLexers(t *testing.T) {
	// Templates with substitutions, regex literals holding quotes and
	// slashes, and comments all stay opaque; lines stay right after an
	// unterminated quote (a Rust lifetime).
	src := "a(`x ${b('`')} y`, /'[/]/g) // c('\n/* d */ e(\"f\") 'g\nh\n"
	var got []string
	for _, tk := range tslex([]byte(src)) {
		got = append(got, string(tk.k)+":"+tk.s)
	}
	want := "i:a p:( t:x ${b('`')} y p:, r:/'[/]/g p:) i:e p:( s:f p:) s:g i:h"
	if strings.Join(got, " ") != want {
		t.Errorf("tslex =\n%s\nwant\n%s", strings.Join(got, " "), want)
	}
	if toks := tslex([]byte(src)); toks[len(toks)-1].line != 3 {
		t.Errorf("last token line = %d, want 3", toks[len(toks)-1].line)
	}
	py := "def f(x):\n    \"\"\"doc\nat column zero\n    \"\"\"\n    return rb'\\'' # c\n"
	var pg []string
	for _, tk := range pylex([]byte(py)) {
		pg = append(pg, string(tk.k)+":"+tk.s)
	}
	pwant := "i:def i:f p:( i:x p:) p:: l: s:doc\nat column zero\n     l: i:return s:\\' l:"
	if strings.Join(pg, " ") != pwant {
		t.Errorf("pylex =\n%q\nwant\n%q", strings.Join(pg, " "), pwant)
	}
	f := parsePy("x.py", []byte(py))
	if len(f.defs) != 1 || f.defs[0].endLine != 5 {
		t.Errorf("def extent = %+v", f.defs)
	}
}
