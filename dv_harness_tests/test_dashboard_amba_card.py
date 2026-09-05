"""GET /api/amba -- the AMBA Fabric / VIP Bind / Scoreboard dashboard card
(GUI-09, 2026-09-05 GUI completeness audit).

Before this, dashboard.py contained zero references to the AMBA discovery
pipeline, even though amba_fabric_discovery.py -> amba_port_registry.py ->
amba_scoreboard_env.py already produce AMBA-22's AMBA_PORT_REGISTRY: the single
artifact joining, per discovered fabric port, its protocol, fabric/endpoint
role, traced endpoint hierarchy, AMBA-15 widths, AMBA-20 vip_mode and the
AMBA-21 scoreboard_channel that port's proposed VIP monitor would feed.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers
rather than standing up a second one -- the same cross-test import convention
test_amba_port_registry.py already uses for its RTL fixture.

Registry fixtures are written through the REAL
amba_port_registry.save_amba_port_registry(), which runs that module's own
assert_registry_complete() on the way out, so a fixture that drifted from
AMBA-22's nineteen-field contract fails at write time rather than quietly
proving the endpoint against a shape the real pipeline never produces.
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


def _amba_registry_rows():
    """Two real-shaped AMBA_PORT_REGISTRY rows, built from the real vocabulary
    constants (never hand-typed status strings): one fully-traced AXI
    slave-interface port that resolved a master endpoint, has an AMBA-20 VIP
    planned and an AMBA-21 scoreboard channel mapped, and one port whose trace
    was blocked -- no endpoint, no VIP, no channel. A fixture with only the
    clean port would prove nothing about the unresolved half this card exists
    to surface."""
    from dv_harness.amba_fabric_discovery import (
        BIND_CHECK_UNKNOWN_VALUE,
        BIND_READINESS_BLOCKED,
        BIND_READINESS_READY,
        TraceTerminationStatus,
    )
    from dv_harness.amba_port_registry import (
        ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
        VIP_MODE_NOT_PLANNED,
    )
    from dv_harness.connectivity import (
        EXTERNAL_ENDPOINT_MASTER,
        FABRIC_SIDE_MASTER_INTERFACE,
        FABRIC_SIDE_SLAVE_INTERFACE,
        REQUIRED_HUMAN_INPUT,
    )
    return [
        {
            "port_id": "U_FABRIC_S00_AXI_", "fabric_port": "u_fabric:S00_AXI_",
            "protocol": "AXI4", "fabric_role": FABRIC_SIDE_SLAVE_INTERFACE,
            "endpoint_role": EXTERNAL_ENDPOINT_MASTER,
            "endpoint_hierarchy": "u_soc/u_cpu",
            "vip_bind_hierarchy": "u_soc/u_cpu/axi_if",
            "vip_mode": "PASSIVE_MONITOR", "clock": "aclk", "reset": "aresetn",
            "address_width": "32", "data_width": "64", "id_width": "4",
            "user_widths": BIND_CHECK_UNKNOWN_VALUE,
            "scoreboard_channel": "axi_sb.m_axi_ap",
            "trace_status": TraceTerminationStatus.SOURCE_FOUND.value,
            "readiness": BIND_READINESS_READY, "confidence": "HIGH",
            "source_evidence": ["amba16_matrix:u_fabric:S00_AXI_", "amba15_checklist"],
            "row_id": "u_fabric:S00_AXI_", "parent_row_id": None,
            "vip_id": "VIP_AXI_S00", "amba11_second_side": False,
            "last_known_hierarchy": "u_soc/u_cpu",
        },
        {
            "port_id": "U_FABRIC_M01_APB_", "fabric_port": "u_fabric:M01_APB_",
            "protocol": "APB4", "fabric_role": FABRIC_SIDE_MASTER_INTERFACE,
            "endpoint_role": BIND_CHECK_UNKNOWN_VALUE,
            "endpoint_hierarchy": ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
            "vip_bind_hierarchy": REQUIRED_HUMAN_INPUT,
            "vip_mode": VIP_MODE_NOT_PLANNED, "clock": "pclk",
            "reset": BIND_CHECK_UNKNOWN_VALUE,
            "address_width": BIND_CHECK_UNKNOWN_VALUE,
            "data_width": BIND_CHECK_UNKNOWN_VALUE,
            "id_width": BIND_CHECK_UNKNOWN_VALUE,
            "user_widths": BIND_CHECK_UNKNOWN_VALUE,
            "scoreboard_channel": REQUIRED_HUMAN_INPUT,
            "trace_status": TraceTerminationStatus.TRACE_BLOCKED.value,
            "readiness": BIND_READINESS_BLOCKED, "confidence": "LOW",
            "source_evidence": ["amba16_matrix:u_fabric:M01_APB_"],
            "row_id": "u_fabric:M01_APB_", "parent_row_id": None,
            "vip_id": None, "amba11_second_side": False,
            "last_known_hierarchy": "",
        },
    ]


def _write_amba_registry(tmp: Path) -> Path:
    from dv_harness.amba_port_registry import save_amba_port_registry
    from dv_harness.dashboard import _default_amba_registry_path

    path = _default_amba_registry_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_amba_port_registry(_amba_registry_rows(), path)
    return path


def test_amba_reports_honest_empty_state_when_no_registry_exists():
    """No AMBA discovery pass has run in this project: the endpoint must say so
    and name the path it looked at, never invent a fabric port -- the same
    honest-empty-state contract GET /api/coverage already holds to."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/amba")
        assert status == 200
        assert data["available"] is False
        assert data["rows"] == []
        assert data["summary"] is None
        assert data["endpoints"] is None
        assert data["error"] is None
        assert data["registry_path"].endswith("amba_port_registry.json")
        assert not Path(data["registry_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_amba_returns_real_registry_rows_and_derived_summary():
    """A real registry on disk reaches the endpoint with all nineteen AMBA-22
    fields intact, and every derived number equals what the REAL
    amba_port_registry helpers compute -- not a dashboard-local re-derivation
    that could disagree with the artifact a human reviewed."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        registry_path = _write_amba_registry(tmp)

        from dv_harness.amba_port_registry import (
            AMBA_PORT_REGISTRY_FIELDS,
            load_amba_port_registry,
            registry_endpoints,
        )

        status, data = _get(base, "/api/amba")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["registry_path"] == str(registry_path)

        expected_rows = load_amba_port_registry(registry_path)
        assert data["rows"] == expected_rows
        for row in data["rows"]:
            for field in AMBA_PORT_REGISTRY_FIELDS:
                assert field in row and row[field] not in (None, "", [])

        assert data["endpoints"] == registry_endpoints(expected_rows)
        assert data["endpoints"]["masters"] == ["u_soc/u_cpu"]
        assert data["endpoints"]["slaves"] == []
        assert [u["port_id"] for u in data["endpoints"]["unresolved"]] == ["U_FABRIC_M01_APB_"]

        s = data["summary"]
        assert s["fabric_port_count"] == 2 and s["row_count"] == 2
        assert s["readiness_counts"] == {"READY": 1, "BLOCKED": 1}
        assert s["vip_planned"] == 1 and s["vip_not_planned"] == 1
        # A REQUIRED_HUMAN_INPUT channel counts as UNmapped: "nothing established
        # where this monitor would feed" is a finding a reviewer must see, not a
        # value that can be folded in with a real channel.
        assert s["scoreboard_channel_mapped"] == 1
        assert s["scoreboard_channel_required_human_input"] == 1
        assert s["traced_master_count"] == 1 and s["traced_slave_count"] == 0
        assert s["unresolved_count"] == 1
    finally:
        shutil.rmtree(tmp)


def test_amba_reports_registry_error_reason_rather_than_a_500():
    """A registry row missing an AMBA-22 column must surface
    amba_port_registry's own PortRegistryError reason/detail -- naming the
    port_id and the missing field -- not a stack trace and not a blank cell.
    Written by hand precisely because the real writer refuses it."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.amba_port_registry import AMBA_PORT_REGISTRY_FIELDS
        from dv_harness.dashboard import _default_amba_registry_path

        broken = _amba_registry_rows()[0]
        broken.pop("data_width")
        _write_json(_default_amba_registry_path(tmp),
                    {"amba_port_registry_fields": list(AMBA_PORT_REGISTRY_FIELDS),
                     "rows": [broken]})

        status, data = _get(base, "/api/amba")
        assert status == 200
        assert data["available"] is True
        assert data["rows"] == [] and data["summary"] is None
        assert data["error"]["reason"] == "AMBA_PORT_REGISTRY_INCOMPLETE_ROW"
        assert data["error"]["detail"]["port_id"] == "U_FABRIC_S00_AXI_"
        assert data["error"]["detail"]["missing_fields"] == ["data_width"]
    finally:
        shutil.rmtree(tmp)


def test_amba_reports_malformed_registry_file_rather_than_a_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.dashboard import _default_amba_registry_path
        p = _default_amba_registry_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")

        status, data = _get(base, "/api/amba")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_REGISTRY_FILE"
        assert data["rows"] == []
    finally:
        shutil.rmtree(tmp)


def test_amba_registry_path_is_overridable_by_query_param():
    """Mirrors GET /api/coverage's ?summary= override: a project whose AMBA
    discovery pass wrote its registry elsewhere points at it, rather than this
    module guessing a second location."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.amba_port_registry import save_amba_port_registry
        elsewhere = tmp / "fabric_out" / "registry.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        save_amba_port_registry(_amba_registry_rows(), elsewhere)

        status, data = _get(base, "/api/amba")
        assert data["available"] is False  # default location still honestly empty

        status, data = _get(base, "/api/amba?registry="
                             + urllib.parse.quote(str(elsewhere), safe=""))
        assert status == 200
        assert data["available"] is True
        assert data["registry_path"] == str(elsewhere)
        assert [r["port_id"] for r in data["rows"]] == ["U_FABRIC_S00_AXI_",
                                                        "U_FABRIC_M01_APB_"]
    finally:
        shutil.rmtree(tmp)


def test_amba_card_is_served_and_wired_into_the_page_load():
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
        assert 'id="ambaFabricCard"' in html
        assert "AMBA Fabric / VIP Bind / Scoreboard" in html
        assert "'/api/amba'" in html
        assert "await loadAmbaFabric();" in html
        # AMBA-30 / AMBA-31: a planning surface. It offers no write path and
        # says so, and it renders no SystemVerilog bind statement.
        assert "Discovery and planning only" in html
    finally:
        shutil.rmtree(tmp)


def test_amba_card_renders_no_bind_statement():
    """The same assert_no_bind_statement() gate amba_port_registry.py runs over
    its own rendered report, run over what this dashboard actually serves: the
    card's HTML plus a real registry payload. A planning surface that
    accidentally rendered emittable SystemVerilog would be a way past AMBA-30's
    review gate."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)
        _write_amba_registry(tmp)

        from dv_harness.amba_fabric_discovery import assert_no_bind_statement

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        _, data = _get(base, "/api/amba")

        # Raises FabricDiscoveryError if either carries a bind statement.
        assert_no_bind_statement(html)
        assert_no_bind_statement(json.dumps(data))
    finally:
        shutil.rmtree(tmp)
