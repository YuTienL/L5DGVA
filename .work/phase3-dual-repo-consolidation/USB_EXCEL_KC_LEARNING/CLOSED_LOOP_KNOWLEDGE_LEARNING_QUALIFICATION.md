# Closed-Loop Knowledge Learning Qualification Gate

Status: registration only — this document DEFINES the gate; it does not
run it.

## Definition

`CLOSED_LOOP_KNOWLEDGE_LEARNING` requires ALL of the following to be
independently, separately evidenced — `KC_STORED=YES` alone cannot
satisfy this gate:

```
1. Experience Captured             -- a real Experience Candidate exists,
                                       with a confirmed KNOWLEDGE_GAP root
                                       cause (USB_EXCEL_GAP_TAXONOMY.md)
2. KC Candidate Created             -- the Experience Candidate carries a
                                       real proposed_knowledge field
3. Promotion Decision Recorded      -- the full promotion flow
                                       (USB_EXCEL_KC_EXTRACTION_CONTRACT.md)
                                       ran and reached a real decision
                                       (promoted or explicitly not)
4. KC Stored                        -- the promoted KC exists in the ONE
                                       Knowledge Brain
5. KC Retrieved                     -- a real retrieval call, in a
                                       genuinely independent V2 session,
                                       returned this KC
6. KC Consumed                      -- real evidence the retrieval
                                       actually changed V2's generated
                                       output (USB_EXCEL_KC_REGENERATION_
                                       CONTRACT.md's own consumption
                                       evidence bar)
7. Generation Behavior Affected     -- the specific behavior change is
                                       identified and attributable to
                                       the specific KC
8. Outcome Re-Qualified             -- V2 went through the SAME
                                       qualification process as V1
9. Improvement/No-Improvement
   Measured                         -- a real V1/V2 comparison verdict
                                       exists (IMPROVED/NO_CHANGE/
                                       REGRESSED/NOT_COMPARABLE) -- any
                                       of the four satisfies this
                                       requirement; only the ABSENCE of a
                                       real comparison fails it
```

## PASS condition

All 9 steps evidenced, in order, for at least one real KC. `PASS` does
NOT require step 9's verdict to be `IMPROVED` — it requires the
MEASUREMENT to have genuinely happened. A `PASS` gate with a
`REGRESSED` V1/V2 verdict is an honest, valid PASS of the LEARNING-LOOP
mechanism (the loop closed and was measured), even though the specific
KC's own value is then called into question by that same regression —
these are two different questions this gate deliberately keeps
separate.

## FAIL conditions (any one is sufficient)

- Any of the 9 steps lacks real, independent evidence.
- Step 6 (KC Consumed) is asserted without the specific consumption
  evidence `USB_EXCEL_KC_REGENERATION_CONTRACT.md` requires (a bare
  "it was retrieved" does not satisfy consumption).
- Step 9 is skipped or asserted without a real comparison having run.
- Any USB-specific observation was promoted to `GENERIC_DV` or
  `PROTOCOL_CLASS` without the applicability + counterexample evidence
  `USB_EXCEL_KC_EXTRACTION_CONTRACT.md` requires.

## Relationship to the qualification principle

This gate is the literal, checkable form of the frozen principle:

```
EXCEL_FILE_GENERATED != EXCEL_QUALIFIED
KC_STORED != CLOSED_LOOP_LEARNING
KC_PROMOTED != KC_CONSUMED
KC_CONSUMED != IMPROVEMENT_PROVEN
```

Each `!=` above corresponds to a real gap this 9-step gate refuses to
let collapse: generating a file is not qualifying it (steps 1-4 alone
do not pass); storing a KC is not closing the loop (steps 4 alone does
not pass); promoting a KC is not consuming it (steps 3-4 without 5-7 do
not pass); consuming a KC is not the same as proving it helped (steps
1-7 without 8-9 do not pass).
