# Substrate library

Importable ontologies of shared infrastructure (DESIGN §14.6, §15.6). Import a substrate
instead of modeling it again:

```yaml
imports:
  - {ontology: ../../substrates/nomad/nomad.yaml, as: nomad}       # a path to the document file,
  - {ontology: ../../substrates/dynamodb/dynamodb.yaml, as: ddb}   # relative to the importer
```

Imported components and interfaces take the `<as>/` prefix (`nomad/nomad-server.job-register`,
state at `state['nomad/nomad-server']`), schemas the `<as>.` prefix; configs keep their ids, and
a local config of the same id overrides the substrate's value. Flows and scenarios stay behind.

| Substrate | Models | Tests |
|---|---|---|
| [nomad](nomad/) | jobs, evaluations, placement after a boot delay, allocation health, node loss, stop/deregister | `check -f nomad/nomad.yaml -f nomad/scenarios.yaml` |
| [dynamodb](dynamodb/) | pk/sk tables from config, get/put/update/delete, the `-if` conditional set, transactions, GSIs, TTL | `check -f dynamodb/dynamodb.yaml -f dynamodb/tables/orders.yaml -f dynamodb/scenarios.yaml` |
| [redis](redis/) | strings, hashes, sorted sets; TTL with lazy and active expiry; INCR, SET NX/XX/PX, SETNX, EXPIRE flags; Lua scripts as one atomic transaction (no rollback), EVALSHA; pub/sub; Redis down through faults | `check -f redis/redis.yaml -f redis/scenarios.yaml` |
| [temporal](temporal/) | workflow start with id reuse and conflict policies, workflow tasks and their timeout, activities with retry policies and start-to-close, schedule-to-close and heartbeat timeouts, redelivery after a worker crash, timers, signals, continue-as-new, terminate, DescribeWorkflowExecution | `check -f temporal/temporal.yaml -f temporal/scenarios.yaml` |
| [tcp-tls](tcp-tls/) (`runtime`) | listen/accept and backlog, the three-way handshake, SYN retries to ETIMEDOUT, ECONNREFUSED, send buffers against the receive window (EAGAIN), half-close, FIN vs RST, idle and read timeouts, keepalive; TLS 1.2/1.3 handshakes with expired, unknown-CA and hostname failures | `check -f tcp-tls/tcp-tls.yaml -f tcp-tls/scenarios.yaml` |
| [linux](linux/) (`runtime`) | fork, execve, exit, waitpid; fd tables capped by RLIMIT_NOFILE; signals (default, ignored, handled); open/read/write/close, sockets, epoll_wait, futex, nanosleep with errno codes; the OOM killer | `check -f linux/linux.yaml -f linux/scenarios.yaml` |
| [cuda](cuda/) (`machine`) | device memory and OOM, streams and events (in-order within, concurrent across), memcpy H2D/D2H/D2D over PCIe or NVLink, kernels with occupancy and a roofline cost, synchronize | `check -f cuda/cuda.yaml -f cuda/scenarios.yaml` |

[examples/](examples/) holds an import example per substrate: `vm-service` (nomad and dynamodb),
`rate-limited-api` (redis), `order-workflow` (temporal), `tcp-client`, `linux-worker` and
`gpu-inference`.

`check -f` loads each document's imports relative to its file (§15.8), so every example passes
`go run ./internal/devtools/check -f substrates/examples/<name>/ontology.yaml`.
