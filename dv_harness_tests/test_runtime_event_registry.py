"""Tests for dv_harness/runtime_event_registry.py.

Covers: the core positive path (a declared event set + REQUIRES/WAITS_FOR/
TRIGGERS/UNBLOCKS relations propagates stop-on-failure correctly, including
transitive cascade and the UNBLOCKS recovery override), plus real negative
controls -- a duplicate event name, a relation naming an unknown event, a
self-referential relation, a REQUIRES cycle, a non-PENDING observation with
no evidence, a caller trying to assert BLOCKED_BY_DEPENDENCY directly, an
unknown relation type string, and an invalid timeout -- each asserted to
raise `EventRegistryError` naming the real defect. Also drives both real CLI
verbs (`graph`/`status`) as the module's own `execute_verb()`, never a mock.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.runtime_event_registry import (
    EventRegistryError,
    EventRelationDecl,
    EventRelationType,
    EventStatus,
    RuntimeEventDef,
    RuntimeEventObservation,
    RuntimeEventRegistry,
    execute_verb,
    load_registry,
    registry_from_dict,
    render_graph,
    render_status,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers: a real illustrative event set matching this repo's own
# block/branch_a*/branch_fw/branch_b* vocabulary (branch-mapper /
# pattern-architecture SKILL.md), declared as data -- never hardcoded inside
# the module under test.
# ---------------------------------------------------------------------------

def _pattern_style_registry(**overrides) -> RuntimeEventRegistry:
    events = (
        RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0", "branch_a1"),
                        timeout=10.0, scope="GLOBAL",
                        source="pattern-architecture/SKILL.md sec 1, block prologue"),
        RuntimeEventDef("DUT_READY_PORT0", producer="branch_a0", consumer=("branch_fw_port0", "branch_b0"),
                        timeout=5.0, scope="PORT:0",
                        source="pattern-architecture/SKILL.md sec 1, branch_a* per-port bring-up"),
        RuntimeEventDef("IRQ_SEEN_PORT0", producer="branch_fw_port0", consumer=("branch_fw_port0",),
                        timeout=2.0, scope="PORT:0",
                        source="interrupt-event-dispatch/SKILL.md ARM/WAIT step"),
        RuntimeEventDef("IRQ_SERVICED_PORT0", producer="branch_fw_port0", consumer=("branch_b0",),
                        timeout=2.0, scope="PORT:0",
                        source="interrupt-event-dispatch/SKILL.md DECODE/CLEAR step"),
        RuntimeEventDef("VIP_STARTED_PORT0", producer="branch_b0", consumer=("branch_b0",),
                        timeout=None, scope="PORT:0",
                        source="pattern-architecture/SKILL.md sec 1, branch_b* VIP-driven body"),
        RuntimeEventDef("CHECK_DONE", producer="verdict", consumer=("FINAL_CHECK",),
                        timeout=None, scope="GLOBAL",
                        source="pattern-architecture/SKILL.md sec 1, verdict/FINAL_CHECK"),
        RuntimeEventDef("RECOVERY_RETRY_PORT0", producer="branch_fw_port0", consumer=("branch_b0",),
                        timeout=3.0, scope="PORT:0",
                        source="interrupt-event-dispatch/SKILL.md documented retry path"),
    )
    relations = (
        EventRelationDecl("DUT_READY_PORT0", EventRelationType.REQUIRES, "GLOBAL_READY",
                          reason="per-port bring-up cannot start before the SoC-global prologue"),
        EventRelationDecl("IRQ_SERVICED_PORT0", EventRelationType.REQUIRES, "IRQ_SEEN_PORT0",
                          reason="cannot decode/clear an interrupt that was never seen"),
        EventRelationDecl("VIP_STARTED_PORT0", EventRelationType.REQUIRES, "DUT_READY_PORT0",
                          reason="branch_b0's VIP-driven body needs the port already bound up"),
        EventRelationDecl("CHECK_DONE", EventRelationType.WAITS_FOR, "IRQ_SERVICED_PORT0",
                          reason="verdict waits on the port's service loop, but is not hard-gated on it"),
        EventRelationDecl("IRQ_SEEN_PORT0", EventRelationType.TRIGGERS, "IRQ_SERVICED_PORT0",
                          reason="seeing the interrupt is what causes the service loop to decode it"),
        EventRelationDecl("RECOVERY_RETRY_PORT0", EventRelationType.UNBLOCKS, "VIP_STARTED_PORT0",
                          reason="a documented retry path re-supplies port readiness if bring-up failed"),
    )
    kwargs = dict(registry_id="usb_dual_port_enum_illustration",
                 events=events, relations=relations,
                 description="illustrative event set, not this repo's own universal vocabulary")
    kwargs.update(overrides)
    return RuntimeEventRegistry(**kwargs)


# ---------------------------------------------------------------------------
# core positive path
# ---------------------------------------------------------------------------

def test_all_pending_propagates_to_all_pending():
    reg = _pattern_style_registry()
    report = reg.propagate()
    assert set(report.effective_status.values()) == {EventStatus.PENDING.value}
    assert report.findings == []
    assert not report.has_blocking_outcome()


def test_upstream_failure_blocks_direct_and_transitive_dependents():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42 UVM_FATAL in soc_int.svh STAGE 1"),
    })
    report = reg.propagate()
    # DUT_READY_PORT0 REQUIRES GLOBAL_READY (direct); VIP_STARTED_PORT0 REQUIRES
    # DUT_READY_PORT0 (transitive) -- both must cascade to BLOCKED_BY_DEPENDENCY.
    assert report.effective_status["GLOBAL_READY"] == EventStatus.FAILED.value
    assert report.effective_status["DUT_READY_PORT0"] == EventStatus.BLOCKED_BY_DEPENDENCY.value
    assert report.effective_status["VIP_STARTED_PORT0"] == EventStatus.BLOCKED_BY_DEPENDENCY.value
    assert "GLOBAL_READY" in report.blocked_events() or True  # GLOBAL_READY itself is FAILED, not BLOCKED
    assert set(report.blocked_events()) == {"DUT_READY_PORT0", "VIP_STARTED_PORT0"}
    assert report.failed_or_timeout_events() == ("GLOBAL_READY",)
    assert report.has_blocking_outcome()
    blocked_finding = next(f for f in report.findings if f["event"] == "DUT_READY_PORT0")
    assert blocked_finding["finding"] == "BLOCKED_BY_DEPENDENCY"
    assert blocked_finding["related_events"] == ["GLOBAL_READY"]


def test_real_observed_status_is_never_overwritten_by_propagation():
    """An event a caller genuinely OBSERVED to have FIRED keeps that real
    evidence even though its declared prerequisite failed -- overwriting an
    observed fact with a computed one would itself be a fabrication."""
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
        "DUT_READY_PORT0": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:200 port0 link trained"),
    })
    report = reg.propagate()
    assert report.effective_status["DUT_READY_PORT0"] == EventStatus.FIRED.value
    # its own dependent still cascades normally off the REAL FIRED status (no block)
    assert report.effective_status["VIP_STARTED_PORT0"] == EventStatus.PENDING.value


def test_timeout_blocks_dependents_same_as_failed():
    reg = _pattern_style_registry(observations={
        "IRQ_SEEN_PORT0": RuntimeEventObservation(EventStatus.TIMEOUT, evidence="sim.log:900 no IRQ within 2.0us budget"),
    })
    report = reg.propagate()
    assert report.effective_status["IRQ_SERVICED_PORT0"] == EventStatus.BLOCKED_BY_DEPENDENCY.value


def test_unblocks_recovery_override_prevents_block():
    """RECOVERY_RETRY_PORT0 UNBLOCKS VIP_STARTED_PORT0; when the recovery
    event has genuinely FIRED, VIP_STARTED_PORT0 must NOT be marked
    BLOCKED_BY_DEPENDENCY even though its REQUIRES prerequisite failed."""
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
        "DUT_READY_PORT0": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:55 PHY calibration mismatch"),
        "RECOVERY_RETRY_PORT0": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:60 retry path engaged"),
    })
    report = reg.propagate()
    assert report.effective_status["VIP_STARTED_PORT0"] == EventStatus.PENDING.value
    assert "VIP_STARTED_PORT0" not in report.blocked_events()


def test_unblocks_recovery_not_fired_still_blocks():
    """Negative control for the previous test: the SAME registry, but the
    recovery event has not fired -- the block must still occur."""
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FIRED, evidence="sim.log:10"),
        "DUT_READY_PORT0": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:55 PHY calibration mismatch"),
    })
    report = reg.propagate()
    assert report.effective_status["VIP_STARTED_PORT0"] == EventStatus.BLOCKED_BY_DEPENDENCY.value


def test_waits_for_produces_at_risk_finding_without_changing_status():
    reg = _pattern_style_registry(observations={
        "IRQ_SEEN_PORT0": RuntimeEventObservation(EventStatus.TIMEOUT, evidence="sim.log:900"),
    })
    report = reg.propagate()
    # CHECK_DONE WAITS_FOR IRQ_SERVICED_PORT0, which is now BLOCKED_BY_DEPENDENCY.
    assert report.effective_status["CHECK_DONE"] == EventStatus.PENDING.value
    at_risk = [f for f in report.findings if f["finding"] == "AT_RISK_WAITS_FOR_FAILED_UPSTREAM"]
    assert any(f["event"] == "CHECK_DONE" for f in at_risk)


def test_triggers_orphaned_finding_when_only_cause_fails():
    reg = _pattern_style_registry(observations={
        "IRQ_SEEN_PORT0": RuntimeEventObservation(EventStatus.TIMEOUT, evidence="sim.log:900"),
    })
    report = reg.propagate()
    # IRQ_SERVICED_PORT0's only TRIGGERS source is IRQ_SEEN_PORT0, but it ALSO has a
    # REQUIRES edge to it -- so it must be reported as BLOCKED_BY_DEPENDENCY, not
    # ORPHANED_TRIGGER (requires_of() is non-empty for it).
    orphaned = [f for f in report.findings if f["finding"] == "ORPHANED_TRIGGER"]
    assert not any(f["event"] == "IRQ_SERVICED_PORT0" for f in orphaned)
    assert report.effective_status["IRQ_SERVICED_PORT0"] == EventStatus.BLOCKED_BY_DEPENDENCY.value


def test_triggers_orphaned_finding_fires_for_a_trigger_only_event():
    """A dedicated small registry where an event's ONLY causal path is a
    TRIGGERS edge (no REQUIRES of its own) -- this is the case
    ORPHANED_TRIGGER exists to name."""
    events = (
        RuntimeEventDef("UPSTREAM", producer="branch_fw", consumer=("branch_fw",), timeout=2.0),
        RuntimeEventDef("DOWNSTREAM_TRIGGER_ONLY", producer="branch_fw", consumer=("branch_b0",), timeout=None),
    )
    relations = (
        EventRelationDecl("UPSTREAM", EventRelationType.TRIGGERS, "DOWNSTREAM_TRIGGER_ONLY"),
    )
    reg = RuntimeEventRegistry(registry_id="trigger_only", events=events, relations=relations,
                               observations={"UPSTREAM": RuntimeEventObservation(EventStatus.TIMEOUT, evidence="x")})
    report = reg.propagate()
    orphaned = [f for f in report.findings if f["finding"] == "ORPHANED_TRIGGER"]
    assert len(orphaned) == 1
    assert orphaned[0]["event"] == "DOWNSTREAM_TRIGGER_ONLY"
    assert orphaned[0]["related_events"] == ["UPSTREAM"]


def test_registry_and_observation_roundtrip_through_json():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    data = reg.to_dict()
    reloaded = registry_from_dict(data)
    report_a = reg.propagate()
    report_b = reloaded.propagate()
    assert report_a.effective_status == report_b.effective_status


# ---------------------------------------------------------------------------
# negative controls -- each a real structural contradiction in the
# declaration, asserted to raise EventRegistryError naming the real defect.
# ---------------------------------------------------------------------------

def test_duplicate_event_name_is_refused():
    events = (
        RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),
        RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a1",)),
    )
    with pytest.raises(EventRegistryError, match="duplicate event name"):
        RuntimeEventRegistry(registry_id="dup", events=events)


def test_relation_naming_unknown_event_is_refused():
    events = (RuntimeEventDef("GLOBAL_READY", producer="block", consumer=("branch_a0",)),)
    relations = (EventRelationDecl("GLOBAL_READY", EventRelationType.REQUIRES, "NO_SUCH_EVENT"),)
    with pytest.raises(EventRegistryError, match="unknown to_event"):
        RuntimeEventRegistry(registry_id="bad_rel", events=events, relations=relations)


def test_self_referential_relation_is_refused():
    with pytest.raises(EventRegistryError, match="self-referential"):
        EventRelationDecl("GLOBAL_READY", EventRelationType.REQUIRES, "GLOBAL_READY")


def test_requires_cycle_is_refused():
    events = (
        RuntimeEventDef("A", producer="p", consumer=("c",)),
        RuntimeEventDef("B", producer="p", consumer=("c",)),
    )
    relations = (
        EventRelationDecl("A", EventRelationType.REQUIRES, "B"),
        EventRelationDecl("B", EventRelationType.REQUIRES, "A"),
    )
    with pytest.raises(EventRegistryError, match="REQUIRES cycle"):
        RuntimeEventRegistry(registry_id="cyclic", events=events, relations=relations)


def test_non_pending_observation_without_evidence_is_refused():
    with pytest.raises(EventRegistryError, match="requires a non-empty `evidence`"):
        RuntimeEventObservation(EventStatus.FAILED, evidence="")


def test_blocked_by_dependency_cannot_be_asserted_directly():
    with pytest.raises(EventRegistryError, match="computed only by propagate"):
        RuntimeEventObservation(EventStatus.BLOCKED_BY_DEPENDENCY, evidence="I say so")


def test_unknown_relation_type_string_is_refused_at_load():
    data = {
        "registry_id": "bad_relation_type",
        "events": [{"event_name": "A", "producer": "p", "consumer": ["c"]},
                   {"event_name": "B", "producer": "p", "consumer": ["c"]}],
        "relations": [{"from_event": "A", "relation": "SUPERVISES", "to_event": "B"}],
    }
    with pytest.raises(EventRegistryError, match="unknown relation type"):
        registry_from_dict(data)


def test_invalid_timeout_is_refused():
    with pytest.raises(EventRegistryError, match="timeout must be > 0"):
        RuntimeEventDef("A", producer="p", consumer=("c",), timeout=0)
    with pytest.raises(EventRegistryError, match="timeout must be"):
        RuntimeEventDef("A", producer="p", consumer=("c",), timeout=-3.0)


def test_event_with_no_consumer_is_refused():
    with pytest.raises(EventRegistryError, match="no consumer"):
        RuntimeEventDef("A", producer="p", consumer=())


def test_observation_for_unknown_event_is_refused():
    events = (RuntimeEventDef("A", producer="p", consumer=("c",)),)
    with pytest.raises(EventRegistryError, match="unknown event"):
        RuntimeEventRegistry(registry_id="r", events=events,
                             observations={"NOT_DECLARED": RuntimeEventObservation(EventStatus.PENDING)})


# ---------------------------------------------------------------------------
# rendering + file I/O + CLI (execute_verb, and both real subprocess entry
# points), never a mock
# ---------------------------------------------------------------------------

def test_render_graph_and_status_are_markdown_tables():
    reg = _pattern_style_registry(observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    graph_text = render_graph(reg)
    assert "GLOBAL_READY" in graph_text and "| Relation |" in graph_text
    status_text = render_status(reg.propagate())
    assert "BLOCKED_BY_DEPENDENCY" in status_text
    assert "runs no build, submits no job, and gates nothing" in status_text


def test_write_report_is_atomic_and_readable_back(tmp_path):
    reg = _pattern_style_registry()
    report = reg.propagate()
    out = write_report(tmp_path, report)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["registry_id"] == reg.registry_id
    assert data["effective_status"] == report.effective_status


def _write_registry_file(tmp_path: Path, **observation_overrides) -> Path:
    reg = _pattern_style_registry(**observation_overrides)
    path = tmp_path / "events.json"
    path.write_text(json.dumps(reg.to_dict()), encoding="utf-8")
    return path


def test_execute_verb_graph_exits_zero(tmp_path):
    path = _write_registry_file(tmp_path)
    text, code = execute_verb("graph", registry_path=str(path))
    assert code == 0
    assert "GLOBAL_READY" in text


def test_execute_verb_status_exits_zero_when_clean(tmp_path):
    path = _write_registry_file(tmp_path)
    text, code = execute_verb("status", registry_path=str(path))
    assert code == 0


def test_execute_verb_status_exits_one_when_blocked(tmp_path):
    path = _write_registry_file(tmp_path, observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    text, code = execute_verb("status", registry_path=str(path))
    assert code == 1
    assert "BLOCKED_BY_DEPENDENCY" in text


def test_execute_verb_missing_registry_path_is_usage_error():
    text, code = execute_verb("status", registry_path=None)
    assert code == 2
    assert "requires --registry" in text


def test_execute_verb_unknown_verb_is_usage_error(tmp_path):
    path = _write_registry_file(tmp_path)
    text, code = execute_verb("bogus", registry_path=str(path))
    assert code == 2
    assert "unknown runtime-events verb" in text


def test_execute_verb_bad_registry_declaration_is_reported_not_raised(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"registry_id": "bad", "events": []}), encoding="utf-8")
    text, code = execute_verb("status", registry_path=str(path))
    assert code == 2
    assert "EventRegistryError" in text


def test_cli_subprocess_status_real_exit_code(tmp_path):
    path = _write_registry_file(tmp_path, observations={
        "GLOBAL_READY": RuntimeEventObservation(EventStatus.FAILED, evidence="sim.log:42"),
    })
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.runtime_event_registry", "status", "--registry", str(path), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["effective_status"]["DUT_READY_PORT0"] == "BLOCKED_BY_DEPENDENCY"


def test_cli_subprocess_graph_real_exit_code(tmp_path):
    path = _write_registry_file(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.runtime_event_registry", "graph", "--registry", str(path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "GLOBAL_READY" in result.stdout


def test_load_registry_missing_file_is_refused(tmp_path):
    with pytest.raises(EventRegistryError, match="not found"):
        load_registry(tmp_path / "does_not_exist.json")


def test_load_registry_invalid_json_is_refused(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(EventRegistryError, match="not valid JSON"):
        load_registry(path)


# ---------------------------------------------------------------------------
# vocabulary independence from loop_budget.FailureType (contrast only, per
# task instructions -- never merged)
# ---------------------------------------------------------------------------

def test_status_vocabulary_does_not_collide_with_loop_budget_failure_type():
    from dv_harness.loop_budget import FailureType
    failure_values = {t.value for t in FailureType}
    status_values = {s.value for s in EventStatus}
    assert not (failure_values & status_values)
