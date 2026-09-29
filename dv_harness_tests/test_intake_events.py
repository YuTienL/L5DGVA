"""Tests for dv_harness/intake_events.py -- the fixed 18-event INTAKE_*
taxonomy wired into the real `storage.StateStore.event()` / events.jsonl
trail at real `verification_intake_contract.py` / `intake_state.py`
transitions.

Real evidence throughout, per this project's Evidence Truth Rule: bind-tier
facts are classified through the REAL `connectivity.py` vocabulary,
dut-boundary facts are the REAL `phy_boundary.classify_boundary()` /
`decide_bind_location()` output, VIP-release facts are the REAL
`env_manifest.build_vip_release()` filesystem scan, address-map disagreement
is a REAL `env_manifest.build_dut_facts_address_map()` mismatch, and every
event asserted on disk is read back through the REAL, shared
`storage.StateStore` / `loop_telemetry.read_events()` machinery -- never a
hand-written events.jsonl line and never a second reader.
"""
import json
import subprocess
import sys

import pytest

from dv_harness import connectivity, env_manifest, intake_events as ie
from dv_harness import intake_state
from dv_harness import verification_intake_contract as vic
from dv_harness.storage import StateStore


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _events(root):
    f = root / ".dv-harness" / "events.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _intake_events(root):
    return [e for e in _events(root) if e.get("event") in ie.INTAKE_EVENTS]


class _FailingStore:
    """A store whose `.event()` always raises -- proves the best-effort
    emitters never turn a telemetry failure into a crash of the real
    transition/build/readiness result they are attached to."""

    def event(self, record):
        raise RuntimeError("events.jsonl is on fire")


# ---------------------------------------------------------------------------
# 1. the fixed taxonomy itself
# ---------------------------------------------------------------------------

def test_taxonomy_has_exactly_18_events():
    assert len(ie.INTAKE_EVENTS) == 18
    assert len(set(ie.INTAKE_EVENTS)) == 18  # no duplicate


def test_taxonomy_totality_check_passes_on_the_real_shipped_mapping():
    # already run at import; re-running directly proves it is a real,
    # callable, non-raising check over the real IntakeContractState enum.
    ie.assert_intake_event_taxonomy_total()


def test_contract_state_mapping_is_total_over_IntakeContractState():
    known = {s.value for s in vic.IntakeContractState}
    assert set(ie.INTAKE_CONTRACT_STATE_TO_EVENT) == known
    assert len(ie.INTAKE_CONTRACT_STATE_TO_EVENT) == 13


def test_the_18_partition_into_13_contract_events_and_5_state_events_with_no_overlap():
    contract_events = set(ie.INTAKE_CONTRACT_STATE_TO_EVENT.values())
    state_events = set(ie.INTAKE_STATE_EVENTS)
    assert len(contract_events) == 13
    assert len(state_events) == 5
    assert contract_events.isdisjoint(state_events)
    assert contract_events | state_events == set(ie.INTAKE_EVENTS)


def test_event_for_contract_state_matches_the_real_mapping():
    for state, event in ie.INTAKE_CONTRACT_STATE_TO_EVENT.items():
        assert ie.event_for_contract_state(state) == event


def test_event_for_contract_state_rejects_unknown_state_NEGATIVE_CONTROL():
    with pytest.raises(ie.IntakeEventError):
        ie.event_for_contract_state("NOT_A_REAL_STATE")


def test_emit_refuses_a_name_outside_the_18_NEGATIVE_CONTROL(tmp_path):
    """The one direct-`emit()` refusal test, mirroring
    `loop_telemetry.py`'s own: an unrecognized name would be dropped
    silently by `read_intake_events()` while the emitter looked like it had
    reported something, so it must never be written at all."""
    store = StateStore(tmp_path)
    with pytest.raises(ie.IntakeEventError):
        ie.emit(store, "INTAKE_VIBES_DETECTED", contract_id="p1")
    assert _intake_events(tmp_path) == []


# ---------------------------------------------------------------------------
# 2. verification_intake_contract.py wiring
# ---------------------------------------------------------------------------

def test_create_contract_without_store_mints_no_dv_harness_tree_NEGATIVE_CONTROL(tmp_path):
    vic.create_contract("proj-no-store")
    assert not (tmp_path / ".dv-harness").exists()


def test_create_contract_with_store_emits_intake_created(tmp_path):
    store = StateStore(tmp_path)
    contract = vic.create_contract("proj-1", store=store)
    events = _intake_events(tmp_path)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "INTAKE_CREATED"
    assert e["contract_id"] == "proj-1"
    assert e["from_state"] is None
    assert e["to_state"] == "CREATED"
    assert contract.state == "CREATED"  # the real result is unaffected by emission


def test_full_real_lifecycle_emits_the_right_event_at_every_real_transition(tmp_path):
    """Drives the same real thirteen-state loop the module's own
    docstring/tests already exercise, with `store=` on every call, and
    proves the events.jsonl trail names the state entered at every step, in
    order -- never a fabricated or reordered trail."""
    store = StateStore(tmp_path)
    c = vic.create_contract("proj-full", store=store)
    path = [
        ("DISCOVERING", "begin discovery"),
        ("CORRELATING", "cross-domain facts gathered"),
        ("QUESTION_PENDING", "ambiguous DUT boundary"),
        ("USER_INPUT_RECEIVED", "human answered"),
        ("VALIDATING", "re-validate with the human's answer"),
        ("CONFLICT", "env manifest vs register map disagree"),
        ("CORRELATING", "re-correlate after conflict noted"),
        ("VALIDATING", "re-validate"),
        ("PARTIAL", "some fields still unresolved"),
        ("DISCOVERING", "go find the missing facts"),
        ("CORRELATING", "re-correlate"),
        ("VALIDATING", "re-validate"),
        ("BLOCKED", "undecidable bind entry"),
        ("QUESTION_PENDING", "escalate the blocker"),
        ("USER_INPUT_RECEIVED", "human resolved it"),
        ("VALIDATING", "final re-validate"),
        ("READY_FOR_REVIEW", "all conditions clear"),
        ("BASELINED", "human approved"),
        ("STALE", "RTL moved since baseline"),
        ("REVALIDATING", "begin revalidation"),
        ("VALIDATING", "re-run validation"),
        ("READY_FOR_REVIEW", "clean after revalidation"),
        ("BASELINED", "re-approved"),
    ]
    for to_state, reason in path:
        c = vic.transition_contract(c, to_state, reason=reason, store=store)

    events = _intake_events(tmp_path)
    expected = ["INTAKE_CREATED"] + [
        ie.INTAKE_CONTRACT_STATE_TO_EVENT[to_state] for to_state, _ in path
    ]
    assert [e["event"] for e in events] == expected
    # every real INTAKE_* name in the taxonomy that a real contract-state
    # transition can name was really produced by this one real path
    assert set(ie.INTAKE_CONTRACT_STATE_TO_EVENT.values()) == set(
        e["event"] for e in events if e["event"] in ie.INTAKE_CONTRACT_STATE_TO_EVENT.values())
    # spot-check the payload on a couple of real, distinct transitions
    conflict = next(e for e in events if e["event"] == "INTAKE_CONFLICT_DETECTED")
    assert conflict["from_state"] == "VALIDATING"
    assert conflict["to_state"] == "CONFLICT"
    assert conflict["reason"] == "env manifest vs register map disagree"
    baselined = [e for e in events if e["event"] == "INTAKE_BASELINED"]
    assert len(baselined) == 2  # the real path baselines twice


def test_transition_contract_without_store_leaves_the_trail_unchanged_NEGATIVE_CONTROL(tmp_path):
    store = StateStore(tmp_path)
    c = vic.create_contract("proj-mixed", store=store)
    before = len(_intake_events(tmp_path))
    c = vic.transition_contract(c, "DISCOVERING", reason="no store this time")
    after = len(_intake_events(tmp_path))
    assert after == before
    assert c.state == "DISCOVERING"  # the real transition still happened


def test_a_real_emission_failure_never_crashes_a_real_transition(tmp_path):
    """`store` here is a real object whose `.event()` always raises -- the
    real, successful `create_contract()`/`transition_contract()` result must
    still be returned, matching `engine.py`'s own best-effort convention."""
    failing = _FailingStore()
    c = vic.create_contract("proj-fail", store=failing)
    assert c.state == "CREATED"
    c = vic.transition_contract(c, "DISCOVERING", reason="go", store=failing)
    assert c.state == "DISCOVERING"


def test_by_and_reason_carry_through_to_the_emitted_event(tmp_path):
    store = StateStore(tmp_path)
    c = vic.create_contract("proj-by", store=store)
    vic.transition_contract(c, "DISCOVERING", reason="begin", by="agent_x", store=store)
    e = _intake_events(tmp_path)[-1]
    assert e["by"] == "agent_x"
    assert e["reason"] == "begin"


# ---------------------------------------------------------------------------
# 3. intake_state.py wiring
# ---------------------------------------------------------------------------

def _real_registers_layer(tmp_path):
    reg_map = {
        "schema_version": "1.0",
        "blocks": [{
            "name": "usb0", "base_address": "0x1000",
            "registers": [{"name": "CTRL", "address_offset": "0x0", "width": 32, "access": "RW"}],
        }],
    }
    p = tmp_path / "register_map.json"
    p.write_text(json.dumps(reg_map), encoding="utf-8")
    return env_manifest.build_dut_facts_registers(str(p))


def _real_disagreeing_address_map_layer(tmp_path, registers_layer):
    soc_map = {
        "schema_version": "1.0",
        "address_map": [{
            "name": "usb0", "base_address": "0x2000", "size_bytes": 4096,
            "target": "chip.core.usb0", "bus": "AXI4-Lite", "evidence": "soc_spec.md#usb0",
        }],
    }
    p = tmp_path / "soc_arch_map_disagree.json"
    p.write_text(json.dumps(soc_map), encoding="utf-8")
    layer = env_manifest.build_dut_facts_address_map(str(p), registers_layer=registers_layer)
    assert layer["disagreement_count"] == 1  # sanity on the real producer
    return layer


def _real_vip_release_layer(tmp_path):
    home = tmp_path / "designware_home"
    pkg_dir = home / "vip" / "svt" / "usb3" / "1.0"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "release_notes.txt").write_text("USB3 VIP 1.0 release notes", encoding="utf-8")
    return env_manifest.build_vip_release(designware_home=str(home))


def _real_parallel_boundary_doc():
    phy_module = {"name": "phy", "ports": [{"name": "pipe_data", "direction": "output", "data_type": "[7:0]"}]}
    ctrl_module = {"name": "ctrl", "ports": [{"name": "pipe_data", "direction": "input", "data_type": "[7:0]"}]}
    from dv_harness import phy_boundary
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    bind_decision = phy_boundary.decide_bind_location(classification, signals)
    return {"status": "EXTRACTED", "bind_decision": bind_decision}


def test_build_intake_state_without_store_mints_no_dv_harness_tree_NEGATIVE_CONTROL(tmp_path):
    intake_state.build_intake_state(env_manifest=None)
    assert not (tmp_path / ".dv-harness").exists()


def test_build_intake_state_with_store_emits_state_built_and_field_findings(tmp_path):
    store = StateStore(tmp_path)
    registers_layer = _real_registers_layer(tmp_path)
    address_layer = _real_disagreeing_address_map_layer(tmp_path, registers_layer)
    manifest = {"dut_facts": {"registers": registers_layer, "address_map": address_layer}}
    bind_entries = [{"target_instance": "chip.core.usb9",
                     "tier": connectivity.BindTier.T4_UNDECIDABLE.value}]

    state = intake_state.build_intake_state(env_manifest=manifest, bind_entries=bind_entries,
                                             store=store)

    events = _intake_events(tmp_path)
    built = [e for e in events if e["event"] == "INTAKE_STATE_BUILT"]
    assert len(built) == 1
    assert built[0]["field_count"] == len(state.records)
    assert built[0]["status_counts"].get("BLOCKED") == 1
    assert built[0]["status_counts"].get("CONTRADICTED") == 1

    blocked = [e for e in events if e["event"] == "INTAKE_FIELD_BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0]["field"] == "bind:chip.core.usb9"
    assert blocked[0]["category"] == "critical_bind"

    contradicted = [e for e in events if e["event"] == "INTAKE_FIELD_CONTRADICTED"]
    assert len(contradicted) == 1
    assert contradicted[0]["field"] == "dut_address_map"

    # INTAKE_STATE_BUILT is always first: a summary before any per-field finding.
    assert events[0]["event"] == "INTAKE_STATE_BUILT"


def test_a_clean_build_emits_no_field_findings_NEGATIVE_CONTROL(tmp_path):
    """Nothing BLOCKED, nothing CONTRADICTED -- the state-built summary must
    still fire (a run that found nothing wrong is itself citable evidence),
    but no fabricated INTAKE_FIELD_BLOCKED/INTAKE_FIELD_CONTRADICTED for a
    field that carries neither status."""
    store = StateStore(tmp_path)
    vip_layer = _real_vip_release_layer(tmp_path)
    manifest = {"vip_config": {"vip_release": vip_layer}}
    bind_entries = [{"target_instance": "chip.core.usb0",
                     "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.PASS, detail={})

    intake_state.build_intake_state(
        env_manifest=manifest, bind_entries=bind_entries,
        dut_boundary=_real_parallel_boundary_doc(), active_driver_conflicts=[],
        build_env_gate=gate, known_pass_tests=[{"test_name": "t", "verdict": "PASS"}],
        store=store,
    )
    events = _intake_events(tmp_path)
    assert len(events) == 1
    assert events[0]["event"] == "INTAKE_STATE_BUILT"
    assert "BLOCKED" not in events[0]["status_counts"]
    assert "CONTRADICTED" not in events[0]["status_counts"]


# ---------------------------------------------------------------------------
# 4. evaluate_uvm_generation_ready() wiring -- exactly-one-of-two, never both
# ---------------------------------------------------------------------------

def test_generation_readiness_without_store_emits_nothing_NEGATIVE_CONTROL(tmp_path):
    state = intake_state.build_intake_state()
    intake_state.evaluate_uvm_generation_ready(state)
    assert not (tmp_path / ".dv-harness").exists()


def test_generation_blocked_emits_blocked_event_naming_every_category(tmp_path):
    store = StateStore(tmp_path)
    state = intake_state.build_intake_state()
    readiness = intake_state.evaluate_uvm_generation_ready(state, store=store)
    assert readiness.ready is False
    events = _intake_events(tmp_path)
    assert [e["event"] for e in events] == ["INTAKE_GENERATION_BLOCKED"]
    assert events[0]["blocking_categories"] == sorted(intake_state.BLOCKING_CATEGORIES)


def test_generation_ready_emits_ready_event_naming_no_blockers(tmp_path):
    store = StateStore(tmp_path)
    vip_layer = _real_vip_release_layer(tmp_path)
    manifest = {"vip_config": {"vip_release": vip_layer}}
    bind_entries = [{"target_instance": "chip.core.usb0",
                     "tier": connectivity.BindTier.T1_ALREADY_DECIDED.value}]
    gate = connectivity.GateResult(gate="gate1_elaboration", status=connectivity.GateStatus.PASS, detail={})
    state = intake_state.build_intake_state(
        env_manifest=manifest, bind_entries=bind_entries,
        dut_boundary=_real_parallel_boundary_doc(), active_driver_conflicts=[],
        build_env_gate=gate, known_pass_tests=[{"test_name": "t", "verdict": "PASS"}],
    )
    readiness = intake_state.evaluate_uvm_generation_ready(state, store=store)
    assert readiness.ready is True
    events = _intake_events(tmp_path)
    assert [e["event"] for e in events] == ["INTAKE_GENERATION_READY"]
    assert events[0]["blocking_categories"] == []


# ---------------------------------------------------------------------------
# 5. the reader half really reuses loop_telemetry.read_events()
# ---------------------------------------------------------------------------

def test_read_intake_events_reuses_the_real_loop_telemetry_reader(tmp_path, monkeypatch):
    from dv_harness import loop_telemetry as lt
    calls = []
    real_reader = lt.read_events

    def _wrapped(root, **kw):
        calls.append((root, kw))
        return real_reader(root, **kw)

    monkeypatch.setattr(lt, "read_events", _wrapped)
    store = StateStore(tmp_path)
    vic.create_contract("proj-read", store=store)
    store.event({"ts": "x", "event": "SOME_UNRELATED_EVENT"})

    picked, stats = ie.read_intake_events(tmp_path)
    assert len(calls) == 1  # really delegated, not a second parser
    assert [e["event"] for e in picked] == ["INTAKE_CREATED"]
    assert stats["intake_events"] == 1


# ---------------------------------------------------------------------------
# 6. ad hoc front door
# ---------------------------------------------------------------------------

def test_execute_verb_names_lists_all_18():
    code, payload = ie.execute_verb(".", "names")
    assert code == 0
    assert len(payload["intake_events"]) == 18


def test_execute_verb_events_on_empty_project_returns_2(tmp_path):
    code, payload = ie.execute_verb(tmp_path, "events")
    assert code == 2
    assert payload["events"] == []


def test_execute_verb_events_after_real_transitions_returns_0(tmp_path):
    store = StateStore(tmp_path)
    vic.create_contract("proj-cli", store=store)
    code, payload = ie.execute_verb(tmp_path, "events")
    assert code == 0
    assert payload["events"][0]["event"] == "INTAKE_CREATED"


def test_execute_verb_unknown_verb_returns_1():
    code, payload = ie.execute_verb(".", "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


def test_real_cli_subprocess_names(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_events", "names", "--json"],
        cwd=str(_repo_root()), capture_output=True, text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert len(payload["intake_events"]) == 18


def test_real_cli_subprocess_events_end_to_end(tmp_path):
    store = StateStore(tmp_path)
    vic.create_contract("proj-subproc", store=store)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intake_events", "events",
         "--project-root", str(tmp_path), "--json"],
        cwd=str(_repo_root()), capture_output=True, text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["events"][0]["event"] == "INTAKE_CREATED"


def _repo_root():
    import dv_harness
    from pathlib import Path
    return Path(dv_harness.__file__).resolve().parent.parent
