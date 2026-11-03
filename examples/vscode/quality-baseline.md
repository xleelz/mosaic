# Model-quality baseline: VS Code 1.144 (examples/vscode)

The trivial lint and the substantive level of DESIGN §13.1 item 15, measured on 2026-10-30
against the merged model after judging: `skeleton.yaml`, `fixtures.yaml`, `worlds.yaml`
(regenerated with `assign_inventory.py --worlds`) and all 13 fragments, with the inventory as
committed (its skips were merged before skip validation existed).

```sh
F=""; for f in examples/vscode/fragments/*.yaml; do F="$F -f $f"; done
go run ./internal/devtools/check -q -f examples/vscode/skeleton.yaml -f examples/vscode/fixtures.yaml \
  -f examples/vscode/worlds.yaml $F --code /home/lbethay/.cache/mosaic-bench/vscode-1.144.0 --strict-citations \
  --inventory examples/vscode/inventory.json --behavior-coverage --lint hollow,trivial --no-mocks \
  --min-modeled 0.5 --min-substantive 0.5 --max-trivial 0.35
```

```
scenarios: 1879 passed, 0 failed
citations: 15552 cited, 15552 ok, 0 missing, 0 bad_line, 0 dir, 0 packed, 0 skipped; 0 entities with problems
coverage: 3763 of 4067 entry points covered (93%), 2019 skipped, 304 not covered
modeled: 3087 of 4067 entry points modeled (76%), 2581 substantive (63%), 3763 registered (93%), 5 owned by no fragment; --min-modeled 0.50: 0 fragments below; --min-substantive 0.50: 1 fragments below
hollow lint: 0 failing (0 unchecked state change, 0 writes flows without read-back), 48 advisory (no state change)
trivial lint: 512 of 2155 entry-citing interfaces trivial (23.8%); --max-trivial 0.35: 3 fragments above
```

**Totals.** 512 of the 2,155 flow-reachable interfaces that cite an entry point are trivial
(23.8%): 237 only return, 272 set one field, 3 set two. 2,581 of the 4,067 unskipped entries are
substantive (63%), against 3,087 modeled (76%) and 3,763 registered (93%). So 506 entries counted
as modeled rest on a trivial interface.

**The gate.** Without the new flags the merged gate passes as before (exit 0; 1,879 of 1,879
scenarios, same hollow-lint and behavior-coverage lines as `quality-gate.txt`). With the
pipeline's `--min-substantive 0.5 --max-trivial 0.35` it fails 4 fragments: agents (49.8%
trivial), chat (42.3%), exthost (37.1%), and workbench-contribs (49% substantive). Cassandra
passes both (`examples/cassandra/quality-baseline.md`).

## By kind

Declaration-only kinds (`level: registered`, here `service`) count as substantive once
registered.

| Kind | Registered | Modeled | Substantive |
|---|---|---|---|
| activation-event | 74/74 | 74 | 57 |
| cli-command | 37/37 | 37 | 11 |
| cron | 0/3 | 0 | 0 |
| extension-api | 121/121 | 121 | 120 |
| extension-command | 478/478 | 320 | 253 |
| extension-point | 55/55 | 21 | 12 |
| exthost-customer | 87/87 | 87 | 15 |
| exthost-rpc | 121/121 | 120 | 86 |
| ipc-channel | 97/97 | 95 | 34 |
| process-main | 29/31 | 24 | 17 |
| python-cli | 0/1 | 0 | 0 |
| service | 666/669 | 666 | 666 |
| vscode-command | 1352/1647 | 1095 | 1060 |
| workbench-contribution | 646/646 | 427 | 250 |

## By fragment

The fragment owns the entries the profile assigns to its area. "Trivial" is over the fragment's
flow-reachable interfaces that cite an unskipped entry and have a behavior or a store.

| Fragment | Modeled | Substantive | Trivial interfaces / entry-citing |
|---|---|---|---|
| agents | 417/432 (97%) | 292/432 (68%) | 128/257 (49.8%) |
| builtin-extensions | 394/552 (71%) | 310/552 (56%) | 77/350 (22.0%) |
| chat | 344/560 (61%) | 328/560 (59%) | 41/97 (42.3%) |
| editor | 256/427 (60%) | 256/427 (60%) | 4/253 (1.6%) |
| exthost | 377/396 (95%) | 270/396 (68%) | 124/334 (37.1%) |
| files-search-scm | 168/191 (88%) | 150/191 (79%) | 19/153 (12.4%) |
| main-process | 117/117 (100%) | 61/117 (52%) | 2/36 (5.6%) |
| notebook-webview | 79/130 (61%) | 76/130 (58%) | 4/57 (7.0%) |
| platform-core | 101/106 (95%) | 101/106 (95%) | 0/8 (0.0%) |
| remote-server | 189/189 (100%) | 159/189 (84%) | 31/113 (27.4%) |
| skeleton (exempt) | 0/1 (0%) | 0/1 (0%) | - |
| terminal-debug-tasks | 199/199 (100%) | 166/199 (83%) | 43/167 (25.7%) |
| workbench-contribs | 224/443 (51%) | 217/443 (49%) | 9/192 (4.7%) |
| workbench-shell | 222/319 (70%) | 195/319 (61%) | 30/138 (21.7%) |

The kinds with the widest gap between modeled and substantive are `exthost-customer` (87 → 15),
`ipc-channel` (95 → 34), `cli-command` (37 → 11) and `workbench-contribution` (427 → 250): many of
their interfaces register a handler and return.

## What a trivial hit looks like

The lint lists each one (without `-q`). A seeded sample of six:

| Interface | Fragment | Behavior |
|---|---|---|
| `main-thread-chat-artifact-integrations.create` | exthost | only return |
| `git-command-center.cmd-git-repositories-copystashname` | builtin-extensions | only return |
| `extension-mcp-discovery.start` | agents | 1 set |
| `code-cli.cli-agent-host` | remote-server | only return |
| `main-thread-comments.register-comment-controller` | exthost | 1 set |
| `search-editor-actions.cmd-search-searcheditor-action-deletefileresults` | files-search-scm | 1 set |

Some are honest (a registration that only records a handler), most stand for logic the code
has (copying a stash name, deleting search results). The gate is the share, not each hit.

## Skip validation

`assign_inventory.py` now rejects a skip that says "covered by" without a `covered_by` entity.
913 exthost skips (`"RPC plumbing: <x> forwards to <y>; covered by the service interface it
forwards to"`) have no `covered_by`; only 201 of their `forwards to` targets name an existing
entity. Re-running `assign_inventory.py examples/vscode` would reject all 913. Exthost would then
drop to 377/1,309 modeled (29%) and 270 substantive (21%), failing `--min-modeled 0.5`, and
coverage would fall to 3,763 of 4,980 (76%). The committed `inventory.json` was left as it was;
fixing it means adding `covered_by` to the exthost skips (or modeling the forwards), an exthost
task.

## Merged worlds

`worlds.yaml` is now generated (`assign_inventory.py examples/vscode --worlds`) from the
profile's `fixtures.worlds` (with `full_id` for `full-window` and `full-untrusted`, `full: false`
for `base-workspace`, and the two overlays under `fixtures.derived`). Against the hand-written
file it differs only by adding `agents-seed` to the four `full-*` worlds; the area variants
(`main-process-two-windows`, `workbench-shell-untrusted`, `editor-dirty`) are found by rule.
`platform-core` defines no seed.

## Test reach and features (DESIGN §13.1 item 19)

Measured on 2026-10-31 against the same merge (skeleton, fixtures, worlds and the 13 fragments;
1,879 of 1,879 scenarios pass).

```sh
python3 .claude/skills/mosaic-generate/scripts/test_targets.py examples/vscode
go run ./internal/devtools/check -q -f examples/vscode/skeleton.yaml -f examples/vscode/fixtures.yaml \
  -f examples/vscode/worlds.yaml $F --tests examples/vscode/test-targets.json --min-test-reach 0.5 \
  --features examples/vscode/profile.yaml
```

**Test targets.** 2,866 test files (`**/*.test.ts` under the profile's test dirs); 2,862 (100%)
resolve at least one target, 9.1 targets each on average. 18 targets imported by more than 10% of
the tests (`lifecycle.ts`, `uri.ts`, `event.ts`, the instantiation service...) are dropped from
tests that have others.

**Test reach: 1,469 of 2,862 (51%).** `--min-test-reach 0.5` fails 5 areas.

| Area | Reached / resolved | Reach |
|---|---|---|
| agents | 482/905 | 53% |
| builtin-extensions | 22/141 | **16%** |
| chat | 354/525 | 67% |
| editor | 91/185 | **49%** |
| exthost | 99/108 | 92% |
| files-search-scm | 44/74 | 59% |
| main-process | 12/33 | **36%** |
| notebook-webview | 30/56 | 54% |
| platform-core | 72/363 | **20%** |
| remote-server | 43/60 | 72% |
| terminal-debug-tasks | 79/159 | **49.7%** |
| workbench-contribs | 73/135 | 54% |
| workbench-shell | 68/118 | 58% |

**Features.** The profile has no `features` yet, so `--features` reports 0 of 0; the feature
list is written in stage 2 of the next build.

**Against the oracle.** Of the 45 stage-6 oracle tests, 25 are reached and 20 aren't.
- Translatable tests pass at 18% when reached (4 of 22) and 9% when not (1 of 11): the direction
  is right, but most reached tests are still model bugs (18 of 22). Reach is file-level and
  generous: a test counts once any target file is cited, even when the feature it checks isn't
  modeled.
- Untranslatable tests are mostly unreached (9 of 12): low reach often marks code below the
  model's level, not a model gap. The two lowest areas show it: platform-core (20%) had 3 of 3
  oracle tests untranslatable (DOM, platform constants) and builtin-extensions (16%) 2 of 3.
- By area there is no clear correlation: exthost has the highest reach (92%) and 4 of 4 oracle
  tests were model bugs; main-process (36%) had 3 of 3.

So test reach is a necessary signal, not a sufficient one. Its use is the `-v` list of unreached
tests per area, which names code no scenario runs.
