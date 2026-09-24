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
