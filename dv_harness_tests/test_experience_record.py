"""Tests for dv_harness/experience_record.py -- the unified Experience
record type M8 Cohort 2 (CAP-M8-EXPLOOP-002 / GAP-M8-002) builds all 3
new producers' records through."""
from __future__ import annotations

import pytest

from dv_harness.experience_record import EXPERIENCE_TYPES, build_experience_record


def test_experience_types_is_the_real_closed_gap_m8_002_vocabulary():
    # The 3 stage names GAP-M8-002/M8_SCOPE_AND_OWNERSHIP_MATRIX.csv name,
    # verbatim -- not a free-text label a caller could invent.
    assert set(EXPERIENCE_TYPES) == {
        "CLARIFICATION_LEARNING",
        "GENERATION_EXPERIENCE_LEARNING",
        "SIGNOFF_EXPERIENCE_CONSOLIDATION",
    }


def test_build_experience_record_rejects_unknown_experience_type():
    with pytest.raises(ValueError):
        build_experience_record(
            experience_type="NOT_A_REAL_TYPE", title="t", pattern="p",
            lesson="l", evidence="e",
        )


@pytest.mark.parametrize("experience_type", EXPERIENCE_TYPES)
def test_build_experience_record_shape_is_unified_across_all_3_types(experience_type):
    # Same real kind/verified/route_and_store()-ready shape regardless of
    # which of the 3 stages produced it -- this uniformity IS "a unified
    # Experience record type", not 3 independently-shaped ad hoc dicts.
    record = build_experience_record(
        experience_type=experience_type, title="title", pattern="pattern",
        lesson="lesson text", evidence="evidence text",
        applicability_constraints="constraints", producing_agent_profile="agentA",
    )
    assert record["kind"] == "debug_lesson"
    assert record["verified"] is True
    assert record["experience_type"] == experience_type
    assert record["title"] == "title"
    assert record["pattern"] == "pattern"
    # `lesson` maps onto the record's own `root_cause` field -- the same
    # field name memory_router.py's ENGINEERING_REUSABLE_CLAIM_FIELDS and
    # the pre-existing _promote_experience_knowledge() record already use,
    # so MemoryStore/MemoryRetriever need no new field support.
    assert record["root_cause"] == "lesson text"
    assert record["evidence"] == "evidence text"
    assert record["applicability_constraints"] == "constraints"
    assert record["confidence"] == "HIGH"
    assert record["producing_agent_profile"] == "agentA"


def test_build_experience_record_extra_fields_are_additive():
    record = build_experience_record(
        experience_type="CLARIFICATION_LEARNING", title="t", pattern="p",
        lesson="l", evidence="e", extra={"question_id": "Q-1"},
    )
    assert record["question_id"] == "Q-1"
    assert record["experience_type"] == "CLARIFICATION_LEARNING"


def test_build_experience_record_routes_to_engineering_memory():
    # Real routing proof, not an assumption: memory_router.route_memory()'s
    # own existing rule (kind in root_cause/verified_fix/debug_lesson and
    # verified=True -> ENGINEERING_MEMORY) is reused unchanged.
    from dv_harness.memory_router import route_memory
    record = build_experience_record(
        experience_type="GENERATION_EXPERIENCE_LEARNING", title="t", pattern="p",
        lesson="l", evidence="e",
    )
    assert route_memory(record) == "ENGINEERING_MEMORY"
