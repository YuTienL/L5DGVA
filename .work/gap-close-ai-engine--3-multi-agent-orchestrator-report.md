# Gap close — AI mechanism #3: Multi-Agent Orchestrator

**Status: DONE**

**Test summary:** 7 new tests in `dv_harness_tests/test_rca_multi_agent_fanout.py` all pass, in a
471-test regression sweep across every Stage-enum-sensitive suite that also caught and fixed 2 real
regressions this change caused — see "Verification" below.

---

## What the audit found, and what I re-verified myself first

Verdict was PARTIALLY_WIRED with a concrete, in-scope wiring gap. I re-checked the load-bearing
evidence before touching anything:

- `.dv-harness/agents/tasks.json` really did contain exactly **one** task
  (`TASK-C098CBE2`, `parallel_group=ANALYSIS_G1`, `status=NOT_STARTED`, old format with no
  `started_at`/`completed_at`/`duration_sec`) — confirmed by reading the file.
- The only `parallel_group` in the real graph really was `ANALYSIS_G1`
  (`REQUIREMENTS_TRACEABILITY` / `SOC_SCENARIO_PLANNER` / `INFRASTRUCTURE_AUDIT` → `ANALYSIS_JOIN`),
  i.e. a requirements/scenario/infra planning fan-out, **not** the DUT/PHY/Register/VIP RCA
  mechanism CLAUDE.md's rule names.
- `.claude/workflows/rca-multi-agent-fusion.js` really is a Workflow-tool script with **zero**
  callers from `dv_harness/engine.py` — it only runs when a coordinating session names it.
- All four agent profiles it needs really exist: `.claude/agents/rtl-evidence-agent.md`,
  `log-evidence-agent.md`, `vip-spec-evidence-agent.md`, `analysis_debug.md`.
- `engine.py`'s own comment at the `multi_agent_consensus_count` derivation really did say
  *"this harness runs ONE agent per stage attempt — no concurrent multi-agent branch exists for
  RE_AUDIT"*.

So the practical behavior was: real fan-out machinery existed at two levels, and CLAUDE.md's
"Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent
synthesis" was still enacted only by a human/session remembering to do it.

I took the audit's **option (a)** — a real graph fan-out through the already-proven
`_advance_with_fanout()` / `AgentTaskStore` path. Option (b) (having `engine.py` shell out to the
Workflow script) is not actually available: a Workflow script is driven by the Workflow tool inside
a Claude Code session, and the Python engine has no bridge to invoke one. Option (a) also gets the
audit's requirement 3 (`AgentTaskStore` bookkeeping) for free rather than needing a new
`agent-task create/start/complete` CLI, which is why I did not build that CLI.

**Reuse over reinvention** was the governing constraint throughout: the new graph nodes dispatch the
*same* three specialist agent profiles the Workflow script already fans out to, the join stage is
gated by the *same* already-real `root_cause_evidence_gate` RE_AUDIT uses, and it persists to the
*same* `rca_evidence_fusion` Blackboard topic the Workflow script writes — one record, two real
paths, no third parallel mechanism.

---

## What changed

### 1. `.dv-harness/graph/main_graph.json` — the RCA_G1 fan-out (37 → 41 nodes)

Four new nodes:

| node | `parallel_group` / `join_group` | agent | blackboard_write |
|---|---|---|---|
| `RCA_RTL_EVIDENCE` | `RCA_G1` | `rtl-evidence-agent` | `rca_rtl_evidence` |
| `RCA_LOG_EVIDENCE` | `RCA_G1` | `log-evidence-agent` | `rca_log_evidence` |
| `RCA_VIP_SPEC_EVIDENCE` | `RCA_G1` | `vip-spec-evidence-agent` | `rca_vip_spec_evidence` |
| `RCA_JOIN` | join_group `RCA_G1` | `analysis_debug` | `rca_evidence_fusion` |

Edges: `FAILURE_RECOVERY --PASS--> {CHANGE_IMPACT (priority 10), RCA_*_EVIDENCE (priority 100)}`;
each branch `--PASS--> RCA_JOIN`; `RCA_JOIN --PASS--> CHANGE_IMPACT`, `--BLOCKED--> WAIT_USER`.

The explicit priorities are load-bearing: `next_frontier()` returns all four targets (which is what
makes the fan-out visible), while `next_for()`/`graph_next()` still deterministically return
`CHANGE_IMPACT`, so every non-fan-out consumer of FAILURE_RECOVERY's PASS edge is unchanged.

The branches deliberately have **no FAIL edge**, matching the existing ANALYSIS_G1 branches: a
failed evidence branch parks for retry/replan rather than auto-routing.

### 2. `dv_harness/models.py`

- Four new `Stage` enum members (`RCA_RTL_EVIDENCE`, `RCA_LOG_EVIDENCE`, `RCA_VIP_SPEC_EVIDENCE`,
  `RCA_JOIN`) — real executable stages, so `ensure_stages()` gives each a real `StageState` and
  `run_stage()` can actually execute them.
- `HarnessState.rca_evidence_fanout_armed: Optional[str]` — the arming token. Not a bare `True`:
  it carries the real triage `evidence_hash`, so the state file records *which* triage decision
  authorized a fan-out.

### 3. `dv_harness/engine.py`

- **`_arm_rca_evidence_fanout(stage, evidence_blocks)`** — new, called from the existing
  `verdict == "PASS"` side-effect block alongside `_promote_verified_fix_knowledge()` et al. Arms
  only on FAILURE_RECOVERY with `issue_triage_classification_gate.classification == "REAL_ISSUE"`,
  and actively **clears** stale arming on any other classification.
  Why REAL_ISSUE is the honest trigger and not a weaker proxy: `issue_triage_classification_gate.py`
  already FAILs (`REAL_ISSUE_WITHOUT_DEEP_RCA`) any REAL_ISSUE that did not also set
  `deep_rca_triggered`, so a REAL_ISSUE block that reaches here is structurally a failure the harness
  has already ruled needs deep RCA — and the three RCA_G1 branches *are* the RTL / log / VIP+spec
  evidence domains CLAUDE.md's rule names. The agent's own claim is never trusted alone: this only
  runs after the gate subprocess itself accepted the block.
- **`_resolve_conditional_fanout_frontier(source_node, frontier)`** — new. Narrows a mixed frontier
  to the branches (if armed) or the sequential target (if not), consumes the arming token on
  dispatch (one triage authorizes exactly one fan-out — same single-use idiom as
  `ControlPlane.clear_approval()`), and logs `RCA_EVIDENCE_FANOUT_DISPATCHED` /
  `RCA_EVIDENCE_FANOUT_NOT_ARMED` to the real event trail. Byte-identical passthrough for every
  other frontier in the graph, ANALYSIS_G1 included.
- **`advance()`** — consults the resolver; when (and only when) a conditional fan-out was narrowed
  to one target, that target is used directly. Every non-narrowed frontier still falls through to
  the unchanged `graph_next()` path, which is the only thing that knows how to pass *through* a
  synthetic non-Stage node like `ANALYSIS_JOIN`.
- **`_advance_with_fanout()`** — a join node that **is** a real Stage (`RCA_JOIN`) is now advanced
  *to*, not passed through. Passing through it would have silently deleted the "independent
  synthesis" half of the mechanism. `ANALYSIS_JOIN` (no Stage member) keeps its existing
  passthrough behavior exactly.
- **`_rca_fanout_agent_evidence_count()`** — new. Counts branches that *both* reached PASS in real
  state *and* really wrote their own Blackboard topic. Two independent real facts; never the
  synthesizing agent's say-so.
- **`_root_cause_confidence_inputs()`** gains an optional `concurrent_agent_evidence_count`, added
  to (never substituted for) the refuted-alternative-hypothesis count. Defaults to 0, so every
  pre-existing caller and stage is byte-identical. `_score_root_cause_confidence()` supplies the
  real count at RCA_JOIN and records it on the `root_cause_confidence` topic and the
  `ROOT_CAUSE_CONFIDENCE_SCORED` event.
- **`_bb_rca_join()`** + `STAGE_BLACKBOARD_WRITERS["RCA_JOIN"]` — writes `rca_evidence_fusion` in
  the same shape `rca-multi-agent-fusion.js` writes. `contributing_agents` is overlaid in
  `_write_blackboard_from_evidence()` from the real graph + real branch results, never from the
  agent's text.
- The stale `multi_agent_consensus_count` comment the audit called out is rewritten to describe
  what the code now actually does.

### 4. `dv_harness/gates.py`

`STAGE_GATES["RCA_JOIN"] = [("root_cause_evidence_gate", "root_cause_evidence_gate.py",
"--root-cause")]` — the existing RE_AUDIT gate, reused rather than duplicated. Registering that
gate id is also what switches on `_score_root_cause_confidence()` for this stage.

The three evidence branches are deliberately **not** gated (`NO_GATE_REQUIRED`): they are
single-domain gatherers, and gating them on producing a root cause would actively push each one to
invent the cross-domain conclusion RCA_JOIN exists to make. Their output is still captured — each
writes its own Blackboard topic, which RCA_JOIN then has to actually read.

### 5. `dv_harness/prompts.py`

`STAGE_DE_EXPLAINER` 白話說明 entries for all four new stages (see "Two real regressions" below —
this is a hard requirement enforced by a test, not optional polish), and
`STAGE_INSTRUCTIONS` for all four new stages (branches: stay in your one evidence domain, you are
blind to the others, do not reach a root cause; RCA_JOIN: run the three real
`dv-harness blackboard read` commands first, resolve disagreements by re-reading cited sources
rather than voting, then the full `root_cause_evidence_gate` block). FAILURE_RECOVERY's own
instructions now state plainly that the classification really does select the downstream path.

### 6. Skills consolidated (CLAUDE.md's Methodology Consolidation Rule)

- `CORE/multi-agent-orchestrator/SKILL.md` — the section the audit quoted ("這個系統的『平行』是真的
  由你…用 Agent tool…不是 `dv_harness` 的 Python 引擎內部有 thread/async 在跑") was factually stale
  and is replaced by an explicit **three real paths** section: (A) the engine's own graph fan-out
  (ANALYSIS_G1 + the new RCA_G1, with the engine doing the `AgentTaskStore` bookkeeping itself),
  (B) the Workflow script's `parallel()`, (C) the session's own multi-Agent-tool-call technique —
  and states that the manual bookkeeping in rule 3 is needed **only** for (C).
- `CORE/issue-triage-and-deep-rca/SKILL.md` — "Two real paths" is now "Three", with the automatic
  engine path listed first.
- Both synced to `../industrial/.claude/` and `../PACKAGE/.claude/`.
- `START_HERE.md`'s "Core mechanisms (verified against current code)" graph line corrected
  37 nodes / 48 edges → 41 / 58, since it explicitly claims to be verified against current code.

---

## Verification

New: `dv_harness_tests/test_rca_multi_agent_fanout.py` (7 tests). These drive the **real** engine over
the **real** `main_graph.json`, through the **real** gate scripts as subprocesses, asserting on
**real** artifacts. The only stub is the LLM adapter itself — unavoidable without a Claude subprocess,
and exactly the same stub the already-proven ANALYSIS_G1 fan-out test uses. The agent *text* is
stubbed; the graph traversal, thread-pool concurrency, gate subprocesses, task-store bookkeeping and
Blackboard writes are all genuinely executed.

`test_real_issue_triage_dispatches_the_rca_fanout_end_to_end` is the answer to the audit's
"actually run it once end-to-end" requirement, and asserts, in one run, every one of the audit's own
verification criteria:

1. FAILURE_RECOVERY passes all **five** of its real gate scripts on real evidence → arming token set,
   carrying the real `evidence_hash`.
2. `advance()` dispatches all three branches with **real concurrency** (peak ≥ 2 simultaneously; the
   first-enter-to-last-exit span is under one branch's sleep × 1.8, i.e. not serial).
3. `current_stage` lands **on** `RCA_JOIN` in `NOT_STARTED` — proving the join was not passed through.
4. The arming token is consumed (single-use).
5. `.dv-harness/agents/tasks.json` gets **3 tasks sharing `parallel_group=RCA_G1`**, all
   `status=COMPLETED`, all with real float `started_at`/`completed_at`/`duration_sec` — the audit's
   criterion "≥2 tasks sharing one parallel_group that both reach DONE/COMPLETE with real timing".
6. RCA_JOIN executes and its `root_cause_evidence_gate` subprocess accepts the synthesis;
   `.dv-harness/blackboard/rca_evidence_fusion.json` is written with
   `contributing_agents == {rtl-evidence-agent, log-evidence-agent, vip-spec-evidence-agent}` derived
   from real branch results.
7. `root_cause_confidence.concurrent_agent_evidence_count == 3` — `multi_agent_consensus_count` now
   genuinely derives from concurrent-agent output, closing the audit's item 4 note.
8. `advance()` from RCA_JOIN resolves back to `CHANGE_IMPACT`.
9. `.dv-harness/events.jsonl` carries `RCA_EVIDENCE_FANOUT_ARMED`, `RCA_EVIDENCE_FANOUT_DISPATCHED`,
   and real stage events for all four new node ids.

The other six tests cover: graph/agent-profile/topic binding; RCA_JOIN being an executable stage on
the reused gate; a KNOWN triage costing **zero** extra agents and routing exactly as before; stale
arming being revoked by a later non-REAL_ISSUE triage; and two backward-compatibility tests proving
the conditional resolver is a no-op for ANALYSIS_G1 and for every ordinary single-edge transition.

Updated (behavior preserved, fixture corrected): `test_graph_parallel_dispatch.py` and
`test_active_stages_read_sites.py`. Both synthetic fixtures modelled ANALYSIS_JOIN but borrowed the
real `DE_BASELINE_REPRODUCTION` Stage id for their join node purely for convenience. Once "join node
that IS a real executable Stage" became a genuinely different case, that fixture no longer modelled
what it claimed to; the join node is now a genuinely synthetic `TESTG1_JOIN`. Every assertion in
those tests is unchanged. Node-count and fan-out-source assertions updated 37 → 41 and
`{PROTOCOL_CAPABILITY}` → `{PROTOCOL_CAPABILITY, FAILURE_RECOVERY}`.

### Two real regressions this change caused, found by the sweep and fixed

Adding four `Stage` enum members is not free, and a 471-test sweep over every Stage-sensitive suite
caught both consequences. Neither was fixed by weakening a test:

1. `test_engine_gates_and_routing.py::test_all_35_stages_have_real_de_explainer_entries` — every
   declared Stage must carry a real, non-fallback `STAGE_DE_EXPLAINER` entry (the test exists
   because the fallback text tells a DE to "ask the DV owner", which is useless to a DE who has
   none). **Fixed by writing four real 白話說明 explainers**, one per new stage, in
   `dv_harness/prompts.py`. The test was also renamed to
   `test_every_declared_stage_has_a_real_de_explainer_entry` — it asserts on `len(Stage)`
   dynamically, so a stage count baked into its *name* goes stale silently (it just moved 35 → 39).
2. `test_engine_gates_and_routing.py::test_graph_next_walks_full_mechanism_first_pipeline` — the
   single-hop PASS walk's expected-unvisited set. The four RCA stages belong there for both reasons
   already represented in that set: they hang off `FAILURE_RECOVERY` (a FAIL-only branch the walk
   never enters), and they are a `parallel_group` fan-out plus join, which a single-target-per-step
   walker structurally cannot enumerate — exactly why `SOC_SCENARIO_PLANNER`/`INFRASTRUCTURE_AUDIT`
   are already listed. Added with a comment saying so and pointing at the tests that *do* prove the
   RCA nodes are reachable and executed.

### Sweep results, stated honestly

Two full sweeps were run over every suite that imports `Stage`/`ORDER`/`STAGE_DE_EXPLAINER` or
drives the engine (`test_engine_gates_and_routing`, `test_graph_parallel_dispatch`,
`test_active_stages_read_sites`, `test_rca_multi_agent_fanout`, `test_stage_*`,
`test_inference_engine_wiring`, `test_react_loop`, `test_harness_reliability`,
`test_cross_adapter_token_tracking`, `test_dashboard_cli_checklist_rendering`,
`test_hard_gate_script_smoke`, `test_skill_resolver`):

- Sweep 1 (471 tests, 34m): **2 failed** — the two real regressions above. Fixed.
- Sweep 2 (382 tests, 41m, after the fixes): the 7 new tests pass, both previously-failing tests
  pass, and **3 failed** — `test_engine_dispatches_all_three_branches_concurrently_and_joins`,
  `test_newly_wired_orphan_gates_pass_with_valid_evidence`,
  `test_run_stage_promotes_vplan_summary_to_project_memory_on_pass`. All three are load-induced,
  not regressions: the second and third died on `subprocess.TimeoutExpired` after 30s on a gate
  script (`vplan_writer_validation_gate.py`), and the first is the timing-sensitive concurrency
  assertion whose own in-file comment documents it failing under `pytest -n8` contention. All three
  **passed on immediate re-run** (`3 passed in 35.81s`) and all three had passed in sweep 1.
  Cause: `ps` showed 13 concurrent `pytest dv_harness_tests/` runs from other agents in this
  session hammering the same tree.

A single clean full-suite run was attempted three times and never completed under that contention
(one was killed at 78%); the two sweeps above are the real, complete signal for everything this
change can affect.

---

## Deliberately not done in this pass

- **No `dv-harness agent-task create/start/complete` CLI bridge.** The audit offered it as
  alternative 3; option (a)'s graph integration makes the engine do that bookkeeping itself, so
  adding the CLI would be a second way to write the same store.
- **No engine-source sync into `../industrial/` and `../PACKAGE/`.** Their `dv_harness/engine.py` is
  dated 2026-08-31 and their `main_graph.json` 2026-08-29 — those trees are already several sessions
  behind v50 independently of this change. Copying only my files into them would produce an
  inconsistent mix, which is worse than leaving them consistently stale. `.claude/` skills *were*
  synced (that is the part CLAUDE.md's rule names explicitly, and those files are self-contained).
  Re-syncing the deliverable trees wholesale is a separate housekeeping pass.
- **No live-LLM run.** No Claude subprocess is available in this environment, so "end-to-end" here
  means the full real engine/graph/gate/store/blackboard round trip with a scripted adapter. What
  remains unproven by this pass is only whether the three real agent *profiles* produce good evidence
  text — which is a prompt-quality question, not a wiring one, and is the same thing that was
  unproven for every other stage in this harness.
