# Model-quality baseline: Apache Cassandra 5.0.9 (examples/cassandra)

These numbers measure the model **before** its migration to the §11 language and the §12 quality gates (DESIGN §12, §13.1 items 5 and 7). They come from `internal/devtools/check` on 2026-10-30:

```sh
A="-f examples/cassandra/skeleton.yaml"; for f in examples/cassandra/fragments/*.yaml; do A="$A -f $f"; done
go run ./internal/devtools/check -q $A --lint hollow --no-mocks --behavior-coverage --behavior-coverage-md cov.md
```

```
entities: 502 components, 1365 interfaces, 0 links, 113 schemas, 270 flows, 1165 scenarios (15 boundary stubs)
validation: 0 errors, 0 warnings
scenarios: 1165 passed, 0 failed
mocks: 0 declared in 0 scenarios, 0 mocked calls
behavior coverage: 6281/7135 steps (88.0%) over 1165 scenarios, 554 unexecuted fail/if branches
hollow lint: 268 failing (268 unchecked state change, 0 writes flows without read-back), 243 advisory (no state change)
```

## By fragment

Both rules skip a scenario when an expectation mentions `state` or `trace`. **Unchecked** (it fails the check): the run records state `set` events. **No state change** (advisory, a warning only): the run is ok and records no state `set`, though the scenario can reach a state-writing interface (a store put, update, delete or incr, or a behavior that sets `state.*`). No flow carries the `writes` tag yet, so the write-then-read rule (§13.1 item 7) reports nothing; it will once flows are tagged.

| fragment | behavior steps run | steps | coverage | interfaces fully covered | unexecuted fail/if branches | scenarios | hollow: unchecked (gate) | hollow: no state change (advisory) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| coordination | 541 | 586 | 92.3% | 61/83 | 24 | 76 | 18 | 28 |
| cql | 448 | 505 | 88.7% | 52/75 | 60 | 133 | 11 | 43 |
| hints-batchlog | 341 | 363 | 93.9% | 44/58 | 13 | 56 | 6 | 6 |
| membership | 741 | 822 | 90.1% | 98/131 | 55 | 117 | 16 | 14 |
| ops | 742 | 999 | 74.3% | 126/242 | 146 | 175 | 58 | 80 |
| paxos | 542 | 617 | 87.8% | 51/71 | 44 | 72 | 32 | 3 |
| read-path | 562 | 600 | 93.7% | 61/81 | 23 | 90 | 11 | 19 |
| repair-streaming | 518 | 584 | 88.7% | 65/103 | 44 | 72 | 26 | 8 |
| schema-auth | 931 | 1058 | 88.0% | 122/184 | 111 | 199 | 24 | 26 |
| transport | 427 | 479 | 89.1% | 67/91 | 26 | 97 | 48 | 4 |
| write-path | 488 | 522 | 93.5% | 91/107 | 8 | 78 | 18 | 12 |

## Top uncovered branches

Interfaces with the most unexecuted `fail` steps and `if` branches:

| interface | fragment | unexecuted fail/if branches | behavior steps run |
|---|---|---:|---:|
| `batch-statement.validate-batch` | cql | 16 | 19/27 |
| `create-index-statement.apply` | schema-auth | 9 | 12/18 |
| `create-trigger-statement.apply` | schema-auth | 9 | 10/16 |
| `nodetool-compact.execute` | ops | 9 | 7/17 |
| `modification-statement.validate` | cql | 8 | 14/18 |
| `create-aggregate-statement.apply` | schema-auth | 7 | 5/12 |
| `nodetool-set-compaction-threshold.execute` | ops | 6 | 8/11 |
| `paxos.cas` | paxos | 6 | 35/43 |
| `storage-service.on-change` | membership | 6 | 28/38 |
| `storage-service.rebuild` | membership | 6 | 11/14 |
| `create-type-statement.apply` | schema-auth | 5 | 10/14 |
| `nodetool-clear-snapshot.execute` | ops | 5 | 4/7 |
| `nodetool-recompress-sstables.execute` | ops | 5 | 9/14 |
| `nodetool-scrub.execute` | ops | 5 | 9/14 |
| `nodetool-upgrade-sstable.execute` | ops | 5 | 9/14 |
| `nodetool-verify.execute` | ops | 5 | 8/12 |
| `paxos.read` | paxos | 5 | 14/24 |
| `pre-v5-handlers-legacy-dispatch-handler.check-limits` | transport | 5 | 9/24 |
| `storage-proxy.should-hint` | coordination | 5 | 18/25 |
| `storage-service.decommission` | membership | 5 | 33/37 |

A sample of the unexecuted branches in those interfaces (the error paths no scenario drives):

| kind | step path | what |
|---|---|---|
| if-then | `batch-statement.validate-batch:behavior[3].then` | if vars.tsSet && vars.hasConditions |
| fail | `batch-statement.validate-batch:behavior[3].then[0]` | {"code":"invalid","message":"Cannot provide custom timestamp for conditional BATCH","status":8704} |
| if-then | `batch-statement.validate-batch:behavior[4].then` | if vars.tsSet && input.statement.batch_type == 'COUNTER' |
| if-then | `create-index-statement.apply:behavior[3].then` | if !vars.rows.value.exists(r, r.kind == 'keyspace') |
| fail | `create-index-statement.apply:behavior[3].then[0]` | {"code":"invalid","message":"= \"Keyspace '\" + input.keyspace + \"' doesn't exist\"","status":8704} |
| if-then | `create-index-statement.apply:behavior[5].then` | if size(vars.table) == 0 |
| if-then | `create-trigger-statement.apply:behavior[1].then` | if !vars.rows.value.exists(r, r.kind == 'keyspace') |
| fail | `create-trigger-statement.apply:behavior[1].then[0]` | {"code":"invalid","message":"= \"Keyspace '\" + input.keyspace + \"' doesn't exist\"","status":8704} |
| if-then | `create-trigger-statement.apply:behavior[3].then` | if size(vars.table) == 0 |
| if-then | `nodetool-compact.execute:behavior[0].then` | if 'user-defined' in input.options && input.options['user-defined'] |
| if-then | `nodetool-compact.execute:behavior[0].then[0].then` | if 'split-output' in input.options && input.options['split-output'] |
| fail | `nodetool-compact.execute:behavior[0].then[0].then[0]` | {"code":"runtime-exception","message":"Invalid option combination: Can not use split-output here"} |
| if-then | `modification-statement.validate:behavior[3].then` | if vars.counter && input.statement.using_ttl > 0 |
| fail | `modification-statement.validate:behavior[3].then[0]` | {"code":"invalid","message":"Cannot provide custom TTL for counter updates","status":8704} |
| if-then | `modification-statement.validate:behavior[5].then` | if vars.virtual && vars.ts |
| if-then | `create-aggregate-statement.apply:behavior[0].then` | if input.or_replace && input.if_not_exists |
| fail | `create-aggregate-statement.apply:behavior[0].then[0]` | {"code":"invalid","message":"Cannot use both 'OR REPLACE' and 'IF NOT EXISTS' directives","status":8704} |
| if-then | `create-aggregate-statement.apply:behavior[2].then` | if !vars.rows.value.exists(r, r.kind == 'keyspace') |
| if-then | `nodetool-set-compaction-threshold.execute:behavior[0].then` | if size(input.args) != 4 |
| fail | `nodetool-set-compaction-threshold.execute:behavior[0].then[0]` | {"code":"illegal-argument-exception","message":"setcompactionthreshold requires ks, cf, min, and max threshold args."} |
| if-then | `nodetool-set-compaction-threshold.execute:behavior[2].then` | if vars.min < 0 \|\| vars.max < 0 |
| if-then | `paxos.cas:behavior[0].then` | if !(input.consistency in ['SERIAL', 'LOCAL_SERIAL']) |
| fail | `paxos.cas:behavior[0].then[0]` | Serial consistency refused |
| if-then | `paxos.cas:behavior[1].then` | if input.commit_consistency in ['SERIAL', 'LOCAL_SERIAL'] |
| if-then | `storage-service.on-change:behavior[0].then` | if !(input.state in ['STATUS', 'STATUS_WITH_PORT']) |
| if-then | `storage-service.on-change:behavior[5].then[0].then` | if vars.mem.value.member |
| if-then | `storage-service.on-change:behavior[10].then` | if input.value == 'removing' \|\| input.value == 'removed' |
| if-then | `storage-service.rebuild:behavior[0].then` | if has(input.source_dc) && input.source_dc == 'datacenter1' && has(input.exclude_local_dc) && input.exclude_local_dc |
| fail | `storage-service.rebuild:behavior[0].then[0]` | {"code":"illegal-argument-exception","message":"Cannot set source data center to be local data center, when excludeLocal… |
| if-then | `storage-service.rebuild:behavior[3].then` | if state.is_rebuilding |

The full per-interface list comes from `--behavior-coverage-md FILE`; `-v` prints every unexecuted step path.

## Precision of rule 1 ("no state change")

Rule 1 went through three versions:
- first, a scenario that could reach any store, reads included: 530 hits;
- then, only scenarios that can reach a state-writing interface: 494 hits, about 1 in 10 real;
- now, also exempting runs that fail and scenarios whose expectations mention `state` or `trace`: 243 hits.

Ten random hits under the current rule, classified by reading their flows and expectations:

| scenario | fragment | class |
|---|---|---|
| `cmd-enableautocompaction` | ops | **real hollow**: enabling auto-compaction changes no modeled state |
| `cmd-invalidatenetworkpermissionscache` | ops | **real hollow**: invalidating a cache changes no modeled state |
| `cql-write-list-index-reads-first` | cql | **real hollow**: a write that passes with only call counts checked |
| `cql-describe-tables-current-keyspace` | cql | read path, fine |
| `cfs-force-compaction-token-ranges-empty` | read-path | conditional write not taken (nothing to compact) |
| `decommission-unsupported` | ops | conditional write not taken (refused with exit status 1, result ok) |
| `grant-permissions-already-granted` | schema-auth | conditional write not taken (already granted) |
| `cleanup-jobs-above-compactors` | ops | conditional write not taken (only the warning output is modeled) |
| `audit-disabled-by-default` | ops | conditional write not taken (audit off) |
| `cql-drop-table-nothing-cached` | cql | conditional write not taken (nothing cached) |

Precision is 3/10. That is under 50%, so rule 1 is **advisory**: it prints `! hollow` and doesn't change the exit code. Rule 2 and the `writes` rule are the gate.

## Precision of rule 2 ("unchecked state change", the gate)

Ten random hits, classified as a real gap (an effect the scenario should assert) or noise (incidental bookkeeping):

| scenario | state set | class |
|---|---|---|
| `cmd-disablegossip` | gossiper, token-metadata | **real gap** |
| `cas-v2-rejected-writes-variant` | paxos-state | **real gap**: the promise is recorded |
| `cas-v1-commit-all-down-replica` | hints-*, paxos-state | **real gap**: the hint is written |
| `cas-v1-contention-timeout` | paxos-state | **real gap** |
| `permission-check-cache-expired` | auth-cache | **real gap**: the cache refresh is the behavior under test |
| `alter-role-own-password` | auth-cache | noise (cache) |
| `list-permissions-recursive` | auth-cache | noise (cache) |
| `execute-prepared` | client-resource-limits, client-warn | noise (limits, warnings) |
| `execute-page-size-zero` | client-resource-limits, client-warn | noise (limits, warnings) |
| `mem-response-failure` | request-callbacks | noise (callback bookkeeping) |

Precision is 5/10, under the 70% bar. The fix is to ignore state on **incidental** components: those whose kind or tag is `cache`, `limiter` or `metrics`, or that are tagged `incidental` (DESIGN §12). This model declares none, so its count is unchanged at 268. Its components are untyped (`module`, `function`), so name matching would be a guess, and the lint doesn't do it. As a rough upper bound, 64 of the 268 hits only set components whose names look like caches, limits, warnings or callbacks. All five noise hits above would go once the model declares those components incidental, and the projected count is about 204. Migration should declare them.

## Coverage levels: registered versus modeled (DESIGN §13.1 item 13)

Measured on 2026-10-30 against the round 2 model (skeleton, `fixtures.yaml` and every fragment). **Registered** is the existing covered count: something reachable cites the entry or is named for it. **Modeled** also needs an interface that cites the entry (or is named for it) to have a behavior or a `store`, and some scenario's trace to call it.

```sh
A="-f examples/cassandra/skeleton.yaml -f examples/cassandra/fixtures.yaml"; for f in examples/cassandra/fragments/*.yaml; do A="$A -f $f"; done
go run ./internal/devtools/check -q $A --inventory examples/cassandra/inventory.json --min-modeled 0.5
```

Totals: 445 of 483 unskipped entry points are modeled (92%) and 478 are registered (99%). 870 are skipped, and 3 aren't owned by any fragment. No fragment is below 0.5, so the gate passes.

| Kind | Registered | Modeled |
|---|---|---|
| background-task | 2/2 | 2 |
| cli-command | 88/88 | 88 |
| cql-statement | 56/56 | 56 |
| java-main | 2/2 | 1 |
| jmx-operation | 158/158 | 128 |
| messaging-verb | 81/81 | 81 |
| native-message | 8/8 | 8 |
| scheduled-task | 29/32 | 29 |
| stage-task | 17/19 | 15 |
| verb-handler | 37/37 | 37 |

| Fragment | Modeled / (owned − skipped) | Registered | Owned | Skipped |
|---|---|---|---|---|
| coordination | 94/95 (99%) | 95 | 105 | 10 |
| cql | 18/18 (100%) | 18 | 18 | 0 |
| hints-batchlog | 95/95 (100%) | 95 | 99 | 4 |
| membership | 98/98 (100%) | 98 | 133 | 35 |
| ops | 226/259 (87%) | 257 | 734 | 475 |
| paxos | 100/100 (100%) | 100 | 101 | 1 |
| read-path | 90/90 (100%) | 90 | 171 | 81 |
| repair-streaming | 91/92 (99%) | 92 | 93 | 1 |
| schema-auth | 137/137 (100%) | 137 | 156 | 19 |
| transport | 13/13 (100%) | 13 | 13 | 0 |
| write-path | 96/96 (100%) | 96 | 159 | 63 |
| skeleton.yaml (exempt: no interface with a behavior or a store) | 101/113 (89%) | 113 | 367 | 254 |

An entry counts toward every fragment that owns it, so the owned counts overlap. Most of the 33 entries that are registered but not modeled are JMX operations (158 registered, 128 modeled), and the largest per-fragment gap is ops (257 registered, 226 modeled). For these entries, the only reachable citation comes from a component, from an interface with no behavior or `store`, or from an interface that no scenario calls.

## Trivial behaviors and substantive coverage (DESIGN §13.1 item 15)

Measured on 2026-10-30 against the same round 2 model (skeleton, `fixtures.yaml` and every
fragment). A **trivial** interface has a behavior with no store and, at any depth, no `call`,
`if`, `when`, `choice`, `fail`, `emit` or `publish`, and at most two `set` steps. **Substantive**
entries are modeled by an interface that isn't trivial; declaration-only kinds would count once
registered (Cassandra has none).

```sh
A="-f examples/cassandra/skeleton.yaml -f examples/cassandra/fixtures.yaml"; for f in examples/cassandra/fragments/*.yaml; do A="$A -f $f"; done
go run ./internal/devtools/check -q $A --inventory examples/cassandra/inventory.json \
  --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35 --lint trivial
```

```
modeled: 445 of 483 entry points modeled (92%), 420 substantive (87%), 478 registered (99%), 3 owned by no fragment; --min-modeled 0.50: 0 fragments below; --min-substantive 0.50: 0 fragments below
trivial lint: 75 of 485 entry-citing interfaces trivial (15.5%); --max-trivial 0.35: 0 fragments above
```

Totals: 75 of 485 entry-citing interfaces are trivial (15.5%), and 420 of 483 unskipped entries
are substantive (87%), against 445 modeled. Only 25 modeled entries rest on a trivial interface.
The pipeline gate (`--min-substantive 0.5 --max-trivial 0.35`) passes; the highest trivial share
is coordination's 5 of 15 (the `on-response` callbacks), then ops' 56 of 209 (mostly JMX setters
that flip one flag, which are honest). This inventory has no `area` fields, so fragments own
entries by citation and the owned counts overlap, as above.

| Kind | Registered | Modeled | Substantive |
|---|---|---|---|
| background-task | 2/2 | 2 | 2 |
| cli-command | 88/88 | 88 | 88 |
| cql-statement | 56/56 | 56 | 55 |
| java-main | 2/2 | 1 | 1 |
| jmx-operation | 158/158 | 128 | 114 |
| messaging-verb | 81/81 | 81 | 74 |
| native-message | 8/8 | 8 | 8 |
| python-cli | 0/0 | 0 | 0 |
| scheduled-task | 29/32 | 29 | 28 |
| stage-task | 17/19 | 15 | 15 |
| verb-handler | 37/37 | 37 | 35 |

| Fragment | Modeled | Substantive | Trivial interfaces / entry-citing |
|---|---|---|---|
| coordination | 94/95 (99%) | 86/95 (91%) | 5/15 (33.3%) |
| cql | 18/18 (100%) | 17/18 (94%) | 4/57 (7.0%) |
| hints-batchlog | 95/95 (100%) | 88/95 (93%) | 2/15 (13.3%) |
| membership | 98/98 (100%) | 89/98 (91%) | 3/19 (15.8%) |
| ops | 226/259 (87%) | 212/259 (82%) | 56/209 (26.8%) |
| paxos | 100/100 (100%) | 93/100 (93%) | 0/34 (0.0%) |
| read-path | 90/90 (100%) | 83/90 (92%) | 0/10 (0.0%) |
| repair-streaming | 91/92 (99%) | 84/92 (91%) | 1/26 (3.8%) |
| schema-auth | 137/137 (100%) | 130/137 (95%) | 1/69 (1.4%) |
| skeleton (exempt) | 101/113 (89%) | 89/113 (79%) | - |
| transport | 13/13 (100%) | 13/13 (100%) | 2/18 (11.1%) |
| write-path | 96/96 (100%) | 89/96 (93%) | 1/13 (7.7%) |

For comparison, VS Code 1.144 (`examples/vscode/quality-baseline.md`): 512 of 2,155 trivial
(23.8%), 2,581 of 4,067 substantive (63%), and 4 fragments fail the gate.
