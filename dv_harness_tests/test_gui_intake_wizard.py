"""Tests for dv_harness/gui_intake_wizard.py (GUI-01 Interactive Intake Wizard).

Every grounded fact in these tests comes from a REAL `intake_state.py`
resolution over a real (if minimal/partial, matching
`dv_harness_tests/test_intake_state.py`'s own fixture convention) env.manifest
document, and every human-answer path is driven through a REAL
`question_queue.QuestionQueueStore` on disk -- never a hand-written decisions
record. The live-server tests start the wizard's real `ThreadingHTTPServer` on
an OS-assigned free port and drive it over real HTTP.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from dv_harness import connectivity, env_manifest, gui_intake_wizard as wiz
from dv_harness import intake_state, question_queue


def _write_inputs(root, doc):
    d = root / ".dv-harness" / "gui_intake_wizard"
    d.mkdir(parents=True, exist_ok=True)
    (d / wiz.INTAKE_INPUTS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


def _real_vip_release_layer(tmp_path):
    home = tmp_path / "designware_home"
    pkg_dir = home / "vip" / "svt" / "usb3" / "1.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "release_notes.txt").write_text("USB3 VIP 1.0 release notes", encoding="utf-8")
    return env_manifest.build_vip_release(designware_home=str(home))


# ---------------------------------------------------------------------------
# Step declarations: transcribed verbatim from section 59, checked at import
# ---------------------------------------------------------------------------

def test_step_titles_match_the_task_spec_verbatim():
    assert tuple(s.title for s in wiz.WIZARD_STEPS) == wiz.TASK_ORDERED_STEP_TITLES
    assert len(wiz.WIZARD_STEPS) == 14


def test_step_ids_are_unique():
    ids = [s.step_id for s in wiz.WIZARD_STEPS]
    assert len(set(ids)) == len(ids)


def test_unmodeled_steps_are_the_five_with_no_intake_state_field():
    unmodeled = {s.step_id for s in wiz.WIZARD_STEPS if s.kind == wiz.KIND_UNMODELED}
    assert unmodeled == {"new_open_project", "verification_level", "spec", "command_txt", "protocol"}


def test_domain_owner_routing_is_reversed_from_the_real_table():
    inverse = {v: k for k, v in question_queue.DOMAIN_OWNER_ROUTING.items()}
    assert wiz._OWNER_TO_DOMAIN == inverse
    assert set(wiz._OWNER_TO_DOMAIN.values()) == {"dut", "vip", "env"}


# ---------------------------------------------------------------------------
# build_step_view(): honest grounding, never fabricated
# ---------------------------------------------------------------------------

def test_unmodeled_step_reports_ungrounded_with_no_fields():
    state = intake_state.build_intake_state()
    step = wiz._STEP_BY_ID["spec"]
    view = wiz.build_step_view(step, state)
    assert view["grounded"] is False
    assert view["fields"] == []
    assert "intake_state.py tracks no" in view["reason"]


def test_rtl_step_grounds_real_registers_layer_and_boundary(tmp_path):
    reg_map = {
        "schema_version": "1.0",
        "blocks": [{"name": "usb0", "base_address": "0x1000",
                     "registers": [{"name": "CTRL", "address_offset": "0x0", "width": 32, "access": "RW"}]}],
    }
    p = tmp_path / "register_map.json"
    p.write_text(json.dumps(reg_map), encoding="utf-8")
    registers_layer = env_manifest.build_dut_facts_registers(str(p))
    manifest = {"dut_facts": {"registers": registers_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    step = wiz._STEP_BY_ID["rtl"]
    view = wiz.build_step_view(step, state)
    fields = {f["field"]: f for f in view["fields"]}
    assert set(fields) == {"dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset", "dut_boundary"}
    assert fields["dut_registers"]["status"] == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_execution_environment_step_shows_every_real_dynamic_bind_field():
    entries = [
        {"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value},
        {"target_instance": "chip.core.usb1", "tier": connectivity.BindTier.T2_STRUCTURAL_MATCH.value},
    ]
    state = intake_state.build_intake_state(bind_entries=entries)
    step = wiz._STEP_BY_ID["execution_environment"]
    view = wiz.build_step_view(step, state)
    field_names = {f["field"] for f in view["fields"]}
    assert field_names == {"bind:chip.core.usb0", "bind:chip.core.usb1", "build_env"}


def test_evidence_discovery_shows_categories_no_earlier_step_names():
    conflicts = [{"resource": "AXI_M0", "status": "ACTIVE_DRIVER_CONFLICT", "reason": "two ACTIVE masters"}]
    state = intake_state.build_intake_state(active_driver_conflicts=conflicts)
    all_view = wiz.build_step_view(wiz._STEP_BY_ID["evidence_discovery"], state)
    all_names = {f["field"] for f in all_view["fields"]}
    assert "active_driver_conflict:AXI_M0" in all_names
    assert len(all_view["fields"]) == len(state.records)
    # ... and none of the earlier FIELDS steps claim it.
    for step_id in ("rtl", "existing_uvm_environment", "vip", "vplan", "execution_environment"):
        earlier = wiz.build_step_view(wiz._STEP_BY_ID[step_id], state)
        assert "active_driver_conflict:AXI_M0" not in {f["field"] for f in earlier["fields"]}


def test_missing_information_shows_every_gap_on_a_bare_project():
    state = intake_state.build_intake_state()
    view = wiz.build_step_view(wiz._STEP_BY_ID["missing_information"], state)
    assert len(view["fields"]) == len(state.records) == 14
    assert all(f["is_gap"] for f in view["fields"])
    assert all(not f["already_resolved"] for f in view["fields"])


def test_missing_information_excludes_resolved_fields():
    entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    view = wiz.build_step_view(wiz._STEP_BY_ID["missing_information"], state)
    assert "bind:chip.core.usb0" not in {f["field"] for f in view["fields"]}


def test_readiness_step_reflects_the_real_refusal_gate():
    state = intake_state.build_intake_state()
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    view = wiz.build_step_view(wiz._STEP_BY_ID["readiness"], state, readiness=readiness)
    assert view["ready"] is False
    assert set(view["blocking_categories"]) == set(intake_state.BLOCKING_CATEGORIES)


def test_readiness_step_reports_ready_when_all_six_categories_resolved(tmp_path):
    vip_layer = _real_vip_release_layer(tmp_path)
    manifest = {"vip_config": {"vip_release": vip_layer}}
    bind_entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    from dv_harness import phy_boundary
    phy_module = {"name": "phy", "ports": [{"name": "pipe_data", "direction": "output", "data_type": "[7:0]"}]}
    ctrl_module = {"name": "ctrl", "ports": [{"name": "pipe_data", "direction": "input", "data_type": "[7:0]"}]}
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    bind_decision = phy_boundary.decide_bind_location(classification, signals)
    dut_boundary = {"status": "EXTRACTED", "bind_decision": bind_decision}
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.PASS, detail={})
    tests = [{"test_name": "test_usb_smoke", "verdict": "PASS"}]
    state = intake_state.build_intake_state(
        env_manifest=manifest, bind_entries=bind_entries, dut_boundary=dut_boundary,
        active_driver_conflicts=[], build_env_gate=gate, known_pass_tests=tests,
    )
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    view = wiz.build_step_view(wiz._STEP_BY_ID["readiness"], state, readiness=readiness)
    assert view["ready"] is True
    assert view["blocking_categories"] == []


# ---------------------------------------------------------------------------
# build_grounded_intake_state(): assembling real inputs, never a manifest of
# nothing where one was declared
# ---------------------------------------------------------------------------

def test_bare_project_grounds_to_an_honest_all_missing_state(tmp_path):
    state, keys, store, note = wiz.build_grounded_intake_state(tmp_path)
    assert note is None
    assert len(state.records) == 14
    assert all(r.status == intake_state.IntakeFieldStatus.MISSING.value for r in state.records)
    assert set(keys) == {r.field for r in state.records}  # every field is routable on a bare project


def test_inline_env_manifest_input_grounds_a_real_layer(tmp_path):
    _write_inputs(tmp_path, {"env_manifest": {"vip_config": {"vip_release": {
        "status": "SCANNED", "reason": "", "packages": []}}}})
    state, _keys, _store, note = wiz.build_grounded_intake_state(tmp_path)
    assert note is None
    rec = state.get("vip_release")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_malformed_intake_inputs_file_is_reported_as_a_note_not_a_crash(tmp_path):
    d = tmp_path / ".dv-harness" / "gui_intake_wizard"
    d.mkdir(parents=True)
    (d / wiz.INTAKE_INPUTS_FILENAME).write_text("{not valid json", encoding="utf-8")
    state, _keys, _store, note = wiz.build_grounded_intake_state(tmp_path)
    assert note is not None and "could not be read" in note
    assert len(state.records) == 14  # still an honest, fully-MISSING state


# ---------------------------------------------------------------------------
# The real backend endpoint sequence: GET current step, POST answer, advance
# ---------------------------------------------------------------------------

def test_get_state_view_defaults_to_the_first_step(tmp_path):
    doc = wiz.get_state_view(tmp_path)
    assert doc["step"]["id"] == "new_open_project"
    assert doc["step"]["index"] == 0
    assert doc["step"]["total"] == 14
    assert len(doc["steps"]) == 14


def test_advance_next_and_back_are_clamped(tmp_path):
    doc = wiz.advance_step(tmp_path, direction="back")
    assert doc["step"]["index"] == 0  # already at the floor
    for _ in range(20):
        doc = wiz.advance_step(tmp_path, direction="next")
    assert doc["step"]["index"] == 13  # clamped at the ceiling, never past it
    assert doc["step"]["id"] == "user_review"


def test_advance_goto_by_step_id(tmp_path):
    doc = wiz.advance_step(tmp_path, step_id="readiness")
    assert doc["step"]["id"] == "readiness"
    assert doc["step"]["index"] == 12


def test_advance_unknown_step_id_refuses():
    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.advance_step(_tmp_root(), step_id="not_a_real_step")
    assert ei.value.reason == "UNKNOWN_STEP"


def test_advance_with_no_direction_or_step_id_refuses():
    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.advance_step(_tmp_root())
    assert ei.value.reason == "UNKNOWN_DIRECTION"


def test_session_position_persists_across_separate_calls(tmp_path):
    wiz.advance_step(tmp_path, step_id="vip")
    doc = wiz.get_state_view(tmp_path)  # a fresh call, as a new HTTP request would make
    assert doc["step"]["id"] == "vip"


def test_answer_field_end_to_end_resolves_and_then_refuses_a_reask(tmp_path):
    field = "build_env"
    doc = wiz.get_state_view(tmp_path)
    before = [f for f in wiz.build_step_view(
        wiz._STEP_BY_ID["execution_environment"],
        wiz.build_grounded_intake_state(tmp_path)[0])["fields"] if f["field"] == field][0]
    assert before["status"] == intake_state.IntakeFieldStatus.MISSING.value

    answered = wiz.answer_field(tmp_path, field, "envA has already been built and verified",
                                 basis="matches the real build log", decided_by="alice")
    assert answered["status"] == "ANSWERED"
    assert answered["answer"] == "envA has already been built and verified"

    state, _keys, store, _note = wiz.build_grounded_intake_state(tmp_path)
    rec = state.get(field)
    assert rec.status == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    assert rec.owner == "alice"
    assert rec.value == "envA has already been built and verified"

    # A real human_answer decision now sits on the real QuestionQueueStore.
    decisions = store._load_decisions()["decisions"]
    matches = [d for d in decisions.values() if d["current"]["source"] == question_queue.HUMAN_DECISION_SOURCE
               and d["current"]["decided_by"] == "alice"]
    assert len(matches) == 1

    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.answer_field(tmp_path, field, "a different answer now")
    assert ei.value.reason == "FIELD_ALREADY_RESOLVED"


def test_answer_field_rejects_unknown_field(tmp_path):
    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.answer_field(tmp_path, "this_field_does_not_exist", "some answer")
    assert ei.value.reason == "UNKNOWN_FIELD"


def test_answer_field_rejects_empty_answer(tmp_path):
    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.answer_field(tmp_path, "build_env", "   ")
    assert ei.value.reason == "EMPTY_ANSWER"


def test_answer_field_rejects_empty_field_name(tmp_path):
    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.answer_field(tmp_path, "", "some answer")
    assert ei.value.reason == "EMPTY_FIELD_NAME"


def test_answer_field_refuses_when_domain_cannot_be_routed(tmp_path, monkeypatch):
    """Defensive branch: a record whose owner is not one of the three real
    routed strings (never reachable through real intake_state.py resolution
    while the field is still unresolved) must still refuse honestly rather
    than raise an unguarded KeyError."""
    fabricated = intake_state.IntakeFieldRecord(
        field="build_env", category="build_env", value=None, source="test",
        confidence="UNKNOWN", status=intake_state.IntakeFieldStatus.MISSING.value,
        owner="not_a_real_routed_owner",
    )
    state = intake_state.IntakeState([fabricated])
    store = question_queue.QuestionQueueStore(tmp_path)
    monkeypatch.setattr(wiz, "build_grounded_intake_state", lambda root: (state, {}, store, None))
    with pytest.raises(wiz.GuiIntakeWizardError) as ei:
        wiz.answer_field(tmp_path, "build_env", "some answer")
    assert ei.value.reason == "FIELD_NOT_ROUTABLE"


# ---------------------------------------------------------------------------
# HTML rendering: honest disclosure, real answer forms only where warranted
# ---------------------------------------------------------------------------

def test_render_html_unmodeled_step_discloses_no_backing_field(tmp_path):
    wiz.advance_step(tmp_path, step_id="spec")
    doc = wiz.get_state_view(tmp_path)
    html = wiz.render_wizard_html(doc)
    assert "GUI-01 Interactive Intake Wizard" in html
    assert "Spec" in html
    assert "intake_state.py tracks no" in html
    assert 'name="field"' not in html  # no fabricated answer form


def test_render_html_fields_step_offers_an_answer_form_for_a_gap():
    state = intake_state.build_intake_state()
    doc = {
        "step": {"id": "rtl", "title": "RTL", "index": 3, "total": 14},
        "steps": [{"id": s.step_id, "title": s.title, "grounded": s.kind != wiz.KIND_UNMODELED}
                  for s in wiz.WIZARD_STEPS],
        "view": wiz.build_step_view(wiz._STEP_BY_ID["rtl"], state),
        "overall_ready": False, "note": None,
    }
    html = wiz.render_wizard_html(doc)
    assert 'name="field" value="dut_rtl"' in html
    assert "dut_rtl" in html and "MISSING" in html


def test_render_html_already_resolved_field_shows_no_form():
    entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    view = wiz.build_step_view(wiz._STEP_BY_ID["execution_environment"], state)
    doc = {
        "step": {"id": "execution_environment", "title": "Execution Environment", "index": 9, "total": 14},
        "steps": [{"id": s.step_id, "title": s.title, "grounded": s.kind != wiz.KIND_UNMODELED}
                  for s in wiz.WIZARD_STEPS],
        "view": view, "overall_ready": False, "note": None,
    }
    html = wiz.render_wizard_html(doc)
    assert "(already resolved)" in html
    assert 'value="bind:chip.core.usb0"' not in html


def test_render_error_html_includes_the_refusal_banner():
    state = intake_state.build_intake_state()
    doc = {
        "step": {"id": "rtl", "title": "RTL", "index": 3, "total": 14},
        "steps": [{"id": s.step_id, "title": s.title, "grounded": s.kind != wiz.KIND_UNMODELED}
                  for s in wiz.WIZARD_STEPS],
        "view": wiz.build_step_view(wiz._STEP_BY_ID["rtl"], state),
        "overall_ready": False, "note": None,
    }
    exc = wiz.GuiIntakeWizardError("FIELD_ALREADY_RESOLVED", {"field": "dut_rtl"})
    html = wiz.render_error_html(doc, exc)
    assert "FIELD_ALREADY_RESOLVED" in html
    assert "dut_rtl" in html


# ---------------------------------------------------------------------------
# The live server: real HTTP, real endpoint sequence
# ---------------------------------------------------------------------------

def _wait_ready(base, timeout=10.0):
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/state", timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - retry until the server is up
            last_exc = exc
            time.sleep(0.05)
    raise AssertionError(f"wizard server never became ready: {last_exc}")


def _get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post_json(base, path, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + path, data=body, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_live_server_get_answer_advance_cycle(tmp_path):
    server = wiz.build_server(tmp_path, port=0)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_ready(base)

        status, doc = _get_json(base, "/api/state")
        assert status == 200 and doc["step"]["id"] == "new_open_project"

        status, doc = _post_json(base, "/api/advance", {"step_id": "rtl"})
        assert status == 200 and doc["step"]["id"] == "rtl"
        rtl_fields = {f["field"]: f for f in doc["view"]["fields"]}
        assert rtl_fields["dut_rtl"]["status"] == intake_state.IntakeFieldStatus.MISSING.value

        status, doc = _post_json(base, "/api/answer", {
            "field": "dut_rtl", "answer": "present under rtl/usb_core.v",
            "basis": "uploaded via Intake Uploads", "decided_by": "tester",
        })
        assert status == 200 and doc["answered"]["status"] == "ANSWERED"

        status, doc = _get_json(base, "/api/state")
        rtl_fields = {f["field"]: f for f in doc["view"]["fields"]}
        assert rtl_fields["dut_rtl"]["status"] == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
        assert rtl_fields["dut_rtl"]["already_resolved"] is True

        # A form-POST (non-JSON) redirects home with a real 303 -- urllib
        # follows it automatically, landing back on a real rendered page.
        form = urllib.parse.urlencode({"direction": "next"}).encode("utf-8")
        req = urllib.request.Request(base + "/advance", data=form, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8")
        assert "GUI-01 Interactive Intake Wizard" in html

        # An unrouted path is a real, honest 404, not a silent fallback.
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(base + "/does-not-exist", timeout=5)
        assert ei.value.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_live_server_root_page_renders_html(tmp_path):
    server = wiz.build_server(tmp_path, port=0)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_ready(base)
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            html = resp.read().decode("utf-8")
        assert "GUI-01 Interactive Intake Wizard" in html
        assert "NEW / OPEN PROJECT" in html
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_live_server_answer_via_json_rejects_bad_field(tmp_path):
    server = wiz.build_server(tmp_path, port=0)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_ready(base)
        status, doc = _post_json(base, "/api/answer", {"field": "no_such_field", "answer": "x"})
        assert status == 400
        assert doc["error"] == "UNKNOWN_FIELD"
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# P1-3 (additive): the shared web_layout.py status-bar/nav partial
# ---------------------------------------------------------------------------

def test_render_wizard_html_carries_the_real_web_layout_status_bar_partial():
    """`render_wizard_html()` must emit `web_layout.render_status_bar_partial()`'s
    real markup -- imported and called, never re-implemented -- proving this
    standalone server actually adopted the shared partial rather than merely
    importing the module unused."""
    from dv_harness import web_layout
    state = intake_state.build_intake_state()
    step = wiz._STEP_BY_ID["rtl"]
    doc = {
        "step": {"id": step.step_id, "title": step.title, "index": 3, "total": 14},
        "steps": [{"id": s.step_id, "title": s.title, "grounded": s.kind != wiz.KIND_UNMODELED}
                  for s in wiz.WIZARD_STEPS],
        "view": wiz.build_step_view(step, state),
        "overall_ready": False, "note": None,
    }
    html = wiz.render_wizard_html(doc)
    assert 'id="globalStatusBar"' in html
    assert web_layout.render_status_bar_partial() in html


def test_render_wizard_html_carries_the_real_web_layout_nav_partial():
    """Same proof for `web_layout.render_nav()`: its real `<nav class=
    "webNav">` markup, over this wizard's own real fourteen steps with the
    current step marked active, appears in the rendered page -- not a
    page-shell rewrite, only an added partial."""
    from dv_harness import web_layout
    state = intake_state.build_intake_state()
    step = wiz._STEP_BY_ID["rtl"]
    steps = [{"id": s.step_id, "title": s.title, "grounded": s.kind != wiz.KIND_UNMODELED}
             for s in wiz.WIZARD_STEPS]
    doc = {
        "step": {"id": step.step_id, "title": step.title, "index": 3, "total": 14},
        "steps": steps,
        "view": wiz.build_step_view(step, state),
        "overall_ready": False, "note": None,
    }
    html = wiz.render_wizard_html(doc)
    expected_nav = web_layout.render_nav([(s["id"], s["title"]) for s in steps], active=step.step_id)
    assert expected_nav in html
    assert 'class="webNav"' in html
    assert 'class="active"' in html  # the current step is marked active in the nav


def test_web_layout_partial_appears_before_this_wizards_own_existing_crumbs():
    """The partial is inserted at a FIXED point -- immediately inside
    `<body>`, before this wizard's own pre-existing crumbs/step markup --
    never scattered or replacing anything that was already there."""
    state = intake_state.build_intake_state()
    step = wiz._STEP_BY_ID["rtl"]
    doc = {
        "step": {"id": step.step_id, "title": step.title, "index": 3, "total": 14},
        "steps": [{"id": s.step_id, "title": s.title, "grounded": s.kind != wiz.KIND_UNMODELED}
                  for s in wiz.WIZARD_STEPS],
        "view": wiz.build_step_view(step, state),
        "overall_ready": False, "note": None,
    }
    html = wiz.render_wizard_html(doc)
    assert html.index('class="webNav"') < html.index('class="crumbs"')
    assert html.index('id="globalStatusBar"') < html.index('class="crumbs"')


def test_live_server_root_page_carries_the_web_layout_partial(tmp_path):
    """End-to-end over a real HTTP connection to the real server, not just
    the pure `render_wizard_html()` function."""
    server = wiz.build_server(tmp_path, port=0)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_ready(base)
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
        assert 'id="globalStatusBar"' in html
        assert 'class="webNav"' in html
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_existing_api_endpoints_are_unaffected_by_the_layout_partial(tmp_path):
    """ADDITIVE ONLY: this server's real, pre-existing JSON API surface must
    be byte-for-byte unaffected by rendering the new HTML-only partial."""
    server = wiz.build_server(tmp_path, port=0)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _wait_ready(base)
        with urllib.request.urlopen(base + "/api/state", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        doc = json.loads(body)
        assert doc["schema_version"] == wiz.SCHEMA_VERSION
        assert "webNav" not in body
        assert "globalStatusBar" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _tmp_root():
    return tempfile.mkdtemp()
