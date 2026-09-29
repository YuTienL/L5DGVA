> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# DV Agent Harness L5 — Ultimate Complete Platform

## Core Positioning
One governed DV Agent Harness that can:
1. Build a Subsystem Verification Environment.
2. Select completed subsystem environments and compose a System-Level / Full-SoC environment.
3. Operate locally or through Remote Control.
4. Learn and onboard future interfaces/specifications through evidence-driven plugins.
5. Run compile/simulation/regression/debug/closure loops with human control and verification memory.

## Truthful Capability Labels
BUILDER_AVAILABLE does NOT mean PRODUCTION_QUALIFIED.

Qualification ladder:
BUILDER_AVAILABLE
→ EVIDENCE_READY
→ ENV_GENERATED
→ COMPILE_QUALIFIED
→ SMOKE_QUALIFIED
→ PROTOCOL_QUALIFIED
→ REGRESSION_QUALIFIED
→ PRODUCTION_QUALIFIED

Built-in builder families include:
USB 2/3.x, PCIe, Ethernet, MIPI CSI-2, MIPI DSI, CAN/CAN-FD,
AMBA4 Multi-Master × Multi-Slave, eMMC, SD/SDIO, eDP/DisplayPort, UCIe.

These built-in builders are framework capabilities until actually qualified on current DUT + current Spec + current VIP evidence.

## Environment Modes
SUBSYSTEM_MODE:
DUT + Spec + VIP → Evidence → Builder → UVM Env → Compile → Smoke → Self-Repair
→ BASELINE_READY → Subsystem Registry.

SYSTEM_LEVEL_MODE:
User SoC Goal → select completed subsystem environments → compatibility analysis
→ resolve missing subsystem via SUBSYSTEM_MODE → SoC composition → cross-subsystem scenarios
→ end-to-end scoreboard → system coverage → compile/smoke/self-repair → Full-SoC baseline.

## Remote Control
Remote Control is a CONTROL PLANE, not an Environment Mode.

Web/Mobile/Local control:
STATUS / WHY / EVIDENCE / HYPOTHESIS / REVIEW / APPROVE / REDIRECT /
PAUSE / RESUME / TAKEOVER.

The control plane must not bypass:
Execution Mode Gate, Evidence Truth Gate, SHA Gate, Waveform Gate,
LSF safety, approval policy, qualification gates, or closure gates.

## Evidence-Driven Problem Analysis
Do not trust CLAUDE.md, memory, old notes or prior hypotheses as final truth.
For technical RCA, inspect current evidence:
- DUT RTL/source
- waveform when needed
- PHY docs
- programming guide/register docs
- VIP manual/examples/source/class reference
- compile/simulation logs

Multi-agent acquisition must be followed by an independent synthesis agent.

## Simulation / Waveform Rules
Default simulation: no FSDB dump.
VIP trace/report may be enabled.
If simulation fails:
- stop at first meaningful failure/error/fatal/missing/mismatch when feasible
- rerun only as needed
- ask user for waveform scope and dump level before waveform dump
- use targeted waveform rather than full-run/full-scope dump
- analyze evidence and propose fix
- rerun and verify

## LSF Regression Rules
- Report all submitted jobs.
- One job = one analysis agent.
- Each agent inspects sim.log and current job state.
- Abnormal/UVM_ERROR/FATAL/missing/mismatch may trigger early-stop/kill according to safety policy.
- RCA + proposed modification required.
- Change-only notification is the primary alert rule.
- Periodic job snapshot is also supported.
- After all jobs complete, perform batch-level closure and discover new problems.

## Autonomous Workflow
Start workflow → understand current issues → fix evidence-backed issues
→ wait for current job batch → inspect new failures → fix new issues
→ repeat until closure → deep-analyze files, command.txt and environment
→ final audit.

Every workflow launch must explicitly state:
LOCAL_ANALYSIS = local file analysis only, no server/no VCS
or
REMOTE_EXECUTION = server access / compile / simulation / jobs.

## Verification Memory
Memory stores validated experience, not guesses:
- successful fixes
- failure signatures
- evidence provenance
- qualified environment identities
- tool/VIP compatibility
- reusable UVM patterns
- stage performance

Reuse requires current-context validation.

## USB UVM Golden Reference Base
USB UVM is the reference architecture for generic reusable UVM engineering patterns:
virtual sequencer, registry, barrier/dependency, scoreboard framework,
coverage framework, config/RAL patterns, build/run/regression structure.

USB-specific protocol truth must never leak into another protocol.

## New Interface / New Specification
New interfaces are supported through:
Doc Extraction → Interface Schema Discovery → Evidence Acquisition
→ Plugin Manifest → Builder Generation → Compile/Smoke/Self-Repair
→ Qualification → Protocol Registry → future reuse.

With VIP:
learn VIP manual/examples/source/class reference and build an adapter.

Without VIP:
generate native UVC building blocks (transaction/sequencer/driver/monitor/agent/
config/assertions/scoreboard/coverage/smoke), then self-qualify.

New spec revision:
Spec Diff → impact analysis → update affected builder components → re-qualification.

## Stage Execution Profile
Record per-stage:
- wall-clock time
- model/token consumption where available
- retries
- agent/tool activity
- result
This supports bottleneck and cost analysis.

## Human Governance
User can inspect:
STATUS / WHY / EVIDENCE / HYPOTHESIS.
User can APPROVE / REDIRECT / PAUSE / RESUME / TAKEOVER.
High-impact operations remain gated.

## Ultimate Goal
DUT + Spec + VIP
→ Block/IP
→ Subsystem
→ Multi-Subsystem
→ Full SoC
→ Compile / Simulation / Regression
→ Evidence-Driven Debug
→ Closure
→ Signoff-ready evidence package.


## Canonical Flow Update — Mechanism Before Test Generation
vPlan FIRST → DUT Architecture Discovery → Verification Architecture & Mechanism Planning → Test / Sequence / Scenario Generation → Regression → Coverage → Triage → Root Cause → Calibration → Expert Feedback → Experience Learning.
