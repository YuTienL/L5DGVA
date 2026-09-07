"""GET /api/verification-architecture -- the Verification Architecture View
dashboard card (item: dashboard_verification_architecture_view, Web Control
Plane theme, CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections 342-402).

REUSE OVER REINVENT: `dv_harness/verification_architecture.py` already exists
and already computes the real 5 required matrices (VIP Bind,
Interface-to-Verification, Function-to-Checker, Assertion Placement,
Scoreboard Architecture) plus its two real comparators
(`detect_placement_conflicts()`/`detect_intra_subsystem_duplicates()`) --
this change adds NO new analysis engine behind the card. It is a pure
dashboard wiring gap, closed the same way the Requirement/vPlan Center and
Design Knowledge Explorer cards were: a thin
`_read_verification_architecture_state()` reader following the file's
existing `{"available", "error"}` honest-empty-state contract, one read-only
GET endpoint, and a fetch-once + client-side-render card.

`verification_architecture.py` discovers no project fact itself (every one of
`assemble_verification_architecture()`'s keyword arguments is a caller-
supplied real fact from `env_manifest.py`/`connectivity.py`/`phy_boundary.py`
or a project's own declared linkage), so this card reads whatever a real
upstream assembly step wrote to
`.dv-harness/verification_architecture/inputs.json` -- mirroring the exact
convention `design_knowledge_correlation.py`'s own `sources.json` card and
`requirement_contract.py`/`vplan_artifact.py`'s own `requirements.json`/
`vplan.json` cards already established.

These tests prove:
  * The card READS the real module. The served document is compared against
    what `verification_architecture.assemble_verification_architecture()`
    itself computes over the identical inputs -- never a string typed into
    the test, so a dashboard-local re-derivation that drifted from the real
    module would fail here.
  * The Evidence Truth Rule holds on the served surface: a project with no
    inputs.json on disk must never render a fabricated matrix, and a
    malformed/unrecognized/schema-invalid inputs file must surface its own
    reason/detail rather than a bare 500 or a silently empty card -- the
    negative control this project's house style requires.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention
test_dashboard_requirement_vplan_center.py already uses.
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

INPUTS_REL_PATH = Path(".dv-harness") / "verification_architecture" / "inputs.json"


def _write_inputs(tmp: Path, raw) -> Path:
    d = tmp / ".dv-harness" / "verification_architecture"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "inputs.json"
    if isinstance(raw, str):
        p.write_text(raw, encoding="utf-8")
    else:
        p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def _real_inputs() -> dict:
    """A real, self-contained input set -- built entirely from
    `connectivity.py`'s own real entry-generating functions (never a hand-
    typed dict standing in for what they produce), JSON-round-tripped so it
    is exactly what a real project's own on-disk inputs.json would carry."""
    from dv_harness import connectivity

    tier = connectivity.classify_bind_tier(existing_bind={"target": "chip.core.usb0.host_vip"})
    check_entry = connectivity.generate_protocol_check_entry(
        "chip.core.usb0::axi_if", "svt_usb3", ["c1"], {})
    sb_entry = connectivity.generate_scoreboard_entry(
        "sb_main", [("chip.core.usb0.apb_if", "chip.core.usb0.axi_if")], "addr")
    raw = {
        "bind_entries": [
            {"target_instance": "chip.core.usb0.host_vip", "ports": ["pipe_txdata"],
             "reason": "r", "tier": tier.tier.value},
        ],
        "boundary_by_target": {
            "chip.core.usb0.host_vip": {"mount_layer": "PARALLEL", "bindable": True},
        },
        "protocol_check_entries": [check_entry],
        "checker_links": {
            "chip.core.usb0::axi_if": {"target_instance": "chip.core.usb0.axi_if",
                                        "mount_side": "POST_BRIDGE"},
        },
        "scoreboard_entries": [sb_entry],
        "assertion_candidates": [
            {"assertion_id": "A_MAIN", "target_instance": "chip.core.usb0.axi_if",
             "clock_domain": "usb_clk_domain", "reset_domain": "usb_clk_domain"},
        ],
    }
    # JSON-round-trip so the test writes exactly what a real project's own
    # on-disk file would contain (e.g. the scoreboard's endpoint_pairs tuple
    # becomes a JSON array of arrays).
    return json.loads(json.dumps(raw))


def test_verification_architecture_honest_empty_state_on_a_bare_project():
    """No inputs.json on disk -> an honest {"available": False} naming the
    real file this endpoint looked for, never a fabricated matrix."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/verification-architecture")
        assert status == 200
        assert data["available"] is False
        assert data["error"] is None
        assert data["document"] is None
        assert data["inputs_path"].endswith(str(INPUTS_REL_PATH))
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_reports_a_malformed_inputs_file_honestly():
    """An inputs.json that is not valid JSON must surface as this endpoint's
    own reason/detail -- never a bare 500, and never a silently empty card
    claiming nothing is wrong. The negative control this project's house
    style requires."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, "not valid json{")

        status, data = _get(base, "/api/verification-architecture")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert data["document"] is None
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_reports_a_non_object_inputs_file_honestly():
    """An inputs.json that parses but is not a JSON object (e.g. a bare
    list) must be refused the same honest way as invalid JSON, never
    silently coerced into an empty document."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, [1, 2, 3])

        status, data = _get(base, "/api/verification-architecture")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_reports_an_unrecognized_input_key_honestly():
    """An inputs.json key `assemble_verification_architecture()` itself does
    not accept must surface the real TypeError rather than being silently
    dropped or crashing the server with a bare 500."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, {"this_key_does_not_exist": True})

        status, data = _get(base, "/api/verification-architecture")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert "this_key_does_not_exist" in data["error"]["detail"]["message"]
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_reports_a_schema_violation_honestly():
    """A real, schema-invalid assembled document (an empty instance_path,
    which verification_architecture.schema.json's own vip_selection_ir
    requires be non-empty) must surface VERIFICATION_ARCHITECTURE_SCHEMA_
    INVALID naming the real error -- never a fabricated matrix over a
    structurally invalid document. Confirmed first, directly against the
    real module, that this exact input really does trip
    validate_verification_architecture() before relying on it here."""
    from dv_harness import verification_architecture as va

    raw = {"vip_config": {"status": "CAPTURED",
                           "vip_instances": [{"instance_path": "", "vip_type": "usb3",
                                               "config_fields": {}}]}}
    doc = va.assemble_verification_architecture(**raw)
    doc.pop("_irs", None)
    try:
        va.validate_verification_architecture(doc)
        assert False, "expected this fixture to be schema-invalid"
    except va.VerificationArchitectureValidationError:
        pass

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, raw)

        status, data = _get(base, "/api/verification-architecture")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "VERIFICATION_ARCHITECTURE_SCHEMA_INVALID"
        assert data["document"] is None
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_reports_the_real_document_over_real_inputs():
    """Real inputs.json on disk -> the served document must equal what
    verification_architecture.assemble_verification_architecture() itself
    computes over the identical inputs -- proving the endpoint reads the
    real module rather than re-deriving anything, including the 5 required
    rendered matrices."""
    from dv_harness import verification_architecture as va

    raw = _real_inputs()
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, raw)

        status, data = _get(base, "/api/verification-architecture")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        expected = va.assemble_verification_architecture(**raw)
        expected.pop("_irs", None)
        assert data["document"] == expected

        doc = data["document"]
        assert len(doc["vip_bind"]) == 1
        assert doc["vip_bind"][0]["target_instance"] == "chip.core.usb0.host_vip"
        assert len(doc["checker"]) == 1
        assert len(doc["scoreboard"]) == 1
        assert len(doc["assertion"]) == 1

        matrices = doc["matrices"]
        for key in ("vip_bind", "interface_to_verification", "function_to_checker",
                    "assertion_placement", "scoreboard_architecture"):
            assert key in matrices
            assert isinstance(matrices[key], str) and matrices[key]
        assert "chip.core.usb0.host_vip" in matrices["vip_bind"]
        assert "chip.core.usb0::axi_if" in matrices["function_to_checker"]
        assert "A_MAIN" in matrices["assertion_placement"]
        assert "sb_main" in matrices["scoreboard_architecture"]

        # The document really re-validates against the real schema (this
        # endpoint already schema-validated it before serving it -- proven
        # again here, independently).
        to_validate = {k: v for k, v in doc.items() if k != "_irs"}
        va.validate_verification_architecture(to_validate)  # raises on failure
    finally:
        shutil.rmtree(tmp)


def test_verification_architecture_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    item exists to avoid, and this card must follow the same rendering
    convention (tiles + tables/pre blocks, fetch-once, no new template) as
    the Requirement/vPlan Center / Design Knowledge cards it was asked to
    reuse."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="verificationArchitectureCard"' in html
        assert "Verification Architecture View" in html
        assert "'/api/verification-architecture'" in html
        assert "await loadVerificationArchitecture();" in html
        assert 'id="verificationArchitectureTiles"' in html
        assert 'id="vaVipBindMatrix"' in html
        assert 'id="vaInterfaceMatrix"' in html
        assert 'id="vaCheckerMatrix"' in html
        assert 'id="vaAssertionMatrix"' in html
        assert 'id="vaScoreboardMatrix"' in html
        assert 'id="vaConflictsBody"' in html
        assert 'id="vaDuplicatesBody"' in html
        # This card is read-only, matching the convention every sibling card
        # it reuses follows -- no POST verb of its own.
        assert "Read-only" in html.split('id="verificationArchitectureCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
