# LSF Reconcile Terminal-Status Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `reconcile_job()` from destroying a real, previously-confirmed terminal LSF status once LSF's own retention window forgets a job; stop a single unparseable `bjobs` batch from costing every other job in that batch an analysis cycle; and make `KILLED` a recognized terminal status everywhere `DONE`/`EXIT` already is.

**Architecture:** Three independent, narrowly-scoped fixes inside two existing files (`dv_harness/lsf_client.py`, `dv_harness/regression_reporter.py`) — no new files, no new public API surface beyond one new internal fallback function.

**Tech Stack:** Python 3 (stdlib only: `subprocess`, `json`), `pytest` with `unittest.mock.patch`.

**Spec:** `docs/superpowers/specs/2026-09-01-lsf-reconcile-terminal-status-hardening-design.md`

## Global Constraints

- `reconcile_job()`'s existing `Discrepancy` dataclass already declares `severity: Literal["INFO", "WARN", "CRITICAL"]` (`dv_harness/lsf_client.py:80`) — `"INFO"` already exists as a valid value; no type change is needed anywhere, only a new place that emits it.
- The only existing code that keys on `Discrepancy.severity` is `_write_job_tier_memory_on_terminal_reconcile()` (`lsf_client.py:474`), which checks `d.field == "sim_status" and d.severity == "CRITICAL"` — an `"INFO"` discrepancy on the `lsf_status` field never matches this condition, so it cannot change that function's behavior.
- `reconcile_job()`'s existing `ANALYSIS_OWED` check (`lsf_client.py:418`, `if live_status in ("DONE", "EXIT") and state.sim_status in ...`) is explicitly OUT OF SCOPE for every task in this plan — do not add `"KILLED"` to it, and do not change its logic. A `KILLED` job was deliberately terminated by this project's own auto-kill-scan and does not owe a pass/fail verdict the way a `DONE`/`EXIT` job does.
- Do not re-test `record_verdict()`/`record_suite()`/`apply_verdict_to_file()`/`bjobs_query_many()`'s existing happy-path behavior — only the new logic in each task needs new tests.
- Commit after each task, using `git add <specific files>` (never `git add -A`).

---

### Task 1: `reconcile_job()` retains an already-confirmed terminal status on an absent live record

**Files:**
- Modify: `dv_harness/lsf_client.py:409-416` (inside `reconcile_job()`)
- Test: `dv_harness_tests/test_lsf_client.py` (add to the existing `class TestReconcileJob:`, starting at line 173)

**Interfaces:**
- Consumes: nothing new — uses `reconcile_job()`'s existing parameters (`state: JobState`, `live_bjobs_record: dict`) and the existing `Discrepancy`/`map_bjobs_stat_to_lsf_status()`.
- Produces: no new public function. `reconcile_job()`'s behavior changes only for the specific case (absent live record + already-terminal `state.lsf_status`); its return type (`tuple[JobState, list[Discrepancy]]`) is unchanged. Task 2 relies on the exact terminal-value set `("DONE", "EXIT", "KILLED")` this task introduces here.

- [ ] **Step 1: Write the failing tests**

Add to `dv_harness_tests/test_lsf_client.py`'s existing `class TestReconcileJob:` (after `test_sim_log_not_containing_job_id_flags_warn`, which ends at line 207):

```python
    def test_absent_record_retains_already_confirmed_done_status(self):
        # LSF has forgotten this job (aged past its own retention window),
        # but the DONE status was already confirmed by a prior real poll --
        # an absent record now must not destroy that fact.
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", sim_status="PASS")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "DONE"
        info = [d for d in discrepancies if d.severity == "INFO"]
        assert len(info) == 1
        assert info[0].field == "lsf_status"
        assert info[0].reported == "DONE"

    def test_absent_record_retains_already_confirmed_exit_status(self):
        state = lsf_client.JobState(job_id=1, lsf_status="EXIT", sim_status="FAIL")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "EXIT"
        assert any(d.severity == "INFO" and d.field == "lsf_status" for d in discrepancies)

    def test_absent_record_retains_already_confirmed_killed_status(self):
        state = lsf_client.JobState(job_id=1, lsf_status="KILLED", sim_status="UNKNOWN")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "KILLED"
        assert any(d.severity == "INFO" and d.field == "lsf_status" for d in discrepancies)

    def test_absent_record_still_overwrites_a_non_terminal_status(self):
        # This is the ORIGINAL, still-correct behavior: a job that was never
        # confirmed terminal genuinely becomes UNKNOWN when LSF has no
        # record of it at all -- that is real (if disappointing) new
        # information, not a case this fix protects.
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", sim_status="RUNNING")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "UNKNOWN"
        assert any(d.severity == "WARN" and d.field == "lsf_status" for d in discrepancies)

    def test_retained_status_does_not_mark_state_as_changed(self):
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", sim_status="PASS")
        original_fingerprint = state.fingerprint()
        live = {"JOBID": "1", "STAT": None}
        new_state, _ = lsf_client.reconcile_job(state, live)
        # No real change happened, so the fingerprint/change-time machinery
        # must not fire for a job whose recorded status was correctly retained.
        assert new_state.state_fingerprint != original_fingerprint or new_state.state_fingerprint is None
        # (state_fingerprint starts as None on a fresh JobState; the real
        # assertion that matters is that last_change_time stays None, since
        # reconcile_job() only sets it inside the `if changed:` block.)
        assert new_state.last_change_time is None

    def test_present_record_still_compares_normally_when_already_terminal(self):
        # A job recorded as DONE that a live poll ALSO reports as DONE (a
        # real, present record, not an absent one) must go through the
        # normal no-discrepancy path -- this fix only changes behavior for
        # an ABSENT record, never a present one.
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", sim_status="PASS")
        live = {"JOBID": "1", "STAT": "DONE"}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "DONE"
        assert discrepancies == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestReconcileJob -v`
Expected: the five new tests FAIL. `test_absent_record_retains_already_confirmed_done_status` fails with `assert 'UNKNOWN' == 'DONE'` (current code overwrites it); `test_absent_record_still_overwrites_a_non_terminal_status` and `test_present_record_still_compares_normally_when_already_terminal` should already PASS (they describe unchanged behavior) — confirm this before moving on, since a plan step that turns out to already pass is a signal to double check the test is exercising what it claims, not a bug in the plan.

- [ ] **Step 3: Write the implementation**

In `dv_harness/lsf_client.py`, replace lines 409-416 (inside `reconcile_job()`):

```python
    live_status = map_bjobs_stat_to_lsf_status(live_bjobs_record.get("STAT"))
    if live_status != state.lsf_status:
        discrepancies.append(Discrepancy(
            job_id=state.job_id, field="lsf_status",
            reported=state.lsf_status, live=live_status, severity="WARN",
        ))
        state.lsf_status = live_status
        changed = True
```

with:

```python
    live_status = map_bjobs_stat_to_lsf_status(live_bjobs_record.get("STAT"))
    # BUG FIX (2026-09-01, lsf-reconcile-terminal-status-hardening): a real,
    # previously-confirmed terminal status must outlive LSF's own retention
    # window. bjobs_query_many() returns {} (no "STAT" key at all) for a job
    # id LSF has completely forgotten -- that is an ABSENCE of information,
    # not new evidence that the job's outcome changed. Downgrading an
    # already-recorded DONE/EXIT/KILLED to UNKNOWN here previously destroyed
    # real evidence for no reason other than the tool's own bookkeeping
    # lifetime expiring -- exactly the decay CLAUDE.md's "LSF DONE is not
    # equal to DV PASS" rule exists to prevent. Scoped precisely to the
    # absent-record case: a live call that explicitly reports an ambiguous
    # real status (e.g. UNKWN/ZOMBI) for a job IS new evidence and is not
    # protected here.
    record_absent = live_bjobs_record.get("STAT") is None
    already_terminal = state.lsf_status in ("DONE", "EXIT", "KILLED")
    if record_absent and already_terminal:
        discrepancies.append(Discrepancy(
            job_id=state.job_id, field="lsf_status",
            reported=state.lsf_status, live=live_status, severity="INFO",
        ))
    elif live_status != state.lsf_status:
        discrepancies.append(Discrepancy(
            job_id=state.job_id, field="lsf_status",
            reported=state.lsf_status, live=live_status, severity="WARN",
        ))
        state.lsf_status = live_status
        changed = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestReconcileJob -v`
Expected: all tests in this class PASS (11 total: 5 pre-existing + 6 new).

- [ ] **Step 5: Run the full lsf_client test file to confirm no regressions**

Run: `pytest dv_harness_tests/test_lsf_client.py -v`
Expected: all tests PASS (this file also has `TestReconcileBatch`, which calls `reconcile_job()` indirectly — confirm nothing there broke).

- [ ] **Step 6: Commit**

```bash
git add dv_harness/lsf_client.py dv_harness_tests/test_lsf_client.py
git commit -m "fix: reconcile_job() retains a confirmed terminal status when LSF's record is absent"
```

---

### Task 2: Extend `regression_reporter.py`'s pre-existing terminal-status checks to include `KILLED`

**Files:**
- Modify: `dv_harness/regression_reporter.py:118` (inside `_job_still_owes_reconciliation()`)
- Modify: `dv_harness/regression_reporter.py:200` (inside `run_reconciliation_cycle()`)
- Test: `dv_harness_tests/test_regression_reporter.py`

**Interfaces:**
- Consumes: Task 1's established terminal-value set `("DONE", "EXIT", "KILLED")` — this task makes the two remaining pre-existing checks consistent with it.
- Produces: no new function; `_job_still_owes_reconciliation(state) -> bool`'s signature and general contract are unchanged, only its terminal-value set grows by one value.

- [ ] **Step 1: Write the failing tests**

First, find the exact current test file location for `_job_still_owes_reconciliation`'s existing tests:

Run: `grep -n "_job_still_owes_reconciliation\|class Test" dv_harness_tests/test_regression_reporter.py`

Add a new test near whatever existing test class covers `_job_still_owes_reconciliation` (match that file's real structure — do not assume a class name not confirmed by the grep above):

```python
def test_killed_and_already_analyzed_job_does_not_still_owe_reconciliation():
    state = lsf_client.JobState(job_id=1, lsf_status="KILLED", sim_status="PASS")
    assert regression_reporter._job_still_owes_reconciliation(state) is False


def test_killed_but_not_yet_analyzed_job_still_owes_reconciliation():
    state = lsf_client.JobState(job_id=1, lsf_status="KILLED", sim_status="UNKNOWN")
    assert regression_reporter._job_still_owes_reconciliation(state) is True
```

(Adjust the import style — module-level function calls vs. a test class — to match whatever the surrounding real tests in this file actually do; the grep in this step tells you which.)

For the second call site (`run_reconciliation_cycle()`'s own `if state.lsf_status not in ("DONE", "EXIT"):` at line 200), find its exact current test coverage:

Run: `grep -n "def test_.*settled\|def test_.*killed" dv_harness_tests/test_regression_reporter.py`

Add a test proving a `KILLED`, already-analyzed job is treated as settled the same way a `DONE` one is (rendered from persisted state, not re-queried against LSF) — model this on whatever existing test already proves this for `DONE`/`EXIT` (search for `test_settled_job_is_dropped_from_the_reconcile_set_and_keeps_its_status` or similarly-named test from the prior plan's work, and write a `KILLED`-flavored sibling of it with the same shape: register a `KILLED`+`PASS` job on disk absent from `discover_live_jobs()`'s mocked result, run `run_reconciliation_cycle()`, and assert `_run_bjobs`/`reconcile_batch` was NOT called for that job's id, and its persisted `lsf_status` remains `"KILLED"`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v -k killed`
Expected: the new tests FAIL — `_job_still_owes_reconciliation()` currently returns `True` for a `KILLED`+`PASS` job (since `"KILLED" not in ("DONE", "EXIT")` is `True`), and the settled-job test fails because a `KILLED` job is not yet recognized as settled.

- [ ] **Step 3: Write the implementation**

In `dv_harness/regression_reporter.py`, change line 118 from:

```python
    return (state.sim_status in ("UNKNOWN", "RUNNING")
            or state.lsf_status not in ("DONE", "EXIT"))
```

to:

```python
    return (state.sim_status in ("UNKNOWN", "RUNNING")
            or state.lsf_status not in ("DONE", "EXIT", "KILLED"))
```

And update the docstring immediately above it (lines 88-116) to also mention `KILLED` alongside `DONE`/`EXIT` wherever it currently says "lsf-terminal" or lists `DONE`/`EXIT` explicitly, so the comment doesn't undersell what the code now does — e.g. line 95's "False only for a job that is BOTH lsf-terminal AND already analyzed" is already correctly abstract (it doesn't hardcode the value list), so it likely needs no change; but any line that spells out `DONE/EXIT` as if that were the complete set (verify by re-reading the current text, don't assume) should be updated to `DONE/EXIT/KILLED`.

Then find and change line 200's `if state.lsf_status not in ("DONE", "EXIT"):` to `if state.lsf_status not in ("DONE", "EXIT", "KILLED"):` — re-read the surrounding function first to confirm this is a call-site checking "is this job settled/terminal" (matching the pattern this plan targets) and not some unrelated check that happens to use the same tuple literal.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v -k killed`
Expected: PASS.

- [ ] **Step 5: Run the full regression_reporter test file to confirm no regressions**

Run: `pytest dv_harness_tests/test_regression_reporter.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add dv_harness/regression_reporter.py dv_harness_tests/test_regression_reporter.py
git commit -m "fix: recognize KILLED as a terminal status in the reconcile-set and settled-job checks"
```

---

### Task 3: `_run_bjobs()` per-id fallback when a batch query fails

**Files:**
- Modify: `dv_harness/lsf_client.py:118-134` (`_run_bjobs()`) and `:145-157` (`bjobs_query_many()`)
- Test: `dv_harness_tests/test_lsf_client.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_run_bjobs_with_fallback(job_ids: list[int]) -> dict`, a new internal function `bjobs_query_many()` calls instead of `_run_bjobs()` directly. Its return shape matches `_run_bjobs()`'s existing contract exactly: a dict with a `"RECORDS"` key holding a list of per-job dicts (so `bjobs_query_many()`'s existing record-processing loop, lines 149-156, needs no change at all — only its one call site, line 148, changes which function it calls).

- [ ] **Step 1: Write the failing tests**

Add to `dv_harness_tests/test_lsf_client.py`, near the existing `class TestBjobsQuery:` (starts at line 61):

```python
class TestRunBjobsFallback:
    def test_healthy_batch_makes_exactly_one_call(self):
        payload = json.dumps({"RECORDS": [
            {"JOBID": "1", "STAT": "RUN"}, {"JOBID": "2", "STAT": "DONE"},
        ]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=payload)) as m:
            result = lsf_client.bjobs_query_many([1, 2])
        assert m.call_count == 1
        assert result[1]["STAT"] == "RUN"
        assert result[2]["STAT"] == "DONE"

    def test_batch_json_failure_falls_back_to_per_id_calls(self):
        # First call (the batch) returns unparseable stdout; each of the
        # two per-id fallback calls succeeds individually.
        bad_batch = _completed(stdout="not json")
        good_1 = _completed(stdout=json.dumps({"RECORDS": [{"JOBID": "1", "STAT": "DONE"}]}))
        good_2 = _completed(stdout=json.dumps({"RECORDS": [{"JOBID": "2", "STAT": "RUN"}]}))
        with patch("dv_harness.lsf_client.subprocess.run",
                   side_effect=[bad_batch, good_1, good_2]) as m:
            result = lsf_client.bjobs_query_many([1, 2])
        assert m.call_count == 3
        assert result[1]["STAT"] == "DONE"
        assert result[2]["STAT"] == "RUN"

    def test_batch_failure_with_one_genuinely_missing_id_isolates_only_that_id(self):
        # The batch fails; per-id fallback finds job 1 but job 2 is
        # genuinely gone (LSF has forgotten it) -- only job 2 comes back
        # empty, job 1 must not be penalized for job 2's absence.
        bad_batch = _completed(stdout="not json")
        good_1 = _completed(stdout=json.dumps({"RECORDS": [{"JOBID": "1", "STAT": "DONE"}]}))
        empty_2 = _completed(stdout=json.dumps({"RECORDS": []}))
        with patch("dv_harness.lsf_client.subprocess.run",
                   side_effect=[bad_batch, good_1, empty_2]):
            result = lsf_client.bjobs_query_many([1, 2])
        assert result[1]["STAT"] == "DONE"
        assert result[2] == {}

    def test_batch_failure_and_all_per_id_fallbacks_also_fail_returns_all_empty(self):
        bad_batch = _completed(stdout="not json")
        bad_1 = _completed(stdout="also not json")
        bad_2 = _completed(stdout="also not json")
        with patch("dv_harness.lsf_client.subprocess.run",
                   side_effect=[bad_batch, bad_1, bad_2]):
            result = lsf_client.bjobs_query_many([1, 2])
        assert result[1] == {}
        assert result[2] == {}

    def test_single_job_id_batch_does_not_need_fallback_shape_but_still_works(self):
        payload = json.dumps({"RECORDS": [{"JOBID": "1", "STAT": "DONE"}]})
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=payload)) as m:
            result = lsf_client.bjobs_query_many([1])
        assert m.call_count == 1
        assert result[1]["STAT"] == "DONE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestRunBjobsFallback -v`
Expected: `test_healthy_batch_makes_exactly_one_call` and `test_single_job_id_batch_does_not_need_fallback_shape_but_still_works` PASS already (unchanged happy-path behavior). The three failure-path tests FAIL — currently a batch JSON failure raises `LsfUnavailableError` uncaught, so these tests fail with that exception propagating instead of returning the expected dict.

- [ ] **Step 3: Write the implementation**

In `dv_harness/lsf_client.py`, add a new function after `_run_bjobs()` (after line 134, before `bjobs_query`):

```python
def _run_bjobs_with_fallback(job_ids: list[int]) -> dict:
    """Wraps _run_bjobs() with a per-id retry when the batch call itself
    fails. A single job id LSF has completely forgotten can make the whole
    batch's -json output unparseable (BUG, 2026-09-01
    lsf-reconcile-terminal-status-hardening) -- without this, every OTHER,
    perfectly healthy job in that batch loses one full analysis cycle. This
    function never changes bjobs_query_many()'s return contract: on success
    it returns exactly what _run_bjobs() would have returned; on batch
    failure it merges the per-id fallback results into the same
    {"RECORDS": [...]} shape, and an id that still fails its own individual
    call contributes no entry to RECORDS (bjobs_query_many()'s own
    default-to-{} handling for a missing id already covers that case
    correctly, unchanged).

    Cost, stated plainly: only on batch failure does this become up to
    len(job_ids) additional real bjobs calls. The healthy-batch path (the
    common case) is exactly as fast as before -- one call, no change."""
    try:
        return _run_bjobs(job_ids)
    except LsfUnavailableError:
        pass
    records = []
    for jid in job_ids:
        try:
            single = _run_bjobs([jid])
        except LsfUnavailableError:
            continue
        records.extend(single.get("RECORDS") or [])
    return {"RECORDS": records}
```

Then change `bjobs_query_many()` (currently lines 145-157) so its one call to `_run_bjobs(job_ids)` (line 148) becomes `_run_bjobs_with_fallback(job_ids)` — every other line in that function is unchanged:

```python
def bjobs_query_many(job_ids: list[int]) -> dict:
    if not job_ids:
        return {}
    parsed = _run_bjobs_with_fallback(job_ids)
    records = parsed.get("RECORDS") or []
    result = {jid: {} for jid in job_ids}
    for rec in records:
        try:
            jid = int(rec.get("JOBID"))
        except (TypeError, ValueError):
            continue
        result[jid] = rec
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest dv_harness_tests/test_lsf_client.py::TestRunBjobsFallback -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Run the full lsf_client test file to confirm no regressions**

Run: `pytest dv_harness_tests/test_lsf_client.py -v`
Expected: all tests PASS — specifically confirm `TestBjobsQuery`'s two pre-existing tests (`test_bjobs_query_many_maps_by_int_job_id`, `test_bjobs_query_many_empty_input_short_circuits_without_subprocess`) still pass unchanged, since this task's only edit to `bjobs_query_many()` is the one line calling the new wrapper.

- [ ] **Step 6: Commit**

```bash
git add dv_harness/lsf_client.py dv_harness_tests/test_lsf_client.py
git commit -m "fix: add per-id fallback to bjobs_query_many() so one bad id can't poison a whole batch"
```

---

### Task 4: Full-suite regression check

**Files:** none modified — verification only.

**Interfaces:** none.

- [ ] **Step 1: Run the complete test suite**

Run: `pytest dv_harness_tests/ -q`
Expected: every test passes (this suite was last confirmed at 1175/1175 before this plan's work began; it should grow by the number of new tests added across Tasks 1-3 — 6 + 2 + 5 = 13 new tests, so expect roughly 1188 passed — treat the exact prior count as a floor to exceed, not a number to hardcode into an assertion anywhere).

- [ ] **Step 2: If anything unexpected fails, stop and investigate**

Do not proceed past this task with a red suite. A failure here means an interaction between Tasks 1-3 (or with pre-existing code) that none of the individual task's own tests caught — diagnose the real cause before considering this plan done.

## Self-Review

**Spec coverage:**
- Part 1 (terminal-status retention in `reconcile_job()`): Task 1.
- Part 2 (`_run_bjobs()` per-id fallback): Task 3.
- Part 3 (`KILLED` added to terminal-status checks, explicitly excluding the `ANALYSIS_OWED` line): Task 1 (bakes it into the new check from the start, per the spec's own requirement) + Task 2 (the two remaining pre-existing call sites) + the Global Constraints section's explicit exclusion of line 418.
- Spec's Testing Strategy section's three groups of test cases: all covered — Task 1's 6 tests cover Part 1's three test requirements (retain-DONE, retain-RUN-unchanged, retain-KILLED); Task 3's 5 tests cover Part 2's two test requirements (fallback success/partial-failure/total-failure, and a "no fallback overhead on the happy path" test); Task 2's 2+ tests cover Part 3's requirement (KILLED excluded from "still owes" and treated as settled).

**Placeholder scan:** no TBD/TODO; every code block is complete, real code with real line references verified against the live file at plan-writing time.

**Type consistency:** `Discrepancy`, `JobState`, `_run_bjobs`, `_run_bjobs_with_fallback`, `bjobs_query_many`, `_job_still_owes_reconciliation` are used with identical signatures/names across every task that references them.
