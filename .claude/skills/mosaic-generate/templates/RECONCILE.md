<!--
Template: reconciliation round (pipeline stage 5). Render into {{workspace}}/RECONCILE.md after the
first merged check. The coordinator fills in the counts and writes the numbered decisions under
"Decisions": one per root cause, each naming the owner, the exact shape and the count of failures
it fixes. The standing decisions (1, 2 and the last three) stay as written.
Requires mosaic with DESIGN §11 (in progress).
-->

# Reconciliation round

All {{areas.count}} fragments pass on their own. Merged, they give <N> validation errors,
<N> of <N> citations resolving, **<N> of <N> scenarios failing**, <N> merge warnings,
<N> hollow-lint findings and <N> uncovered entries. This round fixes that. The rules in `BRIEF.md`
still apply in full: write only your own fragment, notes and skips file.

## Your inputs

- `reconcile/<area>.txt`: your failing scenarios in the merged run, the merge warnings and lint
  findings that name your fragment, and your uncovered entries.
- `reconcile/merged-check.txt`: the full merged check output.
- The other areas' fragments, which you may now read **for contracts and seeded state only**: the
  interfaces you call, the state you set on their components. Still never read
  {{independence.area_never_read}}.

## Decisions (the coordinator's, binding)

1. **The owner's contract wins.** Callers align their call sites, stubs and scenario state to the
   owner's request, response, kind and errors, including `retryable`. Owners don't loosen a
   contract to fit a caller's guess. The exception is a contract that's wrong about the code; then
   the owner fixes it, cites the code, and says so in the report.
2. **World state lives with its owner, in the fixtures.** Scenarios reach shared state (liveness,
   topology, schema, tenants, catalogs) through `fixtures: [...]` and the owner's components,
   never through state on a private stub. Drop stub state that duplicates an owner's component.
   A world your cases need that no fixture provides is a request to the coordinator, not a
   private seed.

<!-- Coordinator: one decision per root cause, largest first. Each names:
     - the interface, schema or state path;
     - the owner, and the exact shape (fields, types, enums, error codes);
     - which areas change what;
     - how many failures it accounts for.
   Example (Cassandra): "`storage-proxy.read` requires `read_command` in the
   `ReadPathReadCommand` shape; `columns` is a list of column names. The fix is cql's. This one
   change accounts for 63 failures."
   Example: "Unowned stubs. Each owner below defines these interfaces. Pass-through definitions
   are fine: the correct kind and shapes, and a short behavior citing the method. Keep the names
   exactly, because callers already use them. <owner (count): interface list>" -->

3. ...

N-2. **One copy of each piece of logic.** If your fragment re-implements logic another area owns,
   replace your copy with calls to the owner's interfaces, and adjust your scenarios.
N-1. **Fan-out uses `parallel` with a join**, peers are instances addressed with `on:`, and
   durations read config (`timeout_ms: "= config['<id>']"`). A differing duplicate config is a
   merge error: the area whose code reads it owns it, and others mark their copy
   `attributes: {boundary: true, owner: <area>}` or drop it.
   Replace any sequential `foreach` that stands in for concurrent sends, and any `to` or
   `endpoint` request field that stands in for an instance.
N. **Assert on your own calls and the outcome**, not on how many times another area's internal
   interfaces are called. Where such an assertion contradicts the owner's model, the assertion
   goes.

## Skips go into a machine-readable file

Keep `skips/<area>.json` current: a JSON array of `{"kind", "name", "file", "line", "reason"}`,
with **one object per inventory entry**, group skips expanded into their exact entries and copied
from `inventory.json`. The coordinator merges these into the inventory's `skip` fields, after
which `--strict-coverage` must pass. Your notes keep the grouped form.

## Verify

Run the merged gate with your updated fragment in the list, and make sure none of **your**
scenarios fail and no merge warning or lint finding names your fragment:

```sh
cd <mosaic repo>
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
F=""; for f in {{workspace}}/fragments/*.yaml; do F="$F -f $f"; done
go run ./internal/devtools/check -f {{workspace}}/skeleton.yaml -f {{workspace}}/fixtures.yaml $F \
  --code {{snapshot.path}} --strict-citations --inventory {{workspace}}/inventory.json \
  --behavior-coverage --lint hollow,racy,seam-names --no-mocks
```

Other areas are editing at the same time, so a failure caused by another area's unfinished fix
isn't yours. Name it in your report, and don't work around it. Also run your standalone check
(skeleton, fixtures and your fragment). It must stay green, apart from scenarios that now need
another area's real definitions.

## Report (≤120 words)

Your failures, warnings and lint findings fixed and remaining (each remaining one with its cause
and the area it waits on), the stubs you defined, contracts you changed as an owner (with the
code citation), your skips file count, and the final check lines.
