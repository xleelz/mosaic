# schema-auth notes

Fragment: `examples/cassandra/fragments/schema-auth.yaml`. Code: cassandra-5.0.9 (`b5f2a54210`).
All paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

After the migration round (§10): standalone, with the shared fixtures filtered to known components,
0 errors and 277/277 scenarios pass; 704 citations ok; behavior coverage 92.0%; hollow lint 0 failing.
Machine-readable skips: `examples/cassandra/skips/schema-auth.json` (10 entries).

## 1. Entry points

Ownership note: the cql fragment models `AuthenticationStatement`, `AddIdentityStatement` and
`DropIdentityStatement` (they fall outside the `*Role*`/`Grant*`/`Revoke*`/`List*` patterns), so they
are not counted here. I stub `authentication-statement.check-permission` from cql's definition.
`AuthorizationStatement` is also outside the patterns, but cql does not model it, so I cover it
(`authorization-statement.maybe-correct-resource`); reconciliation may move it.

| Kind | Entry | Where | Covered by / skip reason |
|---|---|---|---|
| cql-statement | `AlterRoleStatement` | `cql3/statements/AlterRoleStatement.java:34` | alter-role-statement.{authorize,validate,execute} (flows alter-role, alter-role-validate, alter-role-authorize) |
| cql-statement | `AuthorizationStatement` | `cql3/statements/AuthorizationStatement.java:34` | authorization-statement.maybe-correct-resource (flow grant-permissions-validate) |
| cql-statement | `CreateRoleStatement` | `cql3/statements/CreateRoleStatement.java:32` | create-role-statement.{authorize,validate,execute} (flows create-role, create-role-validate, create-role-authorize) |
| cql-statement | `DropRoleStatement` | `cql3/statements/DropRoleStatement.java:31` | drop-role-statement.{authorize,validate,execute} (flows drop-role, drop-role-validate, drop-role-authorize) |
| cql-statement | `GrantPermissionsStatement` | `cql3/statements/GrantPermissionsStatement.java:40` | grant-permissions-statement.{validate,execute} (flows grant-permissions, grant-permissions-validate) |
| cql-statement | `GrantRoleStatement` | `cql3/statements/GrantRoleStatement.java:31` | grant-role-statement.execute (flow grant-role) |
| cql-statement | `ListPermissionsStatement` | `cql3/statements/ListPermissionsStatement.java:37` | list-permissions-statement.{validate,execute} (flows list-permissions, list-permissions-validate) |
| cql-statement | `ListRolesStatement` | `cql3/statements/ListRolesStatement.java:42` | list-roles-statement.{validate,execute,format-results} (flows list-roles, list-roles-validate) |
| cql-statement | `ListUsersStatement` | `cql3/statements/ListUsersStatement.java:36` | list-users-statement.format-results (flow list-roles, scenario list-users) |
| cql-statement | `RevokePermissionsStatement` | `cql3/statements/RevokePermissionsStatement.java:38` | revoke-permissions-statement.execute (flow revoke-permissions) |
| cql-statement | `RevokeRoleStatement` | `cql3/statements/RevokeRoleStatement.java:31` | revoke-role-statement.execute (flow revoke-role) |
| cql-statement | `AlterKeyspaceStatement` | `cql3/statements/schema/AlterKeyspaceStatement.java:53` | alter-keyspace-statement.apply (flow alter-keyspace) |
| cql-statement | `AlterSchemaStatement` | `cql3/statements/schema/AlterSchemaStatement.java:43` | alter-schema-statement.execute (every DDL flow) |
| cql-statement | `AlterTableStatement.AlterColumn` | `cql3/statements/schema/AlterTableStatement.java:153` | alter-table-statement-alter-column.apply (flow alter-table) |
| cql-statement | `AlterTableStatement.MaskColumn` | `cql3/statements/schema/AlterTableStatement.java:169` | alter-table-statement-mask-column.apply (flow alter-table) |
| cql-statement | `AlterTableStatement.AddColumns` | `cql3/statements/schema/AlterTableStatement.java:242` | alter-table-statement-add-columns.apply (flow alter-table) |
| cql-statement | `AlterTableStatement.DropColumns` | `cql3/statements/schema/AlterTableStatement.java:380` | alter-table-statement-drop-columns.apply (flow alter-table) |
| cql-statement | `AlterTableStatement.RenameColumns` | `cql3/statements/schema/AlterTableStatement.java:450` | alter-table-statement-rename-columns.apply (flow alter-table) |
| cql-statement | `AlterTableStatement.AlterOptions` | `cql3/statements/schema/AlterTableStatement.java:524` | alter-table-statement-alter-options.apply (flow alter-table) |
| cql-statement | `AlterTableStatement.DropCompactStorage` | `cql3/statements/schema/AlterTableStatement.java:579` | alter-table-statement-drop-compact-storage.apply (flow alter-table) |
| cql-statement | `AlterTypeStatement.AddField` | `cql3/statements/schema/AlterTypeStatement.java:103` | alter-type-statement-add-field.apply (flow type-ddl) |
| cql-statement | `AlterTypeStatement.RenameFields` | `cql3/statements/schema/AlterTypeStatement.java:174` | alter-type-statement-rename-fields.apply (flow type-ddl) |
| cql-statement | `AlterTypeStatement.AlterField` | `cql3/statements/schema/AlterTypeStatement.java:226` | alter-type-statement-alter-field.apply (flow type-ddl) |
| cql-statement | `AlterViewStatement` | `cql3/statements/schema/AlterViewStatement.java:33` | alter-view-statement.apply (flow other-ddl) |
| cql-statement | `CreateAggregateStatement` | `cql3/statements/schema/CreateAggregateStatement.java:60` | create-aggregate-statement.apply (flow other-ddl) |
| cql-statement | `CreateFunctionStatement` | `cql3/statements/schema/CreateFunctionStatement.java:49` | create-function-statement.apply (flow other-ddl) |
| cql-statement | `CreateIndexStatement` | `cql3/statements/schema/CreateIndexStatement.java:51` | create-index-statement.apply (flow other-ddl) |
| cql-statement | `CreateKeyspaceStatement` | `cql3/statements/schema/CreateKeyspaceStatement.java:48` | create-keyspace-statement.apply (flow create-keyspace) |
| cql-statement | `CreateTableStatement` | `cql3/statements/schema/CreateTableStatement.java:55` | create-table-statement.apply (flow create-table) |
| cql-statement | `CreateTriggerStatement` | `cql3/statements/schema/CreateTriggerStatement.java:32` | create-trigger-statement.apply (flow other-ddl) |
| cql-statement | `CreateTypeStatement` | `cql3/statements/schema/CreateTypeStatement.java:45` | create-type-statement.apply (flow type-ddl) |
| cql-statement | `CreateViewStatement` | `cql3/statements/schema/CreateViewStatement.java:55` | create-view-statement.apply (flow other-ddl) |
| cql-statement | `DropAggregateStatement` | `cql3/statements/schema/DropAggregateStatement.java:47` | drop-aggregate-statement.apply (flow other-ddl) |
| cql-statement | `DropFunctionStatement` | `cql3/statements/schema/DropFunctionStatement.java:48` | drop-function-statement.apply (flow other-ddl) |
| cql-statement | `DropIndexStatement` | `cql3/statements/schema/DropIndexStatement.java:33` | drop-index-statement.apply (flow other-ddl) |
| cql-statement | `DropKeyspaceStatement` | `cql3/statements/schema/DropKeyspaceStatement.java:31` | drop-keyspace-statement.apply (flow drop-keyspace) |
| cql-statement | `DropTableStatement` | `cql3/statements/schema/DropTableStatement.java:38` | drop-table-statement.apply (flow drop-table) |
| cql-statement | `DropTriggerStatement` | `cql3/statements/schema/DropTriggerStatement.java:31` | drop-trigger-statement.apply (flow other-ddl) |
| cql-statement | `DropTypeStatement` | `cql3/statements/schema/DropTypeStatement.java:45` | drop-type-statement.apply (flow type-ddl) |
| cql-statement | `DropViewStatement` | `cql3/statements/schema/DropViewStatement.java:32` | drop-view-statement.apply (flow other-ddl) |
| jmx-operation | `AuthCacheMBean.invalidate` | `auth/AuthCacheMBean.java:23` | auth-cache.invalidate (flow jmx-auth-cache-invalidate) |
| jmx-operation | `AuthCacheMBean.setValidity` | `auth/AuthCacheMBean.java:25` | auth-cache.set-validity (flow jmx-auth-cache-set-validity) |
| jmx-operation | `AuthCacheMBean.getValidity` | `auth/AuthCacheMBean.java:27` | skip (group): the five AuthCacheMBean getters (getValidity, getUpdateInterval, getMaxEntries, getActiveUpdate, getEstimatedSize) are reads of cache config or size, no behavior |
| jmx-operation | `AuthCacheMBean.setUpdateInterval` | `auth/AuthCacheMBean.java:29` | auth-cache.set-update-interval (flow jmx-auth-cache-set-update-interval) |
| jmx-operation | `AuthCacheMBean.getUpdateInterval` | `auth/AuthCacheMBean.java:31` | skip (group): the five AuthCacheMBean getters (getValidity, getUpdateInterval, getMaxEntries, getActiveUpdate, getEstimatedSize) are reads of cache config or size, no behavior |
| jmx-operation | `AuthCacheMBean.setMaxEntries` | `auth/AuthCacheMBean.java:33` | auth-cache.set-max-entries (flow jmx-auth-cache-set-max-entries) |
| jmx-operation | `AuthCacheMBean.getMaxEntries` | `auth/AuthCacheMBean.java:35` | skip (group): the five AuthCacheMBean getters (getValidity, getUpdateInterval, getMaxEntries, getActiveUpdate, getEstimatedSize) are reads of cache config or size, no behavior |
| jmx-operation | `AuthCacheMBean.getActiveUpdate` | `auth/AuthCacheMBean.java:37` | skip (group): the five AuthCacheMBean getters (getValidity, getUpdateInterval, getMaxEntries, getActiveUpdate, getEstimatedSize) are reads of cache config or size, no behavior |
| jmx-operation | `AuthCacheMBean.setActiveUpdate` | `auth/AuthCacheMBean.java:39` | auth-cache.set-active-update (flow jmx-auth-cache-set-active-update) |
| jmx-operation | `AuthCacheMBean.getEstimatedSize` | `auth/AuthCacheMBean.java:41` | skip (group): the five AuthCacheMBean getters (getValidity, getUpdateInterval, getMaxEntries, getActiveUpdate, getEstimatedSize) are reads of cache config or size, no behavior |
| jmx-operation | `AuthPropertiesMXBean.setReadConsistencyLevel` | `auth/AuthPropertiesMXBean.java:25` | auth-properties.set-read-consistency-level (flow jmx-auth-read-consistency) |
| jmx-operation | `AuthPropertiesMXBean.getReadConsistencyLevel` | `auth/AuthPropertiesMXBean.java:26` | auth-properties.get-read-consistency-level (every system_auth read) |
| jmx-operation | `AuthPropertiesMXBean.setWriteConsistencyLevel` | `auth/AuthPropertiesMXBean.java:27` | auth-properties.set-write-consistency-level (flow jmx-auth-write-consistency) |
| jmx-operation | `AuthPropertiesMXBean.getWriteConsistencyLevel` | `auth/AuthPropertiesMXBean.java:28` | auth-properties.get-write-consistency-level (every system_auth write) |
| jmx-operation | `CIDRGroupsMappingManagerMBean.getAvailableCidrGroups` | `auth/CIDRGroupsMappingManagerMBean.java:36` | skip (group): CIDR authorization is disabled in the deployed config (cidr_authorizer: AllowAllCIDRAuthorizer, cassandra.yaml:261-262), so the CIDR groups manager, its cache reload task and the CIDR permissions cache are not modeled |
| jmx-operation | `CIDRGroupsMappingManagerMBean.getCidrsOfCidrGroupAsStrings` | `auth/CIDRGroupsMappingManagerMBean.java:44` | cidr-groups-mapping-manager.get-cidrs-of-cidr-group-as-strings (flow jmx-cidr-get-group) |
| jmx-operation | `CIDRGroupsMappingManagerMBean.updateCidrGroup` | `auth/CIDRGroupsMappingManagerMBean.java:51` | cidr-groups-mapping-manager.update-cidr-group (flow jmx-cidr-update-group) |
| jmx-operation | `CIDRGroupsMappingManagerMBean.dropCidrGroup` | `auth/CIDRGroupsMappingManagerMBean.java:58` | cidr-groups-mapping-manager.drop-cidr-group (flow jmx-cidr-drop-group) |
| jmx-operation | `CIDRGroupsMappingManagerMBean.recreateCidrGroupsMapping` | `auth/CIDRGroupsMappingManagerMBean.java:65` | skip (group): CIDR authorization is disabled in the deployed config (cidr_authorizer: AllowAllCIDRAuthorizer, cassandra.yaml:261-262), so the CIDR groups manager, its cache reload task and the CIDR permissions cache are not modeled |
| jmx-operation | `CIDRGroupsMappingManagerMBean.getCidrGroupsOfIP` | `auth/CIDRGroupsMappingManagerMBean.java:73` | skip (group): CIDR authorization is disabled in the deployed config (cidr_authorizer: AllowAllCIDRAuthorizer, cassandra.yaml:261-262), so the CIDR groups manager, its cache reload task and the CIDR permissions cache are not modeled |
| jmx-operation | `CIDRGroupsMappingManagerMBean.loadCidrGroupsCache` | `auth/CIDRGroupsMappingManagerMBean.java:78` | cidr-groups-mapping-manager.load-cidr-groups-cache (flow jmx-cidr-load-cache) |
| jmx-operation | `CIDRPermissionsManagerMBean.invalidateCidrPermissionsCache` | `auth/CIDRPermissionsManagerMBean.java:31` | cidr-permissions-manager.invalidate-cidr-permissions-cache (flow jmx-cidr-invalidate-permissions) |
| jmx-operation | `NetworkPermissionsCacheMBean.invalidateNetworkPermissions` | `auth/NetworkPermissionsCacheMBean.java:28` | network-permissions-cache.invalidate-network-permissions (flow jmx-invalidate-network-permissions) |
| jmx-operation | `PasswordAuthenticator.CredentialsCacheMBean.invalidateCredentials` | `auth/PasswordAuthenticator.java:345` | password-authenticator-credentials-cache.invalidate-credentials (flow jmx-invalidate-credentials) |
| jmx-operation | `PermissionsCacheMBean.invalidatePermissions` | `auth/PermissionsCacheMBean.java:25` | permissions-cache.invalidate-permissions (flow jmx-invalidate-permissions) |
| jmx-operation | `RolesCacheMBean.invalidateRoles` | `auth/RolesCacheMBean.java:25` | roles-cache.invalidate-roles (flow jmx-invalidate-roles) |
| jmx-operation | `AuthorizationProxy.JmxPermissionsCacheMBean.invalidatePermissions` | `auth/jmx/AuthorizationProxy.java:592` | authorization-proxy-jmx-permissions-cache.invalidate-permissions (flow jmx-invalidate-jmx-permissions) |
| messaging-verb | `SCHEMA_PUSH_RSP` | `net/Verb.java:155` | skip: not an entry point - the response verb is declared, but SchemaPushVerbHandler never replies and MigrationCoordinator.pushSchemaMutations sends SCHEMA_PUSH_REQ without a callback (MigrationCoordinator.java:752-758) |
| messaging-verb | `SCHEMA_PUSH_REQ` | `net/Verb.java:156` | schema-push-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| messaging-verb | `SCHEMA_PULL_RSP` | `net/Verb.java:157` | schema-pull-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| messaging-verb | `SCHEMA_PULL_REQ` | `net/Verb.java:158` | schema-pull-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| messaging-verb | `SCHEMA_VERSION_RSP` | `net/Verb.java:159` | schema-version-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| messaging-verb | `SCHEMA_VERSION_REQ` | `net/Verb.java:160` | schema-version-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| scheduled-task | `AuthCache.initCache: CacheRefresher.create` | `auth/AuthCache.java:368` | auth-cache.init-cache emits cache-refresher.run (flows jmx-auth-cache-set-active-update, auth-cache-refresh) |
| scheduled-task | `CIDRGroupsMappingCache.CIDRGroupsMappingCache: reloadCidrGroupsCache` | `auth/CIDRGroupsMappingCache.java:67` | skip (group): CIDR authorization is disabled in the deployed config (cidr_authorizer: AllowAllCIDRAuthorizer, cassandra.yaml:261-262), so the CIDR groups manager, its cache reload task and the CIDR permissions cache are not modeled |
| scheduled-task | `CassandraRoleManager.scheduleSetupTask: StorageProxy.isSafeToPerformRead` | `auth/CassandraRoleManager.java:488` | cassandra-role-manager.schedule-setup-task (flow role-manager-setup) |
| scheduled-task | `MigrationCoordinator.start: pullUnreceivedSchemaVersions` | `schema/MigrationCoordinator.java:263` | migration-coordinator.pull-unreceived-schema-versions (flow schema-periodic-pull) |
| verb-handler | `SchemaPullVerbHandler.doVerb` | `schema/SchemaPullVerbHandler.java:48` | schema-pull-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| verb-handler | `SchemaPushVerbHandler.doVerb` | `schema/SchemaPushVerbHandler.java:51` | schema-push-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |
| verb-handler | `SchemaVersionVerbHandler.doVerb` | `schema/SchemaVersionVerbHandler.java:36` | schema-version-verb-handler.do-verb (flows schema-push-receive / schema-pull / schema-version-request) |

Total: 80 entries, 70 covered, 10 skipped.

### Skipped entry points (also in skips/schema-auth.json)

- `AuthCacheMBean.getValidity`, `getUpdateInterval`, `getMaxEntries`, `getActiveUpdate`,
  `getEstimatedSize` (auth/AuthCacheMBean.java:27,31,35,37,41): reads of cache configuration or size, no behavior.
- `CIDRGroupsMappingManagerMBean.getAvailableCidrGroups`, `recreateCidrGroupsMapping`,
  `getCidrGroupsOfIP`: CIDR authorization is disabled in the deployed config
  (`cidr_authorizer: AllowAllCIDRAuthorizer`, conf/cassandra.yaml:261-262); the read-only lookups and the
  bulk recreate are not modeled.
- Scheduled `CIDRGroupsMappingCache: reloadCidrGroupsCache` (auth/CIDRGroupsMappingCache.java:67): the cache
  exists only with CassandraCIDRAuthorizer (CassandraCIDRAuthorizer.java:68).
- `SCHEMA_PUSH_RSP` (net/Verb.java:155): not an entry point. SchemaPushVerbHandler never replies and the
  push is sent without a callback (schema/MigrationCoordinator.java:752-758).

The CIDR operations `updateCidrGroup`, `dropCidrGroup`, `loadCidrGroupsCache` and
`invalidateCidrPermissionsCache` are now modeled (reconciliation, decision 6), so they are covered and no
longer skipped. The managers are set up even under AllowAllCIDRAuthorizer
(AbstractCIDRAuthorizer.commonSetup). Group updates and drops work; load and invalidate fail with
InvalidRequest (AllowAllCIDRAuthorizer.java:50-59).

Owned elsewhere, for the record: nodetool `resetlocalschema`, `reloadlocalschema`, `getauthcacheconfig`,
`setauthcacheconfig`, `invalidaterolescache` and the `StorageServiceMBean`/`StorageProxyMBean` schema
operations belong to ops. They should call `schema.reset-local-schema`,
`schema.reload-schema-and-announce-version`, `auth-cache.set-*` and `roles-cache.invalidate-roles`.
`AUTH_RESPONSE` belongs to transport.

## 2. Components

Schema (parent `schema-auth`):
- `schema` - Schema.java:86-127 (state: local version). Interfaces `transform` (606-614),
  `merge-and-update-version` (594-604, 644-779), `get-version` (497-500), `get-keyspace-metadata` (318-322),
  `reset-local-schema` (620-642), `reload-schema-and-announce-version` (583-586).
- `default-schema-update-handler` - DefaultSchemaUpdateHandler.java:55-110. `apply` (227-253),
  `update-schema` (255-271), `apply-mutations` (200-225 plus the push lambda 93-99),
  `apply-mutations-from-coordinator` (333-343), `get-schema-mutations` (100-109, 345-351),
  `get-schema-version-for-coordinator` (325-331), `clear` (311-323).
- `migration-coordinator` - MigrationCoordinator.java:98-265. `announce` (574-579),
  `push-schema-mutations` (747-776), `report-endpoint-version` (428-463), `maybe-pull-schema` (282-319),
  `should-pull-from-endpoint` (354-400), `schedule-schema-pull` (548-572), `pull-schema` (659-687),
  `pull-complete` (689-704), `pull-unreceived-schema-versions` (257-280), `reset` (521-531, 496-514),
  and stores for endpointVersions, versionInfo and lastPullFailures.
- `migration-coordinator-callback` - the inner Callback, 607-657 (`on-response`, `on-failure`).
- `schema-keyspace` - SchemaKeyspace.java (system_schema rows per replica): `apply-changes` (1424-1429),
  `calculate-schema-digest` (374-394), `convert-schema-diff-to-mutations` (296-333),
  `convert-schema-to-mutations` (415-423), `truncate` (358-362), row stores.
- `schema-change-notifier` - SchemaChangeNotifier.java:49-93.
- `schema-push-verb-handler`, `schema-pull-verb-handler`, `schema-version-verb-handler` - their doVerb.
- DDL statements under `alter-schema-statement` (AlterSchemaStatement.java:43-167): one component per
  statement class in cql3/statements/schema, including the 7 inner ALTER TABLE and 3 inner ALTER TYPE
  classes, each with an `apply` interface citing its apply method.

Auth:
- `auth-config` (AuthConfig.java:41-130), `auth-properties` (AuthProperties.java), `auth-keyspace`
  (system_auth tables; AuthKeyspace.java:44-160), `authenticated-user` (AuthenticatedUser.java),
  `roles` (Roles.java), `auth-cache` (AuthCache.java) with `cache-refresher`, `permissions-cache`,
  `roles-cache`, `network-permissions-cache`, `authorization-proxy-jmx-permissions-cache`,
  `password-authenticator-credentials-cache`; `data-resource`, `role-resource`, `function-resource`;
  `allow-all-authenticator` (+ `-negotiator`), `password-authenticator` (+ `-plain-text-sasl-authenticator`),
  `allow-all-authorizer`, `cassandra-authorizer`, `cassandra-role-manager`, `auth-schema-change-listener`.
- Statements: `create-role-statement`, `alter-role-statement`, `drop-role-statement`,
  `role-management-statement`, `grant-role-statement`, `revoke-role-statement`, `authorization-statement`,
  `permissions-management-statement`, `grant-permissions-statement`, `revoke-permissions-statement`,
  `list-roles-statement`, `list-users-statement`, `list-permissions-statement`.

Model conventions (also in the fragment header):
- Nodes are instances n1..n3 of `cassandra-node` (`fixtures: [three-node-rf3]`); n1 coordinates by
  default. Every schema-auth component has per-instance state. system_schema rows are keyed
  `<kind>:<ks>[.<name>]` on each instance (seeded by `base-schema`) with a `sig` string; the schema
  version is `v:` plus the instance's sigs in key order, a stand-in for the MD5 content digest. Two nodes
  with the same rows report the same version, which is what makes push, pull and agreement checkable.
- system_auth lives in `auth-keyspace` on each instance (seeded identically). Every read or write first calls the cql boundary
  with the consistency level the code uses, so faults there reproduce unavailable or timeout behavior.
- Passwords are stored as `bcrypt:<password>`; BCrypt is not simulated.

## 3. Boundary stubs

| Stub | Owner | Contract source |
|---|---|---|
| `client-state.ensure-permission` | transport | copied from transport.yaml (request `{resource, keyspace, permission}`, unauthorized) |
| `client-state.ensure-not-anonymous` | transport | transport has none yet; shape from ClientState.java:582-587 |
| `client-warn.warn` | transport | copied (`{text}`) |
| `authentication-statement.check-permission` | cql | copied from cql.yaml |
| `query-processor.process-query-string` | cql | new: the static `process(String, ConsistencyLevel[, values])` (QueryProcessor.java:377-386) is not in cql.yaml. cql should adopt this name or tell me theirs |
| `query-processor.process-batch` | cql | cql.yaml (CqlRequest subset: statement, options.consistency, client_state; errors copied) |
| `select-statement.execute` | cql | cql.yaml (CqlRequest subset, called with `fill: true`; partition_keys carry token 0) |
| `gossiper.get-live-members` | membership | copied (`{members}`) |
| `gossiper.is-alive` | membership | not in membership.yaml; shapes mirror `failure-detector.is-alive` |
| `gossiper.add-local-application-state` | membership | copied, enum extended with `SCHEMA` |
| `pending-range-calculator-service.calculate-pending-ranges` | membership | not defined there; PendingRangeCalculatorService.java:86-89 |
| `keyspace.open`, `keyspace.init-cf`, `keyspace.drop-cf`, `keyspace.unload`, `column-family-store.reload` | write-path | not defined there; Keyspace.java / ColumnFamilyStore.java |
| `storage-proxy.is-safe-to-perform-read` | coordination | not defined there; StorageProxy.java:1888-1896 |

Contracts other areas stub on my side (to reconcile):
- transport stubs `password-authenticator.evaluate-response` and `.get-authenticated-user`. By the naming
  rule they live on the inner class: `password-authenticator-plain-text-sasl-authenticator.*` (and
  `allow-all-authenticator-negotiator.get-authenticated-user` for the deployed authenticator).
  transport's `evaluate-response` sends `{token}`; mine takes the decoded `{username, password}`.
- transport's `authenticated-user.can-login` expects `{can_login, is_super}`; mine returns `{can_login}`.
- transport stubs `schema.get-keyspace-metadata` as a store; mine is a function over the replica rows.
- cql stubs `cassandra-role-manager.is-super`, `is-existing-role`, `is-existing-identity`,
  `role-for-identity` and `roles.has-superuser-status` with primitive responses; mine return objects
  (`{is_super}`, `{exists}`, `{role}`).
- In the full merge, my role/auth scenarios now abort inside cql's `select-statement.execute` ->
  `storage-proxy.read` (missing `read_command`). That is a cql/coordination contract gap, not mine.

## 4. Deployed config

| Setting | conf/cassandra.yaml | Config.java default | Effective |
|---|---|---|---|
| authenticator | AllowAllAuthenticator (198) | null (82) -> AuthConfig falls back to AllowAllAuthenticator (AuthConfig.java:54, 132-148) | AllowAllAuthenticator |
| authorizer | AllowAllAuthorizer (217) | null (83) -> AllowAllAuthorizer | AllowAllAuthorizer |
| role_manager | CassandraRoleManager (232) | null (84) -> CassandraRoleManager | CassandraRoleManager |
| network_authorizer | AllowAllNetworkAuthorizer (246) | null (86) -> AllowAll | AllowAll |
| cidr_authorizer | AllowAllCIDRAuthorizer (261-262) | null (87) -> AllowAll | AllowAll |
| roles_validity / permissions_validity / credentials_validity | 2000ms (300, 327, 359) | 2s (96, 90, 102) | 2000 ms |
| *_update_interval | commented (312, 339, 371) | null (99, 93, 105) -> = validity (DatabaseDescriptor.java:1803-1808, 1848-1853) | 2000 ms |
| *_cache_active_update | commented | false (100, 94, 106) | false: no CacheRefresher |
| *_cache_max_entries | not set | 1000 (97, 91, 103) | 1000 |
| auth_read_consistency_level | commented (1960) | LOCAL_QUORUM (753) | LOCAL_QUORUM ('cassandra' role: QUORUM) |
| auth_write_consistency_level | commented (1961) | EACH_QUORUM (754) | EACH_QUORUM ('cassandra' role: QUORUM) |
| auth_cache_warming_enabled | commented (1965) | false (749) | false |
| user_defined_functions_enabled | false (1760) | false (588) | false: CREATE FUNCTION refused |
| materialized_views_enabled | false (1981) | false (596) | false: CREATE MATERIALIZED VIEW refused |
| sasi_indexes_enabled | false (1992) | false (606) | false: SASI indexes refused |
| drop_compact_storage_enabled | false (2000) | false (609) | false |
| dynamic_data_masking_enabled | commented (1973) | false (639) | false: MASKED WITH refused in validate() |
| request_timeout (SCHEMA_* verbs use rpcTimeout) | 10000ms (1349) | 10000ms (142) | 10000 ms |
| default_keyspace_rf | commented (1878) | 1 (712) | system_auth RF = max(1, cassandra.system_auth.default_rf=1) = 1 |
| simplestrategy_enabled, drop_keyspace_enabled, drop_truncate_table_enabled, alter_table_enabled, secondary_indexes_enabled, uncompressed_tables_enabled | commented (2176, 2085, 2082, 2189, 2056, 2043) | true (907, 890, ...) | guardrails pass |
| keyspaces/tables/columns_per_table/fields_per_udt/... thresholds | commented (2034-2061, 2180) | -1 | disabled |

System properties (CassandraRelevantProperties): `cassandra.migration_delay_ms` 60000 (359),
`cassandra.schema_pull_interval_ms` 60000 (481), `cassandra.superuser_setup_delay_ms` 10000 (538),
`cassandra.system_auth.default_rf` 1 (539), `cassandra.role_password_update_min_interval_in_ms` 5000 (432),
`cassandra.schema_delay_ms` unset -> SCHEMA_DELAY_MILLIS 30000 (StorageService.java:325-338).

Where the yaml and Config.java differ: only the auth backends, which the yaml names explicitly while
Config.java leaves them null. AuthConfig's fallbacks make the effective values identical. Every other
value in this area is the same in both or left to Config.java.

## 5. What the code didn't settle, and assumptions

- The schema version is a digest; I use a readable content string. Two replicas with identical rows
  agree, which is all the model relies on.
- In-memory schema (Schema/DistributedSchema) and system_schema are kept as one copy of the rows.
  Statements read the coordinator's rows where the code reads in-memory keyspaces.
- Gossip application state for peers (RELEASE_VERSION, SCHEMA, messaging version, gossip-only) is
  seeded as a mirror (`migration-coordinator.state.peers`) so scenarios can vary it. Liveness goes
  through membership's `gossiper.*` stubs. The range-movement check in ALTER KEYSPACE is a choice.
- CassandraRoleManager reads go through `select-statement.execute` (prepared statements) or
  `query-processor.process-query-string` (string queries) as the code does. The data comes from
  `auth-keyspace`.
- The role-identity check in createRole is assumed empty (no identities are bound to new roles).
- `setupDefaultRole`: the three-step hasExistingRoles is simplified to "any row exists" followed by
  the QUORUM probe and the insert. The empty-ring IllegalStateException is not modeled.

## 6. Where docs or common knowledge disagree with the code

- DDL does not wait for schema agreement on the server. AlterSchemaStatement returns after the local
  apply; the push to peers runs on the MIGRATION stage afterwards, with no callback. Agreement is the
  driver's job (it polls schema versions). A lost push is only repaired by a pull, which a running node
  postpones by MIGRATION_DELAY (60 s), plus the periodic task every 60 s.
- Under the default config (AllowAllAuthenticator) every role and permission statement fails in
  validate() with "You have to be logged in and not anonymous to perform this request". GRANT/REVOKE
  would also fail with UnsupportedOperationException (server error), and LIST PERMISSIONS with an
  invalid request.
- Auth consistency in 5.0: non-default roles are read at LOCAL_QUORUM and written at EACH_QUORUM
  (configurable, JMX-settable), not ONE/LOCAL_ONE as older docs say. The 'cassandra' role always uses
  QUORUM. Exceptions in the code: getExistingPermissions in GRANT/REVOKE reads at a hard-coded
  LOCAL_ONE (CassandraAuthorizer.java:222-227), getAllRoles always uses QUORUM (376-390), and the
  password rate limit reads at LOCAL_ONE (CassandraRoleManager.java:690-696).
- REVOKE removes the resource->role index entry whenever it revokes anything, even when the role keeps
  other permissions on the resource (CassandraAuthorizer.java:121-125). revokeAllOn can then miss them.
- revokeAllFrom/revokeAllOn swallow failures (log only), so a DROP ROLE / DROP KEYSPACE can leave
  permissions behind.
- system_auth defaults to RF 1, so with one node down some roles cannot be read at LOCAL_QUORUM, and
  logins or permission checks fail with "Unable to perform authentication/authorization".
- Login caching: PermissionsCache and RolesCache only exist when authorization/authentication is on.
  CredentialsCache is always on, and a missing role caches a sentinel that authenticate() expunges.
- Error text quirks preserved: "Unkown field" (AlterTypeStatement.java:210) and the stray quote in
  "Index 'ks.i' doesn't exist'" (DropIndexStatement.java:58).

## 7. Simulator gaps

- Resolved (migration): the push is one async `emit` per live peer, on that peer's instance, with no
  callback, as `messagingService.send` does; each peer merges into its own schema and announces.
  Example: `create-keyspace-propagates`, `s1-schema-agreement-push-and-pull`.
- Resolved (migration): delayed pulls are timers (`emit ... after_ms: migration-delay-ms`, and 1000 ms
  backoff), so the gossip callback returns at once and the pull runs 60 s later. Example:
  `schema-pull-postponed`. Immediate pulls still run inline (the MIGRATION executor starts them at once).
- Resolved (migration): cross-node convergence chains in one run as a multi-step scenario (DDL, then a
  gossip SCHEMA change on n3, then the timer-driven pull). Gossip propagation itself is membership's,
  so the scenario plays the onChange delivery as a step.
- Await on a promise: resetLocalSchema waits up to 30 s for an async pull. The model runs the pulls
  synchronously inside `clear` and checks a flag, so the failure takes 2 x 10 s pull timeouts instead of
  30 s. Example: `reset-local-schema-no-answer`.
- No recursion: collectRoles walks member_of recursively; the model follows two levels.
- Scenario state can only merge, so rows can't be deleted; `role-manager-setup-creates-superuser`
  overrides rows with a `tombstone` string, which `roles-query` filters out.
- Stub outputs can't be varied per scenario: "no other live nodes" for resetlocalschema and
  `gossiper.is-alive == false` can't be expressed without membership's real behavior. Unreachable
  peers use `timeout` faults on the verb instead.
- Caffeine refreshAfterWrite (serve stale while reloading in the background) is not modeled; only
  expireAfterWrite. Under the defaults update_interval == validity, so expiry dominates. Example:
  `permission-check-cache-expired`.
- Resolved (migration): CacheRefresher is a periodic timer (`every_ms` update interval, 3 deliveries in a run).
- Hashing (BCrypt, MD5 schema digest) uses string stand-ins.

## 8. Known gaps

- Resolved (migration): DDL `authorize()` is `alter-schema-statement.authorize`, which maps each
  statement type to the permission and resource its class checks, and calls transport's ClientState.
- validate() guardrails (table, column and keyspace counts, table properties) are narrated, not modeled.
  All are disabled in the deployed config.
- Statement validation is simplified: column types, clustering, static columns, compact storage,
  dropped-column records, transient replication, view WHERE clauses, function bodies. Keyspace params
  validation (RF options, NTS DCs, the "RF higher than nodes" warning in SimpleStrategy) is
  coordination's locator code and isn't modeled.
- A pull applies only puts, so a keyspace dropped on a peer doesn't propagate through a pull in the
  model. In the code, full-partition schema mutations carry the tombstones.
- Schema listeners other than auth (the client SCHEMA_CHANGE event push, index and view managers) are
  not modeled. Neither are the peers' own gossip announcements after a push.
- MigrationCoordinator's per-version request queue and its limit of 3 outstanding requests are
  simplified to one endpoint per version. Bootstrap waitUntilReady/awaitSchemaRequests and the
  IGNORED_SCHEMA_CHECK_* properties are not modeled.
- Not modeled: network authorizer (datacenter restrictions), CIDR authorizer, mutual-TLS
  authenticators, auth cache warming and bulk loaders, JMX authorization proxy checks.
- ClientState's resource-chain walk (table -> keyspace -> ALL KEYSPACES) belongs to transport. My
  `authenticated-user.get-permissions` answers one resource.

## 9. Reconciliation changes

- Defined the 12 interfaces callers needed (decision 6): `schema.validate-table`, `get-distributed-schema-blocking`,
  `largest-gcgs`, `load-from-disk`; `partition-denylist.is-key-permitted`, `get-denied-keys-in-range-count`
  (store contract as coordination stubbed it); `password-authenticator.evaluate-response` and
  `get-authenticated-user` in transport's shapes. They decode the token (NUL rendered as `\0`), keep the
  credentials on the component and delegate to the inner PlainTextSaslAuthenticator. Also
  `cidr-groups-mapping-manager.{update-cidr-group, drop-cidr-group, load-cidr-groups-cache}` and
  `cidr-permissions-manager.invalidate-cidr-permissions-cache`. Each has a flow and scenarios.
- Seeded data now matches the cluster's scenarios. The shop keyspace holds the tables other areas use
  (accounts, entries, orders, page_views, users), so a real `validate-table` agrees with their requests.
  The baseline schema version string changed with it. alice's password is now `s3cret`, to match
  transport's SASL token. Local and virtual system keyspaces are accepted by validate-table without a
  table check, because they aren't stored in system_schema.
- `client-warn` takes transport's kind (function). `partition-denylist` takes coordination's kind.
  The cql stubs (`query-processor.process-query-string`, `process-batch`, `select-statement.execute`) copy
  cql's `retryable: false`. `client-state.ensure-not-anonymous` copies transport's response, and the
  scenarios that need a logged-in user seed `client-state: {user, authenticator}` (transport's state).

## 10. Migration round (instances, timers, config, fixtures, multi-step)

- **Instances.** `to`/`replica` fields are gone: 3 `to` fields on SCHEMA_* requests and the `replica`
  field on 14 request schemas and calls. The verbs use `on:` (pull, push), and every row key lost its
  `<replica>:` prefix. Endpoint-keyed initial state (`schema-keyspace.rows`, `migration-coordinator.peers/
  endpoint_versions/version_info`, `schema.version`) was emptied; `fixtures.yaml` seeds it. `state.local`
  became `self` (10 places). Scenarios use `fixtures: [three-node-rf3]` and assert per instance
  (`state['schema-keyspace@n2']`, `calls_by_instance`). Peers now merge on their own instance, so a DDL
  runs `keyspace.init-cf`/`open` once per node.
- **Fan-out.** The schema push is fire-and-forget, not a wait-for-k: one `emit` per live peer replaces
  the sequential `foreach` of calls. No `parallel` join applies in this area, because nothing here waits
  for k of n.
- **Config.** 32 config entities (31 owned, plus `request-timeout-ms` as a boundary reference). Behaviors
  read: auth backends (`auth-config`, with fixture state still overriding), auth consistency levels, auth
  cache validity, interval and active update, `user-defined-functions-enabled`,
  `materialized-views-enabled`, `sasi-indexes-enabled`, `drop-compact-storage-enabled`,
  `migration-delay-ms`, `request-timeout-ms` and `role-password-update-min-interval-ms`. With
  `materialized-views-enabled` or `user-defined-functions-enabled` set to true, CREATE MATERIALIZED VIEW
  and CREATE FUNCTION now succeed (scenarios `create-view-enabled`, `create-function-enabled`).
- **Timers.** Delayed and backoff pulls and CacheRefresher are timers. The periodic pull and the
  superuser setup task use `entry.repeat.initial_delay_ms` (60 s and 10 s).
- **Incidental.** `auth-cache` is tagged `incidental`.
- **writes.** 27 flows are tagged `writes`, each with a multi-step read-back scenario (`*-read-back`,
  `identity-add-then-resolve`).
- **DDL from QUERY (judge §2.1, MIGRATE §3).** cql's `process-statement` should dispatch every DDL type to
  `alter-schema-statement.authorize`, `.validate` and `.execute` (or `.execute-locally` for NODE_LOCAL)
  with its CqlRequest: `statement.type` is one of the `SchemaAuthDdlRequest` types (CREATE_KEYSPACE ...
  DROP_TRIGGER; ALTER TABLE/TYPE carry the alteration, e.g. ALTER_TABLE_ADD_COLUMNS), plus the statement
  fields (keyspace, table, name, columns, partition_key, replication, options, if_exists, if_not_exists,
  or_replace...) and `client_state.user`. Role and permission statements keep their
  `SchemaAuthRoleStatement` contract (`user`, `role`, `grantee`, `options`, `permissions`, `resource`,
  `if_exists`, `if_not_exists`, `recursive`). cql maps CREATE_ROLE -> `create-role-statement`,
  ALTER_ROLE, DROP_ROLE, GRANT_ROLE -> `role-management-statement` (authorize/validate) +
  `grant-role-statement.execute`, REVOKE_ROLE, GRANT_PERMISSIONS ->
  `permissions-management-statement.authorize` + `grant-permissions-statement.{validate,execute}`,
  REVOKE_PERMISSIONS, LIST_ROLES/LIST_USERS -> `list-roles-statement` (statement: list-users-statement
  for LIST USERS), LIST_PERMISSIONS -> `list-permissions-statement`.
- **S1 (judge).** `s1-schema-agreement-push-and-pull`: CREATE TABLE on n1 answers SCHEMA_CHANGE in under
  100 ms, before any agreement (AlterSchemaStatement.java:107-137, DefaultSchemaUpdateHandler.java:244-250).
  The push reaches n2 and is lost to n3. At 1 s n3 hears n1's SCHEMA version in gossip
  (DefaultSchemaUpdateHandler.java:157-168, new `default-schema-update-handler.on-change`). n3 postpones
  by `migration-delay-ms` (MigrationCoordinator.java:565-569), pulls from n1 at about 61 s, and merges.
  All three versions are then equal, and n3's SCHEMA_VERSION_REQ confirms it.
- **Contract notes for others.** membership's `gossiper.add-local-application-state` enum still lacks
  `SCHEMA` (gms/ApplicationState.java:34), so every announce warns in the merge (judge §2.5).
  Membership should also deliver SCHEMA changes to `default-schema-update-handler.on-change` (the
  subscriber registered at DefaultSchemaUpdateHandler.java:92).
