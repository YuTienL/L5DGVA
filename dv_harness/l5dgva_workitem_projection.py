"""dv_harness/l5dgva_workitem_projection.py -- narrow "contract->workitem" first-hop
investigation for domain-audit A's C26/C30 clusters
(`.dv-harness/l5dgva_audit_A_orchestration_engines.txt`, `.dv-harness/l5dgva_audit_result_A.md`),
scoped strictly to V22 SS645/SS646
(`L5DGVA/L5_DGVA_v22_EXECUTION_ENFORCEMENT_Governing_Contract_Activation_Dispatch.md`) --
never the "->graph" hop, which needs real `graph.py` wiring and stays out of scope here.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- self-contained
apart from `l5dgva_gap_queue`, migrated identically to canonical in this same batch.

Primary contract text (read directly, not paraphrased):

    ## 645. Directive-to-Work-Item Compilation

    Compile multi-step directives into explicit work items.

    For V21 SS638, create semantic equivalents of: V21-EXEC-001 contract
    discovery V21-EXEC-002 inventory/hash/version V21-EXEC-003 full parse
    V21-EXEC-004 master registry V21-EXEC-005 dedup/inheritance/conflict
    V21-EXEC-006 effective set V21-EXEC-007 runtime mapping V21-EXEC-008
    coverage dashboard V21-EXEC-009 gap queue V21-EXEC-010 auto
    implementation V21-EXEC-011 tests V21-EXEC-012 governance replay
    V21-EXEC-013 coverage recalc V21-EXEC-014 closure loop V21-EXEC-015 KC
    operationalization V21-EXEC-016 checkpoint V21-EXEC-017 closure matrix
    V21-EXEC-018 Codex package V21-EXEC-019 no routine stop V21-EXEC-020 no
    premature COMPLETE V21-EXEC-021 genuine boundary handling.

    Required: `DirectiveWorkItemCompilation_PASS = true`

    ## 646. Work Item State Machine

    Every work item uses: DISCOVERED READY RUNNING BLOCKED_VALID
    FAILED_REPAIRABLE REPAIRING VALIDATING PASS.

    No silent DROPPED state.

    Required: `DirectiveWorkItemStateMachine_PASS = true`

FINDING (this module's own honest scope determination, not a paraphrase carried in from
elsewhere): `l5dgva_gap_queue.ClosureRow` (domain, cluster, requirement_ids, status, evidence,
confidence, notes) is NOT already a WorkItem in the V22 sense, and this is not a naming
coincidence to paper over. `ClosureRow.status` is `RuntimeStatus` -- a 12-value BUILT-vs-NOT
classification of one already-audited concept CLUSTER (~217 raw requirement IDs grouped into 35
rows; see `l5dgva_gap_queue.render_closure_matrix`'s own docstring on why the cluster, not the
requirement, is the unit). A V22 WorkItem is a per-DIRECTIVE dispatchable unit compiled from
`ExecutableDirectiveRegistry` (SS643: DirectiveId, SourceContract, SourceSection, DirectiveTextRef,
ActionType, Dependencies, RequiredEngine, GraphNode, Trigger, Gate, WorkItemIds, ExecutionState,
EvidenceRefs, Verdict) -- a registry domain-audit A's own C26 row confirms is
DOCUMENTED_NOT_IMPLEMENTED ("grep for Directive/WorkItem/GoverningContract/ContractIngestion ...
none implementing a directive registry, work-item compiler, or directive-to-graph dispatcher").
A ClosureRow also cannot honestly answer "what is this work item's LIVE execution progress": it is
produced by a point-in-time audit read of already-existing code, not by a dispatch engine actually
running work, so it can never truthfully claim READY, RUNNING, FAILED_REPAIRABLE, REPAIRING or
VALIDATING -- those require real, currently-nonexistent dispatch/agent evidence this module has no
way to manufacture honestly.

What IS real and narrow enough to build here -- the genuine overlap, not the whole pipeline:

  1. `WorkItemState` -- SS646's exact 8-value vocabulary, transcribed verbatim (never
     `RuntimeStatus` renamed; they are two structurally different axes, per the finding above).
  2. `project_runtime_status_to_workitem_state()` -- a narrow, total, honestly-bounded
     projection that only ever emits the 3 of 8 states a static audit classification can support
     without fabricating live-dispatch evidence: `PASS` (a `PASSING_STATUSES` row), `BLOCKED_VALID`
     (a `RuntimeStatus.BLOCKED` row -- SS646's own name for a validly-recorded block, consistent
     with this codebase's existing `question_queue.HUMAN_DECISION_SOURCE` discipline for a real
     block vs. a silent drop), or `DISCOVERED` (every other `GAP_STATUSES` row: a known, evidenced
     gap nothing has yet picked up for dispatch -- never guessed forward to READY/RUNNING/etc.).
  3. `closure_row_to_workitem_stub()` -- composes a WorkItem-SHAPED dict using only ClosureRow's
     own real fields for the identity/evidence portion (`work_item_id` from domain+cluster,
     `work_item_ids` from `requirement_ids`, `evidence_refs`, `execution_state`, `verdict`), and
     leaves every SS643 provenance/routing field (`source_contract`, `source_section`,
     `directive_text_ref`, `action_type`, `dependencies`, `required_engine`, `graph_node`,
     `trigger`, `gate`) explicitly `None` with one disclosed, shared reason string -- never a
     fabricated guess -- because a ClosureRow structurally carries no directive-provenance or
     graph-routing information. That is `ExecutableDirectiveRegistry`'s and Graph Dispatch's job
     (SS643/SS647), both correctly out of this narrow hop's scope.

This module does NOT implement `ExecutableDirectiveRegistry` (SS643), Graph Dispatch (SS647), or
any live state transition (`RUNNING`/`REPAIRING`/`VALIDATING`) -- those require the full V22
pipeline this investigation was told to stay out of. `DirectiveWorkItemCompilation_PASS` and
`DirectiveWorkItemStateMachine_PASS` stay honestly NOT_PROVEN/open at the full-contract level;
this module only proves, in real callable code, the narrow overlap that DOES already exist
between the audit's own `ClosureRow` output and V22's own vocabulary -- and discloses, rather than
hides, the exact fields and states it structurally cannot supply.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, FrozenSet

from .l5dgva_gap_queue import ClosureRow, PASSING_STATUSES, RuntimeStatus


class WorkItemState(str, Enum):
    """V22 SS646's work-item state machine, verbatim and in the contract's own order.
    Deliberately has no DROPPED value -- SS646 says "No silent DROPPED state", so this
    enum has nowhere to put one even by accident."""

    DISCOVERED = "DISCOVERED"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED_VALID = "BLOCKED_VALID"
    FAILED_REPAIRABLE = "FAILED_REPAIRABLE"
    REPAIRING = "REPAIRING"
    VALIDATING = "VALIDATING"
    PASS = "PASS"


#: The subset of `WorkItemState` a static, point-in-time `ClosureRow` audit classification
#: can honestly reach. The remaining 5 states (`READY`, `RUNNING`, `FAILED_REPAIRABLE`,
#: `REPAIRING`, `VALIDATING`) describe a unit of work actually being dispatched/executed --
#: evidence this module, and this codebase's current V22 implementation status, does not have.
STATICALLY_REACHABLE_STATES: FrozenSet[WorkItemState] = frozenset(
    {WorkItemState.DISCOVERED, WorkItemState.BLOCKED_VALID, WorkItemState.PASS}
)


def project_runtime_status_to_workitem_state(status: RuntimeStatus) -> WorkItemState:
    """`RuntimeStatus` (l5dgva_gap_queue's BUILT-vs-NOT audit classification) -> the one
    `WorkItemState` a ClosureRow carrying that status can honestly claim right now.

    Total over every `RuntimeStatus` value. Never returns anything outside
    `STATICALLY_REACHABLE_STATES` -- there is no branch here that could accidentally claim a
    live-dispatch state (`READY`/`RUNNING`/`FAILED_REPAIRABLE`/`REPAIRING`/`VALIDATING`) this
    module has no dispatch evidence to back.
    """
    if status in PASSING_STATUSES:
        return WorkItemState.PASS
    if status is RuntimeStatus.BLOCKED:
        return WorkItemState.BLOCKED_VALID
    return WorkItemState.DISCOVERED


#: Shared, honest reason string for every V22 SS643 `ExecutableDirectiveRegistry` field a
#: `ClosureRow` structurally cannot supply -- one real sentence, never a per-field invented guess.
UNAVAILABLE_FIELD_REASON = (
    "ClosureRow carries no directive-provenance/graph-routing evidence for this field; "
    "would require ExecutableDirectiveRegistry (V22 SS643, confirmed DOCUMENTED_NOT_IMPLEMENTED "
    "by domain-audit A cluster C26) or Graph Dispatch (V22 SS647), both out of this hop's scope."
)

#: SS643 `ExecutableDirectiveRegistry` fields a `ClosureRow` cannot honestly populate.
_UNAVAILABLE_DIRECTIVE_FIELDS = (
    "source_contract",
    "source_section",
    "directive_text_ref",
    "action_type",
    "dependencies",
    "required_engine",
    "graph_node",
    "trigger",
    "gate",
)


def closure_row_to_workitem_stub(row: ClosureRow) -> Dict[str, Any]:
    """One `ClosureRow` -> one WorkItem-SHAPED dict, honestly partial.

    Populated from ClosureRow's own real fields: `work_item_id` (a deterministic
    domain/cluster identity key), `work_item_ids` (the row's own `requirement_ids`),
    `execution_state` (via `project_runtime_status_to_workitem_state`), `verdict` (the row's
    own `RuntimeStatus` value, so no information is lost by the projection above), and
    `evidence_refs`.

    Every SS643 directive-provenance/graph-routing field this ClosureRow cannot supply is
    `None`, with `unavailable_field_reason` explaining why once rather than per-field --
    never filled with an invented value. This is a STUB, not a compiled
    `ExecutableDirectiveRegistry` entry: it proves the identity/evidence overlap that is real,
    and discloses, rather than hides, the rest.
    """
    state = project_runtime_status_to_workitem_state(row.status)
    stub: Dict[str, Any] = {
        "work_item_id": f"{row.domain}::{row.cluster}",
        "work_item_ids": list(row.requirement_ids),
        "execution_state": state.value,
        "verdict": row.status.value,
        "evidence_refs": [row.evidence] if row.evidence else [],
    }
    for field_name in _UNAVAILABLE_DIRECTIVE_FIELDS:
        stub[field_name] = None
    stub["unavailable_field_reason"] = UNAVAILABLE_FIELD_REASON
    return stub
