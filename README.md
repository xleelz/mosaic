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

### Install

Requires Go 1.27 or newer and Node 20.9 or newer. Install those yourself; the install script
checks for them and stops if either is missing or too old. Mosaic also needs Dolt 2.x, which the
script installs when it's missing.

```sh
scripts/install.sh               # checks Go and Node, installs Dolt if needed, builds bin/, installs the web UI's dependencies
scripts/install.sh --go-install  # the same, and also installs mosaic and mosaicd into Go's bin folder
```

Without the script, you need Dolt on your `PATH`; see the
[Dolt installation guide](https://docs.dolthub.com/introduction/installation).

**Dolt.** The script uses Homebrew on macOS when it's available. Otherwise it downloads the latest
release into `~/.local/bin`, without sudo; pass `--prefix DIR` to choose another folder. Run
`scripts/install.sh --help` for every option.

**Running `mosaic` and `mosaicd` from anywhere.** `--go-install` puts both binaries in Go's bin
folder: `$GOBIN` if set, else `$(go env GOPATH)/bin`, usually `~/go/bin`. Make sure that folder is
on your `PATH`, for example in `~/.zshrc` or `~/.bashrc`:

```sh
export PATH="$(go env GOPATH)/bin:$PATH"
```

To do it without the script, from a clone:

```sh
go install ./cmd/mosaic ./cmd/mosaicd
```

The repository is private, so installing straight from GitHub needs Go to fetch it with your git
credentials:

```sh
GOPRIVATE=github.com/xleelz/mosaic go install github.com/xleelz/mosaic/cmd/mosaic@latest github.com/xleelz/mosaic/cmd/mosaicd@latest
```

### Run

The commands below use `./bin/`. If you installed with `--go-install`, drop the `./bin/`.

```sh
./bin/mosaicd --data-dir ~/.mosaic &          # supervises its own dolt sql-server, on 127.0.0.1:7878

./bin/mosaic ontology create gateway-demo --name "Inference gateway"
./bin/mosaic apply gateway-demo -f internal/testdata/gateway/ontology.yaml -m "Model the gateway"
./bin/mosaic test gateway-demo          # runs all 14 scenarios' expectations
./bin/mosaic sim run gateway-demo --scenario retry-before-commit --format summary
./bin/mosaic sim run gateway-demo --flow chat-stream \
    --fault upstream-a.chat:timeout --state ledger.free=1 --format summary
```

Then start the web UI against the running `mosaicd`, and open http://localhost:3000:

```sh
cd web && pnpm dev
```

The web UI lives in [web/](web/README.md). Set `MOSAIC_SERVER` if `mosaicd` listens somewhere else,
or set `NEXT_PUBLIC_MOSAIC_FIXTURES=1` to use fixtures generated from the engine, with no daemon.

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
