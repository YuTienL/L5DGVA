# M6 Operational Vertical Slice — Status After CAP-M6-CLARSVC-001

Recalculated fresh (not inflated merely because a module now exists). Same
rule as `M6_OPERATIONAL_VERTICAL_SLICE.md`'s own definition: **a stage is
connected only when its output is genuinely consumed by the next required
stage in the real runtime path** — verified per-transition by a real,
passing test, not asserted.

```
M6_VERTICAL_SLICE_CONNECTED_STAGES_BEFORE = 6
M6_VERTICAL_SLICE_CONNECTED_STAGES_AFTER  = 8
```

## Stage-by-stage, updated

| # | Stage | Before (DISPATCH-001) | After (CLARSVC-001) | Real evidence |
|---|---|---|---|---|
| 1 | Intake | Connected (lifecycle CREATE/ADOPT/RESUME) | Connected (unchanged) | `test_start_lifecycle_creates_a_real_lifecycle_and_dispatches` |
| 2 | Field Resolution | Connected (called, but with no QuestionOwner attached) | Connected, now via `clarification_service.resolve_or_ask()` | `test_no_question_when_automatically_resolved` |
| 3 | Clarification hand-off | Connected (unresolved -> `file_clarification()`) | Connected, now carrying a real `authority_role` | `test_unresolved_required_field_files_a_real_question` |
| 4 | **QuestionOwner** | `ROADMAP_DEFINED`, not built | **Newly connected** — `classify_question_owner()` real, evidence-based (domain + conflict signal), persisted onto the real question record | `test_de_question_owner_is_design_for_a_dut_domain_field`, `test_dv_question_owner_is_verification_for_env_and_vip_domain_fields`, `test_shared_question_owner_only_for_a_genuine_dut_conflict` |
| 5 | **HumanGate** | `ROADMAP_DEFINED`, not built | **Newly connected, with one disclosed nuance** — the real gating mechanism (block dispatch until `question_queue.py`'s own `answer` is non-null) is genuinely wired and tested; the named `human_gate_state()` projection helper itself has 0 production callers today (disclosed, not hidden — see `M6_CLARSVC_001_CALLER_SWEEP.csv`) | `test_dispatch_blocks_on_unresolved_field_and_resumes_after_answer`, `test_human_gate_state_projects_real_question_queue_status` |
| 6 | EffectiveValue | Connected | Connected — now also reachable via the real Answer -> Field Resolution loop, not only the first-pass resolution | `test_answer_round_trip_feeds_back_through_field_resolution` |
| 7 | Dispatch | Connected (gated by `_intake_first_guard()`) | Connected (unchanged; still gates on the same real mechanism) | `test_intake_first_guard_blocks_a_post_intake_stage_before_intake_ready` |
| 8 | Task Boundary | Connected | Connected (unchanged) | `test_task_boundary_violation_blocks_dispatch` |
| 9 | VerificationLevel | `ABSENT` | `ABSENT` (unchanged — explicitly out of this capability's scope, item 18) | n/a |
| 10 | IP / SUBSYSTEM / SYSTEM_LEVEL | Separate, `OPERATIONAL` for 2/3 modes | Unchanged — still a separate, unconnected mechanism | n/a |

## What genuinely changed

Two stages (`QuestionOwner`, `HumanGate`) moved from `ROADMAP_DEFINED` to
real, connected, tested mechanism this capability. The remaining 2 stages
(`VerificationLevel`, `IP/SUBSYSTEM/SYSTEM_LEVEL`) are unchanged and remain
correctly out of this capability's own scope (items 18/19 of
`DEC-M6-DISPATCH-001`'s sibling approval; `CAP-M5M6-VLEVEL-001` is
explicitly the next, separately-dispatched gate).

## What did NOT get inflated

- `human_gate_state()`'s own 0-caller status is disclosed, not silently
  omitted — the stage is counted CONNECTED because the underlying real gate
  mechanism (question `status`/`answer`) already blocks/resumes dispatch
  correctly, not because a module with that name merely exists.
- `intake_state.py` is NOT counted as a newly-connected stage anywhere —
  it remains its own, separate, unmodified UVM_GENERATION_READY mechanism
  (see `M6_CLARSVC_001_QUESTION_QUEUE_NWAY_ANALYSIS.md`'s own disposition).
- `VerificationLevel`/`IP_MODE` are NOT claimed connected merely because
  `level`/`protocols` are accepted parameters on `start_lifecycle()` — they
  are stored, never interpreted, exactly as `CAP-M6-DISPATCH-001`'s own
  implementation report already disclosed.

## Update after `CAP-M6-C1-001` (M6 Golden-Path Connectivity Closure C1)

`M6_VERTICAL_SLICE_CONNECTED_STAGES` (the STRUCTURAL metric above, "a real
test proves the mechanism works when given a field control") is
**unchanged at 8** — C1 added no new structurally-connected stage; it
closed a different, distinct gap the Integration Prime Directive adoption
audit named: whether any REAL production caller (not only a test calling
the Python API directly) ever actually supplies that field control.

```
M6_VERTICAL_SLICE_CONNECTED_STAGES = 8   (unchanged, structural)
M6_PRODUCTION_CONNECTED_STAGES     = 8   (new this wave -- NOT the same 8 stages)
```

`M6_PRODUCTION_CONNECTED_STAGES` counts stages reachable starting from a
real CLI argv (`dv-harness start --protocols ... --generate --generate-out
...`) or a real dashboard HTTP `/api/start` JSON body — never a test
calling `start_lifecycle()` directly in Python. The stage SET differs from
the structural one, deliberately:

| # | Stage | Structural (8) | Production (8) | Why |
|---|---|---|---|---|
| 1 | Intake | Yes | Yes | Both: CLI/dashboard always create/resume a lifecycle |
| 2 | Field Resolution | Yes | **Yes (new)** | `--protocols`/`--generate` now really reach `resolve_or_ask()` |
| 3 | Clarification hand-off | Yes | **Yes (new)** | same real path, when unresolved |
| 4 | QuestionOwner | Yes | **Yes (new)** | `classify_question_owner()` runs unconditionally inside the same call |
| 5 | HumanGate | Yes | **Yes (new)** | blocks/resumes exactly as tested via real CLI/dashboard round-trips |
| 6 | EffectiveValue | Yes | **Yes (new)** | resolved value persisted as a real lifecycle fact |
| 7 | Dispatch | Yes | **Yes (new)** | `start_lifecycle()`'s own dispatch decision now genuinely reachable from CLI/dashboard input, not only a direct Python call |
| 8 | Task Boundary | Yes | **No** | no CLI flag or dashboard JSON field supplies a `TaskBoundary` today (pre-existing gap, unchanged by C1) — still test-only |
| 9 | VerificationLevel | No (ABSENT) | No (ABSENT) | unchanged, explicit seam per item 11 |
| 10 | IP/SUBSYSTEM/SYSTEM_LEVEL | No ("separate, unconnected") | **Yes (new)** | `create_environment()`'s own internal mode resolution is now reached from the same governed, production-triggered call |

Real evidence: `dv_harness_tests/test_m6_c1_golden_path_connectivity.py`
(13/13) — `test_cli_start_generate_propagates_protocol_and_manifest_into_
start_lifecycle` (CLI argv -> `start_lifecycle()` kwargs, asserted
directly) and `test_dashboard_start_background_run_propagates_generation_
fields` (dashboard HTTP-payload-shaped call -> a real filed/persisted
outcome) are the two production-entry-point proofs; the remaining 11
tests confirm each stage's own real behavior along that path.

`CLARIFICATION_CAPABILITY_ISLAND` reassessment (dispatch section 13):
`NO` for this specific edge (protocol field, CLI/dashboard entry points).
Two real, disclosed, NOT-closed islands remain: (1)
`tools/generate_protocol_uvm_environment.py`'s own direct,
ungoverned call to `create_environment()` (out of C1's own named scope);
(2) any field OTHER than `protocol` still has zero production producer —
this closure is deliberately narrow (one field), not a general claim that
Field Resolution is now production-connected for every possible intake
fact.

## Update after `GAP-V2-002` remediation (`CAP-M6-GAPV2002-001`)

Island (1) above is now CLOSED. `DEC-GAP-V2-002 = OPTION_B` (approved):
`tools/generate_protocol_uvm_environment.py` reclassified
`INTERNAL_GENERATION_PRIMITIVE`; all 11 `.claude/skills/PROTOCOL_BUILDERS/
*/SKILL.md` now converge on `start_lifecycle(generation_request=...)`,
the same governed path CLI/dashboard already use. A second real,
generic field, `role`, was added alongside `protocol` (derived from all
11 skills' own discovery lists + real downstream consumer evidence, never
assumed -- `GAP_V2_002_FIELD_CONTROL_DERIVATION.md`).

```
M6_VERTICAL_SLICE_CONNECTED_STAGES = 8   (unchanged, structural)
M6_PRODUCTION_CONNECTED_STAGES     = 8   (unchanged count; the SAME 8
  stages now additionally reachable from 11 more real production entry
  points, not a new stage becoming connected)
CAPABILITY_ISLANDS (this program's own generation-edge count) = 0
  (was 1 before this remediation)
```

Island (2) (every field other than `protocol`/`role`) remains open by
disclosed design, not oversight -- see `L5DGVA_CURRENT_SCOPE_GAP_
REGISTER.csv`'s `GAP-V2-003`, `REGISTER_AND_DEFER_WITH_OWNER`.

Real evidence: `dv_harness_tests/test_gap_v2_002_protocol_builder_
convergence.py` (5/5, new) -- all 11 skills verified converged (regex),
none still call the script directly, the script's own header self-
declares `INTERNAL_GENERATION_PRIMITIVE`, and an AST-based (not
text-grep) check confirms `create_environment()`'s real call-site set is
still exactly the 2 expected ones (the governed `engine.py` path and this
script). `dv_harness_tests/test_m6_c1_golden_path_connectivity.py`
(19/19) extended with the `role` field's own 7 test families,
independently of `protocol`'s.
