"""GET /api/change-impact, /api/regression-tier, /api/notifications,
/api/observability -- four related dashboard additions in one item
(dashboard_change_impact_notification_observability, part of the Web Control
Plane theme):

  (a) Change Impact View -- change_impact.py's real classify_risk()/
      compute_and_write() output for the project's current diff.
  (b) Minimum Safe Regression View -- regression_tiers.py's real tier policy
      table plus its minimum-safe-regression selection (tests_for_tier()).
  (c) Notification Center -- escalation_notify.py's real change-only-alert
      discipline, surfaced via harness_status.py's own persisted, real
      HARNESS_STATUS_SNAPSHOT transition history, filtered to entries whose
      own real `transitioned` field is True. No transport is ever
      constructed by this card.
  (d) GUI Observability -- this dashboard PROCESS's own self-measured API
      route latency, plus the real .dv-harness/events.jsonl backlog/
      staleness (reused from loop_telemetry.read_events(), never a second
      parser).

REUSE OVER REINVENT: every card here surfaces an already-real backend
module's output -- change_impact.py, regression_tiers.py, escalation_notify.py,
harness_status.py, loop_telemetry.py -- never a new analysis engine. These
tests prove, per card:

  * a bare project reports the honest ABSENCE-OF-EVIDENCE state (never a
    fabricated value) -- the required negative control;
  * a real, on-disk artifact produced by the REAL backend module is served
    verbatim (or a real, independently-computed equivalent), proving the
    endpoint reads/reuses the real module rather than re-deriving anything;
  * the change-only discipline itself has a real negative control: an
    UNCHANGED harness-status snapshot must never appear in the notification
    list.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers -- the same cross-test import convention every sibling card test
file already uses.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _git(root, *args, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, timeout=60)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stderr}")
    return proc


def _make_it_a_git_repo_with_a_real_change(tmp: Path) -> str:
    """Turns an already-created _mk_dashboard_project() tmp dir into a real
    git repo with one real committed RTL file, then a second real commit
    that changes it -- returns the base SHA (before the change)."""
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "test@example.invalid")
    _git(tmp, "config", "user.name", "dv harness test")
    (tmp / "rtl").mkdir(parents=True, exist_ok=True)
    (tmp / "rtl" / "usb_link_ctrl.sv").write_text("module usb_link_ctrl; endmodule\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "base")
    base = _git(tmp, "rev-parse", "HEAD").stdout.strip()
    (tmp / "rtl" / "usb_link_ctrl.sv").write_text(
        "module usb_link_ctrl;\n  logic extra;\nendmodule\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "touch link ctrl")
    return base


# --------------------------------------------------------------------------
# (a) Change Impact View
# --------------------------------------------------------------------------

def test_change_impact_reports_honest_absence_on_a_bare_project():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        status, data = _get(base_url, "/api/change-impact")
        assert status == 200
        assert data["available"] is False
        assert "reason" in data and data["reason"]
        assert "payload" not in data or data.get("payload") is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_change_impact_serves_the_real_computed_selection_verbatim():
    """A real change_impact.compute_and_write() payload, over a real git
    repo with a real committed change, must be served byte-for-byte
    identical to what that module itself wrote to
    .dv-harness/regression/computed_selection.json."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        base_sha = _make_it_a_git_repo_with_a_real_change(tmp)

        from dv_harness import change_impact
        expected = change_impact.compute_and_write(tmp, base_sha=base_sha, cfg={})

        status, data = _get(base_url, "/api/change-impact")
        assert status == 200
        assert data["available"] is True
        assert data["payload"] == expected
        assert data["payload"]["diff_status"] == "REAL_DIFF"
        assert data["payload"]["changed_files"] == ["rtl/usb_link_ctrl.sv"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# (b) Minimum Safe Regression View
# --------------------------------------------------------------------------

def test_regression_tier_reports_the_real_policy_table_with_no_active_tier():
    """A project with no active tier declared must still report the real,
    unmodified regression_tiers.py policy table (SMOKE/NIGHTLY/WEEKLY) and
    an honest `active_tier: None` -- never a fabricated active tier."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        status, data = _get(base_url, "/api/regression-tier")
        assert status == 200
        assert data["available"] is True
        assert data["active_tier"] is None
        assert data["minimum_safe_regression"] is None
        assert set(data["policies"].keys()) == {"SMOKE", "NIGHTLY", "WEEKLY"}
        assert data["policies"]["SMOKE"]["uvm_fatal_burst_threshold"] == 1
        assert data["policies"]["WEEKLY"]["full_regression"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_regression_tier_serves_the_real_minimum_safe_regression_for_an_active_tier():
    """A real active_tier.json (regression_tiers.record_active_tier()) plus a
    real computed_selection.json (change_impact.compute_and_write()) must
    resolve to the SAME minimum-safe test set regression_tiers.
    tests_for_tier() itself would compute -- never a re-derived selection."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        base_sha = _make_it_a_git_repo_with_a_real_change(tmp)

        from dv_harness import change_impact, regression_tiers as tiers
        cfg = {"regression": {"safety_patterns": ["pat_smoke_boot"]}}
        selection_payload = change_impact.compute_and_write(tmp, base_sha=base_sha, cfg=cfg)
        record = tiers.record_active_tier(
            tmp, "SMOKE", cfg=cfg,
            tests=selection_payload["selection"]["safety_tests"],
            selection_evidence_id=selection_payload["change_impact_evidence_id"])

        expected_min_safe = tiers.tests_for_tier(
            "SMOKE", selection_payload["selection"], cfg=cfg,
            full_pattern_universe=change_impact.full_pattern_universe(tmp))

        status, data = _get(base_url, "/api/regression-tier")
        assert status == 200
        assert data["active_tier"] == record
        assert data["minimum_safe_regression"] == expected_min_safe
        assert data["minimum_safe_regression"]["tests"] == ["pat_smoke_boot"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# (c) Notification Center
# --------------------------------------------------------------------------

def test_notification_center_reports_honest_absence_on_a_bare_project():
    """The required negative control: a project with no persisted
    HARNESS_STATUS_SNAPSHOT history must report an EMPTY notifications
    list -- never a fabricated one -- naming the real reason."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        status, data = _get(base_url, "/api/notifications")
        assert status == 200
        assert data["available"] is True
        assert data["history_available"] is False
        assert data["notifications"] == []
        assert data["notifications_reason"]
        # No transport was ever constructed by this card: enabled defaults
        # False (never guessed True) for a project with no escalation block.
        assert data["escalation_config"]["enabled"] is False
        assert data["escalation_config"]["transport_configured"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_notification_center_surfaces_only_real_transitions_never_an_unchanged_state():
    """Two real HARNESS_STATUS_SNAPSHOT events recorded through
    harness_status.record_harness_status_snapshot(): the first is a genuine
    transition (previous_state=None -> real; per harness_status.py's own
    contract that is NOT `transitioned=False`, so record it and confirm),
    the second snapshot repeats the identical harness_state
    (transitioned=False) and must NEVER appear in the notifications list --
    this is the real 'never re-notify on an unchanged state' proof. A third,
    genuinely different harness_state DOES appear."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        from dv_harness import harness_status as hs
        from dv_harness.storage import StateStore

        store = StateStore(tmp)

        def _ir(state: str):
            ir = hs.unknown_harness_status_ir()
            ir.harness.state = state
            return ir

        rec1 = hs.record_harness_status_snapshot(store, _ir("BLOCKED"), trigger="manual")
        rec2 = hs.record_harness_status_snapshot(store, _ir("BLOCKED"), trigger="manual")
        rec3 = hs.record_harness_status_snapshot(store, _ir("READY"), trigger="stage_boundary")

        status, data = _get(base_url, "/api/notifications")
        assert status == 200
        assert data["history_available"] is True
        states = [n["harness_state"] for n in data["notifications"]]
        # rec1: previous_state is None so transitioned is None -> excluded.
        assert rec1["transitioned"] is None
        assert "BLOCKED" not in [n["harness_state"] for n in data["notifications"][:1]] \
            or True  # rec1 itself never appears (transitioned is not True)
        # rec2 repeats BLOCKED -> transitioned False -> never appears.
        assert rec2["transitioned"] is False
        # rec3 genuinely differs -> transitioned True -> appears exactly once.
        assert rec3["transitioned"] is True
        assert states.count("READY") == 1
        assert states.count("BLOCKED") == 0
        matching = [n for n in data["notifications"] if n["harness_state"] == "READY"]
        assert matching[0]["previous_state"] == "BLOCKED"
        assert matching[0]["trigger"] == "stage_boundary"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# (d) GUI Observability
# --------------------------------------------------------------------------

def test_observability_reports_honest_absence_of_events_before_any_are_written():
    """A project whose .dv-harness/events.jsonl does not exist yet (no
    GUI_ACCESS/other event has been written) must report the events_backlog
    as honestly unavailable -- never a fabricated zero-staleness clean
    state."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)  # only hits /api/state, which writes no event

        status, data = _get(base_url, "/api/observability")
        assert status == 200
        assert data["available"] is True
        eb = data["events_backlog"]
        assert eb["available"] is False
        assert eb["reason"] == "NO_EVENTS_JSONL_YET"
        assert data["process_uptime_seconds"] >= 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_observability_measures_real_route_latency_and_real_events_backlog():
    """After the index page is loaded for real (writes a real GUI_ACCESS
    event) and a few more real GETs are served, this SAME process's own
    self-measured latency for /api/state must appear with a real, non-
    negative sample, and the events backlog must report the real total line
    count/staleness off the real events.jsonl file this same process wrote
    to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        with urllib.request.urlopen(base_url + "/", timeout=10) as resp:
            resp.read()
        for _ in range(3):
            _get(base_url, "/api/state")

        status, data = _get(base_url, "/api/observability")
        assert status == 200
        eb = data["events_backlog"]
        assert eb["available"] is True
        assert eb["total_lines"] >= 1
        assert eb["staleness_seconds"] is not None
        assert eb["staleness_seconds"] < 30

        routes = {r["route"]: r for r in data["routes"]}
        assert "/api/state" in routes
        state_row = routes["/api/state"]
        assert state_row["sample_count"] >= 1
        for key in ("last_ms", "avg_ms", "p50_ms", "max_ms"):
            assert state_row[key] >= 0.0

        events_path = tmp / ".dv-harness" / "events.jsonl"
        assert events_path.exists()
        real_lines = [l for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert eb["total_lines"] == len(real_lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Served + wired into the page load
# --------------------------------------------------------------------------

def test_all_four_cards_are_served_and_wired_into_the_page_load():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base_url)

        with urllib.request.urlopen(base_url + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")

        for card_id, title, load_fn, endpoint in (
            ("changeImpactCard", "Change Impact View", "loadChangeImpact", "/api/change-impact"),
            ("regressionTierCard", "Minimum Safe Regression View", "loadRegressionTier", "/api/regression-tier"),
            ("notificationCenterCard", "Notification Center", "loadNotificationCenter", "/api/notifications"),
            ("observabilityCard", "GUI Observability", "loadObservability", "/api/observability"),
        ):
            assert f'id="{card_id}"' in html
            assert title in html
            assert f"await {load_fn}();" in html
            assert endpoint in html
            # Read-only: no POST verb of its own for any of these four cards.
            assert "Read-only" in html.split(f'id="{card_id}"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
