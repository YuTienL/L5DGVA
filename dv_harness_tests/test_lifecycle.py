"""Standard Flow Wave 1: the persistent lifecycle model (dv_harness/lifecycle.py).

The lifecycle is a SEPARATE persisted model from HarnessState/Status: the owner
requires the 16 project milestones to live beside, never inside, the Status
enum (loop_contract.py's total Status->LoopState map would otherwise fall
through on every new value). Every transition is kept as history, not only as
a single overwritten `last_transition`.
"""
from __future__ import annotations

import json

import pytest

from dv_harness.lifecycle import LifecycleError, LifecycleStore, Milestone
from dv_harness.models import Status

OWNER_MILESTONES = [
    "INTAKE_CREATED", "USER_INPUT_REQUIRED", "INTAKE_LOADED", "INTAKE_PARTIAL",
    "INTAKE_READY", "OPENSPEC_READY", "PLAN_READY", "GENERATED", "BUILD_PASS",
    "SIM_PASS", "REGRESSION_PASS", "COVERAGE_READY", "SIGNOFF_READY",
    "QUALIFICATION_COMPARE", "KC_LEARNING", "COMPLETE",
]
RECORD_FIELDS = {"from_state", "to_state", "trigger", "evidence", "producer",
                 "consumer", "timestamp", "result"}


def _store(tmp_path, sink=None):
    return LifecycleStore(tmp_path, event_sink=sink)


def _created(tmp_path, sink=None):
    s = _store(tmp_path, sink)
    s.create(trigger="dv-harness start", producer="start_lifecycle")
    return s


def test_milestones_are_exactly_the_sixteen_owner_named_values_in_order():
    assert [m.value for m in Milestone] == OWNER_MILESTONES


def test_milestones_never_leak_into_the_status_enum():
    assert {m.value for m in Milestone}.isdisjoint({s.value for s in Status})


def test_store_does_not_exist_until_created(tmp_path):
    s = _store(tmp_path)
    assert s.exists() is False
    with pytest.raises(LifecycleError):
        s.load()


def test_create_records_initial_milestone_and_creation_history(tmp_path):
    s = _created(tmp_path)
    assert s.exists() is True
    assert s.milestone is Milestone.INTAKE_CREATED
    hist = s.load()["history"]
    assert len(hist) == 1
    assert hist[0]["from_state"] is None
    assert hist[0]["to_state"] == "INTAKE_CREATED"
    assert set(hist[0]) == RECORD_FIELDS


def test_create_twice_is_refused_so_history_cannot_be_reset(tmp_path):
    s = _created(tmp_path)
    with pytest.raises(LifecycleError):
        s.create(trigger="again", producer="test")


def test_forward_transition_persists_a_full_audit_record(tmp_path):
    s = _created(tmp_path)
    rec = s.transition(Milestone.USER_INPUT_REQUIRED, trigger="verification_level_unresolved",
                       producer="INTAKE_ROUTING", consumer="question_queue",
                       evidence=["Q-ENV-1"])
    assert set(rec) == RECORD_FIELDS
    assert rec["from_state"] == "INTAKE_CREATED"
    assert rec["to_state"] == "USER_INPUT_REQUIRED"
    assert rec["evidence"] == ["Q-ENV-1"]
    assert rec["timestamp"]
    assert rec["result"] == "ADVANCED"
    # a brand-new store instance (new process) sees the same persisted truth
    again = _store(tmp_path)
    assert again.milestone is Milestone.USER_INPUT_REQUIRED
    assert again.load()["history"][-1] == rec


def test_history_keeps_every_transition_not_only_the_last(tmp_path):
    s = _created(tmp_path)
    s.transition(Milestone.USER_INPUT_REQUIRED, trigger="t1", producer="p")
    s.transition(Milestone.INTAKE_READY, trigger="t2", producer="p")
    hist = s.load()["history"]
    assert [h["to_state"] for h in hist] == [
        "INTAKE_CREATED", "USER_INPUT_REQUIRED", "INTAKE_READY"]


def test_illegal_forward_jump_is_refused_and_leaves_history_untouched(tmp_path):
    s = _created(tmp_path)
    with pytest.raises(LifecycleError):
        s.transition(Milestone.GENERATED, trigger="skip intake", producer="p")
    assert s.milestone is Milestone.INTAKE_CREATED
    assert len(s.load()["history"]) == 1


def test_intake_cannot_be_skipped_on_the_way_to_openspec(tmp_path):
    s = _created(tmp_path)
    with pytest.raises(LifecycleError):
        s.transition(Milestone.OPENSPEC_READY, trigger="skip", producer="p")


def test_rewind_to_an_earlier_milestone_is_allowed_and_marked(tmp_path):
    s = _created(tmp_path)
    s.transition(Milestone.INTAKE_READY, trigger="t", producer="p")
    rec = s.transition(Milestone.USER_INPUT_REQUIRED, trigger="new gap found", producer="p")
    assert rec["result"] == "REWOUND"
    assert s.milestone is Milestone.USER_INPUT_REQUIRED


def test_full_forward_path_reaches_complete(tmp_path):
    s = _created(tmp_path)
    for m in [Milestone.INTAKE_READY, Milestone.OPENSPEC_READY, Milestone.PLAN_READY,
              Milestone.GENERATED, Milestone.BUILD_PASS, Milestone.SIM_PASS,
              Milestone.REGRESSION_PASS, Milestone.COVERAGE_READY, Milestone.SIGNOFF_READY,
              Milestone.QUALIFICATION_COMPARE, Milestone.KC_LEARNING, Milestone.COMPLETE]:
        s.transition(m, trigger="t", producer="p")
    assert s.milestone is Milestone.COMPLETE


def test_coverage_is_optional_on_the_path_to_signoff(tmp_path):
    s = _created(tmp_path)
    for m in [Milestone.INTAKE_READY, Milestone.OPENSPEC_READY, Milestone.PLAN_READY,
              Milestone.GENERATED, Milestone.BUILD_PASS, Milestone.SIM_PASS,
              Milestone.REGRESSION_PASS, Milestone.SIGNOFF_READY]:
        s.transition(m, trigger="t", producer="p")
    assert s.milestone is Milestone.SIGNOFF_READY


def test_transition_requires_a_trigger_and_a_producer(tmp_path):
    s = _created(tmp_path)
    with pytest.raises(ValueError):
        s.transition(Milestone.INTAKE_READY, trigger="", producer="p")
    with pytest.raises(ValueError):
        s.transition(Milestone.INTAKE_READY, trigger="t", producer="")
    assert s.milestone is Milestone.INTAKE_CREATED


def test_every_transition_is_also_emitted_as_an_event(tmp_path):
    seen = []
    s = _created(tmp_path, sink=lambda name, payload: seen.append((name, payload)))
    s.transition(Milestone.INTAKE_READY, trigger="INTAKE stage PASS", producer="INTAKE",
                 evidence=["state.json:INTAKE"])
    names = [n for n, _ in seen]
    assert names == ["LIFECYCLE_TRANSITION", "LIFECYCLE_TRANSITION"]  # creation + advance
    payload = seen[-1][1]
    assert payload["from_state"] == "INTAKE_CREATED"
    assert payload["to_state"] == "INTAKE_READY"
    assert payload["trigger"] == "INTAKE stage PASS"


def test_bypass_is_recorded_in_the_store_and_as_an_event(tmp_path):
    seen = []
    s = _created(tmp_path, sink=lambda n, p: seen.append((n, p)))
    s.record_bypass("run-stage", from_stage="INTAKE_ROUTING", to_stage="DISCOVERY",
                    reason="advanced/manual command")
    b = s.load()["bypasses"]
    assert len(b) == 1 and b[0]["command"] == "run-stage" and b[0]["to_stage"] == "DISCOVERY"
    assert seen[-1][0] == "LIFECYCLE_BYPASS"
    # a bypass must never move the milestone
    assert s.milestone is Milestone.INTAKE_CREATED


def test_facts_are_persisted_beside_the_milestone(tmp_path):
    s = _created(tmp_path)
    s.update_facts(verification_level="IP", level_source="cli_flag", protocols=["usb"])
    got = _store(tmp_path).load()
    assert got["verification_level"] == "IP"
    assert got["level_source"] == "cli_flag"
    assert got["protocols"] == ["usb"]


def test_unknown_fact_key_is_refused(tmp_path):
    s = _created(tmp_path)
    with pytest.raises(LifecycleError):
        s.update_facts(totally_made_up="x")


def test_corrupt_or_unknown_milestone_on_disk_raises_actionable_error(tmp_path):
    s = _created(tmp_path)
    data = json.loads(s.path.read_text(encoding="utf-8"))
    data["milestone"] = "NOT_A_MILESTONE"
    s.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LifecycleError) as ei:
        _store(tmp_path).milestone
    assert "NOT_A_MILESTONE" in str(ei.value)


def test_state_is_persisted_outside_state_json(tmp_path):
    s = _created(tmp_path)
    assert s.path.name == "lifecycle.json"
    assert s.path.parent.name == ".dv-harness"
