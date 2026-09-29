"""Tests for dv_harness/intake_state.py.

Real evidence throughout, per this project's Evidence Truth Rule: env.manifest
layer facts are produced by calling the REAL `env_manifest.py` builder
functions (never a hand-typed manifest shape), bind-tier facts are classified
through the REAL `connectivity.py` vocabulary, dut-boundary facts are the REAL
`phy_boundary.classify_boundary()` / `decide_bind_location()` output, and
question_queue decisions are produced by driving a REAL
`question_queue.QuestionQueueStore` through its real `add_question()` /
`answer_question()` API on a throwaway project root -- never a hand-written
decisions.json record.
"""
import json

import pytest

from dv_harness import connectivity, env_manifest, intake_state, phy_boundary, question_queue


# ---------------------------------------------------------------------------
# fixtures: real env.manifest.json-shaped layers, built by the real producer
# ---------------------------------------------------------------------------

def _write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _real_registers_layer(tmp_path):
    reg_map = {
        "schema_version": "1.0",
        "blocks": [{
            "name": "usb0", "base_address": "0x1000",
            "registers": [{
                "name": "CTRL", "address_offset": "0x0", "width": 32, "access": "RW",
            }],
        }],
    }
    p = _write_json(tmp_path / "register_map.json", reg_map)
    return env_manifest.build_dut_facts_registers(str(p))


def _real_address_map_layer(tmp_path, registers_layer, *, agree: bool):
    base = "0x1000" if agree else "0x2000"
    soc_map = {
        "schema_version": "1.0",
        "address_map": [{
            "name": "usb0", "base_address": base, "size_bytes": 4096,
            "target": "chip.core.usb0", "bus": "AXI4-Lite", "evidence": "soc_spec.md#usb0",
        }],
    }
    p = _write_json(tmp_path / f"soc_arch_map_{'agree' if agree else 'disagree'}.json", soc_map)
    return env_manifest.build_dut_facts_address_map(str(p), registers_layer=registers_layer)


def _real_testplan_layer(tmp_path, *, broken: bool):
    testlist = [{"name": "test_usb_smoke"}]
    vplan_items = [{
        "id": "VP-1",
        "tests": ["test_usb_smoke" if not broken else "test_does_not_exist"],
        "coverage": ["cg_usb_txn"],
    }]
    coverage_model = [{"name": "cg_usb_txn", "kind": "covergroup"}]
    doc = {
        "schema_version": "1.0",
        "testlist": testlist, "vplan_items": vplan_items, "coverage_model": coverage_model,
    }
    p = _write_json(tmp_path / f"testplan_sources_{'broken' if broken else 'clean'}.json", doc)
    return env_manifest.build_testplan_correspondence(str(p))


def _real_vip_release_layer(tmp_path):
    home = tmp_path / "designware_home"
    pkg_dir = home / "vip" / "svt" / "usb3" / "1.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "release_notes.txt").write_text("USB3 VIP 1.0 release notes", encoding="utf-8")
    return env_manifest.build_vip_release(designware_home=str(home))


def _real_parallel_boundary_doc():
    phy_module = {"name": "phy", "ports": [{"name": "pipe_data", "direction": "output", "data_type": "[7:0]"}]}
    ctrl_module = {"name": "ctrl", "ports": [{"name": "pipe_data", "direction": "input", "data_type": "[7:0]"}]}
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    bind_decision = phy_boundary.decide_bind_location(classification, signals)
    assert classification["kind"] == "PARALLEL"
    assert bind_decision["bindable"] is True
    return {"status": "EXTRACTED", "bind_decision": bind_decision}


def _real_serial_boundary_doc():
    phy_module = {"name": "phy", "ports": [{"name": "txp", "direction": "output", "data_type": "logic"}]}
    ctrl_module = {"name": "ctrl", "ports": [{"name": "txp", "direction": "input", "data_type": "logic"}]}
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    bind_decision = phy_boundary.decide_bind_location(classification, signals)
    assert classification["kind"] == "SERIAL"
    assert bind_decision["bindable"] is False
    return {"status": "EXTRACTED", "bind_decision": bind_decision}


# ---------------------------------------------------------------------------
# env_manifest joining
# ---------------------------------------------------------------------------

def test_no_manifest_at_all_reports_missing_for_every_layer():
    state = intake_state.build_intake_state(env_manifest=None)
    for field in ("dut_rtl", "dut_registers", "dut_address_map", "dut_clock_reset",
                  "vip_release", "vip_user_guide_refs", "component_hierarchy",
                  "config_db_trace", "testplan_correspondence"):
        rec = state.get(field)
        assert rec is not None, field
        assert rec.status == intake_state.IntakeFieldStatus.MISSING.value, field
        assert rec.confidence == "UNKNOWN"


def test_real_registers_layer_reports_auto_resolved(tmp_path):
    registers_layer = _real_registers_layer(tmp_path)
    assert registers_layer["status"] == "LOADED"  # sanity on the real producer
    manifest = {"dut_facts": {"registers": registers_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    rec = state.get("dut_registers")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.value == "LOADED"
    assert rec.confidence == "HIGH"
    assert rec.owner == "designer"  # question_queue.route_owner("dut")
    assert rec.source == "env_manifest:dut_facts.registers"


def test_real_address_map_agreement_reports_auto_resolved(tmp_path):
    registers_layer = _real_registers_layer(tmp_path)
    address_layer = _real_address_map_layer(tmp_path, registers_layer, agree=True)
    assert address_layer["disagreement_count"] == 0  # sanity on the real producer
    manifest = {"dut_facts": {"registers": registers_layer, "address_map": address_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    rec = state.get("dut_address_map")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_real_address_map_disagreement_reports_contradicted_NEGATIVE_CONTROL(tmp_path):
    """A genuine register_map_agreement DISAGREES (real producer, real base
    address mismatch) must never read as AUTO_RESOLVED -- that would be a
    false pass over a real cross-source conflict."""
    registers_layer = _real_registers_layer(tmp_path)
    address_layer = _real_address_map_layer(tmp_path, registers_layer, agree=False)
    assert address_layer["disagreement_count"] == 1  # sanity on the real producer
    manifest = {"dut_facts": {"registers": registers_layer, "address_map": address_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    rec = state.get("dut_address_map")
    assert rec.status == intake_state.IntakeFieldStatus.CONTRADICTED.value
    assert "disagreement_count=1" in rec.reason


def test_real_testplan_broken_ref_reports_contradicted_NEGATIVE_CONTROL(tmp_path):
    layer = _real_testplan_layer(tmp_path, broken=True)
    assert layer["summary"]["broken_count"] == 1  # sanity on the real producer
    manifest = {"env_topology": {"testplan_correspondence": layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    rec = state.get("testplan_correspondence")
    assert rec.status == intake_state.IntakeFieldStatus.CONTRADICTED.value


def test_real_testplan_clean_reports_auto_resolved(tmp_path):
    layer = _real_testplan_layer(tmp_path, broken=False)
    assert layer["summary"]["broken_count"] == 0
    manifest = {"env_topology": {"testplan_correspondence": layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    rec = state.get("testplan_correspondence")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_real_vip_release_scan_resolves_vip_category(tmp_path):
    layer = _real_vip_release_layer(tmp_path)
    assert layer["status"] == "SCANNED"  # sanity on the real producer
    manifest = {"vip_config": {"vip_release": layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    rec = state.get("vip_release")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.owner == "DV-owner/Synopsys-AE"  # question_queue.route_owner("vip")
    assert state.category_status("vip_resolution") == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_no_vip_release_blocks_vip_resolution_category_NEGATIVE_CONTROL():
    state = intake_state.build_intake_state(env_manifest={})
    assert state.category_status("vip_resolution") == intake_state.IntakeFieldStatus.MISSING.value
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert not readiness.ready
    assert "vip_resolution" in readiness.blocking


# ---------------------------------------------------------------------------
# connectivity bind-tier joining (critical_bind)
# ---------------------------------------------------------------------------

def test_bind_entries_none_reports_missing():
    state = intake_state.build_intake_state(bind_entries=None)
    assert state.category_status("critical_bind") == intake_state.IntakeFieldStatus.MISSING.value


def test_t1_and_t2_bind_entries_auto_resolve():
    entries = [
        {"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value},
        {"target_instance": "chip.core.usb1", "tier": connectivity.BindTier.T2_STRUCTURAL_MATCH.value},
    ]
    state = intake_state.build_intake_state(bind_entries=entries)
    for target in ("chip.core.usb0", "chip.core.usb1"):
        rec = state.get(f"bind:{target}")
        assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert state.category_status("critical_bind") == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_t3_bind_without_confirmation_blocks_NEGATIVE_CONTROL():
    entries = [{"target_instance": "chip.core.usb2", "tier": connectivity.BindTier.T3_NAMING_HEURISTIC.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    rec = state.get("bind:chip.core.usb2")
    assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value
    assert state.category_status("critical_bind") == intake_state.IntakeFieldStatus.BLOCKED.value
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert not readiness.ready
    assert "critical_bind" in readiness.blocking


def test_t3_bind_with_fabricated_confirmation_source_still_blocks_NEGATIVE_CONTROL():
    """A `human_confirmation` block whose source is NOT the real
    question_queue.HUMAN_DECISION_SOURCE must never be accepted as a real
    human confirmation -- this is exactly the guard connectivity.py's own
    `_t3_human_confirmation_is_real()` enforces, re-read here."""
    entries = [{
        "target_instance": "chip.core.usb2", "tier": connectivity.BindTier.T3_NAMING_HEURISTIC.value,
        "human_confirmation": {"source": "agent_self_attested", "confirmed_by": "agent", "basis": "looked right"},
    }]
    state = intake_state.build_intake_state(bind_entries=entries)
    rec = state.get("bind:chip.core.usb2")
    assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value


def test_t3_bind_with_real_human_confirmation_resolves():
    entries = [{
        "target_instance": "chip.core.usb2", "tier": connectivity.BindTier.T3_NAMING_HEURISTIC.value,
        "human_confirmation": {
            "source": question_queue.HUMAN_DECISION_SOURCE,
            "confirmed_by": "alice", "basis": "matches the programming guide's instance table",
        },
    }]
    state = intake_state.build_intake_state(bind_entries=entries)
    rec = state.get("bind:chip.core.usb2")
    assert rec.status == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    assert rec.owner == "alice"


def test_t4_bind_always_blocks_NEGATIVE_CONTROL():
    entries = [{"target_instance": "chip.core.usb3", "tier": connectivity.BindTier.T4_UNDECIDABLE.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    rec = state.get("bind:chip.core.usb3")
    assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value


def test_unrecognized_bind_tier_is_unknown_not_a_false_pass_NEGATIVE_CONTROL():
    entries = [{"target_instance": "chip.core.usbX", "tier": "T99_MADE_UP"}]
    state = intake_state.build_intake_state(bind_entries=entries)
    rec = state.get("bind:chip.core.usbX")
    assert rec.status == intake_state.IntakeFieldStatus.UNKNOWN.value


# ---------------------------------------------------------------------------
# DUT boundary (phy_boundary-shaped, computed via the real functions)
# ---------------------------------------------------------------------------

def test_no_dut_boundary_supplied_is_missing():
    state = intake_state.build_intake_state(dut_boundary=None)
    assert state.get("dut_boundary").status == intake_state.IntakeFieldStatus.MISSING.value


def test_real_parallel_boundary_resolves():
    doc = _real_parallel_boundary_doc()
    state = intake_state.build_intake_state(dut_boundary=doc)
    rec = state.get("dut_boundary")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.value == "controller_phy_parallel_boundary"


def test_real_serial_boundary_blocks_NEGATIVE_CONTROL():
    """A real SERIAL-only boundary (no PHY parallel mount point) must BLOCK,
    per CLAUDE.md's Bind-Location Rule 5 -- never silently resolve, which
    would let a protocol monitor be bound where it decodes nothing."""
    doc = _real_serial_boundary_doc()
    state = intake_state.build_intake_state(dut_boundary=doc)
    rec = state.get("dut_boundary")
    assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert "dut_boundary" in readiness.blocking


# ---------------------------------------------------------------------------
# active-driver conflicts (generic duck-typed input)
# ---------------------------------------------------------------------------

def test_no_conflicts_supplied_is_missing():
    state = intake_state.build_intake_state(active_driver_conflicts=None)
    assert state.category_status("active_driver_conflict") == intake_state.IntakeFieldStatus.MISSING.value


def test_empty_conflict_list_resolves_the_category():
    state = intake_state.build_intake_state(active_driver_conflicts=[])
    assert state.category_status("active_driver_conflict") == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_a_real_conflict_blocks_the_category_NEGATIVE_CONTROL():
    conflicts = [{"resource": "AXI_M0", "status": "ACTIVE_DRIVER_CONFLICT", "reason": "two ACTIVE masters"}]
    state = intake_state.build_intake_state(active_driver_conflicts=conflicts)
    assert state.category_status("active_driver_conflict") == intake_state.IntakeFieldStatus.BLOCKED.value
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert "active_driver_conflict" in readiness.blocking


# ---------------------------------------------------------------------------
# build env (connectivity Gate 1 result)
# ---------------------------------------------------------------------------

def test_no_build_env_gate_is_missing():
    state = intake_state.build_intake_state(build_env_gate=None)
    assert state.get("build_env").status == intake_state.IntakeFieldStatus.MISSING.value


def test_gate1_pass_resolves_build_env():
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.PASS, detail={})
    state = intake_state.build_intake_state(build_env_gate=gate)
    assert state.get("build_env").status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value


def test_gate1_fail_blocks_build_env_NEGATIVE_CONTROL():
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.FAIL,
                                    detail={"reason": "compile error"})
    state = intake_state.build_intake_state(build_env_gate=gate)
    rec = state.get("build_env")
    assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value
    assert rec.reason == "compile error"
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert "build_env" in readiness.blocking


def test_gate1_not_available_is_unknown_not_a_false_pass_NEGATIVE_CONTROL():
    gate = {"status": connectivity.GateStatus.NOT_AVAILABLE.value, "detail": {"reason": "slang not on PATH"}}
    state = intake_state.build_intake_state(build_env_gate=gate)
    rec = state.get("build_env")
    assert rec.status == intake_state.IntakeFieldStatus.UNKNOWN.value


# ---------------------------------------------------------------------------
# known-PASS test (generic duck-typed input)
# ---------------------------------------------------------------------------

def test_no_known_pass_tests_is_missing():
    state = intake_state.build_intake_state(known_pass_tests=None)
    assert state.category_status("known_pass_test") == intake_state.IntakeFieldStatus.MISSING.value


def test_at_least_one_pass_resolves_the_category():
    tests = [{"test_name": "test_a", "verdict": "FAIL"}, {"test_name": "test_b", "verdict": "PASS"}]
    state = intake_state.build_intake_state(known_pass_tests=tests)
    rec = state.get("known_pass_tests")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.value == ["test_b"]


def test_all_fail_never_reads_as_resolved_NEGATIVE_CONTROL():
    tests = [{"test_name": "test_a", "verdict": "FAIL"}, {"test_name": "test_b", "verdict": "FAIL"}]
    state = intake_state.build_intake_state(known_pass_tests=tests)
    rec = state.get("known_pass_tests")
    assert rec.status != intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.status != intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert "known_pass_test" in readiness.blocking


# ---------------------------------------------------------------------------
# question_queue decision overlay -- driven through a REAL QuestionQueueStore
# ---------------------------------------------------------------------------

def test_tier2_auto_assumption_upgrades_a_missing_field_to_auto_resolved(tmp_path):
    store = question_queue.QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Which build env should intake_state trust?",
        context_path="intake_state_test.build_env_key",
        options=["envA", "envB"], recommendation="envA", assumption_if_unanswered="envA",
        context={},  # no hard trigger -> TIER2_SAFE_ASSUME, auto-persisted
    )
    assert q["status"] == "ASSUMED"
    state = intake_state.build_intake_state(
        build_env_gate=None,  # otherwise MISSING/UNKNOWN -- the overlay should strengthen it
        question_store=store, field_question_keys={"build_env": q["question_key"]},
    )
    rec = state.get("build_env")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.confidence == "MEDIUM"
    assert rec.value == "envA"


def test_human_answer_upgrades_a_missing_field_to_user_confirmed(tmp_path):
    """No `dut_boundary` was ever supplied (MISSING, no computed value to
    disagree with) -- a real human answer on file should be able to resolve
    it directly, distinct from the CONTRADICTED case below where a computed
    value already exists and disagrees."""
    store = question_queue.QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Which mount layer should this DUT boundary use?",
        context_path="intake_state_test.dut_boundary_key",
        options=["controller_phy_parallel_boundary", "serial_boundary_not_bindable"],
        recommendation="controller_phy_parallel_boundary",
        assumption_if_unanswered="serial_boundary_not_bindable",
        context={"affects_pass_fail_verdict": True},  # hard trigger -> TIER3_CANNOT_ASSUME, OPEN
    )
    assert q["status"] == "OPEN"
    store.answer_question(q["id"], answer="controller_phy_parallel_boundary",
                            basis="PHY datasheet section 4 names a real parallel test port",
                            decided_by="alice")
    state = intake_state.build_intake_state(
        dut_boundary=None, question_store=store, field_question_keys={"dut_boundary": q["question_key"]},
    )
    rec = state.get("dut_boundary")
    assert rec.status == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    assert rec.owner == "alice"
    assert rec.value == "controller_phy_parallel_boundary"


def test_human_answer_confirming_an_already_blocked_computed_value_still_confirms(tmp_path):
    """A human who reviews a real BLOCKED finding and answers with the SAME
    value the computation already produced is not a disagreement -- it is a
    human independently confirming the harness's own finding, which is a
    legitimate strengthening (USER_CONFIRMED), not a downgrade."""
    store = question_queue.QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Which mount layer should this DUT boundary use?",
        context_path="intake_state_test.dut_boundary_key2",
        options=["controller_phy_parallel_boundary", "serial_boundary_not_bindable"],
        recommendation="serial_boundary_not_bindable",
        assumption_if_unanswered="serial_boundary_not_bindable",
        context={"affects_pass_fail_verdict": True},
    )
    doc = _real_serial_boundary_doc()  # computed mount_layer == "serial_boundary_not_bindable"
    store.answer_question(q["id"], answer="serial_boundary_not_bindable",
                            basis="confirmed: no parallel port exists on this PHY", decided_by="alice")
    state = intake_state.build_intake_state(
        dut_boundary=doc, question_store=store, field_question_keys={"dut_boundary": q["question_key"]},
    )
    rec = state.get("dut_boundary")
    assert rec.status == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    assert rec.value == "serial_boundary_not_bindable"


def test_human_answer_disagreeing_with_a_computed_value_reports_contradicted_NEGATIVE_CONTROL(tmp_path):
    """A human's filed answer that disagrees with a real, already-computed
    fact must be surfaced as CONTRADICTED, never silently overwritten as if
    the two agreed."""
    store = question_queue.QuestionQueueStore(tmp_path)
    registers_layer = _real_registers_layer(tmp_path)
    q = store.add_question(
        domain="dut", question="What is the registers layer status?",
        context_path="intake_state_test.dut_registers_key",
        options=["LOADED", "NOT_AVAILABLE"], recommendation="LOADED", assumption_if_unanswered="LOADED",
        context={"affects_pass_fail_verdict": True},
    )
    store.answer_question(q["id"], answer="NOT_AVAILABLE", basis="disagreeing on purpose", decided_by="bob")
    manifest = {"dut_facts": {"registers": registers_layer}}
    state = intake_state.build_intake_state(
        env_manifest=manifest, question_store=store,
        field_question_keys={"dut_registers": q["question_key"]},
    )
    rec = state.get("dut_registers")
    assert rec.status == intake_state.IntakeFieldStatus.CONTRADICTED.value
    assert rec.owner == "bob"


def test_no_question_key_for_a_field_leaves_it_unaffected(tmp_path):
    store = question_queue.QuestionQueueStore(tmp_path)
    state = intake_state.build_intake_state(question_store=store, field_question_keys={})
    assert state.get("build_env").status == intake_state.IntakeFieldStatus.MISSING.value


# ---------------------------------------------------------------------------
# do-not-ask helper
# ---------------------------------------------------------------------------

def test_already_resolved_true_for_auto_resolved():
    entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    assert intake_state.already_resolved(state, "bind:chip.core.usb0") is True


def test_already_resolved_false_for_blocked_missing_and_unseen_fields_NEGATIVE_CONTROL():
    entries = [{"target_instance": "chip.core.usb2", "tier": connectivity.BindTier.T3_NAMING_HEURISTIC.value}]
    state = intake_state.build_intake_state(bind_entries=entries, env_manifest=None)
    assert intake_state.already_resolved(state, "bind:chip.core.usb2") is False  # BLOCKED
    assert intake_state.already_resolved(state, "dut_rtl") is False  # MISSING
    assert intake_state.already_resolved(state, "field_never_recorded") is False  # unseen


# ---------------------------------------------------------------------------
# UVM_GENERATION_READY: full refusal / full readiness
# ---------------------------------------------------------------------------

def test_a_fresh_state_with_nothing_supplied_refuses_generation_NEGATIVE_CONTROL():
    """Never silently proceed: an intake state built from nothing must
    refuse on every one of the six blocking categories, not just some."""
    state = intake_state.build_intake_state()
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert readiness.ready is False
    assert set(readiness.blocking) == set(intake_state.BLOCKING_CATEGORIES)


def test_all_six_categories_resolved_is_ready(tmp_path):
    vip_layer = _real_vip_release_layer(tmp_path)
    manifest = {"vip_config": {"vip_release": vip_layer}}
    bind_entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    dut_boundary = _real_parallel_boundary_doc()
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.PASS, detail={})
    tests = [{"test_name": "test_usb_smoke", "verdict": "PASS"}]

    state = intake_state.build_intake_state(
        env_manifest=manifest, bind_entries=bind_entries, dut_boundary=dut_boundary,
        active_driver_conflicts=[], build_env_gate=gate, known_pass_tests=tests,
    )
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert readiness.ready is True
    assert readiness.blocking == {}


def test_one_remaining_blocked_category_still_refuses_NEGATIVE_CONTROL(tmp_path):
    """Five of six resolved, one BLOCKED -- must still refuse as a whole,
    never average toward readiness."""
    vip_layer = _real_vip_release_layer(tmp_path)
    manifest = {"vip_config": {"vip_release": vip_layer}}
    bind_entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T4_UNDECIDABLE.value}]
    dut_boundary = _real_parallel_boundary_doc()
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.PASS, detail={})
    tests = [{"test_name": "test_usb_smoke", "verdict": "PASS"}]

    state = intake_state.build_intake_state(
        env_manifest=manifest, bind_entries=bind_entries, dut_boundary=dut_boundary,
        active_driver_conflicts=[], build_env_gate=gate, known_pass_tests=tests,
    )
    readiness = intake_state.evaluate_uvm_generation_ready(state)
    assert readiness.ready is False
    assert list(readiness.blocking) == ["critical_bind"]


# ---------------------------------------------------------------------------
# record validation / IntakeState basics
# ---------------------------------------------------------------------------

def test_intake_field_record_rejects_unknown_status():
    with pytest.raises(ValueError):
        intake_state.IntakeFieldRecord(
            field="x", category="general", value=None, source="test",
            confidence="HIGH", status="NOT_A_REAL_STATUS",
        )


def test_intake_field_record_rejects_unknown_confidence():
    with pytest.raises(ValueError):
        intake_state.IntakeFieldRecord(
            field="x", category="general", value=None, source="test",
            confidence="SUPER_DUPER_HIGH", status=intake_state.IntakeFieldStatus.MISSING.value,
        )


def test_to_dict_roundtrips_every_record():
    state = intake_state.build_intake_state()
    doc = state.to_dict()
    assert doc["schema_version"] == intake_state.SCHEMA_VERSION
    assert len(doc["fields"]) == len(state.records)
    assert all({"field", "category", "value", "source", "confidence", "status",
                "last_validated", "owner", "reason"} <= set(f) for f in doc["fields"])
