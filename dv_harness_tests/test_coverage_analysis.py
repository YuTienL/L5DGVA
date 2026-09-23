"""Tests for dv_harness/coverage_analysis.py -- coverage hole/trend analysis
plumbing (see poster-compliance audit gap: "Coverage 詳細分析（Hole 分析/
Waiver UI/趨勢圖）", 2026-08-29). Mirrors test_amba_fabric_generator.py's
pure-function-test style."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from dv_harness.coverage_analysis import (
    CoverageAnalysisError,
    parse_coverage_summary,
    identify_holes,
    compute_coverage_trend,
    render_hole_report_text,
    render_coverage_trend_svg,
    append_history_sample,
    ROOT_CAUSE_MISSING_TEST,
    ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
    ROOT_CAUSE_UNREACHABLE_STIMULUS,
    ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS,
    HOLE_TAXONOMY_CLASSES,
    TAXONOMY_ILLEGAL_BIN_MISCLASSIFIED,
    TAXONOMY_WAIVED_HOLE_EXCLUDED,
    TAXONOMY_REGISTER_FIELD_COMBINATION_HOLE,
    TAXONOMY_CROSS_COVERAGE_ONLY_UNCOVERED,
    TAXONOMY_TIMING_WINDOW_HOLE,
    TAXONOMY_CONFIG_SPECIFIC_HOLE,
    TAXONOMY_GOLDEN_SCENARIO_STALE_EVIDENCE_HOLE,
    TAXONOMY_NO_GOLDEN_SCENARIO_EVIDENCE,
    classify_coverage_hole_taxonomy,
    build_hole_evidence_record,
    build_hole_evidence_records,
    COVERAGE_KIND_FUNCTIONAL,
    COVERAGE_KIND_CODE,
    COVERAGE_KIND_CLASSES,
    CODE_COVERAGE_METRIC_NAMES,
    classify_coverage_kind,
    tag_categories_by_kind,
)

ROOT = Path(__file__).resolve().parents[1]
duckdb = pytest.importorskip("duckdb")
GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


# ---- parse_coverage_summary --------------------------------------------------

def _valid_summary():
    return {
        "categories": [
            {"name": "line", "percent": 100.0, "bins_total": 500, "bins_hit": 500},
            {"name": "branch", "percent": 87.5, "bins_total": 200, "bins_hit": 175},
            {"name": "fsm_state", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
        ]
    }


def test_parse_coverage_summary_valid():
    parsed = parse_coverage_summary(_valid_summary())
    assert len(parsed["categories"]) == 3
    assert parsed["categories"][1]["name"] == "branch"


def test_parse_coverage_summary_rejects_empty_categories():
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary({"categories": []})
    assert exc.value.reason == "MALFORMED_CATEGORY"


def test_parse_coverage_summary_rejects_missing_field():
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary({"categories": [{"name": "line", "percent": 90.0, "bins_total": 10}]})
    assert exc.value.reason == "MALFORMED_CATEGORY"


def test_parse_coverage_summary_rejects_bins_hit_exceeds_total():
    data = {"categories": [{"name": "line", "percent": 50.0, "bins_total": 10, "bins_hit": 11}]}
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary(data)
    assert exc.value.reason == "BINS_HIT_EXCEEDS_TOTAL"


def test_parse_coverage_summary_rejects_percent_out_of_range():
    data = {"categories": [{"name": "line", "percent": 150.0, "bins_total": 10, "bins_hit": 5}]}
    with pytest.raises(CoverageAnalysisError) as exc:
        parse_coverage_summary(data)
    assert exc.value.reason == "PERCENT_OUT_OF_RANGE"


# ---- identify_holes ----------------------------------------------------------

def test_identify_holes_sorts_worst_first_and_computes_bins_missing():
    parsed = parse_coverage_summary(_valid_summary())
    holes = identify_holes(parsed)
    assert [h["name"] for h in holes] == ["fsm_state", "branch"]
    assert holes[0]["bins_missing"] == 4
    assert holes[1]["bins_missing"] == 25


def test_identify_holes_empty_when_all_full():
    parsed = parse_coverage_summary({
        "categories": [{"name": "line", "percent": 100.0, "bins_total": 10, "bins_hit": 10}]
    })
    assert identify_holes(parsed) == []


# ---- compute_coverage_trend ---------------------------------------------------

def test_compute_coverage_trend_improving():
    history = [
        {"timestamp": 2, "percent": 90.0},
        {"timestamp": 1, "percent": 80.0},
    ]
    trend = compute_coverage_trend(history)
    assert trend["trend"] == "IMPROVING"
    assert trend["delta"] == pytest.approx(10.0)
    assert trend["first_percent"] == 80.0
    assert trend["last_percent"] == 90.0


def test_compute_coverage_trend_declining():
    history = [
        {"timestamp": "2026-08-01", "percent": 90.0},
        {"timestamp": "2026-08-28", "percent": 70.0},
    ]
    trend = compute_coverage_trend(history)
    assert trend["trend"] == "DECLINING"
    assert trend["delta"] == pytest.approx(-20.0)


def test_compute_coverage_trend_flat_within_tolerance():
    history = [
        {"timestamp": 1, "percent": 85.2},
        {"timestamp": 2, "percent": 85.5},
    ]
    trend = compute_coverage_trend(history)
    assert trend["trend"] == "FLAT"


def test_compute_coverage_trend_insufficient_history():
    with pytest.raises(CoverageAnalysisError) as exc:
        compute_coverage_trend([{"timestamp": 1, "percent": 85.0}])
    assert exc.value.reason == "INSUFFICIENT_HISTORY"


# ---- render_hole_report_text ---------------------------------------------------

def test_render_hole_report_text_lists_holes():
    parsed = parse_coverage_summary(_valid_summary())
    holes = identify_holes(parsed)
    text = render_hole_report_text(holes)
    assert "fsm_state" in text
    assert "60.0%" in text
    assert "4/10" in text


def test_render_hole_report_text_no_holes():
    assert render_hole_report_text([]) == "No coverage holes -- 100% across all reported categories."


# ---- render_coverage_trend_svg ------------------------------------------------

def test_render_coverage_trend_svg_structural_point_count():
    history = [
        {"timestamp": 1, "percent": 70.0},
        {"timestamp": 2, "percent": 82.5},
        {"timestamp": 3, "percent": 88.0},
    ]
    svg = render_coverage_trend_svg(history)
    assert svg.count("<circle") == 3
    assert svg.count("<polyline") == 1
    # one polyline with exactly 3 "x,y" point pairs
    import re
    polyline_points = re.search(r'points="([^"]*)"', svg).group(1)
    assert len(polyline_points.split()) == 3


def test_render_coverage_trend_svg_orders_by_timestamp_not_input_order():
    # out-of-order input -- the chart must still plot left-to-right by time
    history = [
        {"timestamp": 2, "percent": 90.0},
        {"timestamp": 1, "percent": 50.0},
    ]
    svg = render_coverage_trend_svg(history)
    import re
    xs = [float(pt.split(",")[0]) for pt in re.search(r'points="([^"]*)"', svg).group(1).split()]
    assert xs[0] < xs[1]  # timestamp=1 (first) plots at a smaller x than timestamp=2


def test_render_coverage_trend_svg_rejects_insufficient_history():
    with pytest.raises(CoverageAnalysisError) as exc:
        render_coverage_trend_svg([{"timestamp": 1, "percent": 50.0}])
    assert exc.value.reason == "INSUFFICIENT_HISTORY"


# ---- append_history_sample -----------------------------------------------------

def test_append_history_sample_creates_file_and_grows_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        history_path = tmp / "coverage" / "history.json"
        assert not history_path.exists()

        result1 = append_history_sample(history_path, 70.0, timestamp=1)
        assert history_path.exists()
        assert result1 == [{"timestamp": 1, "percent": 70.0}]

        result2 = append_history_sample(history_path, 82.5, timestamp=2)
        assert result2 == [
            {"timestamp": 1, "percent": 70.0},
            {"timestamp": 2, "percent": 82.5},
        ]
        on_disk = json.loads(history_path.read_text(encoding="utf-8"))
        assert on_disk == result2

        # the newly-grown history is real >=2-sample input compute_coverage_trend
        # (the production reader) can now consume without INSUFFICIENT_HISTORY.
        trend = compute_coverage_trend(on_disk)
        assert trend["trend"] == "IMPROVING"
    finally:
        shutil.rmtree(tmp)


def test_append_history_sample_defaults_timestamp_when_omitted():
    tmp = Path(tempfile.mkdtemp())
    try:
        history_path = tmp / "history.json"
        before = time.time()
        result = append_history_sample(history_path, 55.0)
        after = time.time()
        assert len(result) == 1
        assert before <= result[0]["timestamp"] <= after
    finally:
        shutil.rmtree(tmp)


# ---- CLI ------------------------------------------------------------------------

def test_cli_analyze_coverage_prints_categories_holes_and_trend():
    tmp = Path(tempfile.mkdtemp())
    try:
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps(_valid_summary()), encoding="utf-8")
        history_path = tmp / "history.json"
        history_path.write_text(json.dumps([
            {"timestamp": 1, "percent": 70.0},
            {"timestamp": 2, "percent": 82.5},
        ]), encoding="utf-8")

        script = ROOT / "tools" / "analyze_coverage.py"
        r = subprocess.run(
            [sys.executable, str(script), "--summary", str(summary_path), "--history", str(history_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
        assert len(out["categories"]) == 3
        assert [h["name"] for h in out["holes"]] == ["fsm_state", "branch"]
        assert out["trend"]["trend"] == "IMPROVING"
    finally:
        shutil.rmtree(tmp)


def test_cli_analyze_coverage_without_history_omits_trend():
    tmp = Path(tempfile.mkdtemp())
    try:
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps(_valid_summary()), encoding="utf-8")

        script = ROOT / "tools" / "analyze_coverage.py"
        r = subprocess.run(
            [sys.executable, str(script), "--summary", str(summary_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip())
        assert "trend" not in out
    finally:
        shutil.rmtree(tmp)


def test_cli_analyze_coverage_reports_malformed_input_error():
    tmp = Path(tempfile.mkdtemp())
    try:
        summary_path = tmp / "summary.json"
        summary_path.write_text(json.dumps({"categories": []}), encoding="utf-8")

        script = ROOT / "tools" / "analyze_coverage.py"
        r = subprocess.run(
            [sys.executable, str(script), "--summary", str(summary_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode != 0
        out = json.loads(r.stdout.strip())
        assert out["error"] == "MALFORMED_CATEGORY"
    finally:
        shutil.rmtree(tmp)


# ===========================================================================
# classify_coverage_hole_taxonomy() / build_hole_evidence_record() --
# additive 12-category taxonomy + per-hole evidence citation
# (2026-09-06, coverage-hole-taxonomy)
# ===========================================================================

def _write_requirements_csv(root: Path, rows) -> None:
    """Mirrors test_functional_coverage_signoff.py's helper of the same
    name -- the real requirements.csv shape
    change_impact.load_trace_registry()/patterns_for_coverage_id() read."""
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    header = ["REQ_ID", "SOURCE", "SCOPE", "VPLAN_ID", "SCENARIO_ID", "COMMAND_ID",
              "PATTERN_ID", "CHECKER_ID", "COVERAGE_ID", "RESULT", "STATUS", "EVIDENCE"]
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in header))
    (d / "requirements.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                        timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


# ---- vocabulary shape -----------------------------------------------------

def test_hole_taxonomy_classes_has_twelve_unique_categories_including_original_four():
    assert len(HOLE_TAXONOMY_CLASSES) == 12
    assert len(set(HOLE_TAXONOMY_CLASSES)) == 12
    # the original 4 root-cause values are REUSED verbatim, never relabeled
    for original in (ROOT_CAUSE_MISSING_TEST, ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
                      ROOT_CAUSE_UNREACHABLE_STIMULUS, ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS):
        assert original in HOLE_TAXONOMY_CLASSES


# ---- structural additions (no evidence DB needed) --------------------------

def test_taxonomy_illegal_bin_misclassified_overrides_everything(tmp_path):
    # bin_kind=illegal AND waived=True -- illegal-bin precedence wins, proving
    # the documented precedence order rather than merely the rule in isolation.
    hole = {"coverage_id": "cov_illegal", "bin_kind": "illegal", "waived": True}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_ILLEGAL_BIN_MISCLASSIFIED
    assert result["taxonomy_evidence"][0]["source"] == "hole_declared_field"
    assert result["taxonomy_evidence"][0]["field"] == "bin_kind"


def test_taxonomy_ignore_bin_variant_also_classified(tmp_path):
    hole = {"coverage_id": "cov_ignore", "bin_kind": "ignore_bin"}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_ILLEGAL_BIN_MISCLASSIFIED


def test_taxonomy_waived_hole_excluded(tmp_path):
    hole = {"coverage_id": "cov_waived", "waived": True}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_WAIVED_HOLE_EXCLUDED
    assert result["taxonomy_evidence"][0]["field"] == "waived"


def test_taxonomy_register_field_combination_hole(tmp_path):
    hole = {
        "coverage_id": "cov_reg",
        "register_name": "USB3_LINK_CTRL",
        "register_fields": ["LFPS_EN", "U1_TIMEOUT"],
    }
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_REGISTER_FIELD_COMBINATION_HOLE
    ev = result["taxonomy_evidence"][0]
    assert ev["register_name"] == "USB3_LINK_CTRL"
    assert ev["register_fields"] == ["LFPS_EN", "U1_TIMEOUT"]


def test_taxonomy_register_field_combination_requires_at_least_two_fields(tmp_path):
    # ONE declared field is not a combination -- must fall back, never guess.
    hole = {"coverage_id": "cov_reg1", "register_name": "USB3_LINK_CTRL",
            "register_fields": ["LFPS_EN"]}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] is None
    assert result["root_cause_classification"] == ROOT_CAUSE_MISSING_TEST


def _cross_summary(axis_a_percent=100.0, axis_b_percent=100.0):
    return {
        "categories": [
            {"name": "cp_speed", "percent": axis_a_percent, "bins_total": 4, "bins_hit": int(axis_a_percent / 25)},
            {"name": "cp_port", "percent": axis_b_percent, "bins_total": 2, "bins_hit": int(axis_b_percent / 50)},
        ]
    }


def test_taxonomy_cross_coverage_only_uncovered_when_axes_individually_covered(tmp_path):
    hole = {"coverage_id": "cov_cross", "cross_axes": ["cp_speed", "cp_port"]}
    result = classify_coverage_hole_taxonomy(
        tmp_path, hole, parsed_summary=_cross_summary(100.0, 100.0))
    assert result["taxonomy_classification"] == TAXONOMY_CROSS_COVERAGE_ONLY_UNCOVERED
    ev = result["taxonomy_evidence"][0]
    assert ev["source"] == "coverage_summary.categories"
    assert ev["axis_percents"] == [100.0, 100.0]


def test_taxonomy_cross_coverage_not_classified_when_axis_not_fully_covered(tmp_path):
    hole = {"coverage_id": "cov_cross_partial", "cross_axes": ["cp_speed", "cp_port"]}
    result = classify_coverage_hole_taxonomy(
        tmp_path, hole, parsed_summary=_cross_summary(75.0, 100.0))
    assert result["taxonomy_classification"] is None


def test_taxonomy_cross_coverage_not_classified_when_parsed_summary_missing(tmp_path):
    # "cannot confirm" must never be silently read as "confirmed".
    hole = {"coverage_id": "cov_cross_noparse", "cross_axes": ["cp_speed", "cp_port"]}
    result = classify_coverage_hole_taxonomy(tmp_path, hole, parsed_summary=None)
    assert result["taxonomy_classification"] is None


def test_taxonomy_timing_window_hole_via_bin_kind_transition(tmp_path):
    hole = {"coverage_id": "cov_timing1", "bin_kind": "transition"}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_TIMING_WINDOW_HOLE


def test_taxonomy_timing_window_hole_via_timing_window_ns_field(tmp_path):
    hole = {"coverage_id": "cov_timing2", "timing_window_ns": 250}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_TIMING_WINDOW_HOLE
    assert result["taxonomy_evidence"][0]["timing_window_ns"] == 250


def test_taxonomy_config_specific_hole(tmp_path):
    hole = {
        "coverage_id": "cov_cfg",
        "hit_in_configs": ["SS_1port"],
        "legal_configs": ["SS_1port", "SS_2port", "HS_1port"],
    }
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] == TAXONOMY_CONFIG_SPECIFIC_HOLE
    ev = result["taxonomy_evidence"][0]
    assert ev["hit_in_configs"] == ["SS_1port"]
    assert set(ev["unhit_legal_configs"]) == {"SS_2port", "HS_1port"}


def test_taxonomy_config_specific_not_classified_when_hit_equals_legal(tmp_path):
    # hit in every legal configuration -- not config-specific at all.
    hole = {"coverage_id": "cov_cfg_full", "hit_in_configs": ["SS_1port", "HS_1port"],
            "legal_configs": ["SS_1port", "HS_1port"]}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] is None


def test_taxonomy_config_specific_not_classified_when_hit_not_subset_of_legal(tmp_path):
    # malformed input (a "hit" config that isn't even declared legal) --
    # never silently repaired into a classification.
    hole = {"coverage_id": "cov_cfg_bad", "hit_in_configs": ["UNKNOWN_CFG"],
            "legal_configs": ["SS_1port"]}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] is None


def test_taxonomy_falls_back_to_base_root_cause_when_no_structural_evidence(tmp_path):
    hole = {"coverage_id": "cov_plain"}
    result = classify_coverage_hole_taxonomy(tmp_path, hole)
    assert result["taxonomy_classification"] is None
    assert result["root_cause_classification"] == ROOT_CAUSE_MISSING_TEST
    assert "falls back to the base root-cause classification" in result["taxonomy_basis"]


# ---- golden_scenario-corroborated categories --------------------------------

def test_taxonomy_no_golden_scenario_evidence_for_linked_pattern(tmp_path):
    _write_requirements_csv(tmp_path, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": "usb3_lfps_basic", "COVERAGE_ID": "cov_noGS"},
    ])
    hole = {"coverage_id": "cov_noGS", "root_cause_classification": "INSUFFICIENT_CONSTRAINT"}
    result = classify_coverage_hole_taxonomy(
        tmp_path, hole,
        seed_counts={"usb3_lfps_basic": 25}, history_available=True,
        db_path=str(tmp_path / "no_such_evidence.duckdb"))
    assert result["root_cause_classification"] == ROOT_CAUSE_INSUFFICIENT_CONSTRAINT
    assert result["taxonomy_classification"] == TAXONOMY_NO_GOLDEN_SCENARIO_EVIDENCE
    ev = result["taxonomy_evidence"][0]
    assert ev["source"] == "golden_scenario"
    assert ev["capsules_found"] == 0


PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test usb3_lfps_basic...
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""

TAXONOMY_TEST_NAME = "usb3_lfps_basic"
TAXONOMY_JOB_ID = 424242


def _golden_project(tmp_path):
    """A throwaway git repo + real evidence DB + real requirements.csv linking
    coverage_id 'cov_gs' to a real recorded golden_scenario capsule, mirroring
    test_golden_scenario.py's own fixture shape."""
    from dv_harness.evidence_db import EvidenceStore, default_db_path
    from dv_harness.golden_scenario import GoldenScenario, default_capsule_id, record_golden_scenario
    from dv_harness.lsf_client import JobState
    from dv_harness.vip_distill import distill_sim_log

    root = tmp_path / "proj"
    (root / "rtl" / "usb3_link").mkdir(parents=True)
    (root / "rtl" / "usb3_link" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, output reg lfps_done);\n"
        "always @(posedge clk) lfps_done <= 1;\nendmodule\n", encoding="utf-8")
    (root / ".gitignore").write_text(".dv-harness/\nrun/\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "coverage-taxonomy@example.invalid")
    _git(root, "config", "user.name", "coverage-taxonomy-test")
    sha1 = _commit(root, "initial DUT RTL")

    _write_requirements_csv(root, [
        {"REQ_ID": "REQ-1", "PATTERN_ID": TAXONOMY_TEST_NAME, "COVERAGE_ID": "cov_gs"},
    ])

    log_path = root / "run" / str(TAXONOMY_JOB_ID) / "sim.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(PASSING_SIM_LOG, encoding="utf-8")
    envelope = distill_sim_log(log_path=log_path, job_id=TAXONOMY_JOB_ID,
                                pattern=TAXONOMY_TEST_NAME, protocol="USB3",
                                run_dir=str(log_path.parent))
    store = EvidenceStore(default_db_path(root))
    try:
        store.insert_normalized_evidence(envelope)
        store.insert_job_state(JobState(
            job_id=TAXONOMY_JOB_ID, regression_id="REG-CT-1", pattern=TAXONOMY_TEST_NAME,
            run_dir=str(log_path.parent), sim_log=str(log_path), seed="1",
            lsf_status="DONE", sim_status="PASS", uvm_error_count=0, uvm_fatal_count=0,
            git_sha=sha1,
        ))
        capsule = GoldenScenario(
            capsule_id=default_capsule_id("cov_taxonomy_proj", "usb3_link", TAXONOMY_TEST_NAME, "1"),
            project="cov_taxonomy_proj", subsystem="usb3_link", test_name=TAXONOMY_TEST_NAME,
            evidence_id=envelope["evidence_id"], verified_sha=sha1,
            watched_paths=["rtl/usb3_link"],
        )
        record_golden_scenario(store, capsule)
    finally:
        store.close()
    return root


@requires_git
def test_taxonomy_golden_scenario_stale_evidence_hole(tmp_path):
    root = _golden_project(tmp_path)
    # A REAL post-freeze RTL commit inside the capsule's watched_paths --
    # the same act test_golden_scenario.py's own central test drives.
    (root / "rtl" / "usb3_link" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, output reg lfps_done);\n"
        "always @(posedge clk) lfps_done <= 0;\nendmodule\n", encoding="utf-8")
    _commit(root, "change LFPS done polarity")

    hole = {"coverage_id": "cov_gs"}
    result = classify_coverage_hole_taxonomy(root, hole)
    assert result["taxonomy_classification"] == TAXONOMY_GOLDEN_SCENARIO_STALE_EVIDENCE_HOLE
    ev = result["taxonomy_evidence"][0]
    assert ev["source"] == "golden_scenario"
    assert ev["test_name"] == TAXONOMY_TEST_NAME
    assert ev["freshness"] == "STALE"


@requires_git
def test_taxonomy_no_stale_classification_when_golden_scenario_still_fresh(tmp_path):
    root = _golden_project(tmp_path)
    # No further commit -- the capsule is still FRESH, so this category must
    # NOT fire, and the base 4-class verdict is what a caller sees.
    hole = {"coverage_id": "cov_gs"}
    result = classify_coverage_hole_taxonomy(root, hole)
    assert result["taxonomy_classification"] != TAXONOMY_GOLDEN_SCENARIO_STALE_EVIDENCE_HOLE


# ---- build_hole_evidence_record / build_hole_evidence_records --------------

def test_build_hole_evidence_record_always_cites_registry_and_evidence_db_sources(tmp_path):
    hole = {"coverage_id": "cov_plain2"}
    record = build_hole_evidence_record(tmp_path, hole)
    sources = [e["source"] for e in record["evidence"]]
    assert "requirements_registry" in sources
    assert "evidence_db.jobs" in sources
    assert record["coverage_id"] == "cov_plain2"
    assert record["root_cause_classification"] == ROOT_CAUSE_MISSING_TEST
    assert record["taxonomy_classification"] is None


def test_build_hole_evidence_record_appends_taxonomy_specific_evidence(tmp_path):
    hole = {"coverage_id": "cov_reg2", "register_name": "USB3_LINK_CTRL",
            "register_fields": ["LFPS_EN", "U1_TIMEOUT"]}
    record = build_hole_evidence_record(tmp_path, hole)
    assert record["taxonomy_classification"] == TAXONOMY_REGISTER_FIELD_COMBINATION_HOLE
    sources = [e["source"] for e in record["evidence"]]
    assert sources.count("requirements_registry") == 1
    assert sources.count("evidence_db.jobs") == 1
    assert "hole_declared_field" in sources


def test_build_hole_evidence_records_skips_non_dict_entries_and_batches(tmp_path):
    holes = [
        {"coverage_id": "cov_a", "waived": True},
        "not_a_hole_dict",
        {"coverage_id": "cov_b", "bin_kind": "illegal"},
    ]
    records = build_hole_evidence_records(tmp_path, holes)
    assert len(records) == 2
    assert records[0]["taxonomy_classification"] == TAXONOMY_WAIVED_HOLE_EXCLUDED
    assert records[1]["taxonomy_classification"] == TAXONOMY_ILLEGAL_BIN_MISCLASSIFIED


# ---- FUNCTIONAL vs CODE coverage-kind classification (M5 Cohort 5,
# CAP-M5-COV-001, migrated from Parent) --------------------------------------

def test_coverage_kind_classes_are_exactly_functional_and_code():
    # No third kind (e.g. ASSERTION) exists in this codebase's own real
    # producers/consumers today -- see the section docstring.
    assert COVERAGE_KIND_CLASSES == (COVERAGE_KIND_FUNCTIONAL, COVERAGE_KIND_CODE)


def test_code_coverage_metric_names_match_the_real_makefile_cm_opts():
    # tools/coverage/urg_summary_reduce.py still locally re-declares an
    # identical-value CODE_COVERAGE_METRICS constant rather than importing
    # this one -- a disclosed, not-yet-closed consolidation opportunity (see
    # coverage_analysis.py's own section docstring), not implied closed here.
    assert CODE_COVERAGE_METRIC_NAMES == ("line", "cond", "fsm", "tgl", "branch")


@pytest.mark.parametrize("name", ["line", "cond", "fsm", "tgl", "branch"])
def test_classify_coverage_kind_recognises_every_code_coverage_metric(name):
    assert classify_coverage_kind(name) == COVERAGE_KIND_CODE


def test_classify_coverage_kind_is_case_insensitive_and_strips_whitespace():
    assert classify_coverage_kind("LINE") == COVERAGE_KIND_CODE
    assert classify_coverage_kind("  Branch  ") == COVERAGE_KIND_CODE


@pytest.mark.parametrize("name", [
    "functional", "cov_a", "usb3_link_state_cg", "fsm_state", "None", "", None,
])
def test_classify_coverage_kind_defaults_to_functional_for_everything_else(name):
    # "fsm_state" (a real category name used elsewhere in this file's own
    # _valid_summary() fixture) is deliberately included: it is NOT the
    # literal code-coverage metric "fsm" and must not be misclassified by a
    # substring/fuzzy match.
    assert classify_coverage_kind(name) == COVERAGE_KIND_FUNCTIONAL


def test_tag_categories_by_kind_adds_kind_without_mutating_input():
    categories = [
        {"name": "line", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_a", "percent": 50.0, "bins_total": 4, "bins_hit": 2},
    ]
    original = [dict(c) for c in categories]
    tagged = tag_categories_by_kind(categories)
    assert categories == original  # input dicts untouched
    assert tagged[0]["kind"] == COVERAGE_KIND_CODE
    assert tagged[1]["kind"] == COVERAGE_KIND_FUNCTIONAL
    # everything else is carried through unchanged
    assert tagged[0]["percent"] == 100.0 and tagged[0]["bins_hit"] == 10
    assert tagged[1]["percent"] == 50.0 and tagged[1]["bins_hit"] == 2


def test_tag_categories_by_kind_empty_input_is_empty_output():
    assert tag_categories_by_kind([]) == []
    assert tag_categories_by_kind(None) == []
