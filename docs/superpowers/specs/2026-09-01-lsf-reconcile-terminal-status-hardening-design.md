# LSF Reconcile Terminal-Status Hardening — Design Spec

## Context

The just-completed background-job-monitor-and-regression-list-safety-net
plan (`docs/superpowers/specs/2026-09-01-sim-output-layout-and-background-job-monitor-design.md`,
implemented via `docs/superpowers/plans/2026-09-01-background-job-monitor-and-regression-list-safety-net.md`)
closed a Critical bug where the reconciliation cycle's job-id union was
unbounded, and a follow-up fix (commit `cf6a753`) bounded it so a
**settled** job (lsf-terminal AND already analyzed) drops out of the
union once its work is done — `regression_reporter.py`'s
`_job_still_owes_reconciliation()`.

That fix's own final review surfaced three related, honestly-disclosed,
non-blocking residuals that this spec now closes:

1. **`reconcile_job()` can still downgrade an already-recorded terminal
   status to `UNKNOWN`.** The bounding fix only removes a job from the
   reconciliation *union* once it is settled — but a job that is
   lsf-terminal and **can never be analyzed** (a truncated/unparseable
   log with no epilogue) is deliberately kept at `sim_status="UNKNOWN"`
   forever, specifically so its `ANALYSIS_OWED` alarm keeps firing. That
   job can therefore never leave the union, and every cycle it stays in
   still calls `reconcile_job()` against it. If LSF has since forgotten
   the job (past `CLEAN_PERIOD`), `bjobs_query_many()` returns `{}` for
   it, `reconcile_job()` maps the absent record to `live_status =
   "UNKNOWN"`, sees it differs from the recorded `"DONE"`/`"EXIT"`, and
   overwrites `state.lsf_status` with `"UNKNOWN"` — destroying a real,
   previously-confirmed fact for no reason other than LSF's own retention
   window expiring. This directly contradicts the project's own "LSF
   DONE is not equal to DV PASS" principle, which exists to make LSF
   status a durable, trustworthy fact independent of the tool's own
   bookkeeping lifetime.
2. **`_run_bjobs()` has no return-code or partial-failure handling.** A
   single unparseable batch response (e.g. because one of the requested
   ids is one LSF has completely forgotten) raises `LsfUnavailableError`
   for the **entire batch**, costing every other, perfectly healthy job
   in that batch one full analysis cycle. `reconcile_batch()` catches
   this at the `regression_reporter.py` call site and simply logs and
   moves on — but the lost cycle is still lost.
3. **`LsfStatus`'s terminal set is incomplete.** `KILLED` is a real,
   declared `LsfStatus` value (`lsf_client.py:20-21`) that
   `cli.py`'s `lsf-auto-kill-scan` genuinely writes, but every
   terminal-status check in this codebase (`regression_reporter.py:118`,
   `:200`; `reconcile_job()`'s own `("DONE", "EXIT")` checks) tests only
   `("DONE", "EXIT")`. A `KILLED` job is real-world terminal (LSF will
   never resume it) but is not treated as such, so it stays in the
   reconciliation union one cycle longer than necessary. Impact is small
   in practice — the next successful reconcile typically rewrites it to
   a real `EXIT` — but it is a real inconsistency between the declared
   type and its actual use.

None of these three block the prior plan's completion (all were
independently verified as pre-existing, narrowed-not-introduced, and
each has a clear, separately-scoped fix) — this spec is that follow-up
fix.

## Part 1: Terminal status is authoritative once observed — `reconcile_job()` must never downgrade it on an absent record

**The rule:** once `state.lsf_status` has been confirmed as a real
terminal value (`"DONE"`, `"EXIT"`, or `"KILLED"` — see Part 3), an
**absent** live bjobs record (LSF has no information at all — the record
passed to `reconcile_job()` has no `"STAT"` key, or `bjobs_query_many()`
returned `{}` for that id) must never overwrite it. LSF's own retention
window expiring is not new evidence that the job's outcome changed; it
is the tool forgetting, and a real, previously-observed fact must
outlive the tool's bookkeeping.

This must be scoped precisely to the *absent-record* case, not to every
value `map_bjobs_stat_to_lsf_status()` happens to map to `"UNKNOWN"`. A
live bjobs call that explicitly reports an ambiguous real status
(`"UNKWN"`, `"ZOMBI"`) for a job **is** new evidence, however odd, and is
out of scope for this narrower fix. The distinguishing signal already
exists at the call site: `live_bjobs_record.get("STAT") is None` means
no record was found at all (this is exactly what
`bjobs_query_many()`'s `result = {jid: {} for jid in job_ids}` default
produces for a missing id, and what `reconcile_job()`'s docstring/tests
should encode as "absent," not "reported unknown").

**Change to `reconcile_job()`** (`dv_harness/lsf_client.py:392-435`):
before the existing `live_status = map_bjobs_stat_to_lsf_status(...)`
comparison-and-overwrite block, detect the absent-record case
(`live_bjobs_record.get("STAT") is None`) combined with the currently
recorded status already being terminal (`state.lsf_status in ("DONE",
"EXIT", "KILLED")` — see Part 3 for adding `"KILLED"` to this set
project-wide). When both hold: skip the `state.lsf_status = live_status`
overwrite entirely, and record an `INFO`-severity `Discrepancy` (a new,
lower severity than the existing `WARN`/`CRITICAL` values already on
`Discrepancy.severity`'s `Literal` — add `"INFO"` to that type) stating
the retained status and that LSF no longer reports it, rather than a
`WARN` implying a real, actionable status change. When the record is
absent but the currently recorded status is NOT already terminal (e.g.
still `"PEND"`/`"RUN"`/`"UNKNOWN"`), the existing overwrite-to-`UNKNOWN`
behavior is correct and unchanged — an absent record for a job that
was never confirmed terminal is genuinely new (if disappointing)
information, not a case to protect against.

**Callers relying on `Discrepancy.severity` values must not break**:
`reconcile_batch()`'s and `_write_job_tier_memory_on_terminal_reconcile()`'s
existing logic keys only on `"CRITICAL"` and `"WARN"` explicitly — adding
a third `"INFO"` value that nothing currently matches against is
additive and must not change any existing branch's behavior. Verify this
by reading both functions' real current logic before implementing (do
not assume from this description alone).

## Part 2: `_run_bjobs()` per-id fallback on batch failure

**The rule:** a single unparseable or failed batch `bjobs` call must
never cost every OTHER, healthy job in that batch a lost analysis cycle.
When the batch call fails (nonzero return code, or a `JSONDecodeError`
on `proc.stdout`), retry each requested job id individually
(`bjobs -json -o "..." <single-id>`, matching the batch call's own `-o`
column list) before giving up on any of them. An id that still fails
its own individual call is the only one recorded as failed/absent for
this cycle; every id whose individual retry succeeds is processed
normally.

**Design boundary:** this fallback only ever triggers when the batch
call itself failed — it must add zero overhead to the common case (a
healthy batch response). Do not restructure `bjobs_query_many()`'s
happy-path logic; the fallback is additive, invoked only from
`_run_bjobs()`'s existing two `except` blocks (the `JSONDecodeError`
catch at `lsf_client.py:128-133`, and — decide during implementation
whether a nonzero `proc.returncode` with parseable-but-empty
`RECORDS` should also trigger it, since a real LSF `bjobs` invocation
with some unknown ids may still emit valid JSON for the known ones and a
nonzero exit code for the unknown ones; this exact behavior needs to be
confirmed against real LSF at implementation time — do not assume either
way, per this project's own evidence-before-conclusion discipline. If it
cannot be confirmed in this environment, implement defensively for the
"nonzero code but stdout parses" case too, since it is the cheaper case
to get right regardless of which way real LSF actually behaves).

**Cost, stated plainly**: in the failure case only, this changes one
batch call into up to N single-id calls (N = batch size). This is a
real, accepted cost — it happens only when something in the batch was
already going to be a lost cycle for at least one id, and it converts
"lose the whole batch" into "lose only the ids that are genuinely gone."

**New function signature** (exact name/shape is an implementation
choice, but it must be a distinct, separately-testable unit — do not
inline the retry loop directly into `_run_bjobs()`'s body in a way that
makes the fallback path untestable in isolation): something in the
shape of `_run_bjobs_with_fallback(job_ids: list[int]) -> dict`, called
from `bjobs_query_many()` in place of the current direct `_run_bjobs(job_ids)`
call, preserving `bjobs_query_many()`'s existing return contract exactly
(a dict keyed by every requested id, each value either a real record or
`{}}` for one that could not be resolved even after the per-id retry).

## Part 3: Add `KILLED` to every terminal-status check

**The rule:** anywhere this codebase currently tests
`status in ("DONE", "EXIT")` to mean "this job is lsf-terminal, no
further live-status change is expected," `"KILLED"` must be included
too, since it is a real, declared `LsfStatus` value this codebase
itself writes (`cli.py`'s `lsf-auto-kill-scan`) and is exactly as
terminal in the real world as `DONE`/`EXIT`.

**Known call sites to update** (verify this list is complete by
grepping for `("DONE", "EXIT")` and `["DONE", "EXIT"]` across
`dv_harness/` at implementation time — do not trust this list alone):
- `dv_harness/regression_reporter.py:118` (`_job_still_owes_reconciliation()`)
- `dv_harness/regression_reporter.py:200`
- `dv_harness/lsf_client.py`'s Part 1 fix above (the new terminal-set
  check this spec's Part 1 introduces must already include `"KILLED"`
  from the start, not be patched separately)

**Explicitly NOT in scope for this change**: `reconcile_job()`'s
existing `if live_status in ("DONE", "EXIT") and state.sim_status in
("UNKNOWN", "RUNNING"):` block (`lsf_client.py:418`), which arms the
`CRITICAL` `ANALYSIS_OWED` discrepancy. A `KILLED` job was deliberately
terminated (by this codebase's own auto-kill-scan, per its own recorded
policy) — it does not "owe" a pass/fail verdict the way a `DONE`/`EXIT`
job does, since its result was never allowed to complete. Adding
`KILLED` to *this* check would incorrectly demand analysis for jobs this
project itself chose to abort. If a future need arises to track why
something was killed, that is a distinct concern from this spec's scope
and should be designed separately, not folded in here.

## Testing Strategy

- **Part 1**: a test proving a job recorded as `lsf_status="DONE"` whose
  live bjobs record is absent (`{}` or a dict with no `"STAT"` key)
  retains `lsf_status="DONE"` after `reconcile_job()`, with an `INFO`
  discrepancy recorded (not `WARN`, not silently dropped) explaining
  why. A second test proving the ORIGINAL, still-correct behavior is
  unchanged: a job recorded as `lsf_status="RUN"` whose live record is
  absent DOES get overwritten to `"UNKNOWN"` (this is a real transition
  worth surfacing, not a case this fix protects). A third test proving
  a job recorded as `lsf_status="KILLED"` (Part 3) is protected the same
  way as `DONE`/`EXIT`. Do not re-test `reconcile_job()`'s pre-existing,
  unrelated discrepancy fields (`sim_log` mismatch, the `CRITICAL`
  `ANALYSIS_OWED` arming) — only the new terminal-protection behavior
  needs new coverage.
- **Part 2**: a test where the first (batch) `_run_bjobs`-equivalent call
  is mocked to raise/fail, and the per-id fallback is mocked to succeed
  for some ids and fail for others — assert the successful ids get real
  records back and only the genuinely-failing id(s) get `{}`, proving
  the batch failure no longer poisons the whole result. A second test
  proving the healthy-batch happy path makes exactly one `bjobs` call
  (no fallback overhead when nothing failed).
- **Part 3**: a test proving a `KILLED` job is excluded from
  `_job_still_owes_reconciliation()`'s "still owes" set once already
  analyzed (mirroring the existing settled-`DONE`/`EXIT` test this
  mirrors), and is NOT treated as needing an `ANALYSIS_OWED` alarm
  (confirming the Part 3 "explicitly not in scope" boundary is actually
  respected in the implementation, not just stated in this spec).

## Out of Scope

- Redesigning `Discrepancy`'s severity taxonomy beyond adding the one
  new `"INFO"` value Part 1 needs.
- Any change to how or when a job is actually auto-killed
  (`lsf-auto-kill-scan`'s own policy/logic) — this spec only changes how
  an already-`KILLED` status is *treated* once observed.
- A general retry/backoff policy for `bsub`/`bkill` or any other LSF
  subprocess call in this file — Part 2's per-id fallback is scoped
  specifically to `bjobs`'s batch-query path, the one place a single
  bad id can silently cost unrelated jobs their own analysis.
- Determining real LSF's actual behavior when a batch `bjobs -json` call
  includes both valid and long-forgotten ids (flagged as an open,
  implementation-time verification question in Part 2, not resolved by
  this spec) — if it cannot be confirmed against a real LSF instance,
  implement the defensive interpretation Part 2 already describes rather
  than blocking on confirmation.
