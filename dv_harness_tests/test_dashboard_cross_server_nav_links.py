"""P2-2 (cross-server-nav-links): real, evidence-based `web_layout.render_nav()`
nav links out of `/view/dashboard` (P2-1) to the two existing standalone GUI
intake servers -- `gui_intake_wizard.py` and `gui_intake_control_plane.py`.

Every scenario is driven against the real dashboard server over real HTTP
(reusing `test_dashboard_interactive.py`'s own `_free_port`/
`_mk_dashboard_project`/`_start_dashboard`/`_wait_ready` helpers, the same
convention `test_status_acceptance.py`'s STATUS-AT-02/04/18 tests already
use), and the real evidence each link is built from is either a REAL
`gui_intake_control_plane` session file this test writes through that
module's own `issue_session_token()`, or a REAL TCP listener this test binds
itself -- never a hand-typed HTML string standing in for what
`dashboard._external_gui_server_nav_routes()` would produce.
"""
from __future__ import annotations

import json
import shutil
import socket
import threading
import urllib.request
from pathlib import Path

import pytest

from dv_harness_tests.test_dashboard_interactive import (
    _free_port, _mk_dashboard_project, _start_dashboard, _wait_ready,
)


def _get_html(base: str, path: str) -> str:
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        return resp.read().decode("utf-8")


def _port_is_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def test_nav_links_absent_from_root_page_present_on_view_dashboard(tmp_path):
    """The new links must be added ONLY to `/view/dashboard`'s own shell --
    never injected into the existing `/` page's markup."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        root_html = _get_html(base, "/")
        assert "gui_intake_control_plane" not in root_html
        assert "gui_intake_wizard" not in root_html
        assert "GUI Intake Control Plane" not in root_html
        assert "GUI Intake Wizard" not in root_html

        view_html = _get_html(base, "/view/dashboard")
        assert "GUI Intake Control Plane" in view_html
        assert "GUI Intake Wizard" in view_html
        # real <a> tags built by web_layout.render_nav(), not plain text
        assert '<a href="' in view_html
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_control_plane_not_running_reports_honestly_with_inert_href(tmp_path):
    """No `.dv-harness/intake_control_plane_session.json` on disk at all ->
    the honest "(not running)" label and an inert `href="#"`, never a
    guessed port."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        assert not (tmp / ".dv-harness" / "intake_control_plane_session.json").exists()
        view_html = _get_html(base, "/view/dashboard")
        assert "GUI Intake Control Plane (not running)" in view_html
        assert '<a href="#">GUI Intake Control Plane (not running)</a>' in view_html
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_control_plane_real_session_produces_a_real_live_link(tmp_path):
    """A REAL `gui_intake_control_plane` server's own real, persisted
    session record (host/port/token, written by that module's own
    `issue_session_token()` at real server start) must be read verbatim and
    turned into a real, working link -- never re-derived or guessed."""
    from dv_harness import gui_intake_control_plane as gicp

    dash_port = _free_port()
    tmp = _mk_dashboard_project(dash_port)
    try:
        dash_base = f"http://127.0.0.1:{dash_port}"

        gicp_server, gicp_token = gicp.build_server(tmp, port=0)
        gicp_port = gicp_server.server_address[1]
        gicp_thread = threading.Thread(target=gicp_server.serve_forever, daemon=True)
        gicp_thread.start()
        try:
            session = gicp.session_file(tmp)
            assert session.exists()  # real evidence this test relies on is really there
            rec = json.loads(session.read_text(encoding="utf-8"))
            assert rec["port"] == gicp_port
            assert rec["token"] == gicp_token

            _start_dashboard(tmp)
            _wait_ready(dash_base)

            view_html = _get_html(dash_base, "/view/dashboard")
            assert "GUI Intake Control Plane (live)" in view_html
            expected_href = f"http://127.0.0.1:{gicp_port}/?token={gicp_token}"
            assert f'<a href="{expected_href}">' in view_html
        finally:
            gicp_server.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- INTAKE-23: GUI VIP Coverage Wizard nav link ----------------------------

def test_vip_coverage_wizard_not_running_reports_honestly_with_inert_href(tmp_path):
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import gui_vip_coverage_wizard as gvcw
        assert not (tmp / ".dv-harness" / gvcw.AUTH_SESSION_FILENAME).exists()

        view_html = _get_html(base, "/view/dashboard")
        assert "GUI VIP Coverage Wizard (not running)" in view_html
        assert '<a href="#">GUI VIP Coverage Wizard (not running)</a>' in view_html
        # And it must never leak onto the untouched root page.
        assert "GUI VIP Coverage Wizard" not in _get_html(base, "/")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_vip_coverage_wizard_real_session_produces_a_real_live_link(tmp_path):
    """A REAL `gui_vip_coverage_wizard` server's own real, persisted session
    record (host/port/token, written by that module's own
    `issue_session_token()` at real server start) must be read verbatim and
    turned into a real, working link."""
    from dv_harness import gui_vip_coverage_wizard as gvcw

    dash_port = _free_port()
    tmp = _mk_dashboard_project(dash_port)
    try:
        dash_base = f"http://127.0.0.1:{dash_port}"

        gvcw_server, gvcw_token = gvcw.build_server(tmp, port=0)
        gvcw_port = gvcw_server.server_address[1]
        gvcw_thread = threading.Thread(target=gvcw_server.serve_forever, daemon=True)
        gvcw_thread.start()
        try:
            session = tmp / ".dv-harness" / gvcw.AUTH_SESSION_FILENAME
            assert session.exists()
            rec = json.loads(session.read_text(encoding="utf-8"))
            assert rec["port"] == gvcw_port
            assert rec["token"] == gvcw_token

            _start_dashboard(tmp)
            _wait_ready(dash_base)

            view_html = _get_html(dash_base, "/view/dashboard")
            assert "GUI VIP Coverage Wizard (live)" in view_html
            expected_href = f"http://127.0.0.1:{gvcw_port}/?token={gvcw_token}"
            assert f'<a href="{expected_href}">' in view_html
        finally:
            gvcw_server.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_wizard_not_detected_reports_honestly_with_inert_href(tmp_path):
    """No real listener bound at the wizard's own documented default port
    (127.0.0.1:8799) -> the honest "(not detected...)" label and an inert
    `href="#"`. Skipped rather than a false failure if this environment
    already has something else bound to that port."""
    if not _port_is_free("127.0.0.1", 8799):
        pytest.skip("port 127.0.0.1:8799 is not free in this environment")

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        view_html = _get_html(base, "/view/dashboard")
        assert "GUI Intake Wizard (not detected at default port 8799)" in view_html
        assert ('<a href="#">GUI Intake Wizard (not detected at default '
                'port 8799)</a>') in view_html
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_wizard_real_listener_at_default_port_produces_a_real_live_link(tmp_path):
    """A REAL listener actually bound at 127.0.0.1:8799 (the wizard's own
    documented `--port` CLI default) is real, current connectivity evidence
    -- proven here with the real `gui_intake_wizard` server itself, not a
    bare socket standing in for it. Skipped rather than a false failure if
    this environment already has something else bound to that port."""
    if not _port_is_free("127.0.0.1", 8799):
        pytest.skip("port 127.0.0.1:8799 is not free in this environment")

    from dv_harness import gui_intake_wizard as wiz

    dash_port = _free_port()
    tmp = _mk_dashboard_project(dash_port)
    wiz_root = Path(tmp) / "wizard_project"
    wiz_root.mkdir()
    try:
        dash_base = f"http://127.0.0.1:{dash_port}"

        try:
            wiz_server = wiz.build_server(wiz_root, port=8799)
        except OSError:
            pytest.skip("could not bind 127.0.0.1:8799 in this environment")
        wiz_thread = threading.Thread(target=wiz_server.serve_forever, daemon=True)
        wiz_thread.start()
        try:
            _start_dashboard(tmp)
            _wait_ready(dash_base)

            view_html = _get_html(dash_base, "/view/dashboard")
            assert "GUI Intake Wizard (live)" in view_html
            assert '<a href="http://127.0.0.1:8799/">GUI Intake Wizard (live)</a>' in view_html
        finally:
            wiz_server.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
