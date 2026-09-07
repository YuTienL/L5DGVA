"""GET /api/orphaned-fork-detection, GET /api/multi-vip-cooperation, GET
/api/dut-errata-correlation -- three GUI cards wiring three previously
dashboard-unreachable, already-real, already-tested modules
(`orphaned_fork_detection.py`, `multi_vip_cooperation_architecting.py`,
`dut_errata_correlation.py`) into `dashboard.py`, following the exact same
fetch-real-artifact-and-render convention this file's own sibling cards
(`/api/design-knowledge`, `/api/requirement-vplan-center`,
`/api/vip-environment-builder`, ...) already established.

Confirmed a genuine gap before writing anything: `grep -n
"multi_vip_cooperation_architecting|orphaned_fork_detection|dut_errata_
correlation" dv_harness/dashboard.py` returned nothing before this change.

Every reader computes NOTHING itself -- it reads a caller-declared
`.dv-harness/<module>/inputs.json` overlay (or, for
`dut_errata_correlation.py`, this project's own real `env.manifest.json`,
auto-resolved via `env_manifest.default_manifest_path()`) and calls the
real, unmodified module function LIVE on every request. These tests prove
that reuse directly: the served report is compared against a DIRECT call
into the same real module over the identical real inputs, never a value
typed into the test standing in for what the module would compute.
"""
from __future__ import annotations

import json
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)

# The exact fixture orphaned_fork_detection.py's own test suite already uses
# for "the gap a whole-file count check cannot see": >=1 WAIT_SEQ_ALL exists
# in the file, but a later dispatch has nothing after it.
ORPHANED_LAST_DISPATCH = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
`FORK_SEQ("seq_b", p_sequencer);
`WAIT_SEQ_ALL;
`FORK_SEQ("seq_c", p_sequencer);
end
"""


def _strip_generated_at(obj):
    """RuntimeEventRegistry.propagate() stamps a real, current
    `generated_at` ISO timestamp on every call -- two otherwise-identical
    calls a few milliseconds apart legitimately differ only there. Strip it
    recursively so a served-vs-direct comparison proves the REST of the
    report is byte-identical without being defeated by real wall-clock
    drift between the served call and this test's own direct call."""
    if isinstance(obj, dict):
        return {k: _strip_generated_at(v) for k, v in obj.items() if k != "generated_at"}
    if isinstance(obj, list):
        return [_strip_generated_at(v) for v in obj]
    return obj


def _write_inputs(tmp: Path, subdir: str, raw) -> Path:
    d = tmp / ".dv-harness" / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / "inputs.json"
    if isinstance(raw, str):
        p.write_text(raw, encoding="utf-8")
    else:
        p.write_text(json.dumps(raw), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Honest empty state on a bare project -- the required negative control.
# ---------------------------------------------------------------------------

def test_all_three_cards_honest_empty_state_on_a_bare_project():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, ofd = _get(base, "/api/orphaned-fork-detection")
        assert status == 200
        assert ofd["available"] is False
        assert ofd["report"] is None
        assert ofd["error"] is None
        assert "orphaned_fork_detection" in ofd["inputs_path"]

        status, mvc = _get(base, "/api/multi-vip-cooperation")
        assert status == 200
        assert mvc["available"] is False
        assert mvc["report"] is None
        assert mvc["error"] is None
        assert "multi_vip_cooperation" in mvc["inputs_path"]

        # dut_errata_correlation.analyze_errata()'s own contract calls
        # through UNCONDITIONALLY (source_path=None produces its own honest
        # NOT_AVAILABLE without ever attempting to open anything) -- so this
        # one is "available": True with a real NOT_AVAILABLE report, never
        # the "available": False shape the other two use.
        status, dec = _get(base, "/api/dut-errata-correlation")
        assert status == 200
        assert dec["available"] is True
        assert dec["error"] is None
        assert dec["report"]["status"] == "NOT_AVAILABLE"
        assert dec["report"]["erratum_count"] == 0
    finally:
        pass


def test_all_three_cards_are_served_and_wired_into_the_page_load():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        import urllib.request
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        for card_id in ("orphanedForkDetectionCard", "multiVipCooperationCard",
                         "dutErrataCorrelationCard"):
            assert card_id in html
        for fn in ("loadOrphanedForkDetection", "loadMultiVipCooperation",
                    "loadDutErrataCorrelation"):
            assert fn in html
            assert f"await {fn}();" in html
    finally:
        pass


# ---------------------------------------------------------------------------
# Orphaned/Leaked-Fork Detection: real positive path, cross-checked directly
# against orphaned_fork_detection.analyze_pattern_directory().
# ---------------------------------------------------------------------------

def test_orphaned_fork_detection_reads_the_real_module_over_a_declared_pattern_dir():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        pat_dir = tmp / "patterns"
        pat_dir.mkdir(parents=True, exist_ok=True)
        (pat_dir / "orphan.txt").write_text(ORPHANED_LAST_DISPATCH, encoding="utf-8")
        _write_inputs(tmp, "orphaned_fork_detection", {"pattern_dir": str(pat_dir)})
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/orphaned-fork-detection")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        served = data["report"]

        from dv_harness import orphaned_fork_detection as ofd
        direct = ofd.analyze_pattern_directory(str(pat_dir))
        assert served == direct
        assert served["orphaned_dispatch_count"] == 1
        assert served["overall_status"] == "FINDINGS_FOUND"
    finally:
        pass


def test_orphaned_fork_detection_malformed_inputs_file_surfaces_a_real_reason():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _write_inputs(tmp, "orphaned_fork_detection", "{not valid json")
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/orphaned-fork-detection")
        assert status == 200
        assert data["available"] is True
        assert data["report"] is None
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
    finally:
        pass


# ---------------------------------------------------------------------------
# Multi-VIP Cooperation Architecting: real positive path, cross-checked
# directly against build_multi_vip_cooperation().
# ---------------------------------------------------------------------------

def test_multi_vip_cooperation_reads_the_real_module_over_declared_interfaces():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        # Two interfaces sharing the identical real bind_target is,
        # structurally, one physical PHY instance backing two logical
        # interfaces -- a real, auto-derived SHARED_PHY_INSTANCE coupling
        # fact, per multi_vip_cooperation_architecting.py's own docstring.
        interfaces = [
            {"interface_id": "host_mode", "dut_port_direction": "output",
             "bind_target": "dut.top.usb_phy"},
            {"interface_id": "device_mode", "dut_port_direction": "input",
             "bind_target": "dut.top.usb_phy"},
        ]
        _write_inputs(tmp, "multi_vip_cooperation", {"interfaces": interfaces})
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/multi-vip-cooperation")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        served = data["report"]

        from dv_harness import multi_vip_cooperation_architecting as mvca
        direct = mvca.build_multi_vip_cooperation(interfaces).to_dict()
        assert _strip_generated_at(served) == _strip_generated_at(direct)
        assert len(served["relationships"]) == 1
        rel = served["relationships"][0]
        assert {rel["interface_a"], rel["interface_b"]} == {"host_mode", "device_mode"}
    finally:
        pass


def test_multi_vip_cooperation_no_interfaces_declared_is_honestly_reported():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _write_inputs(tmp, "multi_vip_cooperation", {"interfaces": []})
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/multi-vip-cooperation")
        assert status == 200
        assert data["available"] is True
        assert data["report"] is None
        assert data["error"]["reason"] == "INTERFACES_NOT_DECLARED"
    finally:
        pass


# ---------------------------------------------------------------------------
# DUT Errata/Known-Issues Correlation: manifest_path auto-resolved via
# env_manifest.default_manifest_path(); source_path from the declared
# inputs.json.
# ---------------------------------------------------------------------------

def test_dut_errata_correlation_no_source_declared_reports_not_available_honestly():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        # source_path omitted -- title only -- confirms the reader still
        # calls analyze_errata() unconditionally with source_path=None.
        _write_inputs(tmp, "dut_errata_correlation", {"title": "no source here"})
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/dut-errata-correlation")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["report"]["status"] == "NOT_AVAILABLE"

        from dv_harness import dut_errata_correlation as dec
        from dv_harness import env_manifest
        direct = dec.analyze_errata(None, env_manifest.default_manifest_path(tmp), title="no source here")
        assert data["report"] == direct
    finally:
        pass


def test_dut_errata_correlation_malformed_inputs_file_reported_but_still_calls_through():
    """A malformed inputs.json is reported as its own error, but per
    analyze_errata()'s own contract this reader still calls through with
    source_path=None -- so `report` is still a real, honest NOT_AVAILABLE
    document, never a null report."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _write_inputs(tmp, "dut_errata_correlation", "{not valid json")
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/dut-errata-correlation")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert data["report"]["status"] == "NOT_AVAILABLE"
    finally:
        pass
