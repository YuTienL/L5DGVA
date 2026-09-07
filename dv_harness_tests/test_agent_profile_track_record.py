"""Agent-Profile Track-Record Scoring (`dv_harness/memory.py`'s new optional
`producing_agent_profile` field + `dv_harness/agent_profile_track_record.py`'s
read-only report joining it against real `MemoryGC.confirm()`/`retract()`
outcomes).

WHAT THESE TESTS ARE FOR:

  1. **Backward compatibility.** `MemoryStore.add()` must keep its exact prior
     behavior for every existing caller that never mentions
     `producing_agent_profile`: the field defaults to `None`, exactly like
     `applicability_context` before it, and is indistinguishable from a
     record file written before this change existed.
  2. **Reuse, not re-derivation.** The report's VERIFIED/REJECTED/INDETERMINATE
     outcome for one record must come from `confidence_calibration.
     classify_record_outcome()`, called -- proven by driving the exact
     confirmed-then-retracted case that module's own test suite uses to prove
     its REJECTED-checked-first rule, and by asserting the two modules agree.
  3. **Never fabricate attribution.** A record whose writer never supplied
     `producing_agent_profile` must be counted as UNATTRIBUTED, never folded
     into some named profile's bucket, and a project with no memory store at
     all must report NOT_AVAILABLE without ever constructing one.
  4. **Real end-to-end wiring.** `engine.py`'s real `run_stage()` really
     threads its own resolved `route_info["agent"]` onto the
     `kind="verified_fix"` record a real gate-verified RE_AUDIT PASS produces
     -- proven through a real `DVHarness.run_stage()` call over the real
     shipped graph, never asserted from reading the source alone.
  5. **Reporting only.** This module must never write to the memory store,
     and it must reference no approval/governance mechanism -- checked
     against its own real AST, the same technique
     `test_confidence_calibration.py` already uses for its own module.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import agent_profile_track_record as aptr
from dv_harness import confidence_calibration as cc
from dv_harness import models
from dv_harness.memory import MemoryGC, MemoryStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_record(store, *, profile=None, title="finding", protocol="USB3",
               confidence="HIGH", level="engineering"):
    record = {
        "title": title, "protocol": protocol,
        "root_cause": f"{title}-rc", "confidence": confidence,
    }
    if profile is not None:
        record["producing_agent_profile"] = profile
    return store.add(level, record)


# --------------------------------------------------------------------------
# 1. backward compatibility
# --------------------------------------------------------------------------
def test_add_with_no_producing_agent_profile_defaults_to_none(root):
    store = MemoryStore(root)
    rec = add_record(store, title="no-profile-supplied")
    assert rec["producing_agent_profile"] is None
    # Re-read from disk, the same round trip a report would do -- not just
    # the in-memory dict `add()` happened to return.
    reread = store.get(rec["memory_id"])
    assert reread["producing_agent_profile"] is None


def test_a_caller_supplied_profile_is_persisted_verbatim(root):
    store = MemoryStore(root)
    rec = add_record(store, profile="debug-agent", title="with-profile")
    assert store.get(rec["memory_id"])["producing_agent_profile"] == "debug-agent"


# --------------------------------------------------------------------------
# 2/3. the report itself: NOT_AVAILABLE / NO_ATTRIBUTED_RECORDS / REPORTED
# --------------------------------------------------------------------------
def test_bare_project_reports_not_available_and_creates_nothing(root):
    report = aptr.collect_agent_profile_track_record(root)
    assert report["status"] == aptr.STATUS_NOT_AVAILABLE
    assert report["profiles"] == {}
    # Reading must never mint the store it is asking about.
    assert not (root / ".dv-harness").exists()


def test_records_present_but_none_attributed_reports_the_honest_middle_status(root):
    store = MemoryStore(root)
    add_record(store, title="a")
    add_record(store, title="b")
    report = aptr.collect_agent_profile_track_record(root)
    assert report["status"] == aptr.STATUS_NO_ATTRIBUTED_RECORDS
    assert report["records_scanned"] == 2
    assert report["profiles"] == {}


def test_reported_status_separates_named_profiles_from_unattributed(root):
    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="d1")
    add_record(store, profile="debug-agent", title="d2")
    add_record(store, title="no-profile")  # UNATTRIBUTED
    report = aptr.collect_agent_profile_track_record(root)
    assert report["status"] == aptr.STATUS_REPORTED
    assert set(report["profiles"]) == {"debug-agent", aptr.UNATTRIBUTED_LABEL}
    assert report["profiles"]["debug-agent"]["records"] == 2
    assert report["profiles"]["debug-agent"]["producing_agent_profile"] == "debug-agent"
    unattributed = report["profiles"][aptr.UNATTRIBUTED_LABEL]
    assert unattributed["records"] == 1
    assert unattributed["producing_agent_profile"] is None


# --------------------------------------------------------------------------
# 2. reuse of confidence_calibration.classify_record_outcome, not a second
#    definition of "what really happened to this record"
# --------------------------------------------------------------------------
def test_confirmed_then_retracted_is_rejected_matching_confidence_calibration(root):
    store = MemoryStore(root)
    gc = MemoryGC(store)
    rec = add_record(store, profile="review-agent", title="flip-flop")
    assert gc.confirm(rec["memory_id"], evidence={"note": "independent re-derivation"})
    assert gc.retract(rec["memory_id"], "overturned by current evidence",
                      evidence={"sim_log": "run/sim.log:1201"})

    stored = store.get(rec["memory_id"])
    direct = cc.classify_record_outcome(stored)
    assert direct["outcome"] == cc.OUTCOME_REJECTED

    report = aptr.collect_agent_profile_track_record(root)
    bucket = report["profiles"]["review-agent"]
    assert bucket["rejected"] == 1
    assert bucket["verified"] == 0  # the retraction is the last word


def test_a_reconfirmed_record_counts_as_verified_for_its_profile(root):
    store = MemoryStore(root)
    gc = MemoryGC(store)
    rec = add_record(store, profile="debug-agent", title="held-up")
    assert gc.confirm(rec["memory_id"], evidence={"note": "independent re-derivation"})
    report = aptr.collect_agent_profile_track_record(root)
    bucket = report["profiles"]["debug-agent"]
    assert bucket["verified"] == 1
    assert bucket["determinate"] == 1
    assert bucket["observed_reliability"] == 1.0


def test_an_active_never_rechecked_record_is_indeterminate(root):
    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="never-touched")
    report = aptr.collect_agent_profile_track_record(root)
    bucket = report["profiles"]["debug-agent"]
    assert bucket["indeterminate"] == 1
    assert bucket["determinate"] == 0
    assert bucket["observed_reliability"] is None


# --------------------------------------------------------------------------
# profile resolution -- reuses env_manifest.build_generation_agent(), never
# a second "does this profile exist" check
# --------------------------------------------------------------------------
def test_a_real_profile_resolves_as_a_real_agent_profile(root):
    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="real-profile")
    report = aptr.collect_agent_profile_track_record(root)
    resolution = report["profiles"]["debug-agent"]["profile_resolution"]
    assert resolution["resolution"] == "AGENT_PROFILE"


def test_a_fabricated_profile_name_resolves_not_found_never_silently_accepted(root):
    store = MemoryStore(root)
    add_record(store, profile="no-such-agent-profile-xyz", title="fake")
    report = aptr.collect_agent_profile_track_record(root)
    resolution = report["profiles"]["no-such-agent-profile-xyz"]["profile_resolution"]
    assert resolution["resolution"] == "NOT_FOUND"


def test_all_unattributed_records_report_the_honest_middle_status_not_reported(root):
    # Mirrors test_records_present_but_none_attributed_reports_the_honest_middle_status:
    # with NOTHING attributed, there is no named profile to report, so this
    # is NO_ATTRIBUTED_RECORDS, never a REPORTED status with an empty/omitted
    # profiles dict standing in for "nothing to say".
    store = MemoryStore(root)
    add_record(store, title="no-profile-at-all")
    report = aptr.collect_agent_profile_track_record(root)
    assert report["status"] == aptr.STATUS_NO_ATTRIBUTED_RECORDS
    assert report["profiles"] == {}


def test_the_unattributed_bucket_carries_its_own_honest_resolution_label(root):
    # Only surfaced when it coexists with at least one real attributed
    # profile -- see the previous test for the all-unattributed case.
    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="attributed")
    add_record(store, title="no-profile-at-all")
    report = aptr.collect_agent_profile_track_record(root)
    resolution = report["profiles"][aptr.UNATTRIBUTED_LABEL]["profile_resolution"]
    assert resolution["resolution"] == "UNATTRIBUTED"


# --------------------------------------------------------------------------
# vocabulary-collision guard has real detection power
# --------------------------------------------------------------------------
def test_vocabulary_guard_passes_against_the_real_module(root):
    # Already run at import time; re-running it here must still be clean.
    aptr.assert_no_verification_verdict_vocabulary()


def test_vocabulary_guard_detects_a_real_collision(monkeypatch):
    # UNATTRIBUTED_LABEL is read directly by name inside the guard (unlike
    # STATUS_REPORTED, which is folded into the frozen REPORT_STATUSES tuple
    # at import time and so cannot be monkeypatched after the fact) --
    # monkeypatching it to a real Status value is what proves this guard
    # actually inspects live module state rather than merely never tripping.
    monkeypatch.setattr(aptr, "UNATTRIBUTED_LABEL", models.Status.PASS.value)
    with pytest.raises(aptr.AgentProfileTrackRecordError):
        aptr.assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# 4. real end-to-end engine wiring: a real gate-verified RE_AUDIT PASS really
#    threads its own resolved agent name onto the record it writes
# --------------------------------------------------------------------------
def test_a_real_re_audit_pass_stamps_its_own_resolved_agent_on_the_record():
    from dv_harness_tests.test_engineering_confirmation_accumulation import (
        _fresh_harness_with_graph, _run_re_audit_pass, _engineering_records,
        _USB_GOAL,
    )
    tmp, h = _fresh_harness_with_graph()
    try:
        _run_re_audit_pass(h, _USB_GOAL)
        records = _engineering_records(tmp)
        verified_fixes = [r for r in records if r.get("kind") == "verified_fix"]
        assert len(verified_fixes) == 1
        record = verified_fixes[0]
        # RE_AUDIT's own declared agent in the real shipped graph -- see
        # .dv-harness/graph/main_graph.json's RE_AUDIT node.
        assert record["producing_agent_profile"] == "review-agent"

        report = aptr.collect_agent_profile_track_record(tmp)
        assert report["status"] == aptr.STATUS_REPORTED
        assert "review-agent" in report["profiles"]
        resolution = report["profiles"]["review-agent"]["profile_resolution"]
        # review-agent.md is a real profile in THIS harness's own .claude tree
        # (build_generation_agent()'s default profile_root), regardless of the
        # throwaway project root the record itself lives in.
        assert resolution["resolution"] == "AGENT_PROFILE"
    finally:
        shutil.rmtree(tmp)


# --------------------------------------------------------------------------
# CLI / execute_verb
# --------------------------------------------------------------------------
def test_execute_verb_exit_codes_and_unknown_verb(root):
    code, payload = aptr.execute_verb(root, "report")
    assert code == 2 and payload["status"] == aptr.STATUS_NOT_AVAILABLE

    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="x")
    code, payload = aptr.execute_verb(root, "report")
    assert code == 0 and payload["status"] == aptr.STATUS_REPORTED

    code, text = aptr.execute_verb(root, "show")
    assert code == 0 and isinstance(text, str) and "debug-agent" in text

    code, payload = aptr.execute_verb(root, "calibrate-everything")
    assert code == 1 and payload["error"] == "UNKNOWN_VERB"


def test_rendered_report_prints_named_and_unattributed_profiles(root):
    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="x")
    add_record(store, title="y")
    text = aptr.render_report_text(aptr.collect_agent_profile_track_record(root))
    assert "debug-agent" in text
    assert "(unattributed)" in text


def test_module_front_door_runs_as_a_real_subprocess(root):
    store = MemoryStore(root)
    add_record(store, profile="debug-agent", title="cli-test")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.agent_profile_track_record", "show",
         "--project-root", str(root)],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "REPORTED" in proc.stdout
    assert "debug-agent" in proc.stdout


# --------------------------------------------------------------------------
# 5. reporting only -- no write path, no governance/approval symbol
# --------------------------------------------------------------------------
def test_the_module_touches_no_approval_or_governance_symbol():
    src = (ROOT / "dv_harness" / "agent_profile_track_record.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
                      "approve(", "os.system"):
        assert forbidden not in code, forbidden


def test_the_module_never_writes_to_the_memory_store():
    """Checked against the module's real AST, not its text: a mutating METHOD
    CALL is what would matter, and prose naming `MemoryGC.confirm()` in a
    docstring is not one."""
    tree = ast.parse((ROOT / "dv_harness" / "agent_profile_track_record.py")
                     .read_text(encoding="utf-8"))
    mutating = {"add", "confirm", "retract", "supersede", "deprecate", "flag_stale",
                "mark_used", "reindex", "write_text", "write_bytes", "mkdir", "unlink",
                "event", "approve"}
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not (called & mutating), sorted(called & mutating)


def test_reading_the_report_never_mutates_an_existing_store(root):
    store = MemoryStore(root)
    rec = add_record(store, profile="debug-agent", title="untouched")
    before = json.dumps(store.get(rec["memory_id"]), sort_keys=True)
    aptr.collect_agent_profile_track_record(root)
    aptr.collect_agent_profile_track_record(root)
    after = json.dumps(store.get(rec["memory_id"]), sort_keys=True)
    assert before == after
