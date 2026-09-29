"""Tests for tools/verification_flow/server_sync_identity_gate.py.

GIT_SHA mode is the ORIGINAL behavior (unaltered) -- already covered by
dv_harness_tests/test_engine_gates_and_routing.py's
test_server_sync_requires_head_and_submodule_sha_identity via
evaluate_stage_evidence(). This file drives the script directly (same
subprocess convention as test_remote_execution_provenance_gate.py) and adds
coverage for the new SOURCE_ID mode -- real recomputation via
tools/remote/source_identity.py against two real md5sum transcripts, never
trusting a self-reported match/source_id alone.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "server_sync_identity_gate.py"

MD5_A = "d41d8cd98f00b204e9800998ecf8427e"
MD5_B = "5eb63bbbe01eeed093cb22bb8f5acdc3"
MD5_C = "900150983cd24fb0d6963f7d28e17f72"


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--sync", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# --- GIT_SHA mode: default/explicit identity_method is byte-identical to
# the pre-existing behavior. ------------------------------------------------

def test_git_sha_mode_is_default_and_unaffected_by_new_field():
    rc, out = _run({"expected_sha": "abc123", "server_head_sha": "abc123", "submodules": []})
    assert rc == 0 and out == {"status": "PASS", "head_sha": "abc123", "submodules": 0}


def test_git_sha_mode_explicit_matches_default():
    rc, out = _run({"identity_method": "git_sha", "expected_sha": "abc123",
                     "server_head_sha": "def456", "submodules": []})
    assert rc == 3 and out["reason"] == "SERVER_HEAD_SHA_MISMATCH"


def test_unknown_identity_method_fails_explicitly():
    rc, out = _run({"identity_method": "bogus"})
    assert rc == 11 and out["status"] == "FAIL" and out["reason"] == "UNKNOWN_IDENTITY_METHOD"


# --- SOURCE_ID mode ----------------------------------------------------------

def test_source_id_mode_passes_on_matching_real_transcripts(tmp_path):
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n{MD5_B}  dir/b.txt\n")
    remote = _write(tmp_path, "remote.txt",
                     f"REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n{MD5_A}  a.txt\n{MD5_B}  dir/b.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote})
    assert rc == 0 and out["status"] == "PASS"
    assert "source_id" in out and len(out["source_id"]) == 64  # real sha256 hex digest
    assert "claim_flags" not in out


def test_source_id_mode_fails_on_real_content_mismatch(tmp_path):
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n")
    remote = _write(tmp_path, "remote.txt",
                     f"REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n{MD5_C}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote})
    assert rc == 10 and out["status"] == "FAIL" and out["reason"] == "SOURCE_ID_MISMATCH"
    assert out["diff"]["different"] == ["a.txt"]


def test_source_id_mode_fails_when_local_transcript_missing(tmp_path):
    remote = _write(tmp_path, "remote.txt", f"REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n{MD5_A}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": str(tmp_path / "does_not_exist.txt"),
                     "remote_md5sum_transcript_path": remote})
    assert rc == 6 and out["reason"] == "LOCAL_TRANSCRIPT_FILE_NOT_FOUND"


def test_source_id_mode_fails_when_remote_transcript_missing(tmp_path):
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": str(tmp_path / "nope.txt")})
    assert rc == 7 and out["reason"] == "REMOTE_TRANSCRIPT_FILE_NOT_FOUND"


def test_source_id_mode_fails_when_remote_transcript_malformed(tmp_path):
    # A real file exists but carries none of remote_exec.py's own
    # REMOTE_HOST=/EXIT_CODE=/STATUS= markers -- not a real remote_exec.py
    # transcript at all.
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n")
    remote = _write(tmp_path, "remote.txt", f"{MD5_A}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote})
    assert rc == 7 and out["reason"] == "REMOTE_TRANSCRIPT_MISSING_MARKERS"


def test_source_id_mode_fails_when_remote_md5sum_command_itself_failed(tmp_path):
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n")
    remote = _write(tmp_path, "remote.txt",
                     f"REMOTE_HOST=host-b\nEXIT_CODE=1\nSTATUS=FAIL\nmd5sum: a.txt: No such file or directory\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote})
    assert rc == 8 and out["reason"] == "REMOTE_MD5SUM_NONZERO_EXIT" and out["exit_code"] == 1


def test_source_id_mode_fails_when_either_manifest_is_empty(tmp_path):
    local = _write(tmp_path, "local.txt", "")
    remote = _write(tmp_path, "remote.txt", f"REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n{MD5_A}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote})
    assert rc == 9 and out["reason"] == "MD5SUM_MANIFEST_EMPTY"


def test_source_id_mode_pass_decided_by_recomputation_not_self_reported_claim(tmp_path):
    # Defense-in-depth: an agent claiming match=false while the real
    # transcripts actually agree still PASSes (recomputation wins), but the
    # disagreement is flagged for visibility.
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n")
    remote = _write(tmp_path, "remote.txt", f"REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n{MD5_A}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote,
                     "match": False})
    assert rc == 0 and out["status"] == "PASS"
    assert out["claim_flags"] == ["SOURCE_ID_CLAIM_MISMATCH"]


def test_source_id_mode_fail_not_masked_by_self_reported_claim(tmp_path):
    # The mirror case: an agent claiming match=true while the real
    # transcripts actually disagree still FAILs (recomputation wins).
    local = _write(tmp_path, "local.txt", f"{MD5_A}  a.txt\n")
    remote = _write(tmp_path, "remote.txt", f"REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\n{MD5_C}  a.txt\n")
    rc, out = _run({"identity_method": "source_id",
                     "local_md5sum_transcript_path": local,
                     "remote_md5sum_transcript_path": remote,
                     "match": True})
    assert rc == 10 and out["status"] == "FAIL" and out["reason"] == "SOURCE_ID_MISMATCH"
    assert out["claim_flags"] == ["SOURCE_ID_CLAIM_MISMATCH"]
