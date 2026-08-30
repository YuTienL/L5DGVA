# AI Agent Harness L5 - Project Instructions

## Core Operating Rules
- Graph is the global workflow authority.
- Blackboard stores current verification truth.
- Verification Memory stores historical verified engineering knowledge.
- Claude project/native memory may store stable project instructions, conventions, workflow rules and user preferences.
- Memory is prior knowledge, not current evidence.
- Any current root cause must be revalidated with current evidence.
- Human Override is always valid.
- Same regression batch must use the same source/build/config identity.
- LSF DONE is not equal to DV PASS.
- One submitted LSF job = one isolated Job Agent context.
- Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent synthesis.
- All actionable findings must close before Final Deep Audit.
- Any process/method/workflow validated in a session must be consolidated into the Harness's permanent engine/agent/skill assets, not left as one-off conversation state.
- Once a real deficiency/weakness/gap is confirmed by evidence (e.g. an audit pass), it must be closed by launching multi-agent implementation work on all currently-known confirmed gaps together, not queued one-at-a-time waiting for individual re-asks.


## Evidence Truth Rule

CLAUDE.md is project guidance, not verification evidence.

Never treat any statement in this file as proof of a current DUT behavior, bug, root cause or pass/fail condition.

Before accepting an engineering conclusion:
- inspect the current RTL/source when relevant,
- inspect/measure current waveform/FSDB when relevant,
- analyze current sim.log/checker/assertion evidence,
- verify current register/programming state when relevant.

If CLAUDE.md conflicts with current evidence, current evidence wins and this file must be updated.


# AI Agent Harness L5 Canonical Identity

This directory is the canonical AI Agent Harness L5 baseline.
Do not rely on legacy version labels in older reference markdown files.

Core policy:
- Graph is global workflow authority.
- Blackboard is current truth.
- Memory is prior knowledge.
- Current evidence wins.
- Human Override is always valid.


## Execution Mode Gate

Every workflow must begin by explicitly declaring whether it is:
- LOCAL_ANALYSIS: 「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」
- REMOTE_EXECUTION: 「這個需要連伺服器/跑模擬。」

Mixed workflows must be split into phases and the mode must be re-declared at every phase transition.
Local static findings must never be described as runtime/simulation evidence.


## SSH/Remote Transport Connection Intake

When a workflow declares REMOTE_EXECUTION and requires SSH/network transport to a Linux DV server
(real server credentials are involved), first ask the user whether SSH/network transport should be
established this session. Do not assume or silently attempt a connection.

If the user confirms, request these required fields before attempting any connection:
- user account
- password
- vc machine name (e.g. vchost-a, vchost-b)
- ssh machine name (e.g. host-a, host-b)
- DV Agent's working path/directory on the Linux server

The password must never be written into any evidence block, gate payload, state file, log, or
long-term/native memory. It is used only at the moment of the actual interactive connection and must
never be persisted by the harness — consistent with Remote Control Mode below ("Never expose SSH
private keys or credentials to Web/App or long-term memory"). The other four fields (account, vc
machine name, ssh machine name, working path) may be recorded as connection evidence since they are
not secrets by themselves.


## Waveform Dump User Gate

Before any waveform-enabled simulation, ask the user to confirm dump scope and dump level/depth.
Prefer minimum sufficient waveform based on the current failure cone.
Do not silently default to full-chip/full-depth dumping.


## Simulation Observability Default

Normal simulation/regression defaults to FSDB OFF.
VIP trace/report may be enabled independently when supported by the current VIP/project.
Escalate to FSDB only when signal-level waveform evidence is needed.
FSDB enablement must pass the user-confirmed waveform scope/level gate.


## First-Failure Waveform Rerun

Initial simulation defaults to FSDB OFF.

If the simulation fails and signal-level evidence is required:
- rerun the failing testcase with targeted waveform enabled,
- confirm dump scope and level/depth,
- terminate at the first relevant failure/error/fatal/missing/mismatch,
- optionally retain only a minimal post-failure margin,
- do not run the full testcase unless later evidence is explicitly needed.

Regression-batch pipeline shape: push -> build -> verify -> run. The first pass runs the full batch
with FSDB OFF (per Simulation Observability Default). Only the subset of simulations that produced
a real UVM_ERROR or terminated abnormally (fatal/crash/timeout, not a clean UVM_FATAL-free PASS)
get selectively rerun with WAVE=1 (targeted waveform per First-Failure Waveform Rerun above) --
never blanket-rerun the whole batch with waveform on just because some tests failed.


## No Golden-Reference Content Mining

Forbidden methodology: "mine content from a completed reference environment -> have the generator
reproduce it -> verify it matches." This is not genuine generation, it is copying a finished answer
and relabeling the copy as if the harness had produced it from first principles. Even when a real,
locally-available reference environment exists (e.g. USB_UVM_Handoff) and even when the goal is
explicitly "100% parity" with it, protocol-behavior CONTENT — virtual sequence/pattern logic,
scoreboard checking logic, coverage bin/covergroup content, vPlan entries, command.txt scenario
content — must be derived from PRIMARY sources: VIP examples/user manual/source code/class
reference for branch-B/VIP-driven content, DUT RTL/PHY documents/programming guide for
branch-A/branch_fw-driven content (same sourcing already required by `vip-scenario-branch` and
`interrupt-event-dispatch` for any branch-B or branch-A/branch_fw modification — this rule makes
explicit that "modification" includes original content generation, not just edits to existing
files).

A completed reference environment may still be used AFTER independent generation, to measure and
report fidelity/gap (structural comparison, "how close did the independently-generated content
get") — that is legitimate verification, not generation. It must never be the source the generator
reads FROM to produce the content in the first place.


## Generated Content Language

Conversational replies to the user follow the user's own language preference (Traditional Chinese,
technical terms stay English). This is independent from generated deliverable content: all UVM
environment/testbench files, generator output, code comments, and any other artifact written into
the verification environment itself must be in English, regardless of what language the
conversation is conducted in.


## Remote Control Mode
Claude Web/App may control this local Claude Code session through Remote Control.
Remote Control is transport only; Harness governance remains authoritative.
Never expose SSH private keys or credentials to Web/App or long-term memory.


## Environment Generation Mode

Before CREATE ENVIRONMENT, select:
- SUBSYSTEM_MODE: build a protocol/subsystem environment.
- SYSTEM_LEVEL_MODE: select/reuse completed subsystem environments and compose Full-SoC/System-Level environment.

If a required subsystem is missing in SYSTEM_LEVEL_MODE, build it through SUBSYSTEM_MODE then return to composition.


## Methodology Consolidation Rule

A process/method/workflow used in a session is not "done" once it produces a result once.
It only counts as done once it has been consolidated into a permanent Harness asset so future
sessions get it automatically, without needing the user to re-explain it:

- A validated evidence-gathering/verification METHOD (e.g. how many agents, how to keep them
  blind, what counts as a real disagreement, how to resolve one) is consolidated into the
  relevant `.claude/skills/**/SKILL.md` file — with concrete mechanics and a worked real example,
  not a restated abstract mandate.
- A validated multi-phase ORCHESTRATION SHAPE (e.g. Parallel Evidence Gathering -> Consensus
  Synthesis -> Implement -> Re-verify) is consolidated into a reusable, parameterized script under
  `.claude/workflows/`, callable by name via the Workflow tool — not left as a one-off ad-hoc
  scratchpad script that only this conversation can re-run.
- A validated code-level capability (a new generator schema field, gate, check) is consolidated
  into the actual engine source under `dv_harness/`, with regression tests, exactly as already
  practiced this session — never left as a hand-edited one-off file outside the engine.
- After every consolidation: sync `.claude/` (skills + workflows) to the `industrial` and
  `PACKAGE` deliverable trees, same as any other engine change.

This rule itself is Human-Override-able like everything else, but by default applies with no
need for the user to ask for it every time.

This applies at every level, not only surface-level skills/workflows: an AI-architecture decision
(e.g. inference confidence scoring, memory-tier design, routing/dispatch semantics, iterative
reasoning-loop design) must land as real, wired, tested code inside `dv_harness/` — never stay as a
standalone module nothing in the real engine flow calls, and never stay as prose-only skill
guidance describing a desired mechanism an LLM subagent is merely trusted to enact each time. Per
[[dv_harness_poster_gap_reaudit_2026_08_29]] (verify this memory is still current before trusting
it), several past "done" claims at exactly this level (inference math, memory-tier stores, the
ReAct loop, route/skill resolution) turned out to be real-but-unwired or hardcoded/non-evidence-
driven — re-check wiring, not just existence, before declaring an AI-mechanism item complete.


## Engineering Discipline Rules (2026-08-29)

Cross-cutting rules that apply to every file modification, in addition to the domain-specific
mechanics already codified in `.claude/skills/CORE/*`:

- **Comment hygiene**: every file edit must also remove any comment/description in that file that
  is now outdated, redundant, or unrelated to the current content — never leave stale explanations
  behind as edits accumulate.
- **No overly abstract naming**: identifiers, files, signals, IDs must name the concrete real
  thing they represent (protocol/port/register/branch/purpose) — never a vague generic label a
  reader would have to guess the meaning of.
- **branch-B / VIP pattern changes**: query VIP examples, VIP user manual, VIP source code and
  class/API reference FIRST — already codified in `vip-scenario-branch` (do not invent VIP
  API/class/sequence by guessing).
- **branch-A / branch_fw changes**: query DUT RTL source, PHY documents and any programming
  guide/register documentation FIRST — already codified in `interrupt-event-dispatch`.
- **Event/control register hierarchy**: any RTL instance/signal hierarchy path for an event or
  control register must be verified against current RTL evidence, never assumed/reused from a
  stale path — already codified in `interrupt-event-dispatch` (`SOURCE_HIER` field).
- **Real FW pattern is interrupt-driven, not polling**: understand the trigger register/config,
  CPU WRITE task to arm it, then event-driven wait on the resulting interrupt — never periodic
  CPU READ-task polling as the primary detection mechanism — already codified in
  `interrupt-event-dispatch` ("CPU Task 層級實作模式").
- **Concurrent bus arbitration**: APB/AXI transactions that can execute concurrently across
  `block` / `branch_a0` / `branch_a1` / other `branch_a*` against a shared resource must have an
  explicit, RTL-evidence-based arbitration policy modeled — already codified in `branch-mapper`
  ("AMBA M×N Mapping"). Unrelated resources must stay independently parallel.
- **command.txt change-impact check**: every file/generator-schema modification must be checked
  against `.dv-workflow/command_inventory.csv` for which existing command.txt/scenario cases it
  could affect, and the affected set re-verified after the change — already codified in
  `command-inventory` ("Change-Impact Check").
- **Architecture-conformance audit**: every generated/modified environment and file must be
  checked against the current canonical naming architecture —
  `block + branch_a0/1/2/3... + branch_fw (supports parallel Port1/2/3...) + branch_b0/1/2/3...
  (VIPs)` — legacy/pre-v8 naming (non-underscore `branch_a{i}` forms, missing `branch_fw`,
  non-parallel-port assumptions) found during any review must be flagged and corrected, not
  silently left in place. Term semantics: `block` = SoC global initial tasks; `branch_a*` =
  DUT+PHY initial tasks, one parallel branch per DUT port; `branch_fw` = the FW service loop,
  one parallel branch per port; `branch_b*` = VIP-driven parallel tasks. Port numbering (whether
  a given DUT's ports start at 0 or at 1) must be verified against that DUT's actual RTL port
  numbering for the current project, never assumed from this doc's own `Port1/2/3` example
  text or copied from a prior project.
  `D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff` is the reference for how this
  block/branch_a/branch_fw/branch_b usage pattern is organized structurally — subject to the
  same "No Golden-Reference Content Mining" rule above: use it to check structural/organizational
  conformance, never as a source to mine protocol-behavior content from for a different project.
