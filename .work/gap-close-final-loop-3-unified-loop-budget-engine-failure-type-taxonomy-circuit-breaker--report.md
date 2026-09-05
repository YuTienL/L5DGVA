# LOOP-3 gap close: unified loop budget engine + failure-type taxonomy + circuit breaker

**Status: DONE** (with two deliberate, disclosed opt-in defaults -- see "What is
opt-in and why").

**Test summary:** full suite `pytest dv_harness_tests` on the final tree --
**5514 passed, 5 failed, 6 errors in 1:15:43**; all 11 non-passes are the
pre-existing `pueued`-daemon environment failures (`test_cli_pueue.py` x5,
`test_pueue_client.py::TestRealPueueIntegration` x6, all "real pueued did not
come up"), the same set two other close-passes recorded this session and
untouched by this change. New file `test_loop_budget.py`: **61 passed**.

Scope: LOOP_ENGINEERING sections **91** (loop budget engine), **92** (EDA
resource / license-aware control -- the missing PRIORITIZATION half) and **93**
(retry/backoff + circuit breaker).

---

## 1. Independent re-verification of the gap (before building)

Re-run on 2026-09-05, in this checkout, not taken from the audit:

| Check | Command | Result |
|---|---|---|
| circuit breaker | `grep -rn "circuit_breaker\|CircuitBreaker\|CIRCUIT_BREAKER" --include=*.py dv_harness/` | **0 hits** |
| failure taxonomy | `grep -rn "TRANSIENT" --include=*.py .` | **1 hit**, `dv_harness/connectivity.py:3287` -- an unrelated Gate-3 docstring sentence |
| unified budget | no `loop_budget`/`budget_engine`/`BudgetLedger` module anywhere | absent |
| scattered budgets that DO exist | `config.py:17` `policy.max_stage_retries`, `config.py:38` `inner_react_max_iterations`, `config.py:39` `inner_react_max_adapter_calls`, `context_budget.MAX_PACK_BYTES`, `engine.py:4658` `ss["attempts"] <= max_retry` | real, and each isolated |
| section 92's check half | `preflight.check_license()` / `check_queue_health()`, `lsf_client.bsub_submit_with_preflight()`, `engine._execution_preflight_gate()` | **real** -- only the prioritization/deferral half was missing |
| `BUDGET_EXHAUSTED` | `loop_contract.py` (LOOP-1, landed earlier this session) | **exists** -- so this gap reuses it, never re-coins it |

Gap CONFIRMED real. Closest existing mechanisms found and EXTENDED rather than
duplicated: `loop_contract.LoopState`, `sim_log_analysis`'s triage vocabulary
and signature normalization, `preflight`'s check outcomes, `degradation`'s
probe-arming discipline, `tools/senior_dv/failure_attribution.py`'s
boundary-trace rule.

---

## 2. What was built

### New: `dv_harness/loop_budget.py` (one module, because it is one mechanism)

The breaker trips on the budget engine's exhaustion and decides retry-vs-stop
from the taxonomy, which section 92's pressure signal also feeds. Splitting them
would put the trip condition in one file and the thing it trips in another.

**Section 93 -- the taxonomy.** `FailureType` with all ten of section 93's
classes; `RETRYABLE_FAILURE_TYPES` (total, asserted); `classify_failure()` with
a documented precedence: a real `preflight` FAIL (a measurement) > a real
boundary-trace attribution (gate-enforced DUT-vs-TB) > a VIP-side reporter >
text rules over real toolchain strings (VCS `Error-[SE]`, FlexLM, `TERM_RUNLIMIT`,
tcsh `Undefined variable.`, `gates.py`'s own `MISSING_EVIDENCE`/`GATE_FAIL`) >
`sim_log_analysis`'s own triage category > `UNKNOWN` with `rule=no_rule_matched`.
`UNKNOWN` is retryable ON PURPOSE, so an unclassified failure behaves exactly as
it does today.

**Section 91 -- the unified ledger.** All eleven dimensions, persisted atomically
to `.dv-harness/loop_budget.json`. Every limit is `None` by default AND carries
a real reason (the honest state: this harness enforces no run-scoped loop budget
today); a project declares one through `loop_budget.limits.*`.
`reset()` / `reset_breaker()` REQUIRE a real `reason` AND a real `by`, refuse
without them, append an append-only record of the spend cleared, and leave the
`exhaustion_log` intact -- section 91's "cannot silently reset" as enforced code.

**Section 93 -- the circuit breaker.** Eight triggers, `trip_breaker()` /
`reset_breaker()` / `blocking_reason()`. Re-tripping never restamps `opened_at`.

**Section 92 -- prioritization.** `pressure_from_checks()` derives
NONE / ELEVATED / CRITICAL / UNKNOWN from real `preflight.CheckOutcome`s, and
`prioritize_stage()` returns PROCEED / PROCEED_CRITICAL / DEFER. The ELEVATED
band is the range `degradation.py` deliberately says nothing about (it only
trips at full starvation), which is exactly where deferral helps.

**Front door.** `dv-harness loop-budget dimensions|status|classify|reset|breaker-reset`
and the identical `python -m dv_harness.loop_budget`, one shared `execute_verb()`.

### Engine wiring (`dv_harness/engine.py`)

| Method | Call site | Fires on a default config? |
|---|---|---|
| `_classify_stage_failure()` | `loop()`'s FAIL/PARTIAL branch, every attempt | **yes** -- records `failure_type`/`failure_signature`/`failure_signature_repeats` on the stage |
| `_spend_retry_exhaustion_budget()` | `loop()`'s retry-exhaustion branch, one line after `_record_loop_state_observation()` | **yes** -- one real `LOOP_BUDGET_SPENT` event + a real ledger on disk |
| `_retry_refused_by_failure_evidence()` | same branch, before the `attempts <= max_retry` test | only with `enforce_retry_policy` / `repeated_identical_failure_threshold` |
| `_circuit_breaker_gate()` | top of every `loop()` cycle, **after** takeover/pause, **before** the SIGNOFF gate and `run_stage()` | only once a declared budget/threshold has tripped it |
| `_resource_priority_decision()` | `_execution_preflight_gate()`'s PASS branch | **yes** when that gate is armed -- recorded in the `EXECUTION_PREFLIGHT_PASS` event |
| `_defer_stage_under_resource_pressure()` | same | only with `defer_low_value_under_pressure` |

### Two small shared-file edits, both reuse-preserving

* `sim_log_analysis.py`: public `normalize_failure_signature = _normalize_signature`,
  so "is this the same failure" has ONE answer in this codebase.
* `preflight.py`: public `parse_license_availability()` (a wrapper over the same
  `_parse_lmstat_output()` `check_license()` itself uses) and the license PASS
  path now carries the raw lmstat output as `evidence` (the FAIL paths always
  did). Without it, headroom would have to be scraped out of the check's own
  formatted `detail` string.

### `CLAUDE.md`

One new section, "Unified Loop Budget + Failure Taxonomy + Circuit Breaker
(2026-09-05)", following the file's existing convention (what was verified
missing, what was reused, what is opt-in and why, what is a disclosed residual).

---

## 3. What is opt-in, and why (honest, not a hedge)

Two flags default OFF, and one design decision deserves naming:

1. **`loop_budget.enforce_retry_policy`** (default false). Turning it on
   shortens a stage's real retry budget whenever the classifier lands on a
   non-retryable type. That changes the meaning of every existing project's
   `policy.max_stage_retries` on the strength of a classifier they never asked
   for. Same disclosed-default discipline as `require_tier` and
   `probe_resources` elsewhere in this codebase. The classification is computed
   and recorded either way.
2. **`loop_budget.defer_low_value_under_pressure`** (default false), same
   reasoning; and it can only ever fire where a REAL resource probe is already
   armed, so it can never fabricate scarcity.
3. **`policy.max_stage_retries` is NOT reported as a run-wide `max_retries`
   cap.** The first build did exactly that, and it broke
   `test_loop_contract.py::test_a_second_identical_failure_is_a_real_oscillation_fingerprint`
   -- because that per-node budget resets when `current_stage` moves on, so
   accumulating it run-wide reports every second retry-exhausted stage as an
   exhausted RUN. Its per-node spends are still accumulated so the run-wide
   total is visible; the limit is declared, not inferred. This is recorded here
   because the bug is the reason the design is what it is.

The breaker itself DOES block by default; it simply has nothing to trip on
until a project declares a budget or a threshold, which is section 91's own
NOT_ENFORCED-with-a-reason model rather than a hidden off switch.

---

## 4. Human-approval gates: untouched

`ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()`,
`assert_no_production_write_authorized()`, `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError` and the PR-only main/master governance are
untouched and **uncalled** from `loop_budget.py`. Asserted mechanically:
`test_this_module_touches_no_approval_mechanism` tokenizes the module (docstrings
and comments stripped, since the prose legitimately NAMES the gates it leaves
alone) and fails on any of those identifiers appearing in CODE.
`test_the_breaker_authorizes_nothing_it_only_stops` drives a real breaker trip
and recovery and asserts `can_signoff()` concludes the same thing before and
after. Human Override still outranks the breaker
(`test_human_override_still_outranks_the_breaker`).

**No real build / regression / LSF submission was triggered.** Every engine test
runs against the synthetic `controlled_experiment_fixture` project on
`COMMAND_PATTERN`, an `implementation-route` node with no FAIL edge, chosen for
exactly that reason and reused (not duplicated) from `test_loop_contract.py`.
Every license/queue reading in the tests comes from this project's own REAL
captured `lmstat`/`bqueues` transcripts in `test_preflight.py`, driven through a
scripted runner -- no live server is contacted.

---

## 5. Test evidence

`dv_harness_tests/test_loop_budget.py` -- **61 passed**. Real, not
isolated-function checks:

* **Real engine, real gate, real graph**: a declared `max_iterations` budget
  really exhausts during a real `DVHarness.loop()`, the breaker really trips,
  the NEXT `loop()` spends **zero** attempts and lands BLOCKED with a real
  `CIRCUIT_BREAKER_BLOCKED` event, a recorded recovery really releases it, and a
  real takeover still outranks it.
* **Behaviour change with its negative control**: with `enforce_retry_policy`
  off the real loop spends its full 3-attempt budget; with it on, over the
  IDENTICAL fixture, the same real failure stops after 1 attempt with a real
  `LOOP_RETRY_REFUSED` event.
* **The repeat counter has detection power**: the real fixture failure repeats
  identically across all real attempts (`repeats == attempts`), AND a genuinely
  different failure resets the count to 1 -- otherwise the trigger would fire on
  any stage that simply failed twice for two different reasons.
* **Section 92 with its negative control**: this project's real captured
  99-issued/0-in-use lmstat reads PRESSURE_NONE and defers nothing; the same
  real `check_license()` at 95/99 still PASSes (degradation would not trip) and
  reads ELEVATED; fully checked out reads CRITICAL; a SKIP and an empty check
  list read UNKNOWN and never defer.
* **Oscillation, with its negative control**: with `trip_on_oscillation` on,
  ONE real retry-exhaustion does NOT trip (one fingerprint is below the
  2-INDEPENDENT-observations bar) and a SECOND real round over the same node
  does -- computed by `loop_contract.detect_oscillation_from_debug_loop_history()`
  over entries the engine wrote for its own reasons. With the flag off, the
  same run genuinely oscillates and the breaker stays CLOSED, so the default is
  a decision rather than an absence of evidence.
* **Drift guards**: `assert_retry_policy_total()`,
  `assert_triage_mapping_total()`, `assert_sources_total()`, and a test that
  derives `preflight`'s real `CheckOutcome.name` set from `_ALL_CHECKS` and
  compares it against the mapping -- a renamed check fails loudly.

Regression evidence, in order actually run:

| Run | Result |
|---|---|
| `test_loop_budget.py` (final code, incl. oscillation wiring) | **61 passed** |
| `test_loop_budget.py + test_loop_contract.py + test_preflight.py + test_sim_log_analysis.py` | **168 passed** |
| **full `pytest dv_harness_tests` on the final tree** | **5514 passed, 5 failed, 6 errors** (1:15:43) |

**Every one of the 11 non-passes is the pre-existing `pueued`-daemon
environment failure**, reproduced verbatim: `test_cli_pueue.py` x5 (`assert 1
== 0` -- `dv-harness pueue add` exits 1) and
`test_pueue_client.py::TestRealPueueIntegration` x6 (`AssertionError: real
pueued did not come up`). `pueue` is an external local task-orchestration
binary (`dv_harness/pueue_client.py`), untouched by this change; the identical
11 are recorded in
`.work/gap-close-final-loop-2-convergence-plateau-oscillation-detection--report.md`
and
`.work/gap-close-self-check-gap-4-parallel-multi-agent-document-extr-report.md`
from earlier in this same session. Both files also pass in isolation on this
tree, confirming they are the daemon's availability and not an ordering effect
of this change.

One REAL regression was found and fixed during this pass, not worked around:
the first build reported `policy.max_stage_retries` as a run-wide `max_retries`
cap, which broke
`test_loop_contract.py::test_a_second_identical_failure_is_a_real_oscillation_fingerprint`
(a second retry-exhaustion round was blocked by a breaker that should never
have tripped). See section 3.3.

---

## 6. Deferred (deliberately, and named)

* **Section 94** (next-best-action ranking) and **section 95** (loop utility
  telemetry): the ledger MEASURES the cost dimensions both would need, but
  nothing ranks or reports them. Building a ranking on dimensions nothing yet
  spends would be a scoring function over zeros.
* `max_compute` / `max_license_usage` / `max_token_cost` / `max_lsf_jobs` /
  `max_parallel_jobs` are declared and spendable, but **no producer in this
  harness spends them** -- there is no compute, license-second or token
  accounting anywhere. Declared with the honest reason rather than wired to an
  invented meter.
* **Section 90's RESPONSE half** (`STOP BLIND RETRY -> reassess -> materially
  different strategy`) is still not built. `loop_budget.trip_on_oscillation` IS
  a real, wired trigger (it calls
  `loop_contract.detect_oscillation_from_debug_loop_history()` over the very
  entries `_record_debug_loop_round()` wrote one line earlier -- one definition
  of the fingerprint, not two) and is proven end to end with its negative
  control, but it defaults OFF for that stated reason: tripping by default would
  change routing this harness has not decided to change. That residual is
  already disclosed in CLAUDE.md's own sections 88-90 entry and is not made
  worse here.
* `FailureType.VIP` is reachable only from the declared Synopsys `svt_`
  component prefix. A project on another VIP vendor declares its own
  `loop_budget.vip_component_prefixes`; guessing one would be fabrication.
* The ledger is touched only at `loop()`'s retry-exhaustion branch and
  `_execution_preflight_gate()`'s PASS branch, so a run that never exhausts a
  stage's retries never writes one. Wall-time and per-attempt spends at every
  stage boundary would be a broader wiring change than this gap asked for.
* **`_advance_with_fanout()`'s branch-failure path is deliberately NOT wired.**
  It is the sibling call site of `_record_loop_state_observation()`, so wiring
  it would look natural -- but those branches run concurrently in a real
  `ThreadPoolExecutor`, and the ledger's read-modify-write over one JSON file
  would race. Making it safe needs the same serialization
  `doc_extraction_fanout._INDEX_LOCK` uses, which is a separate change; adding
  an unlocked write there would trade a missing datapoint for a corrupt one.

---

## 7. Files

* NEW `dv_harness/loop_budget.py`
* NEW `dv_harness_tests/test_loop_budget.py`
* MOD `dv_harness/engine.py` (6 new methods + 3 call sites)
* MOD `dv_harness/cli.py` (`loop-budget` verb + dispatch)
* MOD `dv_harness/preflight.py` (public `parse_license_availability()`, PASS-path evidence)
* MOD `dv_harness/sim_log_analysis.py` (public `normalize_failure_signature`)
* MOD `CLAUDE.md` (one new section)

`.dv-harness/events.jsonl` is deliberately NOT part of the commit -- it is
per-project runtime state, and it was already modified before this pass started.
