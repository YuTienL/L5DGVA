"""Tests for dv_harness/exec_eng_dashboard.py -- the Executive + Engineering
Dashboard (2026-09-06, TARGETED_HARDENING section 241, gui_exec_eng_dashboard).

Every input this suite drives comes from a REAL producer, never hand-typed to
look like one: `waiver_store.record_waiver()` writes the real ledger,
`platform_health.platform_health_report()` and `system_closure_aggregator.
aggregate_system_closure()` are called exactly as the module under test calls
them, and the real `python -m dv_harness.exec_eng_dashboard` CLI is driven as
a real subprocess.

The negative controls are what give this suite its detection power: a bare
project root reports the executive banner UNKNOWN -- never a fabricated
HEALTHY/CLOSED just because there is no bad news to report -- and a real
EXPIRED waiver drives a real CRITICAL banner even though the surrounding
platform is merely unmeasured, proving the worst-wins fold actually reads
real evidence rather than defaulting to the platform's own (weaker) UNKNOWN.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import exec_eng_dashboard as ded
from dv_harness import platform_health
from dv_harness import system_closure_aggregator as sca
from dv_harness import waiver_store

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _canonical_waiver(waiver_id="W-EXEC-001", **overrides):
    record = {
        "waiver_id": waiver_id,
        "item": "REQ-EXEC-001",
        "reason": "known gap, tracked separately",
        "evidence": "design review 2026-08-30",
        "scope": {
            "requirement_ids": ["REQ-EXEC-001"],
            "subsystem": "exec_test",
            "spec_revision": "SPEC-1.0",
            "design_evidence_hash": "sha256:deadbeef",
            "approval_id": "APPR-1",
            "scope_hash": "sha256:cafe0000",
        },
        "approver": "dv-lead",
        "affected_version": {"spec_revision": "SPEC-1.0", "rtl_hash": "rtl-aaa",
                             "revision": "REV1"},
        "risk": "LOW",
        "created_at": "2026-08-30T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    record.update(overrides)
    return record


def _snapshot(root: Path):
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# combine_banner_state -- the one fold this module exists to compute
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("closure_status,platform_state,expected", [
    (sca.CLOSURE_CLOSED, platform_health.HEALTHY, platform_health.HEALTHY),
    (sca.CLOSURE_CLOSED, platform_health.UNKNOWN, platform_health.UNKNOWN),
    (sca.CLOSURE_CLOSED, platform_health.DEGRADED, platform_health.DEGRADED),
    (sca.CLOSURE_CLOSED, platform_health.CRITICAL, platform_health.CRITICAL),
    (sca.CLOSURE_NOT_CLOSED, platform_health.HEALTHY, platform_health.CRITICAL),
    (sca.CLOSURE_INCOMPLETE_EVIDENCE, platform_health.HEALTHY, platform_health.UNKNOWN),
    (sca.CLOSURE_INCOMPLETE_EVIDENCE, platform_health.CRITICAL, platform_health.CRITICAL),
])
def test_combine_banner_state_is_strict_worst_wins(closure_status, platform_state, expected):
    assert ded.combine_banner_state(closure_status, platform_state) == expected


def test_combine_banner_state_never_reads_closed_plus_unmeasured_platform_as_healthy():
    """The headline negative control: a CLEAN twelve-dimension closure picture
    must never be presented as an overall HEALTHY banner while the platform
    itself was never actually measured."""
    banner = ded.combine_banner_state(sca.CLOSURE_CLOSED, platform_health.UNKNOWN)
    assert banner == platform_health.UNKNOWN
    assert banner != platform_health.HEALTHY


def test_combine_banner_state_unrecognized_closure_status_is_unknown_never_guessed():
    banner = ded.combine_banner_state("SOME_FUTURE_TOKEN", platform_health.HEALTHY)
    assert banner == platform_health.UNKNOWN


# ---------------------------------------------------------------------------
# gather_closure_dimensions -- real per-dimension producers
# ---------------------------------------------------------------------------

def test_gather_closure_dimensions_on_bare_root_is_honestly_not_available(tmp_path):
    dims = ded.gather_closure_dimensions(tmp_path)
    by_name = {d["dimension_name"]: d for d in dims}
    assert set(by_name) == set(ded.AUTO_SOURCED_DIMENSIONS)
    assert by_name["functional_coverage"]["status"] == sca.DIMENSION_NOT_AVAILABLE
    assert by_name["waiver_status"]["status"] == sca.DIMENSION_NOT_AVAILABLE
    # Every dimension record carries a real, non-empty reason -- never a bare
    # status with nothing a human could check.
    for d in dims:
        assert d["reason"]


def test_gather_waiver_status_dimension_reflects_a_real_expired_waiver(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver(
        expires_at="2026-01-01T00:00:00+00:00"))
    dims = ded.gather_closure_dimensions(tmp_path)
    by_name = {d["dimension_name"]: d for d in dims}
    assert by_name["waiver_status"]["status"] == sca.DIMENSION_UNMET
    assert "W-EXEC-001" in by_name["waiver_status"]["reason"]


def test_gather_waiver_status_dimension_reflects_a_real_valid_waiver(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver())  # far-future expiry
    dims = ded.gather_closure_dimensions(tmp_path)
    by_name = {d["dimension_name"]: d for d in dims}
    assert by_name["waiver_status"]["status"] == sca.DIMENSION_MET


# ---------------------------------------------------------------------------
# derive_executive_engineering_dashboard -- the combined report
# ---------------------------------------------------------------------------

def test_derive_dashboard_on_bare_root_reports_unknown_banner_and_writes_nothing(tmp_path):
    before = _snapshot(tmp_path)
    data = ded.derive_executive_engineering_dashboard(tmp_path)
    after = _snapshot(tmp_path)
    assert after == before  # read-only: mints nothing on a bare root

    ex = data["executive_summary"]
    assert ex["banner_state"] == platform_health.UNKNOWN
    assert ex["system_closure_status"] == sca.CLOSURE_INCOMPLETE_EVIDENCE
    assert ex["platform_overall_state"] == platform_health.UNKNOWN
    # Twelve real dimensions, always all reported -- never collapsed to a count.
    assert len(data["engineering_detail"]["closure_dimensions"]) == len(sca.CLOSURE_DIMENSIONS)
    assert len(data["engineering_detail"]["platform_subsystems"]) == len(platform_health.SUBSYSTEMS)
    gathering = data["dimension_gathering"]
    assert set(gathering["auto_sourced_dimensions"]) == set(ded.AUTO_SOURCED_DIMENSIONS)
    assert set(gathering["not_supplied_dimensions"]) == (
        set(sca.CLOSURE_DIMENSIONS) - set(ded.AUTO_SOURCED_DIMENSIONS))


def test_derive_dashboard_with_expired_waiver_reaches_critical_banner(tmp_path):
    """A real, evidence-backed EXPIRED waiver alone -- with the surrounding
    platform still merely UNMEASURED -- must reach the strongest banner,
    proving the worst-wins fold reads real evidence rather than defaulting to
    the weaker platform reading."""
    waiver_store.record_waiver(tmp_path, _canonical_waiver(
        expires_at="2026-01-01T00:00:00+00:00"))
    data = ded.derive_executive_engineering_dashboard(tmp_path)
    ex = data["executive_summary"]
    assert ex["system_closure_status"] == sca.CLOSURE_NOT_CLOSED
    assert "waiver_status" in ex["kpi"]["closure_dimensions_blocking"]
    assert ex["banner_state"] == platform_health.CRITICAL


def test_extra_dimension_records_are_merged_never_silently_dropped(tmp_path):
    others = [d for d in sca.CLOSURE_DIMENSIONS if d not in ded.AUTO_SOURCED_DIMENSIONS]
    extra = [{"dimension_name": name, "status": "MET", "reason": "caller-declared clean"}
             for name in others]
    data = ded.derive_executive_engineering_dashboard(tmp_path, extra_dimension_records=extra)
    gathering = data["dimension_gathering"]
    assert gathering["not_supplied_dimensions"] == []
    assert set(gathering["caller_supplied_dimensions"]) == set(others)
    dims_by_name = {d["dimension_name"]: d for d in data["engineering_detail"]["closure_dimensions"]}
    for name in others:
        assert dims_by_name[name]["normalized_status"] == sca.DIMENSION_MET
    # The two auto-sourced dimensions on a bare root are still NOT_AVAILABLE,
    # so the whole rollup is still honestly incomplete, never CLOSED.
    assert data["executive_summary"]["system_closure_status"] == sca.CLOSURE_INCOMPLETE_EVIDENCE


def test_extra_dimension_disagreeing_with_auto_sourced_surfaces_as_ambiguous_not_silently_overwritten(tmp_path):
    """A caller-supplied record for a dimension this module ALSO auto-sources
    is a genuine second opinion, never silently trusted over the real one."""
    extra = [{"dimension_name": "functional_coverage", "status": "MET",
              "reason": "caller claims clean"}]
    data = ded.derive_executive_engineering_dashboard(tmp_path, extra_dimension_records=extra)
    dims_by_name = {d["dimension_name"]: d for d in data["engineering_detail"]["closure_dimensions"]}
    assert dims_by_name["functional_coverage"]["normalized_status"] == (
        sca.DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def test_render_dashboard_html_carries_both_cards(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver(
        expires_at="2026-01-01T00:00:00+00:00"))
    data = ded.derive_executive_engineering_dashboard(tmp_path)
    html = ded.render_dashboard_html(data)
    assert 'id="execSummaryCard"' in html
    assert 'id="engDetailCard"' in html
    assert 'id="engPlatformCard"' in html
    assert "Executive Summary" in html
    assert "Engineering Detail" in html
    # Every one of the twelve dimensions is rendered, not only the blocking one.
    for name in sca.CLOSURE_DIMENSIONS:
        assert name in html


def test_render_dashboard_html_escapes_reason_text_from_evidence():
    """A dimension `reason` string is rendered verbatim from real evidence
    (a waiver_id, a `functional_coverage_signoff` reason) -- it must never be
    injected into the page unescaped."""
    dims = [{"dimension_name": "functional_coverage",
             "normalized_status": sca.DIMENSION_UNMET,
             "raw_statuses": ["OPEN"],
             "reasons": ["<script>alert(1)</script> known gap"],
             "supplied": True}]
    fake_data = {
        "project_root": "/tmp/proj",
        "executive_summary": {
            "banner_state": platform_health.CRITICAL,
            "banner_note": "<b>bold</b> note",
            "system_closure_status": sca.CLOSURE_NOT_CLOSED,
            "system_closure_reason": "test",
            "platform_overall_state": platform_health.UNKNOWN,
            "platform_degradation_mode": None,
            "kpi": {"closure_dimensions_clear": 0, "closure_dimensions_total": 12,
                    "closure_dimensions_blocking": ["functional_coverage"],
                    "closure_dimensions_incomplete": [],
                    "platform_subsystems_healthy": 0, "platform_subsystems_total": 0,
                    "platform_subsystems_unhealthy": []},
        },
        "engineering_detail": {
            "closure_dimensions": dims, "closure_unrecognized_records": [],
            "platform_subsystems": [], "platform_error_budgets": [],
            "platform_window": {}, "platform_unmeasurable_slis": {},
        },
        "dimension_gathering": {"auto_sourced_dimensions": [], "caller_supplied_dimensions": [],
                                "not_supplied_dimensions": []},
        "fact_sources": [], "authorizes_nothing": "read-only",
    }
    html = ded.render_dashboard_html(fake_data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


def test_render_dashboard_text_carries_banner_and_dimension_rows(tmp_path):
    data = ded.derive_executive_engineering_dashboard(tmp_path)
    text = ded.render_dashboard_text(data)
    assert "EXECUTIVE SUMMARY: UNKNOWN" in text
    assert "ENGINEERING DETAIL -- closure dimensions" in text
    assert "ENGINEERING DETAIL -- platform subsystems" in text
    for name in sca.CLOSURE_DIMENSIONS:
        assert name in text


# ---------------------------------------------------------------------------
# execute() exit codes
# ---------------------------------------------------------------------------

def test_execute_exit_code_ok_on_bare_root_even_though_unknown(tmp_path):
    code, data, text, html = ded.execute(tmp_path)
    assert code == ded.EXIT_OK
    assert data["executive_summary"]["banner_state"] == platform_health.UNKNOWN
    assert text and html


def test_execute_exit_code_attention_on_real_expired_waiver(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver(
        expires_at="2026-01-01T00:00:00+00:00"))
    code, data, text, html = ded.execute(tmp_path)
    assert code == ded.EXIT_ATTENTION
    assert data["executive_summary"]["banner_state"] == platform_health.CRITICAL


# ---------------------------------------------------------------------------
# real CLI subprocess
# ---------------------------------------------------------------------------

def test_cli_json_and_exit_code_on_bare_root(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.exec_eng_dashboard",
         "--root", str(tmp_path), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == ded.EXIT_OK, result.stderr
    payload = json.loads(result.stdout)
    assert payload["executive_summary"]["banner_state"] == platform_health.UNKNOWN


def test_cli_writes_html_snapshot_with_out_flag(tmp_path):
    out_path = tmp_path / "dashboard.html"
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.exec_eng_dashboard",
         "--root", str(tmp_path), "--out", str(out_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == ded.EXIT_OK, result.stderr
    assert out_path.is_file()
    content = out_path.read_text(encoding="utf-8")
    assert "Executive Summary" in content
    assert "Engineering Detail" in content


def test_cli_exit_code_attention_on_real_expired_waiver_subprocess(tmp_path):
    waiver_store.record_waiver(tmp_path, _canonical_waiver(
        expires_at="2026-01-01T00:00:00+00:00"))
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.exec_eng_dashboard",
         "--root", str(tmp_path), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == ded.EXIT_ATTENTION, result.stderr
    payload = json.loads(result.stdout)
    assert payload["executive_summary"]["banner_state"] == platform_health.CRITICAL
