"""Tests for dv_harness/vip_distill.py -- Evidence Normalization ONLY.

Fixtures reuse the same real-shaped sim.log epilogue format
test_sim_log_analysis.py already validates ("FINAL CHECK @ <time> ns" /
"UVM_FATAL = N, UVM_ERROR = N, UVM_WARNING = N" / "VERDICT: PASSED|FAILED"),
and a job-record dict shaped exactly like
`dv_harness.lsf_client._upsert_job_tier_memory_record()` actually builds
(same field names: memory_id/kind/job_id/pattern/lsf_status/
dv_analysis_status/uvm_error_count/uvm_fatal_count/terminal_signature),
so these tests exercise vip_distill.py against real project evidence
shapes, not invented ones.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dv_harness import vip_distill as vd

CLEAN_PASS_LOG = """\
UVM_INFO test_top.sv(42) @ 100000: reporter [TEST] starting basic_ss_serial
FINAL CHECK @ 300000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 2
VERDICT: PASSED
"""

FAILING_LOG = """\
UVM_ERROR test_top.sv(10) @ 1000 ns: scoreboard mismatch on port 2
UVM_ERROR test_top.sv(10) @ 2000 ns: scoreboard mismatch on port 2
UVM_FATAL test_top.sv(99) @ 5000 ns: unrecoverable protocol violation
FINAL CHECK @ 6000 ns
UVM_FATAL = 1, UVM_ERROR = 2, UVM_WARNING = 0
VERDICT: FAILED
"""

JOB_FAILURE_RECORD = {
    "memory_id": "JOB-4242-TERMINAL-RECONCILE",
    "kind": "job_failure",
    "job_id": 4242,
    "pattern": "basic_ss_serial",
    "scope": "regression",
    "title": "LSF job 4242 reached EXIT (dv_analysis_status=ANALYSIS_OWED)",
    "lsf_status": "EXIT",
    "dv_analysis_status": "ANALYSIS_OWED",
    "uvm_error_count": 2,
    "uvm_fatal_count": 1,
    "terminal_signature": "UVM_FATAL:unrecoverable_protocol_violation",
    "sim_status": "FAIL",
}

FSDB_CSV_TEXT = "signal,timestamp,value\ntb.dut.clk,100,1\ntb.dut.clk,200,0\n"


# ---------------------------------------------------------------------------
# distill_sim_log
# ---------------------------------------------------------------------------

class TestDistillSimLog:
    def test_requires_exactly_one_of_text_or_path(self):
        with pytest.raises(vd.VipDistillError):
            vd.distill_sim_log()
        with pytest.raises(vd.VipDistillError):
            vd.distill_sim_log(log_text="x", log_path="y")

    def test_clean_pass_log_normalizes_to_passed_no_signatures(self):
        env = vd.distill_sim_log(log_text=CLEAN_PASS_LOG, job_id=1, pattern="basic_ss_serial")
        assert env["schema_version"] == vd.NORMALIZED_EVIDENCE_SCHEMA_VERSION
        assert env["source_kind"] == "sim_log"
        assert env["job_id"] == 1
        assert env["pattern"] == "basic_ss_serial"
        assert env["verdict"] == "PASSED"
        assert env["counts"] == {"uvm_fatal": 0, "uvm_error": 0, "uvm_warning": 2}
        assert env["detail"]["signatures"] == []
        assert env["provenance"]["parser"] == "sim_log_analysis.parse_sim_log"

    def test_failing_log_normalizes_signatures_and_verdict(self):
        env = vd.distill_sim_log(log_text=FAILING_LOG)
        assert env["verdict"] == "FAILED"
        assert env["counts"] == {"uvm_fatal": 1, "uvm_error": 2, "uvm_warning": 0}
        sigs = env["detail"]["signatures"]
        assert len(sigs) == 2
        # worst severity (uvm_fatal/CRITICAL via scoreboard/mismatch priority
        # rules already tested in test_sim_log_analysis.py) sorts first.
        assert sigs[0]["severity"] == "CRITICAL"
        # job_id/pattern were not supplied -- must be absent, not null.
        assert "job_id" not in env
        assert "pattern" not in env

    def test_from_file_path_carries_source_path_and_no_epilogue_log(self):
        tmp = Path(tempfile.mkdtemp())
        log_path = tmp / "sim.log"
        log_path.write_text("UVM_INFO nothing interesting here\n", encoding="utf-8")
        env = vd.distill_sim_log(log_path=str(log_path))
        assert env["provenance"]["source_path"] == str(log_path)
        assert env["verdict"] is None  # no epilogue present -- never fabricated
        assert env["detail"]["epilogue"] is None

    def test_same_input_yields_same_evidence_id(self):
        a = vd.distill_sim_log(log_text=FAILING_LOG, job_id=1)
        b = vd.distill_sim_log(log_text=FAILING_LOG, job_id=1)
        assert a["evidence_id"] == b["evidence_id"]

    def test_different_job_id_yields_different_evidence_id(self):
        a = vd.distill_sim_log(log_text=FAILING_LOG, job_id=1)
        b = vd.distill_sim_log(log_text=FAILING_LOG, job_id=2)
        assert a["evidence_id"] != b["evidence_id"]


# ---------------------------------------------------------------------------
# distill_job_record
# ---------------------------------------------------------------------------

class TestDistillJobRecord:
    def test_rejects_non_dict_or_empty(self):
        with pytest.raises(vd.VipDistillError):
            vd.distill_job_record({})
        with pytest.raises(vd.VipDistillError):
            vd.distill_job_record(None)  # type: ignore[arg-type]

    def test_normalizes_real_job_failure_record_shape(self):
        env = vd.distill_job_record(JOB_FAILURE_RECORD)
        assert env["source_kind"] == "job_record"
        assert env["job_id"] == 4242
        assert env["pattern"] == "basic_ss_serial"
        assert env["verdict"] == "FAIL"
        assert env["counts"] == {"uvm_fatal": 1, "uvm_error": 2, "uvm_warning": None}
        assert env["detail"]["lsf_status"] == "EXIT"
        assert env["detail"]["terminal_signature"] == "UVM_FATAL:unrecoverable_protocol_violation"
        assert env["provenance"]["source_memory_id"] == "JOB-4242-TERMINAL-RECONCILE"
        assert env["provenance"]["source_kind_original"] == "job_failure"

    def test_unknown_sim_status_yields_no_verdict(self):
        rec = dict(JOB_FAILURE_RECORD)
        rec["sim_status"] = "UNKNOWN"
        env = vd.distill_job_record(rec)
        assert env["verdict"] is None

    def test_extra_unrecognized_fields_are_ignored_not_errors(self):
        rec = dict(JOB_FAILURE_RECORD)
        rec["some_future_field_this_module_has_never_heard_of"] = "whatever"
        env = vd.distill_job_record(rec)  # must not raise
        assert "some_future_field_this_module_has_never_heard_of" not in env["detail"]


# ---------------------------------------------------------------------------
# distill_fsdbreport
# ---------------------------------------------------------------------------

class TestDistillFsdbreport:
    def test_requires_exactly_one_of_text_or_parsed(self):
        with pytest.raises(vd.VipDistillError):
            vd.distill_fsdbreport()
        with pytest.raises(vd.VipDistillError):
            vd.distill_fsdbreport(report_text="x", parsed_report={"parsed": False})

    def test_normalizes_real_csv_report_text(self):
        env = vd.distill_fsdbreport(report_text=FSDB_CSV_TEXT, fsdb_path="/tmp/dump.fsdb", topic="clk_check")
        assert env["source_kind"] == "fsdbreport"
        assert env["verdict"] is None  # fsdbreport has no PASS/FAIL concept
        assert env["counts"] is None
        assert env["detail"]["fsdbreport"]["parsed"] is True
        assert env["detail"]["fsdbreport"]["fieldnames"] == ["signal", "timestamp", "value"]
        assert env["provenance"]["parser"] == "fsdb_report.parse_fsdbreport_output"

    def test_unparseable_text_still_normalizes_honestly(self):
        env = vd.distill_fsdbreport(report_text="not a csv report at all")
        assert env["detail"]["fsdbreport"]["parsed"] is False

    def test_accepts_already_parsed_report(self):
        from dv_harness import fsdb_report as fr
        parsed = fr.parse_fsdbreport_output(FSDB_CSV_TEXT)
        env = vd.distill_fsdbreport(parsed_report=parsed)
        assert env["detail"]["fsdbreport"] == parsed


# ---------------------------------------------------------------------------
# merge_evidence
# ---------------------------------------------------------------------------

class TestMergeEvidence:
    def test_requires_at_least_two_components(self):
        one = vd.distill_sim_log(log_text=FAILING_LOG)
        with pytest.raises(vd.VipDistillError):
            vd.merge_evidence([one])

    def test_rejects_a_combined_component(self):
        a = vd.distill_sim_log(log_text=FAILING_LOG, job_id=1)
        b = vd.distill_job_record(JOB_FAILURE_RECORD)
        combined = vd.merge_evidence([a, b], job_id=1)
        with pytest.raises(vd.VipDistillError):
            vd.merge_evidence([combined, a])

    def test_merges_sim_log_and_job_record_failure_wins(self):
        sim_env = vd.distill_sim_log(log_text=FAILING_LOG, job_id=4242, pattern="basic_ss_serial")
        job_env = vd.distill_job_record(JOB_FAILURE_RECORD)
        merged = vd.merge_evidence([sim_env, job_env], job_id=4242, pattern="basic_ss_serial",
                                    protocol="USB")
        assert merged["source_kind"] == "combined"
        assert merged["verdict"] == "FAILED"
        # uvm_fatal: sim_log=1 + job_record=1 = 2 (pure arithmetic sum over
        # what the components already state, never re-derived from raw text)
        assert merged["counts"]["uvm_fatal"] == 2
        assert merged["counts"]["uvm_error"] == 4
        assert merged["detail"]["aggregate"]["worst_severity"] == "CRITICAL"
        assert merged["detail"]["aggregate"]["component_count"] == 2
        assert set(merged["provenance"]["merged_from_evidence_ids"]) == {
            sim_env["evidence_id"], job_env["evidence_id"]
        }

    def test_merge_is_deterministic_regardless_of_component_order(self):
        a = vd.distill_sim_log(log_text=CLEAN_PASS_LOG, job_id=1)
        b = vd.distill_job_record({**JOB_FAILURE_RECORD, "job_id": 1, "sim_status": "PASS",
                                    "uvm_fatal_count": 0, "uvm_error_count": 0})
        m1 = vd.merge_evidence([a, b], job_id=1)
        m2 = vd.merge_evidence([b, a], job_id=1)
        assert m1["verdict"] == m2["verdict"] == "AMBIGUOUS"
        # PASSED (sim_log) + PASS (job_record) are different literal strings
        # on purpose (each component's own real vocabulary is preserved,
        # never silently coerced) -- so the honest combined verdict here is
        # AMBIGUOUS, not a guessed PASS.


# ---------------------------------------------------------------------------
# write_normalized_evidence
# ---------------------------------------------------------------------------

class TestWriteNormalizedEvidence:
    def test_writes_valid_json_creating_parent_dirs(self):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "nested" / "evidence.json"
        env = vd.distill_sim_log(log_text=FAILING_LOG)
        path = vd.write_normalized_evidence(env, out)
        assert path == out
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["evidence_id"] == env["evidence_id"]


# ---------------------------------------------------------------------------
# Scope guard: this module must never import orchestration/memory/job-control
# modules -- a static check that the narrow scope isn't quietly reopened.
# ---------------------------------------------------------------------------

def test_module_does_not_import_orchestration_or_memory_modules():
    """Checks actual `import`/`from ... import` statements only -- the
    module's own docstrings legitimately NAME memory_router/lsf_client/etc.
    while explaining what this module deliberately does NOT do, so a plain
    substring scan over the whole file would false-positive on its own
    scope documentation."""
    import ast
    import dv_harness.vip_distill as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module)
            imported_names.update(alias.name for alias in node.names)
    forbidden = {"memory_router", "memory_vault", "lsf_client", "route_and_store",
                 "bsub_submit", "MemoryStore", "duckdb", "preflight",
                 "evidence_db", "regression_reporter"}
    hit = imported_names & forbidden
    assert not hit, f"vip_distill.py must stay evidence-normalization-only; found forbidden import(s): {hit}"
