# CUDA substrate

`cuda.yaml` models the CUDA runtime API over one or more GPUs at the `machine` level, from
NVIDIA's runtime API reference, programming guide and best practices guide (each interface
cites the page it follows; there is no code snapshot). `scenarios.yaml` holds its tests:

    go run ./internal/devtools/check -f substrates/cuda/cuda.yaml -f substrates/cuda/scenarios.yaml

**Components.** `cuda` (the driver and GPUs) and `cuda-runtime` (the API and the devices'
state: `allocs`, `streams`, `events`, `ops`, every queued operation with its status and times,
and `completed`, the op ids in the order the device finished them).

**Device timeline.** Device work runs on the scheduler's microsecond clock. A kernel launch, a
copy, an event record or a stream wait queues a row of `ops`. The device starts an operation once
nothing it depends on is pending: earlier work on its stream, the legacy default stream (a
blocking stream waits for it, and it waits for every blocking stream), the event a wait marker
awaits, and a busy copy engine. A started kernel or copy completes through a timer emitted after
its cost (fractional ms), and its completion starts what it unblocked. So stream order,
cross-stream overlap and copy-engine contention are scheduler events, and operations that finish
at the same instant are choice points for `check --explore`. Asynchronous calls return an `op`
id at once (`state.ops[op]` has `start_us`, `end_us`); synchronize calls make the host `wait`
until the operations they cover are done and return the exact `waited_ms` and `done_us`. A buffer
records the last completed operation that wrote it (`written_by`, `written_us`: a copy's
destination, a kernel's `writes`).

**Host programs.** A host thread's calls are scenario steps in one lane (`lane: host`, DESIGN
§17 item 11). Asynchronous calls (`launch-kernel`, `memcpy-async`, `event-record`,
`stream-wait-event`) are `await: false`, so the host moves straight on; synchronizing calls are
awaited, and their `duration_ms` is how long the host was blocked (fractional, §17 item 10). A
step started with `await: false` ends, and records its result, once its device work completes.
The lane keeps the calls in program order under `--explore`, while the device's completions
still race: without it, exploration would reorder the host's own calls. An importer makes the
same calls in order inside its own behaviors.

**Races.** `cross-stream-race` has two streams write one buffer with no event between them; the
two kernels finish at the same instant, and exploration finds the order where the first stream's
write lands last (its invariant fails). `cross-stream-fenced` records an event after the first
write and makes the second stream wait for it; it passes every schedule:

    go run ./internal/devtools/check -f substrates/cuda/cuda.yaml -f substrates/cuda/scenarios.yaml --scenario '^$' --explore . --schedules 10

**Behavior.**
- Memory: `malloc` (rounded to 256 bytes; `cudaErrorMemoryAllocation` past free memory;
  size 0 gives `"0"`), `free` (synchronizes the device first; unknown pointer is
  `cudaErrorInvalidValue`), `mem-get-info` (total minus `cuda-context-reserved-bytes` minus
  allocations).
- Streams: `stream-create` (blocking or `non_blocking`), `stream-destroy` (queued work still
  finishes), `stream-query` (`cudaErrorNotReady` while busy), `stream-synchronize`,
  `stream-wait-event` (a marker that waits for the event's record at the time of the call),
  `device-synchronize`. Work in one stream is serial; different streams overlap.
- Events: `event-create`, `event-record` (a marker; the event's time is when it completes),
  `event-query` (ready when never recorded), `event-synchronize`, `event-elapsed-time`
  (fractional ms; `cudaErrorNotReady` before completion, `cudaErrorInvalidResourceHandle` when
  unrecorded).
- Copies: `memcpy-async` and `memcpy` (legacy stream, host waits). Cost is
  `cuda-memcpy-overhead-us` + bytes / bandwidth: `cuda-host-link` (pcie3/4/5, nvlink-c2c) for
  pinned memory, `cuda-pageable-bandwidth-gbps` for pageable (and then the host waits), half
  of HBM bandwidth within a device, `cuda-peer-link` between devices. H2D and D2H each have a
  copy engine (one shared with `cuda-copy-engines: 1`); a copy waits for its engine to be idle,
  so same-direction copies serialize.
- Kernels: `launch-kernel` validates the configuration (`cudaErrorInvalidConfiguration` above
  1024 threads or for an empty grid, `cudaErrorInvalidValue` for shared memory over 48 KiB,
  `cudaErrorLaunchOutOfResources` for registers), computes blocks per SM (block, thread,
  register and shared-memory limits), occupancy and waves, and costs
  `cuda-launch-overhead-us` + max(flops / peak, bytes / bandwidth) × waves × resident / blocks.
  Bandwidth falls linearly below `cuda-full-bandwidth-occupancy`.

Defaults describe an A100 80GB SXM on PCIe Gen4. Errors carry the numeric `cudaError_t` at
`error.data.cuda_error`.

**Not modeled.** Unified and managed memory, graphs, the per-thread default stream, stream
priorities, SM sharing between concurrent kernels (they overlap fully), bandwidth sharing
between concurrent copies in opposite directions, sticky errors from faulting kernels, MPS, and
data values (a buffer knows its last writer, not its bytes).

[../examples/gpu-inference](../examples/gpu-inference/) imports it.
