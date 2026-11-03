# DynamoDB substrate

`dynamodb.yaml` models one DynamoDB endpoint from the AWS developer guide (cited per
interface). Tests:

    go run ./internal/devtools/check -f substrates/dynamodb/dynamodb.yaml \
      -f substrates/dynamodb/tables/orders.yaml -f substrates/dynamodb/scenarios.yaml

**Tables are config.** Set `dynamodb-tables` in the importing document:
`{<table>: {gsis?: {<index>: {pk: <attr>, sk?: <attr>}}, ttl_attribute?: <attr>}}`. Every
table's primary key is `pk` plus `sk` (`""` without a sort key); items live in
`state['<as>/dynamodb'].items['<table>|<pk>|<sk>']`. An unknown table is `resource_not_found`.

**Operations** (each takes `table`, `pk`, `sk`):
- `get` (a miss returns `item: null`), `put`, `update` (SET, plus `remove: [attrs]`; creates
  a missing item), `delete`.
- `put-if`, `update-if`, `delete-if`, `incr-if`: `cond` is CEL over `row` (`null` when absent),
  defaulting to `"true"` (`"row != null"` for update-if). A failed condition writes nothing and
  fails `{code: condition_failed, status: 412, retryable: false, data: {table, pk, sk, row}}`.
  This is the conditional-write set one build's areas converged on.
- `transact-write`: up to `dynamodb-transact-max-items` (4) writes (`put`, `update`, `delete`,
  `incr`, `check`), all or nothing; a failed condition is `transaction_canceled` (400) with
  `data.index` and `data.reasons`; two writes to one item are `validation_error`.
- `query`: by `pk` on the base table or a GSI (`index`), with `sk_begins_with`, `sk_between`,
  `forward` and `limit`; items without the index's key attributes are left out (sparse index).
- `ttl-sweep`: deletes expired items (TTL attribute in epoch seconds at or before `now`).
  Expired items stay readable until a sweep runs, as in DynamoDB; drive it from a scenario
  step or a repeating flow.

**Per-table names.** `tablegen.py` instantiates `<table>-get/put/update/delete/query` and
`<table>-put-if/update-if/delete-if/incr-if` as thin calls into the generic operations:

    python3 substrates/dynamodb/tablegen.py --table core --table events \
      --component ddb/dynamodb --target ddb/dynamodb > tables.yaml

`tables/orders.yaml` is its output for the test table.

**Simplifications.** Reads are strongly consistent and GSIs are immediately consistent;
there are no streams, scans, batch operations, capacity limits or throttling.
