> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# Generic DE + DV Industrial Workflow — One Click

```text
                         USER REQUEST
                              │
                              ▼
                 CLAUDE ENV READINESS GATE
                              │
                 READY / PARTIAL / BLOCKED
                              │
                              ▼
                    PROJECT / REMOTE INTAKE
                              │
                              ▼
              EXISTING PROJECT + REFERENCE ENV
                              │
                              ▼
                 DUT / SoC HIERARCHY MODEL
                              │
                  Verification Boundary
                              │
          Instance / Port / Interface / Protocol
                              │
                              ▼
                     PROTOCOL ROUTER
                              │
       USB / PCIe / Ethernet / AMBA / CSI2 / DSI / CAN-FD
                              │
                              ▼
                    VIP TOPOLOGY / BIND
                              │
                              ▼
          BLOCK: branch-A | branch_fw | branch-B
                              │
                              ▼
                      PROJECT MODEL
                              │
                       CONFIDENCE CHECK
                              │
                              ▼
                        DV READINESS
                              │
                              ▼
             GENERIC INFRASTRUCTURE AUDIT
         Scoreboard | DMA | Performance | Coverage
                              │
                              ▼
                            vPlan
                              │
                              ▼
             command.txt REUSE/EXTEND/GENERATE
                              │
                              ▼
                    PATTERN REGISTRY / MAKE
                              │
                              ▼
                 IMPLEMENT ALL FINDINGS
                              │
                              ▼
              GIT SYNC → COMMIT → PUSH
                              │
                              ▼
                 LINUX SERVER EXACT SHA
                              │
                              ▼
                       BUILD → VERIFY
                              │
                              ▼
                 WAVE=1 → fsdbreport
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                  FAIL                 PASS
                    │                   │
       Log/FSDB/Verdi/Fix              ▼
                    │          AUTO PROMOTE PATTERN
                    └──────↺            │
                                        ▼
                                  LSF REGRESSION
                                        │
                                  MONITOR / REPORT
                                        │
                                        ▼
                                DETAILED RE-CHECK
                                        │
                                RE-RUN ORIGINAL AUDIT
                                        │
                            ┌───────────┴───────────┐
                            ▼                       ▼
                         NEW ISSUE                 CLEAN
                            │                       │
                            └────── FIX LOOP ───────┘
                                                    ▼
                                                 SIGNOFF
```

Core scope: Block/IP → Subsystem → Multi-Subsystem → Full SoC.
