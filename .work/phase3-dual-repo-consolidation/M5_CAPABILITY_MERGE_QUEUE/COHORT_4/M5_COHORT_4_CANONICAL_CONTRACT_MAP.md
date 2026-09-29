# M5 Cohort 4 — Canonical Contract Map

Maps every symbol this Cohort touches or depends on to its real canonical
home, per instruction item 6 (Canonical OpenSpec Authority) and item 13
(Schema Discipline: no second competing OpenSpec schema).

## task_boundary_conformance.py

| Symbol | Canonical home | Status |
|---|---|---|
| `TaskBoundary`, `classify_path`, `working_tree_changes`, `committed_range_changes`, `check_working_tree_conformance`, `check_committed_range_conformance` | `dv_harness/task_boundary_conformance.py` (new, this Cohort) | NEW, FOUNDATION |
| `_git()` | `dv_harness/change_impact.py` (pre-existing, unmodified) | REUSED |
| `resolve_sha()` | `dv_harness/change_impact.py` (pre-existing, unmodified) | REUSED |

No schema file exists or is created for this module's output shape (a
plain dict, not validated against any JSON Schema anywhere in canonical or
Parent) — no second competing schema risk.

## intake_field_resolution.py

| Symbol | Canonical home | Status |
|---|---|---|
| `OPENSPEC_FIELD_ATTRIBUTES`, `EVIDENCE_LADDER`, `QUESTION_DOMAINS`, `MAX_QUESTION_OPTIONS`, `ValueState`, `ResolutionMethod`, `SourceKind`, `ValidationState`, `ConfirmationState`, `Origin`, `Confidence`, `Candidate`, `FieldControl`, `DiscoveryAttempt`, `EvidenceProducer`, `EffectiveValue`, `resolve_field`, `resolve_recorded`, `QuestionDecision`, `field_is_sufficient`, `evaluate_question_gate`, `file_clarification`, `KNOWN_TECHNICAL_GAPS`, `CLOSED_TECHNICAL_GAPS` | `dv_harness/intake_field_resolution.py` (new, this Cohort) | NEW, FOUNDATION -- an ADAPTED port, not identical to Parent (see the two deliberate departures in the module's own docstring) |
| `source_authority.authority_rank`, `SourceClaim`, `resolve_conflict` | `dv_harness/source_authority.py` (pre-existing, unmodified) | REUSED |
| `question_queue.make_question_id`, `QuestionQueueStore` | `dv_harness/question_queue.py` (pre-existing, unmodified) | REUSED |
| `IntakeFieldRecord`, `IntakeFieldStatus` (the EXISTING, parallel, different canonical model) | `dv_harness/intake_state.py` (pre-existing, unmodified) | UNCHANGED, NOT reconciled this Cohort -- see `M5_COHORT_4_FIELD_RESOLUTION_ANALYSIS.md`'s Canonical Reconciliation section |
| `verification_intake_contract.CONDITION_STATUSES` | `dv_harness/verification_intake_contract.py` (pre-existing, unmodified) | Cited context only, not reused/touched |
| `intake_audit_provenance.established_by_status` taxonomy | `dv_harness/intake_audit_provenance.py` (pre-existing, unmodified) | Cited context only (a real, stronger canonical evidence-provenance analog), not reused/touched |

No schema file exists or is created for this module's output shape either
— `to_openspec_record()`/`to_record()` return plain dicts, asserted
in-code against `OPENSPEC_FIELD_ATTRIBUTES` (a tuple, not a JSON Schema).
No second competing OpenSpec schema is introduced.

## Explicit non-migration (disclosed, not silently dropped)

Parent's 9 sibling intake-pipeline modules
(`intake_contract.py`/`intake_discovery.py`/`intake_interfaces.py`/
`intake_loader.py`/`intake_package.py`/`intake_resume.py`/
`intake_schema.py`/`intake_validation.py`/`intake_workbook.py`) and
`irq_openspec_preflight_gate.py` (905 lines) are **not** migrated, read in
full, or otherwise expanded into by this Cohort — out of the registered
scope by explicit instruction. Their existence is cited as context (they
are `intake_field_resolution.py`'s real Parent-side callers) but their
content is not analyzed.
