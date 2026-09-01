#!/usr/bin/env python3
"""server_sync_identity_gate.py -- verifies PC-vs-Linux-server source
identity before BUILD proceeds against server-side source.

Two modes, selected by evidence field "identity_method":
  - "git_sha" (default, unset == this value): the ORIGINAL behavior, byte-
    for-byte unchanged -- expected_sha/server_head_sha (+ per-submodule
    expected_sha/server_sha) must agree as self-reported strings. Real for
    projects with a git remote between PC and the Linux workdir.
  - "source_id": HARDENING (2026-09-01, trust-boundary-hardening design
    pass) -- CLAUDE.md's "Remote Linux Execution" section mandates a
    git-free SOURCE_ID (md5sum-based) fallback "where [a git remote] does
    not [exist] -- never skipped outright", but this gate previously had no
    branch for it at all. This mode reads two REAL files (never inline JSON
    text): local_md5sum_transcript_path (checked only for real-file
    existence -- no repo-wide transport-marker convention exists for
    local-side capture, same residual limitation this project already
    accepts for remote_execution_provenance_gate.py's own transcript_path)
    and remote_md5sum_transcript_path (must additionally carry the real
    REMOTE_HOST=/EXIT_CODE=/STATUS= marker shape a real
    `python tools/remote/remote_exec.py "md5sum <files>"` invocation stamps
    into its stdout -- checked via the shared _remote_transcript.py helper,
    the same one remote_execution_provenance_gate.py uses). Both are parsed
    into {path: md5} manifests via the real, tested
    tools/remote/source_identity.py and fed to its real
    compute_source_identity() -- the PASS/FAIL verdict is driven ONLY by
    that real recomputation, never by a self-reported match/source_id
    field (those are cross-checked as defense-in-depth only, see
    SOURCE_ID_CLAIM_MISMATCH below).

This gate stays local -- it never itself reaches the remote server (CLAUDE.md:
remote_relay.py, the only credentialed leg, must never be invoked from a
Claude Code tool call). The AGENT (already sanctioned to call
tools/remote/remote_exec.py) performs the real remote `md5sum` and attaches
its real captured transcript; this gate only re-derives the hash math from
that transcript's real content.
"""
import argparse, json, pathlib, sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
# tools/remote/source_identity.py's own sys.path convention -- see
# dv_harness_tests/test_source_identity.py.
sys.path.insert(0, str(_ROOT / "tools" / "remote"))
from source_identity import parse_md5sum_output, compute_source_identity  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _remote_transcript import TranscriptError, read_transcript, parse_markers  # noqa: E402


def _run_source_id_mode(d: dict):
    """Returns (exit_code, payload_dict). PASS/FAIL is decided only by the
    real compute_source_identity() recomputation over two real transcripts;
    a self-reported "match"/"source_id" is cross-checked only as
    defense-in-depth (SOURCE_ID_CLAIM_MISMATCH), never trusted on its own."""
    local_path = d.get("local_md5sum_transcript_path")
    if not local_path or not pathlib.Path(local_path).is_file():
        return 6, {"status": "FAIL", "reason": "LOCAL_TRANSCRIPT_FILE_NOT_FOUND",
                    "path": str(local_path)}

    remote_path = d.get("remote_md5sum_transcript_path")
    try:
        remote_content = read_transcript(remote_path)
        markers = parse_markers(remote_content)
    except TranscriptError as exc:
        payload = {"status": "FAIL", "reason": "REMOTE_" + exc.reason}
        payload.update(exc.detail)
        return 7, payload

    if markers["exit_code"] != 0:
        return 8, {"status": "FAIL", "reason": "REMOTE_MD5SUM_NONZERO_EXIT",
                    "exit_code": markers["exit_code"]}

    local_content = pathlib.Path(local_path).read_text(encoding="utf-8", errors="ignore")
    local_manifest = parse_md5sum_output(local_content)
    remote_manifest = parse_md5sum_output(remote_content)
    if not local_manifest or not remote_manifest:
        return 9, {"status": "FAIL", "reason": "MD5SUM_MANIFEST_EMPTY",
                    "local_file_count": len(local_manifest), "remote_file_count": len(remote_manifest)}

    result = compute_source_identity(local_manifest, remote_manifest)

    claim_flags = []
    claimed_match = d.get("match")
    if claimed_match is not None and bool(claimed_match) != result["match"]:
        claim_flags.append("SOURCE_ID_CLAIM_MISMATCH")
    claimed_source_id = d.get("source_id")
    if claimed_source_id is not None and claimed_source_id != result["local_id"]:
        claim_flags.append("SOURCE_ID_CLAIM_MISMATCH")

    if not result["match"]:
        payload = {"status": "FAIL", "reason": "SOURCE_ID_MISMATCH", "diff": result["diff"],
                   "local_id": result["local_id"], "remote_id": result["remote_id"]}
        if claim_flags:
            payload["claim_flags"] = sorted(set(claim_flags))
        return 10, payload

    payload = {"status": "PASS", "source_id": result["local_id"],
               "local_file_count": len(local_manifest)}
    if claim_flags:
        payload["claim_flags"] = sorted(set(claim_flags))
    return 0, payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.sync).read_text())

    identity_method = d.get("identity_method", "git_sha")
    if identity_method == "source_id":
        code, payload = _run_source_id_mode(d)
        print(json.dumps(payload))
        return code
    if identity_method != "git_sha":
        print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_IDENTITY_METHOD",
                           "identity_method": identity_method}))
        return 11

    # ---- "git_sha" mode: ORIGINAL behavior, byte-for-byte unchanged. ----
    expected = d.get("expected_sha")
    actual = d.get("server_head_sha")
    if not expected or not actual:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_SHA"})); return 2
    if expected != actual:
        print(json.dumps({"status": "FAIL", "reason": "SERVER_HEAD_SHA_MISMATCH",
                           "expected_sha": expected, "server_head_sha": actual})); return 3

    for sm in d.get("submodules", []):
        name = sm.get("name")
        if not sm.get("expected_sha") or not sm.get("server_sha"):
            print(json.dumps({"status": "FAIL", "reason": "SUBMODULE_MISSING_SHA", "submodule": name})); return 4
        if sm.get("expected_sha") != sm.get("server_sha"):
            print(json.dumps({"status": "FAIL", "reason": "SUBMODULE_SHA_MISMATCH", "submodule": name,
                               "expected_sha": sm.get("expected_sha"), "server_sha": sm.get("server_sha")})); return 5

    print(json.dumps({"status": "PASS", "head_sha": actual, "submodules": len(d.get("submodules", []))}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
