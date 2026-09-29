"""Real, passing tests for dv_harness/web_control_plane_readiness_gate.py --
section 400's WEB_CONTROL_PLANE_READY composite gate over its 18 section-399
sub-gates.

Fixture convention matches this project's own established one: real artifacts
are written through the REAL writer that owns them wherever a cheap one
exists (`write_state`/`write_coverage_summary`/`write_lsf_job`/
`write_protocol_registry`, IMPORTED from `test_golden_flow_readiness.py`
rather than re-typed, plus `QuestionQueueStore.add_question()` and
`loop_telemetry.emit()` here), never hand-shaped JSON standing in for a real
producer's output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import (
    dashboard_auth,
    environment_mode_router,
    golden_flow_readiness as gfr,
    web_control_plane_readiness_gate as w,
)
from dv_harness.models import Stage, Status
from dv_harness.storage import StateStore

from dv_harness_tests.test_golden_flow_readiness import (  # noqa: E402  (real, shared fixtures)
    write_state, write_coverage_summary, write_lsf_job, write_protocol_registry,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir(parents=True)
    return p


def gate_of(result: dict, gate_id: str) -> dict:
    return next(g for g in result["gates"] if g["gate_id"] == gate_id)


# ---------------------------------------------------------------------------
# 1. The gate set is section 399's eighteen names, and the check has teeth
# ---------------------------------------------------------------------------

def test_gate_ids_are_section_399s_eighteen_names_in_order():
    assert w.GATE_IDS == w.SECTION_399_GATE_NAMES
    assert len(w.GATE_IDS) == 18
    assert len(set(w.GATE_IDS)) == 18


def test_section_399_check_has_teeth(monkeypatch):
    monkeypatch.setattr(w, "GATES", tuple(w.GATES[:-1]))
    with pytest.raises(w.WebControlPlaneReadinessError) as e:
        w._assert_gates_match_section_399()
    assert e.value.reason == "SECTION_399_GATE_SET_CHANGED"
    assert "GUI_LIVE_EVENT_READY" in e.value.detail["missing"]


def test_duplicate_gate_id_is_refused(monkeypatch):
    dup = w.GUIGateSpec("GUI_AUDIT_READY", (), lambda facts: w._cond(w.READY))
    monkeypatch.setattr(w, "GATES", w.GATES + (dup,))
    with pytest.raises(w.WebControlPlaneReadinessError) as e:
        w._assert_gates_match_section_399()
    assert e.value.reason in ("SECTION_399_GATE_SET_CHANGED", "DUPLICATE_GATE_ID")


def test_every_declared_fact_source_still_resolves():
    resolved = w.assert_fact_sources_resolvable()
    assert "dv_harness.golden_flow_readiness.derive_golden_flow_readiness" in resolved
    assert "dv_harness.dashboard_auth.assert_endpoints_mapped" in resolved
    assert "dv_harness.loop_telemetry.loop_events" in resolved


def test_a_renamed_fact_source_is_refused(monkeypatch):
    bad = w.GUIGateSpec("GUI_AUDIT_READY", ("dv_harness.loop_telemetry._no_such_reader",),
                        lambda facts: w._cond(w.READY))
    monkeypatch.setattr(w, "GATES", (bad,))
    with pytest.raises(w.WebControlPlaneReadinessError) as e:
        w.assert_fact_sources_resolvable()
    assert e.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"


def test_vocabulary_and_fold_are_genuinely_reused_from_golden_flow_readiness():
    """Not merely the same four words -- the SAME function objects."""
    assert w.combine_readiness is gfr.combine_readiness
    assert w.READY == gfr.READY and w.PARTIAL == gfr.PARTIAL
    assert w.BLOCKED == gfr.BLOCKED and w.UNKNOWN == gfr.UNKNOWN


# ---------------------------------------------------------------------------
# 2. A project that has never run: every gate present, nothing written,
#    UNKNOWN shown explicitly (section 402 rules 6/18)
# ---------------------------------------------------------------------------

def test_bare_project_reports_all_eighteen_gates_honestly(project: Path):
    result = w.derive_web_control_plane_readiness(project)
    assert [g["gate_id"] for g in result["gates"]] == list(w.SECTION_399_GATE_NAMES)
    assert result["summary"]["gates_total"] == 18
    assert result["web_control_plane_ready"] is False
    # nothing about this project has ever run -- every project-state-scoped
    # gate is honestly UNKNOWN, never a fabricated READY.
    for gate_id in ("GUI_PROJECT_WORKSPACE_READY", "GUI_INTAKE_READY", "GUI_REGRESSION_READY",
                    "GUI_COVERAGE_READY", "GUI_EVIDENCE_READY", "GUI_HUMAN_GATE_READY",
                    "GUI_AUDIT_READY", "GUI_LIVE_EVENT_READY", "GUI_SYSTEM_INTEGRATION_READY"):
        assert gate_of(result, gate_id)["status"] == w.UNKNOWN, gate_id


def test_producing_the_report_writes_nothing_for_a_bare_project(project: Path):
    """A readiness rollup must not change the readiness it reports."""
    w.derive_web_control_plane_readiness(project)
    assert list(project.rglob("*")) == []


def test_producing_the_report_mutates_nothing_on_an_initialized_project(project: Path):
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})
    write_coverage_summary(project, [{"name": "fsm", "percent": 100.0,
                                      "bins_total": 10, "bins_hit": 10}])
    before = {p.relative_to(project).as_posix(): p.read_bytes()
              for p in sorted(project.rglob("*")) if p.is_file()}
    w.derive_web_control_plane_readiness(project)
    after = {p.relative_to(project).as_posix(): p.read_bytes()
             for p in sorted(project.rglob("*")) if p.is_file()}
    for path, content in before.items():
        assert after.get(path) == content, f"{path} was modified by a read-only rollup"


# ---------------------------------------------------------------------------
# 3. The two pure-capability gates: READY on a bare project, BLOCKED on a
#    real drift -- these are deployment-integrity checks, not project-state
#    measurements, matching golden_flow_readiness's own dashboard/CLI rows.
# ---------------------------------------------------------------------------

def test_backend_contract_and_rbac_are_ready_on_a_bare_project(project: Path):
    result = w.derive_web_control_plane_readiness(project)
    assert gate_of(result, "GUI_BACKEND_CONTRACT_READY")["status"] == w.READY
    assert gate_of(result, "GUI_RBAC_READY")["status"] == w.READY


def test_a_real_dashboard_auth_drift_blocks_both_gates(project: Path, monkeypatch):
    def _explode():
        raise dashboard_auth.DashboardRoleMatrixError("ENDPOINT_REQUIRED_ROLE drifted")
    monkeypatch.setattr(dashboard_auth, "assert_endpoints_mapped", _explode)
    result = w.derive_web_control_plane_readiness(project)
    backend = gate_of(result, "GUI_BACKEND_CONTRACT_READY")
    rbac = gate_of(result, "GUI_RBAC_READY")
    assert backend["status"] == w.BLOCKED
    assert "drifted" in backend["gap"]
    assert rbac["status"] == w.BLOCKED
    assert "drifted" in rbac["gap"]
    assert result["web_control_plane_ready"] is False


# ---------------------------------------------------------------------------
# 4. Gates that reuse a real golden_flow_readiness row directly
# ---------------------------------------------------------------------------

def test_project_workspace_reuses_the_real_spec_in_row(project: Path):
    write_state(project, {Stage.INTAKE.value: Status.PASS.value})
    uploads = project / ".dv-harness" / "uploads" / "spec"
    uploads.mkdir(parents=True)
    (uploads / "spec.pdf").write_bytes(b"%PDF-1.4 real bytes")

    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_PROJECT_WORKSPACE_READY")
    assert gate["status"] == w.READY
    assert "INTAKE=PASS" in gate["evidence"]
    assert "1 uploaded document(s)" in gate["evidence"]


def test_regression_reuses_the_real_lsf_regression_row(project: Path):
    write_state(project, {Stage.REGRESSION.value: Status.PASS.value})
    write_lsf_job(project, {"job_id": "1001", "lsf_status": "DONE",
                            "dv_analysis_status": "PASS"})
    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_REGRESSION_READY")
    assert gate["status"] == w.READY
    assert "1 DV-PASS" in gate["evidence"]


def test_coverage_combines_two_real_golden_flow_rows(project: Path):
    write_coverage_summary(project, [{"name": "fsm", "percent": 100.0,
                                      "bins_total": 10, "bins_hit": 10}])
    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_COVERAGE_READY")
    assert gate["status"] == w.READY
    assert "coverage category" in gate["evidence"]
    assert "no category below 100" in gate["evidence"]


# ---------------------------------------------------------------------------
# 5. Gates with their own real evidence readers
# ---------------------------------------------------------------------------

def test_amba_mxn_ready_from_a_real_protocol_specific_model(project: Path):
    write_protocol_registry(project, {
        "AMBA4_MULTI_MASTER_MULTI_SLAVE": {"qualification_status": "BUILDER_AVAILABLE",
                                           "capability_status": "PROTOCOL_MODEL_PARTIAL"},
    })
    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_AMBA_MXN_READY")
    assert gate["status"] == w.READY
    assert "AMBA4_MULTI_MASTER_MULTI_SLAVE" in gate["evidence"]


def test_amba_mxn_partial_when_only_the_generic_skeleton_is_registered(project: Path):
    write_protocol_registry(project, {
        "AMBA4_MULTI_MASTER_MULTI_SLAVE": {"qualification_status": "BUILDER_AVAILABLE",
                                           "capability_status": "GENERIC_SKELETON_ONLY"},
    })
    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_AMBA_MXN_READY")
    assert gate["status"] == w.PARTIAL
    assert "GENERIC_SKELETON_ONLY" in gate["evidence"]


def test_system_integration_partial_once_a_real_subsystem_is_registered(project: Path):
    reg_path = environment_mode_router.registry_path(project)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps({"subsystems": [
        {"name": "usb0", "environment_manifest": "env.manifest.json",
         "release_sha": "abc123", "qualification_state": "QUALIFIED"},
    ]}), encoding="utf-8")

    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_SYSTEM_INTEGRATION_READY")
    assert gate["status"] == w.PARTIAL
    assert "usb0" in gate["evidence"]
    assert "SYS-37" in gate["gap"]


def test_evidence_ready_partial_once_a_real_but_empty_evidence_store_exists(project: Path):
    from dv_harness.evidence_db import EvidenceStore, default_db_path
    db_path = default_db_path(project)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    EvidenceStore(db_path, read_only=False).close()

    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_EVIDENCE_READY")
    assert gate["status"] == w.PARTIAL
    assert "evidence.duckdb exists" in gate["evidence"]
    assert "no golden scenario capsule" in gate["gap"]


def test_human_gate_ready_reflects_a_real_question_queue_store(project: Path):
    from dv_harness.question_queue import QuestionQueueStore
    store = QuestionQueueStore(project)
    store.add_question(
        domain="vip", question="Slave or master?", context_path="vip.usb0.mode",
        options=[{"label": "slave", "rationale": "port direction evidence says responder"},
                 {"label": "master", "rationale": "fallback"}],
        recommendation="slave",
        assumption_if_unanswered="Configure as bus slave/responder.")

    result = w.derive_web_control_plane_readiness(project)
    gate = gate_of(result, "GUI_HUMAN_GATE_READY")
    assert gate["status"] == w.READY
    assert "1 question(s) on file" in gate["evidence"]


def test_audit_and_live_event_ready_from_a_real_emitted_loop_event(project: Path):
    from dv_harness import loop_telemetry as lt
    store = StateStore(project)
    lt.emit(store, "LOOP_STARTED", run_id="run-1", goal="close coverage")

    result = w.derive_web_control_plane_readiness(project)
    audit = gate_of(result, "GUI_AUDIT_READY")
    live = gate_of(result, "GUI_LIVE_EVENT_READY")
    assert audit["status"] == w.READY
    assert "real audit event(s)" in audit["evidence"]
    assert live["status"] == w.READY
    assert "section-108 LOOP_* event(s)" in live["evidence"]


# ---------------------------------------------------------------------------
# 6. Signoff gate: reuses the real golden_flow row AND the real freeze list,
#    folded worst-wins -- proven with a controlled (monkeypatched) freeze
#    list over a real synthetic _Facts, since freezing a real baseline needs
#    a full gate-verified signoff bundle out of proportion to this one fold.
# ---------------------------------------------------------------------------

def test_signoff_gate_folds_golden_flow_row_and_freeze_list(monkeypatch, project: Path):
    from dv_harness import signoff_export as se

    facts = w._Facts(root=project, golden_flow={"rows": []},
                     gf_rows_by_id={"signoff_evidence": {
                         "status": w.READY, "evidence": "SIGNOFF=VERIFIED", "gap": w.NONE_CELL}})

    monkeypatch.setattr(se, "list_freezes", lambda root: [{"freeze_id": "f1"}])
    ready = w._probe_signoff(facts)
    assert ready["status"] == w.READY
    assert "1 signoff baseline freeze" in ready["evidence"]

    monkeypatch.setattr(se, "list_freezes", lambda root: [])
    mixed = w._probe_signoff(facts)
    # READY (stage) + UNKNOWN (no frozen baseline yet) folds to PARTIAL --
    # real progress must not be silently rounded up to READY.
    assert mixed["status"] == w.PARTIAL
    assert "no signoff baseline has ever been frozen" in mixed["gap"]


# ---------------------------------------------------------------------------
# 7. Top-level formula: READY only when every one of eighteen gates is READY
# ---------------------------------------------------------------------------

def test_top_level_ready_requires_every_gate_ready(monkeypatch, project: Path):
    # section 441 adds a nineteenth AND-condition (GLOBAL_STATUS_READY);
    # pin it READY here so this test's own claim -- "READY requires every
    # SECTION-399 gate READY" -- isn't confounded by that separate condition.
    monkeypatch.setattr(w, "_probe_global_status_ready",
                        lambda facts: w._cond(w.READY, "pinned for this test"))

    all_ready = (
        w.GUIGateSpec("G1", (), lambda facts: w._cond(w.READY, "ok")),
        w.GUIGateSpec("G2", (), lambda facts: w._cond(w.READY, "ok")),
    )
    monkeypatch.setattr(w, "GATES", all_ready)
    result = w.derive_web_control_plane_readiness(project)
    assert result["web_control_plane_ready"] is True
    assert result["critical_gui_unknown_count"] == 0
    assert result["overall_gate_fold"] == w.READY
    assert result["global_status_gate"]["status"] == w.READY

    with_unknown = all_ready + (
        w.GUIGateSpec("G3", (), lambda facts: w._cond(w.UNKNOWN, "", "no evidence")),)
    monkeypatch.setattr(w, "GATES", with_unknown)
    result2 = w.derive_web_control_plane_readiness(project)
    assert result2["web_control_plane_ready"] is False
    assert result2["critical_gui_unknown_count"] == 1

    with_blocked = all_ready + (
        w.GUIGateSpec("G3", (), lambda facts: w._cond(w.BLOCKED, "", "real defect")),)
    monkeypatch.setattr(w, "GATES", with_blocked)
    result3 = w.derive_web_control_plane_readiness(project)
    assert result3["web_control_plane_ready"] is False
    assert result3["overall_gate_fold"] == w.BLOCKED


# ---------------------------------------------------------------------------
# 7b. Section 441 amendment: GLOBAL_STATUS_READY, the nineteenth AND-condition
# ---------------------------------------------------------------------------

def test_global_status_gate_id_and_fact_source():
    assert w.GLOBAL_STATUS_CONDITION_ID == "GLOBAL_STATUS_READY"
    assert w.GLOBAL_STATUS_CONDITION_ID not in w.GATE_IDS
    assert w.GLOBAL_STATUS_CONDITION_ID not in w.SECTION_399_GATE_NAMES


def test_global_status_fact_source_resolves():
    resolved = w.assert_fact_sources_resolvable()
    assert "dv_harness.harness_status.HarnessStatusService.serve" in resolved
    assert "dv_harness.harness_status.HARNESS_STATE_SEVERITY" in resolved


def test_global_status_ready_is_honestly_unknown_on_a_bare_project(project: Path):
    """A never-run project's own HarnessStatusService reports harness.state
    UNKNOWN -- this gate must show that explicitly, never round it up, and
    the eighteen section-399 gates must be reported exactly as before
    (unaffected by this amendment's own bookkeeping)."""
    result = w.derive_web_control_plane_readiness(project)
    assert result["global_status_gate"]["gate_id"] == "GLOBAL_STATUS_READY"
    assert result["global_status_gate"]["status"] == w.UNKNOWN
    assert result["web_control_plane_ready"] is False
    assert len(result["gates"]) == 18
    assert "GLOBAL_STATUS_READY" in result["formula"]


def test_global_status_ready_blocks_the_overall_verdict_even_with_all_18_gates_ready(
        monkeypatch, project: Path):
    """The headline proof of the amendment: every one of the eighteen
    section-399 gates READY is no longer sufficient on its own -- a real
    BLOCKED harness_status verdict must still block WEB_CONTROL_PLANE_READY."""
    all_ready = tuple(
        w.GUIGateSpec(gid, (), lambda facts: w._cond(w.READY, "ok"))
        for gid in w.SECTION_399_GATE_NAMES)
    monkeypatch.setattr(w, "GATES", all_ready)
    monkeypatch.setattr(w, "_probe_global_status_ready",
                        lambda facts: w._cond(w.BLOCKED, "", "harness.state=FAILED"))
    result = w.derive_web_control_plane_readiness(project)
    assert result["overall_gate_fold"] == w.READY  # the eighteen are clean
    assert result["global_status_gate"]["status"] == w.BLOCKED
    assert result["web_control_plane_ready"] is False


def test_global_status_ready_true_end_to_end_via_a_real_harness_status_service(
        monkeypatch, project: Path):
    """Drives the REAL `harness_status.HarnessStatusService.serve()` (not a
    monkeypatched probe) and proves its own READY-shaped `harness.state`
    resolves this condition to READY, folding worst-wins through the real
    `HARNESS_STATE_SEVERITY` table this probe reuses rather than re-derives."""
    from dv_harness import harness_status as hs

    real_service = hs.HarnessStatusService(project)
    monkeypatch.setattr(hs.HarnessStatusService, "serve",
                        lambda self, **kw: {"harness": {"state": "SIGNOFF_READY"}})
    gate = w._probe_global_status_ready(w._Facts(root=project, golden_flow={}, gf_rows_by_id={}))
    assert gate["status"] == w.READY
    assert "SIGNOFF_READY" in gate["evidence"]


def test_global_status_ready_partial_on_an_in_progress_state(project: Path, monkeypatch):
    from dv_harness import harness_status as hs
    monkeypatch.setattr(hs.HarnessStatusService, "serve",
                        lambda self, **kw: {"harness": {"state": "RUNNING"}})
    gate = w._probe_global_status_ready(w._Facts(root=project, golden_flow={}, gf_rows_by_id={}))
    assert gate["status"] == w.PARTIAL


def test_global_status_ready_degrades_honestly_when_harness_status_raises(
        project: Path, monkeypatch):
    from dv_harness import harness_status as hs

    def _explode(self, **kw):
        raise RuntimeError("simulated harness_status failure")
    monkeypatch.setattr(hs.HarnessStatusService, "serve", _explode)
    gate = w._probe_global_status_ready(w._Facts(root=project, golden_flow={}, gf_rows_by_id={}))
    assert gate["status"] == w.BLOCKED
    assert "simulated harness_status failure" in gate["gap"]


def test_report_renders_the_global_status_condition(project: Path):
    result = w.derive_web_control_plane_readiness(project)
    text = w.format_web_control_plane_readiness_report(result)
    assert "GLOBAL_STATUS_READY" in text
    assert "section 441" in text.lower() or "441" in text


def test_a_probe_that_raises_reports_unknown_rather_than_crashing(monkeypatch, project: Path):
    def _explode(facts):
        raise RuntimeError("simulated probe bug")
    broken = (w.GUIGateSpec("G1", (), _explode),)
    monkeypatch.setattr(w, "GATES", broken)
    result = w.derive_web_control_plane_readiness(project)
    gate = result["gates"][0]
    assert gate["status"] == w.UNKNOWN
    assert "simulated probe bug" in gate["gap"]


# ---------------------------------------------------------------------------
# 8. Reporting / execute() / CLI
# ---------------------------------------------------------------------------

def test_report_states_the_formula_and_that_it_authorizes_nothing(project: Path):
    result = w.derive_web_control_plane_readiness(project)
    text = w.format_web_control_plane_readiness_report(result)
    assert "WEB_CONTROL_PLANE_READY" in text
    assert "GUI_AUDIT_READY" in text
    assert "authorizes: nothing" in text.lower()


def test_execute_exit_code_contract(project: Path):
    code, result, text = w.execute(project)
    assert code == 2  # bare project is not ready
    assert result["web_control_plane_ready"] is False
    assert "WEB_CONTROL_PLANE_READY" in text


def test_cli_subcommand_renders_the_report(project: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.web_control_plane_readiness_gate",
         "--project-root", str(project)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2
    assert "WEB_CONTROL_PLANE_READY" in proc.stdout


def test_cli_json_flag_emits_the_full_machine_readable_result(project: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.web_control_plane_readiness_gate",
         "--project-root", str(project), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    payload = json.loads(proc.stdout)
    assert len(payload["gates"]) == 18
    assert payload["web_control_plane_ready"] is False
