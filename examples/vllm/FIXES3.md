# Fix round 3 (vLLM): get the model right

vLLM's round-2 scores (benchmark 27–28/28, oracle 19/19) were measured on cases the builders had
fixed against, so they overstate accuracy. A gateway-platform build showed how much: about 38/45 on seen cases,
and 10/40 blind.

This round fixes what the cross-level check and the new gates found, and ends with vLLM's first
blind measure.

- `BRIEF.md`, `RECONCILE.md` and `FIXES.md` still apply. So do the mosaic language additions since
  then: DESIGN §15–17, and the `mosaic-simulation` skill (`io`, `id()`, invariants, tags, `wait`
  steps, stream windows, streams on routes, `duration_us`, `lane`).
- **Never read** `BENCHMARK2.md`, `oracle2/` or `judge2/`. They are this round's blind measure.
- **Breaking changes toward the code are welcome.** List each one, with the callers it breaks.
  Fix through your generator. `config-platform` has no generator, so edit its fragment directly and
  say so. Before reporting, run
  `.claude/skills/mosaic-generate/scripts/mcheck --stage examples/vllm/fragments/<area>.yaml --accept`.

## Your fix list: `reconcile/round3/<area>.txt`

1. **Cross-level findings** (serving-api, worker-runner, engine-core). The vLLM model was used as
   the refinement of a gateway platform's serving engine. That
   showed it can't stop a request naturally (no EOS), misses request validation, and doesn't
   stream incrementally. Fix them against the vLLM 0.32.0 code
   (`~/.cache/mosaic-bench/vllm-0.32.0`).
2. **The exploration failure** (engine-core). Either fix the ordering in the model, or move a
   guarantee the code doesn't make out of `expect` and into `invariants:`. Tag concurrency
   scenarios `tags: [concurrency]`.
3. **Debt:**
   - **`racy`: drive to 0.** 44 findings across the areas. Model compare-and-set as the code does
     it (Python locks, asyncio ordering, atomic dict ops), or mark `single_writer` when one
     task/thread owns the state (cite the owner, for example the engine-core busy loop). Mark
     `racy_in_code` with citations when the code really races. The `exemptions` lint now checks
     that citations support the claim.
   - **`unknown-inputs`: drive to 0.** 109 of them are in models-layers.
   - **`clock-ids`: drive to 0** (serving-api's 8). Use `id()` or `seq()`.
   - **`unraised-errors`: drive to 0.**
   - **`internal-assertions`: halve them at least.** Assert on `io`, `result` and `steps.*` where
     the behavior is observable at the boundary. Keep trace or internal assertions only where the
     internal path is the test's point, with a comment.
4. **Your unit tests.** `build-oracle/round3/<area>.json` holds 6 fresh tests. Translate them into
   `build-oracle/round3/<area>.{yaml,md}`, and fix the model until each passes or is
   untranslatable for a stated reason.

## Verify

Run the full gate as `docs/PIPELINE.md` documents it, from `/home/lbethay/workplace/mosaic`, with
`--profile examples/vllm/profile.yaml` (thresholds come from its `gates:`) and
`--code ~/.cache/mosaic-bench/vllm-0.32.0`. Then rebuild `vllm.json`:

```sh
go run ./internal/devtools/check -f examples/vllm/skeleton.yaml -f examples/vllm/fixtures.yaml \
  -f examples/vllm/worlds.yaml <fragments> -o examples/vllm/vllm.json
```

Also re-run your area's `judge/` scenarios, `oracle/` and `build-oracle/` scenarios, including
`round3`. The coordinator lowers `gates:` after the round, and runs the vLLM-under-gateway
refinement check again.

**Exit criteria:**
- the merged gate passes;
- your list is fixed;
- your debt is at the targets above;
- your round-3 tests pass, or are untranslatable for a stated reason;
- no earlier measure regresses.

## Report (≤150 words)

- the fixes;
- the debt before and after, per lint;
- your unit tests: passing, out of 6;
- your breaking changes;
- what's still open.
