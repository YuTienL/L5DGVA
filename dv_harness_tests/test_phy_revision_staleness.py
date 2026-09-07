"""Tests for dv_harness/phy_revision_staleness.py -- the PHY-revision
re-architect trigger. Every fingerprint is computed over REAL files written
to a real temp project root (never a hand-typed fake hash), and every
memory-tier mutation is proven against a REAL MemoryStore driven through
the REAL memory_router.route_and_store()/memory.MemoryStore -- never a
mock of either."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import cross_project_mining as cpm
from dv_harness import phy_revision_staleness as prs
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _phy_module_rtl(tmp_path, phy_name="phy_top", other_name="ctrl_top",
                     phy_text="module phy_top; endmodule\n"):
    """A real phy file + a real, unrelated second file, plus the
    verible_parser.to_dict()-shaped rtl_modules list this module consumes."""
    phy_file = _write(tmp_path / "rtl" / "phy_top.sv", phy_text)
    other_file = _write(tmp_path / "rtl" / "ctrl_top.sv", "module ctrl_top; endmodule\n")
    rtl_modules = [
        {"file_path": str(phy_file), "source_sha256": "unused",
         "modules": [{"name": phy_name}]},
        {"file_path": str(other_file), "source_sha256": "unused",
         "modules": [{"name": other_name}]},
    ]
    return phy_file, other_file, rtl_modules


# ---------------------------------------------------------------------------
# derive_phy_module_files -- structural evidence, 3 input shapes
# ---------------------------------------------------------------------------

def test_derive_phy_module_files_bare_list(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    assert prs.derive_phy_module_files(rtl_modules, "phy_top") == [str(phy_file)]


def test_derive_phy_module_files_dut_facts_rtl_shape(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    dut_facts_rtl = {"status": "PARSED", "reason": None, "files": rtl_modules}
    assert prs.derive_phy_module_files(dut_facts_rtl, "phy_top") == [str(phy_file)]


def test_derive_phy_module_files_full_env_manifest_shape(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    manifest = {"dut_facts": {"rtl": {"status": "PARSED", "reason": None, "files": rtl_modules}}}
    assert prs.derive_phy_module_files(manifest, "phy_top") == [str(phy_file)]


def test_derive_phy_module_files_module_not_present_is_honestly_empty(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    # Never a guessed/fabricated match -- an absent module is a real, honest
    # empty list, not an error and not a fabricated file.
    assert prs.derive_phy_module_files(rtl_modules, "nonexistent_phy") == []


def test_derive_phy_module_files_declared_in_two_files_returns_both(tmp_path):
    phy_a = _write(tmp_path / "rtl" / "phy_a.sv", "module phy_top; endmodule\n")
    phy_b = _write(tmp_path / "rtl" / "phy_b.sv", "module phy_top; endmodule\n")
    rtl_modules = [
        {"file_path": str(phy_a), "modules": [{"name": "phy_top"}]},
        {"file_path": str(phy_b), "modules": [{"name": "phy_top"}]},
    ]
    assert prs.derive_phy_module_files(rtl_modules, "phy_top") == sorted([str(phy_a), str(phy_b)])


def test_derive_phy_module_files_empty_module_name_raises():
    with pytest.raises(prs.PhyRevisionStalenessError) as exc:
        prs.derive_phy_module_files([], "")
    assert exc.value.reason == "PHY_MODULE_NOT_DECLARED"


# ---------------------------------------------------------------------------
# compute_phy_module_fingerprint -- real content hash, anti-vacuous rule
# ---------------------------------------------------------------------------

def test_fingerprint_empty_file_list_is_not_available(tmp_path):
    # The anti-vacuous-fingerprint rule: an empty declared file set must
    # never compute a constant fingerprint that would compare equal forever.
    result = prs.compute_phy_module_fingerprint(tmp_path, [])
    assert result["status"] == "NOT_AVAILABLE"
    assert result["fingerprint"] is None


def test_fingerprint_real_file_computed(tmp_path):
    phy_file, _, _ = _phy_module_rtl(tmp_path)
    result = prs.compute_phy_module_fingerprint(tmp_path, [str(phy_file)])
    assert result["status"] == "COMPUTED"
    assert result["file_count"] == 1
    assert len(result["fingerprint"]) == 64  # real sha256 hex digest


def test_fingerprint_is_stable_over_unchanged_content(tmp_path):
    phy_file, _, _ = _phy_module_rtl(tmp_path)
    a = prs.compute_phy_module_fingerprint(tmp_path, [str(phy_file)])
    b = prs.compute_phy_module_fingerprint(tmp_path, [str(phy_file)])
    assert a["fingerprint"] == b["fingerprint"]


def test_fingerprint_changes_with_real_content_edit(tmp_path):
    phy_file, _, _ = _phy_module_rtl(tmp_path)
    before = prs.compute_phy_module_fingerprint(tmp_path, [str(phy_file)])
    phy_file.write_text("module phy_top; // edited\nendmodule\n", encoding="utf-8")
    after = prs.compute_phy_module_fingerprint(tmp_path, [str(phy_file)])
    assert before["fingerprint"] != after["fingerprint"]


def test_fingerprint_missing_files_is_not_available(tmp_path):
    missing = tmp_path / "rtl" / "does_not_exist.sv"
    result = prs.compute_phy_module_fingerprint(tmp_path, [str(missing)])
    assert result["status"] == "NOT_AVAILABLE"
    assert str(missing) in result["missing_files"]


def test_fingerprint_reuses_env_manifest_file_ref(tmp_path):
    """Direct proof of reuse: this module's per-file digest equals a
    completely independent call into env_manifest.file_ref() over the same
    real file, so there is one definition of "hash this file" in this repo."""
    from dv_harness import env_manifest as em
    phy_file, _, _ = _phy_module_rtl(tmp_path)
    result = prs.compute_phy_module_fingerprint(tmp_path, [str(phy_file)])
    rel = "rtl/phy_top.sv"
    assert result["files"][rel] == em.file_ref(phy_file)["sha256"]


# ---------------------------------------------------------------------------
# build/record/list/load decision record
# ---------------------------------------------------------------------------

def test_build_decision_record_phy_module_not_found_raises(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    with pytest.raises(prs.PhyRevisionStalenessError) as exc:
        prs.build_phy_revision_decision_record(
            tmp_path, "nonexistent_phy", rtl_modules,
            {"kind": "phy_boundary_bind", "path": "phy_boundary.json"})
    assert exc.value.reason == "PHY_MODULE_NOT_FOUND_IN_RTL"


def test_decision_ref_missing_kind_raises(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    with pytest.raises(prs.PhyRevisionStalenessError) as exc:
        prs.build_phy_revision_decision_record(tmp_path, "phy_top", rtl_modules, {})
    assert exc.value.reason == "DECISION_REF_MISSING_KIND"


def test_architecture_decision_ref_missing_memory_id_raises(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    with pytest.raises(prs.PhyRevisionStalenessError) as exc:
        prs.build_phy_revision_decision_record(
            tmp_path, "phy_top", rtl_modules, {"kind": "architecture_decision"})
    assert exc.value.reason == "DECISION_REF_MISSING_MEMORY_ID"


def test_record_save_list_load_round_trip(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    decision_ref = {"kind": "phy_boundary_bind", "path": "phy_boundary.json"}
    record = prs.record_phy_revision_decision(tmp_path, "phy_top", rtl_modules, decision_ref)
    assert record["phy_module"] == "phy_top"
    assert record["fingerprint_at_decision"]

    listed = prs.list_phy_revision_decisions(tmp_path)
    assert len(listed) == 1
    assert listed[0]["decision_id"] == record["decision_id"]

    loaded = prs.load_phy_revision_decision_record(tmp_path, record["decision_id"])
    assert loaded == record

    on_disk = prs.decisions_dir(tmp_path) / f"{record['decision_id']}.json"
    assert on_disk.is_file()


def test_list_decisions_on_bare_project_is_empty(tmp_path):
    assert prs.list_phy_revision_decisions(tmp_path) == []


def test_list_decisions_skips_a_corrupt_record_file(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    good = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "phy_boundary_bind"})
    corrupt_path = prs.decisions_dir(tmp_path) / "corrupt.json"
    corrupt_path.write_text("{not valid json", encoding="utf-8")
    listed = prs.list_phy_revision_decisions(tmp_path)
    ids = [r["decision_id"] for r in listed]
    assert good["decision_id"] in ids
    assert len(listed) == 1


# ---------------------------------------------------------------------------
# evaluate_phy_revision_staleness -- the standing trigger
# ---------------------------------------------------------------------------

def test_evaluate_up_to_date(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "phy_boundary_bind"})
    evaluation = prs.evaluate_phy_revision_staleness(record, tmp_path)
    assert evaluation["status"] == prs.STATUS_UP_TO_DATE
    assert evaluation["needs_reevaluation"] is False


def test_evaluate_phy_rtl_changed_after_real_edit(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "phy_boundary_bind"})
    phy_file.write_text("module phy_top; // real content change\nendmodule\n", encoding="utf-8")
    evaluation = prs.evaluate_phy_revision_staleness(record, tmp_path)
    assert evaluation["status"] == prs.STATUS_PHY_RTL_CHANGED
    assert evaluation["needs_reevaluation"] is True
    assert evaluation["recorded_fingerprint"] != evaluation["current_fingerprint"]


def test_evaluate_unrelated_file_edit_stays_up_to_date(tmp_path):
    """Negative control: editing the OTHER (non-PHY) module's file must
    never flip a PHY-module decision stale -- this fingerprint is scoped to
    exactly the PHY module's own declaring file(s)."""
    phy_file, other_file, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "phy_boundary_bind"})
    other_file.write_text("module ctrl_top; // unrelated edit\nendmodule\n", encoding="utf-8")
    evaluation = prs.evaluate_phy_revision_staleness(record, tmp_path)
    assert evaluation["status"] == prs.STATUS_UP_TO_DATE


def test_evaluate_missing_source_file_is_unavailable_never_up_to_date(tmp_path):
    """The required negative control: this module must refuse to fabricate
    an "unchanged" answer when it genuinely could not re-check the real
    file -- deleting the PHY module's own source file must never read as
    STATUS_UP_TO_DATE."""
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "phy_boundary_bind"})
    phy_file.unlink()
    evaluation = prs.evaluate_phy_revision_staleness(record, tmp_path)
    assert evaluation["status"] == prs.STATUS_PHY_SOURCE_FILES_UNAVAILABLE
    assert evaluation["needs_reevaluation"] is True
    assert evaluation["current_fingerprint"] is None


def test_evaluate_record_missing_fingerprint_is_honest_not_fabricated(tmp_path):
    evaluation = prs.evaluate_phy_revision_staleness(
        {"phy_module_source_files": ["x.sv"]}, tmp_path)
    assert evaluation["status"] == prs.STATUS_RECORD_MISSING_FINGERPRINT
    assert evaluation["needs_reevaluation"] is True


# ---------------------------------------------------------------------------
# flag_stale_phy_revision_decision -- the real flagging mechanism
# ---------------------------------------------------------------------------

def test_flag_up_to_date_never_touches_memory(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": "does-not-matter"})
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_UP_TO_DATE
    assert not cpm.has_memory_store(tmp_path)


def test_flag_phy_boundary_bind_kind_is_report_only(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "phy_boundary_bind", "path": "phy_boundary.json"})
    phy_file.write_text("module phy_top; // v2\nendmodule\n", encoding="utf-8")
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_REPORTED_ONLY
    assert "extract_phy_boundary" in result["next_action"]
    # A phy_boundary.json bind decision has no mutation target -- this
    # module must never mint a memory store while reporting on it.
    assert not cpm.has_memory_store(tmp_path)


def test_flag_architecture_decision_no_memory_store_never_mints_one(tmp_path):
    """The required negative control for the memory-tier path: a project
    with no memory store at all must never have one fabricated merely
    because a staleness flag was attempted."""
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": "mem-does-not-exist"})
    phy_file.write_text("module phy_top; // v2\nendmodule\n", encoding="utf-8")
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_SKIPPED_NO_MEMORY_STORE
    assert not cpm.has_memory_store(tmp_path)


def test_flag_architecture_decision_real_memory_record_is_flagged(tmp_path):
    """The headline proof: a real, gate-verified architecture_decision
    memory record's status is really mutated to NEEDS_REVALIDATION through
    the REAL, unmodified memory.MemoryGC.flag_stale() -- no second flagging
    mechanism."""
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    routed = route_and_store(tmp_path, {
        "kind": "architecture_decision", "verified": True,
        "protocol": "USB3", "title": "bind PHY at parallel boundary",
        "decision": "mount at controller_phy_parallel_boundary",
    }, cfg={})
    memory_id = routed["memory_id"]

    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": memory_id})

    phy_file.write_text("module phy_top; // v2 real edit\nendmodule\n", encoding="utf-8")

    evaluation = prs.evaluate_phy_revision_staleness(record, tmp_path)
    assert evaluation["needs_reevaluation"] is True

    result = prs.flag_stale_phy_revision_decision(record, tmp_path, evaluation=evaluation)
    assert result["outcome"] == prs.FLAG_FLAGGED

    store = MemoryStore(tmp_path)
    mem = store.get(memory_id)
    assert mem["status"] == "NEEDS_REVALIDATION"
    assert mem["stale_reason"] == evaluation["detail"]
    assert "phy_top" in mem["stale_reason"]


def test_flag_architecture_decision_unknown_memory_id_is_skipped(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    # A real store must already exist for FLAG_SKIPPED_RECORD_NOT_FOUND to
    # be reachable at all (an absent store is FLAG_SKIPPED_NO_MEMORY_STORE).
    route_and_store(tmp_path, {
        "kind": "architecture_decision", "verified": True,
        "protocol": "USB3", "title": "unrelated decision",
    }, cfg={})
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": "totally-unknown-id"})
    phy_file.write_text("module phy_top; // v2\nendmodule\n", encoding="utf-8")
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_SKIPPED_RECORD_NOT_FOUND


def test_flag_architecture_decision_kind_mismatch_is_skipped(tmp_path):
    """A memory_id that resolves to a REAL record of a DIFFERENT kind must
    never be flagged as if it were the architecture_decision it was
    declared to be."""
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    routed = route_and_store(tmp_path, {
        "kind": "root_cause", "verified": True, "confidence": "HIGH",
        "protocol": "USB3", "root_cause": "unrelated finding",
        "fix": "unrelated fix", "evidence": ["log:1"],
    }, cfg={})
    memory_id = routed["memory_id"]

    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": memory_id})
    phy_file.write_text("module phy_top; // v2\nendmodule\n", encoding="utf-8")
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_SKIPPED_KIND_MISMATCH
    assert result["found_kind"] == "root_cause"

    # And the unrelated real record must be left completely untouched.
    store = MemoryStore(tmp_path)
    mem = store.get(memory_id)
    assert mem["status"] != "NEEDS_REVALIDATION"


def test_flag_unknown_decision_ref_kind_is_skipped(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "some_other_decision_kind"})
    phy_file.write_text("module phy_top; // v2\nendmodule\n", encoding="utf-8")
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_SKIPPED_UNKNOWN_KIND


def test_flag_architecture_decision_missing_memory_id_field(tmp_path):
    """A record hand-edited to strip its own decision_ref.memory_id (bypassing
    build_phy_revision_decision_record's own construction-time refusal) must
    still be handled honestly rather than crashing."""
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": "placeholder"})
    record["decision_ref"] = {"kind": "architecture_decision"}
    phy_file.write_text("module phy_top; // v2\nendmodule\n", encoding="utf-8")
    result = prs.flag_stale_phy_revision_decision(record, tmp_path)
    assert result["outcome"] == prs.FLAG_SKIPPED_MISSING_MEMORY_ID


# ---------------------------------------------------------------------------
# scan_phy_revision_decisions -- batch sweep
# ---------------------------------------------------------------------------

def test_scan_reports_every_decision_with_its_own_outcome(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    routed = route_and_store(tmp_path, {
        "kind": "architecture_decision", "verified": True,
        "protocol": "USB3", "title": "bind decision under scan",
    }, cfg={})
    memory_id = routed["memory_id"]

    up_to_date_record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "phy_boundary_bind", "path": "phy_boundary.json"},
        decision_id="rec-up-to-date")
    stale_mem_record = prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules,
        {"kind": "architecture_decision", "memory_id": memory_id},
        decision_id="rec-stale-memory")

    phy_file.write_text("module phy_top; // real edit for scan\nendmodule\n", encoding="utf-8")

    report = prs.scan_phy_revision_decisions(tmp_path)
    assert report["decision_count"] == 2
    assert report["stale_count"] == 2
    assert report["flagged_count"] == 1

    by_id = {d["decision_id"]: d for d in report["decisions"]}
    assert by_id["rec-up-to-date"]["flag"]["outcome"] == prs.FLAG_REPORTED_ONLY
    assert by_id["rec-stale-memory"]["flag"]["outcome"] == prs.FLAG_FLAGGED

    store = MemoryStore(tmp_path)
    assert store.get(memory_id)["status"] == "NEEDS_REVALIDATION"


def test_scan_on_bare_project_is_empty_and_clean(tmp_path):
    report = prs.scan_phy_revision_decisions(tmp_path)
    assert report == {"decision_count": 0, "stale_count": 0, "flagged_count": 0, "decisions": []}


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.phy_revision_staleness", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def test_cli_fingerprint_verb_subprocess(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    rtl_path = tmp_path / "rtl_modules.json"
    rtl_path.write_text(json.dumps(rtl_modules), encoding="utf-8")
    proc = _run_cli(["fingerprint", "--project-root", str(tmp_path),
                      "--phy-module", "phy_top", "--rtl-modules", str(rtl_path)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "COMPUTED"
    assert payload["phy_module_source_files"] == [str(phy_file)]


def test_cli_fingerprint_verb_module_not_found_exits_error(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    rtl_path = tmp_path / "rtl_modules.json"
    rtl_path.write_text(json.dumps(rtl_modules), encoding="utf-8")
    proc = _run_cli(["fingerprint", "--project-root", str(tmp_path),
                      "--phy-module", "no_such_module", "--rtl-modules", str(rtl_path)])
    assert proc.returncode == prs.EXIT_ERROR
    payload = json.loads(proc.stdout)
    assert payload["status"] == "NOT_AVAILABLE"


def test_cli_record_and_evaluate_verbs(tmp_path):
    phy_file, _, rtl_modules = _phy_module_rtl(tmp_path)
    rtl_path = tmp_path / "rtl_modules.json"
    rtl_path.write_text(json.dumps(rtl_modules), encoding="utf-8")
    ref_path = tmp_path / "decision_ref.json"
    ref_path.write_text(json.dumps({"kind": "phy_boundary_bind", "path": "phy_boundary.json"}),
                         encoding="utf-8")

    rec_proc = _run_cli(["record", "--project-root", str(tmp_path), "--phy-module", "phy_top",
                          "--rtl-modules", str(rtl_path), "--decision-ref", str(ref_path)])
    assert rec_proc.returncode == 0, rec_proc.stderr
    record = json.loads(rec_proc.stdout)
    decision_id = record["decision_id"]

    eval_proc_clean = _run_cli(["evaluate", "--project-root", str(tmp_path),
                                 "--decision-id", decision_id])
    assert eval_proc_clean.returncode == prs.EXIT_UP_TO_DATE

    phy_file.write_text("module phy_top; // real cli edit\nendmodule\n", encoding="utf-8")

    eval_proc_stale = _run_cli(["evaluate", "--project-root", str(tmp_path),
                                 "--decision-id", decision_id])
    assert eval_proc_stale.returncode == prs.EXIT_STALE
    payload = json.loads(eval_proc_stale.stdout)
    assert payload["evaluation"]["status"] == prs.STATUS_PHY_RTL_CHANGED


def test_cli_evaluate_unknown_decision_id_exits_error(tmp_path):
    proc = _run_cli(["evaluate", "--project-root", str(tmp_path), "--decision-id", "nope"])
    assert proc.returncode == prs.EXIT_ERROR
    payload = json.loads(proc.stdout)
    assert payload["error"] == "DECISION_RECORD_NOT_FOUND"


def test_cli_scan_verb_subprocess(tmp_path):
    _, _, rtl_modules = _phy_module_rtl(tmp_path)
    prs.record_phy_revision_decision(
        tmp_path, "phy_top", rtl_modules, {"kind": "phy_boundary_bind"})
    proc = _run_cli(["scan", "--project-root", str(tmp_path)])
    assert proc.returncode == prs.EXIT_UP_TO_DATE
    payload = json.loads(proc.stdout)
    assert payload["decision_count"] == 1
    assert payload["stale_count"] == 0
