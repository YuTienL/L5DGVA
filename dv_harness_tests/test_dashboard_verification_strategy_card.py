"""GET /api/verification-strategy -- the Verification Strategy Optimizer dashboard
card (item verification-strategy-no-dashboard-card).

WIRING_GAP_EXISTING_MODULE: `dv_harness/verification_strategy.py` already exists
(VI-4, see its own module docstring and the matching CLAUDE.md section) and
already has its own `dv-harness verification-strategy` / `python -m
dv_harness.verification_strategy` front doors and real passing tests
(dv_harness_tests/test_verification_strategy.py). This change adds NO new
analysis, signal, or verdict logic anywhere -- it is a pure dashboard wiring
gap, closed the same way dashboard.py's "Confidence Calibration" and
"Generation Readiness Center" cards were: a thin
`_read_verification_strategy_state()` reader calling
`verification_strategy.execute_verb()` directly, one read-only GET endpoint,
and a fetch-once + client-side-render card following the exact same
tiles-plus-table shape those two cards already use.

These tests exist to prove two things beyond "the endpoint returns 200":

  * The card READS the real module. The served report is compared against
    what `verification_strategy.execute_verb()` itself computes over the
    identical project root -- never against a value typed into the test, so a
    dashboard-local re-derivation that drifted from the real module would
    fail here.
  * The Evidence Truth Rule holds on the served surface: a bad invocation the
    module itself refuses (an unknown verb) must surface its own named
    reason rather than a bare 500, and a real internal failure must likewise
    surface its own reason/detail rather than a silently empty card.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention test_dashboard_generation_readiness_card.py
already uses.
"""
from __future__ import annotations

import shutil
import urllib.request

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def test_verification_strategy_reports_the_real_report_over_a_bare_project():
    """A bare project (nothing generated, no evidence) still gets a real,
    honest report back -- the served payload must be byte-identical (modulo
    the timestamp-free fields that report already carries none of) to calling
    verification_strategy.execute_verb() directly over the same root."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import verification_strategy as vs

        status, data = _get(base, "/api/verification-strategy")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        report = data["report"]
        assert report is not None

        _code, expected, _text = vs.execute_verb(tmp, "recommend")
        assert report == expected

        # Every declared strategy gets a row, and the disclosure is the real
        # one this module prints on every report, whatever it recommends.
        strategies_seen = {r["strategy"] for r in report["recommendations"]}
        assert strategies_seen == set(vs.STRATEGIES)
        assert report["disclosure"] == vs.REPORT_DISCLOSURE
    finally:
        shutil.rmtree(tmp)


def test_verification_strategy_capabilities_verb_mirrors_the_cli():
    """?verb=capabilities must reach execute_verb(root, "capabilities") --
    the executability-per-strategy report -- exactly like the CLI's own
    `capabilities` sub-verb."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import verification_strategy as vs

        status, data = _get(base, "/api/verification-strategy?verb=capabilities")
        assert status == 200
        assert data["available"] is True

        _code, expected, _text = vs.execute_verb(tmp, "capabilities")
        assert data["report"] == expected
        assert {row["strategy"] for row in data["report"]["strategies"]} == set(vs.STRATEGIES)
    finally:
        shutil.rmtree(tmp)


def test_verification_strategy_bad_verb_surfaces_the_real_module_error_not_a_500():
    """An unknown verb is refused by execute_verb() itself (exit code 1) --
    this must surface as this endpoint's own named error, never a bare 500
    and never a silently fabricated report."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/verification-strategy?verb=not-a-real-verb")
        assert status == 200
        assert data["available"] is False
        assert data["report"] is None
        assert data["error"]["reason"] == "UNKNOWN_VERB"
    finally:
        shutil.rmtree(tmp)


def test_verification_strategy_reports_a_real_internal_failure_rather_than_a_500():
    """A real exception raised inside verification_strategy.execute_verb()
    must surface as this endpoint's own reason/detail -- the same honest-
    error contract every sibling `_read_*_state()` reader already holds to --
    never a bare 500 and never a silently empty card."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        def _raise(*args, **kwargs):
            raise RuntimeError("simulated failure inside verification_strategy")

        import dv_harness.verification_strategy as vs
        saved = vs.execute_verb
        vs.execute_verb = _raise
        try:
            status, data = _get(base, "/api/verification-strategy")
            assert status == 200
            assert data["available"] is False
            assert data["report"] is None
            assert data["error"]["reason"] == "VERIFICATION_STRATEGY_UNREADABLE"
            assert "simulated failure" in data["error"]["detail"]["message"]
        finally:
            vs.execute_verb = saved
    finally:
        shutil.rmtree(tmp)


def test_verification_strategy_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid -- and must follow the same tiles-plus-table
    rendering convention as the Confidence Calibration / Generation Readiness
    cards it was asked to reuse."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="verificationStrategyCard"' in html
        assert "Verification Strategy Optimizer" in html
        assert "'/api/verification-strategy" in html
        assert "await loadVerificationStrategy();" in html
        assert 'id="verificationStrategyTiles"' in html
        assert 'id="verificationStrategyTableBody"' in html
        for header in ("Strategy", "Verdict", "Executability", "Basis",
                        "Executable Next Action"):
            assert f">{header}<" in html
        # Read-only, matching every reader function it reuses the convention
        # of -- no POST verb of its own.
        assert "Read-only" in html.split('id="verificationStrategyCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
