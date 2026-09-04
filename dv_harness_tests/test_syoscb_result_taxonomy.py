"""Tests for SYOSCB-21 (required scoreboard result taxonomy) and SYOSCB-22
(scoreboard by port visibility) -- `dv_harness/syoscb_result_taxonomy.py`.

Three kinds of fixture, every one of them real where a real one exists:

  * The REAL master-prompt document, so the fourteen result values and the
    thirteen counter names are held against the lines they claim to
    transcribe. A taxonomy that drifted from the requirement it encodes is
    worse than none, because it looks authoritative.
  * The REAL parsed AMBA4 SoC fixture carried through a real
    `build_amba_port_registry()`, so the counter blocks are derived from rows
    a real verible parse produced rather than from hand-typed ones.
  * SYNTHETIC AMBA_PORT_REGISTRY rows (reusing
    `test_amba_route_transform_predictor`'s own `master()`/`slave()` helpers)
    for the feasibility cases the real fixture cannot produce: an APB4 port
    with no burst concept, an AXI4-Stream port with no response channel, a
    port with no VIP planned, a port with no scoreboard channel, and a port
    whose protocol never resolved.

Every decision is tested on BOTH sides -- what it decides, and what it
refuses to decide when the evidence is missing. The no-scoreboard-channel
case, the unresolved-protocol case, the no-VIP case and the
"a zero is refused as an observed value" case are all here for that reason:
a taxonomy tested only where the answer exists is the happy-path-only
coverage this project has been burned by.

Nothing here writes or reads SystemVerilog, runs a simulator, or copies any
file out of D:/DV/Scoreboard/uvm_syoscb-1.0.2.4.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dv_harness import syoscb_result_taxonomy as rt
from dv_harness.amba_fabric_discovery import (
    assert_no_bind_statement,
    build_fabric_netlist,
    build_vip_bind_plan,
    trace_all_fabric_ports,
)
from dv_harness.amba_port_registry import (
    AMBA_PORT_REGISTRY_FIELDS,
    VIP_MODE_NOT_PLANNED,
    build_amba_port_registry,
)
from dv_harness.connectivity import (
    ALL_AMBA_SIGNAL_NAMES,
    AMBA_PROTOCOL_UNRESOLVED,
    REQUIRED_HUMAN_INPUT,
    GateStatus,
)
from dv_harness.sim_log_analysis import (
    TRIAGE_CATEGORIES,
    classify_signatures,
    severity_for_category,
)
from dv_harness.syoscb_result_taxonomy import (
    AMBA_PORT_VISIBILITY_COUNTER_FIELDS,
    COUNTER_DOC_LINE,
    COUNTER_NOT_APPLICABLE,
    COUNTER_NOT_FEASIBLE_NO_VIP,
    COUNTER_NOT_OBSERVED,
    COUNTER_PROTOCOL_UNRESOLVED,
    COUNTER_SOURCE,
    COUNTER_SOURCE_PORT_MONITOR,
    COUNTER_SOURCE_SCOREBOARD,
    MAP_COARSER,
    MAP_EXACT,
    MAP_NONE,
    PORT_VISIBILITY_BLOCK_FIELD,
    RESULT_TRIAGE,
    SCOREBOARD_RESULT_VALUES,
    TAXONOMY_DOC,
    TRIAGE_NOT_A_FAILURE,
    ScoreboardResult,
    ScoreboardResultTaxonomyError,
    assert_counters_unobserved,
    assert_result_taxonomy_is_disjoint_from_gate_status,
    assert_unknown_is_never_silently_triaged,
    attach_port_visibility_counters,
    build_port_visibility_counters,
    classify_result_counts,
    coerce_result,
    port_counter_for_result,
    render_port_visibility_table,
    render_result_taxonomy_report,
    render_result_taxonomy_table,
    triage_for_result,
    unresolved_port_visibility_counters,
)
from dv_harness.syoscb_source_audit import assert_no_emittable_sv
from dv_harness.verible_parser import parse_file
from dv_harness_tests.test_amba_route_transform_predictor import master, slave
from dv_harness_tests.test_amba_vip_bind_plan import FABRIC, write_fixture

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

REAL_DOC = Path(__file__).resolve().parents[2] / TAXONOMY_DOC
MODULE_SOURCE = Path(rt.__file__).read_text(encoding="utf-8")


def doc_line(number: int) -> str:
    """One 1-indexed line of the real master prompt."""
    return REAL_DOC.read_text(encoding="utf-8", errors="replace").splitlines()[number - 1].strip()


@pytest.fixture(scope="module")
def real_registry(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("syoscb_result_taxonomy_rtl"))
    netlist = build_fabric_netlist([parse_file(sv)], "soc_top")
    traces = trace_all_fabric_ports(netlist, FABRIC)
    plan = build_vip_bind_plan(netlist, traces)
    return build_amba_port_registry(netlist, traces, plan)


def counters(row: dict) -> dict:
    return row[PORT_VISIBILITY_BLOCK_FIELD]["counters"]


def one(rows_or_row) -> dict:
    """The counter block for a single synthetic row."""
    return attach_port_visibility_counters([rows_or_row])[0]


# ===========================================================================
# SYOSCB-21: the fourteen values, held against the real document
# ===========================================================================

def test_the_taxonomy_is_the_documents_own_fourteen_values_in_its_own_order():
    """Read straight out of the real master prompt (lines 5049-5062), not out
    of a paraphrase of it."""
    assert REAL_DOC.is_file(), f"the master prompt must be readable at {REAL_DOC}"
    from_doc = [doc_line(n) for n in range(5049, 5063)]
    assert list(SCOREBOARD_RESULT_VALUES) == from_doc
    assert len(SCOREBOARD_RESULT_VALUES) == 14


def test_every_result_cites_the_document_line_that_names_it():
    for result in ScoreboardResult:
        entry = RESULT_TRIAGE[result]
        assert doc_line(entry["doc_line"]) == result.value
        assert triage_for_result(result)["evidence"].endswith(str(entry["doc_line"]))


def test_the_taxonomy_shares_no_value_with_gate_status():
    """A per-transaction verdict and a per-gate-run status must stay two
    vocabularies: a report carrying one token that could be either cannot say
    which question it answered."""
    assert not set(SCOREBOARD_RESULT_VALUES) & {g.value for g in GateStatus}
    assert_result_taxonomy_is_disjoint_from_gate_status()


def test_the_taxonomy_does_not_report_only_pass_fail():
    """SYOSCB-21 opens with "Do not report only PASS/FAIL." -- the check that
    the taxonomy really replaced the binary rather than wrapping it."""
    assert "PASS" not in SCOREBOARD_RESULT_VALUES
    assert "FAIL" not in SCOREBOARD_RESULT_VALUES
    failure_values = [v for v in SCOREBOARD_RESULT_VALUES
                      if v not in (ScoreboardResult.MATCH.value,
                                   ScoreboardResult.UNKNOWN.value)]
    assert len(failure_values) == 12


# ===========================================================================
# SYOSCB-21: "Feed these into existing L5 failure-triage"
# ===========================================================================

def test_every_routed_category_is_one_the_existing_l5_triage_vocabulary_defines():
    """The requirement is to feed the EXISTING triage, so a category this repo
    does not already have would be a second vocabulary wearing the first
    one's name."""
    routed = {e["triage_category"] for e in RESULT_TRIAGE.values()}
    assert routed <= set(TRIAGE_CATEGORIES) | {TRIAGE_NOT_A_FAILURE, REQUIRED_HUMAN_INPUT}


def test_severity_is_read_from_sim_log_analysis_rather_than_stored_here():
    """A stored severity is how one severity scale becomes two that
    disagree."""
    assert all("severity" not in e for e in RESULT_TRIAGE.values())
    for result in ScoreboardResult:
        routed = triage_for_result(result)
        if routed["triage_category"] in TRIAGE_CATEGORIES:
            assert routed["severity"] == severity_for_category(routed["triage_category"])


def test_a_burst_or_transform_error_is_not_dropped_into_the_low_severity_bucket():
    """The L5 vocabulary has no protocol-violation category. Routing these to
    "other" would be syntactically fine and would put a real fabric transform
    bug at LOW severity."""
    for result in (ScoreboardResult.BURST_ERROR, ScoreboardResult.PROTOCOL_TRANSFORM_ERROR):
        routed = triage_for_result(result)
        assert routed["triage_category"] == "scoreboard_mismatch"
        assert routed["severity"] == "HIGH"
        assert routed["triage_precision"] == MAP_COARSER


def test_timeout_maps_exactly_because_l5_triage_really_has_that_category():
    routed = triage_for_result(ScoreboardResult.TIMEOUT)
    assert routed["triage_category"] == "timeout"
    assert routed["triage_precision"] == MAP_EXACT
    assert routed["severity"] == severity_for_category("timeout")


def test_match_is_never_routed_into_failure_triage():
    routed = triage_for_result(ScoreboardResult.MATCH)
    assert routed["triage_category"] == TRIAGE_NOT_A_FAILURE
    assert routed["severity"] == TRIAGE_NOT_A_FAILURE
    assert routed["triage_category"] not in TRIAGE_CATEGORIES


def test_unknown_reaches_a_human_rather_than_a_severity_bucket():
    """The missing-evidence case for SYOSCB-21: a comparison happened and its
    verdict could not be classified. Nothing may absorb that."""
    routed = triage_for_result(ScoreboardResult.UNKNOWN)
    assert routed["triage_category"] == REQUIRED_HUMAN_INPUT
    assert routed["severity"] == REQUIRED_HUMAN_INPUT
    assert routed["severity"] != severity_for_category("other")
    assert port_counter_for_result(ScoreboardResult.UNKNOWN) == REQUIRED_HUMAN_INPUT
    assert_unknown_is_never_silently_triaged()


def test_required_human_input_reuses_the_harnesss_one_sentinel():
    """A second private "a human must supply this" string is exactly the
    duplicate-mechanism failure this project keeps catching."""
    assert RESULT_TRIAGE[ScoreboardResult.UNKNOWN]["triage_category"] is REQUIRED_HUMAN_INPUT


def test_a_value_outside_the_taxonomy_is_refused_rather_than_coerced_to_unknown():
    """UNKNOWN means "a real comparison produced an unclassifiable verdict".
    Reusing it for a caller's typo would make the one member that demands
    attention indistinguishable from a bug."""
    with pytest.raises(ScoreboardResultTaxonomyError) as exc:
        coerce_result("PARTIAL_MATCH")
    assert exc.value.reason == "SYOSCB21_RESULT_NOT_IN_TAXONOMY"


def test_a_string_naming_a_real_member_is_accepted_so_a_persisted_result_round_trips():
    assert coerce_result("ROUTE_ERROR") is ScoreboardResult.ROUTE_ERROR
    assert ScoreboardResult.ROUTE_ERROR == "ROUTE_ERROR"


# ===========================================================================
# SYOSCB-21 -> SYOSCB-22: the mapping, and the information it loses
# ===========================================================================

def test_every_result_routes_to_a_counter_that_really_exists():
    for result in ScoreboardResult:
        target = port_counter_for_result(result)
        assert (target in AMBA_PORT_VISIBILITY_COUNTER_FIELDS
                or target == REQUIRED_HUMAN_INPUT)


def test_a_duplicate_is_indistinguishable_from_an_unexpected_transaction_per_port_and_says_so():
    """SYOSCB-22's counter list carries no duplicate counter. The loss is real
    and is recorded as data, not left for a reader to notice."""
    assert (port_counter_for_result(ScoreboardResult.DUPLICATE_TRANSACTION)
            == port_counter_for_result(ScoreboardResult.UNEXPECTED_TRANSACTION)
            == "unexpected_transaction_count")
    assert RESULT_TRIAGE[ScoreboardResult.DUPLICATE_TRANSACTION][
        "counter_precision"] == MAP_COARSER
    assert RESULT_TRIAGE[ScoreboardResult.UNEXPECTED_TRANSACTION][
        "counter_precision"] == MAP_EXACT


def test_the_three_mismatch_axes_collapse_into_one_counter_and_each_says_so():
    for result in (ScoreboardResult.ADDRESS_MISMATCH, ScoreboardResult.RESPONSE_MISMATCH):
        assert port_counter_for_result(result) == "mismatch_count"
        assert RESULT_TRIAGE[result]["counter_precision"] == MAP_COARSER
    assert RESULT_TRIAGE[ScoreboardResult.DATA_MISMATCH]["counter_precision"] == MAP_EXACT


def test_route_and_ordering_errors_keep_their_own_per_port_counters():
    assert port_counter_for_result(ScoreboardResult.ROUTE_ERROR) == "route_error_count"
    assert port_counter_for_result(ScoreboardResult.ORDERING_ERROR) == "ordering_error_count"


def test_classify_result_counts_aggregates_and_names_every_lossy_mapping():
    totals = classify_result_counts({
        "MATCH": 10, "DATA_MISMATCH": 2, "ADDRESS_MISMATCH": 1,
        "DUPLICATE_TRANSACTION": 3, "ROUTE_ERROR": 4,
    })
    assert totals["counters"]["match_count"] == 10
    assert totals["counters"]["mismatch_count"] == 3
    assert totals["counters"]["unexpected_transaction_count"] == 3
    assert totals["counters"]["route_error_count"] == 4
    lossy = {c["result"] for c in totals["coarse_mappings"]}
    assert lossy == {"ADDRESS_MISMATCH", "DUPLICATE_TRANSACTION"}


def test_classify_result_counts_keeps_unknown_out_of_every_counter():
    totals = classify_result_counts({"UNKNOWN": 7, "MATCH": 1})
    assert totals["unclassified"] == 7
    assert totals["unclassified_result"] == "UNKNOWN"
    assert sum(totals["counters"].values()) == 1


def test_classify_result_counts_refuses_something_that_is_not_a_count():
    with pytest.raises(ScoreboardResultTaxonomyError) as exc:
        classify_result_counts({"MATCH": -1})
    assert exc.value.reason == "SYOSCB21_RESULT_COUNT_NOT_A_COUNT"
    with pytest.raises(ScoreboardResultTaxonomyError):
        classify_result_counts({"MATCH": "many"})


# ===========================================================================
# SYOSCB-22: the thirteen counters, held against the real document
# ===========================================================================

def test_the_counter_list_is_the_documents_own_thirteen_in_its_own_order():
    expected = [
        ("transaction_count", "transaction count"),
        ("read_count", "read count"),
        ("write_count", "write count"),
        ("burst_count", "burst count"),
        ("response_count", "responses"),
        ("error_response_count", "errors"),
        ("match_count", "matches"),
        ("mismatch_count", "mismatches"),
        ("missing_transaction_count", "missing transactions"),
        ("unexpected_transaction_count", "unexpected transactions"),
        ("ordering_error_count", "ordering errors"),
        ("route_error_count", "route errors"),
        ("latency", "latency/performance"),
    ]
    assert list(AMBA_PORT_VISIBILITY_COUNTER_FIELDS) == [f for f, _ in expected]
    for field, noun in expected:
        assert doc_line(COUNTER_DOC_LINE[field]) == noun


def test_no_counter_shadows_one_of_amba22s_nineteen_registry_columns():
    """The counters hang off the same row; a collision would overwrite a real
    width or clock while `assert_registry_complete()` kept passing."""
    assert not set(AMBA_PORT_VISIBILITY_COUNTER_FIELDS) & set(AMBA_PORT_REGISTRY_FIELDS)


def test_the_counters_split_into_monitor_derived_and_compare_derived():
    """Not decoration: it is what lets a port with a monitor and no scoreboard
    still report real observability instead of nothing."""
    monitor = {f for f, s in COUNTER_SOURCE.items() if s == COUNTER_SOURCE_PORT_MONITOR}
    compare = {f for f, s in COUNTER_SOURCE.items() if s == COUNTER_SOURCE_SCOREBOARD}
    assert monitor and compare and not monitor & compare
    assert "match_count" in compare and "transaction_count" in monitor


# ===========================================================================
# SYOSCB-22: feasibility derived from the row, never assumed
# ===========================================================================

def test_every_counter_starts_unobserved_rather_than_zero():
    """No transaction has run and none can before SYOSCB-34. A `0` here would
    be a measurement nobody made."""
    row = one(master("CPU_AXI", "AXI4"))
    for field, entry in counters(row).items():
        assert entry["status"] == COUNTER_NOT_OBSERVED, field
        assert entry["value"] == COUNTER_NOT_OBSERVED
        assert not isinstance(entry["value"], int)


def test_a_numeric_counter_value_is_refused_as_an_observed_run():
    row = one(master("CPU_AXI", "AXI4"))
    counters(row)["transaction_count"]["value"] = 0
    with pytest.raises(ScoreboardResultTaxonomyError) as exc:
        assert_counters_unobserved([row])
    assert exc.value.reason == "SYOSCB22_COUNTER_ALREADY_OBSERVED"


def test_an_unrecognised_counter_status_is_refused():
    row = one(master("CPU_AXI", "AXI4"))
    counters(row)["latency"]["status"] = "OK"
    with pytest.raises(ScoreboardResultTaxonomyError) as exc:
        assert_counters_unobserved([row])
    assert exc.value.reason == "SYOSCB22_COUNTER_UNKNOWN_STATUS"


def test_burst_count_is_not_applicable_on_apb_because_the_bus_has_no_burst_length():
    row = one(slave("CFG_APB", "APB4"))
    assert counters(row)["burst_count"]["status"] == COUNTER_NOT_APPLICABLE
    assert counters(row)["transaction_count"]["status"] == COUNTER_NOT_OBSERVED
    assert counters(row)["response_count"]["status"] == COUNTER_NOT_OBSERVED


def test_response_counters_are_not_applicable_on_axi_stream():
    row = one(slave("VID_STREAM", "AXI4_STREAM"))
    assert counters(row)["response_count"]["status"] == COUNTER_NOT_APPLICABLE
    assert counters(row)["error_response_count"]["status"] == COUNTER_NOT_APPLICABLE
    assert counters(row)["burst_count"]["status"] == COUNTER_NOT_APPLICABLE
    assert counters(row)["transaction_count"]["status"] == COUNTER_NOT_OBSERVED


def test_a_port_with_no_vip_planned_has_no_feasible_counter_at_all():
    """SYOSCB-22 says "where feasible". A port nothing observes is the case
    that word exists for."""
    row = one(master("DARK_AXI", "AXI4", vip_mode=VIP_MODE_NOT_PLANNED))
    statuses = {e["status"] for e in counters(row).values()}
    assert statuses == {COUNTER_NOT_FEASIBLE_NO_VIP}


def test_a_port_with_no_scoreboard_channel_keeps_its_monitor_counters():
    """The missing-evidence case for SYOSCB-22: AMBA-21 established no
    ingress, so no comparison exists -- but the port's own monitor still
    observes traffic, and reporting nothing would hide real observability."""
    row = one(master("CPU_AXI", "AXI4", scoreboard_channel=REQUIRED_HUMAN_INPUT))
    for field, entry in counters(row).items():
        if COUNTER_SOURCE[field] == COUNTER_SOURCE_SCOREBOARD:
            assert entry["status"] == REQUIRED_HUMAN_INPUT, field
        else:
            assert entry["status"] == COUNTER_NOT_OBSERVED, field


def test_an_unresolved_protocol_is_undecided_applicability_not_not_applicable():
    """"this bus has no burst length" and "nobody established what this bus
    is" are different facts, and only the second is a closable discovery
    gap."""
    row = one(master("MYSTERY", AMBA_PROTOCOL_UNRESOLVED))
    assert counters(row)["burst_count"]["status"] == COUNTER_PROTOCOL_UNRESOLVED
    assert counters(row)["response_count"]["status"] == COUNTER_PROTOCOL_UNRESOLVED
    assert COUNTER_PROTOCOL_UNRESOLVED != COUNTER_NOT_APPLICABLE
    # A protocol-independent counter stays feasible: a transfer either
    # happened or it did not, whatever the bus turns out to be.
    assert counters(row)["transaction_count"]["status"] == COUNTER_NOT_OBSERVED


def test_no_vip_planned_outranks_an_unresolved_protocol():
    """Both are true at once on a genuinely undiscovered port; the reviewer
    needs the blocker that stops every counter, not the one that stops some."""
    row = one(master("MYSTERY", AMBA_PROTOCOL_UNRESOLVED, vip_mode=VIP_MODE_NOT_PLANNED))
    assert counters(row)["transaction_count"]["status"] == COUNTER_NOT_FEASIBLE_NO_VIP


def test_every_counter_entry_carries_a_reason_and_its_document_evidence():
    row = one(master("CPU_AXI", "AXI4"))
    for field, entry in counters(row).items():
        assert entry["reason"].strip(), field
        assert entry["evidence"] == f"{TAXONOMY_DOC}:{COUNTER_DOC_LINE[field]}"


# ===========================================================================
# SYOSCB-22: the join onto the AMBA_PORT_REGISTRY row
# ===========================================================================

def test_the_counter_block_is_keyed_on_the_registrys_own_port_id():
    row = one(master("CPU_AXI", "AXI4"))
    assert row[PORT_VISIBILITY_BLOCK_FIELD]["port_id"] == row["port_id"] == "CPU_AXI"
    assert row[PORT_VISIBILITY_BLOCK_FIELD]["protocol"] == row["protocol"]


def test_a_row_with_no_port_id_cannot_be_given_counters():
    row = dict(master("CPU_AXI", "AXI4"))
    row["port_id"] = ""
    with pytest.raises(ScoreboardResultTaxonomyError) as exc:
        build_port_visibility_counters(row)
    assert exc.value.reason == "SYOSCB22_COUNTER_BLOCK_WITHOUT_PORT_ID"


def test_attaching_counters_does_not_mutate_the_registry_a_human_reviewed():
    original = master("CPU_AXI", "AXI4")
    attach_port_visibility_counters([original])
    assert PORT_VISIBILITY_BLOCK_FIELD not in original


def test_attached_rows_still_carry_every_one_of_amba22s_nineteen_columns():
    row = one(master("CPU_AXI", "AXI4"))
    assert all(row.get(f) not in (None, "", []) for f in AMBA_PORT_REGISTRY_FIELDS)


def test_unresolved_counters_report_closable_gaps_only():
    """A NOT_APPLICABLE counter is not a work item -- listing it would turn a
    property of the bus into a task nobody can complete."""
    rows = attach_port_visibility_counters([
        master("CPU_AXI", "AXI4", scoreboard_channel=REQUIRED_HUMAN_INPUT),
        slave("CFG_APB", "APB4"),
    ])
    gaps = unresolved_port_visibility_counters(rows)
    assert {g["port_id"] for g in gaps} == {"CPU_AXI"}
    assert {g["counter"] for g in gaps} == {
        f for f, s in COUNTER_SOURCE.items() if s == COUNTER_SOURCE_SCOREBOARD}
    assert "burst_count" not in {g["counter"] for g in gaps}


def test_no_gap_is_reported_when_every_port_is_fully_observable():
    rows = attach_port_visibility_counters([master("CPU_AXI", "AXI4")])
    assert unresolved_port_visibility_counters(rows) == []


# ===========================================================================
# Reporting
# ===========================================================================

def test_the_taxonomy_table_carries_all_fourteen_values_and_their_severities():
    table = render_result_taxonomy_table()
    for value in SCOREBOARD_RESULT_VALUES:
        assert value in table
    assert "scoreboard_mismatch" in table and "HIGH" in table


def test_the_report_is_not_emittable_systemverilog():
    rows = attach_port_visibility_counters([
        master("CPU_AXI", "AXI4", scoreboard_channel=REQUIRED_HUMAN_INPUT),
        slave("CFG_APB", "APB4"),
    ])
    text = render_result_taxonomy_report(rows)
    assert_no_bind_statement(text)
    assert_no_emittable_sv(text, label="test")
    assert "SYOSCB-21" in text and "SYOSCB-22" in text
    assert "Counters a human must still make possible" in text


def test_the_report_renders_with_no_registry_at_all():
    """Phase-1 frequently has the taxonomy and no discovered fabric yet; an
    empty registry must produce an honest note, not a crash."""
    text = render_result_taxonomy_report([])
    assert "no AMBA_PORT_REGISTRY row carried a visibility counter block" in text


def test_the_port_table_names_every_counter_for_every_port():
    rows = attach_port_visibility_counters([master("CPU_AXI", "AXI4")])
    table = render_port_visibility_table(rows)
    for field in AMBA_PORT_VISIBILITY_COUNTER_FIELDS:
        assert field in table


# ===========================================================================
# The real parsed AMBA4 SoC, carried through a real AMBA_PORT_REGISTRY
# ===========================================================================

@requires_verible
def test_every_real_registry_row_gets_a_complete_counter_block(real_registry):
    rows = attach_port_visibility_counters(real_registry)
    assert rows
    for row in rows:
        block = row[PORT_VISIBILITY_BLOCK_FIELD]
        assert block["port_id"] == row["port_id"]
        assert set(block["counters"]) == set(AMBA_PORT_VISIBILITY_COUNTER_FIELDS)
    assert_counters_unobserved(rows)


@requires_verible
def test_the_real_registry_produces_a_clean_review_artifact(real_registry):
    text = render_result_taxonomy_report(attach_port_visibility_counters(real_registry))
    assert_no_bind_statement(text)
    assert_no_emittable_sv(text, label="test")
    for row in real_registry:
        assert row["port_id"] in text


# ===========================================================================
# Reuse discipline
# ===========================================================================

def test_no_amba_signal_name_is_typed_in_this_module():
    """Per-protocol applicability is `amba_transaction_ir`'s answer, derived
    from `connectivity.py`'s signal table. A signal name typed here would be
    this module holding a second opinion about the same bus."""
    typed = sorted(s for s in ALL_AMBA_SIGNAL_NAMES if s in MODULE_SOURCE)
    assert typed == []


def test_the_module_does_not_reimplement_the_severity_scale():
    assert "CRITICAL" not in MODULE_SOURCE
    assert "severity_for_category" in MODULE_SOURCE


def test_the_severity_accessor_agrees_with_the_classifier_it_was_extracted_from():
    """`classify_signatures()` was refactored onto `severity_for_category()`;
    this holds the two to the same answer so the extraction cannot drift."""
    parsed = classify_signatures({
        "sig-a": {"count": 1, "first_line_no": 1, "last_line_no": 1,
                  "example_line": "UVM_FATAL x", "markers": ["UVM_FATAL"]},
        "sig-b": {"count": 1, "first_line_no": 2, "last_line_no": 2,
                  "example_line": "scoreboard mismatch", "markers": ["SCOREBOARD"]},
        "sig-c": {"count": 1, "first_line_no": 3, "last_line_no": 3,
                  "example_line": "license", "markers": ["LICENSE"]},
    })
    for entry in parsed:
        assert entry["severity"] == severity_for_category(entry["category"])
    assert {e["severity"] for e in parsed} == {"CRITICAL", "HIGH", "LOW"}


def test_the_module_states_that_nothing_is_copied_out_of_the_upstream_tree():
    assert "D:/DV/Scoreboard/uvm_syoscb-1.0.2.4" in MODULE_SOURCE
    assert "SYOSCB-33" in MODULE_SOURCE and "SYOSCB-34" in MODULE_SOURCE


def test_map_precision_vocabulary_is_three_distinct_values():
    assert len({MAP_EXACT, MAP_COARSER, MAP_NONE}) == 3
