"""Tests for dv_harness/signoff_export.py -- closes the "一鍵最終 Signoff 匯出"
poster-compliance gap (bundle vPlan/blackboard signoff state/telemetry/
pattern registry + a fresh self-audit result into one out dir with an
honest manifest of what was actually present)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dv_harness import signoff_export

ROOT = Path(__file__).resolve().parents[1]


def _fresh_project_with_tools():
    """self_audit.py's ROOT_GATES/JSON_GATES resolve gate scripts as
    `project_root/tools/verification_flow/...` (see dv_harness/self_audit.py
    and dv_harness_tests/test_cli_remote_control.py's identical fixture), so
    a fake project root needs its own copy of tools/ for run_self_audit() to
    execute without raising."""
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_partial_project():
    """SOME (not all) of the 8 candidate artifacts present:
    - blackboard/signoff_state.json, blackboard/findings.json: present
    - blackboard/regression_state.json, blackboard/requirements.json: absent
    - vplan/: present (one real schema-shaped file)
    - telemetry/: present (one real stage profile file)
    - pattern_registry/: absent (no such convention exists in this project)
    """
    tmp = _fresh_project_with_tools()
    _write_json(tmp / ".dv-harness" / "blackboard" / "signoff_state.json",
                {"topic": "signoff_state", "value": {"status": "PENDING"}})
    _write_json(tmp / ".dv-harness" / "blackboard" / "findings.json",
                {"topic": "findings", "value": []})
    _write_json(tmp / ".dv-harness" / "vplan" / "vplan.schema.json",
                {"vplan_id": "string", "requirements": []})
    _write_json(tmp / ".dv-harness" / "telemetry" / "workflow_profile.json",
                {"stage_count": 0})
    return tmp


def test_bundles_only_present_artifacts_and_manifest_marks_rest_absent():
    tmp = _make_partial_project()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)

        assert result["status"] == "OK"
        assert result["out_dir"] == str(out_dir.resolve())

        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        assert len(by_artifact) == 8

        present_expected = {
            "blackboard/signoff_state.json", "blackboard/findings.json",
            "vplan", "telemetry", "self_audit_result",
        }
        absent_expected = {
            "blackboard/regression_state.json", "blackboard/requirements.json",
            "pattern_registry",
        }
        for artifact in present_expected:
            assert by_artifact[artifact]["present"] is True, artifact
            assert by_artifact[artifact]["bundled_path"] is not None
            assert (out_dir / by_artifact[artifact]["bundled_path"]).exists()
        for artifact in absent_expected:
            assert by_artifact[artifact]["present"] is False, artifact
            assert by_artifact[artifact]["bundled_path"] is None

        assert result["bundled_count"] == len(present_expected)
        assert result["missing_count"] == len(absent_expected)

        # manifest.json itself is written into out_dir and matches the return value.
        manifest_on_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_on_disk == result["manifest"]

        # self-audit result is always included, and is real self_audit output
        # (has the same summary/gates shape run_self_audit produces), not a
        # fabricated placeholder.
        audit_path = out_dir / by_artifact["self_audit_result"]["bundled_path"]
        audit_json = json.loads(audit_path.read_text(encoding="utf-8"))
        assert "summary" in audit_json and "gates" in audit_json
        assert audit_json["summary"]["total"] == len(audit_json["gates"])

        # bundled blackboard file content actually matches the source.
        bundled_signoff = json.loads(
            (out_dir / by_artifact["blackboard/signoff_state.json"]["bundled_path"]).read_text(encoding="utf-8"))
        assert bundled_signoff["value"]["status"] == "PENDING"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_exception_when_nothing_at_all_is_present():
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        assert result["status"] == "OK"
        by_artifact = {m["artifact"]: m for m in result["manifest"]}
        # only self_audit_result is always generated fresh -- everything else
        # is a real absent artifact under this bare project root.
        assert result["bundled_count"] == 1
        assert result["missing_count"] == 7
        assert by_artifact["self_audit_result"]["present"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_cli(tmp, *args):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "signoff-export", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60, encoding="utf-8",
    )
    return r


def test_cli_signoff_export_subcommand():
    tmp = _make_partial_project()
    out_dir = tmp / "cli_signoff_out"
    try:
        r = _run_cli(tmp, "--out", str(out_dir))
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
        assert out["status"] == "OK"
        assert out["bundled_count"] == 5
        assert out["missing_count"] == 3
        assert (out_dir / "manifest.json").exists()
        assert (out_dir / "self_audit_result.json").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
