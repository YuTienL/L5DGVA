"""Tests for dv_harness/design_source_inventory.py -- the design-source
registry table (source_id/type/version/hash/authority/status/last_checked)
and the 10-kind DISCOVERY_ORDER table.

Real fixtures only: real temp files/directories hashed for real with
hashlib, and real `source_authority.AUTHORITY_ORDER` tiers looked up through
its own public API (never re-derived). No mocks."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dv_harness import source_authority
from dv_harness.design_source_inventory import (
    DesignSourceInventoryError,
    STATUS_CURRENT, STATUS_STALE, STATUS_SUPERSEDED,
    STATUS_NOT_AVAILABLE, STATUS_UNKNOWN,
    AUTHORITY_RESOLVED, AUTHORITY_NOT_APPLICABLE,
    DISCOVERY_ORDER, normalize_discovery_kind, discovery_check_order,
    SourceEntry, compute_source_hash, evaluate_source, build_source_registry,
)


FIXED_NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DISCOVERY_ORDER table
# ---------------------------------------------------------------------------

def test_discovery_order_has_exactly_ten_distinct_kinds_in_fixed_order():
    assert len(DISCOVERY_ORDER) == 10
    ids = [k.id for k in DISCOVERY_ORDER]
    assert len(set(ids)) == 10
    assert ids == [
        "repo_files_on_disk", "existing_uvm_environment", "build_scripts_makefile",
        "rtl_phy_source", "register_files", "specs_datasheets", "vip_examples",
        "regression_lists", "git_history", "ask_user",
    ]
    # 1-based, strictly increasing, matching the AuthoritySource.rank convention.
    assert [k.rank for k in DISCOVERY_ORDER] == list(range(1, 11))


def test_normalize_discovery_kind_accepts_alias_and_label():
    assert normalize_discovery_kind("Makefile") == "build_scripts_makefile"
    assert normalize_discovery_kind("VIP examples") == "vip_examples"
    assert normalize_discovery_kind("ask the user") == "ask_user"


def test_normalize_discovery_kind_rejects_unknown_name():
    with pytest.raises(DesignSourceInventoryError) as exc:
        normalize_discovery_kind("psychic_intuition")
    assert exc.value.reason == "UNKNOWN_DISCOVERY_KIND"


def test_discovery_check_order_filters_and_reorders_regardless_of_input_order():
    # Deliberately out-of-order and using mixed alias/canonical spellings.
    available = ["git_history", "rtl_phy_source", "Makefile", "ask_user"]
    result = discovery_check_order("reset_polarity", available)
    assert result["fact_name"] == "reset_polarity"
    assert result["check_order"] == [
        "build_scripts_makefile", "rtl_phy_source", "git_history", "ask_user",
    ]
    assert "repo_files_on_disk" in result["unavailable_kinds"]
    assert "register_files" in result["unavailable_kinds"]


def test_discovery_check_order_rejects_empty_fact_name():
    with pytest.raises(DesignSourceInventoryError) as exc:
        discovery_check_order("   ", ["git_history"])
    assert exc.value.reason == "FACT_NAME_MUST_BE_STATED"


def test_discovery_check_order_rejects_unknown_available_kind():
    with pytest.raises(DesignSourceInventoryError) as exc:
        discovery_check_order("some_fact", ["git_history", "tarot_cards"])
    assert exc.value.reason == "UNKNOWN_DISCOVERY_KIND"


def test_discovery_order_is_a_distinct_object_from_source_authority_order():
    # The two orders must never be accidentally aliased to the same list --
    # they are a different axis by this module's own stated design.
    discovery_ids = {k.id for k in DISCOVERY_ORDER}
    authority_ids = {s.id for s in source_authority.AUTHORITY_ORDER}
    assert discovery_ids.isdisjoint(authority_ids)


# ---------------------------------------------------------------------------
# Authority resolution (reused BY IMPORT from source_authority.py)
# ---------------------------------------------------------------------------

def test_authority_resolution_matches_source_authority_directly():
    entry = SourceEntry(source_id="s1", type="rtl_phy_source",
                         authority_hint="dut_rtl")
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["authority"]["status"] == AUTHORITY_RESOLVED
    assert result["authority"]["rank"] == source_authority.authority_rank("dut_rtl")
    assert result["authority"]["id"] == "dut_rtl"


def test_authority_resolution_accepts_source_authority_alias():
    # "regfile" is a real alias registered on source_authority's register_file tier.
    entry = SourceEntry(source_id="s2", type="register_files",
                         authority_hint="regfile")
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["authority"]["status"] == AUTHORITY_RESOLVED
    assert result["authority"]["id"] == "register_file"
    assert result["authority"]["rank"] == 4


def test_authority_not_applicable_when_no_hint_supplied():
    entry = SourceEntry(source_id="s3", type="ask_user")
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["authority"]["status"] == AUTHORITY_NOT_APPLICABLE
    assert result["authority"]["rank"] is None
    assert "NO_AUTHORITY_HINT_SUPPLIED" in result["authority"]["reason"]


def test_authority_not_applicable_for_unresolvable_hint_never_guesses_a_tier():
    entry = SourceEntry(source_id="s4", type="git_history",
                         authority_hint="totally_bogus_hint_xyz")
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["authority"]["status"] == AUTHORITY_NOT_APPLICABLE
    assert result["authority"]["rank"] is None
    assert "UNRESOLVED_AUTHORITY_HINT" in result["authority"]["reason"]


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def test_compute_source_hash_matches_hashlib_for_a_real_file(tmp_path):
    f = tmp_path / "regmap.json"
    f.write_text('{"reg": "CTRL"}', encoding="utf-8")
    result = compute_source_hash(f)
    assert result["status"] == "CAPTURED"
    assert result["hash"] == hashlib.sha256(f.read_bytes()).hexdigest()


def test_compute_source_hash_not_available_for_missing_path(tmp_path):
    missing = tmp_path / "does_not_exist.v"
    result = compute_source_hash(missing)
    assert result["status"] == STATUS_NOT_AVAILABLE
    assert result["hash"] is None
    assert "PATH_DOES_NOT_EXIST" in result["reason"]


def test_compute_source_hash_not_available_for_no_path():
    result = compute_source_hash(None)
    assert result["status"] == STATUS_NOT_AVAILABLE
    assert result["hash"] is None


def test_compute_source_hash_for_directory_changes_when_a_file_is_added(tmp_path):
    d = tmp_path / "vip_example"
    d.mkdir()
    (d / "seq.sv").write_text("class seq;", encoding="utf-8")
    before = compute_source_hash(d)["hash"]
    (d / "extra.sv").write_text("class extra;", encoding="utf-8")
    after = compute_source_hash(d)["hash"]
    assert before != after


# ---------------------------------------------------------------------------
# Freshness/staleness derivation (positive path + negative controls)
# ---------------------------------------------------------------------------

def test_status_current_when_hash_matches_recorded_snapshot(tmp_path):
    f = tmp_path / "ctrl_regs.rdl"
    f.write_text("reg CTRL { field EN; }", encoding="utf-8")
    recorded = compute_source_hash(f)["hash"]
    entry = SourceEntry(source_id="regs", type="register_files", path=str(f),
                         authority_hint="register_file", recorded_hash=recorded)
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["status"] == STATUS_CURRENT
    assert result["last_checked"] == FIXED_NOW.isoformat()
    assert result["hash"] == recorded


def test_status_stale_when_content_mutated_since_recorded_snapshot(tmp_path):
    """Negative control: a source whose bytes changed since the last
    recorded hash must NEVER read as CURRENT."""
    f = tmp_path / "ctrl_regs.rdl"
    f.write_text("reg CTRL { field EN; }", encoding="utf-8")
    recorded = compute_source_hash(f)["hash"]
    f.write_text("reg CTRL { field EN; field RST; }", encoding="utf-8")  # mutated
    entry = SourceEntry(source_id="regs", type="register_files", path=str(f),
                         recorded_hash=recorded)
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["status"] == STATUS_STALE
    assert result["status"] != STATUS_CURRENT
    assert "HASH_CHANGED_SINCE_LAST_CHECK" in result["reasons"][0]


def test_status_unknown_without_recorded_hash_never_defaults_to_current(tmp_path):
    """Negative control: absent baseline evidence must read as UNKNOWN, not
    a silently-guessed CURRENT."""
    f = tmp_path / "spec.pdf.txt"
    f.write_text("datasheet contents", encoding="utf-8")
    entry = SourceEntry(source_id="ds1", type="specs_datasheets", path=str(f))
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["status"] == STATUS_UNKNOWN
    assert result["status"] != STATUS_CURRENT
    assert "NO_RECORDED_HASH" in result["reasons"][0]


def test_status_not_available_for_missing_path_never_defaults_to_stale_or_current(tmp_path):
    """Negative control: a source registered but not actually present on
    disk must never silently pass as CURRENT nor be conflated with STALE."""
    entry = SourceEntry(source_id="missing1", type="rtl_phy_source",
                         path=str(tmp_path / "nope.v"), recorded_hash="deadbeef")
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["status"] == STATUS_NOT_AVAILABLE
    assert result["status"] not in (STATUS_CURRENT, STATUS_STALE)


def test_status_superseded_overrides_a_matching_hash(tmp_path):
    """Negative control: a source deliberately marked superseded must report
    SUPERSEDED even when its content still matches the last recorded hash --
    retirement is a fact about the source, not maskable by a hash match."""
    f = tmp_path / "old_regmap.json"
    f.write_text('{"reg": "CTRL_V1"}', encoding="utf-8")
    recorded = compute_source_hash(f)["hash"]
    entry = SourceEntry(source_id="regs_v1", type="register_files", path=str(f),
                         recorded_hash=recorded, superseded_by="regs_v2")
    result = evaluate_source(entry, now=FIXED_NOW)
    assert result["status"] == STATUS_SUPERSEDED
    assert result["status"] != STATUS_CURRENT
    assert "SUPERSEDED_BY: regs_v2" in result["reasons"][0]


def test_evaluate_source_accepts_plain_dict_duck_typed_input(tmp_path):
    f = tmp_path / "dut.v"
    f.write_text("module dut; endmodule", encoding="utf-8")
    row = evaluate_source({"source_id": "dut", "type": "rtl_phy_source",
                            "path": str(f), "authority_hint": "rtl"}, now=FIXED_NOW)
    assert row["source_id"] == "dut"
    assert row["authority"]["id"] == "dut_rtl"


def test_source_entry_requires_source_id():
    with pytest.raises(DesignSourceInventoryError) as exc:
        SourceEntry(source_id="  ", type="rtl_phy_source")
    assert exc.value.reason == "SOURCE_ID_MUST_BE_STATED"


def test_source_entry_requires_type():
    with pytest.raises(DesignSourceInventoryError) as exc:
        SourceEntry(source_id="x1", type="")
    assert exc.value.reason == "SOURCE_TYPE_MUST_BE_STATED"


# ---------------------------------------------------------------------------
# Whole-registry assembly
# ---------------------------------------------------------------------------

def test_build_source_registry_summary_counts_every_status(tmp_path):
    current_f = tmp_path / "cur.v"
    current_f.write_text("module cur; endmodule", encoding="utf-8")
    stale_f = tmp_path / "stale.v"
    stale_f.write_text("module stale_v1; endmodule", encoding="utf-8")
    stale_recorded = compute_source_hash(stale_f)["hash"]
    stale_f.write_text("module stale_v2; endmodule", encoding="utf-8")

    entries = [
        SourceEntry(source_id="a", type="rtl_phy_source", path=str(current_f),
                    recorded_hash=compute_source_hash(current_f)["hash"]),
        SourceEntry(source_id="b", type="rtl_phy_source", path=str(stale_f),
                    recorded_hash=stale_recorded),
        SourceEntry(source_id="c", type="specs_datasheets",
                    path=str(tmp_path / "nope.pdf")),
        SourceEntry(source_id="d", type="specs_datasheets",
                    path=str(current_f)),  # no recorded_hash -> UNKNOWN
        SourceEntry(source_id="e", type="register_files", path=str(current_f),
                    recorded_hash=compute_source_hash(current_f)["hash"],
                    superseded_by="e2"),
    ]
    registry = build_source_registry(entries, now=FIXED_NOW)
    assert registry["source_count"] == 5
    assert registry["summary"][STATUS_CURRENT] == 1
    assert registry["summary"][STATUS_STALE] == 1
    assert registry["summary"][STATUS_NOT_AVAILABLE] == 1
    assert registry["summary"][STATUS_UNKNOWN] == 1
    assert registry["summary"][STATUS_SUPERSEDED] == 1
    ids_by_status = {row["source_id"]: row["status"] for row in registry["sources"]}
    assert ids_by_status == {
        "a": STATUS_CURRENT, "b": STATUS_STALE, "c": STATUS_NOT_AVAILABLE,
        "d": STATUS_UNKNOWN, "e": STATUS_SUPERSEDED,
    }
