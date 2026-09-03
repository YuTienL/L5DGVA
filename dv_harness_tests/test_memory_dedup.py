"""Tests for dv_harness/memory_dedup.py -- Phase 18 (Knowledge Deduplication)
of the Obsidian+Git/Markdown Hybrid Engineering Memory spec, Workstream 2 of
4.

Writes real notes into a real vault (via memory_vault.FileSystemMarkdownAdapter,
the same one `dv-harness memory add` uses) and classifies fresh candidates
against them -- no mocking of the comparison logic itself.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import memory_vault as mv
from dv_harness import memory_dedup as dedup


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _provider(tmp: Path):
    vault_path = tmp / ".dv-harness" / "vault"
    return mv.FileSystemMarkdownAdapter(vault_path, git_enabled=False)


def _seed_engineering_note(tmp: Path, protocol="USB", failure="endpoint stall bulk transfer",
                            root_cause="phy clock domain crossing missing sync flop",
                            configuration="high-speed mode, 3 endpoints",
                            error_pattern="UVM_ERROR timeout waiting for ACK"):
    fs = _provider(tmp)
    fm = {"memory_level": "engineering", "protocol": protocol, "status": "ACTIVE",
          "confidence": "MEDIUM", "failure": failure}
    sections = {"Root Cause": root_cause, "Context": configuration, "Symptom": error_pattern}
    result = fs.create(fm, sections=sections)
    assert result["ok"]
    return result["note_id"]


# --- compute_fingerprint() ---------------------------------------------------

def test_compute_fingerprint_is_order_and_case_insensitive():
    a = dedup.compute_fingerprint({
        "protocol": "USB", "root_cause": "Missing Sync Flop in clock domain",
        "failure_signature": None, "configuration": None, "error_pattern": None,
    })
    b = dedup.compute_fingerprint({
        "protocol": "usb", "root_cause": "clock domain missing flop sync",
        "failure_signature": None, "configuration": None, "error_pattern": None,
    })
    # Same token SET (order/case-insensitive) -> identical normalized string -> identical hash.
    assert a["normalized"]["root_cause"] == b["normalized"]["root_cause"]
    assert a["hash"] == b["hash"]


def test_compute_fingerprint_differs_on_real_content_difference():
    a = dedup.compute_fingerprint({"root_cause": "missing sync flop"})
    b = dedup.compute_fingerprint({"root_cause": "wrong clock divider ratio"})
    assert a["hash"] != b["hash"]
    assert a["tokens"]["root_cause"] != b["tokens"]["root_cause"]


# --- classify_note_candidate(): NEW / DUPLICATE / UPDATE_EXISTING / RELATED --

def test_classifies_as_new_when_vault_is_empty():
    tmp = _tmp()
    try:
        candidate = {"protocol": "USB", "root_cause": "anything", "failure_signature": "anything"}
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] == "NEW"
        assert result["best_match"] is None
    finally:
        _rmtree(tmp)


def test_classifies_as_duplicate_for_an_effectively_identical_claim():
    tmp = _tmp()
    try:
        _seed_engineering_note(tmp)
        candidate = {
            "protocol": "USB", "failure_signature": "endpoint stall bulk transfer",
            "root_cause": "phy clock domain crossing missing sync flop",
            "configuration": "high-speed mode, 3 endpoints",
            "error_pattern": "UVM_ERROR timeout waiting for ACK",
        }
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] == "DUPLICATE"
        assert result["best_match"]["exact_hash_match"] is True
    finally:
        _rmtree(tmp)


def test_classifies_as_update_existing_for_same_root_cause_different_context():
    tmp = _tmp()
    try:
        _seed_engineering_note(tmp)
        # Same root cause (the identifying claim), but a materially different
        # configuration/error signature -- this is the SAME underlying issue
        # showing up under new circumstances, not an unrelated new finding.
        candidate = {
            "protocol": "USB", "failure_signature": "totally different wording here",
            "root_cause": "phy clock domain crossing missing sync flop",
            "configuration": "full-speed mode single endpoint isochronous",
            "error_pattern": "completely different log signature xyz nonmatching",
        }
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] == "UPDATE_EXISTING"
        assert result["best_match"]["per_field_similarity"]["root_cause"] >= dedup.UPDATE_EXISTING_ROOT_CAUSE_THRESHOLD
    finally:
        _rmtree(tmp)


def test_classifies_as_related_for_partial_overlap_different_root_cause():
    tmp = _tmp()
    try:
        _seed_engineering_note(tmp)
        candidate = {
            "protocol": "USB", "failure_signature": "endpoint stall during transfer",  # some word overlap
            "root_cause": "completely unrelated firmware register write ordering bug",
            "configuration": "different config entirely",
            "error_pattern": "different error entirely",
        }
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] in ("RELATED", "NEW")  # depends on exact overlap; must not be DUPLICATE/UPDATE_EXISTING
        assert result["classification"] != "DUPLICATE"
        assert result["classification"] != "UPDATE_EXISTING"
    finally:
        _rmtree(tmp)


def test_different_protocol_is_never_a_match_regardless_of_text_similarity():
    tmp = _tmp()
    try:
        _seed_engineering_note(tmp, protocol="USB")
        candidate = {
            "protocol": "PCIe",  # different protocol -- hard gate
            "failure_signature": "endpoint stall bulk transfer",
            "root_cause": "phy clock domain crossing missing sync flop",
            "configuration": "high-speed mode, 3 endpoints",
            "error_pattern": "UVM_ERROR timeout waiting for ACK",
        }
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] == "NEW"
        assert result["candidate_count_compared"] == 0
    finally:
        _rmtree(tmp)


def test_candidate_with_no_protocol_compares_broadly():
    tmp = _tmp()
    try:
        _seed_engineering_note(tmp, protocol="USB")
        candidate = {
            "protocol": None,
            "failure_signature": "endpoint stall bulk transfer",
            "root_cause": "phy clock domain crossing missing sync flop",
            "configuration": "high-speed mode, 3 endpoints",
            "error_pattern": "UVM_ERROR timeout waiting for ACK",
        }
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["candidate_count_compared"] == 1
        assert result["classification"] == "DUPLICATE"
    finally:
        _rmtree(tmp)


def test_organizational_tier_notes_are_also_compared_against():
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        fm = {"memory_level": "organizational", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"}
        sections = {"Root Cause": "phy clock domain crossing missing sync flop", "Context": "org-wide",
                    "Symptom": "stall pattern"}
        assert fs.create(fm, sections=sections)["ok"]

        candidate = {"protocol": "USB", "root_cause": "phy clock domain crossing missing sync flop",
                     "configuration": "org-wide", "error_pattern": "stall pattern"}
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] == "DUPLICATE"
    finally:
        _rmtree(tmp)


def test_working_job_project_tier_notes_are_never_compared_against():
    tmp = _tmp()
    try:
        fs = _provider(tmp)
        fm = {"memory_level": "project", "protocol": "USB", "status": "ACTIVE", "confidence": "MEDIUM"}
        sections = {"Root Cause": "phy clock domain crossing missing sync flop"}
        assert fs.create(fm, sections=sections, folder="06_Agent_Memory/Project")["ok"]

        candidate = {"protocol": "USB", "root_cause": "phy clock domain crossing missing sync flop"}
        result = dedup.classify_note_candidate(tmp, candidate, cfg={})
        assert result["classification"] == "NEW"
        assert result["candidate_count_compared"] == 0
    finally:
        _rmtree(tmp)


def test_exclude_note_id_skips_that_note():
    tmp = _tmp()
    try:
        note_id = _seed_engineering_note(tmp)
        candidate = {"protocol": "USB", "failure_signature": "endpoint stall bulk transfer",
                     "root_cause": "phy clock domain crossing missing sync flop",
                     "configuration": "high-speed mode, 3 endpoints",
                     "error_pattern": "UVM_ERROR timeout waiting for ACK"}
        result = dedup.classify_note_candidate(tmp, candidate, cfg={}, exclude_note_id=note_id)
        assert result["classification"] == "NEW"
        assert result["candidate_count_compared"] == 0
    finally:
        _rmtree(tmp)
