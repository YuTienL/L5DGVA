# Gap #2 Closure: Mandatory 3-Gate Bind-Connectivity Checkpoint

2026-09-03. Closes the confirmed finding that `dv_harness/connectivity.py`'s
3-gate bind-verification standard (elaboration / static zero-time
connectivity / transaction activity) was never applied to the live
`usb31_dev_uvm` build, and that Gate 3's legitimate "no pattern has
completed yet" state (the TCA-hang situation) had no trackable status
distinct from FAILED or "not checked".

## What was already real (read in full before changing anything)

`dv_harness/connectivity.py` already had a real, tested 3-gate pipeline:
`run_gate1_elaboration_check()`, `evaluate_zero_time_connectivity()` /
`run_gate2_against_live_simv()`, `evaluate_transaction_activity()` /
`run_gate3_against_live_simv()`, wired together by `run_machine_gates()` and
reported via `GateReport`/`GateResult`, using a `GateStatus(str, Enum)` of
`PASS`/`FAIL`/`NOT_AVAILABLE`. This was genuine, working code with real unit
tests (`dv_harness_tests/test_connectivity.py`, 43 tests pre-existing) — the
gap was never that the gates didn't work, it was that (a) nothing made
running them mandatory at a specific build milestone, (b) there was no
status value for "invoked but a real prerequisite doesn't exist yet"
distinct from "failed" or "not applicable", and (c) nothing checked that a
build-status report actually surfaced gate status at all.

## What was built

### 1. Extended the existing `GateStatus` enum (not a parallel schema)

Per the task's own instruction to extend rather than duplicate, `GateStatus`
now carries five values instead of three: `PASS`, `FAIL`, `NOT_AVAILABLE`
(all pre-existing) plus two new ones, each with a docstring spelling out
exactly how it differs from every other value so no future caller conflates
them:

- **`PENDING`** — the gate was invoked, but a real workflow prerequisite
  this specific build has not reached yet (the textbook case: Gate 3 before
  any pattern has completed). Transient, expected to resolve to PASS/FAIL,
  never to be read as FAIL.
- **`NOT_YET_RUN`** — the gate has never been invoked in this build/report
  at all. Distinct from PENDING (invoked, waiting) and from NOT_AVAILABLE
  (invoked, found a tooling gap).

New function `evaluate_transaction_activity_status(pattern_completed,
monitor_transaction_counts=None)` resolves Gate 3 honestly: `False` ->
PENDING; `True` + counts -> the real PASS/FAIL verdict via the existing
`evaluate_transaction_activity()`; `True` + no counts -> NOT_AVAILABLE
(genuine tooling gap, not a workflow wait). `run_machine_gates()` gained an
optional `pattern_completed` parameter that routes Gate 3 through this new
resolver when supplied, defaulting to the old behavior when omitted (no
existing caller breaks).

### 2. The mandatory-checkpoint mechanism

- `bind_verification_status_block(gate_report)` — the canonical status
  dict a build-status report must embed. `gate_report=None` explicitly
  returns all three gates as `NOT_YET_RUN` rather than an empty dict, so
  "never run" is never indistinguishable from "the report just left the
  section out."
- `render_bind_verification_status_markdown(gate_report)` — renders the
  exact `## Bind Verification Status` section (`- Gate 1 (elaboration):
  <STATUS>` etc.) both a human-written report and the standalone lint
  script (below) key off.
- `assert_bind_gates_checkpoint(first_compile_succeeded, gate_report)` — the
  real, testable checkpoint assertion. No-ops before first compile
  succeeds; once it does, raises `BindGateCheckpointError` if Gate 1/2 were
  never invoked (`gate_report is None` or either status is
  `NOT_YET_RUN`), but explicitly ACCEPTS Gate 3 being `PENDING` — that is
  the expected state at this checkpoint, not a violation.

## Is the enforcement mechanical code or documentation? Both, deliberately, for different halves of the problem

**Checked first, as instructed:** `.claude/agents/IP_UVM_DV_Gen.md` is
agent-followed prose, not something any code in `dv_harness/` (`engine.py`,
`graph.py`, `gates.py`) parses or drives step-by-step — confirmed by
grepping every reference to `IP_UVM_DV_Gen` across `dv_harness/`: every one
of them (`address_map_verifier.py`, `vplan_writer/writer.py`, the
`sim_scripts/` templates) cites the doc as a source-of-truth *comment*,
never invokes it as code. There is no `STAGE_GATES`-style engine call site
this requirement could be wired into as an automatic gate, because there is
no engine-driven execution of this agent's steps to hook at all.

Given that, the two things that actually **are** real code — the gate
functions themselves, and whatever a human or a future engine-driven build
path can call — got a real, mechanical, unit-tested checkpoint function
(`assert_bind_gates_checkpoint`, section above). That is genuine mechanical
enforcement, usable the moment any code path drives this build instead of
an LLM agent following prose.

For the actual way `IP_UVM_DV_Gen.md` operates today (an agent reading
instructions and producing free-text status reports), the enforcement is
necessarily at the **documentation + artifact-lint** layer, not a runtime
gate:

1. **`.claude/agents/IP_UVM_DV_Gen.md`** gained a new "Mandatory
   bind-verification checkpoint (2026-09-03, Gap #2 closure)" subsection
   under Step 9, stated as a hard requirement ("REQUIRED... not optional,
   not 'when convenient'") rather than available tooling, explaining why
   (cites the confirmed `usb31_dev_uvm` incident by name), what counts as
   satisfying it (any real Gate 1/2 status, including honest
   NOT_AVAILABLE), how Gate 3 PENDING must be reported, and that every
   status report from that checkpoint through Steps 10-11 must carry the
   rendered status block.
2. **`CLAUDE.md`'s "Bind-Location Rules (2026-09-03)" section** gained a new
   paragraph making the same point from the project-policy side: the gates
   are a required workflow checkpoint, not merely existing capability,
   with the same mechanics and a pointer to this report.
3. **`dv_harness/uvm_generator/bind_verification_lint.py`** (new,
   standalone, no dependency on any engine internals beyond importing
   `connectivity.py`'s status constants) — a real script runnable via
   `python -m dv_harness.uvm_generator.bind_verification_lint
   <report_path>` against **any** build tree's own status-report artifact
   (markdown or JSON), that flags exactly the literal failure mode named in
   the task: a report missing Gate 3 (or Gate 1, or Gate 2) status, or one
   carrying an unrecognized status value (typo protection). Real exit
   codes (0 clean, 1 problems found), problems printed by name, never
   raises on malformed input — it reports the parse failure as a problem
   instead of crashing whatever calls it.

This mirrors how this same codebase already handles an analogous situation
(`address_map_verifier.py`'s three-independent-source method: real code,
cited by prose, not engine-invoked) — a documentation requirement backed by
a real, standalone, independently-runnable checking tool is the correct
shape here, not a fabricated "mechanical gate" pretending to hook into an
engine call site that does not exist.

## Verification performed (this session, all commands actually run)

- **Confirmed the "no engine call site" claim** by grepping every reference
  to `IP_UVM_DV_Gen` under `dv_harness/` before writing anything — all 12
  hits are comments/docstrings, zero are code that parses or executes the
  document.
- **New/extended unit tests, all passing (99 tests total in the two
  directly-relevant test files, 0 failures):**
  - `dv_harness_tests/test_connectivity.py` — added tests for: all 5
    `GateStatus` values existing and being pairwise distinct; Gate 3
    resolving to PENDING when no pattern has completed (and staying PENDING
    even if a stray counts dict is passed); Gate 3 correctly delegating to
    real PASS/FAIL once a pattern completes; Gate 3 NOT_AVAILABLE when
    completed but no counts source exists; `run_machine_gates(...,
    pattern_completed=False)` surfacing PENDING and never blocking
    `ready_for_human_review()`; `bind_verification_status_block(None)`
    returning all-`NOT_YET_RUN`; the rendered markdown containing all three
    gate lines; `assert_bind_gates_checkpoint` no-op before compile
    succeeds, raising `BindGateCheckpointError` when gates were never
    invoked at first compile (the literal confirmed incident,
    reason=`GATES_NEVER_INVOKED_AT_FIRST_COMPILE_CHECKPOINT`), accepting a
    PENDING Gate 3 at that checkpoint, and accepting any real Gate 1/2
    status (PASS/FAIL/NOT_AVAILABLE).
  - **Fault-injection proof requested by the task**: two tests build a
    `FakeBuildWorkflow` class modeling an IP_UVM_DV_Gen-style build that
    reaches `first successful compile`, then tries to advance to the next
    documented step. `test_simulated_build_workflow_blocked_from_proceeding_when_gates_skipped`
    reproduces the real defect (gates never run) and asserts
    `try_advance_to_next_step()` raises `BindGateCheckpointError` and the
    workflow's own `advanced_past_checkpoint` flag stays `False`.
    `test_simulated_build_workflow_proceeds_once_gates_1_and_2_actually_run`
    proves the same workflow succeeds once Gates 1/2 are genuinely run
    (Gate 3 still legitimately PENDING) — a real before/after pair, not an
    assertion against a mock that always passes.
  - `dv_harness_tests/test_bind_verification_lint.py` (new file) — clean
    markdown/JSON reports (including a PENDING Gate 3) lint clean; a report
    missing only the Gate 3 line is flagged with the message
    `"gate3 transaction activity status missing from this report"` (the
    literal string named in the task); a report with no bind-verification
    section at all flags all three; an unrecognized status value (`MAYBE`)
    is flagged by name; malformed JSON is reported as a problem, never
    raised as an exception; real temp-file + CLI (`main()`) round-trip
    returns exit code 0/1 correctly; and two round-trip tests prove the
    lint script and `connectivity.py`'s own
    `render_bind_verification_status_markdown()` agree on the same line
    shape (not two independently-guessed formats that coincidentally
    match today).
- **Manual CLI exercise** (outside pytest, via `python -m
  dv_harness.uvm_generator.bind_verification_lint`): ran against a real
  temp file rendered by `render_bind_verification_status_markdown(None)`
  (clean, exit 0) and against a real temp file with no bind-verification
  section (3 problems printed by name, exit 1) — confirmed both the exit
  code and the printed problem text.
- **No live build/gate check was run against the actual `usb31_dev_uvm`
  tree** — per this workflow's own constraint, that tree is owned by a
  separate, currently-running investigation agent. All proof above uses
  synthetic fixtures and a simulated build-workflow object, exactly as the
  task specified.
- **Full-repo test collection** (`pytest --co`, 2577 tests, no execution)
  succeeded with no import/collection errors after these changes, meaning
  the new/edited files do not break any other test module's ability to
  import `dv_harness.connectivity` or the rest of the package. The full
  2577-test suite itself was not executed end-to-end (out of this task's
  scope, and several of its modules exercise unrelated live-server/LSF
  machinery this workflow was told not to touch) — only the 99 tests in
  the two directly-relevant files were run to completion, all passing.

## Files changed

- `dv_harness/connectivity.py` — extended `GateStatus`; added
  `evaluate_transaction_activity_status()`; added `pattern_completed`
  param to `run_machine_gates()`; added `GateReport.pending_gates()`;
  added `BindGateCheckpointError`, `BIND_VERIFICATION_STATUS_KEYS`,
  `bind_verification_status_block()`,
  `render_bind_verification_status_markdown()`,
  `assert_bind_gates_checkpoint()`.
- `dv_harness/uvm_generator/bind_verification_lint.py` (new) — standalone
  report-artifact lint script + CLI.
- `dv_harness_tests/test_connectivity.py` — added the gate-status/
  checkpoint/simulated-workflow tests described above.
- `dv_harness_tests/test_bind_verification_lint.py` (new) — lint script
  tests.
- `.claude/agents/IP_UVM_DV_Gen.md` — new "Mandatory bind-verification
  checkpoint" subsection under Step 9.
- `CLAUDE.md` — new paragraph in the "Bind-Location Rules (2026-09-03)"
  section making the gates a required workflow checkpoint.

## Test summary

99/99 passed (`dv_harness_tests/test_connectivity.py` +
`dv_harness_tests/test_bind_verification_lint.py`); whole-repo collection
(2577 tests) clean with no import errors introduced.
