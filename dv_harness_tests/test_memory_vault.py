"""Tests for the Obsidian+Git/Markdown Hybrid Engineering Memory foundational
layer (dv_harness/memory_vault.py) and its wiring into memory_router.py --
Workstream 1 of 4 (obsidian-memory-core, 2026-09-03).

Covers: Phase 2 (Obsidian CLI capability detection, real + a simulated
"installed" branch since this dev machine confirmed NOT_INSTALLED), Phase 3
(vault bootstrap, additive/never-destructive), Phase 7 (note schema
validation + render/parse round-trip), Phase 8 (MemoryProvider interface,
ObsidianAdapter's honest NOT_AVAILABLE behavior, FileSystemMarkdownAdapter's
real CRUD+search+tags+links, HybridMemoryProvider's per-call fallback), and
the Phase 4-6 core wiring in memory_router.py (additive vault write-through
on ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion, real
confirmation_count increments via a genuine dedup-and-confirm path, and
promote_to_organizational()'s three-gate promotion logic).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dv_harness import memory_vault as mv
from dv_harness.memory import MemoryStore, MemoryConsolidator, MemoryGC
from dv_harness.memory_router import route_and_store, promote_to_organizational, ORGANIZATIONAL_MIN_CONFIRMATIONS
from dv_harness_tests.organizational_promotion_fixture import admitted_organizational_record


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    # git marks its object files read-only on Windows; shutil.rmtree's
    # default handler can't unlink those without this. Only the
    # git-integration test below actually creates a `.git` dir, but every
    # test uses this helper for consistency.
    def _on_rm_error(func, p, exc_info):
        import os as _os
        import stat as _stat
        _os.chmod(p, _stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_rm_error)


# --- Phase 2: Obsidian CLI capability detection -----------------------------

def test_detect_obsidian_cli_real_probe_reports_not_installed_on_this_machine():
    # Real, unmocked probe -- matches the controller's own 2026-09-03
    # discovery (`where obsidian-cli`/`where obsidian` both failed).
    report = mv.detect_obsidian_cli()
    assert report["installed"] is False
    assert report["version"] is None
    assert report["executable"] is None
    assert report["status"] == "PARTIAL"  # never BLOCKED merely for being absent
    for cap in ("search", "read", "create", "update", "properties", "tags", "links"):
        assert report[cap] == "NOT_AVAILABLE"


def test_detect_obsidian_cli_is_a_real_probe_not_a_hardcoded_false():
    # Proves the detection logic itself is genuine (not `return {"installed":
    # False, ...}` unconditionally) by making shutil.which report a fake
    # executable and a fake subprocess confirm a version -- the function
    # must then honestly report installed=True with that real version.
    with patch("dv_harness.memory_vault.shutil.which", return_value="/fake/path/obsidian-cli"):
        with patch("dv_harness.memory_vault.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="obsidian-cli 1.2.3\n", stderr="")
            report = mv.detect_obsidian_cli()
    assert report["installed"] is True
    assert report["executable"] == "/fake/path/obsidian-cli"
    assert report["version"] == "obsidian-cli 1.2.3"
    # Still PARTIAL, still every operation NOT_AVAILABLE -- Phase 8's "thin
    # adapter" design: detecting a real binary does not, by itself, make
    # this adapter perform real operations against an unverified contract.
    assert report["status"] == "PARTIAL"
    assert report["create"] == "NOT_AVAILABLE"


def test_detect_obsidian_cli_never_raises_even_on_a_probing_crash():
    with patch("dv_harness.memory_vault.shutil.which", side_effect=RuntimeError("boom")):
        report = mv.detect_obsidian_cli()
    assert report["status"] == "BLOCKED"
    assert "error" in report


# --- Phase 3: DV-Knowledge Vault bootstrap ----------------------------------

def test_bootstrap_vault_creates_the_full_structure():
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        report = mv.bootstrap_vault(vault)
        assert report["vault_pre_existing"] is False
        for rel in mv.VAULT_STRUCTURE:
            assert (vault / rel).is_dir(), rel
        assert set(report["created"]) == set(mv.VAULT_STRUCTURE)
        assert report["already_existed"] == []
    finally:
        _rmtree(tmp)


def test_bootstrap_vault_is_additive_and_never_destroys_existing_content():
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        mv.bootstrap_vault(vault)
        marker = vault / "00_Inbox" / "my_own_note.md"
        marker.write_text("do not delete me", encoding="utf-8")
        custom_dir = vault / "My_Custom_Folder"
        custom_dir.mkdir()

        report2 = mv.bootstrap_vault(vault)
        assert report2["vault_pre_existing"] is True
        assert report2["created"] == []
        assert set(report2["already_existed"]) == set(mv.VAULT_STRUCTURE)
        assert marker.read_text(encoding="utf-8") == "do not delete me"
        assert custom_dir.is_dir()
    finally:
        _rmtree(tmp)


def test_resolve_vault_path_defaults_to_project_relative_when_unconfigured():
    tmp = _tmp()
    try:
        p = mv.resolve_vault_path(tmp, cfg={"memory": {"vault_path": ""}})
        assert p == (tmp / ".dv-harness" / "vault").resolve()
    finally:
        _rmtree(tmp)


def test_resolve_vault_path_honors_explicit_absolute_configuration():
    tmp = _tmp()
    try:
        explicit = tmp / "elsewhere" / "my-vault"
        p = mv.resolve_vault_path(tmp, cfg={"memory": {"vault_path": str(explicit)}})
        assert p == explicit.resolve()
    finally:
        _rmtree(tmp)


# --- Phase 7: Memory note schema --------------------------------------------

def test_validate_note_frontmatter_flags_missing_required_fields_as_partial():
    complete = {f: "x" for f in mv.MEMORY_NOTE_REQUIRED_FIELDS}
    result = mv.validate_note_frontmatter(complete)
    assert result["schema_status"] == "COMPLETE"
    assert result["missing_required"] == []

    incomplete = dict(complete)
    del incomplete["protocol"]
    incomplete["confidence"] = ""
    result = mv.validate_note_frontmatter(incomplete)
    assert result["schema_status"] == "PARTIAL"
    assert set(result["missing_required"]) == {"protocol", "confidence"}


def test_missing_recommended_reports_spec_fields_without_gating_schema_status():
    """The spec text calls subsystem/category/failure/project/rtl_sha/tb_sha/
    vip_vendor/vip_version/simulator required; this module gates only on the
    identity/trust fields. The difference must be REPORTED, not invisible --
    and must not flip schema_status on its own."""
    only_required = {f: "x" for f in mv.MEMORY_NOTE_REQUIRED_FIELDS}
    result = mv.validate_note_frontmatter(only_required)
    assert result["schema_status"] == "COMPLETE", "recommended fields must never gate schema_status"
    assert set(result["missing_recommended"]) == set(mv.MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS)

    # `tags`/`knowledge_commit_sha` are deliberately NOT reported as absent.
    assert "tags" not in result["missing_recommended"]
    assert "knowledge_commit_sha" not in result["missing_recommended"]

    fully_populated = {f: "x" for f in mv.MEMORY_NOTE_ALL_FIELDS}
    assert mv.validate_note_frontmatter(fully_populated)["missing_recommended"] == []


def test_validate_note_body_sections_accepts_a_rendered_note():
    fm = {f: "x" for f in mv.MEMORY_NOTE_REQUIRED_FIELDS}
    _, body = mv.parse_note_markdown(mv.render_note_markdown(fm))
    assert mv.validate_note_body_sections(body) == {
        "body_status": "COMPLETE", "missing_sections": [], "unexpected_sections": [], "out_of_order": False,
    }


def test_validate_note_body_sections_flags_a_hand_deleted_section():
    """The real gap this closes: a note hand-edited in the Obsidian GUI that
    drops a `## Fix` header. The write path can never produce this, so only a
    read-side check can catch it."""
    fm = {f: "x" for f in mv.MEMORY_NOTE_REQUIRED_FIELDS}
    _, body = mv.parse_note_markdown(mv.render_note_markdown(fm, {"Fix": "raise the fifo threshold"}))
    assert "## Fix" in body

    edited = "\n".join(l for l in body.splitlines()
                       if l not in ("## Fix", "raise the fifo threshold"))
    result = mv.validate_note_body_sections(edited)
    assert result["body_status"] == "PARTIAL"
    assert result["missing_sections"] == ["Fix"]
    assert result["out_of_order"] is False


def test_validate_note_body_sections_flags_reordered_sections():
    reordered = list(mv.MEMORY_NOTE_BODY_SECTIONS)
    reordered[4], reordered[5] = reordered[5], reordered[4]  # Fix before Root Cause
    body = "\n\n".join(f"## {name}\n_x_" for name in reordered)
    result = mv.validate_note_body_sections(body)
    assert result["body_status"] == "PARTIAL"
    assert result["missing_sections"] == []
    assert result["out_of_order"] is True


def test_validate_note_body_sections_tolerates_an_extra_human_section():
    fm = {f: "x" for f in mv.MEMORY_NOTE_REQUIRED_FIELDS}
    _, body = mv.parse_note_markdown(mv.render_note_markdown(fm))
    result = mv.validate_note_body_sections(body + "\n\n## Operator Notes\nrerun with WAVE=1\n")
    assert result["body_status"] == "COMPLETE", "adding a section is not a schema violation"
    assert result["unexpected_sections"] == ["Operator Notes"]


def test_validate_note_body_sections_flags_a_frontmatter_only_note():
    result = mv.validate_note_body_sections("")
    assert result["body_status"] == "PARTIAL"
    assert result["missing_sections"] == mv.MEMORY_NOTE_BODY_SECTIONS


def test_validate_note_requires_both_halves_complete():
    fm = {f: "x" for f in mv.MEMORY_NOTE_REQUIRED_FIELDS}
    _, body = mv.parse_note_markdown(mv.render_note_markdown(fm))

    assert mv.validate_note(fm, body)["note_status"] == "COMPLETE"

    good_fm_bad_body = mv.validate_note(fm, "## Symptom\nx")
    assert good_fm_bad_body["note_status"] == "PARTIAL"
    assert good_fm_bad_body["schema_status"] == "COMPLETE"
    assert good_fm_bad_body["body_status"] == "PARTIAL"

    bad_fm = dict(fm)
    del bad_fm["protocol"]
    bad_fm_good_body = mv.validate_note(bad_fm, body)
    assert bad_fm_good_body["note_status"] == "PARTIAL"
    assert bad_fm_good_body["schema_status"] == "PARTIAL"
    assert bad_fm_good_body["body_status"] == "COMPLETE"


def test_build_frontmatter_uses_the_general_protocol_key_for_a_protocol_less_record():
    """The measured defect this pins (2026-09-04): all 9 of this project's
    real vault notes were schema_status PARTIAL, every one on `protocol`
    alone, because the mapper emitted null for a harness-engine/process
    lesson that legitimately names no protocol -- while the vault commit that
    captured that very note already said `memory(_general): ...`."""
    engine_lesson = {"memory_id": "MEM-AAAA000001", "scope": "engine", "title": "stage retry loop",
                     "confidence": "CONFIRMED", "status": "ACTIVE"}
    fm = mv.build_frontmatter_from_memory_record("ENGINEERING_MEMORY", engine_lesson)
    assert fm["protocol"] == mv.GENERAL_PROTOCOL
    assert mv.validate_note_frontmatter(fm)["schema_status"] == "COMPLETE"
    # The fallback is a searchable field value, never a tag -- "_general" on
    # every non-protocol note's tag list would filter nothing.
    assert mv.GENERAL_PROTOCOL not in fm["tags"]

    real_protocol = mv.build_frontmatter_from_memory_record(
        "ENGINEERING_MEMORY", {**engine_lesson, "protocol": "USB3"})
    assert real_protocol["protocol"] == "USB3"
    assert "usb3" in real_protocol["tags"]


def test_route_and_store_writes_a_schema_complete_note_for_a_protocol_less_record():
    """End-to-end through the REAL router write path, not the mapper alone:
    a genuinely protocol-less engineering record must land on disk as a note
    whose own frontmatter says COMPLETE, and must still say COMPLETE when the
    file is re-parsed and re-validated from disk."""
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        result = route_and_store(tmp, {
            "kind": "debug_lesson", "verified": True, "scope": "engine",
            "title": "gate evidence blocks were re-parsed per stage instead of cached",
            "lesson": "cache the parsed evidence block per stage attempt",
            "root_cause": "run_stage() re-parsed the same response text once per gate",
            "confidence": "HIGH",
            "evidence": [".dv-harness/events.jsonl:2211 STAGE_GATE re-parse", "stage_profile: 11 duplicate parses"],
        }, cfg=cfg)
        assert result["destination"] == "ENGINEERING_MEMORY"
        note_path = tmp / ".dv-harness" / "vault" / result["vault_write"]["path"]
        fm, body = mv.parse_note_markdown(note_path.read_text(encoding="utf-8"))
        assert fm["protocol"] == mv.GENERAL_PROTOCOL
        assert fm["schema_status"] == "COMPLETE"
        assert mv.validate_note(fm, body)["note_status"] == "COMPLETE"
    finally:
        _rmtree(tmp)


def test_resync_notes_repairs_a_legacy_protocol_null_note_from_its_source_record():
    """The repair half: fixing the mapper cannot fix a note already on disk,
    because nothing re-derives a note until its record is written again. This
    drives a REAL note written the pre-fix way (protocol: null) against a
    real, healthy MemoryStore record and asserts the resync makes it
    COMPLETE without touching the record."""
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        stored = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "scope": "process",
            "title": "reference BFM patterns were consulted reactively",
            "root_cause": "no upfront line-by-line coverage audit of reference/bfm_patterns",
            "fix": "run a full-coverage conversion pass before debugging",
            "confidence": "CONFIRMED",
            "evidence": ["reference/bfm_patterns/USB2_bulkin.txt:79", "3 debugging rounds lost"],
        }, cfg=cfg)
        note_id = stored["memory_id"]
        vault_path = mv.resolve_vault_path(tmp, cfg)
        note_path = vault_path / stored["vault_write"]["path"]

        # Rewrite the note exactly as the pre-fix mapper did: protocol null,
        # schema_status PARTIAL. Written directly, not through the adapter,
        # because the adapter now refuses to record that as COMPLETE.
        fm, body = mv.parse_note_markdown(note_path.read_text(encoding="utf-8"))
        fm["protocol"] = None
        fm["schema_status"] = "PARTIAL"
        note_path.write_text(mv.render_note_markdown(fm, mv._body_to_sections(body)), encoding="utf-8")
        legacy_fm, legacy_body = mv.parse_note_markdown(note_path.read_text(encoding="utf-8"))
        assert mv.validate_note(legacy_fm, legacy_body)["note_status"] == "PARTIAL"
        assert mv.validate_note(legacy_fm, legacy_body)["missing_required"] == ["protocol"]

        report = mv.resync_notes_from_memory_store(tmp, cfg)
        assert report["repaired"] == [note_id]
        assert report["still_partial"] == []
        assert report["skipped"] == []

        fixed_fm, fixed_body = mv.parse_note_markdown(note_path.read_text(encoding="utf-8"))
        assert fixed_fm["protocol"] == mv.GENERAL_PROTOCOL
        assert fixed_fm["schema_status"] == "COMPLETE"
        assert mv.validate_note(fixed_fm, fixed_body)["note_status"] == "COMPLETE"
        # The repair re-renders from the record; it must not lose the body.
        assert "no upfront line-by-line coverage audit" in fixed_body
        assert MemoryStore(tmp).get(note_id).get("protocol") is None, \
            "the fallback belongs to the note, not to the record -- the record stays as written"
    finally:
        _rmtree(tmp)


def test_resync_notes_preserves_a_real_protocol_and_never_invents_one():
    """Two honest-boundary halves in one: a note whose record names USB2 keeps
    USB2 (the fallback only ever fills a genuine absence), and a note with no
    source record left to mirror is reported skipped and left byte-identical
    rather than rebuilt from guesses."""
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        stored = route_and_store(tmp, {
            "kind": "verified_fix", "verified": True, "protocol": "USB2",
            "title": "EP0 underrun", "root_cause": "missing prefetch guard on the ep0 fifo",
            "fix": "assert prefetch before ep0 IN", "confidence": "HIGH",
            "evidence": ["sim.log:8821 UVM_ERROR ep0 underrun"],
        }, cfg=cfg)
        vault_path = mv.resolve_vault_path(tmp, cfg)

        orphan = mv.FileSystemMarkdownAdapter(vault_path, git_enabled=False).create({
            "id": "MEM-ORPHAN0001", "memory_level": "engineering", "protocol": "PCIe",
            "status": "ACTIVE", "confidence": "MEDIUM",
        })
        orphan_path = vault_path / orphan["path"]
        orphan_before = orphan_path.read_text(encoding="utf-8")

        report = mv.resync_notes_from_memory_store(tmp, cfg)
        assert [e["note_id"] for e in report["resynced"]] == [stored["memory_id"]]
        assert report["skipped"] == [{"note_id": "MEM-ORPHAN0001", "path": orphan["path"],
                                      "before": "COMPLETE", "reason": "NO_SOURCE_RECORD"}]
        assert orphan_path.read_text(encoding="utf-8") == orphan_before

        fm, _ = mv.parse_note_markdown(
            (vault_path / stored["vault_write"]["path"]).read_text(encoding="utf-8"))
        assert fm["protocol"] == "USB2"
    finally:
        _rmtree(tmp)


def test_render_and_parse_note_markdown_round_trip():
    fm = {
        "id": "MEM-ABC123", "memory_level": "engineering", "protocol": "USB2",
        "subsystem": None, "status": "ACTIVE", "confidence": "HIGH",
        "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00",
        "tags": ["usb2", "engineering"],
    }
    sections = {
        "Root Cause": "ep0 fifo underrun",
        "Fix": "line 1\nline 2 with: a colon",
        "Related Knowledge": "- [[F-1]]\n- [[MEM-OTHER]]",
    }
    text = mv.render_note_markdown(fm, sections)
    assert text.startswith("---\n")
    for name in mv.MEMORY_NOTE_BODY_SECTIONS:
        assert f"## {name}" in text

    parsed_fm, parsed_body = mv.parse_note_markdown(text)
    assert parsed_fm["id"] == "MEM-ABC123"
    assert parsed_fm["protocol"] == "USB2"
    assert parsed_fm["subsystem"] is None
    assert parsed_fm["tags"] == ["usb2", "engineering"]
    assert "ep0 fifo underrun" in parsed_body
    assert "line 1\nline 2 with: a colon" in parsed_body
    assert "[[F-1]]" in parsed_body


def test_frontmatter_round_trip_handles_special_characters_safely():
    fm = {
        "id": "MEM-1", "memory_level": "engineering", "protocol": "USB2",
        "status": "ACTIVE", "confidence": "HIGH", "created": "c", "updated": "u",
        "failure": 'a value: with a colon and "quotes"',
        "tags": [],
    }
    text = mv.render_note_markdown(fm)
    parsed_fm, _ = mv.parse_note_markdown(text)
    assert parsed_fm["failure"] == 'a value: with a colon and "quotes"'
    assert parsed_fm["tags"] == []


# --- Phase 8: MemoryProvider interface / ObsidianAdapter --------------------

def test_obsidian_adapter_every_operation_reports_not_available():
    adapter = mv.ObsidianAdapter(vault_path=None)
    assert adapter.status()["status"] == "PARTIAL"
    for call in (
        lambda: adapter.search({}), lambda: adapter.read("x"),
        lambda: adapter.create({}), lambda: adapter.update("x"),
        lambda: adapter.delete("x"), lambda: adapter.list_tags(),
        lambda: adapter.list_links("x"), lambda: adapter.get_properties("x"),
        lambda: adapter.set_properties("x", {}),
    ):
        result = call()
        assert result["ok"] is False
        assert result["status"] == "NOT_AVAILABLE"
        assert result["fallback"] == "FileSystemMarkdownAdapter"


def test_obsidian_adapter_not_available_reason_differs_when_installed_but_unwired():
    with patch("dv_harness.memory_vault.detect_obsidian_cli", return_value={
        "installed": True, "version": "1.0", "executable": "/x/obsidian-cli",
        "vault_access": False, "search": "NOT_AVAILABLE", "read": "NOT_AVAILABLE",
        "create": "NOT_AVAILABLE", "update": "NOT_AVAILABLE", "properties": "NOT_AVAILABLE",
        "tags": "NOT_AVAILABLE", "links": "NOT_AVAILABLE", "status": "PARTIAL",
    }):
        adapter = mv.ObsidianAdapter()
        result = adapter.create({})
    assert "detected" in result["reason"].lower()
    assert "/x/obsidian-cli" in result["reason"]


# --- Phase 8: FileSystemMarkdownAdapter (the real implementation) ----------

def _complete_fm(note_id="MEM-1", protocol="USB2", memory_level="engineering", **extra):
    fm = {
        "id": note_id, "memory_level": memory_level, "protocol": protocol,
        "status": "ACTIVE", "confidence": "HIGH",
        "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00",
        "tags": [protocol.lower(), memory_level],
    }
    fm.update(extra)
    return fm


def test_filesystem_adapter_create_read_update_delete_round_trip():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        created = fs.create(_complete_fm(), sections={"Root Cause": "underrun"})
        assert created["ok"] is True
        assert created["validation"]["schema_status"] == "COMPLETE"
        assert (tmp / "vault" / created["path"]).exists()
        assert "06_Agent_Memory" in created["path"] and "Engineering" in created["path"]

        read = fs.read("MEM-1")
        assert read["ok"] is True
        assert read["frontmatter"]["protocol"] == "USB2"
        assert "underrun" in read["body"]

        dup = fs.create(_complete_fm())
        assert dup == {"ok": False, "error": "ALREADY_EXISTS", "note_id": "MEM-1", "path": created["path"]}

        updated = fs.update("MEM-1", frontmatter_patch={"confidence": "CONFIRMED"},
                             sections_patch={"Fix": "per-port queue"})
        assert updated["ok"] is True
        read2 = fs.read("MEM-1")
        assert read2["frontmatter"]["confidence"] == "CONFIRMED"
        assert read2["frontmatter"]["updated"] != read["frontmatter"]["updated"]
        assert "underrun" in read2["body"]  # untouched section preserved
        assert "per-port queue" in read2["body"]  # patched section applied

        deleted = fs.delete("MEM-1")
        assert deleted == {"ok": True, "note_id": "MEM-1"}
        assert fs.read("MEM-1") == {"ok": False, "error": "NOT_FOUND"}
        assert fs.update("MEM-1") == {"ok": False, "error": "NOT_FOUND"}
        assert fs.delete("MEM-1") == {"ok": False, "error": "NOT_FOUND"}
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_marks_incomplete_note_as_partial_never_silently_complete():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        sparse_fm = {"id": "MEM-SPARSE", "memory_level": "engineering"}  # protocol/status/confidence/... missing
        result = fs.create(sparse_fm)
        assert result["validation"]["schema_status"] == "PARTIAL"
        assert "protocol" in result["validation"]["missing_required"]
        on_disk = fs.read("MEM-SPARSE")
        assert on_disk["frontmatter"]["schema_status"] == "PARTIAL"
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_writes_to_the_correct_memory_level_folder():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        for level, folder in (
            ("working", "Working"), ("job", "Job"), ("project", "Project"),
            ("engineering", "Engineering"), ("organizational", "Organizational"),
        ):
            r = fs.create(_complete_fm(note_id=f"MEM-{level}", memory_level=level))
            assert f"06_Agent_Memory\\{folder}" in r["path"] or f"06_Agent_Memory/{folder}" in r["path"]
        r_unknown = fs.create(_complete_fm(note_id="MEM-inbox", memory_level="mystery"))
        assert "00_Inbox" in r_unknown["path"]
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_search_by_protocol_tag_property_and_text():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        fs.create(_complete_fm(note_id="MEM-USB", protocol="USB2"),
                   sections={"Root Cause": "ep0 fifo underrun on GET_DESCRIPTOR"})
        fs.create(_complete_fm(note_id="MEM-PCIE", protocol="PCIe"),
                   sections={"Root Cause": "ltssm cdc timing violation"})

        by_protocol = fs.search({"protocol": "USB2"})
        assert [r["note_id"] for r in by_protocol["results"]] == ["MEM-USB"]

        by_tag = fs.search({"tag": "pcie"})
        assert [r["note_id"] for r in by_tag["results"]] == ["MEM-PCIE"]

        by_property = fs.search({"property": {"confidence": "HIGH"}})
        assert {r["note_id"] for r in by_property["results"]} == {"MEM-USB", "MEM-PCIE"}

        by_text = fs.search({"text": "fifo underrun"})
        assert [r["note_id"] for r in by_text["results"]] == ["MEM-USB"]

        by_exact = fs.search({"exact": "ltssm cdc timing violation"})
        assert [r["note_id"] for r in by_exact["results"]] == ["MEM-PCIE"]

        no_match = fs.search({"protocol": "Ethernet"})
        assert no_match["results"] == []

        everything = fs.search({})
        assert {r["note_id"] for r in everything["results"]} == {"MEM-USB", "MEM-PCIE"}
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_search_degrades_correctly_without_rg():
    # Forces the pure-Python fallback path (no rg accelerator) and proves
    # correctness is identical -- rg is only ever a speed optimization.
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        fs.create(_complete_fm(note_id="MEM-A"), sections={"Root Cause": "needle in haystack"})
        fs.create(_complete_fm(note_id="MEM-B"), sections={"Root Cause": "nothing relevant here"})
        with patch("dv_harness.memory_vault.shutil.which", return_value=None):
            result = fs.search({"text": "needle"})
        assert [r["note_id"] for r in result["results"]] == ["MEM-A"]
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_list_tags_and_list_links():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        fs.create(_complete_fm(note_id="MEM-A", protocol="USB2"),
                   sections={"Related Knowledge": "- [[MEM-B]]"})
        fs.create(_complete_fm(note_id="MEM-B", protocol="USB2"))

        tags = fs.list_tags()
        assert tags["ok"] is True
        assert tags["tags"]["usb2"] == 2

        links_a = fs.list_links("MEM-A")
        assert links_a["forward_links"] == ["MEM-B"]
        assert links_a["backlinks"] == []

        links_b = fs.list_links("MEM-B")
        assert links_b["forward_links"] == []
        assert links_b["backlinks"] == ["MEM-A"]

        by_link = fs.search({"linked_to": "MEM-B"})
        assert [r["note_id"] for r in by_link["results"]] == ["MEM-A"]
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_get_and_set_properties():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        fs.create(_complete_fm())
        props = fs.get_properties("MEM-1")
        assert props["properties"]["protocol"] == "USB2"

        updated = fs.set_properties("MEM-1", {"status": "DEPRECATED"})
        assert updated["ok"] is True
        assert updated["properties"]["status"] == "DEPRECATED"
        assert fs.get_properties("MEM-1")["properties"]["status"] == "DEPRECATED"
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_git_integration_commits_when_enabled_and_git_present():
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        fs = mv.FileSystemMarkdownAdapter(vault, git_enabled=True)
        assert (vault / ".git").is_dir()
        fs.create(_complete_fm())
        import subprocess
        log = subprocess.run(["git", "log", "--oneline"], cwd=str(vault), capture_output=True, text=True)
        assert "create MEM-1" in log.stdout
    finally:
        _rmtree(tmp)


def test_filesystem_adapter_git_disabled_by_default_does_not_create_a_repo():
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        mv.FileSystemMarkdownAdapter(vault, git_enabled=False)
        assert not (vault / ".git").exists()
    finally:
        _rmtree(tmp)


# --- Phase 8: HybridMemoryProvider -------------------------------------------

def test_hybrid_provider_uses_filesystem_when_obsidian_not_ready():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        obs = mv.ObsidianAdapter(vault_path=None)  # real, confirmed not-ready on this machine
        hybrid = mv.HybridMemoryProvider(obs, fs)
        result = hybrid.create(_complete_fm())
        assert result["ok"] is True
        assert (tmp / "vault" / result["path"]).exists()
    finally:
        _rmtree(tmp)


def test_hybrid_provider_falls_back_to_filesystem_when_obsidian_reports_ready_but_op_not_available():
    # The exact scenario a future READY-but-unwired machine would hit --
    # proves "opportunistic Obsidian, filesystem otherwise" degrades
    # per-call rather than silently losing the write.
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        obs = MagicMock()
        obs.status.return_value = {"status": "READY"}
        obs.create.return_value = {"ok": False, "status": "NOT_AVAILABLE", "reason": "unwired"}
        hybrid = mv.HybridMemoryProvider(obs, fs)

        result = hybrid.create(_complete_fm())
        assert obs.create.called
        assert result["ok"] is True
        assert (tmp / "vault" / result["path"]).exists()
    finally:
        _rmtree(tmp)


def test_hybrid_provider_uses_obsidian_result_when_it_genuinely_succeeds():
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        obs = MagicMock()
        obs.status.return_value = {"status": "READY"}
        obs.create.return_value = {"ok": True, "note_id": "MEM-1", "via": "obsidian"}
        hybrid = mv.HybridMemoryProvider(obs, fs)
        result = hybrid.create(_complete_fm())
        assert result == {"ok": True, "note_id": "MEM-1", "via": "obsidian"}
        # filesystem must NOT also have written a duplicate note in this case
        assert not (tmp / "vault" / "06_Agent_Memory" / "Engineering" / "MEM-1.md").exists()
    finally:
        _rmtree(tmp)


def test_get_active_provider_disabled_mode_skips_obsidian_entirely():
    tmp = _tmp()
    try:
        cfg = {"memory": {"vault_path": "", "obsidian_cli": "disabled", "git_enabled": False}}
        provider = mv.get_active_provider(tmp, cfg=cfg)
        assert isinstance(provider, mv.FileSystemMarkdownAdapter)
    finally:
        _rmtree(tmp)


def test_get_active_provider_auto_mode_returns_hybrid_and_bootstraps_vault():
    tmp = _tmp()
    try:
        cfg = {"memory": {"vault_path": "", "obsidian_cli": "auto", "git_enabled": False}}
        provider = mv.get_active_provider(tmp, cfg=cfg)
        assert isinstance(provider, mv.HybridMemoryProvider)
        assert (tmp / ".dv-harness" / "vault" / "06_Agent_Memory" / "Engineering").is_dir()
    finally:
        _rmtree(tmp)


# --- Phase 4-6 core wiring: memory_router.py additive vault write-through --

def test_route_and_store_engineering_memory_writes_a_real_vault_note():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        result = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "USB2 EP0 underrun",
            "protocol": "USB2", "root_cause": "missing prefetch", "confidence": "HIGH",
            "evidence": ["sim.log:8821 UVM_ERROR ep0 underrun", "rtl: no prefetch guard on ep0 fifo"],
        }, cfg=cfg)
        assert result["destination"] == "ENGINEERING_MEMORY"
        assert result["vault_write"]["ok"] is True
        note_path = tmp / ".dv-harness" / "vault" / result["vault_write"]["path"]
        assert note_path.exists()
        fm, body = mv.parse_note_markdown(note_path.read_text(encoding="utf-8"))
        assert fm["id"] == result["memory_id"]
        assert fm["protocol"] == "USB2"
        assert "missing prefetch" in body
    finally:
        _rmtree(tmp)


def test_vault_note_frontmatter_carries_the_records_measured_confidence():
    """The vault note is the human-browsable mirror of the JSON system of
    record; a HIGH-confidence verified fix must not read UNKNOWN there.

    The second half pins the honest complement: a record admitted through
    engineering_admission_gate()'s gate-validated-`verification` path carries
    no `confidence` key of its own, and the note says UNKNOWN rather than
    inventing a level the record never asserted. That is why the USB3 LFPS
    end-to-end chain now puts score_confidence()'s real result ON the record
    (dv_harness_tests/e2e_memory_chain_usb3_lfps.py, STEP 10) instead of the
    note's builder guessing one.
    """
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        measured = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "protocol": "USB3",
            "title": "Polling.LFPS timeout -- lfps_detect CDC missing synchronizer",
            "root_cause": "lfps_detect crosses into core_clk with no 2-flop synchronizer",
            "fix": "add a 2-flop synchronizer on lfps_detect", "confidence": "HIGH",
            "evidence": ["sim.log:4412 UVM_ERROR polling.lfps timeout"],
        }, cfg=cfg)
        assert measured["destination"] == "ENGINEERING_MEMORY"
        fm, _ = mv.parse_note_markdown(
            (tmp / ".dv-harness" / "vault" / measured["vault_write"]["path"]).read_text(encoding="utf-8"))
        assert fm["confidence"] == "HIGH"
        assert "high" in fm["tags"]

        unstated = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "protocol": "USB3",
            "title": "gate-validated but confidence never stated",
            "root_cause": "second, independent root cause with no confidence key",
            "evidence": ["sim.log:9001 UVM_ERROR distinct symptom"],
            "verification": {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
        }, cfg=cfg)
        assert unstated["destination"] == "ENGINEERING_MEMORY"
        fm2, _ = mv.parse_note_markdown(
            (tmp / ".dv-harness" / "vault" / unstated["vault_write"]["path"]).read_text(encoding="utf-8"))
        assert fm2["confidence"] == "UNKNOWN"
    finally:
        _rmtree(tmp)


def test_route_and_store_organizational_memory_writes_a_vault_note_only_on_success():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": True, "remote_root": "/srv/kc"},
               "memory": {"vault_path": "", "git_enabled": False}}
        with patch("dv_harness.knowledge_center.KnowledgeCenterClient.add") as add_mock:
            add_mock.return_value = {"ok": True, "memory_id": "KC-42"}
            result = route_and_store(tmp, admitted_organizational_record(
                tmp, title="cross-project lesson", protocol="USB2"), cfg=cfg)
        assert result["destination"] == "ORGANIZATIONAL_MEMORY"
        assert result["vault_write"]["ok"] is True
        note_path = tmp / ".dv-harness" / "vault" / result["vault_write"]["path"]
        assert note_path.exists()

        # And the NOT_CONFIGURED failure path must NOT attempt a vault write.
        cfg_disabled = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        result2 = route_and_store(tmp, admitted_organizational_record(
            tmp, title="t2", protocol="USB2"), cfg=cfg_disabled)
        assert result2["ok"] is False
        assert "vault_write" not in result2
    finally:
        _rmtree(tmp)


def test_route_and_store_vault_write_failure_never_breaks_the_local_json_write():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        with patch("dv_harness.memory_vault.get_active_provider", side_effect=RuntimeError("disk full")):
            result = route_and_store(tmp, {
                "kind": "root_cause", "verified": True, "title": "t", "protocol": "USB2", "root_cause": "x",
                "confidence": "HIGH", "evidence": ["sim.log:41 UVM_ERROR"],
            }, cfg=cfg)
        assert result["destination"] == "ENGINEERING_MEMORY"
        assert "memory_id" in result
        assert result["vault_write"]["ok"] is False
        assert result["vault_write"]["error"] == "VAULT_WRITE_FAILED"
        # the real JSON record still landed on disk despite the vault failure
        from dv_harness.memory import MemoryStore
        assert MemoryStore(tmp).get(result["memory_id"]) is not None
    finally:
        _rmtree(tmp)


def test_route_and_store_explicit_empty_cfg_skips_vault_write_too():
    tmp = _tmp()
    try:
        result = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "t", "protocol": "USB2", "root_cause": "x",
        }, cfg={})
        assert "vault_write" not in result
    finally:
        _rmtree(tmp)


# --- Phase 4-6 core wiring: real confirmation_count increments --------------

def test_second_route_and_store_call_for_the_same_finding_confirms_instead_of_duplicating():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        r1 = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "first report",
            "protocol": "USB2", "root_cause": "ep0 fifo underrun", "confidence": "HIGH",
            "evidence": ["sim.log:8821 UVM_ERROR ep0 underrun"],
        }, cfg=cfg)
        assert "confirmed_existing" not in r1

        r2 = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "independent re-derivation",
            "protocol": "USB2", "root_cause": "EP0 FIFO Underrun",  # same claim, different casing
            "confidence": "HIGH", "evidence": ["second run sim.log:9104 same UVM_ERROR"],
        }, cfg=cfg)
        assert r2["memory_id"] == r1["memory_id"]
        assert r2["confirmed_existing"] is True

        store = MemoryStore(tmp)
        mem = store.get(r1["memory_id"])
        assert mem["confirmation_count"] == 1
        assert mem["last_confirmed_at"] is not None

        # exactly one file on disk for this finding, not two
        eng_dir = tmp / ".dv-harness" / "memory" / "engineering"
        assert len(list(eng_dir.glob("*.json"))) == 1
    finally:
        _rmtree(tmp)


def test_route_and_store_does_not_dedup_across_different_protocols_or_root_causes():
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        r1 = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "t1",
            "protocol": "USB2", "root_cause": "ep0 fifo underrun",
        }, cfg=cfg)
        r2 = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "t2",
            "protocol": "PCIe", "root_cause": "ep0 fifo underrun",  # same text, different protocol
        }, cfg=cfg)
        r3 = route_and_store(tmp, {
            "kind": "root_cause", "verified": True, "title": "t3",
            "protocol": "USB2", "root_cause": "completely unrelated issue",
        }, cfg=cfg)
        assert len({r1["memory_id"], r2["memory_id"], r3["memory_id"]}) == 3
        for r in (r2, r3):
            assert "confirmed_existing" not in r
    finally:
        _rmtree(tmp)


def test_route_and_store_never_dedups_when_protocol_or_root_cause_is_absent():
    # Matches today's real engine.py verified_fix record shape (no
    # "protocol" key) -- must behave exactly as before this feature existed:
    # a fresh record every time, never an attempted (and impossible) match.
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        r1 = route_and_store(tmp, {
            "kind": "verified_fix", "verified": True, "title": "t", "root_cause": "x", "fix": "y",
        }, cfg=cfg)
        r2 = route_and_store(tmp, {
            "kind": "verified_fix", "verified": True, "title": "t", "root_cause": "x", "fix": "y",
        }, cfg=cfg)
        assert r1["memory_id"] != r2["memory_id"]
        assert "confirmed_existing" not in r2
    finally:
        _rmtree(tmp)


# --- Phase 4-6 core wiring: promote_to_organizational() ---------------------

_HIGH_CONF = dict(independent_sources_count=3, evidence_refs_verified=True,
                   counter_evidence_count=0, multi_agent_consensus_count=2)


def _make_confirmed_engineering_finding(tmp):
    finding = {
        "title": "USB2 EP0 underrun", "status": "CLOSED", "protocol": "USB2",
        "scope": "subsystem", "root_cause": "missing prefetch on GET_DESCRIPTOR",
        "fix": "rev2", "finding_id": "F-1",
    }
    verification = {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"}
    store = MemoryStore(tmp)
    return MemoryConsolidator(store).from_closed_finding(finding, verification)["memory_id"]


def test_promote_to_organizational_requires_engineering_tier_and_active_status():
    tmp = _tmp()
    try:
        with pytest.raises(ValueError):
            promote_to_organizational(tmp, "MEM-DOES-NOT-EXIST", _HIGH_CONF, cfg={})

        from dv_harness.memory import JobMemoryStore
        job_mem = JobMemoryStore(tmp).add({"title": "job record"})
        result = promote_to_organizational(tmp, job_mem["memory_id"], _HIGH_CONF, cfg={})
        assert result == {"promoted": False, "reason": "NOT_ENGINEERING_TIER", "level": "job"}
    finally:
        _rmtree(tmp)


def test_promote_to_organizational_rejects_records_with_neither_known_verification_shape():
    tmp = _tmp()
    try:
        store = MemoryStore(tmp)
        mem = store.add("engineering", {
            "title": "unverified claim", "protocol": "USB2", "root_cause": "guessed cause",
            "verification": {"some_other_field": True},  # neither real gate-verified shape
        })
        result = promote_to_organizational(tmp, mem["memory_id"], _HIGH_CONF, cfg={})
        assert result["promoted"] is False
        assert result["reason"] == "QUALITATIVE_GATE_FAILED"
    finally:
        _rmtree(tmp)


def test_promote_to_organizational_accepts_the_re_audit_gate_verification_shape():
    # This is the REAL shape engine.py's _promote_verified_fix_knowledge()
    # actually writes -- distinct from MemoryConsolidator's shape -- and
    # must be recognized as genuinely gate-verified, not rejected merely
    # for using a different (but equally real) evidence vocabulary.
    tmp = _tmp()
    try:
        store = MemoryStore(tmp)
        mem = store.add("engineering", {
            "title": "verified via RE_AUDIT", "protocol": "USB2", "root_cause": "missing prefetch",
            "verification": {
                "targeted_reproducer_passed": True, "broader_regression_passed": True,
                "new_failures_introduced": False, "target_pre_fix_result": "FAIL",
                "target_post_fix_result": "PASS", "replay_equivalent": True,
            },
        })
        MemoryGC(store).confirm(mem["memory_id"])
        MemoryGC(store).confirm(mem["memory_id"])
        result = promote_to_organizational(tmp, mem["memory_id"], _HIGH_CONF, cfg={})
        assert result["destination"] == "ORGANIZATIONAL_MEMORY"
        assert result["promotion_gate"]["qualitative_shape"] == "re_audit_gate_shape"
    finally:
        _rmtree(tmp)


def test_promote_to_organizational_rejects_confidence_below_high():
    tmp = _tmp()
    try:
        mid = _make_confirmed_engineering_finding(tmp)
        store = MemoryStore(tmp)
        MemoryGC(store).confirm(mid)
        MemoryGC(store).confirm(mid)
        low_conf = dict(independent_sources_count=1, evidence_refs_verified=False,
                         counter_evidence_count=0, multi_agent_consensus_count=0)
        result = promote_to_organizational(tmp, mid, low_conf, cfg={})
        assert result["promoted"] is False
        assert result["reason"] == "CONFIDENCE_NOT_HIGH"
    finally:
        _rmtree(tmp)


def test_promote_to_organizational_requires_repeated_confirmation_not_just_one_creation():
    tmp = _tmp()
    try:
        mid = _make_confirmed_engineering_finding(tmp)
        # Zero confirmations yet -- a single CLOSED/VERIFIED creation event
        # is not "repeated confirmation".
        result = promote_to_organizational(tmp, mid, _HIGH_CONF, cfg={})
        assert result["promoted"] is False
        assert result["reason"] == "INSUFFICIENT_CONFIRMATION"
        assert result["confirmation_count"] == 0
        assert result["required"] == ORGANIZATIONAL_MIN_CONFIRMATIONS

        store = MemoryStore(tmp)
        MemoryGC(store).confirm(mid)  # only 1 of 2 required
        result2 = promote_to_organizational(tmp, mid, _HIGH_CONF, cfg={})
        assert result2["reason"] == "INSUFFICIENT_CONFIRMATION"
        assert result2["confirmation_count"] == 1
    finally:
        _rmtree(tmp)


def test_promote_to_organizational_succeeds_once_every_gate_is_satisfied():
    tmp = _tmp()
    try:
        mid = _make_confirmed_engineering_finding(tmp)
        store = MemoryStore(tmp)
        MemoryGC(store).confirm(mid, evidence={"independent_run": 1})
        MemoryGC(store).confirm(mid, evidence={"independent_run": 2})

        cfg = {"knowledge_center": {"enabled": False}}
        result = promote_to_organizational(tmp, mid, _HIGH_CONF, cfg=cfg, kind="best_practice")
        assert result["destination"] == "ORGANIZATIONAL_MEMORY"
        assert result["ok"] is False  # knowledge_center disabled -> NOT_CONFIGURED, honestly reported
        assert result["error"] == "NOT_CONFIGURED"
        assert result["promotion_gate"]["confidence_result"]["level"] == "HIGH"
        assert result["promotion_gate"]["confirmation_count"] == 2
    finally:
        _rmtree(tmp)


# --- Regression: full pre-existing memory suite behavior is unaffected -----
# (The actual full-suite run is done via `pytest dv_harness_tests/` in CI/the
# report -- these two just spot-check the two most vault-adjacent paths.)

def test_preexisting_route_and_store_credential_rejection_unaffected():
    tmp = _tmp()
    try:
        with pytest.raises(ValueError):
            route_and_store(tmp, {"kind": "password", "value": "hunter2"})
    finally:
        _rmtree(tmp)


def test_preexisting_corner_case_library_route_unaffected_by_vault_feature():
    from dv_harness.memory import CornerCaseLibrary
    tmp = _tmp()
    try:
        cfg = {"knowledge_center": {"enabled": False}, "memory": {"vault_path": "", "git_enabled": False}}
        result = route_and_store(tmp, {
            "kind": "corner_case", "verified": True,
            "corner_case": {"corner_id": "cc-1", "protocol": "PCIe", "category": "cdc_timing", "risk_tier": "P2"},
            "resolution": {"test_mapping": "pcie_ltssm_cdc_seq", "semantic_verdict": "TRUE_FAIL",
                           "runtime_evidence_hash": "abc123"},
        }, cfg=cfg)
        assert result["destination"] == "CORNER_CASE_LIBRARY"
        assert "vault_write" not in result  # CCL is explicitly out of this workstream's vault-write scope
        assert CornerCaseLibrary(tmp).get(result["ccl_id"]) is not None
    finally:
        _rmtree(tmp)
