# USB Excel Qualification Metrics

Status: registration only. No target percentages are invented here —
every metric below has a numerator, denominator, exclusions, evidence
source, and interpretation, never a threshold. Setting a target is a
future, separate decision once real V1/V2 data exists.

## Canonical denominator principle (frozen)

`EXPECTED_ITEMS = APPLICABLE_CANONICAL_ITEMS`, never "all template
fields." A workbook view's own template may list a field that is `N/A`
for this project/protocol/level — `N/A` is not `MISSING`, and is
excluded from every denominator below. Every metric's own denominator
must record WHERE its applicability list came from (OpenSpec field
catalogue, `VerificationEnvironmentIR`, vPlan, topology model, coverage
model, traceability registry, signoff model, or `MAINTAIN_LIFECYCLE`
model) — denominator provenance is itself part of the evidence record,
not assumed obvious.

## Metric definitions

| Metric | Numerator | Denominator | Exclusions | Evidence | Interpretation |
|---|---|---|---|---|---|
| `FIELD_COMPLETENESS` | Fields with a real `EffectiveValue` (not `None`) | `APPLICABLE_CANONICAL_ITEMS` for the view | `N/A`-classified fields | The workbook's own `to_openspec_record()`-shaped export per field | How much of the applicable field set is resolved at all, correct or not |
| `FIELD_CORRECTNESS` | Resolved fields whose `EffectiveValue` matches the current-evidence-correct value (per real RTL/spec/VIP re-check, not assumed) | Resolved fields (from `FIELD_COMPLETENESS`'s numerator) | Fields with no independently-verifiable ground truth | A qualification-time re-derivation of each field against its own real evidence source | Of what got resolved, how much is actually right |
| `EVIDENCE_COVERAGE` | Resolved fields with a non-empty `EvidenceRefs` | Resolved fields | N/A-classified fields | `EffectiveValue.evidence_refs` | Whether a resolved value is backed by a citable source, not a bare assertion |
| `AUTO_DISCOVERY_RATE` | Fields resolved via `SourceKind.AUTO_DISCOVERED`/`ResolutionMethod` other than `HUMAN_CONFIRMED` | Resolved fields | Fields structurally undiscoverable (no real evidence producer exists for that field kind) | `EffectiveValue.resolution_method`, `Candidate.kind` | How much AUTO_DISCOVERY_FIRST is actually doing, vs. relying on a human |
| `DERIVATION_RATE` | Fields resolved via a `SourceKind.DERIVED` candidate | Resolved fields | Fields with no known derivation rule | `Candidate.kind == DERIVED` | How much of resolution comes from computed/derived values specifically |
| `UNRESOLVED_FIELD_RATE` | Fields with `EffectiveValue is None` after discovery ran | `APPLICABLE_CANONICAL_ITEMS` | `N/A`-classified fields | `EffectiveValue.value is None and discovery_ran is True` | Real, honest gap rate — never silently folded into "resolved" |
| `UNKNOWN_FIELD_RATE` | Fields a workbook references that the current schema does not recognize | Total fields referenced in the workbook | N/A | `EXCEL_SCHEMA_VALIDATION`'s own unknown-field check | Schema drift between workbook generation and current Canonical schema |
| `REDUNDANT_HUMAN_QUESTION_RATE` | Questions asked whose field already had high-confidence, validated evidence with no policy reason to re-ask | Total questions asked | Questions the field's own `confirmation_required` policy mandates regardless of confidence | `evaluate_question_gate()`'s own decision + a post-hoc RCA check (Section "Redundant Question RCA" below) | Whether `MINIMAL_STRUCTURED_CLARIFICATION` is actually being honored |
| `WRONG_QUESTION_OWNER_RATE` | Questions routed to the wrong role (DE question sent to DV or vice versa; SHARED used without genuine cross-domain ambiguity) | Total questions asked | N/A | The real DE/DV Role-Based HITL routing rules, re-checked against each question's actual field content | Role-routing correctness, not just "a role was assigned" |
| `SCHEMA_VALIDITY` | Workbooks passing all `EXCEL_SCHEMA_AND_VALIDATION_REQUIREMENTS.md` checks | Total workbooks generated/imported in the qualification run | N/A | The real validation result per workbook | Structural workbook health |
| `ROUND_TRIP_VALIDITY` | Fields whose value survives an export-then-import round trip unchanged (when no real change was made) | Fields exported | N/A | A real export/re-import diff | Whether the round-trip contract (`EXCEL_ROUND_TRIP_CONTRACT.md`) actually holds |
| `STALE_DETECTION_VALIDITY` | Real staleness cases correctly flagged (not `SAFE_TO_APPLY` when they should not be) | Real staleness cases introduced during qualification (deliberately, via a real snapshot advance) | N/A | `EXCEL_STALE_WORKBOOK_DETECTION`'s own disposition output | Whether stale detection works on real, not hypothetical, cases |
| `CONFLICT_DETECTION_VALIDITY` | Real `DeclaredValue`-vs-`AutoDiscoveredValue` conflicts correctly flagged (never silently resolved) | Real conflict cases introduced during qualification | N/A | `EXCEL_FIELD_CONFLICT_DETECTION`'s own output, cross-checked against `ValidationState.CONTRADICTED` | Whether conflict detection works on real, not hypothetical, cases |
| `VPLAN_TRACEABILITY_COMPLETENESS` | vPlan chain links (Requirement->...->Signoff) present in the Excel vPlan view that also exist in Canonical vPlan | Canonical vPlan's own real chain links (M10-owned, once real) | N/A | Direct comparison against Canonical vPlan state | Whether the vPlan VIEW is a faithful presentation, not a degraded copy |
| `TOPOLOGY_COMPLETENESS` | Topology elements present in the Excel Topology view that also exist in Canonical topology/IR | Canonical topology/IR's own real element count | N/A | Direct comparison against Canonical topology/IR | Same faithfulness check, for the Topology view |
| `COVERAGE_TRACEABILITY_COMPLETENESS` | Coverage-to-requirement links present in the Excel Coverage Closure view that also exist in Canonical coverage/traceability | Canonical coverage/traceability's own real link count (M10-owned) | N/A | Direct comparison | Same faithfulness check, for the Coverage Closure view |
| `SIGNOFF_EVIDENCE_COMPLETENESS` | Signoff evidence fields present in the Excel Signoff view that also exist in Canonical signoff state | Canonical signoff's own real evidence field count (M10-owned, DV authority) | N/A | Direct comparison | Same faithfulness check, for the Signoff view |

## Explicit non-goal

No numeric target (e.g. "`FIELD_COMPLETENESS` must be >= 90%") is set
by this reconciliation. Setting targets before any real V1 data exists
would be exactly the fabricated-evidence pattern the Evidence Truth Rule
forbids.
