"""Tests for dv_harness/l5dgva_directive_blackboard_work_queue.py -- V22 SS649
"Blackboard Work Queue": real projection + real Blackboard.write()/read()
round trip, plus the honest ExecutableDirectiveBlackboardQueue_PASS
evaluator. Uses a real dv_harness.blackboard.Blackboard rooted at tmp_path,
never a mock.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- canonical's
real Blackboard was independently confirmed compatible before this migration
(same `.dv-harness/blackboard/<topic>.json` path convention, same
write()/read() payload shape), so no test adaptation was needed.
"""
from __future__ import annotations

import json

from dv_harness.blackboard import Blackboard
from dv_harness.l5dgva_directive_blackboard_work_queue import (
    BLACKBOARD_WORK_QUEUE_TOPIC,
    STATUS_NOT_YET_PUBLISHED,
    STATUS_PRESENT,
    WORK_QUEUE_CATEGORIES,
    build_blackboard_queue_entry,
    evaluate_blackboard_work_queue,
    publish_directive_work_queue,
)
from dv_harness.l5dgva_directive_registry import (
    DirectiveRecord,
    WorkItemDescriptor,
    seed_registry,
    seed_v21_ss638_directive,
    seed_v21_exec_workitem_descriptors,
)
from dv_harness.l5dgva_workitem_projection import WorkItemState


# ---------------------------------------------------------------------------
# Primary-text transcription fixtures
# ---------------------------------------------------------------------------


def test_work_queue_categories_are_the_five_named_in_the_primary_text_in_order():
    assert WORK_QUEUE_CATEGORIES == (
        "work_items",
        "dependencies",
        "blockers",
        "evidence",
        "outcomes",
    )


# ---------------------------------------------------------------------------
# build_blackboard_queue_entry()
# ---------------------------------------------------------------------------


def test_build_entry_from_the_real_seeded_v21_ss638_directive():
    directive = seed_v21_ss638_directive()
    work_items = seed_v21_exec_workitem_descriptors()

    entry = build_blackboard_queue_entry(directive, work_items)

    assert entry.directive_id == "V21-SS638-IMMEDIATE-EXECUTION"
    assert len(entry.work_items) == 21
    assert entry.work_items[0] == {
        "work_item_id": "V21-EXEC-001",
        "label": "contract discovery",
        "execution_state": "DISCOVERED",
    }
    # Honestly empty, not fabricated -- seed_v21_ss638_directive() carries no
    # dependency graph or dispatch evidence (see l5dgva_directive_registry.py).
    assert entry.dependencies == ()
    assert entry.evidence == ()
    # Nothing has been dispatched, so no BLOCKED_VALID item exists yet.
    assert entry.blockers == ()
    assert len(entry.outcomes) == 22  # 1 directive-level + 21 work items
    assert entry.outcomes[0] == {"id": "V21-SS638-IMMEDIATE-EXECUTION", "verdict": None}


def test_build_entry_collects_blockers_from_blocked_valid_work_items():
    directive = seed_v21_ss638_directive()
    work_items = list(seed_v21_exec_workitem_descriptors())
    blocked = work_items[3]
    work_items[3] = WorkItemDescriptor(
        work_item_id=blocked.work_item_id,
        label=blocked.label,
        source_step_number=blocked.source_step_number,
        source_step_text=blocked.source_step_text,
        execution_state=WorkItemState.BLOCKED_VALID,
        verdict=None,
    )

    entry = build_blackboard_queue_entry(directive, work_items)

    assert entry.blockers == (blocked.work_item_id,)


def test_build_entry_prepends_directive_itself_when_directive_is_blocked():
    directive = DirectiveRecord(
        directive_id="D-BLOCKED",
        source_contract="TEST",
        source_section="649",
        directive_text_ref="test fixture",
        execution_state=WorkItemState.BLOCKED_VALID,
    )
    entry = build_blackboard_queue_entry(directive, ())
    assert entry.blockers == ("D-BLOCKED",)


# ---------------------------------------------------------------------------
# publish_directive_work_queue() + evaluate_blackboard_work_queue() -- real
# Blackboard round trip
# ---------------------------------------------------------------------------


def test_evaluate_against_a_fresh_blackboard_the_repo_actually_uses_is_honestly_false(tmp_path):
    """No caller in this codebase invokes publish_directive_work_queue() from
    engine.py/gates.py/cli.py -- confirmed by grep before writing this module.
    A fresh, never-written Blackboard must therefore report every category
    NOT_YET_PUBLISHED and pass_=False, not a fabricated True."""
    blackboard = Blackboard(tmp_path)
    result = evaluate_blackboard_work_queue(blackboard)

    assert set(result.category_status.values()) == {STATUS_NOT_YET_PUBLISHED}
    assert result.pass_ is False


def test_publish_then_evaluate_reports_all_five_categories_present(tmp_path):
    blackboard = Blackboard(tmp_path)
    directive = seed_v21_ss638_directive()
    work_items = seed_v21_exec_workitem_descriptors()

    payload = publish_directive_work_queue(blackboard, directive, work_items, source="test")

    assert payload["topic"] == BLACKBOARD_WORK_QUEUE_TOPIC
    assert payload["value"]["directive_id"] == directive.directive_id
    assert len(payload["value"]["work_items"]) == 21

    result = evaluate_blackboard_work_queue(blackboard)
    assert result.category_status == {category: STATUS_PRESENT for category in WORK_QUEUE_CATEGORIES}
    assert result.pass_ is True


def test_published_topic_is_real_readable_json_on_disk(tmp_path):
    blackboard = Blackboard(tmp_path)
    directive = seed_v21_ss638_directive()
    work_items = seed_v21_exec_workitem_descriptors()
    publish_directive_work_queue(blackboard, directive, work_items)

    topic_path = tmp_path / ".dv-harness" / "blackboard" / f"{BLACKBOARD_WORK_QUEUE_TOPIC}.json"
    assert topic_path.is_file()
    raw = json.loads(topic_path.read_text(encoding="utf-8"))
    assert raw["value"]["directive_id"] == directive.directive_id
    assert raw["value"]["dependencies"] == []


def test_evaluate_reports_present_even_when_a_category_is_honestly_empty(tmp_path):
    """dependencies/evidence/blockers are genuinely () for the real seeded
    directive -- published-empty must read as PRESENT (the key was written),
    never conflated with NOT_YET_PUBLISHED (the topic was never written)."""
    blackboard = Blackboard(tmp_path)
    directive = seed_v21_ss638_directive()
    work_items = seed_v21_exec_workitem_descriptors()
    publish_directive_work_queue(blackboard, directive, work_items)

    result = evaluate_blackboard_work_queue(blackboard)
    assert result.category_status["dependencies"] == STATUS_PRESENT
    assert result.category_status["evidence"] == STATUS_PRESENT
    assert result.category_status["blockers"] == STATUS_PRESENT


def test_seed_registry_round_trips_through_publish_and_evaluate(tmp_path):
    """End-to-end using the module's own seed_registry() convenience, same
    as the sibling checkpoint-resume test suite does."""
    registry, work_items = seed_registry()
    directive = registry.all()[0]
    blackboard = Blackboard(tmp_path)

    publish_directive_work_queue(blackboard, directive, work_items)
    result = evaluate_blackboard_work_queue(blackboard)

    assert result.pass_ is True
