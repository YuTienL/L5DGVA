"""GET /api/protocol-selector -- the Protocol Selector dashboard card (GUI-02,
CLAUDE_L5_VIP_UVM_INTERACTIVE_INTAKE.md's "60. GUI-02 --- PROTOCOL SELECTOR").

The requirement: "Verify the GUI can display/select/detect applicable
protocols... The UI must distinguish: user-selected protocol, auto-detected
protocol, evidence, confidence, and conflict/ambiguity. Backend
`protocol-router` remains authoritative according to evidence and policy."

REUSE OVER REINVENT: dv_harness/protocol_router.py already exists and already
implements the real protocol-router this GUI requirement names --
resolve_protocol() is a real, evidence-driven classifier (over
protocol_hint/failing_test_name/active_config/modified_files/
subsystem_boundary, SKILL.md's own tie-break order). This change adds NO new
protocol-classification logic anywhere: it reads a caller-declared evidence
document at this project's own conventional
`.dv-harness/protocol_selector/inputs.json` path (mirroring
`.dv-harness/multi_vip_cooperation/inputs.json`'s convention elsewhere in this
file, since protocol_router.py -- like that module -- discovers no project
fact itself) and calls resolve_protocol() three times over it: once for the
user's own declared protocol_hint alone, once for every OTHER field (the
"auto-detected" protocol, independent of what the user typed), and once over
every field together (protocol-router's own real authoritative answer).

These tests exist to prove:

  * The card serves protocol_router.resolve_protocol()'s own real output
    verbatim for all three calls -- never a dashboard-local re-derivation of
    its normalization/alias/tie-break logic.
  * The Evidence Truth Rule holds on the served surface: a bare project (no
    evidence ever declared) must never render a fabricated protocol, and a
    malformed evidence file must surface its own honest reason rather than a
    bare 500 or a silently empty card.
  * A genuine user-declared-vs-auto-detected disagreement is reported as
    `conflict: True`, with protocol-router's own real tie-break answer
    (authoritative) shown alongside it -- this card never arbitrates the
    disagreement a second way.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention test_dashboard_smoke_proof_card.py
already uses.
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
)


def _write_inputs(tmp: Path, payload, *, path: Path | None = None) -> Path:
    p = path or (tmp / ".dv-harness" / "protocol_selector" / "inputs.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_protocol_selector_reports_honest_empty_state_on_a_bare_project():
    """A project with no declared evidence must report {"available": False},
    naming the real conventional path this endpoint looked for -- never a
    fabricated protocol and never a silent empty-but-`available: True`
    response."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/protocol-selector")
        assert status == 200
        assert data["available"] is False
        assert data["user_declared"] is None
        assert data["auto_detected"] is None
        assert data["authoritative"] is None
        assert data["conflict"] is None
        assert data["confidence"] is None
        assert data["error"] is None
        assert data["inputs_path"].replace("\\", "/").endswith(
            ".dv-harness/protocol_selector/inputs.json")
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_serves_the_real_resolve_protocol_output_when_user_and_evidence_agree():
    """A declared protocol_hint that agrees with the evidence-derived protocol
    must be reported HIGH confidence, no conflict, and every field must match
    a direct call into protocol_router.resolve_protocol() over the identical
    evidence -- proving the endpoint reads the real module rather than
    re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import protocol_router as pr

        declared = {
            "protocol_hint": "USB3",
            "failing_test_name": "test_usb3_link_training",
            "active_config": None,
            "modified_files": None,
            "subsystem_boundary": None,
        }
        _write_inputs(tmp, declared)

        status, data = _get(base, "/api/protocol-selector")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        expected_user = pr.resolve_protocol({"protocol_hint": "USB3"})
        expected_auto = pr.resolve_protocol({
            "failing_test_name": "test_usb3_link_training",
            "active_config": None, "modified_files": None, "subsystem_boundary": None,
        })
        expected_authoritative = pr.resolve_protocol(declared)

        assert data["user_declared"] == expected_user
        assert data["auto_detected"] == expected_auto
        assert data["authoritative"] == expected_authoritative
        assert data["user_declared"]["protocol"] == "usb"
        assert data["auto_detected"]["protocol"] == "usb"
        assert data["conflict"] is False
        assert data["confidence"] == "HIGH"
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_reports_a_real_conflict_and_never_arbitrates_it():
    """A user-declared protocol that genuinely disagrees with what the
    evidence alone resolves to must be reported conflict=True, LOW
    confidence, with protocol-router's own real authoritative tie-break
    answer served alongside -- this card must never pick a winner itself."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import protocol_router as pr

        declared = {
            "protocol_hint": "PCIe",
            "failing_test_name": "test_usb3_link_training",
            "active_config": None,
            "modified_files": None,
            "subsystem_boundary": None,
        }
        _write_inputs(tmp, declared)

        status, data = _get(base, "/api/protocol-selector")
        assert status == 200
        assert data["available"] is True
        assert data["user_declared"]["protocol"] == "pcie"
        assert data["auto_detected"]["protocol"] == "usb"
        assert data["conflict"] is True
        assert data["confidence"] == "LOW"
        # protocol-router's own real tie-break order (user intent first, per
        # SKILL.md) must still resolve the authoritative answer to the
        # user-declared protocol -- this card never overrides that.
        expected_authoritative = pr.resolve_protocol(declared)
        assert data["authoritative"] == expected_authoritative
        assert data["authoritative"]["protocol"] == "pcie"
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_reports_malformed_json_honestly_never_a_500():
    """A file that exists but is not valid JSON must surface a named, honest
    error rather than a bare 500 or a silently empty card."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, "{not valid json, at all")

        status, data = _get(base, "/api/protocol-selector")
        assert status == 200
        assert data["user_declared"] is None
        assert data["error"]["reason"] == "MALFORMED_PROTOCOL_SELECTOR_INPUTS_FILE"
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_reports_non_object_document_honestly():
    """A file that IS valid JSON but is not an object (e.g. a bare list) must
    never be silently coerced into an evidence dict -- named and refused
    instead."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, ["not", "an", "object"])

        status, data = _get(base, "/api/protocol-selector")
        assert status == 200
        assert data["user_declared"] is None
        assert data["error"]["reason"] == "PROTOCOL_SELECTOR_INPUTS_NOT_A_DOCUMENT"
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_with_no_protocol_hint_never_fabricates_a_user_declared_value():
    """When the evidence document declares no protocol_hint at all,
    user_declared must stay honestly None rather than a guessed value, while
    auto_detected still resolves from the other real fields."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        declared = {
            "failing_test_name": "test_pcie_link_train",
            "active_config": None, "modified_files": None, "subsystem_boundary": None,
        }
        _write_inputs(tmp, declared)

        status, data = _get(base, "/api/protocol-selector")
        assert status == 200
        assert data["available"] is True
        assert data["user_declared"] is None
        assert data["auto_detected"]["protocol"] == "pcie"
        assert data["conflict"] is False
        assert data["confidence"] == "MEDIUM"
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_query_param_overrides_the_conventional_path():
    """?evidence=<path> must read from the named file rather than the
    conventional one, the same override convention /api/system-smoke-proof's
    ?report= and /api/design-knowledge's ?sources= already use."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        alt_path = tmp / "elsewhere" / "my_evidence.json"
        declared = {"protocol_hint": "AMBA", "failing_test_name": None,
                    "active_config": None, "modified_files": None, "subsystem_boundary": None}
        _write_inputs(tmp, declared, path=alt_path)

        # The conventional path still has nothing -- proves the override is
        # really what is being read, not a coincidental fallback.
        status_default, data_default = _get(base, "/api/protocol-selector")
        assert data_default["available"] is False

        status, data = _get(base, "/api/protocol-selector?evidence="
                             + urllib.parse.quote(str(alt_path)))
        assert status == 200
        assert data["available"] is True
        assert data["user_declared"]["protocol"] == "amba"
        assert data["inputs_path"].replace("\\", "/") == str(alt_path).replace("\\", "/")
    finally:
        shutil.rmtree(tmp)


def test_protocol_selector_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="protocolSelectorCard"' in html
        assert "Protocol Selector" in html
        assert "'/api/protocol-selector'" in html
        assert "await loadProtocolSelector();" in html
        assert 'id="protocolSelectorTiles"' in html
        assert 'id="protocolSelectorBody"' in html
        for header in ("Source", "Protocol", "Matched Field", "Evidence"):
            assert f">{header}<" in html
        # Read-only, matching every reader function this card reuses the
        # convention of -- no POST verb of its own.
        assert "Read-only" in html.split('id="protocolSelectorCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
