"""Tests for tools/verification_flow/_remote_transcript.py -- the shared
REMOTE_HOST=/EXIT_CODE=/STATUS= transcript-marker parser factored out of
remote_execution_provenance_gate.py (2026-09-01, trust-boundary-hardening
design pass) so server_sync_identity_gate.py's SOURCE_ID mode can reuse it
against real md5sum transcripts."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "verification_flow"))

from _remote_transcript import TranscriptError, read_transcript, parse_markers, read_and_parse_transcript


def test_read_transcript_raises_on_missing_file(tmp_path):
    with pytest.raises(TranscriptError) as exc:
        read_transcript(str(tmp_path / "does_not_exist.txt"))
    assert exc.value.reason == "TRANSCRIPT_FILE_NOT_FOUND"
    assert exc.value.detail["path"] == str(tmp_path / "does_not_exist.txt")


def test_read_transcript_reads_real_file(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("hello\n", encoding="utf-8")
    assert read_transcript(str(p)) == "hello\n"


def test_parse_markers_extracts_real_shape():
    content = "REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nbuild ok\n"
    assert parse_markers(content) == {"host": "host-b", "exit_code": 0, "status": "PASS"}


def test_parse_markers_negative_exit_code():
    content = "REMOTE_HOST=host-b\nEXIT_CODE=-1\nSTATUS=FAIL\n"
    assert parse_markers(content)["exit_code"] == -1


def test_parse_markers_raises_when_markers_absent():
    with pytest.raises(TranscriptError) as exc:
        parse_markers("some unrelated output\n")
    assert exc.value.reason == "TRANSCRIPT_MISSING_MARKERS"


def test_parse_markers_raises_when_host_blank():
    with pytest.raises(TranscriptError) as exc:
        parse_markers("REMOTE_HOST=\nEXIT_CODE=0\nSTATUS=PASS\n")
    assert exc.value.reason == "TRANSCRIPT_MISSING_MARKERS"


def test_read_and_parse_transcript_convenience(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("REMOTE_HOST=host-a\nEXIT_CODE=2\nSTATUS=FAIL\n", encoding="utf-8")
    assert read_and_parse_transcript(str(p)) == {"host": "host-a", "exit_code": 2, "status": "FAIL"}
