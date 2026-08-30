> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# DV Agent Harness Edition v15

```text
┌────────────────────────────────────────────────────────────┐
│                     DV AGENT HARNESS                       │
│ State Machine | Resume | Retry | Audit Trail | Dashboard  │
│ Findings | Requirements | Git SHA | Server SHA | LSF      │
└──────────────────────────┬─────────────────────────────────┘
                           │
                   CLI / SDK Adapter
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                  CLAUDE DV WORKFLOW                        │
│ 7 Agents + Skills + Iron Rules                            │
│ Requirements Traceability                                 │
│ SoC Scenario Planner                                      │
│ Generic Infrastructure Audit                              │
│ Verification Change Impact                                │
│ Workflow Closure                                          │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
                 Git / SSH / Linux Server
                           │
                           ▼
             VCS / VIP / Verdi / FSDB / LSF
```

Harness = WHEN / STATE / RETRY / HISTORY / GOVERNANCE
DV Workflow = WHAT / WHY / HOW
Linux = BUILD / SIM / WAVE / REGRESSION
