# Coordinator's running list for the VS Code reconciliation (becomes RECONCILE.md)

1. **"Not modeled" isn't a skip reason.** A skip is valid only when the entry isn't an entry
   point, is a UI toggle, or is developer/internal tooling, plus the profile's rules. Entries
   skipped as "not modeled: …" count as uncovered. Chat has 393 of these. The modeled gate
   (`--min-modeled 0.5`) applies per area.
2. **Contribution stubs** (a constructor with no behavior, cited only to cover an entry) count
   as registered, not modeled. Workbench-contribs has about 420 of these, chat 137.
3. **Command registration.** Every area registers its commands with platform-core's
   commands registry (`commands-registry.register-command`, or seeded registry state through a
   fixture). `command-service.execute-command` resolves the handler from there.
4. **Seam ownership.** `command-service` and `configuration-service` stay with platform-core,
   even though their implementations live under workbench/services. Record this in the
   profile's overrides.
5. **About 45 unassigned services** (declared in platform, implemented elsewhere) each need an
   owner (see notes/platform-core.md).
6. **`extension-service.activate-by-event`.** Platform-core guessed `{activation_event}`. Align
   to exthost's definition.
7. **Shared schemas** were added to skeleton.yaml after fan-out. Areas that inlined
   `FilesSaveOptions` switch to the shared one.
8. **Engine backlog** from this build:
   - a branch error can't propagate through a join;
   - a behavior can't wait until something registers;
   - steps can't overlap, so it can't show writes inside a 100 ms flush window landing as one
     batch;
   - a confirmation that blocks across user actions;
   - cancel racing an in-flight request;
   - a null config value is dropped;
   - a store `default: null` still fails;
   - optional request fields are always fake-filled.
9. **Builtin-extensions duplicates exthost.** Its two index components (activate and command
   map) stand in for exthost's activation and command dispatch. Replace them with exthost's
   `extension-service.activate-by-event` and the command-service seam once those exist.
10. **Fixtures added by the coordinator during the build:**
    - `all-builtin-extensions` (95 built-in extensions from package.json);
    - `git-binary.repositories` seeded in base-workspace.

    `language-server` seed: still to do.
11. **Notebook commands.** The ipynb `notebook.cellOutput.*` handlers are registered by the
    workbench notebook contribution, so they're notebook-webview's to cover.
12. **Exthost's contracts are now defined.**
    - `extension-service.activate-by-event` takes `ExthostActivateByEventRequest` and returns
      `ExthostActivationResult`. Platform-core and builtin-extensions align to it, replacing
      platform-core's `{activation_event}` guess and builtin-extensions' index components.
    - `vscode-api` is defined; builtin-extensions copies its contracts.
    - Exthost publishes 7 events (onWillActivateByEvent, onDidChangeExtensionsStatus,
      onWillStop, ...) that other areas should subscribe to where their code listens.
13. **Extension host registry fixture.** Exthost asks for `ext-host-extension-service@ehN` to be
    seeded with the host's extension registry. Exthost names the state key and shape, and the
    coordinator adds it to `one-window-folder` and `all-builtin-extensions`.
14. **Tool gap.** Coverage reachability doesn't follow publish/subscribe edges (reported by
    exthost). Fix in check/model reach.
15. **Exthost-rpc skip review.** The skip rule may be wrong for stateful MainThread classes
    (SCM, terminal, quick open, comments). Their owners must model those classes, or confirm
    they're pass-through.
16. **Notebook fixture requests:**
    - `file:///work/app/analysis.ipynb` on disk;
    - a `notebook-open` world with the jupyter-notebook and interactive serializers registered;
    - a registered kernel, with a canonical name to add (`python3` kernel from
      `ms-toolsai.jupyter`).
17. **Engine backlog: optional entry fields.** Optional entry fields are always fake-filled, so
    "absent" has to be encoded as `""`, `-1` or `null`. Two areas hit this (workbench-contribs,
    notebook-webview), and builtin-extensions hit related gaps. Proposal: entry and call inputs
    fill only required properties, plus those with `default` or `const`. Measure the effect on
    the Cassandra, gateway-platform and demo models before switching.
18. **Files-search-scm contracts.**
    - `text-file-service.save` takes `{resource, options}` and returns
      `{saved, resource, skipped, error_code}`.
    - `text-file-models` exposes get, resolve, save, revert and on-model-content-changed. The
      editor calls on-model-content-changed on edits.
    - Workbench-shell's EditorAutoSave subscribes to `working-copy-service.on-did-change-dirty`
      and `-content`, and to `text-file-models.on-did-*`.
    - The `editorService.save` hop through the editor input was elided, so reconcile it with
      workbench-shell.
    - `FilesSaveOptions` gained `ignore_modified_since`, `write_unlock` and `write_elevated`
      (done in the skeleton).
19. **Files fixture requests:**
    - `search-service@w1` with the file text provider registered;
    - a git SCM repository `scm0` (acceptInputCommand `git.commit`);
    - a clean, open `src/main.ts` model.
20. **Owner disputes.** Notification, clipboard, quick input and native host stubs disagree on
    owner and kind. Decide each by where the service is registered.
21. **Engine backlog: reading another component's state.** A behavior can't read another
    component's state, so all text file model logic sits on the anchor. Consider read-only
    `peek(component[@instance])` access, or require a store call.
22. **Generators** are kept in the repo under `examples/vscode/gen/<area>/` (files-search-scm
    copied from /tmp).
23. **Main-process contracts.**
    - `open-window` takes `folder_uris` / `file_uris` arrays. Workbench-shell's stub sends
      `folder_uri`, so it aligns.
    - Window count is `native-host-main-service.get-window-count`, not
      `native-host-service.get-window-count`. Three areas align.
    - `extension-host-starter` (`src/vs/platform/extensions/electron-main`) is main-process's,
      by the `*/electron-main/**` glob. Exthost's inventory credit for IExtensionHostStarter
      moves to main-process.
    - Four electron-browser components were renamed to `desktop-*` to avoid clashes.
24. **Merged failure.** `disk.write-file` is called without `uri` on the path backup-tracker →
    text-file-service.write → file-service.write-file. Two main-process scenarios abort on it.
    It's at the seam between files-search-scm and platform-core: check which side drops `uri`
    (`resource` vs `uri` naming).
25. **Main-process fixture requests:**
    - `windows-main-service` and `code-window` state for w1, and w2 for two-windows;
    - a "fresh window" world.
26. **Engine backlog: instance lifecycle.** A reloaded window keeps its old per-window state.
    The language has no "restart instance" that clears its state. Consider a `reset: <component
    group>@<instance>` step for a restart or reload, which reapplies the fixture's state for that
    instance.
27. **Editor.**
    - Format on save belongs to workbench-contribs, and the editor keeps the formatter functions
      (component `format`, field `resource`).
    - The merged failure `editor-suggest-accept-with-command` aborts in exthost's
      `activate-by-event`: platform-core's `execute-command` doesn't send `activation_kind`.
      That's item 12, and platform-core aligns.
    - Fixture requests:
      - add editor-side state (`text-model@w1`, `code-editor-widget@w1`,
        `cursors-controller@w1`) to `dirty-editor`;
      - a world with the TypeScript providers registered.
28. **Engine backlog.**
    - CEL has no regex replace. Add `replace(s, regex, repl)`, and `matches` with groups.
    - Negative answers from another area can't be driven without mocks (7 editor branches, and
      several others). In the merged model most become drivable through the owner's state;
      re-measure after reconciliation before adding anything.
29. **Remote-server.**
    - **Finding:** the OSS product.json has no `extensionsGallery` and no sync store, so as
      deployed, installs fail and the sync commands aren't registered. Scenarios override this.
      Add product worlds with the Marketplace and sync enabled, as fixtures with config
      overrides.
    - **Skipped hop:** installs skip workbench-shell's `ExtensionManagementService` and call the
      shared-process channel directly. Restore the hop in reconciliation.
    - **Fixture requests:** a `remote-folder` world with `srv1`, and a seeded user extension in
      the default profile.
    - **Generator** copied to `examples/vscode/gen/remote-server/`.
30. **Engine backlog: dynamic `set` paths.** `set` paths can't be computed, so keyed state is
    forced into store tables (reported by remote-server, and by Cassandra transport earlier).
    Proposal: `set: {"= 'state.sessions.' + vars.id": value}`, where a key starting with `=`
    is evaluated to a path.
31. **Agents.**
    - 552 of 636 entries are skipped. Review them under rule 1: agent-host internals that really
      are entry points need modeling.
    - The 5 entries both covered and skipped are tolerance matches, so drop them from skips.
    - Fixture requests: a trust answer driven by `untrusted-folder`, and a shared MCP-servers
      fixture.
    - Ids: `mcp-server-runtime` and `local-agent-host-service-client` stand.
32. **Workbench-shell.**
    - Shutdown participants subscribe to `lifecycle-service.on-before-shutdown` and answer by
      calling `lifecycle-service.veto`. The final participant (the backup tracker) subscribes
      to `on-before-shutdown-final`.
    - `ICodeEditorService` and `ITreeSitterThemeService` were wrongly skipped as UI toggles;
      restore them.
    - Fixture fixes:
      - `one-window-folder`'s trusted-URI list must contain `file:///work/app` (the coordinator
        does this);
      - add an untitled multi-root workspace world.
    - Generator copied to `examples/vscode/gen/workbench-shell/`.
33. **Cross-cutting merged aborts (top priority):**
    - **`disk.*` wants `input.uri`.** Files-search-scm sends another field (probably
      `resource`), which breaks main-process, workbench-shell and others. Decision:
      platform-core's file-service and disk interfaces use `resource` per the shared shapes
      ("`resource`: a URI, as `uri`"). `uri` is the alias, so align on `resource`. Wait: the
      shared shapes list both. Pick **`resource`** for file-service/disk, as VS Code's own APIs
      name it.
    - **`activation_kind`.** See items 12 and 27.
34. **Trust fixture (moved to workbench-shell-seed).** `one-window-folder` now seeds
    `workspace-trust-management-service@w1.uri_trust_info: ["file:///work/app"]`, and
    `untrusted-folder` seeds `[]`. Three workbench-shell scenarios that relied on the empty list
    now fail and must be updated:
    - `workbench-shell-startup-untrusted` (use the `untrusted-folder` fixture);
    - `workbench-shell-trust-empty-window`;
    - `workbench-shell-untrust-not-directly-trusted`.
35. **Final fixture wiring, after the reconciliation round (coordinator):**
    - `one-window-folder` extends every `*-seed`;
    - `two-windows` extends `main-process-two-windows`, and the other areas' w2 variants if any.

    Check for cycles: the seeds must not extend shared worlds.
36. **Final mini-round (after workbench-contribs).**
    - **Main-process:** its stubs of lifecycle-service and editor-service say `kind: module`. Drop
      the kind and parent.
    - **Agents' requests:**
      - chat: `acquire-or-load-session`, the `automation-service` contract, and registering
        `triggerSetup`;
      - workbench-shell: `mcp install` and `authentication remove-session`;
      - platform-core: the `opener` and `secret-storage` contracts.
    - **Agents jumped to 97% modeled (69 → 417).** Spot-check that the behaviors are real, not
      one-step returns. The judges and the oracle will test this.
37. **Behavior depth, measured by the coordinator after the round.** For own non-stub interfaces, I
    counted the share whose behavior is only `return`, or 1–2 `set` steps with no call, `if` or
    `fail`:

    | Area | Trivial behaviors |
    |---|---|
    | chat | 59% |
    | agents | 42% |
    | remote-server | 37% |
    | terminal-debug-tasks | 31% |
    | others | 4–27% |

    The modeled gate counts these as modeled. **Tool backlog:** report "modeled (substantive)"
    next to modeled, and add a `--lint trivial` that lists entry interfaces whose behavior is
    trivial. The oracle and judges will show whether the trivial ones matter.
38. **Exthost owner gap (for the judges, or a later round).** Exthost doesn't register the
    `setContext` → `_setContext` API command (`extHostApiCommands.ts:532`). Builtin git
    continues past it with on_error.
39. **`worlds.yaml` is missing `agents-seed`** (and any seed defined after it was generated).
    Regenerate it from the fragments after judging, not now, so the model doesn't change under
    the judges. Tool backlog: generate `worlds.yaml` in `assign_inventory.py` (or a sibling
    script), so it never goes stale.
40. **Oracle (stage 6) shows the coverage illusion.** Sampled tests mostly hit unmodeled or
    stubbed services; three oracle groups passed 1 of 31 tests. Pipeline changes for RESULTS:
    - validate skip reasons that claim coverage by another entity (the entity must exist);
    - run a sample of the oracle during the build, before hand-off, not only at the end;
    - report modeled coverage weighted by test density, so the denominator reflects what the
      repo's tests exercise.
