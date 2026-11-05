# Fix round 6 (vLLM): mechanism coverage

Round 5 made the model exact where it was present and added MoE, vision-language and FP8 worlds:
judge3 rose from 48 to 92 of 113 steps. The blind measure barely moved: BENCHMARK4 passed 38 of 136
steps (28%) and the fresh oracle 7 of 36. Its misses are mostly **mechanisms the model doesn't
have**: pooling, embedding and scoring endpoints, offline logprobs, bad-words masking, request
histograms, the startup handshake, multi-API-server mode, the Marlin FP8 path, EPLB rearrangement,
warmup and autotune, whole model families. This round adds the mechanisms, end to end, then makes
them exact.

- `BRIEF.md`, `RECONCILE.md`, `FIXES.md`, `FIXES3.md`, `FIXES4.md` and `FIXES5.md` still apply.
- **The code** is `~/.cache/mosaic-bench/vllm-0.32.0`, read-only.
- **You may now read** `judge4/` and `oracle4/` (round 5's blind measure), the "Round 5" section of
  `RESULTS.md`, and `reconcile/round5/`.
- **Never read** `BENCHMARK5.md`, `oracle5/` or `judge5/`. They are this round's blind measure.
- **Breaking changes toward the code are welcome.** List each one with the callers it breaks. Fix
  through your generator; `config-platform` edits its fragment directly.

## Your list

1. **Every absent mechanism the round-5 measure attributes to your area.** Find them in:
   - `RESULTS.md` "Round 5 ... Wrong claims to fix", under your area;
   - every `judge4/<group>.md` step graded missing, partial or fail whose component is yours;
   - every `oracle4/<area>.md` model-bug row.

   For each: model the mechanism the way the code runs it (its trigger, its state, its calls to
   other components, its timing from config, its errors). Re-run the judge's or oracle's scenario
   **unedited**; it passes, or your notes say why with a citation (a judge expectation wrong about
   the code goes to `reconcile/round6/measure-notes.md`). Add a regression scenario.
2. **Your area's other unmodeled mechanisms on the request paths.** Run
   `.claude/skills/mosaic-generate/scripts/coverage_gaps.py examples/vllm --by owner` (your area's
   section) and read the code around each entry point you own. Model the mechanisms a user or
   operator would observe (an endpoint, a parameter, a model family, a metric, a parallel mode),
   most-used first. Add a world variant when a mechanism needs one, as round 5 did. Report how many
   you added.
3. **Unwritten fields.** Run `--lint unwritten-fields` (DESIGN §13.1 item 37) on the merged set and
   fix each finding in your fragments against the code, or answer it in your notes.
4. **Keep the gate where it is:** thresholds don't go up, coverage doesn't drop, citations resolve.

## New tooling (commit 36bff95)

- **Joint staging.** `mcheck --stage A.yaml --stage B.yaml --accept` validates several fragments
  together and records them all only when the run passes; a failure names the staged owner and the
  stale peers, with a suggested `--stage` line. Round 5's accepts deadlocked on new world variants;
  stage with the peers whose variants you need.
- **Simulator** (behavior-language §30): a config `{$absent: true}` removes a key, so "no
  `--served-model-name`" can be driven (`null` is now a value); bracketed `set` keys with dots;
  integers past int64 stay numeric; the CEL cost limit scales with input size, so 8k-token prompts
  run without a manual raise (`--max-cel-cost` overrides).
- After adding a world variant, the coordinator regenerates `worlds.yaml`
  (`assign_inventory.py examples/vllm --worlds`); say so in your report.

## Verify

Run the full gate as `docs/PIPELINE.md` documents it, with `--profile examples/vllm/profile.yaml`,
`--code ~/.cache/mosaic-bench/vllm-0.32.0` and `--lint unwritten-fields`; the `-f` order is
skeleton, fixtures, the 9 fragments, then `worlds.yaml`. Re-run your judge*, oracle* and
build-oracle scenarios. Before reporting, run `mcheck` with the full `-f` list and
`--stage examples/vllm/fragments/<area>.yaml --accept` (joint if needed).

**Exit criteria:**
- the merged gate passes;
- every round-5 absent mechanism and wrong claim in your area is modeled and passes, or is answered;
- your unwritten-fields findings are fixed or answered;
- no earlier measure regresses without a measure note.

## Report (≤150 words)

- the mechanisms added, with counts and the main ones;
- the judge4/oracle4 scenarios now passing, and those still failing, with why;
- other mechanisms added from coverage_gaps, and any world variants;
- unwritten fields fixed;
- your breaking changes;
- what's still open.
