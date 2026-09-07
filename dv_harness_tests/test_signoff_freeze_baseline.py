"""Tests for spec section 238 (SIGNOFF FREEZE / BASELINE) in
dv_harness/signoff_export.py.

Every fixture is a REAL throwaway project: a real git repository with real
commits, a real `.dv-harness/connectivity_check.json` + RTL tree that the
REAL `connectivity_check.compute_rtl_fingerprint()` fingerprints, a real
waiver ledger written through the REAL `waiver_store.record_waiver()`, real
`lsf_client`-shaped job records, and a real signoff bundle produced by the
REAL `collect_signoff_bundle()`. Nothing is mocked, because a freeze whose
inputs were stubs would prove the record shape and nothing about whether a
post-freeze change is really detectable.

The central proof is `test_freeze_then_change_the_fixture_then_the_check_fires`:
freeze a bundle against the fixture, assert VALID, then change the fixture's
RTL and commit it, and assert the SAME frozen record now reads INVALIDATED
naming both the diverged baseline field and the changed file at its real
risk -- with the frozen record itself untouched on disk, because the verdict
is derived, never stored.

Nothing here runs a build, a regression or an LSF submission, and no
human-approval gate is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dv_harness import signoff_export as sx
from dv_harness import waiver_store

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


# --- real fixture ----------------------------------------------------------

def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _waiver(waiver_id="W-238-1"):
    return {
        "waiver_id": waiver_id,
        "item": "REQ-USB3-LFPS-07",
        "reason": "LFPS polling corner not reachable on this SKU",
        "evidence": "sim/lfps_corner_analysis.md",
        "approver": "dv-lead",
        "risk": "LOW",
        "created_at": "2026-09-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "scope": {
            "requirement_ids": ["REQ-USB3-LFPS-07"],
            "subsystem": "usb3_link",
            "spec_revision": "spec-1.4",
            "design_evidence_hash": "deadbeef",
            "approval_id": "APR-1",
            "scope_hash": "cafebabe",
        },
        "affected_version": {"spec_revision": "spec-1.4", "rtl_hash": "rtl-aaa"},
        "revalidation_trigger": {"spec_revision": "spec-1.4", "rtl_hash": "rtl-aaa"},
    }


def _make_project(tmp_path, *, name="proj", with_coverage=True,
                  with_tools=False):
    """A real git project carrying real producers for most of section 238's
    baseline fields."""
    root = tmp_path / name
    (root / "rtl").mkdir(parents=True)
    (root / "doc").mkdir(parents=True)
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, input rst_n, output reg lfps_done);\n"
        "always @(posedge clk) lfps_done <= rst_n;\nendmodule\n", encoding="utf-8")
    (root / "doc" / "notes.md").write_text("# notes\n", encoding="utf-8")
    # .dv-harness/ is per-project RUNTIME state, and this test writes freeze
    # records and events into it -- keeping it out of git is what makes the
    # post-freeze impact analysis a statement about the DESIGN moving. The
    # __pycache__ exclusion is load-bearing for the same reason: the copied
    # tools/ tree really is executed by run_self_audit() during a bundle
    # export, and its freshly-written .pyc files would otherwise land in the
    # next commit and show up as MEDIUM-risk post-freeze changes that have
    # nothing to do with the DUT.
    (root / ".gitignore").write_text(
        ".dv-harness/\nbundle/\n__pycache__/\n*.pyc\n", encoding="utf-8")

    dvh = root / ".dv-harness"
    _write_json(dvh / "connectivity_check.json",
                {"rtl_sources": ["rtl/*.v"], "top_module": "usb3_link_ctrl"})
    _write_json(dvh / "config.json", {"policy": {"max_stage_retries": 2}})
    (dvh / "regression.list").write_text("usb3_lfps_basic PASS\n", encoding="utf-8")
    _write_json(dvh / "regression" / "computed_selection.json",
                {"base_sha": "x", "head_sha": "y", "selected": ["usb3_lfps_basic"]})
    _write_json(dvh / "vplan" / "vplan.json",
                {"vplan_id": "VP-1", "requirements": ["REQ-USB3-LFPS-07"]})
    _write_json(dvh / "lsf" / "jobs" / "987654.json",
                {"job_id": 987654, "pattern": "usb3_lfps_basic",
                 "assertion_failure": False, "uvm_fatal_count": 0,
                 "uvm_error_count": 0, "sim_status": "PASS"})
    if with_coverage:
        _write_json(dvh / "coverage" / "summary.json",
                    {"categories": [{"name": "functional", "percent": 91.0, "bins": 100}]})
    waiver_store.record_waiver(root, _waiver())

    if with_tools:
        shutil.copytree(ROOT / "tools", root / "tools")

    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "signoff-freeze@example.invalid")
    _git(root, "config", "user.name", "signoff-freeze-test")
    sha = _commit(root, "initial DUT + docs")
    return root, sha


# --- the fifteen declared fields -------------------------------------------

def test_section_238_field_list_and_capture_table_are_held_equal_both_ways():
    assert len(sx.SECTION_238_FIELDS) == 15
    assert set(sx.SECTION_238_FIELDS) == set(sx.BASELINE_CAPTURES)
    sx.assert_baseline_covers_section_238()


def test_a_field_with_no_capture_function_fails_the_import_time_assertion():
    saved = dict(sx.BASELINE_CAPTURES)
    try:
        sx.BASELINE_CAPTURES.pop("dut_sha")
        with pytest.raises(AssertionError) as exc:
            sx.assert_baseline_covers_section_238()
        assert "dut_sha" in str(exc.value)
    finally:
        sx.BASELINE_CAPTURES.clear()
        sx.BASELINE_CAPTURES.update(saved)


def test_a_capture_for_a_field_section_238_does_not_name_is_refused():
    saved = dict(sx.BASELINE_CAPTURES)
    try:
        sx.BASELINE_CAPTURES["moon_phase"] = lambda root, declared: None
        with pytest.raises(AssertionError) as exc:
            sx.assert_baseline_covers_section_238()
        assert "moon_phase" in str(exc.value)
    finally:
        sx.BASELINE_CAPTURES.clear()
        sx.BASELINE_CAPTURES.update(saved)


@requires_git
def test_every_field_is_reported_captured_or_not_available_with_a_real_reason(tmp_path):
    root, _ = _make_project(tmp_path)
    b = sx.capture_baseline(root)
    assert set(b["fields"]) == set(sx.SECTION_238_FIELDS)
    for name in sx.SECTION_238_FIELDS:
        f = b["fields"][name]
        assert f["status"] in (sx.CAPTURED, sx.NOT_AVAILABLE)
        assert f["reason"], f"{name} carries no reason"
        if f["status"] == sx.CAPTURED:
            assert f["digest"], f"{name} is CAPTURED with no digest"
            assert f["source"], f"{name} is CAPTURED with no source"
        else:
            assert f["digest"] is None


@requires_git
def test_the_real_producers_answer_the_fields_this_fixture_supplies(tmp_path):
    root, _ = _make_project(tmp_path)
    f = sx.capture_baseline(root)["fields"]
    for name in ("dut_sha", "tb_sha", "requirement_vplan_version",
                 "configuration", "test_list", "coverage_databases",
                 "assertion_status", "waivers", "agent_skill_versions",
                 "schema_policy_versions"):
        expected = sx.NOT_AVAILABLE if name == "tb_sha" else sx.CAPTURED
        assert f[name]["status"] == expected, (name, f[name])
    # dut_sha really is the RTL content fingerprint connectivity_check computes
    from dv_harness import connectivity_check as cc
    cfg = cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH)
    assert f["dut_sha"]["digest"] == cc.compute_rtl_fingerprint(root, cfg.rtl_sources)["fingerprint"]
    # waivers really carries the ledger's DERIVED status, not a stored one
    assert f["waivers"]["detail"]["statuses"] == {"W-238-1": "VALID"}


@requires_git
def test_spec_version_is_not_available_unless_a_human_declares_it(tmp_path):
    root, _ = _make_project(tmp_path)
    absent = sx.capture_baseline(root)["fields"]["spec_version"]
    assert absent["status"] == sx.NOT_AVAILABLE
    assert absent["reason"] == "NO_SPEC_VERSION_PRODUCER"

    declared = sx.capture_baseline(root, {"spec_version": "USB3.2-r1.1"})["fields"]["spec_version"]
    assert declared["status"] == sx.CAPTURED
    assert declared["detail"]["value"] == "USB3.2-r1.1"
    # attested, never presented as derived evidence
    assert declared["detail"]["attested"] is True
    assert declared["detail"]["machine_verified"] is False


@requires_git
def test_capture_baseline_creates_nothing(tmp_path):
    """Reading is not a mutating act: asking a project with nothing on disk
    what its baseline is must not bring a .dv-harness/, a state.json, a memory
    store or an evidence database into existence."""
    empty = tmp_path / "bare"
    empty.mkdir()
    b = sx.capture_baseline(empty)
    assert b["captured_field_count"] >= 1  # harness-owned fields still answer
    assert list(empty.iterdir()) == []
    assert b["fields"]["dut_sha"]["reason"] == "CONNECTIVITY_CHECK_NOT_CONFIGURED"
    assert b["fields"]["evidence_hashes"]["reason"] == "NO_EVIDENCE_DATABASE"


# --- the central proof -----------------------------------------------------

@requires_git
def test_freeze_then_change_the_fixture_then_the_check_fires(tmp_path):
    root, base_sha = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"

    result = sx.collect_signoff_bundle(root, bundle, freeze=True,
                                       frozen_by="dv-lead")
    frozen = result["freeze"]
    assert frozen is not None
    assert frozen["frozen_by"] == "dv-lead"
    assert frozen["bundle_hash"] == result["bundle_hash"]
    assert frozen["baseline"]["repo_head_sha"] == base_sha
    record_path = sx.freeze_dir(root) / f"{frozen['freeze_id']}.json"
    assert record_path.is_file()
    frozen_bytes_before = record_path.read_bytes()

    # NEGATIVE CONTROL: nothing changed -> the freeze is still VALID.
    clean = sx.evaluate_freeze_invalidation(root, frozen)
    assert clean["status"] == sx.FREEZE_VALID, clean["findings"]
    assert clean["findings"] == []
    assert clean["impact_analysis"]["status"] == "REAL_DIFF"
    assert clean["bundle"]["status"] == "BUNDLE_UNCHANGED"

    # Now really change the fixture: the DUT's RTL, committed.
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, input rst_n, output reg lfps_done);\n"
        "always @(posedge clk) lfps_done <= rst_n & 1'b1;  // behavior changed\n"
        "endmodule\n", encoding="utf-8")
    _commit(root, "change the LFPS done condition")

    after = sx.evaluate_freeze_invalidation(root, frozen)
    assert after["status"] == sx.FREEZE_INVALIDATED
    codes = {f["code"] for f in after["findings"]}
    # 1. the DUT SHA baseline field really diverged
    assert "BASELINE_FIELD_CHANGED" in codes
    changed = [f for f in after["findings"] if f["code"] == "BASELINE_FIELD_CHANGED"]
    assert [f["field"] for f in changed] == ["dut_sha"]
    assert changed[0]["detail"]["frozen_digest"] != changed[0]["detail"]["current_digest"]
    # 2. the post-freeze impact analysis names the real file at its real risk
    assert "POST_FREEZE_MATERIAL_CHANGE" in codes
    impact = [f for f in after["findings"] if f["code"] == "POST_FREEZE_MATERIAL_CHANGE"][0]
    assert impact["detail"]["material_changes"] == [
        {"path": "rtl/usb3_link_ctrl.v", "risk": "HIGH"}]
    assert impact["detail"]["base_sha"] == base_sha

    # The verdict is DERIVED: the frozen record on disk is byte-identical.
    assert record_path.read_bytes() == frozen_bytes_before


@requires_git
def test_a_low_risk_documentation_commit_does_not_invalidate_a_freeze(tmp_path):
    """The negative control that gives the impact analysis its power: a
    committed change that classify_risk() calls LOW must not invalidate a
    signoff, or every doc edit would."""
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    (root / "doc" / "notes.md").write_text("# notes\n\nmore prose\n", encoding="utf-8")
    _commit(root, "documentation only")
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_VALID, report["findings"]
    assert report["impact_analysis"]["changed_files"] == ["doc/notes.md"]
    assert report["impact_analysis"]["material_changes"] == []


# --- non-git material changes ---------------------------------------------

@requires_git
def test_revoking_a_waiver_after_the_freeze_invalidates_it_with_no_git_change(tmp_path):
    """A waiver's status is DERIVED on every read, so a waiver that stops
    being VALID after signoff is a post-freeze material change even though
    not one tracked file moved."""
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    assert sx.evaluate_freeze_invalidation(root, frozen)["status"] == sx.FREEZE_VALID

    waiver_store.revoke_waiver(root, "W-238-1", revoked_by="dv-lead",
                               reason="corner is reachable after all")
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_INVALIDATED
    fields = {f["field"] for f in report["findings"] if f["code"] == "BASELINE_FIELD_CHANGED"}
    assert fields == {"waivers"}
    assert report["impact_analysis"]["material_changes"] == []


@requires_git
def test_editing_the_coverage_database_after_the_freeze_invalidates_it(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    _write_json(root / ".dv-harness" / "coverage" / "summary.json",
                {"categories": [{"name": "functional", "percent": 74.0, "bins": 100}]})
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_INVALIDATED
    assert {f["field"] for f in report["findings"]
            if f["code"] == "BASELINE_FIELD_CHANGED"} == {"coverage_databases"}


@requires_git
def test_evidence_that_disappears_after_the_freeze_invalidates_it(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    (root / ".dv-harness" / "regression.list").unlink()
    (root / ".dv-harness" / "regression" / "computed_selection.json").unlink()
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_INVALIDATED
    gone = [f for f in report["findings"] if f["code"] == "BASELINE_EVIDENCE_DISAPPEARED"]
    assert [f["field"] for f in gone] == ["test_list"]
    assert gone[0]["detail"]["current_reason"] == "NO_REGRESSION_LIST_OR_COMPUTED_SELECTION"


@requires_git
def test_new_evidence_after_the_freeze_is_unknown_not_invalidated(tmp_path):
    """Evidence appearing after a signoff is a real change, but it is not
    proof the frozen evidence went wrong -- so it downgrades the verdict to
    UNKNOWN rather than claiming INVALIDATED."""
    root, _ = _make_project(tmp_path, with_coverage=False)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    assert frozen["baseline"]["fields"]["coverage_databases"]["status"] == sx.NOT_AVAILABLE

    _write_json(root / ".dv-harness" / "coverage" / "summary.json",
                {"categories": [{"name": "functional", "percent": 91.0, "bins": 100}]})
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_UNKNOWN
    assert report["invalidating_count"] == 0
    new = [f for f in report["findings"] if f["code"] == "NEW_EVIDENCE_AFTER_FREEZE"]
    assert [f["field"] for f in new] == ["coverage_databases"]


# --- bundle integrity ------------------------------------------------------

@requires_git
def test_a_bundle_edited_after_the_freeze_invalidates_it(tmp_path):
    root, _ = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"
    frozen = sx.collect_signoff_bundle(root, bundle, freeze=True,
                                       frozen_by="dv-lead")["freeze"]
    assert sx.evaluate_freeze_invalidation(root, frozen)["status"] == sx.FREEZE_VALID

    doc = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    doc["manifest"].append({"artifact": "smuggled", "present": True,
                            "bundled_path": "smuggled.json", "content_sha256": None})
    (bundle / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")

    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_INVALIDATED
    assert any(f["code"] == "FROZEN_BUNDLE_CHANGED" for f in report["findings"])
    assert report["bundle"]["recomputed_bundle_hash"] != frozen["bundle_hash"]


@requires_git
def test_a_bundle_that_is_gone_is_unknown_not_valid(tmp_path):
    root, _ = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"
    frozen = sx.collect_signoff_bundle(root, bundle, freeze=True,
                                       frozen_by="dv-lead")["freeze"]
    shutil.rmtree(bundle)
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_UNKNOWN
    assert any(f["code"] == "FROZEN_BUNDLE_NOT_FOUND" for f in report["findings"])


@requires_git
def test_a_project_with_no_git_history_reports_unknown_not_valid(tmp_path):
    """"We could not run the impact analysis" is never VALID."""
    root = tmp_path / "nogit"
    (root / ".dv-harness").mkdir(parents=True)
    _write_json(root / ".dv-harness" / "config.json", {"policy": {}})
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    assert frozen["baseline"]["repo_head_sha"] is None
    report = sx.evaluate_freeze_invalidation(root, frozen)
    assert report["status"] == sx.FREEZE_UNKNOWN
    codes = {f["code"] for f in report["findings"]}
    assert codes == {"POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE"}
    assert report["impact_analysis"]["status"] == "NO_RECORDED_HEAD_SHA"


# --- bundle wiring ---------------------------------------------------------

@requires_git
def test_bundle_manifest_carries_content_digests_without_moving_bundle_hash(tmp_path):
    """`content_sha256` is the content half section 238 asked for, and it is
    deliberately NOT material for compute_bundle_hash -- widening that would
    break signoff_bundle_completeness_gate.py's independent recomputation for
    every bundle produced before this change."""
    root, _ = _make_project(tmp_path, with_tools=True)
    result = sx.collect_signoff_bundle(root, tmp_path / "bundle")
    present = [m for m in result["manifest"] if m["present"]]
    assert present and all(m["content_sha256"] for m in present)
    assert all(m["content_sha256"] is None
               for m in result["manifest"] if not m["present"])

    stripped = [{k: v for k, v in m.items() if k != "content_sha256"}
                for m in result["manifest"]]
    assert sx.compute_bundle_hash(stripped) == result["bundle_hash"]

    entry = next(m for m in present if m["artifact"] == "self_audit_result")
    assert sx._sha256_file(Path(result["out_dir"]) / entry["bundled_path"]) == entry["content_sha256"]


@requires_git
def test_a_pre_gate_bundle_is_not_auto_frozen_and_a_gate_verified_one_is(tmp_path):
    """The auto-freeze wiring: `engine._export_signoff_bundle()` produces the
    SIGNOFF_GATE_VERIFIED bundle on a real gate-verified SIGNOFF PASS, and
    that -- and only that -- mints a frozen baseline by default."""
    root, _ = _make_project(tmp_path, with_tools=True)
    pre = sx.collect_signoff_bundle(root, tmp_path / "pre")
    assert pre["bundle_kind"] == "PRE_SIGNOFF_GATE_INPUT"
    assert pre["freeze"] is None
    assert sx.list_freezes(root) == []

    _write_json(root / ".dv-harness" / "state.json",
                {"project": "proj", "current_stage": "SIGNOFF",
                 "stages": {"SIGNOFF": {"status": "PASS", "attempts": 1}}})
    post = sx.collect_signoff_bundle(root, tmp_path / "post")
    assert post["bundle_kind"] == "SIGNOFF_GATE_VERIFIED"
    assert post["freeze"] is not None
    assert post["freeze"]["bundle_kind"] == "SIGNOFF_GATE_VERIFIED"
    assert (Path(post["out_dir"]) / "signoff_freeze.json").is_file()
    assert [r["freeze_id"] for r in sx.list_freezes(root)] == [post["freeze"]["freeze_id"]]


@requires_git
def test_freezing_writes_one_real_audit_event(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    events = [json.loads(line) for line in
              (root / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    frozen_events = [e for e in events if e.get("event") == sx.FREEZE_EVENT]
    assert len(frozen_events) == 1
    assert frozen_events[0]["freeze_id"] == frozen["freeze_id"]
    assert frozen_events[0]["frozen_by"] == "dv-lead"
    assert frozen_events[0]["stage"] == "SIGNOFF"


@requires_git
def test_a_standalone_freeze_recomputes_the_bundle_hash_rather_than_trusting_it(tmp_path):
    root, _ = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"
    result = sx.collect_signoff_bundle(root, bundle)
    doc = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    doc["bundle_hash"] = "0" * 64          # a lie written into the file
    (bundle / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")

    frozen = sx.freeze_signoff_baseline(root, bundle, frozen_by="dv-lead")
    assert frozen["bundle_hash"] == result["bundle_hash"]
    assert frozen["bundle_hash"] != "0" * 64


# --- freeze ledger ---------------------------------------------------------

@requires_git
def test_freezes_are_listed_in_frozen_at_order_and_load_defaults_to_the_latest(tmp_path):
    root, _ = _make_project(tmp_path)
    first = sx.freeze_signoff_baseline(root, frozen_by="a")
    time.sleep(0.01)
    _write_json(root / ".dv-harness" / "coverage" / "summary.json",
                {"categories": [{"name": "functional", "percent": 95.0, "bins": 100}]})
    second = sx.freeze_signoff_baseline(root, frozen_by="b")
    assert first["freeze_id"] != second["freeze_id"]
    assert [r["freeze_id"] for r in sx.list_freezes(root)] == [
        first["freeze_id"], second["freeze_id"]]
    assert sx.load_freeze(root)["freeze_id"] == second["freeze_id"]
    assert sx.load_freeze(root, first["freeze_id"])["frozen_by"] == "a"
    assert sx.load_freeze(root, "no-such-id") is None


@requires_git
def test_evaluate_all_freezes_reports_the_worst_present(tmp_path):
    root, _ = _make_project(tmp_path)
    stale = sx.freeze_signoff_baseline(root, frozen_by="a")
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk); endmodule\n", encoding="utf-8")
    _commit(root, "rtl moved")
    fresh = sx.freeze_signoff_baseline(root, frozen_by="b")

    report = sx.evaluate_all_freezes(root)
    assert report["status"] == sx.FREEZE_INVALIDATED
    assert report["freeze_count"] == 2
    assert report["counts"][sx.FREEZE_INVALIDATED] == 1
    assert report["counts"][sx.FREEZE_VALID] == 1
    by_id = {r["freeze_id"]: r["status"] for r in report["freezes"]}
    assert by_id[stale["freeze_id"]] == sx.FREEZE_INVALIDATED
    assert by_id[fresh["freeze_id"]] == sx.FREEZE_VALID


def test_evaluate_all_freezes_on_a_project_with_none_is_not_available(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    report = sx.evaluate_all_freezes(root)
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "NO_FROZEN_SIGNOFF_BASELINE"


# --- front door ------------------------------------------------------------

def _run_module(root, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "dv_harness.signoff_export",
                           *args, "--root", str(root)],
                          capture_output=True, text=True, timeout=300,
                          env=env, cwd=str(ROOT), encoding="utf-8", errors="replace")


@requires_git
def test_module_entry_point_reports_fields_freeze_and_status(tmp_path):
    root, _ = _make_project(tmp_path)

    r = _run_module(root, "fields")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["section_238_fields"] == list(sx.SECTION_238_FIELDS)

    # nothing frozen yet
    r = _run_module(root, "status")
    assert r.returncode == 2, r.stdout
    assert json.loads(r.stdout)["reason"] == "NO_FROZEN_SIGNOFF_BASELINE"

    # a freeze with no named human is refused
    r = _run_module(root, "freeze")
    assert r.returncode == 2
    assert json.loads(r.stdout)["reason"] == "FROZEN_BY_REQUIRED"
    assert sx.list_freezes(root) == []

    r = _run_module(root, "freeze", "--frozen-by", "dv-lead")
    assert r.returncode == 0, r.stderr
    fid = json.loads(r.stdout)["freeze_id"]

    r = _run_module(root, "status")
    assert r.returncode == 0, r.stdout
    assert json.loads(r.stdout)["status"] == sx.FREEZE_VALID

    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk); endmodule\n", encoding="utf-8")
    _commit(root, "rtl moved")

    r = _run_module(root, "status", "--freeze-id", fid)
    assert r.returncode == 1, r.stdout
    assert json.loads(r.stdout)["status"] == sx.FREEZE_INVALIDATED


# --- boundaries ------------------------------------------------------------

@requires_git
def test_evaluating_a_freeze_writes_nothing(tmp_path):
    """Reporting is not a mutating act: the invalidation check must not
    revalidate, re-freeze, approve or record anything."""
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")

    def snapshot():
        return {str(p.relative_to(root)): p.read_bytes()
                for p in sorted(root.rglob("*"))
                if p.is_file() and ".git" not in p.parts}

    before = snapshot()
    sx.evaluate_freeze_invalidation(root, frozen)
    sx.evaluate_all_freezes(root)
    assert snapshot() == before


def test_the_freeze_module_touches_no_approval_machinery():
    src = (ROOT / "dv_harness" / "signoff_export.py").read_text(encoding="utf-8")
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "bsub", "run_preflight"):
        assert forbidden not in src, forbidden


# --- freeze acceptance: revalidation is a human act, made real -------------
#
# WIRING_GAP_EXISTING_MODULE closure (signoff-freeze-revalidation-explicitly-
# undone). freeze_acceptance_digest()/freeze_acceptance_command()/
# freeze_acceptance_status() are pure functions over an already-fetched
# `approval` record -- proven directly below with no ControlPlane involved at
# all, so the "touches no approval machinery" test above and these tests can
# never disagree about what this module does. The real fetch-then-judge
# composition (commands.cmd_signoff_freeze_acceptance_status) is proven
# end-to-end against a REAL throwaway project and a REAL ControlPlane
# approval, mirroring dv_harness_tests/test_bounded_self_healing.py's own
# "commands.py wiring" tests for its sibling APPROVAL_ONLY_STAGES key.

def test_freeze_acceptance_digest_and_command_are_real_and_deterministic():
    evaluation = {"freeze_id": "fz-1", "findings": [
        {"code": "BASELINE_FIELD_CHANGED", "field": "waivers", "severity": "INVALIDATING"},
    ]}
    d1 = sx.freeze_acceptance_digest(evaluation)
    d2 = sx.freeze_acceptance_digest(evaluation)
    assert d1 == d2 and d1  # deterministic, non-empty

    # Reordering the SAME findings must not move the digest (sorted key).
    evaluation2 = {"freeze_id": "fz-1", "findings": list(reversed(evaluation["findings"] * 1))}
    assert sx.freeze_acceptance_digest(evaluation2) == d1

    # A genuinely different finding set moves it.
    evaluation3 = {"freeze_id": "fz-1", "findings": [
        {"code": "BASELINE_FIELD_CHANGED", "field": "waivers", "severity": "INVALIDATING"},
        {"code": "POST_FREEZE_MATERIAL_CHANGE", "field": None, "severity": "INVALIDATING"},
    ]}
    assert sx.freeze_acceptance_digest(evaluation3) != d1

    cmd = sx.freeze_acceptance_command("fz-1", d1)
    assert "dv-harness approve SIGNOFF_FREEZE_REVALIDATION" in cmd
    assert "fz-1" in cmd and d1 in cmd


def test_freeze_acceptance_status_is_a_pure_function_never_touching_disk():
    evaluation = {"freeze_id": "fz-1", "findings": [
        {"code": "BASELINE_FIELD_CHANGED", "field": "waivers", "severity": "INVALIDATING"},
    ]}
    digest = sx.freeze_acceptance_digest(evaluation)

    # negative control: no approval at all
    s = sx.freeze_acceptance_status(evaluation, None)
    assert s == {"accepted": False, "state": "ABSENT", "digest": digest, "approval": None}

    # negative control: an approval on file for a DIFFERENT freeze
    other = {"note": "freeze fz-OTHER 00000000: unrelated"}
    s = sx.freeze_acceptance_status(evaluation, other)
    assert s["accepted"] is False
    assert s["state"] == "PRESENT_BUT_NOT_MATCHING"

    # negative control: the right freeze_id but a stale/different digest
    stale = {"note": "freeze fz-1 00000000000000: stale"}
    s = sx.freeze_acceptance_status(evaluation, stale)
    assert s["accepted"] is False
    assert s["state"] == "PRESENT_BUT_NOT_MATCHING"

    # positive: freeze_id AND digest both present in the note
    matching = {"note": f"freeze fz-1 {digest}: reviewed and acceptable",
                "reviewer_id": "dv-lead", "approved_at": "2026-09-07T00:00:00+00:00"}
    s = sx.freeze_acceptance_status(evaluation, matching)
    assert s == {"accepted": True, "state": "PINNED_MATCH", "digest": digest, "approval": matching}


@requires_git
def test_evaluate_freeze_invalidation_with_acceptance_valid_freeze_never_requires_it(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    report = sx.evaluate_freeze_invalidation_with_acceptance(root, frozen)
    assert report["status"] == sx.FREEZE_VALID
    assert report["acceptance"] == {"required": False, "accepted": True, "state": "NOT_REQUIRED",
                                     "digest": None, "approval": None, "command": None}


@requires_git
def test_freeze_acceptance_becomes_true_only_after_a_real_pinned_approval(tmp_path):
    """The end-to-end proof that a human CAN accept an INVALIDATED freeze:
    revoke the waiver (a real, non-git material change), confirm the
    evaluation reports INVALIDATED with no acceptance on file, then record a
    real Control Plane approval citing the exact freeze_id+digest and confirm
    the SAME evaluation now reports accepted."""
    from dv_harness.control_plane import ControlPlane

    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    waiver_store.revoke_waiver(root, "W-238-1", revoked_by="dv-lead",
                               reason="corner is reachable after all")

    report = sx.evaluate_freeze_invalidation_with_acceptance(root, frozen)
    assert report["status"] == sx.FREEZE_INVALIDATED
    acceptance = report["acceptance"]
    assert acceptance["required"] is True
    assert acceptance["accepted"] is False
    assert acceptance["state"] == "ABSENT"
    digest = acceptance["digest"]
    assert frozen["freeze_id"] in acceptance["command"]
    assert digest in acceptance["command"]

    ControlPlane(root).approve(
        sx.SIGNOFF_FREEZE_REVALIDATION_STAGE,
        note=f"freeze {frozen['freeze_id']} {digest}: reviewed, acceptable",
        reviewer_id="dv-lead", reviewer_confidence="HIGH")

    approval = ControlPlane(root).get_approval(sx.SIGNOFF_FREEZE_REVALIDATION_STAGE)
    report2 = sx.evaluate_freeze_invalidation_with_acceptance(root, frozen, approval=approval)
    assert report2["status"] == sx.FREEZE_INVALIDATED  # the freeze is still, honestly, invalidated
    assert report2["acceptance"]["accepted"] is True
    assert report2["acceptance"]["state"] == "PINNED_MATCH"


@requires_git
def test_freeze_acceptance_is_explicitly_undone_by_a_new_divergence(tmp_path):
    """The headline negative control: a further divergence AFTER a human
    accepted one INVALIDATED evaluation must retire that acceptance rather
    than let it silently keep covering a WORSE, never-reviewed state -- the
    exact "revalidation" this item's own title says was never made real."""
    from dv_harness.control_plane import ControlPlane

    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    waiver_store.revoke_waiver(root, "W-238-1", revoked_by="dv-lead",
                               reason="corner is reachable after all")
    report = sx.evaluate_freeze_invalidation_with_acceptance(root, frozen)
    digest_before = report["acceptance"]["digest"]

    ControlPlane(root).approve(
        sx.SIGNOFF_FREEZE_REVALIDATION_STAGE,
        note=f"freeze {frozen['freeze_id']} {digest_before}: reviewed, acceptable",
        reviewer_id="dv-lead", reviewer_confidence="HIGH")
    approval = ControlPlane(root).get_approval(sx.SIGNOFF_FREEZE_REVALIDATION_STAGE)
    report = sx.evaluate_freeze_invalidation_with_acceptance(root, frozen, approval=approval)
    assert report["acceptance"]["accepted"] is True

    # A genuinely new, independent divergence -- the coverage database moves.
    _write_json(root / ".dv-harness" / "coverage" / "summary.json",
                {"categories": [{"name": "functional", "percent": 74.0, "bins": 100}]})

    report_after = sx.evaluate_freeze_invalidation_with_acceptance(root, frozen, approval=approval)
    assert report_after["status"] == sx.FREEZE_INVALIDATED
    assert report_after["acceptance"]["accepted"] is False
    assert report_after["acceptance"]["state"] == "PRESENT_BUT_NOT_MATCHING"
    assert report_after["acceptance"]["digest"] != digest_before
    # The stale approval is still real evidence on the record (never hidden);
    # it just no longer covers the current, worse evaluation.
    assert report_after["acceptance"]["approval"]["reviewer_id"] == "dv-lead"


# --- commands.py wiring: the real, already-existing `dv-harness approve` verb --

def test_commands_approval_stage_choices_includes_signoff_freeze_revalidation():
    from dv_harness import commands
    assert sx.SIGNOFF_FREEZE_REVALIDATION_STAGE in commands.APPROVAL_ONLY_STAGES
    assert sx.SIGNOFF_FREEZE_REVALIDATION_STAGE in commands.approval_stage_choices()


@requires_git
def test_cmd_signoff_freeze_acceptance_status_composes_a_real_approval(tmp_path):
    """commands.cmd_signoff_freeze_acceptance_status() is the real composition
    point: a real freeze, a real Control Plane approval fetch, and the SAME
    signoff_export.py functions proven pure above -- reused, not
    re-implemented."""
    from dv_harness import commands
    from dv_harness.control_plane import ControlPlane

    class _StubStore:
        def event(self, ev):
            pass

    class _StubHarness:
        pass

    root, _ = _make_project(tmp_path)
    h = _StubHarness()
    h.root = root
    h.store = _StubStore()

    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    report = commands.cmd_signoff_freeze_acceptance_status(h)
    assert report["status"] == sx.FREEZE_VALID
    assert report["acceptance"]["required"] is False

    waiver_store.revoke_waiver(root, "W-238-1", revoked_by="dv-lead",
                               reason="corner is reachable after all")
    report = commands.cmd_signoff_freeze_acceptance_status(h)
    assert report["status"] == sx.FREEZE_INVALIDATED
    assert report["acceptance"]["accepted"] is False
    digest = report["acceptance"]["digest"]

    # The REAL, generic, already-existing approval verb -- this is exactly
    # what `dv-harness approve SIGNOFF_FREEZE_REVALIDATION --note ...` does.
    entry = commands.cmd_approve(
        h, sx.SIGNOFF_FREEZE_REVALIDATION_STAGE,
        note=f"freeze {frozen['freeze_id']} {digest}: reviewed, acceptable",
        reviewer_id="dv-lead", reviewer_confidence="HIGH")
    assert entry["stage"] == sx.SIGNOFF_FREEZE_REVALIDATION_STAGE

    report = commands.cmd_signoff_freeze_acceptance_status(h)
    assert report["acceptance"]["accepted"] is True
    assert report["acceptance"]["state"] == "PINNED_MATCH"

    # Cross-checked against a direct ControlPlane read of the same record.
    approval = ControlPlane(root).get_approval(sx.SIGNOFF_FREEZE_REVALIDATION_STAGE)
    assert approval["reviewer_id"] == "dv-lead"
    assert report["acceptance"]["approval"] == approval


def test_cmd_signoff_freeze_acceptance_status_raises_with_no_frozen_baseline(tmp_path):
    from dv_harness import commands

    class _StubStore:
        def event(self, ev):
            pass

    class _StubHarness:
        pass

    h = _StubHarness()
    h.root = tmp_path
    h.store = _StubStore()

    import pytest as _pytest
    with _pytest.raises(ValueError):
        commands.cmd_signoff_freeze_acceptance_status(h)


def test_no_stage_gate_was_introduced_for_the_freeze():
    """A gate that passed because a freeze had not been recorded, or failed
    because one had, would be worse than none -- section 238 is a record, not
    a verdict on a stage."""
    from dv_harness.gates import STAGE_GATES
    for stage, entries in STAGE_GATES.items():
        for gate_id, _script, _flags in entries:
            assert "freeze" not in gate_id, (stage, gate_id)
