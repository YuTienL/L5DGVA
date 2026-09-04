"""Tests for dv_harness/memory_doctor.py -- Phase 21 (Health Check /
`memory doctor`) of the Obsidian+Git/Markdown Hybrid Engineering Memory
spec, Workstream 2 of 4.

Runs against real vault directories (created via memory_vault.bootstrap_vault()/
FileSystemMarkdownAdapter, the same code path `dv-harness memory doctor` uses
in production) -- no mocking of the checks themselves.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import memory_vault as mv
from dv_harness import memory_doctor as doctor


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    def _on_rm_error(func, p, exc_info):
        import os as _os, stat as _stat
        _os.chmod(p, _stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_rm_error, ignore_errors=True)


def _vault_path(tmp: Path) -> Path:
    return tmp / ".dv-harness" / "vault"


def _provider(tmp: Path, git_enabled=False):
    return mv.FileSystemMarkdownAdapter(_vault_path(tmp), git_enabled=git_enabled)


# --- run_doctor(): empty vault ----------------------------------------------

def test_doctor_on_empty_bootstrapped_vault_is_partial_not_blocked():
    # An honest empty vault: writable, no notes, no defects -- the ONLY
    # reason it is not READY is Obsidian's own permanent PARTIAL status
    # (see memory_vault.detect_obsidian_cli()'s docstring) -- never BLOCKED
    # merely for being empty/new.
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        result = doctor.run_doctor(tmp, cfg={})
        assert result["overall"] in ("READY", "PARTIAL")
        assert result["overall"] != "BLOCKED"
        assert result["note_count"] == 0
        assert result["checks"]["vault_writable"]["status"] == "READY"
        assert result["checks"]["duplicate_ids"]["status"] == "READY"
        assert result["checks"]["invalid_yaml"]["status"] == "READY"
        assert result["checks"]["secrets"]["status"] == "READY"
    finally:
        _rmtree(tmp)


def test_doctor_git_check_reports_disabled_not_partial_when_git_enabled_false():
    tmp = _tmp()
    try:
        result = doctor.run_doctor(tmp, cfg={})  # memory.git_enabled defaults False
        assert result["checks"]["git"]["status"] == "DISABLED"
        assert "git" not in result["partial_reasons"]
        assert "git" not in result["blocked_reasons"]
    finally:
        _rmtree(tmp)


def test_doctor_obsidian_check_is_real_not_hardcoded():
    tmp = _tmp()
    try:
        result = doctor.run_doctor(tmp, cfg={})
        obs = result["checks"]["obsidian_cli"]
        assert obs["status"] == "PARTIAL"
        assert isinstance(obs["installed"], bool)
        assert "obsidian_cli" in result["partial_reasons"]
    finally:
        _rmtree(tmp)


# --- run_doctor(): schema / missing metadata --------------------------------

def test_doctor_flags_a_schema_partial_note_without_blocking():
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        # No "protocol" -> missing required field -> schema_status: PARTIAL,
        # matching engine.py's real _promote_verified_fix_knowledge() gap
        # (Workstream 1's own report) -- this is a real, expected, non-fatal
        # condition, not a defect that should ever BLOCK the whole vault.
        result = fs.create({"memory_level": "engineering", "status": "ACTIVE", "confidence": "LOW"})
        assert result["validation"]["schema_status"] == "PARTIAL"

        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] != "BLOCKED"
        assert "schema" in report["partial_reasons"]
        assert report["checks"]["schema"]["partial"][0]["note_id"] == result["note_id"]
        assert "protocol" in report["checks"]["schema"]["partial"][0]["missing_required"]
    finally:
        _rmtree(tmp)


def test_doctor_flags_a_note_whose_body_section_was_hand_deleted():
    """The read-side half of Phase 7. The adapter builds the 11-section body
    by construction, so this state is only reachable by an edit made outside
    it (Obsidian GUI, another tool) -- simulated here by editing the real
    on-disk file the real adapter just wrote."""
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        created = fs.create({"memory_level": "engineering", "protocol": "USB",
                             "status": "ACTIVE", "confidence": "HIGH"},
                            sections={"Fix": "raise the branch_b0 fifo threshold"})
        assert created["validation"]["schema_status"] == "COMPLETE"

        note_path = _vault_path(tmp) / created["path"]
        text = note_path.read_text(encoding="utf-8")
        assert "## Fix" in text
        note_path.write_text(
            "\n".join(l for l in text.splitlines()
                      if l not in ("## Fix", "raise the branch_b0 fifo threshold")),
            encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] != "BLOCKED", "a reshaped body is repairable, never fatal"
        assert "schema" in report["partial_reasons"]
        entry = report["checks"]["schema"]["partial"][0]
        assert entry["note_id"] == created["note_id"]
        assert entry["missing_sections"] == ["Fix"]
        assert entry["missing_required"] == [], "frontmatter itself is still complete"
    finally:
        _rmtree(tmp)


def test_doctor_reports_missing_recommended_fields_without_marking_the_note_partial():
    """A note carrying every GATING field but none of the spec's enrichment
    fields is READY, and the absent enrichment fields are still named."""
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        created = fs.create({"memory_level": "engineering", "protocol": "USB",
                             "status": "ACTIVE", "confidence": "HIGH"})
        schema = doctor.run_validate(tmp, cfg={})["checks"]["schema"]

        assert schema["status"] == "READY"
        assert schema["partial"] == []
        assert schema["complete_count"] == 1

        reported = schema["notes_missing_recommended"]
        assert [e["note_id"] for e in reported] == [created["note_id"]]
        assert set(reported[0]["missing_recommended"]) == set(mv.MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS)
    finally:
        _rmtree(tmp)


# --- run_doctor(): duplicate IDs (BLOCKED) ----------------------------------

def test_doctor_blocks_on_duplicate_note_ids():
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        note_text = mv.render_note_markdown({
            "id": "NOTE-DUPE", "memory_level": "engineering", "protocol": "USB",
            "status": "ACTIVE", "confidence": "HIGH", "created": "2026-01-01T00:00:00+00:00",
            "updated": "2026-01-01T00:00:00+00:00",
        })
        eng_dir = vault_path / "06_Agent_Memory" / "Engineering"
        (eng_dir / "NOTE-DUPE.md").write_text(note_text, encoding="utf-8")
        (eng_dir / "NOTE-DUPE-copy.md").write_text(note_text, encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] == "BLOCKED"
        assert "duplicate_ids" in report["blocked_reasons"]
        assert "NOTE-DUPE" in report["checks"]["duplicate_ids"]["duplicates"]
    finally:
        _rmtree(tmp)


# --- run_doctor(): invalid YAML (BLOCKED) -----------------------------------

def test_doctor_blocks_on_invalid_yaml_frontmatter():
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        eng_dir = vault_path / "06_Agent_Memory" / "Engineering"
        # No closing "---" delimiter -> parse_note_markdown() returns ({}, text).
        (eng_dir / "BROKEN.md").write_text("---\nid: BROKEN\nprotocol: USB\n\n## Symptom\nnothing", encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] == "BLOCKED"
        assert "invalid_yaml" in report["blocked_reasons"]
        assert any("BROKEN.md" in p for p in report["checks"]["invalid_yaml"]["invalid_notes"])
    finally:
        _rmtree(tmp)


def test_doctor_does_not_flag_ordinary_non_schema_markdown_outside_memory_tier():
    # 00_Inbox etc. are general Obsidian-vault space, not Phase-7 Memory
    # Notes -- a plain human-authored README there must never trip
    # invalid_yaml/schema checks.
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        (vault_path / "00_Inbox" / "README.md").write_text("# just a note\nno frontmatter here", encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] != "BLOCKED"
        assert report["note_count"] == 0
    finally:
        _rmtree(tmp)


# --- run_doctor(): broken wiki-links -----------------------------------------

def test_doctor_flags_broken_wiki_links_as_partial():
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        result = fs.create(
            {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"},
            sections={"Related Knowledge": "- [[NOTE-DOES-NOT-EXIST-ANYWHERE]]"},
        )
        assert result["ok"]
        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] != "BLOCKED"
        assert "broken_links" in report["partial_reasons"]
        assert report["checks"]["broken_links"]["notes_with_broken_links"][0]["note_id"] == result["note_id"]
    finally:
        _rmtree(tmp)


def test_doctor_does_not_flag_a_real_wiki_link_between_two_notes():
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        a = fs.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"})
        b = fs.create(
            {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"},
            sections={"Related Knowledge": f"- [[{a['note_id']}]]"},
        )
        report = doctor.run_doctor(tmp, cfg={})
        assert "broken_links" not in report["partial_reasons"]
    finally:
        _rmtree(tmp)


# --- run_doctor(): secret leakage (BLOCKED) ---------------------------------

def test_doctor_blocks_on_a_secret_left_in_a_hand_edited_note():
    # Simulates a note that predates the redaction feature, or was hand-
    # edited directly on disk -- memory_vault.py's create()/update() would
    # never introduce this themselves (see test_memory_security.py), but
    # doctor must still catch it on the real files.
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        eng_dir = vault_path / "06_Agent_Memory" / "Engineering"
        text = mv.render_note_markdown(
            {"id": "NOTE-LEAK", "memory_level": "engineering", "protocol": "USB", "status": "ACTIVE",
             "confidence": "HIGH", "created": "2026-01-01T00:00:00+00:00", "updated": "2026-01-01T00:00:00+00:00"},
            sections={"Context": "connect via VCPW=realhuntersecret to vchost-a"},
        )
        (eng_dir / "NOTE-LEAK.md").write_text(text, encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] == "BLOCKED"
        assert "secrets" in report["blocked_reasons"]
        assert report["checks"]["secrets"]["notes_with_secrets"][0]["path"].endswith("NOTE-LEAK.md")
    finally:
        _rmtree(tmp)


def test_doctor_does_not_block_on_a_properly_redacted_note():
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        result = fs.create(
            {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH",
             "failure": "leak attempt VCPW=realhuntersecret here"},
        )
        assert result["ok"]
        assert result.get("secrets_redacted")
        report = doctor.run_doctor(tmp, cfg={})
        assert report["overall"] != "BLOCKED"
        assert report["checks"]["secrets"]["notes_with_secrets"] == []
    finally:
        _rmtree(tmp)


# --- run_doctor(): large / forbidden-artifact files -------------------------

def test_doctor_flags_a_forbidden_fsdb_extension_file_anywhere_in_the_vault():
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        bad = vault_path / "04_Debug" / "Known_Issues" / "waveform.fsdb"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"not a real fsdb but has the extension")

        report = doctor.run_doctor(tmp, cfg={})
        assert "large_files" in report["partial_reasons"]
        assert any(f["path"].endswith("waveform.fsdb") for f in report["checks"]["large_files"]["flagged"])
    finally:
        _rmtree(tmp)


def test_doctor_flags_a_huge_non_fsdb_file_by_size_threshold():
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        big = vault_path / "00_Inbox" / "dump.bin"
        big.write_bytes(b"0" * (doctor.LARGE_FILE_SIZE_BYTES + 1))

        report = doctor.run_doctor(tmp, cfg={})
        assert "large_files" in report["partial_reasons"]
        assert any(f["path"].endswith("dump.bin") for f in report["checks"]["large_files"]["flagged"])
    finally:
        _rmtree(tmp)


def test_doctor_does_not_flag_small_ordinary_files():
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        small = vault_path / "00_Inbox" / "small.txt"
        small.write_text("just some notes", encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={})
        assert "large_files" not in report["partial_reasons"]
    finally:
        _rmtree(tmp)


# --- run_doctor(): git status when ENABLED ----------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git not present on this machine")
def test_doctor_reports_uncommitted_changes_when_git_enabled():
    tmp = _tmp()
    try:
        fs = _provider(tmp, git_enabled=True)
        # A create() call auto-commits (see memory_vault._maybe_git_commit) --
        # simulate an UNCOMMITTED change by writing a file directly afterward.
        fs.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"})
        inbox = _vault_path(tmp) / "00_Inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "uncommitted.md").write_text("uncommitted", encoding="utf-8")

        report = doctor.run_doctor(tmp, cfg={"memory": {"git_enabled": True}})
        assert report["checks"]["git"]["status"] == "PARTIAL"
        assert report["checks"]["git"]["uncommitted_changes"] >= 1
        assert "git" in report["partial_reasons"]
    finally:
        _rmtree(tmp)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not present on this machine")
def test_doctor_reports_git_ready_when_everything_committed():
    tmp = _tmp()
    try:
        fs = _provider(tmp, git_enabled=True)
        fs.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"})
        report = doctor.run_doctor(tmp, cfg={"memory": {"git_enabled": True}})
        assert report["checks"]["git"]["status"] == "READY"
        assert report["checks"]["git"]["uncommitted_changes"] == 0
    finally:
        _rmtree(tmp)


# --- run_validate(): the note-correctness subset ----------------------------

def test_run_validate_excludes_environment_checks():
    tmp = _tmp()
    try:
        mv.bootstrap_vault(_vault_path(tmp))
        result = doctor.run_validate(tmp, cfg={})
        assert set(result["checks"].keys()) == {"schema", "duplicate_ids", "invalid_yaml", "broken_links", "secrets"}
        assert "git" not in result["checks"]
        assert "obsidian_cli" not in result["checks"]
        assert "large_files" not in result["checks"]
    finally:
        _rmtree(tmp)


def test_run_validate_blocks_on_the_same_secret_leak_doctor_would():
    tmp = _tmp()
    try:
        vault_path = _vault_path(tmp)
        mv.bootstrap_vault(vault_path)
        eng_dir = vault_path / "06_Agent_Memory" / "Engineering"
        text = mv.render_note_markdown(
            {"id": "NOTE-LEAK2", "memory_level": "engineering", "protocol": "USB", "status": "ACTIVE",
             "confidence": "HIGH", "created": "2026-01-01T00:00:00+00:00", "updated": "2026-01-01T00:00:00+00:00"},
            sections={"Context": "PASSWORD=realsecret"},
        )
        (eng_dir / "NOTE-LEAK2.md").write_text(text, encoding="utf-8")
        result = doctor.run_validate(tmp, cfg={})
        assert result["overall"] == "BLOCKED"
        assert "secrets" in result["blocked_reasons"]
    finally:
        _rmtree(tmp)
