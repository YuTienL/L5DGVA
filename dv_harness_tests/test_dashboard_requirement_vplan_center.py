"""GET /api/requirement-vplan-center -- the Requirement/vPlan Center dashboard
card (item: dashboard_requirement_vplan_center, Web Control Plane theme,
CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections 342-402).

REUSE OVER REINVENT: `dv_harness/requirement_contract.py` and
`dv_harness/vplan_artifact.py` already exist and already compute the real
five-value requirement status / nine-dimension vPlan completeness / fifteen-
value gap taxonomy this card needs -- this change adds NO new analysis engine
behind the card. It is a pure dashboard wiring gap, closed the same way the
Generation Readiness Center and Design Knowledge Explorer cards were: a thin
`_read_requirement_vplan_center_state()` reader following the file's existing
`{"available", "error"}` honest-empty-state contract, one read-only GET
endpoint, and a fetch-once + client-side-render card.

Neither `requirement_contract.py` nor `vplan_artifact.py` discovers a
project's own records itself (both take a plain caller-supplied record list),
so this card reads whatever a real upstream extraction step wrote to
`.dv-harness/requirement_vplan/requirements.json` and `.../vplan.json` --
mirroring the exact convention `design_knowledge_correlation.py`'s own
`sources.json` card already established.

These tests prove:
  * The card READS the real modules. Every asserted value is compared against
    what `requirement_contract.analyze_requirement_contract_set()` and
    `vplan_artifact.analyze_vplan_completeness()` themselves compute over the
    identical record set -- never a string typed into the test, so a
    dashboard-local re-derivation that drifted from the real analysis would
    fail here.
  * The Evidence Truth Rule holds on the served surface: a project with
    neither file on disk must never render a fabricated table, and a
    malformed input file must surface its own reason/detail rather than a
    bare 500 or a silently empty card -- the negative control this project's
    house style requires.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention test_dashboard_generation_readiness_
card.py already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)

REQ_COMPLETE = {
    "contract_schema_version": "1.0",
    "requirement_id": "REQ-1",
    "source": {"document": "spec.pdf", "section": "4.2"},
    "feature": "USB3 link training",
    "protocol": "USB3",
    "configuration": "default",
    "precondition": "PHY ready",
    "stimulus": "assert LINK_TRAIN",
    "expected_result": "link reaches U0",
    "observability": "LTSSM state register",
    "checker": "ltssm_checker",
    "coverage_intent": "cover LTSSM states",
    "priority": "P1",
    "criticality": "MAJOR",
    "confidence": "HIGH",
    "status": "COMPLETE",
    "ambiguities": [],
    "contradictions": [],
}

VPLAN_ROWS = [
    {
        "id": "ROW-1", "row_type": "leaf", "parent_id": None,
        "name": "link training test",
        "requirement_refs": ["REQ-1"], "verification_method": "SIMULATION",
        "coverage_refs": ["cg_ltssm"], "checker_refs": ["ltssm_checker"],
        "test_refs": ["test_link_train"],
        "owner": "alice", "priority": "P1",
    },
]


def _write_center_files(tmp: Path, requirements=None, vplan_rows=None):
    d = tmp / ".dv-harness" / "requirement_vplan"
    d.mkdir(parents=True, exist_ok=True)
    if requirements is not None:
        (d / "requirements.json").write_text(json.dumps(requirements), encoding="utf-8")
    if vplan_rows is not None:
        (d / "vplan.json").write_text(json.dumps(vplan_rows), encoding="utf-8")


def test_requirement_vplan_center_honest_empty_state_on_a_bare_project():
    """Neither requirements.json nor vplan.json on disk -> an honest
    {"available": False} naming both real files this endpoint looked for,
    never a fabricated table."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/requirement-vplan-center")
        assert status == 200
        assert data["available"] is False
        assert data["error"] is None
        assert data["requirement_report"] is None
        assert data["vplan_report"] is None
        assert data["requirements_path"].endswith(
            str(Path(".dv-harness") / "requirement_vplan" / "requirements.json"))
        assert data["vplan_path"].endswith(
            str(Path(".dv-harness") / "requirement_vplan" / "vplan.json"))
    finally:
        shutil.rmtree(tmp)


def test_requirement_vplan_center_reports_a_malformed_requirements_file_honestly():
    """A requirements.json that is not valid JSON must surface as this
    endpoint's own reason/detail -- never a bare 500, and never a silently
    empty card claiming nothing is wrong. The negative control this
    project's house style requires."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        d = tmp / ".dv-harness" / "requirement_vplan"
        d.mkdir(parents=True)
        (d / "requirements.json").write_text("not valid json{", encoding="utf-8")

        status, data = _get(base, "/api/requirement-vplan-center")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_REQUIREMENTS_FILE"
    finally:
        shutil.rmtree(tmp)


def test_requirement_vplan_center_reports_a_vplan_schema_violation_honestly():
    """A vplan.json whose rows fail vplan_artifact.py's own schema must
    surface VPLAN_ARTIFACT_VALIDATION_FAILED naming the real error -- never a
    fabricated matrix over a structurally invalid document."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        # A real structural defect (owner declared but not a string) --
        # vplan_artifact.validate_vplan_row() itself refuses this, never a
        # gap-report smoothing.
        _write_center_files(tmp, vplan_rows=[{"id": "ROW-1", "owner": 123}])

        status, data = _get(base, "/api/requirement-vplan-center")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "VPLAN_ARTIFACT_VALIDATION_FAILED"
    finally:
        shutil.rmtree(tmp)


def test_requirement_vplan_center_reports_the_real_reports_over_real_records():
    """Real requirements.json + vplan.json on disk -> the served
    requirement_report/vplan_report must equal what
    requirement_contract.analyze_requirement_contract_set() and
    vplan_artifact.analyze_vplan_completeness() themselves compute over the
    identical record set -- proving the endpoint reads the real modules
    rather than re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_center_files(tmp, requirements=[REQ_COMPLETE], vplan_rows=VPLAN_ROWS)

        status, data = _get(base, "/api/requirement-vplan-center")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        from dv_harness import requirement_contract as rc
        from dv_harness import vplan_artifact as va

        expected_req_report = rc.analyze_requirement_contract_set([REQ_COMPLETE])
        served_req = data["requirement_report"]
        assert served_req["analyzed"] == expected_req_report["analyzed"] == 1
        assert served_req["status_counts"] == expected_req_report["status_counts"]
        assert served_req["findings"] == expected_req_report["findings"]
        assert served_req["findings"] == []
        # Per-requirement rows the endpoint builds from the same real
        # derive_status()/downstream_consumable() calls.
        assert len(served_req["requirements"]) == 1
        row = served_req["requirements"][0]
        assert row["requirement_id"] == "REQ-1"
        assert row["declared_status"] == "COMPLETE"
        expected_status, expected_reason = rc.derive_status(REQ_COMPLETE)
        assert row["derived_status"] == expected_status == "COMPLETE"
        assert row["derived_reason"] == expected_reason
        expected_consumable, expected_consumable_reason = rc.downstream_consumable(REQ_COMPLETE)
        assert row["downstream_consumable"] == expected_consumable is True
        assert row["downstream_consumable_reason"] == expected_consumable_reason

        expected_report = va.analyze_vplan_completeness(
            VPLAN_ROWS, requirements=[{"id": "REQ-1"}], root=str(tmp))
        expected_dict = va.vplan_completeness_report_to_dict(expected_report)
        served_vr = data["vplan_report"]
        # generated_at is a real wall-clock stamp; strip before comparing so
        # this test never flakes across a second boundary.
        served_no_ts = {k: v for k, v in served_vr.items() if k not in ("generated_at", "gap_severity")}
        expected_no_ts = {k: v for k, v in expected_dict.items() if k != "generated_at"}
        assert served_no_ts == expected_no_ts

        # Every applicable dimension is READY over this fully-linked fixture
        # (the ninth, INTENT_CROSS_CONSISTENCY, is honestly UNKNOWN -- no
        # verification_intents were supplied).
        assert len(served_vr["dimensions"]) == 9
        for dim, result in served_vr["dimensions"].items():
            if dim == "INTENT_CROSS_CONSISTENCY":
                assert result["status"] == "UNKNOWN", (dim, result)
            else:
                assert result["status"] == "READY", (dim, result)
        assert served_vr["all_gaps"] == []

        # gap_severity is carried from the real module-level GAP_SEVERITY
        # table so the card can render each gap's real severity, never a
        # dashboard-local re-derivation of it.
        assert served_vr["gap_severity"] == dict(va.GAP_SEVERITY)
        assert len(served_vr["gap_severity"]) == len(va.GAP_TAXONOMY) == 15
    finally:
        shutil.rmtree(tmp)


def test_requirement_vplan_center_evidence_truth_rule_a_real_gap_is_never_hidden():
    """A vPlan row missing an owner/coverage link must produce a real,
    named GAP -- never silently smoothed into a clean pass -- and the
    dimension's own status must honestly reflect it (never READY)."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        broken_row = dict(VPLAN_ROWS[0])
        broken_row["owner"] = None
        broken_row["coverage_refs"] = []
        _write_center_files(tmp, requirements=[REQ_COMPLETE], vplan_rows=[broken_row])

        status, data = _get(base, "/api/requirement-vplan-center")
        assert status == 200
        assert data["available"] is True
        vr = data["vplan_report"]
        # GAP_MISSING_OWNER / GAP_MISSING_COVERAGE_LINK are both PARTIAL
        # severity (an honest absence, not a false traceability claim) per
        # vplan_artifact.GAP_SEVERITY -- so the dimension is PARTIAL, never
        # the fabricated READY the Evidence Truth Rule forbids.
        assert vr["dimensions"]["OWNERSHIP_ASSIGNMENT"]["status"] == "PARTIAL"
        assert vr["dimensions"]["COVERAGE_MODEL_LINKAGE"]["status"] == "PARTIAL"
        gap_codes = {g["gap"] for g in vr["all_gaps"]}
        assert "MISSING_OWNER" in gap_codes
        assert "MISSING_COVERAGE_LINK" in gap_codes
        # Every reported gap's severity must resolve through the real
        # served gap_severity table.
        for g in vr["all_gaps"]:
            assert g["gap"] in vr["gap_severity"]
        # A real gap must produce a real next-best-action, not silence.
        assert len(vr["next_best_actions"]) > 0
    finally:
        shutil.rmtree(tmp)


def test_requirement_vplan_center_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    item exists to avoid, and this card must follow the same rendering
    convention (tiles + tables, fetch-once, no new template) as the
    Generation Readiness / Design Knowledge cards it was asked to reuse."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="requirementVplanCard"' in html
        assert "Requirement / vPlan Center" in html
        assert "'/api/requirement-vplan-center'" in html
        assert "await loadRequirementVplan();" in html
        assert 'id="requirementVplanTiles"' in html
        assert 'id="requirementBody"' in html
        assert 'id="vplanDimensionsBody"' in html
        assert 'id="vplanGapsBody"' in html
        # This card is read-only, matching the convention every sibling
        # card it reuses follows -- no POST verb of its own.
        assert "Read-only" in html.split('id="requirementVplanCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
