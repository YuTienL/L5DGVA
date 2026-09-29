"""Tests for dv_harness/gui_vip_coverage_wizard.py.

Real evidence throughout, per this project's Evidence Truth Rule: env.manifest
layer facts are produced by calling the REAL `env_manifest.py` builder
functions (never a hand-typed manifest shape), recorded coverage numbers land
in a REAL DuckDB `EvidenceStore` (`evidence_db.py`), and every intake-field
confirmation goes through the REAL `question_queue.QuestionQueueStore` via its
own `add_question()`/`answer_question()` API (never a hand-written decision
record). The suite includes a REQUIRED negative control proving the wizard
never fabricates a step's status when its real upstream evidence is absent,
and a live-server test driving the real HTTP endpoints end to end.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from dv_harness import env_manifest as em
from dv_harness import functional_coverage_signoff as fcs
from dv_harness import golden_flow_readiness
from dv_harness import gui_vip_coverage_wizard as wiz
from dv_harness import intake_state
from dv_harness import phy_boundary
from dv_harness import question_queue as qq
from dv_harness.evidence_db import EvidenceStore, default_db_path


# ---------------------------------------------------------------------------
# fixtures -- every one drives a real producer, never hand-typed JSON
# ---------------------------------------------------------------------------

def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _real_registers_layer(tmp_path):
    reg_map = {
        "schema_version": "1.0",
        "blocks": [{
            "name": "usb0", "base_address": "0x1000",
            "registers": [{"name": "CTRL", "address_offset": "0x0", "width": 32, "access": "RW"}],
        }],
    }
    p = _write_json(tmp_path / "register_map.json", reg_map)
    return em.build_dut_facts_registers(str(p))


def _real_vip_release_layer(tmp_path):
    home = tmp_path / "designware_home"
    pkg_dir = home / "vip" / "svt" / "usb3" / "1.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "release_notes.txt").write_text("USB3 VIP 1.0 release notes", encoding="utf-8")
    return em.build_vip_release(designware_home=str(home))


def _real_parallel_boundary_doc():
    phy_module = {"name": "phy", "ports": [{"name": "pipe_data", "direction": "output", "data_type": "[7:0]"}]}
    ctrl_module = {"name": "ctrl", "ports": [{"name": "pipe_data", "direction": "input", "data_type": "[7:0]"}]}
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    bind_decision = phy_boundary.decide_bind_location(classification, signals)
    assert classification["kind"] == "PARALLEL"
    assert bind_decision["bindable"] is True
    return {"status": "EXTRACTED", "bind_decision": bind_decision}


def _write_functional_coverage_signoff_fixture(root, bin_names, samples):
    """A real, schema-valid env.manifest.json (via env_manifest.
    generate_env_manifest()) whose testplan_correspondence claims exactly
    `bin_names`, plus real recorded coverage samples in a real DuckDB
    EvidenceStore -- the exact recipe test_functional_coverage_signoff.py's
    own fixtures already use."""
    testplan = {
        "schema_version": "1.0",
        "coverage_model": [{"name": name, "kind": "covergroup"} for name in bin_names],
        "vplan_items": [{"id": f"VP-{name}", "coverage": [name]} for name in bin_names],
    }
    tp_path = root / "testplan_sources.json"
    tp_path.write_text(json.dumps(testplan), encoding="utf-8")
    manifest = em.generate_env_manifest(testplan_sources_path=tp_path)
    out_path = root / ".dv-harness" / "env.manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    em.save_env_manifest(manifest, out_path)
    with EvidenceStore(default_db_path(root)) as store:
        for sample in samples:
            store.insert_coverage_sample(sample, timestamp="2026-09-06T00:00:00Z", source="test")


# ===========================================================================
# step declarations self-check
# ===========================================================================

def test_step_titles_match_task_order():
    wiz._assert_steps_match_task_order()  # must not raise
    assert [s.title for s in wiz.WIZARD_STEPS] == list(wiz.TASK_ORDERED_STEP_TITLES)
    assert len(wiz.WIZARD_STEPS) == 11


# ===========================================================================
# build_grounded_intake_state()
# ===========================================================================

def test_bare_project_grounds_every_field_honestly_missing(tmp_path):
    state, fqk, store, note = wiz.build_grounded_intake_state(tmp_path)
    for field in ("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset"):
        rec = state.get(field)
        assert rec is not None
        assert rec.status == intake_state.IntakeFieldStatus.MISSING.value
    assert note is not None and "no env.manifest.json" in note


def test_real_registers_layer_grounds_step_one_as_auto_resolved(tmp_path):
    registers_layer = _real_registers_layer(tmp_path)
    assert registers_layer["status"] == "LOADED"  # sanity on the real producer
    manifest = {"dut_facts": {"registers": registers_layer}}
    _write_json(wiz._inputs_path(tmp_path), {"env_manifest": manifest})

    step = wiz._STEP_BY_ID["dut_rtl_discovery"]
    view = wiz.build_step_view(tmp_path, step)
    rec = view["fields"]["dut_registers"]
    assert rec["status"] == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec["value"] == "LOADED"


def test_real_vip_release_layer_grounds_step_two(tmp_path):
    vip_release = _real_vip_release_layer(tmp_path)
    assert vip_release["status"] == "SCANNED"  # sanity on the real producer
    manifest = {"vip_config": {"vip_release": vip_release}}
    _write_json(wiz._inputs_path(tmp_path), {"env_manifest": manifest})

    step = wiz._STEP_BY_ID["vip_discovery"]
    view = wiz.build_step_view(tmp_path, step)
    assert view["categories"]["vip_resolution"]["status"] == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_real_parallel_phy_boundary_grounds_step_three(tmp_path):
    doc = _real_parallel_boundary_doc()
    _write_json(wiz._inputs_path(tmp_path), {"dut_boundary": doc})

    step = wiz._STEP_BY_ID["bind_tier_phy_boundary"]
    view = wiz.build_step_view(tmp_path, step)
    assert view["categories"]["dut_boundary"]["status"] == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    # critical_bind was never populated -> honestly MISSING, never fabricated clean
    assert view["categories"]["critical_bind"]["status"] == intake_state.IntakeFieldStatus.MISSING.value


# ===========================================================================
# answer_field() -- the real question_queue round trip
# ===========================================================================

def test_answer_field_resolves_a_missing_field_end_to_end(tmp_path):
    result = wiz.answer_field(tmp_path, "dut_rtl", "confirmed by human")
    assert result["question"]["status"] == "ANSWERED"
    assert result["question"]["answer"] == "confirmed by human"

    state, _fqk, _store, _note = wiz.build_grounded_intake_state(tmp_path)
    rec = state.get("dut_rtl")
    assert rec.status == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    assert intake_state.already_resolved(state, "dut_rtl") is True


def test_answer_field_refuses_when_already_resolved_NEGATIVE_CONTROL(tmp_path):
    wiz.answer_field(tmp_path, "dut_rtl", "first answer")
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.answer_field(tmp_path, "dut_rtl", "second answer")
    assert exc.value.reason == "ALREADY_RESOLVED"


def test_answer_field_refuses_empty_field_name(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.answer_field(tmp_path, "", "x")
    assert exc.value.reason == "EMPTY_FIELD_NAME"


def test_answer_field_refuses_empty_answer(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.answer_field(tmp_path, "dut_rtl", "")
    assert exc.value.reason == "EMPTY_ANSWER"


def test_answer_field_refuses_unknown_field(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.answer_field(tmp_path, "not_a_real_field", "x")
    assert exc.value.reason == "FIELD_NOT_FOUND"


def test_answer_question_directly_refuses_unknown_question_id(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.answer_question_directly(tmp_path, "Q-NOT-REAL", "x")
    assert exc.value.reason == "QUESTION_NOT_FOUND"


# ===========================================================================
# Step 8: coverage-hole identification (real coverage_analysis.py machinery)
# ===========================================================================

def test_coverage_hole_identification_honestly_reports_ungrounded_absent_summary(tmp_path):
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["coverage_hole_identification"])
    assert view["grounded"] is False
    assert view["holes"] == []


def test_coverage_hole_identification_finds_a_real_hole_and_escalates_it(tmp_path):
    summary = {"categories": [
        {"name": "cov_full", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_partial", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
    ]}
    _write_json(wiz._inputs_path(tmp_path), {"coverage_summary": summary})
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["coverage_hole_identification"])
    assert view["grounded"] is True
    assert view["coverage_summary_loaded"] is True
    names = [h["name"] for h in view["holes"]]
    assert names == ["cov_partial"]  # sorted ascending by percent, real hole only


# ===========================================================================
# Step 9: ranked coverage-closure actions (real coverage_closure_action_utility.py)
# ===========================================================================

def test_ranked_closure_actions_honestly_reports_no_candidates(tmp_path):
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["ranked_closure_actions"])
    assert view["grounded"] is False
    assert view["ranking_ever_run"] is False


def test_ranked_closure_actions_ranks_real_candidates(tmp_path):
    candidates = [
        {"action_id": "A1", "description": "write directed test",
         "expected_coverage_gain": 10, "requirement_priority": 5, "risk_coverage": 3, "cost": 2},
        {"action_id": "A2", "description": "relax constraint",
         "expected_coverage_gain": 4, "requirement_priority": 5, "risk_coverage": 3, "cost": 1},
    ]
    _write_json(wiz._inputs_path(tmp_path), {"closure_action_candidates": candidates})
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["ranked_closure_actions"])
    assert view["grounded"] is True
    assert view["ranking_ever_run"] is True
    ranked = view["ranking"]["ranked"]
    assert len(ranked) == 2
    assert ranked[0]["action_id"] == "A1"  # higher utility_score ranks first


# ===========================================================================
# Step 10: functional coverage signoff (real functional_coverage_signoff.py)
# ===========================================================================

def test_functional_coverage_signoff_honestly_not_available_on_bare_project(tmp_path):
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["functional_coverage_signoff"])
    assert view["report"]["status"] == fcs.STATUS_NOT_AVAILABLE
    assert view["report"]["functional_coverage_signoff_ready"] is None


def test_functional_coverage_signoff_real_full_measured_coverage_is_ready(tmp_path):
    _write_functional_coverage_signoff_fixture(
        tmp_path, ["cov_a"],
        [{"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10}])
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["functional_coverage_signoff"])
    assert view["report"]["status"] == fcs.STATUS_SIGNOFF_READY
    assert view["report"]["functional_coverage_signoff_ready"] is True


def test_overall_ready_is_exactly_step_10s_real_signal_NEGATIVE_CONTROL(tmp_path):
    """The REQUIRED negative control: on a bare project with no upstream
    evidence at all, overall_ready must be None -- never a fabricated True
    or False standing in for "we could not compute this"."""
    doc = wiz.get_state_view(tmp_path)
    assert doc["overall_ready"] is None

    _write_functional_coverage_signoff_fixture(
        tmp_path, ["cov_a"],
        [{"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10}])
    doc2 = wiz.get_state_view(tmp_path)
    assert doc2["overall_ready"] is True

    signoff_view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["functional_coverage_signoff"])
    assert doc2["overall_ready"] == signoff_view["report"]["functional_coverage_signoff_ready"]


def test_overall_ready_never_averages_the_other_ten_steps_NEGATIVE_CONTROL(tmp_path):
    """Even with several OTHER steps fully resolved, overall_ready must
    still be exactly Step 10's own real signal -- never an average or a
    completion percentage this wizard computed on its own."""
    wiz.answer_field(tmp_path, "dut_rtl", "confirmed")
    wiz.answer_field(tmp_path, "dut_registers", "confirmed")
    wiz.answer_field(tmp_path, "dut_address_map", "confirmed")
    wiz.answer_field(tmp_path, "dut_clock_reset", "confirmed")
    doc = wiz.get_state_view(tmp_path)
    # every DUT/RTL field is now resolved, but step 10's own inputs are
    # still absent -- overall_ready must stay None, not become True/False
    # from the OTHER steps' own progress.
    assert doc["overall_ready"] is None


# ===========================================================================
# Step 11: overall maturity summary (real subsystem_maturity_gate.py)
# ===========================================================================

def test_overall_maturity_summary_reports_all_three_levels(tmp_path):
    view = wiz.build_step_view(tmp_path, wiz._STEP_BY_ID["overall_maturity_summary"])
    assert set(view["levels"]) == {"9.0", "9.5", "10.0"}
    for level, result in view["levels"].items():
        assert result.get("level") == level
        assert "verdict" in result


# ===========================================================================
# advance_step() -- genuine per-step precondition refusal
# ===========================================================================

def test_advance_refused_when_step_one_unresolved_NEGATIVE_CONTROL(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.advance_step(tmp_path, direction="next")
    assert exc.value.reason == "PRECONDITION_NOT_MET"
    assert "dut_rtl" in exc.value.detail


def test_advance_succeeds_once_step_one_is_resolved(tmp_path):
    for f in ("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset"):
        wiz.answer_field(tmp_path, f, "confirmed")
    result = wiz.advance_step(tmp_path, direction="next")
    assert result["step"]["step_id"] == "vip_discovery"


def test_advance_back_always_allowed_and_clamps_at_zero(tmp_path):
    result = wiz.advance_step(tmp_path, direction="back")
    assert result["step"]["index"] == 0


def test_advance_refuses_unknown_step_id(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.advance_step(tmp_path, step_id="does_not_exist")
    assert exc.value.reason == "UNKNOWN_STEP_ID"


def test_advance_forward_jump_names_the_first_unmet_step(tmp_path):
    with pytest.raises(wiz.GuiVipCoverageWizardError) as exc:
        wiz.advance_step(tmp_path, step_id="overall_maturity_summary")
    assert exc.value.reason == "PRECONDITION_NOT_MET"
    assert "step 0" in exc.value.detail


def test_advance_terminal_step_has_no_precondition(tmp_path):
    for f in ("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset"):
        wiz.answer_field(tmp_path, f, "confirmed")
    for sid in ("vip_discovery", "bind_tier_phy_boundary", "vip_learning_gate",
                "uvm_generation_readiness", "vip_uvm_generation", "single_test_proof",
                "coverage_hole_identification", "ranked_closure_actions",
                "functional_coverage_signoff"):
        # These other steps have real gates that are not cleared on a bare
        # project (VIP learning gate, golden-flow rows, etc.); the terminal
        # step itself must still be reachable via advance_precondition()
        # returning True with no upstream evidence at all.
        pass
    ok, reason = wiz.advance_precondition(tmp_path, wiz._STEP_BY_ID["overall_maturity_summary"])
    assert ok is True
    assert reason == ""


# ===========================================================================
# HTML rendering
# ===========================================================================

def test_render_wizard_html_contains_crumbs_and_answer_form(tmp_path):
    doc = wiz.get_state_view(tmp_path)
    html = wiz.render_wizard_html(doc)
    assert "DUT/RTL Discovery" in html
    assert 'action="/answer"' in html
    assert 'name="field"' in html
    assert "Functional Coverage Signoff Ready" in html


def test_render_wizard_html_terminal_step_has_no_answer_form(tmp_path):
    session = wiz.WizardSession(current_step_index=len(wiz.WIZARD_STEPS) - 1)
    wiz.save_session(tmp_path, session)
    doc = wiz.get_state_view(tmp_path)
    html = wiz.render_wizard_html(doc)
    assert 'action="/answer"' not in html


def test_render_error_html_names_the_reason():
    exc = wiz.GuiVipCoverageWizardError("SOME_REASON", "some detail")
    html = wiz.render_error_html({}, exc)
    assert "SOME_REASON" in html
    assert "some detail" in html


# ===========================================================================
# Auth: own session-token issuance, distinct from dashboard_auth.py's own
# ===========================================================================

def test_issue_and_read_session_token(tmp_path):
    record = wiz.issue_session_token(tmp_path, port=12345)
    token = wiz.read_session_token(tmp_path)
    assert token == record["token"]
    assert len(token) > 20
    # own, distinct file from dashboard.py's own session file
    assert wiz._auth_session_path(tmp_path).name == "gui_vip_coverage_wizard_session.json"


def test_authorized_rejects_missing_and_wrong_token(tmp_path):
    class FakeHeaders(dict):
        def get(self, k, default=None):
            return dict.get(self, k, default)

    token = wiz.issue_session_token(tmp_path)["token"]
    assert wiz._authorized(token, FakeHeaders({"Authorization": f"Bearer {token}"}), "/api/answer") is True
    assert wiz._authorized(token, FakeHeaders({}), "/api/answer") is False
    assert wiz._authorized(token, FakeHeaders({"Authorization": "Bearer wrong"}), "/api/answer") is False


# ===========================================================================
# Live server: full GET/answer/advance/404 cycle over real HTTP
# ===========================================================================

def _wait_ready(base, timeout=10.0):
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/api/state", timeout=1)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.1)
    raise AssertionError(f"server never became ready: {last_exc}")


def _get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def _post_json(base, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            doc = {"raw": body.decode("utf-8", "replace")}
        return exc.code, doc


def test_live_server_get_answer_advance_cycle(tmp_path):
    server, token = wiz.build_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        _wait_ready(base)

        status, doc = _get_json(base, "/api/state")
        assert status == 200
        assert doc["step"]["step_id"] == "dut_rtl_discovery"
        assert doc["overall_ready"] is None

        # unauthorized answer is refused
        status, _doc = _post_json(base, "/api/answer", {"field": "dut_rtl", "answer": "x"})
        assert status == 401

        # authorized answer for every required field, then advance
        for f in ("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset"):
            status, doc = _post_json(base, "/api/answer", {"field": f, "answer": "confirmed"}, token=token)
            assert status == 200, doc

        status, doc = _post_json(base, "/api/advance", {"direction": "next"}, token=token)
        assert status == 200
        assert doc["step"]["step_id"] == "vip_discovery"

        # form-POST (non-/api) path redirects home (303)
        req = urllib.request.Request(
            base + "/advance", data=b"direction=back",
            method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Bearer {token}",
            })
        with urllib.request.urlopen(req, timeout=5) as resp:
            final_url = resp.geturl()
        assert resp.status == 200  # urllib follows the 303 to GET /

        # 404 on an unknown path
        try:
            urllib.request.urlopen(base + "/nope", timeout=5)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_live_server_root_page_renders_html(tmp_path):
    server, _token = wiz.build_server(tmp_path, port=0, require_auth=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        _wait_ready(base)
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "GUI VIP Coverage Wizard" in html
        assert "DUT/RTL Discovery" in html
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_live_server_answer_via_json_rejects_bad_field(tmp_path):
    server, token = wiz.build_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        _wait_ready(base)
        status, doc = _post_json(
            base, "/api/answer", {"field": "not_a_real_field", "answer": "x"}, token=token)
        assert status == 400
        assert doc["reason"] == "FIELD_NOT_FOUND"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_live_server_no_auth_flag_disables_gating(tmp_path):
    server, token = wiz.build_server(tmp_path, port=0, require_auth=False)
    assert token is None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        _wait_ready(base)
        status, doc = _post_json(base, "/api/answer", {"field": "dut_rtl", "answer": "confirmed"})
        assert status == 200, doc
    finally:
        server.shutdown()
        thread.join(timeout=5)
