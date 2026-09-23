# USB Excel Gap Taxonomy & Root-Cause Classification

Status: registration only. **Not every gap becomes a KC.** Root cause
is classified FIRST; only a real `KNOWLEDGE_GAP` root cause is eligible
to proceed toward an Experience/KC Candidate (see
`USB_EXCEL_KC_EXTRACTION_CONTRACT.md`). A software defect is an
implementation issue, filed and fixed as a defect — never smuggled into
the Knowledge Brain as a "learned rule."

## Gap taxonomy (what was observed)

| Gap class | Meaning |
|---|---|
| `MISSING_REQUIRED_FIELD` | A required field's `EffectiveValue` is `None` after discovery ran |
| `INCORRECT_VALUE` | A resolved field's `EffectiveValue` does not match the current-evidence-correct value |
| `MISSING_EVIDENCE` | A resolved field has no `EvidenceRefs` |
| `WRONG_DERIVATION` | A `SourceKind.DERIVED` candidate used a wrong derivation rule |
| `DISCOVERY_NOT_CONSUMED` | A real evidence producer found the correct value, but it was not reflected in the final `EffectiveValue` (a resolution-algorithm or wiring defect, not a discovery defect) |
| `REDUNDANT_HUMAN_QUESTION` | A question was asked for a field that already had sufficient evidence with no policy reason to re-ask |
| `WRONG_QUESTION_OWNER` | A question was routed to the wrong DE/DV/SHARED role |
| `MISSING_VPLAN_ITEM` | A real Canonical vPlan chain link is absent from the Excel vPlan view |
| `MISSING_TOPOLOGY_ITEM` | A real Canonical topology/IR element is absent from the Excel Topology view |
| `MISSING_COVERAGE_LINK` | A real Canonical coverage/traceability link is absent from the Excel Coverage Closure view |
| `MISSING_SIGNOFF_EVIDENCE` | A real Canonical signoff evidence field is absent from the Excel Signoff view |
| `ROUND_TRIP_LOSS` | A field's value did not survive an export-then-import round trip unchanged |
| `STALE_WORKBOOK_FAILURE` | A real stale-workbook case was not correctly flagged |
| `CONFLICT_NOT_DETECTED` | A real `DeclaredValue`-vs-`AutoDiscoveredValue` conflict was silently resolved instead of flagged |
| `SCHEMA_DEFECT` | A workbook that should have passed schema validation failed, or vice versa |
| `PRESENTATION_ONLY_DEFECT` | A cosmetic/formatting defect with no semantic impact (e.g. a column mislabeled but the underlying data correct) |
| `USB_SPECIFIC_KNOWLEDGE_GAP` | A gap whose root cause is genuinely USB-protocol-specific missing knowledge |
| `GENERIC_DV_KNOWLEDGE_GAP` | A gap whose root cause is genuinely protocol-agnostic missing DV knowledge |

## Root-cause classification (WHY it happened — required before any KC eligibility decision)

| Root cause | Meaning | KC-eligible? |
|---|---|---|
| `GENERATOR_DEFECT` | The Excel generation code itself has a bug | NO — file as a software defect |
| `FIELD_MAPPING_DEFECT` | The Excel<->Canonical field mapping (`EXCEL_INTAKE_FIELD_MAPPING.csv`) is wrong or incomplete | NO — file as a documentation/mapping defect |
| `CANONICAL_MODEL_GAP` | The underlying Canonical model itself (vPlan/topology/coverage/signoff) is missing something Excel merely surfaces | NO — file against the owning Canonical model (M10/M10.5/etc.), not Excel |
| `DISCOVERY_DEFECT` | A real evidence producer has a bug or is missing entirely | NO — file as a software defect against the producer |
| `DERIVATION_DEFECT` | A derivation rule is wrong or missing | NO — file as a software defect |
| `VALIDATION_DEFECT` | The validator callback for a field is wrong or missing | NO — file as a software defect |
| `ROLE_ROUTING_DEFECT` | The DE/DV/SHARED routing rule itself is wrong for this field | NO — file as a software/policy defect against the role-routing rule |
| `KNOWLEDGE_GAP` | Nothing is broken — the SYSTEM correctly did everything it could, and what's missing is genuinely institutional knowledge no code change would fix | **YES** — proceed to Experience/KC Candidate |
| `PROJECT_DATA_GAP` | The project itself is missing a real input (e.g. a spec document was never provided) | NO — not a knowledge gap, a data-availability gap; escalate to the project, not the Knowledge Brain |
| `USER_INPUT_REQUIRED` | The field genuinely requires a human decision no evidence chain can supply | NO — this is `MINIMAL_STRUCTURED_CLARIFICATION` working as intended, not a gap to learn from |
| `UX_PRESENTATION_DEFECT` | A cosmetic/UX defect with no semantic impact | NO — file as a UX defect (M12's own productization scope) |

## Redundant-question RCA (Section 7's own required drill-down)

A `REDUNDANT_HUMAN_QUESTION` gap's root cause is narrowed to exactly one
of: `discovery-not-run` (the evidence producer never executed),
`result-not-consumed` (the producer found the value but `_decide()`
never saw it — a `DISCOVERY_NOT_CONSUMED` gap), `mapping gap` (a
`FIELD_MAPPING_DEFECT`), `validation ignored` (a `VALIDATION_DEFECT`),
`question-policy defect` (the question gate itself is miscalibrated —
e.g. asking despite `discovery_ran=True` and a valid, unambiguous
result), or `stale context` (the workbook/session context predates a
real answer that already exists elsewhere). None of these six is itself
`KNOWLEDGE_GAP` — a redundant question is, by construction, a software
or process defect, never a knowledge-learning opportunity.

## Question-owner RCA (Section 7's own required tracking)

`WRONG_QUESTION_OWNER`, `UNROUTABLE_QUESTION` (no real role rule covers
this field at all), and `LAZY_SHARED_CLASSIFICATION` (routed to SHARED
without genuine cross-domain ambiguity — SHARED is not an uncertainty
fallback) are tracked as their own named sub-classes of
`ROLE_ROUTING_DEFECT` — always a defect to fix in the routing rule
itself, never a `KNOWLEDGE_GAP`.
