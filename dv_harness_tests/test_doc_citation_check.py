# dv_harness_tests/test_doc_citation_check.py
"""Proves doc_citation_check really detects citation drift (not just that it
parses), and holds the 5 Phase-24 memory docs at zero drift."""
from pathlib import Path

import pytest

from dv_harness.doc_citation_check import (
    DRIFT,
    MEMORY_DOCS,
    MISSING_SOURCE,
    OK,
    OUT_OF_RANGE,
    UNVERIFIABLE,
    check_docs,
    collect_definitions,
    context_symbols,
    main,
    parse_citations,
)

ROOT = Path(__file__).resolve().parents[1]

SOURCE = """\
from __future__ import annotations

MEMORY_LEVELS = ["working", "job"]


def route_and_store(root, record, cfg=None):
    return {}


class MemoryStore:
    def add(self, level, memory):
        return memory


class CornerCaseLibrary:
    def add(self, record):
        return record
"""
# MEMORY_LEVELS:3  route_and_store:6  MemoryStore:10  MemoryStore.add:11
# CornerCaseLibrary:15  CornerCaseLibrary.add:16


@pytest.fixture()
def check(tmp_path):
    """Build a throwaway repo holding SOURCE, and return check(doc_body)."""
    (tmp_path / "dv_harness").mkdir()
    (tmp_path / "dv_harness" / "sample.py").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "docs").mkdir()

    def _check(body, expect_count=1):
        doc = tmp_path / "docs" / "D.md"
        doc.write_text(body, encoding="utf-8")
        results = check_docs(tmp_path, [doc])
        assert len(results) == expect_count
        return results[0] if expect_count == 1 else results

    return _check


def test_correct_citation_passes(check):
    r = check("`route_and_store(root, record, cfg)` (`sample.py:6`) is the entry point.")
    assert r.verdict == OK
    assert r.matched_symbols == ["route_and_store"]


def test_drifted_citation_is_caught_and_reports_the_real_line(check):
    r = check("`route_and_store(root, record, cfg)` (`sample.py:12`) is the entry point.")
    assert r.verdict == DRIFT
    assert r.expected_lines == [6]
    assert "really at line 6" in r.render()


def test_drift_of_one_line_is_caught(check):
    """An off-by-one is the drift that actually happens -- one import or
    decorator added above the def -- so it must not be tolerated."""
    assert check("`route_and_store` (`sample.py:7`) routes.").verdict == DRIFT


def test_module_level_constant_citation(check):
    good = check("`MEMORY_LEVELS = [...]` (`sample.py:3`) lists the tiers.")
    bad = check("`MEMORY_LEVELS = [...]` (`sample.py:6`) lists the tiers.")
    assert (good.verdict, bad.verdict) == (OK, DRIFT)
    assert bad.expected_lines == [3]


def test_line_range_citation_passes_when_the_definition_is_inside_it(check):
    inside = check("`MemoryStore.add()` (`sample.py:10-13`) writes the record.")
    outside = check("`MemoryStore.add()` (`sample.py:2-6`) writes the record.")
    assert (inside.verdict, outside.verdict) == (OK, DRIFT)


def test_ambiguous_method_name_does_not_wave_a_wrong_citation_through(check):
    """`add` is defined on two classes here. A citation naming
    CornerCaseLibrary must not be satisfied by MemoryStore.add's line."""
    r = check("`CornerCaseLibrary.add()` (`sample.py:11`) is a separate store.")
    assert r.verdict == DRIFT
    assert r.expected_lines == [16]


def test_class_named_in_a_heading_qualifies_a_bare_method_mention(check):
    body = "## 1. MemoryStore record\n\nFields `add()` (`sample.py:11`) always fills in:\n"
    assert check(body).verdict == OK


def test_citation_with_no_nameable_symbol_is_unverifiable_not_ok(check):
    assert check("Some prose with no symbol at all (`sample.py:6`).").verdict == UNVERIFIABLE


def test_missing_source_and_out_of_range_are_distinct_verdicts(check):
    assert check("`route_and_store` (`nope.py:6`) routes.").verdict == MISSING_SOURCE
    assert check("`route_and_store` (`sample.py:9000`) routes.").verdict == OUT_OF_RANGE


def test_citations_inside_a_fenced_code_block_are_not_checked(check):
    check("```\n`sample.py:9999` route_and_store\n```\n", expect_count=0)


def test_path_qualified_reference_resolves(check):
    assert check("`route_and_store` (`dv_harness/sample.py:6`) routes.").verdict == OK


def test_collect_definitions_registers_ambiguous_methods_only_when_qualified():
    defs = collect_definitions(SOURCE)
    assert defs["MemoryStore.add"] == [11]
    assert defs["CornerCaseLibrary.add"] == [16]
    assert "add" not in defs, "ambiguous bare method name must not be citable"
    assert defs["route_and_store"] == [6]
    assert defs["MEMORY_LEVELS"] == [3]


def test_context_symbols_expands_dotted_chains():
    tokens = context_symbols("`dv_harness.memory_router.route_memory(record)`")
    assert {"route_memory", "memory_router.route_memory"} <= tokens


def test_parse_citations_records_the_doc_line():
    cites = parse_citations("intro\n\n(`sample.py:6`)\n", "D.md")
    assert (cites[0].doc_line, cites[0].start, cites[0].end) == (3, 6, 6)


# --- the real Phase 24 docs --------------------------------------------------

def test_all_five_phase24_memory_docs_exist():
    for rel in MEMORY_DOCS:
        assert (ROOT / rel).is_file(), f"{rel} missing"


def test_real_memory_docs_have_no_drifted_citations():
    results = check_docs(ROOT, [ROOT / rel for rel in MEMORY_DOCS])
    assert results, "expected the memory docs to carry file:line citations"
    bad = [r.render() for r in results if r.verdict != OK]
    assert not bad, "stale citations in the memory docs:\n" + "\n".join(bad)


def test_memory_docs_checker_cli_exits_zero():
    assert main(["--memory-docs"]) == 0
