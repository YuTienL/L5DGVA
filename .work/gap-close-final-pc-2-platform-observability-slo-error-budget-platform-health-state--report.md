# PC-2 — Platform observability + SLO/error-budget + platform health-state

**Status: DONE**
**Tests: 37 new (`dv_harness_tests/test_platform_health.py`) all pass; 171 pass across the six neighbouring suites I could have broken (`test_loop_telemetry`, `test_connectivity_check`, `test_execution_preflight_wiring`, `test_trend_analysis`, `test_preflight`, `test_cli_preflight`).**
**Commit: `c1f89ef` on branch `gap-close/env-manifest-fact-sources` (not main/master; PR-only governance untouched).**

---

## 1. The gap was re-verified independently, and it was real

Repo-wide greps run this session, before writing anything:

- `grep -rn "error_budget\|health_state" --include=*.py dv_harness/ dv_harness_tests/` → **0 hits**
- `grep -rn "\bSLO\b\|slo_" --include=*.py dv_harness/ dv_harness_tests/` → **0 hits**
- `grep -rn "platform_health\|health_aggregat" ...` → **0 hits**
- `HEALTHY`/`DEGRADED` hits were all `degradation.py`'s single **global** NORMAL/DEGRADED mode, `capability_evolution.py`'s `BENCHMARK_OUTCOMES` (an unrelated vocabulary), and prose in comments.

So: no SLO, no error budget, no per-subsystem health state. The only health-ish state was `degradation.py`, which is one global mode driven by three triggers — genuinely not a per-subsystem picture, and not something to be duplicated.

## 2. What I built (all of it real, nothing measured by this module itself)

`dv_harness/platform_health.py` (1055 lines incl. docstrings) — a **read-only aggregator**.

### Eight subsystems, each from an existing real producer

| subsystem | real source read |
|---|---|
| `agent_adapter` | `degradation.describe()` — `adapter_unavailable` trigger + failure streak |
| `eda_license` | `degradation` `eda_license_full` trigger **+** the `eda_license` `CheckOutcome` carried by the last recorded `EXECUTION_PREFLIGHT_*` event |
| `lsf_queue` | same, `farm_queue_congested` + `lsf_queue_health` |
| `execution_environment` | `host_reachability` / `disk_space` / `workdir` / `eda_env_vars` from the same recorded event |
| `connectivity_gates` | `connectivity_check.load_state()` + a **fresh** `connectivity_check.evaluate_staleness()` against the RTL on disk now |
| `regression_quality` | `trend_analysis.trend_report()`'s three detectors (regressions / fix-revert oscillation / runtime anomalies) |
| `harness_self_reporting` | this harness's own `*_FAILED` best-effort side-channel events in `.dv-harness/events.jsonl` |
| `slo_compliance` | the error budgets computed in the same report |

States: `HEALTHY / DEGRADED / CRITICAL / UNKNOWN`, rolled up by `HEALTH_SEVERITY` where **UNKNOWN outranks HEALTHY** — one unmeasured subsystem stops the platform reading healthy. A SKIPped preflight check is UNKNOWN (never a pass, and never an alert either — the shipped config deliberately leaves `preflight.workdir` empty); `PENDING`/`NOT_AVAILABLE` gates stay UNKNOWN, never collapsed into PASS or FAIL; a stale-but-passing gate run is DEGRADED because `evaluate_staleness()` already says those verdicts may not be cited.

### Two SLOs — and a structural refusal for everything else

- `regression_verdict_pass_rate` — good = a real `regression_verdict_history` PASS row; target 95%; source `trend_analysis.daily_rollup()` (evidence DB opened READ-ONLY).
- `execution_preflight_pass_rate` — good = a real `EXECUTION_PREFLIGHT_PASS` event, bad = a real `EXECUTION_PREFLIGHT_BLOCKED`; target 90%.

`UNMEASURABLE_SLIS` names the five SLIs a normal SRE platform would carry — uptime, request latency, service availability, simulator-farm uptime, data durability — **each with the missing producer stated**, and `assert_no_unmeasurable_slo()` raises if one ever appears in `SLO_CATALOG`. That is the "do not fabricate SLOs for telemetry you don't have" instruction turned into an enforced invariant rather than a promise. A window holding fewer than `min_events` real events reports `INSUFFICIENT_EVIDENCE` with `achieved_percent=None`.

Error-budget arithmetic is plain and honest: `error_budget_events = (1 - target) * total`, remaining = budget − bad, statuses `MEETING / AT_RISK / BREACHED / INSUFFICIENT_EVIDENCE`. Nothing is extrapolated, smoothed or projected.

### A real bug the work surfaced: two clocks

`events.jsonl` carries `engine.now()` (explicit UTC); `evidence.duckdb`'s `recorded_at` defaults to DuckDB's `now()`, which is the machine's **local** wall clock. A single UTC-anchored window silently dropped verdicts recorded minutes earlier (caught by a failing test, not by inspection). Each SLI is now windowed in the clock its own source uses (`CLOCK_UTC_EVENT` / `CLOCK_LOCAL_STORE`), every budget carries `window_clock`, and the clock is deliberately **not** config-overridable.

### Surfaces

- `dv-harness platform-health [--json] [--window-days N]` (cli.py parser + handler)
- `python -m dv_harness.platform_health --root … [--json]`
- One shared `execute()` behind both. Exit 2 only on DEGRADED/CRITICAL; UNKNOWN exits 0 but is never rendered as a pass (the text output says so in as many words).
- `config.py` gains a `platform_health` block that may retune `target_percent`/`window_days`/`min_events`, and may **not** add an SLO id or change a clock.

## 3. No parallel mechanism, per the Methodology Consolidation Rule

- Regression counts come from `trend_analysis.daily_rollup()` — this module never queries the evidence DB itself, so the SLO and the trend report cannot disagree. A test asserts the counts equal `daily_rollup()`'s own sums.
- Connectivity staleness is `connectivity_check.evaluate_staleness()`, not a re-implementation.
- **No third events.jsonl parser.** `loop_telemetry._read_events` gained a public `read_events` alias (8 lines) which `platform_health` reuses; a test asserts function **identity** and that the module contains no `/ "events.jsonl"` path-join and no `json.loads`.
- Preflight check names are read from `preflight.py`'s own `name = "…"` literals; a test asserts every name this module references really exists there.

## 4. Approval gates: untouched, and asserted so

No approval machinery is imported or referenced. `assert_authorizes_nothing()` checks this module's own source for `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`, `ControlPlane`, `can_signoff`, `assert_human_approval`, `approve(` — with `control_plane.py` as the negative control that really trips it. A BREACHED budget is a report; it blocks no stage and lets none through. The report performs **no writes at all** (a test snapshots every file under the project root and asserts two full reports change none of them), opens the evidence DB READ-ONLY, and started no build/regression/LSF submission anywhere in this work — every test drives synthetic/local fixtures, and the only farm-facing code path goes through `preflight.py`'s injected-Runner seam with canned real captured output (`conftest.py` also pins the DEGRADED probe transport to `off` suite-wide).

## 5. Test evidence — why these are not "returns a value" tests

37 tests, every input from the real producer:

- **Preflight events** come out of real `DVHarness.run_stage()` passes over the real shipped `main_graph.json`, through `engine._execution_preflight_gate()`. Positive/negative control pair: a healthy farm run makes `eda_license` HEALTHY, a starved-license run through the *same* code path makes it CRITICAL while `lsf_queue` stays HEALTHY (no smearing), and two sequential runs prove the *latest* recorded run wins.
- **Error budget**: 5 real PASS gate runs + 1 real BLOCKED = 83.33% vs 90% → BREACHED with `budget_remaining_events < 0`; retuning the project target to 75% flips the same real evidence to MEETING; 2 runs → INSUFFICIENT_EVIDENCE with `achieved_percent is None`.
- **Regression verdicts** come out of the real `regression_reporter._write_reconciliation_evidence_if_configured()` path into a real DuckDB. Back-dating the whole set 60 days really drops the SLO to INSUFFICIENT_EVIDENCE, and asking as-of the back-dated day finds it again — proving the window moved rather than the evidence vanishing.
- **Connectivity gates**: a real `run_connectivity_check()` with **all three gates genuinely PASSing** (real trace file, real monitor counts; only Gate 1's `which`/`subprocess` seam injected) → HEALTHY; editing the RTL → DEGRADED `STALE_RTL_CHANGED`; a silent monitor → CRITICAL; no elaborator on PATH → UNKNOWN, never conflated.
- **Degradation**: a real `force_trigger(TRIGGER_LICENSE)` outranks an older passing preflight run, and `clear_trigger()` really returns the subsystem to that evidence — so it is a live read, not a latch.
- **Guards**: adding a `harness_uptime` SLO to the catalog really trips both `assert_no_unmeasurable_slo()` and `assert_slo_catalog_has_producers()`.
- **CLI**: both entry points driven as real subprocesses; a real breach really flips the process exit code to 2.

Run on this repo itself, the tool honestly reports `OVERALL: UNKNOWN` with six subsystems unmeasured and both SLOs `INSUFFICIENT_EVIDENCE` — which is the correct answer for a repo that has never run a preflight gate or a regression here.

## 6. Deliberately NOT built (scoped down, stated rather than implied)

- **No dashboard card / `GET /api/platform-health` endpoint.** `dashboard.py` (3.5k lines) was being actively modified by other close-passes in this same loop; adding a card there was a collision risk out of proportion to its value, and the CLI + module entry points are a real, complete surface. This is the one honest deferral. Adding the endpoint later is a small, self-contained delegation to `platform_health.platform_health_report()` — no new logic.
- **No alerting/notification wiring.** `escalation_notify.py` exists and is opt-in; hooking budgets into it would be a policy decision (which breach is worth waking someone for) that nobody has made, and inventing a threshold would be the fabrication this module is built to avoid.
- **No engine gate.** Deliberately: a gate passing on a platform nobody measured would be worse than none, and any gate here would sit next to the human-approval gates I was told not to weaken.
