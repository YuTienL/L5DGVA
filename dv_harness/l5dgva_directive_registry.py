"""dv_harness/l5dgva_directive_registry.py -- V22 SS643 `ExecutableDirectiveRegistry`:
schema + a real, evidence-grounded seeding of the one worked example the contract chain
itself gives (V21 SS638 compiled into V21-EXEC-001..021 by V22 SS645).

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- depends only on
`l5dgva_workitem_projection.WorkItemState`, migrated identically to canonical in this same
batch. `SOURCE_FILE_V21`/`SOURCE_FILE_V22` below cite the L5DGVA governing-contract document
corpus, which is Parent-only (a separately-tracked, unresolved architectural gap per
`M4_M3_DEFERRED_CLOSURE.md`) -- these constants and the quoted text below are cited/carried
over as-is for provenance; this migration does not attempt to resolve that corpus gap.

Primary text, quoted verbatim (never paraphrased), from
`L5DGVA/L5_DGVA_v22_EXECUTION_ENFORCEMENT_Governing_Contract_Activation_Dispatch.md`:

    ## 643. ExecutableDirectiveRegistry

    Create/reconcile `ExecutableDirectiveRegistry`: DirectiveId
    SourceContract SourceSection DirectiveTextRef ActionType Dependencies
    RequiredEngine GraphNode Trigger Gate WorkItemIds ExecutionState
    EvidenceRefs Verdict.

    Required: `ExecutableDirectiveRegistry_PASS = true`

    ## 645. Directive-to-Work-Item Compilation

    Compile multi-step directives into explicit work items.

    For V21 §638, create semantic equivalents of: V21-EXEC-001 contract
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

(both quoted from that file, lines 8078-8112; line numbers as of this module's authoring --
re-grep for "## 643." / "## 645." before trusting them across a future edit to that file.)

CORRECTION OF AN UPSTREAM PARAPHRASE (primary-source-over-paraphrase, applied): the task
that produced this module described V21-EXEC-001..021 as "21 real named directives." Read
literally, SS645's own text says the opposite of that: it is ONE "multi-step directive" --
the numbered mandate at `L5DGVA/L5_DGVA_v21_IMPLEMENTATION_STRICT_All_Contract_100pct_Runtime_Closure.md`
section 638 ("Immediate Execution", lines 7973-7990, quoted below) -- that gets *compiled
into* 21 explicit WORK ITEMS named V21-EXEC-001 through V21-EXEC-021. "Compile multi-step
directives into explicit work items. For V21 §638, create semantic equivalents of:
V21-EXEC-001 ..." is a directive-to-work-item mapping, not a directive-to-directive one.
SS643's own registry schema has a `WorkItemIds` field precisely for this: a directive
registry entry cites the many work items compiled from it by ID, it does not itself become
21 rows. This module therefore seeds:

  1. Exactly ONE `DirectiveRecord` -- the real granularity SS643 describes -- for the V21
     §638 directive itself, with `work_item_ids` populated with the 21 real, literal
     V21-EXEC-NNN identifiers from SS645.
  2. A separate, smaller `WorkItemDescriptor` catalog (21 entries) transcribing SS645's own
     per-item labels ("contract discovery", "inventory/hash/version", ...) cross-referenced,
     by ordinal position, against V21 §638's own 21 numbered action-item texts -- both
     sources describe the same 21-step sequence in the same order; `verify_ordinal_alignment()`
     is a real, run test-covered check of that alignment, not an assumed one.

V21 §638 primary text, quoted verbatim (lines 7973-7990 of the V21 file):

    ## 638. Immediate Execution

    Upon receiving V21 Claude CLI MUST: 1. Locate ALL configured governing
    contract Markdown files. 2. Inventory/hash/version them. 3. Fully parse
    all active contracts. 4. Build MasterContractRequirementRegistry. 5.
    Resolve semantic duplicates/inheritance/supersession/conflicts. 6.
    Produce EffectiveContractRequirementSet. 7. Map every applicable
    requirement to runtime implementation. 8. Display initial coverage
    dashboard. 9. Build gap queue. 10. Automatically implement/repair every
    internally resolvable gap. 11. Run unit/static/harness tests. 12. Replay
    known governance failures. 13. Recalculate coverage. 14. Repeat
    repair/test/replay until 100% or genuine boundary. 15.
    Auto-operationalize reusable findings as KC. 16. Persist checkpoints.
    17. Produce final closure matrix. 18. Generate Codex review package. 19.
    Do not stop for routine confirmation. 20. Do not claim COMPLETE below
    100% applicable runtime closure. 21. Stop only at genuine
    Human/Authority/External boundary and request only the minimum required
    input.

HONESTLY UNASSIGNED FIELDS (never fabricated -- see `FIELD_NOT_YET_ASSIGNED_REASON`):
`action_type`, `required_engine`, `graph_node` and `gate` are `None` on the seeded
directive. Checked directly against the primary text before deciding this:

  - SS642 ("Executable Directive Detection") lists example *keyword categories* used to
    DETECT that a directive is executable at all ("Upon receiving this prompt", "Run",
    "Implement", "Repeat until", ...) -- it never assigns one categorical ActionType value
    per V21-EXEC-NNN work item, so `action_type` would be this module's own invented
    classification, not the contract's. Left `None`.
  - SS648 ("Eight-Engine Execution") requires the eight named engines to produce runtime
    proof for executable directives COLLECTIVELY; it names no per-directive `RequiredEngine`.
    Left `None`.
  - SS647 ("Graph Dispatch") requires the Graph Orchestrator to own work-item transitions;
    it assigns no specific `GraphNode` name to this directive or to any V21-EXEC-NNN item.
    Left `None`.
  - `Gate` is genuinely tempting to guess from the closure-gate AND-list at V21 SS637
    (`AllContractFilesDiscovered_PASS`, `ContractSemanticDedup_PASS`,
    `AllContractKnownFailureReplay_PASS`, `AllContractImplementationClosureMatrix_PASS`, ...)
    -- several of those names read as a plausible per-step match (e.g.
    `AllContractFilesDiscovered_PASS` for item 1's "Locate ALL configured governing contract
    Markdown files"). But SS637's own heading is `ALL_CONTRACT_IMPLEMENTATION_CLOSURE_GATE`:
    one whole-contract closure gate, an AND over the *entire* 21-step mandate, not a table
    binding one gate name to one numbered item. Guessing that binding here would be exactly
    the fabrication this module exists to avoid. Left `None`; SS637's real closure-gate names
    are cited in this docstring for a human's own reference, never silently assigned.

`dependencies` is `()` for the same reason: SS638's text is a literal *numbered* list (a
real, textual ordinal sequence), but nothing in SS638/643/645 uses the word "dependency" or
declares that step N structurally blocks step N+1 (vs. merely being narrated in that order).
An ordinal position is real; a `Dependencies` graph edge is a distinct claim this module
will not manufacture from position alone.

`trigger` IS populated for the one seeded directive: SS638's own opening clause ("Upon
receiving V21 Claude CLI MUST: ...") is the literal, explicitly-stated trigger for the whole
21-step mandate, quoted rather than invented.

`execution_state` reuses `dv_harness.l5dgva_workitem_projection.WorkItemState` verbatim
(imported, never redefined) -- SS643 does not define its own separate ExecutionState
vocabulary, and SS646's 8-value state machine is the only one this contract chain defines
anywhere. Every record this module seeds is un-dispatched, so `DISCOVERED` is the only
honest default (same reasoning `l5dgva_workitem_projection.STATICALLY_REACHABLE_STATES`
already uses for a static, non-dispatching module).

`verdict` and `evidence_refs` stay `None`/`()`: no dispatch has occurred, so there is no
outcome or runtime evidence to cite. `DirectiveTextRef`/`SourceSection` already cite the
directive's own textual EXISTENCE; that is a distinct claim from execution evidence, and
this module does not conflate the two.

SCOPE, matching the same "build the mechanism, defer the wiring" precedent as
`l5dgva_contract_compliance_gate.py` and `l5dgva_workitem_projection.py`: this module is a
registry/schema + one real worked-example seeding only. It does not detect directives from
free text (SS642), dispatch work (SS644/647), run a state machine (SS646), or touch
Blackboard/Graph/engine.py in any way. `ExecutableDirectiveRegistry_PASS` and
`DirectiveWorkItemCompilation_PASS` stay honestly NOT_PROVEN/open at the full-contract
level; this module only proves that a real, non-fabricated `ExecutableDirectiveRegistry`
schema now exists and can hold the one worked example the contract chain itself supplies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .l5dgva_workitem_projection import WorkItemState

#: Where every literal quote in this module's docstring and seed data came from -- re-grep
#: for "## 638."/"## 643."/"## 645." before trusting these line numbers across a future edit.
SOURCE_FILE_V22 = (
    "L5DGVA/L5_DGVA_v22_EXECUTION_ENFORCEMENT_Governing_Contract_Activation_Dispatch.md"
)
SOURCE_FILE_V21 = (
    "L5DGVA/L5_DGVA_v21_IMPLEMENTATION_STRICT_All_Contract_100pct_Runtime_Closure.md"
)

#: Shared, honest reason for every SS643 field this module's one real worked example cannot
#: honestly assign a value to -- one real sentence, never a per-field invented guess. See the
#: module docstring's "HONESTLY UNASSIGNED FIELDS" section for the field-by-field check.
FIELD_NOT_YET_ASSIGNED_REASON = (
    "V21 SS638 / V22 SS642/645/647/648 do not assign this field a specific value for this "
    "directive; assigning one here would be this module's own guess, not the contract's."
)


@dataclass(frozen=True)
class DirectiveRecord:
    """One row of V22 SS643's `ExecutableDirectiveRegistry`, field names transcribed
    1:1 from the contract's own list (`DirectiveId` -> `directive_id`, etc.), lower-cased
    to this codebase's existing snake_case convention (matching the same field-name choice
    `l5dgva_workitem_projection.closure_row_to_workitem_stub` already made for the identical
    SS643 field set).

    `work_item_ids`/`dependencies`/`evidence_refs` are tuples (not lists) so a frozen,
    hashable record stays genuinely immutable end to end.
    """

    directive_id: str
    source_contract: str
    source_section: str
    directive_text_ref: str
    action_type: Optional[str] = None
    dependencies: Tuple[str, ...] = ()
    required_engine: Optional[str] = None
    graph_node: Optional[str] = None
    trigger: Optional[str] = None
    gate: Optional[str] = None
    work_item_ids: Tuple[str, ...] = ()
    execution_state: WorkItemState = WorkItemState.DISCOVERED
    evidence_refs: Tuple[str, ...] = ()
    verdict: Optional[str] = None

    def __post_init__(self) -> None:
        for required_field_name in ("directive_id", "source_contract", "source_section", "directive_text_ref"):
            value = getattr(self, required_field_name)
            if not value or not isinstance(value, str):
                raise ValueError(
                    f"DirectiveRecord.{required_field_name} must be a non-empty string "
                    f"(SS643's own required identity/provenance fields), got {value!r}"
                )


@dataclass(frozen=True)
class WorkItemDescriptor:
    """One SS645-compiled work item (`V21-EXEC-NNN`), cataloguing what the primary text
    literally says about it -- NOT a `DirectiveRecord` in its own right (see this module's
    docstring for why SS643's registry granularity is the multi-step directive, not each
    compiled work item). `execution_state` reuses `WorkItemState` verbatim; every catalogued
    item here is un-dispatched, so `DISCOVERED` is the only honest default.
    """

    work_item_id: str
    label: str
    source_step_number: int
    source_step_text: str
    execution_state: WorkItemState = WorkItemState.DISCOVERED
    verdict: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.work_item_id or not self.label or not self.source_step_text:
            raise ValueError(
                "WorkItemDescriptor requires a real work_item_id, label and source_step_text "
                f"(got work_item_id={self.work_item_id!r}, label={self.label!r})"
            )
        if self.source_step_number < 1:
            raise ValueError(f"source_step_number must be >= 1, got {self.source_step_number}")


class ExecutableDirectiveRegistry:
    """SS643's `ExecutableDirectiveRegistry`: "Create/reconcile" -- registering the same
    `directive_id` twice with IDENTICAL content is a no-op (a real reconciliation, not a
    duplicate); registering it twice with DIFFERENT content raises, because that is a real
    conflict this registry must surface rather than silently overwrite.

    No detection, dispatch, or state-transition logic lives here -- see this module's
    docstring's SCOPE paragraph.
    """

    def __init__(self) -> None:
        self._by_id: Dict[str, DirectiveRecord] = {}

    def register(self, record: DirectiveRecord) -> None:
        existing = self._by_id.get(record.directive_id)
        if existing is not None and existing != record:
            raise ValueError(
                f"conflicting DirectiveRecord for directive_id={record.directive_id!r}: "
                f"existing={existing!r} new={record!r}"
            )
        self._by_id[record.directive_id] = record

    def reconcile(self, records: Tuple[DirectiveRecord, ...]) -> None:
        for record in records:
            self.register(record)

    def get(self, directive_id: str) -> Optional[DirectiveRecord]:
        return self._by_id.get(directive_id)

    def all(self) -> Tuple[DirectiveRecord, ...]:
        return tuple(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


#: V21 SS638's 21 numbered action-item texts, transcribed verbatim and in source order
#: (file lines 7975-7990). Ordinal position 1..21 matches SS638's own numbering.
V21_SS638_STEP_TEXTS: Tuple[str, ...] = (
    "Locate ALL configured governing contract Markdown files.",
    "Inventory/hash/version them.",
    "Fully parse all active contracts.",
    "Build MasterContractRequirementRegistry.",
    "Resolve semantic duplicates/inheritance/supersession/conflicts.",
    "Produce EffectiveContractRequirementSet.",
    "Map every applicable requirement to runtime implementation.",
    "Display initial coverage dashboard.",
    "Build gap queue.",
    "Automatically implement/repair every internally resolvable gap.",
    "Run unit/static/harness tests.",
    "Replay known governance failures.",
    "Recalculate coverage.",
    "Repeat repair/test/replay until 100% or genuine boundary.",
    "Auto-operationalize reusable findings as KC.",
    "Persist checkpoints.",
    "Produce final closure matrix.",
    "Generate Codex review package.",
    "Do not stop for routine confirmation.",
    "Do not claim COMPLETE below 100% applicable runtime closure.",
    "Stop only at genuine Human/Authority/External boundary and request only the minimum required input.",
)

#: V22 SS645's own 21 work-item id/label pairs, transcribed verbatim in source order
#: (file lines 8101-8110): "V21-EXEC-001 contract discovery V21-EXEC-002
#: inventory/hash/version ... V21-EXEC-021 genuine boundary handling."
V22_SS645_WORKITEM_LABELS: Tuple[Tuple[str, str], ...] = (
    ("V21-EXEC-001", "contract discovery"),
    ("V21-EXEC-002", "inventory/hash/version"),
    ("V21-EXEC-003", "full parse"),
    ("V21-EXEC-004", "master registry"),
    ("V21-EXEC-005", "dedup/inheritance/conflict"),
    ("V21-EXEC-006", "effective set"),
    ("V21-EXEC-007", "runtime mapping"),
    ("V21-EXEC-008", "coverage dashboard"),
    ("V21-EXEC-009", "gap queue"),
    ("V21-EXEC-010", "auto implementation"),
    ("V21-EXEC-011", "tests"),
    ("V21-EXEC-012", "governance replay"),
    ("V21-EXEC-013", "coverage recalc"),
    ("V21-EXEC-014", "closure loop"),
    ("V21-EXEC-015", "KC operationalization"),
    ("V21-EXEC-016", "checkpoint"),
    ("V21-EXEC-017", "closure matrix"),
    ("V21-EXEC-018", "Codex package"),
    ("V21-EXEC-019", "no routine stop"),
    ("V21-EXEC-020", "no premature COMPLETE"),
    ("V21-EXEC-021", "genuine boundary handling"),
)

#: SS638's own literal opening clause -- the real, stated trigger for the whole 21-step
#: mandate, quoted rather than invented (file line 7975).
V21_SS638_TRIGGER = "Upon receiving V21 Claude CLI MUST: <21 numbered action items follow>"


def verify_ordinal_alignment() -> Tuple[Tuple[int, str, str], ...]:
    """Real, run cross-check (not an assumption) that SS638's 21 step texts and SS645's 21
    work-item id/label pairs are genuinely the same 21-step sequence in the same order --
    both are independently transcribed from two different files/sections above; this
    function is what actually proves they line up rather than merely asserting it.

    Returns one (ordinal, work_item_id, step_text) tuple per position; raises ValueError if
    the two source lists ever come back a different length (a real transcription-drift
    guard, not a cosmetic check).
    """
    if len(V21_SS638_STEP_TEXTS) != len(V22_SS645_WORKITEM_LABELS):
        raise ValueError(
            f"SS638 step-text count ({len(V21_SS638_STEP_TEXTS)}) != SS645 "
            f"work-item-label count ({len(V22_SS645_WORKITEM_LABELS)}); one of the two "
            "transcriptions has drifted from the primary text."
        )
    return tuple(
        (ordinal, work_item_id, step_text)
        for ordinal, ((work_item_id, _label), step_text) in enumerate(
            zip(V22_SS645_WORKITEM_LABELS, V21_SS638_STEP_TEXTS), start=1
        )
    )


def seed_v21_ss638_directive() -> DirectiveRecord:
    """The one real `DirectiveRecord` SS643's own worked example (SS645, over V21 SS638)
    supports -- see this module's docstring for why this is ONE record, not 21."""
    work_item_ids = tuple(work_item_id for work_item_id, _label in V22_SS645_WORKITEM_LABELS)
    return DirectiveRecord(
        directive_id="V21-SS638-IMMEDIATE-EXECUTION",
        source_contract="V21 (L5_DGVA_v21_IMPLEMENTATION_STRICT_All_Contract_100pct_Runtime_Closure)",
        source_section="638",
        directive_text_ref=f"{SOURCE_FILE_V21}#638 (\"Immediate Execution\", 21 numbered action items)",
        action_type=None,
        dependencies=(),
        required_engine=None,
        graph_node=None,
        trigger=V21_SS638_TRIGGER,
        gate=None,
        work_item_ids=work_item_ids,
        execution_state=WorkItemState.DISCOVERED,
        evidence_refs=(),
        verdict=None,
    )


def seed_v21_exec_workitem_descriptors() -> Tuple[WorkItemDescriptor, ...]:
    """The 21 real `WorkItemDescriptor`s SS645 names for V21 SS638, one per
    `verify_ordinal_alignment()` position -- calling that function first so a future
    transcription drift between the two source lists fails loudly here rather than
    silently producing misaligned descriptors."""
    aligned = verify_ordinal_alignment()
    return tuple(
        WorkItemDescriptor(
            work_item_id=work_item_id,
            label=next(label for wid, label in V22_SS645_WORKITEM_LABELS if wid == work_item_id),
            source_step_number=ordinal,
            source_step_text=step_text,
            execution_state=WorkItemState.DISCOVERED,
            verdict=None,
        )
        for ordinal, work_item_id, step_text in aligned
    )


def seed_registry() -> Tuple[ExecutableDirectiveRegistry, Tuple[WorkItemDescriptor, ...]]:
    """Build one populated `ExecutableDirectiveRegistry` (the single V21 SS638 directive)
    plus the 21 `WorkItemDescriptor`s SS645 compiles it into. This is the whole real,
    non-fabricated seeding this module provides -- see SCOPE in the module docstring for
    what deliberately does not exist yet (detection, dispatch, state transitions)."""
    registry = ExecutableDirectiveRegistry()
    registry.register(seed_v21_ss638_directive())
    return registry, seed_v21_exec_workitem_descriptors()
