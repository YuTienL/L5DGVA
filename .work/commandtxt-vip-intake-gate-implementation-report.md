# command.txt / VIP-reference INTAKE gate implementation

## What was found

Per the earlier audit, `tools/vplan/intake_readiness.py` (wired into
`dv_harness/gates.py`'s `STAGE_GATES["INTAKE"]` as the `intake_readiness` gate)
validated `required_artifacts.protocol_spec`, `.dut_design_spec`,
`.rtl_top_or_interface_files`, `.clock_reset_spec`/`.phy_interface_spec`, and
(conditionally, by protocol) `.fabric_topology_spec`/`.uhs_tuning_spec` — but
never looked at `required_artifacts.command_txt` or
`required_artifacts.vip_reference` at all, even though:

- `.dv-harness/vplan/intake_request.schema.json` (the real, already-documented
  `required_artifacts` schema) already declares `command_txt: []` as one of
  its fields (list-of-file-reference shape, same as every other artifact key).
- `dv_harness/dashboard.py`'s real, wired file-upload UI
  (`_UPLOAD_CATEGORIES = ("spec", "rtl", "command_txt", "vip_reference",
  "de_sim")`) already collects real files for exactly these two categories,
  and its own comment states these are "the 5 real evidence categories
  CLAUDE.md/intake_readiness.py care about."
- `dv_harness/prompts.py`'s INTAKE stage text never told an agent it needed to
  supply either field, so an agent had no reason to include them even if the
  gate did check them.

So a SUBSYSTEM-mode intake could reach `READY_FOR_VPLAN` with zero
command.txt/VIP-reference evidence, or with a bare `"command_txt": true`
attestation naming no real file.

## What was built

**`tools/vplan/intake_readiness.py`** (the intake gate): added two new
required-artifact checks in the `SUBSYSTEM` branch, following the file's
existing `empty(k)`-based validation-style convention exactly:

- `command_txt` and `vip_reference` are now required in `required_artifacts`
  for SUBSYSTEM-mode intake, unconditionally (same tier as `protocol_spec`/
  `dut_design_spec`, not conditionally gated by protocol the way
  `fabric_topology_spec`/`uhs_tuning_spec` are) — outright absence appends the
  bare field name to `missing`, exactly like every other unconditional field
  already does.
- Because the schema calls for these two to be **real file paths** (not just
  a boolean attestation), a present-but-non-empty value additionally has to
  be *well-formed*: a string or list of strings, every entry non-empty, and
  every entry a path that actually exists on disk. `pathlib.Path(p).exists()`
  is called bare (no `--root` flag) because `gates.run_gate()` always invokes
  gate subprocesses with `cwd=str(root)` — the exact same bare-relative-path
  convention `focused_wave_debug_window_gate.py` already uses for its own
  on-disk policy-file check. A malformed/nonexistent-path value appends
  `command_txt_path_not_found` / `vip_reference_path_not_found` (distinct
  from outright absence) so the failure reason is diagnosable.
- SYSTEM_LEVEL-mode intake is untouched — see RULING 1 below.

**`dv_harness/gates.py`**: added the four new field-name → Traditional
Chinese human-question entries to `INTAKE_FIELD_QUESTIONS` (so a stalled
INTAKE surfaces an actual question instead of falling back to the generic
"缺少必要資訊：{f}"), and added `command_txt`/`vip_reference` to
`_PROTOCOL_TECHNICAL_INTAKE_FIELDS` so the existing per-protocol
`protocol_builder_registry.json` checklist escalation also applies to them,
consistent with the other "what material do you actually have" fields
already in that set.

**`dv_harness/prompts.py`**: updated the INTAKE stage instruction text's
`intake_readiness` evidence-block example to show `command_txt`/
`vip_reference` as arrays of real paths, and added a sentence stating both
are now mandatory for SUBSYSTEM mode, must be real on-disk paths (not `true`
or an invented path), and that the agent should widen its evidence search
before falling back to asking the user (per BASE's existing Interactive
Evidence Intake protocol).

## Rulings

- **RULING 1**: `command_txt`/`vip_reference` are enforced only for
  `mode == "SUBSYSTEM"`, not `SYSTEM_LEVEL`. A SYSTEM_LEVEL intake composes
  already-built subsystem environments, each of which already passed its own
  SUBSYSTEM-mode intake (with its own command.txt/VIP-reference evidence) —
  requiring it again independently at the composition level would be
  redundant, matching how the gate's SYSTEM_LEVEL branch already checks an
  entirely different field set (`selected_subsystems`,
  `system_level_use_cases`, `existing_uvm_env`).
- **RULING 2**: the required key is named `vip_reference` (not the
  `intake_request.schema.json` name `vip_docs_examples_source`). Both names
  exist in the repo, but `vip_reference` is the one with a real, wired
  consumer (`dashboard.py`'s `_UPLOAD_CATEGORIES`/`ufLabels`, whose own
  comment explicitly names it one of "the 5 real evidence categories
  CLAUDE.md/intake_readiness.py care about"); `command_txt` matches both the
  schema and the dashboard category exactly, so no naming decision was needed
  there.
- **RULING 3**: both fields are unconditionally required in SUBSYSTEM mode
  (not gated behind a protocol match, unlike `fabric_topology_spec`/
  `uhs_tuning_spec`). CLAUDE.md's "Five Source Discovery" step and
  `prompts.py`'s DISCOVERY/COMMAND_PATTERN text both already treat
  command.txt and Reference UVM/VIP material as foundational, same tier as
  Spec/RTL — so they get the same unconditional treatment as
  `protocol_spec`/`dut_design_spec`, not the narrower per-protocol treatment.
- **RULING 4**: accepted value shapes are a single path string or a list of
  path strings (matching the schema's list-of-references shape while staying
  ergonomic for a single-file case) — a bare boolean `true` is deliberately
  **not** accepted for these two fields (unlike the older boolean-only
  fields), because the entire point of this fix is that "evidence was
  supplied" must mean a real, checkable file reference, not an unverifiable
  attestation.
- Not attempted: syncing this change to the sibling `industrial`/`PACKAGE`
  deliverable trees that CLAUDE.md's Methodology Consolidation Rule calls
  for. Those are separate, non-git-tracked directories outside this task's
  stated repo root (`v50`) and were left untouched, consistent with the
  task's explicit scope; flagged here as a residual item for a follow-up
  sync pass (same shape as the `2026-08-31-protocol-generalization-gap-
  closing/task-7` sync already done for a different change set).

## Tests

Added to `dv_harness_tests/test_intake_readiness.py` (14 tests total in the
file now, 8 new): missing-both-fields, bare-`true`-not-accepted,
nonexistent-path-for-`command_txt`, nonexistent-path-for-`vip_reference`,
empty-string-entry-in-a-list, full happy path with real on-disk paths
(asserts `READY_FOR_VPLAN` and exit code 0), single-string-path (not just a
list) accepted, and SYSTEM_LEVEL-mode unaffected (RULING 1).

Updated `dv_harness_tests/test_engine_gates_and_routing.py`'s
`test_newly_wired_orphan_gates_pass_with_valid_evidence` INTAKE case to add
`command_txt`/`vip_reference` (real, existing repo-relative paths —
`CLAUDE.md`, `dv_harness/gates.py`) to its previously-PASSing payload; without
this the test would have newly failed as an expected consequence of the new
mandatory checks, not a bug in the fix.

## Test results

- `dv_harness_tests/test_intake_readiness.py`: 14/14 passed.
- `dv_harness_tests/test_engine_gates_and_routing.py -k "intake or newly_wired_orphan or needs_user_input or project"`: 14/14 passed.
- Full suite (`python -m pytest dv_harness_tests -q`): **1432 passed, 1 failed**
  in 790s. The one failure,
  `test_graph_parallel_dispatch.py::test_engine_dispatches_all_three_branches_concurrently_and_joins`,
  is an unrelated, pre-existing timing-sensitive concurrency assertion
  (`assert state["peak"] >= 2` — a real-thread-pool `time.sleep(0.25)` race
  that needs two branches genuinely overlapping under system load) in a file
  this change never touches. Re-run in isolation immediately after the full
  run: `1 passed in 1.94s` — confirms it is a flaky, load-sensitive test, not
  a regression from this work (the intake-gate change touches only INTAKE
  evidence validation, nothing in the graph/thread-pool dispatch path this
  test exercises).

## Concerns / residual gaps

- The `industrial`/`PACKAGE` deliverable-tree sync called for by CLAUDE.md's
  Methodology Consolidation Rule was not performed (see RULING above) —
  those trees will be out of sync with this change until a dedicated sync
  pass runs.
- `command_txt`/`vip_reference` being unconditionally required in SUBSYSTEM
  mode means a genuinely greenfield protocol with zero pre-existing
  command.txt/VIP material (the `COMMAND_PATTERN` stage's "GENERATE"
  classification exists for exactly this case) has no built-in waiver path
  at INTAKE time — this mirrors the pre-existing behavior of
  `protocol_spec`/`dut_design_spec` (also unconditionally required with no
  waiver escape hatch), so it is not a new gap this change introduces, but it
  is worth flagging if a real greenfield-protocol project hits it.
