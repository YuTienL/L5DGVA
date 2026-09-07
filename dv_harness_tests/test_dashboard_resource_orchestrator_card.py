"""GET /api/resource-orchestrator -- the Resource Orchestrator dashboard card
(resource-orchestrator-no-dashboard-card).

resource_orchestrator.py (VI-5's global cross-job license/queue-slot
arbitration, 53 tests) already has its own real `python -m
dv_harness.resource_orchestrator` front door and its own real `dv-harness
resource-orchestrator` CLI verb, but before this change had zero real usage
in dashboard.py: `grep -c resource_orchestrator dv_harness/dashboard.py`
returned 0, and cli.py's own wired-verb table already covered the CLI --
only the dashboard-card gap was real and current.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers rather than standing up a second one -- the same cross-test import
convention test_dashboard_amba_bottleneck_card.py already uses. Every
license-headroom fixture is the REAL captured `lmutil lmstat` output
resource_orchestrator's own test suite already imports from
test_preflight.py, reused here rather than re-typed.
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
    _write_json,
)
from dv_harness_tests.test_resource_orchestrator import _lmstat_with


def _two_requests_one_seat_doc():
    """Two real, buildable requests, both consuming the scarce resource, one
    real measured license seat available: the earlier-requested contender
    must be GRANTED and the later one QUEUED -- a real, checkable FIFO
    arbitration outcome, not a fabricated one."""
    return {
        "requests": [
            {"project_id": "proj-a", "stage": "IMPLEMENT",
             "consumes_scarce_resource": True,
             "requested_at": "2026-01-01T00:00:00Z"},
            {"project_id": "proj-b", "stage": "IMPLEMENT",
             "consumes_scarce_resource": True,
             "requested_at": "2026-01-01T01:00:00Z"},
        ],
        "checks": [
            {"name": "eda_license", "status": "PASS",
             "detail": "1 free VCSRuntime seat",
             "evidence": _lmstat_with(1, 0, "VCSRuntime")},
        ],
    }


def _write_inputs(tmp: Path, doc=None) -> Path:
    from dv_harness.dashboard import _default_resource_orchestrator_inputs_path

    path = _default_resource_orchestrator_inputs_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc if doc is not None else _two_requests_one_seat_doc())
    return path


def test_resource_orchestrator_reports_honest_empty_state_when_no_inputs_exist():
    """No plan inputs have been declared for this project: the endpoint must
    say so and name the path it looked at, never invent a plan -- the same
    honest-empty-state contract the AMBA cards already hold to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/resource-orchestrator")
        assert status == 200
        assert data["available"] is False
        assert data["plan"] is None
        assert data["skipped"] == []
        assert data["error"] is None
        assert data["inputs_path"].endswith("plan_inputs.json")
        assert not Path(data["inputs_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_builds_a_real_plan_with_grant_and_queue():
    """The two declared requests must come back with the exact GRANTED/QUEUED
    decisions resource_orchestrator.orchestrate() itself produces against the
    real, measured 1-seat license capacity -- never a dashboard-local
    re-derivation of the arbitration rule."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_inputs(tmp)

        status, data = _get(base, "/api/resource-orchestrator")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        plan = data["plan"]
        assert plan is not None
        assert plan["granted"] == 1
        assert plan["queued"] == 1
        assert plan["deferred"] == 0
        assert plan["capacity"]["slots_available"] == 1
        assert plan["capacity"]["binding_constraint"] == "license_free_seats"

        by_project = {a["project_id"]: a for a in plan["allocations"]}
        assert by_project["proj-a"]["decision"] == "GRANTED"
        assert by_project["proj-a"]["rank"] == 1
        assert by_project["proj-b"]["decision"] == "QUEUED"
        assert "disclosure" in plan and plan["disclosure"]
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_reports_no_contenders_honestly_when_none_declared():
    """Omitting `requests` entirely means "build contenders from the real
    cross-project registry" -- a bare project with nothing registered must
    report the real NO_CONTENDERS note, never a fabricated plan."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        from dv_harness.dashboard import _default_resource_orchestrator_inputs_path
        path = _default_resource_orchestrator_inputs_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, {"checks": []})

        status, data = _get(base, "/api/resource-orchestrator")
        assert status == 200
        assert data["available"] is True
        assert data["plan"] is None
        assert data["error"] is None
        assert "NO_CONTENDERS" in (data["note"] or "")
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_reports_malformed_request_rather_than_a_500():
    """A declared request missing a required field (stage) must be refused
    by the real module and surfaced as MALFORMED_REQUEST -- never a bare
    500 and never a fabricated plan built over broken data."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_inputs(tmp, {"requests": [
            {"project_id": "proj-a", "consumes_scarce_resource": True},
        ]})

        status, data = _get(base, "/api/resource-orchestrator")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_REQUEST"
        assert data["plan"] is None
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_reports_malformed_inputs_file_rather_than_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import _default_resource_orchestrator_inputs_path
        p = _default_resource_orchestrator_inputs_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        status, data = _get(base, "/api/resource-orchestrator")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert data["plan"] is None
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_inputs_path_is_overridable_by_query_param():
    """Mirrors GET /api/amba-bottleneck's ?candidates= override: a project
    whose plan-input declarations live elsewhere points at it, rather than
    this module guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        elsewhere = tmp / "ro_out" / "inputs.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        _write_json(elsewhere, _two_requests_one_seat_doc())

        status, data = _get(base, "/api/resource-orchestrator")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/resource-orchestrator?inputs="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["inputs_path"] == str(elsewhere)
        assert data["plan"]["granted"] == 1
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    project's Methodology Consolidation Rule exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="resourceOrchestratorCard"' in html
        assert "Resource Orchestrator" in html
        assert "'/api/resource-orchestrator'" in html
        assert "await loadResourceOrchestrator();" in html
        assert 'id="resourceOrchestratorTable"' in html
        assert "Read-only" in html
    finally:
        shutil.rmtree(tmp)


def test_resource_orchestrator_never_renders_a_bind_statement():
    """A planning surface accidentally rendering emittable SystemVerilog
    would be a way past this project's usual review discipline -- the card
    and its JSON payload must never carry a `bind` statement."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_inputs(tmp)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        _, data = _get(base, "/api/resource-orchestrator")

        assert "\nbind " not in html and " bind (" not in html
        payload = json.dumps(data)
        assert "\nbind " not in payload and " bind (" not in payload
    finally:
        shutil.rmtree(tmp)
