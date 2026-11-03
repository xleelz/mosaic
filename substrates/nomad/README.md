# Nomad substrate

`nomad.yaml` models a Nomad region from HashiCorp's documentation (each interface cites the
page it follows; there is no code snapshot). `scenarios.yaml` holds its tests:

    go run ./internal/devtools/check -f substrates/nomad/nomad.yaml -f substrates/nomad/scenarios.yaml

**Components.** `nomad-server` (the HTTP API, the state store of nodes, jobs, evaluations and
allocations, and the scheduler workers) and `nomad-client` (alloc runners on the nodes).

**Behavior.**
- `job-register` stores the job (pending) and creates an evaluation; it returns the eval id at
  once. `process-eval` runs `nomad-scheduler-delay-ms` later and places each missing
  allocation on a feasible node (ready, eligible, in the job's datacenters, matching
  `node_class`, with free cpu and memory), bin packing. Allocations without capacity leave a
  blocked evaluation that `node-register` unblocks. Re-registering with another count scales.
- An allocation is `pending` until the boot delay passes (`nomad-boot-delay-ms`, or the group's
  `boot_delay_ms`: seconds for containers, tens of seconds for a VM), then `running`; a service
  is `healthy` after `min_healthy_time` with passing checks, or `unhealthy` at
  `healthy_deadline`. A task that exits does so `run_ms` after starting: `complete` or `failed`.
- `job-stop` (with `purge`, deregister) sets desired status `stop`. Pending allocations complete
  at once; running ones keep running until the kill timeout (`nomad-kill-timeout-ms`, or the
  group's `kill_timeout_ms`), then complete. The job is `dead` when all are terminal.
- `nomad-client.node-crash` stops heartbeats; after TTL plus grace the node is `down` and its
  allocations `lost` (or `unknown`, then lost when `disconnect_lost_after_ms` expires; the node
  is `disconnected`), and replacements are placed elsewhere.
- Reads: `job-get`, `allocations-by-job`, `allocations-by-node`.

An allocation's `status` is its `client_status`, with `running` refined to `healthy` or
`unhealthy` by deployment health.

**Not modeled.** Deployments and canaries, restart and reschedule after a task failure,
spread and affinity, preemption, drain, and reconnection of disconnected clients.
