"""Tests for the asset-processing table's previously-missing artifact types
(2026-09-04 gap-closing pass over rows 2, 8, 9, 10, 11, 12, 13):

  phy_boundary.py    row 2   PHY<->controller serial/parallel boundary -> bind location
  sys_regmap.py      row 8   global control bits -> mode-determining bits
  init_seq.py        row 10  register write order/waits -> directed test + Gate-2 precondition
  design_intent.py   rows 9 and 11  intent.md / constraints.md -> scoreboard + exemption list
  vip_symbol_index.py rows 12 and 13  VIP source symbol index -> vip_ref/<protocol>.md

Every test asserts against real behaviour of real code. The worked examples
under examples/asset_processing/ are exercised as real inputs so the committed
artifacts cannot silently rot away from the generators that produce them.

The highest-value assertions here, i.e. the ones that would actually catch a
regression that matters:
  * `test_serial_boundary_is_refused_for_binding` -- the whole point of row 2.
  * `test_differential_lanes_are_payload` -- if this broke, every serial
    boundary would misclassify as UNDECIDABLE and the row-2 gate would stop
    firing.
  * `test_gated_interpretation_*` -- the row-8/10 payoff: an identical Gate-2
    dead-clock FAIL must read as PRECONDITION_NOT_MET or CONNECTIVITY_FAILURE
    depending purely on whether the clock-enable bit was really programmed.
  * `test_index_retains_no_method_bodies` -- the row-13 invariant that makes
    indexing a tier-1-denied VIP tree legitimate at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness import design_intent, init_seq, phy_boundary, sys_regmap, vip_symbol_index
from dv_harness.connectivity import GateStatus, SignalTrace

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples" / "asset_processing"
INPUTS = EXAMPLES / "inputs"
GENERATED = EXAMPLES / "generated"


# ===========================================================================
# row 2 -- phy_boundary.py
# ===========================================================================

def _mod(name, ports):
    return {"name": name, "ports": [
        {"name": n, "direction": d, "data_type": t} for n, d, t in ports]}


PARALLEL_PAIR = [
    _mod("phy", [("pclk", "input", "logic"), ("pipe_txdata", "input", "logic [31:0]"),
                 ("pipe_rxdata", "output", "logic [31:0]"), ("txp", "output", "logic")]),
    _mod("ctrl", [("pclk", "input", "logic"), ("pipe_txdata", "output", "logic [31:0]"),
                  ("pipe_rxdata", "input", "logic [31:0]")]),
]
SERIAL_PAIR = [
    _mod("aphy", [("refclk", "input", "logic"), ("serial_txp", "output", "logic"),
                  ("serial_rxn", "input", "logic")]),
    _mod("actrl", [("refclk", "input", "logic"), ("serial_txp", "input", "logic"),
                   ("serial_rxn", "output", "logic")]),
]


@pytest.mark.parametrize("data_type,expected", [
    ("logic", 1), ("logic [31:0]", 32), ("logic [3:0]", 4), ("bit [7:0]", 8),
    ("logic [1:0][7:0]", 16),
    # Unresolvable parameterized widths must report None, never a defaulted 1:
    # counting one as a 1-bit serial signal would produce a confident wrong
    # bind decision.
    ("logic [WIDTH-1:0]", None), ("logic [N:0]", None), (None, None),
])
def test_parse_port_width(data_type, expected):
    assert phy_boundary.parse_port_width(data_type) == expected


@pytest.mark.parametrize("name", [
    "pclk", "refclk", "preset_n", "por_n", "pipe_rxvalid", "pipe_powerdown", "rst_n",
])
def test_control_ports_are_not_payload(name):
    assert phy_boundary.is_payload_port(name) is False


@pytest.mark.parametrize("name", ["txp", "txn", "rxp", "rxn", "serial_txp", "serial_rxn"])
def test_differential_lanes_are_payload(name):
    """Differential serial lanes ARE the payload of a serial boundary. If the
    control-token filter ever swallowed them, every serial boundary would
    have zero payload signals and classify UNDECIDABLE instead of SERIAL --
    silently disabling the row-2 not-bindable gate rather than failing
    loudly."""
    assert phy_boundary.is_payload_port(name) is True


@pytest.mark.parametrize("name", ["pipe_rxdata", "app_wdata", "token", "channel_data"])
def test_ordinary_payload_names_are_payload(name):
    assert phy_boundary.is_payload_port(name) is True


def test_parallel_boundary_is_bindable_at_parallel_signals():
    doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "phy", "ctrl")
    assert doc["status"] == "EXTRACTED"
    assert doc["classification"]["kind"] == "PARALLEL"
    assert doc["classification"]["tier"] == "B2_STRUCTURAL_WIDTH"
    assert doc["bind_decision"]["mount_layer"] == "controller_phy_parallel_boundary"
    assert doc["bind_decision"]["bindable"] is True
    assert doc["bind_decision"]["recommended_bind_signals"] == ["pipe_rxdata", "pipe_txdata"]
    # txp is on the PHY only, so it is not part of the shared boundary at all.
    assert "txp" not in {s["name"] for s in doc["boundary_signals"]}


def test_serial_boundary_is_refused_for_binding():
    """Row 2's core purpose: a monitor bound at a serial boundary passes
    Gates 1 and 2 and fails Gate 3 as a silent monitor, so the bind must be
    refused up front rather than emitted."""
    doc = phy_boundary.extract_phy_boundary(SERIAL_PAIR, "aphy", "actrl")
    assert doc["classification"]["kind"] == "SERIAL"
    assert doc["classification"]["serial_signals"] == ["serial_rxn", "serial_txp"]
    assert doc["bind_decision"]["bindable"] is False
    assert doc["bind_decision"]["mount_layer"] == "serial_boundary_not_bindable"
    with pytest.raises(phy_boundary.PhyBoundaryValidationError, match="NOT_BINDABLE"):
        phy_boundary.assert_bind_location_allowed(doc)


def test_mixed_boundary_binds_parallel_signals_only():
    pair = [
        _mod("p", [("lane_txp", "output", "logic"), ("sym_data", "output", "logic [15:0]")]),
        _mod("c", [("lane_txp", "input", "logic"), ("sym_data", "input", "logic [15:0]")]),
    ]
    doc = phy_boundary.extract_phy_boundary(pair, "p", "c")
    assert doc["classification"]["kind"] == "MIXED"
    assert doc["bind_decision"]["bindable"] is True
    assert doc["bind_decision"]["recommended_bind_signals"] == ["sym_data"]
    # Binding the serial lane of a MIXED boundary must still be refused.
    with pytest.raises(phy_boundary.PhyBoundaryValidationError, match="SIGNAL_NOT_SANCTIONED"):
        phy_boundary.assert_bind_location_allowed(doc, target_signals=["lane_txp"])
    assert phy_boundary.assert_bind_location_allowed(doc, target_signals=["sym_data"])


def test_unresolvable_widths_go_to_human_not_a_guess():
    pair = [
        _mod("p", [("bus", "output", "logic [W-1:0]")]),
        _mod("c", [("bus", "input", "logic [W-1:0]")]),
    ]
    doc = phy_boundary.extract_phy_boundary(pair, "p", "c")
    assert doc["classification"]["kind"] == "UNDECIDABLE"
    assert doc["classification"]["tier"] == "B3_UNDECIDABLE"
    assert doc["classification"]["unresolved_width_signals"] == ["bus"]
    assert doc["bind_decision"]["mount_layer"] == "requires_human_decision"


def test_width_between_serial_and_parallel_bands_is_undecidable():
    """The 3..7-bit band is deliberately unsplit -- a boundary landing there
    must go to a human rather than being resolved by a guessed threshold."""
    pair = [_mod("p", [("bus", "output", "logic [3:0]")]),
            _mod("c", [("bus", "input", "logic [3:0]")])]
    doc = phy_boundary.extract_phy_boundary(pair, "p", "c")
    assert doc["classification"]["kind"] == "UNDECIDABLE"


def test_missing_module_is_not_available_not_invented():
    doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "nope", "ctrl")
    assert doc["status"] == "NOT_AVAILABLE"
    assert "nope" in doc["reason"]
    assert doc["boundary_signals"] == []
    with pytest.raises(phy_boundary.PhyBoundaryValidationError, match="NOT_EXTRACTED"):
        phy_boundary.assert_bind_location_allowed(doc)


def test_no_rtl_supplied_is_not_available():
    doc = phy_boundary.extract_phy_boundary([], "a", "b")
    assert doc["status"] == "NOT_AVAILABLE"
    assert doc["reason"]


def test_declared_kind_outranks_derived():
    doc = phy_boundary.extract_phy_boundary(SERIAL_PAIR, "aphy", "actrl", declared_kind="PARALLEL")
    assert doc["classification"]["tier"] == "B1_DECLARED"
    assert doc["classification"]["kind"] == "PARALLEL"


def test_direction_opposition_is_recorded():
    doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "phy", "ctrl")
    by_name = {s["name"]: s for s in doc["boundary_signals"]}
    assert by_name["pipe_txdata"]["direction_opposed"] is True
    # A shared input on both sides (a common clock) is not opposed.
    assert by_name["pclk"]["direction_opposed"] is False


def test_env_manifest_shape_is_accepted_directly():
    """extract_phy_boundary must consume env_manifest's dut_facts.rtl.files
    shape without the caller reshaping it."""
    files = [{"file_path": "x.sv", "modules": PARALLEL_PAIR}]
    doc = phy_boundary.extract_phy_boundary(files, "phy", "ctrl")
    assert doc["classification"]["kind"] == "PARALLEL"


def test_extract_from_env_manifest_reports_unparsed_rtl_honestly():
    manifest = {"dut_facts": {"rtl": {"status": "NOT_AVAILABLE",
                                       "reason": "no rtl_files supplied", "files": []}}}
    doc = phy_boundary.extract_from_env_manifest(manifest, "phy", "ctrl")
    assert doc["status"] == "NOT_AVAILABLE"
    assert "NOT_AVAILABLE" in doc["reason"]


def test_save_is_deterministic(tmp_path):
    doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "phy", "ctrl")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    phy_boundary.save_phy_boundary(doc, a)
    phy_boundary.save_phy_boundary(phy_boundary.load_phy_boundary(a), b)
    assert a.read_bytes() == b.read_bytes()


def test_invalid_document_is_rejected():
    with pytest.raises(phy_boundary.PhyBoundaryValidationError):
        phy_boundary.validate_phy_boundary({"schema_version": "1.0"})


# ===========================================================================
# row 2 -- worked example, through the REAL verible parser
# ===========================================================================

def test_worked_example_phy_boundary_matches_committed_artifact():
    """The committed examples/asset_processing/generated/phy_boundary.json
    must still be what the generator produces from the committed RTL port
    table -- otherwise the worked example has rotted away from the code."""
    rtl = json.loads((GENERATED / "rtl_port_table.json").read_text(encoding="utf-8"))
    doc = phy_boundary.extract_phy_boundary(
        rtl["files"], "demo_usb_phy", "demo_usb_controller",
        source={"kind": "verible_parse",
                "files": ["examples/asset_processing/inputs/phy_boundary_demo.sv"]})
    committed = phy_boundary.load_phy_boundary(GENERATED / "phy_boundary.json")
    assert doc == committed
    assert doc["classification"]["kind"] == "PARALLEL"
    assert doc["bind_decision"]["recommended_bind_signals"] == ["pipe_rxdata", "pipe_txdata"]


def test_worked_example_serial_boundary_is_not_bindable():
    committed = phy_boundary.load_phy_boundary(GENERATED / "phy_boundary_serial.json")
    assert committed["classification"]["kind"] == "SERIAL"
    assert committed["bind_decision"]["bindable"] is False


# ===========================================================================
# row 8 -- sys_regmap.py
# ===========================================================================

@pytest.fixture()
def sysmap():
    return sys_regmap.load_sys_regmap(INPUTS / "sys_regmap.json")


def test_worked_example_sys_regmap_validates(sysmap):
    assert sysmap["schema_version"] == "1.0"


def test_absolute_address_computation(sysmap):
    bits = {b["field"]: b for b in sys_regmap.mode_determining_bits(sysmap, "usb0")}
    assert bits["usb0_clk_en"]["absolute_address"] == "0x40000010"
    assert bits["usb0_rst_release"]["absolute_address"] == "0x40000020"
    assert bits["usb0_pad_sel"]["absolute_address"] == "0x40010004"


def test_not_mode_determining_bits_are_excluded(sysmap):
    names = {b["field"] for b in sys_regmap.mode_determining_bits(sysmap, "usb0")}
    assert "revision_id" not in names


def test_unscoped_bit_applies_to_every_interface(sysmap):
    """An unscoped mode bit must apply everywhere. Treating it as irrelevant
    would compute a Gate-2 verdict against an incomplete precondition set."""
    for iface in ("usb0", "some_other_interface"):
        bits = {b["field"]: b for b in sys_regmap.mode_determining_bits(sysmap, iface)}
        assert "global_pad_ie" in bits
        assert bits["global_pad_ie"]["applies_to_all_interfaces"] is True
    # ...but an interface-scoped bit does not leak to other interfaces.
    other = {b["field"] for b in sys_regmap.mode_determining_bits(sysmap, "some_other_interface")}
    assert "usb0_clk_en" not in other


def test_undocumented_required_value_is_unverifiable_not_guessed(sysmap):
    required = {b["field"] for b in sys_regmap.required_preconditions(sysmap, "usb0")}
    unverifiable = {b["field"] for b in sys_regmap.unverifiable_bits(sysmap, "usb0")}
    assert required == {"usb0_clk_en", "usb0_rst_release", "usb0_pad_sel"}
    assert unverifiable == {"global_pad_ie"}
    assert required.isdisjoint(unverifiable)


def test_invalid_sys_regmap_rejected():
    with pytest.raises(sys_regmap.SysRegmapValidationError):
        sys_regmap.validate_sys_regmap({"schema_version": "1.0", "blocks": [
            {"name": "B", "base_address": "not-hex", "kind": "clock_control", "registers": []}]})


def test_unknown_control_kind_rejected():
    with pytest.raises(sys_regmap.SysRegmapValidationError):
        sys_regmap.validate_sys_regmap({"schema_version": "1.0", "blocks": [
            {"name": "B", "base_address": "0x0", "kind": "clock_control", "registers": [
                {"name": "R", "address_offset": "0x0", "width": 32, "access": "RW", "fields": [
                    {"name": "f", "bit_offset": 0, "bit_width": 1, "access": "RW",
                     "control_kind": "invented_kind"}]}]}]})


# ===========================================================================
# row 10 -- init_seq.py
# ===========================================================================

@pytest.fixture()
def seq():
    return init_seq.load_init_seq(INPUTS / "init_seq.yaml")


def test_worked_example_init_seq_validates(seq):
    assert seq["interface"] == "usb0"
    assert [s["index"] for s in seq["steps"]] == [0, 1, 2, 3, 4]
    # The documented order is the artifact's whole point: clock before reset.
    kinds = [(s["index"], s.get("field")) for s in seq["steps"] if s["kind"] == "write"]
    assert kinds[0][1] == "usb0_clk_en"
    assert kinds[1][1] == "usb0_rst_release"


def test_non_contiguous_indices_rejected():
    doc = {"schema_version": "1.0", "interface": "i", "steps": [
        {"index": 0, "kind": "wait_us", "wait_us": 1},
        {"index": 2, "kind": "wait_us", "wait_us": 1}]}
    with pytest.raises(init_seq.InitSeqValidationError, match="contiguous"):
        init_seq.validate_init_seq(doc)


def test_wait_condition_without_timeout_rejected():
    """A poll with no documented timeout is a hang."""
    doc = {"schema_version": "1.0", "interface": "i", "steps": [
        {"index": 0, "kind": "wait_condition", "block": "B", "register": "R", "value": "0x1"}]}
    with pytest.raises(init_seq.InitSeqValidationError, match="timeout_us"):
        init_seq.validate_init_seq(doc)


def test_write_without_value_rejected():
    doc = {"schema_version": "1.0", "interface": "i", "steps": [
        {"index": 0, "kind": "write", "block": "B", "register": "R"}]}
    with pytest.raises(init_seq.InitSeqValidationError, match="value"):
        init_seq.validate_init_seq(doc)


def test_directed_test_steps_resolve_real_addresses(seq, sysmap):
    steps = init_seq.directed_test_steps(seq, sysmap)
    first = steps[0]
    assert first["absolute_address"] == "0x40000010"
    assert first["bit_offset"] == 3 and first["bit_width"] == 1
    # A pure wait step resolves no address, and that is correct, not missing.
    assert steps[1]["kind"] == "wait_us" and steps[1]["absolute_address"] is None


def test_directed_test_rejects_unknown_register(sysmap):
    doc = {"schema_version": "1.0", "interface": "usb0", "steps": [
        {"index": 0, "kind": "write", "block": "CRU", "register": "NO_SUCH_REG", "value": "0x1"}]}
    init_seq.validate_init_seq(doc)
    with pytest.raises(init_seq.InitSeqValidationError, match="does not exist"):
        init_seq.directed_test_steps(doc, sysmap)


def test_directed_test_rejects_unknown_field(sysmap):
    doc = {"schema_version": "1.0", "interface": "usb0", "steps": [
        {"index": 0, "kind": "write", "block": "CRU", "register": "CLK_ENABLE",
         "field": "no_such_field", "value": "0x1"}]}
    with pytest.raises(init_seq.InitSeqValidationError, match="does not define"):
        init_seq.directed_test_steps(doc, sysmap)


# --- the Gate-2 precondition ------------------------------------------------

ALL_PROGRAMMED = {"0x40000010": "0x00000008",   # usb0_clk_en   bit 3 = 1
                  "0x40000020": "0x00000008",   # usb0_rst_release bit 3 = 1
                  "0x40010004": "0x00000002"}   # usb0_pad_sel  bits 1:0 = 0b10
NONE_PROGRAMMED = {"0x40000010": "0x0", "0x40000020": "0x0", "0x40010004": "0x0"}


def test_preconditions_pass_when_all_bits_programmed(sysmap, seq):
    res = init_seq.evaluate_gate2_preconditions(sysmap, "usb0", ALL_PROGRAMMED, seq)
    assert res.status is GateStatus.PASS
    assert res.detail["violations"] == []
    # The unverifiable bit is still surfaced, never silently dropped.
    assert res.detail["unverifiable_bits"] == ["PINMUX.PAD_SEL0.global_pad_ie"]


def test_preconditions_fail_names_the_offending_bits(sysmap):
    res = init_seq.evaluate_gate2_preconditions(sysmap, "usb0", NONE_PROGRAMMED)
    assert res.status is GateStatus.FAIL
    names = {v["name"] for v in res.detail["violations"]}
    assert names == {"CRU.CLK_ENABLE.usb0_clk_en", "CRU.RESET_CTRL.usb0_rst_release",
                     "PINMUX.PAD_SEL0.usb0_pad_sel"}
    kinds = {v["control_kind"] for v in res.detail["violations"]}
    assert kinds == {"clock_enable", "reset_release", "pinmux_select"}


def test_multibit_field_is_extracted_correctly(sysmap):
    """usb0_pad_sel is a 2-bit field requiring 0b10. A 0b01 must FAIL -- a
    naive non-zero test would wrongly pass it."""
    obs = dict(ALL_PROGRAMMED, **{"0x40010004": "0x00000001"})
    res = init_seq.evaluate_gate2_preconditions(sysmap, "usb0", obs)
    assert res.status is GateStatus.FAIL
    viol = [v for v in res.detail["violations"] if v["name"].endswith("usb0_pad_sel")][0]
    assert viol["observed_value"] == "0x1" and viol["required_value"] == "0x2"


def test_preconditions_not_available_without_observed_values(sysmap):
    res = init_seq.evaluate_gate2_preconditions(sysmap, "usb0")
    assert res.status is GateStatus.NOT_AVAILABLE
    assert res.detail["required_bits"]
    assert "instructions" in res.detail


def test_partial_observation_claims_no_verdict(sysmap):
    res = init_seq.evaluate_gate2_preconditions(sysmap, "usb0", {"0x40000010": "0x8"})
    assert res.status is GateStatus.NOT_AVAILABLE
    assert len(res.detail["unread_bits"]) == 2


def test_nothing_verifiable_is_pending_not_pass():
    """'We checked nothing' must never report the same status as 'we checked
    everything and it was fine'."""
    doc = {"schema_version": "1.0", "blocks": [
        {"name": "B", "base_address": "0x0", "kind": "clock_control", "registers": [
            {"name": "R", "address_offset": "0x0", "width": 32, "access": "RW", "fields": [
                {"name": "f", "bit_offset": 0, "bit_width": 1, "access": "RW",
                 "control_kind": "clock_enable", "required_value": None,
                 "governs_interfaces": ["usb0"]}]}]}]}
    res = init_seq.evaluate_gate2_preconditions(doc, "usb0", {"0x0": "0x0"})
    assert res.status is GateStatus.PENDING


def _dead_clock_trace():
    return SignalTrace(samples={"clk": [(0, "0"), (1, "0")],
                                "rst_n": [(0, "0"), (1, "1")],
                                "dat": [(0, "0")]})


def _healthy_trace():
    return SignalTrace(samples={"clk": [(0, "0"), (1, "1"), (2, "0")],
                                "rst_n": [(0, "0"), (1, "1")],
                                "dat": [(0, "0")]})


def test_gated_interpretation_precondition_not_met(sysmap, seq):
    """The payoff: a dead clock with the clock-enable bit never written is a
    BRING-UP defect, and must not send a debugger after the bind."""
    out = init_seq.evaluate_zero_time_connectivity_gated(
        _dead_clock_trace(), "clk", "rst_n", ["dat"],
        sys_regmap_doc=sysmap, interface="usb0",
        observed_register_values=NONE_PROGRAMMED, init_seq_doc=seq)
    assert out["gate2"].status is GateStatus.FAIL
    assert out["preconditions"].status is GateStatus.FAIL
    assert out["interpretation"] == "PRECONDITION_NOT_MET"


def test_gated_interpretation_connectivity_failure(sysmap, seq):
    """The SAME dead clock, with every mode bit correctly programmed, IS a
    genuine connectivity failure."""
    out = init_seq.evaluate_zero_time_connectivity_gated(
        _dead_clock_trace(), "clk", "rst_n", ["dat"],
        sys_regmap_doc=sysmap, interface="usb0",
        observed_register_values=ALL_PROGRAMMED, init_seq_doc=seq)
    assert out["gate2"].status is GateStatus.FAIL
    assert out["preconditions"].status is GateStatus.PASS
    assert out["interpretation"] == "CONNECTIVITY_FAILURE"


def test_gated_interpretation_indeterminate_without_observations(sysmap):
    out = init_seq.evaluate_zero_time_connectivity_gated(
        _dead_clock_trace(), "clk", "rst_n", ["dat"],
        sys_regmap_doc=sysmap, interface="usb0")
    assert out["interpretation"] == "INDETERMINATE"


def test_gated_interpretation_ok_when_gate2_passes(sysmap):
    out = init_seq.evaluate_zero_time_connectivity_gated(
        _healthy_trace(), "clk", "rst_n", ["dat"],
        sys_regmap_doc=sysmap, interface="usb0",
        observed_register_values=ALL_PROGRAMMED)
    assert out["gate2"].status is GateStatus.PASS
    assert out["interpretation"] == "CONNECTIVITY_OK"


def test_gate_result_uses_the_real_connectivity_enum(sysmap):
    """The precondition must reuse connectivity.py's GateStatus rather than
    introducing a parallel status vocabulary."""
    res = init_seq.evaluate_gate2_preconditions(sysmap, "usb0", ALL_PROGRAMMED)
    assert isinstance(res.status, GateStatus)
    assert res.gate == "gate2_preconditions_mode_bits"


# ===========================================================================
# rows 12 and 13 -- vip_symbol_index.py
# ===========================================================================

@pytest.fixture()
def index():
    return vip_symbol_index.build_symbol_index(
        [INPUTS / "vip_src"], "demo", relative_to=INPUTS)


def test_index_finds_real_classes_and_inheritance(index):
    by_name = {c["name"]: c for c in index["classes"]}
    assert set(by_name) == {"svt_demo_cfg", "svt_demo_transaction", "svt_demo_base_sequence",
                            "svt_demo_driver", "svt_demo_monitor", "svt_demo_agent"}
    assert by_name["svt_demo_cfg"]["base_class"] == "uvm_object"
    assert by_name["svt_demo_driver"]["is_virtual"] is True
    assert by_name["svt_demo_cfg"]["is_virtual"] is False


def test_index_records_config_fields_with_locations(index):
    cfg = next(c for c in index["classes"] if c["name"] == "svt_demo_cfg")
    fields = {f["name"]: f for f in cfg["config_fields"]}
    assert set(fields) == {"enable_protocol_checks", "max_burst_length",
                           "coverage_enable", "interface_name"}
    assert fields["enable_protocol_checks"]["is_rand"] is True
    assert fields["coverage_enable"]["is_rand"] is False
    assert fields["interface_name"]["data_type"] == "string"
    for f in fields.values():
        assert f["line"] > 0 and f["file"].endswith("svt_demo_pkg.sv")


def test_index_records_method_signatures(index):
    cfg = next(c for c in index["classes"] if c["name"] == "svt_demo_cfg")
    methods = {m["name"]: m for m in cfg["methods"]}
    assert methods["apply_preset"]["kind"] == "function"
    assert methods["wait_for_ready"]["kind"] == "task"
    assert methods["wait_for_ready"]["arguments"] == "(input int timeout_ns)"
    assert methods["set_defaults"]["is_extern"] is True


def test_index_retains_no_method_bodies(index):
    """The row-13 invariant. The fixture's bodies contain `$display`,
    `begin`, `if (` and a `while` loop; none may appear anywhere in the
    index, or a tier-1-denied VIP source would be smuggled into context
    inside a tier-3-shaped artifact."""
    vip_symbol_index.assert_no_bodies_retained(index)
    blob = json.dumps(index)
    for token in ("$display", "$sformatf", "uvm_do", "raise_objection",
                  "get_next_item", "posedge", "begin"):
        assert token not in blob, f"index leaked implementation text: {token!r}"


def test_body_leak_is_detected():
    """assert_no_bodies_retained must actually fire -- a check that can never
    fail proves nothing."""
    bad = {"schema_version": "1.0",
           "generator": {"tool": "t", "version": "1.0"}, "protocol": "p", "roots": [],
           "stats": {"files_scanned": 0, "classes_indexed": 0, "methods_indexed": 0,
                     "bytes_scanned": 0},
           "classes": [{"name": "C", "file": "f.sv", "line": 1, "config_fields": [],
                        "methods": [{"name": "m", "kind": "task", "file": "f.sv", "line": 2,
                                     "arguments": "(); begin $display(\"x\"); end"}]}]}
    with pytest.raises(vip_symbol_index.VipSymbolIndexError, match="BODY_LEAK"):
        vip_symbol_index.assert_no_bodies_retained(bad)


def test_find_symbol_returns_targeted_read_locations(index):
    hits = vip_symbol_index.find_symbol(index, "wait_for_ready")
    assert len(hits) == 1
    assert hits[0]["kind"] == "task"
    assert hits[0]["name"] == "svt_demo_cfg.wait_for_ready"
    assert hits[0]["line"] > 0
    assert vip_symbol_index.find_symbol(index, "no_such_symbol_anywhere") == []


def test_find_symbol_matches_classes_and_fields(index):
    assert any(h["kind"] == "class" for h in vip_symbol_index.find_symbol(index, "monitor"))
    assert any(h["kind"] == "field" for h in vip_symbol_index.find_symbol(index, "max_burst"))


def test_constructor_is_not_indexed_as_a_method(index):
    for cls in index["classes"]:
        assert "new" not in {m["name"] for m in cls["methods"]}


def test_missing_root_raises_rather_than_indexing_nothing():
    with pytest.raises(vip_symbol_index.VipSymbolIndexError, match="does not exist"):
        vip_symbol_index.build_symbol_index(["/no/such/vip/root"], "demo")


def test_index_is_deterministic(tmp_path):
    a = vip_symbol_index.build_symbol_index([INPUTS / "vip_src"], "demo", relative_to=INPUTS)
    b = vip_symbol_index.build_symbol_index([INPUTS / "vip_src"], "demo", relative_to=INPUTS)
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    vip_symbol_index.save_symbol_index(a, pa)
    vip_symbol_index.save_symbol_index(b, pb)
    assert pa.read_bytes() == pb.read_bytes()


def test_vip_ref_markdown_is_generated_from_real_index(index):
    md = vip_symbol_index.render_vip_ref_markdown(index)
    assert "# VIP Reference -- demo" in md
    assert "svt_demo_cfg" in md and "enable_protocol_checks" in md
    # Locations must be present so a targeted read is possible.
    assert "svt_demo_pkg.sv:" in md
    # The honest-limits section must survive edits -- it is what stops this
    # inventory being read as a behavioural specification.
    assert "does NOT carry SEMANTICS" in md
    for token in ("$display", "$sformatf", "posedge"):
        assert token not in md


def test_worked_example_vip_ref_matches_committed(index):
    committed = (GENERATED / "vip_ref" / "demo.md").read_text(encoding="utf-8")
    assert vip_symbol_index.render_vip_ref_markdown(index) == committed


def test_write_vip_ref_uses_the_documented_tier3_path(index, tmp_path):
    path = vip_symbol_index.write_vip_ref(index, tmp_path)
    assert path == tmp_path / "vip_ref" / "demo.md"
    assert path.is_file()


# ===========================================================================
# rows 9 and 11 -- design_intent.py
# ===========================================================================

@pytest.fixture()
def intent():
    return design_intent.load_intent(INPUTS / "dut_intent.yaml")


@pytest.fixture()
def constraints():
    return design_intent.load_constraints(INPUTS / "constraints.yaml")


def test_worked_example_intent_validates(intent):
    assert intent["dut_name"] == "demo_usb_controller"
    assert {m["name"] for m in intent["modes"]} == {"high_speed", "low_power"}


def test_transition_to_undeclared_state_rejected(intent):
    broken = json.loads(json.dumps(intent))
    broken["state_machine"]["transitions"][0]["to"] = "GHOST_STATE"
    with pytest.raises(design_intent.DesignIntentValidationError, match="not a declared state"):
        design_intent.validate_intent(broken)


def test_uncited_drop_condition_cannot_validate(intent):
    """An uncited legal-drop condition is indistinguishable from an invented
    one, and an invented one silently licenses a real dropped packet."""
    broken = json.loads(json.dumps(intent))
    del broken["legal_drop_conditions"][0]["basis"]
    with pytest.raises(design_intent.DesignIntentValidationError):
        design_intent.validate_intent(broken)


def test_scoreboard_compare_mode_from_documented_rules(intent):
    assert design_intent.scoreboard_compare_mode(intent, "per endpoint")["mode"] == "strict_in_order"
    assert design_intent.scoreboard_compare_mode(intent, "across endpoints")["mode"] == "unordered"


def test_undocumented_scope_defaults_to_the_stricter_comparison(intent):
    """Relaxing a comparison on an undocumented guarantee would silently
    accept a genuine reordering defect."""
    res = design_intent.scoreboard_compare_mode(intent, "per virtual channel")
    assert res["mode"] == "UNKNOWN"
    assert res["safe_default"] == "strict_in_order"
    assert res["basis"] is None


def test_legal_drop_conditions_are_mode_scoped(intent):
    assert design_intent.is_drop_legal(intent, "DROP-001") is True          # any mode
    assert design_intent.is_drop_legal(intent, "DROP-002", mode="low_power") is True
    assert design_intent.is_drop_legal(intent, "DROP-002", mode="high_speed") is False
    assert design_intent.is_drop_legal(intent, "DROP-NONEXISTENT") is False


def test_backpressure_conditions_are_separate_from_drops(intent):
    bp_ids = {c["id"] for c in design_intent.backpressure_conditions(intent)}
    drop_ids = {c["id"] for c in design_intent.legal_drop_conditions(intent)}
    assert bp_ids == {"BP-001"}
    assert bp_ids.isdisjoint(drop_ids)


def test_constraint_bound_without_unit_rejected(constraints):
    broken = json.loads(json.dumps(constraints))
    broken["timing_constraints"][0]["unit"] = None
    with pytest.raises(design_intent.DesignIntentValidationError, match="unit"):
        design_intent.validate_constraints(broken)


def test_impossible_review_date_rejected(constraints):
    """`format: date` is inert without a FormatChecker; this pins that it is
    actually attached."""
    broken = json.loads(json.dumps(constraints))
    broken["untestable_items"][0]["valid_until"] = "2026-02-30"
    with pytest.raises(design_intent.DesignIntentValidationError):
        design_intent.validate_constraints(broken)


def test_untestable_items_become_exemption_records(constraints):
    entries = design_intent.untestable_items_as_exemptions(constraints)
    assert len(entries) == 3
    for e in entries:
        assert set(e) == {"id", "check_id", "reason", "basis_document", "owner", "valid_until"}
        assert e["basis_document"] and e["owner"] and e["valid_until"]
    first = entries[0]
    assert first["check_id"] == "chk_tx_diff_swing_within_limits"
    assert "analog_no_digital_observable" in first["reason"]
    assert "DEMO IP User Guide" in first["basis_document"]


def test_exemptions_bridge_writes_through_the_real_store(constraints, tmp_path):
    """The bridge must go through exemptions.py's own validating entry point,
    so an untestable item lands in the same expiring, owned list every other
    exemption uses -- not a parallel store."""
    from dv_harness import exemptions

    path = tmp_path / "exemptions.yaml"
    added = design_intent.write_exemptions_from_constraints(constraints, path)
    assert len(added) == 3
    stored = {e["id"] for e in exemptions.list_exemptions(path)}
    assert stored == {"EXEMPT-DEMO-001", "EXEMPT-DEMO-002", "EXEMPT-DEMO-003"}
    # Re-running must be idempotent, never duplicating an exemption.
    assert design_intent.write_exemptions_from_constraints(constraints, path) == []
    assert len(exemptions.list_exemptions(path)) == 3


def test_rendered_intent_matches_committed(intent):
    committed = (GENERATED / "docs" / "intent.md").read_text(encoding="utf-8")
    assert design_intent.render_intent_markdown(intent) == committed


def test_rendered_constraints_matches_committed(constraints):
    committed = (GENERATED / "docs" / "constraints.md").read_text(encoding="utf-8")
    assert design_intent.render_constraints_markdown(constraints) == committed


def test_rendered_markdown_carries_citations(intent, constraints):
    imd = design_intent.render_intent_markdown(intent)
    cmd = design_intent.render_constraints_markdown(constraints)
    assert "DEMO Controller Databook" in imd
    assert "DROP-001" in imd and "BP-001" in imd
    assert "DEMO IP User Guide" in cmd
    assert "EXEMPT-DEMO-001" in cmd
    for md in (imd, cmd):
        assert "GENERATED by `dv_harness/design_intent.py`" in md
