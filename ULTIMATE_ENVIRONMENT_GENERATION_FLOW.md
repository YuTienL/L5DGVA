> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# Ultimate Environment Generation Flow

CREATE ENVIRONMENT
        ↓
Environment Mode Router
        ↓
┌──────────────────────────────────────┬────────────────────────────────────────┐
│ SUBSYSTEM_MODE                       │ SYSTEM_LEVEL_MODE                      │
├──────────────────────────────────────┼────────────────────────────────────────┤
│ Select PCIe/USB/MIPI/AMBA4/...       │ Read SoC Goal                          │
│ DUT + Spec + VIP                     │ Subsystem Environment Registry         │
│ Protocol Builder                     │ User-Driven Selection                  │
│ Generate UVM Environment             │ Compatibility Analysis                 │
│ Compile / Smoke / Self-Repair        │ Missing Subsystem?                     │
│ BASELINE_READY                       │   YES -> build via SUBSYSTEM_MODE      │
│ Register Environment                 │   NO  -> SoC Composition               │
│                                      │ Cross-Subsystem Virtual Sequences      │
│                                      │ End-to-End Scoreboard                  │
│                                      │ System Coverage                        │
│                                      │ Compile / Smoke / Self-Repair          │
│                                      │ Full-SoC BASELINE_READY                │
└──────────────────────────────────────┴────────────────────────────────────────┘
                         ↓
                 Regression / Closure
                         ↓
                   Final Deep Audit
