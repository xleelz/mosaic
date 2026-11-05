"""Round-6 regressions (FIXES6): the mechanisms the round-5 blind measure found absent in this area.

Writes gen/scheduler-kv/round6_scenarios.yaml (ids scheduler-kv-r6-*), appended to the fragment by build.sh.
"""

import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
FX = ["tp1-llama-8b"]


def call(iface, as_, caller="engine-core", **inp):
    return {"interface": iface, "caller": caller, "as": as_, "input": inp}


def add(as_, rid, segs=None, toks=None, **kw):
    inp = {"request_id": rid}
    if segs is not None:
        inp["prompt_segments"] = [{"key": k, "num_tokens": n} for k, n in segs]
    if toks is not None:
        inp["prompt_token_ids"] = toks
    inp.setdefault("sampling_params", {"max_tokens": kw.pop("max_tokens", 8)})
    inp.update(kw)
    return {"flow": "scheduler-add-request", "as": as_, "input": inp}


def sched(as_):
    return {"flow": "scheduler-schedule", "as": as_, "input": {}}


def update(as_, s_as, mro):
    return {"interface": "scheduler.update-from-output", "caller": "engine-core", "as": as_,
            "input": {"scheduler_output": f"= steps.{s_as}.result.value", "model_runner_output": mro}}


def free(as_):
    return call("block-pool.get-num-free-blocks", as_, caller="kv-cache-manager")


scen = []
P33 = list(range(1, 34))

# ------------------------------------------------------------------ deferred block free (oracle4)
for name, cfg, deferred in [
    ("consumer-async", {"async-scheduling": True, "kv-connector": "NixlConnector", "kv-role": "kv_consumer"}, True),
    ("kv-both-pp2-sync", {"async-scheduling": False, "pipeline-parallel-size": 2, "kv-connector": "NixlConnector", "kv-role": "kv_both"}, False),
    ("producer-async", {"async-scheduling": True, "kv-connector": "NixlConnector", "kv-role": "kv_producer"}, False),
    ("consumer-sync", {"async-scheduling": False, "kv-connector": "NixlConnector", "kv-role": "kv_consumer"}, False),
]:
    exp = [
        "steps.u0.result.value.outputs.exists(o, o.request_id == 'r1' && o.finish_reason == 'stop')",
        "steps.f0.result.value.num_free_blocks < steps.f0.result.value.num_gpu_blocks",
    ]
    if deferred:
        exp += [
            "// step 2 (scheduled before step 1's output) may still write r1's blocks: they wait behind fence 2\nsteps.fu0.result.value.num_free_blocks == steps.f0.result.value.num_free_blocks && size(state.scheduler.deferred_frees) == 0",
            "steps.fu1.result.value.num_free_blocks > steps.fu0.result.value.num_free_blocks" if not cfg["async-scheduling"] else "steps.fu1.result.value.num_free_blocks == steps.f0.result.value.num_gpu_blocks - 1",
            "trace.exists(e, e.type == 'note' && e.title.startsWith('An in-flight step may still write these blocks'))",
            "trace.exists(e, e.type == 'call.start' && e.interface == 'scheduler.drain-deferred-frees')",
        ]
    else:
        exp += [
            "steps.fu0.result.value.num_free_blocks > steps.f0.result.value.num_free_blocks",
            "!trace.exists(e, e.type == 'note' && e.title.startsWith('An in-flight step may still write these blocks'))",
        ]
    steps = [add("a", "r1", toks=P33, sampling_params={"max_tokens": 5, "stop_token_ids": [42]}), sched("s0")]
    if not cfg["async-scheduling"]:
        # sync: r1 is not rescheduled before its output, so another request fills step 2 (the PP pipeline's second batch)
        steps.append(add("b", "r2", toks=list(range(100, 117)), sampling_params={"max_tokens": 5}))
    # sync scheduling: a second schedule finds r1 still running and schedules its decode only after output;
    # schedule twice before the first output, as the async engine core does.
    steps += [sched("s1"), free("f0"),
              update("u0", "s0", {"req_ids": ["r1"], "sampled_token_ids": [[42]]}), free("fu0"),
              update("u1", "s1", {"req_ids": ["r1"], "sampled_token_ids": [[7]]}), free("fu1")]
    scen.append({
        "id": f"scheduler-kv-r6-defer-block-free-{name}",
        "name": ("Deferred block free on (kv_both, PP 2) but r1 was not scheduled in the in-flight step 2: its last_sched_seq has been processed, so its blocks return at once" if name == "kv-both-pp2-sync" else None) or f"Deferred block free ({name}): {'blocks of a request finished by step 1 wait until step 2 is processed' if deferred else 'blocks return to the pool at once'}",
        "description": "Scheduler.__init__ sets defer_block_free for a KV-consumer connector (kv_consumer or kv_both) when max_concurrent_batches > 1 (async on V1 without PP: 2; PP size otherwise; scheduler.py:185-192, vllm.py:577-587). _free_request_blocks parks the blocks behind sched_step_seq; update_from_output advances processed_step_seq and drains (scheduler.py:1549-1552, 2044-2048, 2759-2801).",
        "fixtures": FX,
        "config": dict(cfg, **{"use-v2-model-runner": False}),
        "steps": steps,
        "expect": exp,
    })

# ------------------------------------------------------------------ stride alignment and layouts (oracle4)
scen.append({
    "id": "scheduler-kv-r6-stride-alignment-layouts",
    "name": "Bytes per block: BLHNC rounds the packed sum to lcm(hot page, layer alignments); layer-outer pads each page; LHBNC can't express mixed page sizes",
    "description": "_get_kv_cache_bytes_per_block (kv_cache_utils.py:1520-1551), _get_layer_block_stride (1515-1517), validate_kv_cache_layout (1554-1586), KVCacheLayout (kv_cache_layout.py:23-28).",
    "fixtures": FX,
    "steps": [
        call("kv-cache-utils.get-kv-cache-config-from-groups", "blhnc", available_memory=138240, layout="BLHNC",
             kv_cache_groups=[{"layer_names": ["attention"], "layer_pages": {"attention": 8192}, "block_stride_alignment": 1152},
                              {"layer_names": ["hot"], "layer_pages": {"hot": 5120}, "hisparse_hot": True}]),
        call("kv-cache-utils.get-kv-cache-config-from-groups", "bhlnc", available_memory=65536, layout="BHLNC",
             kv_cache_groups=[{"layer_names": ["l0", "l1"], "layer_pages": {"l0": 4096, "l1": 4096}, "layer_alignments": {"l1": 3072}}]),
        call("kv-cache-utils.get-kv-cache-config-from-groups", "lbnhc", available_memory=92160, layout="LBNHC",
             kv_cache_groups=[{"layer_names": ["mla"], "layer_pages": {"mla": 8192}, "block_stride_alignment": 1152}]),
        call("kv-cache-utils.get-kv-cache-config-from-groups", "lhbnc", available_memory=100000, layout="LHBNC",
             kv_cache_groups=[{"layer_names": ["a", "b"], "layer_pages": {"a": 8192, "b": 5120}}]),
        call("kv-cache-utils.get-kv-cache-config-from-groups", "lbhnc2", available_memory=100000, layout="LBHNC",
             kv_cache_groups=[{"layer_names": ["a"], "layer_pages": {"a": 8192}}, {"layer_names": ["b"], "layer_pages": {"b": 5120}}]),
    ],
    "expect": [
        "steps.blhnc.result.value.bytes_per_block == 46080 && steps.blhnc.result.value.num_blocks == 3 && steps.blhnc.result.value.kv_cache_tensors.all(t, t.block_stride == 46080)",
        "// 8192 rounded up to lcm(1, 3072) = 3072 -> 9216; block-outer: every layer shares the 9216-byte block\nsteps.bhlnc.result.value.bytes_per_block == 9216 && steps.bhlnc.result.value.num_blocks == 7",
        "// layer-outer: the 8192-byte page padded to its 1152 alignment is 9216, and is the tensor's block stride\nsteps.lbnhc.result.value.bytes_per_block == 9216 && steps.lbnhc.result.value.num_blocks == 10 && steps.lbnhc.result.value.kv_cache_tensors[0].block_stride == 9216",
        "!steps.lhbnc.result.ok && steps.lhbnc.result.error.message == \"KV cache layout LHBNC cannot express this model's mixed page sizes ([5120, 8192]); a backend should declare block-outermost supported layouts (e.g. BLHNC), or set VLLM_KV_CACHE_LAYOUT=BLHNC.\"",
        "// two groups need the layer dim inside the block dim, so the layer-compact LBHNC is refused too\n!steps.lbhnc2.result.ok && steps.lbhnc2.result.error.message.startsWith('KV cache layout LBHNC cannot express')",
    ],
})

# ------------------------------------------------------------------ stop check: min_tokens and repetition (judge4 Q4-2)
RD = {"max_pattern_size": 4, "min_count": 3}
scen.append({
    "id": "scheduler-kv-r6-stop-check-order",
    "name": "check_stop order: EOS, stop ids, length, then the min_tokens gate, then repetition (FINISHED_REPETITION, stop_reason repetition_detected)",
    "description": "vllm/v1/core/sched/utils.py:98-140 and check_sequence_repetition 28-67.",
    "fixtures": FX,
    "steps": [
        call("sched-utils.check-stop", "eos_below_min", caller="scheduler", last_token_id=128009, num_tokens=5, num_output_tokens=2, max_tokens=16, min_tokens=8, eos_token_id=128009, stop_token_ids=[]),
        call("sched-utils.check-stop", "rep_below_min", caller="scheduler", last_token_id=12, num_tokens=10, num_output_tokens=6, max_tokens=16, min_tokens=8, eos_token_id=128009, stop_token_ids=[], output_token_ids=[11, 12, 11, 12, 11, 12], repetition_detection=RD),
        call("sched-utils.check-stop", "rep", caller="scheduler", last_token_id=12, num_tokens=10, num_output_tokens=6, max_tokens=16, min_tokens=0, eos_token_id=128009, stop_token_ids=[], output_token_ids=[11, 12, 11, 12, 11, 12], repetition_detection=RD),
        call("sched-utils.check-stop", "two_reps", caller="scheduler", last_token_id=12, num_tokens=8, num_output_tokens=4, max_tokens=16, eos_token_id=128009, stop_token_ids=[], output_token_ids=[11, 12, 11, 12], repetition_detection=RD),
        call("sched-utils.check-stop", "len_first", caller="scheduler", last_token_id=12, num_tokens=10, num_output_tokens=6, max_tokens=6, eos_token_id=128009, stop_token_ids=[], output_token_ids=[11, 12, 11, 12, 11, 12], repetition_detection=RD),
        call("sched-utils.check-stop", "off", caller="scheduler", last_token_id=12, num_tokens=10, num_output_tokens=6, max_tokens=16, eos_token_id=128009, stop_token_ids=[], output_token_ids=[11, 12, 11, 12, 11, 12], repetition_detection={"max_pattern_size": 0, "min_count": 0}),
        call("sched-utils.check-stop", "minp", caller="scheduler", last_token_id=7, num_tokens=10, num_output_tokens=6, max_tokens=16, eos_token_id=128009, stop_token_ids=[], output_token_ids=[7, 7, 7, 7, 7, 7], repetition_detection={"max_pattern_size": 3, "min_pattern_size": 2, "min_count": 3}),
    ],
    "expect": [
        "steps.eos_below_min.result.value == {'stopped': true, 'status': 'FINISHED_STOPPED', 'stop_reason': null}",
        "!steps.rep_below_min.result.value.stopped",
        "steps.rep.result.value == {'stopped': true, 'status': 'FINISHED_REPETITION', 'stop_reason': 'repetition_detected'}",
        "!steps.two_reps.result.value.stopped",
        "steps.len_first.result.value.status == 'FINISHED_LENGTH_CAPPED'",
        "!steps.off.result.value.stopped",
        "// pattern [7, 7] repeats three times in six 7s\nsteps.minp.result.value.status == 'FINISHED_REPETITION'",
    ],
})
loop = [11, 12, 13, 14] * 3
steps = [add("a", "rr", toks=[128000, 9906, 1917], sampling_params={"max_tokens": 64, "min_tokens": 0, "repetition_detection": RD})]
for i, t in enumerate(loop):
    steps += [sched(f"s{i}"), update(f"u{i}", f"s{i}", {"req_ids": ["rr"], "sampled_token_ids": [[t]]})]
scen.append({
    "id": "scheduler-kv-r6-repetition-finishes-request",
    "name": "A looping output (4-token pattern three times) finishes the request with finish_reason repetition and frees it",
    "description": "update_from_output -> _update_request_with_output -> check_stop (scheduler.py:2493-2510, utils.py:128-138); FINISHED_REPETITION maps to FinishReason.REPETITION (request.py:386, 411).",
    "fixtures": FX,
    "config": {"async-scheduling": False},
    "steps": steps,
    "expect": [
        "lists.range(11).all(k, steps['u' + string(k)].result.value.outputs[0].finish_reason == null)",
        "steps.u11.result.value.outputs[0].finish_reason == 'repetition' && steps.u11.result.value.outputs[0].stop_reason == 'repetition_detected'",
        "!('rr' in state.scheduler.requests)",
    ],
})

# ------------------------------------------------------------------ logprobs forwarding (oracle4 worker-runner fix 4)
LP = {"logprob_token_ids": [[500, 500, 9], [600, 1, 600]], "logprobs": [[-0.1, -0.1, -2.0], [-0.7, -0.3, -0.7]],
      "sampled_token_ranks": [1, 2], "cu_num_generated_tokens": None}
scen.append({
    "id": "scheduler-kv-r6-forwards-logprobs",
    "name": "update_from_output slices the runner's LogprobsLists per request (only for requests asking for logprobs) and passes prompt logprobs through",
    "description": "new_logprobs = logprobs.slice_request(req_index, len(new_token_ids)) when sampling_params.num_logprobs is not None (scheduler.py:2214-2221); new_prompt_logprobs_tensors = prompt_logprobs_dict.get(req_id) (2249-2262); LogprobsLists (outputs.py:24-56).",
    "fixtures": FX,
    "config": {"async-scheduling": False, "enable-prefix-caching": False},
    "steps": [
        add("a1", "lp", toks=[128000, 9906, 1917], sampling_params={"max_tokens": 4, "logprobs": 2, "prompt_logprobs": 1}),
        add("a2", "nolp", toks=[128000, 9906, 1918], sampling_params={"max_tokens": 4}),
        sched("s1"),
        update("u1", "s1", {"req_ids": ["lp", "nolp"], "sampled_token_ids": [[500], [600]], "logprobs": LP,
                            "prompt_logprobs_dict": {"lp": {"logprob_token_ids": [[9906, 1], [1917, 1]], "logprobs": [[-1.5, -0.2], [-2.5, -0.1]], "selected_token_ranks": [3, 5]}}}),
        sched("s2"),
        update("u2", "s2", {"req_ids": ["lp", "nolp"], "sampled_token_ids": [[501], [601]]}),
    ],
    "expect": [
        "steps.u1.result.value.outputs.exists(o, o.request_id == 'lp' && o.new_logprobs == {'token_ids': [[500, 500, 9]], 'logprobs': [[-0.1, -0.1, -2.0]], 'ranks': [1]})",
        "steps.u1.result.value.outputs.exists(o, o.request_id == 'lp' && o.new_prompt_logprobs_tensors == {'token_ids': [[9906, 1], [1917, 1]], 'logprobs': [[-1.5, -0.2], [-2.5, -0.1]], 'ranks': [3, 5]})",
        "steps.u1.result.value.outputs.exists(o, o.request_id == 'nolp' && o.new_logprobs == null && o.new_prompt_logprobs_tensors == null)",
        "// a step whose runner output has no logprobs (None) gives None\nsteps.u2.result.value.outputs.all(o, o.new_logprobs == null)",
    ],
})
scen.append({
    "id": "scheduler-kv-r6-logprobs-cu-and-stop-trim",
    "name": "With spec decode (cu_num_generated_tokens) a request's logprob rows start at its cumulative offset; tokens trimmed after a stop drop their rows",
    "description": "LogprobsLists.slice_request uses cu_num_generated_tokens[req_idx] (outputs.py:47-56); _update_request_with_output trims tokens after the stop before the slice (scheduler.py:2493-2510, 2214-2221).",
    "fixtures": FX,
    "config": {"async-scheduling": False, "enable-prefix-caching": False},
    "steps": [
        add("a1", "x", toks=[1, 2, 3], sampling_params={"max_tokens": 8, "logprobs": 0}),
        add("a2", "y", toks=[4, 5, 6], sampling_params={"max_tokens": 8, "logprobs": 0, "stop_token_ids": [77]}),
        sched("s1"),
        update("u1", "s1", {"req_ids": ["x", "y"], "sampled_token_ids": [[10, 11], [77, 78]],
                            "logprobs": {"logprob_token_ids": [[10], [11], [77], [78]], "logprobs": [[-0.1], [-0.2], [-0.3], [-0.4]],
                                         "sampled_token_ranks": [1, 1, 1, 1], "cu_num_generated_tokens": [0, 2]}}),
    ],
    "expect": [
        "steps.u1.result.value.outputs.exists(o, o.request_id == 'x' && o.new_logprobs.token_ids == [[10], [11]])",
        "steps.u1.result.value.outputs.exists(o, o.request_id == 'y' && o.new_token_ids == [77] && o.finish_reason == 'stop' && o.new_logprobs == {'token_ids': [[77]], 'logprobs': [[-0.3]], 'ranks': [1]})",
    ],
})

# ------------------------------------------------------------------ PrefillStats (engine-core request)
scen.append({
    "id": "scheduler-kv-r6-prefill-stats",
    "name": "The first output carries finalized PrefillStats (local hit, cache-creation tokens); later outputs and a post-preemption prefill carry none",
    "description": "PrefillStats.set at the first scheduled prefill when num_preemptions <= 0 (scheduler.py:1074-1081); take_prefill_stats on the first emitted output and finalize(estimate_cached_tokens) (2207-2212, stats.py:327-346, kv_cache_manager.py:751-780).",
    "fixtures": FX,
    "config": {"async-scheduling": False, "enable-prefix-caching": True},
    "steps": [
        add("a0", "warm", segs=[("doc", 100)], max_tokens=1),
        sched("s0"),
        update("u0", "s0", {"req_ids": ["warm"], "sampled_token_ids": [[5]]}),
        add("a1", "hit", segs=[("doc", 100), ("tail", 40)], max_tokens=3),
        sched("s1"),
        update("u1", "s1", {"req_ids": ["hit"], "sampled_token_ids": [[6]]}),
        sched("s2"),
        update("u2", "s2", {"req_ids": ["hit"], "sampled_token_ids": [[7]]}),
    ],
    "expect": [
        "// cold: 100 prompt tokens, 6 full blocks (96 tokens) written to the prefix cache\nsteps.u0.result.value.outputs[0].prefill_stats == {'num_prompt_tokens': 100, 'num_computed_tokens': 100, 'num_cached_tokens': 0, 'num_local_cached_tokens': 0, 'num_external_cached_tokens': 0, 'num_cache_creation_tokens': 96}",
        "// warm: 96 tokens hit locally; 140 tokens make 8 full blocks (128 cached), so 32 are newly created\nsteps.u1.result.value.outputs[0].prefill_stats == {'num_prompt_tokens': 140, 'num_computed_tokens': 44, 'num_cached_tokens': 96, 'num_local_cached_tokens': 96, 'num_external_cached_tokens': 0, 'num_cache_creation_tokens': 32}",
        "steps.u2.result.value.outputs[0].prefill_stats == null",
    ],
})

# ------------------------------------------------------------------ KV events (judge4 Q4-3 b, c, d)
EV = {"enable-kv-cache-events": True, "kv-events-publisher": "zmq", "async-scheduling": False}
take = lambda as_: call("kv-cache-manager.take-events", as_, caller="scheduler")
scen.append({
    "id": "scheduler-kv-r6-kv-events-block-stored-fields",
    "name": "BlockStored carries the new hashes, the parent hash, the blocks' token ids, block size, medium GPU and the LoRA; a decode-filled block's parent is the previous block",
    "description": "cache_full_blocks -> _build_block_stored_event (block_pool.py:303-377).",
    "fixtures": FX,
    "config": EV,
    "steps": [
        add("a", "e1", toks=list(range(1000, 1020)), sampling_params={"max_tokens": 14},
            lora_request={"lora_name": "sql", "lora_int_id": 3, "lora_path": "/models/lora/sql"}),
        sched("s1"), take("ev1"),
    ] + sum([[update(f"u{i}", f"s{i}", {"req_ids": ["e1"], "sampled_token_ids": [[2000 + i]]}), sched(f"s{i + 1}"), take(f"ev{i + 1}")] for i in range(1, 13)], []),
    "expect": [
        "size(steps.ev1.result.value.events) == 1 && steps.ev1.result.value.events[0].parent_block_hash == null && steps.ev1.result.value.events[0].token_ids == lists.range(16).map(i, 1000 + i)",
        "steps.ev1.result.value.events[0].block_size == 16 && steps.ev1.result.value.events[0].medium == 'GPU' && steps.ev1.result.value.events[0].lora_id == 3 && steps.ev1.result.value.events[0].lora_name == 'sql' && steps.ev1.result.value.events[0].group_idx == 0",
        "// 20 prompt + 12 output tokens fill block 2 when token 32 is computed\nlists.range(12).map(i, i + 2).filter(k, size(steps['ev' + string(k)].result.value.events) > 0).size() == 1",
        "lists.range(12).map(i, i + 2).exists(k, size(steps['ev' + string(k)].result.value.events) == 1 && steps['ev' + string(k)].result.value.events[0].parent_block_hash == steps.ev1.result.value.events[0].block_hashes[0] && steps['ev' + string(k)].result.value.events[0].token_ids == lists.range(4).map(i, 1016 + i) + lists.range(12).map(i, 2001 + i))",
    ],
})
scen.append({
    "id": "scheduler-kv-r6-kv-events-report-mode-and-reset",
    "name": "kv_cache_report_mode full re-announces a prefix hit as one BlockStored (parent null); eviction emits BlockRemoved with medium GPU; reset emits AllBlocksCleared",
    "description": "get_computed_blocks -> emit_cached_block_events (kv_cache_manager.py:302-310, block_pool.py:379-448); _emit_block_removed_events (605-618); reset_prefix_cache (863-864).",
    "fixtures": FX,
    "config": EV,
    "state": {"block-pool": {"num_gpu_blocks": 9, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        add("a1", "A", segs=[("shared", 100)], max_tokens=1),
        sched("s1"), update("u1", "s1", {"req_ids": ["A"], "sampled_token_ids": [[1]]}), take("evA"),
        add("a2", "B", segs=[("shared", 100)], sampling_params={"max_tokens": 1, "extra_args": {"kv_cache_report_mode": "full"}}),
        sched("s2"), take("evB"), update("u2", "s2", {"req_ids": ["B"], "sampled_token_ids": [[1]]}),
        add("a3", "D", segs=[("other", 100)], max_tokens=1),
        sched("s3"), take("evD"), update("u3", "s3", {"req_ids": ["D"], "sampled_token_ids": [[1]]}),
        {"flow": "scheduler-reset-prefix-cache", "as": "rst", "input": {}}, take("evR"),
    ],
    "expect": [
        "steps.evB.result.value.events.exists(e, e.type == 'BlockStored' && e.parent_block_hash == null && e.block_hashes == steps.evA.result.value.events[0].block_hashes && size(e.token_ids) == 96)",
        "steps.evD.result.value.events.exists(e, e.type == 'BlockRemoved' && size(e.block_hashes) == 1 && e.medium == 'GPU')",
        "steps.rst.result.ok && steps.evR.result.value.events.exists(e, e.type == 'AllBlocksCleared')",
    ],
})

# ------------------------------------------------------------------ evict_blocks (coverage_gaps)
scen.append({
    "id": "scheduler-kv-r6-evict-blocks-by-id",
    "name": "evict_blocks drops a cached block's hash (so a repeat prompt misses it) and emits BlockRemoved; an id past the pool is refused",
    "description": "KVCacheManager.evict_blocks -> BlockPool.evict_blocks (kv_cache_manager.py:665-672, block_pool.py:807-825).",
    "fixtures": FX,
    "config": EV,
    "state": {"block-pool": {"num_gpu_blocks": 64, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        add("a1", "A", segs=[("doc", 40)], max_tokens=1),
        sched("s1"), update("u1", "s1", {"req_ids": ["A"], "sampled_token_ids": [[1]]}), take("ev0"),
        call("kv-cache-manager.evict-blocks", "ev", caller="scheduler", block_ids=[1]),
        take("evE"),
        add("a2", "B", segs=[("doc", 40)], max_tokens=1),
        sched("s2"),
        call("kv-cache-manager.evict-blocks", "bad", caller="scheduler", block_ids=[64]),
    ],
    "expect": [
        "size(steps.ev.result.value.evicted_hashes) == 1 && steps.evE.result.value.events == [{'type': 'BlockRemoved', 'block_hashes': steps.ev.result.value.evicted_hashes, 'medium': 'GPU', 'group_idx': 0}]",
        "// the chain breaks at block 1, so B recomputes its whole prompt\nsteps.s2.result.value.scheduled_new_reqs[0].num_computed_tokens == 0",
        "!steps.bad.result.ok && steps.bad.result.error.message.startsWith('Invalid block_id 64 >= 64.')",
    ],
})

# ------------------------------------------------------------------ NONE_HASH seed warning (judge4 Q4-4 d)
scen.append({
    "id": "scheduler-kv-r6-none-hash-xxhash-warning",
    "name": "xxhash without PYTHONHASHSEED takes a random NONE_HASH seed and logs why; PYTHONHASHSEED silences it",
    "description": "init_none_hash (kv_cache_utils.py:160-172).",
    "fixtures": FX,
    "steps": [
        call("kv-cache-utils.init-none-hash", "xx", hash_fn_name="xxhash_cbor", pythonhashseed=None),
        call("kv-cache-utils.init-none-hash", "seeded", hash_fn_name="xxhash", pythonhashseed="42"),
    ],
    "expect": [
        "steps.xx.result.value.random_seed && trace.exists(e, e.type == 'note' && e.title.startsWith('Using a random per-process NONE_HASH seed because xxhash_cbor is not collision resistant.'))",
        "!steps.seeded.result.value.random_seed && steps.seeded.result.value.seed == '42' && !trace.exists(e, e.type == 'note' && e.title.startsWith('Using a random per-process NONE_HASH seed because xxhash is'))",
    ],
})


scen.append({
    "id": "scheduler-kv-r6-deferred-free-pops-mamba-blocks",
    "name": "Under deferred free a hybrid request's Mamba blocks are popped with its full-attention blocks; none returns to the pool yet",
    "description": "KVCacheCoordinator.pop_blocks_for_free walks every single-type manager (kv_cache_coordinator.py:424-427); MambaManager's pop has the same blocks free would return (single_type_kv_cache_manager.py:1935-1952).",
    "fixtures": FX,
    "state": {"kv-cache-manager": {"kv_cache_groups": [{"name": "attn"}, {"name": "mamba"}]},
              "full-attention-manager": {"req_to_blocks": {"r1": [1, 2]}, "num_cached_block": {"r1": 2}},
              "mamba-manager": {"req_to_blocks": {"r1": [7, 9]}, "num_cached_block": {"r1": 1}}},
    "steps": [call("kv-cache-manager.pop-blocks-for-free", "pop", caller="scheduler", request_id="r1")],
    "expect": [
        "steps.pop.result.value.block_ids == [1, 2, 7, 9]",
        "!('r1' in state['mamba-manager'].req_to_blocks) && !('r1' in state['full-attention-manager'].req_to_blocks)",
        "calls['block-pool.free-blocks'] == 0",
    ],
})


def with_trace(sc):
    last = sc["steps"][-1]
    iface = last.get("interface") or {"scheduler-add-request": "scheduler.add-request", "scheduler-schedule": "scheduler.schedule",
                                      "scheduler-reset-prefix-cache": "scheduler.reset-prefix-cache"}[last["flow"]]
    sc["expect"].append(f"trace.exists(e, e.type == 'call.end' && e.interface == '{iface}')")
    return sc


with open(os.path.join(HERE, "round6_scenarios.yaml"), "w") as f:
    yaml.safe_dump({"scenarios": [with_trace(s) for s in scen]}, f, sort_keys=False, width=100000, allow_unicode=False)
print("r6 ok", len(scen), file=sys.stderr)
