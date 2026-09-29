# VI-4 — Verification Strategy Optimizer — close-pass report

**Status: DONE**

**Test summary:** `dv_harness_tests/test_verification_strategy.py` — 42 passed in
313s; neighbouring suites (loop_convergence, coverage_analysis,
protocol_capability, trend_analysis, evidence_db, cross_project_mining,
capability_evolution controlled-experiment + shadow-validation) re-run green
alongside it. See "Test evidence" below for the exact command and result.

---

## 1. Independent re-verification of the gap (done first, before any code)

Two greps on 2026-09-06 against `D:/DV/Task/DV_Agent_Harness_L5/v50/`:

| Question | Command | Result |
|---|---|---|
| Does a strategy optimizer already exist? | `grep -rniE "strategy_optimizer\|verification_strategy\|strategy_recommend" --include=*.py --include=*.md .` | **zero hits** — the mechanism was genuinely absent |
| Is there any formal / PSS / emulation backend? | `grep -rniE "formal\|emulation\|zebu\|haps\|\bPSS\b\|jasper\|vc_formal\|questa_formal\|veloce\|palladium\|protium\|trek\|breker\|symbolic" --include=*.py --include=*.json dv_harness/ tools/` | **no backend of any kind.** Every `formal` hit is a Verilog FORMAL PORT (`verible_parser.py`, `amba_fabric_discovery.py`); `router.py:170` lists `'pss'` in `RESEARCH_FOCUS_DOMAINS` (a reading-list topic, not an execution path); `memory_vault.py:471` names `05_Tools/ZeBu` and `05_Tools/HAPS` as vault FOLDER NAMES. `dv_harness/adapters/` contains only `base.py`/`cli.py`/`sdk.py`. |

The audit was correct on both halves: the optimizer was NEVER_BUILT, and this
harness's one real execution engine is simulation —
`lsf_client.bsub_submit_with_preflight()` behind `preflight.run_preflight()`.

## 2. What was built

`dv_harness/verification_strategy.py` (~1135 lines incl. docstrings), plus a
`dv-harness verification-strategy` front door and a CLAUDE.md section.

### Two axes, never merged
Same discipline `protocol_capability.py` applies to "can generate" vs. "has proven":

- **Executability is DERIVED from the import system, never typed in.** Each
  strategy declares the backend entry points it would need (`STRATEGY_BACKENDS`,
  e.g. FORMAL's `dv_harness.formal_client:prove_property`), and
  `derive_executability()` resolves each with real `find_spec` + `import` +
  `getattr` — the same resolution `protocol_capability.resolve_generator_class()`
  does. SIMULATION → `EXECUTABLE_HERE`; FORMAL/PSS/EMULATION/FPGA_PROTOTYPE →
  `RECOMMEND_ONLY_NO_BACKEND`, and those rows carry **no `execution_path` at all**.
- **The verdict is what the signals say**: `RECOMMENDED` / `NOT_INDICATED` /
  `NO_SIGNAL` / `SUPPRESSED`. Every strategy always gets a row; `R9` guarantees no
  row is ever returned with an empty basis (an omitted strategy and a
  no-evidence strategy must not read the same).

### Three enforced invariants (not docstring promises)
- `assert_executability_matches_code()` — SIMULATION is the only strategy with a
  real backend **in this repo**. If someone later builds a real formal client,
  this FAILS, forcing module docstring + CLAUDE.md + tests to be updated
  together with the new capability rather than drifting.
- `assert_no_unexecutable_strategy_claimed_executable()` — called on the way out
  of **every** report. Re-derives executability from the import system rather
  than trusting the record, and additionally requires that any RECOMMENDED
  strategy this harness cannot execute names a real `executable_next_action`.
  "Use formal" with no act this harness can perform reads as a capability and
  is not one.
- `assert_named_escalators_resolve()` — every named escalation path must really
  exist. Because this module *names* them and takes none, nothing else would
  catch one being renamed away.
- (plus `assert_no_verification_verdict_vocabulary()` — no strategy token may
  collide with `models.Status`, mirroring
  `capability_evolution.assert_no_verification_verdict_vocabulary()`.)

### Signals — all imported, nothing re-measured
| Signal | Source (imported, not reimplemented) |
|---|---|
| coverage-closure difficulty | `loop_convergence.classify_loop_convergence()` → `investigate_plateau()` → `coverage_analysis.classify_coverage_hole()` over `trend_analysis.daily_rollup()`'s real series |
| failure density | `capability_evolution.repeated_unresolved_failure_patterns()` + the `failure_signatures` table read READ-ONLY from `evidence_db`; identity is `evidence_db.signature_key()` in both |
| protocol reach | `protocol_capability.capability_for()` / `derive_status()` / `does_not_model` |
| multi-subsystem scope | `environment_mode_router.read_registered_subsystem_entries()` (the registry `engine.py` writes on a real SIGNOFF PASS) |
| throughput | `trend_analysis.daily_rollup()`'s `total_runtime_hours` from real `jobs.runtime_seconds` |

### Rules (R1–R9), precedence lifted from `investigate_plateau()`
- **R1** under-sampled bins → SIMULATION (add seeds) **and FORMAL is `SUPPRESSED`**,
  not merely unrecommended. A bin randomization has not fairly attempted cannot
  support a structural unreachability claim; recommending an engine this harness
  cannot even run on the strength of bins nobody has run yet is the most
  expensive possible wrong answer.
- **R2** stimulus-gap bins → SIMULATION (generate testcase / adjust constraint).
- **R3** adequately-sampled UNREACHABLE_STIMULUS bins → **FORMAL**, with
  `coverage_analysis.escalate_unreachable_holes()` (Tier-3, designer-owned) as
  the one act this harness CAN take.
- **R4** unresolved recurring failure / fix-revert oscillation → FORMAL, with
  `capability_evolution.file_repeated_failure_candidate()` as the actionable act.
- **R5** measured runtime/day ≥ threshold while coverage is not converging →
  EMULATION + FPGA_PROTOTYPE, with a Tier-3 tool-budget question named.
- **R6** declared SYSTEM scope over ≥2 REGISTERED subsystems → PSS.
- **R7** protocol modelling ceiling (`GENERIC_SKELETON_ONLY` → build the model
  first; partial model's `does_not_model` layers surfaced as a **caveat**, not a
  verdict, because whether this goal touches them is not machine-evaluated).
- **R8** honest default: with no signal, simulation stays the engine, **labelled a
  default rather than a measurement**.
- **R9** any strategy no rule reached says so and names what was unavailable.

### Front door
`dv-harness verification-strategy capabilities|recommend`
(`--goal --scope --protocol --holes --json`), sharing one `execute_verb()` with
`python -m dv_harness.verification_strategy` (no second handler).
`recommend` **exits 2 when it names a strategy this harness cannot execute** — a
CI-visible "a human must decide something", never an approval in either
direction. Exits 1 on a bad invocation (reported as data), 0 otherwise.

## 3. Honesty guarantees, specifically as required by the task

- The report **never** presents formal/PSS/emulation/prototyping as executable:
  the executability column is derived at report time, those rows name no
  execution path, and `REPORT_DISCLOSURE` is printed on **every** render.
- Every RECOMMENDED non-executable strategy carries a real act this harness can
  perform — enforced, not merely intended.
- `goal_text` is recorded verbatim with `goal_text_machine_evaluated: false`;
  scope is a caller fact and is never inferred from prose (proved by a test
  whose goal literally contains the word "formal" and whose FORMAL row stays
  unrecommended, and by another whose goal says "SoC multi-subsystem" while PSS
  stays `NO_SIGNAL`).
- The module is a **pure read**: no question filed, no candidate minted, no
  memory record written, no evidence database created or migrated. Proved by a
  byte-level snapshot of the whole project root across a recommendation that
  really did recommend FORMAL.

## 4. Approval gates and production safety

Nothing was weakened and nothing was touched: `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError`, `ControlPlane.approve()`,
`policy.can_signoff()` and the PR-only main/master governance are all unchanged
— this module imports none of them and grants no authority. No build, no
regression and no LSF submission is triggered by any code path in the module or
in its tests; every fixture is synthetic and local.

`dv_harness/golden_flow_readiness.py` was **not touched** (separate concurrent
close-pass).

## 5. Test evidence

```
python -m pytest dv_harness_tests/test_verification_strategy.py -q -p no:randomly
=> 42 passed in 313.62s
```

The negative controls are where the detection power lives:
- under-sampled bins **SUPPRESS** formal; the *same bin* after 20+ real distinct
  seeds flips the answer to FORMAL (the two tests differ only in seed count);
- three retries against one commit are one run, not a repeated pattern;
- a failure closed by a gate-verified `verified_fix` recommends nothing;
- one busy day is `NO_SIGNAL` about the sample, never `NOT_INDICATED` about the
  project; several modest days are measured and found *not* throughput-bound;
- a climbing coverage curve is told to change nothing;
- a forged `EXECUTABLE_HERE` row is refused, a RECOMMENDED row with no
  actionable act is refused, a renamed escalator fails the check;
- a **synthesised real module** at FORMAL's declared backend name flips the row
  to EXECUTABLE_HERE with no source edit — the proof that executability is
  derived, not declared — and then correctly fails
  `assert_executability_matches_code()`;
- a missing evidence database reports unavailable, never "0 failures", and is
  not created by gathering signals.

Neighbouring suites re-run together with it: `test_loop_convergence.py`,
`test_coverage_analysis.py`, `test_protocol_capability.py`,
`test_trend_analysis.py`, `test_evidence_db.py`, `test_cross_project_mining.py`,
`test_capability_evolution_controlled_experiment.py`,
`test_capability_evolution_shadow_validation.py`.

## 6. Built vs. deferred — the honest boundary

**Built:** the two-axis recommendation over four real signal families, the
derived-executability mechanism with its three enforced invariants, nine rules
with the plateau precedence, the CLI front door, 42 tests, and the CLAUDE.md
section.

**Deferred / not built, and why:**
1. **Dispatch to formal / PSS / emulation / prototyping — permanently out of
   scope here.** No such backend exists in this repository; building a fake one
   is exactly the overstatement this module exists to prevent. The module says
   so on every render.
2. **The throughput threshold is a heuristic, not a measurement.**
   `DEFAULT_THROUGHPUT_BOUND_RUNTIME_HOURS_PER_DAY = 24.0` is
   project-overridable with a stated justification: this harness reads no farm
   capacity, no license-pool size and no schedule, so no universal number exists
   and inventing one would be fabricated precision.
3. **REACHED, not WIRED.** There is a CLI verb but no `run_stage()`/`advance()`
   call site, no graph node and no dashboard card — the same disclosed state
   `cross_project_mining.py` and `run_controlled_experiment()` are in. Auto-firing
   it on a stage boundary would emit a NO_SIGNAL report in every installation
   that has not yet declared a scope or supplied holes.
4. **No expected-gain / cost scoring per strategy.** That needs ground truth
   (labelled outcomes per engine) this repo does not have, exactly as VI-3
   disclosed for false-positive rates.

## 7. Files

- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/verification_strategy.py` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_verification_strategy.py` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/cli.py` (two hand-scoped hunks: the
  `verification-strategy` parser and its dispatch branch)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md` (one appended section, VI-4)
