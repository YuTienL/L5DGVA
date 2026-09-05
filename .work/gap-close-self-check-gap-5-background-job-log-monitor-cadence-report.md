# Gap 5 — Background job/log monitor cadence (self_check_list.md #41)

**Status: DONE**

**Verdict on entry (re-confirmed, not taken on trust): PARTIALLY_WIRED.**
The mechanism is real; the cadence contract was unenforced and three of the
four real entry points shipped a cadence outside the spec's ceiling.

---

## 1. What the spec asks

`.work/self_check_list_utf8.md:307`

```
#41 建立背景觀察各個 job 和 simulation log 的狀態的機制。每隔10分鐘自動確認
```

Read as a **ceiling** on the cycle period, not an exact value: checking more
often than every 10 minutes still satisfies "the operator is never blind for
longer than 10 minutes"; checking less often does not. That reading is now
written down in code (`regression_reporter.SPEC_MAX_INTERVAL_MINUTES`) rather
than left to the reader.

## 2. Evidence re-confirmed (all cited lines re-read this pass)

The handed-over audit was accurate. Re-verified before touching anything:

- **The mechanism is real.** `dv-harness lsf-watch-start` →
  `dv_harness/cli.py:337-350` → `cli.py:1863-1877` →
  `regression_reporter.ensure_watcher_running()`
  (`dv_harness/regression_reporter.py:735-…`), which spawns a genuinely
  detached `subprocess.Popen(... start_new_session=True` / `DETACHED_PROCESS)`
  tracked by a PID file, with stdout appended to
  `.dv-harness/lsf/watcher.log`.
- **It is fixed-interval polling, not event-driven.** `main()`'s loop is
  `_run_one_cycle()` then `time.sleep(max(1, interval_minutes) * 60)`
  (`regression_reporter.py:851`, post-change numbering). Confirmed by reading
  the loop, not inferred.
- **5 minutes was a deliberate design decision**, not an accident:
  `docs/superpowers/specs/2026-09-01-sim-output-layout-and-background-job-monitor-design.md:164`
  — *"On each watch cycle (default every 5 minutes, `--interval-minutes 5`
  when launched by the auto-start hook below)"*. 5 ≤ 10, so the sanctioned
  path was already inside #41's ceiling and was **left unchanged**.

## 3. The real, bounded gap that was actually there

The sanctioned path was fine. Everything around it was not — **five** places
declare this cadence and they did not agree, with **four of the five outside
the 10-minute ceiling**:

(Line refs in this table are **pre-change** numbering.)

| Entry point | Cadence before | Inside #41's 10min ceiling? |
|---|---|---|
| `dv-harness lsf-watch-start` (`cli.py:342`) | 5 | yes |
| `python -m dv_harness.regression_reporter --watch` (`regression_reporter.py:809`) | **30** | **no** |
| `DV_REGRESSION_SNAPSHOT.ps1 -Watch` (`param([int]$IntervalMinutes=30…)`) | **30** | **no** |
| `.dv-harness/lsf/periodic_snapshot_policy.json` `default_interval_minutes`, which `.claude/agents/regression-agent.md:165` orders the Regression Agent to report on | **30** | **no** |
| `.claude/skills/CORE/periodic-regression-snapshot/SKILL.md:7` — 預設每 **30** 分鐘產生一次完整 snapshot | **30** | **no** |

Plus: **nothing tested any default.** Every pre-existing test
(`dv_harness_tests/test_cli_lsf_watch.py:98/122/134/147`) passes an explicit
`--interval-minutes 30`, so the shipped cadence was untested in all four
places and a silent edit to any of them would have gone unnoticed.

That is the gap: not "5 ≠ 10", but *the harness had no single, tested
statement of what its background-monitor cadence is, and most of its real
entry points violated the spec.*

## 4. What changed

Extended existing code only — no new module, no parallel mechanism.

**`dv_harness/regression_reporter.py`** (the one module all four entry points
already fan into):
- `DEFAULT_INTERVAL_MINUTES = 5` and `SPEC_MAX_INTERVAL_MINUTES = 10` — the
  single source of truth, with the #41 quotation and the design-doc citation
  in the comment.
- `interval_compliance(interval_minutes) -> dict` — `{interval_minutes,
  spec_max_interval_minutes, compliant, message}`. Deliberately **advisory,
  not a clamp**: an operator who really wants a slow watcher (long overnight
  soak on a shared cluster) keeps that control; they just cannot get it by
  accident or in silence.
- `ensure_watcher_running()` and `main()` now default from the constant; the
  module's own `--interval-minutes` argparse default went **30 → 5** and
  gained real help text.
- `main()` in watch mode prints its real cadence as the first line of
  `.dv-harness/lsf/watcher.log`, so a running watcher's cadence is
  discoverable without re-deriving it from argv.

**`dv_harness/cli.py`** — `lsf-watch-start` calls `interval_compliance()` and
prints `[warn] …` to **stderr** when the requested interval exceeds the
ceiling. Stdout stays pure JSON (callers parse it; the existing
`assert out == {"started": True, "pid": pid}` exact-dict tests still hold).

**`DV_REGRESSION_SNAPSHOT.ps1`** — `-IntervalMinutes` default 30 → 5.

**`.dv-harness/lsf/periodic_snapshot_policy.json`** —
`default_interval_minutes` 30 → 5, plus an explicit
`spec_max_interval_minutes: 10` and a note pointing at #41 and at
`regression-agent.md:165`.

**`.claude/skills/CORE/periodic-regression-snapshot/SKILL.md`** — the CORE
skill an agent actually reads before producing a snapshot said 預設每 **30**
分鐘, a number an agent would have followed straight past the ceiling. Now 5,
with the 10-minute ceiling and both constant names stated inline.

**`CLAUDE.md`** — the "Background Job/Log Monitor Auto-Start" section stated
no numeric interval at all. It now has a **Cadence** paragraph: fixed-interval
polling, 5-minute default, 10-minute spec ceiling, and the fact that a slower
interval warns rather than fails.

## 5. Tests

New: **`dv_harness_tests/test_watch_cadence_spec.py`** — 22 tests, four groups:

- `TestSpecCeiling` — the ceiling is 10, the default is inside it, compliant/
  non-compliant classification at 1/5/9/10 and 11/30/120, non-compliance is
  advisory (does not rewrite the operator's number), and sub-minute input is
  floored the same way `main()`'s `max(1, …)` sleep floors it.
- `TestEveryEntryPointSharesTheDefault` — pins all five declarations to the
  one constant. The CLI one drives the **real argv path** (`cli.main()` with
  patched `ensure_watcher_running`) and asserts what actually arrives, rather
  than re-reading source.
- `TestWatchLoopAnnouncesItsCadence` — watch mode logs its cadence once and
  says `SLOWER` at 30; single-shot mode stays quiet.
- `TestCliWarnsOnSlowCadence` — **real CLI subprocesses**: `--interval-minutes
  30` still starts and warns on stderr with clean JSON on stdout; the default
  invocation produces no warning. Both hard-stop the spawned watcher in
  `finally`.

## 6. Test summary

- Targeted: `test_watch_cadence_spec.py` — **22 passed**.
- Watcher-related suites together
  (`test_regression_reporter.py` + `test_cli_lsf_watch.py` +
  `test_watch_cadence_spec.py`) — **56 passed in 73.60s**.
- Real end-to-end smoke of the new warning path (not a test, a real CLI run):

  ```
  $ python -m dv_harness.cli --project-root <tmp> lsf-watch-start \
        --vcuser vcuser1 --uvm-root-path <tmp>/uvm --interval-minutes 45
  [warn] background job/log monitor cadence 45min is SLOWER than the 10min
  self_check_list #41 ceiling: jobs and simulation logs can go unconfirmed
  for up to 45 minutes            <- stderr
  {"started": true, "pid": 54840} <- stdout, still clean JSON
  ```
- **Full suite: all 5592 tests in `dv_harness_tests/` run — 5581 passed, 11
  non-passes, all one pre-existing environmental cause unrelated to this
  change.** Run in 9 balanced chunks (`-q -p no:randomly`) because a single
  `pytest dv_harness_tests` process exceeded the 10-minute tool ceiling:

  | chunk | result |
  |---|---|
  | 0 `test_active_stages_read_sites` … `test_blackboard_subsystem_wiring` | 627 passed |
  | 1 `test_canfd_arbitration_generator` … `test_coverage_points_dsl` | 633 passed, **5 failed** (all `test_cli_pueue.py`) |
  | 2 `test_cross_adapter_token_tracking` … `test_escalation_wiring` | 633 passed |
  | 3 `test_evidence_db` … `test_intake_upload` | 628 passed |
  | 4 `test_interface_and_conditional_components` … `test_memory_search_filters` | 634 passed |
  | 5 `test_memory_security` … `test_question_queue_digest_auto_trigger` | 619 passed, **6 errors** (all `test_pueue_client.py::TestRealPueueIntegration`) |
  | 6 `test_rca_multi_agent_fanout` … `test_session_and_info` | **672 passed** on re-run (a single failure in the first pass did not reproduce — it was contention with a concurrently-running full-suite process) |
  | 7 `test_signoff_bundle_completeness_gate` … `test_system_level_soc_composition_wiring` | 624 passed |
  | 8 `test_system_regression_readiness_and_phase1_report` … `test_workflow_rca_multi_agent_fusion` | 511 passed |

  **The 11 non-passes are one environmental root cause, not a regression.**
  The local pueue daemon is down and cannot be restarted:

  ```
  $ pueue status
  2: Failed to connect to the daemon on 127.0.0.1:6924. Did you start it?
  $ pueued -d
  Pueued is now running in the background
  Error:  0: Failed to create pid file.      <- stale %LOCALAPPDATA%\pueue\pueue.pid (dated 九月 3 23:31)
  ```

  plus a dozen orphaned `pueue.exe` client processes. All 11 non-passes are
  `pueue`-daemon tests (`assert 1 == 0` on the CLI's exit code, and
  `AssertionError: real pueued did not come up` at
  `test_pueue_client.py:323`). Nothing in this change touches the pueue path.
  Corroborated independently: an earlier near-complete run of the same tree,
  started before the daemon died, reached 96% with **zero** F/E markers —
  i.e. those same pueue tests passed then. The daemon was deliberately not
  force-repaired (killing it would disrupt other work running on this
  machine).

## 7. Not done, and why

- **The 5-minute default was not changed to 10.** It is a documented design
  decision, it satisfies the spec's ceiling, and tightening a monitor's
  cadence toward the limit would be a regression in observability with no
  requirement behind it.
- **No clamp / no hard failure on a slow interval.** Silently overriding an
  explicit operator flag is worse than a loud warning; `interval_compliance()`
  reports and lets the operator proceed.
- **`docs/superpowers/specs/2026-09-01-…-design.md:18`** still says "default
  30 minutes". Left alone deliberately: it is that spec's *problem statement*
  describing the state of the world before the watcher was built, and it was
  accurate then. Rewriting history in a design doc would be worse than leaving
  it.
- **`.dv-harness/lsf/` is gitignored as runtime state** but
  `periodic_snapshot_policy.json` is already tracked, so the fix was staged
  with `git add -f`. Whether that seed file should move out of the ignored
  runtime directory is a separate housekeeping question, not this gap.
