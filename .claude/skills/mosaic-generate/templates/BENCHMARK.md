<!--
Template: how to write a benchmark (written by the coordinator before stage 4, used in stage 7).
Render into {{workspace}}/BENCHMARK.md. Builders never see it. Every later round gets a new one,
{{workspace}}/BENCHMARK<n>.md, written by a separate agent before the round starts, with no case
taken from an earlier benchmark (DESIGN §13.1 item 31). Requires mosaic with DESIGN §11
(in progress).

How to write one:
1. Pick 30 to 60 behaviors that are well known about the system: the ones its docs, talks and
   operators describe, and the failure modes people rely on (timeouts, refusals, retries,
   recovery). Cover every area, and every benchmark group in {{benchmark.groups}}.
2. Write each expectation from docs and common knowledge, before the build, so it is independent
   of the model. Be concrete: an outcome (a code, a status, a value), the path (which components,
   which messages, in which order), and the numbers (timeouts, thresholds, counts).
3. Mark each number and mode with the config key it depends on. The deployed config often differs
   from the docs' default.
4. State the default world ({{benchmark.default_world}}) once, at the top.
5. Expect to be wrong. In the Cassandra build, 20 of 44 expectations written this way were wrong
   or imprecise for the deployed version. That is why judges verify each one against the code
   before scoring, and why a wrong expectation is scored with cause `benchmark`, never against
   the model.
-->

# {{name}} benchmark: does the generated ontology map the system's workflows correctly?

The builders never see this file. It lists well-known behaviors of {{snapshot.repo}} at
{{snapshot.ref}}, each written so it can be run as a mosaic scenario against the merged ontology
(`{{workspace}}/{{id}}.json`).

**Verify each case against the code before scoring it.** The expectations below come from
documentation and common knowledge, and either can be wrong for {{snapshot.ref}} with the
deployed configuration ({{config.sources}}). A judge first confirms or corrects each expectation,
citing code (and, for the record, docs or tests). Only then is the ontology scored against the
corrected expectation.

**Default world:** fixtures {{benchmark.default_world}} (<describe: instances, seed data,
config>). A case that needs another world says so.

## Scoring per case

- **pass**: a scenario on the merged ontology reproduces the verified outcome, and the trace takes
  the code's path: the right components, instances, messages and decisions.
- **partial**: the outcome is right, but the path is wrong or incomplete. Or the behavior is
  modeled, but no scenario can drive it without editing the ontology.
- **fail**: the ontology produces a different outcome.
- **missing**: the behavior isn't modeled.
- **sim-gap**: the ontology models it as well as mosaic allows, but the simulator can't express
  it. Name the missing feature.

Write a scenario for each case under `judge/scenarios/<case>.yaml`. Use only fixtures, inputs,
`state`, `config`, `choices`, `faults` and `steps`; never edit the ontology, and never use mocks.

## <Group 1>

| ID | Behavior | Expected outcome | Depends on config |
|---|---|---|---|
| <G1> | <the action, the world, the injected condition> | <outcome code or value; the path; the numbers> | <config ids> |

<!-- Examples of well-formed cases from three kinds of system:
| W4 | Write at QUORUM; two replicas alive per the failure detector but silent | `write-timeout` after the write timeout (2000 ms); received 1 of 2; hints for the silent replicas | write-request-timeout-ms, hinted-handoff-enabled |
| E3 | Edit, then save, while a format-on-save provider is registered | the provider runs before the write; the saved text is formatted; one write to disk | editor-format-on-save, files-auto-save |
| V2 | A request arrives while `max_num_seqs` sequences are running | it waits in the scheduler queue until a sequence finishes; then prefill, then decode | max-num-seqs |
-->

## <Group 2>

| ID | Behavior | Expected outcome | Depends on config |
|---|---|---|---|
