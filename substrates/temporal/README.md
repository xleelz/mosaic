# Temporal substrate

`temporal.yaml` models one Temporal cluster and namespace from Temporal's documentation and API
reference (each interface cites the page it follows; there is no code snapshot).
`scenarios.yaml` holds its tests, with a sample worker:

    go run ./internal/devtools/check -f substrates/temporal/temporal.yaml -f substrates/temporal/scenarios.yaml

**Components.** `temporal-server` (frontend, history and matching in one). Workers are the
importer's own interfaces, subscribed to two topics, under the import's prefix
(`<as>/temporal-workflow-task`, §17 item 8):
- `temporal-workflow-task`: `{task_token, workflow_id, run_id, workflow_type, task_queue, input,
  attempt, history, new_events}` (schema `WorkflowTask`). The worker answers with
  `respond-workflow-task-completed {task_token, commands}`; a command is `schedule_activity`,
  `start_timer`, `cancel_timer`, `complete_workflow`, `fail_workflow` or `continue_as_new`.
- `temporal-activity-task`: `{task_token, activity_id, activity_type, input, attempt,
  heartbeat_details, ...}` (schema `ActivityTask`). The worker calls `record-activity-heartbeat`,
  then `respond-activity-completed` or `respond-activity-failed`.

Every subscriber receives every task, so each filters on `workflow_type` or `activity_type`.

**Behavior.**
- `start-workflow`: a running run of the same id is handled by `id_conflict_policy` (`fail`,
  the default, is `workflow_execution_already_started`; `use_existing`; `terminate_existing`);
  closed runs by `id_reuse_policy` (`allow_duplicate`, `allow_duplicate_failed_only`,
  `reject_duplicate`, `terminate_if_running`).
- Workflow tasks: one is outstanding at a time; events arriving meanwhile wait for the next.
  Unanswered after `temporal-workflow-task-timeout-ms` (10 s), the task is redelivered with
  attempt + 1, which is how a crashed workflow worker shows up. A close command while new events
  arrived is refused as an unhandled command, and a new task carries them.
- Activities: retried per their retry policy (initial interval, coefficient, maximum interval,
  maximum attempts, non-retryable error types; Temporal's defaults otherwise). A
  start-to-close timeout, or a heartbeat timeout restarted by each heartbeat, counts as a failed
  attempt; the next attempt gets the last heartbeat's details. Retries stop at the
  schedule-to-close timeout (`activity_task_timed_out`). An answer carrying a superseded
  attempt's token is `not_found`. A worker crash is the `crash` fault on its handler: it never
  answers, and the timeouts do the rest.
- Timers (`timer_started`, `timer_fired`, `timer_canceled`), signals (`signal-workflow`;
  closed runs are `not_found`), continue-as-new (the run closes `continued_as_new` and a new run
  of the same id starts with a fresh history), `terminate-workflow`.
- Reads: `describe-workflow` (DescribeWorkflowExecution: execution info, pending activities with
  attempt, last failure, heartbeat details and next attempt time, the pending workflow task) and
  `get-workflow-history`.

**Scenarios** (15): completion, id conflict and reuse policies, retry backoff (with describe
during the backoff), maximum attempts, non-retryable types, schedule-to-close, a heartbeat
timeout after a worker crash resuming from its heartbeat details, start-to-close with a refused
late answer, a workflow task redelivered after a worker crash, a durable timer, signals, a
signal racing the close, continue-as-new, and termination. Each sets `max_virtual_ms`, which
makes the run concurrent, so steps start at their `at_ms` while earlier timers are pending.

**Simplifications.** No queries, updates, child workflows, cancellation requests, local
activities, schedule-to-start or workflow execution timeouts, namespaces or versioning. Workers
are assumed to be polling. The history leaves out the WorkflowTask* events, so its length is
smaller than Temporal's. Ids may not contain `|`.

[../examples/order-workflow](../examples/order-workflow/) imports it.
