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

## Two real paths for launching deep RCA -- pick honestly, do not overclaim

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
specialist agents (see `.claude/agents/ROSTER.md`) concurrently -- a real,
different mechanism from `CORE/multi-agent-orchestrator`'s documented
today-state (a human/LLM session manually issuing several Agent-tool calls in
one turn is not this). Reach for the fan-out script by name when parallel
multi-angle gathering is genuinely warranted; do not invoke it reflexively
for every REAL_ISSUE, and do not describe the plain sequential analysis_debug
path as "multi-agent parallel" -- it is not.

Before modify:
produce root cause, fix plan, risk assessment, affected scope, regression plan, rollback plan.
Only HIGH/VERIFIED RCA can modify.
After successful verification, record issue, root cause, fix, risk, verification result and change hash in dut-request.md.
