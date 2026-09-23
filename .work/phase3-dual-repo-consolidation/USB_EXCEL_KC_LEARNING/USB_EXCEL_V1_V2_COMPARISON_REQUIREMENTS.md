# USB Excel V1/V2 Comparison Requirements

Status: registration only.

## Comparison basis

V1 and V2 are compared using IDENTICAL applicable denominators and
rules — the same `APPLICABLE_CANONICAL_ITEMS` set, the same gap
taxonomy, the same root-cause taxonomy, the same metric definitions
(`USB_EXCEL_QUALIFICATION_METRICS.md`). A denominator that changed
between V1 and V2 (e.g. because the Canonical model itself grew a new
field) is disclosed as a `NOT_COMPARABLE` condition for that specific
item, never silently normalized away.

## What is compared

Missing items, incorrect values, missing evidence, redundant questions,
wrong question owner, unknown fields, traceability gaps (vPlan/
topology/coverage/signoff), and round-trip failures — one comparison
per gap-taxonomy class from `USB_EXCEL_GAP_TAXONOMY.md`, V1 count vs. V2
count, for the same applicable item set.

## Verdicts (per comparison item, and rolled up overall)

```
IMPROVED       -- V2 measurably better than V1 on this dimension
NO_CHANGE      -- no measurable difference
REGRESSED      -- V2 measurably worse than V1 on this dimension
NOT_COMPARABLE -- the denominator or rule itself changed between V1 and
                  V2, so a direct comparison would be misleading
```

**Improvement is never forced.** A `REGRESSED` or `NO_CHANGE` verdict is
as valid an outcome as `IMPROVED` — this qualification measures reality,
it does not exist to produce a predetermined positive result.

## Required no-regression checks

```
NO_QUALITY_REGRESSION        -- overall FIELD_CORRECTNESS/COMPLETENESS
                                 does not silently drop
NO_NEW_UNEXPLAINED_GAPS       -- any gap present in V2 but not V1 has a
                                 recorded root cause, never left as an
                                 unexplained new defect
NO_ROLE_ROUTING_REGRESSION    -- WRONG_QUESTION_OWNER/UNROUTABLE_QUESTION/
                                 LAZY_SHARED_CLASSIFICATION counts do not
                                 increase
NO_EVIDENCE_REGRESSION        -- EVIDENCE_COVERAGE does not drop
NO_SCHEMA_REGRESSION          -- SCHEMA_VALIDITY does not drop
NO_TRACEABILITY_REGRESSION    -- VPLAN/TOPOLOGY/COVERAGE/SIGNOFF
                                 traceability completeness does not drop
```

## Disclose tradeoffs, never hide them

If V2 improves on one dimension at the cost of another (e.g. fewer
redundant questions but a new, real traceability gap), both results are
reported together — a V1/V2 report that only surfaces the improved
dimension while omitting a real regression is not a valid qualification
result under this contract.

## Relationship to the Closed-Loop Knowledge Learning Gate

This comparison is the FINAL step of the closed loop
(`CLOSED_LOOP_KNOWLEDGE_LEARNING_QUALIFICATION.md`'s own "Outcome
Re-Qualified" and "Improvement/No-Improvement Measured" requirements).
A `CLOSED_LOOP_KNOWLEDGE_LEARNING_QUALIFICATION` verdict of `PASS`
requires this comparison to have actually run and produced a real
verdict (any of the four above) — it does not require the verdict to be
`IMPROVED`.
