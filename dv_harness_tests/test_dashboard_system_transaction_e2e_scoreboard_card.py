"""GET /api/system-transaction-e2e-scoreboard -- the "System Transaction View
+ End-to-End Scoreboard UI" dashboard card
(dashboard_system_transaction_e2e_scoreboard_view).

The assigned item asks for "a route + card surfacing amba_transaction_ir.py /
transaction_correlation_ir.py real correlated-transaction records and
system-scope scoreboard placement facts for a composed system."

REUSE OVER REINVENT, verified first: `dv_harness/amba_transaction_ir.py`
(SYOSCB-10, per-fabric transaction shape), `dv_harness/system_transaction_ir.py`
(composes that shape cross-subsystem), `dv_harness/transaction_correlation_ir.py`
(SYOSCB-11, response correlation / data-beat association / logical-transaction
reconstruction) and `dv_harness/system_scoreboard_ir.py` (system-scope
scoreboard-placement composition) all already exist, complete and tested, with
their own CLAUDE.md sections. A repo-wide grep for
"system_transaction_e2e_scoreboard"/"transaction_correlation"/
"system_scoreboard"/"logical_transaction" inside dashboard.py before this
change confirmed no route or card for any of the four surfaced this to a GUI --
a genuine, real gap, not a rediscovery of already-wired work. This change adds
NO new analysis anywhere: `_read_system_transaction_e2e_scoreboard_state()`
reads a real, caller-supplied `.dv-harness/system_transaction_e2e_scoreboard/
inputs.json` overlay and calls the three real, unmodified builder functions
live, on every request -- the exact same fetch-real-artifact-and-render
convention `_read_design_knowledge_state()`/
`_read_subsystem_system_verification_state()`/
`_read_verification_architecture_state()` already established.

These tests exist to prove three things beyond "the endpoint returns 200":

  * The card READS the real modules. Every asserted value is compared against
    what `system_transaction_ir.build_system_transaction_ir()`,
    `transaction_correlation_ir.correlate_responses()`/`associate_data_beats()`/
    `reconstruct_logical_transactions()`, and
    `system_scoreboard_ir.build_system_scoreboard_ir()` themselves compute over
    the IDENTICAL declared facts -- never against a value typed into the test,
    so a dashboard-local re-derivation that drifted from the real composition
    would fail here.
  * Each of the three sections is built INDEPENDENTLY: a real build failure in
    one section is surfaced as that section's own `error`, never hiding or
    corrupting the other two -- the same per-section isolation
    `_read_subsystem_system_verification_state()`'s own `errors` list already
    holds to.
  * The Evidence Truth Rule holds on the served surface: a bare project (no
    overlay file at all) must never render a fabricated composed record, and a
    malformed overlay must surface its own reason/detail rather than a bare 500
    or a silently empty card.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention every sibling card test file already
uses.
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


# ---------------------------------------------------------------------------
# Real fixture builders -- one per underlying module, mirroring each module's
# own test file's fixture-construction helpers exactly, so what is served here
# is genuinely the same shape those modules' own test suites already exercise.
# ---------------------------------------------------------------------------

def _amba_port_row(port_id: str, protocol: str = "AXI4") -> dict:
    """A complete AMBA_PORT_REGISTRY row -- mirrors test_amba_transaction_ir.py's
    own `make_row()` helper field-for-field, so `build_transaction_ir_template()`
    receives every mandated column."""
    return {
        "port_id": port_id,
        "fabric_port": port_id.lower(),
        "protocol": protocol,
        "fabric_role": "SLAVE_INTERFACE",
        "endpoint_role": "MASTER_ENDPOINT",
        "endpoint_hierarchy": f"soc_top.u_{port_id.lower()}",
        "vip_bind_hierarchy": f"soc_top.u_{port_id.lower()}",
        "vip_mode": "PASSIVE_MONITOR",
        "clock": "ACLK",
        "reset": "ARESETN",
        "address_width": "32",
        "data_width": "64",
        "id_width": "4",
        "user_widths": "4",
        "scoreboard_channel": "sb_axi_master",
        "trace_status": "SOURCE_FOUND",
        "readiness": "READY_TO_BIND",
        "confidence": "HIGH",
        "source_evidence": [f"AMBA-16 matrix row {port_id.lower()}"],
        "row_id": port_id.lower(),
    }


def _req(ref, scope="P0", tid=1, seq=None, evidence=("sim.log:10",)):
    return {"request_ref": ref, "scope": scope, "transaction_id": tid,
            "sequence_number": seq, "evidence": list(evidence)}


def _resp(ref, scope="P0", tid=1, seq=None, evidence=("sim.log:20",)):
    return {"response_ref": ref, "scope": scope, "transaction_id": tid,
            "sequence_number": seq, "evidence": list(evidence)}


def _txn(ref, scope="P0", tid=None, seq=None, expected=None, evidence=("sim.log:1",)):
    return {"transaction_ref": ref, "scope": scope, "transaction_id": tid,
            "sequence_number": seq, "expected_beat_count": expected, "evidence": list(evidence)}


def _beat(ref, scope="P0", bid=None, evidence=("sim.log:2",)):
    return {"beat_ref": ref, "scope": scope, "beat_id": bid, "evidence": list(evidence)}


def _logical_txn(ref, request_ref, scope="P0", evidence=("sim.log:5",)):
    return {"transaction_ref": ref, "request_ref": request_ref, "scope": scope,
            "evidence": list(evidence)}


def _write_inputs(tmp: Path, overlay: dict) -> Path:
    p = tmp / ".dv-harness" / "system_transaction_e2e_scoreboard" / "inputs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(overlay), encoding="utf-8")
    return p


def _full_overlay() -> dict:
    from dv_harness import amba_transaction_ir as tir
    return {
        "system_transaction": {
            "subsystem_fabrics": {
                "usb0": [tir.build_transaction_ir_template(_amba_port_row("USB0"))],
                "pcie0": [tir.build_transaction_ir_template(_amba_port_row("PCIE0"))],
            },
            "system_transaction_links": [{
                "link_id": "usb0_pcie0_bridge",
                "master_subsystem": "usb0", "master_port_id": "USB0",
                "slave_subsystem": "pcie0", "slave_port_id": "PCIE0",
                "evidence": "shared SoC interconnect bridge",
            }],
        },
        "transaction_correlation": {
            "requests": [_req("Q1")],
            "responses": [_resp("R1")],
            "data_transactions": [_txn("W1", tid="AWID0", expected=2)],
            "beats": [_beat("B1", bid="AWID0"), _beat("B2", bid="AWID0")],
            "transactions": [_logical_txn("W1", "Q1")],
        },
        "system_scoreboard": {
            "system_interactions": [{
                "interaction_id": "usb0_pcie0_dma",
                "subsystems": ["usb0", "pcie0"],
                "evidence": "shared DMA engine",
                "spans_dma_engine": True,
            }],
            "existing_scoreboards": [{
                "scoreboard_id": "sb_soc_e2e",
                "owning_subsystems": ["usb0", "pcie0", "ddr0"],
                "evidence": "generated SoC-level scoreboard",
                "spans_end_to_end_stimulus_to_system_effect": True,
            }],
        },
    }


def test_bare_project_reports_an_honest_empty_state():
    """No .dv-harness/system_transaction_e2e_scoreboard/inputs.json on disk at
    all -- the endpoint must report `available: False` naming the real
    conventional path it looked for, never a fabricated composed record."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/system-transaction-e2e-scoreboard")
        assert status == 200
        assert data["available"] is False
        assert data["error"] is None
        assert data["system_transaction"] is None
        assert data["transaction_correlation"] is None
        assert data["system_scoreboard"] is None
        assert data["inputs_path"].replace("\\", "/").endswith(
            ".dv-harness/system_transaction_e2e_scoreboard/inputs.json")
    finally:
        shutil.rmtree(tmp)


def test_malformed_inputs_file_surfaces_its_own_reason_never_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        p = tmp / ".dv-harness" / "system_transaction_e2e_scoreboard" / "inputs.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not valid json", encoding="utf-8")

        status, data = _get(base, "/api/system-transaction-e2e-scoreboard")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert data["system_transaction"] is None
    finally:
        shutil.rmtree(tmp)


def test_full_overlay_served_report_matches_the_three_real_modules_directly():
    """The headline proof: every one of the three served sections must be
    byte-identical to independently calling that module's own real, unmodified
    builder over the identical declared facts -- proving the endpoint reads
    the real modules rather than re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        overlay = _full_overlay()
        _write_inputs(tmp, overlay)

        status, data = _get(base, "/api/system-transaction-e2e-scoreboard")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        from dv_harness import system_transaction_ir as sti
        from dv_harness import transaction_correlation_ir as tci
        from dv_harness import system_scoreboard_ir as ssi

        st_overlay = overlay["system_transaction"]
        expected_st = sti.build_system_transaction_ir(
            st_overlay["subsystem_fabrics"], st_overlay["system_transaction_links"])
        assert data["system_transaction"]["error"] is None
        assert data["system_transaction"]["report"] == expected_st.to_dict()
        assert data["system_transaction"]["report"]["overall_status"] == \
            sti.OVERALL_COMPLETE
        assert data["system_transaction"]["markdown"] == \
            sti.render_system_transaction_markdown(expected_st)

        tc_overlay = overlay["transaction_correlation"]
        expected_responses = tci.correlate_responses(
            tc_overlay["requests"], tc_overlay["responses"])
        expected_data_report = tci.associate_data_beats(
            tc_overlay["data_transactions"], tc_overlay["beats"])
        expected_logical = tci.reconstruct_logical_transactions(
            tc_overlay["transactions"], expected_responses, expected_data_report)
        assert data["transaction_correlation"]["error"] is None
        assert data["transaction_correlation"]["logical_transactions"] == \
            [e.to_dict() for e in expected_logical]
        assert data["transaction_correlation"]["response_correlation"] == \
            [e.to_dict() for e in expected_responses]
        assert data["transaction_correlation"]["data_association"] == \
            expected_data_report.to_dict()
        assert data["transaction_correlation"]["logical_transactions"][0]["status"] == \
            tci.LOGICAL_TXN_COMPLETE
        assert data["transaction_correlation"]["markdown"] == \
            tci.render_logical_transaction_report(expected_logical)

        ss_overlay = overlay["system_scoreboard"]
        expected_ss = ssi.build_system_scoreboard_ir(
            ss_overlay["system_interactions"], ss_overlay["existing_scoreboards"])
        assert data["system_scoreboard"]["error"] is None
        assert data["system_scoreboard"]["report"] == expected_ss.to_dict()
        assert data["system_scoreboard"]["report"]["overall_status"] == \
            ssi.OVERALL_COMPLETE
        assert data["system_scoreboard"]["markdown"] == \
            ssi.render_system_scoreboard_markdown(expected_ss)
    finally:
        shutil.rmtree(tmp)


def test_one_section_build_failure_never_hides_the_other_two():
    """A malformed `system_transaction_links` entry (missing the required
    `evidence` citation) must surface `SYSTEM_TRANSACTION_BUILD_FAILED` for
    that section ALONE -- the other two sections, built from otherwise-valid
    facts in the same overlay, must still render their own real reports."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        overlay = _full_overlay()
        # Break ONLY the system_transaction section.
        del overlay["system_transaction"]["system_transaction_links"][0]["evidence"]
        _write_inputs(tmp, overlay)

        status, data = _get(base, "/api/system-transaction-e2e-scoreboard")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        assert data["system_transaction"]["report"] is None
        assert data["system_transaction"]["error"]["reason"] == \
            "SYSTEM_TRANSACTION_BUILD_FAILED"

        # The other two sections are untouched by the broken one.
        assert data["transaction_correlation"]["error"] is None
        assert len(data["transaction_correlation"]["logical_transactions"]) == 1
        assert data["system_scoreboard"]["error"] is None
        assert data["system_scoreboard"]["report"]["overall_status"] == \
            "SYSTEM_SCOREBOARD_COMPOSITION_COMPLETE"
    finally:
        shutil.rmtree(tmp)


def test_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() -- an
    endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="systemTransactionE2EScoreboardCard"' in html
        assert "System Transaction View + End-to-End Scoreboard" in html
        assert "'/api/system-transaction-e2e-scoreboard'" in html
        assert "await loadSystemTransactionE2EScoreboard();" in html
        assert 'id="steTiles"' in html
        assert 'id="steSystemTransactionPre"' in html
        assert 'id="steTransactionCorrelationPre"' in html
        assert 'id="steSystemScoreboardPre"' in html
        # This card is read-only, matching every reader function it reuses
        # the convention of -- no POST verb of its own.
        assert "Read-only" in html.split('id="systemTransactionE2EScoreboardCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
