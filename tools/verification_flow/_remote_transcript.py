#!/usr/bin/env python3
"""tools/verification_flow/_remote_transcript.py -- shared real-transcript
marker parsing for any gate that must verify a claim against an actual
captured tools/remote/remote_exec.py stdout transcript, never trust a
self-reported field alone.

Factored out of remote_execution_provenance_gate.py (2026-09-01,
trust-boundary-hardening design pass) so server_sync_identity_gate.py's new
SOURCE_ID mode can reuse the IDENTICAL REMOTE_HOST=/EXIT_CODE=/STATUS=
marker parsing against real md5sum transcripts, instead of re-deriving or
duplicating the same three regexes a second time. remote_execution_
provenance_gate.py was refactored to call this helper too -- its own
existing tests (dv_harness_tests/test_remote_execution_provenance_gate.py)
verify the refactor produced byte-identical FAIL/PASS JSON.

Not itself a registered hard gate (no argparse CLI, nothing in
.dv-harness/workflow/hard_gate_registry.json points at it) -- a plain
importable library module, like tools/remote/source_identity.py.
"""
from __future__ import annotations

import pathlib
import re

HOST_RE = re.compile(r"^REMOTE_HOST=(.*)$", re.MULTILINE)
EXIT_RE = re.compile(r"^EXIT_CODE=(-?\d+)$", re.MULTILINE)
STATUS_RE = re.compile(r"^STATUS=(.*)$", re.MULTILINE)


class TranscriptError(Exception):
    """Raised when a claimed transcript file doesn't exist or doesn't carry
    the real remote_exec.py marker shape. `reason` is a SCREAMING_SNAKE_CASE
    gate-failure reason code; `detail` is a dict of extra context the caller
    should fold into its own FAIL payload."""

    def __init__(self, reason: str, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def read_transcript(path_str) -> str:
    """Reads and returns the raw text of a real transcript file. Raises
    TranscriptError("TRANSCRIPT_FILE_NOT_FOUND") if `path_str` is not a real
    file on disk -- an inline JSON string can never stand in for a real
    captured transcript."""
    path = pathlib.Path(path_str or "")
    if not path.is_file():
        raise TranscriptError("TRANSCRIPT_FILE_NOT_FOUND", {"path": str(path)})
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_markers(content: str) -> dict:
    """Extracts the REMOTE_HOST=/EXIT_CODE=/STATUS= markers that
    tools/remote/remote_exec.py's own format_result() really stamps into its
    stdout. Raises TranscriptError("TRANSCRIPT_MISSING_MARKERS") if any
    marker is absent, or the host marker is present but blank. Returns
    {"host": str, "exit_code": int, "status": str}."""
    host_m = HOST_RE.search(content)
    exit_m = EXIT_RE.search(content)
    status_m = STATUS_RE.search(content)
    if not (host_m and host_m.group(1).strip() and exit_m and status_m):
        raise TranscriptError("TRANSCRIPT_MISSING_MARKERS")
    return {
        "host": host_m.group(1).strip(),
        "exit_code": int(exit_m.group(1)),
        "status": status_m.group(1).strip(),
    }


def read_and_parse_transcript(path_str) -> dict:
    """Convenience: read_transcript() + parse_markers() in one call."""
    return parse_markers(read_transcript(path_str))
