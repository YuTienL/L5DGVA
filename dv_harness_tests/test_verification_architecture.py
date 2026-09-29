"""Tests for dv_harness/verification_architecture.py.

Every producer this module reads is exercised for REAL: `env_manifest.
build_vip_config()`/`build_vip_release()`/`build_dut_facts_clock_reset()`
against real fixture files on disk, `connectivity.classify_bind_tier()` /
`generate_protocol_check_entry()` / `generate_scoreboard_entry()` for real,
and `phy_boundary.classify_boundary()`/`decide_bind_location()` against a
real synthetic port table. Nothing here hand-builds an IR's underlying
`raw` dict to look like a producer's output without calling that producer.

The 3 standalone generation gates are driven as real subprocesses against
real assembled documents.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import connectivity, env_manifest, phy_boundary, verification_architecture as va

REPO_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = REPO_ROOT / "tools" / "verification_flow"


# ===========================================================================
# fixtures: real producer outputs
# ===========================================================================

@pytest.fixture()
def real_vip_config(tmp_path):
    dump = tmp_path / "vip_config_dump.json"
    dump.write_text(json.dumps({
        "schema_version": "1.0",
        "vip_instances": [
            {"instance_path": "chip.core.usb0.host_vip", "vip_type": "svt_usb3",
             "config_fields": {"speed": "SS"}},
            {"instance_path": "chip.core.usb0.dev_vip", "vip_type": "svt_usb3",
             "config_fields": {"speed": "SS"}},
        ],
    }), encoding="utf-8")
    return env_manifest.build_vip_config(str(dump))


@pytest.fixture()
def real_vip_release(tmp_path):
    home = tmp_path / "designware_home"
    pkg_dir = home / "vip" / "svt" / "svt_usb3" / "R-2023.06"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "svt_usb3_release_notes.txt").write_text("release notes", encoding="utf-8")
    return env_manifest.build_vip_release(designware_home=str(home))


@pytest.fixture()
def real_clock_reset(tmp_path):
    soc_arch_map = tmp_path / "soc_arch_map.json"
    soc_arch_map.write_text(json.dumps({
        "schema_version": "1.0",
        "clocks": [
            {"name": "clk_usb_ref", "frequency_mhz": 125.0, "domain": "usb_clk_domain"},
        ],
        "resets": [
            {"name": "rst_usb_n", "active_level": "low", "clock": "clk_usb_ref"},
        ],
    }), encoding="utf-8")
    return env_manifest.build_dut_facts_clock_reset(str(soc_arch_map))


def _port(name, direction, data_type):
    return {"name": name, "direction": direction, "data_type": data_type}


def _phy_and_controller_modules(mixed=False):
    """A real synthetic PHY/controller module pair for phy_boundary.py:
    a shared PARALLEL data bus (>= PARALLEL_MIN_WIDTH bits) plus, when
    `mixed`, an additional shared SERIAL differential pair -- exactly
    phy_boundary.classify_boundary()'s own documented MIXED/bridge shape."""
    phy_ports = [
        _port("pclk", "input", None),
        _port("pipe_txdata", "output", "logic [7:0]"),
        _port("pipe_rxdata", "input", "logic [7:0]"),
    ]
    ctrl_ports = [
        _port("pclk", "input", None),
        _port("pipe_txdata", "input", "logic [7:0]"),
        _port("pipe_rxdata", "output", "logic [7:0]"),
    ]
    if mixed:
        phy_ports += [_port("txp", "output", "logic"), _port("rxp", "input", "logic")]
        ctrl_ports += [_port("txp", "input", "logic"), _port("rxp", "output", "logic")]
    phy_module = {"name": "usb3_phy", "ports": phy_ports}
    ctrl_module = {"name": "usb3_ctrl", "ports": ctrl_ports}
    return phy_module, ctrl_module


def _real_boundary_decision(mixed=False):
    phy_module, ctrl_module = _phy_and_controller_modules(mixed=mixed)
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    decision = phy_boundary.decide_bind_location(classification, signals)
    return classification, decision


# ===========================================================================
# VipSelectionIR
# ===========================================================================

def test_vip_selection_ir_resolved_from_real_producers(real_vip_config, real_vip_release):
    tier = connectivity.classify_bind_tier(existing_bind={"target": "chip.core.usb0.host_vip"})
    bind_tiers = {"chip.core.usb0.host_vip": tier}
    active_passive = {"chip.core.usb0.host_vip": "ACTIVE", "chip.core.usb0.dev_vip": "PASSIVE"}

    irs = va.build_vip_selection_ir(real_vip_config, real_vip_release, bind_tiers, active_passive)
    assert len(irs) == 2
    host = next(i for i in irs if i.vip_instance_path == "chip.core.usb0.host_vip")
    assert host.bind_tier == "T1_ALREADY_DECIDED"
    assert host.confidence == "HIGH"
    assert host.status == "RESOLVED"
    assert host.release_status == "INSTALLED"
    assert host.release_version == "R-2023.06"
    assert any(e["fact_source"] == "env_manifest.build_vip_config" for e in host.source_evidence)
    assert any(e["fact_source"] == "env_manifest.build_vip_release" for e in host.source_evidence)
    assert any(e["fact_source"] == "connectivity.classify_bind_tier" for e in host.source_evidence)


def test_vip_selection_ir_empty_when_vip_config_not_available():
    """Negative control: absent evidence must never be silently treated as
    a real (empty-but-populated) selection list."""
    not_available = env_manifest.build_vip_config(None)
    assert not_available["status"] == "NOT_AVAILABLE"
    assert va.build_vip_selection_ir(not_available) == []


def test_vip_selection_ir_unclassified_tier_without_bind_tiers(real_vip_config):
    """Negative control: no bind_tiers supplied -> UNCLASSIFIED/UNKNOWN,
    never a guessed HIGH confidence."""
    irs = va.build_vip_selection_ir(real_vip_config)
    assert all(i.bind_tier == connectivity.BIND_TIER_UNCLASSIFIED for i in irs)
    assert all(i.confidence == "UNKNOWN" for i in irs)


def test_vip_selection_ir_release_not_available_when_package_not_installed(real_vip_config):
    empty_release = env_manifest.build_vip_release(designware_home=None)
    assert empty_release["status"] == "NOT_AVAILABLE"
    irs = va.build_vip_selection_ir(real_vip_config, empty_release)
    assert all(i.release_status == "NOT_AVAILABLE" and i.release_version is None for i in irs)


# ===========================================================================
# VipBindIR + wrapper/bridge chain
# ===========================================================================

def test_derive_wrapper_bridge_chain_classifies_real_boundary_evidence():
    parallel_classification, _ = _real_boundary_decision(mixed=False)
    mixed_classification, _ = _real_boundary_decision(mixed=True)
    assert parallel_classification["kind"] == "PARALLEL"
    assert mixed_classification["kind"] == "MIXED"

    hops = [
        {"instance": "chip.core.usb0.wrap", "module": "usb3_ctrl",
         "boundary_classification": parallel_classification},
        {"instance": "chip.core.usb0.bridge", "module": "usb3_phy",
         "boundary_classification": mixed_classification},
    ]
    chain = va.derive_wrapper_bridge_chain(hops)
    assert [h["role"] for h in chain] == ["WRAPPER", "BRIDGE"]


def test_derive_wrapper_bridge_chain_unclassified_without_evidence():
    """Negative control: no boundary evidence for a hop -> UNCLASSIFIED,
    never guessed from the module/instance name (Bind-Location Rule 5
    discipline extended to a whole chain)."""
    chain = va.derive_wrapper_bridge_chain([{"instance": "chip.x.bridge_thing", "module": "looks_like_a_bridge"}])
    assert chain[0]["role"] == "UNCLASSIFIED"


def test_vip_bind_ir_bridge_in_path_from_real_boundary_decision():
    _, decision = _real_boundary_decision(mixed=False)
    mixed_classification, _ = _real_boundary_decision(mixed=True)
    bind_entries = [{"target_instance": "chip.core.usb0.phy_ctrl_if",
                      "ports": ["pipe_txdata", "pipe_rxdata"], "reason": "structural match",
                      "tier": "T2_STRUCTURAL_MATCH"}]
    boundary_by_target = {"chip.core.usb0.phy_ctrl_if": decision}
    chain_by_target = {"chip.core.usb0.phy_ctrl_if": [
        {"instance": "chip.core.usb0.bridge", "module": "usb3_phy",
         "boundary_classification": mixed_classification},
    ]}
    irs = va.build_vip_bind_ir(bind_entries, boundary_by_target, chain_by_target)
    assert len(irs) == 1
    b = irs[0]
    assert b.chain_classification == "BRIDGE_IN_PATH"
    assert b.bindable is True
    assert b.status == "RESOLVED"
    assert b.confidence == "HIGH"
    assert b.raw["ports"] == ["pipe_txdata", "pipe_rxdata"]  # raw shape preserved verbatim


def test_vip_bind_ir_direct_when_no_chain_declared():
    _, decision = _real_boundary_decision(mixed=False)
    bind_entries = [{"target_instance": "chip.core.usb0.phy_ctrl_if", "ports": [], "reason": "r",
                      "tier": "T1_ALREADY_DECIDED"}]
    irs = va.build_vip_bind_ir(bind_entries, {"chip.core.usb0.phy_ctrl_if": decision})
    assert irs[0].chain_classification == "DIRECT"


def test_vip_bind_ir_unknown_without_any_boundary_or_chain_evidence():
    """Negative control: no boundary and no chain supplied -> UNKNOWN
    status, never a fabricated RESOLVED."""
    irs = va.build_vip_bind_ir([{"target_instance": "chip.x.y", "ports": [], "reason": "r"}])
    assert irs[0].status == "UNKNOWN"
    assert irs[0].boundary_kind == "NOT_EVALUATED"


# ===========================================================================
# CheckerIR / ScoreboardIR extending the real connectivity.py generators
# ===========================================================================

def test_checker_ir_extends_real_protocol_check_entry():
    entry = connectivity.generate_protocol_check_entry(
        "chip.core.usb0::axi_if", "svt_axi", ["parity_check", "protocol_check"],
        {"parity_check": "disabled per project waiver W-12"},
    )
    checker_links = {"chip.core.usb0::axi_if": {"target_instance": "chip.core.usb0.axi_if",
                                                 "mount_side": "POST_BRIDGE"}}
    irs = va.build_checker_ir([entry], checker_links)
    assert len(irs) == 1
    c = irs[0]
    assert c.raw["kind"] == "protocol_check"
    assert c.raw["enabled_builtin_checks"] == ["protocol_check"]
    assert c.target_instance == "chip.core.usb0.axi_if"
    assert c.mount_side == "POST_BRIDGE"
    assert c.status == "RESOLVED"


def test_checker_ir_partial_when_unlinked():
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["c1"], {})
    irs = va.build_checker_ir([entry])
    assert irs[0].status == "UNKNOWN"
    assert irs[0].target_instance is None


def test_checker_ir_rejects_unknown_mount_side():
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["c1"], {})
    with pytest.raises(va.VerificationArchitectureError):
        va.build_checker_ir([entry], {"row1": {"target_instance": "x", "mount_side": "SIDEWAYS"}})


def test_scoreboard_ir_extends_real_generate_scoreboard_entry_and_reports_unfilled():
    entry = connectivity.generate_scoreboard_entry(
        "sb_apb_to_axi", [("chip.core.usb0.apb_if", "chip.core.usb0.axi_if")], "addr",
    )
    irs = va.build_scoreboard_ir([entry])
    sb = irs[0]
    # matching_key was supplied, ordering/legal_drop/etc were not -> real
    # unfilled fields carried through from connectivity.unfilled_plan_fields
    assert "ordering" in sb.unfilled_fields
    assert "matching_key" not in sb.unfilled_fields
    assert sb.status == "PARTIAL"
    assert sb.comparable is None
    assert sb.raw["scoreboard_id"] == "sb_apb_to_axi"


def test_scoreboard_comparability_true_with_agreeing_real_boundary_evidence():
    parallel_classification, _ = _real_boundary_decision(mixed=False)
    entry = connectivity.generate_scoreboard_entry(
        "sb1", [("chip.core.usb0.apb_if", "chip.core.usb0.axi_if")], "addr",
        ordering="in_order", ordering_tolerance_depth=0, transformation_rules=[],
        legal_drop_conditions="none", reset_flush_behavior="flush_on_reset",
        orphan_threshold=0, orphan_timeout="0ns",
    )
    boundary_by_endpoint = {"chip.core.usb0.apb_if": parallel_classification,
                             "chip.core.usb0.axi_if": parallel_classification}
    irs = va.build_scoreboard_ir([entry], boundary_by_endpoint)
    assert irs[0].comparable is True
    assert irs[0].status == "RESOLVED"
    assert irs[0].confidence == "HIGH"


def test_scoreboard_comparability_false_with_disagreeing_real_boundary_evidence():
    """Negative control: real disagreeing boundary-kind evidence for the
    two endpoints must flip comparable to False, never stay silently True."""
    parallel_classification, _ = _real_boundary_decision(mixed=False)
    serial_only = {"kind": "SERIAL", "tier": "B2_STRUCTURAL_WIDTH", "rationale": "r",
                   "serial_signals": ["txp"], "parallel_signals": [], "unresolved_width_signals": []}
    entry = connectivity.generate_scoreboard_entry(
        "sb2", [("chip.core.usb0.apb_if", "chip.core.usb0.serial_if")], "addr",
        ordering="in_order", ordering_tolerance_depth=0, transformation_rules=[],
        legal_drop_conditions="none", reset_flush_behavior="flush_on_reset",
        orphan_threshold=0, orphan_timeout="0ns",
    )
    boundary_by_endpoint = {"chip.core.usb0.apb_if": parallel_classification,
                             "chip.core.usb0.serial_if": serial_only}
    irs = va.build_scoreboard_ir([entry], boundary_by_endpoint)
    assert irs[0].comparable is False
    assert irs[0].confidence == "LOW"


# ===========================================================================
# AssertionIR against a real clock_reset layer
# ===========================================================================

def test_assertion_ir_matches_real_clock_and_reset_domain(real_clock_reset):
    candidate = {"assertion_id": "A1", "target_signal": "req", "target_instance": "chip.core.usb0.axi_if",
                 "clock_domain": "usb_clk_domain", "reset_domain": "usb_clk_domain"}
    irs = va.build_assertion_ir([candidate], real_clock_reset)
    a = irs[0]
    assert a.clock_domain_match is True
    assert a.reset_domain_match is True
    assert a.status == "RESOLVED"
    assert a.confidence == "HIGH"


def test_assertion_ir_wrong_clock_domain_is_a_real_negative_control(real_clock_reset):
    candidate = {"assertion_id": "A2", "target_instance": "chip.core.usb0.axi_if",
                 "clock_domain": "clk_that_does_not_exist", "reset_domain": "usb_clk_domain"}
    irs = va.build_assertion_ir([candidate], real_clock_reset)
    assert irs[0].clock_domain_match is False
    assert irs[0].status == "PARTIAL"
    assert irs[0].confidence == "LOW"


def test_assertion_ir_unknown_when_clock_reset_layer_not_loaded():
    """Negative control: absent clock/reset evidence must never be graded
    as either a pass or a fail -- it is UNKNOWN with a real reason."""
    not_available = env_manifest.build_dut_facts_clock_reset(None)
    candidate = {"assertion_id": "A3", "clock_domain": "anything", "reset_domain": "anything"}
    irs = va.build_assertion_ir([candidate], not_available)
    a = irs[0]
    assert a.clock_domain_match is None
    assert a.reset_domain_match is None
    assert a.confidence == "UNKNOWN"


# ===========================================================================
# detect_placement_conflicts()
# ===========================================================================

def _bridge_bind_and_vip_after_it():
    _, decision = _real_boundary_decision(mixed=False)
    mixed_classification, _ = _real_boundary_decision(mixed=True)
    bind_entries = [{"target_instance": "chip.core.usb0.phy_ctrl_if", "ports": [], "reason": "r",
                      "tier": "T2_STRUCTURAL_MATCH"}]
    chain_by_target = {"chip.core.usb0.phy_ctrl_if": [
        {"instance": "chip.core.usb0.bridge", "module": "usb3_phy",
         "boundary_classification": mixed_classification},
    ]}
    vip_binds = va.build_vip_bind_ir(bind_entries, {"chip.core.usb0.phy_ctrl_if": decision}, chain_by_target)
    return vip_binds


def test_vip_after_bridge_conflict_detected():
    vip_binds = _bridge_bind_and_vip_after_it()
    vip_config = {"status": "CAPTURED", "vip_instances": [
        {"instance_path": "chip.core.usb0.phy_ctrl_if.monitor_vip", "vip_type": "svt_usb3", "config_fields": {}},
    ]}
    vip_selections = va.build_vip_selection_ir(vip_config)
    findings = va.detect_placement_conflicts(vip_selections=vip_selections, vip_binds=vip_binds)
    kinds = [f["kind"] for f in findings]
    assert "VIP_AFTER_BRIDGE" in kinds


def test_no_vip_after_bridge_conflict_when_vip_is_elsewhere():
    """Negative control: a VIP instance NOT under the bridge-crossing bind
    target must not be flagged."""
    vip_binds = _bridge_bind_and_vip_after_it()
    vip_config = {"status": "CAPTURED", "vip_instances": [
        {"instance_path": "chip.core.usb1.unrelated_vip", "vip_type": "svt_usb3", "config_fields": {}},
    ]}
    vip_selections = va.build_vip_selection_ir(vip_config)
    findings = va.detect_placement_conflicts(vip_selections=vip_selections, vip_binds=vip_binds)
    assert not any(f["kind"] == "VIP_AFTER_BRIDGE" for f in findings)


def test_checker_wrong_side_of_bridge_conflict_detected():
    vip_binds = _bridge_bind_and_vip_after_it()
    entry = connectivity.generate_protocol_check_entry("row1", "svt_usb3", ["c1"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.phy_ctrl_if",
                                                        "mount_side": "PRE_BRIDGE"}})
    findings = va.detect_placement_conflicts(vip_binds=vip_binds, checkers=checkers)
    assert any(f["kind"] == "CHECKER_WRONG_SIDE_OF_BRIDGE" for f in findings)


def test_checker_correct_side_of_bridge_is_not_a_conflict():
    """Negative control: the same bridge-crossing bind with mount_side
    correctly declared POST_BRIDGE must not be flagged."""
    vip_binds = _bridge_bind_and_vip_after_it()
    entry = connectivity.generate_protocol_check_entry("row1", "svt_usb3", ["c1"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.phy_ctrl_if",
                                                        "mount_side": "POST_BRIDGE"}})
    findings = va.detect_placement_conflicts(vip_binds=vip_binds, checkers=checkers)
    assert not any(f["kind"] == "CHECKER_WRONG_SIDE_OF_BRIDGE" for f in findings)


def test_assertion_wrong_clock_and_reset_domain_conflicts(real_clock_reset):
    candidate = {"assertion_id": "A4", "clock_domain": "bogus_clk", "reset_domain": "bogus_rst"}
    assertions = va.build_assertion_ir([candidate], real_clock_reset)
    findings = va.detect_placement_conflicts(assertions=assertions)
    kinds = {f["kind"] for f in findings}
    assert "ASSERTION_WRONG_CLOCK_DOMAIN" in kinds
    assert "WRONG_RESET_DOMAIN" in kinds


def test_scoreboard_not_comparable_conflict_detected():
    parallel_classification, _ = _real_boundary_decision(mixed=False)
    serial_only = {"kind": "SERIAL", "tier": "B2_STRUCTURAL_WIDTH", "rationale": "r",
                   "serial_signals": ["txp"], "parallel_signals": [], "unresolved_width_signals": []}
    entry = connectivity.generate_scoreboard_entry(
        "sb3", [("chip.x.a", "chip.x.b")], "addr", ordering="o", ordering_tolerance_depth=0,
        transformation_rules=[], legal_drop_conditions="none", reset_flush_behavior="f",
        orphan_threshold=0, orphan_timeout="0ns",
    )
    scoreboards = va.build_scoreboard_ir(
        [entry], {"chip.x.a": parallel_classification, "chip.x.b": serial_only})
    findings = va.detect_placement_conflicts(scoreboards=scoreboards)
    assert any(f["kind"] == "SCOREBOARD_INPUTS_NOT_COMPARABLE" for f in findings)


def test_duplicate_active_vip_conflict_detected():
    vip_config = {"status": "CAPTURED", "vip_instances": [
        {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb3", "config_fields": {}},
        {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb2", "config_fields": {}},
    ]}
    active_passive = {"chip.core.usb0.if0": "ACTIVE"}
    vip_selections = va.build_vip_selection_ir(vip_config, active_passive_by_instance=active_passive)
    findings = va.detect_placement_conflicts(vip_selections=vip_selections)
    assert any(f["kind"] == "DUPLICATE_ACTIVE_VIP" for f in findings)


def test_duplicate_passive_vip_is_not_a_conflict():
    """Negative control: two PASSIVE monitors on the same path is a normal
    shape, not a conflict."""
    vip_config = {"status": "CAPTURED", "vip_instances": [
        {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb3", "config_fields": {}},
        {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb2", "config_fields": {}},
    ]}
    vip_selections = va.build_vip_selection_ir(
        vip_config, active_passive_by_instance={})  # explicitly nothing declared for either
    # Force both declarations to PASSIVE for the negative control.
    for v in vip_selections:
        v.active_passive = "PASSIVE"
    findings = va.detect_placement_conflicts(vip_selections=vip_selections)
    assert not any(f["kind"] == "DUPLICATE_ACTIVE_VIP" for f in findings)


# ===========================================================================
# Named per-protocol-domain checker-placement rules (CSR + Interrupt/DMA/
# State/Timing) -- CHECKER_DOMAIN_PLACEMENT_RULES /
# check_checker_domain_placement()
# ===========================================================================

def test_checker_domain_placement_rules_cover_exactly_five_named_domains():
    assert va.CHECKER_DOMAINS == ("REGISTER_CSR", "INTERRUPT", "DMA", "STATE", "TIMING")
    # Every rule names a distinct finding kind, and every one of those kinds
    # is registered in the closed PLACEMENT_CONFLICT_KINDS vocabulary --
    # never a rule whose own kind `_finding()` would reject.
    kinds = {rule["finding_kind"] for rule in va.CHECKER_DOMAIN_PLACEMENT_RULES.values()}
    assert kinds == {
        "CSR_CHECKER_WRONG_TARGET_DOMAIN", "INTERRUPT_CHECKER_WRONG_TARGET_DOMAIN",
        "DMA_CHECKER_WRONG_TARGET_DOMAIN", "STATE_CHECKER_WRONG_TARGET_DOMAIN",
        "TIMING_CHECKER_WRONG_TARGET_DOMAIN",
    }
    assert kinds <= set(va.PLACEMENT_CONFLICT_KINDS)


def test_checker_ir_carries_declared_checker_domain():
    entry = connectivity.generate_protocol_check_entry("row1", "svt_csr", ["w1c_check"], {})
    checkers = va.build_checker_ir([entry], {"row1": {
        "target_instance": "chip.core.usb0.csr_if", "mount_side": "POST_BRIDGE",
        "checker_domain": "REGISTER_CSR",
    }})
    c = checkers[0]
    assert c.checker_domain == "REGISTER_CSR"
    assert c.to_dict()["checker_domain"] == "REGISTER_CSR"


def test_checker_domain_defaults_to_none_when_undeclared():
    """Negative control: an ordinary checker_links entry that never
    mentions checker_domain must never be given one -- absent, not
    defaulted to any of the five names."""
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["c1"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.axi_if",
                                                        "mount_side": "POST_BRIDGE"}})
    assert checkers[0].checker_domain is None
    assert checkers[0].status == "RESOLVED"  # unaffected by the new, optional field


def test_checker_ir_rejects_unknown_checker_domain():
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["c1"], {})
    with pytest.raises(va.VerificationArchitectureError):
        va.build_checker_ir([entry], {"row1": {"target_instance": "x", "checker_domain": "GALACTIC"}})


def _domain_checker(domain, target="chip.core.usb0.iface"):
    entry = connectivity.generate_protocol_check_entry("row1", "svt_x", ["c1"], {})
    return va.build_checker_ir([entry], {"row1": {
        "target_instance": target, "mount_side": "POST_BRIDGE", "checker_domain": domain,
    }})


@pytest.mark.parametrize("domain,expected_kind", [
    ("REGISTER_CSR", "CSR_CHECKER_WRONG_TARGET_DOMAIN"),
    ("INTERRUPT", "INTERRUPT_CHECKER_WRONG_TARGET_DOMAIN"),
    ("DMA", "DMA_CHECKER_WRONG_TARGET_DOMAIN"),
    ("STATE", "STATE_CHECKER_WRONG_TARGET_DOMAIN"),
    ("TIMING", "TIMING_CHECKER_WRONG_TARGET_DOMAIN"),
])
def test_checker_domain_placement_mismatch_detected_for_each_named_rule(domain, expected_kind):
    checkers = _domain_checker(domain)
    # every other declared domain disagrees -- pick one deterministically
    wrong_target_domain = next(d for d in va.CHECKER_DOMAINS if d != domain)
    findings = va.check_checker_domain_placement(
        checkers, {"chip.core.usb0.iface": wrong_target_domain})
    assert len(findings) == 1
    f = findings[0]
    assert f["kind"] == expected_kind
    assert f["checker_domain"] == domain
    assert f["target_domain"] == wrong_target_domain
    # also reachable through the composed comparator
    findings2 = va.detect_placement_conflicts(
        checkers=checkers, target_domain_by_instance={"chip.core.usb0.iface": wrong_target_domain})
    assert any(x["kind"] == expected_kind for x in findings2)


@pytest.mark.parametrize("domain", list(va.CHECKER_DOMAINS))
def test_checker_domain_placement_agreement_is_not_a_conflict(domain):
    """Negative control: a checker whose declared domain matches its
    target's declared domain must never be flagged, for any of the five
    named rules."""
    checkers = _domain_checker(domain)
    findings = va.check_checker_domain_placement(checkers, {"chip.core.usb0.iface": domain})
    assert findings == []


def test_csr_checker_correctly_placed_on_the_real_csr_target_is_not_flagged():
    """The task's own headline example: a register/CSR checker mounted on
    the real CSR bus target must be clean."""
    checkers = _domain_checker("REGISTER_CSR", target="chip.core.usb0.apb_csr_if")
    findings = va.detect_placement_conflicts(
        checkers=checkers,
        target_domain_by_instance={"chip.core.usb0.apb_csr_if": "REGISTER_CSR"},
    )
    assert findings == []


def test_checker_domain_placement_unresolved_without_target_domain_evidence():
    """Negative control: a declared checker_domain with NO
    target_domain_by_instance entry for its target is UNRESOLVED, not a
    guessed pass or a guessed conflict -- it produces no finding at all."""
    checkers = _domain_checker("REGISTER_CSR")
    findings = va.check_checker_domain_placement(checkers, target_domain_by_instance=None)
    assert findings == []
    findings2 = va.check_checker_domain_placement(checkers, {"some.other.target": "REGISTER_CSR"})
    assert findings2 == []


def test_checker_domain_placement_never_fires_without_a_declared_checker_domain():
    """Negative control: an ordinary checker with no declared
    checker_domain is never swept into a domain-placement finding, even
    when target_domain_by_instance carries an entry for its target."""
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["c1"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.axi_if",
                                                        "mount_side": "POST_BRIDGE"}})
    findings = va.detect_placement_conflicts(
        checkers=checkers, target_domain_by_instance={"chip.core.usb0.axi_if": "INTERRUPT"})
    assert findings == []


def test_checker_domain_placement_evidence_cites_both_declared_facts():
    checkers = _domain_checker("REGISTER_CSR")
    findings = va.check_checker_domain_placement(checkers, {"chip.core.usb0.iface": "DMA"})
    fact_sources = {e["fact_source"] for e in findings[0]["evidence"]}
    assert "caller_declared_checker_link" in fact_sources
    assert "caller_declared_target_domain" in fact_sources


def test_assemble_verification_architecture_carries_checker_domain_through_schema(
    real_vip_config, real_vip_release, real_clock_reset,
):
    """checker_domain must round-trip through the full assembly and still
    validate against verification_architecture.schema.json, and a real
    domain mismatch must surface as a real CSR_CHECKER_WRONG_TARGET_DOMAIN
    finding in the assembled document."""
    tier = connectivity.classify_bind_tier(existing_bind={"target": "chip.core.usb0.host_vip"})
    check_entry = connectivity.generate_protocol_check_entry(
        "chip.core.usb0::csr_if", "svt_csr", ["w1c_check"], {})
    doc = va.assemble_verification_architecture(
        vip_config=real_vip_config, vip_release=real_vip_release,
        protocol_check_entries=[check_entry],
        checker_links={"chip.core.usb0::csr_if": {
            "target_instance": "chip.core.usb0.csr_if", "mount_side": "POST_BRIDGE",
            "checker_domain": "REGISTER_CSR",
        }},
        target_domain_by_instance={"chip.core.usb0.csr_if": "DMA"},
        clock_reset=real_clock_reset,
    )
    to_validate = {k: v for k, v in doc.items() if k != "_irs"}
    va.validate_verification_architecture(to_validate)  # raises on failure
    assert doc["checker"][0]["checker_domain"] == "REGISTER_CSR"
    assert any(f["kind"] == "CSR_CHECKER_WRONG_TARGET_DOMAIN" for f in doc["placement_conflicts"])


# ===========================================================================
# detect_intra_subsystem_duplicates()
# ===========================================================================

def test_vip_checker_duplicates_sva_detected():
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["no_x_on_valid"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.axi_if",
                                                        "mount_side": "POST_BRIDGE"}})
    assertions = va.build_assertion_ir([
        {"assertion_id": "A5", "target_instance": "chip.core.usb0.axi_if", "checked_property": "no_x_on_valid"},
    ])
    findings = va.detect_intra_subsystem_duplicates(checkers=checkers, assertions=assertions)
    assert any(f["kind"] == "VIP_CHECKER_DUPLICATES_SVA" for f in findings)


def test_no_duplicate_sva_when_properties_differ():
    """Negative control: different checked properties on the same target
    must not be flagged as a duplicate."""
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["parity_check"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.axi_if",
                                                        "mount_side": "POST_BRIDGE"}})
    assertions = va.build_assertion_ir([
        {"assertion_id": "A6", "target_instance": "chip.core.usb0.axi_if", "checked_property": "no_x_on_valid"},
    ])
    findings = va.detect_intra_subsystem_duplicates(checkers=checkers, assertions=assertions)
    assert not any(f["kind"] == "VIP_CHECKER_DUPLICATES_SVA" for f in findings)


def test_scoreboard_duplicates_checker_detected():
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["data_integrity_check"], {})
    checkers = va.build_checker_ir([entry], {"row1": {"target_instance": "chip.core.usb0.axi_if",
                                                        "mount_side": "POST_BRIDGE"}})
    sb_entry = connectivity.generate_scoreboard_entry(
        "sb4", [("chip.core.usb0.axi_if", "chip.core.usb0.apb_if")], "addr",
    )
    scoreboards = va.build_scoreboard_ir([sb_entry])
    findings = va.detect_intra_subsystem_duplicates(checkers=checkers, scoreboards=scoreboards)
    assert any(f["kind"] == "SCOREBOARD_DUPLICATES_CHECKER" for f in findings)


def test_duplicate_scoreboard_path_detected():
    e1 = connectivity.generate_scoreboard_entry("sb5", [("chip.x.a", "chip.x.b")], "addr")
    e2 = connectivity.generate_scoreboard_entry("sb6", [("chip.x.a", "chip.x.b")], "addr")
    scoreboards = va.build_scoreboard_ir([e1, e2])
    findings = va.detect_intra_subsystem_duplicates(scoreboards=scoreboards)
    assert any(f["kind"] == "DUPLICATE_SCOREBOARD_PATH" for f in findings)


def test_no_duplicate_scoreboard_path_when_endpoints_differ():
    """Negative control."""
    e1 = connectivity.generate_scoreboard_entry("sb7", [("chip.x.a", "chip.x.b")], "addr")
    e2 = connectivity.generate_scoreboard_entry("sb8", [("chip.x.c", "chip.x.d")], "addr")
    scoreboards = va.build_scoreboard_ir([e1, e2])
    findings = va.detect_intra_subsystem_duplicates(scoreboards=scoreboards)
    assert not any(f["kind"] == "DUPLICATE_SCOREBOARD_PATH" for f in findings)


# ===========================================================================
# vocabulary / fail-closed discipline
# ===========================================================================

def test_invalid_status_value_raises():
    with pytest.raises(va.VerificationArchitectureError):
        va.VipSelectionIR(raw={"instance_path": "x", "vip_type": "y"}, bind_tier="UNCLASSIFIED",
                          release_status="NOT_AVAILABLE", release_version=None, active_passive=None,
                          status="MOSTLY_FINE", confidence="HIGH", source_evidence=[])


def test_invalid_confidence_value_raises():
    with pytest.raises(va.VerificationArchitectureError):
        va.VipSelectionIR(raw={"instance_path": "x", "vip_type": "y"}, bind_tier="UNCLASSIFIED",
                          release_status="NOT_AVAILABLE", release_version=None, active_passive=None,
                          status="UNKNOWN", confidence="VERY_SURE", source_evidence=[])


def test_unrecognized_finding_kind_rejected_internally():
    with pytest.raises(va.VerificationArchitectureError):
        va._finding("NOT_A_REAL_KIND", severity="HIGH", summary="s", evidence=[])


# ===========================================================================
# rendering
# ===========================================================================

def test_render_functions_produce_markdown_tables():
    vip_binds = _bridge_bind_and_vip_after_it()
    assert "phy_ctrl_if" in va.render_vip_bind_matrix(vip_binds)
    assert va.render_vip_bind_matrix([]) == "(empty connectivity matrix)" or "no VIP binds" in va.render_vip_bind_matrix([])
    assert "Interface" in va.render_interface_to_verification_matrix(vip_binds, [], [], [])
    entry = connectivity.generate_protocol_check_entry("row1", "svt_axi", ["c1"], {})
    checkers = va.build_checker_ir([entry])
    assert "row1" in va.render_function_to_checker_matrix(checkers)
    candidate = {"assertion_id": "A7", "clock_domain": "clk"}
    assertions = va.build_assertion_ir([candidate])
    assert "A7" in va.render_assertion_placement_matrix(assertions)
    sb_entry = connectivity.generate_scoreboard_entry("sb9", [("chip.x.a", "chip.x.b")], "addr")
    scoreboards = va.build_scoreboard_ir([sb_entry])
    assert "sb9" in va.render_scoreboard_architecture_matrix(scoreboards)


# ===========================================================================
# assemble_verification_architecture() + schema validation
# ===========================================================================

def _complete_architecture_doc(real_vip_config, real_vip_release, real_clock_reset):
    tier = connectivity.classify_bind_tier(existing_bind={"target": "chip.core.usb0.host_vip"})
    _, decision = _real_boundary_decision(mixed=False)
    bind_entries = [{"target_instance": "chip.core.usb0.host_vip", "ports": ["pipe_txdata"], "reason": "r",
                      "tier": tier}]
    check_entry = connectivity.generate_protocol_check_entry("chip.core.usb0::axi_if", "svt_usb3", ["c1"], {})
    sb_entry = connectivity.generate_scoreboard_entry(
        "sb_main", [("chip.core.usb0.apb_if", "chip.core.usb0.axi_if")], "addr",
        ordering="in_order", ordering_tolerance_depth=0, transformation_rules=[],
        legal_drop_conditions="none", reset_flush_behavior="flush_on_reset",
        orphan_threshold=0, orphan_timeout="0ns",
    )
    assertion_candidate = {"assertion_id": "A_MAIN", "target_instance": "chip.core.usb0.axi_if",
                            "clock_domain": "usb_clk_domain", "reset_domain": "usb_clk_domain"}
    return va.assemble_verification_architecture(
        vip_config=real_vip_config, vip_release=real_vip_release,
        bind_tiers={"chip.core.usb0.host_vip": tier},
        active_passive_by_instance={"chip.core.usb0.host_vip": "ACTIVE", "chip.core.usb0.dev_vip": "PASSIVE"},
        bind_entries=bind_entries, boundary_by_target={"chip.core.usb0.host_vip": decision},
        protocol_check_entries=[check_entry],
        checker_links={"chip.core.usb0::axi_if": {"target_instance": "chip.core.usb0.axi_if",
                                                    "mount_side": "POST_BRIDGE"}},
        scoreboard_entries=[sb_entry],
        assertion_candidates=[assertion_candidate], clock_reset=real_clock_reset,
    )


def test_assemble_verification_architecture_validates_against_schema(
    real_vip_config, real_vip_release, real_clock_reset,
):
    doc = _complete_architecture_doc(real_vip_config, real_vip_release, real_clock_reset)
    to_validate = {k: v for k, v in doc.items() if k != "_irs"}
    va.validate_verification_architecture(to_validate)  # raises on failure
    assert doc["schema_version"] == "1.0"
    assert len(doc["vip_selection"]) == 2
    assert len(doc["vip_bind"]) == 1
    assert "vip_bind" in doc["matrices"]


def test_validate_verification_architecture_rejects_broken_document():
    broken = {"schema_version": "1.0", "vip_selection": "not-a-list", "vip_bind": [], "checker": [],
              "scoreboard": [], "assertion": [], "placement_conflicts": [], "intra_subsystem_duplicates": [],
              "matrices": {"vip_bind": "", "interface_to_verification": "", "function_to_checker": "",
                           "assertion_placement": "", "scoreboard_architecture": ""}}
    with pytest.raises(va.VerificationArchitectureValidationError):
        va.validate_verification_architecture(broken)


def test_assemble_with_no_inputs_returns_all_empty():
    doc = va.assemble_verification_architecture()
    for key in ("vip_selection", "vip_bind", "checker", "scoreboard", "assertion",
                "placement_conflicts", "intra_subsystem_duplicates"):
        assert doc[key] == []


# ===========================================================================
# 3 standalone generation gate scripts, driven as real subprocesses
# ===========================================================================

def _run_gate(script_name, architecture_path):
    result = subprocess.run(
        [sys.executable, str(GATES_DIR / script_name), "--architecture", str(architecture_path)],
        capture_output=True, text=True,
    )
    return result.returncode, json.loads(result.stdout)


def test_vip_bind_generation_gate_pass_and_fail(tmp_path, real_vip_config, real_vip_release, real_clock_reset):
    doc = _complete_architecture_doc(real_vip_config, real_vip_release, real_clock_reset)
    clean = {k: v for k, v in doc.items() if k != "_irs"}
    path = tmp_path / "arch.json"
    path.write_text(json.dumps(clean), encoding="utf-8")
    code, out = _run_gate("vip_bind_generation_gate.py", path)
    assert code == 0 and out["status"] == "PASS"

    # Negative control: make the single vip_bind record PARTIAL.
    broken = json.loads(json.dumps(clean))
    broken["vip_bind"][0]["status"] = "PARTIAL"
    path2 = tmp_path / "arch_broken.json"
    path2.write_text(json.dumps(broken), encoding="utf-8")
    code2, out2 = _run_gate("vip_bind_generation_gate.py", path2)
    assert code2 == 2 and out2["status"] == "FAIL"


def test_scoreboard_generation_gate_pass_and_fail(tmp_path, real_vip_config, real_vip_release, real_clock_reset):
    doc = _complete_architecture_doc(real_vip_config, real_vip_release, real_clock_reset)
    clean = {k: v for k, v in doc.items() if k != "_irs"}
    # The main fixture's scoreboard is deliberately PARTIAL (no boundary
    # evidence supplied) -- so first assert the gate correctly FAILs on it,
    # then construct a genuinely RESOLVED scoreboard for the PASS case.
    path = tmp_path / "arch.json"
    path.write_text(json.dumps(clean), encoding="utf-8")
    code, out = _run_gate("scoreboard_generation_gate.py", path)
    assert code == 2 and out["status"] == "FAIL"

    parallel_classification, _ = _real_boundary_decision(mixed=False)
    sb_entry = connectivity.generate_scoreboard_entry(
        "sb_ready", [("chip.x.a", "chip.x.b")], "addr", ordering="in_order", ordering_tolerance_depth=0,
        transformation_rules=[], legal_drop_conditions="none", reset_flush_behavior="f",
        orphan_threshold=0, orphan_timeout="0ns",
    )
    scoreboards = va.build_scoreboard_ir(
        [sb_entry], {"chip.x.a": parallel_classification, "chip.x.b": parallel_classification})
    ready = dict(clean)
    ready["scoreboard"] = [s.to_dict() for s in scoreboards]
    path2 = tmp_path / "arch_ready.json"
    path2.write_text(json.dumps(ready), encoding="utf-8")
    code2, out2 = _run_gate("scoreboard_generation_gate.py", path2)
    assert code2 == 0 and out2["status"] == "PASS"


def test_assertion_generation_gate_pass_and_fail(tmp_path, real_vip_config, real_vip_release, real_clock_reset):
    doc = _complete_architecture_doc(real_vip_config, real_vip_release, real_clock_reset)
    clean = {k: v for k, v in doc.items() if k != "_irs"}
    path = tmp_path / "arch.json"
    path.write_text(json.dumps(clean), encoding="utf-8")
    code, out = _run_gate("assertion_generation_gate.py", path)
    assert code == 0 and out["status"] == "PASS"

    broken = json.loads(json.dumps(clean))
    broken["assertion"][0]["clock_domain_match"] = False
    path2 = tmp_path / "arch_broken.json"
    path2.write_text(json.dumps(broken), encoding="utf-8")
    code2, out2 = _run_gate("assertion_generation_gate.py", path2)
    assert code2 == 2 and out2["status"] == "FAIL"


def test_generation_gates_fail_on_empty_arrays(tmp_path):
    empty_doc = {"schema_version": "1.0", "vip_selection": [], "vip_bind": [], "checker": [],
                 "scoreboard": [], "assertion": [], "placement_conflicts": [], "intra_subsystem_duplicates": [],
                 "matrices": {"vip_bind": "", "interface_to_verification": "", "function_to_checker": "",
                              "assertion_placement": "", "scoreboard_architecture": ""}}
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(empty_doc), encoding="utf-8")
    for script in ("vip_bind_generation_gate.py", "scoreboard_generation_gate.py", "assertion_generation_gate.py"):
        code, out = _run_gate(script, path)
        assert code == 2 and out["status"] == "FAIL"
