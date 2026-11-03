# transport: notes

Fragment: `examples/cassandra/fragments/transport.yaml`. Code: cassandra-5.0.9 (`b5f2a54210`).
All paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

## 1. Entry points

Inventory entries under the transport paths (`transport/**`, `service/NativeTransportService.java`,
`service/ClientState.java`, `service/QueryState.java`, `service/ClientWarn.java`): 10.

| Entry | Kind | Covered by |
|---|---|---|
| STARTUP `StartupMessage.java:72` | native-message | `transport.startup-message` -> `startup-message.execute`; flow `native-startup` (13 scenarios) |
| OPTIONS `OptionsMessage.java:62` | native-message | `transport.options-message` -> `options-message.execute` (post-STARTUP) or `initial-connection-handler.decode` (pre-STARTUP); flow `native-options` |
| AUTH_RESPONSE `AuthResponse.java:72` | native-message | `transport.auth-response-message` -> `auth-response.execute`; flow `native-auth-response` |
| REGISTER `RegisterMessage.java:66` | native-message | `transport.register-message` -> `register-message.execute`; flow `native-register` |
| QUERY `QueryMessage.java:102` | native-message | `transport.query-message` -> `query-message.execute`; flow `native-query` (22 scenarios) |
| PREPARE `PrepareMessage.java:122` | native-message | `transport.prepare-message` -> `prepare-message.execute`; flow `native-prepare` |
| EXECUTE `ExecuteMessage.java:131` | native-message | `transport.execute-message` -> `execute-message.execute`; flow `native-execute` |
| BATCH `BatchMessage.java:173` | native-message | `transport.batch-message` -> `batch-message.execute`; flow `native-batch` |

All 8 native-message entries show as covered (lines) in the `-v` coverage output.

### Skipped entry points

Machine-readable copy: `examples/cassandra/skips/transport.json` (2 entries).

- `java-main org.apache.cassandra.transport.Client` (`transport/Client.java:244`, `bin/debug-cql`): debug
  console client that speaks the native protocol to a server; it is a client tool, not server behavior.
- `scheduled-task SimpleClient.SimpleFlusher.schedule: maybeWrite` (`transport/SimpleClient.java:751`):
  the 10ms flush timer of `SimpleClient`, the in-tree test/tool client (used by `Client` and tests);
  not part of the server.

JMX entries that mention the native transport (`StorageServiceMBean.startNativeTransport`,
`stopNativeTransport`, `*NativeTransport*` getters/setters, `StorageProxyMBean.*NativeTransportMaxConcurrentConnections*`)
live in `service/*MBean.java` and belong to `ops` by the brief. Their behavior is here:
`native-transport-service.start` / `.stop` (enablebinary / disablebinary), and the setters change the
state values documented in section 4 (`client-resource-limits`, `connection-limit-handler`, `dispatcher`,
`protocol-version.allow_older_protocols` for enable/disableoldprotocolversions).

Other flows (not inventory entries): `client-connection-accept`, `native-transport-start`,
`native-transport-stop`, `endpoint-down-event`, `endpoint-up-event`, `endpoint-join-event`,
`endpoint-leave-event`, `endpoint-move-event`, `schema-change-event`, `client-permission-check`,
`client-use-keyspace`, `request-timestamp`.

## 2. Components

| Component | Code |
|---|---|
| `native-transport-service` | `service/NativeTransportService.java:48-205` |
| `pipeline-configurator` | `transport/PipelineConfigurator.java:62-402` |
| `connection-limit-handler` | `transport/ConnectionLimitHandler.java:46-149` |
| `server-connection-tracker` (Server.ConnectionTracker; also holds Server.isRunning) | `transport/Server.java:276-360`, `:84`, `:113` |
| `server-event-notifier` (Server.EventNotifier) | `transport/Server.java:396-609` |
| `initial-connection-handler` | `transport/InitialConnectionHandler.java:52-175` |
| `envelope-decoder` (Envelope.Decoder) | `transport/Envelope.java:195-497` |
| `protocol-version` | `transport/ProtocolVersion.java:38-176` |
| `cql-message-handler` | `transport/CQLMessageHandler.java:78-862` |
| `pre-v5-handlers-legacy-dispatch-handler` | `transport/PreV5Handlers.java:56-270` |
| `client-resource-limits` | `transport/ClientResourceLimits.java:38-297` (+ `QueueBackpressure` via dispatcher) |
| `dispatcher` | `transport/Dispatcher.java:53-518`, `transport/QueueBackpressure.java` |
| `server-connection` | `transport/ServerConnection.java:34-146`, `transport/Connection.java` |
| `client-state` | `service/ClientState.java:68-651` |
| `query-state` | `service/QueryState.java:30-117` |
| `client-warn` | `service/ClientWarn.java:26-90` |
| `message-request` (Message.Request) | `transport/Message.java:198-285` |
| `error-message` | `transport/messages/ErrorMessage.java:44-506` |
| `startup-message`, `options-message`, `auth-response`, `register-message`, `query-message`, `prepare-message`, `execute-message`, `batch-message` | `transport/messages/*.java` |

Interfaces on skeleton components I own: `transport.<opcode>-message` (8 entries), `transport.route-request`,
`transport.start`, `transport.stop` (Server.java), `cql-client.event-message` (EVENT pushed to clients).

Request path modeled (v5 default): `transport.<op>-message` -> `transport.route-request` ->
`cql-message-handler.process-one-contained-message` (header checks, bytes in flight, rate limit, queue age)
-> `cql-message-handler.process-request` (body decode) -> `dispatcher.dispatch` (shutting down?, executor)
-> `dispatcher.process-request` (queue timeout, ClientWarn, stage gate, execute, stage transition, warnings)
-> `message-request.execute` (tracing) -> `<op>-message.execute` -> cql stubs. Errors from execute go
through `error-message.from-exception` (version downgrade). Pre-v5 goes through
`pre-v5-handlers-legacy-dispatch-handler`; pre-STARTUP through `initial-connection-handler.decode`.

## 3. Boundary stubs

Reconciled with the owners' fragments (RECONCILE.md decisions 1, 3, 6). Request, response, kind and errors
(with `retryable`) are copied from the owner. Schemas are inlined (YAML anchors in my fragment), because only
the owner defines the named ones (`CqlParseRequest`, `CqlRequest`, `CqlStatement`, ...).

| Stub | Owner | Contract copied |
|---|---|---|
| `query-processor.parse`, `.prepare`, `.parse-and-prepare` | cql | `CqlParseRequest` `{query, statement, options, client_state}` -> `CqlStatement` / `CqlResultMessage` / `CqlPrepared`. The model's parser takes the statement structure alongside the string, so QUERY, PREPARE and BATCH entries carry a `statement` field. |
| `query-processor.process`, `.process-prepared`, `.process-batch` | cql | `CqlRequest` `{statement, options, client_state}` -> `CqlResultMessage`; cql's exec errors. Calls use `fill: true` so missing statement fields are filled from the owner's schema. |
| `query-processor.get-prepared` + `query-processor-prepared-statements.get-if-present` | cql | Hit returns `CqlPrepared` (statement nested), miss `{found: false}`. The stub has a pass-through copy of the owner's behavior so standalone scenarios seed the same cache rows (`query-processor-prepared-statements.entries`). |
| `password-authenticator.new-sasl-negotiator`, `password-authenticator-plain-text-sasl-authenticator.evaluate-response` / `.get-authenticated-user` | schema-auth | Inner-class names. Credentials are passed already split (`username`, `password`), as schema-auth's negotiator takes them; the AUTH_RESPONSE entry carries them instead of the raw token. |
| `authenticated-user.can-login`, `.is-super`, `.get-permissions` | schema-auth | `can-login` -> `{can_login}`; `is-super` -> `{is_super}`; `get-permissions` one resource at a time. |
| `auth-config.get-backends` | schema-auth | The installed authenticator/authorizer. Pass-through copy that defaults to AllowAll when `auth-config` state is unset, so both runs read the same seed (`state: {auth-config: {authenticator: PasswordAuthenticator}}`). |
| `schema.get-keyspace-metadata` | schema-auth | kind function, `{exists, name}`; standalone uses a store on table `keyspaces`. |
| `tracing.new-session`, `.begin`, `.stop-session` | ops | |
| `storage-service.get-nativeaddress`, `.is-rpc-ready` | membership | |

Defined for other areas (decision 6): `client-state.ensure-not-anonymous` (`ClientState.java:582-587`),
with flow `client-not-anonymous-check`. Also new: `client-state.get-user` (`:641-644`, `:602-605`) and
`query-state.get-client-state` (`QueryState.java:108-111`), which build the `client_state` cql expects.

Contract fixes on my side found during reconciliation: ClientState has no superuser shortcut in
`ensurePermission` (superusers get all permissions from the authorizer), so `ensure-permission` now walks the
resource chain (table, keyspace, `data`) calling `authenticated-user.get-permissions`. `isSuper()` is
true whenever the authenticator doesn't require authentication (so under AllowAllAuthenticator the anonymous
user is a superuser for CQL purposes).

The result metadata id (a digest of the result columns, `ResultSet.ResultMetadata`) isn't in cql's result
shape. Transport models it as `'meta:<keyspace>.<table>'` of the prepared statement.

Interfaces other areas are expected to call on me: `client-state.ensure-table-permission`,
`client-state.ensure-permission`, `client-state.validate-login`, `client-state.set-keyspace` (USE),
`client-state.get-timestamp`, `query-state.get-timestamp`, `client-warn.warn`; and, from membership and
schema-auth, `server-event-notifier.on-up/on-down/on-join-cluster/on-leave-cluster/on-move` and
`on-create-keyspace/on-create-table/on-alter-keyspace/on-alter-table/on-drop-keyspace/on-drop-table`.

## 4. Deployed config

Since the migration round these are `config` entities in the fragment (21, ids `native-transport-*`,
`client-encryption-policy`, `consecutive-message-errors-threshold`), each with its deployed `value`, code
`default` and both sources. Behaviors read `config[...]`, and scenarios override with `config:`. The table
below is the human-readable copy.

`cassandra.yaml` sets: `authenticator: AllowAllAuthenticator` (`conf/cassandra.yaml:198`),
`authorizer: AllowAllAuthorizer` (`:217`), `role_manager: CassandraRoleManager` (`:232`),
`start_native_transport: true` (`:1020`), `native_transport_port: 9042` (`:1023`),
`native_transport_allow_older_protocols: true` (`:1056`). Everything else below is commented out or absent,
so `Config.java` defaults apply:

| Setting | Effective | Source |
|---|---|---|
| native_transport_port_ssl | null -> same as port, one server | Config.java:282, DatabaseDescriptor.java:3116-3119 |
| native_transport_max_threads | 128 | Config.java:283 (yaml :1035 commented) |
| native_transport_max_auth_threads | 4 | Config.java:287 (yaml :1038 commented) |
| native_transport_max_frame_size | 16MiB | Config.java:285 (yaml :1044 commented) |
| native_transport_max_concurrent_connections(_per_ip) | -1 (handler not installed) | Config.java:289-290 (yaml :1048, :1052 commented) |
| native_transport_idle_timeout | 0ms (no idle handler) | Config.java:139 (yaml :1067 commented, 60000ms) |
| native_transport_rate_limiting_enabled / max_requests_per_second | false / 1000000 | Config.java:299-300 (yaml :1076-1077 commented) |
| native_transport_max_request_data_in_flight(_per_ip) | null -> heap/10 and heap/40 | Config.java:295-298, DatabaseDescriptor.java:649-656 |
| native_transport_max_message_size | null -> min(max_mutation_size, both in-flight limits) | Config.java:288, DatabaseDescriptor.java:903-918, 3237-3244 |
| native_transport_receive_queue_capacity | 1MiB | Config.java:302 |
| native_transport_throw_on_overload | false | Config.java:1393 |
| native_transport_queue_max_item_age_threshold | Double.MAX_VALUE (queue-age check never trips) | Config.java:1394 |
| native_transport_min/max_backoff_on_queue_overload | 10ms / 200ms | Config.java:1395-1396 |
| native_transport_timeout | 12s | Config.java:1399 |
| cql_start_time | REQUEST | Config.java:1391 |
| enforce_native_deadline_for_hints | false | Config.java:1400 |
| consecutive_message_errors_threshold | 1 | Config.java:855 |
| native_transport_flush_in_batches_legacy | false | Config.java:291 (yaml :1940 commented) |
| authenticator when unset | AllowAllAuthenticator | AuthConfig.java:54 (yaml sets the same) |

yaml vs Config.java differences: none in value for the settings I read. Only differences in what's
documented: the yaml's commented example for `native_transport_idle_timeout` is 60000ms, while the
effective default is 0 (disabled). The yaml comment says the same ("disabled by default").

Heap-derived values: I assumed a 4GiB heap, so the global in-flight limit is 429496729 bytes, per-IP
107374182 bytes. `native_transport_max_message_size` is then min(max_mutation_size, ...); I used 16MiB
as a round example (`cql-message-handler.native_transport_max_message_size_bytes`), which is an assumption.

## 5. What the code didn't settle, and my assumptions

- Scenarios use the shared fixtures: `three-node-rf3` (with `auth-users` for logins and permissions) for
  anything that reaches the CQL layer, the cluster or the event notifier; `base-schema` for USE; none for
  transport-only flows. With a topology the transport components live on `n1` (the coordinator), so
  expectations read `state['<component>@n1']`.
- One connection per run. `server-connection`, `client-state`, `client-warn` and `query-state` hold the
  state of that one connection or request. `server-connection.stage` starts READY so post-negotiation
  flows work by default. The STARTUP flow models a fresh channel (`negotiated: false`), which resets it to
  ESTABLISHED.
- Wire input is modeled at the decoded level: the entry request carries `header` (version, stream id,
  body size, TRACING and USE_BETA flags), `connection_version` (the version fixed at STARTUP),
  `negotiated` (whether STARTUP has already reconfigured the pipeline) and `queue_time_ms` (time spent in
  the Native-Transport-Requests queue). Empty strings stand for absent STARTUP options and a null keyspace.
- Auth config is read from schema-auth's `auth-config.get-backends` (one place). Scenarios set
  `auth-config: {authenticator: ..., authorizer: ...}`.
- Snappy is assumed loadable (`startup-message.snappy_available: true`).
- `acquireCapacityAndQueueOnFailure` (v5, no throw) is modeled as "allocate anyway, then backpressure".
  The real AbstractMessageHandler wait-queue semantics are owned by `net/` (membership).
- Bytes in flight are never released in the model after a successful request (the release happens in the
  flusher after the response is written). A single run doesn't need it.
- CQL version parsing: modeled as `major.minor.patch` numerics. CassandraVersion accepts more forms.
- `client-state.ensure-table-permission` models the local system keyspace rule (system, system_schema)
  only. The replicated system keyspace rule (system_auth, system_distributed, system_traces: only keyspace-level
  ALTER allowed), READABLE_SYSTEM_RESOURCES and PROTECTED_AUTH_RESOURCES are described but not branched.
  Role inheritance and `auth_from_root` ordering are inside `authenticated-user.get-permissions`.
- AuthEvents, QueryEvents (audit / FQL listeners), ClientMetrics and NoSpamLogger calls are left out.
- The AUTH_RESPONSE flow always uses the PasswordAuthenticator negotiator stubs. With the deployed
  AllowAllAuthenticator a connection never reaches AUTHENTICATING. AUTH_RESPONSE on a READY connection
  passes `validateNewMessage` (READY only refuses STARTUP) and would use AllowAllAuthenticator's own
  negotiator. That case isn't modeled.

## 6. Code vs common knowledge / docs

- **STARTUP never sees the request executor.** The first STARTUP is executed on the netty event loop
  through `Dispatcher.processRequest` directly (`InitialConnectionHandler.java:152`). So the
  "server is shutting down" check (`Dispatcher.java:105`), the queue timeout and executor selection
  don't apply to it. Scenario `startup-ready-allow-all` asserts `dispatcher.dispatch == 0`.
- **A failed v5 STARTUP still switches the pipeline to v5 framing.** The listener configures the modern
  pipeline on any successful write, including an ERROR response (`InitialConnectionHandler.java:120-126`).
  Scenario `startup-missing-cql-version`.
- **OPTIONS before STARTUP is answered by the InitialConnectionHandler**, not `OptionsMessage.execute`.
  The same SUPPORTED content is built twice in the code.
- **THROW_ON_OVERLOAD defaults differ by protocol version.** On v5 an absent option falls back to
  `native_transport_throw_on_overload` (`PipelineConfigurator.java:309-314`). Pre-v5 uses
  `Connection.throwOnOverload`, set only from the option (`StartupMessage.java:111`), so the yaml flag
  has no effect on V3/V4 connections.
- **Overload under the deployed config (judge T3).** Rate limiting is off and the queue-age threshold is
  Double.MAX_VALUE, and THROW_ON_OVERLOAD is unset. So a bytes-in-flight breach is backpressure (processed,
  paused, warned), not OVERLOADED. OVERLOADED comes only from THROW_ON_OVERLOAD with a byte breach, a queue
  wait past `native_transport_timeout`, or shutdown. Scenarios: `query-backpressure-bytes-in-flight`,
  `query-throw-on-overload-bytes-in-flight`, `query-rate-limiter-ignored-when-disabled`,
  `query-timed-out-in-queue`, `auth-storm-times-out-in-queue`, `stop-then-query-refused`.
- **Server shutdown is reported as OVERLOADED**, deliberately, so drivers don't defunct the connection.
- **Request timeout before processing.** A request that waited in the queue longer than
  `native_transport_timeout` (12s, not the read/write timeouts) is answered OVERLOADED "Query timed out
  before it could start". This applies to every message type.
- **Error code downgrades.** CAS_WRITE_UNKNOWN becomes WRITE_TIMEOUT (write type CAS) for V3/V4 clients.
  READ_FAILURE and WRITE_FAILURE become timeouts, and FUNCTION_FAILURE and CDC_WRITE_FAILURE become INVALID,
  for clients older than V4 (V3 is the only one still supported) (`ErrorMessage.java:350-386`).
- **EXECUTE order:** the UNPREPARED check comes before the page-size check. EXECUTE with page size 0 and an
  unknown id answers UNPREPARED (`execute-unprepared-before-page-size`).
- **BATCH checks statement kinds only after preparing and bind-checking every statement**, so an UNPREPARED
  or bind-count error wins over "only UPDATE, INSERT and DELETE".
- **LWT EXECUTE never sets METADATA_CHANGED** on v5 (CASSANDRA-13992).
- **Event dedup quirk:** `LatestEvent.forStatusChange(status, null)` forgets the last topology change
  (`Server.java:507`). After NEW_NODE followed by UP, a second NEW_NODE for the same endpoint is sent again.
  Scenario `up-after-deferred-join` asserts the topology is cleared.
- **NEW_NODE is deferred** until the joined node gossips RPC_READY, then sent from `onUp` before the UP event.
- Protocol versions: V1 and V2 are refused with a forced-version error (so the driver can downgrade). DSE
  versions 65/66 are refused silently. V6 is beta and needs the USE_BETA flag. Older protocols (V3/V4) are
  allowed on the deployed node (`native_transport_allow_older_protocols: true`).
- `CassandraDaemon.startNativeTransport` sets RPC ready in gossip only if no server was running before
  (`CassandraDaemon.java:817-825`). That part is ops/membership, so I didn't model it.

## 7. Simulator gaps

Resolved in the migration round:

- **Executor queueing** is now `capacity`. `dispatcher.dispatch` submits to `dispatcher-request-executor.run`
  (Native-Transport-Requests, concurrency 128) or `dispatcher-auth-executor.run` (Native-Transport-Auth-Requests,
  concurrency 4). The wait for a worker adds to the request's queue time, which `process-request` compares with
  `native-transport-timeout-ms`. Example: `auth-storm-times-out-in-queue` has 5 AUTH_RESPONSEs with 12.5s
  password checks. The fifth waits for a worker past 12s and is answered OVERLOADED "Query timed out before
  it could start" (`Dispatcher.java:364-367`). The `queue_time_ms` input remains for earlier backlog.
- **Client sessions** are multi-step scenarios: STARTUP then QUERY, STARTUP then AUTH_RESPONSE then QUERY,
  a wrong password then a retry, PREPARE then EXECUTE, UNPREPARED then re-PREPARE then EXECUTE, REGISTER
  then a node DOWN event, USE then an unqualified QUERY, stop then QUERY, stop, start then QUERY, BATCH then
  SELECT.
- **Config** is shared. 21 `config` entities hold the native transport settings, and auth config comes from
  schema-auth's `auth-config`.
- **Instances.** Event endpoints are instance names (`n2`). The notifier compares against `self`'s native
  address.

Still open:

- **`capacity.concurrency` and `entry.deadline_ms` take literals**, so a config override of
  `native-transport-max-threads`/`-max-auth-threads`/`-timeout-ms` doesn't resize the pools or the
  entry deadline (12000). Example: `config: {native-transport-max-auth-threads: 1}` changes the executor
  choice but not the auth pool's 4 workers.
- **Config integers aren't plain CEL ints**: `double(config['x'])` and `string(config['x'])` fail with "no
  such overload". The fragment wraps them in `int(...)`. coordination's
  `dynamic-endpoint-snitch.sorted-by-proximity` hits this (`double(config['dynamic-snitch-badness-threshold'])`,
  whose YAML value `1.0` decodes as an int).
- **Many connections, frames and messages.** A v5 frame carries several envelopes, and
  `consecutive_message_errors_threshold` turns the second error in one frame fatal. A run models one connection
  (parallel branches share it), so the fatal path can't be reached.
- **Backpressure is a pause of the socket, not an error.** The model records `ctx.connection_paused` and the
  wakeup delay. It can't show later messages being held back.
- **Rate limiter and QueueBackpressure incidents** are time-based. They are modeled as state flags
  (`permit_available`, `permit_delay_ms`, `queue_backpressure_severity`), and `oldest_task_queue_ms` is set
  by scenarios. It isn't derived from the executor's real queue.
- **Client events stay a loop** over the channel group's registrations (`server-connection-tracker.send`).
  The code iterates a netty `ChannelGroup`, not a listener list. The notifier's handlers now `subscribe` to
  `endpoint-lifecycle.on-*` and `schema-change.on-*` topics, which membership and schema-auth can `publish`.
  Until they do, they call the handlers directly.
- **Response stream routing, compression, flushing** and **large (multi-frame) messages**: as before, a
  narrative step and a size check.

## 8. Known gaps

- Schema change events for types, functions and aggregates (`Server.java:525-609`) aren't separate interfaces.
  They behave like the keyspace and table ones.
- `ExceptionHandlers` (channel-level exception to ERROR frame, fatal close when no stream id),
  `Envelope.Decompressor/Compressor`, `Compressor`, `CBUtil`, `DataType` and `ProtocolVersionTracker`
  aren't modeled. The `connected clients` views (`ConnectedClient`, `ClientStat`) are left to `ops`
  virtual tables.
- `transport.route-request` is a modeling helper. The routing really is the pipeline state set by
  PipelineConfigurator, which it cites.
- The deferred-join branch of `on-join-cluster` (node not RPC ready) has no scenario. The
  `storage-service.is-rpc-ready` stub returns `ready: true`, and only membership can make it false. The
  other half (UP releases the pending NEW_NODE) is covered by `up-after-deferred-join`.
- Probabilistic tracing (`StorageService.shouldTraceProbablistically`) isn't modeled.
- `cassandra.custom_query_handler_class` (alternative QueryHandler) is cited but not branched.
