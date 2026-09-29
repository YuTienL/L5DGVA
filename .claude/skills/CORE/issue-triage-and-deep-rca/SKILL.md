---
name: issue-triage-and-deep-rca
description: Classify MISCLASSIFIED/KNOWN/REAL_ISSUE, then deep RCA only for real issues, with fix/risk review and dut-request.md logging.
---
# Issue Triage and Deep RCA

health_monitor → issue_triage → MISCLASSIFIED / KNOWN / REAL_ISSUE.

MISCLASSIFIED:
record reason/evidence; do not launch deep RCA unless contradictory evidence exists.

KNOWN:
link known issue / waiver / prior RCA; verify signature matches.

REAL_ISSUE:
launch deep analysis_debug over scoreboard report, PHY model, Standard spec,
VIP examples/source/docs, RTL, TB, command.txt, sim.log, trace and FSDB if needed.

## Three real paths for launching deep RCA -- pick honestly, do not overclaim

**Automatic, and the one to expect first: the engine's own RCA_G1 graph
fan-out (2026-09-03).** When this triage runs as the harness's FAILURE_RECOVERY
stage and your `issue_triage_classification_gate` evidence block classifies the
failure `REAL_ISSUE`, you do not have to launch anything: `dv_harness/engine.py`
itself fans `main_graph.json` out to RCA_RTL_EVIDENCE / RCA_LOG_EVIDENCE /
RCA_VIP_SPEC_EVIDENCE (the same three specialist agent profiles the Workflow
script below uses) on a real `ThreadPoolExecutor`, then lands on the real
RCA_JOIN stage where `analysis_debug` re-reads the three branches' Blackboard
topics and rules under `root_cause_evidence_gate`. Classifying
MISCLASSIFIED/KNOWN/BLOCKED keeps the original single FAILURE_RECOVERY ->
CHANGE_IMPACT path. So the classification you write is not just a record -- it
really does select the investigation shape. The two manual paths below stay for
RCA that is NOT happening inside a FAILURE_RECOVERY stage run.


**Default: single-sub-agent sequential path (analysis_debug).** One
analysis_debug sub-agent call pulls the evidence types above itself, in
sequence, inside its own turn (optionally using several Read/Grep/PowerShell
tool calls, still one agent). This is the existing, real, always-available
path and remains the default for most REAL_ISSUE cases -- most failures do
not need multiple independent evidence-gathering agents to explain.

**Optional: multi-agent parallel evidence fan-out
(`.claude/workflows/rca-multi-agent-fusion.js`).** Use this saved Workflow-tool
script instead when the failure genuinely needs multi-angle evidence gathered
independently and in parallel before a verdict makes sense -- e.g. the
symptom could plausibly originate in RTL, in the TB/VIP side, or in a spec
ambiguity, and pre-committing to one investigation order would bias the
result. It fans real specialist agents out in genuine parallel (RTL/TB via
`rtl-evidence-agent`, sim.log/trace/scoreboard/command.txt via
`log-evidence-agent`, VIP source/example/docs+Standard-spec+PHY-model via
`vip-spec-evidence-agent`, and optionally FSDB/waveform via the existing
`waveform-root-cause-agent` when `includeWaveform`+`fsdbHint` are given), then
a real Evidence Fusion stage that cross-references/dedups their findings and
persists the merged result to the Blackboard's `rca_evidence_fusion` topic
via the real `dv-harness blackboard write` CLI command (backed by
dv_harness/blackboard.py's actual `Blackboard.write()`), then an RCA Review
stage (`analysis_debug`, reused as the arbiter over already-fused evidence)
that independently re-reads that topic and produces the final verdict.

Be honest about what each path actually is: the sequential path is one agent
pulling several evidence types itself, one after another; the fan-out path is
this repo's own Workflow tool genuinely running several distinct, narrow
specialist agents (see `.claude/agents/ROSTER.md`) concurrently; and the
engine's RCA_G1 fan-out above is a third, separate mechanism again -- the
Python engine's own threads, driven by the graph rather than by anyone
remembering to call something. All three are real; a human/LLM session
manually issuing several Agent-tool calls in one turn is none of them (see
`CORE/multi-agent-orchestrator`, which now lists all three side by side).
Reach for the fan-out script by name when parallel
multi-angle gathering is genuinely warranted; do not invoke it reflexively
for every REAL_ISSUE, and do not describe the plain sequential analysis_debug
path as "multi-agent parallel" -- it is not.

Before modify:
produce root cause, fix plan, risk assessment, affected scope, regression plan, rollback plan.
Only HIGH/VERIFIED RCA can modify.
After successful verification, record issue, root cause, fix, risk, verification result and change hash in dut-request.md.
