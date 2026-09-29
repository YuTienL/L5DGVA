# Gap-close pass — AI mechanism #3: Multi-Agent Orchestrator

**Status: NO_ACTION_NEEDED**

No file was modified. No commit was made.

The audit verdict for this mechanism was WIRED_AND_FIRING with no gap named, so
per the task's own rule 1 the job here was to re-verify the cited evidence
first-hand rather than to change code. Every cited item was re-checked against
the **current working tree** (not the audit's snapshot), which matters because
`dv_harness/engine.py` has since accumulated uncommitted edits from concurrent
workstreams in this same session — the audit's line numbers have shifted by
~167 lines, but every symbol and every link in the chain is intact.

## Re-verification, first-hand

Repo root is `D:\DV\Task\DV_Agent_Harness_L5\v50` (not the parent directory).

1. **The commit is real.** `80cd2b87191aaac175bf561d1694da8480434cac`, "Wire the
   RCA multi-agent evidence fan-out into the real engine stage flow",
   2026-09-04, +167/-7 in `dv_harness/engine.py`. Its message independently
   states the same before-state the audit describes (no `RCA_G1` in the graph;
   `.claude/workflows/rca-multi-agent-fusion.js` with zero callers from
   `engine.py`).

2. **Graph is real** — `v50/.dv-harness/graph/main_graph.json:356-394`:
   `RCA_RTL_EVIDENCE` / `RCA_LOG_EVIDENCE` / `RCA_VIP_SPEC_EVIDENCE`, each
   `parallel_group: "RCA_G1"`, each with a distinct `blackboard_write` topic
   (`rca_rtl_evidence` / `rca_log_evidence` / `rca_vip_spec_evidence`) and a
   distinct real agent profile; `RCA_JOIN` with `join_group: "RCA_G1"`,
   `blackboard_read` of all three branch topics, `blackboard_write:
   ["rca_evidence_fusion"]`. Edges at `:522-529` fan out from
   `FAILURE_RECOVERY` and rejoin onto `CHANGE_IMPACT`.

3. **The three agent profiles exist on disk** —
   `v50/.claude/agents/rtl-evidence-agent.md`, `log-evidence-agent.md`,
   `vip-spec-evidence-agent.md`. The graph binds real files, not names.

4. **`FAILURE_RECOVERY` is genuinely reachable**, so the fan-out source is not a
   dead node: five real FAIL edges enter it (`main_graph.json:487,509,511,518,520`
   from `DE_BASELINE_REPRODUCTION`, `BUILD_DEBUG`, `VERIFY`, `INFRA_RECOVERY`,
   `COVERAGE_CLOSURE`).

5. **Stage enum is real** — `v50/dv_harness/models.py:63-66`. All four are real
   `Stage` members, so `RCA_JOIN` is `run_stage()`-executable, not a synthetic
   passthrough node.

6. **Trigger** — `engine.py:1647` `_arm_rca_evidence_fanout()`, called from the
   `verdict == "PASS"` branch of `run_stage()` at `engine.py:3418`. Arms only on
   `stage == FAILURE_RECOVERY` with
   `issue_triage_classification_gate.classification == "REAL_ISSUE"`; any other
   classification actively clears a stale arming.

7. **Dispatch is on the real production path** —
   `_resolve_conditional_fanout_frontier()` (`engine.py:3757`) is called from
   the real `advance()` (`engine.py:3796`) at `engine.py:3820`, which calls
   `_advance_with_fanout()` at `:3822`; `loop()` (`engine.py:4013`) calls
   `self.advance(user_goal)` at `engine.py:4166`. No bypass, no test-only shim.

8. **Real concurrency through the real stage path** — `_advance_with_fanout()`
   (`engine.py:3876`) submits `_run_branch_to_terminal` per branch to a
   `ThreadPoolExecutor` (`:3931`); `_run_branch_to_terminal` (`engine.py:3848`)
   calls `self.run_stage(user_goal, stage=branch)` (`:3857`) — the same real
   gate-subprocess/adapter-dispatch path every other stage uses, with the same
   `max_stage_retries` / `replan_stage()` handling `loop()` itself uses.

9. **Independent synthesis is gated and persisted** — `gates.py:278` binds
   `RCA_JOIN` to the existing reused gate set (the same `root_cause_evidence_gate`
   family, with the deliberate rationale comment at `gates.py:260-271` about why
   the three branches stay domain-scoped and only `RCA_JOIN` makes the single
   cross-domain root-cause claim). `_bb_rca_join` (`engine.py:317-351`) writes
   `rca_evidence_fusion` with `produced_by: "engine:RCA_G1_graph_fanout"`, and
   `engine.py:2467-2484` derives `contributing_agents` from actual branch results.

10. **Concurrent edits did not damage it.** `git diff -U2 dv_harness/engine.py`
    shows the only uncommitted hunks anywhere near this code are at the
    `verdict == "PASS"` promotion block (`_promote_experience_knowledge` /
    `_promote_verified_fix_knowledge` gaining a `resolved_protocol=` argument)
    and a stage-done display block much further down. The
    `self._arm_rca_evidence_fanout(stage, evidence_blocks)` call appears in that
    diff as an untouched context line. `models.py`, `gates.py`,
    `main_graph.json` and the test file are all clean in `git status`.

11. **I ran the suite myself, in the current dirty tree**:
    `python -m pytest dv_harness_tests/test_rca_multi_agent_fanout.py -q`
    → **`7 passed in 44.22s`**.

    The load-bearing test, `test_real_issue_triage_dispatches_the_rca_fanout_end_to_end`
    (`dv_harness_tests/test_rca_multi_agent_fanout.py:251-338`), drives a real
    `DVHarness` over the real shipped graph: real `run_stage("FAILURE_RECOVERY")`
    through its real gate subprocesses to a real PASS, then the real
    `h.advance("goal")` — not a private helper — asserting real concurrency
    (`adapter.peak >= 2` plus an overlapping-time-window span check), that
    `RCA_JOIN` was *landed on* and left `NOT_STARTED` rather than silently
    passed through, real `AgentTaskStore` bookkeeping (3 tasks,
    `parallel_group="RCA_G1"`, real float timings), a real `RCA_JOIN`
    `run_stage()` PASS through `root_cause_evidence_gate`, the persisted
    `rca_evidence_fusion` record with `contributing_agents` covering all three
    agents, `concurrent_agent_evidence_count == 3`, resolution back onto
    `CHANGE_IMPACT`, and a real `RCA_EVIDENCE_FANOUT_ARMED` /
    `RCA_EVIDENCE_FANOUT_DISPATCHED` event trail. Only the LLM adapter is
    stubbed.

## On the scope condition

The fan-out fires only when `FAILURE_RECOVERY`'s gate-verified triage lands on
`REAL_ISSUE`. I agree with the audit that this is a deliberate boundary rather
than a gap: `issue_triage_classification_gate.py` already FAILs any `REAL_ISSUE`
that did not also set `deep_rca_triggered`, so a `REAL_ISSUE` reaching the arming
point is structurally a failure the harness has already ruled needs deep RCA —
which is CLAUDE.md's "important DUT/PHY/Register/VIP changes" stated in the
harness's own vocabulary. The `KNOWN`/`MISCLASSIFIED`/`BLOCKED` path costing zero
extra agents is itself covered by
`test_non_real_issue_triage_keeps_the_original_single_path` and
`test_stale_arming_is_cleared_by_a_later_non_real_issue_triage`.

Widening the trigger would be a policy change requiring a user decision, not a
gap closure, and would contradict the fan-out's own `whenToUse` scoping. I did
not touch it.

## Conclusion

Mechanism #3 is (a) a real, engine-native mechanism — dispatched by
`engine.py`'s own `advance()`/`loop()` stage progression, over the real shipped
graph, through the real gate/adapter path, with real concurrency and a real
persisted independent synthesis. It is not this session's ad hoc Workflow-tool
usage. Nothing to close.
