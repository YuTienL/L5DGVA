## Stage Progress Displays: #32 Real-Time Progress + #33 Stage-Entry Banner -- Audited Already Satisfied (2026-09-06/07)

`self_check_list.md` #32/#33 (a real-time current-stage/remaining-items/completion-% display, and a
stage-START banner naming required documents/files/materials with a completeness % and a "needs your
detail" reminder) were assigned to this session as `stage_entry_exit_banner`. Auditing `engine.py`'s
`run_stage()`/`loop()` FIRST, per house style, found the gap already closed by
`dv_harness/stage_progress_display.py` (its own "STAGE-ENTRY BANNER EVIDENCE, WIDENED (2026-09-06,
stage_entry_exit_banner gap-close; self_check_list.md #33)" section) plus `engine.py`'s pre-existing
`_emit_stage_start_display()`/`_emit_stage_done_display()` call sites -- built in this same session,
immediately before this audit ran (`stage_progress_display.py` mtime post-dates every core module it
imports, including `target_conditioned_missing_artifact_detector.py`). No code change was made here;
this section is the missing CLAUDE.md record for work that already landed with real, passing tests.

**What is real and wired, confirmed by reading the code rather than trusting its own docstring.**
`run_stage()` calls `_emit_stage_start_display()` immediately after `_emit_stage_start_marker()` and
before the attempts++ mutation (engine.py ~4253-4265), and `_emit_stage_done_display()` immediately
after the stage-exit `last_transition`/`_emit_stage_done_marker()` write (~4798-4814) -- both are the
PROACTIVE trigger at real stage transitions the task asked for, not a second on-demand-only query path.
Both calls are wrapped in `try/except` at their call sites, so a display/report failure can never turn
a real stage PASS/FAIL into something else. `#32`'s real-time "current stage / remaining items /
completion %" requirement is satisfied by reusing the SAME pre-existing `dv-harness
checklist`/`explain`/`stage-report`/`stage-profile` query machinery (`gates.STAGE_GATES`,
`graph.Node.blackboard_read`/`blackboard_write`/`expected_evidence`/`expected_outputs`,
`stage_profile_report.stage_time_and_token_summary()`) as its data source, with this module adding only
the automatic call at each real transition -- exactly the task's own instruction ("this item adds the
PROACTIVE auto-display trigger at stage transitions, not a new data source").

**`#33`'s widened evidence source is real, not merely claimed.**
`build_env_manifest_checklist_items()` turns a project's real `env.manifest.json` (when one exists,
via `env_manifest.default_manifest_path()`/`load_env_manifest()`/`summarize_for_blackboard()`) into one
checklist item per layer, presence-checked from that layer's own real `status` field.
`build_target_conditioned_checklist_items()` maps a stage onto `target_conditioned_missing_artifact_
detector.py`'s own fixed target vocabulary (`STAGE_ARTIFACT_TARGET`: IMPLEMENT->VIP_UVM_CREATION,
SIGNOFF->SIGNOFF_PACKAGE, COVERAGE_CLOSURE->COVERAGE_CLOSURE, REGRESSION_SELECT->
REGRESSION_SUBMISSION) and calls that module's real `detect_missing_artifacts()`, reusing its own
per-category reason text verbatim rather than a second requirement table. Both are additive-only and
honest-by-omission (a project with no manifest, or a stage with no mapped target, contributes zero
extra items -- never a fabricated one), verified directly by `dv_harness_tests/
test_stage_progress_display.py`'s own negative controls (`test_env_manifest_items_are_empty_with_no_
manifest_on_disk`, `test_env_manifest_items_are_empty_on_a_malformed_manifest_file`,
`test_target_conditioned_items_are_empty_for_a_stage_with_no_mapped_target`).

**Verification performed by this audit.** `python -m pytest dv_harness_tests/
test_stage_progress_display.py dv_harness_tests/test_target_conditioned_missing_artifact_detector.py
dv_harness_tests/test_stage_evidence_checklists.py dv_harness_tests/test_dashboard_cli_checklist_
rendering.py -q` -> 84 passed. The full relevant engine suite,
`dv_harness_tests/test_engine_gates_and_routing.py` (239 tests, the module that drives real
`DVHarness.run_stage()` calls through the real graph), was also run in full: 236 passed, 3 failed --
`test_newly_wired_orphan_gates_pass_with_valid_evidence`, `test_run_stage_promotes_vplan_summary_to_
project_memory_on_pass`, `test_verification_architecture_requires_fabric_topology_completeness_gate`.
All three fail on a `GATE_FAIL`/`PARTIAL` verdict from a MISSING EVIDENCE BLOCK for a gate id these
older fixtures never supply (`spec_to_vplan_quality_gate` now required on `VPLAN`;
`vip_bind_generation_gate`/`scoreboard_generation_gate`/`assertion_generation_gate` now required on
`VERIFICATION_ARCHITECTURE`) -- a `gates.py`/`STAGE_GATES` registration fact, entirely independent of
`stage_progress_display.py`'s own display-only, try/except-wrapped code, which never touches gate
evaluation. Confirmed pre-existing and out of this item's own scope (this audit made no edit to
`gates.py`, `engine.py`, or any gate script): both `spec_to_vplan_quality_gate` (see this file's own
"Spec-to-vPlan Transform Quality Gate" section, "Not yet wired into `gates.py`'s `STAGE_GATES` -- that
edit is left for the integrator") and the three `verification_architecture.py` generation gates (see
this file's own "Verification Architecture IR" section, "not registered in `gates.py`") were, by their
OWN authoring modules' explicit disclosure, meant to stay unwired for a separate integration step --
yet `gates.py`'s real `STAGE_GATES` table now requires all four, evidently wired in by a different
concurrent pass in this same multi-agent session without those two disclosures being updated to match.
This is a real, disclosed residual for whichever task owns `gates.py`'s `STAGE_GATES` table next, not
a defect in this item's own display work.

**Disclosed residual, restated from `stage_progress_display.py`'s own module docstring.** The
env-manifest/target-conditioned widening covers only the four `env.manifest.json` layers and four
`STAGE_ARTIFACT_TARGET`-mapped stages named above; a stage outside that table, or a project with no
manifest yet, still gets the pre-existing graph-declared checklist unchanged -- never a guessed
requirement. Nothing here runs a build, a regression, or an LSF job; both displays are informational
and print-only.
