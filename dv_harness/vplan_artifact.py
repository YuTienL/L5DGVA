"""dv_harness/vplan_artifact.py -- a vPlan schema + hierarchy + a NINE-dimension
completeness analysis, never collapsed to one number, plus a fifteen-value gap
taxonomy wired through the real `inference.next_best_action()` Gap ->
Next-Best-Action engine through a NEW `VPLAN_GAP_ACTION_CATALOG` this module
defines.

THE GAP THIS CLOSES
-------------------
A vPlan (verification plan) is a hierarchy of rows -- sections, features, and
leaf verification items -- each of which should carry a requirement link, a
verification method, a coverage/checker/test linkage, an owner and a
priority. Nothing in this repo turned that shape into a checkable artifact:
a repo-wide grep for `vplan_artifact`/`VPlanCompletenessReport` before this
change matched nothing, and the closest existing mechanism,
`env_manifest.py`'s `testplan_correspondence`, answers a narrower, DIFFERENT
question -- "does a name-matched join of an EXISTING testlist/vPlan/coverage
model line up" -- over a project's own real `env.manifest.json`. It has no
notion of vPlan HIERARCHY (parent/child rows), no independent per-dimension
status (it reports LINKED/PARTIAL/NOT_CHECKED per testplan item, one axis),
and no gap taxonomy or next-best-action wiring at all.

WHY THIS TAKES GENERIC dict/list INPUT RATHER THAN IMPORTING A REAL PRODUCER
-----------------------------------------------------------------------------
Per this batch's file-safety scope, this module must not import
`spec_intelligence.py` or `verification_intent_ir.py` -- both are owned by
OTHER, concurrently-running tasks in this same batch, and importing a module
mid-edit by a sibling task is exactly the drift this project's Reuse-Over-
Reinvent rule is meant to prevent, not encourage. So `vplan_rows`,
`requirements` and `verification_intents` are accepted as plain
dict/list parameters -- the generic shape any real producer's OUTPUT would
already have to be reducible to before a downstream consumer could read it.
Once either of those modules lands, its own real record objects can be
converted to these same plain dicts (documented at each cross-check
function below) with NO change to this module's own logic -- this module is
independently testable today and does not need to wait on, or guess at,
either sibling's still-moving internal shape.

WHAT IS REUSED, NOT RE-MINTED
------------------------------
  * `subsystem_discovery`'s READY/PARTIAL/BLOCKED/UNKNOWN readiness words
    (imported as `READY`/`PARTIAL`/`BLOCKED`/`UNKNOWN`/`READINESS_CLASSES`),
    the same four words `golden_flow_readiness.py`, `generation_readiness.py`
    and `system_readiness.py` already reuse rather than minting a fifth
    vocabulary for "is this dimension connected with evidence".
  * `verification_strategy.STRATEGIES` (SIMULATION/FORMAL/PSS/EMULATION/
    FPGA_PROTOTYPE) as the known verification-method vocabulary -- the real,
    already-derived-from-code strategy list this harness maintains, rather
    than inventing a second spelling of "what kind of verification is this".
  * `memory.CORNER_CASE_RISK_TIERS` (P0..P3) as the priority vocabulary --
    the same reuse `requirement_contract.py`'s own `priority` field already
    makes, so this repo keeps one P0..P3 vocabulary rather than two.
  * `inference.next_best_action()` through its `gap_action_catalog`
    parameter -- the domain-neutral Gap -> Next-Best-Action engine section 10
    of the master prompt forbids re-implementing. `VPLAN_GAP_ACTION_CATALOG`
    is the one genuinely new artifact this wiring needs: a lookup table, not
    an engine.
  * `connectivity.render_markdown_table()` -- this repo's only parameterized
    table renderer -- for the optional markdown render of the 9-dimension
    matrix, rather than a second hand-rolled `"| " + " | ".join(...)` loop.

WHAT IS GENUINELY NEW
----------------------
  * The vPlan row SCHEMA itself (`validate_vplan_row`/`validate_vplan_document`)
    -- nothing in this repo had a vPlan row shape as a checkable contract.
  * The HIERARCHY builder (`build_vplan_hierarchy`) -- duplicate-id, orphan-
    parent-reference and cycle detection over a vPlan's own parent_id links.
    Nothing here is a graph library import: it is the same small,
    single-parent-pointer tree-walk shape `system_scheduling_plan.py` and
    `subsystem_command_contract.py` already use for their own hierarchies,
    applied to vPlan rows.
  * The NINE-dimension completeness analysis
    (`analyze_vplan_completeness`/`VPlanCompletenessReport`). Each dimension
    is scored, gapped and reasoned about INDEPENDENTLY and none is averaged,
    weighted or folded into a single score -- the same non-collapsing-status
    discipline `requirement_contract.py`'s five-value status vocabulary and
    `golden_flow_readiness.py`'s per-row Status column already hold. A vPlan
    can be READY on ownership and BLOCKED on hierarchy integrity at the same
    time, and a caller reading only one dimension must never mistake it for
    the whole picture.
  * The FIFTEEN-value gap taxonomy (`GAP_TAXONOMY`) -- one code per concrete,
    independently-detectable defect a vPlan can carry, each mapped to
    exactly one of the nine dimensions (`GAP_TO_DIMENSION`) and to a
    severity (`GAP_SEVERITY`) that decides whether it can make a dimension
    BLOCKED rather than merely PARTIAL.

DELIBERATELY BOUNDED, STATED RATHER THAN IMPLIED CLOSED
---------------------------------------------------------
  * This module reads a vPlan RECORD (plus optional requirement/intent
    records for cross-checking). It does NOT parse a specification, does
    NOT extract vPlan rows from prose, and does NOT check a vPlan against
    RTL, a register map, or a real coverage database -- those are
    `spec_intelligence.py`/`verification_intent_ir.py`/`env_manifest.py`'s
    jobs, not this one.
  * Coverage-model/checker/test-stimulus linkage (dimensions 4-6) is
    evaluated ONLY over leaf rows whose declared `verification_method` is one
    of `DYNAMIC_COVERAGE_METHODS` (SIMULATION/EMULATION/PSS for coverage and
    checker linkage; SIMULATION/EMULATION for test-stimulus linkage --
    PSS-generated stimulus is not itself a pre-existing "test" to cite). A
    FORMAL or FPGA_PROTOTYPE item, or a leaf with no declared method at all,
    is honestly excluded from those three dimensions' applicable set rather
    than being scored PARTIAL against a linkage kind that method does not
    use -- and if that leaves a dimension's applicable set empty, the
    dimension reports UNKNOWN with the real reason, never a fabricated
    READY over zero applicable rows.
  * `requirements` and `verification_intents` are cross-checked ONLY when the
    caller supplies them (`None` means "not evaluated", reported UNKNOWN with
    a real reason, never silently treated as "nothing to report" or as a
    clean pass).
  * It DECIDES, APPROVES and RUNS nothing: no stage executes, no gate script
    is invoked, no file is written by `analyze_vplan_completeness()` itself,
    and there is deliberately no stage gate -- a completeness report is an
    input to a human's vPlan-review decision, never a substitute for one.
    `ControlPlane.approve()`, `policy.can_signoff()`,
    `assert_human_approval()` and the PR-only main/master governance are
    untouched and unreferenced.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import subsystem_discovery as sd
from .inference import next_best_action
from .memory import CORNER_CASE_RISK_TIERS
from .verification_strategy import STRATEGIES

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Reused vocabularies -- see module docstring for why each is imported rather
# than re-typed.
# ---------------------------------------------------------------------------
READY = sd.READY
PARTIAL = sd.PARTIAL
BLOCKED = sd.BLOCKED
UNKNOWN = sd.UNKNOWN
READINESS_CLASSES: Tuple[str, ...] = sd.READINESS_CLASSES

#: The known verification-method vocabulary, reused verbatim from
#: `verification_strategy.STRATEGIES` rather than re-typed. A vPlan row
#: declaring anything outside this tuple is `GAP_UNKNOWN_VERIFICATION_METHOD`.
KNOWN_VERIFICATION_METHODS: Tuple[str, ...] = tuple(STRATEGIES)

#: The subset of `KNOWN_VERIFICATION_METHODS` whose dynamic execution
#: legitimately produces coverage bins and needs a checking mechanism.
#: FORMAL (a property proof, not a coverage-bearing run) and FPGA_PROTOTYPE
#: (this harness models no coverage-collection path for it) are deliberately
#: excluded -- see the module docstring's bounded-scope section.
COVERAGE_AND_CHECKER_RELEVANT_METHODS: Tuple[str, ...] = ("SIMULATION", "EMULATION", "PSS")

#: The subset that cites a pre-existing, runnable "test": PSS is excluded
#: because a PSS model GENERATES per-target scenario tests rather than
#: citing one that already exists (see `verification_strategy.py`'s own
#: `StrategyBackend` for PSS).
TEST_STIMULUS_RELEVANT_METHODS: Tuple[str, ...] = ("SIMULATION", "EMULATION")

#: Priority vocabulary, reused verbatim from `memory.CORNER_CASE_RISK_TIERS`
#: -- the same P0..P3 scale `requirement_contract.py`'s own `priority` field
#: already uses, so this repo keeps one priority vocabulary rather than two.
PRIORITY_VALUES: Tuple[str, ...] = tuple(CORNER_CASE_RISK_TIERS)


class VPlanArtifactError(ValueError):
    """Base error for this module. Raised, never a False/None return, per
    this project's fail-closed convention for a genuinely malformed shape."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


class VPlanArtifactValidationError(VPlanArtifactError):
    """A vPlan row (or the whole document) does not satisfy the schema this
    module defines. Raised only for a STRUCTURAL defect (wrong type, missing
    required field) -- a SEMANTIC defect that is still shape-valid (a
    duplicate id, an orphan parent reference, a missing owner) is reported as
    a gap by `analyze_vplan_completeness()` instead, never raised."""


# ===========================================================================
# vPlan row schema
# ===========================================================================

#: The vPlan row's own fields, in this module's canonical order. `id` and
#: `parent_id` describe the HIERARCHY; the rest describe one row's
#: completeness. A row with no `parent_id` is a hierarchy root.
VPLAN_ROW_FIELDS: Tuple[str, ...] = (
    "id", "parent_id", "title", "requirement_refs", "verification_method",
    "coverage_refs", "checker_refs", "test_refs", "owner", "priority",
    "verification_intent_ref",
)

#: Fields whose value, when present, must be a list of non-empty strings.
_STRING_LIST_FIELDS: Tuple[str, ...] = (
    "requirement_refs", "coverage_refs", "checker_refs", "test_refs",
)

#: Fields whose value, when present, must be a non-empty string.
_OPTIONAL_STRING_FIELDS: Tuple[str, ...] = (
    "parent_id", "title", "verification_method", "owner", "priority",
    "verification_intent_ref",
)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_vplan_row(row: Any, *, index: Optional[int] = None) -> None:
    """Validate ONE vPlan row against this module's schema. Raises
    `VPlanArtifactValidationError` naming the row's index (when known) and
    the exact defect. Checks STRUCTURE only -- see the module docstring for
    why a duplicate id / orphan parent / missing owner is a reported gap
    rather than a validation failure."""
    where = {"row_index": index}
    if not isinstance(row, Mapping):
        raise VPlanArtifactValidationError("VPLAN_ROW_NOT_A_MAPPING", dict(where, got=type(row).__name__))
    row_id = row.get("id")
    if not _is_nonempty_str(row_id):
        raise VPlanArtifactValidationError("VPLAN_ROW_MISSING_ID", dict(where, got=row_id))
    where = dict(where, row_id=row_id)
    for key in _OPTIONAL_STRING_FIELDS:
        if key in row and row[key] is not None and not _is_nonempty_str(row[key]):
            raise VPlanArtifactValidationError(
                "VPLAN_ROW_FIELD_NOT_A_STRING", dict(where, field=key, got=row[key]))
    for key in _STRING_LIST_FIELDS:
        if key not in row or row[key] is None:
            continue
        value = row[key]
        if not isinstance(value, list) or not all(_is_nonempty_str(v) for v in value):
            raise VPlanArtifactValidationError(
                "VPLAN_ROW_FIELD_NOT_A_STRING_LIST", dict(where, field=key, got=value))


def validate_vplan_document(vplan_rows: Any) -> None:
    """Validate a whole vPlan (a list of rows). Raises
    `VPlanArtifactValidationError` on the first structural defect found."""
    if not isinstance(vplan_rows, list):
        raise VPlanArtifactValidationError(
            "VPLAN_DOCUMENT_NOT_A_LIST", {"got": type(vplan_rows).__name__})
    for index, row in enumerate(vplan_rows):
        validate_vplan_row(row, index=index)


# ===========================================================================
# Hierarchy
# ===========================================================================

def build_vplan_hierarchy(vplan_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the vPlan's parent/child hierarchy and detect the three
    structural defects a single-parent-pointer tree can carry: a duplicate
    id, a parent reference to an id that does not exist, and a cycle. Never
    raises on a semantic defect -- each is reported as a gap dict in the
    returned `gaps` list, following this module's own severity/dimension
    taxonomy (`GAP_DUPLICATE_ROW_ID`/`GAP_ORPHAN_PARENT_REF`/
    `GAP_CYCLIC_HIERARCHY`, all `DIM_HIERARCHY_INTEGRITY`).

    Assumes `validate_vplan_document()` already cleared the input -- this
    function does not re-check row shape.
    """
    gaps: List[Dict[str, Any]] = []
    seen_ids: Dict[str, int] = {}
    canonical_row: Dict[str, Mapping[str, Any]] = {}
    duplicate_ids: List[str] = []
    for row in vplan_rows:
        row_id = row["id"]
        seen_ids[row_id] = seen_ids.get(row_id, 0) + 1
        if row_id not in canonical_row:
            canonical_row[row_id] = row

    for row_id, count in seen_ids.items():
        if count > 1:
            duplicate_ids.append(row_id)
            gaps.append({
                "gap": GAP_DUPLICATE_ROW_ID, "dimension": DIM_HIERARCHY_INTEGRITY,
                "row_id": row_id,
                "detail": f"id '{row_id}' appears {count} times in the vPlan document",
            })
    duplicate_ids.sort()

    distinct_ids: List[str] = list(canonical_row.keys())
    id_set = set(distinct_ids)
    parent_of: Dict[str, Optional[str]] = {}
    orphan_ids: List[str] = []
    for row_id in distinct_ids:
        parent_id = canonical_row[row_id].get("parent_id")
        if parent_id is None:
            parent_of[row_id] = None
            continue
        if parent_id not in id_set:
            orphan_ids.append(row_id)
            gaps.append({
                "gap": GAP_ORPHAN_PARENT_REF, "dimension": DIM_HIERARCHY_INTEGRITY,
                "row_id": row_id,
                "detail": f"row '{row_id}' declares parent_id '{parent_id}', which is not "
                          "the id of any row in this vPlan document",
            })
            parent_of[row_id] = None  # treated as a root for tree-walk purposes
            continue
        parent_of[row_id] = parent_id
    orphan_ids.sort()

    # Cycle detection over the (now orphan-free) parent-pointer function --
    # each id has at most one parent, so a cycle is found by following
    # parent pointers and watching for a revisit within the CURRENT walk.
    color: Dict[str, int] = {}  # 0/absent=unvisited, 1=in-progress, 2=resolved
    cycle_ids: List[str] = []
    for start in distinct_ids:
        if color.get(start, 0) != 0:
            continue
        path: List[str] = []
        node: Optional[str] = start
        while node is not None and color.get(node, 0) == 0:
            color[node] = 1
            path.append(node)
            node = parent_of.get(node)
        if node is not None and color.get(node) == 1:
            cycle_start = path.index(node)
            cycle_ids.extend(path[cycle_start:])
        for n in path:
            color[n] = 2
    cycle_ids = sorted(set(cycle_ids))
    for row_id in cycle_ids:
        gaps.append({
            "gap": GAP_CYCLIC_HIERARCHY, "dimension": DIM_HIERARCHY_INTEGRITY,
            "row_id": row_id,
            "detail": f"row '{row_id}' is part of a parent_id cycle",
        })

    children_of: Dict[str, List[str]] = {rid: [] for rid in distinct_ids}
    for rid, parent_id in parent_of.items():
        if parent_id is not None:
            children_of[parent_id].append(rid)
    roots = sorted(rid for rid, parent_id in parent_of.items() if parent_id is None)
    leaves = sorted(rid for rid in distinct_ids if not children_of[rid])

    return {
        "distinct_ids": distinct_ids,
        "duplicate_ids": duplicate_ids,
        "orphan_ids": orphan_ids,
        "cycle_ids": cycle_ids,
        "roots": roots,
        "leaves": leaves,
        "children_of": children_of,
        "canonical_row": canonical_row,
        "gaps": gaps,
    }


# ===========================================================================
# The nine completeness dimensions -- see module docstring: never collapsed.
# ===========================================================================

DIM_HIERARCHY_INTEGRITY = "HIERARCHY_INTEGRITY"
DIM_REQUIREMENT_COVERAGE = "REQUIREMENT_COVERAGE"
DIM_VERIFICATION_METHOD_ASSIGNMENT = "VERIFICATION_METHOD_ASSIGNMENT"
DIM_COVERAGE_MODEL_LINKAGE = "COVERAGE_MODEL_LINKAGE"
DIM_CHECKER_LINKAGE = "CHECKER_LINKAGE"
DIM_TEST_STIMULUS_LINKAGE = "TEST_STIMULUS_LINKAGE"
DIM_OWNERSHIP_ASSIGNMENT = "OWNERSHIP_ASSIGNMENT"
DIM_PRIORITY_ASSIGNMENT = "PRIORITY_ASSIGNMENT"
DIM_INTENT_CROSS_CONSISTENCY = "INTENT_CROSS_CONSISTENCY"

DIMENSIONS: Tuple[str, ...] = (
    DIM_HIERARCHY_INTEGRITY, DIM_REQUIREMENT_COVERAGE,
    DIM_VERIFICATION_METHOD_ASSIGNMENT, DIM_COVERAGE_MODEL_LINKAGE,
    DIM_CHECKER_LINKAGE, DIM_TEST_STIMULUS_LINKAGE, DIM_OWNERSHIP_ASSIGNMENT,
    DIM_PRIORITY_ASSIGNMENT, DIM_INTENT_CROSS_CONSISTENCY,
)

DIMENSION_DEFINITIONS: Dict[str, str] = {
    DIM_HIERARCHY_INTEGRITY: "every row id is unique, every parent_id resolves to a real "
        "row, and no row is part of a parent_id cycle",
    DIM_REQUIREMENT_COVERAGE: "every supplied requirement is referenced by at least one "
        "vPlan row, and every row's requirement reference resolves to a supplied requirement",
    DIM_VERIFICATION_METHOD_ASSIGNMENT: "every leaf vPlan item declares a recognized "
        "verification_method",
    DIM_COVERAGE_MODEL_LINKAGE: "every leaf item whose method is coverage-relevant "
        "(SIMULATION/EMULATION/PSS) cites at least one coverage_ref",
    DIM_CHECKER_LINKAGE: "every leaf item whose method is coverage-relevant "
        "(SIMULATION/EMULATION/PSS) cites at least one checker_ref",
    DIM_TEST_STIMULUS_LINKAGE: "every leaf item whose method cites a pre-existing test "
        "(SIMULATION/EMULATION) cites at least one test_ref",
    DIM_OWNERSHIP_ASSIGNMENT: "every leaf vPlan item names an owner",
    DIM_PRIORITY_ASSIGNMENT: "every leaf vPlan item declares a recognized priority (P0..P3)",
    DIM_INTENT_CROSS_CONSISTENCY: "every supplied verification intent is referenced by at "
        "least one row, every row's intent reference resolves to a supplied intent, and a "
        "row's declared method never contradicts its cited intent's declared method",
}


# ===========================================================================
# The fifteen-value gap taxonomy
# ===========================================================================

GAP_DUPLICATE_ROW_ID = "DUPLICATE_ROW_ID"
GAP_ORPHAN_PARENT_REF = "ORPHAN_PARENT_REF"
GAP_CYCLIC_HIERARCHY = "CYCLIC_HIERARCHY"
GAP_UNMAPPED_REQUIREMENT = "UNMAPPED_REQUIREMENT"
GAP_DANGLING_REQUIREMENT_REF = "DANGLING_REQUIREMENT_REF"
GAP_MISSING_VERIFICATION_METHOD = "MISSING_VERIFICATION_METHOD"
GAP_UNKNOWN_VERIFICATION_METHOD = "UNKNOWN_VERIFICATION_METHOD"
GAP_MISSING_COVERAGE_LINK = "MISSING_COVERAGE_LINK"
GAP_MISSING_CHECKER_LINK = "MISSING_CHECKER_LINK"
GAP_MISSING_TEST_LINK = "MISSING_TEST_LINK"
GAP_MISSING_OWNER = "MISSING_OWNER"
GAP_MISSING_PRIORITY = "MISSING_PRIORITY"
GAP_UNREFERENCED_VERIFICATION_INTENT = "UNREFERENCED_VERIFICATION_INTENT"
GAP_DANGLING_INTENT_REF = "DANGLING_INTENT_REF"
GAP_INTENT_METHOD_CONTRADICTION = "INTENT_METHOD_CONTRADICTION"

GAP_TAXONOMY: Tuple[str, ...] = (
    GAP_DUPLICATE_ROW_ID, GAP_ORPHAN_PARENT_REF, GAP_CYCLIC_HIERARCHY,
    GAP_UNMAPPED_REQUIREMENT, GAP_DANGLING_REQUIREMENT_REF,
    GAP_MISSING_VERIFICATION_METHOD, GAP_UNKNOWN_VERIFICATION_METHOD,
    GAP_MISSING_COVERAGE_LINK, GAP_MISSING_CHECKER_LINK, GAP_MISSING_TEST_LINK,
    GAP_MISSING_OWNER, GAP_MISSING_PRIORITY,
    GAP_UNREFERENCED_VERIFICATION_INTENT, GAP_DANGLING_INTENT_REF,
    GAP_INTENT_METHOD_CONTRADICTION,
)

GAP_DEFINITIONS: Dict[str, str] = {
    GAP_DUPLICATE_ROW_ID: "the same row id appears more than once in the vPlan document",
    GAP_ORPHAN_PARENT_REF: "a row's parent_id does not match any row's id",
    GAP_CYCLIC_HIERARCHY: "a row's parent_id chain loops back to itself",
    GAP_UNMAPPED_REQUIREMENT: "a supplied requirement is not referenced by any vPlan row",
    GAP_DANGLING_REQUIREMENT_REF: "a row cites a requirement id absent from the supplied "
        "requirements list -- a false traceability claim, not merely an absent one",
    GAP_MISSING_VERIFICATION_METHOD: "a leaf vPlan item declares no verification_method",
    GAP_UNKNOWN_VERIFICATION_METHOD: "a leaf item's verification_method is not one of "
        "verification_strategy.STRATEGIES",
    GAP_MISSING_COVERAGE_LINK: "a coverage-relevant leaf item cites no coverage_ref",
    GAP_MISSING_CHECKER_LINK: "a coverage-relevant leaf item cites no checker_ref",
    GAP_MISSING_TEST_LINK: "a test-citing leaf item cites no test_ref",
    GAP_MISSING_OWNER: "a leaf vPlan item names no owner",
    GAP_MISSING_PRIORITY: "a leaf vPlan item declares no priority, or one outside P0..P3",
    GAP_UNREFERENCED_VERIFICATION_INTENT: "a supplied verification intent is not "
        "referenced by any vPlan row",
    GAP_DANGLING_INTENT_REF: "a row cites a verification_intent_ref absent from the "
        "supplied verification_intents list",
    GAP_INTENT_METHOD_CONTRADICTION: "a row's verification_method disagrees with its "
        "cited verification intent's own declared method",
}

#: Every gap maps to exactly one of the nine dimensions -- checked totally by
#: `assert_gap_taxonomy_total()` at import time.
GAP_TO_DIMENSION: Dict[str, str] = {
    GAP_DUPLICATE_ROW_ID: DIM_HIERARCHY_INTEGRITY,
    GAP_ORPHAN_PARENT_REF: DIM_HIERARCHY_INTEGRITY,
    GAP_CYCLIC_HIERARCHY: DIM_HIERARCHY_INTEGRITY,
    GAP_UNMAPPED_REQUIREMENT: DIM_REQUIREMENT_COVERAGE,
    GAP_DANGLING_REQUIREMENT_REF: DIM_REQUIREMENT_COVERAGE,
    GAP_MISSING_VERIFICATION_METHOD: DIM_VERIFICATION_METHOD_ASSIGNMENT,
    GAP_UNKNOWN_VERIFICATION_METHOD: DIM_VERIFICATION_METHOD_ASSIGNMENT,
    GAP_MISSING_COVERAGE_LINK: DIM_COVERAGE_MODEL_LINKAGE,
    GAP_MISSING_CHECKER_LINK: DIM_CHECKER_LINKAGE,
    GAP_MISSING_TEST_LINK: DIM_TEST_STIMULUS_LINKAGE,
    GAP_MISSING_OWNER: DIM_OWNERSHIP_ASSIGNMENT,
    GAP_MISSING_PRIORITY: DIM_PRIORITY_ASSIGNMENT,
    GAP_UNREFERENCED_VERIFICATION_INTENT: DIM_INTENT_CROSS_CONSISTENCY,
    GAP_DANGLING_INTENT_REF: DIM_INTENT_CROSS_CONSISTENCY,
    GAP_INTENT_METHOD_CONTRADICTION: DIM_INTENT_CROSS_CONSISTENCY,
}

#: Whether a gap can make its dimension BLOCKED (a structural defect or a
#: FALSE claim) versus merely PARTIAL (an honest absence). See the module
#: docstring's "never a fabricated READY" note -- this ranking is what makes
#: e.g. a dangling requirement reference worse than an unmapped requirement.
GAP_SEVERITY: Dict[str, str] = {
    GAP_DUPLICATE_ROW_ID: BLOCKED,
    GAP_ORPHAN_PARENT_REF: BLOCKED,
    GAP_CYCLIC_HIERARCHY: BLOCKED,
    GAP_UNMAPPED_REQUIREMENT: PARTIAL,
    GAP_DANGLING_REQUIREMENT_REF: BLOCKED,
    GAP_MISSING_VERIFICATION_METHOD: PARTIAL,
    GAP_UNKNOWN_VERIFICATION_METHOD: BLOCKED,
    GAP_MISSING_COVERAGE_LINK: PARTIAL,
    GAP_MISSING_CHECKER_LINK: PARTIAL,
    GAP_MISSING_TEST_LINK: PARTIAL,
    GAP_MISSING_OWNER: PARTIAL,
    GAP_MISSING_PRIORITY: PARTIAL,
    GAP_UNREFERENCED_VERIFICATION_INTENT: PARTIAL,
    GAP_DANGLING_INTENT_REF: BLOCKED,
    GAP_INTENT_METHOD_CONTRADICTION: BLOCKED,
}


def assert_gap_taxonomy_total() -> None:
    """Import-time guard: every gap code has exactly one dimension and one
    severity, every dimension has at least one gap code, and the taxonomy is
    really fifteen values -- so a future edit that adds a gap without wiring
    it fails a test rather than silently reporting `UNKNOWN` severity."""
    if len(GAP_TAXONOMY) != 15:
        raise VPlanArtifactError("GAP_TAXONOMY_WRONG_SIZE", {"size": len(GAP_TAXONOMY)})
    if set(GAP_TAXONOMY) != set(GAP_DEFINITIONS):
        raise VPlanArtifactError("GAP_TAXONOMY_DEFINITIONS_MISMATCH", {
            "taxonomy_only": sorted(set(GAP_TAXONOMY) - set(GAP_DEFINITIONS)),
            "definitions_only": sorted(set(GAP_DEFINITIONS) - set(GAP_TAXONOMY)),
        })
    if set(GAP_TAXONOMY) != set(GAP_TO_DIMENSION):
        raise VPlanArtifactError("GAP_TAXONOMY_DIMENSION_MAPPING_INCOMPLETE", {
            "taxonomy_only": sorted(set(GAP_TAXONOMY) - set(GAP_TO_DIMENSION)),
            "mapping_only": sorted(set(GAP_TO_DIMENSION) - set(GAP_TAXONOMY)),
        })
    if set(GAP_TAXONOMY) != set(GAP_SEVERITY):
        raise VPlanArtifactError("GAP_TAXONOMY_SEVERITY_MAPPING_INCOMPLETE", {
            "taxonomy_only": sorted(set(GAP_TAXONOMY) - set(GAP_SEVERITY)),
            "mapping_only": sorted(set(GAP_SEVERITY) - set(GAP_TAXONOMY)),
        })
    bad_severity = {g: v for g, v in GAP_SEVERITY.items() if v not in (BLOCKED, PARTIAL)}
    if bad_severity:
        raise VPlanArtifactError("GAP_SEVERITY_NOT_BLOCKED_OR_PARTIAL", {"bad": bad_severity})
    dims_with_gaps = set(GAP_TO_DIMENSION.values())
    missing_dims = set(DIMENSIONS) - dims_with_gaps
    if missing_dims:
        raise VPlanArtifactError("DIMENSION_WITH_NO_GAP_CODE", {"dimensions": sorted(missing_dims)})
    extra_dims = dims_with_gaps - set(DIMENSIONS)
    if extra_dims:
        raise VPlanArtifactError("GAP_MAPS_TO_UNKNOWN_DIMENSION", {"dimensions": sorted(extra_dims)})


assert_gap_taxonomy_total()


# ===========================================================================
# Gap -> Next-Best-Action catalog, driven through the REAL
# `inference.next_best_action()` -- see module docstring for why this is a
# lookup table and not a second engine.
# ===========================================================================

VPLAN_GAP_ACTION_CATALOG: Dict[str, Any] = {
    "source": "vplan_artifact",
    "fallback": (
        "no next action is registered for '{gap}' -- this indicates a taxonomy/catalog "
        "drift in vplan_artifact.py itself; report it rather than acting on a guess"
    ),
    "actions": {
        GAP_DUPLICATE_ROW_ID: (
            "rename or merge the duplicate row so every vPlan row id is unique before "
            "this vPlan is used for traceability"),
        GAP_ORPHAN_PARENT_REF: (
            "fix the row's parent_id to a real row id, or clear it to make the row a "
            "hierarchy root"),
        GAP_CYCLIC_HIERARCHY: (
            "break the parent_id cycle -- at least one row in the cycle must point to a "
            "row outside it, or to no parent at all"),
        GAP_UNMAPPED_REQUIREMENT: (
            "add a vPlan row (or a requirement_refs entry on an existing row) that "
            "verifies this requirement, or record why it is deliberately out of scope"),
        GAP_DANGLING_REQUIREMENT_REF: (
            "correct the row's requirement_refs entry to a requirement id that is really "
            "in the supplied requirements list, or add the missing requirement record"),
        GAP_MISSING_VERIFICATION_METHOD: (
            "declare a verification_method for this leaf item, one of "
            f"{', '.join(KNOWN_VERIFICATION_METHODS)}"),
        GAP_UNKNOWN_VERIFICATION_METHOD: (
            "correct verification_method to one of "
            f"{', '.join(KNOWN_VERIFICATION_METHODS)} (verification_strategy.STRATEGIES)"),
        GAP_MISSING_COVERAGE_LINK: (
            "cite at least one coverage_ref for this item, or move it off a "
            "coverage-relevant verification_method if none applies"),
        GAP_MISSING_CHECKER_LINK: (
            "cite at least one checker_ref for this item -- what mechanism decides "
            "pass/fail for it"),
        GAP_MISSING_TEST_LINK: (
            "cite at least one test_ref for this item, or generate the test this vPlan "
            "row is supposed to drive"),
        GAP_MISSING_OWNER: "assign a real owner to this leaf vPlan item",
        GAP_MISSING_PRIORITY: (
            "declare a priority for this item, one of " f"{', '.join(PRIORITY_VALUES)}"),
        GAP_UNREFERENCED_VERIFICATION_INTENT: (
            "add a vPlan row that references this verification intent, or record why it "
            "is deliberately not yet planned"),
        GAP_DANGLING_INTENT_REF: (
            "correct the row's verification_intent_ref to an intent id that is really in "
            "the supplied verification_intents list"),
        GAP_INTENT_METHOD_CONTRADICTION: (
            "resolve the disagreement between this row's own verification_method and its "
            "cited intent's declared method -- a human decision, this module does not "
            "pick a winner"),
    },
}
assert set(VPLAN_GAP_ACTION_CATALOG["actions"]) == set(GAP_TAXONOMY), (
    "VPLAN_GAP_ACTION_CATALOG must name an action for every GAP_TAXONOMY code")


# ===========================================================================
# Report dataclasses
# ===========================================================================

@dataclass
class DimensionResult:
    """One dimension's independent verdict. Never merged with any other
    dimension's -- see module docstring."""
    dimension: str
    status: str
    applicable_count: int
    satisfied_count: int
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""


@dataclass
class VPlanCompletenessReport:
    schema_version: str
    generated_at: float
    row_count: int
    leaf_count: int
    hierarchy: Dict[str, Any]
    dimensions: Dict[str, DimensionResult]
    all_gaps: List[Dict[str, Any]]
    next_best_actions: List[Dict[str, Any]]


def _status_for(gaps: List[Dict[str, Any]], applicable_count: int) -> str:
    if applicable_count == 0:
        return UNKNOWN
    if not gaps:
        return READY
    if any(GAP_SEVERITY[g["gap"]] == BLOCKED for g in gaps):
        return BLOCKED
    return PARTIAL


def _leaf_rows(hierarchy: Dict[str, Any]) -> List[Mapping[str, Any]]:
    canonical_row = hierarchy["canonical_row"]
    return [canonical_row[rid] for rid in hierarchy["leaves"]]


# ---------------------------------------------------------------------------
# Dimension 1: hierarchy integrity
# ---------------------------------------------------------------------------
def _analyze_hierarchy_integrity(hierarchy: Dict[str, Any], row_count: int) -> DimensionResult:
    gaps = [g for g in hierarchy["gaps"] if g["dimension"] == DIM_HIERARCHY_INTEGRITY]
    applicable_count = row_count
    implicated = set(hierarchy["duplicate_ids"]) | set(hierarchy["orphan_ids"]) | set(hierarchy["cycle_ids"])
    satisfied_count = max(applicable_count - len(implicated), 0)
    reason = (f"{applicable_count} vPlan row(s) checked for id uniqueness, parent-reference "
              "resolution and cycle-freedom" if applicable_count else "no vPlan rows supplied")
    return DimensionResult(DIM_HIERARCHY_INTEGRITY, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ---------------------------------------------------------------------------
# Dimension 2: requirement coverage
# ---------------------------------------------------------------------------
def _analyze_requirement_coverage(vplan_rows: Sequence[Mapping[str, Any]],
                                   requirements: Optional[Sequence[Mapping[str, Any]]]) -> DimensionResult:
    if requirements is None:
        return DimensionResult(DIM_REQUIREMENT_COVERAGE, UNKNOWN, 0, 0, [],
                                "no requirements list supplied for cross-check "
                                "(pass requirements=[...] to enable this dimension)")
    req_ids = {r["id"] for r in requirements
               if isinstance(r, Mapping) and _is_nonempty_str(r.get("id"))}
    referenced = set()
    all_refs: List[Tuple[str, str]] = []
    for row in vplan_rows:
        for ref in row.get("requirement_refs") or []:
            all_refs.append((row["id"], ref))
            referenced.add(ref)
    gaps: List[Dict[str, Any]] = []
    for req_id in sorted(req_ids - referenced):
        gaps.append({"gap": GAP_UNMAPPED_REQUIREMENT, "dimension": DIM_REQUIREMENT_COVERAGE,
                      "requirement_id": req_id,
                      "detail": f"requirement '{req_id}' is not referenced by any vPlan row"})
    for row_id, ref in all_refs:
        if ref not in req_ids:
            gaps.append({"gap": GAP_DANGLING_REQUIREMENT_REF, "dimension": DIM_REQUIREMENT_COVERAGE,
                          "row_id": row_id, "requirement_id": ref,
                          "detail": f"row '{row_id}' cites requirement '{ref}', absent from "
                                    "the supplied requirements list"})
    applicable_count = len(req_ids) + len(all_refs)
    satisfied_count = max(applicable_count - len(gaps), 0)
    reason = (f"{len(req_ids)} supplied requirement(s) cross-checked against {len(all_refs)} "
              "vPlan requirement reference(s)" if applicable_count else
              "no requirements and no vPlan row references one either")
    return DimensionResult(DIM_REQUIREMENT_COVERAGE, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ---------------------------------------------------------------------------
# Dimension 3: verification method assignment
# ---------------------------------------------------------------------------
def _analyze_verification_method(leaf_rows: List[Mapping[str, Any]]) -> DimensionResult:
    gaps: List[Dict[str, Any]] = []
    for row in leaf_rows:
        method = row.get("verification_method")
        if not method:
            gaps.append({"gap": GAP_MISSING_VERIFICATION_METHOD,
                         "dimension": DIM_VERIFICATION_METHOD_ASSIGNMENT, "row_id": row["id"],
                         "detail": f"row '{row['id']}' declares no verification_method"})
        elif method not in KNOWN_VERIFICATION_METHODS:
            gaps.append({"gap": GAP_UNKNOWN_VERIFICATION_METHOD,
                         "dimension": DIM_VERIFICATION_METHOD_ASSIGNMENT, "row_id": row["id"],
                         "detail": f"row '{row['id']}' declares verification_method "
                                   f"'{method}', not one of {KNOWN_VERIFICATION_METHODS}"})
    applicable_count = len(leaf_rows)
    satisfied_count = max(applicable_count - len(gaps), 0)
    reason = (f"{applicable_count} leaf vPlan item(s) checked for a declared, recognized "
              f"verification_method (of {KNOWN_VERIFICATION_METHODS})" if applicable_count else
              "no leaf vPlan items to check (no rows, or every row has children)")
    return DimensionResult(DIM_VERIFICATION_METHOD_ASSIGNMENT, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ---------------------------------------------------------------------------
# Dimensions 4-6: coverage/checker/test-stimulus linkage
# ---------------------------------------------------------------------------
def _analyze_linkage(leaf_rows: List[Mapping[str, Any]], dimension: str, field_name: str,
                      gap_code: str, relevant_methods: Tuple[str, ...]) -> DimensionResult:
    applicable_rows = [r for r in leaf_rows if r.get("verification_method") in relevant_methods]
    gaps: List[Dict[str, Any]] = []
    for row in applicable_rows:
        if not row.get(field_name):
            gaps.append({"gap": gap_code, "dimension": dimension, "row_id": row["id"],
                         "detail": f"row '{row['id']}' (method {row.get('verification_method')}) "
                                   f"cites no {field_name}"})
    applicable_count = len(applicable_rows)
    satisfied_count = max(applicable_count - len(gaps), 0)
    reason = (f"{applicable_count} leaf item(s) with a {field_name}-relevant "
              f"verification_method (of {relevant_methods}) checked for {field_name}"
              if applicable_count else
              f"no leaf items declare a {field_name}-relevant verification_method "
              f"(of {relevant_methods}); this dimension is not evaluated over other methods")
    return DimensionResult(dimension, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ---------------------------------------------------------------------------
# Dimension 7: ownership
# ---------------------------------------------------------------------------
def _analyze_ownership(leaf_rows: List[Mapping[str, Any]]) -> DimensionResult:
    gaps = [{"gap": GAP_MISSING_OWNER, "dimension": DIM_OWNERSHIP_ASSIGNMENT, "row_id": r["id"],
             "detail": f"row '{r['id']}' names no owner"}
            for r in leaf_rows if not r.get("owner")]
    applicable_count = len(leaf_rows)
    satisfied_count = max(applicable_count - len(gaps), 0)
    reason = (f"{applicable_count} leaf vPlan item(s) checked for a named owner" if applicable_count
              else "no leaf vPlan items to check")
    return DimensionResult(DIM_OWNERSHIP_ASSIGNMENT, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ---------------------------------------------------------------------------
# Dimension 8: priority
# ---------------------------------------------------------------------------
def _analyze_priority(leaf_rows: List[Mapping[str, Any]]) -> DimensionResult:
    gaps: List[Dict[str, Any]] = []
    for row in leaf_rows:
        p = row.get("priority")
        if not p or p not in PRIORITY_VALUES:
            gaps.append({"gap": GAP_MISSING_PRIORITY, "dimension": DIM_PRIORITY_ASSIGNMENT,
                         "row_id": row["id"],
                         "detail": f"row '{row['id']}' declares priority {p!r}, not one of "
                                   f"{PRIORITY_VALUES}"})
    applicable_count = len(leaf_rows)
    satisfied_count = max(applicable_count - len(gaps), 0)
    reason = (f"{applicable_count} leaf vPlan item(s) checked for a recognized priority "
              f"(of {PRIORITY_VALUES})" if applicable_count else "no leaf vPlan items to check")
    return DimensionResult(DIM_PRIORITY_ASSIGNMENT, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ---------------------------------------------------------------------------
# Dimension 9: intent cross-consistency
# ---------------------------------------------------------------------------
def _analyze_intent_cross_consistency(
        vplan_rows: Sequence[Mapping[str, Any]],
        verification_intents: Optional[Sequence[Mapping[str, Any]]]) -> DimensionResult:
    if verification_intents is None:
        return DimensionResult(DIM_INTENT_CROSS_CONSISTENCY, UNKNOWN, 0, 0, [],
                                "no verification_intents supplied for cross-check "
                                "(pass verification_intents=[...] to enable this dimension)")
    intents_by_id = {i["id"]: i for i in verification_intents
                      if isinstance(i, Mapping) and _is_nonempty_str(i.get("id"))}
    gaps: List[Dict[str, Any]] = []
    ref_rows = [(row, row.get("verification_intent_ref")) for row in vplan_rows
                if row.get("verification_intent_ref")]
    referenced_ids = set()
    for row, ref in ref_rows:
        referenced_ids.add(ref)
        intent = intents_by_id.get(ref)
        if intent is None:
            gaps.append({"gap": GAP_DANGLING_INTENT_REF, "dimension": DIM_INTENT_CROSS_CONSISTENCY,
                         "row_id": row["id"], "intent_id": ref,
                         "detail": f"row '{row['id']}' cites verification_intent_ref '{ref}', "
                                   "absent from the supplied verification_intents list"})
            continue
        row_method = row.get("verification_method")
        intent_method = intent.get("verification_method")
        if row_method and intent_method and row_method != intent_method:
            gaps.append({"gap": GAP_INTENT_METHOD_CONTRADICTION,
                         "dimension": DIM_INTENT_CROSS_CONSISTENCY, "row_id": row["id"],
                         "intent_id": ref,
                         "detail": f"row '{row['id']}' declares verification_method "
                                   f"'{row_method}' but cited intent '{ref}' declares "
                                   f"'{intent_method}'"})
    for intent_id in sorted(set(intents_by_id) - referenced_ids):
        gaps.append({"gap": GAP_UNREFERENCED_VERIFICATION_INTENT,
                     "dimension": DIM_INTENT_CROSS_CONSISTENCY, "intent_id": intent_id,
                     "detail": f"verification intent '{intent_id}' is not referenced by any "
                               "vPlan row"})
    applicable_count = len(intents_by_id) + len(ref_rows)
    satisfied_count = max(applicable_count - len(gaps), 0)
    reason = (f"{len(intents_by_id)} supplied verification intent(s) cross-checked against "
              f"{len(ref_rows)} vPlan row reference(s)" if applicable_count else
              "no verification_intents and no vPlan row references one either")
    return DimensionResult(DIM_INTENT_CROSS_CONSISTENCY, _status_for(gaps, applicable_count),
                            applicable_count, satisfied_count, gaps, reason)


# ===========================================================================
# Top-level analysis
# ===========================================================================

def analyze_vplan_completeness(
        vplan_rows: List[Dict[str, Any]], *,
        requirements: Optional[List[Dict[str, Any]]] = None,
        verification_intents: Optional[List[Dict[str, Any]]] = None,
        root: Optional[str] = None) -> VPlanCompletenessReport:
    """Analyze a vPlan document's hierarchy and its nine completeness
    dimensions (never collapsed -- see module docstring), and wire the
    resulting gaps through the real `inference.next_best_action()`.

    `vplan_rows` is a plain list of dicts satisfying `VPLAN_ROW_FIELDS` (see
    `validate_vplan_row`). `requirements` and `verification_intents` are
    plain lists of dicts each carrying at least an `"id"` string; omit
    either to skip its cross-check dimension (reported UNKNOWN with a real
    reason, never a fabricated pass). Once `spec_intelligence.py` /
    `verification_intent_ir.py` land, their own real requirement/intent
    records can be converted to these same plain dicts -- e.g.
    `{"id": rec.requirement_id}` / `{"id": rec.intent_id,
    "verification_method": rec.method}` -- with no change to this function.

    `root` is accepted for signature parity with every other
    `next_best_action()` caller in this repo; it is never read because this
    function always supplies `gap_action_catalog`, whose branch in
    `inference.next_best_action()` returns before touching `protocol` or
    `root` at all -- so this function performs no filesystem I/O.

    Raises `VPlanArtifactValidationError` if `vplan_rows` (or a row within
    it) does not satisfy this module's schema -- a STRUCTURAL defect, never
    silently tolerated. A SEMANTIC defect (duplicate id, missing owner, ...)
    is reported as a gap instead.
    """
    validate_vplan_document(vplan_rows)
    hierarchy = build_vplan_hierarchy(vplan_rows)
    leaf_rows = _leaf_rows(hierarchy)

    dimensions: Dict[str, DimensionResult] = {
        DIM_HIERARCHY_INTEGRITY: _analyze_hierarchy_integrity(hierarchy, len(vplan_rows)),
        DIM_REQUIREMENT_COVERAGE: _analyze_requirement_coverage(vplan_rows, requirements),
        DIM_VERIFICATION_METHOD_ASSIGNMENT: _analyze_verification_method(leaf_rows),
        DIM_COVERAGE_MODEL_LINKAGE: _analyze_linkage(
            leaf_rows, DIM_COVERAGE_MODEL_LINKAGE, "coverage_refs", GAP_MISSING_COVERAGE_LINK,
            COVERAGE_AND_CHECKER_RELEVANT_METHODS),
        DIM_CHECKER_LINKAGE: _analyze_linkage(
            leaf_rows, DIM_CHECKER_LINKAGE, "checker_refs", GAP_MISSING_CHECKER_LINK,
            COVERAGE_AND_CHECKER_RELEVANT_METHODS),
        DIM_TEST_STIMULUS_LINKAGE: _analyze_linkage(
            leaf_rows, DIM_TEST_STIMULUS_LINKAGE, "test_refs", GAP_MISSING_TEST_LINK,
            TEST_STIMULUS_RELEVANT_METHODS),
        DIM_OWNERSHIP_ASSIGNMENT: _analyze_ownership(leaf_rows),
        DIM_PRIORITY_ASSIGNMENT: _analyze_priority(leaf_rows),
        DIM_INTENT_CROSS_CONSISTENCY: _analyze_intent_cross_consistency(vplan_rows, verification_intents),
    }

    all_gaps: List[Dict[str, Any]] = []
    for dim_result in dimensions.values():
        all_gaps.extend(dim_result.gaps)

    gap_codes_present = sorted({g["gap"] for g in all_gaps})
    next_best_actions = (
        next_best_action(None, gap_codes_present, root or ".", gap_action_catalog=VPLAN_GAP_ACTION_CATALOG)
        if gap_codes_present else []
    )

    return VPlanCompletenessReport(
        schema_version=SCHEMA_VERSION,
        generated_at=time.time(),
        row_count=len(vplan_rows),
        leaf_count=len(leaf_rows),
        hierarchy=hierarchy,
        dimensions=dimensions,
        all_gaps=all_gaps,
        next_best_actions=next_best_actions,
    )


def vplan_completeness_report_to_dict(report: VPlanCompletenessReport) -> Dict[str, Any]:
    """JSON-serializable rendering of a report. `hierarchy["canonical_row"]`
    is dropped (it duplicates the caller's own `vplan_rows` input verbatim
    and is not JSON-safe in general since a row may carry non-serializable
    caller extensions); every dimension result is asdict'ed explicitly."""
    hierarchy = {k: v for k, v in report.hierarchy.items() if k != "canonical_row"}
    return {
        "schema_version": report.schema_version,
        "generated_at": report.generated_at,
        "row_count": report.row_count,
        "leaf_count": report.leaf_count,
        "hierarchy": hierarchy,
        "dimensions": {dim: asdict(result) for dim, result in report.dimensions.items()},
        "all_gaps": report.all_gaps,
        "next_best_actions": report.next_best_actions,
    }


def render_completeness_matrix_markdown(report: VPlanCompletenessReport) -> str:
    """The 9-dimension matrix as a markdown table, through this repo's only
    parameterized table renderer (`connectivity.render_markdown_table()`)
    rather than a second hand-rolled row-join loop."""
    from .connectivity import render_markdown_table

    columns = (
        ("dimension", "Dimension"), ("status", "Status"),
        ("applicable_count", "Applicable"), ("satisfied_count", "Satisfied"),
        ("gap_count", "Gaps"), ("reason", "Reason"),
    )
    rows = [{
        "dimension": dim, "status": result.status,
        "applicable_count": result.applicable_count,
        "satisfied_count": result.satisfied_count,
        "gap_count": len(result.gaps), "reason": result.reason,
    } for dim, result in report.dimensions.items()]
    return render_markdown_table(columns, rows, empty_note="(no dimensions)")
