---
name: job-memory
description: 保存單一 LSF JOB_ID 的 pattern/options/sim.log/signature/root-cause/fix/rerun 歷史，必須 JOB_ID 隔離。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# job-memory
保存單一 LSF JOB_ID 的 pattern/options/sim.log/signature/root-cause/fix/rerun 歷史，必須 JOB_ID 隔離。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: per-LSF-job history (v16.1 Per-Job LSF Agent Monitoring's
JOB_ID/pattern/options/run_dir/sim.log/Git SHA/Server SHA context), kept
isolated per job so one job's history never leaks into another job's
context (CLAUDE.md: "One submitted LSF job = one isolated Job Agent
context").

**Inputs**: a record with `kind` in `job_result` / `job_failure` /
`job_rerun`, carrying `JOB_ID`, pattern/testcase, sim options, run
directory, log path, Git/Server SHA (v16.1's required Job Agent Result
fields -- see regression-agent.md).

**Outputs**: `route_and_store()` returns
`{"destination": "JOB_MEMORY", "level": "job", "memory_id": ...}`, written
via `dv_harness.memory.JobMemoryStore` to
`.dv-harness/memory/job/<memory_id>.json`.

**Preconditions**: none -- `route_memory()` routes any
`job_result`/`job_failure`/`job_rerun` kind here regardless of `verified`
(a job's raw outcome is itself the fact being recorded, not a hypothesis
needing separate verification).

**Execution Steps**:
1. Regression Agent's per-Job Monitor Task builds the Job Agent Result
   record after each LSF state/sim.log increment.
2. `route_and_store(root, record, cfg)` on job completion, rerun, or a
   change-only status transition (v18 Periodic Full Snapshot / v19.1 Strict
   Per-Job Monitor Iron Rules).
3. Do not merge two different JOB_IDs' evidence into one record.

**Fallback**: if `JOB_ID` is missing, the record still lands here (kind
alone routes it) but is not usefully retrievable later -- always populate
`JOB_ID` before writing.

**Evidence Requirements**: sim.log analysis (not LSF DONE/EXIT alone --
"LSF DONE is not equal to DV PASS", CLAUDE.md).

**Failure Conditions**: writing a giant raw log body into the record
violates the Engineering Memory Policy's "Never store giant logs" rule --
store `LOG_PATH` + `LAST_LOG_OFFSET` + extracted `ERROR_SIGNATURES` instead.

**Example**:
```python
route_and_store(root, {
    "kind": "job_result", "JOB_ID": "1234567", "pattern": "usb_bulk_txn_p0",
    "LSF_STATUS": "DONE", "SIM_STATUS": "FAIL", "LOG_PATH": "run/1234567/sim.log",
    "LAST_LOG_OFFSET": 48213, "UVM_ERROR_COUNT": 1, "GIT_SHA": "abc123", "SERVER_SHA": "def456",
}, cfg=cfg)
```
