> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# Claude CLI → Generic DV Workflow Startup Gate

```text
            User Request
                 │
                 ▼
      Claude Environment Check
                 │
     ┌───────────┼────────────┐
     ▼           ▼            ▼
 Claude CLI   Superpowers   Plugins
     │           │            │
     ├────── Skills / Workflow ──────┐
     │                               │
     └────── 7 Agents / Settings ────┘
                     │
                     ▼
             READY / PARTIAL / BLOCKED
                     │
                     ▼
            Generic DV Workflow
                     │
          Subsystem → Full SoC
                     │
                     ▼
      Git → Build → Verify → Regression
                     │
                     ▼
                  Signoff
```

Plugin、Skill、Agent 是三種不同 dependency，不可互相推論。
