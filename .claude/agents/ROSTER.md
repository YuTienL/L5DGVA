# Real Agent Roster (live-checkable — see dv_harness/stats_snapshot.py)

This is the canonical list of real agent profiles in this repo, for
checking any future poster/doc claim against. Do not write a fictional
taxonomy that doesn't match this list — verify any role names claimed
against the entries below.

<!-- One entry per real .claude/agents/*.md file, name + its actual
     description: field, filled in from the real files at write time. -->

## Real Agents (21)

1. **analysis-agent**: Read-only SoC hierarchy, interface, VIP/TB topology, protocol, command capability and readiness investigator.

2. **analysis_debug**: Deep multi-source root-cause-analysis sub-agent, invoked by debug-agent during FAILURE_RECOVERY ONLY when issue_triage classifies an issue as REAL_ISSUE -- see CORE/issue-triage-and-deep-rca. Produces the root_cause_evidence_gate/deep_rca_evidence_gate evidence debug-agent's own stage instructions require for RE_AUDIT-grade findings.

3. **build-agent**: Read/write-free build specialist for canonical compile/elaboration execution, first-causal-error extraction and infrastructure diagnosis.

4. **debug-agent**: Read-only evidence-driven root-cause specialist for UVM, protocol, compile, assertions, scoreboard, timeout, seed-dependent and regression failures.

5. **dv-lead**: Top-level industrial DV orchestrator for DE/general DV engineers using command-driven SoC-aware verification.

6. **failure-triage-attribution-agent**: Senior-DV reasoning agent for failure triage attribution agent.

7. **implementation-agent**: Primary controlled writer for command-driven SoC-aware DV implementation.

8. **IP_UVM_DV_Gen**: Use when building a Synopsys VIP-based IP-level UVM verification environment for any protocol or bus IP - USB, PCIe, Ethernet, MIPI CSI-2, MIPI DSI, CAN-FD, eDP, eMMC, SDIO, AMBA4/AXI/AHB/APB and similar - that must live inside an existing SoC testbench driven by command.txt-style BFM patterns. Toolchain is VCS for simulation and Verdi for debug. Covers surveying the DUT and the VIP, choosing the attachment layer, building the Verilog-to-UVM bridges, wrapping VIP sequences as plain tasks, converting the existing BFM patterns, and producing the filelists, Makefile, waveform setup, checkers, vPlan and user guide.

9. **issue_triage**: Cheap first-pass classifier for a detected issue (MISCLASSIFIED/KNOWN/REAL_ISSUE/BLOCKED) that gates whether the expensive analysis_debug deep-RCA sub-agent runs at all -- see CORE/issue-triage-and-deep-rca. Invoked as a sub-agent by debug-agent during FAILURE_RECOVERY, matching the issue_triage_classification_gate evidence contract debug-agent's own stage instructions already require.

10. **log-evidence-agent**: Read-only sim.log/trace/scoreboard-report/command.txt runtime-text evidence specialist for one RCA evidence-gathering fan-out branch -- extracts exact timestamped log/checker/scoreboard evidence and correlates it against command.txt intent, never from memory or assumption. Distinct from post-sim-command-log-validation-agent/simulation-semantic-validation-agent (those two gate a run that already reports PASSED); this one gathers log evidence during REAL_ISSUE deep RCA on a FAILING run. Added for `.claude/workflows/rca-multi-agent-fusion.js`.

11. **memory-agent**: Read/write-free-of-source-files Engineering Memory specialist -- searches, retrieves, summarizes, writes, links, deduplicates, promotes, demotes, archives and validates records across the 5-tier Memory system and the DV-Knowledge Vault, always through the real router/provider API (`route_and_store()`/`promote_to_organizational()`/`MemoryGC`/`MemoryProvider`), never by hand-editing memory files directly. Not responsible for RTL/UVM modification or running simulation (see implementation-agent/build-agent/regression-agent) or root-causing a failure (see debug-agent).

12. **post-sim-command-log-validation-agent**: After simulation PASSED, compare command.txt verification intent with sim.log semantic evidence and block false-green runs.

13. **preflight-resource-guard-agent**: Read/write-free BLOCKING gate specialist that runs the real lmstat + scheduler preflight check (EDA license, LSF/Slurm queue health, host reachability, disk space, workdir, required EDA env vars) before any bsub/sbatch job submission and refuses to let a job go out when any check fails.

14. **protocol-corner-case-intelligence-agent**: Senior-DV reasoning agent for protocol corner case intelligence agent.

15. **regression-agent**: Read/write-free targeted-test and regression specialist that captures test/seed/config evidence, clusters normalized failures, and distinguishes functional, flaky and infrastructure failures.

16. **review-agent**: Independent read-only signoff reviewer. Challenges low-confidence assumptions, diff scope, protocol correctness, vPlan traceability, validation evidence and regression risk.

17. **rtl-evidence-agent**: Read-only RTL/testbench static-source evidence specialist for one RCA evidence-gathering fan-out branch -- pulls exact instance/signal/hierarchy/protocol-state evidence from real RTL and TB source, never from memory or assumption. Added for `.claude/workflows/rca-multi-agent-fusion.js`.

18. **simulation-semantic-validation-agent**: Confirm a simulation PASSED run actually proves command.txt verification intent using sim.log evidence before TRUE_PASS.

19. **verification-risk-experience-agent**: Senior-DV reasoning agent for verification risk experience agent.

20. **vip-spec-evidence-agent**: Read-only VIP source/example/user-doc and protocol Standard-spec/PHY-model evidence specialist for one RCA evidence-gathering fan-out branch -- cites exact VIP class/sequence/config semantics and exact spec clauses, never invented VIP API or paraphrased spec text. Added for `.claude/workflows/rca-multi-agent-fusion.js`.

21. **waveform-root-cause-agent**: Senior-DV reasoning agent for waveform root cause agent. Already covers the FSDB/waveform RCA evidence-gathering role reused (not duplicated) by `.claude/workflows/rca-multi-agent-fusion.js`.
