"""Memory engine JOB tier -> DuckDB mirror WIRING (2026-09-04,
5-level-memory-engine gap-close).

`EvidenceStore.insert_job_memory_record()` is the one function in
`dv_harness/evidence_db.py` whose entire purpose is mirroring the 5-level
Memory engine's JOB tier into DuckDB: it is the sole writer of the
`job_memory_records` table, and the sole writer of the cross-run
`failure_signatures` aggregate ("has this exact failure shape been seen
before, and how often") that table exists to feed.

A 2026-09-04 re-audit of the memory engine found it had ZERO callers
anywhere outside `evidence_db.py` and its own unit tests, while BOTH of its
siblings inside the very same
`regression_reporter._write_reconciliation_evidence_if_configured()` body --
`insert_job_state()` and `insert_regression_verdict()` -- were wired into the
real reconciliation cycle. Net effect: a real cycle recorded the job and its
verdict, but never the job's Memory-tier record, and `failure_signatures`
stayed permanently empty no matter how many real failures reconciled.

These tests are deliberately about the WIRE, not the function. That
`insert_job_memory_record()` works in isolation was never the gap and is
already covered by `test_evidence_db.py`. Every memory record here is
produced by the REAL production writer
(`lsf_client._upsert_job_tier_memory_record()`, the same one
`reconcile_batch()` and `run_reconciliation_cycle()` call) -- never a
hand-built dict -- so what is asserted is that a real Memory-tier record
really reaches DuckDB through the real cycle. Only the LSF discovery layer
is mocked, exactly as `test_evidence_db_wiring.py` already does.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import regression_reporter as rr
from dv_harness import lsf_client
from dv_harness.evidence_db import EvidenceStore, default_db_path


FAILING_SIM_LOG = (
    "some output\nFINAL CHECK @ 2000 ns\n"
    "UVM_FATAL = 1, UVM_ERROR = 3, UVM_WARNING = 0\nVERDICT: FAILED\n"
)


def _write_job(root, job_id, **kwargs):
    state = lsf_client.JobState(job_id=job_id, **kwargs)
    lsf_client.save_job_state(root, state)
    return state


def _failing_job_on_disk(tmp_path, job_id, pattern, run_name):
    run_dir = tmp_path / "sim" / "run" / run_name
    run_dir.mkdir(parents=True)
    log_path = run_dir / "sim.log"
    log_path.write_text(FAILING_SIM_LOG, encoding="utf-8")
    _write_job(tmp_path, job_id, pattern=pattern, sim_log=str(log_path),
               lsf_status="RUN")
    return [{"job_id": job_id, "stat": "EXIT", "queue": "normal",
             "exec_host": "host1", "job_name": pattern, "submit_time": "x"}]


class TestJobMemoryRecordMirror:
    def test_real_memory_tier_record_on_disk_is_mirrored_into_job_memory_records(self, tmp_path):
        """The Memory tier's real JSON record for a job lands in DuckDB's
        `job_memory_records`, keyed by the same deterministic memory_id both
        sides already agree on (`lsf_client.job_tier_memory_id()`)."""
        state = lsf_client.JobState(job_id=777, pattern="usb3_lfps_basic",
                                    lsf_status="DONE", sim_status="PASS",
                                    uvm_error_count=0, uvm_fatal_count=0)
        lsf_client.save_job_state(tmp_path, state)
        lsf_client._upsert_job_tier_memory_record(tmp_path, 777, state)

        # Precondition: the JSON Memory tier really holds it. If this ever
        # fails, the test below is meaningless rather than merely failing.
        on_disk = lsf_client.load_job_tier_memory_record(tmp_path, 777)
        assert on_disk is not None and on_disk["kind"] == "job_result"

        rr._write_reconciliation_evidence_if_configured(tmp_path, {777: (state, [])})

        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query(
                "SELECT memory_id, kind, job_id, pattern, lsf_status "
                "FROM job_memory_records"
            ) == [(lsf_client.job_tier_memory_id(777), "job_result", 777,
                   "usb3_lfps_basic", "DONE")]

    def test_job_with_no_memory_tier_record_mirrors_nothing(self, tmp_path):
        """An absent Job-tier memory record is a real, normal state (the job
        never reached a terminal reconcile). It is skipped, never backfilled
        with an invented row -- while the job's own `jobs` row, which does
        not depend on the memory tier at all, is still written."""
        state = lsf_client.JobState(job_id=888, pattern="no_memory_yet",
                                    lsf_status="RUN", sim_status="UNKNOWN")
        assert lsf_client.load_job_tier_memory_record(tmp_path, 888) is None

        rr._write_reconciliation_evidence_if_configured(tmp_path, {888: (state, [])})

        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query("SELECT count(*) FROM job_memory_records")[0][0] == 0
            assert store.query("SELECT job_id FROM jobs") == [(888,)]

    def test_one_bad_mirror_insert_is_isolated_to_its_own_job(self, tmp_path):
        """Same per-job isolation the rest of this function already
        guarantees: a bad `job_memory_records` insert for one job must not
        cost every sibling job in the same cycle its evidence. Pins the REAL
        behavior, including the honest cost -- the failing job shares one
        try/except with its own verdict write, so IT loses that too; no other
        job does."""
        good = lsf_client.JobState(job_id=901, pattern="good_one",
                                   lsf_status="DONE", sim_status="PASS")
        bad = lsf_client.JobState(job_id=902, pattern="bad_one",
                                  lsf_status="DONE", sim_status="PASS")
        for st in (good, bad):
            lsf_client.save_job_state(tmp_path, st)
            lsf_client._upsert_job_tier_memory_record(tmp_path, st.job_id, st)

        real_insert = EvidenceStore.insert_job_memory_record

        def _raise_for_902(self, record):
            if record.get("job_id") == 902:
                raise RuntimeError("simulated bad job_memory_records insert")
            return real_insert(self, record)

        with patch.object(EvidenceStore, "insert_job_memory_record", _raise_for_902):
            rr._write_reconciliation_evidence_if_configured(
                tmp_path, {902: (bad, []), 901: (good, [])})

        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query(
                "SELECT job_id FROM job_memory_records ORDER BY job_id") == [(901,)]
            assert store.query(
                "SELECT pattern FROM regression_verdicts ORDER BY pattern") == [("good_one",)]
            # Both `jobs` rows were written before the failure point.
            assert store.query("SELECT job_id FROM jobs ORDER BY job_id") == [(901,), (902,)]


class TestReconciliationCycleEndToEndJobMemoryMirror:
    def test_full_cycle_failing_job_lands_in_job_memory_records_and_failure_signatures(self, tmp_path):
        """THE gap-closing test: one real `run_reconciliation_cycle()` over a
        genuinely FAILING job leaves BOTH halves of the Memory->DuckDB mirror
        populated -- the `job_memory_records` row AND the cross-run
        `failure_signatures` aggregate that was permanently empty before this
        wiring landed.

        The mirrored record is never constructed by this test: the cycle's
        own `_upsert_job_tier_memory_record()` call (which runs AFTER the
        real sim.log epilogue parse, and is what upgrades a premature
        `job_result` classification to the accurate `job_failure` one with a
        real failure_signature attached) is its only writer."""
        uvm_root = tmp_path / "uvm"
        live_bjobs = _failing_job_on_disk(tmp_path, 555, "usb3_lfps_fail", "lfps_fail_1")

        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "555", "STAT": "EXIT"}]}):
            rr.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        # The JSON Memory tier really holds a job_failure record for it...
        mem = lsf_client.load_job_tier_memory_record(tmp_path, 555)
        assert mem is not None
        assert mem["kind"] == "job_failure"
        assert mem.get("failure_signature")

        # ...and DuckDB now mirrors that SAME record, with no drift.
        with EvidenceStore(default_db_path(tmp_path)) as store:
            rows = store.query(
                "SELECT memory_id, kind, job_id, pattern, uvm_error_count, uvm_fatal_count "
                "FROM job_memory_records WHERE job_id = 555")
            assert rows == [(mem["memory_id"], "job_failure", 555, "usb3_lfps_fail",
                             mem["uvm_error_count"], mem["uvm_fatal_count"])]
            assert rows[0][0] == lsf_client.job_tier_memory_id(555)

            sig_json = store.query(
                "SELECT failure_signature_json FROM job_memory_records "
                "WHERE job_id = 555")[0][0]
            assert json.loads(sig_json) == mem["failure_signature"]

            # The cross-run aggregate the whole table was built for is no
            # longer empty: one real occurrence of one real failure shape.
            assert store.query(
                "SELECT occurrence_count, sample_job_id, sample_memory_id "
                "FROM failure_signatures") == [(1, 555, mem["memory_id"])]

    def test_second_cycle_over_the_same_failure_accumulates_occurrence_count(self, tmp_path):
        """What the mirror is FOR. Two real reconciliation cycles over the
        same failing job upsert ONE `job_memory_records` row (deterministic
        memory_id) while ACCUMULATING the `failure_signatures`
        occurrence_count -- repeat occurrences of one failure shape become
        one countable fact instead of duplicate rows.

        `_job_still_owes_reconciliation` is patched True only so the second
        cycle re-reconciles a job the first cycle legitimately settled (that
        bounding filter is real, correct, and tested elsewhere -- it is not
        what this test is about)."""
        uvm_root = tmp_path / "uvm"
        live_bjobs = _failing_job_on_disk(tmp_path, 556, "usb3_repeat_fail", "repeat_fail_1")

        for _ in range(2):
            with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                       return_value=live_bjobs), \
                 patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                       return_value={"RECORDS": [{"JOBID": "556", "STAT": "EXIT"}]}), \
                 patch("dv_harness.regression_reporter._job_still_owes_reconciliation",
                       return_value=True):
                rr.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        with EvidenceStore(default_db_path(tmp_path)) as store:
            assert store.query(
                "SELECT count(*) FROM job_memory_records WHERE job_id = 556")[0][0] == 1
            assert store.query("SELECT count(*) FROM failure_signatures")[0][0] == 1
            assert store.query(
                "SELECT occurrence_count FROM failure_signatures")[0][0] == 2


class TestInsertJobMemoryRecordIsNotDormant:
    """Static regression guard for the exact condition the 2026-09-04 audit
    found: `insert_job_memory_record()` real, tested and schema-backed, but
    with zero callers in production code. Every behavioral test above would
    disappear along with the call site in a refactor that removed both; this
    one fails the moment the production package stops calling it at all."""

    def test_a_real_production_module_calls_insert_job_memory_record(self):
        pkg = Path(rr.__file__).parent
        callers = set()
        for py in pkg.rglob("*.py"):
            if py.name == "evidence_db.py":
                continue  # the definition site itself is not a caller
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "insert_job_memory_record"):
                    callers.add(py.name)
        assert callers, (
            "insert_job_memory_record() has no caller anywhere in dv_harness/ -- "
            "the Memory JOB tier -> DuckDB mirror is dormant again")
        assert "regression_reporter.py" in callers
