# Reconciliation round (VS Code)

All 13 fragments pass on their own. Merged, the ontology has 1,464 components, 3,465 interfaces,
421 flows and 1,395 scenarios, with 0 validation errors and all 11,327 citations resolving. But:

- **149 scenarios fail** in the merged run;
- there are **57 merge warnings** (25 stub-vs-stub, 32 stub-vs-owner) and **11 hollow-lint
  failures**;
- **5 areas are below the modeled-coverage gate** (`--min-modeled 0.5`, DESIGN §13.1 item 13):

| Area | Modeled | Registered | Notes |
|---|---|---|---|
| agents | 69/367 (19%) | 84 | 285 skips rejected: "not modeled" isn't a skip reason |
| builtin-extensions | 39/552 (7%) | 552 | 478 extension commands are covered by registration only |
| chat | 186/600 (31%) | 207 | 393 skips rejected ("not modeled") |
| exthost | 85/296 (29%) | 296 | the API functions are forwarding stubs |
| workbench-contribs | 46/443 (10%) | 443 | most contributions are constructor-only |

Every other area passes the gate: editor 60%, files-search-scm 53%, notebook-webview 81%,
platform-core 83%, workbench-shell 91%, remote-server 92%, terminal-debug-tasks 92% and
main-process 100%.

The rules in `BRIEF.md` still apply. Write only your fragment, notes and skips, plus any
`<area>-*` fixtures you define inside your own fragment (decision 10).

## Your inputs

- `reconcile/<area>.txt` lists your failing merged scenarios and the warnings and hollow findings
  that name your fragment.
- `reconcile/merged-check.txt` is the full merged output.
- `inventory.json` now carries `area` (the owner, from the profile's globs), `skip`, and `level`.
  `level: registered` marks `service` entries, which count as modeled once registered.
- You may now read the other areas' fragments for their contracts and seeded state. You still
  may not read their notes, `BENCHMARK.md` or `judge/`.

## Decisions (binding)

1. **The owner's contract wins.** Callers align their call sites and stubs to the owner's
   request, response, kind and errors, `retryable` included. Owners don't loosen a contract to
   fit a guess, unless the contract is wrong about the code; then the owner fixes it and says so.
2. **Files and disk use `resource`.** This fixes 52 aborts. Platform-core changes
   `file-service.*` and the `disk.*` stores to take and key by `resource` (the URI string),
   since the shared shapes list `resource` and VS Code's file APIs name it so. Every caller sends
   `resource`, never `uri`, to file-service and disk. Other interfaces may keep `uri` where
   their code says `uri`.
3. **`extension-service.activate-by-event` belongs to exthost.** It takes
   `ExthostActivateByEventRequest` and returns `ExthostActivationResult`. This fixes 27 aborts.
   Platform-core's `command-service.execute-command` and every other caller send exactly that
   shape, `activation_kind` included. Builtin-extensions deletes its stand-in activation and
   command-map components and calls exthost's seams.
4. **`vscode-api.*` belongs to exthost.** This fixes 21 aborts in the
   `window-show-*-message` calls. Builtin-extensions copies exthost's request shapes exactly.
   Exthost makes sure each `vscode-api` interface it defines has the parameters vscode.d.ts gives
   it.
5. **`bulk-edit-service.apply` belongs to workbench-contribs.** Callers (editor, exthost, chat)
   send its request shape. Workbench-contribs fixes the `if` that aborts on a missing field, if
   the field is optional in the code.
6. **Command registration.** `command-service.execute-command` resolves handlers from
   platform-core's `commands-registry`. Every area registers its modeled commands there by
   seeding the registry in its `<area>-seed` fixture (decision 10), keyed by command id and
   naming its `cmd-*` interface. Per-area routers (`execute-registered-command`,
   `files-area-registrations`) stay only as each area's internal dispatch. The seam is
   platform-core's.
7. **Seam ownership.** `command-service` and `configuration-service` stay with platform-core,
   even though their implementations sit under workbench/services. Workbench-shell keeps
   `editor-service`, `lifecycle-service`, workspace trust, notifications, dialogs, quick input and
   the clipboard (the registered implementations). Main-process keeps `native-host-main-service`
   and `extension-host-starter`. The renderer-side `native-host-service` belongs to
   workbench-shell, and window counts go through `native-host-main-service.get-window-count`.
   Component `kind` follows the owner, with `service` for services.
8. **Events.** Listeners subscribe to the owner's topics instead of being called directly:
   - exthost's `onWillActivateByEvent`, `onDidChangeExtensionsStatus` and `onWillStop`;
   - workbench-shell's `lifecycle-service.on-before-shutdown` (answer with
     `lifecycle-service.veto`) and `on-before-shutdown-final`;
   - files-search-scm's `text-file-models.on-did-*` and `working-copy-service.on-did-change-*`
     (workbench-shell's EditorAutoSave subscribes);
   - workbench-shell's `on-did-change-trust`.

   The editor calls `text-file-models.on-model-content-changed` on edits.
9. **Missing hops get restored.** Use the real hop instead of a shortcut:
   - remote-server installs go through workbench-shell's `ExtensionManagementService`
     (workbench-shell exposes the interface);
   - files-search-scm saves go through `editor-service.save`;
   - notebook's kernel picker goes through `command-service`;
   - terminal-debug-tasks' DAP goes through exthost's debug relay where the code uses one.

   If the owner's interface doesn't exist yet, the owner adds it in this round.
10. **Area fixtures.** Areas may now define fixtures **inside their own fragment**, with ids
    prefixed `<area>-`:
    - `<area>-seed` holds initial state for your own components only. Use plain component keys,
      which apply to every window or host instance. If you need state for one instance, use
      `@w1`.
    - Derived worlds (`<area>-notebook-open`, `editor-dirty`, `remote-srv1`, ...) extend the
      shared worlds.

    Your scenarios list them (`fixtures: [one-window-folder, <area>-seed]`). After this round
    the coordinator makes the shared worlds extend every `*-seed`. Requests for shared state
    (files on disk, settings, product values) go in your notes; the coordinator adds them to
    `fixtures.yaml`. Already added:
    - the `all-builtin-extensions` fixture;
    - git repository state in `base-workspace`;
    - the trusted-folder list in `one-window-folder` (`untrusted-folder` has an empty list).
11. **Coverage that counts.**
    - **Skip reasons:** a skip is valid only for:
      - not an entry point (a heuristic false positive);
      - a UI toggle;
      - developer or internal tooling;
      - an entry another area owns, naming the area;
      - the profile's exthost-rpc rule.

      Reasons starting with "not modeled", "out of scope", "too large" or "TODO" are rejected
      and count as uncovered.
    - **The modeled gate:** each area must reach **modeled ≥ 50%** of its non-skipped entries.
      Modeled means an interface citing the entry has a behavior or a store, **and** some
      scenario's trace calls it.
    - **What to model first:** start with entries a user or an extension triggers directly
      (commands, API functions, activation). A constructor-only contribution with no behavior
      counts as registered, not modeled.
12. **Wrong skips.** Workbench-shell restores `ICodeEditorService` and `ITreeSitterThemeService`.
    Agents drops the 5 entries listed as both covered and skipped. Exthost reviews its rpc skips
    for the stateful MainThread classes (SCM, terminal, quick open, comments): the owning areas
    model those classes or confirm they're pure pass-through.
13. **Trust fixture fallout.** Workbench-shell updates `workbench-shell-startup-untrusted` (use
    `untrusted-folder`), `-trust-empty-window` and `-untrust-not-directly-trusted` for the
    corrected trust list.
14. **Generators.** Areas that build their fragment from a script keep it under
    `examples/vscode/gen/<area>/`, and edit it there, not in /tmp. Copies of three generators
    (files-search-scm, remote-server, workbench-shell) are already there.

## Verify

Run the full merged gate:

```sh
cd /home/lbethay/workplace/mosaic
export PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly
F=""; for f in examples/vscode/fragments/*.yaml; do F="$F -f $f"; done
go run ./internal/devtools/check -f examples/vscode/skeleton.yaml -f examples/vscode/fixtures.yaml -f examples/vscode/worlds.yaml $F \
  --code /home/lbethay/.cache/mosaic-bench/vscode-1.144.0 --strict-citations \
  --inventory examples/vscode/inventory.json --behavior-coverage --lint hollow --no-mocks --min-modeled 0.5
```

After you change `skips/<area>.json`, refresh the inventory with
`python3 .claude/skills/mosaic-generate/scripts/assign_inventory.py examples/vscode`. Other agents
run it too, and it's idempotent.

**Exit criteria for your area:**
- none of your scenarios fail in the merged run;
- no merge warning or hollow failure names your fragment;
- modeled ≥ 50%;
- 0 mocks;
- citations ok.

Failures caused by another area's unfinished fix aren't yours: name them in your report, and
don't work around them.

## Report (≤150 words)

Report your failures and warnings fixed and remaining, each remaining one with its cause and the
area it waits on. Include modeled coverage before and after, fixtures you defined, requests for
shared fixtures, and the final gate lines.
