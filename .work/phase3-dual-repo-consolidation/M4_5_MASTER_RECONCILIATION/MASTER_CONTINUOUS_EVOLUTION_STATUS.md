# Master Continuous Capability Evolution Status

Two loops per Article 0 (S13 of the reconciliation prompt). Synthesis of
`CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`'s capability-family table —
not re-audited from scratch this wave.

## EXTERNAL loop: CONTINUOUS_RESEARCH_EVOLUTION

`Research → Distill → Evidence → Applicability → Proposal → Validate → Evolve`

```
RESEARCH_INGESTION                  = IMPLEMENTED,WIRED,TESTED
DV_PAPER_DISTILLATION               = IMPLEMENTED (folded into research-ingestion skill)
NEW_TECHNOLOGY_EXTRACTION           = IMPLEMENTED (same skill, no separate module)
RESEARCH_PROVENANCE                 = IMPLEMENTED,TESTED
RESEARCH_APPLICABILITY              = IMPLEMENTED,TESTED
RESEARCH_TO_CAPABILITY_PROPOSAL     = IMPLEMENTED,WIRED,TRIGGERED,TESTED
CAPABILITY_EXPERIMENT_VALIDATION    = IMPLEMENTED,TESTED
```

**This loop is real and operational end-to-end** (research → candidate →
controlled experiment), already present via the v50 bootstrap and
confirmed unchanged in canonical during M3. This is the strongest-
evidenced domain in the whole reconciliation — no gap reassignment
needed here.

## INTERNAL loop: CONTINUOUS_PROJECT_EXPERIENCE_LEARNING

`Project/User → Generate → Simulate → RCA → Regression → Coverage →
Signoff → Experience → Generalize → Promote → Improve next generation`

```
PROJECT_EXPERIENCE_EXTRACTION       = PARTIAL (no unified Experience
  record type exists anywhere; covered only by narrower mechanisms:
  memory_lineage.py, memory_quality_policy.py, cross_project_mining.py)
USER_INTERACTION_LEARNING           = IMPLEMENTED,TESTED (v50-lineage)
CLARIFICATION_LEARNING              = ABSENT (confirmed on every tree)
GENERATION_EXPERIENCE_LEARNING      = ABSENT (confirmed on every tree)
RCA_EXPERIENCE_LEARNING             = PARTIAL (repeated-failure detection
  only, not a full RCA-to-fix experience record)
COVERAGE_CLOSURE_LEARNING           = IMPLEMENTED,TESTED (both halves,
  after CAP-M3-005's migration)
SIGNOFF_EXPERIENCE_CONSOLIDATION    = ABSENT (confirmed on every tree)
KNOWLEDGE_PROMOTION                 = IMPLEMENTED,TESTED
CROSS_PROJECT_GENERALIZATION        = IMPLEMENTED,TESTED
MULTI_AGENT_KNOWLEDGE_CONSUMPTION   = NOT_VERIFIED (never independently
  audited, any wave)
```

**Confirmed-broken common mechanism (not a migration gap — a real,
pre-existing defect identical on Parent, v50, and canonical):**
`tools/verification_flow/promotion_chain_audit_gate.py` requires an
`EXPERIENCE_READY` event whenever `failure_detected` is false, but no
stage in `gates.py`'s `STAGE_GATES`/`prompts.py`'s `STAGE_INSTRUCTIONS`
ever emits it, and `memory_router.route_and_store()` has no caller in the
prompt/gate pipeline at all. This is the concrete, current-evidence
reason the INTERNAL loop cannot be `OPERATIONAL` even where its
individual pieces are real — see `CAP-M8-EXPLOOP-001` (`P0`, owner `M8`).

```
CONTINUOUS_CAPABILITY_EVOLUTION (composite) = PARTIAL
  -- EXTERNAL half: real, operational end-to-end
  -- INTERNAL half: structurally broken at the wiring point common to
     every tree, plus 3 of its named stages confirmed fully absent
     (CLARIFICATION_LEARNING, GENERATION_EXPERIENCE_LEARNING,
     SIGNOFF_EXPERIENCE_CONSOLIDATION)
```

This composite cannot honestly be marked `OPERATIONAL` while either half
is `PARTIAL`/`ABSENT` — unchanged conclusion from M3, re-confirmed by
this reconciliation's cross-check against the M8 ownership assignment.
Not M3/M4/M4.5's job to fix (explicitly M8's, per instruction #28 and the
M4 Final Report's own `HIGHEST_PRINCIPLE_COMPLIANCE` line).
