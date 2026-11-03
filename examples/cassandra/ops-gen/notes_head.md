# ops: notes

Area `ops` of the Cassandra 5.0.9 ontology (`fragments/ops.yaml`): the daemon's startup, nodetool and
the JMX operations it invokes, tracing sessions, the audit log and the full query log, plus the
operational glue in `StorageService` behind `StorageServiceMBean`. All citations are relative to
the checkout `cassandra-5.0.9` (`b5f2a54210`).

How the fragment is organised:

- **nodetool** is one dispatcher, `node-tool.execute` (NodeTool.execute), that connects through
  `node-probe.connect` and calls `nodetool-<command>.execute` (one component per command class).
  It maps exceptions as NodeTool does: IllegalArgumentException or IllegalStateException (and airline
  parse errors) give exit status 1 with `nodetool: <message>`; anything else gives exit 2 with
  `error: <root cause message>`; a failed JMX connection exits 1. The result is
  `{exit_status, output}`, so scenarios assert the exit status the operator sees.
- **JMX operations** of the service MBeans (`StorageServiceMBean`, `StorageProxyMBean`,
  `CacheServiceMBean`, `ActiveRepairServiceMBean`) are interfaces of kind `jmx` on ops components
  named after the MBean (`storage-service-mbean.force-keyspace-flush`). Each cites the MBean
  declaration line (coverage) and the implementing method, and models the StorageService glue
  (table resolution, refusals, status aggregation). Where the implementation is another area's,
  the operation calls that area's interface as a boundary stub. For MBean operations whose whole
  behavior another area already models on its own component (repairAsync, takeSnapshot,
  clearSnapshot, drain, decommission, move, removeNode, joinRing, rebuild, resumeBootstrap,
  start/stopGossiping), the nodetool command calls the owner's interface directly and cites the
  MBean declaration in the step, so nothing is modeled twice.
- Operations of MBeans in other areas' packages (HintsServiceMBean, GossiperMBean,
  CompactionManagerMBean, ColumnFamilyStoreMBean, auth caches, BatchlogManagerMBean,
  MessagingServiceMBean) are reached the same way: the nodetool command calls the owner's interface
  and cites the MBean line.
- `mbean-wrapper.invoke-operation` is the path for any JMX client (jconsole, scripts): a dynamic call
  over every modeled service-MBean operation, used by the `jmx-operation` flow for operations no
  nodetool command invokes.

## Flows and scenarios

| Flow | Entry | Scenarios | What it proves |
|---|---|---|---|
| `daemon-startup` | `cassandra-daemon.activate` | 13 | setup order, startup checks with their exit codes (1, 3, 100), config error exit 3, commit log replay failure exit 3, initServer ConfigurationException exit 1, transports skipped when bootstrap incomplete or `start_native_transport: false`, cache load failure tolerated |
| `nodetool-repair` | `node-tool.execute` (repair) | 11 | system_distributed skipped unless named, incremental by default, RF 1, FAILED parent status, ERROR notification, connection closed, `-pr` with `-dc`, unknown keyspace, JMX unreachable, invalid options |
| `nodetool-flush` | `node-tool.execute` (flush) | 7 | per-table forceBlockingFlush, unknown table wrapped (exit 2, not 1), unknown or virtual keyspace refused client side (exit 1), flush failure |
| `nodetool-cleanup` | `node-tool.execute` (cleanup) | 7 | pending ranges refusal, local system keyspace skipped client side, ABORTED (exit 0 with message) vs UNABLE_TO_CANCEL (exit 2), `--jobs` warning |
| `nodetool-decommission` | `node-tool.execute` | 4 | already decommissioning/decommissioned short-circuits, UnsupportedOperationException becomes IllegalStateException (exit 1) |
| `nodetool-drain` | `node-tool.execute` | 3 | only IOException/InterruptedException/ExecutionException are wrapped |
| `nodetool-snapshot` | `node-tool.execute` | 6 | tag with path separator refused client side, server IOExceptions wrapped (exit 2), IllegalArgumentException not wrapped (exit 1) |
| `nodetool-hinted-handoff` | `node-tool.execute` | 10 | disable/enable handoff (enable refused after drain), pause/resume dispatch, truncatehints all or per endpoint, hints per DC, max hint window |
| `nodetool-runtime-config` | `node-tool.execute` | 11 | compaction throughput updates the rate limiter, settimeout dispatch and validation, client-side checkArgument refusals, unknown stage IllegalStateException, cache capacity refusal |
| `nodetool-audit-and-fql` | `node-tool.execute` | 7 | enable/disable audit log, archive command refused, FQL refused with the deployed empty `log_dir`, FQL already configured |
| `audit-log-query` | `audit-log-manager.query-success` | 5 | disabled by default (nothing logged), logged when enabled, exclusion beats inclusion, user include list |
| `tracing-session` | `tracing-impl.begin` | 3 | trace rows written async at CL ANY on the TRACING stage; OverloadedException swallowed; other failures do not affect the traced request |
| `tracing-remote-event` | `tracing-impl.trace` | 1 | replica-side event on the TRACING stage |
| `jmx-operation` | `mbean-wrapper.invoke-operation` | 11 | JMX-only operations: truncate (and Unavailable -> IOException), denylist, repaired-data tracking, saveCaches, deliverHints unsupported, sampling validation |
| `nodetool-command` | `node-tool.execute` | 72 | one happy path per remaining action command, plus unknown command, read-only command, bootstrap resume disabled, client-side validation |

## 1. Entry points

Inventory entries in this area: all `jmx-operation` (913) and `cli-command` (159) entries, the
`java-main` entries under `tools/` plus `CassandraDaemon` and `utils/DynamicList`, the four
`python-cli` entries, and the scheduled, background and stage tasks under `utils/`, `metrics/`,
`security/`, `tracing/`, `CassandraDaemon` and `DataResurrectionCheck` (claimed because it is
StartupChecks' heartbeat). That is 1118 entries: 253 covered and 865 skipped with a reason.
Owners may also cover some of the skipped JMX entries of their own MBeans. One getter,
`CacheServiceMBean.getRowCacheSavePeriodInSeconds`, counts as covered only because the
`cache-service-mbean` component cites the interface declaration two lines above it.
