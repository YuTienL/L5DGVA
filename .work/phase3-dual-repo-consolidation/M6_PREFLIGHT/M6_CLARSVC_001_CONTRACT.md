# CAP-M6-CLARSVC-001 — ClarificationService Contract

`dv_harness/clarification_service.py`. One Canonical `ClarificationService`
(M-1 D2, not reopened), over `question_queue.py` + `intake_field_resolution.py`
— never a second Field Resolution engine.

## Responsibility (dispatch Section 3)

`resolve_or_ask(root_or_store, control, ...)` is the one real entry point:

1. Consume unresolved field-resolution results — runs
   `intake_field_resolution.resolve_field()` first, always.
2. Determine whether human clarification is required —
   `intake_field_resolution.evaluate_question_gate()`, reused verbatim.
3. Determine `QuestionOwner` — `classify_question_owner()`, real, evidence-
   based (see `M6_CLARSVC_001_ROLE_ROUTING.md`).
4. Construct the minimum sufficient question — `intake_field_resolution.
   file_clarification()`, reused verbatim, now carrying `authority_role`.
5. Submit/store the question — `question_queue.QuestionQueueStore.add_
   question()`, reused verbatim (additive `authority_role` kwarg).
6. Consume the answer — checks `QuestionQueueStore.get_question()` for a
   real answer BEFORE filing a new question.
7. Feed the answer back through Canonical Field Resolution — re-runs
   `resolve_field(..., human_answer=existing["answer"])`, never a direct
   `EffectiveValue` overwrite.
8. Produce a newly resolved or still-unresolved field state —
   `ClarificationOutcome.resolved` / `.effective_value`.

## OpenSpec field model (Section 6) — preserved exactly, not collapsed

`DeclaredValue`/`AutoDiscoveredValue`/`DerivedValue`/`EffectiveValue`/
`Confidence`/`ValidationState`/`ConfirmationState`/`EvidenceRefs` are
`intake_field_resolution.py`'s own real dataclasses/fields — `clarification_
service.py` imports and reuses them (`EffectiveValue`, `Confidence`,
`FieldControl`, `EvidenceProducer`, `QuestionDecision`) and defines **zero**
new field-value types of its own. `Confidence`/`ValidationState`/
`ConfirmationState` remain three distinct fields on `EffectiveValue` — never
collapsed into one. A human answer enters via `resolve_field()`'s own real
`human_answer=` parameter, so `_decide()`'s existing 9-level source-authority
arbitration, validation and confirmation-state logic all apply to it exactly
as they do to any other candidate — confirmed by
`test_answer_round_trip_feeds_back_through_field_resolution`.

## Question contract (Section 7) — reused, not duplicated

The real, persisted `question_queue.py` record already carries: `id`
(`QUESTION_ID`), `question_key` (embeds `FIELD_ID` as `intake:<field_id>`),
`domain`+`owner` (routing), `question` (`PROMPT`, with candidates/evidence/
reasons rendered into its own text per `file_clarification()`'s existing
behavior), `tier`/`tier_reason` (`CONFIDENCE`/why-asked context), `status`
(`STATUS`), `answer`/`answered_at`/`decided_by` (`ALLOWED_RESPONSES`'
resolution), `created_at` (`CREATED_AT`), `grounding_evidence` (the existing
"why am I being asked this" citation, Section 8's own field, reused
unchanged), and now `authority_role` (`QUESTION_OWNER` — the one genuinely
new, real, persisted structured field this capability adds). No duplicate
schema was invented; `KNOWN_TECHNICAL_GAPS["STRUCTURED_CLARIFICATION_
CONTEXT_NOT_PERSISTED"]` (candidates/evidence rendered into text only, not
separately structured) remains open and disclosed, unchanged by this
capability — a real, pre-existing, deliberately-deferred gap, not silently
claimed closed.

## Why-am-I-being-asked (Section 8) — reused, not rebuilt

`grounding_evidence` (real, already built, `2026-09-07`) is `question_
queue.py`'s own existing proactive question-grounding mechanism. `file_
clarification()`'s own rendered question text already answers all four
named sub-questions (why unresolved, what evidence exists, why automatic
resolution was insufficient, what is blocked) — confirmed by direct read of
its own text-assembly code (`Reason: ...`, `Why user authority is required:
...`, `Attempted evidence sources: ...`, `Downstream impact: ...`).

## HumanGate integration (Section 9) — generalized, not replaced

`ClarificationService` does not become a human authority itself — it routes
(`classify_question_owner()`) and records (`question_queue.py`'s existing
persistence). `human_gate_state()` projects a real, persisted question
record onto `HUMAN_GATE_CONTRACT.md`'s own `RESOLUTION_STATE` vocabulary
using ONLY states this codebase's real fields can honestly support:
`WAITING_FOR_HUMAN` (status `OPEN`), `ANSWERED` (`answer` is not null),
`SUPERSEDED` (`overturned` is true). `REJECTED`/`DEFERRED`/`CANCELLED` have
no real canonical equivalent today and are disclosed as `NOT_SUPPORTED`
(returned only defensively; no real code path produces them) rather than
invented.

## Dispatch integration (Section 11) — no duplicated guard

`engine.py`'s `start_lifecycle()` (`CAP-M6-DISPATCH-001`) now delegates its
own field-resolution loop to `clarification_service.resolve_or_ask()`
instead of re-inlining `resolve_field()`/`evaluate_question_gate()`/`file_
clarification()` a second time — a real refactor, not merely an added call
site (see the git diff on `engine.py`'s `start_lifecycle()`). The
`_intake_first_guard()` gate embedded in `run_stage()` is untouched by this
capability; `ClarificationService` blocks dispatch the same way it already
did (a `WAIT_USER` `AgentResult` with `blocked_by: "clarification"`) and
dispatch resumes through the exact same `_start_dispatch()` path once fields
resolve — confirmed end-to-end by `test_dispatch_blocks_on_unresolved_
field_and_resumes_after_answer`.

## Frontend independence (Section 12) — preserved

`resolve_or_ask()`'s only inputs are a `FieldControl` and evidence
producers — no CLI/dashboard/Excel/Native-Claude-specific code exists
anywhere in `clarification_service.py`. Every future frontend consumes the
same contract through the same function.

## What this capability deliberately does NOT build (Sections 13/14/18)

- Native Claude Fast Maintenance's own CLI flow — not started.
- Structured Excel Intake's own UX — not started; Excel's own roadmap
  document already names this capability as the wave that decides "which
  field-resolution model M6 ultimately wires as canonical's own live
  engine" — answered here (`intake_field_resolution.py`), inherited
  unchanged by Excel's own future integration.
- `VerificationLevel` (`CAP-M5M6-VLEVEL-001`) — not started; `level`/
  `protocols` remain stored-but-uninterpreted lifecycle facts, unchanged
  from `CAP-M6-DISPATCH-001`'s own implementation.
