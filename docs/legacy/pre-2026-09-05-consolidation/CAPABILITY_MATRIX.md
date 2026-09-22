> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# AI Agent Harness L5 — Final Capability Matrix

| Domain | Final Mechanism |
|---|---|
| Scope | Block/IP -> Subsystem -> Multi-Subsystem -> Full SoC |
| Orchestration | Graph Workflow + Conditional Edges |
| Planning | Plan-and-Execute |
| Routing | Route Resolver + Skill Resolver |
| Agents | 7 Primary Agents + Dynamic Task/Job Agents |
| Shared State | Blackboard |
| Memory | Claude Project + Working + Job + Project + Engineering + Organizational |
| Memory Governance | Router + Retrieval + Consolidation + Confidence Gate + GC |
| Evidence Truth | Current Evidence Wins |
| Documents | Extraction + Incremental Index + SHA/Version/Page/Section Traceability |
| Reasoning | Evidence-Grounded ReAct + Autonomous Inference |
| Evidence Consensus | DUT RTL + PHY + Register + VIP + Independent Synthesis |
| Simulation Default | FSDB OFF |
| VIP Observability | VIP Trace/Report optional |
| Debug Escalation | Targeted FSDB only when needed |
| Waveform Planning | User-confirmed scope + level/depth |
| Failure Replay | Stop at first relevant failure/error/fatal/missing/mismatch |
| Source Control | Git Pull/Sync/Commit/Push |
| Source Identity | Server Exact SHA Gate |
| Build/Sim | VCS |
| Debug | FSDB + fsdbreport + Verdi |
| Regression | LSF |
| Job Autonomy | One Job = One Agent |
| Alerts | Change-only immediate + periodic full snapshot |
| Job Early Stop | Exact JOB_ID only |
| Batch Consistency | Same SHA/build/config per regression batch |
| Closure | Fix current -> wait all jobs -> batch fix new -> rerun |
| Audit | Final Deep Audit |
| Observability | Stage Wall Clock + Aggregate Agent Runtime + Token/Tool/Retry/Finding metrics |
| Human Control | STATUS / WHY / EVIDENCE / HYPOTHESIS / REVIEW / DOCS / MEMORY / PROFILE / PAUSE / REDIRECT / TAKEOVER |
| Startup Governance | LOCAL_ANALYSIS vs REMOTE_EXECUTION |

| DV Environment Builder | From DUT RTL/spec/VIP inputs to UVM/VIP/scoreboard/RAL/coverage/smoke-test baseline |
| One-Click Package | Remote Control + Local/Remote execution + Builder + Closure in one canonical ZIP |
