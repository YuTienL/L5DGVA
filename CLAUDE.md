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


## Engineering Memory Policy (2026-09-03)

Concrete before/during/after mechanics for the 5-tier Memory system
(`dv_harness/memory.py`, routed by `dv_harness/memory_router.py`, mirrored
into the DV-Knowledge Vault by `dv_harness/memory_vault.py` -- see
`docs/MEMORY_ARCHITECTURE.md`). This operationalizes the Core Operating
Rules' "Memory is prior knowledge, not current evidence" and the Evidence
Truth Rule above; it does not restate them.

**Before debugging**: Search relevant Project Memory and Engineering Memory
for the current protocol/scope/symptom before forming a first hypothesis
(`python -m dv_harness.memory_cli search --protocol <p> --text <symptom>`,
or the `memory-retrieval` skill). Any hit is a candidate hypothesis to rank
higher, never an accepted root cause -- validate it against current
RTL/VIP/sim.log/waveform evidence exactly as the Evidence Truth Rule
requires, and as `memory-confidence-gate` keeps historical-memory
confidence and current root-cause-evidence confidence from being conflated
into one number.

**During debugging**: Maintain Hypothesis -> Evidence -> Confidence -> Gap ->
Next-Best-Action for every open failure (`dv_harness.inference.score_confidence()`
/ `identify_gap()` / `next_best_action()` -- see debug-agent.md's "v20
Autonomous Inference"). Each stage transition is a real, persisted Working
Memory record (`memory_router.route_memory()` routes `kind="react_reasoning_step"`
there), not only conversation state.

**After verified PASS**: Record root cause, evidence, fix, verification, and
confidence together as one Engineering Memory record (`kind` one of
`root_cause`/`verified_fix`/`debug_lesson`, `verified: true`), then evaluate
promotion:
- Engineering -> Organizational happens ONLY through
  `memory_router.promote_to_organizational()`, never a direct write. It
  requires all three: the qualitative CLOSED/VERIFIED + single PASS +
  regression PASS/NOT_REQUIRED + re-audit CLEAN gate (`memory-consolidation`
  skill), a HIGH `inference.score_confidence()` result, and
  `confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS` (2, i.e. a second
  independent run re-deriving the same root_cause/protocol -- not the same
  run reported twice).
- A record failing any one gate stays at Engineering tier (or lower). Do not
  re-word the qualitative gate's inputs to force a pass.

**Never**:
- Store secrets/passwords/tokens/credentials in any memory tier or vault
  note -- `memory_router.route_memory()` already hard-`REJECT`s any record
  whose `kind` is `credential`/`password`/`token`/`secret`; this is enforced
  code, not policy prose.
- Store giant logs or raw FSDB content in a memory record or vault note --
  cite a path/offset/signature only, per the Waveform Dump User Gate and
  Simulation Observability Default above.
- Promote an unverified hypothesis straight to Engineering or Organizational
  Memory -- it belongs in Working Memory (or Blackboard, for current-run
  state) until it clears verification.

**Debug-flow / regression / git-integration mechanics (2026-09-03,
obsidian-memory-debugflow, Workstream 3)**: `dv_harness.engine.DVHarness.
run_stage()`'s FAILURE_RECOVERY/RE_AUDIT stages, and `dv_harness.lsf_client
._write_job_tier_memory_on_terminal_reconcile()` (real UVM_ERROR/UVM_FATAL/
abnormal-termination signal), both call the same shared interface --
`dv_harness.memory_vault.build_failure_signature()` /
`search_related_memory_for_debug()` -- to surface Vault matches as prior
evidence BEFORE a debug attempt (never an assumed root cause: 不得直接假設
previous root cause == current root cause). AFTER a debug attempt: FAIL/
PARTIAL updates Job Memory only, no promotion; a RE_AUDIT PASS records
symptom/root_cause/evidence/fix/verification/confidence/git SHA/test/result
and always triggers (not always succeeds) the `promote_to_organizational()`
evaluation. Vault git commits (`memory.git_enabled`, opt-in) fire only on a
verified Job result, a Project Memory update, an Engineering Memory
promotion, or an Organizational Memory approval -- never on a Working Memory
update -- with message format `memory(<protocol>): <short description>`; a
real commit's SHA is written back onto the underlying JSON MemoryStore
record as `knowledge_commit_sha`, alongside its existing `rtl_sha`/`tb_sha`.
See `.work/obsidian-memory-debugflow-report.md` for full detail.


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


## Remote Linux Execution (Persistent Relay)

`remote_hop.py`, `remote_relay.py`, `remote_exec.py`, and `source_identity.py` live in
`tools/remote/` within this `v50` project (not at the repo/project root).

Once a Linux DV server session has been established this session per the SSH/Remote Transport
Connection Intake gate above (user confirmed, relay started by the user in their own terminal), do
not ask the user to manually run and paste back individual Linux commands. Use:

  python tools/remote/remote_exec.py "<command>"

Check readiness first with `python tools/remote/remote_exec.py --status`. If READY, issue commands
directly. If DOWN, run `python tools/remote/remote_exec.py --reconnect`; if that reports the relay
cannot self-reauthenticate, ask the user to restart it in their own terminal (never embed VCPW in
any Claude-issued command) and stop until they confirm it is back up.

This does not remove the SSH/Remote Transport Connection Intake gate itself — establishing or
re-establishing a relay for the first time in a session still requires that confirmation. It only
removes the per-command manual-paste fallback once a relay is already confirmed READY.

`remote_relay.py` (which actually performs the login) must never be invoked from a Claude Code tool
call, including to test its own error paths — not even when the invocation doesn't type a password
into the command text. A persistent OS-level environment variable can supply required credentials
silently, defeating a "missing env vars" safety check without any password ever appearing in the
command itself (confirmed real incident, 2026-08-31 — see
`remote-linux-execution-bridge/SKILL.md`'s corresponding drift note). Test `remote_relay.py`'s logic
via unit tests against its pure `RelayServer.handle_request()` function, never via a live `--start`.

**2026-09-03 amendment (explicit user decision, single-user machine)**: on this specific machine,
confirmed single-user by the project owner, the user has explicitly decided to relax the prohibition
above: when `remote_exec.py --status`/`--reconnect` reports the relay is down mid-session, Claude
Code MAY automatically source a local, never-committed credential script (e.g. `replay.csh`, kept
outside version control and outside any path Claude reads or echoes) and invoke
`remote_relay.py --start` to reconnect, without asking the user each time. This is a deliberate
override of the 2026-08-31 incident's original blanket prohibition — the user judged that a
single-user machine reduces credential-exposure risk enough to accept fully autonomous reconnect in
exchange for not being interrupted. This amendment covers only mid-session RECONNECTION; the
SSH/Remote Transport Connection Intake gate above (asking before the FIRST connection of a session)
is unchanged and still applies.

Even under this amendment:
1. The password itself must still never be printed, echoed, quoted, or written into any evidence
   block, log, gate payload, or memory record.
2. Claude may source and invoke the credential script, but must never read or print the script's
   own contents.
3. This amendment is scoped to this machine/project only. If this harness is ever deployed to a
   shared or multi-user environment, this decision must be explicitly re-confirmed before it still
   applies there.

Source identity (PC vs. Linux) is verified per-project: git SHA comparison where a git remote exists
between PC and Linux, or the md5sum-based `SOURCE_ID` token (`source_identity.py`, see
`remote-linux-execution-bridge`) where it does not — never skipped outright.

Never request or print passwords, tokens, or credentials in any `remote_exec.py` invocation or
output.


## Background Job/Log Monitor Auto-Start

There is no Python code path that fires automatically the moment
REMOTE_EXECUTION_REQUIRED is declared -- that declaration is agent-supplied
evidence (an `execution_mode_validator` block embedded in the agent's own
message text), not an engine event with a hookable call site. "Automatic"
here means the same thing it means for the SSH/Remote Transport Connection
Intake gate above: a required action the agent takes as part of following
this protocol, not something the engine does on its own.

Once REMOTE_EXECUTION_REQUIRED has been declared and any needed SSH/Remote
Transport Connection Intake has completed, run:

    dv-harness lsf-watch-start --vcuser <account>

before submitting or expecting visibility into any LSF job this session.
This starts (or confirms already-running) a detached background process
that discovers every live job under that account, reconciles/analyzes any
job this harness has a registered `JobState` for, and maintains the
`regression.list` safety net (see `apply_verdict_to_file()` in
`dv_harness/uvm_generator/regression_list_manager.py`) for jobs that bypass
the generated environment's own Makefile-native `RECORD=1` mechanism. It is
a no-op if a watcher is already running for this project (tracked via a PID
file). Stop it with `dv-harness lsf-watch-stop` on a clean session end, or
when execution mode transitions back to `PURE_LOCAL_READ_ANALYSIS`.


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


## gh CLI + PR-Only Governance Policy (2026-09-03)

L5 governance requirement: an agent (Claude Code or any other automated
caller) may `git branch` / `git commit` / open a PR (`gh pr create`), but
must **never merge or push directly into a protected branch** (`main` or
`master`). Human review via PR is the only path onto those branches. This
is additive to, not a replacement for, the existing git-safety language in
`CORE/git-push-gate` (secret/scope/diff/commit-message discipline before
any push) and `CORE/git-workflow` (the full SYNC->...->PUSH lifecycle,
including its own "禁止自動 force push" rule) -- this section adds the
specific main/master-protection rule those two skills did not yet state.

**Real current state of this repo (checked 2026-09-03, kept honest rather
than assumed)**: no GitHub remote is configured (`git remote -v` is empty)
and this session's own git history has been direct commits to a
local-only `master` branch the whole time -- there is no live PR workflow
to point at today. The policy and its enforcement below are written and
active regardless, so they are already in force the moment a real remote
(and GitHub branch-protection rules requiring PR review) is added.

**Layered enforcement**:
1. **Primary (once a remote exists): server-side branch protection** on
   `main`/`master` requiring PR review before merge, disallowing direct
   pushes. This is the authoritative gate -- it holds even if a local hook
   is missing or bypassed.
2. **Secondary (coded and tested, NOT YET INSTALLED as of 2026-09-03 --
   `git config --get core.hooksPath` returns nothing in this repo and
   neither hook file exists under `.git/hooks/`; run
   `git config core.hooksPath tools/git-hooks` to activate): local
   `tools/git-hooks/pre-push` and
   `tools/git-hooks/pre-merge-commit`**, backed by
   `dv_harness/git_governance.py` (`dv-harness git-guard`). These detect an
   AI-agent execution environment using the same env-marker pattern
   `tools/remote/remote_relay.py`'s own Layer 2 guard already established
   (`AI_AGENT_ENV_MARKERS`, reused via import -- not duplicated) and BLOCK
   (non-zero exit, which git treats as hook failure) a direct push/merge
   into `main`/`master` from that environment. A human pushing/merging from
   their own interactive terminal (no agent marker present) is never
   blocked by this gate -- see `tools/git-hooks/README.md` for install
   (`git config core.hooksPath tools/git-hooks`) and the deliberate
   fail-open behavior when Python is unavailable.

Every `git-guard` decision that touched a protected branch is logged as a
`GIT_GUARD_DECISION` event in `.dv-harness/events.jsonl` -- the same real
audit trail `dv-harness audit` already surfaces (see
`.claude/agents/audit-change-governance-agent.md`, the agent responsible
for reading this trail back and answering "what changed, by what/whom,
when, with what evidence, is it reversible" from real sources only).

`gh` (GitHub CLI) is the sanctioned tool for opening/inspecting PRs
(`gh pr create`, `gh pr view`, `gh pr checks`) once a remote exists. An
agent may run any read-only or PR-creating `gh`/`git` command freely; it
must never run `gh pr merge` (or an equivalent `git push`/`git merge`
straight onto `main`/`master`) itself -- that action is reserved for a
human, per this section's own rule and `git-guard`'s enforcement of it.


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
  `D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff` is the canonical structural template for
  DV Agent Harness L5's VIP-based verification environment generation, at both SUBSYSTEM_MODE
  and SYSTEM_LEVEL_MODE — subject to the same "No Golden-Reference Content Mining" rule above:
  use it to check structural/organizational conformance, never as a source to mine
  protocol-behavior content from for a different project.
  **Consolidation status (audited 2026-09-02, see MEM-7F2DCD9E83/MEM-53FCE2C191/MEM-1669464837
  for full evidence):** file structure, verification-environment composition (env/agent/scoreboard
  wiring), and VIP-examples grounding are real, code-consolidated assets in
  `dv_harness/uvm_generator/*.py` (20+ line-cited references) and
  `dv_harness/uvm_generator/templates/sim_scripts/` (a real, now chip-configured copy of
  `USB_UVM_Handoff/sim/scripts/`), enforced against direct golden-reference citation by the real
  `protocol_isolation_gate`. The command.txt/pattern content architecture gap (`block`/
  `branch_a`/`branch_fw`/`branch_b` task composition, fork/join semantics, named
  arbitration/ordering traps) was closed 2026-09-03: distilled, generalized (USB kept only
  as clearly-labeled illustration, never as vocabulary) into a new
  `.claude/skills/CORE/pattern-architecture/SKILL.md` — the five-layer shape, the
  join-vs-join_any rule and why the "every branch guaranteed to run forever" justification
  expires, six recurring trap classes, and what varies vs. stays fixed by test intent
  (see `.work/gap-close-command-txt-report.md`). `command-generator/SKILL.md` now
  cross-references it (which command IDs must exist vs. how a pattern's internal task
  composition must be built) rather than duplicating it. The Makefile/sim-scripts migration gap
  (2026-09-02 audit: 5 files never carried over) was closed 2026-09-03: `analyze_sim.sh`,
  `apb_timing_report.sh`, `dpdm_report.sh`, `irq_report.sh` (the latter three sharing one
  `fsdb_signal_report.sh` engine, per-question wrappers only) and `check/gen_scaledown.py` are
  now genericized templates in `dv_harness/uvm_generator/templates/sim_scripts/` (see
  `.work/gap-close-makefile-report.md`). The consolidated part of this directory still goes
  unused unless an agent is explicitly told to survey
  `dv_harness/uvm_generator/templates/sim_scripts/` before hand-authoring build infrastructure —
  citing one sibling file in this directory (as this document previously did for
  `regression_list_manager.py`) is not sufficient for a dispatched agent to discover the rest.
- **Non-USB topology variants (2026-09-01, UNTESTED placeholder guidance)**: the canonical
  `block/branch_a*/branch_fw/branch_b*` naming above was reverse-distilled from, and has only
  ever been validated against, USB. Two topology-shape variants have since been added as
  clearly-labeled, explicitly UNTESTED generic guidance for a future non-USB pilot to start
  from — neither has been validated end-to-end and neither changes any protocol's
  genericity_status from untested/structurally-incompatible to working: (1) a **simplex
  streaming `branch_fw` variant** (RX-only/TX-only DUT, e.g. MIPI CSI-2/DSI-shaped) in
  `interrupt-event-dispatch/SKILL.md` — "Simplex Streaming branch_fw Variant" section; (2) an
  **AMBA-as-primary-DUT master/slave redefinition** of `branch_a*`/`branch_b*` (fabric IS the
  DUT, not an overlay on top of pre-existing ports) in `branch-mapper/SKILL.md` — "AMBA-as-
  Primary-DUT Master/Slave Redefinition" section. A future agent building a non-USB environment
  (CSI-2/DSI, or an AMBA-fabric-as-DUT/`SYSTEM_LEVEL_MODE` environment) should read these
  sections first rather than starting from zero.


## Agent-Authored Change Accountability (2026-09-03)

Explicit, written policy so this is settled before it becomes a real incident, per the user's
own reasoning: without this stated up front, no human feels safe clicking Approve on an
agent-authored change, and the harness stays permanently stuck below L5 regardless of how good
its technical output is.

- **The agent is a tool, not an accountable party.** Claude Code (or any automated caller)
  proposes; it never bears responsibility for a merged/pushed change's consequences.
- **The human approver of a PR/merge carries the same responsibility as if they had authored the
  change by hand.** Approving an agent-authored PR is not a lower-scrutiny action than approving
  a colleague's PR — the approver is the accountable party for any escape that change causes,
  exactly as with any other PR they approve.
- This is why `gh CLI + PR-Only Governance Policy` above exists as a hard technical gate (agent
  proposes via PR, never merges/pushes to `main`/`master` directly): the accountability model
  above only works if there really is always a human decision point in between an agent's
  proposal and a protected branch. Removing or bypassing that gate would also remove the
  precondition this accountability policy depends on.
- This policy does not change any existing evidence/verification requirement in this file (the
  Evidence Truth Rule, stage-gate checklists, etc.) — those still apply in full before a change
  reaches PR stage. It only settles the separate question of who is accountable once a human
  clicks Approve.


## Trust Progression for Autonomous/Semi-Autonomous Work (2026-09-03)

Real-world adoption should climb by task risk, not jump straight to the riskiest category:

1. **Start with near-zero-risk tasks**: log/failure triage, report generation, coverage
   summarization. A wrong output here costs a few minutes of a human's attention, not a bad
   tapeout decision.
2. **Only after a track record accumulates on tier 1** (accuracy data the team has actually
   looked at, not an assumption) should autonomy extend toward stimulus/pattern modification —
   the tier where a wrong output can silently produce a false PASS.
3. This is a recommended adoption ordering for the humans operating this harness, not a
   mechanically enforced gate in the engine — record it here so it is a deliberate team decision
   each time scope expands, not a default that happens by not thinking about it.

**Deliberately preserved knowledge asymmetry**: as this harness gets better at autonomous
debug, new engineers get fewer chances to debug a real failure by hand — which is a genuine
long-term cost to the team's own capability, not merely a short-term efficiency tradeoff. Teams
adopting this harness should deliberately route some fraction of real failures to a human for
hands-on debug rather than letting the harness resolve every one it technically could, treating
this as an investment in the team's future capability rather than lost efficiency today.
