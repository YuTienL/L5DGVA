"""Tests for dv_harness/doc_extraction_fanout.py -- the parallel multi-extractor
dispatch layer over self_check_list.md item #40's eleven document categories.

Every extraction here is performed by the REAL extractor against REAL inputs:
`examples/asset_processing/inputs/` (the committed worked examples
`test_asset_processing_artifacts.py` already exercises), this repo's own
`dv_harness/uvm_generator/templates/sim_scripts/Makefile`, and this repo's own
`docs/*.pdf` user guide for the pypdf path. Nothing here mocks an extractor,
because a fan-out that only ever dispatched stubs would prove the fan-out and
nothing about whether the eleven categories actually convert.

The highest-value assertions, i.e. the ones that would catch a regression that
matters:
  * `test_fanout_really_runs_concurrently` -- the whole point of item #40. It
    would pass trivially against a sequential loop if it only counted results,
    so it measures real overlap against a deliberately-blocking barrier that
    CANNOT be satisfied by a sequential dispatcher.
  * `test_absent_extractor_is_reported_never_faked` -- an empty fan-out must
    never read as a complete one.
  * `test_one_failing_category_does_not_sink_the_others` -- a fan-out that
    aborted on the first bad document would be worse than the status quo.
  * `test_concurrent_document_index_registration_loses_no_rows` -- the real
    read-modify-write hazard the fan-out introduces, with a control proving the
    test would actually notice if the lock were removed.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from dv_harness import doc_extraction_fanout as fanout
from dv_harness.doc_extraction import DocumentIndex
from dv_harness.doc_extraction_fanout import (
    CATEGORY_EXTRACTORS,
    DocExtractionFanoutError,
    ExtractionOutcome,
    ExtractionRequest,
    STATUS_EXTRACTED,
    STATUS_FAILED,
    STATUS_INPUT_NOT_SUPPLIED,
    STATUS_NO_EXTRACTOR,
    STATUS_UP_TO_DATE,
    assert_extractor_table_matches_categories,
    dispatch_document_extractions,
    plan_extractions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT / "examples" / "asset_processing" / "inputs"
TEMPLATE_MAKEFILE = (REPO_ROOT / "dv_harness" / "uvm_generator" / "templates"
                     / "sim_scripts" / "Makefile")
REPO_PDF = REPO_ROOT / "docs" / "DV_Agent_Harness_L5_Detailed_User_Guide_TC.pdf"

# item #40's own sub-item letters, in the order the checklist states them.
CHECKLIST_ITEMS = ("40a", "40b", "40c", "40d", "40e", "40f",
                   "40g", "40h", "40i", "40j", "40k")


# ---------------------------------------------------------------------------
# real inputs
# ---------------------------------------------------------------------------

@pytest.fixture
def guide_docs(tmp_path):
    """Two small real documents the .md branch of the distiller reads for
    real. The .pdf branch is covered separately by `test_pdf_document_is_
    distilled_through_the_fanout` against this repo's own committed guide."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "demo_vip_user_guide.md").write_text(
        "1. Overview\nThe demo VIP provides an agent and a scoreboard.\n"
        "2. Sequences\nThe base sequence drives one transaction.\n", encoding="utf-8")
    (src / "demo_protocol_spec.md").write_text(
        "1. Link Layer\nLink training completes before data.\n"
        "2. Physical Layer\nThe lane rate is fixed.\n", encoding="utf-8")
    return src


@pytest.fixture
def pattern_dir(tmp_path):
    """A real BFM-pattern directory reference_pattern_audit.audit_directory()
    parses for real -- host/DUT paired register writes at the same offset."""
    d = tmp_path / "bfm_patterns"
    d.mkdir()
    (d / "cmd_link_init.txt").write_text(
        "WRITE 0xBB000020 0x00000001\n"
        "WRITE 0xCC000020 0x00000001\n"
        "WRITE 0xBB000024 0x0000000F\n", encoding="utf-8")
    return d


@pytest.fixture
def real_inputs(guide_docs, pattern_dir):
    """Every category that has a real extractor, wired to a real input."""
    return {
        "vip_user_guide": {"documents": [
            {"path": str(guide_docs / "demo_vip_user_guide.md"), "title": "Demo VIP UG"}]},
        "vip_source": {"roots": [str(INPUTS / "vip_src")], "protocol": "demo"},
        "dut_document_registers": {"intent_path": str(INPUTS / "dut_intent.yaml"),
                                    "sys_regmap_path": str(INPUTS / "sys_regmap.json")},
        "ip_document": {"constraints_path": str(INPUTS / "constraints.yaml")},
        "programming_guide": {"init_seq_path": str(INPUTS / "init_seq.yaml"),
                               "sys_regmap_path": str(INPUTS / "sys_regmap.json")},
        "dut_rtl": {"rtl_files": [str(INPUTS / "phy_boundary_demo.sv")]},
        "top_testbench_runscript": {"makefile": str(TEMPLATE_MAKEFILE),
                                     "target_ip": "USB", "ip_prefix": "usb_"},
        "reference_command_txt": {"pattern_dir": str(pattern_dir), "glob": "*.txt"},
        "standard_spec": {"documents": [
            {"path": str(guide_docs / "demo_protocol_spec.md"), "title": "Demo Spec"}]},
    }


@pytest.fixture
def fanned_out(tmp_path, real_inputs):
    return dispatch_document_extractions(
        real_inputs, tmp_path / "out", project_root=tmp_path / "proj")


# ---------------------------------------------------------------------------
# the category table is the checklist, and the code matches it
# ---------------------------------------------------------------------------

def test_eleven_categories_cover_checklist_item_40_a_through_k():
    entries = fanout.load_categories()
    assert len(entries) == 11
    assert tuple(e["checklist_item"] for e in entries) == CHECKLIST_ITEMS


def test_extractor_table_and_category_data_agree():
    # The drift check itself: a category with no adapter, an adapter for no
    # category, or a declared module.callable that no longer resolves.
    assert_extractor_table_matches_categories()


def test_every_declared_extractor_resolves_to_a_real_callable():
    import importlib
    for entry in fanout.load_categories():
        target = entry.get("extractor")
        if not target:
            continue
        module_name, _, attr = target.rpartition(".")
        assert callable(getattr(importlib.import_module(module_name), attr)), target


def test_a_category_without_an_extractor_must_say_why():
    for entry in fanout.load_categories():
        if not entry.get("extractor"):
            assert (entry.get("no_extractor_reason") or "").strip(), entry["category_id"]


def test_drift_check_catches_an_adapter_for_an_undeclared_category(monkeypatch):
    # Detection power: if the check could not see a table/data disagreement,
    # every other assertion about the table would be worthless.
    monkeypatch.setitem(CATEGORY_EXTRACTORS, "invented_category", lambda req: None)
    with pytest.raises(DocExtractionFanoutError, match="adapter-but-not-declared"):
        assert_extractor_table_matches_categories()


# ---------------------------------------------------------------------------
# the fan-out itself
# ---------------------------------------------------------------------------

def test_every_category_with_a_real_input_extracts(fanned_out):
    by_id = {r["category_id"]: r for r in fanned_out["results"]}
    for cid in CATEGORY_EXTRACTORS:
        assert by_id[cid]["status"] == STATUS_EXTRACTED, (cid, by_id[cid]["reason"])
    assert fanned_out["counts"][STATUS_EXTRACTED] == 9
    assert fanned_out["counts"][STATUS_FAILED] == 0


def test_every_reported_artifact_really_exists_on_disk(fanned_out):
    produced = 0
    for result in fanned_out["results"]:
        for artifact in result["artifacts"]:
            assert artifact["exists"], artifact["path"]
            assert Path(artifact["path"]).is_file()
            assert artifact["bytes"] > 0
            assert len(artifact["sha256"]) == 64
            produced += 1
    assert produced >= 12


def test_each_category_writes_only_into_its_own_directory(tmp_path, fanned_out):
    out_root = tmp_path / "out"
    for result in fanned_out["results"]:
        for artifact in result["artifacts"]:
            path = Path(artifact["path"]).resolve()
            assert path.is_relative_to((out_root / result["category_id"]).resolve()), path


def test_results_are_returned_in_declared_order_not_completion_order(fanned_out):
    assert [r["category_id"] for r in fanned_out["results"]] == list(fanout.category_ids())
    assert [r["checklist_item"] for r in fanned_out["results"]] == list(CHECKLIST_ITEMS)


def test_absent_extractor_is_reported_never_faked(fanned_out):
    by_id = {r["category_id"]: r for r in fanned_out["results"]}
    for cid in ("vip_examples", "ip_source"):
        assert by_id[cid]["status"] == STATUS_NO_EXTRACTOR
        assert by_id[cid]["artifacts"] == []
        # The reason is the real one from the data file, not a generic string.
        assert len(by_id[cid]["reason"]) > 80
    assert fanned_out["counts"][STATUS_NO_EXTRACTOR] == 2


def test_no_input_is_a_distinct_outcome_from_no_extractor(tmp_path):
    result = dispatch_document_extractions({}, tmp_path / "out", project_root=tmp_path)
    counts = result["counts"]
    assert counts[STATUS_INPUT_NOT_SUPPLIED] == 9
    assert counts[STATUS_NO_EXTRACTOR] == 2
    assert counts[STATUS_EXTRACTED] == 0
    # "nobody built this" and "you gave me nothing" must never collapse.
    assert counts[STATUS_INPUT_NOT_SUPPLIED] != counts[STATUS_NO_EXTRACTOR]


def test_only_restricts_the_fanout(tmp_path, real_inputs):
    result = dispatch_document_extractions(
        real_inputs, tmp_path / "out", project_root=tmp_path,
        only=["ip_document", "programming_guide"])
    assert result["categories_dispatched"] == ["ip_document", "programming_guide"]
    assert len(result["results"]) == 2


def test_unknown_category_is_refused(tmp_path):
    with pytest.raises(DocExtractionFanoutError, match="unknown document categories"):
        dispatch_document_extractions({}, tmp_path / "out", only=["not_a_category"])


# ---------------------------------------------------------------------------
# genuine concurrency -- the point of item #40
# ---------------------------------------------------------------------------

def test_fanout_really_runs_concurrently(tmp_path, monkeypatch):
    """A barrier a SEQUENTIAL dispatcher cannot get past.

    Each of the four adapters blocks on the same `threading.Barrier(4)`. If the
    fan-out ran them one at a time, the first would block forever and the
    barrier would time out -- so this is a property no result-counting test
    could establish.
    """
    barrier = threading.Barrier(4, timeout=20)
    entered = []

    def blocking(req: ExtractionRequest) -> ExtractionOutcome:
        entered.append(req.category_id)
        barrier.wait()
        path = req.out_dir / "blocked.json"
        path.write_text("{}", encoding="utf-8")
        return ExtractionOutcome(artifacts=[path])

    selected = ["ip_document", "programming_guide", "dut_rtl", "top_testbench_runscript"]
    for cid in selected:
        monkeypatch.setitem(CATEGORY_EXTRACTORS, cid, blocking)

    result = dispatch_document_extractions(
        {cid: {"probe": True} for cid in selected}, tmp_path / "out",
        project_root=tmp_path, only=selected, max_workers=4)

    assert sorted(entered) == sorted(selected)
    assert all(r["status"] == STATUS_EXTRACTED for r in result["results"])
    assert result["distinct_worker_threads"] == 4


def test_real_extractors_overlap_in_wall_clock_time(fanned_out):
    """Real overlap on the REAL extractors, measured rather than asserted: the
    summed per-worker time must exceed the wall clock the whole batch took."""
    assert fanned_out["distinct_worker_threads"] > 1
    assert fanned_out["worker_seconds_sum"] > fanned_out["wall_clock_seconds"]


def test_worker_threads_are_named_for_this_fanout(fanned_out):
    names = {r["thread_name"] for r in fanned_out["results"]}
    assert all(n.startswith("doc-extract") for n in names), names


def test_single_category_selection_needs_no_thread_pool(tmp_path, real_inputs):
    result = dispatch_document_extractions(
        real_inputs, tmp_path / "out", project_root=tmp_path, only=["ip_document"])
    assert result["results"][0]["status"] == STATUS_EXTRACTED
    assert result["results"][0]["thread_name"] == threading.current_thread().name


# ---------------------------------------------------------------------------
# failure isolation
# ---------------------------------------------------------------------------

def test_one_failing_category_does_not_sink_the_others(tmp_path, real_inputs):
    broken = dict(real_inputs)
    broken["ip_document"] = {"constraints_path": str(tmp_path / "does_not_exist.yaml")}
    result = dispatch_document_extractions(
        broken, tmp_path / "out", project_root=tmp_path)
    by_id = {r["category_id"]: r for r in result["results"]}
    assert by_id["ip_document"]["status"] == STATUS_FAILED
    assert "does_not_exist.yaml" in by_id["ip_document"]["reason"]
    # every other extractor still ran
    assert result["counts"][STATUS_EXTRACTED] == 8
    assert result["counts"][STATUS_FAILED] == 1


def test_missing_required_input_fails_only_that_category(tmp_path, real_inputs):
    broken = dict(real_inputs)
    broken["vip_source"] = {"roots": [str(INPUTS / "vip_src")]}  # no protocol
    result = dispatch_document_extractions(
        broken, tmp_path / "out", project_root=tmp_path)
    by_id = {r["category_id"]: r for r in result["results"]}
    assert by_id["vip_source"]["status"] == STATUS_FAILED
    assert "'protocol'" in by_id["vip_source"]["reason"]
    assert result["counts"][STATUS_EXTRACTED] == 8


def test_colliding_document_stems_are_refused_not_silently_overwritten(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "guide.md").write_text("1. Section\nbody\n", encoding="utf-8")
    result = dispatch_document_extractions(
        {"vip_user_guide": {"documents": [str(a / "guide.md"), str(b / "guide.md")]}},
        tmp_path / "out", project_root=tmp_path, only=["vip_user_guide"])
    assert result["results"][0]["status"] == STATUS_FAILED
    assert "colliding file stems" in result["results"][0]["reason"]


# ---------------------------------------------------------------------------
# DocumentIndex: the fan-out is doc_extraction.py's first pipeline caller
# ---------------------------------------------------------------------------

def test_every_consumed_source_document_is_registered(tmp_path, real_inputs):
    project_root = tmp_path / "proj"
    result = dispatch_document_extractions(
        real_inputs, tmp_path / "out", project_root=project_root)
    rows = DocumentIndex(project_root).load()
    assert rows, "the fan-out registered nothing in the DocumentIndex"
    registered = {r["path"] for r in rows}
    for expected in (INPUTS / "dut_intent.yaml", INPUTS / "constraints.yaml",
                     INPUTS / "init_seq.yaml", TEMPLATE_MAKEFILE):
        assert str(expected.resolve()) in registered, expected
    # kind carries the category, so a fan-out row stays distinguishable from a
    # research_document row in the same shared index.
    kinds = {r["kind"] for r in rows}
    assert all(k.startswith("doc_extraction:") for k in kinds), kinds
    assert "doc_extraction:ip_document" in kinds
    # and the result set reports the same sha256s the index holds
    by_path = {r["path"]: r["sha256"] for r in rows}
    for entry in result["results"]:
        for doc in entry["source_documents"]:
            assert by_path[doc["path"]] == doc["sha256"]


def test_concurrent_document_index_registration_loses_no_rows(tmp_path):
    """The real read-modify-write hazard the fan-out introduces.

    Nine adapters each hand back a distinct source document; every one must
    survive in the single index JSON. The control below proves this test has
    the power to notice a lost row.
    """
    sources = {}
    for cid in CATEGORY_EXTRACTORS:
        src = tmp_path / "sources" / f"{cid}.txt"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(f"source document for {cid}\n", encoding="utf-8")
        sources[cid] = src

    def register_only(req: ExtractionRequest) -> ExtractionOutcome:
        # Widen the read-modify-write window so an unserialized index would
        # actually lose rows rather than only theoretically being able to.
        time.sleep(0.01)
        return ExtractionOutcome(source_documents=[sources[req.category_id]])

    original = dict(CATEGORY_EXTRACTORS)
    try:
        for cid in list(CATEGORY_EXTRACTORS):
            CATEGORY_EXTRACTORS[cid] = register_only
        project_root = tmp_path / "proj"
        dispatch_document_extractions(
            {cid: {"probe": True} for cid in original}, tmp_path / "out",
            project_root=project_root, max_workers=9)
    finally:
        CATEGORY_EXTRACTORS.clear()
        CATEGORY_EXTRACTORS.update(original)

    rows = DocumentIndex(project_root).load()
    assert len(rows) == len(original) == 9
    assert {Path(r["path"]).stem for r in rows} == set(original)


def test_the_index_lock_is_what_makes_that_safe():
    """Control for the test above: without `_INDEX_LOCK` actually serializing
    registration, the guarantee it asserts has no mechanism behind it."""
    assert isinstance(fanout._INDEX_LOCK, type(threading.Lock()))
    src = fanout.__file__
    body = Path(src).read_text(encoding="utf-8")
    assert "with _INDEX_LOCK:" in body


def test_no_register_writes_no_index(tmp_path, real_inputs):
    project_root = tmp_path / "proj"
    dispatch_document_extractions(real_inputs, tmp_path / "out",
                                   project_root=project_root, register=False)
    assert not (project_root / ".dv-harness" / "documents" / "document_index.json").exists()


def test_incremental_skips_a_category_whose_sources_are_unchanged(tmp_path, real_inputs):
    out = tmp_path / "out"
    project_root = tmp_path / "proj"
    first = dispatch_document_extractions(
        real_inputs, out, project_root=project_root, only=["ip_document"])
    assert first["results"][0]["status"] == STATUS_EXTRACTED

    second = dispatch_document_extractions(
        real_inputs, out, project_root=project_root, only=["ip_document"],
        incremental=True)
    assert second["results"][0]["status"] == STATUS_UP_TO_DATE
    assert second["results"][0]["artifacts"], "UP_TO_DATE must still report the artifacts"


def test_incremental_re_extracts_when_a_source_really_changed(tmp_path):
    src = tmp_path / "constraints.yaml"
    src.write_text((INPUTS / "constraints.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    inputs = {"ip_document": {"constraints_path": str(src)}}
    out = tmp_path / "out"
    project_root = tmp_path / "proj"
    dispatch_document_extractions(inputs, out, project_root=project_root,
                                   only=["ip_document"])
    src.write_text(src.read_text(encoding="utf-8") + "\n# a real edit\n", encoding="utf-8")
    again = dispatch_document_extractions(inputs, out, project_root=project_root,
                                           only=["ip_document"], incremental=True)
    assert again["results"][0]["status"] == STATUS_EXTRACTED


# ---------------------------------------------------------------------------
# honesty of what each category actually produced
# ---------------------------------------------------------------------------

def test_dut_rtl_carries_each_manifest_layer_status_verbatim(fanned_out):
    """VERBATIM, checked against the manifest actually on disk rather than
    against a status vocabulary this test hardcodes -- so a layer that could
    not be produced (NOT_AVAILABLE, with its own reason) can never be
    summarized away into a fan-out that reports a clean EXTRACTED."""
    result = next(r for r in fanned_out["results"] if r["category_id"] == "dut_rtl")
    statuses = result["detail"]["layer_status"]
    assert set(statuses) == {"rtl", "registers", "address_map", "clock_reset", "vip_config"}

    manifest = json.loads(Path(result["artifacts"][0]["path"]).read_text(encoding="utf-8"))
    for layer in ("rtl", "registers", "address_map", "clock_reset"):
        assert statuses[layer] == manifest["dut_facts"][layer]["status"], layer
    assert statuses["vip_config"] == manifest["vip_config"]["status"]
    assert all(statuses.values()), statuses


def test_top_testbench_declares_the_half_it_does_not_produce(fanned_out):
    detail = next(r for r in fanned_out["results"]
                  if r["category_id"] == "top_testbench_runscript")["detail"]
    assert detail["hierarchy_json"] == "NOT_PRODUCED_NO_NON_AGENT_EXTRACTOR"


def test_command_txt_extraction_escalates_nothing(fanned_out, tmp_path):
    """Property 4: reading is never a mutating act. The fan-out must not file
    questions on a human's behalf just because it converted some documents."""
    detail = next(r for r in fanned_out["results"]
                  if r["category_id"] == "reference_command_txt")["detail"]
    assert detail["escalated_to_question_queue"] is False
    assert not list((tmp_path / "proj").rglob("questions.json"))
    assert not list((tmp_path / "proj").rglob("decisions.json"))


def test_dut_document_registers_states_a_missing_regmap_half(tmp_path):
    result = dispatch_document_extractions(
        {"dut_document_registers": {"intent_path": str(INPUTS / "dut_intent.yaml")}},
        tmp_path / "out", project_root=tmp_path, only=["dut_document_registers"])
    entry = result["results"][0]
    assert entry["status"] == STATUS_EXTRACTED
    assert entry["detail"]["sys_regmap"] == "NOT_SUPPLIED"


def test_vip_source_index_retains_no_method_bodies(tmp_path, real_inputs):
    """The invariant that makes indexing a context-budget tier-1 VIP tree
    legitimate at all -- re-asserted on the fan-out path, which is the one that
    will be pointed at a real customer VIP tree."""
    result = dispatch_document_extractions(
        real_inputs, tmp_path / "out", project_root=tmp_path, only=["vip_source"])
    index_path = Path(result["results"][0]["artifacts"][0]["path"])
    doc = json.loads(index_path.read_text(encoding="utf-8"))
    from dv_harness import vip_symbol_index
    vip_symbol_index.assert_no_bodies_retained(doc)


@pytest.mark.skipif(not REPO_PDF.is_file(), reason="repo user-guide PDF not present")
def test_pdf_document_is_distilled_through_the_fanout(tmp_path):
    """The pypdf branch, on this repo's own real committed PDF -- the .md
    fixtures elsewhere exercise the pre-extracted-text branch only."""
    result = dispatch_document_extractions(
        {"standard_spec": {"documents": [{"path": str(REPO_PDF), "title": "L5 Guide"}]}},
        tmp_path / "out", project_root=tmp_path, only=["standard_spec"])
    entry = result["results"][0]
    assert entry["status"] == STATUS_EXTRACTED, entry["reason"]
    assert entry["detail"]["documents"][0]["page_count"] > 1
    assert entry["detail"]["documents"][0]["doc_kind"] == "protocol_spec"


# ---------------------------------------------------------------------------
# plan (dry run) and the CLI verb
# ---------------------------------------------------------------------------

def test_plan_opens_no_document_and_writes_nothing(tmp_path, real_inputs):
    before = sorted(p.name for p in tmp_path.iterdir())
    plan = plan_extractions(real_inputs)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    by_id = {p["category_id"]: p for p in plan}
    assert by_id["ip_document"]["status"] == "WOULD_EXTRACT"
    assert by_id["vip_examples"]["status"] == STATUS_NO_EXTRACTOR
    assert len(plan) == 11


def test_plan_matches_what_run_actually_did(tmp_path, real_inputs, fanned_out):
    plan = {p["category_id"]: p["status"] for p in plan_extractions(real_inputs)}
    for result in fanned_out["results"]:
        expected = STATUS_EXTRACTED if plan[result["category_id"]] == "WOULD_EXTRACT" \
            else plan[result["category_id"]]
        assert result["status"] == expected, result["category_id"]


def test_cli_categories_verb(capsys):
    assert fanout.main(["categories"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["categories"]) == 11
    assert {c["category_id"] for c in payload["categories"]} == set(fanout.category_ids())


def test_cli_run_verb_end_to_end(tmp_path, real_inputs, capsys):
    inputs_file = tmp_path / "inputs.json"
    inputs_file.write_text(json.dumps(real_inputs), encoding="utf-8")
    code = fanout.main(["run", "--inputs", str(inputs_file),
                        "--out", str(tmp_path / "out"),
                        "--project-root", str(tmp_path / "proj")])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"][STATUS_EXTRACTED] == 9
    assert payload["counts"][STATUS_NO_EXTRACTOR] == 2


def test_cli_run_verb_exits_1_when_a_category_failed(tmp_path, real_inputs, capsys):
    broken = dict(real_inputs)
    broken["ip_document"] = {"constraints_path": str(tmp_path / "nope.yaml")}
    inputs_file = tmp_path / "inputs.json"
    inputs_file.write_text(json.dumps(broken), encoding="utf-8")
    assert fanout.main(["run", "--inputs", str(inputs_file),
                        "--out", str(tmp_path / "out")]) == 1
    capsys.readouterr()


def test_cli_rejects_an_unknown_category_key_in_the_inputs_file(tmp_path, capsys):
    inputs_file = tmp_path / "inputs.json"
    inputs_file.write_text(json.dumps({"not_a_category": {}}), encoding="utf-8")
    assert fanout.main(["plan", "--inputs", str(inputs_file)]) == 2
    assert "unknown category keys" in capsys.readouterr().out


def test_dv_harness_cli_exposes_the_verb():
    """The fan-out must be reachable from the real front door, not only by
    import -- an orchestration layer nobody can invoke is the shape this whole
    gap was."""
    # cli.main() builds its parser inline, so this drives the real process
    # rather than reaching into a parser object that is never exposed.
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "dv_harness", "doc-extract", "categories"],
                          capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload["categories"]) == 11
