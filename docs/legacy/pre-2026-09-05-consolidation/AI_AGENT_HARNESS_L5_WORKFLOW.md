> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# AI Agent Harness L5 — Final Complete Workflow

PRE-FLIGHT
↓
Declare Execution Mode
- LOCAL_ANALYSIS
- REMOTE_EXECUTION
- MIXED-PHASED
↓
Environment / Claude CLI / Agent / Skill / Tool Readiness
↓
Document Discovery + Incremental Extraction
↓
Project / DUT / VIP / SoC Modeling
↓
Requirements / vPlan / command.txt / Scenario Analysis
↓
Route Resolver + Skill Resolver
↓
Graph Orchestrator + Plan-and-Execute
↓
Multi-Agent Evidence Acquisition
- DUT RTL/source
- PHY documents
- Programming Guide / Registers
- VIP examples / manual / source / class reference
↓
Blackboard
↓
Independent Synthesis
↓
Autonomous Inference
- Multiple hypotheses
- Supporting evidence
- Counter evidence
- Missing evidence
- Next-Best-Action
↓
Evidence Truth Gate
↓
Find ALL Current Problems
↓
Fix ALL Current Findings
↓
Independent Review
↓
Git Pull/Sync -> Commit/Push
↓
Server Exact SHA
↓
Build
↓
Initial Simulation
- FSDB OFF
- VIP trace/report optional
↓
PASS?
YES:
  Single Verify PASS
  -> Promote pattern/options/SHA/evidence to regression registry
NO:
  Analyze sim.log/UVM/assertion/scoreboard/VIP trace
  -> Need signal-level evidence?
     NO -> continue root-cause analysis
     YES:
       -> Waveform Dump Scope Planner
       -> Ask user for scope + level/depth
       -> Targeted Debug Rerun with FSDB ON
       -> Stop at first relevant:
          failure / error / fatal / missing / mismatch
       -> Optional minimal post-failure margin
       -> Save targeted FSDB + failure timestamp
↓
Freeze Regression Baseline
↓
LSF Submit
↓
One Job = One Agent
↓
Fast Internal Monitoring
+ Change-only Immediate Alert
+ Periodic Full Job Snapshot
↓
Confirmed terminal failure?
YES:
  Save exact-job evidence
  Validate exact JOB_ID
  bkill exact failing job only
  Root-cause analysis / fix proposal
  Queue finding
NO:
  Continue
↓
Wait ALL Jobs Final
↓
Analyze ALL New Findings
↓
Batch Fix ALL New Findings
↓
Review / Git / Exact SHA / Build / Verify
↓
New Frozen Baseline
↓
Regression Again
↓
Repeat Until No Actionable Findings
↓
FINAL DEEP AUDIT
- all source files
- command.txt
- UVM / VIP / branch-A / branch_fw / branch-B
- scoreboard / DMA scoreboard / performance / coverage
- patterns / Make
- Git / DevOps
- Claude CLI / Linux environment
- VCS / Verdi / FSDB
- LSF
- requirements / vPlan / SoC scenarios
- documents / extraction/index
- memory
- agents / skills
- graph / blackboard
↓
CLEAN?
NO -> Closure Loop Again
YES -> SIGNOFF-READY

Cross-cutting controls:
- Human Control
- Evidence Truth Gate
- Execution Mode Gate
- Document Traceability
- Verification Memory
- Stage Execution Profile
