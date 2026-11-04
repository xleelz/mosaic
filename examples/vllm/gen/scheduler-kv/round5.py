"""Round-5 scenarios: the round-4 blind findings (judge3, oracle3), the precision sweep, the new
model-type worlds, and the six round-5 unit tests (build-oracle/round5/scheduler-kv.json).

Writes:
  - gen/scheduler-kv/round5_scenarios.yaml: appended to the fragment by build.sh (ids scheduler-kv-r5-*);
  - build-oracle/round5/scheduler-kv.yaml: the translated tests under oracle ids
    (oracle-r5-scheduler-kv-<n>), to run against the merged model.
"""

import copy
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.normpath(os.path.join(HERE, "..", ".."))

FX = ["tp1-llama-8b"]


def call(iface, as_, caller="engine-core", **inp):
    return {"interface": iface, "caller": caller, "as": as_, "input": inp}


def flow(name, as_, **inp):
    return {"flow": name, "as": as_, "input": inp}


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


def update(as_, s_as, tokens_expr):
    """update-from-output for the step `s_as`; tokens_expr maps each scheduled id to its tokens."""
    return {"interface": "scheduler.update-from-output", "caller": "engine-core", "as": as_, "input": {
        "scheduler_output": f"= steps.{s_as}.result.value",
        "model_runner_output": {
            "req_ids": f"= steps.{s_as}.result.value.num_scheduled_tokens.transformList(k, v, k)",
            "sampled_token_ids": f"= steps.{s_as}.result.value.num_scheduled_tokens.transformList(k, v, {tokens_expr})",
        }}}


def mm(ident, offset, length):
    return {"identifier": ident, "modality": "image", "offset": offset, "length": length}


ENC2048 = {"scheduler": {"max_num_encoder_input_tokens": 2048},
           "encoder-cache-manager": {"cache_size": 2048, "num_free_slots": 2048, "num_freeable_slots": 2048,
                                     "cached": {}, "num_embeds_by_hash": {}, "request_cached_ids": {},
                                     "freeable": [], "freed": []}}

scen = []

# ------------------------------------------------------------------ judge3 wrong claims
# W1 / Q3-7 (d): deferred waiting requests are reported as skipped, not waiting.
LORA = lambda n, i: {"lora_name": n, "lora_int_id": i, "lora_path": f"/models/lora/{n}"}
scen.append({
    "id": "scheduler-kv-r5-stats-split-deferred-waiting",
    "name": "Judge3 Q3-7 (d): a request max_loras holds back is deferred; SchedulerStats count it as skipped, not waiting, until it is admitted",
    "description": "skip_request adds the request to deferred_waiting (scheduler.py:904-910); make_stats reports num_waiting_reqs = waiting - deferred and num_skipped_waiting_reqs = deferred (2944-2948); admission discards it (1344).",
    "fixtures": FX,
    "config": {"enable-lora": True, "max-loras": 1, "async-scheduling": False},
    "steps": [
        add("a1", "a", segs=[("doc-a", 40)], max_tokens=2, lora_request=LORA("sql", 1)),
        sched("s1"),
        update("u1", "s1", "[7]"),
        add("a2", "b", segs=[("doc-b", 40)], lora_request=LORA("chat", 2)),
        sched("s2"),
        {"flow": "scheduler-make-stats", "as": "st2", "input": {}},
        update("u2", "s2", "[7]"),
        sched("s3"),
        {"flow": "scheduler-make-stats", "as": "st3", "input": {}},
    ],
    "expect": [
        "steps.s2.result.value.num_scheduled_tokens == {'a': 1}",
        "steps.st2.result.value.num_waiting_reqs == 0 && steps.st2.result.value.num_skipped_waiting_reqs == 1",
        "steps.s3.result.value.num_scheduled_tokens == {'b': 40}",
        "steps.st3.result.value.num_waiting_reqs == 0 && steps.st3.result.value.num_skipped_waiting_reqs == 0",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-grammar-wait-counts-as-deferred",
    "name": "A structured-output request waiting for its grammar is deferred from the moment it is added",
    "description": "_enqueue_waiting_request adds a request in a blocked waiting status (WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR) to deferred_waiting (scheduler.py:2436-2462).",
    "fixtures": FX,
    "steps": [
        add("a1", "g1", toks=[128000, 9906, 1917], sampling_params={"max_tokens": 4, "structured_outputs": {"json": {"type": "object"}}}),
        {"flow": "scheduler-make-stats", "as": "st", "input": {}},
    ],
    "expect": [
        "steps.a1.result.value.status == 'WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR'",
        "steps.st.result.value.num_waiting_reqs == 0 && steps.st.result.value.num_skipped_waiting_reqs == 1",
    ],
})
# W2 / Q3-4 (a): prompt logprobs skip reading the prefix cache and record no stats.
scen.append({
    "id": "scheduler-kv-r5-prompt-logprobs-skip-prefix-cache",
    "name": "Judge3 Q3-4 (a): a prompt_logprobs request recomputes a fully cached prompt and adds no prefix-cache queries",
    "description": "skip_reading_prefix_cache defaults to prompt_logprobs is not None (sampling_params.py:622-629); get_computed_blocks returns no hit (kv_cache_manager.py:280-287) and record_prefix_cache_stats ignores the request (253-256).",
    "fixtures": FX,
    "config": {"async-scheduling": False},
    "steps": [
        add("a0", "r0", segs=[("doc-x", 100)], max_tokens=4),
        sched("s0"),
        {"flow": "scheduler-finish-requests", "as": "f0", "input": {"request_ids": ["r0"], "finished_status": "FINISHED_STOPPED"}},
        {"flow": "scheduler-make-stats", "as": "st0", "input": {}},
        add("a1", "r1", segs=[("doc-x", 100)], sampling_params={"max_tokens": 4, "prompt_logprobs": 1}),
        sched("s1"),
        {"flow": "scheduler-make-stats", "as": "st1", "input": {}},
        add("a2", "r2", segs=[("doc-x", 100)], sampling_params={"max_tokens": 4, "prompt_logprobs": 1, "skip_reading_prefix_cache": False}),
        sched("s2"),
        {"flow": "scheduler-make-stats", "as": "st2", "input": {}},
    ],
    "expect": [
        "steps.s1.result.value.num_scheduled_tokens == {'r1': 100}",
        "steps.st1.result.value.prefix_cache_stats.queries == 0 && steps.st1.result.value.prefix_cache_stats.requests == 0",
        "// an explicit skip_reading_prefix_cache=False keeps the lookup: 96 of 100 hit\nsteps.s2.result.value.num_scheduled_tokens == {'r2': 4} && steps.st2.result.value.prefix_cache_stats.hits == 96",
    ],
})
# W3: adaptive long-prefill floor (Q3-1 d).
scen.append({
    "id": "scheduler-kv-r5-adaptive-long-prefill-floor",
    "name": "Judge3 Q3-1 (d): with long_prefill_token_threshold_adaptive the 512 cap is floored at 2048 // 2 = 1024 per request",
    "description": "scheduler.py:650-655: max(long_prefill_token_threshold, input_budget // num_eligible_reqs).",
    "fixtures": FX,
    "config": {"max-num-batched-tokens": 2048, "long-prefill-token-threshold": 512, "long-prefill-token-threshold-adaptive": True},
    "steps": [
        add("a1", "p1", segs=[("doc-p1", 3000)]),
        add("a2", "p2", segs=[("doc-p2", 3000)]),
        sched("s1"),
    ],
    "expect": ["steps.s1.result.value.num_scheduled_tokens == {'p1': 1024, 'p2': 1024}"],
})
scen.append({
    "id": "scheduler-kv-r5-adaptive-long-prefill-off-by-default",
    "name": "Without the adaptive flag the 512 cap applies as is",
    "fixtures": FX,
    "config": {"max-num-batched-tokens": 2048, "long-prefill-token-threshold": 512},
    "steps": [
        add("a1", "p1", segs=[("doc-p1", 3000)]),
        add("a2", "p2", segs=[("doc-p2", 3000)]),
        sched("s1"),
    ],
    "expect": ["steps.s1.result.value.num_scheduled_tokens == {'p1': 512, 'p2': 512}"],
})
# W3: encoder-input scheduling (Q3-8, P3-8).
P1_MM = [mm("p1-img0", 8, 800), mm("p1-img1", 808, 800), mm("p1-img2", 1608, 800)]
scen.append({
    "id": "scheduler-kv-r5-encoder-budget-stops-chunk-before-image",
    "name": "Judge3 Q3-8 (b, c): images 1 and 2 use 1600 of the 2048 encoder budget, so chunk 1 stops before image 3 (1608); step 2 frees them, encodes image 3 and completes the prefill (892)",
    "description": "_try_schedule_encoder_inputs cuts num_new_tokens to start_pos - num_computed_tokens when can_allocate fails (scheduler.py:1922-1941); _free_encoder_inputs drops processed items after the step (2151-2153, 2531-2543); the third allocation evicts the oldest unreferenced entry (encoder_cache_manager.py:194-206).",
    "fixtures": FX,
    "config": {"max-num-batched-tokens": 2048, "async-scheduling": False},
    "state": copy.deepcopy(ENC2048),
    "steps": [
        add("a1", "p1", segs=[("p1-text0", 8), ("p1-img0", 800), ("p1-img1", 800), ("p1-img2", 800), ("p1-text1", 92)], mm_features=P1_MM),
        sched("s1"),
        update("u1", "s1", "[]"),
        sched("s2"),
    ],
    "expect": [
        "steps.s1.result.value.num_scheduled_tokens == {'p1': 1608} && steps.s1.result.value.scheduled_encoder_inputs == {'p1': [0, 1]}",
        "steps.s2.result.value.num_scheduled_tokens == {'p1': 892} && steps.s2.result.value.scheduled_encoder_inputs == {'p1': [2]}",
        "steps.s2.result.value.free_encoder_mm_hashes == ['p1-img0']",
        "trace.exists(e, e.type == 'call.end' && e.interface == 'encoder-cache-manager.can-allocate' && !e.output.can_allocate)",
    ],
})
P2_MM = [mm("p2-img0", 1500, 800)]
scen.append({
    "id": "scheduler-kv-r5-encoder-whole-item-then-reuse",
    "name": "Judge3 Q3-8 (d): by default chunk 1 (2048) encodes the whole image though only 548 placeholders are in it; chunk 2 (352) reuses the cached output",
    "fixtures": FX,
    "config": {"max-num-batched-tokens": 2048, "async-scheduling": False},
    "state": copy.deepcopy(ENC2048),
    "steps": [
        add("a1", "p2", segs=[("p2-text0", 1500), ("p2-img0", 800), ("p2-text1", 100)], mm_features=P2_MM),
        sched("s1"),
        update("u1", "s1", "[]"),
        sched("s2"),
    ],
    "expect": [
        "steps.s1.result.value.num_scheduled_tokens == {'p2': 2048} && steps.s1.result.value.scheduled_encoder_inputs == {'p2': [0]}",
        "steps.s2.result.value.num_scheduled_tokens == {'p2': 352} && steps.s2.result.value.scheduled_encoder_inputs == {}",
        "trace.exists(e, e.type == 'call.end' && e.interface == 'encoder-cache-manager.check-and-update-cache' && e.output.cached)",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-encoder-no-chunked-mm-input-rolls-back",
    "name": "Judge3 Q3-8 (d): with --disable-chunked-mm-input chunk 1 rolls back to the 1500 text tokens, chunk 2 takes the whole image and the rest (900)",
    "description": "scheduler.py:1866-1881.",
    "fixtures": FX,
    "config": {"max-num-batched-tokens": 2048, "async-scheduling": False, "disable-chunked-mm-input": True},
    "state": copy.deepcopy(ENC2048),
    "steps": [
        add("a1", "p2", segs=[("p2-text0", 1500), ("p2-img0", 800), ("p2-text1", 100)], mm_features=P2_MM),
        sched("s1"),
        update("u1", "s1", "[]"),
        sched("s2"),
    ],
    "expect": [
        "steps.s1.result.value.num_scheduled_tokens == {'p2': 1500} && steps.s1.result.value.scheduled_encoder_inputs == {}",
        "steps.s2.result.value.num_scheduled_tokens == {'p2': 900} && steps.s2.result.value.scheduled_encoder_inputs == {'p2': [0]}",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-encoder-refs-freed-on-finish-and-preempt",
    "name": "Judge3 P3-8 (d) / W5: a finished request and a preempted request both release their encoder-cache references",
    "description": "_free_request and _preempt_request call encoder_cache_manager.free (scheduler.py:2734, 1590).",
    "fixtures": FX,
    "config": {"max-num-batched-tokens": 2048, "async-scheduling": False},
    "state": copy.deepcopy(ENC2048),
    "steps": [
        add("a1", "m1", segs=[("m1-text", 8), ("m1-img", 600), ("m1-tail", 8)], mm_features=[mm("m1-img", 8, 600)], max_tokens=1),
        add("a2", "m2", segs=[("m2-text", 8), ("m2-img", 400), ("m2-tail", 8)], mm_features=[mm("m2-img", 8, 400)], max_tokens=4),
        sched("s1"),
        call("encoder-cache-manager.get-state", "before", caller="scheduler"),
        call("scheduler.preempt-request", "pre", request_id="m2"),
        {"flow": "scheduler-finish-requests", "as": "f1", "input": {"request_ids": ["m1"], "finished_status": "FINISHED_ABORTED"}},
        call("encoder-cache-manager.get-state", "after", caller="scheduler"),
    ],
    "expect": [
        "steps.s1.result.value.scheduled_encoder_inputs == {'m1': [0], 'm2': [0]} && steps.before.result.value.num_free_slots == 1048",
        "steps.after.result.value.num_freeable_slots == 2048 && size(steps.after.result.value.request_cached_ids) == 0",
        "steps.after.result.value.cached == {'m1-img': [], 'm2-img': []}",
    ],
})
# W4 / Q3-6 (d), W5: reset_prefix_cache drops stale output; preemption marks it stale and records an event.
scen.append({
    "id": "scheduler-kv-r5-preempted-stale-output-defers-resume",
    "name": "Judge3 W3/W5: under async scheduling a preempted request with output still in flight is skipped (deferred) until that output drains, which also delivers it with the PREEMPTED event",
    "description": "_preempt_request marks num_in_flight_tokens stale and records PREEMPTED (scheduler.py:1596-1610); the waiting loop skips a request with deliverable stale output (934-938); update_from_output drains it in lockstep and still delivers the tokens (2079-2087); EngineCoreOutput takes the request's events (2276).",
    "fixtures": FX,
    "config": {"async-scheduling": True},
    "steps": [
        add("a1", "r1", toks=[128000, 9906, 1917, 13], max_tokens=8),
        sched("s1"),
        call("scheduler.preempt-request", "pre", request_id="r1"),
        sched("s2"),
        {"flow": "scheduler-make-stats", "as": "st2", "input": {}},
        update("u1", "s1", "[42]"),
        sched("s3"),
    ],
    "expect": [
        "steps.pre.result.value.num_stale_output_tokens == 4",
        "steps.s2.result.value.num_scheduled_tokens == {} && steps.st2.result.value.num_skipped_waiting_reqs == 1",
        "steps.u1.result.value.outputs[0].new_token_ids == [42] && steps.u1.result.value.outputs[0].events.map(e, e.type) == ['QUEUED', 'SCHEDULED', 'PREEMPTED']",
        "steps.s3.result.value.num_scheduled_tokens == {'r1': 5}",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-reset-running-drops-stale-output",
    "name": "Judge3 Q3-6 (d): reset_prefix_cache(reset_running_requests) preempts with drop_stale_output, so the requests resume at once and the in-flight tokens are discarded",
    "description": "scheduler.py:2850-2866 (drop_stale_output=True, prev_step_scheduled_req_ids cleared); update_from_output discards drop-mode stale output (2101-2103).",
    "fixtures": FX,
    "config": {"async-scheduling": True},
    "steps": [
        add("a1", "a", toks=[128000, 9906, 1917, 13], max_tokens=8),
        sched("s1"),
        call("scheduler.reset-prefix-cache", "r", reset_running_requests=True),
        sched("s2"),
        update("u1", "s1", "[42]"),
    ],
    "expect": [
        "steps.r.result.value.reset",
        "steps.s2.result.value.num_scheduled_tokens == {'a': 4}",
        "steps.u1.result.value.outputs == []",
        "trace.exists(e, e.type == 'call.start' && e.interface == 'scheduler.preempt-request' && e.input.drop_stale_output)",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-reset-connector-without-connector",
    "name": "reset_connector with no KV connector configured counts as success",
    "description": "reset_connector_cache returns True when self.connector is None (scheduler.py:2885-2895).",
    "fixtures": FX,
    "steps": [call("scheduler.reset-prefix-cache", "r", reset_connector=True)],
    "expect": ["steps.r.result.value.reset"],
})
scen.append({
    "id": "scheduler-kv-r5-reset-failure-message",
    "name": "Precision: the RuntimeError text when the reset still fails after preempting everything",
    "description": "scheduler.py:2868-2874. A block still held by another owner (here a request waiting for remote KV, outside running) keeps the reset from succeeding.",
    "fixtures": FX,
    "state": {"block-pool": {"ref_cnt": {"7": 1}, "next_fresh": 8}},
    "steps": [call("scheduler.reset-prefix-cache", "r", reset_running_requests=True)],
    "expect": ["steps.r.result.error.code == 'runtime-error' && steps.r.result.error.message == 'Failed to reset KV cache even when all the running requests are preempted and moved to the waiting queue. This is likely due to the presence of running requests waiting for remote KV transfer, which is not supported yet.'"],
})

# ------------------------------------------------------------------ oracle3: P2P tier
scen.append({
    "id": "scheduler-kv-r5-p2p-tier-seed-resolved-lazily",
    "name": "Oracle3: the P2P tier is built with no seed; the first session resolves get_none_hash_seed (the default with PYTHONHASHSEED unset) and advertises it",
    "description": "manager.py:306-314 (lazy), 689-693, 724-732 (local_hash_seed).",
    "fixtures": FX,
    "steps": [
        call("secondary-tier-factory.create-secondary-tier", "tier", tier_id="p2p-0", tier_config={"type": "p2p", "module_path": None, "backpressure": None}),
        call("kv-cache-utils.init-none-hash", "init", hash_fn_name="sha256", pythonhashseed=None),
        call("p2p-secondary-tier-manager.get-or-create-session", "sess", caller="scheduler", tier_id="p2p-0", peer_id="10.0.0.1:8000"),
        call("p2p-secondary-tier-manager.get-hash-seed", "seed", caller="scheduler", tier_id="p2p-0"),
    ],
    "expect": [
        "steps.tier.result.value.class_name == 'P2PSecondaryTierManager'",
        "steps.sess.result.value.created && steps.sess.result.value.local_hash_seed == 'vllm-none-hash'",
        "steps.seed.result.value.seed == 'vllm-none-hash'",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-p2p-tier-rejects-backpressure",
    "name": "Precision: a P2P tier with a backpressure config is rejected with the code's message",
    "description": "manager.py:276-290.",
    "fixtures": FX,
    "steps": [call("secondary-tier-factory.create-secondary-tier", "tier", tier_id="p2p-0",
                   tier_config={"type": "p2p", "module_path": None, "backpressure": {"backpressure_cls": "EMABackpressureDetector"}})],
    "expect": ["steps.tier.result.error.code == 'value-error' && steps.tier.result.error.message.startsWith('Backpressure is not supported for the P2P secondary tier.')"],
})
scen.append({
    "id": "scheduler-kv-r5-p2p-consumer-finish-routes-by-peer",
    "name": "A consumer-side (remote_prefiller) finish routes to the session by peer id",
    "description": "test_manager.py: the consumer branch of on_request_finished (manager.py:469-473).",
    "fixtures": FX,
    "state": {"p2p-secondary-tier-manager": {"tiers": {"p2p-0": {"tier_type": "p2p", "local_id": "localhost:5710", "hash_seed": None,
        "sessions": {"10.0.0.1:8000": {"connected": True, "local_hash_seed": "vllm-none-hash", "finished": []}},
        "kv_to_session": {}, "failed_req_ids": ["req-1"], "unbound_stores": {}, "unbound_store_timeout_s": 60.0}}}},
    "steps": [call("p2p-secondary-tier-manager.on-request-finished", "f", caller="scheduler", tier_id="p2p-0",
                   kv_transfer_params={"remote_prefiller": {"kv_request_id": "req-1", "remote_host": "10.0.0.1", "remote_port": 8000}})],
    "expect": [
        "steps.f.result.value.finished_on == '10.0.0.1:8000'",
        "state['p2p-secondary-tier-manager'].tiers['p2p-0'].sessions['10.0.0.1:8000'].finished == ['req-1'] && state['p2p-secondary-tier-manager'].tiers['p2p-0'].failed_req_ids == []",
    ],
})

# ------------------------------------------------------------------ worlds
scen.append({
    "id": "scheduler-kv-r5-vl-world-encoder-cache-sized",
    "name": "VL world: Qwen2-VL's largest item (16384 tokens) raises the encoder budget and cache above max_num_batched_tokens (8192), and an image request is encoded in its first chunk",
    "description": "compute_mm_encoder_budget (encoder_cache_manager.py:356-363) at scheduler init (scheduler.py:257-285). The largest item is the default max_pixels 12845056 / (28*28) = 16384 tokens (qwen2_vl.py:1079-1138). The world variant scheduler-kv-vl-qwen2-vl-7b seeds the result.",
    "fixtures": ["full-vl-qwen2-vl-7b"],
    "config": {"async-scheduling": False},
    "steps": [
        call("scheduler.init-encoder-cache", "init", mm_max_toks_per_item={"image": 16384, "video": 16384}),
        add("a1", "v1", segs=[("v1-sys", 14), ("v1-img", 1196), ("v1-q", 20)], mm_features=[mm("v1-img", 14, 1196)]),
        sched("s1"),
    ],
    "expect": [
        "steps.init.result.value == {'max_num_encoder_input_tokens': 16384, 'encoder_cache_size': 16384}",
        "steps.s1.result.value.num_scheduled_tokens == {'v1': 1230} && steps.s1.result.value.scheduled_encoder_inputs == {'v1': [0]}",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-vl-world-seeded-budget",
    "name": "VL world: the merged world starts with the encoder cache sized for Qwen2-VL (16384), the Llama default (0) left behind",
    "description": "The variant fixture is named explicitly so the scenario doesn't depend on worlds.yaml listing it.",
    "fixtures": ["full-vl-qwen2-vl-7b", "scheduler-kv-vl-qwen2-vl-7b"],
    "config": {"async-scheduling": False},
    "steps": [
        add("a1", "v1", segs=[("v1-sys", 14), ("v1-img", 1196), ("v1-q", 20)], mm_features=[mm("v1-img", 14, 1196)]),
        sched("s1"),
        call("encoder-cache-manager.get-state", "ecm", caller="scheduler"),
    ],
    "expect": [
        "steps.s1.result.value.scheduled_encoder_inputs == {'v1': [0]}",
        "steps.ecm.result.value.cache_size == 16384 && steps.ecm.result.value.num_free_slots == 16384 - 1196",
    ],
})
scen.append({
    "id": "scheduler-kv-r5-text-world-has-no-encoder-budget",
    "name": "Text-only Llama: no MultiModalBudget, so the encoder budget and cache are 0 and an image item could never be scheduled",
    "fixtures": FX,
    "steps": [call("scheduler.init-encoder-cache", "init")],
    "expect": ["steps.init.result.value == {'max_num_encoder_input_tokens': 0, 'encoder_cache_size': 0}"],
})
scen.append({
    "id": "scheduler-kv-r5-mm-budget-rejects-unchunkable-item",
    "name": "Precision: with --disable-chunked-mm-input an item larger than max_num_batched_tokens is a ValueError with the code's message",
    "fixtures": ["full-vl-qwen2-vl-7b"],
    "config": {"disable-chunked-mm-input": True},
    "steps": [call("encoder-cache-manager.compute-mm-encoder-budget", "b", caller="scheduler", mm_max_toks_per_item={"image": 16384, "video": 16384})],
    "expect": ["steps.b.result.error.code == 'value-error' && steps.b.result.error.message == 'Chunked MM input disabled but max_tokens_per_mm_item (16384) is larger than max_num_batched_tokens (8192). Please increase max_num_batched_tokens.'"],
})
scen.append({
    "id": "scheduler-kv-r5-fp8-kv-world-doubles-blocks",
    "name": "FP8 KV world: with --kv-cache-dtype fp8 a block takes half the bytes (1 byte per element), so the same memory holds twice the blocks",
    "description": "get_kv_cache_configs: num_blocks = available_memory // (page_size_bytes * num_layers) (kv_cache_utils.py:1230-1260); the fp8 page is 2 * 16 * 8 * 128 * 1 bytes (cache.py:122-126, torch_utils.py:518-519). The page size comes from the worker's get_kv_cache_spec (worker-runner).",
    "fixtures": ["full-fp8-llama-3-8b-kv-fp8"],
    "steps": [
        call("kv-cache-utils.get-kv-cache-configs", "auto", available_memory=[59742896128], bytes_per_block=2 * 16 * 8 * 128 * 2 * 32),
        call("kv-cache-utils.get-kv-cache-configs", "fp8", available_memory=[59742896128], bytes_per_block=2 * 16 * 8 * 128 * 1 * 32),
    ],
    "expect": ["// both counts leave out the null block\nsteps.fp8.result.value.num_blocks + 1 == 2 * (steps.auto.result.value.num_blocks + 1)"],
})


# ------------------------------------------------------------------ precision sweep
MSG_SEQ = ("To serve at least one request with the model's max seq len (131072), (16.0 GiB KV cache is needed, which is larger than the available KV cache memory (8.0 GiB). "
           "Based on the available memory, the estimated maximum model length is 65520. Try increasing `gpu_memory_utilization` (which also controls CPU memory on the CPU backend) "
           "or decreasing `max_model_len` when initializing the engine. See https://docs.vllm.ai/en/latest/configuration/conserving_memory/ for more details.")
MSG_NOMEM = ("No available memory for the cache blocks. Try increasing `gpu_memory_utilization` when initializing the engine (this flag also controls CPU memory reservation on the CPU "
             "backend, despite its name). See https://docs.vllm.ai/en/latest/configuration/conserving_memory/ for more details.")
def q(m):
    return "'" + m.replace("\\", "\\\\").replace("'", "\\'") + "'"
scen.append({
    "id": "scheduler-kv-r5-precision-max-seq-len-message",
    "name": "Precision: the max-seq-len ValueError word for word (format_gib rounding, the memory after the null block, the binary-searched estimate)",
    "description": "kv_cache_utils.py:1019-1040, 2627-2647; mem_utils.py:30-31.",
    "fixtures": FX,
    "config": {"max-model-len": 131072},
    "steps": [call("kv-cache-utils.get-kv-cache-configs", "kvc", available_memory=[8589934592], bytes_per_block=2097152)],
    "expect": ["steps.kvc.result.error.code == 'value-error' && steps.kvc.result.error.message == " + q(MSG_SEQ)],
})
scen.append({
    "id": "scheduler-kv-r5-precision-no-memory-message",
    "name": "Precision: no memory left after the null block is the 'No available memory' ValueError, word for word",
    "fixtures": FX,
    "steps": [call("kv-cache-utils.get-kv-cache-configs", "kvc", available_memory=[1048576], bytes_per_block=2097152)],
    "expect": ["steps.kvc.result.error.code == 'value-error' && steps.kvc.result.error.message == " + q(MSG_NOMEM)],
})
scen.append({
    "id": "scheduler-kv-r5-precision-block-pool-bare-assert",
    "name": "Precision: BlockPool(0) trips a bare assert (AssertionError with no message)",
    "description": "block_pool.py:166.",
    "fixtures": FX,
    "steps": [call("block-pool.init", "bp", caller="kv-cache-manager", num_gpu_blocks=0)],
    "expect": ["steps.bp.result.error.code == 'assertion-error' && steps.bp.result.error.message == ''"],
})
scen.append({
    "id": "scheduler-kv-r5-precision-outlines-messages",
    "name": "Precision: the outlines backreference message (with the code's double period and its hint) and the invalid request type (the enum's str)",
    "description": "backend_outlines.py:350-356 wraps the ValueError; 73-76 formats StructuredOutputOptions with !s.",
    "fixtures": FX,
    "steps": [
        call("backend-outlines.validate-regex-is-buildable", "br", caller="scheduler", pattern="(a)\\1"),
        call("backend-outlines.compile-grammar", "cg", caller="scheduler", grammar_id="g1", request_type="grammar", grammar_spec="root ::= 'a'"),
        call("xgrammar-backend.compile-grammar", "xg", caller="scheduler", grammar_id="g2", request_type="choice", grammar_spec="[\"a\"]"),
    ],
    "expect": [
        "steps.br.result.error.status == 400 && steps.br.result.error.message == 'Regex uses unsupported feature for structured outputs: Backreferences are unsupported.. Only basic matching constructs are supported\u2014lookarounds, backreferences, and unicode boundaries are not.'",
        "steps.cg.result.error.message == 'Invalid request type for Outlines backend (StructuredOutputOptions.GRAMMAR)'",
        "steps.xg.result.error.message == 'grammar is not of valid supported types. (StructuredOutputOptions.CHOICE)'",
    ],
})

# ------------------------------------------------------------------ round-5 unit tests
tests = []
P2P_TIER = lambda sessions, kv_to_session: {"p2p-secondary-tier-manager": {"tiers": {"p2p-0": {
    "tier_type": "p2p", "local_id": "localhost:5710", "hash_seed": None, "sessions": sessions,
    "kv_to_session": kv_to_session, "failed_req_ids": [], "unbound_stores": {}, "unbound_store_timeout_s": 60.0}}}}
tests.append({"n": 1, "test": "tests/v1/kv_offload/tiering/p2p/test_manager.py:578 TestOnRequestFinished.test_prefiller_bound_id_routes_via_kv_to_session", "scenario": {
    "name": "A prefiller-side finish for an id already bound to a session routes through _kv_to_session and pops the entry",
    "fixtures": FX,
    "state": P2P_TIER({"some-peer:1": {"connected": True, "local_hash_seed": "vllm-none-hash", "finished": []}}, {"req-1": "some-peer:1"}),
    "steps": [call("p2p-secondary-tier-manager.on-request-finished", "f", caller="scheduler", tier_id="p2p-0",
                   kv_transfer_params={"remote_decoder": {"kv_request_id": "req-1"}})],
    "expect": [
        "steps.f.result.value.finished_on == 'some-peer:1'",
        "// the fake session's finishes and the manager's map are what the test reads\nstate['p2p-secondary-tier-manager'].tiers['p2p-0'].sessions['some-peer:1'].finished == ['req-1']",
        "!('req-1' in state['p2p-secondary-tier-manager'].tiers['p2p-0'].kv_to_session)",
    ]}})
tests.append({"n": 2, "test": "tests/v1/core/test_scheduler.py:7263 test_encoder_instance_finishes_request_once_prompt_is_consumed", "scenario": {
    "name": "An encoder-only instance encodes the image and finishes the request in one step, with no sampled tokens",
    "description": "The EC producer makes the instance mm_encoder_only (vllm.py:2778-2790); the test gives the encoder cache 8 * 16 = 128 slots and the budget 128. The EC connector's has_cache_item is false, so the item is encoded locally.",
    "fixtures": FX,
    "config": {"max-num-seqs": 8, "max-num-batched-tokens": 1024, "mm-encoder-only": True, "enable-prefix-caching": False, "async-scheduling": False},
    "state": {"scheduler": {"max_num_encoder_input_tokens": 128},
              "encoder-cache-manager": {"cache_size": 128, "num_free_slots": 128, "num_freeable_slots": 128, "cached": {}, "num_embeds_by_hash": {}, "request_cached_ids": {}, "freeable": [], "freed": []}},
    "steps": [
        add("a", "0", toks=list(range(28)), max_tokens=16, mm_features=[{"identifier": "img-hash-0", "modality": "image", "offset": 8, "length": 16}]),
        sched("s1"),
        update("u1", "s1", "[]"),
    ],
    "expect": [
        "steps.s1.result.value.scheduled_encoder_inputs['0'] == [0] && steps.s1.result.value.num_scheduled_tokens['0'] == 28",
        "steps.u1.result.value.outputs[0].finish_reason == 'stop' && steps.u1.result.value.outputs[0].new_token_ids == []",
    ]}})
SW_POOL = lambda cached: {"block-pool": {"num_gpu_blocks": 10, "next_fresh": 4, "free_front": [], "free_tail": [3, 2, 1],
                                          "ref_cnt": {}, "block_hash": {str(b): h for h, b in cached.items()}, "cached": cached,
                                          "hash_tokens": {}, "kv_event_queue": []}}
tests.append({"n": 3, "test": "tests/v1/core/test_prefix_caching.py:4255 test_eagle_with_sliding_window", "scenario": {
    "name": "Sliding window (16) with EAGLE: two cached full blocks give a one-block hit (EAGLE drops the last)",
    "description": "Priming (allocate 2 full blocks + 5 tokens, then free) is given as the cache it leaves: the two full blocks' hashes cached in blocks 1 and 2. The eviction half of the test is -3b.",
    "fixtures": FX,
    "config": {"block-size": 16},
    "state": SW_POOL({"h0": 1, "h1": 2}),
    "steps": [call("sliding-window-manager.find-longest-cache-hit", "hit", caller="kv-cache-manager",
                   block_hashes=["h0", "h1"], max_length=36, sliding_window=16, use_eagle=True)],
    "expect": ["size(steps.hit.result.value.block_ids) == 1 && steps.hit.result.value.hit_length == 16"]}})
tests.append({"n": "3b", "test": "tests/v1/core/test_prefix_caching.py:4255 test_eagle_with_sliding_window (after the first block is evicted)", "scenario": {
    "name": "Sliding window with EAGLE: with the first block evicted, [null, block 2] minus EAGLE's dropped block is no hit",
    "fixtures": FX,
    "config": {"block-size": 16},
    "state": SW_POOL({"h1": 2}),
    "steps": [call("sliding-window-manager.find-longest-cache-hit", "hit", caller="kv-cache-manager",
                   block_hashes=["h0", "h1"], max_length=36, sliding_window=16, use_eagle=True)],
    "expect": ["size(steps.hit.result.value.block_ids) == 0 && steps.hit.result.value.hit_length == 0"]}})


def no_chunk(warm):
    steps = [call("scheduler.init-encoder-cache", "init", mm_max_toks_per_item={"image": 576})]
    if warm:
        steps += [
            call("encoder-cache-manager.allocate", "prime", caller="scheduler", request_id="cache-primer", input_id=0, mm_hash="llava-img", num_embeds=800),
            call("encoder-cache-manager.free", "unprime", caller="scheduler", request_id="cache-primer", mm_hashes=["llava-img"]),
        ]
    steps += [
        add("a", "0", toks=list(range(1200)), max_tokens=16, mm_features=[{"identifier": "llava-img", "modality": "image", "offset": 400, "length": 800}]),
        sched("s1"),
        update("u1", "s1", "[]"),
        sched("s2"),
        call("scheduler.get-request-counts", "c2", caller="engine-core"),
        call("encoder-cache-manager.compute-mm-encoder-budget", "small", caller="scheduler", mm_max_toks_per_item={"image": 576}, max_num_batched_tokens=100),
    ]
    exp = [
        "size(steps.s1.result.value.scheduled_new_reqs) == 1 && size(steps.s1.result.value.scheduled_cached_reqs.req_ids) == 0 && size(steps.s1.result.value.finished_req_ids) == 0",
        "steps.s1.result.value.num_scheduled_tokens['0'] == 400",
        "steps.c2.result.value.num_running == 1 && size(steps.s2.result.value.scheduled_new_reqs) == 0 && size(steps.s2.result.value.scheduled_cached_reqs.req_ids) == 1 && size(steps.s2.result.value.finished_req_ids) == 0",
        "steps.s2.result.value.num_scheduled_tokens['0'] == 800",
        "steps.small.result.error.code == 'value-error'",
    ]
    if warm:
        exp.append("size(steps.s2.result.value.scheduled_encoder_inputs) == 0")
    return {
        "name": f"No MM input chunking ({'warm' if warm else 'cold'} encoder cache): the 400 text tokens first, then the whole 800-token image; a 100-token batch can't hold a 576-token item",
        "description": "llava-1.5's image is 576 tokens, so the budget and cache are max(1024, 576) = 1024. The image is given 800 placeholder tokens, as in the test.",
        "fixtures": FX,
        "config": {"max-num-batched-tokens": 1024, "disable-chunked-mm-input": True, "max-model-len": 2048, "enable-prefix-caching": False, "async-scheduling": False},
        "steps": steps, "expect": exp}
tests.append({"n": 4, "test": "tests/v1/core/test_scheduler.py:745 test_no_mm_input_chunking[False]", "scenario": no_chunk(False)})
tests.append({"n": "4b", "test": "tests/v1/core/test_scheduler.py:745 test_no_mm_input_chunking[True]", "scenario": no_chunk(True)})
tests.append({"n": 5, "test": "tests/v1/core/test_scheduler.py:3943 test_priority_scheduling_waiting_queue_order", "scenario": {
    "name": "Priority policy with max_num_seqs 1: the priority-0 request runs; the waiting queue iterates 1, 2, 0 (priorities 1, 2, 3)",
    "fixtures": FX,
    "config": {"scheduling-policy": "priority", "max-num-seqs": 1, "enable-prefix-caching": False, "async-scheduling": False},
    "steps": [add(f"a{i}", str(i), toks=[i] * 10, max_tokens=16, priority=p, arrival_time=t)
              for i, (p, t) in enumerate(zip([3, 1, 2, 0], [1.0, 2.0, 3.0, 4.0]))] + [
        sched("s1"),
        call("scheduler.iter-waiting", "w", caller="engine-core"),
    ],
    "expect": [
        "size(steps.s1.result.value.scheduled_new_reqs) == 1 && steps.s1.result.value.scheduled_new_reqs[0].req_id == '3'",
        "size(steps.w.result.value.request_ids) == 3",
        "steps.w.result.value.request_ids == ['1', '2', '0'] && steps.w.result.value.priorities == [1, 2, 3]",
    ]}})


def leak():
    steps = []
    for i in range(5):
        steps += [add(f"a{i}", str(i), toks=[i + 1] * 10, max_tokens=10), sched(f"s{i}"), update(f"u{i}", f"s{i}", "[0]")]
    for i in range(5, 14):
        steps += [sched(f"s{i}"), update(f"u{i}", f"s{i}", "[0]")]
    steps += [sched("s14"),
              call("scheduler.get-request-counts", "c", caller="engine-core"),
              call("block-pool.get-num-free-blocks", "free", caller="kv-cache-manager"),
              call("encoder-cache-manager.get-state", "ecm", caller="scheduler")]
    return {
        "name": "No memory leak: five 10-token requests run to max_tokens 10; afterwards nothing is held",
        "description": "create_scheduler(enable_prefix_caching=True): 10,000 blocks of 16, sync scheduling; make_output samples token 0 for every running request.",
        "fixtures": FX,
        "config": {"enable-prefix-caching": True, "async-scheduling": False, "block-size": 16},
        "state": {"block-pool": {"num_gpu_blocks": 10000, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}, "kv_event_queue": []}},
        "max_events": 100000,
        "steps": steps,
        "expect": [
            "steps.s14.result.value.num_scheduled_tokens == {} && steps.c.result.value == {'num_running': 0, 'num_waiting': 0}",
            "// assert_scheduler_empty reads the scheduler's and the managers' internals (test_scheduler.py:3325-3364)\nsize(state.scheduler.requests) == 0 && size(state.scheduler.finished_req_ids) == 0",
            "size(steps.ecm.result.value.freed) == 0 && size(steps.ecm.result.value.cached) == 0",
            "size(state['full-attention-manager'].req_to_blocks) == 0 && size(state['full-attention-manager'].num_cached_block) == 0",
            "steps.free.result.value.num_free_blocks == 9999 && size(state['block-pool'].ref_cnt) == 0",
        ]}
tests.append({"n": 6, "test": "tests/v1/core/test_scheduler.py:3365 test_memory_leak", "scenario": leak()})


FLOW_ENTRY = {
    "scheduler-add-request": "scheduler.add-request",
    "scheduler-schedule": "scheduler.schedule",
    "scheduler-finish-requests": "scheduler.finish-requests",
    "scheduler-make-stats": "scheduler.make-stats",
}


def with_trace(sc):
    """Write-then-read: the scenario's last step (a read or the write itself) is checked in the trace."""
    last = sc["steps"][-1]
    iface = last.get("interface") or FLOW_ENTRY[last["flow"]]
    sc["expect"].append(f"trace.exists(e, e.type == 'call.end' && e.interface == '{iface}')")
    return sc


frag = []
oracle = []
for t in tests:
    sc = with_trace({"id": f"scheduler-kv-r5-test-{t['n']}", **copy.deepcopy(t["scenario"])})
    sc.setdefault("description", t["test"])
    frag.append(sc)
    o = copy.deepcopy(sc)
    o["id"] = f"oracle-r5-scheduler-kv-{t['n']}"
    o["description"] = t["test"]
    oracle.append(o)
frag.extend(with_trace(sc) for sc in scen)


def dump(path, doc):
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, width=100000, allow_unicode=False)


dump(os.path.join(HERE, "round5_scenarios.yaml"), {"scenarios": frag})
os.makedirs(os.path.join(WS, "build-oracle", "round5"), exist_ok=True)
dump(os.path.join(WS, "build-oracle", "round5", "scheduler-kv.yaml"),
     {"schema_version": 1, "id": "vllm", "scenarios": oracle})
print("r5 ok", len(frag), len(oracle), file=sys.stderr)
