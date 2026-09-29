"""Tests for dv_harness/system_virtual_sequencer.py.

The structural input this module consumes -- `VipBindIR.chain_classification`
-- is built through the REAL `verification_architecture.build_vip_bind_ir()`
pipeline (real bind entries, real `chain_by_target` hop lists classified by
that module's own `classify_wrapper_bridge_hop()`), never a hand-typed stand
-in for a VipBindIR's own shape. Both the real-instance input form and the
`.to_dict()` input form are exercised, since the module documents accepting
either.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import system_virtual_sequencer as svs
from dv_harness import verification_architecture as va

REPO_ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# helpers -- build real VipBindIR records via the real producer
# ===========================================================================

def _wrapper_hop(instance="chip.core.usb0.wrap", module="usb_wrapper"):
    return {"instance": instance, "module": module,
            "boundary_classification": {"kind": "PARALLEL"}}


def _bridge_hop(instance="chip.core.usb0.phy_bridge", module="usb_phy_bridge"):
    return {"instance": instance, "module": module,
            "boundary_classification": {"kind": "MIXED"}}


def _undecidable_hop(instance="chip.core.usb0.mystery", module="mystery_mod"):
    return {"instance": instance, "module": module,
            "boundary_classification": {"kind": "UNDECIDABLE", "rationale": "no evidence"}}


def _real_vip_bind_irs(target_instance, hops=None):
    """Real `VipBindIR` list (length 1) built through
    `verification_architecture.build_vip_bind_ir()` -- the real producer,
    never a hand-constructed stand-in."""
    bind_entries = [{"target_instance": target_instance, "ports": ["p0"], "reason": "test"}]
    chain_by_target = {target_instance: hops} if hops is not None else None
    return va.build_vip_bind_ir(bind_entries, chain_by_target=chain_by_target)


# ===========================================================================
# derive_composition_mode() -- the core worst-wins fold
# ===========================================================================

def test_direct_chain_with_no_hops_yields_direct_handle():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip")  # no hops declared -> DIRECT
    assert binds[0].chain_classification == "DIRECT"
    bcs = svs.classify_subsystem_binds(binds)
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode(bcs)
    assert mode == "DIRECT_HANDLE"
    assert bridge_findings == []
    assert unresolved_findings == []


def test_wrapper_only_chain_yields_direct_handle():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_wrapper_hop()])
    assert binds[0].chain_classification == "WRAPPER_ONLY"
    bcs = svs.classify_subsystem_binds(binds)
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode(bcs)
    assert mode == "DIRECT_HANDLE"
    assert bridge_findings == []


def test_bridge_in_path_yields_adapter_required():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])
    assert binds[0].chain_classification == "BRIDGE_IN_PATH"
    bcs = svs.classify_subsystem_binds(binds)
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode(bcs)
    assert mode == "ADAPTER_REQUIRED"
    assert len(bridge_findings) == 1
    assert bridge_findings[0]["target_instance"] == "chip.core.usb0.dev_vip"
    assert bridge_findings[0]["bridge_hops"], "bridge hop evidence must be carried through"


def test_unknown_chain_yields_composition_undetermined():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_undecidable_hop()])
    assert binds[0].chain_classification == "UNKNOWN"
    bcs = svs.classify_subsystem_binds(binds)
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode(bcs)
    assert mode == "COMPOSITION_UNDETERMINED"
    assert len(unresolved_findings) == 1
    assert unresolved_findings[0]["target_instance"] == "chip.core.usb0.dev_vip"


def test_worst_wins_bridge_outranks_clean_binds_on_same_subsystem():
    """A single BRIDGE_IN_PATH bind among several clean ones must still make
    the WHOLE subsystem ADAPTER_REQUIRED -- never averaged/diluted."""
    clean = _real_vip_bind_irs("chip.core.usb0.host_vip")[0]
    bridge = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])[0]
    another_clean = _real_vip_bind_irs("chip.core.usb0.reg_vip", hops=[_wrapper_hop()])[0]
    bcs = svs.classify_subsystem_binds([clean, bridge, another_clean])
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode(bcs)
    assert mode == "ADAPTER_REQUIRED"
    assert len(bridge_findings) == 1
    assert unresolved_findings == []


def test_worst_wins_bridge_outranks_unknown_on_same_subsystem():
    bridge = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])[0]
    unknown = _real_vip_bind_irs("chip.core.usb0.dbg_vip", hops=[_undecidable_hop()])[0]
    bcs = svs.classify_subsystem_binds([bridge, unknown])
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode(bcs)
    assert mode == "ADAPTER_REQUIRED"
    assert len(bridge_findings) == 1
    assert len(unresolved_findings) == 1  # still reported, just doesn't win the fold


def test_no_binds_supplied_is_not_available_never_guessed_clean():
    mode, bridge_findings, unresolved_findings = svs.derive_composition_mode([])
    assert mode == "NOT_AVAILABLE"
    assert bridge_findings == []
    assert unresolved_findings == []


# ===========================================================================
# classify_subsystem_binds() -- accepts real VipBindIR instances AND dicts
# ===========================================================================

def test_classify_subsystem_binds_accepts_real_vipbindir_instances():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])
    bcs = svs.classify_subsystem_binds(binds)
    assert len(bcs) == 1
    assert bcs[0].chain_classification == "BRIDGE_IN_PATH"
    assert bcs[0].target_instance == "chip.core.usb0.dev_vip"
    assert bcs[0].source_evidence, "real VipBindIR source_evidence must be carried through"


def test_classify_subsystem_binds_accepts_to_dict_shape():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])
    as_dicts = [b.to_dict() for b in binds]
    assert as_dicts[0]["ir_kind"] == "vip_bind"
    bcs = svs.classify_subsystem_binds(as_dicts)
    assert len(bcs) == 1
    assert bcs[0].chain_classification == "BRIDGE_IN_PATH"
    assert bcs[0].target_instance == "chip.core.usb0.dev_vip"


def test_classify_subsystem_binds_none_and_empty_both_yield_empty_list():
    assert svs.classify_subsystem_binds(None) == []
    assert svs.classify_subsystem_binds([]) == []


def test_classify_subsystem_binds_refuses_a_record_with_no_chain_classification():
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.classify_subsystem_binds([{"target_instance": "x", "ports": []}])


def test_subsystem_bind_classification_refuses_unrecognized_chain_value():
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.SubsystemBindClassification(
            target_instance="x", chain_classification="MADE_UP_VALUE",
            bridge_hops=[], source_evidence=[],
        )


# ===========================================================================
# build_subsystem_composition() -- naming + full per-subsystem record
# ===========================================================================

def test_build_subsystem_composition_names_match_generator_convention():
    """class_type/field_name must match the EXACT convention
    soc_environment_composer.py's own _build_virtual_sequencer_fields()
    uses: <sv_id(name)>_virtual_sequencer / <sv_id(name)>_vseqr."""
    from dv_harness.uvm_generator.generator import sv_id
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip")
    comp = svs.build_subsystem_composition("USB-3.0", binds)
    proto = sv_id("USB-3.0")
    assert comp.class_type == f"{proto}_virtual_sequencer"
    assert comp.field_name == f"{proto}_vseqr"
    assert comp.composition_mode == "DIRECT_HANDLE"


def test_build_subsystem_composition_refuses_blank_name():
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.build_subsystem_composition("   ", None)


def test_build_subsystem_composition_no_binds_reports_not_available_with_reason():
    comp = svs.build_subsystem_composition("usb", None)
    assert comp.composition_mode == "NOT_AVAILABLE"
    assert comp.bind_classifications == []
    reasons = [e["fact_source"] for e in comp.source_evidence]
    assert "caller_supplied_vip_binds" in reasons


def test_build_subsystem_composition_adapter_required_carries_real_evidence():
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])
    comp = svs.build_subsystem_composition("usb", binds)
    assert comp.composition_mode == "ADAPTER_REQUIRED"
    assert len(comp.bridge_findings) == 1
    finding = comp.bridge_findings[0]
    assert finding["target_instance"] == "chip.core.usb0.dev_vip"
    assert "bridge" in finding["reason"].lower()
    row = comp.to_row()
    assert row["bridge_count"] == 1


# ===========================================================================
# build_system_virtual_sequencer_composition() -- whole-record rollup
# ===========================================================================

def test_whole_record_all_direct_reads_ready():
    subsystems = [
        {"name": "usb", "vip_binds": _real_vip_bind_irs("chip.core.usb0.dev_vip")},
        {"name": "pcie", "vip_binds": _real_vip_bind_irs("chip.core.pcie0.ep_vip", hops=[_wrapper_hop()])},
    ]
    ir = svs.build_system_virtual_sequencer_composition(subsystems)
    assert ir.overall_status == "READY_DIRECT_COMPOSITION"
    assert {s.composition_mode for s in ir.subsystems} == {"DIRECT_HANDLE"}


def test_whole_record_one_adapter_required_outranks_the_rest():
    subsystems = [
        {"name": "usb", "vip_binds": _real_vip_bind_irs("chip.core.usb0.dev_vip")},
        {"name": "pcie", "vip_binds": _real_vip_bind_irs(
            "chip.core.pcie0.ep_vip", hops=[_bridge_hop()])},
    ]
    ir = svs.build_system_virtual_sequencer_composition(subsystems)
    assert ir.overall_status == "ADAPTER_REQUIRED"


def test_whole_record_incomplete_evidence_never_confused_with_adapter_required():
    subsystems = [
        {"name": "usb", "vip_binds": _real_vip_bind_irs("chip.core.usb0.dev_vip")},
        {"name": "amba", "vip_binds": None},  # NOT_AVAILABLE, no bridge anywhere
    ]
    ir = svs.build_system_virtual_sequencer_composition(subsystems)
    assert ir.overall_status == "INCOMPLETE_EVIDENCE"


def test_whole_record_unknown_chain_also_folds_to_incomplete_evidence():
    subsystems = [
        {"name": "usb", "vip_binds": _real_vip_bind_irs("chip.core.usb0.dev_vip")},
        {"name": "amba", "vip_binds": _real_vip_bind_irs(
            "chip.core.amba0.fabric_vip", hops=[_undecidable_hop()])},
    ]
    ir = svs.build_system_virtual_sequencer_composition(subsystems)
    assert ir.overall_status == "INCOMPLETE_EVIDENCE"


def test_whole_record_no_subsystems_is_not_available_never_vacuous_ready():
    ir = svs.build_system_virtual_sequencer_composition([])
    assert ir.overall_status == "NOT_AVAILABLE"
    assert ir.subsystems == []


def test_build_system_virtual_sequencer_composition_refuses_none():
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.build_system_virtual_sequencer_composition(None)


def test_build_system_virtual_sequencer_composition_refuses_entry_with_no_name():
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.build_system_virtual_sequencer_composition([{"vip_binds": []}])


def test_ir_construction_refuses_unrecognized_overall_status():
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.SystemVirtualSequencerCompositionIR(
            schema_version="1.0", subsystems=[], overall_status="MADE_UP",
        )


# ===========================================================================
# rendering + to_dict()
# ===========================================================================

def test_to_dict_round_trips_every_field():
    subsystems = [
        {"name": "usb", "vip_binds": _real_vip_bind_irs(
            "chip.core.usb0.dev_vip", hops=[_bridge_hop()])},
    ]
    ir = svs.build_system_virtual_sequencer_composition(subsystems)
    doc = ir.to_dict()
    assert doc["overall_status"] == "ADAPTER_REQUIRED"
    assert doc["subsystems"][0]["subsystem_name"] == "usb"
    assert doc["subsystems"][0]["composition_mode"] == "ADAPTER_REQUIRED"
    assert doc["subsystems"][0]["bind_classifications"][0]["chain_classification"] == "BRIDGE_IN_PATH"


def test_render_markdown_lists_every_subsystem_row():
    subsystems = [
        {"name": "usb", "vip_binds": _real_vip_bind_irs("chip.core.usb0.dev_vip")},
    ]
    ir = svs.build_system_virtual_sequencer_composition(subsystems)
    md = ir.render_markdown()
    assert "usb_virtual_sequencer" in md
    assert "DIRECT_HANDLE" in md


def test_render_markdown_empty_note_when_no_subsystems():
    ir = svs.build_system_virtual_sequencer_composition([])
    md = ir.render_markdown()
    assert "NOT_AVAILABLE" in md


# ===========================================================================
# vocabulary guard
# ===========================================================================

def test_vocabulary_disjoint_from_models_status():
    # Import-time assertion already ran; re-run explicitly for a direct test.
    svs.assert_no_verification_verdict_vocabulary()


def test_vocabulary_guard_has_real_detection_power(monkeypatch):
    monkeypatch.setattr(svs, "COMPOSITION_MODES", tuple(svs.COMPOSITION_MODES) + ("PASS",))
    with pytest.raises(svs.SystemVirtualSequencerError):
        svs.assert_no_verification_verdict_vocabulary()


# ===========================================================================
# CLI: real subprocess, all exit codes
# ===========================================================================

def _write_subsystems_doc(tmp_path, subsystems):
    doc = tmp_path / "subsystems.json"
    doc.write_text(json.dumps({"subsystems": subsystems}), encoding="utf-8")
    return doc


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.system_virtual_sequencer", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def test_cli_ready_direct_composition_exit_0(tmp_path):
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip")
    doc = _write_subsystems_doc(tmp_path, [{"name": "usb", "vip_binds": [b.to_dict() for b in binds]}])
    result = _run_cli("--subsystems", str(doc), "--json")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["overall_status"] == "READY_DIRECT_COMPOSITION"


def test_cli_adapter_required_exit_1(tmp_path):
    binds = _real_vip_bind_irs("chip.core.usb0.dev_vip", hops=[_bridge_hop()])
    doc = _write_subsystems_doc(tmp_path, [{"name": "usb", "vip_binds": [b.to_dict() for b in binds]}])
    result = _run_cli("--subsystems", str(doc), "--markdown")
    assert result.returncode == 1, result.stderr
    assert "ADAPTER_REQUIRED" in result.stdout


def test_cli_not_available_exit_2_on_missing_file(tmp_path):
    result = _run_cli("--subsystems", str(tmp_path / "nope.json"))
    assert result.returncode == 2


def test_cli_incomplete_evidence_exit_2(tmp_path):
    doc = _write_subsystems_doc(tmp_path, [{"name": "usb", "vip_binds": []}])
    result = _run_cli("--subsystems", str(doc))
    assert result.returncode == 2
