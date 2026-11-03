# Redis substrate

`redis.yaml` models one standalone Redis server from the Redis command reference (each
interface cites the page it follows; there is no code snapshot). `scenarios.yaml` holds its
tests:

    go run ./internal/devtools/check -f substrates/redis/redis.yaml -f substrates/redis/scenarios.yaml

**Keyspace.** One component, `redis`. Every key is `state.keys[<key>] = {type, value, expires_at?}`:
strings store their value as a string (as Redis does; `INCR` parses it), hashes a map of string
fields, sorted sets a map of member to double score. `expires_at` is epoch ms. A command on the
wrong type fails `wrongtype` with Redis's WRONGTYPE message; other refusals are `err` with the
`ERR ...` text.

**Commands.**
- Strings: `get`, `set` (`nx`, `xx`, `get`, `ex`, `px`, `keepttl`; a refused NX/XX replies
  `ok: false`), `setnx`, `incr`, `incrby`.
- Keys and expiry: `del`, `exists`, `expire` and `pexpire` (with `nx`, `xx`, `gt`, `lt`; a
  non-positive timeout deletes the key), `ttl` (rounded, -1 and -2 as in Redis), `pttl`,
  `persist`. Expired keys are invisible to every command. A command that touches one deletes it
  (lazy expiry); `expire-cycle` is the active sweep, for callers that want the state to show it.
  `set` drops the TTL; `incr`, `hset`, `zadd` and the other in-place writes keep it.
- Hashes: `hset` (replies with fields added), `hget`, `hgetall`, `hdel` (the last field deletes
  the key), `hincrby`.
- Sorted sets: `zadd` (`nx`, `xx`, `gt`, `lt`, `ch`), `zincrby`, `zscore`, `zcard`, `zrem`,
  `zrange` (by rank, ties by member, `rev`, negative indexes), `zrangebyscore` (exclusive bounds,
  `offset`/`count`), `zremrangebyscore`.
- Lua: `eval` takes the script as a CEL expression over `KEYS`, `ARGV`, `now` and `data` (each
  declared key's row, or null), returning `{reply, writes?, error?}`. The script runs as one step,
  so no other command interleaves, and its writes (up to `redis-script-max-keys`, 4) land
  together as one transaction. As in Redis, there is no rollback: a script returning `error`
  keeps its writes and then fails `script_error`. Writing an undeclared key is `err`.
  `script-load` and `evalsha` (NOSCRIPT when unknown) cache scripts by a 40-hex digest.
- Pub/sub: `subscribe`, `unsubscribe` and `publish` by client name. A publish reaching at least
  one client pushes `{channel, message, receivers}` on the topic `redis-message`; an importer's
  subscriber declares `subscribe: [<as>/redis-message]` (imported topics take the prefix, §17
  item 8) and keeps the messages whose `receivers` hold
  its client name. Delivery is at most once and nothing is stored, so a later subscriber misses
  earlier messages.

**Redis down** is a fault on the component, not a mode: `{target: <as>/redis, type: unavailable}`
(connection refused, at once), `timeout` (a hung server; the client's `timeout_ms` decides), or
`lost_reply` with a `code` (the write lands and the reply is lost, so a retried `INCR` counts
twice). The scenarios show a cache-aside read falling back to its database.

**Scenarios** (31): strings and NX/XX/GET, TTL expiry and rounding, EXPIRE flags, PERSIST, DEL
and EXISTS over expired keys, the active cycle, hashes, sorted-set order, flags and score ranges,
Lua compare-and-delete, Lua atomicity against an interleaved GET-then-SET (which loses an
update), multi-key script writes with a TTL, no rollback, undeclared keys, EVALSHA, pub/sub
delivery, and Redis down, hung and losing a reply.

**Simplifications.** One database, no lists, sets, streams, MULTI/EXEC/WATCH, replication,
cluster slots, persistence, eviction or pattern subscriptions. The script digest is a SHA-256
prefix, not SHA1.

[../examples/rate-limited-api](../examples/rate-limited-api/) imports it.
