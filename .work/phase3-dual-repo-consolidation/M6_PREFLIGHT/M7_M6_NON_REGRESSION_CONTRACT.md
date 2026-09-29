# M7 Preflight -- M6 Non-Regression Contract

M7 must not break the qualified M6 Golden Workflow
(`M6_QUALIFIED_CHECKPOINT_SHA = 2bd986f5e05fb5ee0c01d1c5c29d41a44c5b859f`,
`M6_STATUS = CLOSED`). This is the explicit preservation contract every
future M7 implementation cohort must satisfy, covering every stage this
task's own section 2 names.

## Preservation requirements, one per M6 stage

| M6 stage | What must be preserved | How a future M7 cohort proves it |
|---|---|---|
| Canonical Intake | `start_lifecycle()` remains the ONE lifecycle-first entry point; no second intake path for a multi-model task | re-run `test_start_lifecycle_dispatch.py` unchanged |
| Field Resolution | `intake_field_resolution.resolve_field()` remains the ONE resolution engine; a multi-model handoff's own fields (if any become real `FieldControl`s) resolve through it, never a second engine | re-run `test_intake_field_resolution.py` unchanged; any new M7 field control must pass through `resolve_field()`, never re-implement it |
| ClarificationService | `clarification_service.resolve_or_ask()` remains the ONE Clarification entry point | re-run `test_clarification_service.py` unchanged |
| QuestionOwner | `classify_question_owner()`'s DESIGN/VERIFICATION/SHARED classification is never bypassed by a multi-model "consensus" (see `M7_FAILURE_AND_FALLBACK_CONTRACT.md`, section 15/16) | re-run the QuestionOwner test family unchanged; no new authority_role value invented |
| HumanGate | dispatch still genuinely blocks on a real, unanswered question -- a model's own output is never substituted for a required human answer | re-run `test_human_answers_unblock_generation_and_are_persisted_as_lifecycle_facts` unchanged |
| EffectiveValue | still persisted via `lc.update_facts()`, the ONE real fact-persistence path | re-run the EffectiveValue-persistence tests unchanged |
| Dispatch | `start_lifecycle()`'s own generation branch remains the ONE dispatch point; a multi-model router (if any) sits ALONGSIDE it, never replaces it or forks a second dispatch path | re-run `test_generation_dispatch_calls_create_environment_directly_never_recurses` unchanged |
| Task Boundary | `check_working_tree_conformance()` remains the ONE boundary check; any model delegation's own scope is expressed as a real `TaskBoundary`, never a parallel scope mechanism | re-run `test_m6_task_boundary_production_001.py` unchanged; `M7_FAILURE_AND_FALLBACK_CONTRACT.md`'s own section 17 reuse requirement |
| VerificationLevel | `environment_mode_router.resolve_environment_mode()` remains the ONE mode decision; no model-specific mode variant invented | re-run `test_environment_mode_router.py`/`test_verification_level.py` unchanged |
| IP/SUBSYSTEM/SYSTEM_LEVEL routing | `create_environment()` remains the ONE generation consumer; a Codex/ChatGPT-assisted change still lands through the SAME dispatch, never a parallel generator | re-run `test_m5m6_vlevel_001_production_connectivity.py` unchanged |
| Protocol Builder governance | all 11 `.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` still converge on `dv-harness start --generate`; a multi-model-assisted skill invocation is still THIS same entry point, never a bypass | re-run `test_gap_v2_002_protocol_builder_convergence.py`'s AST-based check unchanged, `DIRECT_UNGOVERNED_PROTOCOL_BUILDER_CALLERS = 0` |
| Generation dispatch | the 10 real `create_environment()`-family exception classes stay fully caught and normalized | re-run the generation-failure-normalization tests unchanged; re-derive the exception-class inventory fresh at the start of any future M7 cohort (never assume the count is still 10 without re-checking) |

## Required regression discipline for every future M7 cohort

```
M6_GOLDEN_PATH_PRESERVED = YES
```

is required THROUGHOUT M7, not just at its own start. Every M7
implementation cohort must include the SAME 31-file real M6-slice
caller-population regression this qualification used
(`M6_FINAL_REGRESSION_EVIDENCE.md`'s own file list) as part of its own
closure evidence -- a regression against THAT population, not a
narrower subset, is what proves `M6_GOLDEN_PATH_PRESERVED` stays `YES`
after an M7 change, not merely at M7's own start.

## What this explicitly forbids (section 21's own "ONE Golden Workflow")

```
PARALLEL_MODEL_WORKFLOWS_CREATED = NO (required, every cohort)
ONE_GOLDEN_WORKFLOW = YES (required, every cohort)
```

No future M7 cohort may create a "Claude Workflow" / "Codex Workflow" /
"ChatGPT Workflow" as separate parallel paths. Every model's own
execution/review capability must plug INTO the existing 10-stage M6
Golden Workflow at a real, named stage (Dispatch, for model selection;
Task Boundary, for scope; VerificationLevel/generation, for the actual
work) -- never beside it.
