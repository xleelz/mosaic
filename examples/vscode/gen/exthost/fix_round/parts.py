import os
HERE = os.path.dirname(os.path.abspath(__file__)) + '/'
def apply(src, g):
    sub_once = g['sub_once']; sub_in_comp = g['sub_in_comp']; sub_in_iface = g['sub_in_iface']
    replace_iface = g['replace_iface']; insert_before_section = g['insert_before_section']

    # ---------------- fixture: manifest capabilities (X8) ----------------
    src = sub_once(src, """  state:
    ext-host-extension-service:
      registry:
""", """  state:
    extension-registry@w1:
      extensions:
        vscode.git:
          capabilities:
            untrusted_workspaces:
              supported: false
        vscode.typescript-language-features:
          capabilities:
            untrusted_workspaces:
              supported: false
        vscode.markdown-language-features:
          capabilities:
            untrusted_workspaces:
              supported: limited
    ext-host-extension-service:
      registry:
""")

    # ---------------- component state ----------------
    src = sub_in_comp(src, 'ext-host-commands', """        commands:
          type: array
          items:
            type: string
    initial:
      commands: []
""", """        commands:
          type: array
          items:
            type: string
        api_commands:
          type: object
          description: ExtHostCommands._apiCommands, filled by ExtHostApiCommands.register at API creation (extHost.api.impl.ts:289); id -> internal id and argument validators
    initial:
      commands: []
      api_commands:
        vscode.executeWorkspaceSymbolProvider:
          internal_id: _executeWorkspaceSymbolProvider
          args:
          - string
        vscode.executeDocumentSymbolProvider:
          internal_id: _executeDocumentSymbolProvider
          args:
          - uri
        vscode.executeFormatDocumentProvider:
          internal_id: _executeFormatDocumentProvider
          args:
          - uri
          - any
        vscode.executeDefinitionProvider:
          internal_id: _executeDefinitionProvider
          args:
          - uri
          - position
        setContext:
          internal_id: _setContext
          args:
          - string
          - any
""")
    src = sub_in_comp(src, 'ext-host-debug-service', """        adapters:
          type: object
    initial:
      adapters: {}
""", """        adapters:
          type: object
        descriptor_factories:
          type: object
        vis_providers:
          type: object
        visualizers:
          type: object
        vis_counter:
          type: integer
    initial:
      adapters: {}
      descriptor_factories: {}
      vis_providers: {}
      visualizers: {}
      vis_counter: 0
""")
    src = sub_in_comp(src, 'main-thread-editor-tabs', """  attributes:
    owner: exthost
""", """  attributes:
    owner: exthost
  state:
    schema:
      type: object
      properties:
        groups:
          type: object
          description: _groupLookup, group id -> the editors (tab inputs) in tab order
        tab_ids:
          type: array
          items:
            type: string
          description: _tabInfoLookup keys (groupId~editor)
        rebuilds:
          type: integer
    initial:
      groups: {}
      tab_ids: []
      rebuilds: 0
""")
    src = sub_in_comp(src, 'ext-host-editor-tabs', """  attributes:
    owner: exthost
""", """  attributes:
    owner: exthost
  state:
    schema:
      type: object
      properties:
        groups:
          type: object
          description: _extHostTabGroups, group id -> tab ids
        active_group:
          type: integer
    initial:
      groups: {}
      active_group: 0
""")
    src = sub_in_comp(src, 'main-thread-debug-service', """  attributes:
    owner: exthost
""", """  attributes:
    owner: exthost
  state:
    schema:
      type: object
      properties:
        visualizer_handles:
          type: object
    initial:
      visualizer_handles: {}
""")
    _c, _i = stubs()
    src = insert_before_section(src, 'interfaces', NEW_COMPONENTS + _c)
    src = insert_before_section(src, 'flows', _i)

    # ---------------- X8: initialize filters by trust ----------------
    src = sub_in_iface(src, 'extension-service', 'initialize', """  - title: Resolve local extensions, keep the enabled ones, register them and run the extension point handlers
    source: src/vs/workbench/services/extensions/common/abstractExtensionService.ts:518-582
    call: extension-registry.snapshot
    as: snap
""", """  - title: Resolve the local extensions (the scanned set before enablement)
    source: src/vs/workbench/services/extensions/common/abstractExtensionService.ts:518-525
    call: extension-registry.snapshot
    as: scanned
  - title: checkEnabledAndProposedAPI asks the enablement service; in an untrusted workspace it disables (DisabledByTrustRequirement) every extension with code whose untrustedWorkspaces support is false
    source: src/vs/workbench/services/extensions/common/abstractExtensionService.ts:525-533
    call: workspace-trust-management-service.is-workspace-trusted
    as: trust
  - if: '!vars.trust.value.trusted'
    then:
    - title: 'getExtensionUntrustedWorkspaceSupportType: no main -> supported; else the manifest capabilities.untrustedWorkspaces.supported, else the default false (no product.json overrides)'
      source: src/vs/workbench/services/extensions/common/extensionManifestPropertiesService.ts:314-345
      set:
        vars.disabled: '= vars.scanned.value.extensions.filter(e, e.main != '''' && !(''untrusted_workspaces'' in e.capabilities && ''supported'' in e.capabilities.untrusted_workspaces && !(type(e.capabilities.untrusted_workspaces.supported)
          == bool && !e.capabilities.untrusted_workspaces.supported))).map(e, e.identifier)'
    - if: size(vars.disabled) > 0
      then:
      - title: Disabled extensions are never registered, so they are not sent to the host and their activation events find nothing
        source: src/vs/workbench/services/extensionManagement/browser/extensionEnablementService.ts:494-495
        call: extension-registry.delta-extensions
        input:
          to_add: []
          to_remove: = vars.disabled
  - title: Register the enabled extensions and run the extension point handlers
    source: src/vs/workbench/services/extensions/common/abstractExtensionService.ts:533-582
    call: extension-registry.snapshot
    as: snap
  - call: workspace-context.get-workspace
    as: ws
  - set:
      vars.remote: '= has(vars.ws.value.remote_authority) ? vars.ws.value.remote_authority : '''''
  - if: vars.remote != ''
    then:
    - title: 'determineExtensionHostKinds: an extension with code and no extensionKind defaults to [''workspace''], which runs on the remote host in a remote window; only UI/web ones stay local'
      source: src/vs/workbench/services/extensions/common/extensionHostKind.ts:47-88
      set:
        vars.remote_exts: = vars.snap.value.extensions.filter(e, e.main != '')
        vars.local_exts: = vars.snap.value.extensions.filter(e, e.main == '')
    - title: the remote window also creates a RemoteExtensionHost (ExtensionHostKind.Remote) and starts it
      source: src/vs/workbench/services/extensions/electron-browser/nativeExtensionService.ts:585-589
      call: remote-extension-host.start
      input:
        remote_authority: = vars.remote
        extensions: = vars.remote_exts
    else:
    - set:
        vars.local_exts: = vars.snap.value.extensions
""")
    src = sub_in_iface(src, 'extension-service', 'initialize', "        extensions: = vars.snap.value.extensions\n", "        extensions: = vars.local_exts\n")
    # snapshot keeps capabilities
    src = sub_in_iface(src, 'extension-registry', 'snapshot', """''extension_dependencies'' in v ? v.extension_dependencies : []})'""",
        """''extension_dependencies'' in v ? v.extension_dependencies : [], ''capabilities'': ''capabilities'' in v ? v.capabilities : {}})'""")

    # ---------------- API commands + setContext ----------------
    src = sub_in_iface(src, 'ext-host-commands', 'execute-command', """  behavior:
  - if: input.command_id in state.commands
""", """  behavior:
  - if: input.command_id in state.api_commands
    then:
    - title: An API command is registered in this host (registerCommand(false, ...)); emit onCommand activation (not awaited) and run its handler here
      source: src/vs/workbench/api/common/extHostCommands.ts:180-186
      emit: main-thread-commands.fire-command-activation-event
      'on': = 'w' + self.substring(2)
      input:
        command_id: = input.command_id
    - call: ext-host-commands.run-api-command
      input:
        command_id: = input.command_id
        args: = input.args
      as: api
    - return:
        value: = vars.api.value.value
  - if: input.command_id in state.commands
""")
    src = sub_in_iface(src, 'vscode-api', 'commands-execute-command', """  errors:
  - code: command-not-found
    status: 0
    retryable: false
""", """  errors:
  - code: command-not-found
    status: 0
    retryable: false
  - code: invalid-argument
    status: 0
    retryable: false
""")
    src = replace_iface(src, 'main-thread-commands', 'register-command', MT_REGISTER_COMMAND)
    src = sub_in_iface(src, 'main-thread-commands', 'execute-command', """  behavior:
  - choice: registered
    default: '= input.command_id in state.registrations ? ''known'' : ''known'''
    options:
      known: []
      unknown:
      - if: input.retry && size(input.args) > 0
        then:
        - title: Unknown command with arguments; activate onCommand:<id> and ask the host to retry
          source: src/vs/workbench/api/browser/mainThreadCommands.ts:87-90
          call: extension-service.activate-by-event
          input:
            activation_event: = 'onCommand:' + input.command_id
            activation_kind: normal
        - fail:
            code: execute-command-retry
            message: $executeCommand:retry
""", """  behavior:
  - if: input.retry && size(input.args) > 0
    then:
    - title: CommandsRegistry.getCommand(id)
      source: src/vs/workbench/api/browser/mainThreadCommands.ts:87
      call: commands-registry.get-command
      input:
        command_id: = input.command_id
      as: known
      on_error: continue
    - if: '!vars.known.ok'
      then:
      - title: Unknown command with arguments; activate onCommand:<id> and ask the host to retry
        source: src/vs/workbench/api/browser/mainThreadCommands.ts:87-90
        call: extension-service.activate-by-event
        input:
          activation_event: = 'onCommand:' + input.command_id
          activation_kind: normal
      - fail:
          code: execute-command-retry
          message: $executeCommand:retry
""")
    src = replace_iface(src, 'main-thread-commands', 'create', MT_COMMANDS_CREATE)

    # ---------------- editor tabs ----------------
    src = replace_iface(src, 'main-thread-editor-tabs', 'create', MT_EDITOR_TABS_CREATE)

    # ---------------- DA session ----------------
    src = replace_iface(src, 'ext-host-debug-service', 'start-da-session', START_DA)
    src = replace_iface(src, 'ext-host-debug-service', 'stop-da-session', STOP_DA)
    src = sub_in_iface(src, 'ext-host-debug-service', 'register-debug-adapter-descriptor-factory', """  response: ExthostApiResult
""", """  response: ExthostApiResult
  errors:
  - code: factory-already-registered
    status: 0
    retryable: false
  behavior:
  - title: make sure that only one factory for this type is registered
    source: src/vs/workbench/api/common/extHostDebugService.ts:546-549
    if: input.debug_type in state.descriptor_factories
    then:
    - fail:
        code: factory-already-registered
        message: a DebugAdapterDescriptorFactory can only be registered once per a type.
  - title: keep the factory and tell the window ($registerDebugAdapterDescriptorFactory)
    source: src/vs/workbench/api/common/extHostDebugService.ts:551-554
    set:
      state.descriptor_factories: '= merge(state.descriptor_factories, {input.debug_type: input.extension_id})'
  - return:
      disposable_id: = 'debug-adapter-factory:' + input.debug_type
""")

    # ---------------- small real logic ----------------
    src = sub_in_iface(src, 'vscode-api', 'languages-match', """  behavior:
  - return:
      score: '= has(input.document) && has(input.document.language_id) && input.document.language_id == input.selector ? 10 : 0'
""", """  behavior:
  - set:
      vars.language: '= has(input.document) && has(input.document.language_id) ? input.document.language_id : '''''
  - title: a '*' string selector scores 5
    source: src/vs/editor/common/languageSelector.ts:54-55
    if: input.selector == '*'
    then:
    - return:
        score: 5
  - title: a language id equal to the document's language scores 10, anything else 0
    source: src/vs/editor/common/languageSelector.ts:56-60
    if: input.selector == vars.language
    then:
    - return:
        score: 10
  - return:
      score: 0
""")
    src = sub_in_iface(src, 'user-trusted-extension-id-storage', 'set', """  behavior:
  - set:
      state.extensions: = input.extensions
""", """  behavior:
  - set:
      state.extensions: = input.extensions
  - title: storageService.store('extensionUrlHandler.confirmedExtensions', JSON.stringify(ids), PROFILE, MACHINE)
    source: src/vs/workbench/services/extensions/browser/extensionUrlHandler.ts:63-65
    call: storage-service.store
    input:
      key: extensionUrlHandler.confirmedExtensions
      value: = '[' + input.extensions.map(e, '"' + e + '"').join(',') + ']'
      scope: profile
""")
    src = sub_in_iface(src, 'main-thread-language-features', 'set-language-configuration', """  behavior:
  - title: ILanguageConfigurationService.register for the language (editor area); no provider registry entry
    source: src/vs/workbench/api/browser/mainThreadLanguageFeatures.ts:979
    set:
      vars.language: = input.selector
  - return:
      registered: true
""", """  behavior:
  - title: Revive the configuration DTO (comments, brackets, word pattern, rules)
    source: src/vs/workbench/api/browser/mainThreadLanguageFeatures.ts:981-1007
    set:
      vars.config: '= has(input.configuration) ? input.configuration : {}'
  - title: Only a registered language id gets the configuration (isRegisteredLanguageId); the model has no language registry, so the selector is taken as registered
    source: src/vs/workbench/api/browser/mainThreadLanguageFeatures.ts:1009-1011
    call: language-configuration-service.register
    input:
      language_id: = input.selector
      line_comment: '= ''comments'' in vars.config && ''line_comment'' in vars.config.comments ? vars.config.comments.line_comment : '''''
  - return:
      registered: true
""")
    src = sub_in_iface(src, 'main-thread-language-features', 'set-language-configuration', """      selector:
        type: string
""", """      configuration:
        type: object
        description: ILanguageConfigurationDto
      selector:
        type: string
""")
    src = sub_in_iface(src, 'vscode-api', 'languages-set-language-configuration', """      extension_id: = input.extension_id
""", """      extension_id: = input.extension_id
      configuration: = input.configuration
""") if False else src
    src = sub_in_iface(src, 'ext-host-language-features', 'set-language-configuration', """      selector: '= has(input.selector) ? input.selector : (has(input.language) ? input.language : '''')'
      extension_id: = input.extension_id
""", """      selector: '= has(input.selector) ? input.selector : (has(input.language) ? input.language : '''')'
      extension_id: = input.extension_id
      configuration: = input.configuration
""")

    # call-api targets: add the debug visualization API
    src = sub_once(src, """    - vscode-api.debug-remove-breakpoints
    - vscode-api.debug-start-debugging
""", """    - vscode-api.debug-register-debug-visualization-provider
    - vscode-api.debug-remove-breakpoints
    - vscode-api.debug-start-debugging
""")

    src = sub_once(src, """  choices:
    main-thread-commands.execute-command.registered: unknown
""", "")
    src = src.replace("  fixtures:\n  - dirty-editor\n  - exthost-seed\n", "  fixtures:\n  - full-dirty-editor\n")
    src = sub_in_iface(src, 'ext-host-commands', 'execute-command', "      retry: = input.retry\n", "      retry: '= has(input.retry) ? input.retry : true'\n")
    src = sub_in_iface(src, 'main-thread-language-features', 'register-navigate-type-support', open(HERE + 'navtype_old.yaml').read(), open(HERE + 'navtype_new.yaml').read())
    # auth getSession path and vscode.open (follow-up)
    src = sub_in_comp(src, 'ext-host-authentication', "  attributes:\n    owner: exthost\n", "  attributes:\n    owner: exthost\n  state:\n    schema:\n      type: object\n      properties:\n        providers:\n          type: object\n          description: _authenticationProviders, provider id -> registering extension\n    initial:\n      providers: {}\n")
    src = sub_in_iface(src, 'ext-host-authentication', 'get-session', "  response: ExthostApiResult\n", open(HERE + 'auth_get_session_new.yaml').read())
    src = sub_in_iface(src, 'ext-host-authentication', 'register-authentication-provider', "  response: ExthostApiResult\n", open(HERE + 'auth_register_new.yaml').read())
    src = sub_in_comp(src, 'ext-host-commands', "        setContext:\n", "        vscode.open:\n          internal_id: _workbench.open\n          args:\n          - uri-or-http\n          - optional\n          - optional-string\n        setContext:\n")
    src = sub_in_comp(src, "exthost-api-smoke-authentication", "  - steps.s0.result.ok && steps.s1.result.ok && steps.s2.result.ok\n", "  - '!steps.s0.result.ok && steps.s0.result.error.code == ''no-provider'' && steps.s1.result.ok && steps.s2.result.ok'\n")
    # ---------------- feature tags ----------------
    for fid, feat in [('exthost-start', 'extension-host-lifecycle'), ('exthost-activate-by-event', 'extension-host-lifecycle'),
                      ('exthost-crash', 'extension-host-lifecycle'), ('exthost-unresponsive', 'extension-host-lifecycle'),
                      ('exthost-api-call', 'extension-api')]:
        src = sub_in_comp(src, fid, "  tags:\n  - writes\n", "  tags:\n  - writes\n  - feature:%s\n" % feat)

    src = insert_before_section(src, 'flows', NEW_INTERFACES)
    src = src.rstrip('\n') + '\n' + NEW_SCENARIOS.strip('\n') + '\n'
    return src


NEW_COMPONENTS = r"""
- id: remote-extension-host
  name: RemoteExtensionHost
  kind: module
  layer: extensions
  parent: exthost-bridge
  summary: 'RemoteExtensionHost: the renderer side of the extension host running on the remote server (connects with an ExtensionHost connection).'
  sources:
  - src/vs/workbench/services/extensions/common/remoteExtensionHost.ts:48
  attributes:
    owner: exthost
  state:
    schema:
      type: object
      properties:
        started:
          type: boolean
        extensions:
          type: array
          items:
            type: string
    initial:
      started: false
      extensions: []
- id: ext-host-save-participant
  name: ExtHostSaveParticipant
  kind: service
  layer: extensions
  parent: exthost-bridge
  summary: 'The renderer''s text-file save participant for the extension host (added by the SaveParticipant customer): fires onWillSaveTextDocument in the host and gives up after 1750 ms.'
  sources:
  - src/vs/workbench/api/browser/mainThreadSaveParticipant.ts:17-49
  attributes:
    owner: exthost
- id: ext-host-document-save-participant
  name: ExtHostDocumentSaveParticipant
  kind: service
  layer: extensions
  parent: exthost-runtime
  summary: 'ExtHostDocumentSaveParticipant: delivers onWillSaveTextDocument to the extensions'' listeners within a 1500 ms budget and ignores listeners that failed more than 3 times.'
  sources:
  - src/vs/workbench/api/common/extHostDocumentSaveParticipant.ts:22-31
  attributes:
    owner: exthost
  state:
    schema:
      type: object
      properties:
        listeners:
          type: array
          items:
            type: string
          description: _callbacks, the extension ids that subscribed to workspace.onWillSaveTextDocument, in order
        bad_listeners:
          type: object
          description: _badListeners, listener -> error/timeout count
    initial:
      listeners: []
      bad_listeners: {}
"""

MT_REGISTER_COMMAND = r"""
- component: main-thread-commands
  name: register-command
  kind: rpc
  summary: '$registerCommand(id): register a CommandsRegistry handler that calls back $executeContributedCommand.'
  attributes:
    shape: MainThreadCommandsShape
  sources:
  - src/vs/workbench/api/common/extHost.protocol.ts:138
  - src/vs/workbench/api/browser/mainThreadCommands.ts:57-66
  request:
    type: object
    required:
    - command_id
    properties:
      command_id:
        type: string
        examples:
        - myext.sayHello
  behavior:
  - title: CommandsRegistry.registerCommand(id, (accessor, ...args) => this._proxy.$executeContributedCommand(id, ...args))
    source: src/vs/workbench/api/browser/mainThreadCommands.ts:58-63
    call: commands-registry.register-command
    input:
      command_id: = input.command_id
      handler: main-thread-commands.execute-contributed-command
  - set:
      state.registrations: '= input.command_id in state.registrations ? state.registrations : state.registrations + [input.command_id]'
"""

MT_COMMANDS_CREATE = r"""
- component: main-thread-commands
  name: create
  kind: function
  summary: 'new MainThreadCommands(extHostContext): instantiated for each extension host and registered on its RPC protocol; registers the _generateCommandsDocumentation command.'
  sources:
  - src/vs/workbench/api/browser/mainThreadCommands.ts:16
  - src/vs/workbench/api/browser/mainThreadCommands.ts:23-31
  behavior:
  - title: CommandsRegistry.registerCommand('_generateCommandsDocumentation', ...)
    source: src/vs/workbench/api/browser/mainThreadCommands.ts:30
    call: commands-registry.register-command
    input:
      command_id: _generateCommandsDocumentation
      handler: main-thread-commands.generate-commands-documentation
  - return:
      customer: MainThreadCommands
"""

MT_EDITOR_TABS_CREATE = r"""
- component: main-thread-editor-tabs
  name: create
  kind: function
  summary: 'new MainThreadEditorTabs(extHostContext): listens to editorService.onDidEditorsChange (patching the tab model) and to group add/remove (rebuilding it), then builds the initial model once the groups are ready.'
  sources:
  - src/vs/workbench/api/browser/mainThreadEditorTabs.ts:37
  - src/vs/workbench/api/browser/mainThreadEditorTabs.ts:59-79
  behavior:
  - title: Once everything is ready go ahead and initialize the model
    source: src/vs/workbench/api/browser/mainThreadEditorTabs.ts:78
    call: main-thread-editor-tabs.create-tabs-model
  - return:
      customer: MainThreadEditorTabs
"""

START_DA = r"""
- component: ext-host-debug-service
  name: start-da-session
  kind: rpc
  attributes:
    shape: ExtHostDebugServiceShape
  summary: '$startDASession(handle, session): resolve the debug adapter descriptor (the extension''s factory for the type, else the executable its debuggers contribution declares), create the adapter, keep it under the handle and start it.'
  sources:
  - src/vs/workbench/api/common/extHost.protocol.ts:3432
  - src/vs/workbench/api/common/extHostDebugService.ts:607-704
  request:
    type: object
    properties:
      handle:
        type: integer
        examples:
        - 1
      session_id:
        type: string
        examples:
        - session-1
      type:
        type: string
        examples:
        - node
  response:
    type: object
  errors:
  - code: no-debug-adapter-descriptor
    status: 0
    retryable: false
  behavior:
  - set:
      vars.type: '= has(input.type) ? input.type : '''''
  - if: vars.type == ''
    then:
    - title: Couldn't find a debug adapter descriptor for the debug type
      source: src/vs/workbench/api/common/extHostDebugService.ts:614-616
      fail:
        code: no-debug-adapter-descriptor
        message: = "Couldn't find a debug adapter descriptor for debug type '" + vars.type + "' (extension might have failed to activate)"
  - title: getAdapterDescriptor(getAdapterDescriptorFactoryByType(type), session)
    source: src/vs/workbench/api/common/extHostDebugService.ts:612
    set:
      vars.descriptor: '= vars.type in state.descriptor_factories ? ''factory:'' + state.descriptor_factories[vars.type] : ''executable'''
  - title: this._debugAdapters.set(debugAdapterHandle, debugAdapter)
    source: src/vs/workbench/api/common/extHostDebugService.ts:625
    set:
      state.adapters: '= merge(state.adapters, {string(input.handle): {''session_id'': has(input.session_id) ? input.session_id : '''', ''type'': vars.type, ''descriptor'': vars.descriptor}})'
  - title: debugAdapter.startSession() (its onMessage/onError/onExit relay to $acceptDAMessage/$acceptDAError/$acceptDAExit)
    source: src/vs/workbench/api/common/extHostDebugService.ts:689-702
    call: debug-adapter.start-session
  - return: {}
"""

STOP_DA = r"""
- component: ext-host-debug-service
  name: stop-da-session
  kind: rpc
  attributes:
    shape: ExtHostDebugServiceShape
  summary: '$stopDASession(handle): drop the tracker and the adapter for the handle and stop the adapter session (none: resolves).'
  sources:
  - src/vs/workbench/api/common/extHost.protocol.ts:3433
  - src/vs/workbench/api/common/extHostDebugService.ts:721-736
  request:
    type: object
    properties:
      handle:
        type: integer
        examples:
        - 1
  response:
    type: object
  behavior:
  - set:
      vars.known: = string(input.handle) in state.adapters
      state.adapters: = state.adapters.transformMap(k, v, k != string(input.handle), v)
  - if: vars.known
    then:
    - title: da.stopSession()
      source: src/vs/workbench/api/common/extHostDebugService.ts:731-733
      call: debug-adapter.stop-session
  - return: {}
"""

NEW_INTERFACES = open(HERE + 'new_interfaces.yaml').read() + open(HERE + 'auth_ifaces.yaml').read()
NEW_SCENARIOS = open(HERE + 'new_scenarios.yaml').read()

import re as _re, yaml as _yaml
FR = os.path.normpath(HERE + '../../../fragments') + '/'
def _load(area):
    return _yaml.safe_load(open(FR + area + '.yaml'))
_STUB_IFACES = [('terminal-debug-tasks', 'debug-adapter', 'start-session'), ('terminal-debug-tasks', 'debug-adapter', 'stop-session'),
    ('workbench-shell', 'workspace-trust-management-service', 'is-workspace-trusted'),
    ('platform-core', 'commands-registry', 'register-command'), ('platform-core', 'commands-registry', 'get-command'),
    ('workbench-shell', 'editor-groups', 'get-state'), ('editor', 'language-configuration-service', 'register'),
    ('platform-core', 'storage-service', 'store')]
_STUB_COMPS = [('workbench-shell', 'workspace-trust-management-service'), ('platform-core', 'commands-registry'),
    ('editor', 'language-configuration-service'), ('platform-core', 'storage-service'),
    ('remote-server', 'extensions-auto-profiler')]
def stubs():
    docs = {}
    comps, ifaces = [], []
    for area, cid in _STUB_COMPS:
        d = docs.setdefault(area, _load(area))
        c = [x for x in d['components'] if x['id'] == cid and not x.get('attributes', {}).get('boundary')][0]
        comps.append({'id': cid, 'kind': c['kind'], 'parent': c['parent'], 'name': c.get('name', cid),
                      'summary': 'Boundary stub; modeled by %s.' % area, 'attributes': {'boundary': True, 'owner': area}})
    for area, cid, name in _STUB_IFACES:
        d = docs.setdefault(area, _load(area))
        i = [x for x in d['interfaces'] if x['component'] == cid and x['name'] == name and not x.get('attributes', {}).get('boundary')][0]
        s = {'component': cid, 'name': name, 'kind': i.get('kind', 'function'), 'attributes': {'boundary': True, 'owner': area}}
        for k in ('request', 'response', 'errors'):
            if k in i: s[k] = i[k]
        s['summary'] = 'Boundary stub (contract copied from %s).' % area
        if cid == 'editor-groups':
            s['response']['properties']['groups']['items'] = {'type': 'object'}
        ifaces.append(s)
    dump = lambda l: _yaml.safe_dump(l, sort_keys=False, width=200, allow_unicode=True)
    return dump(comps), dump(ifaces)
