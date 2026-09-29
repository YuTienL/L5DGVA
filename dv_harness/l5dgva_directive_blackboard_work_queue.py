"""dv_harness/l5dgva_directive_blackboard_work_queue.py -- V22 SS649
`Blackboard Work Queue`: a real projection of the L5DGVA contract-execution
directive/work-item chain into the exact shape SS649 names, plus a real,
run-against-this-repo evaluator of `ExecutableDirectiveBlackboardQueue_PASS`.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- this
module is CAP-POOL-003's target capability. Depends on `blackboard.Blackboard`
(canonical's real class, independently verified compatible before this
migration: `Blackboard.write(t, value, source='', confidence='HIGH')` writes
`{'topic': t, 'value': value, 'source': source, 'confidence': confidence}`
atomically; `Blackboard.read(t, default=None)` returns that whole dict or
`default` -- exactly the shape this module's own `_entry_to_payload()`/
`evaluate_blackboard_work_queue()` already assume) and on
`l5dgva_directive_registry.py`/`l5dgva_workitem_projection.py`, both migrated
identically to canonical earlier in this same batch.

Primary text, quoted verbatim, from
`L5DGVA/L5_DGVA_v22_EXECUTION_ENFORCEMENT_Governing_Contract_Activation_Dispatch.md`
(lines 8139-8144; re-grep for "## 649." before trusting these line numbers
across a future edit to that file):

    ## 649. Blackboard Work Queue

    Publish active directive work items, dependencies, blockers, evidence
    and outcomes into Blackboard/shared authoritative state.

    Required: `ExecutableDirectiveBlackboardQueue_PASS = true`

WHY THIS SECTION, AND WHY NOW: `l5dgva_directive_execution_counters.py`'s own
docstring (V22 SS658-663/675) surveyed the "after 648" range and rejected
SS649 alongside SS650-653/665-671/677/679/680 as all requiring "a real
dispatch/execution/session-persistence event ... none of that exists yet".
That blanket rejection has since been falsified twice over for its own
siblings: CAP204 built a real persistence mechanism for SS631/677
(`l5dgva_directive_checkpoint_resume.py`) and CAP264 built a real composite
for SS679 (`l5dgva_v22_execution_enforcement_closure_gate.py`), in both cases
by separating "the real STRUCTURAL/SCHEMA mechanism can be built and run
honestly today" from "the LIVE-DISPATCH semantic claim it describes stays
open" -- exactly the same split this module applies to SS649. SS649's own
verb is "Publish ... into Blackboard" -- Blackboard is not a hypothetical
future component, it is `dv_harness/blackboard.py`, a real class this repo
already has three live, tested registry topics on (`findings`,
`debug_loop_history`, `capability_evolution_candidates`). Whether SS649's
publish step has ever actually been exercised by a real caller is an honest,
checkable fact, not a live-dispatch question -- it needs zero engine.py
wiring to answer, only a real `Blackboard.read()`.

WHAT THIS MODULE BUILDS (the real, buildable half):

  1. `WORK_QUEUE_CATEGORIES`: SS649's own five named categories, verbatim
     order ("work items, dependencies, blockers, evidence and outcomes").
  2. `build_blackboard_queue_entry()`: projects one real, already-seeded
     `DirectiveRecord` + its `WorkItemDescriptor`s (from
     `l5dgva_directive_registry.py`, reused read-only, never re-implemented)
     into a `DirectiveBlackboardQueueEntry` populated from real field values
     only -- never a fabricated dependency/blocker/evidence/outcome.
  3. `publish_directive_work_queue()`: a real call to the real
     `dv_harness.blackboard.Blackboard.write()` (reused, not re-implemented)
     under one topic name, `BLACKBOARD_WORK_QUEUE_TOPIC`, following the exact
     same `{"items": {...}}`-free flat-payload convention `blackboard.py`'s
     own `findings`/`debug_loop_history` topics already use.
  4. `evaluate_blackboard_work_queue()`: SS649's own
     `ExecutableDirectiveBlackboardQueue_PASS`, computed honestly from a real
     `Blackboard.read()` -- `NOT_YET_PUBLISHED_TO_BLACKBOARD` per category
     when the topic has never been written, `PRESENT` per category once
     `publish_directive_work_queue()` has actually run against that
     `Blackboard` instance.

WHAT THIS MODULE HONESTLY DOES NOT DO:

  - It never calls `publish_directive_work_queue()` itself from anywhere in
    `engine.py`/`gates.py`/`cli.py` -- no such wiring exists, so
    `ExecutableDirectiveBlackboardQueue_PASS` against this repo's real,
    running Blackboard stays honestly `False` (see
    `test_evaluate_against_a_fresh_blackboard_the_repo_actually_uses_is_
    honestly_false`). This module proves the publish MECHANISM is real, not
    that any real run has ever exercised it.
  - `dependencies`/`evidence` on the one real seeded `DirectiveRecord` are
    genuinely `()` today -- `l5dgva_directive_registry.py`'s own docstring
    explains why (no dependency graph or dispatch evidence exists for an
    un-dispatched directive). This module reports that as a real, honestly
    EMPTY category (still `PRESENT` -- the key is published, its value is
    genuinely empty), never as `NOT_YET_PUBLISHED_TO_BLACKBOARD`, which is
    reserved for "the whole topic was never written at all". Conflating
    "published empty" with "never published" would let a caller who writes
    an empty stub silently claim the same status as one who never wrote
    anything.
  - `WorkItemDescriptor` (unlike `DirectiveRecord`) carries no `evidence_refs`
    field at all -- the identical disclosed schema gap
    `l5dgva_directive_execution_counters.py` already names for SS675. This
    module's `evidence` category is therefore sourced from the directive
    level only, never invented per work item.
  - `blockers` is derived purely from `execution_state == BLOCKED_VALID` on
    real seeded records -- it does not attempt SS662's separate
    reason-validity classification (a different section, already built in
    `l5dgva_directive_execution_counters.classify_valid_block_reason()`);
    SS649 only asks that blockers be published, not that their reasons be
    judged valid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from .blackboard import Blackboard
from .l5dgva_directive_registry import DirectiveRecord, WorkItemDescriptor
from .l5dgva_workitem_projection import WorkItemState

#: Where every literal quote in this module's docstring came from -- re-grep for
#: "## 649." before trusting the cited line numbers across a future edit to that file.
SOURCE_FILE_V22 = (
    "L5DGVA/L5_DGVA_v22_EXECUTION_ENFORCEMENT_Governing_Contract_Activation_Dispatch.md"
)

#: SS649's own five named categories, verbatim order from "Publish active
#: directive work items, dependencies, blockers, evidence and outcomes".
WORK_QUEUE_CATEGORIES: Tuple[str, ...] = (
    "work_items",
    "dependencies",
    "blockers",
    "evidence",
    "outcomes",
)

#: The real `dv_harness.blackboard.Blackboard` topic this module publishes
#: to/reads from -- one flat payload per directive_id, same convention as
#: `blackboard.py`'s own `findings`/`debug_loop_history` topics (a `.json`
#: file under `.dv-harness/blackboard/`, never a second parallel store).
BLACKBOARD_WORK_QUEUE_TOPIC = "l5dgva_directive_work_queue"

#: Honest per-category status vocabulary -- matches the existing
#: `l5dgva_directive_checkpoint_resume.py` convention of naming absence
#: precisely rather than a bare `False`.
STATUS_PRESENT = "PRESENT"
STATUS_NOT_YET_PUBLISHED = "NOT_YET_PUBLISHED_TO_BLACKBOARD"


@dataclass(frozen=True)
class DirectiveBlackboardQueueEntry:
    """One directive's worth of SS649's five named categories, populated only
    from real `DirectiveRecord`/`WorkItemDescriptor` field values -- see this
    module's docstring for exactly which fields back which category and why
    two of them (`dependencies`, `evidence`) are honestly empty tuples today
    rather than fabricated content."""

    directive_id: str
    work_items: Tuple[Dict[str, str], ...]
    dependencies: Tuple[str, ...]
    blockers: Tuple[str, ...]
    evidence: Tuple[str, ...]
    outcomes: Tuple[Dict[str, Optional[str]], ...]


def build_blackboard_queue_entry(
    directive: DirectiveRecord,
    work_items: Sequence[WorkItemDescriptor],
) -> DirectiveBlackboardQueueEntry:
    """Project one real seeded directive + its compiled work items into
    SS649's five categories. Never invents a dependency, blocker, evidence
    reference or outcome that is not already a real field value."""
    work_item_rows = tuple(
        {
            "work_item_id": item.work_item_id,
            "label": item.label,
            "execution_state": item.execution_state.value,
        }
        for item in work_items
    )
    blockers = tuple(
        item.work_item_id for item in work_items if item.execution_state is WorkItemState.BLOCKED_VALID
    )
    if directive.execution_state is WorkItemState.BLOCKED_VALID:
        blockers = (directive.directive_id,) + blockers
    outcomes = ({"id": directive.directive_id, "verdict": directive.verdict},) + tuple(
        {"id": item.work_item_id, "verdict": item.verdict} for item in work_items
    )
    return DirectiveBlackboardQueueEntry(
        directive_id=directive.directive_id,
        work_items=work_item_rows,
        dependencies=tuple(directive.dependencies),
        blockers=blockers,
        evidence=tuple(directive.evidence_refs),
        outcomes=outcomes,
    )


def _entry_to_payload(entry: DirectiveBlackboardQueueEntry) -> Dict[str, Any]:
    """JSON-safe dict, one key per `WORK_QUEUE_CATEGORIES` entry plus the
    identifying `directive_id` -- the exact shape written to/read from the
    real Blackboard topic."""
    return {
        "directive_id": entry.directive_id,
        "work_items": list(entry.work_items),
        "dependencies": list(entry.dependencies),
        "blockers": list(entry.blockers),
        "evidence": list(entry.evidence),
        "outcomes": list(entry.outcomes),
    }


def publish_directive_work_queue(
    blackboard: Blackboard,
    directive: DirectiveRecord,
    work_items: Sequence[WorkItemDescriptor],
    source: str = "",
) -> Dict[str, Any]:
    """SS649's own verb, for real: write one directive's SS649-shaped entry
    into the real `Blackboard.write()` (reused, never re-implemented) under
    `BLACKBOARD_WORK_QUEUE_TOPIC`. Returns the exact payload written."""
    entry = build_blackboard_queue_entry(directive, work_items)
    payload = blackboard.write(BLACKBOARD_WORK_QUEUE_TOPIC, _entry_to_payload(entry), source=source)
    return payload


@dataclass(frozen=True)
class BlackboardWorkQueueEvaluation:
    """SS649's own `ExecutableDirectiveBlackboardQueue_PASS`, computed
    honestly from a real `Blackboard.read()` against one live `Blackboard`
    instance -- never assumed from whether the mechanism merely exists."""

    category_status: Dict[str, str]
    pass_: bool


def evaluate_blackboard_work_queue(blackboard: Blackboard) -> BlackboardWorkQueueEvaluation:
    """Read `BLACKBOARD_WORK_QUEUE_TOPIC` off the given `Blackboard` and
    report, per SS649 category, whether it has genuinely been published
    (`STATUS_PRESENT`, the key exists in the written payload -- including a
    real, honestly-empty list) or never published at all
    (`STATUS_NOT_YET_PUBLISHED`, the topic file does not exist yet).

    `pass_` is `True` only when every one of `WORK_QUEUE_CATEGORIES` is
    `STATUS_PRESENT`. This never inspects `engine.py`/`gates.py`/`cli.py` --
    it is entirely a fact about what has actually been written to `blackboard`.
    """
    payload = blackboard.read(BLACKBOARD_WORK_QUEUE_TOPIC, default=None)
    value = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(value, dict):
        category_status = {category: STATUS_NOT_YET_PUBLISHED for category in WORK_QUEUE_CATEGORIES}
        return BlackboardWorkQueueEvaluation(category_status=category_status, pass_=False)

    category_status = {
        category: (STATUS_PRESENT if category in value else STATUS_NOT_YET_PUBLISHED)
        for category in WORK_QUEUE_CATEGORIES
    }
    pass_ = all(status == STATUS_PRESENT for status in category_status.values())
    return BlackboardWorkQueueEvaluation(category_status=category_status, pass_=pass_)
