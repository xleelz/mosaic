"""Round-4 scenarios: blind-finding fixes, coverage of the functions the tests call, and the six
round-4 unit tests (build-oracle/round4/scheduler-kv.json).

Writes:
  - gen/scheduler-kv/round4_scenarios.yaml: appended to the fragment by build.sh (ids scheduler-kv-r4-*);
  - build-oracle/round4/scheduler-kv.yaml: the translated tests under oracle ids
    (oracle-r4-scheduler-kv-<n>), to run against the merged model.
"""

import copy
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.normpath(os.path.join(HERE, "..", ".."))

FX = ["tp1-llama-8b"]
P48 = [128000] + list(range(5000, 5047))  # 48 tokens: 3 full blocks
P3 = [128000, 9906, 1917]


def call(iface, as_, caller="engine-core", **inp):
    return {"interface": iface, "caller": caller, "as": as_, "input": inp}


def flow(name, as_, **inp):
    return {"flow": name, "as": as_, "input": inp}


def sp(max_tokens=4, **kw):
    d = {"max_tokens": max_tokens}
    d.update(kw)
    return d


scen = []

# ------------------------------------------------------------------ blind findings
scen.append({
    "id": "scheduler-kv-r4-cache-salt-isolates-prefix",
    "name": "Judge W1/Q8a: a different cache_salt shares no prefix blocks; the same salt does",
    "description": "generate_block_hash_extra_keys puts ('cache_salt', salt) in the first block's hash; the chain carries it on (kv_cache_utils.py:647-650).",
    "fixtures": FX,
    "steps": [
        flow("scheduler-add-request", "a1", request_id="salt-a1", prompt_token_ids=P48, sampling_params=sp(), cache_salt="tenant-a"),
        flow("scheduler-schedule", "s1"),
        flow("scheduler-add-request", "a2", request_id="salt-b1", prompt_token_ids=P48, sampling_params=sp(), cache_salt="tenant-b"),
        flow("scheduler-schedule", "s2"),
        flow("scheduler-add-request", "a3", request_id="salt-a2", prompt_token_ids=P48, sampling_params=sp(), cache_salt="tenant-a"),
        flow("scheduler-schedule", "s3"),
    ],
    "expect": [
        "steps.s1.result.value.num_scheduled_tokens['salt-a1'] == 48",
        "steps.s2.result.value.num_scheduled_tokens['salt-b1'] == 48",
        "steps.s3.result.value.num_scheduled_tokens['salt-a2'] == 16",
        "steps.a1.result.value.num_block_hashes == 3",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-lora-isolates-prefix",
    "name": "Judge W1/Q8b: two LoRA adapters share no prefix blocks; the same adapter does",
    "description": "_gen_lora_extra_hash_keys adds ('lora', name, path) to every block hash (kv_cache_utils.py:578-595).",
    "fixtures": FX,
    "steps": [
        flow("scheduler-add-request", "a1", request_id="lora-a1", prompt_token_ids=P48, sampling_params=sp(),
             lora_request={"lora_name": "sql", "lora_int_id": 1, "lora_path": "/adapters/a"}),
        flow("scheduler-schedule", "s1"),
        flow("scheduler-add-request", "a2", request_id="lora-b1", prompt_token_ids=P48, sampling_params=sp(),
             lora_request={"lora_name": "chat", "lora_int_id": 2, "lora_path": "/adapters/b"}),
        flow("scheduler-schedule", "s2"),
        flow("scheduler-add-request", "a3", request_id="lora-a2", prompt_token_ids=P48, sampling_params=sp(),
             lora_request={"lora_name": "sql", "lora_int_id": 1, "lora_path": "/adapters/a"}),
        flow("scheduler-schedule", "s3"),
        flow("scheduler-add-request", "a4", request_id="base-1", prompt_token_ids=P48, sampling_params=sp()),
        flow("scheduler-schedule", "s4"),
    ],
    "expect": [
        "steps.s2.result.value.num_scheduled_tokens['lora-b1'] == 48",
        "steps.s3.result.value.num_scheduled_tokens['lora-a2'] == 16",
        "steps.s4.result.value.num_scheduled_tokens['base-1'] == 48",
        "steps.s1.result.value.scheduled_new_reqs[0].lora_request.lora_int_id == 1",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-max-loras-gate",
    "name": "Judge L8a: with max_loras 2, a third adapter waits until a scheduled adapter's request leaves",
    "fixtures": FX,
    "config": {"enable-lora": True, "max-loras": 2},
    "steps": [
        flow("scheduler-add-request", "r1", request_id="l1", prompt_token_ids=P3, sampling_params=sp(16), lora_request={"lora_name": "a", "lora_int_id": 1, "lora_path": "/a"}),
        flow("scheduler-add-request", "r2", request_id="l2", prompt_token_ids=P3, sampling_params=sp(16), lora_request={"lora_name": "b", "lora_int_id": 2, "lora_path": "/b"}),
        flow("scheduler-add-request", "r3", request_id="l3", prompt_token_ids=P3, sampling_params=sp(16), lora_request={"lora_name": "c", "lora_int_id": 3, "lora_path": "/c"}),
        flow("scheduler-add-request", "r4", request_id="l4", prompt_token_ids=P3, sampling_params=sp(16), lora_request={"lora_name": "a", "lora_int_id": 1, "lora_path": "/a"}),
        flow("scheduler-schedule", "s1"),
        flow("scheduler-schedule", "s2"),
        flow("scheduler-finish-requests", "f1", request_ids=["l1", "l4"]),
        flow("scheduler-schedule", "s3"),
        call("scheduler.get-request-counts", "counts"),
    ],
    "expect": [
        "steps.s1.result.value.scheduled_new_reqs.map(r, r.req_id) == ['l1', 'l2', 'l4']",
        "!('l3' in steps.s2.result.value.num_scheduled_tokens)",
        "steps.s3.result.value.scheduled_new_reqs.map(r, r.req_id) == ['l3']",
        "steps.counts.result.value.num_waiting == 0 && steps.counts.result.value.num_running == 2",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-grammar-wait-and-promote",
    "name": "Judge L4d/S10: a structured-output request waits for its grammar, is promoted once it compiles, and a failed compile finishes it with an error",
    "description": "Request status WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR (request.py:116-117); promotion and compile errors in _handle_blocked_waiting_request (scheduler.py:3191-3200) and update_from_output (2302-2326).",
    "fixtures": FX,
    "steps": [
        flow("scheduler-add-request", "add", request_id="so-1", prompt_token_ids=P3, sampling_params=sp(8, structured_outputs={"json": {"type": "string"}})),
        flow("scheduler-add-request", "add2", request_id="so-2", prompt_token_ids=P3, sampling_params=sp(8, structured_outputs={"grammar": "root ::= x"})),
        flow("scheduler-schedule", "s1"),
        call("structured-output-manager.grammar-init", "g1", request_id="so-1", backend="xgrammar", request_type="json", grammar_spec='{"type": "string"}'),
        call("structured-output-manager.grammar-init", "g2", request_id="so-2", backend="xgrammar", request_type="bogus", grammar_spec="root ::= x"),
        flow("scheduler-schedule", "s2"),
        call("scheduler.get-grammar-bitmask", "gb1", scheduler_output="= steps.s1.result.value"),
        call("scheduler.get-grammar-bitmask", "gb2", scheduler_output="= steps.s2.result.value"),
        flow("scheduler-update-from-output", "u2", scheduler_output="= steps.s2.result.value", model_runner_output={"req_ids": ["so-1"], "sampled_token_ids": [[1]]}),
        call("scheduler.get-request-counts", "counts"),
    ],
    "expect": [
        "steps.add.result.value.status == 'WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR'",
        "steps.s1.result.value.total_num_scheduled_tokens == 0",
        "steps.g1.result.value.status == 'ready' && steps.g2.result.value.status == 'failed'",
        "steps.s2.result.value.num_scheduled_tokens == {'so-1': 3}",
        "steps.gb1.result.value == null && steps.gb2.result.value.structured_output_request_ids == ['so-1'] && steps.gb2.result.value.num_acceptable_drafts == [0]",
        "steps.u2.result.value.outputs.exists(o, o.request_id == 'so-2' && o.finish_reason == 'error')",
        "steps.counts.result.value.num_waiting == 0 && steps.counts.result.value.num_running == 1",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-spec-decode-stats",
    "name": "Judge P3c: verified drafts are counted in the step's SpecDecodingStats; none when stats are off",
    "fixtures": FX,
    "config": {"speculative-method": "eagle", "num-speculative-tokens": 3, "async-scheduling": False},
    "steps": [
        flow("scheduler-add-request", "add", request_id="sd-1", prompt_token_ids=P3, sampling_params=sp(32)),
        flow("scheduler-schedule", "s1"),
        flow("scheduler-update-from-output", "u1", scheduler_output="= steps.s1.result.value", model_runner_output={"req_ids": ["sd-1"], "sampled_token_ids": [[791]]}),
        call("scheduler.update-draft-token-ids", "d1", req_ids=["sd-1"], draft_token_ids=[[201, 202, 203]]),
        flow("scheduler-schedule", "s2"),
        flow("scheduler-update-from-output", "u2", scheduler_output="= steps.s2.result.value", model_runner_output={"req_ids": ["sd-1"], "sampled_token_ids": [[201, 202, 9]]}),
        call("scheduler.make-spec-decoding-stats", "over", num_draft_tokens=3, num_accepted_tokens=5),
        call("scheduler.make-spec-decoding-stats", "none", num_draft_tokens=0, num_accepted_tokens=0),
    ],
    "expect": [
        "steps.u1.result.value.scheduler_stats.spec_decoding_stats == null",
        "steps.u2.result.value.scheduler_stats.spec_decoding_stats.num_draft_tokens == 3",
        "steps.u2.result.value.scheduler_stats.spec_decoding_stats.num_accepted_tokens == 2",
        "steps.u2.result.value.scheduler_stats.spec_decoding_stats.num_accepted_tokens_per_pos == [1, 1, 0]",
        "steps.over.result.error.code == 'assertion-error' && steps.none.result.value == null",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-stats-off",
    "name": "With --disable-log-stats the scheduler builds no SchedulerStats and no spec-decoding stats",
    "fixtures": FX,
    "config": {"disable-log-stats": True},
    "steps": [
        call("scheduler.make-stats", "st"),
        call("scheduler.make-spec-decoding-stats", "sd", num_draft_tokens=3, num_accepted_tokens=1),
    ],
    "expect": ["steps.st.result.value == null && steps.sd.result.value == null"],
})
scen.append({
    "id": "scheduler-kv-r4-new-request-data-prefill",
    "name": "Judge W2: NewRequestData carries prefill_token_ids for token prompts and the prompt length for segment prompts",
    "fixtures": FX,
    "steps": [
        flow("scheduler-add-request", "a1", request_id="tok-1", prompt_token_ids=P3, sampling_params=sp()),
        flow("scheduler-add-request", "a2", request_id="seg-1", prompt_segments=[{"key": "doc", "num_tokens": 40}], sampling_params=sp()),
        flow("scheduler-schedule", "s1"),
    ],
    "expect": [
        "steps.s1.result.value.scheduled_new_reqs.filter(r, r.req_id == 'tok-1')[0].prefill_token_ids == [128000, 9906, 1917]",
        "!has(steps.s1.result.value.scheduled_new_reqs.filter(r, r.req_id == 'seg-1')[0].prefill_token_ids)",
        "steps.s1.result.value.scheduled_new_reqs.filter(r, r.req_id == 'seg-1')[0].num_prompt_tokens == 40",
        "steps.s1.result.value.scheduled_new_reqs.filter(r, r.req_id == 'seg-1')[0].num_prefill_tokens == 40",
    ],
})

# ------------------------------------------------------------------ encoder cache
EC = "encoder-cache-manager"
scen.append({
    "id": "scheduler-kv-r4-encoder-cache-lifecycle",
    "name": "Encoder cache: share an item, free it to freeable, evict oldest-first on demand, and reset to full capacity",
    "fixtures": FX,
    "steps": [
        call(f"{EC}.init", "init", caller="scheduler", cache_size=20),
        call(f"{EC}.check-and-update-cache", "miss", caller="scheduler", request_id="r1", input_id=0, mm_hash="img1"),
        call(f"{EC}.can-allocate", "budget", caller="scheduler", request_id="r1", input_id=0, num_embeds=30, encoder_compute_budget=16),
        call(f"{EC}.can-allocate", "fits", caller="scheduler", request_id="r1", input_id=0, num_embeds=5, encoder_compute_budget=100),
        call(f"{EC}.allocate", "al1", caller="scheduler", request_id="r1", input_id=0, mm_hash="img1", num_embeds=5),
        call(f"{EC}.allocate", "al2", caller="scheduler", request_id="r2", input_id=0, mm_hash="img2", num_embeds=3),
        call(f"{EC}.allocate", "mismatch", caller="scheduler", request_id="r2", input_id=1, mm_hash="img1", num_embeds=7),
        call(f"{EC}.check-and-update-cache", "hit", caller="scheduler", request_id="r3", input_id=0, mm_hash="img1"),
        call(f"{EC}.free-encoder-input", "f_shared", caller="scheduler", request_id="r1", input_id=0, mm_hashes=["img1"]),
        call(f"{EC}.free", "f_r3", caller="scheduler", request_id="r3", mm_hashes=["img1"]),
        call(f"{EC}.free-encoder-input", "f_again", caller="scheduler", request_id="r3", input_id=0, mm_hashes=["img1"]),
        call(f"{EC}.free-encoder-input", "f_r2", caller="scheduler", request_id="r2", input_id=0, mm_hashes=["img2"]),
        call(f"{EC}.check-and-update-cache", "reclaim", caller="scheduler", request_id="r4", input_id=0, mm_hash="img2"),
        call(f"{EC}.can-allocate", "too_big", caller="scheduler", request_id="r5", input_id=0, num_embeds=20, encoder_compute_budget=100),
        call(f"{EC}.can-allocate", "evict", caller="scheduler", request_id="r5", input_id=0, num_embeds=15, encoder_compute_budget=100),
        call(f"{EC}.allocate", "full", caller="scheduler", request_id="r6", input_id=0, mm_hash="img9", num_embeds=30),
        call(f"{EC}.get-freed-mm-hashes", "freed", caller="scheduler"),
        call(f"{EC}.get-state", "before", caller="scheduler"),
        call("scheduler.reset-encoder-cache", "reset"),
        call(f"{EC}.get-state", "after", caller="scheduler"),
    ],
    "expect": [
        "!steps.miss.result.value.cached && !steps.budget.result.value.can_allocate && steps.fits.result.value.can_allocate",
        "steps.mismatch.result.error.code == 'assertion-error' && steps.full.result.error.code == 'assertion-error'",
        "steps.hit.result.value.cached && !steps.f_shared.result.value.freeable && steps.f_r3.result.value.released == 1 && !steps.f_again.result.value.freeable",
        "steps.f_r2.result.value.freeable && steps.reclaim.result.value.cached",
        "!steps.too_big.result.value.can_allocate && steps.evict.result.value.evicted == ['img1'] && steps.freed.result.value.freed == ['img1']",
        "steps.before.result.value.num_free_slots == 17 && steps.before.result.value.num_freeable_slots == 17",
        "steps.reset.result.value.num_free_slots == 20 && size(steps.after.result.value.cached) == 0 && size(steps.after.result.value.request_cached_ids) == 0",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-encoder-cache-same-item-twice",
    "name": "A request holding the same image at two inputs keeps it referenced until both are freed",
    "fixtures": FX,
    "steps": [
        call(f"{EC}.init", "init", caller="scheduler", cache_size=10),
        call(f"{EC}.allocate", "a0", caller="scheduler", request_id="r1", input_id=0, mm_hash="img1", num_embeds=4),
        call(f"{EC}.check-and-update-cache", "a1", caller="scheduler", request_id="r1", input_id=1, mm_hash="img1"),
        call(f"{EC}.free-encoder-input", "f0", caller="scheduler", request_id="r1", input_id=0, mm_hashes=["img1", "img1"]),
        call(f"{EC}.free-encoder-input", "f1", caller="scheduler", request_id="r1", input_id=1, mm_hashes=["img1", "img1"]),
        call(f"{EC}.get-state", "st", caller="scheduler"),
    ],
    "expect": [
        "!steps.f0.result.value.freeable && steps.f1.result.value.freeable",
        "steps.st.result.value.num_freeable_slots == 10 && steps.st.result.value.num_free_slots == 6",
    ],
})

# ------------------------------------------------------------------ block pool / hashing / config
scen.append({
    "id": "scheduler-kv-r4-free-queue-append",
    "name": "FreeKVCacheBlockQueue.append returns a block to the free tail; appending a free block is refused",
    "fixtures": FX,
    "state": {"block-pool": {"num_gpu_blocks": 6, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}}},
    "steps": [
        call("block-pool.get-new-blocks", "take", caller="kv-cache-manager", num_blocks=3),
        call("block-pool.free-queue-append", "app", caller="kv-cache-manager", block_id=2),
        call("block-pool.free-queue-append", "dup", caller="kv-cache-manager", block_id=2),
        call("block-pool.get-num-free-blocks", "free", caller="kv-cache-manager"),
        call("block-pool.get-new-blocks", "take2", caller="kv-cache-manager", num_blocks=3),
    ],
    "expect": [
        "steps.take.result.value.block_ids == [1, 2, 3] && steps.app.result.value.num_free_blocks == 3",
        "steps.dup.result.error.code == 'runtime-error' && steps.free.result.value.num_free_blocks == 3",
        "steps.take2.result.value.block_ids == [4, 5, 2]",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-none-hash-seed",
    "name": "NONE_HASH seed: deterministic for SHA-256, random for xxhash, PYTHONHASHSEED wins, unknown algorithms refused",
    "fixtures": FX,
    "steps": [
        call("kv-cache-utils.get-none-hash-seed", "pre", caller="engine-core"),
        call("kv-cache-utils.init-none-hash", "sha", caller="engine-core"),
        call("kv-cache-utils.get-none-hash-seed", "after_sha", caller="engine-core"),
        call("kv-cache-utils.init-none-hash", "xx", caller="engine-core", hash_fn_name="xxhash"),
        call("kv-cache-utils.init-none-hash", "env", caller="engine-core", hash_fn_name="xxhash_cbor", pythonhashseed="42"),
        call("kv-cache-utils.get-none-hash-seed", "after_env", caller="engine-core"),
        call("kv-cache-utils.init-none-hash", "bad", caller="engine-core", hash_fn_name="md5"),
    ],
    "expect": [
        "steps.pre.result.value.seed == 'vllm-none-hash' && steps.after_sha.result.value.seed == 'vllm-none-hash' && !steps.sha.result.value.random_seed",
        "steps.xx.result.value.random_seed && steps.xx.result.value.seed != 'vllm-none-hash'",
        "steps.after_env.result.value.seed == '42' && !steps.env.result.value.random_seed",
        "steps.bad.result.error.code == 'value-error'",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-kv-cache-config-from-groups",
    "name": "KVCacheConfig from groups: blocks = memory // largest group's bytes per block (or the override), an attention-free model gets one block, and offload registration follows the layout",
    "fixtures": FX,
    "steps": [
        call("kv-cache-utils.get-kv-cache-config-from-groups", "none", caller="engine-core", kv_cache_groups=[], available_memory=1000),
        call("kv-cache-utils.get-kv-cache-config-from-groups", "blk", caller="engine-core", layout="BLNHC",
             kv_cache_groups=[{"layer_names": ["l0", "l1"], "layer_pages": {"l0": 100, "l1": 100}}], available_memory=1000),
        call("simple-cpu-offload-worker.register-kv-caches", "reg_blk", caller="engine-core", num_blocks="= steps.blk.result.value.num_blocks",
             kv_cache_tensors="= steps.blk.result.value.kv_cache_tensors", layer_names=["l0", "l1"]),
        call("simple-cpu-offload-worker.register-kv-caches", "reg_none", caller="engine-core", num_blocks=1, kv_cache_tensors=[], layer_names=[]),
    ],
    "expect": [
        "steps.none.result.value.num_blocks == 1",
        "steps.blk.result.value.num_blocks == 5 && steps.blk.result.value.kv_cache_tensors[0].block_stride == 200",
        "steps.reg_blk.result.value.regions == {'l0': [5, 200]} && steps.reg_none.result.value.regions == {}",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-kv-cache-config-override",
    "name": "--num-gpu-blocks-override replaces the computed block count",
    "fixtures": FX,
    "config": {"num-gpu-blocks-override": 7},
    "steps": [
        call("kv-cache-utils.get-kv-cache-config-from-groups", "ov", caller="engine-core",
             kv_cache_groups=[{"layer_names": ["l0"], "layer_pages": {"l0": 100}}], available_memory=1000),
    ],
    "expect": ["steps.ov.result.value.num_blocks == 7 && steps.ov.result.value.kv_cache_tensors[0].layer_stride == 700"],
})

# ------------------------------------------------------------------ offloading specs
scen.append({
    "id": "scheduler-kv-r4-offloading-spec-factory",
    "name": "Offloading spec factory: default CPU spec, registered and out-of-tree specs, duplicates and unknown specs refused",
    "fixtures": FX,
    "steps": [
        call("offloading-spec-factory.get-spec-cls", "dflt", caller="engine-core", extra_config={}),
        call("offloading-spec-factory.get-spec-cls", "tier", caller="engine-core", extra_config={"spec_name": "TieringOffloadingSpec"}),
        call("offloading-spec-factory.get-spec-cls", "unk", caller="engine-core", extra_config={"spec_name": "Nope"}),
        call("offloading-spec-factory.get-spec-cls", "oot", caller="engine-core", extra_config={"spec_name": "MySpec", "spec_module_path": "my_pkg.spec"}),
        call("offloading-spec-factory.register-spec", "dup", caller="engine-core", name="CPUOffloadingSpec", module_path="x", class_name="X"),
        call("offloading-spec-factory.register-spec", "reg", caller="engine-core", name="MySpec", module_path="my_pkg.spec", class_name="MySpec"),
        call("offloading-spec-factory.get-spec-cls", "after", caller="engine-core", extra_config={"spec_name": "MySpec"}),
        call("offloading-spec-factory.create-spec", "mk_tier", caller="engine-core", extra_config={"spec_name": "TieringOffloadingSpec", "cpu_bytes_to_use": 4096}),
    ],
    "expect": [
        "steps.dflt.result.value.spec_cls == 'CPUOffloadingSpec' && steps.tier.result.value.module_path == 'vllm.v1.kv_offload.tiering.spec'",
        "steps.unk.result.error.code == 'value-error' && steps.unk.result.error.message == 'Unsupported spec type: Nope'",
        "steps.oot.result.value.out_of_tree && steps.dup.result.error.code == 'value-error'",
        "!steps.after.result.value.out_of_tree && steps.mk_tier.result.value.num_chunks == null",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-cpu-spec-sizing",
    "name": "CPU spec sizing: page-aligned rows, the replicated single-copy layout, an empty cache without worker bytes, and the required cpu_bytes_to_use",
    "fixtures": FX,
    "steps": [
        call("offloading-spec-factory.create-spec", "mk", caller="engine-core", extra_config={"cpu_bytes_to_use": 1048576}, worker_kv_bytes_per_block=2048, blocks_per_chunk=4, world_size=2),
        call("cpu-offloading-spec.get-manager", "mgr", caller="engine-core"),
        call("cpu-offloading-manager.get-stats", "mstats", caller="engine-core"),
        call("cpu-offloading-spec.create-worker", "wk", caller="engine-core", rank=1),
        call("shared-offload-region.create-next-worker-view", "view", caller="engine-core", tensor_page_size=8192),
        call("cpu-offloading-spec.init", "repl", caller="engine-core", cpu_bytes_to_use=1048576, worker_kv_bytes_per_block=2048, blocks_per_chunk=4, world_size=2, replicated_layout=True),
        call("cpu-offloading-spec.init", "zero", caller="engine-core", cpu_bytes_to_use=4096, worker_kv_bytes_per_block=0, world_size=4),
        call("cpu-offloading-spec.create-worker", "wk0", caller="engine-core"),
        call("cpu-offloading-spec.init", "missing", caller="engine-core", worker_kv_bytes_per_block=16),
    ],
    "expect": [
        "steps.mk.result.value.num_chunks == 64 && steps.mstats.result.value.num_free_chunks == 64",
        "steps.wk.result.value.shared_region && steps.view.result.value.storage_offset == 8192",
        "steps.repl.result.value.replicated_layout && steps.repl.result.value.kv_bytes_per_chunk == 8192 && steps.repl.result.value.num_chunks == 128",
        "steps.zero.result.value.num_chunks == 0 && steps.zero.result.value.cpu_page_size_per_worker == 0 && !steps.wk0.result.value.shared_region",
        "steps.missing.result.error.code == 'exception'",
    ],
})

# ------------------------------------------------------------------ CPU offloading manager
CM = "cpu-offloading-manager"
scen.append({
    "id": "scheduler-kv-r4-cpu-offload-store-load-evict",
    "name": "CPU offload tier: stores are pending until complete, LRU eviction never takes the offered keys, loads pin chunks",
    "fixtures": FX,
    "steps": [
        call(f"{CM}.init", "init", caller="engine-core", num_chunks=2, enable_events=True),
        call(f"{CM}.on-new-request", "nr", caller="engine-core", req_id="q1"),
        call(f"{CM}.prepare-store", "ps1", caller="engine-core", keys=["a", "b"], req_id="q1"),
        call(f"{CM}.lookup", "pend", caller="engine-core", key="a", req_id="q1"),
        call(f"{CM}.prepare-load", "notready", caller="engine-core", keys=["a"], req_id="q1"),
        call(f"{CM}.complete-store", "cs1", caller="engine-core", keys=["a", "b"], req_id="q1"),
        call(f"{CM}.lookup", "hit", caller="engine-core", key="a", req_id="q1"),
        call(f"{CM}.lookup", "miss", caller="engine-core", key="zz", req_id="q1"),
        call(f"{CM}.prepare-store", "again", caller="engine-core", keys=["a"], req_id="q1"),
        call(f"{CM}.prepare-store", "prot", caller="engine-core", keys=["a", "b", "c"], req_id="q1"),
        call(f"{CM}.prepare-load", "pin", caller="engine-core", keys=["a"], req_id="q1"),
        call(f"{CM}.prepare-store", "full", caller="engine-core", keys=["c", "d"], req_id="q1"),
        call(f"{CM}.prepare-store", "ev", caller="engine-core", keys=["c"], req_id="q1"),
        call(f"{CM}.complete-load", "unpin", caller="engine-core", keys=["a"], req_id="q1"),
        call(f"{CM}.complete-load", "unpin2", caller="engine-core", keys=["a"], req_id="q1"),
        call(f"{CM}.prepare-load", "gone", caller="engine-core", keys=["b"], req_id="q1"),
        call(f"{CM}.complete-store", "fail", caller="engine-core", keys=["c"], req_id="q1", success=False),
        call(f"{CM}.get-stats", "st", caller="engine-core"),
        call(f"{CM}.take-events", "ev1", caller="engine-core"),
        call(f"{CM}.take-events", "ev2", caller="engine-core"),
    ],
    "expect": [
        "steps.ev1.result.value.events.map(e, e.removed) == [false, true] && size(steps.ev2.result.value.events) == 0",
        "steps.nr.result.value.policy == 'chunk_level' && steps.ps1.result.value.chunk_ids == [0, 1]",
        "steps.pend.result.value.result == 'HIT_PENDING' && steps.notready.result.error.code == 'assertion-error'",
        "steps.cs1.result.value.stored == ['a', 'b'] && steps.hit.result.value.result == 'HIT' && steps.miss.result.value.result == 'MISS'",
        "steps.again.result.value.keys_to_store == [] && steps.prot.result.value == null && steps.full.result.value == null",
        "steps.ev.result.value.evicted_keys == ['b'] && steps.ev.result.value.chunk_ids == [1]",
        "steps.unpin.result.value.evictable == ['a'] && steps.unpin2.result.error.code == 'assertion-error' && steps.gone.result.error.code == 'assertion-error'",
        "steps.fail.result.value.removed == ['c'] && steps.st.result.value.num_free_chunks == 1 && steps.st.result.value.num_stored == 1",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-cpu-offload-recency",
    "name": "CPU offload recency: touch and request finish refresh LRU order (the first key becomes the most recent); reset starts a new generation",
    "fixtures": FX,
    "steps": [
        call(f"{CM}.init", "init", caller="engine-core", num_chunks=3),
        call(f"{CM}.prepare-store", "ps", caller="engine-core", keys=["a", "b", "c"], req_id="q1"),
        call(f"{CM}.complete-store", "cs", caller="engine-core", keys=["a", "b", "c"], req_id="q1"),
        call(f"{CM}.touch", "t", caller="engine-core", keys=["a", "b", "zz"], req_id="q2"),
        call(f"{CM}.on-request-finished", "fin", caller="engine-core", req_id="q1"),
        call(f"{CM}.on-request-finished", "fin2", caller="engine-core", req_id="q1"),
        call(f"{CM}.prepare-store", "ev", caller="engine-core", keys=["d"], req_id="q3"),
        call(f"{CM}.reset-cache", "rs", caller="engine-core"),
        call(f"{CM}.get-stats", "st", caller="engine-core"),
    ],
    "expect": [
        "steps.t.result.value.lru == ['c', 'b', 'a']",
        "steps.fin.result.value.finalized && !steps.fin2.result.value.finalized",
        "steps.ev.result.value.evicted_keys == ['c']",
        "steps.rs.result.value.cache_generation == 1 && steps.st.result.value.num_stored == 0 && steps.st.result.value.num_free_chunks == 3",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-cpu-offload-worker",
    "name": "The CPU offload worker queues stores and loads and reports them finished in order with their sizes",
    "fixtures": FX,
    "steps": [
        call("cpu-offloading-worker.submit-store", "st", caller="engine-core", job_id=1, src_block_ids=[3, 4], dst_chunk_ids=[0]),
        call("cpu-offloading-worker.submit-load", "ld", caller="engine-core", job_id=2, src_chunk_ids=[0], dst_block_ids=[7], bytes_per_block=1024),
        call("cpu-offloading-worker.get-finished", "fin", caller="engine-core"),
        call("cpu-offloading-worker.get-finished", "fin2", caller="engine-core"),
    ],
    "expect": [
        "steps.fin.result.value.results.map(r, r.job_id) == [1, 2] && steps.fin.result.value.results[0].transfer_size == 4194304 && steps.fin.result.value.results[1].transfer_size == 1024",
        "size(steps.fin2.result.value.results) == 0",
    ],
})

# ------------------------------------------------------------------ tiering
TM = "tiering-offloading-manager"
XT = "example-secondary-tier-manager"
scen.append({
    "id": "scheduler-kv-r4-tiering-cascade-and-promote",
    "name": "Tiered offload: a completed store cascades to the secondary tier; after the primary forgets it, a lookup promotes it back (HIT_PENDING, then HIT)",
    "fixtures": FX,
    "steps": [
        call(f"{CM}.init", "pinit", caller="engine-core", num_chunks=2),
        call("secondary-tier-factory.create-secondary-tier", "t0", caller="engine-core", tier_id="tier0", tier_config={"type": "example"}),
        call(f"{TM}.init", "init", caller="engine-core", secondary_tiers=["tier0"]),
        call(f"{TM}.on-new-request", "nr", caller="engine-core", req_id="q1"),
        call(f"{TM}.prepare-store", "ps", caller="engine-core", keys=["k1"], req_id="q1"),
        call(f"{TM}.on-request-finished", "early", caller="engine-core", req_id="q1"),
        call(f"{TM}.complete-store", "cs", caller="engine-core", keys=["k1"], req_id="q1"),
        call(f"{CM}.get-stats", "pinned", caller="engine-core"),
        call(f"{TM}.on-schedule-end", "end1", caller="engine-core"),
        call(f"{CM}.get-stats", "unpinned", caller="engine-core"),
        call(f"{XT}.get-num-chunks", "n0", caller="engine-core", tier_id="tier0"),
        call(f"{TM}.lookup", "phit", caller="engine-core", key="k1", req_id="q2"),
        call(f"{CM}.reset-cache", "forget", caller="engine-core"),
        call(f"{TM}.lookup", "promo", caller="engine-core", key="k1", req_id="q2"),
        call(f"{TM}.lookup", "inflight", caller="engine-core", key="k1", req_id="q2"),
        call(f"{TM}.lookup", "none", caller="engine-core", key="k9", req_id="q2"),
        call(f"{TM}.on-schedule-end", "end2", caller="engine-core"),
        call(f"{TM}.on-schedule-end", "end3", caller="engine-core"),
        call(f"{TM}.lookup", "back", caller="engine-core", key="k1", req_id="q2"),
        call(f"{TM}.on-request-finished", "fin", caller="engine-core", req_id="q1"),
        call(f"{TM}.on-request-finished", "unknown", caller="engine-core", req_id="zz"),
    ],
    "expect": [
        "steps.t0.result.value.class_name == 'ExampleSecondaryTierManager' && steps.nr.result.value.policy == 'chunk_level'",
        "!steps.early.result.value.finalized && steps.cs.result.value.cascaded_to == ['tier0'] && steps.pinned.result.value.num_evictable == 0",
        "steps.end1.result.value.finished_jobs == 1 && steps.unpinned.result.value.num_evictable == 1 && steps.n0.result.value.num_chunks == 1",
        "steps.phit.result.value.result == 'HIT' && steps.promo.result.value.result == 'HIT_PENDING' && steps.inflight.result.value.result == 'HIT_PENDING' && steps.none.result.value.result == 'MISS'",
        "steps.end2.result.value.promotions_submitted == 1 && steps.end3.result.value.finished_jobs == 1 && steps.back.result.value.result == 'HIT'",
        "steps.fin.result.value.finalized && !steps.unknown.result.value.finalized",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-tiering-full-primary-and-failures",
    "name": "Tiered offload edge cases: a full primary refuses stores and promotions, a failed promotion drops its slot, and an unknown finished job is an assertion",
    "fixtures": FX,
    "steps": [
        call(f"{CM}.init", "pinit", caller="engine-core", num_chunks=1),
        call("secondary-tier-factory.create-secondary-tier", "t0", caller="engine-core", tier_id="tier0", tier_config={"type": "example"}),
        call(f"{TM}.init", "init", caller="engine-core", secondary_tiers=["tier0"]),
        call(f"{XT}.submit-store", "seed", caller="engine-core", tier_id="tier0", job_id=50, keys=["x1"], chunk_ids=[0]),
        call(f"{XT}.get-finished-jobs", "drain", caller="engine-core", tier_id="tier0"),
        call(f"{TM}.on-new-request", "nr", caller="engine-core", req_id="q1"),
        call(f"{TM}.prepare-store", "ps", caller="engine-core", keys=["k1"], req_id="q1"),
        call(f"{TM}.prepare-store", "refused", caller="engine-core", keys=["k2"], req_id="q1"),
        call(f"{TM}.lookup", "nopromo", caller="engine-core", key="x1", req_id="q1"),
        call(f"{TM}.complete-store", "csfail", caller="engine-core", keys=["k1"], req_id="q1", success=False),
        call(f"{XT}.submit-store", "orphan", caller="engine-core", tier_id="tier0", job_id=99, keys=["y"], chunk_ids=[0]),
        call(f"{TM}.on-schedule-end", "bad", caller="engine-core"),
    ],
    "expect": [
        "steps.ps.result.value.chunk_ids == [0] && steps.refused.result.value == null",
        "steps.nopromo.result.value.result == 'MISS' && steps.csfail.result.value.cascaded_to == []",
        "steps.bad.result.error.code == 'assertion-error'",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-tiering-failed-promotion",
    "name": "A promotion whose key vanished from the tier fails, and the reserved primary slot is freed",
    "fixtures": FX,
    "steps": [
        call(f"{CM}.init", "pinit", caller="engine-core", num_chunks=2),
        call(f"{XT}.init", "t0", caller="engine-core", tier_id="tier0", tier_type="example"),
        call(f"{TM}.init", "init", caller="engine-core", secondary_tiers=["tier0"]),
        call(f"{XT}.submit-store", "seed", caller="engine-core", tier_id="tier0", job_id=70, keys=["k1"], chunk_ids=[0]),
        call(f"{XT}.get-finished-jobs", "drain", caller="engine-core", tier_id="tier0"),
        call(f"{TM}.lookup", "promo", caller="engine-core", key="k1", req_id="q1"),
        call(f"{XT}.init", "wipe", caller="engine-core", tier_id="tier0", tier_type="example"),
        call(f"{TM}.on-schedule-end", "end1", caller="engine-core"),
        call(f"{TM}.on-schedule-end", "end2", caller="engine-core"),
        call(f"{CM}.lookup", "after", caller="engine-core", key="k1"),
    ],
    "expect": [
        "steps.promo.result.value.result == 'HIT_PENDING' && steps.end1.result.value.promotions_submitted == 1",
        "steps.end2.result.value.finished_jobs == 1 && steps.after.result.value.result == 'MISS'",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-secondary-tier-factory",
    "name": "Secondary-tier factory: registration, type resolution, out-of-tree tiers and the configuration errors",
    "fixtures": FX,
    "steps": [
        call("secondary-tier-factory.register-tier", "reg", caller="engine-core", tier_type="nvme", module_path="vllm.v1.kv_offload.tiering.example.manager", class_name="ExampleSecondaryTierManager"),
        call("secondary-tier-factory.create-secondary-tier", "mk", caller="engine-core", tier_id="t-nvme", tier_config={"type": "nvme", "custom_param": 99}),
        call("secondary-tier-factory.get-tier-class", "notype", caller="engine-core", tier_config={}),
        call("secondary-tier-factory.get-tier-class", "unknown", caller="engine-core", tier_config={"type": "nonexistent_tier"}),
        call("secondary-tier-factory.get-tier-class", "oot", caller="engine-core", tier_config={"type": "MyTier", "module_path": "my_pkg.tiers"}),
        call("secondary-tier-factory.create-secondary-tier", "fs", caller="engine-core", tier_id="t-fs", tier_config={"type": "fs"}),
        call("secondary-tier-factory.create-secondary-tier", "bp", caller="engine-core", tier_id="t-bp", tier_config={"type": "example", "backpressure": {"alpha": 0.5}}),
        call(f"{XT}.lookup", "notier", caller="engine-core", tier_id="t-fs", key="k"),
        call(f"{XT}.get-num-chunks", "n", caller="engine-core", tier_id="t-nvme"),
    ],
    "expect": [
        "steps.mk.result.value.tier_type == 'nvme' && steps.mk.result.value.class_name == 'ExampleSecondaryTierManager' && steps.n.result.value.num_chunks == 0",
        "steps.notype.result.error.code == 'value-error' && steps.notype.result.error.message.contains(\"must include 'type'\")",
        "steps.unknown.result.error.message.matches('Unknown secondary tier type.*also set .module_path.')",
        "steps.oot.result.value.class_name == 'MyTier' && steps.fs.result.value.class_name == 'FileSystemTierManager'",
        "steps.bp.result.error.code == 'value-error' && steps.notier.result.error.code == 'key-error'",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-example-tier-jobs",
    "name": "Example tier: stores complete at once, a load of a missing key fails its job, mismatched lengths are assertions, drain has nothing in flight",
    "fixtures": FX,
    "steps": [
        call(f"{XT}.init", "t0", caller="engine-core", tier_id="tier0", tier_type="example", primary_row_stride=16),
        call(f"{XT}.submit-store", "st", caller="engine-core", tier_id="tier0", job_id=1, keys=["a", "b"], chunk_ids=[0, 1]),
        call(f"{XT}.submit-store", "bad_st", caller="engine-core", tier_id="tier0", job_id=2, keys=["a"], chunk_ids=[0, 1]),
        call(f"{XT}.submit-load", "ld", caller="engine-core", tier_id="tier0", job_id=3, keys=["a"], chunk_ids=[2]),
        call(f"{XT}.submit-load", "ld_miss", caller="engine-core", tier_id="tier0", job_id=4, keys=["a", "z"], chunk_ids=[2, 3]),
        call(f"{XT}.submit-load", "bad_ld", caller="engine-core", tier_id="tier0", job_id=5, keys=["a"], chunk_ids=[]),
        call(f"{XT}.drain-jobs", "dr", caller="engine-core", tier_id="tier0"),
        call(f"{XT}.get-finished-jobs", "jobs", caller="engine-core", tier_id="tier0"),
        call(f"{XT}.on-new-request", "nr", caller="engine-core", tier_id="tier0", req_id="q"),
    ],
    "expect": [
        "steps.t0.result.value.block_size_bytes == 16 && steps.t0.result.value.cache_hit_source == 'HOST'",
        "steps.bad_st.result.error.code == 'assertion-error' && steps.bad_ld.result.error.code == 'assertion-error'",
        "steps.ld.result.value.success && !steps.ld_miss.result.value.success && steps.dr.result.value.pending == 3",
        "steps.jobs.result.value.jobs.map(j, j.success) == [true, true, false] && steps.nr.result.value.policy == 'chunk_level'",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-zmq-monitor-fatal-events",
    "name": "P2P control plane: a disconnected or closed monitor event marks the connection dead, other events do not, and a dead connection refuses sends",
    "fixtures": FX,
    "steps": [
        call("zmq-transport.fatal-monitor-events", "old", caller="engine-core", pyzmq_has_handshake_events=False),
        call("zmq-transport.connect", "c1", caller="engine-core", peer_id="10.0.0.2:5555"),
        call("zmq-transport.connect", "c2", caller="engine-core", peer_id="10.0.0.3:5555"),
        call("zmq-transport.connect", "c3", caller="engine-core", peer_id="10.0.0.4:5555"),
        call("zmq-transport.send", "ok", caller="engine-core", peer_id="10.0.0.2:5555", msg={"type": "hello"}),
        call("zmq-transport.check-monitors", "mon", caller="engine-core", events={
            "10.0.0.2:5555": ["EVENT_CONNECTED", "EVENT_DISCONNECTED"],
            "10.0.0.3:5555": ["EVENT_CONNECTED"],
            "10.0.0.4:5555": ["EVENT_CLOSED"]}),
        call("zmq-transport.send", "dead", caller="engine-core", peer_id="10.0.0.2:5555", msg={"type": "hello"}),
        call("zmq-transport.send", "alive", caller="engine-core", peer_id="10.0.0.3:5555", msg={"type": "hello"}),
    ],
    "expect": [
        "steps.old.result.value.events == ['EVENT_DISCONNECTED', 'EVENT_CLOSED']",
        "steps.ok.result.value.sent && steps.mon.result.value.dead == ['10.0.0.2:5555', '10.0.0.4:5555']",
        "steps.dead.result.error.code == 'runtime-error' && steps.alive.result.value.sent",
    ],
})

# ------------------------------------------------------------------ round-4 unit tests
DSA_LAYERS = [f"model.layers.{i}.self_attn.{k}" for i in range(4) for k in ("attn", "indexer.k_cache")]
MLA_PAGE = 64 * 1 * (512 + 64)
IDX_PAGE = 64 * 1 * (128 + 4)
PAGES = {n: (MLA_PAGE if n.endswith(".attn") else IDX_PAGE) for n in DSA_LAYERS}

tests = []
tests.append({
    "n": 1,
    "test": "tests/v1/kv_offload/tiering/test_factory.py:164 test_duplicate_registration_raises",
    "scenario": {
        "name": "Registering an already registered tier type raises ValueError",
        "fixtures": FX,
        "steps": [call("secondary-tier-factory.register-tier", "dup", caller="engine-core", tier_type="example", module_path="some.module", class_name="SomeClass")],
        "expect": ["steps.dup.result.error.code == 'value-error' && steps.dup.result.error.message.contains('is already registered')"],
    },
})
tests.append({
    "n": 2,
    "test": "tests/v1/core/test_kv_cache_utils.py:2355 test_allocate_with_lookahead",
    "scenario": {
        "name": "Lookahead tokens count toward the blocks allocated: 3 new + 2 or 4 lookahead tokens at block size 4 need 2 blocks",
        "fixtures": FX,
        "config": {"block-size": 4, "max-model-len": 100},
        "state": {"block-pool": {"num_gpu_blocks": 10, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}}},
        "steps": [
            call("kv-cache-manager.allocate-slots", "c1", caller="scheduler", request_id="0", status="WAITING", num_computed_tokens=0, num_tokens=0, num_new_tokens=3, num_lookahead_tokens=2),
            call("kv-cache-manager.allocate-slots", "c2", caller="scheduler", request_id="0b", status="WAITING", num_computed_tokens=0, num_tokens=0, num_new_tokens=3, num_lookahead_tokens=2),
            call("kv-cache-manager.allocate-slots", "c3", caller="scheduler", request_id="0c", status="WAITING", num_computed_tokens=0, num_tokens=0, num_new_tokens=3, num_lookahead_tokens=4),
            call("kv-cache-manager.get-block-ids", "ids", caller="scheduler", request_id="0"),
        ],
        "expect": [
            "size(steps.c1.result.value.block_ids) == 2 && size(steps.c2.result.value.block_ids) == 2 && size(steps.c3.result.value.block_ids) == 2",
            "size(steps.ids.result.value.block_ids) == 2",
        ],
    },
})
tests.append({
    "n": 3,
    "test": "tests/v1/simple_kv_offload/test_worker.py:480 test_register_mixed_page_sizes_in_one_cache_group",
    "scenario": {
        "name": "A sparse-MLA cache group mixing page sizes registers one [num_blocks, page] region per layer",
        "fixtures": FX,
        "steps": [
            call("kv-cache-utils.get-kv-cache-config-from-groups", "cfg", caller="engine-core", layout="LBNHC",
                 kv_cache_groups=[{"layer_names": DSA_LAYERS, "layer_pages": PAGES}], available_memory=sum(PAGES.values()) * 4),
            call("simple-cpu-offload-worker.register-kv-caches", "reg", caller="engine-core", num_blocks="= steps.cfg.result.value.num_blocks",
                 kv_cache_tensors="= steps.cfg.result.value.kv_cache_tensors", layer_names=DSA_LAYERS),
        ],
        "expect": [
            "steps.cfg.result.value.num_blocks == 4",
            "steps.reg.result.value.regions.transformList(k, v, k).size() == 8",
            "steps.reg.result.value.regions.transformList(k, v, v[0] == 4 && v[1] == (k.endsWith('.attn') ? %d : %d)).all(b, b)" % (MLA_PAGE, IDX_PAGE),
        ],
    },
})
tests.append({
    "n": 4,
    "test": "tests/v1/kv_offload/tiering/test_factory.py:74 test_create_tier_from_registry",
    "scenario": {
        "name": "A registered tier type creates an instance whose tier_type is that type",
        "fixtures": FX,
        "steps": [
            call("secondary-tier-factory.create-secondary-tier", "tier", caller="engine-core", tier_id="tier0", tier_config={"type": "example"}),
            call(f"{XT}.get-num-chunks", "n", caller="engine-core", tier_id="tier0"),
        ],
        "expect": [
            "steps.tier.result.value.tier_type == 'example' && steps.tier.result.value.class_name == 'ExampleSecondaryTierManager'",
            "steps.n.result.value.num_chunks == 0",
        ],
    },
})
tests.append({
    "n": 5,
    "test": "tests/v1/kv_offload/tiering/test_tiering_offloading.py:225 TestExampleSecondaryTierManager.test_basic_store_and_lookup",
    "scenario": {
        "name": "The example tier misses an empty key, then hits the two stored chunks and misses the third",
        "fixtures": FX,
        "steps": [
            call(f"{XT}.init", "tier", caller="engine-core", tier_id="tier0", tier_type="example", custom_param=67, primary_row_stride=16),
            call(f"{XT}.lookup", "m0", caller="engine-core", tier_id="tier0", key="0", req_id="test"),
            call(f"{XT}.submit-store", "ins", caller="engine-core", tier_id="tier0", job_id=0, keys=["0", "1"], chunk_ids=[0, 1]),
            call(f"{XT}.lookup", "h0", caller="engine-core", tier_id="tier0", key="0", req_id="test"),
            call(f"{XT}.lookup", "h1", caller="engine-core", tier_id="tier0", key="1", req_id="test"),
            call(f"{XT}.lookup", "m2", caller="engine-core", tier_id="tier0", key="2", req_id="test"),
        ],
        "expect": [
            "steps.m0.result.value.result == 'MISS'",
            "steps.h0.result.value.result == 'HIT' && steps.h1.result.value.result == 'HIT'",
            "steps.m2.result.value.result == 'MISS'",
        ],
    },
})
tests.append({
    "n": 6,
    "test": "tests/v1/kv_offload/tiering/p2p/test_zmq_transport.py:344 TestExpandedMonitorEvents.test_fatal_events_include_disconnected_and_closed",
    "scenario": {
        "name": "The fatal monitor events include EVENT_DISCONNECTED and EVENT_CLOSED",
        "fixtures": FX,
        "steps": [call("zmq-transport.fatal-monitor-events", "ev", caller="engine-core")],
        "expect": ["'EVENT_DISCONNECTED' in steps.ev.result.value.events && 'EVENT_CLOSED' in steps.ev.result.value.events"],
    },
})

SW = "sliding-window-manager"
scen.append({
    "id": "scheduler-kv-r4-sliding-window",
    "name": "Sliding window: a hit needs only the window's last blocks contiguous; blocks that leave the window are freed to the pool and nulled",
    "fixtures": FX,
    "config": {"block-size": 4},
    "state": {"block-pool": {"num_gpu_blocks": 20, "next_fresh": 9, "free_front": [], "free_tail": [], "ref_cnt": {},
                             "block_hash": {"1": "h0", "3": "h2", "4": "h3", "5": "h5"}, "cached": {"h0": 1, "h2": 3, "h3": 4, "h5": 5}, "hash_tokens": {}}},
    "steps": [
        call(f"{SW}.find-longest-cache-hit", "hit", caller="kv-cache-manager", block_hashes=["h0", "h1", "h2", "h3", "h4", "h5"], max_length=24, sliding_window=8),
        call(f"{SW}.find-longest-cache-hit", "eagle", caller="kv-cache-manager", block_hashes=["h0", "h1", "h2", "h3"], max_length=16, sliding_window=8, use_eagle=True),
        call(f"{SW}.find-longest-cache-hit", "prefix", caller="kv-cache-manager", block_hashes=["h0", "h1"], max_length=8, sliding_window=16),
        call(f"{SW}.allocate", "al", caller="kv-cache-manager", request_id="sw-1", block_ids=[6, 7, 8]),
        call(f"{SW}.remove-skipped-blocks", "early", caller="kv-cache-manager", request_id="sw-1", processed_computed_tokens=3, sliding_window=4),
        call(f"{SW}.remove-skipped-blocks", "rm", caller="kv-cache-manager", request_id="sw-1", processed_computed_tokens=11, sliding_window=4),
        call(f"{SW}.remove-skipped-blocks", "again", caller="kv-cache-manager", request_id="sw-1", processed_computed_tokens=11, sliding_window=4),
        call("block-pool.get-num-free-blocks", "free", caller="kv-cache-manager"),
    ],
    "expect": [
        "steps.hit.result.value.block_ids == [0, 0, 3, 4] && steps.hit.result.value.hit_length == 16",
        "steps.eagle.result.value.hit_length == 0 && steps.prefix.result.value.block_ids == [1]",
        "steps.early.result.value.freed == [] && steps.rm.result.value.freed == [7, 6] && steps.rm.result.value.block_ids == [0, 0, 8]",
        "steps.again.result.value.freed == [] && steps.free.result.value.num_free_blocks == 13",
    ],
})

scen.append({
    "id": "scheduler-kv-r4-kv-cache-events",
    "name": "KV events: with --kv-events-config, caching a block queues BlockStored (annotated with its spec kind) and evicting it queues BlockRemoved; off, nothing is queued",
    "fixtures": FX,
    "config": {"enable-kv-cache-events": True},
    "state": {"block-pool": {"num_gpu_blocks": 3, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        call("block-pool.get-new-blocks", "a", caller="kv-cache-manager", num_blocks=2),
        call("block-pool.cache-full-blocks", "c", caller="kv-cache-manager", block_ids=[1, 2], block_hashes=["h@16", "h@32"]),
        call("block-pool.free-blocks", "f", caller="kv-cache-manager", block_ids=[2, 1]),
        call("block-pool.get-new-blocks", "b", caller="kv-cache-manager", num_blocks=1),
        call("kv-cache-manager.take-events", "ev", caller="scheduler"),
        call("kv-cache-manager.take-events", "ev2", caller="scheduler"),
    ],
    "expect": [
        "steps.ev.result.value.events.map(e, e.type) == ['BlockStored', 'BlockRemoved'] && steps.ev.result.value.events[0].kv_cache_spec_kind == 'full_attention'",
        "steps.ev.result.value.events[1].block_hashes == ['h@32'] && size(steps.ev2.result.value.events) == 0",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-kv-cache-events-off",
    "name": "Without --kv-events-config the block pool queues no events",
    "fixtures": FX,
    "steps": [call("block-pool.take-events", "ev", caller="kv-cache-manager")],
    "expect": ["size(steps.ev.result.value.events) == 0"],
})

CB = "circular-buffer-manager"
scen.append({
    "id": "scheduler-kv-r4-circular-buffer",
    "name": "Circular buffer: one ring block per request, claimed once; no prefix hits, caching or skipped blocks",
    "fixtures": FX,
    "state": {"block-pool": {"num_gpu_blocks": 4, "next_fresh": 1, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        call(f"{CB}.get-num-blocks-to-allocate", "n0", caller="kv-cache-manager", request_id="cb-1"),
        call(f"{CB}.allocate-new-blocks", "a1", caller="kv-cache-manager", request_id="cb-1"),
        call(f"{CB}.allocate-new-blocks", "a2", caller="kv-cache-manager", request_id="cb-1"),
        call(f"{CB}.get-num-blocks-to-allocate", "n1", caller="kv-cache-manager", request_id="cb-1"),
        call(f"{CB}.find-longest-cache-hit", "hit", caller="kv-cache-manager", block_hashes=["h0"], max_length=16),
        call(f"{CB}.cache-blocks", "c", caller="kv-cache-manager", request_id="cb-1", num_tokens=16),
        call(f"{CB}.remove-skipped-blocks", "r", caller="kv-cache-manager", request_id="cb-1", processed_computed_tokens=64),
        call("block-pool.get-num-free-blocks", "free", caller="kv-cache-manager"),
    ],
    "expect": [
        "steps.n0.result.value.num_blocks == 1 && steps.a1.result.value.new_block_ids == [1] && steps.a2.result.value.new_block_ids == [] && steps.n1.result.value.num_blocks == 0",
        "steps.hit.result.value.hit_length == 0 && steps.c.result.value.cached == 0 && steps.r.result.value.freed == [] && steps.free.result.value.num_free_blocks == 2",
    ],
})

scen.append({
    "id": "scheduler-kv-r4-mamba-sibling-below-block-grid",
    "name": "oracle2 Mamba: with EAGLE and the shared-prefix checkpoint the follower's chunk stops at the junction (12), and a sibling then hits 12 tokens, below the 16-token block grid",
    "description": "tests/v1/core/prefix_cache/test_mamba_eagle_resume_checkpoint.py:169; _mamba_block_aligned_split (scheduler.py:443-556) and MambaManager partial hits (single_type_kv_cache_manager.py:1478-1497).",
    "fixtures": FX,
    "config": {"block-size": 16},
    "state": {"block-pool": {"num_gpu_blocks": 20, "next_fresh": 10, "free_front": [], "free_tail": [], "ref_cnt": {},
                             "block_hash": {"7": "f3", "9": "f2#mamba"}, "cached": {"f3": 7, "f2#mamba": 9}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        call("scheduler.mamba-block-aligned-split", "split", caller="scheduler", num_computed_tokens=0, num_new_tokens=24, num_prompt_tokens=24, num_tokens=24,
             shared_prefix_boundary=12, hash_block_size=4, mamba_partial_cache_hit=True, use_eagle_block_drop=True, mamba_shared_prefix_checkpoint=True),
        call("scheduler.mamba-block-aligned-split", "nojunction", caller="scheduler", num_computed_tokens=0, num_new_tokens=40, num_prompt_tokens=40, num_tokens=40),
        call("scheduler.mamba-block-aligned-split", "midblock", caller="scheduler", num_computed_tokens=4, num_new_tokens=30, num_prompt_tokens=40, num_tokens=40),
        call("scheduler.mamba-block-aligned-split", "decode", caller="scheduler", num_computed_tokens=40, num_new_tokens=1, num_prompt_tokens=40, num_tokens=41),
        call("scheduler.mamba-block-aligned-split", "floored", caller="scheduler", num_computed_tokens=0, num_new_tokens=40, num_prompt_tokens=40, num_tokens=40, shared_prefix_boundary=12),
        call("hybrid-kv-cache-coordinator.find-longest-cache-hit", "hit", caller="kv-cache-manager", block_hashes=["f0", "f1", "f2", "f3", "f4", "f5"], max_length=23, hash_block_size=4),
    ],
    "expect": [
        "steps.split.result.value.num_new_tokens == 12",
        "steps.nojunction.result.value.end == 32 && steps.midblock.result.value.end == 16 && steps.decode.result.value.num_new_tokens == 1",
        "steps.floored.result.value.end == 32",
        "steps.hit.result.value.hit_length == 12 && steps.hit.result.value.mamba_block.block_id == 9",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-resolve-block-sizes",
    "name": "Block-size resolution: one group hashes at its block size, hybrid groups schedule at the LCM and hash at the GCD or prefix_match_unit; bad units are refused",
    "fixtures": FX,
    "steps": [
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "one", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}]),
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "one_bad", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}], prefix_match_unit=8),
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "hyb", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}, {"kind": "mamba", "block_size": 64, "mamba_cache_mode": "align"}]),
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "unit", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}, {"kind": "mamba", "block_size": 64, "mamba_cache_mode": "align"}], prefix_match_unit=8),
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "badunit", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}, {"kind": "mamba", "block_size": 64, "mamba_cache_mode": "align"}], prefix_match_unit=12),
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "noalign", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}, {"kind": "mamba", "block_size": 48, "mamba_cache_mode": "none"}]),
        call("kv-cache-utils.resolve-kv-cache-block-sizes", "noncache", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}, {"kind": "sliding_window", "block_size": 32, "prefix_cacheable": False}, {"kind": "mamba", "block_size": 64, "mamba_cache_mode": "align"}]),
    ],
    "expect": [
        "steps.one.result.value.hash_block_size == 16 && steps.one_bad.result.error.code == 'value-error'",
        "steps.hyb.result.value.scheduler_block_size == 64 && steps.hyb.result.value.hash_block_size == 16 && steps.unit.result.value.hash_block_size == 8",
        "steps.badunit.result.error.code == 'value-error' && steps.noalign.result.value.hash_block_size == 48",
        "steps.noncache.result.value.hash_block_size == 16",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-resolve-block-sizes-no-caching",
    "name": "With prefix caching off and no connector, hybrid groups hash at the scheduler block size",
    "fixtures": FX,
    "config": {"enable-prefix-caching": False},
    "steps": [call("kv-cache-utils.resolve-kv-cache-block-sizes", "r", caller="engine-core", groups=[{"kind": "full_attention", "block_size": 16}, {"kind": "mamba", "block_size": 64, "mamba_cache_mode": "align"}])],
    "expect": ["steps.r.result.value.hash_block_size == 64"],
})
scen.append({
    "id": "scheduler-kv-r4-scheduler-kv-cache-config",
    "name": "The scheduler's KV config is the first worker's, with a uniform-type group represented by one layer spec; workers must agree on num_blocks",
    "fixtures": FX,
    "steps": [
        call("kv-cache-utils.generate-scheduler-kv-cache-config", "ok", caller="engine-core", kv_cache_configs=[
            {"num_blocks": 4, "kv_cache_groups": [{"layer_names": ["a", "b"], "layer_specs": [{"kind": "mla_attention", "head_size": 576}, {"kind": "mla_attention", "head_size": 132}]}]},
            {"num_blocks": 4, "kv_cache_groups": [{"layer_names": ["a", "b"]}]}]),
        call("kv-cache-utils.generate-scheduler-kv-cache-config", "bad", caller="engine-core", kv_cache_configs=[{"num_blocks": 4, "kv_cache_groups": []}, {"num_blocks": 5, "kv_cache_groups": []}]),
    ],
    "expect": [
        "steps.ok.result.value.num_blocks == 4 && steps.ok.result.value.kv_cache_groups[0].spec.head_size == 576",
        "steps.bad.result.error.code == 'assertion-error'",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-rswa-gap",
    "name": "R-SWA frees the gap between the prompt and the decode window (nothing without the prompt length)",
    "fixtures": FX,
    "config": {"block-size": 4},
    "state": {"block-pool": {"num_gpu_blocks": 12, "next_fresh": 9, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {}, "cached": {}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        call("rswa-manager.remove-skipped-blocks", "full", caller="kv-cache-manager", request_id="r1", processed_computed_tokens=30, rswa_window=8, block_ids=[1, 2, 3, 4, 5, 6, 7, 8]),
        call("rswa-manager.remove-skipped-blocks", "gap", caller="kv-cache-manager", request_id="r1", processed_computed_tokens=30, rswa_window=8, num_prompt_tokens=6),
        call("rswa-manager.remove-skipped-blocks", "again", caller="kv-cache-manager", request_id="r1", processed_computed_tokens=30, rswa_window=8, num_prompt_tokens=6),
        call("block-pool.get-num-free-blocks", "free", caller="kv-cache-manager"),
    ],
    "expect": [
        "steps.full.result.value.freed == [] && steps.gap.result.value.freed == [5, 4, 3]",
        "steps.gap.result.value.block_ids == [1, 2, 0, 0, 0, 6, 7, 8] && steps.again.result.value.freed == [] && steps.free.result.value.num_free_blocks == 6",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-chunked-local-hit",
    "name": "Chunked local attention: blocks before the current chunk are free hits; the chunk's cached blocks are adopted until a miss",
    "fixtures": FX,
    "config": {"block-size": 4},
    "state": {"block-pool": {"num_gpu_blocks": 10, "next_fresh": 6, "free_front": [], "free_tail": [], "ref_cnt": {}, "block_hash": {"3": "c2", "5": "c4"}, "cached": {"c2": 3, "c4": 5}, "hash_tokens": {}, "kv_event_queue": []}},
    "steps": [
        call("chunked-local-attention-manager.find-longest-cache-hit", "hit", caller="kv-cache-manager", block_hashes=["c0", "c1", "c2", "c3"], max_length=15, attention_chunk_size=8),
        call("chunked-local-attention-manager.find-longest-cache-hit", "miss", caller="kv-cache-manager", block_hashes=["c0", "c1", "c2", "c3", "c4"], max_length=20, attention_chunk_size=8),
        call("chunked-local-attention-manager.find-longest-cache-hit", "edge", caller="kv-cache-manager", block_hashes=["c0", "c1", "c2", "c3"], max_length=16, attention_chunk_size=8),
    ],
    "expect": [
        "steps.hit.result.value.block_ids == [0, 0, 3] && steps.hit.result.value.hit_length == 12",
        "steps.miss.result.value.block_ids == [0, 0, 0, 0, 5] && steps.edge.result.value.hit_length == 16",
    ],
})
scen.append({
    "id": "scheduler-kv-r4-spec-registry",
    "name": "The spec registry maps MLA to the full-attention manager via its MRO, honors group roles, and refuses conflicting registrations",
    "fixtures": FX,
    "steps": [
        call("kv-cache-spec-registry.register-all-kvcache-specs", "reg", caller="kv-cache-manager"),
        call("kv-cache-spec-registry.get-manager-class", "mla", caller="kv-cache-manager", mro=["MLAAttentionSpec", "FullAttentionSpec", "AttentionSpec", "KVCacheSpec"]),
        call("kv-cache-spec-registry.get-manager-class", "role", caller="kv-cache-manager", mro=["FullAttentionSpec"], role="hisparse_source"),
        call("kv-cache-spec-registry.get-manager-class", "none", caller="kv-cache-manager", mro=["MyCustomSpec", "KVCacheSpec"]),
        call("kv-cache-spec-registry.register-all-kvcache-specs", "conflict", caller="kv-cache-manager", extra=[{"spec": "MambaSpec", "manager": "Other", "base": "MambaSpec"}]),
        call("kv-cache-spec-registry.register-all-kvcache-specs", "plugin", caller="kv-cache-manager", extra=[{"spec": "MyCustomSpec", "manager": "FullAttentionManager", "base": "FullAttentionSpec"}]),
        call("kv-cache-spec-registry.get-manager-class", "custom", caller="kv-cache-manager", mro=["MyCustomSpec", "KVCacheSpec"]),
    ],
    "expect": [
        "steps.reg.result.value.num_specs == 13 && steps.mla.result.value.manager == 'FullAttentionManager'",
        "steps.role.result.value.manager == 'HiSparseSourceManager' && steps.none.result.value.manager == null",
        "steps.conflict.result.error.code == 'assertion-error' && steps.custom.result.value.manager == 'FullAttentionManager'",
    ],
})

FLOW_ENTRY = {
    "scheduler-add-request": "scheduler.add-request",
    "scheduler-schedule": "scheduler.schedule",
    "scheduler-update-from-output": "scheduler.update-from-output",
    "scheduler-finish-requests": "scheduler.finish-requests",
}


def with_trace(sc):
    """Write-then-read: the scenario's last step (a read or the write itself) is checked in the trace."""
    last = sc["steps"][-1]
    iface = last.get("interface") or FLOW_ENTRY[last["flow"]]
    sc["expect"].append(f"trace.exists(e, e.type == 'call.end' && e.interface == '{iface}')")
    return sc


# A second eviction case: two reclaimable entries, only the oldest is evicted.
scen.append({
    "id": "scheduler-kv-r4-encoder-cache-evicts-only-what-it-needs",
    "name": "Encoder cache eviction stops as soon as the new item fits: only the oldest unreferenced entry goes",
    "fixtures": FX,
    "steps": [
        call(f"{EC}.init", "init", caller="scheduler", cache_size=10),
        call(f"{EC}.allocate", "a", caller="scheduler", request_id="r1", input_id=0, mm_hash="old", num_embeds=4),
        call(f"{EC}.allocate", "b", caller="scheduler", request_id="r2", input_id=0, mm_hash="new", num_embeds=4),
        call(f"{EC}.free", "fa", caller="scheduler", request_id="r1", mm_hashes=["old"]),
        call(f"{EC}.free", "fb", caller="scheduler", request_id="r2", mm_hashes=["new"]),
        call(f"{EC}.can-allocate", "ev", caller="scheduler", request_id="r3", input_id=0, num_embeds=5, encoder_compute_budget=100),
        call(f"{EC}.check-and-update-cache", "still", caller="scheduler", request_id="r3", input_id=0, mm_hash="new"),
    ],
    "expect": ["steps.ev.result.value.evicted == ['old'] && steps.still.result.value.cached"],
})

frag = []
oracle = []
for t in tests:
    sc = with_trace({"id": f"scheduler-kv-r4-test-{t['n']}", **copy.deepcopy(t["scenario"])})
    sc.setdefault("description", t["test"])
    frag.append(sc)
    o = copy.deepcopy(sc)
    o["id"] = f"oracle-r4-scheduler-kv-{t['n']}"
    o["description"] = t["test"]
    oracle.append(o)
frag.extend(with_trace(sc) for sc in scen)


def dump(path, doc):
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, width=100000, allow_unicode=False)


dump(os.path.join(HERE, "round4_scenarios.yaml"), {"scenarios": frag})
os.makedirs(os.path.join(WS, "build-oracle", "round4"), exist_ok=True)
dump(os.path.join(WS, "build-oracle", "round4", "scheduler-kv.yaml"),
     {"schema_version": 1, "id": "vllm", "scenarios": oracle})
print("r4 ok", len(frag), len(oracle), file=sys.stderr)
