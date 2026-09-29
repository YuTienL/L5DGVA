"""Tests for SYOSCB-17 (compare strategy) and SYOSCB-18 (AXI matching must not
be raw object compare) -- `dv_harness/syoscb_compare_policy.py`.

Four kinds of fixture, and every one of them real where a real one exists:

  * The REAL master-prompt document, so every `doc_line` in the policy table
    and every match-key axis is held against the line it claims to transcribe.
    A table that drifted from the requirement it encodes is worse than no
    table, because it looks authoritative.
  * The REAL upstream uvm_syoscb-1.0.2.4 tree at D:/DV/Scoreboard, read
    READ-ONLY, to prove the three orderings resolve to three real classes, to
    prove the cited compare/item lines really say what the module claims, and
    to prove the "no compare-selector field in cl_syoscb_cfg" claim from the
    other direction. Nothing is copied out of it.
  * SYNTHETIC AMBA_PORT_REGISTRY rows, reusing `test_amba_route_transform_
    predictor`'s own `master()`/`slave()` helpers, for the topologies the real
    fixture cannot produce: a multi-master AHB group, a mixed-protocol group,
    two APB masters with no id.
  * The REAL parsed AMBA4 SoC fixture carried through a real registry, real
    predictions and a real SyoSil plan.

Every decision is tested on BOTH sides -- what it decides, and what it refuses
to decide when the evidence is missing. The AHB-with-unknown-master-count
case, the no-prediction ordering-domain axis, the ACE-Lite coherency axis with
no IR field, and the mixed-protocol group are all here for that reason.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dv_harness import syoscb_compare_policy as cp
from dv_harness.amba_fabric_discovery import (
    assert_no_bind_statement,
    build_fabric_netlist,
    build_vip_bind_plan,
    trace_all_fabric_ports,
)
from dv_harness.amba_port_registry import build_amba_port_registry
from dv_harness.amba_route_transform_predictor import (
    ORDERING_DOMAIN_PER_ROUTE,
    ORDERING_DOMAIN_PER_ROUTE_AND_ID,
    ROUTE_RESPONSIBILITIES,
    predict_routes,
)
from dv_harness.amba_transaction_ir import AMBA_TRANSACTION_IR_FIELDS
from dv_harness.connectivity import (
    ACE_LITE_COHERENCY_SIGNALS,
    AMBA4_PROTOCOLS,
    AMBA_PROTOCOL_UNRESOLVED,
    REQUIRED_HUMAN_INPUT,
    SCOREBOARD_PLAN_FIELDS,
)
from dv_harness.syoscb_compare_policy import (
    AXIS_APPLICABLE,
    AXIS_NO_IR_FIELD,
    AXIS_NOT_APPLICABLE,
    AXIS_PROTOCOL_UNRESOLVED,
    AXIS_REQUIRED_HUMAN_INPUT,
    COMPARE_CLASS_AUDIT_NOT_SUPPLIED,
    COMPARE_POLICY_INFORMED_PLAN_FIELDS,
    COMPARE_SELECTION_MECHANISM,
    GROUP_MIXED_PROTOCOL,
    MATCH_KEY_AXES,
    MATCH_KEY_AXIS_SPEC,
    POLICY_DOC,
    POLICY_FROM_PROTOCOL_TABLE,
    POLICY_MASTER_COUNT_DECIDES,
    POLICY_PROTOCOL_UNRESOLVED,
    POLICY_REFINED_BY_TOPOLOGY,
    PROTOCOL_COMPARE_POLICY,
    SYOSCB18_MATCH_KEY_AXES,
    CompareStrategyError,
    assert_not_raw_object_compare,
    assert_plan_proposals_are_not_confirmations,
    assert_policy_required_axes_present,
    assert_policy_table_resolves_to_real_classes,
    build_match_key_schema,
    propose_scoreboard_plan_fields,
    render_compare_policy_report,
    render_compare_strategy_table,
    render_match_key_table,
    render_protocol_policy_table,
    resolve_compare_policy,
    resolve_plan_compare_strategies,
    unresolved_compare_strategies,
    unresolved_match_key_axes,
)
from dv_harness.syoscb_source_audit import (
    ORDERING_IN_ORDER,
    ORDERING_IN_ORDER_PER_PRODUCER,
    ORDERING_OUT_OF_ORDER,
    ORDERING_VALUES,
    assert_no_emittable_sv,
    audit_syoscb_source,
)
from dv_harness.syoscb_topology_plan import (
    COMPARE_STRATEGY_DEFERRED,
    build_syoscb_configuration_plan,
)
from dv_harness.verible_parser import parse_file
from dv_harness_tests.test_amba_route_transform_predictor import master, slave
from dv_harness_tests.test_amba_vip_bind_plan import FABRIC, write_fixture

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

REAL_SYOSCB_ROOT = Path("D:/DV/Scoreboard/uvm_syoscb-1.0.2.4")
real_source = pytest.mark.skipif(
    not REAL_SYOSCB_ROOT.is_dir(),
    reason=f"the real uvm_syoscb source tree is not present at {REAL_SYOSCB_ROOT}",
)

REAL_DOC = Path(__file__).resolve().parents[2] / POLICY_DOC
real_doc = pytest.mark.skipif(
    not REAL_DOC.is_file(),
    reason=f"the master prompt is not present at {REAL_DOC}")

MODULE_SOURCE = Path(cp.__file__).read_text(encoding="utf-8")


def _doc_line(number: int) -> str:
    return REAL_DOC.read_text(encoding="utf-8").splitlines()[number - 1].strip()


def plan_from(rows, **kwargs):
    """Registry rows -> real predictions -> a real SyoSil plan, nothing faked."""
    destination_classes = kwargs.pop("destination_classes", None)
    predictions = predict_routes(rows, **{"assume_full_connectivity": True, **kwargs})
    return build_syoscb_configuration_plan(
        rows, predictions, destination_classes=destination_classes)


@pytest.fixture
def three_axi_masters_one_ddr():
    return [master("CPU_AXI", "AXI4"), master("DMA_AXI", "AXI4", id_width="6"),
            master("GPU_AXI", "AXI4", id_width="5"), slave("DDR_AXI", "AXI4", id_width="8")]


@pytest.fixture
def two_ahb_masters_one_slave():
    """Full AHB (HMASTER-capable), two masters into one destination -- the
    topology SYOSCB-17's "producer-aware where necessary" is about."""
    return [master("CPU_AHB", "AHB", clock="HCLK", reset="HRESETN", id_width="UNKNOWN"),
            master("DMA_AHB", "AHB", clock="HCLK", reset="HRESETN", id_width="UNKNOWN"),
            slave("MEM_AHB", "AHB", clock="HCLK", reset="HRESETN", id_width="UNKNOWN")]


@pytest.fixture
def one_ahb_master_one_slave():
    return [master("CPU_AHB", "AHB", clock="HCLK", reset="HRESETN", id_width="UNKNOWN"),
            slave("MEM_AHB", "AHB", clock="HCLK", reset="HRESETN", id_width="UNKNOWN")]


@pytest.fixture
def mixed_protocol_masters_one_slave():
    """An AHB-Lite master and an APB4 master into ONE destination. Neither
    carries a transaction id, so both routes land in the same PER_ROUTE
    ordering domain and therefore in the same scoreboard group -- two starting
    policies, one group."""
    return [master("CPU_AHB", "AHB_LITE", clock="HCLK", reset="HRESETN", id_width="UNKNOWN"),
            master("HOST_APB", "APB4", clock="PCLK", reset="PRESETN", id_width="UNKNOWN"),
            slave("CFG_APB", "APB4", clock="PCLK", reset="PRESETN", id_width="UNKNOWN")]


def _axi_prediction():
    """One real SYOSCB-12 prediction for an AXI4 -> AXI4 route."""
    rows = [master("CPU_AXI", "AXI4"), slave("DDR_AXI", "AXI4", id_width="8")]
    return predict_routes(rows, assume_full_connectivity=True)[0]


# ===========================================================================
# The table is a transcription -- held against the document it transcribes
# ===========================================================================

def test_the_policy_table_covers_every_amba4_protocol_and_invents_none():
    assert set(PROTOCOL_COMPARE_POLICY) == set(AMBA4_PROTOCOLS)
    for protocol, entry in PROTOCOL_COMPARE_POLICY.items():
        assert (entry["starting_ordering"] in ORDERING_VALUES
                or entry["starting_ordering"] == POLICY_MASTER_COUNT_DECIDES), protocol


@real_doc
def test_every_policy_line_really_says_what_the_table_claims():
    """SYOSCB-17's protocol starting policy list, held against the real
    document line by line. A table that drifted from its requirement looks
    authoritative while being wrong, which is worse than having no table."""
    for protocol, entry in PROTOCOL_COMPARE_POLICY.items():
        line = _doc_line(entry["doc_line"])
        assert entry["doc_policy"] in line, (protocol, entry["doc_line"], line)
        label = _doc_line(entry["doc_line"] - 1)
        assert entry["doc_label"] == label, (protocol, label)


@real_doc
def test_the_match_key_axes_are_the_documents_own_six_in_the_documents_order():
    """SYOSCB-18 lines 4998-5003. The seventh axis (ACE-Lite coherency) comes
    from SYOSCB-17 and is labelled as such, so a reader can tell which axes the
    match-key requirement itself names."""
    for axis in SYOSCB18_MATCH_KEY_AXES:
        spec = MATCH_KEY_AXIS_SPEC[axis]
        assert spec["doc_source"] == "SYOSCB-18"
        assert _doc_line(spec["doc_line"]) == spec["doc_term"], axis
    lines = [MATCH_KEY_AXIS_SPEC[a]["doc_line"] for a in SYOSCB18_MATCH_KEY_AXES]
    assert lines == sorted(lines), "the axes must be in the document's own order"
    assert MATCH_KEY_AXIS_SPEC["coherency_attributes"]["doc_source"] == "SYOSCB-17 (ACE-Lite)"


def test_every_axis_is_backed_by_real_ir_fields_and_real_responsibilities():
    for axis, spec in MATCH_KEY_AXIS_SPEC.items():
        assert set(spec["ir_fields"]) <= set(AMBA_TRANSACTION_IR_FIELDS), axis
        assert set(spec["normalized_by"]) <= set(ROUTE_RESPONSIBILITIES), axis


def test_the_table_names_no_upstream_class_of_its_own():
    """SYOSCB-17: "Use actual class/config names from source." No policy value
    is an upstream class name -- the class is resolved at call time from a real
    read-only audit, so a renamed or absent class surfaces there rather than
    being frozen into a table."""
    for protocol, entry in PROTOCOL_COMPARE_POLICY.items():
        blob = repr(entry)
        assert "cl_syoscb" not in blob, (protocol, "a class name leaked into the policy table")


def test_the_module_carries_no_upstream_source_body():
    """SYOSCB-2 / SYOSCB-33: this module CITES the upstream tree, it does not
    absorb it. A copied method body would be vendoring by another name."""
    for token in ("endfunction", "endclass", "`uvm_info", "`uvm_fatal", "function bit"):
        assert token not in MODULE_SOURCE, f"upstream source body leaked: {token}"


# ===========================================================================
# The three orderings resolve to three REAL classes, read from the real tree
# ===========================================================================

@real_source
def test_the_policy_tables_orderings_all_resolve_to_real_upstream_classes():
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    assert_policy_table_resolves_to_real_classes(audit)
    names = {o: audit.compare_algorithms[o]["class"] for o in ORDERING_VALUES}
    assert names == {ORDERING_IN_ORDER: "cl_syoscb_compare_io",
                     ORDERING_IN_ORDER_PER_PRODUCER: "cl_syoscb_compare_iop",
                     ORDERING_OUT_OF_ORDER: "cl_syoscb_compare_ooo"}


@real_source
def test_a_resolution_carries_the_real_class_when_an_audit_is_supplied():
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    policy = resolve_compare_policy("AXI4", master_count=1, audit=audit)
    assert policy["ordering"] == ORDERING_OUT_OF_ORDER
    assert policy["compare_class"]["class"] == "cl_syoscb_compare_ooo"
    assert policy["compare_class"]["file"].endswith("cl_syoscb_compare_ooo.svh")


def test_without_an_audit_no_class_is_invented():
    """The negative half of "use actual class names from source": with no
    source read, the answer is a sentinel, never a remembered class name."""
    policy = resolve_compare_policy("APB4")
    assert policy["compare_class"]["class"] == COMPARE_CLASS_AUDIT_NOT_SUPPLIED


def test_an_ordering_the_tree_does_not_implement_is_refused_not_substituted():
    """A tree carrying only in-order and in-order-per-producer must fail the
    table check, not silently compare an out-of-order stream in order."""

    class _PartialAudit:
        root = "synthetic-partial-tree"
        compare_algorithms = {
            ORDERING_IN_ORDER: {"class": "cl_syoscb_compare_io", "file": "x.svh",
                                "line": 20, "base_class": "cl_syoscb_compare_base",
                                "tier": "T1"},
            ORDERING_IN_ORDER_PER_PRODUCER: {"class": "cl_syoscb_compare_iop",
                                             "file": "y.svh", "line": 20,
                                             "base_class": "cl_syoscb_compare_base",
                                             "tier": "T1"},
        }

    with pytest.raises(CompareStrategyError) as excinfo:
        assert_policy_table_resolves_to_real_classes(_PartialAudit())
    assert excinfo.value.reason == "COMPARE_POLICY_ORDERING_NOT_IMPLEMENTED_UPSTREAM"
    assert [o["ordering"] for o in excinfo.value.detail["orderings"]] == [ORDERING_OUT_OF_ORDER]


@real_source
def test_the_cited_compare_lines_really_say_what_the_module_claims():
    """Every `file:line` in `RAW_OBJECT_COMPARE_CITATIONS` and in the module's
    cautions, read from the real tree read-only."""
    src = REAL_SYOSCB_ROOT / "src"
    expected = {
        ("cl_syoscb_compare_io.svh", 117): "sih.compare(primary_item)",
        ("cl_syoscb_compare_iop.svh", 119): "get_producer",
        ("cl_syoscb_compare_iop.svh", 120): "sih.compare(primary_item)",
        ("cl_syoscb_compare_ooo.svh", 118): "sih.compare(primary_item)",
        ("cl_syoscb_item.svh", 44): "uvm_field_object(item",
    }
    for (name, number), token in expected.items():
        line = (src / name).read_text(encoding="utf-8",
                                      errors="replace").splitlines()[number - 1]
        assert token in line, (name, number, line)


@real_source
def test_the_config_object_really_carries_no_compare_selector_field():
    """`COMPARE_SELECTION_MECHANISM` claims selection is a UVM factory type
    override and NOT a cfg knob. That is a claim about the real source, so it
    is checked against the real source -- a Phase-2 plan that configured a
    selector would be planning a knob the library does not have."""
    assert COMPARE_SELECTION_MECHANISM["config_selector_field"] is None
    for name in ("cl_syoscb_cfg.svh", "cl_syoscb_cfg_pl.svh"):
        text = (REAL_SYOSCB_ROOT / "src" / name).read_text(
            encoding="utf-8", errors="replace").lower()
        for token in ("compare_algo", "set_compare_algo", "compare_strategy",
                      "compare_type"):
            assert token not in text, (name, token)
    compare = (REAL_SYOSCB_ROOT / "src" / "cl_syoscb_compare.svh").read_text(
        encoding="utf-8", errors="replace").splitlines()
    assert "cl_syoscb_compare_base::type_id::create" in compare[64]
    cfg = (REAL_SYOSCB_ROOT / "src" / "cl_syoscb_cfg.svh").read_text(
        encoding="utf-8", errors="replace")
    assert "primary_queue" in cfg, "the one real per-scoreboard compare-loop knob"


# ===========================================================================
# SYOSCB-17: resolving a starting policy, and refusing to
# ===========================================================================

@pytest.mark.parametrize("protocol", ["APB", "APB3", "APB4", "AHB_LITE"])
def test_the_in_order_protocols_start_in_order(protocol):
    policy = resolve_compare_policy(protocol)
    assert policy["ordering"] == ORDERING_IN_ORDER
    assert policy["status"] == POLICY_FROM_PROTOCOL_TABLE
    assert policy["evidence"], "a starting policy must state what it was decided from"


@pytest.mark.parametrize("protocol", ["AXI3", "AXI4", "ACE_LITE"])
def test_the_id_bearing_protocols_start_out_of_order(protocol):
    assert resolve_compare_policy(protocol)["ordering"] == ORDERING_OUT_OF_ORDER


def test_axi4_stream_starts_in_order_per_producer_because_streams_interleave():
    policy = resolve_compare_policy("AXI4_STREAM")
    assert policy["ordering"] == ORDERING_IN_ORDER_PER_PRODUCER
    assert "TID" in policy["evidence"][1] or "stream" in policy["evidence"][1]


def test_full_ahb_with_an_unknown_master_count_is_required_human_input():
    """The honest missing-evidence case. AHB's fingerprint carries HMASTER, so
    the bus MAY be multi-master, and "producer-aware where necessary" turns on
    a master count nobody established. Neither default is free, so neither is
    taken."""
    policy = resolve_compare_policy("AHB")
    assert policy["ordering"] == REQUIRED_HUMAN_INPUT
    assert policy["status"] == REQUIRED_HUMAN_INPUT
    assert policy["starting_ordering"] == POLICY_MASTER_COUNT_DECIDES
    assert any("HMASTER" in e for e in policy["evidence"])
    assert any("false-FAIL" in e for e in policy["evidence"])
    assert policy["compare_class"]["class"] == REQUIRED_HUMAN_INPUT


def test_full_ahb_with_a_real_master_count_resolves_both_ways():
    single = resolve_compare_policy("AHB", master_count=1)
    assert single["ordering"] == ORDERING_IN_ORDER
    assert single["status"] == POLICY_REFINED_BY_TOPOLOGY
    multi = resolve_compare_policy("AHB", master_count=3)
    assert multi["ordering"] == ORDERING_IN_ORDER_PER_PRODUCER
    assert multi["status"] == POLICY_REFINED_BY_TOPOLOGY
    assert any("3 masters" in e for e in multi["evidence"])


def test_a_route_the_predictor_calls_out_of_order_outranks_an_in_order_default():
    """SYOSCB-17's starting policy is a STARTING point. Real routing evidence
    that the route completes out of order escalates it, because an in-order
    compare on such a route raises COMPARE_ERROR on correct traffic."""
    policy = resolve_compare_policy(
        "AXI4_LITE", master_count=1, route_ordering_expectation=ORDERING_OUT_OF_ORDER)
    assert policy["starting_ordering"] == ORDERING_IN_ORDER
    assert policy["ordering"] == ORDERING_OUT_OF_ORDER
    assert policy["status"] == POLICY_REFINED_BY_TOPOLOGY
    assert any("outranks" in e for e in policy["evidence"])


def test_an_out_of_order_policy_with_several_masters_carries_the_ooo_producer_caution():
    """`cl_syoscb_compare_ooo` has no producer filter, unlike `_iop`. With more
    than one master that is a real limitation the match key must cover, so it
    is reported rather than left for Phase-2 to discover."""
    policy = resolve_compare_policy("AXI4", master_count=3)
    assert any("no producer filter" in c.lower() for c in policy["cautions"])


def test_an_in_order_policy_with_several_masters_carries_its_own_caution():
    policy = resolve_compare_policy("APB4", master_count=2)
    assert policy["ordering"] == ORDERING_IN_ORDER
    assert any("more than one producer" in c for c in policy["cautions"])


def test_an_unresolved_protocol_is_a_discovery_gap_not_a_policy_question():
    """Kept distinct from REQUIRED_HUMAN_INPUT on purpose: nobody is being
    asked about compare strategy, the protocol classification never landed."""
    policy = resolve_compare_policy(AMBA_PROTOCOL_UNRESOLVED)
    assert policy["status"] == POLICY_PROTOCOL_UNRESOLVED
    assert policy["ordering"] is None
    assert policy["doc_citation"] is None
    assert policy["evidence"]


def test_no_resolution_ever_marks_itself_confirmed():
    """SYOSCB-17 ends with "Validate every policy against the actual DUT/fabric
    behavior" -- so a table entry is a starting point, never an answer."""
    for protocol in AMBA4_PROTOCOLS:
        policy = resolve_compare_policy(protocol, master_count=2)
        assert policy["confirmed"] is False
        assert "Validate every policy" in policy["validation_question"]


# ===========================================================================
# SYOSCB-18: the composite match key
# ===========================================================================

def test_the_axi_key_is_composite_not_one_field():
    """The whole point of SYOSCB-18 against `connectivity.SCOREBOARD_FIELD_
    QUESTIONS["matching_key"]`, whose three canned options each name ONE
    field."""
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    included = schema["included_axes"]
    assert {"route", "master", "transaction_id", "read_write_domain",
            "ordering_domain", "sequence_burst"} <= set(included)
    assert schema["axes"]["transaction_id"]["ir_fields_available"] == [
        "transaction_id", "original_id", "fabric_id"]


def test_a_protocol_with_no_id_reports_the_id_axis_not_applicable_not_missing():
    schema = build_match_key_schema("APB4")
    assert schema["axes"]["transaction_id"]["status"] == AXIS_NOT_APPLICABLE
    # A settled protocol fact is NOT an open question.
    assert "transaction_id" not in unresolved_match_key_axes(schema)


def test_an_axis_thinner_than_its_definition_says_so():
    """APB has a sequence/burst axis only through `sequence_number`; its burst
    fields do not exist. Reporting a bare APPLICABLE would overstate the key."""
    axis = build_match_key_schema("APB4")["axes"]["sequence_burst"]
    assert axis["status"] == AXIS_APPLICABLE
    assert axis["ir_fields_available"] == ["sequence_number"]
    assert axis["partial"] is True
    assert set(axis["ir_fields_not_applicable"]) == {"burst_type", "burst_len", "burst_size"}


def test_the_route_axis_survives_a_protocol_with_no_address():
    """AXI4-Stream is not memory-mapped, but route identity is carried by
    protocol-independent IR fields, so the axis is still available."""
    schema = build_match_key_schema("AXI4_STREAM")
    assert schema["axes"]["route"]["status"] == AXIS_APPLICABLE
    assert schema["axes"]["transaction_id"]["status"] == AXIS_APPLICABLE  # TID


def test_ace_lite_coherency_is_a_named_ir_gap_not_a_dropped_axis():
    """SYOSCB-17 asks for "coherency attributes where applicable" and
    AMBA_TRANSACTION_IR_FIELDS carries no field for AxSNOOP/AxDOMAIN/AxBAR.
    The axis is reported real-but-uncarriable, with the signals named."""
    schema = build_match_key_schema("ACE_LITE")
    axis = schema["axes"]["coherency_attributes"]
    assert axis["status"] == AXIS_NO_IR_FIELD
    assert set(axis["witness_signals"]) == set(ACE_LITE_COHERENCY_SIGNALS)
    assert "coherency_attributes" in unresolved_match_key_axes(schema)
    assert not any(f in AMBA_TRANSACTION_IR_FIELDS
                   for f in ("snoop", "domain", "barrier"))


def test_a_non_ace_protocol_reports_coherency_not_applicable():
    assert build_match_key_schema("AXI4")["axes"][
        "coherency_attributes"]["status"] == AXIS_NOT_APPLICABLE


def test_an_unresolved_protocol_leaves_every_protocol_DEPENDENT_axis_undecided():
    """Only the axes that need a protocol go undecided. Route and master
    identity are protocol-INDEPENDENT IR fields -- which master port sent an
    item is knowable before anyone has classified the bus -- so claiming those
    were undecided would overstate the gap in the other direction."""
    schema = build_match_key_schema(AMBA_PROTOCOL_UNRESOLVED)
    for axis in ("transaction_id", "coherency_attributes"):
        assert schema["axes"][axis]["status"] == AXIS_PROTOCOL_UNRESOLVED, axis
    for axis in ("route", "master", "read_write_domain"):
        assert schema["axes"][axis]["status"] == AXIS_APPLICABLE, axis
    # The burst axis survives only through its protocol-independent field, and
    # says so rather than implying the burst fields were resolved.
    burst = schema["axes"]["sequence_burst"]
    assert burst["ir_fields_available"] == ["sequence_number"]
    assert set(burst["ir_fields_unresolved"]) == {"burst_type", "burst_len", "burst_size"}
    assert any("stay undecided" in e for e in burst["evidence"])
    # A protocol-classification gap is reported by whoever owns classification.
    assert unresolved_match_key_axes(schema) == ["ordering_domain"]


def test_the_ordering_domain_axis_without_a_prediction_says_who_owns_it():
    axis = build_match_key_schema("AXI4")["axes"]["ordering_domain"]
    assert axis["status"] == AXIS_REQUIRED_HUMAN_INPUT
    assert any("detect_ordering_domain" in e for e in axis["evidence"])


def test_the_ordering_domain_axis_reads_a_real_prediction_rather_than_re_deriving_it():
    axis = build_match_key_schema("AXI4", prediction=_axi_prediction())["axes"]["ordering_domain"]
    assert axis["status"] == AXIS_APPLICABLE
    assert axis["domain_key"] == ORDERING_DOMAIN_PER_ROUTE_AND_ID
    assert axis["route_ordering_expectation"] == ORDERING_OUT_OF_ORDER
    # The reorder-window depth stays the predictor's open question.
    assert axis["ordering_tolerance_depth"] == REQUIRED_HUMAN_INPUT


def test_normalization_without_a_prediction_is_unchecked_not_absent():
    """"Normalize expected behavior before comparison" -- treating an
    unchecked axis as needing no normalization is the silent false-PASS."""
    axis = build_match_key_schema("AXI4")["axes"]["transaction_id"]
    assert axis["normalization"]["status"] == AXIS_REQUIRED_HUMAN_INPUT
    assert axis["normalization"]["responsibilities"] == ["id_remap"]
    assert any("unchecked" in e for e in axis["normalization"]["evidence"])


def test_normalization_with_a_real_prediction_names_the_responsibility_that_did_it():
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    normalization = schema["axes"]["transaction_id"]["normalization"]
    assert normalization["status"] in ("NORMALIZATION_PREDICTED", "NO_TRANSFORM_PREDICTED",
                                       AXIS_REQUIRED_HUMAN_INPUT)
    assert normalization["responsibilities"] == ["id_remap"]
    assert normalization["evidence"]


def test_an_axis_with_no_transform_says_no_normalization_is_required():
    axis = build_match_key_schema("AXI4")["axes"]["read_write_domain"]
    assert axis["normalization"]["status"] == "NO_NORMALIZATION_REQUIRED"


# ===========================================================================
# SYOSCB-18's actual rule, enforced
# ===========================================================================

def test_a_key_that_keeps_no_discriminating_axis_is_refused():
    """"Do not rely solely on expected.compare(actual)". A key made only of
    payload-shaped axes is that compare with extra steps."""
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    with pytest.raises(CompareStrategyError) as excinfo:
        assert_not_raw_object_compare(schema, proposed_axes=["sequence_burst"])
    assert excinfo.value.reason == "MATCH_KEY_IS_RAW_OBJECT_COMPARE"
    assert "transaction_id" in excinfo.value.detail["dropped_discriminating_axes"]
    assert any("cl_syoscb_item.svh" in c for c in excinfo.value.detail["citations"])


def test_an_empty_key_is_refused_too():
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    with pytest.raises(CompareStrategyError):
        assert_not_raw_object_compare(schema, proposed_axes=[])


def test_the_schemas_own_key_passes_the_rule():
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    assert_not_raw_object_compare(schema)


def test_a_key_naming_an_axis_that_does_not_exist_is_refused():
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    with pytest.raises(CompareStrategyError) as excinfo:
        assert_not_raw_object_compare(schema, proposed_axes=["payload_hash"])
    assert excinfo.value.reason == "MATCH_KEY_UNKNOWN_AXIS"


def test_a_policy_whose_required_axes_are_unavailable_cannot_be_adopted():
    """AXI4's OUT_OF_ORDER default requires the ordering-domain axis. Built
    without a prediction that axis is REQUIRED_HUMAN_INPUT, so the policy's own
    precondition is unmet and adopting it would be a false PASS waiting to
    happen."""
    policy = resolve_compare_policy("AXI4", master_count=1)
    schema = build_match_key_schema("AXI4")
    with pytest.raises(CompareStrategyError) as excinfo:
        assert_policy_required_axes_present(policy, schema)
    assert excinfo.value.reason == "COMPARE_POLICY_REQUIRED_AXIS_UNAVAILABLE"
    assert [u["axis"] for u in excinfo.value.detail["unmet"]] == ["ordering_domain"]


def test_the_same_policy_is_adoptable_once_the_prediction_supplies_the_axis():
    policy = resolve_compare_policy("AXI4", master_count=1)
    assert_policy_required_axes_present(
        policy, build_match_key_schema("AXI4", prediction=_axi_prediction()))


def test_ace_lite_cannot_yet_meet_its_own_coherency_precondition():
    """The IR gap made consequential: ACE-Lite's starting policy REQUIRES a
    coherency axis the IR has no field for, so the check refuses it and names
    the missing thing."""
    policy = resolve_compare_policy("ACE_LITE", master_count=1)
    rows = [master("CPU_ACE", "ACE_LITE"), slave("DDR_ACE", "ACE_LITE", id_width="8")]
    prediction = predict_routes(rows, assume_full_connectivity=True)[0]
    schema = build_match_key_schema("ACE_LITE", prediction=prediction)
    with pytest.raises(CompareStrategyError) as excinfo:
        assert_policy_required_axes_present(policy, schema)
    unmet = {u["axis"]: u["status"] for u in excinfo.value.detail["unmet"]}
    assert unmet == {"coherency_attributes": AXIS_NO_IR_FIELD}


# ===========================================================================
# Feeding the existing scoreboard-plan schema, as proposals
# ===========================================================================

def test_the_proposals_only_touch_real_scoreboard_plan_columns():
    assert set(COMPARE_POLICY_INFORMED_PLAN_FIELDS) <= set(SCOREBOARD_PLAN_FIELDS)
    policy = resolve_compare_policy("AXI4", master_count=1)
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    proposals = propose_scoreboard_plan_fields(policy, schema)
    assert set(proposals) == set(COMPARE_POLICY_INFORMED_PLAN_FIELDS)
    assert_plan_proposals_are_not_confirmations(proposals)


def test_the_matching_key_proposal_is_a_composite_with_its_normalization():
    policy = resolve_compare_policy("AXI4", master_count=1)
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    proposal = propose_scoreboard_plan_fields(policy, schema)["matching_key"]["proposal"]
    assert proposal["kind"] == "COMPOSITE_MATCH_KEY"
    assert len(proposal["axes"]) >= 5, "SYOSCB-18's key is composite, not one field"
    for axis in proposal["axes"]:
        assert axis["axis"] in MATCH_KEY_AXES
        assert axis["normalization"]


def test_transformation_rules_is_left_to_the_predictor_that_already_proposes_it():
    """One proposer per column. A second one is how two mechanisms end up
    disagreeing about one field."""
    assert "transformation_rules" not in COMPARE_POLICY_INFORMED_PLAN_FIELDS


def test_a_proposal_that_claims_confirmation_is_refused():
    policy = resolve_compare_policy("AXI4", master_count=1)
    schema = build_match_key_schema("AXI4", prediction=_axi_prediction())
    proposals = propose_scoreboard_plan_fields(policy, schema)
    proposals["ordering"]["confirmed"] = True
    with pytest.raises(CompareStrategyError) as excinfo:
        assert_plan_proposals_are_not_confirmations(proposals)
    assert excinfo.value.reason == "COMPARE_POLICY_PROPOSAL_CLAIMS_CONFIRMATION"


# ===========================================================================
# Resolving the SYOSCB-14/16 plan's own deferred compare strategy
# ===========================================================================

def test_the_plans_deferred_marker_is_what_this_module_answers(three_axi_masters_one_ddr):
    plan = plan_from(three_axi_masters_one_ddr)
    assert {g["compare_strategy"] for g in plan["scoreboards"]} == {COMPARE_STRATEGY_DEFERRED}
    resolutions = resolve_plan_compare_strategies(plan)
    assert len(resolutions) == len(plan["scoreboards"])
    assert all(r["deferred_marker"] == COMPARE_STRATEGY_DEFERRED for r in resolutions)


def test_three_axi_masters_into_one_ddr_resolve_out_of_order_with_the_ooo_caution(
        three_axi_masters_one_ddr):
    plan = plan_from(three_axi_masters_one_ddr)
    record = resolve_plan_compare_strategies(plan)[0]
    assert record["master_count"] == 3
    assert record["master_protocols"] == ["AXI4"]
    assert record["policy"]["ordering"] == ORDERING_OUT_OF_ORDER
    assert record["ordering_domain_key"] == ORDERING_DOMAIN_PER_ROUTE_AND_ID
    assert any("no producer filter" in c.lower() for c in record["policy"]["cautions"])
    assert unresolved_compare_strategies([record]) == []


def test_the_plans_own_master_count_decides_a_multi_master_ahb(two_ahb_masters_one_slave):
    """The AHB question answered from real topology evidence rather than
    asked: the plan's producer list already knows how many masters feed the
    group."""
    record = resolve_plan_compare_strategies(plan_from(two_ahb_masters_one_slave))[0]
    assert record["master_count"] == 2
    assert record["policy"]["ordering"] == ORDERING_IN_ORDER_PER_PRODUCER
    assert record["status"] == POLICY_REFINED_BY_TOPOLOGY
    assert record["ordering_domain_key"] == ORDERING_DOMAIN_PER_ROUTE


def test_a_single_master_ahb_needs_no_producer_awareness(one_ahb_master_one_slave):
    record = resolve_plan_compare_strategies(plan_from(one_ahb_master_one_slave))[0]
    assert record["master_count"] == 1
    assert record["policy"]["ordering"] == ORDERING_IN_ORDER


def test_a_mixed_protocol_group_is_an_open_question_not_an_arbitration(
        mixed_protocol_masters_one_slave):
    """SYOSCB-17 gives one starting policy per protocol and no rule for
    arbitrating two. Picking one would be inventing a rule the document does
    not have."""
    plan = plan_from(mixed_protocol_masters_one_slave)
    record = next(r for r in resolve_plan_compare_strategies(plan)
                  if len(r["master_protocols"]) > 1)
    assert set(record["master_protocols"]) == {"AHB_LITE", "APB4"}
    assert record["status"] == REQUIRED_HUMAN_INPUT
    assert record["reason"] == GROUP_MIXED_PROTOCOL
    assert record["policy"] is None
    assert record["scoreboard_id"] in unresolved_compare_strategies([record])


def test_resolving_never_mutates_the_plan(three_axi_masters_one_ddr):
    """A policy is a proposal; overwriting DEFERRED_TO_SYOSCB_17 in place would
    make the plan look decided."""
    plan = plan_from(three_axi_masters_one_ddr)
    resolve_plan_compare_strategies(plan)
    assert {g["compare_strategy"] for g in plan["scoreboards"]} == {COMPARE_STRATEGY_DEFERRED}


@real_source
def test_a_resolved_plan_names_the_real_compare_class(three_axi_masters_one_ddr):
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    record = resolve_plan_compare_strategies(
        plan_from(three_axi_masters_one_ddr), audit=audit)[0]
    assert record["policy"]["compare_class"]["class"] == "cl_syoscb_compare_ooo"


# ===========================================================================
# Rendering: tables and a report, never SystemVerilog
# ===========================================================================

def test_the_policy_table_renders_every_protocol():
    table = render_protocol_policy_table()
    for protocol in AMBA4_PROTOCOLS:
        assert PROTOCOL_COMPARE_POLICY[protocol]["doc_policy"] in table


def test_the_rendered_report_is_not_emittable_systemverilog(three_axi_masters_one_ddr):
    plan = plan_from(three_axi_masters_one_ddr)
    report = render_compare_policy_report(
        resolutions=resolve_plan_compare_strategies(plan),
        schemas=[build_match_key_schema("AXI4", prediction=_axi_prediction()),
                 build_match_key_schema("ACE_LITE")])
    assert_no_emittable_sv(report, label="SYOSCB-17/18 policy report")
    assert_no_bind_statement(report)
    assert "SYOSCB-17" in report and "SYOSCB-18" in report


def test_the_report_names_the_open_axes_rather_than_hiding_them():
    report = render_compare_policy_report(
        schemas=[build_match_key_schema("ACE_LITE")])
    assert "axes still open" in report
    assert "coherency_attributes" in report


def test_the_match_key_and_strategy_tables_render(three_axi_masters_one_ddr):
    assert render_match_key_table(build_match_key_schema("AXI4")).count("|") > 10
    resolutions = resolve_plan_compare_strategies(plan_from(three_axi_masters_one_ddr))
    assert "cl_syoscb" not in render_compare_strategy_table(resolutions)


# ===========================================================================
# The real parsed AMBA4 SoC, end to end
# ===========================================================================

@pytest.fixture(scope="module")
def real_registry(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("syoscb_compare_policy_rtl"))
    netlist = build_fabric_netlist([parse_file(sv)], "soc_top")
    traces = trace_all_fabric_ports(netlist, FABRIC)
    bind_plan = build_vip_bind_plan(netlist, traces)
    return build_amba_port_registry(netlist, traces, bind_plan)


@requires_verible
def test_the_real_discovered_fabric_gets_a_real_compare_policy(real_registry):
    """The whole chain with nothing synthetic: real RTL -> real trace -> real
    AMBA_PORT_REGISTRY -> real predictions -> a real plan -> a real compare
    strategy and a real match key per scoreboard."""
    predictions = predict_routes(real_registry, assume_full_connectivity=True)
    plan = build_syoscb_configuration_plan(real_registry, predictions)
    resolutions = resolve_plan_compare_strategies(plan)
    assert resolutions, "a discovered scoreboard must get a compare-strategy record"
    for record in resolutions:
        assert record["scoreboard_id"]
        assert record["evidence"], "every record states what it was decided from"
        if record["policy"] is not None:
            assert record["policy"]["confirmed"] is False
    schemas = [build_match_key_schema(p["responsibilities"]["master_slave_route"]
                                      and _protocol_of(real_registry, p), prediction=p)
               for p in predictions]
    for schema in schemas:
        assert_not_raw_object_compare(schema)
    report = render_compare_policy_report(resolutions=resolutions, schemas=schemas)
    assert_no_emittable_sv(report, label="real fixture compare policy")
    assert_no_bind_statement(report)


def _protocol_of(rows, prediction):
    """The master-side protocol of a real prediction, read off the registry."""
    for row in rows:
        if row.get("endpoint_hierarchy") == prediction["master_endpoint"]:
            return row.get("protocol")
    return AMBA_PROTOCOL_UNRESOLVED


@requires_verible
@real_source
def test_the_real_plan_and_the_real_library_agree_on_the_compare_class(real_registry):
    """The two real inputs joined the way a Phase-2 implementer would have to:
    the discovered fabric and the upstream library, checked together."""
    predictions = predict_routes(real_registry, assume_full_connectivity=True)
    plan = build_syoscb_configuration_plan(real_registry, predictions)
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    assert_policy_table_resolves_to_real_classes(audit)
    for record in resolve_plan_compare_strategies(plan, audit=audit):
        if record["policy"] is None:
            continue
        name = record["policy"]["compare_class"]["class"]
        assert name in {"cl_syoscb_compare_io", "cl_syoscb_compare_iop",
                        "cl_syoscb_compare_ooo", REQUIRED_HUMAN_INPUT}, name
