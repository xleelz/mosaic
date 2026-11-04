# Fix round 5 (vLLM): precision, and the worlds the judges lacked

Round 4 fixed coverage of what the tests exercise: the oracle tripled, from 2/36 to 6/36. But the
new benchmark (BENCHMARK3) passes 3 of 32 cases. The judges found behavior that is modeled but
wrong in its details, and behavior they couldn't drive at all, because no world has an MoE, a
vision-language or an FP8-checkpoint model.

- `BRIEF.md`, `RECONCILE.md`, `FIXES.md`, `FIXES3.md` and `FIXES4.md` still apply.
- **The code** is `~/.cache/mosaic-bench/vllm-0.32.0`, read-only.
- **You may now read** `judge3/` and `oracle3/` (round 4's blind measure), the "Round 4" section of
  `RESULTS.md`, and `reconcile/round4/measure-notes.md`.
- **Never read** `BENCHMARK4.md`, `oracle4/` or `judge4/`. They are this round's blind measure.
- **Breaking changes toward the code are welcome.** List each one, with the callers it breaks. Fix
  through your generator; `config-platform` edits its fragment directly. Before reporting, run
  `.claude/skills/mosaic-generate/scripts/mcheck` with the full `-f` list and
  `--stage examples/vllm/fragments/<area>.yaml --accept`.

## New worlds

`examples/vllm/worlds.yaml` and `fixtures.yaml` gain three worlds (the coordinator adds them before
you start; see their summaries in the file):
- an **MoE** model deployment, with expert parallelism;
- a **vision-language** model with multimodal inputs;
- an **FP8-checkpoint** model.

Use them: where your area's behavior depends on the model being MoE, multimodal or FP8, model that
behavior and give it scenarios in the matching world.

## Your list

1. **Every wrong claim the round-4 measure attributes to your area.** Find them in:
   - `RESULTS.md` "Round 4 ... Wrong claims to fix", under your area;
   - every `judge3/<group>.md` step graded partial, fail or missing whose component is yours;
   - every `oracle3/<area>.md` model-bug row.

   For each one:
   - Fix it against the code exactly.
   - Re-run the scenario **unedited**. It passes, or you explain why in your notes, with a citation.
     A judge expectation that is wrong about the code goes into `reconcile/round5/measure-notes.md`.
   - Add a regression scenario.
2. **Precision sweep of your area's error paths:** status, error type, message text word for word,
   and the order of checks, for every interface with a `fail`. Work from the most-used down.
3. **Your unit tests.** `build-oracle/round5/<area>.json` holds 6 fresh tests. Translate them into
   `build-oracle/round5/<area>.{yaml,md}`, and fix the model until each passes or is untranslatable
   for a stated reason.
4. **Keep the gate where it is:** thresholds don't go up, coverage doesn't drop, and citations resolve.

## Simulator fixes landing during the round

A separate agent is adding these to mosaic:
- `{$absent: true}` deleting a fixture row;
- a finer clock;
- configurable `foreach` and iteration caps (a 30 s drain exceeded the event budget);
- `string(map)`;
- error faults that honor `latency_ms`;
- a scenario step that closes a session.

Note what you need from them, and re-check after the coordinator says they landed.

## Verify

Run the full gate as `docs/PIPELINE.md` documents it, with `--profile examples/vllm/profile.yaml`
and `--code ~/.cache/mosaic-bench/vllm-0.32.0`. Rebuild `vllm.json`. Re-run your judge*, oracle*
and build-oracle scenarios.

**Exit criteria:**
- the merged gate passes;
- every round-4 wrong claim in your area is fixed or answered;
- the sweep is done;
- your round-5 tests pass, or are untranslatable for a stated reason;
- no earlier measure regresses.

## Report (≤150 words)

- the claims fixed;
- the error paths checked and corrected;
- the judge3/oracle3 scenarios now passing, and those still failing, with why;
- how you used the new worlds;
- your unit tests: passing, out of 6;
- your breaking changes;
- what's still open.
