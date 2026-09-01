"""Tests for tools/verification_flow/signoff_bundle_completeness_gate.py's
2026-09-01 trust-boundary-hardening: bundle_hash is no longer a bare
self-reported string -- the gate now reads a real bundle_dir's real
manifest.json (written by dv_harness/signoff_export.py's real
collect_signoff_bundle()) and recomputes compute_bundle_hash() over it
itself, requiring an exact match."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dv_harness import signoff_export

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "signoff_bundle_completeness_gate.py"

REQUIRED_EVIDENCE = [
    {"class": c, "hash": "h"} for c in
    ["SPEC_TRACE", "BUILD", "TEST", "ASSERTION", "SCOREBOARD", "COVERAGE",
     "REGRESSION", "RCA_FIX", "ENV_FINGERPRINT"]
]


def _fresh_project_with_tools():
    """self_audit.py's ROOT_GATES/JSON_GATES resolve gate scripts as
    `project_root/tools/verification_flow/...`, so a fake project root needs
    its own copy of tools/ for collect_signoff_bundle()'s embedded
    run_self_audit() call to execute without raising (same fixture as
    dv_harness_tests/test_signoff_export.py)."""
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--bundle", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_missing_evidence_class_still_fails_as_before():
    rc, out = _run({"evidence": [], "bundle_hash": "x", "final_verdict": "PASS", "bundle_dir": "irrelevant"})
    assert rc == 2 and out["reason"] == "INCOMPLETE_SIGNOFF_BUNDLE"
    assert out["missing"] == sorted(c["class"] for c in REQUIRED_EVIDENCE)


def test_final_verdict_not_pass_still_fails_as_before():
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "x", "final_verdict": "BLOCKED"})
    assert rc == 3 and out["reason"] == "INVALID_FINAL_SIGNOFF_BUNDLE"


def test_missing_bundle_hash_still_fails_as_before():
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "final_verdict": "PASS"})
    assert rc == 3 and out["reason"] == "INVALID_FINAL_SIGNOFF_BUNDLE"


def test_missing_bundle_dir_fails():
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "x", "final_verdict": "PASS"})
    assert rc == 4 and out["reason"] == "MISSING_BUNDLE_DIR"


def test_bundle_dir_without_manifest_fails(tmp_path):
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "x", "final_verdict": "PASS",
                     "bundle_dir": str(tmp_path)})
    assert rc == 5 and out["reason"] == "BUNDLE_DIR_MANIFEST_NOT_FOUND"


def test_malformed_manifest_fails(tmp_path):
    (tmp_path / "manifest.json").write_text("not json", encoding="utf-8")
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "x", "final_verdict": "PASS",
                     "bundle_dir": str(tmp_path)})
    assert rc == 6 and out["reason"] == "BUNDLE_MANIFEST_MALFORMED"


def test_manifest_wrong_shape_fails(tmp_path):
    # Real key present but not the real {"manifest": [...], "bundle_hash": ...}
    # shape collect_signoff_bundle() actually writes.
    (tmp_path / "manifest.json").write_text(json.dumps([{"artifact": "x"}]), encoding="utf-8")
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "x", "final_verdict": "PASS",
                     "bundle_dir": str(tmp_path)})
    assert rc == 6 and out["reason"] == "BUNDLE_MANIFEST_MALFORMED"


def test_manifest_missing_self_audit_result_fails(tmp_path):
    manifest_list = [{"artifact": "vplan", "present": True, "bundled_path": "vplan"}]
    bundle_hash = signoff_export.compute_bundle_hash(manifest_list)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"manifest": manifest_list, "bundle_hash": bundle_hash}), encoding="utf-8")
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": bundle_hash, "final_verdict": "PASS",
                     "bundle_dir": str(tmp_path)})
    assert rc == 7 and out["reason"] == "BUNDLE_SELF_AUDIT_RESULT_MISSING"


def test_bundle_hash_mismatch_fails_even_with_valid_manifest(tmp_path):
    manifest_list = [{"artifact": "self_audit_result", "present": True, "bundled_path": "self_audit_result.json"}]
    real_hash = signoff_export.compute_bundle_hash(manifest_list)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"manifest": manifest_list, "bundle_hash": real_hash}), encoding="utf-8")
    rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "not-the-real-hash",
                     "final_verdict": "PASS", "bundle_dir": str(tmp_path)})
    assert rc == 8 and out["reason"] == "BUNDLE_HASH_MISMATCH"
    assert out["real"] == real_hash


def test_real_signoff_export_bundle_passes_end_to_end():
    """Full real path: a real collect_signoff_bundle() call writes a real
    manifest.json with a real bundle_hash; the gate independently recomputes
    the identical value and PASSes."""
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        assert result["status"] == "OK"

        rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": result["bundle_hash"],
                         "final_verdict": "PASS", "bundle_dir": str(out_dir)})
        assert rc == 0, out
        assert out["status"] == "PASS"
        assert out["bundle_hash"] == result["bundle_hash"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_real_signoff_export_bundle_detects_tampered_hash_claim():
    tmp = _fresh_project_with_tools()
    out_dir = tmp / "signoff_out"
    try:
        result = signoff_export.collect_signoff_bundle(tmp, out_dir)
        rc, out = _run({"evidence": REQUIRED_EVIDENCE, "bundle_hash": "deadbeef" * 8,
                         "final_verdict": "PASS", "bundle_dir": str(out_dir)})
        assert rc == 8 and out["reason"] == "BUNDLE_HASH_MISMATCH"
        assert out["real"] == result["bundle_hash"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
