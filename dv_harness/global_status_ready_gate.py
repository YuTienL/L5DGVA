"""GLOBAL_STATUS_READY + CLI_STATUS_READY: two composite machine-checkable
gates over `harness_status_ir.HarnessStatusIR`'s own real fields
(Global Status Bar theme, `CLAUDE_L5_GLOBAL_STATUS_BAR_MASTER.md` sections
440/442).

WHAT THIS MODULE IS NOT
------------------------
It builds no `HarnessStatusIR` of its own and reads no `state.json`,
`env.manifest.json`, evidence database, or any other real subsystem --
that assembly is section 409's Global State Aggregator / section 410's
HarnessStatusService, both explicitly NOT built by `harness_status_ir.py`
and not built here either. This module takes an ALREADY-ASSEMBLED
`HarnessStatusIR` (or its `to_dict()` shape) as input and answers a
narrower, structural question: is this IR internally trustworthy enough to
be trusted as the ONE canonical Global Status Bar data source, for any
surface (GLOBAL_STATUS_READY), and does it additionally carry the specific
leaf set the CLI text surface renders (CLI_STATUS_READY). Building the
aggregator here would duplicate a separately-confirmed gap and let this
gate drift out of agreement with whatever actually assembles the IR --
the exact parallel-mechanism failure this project's Methodology
Consolidation Rule forbids.

WHY THIS IS NOT "IS THE PROJECT HEALTHY"
-------------------------------------------
`derive_overall_status()` (in `harness_status_ir.py`) already folds an
IR's own status fields worst-wins into the project's real current status
(READY, BLOCKED, FAILED, ...). That is a DIFFERENT question from the one
these two gates ask. A Global Status Bar must be able to render a
genuinely BLOCKED or FAILED project just as reliably as a READY one --
"can this bar be trusted right now" and "what does this bar currently
say" are independent axes, and conflating them would make a project that
is honestly BLOCKED look like a broken status bar. Neither gate below
inspects what the IR's fields actually SAY (its `status`/`value` payload);
both inspect only whether the IR is SHAPED and CITED well enough to say
it reliably -- schema currency, GF-AT-28 fact-source integrity re-checked
per instance (not merely trusted from construction-time validation, in
case a caller reconstructed an IR from stored/transmitted JSON that
bypassed `StatusField.__post_init__`), and, for the CLI gate, whether the
specific leaves a CLI renderer reads are present in that IR's own real
leaf set at all.

THE SAME WORST-WINS, NO-AVERAGING DISCIPLINE THIS PROJECT ALREADY APPLIES
EVERYWHERE (`system_readiness_gates.py`, `subsystem_maturity_gate.py`,
`functional_coverage_signoff.py`, `spec_vplan_readiness_gate.py`)
--------------------------------------------------------------------------
Every gate here is a real AND-formula over its own required conditions,
folded by `_fold()`, mirroring `system_readiness_gates._fold()` byte for
byte:

  * A single condition that is BLOCKED or CONCERN (a real, evidenced
    structural defect -- a stale schema version, a status field the
    construction-time GF-AT-28 check somehow missed, a leaf path the
    catalog no longer names) makes the WHOLE gate NOT_READY, regardless
    of how many other conditions on that gate are clean.
  * A condition genuinely absent evidence for (no IR supplied at all, an
    IR missing a leaf this gate needed to check) is UNKNOWN, and -- when
    nothing worse is present on that gate -- makes the gate
    INCOMPLETE_EVIDENCE, a THIRD value distinct from both READY and
    NOT_READY: GF-AT-28 applied to this module specifically. A Critical
    UNKNOWN must never silently become READY, and must equally never be
    reported as a confirmed NOT_READY it was never proven to be.
  * Only when every required condition on a gate is CLEAR does that gate
    report READY.

`GATE_VERDICTS = (READY, NOT_READY, INCOMPLETE_EVIDENCE)` is checked, at
import time, to share no token with `dv_harness.models.Status` -- the
identical guard `system_readiness_gates.py`/`subsystem_maturity_gate.py`
already apply to their own gate-verdict vocabularies. (It deliberately
does NOT check disjointness from `harness_status_ir.HarnessStatus` --
that enum's own "READY" spells the same word as this module's gate-READY
token, exactly the same accepted overlap `system_readiness_gates.py`'s own
`GATE_READY = "READY"` already has with `subsystem_discovery.READY`/
`system_readiness.READY`: two different vocabularies in two different
type spaces, checked disjoint only from the one real stage-verdict
vocabulary, `models.Status`, that every gate in this project is checked
against.)

THE TWO GATES
--------------
GLOBAL_STATUS_READY -- is this IR, as a whole, structurally fit to be
  rendered identically by CLI, GUI and Web (section 403's own promise)?
  Five conditions, each a real re-check of a fact the IR's own governance
  functions already assert at import time / construction time, re-derived
  here per INSTANCE rather than trusted from a cached result (an IR
  reconstructed from stored/transmitted JSON bypasses
  `StatusField.__post_init__` entirely, so a per-instance re-check is the
  only way this gate can know the GF-AT-28 property still holds for the
  ACTUAL object a caller handed it):
    schema_version_current      -- `ir.schema_version == SCHEMA_VERSION`.
    status_governance_intact    -- `assert_all_status_governance()` still
                                    passes (the enum/severity/bridge
                                    totality checks `harness_status_ir.py`
                                    itself runs at import).
    leaf_shape_matches_catalog   -- this IR's own real leaf-path set
                                    (`iter_leaf_fields`) is exactly
                                    `FACT_SOURCE_CATALOG`'s key set --
                                    catches a caller handing this gate an
                                    IR built against a different (older or
                                    newer) schema shape.
    no_status_field_missing_evidence -- every one of THIS IR's own
                                    `StatusField` leaves that is not
                                    UNKNOWN/NOT_APPLICABLE really carries a
                                    non-empty `fact_source`, re-checked
                                    directly rather than trusted from
                                    construction time.
    no_evidence_field_missing_source -- the identical re-check for every
                                    `EvidenceField` leaf whose `value` is
                                    not `None`.
  GLOBAL_STATUS_READY is READY only when all five are CLEAR.

CLI_STATUS_READY -- does this IR additionally carry, structurally intact,
  the specific leaf set the CLI's own default text rendering reads
  (`CLI_REQUIRED_LEAF_PATHS`: identity.project_id, identity.mode,
  harness.state, harness.readiness, workflow.current_operation,
  blockers.critical_failures, blockers.human_gates, freshness.state --
  the minimum a one-line CLI status summary needs)? CLI_STATUS_READY
  folds GLOBAL_STATUS_READY itself as one condition (an IR that cannot
  even be trusted globally can never be trusted for one surface's own
  narrower needs) alongside one `leaf_present` condition per required
  path -- never a value/status check on those leaves (see "why this is
  not is-the-project-healthy" above), only "does this leaf exist on this
  IR at all, and if it is a StatusField, does IT ALSO carry the
  fact-source integrity GLOBAL_STATUS_READY already checks project-wide
  (re-checked per leaf here since a caller could in principle hand this
  gate a hand-built partial IR that skips the whole-instance check)".

NEITHER GATE RUNS A STAGE, INVOKES A GATE SCRIPT, WRITES STATE, OR
AUTHORIZES ANYTHING
---------------------------------------------------------------------
Both are pure reads over an already-in-memory `HarnessStatusIR` (or its
`to_dict()`); nothing here touches `.dv-harness/`, submits a build/
regression/LSF job, or references `ControlPlane.approve()`/
`policy.can_signoff()`/the PR-only main/master governance. There is
deliberately no `dv-harness` CLI verb and no `gates.py` `STAGE_GATES`
entry -- this project's own established disclosed-choice pattern for a
read-only rollup gate (`system_readiness_gates.py`, `subsystem_maturity_
gate.py`, `spec_vplan_readiness_gate.py` all make the identical choice):
the front door is `python -m dv_harness.global_status_ready_gate`, a
REACHED capability rather than a WIRED one, since nothing in this repo yet
assembles a real `HarnessStatusIR` for it to be handed.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from . import harness_status_ir as hsi
from .models import Status as VerdictStatus

# ===========================================================================
# Vocabulary
# ===========================================================================

#: This module's own per-condition status vocabulary. Deliberately the same
#: four spellings `system_readiness_gates.py` already uses for its own
#: per-input vocabulary (CLEAR/CONCERN/BLOCKED/UNKNOWN) -- not imported from
#: that module (this gate's domain is HarnessStatusIR structural integrity,
#: not SYS-37 composition readiness, and the two should not silently drift
#: together through a shared import), but the identical four words, for the
#: identical reason: a condition is either clean, a real evidenced problem,
#: a hard block, or genuinely unresolvable evidence -- never a fifth thing.
COND_CLEAR = "CLEAR"
COND_CONCERN = "CONCERN"
COND_BLOCKED = "BLOCKED"
COND_UNKNOWN = "UNKNOWN"
COND_STATUSES: tuple = (COND_CLEAR, COND_CONCERN, COND_BLOCKED, COND_UNKNOWN)

#: This module's own three-value GATE verdict vocabulary, mirroring
#: `system_readiness_gates.GATE_VERDICTS` exactly.
GATE_READY = "READY"
GATE_NOT_READY = "NOT_READY"
GATE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: tuple = (GATE_READY, GATE_NOT_READY, GATE_INCOMPLETE_EVIDENCE)

#: How this gate's own verdict folds into a condition on a gate that names
#: it as a dependency (CLI_STATUS_READY folding in GLOBAL_STATUS_READY).
GATE_VERDICT_TO_COND_STATUS: Dict[str, str] = {
    GATE_READY: COND_CLEAR,
    GATE_NOT_READY: COND_BLOCKED,
    GATE_INCOMPLETE_EVIDENCE: COND_UNKNOWN,
}

GATE_GLOBAL_STATUS_READY = "GLOBAL_STATUS_READY"
GATE_CLI_STATUS_READY = "CLI_STATUS_READY"
GATE_NAMES: tuple = (GATE_GLOBAL_STATUS_READY, GATE_CLI_STATUS_READY)

#: The fixed, minimum leaf set this project's CLI text surface reads to
#: render a one-line status summary -- section 442's own named subset.
#: Deliberately narrower than the full eleven-section IR (a GUI/Web surface
#: may render more), and deliberately NOT re-derived from any CLI rendering
#: code (none exists yet in this repo to read it from -- the CLI renderer
#: itself is section 410/a future HarnessStatusService concern). Declared
#: here, once, exactly as `system_readiness_gates.py` declares its own
#: eight gate names and `intake_state.py` declares its own required-fact
#: paths -- never re-derived per call.
CLI_REQUIRED_LEAF_PATHS: tuple = (
    "identity.project_id",
    "identity.mode",
    "harness.state",
    "harness.readiness",
    "workflow.current_operation",
    "blockers.critical_failures",
    "blockers.human_gates",
    "freshness.state",
)


class GlobalStatusReadyGateError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _assert_gate_vocabulary_disjoint_from_status() -> None:
    """Import-time guard: this module's own three-value gate-verdict
    vocabulary must never collide with `dv_harness.models.Status` -- a real
    stage-gate PASS/FAIL/BLOCKED/... is a different kind of fact from one
    of these composite gates' own READY/NOT_READY/INCOMPLETE_EVIDENCE
    verdict, and conflating the two tokens would let a caller mistake one
    for the other. The identical guard several sibling composite-gate
    modules already apply to their own vocabularies."""
    collision = set(GATE_VERDICTS) & {member.value for member in VerdictStatus}
    if collision:
        raise GlobalStatusReadyGateError(
            "GATE_VERDICT_VOCABULARY_COLLIDES_WITH_STATUS",
            {"collision": sorted(collision)})


_assert_gate_vocabulary_disjoint_from_status()


def _assert_two_named_gates() -> None:
    """Import-time check that this module still defines exactly the two
    named gates its own docstring promises -- the same defensive pattern
    `system_readiness_gates._assert_eight_named_gates()` uses."""
    if len(GATE_NAMES) != 2 or len(set(GATE_NAMES)) != 2:
        raise GlobalStatusReadyGateError(
            "GATE_NAME_SET_CHANGED", {"gates": list(GATE_NAMES), "expected_count": 2})


_assert_two_named_gates()


# ===========================================================================
# Accepting either a real HarnessStatusIR object or its to_dict() shape
# ===========================================================================

IRLike = Union[hsi.HarnessStatusIR, Mapping[str, Any]]


def _leaf_paths_and_dicts(ir_like: IRLike) -> Dict[str, dict]:
    """Return `{"section.leaf": leaf_dict}` for the supplied IR, whether it
    arrived as a real `HarnessStatusIR` dataclass instance or as the plain
    dict `to_dict()` already produces (e.g. read back from a JSON transport
    or a stored snapshot -- exactly the shape a future HarnessStatusService
    would hand this gate over the wire). Never re-derives the walk itself
    for a real instance: `iter_leaf_fields()`/`.to_dict()` do that."""
    if isinstance(ir_like, hsi.HarnessStatusIR):
        out: Dict[str, dict] = {}
        for path, leaf in hsi.iter_leaf_fields(ir_like):
            out[path] = leaf.to_dict()
        return out
    if isinstance(ir_like, Mapping):
        out = {}
        for section_name in hsi.HARNESS_STATUS_IR_SECTIONS:
            section = ir_like.get(section_name)
            if not isinstance(section, Mapping):
                continue
            for leaf_name, leaf_dict in section.items():
                if isinstance(leaf_dict, Mapping):
                    out[f"{section_name}.{leaf_name}"] = dict(leaf_dict)
        return out
    raise GlobalStatusReadyGateError(
        "NOT_A_HARNESS_STATUS_IR", {"got": type(ir_like).__name__})


def _schema_version_of(ir_like: IRLike) -> Optional[str]:
    if isinstance(ir_like, hsi.HarnessStatusIR):
        return ir_like.schema_version
    if isinstance(ir_like, Mapping):
        return ir_like.get("schema_version")
    return None


def _is_status_leaf(leaf_dict: Mapping[str, Any]) -> bool:
    """A `StatusField.to_dict()` carries `"status"`; an `EvidenceField.
    to_dict()` carries `"available"` instead and never `"status"` -- the two
    dict shapes are distinguishable without re-parsing the section schema."""
    return "status" in leaf_dict


# ===========================================================================
# Conditions -- each a single real, re-derived fact about the supplied IR
# ===========================================================================

def _condition(name: str, status: str, evidence: str, **detail) -> Dict[str, Any]:
    if status not in COND_STATUSES:
        raise GlobalStatusReadyGateError(
            "UNKNOWN_CONDITION_STATUS", {"condition": name, "status": status})
    return {"condition": name, "status": status, "evidence": evidence, **detail}


def _schema_version_current_condition(ir_like: IRLike) -> Dict[str, Any]:
    version = _schema_version_of(ir_like)
    if version is None:
        return _condition(
            "schema_version_current", COND_UNKNOWN,
            "the supplied document carries no schema_version field at all")
    if version == hsi.SCHEMA_VERSION:
        return _condition(
            "schema_version_current", COND_CLEAR,
            f"schema_version={version} matches the current HarnessStatusIR schema")
    return _condition(
        "schema_version_current", COND_BLOCKED,
        f"schema_version={version} does not match the current "
        f"HarnessStatusIR schema ({hsi.SCHEMA_VERSION}); this document was built "
        "against a stale or unrecognized shape", declared=version,
        current=hsi.SCHEMA_VERSION)


def _status_governance_intact_condition() -> Dict[str, Any]:
    """Re-runs `harness_status_ir.py`'s own import-time governance checks
    right now, rather than trusting that they still hold -- the same
    "re-derive, never merely trust a cached result" discipline this
    module's docstring names as its reason for existing at all."""
    try:
        hsi.assert_all_status_governance()
    except hsi.HarnessStatusIRError as e:
        return _condition(
            "status_governance_intact", COND_BLOCKED,
            f"HarnessStatus vocabulary/severity/bridge governance failed: "
            f"{e.reason}", detail=e.detail)
    return _condition(
        "status_governance_intact", COND_CLEAR,
        "HarnessStatus enum matches section 406, severity covers every "
        "foldable state, and every status bridge (readiness/verdict/loop-"
        "state) is total")


def _leaf_shape_matches_catalog_condition(ir_like: IRLike) -> Dict[str, Any]:
    leaves = _leaf_paths_and_dicts(ir_like)
    declared = set(hsi.FACT_SOURCE_CATALOG)
    actual = set(leaves)
    missing = sorted(actual - declared)
    extra = sorted(declared - actual)
    if missing or extra:
        return _condition(
            "leaf_shape_matches_catalog", COND_BLOCKED,
            f"the supplied document's leaf-path set disagrees with "
            f"FACT_SOURCE_CATALOG's own leaf set: "
            f"{len(missing)} leaf(-ves) with no catalog entry, "
            f"{len(extra)} catalog entr(y/ies) for a leaf this document "
            "does not carry -- this is not a current-shaped HarnessStatusIR",
            leaves_with_no_catalog_entry=missing,
            catalog_entries_for_absent_leaves=extra)
    return _condition(
        "leaf_shape_matches_catalog", COND_CLEAR,
        f"all {len(actual)} leaf paths match FACT_SOURCE_CATALOG's own key set")


def _no_status_field_missing_evidence_condition(ir_like: IRLike) -> Dict[str, Any]:
    """GF-AT-28, re-checked per instance: every StatusField leaf that
    claims a non-UNKNOWN, non-NOT_APPLICABLE status must really carry a
    non-empty `fact_source`. `StatusField.__post_init__` already enforces
    this at construction time for a real dataclass instance built through
    the sanctioned constructors -- this re-check exists for the document
    that arrived over the wire/from storage as a plain dict, which never
    passed through that constructor at all."""
    leaves = _leaf_paths_and_dicts(ir_like)
    violations: List[str] = []
    for path, leaf in leaves.items():
        if not _is_status_leaf(leaf):
            continue
        status = leaf.get("status")
        if status in (hsi.HarnessStatus.UNKNOWN.value, hsi.HarnessStatus.NOT_APPLICABLE.value):
            continue
        if not leaf.get("fact_source"):
            violations.append(path)
    if violations:
        return _condition(
            "no_status_field_missing_evidence", COND_BLOCKED,
            f"{len(violations)} status field(s) claim a non-UNKNOWN, "
            f"non-NOT_APPLICABLE status with no fact_source citation -- "
            f"GF-AT-28 violated: {violations}",
            violating_leaves=violations)
    status_leaf_count = sum(1 for leaf in leaves.values() if _is_status_leaf(leaf))
    return _condition(
        "no_status_field_missing_evidence", COND_CLEAR,
        f"every one of {status_leaf_count} status field(s) is either "
        "UNKNOWN/NOT_APPLICABLE or carries a real fact_source citation")


def _no_evidence_field_missing_source_condition(ir_like: IRLike) -> Dict[str, Any]:
    """The identical GF-AT-28 re-check, one level down, for `EvidenceField`
    leaves: a real (non-None) `value` must carry a non-empty `fact_source`."""
    leaves = _leaf_paths_and_dicts(ir_like)
    violations: List[str] = []
    for path, leaf in leaves.items():
        if _is_status_leaf(leaf):
            continue
        if leaf.get("value") is None:
            continue
        if not leaf.get("fact_source"):
            violations.append(path)
    if violations:
        return _condition(
            "no_evidence_field_missing_source", COND_BLOCKED,
            f"{len(violations)} evidence field(s) carry a real value with no "
            f"fact_source citation: {violations}",
            violating_leaves=violations)
    evidence_leaf_count = sum(1 for leaf in leaves.values() if not _is_status_leaf(leaf))
    return _condition(
        "no_evidence_field_missing_source", COND_CLEAR,
        f"every one of {evidence_leaf_count} evidence field(s) is either absent "
        "or carries a real fact_source citation")


def _leaf_present_condition(ir_like: IRLike, path: str) -> Dict[str, Any]:
    """One CLI-required leaf: does it exist on this document at all, and --
    if it is a StatusField -- does it independently clear the identical
    GF-AT-28 fact-source check `_no_status_field_missing_evidence_condition`
    already runs project-wide. Never inspects the leaf's own `status`/
    `value` payload: whether the CLI can render this leaf is a structural
    question, not a question about what the leaf currently says."""
    leaves = _leaf_paths_and_dicts(ir_like)
    leaf = leaves.get(path)
    if leaf is None:
        return _condition(
            f"leaf_present:{path}", COND_UNKNOWN,
            f"'{path}' is absent from the supplied document")
    if _is_status_leaf(leaf):
        status = leaf.get("status")
        if status not in (hsi.HarnessStatus.UNKNOWN.value, hsi.HarnessStatus.NOT_APPLICABLE.value) \
                and not leaf.get("fact_source"):
            return _condition(
                f"leaf_present:{path}", COND_BLOCKED,
                f"'{path}' claims status={status} with no fact_source citation")
    return _condition(f"leaf_present:{path}", COND_CLEAR, f"'{path}' is present")


# ===========================================================================
# The worst-wins fold -- identical shape to system_readiness_gates._fold()
# ===========================================================================

def _fold(conditions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_status = {s: [c["condition"] for c in conditions if c["status"] == s]
                 for s in COND_STATUSES}
    if by_status[COND_BLOCKED] or by_status[COND_CONCERN]:
        verdict = GATE_NOT_READY
        why = "unmet condition(s): " + "; ".join(
            f"{c['condition']}={c['status']}: {c['evidence']}" for c in conditions
            if c["status"] in (COND_BLOCKED, COND_CONCERN))
    elif by_status[COND_UNKNOWN]:
        verdict = GATE_INCOMPLETE_EVIDENCE
        why = "insufficient evidence: " + "; ".join(
            f"{c['condition']}: {c['evidence']}" for c in conditions
            if c["status"] == COND_UNKNOWN)
    else:
        verdict = GATE_READY
        why = f"all {len(conditions)} required condition(s) are CLEAR"
    return {
        "verdict": verdict,
        "evidence": why,
        "conditions": list(conditions),
        "by_status": by_status,
    }


# ===========================================================================
# The two named gates
# ===========================================================================

def _global_status_ready(ir_like: IRLike) -> Dict[str, Any]:
    conditions = [
        _schema_version_current_condition(ir_like),
        _status_governance_intact_condition(),
        _leaf_shape_matches_catalog_condition(ir_like),
        _no_status_field_missing_evidence_condition(ir_like),
        _no_evidence_field_missing_source_condition(ir_like),
    ]
    return _fold(conditions)


def _cli_status_ready(ir_like: IRLike, global_report: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = [
        _condition(
            GATE_GLOBAL_STATUS_READY,
            GATE_VERDICT_TO_COND_STATUS.get(global_report["verdict"], COND_UNKNOWN),
            f"{GATE_GLOBAL_STATUS_READY}={global_report['verdict']}: "
            f"{global_report['evidence']}"),
    ]
    for path in CLI_REQUIRED_LEAF_PATHS:
        conditions.append(_leaf_present_condition(ir_like, path))
    return _fold(conditions)


# ===========================================================================
# Front door
# ===========================================================================

def derive_global_status_ready_gates(ir_like: IRLike) -> Dict[str, Any]:
    """The two named composite gates over an already-assembled
    `HarnessStatusIR` (or its `to_dict()` shape). Never assembles one
    itself -- see the module docstring's "what this module is not"."""
    reports: Dict[str, Any] = {}
    reports[GATE_GLOBAL_STATUS_READY] = _global_status_ready(ir_like)
    reports[GATE_CLI_STATUS_READY] = _cli_status_ready(
        ir_like, reports[GATE_GLOBAL_STATUS_READY])

    by_verdict = {v: [n for n in GATE_NAMES if reports[n]["verdict"] == v]
                  for v in GATE_VERDICTS}
    return {
        "gates": reports,
        "gate_names": list(GATE_NAMES),
        "by_verdict": by_verdict,
        "authorizes": "NOTHING -- a structural readiness check on the Global "
                      "Status Bar's own data shape, never a project readiness "
                      "verdict and never a substitute for any human-approval gate",
        "summary": {
            "global_status_ready": reports[GATE_GLOBAL_STATUS_READY]["verdict"] == GATE_READY,
            "cli_status_ready": reports[GATE_CLI_STATUS_READY]["verdict"] == GATE_READY,
            "gates_ready": len(by_verdict[GATE_READY]),
            "gates_not_ready": len(by_verdict[GATE_NOT_READY]),
            "gates_incomplete_evidence": len(by_verdict[GATE_INCOMPLETE_EVIDENCE]),
            "gates_total": len(GATE_NAMES),
        },
    }


# ===========================================================================
# Reporting
# ===========================================================================

def render_global_status_ready_gates_table(gates_result: Mapping[str, Any]) -> str:
    header = "| Gate | Verdict | Evidence |"
    lines = [header, "|---|---|---|"]
    reports = gates_result.get("gates") or {}
    for name in gates_result.get("gate_names") or GATE_NAMES:
        report = reports.get(name) or {}
        evidence = str(report.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {report.get('verdict', '')} | {evidence} |")
    return "\n".join(lines)


def format_global_status_ready_gates_report(gates_result: Mapping[str, Any]) -> str:
    summary = gates_result.get("summary") or {}
    out = [
        "# GLOBAL_STATUS_READY / CLI_STATUS_READY "
        "(composite AND-formulas over HarnessStatusIR's own real fields)",
        "",
        f"{summary.get('gates_ready', 0)} ready / "
        f"{summary.get('gates_not_ready', 0)} not ready / "
        f"{summary.get('gates_incomplete_evidence', 0)} incomplete evidence, "
        f"of {summary.get('gates_total', 0)} gates.",
        "",
        render_global_status_ready_gates_table(gates_result),
        "",
        f"GLOBAL_STATUS_READY = {summary.get('global_status_ready')}.",
        f"CLI_STATUS_READY = {summary.get('cli_status_ready')}.",
        "",
        f"This verdict authorizes: {gates_result.get('authorizes', '')}",
    ]
    return "\n".join(out)


# ===========================================================================
# python -m dv_harness.global_status_ready_gate -- standalone front door.
# Deliberately no `dv-harness` CLI verb and no `gates.py` STAGE_GATES entry
# -- see the module docstring's own closing section.
# ===========================================================================

def execute_verb(document_path: str, *, as_json: bool = False) -> "tuple[str, int]":
    with open(document_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    result = derive_global_status_ready_gates(doc)
    text = json.dumps(result, indent=2) if as_json else format_global_status_ready_gates_report(result)
    code = {GATE_READY: 0, GATE_NOT_READY: 1, GATE_INCOMPLETE_EVIDENCE: 2}[
        result["gates"][GATE_GLOBAL_STATUS_READY]["verdict"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.global_status_ready_gate",
        description="GLOBAL_STATUS_READY + CLI_STATUS_READY composite gates over an "
                    "already-assembled HarnessStatusIR document (its to_dict() JSON). "
                    "Reads only; assembles nothing, runs no stage/gate/build/regression/"
                    "LSF job, and authorizes nothing.")
    parser.add_argument("document", help="path to a HarnessStatusIR.to_dict() JSON file")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        text, code = execute_verb(args.document, as_json=args.as_json)
    except (GlobalStatusReadyGateError, hsi.HarnessStatusIRError, OSError,
            json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
