"""Tests for tools/vplan/vplan_writer_validation_gate.py -- the gate wired
into dv_harness/gates.py's STAGE_GATES["VPLAN"] alongside spec_coverage_audit
(2026-09-01, vplan-doc-and-wiring-fix). Unlike spec_coverage_audit.py (which
checks a structurally different requirements[] JSON schema and never touches
dv_harness/vplan_writer), this gate calls the real
dv_harness.vplan_writer.build_evidence_context()/validate_items() against
real pattern-dir/dispatcher-file/task-declaration-source evidence on disk --
the same functions and evidence discipline `dv-harness vplan-export` itself
uses.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "vplan" / "vplan_writer_validation_gate.py"


def _make_fake_env(tmp: Path):
    pattern_dir = tmp / "uvm" / "patterns"
    pattern_dir.mkdir(parents=True)
    (pattern_dir / "USB2_bulkin.txt").write_text("bulkin pattern", encoding="utf-8")

    dispatcher_file = tmp / "dv_uvm_pattern_pool.svh"
    dispatcher_file.write_text(
        'case (pattern_name)\n  "USB2_bulkin": run_bulkin();\nendcase\n', encoding="utf-8",
    )

    tests_dir = tmp / "tb" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "usb_bulkin_test.sv").write_text(
        "task automatic usb_bulkin_test();\nendtask\n", encoding="utf-8",
    )
    return pattern_dir, dispatcher_file, tests_dir


def _base_item(**overrides):
    item = {
        "req_id": "USB2-BULK-001", "feature_area": "Bulk Transfers",
        "verification_item": "Bulk IN transfer completes",
        "pattern_name": "USB2_bulkin", "task_name": "usb_bulkin_test",
        "suite": "USB2_sanity", "covered_by": "covered",
        "description": "Directed bulk-in transfer test", "spec_section": "TBD-spec",
        "constraint_items": [], "random_or_directed": "directed", "mode_speed": "HS",
        "instance": "N/A", "checkers_active": ["sb_bulk_data_match"], "notes": "",
        "blocked_on": None, "blocked_reason": None,
    }
    item.update(overrides)
    return item


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--vplan-validation", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_help_smoke():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    assert r.stdout.strip()


def test_valid_items_against_real_evidence_pass():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item()],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
        assert out["item_count"] == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_unresolved_pattern_file_fails():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(pattern_name="USB2_nope")],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc != 0
        assert out["status"] == "FAIL"
        assert out["reason"] == "UNRESOLVED_PATTERN_FILE"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_pattern_not_in_dispatcher_fails():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        # A second pattern file exists on disk but was never added to the
        # dispatcher -- real-world case this rule exists to catch.
        (pattern_dir / "USB2_isoc.txt").write_text("isoc pattern", encoding="utf-8")
        rc, out = _run({
            "items": [_base_item(
                req_id="USB2-ISOC-001", pattern_name="USB2_isoc", task_name="usb_bulkin_test",
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc != 0
        assert out["status"] == "FAIL"
        assert out["reason"] == "PATTERN_NOT_IN_DISPATCHER"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_unknown_task_declaration_fails():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(task_name="usb_nonexistent_test")],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc != 0
        assert out["status"] == "FAIL"
        assert out["reason"] == "UNKNOWN_TASK_DECLARATION"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_required_top_level_field_fails_closed():
    rc, out = _run({"items": [_base_item()], "pattern_dir": "somewhere"})
    assert rc == 2
    assert out["status"] == "FAIL"
    assert out["reason"] == "MISSING_REQUIRED_FIELD"
    assert "dispatcher_file" in out["missing"]


def test_empty_items_fails_closed():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 2
        assert out["status"] == "FAIL"
        assert out["reason"] == "MISSING_REQUIRED_FIELD"
        assert "items" in out["missing"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _add_constraint_declarations(tests_dir: Path):
    """Adds a real SV file declaring `constraint c_bulk_len` under tests_dir,
    evidence for the 4th (constraint-items-exist-in-SV-source, 2026-09-01)
    validation rule."""
    (tests_dir / "constraints.sv").write_text(
        "class usb_bulkin_test extends uvm_test;\n"
        "  constraint c_bulk_len { len inside {[1:512]}; }\n"
        "endclass\n",
        encoding="utf-8",
    )


def test_constraint_items_exist_in_sv_source_passes_when_evidence_supplied():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        _add_constraint_declarations(tests_dir)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_bulk_len"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
            "constraint_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_constraint_not_in_sv_source_fails_when_evidence_supplied():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        _add_constraint_declarations(tests_dir)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_totally_made_up"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
            "constraint_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 3
        assert out["status"] == "FAIL"
        assert out["reason"] == "CONSTRAINT_NOT_IN_SV_SOURCE"
        assert out["detail"]["constraint_name"] == "c_totally_made_up"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_constraint_rule_skipped_when_no_constraint_evidence_in_payload():
    # No constraint_declaration_sources/known_constraint_names in the
    # payload at all -- an unresolvable-looking constraint name must still
    # PASS, since the 4th rule was never requested (optional, additive).
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_anything_goes"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_known_constraint_names_bypasses_scanning_in_payload():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_custom_only"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
            "known_constraint_names": ["c_custom_only"],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_wired_into_vplan_stage_gates():
    from dv_harness.gates import STAGE_GATES
    gate_ids = [g[0] for g in STAGE_GATES["VPLAN"]]
    assert "vplan_writer_validation_gate" in gate_ids
    assert "spec_coverage_audit" in gate_ids
