"""SYS-31..SYS-32: the System-level failure record shape, and the failure-locus
classification built on it.

FIXTURES. The failures below are invented; this harness repo has no
multi-subsystem project and no real System scenario to fail. What is NOT
invented is anything the classification is decided from: the SYS-15 registry
entry, the SYS-28 address reconciliation, the SYS-29 clock/reset comparison,
the SYS-24 scheduling rows, the SYS-25 pair relationships and the SYS-22
collisions all come from the REAL builders over the shared synthetic
subsystems, imported from `test_system_topology_analysis` rather than re-typed
-- a triage proved against a hand-written imitation of an upstream document
proves nothing about the documents the real stack produces.

WHAT THE HARD CASES ARE. A classifier that fires on everything is worse than
none, so every positive case below has a paired control: a driver conflict that
must NOT be attributed to a failure naming a different resource, an ordering
pair that must NOT match a command it does not contain, a cross-subsystem
residual that must stay a residual when a named mechanism really did fire, and
a not-consulted source that must never be read as evidence for the negative.
"""

import json

import pytest

from dv_harness import evidence_db
from dv_harness import inference
from dv_harness import memory_vault as mv
from dv_harness import system_failure_triage as sft
from dv_harness import system_resource_inventory as sri
from dv_harness import system_resource_registry as srr
from dv_harness import system_scheduling_plan as ssp
from dv_harness import system_topology_analysis as sta
from dv_harness_tests.test_system_topology_analysis import (  # reused fixtures
    _address_entry,
    _analysis,
    _clock_reset_agent_entry,
    _clock_reset_field,
    _plans,
    _registry,
)

SCENARIO = "SYSSCEN-TEST0001"


def _failure(subsystem, *, command=None, resource=None, vip_agent=None,
             uvm_error_count=1, **kwargs):
    return sft.build_subsystem_failure_record(
        system_scenario_id=SCENARIO, subsystem=subsystem, command=command,
        resource=resource, vip_agent=vip_agent, protocol=subsystem.split("_")[0],
        pattern="synthetic_pattern", symptom="synthetic symptom",
        uvm_error_count=uvm_error_count,
        sim_log=f"/runs/{subsystem}/sim.log", fsdb_path=f"/runs/{subsystem}/dump.fsdb",
        job_id=f"JOB-{subsystem}", lsf_status="DONE",
        root_cause_hypothesis="synthetic hypothesis",
        independent_sources_count=2, evidence_refs_verified=True, **kwargs)


def _passing(subsystem):
    return sft.build_subsystem_failure_record(
        system_scenario_id=SCENARIO, subsystem=subsystem, uvm_error_count=0,
        lsf_status="DONE")


def _record(*subsystem_records, participating=None):
    return sft.build_system_failure_record(
        SCENARIO, list(subsystem_records),
        participating_subsystems=participating)


def _driver_conflict_registry():
    entry = _clock_reset_agent_entry()
    entry = dict(entry, resource_id="SYSRES-CPU-AXI-0001",
                 resource_type=sri.RT_CPU_BUS_MASTER,
                 member_resource_ids=["PCIE_SS::cpu_axi", "USB_SS::cpu_axi"])
    return _registry([entry], subsystems=("PCIE_SS", "USB_SS"))


def _clean_address_and_clock():
    """A selection with nothing wrong in it, used as the control input wherever
    a test needs the address/clock sources CONSULTED but silent."""
    clean = _analysis(
        include_eth=False,
        usb_address_entries=[_address_entry("usb_only", "0x70000000", 0x1000, bus="apb")],
        usb_clock_reset=_clock_reset_field(
            [{"name": "usb_clk", "frequency_mhz": 60.0, "source": "usb_pll",
              "domain": "usb", "evidence": "USB_SS:usb_clk"}],
            [{"name": "usb_rst_n", "active_level": "low", "synchronous": True,
              "clock": "usb_clk", "clock_resolved": "RESOLVED",
              "evidence": "USB_SS:usb_rst_n"}]))
    address = sta.reconcile_address_maps(clean)
    clock_reset = sta.compare_clock_reset_domains(clean, address_reconciliation=address)
    return address, clock_reset


# ============================================================================
# Vocabulary held to the requirements' own sentences
# ============================================================================

def test_sys31_dimensions_match_the_requirements_own_sentence_one_to_one():
    """SYS-31: "Preserve SYSTEM SCENARIO / SUBSYSTEM / COMMAND / VIP-AGENT /
    RESOURCE / UVM_ERROR / LOG / WAVEFORM / ROOT-CAUSE HYPOTHESIS /
    CONFIDENCE.\""""
    assert sft.SYS31_DIMENSIONS == (
        "system_scenario", "subsystem", "command", "vip_agent", "resource",
        "uvm_error", "log", "waveform", "root_cause_hypothesis", "confidence")
    assert len(sft.SYS31_DIMENSIONS) == 10


def test_sys32_classifications_match_the_requirements_own_sentence_one_to_one():
    """SYS-32: "determine local vs cross-subsystem, shared-resource cause,
    command ordering, duplicate driver, address conflict, clock/reset, or
    genuine SoC integration bug." Seven named outcomes plus UNKNOWN."""
    assert sft.SYS32_CLASSIFICATIONS == (
        "LOCAL_SUBSYSTEM_DEFECT", "SHARED_RESOURCE_CAUSE", "COMMAND_ORDERING_CAUSE",
        "DUPLICATE_DRIVER_CAUSE", "ADDRESS_CONFLICT_CAUSE", "CLOCK_RESET_CAUSE",
        "GENUINE_SOC_INTEGRATION_BUG", "UNKNOWN")


def test_sys32_precedence_puts_named_mechanisms_before_both_residuals():
    assert sorted(sft.SYS32_PRECEDENCE) == sorted(sft.SYS32_CLASSIFICATIONS)
    named = sft.SYS32_PRECEDENCE[:5]
    assert set(named) == {sft.DUPLICATE_DRIVER_CAUSE, sft.ADDRESS_CONFLICT_CAUSE,
                          sft.CLOCK_RESET_CAUSE, sft.SHARED_RESOURCE_CAUSE,
                          sft.COMMAND_ORDERING_CAUSE}
    assert sft.SYS32_PRECEDENCE[-3:] == (sft.GENUINE_SOC_INTEGRATION_BUG,
                                         sft.LOCAL_SUBSYSTEM_DEFECT, sft.TRIAGE_UNKNOWN)


def test_every_named_cause_declares_which_document_decides_it():
    """SYS-32's own instruction is to REUSE existing L5 triage. Each of the
    five mechanism causes must name the upstream requirement that owns it, so
    nothing here can quietly grow a second opinion."""
    declared = {c for c, _, _ in sft.CAUSE_SOURCES}
    assert declared == set(sft.SYS32_PRECEDENCE[:5])


def test_vocabularies_match_the_json_schemas_enums():
    triage_schema = json.loads(sft.SCHEMA_PATH.read_text(encoding="utf-8"))
    props = triage_schema["properties"]
    assert sorted(props["classification"]["enum"]) == sorted(sft.SYS32_CLASSIFICATIONS)
    assert sorted(props["locus"]["enum"]) == sorted(sft.SYS32_LOCUS_VALUES)
    assert props["root_cause_decided"]["const"] is False
    assert props["failures_fixed"]["const"] == 0
    record_schema = json.loads(sft.RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    dimensions = record_schema["properties"]["dimensions"]
    assert dimensions["minItems"] == dimensions["maxItems"] == len(sft.SYS31_DIMENSIONS)
    item = record_schema["properties"]["per_subsystem"]["items"]
    for dimension in sft.SYS31_DIMENSIONS:
        assert dimension in item["required"]
    assert (record_schema["properties"]["summary"]["properties"]
            ["generic_system_failure_records"]["const"] == 0)


def test_no_second_symptom_shape_confidence_scale_or_upstream_derivation():
    """REUSE-FIRST, checked. The symptom shape is memory_vault's, the
    confidence math is inference's, and the five mechanism causes are decided
    by consulting the upstream documents -- this module must define none of
    them again."""
    text = open(sft.__file__, encoding="utf-8").read()
    assert "mv.build_failure_signature(" in text
    assert "mv.search_related_memory_for_debug(" in text
    assert "inference.score_confidence(" in text
    for forbidden in ("def build_failure_signature", "def score_confidence",
                      "def reconcile_address_maps", "def compare_clock_reset_domains",
                      "def build_system_resource_registry",
                      "def classify_parallelism_relationships"):
        assert forbidden not in text


# ============================================================================
# SYS-31 -- SUBSYSTEM FAILURE ISOLATION
# ============================================================================

def test_every_dimension_is_a_distinct_field_never_one_collapsed_string():
    record = _failure("PCIE_SS", command="CPUWRITE4B", resource="REGISTER_BLOCK:1400",
                      vip_agent="pcie_rc_agent")
    for dimension in sft.SYS31_DIMENSIONS:
        assert dimension in record
    assert record["system_scenario"] == SCENARIO
    assert record["subsystem"] == "PCIE_SS"
    assert record["command"] == "CPUWRITE4B"
    assert record["vip_agent"] == "pcie_rc_agent"
    assert record["resource"] == "REGISTER_BLOCK:1400"
    assert record["uvm_error"]["uvm_error_count"] == 1
    assert record["log"].endswith("sim.log")
    assert record["waveform"].endswith(".fsdb")
    assert record["root_cause_hypothesis"] == "synthetic hypothesis"
    assert record["confidence"]["level"] in ("HIGH", "MEDIUM", "LOW")


def test_an_uncaptured_dimension_says_not_captured_rather_than_looking_empty():
    record = _failure("USB_SS")
    assert record["command"] == sft.NOT_CAPTURED
    assert record["vip_agent"] == sft.NOT_CAPTURED
    assert record["resource"] == sft.NOT_CAPTURED


def test_the_symptom_shape_is_memory_vaults_and_carries_the_new_dimensions():
    record = _failure("PCIE_SS", resource="REGISTER_BLOCK:1400", vip_agent="pcie_rc_agent")
    signature = record["failure_signature"]
    expected = mv.build_failure_signature(
        protocol="PCIE", pattern="synthetic_pattern", symptom="synthetic symptom",
        root_cause_hint="synthetic hypothesis", uvm_error_count=1, lsf_status="DONE",
        vip_agent="pcie_rc_agent", resource="REGISTER_BLOCK:1400")
    assert signature == expected
    assert signature["vip_agent"] == "pcie_rc_agent"
    assert signature["resource"] == "REGISTER_BLOCK:1400"


def test_the_default_failure_signature_and_its_key_are_byte_identical_to_before():
    """The regression guard for the additive `vip_agent`/`resource` fields.
    `evidence_db.signature_key()` hashes the WHOLE dict, so a key that were
    always present would silently orphan every accumulated
    occurrence_count/first_seen/last_seen row on the failure_signatures table.
    Omitted-when-absent keeps a caller that supplies neither byte-identical."""
    signature = mv.build_failure_signature(protocol="USB", pattern="p", symptom="s")
    assert set(signature) == {
        "protocol", "pattern", "symptom", "root_cause_hint", "uvm_error_count",
        "uvm_fatal_count", "assertion_failure", "simulator_crash",
        "terminal_signature", "lsf_status", "abnormal_termination", "extra_text"}
    assert evidence_db.signature_key(signature) == evidence_db.signature_key({
        "protocol": "USB", "pattern": "p", "symptom": "s", "root_cause_hint": None,
        "uvm_error_count": 0, "uvm_fatal_count": 0, "assertion_failure": False,
        "simulator_crash": False, "terminal_signature": None, "lsf_status": None,
        "abnormal_termination": False, "extra_text": None})
    # and a supplied vip_agent really is a different failure shape
    assert evidence_db.signature_key(signature) != evidence_db.signature_key(
        mv.build_failure_signature(protocol="USB", pattern="p", symptom="s",
                                   vip_agent="usb_host_agent"))


def test_confidence_comes_from_inference_and_is_never_invented():
    scored = _failure("PCIE_SS")
    assert scored["confidence"]["source"] == "inference.score_confidence()"
    assert scored["confidence"] == dict(
        inference.score_confidence(2, True, 0, 0),
        source="inference.score_confidence()")

    unscored = sft.build_subsystem_failure_record(
        system_scenario_id=SCENARIO, subsystem="USB_SS", uvm_error_count=1)
    assert unscored["confidence"]["level"] == "UNKNOWN"
    assert unscored["confidence"]["source"] == "NOT_SCORED"


def test_a_system_record_keeps_one_sub_record_per_failing_subsystem():
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"), _passing("ETH_SS"))
    assert record["summary"]["subsystem_record_count"] == 3
    assert record["summary"]["failing_subsystems"] == ["PCIE_SS", "USB_SS"]
    assert record["summary"]["generic_system_failure_records"] == 0
    sft.validate_system_failure_record(record)


def test_a_record_missing_a_scenario_id_or_a_subsystem_is_refused():
    with pytest.raises(sft.SystemFailureTriageError) as excinfo:
        sft.build_subsystem_failure_record(system_scenario_id="", subsystem="PCIE_SS")
    assert excinfo.value.reason == "SYSTEM_SCENARIO_ID_REQUIRED"
    with pytest.raises(sft.SystemFailureTriageError) as excinfo:
        sft.build_subsystem_failure_record(system_scenario_id=SCENARIO, subsystem="")
    assert excinfo.value.reason == "SUBSYSTEM_REQUIRED"


def test_two_scenarios_failures_cannot_be_joined_into_one_record():
    other = sft.build_subsystem_failure_record(
        system_scenario_id="SYSSCEN-OTHER", subsystem="USB_SS", uvm_error_count=1)
    with pytest.raises(sft.SystemFailureTriageError) as excinfo:
        sft.build_system_failure_record(SCENARIO, [_failure("PCIE_SS"), other])
    assert excinfo.value.reason == "SCENARIO_ID_MISMATCH"


def test_the_no_collapse_rule_actually_catches_a_collapsed_document():
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"))

    collapsed = json.loads(json.dumps(record))
    collapsed["per_subsystem"] = [collapsed["per_subsystem"][0]]
    with pytest.raises(sft.SystemFailureTriageError) as excinfo:
        sft.assert_not_collapsed(collapsed)
    assert excinfo.value.reason == "FAILING_SUBSYSTEM_WITHOUT_RECORD"

    generic = json.loads(json.dumps(record))
    generic["summary"]["generic_system_failure_records"] = 1
    with pytest.raises(sft.SystemFailureTriageError) as excinfo:
        sft.assert_not_collapsed(generic)
    assert excinfo.value.reason == "GENERIC_SYSTEM_FAILURE_COLLAPSE"

    dropped = json.loads(json.dumps(record))
    del dropped["per_subsystem"][0]["waveform"]
    with pytest.raises(sft.SystemFailureTriageError) as excinfo:
        sft.assert_not_collapsed(dropped)
    assert excinfo.value.reason == "SYS31_DIMENSION_MISSING"


def test_prior_evidence_is_attached_through_the_shared_memory_interface(tmp_path):
    """`search_related_memory_for_debug()` unchanged -- the same interface
    engine.py's FAILURE_RECOVERY stage and lsf_client.py already call. Prior
    evidence only: the root-cause hypothesis must be untouched by it."""
    record = _failure("PCIE_SS")
    before = record["root_cause_hypothesis"]
    sft.attach_prior_evidence(record, tmp_path, {})
    assert record["prior_evidence"]["searched"] is True
    assert isinstance(record["prior_evidence"]["related_cases"], list)
    assert "never an accepted root cause" in record["prior_evidence"]["disclaimer"]
    assert record["root_cause_hypothesis"] == before


# ============================================================================
# SYS-32 -- SYSTEM FAILURE TRIAGE
# ============================================================================

def test_a_failure_on_a_registry_driver_conflict_is_a_duplicate_driver_cause():
    record = _record(_failure("PCIE_SS", resource="SYSRES-CPU-AXI-0001"),
                     _failure("USB_SS", resource="SYSRES-CPU-AXI-0001"))
    triage = sft.triage_system_failure(record, registry=_driver_conflict_registry())
    assert triage["classification"] == sft.DUPLICATE_DRIVER_CAUSE
    assert triage["cited_row"] == "SYSRES-CPU-AXI-0001"
    assert triage["from_source"] == "system_resource_registry"
    assert srr.CONFLICT_DRIVER in triage["basis"]


def test_a_driver_conflict_elsewhere_is_not_attributed_to_an_unrelated_failure():
    """The control that keeps DUPLICATE_DRIVER_CAUSE from firing on any
    selection that happens to contain a conflict somewhere. The link must be
    the failing record's OWN resource value, never a name that merely exists in
    the same registry."""
    record = _record(_failure("PCIE_SS", resource="SYSRES-SOMETHING-ELSE"),
                     _failure("USB_SS", resource="SYSRES-SOMETHING-ELSE"))
    triage = sft.triage_system_failure(record, registry=_driver_conflict_registry())
    assert triage["classification"] != sft.DUPLICATE_DRIVER_CAUSE
    assert not [s for s in triage["signals"]
                if s["classification"] == sft.DUPLICATE_DRIVER_CAUSE]


def test_two_subsystems_failing_on_a_sys28_conflict_is_an_address_conflict_cause():
    address = sta.reconcile_address_maps(_analysis())
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"))
    triage = sft.triage_system_failure(record, address_reconciliation=address)
    assert triage["classification"] == sft.ADDRESS_CONFLICT_CAUSE
    assert triage["cited_row"].startswith("SYSADDR-")
    assert triage["locus"] == sft.LOCUS_CROSS_SUBSYSTEM


def test_an_address_conflict_between_two_subsystems_that_did_not_fail_is_ignored():
    address = sta.reconcile_address_maps(_analysis())
    record = _record(_failure("ETH_SS"), _passing("PCIE_SS"), _passing("USB_SS"))
    triage = sft.triage_system_failure(record, address_reconciliation=address)
    assert triage["classification"] == sft.LOCAL_SUBSYSTEM_DEFECT
    assert triage["locus"] == sft.LOCUS_LOCAL


def test_a_reset_polarity_disagreement_is_a_clock_reset_cause():
    analysis = _analysis()
    clock_reset = sta.compare_clock_reset_domains(
        analysis, address_reconciliation=sta.reconcile_address_maps(analysis))
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"))
    triage = sft.triage_system_failure(record, clock_reset_comparison=clock_reset)
    assert triage["classification"] == sft.CLOCK_RESET_CAUSE
    assert triage["cited_row"].startswith("SYSCR-")


def test_a_failure_naming_a_shared_access_point_resource_is_a_shared_resource_cause(
        tmp_path):
    _, _, scheduling_plan, _ = _plans(tmp_path)
    record = _record(_failure("PCIE_SS", resource="REGISTER_BLOCK:1400"),
                     _failure("USB_SS", resource="REGISTER_BLOCK:1400"))
    triage = sft.triage_system_failure(record, scheduling_plan=scheduling_plan)
    assert triage["classification"] == sft.SHARED_RESOURCE_CAUSE
    assert triage["cited_row"] == "REGISTER_BLOCK:1400"
    assert ssp.ACCESS_POINT_STATUS in triage["basis"]


def test_two_commands_on_a_sys25_order_dependent_pair_are_a_command_ordering_cause(
        tmp_path):
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    record = _record(_failure("PCIE_SS", command="CPUWRITE4B"),
                     _failure("USB_SS", command="`GMODEL.GLOBAL_INIT"))
    triage = sft.triage_system_failure(
        record, scheduling_plan=scheduling_plan, command_plan=command_plan)
    assert triage["classification"] == sft.COMMAND_ORDERING_CAUSE
    ordering = [s for s in triage["signals"]
                if s["classification"] == sft.COMMAND_ORDERING_CAUSE]
    # both evidence axes, SYS-25 and SYS-22, and each cites its own row
    assert {s["from_source"] for s in ordering} == {"scheduling_plan", "command_plan"}


def test_an_ordering_pair_that_does_not_contain_the_failing_commands_is_ignored(
        tmp_path):
    """The control for the whole-name match: a command that merely resembles a
    fragment of a pair's id must not link to it."""
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    record = _record(_failure("PCIE_SS", command="WRITE"),
                     _failure("USB_SS", command="INIT"))
    triage = sft.triage_system_failure(
        record, scheduling_plan=scheduling_plan, command_plan=command_plan)
    assert not [s for s in triage["signals"]
                if s["classification"] == sft.COMMAND_ORDERING_CAUSE]


def test_the_most_specific_mechanism_wins_and_the_losers_survive():
    analysis = _analysis()
    address = sta.reconcile_address_maps(analysis)
    clock_reset = sta.compare_clock_reset_domains(
        analysis, address_reconciliation=address)
    record = _record(_failure("PCIE_SS", resource="SYSRES-CPU-AXI-0001"),
                     _failure("USB_SS", resource="SYSRES-CPU-AXI-0001"))
    triage = sft.triage_system_failure(
        record, registry=_driver_conflict_registry(),
        address_reconciliation=address, clock_reset_comparison=clock_reset)
    assert triage["classification"] == sft.DUPLICATE_DRIVER_CAUSE
    assert sft.ADDRESS_CONFLICT_CAUSE in triage["also_matched"]
    assert sft.CLOCK_RESET_CAUSE in triage["also_matched"]


def test_two_subsystems_failing_with_no_named_mechanism_is_an_integration_bug(tmp_path):
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    address, clock_reset = _clean_address_and_clock()
    record = _record(_failure("PCIE_SS", command="NO_SUCH_COMMAND_A"),
                     _failure("USB_SS", command="NO_SUCH_COMMAND_B"))
    triage = sft.triage_system_failure(
        record, registry=_registry([], subsystems=("PCIE_SS", "USB_SS")),
        address_reconciliation=address, clock_reset_comparison=clock_reset,
        scheduling_plan=scheduling_plan, command_plan=command_plan)
    assert triage["classification"] == sft.GENUINE_SOC_INTEGRATION_BUG
    assert triage["locus"] == sft.LOCUS_CROSS_SUBSYSTEM
    assert triage["sources_not_consulted"] == []
    assert "every named mechanism consulted" in triage["basis"]


def test_one_subsystem_failing_alone_is_a_local_defect(tmp_path):
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    address, clock_reset = _clean_address_and_clock()
    record = _record(_failure("PCIE_SS", command="NO_SUCH_COMMAND_A"),
                     _passing("USB_SS"))
    triage = sft.triage_system_failure(
        record, registry=_registry([], subsystems=("PCIE_SS", "USB_SS")),
        address_reconciliation=address, clock_reset_comparison=clock_reset,
        scheduling_plan=scheduling_plan, command_plan=command_plan)
    assert triage["classification"] == sft.LOCAL_SUBSYSTEM_DEFECT
    assert triage["locus"] == sft.LOCUS_LOCAL
    assert triage["failing_subsystems"] == ["PCIE_SS"]


def test_an_unconsulted_source_is_never_read_as_evidence_for_the_negative():
    """The distinction that keeps a residual honest. With nothing supplied, a
    two-subsystem failure still lands on the residual -- but the residual must
    SAY that four of the five mechanisms were never looked at, or an
    unexamined failure would read exactly like an examined one."""
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"))
    triage = sft.triage_system_failure(record)
    assert triage["classification"] == sft.GENUINE_SOC_INTEGRATION_BUG
    assert set(triage["sources_not_consulted"]) == set(sft.SYS32_PRECEDENCE[:5])
    assert "NOT CONSULTED" in triage["basis"]
    assert all(v == sft.NOT_CONSULTED for v in triage["sources_consulted"].values())


def test_a_record_with_no_failing_sub_record_is_unknown_not_an_integration_bug():
    record = _record(_passing("PCIE_SS"), _passing("USB_SS"))
    triage = sft.triage_system_failure(record)
    assert triage["classification"] == sft.TRIAGE_UNKNOWN
    assert triage["locus"] == sft.LOCUS_UNKNOWN


def test_triage_decides_a_locus_and_never_a_root_cause_or_a_fix():
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"))
    triage = sft.triage_system_failure(record)
    assert triage["root_cause_decided"] is False
    assert triage["failures_fixed"] == 0
    assert triage["failures_waived"] == 0
    assert "not a root cause" in triage["root_cause_note"]
    sft.validate_system_failure_triage(triage)


def test_the_convenience_front_door_unpacks_the_same_four_documents(tmp_path):
    integration_plan, command_plan, scheduling_plan, selection = _plans(tmp_path)
    topology = sta.build_system_topology_analysis(
        _analysis(), integration_plan, command_plan, scheduling_plan,
        selection=selection)
    record = _record(_failure("PCIE_SS"), _failure("USB_SS"))
    triage = sft.triage_from_topology_analysis(
        record, topology, integration_plan, command_plan, scheduling_plan)
    assert all(v == sft.CONSULTED for v in triage["sources_consulted"].values())
    assert triage["classification"] == sft.ADDRESS_CONFLICT_CAUSE
    sft.validate_system_failure_triage(triage)


def test_the_report_shows_every_dimension_and_which_sources_were_consulted():
    address = sta.reconcile_address_maps(_analysis())
    record = _record(_failure("PCIE_SS", command="CPUWRITE4B", vip_agent="pcie_rc_agent",
                              resource="REGISTER_BLOCK:1400"),
                     _failure("USB_SS", command="CPUWRITE4B"))
    triage = sft.triage_system_failure(record, address_reconciliation=address)
    report = sft.format_system_failure_triage_report(record, triage)
    assert "SYS-31 SUBSYSTEM FAILURE ISOLATION" in report
    assert "SYS-32 SYSTEM FAILURE TRIAGE" in report
    assert "pcie_rc_agent" in report and "REGISTER_BLOCK:1400" in report
    assert sft.NOT_CONSULTED in report and sft.CONSULTED in report
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in report
