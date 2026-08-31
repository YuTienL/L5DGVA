import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "remote_execution_provenance_gate.py"


def _write_transcript(tmp_path, text):
    p = tmp_path / "transcript.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--provenance", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_real_shaped_pass_transcript_passes(tmp_path):
    path = _write_transcript(tmp_path, "REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nbuild ok\n")
    rc, out = _run({"transcript_path": path, "claimed_exit_code": 0})
    assert rc == 0 and out["status"] == "PASS"


def test_exit_code_mismatch_fails(tmp_path):
    path = _write_transcript(tmp_path, "REMOTE_HOST=host-b\nEXIT_CODE=1\nSTATUS=FAIL\nerror\n")
    rc, out = _run({"transcript_path": path, "claimed_exit_code": 0})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "EXIT_CODE_MISMATCH"


def test_missing_transcript_file_fails(tmp_path):
    rc, out = _run({"transcript_path": str(tmp_path / "does_not_exist.txt"), "claimed_exit_code": 0})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "TRANSCRIPT_FILE_NOT_FOUND"


def test_missing_marker_line_fails(tmp_path):
    path = _write_transcript(tmp_path, "some unrelated output\n")
    rc, out = _run({"transcript_path": path, "claimed_exit_code": 0})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "TRANSCRIPT_MISSING_MARKERS"
