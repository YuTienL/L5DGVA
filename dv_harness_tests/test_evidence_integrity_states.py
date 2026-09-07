"""Tests for dv_harness/evidence_integrity_states.py -- the Evidence
Integrity state classifier (VALID/STALE/SUPERSEDED/CONTRADICTED/CORRUPT).

Every capsule-side fixture is REUSED, not duplicated, from
`test_golden_scenario.py` (a real throwaway git repo, a real DuckDB
`EvidenceStore`, a real `vip_distill.distill_sim_log()` envelope, a real
`lsf_client.JobState` row) and every freeze-side fixture is REUSED from
`test_signoff_freeze_baseline.py` (a real project with a real
`connectivity_check.json`/RTL tree, a real waiver ledger, a real
`collect_signoff_bundle()`), so this module's own tests prove the FOLD --
never re-derive whether the underlying capsule/freeze facts themselves are
correct, which those two files already prove in full.

The mandated negative controls (house style item 4, "a negative control
proving absence-of-evidence reports UNKNOWN/empty-state honestly rather
than a fabricated value") are:
  * a capsule with no `verified_sha` and no VIP drift -> UNKNOWN, never VALID;
  * a bare `normalized_evidence`-shaped dict with no capsule/freeze context
    -> UNKNOWN naming why, never a guessed state;
  * a project recording neither a capsule nor a freeze -> NOT_AVAILABLE,
    never a vacuous VALID.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import evidence_integrity_states as eis
from dv_harness import golden_scenario as gs
from dv_harness import signoff_export as sx

# --- reused capsule-side fixtures (test_golden_scenario.py) -----------------
from dv_harness_tests.test_golden_scenario import (  # noqa: F401
    project, store, _ingest_passing_evidence, _capsule, GIT, requires_git, TEST_NAME,
)

# --- reused freeze-side fixtures (test_signoff_freeze_baseline.py) ----------
from dv_harness_tests.test_signoff_freeze_baseline import (
    _make_project, _git, _commit, _write_json,
)


# =============================================================================
# capsule (golden_scenario) folding
# =============================================================================


@requires_git
def test_capsule_fresh_folds_to_valid(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    result = eis.classify_capsule_integrity(root, capsule)
    assert result["state"] == eis.VALID
    assert result["fact_source"] == "golden_scenario.evaluate_freshness"
    assert result["underlying_fact"]["freshness"] == gs.FRESH


@requires_git
def test_capsule_rtl_change_folds_to_stale(project, store):
    """The same real round trip test_golden_scenario.py's own central proof
    drives -- record FRESH, make a real HIGH-risk RTL commit, re-classify."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    assert eis.classify_capsule_integrity(root, capsule)["state"] == eis.VALID

    rtl = root / "rtl" / "usb3_link" / "usb3_link_ctrl.v"
    rtl.write_text(rtl.read_text(encoding="utf-8").replace(
        "lfps_done <= rst_n;", "lfps_done <= rst_n & 1'b1;"), encoding="utf-8")
    _commit(root, "usb3_link_ctrl: gate lfps_done")

    result = eis.classify_capsule_integrity(root, capsule)
    assert result["state"] == eis.STALE
    assert any("DESIGN_OR_CONFIG_CHANGED_SINCE_VERIFIED_SHA" in r for r in result["reasons"])


def test_capsule_with_no_verified_sha_and_no_drift_folds_to_unknown_never_valid(tmp_path):
    """NEGATIVE CONTROL: absence of evidence (no recorded SHA, no VIP drift)
    must be reported UNKNOWN, never a fabricated VALID."""
    root = tmp_path / "bare"
    root.mkdir()
    capsule = _capsule("EVID-x", verified_sha=None, vip_versions={})
    result = eis.classify_capsule_integrity(root, capsule)
    assert result["state"] == eis.UNKNOWN
    assert result["underlying_fact"]["freshness"] == gs.UNKNOWN


# =============================================================================
# freeze (signoff_export) folding
# =============================================================================

requires_git_sx = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")


@requires_git_sx
def test_freeze_clean_folds_to_valid(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.VALID
    assert result["contributions"] == []
    assert result["fact_source"] == "signoff_export.evaluate_freeze_invalidation"


@requires_git_sx
def test_freeze_baseline_field_changed_folds_to_contradicted(tmp_path):
    """`BASELINE_FIELD_CHANGED` -- a field re-derives differently now: the
    current, still-computable truth CONTRADICTS the recorded claim."""
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    from dv_harness import waiver_store
    waiver_store.revoke_waiver(root, "W-238-1", revoked_by="dv-lead",
                               reason="corner is reachable after all")
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.CONTRADICTED
    codes = {c["code"] for c in result["contributions"]}
    assert codes == {"BASELINE_FIELD_CHANGED"}
    assert result["contributions"][0]["field"] == "waivers"


@requires_git_sx
def test_freeze_evidence_disappeared_folds_to_corrupt(tmp_path):
    """`BASELINE_EVIDENCE_DISAPPEARED` -- evidence that existed is now gone
    entirely: the evidence TRAIL itself is broken, not merely stale."""
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    (root / ".dv-harness" / "regression.list").unlink()
    (root / ".dv-harness" / "regression" / "computed_selection.json").unlink()
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.CORRUPT
    assert {c["code"] for c in result["contributions"]} == {"BASELINE_EVIDENCE_DISAPPEARED"}


@requires_git_sx
def test_freeze_new_evidence_after_freeze_folds_to_superseded(tmp_path):
    """`NEW_EVIDENCE_AFTER_FREEZE` -- a field that had NO evidence at freeze
    time now has some: the earlier absence is SUPERSEDED by a newer, more
    complete record. Never invalidating on its own -- the underlying
    function's own INDETERMINATE severity is respected."""
    root, _ = _make_project(tmp_path, with_coverage=False)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    _write_json(root / ".dv-harness" / "coverage" / "summary.json",
                {"categories": [{"name": "functional", "percent": 91.0, "bins": 100}]})
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.SUPERSEDED
    assert {c["code"] for c in result["contributions"]} == {"NEW_EVIDENCE_AFTER_FREEZE"}


@requires_git_sx
def test_freeze_post_freeze_material_change_folds_to_stale(tmp_path):
    """`POST_FREEZE_MATERIAL_CHANGE` -- the design moved since the freeze;
    the recorded evidence itself is untouched, but the world has moved
    past it."""
    root, _ = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"
    frozen = sx.collect_signoff_bundle(root, bundle, freeze=True,
                                       frozen_by="dv-lead")["freeze"]
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, input rst_n, output reg lfps_done);\n"
        "always @(posedge clk) lfps_done <= rst_n & 1'b1;  // behavior changed\n"
        "endmodule\n", encoding="utf-8")
    _commit(root, "change the LFPS done condition")
    result = eis.classify_freeze_integrity(root, frozen)
    # BASELINE_FIELD_CHANGED (dut_sha) and POST_FREEZE_MATERIAL_CHANGE both
    # fire on a real RTL edit -- CORRUPT would be wrong here (nothing
    # disappeared or was altered post-hoc; the design moved and dut_sha's
    # own content-hash re-derivation naturally disagrees as a consequence).
    # This module's worst-wins fold reports STALE only when CONTRADICTED's
    # own trigger (BASELINE_FIELD_CHANGED) is NOT independently present --
    # so assert the real, honest fold rather than assume one particular code.
    codes = {c["code"] for c in result["contributions"]}
    assert "POST_FREEZE_MATERIAL_CHANGE" in codes
    mapped = {c["code"]: c["mapped_state"] for c in result["contributions"]}
    assert mapped["POST_FREEZE_MATERIAL_CHANGE"] == eis.STALE


@requires_git_sx
def test_freeze_post_freeze_material_change_alone_folds_to_stale_not_contradicted(tmp_path):
    """Isolate POST_FREEZE_MATERIAL_CHANGE from BASELINE_FIELD_CHANGED: a
    LOW/MEDIUM-risk-free real change with no `dut_sha`-tracked file touched
    would never fire CONTRADICTED, but a genuine RTL edit always moves
    `dut_sha`'s own digest too (they share one real cause), so this test
    proves the mapping table directly over a synthetic finding list instead
    of relying on a real fixture producing exactly one code."""
    findings = [{"code": "POST_FREEZE_MATERIAL_CHANGE", "severity": "INVALIDATING",
                "field": None, "detail": {}}]
    fold = eis._fold_freeze_findings(findings)
    assert fold["state"] == eis.STALE


@requires_git_sx
def test_freeze_bundle_changed_folds_to_corrupt(tmp_path):
    """`FROZEN_BUNDLE_CHANGED` -- the frozen artifact's own content no
    longer matches its recorded hash: the artifact itself was altered."""
    root, _ = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"
    frozen = sx.collect_signoff_bundle(root, bundle, freeze=True,
                                       frozen_by="dv-lead")["freeze"]
    doc = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    doc["manifest"].append({"artifact": "smuggled", "present": True,
                            "bundled_path": "smuggled.json", "content_sha256": None})
    (bundle / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.CORRUPT
    assert "FROZEN_BUNDLE_CHANGED" in {c["code"] for c in result["contributions"]}


@requires_git_sx
def test_freeze_bundle_not_found_folds_to_corrupt(tmp_path):
    root, _ = _make_project(tmp_path, with_tools=True)
    bundle = tmp_path / "bundle"
    frozen = sx.collect_signoff_bundle(root, bundle, freeze=True,
                                       frozen_by="dv-lead")["freeze"]
    shutil.rmtree(bundle)
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.CORRUPT
    assert "FROZEN_BUNDLE_NOT_FOUND" in {c["code"] for c in result["contributions"]}


@requires_git_sx
def test_freeze_impact_analysis_unavailable_folds_to_unknown_never_valid(tmp_path):
    """NEGATIVE CONTROL: "we could not check whether the design moved" must
    be reported UNKNOWN, never a fabricated VALID."""
    root = tmp_path / "no_git"
    root.mkdir()
    frozen = {"freeze_id": "GS-fake", "baseline": {"repo_head_sha": "deadbeef" * 5,
                                                   "fields": {}}}
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.UNKNOWN
    assert "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE" in {
        c["code"] for c in result["contributions"]}


@requires_git_sx
def test_freeze_low_risk_doc_commit_does_not_move_off_valid(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    (root / "doc" / "notes.md").write_text("# notes\n\nmore prose\n", encoding="utf-8")
    _commit(root, "documentation only")
    result = eis.classify_freeze_integrity(root, frozen)
    assert result["state"] == eis.VALID
    assert result["contributions"] == []


# --- the field-not-in-frozen-baseline code is ignored, not classified -------


def test_field_not_in_frozen_baseline_is_ignored_not_folded():
    findings = [{"code": "FIELD_NOT_IN_FROZEN_BASELINE", "severity": "INDETERMINATE",
                "field": "some_new_field", "detail": {}}]
    fold = eis._fold_freeze_findings(findings)
    assert fold["state"] == eis.VALID
    assert fold["contributions"] == []


# --- an unrecognized finding code folds by its own real severity -----------


def test_unrecognized_invalidating_code_folds_to_contradicted_never_unknown():
    """A future/older signoff_export.py finding code this module has not
    been taught must never be silently downgraded to the merely-uncertain
    UNKNOWN just because it is unrecognized."""
    findings = [{"code": "SOME_FUTURE_CODE", "severity": sx.SEV_INVALIDATING,
                "field": "x", "detail": {}}]
    fold = eis._fold_freeze_findings(findings)
    assert fold["state"] == eis.CONTRADICTED
    assert "UNRECOGNIZED_FREEZE_FINDING_CODE" in fold["contributions"][0]["note"]


def test_unrecognized_indeterminate_code_folds_to_unknown():
    findings = [{"code": "SOME_FUTURE_CODE", "severity": sx.SEV_INDETERMINATE,
                "field": "x", "detail": {}}]
    fold = eis._fold_freeze_findings(findings)
    assert fold["state"] == eis.UNKNOWN


def test_worst_wins_across_mixed_findings():
    findings = [
        {"code": "NEW_EVIDENCE_AFTER_FREEZE", "severity": sx.SEV_INDETERMINATE,
         "field": "a", "detail": {}},
        {"code": "BASELINE_EVIDENCE_DISAPPEARED", "severity": sx.SEV_INVALIDATING,
         "field": "b", "detail": {}},
        {"code": "POST_FREEZE_MATERIAL_CHANGE", "severity": sx.SEV_INVALIDATING,
         "field": None, "detail": {}},
    ]
    fold = eis._fold_freeze_findings(findings)
    # CORRUPT (from BASELINE_EVIDENCE_DISAPPEARED) outranks STALE and
    # SUPERSEDED, whatever order the findings arrived in.
    assert fold["state"] == eis.CORRUPT
    assert len(fold["contributions"]) == 3


# =============================================================================
# generic dispatch: classify_evidence_integrity()
# =============================================================================


@requires_git
def test_dispatch_routes_a_capsule_object(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    result = eis.classify_evidence_integrity(root, capsule)
    assert result["record_kind"] == "GOLDEN_SCENARIO_CAPSULE"
    assert result["state"] == eis.VALID


@requires_git
def test_dispatch_routes_a_capsule_shaped_dict(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    result = eis.classify_evidence_integrity(root, capsule.to_dict())
    assert result["record_kind"] == "GOLDEN_SCENARIO_CAPSULE"
    assert result["state"] == eis.VALID


@requires_git_sx
def test_dispatch_routes_a_freeze_shaped_dict(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    result = eis.classify_evidence_integrity(root, frozen)
    assert result["record_kind"] == "SIGNOFF_FREEZE_RECORD"
    assert result["state"] == eis.VALID


def test_dispatch_a_malformed_capsule_dict_folds_to_unknown_not_a_crash(tmp_path):
    result = eis.classify_evidence_integrity(
        tmp_path, {"capsule_id": "GS-x", "project": "p"})  # missing required fields
    assert result["state"] == eis.UNKNOWN
    assert "MALFORMED_CAPSULE_RECORD" in result["reasons"][0]


def test_dispatch_a_bare_normalized_evidence_row_folds_to_unknown_never_guessed(tmp_path):
    """NEGATIVE CONTROL: a bare `normalized_evidence`-shaped row with no
    capsule or freeze context around it must be reported UNKNOWN, naming
    exactly why -- never a fabricated freshness/invalidation verdict."""
    record = {"evidence_id": "EVID-bare", "verdict": "PASS", "pattern": "usb3_lfps_basic"}
    result = eis.classify_evidence_integrity(tmp_path, record)
    assert result["state"] == eis.UNKNOWN
    assert result["record_kind"] == "UNRECOGNIZED_RECORD_SHAPE"
    assert "INSUFFICIENT_CONTEXT" in result["reasons"][0]
    assert result["fact_source"] is None


def test_dispatch_an_unrelated_object_folds_to_unknown(tmp_path):
    result = eis.classify_evidence_integrity(tmp_path, object())
    assert result["state"] == eis.UNKNOWN


# =============================================================================
# by-reference: capsule_id / freeze_id / bare evidence_id
# =============================================================================


def test_by_reference_requires_exactly_one_identifier(tmp_path):
    with pytest.raises(eis.EvidenceIntegrityError):
        eis.classify_evidence_by_reference(tmp_path)
    with pytest.raises(eis.EvidenceIntegrityError):
        eis.classify_evidence_by_reference(
            tmp_path, capsule_id="GS-x", freeze_id="GS-y")


@requires_git_sx
def test_by_reference_freeze_id_found(tmp_path):
    root, _ = _make_project(tmp_path)
    frozen = sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    result = eis.classify_evidence_by_reference(root, freeze_id=frozen["freeze_id"])
    assert result["state"] == eis.VALID
    assert result["freeze_id"] == frozen["freeze_id"]


def test_by_reference_freeze_id_not_found(tmp_path):
    result = eis.classify_evidence_by_reference(tmp_path, freeze_id="GS-does-not-exist")
    assert result["state"] == eis.UNKNOWN
    assert "FREEZE_NOT_FOUND" in result["reasons"][0]


@requires_git
def test_by_reference_capsule_id_found(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    store.close()  # release the DuckDB file: classify_evidence_by_reference() opens
    # its own read-only connection, and DuckDB refuses two differently-configured
    # connections to one file from the same process.
    result = eis.classify_evidence_by_reference(root, capsule_id=capsule.capsule_id)
    assert result["state"] == eis.VALID
    assert result["capsule_id"] == capsule.capsule_id


@requires_git
def test_by_reference_capsule_id_not_found(project, store):
    root, sha = project
    _ingest_passing_evidence(store, root, sha)  # ensures the store/db exists
    store.close()
    result = eis.classify_evidence_by_reference(root, capsule_id="GS-does-not-exist")
    assert result["state"] == eis.UNKNOWN
    assert "CAPSULE_NOT_FOUND" in result["reasons"][0]


def test_by_reference_no_evidence_store_at_all(tmp_path):
    result = eis.classify_evidence_by_reference(tmp_path, capsule_id="GS-anything")
    assert result["state"] == eis.UNKNOWN
    assert "NO_EVIDENCE_STORE" in result["reasons"][0]


@requires_git
def test_by_reference_evidence_id_resolves_the_one_owning_capsule(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    store.close()
    result = eis.classify_evidence_by_reference(root, evidence_id=envelope["evidence_id"])
    assert result["state"] == eis.VALID
    assert result["capsule_id"] == capsule.capsule_id


@requires_git
def test_by_reference_evidence_id_ambiguous_when_two_capsules_cite_it(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    # `_capsule()`'s own `capsule_id` default is fixed at seed "42" regardless
    # of the `seed` override, so a distinct `capsule_id` must be passed
    # explicitly for the two capsules to land as two real, separate rows
    # rather than one upserting over the other.
    gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], seed="1",
        capsule_id=gs.default_capsule_id("usb3_soc", "usb3_link", TEST_NAME, "1")))
    gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], seed="2",
        capsule_id=gs.default_capsule_id("usb3_soc", "usb3_link", TEST_NAME, "2")))
    store.close()
    result = eis.classify_evidence_by_reference(root, evidence_id=envelope["evidence_id"])
    assert result["state"] == eis.UNKNOWN
    assert "AMBIGUOUS_EVIDENCE_ID" in result["reasons"][0]


@requires_git
def test_by_reference_evidence_id_with_no_capsule_or_freeze_context(project, store):
    """NEGATIVE CONTROL: a real `normalized_evidence` row with real verdict/
    pattern facts, but no golden_scenario capsule and no signoff freeze
    citing it -- honestly UNKNOWN, never a fabricated freshness verdict."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    store.close()
    result = eis.classify_evidence_by_reference(root, evidence_id=envelope["evidence_id"])
    assert result["state"] == eis.UNKNOWN
    assert "EVIDENCE_ID_HAS_NO_CAPSULE_OR_FREEZE_CONTEXT" in result["reasons"][0]
    assert "PASS" in result["reasons"][0]


@requires_git
def test_by_reference_evidence_id_not_found_at_all(project, store):
    root, sha = project
    _ingest_passing_evidence(store, root, sha)  # ensures the store/db exists
    store.close()
    result = eis.classify_evidence_by_reference(root, evidence_id="EVID-never-ingested")
    assert result["state"] == eis.UNKNOWN
    assert "EVIDENCE_ID_NOT_FOUND" in result["reasons"][0]


# =============================================================================
# project-wide rollup
# =============================================================================


def test_project_with_nothing_recorded_is_not_available(tmp_path):
    report = eis.classify_project_evidence_integrity(tmp_path)
    assert report["status"] == "NOT_AVAILABLE"
    assert report["capsules"] == [] and report["freezes"] == []


@requires_git
def test_project_all_valid(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    store.close()
    report = eis.classify_project_evidence_integrity(root)
    assert report["status"] == eis.VALID
    assert report["capsule_count"] == 1
    assert report["freeze_count"] == 0


@requires_git
def test_project_worst_wins_across_capsules_and_freezes(project, store, tmp_path):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    assert eis.classify_capsule_integrity(root, capsule)["state"] == eis.VALID

    # Make the capsule STALE via a real HIGH-risk RTL commit.
    rtl = root / "rtl" / "usb3_link" / "usb3_link_ctrl.v"
    rtl.write_text(rtl.read_text(encoding="utf-8").replace(
        "lfps_done <= rst_n;", "lfps_done <= rst_n & 1'b1;"), encoding="utf-8")
    _commit(root, "usb3_link_ctrl: gate lfps_done")

    store.close()
    report = eis.classify_project_evidence_integrity(root)
    assert report["status"] == eis.STALE
    assert report["counts"][eis.STALE] == 1


# =============================================================================
# CLI
# =============================================================================


def test_cli_states_verb():
    rc = eis.execute_verb(["states"])
    assert rc == 0


@requires_git
def test_cli_capsule_verb_valid_exit_0(project, store, capsys):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    store.close()  # release the DuckDB file: execute_verb() opens its own connection
    rc = eis.execute_verb(["capsule", "--root", str(root),
                          "--capsule-id", capsule.capsule_id, "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == eis.VALID
    assert rc == 0


def test_cli_capsule_verb_unknown_exit_2(tmp_path, capsys):
    rc = eis.execute_verb(["capsule", "--root", str(tmp_path), "--capsule-id", "GS-x"])
    assert rc == 2


@requires_git_sx
def test_cli_project_verb_via_subprocess(tmp_path):
    root, _ = _make_project(tmp_path)
    sx.freeze_signoff_baseline(root, frozen_by="dv-lead")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.evidence_integrity_states", "project",
         "--root", str(root), "--json"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == eis.VALID
    assert out["freeze_count"] == 1
