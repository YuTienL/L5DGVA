> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# AI Agent Harness L5 — One-Click Complete Baseline

## Start Modes

### Local-only
This must be declared first:
「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」

### Remote execution
This must be declared first:
「這個需要連伺服器/跑模擬。」

## Remote Control
```powershell
.\REMOTE_CONTROL_READINESS.ps1
.\REMOTE_CONTROL_START.ps1
```

## Core Full Flow
Goal / Requirements
-> Route + Skill Resolver
-> Graph + Plan-and-Execute
-> Multi-Agent Evidence Acquisition
-> Blackboard + Memory
-> Independent Synthesis
-> Autonomous Inference
-> Evidence Truth Gate
-> Implementation / Review
-> Git / Exact SHA
-> Initial Simulation (FSDB OFF, VIP trace optional)
-> FAILED? Targeted First-Failure Waveform Rerun
-> LSF One Job = One Agent
-> Change-only Alert + Periodic Snapshot
-> Batch Closure
-> Final Deep Audit
-> SIGNOFF-READY

## Environment Builder Capability
Inputs:
DUT RTL / Spec / Programming Guide / Register Spec / VIP / Examples / Reference Designs

Outputs:
UVM top / VIP integration / clock-reset / config-reg model / sequence library /
scoreboard / RAL / assertions / coverage / error injection / smoke tests /
compile -> simulation -> self-repair -> baseline-ready

## Human Control
STATUS / WHY / EVIDENCE / HYPOTHESIS / REVIEW / DOCS / MEMORY / PROFILE /
APPROVE / REJECT / REDIRECT / PAUSE / RESUME / TAKEOVER
