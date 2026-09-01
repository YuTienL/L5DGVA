# DE-Local Simulation Environment Intake — Implementation Report

## Gap addressed

An earlier audit this session found that DE-local-simulation-environment
intake — the local Design-Engineer simulation environment (compile script,
run script, filelist, environment-setup script) a project may already have
before the harness gets involved — had **zero schema or code backing**
anywhere in the codebase. `DE_BASELINE_REPRODUCTION`'s existing
`de_baseline_reproduction_gate.py` validates hashes proving a baseline was
*reproduced* identically, but nothing ever validated that the four
underlying DE-local artifacts (compile/run/filelist/env-setup scripts) were
real, on-disk, non-empty files confirmed to exist/work in the first place.
This closes that specific gap, additively, at the `INTAKE` stage.

## What was built

1. **Evidence schema**, documented in `dv_harness/prompts.py`'s `INTAKE`
   stage instructions (both the technical `STAGE_INSTRUCTIONS[Stage.INTAKE]`
   block and a one-line addition to the plain-language
   `STAGE_DE_EXPLAINER[Stage.INTAKE]` companion block): a
   `de_local_sim_env_intake_gate` evidence object with exactly four fields —
   `compile_script_path`, `run_script_path`, `filelist_path`,
   `env_setup_script_path` — each an object `{"path": "<real file path>",
   "evidence": "<how it was confirmed to exist/work>"}`. This mirrors the
   existing per-item `"evidence"` note convention already used elsewhere in
   the repo (`experience_knowledge_gate.py`,
   `protocol_builder_registry_conformance_gate.py`, etc.) and the mandatory
   non-empty `"evidence"` string field convention from
   `dv_harness/uvm_generator/generator.py`'s house DSL style.

2. **Gate script**: `tools/verification_flow/de_local_sim_env_intake_gate.py`
   — same argparse + JSON-evidence-file + print-json-verdict convention as
   every other real gate script (`server_sync_identity_gate.py`,
   `de_baseline_reproduction_gate.py`, `generated_artifact_boundary_gate.py`
   were read first for exact house style). It validates each supplied path
   exists on disk as a non-empty file, with a typed FAIL `reason` per
   missing/invalid field (e.g. `COMPILE_SCRIPT_PATH_PATH_NOT_FOUND`,
   `RUN_SCRIPT_PATH_EVIDENCE_MISSING`, `FILELIST_PATH_PATH_FILE_EMPTY`,
   `ENV_SETUP_SCRIPT_PATH_PATH_NOT_A_FILE`), and a distinct exit code per
   FAIL *kind* (2–7), matching `server_sync_identity_gate.py`'s convention
   of distinct exit codes per distinct reason.

3. **Wiring**: added
   `("de_local_sim_env_intake_gate", "de_local_sim_env_intake_gate.py",
   "--intake")` to `dv_harness/gates.py`'s `STAGE_GATES["INTAKE"]` list,
   additively (the three pre-existing INTAKE gates — `intake_readiness`,
   `generated_artifact_boundary_gate`, `interactive_evidence_intake_gate` —
   are untouched). Also registered the new gate in
   `.dv-harness/workflow/hard_gate_registry.json` and
   `.dv-harness/workflow/verification_flow_v13.json` (both are checked for
   mutual consistency by `gate_manifest_registry_consistency_gate.py`, which
   now still PASSes against this real repo) and added it to
   `dv_harness_tests/test_hard_gate_script_smoke.py`'s
   `ALL_GATE_TOOL_FILES` drift-guard list.

## Rulings made

- **RULING (optionality mechanism)**: `dv_harness/gates.py`'s evidence
  engine (`_evaluate_stage_evidence_core`) treats a gate whose fenced
  ` ```dv-harness-evidence:<gate_id>``` ` block is entirely missing from the
  agent's reply as an unconditional per-gate failure ("no evidence block
  supplied") — there is no existing per-gate "skip this one if genuinely not
  applicable" switch, and adding one would be a much larger, cross-cutting
  change to every stage's gate list rather than a minimal, additive fix
  scoped to this one gap. To keep the gate genuinely OPTIONAL/non-blocking
  without that engine surgery, `prompts.py` instructs the agent to *always*
  emit the fenced block, using an **empty JSON object `{}`** when no
  pre-existing DE-local environment exists. The gate script itself is what
  makes that concession safe: a payload that is not a dict, or that carries
  none of the four required fields (all falsy/absent), PASSes as a no-op
  (`{"status": "PASS", "de_local_sim_env": "NOT_APPLICABLE"}`) with zero
  field enforcement. The task's phrase "the evidence block is entirely
  absent" is interpreted at the JSON-content level (no fields populated),
  not at the markdown-fence level (which the engine already refuses to
  no-op on for any gate, by design, elsewhere in the codebase) — this is
  the smallest change consistent with both the task's optionality
  requirement and the existing engine contract.

- **RULING (all-or-nothing field enforcement)**: once *any* of the four
  fields is populated, the block is considered "present" and all four
  fields become required and are each checked in full (real file, non-empty,
  non-empty `evidence` note). Partial evidence is never treated as if the
  whole block were absent — this prevents an agent from supplying one
  cherry-picked field to dodge the other three's real checks.

- **RULING (nested per-field object shape)**: chose
  `{"path": ..., "evidence": ...}` per field rather than flat
  `"compile_script_path"` + `"compile_script_path_evidence"` sibling keys,
  because the former matches this repo's existing per-item
  `{"key"/"...", "evidence": ...}` object convention (seen in
  `experience_knowledge_gate.py`, `protocol_builder_registry_conformance_gate.py`,
  `promotion_chain_audit_gate.py`) more closely than a flat sibling-key
  scheme would.

## Pre-existing test fixtures updated (regression prevention)

Because the new gate is additive to `STAGE_GATES["INTAKE"]`, every existing
test that constructs a full/PASS-path or NEEDS_USER_INPUT-path `INTAKE`
evidence text in `dv_harness_tests/test_engine_gates_and_routing.py` needed
its own `de_local_sim_env_intake_gate` fence (using the documented `{}`
no-op) added, or those tests would have regressed from PASS/NEEDS_USER_INPUT
to GATE_FAIL purely because of the new gate's presence:
- `_INTAKE_EXTRA_GATES` (shared constant)
- `_intake_needs_input_text()` (shared helper)
- `test_evaluate_stage_evidence_returns_needs_user_input_for_intake_gate_miss`
- `test_run_stage_maps_needs_user_input_to_wait_user_status` (also needed the
  new gate script copied into its temp sandboxed root, alongside the other
  two INTAKE gate scripts it already copies)

These are test-fixture updates only — no test's assertions/expectations were
weakened, only the fixed evidence text they feed in was extended with the
documented no-op block for the newly-additive gate.

## Tests added

`dv_harness_tests/test_de_local_sim_env_intake_gate.py` — 17 tests covering:
- no-op PASS for `{}`, a non-dict payload, and an all-falsy-fields payload;
- full valid block PASS;
- partial block (one field deleted, or one field not a dict) → typed
  `..._FIELD_MISSING` FAIL;
- each per-field validation kind: missing `path`, blank `path`, missing
  `evidence`, blank `evidence`, nonexistent path, directory-instead-of-file,
  empty file — each asserting its exact typed reason string and exit code;
- deterministic first-failing-field ordering;
- wiring: the gate id is present in `dv_harness.gates.STAGE_GATES["INTAKE"]`
  alongside the three pre-existing gates (still present, unbroken);
- end-to-end `evaluate_stage_evidence()` checks: a full INTAKE evidence set
  with the new gate's `{}` no-op block still yields `PASS`, and a broken
  `de_local_sim_env_intake_gate` field genuinely causes `GATE_FAIL`.

## Test results

- `dv_harness_tests/test_de_local_sim_env_intake_gate.py`: **17 passed**.
- `dv_harness_tests/test_engine_gates_and_routing.py` (full file, includes
  all pre-existing INTAKE-stage and general gate-routing tests): **188
  passed**, zero regressions after the fixture updates above.
- `dv_harness_tests/test_hard_gate_script_smoke.py` (full file, drift-guard
  + `--help` smoke test for every registered gate script): **177 passed**
  (176 pre-existing + 1 new), confirming the registry/flow-manifest/
  smoke-list additions are internally consistent.
- Full `dv_harness_tests` suite run for final regression confirmation; see
  the `tests_summary` field in the structured result for the final count.
- `tools/verification_flow/gate_manifest_registry_consistency_gate.py --root .`
  run directly against this real repo: **PASS** (`registry_gates: 176`) —
  confirmed both before (would have reported `REGISTRY_NOT_IN_FLOW` for the
  new gate) and after adding the `verification_flow_v13.json` entry.

## Concerns / residual gaps

- The optionality mechanism (RULING above) depends on the agent actually
  following the `prompts.py` instruction to emit `{}` when not applicable.
  If an agent implementation ever omits the `INTAKE` stage prompt text (or a
  future prompt refactor drops this instruction), the gate reverts to
  behaving like a mandatory gate at the engine level (missing block →
  `GATE_FAIL`) rather than a true no-op. This is an inherent limitation of
  the current `_evaluate_stage_evidence_core` design (shared by every other
  "technically optional" gate that must presently be represented as
  always-emitted-but-content-optional), not something newly introduced by
  this change — flagged here rather than silently accepted.
- No RTL/tool-specific validation of the *content* of the four scripts (e.g.
  that `compile_script_path` actually invokes VCS, or that `filelist_path`
  is well-formed `-f` syntax) was implemented — the task scope was
  existence/non-emptiness plus an `evidence` attestation, not semantic
  validation of script content, and no real sample DE-local compile/run
  script format was available in this repo to validate against without
  guessing (Evidence Truth Rule / No Golden-Reference Content Mining) — the
  gate deliberately stops at the file-existence/evidence-note level the
  task specified.
