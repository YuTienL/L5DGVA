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
"""
import argparse, json, pathlib, re, sys

_HOST_RE = re.compile(r"^REMOTE_HOST=(.*)$", re.MULTILINE)
_EXIT_RE = re.compile(r"^EXIT_CODE=(-?\d+)$", re.MULTILINE)
_STATUS_RE = re.compile(r"^STATUS=(.*)$", re.MULTILINE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provenance", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.provenance).read_text())

    transcript_path = pathlib.Path(d.get("transcript_path", ""))
    if not transcript_path.is_file():
        print(json.dumps({"status": "FAIL", "reason": "TRANSCRIPT_FILE_NOT_FOUND",
                           "path": str(transcript_path)}))
        return 2

    content = transcript_path.read_text(encoding="utf-8", errors="ignore")
    host_m = _HOST_RE.search(content)
    exit_m = _EXIT_RE.search(content)
    status_m = _STATUS_RE.search(content)
    if not (host_m and host_m.group(1).strip() and exit_m and status_m):
        print(json.dumps({"status": "FAIL", "reason": "TRANSCRIPT_MISSING_MARKERS"}))
        return 3

    real_exit_code = int(exit_m.group(1))
    claimed_exit_code = d.get("claimed_exit_code")
    if real_exit_code != claimed_exit_code:
        print(json.dumps({"status": "FAIL", "reason": "EXIT_CODE_MISMATCH",
                           "claimed": claimed_exit_code, "real": real_exit_code}))
        return 4

    print(json.dumps({"status": "PASS", "remote_host": host_m.group(1).strip(),
                       "exit_code": real_exit_code}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
