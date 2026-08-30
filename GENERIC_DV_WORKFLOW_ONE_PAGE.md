> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# Generic DV Workflow — Any Subsystem to Full SoC

```text
             ANY DUT SCOPE
                  │
       ┌──────────┼──────────┐
       ▼          ▼          ▼
     Block     Subsystem     SoC
                  │
                  ▼
          Generic DV Workflow
                  │
         Hierarchy Discovery
                  ↓
       Instance / Port / Interface
                  ↓
           Protocol Profiles
                  ↓
          VIP / TB Topology
                  ↓
      Generic Infrastructure Audit
       ├─ Scoreboard
       ├─ DMA Scoreboard
       ├─ Performance
       └─ Coverage
                  ↓
                 vPlan
                  ↓
         Pattern / command.txt
                  ↓
          Single Simulation
                  ↓
          Failure Recovery
                  ↓
          LSF Regression
                  ↓
        Monitor / Report
                  ↓
               Signoff
```

Protocol 是 profile；Core Workflow 是通用 verification architecture。
