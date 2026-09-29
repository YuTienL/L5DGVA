"""dv_harness/web_control_plane_readiness_gate.py -- sections 342-402's
WEB_CONTROL_PLANE_READY composite gate and its 18 named GUI_*_READY sub-gates,
as a real, auto-generated artifact.

THE GAP THIS CLOSES
--------------------
Section 400 defines a literal AND-formula over eighteen named gates
(`GUI_BACKEND_CONTRACT_READY` through `GUI_LIVE_EVENT_READY`, section 399) plus
`Critical_GUI_UNKNOWN == 0`, and section 402's own Final GUI Implementation
Directive rule 6 requires "show UNKNOWN explicitly" and rule 18 "never infer
PASS from missing UI data". Every one of the eighteen concerns those gates name
is already answered by a REAL backend module elsewhere in this repo --
`golden_flow_readiness.py`'s own twenty-row matrix, `dashboard_auth.py`'s
role-map self-check, `loop_telemetry.py`'s section-108 event stream,
`subsystem_practicality_score.py`'s maturity rollup, `golden_scenario.py`'s
evidence store, `question_queue.py`'s human-gate queue, `signoff_export.py`'s
freeze store, `environment_mode_router.py`'s subsystem registry -- but nothing
folded those eighteen answers into the one composite verdict section 400
actually asks for. Two audits of the same project could therefore describe
"is the Web Control Plane ready" differently even from identical underlying
facts.

WHAT THIS MODULE IS NOT
------------------------
It derives no new fact about the GUI. Every one of the eighteen gates reads,
verbatim, an already-real backend module's own output -- most of them by
literally reusing one or more rows `golden_flow_readiness.
derive_golden_flow_readiness()` already computed for THIS SAME PROJECT ROOT,
never a second parse of the same evidence. Every other gate's `fact_source`
names the exact already-real function it reads, and
`assert_fact_sources_resolvable()` proves each one still resolves through the
import system -- the same anti-drift discipline `golden_flow_readiness.py`,
`generation_readiness.py` and `subsystem_maturity_gate.py` already apply to
their own row/condition tables.

It WRITES NO GOVERNANCE STATE and RUNS NOTHING: no stage is executed, no gate
script is invoked, no build/regression/LSF job is submitted, and no state,
control or approval file is written by this module's own code. It is a
READ-ONLY ROLLUP with NO STAGE GATE OF ITS OWN, exactly as the task that built
it specifies -- a `web_control_plane_ready: True` verdict is an input to a
human's Web Control Plane readiness review, never a substitute for one, and
this module has no write path to any approval record.

Disclosed, not hidden: this module's own first read,
`golden_flow_readiness.derive_golden_flow_readiness()`, inherits that module's
own pre-existing (and separately disclosed) side effect of materializing a
default `.dv-harness/config.json`/`control.json` the first time it runs over a
project that already has `state.json` but no `config.json` yet --
`subsystem_practicality_score.py` and `subsystem_maturity_gate.py` both carry
the identical disclosure for the identical reason (they call the same
function). Fixing that belongs to `golden_flow_readiness.py`, not here.

WHY THE VOCABULARY IS BORROWED, NOT MINTED
--------------------------------------------
Every gate's per-condition status and the fold across conditions reuse
`golden_flow_readiness.py`'s own READY/PARTIAL/BLOCKED/UNKNOWN vocabulary and
its `combine_readiness()` worst-wins fold verbatim (imported, never
re-typed) -- the same four words `system_readiness.py`, `subsystem_discovery`
and `golden_flow_readiness.py` itself already reuse one level down. A single
BLOCKED condition on a gate outranks any number of clean ones; a gate mixing
READY and UNKNOWN conditions is PARTIAL, never silently rounded up to READY;
an all-UNKNOWN gate is UNKNOWN, never READY by omission -- section 402 rule 6
("show UNKNOWN explicitly") and rule 18 ("never infer PASS from missing UI
data") as enforced fold behaviour, not merely as prose.

THE TOP-LEVEL FORMULA
-----------------------
Section 400's literal AND -- `WEB_CONTROL_PLANE_READY = G1 AND G2 AND ... AND
G18 AND Critical_GUI_UNKNOWN == 0` -- is realized exactly:
`combine_readiness()` folded across all eighteen gate verdicts can only return
READY when every one of them is READY (its own documented rule: "an empty
input is UNKNOWN... a mix of READY and UNKNOWN is PARTIAL"), so
`web_control_plane_ready = (overall == READY)` already IS the eighteen-way AND,
and `critical_gui_unknown_count` (how many of the eighteen gates read UNKNOWN)
is reported explicitly alongside it -- redundant with the fold by
construction, kept anyway because section 400 names it as its own term and a
reader should be able to see it without re-deriving it from the fold.

SECTION 441 AMENDMENT (2026-09-06) -- a NINETEENTH AND-condition,
GLOBAL_STATUS_READY
--------------------------------------------------------------------------
Section 441 (Global Status Bar theme) requires the Web Control Plane's own
composite readiness to ALSO require that the project's one canonical Global
Status Bar (`dv_harness/harness_status.py`'s `HarnessStatusService`, Global
Status Bar theme sections 403-411, built and tested in this same repo) is
itself not BLOCKED/UNKNOWN -- a Web Control Plane cannot honestly claim
READY while the harness's own single source of truth about "what is this
project's state right now" disagrees. This is deliberately NOT folded INTO
section 399's own eighteen-gate set (`GATES`/`SECTION_399_GATE_NAMES`/
`_assert_gates_match_section_399()` stay a byte-for-byte transcription of
that document's own eighteen names, unmodified, and `result["gates"]` stays
exactly those eighteen for every existing consumer of this module) -- it is
a separate, nineteenth AND-term this amendment adds ALONGSIDE that set,
reported on its own `global_status_gate` field and folded only into the
final `web_control_plane_ready` boolean and the printed formula string.

`_probe_global_status_ready()` reads `HarnessStatusService(root).serve()`'s
own, already-worst-wins-aggregated `harness.state` -- never a second
aggregation of any of the many subsystems that field already folds -- and
maps its nineteen-word `HarnessStatus` vocabulary down onto this module's
own borrowed READY/PARTIAL/BLOCKED/UNKNOWN four words via
`harness_status.HARNESS_STATE_SEVERITY`'s OWN severity numbers (reused, not
re-derived): SIGNOFF_READY/READY (severity 0-1) -> READY; every in-progress
value (PARTIAL/IDLE/WAITING/CONVERGING/RUNNING/VERIFYING/RETRY_WAIT/
PLATEAU/OSCILLATING/RESUMING/CREATED, severity 2-4) -> PARTIAL; UNKNOWN
itself (severity 5) -> UNKNOWN; every blocked/terminal-bad value (STALE/
CANCELLED/HUMAN_GATE/BLOCKED/STOPPED/FAILED/BUDGET_EXHAUSTED, severity
6-11) -> BLOCKED. A state this module cannot resolve a severity for
(`harness_status.py`'s own deliberately-severity-less NOT_APPLICABLE, or an
unrecognized future value) is honestly UNKNOWN rather than guessed --
GF-AT-28 applied one level up, exactly as every other probe in this file
already applies it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from . import golden_flow_readiness as gfr

SCHEMA_VERSION = "1.0"

#: READY / PARTIAL / BLOCKED / UNKNOWN, reused rather than reminted -- see the
#: module docstring.
READY = gfr.READY
PARTIAL = gfr.PARTIAL
BLOCKED = gfr.BLOCKED
UNKNOWN = gfr.UNKNOWN
READINESS_CLASSES: tuple = gfr.GOLDEN_FLOW_READINESS_CLASSES
combine_readiness = gfr.combine_readiness
NONE_CELL = gfr.NONE_CELL


class WebControlPlaneReadinessError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Small shared shape: one condition, and the worst-wins fold over several
# ===========================================================================

def _cond(status: str, evidence: str = "", gap: str = "") -> Dict[str, str]:
    if status not in READINESS_CLASSES:
        raise WebControlPlaneReadinessError(
            "UNKNOWN_READINESS_CLASS", {"status": status, "legal_values": list(READINESS_CLASSES)})
    return {"status": status, "evidence": evidence, "gap": gap}


def _fold(conds: List[Mapping[str, str]]) -> Dict[str, str]:
    """One gate's own worst-wins fold over its conditions -- `combine_readiness()`
    applied to a gate's own condition list, exactly the way
    `golden_flow_readiness.py` folds its twenty rows into one overall verdict,
    one level down."""
    if not conds:
        return _cond(UNKNOWN, "", "no condition was evaluated for this gate")
    status = combine_readiness([c["status"] for c in conds])
    evidence = "; ".join(c["evidence"] for c in conds if c.get("evidence"))
    gap = "; ".join(c["gap"] for c in conds if c.get("gap"))
    return _cond(status, evidence or NONE_CELL, gap or NONE_CELL)


# ===========================================================================
# Facts -- gathered once per report
# ===========================================================================

@dataclass
class _Facts:
    """Everything the eighteen probes below read. `golden_flow` is the REAL,
    already-computed `golden_flow_readiness.derive_golden_flow_readiness()`
    result for this same project root -- eleven of the eighteen gates below
    reuse one or more of its own twenty rows directly rather than re-reading
    the same evidence a second way."""
    root: Path
    golden_flow: Dict[str, Any]
    gf_rows_by_id: Dict[str, Dict[str, Any]]


def _gather_facts(root, cfg: Optional[Dict[str, Any]] = None) -> _Facts:
    root = Path(root)
    matrix = gfr.derive_golden_flow_readiness(root, cfg)
    rows_by_id = {r["row_id"]: r for r in matrix.get("rows") or []}
    return _Facts(root=root, golden_flow=matrix, gf_rows_by_id=rows_by_id)


def _gf_cond(facts: _Facts, row_id: str) -> Dict[str, str]:
    """One golden_flow_readiness row, reused verbatim as a condition. A row
    the matrix does not carry (a bug in that module, or a caller-supplied
    partial matrix) is honestly UNKNOWN rather than silently skipped."""
    row = facts.gf_rows_by_id.get(row_id)
    if row is None:
        return _cond(UNKNOWN, "", f"golden_flow_readiness row '{row_id}' is absent from the "
                                   "supplied matrix")
    evidence = row.get("evidence") or ""
    gap = row.get("gap") or ""
    # golden_flow_readiness renders an empty cell as the literal NONE_CELL
    # ("-"); strip it back to "" here so `_fold()`'s `if c.get("evidence")`
    # check treats it as absent rather than as a real evidence string.
    # Compared for EQUALITY, never with str.replace(), which would corrupt a
    # real evidence string that legitimately contains a hyphen.
    if evidence.strip() == NONE_CELL:
        evidence = ""
    if gap.strip() == NONE_CELL:
        gap = ""
    return _cond(row.get("status") or UNKNOWN, evidence, gap)


# ===========================================================================
# The eighteen probes -- each one real backend evidence, never re-derived
# ===========================================================================
#
# Contract, held by every probe below (mirrors golden_flow_readiness.py's
# own probe contract):
#   * returns {"status", "evidence", "gap"};
#   * reads only through the reader(s) named in the gate's own `fact_source`;
#   * NEVER raises for a project that has not run -- absence is a verdict
#     (UNKNOWN plus a real reason), not an error; a reader that itself fails
#     is reported in the gap cell.

def _probe_backend_contract(facts: _Facts) -> Dict[str, str]:
    conds = [_gf_cond(facts, "dashboard")]
    try:
        from . import dashboard_auth as da
        da.assert_endpoints_mapped()
        da.assert_control_commands_mapped()
        conds.append(_cond(
            READY,
            "dashboard_auth.ENDPOINT_REQUIRED_ROLE/CONTROL_COMMAND_REQUIRED_ROLE agree with "
            "dashboard.py's real POST dispatch (assert_endpoints_mapped()/"
            "assert_control_commands_mapped())"))
    except Exception as e:
        conds.append(_cond(
            BLOCKED, "",
            f"dashboard_auth's role map has drifted from dashboard.py's real dispatch: "
            f"{type(e).__name__}: {e}"))
    return _fold(conds)


def _probe_project_workspace(facts: _Facts) -> Dict[str, str]:
    return _gf_cond(facts, "spec_in")


def _probe_intake(facts: _Facts) -> Dict[str, str]:
    return _gf_cond(facts, "requirement_extraction")


def _probe_dut_discovery(facts: _Facts) -> Dict[str, str]:
    conds = [_gf_cond(facts, "protocol_topology_discovery")]
    try:
        from . import env_manifest as em
        path = em.default_manifest_path(facts.root)
        if path is not None and Path(path).exists():
            manifest = em.load_env_manifest(path)
            rtl = (manifest.get("dut_facts") or {}).get("rtl") or {}
            status = rtl.get("status")
            n_files = len(rtl.get("files") or [])
            if status == "PARSED" and n_files:
                conds.append(_cond(READY, f"env.manifest.json dut_facts.rtl status=PARSED "
                                          f"({n_files} file(s))"))
            elif status == "PARSED":
                conds.append(_cond(PARTIAL, "env.manifest.json dut_facts.rtl status=PARSED but "
                                            "parsed zero files"))
            else:
                conds.append(_cond(UNKNOWN, "", f"env.manifest.json dut_facts.rtl status="
                                               f"{status!r}"))
        else:
            conds.append(_cond(UNKNOWN, "", "no env.manifest.json exists yet to report "
                                            "dut_facts.rtl"))
    except Exception as e:
        conds.append(_cond(UNKNOWN, "", f"env.manifest.json unreadable: {type(e).__name__}: {e}"))
    return _fold(conds)


def _probe_workflow_observability(facts: _Facts) -> Dict[str, str]:
    try:
        from . import loop_telemetry as lt
        telemetry = lt.read_loop_telemetry(facts.root)
    except Exception as e:
        return _cond(UNKNOWN, "", f"loop_telemetry.read_loop_telemetry() failed: "
                                  f"{type(e).__name__}: {e}")
    if telemetry.get("available"):
        sessions = telemetry.get("sessions") or []
        n = len(sessions)
        return _cond(READY, f"loop_telemetry.read_loop_telemetry() reports {n} real loop "
                            f"session(s) with section-108 telemetry ({telemetry.get('events_file')})")
    return _cond(UNKNOWN, "", telemetry.get("reason") or "no loop telemetry has been recorded "
                                                          "for this project yet")


def _probe_regression(facts: _Facts) -> Dict[str, str]:
    return _gf_cond(facts, "lsf_regression")


def _probe_failure_triage(facts: _Facts) -> Dict[str, str]:
    return _gf_cond(facts, "failure_triage")


def _probe_coverage(facts: _Facts) -> Dict[str, str]:
    return _fold([_gf_cond(facts, "coverage_collection"), _gf_cond(facts, "coverage_hole_analysis")])


def _probe_amba_mxn(facts: _Facts) -> Dict[str, str]:
    try:
        from . import dashboard as dash
        registry = dash._protocol_registry(facts.root)
    except Exception as e:
        return _cond(BLOCKED, "", f"protocol_capability_registry.json unreadable: "
                                  f"{type(e).__name__}: {e}")
    amba_rows = [p for p in (registry or []) if "AMBA" in str(p.get("name") or "").upper()]
    if not amba_rows:
        return _cond(UNKNOWN, "", "no AMBA-family protocol is registered in "
                                  "protocol_capability_registry.json for this project")
    specific = [p for p in amba_rows if p.get("capability_status") not in
                (None, "GENERIC_SKELETON_ONLY")]
    if specific:
        return _cond(READY, f"{len(specific)}/{len(amba_rows)} AMBA protocol row(s) carry a "
                            f"protocol-specific model ({[p.get('name') for p in specific]})")
    return _cond(PARTIAL, f"{len(amba_rows)} AMBA protocol row(s) registered, all "
                          f"GENERIC_SKELETON_ONLY",
                "no protocol-specific AMBA M\u00d7N model exists yet for this project")


def _probe_performance(facts: _Facts) -> Dict[str, str]:
    try:
        from . import connectivity_check as cc
    except Exception as e:
        return _cond(BLOCKED, "", f"connectivity_check module unavailable: "
                                  f"{type(e).__name__}: {e}")
    try:
        state = cc.load_state(facts.root / cc.DEFAULT_STATE_RELPATH)
    except Exception as e:
        return _cond(UNKNOWN, "", f"connectivity_check state unreadable: "
                                  f"{type(e).__name__}: {e}")
    if not state:
        return _cond(UNKNOWN, "", f"no `{cc.DEFAULT_STATE_RELPATH}` exists yet -- no real "
                                  "connectivity/bus gate has ever run for this project; "
                                  "BUS_PERFORMANCE_READY/BUS_PERFORMANCE_SIGNOFF_READY need "
                                  "caller-declared measured conditions this harness has no live "
                                  "simulator to produce")
    return _cond(PARTIAL, f"a real connectivity/gate run is on file "
                          f"({cc.DEFAULT_STATE_RELPATH})",
                "amba_performance_readiness_gates.py's BUS_PERFORMANCE_READY/"
                "BUS_PERFORMANCE_SIGNOFF_READY still need caller-declared performance target/"
                "measurement conditions this rollup does not itself supply")


def _probe_subsystem(facts: _Facts) -> Dict[str, str]:
    try:
        from . import subsystem_practicality_score as sps
        report = sps.derive_subsystem_practicality_score(facts.root, deep=False)
    except Exception as e:
        return _cond(UNKNOWN, "", f"subsystem_practicality_score unreadable: "
                                  f"{type(e).__name__}: {e}")
    status_map = {
        sps.MATURITY_HIGH: READY,
        sps.MATURITY_MODERATE: PARTIAL,
        sps.MATURITY_LOW: PARTIAL,
        sps.MATURITY_INSUFFICIENT: UNKNOWN,
    }
    cls = status_map.get(report.get("maturity_status"), UNKNOWN)
    return _cond(cls, f"subsystem_practicality_score.derive_subsystem_practicality_score() "
                      f"maturity_status={report.get('maturity_status')} "
                      f"(overall_score_over_measured={report.get('overall_score_over_measured')}, "
                      f"measured_weight_percent={report.get('measured_weight_percent')})")


def _probe_system_integration(facts: _Facts) -> Dict[str, str]:
    try:
        from . import environment_mode_router as emr
        entries = emr.read_registered_subsystem_entries(facts.root)
    except Exception as e:
        return _cond(BLOCKED, "", f"subsystem_environment_registry.json unreadable: "
                                  f"{type(e).__name__}: {e}")
    if not entries:
        return _cond(UNKNOWN, "", "no subsystem is registered in the real SIGNOFF-PASS registry "
                                  "(environment_mode_router.read_registered_subsystem_entries) -- "
                                  "this project has not composed a multi-subsystem system yet")
    names = [e.get("name") for e in entries]
    return _cond(PARTIAL, f"{len(entries)} subsystem(s) registered ({names})",
                "system_readiness_gates.py's SYSTEM_SIGNOFF_READY still needs a real SYS-37 "
                "readiness document this rollup does not itself assemble from the registered set")


def _probe_evidence(facts: _Facts) -> Dict[str, str]:
    try:
        from . import golden_scenario as gs
        store = gs._open_store(facts.root, None, read_only=True)
    except Exception as e:
        return _cond(BLOCKED, "", f"evidence store open failed: {type(e).__name__}: {e}")
    if store is None:
        return _cond(UNKNOWN, "", "no `.dv-harness/evidence/evidence.duckdb` exists yet -- no "
                                  "regression evidence has ever been recorded for this project")
    try:
        capsules = gs.load_golden_scenarios(store)
    except Exception as e:
        return _cond(UNKNOWN, "", f"golden_scenario.load_golden_scenarios() failed: "
                                  f"{type(e).__name__}: {e}")
    finally:
        store.close()
    if capsules:
        return _cond(READY, f"{len(capsules)} golden scenario capsule(s) recorded in the real "
                            "evidence store (golden_scenario.load_golden_scenarios)")
    return _cond(PARTIAL, "evidence.duckdb exists", "no golden scenario capsule has ever been "
                                                    "recorded for this project")


def _probe_human_gate(facts: _Facts) -> Dict[str, str]:
    path = facts.root / ".dv-harness" / "question_queue" / "questions.json"
    if not path.exists():
        return _cond(UNKNOWN, "", "no `.dv-harness/question_queue/questions.json` exists yet -- "
                                  "no question has ever been filed for this project")
    try:
        from . import question_queue as qq
        store = qq.QuestionQueueStore(facts.root)
        questions = store.list_questions()
        metrics = store.compute_metrics()
    except Exception as e:
        return _cond(UNKNOWN, "", f"question_queue store unreadable: {type(e).__name__}: {e}")
    return _cond(READY, f"question_queue store readable: {len(questions)} question(s) on file, "
                        f"self_resolve_rate={metrics.get('self_resolve_rate')}")


def _probe_signoff(facts: _Facts) -> Dict[str, str]:
    gf = _gf_cond(facts, "signoff_evidence")
    try:
        from . import signoff_export as se
        freezes = se.list_freezes(facts.root)
        if freezes:
            freeze_cond = _cond(READY, f"{len(freezes)} signoff baseline freeze(s) on file "
                                       "(signoff_export.list_freezes)")
        else:
            freeze_cond = _cond(UNKNOWN, "", "no signoff baseline has ever been frozen "
                                            "(signoff_export.list_freezes)")
    except Exception as e:
        freeze_cond = _cond(UNKNOWN, "", f"signoff_export.list_freezes() failed: "
                                        f"{type(e).__name__}: {e}")
    return _fold([gf, freeze_cond])


def _probe_rbac(facts: _Facts) -> Dict[str, str]:
    try:
        from . import dashboard_auth as da
        da.assert_endpoints_mapped()
        da.assert_control_commands_mapped()
    except Exception as e:
        return _cond(BLOCKED, "", f"dashboard_auth's ROLE map has drifted from dashboard.py's "
                                  f"real dispatch: {type(e).__name__}: {e}")
    return _cond(READY, "dashboard_auth's VIEWER < OPERATOR < APPROVER role ranking is enforced "
                        "and its ENDPOINT_REQUIRED_ROLE/CONTROL_COMMAND_REQUIRED_ROLE maps are "
                        "self-consistent with dashboard.py's real POST dispatch "
                        "(assert_endpoints_mapped()/assert_control_commands_mapped())")


def _probe_audit(facts: _Facts) -> Dict[str, str]:
    try:
        from . import loop_telemetry as lt
        entries, scanned, truncated = lt.read_events(facts.root)
    except Exception as e:
        return _cond(UNKNOWN, "", f"events.jsonl unreadable: {type(e).__name__}: {e}")
    if entries:
        return _cond(READY, f"{scanned} real audit event(s) on file in .dv-harness/events.jsonl "
                            "(the same trail dv-harness audit / StateStore.event() write)")
    return _cond(UNKNOWN, "", "no `.dv-harness/events.jsonl` audit trail exists yet for this "
                             "project")


def _probe_live_event(facts: _Facts) -> Dict[str, str]:
    try:
        from . import loop_telemetry as lt
        picked, stats = lt.loop_events(facts.root)
    except Exception as e:
        return _cond(UNKNOWN, "", f"loop_telemetry.loop_events() failed: {type(e).__name__}: {e}")
    if picked:
        return _cond(READY, f"{len(picked)} real section-108 LOOP_* event(s) recorded "
                            f"(lines_scanned={stats.get('lines_scanned')})")
    return _cond(UNKNOWN, "", "no section-108 LOOP_* event has ever been emitted for this "
                             "project (run `dv-harness start --loop \"<goal>\"`)")


# ===========================================================================
# The eighteen gates -- section 399's own names, verbatim
# ===========================================================================

@dataclass(frozen=True)
class GUIGateSpec:
    gate_id: str
    fact_source: Tuple[str, ...]
    probe: Callable[[_Facts], Dict[str, str]]


GATES: Tuple[GUIGateSpec, ...] = (
    GUIGateSpec("GUI_BACKEND_CONTRACT_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.dashboard.serve",
                 "dv_harness.dashboard_auth.assert_endpoints_mapped",
                 "dv_harness.dashboard_auth.assert_control_commands_mapped"),
                _probe_backend_contract),
    GUIGateSpec("GUI_PROJECT_WORKSPACE_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.dashboard._uploaded_files"),
                _probe_project_workspace),
    GUIGateSpec("GUI_INTAKE_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.gates.effective_stage_gates"),
                _probe_intake),
    GUIGateSpec("GUI_DUT_DISCOVERY_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.dashboard._protocol_registry",
                 "dv_harness.env_manifest.load_env_manifest"),
                _probe_dut_discovery),
    GUIGateSpec("GUI_WORKFLOW_OBSERVABILITY_READY",
                ("dv_harness.loop_telemetry.read_loop_telemetry",),
                _probe_workflow_observability),
    GUIGateSpec("GUI_REGRESSION_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.regression_reporter.load_jobs",
                 "dv_harness.dashboard._lsf_summary"),
                _probe_regression),
    GUIGateSpec("GUI_FAILURE_TRIAGE_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.dashboard._failure_attribution"),
                _probe_failure_triage),
    GUIGateSpec("GUI_COVERAGE_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.dashboard._read_coverage_state",
                 "dv_harness.coverage_analysis.identify_holes"),
                _probe_coverage),
    GUIGateSpec("GUI_AMBA_MXN_READY",
                ("dv_harness.dashboard._protocol_registry",
                 "dv_harness.amba_readiness_gates.evaluate_amba_readiness_gates"),
                _probe_amba_mxn),
    GUIGateSpec("GUI_PERFORMANCE_READY",
                ("dv_harness.connectivity_check.load_state",
                 "dv_harness.amba_performance_readiness_gates."
                 "evaluate_amba_performance_readiness_gates"),
                _probe_performance),
    GUIGateSpec("GUI_SUBSYSTEM_READY",
                ("dv_harness.subsystem_practicality_score.derive_subsystem_practicality_score",),
                _probe_subsystem),
    GUIGateSpec("GUI_SYSTEM_INTEGRATION_READY",
                ("dv_harness.environment_mode_router.read_registered_subsystem_entries",
                 "dv_harness.system_readiness_gates.derive_system_readiness_gates"),
                _probe_system_integration),
    GUIGateSpec("GUI_EVIDENCE_READY",
                ("dv_harness.golden_scenario._open_store",
                 "dv_harness.golden_scenario.load_golden_scenarios"),
                _probe_evidence),
    GUIGateSpec("GUI_HUMAN_GATE_READY",
                ("dv_harness.question_queue.QuestionQueueStore.list_questions",
                 "dv_harness.question_queue.QuestionQueueStore.compute_metrics"),
                _probe_human_gate),
    GUIGateSpec("GUI_SIGNOFF_READY",
                ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
                 "dv_harness.signoff_export.read_signoff_stage_status",
                 "dv_harness.signoff_export.list_freezes"),
                _probe_signoff),
    GUIGateSpec("GUI_RBAC_READY",
                ("dv_harness.dashboard_auth.assert_endpoints_mapped",
                 "dv_harness.dashboard_auth.assert_control_commands_mapped"),
                _probe_rbac),
    GUIGateSpec("GUI_AUDIT_READY",
                ("dv_harness.loop_telemetry.read_events",),
                _probe_audit),
    GUIGateSpec("GUI_LIVE_EVENT_READY",
                ("dv_harness.loop_telemetry.loop_events",),
                _probe_live_event),
)

# ===========================================================================
# Section 441 amendment -- the nineteenth AND-condition, GLOBAL_STATUS_READY.
# Deliberately kept OUT of `GATES`/`GATE_IDS`/`SECTION_399_GATE_NAMES`: those
# three stay section 399's own eighteen names, byte-for-byte, so every
# existing consumer of `result["gates"]` (and `_assert_gates_match_section_
# 399()`) keeps working over exactly that eighteen-gate set. This condition
# is tracked, resolved and folded separately -- see the module docstring's
# "SECTION 441 AMENDMENT" section for the full rationale.
# ===========================================================================

GLOBAL_STATUS_CONDITION_ID = "GLOBAL_STATUS_READY"

#: `HarnessStatusService.serve()`'s own `harness.state` and the severity
#: table this probe reuses to bucket it -- cited here (never re-typed) so
#: `assert_fact_sources_resolvable()` proves this amendment's own evidence
#: provenance the same way it already proves the section-399 eighteen's.
GLOBAL_STATUS_FACT_SOURCE: Tuple[str, ...] = (
    "dv_harness.harness_status.HarnessStatusService.serve",
    "dv_harness.harness_status.HARNESS_STATE_SEVERITY",
)


def _probe_global_status_ready(facts: "_Facts") -> Dict[str, str]:
    """Section 441: read the project's own canonical `HarnessStatusService`
    verdict and fold it down onto this module's four-word vocabulary via
    that service's own severity numbers. Never re-derives any subsystem
    `harness.state` already aggregated -- see the module docstring."""
    try:
        from . import harness_status as hs
    except Exception as e:
        return _cond(UNKNOWN, "", f"dv_harness.harness_status unavailable: "
                                   f"{type(e).__name__}: {e}")
    try:
        snapshot = hs.HarnessStatusService(facts.root).serve()
    except Exception as e:
        return _cond(BLOCKED, "", f"HarnessStatusService.serve() failed: "
                                  f"{type(e).__name__}: {e}")
    state = (snapshot.get("harness") or {}).get("state") or "UNKNOWN"
    severity = hs.HARNESS_STATE_SEVERITY.get(state)
    evidence = (f"harness_status.HarnessStatusService.serve() reports "
                f"harness.state={state}")
    if severity is None:
        # NOT_APPLICABLE (deliberately severity-less in harness_status.py)
        # or a future/unrecognized value -- honestly UNKNOWN, never guessed.
        return _cond(UNKNOWN, "", f"{evidence} (no severity mapping -- "
                                   "NOT_APPLICABLE or unrecognized)")
    if severity <= 1:
        return _cond(READY, evidence)
    if severity <= 4:
        return _cond(PARTIAL, evidence,
                     f"harness.state={state} is in-progress, not yet READY")
    if severity == 5:
        return _cond(UNKNOWN, "", evidence)
    return _cond(BLOCKED, "", f"{evidence} (a blocked-shaped harness state)")


GATE_IDS: tuple = tuple(g.gate_id for g in GATES)

#: Section 399's own eighteen names, transcribed verbatim in the document's own
#: order -- compared against `GATE_IDS` at import time so a later edit that
#: silently drops or renames a gate fails a test rather than a matrix.
SECTION_399_GATE_NAMES: tuple = (
    "GUI_BACKEND_CONTRACT_READY", "GUI_PROJECT_WORKSPACE_READY", "GUI_INTAKE_READY",
    "GUI_DUT_DISCOVERY_READY", "GUI_WORKFLOW_OBSERVABILITY_READY", "GUI_REGRESSION_READY",
    "GUI_FAILURE_TRIAGE_READY", "GUI_COVERAGE_READY", "GUI_AMBA_MXN_READY",
    "GUI_PERFORMANCE_READY", "GUI_SUBSYSTEM_READY", "GUI_SYSTEM_INTEGRATION_READY",
    "GUI_EVIDENCE_READY", "GUI_HUMAN_GATE_READY", "GUI_SIGNOFF_READY", "GUI_RBAC_READY",
    "GUI_AUDIT_READY", "GUI_LIVE_EVENT_READY",
)


def _assert_gates_match_section_399() -> None:
    # Recomputed live off `GATES` on every call -- never the module-level
    # `GATE_IDS` cache -- so this check has teeth against a `GATES` that has
    # since been edited (or, in a test, monkeypatched), the same reason
    # `golden_flow_readiness._assert_rows_match_section_47()` recomputes its
    # own `declared` tuple from `ROWS` fresh rather than reading a cache.
    declared = tuple(g.gate_id for g in GATES)
    if declared != SECTION_399_GATE_NAMES:
        raise WebControlPlaneReadinessError("SECTION_399_GATE_SET_CHANGED", {
            "declared": list(declared), "specification": list(SECTION_399_GATE_NAMES),
            "missing": [g for g in SECTION_399_GATE_NAMES if g not in declared],
            "unexpected": [g for g in declared if g not in SECTION_399_GATE_NAMES]})
    if len(set(declared)) != len(declared):
        raise WebControlPlaneReadinessError("DUPLICATE_GATE_ID", {"gate_ids": list(declared)})


_assert_gates_match_section_399()


def _resolve_fact_source(dotted: str, gate_id: str) -> None:
    """Shared resolution routine for one `module.attribute` dotted-path
    citation -- extracted so `assert_fact_sources_resolvable()` can apply it
    to section 399's own eighteen gates AND (section 441) to the nineteenth
    GLOBAL_STATUS_READY condition without two copies of the same algorithm."""
    import importlib
    parts = dotted.split(".")
    obj = None
    for cut in range(len(parts), 1, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except Exception:
            continue
        rest = parts[cut:]
        break
    else:
        raise WebControlPlaneReadinessError("FACT_SOURCE_MODULE_UNIMPORTABLE", {
            "fact_source": dotted, "gate": gate_id})
    for name in rest:
        if not hasattr(obj, name):
            raise WebControlPlaneReadinessError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                "fact_source": dotted, "gate": gate_id, "missing_attribute": name})
        obj = getattr(obj, name)


def assert_fact_sources_resolvable() -> List[str]:
    """Import-time-style guard (also callable ad hoc / from tests): every
    `fact_source` a gate declares still resolves through the import system.

    The same anti-drift check `golden_flow_readiness.py`'s own
    `assert_fact_sources_resolvable()` runs over its twenty rows, applied here
    to this module's eighteen gates -- a gate saying it reads
    `dashboard._failure_attribution` after that function is renamed away is a
    gate whose evidence provenance is fiction. Section 441's nineteenth
    condition (`GLOBAL_STATUS_FACT_SOURCE`) is checked the identical way,
    appended after the eighteen so the two are proven independently.
    """
    resolved: List[str] = []
    for spec in GATES:
        for dotted in spec.fact_source:
            _resolve_fact_source(dotted, spec.gate_id)
            resolved.append(dotted)
    for dotted in GLOBAL_STATUS_FACT_SOURCE:
        _resolve_fact_source(dotted, GLOBAL_STATUS_CONDITION_ID)
        resolved.append(dotted)
    return resolved


# ===========================================================================
# The rollup
# ===========================================================================

def derive_web_control_plane_readiness(root, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Section 400's `WEB_CONTROL_PLANE_READY` verdict, plus every one of the
    eighteen section-399 sub-gates, for one real project root.

    Read-only and total: every declared gate appears in the output, including
    gates whose real sources reported absence -- section 402's "show UNKNOWN
    explicitly" rule as a mandatory row, not an optional footnote.
    """
    root = Path(root)
    facts = _gather_facts(root, cfg)
    gates: List[Dict[str, Any]] = []
    for spec in GATES:
        try:
            probed = spec.probe(facts)
        except Exception as e:  # a probe bug must not delete a mandatory gate
            probed = _cond(UNKNOWN, "", f"probe raised {type(e).__name__}: {e}")
        status = probed.get("status") or UNKNOWN
        if status not in READINESS_CLASSES:
            raise WebControlPlaneReadinessError("PROBE_RETURNED_UNKNOWN_READINESS_CLASS", {
                "gate": spec.gate_id, "status": status, "legal_values": list(READINESS_CLASSES)})
        gates.append({
            "gate_id": spec.gate_id,
            "status": status,
            "evidence": (probed.get("evidence") or "").strip() or NONE_CELL,
            "gap": (probed.get("gap") or "").strip() or NONE_CELL,
            "fact_source": list(spec.fact_source),
        })

    counts = {cls: sum(1 for g in gates if g["status"] == cls) for cls in READINESS_CLASSES}
    critical_gui_unknown_count = counts[UNKNOWN]
    overall = combine_readiness([g["status"] for g in gates])
    # combine_readiness() returns READY only when EVERY input is READY (its own
    # documented rule), so this already IS section 400's eighteen-way AND;
    # `critical_gui_unknown_count == 0` is redundant with `overall == READY` by
    # construction and is reported anyway because section 400 names it as its
    # own explicit term.
    web_control_plane_ready_pre_441 = (overall == READY) and (critical_gui_unknown_count == 0)

    # -- section 441 amendment: the nineteenth AND-condition, evaluated and
    # reported separately from the eighteen (see the module docstring's
    # "SECTION 441 AMENDMENT" section and GLOBAL_STATUS_CONDITION_ID above).
    try:
        global_status_probed = _probe_global_status_ready(facts)
    except Exception as e:  # a probe bug must not silently satisfy the AND
        global_status_probed = _cond(UNKNOWN, "", f"probe raised {type(e).__name__}: {e}")
    global_status_status = global_status_probed.get("status") or UNKNOWN
    if global_status_status not in READINESS_CLASSES:
        raise WebControlPlaneReadinessError("PROBE_RETURNED_UNKNOWN_READINESS_CLASS", {
            "gate": GLOBAL_STATUS_CONDITION_ID, "status": global_status_status,
            "legal_values": list(READINESS_CLASSES)})
    global_status_gate = {
        "gate_id": GLOBAL_STATUS_CONDITION_ID,
        "status": global_status_status,
        "evidence": (global_status_probed.get("evidence") or "").strip() or NONE_CELL,
        "gap": (global_status_probed.get("gap") or "").strip() or NONE_CELL,
        "fact_source": list(GLOBAL_STATUS_FACT_SOURCE),
    }

    web_control_plane_ready = (
        web_control_plane_ready_pre_441 and (global_status_status == READY))

    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gates": gates,
        "gate_ids": list(GATE_IDS),
        "summary": {
            "gates_total": len(gates),
            **{f"gates_{cls.lower()}": counts[cls] for cls in READINESS_CLASSES},
        },
        "critical_gui_unknown_count": critical_gui_unknown_count,
        "overall_gate_fold": overall,
        # section 441: the nineteenth condition, reported on its own field
        # rather than folded into `gates`/`summary` (which stay exactly
        # section 399's own eighteen for every existing consumer).
        "global_status_gate": global_status_gate,
        "web_control_plane_ready": web_control_plane_ready,
        "formula": (
            "WEB_CONTROL_PLANE_READY = " + " AND ".join(GATE_IDS) +
            " AND Critical_GUI_UNKNOWN == 0 AND " + GLOBAL_STATUS_CONDITION_ID +
            "  (sections 400, 441)"),
        "authorizes": (
            "nothing. This is a read-only rollup over other read-only backend reports; it runs "
            "no stage, invokes no gate, starts no build/regression/LSF job, and approves no "
            "promotion or production write. A True verdict is an input to a human's Web Control "
            "Plane readiness review, never a substitute for one."),
    }


# ===========================================================================
# Reporting
# ===========================================================================

def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_web_control_plane_gates_table(result: Mapping[str, Any]) -> str:
    from .connectivity import render_markdown_table
    columns = (("gate_id", "Gate"), ("status", "Status"), ("evidence", "Evidence"), ("gap", "Gap"))
    keys = [k for k, _ in columns]
    rows = [{k: _cell(g.get(k, NONE_CELL)) for k in keys} for g in result.get("gates") or ()]
    return render_markdown_table(
        list(columns), rows,
        empty_note="(no gate was produced -- this is a bug: section 399's eighteen gates are "
                   "mandatory even when every one is UNKNOWN)")


def format_web_control_plane_readiness_report(result: Mapping[str, Any]) -> str:
    summary = result.get("summary") or {}
    global_status_gate = result.get("global_status_gate") or {}
    out = [
        "# WEB CONTROL PLANE READINESS (sections 342-402, 441)",
        "",
        f"**WEB_CONTROL_PLANE_READY = {result.get('web_control_plane_ready')}** -- "
        f"{summary.get('gates_ready', 0)} ready / {summary.get('gates_partial', 0)} partial / "
        f"{summary.get('gates_blocked', 0)} blocked / {summary.get('gates_unknown', 0)} unknown, "
        f"of {summary.get('gates_total', 0)} section-399 gates. Critical_GUI_UNKNOWN = "
        f"{result.get('critical_gui_unknown_count')}. Section 441's own nineteenth condition, "
        f"{GLOBAL_STATUS_CONDITION_ID} = {global_status_gate.get('status')}.",
        "",
        f"Project root: `{result.get('root')}`  (generated {result.get('generated_at')})",
        "",
        render_web_control_plane_gates_table(result),
        "",
        f"**{GLOBAL_STATUS_CONDITION_ID}** (section 441): "
        f"{global_status_gate.get('status')} -- "
        f"{global_status_gate.get('evidence') or NONE_CELL}",
        "",
        result.get("formula", ""),
        "",
        f"This verdict authorizes: {result.get('authorizes', '')}",
    ]
    blocked = [g for g in result.get("gates") or () if g["status"] == BLOCKED]
    if global_status_gate.get("status") == BLOCKED:
        blocked = list(blocked) + [global_status_gate]
    if blocked:
        out += ["", "## Blocked gates", ""]
        out += [f"- **{g['gate_id']}** -- {g['gap']}" for g in blocked]
    return "\n".join(out)


def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            as_json: bool = False) -> Tuple[int, Dict[str, Any], str]:
    """Returns (exit_code, result, rendered_text). Exit 2 unless
    `web_control_plane_ready` is True -- a CI signal, never an approval signal
    in either direction, the same convention `golden_flow_readiness.execute()`
    already uses."""
    result = derive_web_control_plane_readiness(root, cfg)
    text = "" if as_json else format_web_control_plane_readiness_report(result)
    return (0 if result["web_control_plane_ready"] else 2), result, text


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.web_control_plane_readiness_gate",
        description="Section 400's WEB_CONTROL_PLANE_READY composite gate and its 18 "
                    "section-399 sub-gates, aggregated from this project's real per-domain "
                    "sources. Reads only; runs no stage.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    code, result, text = execute(Path(args.project_root), as_json=args.as_json)
    print(_json.dumps(result, ensure_ascii=False, indent=2) if args.as_json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
