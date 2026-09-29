# M6 Final Operational Slice Qualification -- HITL Metric Correction

Per this task's own explicit instruction (section 23): "Not every stage
requires HITL... Do not penalize purely automated stages for not
involving a human." The prior report's flat `HITL_CONNECTED_STAGES = 5/10`
used the WRONG denominator -- 10 (every M6 stage), when only a subset of
the 10 stages have HITL as part of their own contract at all. This
document supplies the corrected, two-number metric this task requires.

## HITL_APPLICABLE_STAGES = 4

Determined by direct source re-inspection of each stage's own real
contract (not inherited from the prior report), one stage at a time:

| Stage | HITL applicable? | Why |
|---|---|---|
| 1. Intake | NO | asks no question itself; a pure entry-plan/lifecycle-record step |
| 2. Field Resolution | **YES** | the point where an unresolved required field genuinely needs a human decision |
| 3. Clarification hand-off | **YES** | the point where that need becomes a real, persisted question |
| 4. QuestionOwner | **YES** | the point where WHO owns that human decision (DESIGN/VERIFICATION/SHARED) is decided |
| 5. HumanGate | **YES** | the point where dispatch genuinely blocks until a real human answers |
| 6. EffectiveValue | NO | the OUTPUT of a HITL decision (or auto-discovery), not itself a human interaction |
| 7. Dispatch | NO | mechanical request assembly |
| 8. Task Boundary | NO | a structural git-evidence check by design (CAP-ATL-004's own docstring: "caller-declared... never derived" -- no QuestionOwner/HumanGate involved at all) |
| 9. VerificationLevel | NO | ROUTES an already-resolved value; the level's own human-decision point already happened at stages 2-5 -- counting it again here would double-count the SAME human decision against two stages |
| 10. IP/SUBSYSTEM/SYSTEM_LEVEL | NO | mechanical generation dispatch |

`HITL_APPLICABLE_STAGES = 4` (stages 2, 3, 4, 5).

## HITL_QUALIFIED_STAGES = 4

Each of the 4 applicable stages independently evaluated against real
evidence (not credited merely for having a test file):

- **Stage 2 (Field Resolution)**: QUALIFIED. The unresolved-field path is
  real and production-connected for all 3 M6 generation fields
  (`test_m6_c1_golden_path_connectivity.py`,
  `test_m5m6_vlevel_001_production_connectivity.py`), and the underlying
  conflict-handling contract it depends on is independently proven
  (`test_intake_field_resolution.py`).
- **Stage 3 (Clarification hand-off)**: QUALIFIED. A real question is
  filed, persisted, and idempotent
  (`test_all_three_unresolved_files_three_real_questions`,
  `test_duplicate_question_is_not_re_filed_without_evidence_change`).
- **Stage 4 (QuestionOwner)**: QUALIFIED, with a disclosed scope finding
  (not a defect) -- see below.
- **Stage 5 (HumanGate)**: QUALIFIED. A real human answer via
  `QuestionQueueStore.answer_question()` (never a direct `EffectiveValue`
  edit) unblocks dispatch and persists the resolved fact
  (`test_human_answers_unblock_generation_and_are_persisted_as_lifecycle_facts`).

`HITL_QUALIFIED_STAGES = 4`.

```
HITL_QUALIFICATION = HITL_QUALIFIED_STAGES / HITL_APPLICABLE_STAGES = 4/4 = PASS
```

## Disclosed finding at stage 4: DESIGN and SHARED authority are real,
tested MECHANISM, but NOT_APPLICABLE to M6's own current production scope

Direct re-verification (fresh, not assumed) of `clarification_service.
classify_question_owner()`: `_DOMAIN_DEFAULT_OWNER` maps `"dut" ->
DESIGN`, `"env"/"vip" -> VERIFICATION`; the one real promotion to
`SHARED` requires a `"dut"`-domain field AND a genuine `CONFLICT` kind.

`clarification_service.resolve_or_ask()`'s ONLY real production caller,
repo-wide (`grep -rln "resolve_or_ask" dv_harness/*.py`, production files
only), is `engine.py`'s `start_lifecycle()`, via `generation_field_
controls.py`'s exactly 3 `FieldControl`s (`protocol`/`role`/
`verification_level`) -- and all 3 are declared `domain="env"`
(`protocol_field_control()`/`role_field_control()`/`verification_level_
field_control()`, confirmed by direct source read). **No real, current M6
production `FieldControl` ever uses `domain="dut"`.** This means:

- **VERIFICATION authority**: real, production-exercised, QUALIFIED
  (`test_protocol_and_role_question_owner_is_verification`, extended for
  `verification_level`).
- **DESIGN authority**: the MECHANISM's own `"dut" -> DESIGN` branch is
  real and independently tested through the actual `resolve_or_ask()`
  function (`test_de_question_owner_is_design_for_a_dut_domain_field`),
  but no CURRENT M6-scope production caller ever constructs a `domain=
  "dut"` generation `FieldControl`. Classified **NOT_APPLICABLE_WITH_
  EVIDENCE** for "a genuine DESIGN-owned clarification within M6's own
  generation path" -- not fabricated merely to complete the matrix, per
  this task's own explicit instruction.
- **SHARED authority (positive case)**: same reasoning, doubly
  inapplicable (requires `domain="dut"` AND `CONFLICT`, neither of which
  M6's own field set can ever produce). Classified **NOT_APPLICABLE_WITH_
  EVIDENCE**.
- **SHARED authority (negative case, explicitly required by this task's
  own section 10)**: "prove an ordinary unknown is NOT automatically
  classified SHARED" -- real and tested
  (`test_an_ordinary_unknown_dut_field_is_not_automatically_shared`),
  independent of whether M6's own field set can reach `"dut"` domain at
  all; this proves the underlying classifier M6's own QuestionOwner stage
  depends on never lazily defaults to SHARED.

This is a genuine, evidence-derived scope boundary of the M6 Operational
Slice's OWN 3-field generation path -- not a defect in `classify_
question_owner()` itself (which is real, correct, and independently
tested for all 3 authority classes), and not something this task
manufactured a fake case to paper over.
