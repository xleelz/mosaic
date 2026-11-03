# Mosaic

Mosaic models software systems as versioned **ontologies** and simulates user and system actions
through them, down to the fake data passed between the smallest modeled components, with retries,
timeouts and injected faults.

It is built in three pillars:

1. **Understand**: generate an ontology from code repos, visualize the system, and simulate flows
   through it.
2. **Draft**: describe a change as a draft ontology, then show and simulate it the same way.
3. **Build and compare**: propose several plans of fae workflows and task DAGs that would reach the
   draft, narrow them by simulation, implement the survivors in parallel on fae, and keep the one
   that wins on the user's metrics.

This repository is the foundation for pillar 1: a Dolt-backed ontology store with revisions, a
deterministic simulator, an agent CLI with skills, and a web UI. [docs/DESIGN.md](docs/DESIGN.md)
is the contract: the meta-model, the behavior language, simulation semantics, the API and the CLI.

## Quick start

Requires Go 1.27, Dolt 2.x and Node 22.

```sh
go build -o bin/mosaicd ./cmd/mosaicd
go build -o bin/mosaic ./cmd/mosaic

./bin/mosaicd --data-dir ~/.mosaic &          # supervises its own dolt sql-server

./bin/mosaic ontology create gateway-demo --name "Inference gateway"
./bin/mosaic apply gateway-demo -f internal/testdata/gateway/ontology.yaml -m "Model the gateway"
./bin/mosaic test gateway-demo          # runs all 14 scenarios' expectations
./bin/mosaic sim run gateway-demo --scenario retry-before-commit --format summary
./bin/mosaic sim run gateway-demo --flow chat-stream \
    --fault upstream-a.chat:timeout --state ledger.free=1 --format summary
```

The web UI lives in [web/](web/README.md). Run it against `mosaicd`, or set
`NEXT_PUBLIC_MOSAIC_FIXTURES=1` to use fixtures generated from the engine.

## The example

[internal/testdata/gateway](internal/testdata/gateway/ontology.yaml) models a synthetic LLM
inference gateway: admission, routing and retries. It has 20 components, 20 interfaces, one flow
(`chat-stream`) and 14 scenarios whose expectations pass. Each outcome is driven by a different
mechanism:

- input data: an unknown key, an oversized prompt;
- component state: the balance floor, the key budget, free slots;
- choice points: the rate limit, model policy, a stream breaking after commit;
- injected faults: the account store down, the slot ledger down, an upstream error or timeout before commit.

## Development

```sh
go test ./...                                   # needs the dolt binary for store/api tests
go run ./internal/devtools/fixtures -out web/fixtures   # refresh UI fixtures after engine changes
```

Agent skills for operating mosaic are in [.claude/skills](.claude/skills).
