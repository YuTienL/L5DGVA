# Background Job Monitor + Regression-List Safety Net Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `dv_harness` real, background LSF-job visibility (any job under the account, registered or not) and a regression-list safety net for jobs that bypass the generated environment's own Makefile-native `RECORD=1` mechanism.

**Architecture:** `lsf_client.py` gains two new subprocess-wrapping functions (`discover_live_jobs`, `register_external_job`); `regression_list_manager.py` gains one new file-I/O wrapper around its existing pure `record_verdict()`; `regression_reporter.py` gains a reconciliation-cycle orchestrator, a watch-loop rewrite that calls it, and a PID-file-based watcher lifecycle; `cli.py` gains three new subcommands exposing that lifecycle. A CLAUDE.md protocol addition — not code — is how "auto-start" is actually achieved, because this codebase's Execution Mode Gate is agent-conversational evidence, not a Python event with a hookable call site (confirmed by investigation below).

**Tech Stack:** Python 3 (stdlib only: `subprocess`, `json`, `pathlib`, `time`, `os`), `pytest` with `unittest.mock.patch`.

**Spec:** `docs/superpowers/specs/2026-09-01-sim-output-layout-and-background-job-monitor-design.md` (Part 2 and Part 3; Part 1 requires no implementation work — see note below).

## Part 1 status: already fully implemented, no tasks in this plan

Investigation during plan-writing found that Part 1 (the `sim/` directory layout, including the `run/`-is-real / `report/`+`log/`-are-symlink-views design) is **already fully implemented** in `dv_harness/uvm_generator/templates/sim_scripts/Makefile`:

- `run:` target (Makefile line ~2695-2706) creates `$(PAT_RUN)`/`$(PAT_REPORT)` fresh and links `$(PAT_LOG_LINK)` (`log/<job>.log`) and `$(PAT_REPORT)/sim.log` to the real `$(PAT_LOG)` (`run/<job>/sim.log`) **before** `simv` is invoked later in the same recipe — exactly the hard-kill-resilience property the spec requires.
- `collect_reports:` target (line ~2829+) separately links the remaining artifacts (fsdb, coverage, rundir) into `report/<job>/` after the run finishes.
- `IP_UVM_DV_Gen.md` (line ~1904-1909) already documents this exact contract, added by the same distillation work that produced this spec's Part 1.

No further code or doc changes are needed for Part 1. Do not add a task that re-does this.

One naming-convention correction for implementers of Part 2/3 below: the real Makefile keys everything by `$(JOB)` = `<pattern>_<seed>`, not by the raw LSF job ID (an LSF job ID is ephemeral across reruns; pattern+seed is stable and human-meaningful). `register_external_job()` (Task 2) takes `log_path` as an explicit caller-supplied string for exactly this reason — never derive a log path from a job ID.

## Part 2 real-architecture finding: there is no Python call site for "REMOTE_EXECUTION begins"

The spec's original Part 2 said to "hook the watcher's start into the real code path that handles Execution Mode Gate declaration... confirm the exact real call site before implementing." Investigation found there is no such call site:

- `tools/real_env/execution_mode_validator.py` is a standalone script invoked with `--request <file>` — an agent runs it as a subprocess as part of following the CLAUDE.md protocol, then embeds its JSON result as an evidence block inside its own conversational message text.
- `dv_harness/gates.py` (line 61) registers it as an external, subprocess-invoked gate script, not an in-process function.
- `dv_harness/dashboard.py:_execution_mode()` (line ~1063-1076) is a pure **reader**: it re-parses `.dv-harness/state.json`'s stored `ENV_CHECK` stage's `last_message` text for that evidence block, purely for GUI display. It has no side effects and is not called at the moment the mode is declared.

In short: execution-mode declaration is agent-conversational evidence, not a Python event. There is nothing to attach a background-process launcher to. Task 8 below addresses "auto-start" the same way this codebase already achieves everything else in this gate family (e.g. SSH/Remote Transport Connection Intake) — a required protocol instruction telling the agent what command to run, not a code hook.

## Global Constraints

- Every new/modified function must have real, deterministic tests — no live LSF farm required (mock `subprocess.run`, matching `dv_harness_tests/test_lsf_client.py`'s existing pattern).
- Never introduce a second, divergent definition of "passed" — the sole source of truth for a job's pass/fail verdict is `dv_harness/sim_log_analysis.py:parse_sim_log_file()`'s `epilogue["verdict"]` field (`"PASSED"`, `"FAILED"`, or `None`/missing when indeterminate).
- Do not add detection logic to skip the Part 3 regression-list wiring when the Make-native mechanism might have already handled the same job — rely on `record_verdict()`'s existing idempotency instead (per the spec's explicit YAGNI ruling).
- `regression.list`'s real path is `<project>/uvm/regression.list` (`UVM_ROOT_PATH`), never under `SIM_ROOT_PATH`.
- Do not re-test `record_verdict()`/`record_suite()` themselves (`dv_harness_tests/test_regression_list_manager.py` already covers them fully, including idempotency) — only new call sites and new functions need new tests.
- Commit after each task, using `git add <specific files>` (never `git add -A`).

---

### Task 1: `discover_live_jobs()` in `lsf_client.py`

**Files:**
- Modify: `dv_harness/lsf_client.py`
- Test: `dv_harness_tests/test_lsf_client.py`

**Interfaces:**
- Consumes: nothing new (uses stdlib `subprocess`, matches the existing `_run_bjobs()` pattern in the same file).
- Produces: `discover_live_jobs(vcuser: str) -> list[dict]`, one dict per live job with keys `{"job_id": int, "stat": str, "queue": str, "exec_host": str, "job_name": str, "submit_time": str}`. Later tasks (Task 4) call this directly.

- [ ] **Step 1: Write the failing test**

Add to `dv_harness_tests/test_lsf_client.py`:

```python
class TestDiscoverLiveJobs:
    def test_parses_bjobs_json_output(self):
        raw = json.dumps({
            "RECORDS": [
                {"JOBID": "111", "STAT": "RUN", "QUEUE": "normal",
                 "EXEC_HOST": "host1", "JOB_NAME": "usb2_enum_1",
                 "SUBMIT_TIME": "Sep  1 10:00"},
                {"JOBID": "222", "STAT": "PEND", "QUEUE": "normal",
                 "EXEC_HOST": "", "JOB_NAME": "usb3_gen1_2",
                 "SUBMIT_TIME": "Sep  1 10:05"},
            ]
        })
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=raw)) as m:
            jobs = lsf_client.discover_live_jobs("vcuser1")
        argv = m.call_args.args[0]
        assert argv[0] == "bjobs"
        assert "-u" in argv and "vcuser1" in argv
        assert jobs == [
            {"job_id": 111, "stat": "RUN", "queue": "normal",
             "exec_host": "host1", "job_name": "usb2_enum_1",
             "submit_time": "Sep  1 10:00"},
            {"job_id": 222, "stat": "PEND", "queue": "normal",
             "exec_host": "", "job_name": "usb3_gen1_2",
             "submit_time": "Sep  1 10:05"},
        ]

    def test_no_jobs_returns_empty_list(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=json.dumps({"RECORDS": []}))):
            assert lsf_client.discover_live_jobs("vcuser1") == []

    def test_lsf_unavailable_raises(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   side_effect=FileNotFoundError("no bjobs")):
            with pytest.raises(lsf_client.LsfUnavailableError):
                lsf_client.discover_live_jobs("vcuser1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestDiscoverLiveJobs -v`
Expected: FAIL with `AttributeError: module 'dv_harness.lsf_client' has no attribute 'discover_live_jobs'`

- [ ] **Step 3: Write minimal implementation**

Add to `dv_harness/lsf_client.py`, after `bjobs_query_many()`:

```python
def discover_live_jobs(vcuser: str) -> list[dict]:
    """Real LSF status for every job under `vcuser`, independent of whether
    any of them were ever submitted via this module's own bsub_submit() or
    registered via register_external_job(). Used by Part 2's reconciliation
    cycle for baseline visibility -- a job with no registered JobState still
    shows up here with RUN/DONE/EXIT/PEND status."""
    argv = ["bjobs", "-u", vcuser, "-json", "-o",
            "jobid stat queue exec_host job_name submit_time"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError as e:
        raise LsfUnavailableError(f"bjobs not found on PATH: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise LsfUnavailableError(f"bjobs timed out: {e}") from e
    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise LsfUnavailableError(
            f"failed to parse bjobs -json output: {e}; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from e
    records = parsed.get("RECORDS") or []
    result = []
    for rec in records:
        try:
            jid = int(rec.get("JOBID"))
        except (TypeError, ValueError):
            continue
        result.append({
            "job_id": jid,
            "stat": rec.get("STAT") or "",
            "queue": rec.get("QUEUE") or "",
            "exec_host": rec.get("EXEC_HOST") or "",
            "job_name": rec.get("JOB_NAME") or "",
            "submit_time": rec.get("SUBMIT_TIME") or "",
        })
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestDiscoverLiveJobs -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/lsf_client.py dv_harness_tests/test_lsf_client.py
git commit -m "feat: add discover_live_jobs() for baseline LSF status of every job under an account"
```

---

### Task 2: `register_external_job()` in `lsf_client.py`

**Files:**
- Modify: `dv_harness/lsf_client.py`
- Test: `dv_harness_tests/test_lsf_client.py`

**Interfaces:**
- Consumes: `JobState` dataclass and `save_job_state()` (both already in this file).
- Produces: `register_external_job(root: Path, job_id: int, *, log_path: str, pattern: Optional[str] = None) -> None`. Task 4's reconciliation cycle treats jobs registered this way identically to `bsub_submit()`-originated ones.

- [ ] **Step 1: Write the failing test**

Add to `dv_harness_tests/test_lsf_client.py`:

```python
class TestRegisterExternalJob:
    def test_writes_job_state_matching_bsub_submit_shape(self, tmp_path):
        lsf_client.register_external_job(tmp_path, 999, log_path="/proj/sim/run/foo_1/sim.log",
                                          pattern="foo")
        loaded = lsf_client.load_job_state(tmp_path, 999)
        assert loaded.job_id == 999
        assert loaded.pattern == "foo"
        assert loaded.sim_log == "/proj/sim/run/foo_1/sim.log"
        assert loaded.lsf_status == "UNKNOWN"

    def test_pattern_optional(self, tmp_path):
        lsf_client.register_external_job(tmp_path, 1000, log_path="/proj/sim/run/bar/sim.log")
        loaded = lsf_client.load_job_state(tmp_path, 1000)
        assert loaded.pattern is None

    def test_reconcile_batch_treats_registered_job_like_bsub_submit_job(self, tmp_path):
        lsf_client.register_external_job(tmp_path, 2000, log_path="/proj/sim/run/baz/sim.log",
                                          pattern="baz")
        live = {"JOBID": "2000", "STAT": "DONE", "EXIT_CODE": "0",
                "EXEC_HOST": "host1", "QUEUE": "normal", "RUN_TIME": "10",
                "SUBMIT_TIME": "x", "JOB_NAME": "baz"}
        with patch("dv_harness.lsf_client._run_bjobs",
                   return_value={"RECORDS": [live]}):
            result = lsf_client.reconcile_batch(tmp_path, [2000])
        state, discrepancies = result[2000]
        assert state.lsf_status == "DONE"
        assert any(d.field == "sim_status" and d.severity == "CRITICAL" for d in discrepancies)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestRegisterExternalJob -v`
Expected: FAIL with `AttributeError: module 'dv_harness.lsf_client' has no attribute 'register_external_job'`

- [ ] **Step 3: Write minimal implementation**

Add to `dv_harness/lsf_client.py`, after `bkill_job()`:

```python
def register_external_job(root: Path, job_id: int, *, log_path: str,
                           pattern: Optional[str] = None) -> None:
    """Register a job that was submitted OUTSIDE this module's own
    bsub_submit() -- e.g. a generated environment's own Makefile-native
    `bsub` -- so reconcile_batch()/save_job_state() treat it identically to
    a bsub_submit()-originated job. Writes a fresh JobState with
    lsf_status="UNKNOWN" (the next reconcile_batch() call fills in the real
    status from a live bjobs poll)."""
    jid = _validate_job_id(job_id)
    state = JobState(job_id=jid, pattern=pattern, sim_log=log_path)
    save_job_state(root, state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestRegisterExternalJob -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/lsf_client.py dv_harness_tests/test_lsf_client.py
git commit -m "feat: add register_external_job() for jobs submitted outside bsub_submit()"
```

---

### Task 3: `apply_verdict_to_file()` in `regression_list_manager.py`

**Files:**
- Modify: `dv_harness/uvm_generator/regression_list_manager.py`
- Test: `dv_harness_tests/test_regression_list_manager.py`

**Interfaces:**
- Consumes: `record_verdict()` (already in this file, unchanged).
- Produces: `apply_verdict_to_file(regression_list_path: Path, pattern: str, verdict_passed: bool) -> None`. Task 4's reconciliation cycle calls this directly.

- [ ] **Step 1: Write the failing test**

Add to `dv_harness_tests/test_regression_list_manager.py`:

```python
from pathlib import Path

from dv_harness.uvm_generator.regression_list_manager import (
    record_verdict, record_suite, emit_makefile_fragment, apply_verdict_to_file,
)


class TestApplyVerdictToFile:
    def test_creates_file_on_first_pass(self, tmp_path):
        path = tmp_path / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", True)
        assert path.read_text().splitlines() == ["usb2_enum"]

    def test_fail_does_not_create_file_with_pattern_present(self, tmp_path):
        path = tmp_path / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", False)
        assert path.read_text().splitlines() == []

    def test_fail_evicts_existing_pass(self, tmp_path):
        path = tmp_path / "regression.list"
        path.write_text("usb2_enum\nusb3_gen1_enum\n")
        apply_verdict_to_file(path, "usb2_enum", False)
        assert path.read_text().splitlines() == ["usb3_gen1_enum"]

    def test_calling_twice_with_same_verdict_is_idempotent(self, tmp_path):
        path = tmp_path / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", True)
        first = path.read_text()
        apply_verdict_to_file(path, "usb2_enum", True)
        second = path.read_text()
        assert first == second == "usb2_enum\n"

    def test_missing_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "nested" / "regression.list"
        apply_verdict_to_file(path, "usb2_enum", True)
        assert path.read_text().splitlines() == ["usb2_enum"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_regression_list_manager.py::TestApplyVerdictToFile -v`
Expected: FAIL with `ImportError: cannot import name 'apply_verdict_to_file'`

- [ ] **Step 3: Write minimal implementation**

Add to `dv_harness/uvm_generator/regression_list_manager.py`, after `record_verdict()`:

```python
from pathlib import Path


def apply_verdict_to_file(regression_list_path, pattern: str, verdict_passed: bool) -> None:
    """File-I/O wrapper around the pure record_verdict() -- reads the current
    regression.list (missing file treated as empty, matching a project's
    first-ever recorded pattern), applies record_verdict(), writes back.
    record_verdict() itself is unchanged and untouched by this wrapper."""
    path = Path(regression_list_path)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = record_verdict(existing, pattern, verdict_passed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(updated) + ("\n" if updated else ""), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_regression_list_manager.py::TestApplyVerdictToFile -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/uvm_generator/regression_list_manager.py dv_harness_tests/test_regression_list_manager.py
git commit -m "feat: add apply_verdict_to_file() file-I/O wrapper around record_verdict()"
```

---

### Task 4: `run_reconciliation_cycle()` in `regression_reporter.py`

**Files:**
- Modify: `dv_harness/regression_reporter.py`
- Test: `dv_harness_tests/test_regression_reporter.py` (new file)

**Interfaces:**
- Consumes: `lsf_client.discover_live_jobs()`, `lsf_client.reconcile_batch()`, `lsf_client.load_job_state()`, `lsf_client.save_job_state()`, `lsf_client.JobState` (Task 1, Task 2, and pre-existing); `sim_log_analysis.parse_sim_log_file()`, `sim_log_analysis.detect_underreporting()` (pre-existing); `regression_list_manager.apply_verdict_to_file()` (Task 3); `render_snapshot()` (pre-existing, same file).
- Produces: `run_reconciliation_cycle(root: Path, vcuser: str, uvm_root_path: Path) -> str` (returns the rendered snapshot text, also writes it to `.dv-harness/lsf/latest_snapshot.txt`). Task 5's watch loop calls this each cycle.

- [ ] **Step 1: Write the failing test**

Create `dv_harness_tests/test_regression_reporter.py`:

```python
"""Tests for dv_harness/regression_reporter.py's reconciliation cycle
(Part 2/Part 3 of the 2026-09-01 sim-output-layout-and-background-job-monitor
spec)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from dv_harness import regression_reporter, lsf_client


def _write_job(root, job_id, **kwargs):
    state = lsf_client.JobState(job_id=job_id, **kwargs)
    lsf_client.save_job_state(root, state)


class TestRunReconciliationCycle:
    def test_registered_job_gets_analyzed_and_regression_list_updated(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "foo_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text(
            "some output\nFINAL CHECK @ 1000 ns\n"
            "UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n"
        )
        _write_job(tmp_path, 111, pattern="foo", sim_log=str(log_path), lsf_status="RUN")

        live_bjobs = [{"job_id": 111, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "foo", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "111", "STAT": "DONE"}]}):
            regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        assert (uvm_root / "regression.list").read_text().splitlines() == ["foo"]
        updated = lsf_client.load_job_state(tmp_path, 111)
        assert updated.uvm_error_count == 0
        assert updated.uvm_fatal_count == 0

    def test_indeterminate_verdict_does_not_touch_regression_list(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        run_dir = tmp_path / "sim" / "run" / "bar_1"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "sim.log"
        log_path.write_text("no epilogue in this truncated log\n")
        _write_job(tmp_path, 222, pattern="bar", sim_log=str(log_path), lsf_status="RUN")

        live_bjobs = [{"job_id": 222, "stat": "DONE", "queue": "normal",
                       "exec_host": "host1", "job_name": "bar", "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs), \
             patch("dv_harness.regression_reporter.lsf_client._run_bjobs",
                   return_value={"RECORDS": [{"JOBID": "222", "STAT": "DONE"}]}):
            regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)

        assert not (uvm_root / "regression.list").exists()

    def test_unregistered_job_gets_unregistered_status_not_analyzed(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        live_bjobs = [{"job_id": 333, "stat": "RUN", "queue": "normal",
                       "exec_host": "host1", "job_name": "unregistered_job",
                       "submit_time": "x"}]
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   return_value=live_bjobs):
            snapshot = regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)
        assert "333" in snapshot
        assert not (uvm_root / "regression.list").exists()

    def test_one_failed_bjobs_call_does_not_raise(self, tmp_path):
        uvm_root = tmp_path / "uvm"
        with patch("dv_harness.regression_reporter.lsf_client.discover_live_jobs",
                   side_effect=lsf_client.LsfUnavailableError("down")):
            snapshot = regression_reporter.run_reconciliation_cycle(tmp_path, "vcuser1", uvm_root)
        assert isinstance(snapshot, str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v`
Expected: FAIL with `AttributeError: module 'dv_harness.regression_reporter' has no attribute 'run_reconciliation_cycle'`

- [ ] **Step 3: Write minimal implementation**

Add to `dv_harness/regression_reporter.py` (add imports at top, function after `render_snapshot()`):

```python
from dv_harness import lsf_client
from dv_harness.sim_log_analysis import parse_sim_log_file, detect_underreporting
from dv_harness.uvm_generator.regression_list_manager import apply_verdict_to_file
from dataclasses import asdict


def run_reconciliation_cycle(root: Path, vcuser: str, uvm_root_path: Path) -> str:
    """One pass of Part 2's reconciliation cycle: discover every live job
    under vcuser, reconcile+analyze the ones dv_harness has a registered
    JobState for (via bsub_submit() or register_external_job()), apply
    Part 3's regression-list safety net for any job with a real PASS/FAIL
    verdict and a known pattern, then render and persist the snapshot.

    A single failed discover_live_jobs()/reconcile_batch() call is caught
    and logged rather than raised, per the spec's error-handling
    requirement -- one bad LSF poll must not kill the whole cycle."""
    try:
        live_jobs = lsf_client.discover_live_jobs(vcuser)
    except lsf_client.LsfUnavailableError as e:
        print(f"[reconciliation_cycle] discover_live_jobs failed: {e}", flush=True)
        live_jobs = []

    registered_ids = []
    for j in live_jobs:
        jid = j["job_id"]
        state = lsf_client.load_job_state(root, jid)
        if state.pattern is not None or state.sim_log is not None:
            registered_ids.append(jid)

    if registered_ids:
        try:
            reconciled = lsf_client.reconcile_batch(root, registered_ids)
        except Exception as e:
            print(f"[reconciliation_cycle] reconcile_batch failed: {e}", flush=True)
            reconciled = {}
    else:
        reconciled = {}

    for jid, (state, _discrepancies) in reconciled.items():
        if state.lsf_status not in ("DONE", "EXIT"):
            continue
        if not state.sim_log:
            continue
        try:
            parsed = parse_sim_log_file(state.sim_log)
        except OSError as e:
            print(f"[reconciliation_cycle] could not read {state.sim_log}: {e}", flush=True)
            continue
        epilogue = parsed.get("epilogue")
        if epilogue:
            state.uvm_error_count = epilogue.get("uvm_error") or 0
            state.uvm_fatal_count = epilogue.get("uvm_fatal") or 0
        discrepancies = detect_underreporting(asdict(state), parsed)
        for d in discrepancies:
            print(f"[reconciliation_cycle] job {jid} under-reporting: {d}", flush=True)
        state.sim_status = "ANALYZED"
        lsf_client.save_job_state(root, state)

        verdict = (epilogue or {}).get("verdict")
        if state.pattern and verdict in ("PASSED", "FAILED"):
            regression_list_path = Path(uvm_root_path) / "regression.list"
            apply_verdict_to_file(regression_list_path, state.pattern, verdict == "PASSED")

    jobs_for_snapshot = []
    for j in live_jobs:
        jid = j["job_id"]
        if jid in reconciled:
            state, _ = reconciled[jid]
            row = lsf_client.to_snapshot_row(state, agent_action="monitoring")
            row["lsf_status"] = state.lsf_status
        else:
            row = {"job_id": jid, "pattern": j.get("job_name"),
                   "lsf_status": j.get("stat"), "dv_analysis_status": "UNREGISTERED",
                   "uvm_error": None, "uvm_fatal": None,
                   "agent_action": "monitoring", "note": None}
        jobs_for_snapshot.append(row)

    snapshot = render_snapshot(jobs_for_snapshot)
    snapshot_path = root / ".dv-harness" / "lsf" / "latest_snapshot.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")
    print(snapshot, flush=True)
    return snapshot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/regression_reporter.py dv_harness_tests/test_regression_reporter.py
git commit -m "feat: add run_reconciliation_cycle() wiring discover/reconcile/analyze/regression-list"
```

---

### Task 5: Rewrite the watch loop to call `run_reconciliation_cycle()`

**Files:**
- Modify: `dv_harness/regression_reporter.py`
- Test: `dv_harness_tests/test_regression_reporter.py`

**Interfaces:**
- Consumes: `run_reconciliation_cycle()` (Task 4).
- Produces: `main(project_root='.', once=True, interval_minutes=30, vcuser=None, uvm_root_path=None)` — same function, extended signature. `--watch` now performs real reconciliation each cycle, not just a stale re-print.

- [ ] **Step 1: Write the failing test**

Add to `dv_harness_tests/test_regression_reporter.py`:

```python
class TestMainWatchLoop:
    def test_watch_false_calls_reconciliation_once(self, tmp_path):
        with patch("dv_harness.regression_reporter.run_reconciliation_cycle",
                   return_value="snapshot text") as m:
            regression_reporter.main(project_root=str(tmp_path), once=True,
                                      vcuser="vcuser1", uvm_root_path=str(tmp_path / "uvm"))
        m.assert_called_once()

    def test_missing_vcuser_falls_back_to_legacy_render(self, tmp_path, capsys):
        # No vcuser supplied -- cannot discover live jobs at all, so fall back
        # to the pre-existing load_jobs()/render_snapshot() behavior rather
        # than crashing.
        regression_reporter.main(project_root=str(tmp_path), once=True)
        captured = capsys.readouterr()
        assert "Periodic Regression Snapshot" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_regression_reporter.py::TestMainWatchLoop -v`
Expected: FAIL — `main()` does not yet accept `vcuser`/`uvm_root_path` keyword arguments.

- [ ] **Step 3: Write minimal implementation**

Replace the existing `main()` in `dv_harness/regression_reporter.py`:

```python
def main(project_root='.', once=True, interval_minutes=30, vcuser=None, uvm_root_path=None):
    root = Path(project_root).resolve()
    while True:
        if vcuser:
            uvm_root = Path(uvm_root_path) if uvm_root_path else root / 'uvm'
            run_reconciliation_cycle(root, vcuser, uvm_root)
        else:
            # No vcuser means discover_live_jobs() has nothing to query --
            # fall back to the pre-existing behavior of re-rendering
            # whatever is already registered locally, rather than crashing.
            print(render_snapshot(load_jobs(root)), flush=True)
        if once:
            break
        time.sleep(max(1, interval_minutes) * 60)
```

Update the `if __name__=='__main__':` block's argparse to accept the two new flags:

```python
if __name__=='__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-root', default='.')
    ap.add_argument('--watch', action='store_true')
    ap.add_argument('--interval-minutes', type=int, default=30)
    ap.add_argument('--vcuser', default=None,
                     help='LSF account to discover live jobs under; omit for legacy local-only mode')
    ap.add_argument('--uvm-root-path', default=None,
                     help='UVM_ROOT_PATH for regression.list; defaults to <project-root>/uvm')
    a = ap.parse_args()
    main(a.project_root, not a.watch, a.interval_minutes, a.vcuser, a.uvm_root_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/regression_reporter.py dv_harness_tests/test_regression_reporter.py
git commit -m "feat: wire --watch loop to real reconciliation cycle, keep legacy no-vcuser fallback"
```

---

### Task 6: `ensure_watcher_running()` / `stop_watcher()` — PID-file lifecycle

**Files:**
- Modify: `dv_harness/regression_reporter.py`
- Test: `dv_harness_tests/test_regression_reporter.py`

**Interfaces:**
- Consumes: stdlib `subprocess`, `os`, `sys`.
- Produces: `ensure_watcher_running(root: Path, vcuser: str, uvm_root_path: Path, interval_minutes: int = 5) -> dict` (returns `{"started": bool, "pid": int}`); `stop_watcher(root: Path) -> dict` (returns `{"stopped": bool}`); `watcher_status(root: Path) -> dict` (returns `{"running": bool, "pid": int|None}`). Task 7's CLI commands call all three.

- [ ] **Step 1: Write the failing test**

Add to `dv_harness_tests/test_regression_reporter.py`:

```python
import os
import signal


class TestWatcherLifecycle:
    def test_ensure_watcher_running_starts_when_no_pid_file(self, tmp_path):
        with patch("dv_harness.regression_reporter.subprocess.Popen") as m:
            m.return_value.pid = 54321
            result = regression_reporter.ensure_watcher_running(
                tmp_path, "vcuser1", tmp_path / "uvm", interval_minutes=5)
        assert result == {"started": True, "pid": 54321}
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        assert pid_file.read_text().strip() == "54321"

    def test_ensure_watcher_running_noop_when_already_running(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text(str(os.getpid()))  # our own pid is definitely alive
        with patch("dv_harness.regression_reporter.subprocess.Popen") as m:
            result = regression_reporter.ensure_watcher_running(
                tmp_path, "vcuser1", tmp_path / "uvm")
        m.assert_not_called()
        assert result == {"started": False, "pid": os.getpid()}

    def test_ensure_watcher_running_restarts_on_stale_pid_file(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text("999999999")  # not a real running pid
        with patch("dv_harness.regression_reporter._pid_is_running", return_value=False), \
             patch("dv_harness.regression_reporter.subprocess.Popen") as m:
            m.return_value.pid = 11111
            result = regression_reporter.ensure_watcher_running(
                tmp_path, "vcuser1", tmp_path / "uvm")
        assert result == {"started": True, "pid": 11111}
        assert pid_file.read_text().strip() == "11111"

    def test_stop_watcher_terminates_and_removes_pid_file(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text("22222")
        with patch("dv_harness.regression_reporter._pid_is_running", return_value=True), \
             patch("dv_harness.regression_reporter.os.kill") as m:
            result = regression_reporter.stop_watcher(tmp_path)
        m.assert_called_once()
        assert result == {"stopped": True}
        assert not pid_file.exists()

    def test_stop_watcher_no_pid_file_is_a_noop(self, tmp_path):
        result = regression_reporter.stop_watcher(tmp_path)
        assert result == {"stopped": False}

    def test_watcher_status_reports_running(self, tmp_path):
        pid_file = tmp_path / ".dv-harness" / "lsf" / "watcher.pid"
        pid_file.parent.mkdir(parents=True)
        pid_file.write_text(str(os.getpid()))
        assert regression_reporter.watcher_status(tmp_path) == {"running": True, "pid": os.getpid()}

    def test_watcher_status_reports_not_running_when_no_pid_file(self, tmp_path):
        assert regression_reporter.watcher_status(tmp_path) == {"running": False, "pid": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_regression_reporter.py::TestWatcherLifecycle -v`
Expected: FAIL with `AttributeError: module 'dv_harness.regression_reporter' has no attribute 'ensure_watcher_running'`

- [ ] **Step 3: Write minimal implementation**

Add to `dv_harness/regression_reporter.py` (add `import os, subprocess, sys` at top alongside existing imports):

```python
WATCHER_PID_FILE = ('.dv-harness', 'lsf', 'watcher.pid')


def _pid_file_path(root: Path) -> Path:
    return root.joinpath(*WATCHER_PID_FILE)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except AttributeError:
        # os.kill(pid, 0) is not universally available; treat as unknown
        # rather than crash -- caller falls through to "start a new one".
        return False
    return True


def ensure_watcher_running(root: Path, vcuser: str, uvm_root_path,
                            interval_minutes: int = 5) -> dict:
    """Start the --watch loop as a detached background process if one is
    not already running for this project, tracked via a PID file. A stale
    PID file (process no longer alive) is detected and cleaned up
    automatically rather than blocking a fresh start."""
    pid_path = _pid_file_path(root)
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text().strip())
        except ValueError:
            existing_pid = None
        if existing_pid is not None and _pid_is_running(existing_pid):
            return {"started": False, "pid": existing_pid}
        pid_path.unlink()

    argv = [sys.executable, "-m", "dv_harness.regression_reporter",
            "--project-root", str(root), "--watch",
            "--interval-minutes", str(interval_minutes),
            "--vcuser", vcuser, "--uvm-root-path", str(uvm_root_path)]
    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, **popen_kwargs)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    return {"started": True, "pid": proc.pid}


def stop_watcher(root: Path) -> dict:
    """Terminate the running watcher (if any) and remove its PID file.
    A missing PID file is a no-op, not an error -- nothing was running."""
    pid_path = _pid_file_path(root)
    if not pid_path.exists():
        return {"stopped": False}
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        pid_path.unlink()
        return {"stopped": False}
    if _pid_is_running(pid):
        os.kill(pid, signal.SIGTERM if os.name != "nt" else 15)
    pid_path.unlink()
    return {"stopped": True}


def watcher_status(root: Path) -> dict:
    pid_path = _pid_file_path(root)
    if not pid_path.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        return {"running": False, "pid": None}
    return {"running": _pid_is_running(pid), "pid": pid if _pid_is_running(pid) else None}
```

Add `import signal` alongside the other new imports at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/regression_reporter.py dv_harness_tests/test_regression_reporter.py
git commit -m "feat: add PID-file-based watcher lifecycle (ensure_watcher_running/stop_watcher/watcher_status)"
```

---

### Task 7: CLI commands `lsf-watch-start` / `lsf-watch-stop` / `lsf-watch-status`

**Files:**
- Modify: `dv_harness/cli.py`
- Test: `dv_harness_tests/test_cli.py` (check whether this file exists first; if not, follow the pattern of whatever test file already covers `lsf-submit`/`lsf-kill` — search for it before creating a new one)

**Interfaces:**
- Consumes: `regression_reporter.ensure_watcher_running()`, `stop_watcher()`, `watcher_status()` (Task 6).
- Produces: three new argparse subcommands, matching the existing flat `lsf-submit`/`lsf-kill`/`lsf-reconcile` naming convention (not a nested `lsf watch ...` subgroup).

- [ ] **Step 1: Write the failing test**

First, locate the existing CLI test file:

Run: `python -c "import pathlib; print([p for p in pathlib.Path('dv_harness_tests').glob('test_cli*.py')])"`

If a `test_cli.py`-style file exists, add the tests below to it, following its existing fixture/style. If none exists, create `dv_harness_tests/test_cli_lsf_watch.py`:

```python
"""Tests for dv_harness/cli.py's lsf-watch-start/stop/status subcommands."""
from __future__ import annotations

import json
from unittest.mock import patch

from dv_harness import cli


def _run_cli(monkeypatch, capsys, argv):
    monkeypatch.setattr("sys.argv", ["dv-harness"] + argv)
    try:
        cli.main()
    except SystemExit:
        pass
    return capsys.readouterr()


class TestLsfWatchCli:
    def test_watch_start_prints_result(self, tmp_path, monkeypatch, capsys):
        with patch("dv_harness.regression_reporter.ensure_watcher_running",
                   return_value={"started": True, "pid": 123}):
            out = _run_cli(monkeypatch, capsys,
                            ["--root", str(tmp_path), "lsf-watch-start",
                             "--vcuser", "vcuser1"])
        assert json.loads(out.out)["pid"] == 123

    def test_watch_stop_prints_result(self, tmp_path, monkeypatch, capsys):
        with patch("dv_harness.regression_reporter.stop_watcher",
                    return_value={"stopped": True}):
            out = _run_cli(monkeypatch, capsys, ["--root", str(tmp_path), "lsf-watch-stop"])
        assert json.loads(out.out)["stopped"] is True

    def test_watch_status_prints_result(self, tmp_path, monkeypatch, capsys):
        with patch("dv_harness.regression_reporter.watcher_status",
                    return_value={"running": True, "pid": 456}):
            out = _run_cli(monkeypatch, capsys, ["--root", str(tmp_path), "lsf-watch-status"])
        assert json.loads(out.out)["pid"] == 456
```

Note: adjust the `--root`/global-argument shape and `cli.main()` entry point in the test above to match whatever `cli.py` actually uses elsewhere (check an existing test for `lsf-submit` if one exists, or `cli.py`'s own `ap.add_argument` calls above line 35, before writing this test for real — do not guess the global flag name).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest dv_harness_tests/test_cli_lsf_watch.py -v` (or wherever Step 1 placed the tests)
Expected: FAIL — `error: argument cmd: invalid choice: 'lsf-watch-start'`

- [ ] **Step 3: Write minimal implementation**

In `dv_harness/cli.py`, add three new subparsers alongside the existing `lsf-submit`/`lsf-kill`/`lsf-reconcile` ones (near line 126-159):

```python
    pwatch_start = sub.add_parser("lsf-watch-start",
        help="Start the background job/log monitor (Part 2 of the "
             "2026-09-01 sim-output-layout spec) if not already running.")
    pwatch_start.add_argument("--vcuser", required=True)
    pwatch_start.add_argument("--uvm-root-path", default=None)
    pwatch_start.add_argument("--interval-minutes", type=int, default=5)

    sub.add_parser("lsf-watch-stop", help="Stop the background job/log monitor.")
    sub.add_parser("lsf-watch-status", help="Report whether the background job/log monitor is running.")
```

And in the command-dispatch `elif` chain (near line 473-479, after the `lsf-kill` handler):

```python
    elif args.cmd == "lsf-watch-start":
        from . import regression_reporter
        uvm_root = args.uvm_root_path or str(h.root / "uvm")
        result = regression_reporter.ensure_watcher_running(
            h.root, args.vcuser, uvm_root, interval_minutes=args.interval_minutes)
        print(json.dumps(result, ensure_ascii=False))
    elif args.cmd == "lsf-watch-stop":
        from . import regression_reporter
        result = regression_reporter.stop_watcher(h.root)
        print(json.dumps(result, ensure_ascii=False))
    elif args.cmd == "lsf-watch-status":
        from . import regression_reporter
        result = regression_reporter.watcher_status(h.root)
        print(json.dumps(result, ensure_ascii=False))
```

(Match `h.root`/`h` to whatever variable name the surrounding `lsf-submit`/`lsf-kill` handlers already use for the harness root in this file — read the actual surrounding code before pasting, since this plan's earlier reads of `cli.py` used `h.root` for `lsf_client.bsub_submit`'s call but this must be verified against the live file, not assumed from this snippet alone.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest dv_harness_tests/test_cli_lsf_watch.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add dv_harness/cli.py dv_harness_tests/test_cli_lsf_watch.py
git commit -m "feat: add lsf-watch-start/stop/status CLI commands"
```

---

### Task 8: CLAUDE.md protocol addition — how "auto-start" actually works here

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: a new short section instructing an agent to run `dv-harness lsf-watch-start` immediately after declaring `REMOTE_EXECUTION_REQUIRED`, mirroring the existing SSH/Remote Transport Connection Intake gate's own required-action shape.

- [ ] **Step 1: Locate the insertion point**

Read `CLAUDE.md`'s existing `## Remote Linux Execution (Persistent Relay)` section (the one describing `remote_exec.py`/`remote_relay.py`) to confirm the exact text to insert after, since this is the most closely related existing section.

- [ ] **Step 2: Add the new section**

Insert a new section immediately after `## Remote Linux Execution (Persistent Relay)` and before `## Waveform Dump User Gate`:

```markdown
## Background Job/Log Monitor Auto-Start

There is no Python code path that fires automatically the moment
REMOTE_EXECUTION_REQUIRED is declared -- that declaration is agent-supplied
evidence (an `execution_mode_validator` block embedded in the agent's own
message text), not an engine event with a hookable call site. "Automatic"
here means the same thing it means for the SSH/Remote Transport Connection
Intake gate above: a required action the agent takes as part of following
this protocol, not something the engine does on its own.

Once REMOTE_EXECUTION_REQUIRED has been declared and any needed SSH/Remote
Transport Connection Intake has completed, run:

    dv-harness lsf-watch-start --vcuser <account>

before submitting or expecting visibility into any LSF job this session.
This starts (or confirms already-running) a detached background process
that discovers every live job under that account, reconciles/analyzes any
job this harness has a registered `JobState` for, and maintains the
`regression.list` safety net (see `apply_verdict_to_file()` in
`dv_harness/uvm_generator/regression_list_manager.py`) for jobs that bypass
the generated environment's own Makefile-native `RECORD=1` mechanism. It is
a no-op if a watcher is already running for this project (tracked via a PID
file). Stop it with `dv-harness lsf-watch-stop` on a clean session end, or
when execution mode transitions back to `PURE_LOCAL_READ_ANALYSIS`.
```

- [ ] **Step 3: Verify the insertion reads correctly in context**

Read the full `CLAUDE.md` section spanning from `## Remote Linux Execution (Persistent Relay)` through the new section into `## Waveform Dump User Gate`, and confirm no heading levels or list formatting broke.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Background Job/Log Monitor Auto-Start protocol section"
```

---

## Self-Review

**Spec coverage:**
- Part 1: confirmed already fully implemented (see note at top) -- no task needed, not a gap.
- Part 2 "Auto-discovery": Task 1.
- Part 2 "Registration for deep analysis": Task 2.
- Part 2 "The reconciliation cycle" (steps 1-3): Task 4.
- Part 2 "Auto-start / lifecycle": Tasks 6, 7, 8 (re-scoped per the real-architecture finding above).
- Part 2 "Error handling": folded into Task 4 (per-call try/except) and Task 5 (watch loop keeps running).
- Part 3 (regression-list safety net, wiring + idempotency + verdict source of truth): Tasks 3 and 4.
- Testing Strategy's four Part-3 test cases (PASS/FAIL/indeterminate/idempotent-double-call): all four covered across Task 3's tests (idempotent-double-call, PASS, FAIL) and Task 4's tests (indeterminate skip, wired end-to-end).

**Placeholder scan:** no TBD/TODO; the one explicit "verify against the live file" instruction (Task 7, Step 3) is a deliberate anti-guessing instruction, not a placeholder for missing content -- the actual code to add is fully written above it.

**Type consistency:** `JobState`, `discover_live_jobs()`'s dict shape, `apply_verdict_to_file()`'s signature, and `run_reconciliation_cycle()`'s parameters are used identically across every task that references them.
