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

Before modify:
produce root cause, fix plan, risk assessment, affected scope, regression plan, rollback plan.
Only HIGH/VERIFIED RCA can modify.
After successful verification, record issue, root cause, fix, risk, verification result and change hash in dut-request.md.
