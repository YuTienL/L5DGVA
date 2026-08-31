# Standardized Sim Output Layout + Background Job/Log Monitor — Design Spec

## Context

Two related, real gaps surfaced during the first live USB VIP-based UVM
environment generation session (2026-08-31/09-01):

1. **No standardized simulation output layout.** The live USB generation's
   `sim/` tree dumped build artifacts, LSF job output, VCS/Verdi files, and
   simulation logs all flat into `DUT/` (the compile working directory) --
   finding the real LSF job's actual log required a `find -newer` sweep
   across dozens of unrelated files (`vc_hdrs.h`, `ucli.key`, `csrc/*`,
   `simv_dvuvm`, etc.) rather than a predictable path. `IP_UVM_DV_Gen.md`'s
   own Step 11 file manifest defines `sim/scripts/` but nothing else under
   `sim/`.
2. **No automatic background visibility into job/simulation status.**
   `dv_harness/regression_reporter.py --watch` exists (configurable
   interval, default 30 minutes) but (a) nothing ever starts it
   automatically -- a real gap already confirmed by this session's earlier
   full-harness wiring audit -- and (b) even when run, it only re-renders
   whatever is already in `.dv-harness/lsf/jobs/*.json`; it does not itself
   poll `bjobs` or analyze logs (that is `dv_harness/lsf_client.py`'s
   `reconcile_batch`, called from elsewhere). Jobs submitted outside
   `lsf_client.py`'s own `bsub_submit()` -- as the live USB generation
   session did, via its own Makefile's native `bsub` -- are invisible to
   this mechanism entirely, since it only reads pre-registered job state
   files.

This spec closes both, since the second depends on the first for
predictable log discovery, and both were requested together.

## Part 1: Standardized sim output layout

Every environment `IP_UVM_DV_Gen` generates gets these directories under
`SIM_ROOT_PATH` (`<project>/sim/`), alongside the already-established
`sim/scripts/`:

```
sim/
|-- scripts/    (existing) Makefile, waves.tcl, LSF scripts, static checks
|-- log/        text logs, one per job/pattern invocation: <job_id_or_pattern>.log
|-- fsdb/       waveform files (per CLAUDE.md's Simulation Observability
|               Default: empty by default, populated only when the
|               Waveform Dump User Gate has approved a scoped dump)
|-- report/     human-readable analysis output: regression snapshots,
|               coverage summaries, DMA/register audit reports
|-- output/     other simulation-produced artifacts that are not logs,
|               waveforms, or reports: memory dumps, generated hex/bin
|               stimulus captured back from a run, scratch files a pattern
|               produces
`-- cov/        coverage database / merge artifacts (URG/IMC-style output,
                whatever the project's real coverage tool produces)
```

**Naming convention inside `log/`**: `<job_id>.log` when the run went
through LSF (matching the real job ID, so the background monitor in Part 2
can find it with no guessing), or `<pattern>_<timestamp>.log` for a
local/interactive run with no job ID. The Makefile template
(`dv_harness/uvm_generator/templates/sim_scripts/Makefile`, internalized
per this session's earlier work) must be updated so its real LSF output
redirection (currently `$(PAT_RUN)/lsf.out`-shaped, per this template's own
documented `LSFW` macro) writes into `sim/log/` using this convention,
not wherever the pattern's own working directory happens to be.

This is a Step 11 file-manifest addition (`.claude/agents/IP_UVM_DV_Gen.md`
and its companion `CORE/ip-uvm-dv-gen/SKILL.md`), not a `dv_harness/`
code change by itself -- it changes what the process instructs an
implementer (human or agent) to create and where the internalized
Makefile template writes its outputs.

## Part 2: Background job/log monitor

### Auto-discovery (no registration required)

Extend `regression_reporter.py`'s watch loop to call a new function,
`discover_live_jobs(vcuser: str) -> list[dict]`, which runs `bjobs -u
<vcuser>` (via the existing zero-credential `remote_exec.py` transport,
never a direct SSH/telnet call from this module) and parses its output
into `{job_id, stat, queue, exec_host, job_name, submit_time}` records --
independent of whether that job was ever registered with `lsf_client.py`.
This gives baseline LSF-status visibility (RUN/DONE/EXIT/PEND) for every
job under that account, submitted through any path (`lsf_client.py`'s
`bsub_submit()`, a generated Makefile's own `bsub`, or a human's manual
`bsub`).

### Registration for deep analysis (optional, opt-in)

Add `lsf_client.py:register_external_job(root: Path, job_id: int, *,
log_path: str, pattern: Optional[str] = None) -> None`, a thin wrapper
that writes a `JobState`-shaped record (reusing the existing `save_job_state`
function) for a job that was NOT submitted via this module's own
`bsub_submit()`. Any agent (including `IP_UVM_DV_Gen`) that submits its own
`bsub` job should call this once, right after submission, with the real
log path per Part 1's naming convention. A job with no registration still
gets baseline LSF-status visibility from auto-discovery; it just does not
get UVM_ERROR/FATAL analysis until/unless registered.

### The reconciliation cycle

On each watch cycle (default every 5 minutes, `--interval-minutes 5` when
launched by the auto-start hook below):

1. `discover_live_jobs()` -- real LSF status for every job under the
   account.
2. For every job that also has a registered `JobState` (via either
   `bsub_submit()` or `register_external_job()`): call the existing
   `reconcile_batch()` to poll `bjobs`, and where the job has reached a
   terminal state (`DONE`/`EXIT`), analyze its real log
   (`dv_harness/sim_log_analysis.py`, wiring its previously-unwired
   `detect_underreporting()` into this call site -- confirmed absent any
   caller by this session's earlier full-harness audit) for UVM_ERROR/
   FATAL counts and known hang/timeout signatures, writing the result back
   via `save_job_state()`.
3. Merge both sets (auto-discovered-only jobs get `dv_analysis_status:
   "UNREGISTERED"` rather than a fabricated value) and call the existing
   `render_snapshot()` to produce the human-readable table, writing it to
   a fixed path (`` .dv-harness/lsf/latest_snapshot.txt ``) the dashboard
   can poll, in addition to the existing stdout print.

### Auto-start / lifecycle

Hook the watcher's start into the real code path that handles Execution
Mode Gate declaration + confirmed SSH/Remote Transport Connection Intake
for `REMOTE_EXECUTION` (the real gate already implemented in
`tools/real_env/execution_mode_validator.py` / wherever the engine calls
it from `dv_harness/engine.py` -- confirm the exact real call site before
implementing, per this project's own evidence discipline; do not assume
a call site from this spec's paraphrase). At that point:

- Check for a live watcher via a PID file (`.dv-harness/lsf/watcher.pid`):
  if the PID is real and running, do nothing (already watching).
- If not running, launch `regression_reporter.py --watch --interval-minutes
  5` as a real detached background process (platform-appropriate: `nohup
  ... &` on the remote Linux side is irrelevant here since this runs
  locally where Claude Code / the harness CLI executes, not on the DV
  server -- use the local platform's real detached-process mechanism), and
  write its PID to the PID file.
- On a clean session/engine shutdown, or when execution mode transitions
  back to `LOCAL_ANALYSIS`, stop the watcher (read the PID file, terminate
  that process, remove the file). A stale PID file (process no longer
  running) is detected and cleaned up automatically on the next
  REMOTE_EXECUTION entry rather than blocking a fresh start.

### Error handling

A single failed `bjobs`/relay call must not kill the watch loop -- log the
failure (one line, to the same log stream the snapshot goes to) and retry
next cycle. A `reconcile_batch()` exception for one job must not prevent
other jobs in the same cycle from being processed.

## Testing Strategy

- `discover_live_jobs()`: real subprocess-call shape tested against a
  mocked `remote_exec.py` response fixture (a realistic `bjobs -u <user>`
  text block), asserting correct parsing into the record shape above --
  and a real integration test against the actual remote transport is out
  of scope for automated tests (no live server in CI) but should be
  spot-verified manually once implemented.
- `register_external_job()`: real filesystem test asserting the written
  `JobState` file matches what `bsub_submit()`-originated jobs produce,
  so `load_job_state()`/`reconcile_batch()` treat both identically.
- Auto-start hook: a test exercising the real REMOTE_EXECUTION declaration
  code path with a fake/no-op watcher launcher, asserting (a) it starts
  when no PID file exists, (b) it does NOT start a second time when a
  live PID file exists, (c) it cleans up and restarts when the PID file is
  stale (process not actually running).
- `render_snapshot()`'s existing behavior (already tested) must not
  regress -- new tests for the "UNREGISTERED" row shape, not a rewrite of
  existing assertions.

## Out of Scope

- Any change to how `IP_UVM_DV_Gen`'s already-in-progress USB generation
  session organizes its OWN existing output (that live work continues as
  currently structured; this spec governs future generations and the
  harness's own permanent capability).
- A dashboard UI panel rendering the new snapshot file (the file existing
  in a fixed, pollable location is in scope; wiring a dashboard view to
  read it is a natural follow-up, not required by this spec).
- Coverage-tool-specific `cov/` merge logic (the directory convention is
  in scope; how a specific coverage tool populates it is protocol/project
  specific and stays out of this spec, matching this process's existing
  "fill in the specifics from the real tool" pattern elsewhere).
