# M6 Final Operational Slice Qualification -- Path Proof

Every claim below cites a real, named, re-run test against the frozen
candidate `M6_QUALIFICATION_CANDIDATE_SHA = 2bd986f5e05fb5ee0c01d1c5c29d41a44c5b859f`.
See `M6_FINAL_OPERATIONAL_SLICE_QUALIFICATION_MATRIX.csv` for the full
per-stage matrix this document narrates.

## 6. Auto-resolved happy path

```
AUTO_DISCOVERY_FIRST = PASS
REDUNDANT_HUMAN_QUESTION = 0
```

`test_ip_level_with_task_boundary_pass` / `test_subsystem_level_with_
task_boundary_pass` / `test_system_level_with_task_boundary_pass`
(`test_m6_task_boundary_production_001.py`): protocol/role/level all
DECLARED, a real Task Boundary also declared and held, generation
succeeds. `assert QuestionQueueStore(root).list_questions() == []` (or
equivalent) confirms zero questions filed anywhere in the chain --
Intake -> Field Resolution -> no redundant question -> EffectiveValue ->
Dispatch -> Task Boundary PASS -> VerificationLevel -> correct generation
branch, all in one real `start_lifecycle()` call.

## 7. Clarification / HITL path

`test_human_answers_unblock_generation_and_are_persisted_as_lifecycle_
facts` (`test_m6_c1_golden_path_connectivity.py`): an unresolved
`generation_request` call files 3 real questions (protocol/role/
verification_level); `QuestionQueueStore.answer_question()` -- the REAL
human-answer API, never a direct `EffectiveValue` edit -- answers all 3; a
SECOND `start_lifecycle()` call re-enters Field Resolution WITH those
answers, resolves silently, and generation succeeds. The resolved facts
are independently re-read from `LifecycleStore(root).load()` (real
on-disk state, not the in-memory return value) and asserted equal to the
human's own answers.

## 8/9/10. DE / DV / SHARED authority paths

See `M6_FINAL_HITL_QUALIFICATION.md` for the full analysis. Summary:
DV/VERIFICATION -- real, M6-production-qualified. DE/DESIGN and SHARED
(positive case) -- real, MECHANISM-qualified via `resolve_or_ask()`
directly, but `NOT_APPLICABLE_WITH_EVIDENCE` to M6's own current 3-field
generation scope (no `domain="dut"` FieldControl exists there). SHARED
negative case ("an ordinary unknown is not automatically SHARED") --
real and tested regardless of M6-scope applicability
(`test_an_ordinary_unknown_dut_field_is_not_automatically_shared`).

## 11/12. Task Boundary PASS / FAIL

PASS: `test_ip_level_with_task_boundary_pass` /
`test_subsystem_level_with_task_boundary_pass` /
`test_system_level_with_task_boundary_pass`. FAIL:
`test_ip_level_with_task_boundary_fail_blocks_generation` /
`test_subsystem_level_with_task_boundary_fail_blocks_generation` /
`test_system_level_with_task_boundary_fail_blocks_generation` -- each
asserts `r.raw["blocked_by"] == "task_boundary"`, `not out_dir.exists()`,
and (for the generic case) `h.adapter.calls == 0`: VerificationLevel does
not silently route, generation does not proceed, and the
`TASK_BOUNDARY_BLOCKED` event/`findings` are retained.

## 13/14/15. IP / SUBSYSTEM / SYSTEM_LEVEL paths, real output consumption

- **IP**: `test_ip_level_full_production_path`
  (`test_m5m6_vlevel_001_production_connectivity.py`) -- real
  `(out_dir / "environment_manifest.json").exists()`,
  `r.raw["environment_mode"] == "IP_MODE"`;
  `test_ip_level_never_touches_the_subsystem_registry` -- confirms
  IP_MODE's own "no subsystem registry involved" semantics for real.
- **SUBSYSTEM**: `test_subsystem_level_full_production_path` -- same
  real-file assertion, `environment_mode == "SUBSYSTEM_MODE"`.
- **SYSTEM_LEVEL**: `test_system_level_full_production_path` -- real
  registered USB+PCIe subsystems (via `engine.py`'s own real
  `_persist_subsystem_registry_entry()` writer, never a hand-authored
  registry file), real composed `soc_tb_top.sv` content
  (`"usb_env usb_env_inst;"`, `"pcie_env pcie_env_inst;"`), and
  `test_system_level_needs_two_or_more_subsystems_even_when_declared` for
  the real arity-requirement failure path.

Per this task's own explicit instruction (section 15): GAP-V2-006
(SYSTEM_LEVEL_MODE still needing `protocol`/`role`) is NOT pulled forward
as new work here -- no qualification evidence this pass demonstrated it
is a current correctness defect (the composition still succeeds when
supplied, per `test_system_level_composition_still_requires_generic_
protocol_role_fields_to_resolve`'s own passing assertion).

## 16. Entry-point coverage

- **CLI**: `test_cli_task_boundary_flags_propagate_a_real_taskboundary_
  into_start_lifecycle`, `test_cli_start_generate_propagates_protocol_
  role_and_manifest_into_start_lifecycle`.
- **Dashboard**: `test_dashboard_task_boundary_pass_reaches_generation`,
  `test_dashboard_start_background_run_propagates_generation_fields`.
- **Protocol Builder**: `test_protocol_builder_invocation_shape_reaches_
  task_boundary_and_generation` (the exact CLI shape all 11 skills use,
  per GAP-V2-002) PLUS the AST-based `test_gap_v2_002_protocol_builder_
  convergence.py` re-confirming all 11 skills converge and
  `DIRECT_UNGOVERNED_PROTOCOL_BUILDER_CALLERS = 0`, re-run fresh this
  task (not assumed unchanged).

```
PROTOCOL_BUILDERS_GOVERNED = 11/11
DIRECT_UNGOVERNED_PROTOCOL_BUILDER_CALLERS = 0
```

## 21. Bypass qualification

| Path | Classification |
|---|---|
| `start --advanced` | AUTHORIZED_LOW_LEVEL_BYPASS -- a declared `TaskBoundary`/`generation_request` is ignored under it, recorded as a real `LIFECYCLE_BYPASS` event, never masquerading as qualified normal execution (`test_advanced_bypass_also_skips_a_declared_task_boundary`) |
| `tools/generate_protocol_uvm_environment.py` direct call | INTERNAL_GENERATION_PRIMITIVE -- already-authorized (GAP-V2-002, `DEC-GAP-V2-002=OPTION_B`), re-confirmed unchanged this pass |
| Test-only direct calls to `task_boundary_conformance.*`/`clarification_service.*` | TEST_ONLY |

```
UNCONTROLLED_BYPASSES = 0
```
