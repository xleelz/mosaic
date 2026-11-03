"""Map each attention triton/cuda kernel entry to its launch sites (read-only analysis)."""
import ast, json, os, re, sys
ROOT = sys.argv[1]
INV = sys.argv[2]
inv = json.load(open(INV))["entries"]
mine = [e for e in inv if e.get("area") == "attention" or e["file"].startswith(("vllm/v1/attention/", "vllm/vllm_flash_attn/", "csrc/attention/"))]
tk = [e for e in mine if e["kind"] == "triton-kernel"]
# collect all python files under vllm
pyfiles = []
for d, _, fs in os.walk(os.path.join(ROOT, "vllm")):
    for f in fs:
        if f.endswith(".py"):
            pyfiles.append(os.path.join(d, f))
src = {p: open(p).read() for p in pyfiles}
def enclosing(tree):
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.lineno, node.end_lineno, node.name))
    return spans
trees = {}
for e in tk:
    short = e["name"].split(".")[-1]
    cls = e["name"].split(".")[0] if "." in e["name"] else None
    hits = []
    pat = re.compile(r"(?<![\w.])" + re.escape(short) + r"\s*[\[(]") if not cls else re.compile(re.escape(cls) + r"\b")
    for p, s in src.items():
        if short not in s and (not cls or cls not in s):
            continue
        for i, line in enumerate(s.splitlines(), 1):
            if pat.search(line) and not re.match(r"\s*def ", line) and not re.match(r"\s*class ", line) and not line.strip().startswith(("#", "import", "from")):
                if p not in trees:
                    try: trees[p] = enclosing(ast.parse(s))
                    except Exception: trees[p] = []
                fn = [n for (a, b, n) in trees[p] if a <= i <= b]
                fn = min([(b - a, n, a) for (a, b, n) in trees[p] if a <= i <= b], default=(0, "<module>", 0))
                hits.append((os.path.relpath(p, ROOT), i, fn[1], fn[2], "[" in line[line.find(short):line.find(short)+len(short)+3]))
    print(json.dumps({"name": e["name"], "file": e["file"], "line": e["line"], "end": e.get("end_line"), "hits": hits[:8]}))
