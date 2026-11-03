"""Generate the seeded state of the scheduler-kv area fixtures.

Prints YAML for the two area fixtures (scheduler-kv-nearly-full and
scheduler-kv-prefix-warm) so the block tables, the block pool's free queue and
the prefix-cache hash map stay consistent with each other. The block-hash
format must match kv-cache-utils.request-block-hasher in the fragment:
  "<segment keys overlapping [0, min(E, P))>@<min(E, P)>" + ("+" + output
  tokens up to E) when the block ends past the prompt, for a block ending at
  token E of a prompt of P tokens.
"""

import json

BS = 16


def block_hashes(segments, outputs, num_tokens):
    p = sum(s["num_tokens"] for s in segments)
    starts = []
    acc = 0
    for s in segments:
        starts.append(acc)
        acc += s["num_tokens"]
    hashes = []
    for i in range(num_tokens // BS):
        end = (i + 1) * BS
        pe = min(end, p)
        keys = [segments[j]["key"] for j in range(len(segments)) if starts[j] < pe]
        h = "|".join(keys) + "@" + str(pe)
        if end > p:
            h += "+" + ",".join(str(t) for t in outputs[: end - p])
        hashes.append(h)
    return hashes


def j(v):
    return json.dumps(v, separators=(", ", ": "))


def running_request(rid, key, first_block, arrival, out_base):
    segs = [{"key": key, "num_tokens": 480}]
    outputs = list(range(out_base, out_base + 17))
    num_tokens = 480 + len(outputs)  # 497
    num_computed = num_tokens - 1  # the last sampled token is not computed yet
    blocks = list(range(first_block, first_block + 31))  # 31 blocks = 496 slots
    hashes = block_hashes(segs, outputs, num_tokens)  # 31 full blocks
    req = {
        "request_id": rid,
        "status": "RUNNING",
        "priority": 0,
        "arrival_time": arrival,
        "prompt_segments": segs,
        "prompt_token_ids": None,
        "num_prompt_tokens": 480,
        "output_token_ids": outputs,
        "num_computed_tokens": num_computed,
        "num_output_placeholders": 0,
        "max_tokens": 256,
        "min_tokens": 0,
        "eos_token_id": 128009,
        "stop_token_ids": [128001, 128008],
        "sampling_params": {"max_tokens": 256, "temperature": 0.0},
        "block_hashes": hashes,
        "spec_token_ids": [],
        "kv_transfer_params": None,
        "num_preemptions": 0,
        "num_cached_tokens": 0,
        "is_prefill_chunk": False,
        "grammar_id": None,
        "client_index": 0,
    }
    return req, blocks, hashes


def nearly_full():
    a, a_blocks, a_hashes = running_request("chatcmpl-run-a", "doc-a", 1, 0, 1001)
    b, b_blocks, b_hashes = running_request("chatcmpl-run-b", "doc-b", 32, 1, 2001)
    c = {
        "request_id": "chatcmpl-wait-c",
        "status": "WAITING",
        "priority": 0,
        "arrival_time": 2,
        "prompt_segments": [{"key": "doc-c", "num_tokens": 100}],
        "prompt_token_ids": None,
        "num_prompt_tokens": 100,
        "output_token_ids": [],
        "num_computed_tokens": 0,
        "num_output_placeholders": 0,
        "max_tokens": 64,
        "min_tokens": 0,
        "eos_token_id": 128009,
        "stop_token_ids": [128001, 128008],
        "sampling_params": {"max_tokens": 64, "temperature": 0.0},
        "block_hashes": block_hashes([{"key": "doc-c", "num_tokens": 100}], [], 100),
        "spec_token_ids": [],
        "kv_transfer_params": None,
        "num_preemptions": 0,
        "num_cached_tokens": -1,
        "is_prefill_chunk": True,
        "grammar_id": None,
        "client_index": 0,
    }
    block_hash = {}
    cached = {}
    for blocks, hashes in ((a_blocks, a_hashes), (b_blocks, b_hashes)):
        for blk, h in zip(blocks, hashes):
            block_hash[str(blk)] = h
            cached[h] = blk
    out = []
    out.append("  - id: scheduler-kv-nearly-full")
    out.append('    summary: "tp1-llama-8b launched with --num-gpu-blocks-override 64: two decoding requests hold 62 of the 63 usable blocks (block 0 is the null block), one free block is left, and chatcmpl-wait-c waits."')
    out.append("    extends: [tp1-llama-8b]")
    out.append("    config: {num-gpu-blocks-override: 64}")
    out.append("    state:")
    out.append("      scheduler:")
    out.append("        requests:")
    for r in (a, b, c):
        out.append(f"          {r['request_id']}: {j(r)}")
    out.append("        running: [chatcmpl-run-a, chatcmpl-run-b]")
    out.append("        waiting: [chatcmpl-wait-c]")
    out.append("      full-attention-manager:")
    out.append(f"        req_to_blocks: {j({'chatcmpl-run-a': a_blocks, 'chatcmpl-run-b': b_blocks})}")
    out.append("        num_cached_block: {chatcmpl-run-a: 31, chatcmpl-run-b: 31}")
    out.append("      block-pool:")
    out.append("        num_gpu_blocks: 64")
    out.append("        next_fresh: 63")
    out.append("        free_front: []")
    out.append("        free_tail: []")
    out.append("        ref_cnt: {}")
    out.append(f"        block_hash: {j(block_hash)}")
    out.append(f"        cached: {j(cached)}")
    out.append("        hash_tokens: {}")
    out.append("        kv_event_queue: []")
    return "\n".join(out)


def prefix_warm():
    segs = [{"key": "sys-prompt-v1", "num_tokens": 1024}]
    hashes = block_hashes(segs, [], 1024)
    blocks = list(range(1, 65))
    block_hash = {str(b): h for b, h in zip(blocks, hashes)}
    cached = {h: b for b, h in zip(blocks, hashes)}
    # The request that computed them finished and freed its blocks in reverse
    # order, so the tail block is the first eviction candidate.
    tail = list(reversed(blocks))
    out = []
    out.append("  - id: scheduler-kv-prefix-warm")
    out.append('    summary: "tp1-llama-8b after a finished request left the 1024-token system prompt sys-prompt-v1 in the prefix cache: 64 cached blocks with ref_cnt 0, evictable, at the tail of the free queue."')
    out.append("    extends: [tp1-llama-8b]")
    out.append("    state:")
    out.append("      block-pool:")
    out.append("        num_gpu_blocks: 28488")
    out.append("        next_fresh: 65")
    out.append("        free_front: []")
    out.append(f"        free_tail: {j(tail)}")
    out.append("        ref_cnt: {}")
    out.append(f"        block_hash: {j(block_hash)}")
    out.append(f"        cached: {j(cached)}")
    out.append("        hash_tokens: {}")
    out.append("        kv_event_queue: []")
    return "\n".join(out)


def seed():
    out = []
    out.append("  - id: scheduler-kv-seed")
    out.append('    summary: "scheduler-kv state for the merged worlds: an empty scheduler and an all-free block pool of the default world\'s 28,488 blocks (re-initialized by kv-cache-utils.get-kv-cache-configs at startup)."')
    out.append("    state:")
    out.append("      scheduler: {requests: {}, waiting: [], running: [], finished_req_ids: [], preempted_req_ids: [], current_step: 0, pause_state: UNPAUSED, num_waiting_for_streaming_input: 0, finished_recving_kv_req_ids: []}")
    out.append("      block-pool: {num_gpu_blocks: 28488, next_fresh: 1, free_front: [], free_tail: [], ref_cnt: {}, block_hash: {}, cached: {}, hash_tokens: {}, kv_event_queue: []}")
    out.append("      full-attention-manager: {req_to_blocks: {}, num_cached_block: {}}")
    return "\n".join(out)


if __name__ == "__main__":
    print("fixtures:")
    print(seed())
    print(nearly_full())
    print(prefix_warm())
