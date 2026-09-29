"""Tests for dv_harness/subsystem_discovery.py -- SYS-1..SYS-4 of the
System-Level Verification Integration workflow.

Every fixture here is SYNTHETIC and built inside a tmp_path: a fake subsystem
registry, fake subsystem environment trees, a fake declared-candidate file, a
fake Knowledge Center client. Nothing touches the real
.dv-harness/soc-composer/subsystem_environment_registry.json (which is
legitimately absent in this repo), no network call is made, and nothing under
test generates System-Level UVM source, a System command.txt or a virtual
sequencer -- SYS-1..4 is discovery/analysis/reporting only.

The suite deliberately includes conflicting/ambiguous cases rather than a
happy path only: a subsystem whose recorded clock/reset verdict FAILs, one on
disk that was never registered, two candidates pointing at ONE environment
tree, a Knowledge Center record whose GIT_SHA contradicts the repository, and
a claim whose release_sha disagrees with the registry (the case that is
genuinely EXISTS_UNKNOWN rather than any kind of PASS or FAIL).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import subsystem_discovery as sd
from dv_harness.environment_mode_router import resolve_environment_mode
from dv_harness.knowledge_center import (
    SUBSYSTEM_RECORD_FIELDS, normalize_subsystem_record,
)

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "real_env" / "system_level_validator.py"
REGISTRATION_GATE = (ROOT / "tools" / "verification_flow"
                     / "subsystem_environment_registration_gate.py")


# --- synthetic fixtures ------------------------------------------------------

def _write_env_tree(base: Path, *, complete: bool = True) -> Path:
    """A synthetic subsystem verification environment covering every SYS-4
    factor. `complete=False` drops the scoreboard/command.txt/regression
    artifacts, which is what makes a PARTIAL readiness reachable."""
    base.mkdir(parents=True, exist_ok=True)
    files = {
        "rtl/dut_core.sv": "// synthetic RTL",
        "env/foo_env.sv": "// synthetic uvm env",
        "env/foo_agent.sv": "// synthetic agent",
        "vip/svt_foo_vip.sv": "// synthetic vip setup",
        "Makefile": "all:\n\techo synthetic\n",
        "filelist.f": "-f nothing\n",
        "test/foo_test.sv": "// synthetic test",
        "seq/foo_seq.sv": "// synthetic sequence",
        "tb/tb_top.sv": "// synthetic top",
        "cfg/foo_config.sv": "// synthetic config object",
        "cfg/clock_reset_assumptions.json": "{}",
        "logs/sim.log": "UVM_ERROR : 0\n",
        "docs/readme.md": "synthetic",
    }
    if complete:
        files["env/foo_scoreboard.sv"] = "// synthetic scoreboard"
        files["command.txt"] = "# synthetic command file, fixture only\n"
        files["regression.list"] = "foo_test PASS\n"
    for rel, content in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return base


def _registry_entry(name, *, sha="a" * 12, iface="PASS", clk="PASS",
                    state="REGRESSION_QUALIFIED", drop=()):
    entry = {
        "name": name,
        "environment_manifest": f"{name.lower()}/env.manifest.json",
        "release_sha": sha,
        "qualification_state": state,
        "interface_compatibility": iface,
        "clock_reset_compatibility": clk,
    }
    for key in drop:
        entry.pop(key, None)
    return entry


def _write_registry(root: Path, entries):
    path = root / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"subsystems": entries}), encoding="utf-8")
    return path


def _write_candidate_sources(root: Path, candidates):
    path = sd.candidate_sources_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")
    return path


class FakeKnowledgeCenter:
    """Stands in for KnowledgeCenterClient with the SAME method surface the
    real one now exposes (configured()/subsystem_record()). No transport, no
    relay, no credentials -- a KC test that needed a live server would never
    run, and one that mocked _invoke() would be testing the transport rather
    than SYS-3's contradiction/staleness rules."""

    def __init__(self, records=None, *, configured=True, error=None):
        self.records = {str(k).lower(): v for k, v in (records or {}).items()}
        self._configured = configured
        self.error = error

    def configured(self):
        return self._configured

    def subsystem_record(self, subsystem_id, protocol=""):
        if self.error:
            return {"ok": False, "found": False, "record": None, "error": self.error}
        rec = self.records.get(str(subsystem_id).lower())
        return {"ok": True, "found": rec is not None, "record": rec, "candidates": []}


def _two_subsystem_project(tmp_path: Path):
    """The base synthetic project every scenario builds on: PCIE and USB, both
    registered, both with a complete environment tree on disk."""
    pcie_env = _write_env_tree(tmp_path / "generated" / "pcie_uvm_env")
    usb_env = _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_registry(tmp_path, [
        _registry_entry("PCIE", sha="pcie1234"),
        _registry_entry("USB", sha="usb56789"),
    ])
    _write_candidate_sources(tmp_path, [
        {"name": "PCIE", "protocol": "PCIE", "environment_path": "generated/pcie_uvm_env"},
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"},
    ])
    return pcie_env, usb_env


def _row(discovery, name):
    for r in discovery["candidates"]:
        if r["subsystem"].lower() == name.lower():
            return r
    raise AssertionError(f"{name} not in {[r['subsystem'] for r in discovery['candidates']]}")


# --- SYS-1: discover and present ---------------------------------------------

def test_sys1_presents_all_six_mandated_columns_for_every_candidate(tmp_path):
    _two_subsystem_project(tmp_path)
    discovery = sd.discover_subsystem_candidates(tmp_path)

    assert {r["subsystem"] for r in discovery["candidates"]} == {"PCIE", "USB"}
    for row in discovery["candidates"]:
        # The exact six SYS-1 columns, all populated from real evidence.
        assert row["subsystem"]
        assert row["environment_path"].endswith("_uvm_env")
        assert row["knowledge_center_status"] == "KC_NOT_CHECKED"
        assert row["readiness"] in sd.READINESS_CLASSES
        assert row["protocol"] in {"PCIE", "USB"}
        assert row["version_sha"] in {"pcie1234", "usb56789"}

    table = sd.render_discovery_table(discovery)
    for column in ("SUBSYSTEM", "ENVIRONMENT PATH", "KNOWLEDGE CENTER STATUS",
                   "READINESS", "PROTOCOL", "VERSION-SHA"):
        assert column in table
    assert "PCIE" in table and "USB" in table


def test_sys1_empty_project_reports_honest_absence_not_a_fabricated_candidate(tmp_path):
    discovery = sd.discover_subsystem_candidates(tmp_path)
    assert discovery["candidates"] == []
    assert discovery["candidate_source_status"] == "NOT_CONFIGURED"
    assert discovery["registered_count"] == 0
    assert "no candidate subsystem environments discovered" in sd.render_discovery_table(discovery)


def test_sys1_registry_alone_is_enough_when_no_candidate_sources_are_declared(tmp_path):
    """A project that never wrote a subsystem_candidate_sources.json must
    still get a usable table: the registry entry's environment_manifest names
    the environment directory, so the path does not have to be declared a
    second time."""
    _write_env_tree(tmp_path / "envs" / "usb_uvm_env")
    _write_registry(tmp_path, [{
        "name": "USB",
        "environment_manifest": "envs/usb_uvm_env/env.manifest.json",
        "release_sha": "u1", "qualification_state": "PRODUCTION_QUALIFIED",
        "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS",
        "protocol": "USB"}])
    discovery = sd.discover_subsystem_candidates(tmp_path)
    assert discovery["candidate_source_status"] == "NOT_CONFIGURED"
    row = _row(discovery, "USB")
    assert row["environment_path_basis"] == "REGISTRY_ENVIRONMENT_MANIFEST_PARENT"
    assert row["environment_path"] == str(tmp_path / "envs" / "usb_uvm_env")
    assert row["environment_path_readable"] is True
    assert row["existence_class"] == sd.EXISTS_READY
    assert row["protocol"] == "USB" and row["version_sha"] == "u1"


def test_sys1_requires_explicit_selection_and_never_assumes_all_candidates(tmp_path):
    _two_subsystem_project(tmp_path)
    result = sd.require_explicit_selection(tmp_path, [])

    assert result["selection_admissible"] is False
    assert result["refusal_reason"] == "NO_EXPLICIT_SELECTION"
    decision = result["environment_mode_decision"]
    assert decision["resolved"] is False
    assert decision["reason"] == "MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION"
    # The refusal now NAMES what could be chosen -- the discover-and-present
    # half SYS-1 requires, which the router alone could never supply.
    assert sorted(decision["candidate_subsystems"]) == ["PCIE", "USB"]
    assert sorted(decision["unselected_candidates"]) == ["PCIE", "USB"]


def test_sys1_a_deliberately_unselected_candidate_is_reported_not_dropped(tmp_path):
    _two_subsystem_project(tmp_path)
    # Selecting ONE of two registered subsystems is legitimate; what must not
    # happen is the other one vanishing without a trace.
    result = sd.require_explicit_selection(tmp_path, ["PCIE"])
    decision = result["environment_mode_decision"]
    assert decision["environment_mode"] == "SUBSYSTEM_MODE"
    assert decision["unselected_candidates"] == ["USB"]
    assert "deliberately NOT selected" in sd.format_report(result)


def test_sys1_selection_of_two_ready_subsystems_is_admissible_and_is_system_level(tmp_path):
    _two_subsystem_project(tmp_path)
    result = sd.require_explicit_selection(tmp_path, ["PCIE", "USB"])
    assert result["selection_admissible"] is True
    assert result["refusal_reason"] == ""
    assert result["environment_mode_decision"]["environment_mode"] == "SYSTEM_LEVEL_MODE"
    assert result["environment_mode_decision"]["needs_subsystem_mode_first"] is False


# --- SYS-2: the five-way existence classification ----------------------------

def test_sys2_registered_complete_environment_is_exists_ready(tmp_path):
    _two_subsystem_project(tmp_path)
    row = _row(sd.discover_subsystem_candidates(tmp_path), "PCIE")
    assert row["existence_class"] == sd.EXISTS_READY
    assert row["readiness"] == sd.READY
    assert row["next_action"] == "ELIGIBLE_FOR_EXPLICIT_USER_SELECTION"


def test_sys2_environment_on_disk_but_never_registered_is_exists_partial(tmp_path):
    _write_env_tree(tmp_path / "generated" / "canfd_uvm_env")
    _write_registry(tmp_path, [])
    _write_candidate_sources(tmp_path, [
        {"name": "CAN_FD", "protocol": "CAN_FD", "environment_path": "generated/canfd_uvm_env"},
    ])
    row = _row(sd.discover_subsystem_candidates(tmp_path), "CAN_FD")
    assert row["existence_class"] == sd.EXISTS_PARTIAL
    assert row["registered"] is False
    assert row["next_action"] == "REGISTER_VIA_SUBSYSTEM_MODE_SIGNOFF"
    assert any("never been registered" in r for r in row["existence_reasons"])


def test_sys2_registry_entry_missing_required_fields_is_exists_partial(tmp_path):
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_registry(tmp_path, [_registry_entry("USB", drop=("environment_manifest",))])
    _write_candidate_sources(tmp_path, [
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"}])
    row = _row(sd.discover_subsystem_candidates(tmp_path), "USB")
    assert row["existence_class"] == sd.EXISTS_PARTIAL
    assert any("environment_manifest" in r for r in row["existence_reasons"])


def test_sys2_recorded_clock_reset_failure_is_exists_blocked_not_partial(tmp_path):
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_registry(tmp_path, [_registry_entry("USB", clk="FAIL")])
    _write_candidate_sources(tmp_path, [
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"}])
    row = _row(sd.discover_subsystem_candidates(tmp_path), "USB")
    # Every artifact is on disk, so a file-presence-only view would have said
    # READY. The recorded verdict outranks the file evidence.
    assert row["existence_class"] == sd.EXISTS_BLOCKED
    assert row["readiness"] == sd.BLOCKED
    assert row["readiness_detail"]["blocking_factors"] == ["clock_reset_assumptions"]


def test_sys2_registered_but_unreadable_environment_is_exists_unknown(tmp_path):
    _write_registry(tmp_path, [_registry_entry("MIPI_CSI2")])
    _write_candidate_sources(tmp_path, [
        {"name": "MIPI_CSI2", "protocol": "MIPI_CSI2",
         "environment_path": "generated/never_created_csi2_env"}])
    row = _row(sd.discover_subsystem_candidates(tmp_path), "MIPI_CSI2")
    assert row["existence_class"] == sd.EXISTS_UNKNOWN
    assert row["readiness"] == sd.UNKNOWN
    assert row["confidence"] == "LOW"


def test_sys2_requested_subsystem_that_exists_nowhere_is_not_found_and_forbids_invention(tmp_path):
    _two_subsystem_project(tmp_path)
    discovery = sd.discover_subsystem_candidates(tmp_path, requested=["ETHERNET"])
    row = _row(discovery, "ETHERNET")
    assert row["existence_class"] == sd.NOT_FOUND
    assert "SCOPE_CORRECTION" in row["next_action"]
    assert "forbids inventing" in row["next_action"]


def test_sys2_all_five_existence_classes_are_reachable_from_real_evidence(tmp_path):
    """The audit's core SYS-2 finding was that the repo only ever produced
    binary PASS/FAIL and that EXISTS_UNKNOWN in particular had no analog.
    This asserts all five are genuinely reachable, in one project."""
    _write_env_tree(tmp_path / "generated" / "ready_env")
    _write_env_tree(tmp_path / "generated" / "unregistered_env")
    _write_env_tree(tmp_path / "generated" / "blocked_env")
    _write_registry(tmp_path, [
        _registry_entry("READY_ONE", sha="r1"),
        _registry_entry("BLOCKED_ONE", sha="b1", iface="FAIL"),
        _registry_entry("UNREADABLE_ONE", sha="u1"),
    ])
    _write_candidate_sources(tmp_path, [
        {"name": "READY_ONE", "protocol": "USB", "environment_path": "generated/ready_env"},
        {"name": "BLOCKED_ONE", "protocol": "PCIE", "environment_path": "generated/blocked_env"},
        {"name": "UNREADABLE_ONE", "protocol": "SDIO", "environment_path": "generated/gone"},
        {"name": "PARTIAL_ONE", "protocol": "CAN_FD",
         "environment_path": "generated/unregistered_env"},
    ])
    discovery = sd.discover_subsystem_candidates(tmp_path, requested=["ABSENT_ONE"])
    got = {r["subsystem"]: r["existence_class"] for r in discovery["candidates"]}
    assert got == {
        "READY_ONE": sd.EXISTS_READY,
        "BLOCKED_ONE": sd.EXISTS_BLOCKED,
        "UNREADABLE_ONE": sd.EXISTS_UNKNOWN,
        "PARTIAL_ONE": sd.EXISTS_PARTIAL,
        "ABSENT_ONE": sd.NOT_FOUND,
    }
    assert set(got.values()) == set(sd.EXISTENCE_CLASSES)


# --- the ambiguous candidate-set case ----------------------------------------

def test_two_candidates_sharing_one_environment_tree_is_reported_as_a_conflict(tmp_path):
    """The genuinely ambiguous case at discovery time: two candidate NAMES
    resolving to one environment tree. Selecting both would compose the same
    environment twice. It must be reported, and never auto-merged -- which of
    the two names is right is a user decision."""
    shared = _write_env_tree(tmp_path / "generated" / "pcie_uvm_env")
    _write_registry(tmp_path, [
        _registry_entry("PCIE", sha="p1"), _registry_entry("PCIE_GEN5", sha="p2")])
    _write_candidate_sources(tmp_path, [
        {"name": "PCIE", "protocol": "PCIE", "environment_path": "generated/pcie_uvm_env"},
        {"name": "PCIE_GEN5", "protocol": "PCIE", "environment_path": "generated/pcie_uvm_env"},
    ])
    discovery = sd.discover_subsystem_candidates(tmp_path)
    assert len(discovery["conflicts"]) == 1
    conflict = discovery["conflicts"][0]
    assert conflict["conflict"] == "DUPLICATE_ENVIRONMENT_PATH"
    assert conflict["subsystems"] == ["PCIE", "PCIE_GEN5"]
    assert conflict["environment_path"] == str(shared)
    assert conflict["resolution"] == "USER_MUST_DISAMBIGUATE_BEFORE_SELECTION"
    # Both rows are individually EXISTS_READY, so a per-row check alone would
    # have waved this through -- the conflict must block the SELECTION.
    assert all(r["existence_class"] == sd.EXISTS_READY for r in discovery["candidates"])
    result = sd.require_explicit_selection(tmp_path, ["PCIE", "PCIE_GEN5"])
    assert result["selection_admissible"] is False
    assert result["refusal_reason"] == "CANDIDATE_SET_CONFLICT"


def test_selecting_a_blocked_subsystem_is_refused_with_its_own_next_action(tmp_path):
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_env_tree(tmp_path / "generated" / "pcie_uvm_env")
    _write_registry(tmp_path, [
        _registry_entry("USB", sha="u1", clk="FAIL"), _registry_entry("PCIE", sha="p1")])
    _write_candidate_sources(tmp_path, [
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"},
        {"name": "PCIE", "protocol": "PCIE", "environment_path": "generated/pcie_uvm_env"}])
    result = sd.require_explicit_selection(tmp_path, ["USB", "PCIE"])
    assert result["selection_admissible"] is False
    assert result["refusal_reason"] == "SELECTED_SUBSYSTEM_NOT_EXISTS_READY"
    assert [n["subsystem"] for n in result["not_ready"]] == ["USB"]
    assert result["not_ready"][0]["existence_class"] == sd.EXISTS_BLOCKED


# --- SYS-3: Knowledge Center check -------------------------------------------

def test_sys3_record_fields_are_exactly_the_twenty_one_the_requirement_names():
    assert SUBSYSTEM_RECORD_FIELDS == (
        "SUBSYSTEM_ID", "PROTOCOL", "ROLE", "VERSION", "GIT_SHA",
        "ENVIRONMENT_PATH", "RTL_PATH", "VIP", "VIP_VERSION", "BUILD_STATUS",
        "LAST_KNOWN_PASS", "REGRESSION_STATUS", "COVERAGE_STATUS",
        "KNOWN_LIMITATIONS", "KNOWN_FAILURES", "COMMAND_TXT", "OWNER_AGENT",
        "OWNER_SKILL", "READINESS", "EVIDENCE", "CONFIDENCE")
    assert len(SUBSYSTEM_RECORD_FIELDS) == 21


def test_sys3_normalize_is_case_insensitive_and_keeps_absent_fields_as_null():
    rec = normalize_subsystem_record({"subsystem_id": "USB", "GIT_SHA": "abc",
                                      "written_at": 1.0, "memory_id": "KC-1"})
    assert rec["SUBSYSTEM_ID"] == "USB"
    assert rec["GIT_SHA"] == "abc"
    assert rec["ROLE"] is None and "ROLE" in rec
    assert rec["_kc"]["written_at"] == 1.0 and rec["_kc"]["memory_id"] == "KC-1"


def test_sys3_stale_kc_git_sha_is_overridden_by_repository_evidence_and_reported(tmp_path):
    _two_subsystem_project(tmp_path)
    kc = FakeKnowledgeCenter({"USB": normalize_subsystem_record({
        "SUBSYSTEM_ID": "USB", "PROTOCOL": "USB", "GIT_SHA": "STALE_SHA_0000",
        "READINESS": "BLOCKED", "written_at": 0.0})})
    discovery = sd.discover_subsystem_candidates(tmp_path, knowledge_center_client=kc)
    row = _row(discovery, "USB")

    assert row["knowledge_center_status"] == "KC_RECORD_FOUND"
    fields = {c["field"]: c for c in row["knowledge_center"]["contradictions"]}
    assert fields["GIT_SHA"]["repository_value"] == "usb56789"
    assert fields["GIT_SHA"]["overridden_value"] == "STALE_SHA_0000"
    assert fields["GIT_SHA"]["resolution"] == "REPOSITORY_EVIDENCE_WINS"
    # The KC calling it BLOCKED does not make it blocked; the repository's own
    # derived readiness wins and the disagreement is reported instead.
    assert row["readiness"] == sd.READY
    assert fields["READINESS"]["knowledge_center_value"] == "BLOCKED"
    assert row["existence_class"] == sd.EXISTS_READY
    assert row["knowledge_center"]["staleness"]["stale"] is True
    report = sd.format_report({"discovery": discovery})
    assert "CONTRADICTION GIT_SHA" in report and "STALE" in report


def test_sys3_four_non_found_knowledge_center_statuses_stay_distinct(tmp_path):
    _two_subsystem_project(tmp_path)

    def status_for(client):
        return _row(sd.discover_subsystem_candidates(
            tmp_path, knowledge_center_client=client), "USB")["knowledge_center_status"]

    assert status_for(None) == "KC_NOT_CHECKED"
    assert status_for(FakeKnowledgeCenter(configured=False)) == "KC_NOT_CONFIGURED"
    assert status_for(FakeKnowledgeCenter(error="RELAY_NOT_READY")) == "KC_UNAVAILABLE"
    assert status_for(FakeKnowledgeCenter({})) == "KC_RECORD_ABSENT"


def test_sys3_agreeing_kc_record_produces_no_contradiction(tmp_path):
    import time
    _two_subsystem_project(tmp_path)
    kc = FakeKnowledgeCenter({"USB": normalize_subsystem_record({
        "SUBSYSTEM_ID": "USB", "PROTOCOL": "USB", "GIT_SHA": "usb56789",
        "READINESS": "READY", "written_at": time.time()})})
    row = _row(sd.discover_subsystem_candidates(tmp_path, knowledge_center_client=kc), "USB")
    assert row["knowledge_center"]["contradictions"] == []
    assert row["knowledge_center"]["staleness"]["stale"] is False


def test_sys3_kc_client_subsystem_record_matches_exactly_never_by_substring():
    """A free-text KC search for "USB" happily returns USB3_DEVICE. The typed
    accessor must not treat that as this subsystem's record."""
    from dv_harness.knowledge_center import KnowledgeCenterClient

    client = KnowledgeCenterClient({"knowledge_center": {"enabled": True,
                                                          "remote_root": "/fake"}})
    client.search = lambda **kw: {"ok": True, "records": [
        {"SUBSYSTEM_ID": "USB3_DEVICE", "GIT_SHA": "x"},
        {"SUBSYSTEM_ID": "usb", "GIT_SHA": "y"}]}
    res = client.subsystem_record("USB")
    assert res["found"] is True
    assert res["record"]["GIT_SHA"] == "y"
    assert client.subsystem_record("CAN_FD")["found"] is False


# --- SYS-4: the 13-factor readiness gate -------------------------------------

def test_sys4_factor_list_is_exactly_the_thirteen_the_requirement_names():
    assert sd.READINESS_FACTORS == (
        "rtl", "uvm_env", "vip", "build", "tests", "sequences",
        "scoreboard_reference_model", "command_txt", "clock_reset_assumptions",
        "top_hierarchy", "config", "pass_evidence", "regression_evidence")
    assert len(sd.READINESS_FACTORS) == 13
    # Every factor really has an artifact it is derived from -- none is a
    # placeholder that silently reports UNKNOWN forever.
    assert set(sd.FACTOR_ARTIFACT) == set(sd.READINESS_FACTORS)
    assert set(sd.FACTOR_ARTIFACT.values()) <= set(sd.ARTIFACT_GLOBS)


def test_sys4_incomplete_environment_is_partial_and_names_the_missing_factors(tmp_path):
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env", complete=False)
    _write_registry(tmp_path, [_registry_entry("USB")])
    _write_candidate_sources(tmp_path, [
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"}])
    row = _row(sd.discover_subsystem_candidates(tmp_path), "USB")
    assert row["readiness"] == sd.PARTIAL
    assert set(row["readiness_detail"]["missing_factors"]) == {
        "scoreboard_reference_model", "command_txt", "regression_evidence"}
    assert row["existence_class"] == sd.EXISTS_PARTIAL


def test_sys4_all_four_readiness_values_are_reachable():
    def factors(**overrides):
        base = {f: {"status": sd.PRESENT, "evidence": "fixture"} for f in sd.READINESS_FACTORS}
        base.update({k: {"status": v, "evidence": "fixture"} for k, v in overrides.items()})
        return base

    assert sd.derive_subsystem_readiness(factors())["readiness"] == sd.READY
    assert sd.derive_subsystem_readiness(factors(tests=sd.ABSENT))["readiness"] == sd.PARTIAL
    assert sd.derive_subsystem_readiness(factors(rtl=sd.BLOCKED))["readiness"] == sd.BLOCKED
    all_unknown = {f: {"status": sd.UNKNOWN, "evidence": "not probed"}
                   for f in sd.READINESS_FACTORS}
    assert sd.derive_subsystem_readiness(all_unknown)["readiness"] == sd.UNKNOWN


def test_sys4_a_single_unknown_factor_never_rounds_up_to_ready():
    factors = {f: {"status": sd.PRESENT, "evidence": "fixture"} for f in sd.READINESS_FACTORS}
    factors["command_txt"] = {"status": sd.UNKNOWN, "evidence": "not probed"}
    derived = sd.derive_subsystem_readiness(factors)
    assert derived["readiness"] == sd.PARTIAL
    assert derived["unknown_factors"] == ["command_txt"]


def test_sys4_one_blocker_outranks_twelve_healthy_factors():
    factors = {f: {"status": sd.PRESENT, "evidence": "fixture"} for f in sd.READINESS_FACTORS}
    factors["clock_reset_assumptions"] = {"status": sd.BLOCKED,
                                          "evidence": "clock_reset_compatibility='FAIL'"}
    derived = sd.derive_subsystem_readiness(factors)
    assert derived["readiness"] == sd.BLOCKED
    assert len(derived["present_factors"]) == 12
    assert "clock_reset_compatibility" in derived["evidence"]


def test_sys4_qualification_state_outside_the_canonical_set_blocks_pass_evidence(tmp_path):
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_registry(tmp_path, [_registry_entry("USB", state="COMPILE_QUALIFIED")])
    _write_candidate_sources(tmp_path, [
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"}])
    row = _row(sd.discover_subsystem_candidates(tmp_path), "USB")
    assert row["readiness_detail"]["blocking_factors"] == ["pass_evidence"]
    assert row["existence_class"] == sd.EXISTS_BLOCKED


def test_declared_artifact_paths_beat_the_name_conventions(tmp_path):
    """A project that declares where its scoreboard lives must not be at the
    mercy of this module's guess about what a scoreboard file is called."""
    env = tmp_path / "generated" / "odd_env"
    _write_env_tree(env, complete=False)
    (env / "checkers").mkdir(parents=True, exist_ok=True)
    (env / "checkers" / "compare_engine.svh").write_text("// not named _scoreboard", "utf-8")
    (env / "patterns").mkdir(parents=True, exist_ok=True)
    (env / "patterns" / "bringup.pat").write_text("# not named command.txt", "utf-8")
    (env / "runs").mkdir(parents=True, exist_ok=True)
    (env / "runs" / "nightly.csv").write_text("test,PASS\n", "utf-8")

    plain = sd.probe_environment_artifacts(env)
    assert plain["scoreboards"]["status"] == sd.ABSENT
    assert plain["command_txt"]["status"] == sd.ABSENT

    declared = sd.probe_environment_artifacts(env, {
        "scoreboards": ["checkers/compare_engine.svh"],
        "command_txt": ["patterns/bringup.pat"],
        "regression_lists": ["runs/nightly.csv"],
        "missing_kind": ["nope/not_here.sv"],
    })
    assert declared["scoreboards"]["status"] == sd.PRESENT
    assert declared["scoreboards"]["basis"] == "DECLARED_PATHS"
    assert declared["command_txt"]["status"] == sd.PRESENT
    assert sd.derive_subsystem_readiness(
        sd.readiness_factors_from_evidence(declared))["readiness"] == sd.READY


def test_unreadable_environment_reports_unknown_not_absent(tmp_path):
    probe = sd.probe_environment_artifacts(tmp_path / "does_not_exist")
    assert all(v["status"] == sd.UNKNOWN for k, v in probe.items() if k != "_walk")
    assert "DOES_NOT_EXIST" in probe["_walk"]["basis"]


# --- contracts held to the real gate scripts ---------------------------------

def test_registry_required_fields_match_both_real_gate_scripts():
    """One registry-entry contract, three statements of it (this module plus
    the two standalone stdlib-only gate scripts, which cannot import it
    because they run as gate subprocesses). Drift guard, same pattern as
    source_authority.assert_doc_matches_code()."""
    import ast

    def required_of(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", None) == "REQUIRED" for t in node.targets):
                return tuple(ast.literal_eval(node.value))
        raise AssertionError(f"no REQUIRED list in {path}")

    assert required_of(VALIDATOR) == sd.REGISTRY_REQUIRED_FIELDS
    assert required_of(REGISTRATION_GATE) == sd.REGISTRY_REQUIRED_FIELDS


def test_qualification_vocabulary_is_reused_not_redefined():
    from dv_harness.qualification import SYSTEM_LEVEL_STATES
    assert sd.SYSTEM_LEVEL_STATES is SYSTEM_LEVEL_STATES


# --- system_level_validator --classify (the real gate script, as a subprocess) -

def _run_validator(tmp_path, claim, registered=None, classify=False):
    registry = tmp_path / "claim.json"
    registry.write_text(json.dumps(claim), encoding="utf-8")
    cmd = [sys.executable, str(VALIDATOR), "--registry", str(registry)]
    if registered is not None:
        reg = tmp_path / "registered.json"
        reg.write_text(json.dumps({"subsystems": registered}), encoding="utf-8")
        cmd += ["--registered", str(reg)]
    if classify:
        cmd.append("--classify")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1])


def test_validator_classify_is_purely_additive_and_changes_no_verdict(tmp_path):
    claim = {"subsystems": [_registry_entry("USB", sha="u1"), _registry_entry("PCIE", sha="p1")]}
    registered = [_registry_entry("USB", sha="u1"), _registry_entry("PCIE", sha="p1")]

    plain_code, plain = _run_validator(tmp_path, claim, registered)
    cls_code, classified = _run_validator(tmp_path, claim, registered, classify=True)

    assert plain_code == cls_code == 0
    assert plain["status"] == classified["status"] == "PASS"
    assert "classification" not in plain
    assert {c["name"]: c["existence_class"] for c in classified["classification"]["subsystems"]} == {
        "USB": sd.EXISTS_READY, "PCIE": sd.EXISTS_READY}
    # Stripping the added key leaves the byte-identical original payload.
    stripped = dict(classified)
    stripped.pop("classification")
    assert stripped == plain


def test_validator_classify_maps_each_real_fail_reason_onto_its_sys2_class(tmp_path):
    good = _registry_entry("USB", sha="u1")

    # SUBSYSTEM_NOT_REGISTERED -> NOT_FOUND
    code, out = _run_validator(tmp_path, {"subsystems": [good]}, [], classify=True)
    assert code == 5 and out["reason"] == "SUBSYSTEM_NOT_REGISTERED"
    assert out["classification"]["subsystems"][0]["existence_class"] == sd.NOT_FOUND

    # SUBSYSTEM_RELEASE_SHA_MISMATCH -> EXISTS_UNKNOWN (it exists; which
    # version you have cannot be told from this evidence).
    code, out = _run_validator(tmp_path, {"subsystems": [good]},
                               [_registry_entry("USB", sha="DIFFERENT")], classify=True)
    assert code == 6 and out["reason"] == "SUBSYSTEM_RELEASE_SHA_MISMATCH"
    assert out["classification"]["subsystems"][0]["existence_class"] == sd.EXISTS_UNKNOWN

    # MISSING_REQUIRED_FIELDS -> EXISTS_PARTIAL
    code, out = _run_validator(
        tmp_path, {"subsystems": [_registry_entry("USB", drop=("release_sha",))]},
        [good], classify=True)
    assert code == 3
    assert out["classification"]["subsystems"][0]["existence_class"] == sd.EXISTS_PARTIAL

    # *_NOT_PASS -> EXISTS_BLOCKED
    code, out = _run_validator(tmp_path,
                               {"subsystems": [_registry_entry("USB", sha="u1", iface="FAIL")]},
                               [good], classify=True)
    assert code == 0  # this gate never checked compatibility itself
    assert out["classification"]["subsystems"][0]["existence_class"] == sd.EXISTS_BLOCKED

    # No --registered cross-check at all -> EXISTS_UNKNOWN, never a guessed PASS.
    code, out = _run_validator(tmp_path, {"subsystems": [good]}, None, classify=True)
    assert code == 0
    assert out["classification"]["subsystems"][0]["existence_class"] == sd.EXISTS_UNKNOWN


# --- the CLI front door ------------------------------------------------------

def test_cli_subsystem_discovery_prints_the_table_and_exits_two_on_a_bad_selection(tmp_path):
    _write_env_tree(tmp_path / "generated" / "usb_uvm_env")
    _write_registry(tmp_path, [_registry_entry("USB", sha="u1", clk="FAIL")])
    _write_candidate_sources(tmp_path, [
        {"name": "USB", "protocol": "USB", "environment_path": "generated/usb_uvm_env"}])

    listing = subprocess.run(
        [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path),
         "subsystem-discovery"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert listing.returncode == 0, listing.stderr
    assert "KNOWLEDGE CENTER STATUS" in listing.stdout
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in listing.stdout

    selected = subprocess.run(
        [sys.executable, "-m", "dv_harness", "--project-root", str(tmp_path),
         "subsystem-discovery", "--select", "USB"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert selected.returncode == 2, selected.stdout
    assert "EXISTS_BLOCKED" in selected.stdout


# --- the router extension stays backward compatible --------------------------

def test_router_candidate_fields_are_optional_and_change_nothing_when_omitted():
    single = resolve_environment_mode({"requested_subsystems": ["usb"]})
    assert single["environment_mode"] == "SUBSYSTEM_MODE"
    assert single["candidate_subsystems"] == []
    assert single["unselected_candidates"] == []
    unresolved = resolve_environment_mode({})
    assert unresolved["reason"] == "MODE_MUST_BE_EXPLICIT_BEFORE_GENERATION"
    assert unresolved["candidate_subsystems"] == []


def test_router_reports_unselected_candidates_without_ever_auto_selecting_them():
    decision = resolve_environment_mode({
        "requested_subsystems": ["usb", "pcie"],
        "existing_registered_subsystems": ["usb", "pcie", "ethernet"],
        "candidate_subsystems": ["usb", "pcie", "ethernet", "can_fd"]})
    assert decision["environment_mode"] == "SYSTEM_LEVEL_MODE"
    assert decision["requested_subsystems"] == ["usb", "pcie"]
    assert decision["unselected_candidates"] == ["ethernet", "can_fd"]
    # Reported, never folded into the composition.
    assert "ethernet" not in decision["reused_subsystems"]


# --- the phase boundary this whole step is bounded by ------------------------

def test_module_generates_no_system_level_artifacts(tmp_path):
    """SYS-39/SYS-40: this step is discovery/analysis/planning/reporting only.
    A full discovery+selection run must leave the project tree untouched --
    no System-Level UVM source, no System command.txt, no virtual sequencer,
    and not even a mutation of the real registry it reads."""
    _two_subsystem_project(tmp_path)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    result = sd.require_explicit_selection(tmp_path, ["PCIE", "USB"])
    sd.format_report(result)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in sd.format_report(result)


def test_soc_composer_cross_subsystem_stubs_are_still_unimplemented():
    """Guard on the hard constraint this whole effort is bounded by: filling
    cross_subsystem_scenarios()/end_to_end_scoreboard()/system_coverage() with
    real protocol-behavior content is SYS-40 territory. Nothing in SYS-1..4
    may have quietly done it."""
    from dv_harness.uvm_generator import soc_environment_composer as composer
    for fn in (composer.cross_subsystem_scenarios, composer.end_to_end_scoreboard,
               composer.system_coverage):
        with pytest.raises(NotImplementedError):
            fn({})
