# M4 — Research / Experience Foundation

Per instruction #11: M3 already established that canonical/v50 lineage
contains the overwhelming majority of both capability families
(`M3_CAPABILITY_MIGRATION_RECORDS.md` Cohort 2,
`CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`). This wave does not create a
second framework — it checks only for missing FOUNDATION elements
(schemas/contracts/identifiers), reusing what already exists.

## Foundation element check (real, re-verified this wave, not re-asserted from M3)

| Needed foundation element | Real schema/contract found | Status |
|---|---|---|
| research provenance | `capability_evolution.compare_evidence_cards()`/`link_prior_research()` | REUSE (already present, tested) |
| research applicability | `capability_evolution.decide_recommendation()` (KEEP/ENHANCE/ADD/EXPERIMENT/REJECT/UNKNOWN) | REUSE |
| capability candidate schema | `capability_evolution.build_candidate()`'s real dataclass shape + `PROMOTION_STATES`/`LEGAL_TRANSITIONS` | REUSE |
| experiment/validation result | `capability_evolution.run_controlled_experiment()`/`run_shadow_replication()`/`assert_stability_window()` | REUSE |
| experience record (unified) | none anywhere on any tree (confirmed absent, M3 audit) | GENUINE GAP -- not a foundation this wave can close by reusing something; a real future design task (M8), not an M4 schema-closure item |
| applicability scope, counterexamples, generalization state, promotion state | `capability_evolution.py`'s `PROMOTION_STATES`/`LEGAL_TRANSITIONS` cover promotion state; applicability/counterexamples/generalization have no dedicated field anywhere (same gap as "experience record" above -- part of the same missing unified model) | PARTIAL (promotion state only) |
| coverage-closure experience | `coverage_closure_hole_correlation.py` (canonical/v50-only) + `coverage_hole_generation_candidate_queue.py` (CAP-M3-005, migrated) | REUSE |
| clarification-learning evidence | `QUESTION_AVOIDABLE` or equivalent: confirmed absent on every tree (M3 audit, re-confirmed via a fresh grep this wave: 0 hits) | GENUINE GAP, unchanged from M3's finding |
| generation-experience evidence | no generation-decision -> result -> reusable-experience mechanism found (M3 audit, re-confirmed) | GENUINE GAP, unchanged from M3's finding |

## Result

```
RESEARCH_EXPERIENCE_FOUNDATION = PARTIAL
DEFERRED_TO = M8
REASON = the missing pieces (a unified Experience record type,
  QUESTION_AVOIDABLE clarification learning, generation-experience
  learning) are genuine, confirmed-absent capabilities on every source
  tree -- not something any migration wave can "reuse" from an existing
  source, and not a schema/contract gap M4's narrow foundation-closure
  scope is positioned to design from scratch (that is real product design
  work, explicitly M8's job per Article 0's own migration-wave scoping).
REQUIRED_FUTURE_EVIDENCE = M8 must design the unified Experience record
  schema (EXPERIENCE_ID/OBSERVATION/SOURCE_PROJECT/VERIFICATION_LEVEL/
  PROTOCOL/DUT_CONTEXT/TOPOLOGY_CONTEXT/DECISION/OUTCOME/EVIDENCE_REFS/
  CONFIDENCE/APPLICABILITY_SCOPE/COUNTEREXAMPLES/GENERALIZATION_STATE/
  PROMOTION_STATE per the constitution's own field list) and the
  QUESTION_AVOIDABLE clarification-learning mechanism, with real evidence
  of at least one end-to-end use.
```

No second research/experience framework was created this wave, per the
explicit instruction not to redesign unnecessarily.
