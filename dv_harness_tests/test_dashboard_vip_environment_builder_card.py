"""GET /api/vip-environment-builder -- the "VIP/UVM Environment Builder + VIP
Evidence View" dashboard card (item: dashboard_vip_uvm_env_builder_evidence_
view, Web Control Plane theme, CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections
342-402).

REUSE OVER REINVENT: `dv_harness/protocol_capability.py` and
`dv_harness/vip_api_card.py` already exist and already compute the two real
facts this item names -- per-protocol `capability_status`
(protocol_capability.py, derived from modules verified to import) and the
real PROVEN/BLOCKED/UNPROVABLE VIPApiCard citation report for a generated
environment (vip_api_card.validate_vip_api_usage(), derived from a real
vip_symbol_index over real VIP source). This change adds NO new analysis
engine behind the card. It is a pure dashboard wiring gap: no route/card in
dashboard.py ever surfaced vip_api_card.py's report at all (the existing
Protocols card already surfaces capability_status alone). Closed the same way
the Requirement/vPlan Center and Verification Architecture cards were: a thin
`_read_vip_environment_builder_state()` reader following the file's existing
`{"available", "error"}` honest-empty-state contract, one read-only GET
endpoint, and a fetch-once + client-side-render card.

`vip_api_card.py` discovers no project fact itself (validate_vip_api_usage()
takes a caller-supplied source list and a real vip_symbol_index document), so
this card reads whatever a real upstream step wrote to
`.dv-harness/vip_evidence/inputs.json` -- mirroring the exact convention
`verification_architecture.py`'s own `inputs.json` card, and
`design_knowledge_correlation.py`'s own `sources.json` card, already
established.

These tests prove:
  * The card READS the real modules. The served VIP API report is compared
    against what `vip_api_card.validate_vip_api_usage()` itself computes over
    the identical real inputs (a real vip_symbol_index built over this
    repo's own synthetic VIP source, and the real clean generated-sequence
    fixture `vip_api_card`'s own test suite already ships) -- never a string
    typed into the test, so a dashboard-local re-derivation that drifted from
    the real module would fail here. A real, injected fabrication (the same
    `apply_preset` -> `apply_prezet` mutation `vip_api_card`'s own test suite
    uses) is proven to surface as a real BLOCKED citation on the served
    endpoint, not merely on the module directly.
  * The protocol capability half is reused, never re-derived: the served
    `protocols` list is compared against `_protocol_registry()`'s own real
    output over a real `protocol_capability_registry.json`, and is proven
    present even when no vip_evidence inputs.json exists at all (it needs no
    upstream step).
  * The Evidence Truth Rule holds on the served surface: a project with no
    inputs.json on disk must never render a fabricated report, and a
    malformed/incomplete/unresolvable inputs file must surface its own
    reason/detail rather than a bare 500 or a silently empty card -- the
    negative control this project's house style requires.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention
test_dashboard_verification_architecture_view.py already uses.
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

INPUTS_REL_PATH = Path(".dv-harness") / "vip_evidence" / "inputs.json"

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"
CLEAN_FIXTURE = Path(__file__).parent / "fixtures" / "vip_api" / "demo_env_seq.sv"


def _write_inputs(tmp: Path, raw) -> Path:
    d = tmp / ".dv-harness" / "vip_evidence"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "inputs.json"
    if isinstance(raw, str):
        p.write_text(raw, encoding="utf-8")
    else:
        p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def _write_real_index(tmp: Path) -> Path:
    """A REAL vip_symbol_index built by the real indexer over this repo's own
    synthetic VIP source (the same fixture vip_api_card.py's own test suite
    already exercises against) -- never a hand-written index dict."""
    from dv_harness import vip_symbol_index as vsi

    index = vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)
    idx_dir = tmp / ".dv-harness" / "vip_evidence"
    idx_dir.mkdir(parents=True, exist_ok=True)
    idx_path = idx_dir / "index.json"
    vsi.save_symbol_index(index, idx_path)
    return idx_path


def _write_generated_env(tmp: Path, text: str) -> Path:
    d = tmp / "generated_env"
    d.mkdir(parents=True, exist_ok=True)
    (d / "generated_seq.sv").write_text(text, encoding="utf-8")
    return d


def _write_protocol_registry(tmp: Path) -> None:
    d = tmp / ".dv-harness" / "qualification"
    d.mkdir(parents=True, exist_ok=True)
    (d / "protocol_capability_registry.json").write_text(json.dumps({
        "protocols": {
            "USB_2_3x": {"capability_status": "DUT_PROVEN", "qualification_status": "DUT_PROVEN",
                         "protocol_model_generator": "NONE"},
            "PCIe": {"capability_status": "PROTOCOL_MODEL_PARTIAL", "qualification_status": "BUILDER_AVAILABLE",
                     "protocol_model_generator": "dv_harness.uvm_generator.pcie_ltssm_generator"},
        }
    }), encoding="utf-8")


def test_vip_environment_builder_honest_empty_state_on_a_bare_project():
    """No vip_evidence/inputs.json on disk -> an honest {"available": False}
    naming the real file this endpoint looked for, never a fabricated
    report. `protocols` is still real (empty, since the bare project has no
    registered protocol either)."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is False
        assert data["error"] is None
        assert data["report"] is None
        assert data["protocols"] == []
        assert data["inputs_path"].endswith(str(INPUTS_REL_PATH))
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_the_real_protocol_registry_without_vip_evidence():
    """The protocol_capability_status half needs no vip_evidence/inputs.json
    at all -- it is the same real _protocol_registry() data the Protocols
    card already reads, proven equal to that function's own direct output."""
    from dv_harness.dashboard import _protocol_registry

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_protocol_registry(tmp)

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is False  # still no vip_evidence inputs.json
        assert data["report"] is None
        expected = _protocol_registry(tmp)
        assert data["protocols"] == expected
        names = {p["name"] for p in data["protocols"]}
        assert names == {"USB_2_3x", "PCIe"}
        usb = next(p for p in data["protocols"] if p["name"] == "USB_2_3x")
        assert usb["capability_status"] == "DUT_PROVEN"
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_a_malformed_inputs_file_honestly():
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

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert data["report"] is None
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_a_non_object_inputs_file_honestly():
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

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_missing_required_keys_honestly():
    """An inputs.json declaring neither "sources" nor "index_path" (the two
    keys this endpoint requires before it will call
    vip_api_card.validate_vip_api_usage() at all) must be refused with a
    named reason, never silently treated as an empty report."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, {"relative_to": "somewhere"})

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert "sources" in data["error"]["detail"]["message"]
        assert "index_path" in data["error"]["detail"]["message"]
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_an_unresolvable_index_honestly():
    """An index_path naming a file that does not exist must surface the real
    VipApiValidationError vip_api_card.load_index() raises -- never a bare
    500, and never silently read as "nothing to check"."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_inputs(tmp, {"sources": [str(tmp)], "index_path": str(tmp / "no_such_index.json")})

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "VIP_SYMBOL_INDEX_UNAVAILABLE"
        assert data["report"] is None
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_an_unrecognized_input_key_honestly():
    """An inputs.json key `validate_vip_api_usage()` itself does not accept
    must surface the real TypeError rather than being silently dropped or
    crashing the server with a bare 500."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        idx_path = _write_real_index(tmp)
        env_dir = _write_generated_env(tmp, CLEAN_FIXTURE.read_text(encoding="utf-8"))
        _write_inputs(tmp, {"sources": [str(env_dir)], "index_path": str(idx_path),
                            "this_key_does_not_exist": True})

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "MALFORMED_INPUTS_FILE"
        assert "this_key_does_not_exist" in data["error"]["detail"]["message"]
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_the_real_proven_report_over_real_inputs():
    """Real inputs.json on disk, over the real clean generated-sequence
    fixture and a real vip_symbol_index -> the served report must equal what
    vip_api_card.validate_vip_api_usage() itself computes over the identical
    inputs -- proving the endpoint reads the real module rather than
    re-deriving anything."""
    from dv_harness import vip_api_card as vac
    from dv_harness import vip_symbol_index as vsi

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        idx_path = _write_real_index(tmp)
        env_dir = _write_generated_env(tmp, CLEAN_FIXTURE.read_text(encoding="utf-8"))
        raw = {"sources": [str(env_dir)], "index_path": str(idx_path), "relative_to": str(env_dir)}
        _write_inputs(tmp, raw)

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        index = vsi.load_symbol_index(idx_path)
        expected = vac.validate_vip_api_usage([env_dir], index, relative_to=env_dir)
        assert data["report"] == expected.to_dict()

        rep = data["report"]
        assert rep["status"] == "PROVEN"
        assert rep["counts"]["BLOCKED"] == 0
        assert rep["counts"]["PROVEN"] > 0
        proven_citations = {c["citation"] for c in rep["cards"] if c["status"] == "PROVEN"}
        assert "svt_demo_cfg.apply_preset" in proven_citations
        proven_card = next(c for c in rep["cards"] if c["citation"] == "svt_demo_cfg.apply_preset")
        assert proven_card["resolved_file"]
        assert proven_card["resolved_line"] is not None
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_reports_a_real_blocked_citation_from_a_mutated_source():
    """A real, injected fabrication (apply_preset -> apply_prezet, the same
    mutation vip_api_card.py's own test suite uses) must surface as a real
    BLOCKED VIPApiCard on the served endpoint -- the negative control proving
    this card cannot be fooled into reporting PROVEN over a hallucinated VIP
    API call, exactly the fabrication spec section 187 exists to catch."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        idx_path = _write_real_index(tmp)
        mutated = CLEAN_FIXTURE.read_text(encoding="utf-8").replace(
            "apply_preset(2)", "apply_prezet(2)")
        assert "apply_prezet" in mutated  # the mutation actually landed
        env_dir = _write_generated_env(tmp, mutated)
        _write_inputs(tmp, {"sources": [str(env_dir)], "index_path": str(idx_path),
                            "relative_to": str(env_dir)})

        status, data = _get(base, "/api/vip-environment-builder")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        rep = data["report"]
        assert rep["status"] == "BLOCKED"
        assert rep["counts"]["BLOCKED"] == 1
        blocked = [c for c in rep["cards"] if c["status"] == "BLOCKED"]
        assert len(blocked) == 1
        assert blocked[0]["citation"] == "svt_demo_cfg.apply_prezet"
        assert blocked[0]["reason"]
    finally:
        shutil.rmtree(tmp)


def test_vip_environment_builder_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    item exists to avoid, and this card must follow the same rendering
    convention (tiles + tables, fetch-once, no new template) as the
    Verification Architecture / Requirement-vPlan Center cards it reuses."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="vipEnvironmentBuilderCard"' in html
        assert "VIP/UVM Environment Builder" in html
        assert "'/api/vip-environment-builder'" in html
        assert "await loadVipEnvironmentBuilder();" in html
        assert 'id="vipEnvBuilderProtocolTiles"' in html
        assert 'id="vipEnvBuilderTiles"' in html
        assert 'id="vipEnvBuilderBlockedBody"' in html
        assert 'id="vipEnvBuilderUnprovableBody"' in html
        assert 'id="vipEnvBuilderProvenBody"' in html
        # This card is read-only, matching the convention every sibling card
        # it reuses follows -- no POST verb of its own.
        assert "Read-only" in html.split('id="vipEnvironmentBuilderCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
