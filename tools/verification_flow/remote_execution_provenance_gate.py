#!/usr/bin/env python3
"""remote_execution_provenance_gate.py -- 2026-08-31 full-harness wiring
audit finding B4: BUILD/VERIFY stage compile/simulate claims were
self-attested JSON with no independent proof a real remote execution
occurred. This gate reads a real transcript file (captured stdout of a
real tools/remote/remote_exec.py invocation) and verifies it actually
contains that script's REMOTE_HOST=/EXIT_CODE=/STATUS= structured output
(see tools/remote/remote_exec.py's format_result()), and that the claimed
exit code matches what the transcript really shows -- an agent cannot
claim BUILD/VERIFY success while the real transcript shows a nonzero exit.

REFACTOR (2026-09-01, trust-boundary-hardening design pass): the
REMOTE_HOST=/EXIT_CODE=/STATUS= regex parsing this gate always did now
lives in the shared tools/verification_flow/_remote_transcript.py helper
(server_sync_identity_gate.py's new SOURCE_ID mode needs the exact same
parsing against real md5sum transcripts) -- this gate's own FAIL/PASS JSON
shapes and exit codes are unchanged, only the parsing is no longer
duplicated. See dv_harness_tests/test_remote_execution_provenance_gate.py.
"""
import argparse, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _remote_transcript import TranscriptError, read_transcript, parse_markers  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provenance", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.provenance).read_text())

    # Escape hatch (2026-08-31 final-review I4 finding), same convention as
    # fabric_topology_completeness_gate.py/protocol_structural_completeness_gate.py/
    # protocol_builder_registry_conformance_gate.py/system_level_* gates: a
    # reason is MANDATORY, never a bare boolean opt-out -- an agent must
    # still justify why no real remote execution transcript applies (e.g. a
    # BUILD/VERIFY response that made no remote_exec.py invocation at all).
    if d.get("provenance_applicable") is False:
        reason = d.get("provenance_not_applicable_reason")
        if not reason:
            print(json.dumps({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 5
        print(json.dumps({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}))
        return 0

    try:
        content = read_transcript(d.get("transcript_path", ""))
        markers = parse_markers(content)
    except TranscriptError as exc:
        payload = {"status": "FAIL", "reason": exc.reason}
        payload.update(exc.detail)
        print(json.dumps(payload))
        return 2 if exc.reason == "TRANSCRIPT_FILE_NOT_FOUND" else 3

    real_exit_code = markers["exit_code"]
    claimed_exit_code = d.get("claimed_exit_code")
    if real_exit_code != claimed_exit_code:
        print(json.dumps({"status": "FAIL", "reason": "EXIT_CODE_MISMATCH",
                           "claimed": claimed_exit_code, "real": real_exit_code}))
        return 4

    print(json.dumps({"status": "PASS", "remote_host": markers["host"],
                       "exit_code": real_exit_code}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
