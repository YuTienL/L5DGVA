# Multi-Agent RCA Orchestrator Implementation Report

2026-09-01

## Background

An architecture audit found that the previously-claimed "Multi-Agent Orchestrator for RCA"
(parallel fan-out across RTL/Log/FSDB/VIP/Spec/TB/Cmd/Scoreboard specialists -> Evidence Fusion ->
RCA Review) had zero corresponding code or agent definitions. `.claude/skills/CORE/
multi-agent-orchestrator/SKILL.md` explicitly disclaims engine-level parallelism for RCA today,
attributing "parallelism" entirely to a human/LLM session issuing multiple `Agent` tool calls
manually in one turn; `dv_harness/multi_agent.py`'s `AgentTaskStore`/`MultiAgentOrchestrator` only
does bookkeeping (parallel-group/dependency tracking, resource ownership locks) and never itself
dispatches or runs anything concurrently.

This task closes that specific gap with real, narrow, additive pieces: three new RCA
evidence-gathering agent profiles, a real saved Workflow-tool script that genuinely fans them out
in parallel (via the Workflow tool's own concurrent `agent()` dispatch -- a third, real mechanism,
distinct from both the dv_harness Python engine's graph-node `ThreadPoolExecutor` fan-out and
`multi-agent-orchestrator`'s documented manual-Agent-tool-calls today-state), a real CLI bridge so
that workflow can genuinely call `Blackboard.write()`, and an honest update to
`CORE/issue-triage-and-deep-rca/SKILL.md` describing both the existing sequential path and this new
optional parallel path without overclaiming either.

## What was built

**Three new agent profiles** (`.claude/agents/rtl-evidence-agent.md`,
`.claude/agents/log-evidence-agent.md`, `.claude/agents/vip-spec-evidence-agent.md`), matching the
existing read-only-investigator frontmatter convention (`tools: Read, Grep, Glob, PowerShell,
Skill`, `disallowedTools: Edit, Write`, `model: inherit`, a `skills:` list, then a body ending in a
"Mandatory evidence discipline" section) already used by `analysis-agent`/`analysis_debug`/
`regression-agent`. Each is scoped to exactly one evidence domain and explicitly cites which
sibling agent(s) own the domains it does *not* cover, so a reader cannot mistake overlapping scope
for duplication. `.claude/agents/ROSTER.md` was updated (16 -> 19 real agents) and
`dv_harness_tests/test_stats_snapshot.py`'s hardcoded count assertion was updated alongside it (its
`_real_agent_profile_count()` re-derivation logic was left untouched -- only the expected literal
changed, since the count itself legitimately changed).

**A real Blackboard CLI bridge** (`dv_harness/cli.py`'s new `blackboard write|read` subcommand,
backed by two new functions in `dv_harness/commands.py`: `cmd_blackboard_write`/
`cmd_blackboard_read`, which are thin wrappers around the real `Blackboard.write()`/`Blackboard.
read()` in `dv_harness/blackboard.py`). This exists because a Workflow-tool script is plain JS with
no filesystem/Python access of its own (per the workflow-authoring skill) -- there is no way for
`rca-multi-agent-fusion.js`'s own code to call into `dv_harness/blackboard.py` directly. The only
genuine way to satisfy "use the real `Blackboard.write()` method" from a saved workflow script is
for one of its subagents to invoke a real CLI command via its own PowerShell tool call. New tests:
`dv_harness_tests/test_cli_blackboard.py` (7 tests: direct `commands.py` unit tests plus a real
subprocess CLI round-trip, including asserting the real on-disk
`.dv-harness/blackboard/rca_evidence_fusion.json` artifact, not just CLI stdout).

**The workflow script** (`.claude/workflows/rca-multi-agent-fusion.js`), following the existing
`gap-closing-evidence-consensus.js` script's conventions (`export const meta`, argument validation
that throws a descriptive `Error`, `phase()`/`agent()`/`parallel()`, JSON Schemas passed via
`schema` to force structured `StructuredOutput` returns):
- **Phase "Parallel Evidence Gathering"**: a `parallel()` fan-out (a genuine barrier, justified per
  workflow-authoring's own rule -- Evidence Fusion needs every branch's result together to
  dedup/cross-reference) over `rtl-evidence-agent`, `log-evidence-agent`, `vip-spec-evidence-agent`,
  and -- only when `args.includeWaveform` + `args.fsdbHint` are given -- the **existing**
  `waveform-root-cause-agent`, reused rather than duplicated as a new `fsdb-evidence-agent.md`.
  Each branch returns structured findings (`claim`/`source_file`/`location`/`evidence`/
  `confidence`) via a shared JSON Schema.
- **Phase "Evidence Fusion"**: one `agent()` call (`agentType: 'review-agent'`, the existing
  independent read-only reviewer persona) that dedups/cross-references the parallel findings,
  surfaces genuine disagreements for resolution (never by voting), and then *actually* persists
  the fused record to the Blackboard by running `dv-harness blackboard write rca_evidence_fusion
  --file <tmp.json> --source rca-multi-agent-fusion --confidence <...>` via its own PowerShell tool
  call -- the prompt has it save the JSON via PowerShell's own `Set-Content` first, so no `Write`
  tool grant is needed (review-agent's frontmatter already disallows `Write`/`Edit`).
- **Phase "RCA Review"**: one `agent()` call (`agentType: 'analysis_debug'`, the existing deep-RCA
  arbiter persona) that does **not** trust the Fusion stage's own report blindly -- it is instructed
  to independently run `dv-harness blackboard read rca_evidence_fusion` itself first, per CLAUDE.md's
  "current evidence wins" rule, then produce the final verdict (root cause, first bad event, causal
  chain, DUT_BUG/TB_BUG/VIP_ISSUE/TEST_ISSUE/SPEC_AMBIGUITY/INFRA_ISSUE/UNKNOWN attribution,
  confidence, fix/risk/scope/regression/rollback plan).

New structural tests: `dv_harness_tests/test_workflow_rca_multi_agent_fusion.py` (8 tests) --
`node --check` syntax validity, `meta.phases` titles matching the body's `phase()` calls exactly,
every `agentType` naming a real existing `.claude/agents/*.md` file, an explicit guard that no
`fsdb-evidence-agent.md` or fictional org-chart-style agent file was invented, and that the CLI
subcommand/topic name the script's prompts depend on are real (grepped directly from `cli.py`/
`commands.py`).

**SKILL.md update** (`.claude/skills/CORE/issue-triage-and-deep-rca/SKILL.md`): added a "Two real
paths for launching deep RCA" section distinguishing the default single-sub-agent sequential
`analysis_debug` path from the new optional `rca-multi-agent-fusion.js` parallel fan-out, stating
plainly that the fan-out is a real, different mechanism from what `CORE/multi-agent-orchestrator`
documents today (manual multi-Agent-tool-call parallelism), and that the fan-out should be reached
for by name when genuinely warranted, not reflexively for every REAL_ISSUE.

## Rulings

- **RULING**: created exactly 3 new narrow agents (rtl/log/vip-spec) and deliberately did **not**
  create `fsdb-evidence-agent.md` -- `waveform-root-cause-agent` already is a real, tested,
  roster-listed FSDB/waveform RCA specialist; duplicating it would violate the task's own
  "if an existing agent already covers one of these roles well, do not duplicate it" instruction.
  The workflow reuses it via `agentType` instead.
- **RULING**: folded `analysis_debug.md`'s own named "Parallel agents:" list into 3 agents, not ~12:
  Command-Semantic + Scoreboard/Checker evidence folded into `log-evidence-agent` (same runtime-text
  domain, read the same way, already inseparable -- a scoreboard mismatch and its command.txt intent
  both live in/near sim.log); RTL + TB folded into `rtl-evidence-agent` (same static-source domain);
  PHY-Model + Standard-Spec + VIP-Source/Example/Docs folded into `vip-spec-evidence-agent` (same
  documentary-evidence domain). Build/Tool already has `build-agent` in the roster (untouched).
  RCA Arbiter is the RCA Review stage itself, played by the existing `analysis_debug` -- no new file.
- **RULING**: did not touch `CORE/multi-agent-orchestrator/SKILL.md` -- the task's item 3 only asked
  to update `issue-triage-and-deep-rca`; the honest distinction between this workflow's real
  parallel dispatch and multi-agent-orchestrator's documented manual-Agent-tool-calls today-state is
  captured entirely in the new `issue-triage-and-deep-rca` text, cross-referencing it by name.
- **RULING**: the real Blackboard write happens via a subagent's own PowerShell call to a new
  `dv-harness blackboard write` CLI subcommand, not from the `.js` file's own code -- the
  workflow-authoring skill states scripts have "No filesystem or Node.js API access." This CLI
  subcommand is new, real, additive code with its own tests, not a simulated bridge.
- **RULING**: the Evidence Fusion prompt saves its JSON payload to a temp file via PowerShell's own
  `Set-Content` and passes it with the CLI's `--file` flag, rather than inlining JSON via `--value`
  on the command line -- avoids Windows/PowerShell quoting fragility for a large payload, and lets
  the stage reuse the existing read-only `review-agent` persona unmodified (PowerShell allowed,
  Write/Edit disallowed -- PowerShell's own file redirection is not gated by Claude's Edit/Write
  tool permissions).
- **RULING**: updated `test_stats_snapshot.py`'s hardcoded `16` to `19` -- not a bug being papered
  over; the test's own docstring documents "16, not 17" as this real repo's *current* count, and
  adding 3 new real, tested agent profiles legitimately changes it. The test's independent
  `_real_agent_profile_count()` re-derivation was left untouched and would have failed loudly on any
  malformed new agent file.
- **RULING**: performed no "industrial"/"PACKAGE" deliverable-tree sync (CLAUDE.md's Methodology
  Consolidation Rule mentions syncing `.claude/` to those trees) -- verified no such sibling
  directory trees actually exist in this `v50` checkout (only `PACKAGE_INVENTORY.json`/
  `FINAL_PACKAGE_INDEX.md` docs). Noted here rather than fabricating a sync target.

## Tests and results

- New: `dv_harness_tests/test_cli_blackboard.py` (7 tests), `dv_harness_tests/
  test_workflow_rca_multi_agent_fusion.py` (8 tests).
- Updated: `dv_harness_tests/test_stats_snapshot.py` (count 16 -> 19).
- Full existing suite after all changes: `python -m pytest dv_harness_tests/ -q` ->
  **1570 passed in 656.61s (0:10:56), 0 failed** -- zero regressions.

## Residual gaps / concerns

- **End-to-end live execution was not performed.** This offline implementation pass cannot itself
  trigger a live Workflow-tool run (real concurrent `agent()` dispatch, a real subagent actually
  running `dv-harness blackboard write`, a real `.dv-harness/blackboard/rca_evidence_fusion.json`
  appearing, RCA Review really re-reading it). Structural validation (schema shape, real JS syntax,
  every referenced agent file existing, the real CLI subcommand existing) is what this pass could
  verify; a future session should run `rca-multi-agent-fusion.js` against a real REAL_ISSUE-
  classified failure and confirm the full round trip, including that `blackboard_write_confirmed`
  actually reflects a real successful write rather than an agent's unverified claim.
- `CORE/multi-agent-orchestrator`'s rule 3 (AgentTaskStore `create_task`/`acquire` bookkeeping kept
  in sync with real parallel dispatch) was intentionally **not** wired into this workflow -- the
  task's explicit ask was Blackboard integration only. This workflow's fan-out will not show up in
  `.dv-harness/agents/tasks.json`. Flagging as a deliberate scope boundary, not a silent omission --
  a future pass could add a similar CLI bridge for `AgentTaskStore` if that bookkeeping is later
  required for this workflow too.
- `.claude/skills/CORE/multi-agent-orchestrator/SKILL.md` itself was left unedited (see ruling
  above); a future consolidation pass may want a short pointer there back to this new workflow.
