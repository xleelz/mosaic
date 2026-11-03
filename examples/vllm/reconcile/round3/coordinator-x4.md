# Judge X4 after round 3: scenario needs adaptation, not a model fix

The model now dispatches `[NONE:20, FULL:1, PIECEWISE:8]` (inputs `[20, 1, 7]`); the judge expected
`[NONE:20, PIECEWISE:8, FULL:2]` (inputs `[20, 7, 2]`).

- The scenario runs `engine-core-busy-loop {iterations: 2}`, then adds `x4-short`, then runs one
  more iteration. Read sequentially, that is: prefill 20 tokens (eager, above the capture size 16),
  decode 1 token of `x4-long` (uniform decode, FULL), then the mixed batch (1 decode + 6 prefill =
  7, PIECEWISE padded to 8). The model now does exactly this.
- The judge's expected order relied on the busy loop re-emitting itself asynchronously, so that
  `add-request` landed inside loop1's second iteration. The judge flagged that quirk itself
  (`judge/execution-parallel.md`, "Self-emitting busy loop (X4, X5)"). Round 3 made the engine
  loop sequential (engine-core: capacity 1 on llm-engine and the executor, for the racy lint).
- The judge's *claim* (decode within the capture sizes → FULL, mixed/prefill → PIECEWISE, above →
  NONE) still holds on every dispatch. Only the scenario's step timing is stale.

**Verdict for the measure review:** adapt. Expected `[NONE:20, FULL:1, PIECEWISE:8]`, or add one
more busy-loop iteration to reach a 2-token uniform decode (`FULL:2`).

# Judge V2 and V5 after `streams_when`: adapt

Both send `stream: true`. The chat route now streams only on that path (DESIGN §17.12), so the
caller gets `{items, value}`: the SSE frames plus the route's return. V2's
`steps.chat.result.value.stream` reads the old non-streaming shape; it should read
`result.value.value.stream`, or assert on `result.value.items`. V5 likewise. The model is right
(`serving_chat.py` returns a StreamingResponse over `chat_completion_stream_generator` when
`request.stream`); only the scenarios' result paths are stale. Verdict for the measure review: adapt.
