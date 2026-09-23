# Role-Aware Signoff Requirements (Sections 19-20)

Not implemented this wave — future M10 requirements.

## Coverage / Waiver / Signoff authority (Section 19)

```
Coverage Closure : primary authority = VERIFICATION/DV;
                    DESIGN/DE consulted where interpretation depends on
                    design intent
Waiver           : primary verification authority = DV;
                    a design limitation may require DE confirmation
Signoff          : DV owns Verification Signoff;
                    DE owns/participates in Design Closure and
                    unresolved design-risk confirmation
```

Every decision must preserve **evidence of who approved what, their
authority role, the evidence they relied on, and their rationale** —
this is a strengthening of the existing Evidence Truth Rule applied
specifically to the signoff boundary, not a new evidentiary standard.

## Role-Aware Signoff Traceability (Section 20)

Future traceability chain:

```
Requirement -> OpenSpec -> vPlan -> Test/Scenario ->
  Checker/Assertion/Scoreboard -> Coverage -> Regression Evidence ->
  Waiver -> Human Decision -> Authority Role -> Signoff
```

Add/reconcile equivalents of `AUTHORITY_ROLE` and `HUMAN_DECISION_REF`
onto the existing `requirement_traceability_registry.py` schema —
extending its already-real `ClosureRow`/vplan-leaf-row structure, not
replacing it.

## Not implemented during this task

Per Section 20's own instruction: M10 is not started. This document
records the target schema extension only.
