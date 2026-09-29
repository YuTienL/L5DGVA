"""Phase 9 gap closure (2026-09-04, gap-close-obsidian-memory-phase-9-18):
the two closeable gaps the Search Strategy audit found, each proven closed
against real records/notes and real CLI invocations -- never a parse/import
smoke test.

  1. `dv-harness memory search` exposed only --protocol/--tag/--level, while
     FileSystemMarkdownAdapter.search() already accepted exact/property/
     linked_to/confidence/status/project. Those six are now real CLI flags.
  2. MemoryRetriever.search() (the JSON MemoryStore holding the actual
     tier-1..5 records, including Working Memory, which is deliberately never
     mirrored into the vault) supported only protocol/scope/symptoms/text.
     It now also filters on level/confidence/status/arbitrary property.

Tag and wiki-link filters are deliberately absent from MemoryRetriever: a
MemoryStore record carries neither field, so such a filter could only ever
match nothing. Those two stay vault-note concepts, filtered by
memory_vault.FileSystemMarkdownAdapter.search() -- covered by
dv_harness_tests/test_memory_vault.py.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

import dv_harness.cli as cli_mod
import dv_harness.memory_cli as memory_cli
from dv_harness import memory_vault as memory_vault_mod
from dv_harness.memory import (
    MemoryRetriever,
    MemoryStore,
    PropertyFilterError,
    parse_property_filters,
)


@pytest.fixture()
def tmp_root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    try:
        rc = cli_mod.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _run_memory_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["memory_cli", "--project-root", str(tmp_path)] + args)
    try:
        rc = memory_cli.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _ids(hits):
    return sorted(h["memory"]["memory_id"] for h in hits)


# ===========================================================================
# parse_property_filters -- shared by both CLIs, so they cannot drift
# ===========================================================================

def test_property_filter_parsing_splits_on_the_first_equals_only():
    assert parse_property_filters(["kind=root_cause", "note=a=b"]) == {
        "kind": "root_cause", "note": "a=b",
    }


def test_property_filter_parsing_rejects_an_argument_with_no_equals():
    with pytest.raises(PropertyFilterError):
        parse_property_filters(["kind"])
    with pytest.raises(PropertyFilterError):
        parse_property_filters(["=root_cause"])


# ===========================================================================
# 1. MemoryRetriever structural filters (JSON MemoryStore, all 5 tiers)
# ===========================================================================

def _seed_store(root: Path) -> MemoryStore:
    """Three records that a protocol/text query alone cannot tell apart:
    same protocol, same title tokens, different tier/confidence/kind."""
    store = MemoryStore(root)
    store.add("engineering", {
        "memory_id": "MEM-ENG-HIGH", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "HIGH", "kind": "root_cause", "subsystem": "link_training",
    })
    store.add("working", {
        "memory_id": "MEM-WORK-LOW", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "LOW", "kind": "react_reasoning_step", "subsystem": "link_training",
    })
    store.add("project", {
        "memory_id": "MEM-PROJ-HIGH", "title": "USB2 LFPS polling timeout",
        "protocol": "USB2", "root_cause": "missing sync flop on lfps_detect",
        "confidence": "HIGH", "kind": "topology_note", "subsystem": "phy",
    })
    return store


def test_without_filters_all_three_tiers_are_returned_unchanged(tmp_root):
    """Baseline: the pre-existing protocol/text behavior is untouched."""
    store = _seed_store(tmp_root)
    hits = MemoryRetriever(store).search({"protocol": "USB2", "text": "lfps polling timeout"})
    assert _ids(hits) == ["MEM-ENG-HIGH", "MEM-PROJ-HIGH", "MEM-WORK-LOW"]


def test_level_filter_restricts_to_the_named_tiers(tmp_root):
    store = _seed_store(tmp_root)
    r = MemoryRetriever(store)
    assert _ids(r.search({"protocol": "USB2", "level": "working"})) == ["MEM-WORK-LOW"]
    assert _ids(r.search({"protocol": "USB2", "level": ["engineering", "project"]})) == [
        "MEM-ENG-HIGH", "MEM-PROJ-HIGH",
    ]


def test_confidence_filters_rather_than_only_ranking(tmp_root):
    """Before this change `confidence` only added to the score, so a LOW
    record still came back for a HIGH-only question."""
    store = _seed_store(tmp_root)
    hits = MemoryRetriever(store).search({"protocol": "USB2", "confidence": "HIGH"})
    assert _ids(hits) == ["MEM-ENG-HIGH", "MEM-PROJ-HIGH"]


def test_arbitrary_property_filter_reads_fields_index_json_does_not_carry(tmp_root):
    """`kind`/`subsystem` are on the record file only -- _index_row() persists
    neither -- so this proves the record-file fallback, not just an index scan."""
    store = _seed_store(tmp_root)
    index_row_keys = set(store._index()[0])
    assert "kind" not in index_row_keys and "subsystem" not in index_row_keys

    r = MemoryRetriever(store)
    assert _ids(r.search({"protocol": "USB2", "property": {"kind": "root_cause"}})) == ["MEM-ENG-HIGH"]
    assert _ids(r.search({"protocol": "USB2", "property": {"subsystem": "link_training"}})) == [
        "MEM-ENG-HIGH", "MEM-WORK-LOW",
    ]
    assert r.search({"protocol": "USB2", "property": {"subsystem": "nonexistent"}}) == []


def test_property_filter_matches_a_member_of_a_list_valued_field(tmp_root):
    store = MemoryStore(tmp_root)
    store.add("engineering", {
        "memory_id": "MEM-LIST", "title": "USB2 timeout", "protocol": "USB2",
        "symptoms": ["timeout", "lfps"],
    })
    hits = MemoryRetriever(store).search({"protocol": "USB2", "property": {"symptoms": "lfps"}})
    assert _ids(hits) == ["MEM-LIST"]


def test_status_defaults_to_active_only_but_is_overridable(tmp_root):
    from dv_harness.memory import MemoryGC

    store = _seed_store(tmp_root)
    MemoryGC(store).deprecate("MEM-WORK-LOW", "superseded by MEM-ENG-HIGH")
    r = MemoryRetriever(store)

    # Default: the deprecated record is gone (pre-existing behavior).
    assert "MEM-WORK-LOW" not in _ids(r.search({"protocol": "USB2"}))
    # Explicit status: reachable again, and only it.
    assert _ids(r.search({"protocol": "USB2", "status": "DEPRECATED"})) == ["MEM-WORK-LOW"]
    # ANY sentinel: every status at once.
    assert _ids(r.search({"protocol": "USB2", "status": "ANY"})) == [
        "MEM-ENG-HIGH", "MEM-PROJ-HIGH", "MEM-WORK-LOW",
    ]


def test_a_structural_filter_alone_is_enough_to_clear_the_relevance_floor(tmp_root):
    """"list every engineering-tier record" carries no protocol/scope/symptom/
    text overlap at all, so before this change the finding-I2 relevance floor
    emptied it out."""
    store = _seed_store(tmp_root)
    hits = MemoryRetriever(store).search({"level": "engineering"})
    assert _ids(hits) == ["MEM-ENG-HIGH"]


def test_the_relevance_floor_still_rejects_an_unfiltered_zero_overlap_query(tmp_root):
    """The finding-I2 guarantee must survive: with no structural filter and no
    query overlap, recency/confidence alone must still not manufacture a hit."""
    _seed_store(tmp_root)
    store = MemoryStore(tmp_root)
    assert MemoryRetriever(store).search({"protocol": "ETHERNET", "text": "lsf queue drain"}) == []


# ===========================================================================
# 2. `python -m dv_harness.memory_cli search` exposes the same filters
# ===========================================================================

def test_memory_cli_search_applies_level_confidence_and_property_flags(monkeypatch, tmp_root, capsys):
    _seed_store(tmp_root)
    rc, out = _run_memory_cli(monkeypatch, tmp_root,
                               ["search", "--protocol", "USB2", "--level", "engineering",
                                "--confidence", "HIGH", "--property", "kind=root_cause"], capsys)
    assert rc == 0
    assert [h["memory"]["memory_id"] for h in json.loads(out)] == ["MEM-ENG-HIGH"]


def test_memory_cli_search_status_flag_reaches_a_deprecated_record(monkeypatch, tmp_root, capsys):
    from dv_harness.memory import MemoryGC

    MemoryGC(_seed_store(tmp_root)).deprecate("MEM-WORK-LOW", "superseded")
    rc, out = _run_memory_cli(monkeypatch, tmp_root,
                               ["search", "--protocol", "USB2", "--status", "DEPRECATED"], capsys)
    assert rc == 0
    assert [h["memory"]["memory_id"] for h in json.loads(out)] == ["MEM-WORK-LOW"]


def test_memory_cli_search_rejects_a_malformed_property_flag(monkeypatch, tmp_root, capsys):
    _seed_store(tmp_root)
    rc, out = _run_memory_cli(monkeypatch, tmp_root,
                               ["search", "--protocol", "USB2", "--property", "kind"], capsys)
    assert rc == 2
    assert json.loads(out)["error"] == "BAD_PROPERTY_FILTER"


# ===========================================================================
# 3. `dv-harness memory search` exposes every vault-adapter filter
# ===========================================================================

def _add_note(monkeypatch, tmp_root, capsys, **kw):
    args = ["memory", "add", "--protocol", kw.get("protocol", "USB2"),
            "--failure", kw["failure"], "--root-cause", kw["root_cause"],
            "--confidence", kw.get("confidence", "MEDIUM"),
            "--status", kw.get("status", "ACTIVE")]
    for tag in kw.get("tags", []):
        args += ["--tag", tag]
    if kw.get("force"):
        args += ["--force"]
    rc, out = _run_cli(monkeypatch, tmp_root, args, capsys)
    assert rc == 0, out
    return json.loads(out)["note_id"]


def _search_ids(monkeypatch, tmp_root, capsys, args):
    rc, out = _run_cli(monkeypatch, tmp_root, ["memory", "search"] + args, capsys)
    assert rc in (0, None), out
    return sorted(r["note_id"] for r in json.loads(out)["results"])


def test_memory_search_confidence_and_status_flags_filter_real_notes(monkeypatch, tmp_root, capsys):
    high = _add_note(monkeypatch, tmp_root, capsys, failure="lfps polling stall",
                      root_cause="missing sync flop on lfps_detect", confidence="HIGH")
    low = _add_note(monkeypatch, tmp_root, capsys, failure="ep0 setup underrun",
                     root_cause="prefetch guard absent in ep0 fifo", confidence="LOW",
                     status="DEPRECATED")

    assert _search_ids(monkeypatch, tmp_root, capsys, ["--confidence", "HIGH"]) == [high]
    assert _search_ids(monkeypatch, tmp_root, capsys, ["--confidence", "LOW"]) == [low]
    assert _search_ids(monkeypatch, tmp_root, capsys, ["--status", "DEPRECATED"]) == [low]
    assert _search_ids(monkeypatch, tmp_root, capsys, ["--status", "ACTIVE"]) == [high]


def test_memory_search_exact_flag_matches_a_literal_substring(monkeypatch, tmp_root, capsys):
    target = _add_note(monkeypatch, tmp_root, capsys, failure="uvm_error at lfps_detect_sync",
                        root_cause="missing sync flop on lfps_detect", confidence="HIGH")
    _add_note(monkeypatch, tmp_root, capsys, failure="ep0 setup underrun",
               root_cause="prefetch guard absent in ep0 fifo", confidence="HIGH")

    assert _search_ids(monkeypatch, tmp_root, capsys, ["--exact", "lfps_detect_sync"]) == [target]
    assert _search_ids(monkeypatch, tmp_root, capsys, ["--exact", "no_such_signal"]) == []


def test_memory_search_property_flag_is_repeatable_and_anded(monkeypatch, tmp_root, capsys):
    usb = _add_note(monkeypatch, tmp_root, capsys, protocol="USB2", failure="lfps polling stall",
                     root_cause="missing sync flop on lfps_detect", confidence="HIGH")
    _add_note(monkeypatch, tmp_root, capsys, protocol="PCIE", failure="ltssm recovery loop",
               root_cause="eq phase 2 preset never applied", confidence="LOW")

    assert _search_ids(monkeypatch, tmp_root, capsys,
                        ["--property", "protocol=USB2", "--property", "confidence=HIGH"]) == [usb]
    assert _search_ids(monkeypatch, tmp_root, capsys,
                        ["--property", "protocol=USB2", "--property", "confidence=LOW"]) == []


def test_memory_search_rejects_a_malformed_property_flag(monkeypatch, tmp_root, capsys):
    rc, out = _run_cli(monkeypatch, tmp_root, ["memory", "search", "--property", "protocol"], capsys)
    assert rc == 2
    assert json.loads(out)["error"] == "BAD_PROPERTY_FILTER"


def test_memory_search_linked_to_flag_traverses_a_real_wiki_link(monkeypatch, tmp_root, capsys):
    """Written through the same provider the CLI reads, then reached from the
    CLI by --linked-to -- previously Python-API-only."""
    from dv_harness import memory_vault as mv

    target = _add_note(monkeypatch, tmp_root, capsys, failure="lfps polling stall",
                        root_cause="missing sync flop on lfps_detect", confidence="HIGH")
    cfg = json.loads((tmp_root / ".dv-harness" / "config.json").read_text(encoding="utf-8"))
    provider = mv.get_active_provider(tmp_root, cfg)
    linker = provider.create(
        {"memory_level": "engineering", "protocol": "USB2", "status": "ACTIVE",
         "confidence": "MEDIUM", "failure": "ep0 setup underrun"},
        sections={"Related Knowledge": f"Supersedes [[{target}]]."},
    )["note_id"]

    assert _search_ids(monkeypatch, tmp_root, capsys, ["--linked-to", target]) == [linker]
    assert _search_ids(monkeypatch, tmp_root, capsys, ["--linked-to", linker]) == []


def test_memory_search_project_flag_filters_on_the_project_frontmatter_field(monkeypatch, tmp_root, capsys):
    from dv_harness import memory_vault as mv

    _run_cli(monkeypatch, tmp_root, ["memory", "status"], capsys)
    cfg = json.loads((tmp_root / ".dv-harness" / "config.json").read_text(encoding="utf-8"))
    provider = mv.get_active_provider(tmp_root, cfg)
    mine = provider.create({"memory_level": "engineering", "protocol": "USB2", "status": "ACTIVE",
                            "confidence": "HIGH", "project": "usb31_dev_uvm",
                            "failure": "lfps polling stall"})["note_id"]
    provider.create({"memory_level": "engineering", "protocol": "USB2", "status": "ACTIVE",
                     "confidence": "HIGH", "project": "pcie_gen5_uvm",
                     "failure": "ltssm recovery loop"})

    assert _search_ids(monkeypatch, tmp_root, capsys, ["--project", "usb31_dev_uvm"]) == [mine]


# ===========================================================================
# 4. The `rg` prefilter is a SPEED optimization only -- never a filter
#
# FileSystemMarkdownAdapter.search() optionally narrows which note files it
# parses with `rg -l`. That is only sound while the prefilter's term is a
# MANDATORY constraint on the final result. Two real query shapes broke that
# and silently returned fewer notes on any machine that happens to have
# ripgrep installed (which is the common case, including this repo's own dev
# environment) than on one that does not:
#
#   - a multi-word free-text query, which the Python scorer matches by TOKEN
#     OVERLAP but the prefilter demanded as one contiguous literal phrase;
#   - free text combined with a structural filter (tag/property/protocol/...),
#     where a note matching only the structural filter still scores above the
#     relevance floor and must be returned.
#
# Each test below asserts rg-present and rg-absent results are EQUAL, so the
# accelerator can never again change what a search means. The pre-existing
# single-token coverage in test_memory_vault.py
# (test_filesystem_adapter_search_degrades_correctly_without_rg) hits the one
# shape that never diverged, which is why this went unnoticed.
# ===========================================================================

def _vault(tmp_root):
    from dv_harness import memory_vault as mv
    return mv.FileSystemMarkdownAdapter(tmp_root / "vault", git_enabled=False)


def _note_fm(note_id, protocol="USB3"):
    return {"id": note_id, "memory_level": "engineering", "protocol": protocol,
            "confidence": "HIGH", "status": "ACTIVE", "tags": [protocol.lower()],
            "verified": True}


def _both_ways(fs, query):
    """Same query, run with rg available and with it forced unavailable."""
    from unittest.mock import patch

    with_rg = sorted(r["note_id"] for r in fs.search(query)["results"])
    with patch("dv_harness.memory_vault.shutil.which", return_value=None):
        without_rg = sorted(r["note_id"] for r in fs.search(query)["results"])
    return with_rg, without_rg


@pytest.fixture()
def two_notes(tmp_root):
    fs = _vault(tmp_root)
    fs.create(_note_fm("MEM-A"), sections={"Root Cause": "lfps underrun on the receiver"})
    fs.create(_note_fm("MEM-B"), sections={"Root Cause": "descriptor fetch stalled"})
    return fs


def test_multi_word_text_query_matches_on_token_overlap_not_a_literal_phrase(two_notes):
    # No note contains the phrase "underrun descriptor"; each contains one of
    # the two tokens, so token-overlap scoring must return both.
    with_rg, without_rg = _both_ways(two_notes, {"text": "underrun descriptor"})
    assert with_rg == without_rg == ["MEM-A", "MEM-B"]


def test_text_combined_with_a_property_filter_does_not_drop_filter_only_matches(two_notes):
    # Both notes are protocol USB3, so both clear the relevance floor on the
    # structural filter alone; "underrun" only ranks MEM-A higher.
    with_rg, without_rg = _both_ways(two_notes, {"text": "underrun", "protocol": "USB3"})
    assert with_rg == without_rg == ["MEM-A", "MEM-B"]


def test_text_combined_with_a_tag_filter_does_not_drop_filter_only_matches(two_notes):
    with_rg, without_rg = _both_ways(two_notes, {"text": "underrun", "tag": "usb3"})
    assert with_rg == without_rg == ["MEM-A", "MEM-B"]


def test_text_combined_with_a_linked_to_filter_does_not_drop_filter_only_matches(tmp_root):
    fs = _vault(tmp_root)
    fs.create(_note_fm("MEM-TARGET"), sections={"Root Cause": "lfps underrun on the receiver"})
    fs.create(_note_fm("MEM-LINKER"),
              sections={"Related Knowledge": "Supersedes [[MEM-TARGET]]."})

    # MEM-LINKER satisfies --linked-to but contains none of the query tokens.
    with_rg, without_rg = _both_ways(fs, {"text": "underrun", "linked_to": "MEM-TARGET"})
    assert with_rg == without_rg == ["MEM-LINKER"]


def test_single_token_text_query_still_narrows_and_agrees_both_ways(two_notes):
    # The shape that always worked -- kept so the fix cannot regress it into
    # "prefilter nothing, ever", which would preserve correctness by throwing
    # the accelerator away entirely.
    with_rg, without_rg = _both_ways(two_notes, {"text": "underrun"})
    assert with_rg == without_rg == ["MEM-A"]


def test_exact_query_still_narrows_and_agrees_both_ways(two_notes):
    with_rg, without_rg = _both_ways(two_notes, {"exact": "lfps underrun"})
    assert with_rg == without_rg == ["MEM-A"]


def test_exact_query_prefilter_survives_a_case_difference(two_notes):
    # The prefilter runs `rg -i` while the Python check is case-SENSITIVE, so
    # the prefilter is deliberately over-inclusive and Python still rejects.
    with_rg, without_rg = _both_ways(two_notes, {"exact": "LFPS underrun"})
    assert with_rg == without_rg == []


def test_stopword_only_text_query_agrees_both_ways(two_notes):
    # "the on" tokenizes to nothing, so no note can clear the relevance floor.
    with_rg, without_rg = _both_ways(two_notes, {"text": "the on"})
    assert with_rg == without_rg == []


def test_the_rg_prefilter_is_actually_exercised_when_it_is_sound(tmp_root, monkeypatch):
    """Proves the accelerator is still USED for a bare multi-token text query
    -- i.e. the fix narrows the candidate set rather than silently disabling
    rg, which the result-parity tests above alone could not distinguish."""
    fs = _vault(tmp_root)
    fs.create(_note_fm("MEM-A"), sections={"Root Cause": "lfps underrun on the receiver"})
    fs.create(_note_fm("MEM-B"), sections={"Root Cause": "descriptor fetch stalled"})
    fs.create(_note_fm("MEM-C"), sections={"Root Cause": "entirely unrelated content"})

    parsed = []
    real_parse = memory_vault_mod.parse_note_markdown
    monkeypatch.setattr(memory_vault_mod, "parse_note_markdown",
                        lambda text: (parsed.append(text), real_parse(text))[1])

    fs.search({"text": "underrun descriptor"})
    assert len(parsed) == 2, "rg should have excluded MEM-C from the parsed candidate set"
