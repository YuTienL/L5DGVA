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
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds one route_and_store()-shaped record dict, the unified shape
    across all 3 Cohort-2 Experience producers. Raises ValueError on an
    experience_type outside EXPERIENCE_TYPES -- a real, checked contract,
    not a caller convention trusted by naming alone.

    `lesson` maps onto the record's own `root_cause` field (the same field
    name _promote_experience_knowledge()'s existing record already uses for
    a debug_lesson-kind record) so a Cohort-2 record has the identical
    shape MemoryStore/MemoryRetriever already know how to index and search
    -- deliberately not a new field name that would need its own retrieval
    support."""
    if experience_type not in EXPERIENCE_TYPES:
        raise ValueError(
            f"Unknown experience_type: {experience_type!r} (must be one of {EXPERIENCE_TYPES})"
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
    }
    if extra:
        record.update(extra)
    return record
