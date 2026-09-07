"""Tests for dv_harness/intake_audit_provenance.py.

Real evidence throughout, matching test_intake_state.py's own discipline: a
real question_queue.QuestionQueueStore driven through its real
add_question()/answer_question() API on a throwaway project root, real
connectivity.BindTier values, and real env_manifest.py-produced layers --
never a hand-written decision or field record.
"""
import json

import pytest

from dv_harness import connectivity, env_manifest, intake_audit_provenance as iap, intake_state, question_queue


def _write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _real_registers_layer(tmp_path):
    reg_map = {
        "schema_version": "1.0",
        "blocks": [{
            "name": "usb0", "base_address": "0x1000",
            "registers": [{"name": "CTRL", "address_offset": "0x0", "width": 32, "access": "RW"}],
        }],
    }
    p = _write_json(tmp_path / "register_map.json", reg_map)
    return env_manifest.build_dut_facts_registers(str(p))


# ---------------------------------------------------------------------------
# NOT_ESTABLISHED: the negative control -- absent evidence must never be
# reported as an established fact with a fabricated establisher.
# ---------------------------------------------------------------------------

def test_missing_field_reports_not_established_NEGATIVE_CONTROL():
    state = intake_state.build_intake_state(env_manifest=None)
    report = iap.build_intake_audit_provenance(state)
    rec = report.get("dut_rtl")
    assert rec.status == intake_state.IntakeFieldStatus.MISSING.value
    assert rec.established is False
    assert rec.established_by is None
    assert rec.established_by_status == iap.ESTABLISHED_BY_NOT_ESTABLISHED
    assert rec.established_at is None
    assert rec.established_at_status == iap.ESTABLISHED_AT_UNKNOWN


def test_unknown_status_field_reports_not_established_NEGATIVE_CONTROL():
    gate = {"status": connectivity.GateStatus.NOT_AVAILABLE.value, "detail": {"reason": "slang not on PATH"}}
    state = intake_state.build_intake_state(build_env_gate=gate)
    report = iap.build_intake_audit_provenance(state)
    rec = report.get("build_env")
    assert rec.status == intake_state.IntakeFieldStatus.UNKNOWN.value
    assert rec.established is False
    assert rec.established_by_status == iap.ESTABLISHED_BY_NOT_ESTABLISHED


# ---------------------------------------------------------------------------
# SYSTEM_COMPUTED: a real env_manifest/connectivity/gate fact with no
# question_queue decision involved at all.
# ---------------------------------------------------------------------------

def test_real_registers_layer_reports_system_computed_provenance(tmp_path):
    registers_layer = _real_registers_layer(tmp_path)
    manifest = {"dut_facts": {"registers": registers_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    report = iap.build_intake_audit_provenance(state)
    rec = report.get("dut_registers")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.established is True
    assert rec.established_by_status == iap.ESTABLISHED_BY_SYSTEM_COMPUTED
    assert rec.established_by == "designer"  # reused verbatim from record.owner
    assert rec.established_via == "env_manifest:dut_facts.registers"
    assert rec.source == "env_manifest:dut_facts.registers"  # base reused verbatim
    assert rec.confidence == "HIGH"  # base reused verbatim
    assert rec.establishment_history == []


def test_t1_bind_entry_reports_system_computed_provenance():
    entries = [{"target_instance": "chip.core.usb0", "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    report = iap.build_intake_audit_provenance(state)
    rec = report.get("bind:chip.core.usb0")
    assert rec.established_by_status == iap.ESTABLISHED_BY_SYSTEM_COMPUTED
    assert rec.established is True


def test_blocked_field_is_still_established_NEGATIVE_CONTROL():
    """BLOCKED means a real determination happened (T3 unconfirmed) -- it
    must never read as NOT_ESTABLISHED, which would hide the real
    determination behind an absence."""
    entries = [{"target_instance": "chip.core.usb2", "tier": connectivity.BindTier.T3_NAMING_HEURISTIC.value}]
    state = intake_state.build_intake_state(bind_entries=entries)
    report = iap.build_intake_audit_provenance(state)
    rec = report.get("bind:chip.core.usb2")
    assert rec.status == intake_state.IntakeFieldStatus.BLOCKED.value
    assert rec.established is True
    assert rec.established_by_status == iap.ESTABLISHED_BY_SYSTEM_COMPUTED


# ---------------------------------------------------------------------------
# HUMAN: a real question_queue decision, recovered structurally (who/what/
# when/basis/Q-ID), not merely compressed into prose.
# ---------------------------------------------------------------------------

def test_human_decision_recovers_full_structured_provenance(tmp_path):
    store = question_queue.QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="dut", question="Which mount layer should this DUT boundary use?",
        context_path="iap_test.dut_boundary_key",
        options=["controller_phy_parallel_boundary", "serial_boundary_not_bindable"],
        recommendation="controller_phy_parallel_boundary",
        assumption_if_unanswered="serial_boundary_not_bindable",
        context={"affects_pass_fail_verdict": True},
    )
    store.answer_question(q["id"], answer="controller_phy_parallel_boundary",
                           basis="PHY datasheet section 4 names a real parallel test port",
                           decided_by="alice")
    state = intake_state.build_intake_state(
        dut_boundary=None, question_store=store, field_question_keys={"dut_boundary": q["question_key"]},
    )
    report = iap.build_intake_audit_provenance(
        state, question_store=store, field_question_keys={"dut_boundary": q["question_key"]},
    )
    rec = report.get("dut_boundary")
    assert rec.status == intake_state.IntakeFieldStatus.USER_CONFIRMED.value
    assert rec.established is True
    assert rec.established_by_status == iap.ESTABLISHED_BY_HUMAN
    assert rec.established_by == "alice"
    assert rec.established_at is not None
    assert rec.established_at_status == iap.ESTABLISHED_AT_EXACT
    assert rec.basis == "PHY datasheet section 4 names a real parallel test port"
    assert f"question_id={q['id']}" in rec.established_via
    assert "question_queue:human_answer" in rec.established_via
    assert "confirmed_by=" in rec.established_via
    assert rec.establishment_history and rec.establishment_history[0]["decided_by"] == "alice"


def test_human_answer_disagreement_recovers_contradicted_by_verb(tmp_path):
    store = question_queue.QuestionQueueStore(tmp_path)
    registers_layer = _real_registers_layer(tmp_path)
    q = store.add_question(
        domain="dut", question="What is the registers layer status?",
        context_path="iap_test.dut_registers_key",
        options=["LOADED", "NOT_AVAILABLE"], recommendation="LOADED", assumption_if_unanswered="LOADED",
        context={"affects_pass_fail_verdict": True},
    )
    store.answer_question(q["id"], answer="NOT_AVAILABLE", basis="disagreeing on purpose", decided_by="bob")
    manifest = {"dut_facts": {"registers": registers_layer}}
    keys = {"dut_registers": q["question_key"]}
    state = intake_state.build_intake_state(env_manifest=manifest, question_store=store, field_question_keys=keys)
    report = iap.build_intake_audit_provenance(state, question_store=store, field_question_keys=keys)
    rec = report.get("dut_registers")
    assert rec.status == intake_state.IntakeFieldStatus.CONTRADICTED.value
    assert rec.established_by_status == iap.ESTABLISHED_BY_HUMAN
    assert rec.established_by == "bob"
    assert "contradicted_by=" in rec.established_via


# ---------------------------------------------------------------------------
# TIER2_ASSUMPTION: distinct from a real human decision.
# ---------------------------------------------------------------------------

def test_tier2_auto_assumption_reports_tier2_not_human(tmp_path):
    store = question_queue.QuestionQueueStore(tmp_path)
    q = store.add_question(
        domain="env", question="Which build env should intake_state trust?",
        context_path="iap_test.build_env_key",
        options=["envA", "envB"], recommendation="envA", assumption_if_unanswered="envA",
        context={},  # no hard trigger -> TIER2_SAFE_ASSUME, auto-persisted
    )
    assert q["status"] == "ASSUMED"
    keys = {"build_env": q["question_key"]}
    state = intake_state.build_intake_state(build_env_gate=None, question_store=store, field_question_keys=keys)
    report = iap.build_intake_audit_provenance(state, question_store=store, field_question_keys=keys)
    rec = report.get("build_env")
    assert rec.status == intake_state.IntakeFieldStatus.AUTO_RESOLVED.value
    assert rec.established_by_status == iap.ESTABLISHED_BY_TIER2_ASSUMPTION
    assert rec.established_by != "alice"  # never mistaken for a human decider
    assert "strengthened_by=" in rec.established_via
    assert rec.ever_tier2_assumed is True


# ---------------------------------------------------------------------------
# UNVERIFIABLE: the honest "we could not tell" case for CONTRADICTED with no
# decision lookup supplied at all -- must never be defaulted either way.
# ---------------------------------------------------------------------------

def test_contradicted_with_no_lookup_supplied_is_unverifiable_NEGATIVE_CONTROL(tmp_path):
    registers_layer = _real_registers_layer(tmp_path)
    soc_map = {
        "schema_version": "1.0",
        "address_map": [{
            "name": "usb0", "base_address": "0x2000", "size_bytes": 4096,
            "target": "chip.core.usb0", "bus": "AXI4-Lite", "evidence": "soc_spec.md#usb0",
        }],
    }
    p = _write_json(tmp_path / "soc_arch_map.json", soc_map)
    address_layer = env_manifest.build_dut_facts_address_map(str(p), registers_layer=registers_layer)
    assert address_layer["disagreement_count"] == 1  # sanity: a real, purely-computed conflict
    manifest = {"dut_facts": {"registers": registers_layer, "address_map": address_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    # No question_store/field_question_keys supplied to this module at all.
    report = iap.build_intake_audit_provenance(state)
    rec = report.get("dut_address_map")
    assert rec.status == intake_state.IntakeFieldStatus.CONTRADICTED.value
    assert rec.established is True
    assert rec.established_by_status == iap.ESTABLISHED_BY_UNVERIFIABLE
    assert rec.established_by is None  # never guessed


def test_contradicted_with_lookup_supplied_but_no_decision_is_system_computed(tmp_path):
    """The same purely-computed conflict, but this time a real (empty)
    question_store/field_question_keys IS supplied -- confirming no decision
    exists for this field, which lets the module confidently rule out human
    involvement rather than merely reporting UNVERIFIABLE."""
    store = question_queue.QuestionQueueStore(tmp_path)
    registers_layer = _real_registers_layer(tmp_path)
    soc_map = {
        "schema_version": "1.0",
        "address_map": [{
            "name": "usb0", "base_address": "0x2000", "size_bytes": 4096,
            "target": "chip.core.usb0", "bus": "AXI4-Lite", "evidence": "soc_spec.md#usb0",
        }],
    }
    p = _write_json(tmp_path / "soc_arch_map2.json", soc_map)
    address_layer = env_manifest.build_dut_facts_address_map(str(p), registers_layer=registers_layer)
    manifest = {"dut_facts": {"registers": registers_layer, "address_map": address_layer}}
    state = intake_state.build_intake_state(env_manifest=manifest)
    report = iap.build_intake_audit_provenance(
        state, question_store=store, field_question_keys={"dut_address_map": "some_unrelated_key_never_asked"},
    )
    rec = report.get("dut_address_map")
    assert rec.established_by_status == iap.ESTABLISHED_BY_SYSTEM_COMPUTED
    assert rec.established_by == "designer"


# ---------------------------------------------------------------------------
# Report-level shape
# ---------------------------------------------------------------------------

def test_report_carries_state_generated_at_separately_from_any_field():
    state = intake_state.build_intake_state(now="2026-09-07T00:00:00Z")
    report = iap.build_intake_audit_provenance(state)
    assert report.state_generated_at == "2026-09-07T00:00:00Z"
    doc = report.to_dict()
    assert doc["schema_version"] == iap.SCHEMA_VERSION
    assert doc["state_generated_at"] == "2026-09-07T00:00:00Z"
    assert len(doc["records"]) == len(report.records)
    for rec in doc["records"]:
        assert {"field", "category", "status", "confidence", "source", "responsible_owner",
                "established", "established_by", "established_by_status", "established_via",
                "established_at", "established_at_status", "basis", "establishment_history",
                "overturned", "ever_tier2_assumed"} <= set(rec)


def test_record_rejects_unknown_established_by_status():
    with pytest.raises(ValueError):
        iap.IntakeProvenanceRecord(
            field="x", category="general", status="MISSING", confidence="UNKNOWN",
            source="test", responsible_owner=None, established=False, established_by=None,
            established_by_status="NOT_A_REAL_STATUS", established_via=None,
            established_at=None, established_at_status=iap.ESTABLISHED_AT_UNKNOWN, basis="",
        )


def test_execute_verb_build():
    state = intake_state.build_intake_state()
    code, payload = iap.execute_verb(state, "build")
    assert code == 0
    assert payload["schema_version"] == iap.SCHEMA_VERSION


def test_execute_verb_unknown():
    state = intake_state.build_intake_state()
    code, payload = iap.execute_verb(state, "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"
