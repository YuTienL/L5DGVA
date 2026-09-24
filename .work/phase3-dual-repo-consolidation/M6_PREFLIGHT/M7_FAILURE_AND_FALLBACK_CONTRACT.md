# M7 Preflight -- Failure and Fallback Contract

Per this task's own explicit instruction: "The Golden Workflow must
degrade safely. No model failure may silently become PASS." This
document defines the REQUIRED contract for M7's own future
implementation cohorts -- it does not implement fallback logic itself
(PREFLIGHT scope only), but every requirement below reuses a real,
already-proven pattern from this project rather than inventing a new
failure vocabulary.

## Failure classes and the real pattern each must reuse

| Failure class | Required behavior | Reused pattern (real, already proven) |
|---|---|---|
| ChatGPT unavailable | Degrade to `HUMAN_MEDIATED_ONLY` (the CURRENT real state -- never silently skip the step) | `task_boundary_conformance.working_tree_changes()`'s own degrade-never-raise `NO_GIT`/`STATUS_FAILED` vocabulary (`change_impact._git()`'s shared wrapper) |
| Codex unavailable | Same -- degrade to `HUMAN_MEDIATED_ONLY`, never silently PASS | Same degrade-never-raise discipline |
| Claude unavailable | This is the ONE path the current Golden Workflow already depends on unconditionally -- no fallback model exists today; must surface as a real, blocking failure, never silently substituted | `AgentResult(ok=False, ...)`'s own real failure-result contract |
| Model invocation fails (network/timeout/etc.) | A real, structured failure result, never an uncaught exception | The SAME 10-exception-class normalization pattern `create_environment()`'s own callers already use (`GAP-V2-001`, re-verified intact by `M6-TASK-BOUNDARY-PRODUCTION-001`'s own qualification pass) |
| Output invalid / cannot be parsed | `ValidationState.INVALID` + a real reason string, never a silent drop or a guessed correction | `intake_field_resolution.py`'s own `ValidationState`/`validator=` pattern |
| Review disagreement occurs | See `M7_M6_NON_REGRESSION_CONTRACT.md`'s own reuse of Evidence-Grounded contracts -- claim/evidence/counter-evidence/confidence/validation-state, never majority vote | `dv_harness/confidence_calibration.py`'s own `confirmation_count`-based confidence model (the SAME real cross-run confirmation contract `M6-FINAL-QUALIFICATION` itself used) |

## The one hard rule (section 14's own core requirement)

```
NO_MODEL_FAILURE_BECOMES_SILENT_PASS = REQUIRED
```

Every real failure-normalization precedent in this codebase already
honors this (`create_environment()`'s 10 exception classes all surface
as `AgentResult(ok=False, ...)`, never a swallowed exception; `Task
Boundary` VIOLATION always blocks, never silently degrades to HELD). M7's
own future fallback logic for Codex/ChatGPT unavailability must be built
to the SAME discipline: an unavailable model degrades the WORKFLOW'S OWN
CLAIM (e.g. "this was NOT independently reviewed, proceed with that
disclosed as a known gap") -- it must never make the workflow report a
review/synthesis STEP as having happened when it did not.

## Human authority is never replaced by multi-model consensus (section 15)

```
DESIGN_AUTHORITY = DE
VERIFICATION_AUTHORITY = DV
VERIFICATION_SIGNOFF_AUTHORITY = DV
```

Already real, already enforced elsewhere in this project (`clarification_
service.classify_question_owner()`'s own DESIGN/VERIFICATION/SHARED
authority_role classification, qualified as part of M6's own HITL
stage). Three models "agreeing" is not a `QuestionOwner`, is not a
`HumanGate` answer, and must never be substituted for one. Any future M7
router/consensus mechanism must route its own OUTPUT through the SAME
`resolve_or_ask()`/`HumanGate` mechanism a human answer already goes
through -- never bypass it with a multi-model vote.

## Model disagreement representation (section 16)

Reuse, not invent: `intake_field_resolution.py`'s own real conflict
model already carries exactly the shape section 16 asks for --
`Candidate`s preserving both sides' own `value`/`source`/`confidence`/
`evidence_refs`, never silently picking a winner by confidence alone
(`test_confidence_alone_never_selects_a_winner_among_conflicting_
values`), escalating to a real question when unresolved
(`clarification_service`'s own `CONFLICT` `QuestionDecision.kind`). A
future Codex-vs-Claude or ChatGPT-vs-Claude disagreement should be
modeled as exactly this shape: two `Candidate`s, both evidence-backed,
never averaged, never majority-voted, escalated to the correct
`QuestionOwner` (DE/DV/SHARED) when genuinely unresolved.

## Security / scope boundary (section 17)

```
Track: ALLOWED_CONTEXT, FORBIDDEN_CONTEXT, FILES_SHARED, OUTPUT_SCOPE
```

Directly reuses `TaskBoundary.allowed_path_prefixes`/`forbidden_paths`
(CAP-ATL-004, now production-connected as of `M6-TASK-BOUNDARY-
PRODUCTION-001`) -- a delegated model's own scope IS a `TaskBoundary`,
the same real mechanism the M6 Golden Workflow itself just qualified. A
multi-model path that skipped Task Boundary would be a NEW, uncontrolled
bypass class (`UNCONTROLLED_BYPASSES > 0`) -- explicitly forbidden by
this same task's own section 17 instruction ("Do not create a
multi-model path that bypasses M6 Task Boundary").
