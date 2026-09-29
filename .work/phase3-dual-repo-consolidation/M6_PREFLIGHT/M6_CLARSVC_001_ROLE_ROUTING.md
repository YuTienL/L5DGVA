# CAP-M6-CLARSVC-001 — QuestionOwner Role Routing

`dv_harness.clarification_service.classify_question_owner(control, decision)`.
Evidence/policy-based, never a lazy `SHARED` fallback
(`DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md` Section 5: "SHARED is never a
fallback for poor classification").

## Real signals used (both already exist; no new evidence source invented)

1. `FieldControl.domain` — `intake_field_resolution.QUESTION_DOMAINS =
   ("dut", "env", "vip")`, a real, already-required field on every
   `FieldControl`.
2. `QuestionDecision.kind` — `evaluate_question_gate()`'s own real
   classification (`"CONFLICT"` / `"UNKNOWN"` / `"CONFIRMATION"` / `None`).

## The mapping

```
domain == "dut" AND decision.kind != "CONFLICT"  -> DESIGN
domain == "dut" AND decision.kind == "CONFLICT"  -> SHARED
domain in ("env", "vip")                          -> VERIFICATION
```

## Why this mapping is the correct one, per the frozen architecture

`DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md` Section 5's own definitions:

- **`DESIGN_AUTHORITY` (DE)**: "intended DUT behavior, register semantics,
  reset/IRQ/clock intent, legal states, firmware programming intent,
  undocumented behavior, design limitations, protocol-mode design
  configuration, **RTL/spec discrepancy from a design-intent perspective**,
  implementation constraints." — this is exactly the `"dut"` domain's own
  real scope (DUT RTL/port/register facts, per `question.schema.json`'s
  own `domain` enum description: `"dut: DUT RTL/port/register question"`).
- **`VERIFICATION_AUTHORITY` (DV)**: "verification architecture, vPlan,
  feature mapping, scenario/test/sequence/constraint strategy,
  checker/scoreboard/assertion strategy, coverage model/closure,
  verification waiver, verification risk acceptance, verification signoff."
  — `"env"` (environment/component-hierarchy/config_db) and `"vip"`
  (VIP configuration/behavior) are both verification-environment concerns;
  neither is named anywhere under `DESIGN_AUTHORITY`.
- **`SHARED_AUTHORITY` (DE+DV)**: "reserved for genuine cross-domain
  decisions only: **Spec/RTL contradiction**, feature interpretation
  affecting closure, a design limitation requiring a verification waiver,
  requirement interpretation affecting signoff." — a `"dut"`-domain field
  whose `QuestionDecision.kind == "CONFLICT"` (two real, evidence-backed
  candidates disagree about a DUT/RTL fact) is, concretely, a Spec/RTL
  contradiction — the architecture's own first named `SHARED` example.

## What is deliberately NOT promoted to SHARED

An ordinary `"dut"`-domain field that is simply unresolved (`decision.kind
== "UNKNOWN"` — no evidence source found a value at all, no disagreement)
stays `DESIGN`. Needing to ask a human at all is never, by itself, evidence
of a cross-domain question — confirmed by
`test_an_ordinary_unknown_dut_field_is_not_automatically_shared`. An
`"env"`/`"vip"` conflict also stays `VERIFICATION` (not promoted to
`SHARED`): two verification-side sources disagreeing about a VIP/environment
config is a DV-internal question, not the DE-vs-DV tension the architecture's
own `SHARED` examples describe.

## Test evidence (all in `dv_harness_tests/test_clarification_service.py`)

```
test_de_question_owner_is_design_for_a_dut_domain_field            PASS
test_dv_question_owner_is_verification_for_env_and_vip_domain_fields PASS
test_shared_question_owner_only_for_a_genuine_dut_conflict          PASS
test_an_ordinary_unknown_dut_field_is_not_automatically_shared      PASS
```

## Persistence

`authority_role` (the literal `DESIGN`/`VERIFICATION`/`SHARED` string) is a
real, persisted, structured field on the `question_queue.py` record —
`schemas/question.schema.json`'s new, additive `authority_role` property —
never re-derived from prose at read time.

## Location-independence (preserved, Article 0 / Section 6 of the HITL architecture)

`classify_question_owner()`'s only inputs are `FieldControl.domain` and
`QuestionDecision.kind` — no username, host, repository path, or gateway
name is ever read. Confirmed by direct code read: the function has no
access to any identity/host information at all.
