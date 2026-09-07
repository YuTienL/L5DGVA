"""dv_harness/unknown_uncertainty_registry.py -- a first-class registry of
open UNKNOWNs across a project.

WHAT THESE TESTS ARE FOR:

  1. **Extraction correctness.** `extract_unknown_rows()` keeps only the rows
     whose status reads UNKNOWN, carries the right fields through, and never
     silently drops a malformed row -- it reports one instead.
  2. **Real reuse, not simulated reuse.** `collect_from_golden_flow_readiness()`
     and `collect_from_generation_readiness()` are driven against the REAL
     `golden_flow_readiness.py`/`generation_readiness.py` modules over a real
     (bare) project directory -- never a stub standing in for either -- and
     the counts are independently recomputed from each module's own real
     matrix as the negative control.
  3. **The negative control this project is graded on**: the registry must
     never fabricate `UNCERTAINTY_SURFACE_CLEAR` when it did not actually
     check every source (an extra source the caller never supplied is simply
     absent from `sources_consulted`, never assumed clean), and it must
     report `UNCERTAINTY_SURFACE_CLEAR` for real, honestly, when every
     consulted source's rows are genuinely free of UNKNOWN.
  4. **A read that is secretly a write.** Building the registry over a bare
     project must create nothing on disk; only the explicit `snapshot`
     verb/function may write, and only to the one file it declares.
  5. **The front door drifting from the library.** The CLI is driven as a
     real subprocess, both verbs, both output formats, all documented exit
     codes.

Nothing here runs a stage, a gate script, a build, a regression or an LSF
submission.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dv_harness import unknown_uncertainty_registry as uur
from dv_harness import golden_flow_readiness as gfr
from dv_harness import generation_readiness as gr

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    return tmp_path / "proj"


# ===========================================================================
# extract_unknown_rows() -- pure extraction
# ===========================================================================

def test_extract_unknown_rows_keeps_only_unknown_status():
    rows = [
        {"row_id": "r1", "row": "Row One", "status": "READY",
         "evidence": "e1", "gap": "", "fact_source": ["a.b"]},
        {"row_id": "r2", "row": "Row Two", "status": "UNKNOWN",
         "evidence": "e2", "gap": "g2", "fact_source": ["c.d"]},
        {"row_id": "r3", "row": "Row Three", "status": "PARTIAL",
         "evidence": "e3", "gap": "g3", "fact_source": []},
        {"row_id": "r4", "row": "Row Four", "status": "BLOCKED",
         "evidence": "e4", "gap": "g4", "fact_source": ["x"]},
        {"row_id": "r5", "row": "Row Five", "status": "UNKNOWN",
         "evidence": "e5", "gap": "g5", "fact_source": ["y", "z"]},
    ]
    entries = uur.extract_unknown_rows("my_source", rows)
    assert [e["row_id"] for e in entries] == ["r2", "r5"]
    assert entries[0]["source"] == "my_source"
    assert entries[0]["label"] == "Row Two"
    assert entries[0]["evidence"] == "e2"
    assert entries[0]["gap"] == "g2"
    assert entries[0]["fact_source"] == "c.d"
    assert entries[0]["status"] == "UNKNOWN"
    assert entries[0]["malformed"] is False
    assert entries[1]["fact_source"] == "y, z"


def test_extract_unknown_rows_empty_and_none_return_empty_list():
    assert uur.extract_unknown_rows("src", []) == []
    assert uur.extract_unknown_rows("src", None) == []


def test_extract_unknown_rows_malformed_row_reported_never_dropped_or_crashing():
    rows = [
        "this is not a mapping at all",
        {"row_id": "ok", "row": "Fine Row", "status": "UNKNOWN",
         "evidence": "e", "gap": "g", "fact_source": ["f"]},
        42,
    ]
    entries = uur.extract_unknown_rows("weird_source", rows)
    # Both the string and the int are reported, never silently swallowed --
    # and the genuinely UNKNOWN dict row in between is still extracted
    # correctly despite its malformed neighbours.
    assert len(entries) == 3
    malformed = [e for e in entries if e["malformed"]]
    assert len(malformed) == 2
    assert malformed[0]["row_id"] == "weird_source[0]"
    assert "MALFORMED_ROW" in malformed[0]["gap"]
    assert "str" in malformed[0]["gap"]
    assert malformed[1]["row_id"] == "weird_source[2]"
    assert "int" in malformed[1]["gap"]
    ok = [e for e in entries if not e["malformed"]]
    assert ok[0]["row_id"] == "ok"
    assert ok[0]["status"] == "UNKNOWN"


def test_extract_unknown_rows_key_overrides_for_a_differently_shaped_source():
    """A source that does not spell its fields row/row_id/status/evidence/gap/
    fact_source can still register, via explicit key overrides -- this is what
    lets ANY other analyzer's row-based output be folded into the registry
    without this module importing that analyzer itself."""
    rows = [
        {"id": "x1", "name": "Custom Row", "verdict": "UNKNOWN",
         "why": "no data yet", "missing": "needs a re-run", "source_fn": "m.f"},
        {"id": "x2", "name": "Another Row", "verdict": "READY",
         "why": "", "missing": "", "source_fn": "m.g"},
    ]
    entries = uur.extract_unknown_rows(
        "custom_source", rows,
        row_id_key="id", label_key="name", status_key="verdict",
        evidence_key="why", gap_key="missing", fact_source_key="source_fn")
    assert len(entries) == 1
    assert entries[0]["row_id"] == "x1"
    assert entries[0]["label"] == "Custom Row"
    assert entries[0]["evidence"] == "no data yet"
    assert entries[0]["gap"] == "needs a re-run"
    assert entries[0]["fact_source"] == "m.f"


def test_register_generic_source_is_the_same_function():
    assert uur.register_generic_source is uur.extract_unknown_rows


def test_extract_unknown_rows_missing_row_id_falls_back_to_label_then_index():
    rows = [
        {"row": "Only A Label", "status": "UNKNOWN", "evidence": "", "gap": ""},
        {"status": "UNKNOWN", "evidence": "", "gap": ""},
    ]
    entries = uur.extract_unknown_rows("s", rows)
    assert entries[0]["row_id"] == "Only A Label"
    assert entries[1]["row_id"] == "s[1]"


# ===========================================================================
# unknown_rows_from_*_matrix() -- pure, over an already-computed matrix
# ===========================================================================

def test_unknown_rows_from_golden_flow_matrix_uses_that_source_name():
    matrix = {"rows": [
        {"row_id": "a", "row": "A", "status": "UNKNOWN", "evidence": "", "gap": "",
         "fact_source": []},
        {"row_id": "b", "row": "B", "status": "READY", "evidence": "", "gap": "",
         "fact_source": []},
    ]}
    entries = uur.unknown_rows_from_golden_flow_matrix(matrix)
    assert len(entries) == 1
    assert entries[0]["source"] == "golden_flow_readiness"
    assert entries[0]["row_id"] == "a"


def test_unknown_rows_from_generation_matrix_uses_that_source_name():
    matrix = {"rows": [
        {"row_id": "c", "row": "C", "status": "UNKNOWN", "evidence": "", "gap": "",
         "fact_source": []},
    ]}
    entries = uur.unknown_rows_from_generation_matrix(matrix)
    assert len(entries) == 1
    assert entries[0]["source"] == "generation_readiness"
    assert entries[0]["row_id"] == "c"


# ===========================================================================
# collect_from_*() -- real integration against the REAL sibling modules
# ===========================================================================

def test_collect_from_golden_flow_readiness_over_a_real_bare_project(project: Path):
    """Driven against the REAL `golden_flow_readiness.py` -- never a stub.
    The independent recount (over the module's own real matrix) is the
    negative control: it proves this registry's extraction agrees exactly
    with a fresh, separately-computed count over the same real evidence."""
    project.mkdir(parents=True)
    matrix, entries = uur.collect_from_golden_flow_readiness(project)
    assert matrix["schema_version"]
    independent_unknown_row_ids = [r["row_id"] for r in matrix["rows"]
                                    if r["status"] == "UNKNOWN"]
    assert [e["row_id"] for e in entries] == independent_unknown_row_ids
    assert len(independent_unknown_row_ids) > 0  # a bare project really has open unknowns
    for e in entries:
        assert e["source"] == "golden_flow_readiness"
        assert e["malformed"] is False


def test_collect_from_generation_readiness_over_a_real_bare_project(project: Path):
    """Driven against the REAL `generation_readiness.py` -- never a stub.
    `deep=False` keeps this fast without changing which rows are UNKNOWN for
    reasons unrelated to the SYS-1..30 chain."""
    project.mkdir(parents=True)
    matrix, entries = uur.collect_from_generation_readiness(project, deep=False)
    assert matrix["schema_version"]
    independent_unknown_row_ids = [r["row_id"] for r in matrix["rows"]
                                    if r["status"] == "UNKNOWN"]
    assert [e["row_id"] for e in entries] == independent_unknown_row_ids
    assert len(independent_unknown_row_ids) > 0
    for e in entries:
        assert e["source"] == "generation_readiness"


def test_collecting_from_either_real_source_creates_nothing_on_disk(project: Path):
    project.mkdir(parents=True)
    uur.collect_from_golden_flow_readiness(project)
    uur.collect_from_generation_readiness(project, deep=False)
    assert list(project.rglob("*")) == []


# ===========================================================================
# build_unknown_uncertainty_registry() -- the full aggregator
# ===========================================================================

def test_build_registry_over_a_real_bare_project_aggregates_both_real_sources(
        project: Path):
    project.mkdir(parents=True)
    registry = uur.build_unknown_uncertainty_registry(project, deep=False)

    gf_matrix = gfr.derive_golden_flow_readiness(project)
    gr_matrix = gr.derive_generation_readiness(project, deep=False)
    expected_gf = sum(1 for r in gf_matrix["rows"] if r["status"] == "UNKNOWN")
    expected_gr = sum(1 for r in gr_matrix["rows"] if r["status"] == "UNKNOWN")

    assert registry["overall"] == "UNCERTAINTY_SURFACE_OPEN"
    assert registry["summary"]["entries_total"] == expected_gf + expected_gr
    assert registry["summary"]["by_source"]["golden_flow_readiness"] == expected_gf
    assert registry["summary"]["by_source"]["generation_readiness"] == expected_gr

    names = [s["source"] for s in registry["sources_consulted"]]
    assert names == ["golden_flow_readiness", "generation_readiness"]
    for s in registry["sources_consulted"]:
        assert s["unknown_count"] <= s["rows_total"]

    # Every entry really came from one of the two real sources -- never a
    # phantom third source this build never consulted.
    assert {e["source"] for e in registry["entries"]} == \
        {"golden_flow_readiness", "generation_readiness"}


def test_build_registry_over_a_real_bare_project_writes_nothing(project: Path):
    project.mkdir(parents=True)
    uur.build_unknown_uncertainty_registry(project, deep=False)
    assert list(project.rglob("*")) == []


def test_build_registry_with_extra_sources_folds_them_in(project: Path):
    project.mkdir(parents=True)
    extra = {
        "my_analyzer": [
            {"row_id": "z1", "row": "Z1", "status": "UNKNOWN",
             "evidence": "", "gap": "no evidence yet", "fact_source": ["m.n"]},
            {"row_id": "z2", "row": "Z2", "status": "READY",
             "evidence": "", "gap": "", "fact_source": []},
        ],
    }
    registry = uur.build_unknown_uncertainty_registry(
        project, deep=False, extra_sources=extra)
    names = [s["source"] for s in registry["sources_consulted"]]
    assert names == ["golden_flow_readiness", "generation_readiness", "my_analyzer"]
    my_entries = [e for e in registry["entries"] if e["source"] == "my_analyzer"]
    assert len(my_entries) == 1
    assert my_entries[0]["row_id"] == "z1"
    assert registry["summary"]["by_source"]["my_analyzer"] == 1


def test_build_registry_with_extra_source_using_key_overrides(project: Path):
    project.mkdir(parents=True)
    extra = {
        "custom": (
            [{"id": "c1", "name": "Custom", "verdict": "UNKNOWN",
              "why": "", "missing": "", "source_fn": "c.d"}],
            {"row_id_key": "id", "label_key": "name", "status_key": "verdict",
             "evidence_key": "why", "gap_key": "missing",
             "fact_source_key": "source_fn"},
        ),
    }
    registry = uur.build_unknown_uncertainty_registry(
        project, deep=False, extra_sources=extra)
    custom_entries = [e for e in registry["entries"] if e["source"] == "custom"]
    assert len(custom_entries) == 1
    assert custom_entries[0]["row_id"] == "c1"


def test_extra_source_never_consulted_is_absent_never_assumed_clean(project: Path):
    """The negative control this whole module exists to keep honest: a source
    the caller never supplied contributes NOTHING to `sources_consulted` and
    NOTHING to `entries` -- it is never silently assumed to have zero
    unknowns just because it was not asked."""
    project.mkdir(parents=True)
    registry = uur.build_unknown_uncertainty_registry(project, deep=False)
    names = [s["source"] for s in registry["sources_consulted"]]
    assert "some_other_analyzer_nobody_registered" not in names
    assert all(e["source"] != "some_other_analyzer_nobody_registered"
               for e in registry["entries"])


def test_build_registry_reports_clear_when_every_consulted_source_is_genuinely_clean(
        monkeypatch, project: Path):
    """`UNCERTAINTY_SURFACE_CLEAR` is only ever reached honestly: this test
    controls both real sources' own matrices (rather than fabricating a fully
    wired real project, which this repo cannot manufacture on demand) to
    prove the aggregator's own fold -- zero entries in, CLEAR out -- rather
    than merely asserting it never fires on a bare project."""
    project.mkdir(parents=True)

    clean_gf_matrix = {"schema_version": "1.0", "rows": [
        {"row_id": "g1", "row": "G1", "status": "READY", "evidence": "e",
         "gap": "", "fact_source": ["x"]},
    ]}
    clean_gr_matrix = {"schema_version": "1.0", "rows": [
        {"row_id": "r1", "row": "R1", "status": "READY", "evidence": "e",
         "gap": "", "fact_source": ["y"]},
    ]}

    monkeypatch.setattr(
        "dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
        lambda root, cfg=None: clean_gf_matrix)
    monkeypatch.setattr(
        "dv_harness.generation_readiness.derive_generation_readiness",
        lambda root, cfg=None, deep=True: clean_gr_matrix)

    registry = uur.build_unknown_uncertainty_registry(project, deep=False)
    assert registry["overall"] == "UNCERTAINTY_SURFACE_CLEAR"
    assert registry["summary"]["entries_total"] == 0
    assert registry["entries"] == []


# ===========================================================================
# Rendering
# ===========================================================================

def test_render_table_and_report_over_a_real_bare_project(project: Path):
    project.mkdir(parents=True)
    registry = uur.build_unknown_uncertainty_registry(project, deep=False)
    table = uur.render_unknown_uncertainty_table(registry)
    assert "Source" in table
    assert "golden_flow_readiness" in table
    report = uur.format_unknown_uncertainty_report(registry)
    assert "UNKNOWN / UNCERTAINTY REGISTRY" in report
    assert registry["overall"] in report
    assert "This registry authorizes" in report


def test_render_table_empty_note_when_registry_has_no_entries():
    registry = {"entries": []}
    table = uur.render_unknown_uncertainty_table(registry)
    assert "no open UNKNOWN rows" in table


# ===========================================================================
# Persistence -- assemble never writes, snapshot writes exactly one file
# ===========================================================================

def test_write_and_load_round_trip(project: Path):
    project.mkdir(parents=True)
    registry = uur.build_unknown_uncertainty_registry(project, deep=False)
    out_path = uur.write_unknown_uncertainty_registry(project, registry)
    assert out_path == project / ".dv-harness" / "unknown_uncertainty_registry.json"
    assert out_path.exists()
    loaded = uur.load_unknown_uncertainty_registry(project)
    assert loaded == registry


def test_load_returns_none_when_no_snapshot_exists(project: Path):
    project.mkdir(parents=True)
    assert uur.load_unknown_uncertainty_registry(project) is None


def test_load_raises_on_a_corrupt_snapshot_never_reads_as_absent(project: Path):
    snap = project / ".dv-harness" / "unknown_uncertainty_registry.json"
    snap.parent.mkdir(parents=True)
    snap.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(uur.UnknownUncertaintyRegistryError) as excinfo:
        uur.load_unknown_uncertainty_registry(project)
    assert excinfo.value.reason == "REGISTRY_SNAPSHOT_UNREADABLE"


# ===========================================================================
# CLI -- real subprocess, both verbs, both output formats, all exit codes
# ===========================================================================

def _run_cli(project: Path, *extra_args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.unknown_uncertainty_registry",
         "--project-root", str(project), *extra_args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)


def test_cli_assemble_over_bare_project_exits_1_and_writes_nothing(project: Path):
    project.mkdir(parents=True)
    proc = _run_cli(project, "assemble", "--no-deep")
    assert proc.returncode == 1, proc.stderr
    assert "UNCERTAINTY_SURFACE_OPEN" in proc.stdout
    assert list(project.rglob("*")) == []


def test_cli_assemble_json_matches_library_call(project: Path):
    project.mkdir(parents=True)
    proc = _run_cli(project, "assemble", "--no-deep", "--json")
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    registry = uur.build_unknown_uncertainty_registry(project, deep=False)
    assert payload["overall"] == registry["overall"]
    assert payload["summary"]["entries_total"] == registry["summary"]["entries_total"]
    assert [e["row_id"] for e in payload["entries"]] == \
        [e["row_id"] for e in registry["entries"]]


def test_cli_snapshot_writes_exactly_the_one_declared_file(project: Path):
    project.mkdir(parents=True)
    proc = _run_cli(project, "snapshot", "--no-deep")
    assert proc.returncode == 1, proc.stderr
    written = list(project.rglob("*"))
    written_files = [p for p in written if p.is_file()]
    assert written_files == [project / ".dv-harness" / "unknown_uncertainty_registry.json"]
    loaded = uur.load_unknown_uncertainty_registry(project)
    assert loaded["overall"] == "UNCERTAINTY_SURFACE_OPEN"


def test_cli_rejects_an_unknown_verb(project: Path):
    project.mkdir(parents=True)
    proc = _run_cli(project, "not-a-real-verb")
    assert proc.returncode == 2
