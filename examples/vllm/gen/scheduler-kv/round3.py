"""Round-3 unit tests (build-oracle/round3/scheduler-kv.json) as scenarios.

Writes:
  - gen/scheduler-kv/round3_scenarios.yaml: the translated tests plus branch-coverage
    scenarios, appended to the fragment by build.sh (ids scheduler-kv-r3-*);
  - build-oracle/round3/scheduler-kv.yaml: the translated tests under oracle ids
    (oracle-r3-scheduler-kv-<n>), to run against the merged model.
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.normpath(os.path.join(HERE, "..", ".."))


def nested_array_schema(levels: int) -> str:
    wrappers = levels - 1
    return '{"type": "array", "items": ' * wrappers + '{"type": "string"}' + "}" * wrappers


def structural_tag(schema: str) -> str:
    return (
        '{"type": "structural_tag", "format": {"type": "json_schema", '
        f'"json_schema": {schema}}}}}'
    )


def nested_obj(levels: int):
    node = {"type": "string"}
    for _ in range(levels - 1):
        node = {"type": "array", "items": node}
    return node


PROMPT = [1, 15043, 590, 1024, 338, 4755, 322, 306, 29871]  # 9 tokens, a stand-in for the test prompt

tests = []

# 1. test_xgrammar_validation_rejects_deeply_nested_schema (json and structural_tag)
tests.append({
    "n": 1,
    "test": "tests/v1/structured_output/test_validation.py:186 test_xgrammar_validation_rejects_deeply_nested_schema",
    "scenario": {
        "name": "A JSON schema or structural tag nested 2000 levels deep is a validation error before any grammar conversion",
        "fixtures": ["tp1-llama-8b"],
        "steps": [
            {"flow": "structured-output-validate-xgrammar", "as": "json", "input": {"structured_outputs": {"json": nested_array_schema(2000)}}},
            {"flow": "structured-output-validate-xgrammar", "as": "tag", "input": {"structured_outputs": {"structural_tag": structural_tag(nested_array_schema(2000))}}},
        ],
        "expect": [
            "!steps.json.result.ok && steps.json.result.error.code == 'vllm-validation-error' && steps.json.result.error.message.contains('nested too deeply')",
            "!steps.tag.result.ok && steps.tag.result.error.code == 'vllm-validation-error' && steps.tag.result.error.message.contains('nested too deeply')",
        ],
    },
})

# 2. test_normal_regex_compiles_successfully
tests.append({
    "n": 2,
    "test": "tests/v1/structured_output/test_regex_compilation_timeout.py:23 test_normal_regex_compiles_successfully",
    "scenario": {
        "name": "A normal regex compiles under the timeout guard",
        "fixtures": ["tp1-llama-8b"],
        "steps": [
            {"interface": "structured-output-utils.compile-regex-with-timeout", "caller": "xgrammar-backend", "as": "c", "input": {"pattern": "[a-z]+"}},
        ],
        "expect": ["steps.c.result.ok && steps.c.result.value.compiled && steps.c.duration_ms < 5000"],
    },
})

# 3. test_concurrent_partial_prefill
steps = []
for i in range(3):
    steps.append({"flow": "scheduler-add-request", "as": f"a{i}", "input": {"request_id": f"cmpl-r{i}", "prompt_token_ids": PROMPT, "sampling_params": {"max_tokens": 1}}})
for k in range(1, 6):
    steps.append({"flow": "scheduler-schedule", "as": f"s{k}", "input": {}})
    sampled = [[791], [791], [791]] if k == 5 else [[], [], []]
    steps.append({"flow": "scheduler-update-from-output", "as": f"u{k}", "input": {
        "scheduler_output": f"= steps.s{k}.result.value",
        "model_runner_output": {"req_ids": ["cmpl-r0", "cmpl-r1", "cmpl-r2"], "sampled_token_ids": sampled}}})
tests.append({
    "n": 3,
    "test": "tests/v1/core/test_scheduler_e2e.py:25 test_concurrent_partial_prefill",
    "scenario": {
        "name": "Three prompts prefill concurrently in 2-token chunks (long_prefill_token_threshold 2, budget 6) and each finishes with one output",
        "description": "LLM(..., long_prefill_token_threshold=2, max_num_batched_tokens=6, max_num_seqs=3, enable_prefix_caching=True, block_size=16). The test's sampling defaults are replaced by max_tokens 1 (the test only checks one completion per prompt); the prompt is 9 tokens.",
        "fixtures": ["tp1-llama-8b"],
        "config": {"long-prefill-token-threshold": 2, "max-num-batched-tokens": 6, "max-num-seqs": 3, "async-scheduling": False},
        "steps": steps,
        "expect": [
            "steps.s1.result.value.num_scheduled_tokens == {'cmpl-r0': 2, 'cmpl-r1': 2, 'cmpl-r2': 2}",
            "steps.s5.result.value.num_scheduled_tokens == {'cmpl-r0': 1, 'cmpl-r1': 1, 'cmpl-r2': 1}",
            "[steps.u1, steps.u2, steps.u3, steps.u4].all(u, u.result.value.outputs == [])",
            "size(steps.u5.result.value.outputs) == 3 && steps.u5.result.value.outputs.all(o, size(o.new_token_ids) == 1 && o.finish_reason == 'length')",
        ],
    },
})

# 6. test_later_request_hits_cached_partial_tail
tests.append({
    "n": 6,
    "test": "tests/v1/core/prefix_cache/test_partial_prefix_cache_primitives.py:309 test_later_request_hits_cached_partial_tail",
    "scenario": {
        "name": "A partial-tail entry (hash at 10 tokens inside a 6-token block) is hit by a replay and by a longer request",
        "description": "hash_block_size 2, block_size 6, pool of 3 blocks. The prefix-chain hash at 10 tokens is the same string for the original, the replay and the extended request (the model's hashes are prefix-determined), so one lookup stands for both.",
        "fixtures": ["tp1-llama-8b"],
        "state": {"block-pool": {"num_gpu_blocks": 3, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}}},
        "steps": [
            {"interface": "block-pool.get-new-blocks", "caller": "kv-cache-manager", "as": "alloc", "input": {"num_blocks": 2}},
            {"interface": "block-pool.cache-full-blocks", "caller": "kv-cache-manager", "as": "full", "input": {"block_ids": [1], "block_hashes": ["0,0,1,1,2,2@6"]}},
            {"interface": "block-pool.cache-partial-block", "caller": "kv-cache-manager", "as": "part", "input": {"block_id": 2, "block_hash": "0,0,1,1,2,2,3,3,4,4@10", "num_tokens": 10}},
            {"interface": "block-pool.get-cached-block", "caller": "kv-cache-manager", "as": "replay", "input": {"block_hash": "0,0,1,1,2,2,3,3,4,4@10"}},
        ],
        "expect": [
            "steps.alloc.result.value.block_ids == [1, 2] && steps.part.result.value.cached",
            "steps.replay.result.value.block.block_id == 2",
        ],
    },
})

# Branch coverage for the new validator and partial entries (fragment only).
extra = [
    {"id": "scheduler-kv-r3-xgrammar-validation-branches",
     "name": "The xgrammar validator: a NUL regex is refused, a ReDoS regex times out, shallow schemas and objects pass, a deep object fails",
     "fixtures": ["tp1-llama-8b"],
     "steps": [
         {"flow": "structured-output-validate-xgrammar", "as": "nul", "input": {"structured_outputs": {"regex": "a\u0000b"}}},
         {"flow": "structured-output-validate-xgrammar", "as": "slow", "input": {"structured_outputs": {"regex": "(a+)+b"}}},
         {"flow": "structured-output-validate-xgrammar", "as": "re", "input": {"structured_outputs": {"regex": "[a-z]+"}}},
         {"flow": "structured-output-validate-xgrammar", "as": "shallow", "input": {"structured_outputs": {"json": nested_array_schema(64)}}},
         {"flow": "structured-output-validate-xgrammar", "as": "obj_ok", "input": {"structured_outputs": {"json": nested_obj(10)}}},
         {"flow": "structured-output-validate-xgrammar", "as": "obj_deep", "input": {"structured_outputs": {"json": nested_obj(70)}}},
         {"flow": "structured-output-validate-xgrammar", "as": "none", "input": {"structured_outputs": None}},
         {"flow": "structured-output-validate-xgrammar", "as": "empty", "input": {"structured_outputs": {}}},
     ],
     "expect": [
         "steps.nul.result.error.code == 'value-error' && steps.slow.result.error.code == 'vllm-validation-error' && steps.slow.result.error.message.contains('timed out')",
         "steps.re.result.value.valid && steps.shallow.result.value.valid && steps.obj_ok.result.value.valid && steps.none.result.value.valid && steps.empty.result.value.valid",
         "steps.obj_deep.result.error.code == 'vllm-validation-error'",
     ]},
    {"id": "scheduler-kv-r3-partial-entry-replaced-and-null",
     "name": "A longer partial entry replaces the block's shorter one; the null block is never cached",
     "fixtures": ["tp1-llama-8b"],
     "state": {"block-pool": {"num_gpu_blocks": 3, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}}},
     "steps": [
         {"interface": "block-pool.get-new-blocks", "caller": "kv-cache-manager", "as": "alloc", "input": {"num_blocks": 2}},
         {"interface": "block-pool.cache-partial-block", "caller": "kv-cache-manager", "as": "p8", "input": {"block_id": 2, "block_hash": "h@8", "num_tokens": 8}},
         {"interface": "block-pool.cache-partial-block", "caller": "kv-cache-manager", "as": "p10", "input": {"block_id": 2, "block_hash": "h@10", "num_tokens": 10}},
         {"interface": "block-pool.cache-partial-block", "caller": "kv-cache-manager", "as": "nullblk", "input": {"block_id": 0, "block_hash": "h@2", "num_tokens": 2}},
         {"interface": "block-pool.get-cached-block", "caller": "kv-cache-manager", "as": "old", "input": {"block_hash": "h@8"}},
         {"interface": "block-pool.get-cached-block", "caller": "kv-cache-manager", "as": "new", "input": {"block_hash": "h@10"}},
     ],
     "expect": [
         "steps.p10.result.value.removed == ['h@8'] && !steps.nullblk.result.value.cached",
         "steps.old.result.value.block == null && steps.new.result.value.block.block_id == 2",
         "trace.exists(e, e.type == 'call.end' && e.interface == 'block-pool.get-cached-block' && e.output.block != null)",
     ]},
]

frag = []
oracle = []
for t in tests:
    sc = copy.deepcopy(t["scenario"])
    sc = {"id": f"scheduler-kv-r3-test-{t['n']}", **sc}
    sc.setdefault("description", t["test"])
    if "trace" not in json.dumps(sc["expect"]) and "state" not in json.dumps(sc["expect"]):
        # write-then-read: the last step's call ended without an error
        last = sc["steps"][-1]
        iface = last.get("interface") or {
            "structured-output-validate-xgrammar": "xgrammar-backend.validate-xgrammar-grammar",
            "scheduler-update-from-output": "scheduler.update-from-output",
        }[last["flow"]]
        sc["expect"].append(f"trace.exists(e, e.type == 'call.end' && e.interface == '{iface}')")
    frag.append(sc)
    o = copy.deepcopy(sc)
    o["id"] = f"oracle-r3-scheduler-kv-{t['n']}"
    o["description"] = t["test"]
    oracle.append(o)
frag.extend(extra)


def dump(path, doc):
    import yaml
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, width=100000, allow_unicode=False)


dump(os.path.join(HERE, "round3_scenarios.yaml"), {"scenarios": frag})
os.makedirs(os.path.join(WS, "build-oracle", "round3"), exist_ok=True)
dump(os.path.join(WS, "build-oracle", "round3", "scheduler-kv.yaml"),
     {"schema_version": 1, "id": "vllm", "scenarios": oracle})
print("ok", len(frag), len(oracle), file=sys.stderr)
