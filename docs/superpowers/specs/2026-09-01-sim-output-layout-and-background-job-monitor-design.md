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

## Revision note (2026-09-01, post-distillation)

Three multi-agent distillation passes over a real sibling project
(`D:\DV\Task\USB`) ran after this spec was first written, and their
findings are now fully documented in `IP_UVM_DV_Gen.md`/
`CORE/ip-uvm-dv-gen/SKILL.md`. Two of those findings directly correct
assumptions this spec made, and are applied below:

1. **`regression.list` does not live under `sim/`.** It must survive
   `make distclean` (which wipes build/run products), so it lives in
   `UVM_ROOT_PATH` (`<project>/uvm/regression.list`), not
   `SIM_ROOT_PATH`. Part 3 originally said `<project>/sim/regression.list`
   -- that was wrong; `IP_UVM_DV_Gen.md` already documents the correct
   location as of this distillation pass, so this spec is now the
   stale side of that disagreement. Fixed below.
2. **A real, already-proven, already-internalized Make-native mechanism
   (`record_result`/`record_suite`, gated by `RECORD=1`/`IN_REGRESS`)
   already maintains `regression.list` correctly for the common case**
   -- any job run via the generated environment's own
   `make sim RECORD=1` / `make regress RECORD=1`. This was not known
   when Part 3 was first written; Part 3 treated
   `regression_list_manager.py`'s Python-side wiring as "the fix" for
   an unwired gap. It no longer is the fix for the common case -- it is
   a secondary safety net for a narrower, still-real scenario. See the
   rewritten Part 3 below for what changed and why.

Part 1's directory layout and Part 2's background monitor are
otherwise unaffected by this distillation work, with one small
addition to Part 1 (the real `run/`-vs-`report/`-symlink-view design,
also newly confirmed real) noted in place below.

## Part 1: Standardized sim output layout

Every environment `IP_UVM_DV_Gen` generates gets these directories under
`SIM_ROOT_PATH` (`<project>/sim/`), alongside the already-established
`sim/scripts/`:

```
sim/
|-- scripts/    (existing) Makefile, waves.tcl, LSF scripts, static checks
|-- run/        the REAL per-job/per-pattern working directory: simv's
|               actual cwd and the one real sim.log per invocation
|-- log/        <job_id_or_pattern>.log -- a SYMLINK into run/'s real
|               sim.log, created before simv starts (see below)
|-- fsdb/       waveform files (per CLAUDE.md's Simulation Observability
|               Default: empty by default, populated only when the
|               Waveform Dump User Gate has approved a scoped dump)
|-- report/     a SYMLINK VIEW into run/ (not a second copy) plus other
|               human-readable analysis output: regression snapshots,
|               coverage summaries, DMA/register audit reports
|-- output/     other simulation-produced artifacts that are not logs,
|               waveforms, or reports: memory dumps, generated hex/bin
|               stimulus captured back from a run, scratch files a pattern
|               produces
`-- cov/        coverage database / merge artifacts (URG/IMC-style output,
                whatever the project's real coverage tool produces)

(regression.list is NOT under sim/ -- it lives at UVM_ROOT_PATH/
regression.list so it survives make distclean; see Part 3.)
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

**`run/` is real, `report/` and `log/` are symlink views into it (2026-09-01,
distilled and confirmed real).** A real sibling project's own design,
now also documented in `IP_UVM_DV_Gen.md`: `run/<job_or_pattern>/` holds
the actual simv working directory and the one real `sim.log`; `report/`
and `log/` entries for the same job are symlinks pointing back into
`run/`, never a second copy of the file. Critically, both symlinks are
created **before** `simv` starts, not collected afterward -- a
hard-killed job (`bkill`, a crashed relay, a manual `kill -9`) still
leaves a reachable transcript at its `log/<job_id>.log` path, because
the symlink already existed before the process that might die ever
started. Both `run/` and its two view directories are wiped and
recreated per invocation; a stale symlink from a prior run is never
left dangling. This is a real design detail the directory list above
does not yet capture -- when implementing, `run/` should join the
directory list as the seventh member (alongside `scripts/`, `log/`,
`fsdb/`, `report/`, `output/`, `cov/`), and `log/`/`report/`'s own
descriptions should say "symlink view into `run/`," not "a copy of the
log."

**`regression.list` is explicitly NOT one of these directories.** It
lives in `UVM_ROOT_PATH` (`<project>/uvm/regression.list`), a sibling
of `SIM_ROOT_PATH`, specifically because it must survive `make
distclean` -- a build/run product wipe must never erase a durable,
cross-run index of which patterns currently pass. See Part 3 for the
corrected treatment; do not place it under any `sim/` subdirectory.

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

## Part 3: Automatic regression-list maintenance (revised 2026-09-01)

**The common case is already solved, natively, by the generated
environment's own Makefile -- this is no longer "the fix," it is
background context that dv_harness's own mechanism must respect,
not duplicate or fight.** The
internalized, already-generic Makefile template
(`dv_harness/uvm_generator/templates/sim_scripts/Makefile`, per the
2026-09-01 distillation pass, now documented in `IP_UVM_DV_Gen.md`'s
Build System section as "Tracked-passing-suite list (regression.list /
RECORD=1)") implements a real, proven `record_result`/`record_suite`
mechanism: `make sim RECORD=1 PATTERN=<name>` updates a single pattern's
entry on its own real log; `make regress RECORD=1` walks every pattern
in the suite once, after all jobs finish, and rewrites the whole list.
Both use the same idempotent shape `regression_list_manager.py`
independently implements in Python (strip any existing line for the
pattern, re-append only on a confirmed PASS) -- and `record_result` is
deliberately gated OFF under `IN_REGRESS=1` (i.e. inside a parallel
regression batch) specifically to avoid N parallel hosts
read-modify-writing the same file and losing entries, a real race this
project's own design already had to solve. **For any job that runs
through this Makefile with `RECORD=1` set, regression.list is already
correctly maintained with zero dv_harness involvement.** Nothing in
dv_harness needs to detect this case or avoid duplicating it -- see
"Why redundant execution is safe" below.

**`regression_list_manager.py`'s Python-side mechanism is a safety net
for a narrower, still-real case: jobs dv_harness tracks that do NOT go
through a `RECORD=1`-enabled Make target at all.** This case is real,
not hypothetical -- `dv_harness/cli.py` exposes a live `lsf submit`
command that calls `lsf_client.py:bsub_submit()` directly with an
arbitrary shell command string (confirmed by reading the current code,
not assumed); nothing requires that command to be
`make sim PATTERN=<x> RECORD=1`, and a human or agent using this path
(or registering an externally-submitted job via
`register_external_job()`) can easily submit something that never
touches the Makefile's own RECORD mechanism at all. For exactly this
narrower case, extend Part 2's reconciliation cycle (step 2 of "The
reconciliation cycle" above, where a terminal job's real log gets
analyzed for UVM_ERROR/FATAL counts): once a job's real pass/fail
verdict is determined for a job carrying a known `pattern` name (from
its registered `JobState`, either via `bsub_submit()` or
`register_external_job()`), call `record_verdict()` against that
project's real `regression.list` at **`UVM_ROOT_PATH/regression.list`**
(`<project>/uvm/regression.list` -- corrected from this spec's original
`<project>/sim/regression.list`, which was wrong; see the Revision note
above and Part 1's corrected treatment) and persist the updated list
back to disk. A job with no known `pattern` name (e.g. an
auto-discovered-only job with no registration) cannot update the
regression list -- this is a real, honest limitation of unregistered
jobs, consistent with Part 2's own "UNREGISTERED" status handling, not
a defect to silently work around.

**Why redundant execution is safe, and why no detection logic is
needed to avoid it.** A job that already went through
`make regress RECORD=1` will have its pattern correctly present (or
absent) in `regression.list` by the time dv_harness's reconciliation
cycle gets to it. If that job also happens to be tracked by dv_harness
(registered via `bsub_submit()`/`register_external_job()`) and its
reconciliation cycle also calls `record_verdict()` for the same
pattern and verdict, the result is a no-op -- `record_verdict()`'s own
strip-then-conditional-append shape is idempotent, so calling it twice
with the same `(pattern, verdict_passed)` produces the exact same list
either way. **Do not add logic to detect "did the Make-native
mechanism already handle this job" and skip the Python-side call when
it did** -- that detection would require parsing an arbitrary command
string for `RECORD=1`, is fragile (the flag could arrive via
environment rather than argv), and buys nothing: the idempotent
behavior already makes the redundant case free of any correctness or
data-loss risk. Simplicity wins here (YAGNI) over a "smarter" call
site that adds fragile detection for zero actual benefit.

**Verdict source of truth**: reuse the exact same UVM_ERROR/FATAL-count
based pass/fail determination Part 2's reconciliation step already
produces (via `sim_log_analysis.py`) -- do not introduce a second,
divergent definition of "passed" for this purpose. If Part 2's analysis
cannot conclusively determine a verdict (e.g. the log is truncated, or a
recognized-but-unclassified failure signature is present), do not call
`record_verdict()` at all for that job rather than guessing -- an
indeterminate result must never silently count as either a PASS (would
wrongly keep failing patterns in the regression list) or a FAIL (would
wrongly evict a genuinely-passing pattern over a transient analysis
failure).

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
- Part 3's wiring (revised 2026-09-01): a real test proving that a
  reconciliation cycle for a registered job with a real PASS verdict
  calls `record_verdict()` and the pattern appears in
  `UVM_ROOT_PATH/regression.list` (corrected path -- not
  `sim/regression.list`); a second test for a FAIL verdict evicting a
  previously-recorded PASS; a third test proving an
  indeterminate/unanalyzable verdict calls `record_verdict()` NOT AT ALL
  (list unchanged) rather than guessing either direction; a fourth test
  proving that calling `record_verdict()` twice in a row with the same
  `(pattern, verdict_passed)` (simulating the Make-native mechanism
  having already recorded the same verdict) produces an identical list
  both times -- the idempotency guarantee the "redundant execution is
  safe" design relies on, exercised as a real test rather than only
  asserted in prose. Do not re-test `record_verdict()`/`record_suite()`
  themselves -- they are already correct and already have their own
  test coverage; only the new call site needs new tests.

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
