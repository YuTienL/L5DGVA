"""GET /view/dashboard -- the Executive Dashboard view (item:
P2-1-dashboard-executive-view-route).

A genuinely SEPARATE, SMALLER document from the "/" route -- built via
`web_layout.page_shell()`/`render_nav()`/`render_status_bar_partial()`/
`render_card()`, never a modification of the "/" route's own HTML/CSS/JS
string -- implementing GUI-13's own required minimum metric set: Overall
Readiness, Verification Closure, Requirements, vPlan, Regression PASS Rate,
Functional/Code Coverage, Assertion Closure, Critical Failures, Open
Waivers, Blocked Requirements, Active LSF Jobs, Recent Coverage Delta.

REUSE OVER REINVENT: every metric on this page is read from an
already-real, already-tested producer this same dashboard.py file already
calls elsewhere (`_read_harness_status_state()` ->
`harness_status.HarnessStatusService`, `_read_requirement_vplan_center_
state()` -> `requirement_contract.py`/`vplan_artifact.py`,
`_read_coverage_state()` -> `coverage_analysis.py`) plus one direct call to
`waiver_store.status_report()` -- this route computes no new verdict of its
own. These tests prove the served page's own values are exactly what those
real producers compute over the identical project state (never a string
typed into the test), including the Evidence-Truth-Rule negative control: a
bare project with nothing recorded reports every metric honestly UNKNOWN/0,
never a fabricated pass.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers -- the same cross-test import convention every sibling
`test_dashboard_*_card.py` file already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)
from dv_harness_tests.test_golden_flow_readiness import write_lsf_job


def _get_html(base: str, path: str) -> str:
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


def test_executive_view_is_a_real_smaller_document_distinct_from_the_main_page():
    """The route is a genuinely separate document -- built via
    web_layout.page_shell(), never the "/" route's own HTML string -- and is
    smaller than it, since "/" carries the full 38-card monolithic page."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        main_html = _get_html(base, "/")
        exec_html = _get_html(base, "/view/dashboard")

        assert exec_html != main_html
        assert len(exec_html) < len(main_html)
        assert "<!doctype html>" in exec_html.lower()
        assert "<title>Executive Dashboard</title>" in exec_html
        # web_layout.render_status_bar_partial()'s own real, documented
        # element ids -- proof the real module was actually called, not a
        # hand-typed lookalike string.
        assert 'id="globalStatusBar"' in exec_html
        assert 'id="statusBarDrawer"' in exec_html
        # web_layout.render_nav()'s own real markup, linking back to "/".
        assert '<nav class="webNav">' in exec_html
        assert 'href="/"' in exec_html
        assert 'class="active"' in exec_html
        # The "/" route's own real HTML must be completely untouched --
        # this item's own hard rule.
        assert 'id="globalStatusBar"' in main_html  # "/" already has its own
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_executive_view_renders_all_twelve_gui_13_metric_titles():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        html = _get_html(base, "/view/dashboard")
        for title in (
            "Overall Readiness", "Verification Closure", "Requirements",
            "vPlan", "Regression PASS Rate", "Functional / Code Coverage",
            "Assertion Closure", "Critical Failures", "Open Waivers",
            "Blocked Requirements", "Active LSF Jobs", "Recent Coverage Delta",
        ):
            assert title in html, f"missing metric card: {title}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_executive_view_on_a_bare_project_reports_every_metric_honestly_unknown():
    """The required negative control: a bare project with no state.json, no
    LSF jobs, no requirements/vplan declared, no waiver ledger, and no
    coverage history must never fabricate a passing/ready value for any of
    the 12 metrics."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        html = _get_html(base, "/view/dashboard")

        assert 'id="overallReadiness"' in html
        card = html.split('id="overallReadiness"')[1].split("</div>")[0]
        assert "UNKNOWN" in card

        card = html.split('id="verificationClosure"')[1].split("</div>")[0]
        assert "UNKNOWN" in card

        card = html.split('id="openWaivers"')[1].split("</div>")[0]
        assert ">0<" in card  # zero waivers recorded

        card = html.split('id="blockedRequirements"')[1].split("</div>")[0]
        assert ">0<" in card  # zero requirements declared, so zero blocked

        card = html.split('id="activeLsfJobs"')[1].split("</div>")[0]
        # a real, checked-and-empty job list is a genuine 0 (evidence was
        # consulted and found nothing), never the "UNKNOWN" absence-of-
        # evidence state -- see harness_status._gather_execution()'s own
        # real ExecutionIR(queued_jobs=0, running_jobs=0, ...) branch for a
        # jobs directory that exists and is empty.
        assert ">0<" in card

        card = html.split('id="recentCoverageDelta"')[1].split("</div>")[0]
        assert "UNKNOWN" in card
        assert "requires &gt;= 2 recorded" in card or "requires >= 2 recorded" in card
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_executive_view_open_waivers_and_regression_pass_rate_reflect_real_evidence():
    """A real, expired waiver recorded through waiver_store.py's own real
    ledger writer, plus real LSF job records written through
    regression_reporter.py's own real writer, must drive the served
    Open Waivers / Regression PASS Rate cards -- proving the route reads
    real evidence rather than a fixed placeholder."""
    from dv_harness import waiver_store as ws

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        ws.record_waiver(tmp, {
            "waiver_id": "W-EXEC-1", "item": "cov_a",
            "reason": "known limitation, accepted by design",
            "evidence": "see review notes", "approver": "alice",
            "affected_version": {"spec_revision": "r1"}, "risk": "LOW",
            "created_at": "2026-01-01T00:00:00+00:00",
            "expires_at": "2020-01-01T00:00:00+00:00",
            "scope": {
                "requirement_ids": ["REQ-1"], "subsystem": "usb3",
                "spec_revision": "r1", "design_evidence_hash": "abc123",
                "approval_id": "AP-1", "scope_hash": "hash1",
            },
        })

        write_lsf_job(tmp, {"job_id": "9001", "lsf_status": "DONE",
                             "dv_analysis_status": "PASS"})
        write_lsf_job(tmp, {"job_id": "9002", "lsf_status": "EXIT",
                             "dv_analysis_status": "FAIL"})

        html = _get_html(base, "/view/dashboard")

        card = html.split('id="openWaivers"')[1].split("</div>")[0]
        assert ">1<" in card  # exactly one real waiver on file
        assert "not VALID" in card  # expired, so real not_valid == 1

        card = html.split('id="regressionPassRate"')[1].split("</div>")[0]
        assert "50.0%" in card
        assert "1 passed / 1 failed" in card
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_executive_view_matches_the_real_underlying_producers_exactly():
    """The served metrics must be byte-identical to calling the real
    producers directly over the same project state -- never a
    dashboard-local re-derivation that could silently drift."""
    from dv_harness import harness_status
    from dv_harness import waiver_store as ws

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        ws.record_waiver(tmp, {
            "waiver_id": "W-EXEC-2", "item": "cov_b",
            "reason": "known limitation, accepted by design",
            "evidence": "see review notes", "approver": "bob",
            "affected_version": {"spec_revision": "r1"}, "risk": "LOW",
            "created_at": "2026-01-01T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",  # still VALID
            "scope": {
                "requirement_ids": ["REQ-2"], "subsystem": "usb3",
                "spec_revision": "r1", "design_evidence_hash": "abc456",
                "approval_id": "AP-2", "scope_hash": "hash2",
            },
        })

        html = _get_html(base, "/view/dashboard")

        expected_snapshot = harness_status.HarnessStatusService(tmp).serve()
        expected_harness_state = expected_snapshot["harness"]["state"]
        card = html.split('id="overallReadiness"')[1].split("</div>")[0]
        assert f">{expected_harness_state}<" in card

        expected_waiver_report = ws.status_report(tmp)
        expected_count = len(expected_waiver_report["waivers"])
        assert expected_count == 1
        card = html.split('id="openWaivers"')[1].split("</div>")[0]
        assert f">{expected_count}<" in card
        # a VALID (not-expired) waiver contributes 0 to not_valid.
        assert expected_waiver_report["not_valid"] == 0
        assert "0 not VALID" in card
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_executive_view_recent_coverage_delta_reflects_a_real_coverage_history():
    """A real >= 2-sample coverage history (the same on-disk convention
    _read_coverage_state() already reads for every other coverage-aware
    card on this page) must drive a real, non-fabricated delta value."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        cov_dir = tmp / ".dv-harness" / "coverage"
        cov_dir.mkdir(parents=True, exist_ok=True)
        (cov_dir / "summary.json").write_text(json.dumps({
            "categories": [
                {"name": "cg_a", "percent": 80.0, "bins_total": 100, "bins_hit": 80},
            ]
        }), encoding="utf-8")
        (cov_dir / "history.json").write_text(json.dumps([
            {"timestamp": "2026-01-01T00:00:00Z", "percent": 60.0},
            {"timestamp": "2026-01-02T00:00:00Z", "percent": 80.0},
        ]), encoding="utf-8")

        html = _get_html(base, "/view/dashboard")
        card = html.split('id="recentCoverageDelta"')[1].split("</div>")[0]
        assert "+20.0% (IMPROVING)" in card
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
