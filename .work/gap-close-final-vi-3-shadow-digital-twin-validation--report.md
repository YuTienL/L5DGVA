# VI-3 — Shadow / Digital-Twin Validation — gap-close report

**Verdict: DONE (scoped-down as designed, with an explicit disclosed residual).**

**Test summary:** 48 pass in the two directly-affected suites
(`test_capability_evolution_shadow_validation.py` 24 new + `..._controlled_experiment.py` 24);
448 pass across every capability-evolution consumer suite touched
(`..._research_architect`, `..._auto_discovery`, `test_dashboard_research_card`,
`test_loop_contract`, `test_loop_convergence`, `test_loop_telemetry`,
`test_cross_project_mining`, `test_research_*`, `test_confidence_vocabulary_separation`,
`test_stats_snapshot`). Nothing runs a build, a regression or an LSF submission.

**Commit:** `659b07b` — *"shadow validation: one successful shadow run is not sufficient
proof (VI-3)"* on `gap-close/env-manifest-fact-sources`. 8 files, +1401/-105.

---

## 1. Independent re-verification of the gap (before building)

`grep -rniE "shadow|digital[ _-]?twin" --include=*.py` over
`D:/DV/Task/DV_Agent_Harness_L5/v50/` returned **only unrelated hits**: Python variable
shadowing (`connectivity.py:3271`, `dashboard.py:3072`, `engine.py:4337`,
`loop_budget.py:212`, `syoscb_result_taxonomy.py:496`), a coverpoint's `cp_*` shadow class
member (`uvm_generator/generator.py`), and W1C shadow *registers* in `.work/` notes and a
test's Verilog fixture. Zero occurrences of `digital_twin` / `digital twin` anywhere.
So the audit was right that the NAME was absent.

The specification is `CLAUDE_DV_Agent_Harness_L5_ULTIMATE_COMPLETE_VERIFICATION_INTELLIGENCE.md`
(in the PARENT directory, not `v50/`) **§133 SHADOW / DIGITAL-TWIN VALIDATION MODE** (lines
4439-4476) and **§134 SHADOW PROMOTION FLOW** (lines 4478-4496), both read in full.

**The audit was only half right, and that materially changed the scope.** §133's canonical
diagram is: same input evidence → two arms (Current L5 Production / Candidate L5 Shadow) →
compare decisions/results → candidate output must not alter production unless promoted.
That is *exactly* what `capability_evolution.run_controlled_experiment()` already does (built
2026-09-05, documented in CLAUDE.md's "Controlled Experiments Are Executed, Not Attested"):
two copies of an isolated fixture, `baseline` untouched standing for production, `treatment`
carrying the candidate's bounded change, both driven through the REAL
`DVHarness.run_stage()`, measured through the REAL `control_plane.describe_stage()`, four
enforced isolation properties, and a hard stop at BENCHMARKED. **§133 was already closed under
another name.** Building a second "shadow runner" beside it would have been precisely the
parallel mechanism CLAUDE.md's Methodology Consolidation Rule forbids.

What was genuinely NEVER_BUILT is **§134's promotion flow around it**, and its own closing
lines *"Provide rollback"* and *"A single successful shadow run is not sufficient proof."*
Confirmed by reading the code, not inferred:

- `assert_benchmark_measured()` accepted **exactly one** experiment record; nothing anywhere
  enumerated runs, and `grep -niE "stability|rollback|min_runs"` over
  `capability_evolution.py` found only `rollback_plan` (a prose schema field).
- `LEGAL_TRANSITIONS["BENCHMARKED"] = ("PROMOTION_CANDIDATE", "REJECTED")` and `transition()`
  attached an evidence requirement to `-> HUMAN_APPROVED` and `-> BENCHMARKED` **only**. So a
  single IMPROVED run carried a candidate to PROMOTION_CANDIDATE with no further evidence.
- `compare_experiment_arms()` returns a **NET** verdict over arm totals. A treatment arm that
  satisfies two more gates on one stage and one fewer on another totals `+1` and reads
  IMPROVED — the broken gate appears nowhere. §134 puts a "Regression Safety" node in front of
  the stability window for exactly this, and nothing computed it.

## 2. What I built (all in `dv_harness/capability_evolution.py`, extending, not duplicating)

| Addition | What it is |
|---|---|
| `run_shadow_replication()` | §134's "Shadow Runs", plural. Re-measures an already-BENCHMARKED candidate over the same fixture/arms/stages. **Makes no governance transition** — §70's state table gains no edge — and asserts that on the way out, mirroring `run_controlled_experiment()`'s terminal-state assertion. |
| `_prepare_shadow_run()` / `_execute_shadow_run()` | Extracted verbatim from `run_controlled_experiment()` so both paths share ONE set of isolation checks, ONE stage runner, ONE record shape. This is the reuse: no second experiment engine exists. |
| `regression_safety()` | §134's "Regression Safety" node: the per-stage view a net verdict cannot give. Pure function over two measured arms, so `stability_window_status()` **recomputes** it from each record's own `before`/`after` rather than reading a stored field — it holds for records written before it existed and cannot be forged by editing one. A stage the treatment stopped measuring is unsafe too (the one way a regression hides from an intersection-only walk). |
| `shadow_run_history()` / `stability_window_status()` / `assert_stability_window()` | §134's "Stability Window", as a NEW PRECONDITION on `BENCHMARKED -> PROMOTION_CANDIDATE` inside `transition()`. `STABILITY_WINDOW_MIN_RUNS = 2` (same bar as `REPEAT_FAILURE_MIN_OCCURRENCES` / `ORGANIZATIONAL_MIN_CONFIRMATIONS`), same stage set, agreeing on IMPROVED or UNCHANGED, none regressed, non-empty `rollback_plan`. Reports **every** blocker at once. |
| `shadow_rollback_manifest()` | §134's "Provide rollback" as data, derived from the experiment's own untouched **baseline arm**: per changed path, `delete` or `restore_content` plus a baseline digest. Reads only; restores nothing. |
| `StabilityWindowNotEstablishedError` | Distinct from `HumanApprovalRequiredError` on purpose — this is missing EVIDENCE, and clearing it never substitutes for the human decision. |
| schema: `shadow_runs` + `$defs/shadow_run` + `status_transition.stability_window` | `additionalProperties: false`, so these are real contract additions, shaped exactly like the existing `benchmark_result` def (const `produced_by`, `record_path` + `record_digest`). Not in `required`, so an older candidate still validates. |

**Anti-forgery — the property that makes the window mean anything.** A run counts because the
**candidate pins it by digest** (`benchmark_result` for the first, `shadow_runs` for each
replication), never because a file appeared in the experiments directory. Every check re-reads
disk: the record must exist, still hash to the pinned digest, name this candidate and this run,
sit under this project's own `experiments_dir(root)`, and be its own directory's record. The
pin's own copy of the outcome is never trusted — the record decides. And because a digest proves
a record was not *edited* rather than that anything ever *ran*, **both arm workspaces must still
be on disk carrying real harness state**. `build_candidate()` refuses a caller-supplied
`shadow_runs`, mirroring its `benchmark_result` guard.

## 3. Human-approval gates: unchanged, and tightened only in the safe direction

Adding a precondition in front of an edge that previously had **none** can only tighten it.
Untouched and uncalled-with-weakening: `assert_human_approval()`'s real `ControlPlane` check,
`HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`,
`assert_no_production_write_authorized()`, `ControlPlane.approve()`, `policy.can_signoff()`,
the PR-only main/master governance. `PROMOTION_CANDIDATE` remains a state a *human* puts a
candidate into; the window only refuses to let one good run stand in for the evidence.
`acceptance_criteria_machine_evaluated: false` is carried on the window evidence too — whether
a measurement MEETS the free-text criteria is still not judged in code.
`test_an_established_window_authorizes_nothing` holds this end to end, including that a real
`ControlPlane.approve()` still unblocks the last edge exactly as before.

The `PROPOSED -> PROMOTION_CANDIDATE` edge (for `experiment_required: false` candidates, which
ran no experiment and have no window to establish) is deliberately **not** gated — held by
`test_the_window_is_not_required_of_a_candidate_that_ran_no_experiment`.

## 4. Tests

`dv_harness_tests/test_capability_evolution_shadow_validation.py` — 24 tests, all driving the
REAL two-arm fixture (`controlled_experiment_fixture.py`, reused not duplicated; the only stub
anywhere is the agent adapter, because the real one dispatches a `claude -p` subprocess).
Negative controls carry the detection power:

- one real IMPROVED run is refused at the edge; the **same** candidate measured a second time
  for real passes it (positive control for the first);
- a genuinely-improving real run is NOT reported as a regression;
- a `+2/-1` trade whose stored `outcome` still says IMPROVED is caught by the per-stage view;
- a hand-written `experiment.json` in the experiments directory counts for nothing;
- a deleted record, a deleted arm workspace, an edited stage list, disagreeing outcomes and a
  DEGRADED pair each stop the window — each for its own named reason;
- a replication moves no governance state (`status_history` asserted byte-identical);
- a replication refuses to prop up a tampered benchmark;
- the source fixture is re-fingerprinted across a real replication (isolation still holds).

Three pre-existing tests that promoted on one run were updated to measure a **second real run**
rather than relax the new requirement:
`test_capability_evolution_controlled_experiment.py` (2 sites),
`test_capability_evolution_research_architect.py` (1), and
`test_dashboard_research_card.py::_walk_to` (which now runs a real replication before
PROMOTION_CANDIDATE). `controlled_experiment_fixture.py` gained `run_demo_replication()` /
`benchmarked_with_stability_window()`.

One incidental robustness fix: the default `run_id` now folds in a microsecond-resolution
timestamp, because a replication runs the SAME candidate over the SAME fixture and stages and
an inputs-only digest made two runs in one second collide on the workspace-exists check.

## 5. What I did NOT build, and why (the honest BLOCKED remainder)

1. **§133's full compare list** — accuracy, failure detection, coverage gain, false positives,
   false negatives, resource cost, human-review burden. What is compared is what this harness
   can measure **without ground truth it does not have**: gate satisfaction, stage completion,
   per-stage regression, and a gate-outcome digest. Scoring a candidate's false-positive rate
   needs a labeled corpus of known-correct verdicts that does not exist in this repo;
   manufacturing one would be exactly the fabrication this module exists to prevent. **Runtime
   / resource cost were also deliberately left out** rather than added cheaply: the candidate
   schema's `benchmark_arm` is `additionalProperties: false`, a wall-clock number is
   nondeterministic across runs, and a stability window that compared runtimes would flake —
   so a number nothing gates on was not worth loosening a strict contract for.
2. **§134's `Limited Rollout` and `Revalidation` nodes** — both are acts on *production*, i.e.
   Level C, which stays human-governed. Not built, by design.
3. **Applying a rollback** — the manifest is produced; applying it is a production write behind
   the same human gate as every other.
4. **An actual parallel/shadow simulation environment** — genuinely out of reach here and not
   attempted. There is no RTL tree, no VCS licence, no LSF farm and no second DUT in this repo
   (the same disclosure CLAUDE.md already makes for connectivity gates and cross-project
   mining). The scoped-down slice this closes is the real, bounded one the task described: a
   comparison/diff mechanism between two independently-produced evidence sets for the same DUT
   state, reusing `engine.py`'s stage runner and the existing experiment record store.
5. **Wiring** — like `run_controlled_experiment()` before it, this is **REACHED, not WIRED**:
   no CLI verb, no engine call site, no graph node. Callers are the `research-architect` path
   and these tests. The mutation is still authored by whoever runs the experiment rather than
   derived from the candidate's own `proposed_action`.

## 6. Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\capability_evolution.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\schemas\capability_evolution_candidate.schema.json`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_capability_evolution_shadow_validation.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\controlled_experiment_fixture.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_capability_evolution_controlled_experiment.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_capability_evolution_research_architect.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_dashboard_research_card.py`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md` (new section: "Shadow / Digital-Twin
  Validation: One Good Run Is Not Proof (2026-09-05, VI-3)")

`dv_harness/golden_flow_readiness.py` was not touched.
