# Substrate examples

`vm-service/ontology.yaml` imports both substrates: it records a VM in DynamoDB with `put-if`,
registers a VM-like Nomad job, and marks the record ready with `update-if` once the allocation
is healthy after a 40 s boot.

Each example passes `go run ./internal/devtools/check -f substrates/examples/<name>/ontology.yaml`.

`rate-limited-api/ontology.yaml` imports `redis`: a sliding-window rate limiter as one Lua script
over a sorted set (failing open when Redis is down), login sessions with a TTL, and an
in-process flag cache dropped by a pub/sub invalidation.

`order-workflow/ontology.yaml` imports `temporal`: an order workflow (id = order id, reuse policy
reject_duplicate) that charges a card through an external API (outages retried, a decline not),
waits a durable timer, ships with a heartbeating activity, and can be cancelled by a signal; the
status reads DescribeWorkflowExecution. It overrides the substrate's retry interval config.

`tcp-client/ontology.yaml` imports `tcp-tls`: a quote service that dials a TLS backend (retrying a
refused connection), verifies its certificate, writes the request and reads the reply with a read
timeout; scenarios cover success, an expired certificate, refused-until-listening and a backend
that never replies.

`linux-worker/ontology.yaml` imports `linux`: a supervisor that forks and execs a job and reaps it
with a blocking waitpid, all in one call; a missing program exits 127, and a stop sends SIGTERM,
waits a grace period, then escalates to SIGKILL.

`gpu-inference/ontology.yaml` imports `cuda`: it loads a 7B model's weights over PCIe Gen4 and
serves a request with kernel launches queued on its stream and a stream synchronize, all in one
call, so the device's completions run on the scheduler's clock; a 70B model fails out of memory.
