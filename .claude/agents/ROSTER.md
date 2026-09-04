# Real Agent Roster (live-checkable)

Canonical list of the real agent profiles in this repo, with each one's REAL
production **dispatch status**. Check any poster/doc/marketing claim about this
harness's "agent roles" against this file before believing it.

Both halves of this file are machine-checked:

- the agent list is checked against the real `.claude/agents/*.md` files by
  `dv_harness/stats_snapshot.list_agent_files()`;
- the **Dispatch** value on every entry is checked against the real dispatch
  tables by `dv_harness/agent_dispatch.agent_dispatch_map()`.

`dv_harness_tests/test_agent_roster_doc.py` and
`dv_harness_tests/test_agent_dispatch_map.py` fail if either drifts, so
repointing a `node.agent` field in `main_graph.json` without updating this file
breaks the build. Do not hand-edit a Dispatch value to make it agree -- fix the
graph or regenerate the entry.

## What the Dispatch values mean

The real dispatch path a `GRAPH_DISPATCHED` agent travels:

```
main_graph.json node.agent
  -> dv_harness/router.py        RouteResolver.resolve()
  -> dv_harness/multi_agent.py   delegate()  [records .dv-harness/agents/tasks.json]
  -> dv_harness/agent_profile.py load_agent_profile()  [reads this .md's frontmatter]
  -> dv_harness/adapters/cli.py  claude --agent <name> --allowedTools/--disallowedTools
```

- **GRAPH_DISPATCHED** -- named by >=1 `.dv-harness/graph/main_graph.json` `node.agent` field -- really dispatched by `engine.run_stage()`.
- **SUBGRAPH_DISPATCHED** -- named only by a `.dv-harness/graph/subgraphs/*.json` `node.agent` field.
- **WORKFLOW_DISPATCHED** -- named only by a `.claude/workflows/*.js` caller.
- **NOT_DISPATCHED** -- no `node.agent` or workflow call site anywhere -- see the per-agent note for how its role-shaped work really runs.

`NOT_DISPATCHED` does **not** mean "fake" or "dead". In every case below the
role-shaped work really does run in production -- as an engine gate script, a
library call, a Skill, or a sub-agent of a dispatched agent. It means only that
this profile is not itself named by a stage's `node.agent` field, so it must
never be described as a stage-owning role in the automatic flow.

## Real Agents (23)

Counts by dispatch status: GRAPH_DISPATCHED 14, SUBGRAPH_DISPATCHED 0, WORKFLOW_DISPATCHED 0, NOT_DISPATCHED 9.

1. **IP_UVM_DV_Gen** -- Dispatch: `NOT_DISPATCHED`

   Use when building a Synopsys VIP-based IP-level UVM verification environment for any protocol or bus IP - USB, PCIe, Ethernet, MIPI CSI-2, MIPI DSI, CAN-FD, eDP, eMMC, SDIO, AMBA4/AXI/AHB/APB and similar - that must live inside an existing SoC testbench driven by command.txt-style BFM patterns. Toolchain is VCS for simulation and Verdi for debug. Covers surveying the DUT and the VIP, choosing the attachment layer, building the Verilog-to-UVM bridges, wrapping VIP sequences as plain tasks, converting the existing BFM patterns, and producing the filelists, Makefile, waveform setup, checkers, vPlan and user guide.

   *How this role really runs*: Invoked by trigger description as the `ip-uvm-dv-gen` Skill, not via a `node.agent` field. Its generator work also runs as real library code (`dv_harness/uvm_generator/`, `dv_harness/vplan_writer/writer.py`).

2. **analysis-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read-only SoC hierarchy, interface, VIP/TB topology, protocol, command capability and readiness investigator.

   *main_graph.json nodes (11)*: `ARCH_CALIBRATION`, `ARCH_DISCOVERY`, `CHANGE_IMPACT`, `DISCOVERY`, `INFRASTRUCTURE_AUDIT`, `INTAKE`, `PROJECT_MODEL`, `PROTOCOL_CAPABILITY`, `REQUIREMENTS_TRACEABILITY`, `VERIFICATION_ARCHITECTURE`, `VPLAN`

   *subgraph nodes (4)*: `multi_source_evidence_consensus.json:DUT_RTL_EVIDENCE`, `multi_source_evidence_consensus.json:PHY_DOC_EVIDENCE`, `multi_source_evidence_consensus.json:REGISTER_GUIDE_EVIDENCE`, `multi_source_evidence_consensus.json:VIP_REFERENCE_EVIDENCE`

3. **analysis_debug** -- Dispatch: `GRAPH_DISPATCHED`

   Deep multi-source root-cause-analysis sub-agent, invoked by debug-agent during FAILURE_RECOVERY ONLY when issue_triage classifies an issue as REAL_ISSUE -- see CORE/issue-triage-and-deep-rca. Produces the root_cause_evidence_gate/deep_rca_evidence_gate evidence debug-agent's own stage instructions require for RE_AUDIT-grade findings.

   *main_graph.json nodes (1)*: `RCA_JOIN`

   *workflow callers*: `rca-multi-agent-fusion.js`

4. **audit-change-governance-agent** -- Dispatch: `NOT_DISPATCHED`

   Read-only Audit/Change Governance specialist -- answers "what changed, by whom/which agent, when, with what evidence, and is it reversible" by querying this harness's own real, already-existing audit substrates (.dv-harness/events.jsonl, git log/PR history, GIT_GUARD_DECISION entries, Job/Engineering Memory git SHAs). Never writes code, never runs a job, never merges/pushes/opens a PR itself.

   *How this role really runs*: On-demand, human-invoked read-only agent. It answers questions about substrates the engine already writes (`.dv-harness/events.jsonl`, git history, GIT_GUARD_DECISION events at `dv_harness/cli.py:1435`); it is deliberately not on any automatic stage path.

5. **build-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read/write-free build specialist for canonical compile/elaboration execution, first-causal-error extraction and infrastructure diagnosis.

   *main_graph.json nodes (5)*: `BUILD`, `BUILD_DEBUG`, `DE_BASELINE_REPRODUCTION`, `SERVER_SYNC`, `VERIFY`

6. **debug-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read-only evidence-driven root-cause specialist for UVM, protocol, compile, assertions, scoreboard, timeout, seed-dependent and regression failures.

   *main_graph.json nodes (1)*: `FAILURE_RECOVERY`

   *subgraph nodes (2)*: `lsf_per_job_monitor_template.json:FIX_PROPOSAL`, `lsf_per_job_monitor_template.json:JOB_DEBUG`

7. **dv-lead** -- Dispatch: `GRAPH_DISPATCHED`

   Top-level industrial DV orchestrator for DE/general DV engineers using command-driven SoC-aware verification.

   *main_graph.json nodes (3)*: `ANALYSIS_JOIN`, `ENV_CHECK`, `WAIT_USER`

8. **failure-triage-attribution-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Senior-DV reasoning agent for failure triage attribution agent.

   *main_graph.json nodes (1)*: `REGRESSION_MONITOR`

9. **implementation-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Primary controlled writer for command-driven SoC-aware DV implementation.

   *main_graph.json nodes (4)*: `COMMAND_PATTERN`, `GIT_PUSH`, `GIT_SYNC`, `IMPLEMENT`

10. **issue_triage** -- Dispatch: `NOT_DISPATCHED`

   Cheap first-pass classifier for a detected issue (MISCLASSIFIED/KNOWN/REAL_ISSUE/BLOCKED) that gates whether the expensive analysis_debug deep-RCA sub-agent runs at all -- see CORE/issue-triage-and-deep-rca. Invoked as a sub-agent by debug-agent during FAILURE_RECOVERY, matching the issue_triage_classification_gate evidence contract debug-agent's own stage instructions already require.

   *How this role really runs*: Sub-agent invoked by `debug-agent`; the classification it must produce is enforced in production as the `issue_triage_classification_gate` gate registered for FAILURE_RECOVERY (`dv_harness/gates.py:233`).

11. **log-evidence-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read-only sim.log/trace/scoreboard-report/command.txt runtime-text evidence specialist for one RCA evidence-gathering fan-out branch -- extracts exact timestamped log/checker/scoreboard evidence and correlates it against command.txt intent, never from memory or assumption.

   *main_graph.json nodes (1)*: `RCA_LOG_EVIDENCE`

   *workflow callers*: `rca-multi-agent-fusion.js`

12. **memory-agent** -- Dispatch: `NOT_DISPATCHED`

   Read/write-free-of-source-files Engineering Memory specialist -- searches, retrieves, summarizes, writes, links, deduplicates, promotes, demotes, archives and validates records across the 5-tier Memory system and the DV-Knowledge Vault, always through the real router/provider API, never by hand-editing memory files directly.

   *How this role really runs*: DELIBERATELY NON-DISPATCHED. Engineering-Memory work runs in production as engine-internal library calls -- `memory_router.route_and_store()` / `promote_to_organizational()`, imported at `dv_harness/engine.py:14` and called from many `run_stage()` paths -- per CLAUDE.md's Engineering Memory Policy. This profile documents and constrains that tier for a human or sub-agent doing memory work by hand; it is not a stage persona.

13. **post-sim-command-log-validation-agent** -- Dispatch: `NOT_DISPATCHED`

   After simulation PASSED, compare command.txt verification intent with sim.log semantic evidence and block false-green runs.

   *How this role really runs*: Its check runs in production as VERIFY-stage gate scripts (`wave0_post_sim_semantic_gate`, `command_intent_semantic_closure_gate`, `dv_harness/gates.py:199-219`), not as a dispatched persona.

14. **preflight-resource-guard-agent** -- Dispatch: `NOT_DISPATCHED`

   Read/write-free BLOCKING gate specialist that runs the real lmstat + scheduler preflight check (EDA license, LSF/Slurm queue health, host reachability, disk space, workdir, required EDA env vars) before any bsub/sbatch job submission and refuses to let a job go out when any check fails.

   *How this role really runs*: Its check runs in production as `dv_harness/preflight.py`, invoked inside `lsf-submit` and exposed standalone as `dv-harness preflight` (`dv_harness/cli.py:272-292`) for this agent to call.

15. **protocol-corner-case-intelligence-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Senior-DV reasoning agent for protocol corner case intelligence agent.

   *main_graph.json nodes (1)*: `SOC_SCENARIO_PLANNER`

16. **regression-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read/write-free targeted-test and regression specialist that captures test/seed/config evidence, clusters normalized failures, and distinguishes functional, flaky and infrastructure failures.

   *main_graph.json nodes (4)*: `COVERAGE_CLOSURE`, `INFRA_RECOVERY`, `REGRESSION`, `REGRESSION_SELECT`

   *subgraph nodes (4)*: `lsf_per_job_monitor_template.json:EARLY_FAIL_GATE`, `lsf_per_job_monitor_template.json:EARLY_KILL`, `lsf_per_job_monitor_template.json:JOB_STATE_QUERY`, `lsf_per_job_monitor_template.json:SIMLOG_ANALYSIS`

17. **research-architect** -- Dispatch: `NOT_DISPATCHED`

   Principal Verification Research Architect. Takes ResearchEvidenceCards + the ACTUAL current L5 implementation + prior validated research and decides KEEP/ENHANCE/ADD/EXPERIMENT/REJECT for one capability, through the mandatory ten-question current-L5 check. Never implements anything, never decides alone, never issues a verification verdict.

   *How this role really runs*: On-demand, human-invoked. Its decision is not this profile's prose -- it is made by real code, `dv_harness/capability_evolution.py`'s `decide_recommendation()`, from the six searches the agent records, and persisted by `persist_candidate()` to the `capability_evolution_candidates` Blackboard topic plus a Working Memory audit record through the real `memory_router.route_and_store()`. Its Human Approval Gate is the existing `dv_harness/control_plane.py` `ControlPlane.approve()`, not a second approval mechanism. Deliberately not on any automatic stage path: Stage 3 (implementing an approved change) is separate, human-approved work done by `implementation-agent` through a branch and a PR.

18. **review-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Independent read-only signoff reviewer. Challenges low-confidence assumptions, diff scope, protocol correctness, vPlan traceability, validation evidence and regression risk.

   *main_graph.json nodes (6)*: `EXPERT_FEEDBACK_LOOP`, `PROMOTION_READINESS`, `REQUIREMENT_CLOSURE`, `RE_AUDIT`, `SIGNOFF`, `SYSTEM_LEVEL`

   *subgraph nodes (1)*: `multi_source_evidence_consensus.json:INDEPENDENT_SYNTHESIS`

   *workflow callers*: `rca-multi-agent-fusion.js`

19. **rtl-evidence-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read-only RTL/testbench static-source evidence specialist for one RCA evidence-gathering fan-out branch -- pulls exact instance/signal/hierarchy/protocol-state evidence from real RTL and TB source, never from memory or assumption.

   *main_graph.json nodes (1)*: `RCA_RTL_EVIDENCE`

   *workflow callers*: `rca-multi-agent-fusion.js`

20. **simulation-semantic-validation-agent** -- Dispatch: `NOT_DISPATCHED`

   Confirm a simulation PASSED run actually proves command.txt verification intent using sim.log evidence before TRUE_PASS.

   *How this role really runs*: Its check runs in production as the `simulation_semantic_validation_gate` gate registered for VERIFY (`dv_harness/gates.py:200`).

21. **verification-risk-experience-agent** -- Dispatch: `NOT_DISPATCHED`

   Senior-DV reasoning agent for verification risk experience agent.

   *How this role really runs*: Its judgement runs in production as the `experience_applicability_gate` gate (`dv_harness/gates.py:351`), consumed by `engine.py`'s memory promotion path.

22. **vip-spec-evidence-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Read-only VIP source/example/user-doc and protocol Standard-spec/PHY-model evidence specialist for one RCA evidence-gathering fan-out branch -- cites exact VIP class/sequence/config semantics and exact spec clauses, never invented VIP API or paraphrased spec text.

   *main_graph.json nodes (1)*: `RCA_VIP_SPEC_EVIDENCE`

   *workflow callers*: `rca-multi-agent-fusion.js`

23. **waveform-root-cause-agent** -- Dispatch: `GRAPH_DISPATCHED`

   Senior-DV reasoning agent for waveform root cause agent.

   *main_graph.json nodes (1)*: `WAVE_ANALYSIS`

   *workflow callers*: `rca-multi-agent-fusion.js`

## Role-shaped work that is deliberately NOT an agent

External posters and summaries of this harness have repeatedly asserted tidy
role taxonomies that this repo does not implement. The recurring four are
recorded here with the real, verified answer, so the question does not have to
be re-litigated by grep every audit:

1. **A project-management / workflow-control role.** Not an agent, by design.
   Stage sequencing, gating and transition control are ordinary Python in
   `dv_harness/engine.py`'s state machine plus `dv_harness/planner.py`'s
   decomposition -- deterministic, replayable and testable, which an LLM
   persona would not be. `dv-lead` is a real GRAPH_DISPATCHED agent but owns
   only 3 nodes (`ENV_CHECK`, `ANALYSIS_JOIN`, `WAIT_USER`); it is not the
   workflow controller and must not be described as one.

2. **An architecture-owning role.** Not a separate agent. `ARCH_DISCOVERY`,
   `ARCH_CALIBRATION` and `VERIFICATION_ARCHITECTURE` dispatch to the read-only
   `analysis-agent` on purpose: those stages emit *evidence*, and the resulting
   `architecture` / `verification_architecture` Blackboard topics are written by
   the engine (`engine.py`'s `_write_blackboard_from_evidence`), not by an agent
   holding a `Write` tool. Architecture that becomes real files is generated
   under `implementation-agent`/`IP_UVM_DV_Gen`. Giving these nodes a writer
   persona would widen write scope for no functional gain.

3. **A verification-planning role.** Not a separate agent, for the same reason:
   `VPLAN` dispatches to read-only `analysis-agent` and the `vplan` Blackboard
   topic is engine-written, while the vPlan artifact itself is produced by real
   library code (`dv_harness/vplan_writer/`). Coverage stays split on purpose --
   vPlan defines coverage intent; `regression-agent` executes and closes it at
   `COVERAGE_CLOSURE`. Do not merge those two.

4. **A knowledge / memory-tier role.** `memory-agent` is a real profile but is
   `NOT_DISPATCHED` on purpose -- see its entry above. Memory work fires in
   production as engine-internal `route_and_store()` /
   `promote_to_organizational()` calls, not as a dispatched persona.

Separation of duties in this harness is real but is enforced by tool scope on
the dispatched agents, not by role names: `analysis-agent` and `review-agent`
declare `disallowedTools: Edit, Write`, so the node sets that reach `SIGNOFF`
genuinely cannot write, and `implementation-agent`'s node set never reaches
`SIGNOFF`.
