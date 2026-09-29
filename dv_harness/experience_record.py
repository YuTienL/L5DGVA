"""Unified Experience record type (M8 Cohort 2, CAP-M8-EXPLOOP-002 / GAP-M8-002).

GAP-M8-002's own root cause (CANONICAL_CAPABILITY_SUPERSET_MATRIX.md,
capability-family table): "No unified Experience record type exists
anywhere" for the 3 confirmed-absent internal learning stages --
CLARIFICATION_LEARNING, GENERATION_EXPERIENCE_LEARNING, SIGNOFF_
EXPERIENCE_CONSOLIDATION (all "ABSENT" on every source tree, zero code).

This module is the one shared record shape all 3 new producers build
through (dv_harness/question_queue.py's answer_question();
dv_harness/engine.py's _promote_generation_experience_knowledge() and
_promote_signoff_experience_consolidation()), instead of each inventing
its own ad hoc dict. Per CLAUDE.md's Connect-Before-Expand discipline it
feeds the SAME existing route_and_store()/memory_router.py pipeline the
pre-existing EXPERT_FEEDBACK_LOOP experience-promotion call site
(engine.py's _promote_experience_knowledge(), kind="debug_lesson") already
uses -- never a second store, router, or event bus. memory_router.
route_memory()'s existing routing rule (kind in ("root_cause",
"verified_fix","debug_lesson") and verified -> ENGINEERING_MEMORY) is
reused unchanged, so a Cohort-2 record is discoverable through the exact
same real MemoryStore/MemoryRetriever path Cohort 1's own adjacent
regression already exercises -- no new consumer was built or is needed.

What this module deliberately does NOT do: decide whether/when to
promote (that stays each call site's own stage-scoped guard, mirroring
engine.py's existing 5 _promote_*/_record_* methods), or prove downstream
consumption -- Cohort 2's own frozen exit criterion (M8_EXIT_CRITERIA.md
Internal-experience-loop #2) requires only "a real producer, a unified
Experience record type, and a real behavioral test" for each of the 3
stages, not proof that a later workflow acts on the resulting knowledge
(that is Cohort 4/5's own scope, per M8_EXIT_CRITERIA.md's Role-Aware
Experience Learning criterion)."""
from __future__ import annotations

from typing import Any, Dict, Optional

# The 3 stages GAP-M8-002 names, verbatim (CANONICAL_CAPABILITY_SUPERSET_
# MATRIX.md / M8_GAP_REGISTER.csv / M8_SCOPE_AND_OWNERSHIP_MATRIX.csv) --
# a real, closed vocabulary, never a free-text label a caller invents.
EXPERIENCE_TYPES = (
    "CLARIFICATION_LEARNING",
    "GENERATION_EXPERIENCE_LEARNING",
    "SIGNOFF_EXPERIENCE_CONSOLIDATION",
)

# M8 Cohort 4 (CAP-HITL-008 ROLE_AWARE_EXPERIENCE_LEARNING / CAP-HITL-009
# KNOWLEDGE_DOMAIN_CLASSIFICATION): the SAME real, already-built 3-value
# vocabulary dv_harness/clarification_service.py's own QUESTION_OWNERS
# already defines and dv_harness/clarification_service.classify_question_
# owner() already computes for real, production-filed intake questions
# (added 2026-09-24 for CAP-M6-CLARSVC-001, reused here rather than
# duplicated import-wise to avoid a real circular-import path: question_
# queue.py -> experience_record.py -> clarification_service.py ->
# question_queue.py). DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md Section 5's
# own DESIGN_AUTHORITY/VERIFICATION_AUTHORITY/SHARED_AUTHORITY and ROLE_
# AWARE_EXPERIENCE_REQUIREMENTS.md Section 14's KNOWLEDGE_DOMAIN are the
# SAME 3-value taxonomy applied to two closely related questions ("who
# decided" vs. "what kind of knowledge is this") -- Cohort 4 deliberately
# sources both from the one real classified value available today rather
# than building a second classifier with no real signal to compute from.
ROLE_DOMAIN_VALUES = ("DESIGN", "VERIFICATION", "SHARED")
# Explicit, persisted sentinel for a record with no real role/domain
# signal available at write time (e.g. GENERATION_EXPERIENCE_LEARNING/
# SIGNOFF_EXPERIENCE_CONSOLIDATION, or a CLARIFICATION_LEARNING record
# whose underlying question predates CAP-M6-CLARSVC-001's authority_role
# field, or was filed through a caller that never set it) -- never a
# silent None/omission, so historical/unclassified knowledge stays
# explicitly, honestly excluded from a role/domain-scoped search rather
# than becoming undiscoverable or falsely claimed as classified.
UNCLASSIFIED = "UNCLASSIFIED"


def build_experience_record(
    *,
    experience_type: str,
    title: str,
    pattern: str,
    lesson: str,
    evidence: str,
    applicability_constraints: str = "",
    confidence: str = "HIGH",
    producing_agent_profile: Optional[str] = None,
    verified: bool = True,
    protocol: Optional[str] = None,
    knowledge_domain: Optional[str] = None,
    human_role: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds one route_and_store()-shaped record dict, the unified shape
    across all 3 Cohort-2 Experience producers (now also carrying Cohort
    4's role/domain metadata). Raises ValueError on an experience_type
    outside EXPERIENCE_TYPES, or on a knowledge_domain/human_role outside
    ROLE_DOMAIN_VALUES (when not None) -- a real, checked contract, not a
    caller convention trusted by naming alone.

    `lesson` maps onto the record's own `root_cause` field (the same field
    name _promote_experience_knowledge()'s existing record already uses for
    a debug_lesson-kind record) so a Cohort-2 record has the identical
    shape MemoryStore/MemoryRetriever already know how to index and search
    -- deliberately not a new field name that would need its own retrieval
    support.

    `knowledge_domain`/`human_role` (Cohort 4, both default None -> stored
    as the explicit UNCLASSIFIED sentinel, never omitted): applicability
    metadata on this SAME existing record, per ROLE_AWARE_EXPERIENCE_
    REQUIREMENTS.md Section 14's own instruction ("a KNOWLEDGE_DOMAIN field
    added to the existing Memory/Obsidian schema, never a fourth or fifth
    memory system"). MemoryRetriever.search()'s own pre-existing, generic
    `property` filter (memory.py's `property_filters`/`_record_field()`)
    already supports filtering by any record field including these two --
    no new retrieval code was needed or written for this."""
    if experience_type not in EXPERIENCE_TYPES:
        raise ValueError(
            f"Unknown experience_type: {experience_type!r} (must be one of {EXPERIENCE_TYPES})"
        )
    for field_name, value in (("knowledge_domain", knowledge_domain), ("human_role", human_role)):
        if value is not None and value not in ROLE_DOMAIN_VALUES:
            raise ValueError(
                f"{field_name} must be one of {ROLE_DOMAIN_VALUES} or None, got {value!r}"
            )
    record: Dict[str, Any] = {
        "kind": "debug_lesson",
        "verified": verified,
        "experience_type": experience_type,
        "title": title,
        "pattern": pattern,
        "root_cause": lesson,
        "evidence": evidence,
        "applicability_constraints": applicability_constraints,
        "confidence": confidence,
        "producing_agent_profile": producing_agent_profile,
        "protocol": protocol,
        "knowledge_domain": knowledge_domain or UNCLASSIFIED,
        "human_role": human_role or UNCLASSIFIED,
    }
    if extra:
        record.update(extra)
    return record
