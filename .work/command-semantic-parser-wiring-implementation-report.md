# command_semantic_expectation_parser.py wiring (2026-09-01)

## What was found

`tools/verification_flow/command_semantic_expectation_parser.py` is a real, correct,
deterministic command.txt-intent extractor: given a `command.txt`, `parse_line()`
regex-derives per-line protocol/operation/attribute/outcome `evidence_requirements`
and `contradiction_requirements` in exactly the schema
`simulation_semantic_validation_gate.py` already consumes
(`expectation_id`, `source_file`, `source_line`, `testcase_id`, `vplan_ids`,
`required`, `evidence_requirements`, `contradiction_requirements`, plus the
legacy `evidence_patterns`/`contradiction_patterns` arrays). It was genuinely
orphaned: the only place it is referenced anywhere in the repo is the
non-executed documentation registry
`.dv-harness/workflow/verification_flow_v13.json` (a `simulation_pass_semantics.order`
list describing an aspirational pipeline shape) and one self-audit
meta-consistency gate that scans that same JSON for schema-catalog drift.
Nothing in the live `STAGE_GATES` chain (`dv_harness/gates.py`) ever imported
or subprocess-invoked it.

## Investigating the live chain (read in full before making any change)

`simulation_semantic_validation_gate.py` (VERIFY stage, `--input`) is the real,
working TRUE_PASS semantic-verdict engine: it matches an agent-supplied list of
`command_expectations` (each with `evidence_requirements`/
`contradiction_requirements`) against real sim.log content (read from a real
file via `sim_log_path`, per its own existing anti-spoofing docstring), and
`simulation_semantic_trace_gate.py` (`--result`) re-validates that gate's own
output for MATCH-only status, source-line provenance and evidence-source
provenance before allowing signoff credit.

Critically, **`command_expectations` itself was pure agent-attested JSON** in
both gates -- nothing anywhere in the live chain independently re-derived what
a real `command.txt` line actually requires. The one other VERIFY-stage gate
that sounds related, `command_intent_semantic_closure_gate.py`, does not close
this gap either: it only compares two agent-self-reported strings
(`expected_semantics` vs `observed_semantics`) to each other, never to a real
parse of the file. So the premise for option (b) in the task -- "the two gates
already re-derive the same information some other real way" -- is false; I
verified this by reading both gate scripts in full and grepping the whole
VERIFY stage's gate list for any other command.txt-parsing code, and found
none.

**RULING**: per the task's own decision procedure, since the live gates do
*not* already re-derive command.txt intent, this is option (a): wire the real
parser directly into `simulation_semantic_validation_gate.py` as part of
computing its own semantic verdict, rather than adding a separate new gate
that would have to ask the agent to re-supply the same `command_expectations`
a second time in an isolated evidence block (each gate script in this harness
runs as its own subprocess with only its own fenced evidence block -- there is
no cross-gate payload sharing in `run_gate()`/`evaluate_stage_evidence()` to
build a "new gate cross-checking gate A's evidence" on top of without that
duplication).

## What was built

`simulation_semantic_validation_gate.py` gained:

- `load_command_semantic_expectation_parser()` -- loads the sibling
  `command_semantic_expectation_parser.py` by file path (`importlib.util`,
  not a package import -- these gate scripts are standalone files with no
  `__init__.py`, each invoked individually via subprocess) and calls its real
  `parse_line()` in-process.
- `cross_check_against_command_file(command_file_path, exps)` -- reads the
  real file at `command_file_path` from disk, re-derives each line's minimum
  `evidence_requirements`/`contradiction_requirements` via the real parser,
  and verifies the agent-supplied `command_expectations` (matched by
  `source_line`) covers at least that minimum pattern/match_mode set. The
  agent may supply *more* than the deterministic baseline (the parser is a
  necessary-minimum extractor, not exhaustive -- e.g. it has no idea about
  protocol-specific timing/sequencing intent a human authored into the
  command), but may not supply *less*. A command.txt line the parser derives
  real requirements for, with no agent-supplied entry mapped to that
  `source_line` at all, is flagged exactly like an entry that omits
  individual patterns -- omission-by-absence is not a loophole.
- A new **optional** `command_file_path` evidence field, read in `main()`
  right after the existing duplicate/missing-`expectation_id` check. When
  present, a real-file-read failure fails closed with
  `INSUFFICIENT_EVIDENCE`/`COMMAND_FILE_PATH_NOT_FOUND` (or `_UNREADABLE`),
  and an under-reporting agent fails closed with a new
  `final_state: "COMMAND_TXT_INTENT_UNDER_REPORTED"` carrying a structured
  `under_reported` list (`source_line`, `raw_command`,
  `missing_evidence_requirements`, `missing_contradiction_requirements`).
  **When the field is absent, behavior is byte-for-byte identical to before
  this change** -- the additive/backward-compatible convention this project's
  CLAUDE.md and `generator.py` already establish. No change was needed to
  `dv_harness/gates.py`'s `STAGE_GATES` (the script's CLI contract, `--input`,
  is unchanged; it was already wired into the `VERIFY` stage).

`command_semantic_expectation_parser.py` itself was not modified -- it was
already correct; the fix was purely wiring it into the live invocation path.

## Tests

New file `dv_harness_tests/test_command_semantic_expectation_parser_wiring.py`
(13 tests), covering:

- The previously-untested parser itself (`parse_line` extraction correctness
  for protocol/operation/attribute/outcome/contradiction, and blank/comment
  line handling) -- it had zero test coverage before this task despite being
  "real and correct" per the prior audit.
- `cross_check_against_command_file()` directly: full-coverage PASS, a
  dropped OPERATION pattern, a dropped CONTRADICTION pattern, a source_line
  with no agent entry at all, and a missing/bad `command_file_path`.
- The gate script's `main()` end-to-end via subprocess (matching this
  project's existing gate-script test convention): PASS with a real
  command.txt, `FAIL COMMAND_TXT_INTENT_UNDER_REPORTED` (exit 9) on an
  under-reporting payload, `FAIL COMMAND_FILE_PATH_NOT_FOUND` (exit 8) on a
  bad path, and the backward-compatibility guarantee (omitting
  `command_file_path` reproduces the exact pre-fix PASS behavior even with a
  weak `command_expectations` block that would fail the cross-check).
- One live-chain integration test through
  `dv_harness.gates.evaluate_stage_evidence(ROOT, "VERIFY", text)`, reusing
  the existing `_VERIFY_EXTRA_GATES` fixture from
  `test_engine_gates_and_routing.py` for every other mandatory VERIFY gate,
  proving the fix reaches real production traffic through the actual
  `STAGE_GATES`/`run_gate()` path (not just the script in isolation).

Full existing suite run: `python -m pytest dv_harness_tests/ -q`.
Result: **1425 passed, 0 failed** in 780.24s -- zero regressions from this
change (this count includes the 13 new tests in
`test_command_semantic_expectation_parser_wiring.py`). A targeted rerun of
`dv_harness_tests/test_engine_gates_and_routing.py` (the file most directly
exercising `dv_harness/gates.py`'s live `STAGE_GATES` chain, including the
pre-existing `simulation_semantic_validation_gate` tests such as
`test_verify_stage_with_matching_evidence_passes`,
`test_simulation_gate_reads_sim_log_from_real_file_path`,
`test_simulation_gate_fails_closed_on_missing_sim_log_path`, and
`test_verify_stage_with_mismatched_log_fails_not_passes`) also passed clean
(188 passed). `test_gate_script_argparse_smoke` (parametrized over every
registered gate, `--help` exit-0 smoke check) confirms the modified script's
CLI contract is untouched.

## Residual gaps / concerns

- `command_file_path`, like the pre-existing `sim_log_path`, is agent-supplied
  text pointing at a real file -- reading it from disk closes the "arbitrary
  pasted text" gap but does not itself prove the file is genuinely *this run's*
  `command.txt` (vs. a stale or unrelated one at a plausible path). Fully
  closing that needs cross-referencing against a harness-tracked run identity
  (same caveat `load_sim_log()`'s own docstring already documents for
  `sim_log_path`, and the same class of gap `run_identity_consistency_gate`
  addresses at the REGRESSION_MONITOR stage for build/config identity) --
  out of scope for this task.
- `command_file_path` is optional, not mandatory. Making it mandatory would
  immediately break every existing caller/test that never supplies a
  command.txt path (there is no migration path for that today, mirroring the
  same opt-in reasoning already documented in `gates.py` for the Tier-5
  DV-review co-sign mechanism). Flipping it to mandatory is a follow-up that
  needs a `prompts.py` VERIFY-stage instruction update telling agents to
  always supply it, done deliberately rather than silently.
- The deterministic parser is a heuristic regex extractor (a fixed
  `PROTOCOLS`/`OPS` vocabulary); a command.txt line using vocabulary outside
  those lists derives an empty `evidence_requirements`/`contradiction_requirements`
  set and is silently skipped by the cross-check (nothing to enforce). This
  is unchanged parser behavior, not a regression introduced here, but it
  means the cross-check's coverage is only as good as that vocabulary.
