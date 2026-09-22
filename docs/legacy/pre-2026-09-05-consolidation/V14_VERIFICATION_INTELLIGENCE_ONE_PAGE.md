> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# v14 Verification Intelligence

```text
               SPEC / REQUIREMENTS
                       │
                       ▼
             REQUIREMENTS TRACEABILITY
                       │
                       ▼
            DUT / SUBSYSTEM / SoC MODEL
                       │
                       ▼
               SoC SCENARIO PLANNER
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼               ▼
 Cross-Protocol   Shared Resource   End-to-End
        │              │               │
        └──────────────┼───────────────┘
                       ▼
            Generic Infrastructure Audit
                       │
                       ▼
                     vPlan
                       │
                       ▼
              command.txt / Pattern
                       │
                       ▼
                 Implementation
                       │
                       ▼
                  Git Changes
                       │
                       ▼
          VERIFICATION CHANGE IMPACT
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
      Targeted      Dependency      Safety
         │             │             │
         └─────────────┼─────────────┘
                       ▼
                 LSF Regression
                       │
                       ▼
              Requirement Closure
                       │
                       ▼
               Workflow Closure
                       │
                       ▼
                    SIGNOFF
```
