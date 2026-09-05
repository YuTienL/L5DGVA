export const meta = {
  name: 'ai-engine-audit-and-close',
  description: 'Re-audit all 14 AI mechanisms (incl. generic multi-protocol scope + subsystem-to-SoC generation) with CURRENT real evidence, build the stage-progress/logo/checklist/report display feature, then close every confirmed gap for real',
  phases: [
    { title: 'Audit+Build', detail: '14 mechanism audits + progress-display feature, in parallel' },
    { title: 'Close', detail: 'sequential fix pass over every confirmed real, in-scope gap' },
    { title: 'Review', detail: 'independent verification each closed gap is really closed' },
  ],
}

const AUDIT_RULES = `
You are re-auditing ONE AI mechanism inside DV Agent Harness L5, with CURRENT
real evidence -- a similar audit was done earlier in this session and found
several real gaps (Autonomous Inference Engine never fired in production
despite real math existing; Route Resolver was static per-graph-node lookup,
not evidence-driven; Job/Project/Organizational Memory tiers were dormant;
RCA Multi-Agent Orchestrator was never run end-to-end). A LOT of new work has
landed in this repo since that audit (a large Memory Integration effort,
Production-Grade Execution Governance, real evidence_db wiring into the
reconciliation cycle, the MCP+question-queue+connectivity system, exemptions,
dry-run/checkpoint/degradation). Your job is to determine, with real
evidence, whether THIS mechanism's status has actually changed -- do not
assume the old finding still holds, and do not assume it's been fixed either.

Required verdict format, one of:
- WIRED_AND_FIRING: real evidence the mechanism executes as part of the
  actual production stage flow (a real log line, a real persisted record it
  wrote, a real code path with no bypass) -- not just "the function exists
  and has unit tests".
- PARTIALLY_WIRED: real code exists and is technically reachable, but with a
  specific, named condition under which it's skipped/bypassed/never reached
  in practice.
- DORMANT: real code exists, is never called from any real production path
  (grep confirms zero real callers outside its own tests).
- NEVER_BUILT: no real implementation exists at all for this mechanism.

Evidence standard: cite real file:line, run a real command yourself and show
its real output, or grep for real callers -- never assert a verdict from
memory or from this prompt's own framing. If your finding differs from the
prior audit's framing above, say so explicitly and say why.

If you find a real, confirmed gap (PARTIALLY_WIRED or DORMANT, not a
NEVER_BUILT-and-genuinely-out-of-scope case), describe EXACTLY what a fix
would need to do to close it -- concrete file(s), concrete function(s) to
add/change, concrete verification method -- so a separate fix pass can act on
your finding without re-investigating from scratch.

Do not fix anything yourself. Do not modify any file. This is audit only.
`

phase('Audit+Build')

const auditInference = agent(`${AUDIT_RULES}

## Your mechanism: #1 Autonomous Inference Engine

dv_harness/inference.py's score_confidence()/identify_gap()/next_best_action() -- real math, confirmed tested in isolation by the prior audit. The prior finding: never fired in production because the RE_AUDIT stage was never reached in the sessions examined; what actually fires is a flat single-hypothesis pattern in WM-REACT-*.json records instead.

Check: (1) grep dv_harness/engine.py and dv_harness/react_loop.py for real call sites of these 3 functions -- are they called from the real stage-transition code path today? (2) Look at real, current .dv-harness/react/ or working-memory records (if any exist in this project or a recently-generated one) for evidence of actual multi-hypothesis confidence scoring vs a flat pattern. (3) Check whether any of today's new work (question_queue.py's tier classification, connectivity.py's T1-T4 confidence tiers) represents a PARALLEL confidence-scoring mechanism that was built without ever calling into inference.py's real functions -- this would be a real, notable finding if true (reinventing a wheel that already existed, real evidence of the reference_pattern lesson from earlier this session applying to the Harness's own development, not just the USB build).

Report your verdict per the required format.`, {label: 'audit:inference', phase: 'Audit+Build'})

const auditGraph = agent(`${AUDIT_RULES}

## Your mechanism: #2 Graph Orchestrator

main_graph.json-driven stage sequencing inside dv_harness/engine.py's run_stage()/loop(). The prior audit confirmed this WIRED_AND_FIRING.

Check: is this still true given today's changes (dry-run mode, auto-checkpoint, DEGRADED mode all touched run_stage()/loop())? Specifically confirm the graph-driven stage transition logic itself (reading main_graph.json, computing the next stage from gate verdicts) is unchanged in its real firing behavior, and that dry-run/degraded modes correctly wrap around it rather than bypassing or duplicating it. Run a real check if you can (e.g. python -m dv_harness.cli status against a real or synthetic project state).

Report your verdict per the required format.`, {label: 'audit:graph', phase: 'Audit+Build'})

const auditMultiAgent = agent(`${AUDIT_RULES}

## Your mechanism: #3 Multi-Agent Orchestrator

The RCA/evidence-acquisition multi-agent fan-out mechanism CLAUDE.md's own Core Operating Rules require ("Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent synthesis"). The prior audit found this confirmed never run end-to-end in the sessions examined at that time.

Check: has this actually been exercised for real since then? This session's own work today (the many Workflow-tool dispatches, the 4-agent MCP/question-queue/env-manifest/bind-connectivity effort, the gap-closing efforts) ARE real multi-agent evidence-acquisition-plus-synthesis patterns -- but determine whether these are: (a) the SAME mechanism CLAUDE.md's rule refers to (i.e. does dv_harness/engine.py itself have code that dispatches a multi-agent RCA fan-out as part of its own stage flow), or (b) a structurally different thing (this coordinating Claude Code session's own ad hoc Workflow-tool usage, outside dv_harness's own engine code entirely). This distinction matters -- CLAUDE.md's rule is about the HARNESS having this capability built in, not about the coordinating session happening to use multi-agent patterns manually.

Report your verdict per the required format, and be explicit about which of (a)/(b) you found.`, {label: 'audit:multiagent', phase: 'Audit+Build'})

const auditRouter = agent(`${AUDIT_RULES}

## Your mechanism: #4 Route & Skill Resolver

The prior audit found this was a STATIC per-graph-node lookup, not dynamic evidence-driven resolution.

Check: is this still the current real behavior? Grep dv_harness/engine.py (and wherever skill/route resolution actually lives) for the resolution logic. Does today's new question_queue.py (owner routing: vip->DV-owner/Synopsys-AE, dut->designer, env->DV-owner) or connectivity.py's tier classification represent a MORE dynamic, evidence-driven resolution pattern that could inform what "dynamic" should look like here, or are they unrelated? Determine concretely: given the same evidence, could this resolver currently select a DIFFERENT skill/route than a static per-node table would predict? If not, it's still static.

Report your verdict per the required format.`, {label: 'audit:router', phase: 'Audit+Build'})

const auditReact = agent(`${AUDIT_RULES}

## Your mechanism: #5 Plan-and-Execute / ReAct Engine

dv_harness/react_loop.py. The prior audit found real WM-REACT-*.json records showing a flat single-hypothesis pattern, not genuine iterative reasoning.

Check: pull any real, current WM-REACT-*.json or working-memory records that exist in this project (or a recently-generated one, e.g. from today's USB build agent's own investigation if it left any harness-tracked working-memory records, or from this session's own dv_harness usage) and examine their actual shape. Does the real content show genuine Hypothesis->Evidence->Confidence->Gap->Next-Best-Action iteration (per CLAUDE.md's Engineering Memory Policy section, which explicitly requires this), or still a flat pattern? Cross-reference against dv_harness/inference.py's real functions (same as audit #1 -- coordinate findings, you're auditing the same underlying gap from a different angle).

Report your verdict per the required format.`, {label: 'audit:react', phase: 'Audit+Build'})

const auditBlackboard = agent(`${AUDIT_RULES}

## Your mechanism: #6 Blackboard / Evidence Engine

dv_harness/blackboard.py. The prior audit confirmed this WIRED_AND_FIRING with real evidence.

Check: is this still true given today's very heavy concurrent usage (many Workflow runs, the MCP server's get_topology verb reading config_db traces, connectivity.py's config_db event parsing)? Confirm real Blackboard.write()/read() calls still happen from real stage evidence (not from any of today's new code accidentally bypassing it), and check whether today's new systems (question_queue, connectivity, env_manifest) SHOULD be writing to the Blackboard for current-run truth per CLAUDE.md's own Core Operating Rule ("Blackboard stores current verification truth") but currently don't -- if so, that's a real, notable gap worth flagging even though the original Blackboard mechanism itself is fine.

Report your verdict per the required format.`, {label: 'audit:blackboard', phase: 'Audit+Build'})

const auditMemory = agent(`${AUDIT_RULES}

## Your mechanism: #7 5-Level Memory Engine

dv_harness/memory.py (5 tiers), routed by memory_router.py. The prior audit found Job/Project/Organizational Memory tiers DORMANT (0-1 seed records). This is the mechanism most likely to have genuinely changed given today's work: a full Obsidian+Git/Markdown Hybrid Memory Integration effort landed earlier this session (memory_vault.py, memory_dedup.py, memory_doctor.py, promote_to_organizational()), and TODAY specifically: real evidence_db wiring into the reconciliation cycle, multiple real KC-persisted lessons from this session's own gap-closing work (grep .dv-harness/memory/ for real, current record counts per tier).

Check: run 'python -m dv_harness.cli memory status' (or the real equivalent command) for real, current tier populations. Count real files under .dv-harness/memory/{engineering,project,organizational,job}/ (or wherever each tier actually persists) RIGHT NOW. Is Organizational Memory still at 0-1, or has promote_to_organizational()'s 3-gate requirement (qualitative CLOSED/VERIFIED + HIGH confidence + confirmation_count>=2) actually been satisfied by anything real yet? Job Memory specifically should be checked against today's real evidence_db-wiring work, which touches job-state persistence.

Report your verdict per the required format -- this one especially needs real current numbers, not the old audit's numbers repeated.`, {label: 'audit:memory', phase: 'Audit+Build'})

const auditSignoff = agent(`${AUDIT_RULES}

## Your mechanism: #8 Qualification / Signoff Engine

dv_harness/gates.py's signoff-related gates, dv_harness/vplan_writer.py, dv_harness/signoff_export.py.

Check: has this ever been exercised for real, end-to-end, against a real or realistic project state? Run 'python -m dv_harness.cli signoff-export' (or the real equivalent) against a synthetic/test project and confirm it produces a real, openable output. Check gates.py for the real signoff-stage gate logic and whether it's ever been satisfied (PASSED) by a real stage transition in this project's own .dv-harness/ state, or only in isolated unit tests.

Report your verdict per the required format.`, {label: 'audit:signoff', phase: 'Audit+Build'})

const auditEvidenceGrounded = agent(`${AUDIT_RULES}

## Your mechanism: Evidence-Grounded AI (Hypothesis + Evidence + Execution result + Hard Gate = Qualified Conclusion)

User's own framing (authoritative): "AI Opinion != Verification Fact. Only Hypothesis + Evidence + Execution result + Hard Gate = Qualified Conclusion can enter closure." This is related to but DISTINCT from the Blackboard/Evidence-storage mechanism (audited separately) and from the Autonomous Inference Engine's confidence math (audited separately) -- this one is about whether there is a real, enforced INVARIANT that a stage/closure conclusion cannot advance past a gate without all four of {hypothesis, evidence, execution result, hard gate} present, not just whether evidence gets stored somewhere.

Check: grep dv_harness/gates.py's STAGE_GATES and gate-evaluation logic -- does a gate's PASS verdict actually require real evidence artifacts to be present and cited (not just "gate ran"), and does the code structurally prevent a conclusion from reaching CLOSED/signoff without a real execution result backing it? Or is this currently only prose in CLAUDE.md's Evidence Truth Rule section, trusted to an LLM subagent to follow each time rather than mechanically enforced? Be concrete about which stage-gates (if any) actually check for evidence-completeness in code vs. which just check a boolean "ran" flag.

Report your verdict per the required format.`, {label: 'audit:evidence-grounded', phase: 'Audit+Build'})

const auditAgentRoles = agent(`${AUDIT_RULES}

## Your mechanism: The 7 Expert Agent roles

User's own exact list (authoritative): PM Agent (task decomposition/progress/dependency/workflow control), Architect Agent (DUT/TB/protocol architecture), Developer Agent (RTL/UVM/script/code changes), Verification Agent (vPlan/test/checker/coverage), Regression Agent (simulation/LSF/job/result), QA & Closure Agent (qualification/signoff/evidence completeness), Knowledge Agent (Spec/VIP/reference/history/experience).

Check: do these 7 roles exist as real, distinct, dispatchable entities in this codebase (e.g. real files under .claude/agents/ with these responsibilities, or a real role-dispatch table in dv_harness/engine.py that routes work to a named role), or is this currently an informal conceptual grouping in CLAUDE.md/docs prose with no 1:1 code mapping -- i.e. does the SAME underlying code (e.g. one generic Claude Code session or one IP_UVM_DV_Gen agent) actually perform all 7 roles' work without any real separation enforcing "PM Agent doesn't touch RTL, Developer Agent doesn't decide qualification"? List, role by role, what real artifact (if any) backs each one.

Report your verdict per the required format, once per role if verdicts differ across roles.`, {label: 'audit:agent-roles', phase: 'Audit+Build'})

const auditSessionRestore = agent(`${AUDIT_RULES}

## Your mechanism: Session Save / Restore

User's own exact required-field list (authoritative), a session snapshot should preserve: Graph state, Blackboard, Plan, Hypotheses, Confidence, Evidence IDs, Git SHA, DUT version, TB version, command.txt, simulation seed, environment, LSF jobs, FSDB references, coverage, pending actions.

Check dv_harness/session_snapshot.py (gained retention pruning earlier this session per project history) -- read its real save() and restore()/load() functions. For EACH field in the user's list above, determine concretely: is it actually captured on save and actually restorable, or missing? Run a real save-then-restore round-trip yourself against a real or synthetic project state if possible, and report which of the listed fields survive the round trip and which don't.

Report your verdict per the required format, with a field-by-field checklist (present/missing) as supporting evidence.`, {label: 'audit:session-restore', phase: 'Audit+Build'})

const auditDebugLoop = agent(`${AUDIT_RULES}

## Your mechanism: AI Debug Closed Loop

User's own exact flow (authoritative): PC Claude -> Analyze/Fix -> Git Push -> Telnet vchost-b -> SSH host-b -> Linux Path -> Sync -> Build -> Single Simulation -> TRUE PASS? If NO: Health Monitor/Failure Triage -> Multi-Agent RCA (sim.log + trace + RTL + TB + command.txt + Spec + VIP) -> need FSDB? -> if yes: WAVE=1, time=0, stop=failure_time+200us -> fsdbreport -> Evidence Fusion -> PC Fix -> Push -> (loop). If YES: Regression -> Coverage -> Closure -> Signoff.

Check: is this ENTIRE loop actually driven autonomously by dv_harness's own engine code end-to-end (a real code path that goes from a build failure through RCA through fix through re-push through regression without a human manually re-invoking each step), or is what actually happens today a HUMAN-ORCHESTRATED version of this same shape -- i.e. a person (via a Claude Code session) manually approving/triggering each step, as literally happened in this exact session's own live USB TCA-hang investigation (a human explicitly approved every register-write/spine-adjacent decision across many rounds via AskUserQuestion, rather than dv_harness's engine autonomously looping through Build->Sim->RCA->Fix->Push on its own)? This distinction matters a great deal for an honest verdict. Also check specifically: does dv_harness/engine.py or any real code actually implement the FSDB-conditional branch (WAVE=1, stop=failure_time+200us) as an automatic decision, or is this manual today per the project's own "Waveform Dump User Gate" CLAUDE.md rule (which requires asking the user before any waveform-enabled simulation -- note this may be in TENSION with a fully-autonomous closed loop, worth flagging explicitly)?

Report your verdict per the required format, and be explicit about autonomous-vs-human-orchestrated for each major branch of the loop.`, {label: 'audit:debug-loop', phase: 'Audit+Build'})

const auditGenericProtocol = agent(`${AUDIT_RULES}

## Your mechanism: Generic (multi-protocol) DV Harness scope, not USB-only

User's own exact required protocol scope (authoritative), organized as a tree:
- USB Host: USB2 HS/FS, USB3 Gen1/Gen2
- USB Device: USB2 HS/FS, USB3 Gen1/Gen2
- PCIe: Gen2/3/4/5/6
- MIPI: CSI-2, DSI
- Ethernet
- CAN-FD
- AMBA4 SoC: APB, AHB/AHB-Lite, AXI3, AXI4, ACE-Lite, AXI-Stream

This is a request to ANALYZE (not build) how close DV Agent Harness L5 is to being genuinely protocol-generic today, vs. USB-specific. Check concretely, protocol-family by protocol-family:
1. Grep dv_harness/ core modules (engine.py, connectivity.py, reference_pattern_audit.py, reg_write_safety.py, address_map_verifier.py, gates.py, the uvm_generator/ package) for hardcoded "usb"/"USB" literals vs real parameterization (TARGET_IP/IP_PREFIX, protocol-agnostic function names/logic). Cite real counts and real file:line examples of both.
2. Check CLAUDE.md's own "Non-USB topology variants" section (search for it) -- it documents 2 UNTESTED placeholder generalizations (a simplex streaming branch_fw variant for MIPI CSI-2/DSI-shaped DUTs, and an AMBA-as-primary-DUT master/slave redefinition) -- confirm these are real text and assess honestly whether either has ever been exercised against a real non-USB DUT (the answer is very likely no -- confirm rather than assume).
3. For EACH of the 7 protocol families in the user's list above (USB Host, USB Device, PCIe, MIPI CSI-2, MIPI DSI, Ethernet, CAN-FD, AMBA4-as-primary-DUT), give an honest verdict: GENERIC_READY (the harness's real code already handles this with no protocol-specific rework needed) / PARTIALLY_GENERIC (some real parameterization exists but real gaps remain -- name them) / UNTESTED_PLACEHOLDER (only doc-level guidance exists, never exercised) / USB_ONLY (no real path exists at all).
4. This is explicitly OUT OF SCOPE for a same-pass fix -- becoming genuinely multi-protocol across 7 families is a large architectural effort. Do not attempt to build multi-protocol support. Your job is ONLY to produce an honest, evidence-based current-state map, and a concrete recommendation for what a bounded first non-USB pilot protocol should be (which of the 7 is closest to GENERIC_READY today) so a future scoped design effort has a real starting point.

Report your verdict per the required format (use PARTIALLY_WIRED as the overall bucket if the answer is "some real generic scaffolding exists but no protocol has actually been proven end-to-end"), with the full 7-family table as supporting evidence.`, {label: 'audit:generic-protocol', phase: 'Audit+Build'})

const auditSubsystemToSoc = agent(`${AUDIT_RULES}

## Your mechanism: Subsystem Verification -> System-Level / SoC Verification generation

CLAUDE.md already documents an "Environment Generation Mode" section requiring a SUBSYSTEM_MODE vs SYSTEM_LEVEL_MODE choice before CREATE ENVIRONMENT, with SYSTEM_LEVEL_MODE described as "select/reuse completed subsystem environments and compose Full-SoC/System-Level environment" (and falling back to building a missing subsystem via SUBSYSTEM_MODE first). This is a request to analyze whether this is real, working capability or aspirational doc text.

Check: (1) grep dv_harness/ for any real code implementing SYSTEM_LEVEL_MODE composition (selecting multiple completed subsystem environments and generating a combined system-level/SoC testbench around them) -- is there a real generator path for this, or does uvm_generator/ only ever emit single-IP/single-subsystem environments today? (2) Has SYSTEM_LEVEL_MODE ever actually been exercised for real (a real generated system-level environment exists somewhere, even partial), or does every real generated environment in this project's history (including the live usb31_dev_uvm build) use SUBSYSTEM_MODE only? (3) What would be structurally required to close this gap for real (e.g. a system-level topology descriptor combining multiple env_manifest.json files, a system-level scoreboard/checker composition strategy, multi-IP regression orchestration) -- describe concretely without attempting to build it (this is architectural scope, not a same-pass fix).

Report your verdict per the required format.`, {label: 'audit:subsystem-to-soc', phase: 'Audit+Build'})

const progressDisplay = agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Your task: build the stage-progress/logo/checklist/report display feature for DV Agent Harness L5

User's own spec (Traditional Chinese, authoritative), 4 requirements:
1. 執行過程要能顯示目前 DV Agent Harness L5 目前所在階段和目前該階段還有哪些待完成項目及距離完成的百分比 (show current stage, remaining incomplete items in that stage, and completion percentage)
2. 執行過程要能顯示目前 DV Agent Harness L5 每個階段開始要用一個明顯的 Logo 顯示（使用者已澄清：Logo 指的是文字/ASCII art，不是圖檔），同時要顯示所需要的文件、檔案和相關資料清單和完整度百分比。另外要提醒使用者哪些項目需要再提供詳細資料 (at stage START: a clear ASCII-art banner, PLUS a checklist of required input documents/files/data with completeness %, PLUS an explicit reminder listing which items still need the user to supply more detail)
3. 執行過程要能顯示目前 DV Agent Harness L5 每個階段結束要用一個明顯的 Logo 顯示，同時要顯示輸出的檔案和相關資料清單和完整度百分比，並顯示總執行時間（含各個 Agents）和所耗掉的 token 數量 (at stage END: a clear ASCII-art banner, PLUS a checklist of output files/data with completeness %, PLUS total execution time including all sub-agents, PLUS total token count consumed)
4. 同時儲存 2,3 顯示的內容為 reports (save both the start-of-stage and end-of-stage displays as persisted report files)

An earlier audit this session found this PARTIAL: dv_harness/engine.py already has REAL _emit_stage_start_marker(stage) and _emit_stage_done_marker(stage, gate_verdict, stage_completion_percent) functions (read them at the top of engine.py, they're small), called from real stage-transition code -- these already give you #1's completion-percentage piece and a start/done marker to build on. What's genuinely missing: the ASCII-art banner, the required/output file checklist with completeness %, the "ask user for more detail" reminder, the total-time-including-subagents + token-count display, and persisted report files.

Also read dv_harness/stage_profile_report.py in full first -- it ALREADY computes real per-stage wall-clock/token/tool-call/retry numbers (the 'dv-harness stage-profile' CLI command). Do not reimplement this; call into its real functions/data for the time+token piece of requirement #3, extending it if it doesn't yet aggregate "including all sub-agents" (check whether it does today, and if it only counts the main session's own token usage not sub-agent Workflow/Agent-tool dispatches, that's a real gap to close here).

Concrete requirements:
1. Extend (do not replace) _emit_stage_start_marker/_emit_stage_done_marker in dv_harness/engine.py, or add new sibling functions called alongside them, to produce: an ASCII-art banner (design a real, recognizable one -- reuse across all stages is fine, a stage-name-parameterized banner is fine, just make it genuinely visually distinct in a terminal, not just a text line), a required-input-files checklist (source this from gates.py's real STAGE_GATES definitions -- each stage's entry evidence requirements are already real data; do not invent a parallel checklist source) with real completeness % computed from what's actually present vs required, and an explicit "please provide more detail on: X, Y, Z" reminder listing exactly the missing/incomplete required items.
2. Same for stage-done: an output-files/data checklist (source from the stage's real exit evidence/blackboard_write topics, same principle -- real data, not invented), completeness %, and the total-time+token summary (extending stage_profile_report.py's real data, not reinventing).
3. Persist BOTH displays as real report files (e.g. .dv-harness/stage_reports/<stage>_start_<timestamp>.md and <stage>_done_<timestamp>.md) -- markdown, human-readable, containing everything shown on screen.
4. New CLI surface if useful (e.g. 'dv-harness stage-report <stage>' to re-render a saved report), but the core requirement is the automatic display+save at real stage start/done, not just an on-demand command.
5. Real tests: run a real (or synthetic) stage transition and confirm the banner/checklist/percentage/report-file all appear and are internally consistent (the completeness % actually matches the checklist's own item count, the report file's content matches what was printed).

This touches dv_harness/engine.py -- check git status/git diff first (other concurrent work may still be uncommitted there; as of this dispatch engine.py should be clean/committed from the reliability workstream's own recent commit, but verify rather than assume) and use the hand-scoped patch technique if anything else is uncommitted there when you start.

Write a report to .work/gap-close-progress-display-report.md. Run your tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED with a one-line test summary.`, {label: 'build:progress-display', phase: 'Audit+Build', model: 'claude-opus-5'})

const results = await parallel([
  () => auditInference, () => auditGraph, () => auditMultiAgent, () => auditRouter,
  () => auditReact, () => auditBlackboard, () => auditMemory, () => auditSignoff,
  () => auditEvidenceGrounded, () => auditAgentRoles, () => auditSessionRestore,
  () => auditDebugLoop, () => auditGenericProtocol, () => auditSubsystemToSoc,
  () => progressDisplay,
])
const [inferenceR, graphR, multiAgentR, routerR, reactR, blackboardR, memoryR, signoffR,
  evidenceGroundedR, agentRolesR, sessionRestoreR, debugLoopR, genericProtocolR, subsystemToSocR,
  progressDisplayR] = results

phase('Close')

const auditSummaries = [
  ['#1 Autonomous Inference Engine', inferenceR],
  ['#2 Graph Orchestrator', graphR],
  ['#3 Multi-Agent Orchestrator', multiAgentR],
  ['#4 Route & Skill Resolver', routerR],
  ['#5 Plan-and-Execute / ReAct Engine', reactR],
  ['#6 Blackboard / Evidence Engine', blackboardR],
  ['#7 5-Level Memory Engine', memoryR],
  ['#8 Qualification / Signoff Engine', signoffR],
  ['#9 Evidence-Grounded AI (Hypothesis+Evidence+Result+Gate=Conclusion)', evidenceGroundedR],
  ['#10 The 7 Expert Agent Roles', agentRolesR],
  ['#11 Session Save/Restore', sessionRestoreR],
  ['#12 AI Debug Closed Loop', debugLoopR],
  ['#13 Generic multi-protocol DV Harness scope (USB/PCIe/MIPI/Ethernet/CAN-FD/AMBA4)', genericProtocolR],
  ['#14 Subsystem -> System-Level/SoC verification generation', subsystemToSocR],
]

log('Audit phase complete. Closing confirmed gaps one at a time (sequential, since most touch dv_harness/engine.py or shared core files) to avoid concurrent-edit collisions.')

const closeResults = []
for (const [name, report] of auditSummaries) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

This is a sequential gap-closing pass over today's fresh re-audit of DV Agent Harness L5's 14 core AI mechanisms (including the new "generic multi-protocol scope" and "subsystem-to-SoC generation" analysis items, which are explicitly expected to resolve to NEEDS_SEPARATE_EFFORT rather than a same-pass fix -- do not attempt to build multi-protocol support or system-level composition in this pass). You are handling exactly ONE mechanism: **${name}**.

Its real, current audit finding (read carefully, this is real evidence gathered just now, not the old prior-session audit):

${report}

## Your task

1. If the audit verdict is WIRED_AND_FIRING with no real gap named: do nothing to the code. Just confirm this by re-reading the cited evidence yourself, and report NO_ACTION_NEEDED with why.
2. If the audit found a real, concrete, in-scope gap (PARTIALLY_WIRED or DORMANT with a fixable cause): close it for real. The audit report above should already describe concretely what a fix needs to do -- follow that, but use your own judgment if the concrete plan needs adjustment once you're actually in the code. Prioritize wiring the REAL existing mechanism into the REAL production path over building a parallel/duplicate mechanism (per this session's own repeatedly-learned lesson about not reinventing something that already exists).
3. If the audit found a gap that is a genuine, large, separate design effort (not a quick wiring fix -- e.g. "build an entirely new capability from scratch"), do NOT attempt it in this single pass. Instead, report NEEDS_SEPARATE_EFFORT with a clear, scoped description of what that follow-up effort should cover, and do not modify any file.
4. Check git status/git diff on any file you're about to touch FIRST -- other sequential fixes in this same pass, and other concurrent workstreams elsewhere in this session, may have already changed things since the audit ran. Use the hand-scoped patch technique for any shared file if needed.
5. Write real tests proving the fix actually wires the mechanism into the real path (not just that the underlying function still works in isolation -- that was never the gap).
6. Run the full relevant test suite for whatever you touched and confirm pass.
7. Commit your change for real (if you made one) with a clear, scoped commit -- do not leave real, tested work uncommitted in this heavily concurrent-edited tree.

Write a report to .work/gap-close-ai-engine-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase()}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `close:${name}`, phase: 'Close', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Review')

const review = await agent(`Independently review this entire "re-audit 14 AI mechanisms + close every confirmed in-scope gap + build the stage-progress-display feature" effort for DV Agent Harness L5, against the user's own explicit, emphatic instruction: "一定要全部項目、要求、問題修正、缺失改進、沒有實做要補上實做" (every single item, requirement, issue-fix, deficiency-improvement, and not-yet-implemented part must genuinely be implemented) -- and against this project's established standard of NOT accepting a report's own claim without independent re-verification.

Read every audit report and every close-pass report in full first (search .work/ for files matching gap-close-ai-engine-*-report.md and gap-close-progress-display-report.md).

Raw returned results, for cross-reference:

### Audits
${auditSummaries.map(([name, report]) => `#### ${name}\n${report}`).join('\n\n')}

### Progress display build
${progressDisplayR}

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

For EVERY one of the 14 mechanisms, verify independently (run real commands yourself, do not trust prose):
1. Was the audit's evidence actually real (re-run whatever command/grep it cited, confirm the same result)?
2. For every engine the close-pass touched: did the fix actually wire the mechanism into a real production path, verified by you running something real (not just reading the new code and agreeing it looks right)? Is there a real test proving it, and does that test actually exercise production wiring, not just the underlying function in isolation (the exact distinction the original gap was about)?
3. For every engine marked NO_ACTION_NEEDED or NEEDS_SEPARATE_EFFORT: is that call correct, or did the close-pass under-scope something that was actually fixable now?
4. For the progress-display feature: actually trigger a real (or synthetic) stage transition yourself and confirm the banner/checklist/percentage/time/token/report-file all genuinely appear and are internally consistent -- this is a user-facing feature, "the code exists" is not sufficient, it must actually produce real visible output when a stage runs.
5. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
6. Check git hygiene across all the commits this pass made -- confirm no whole-file git add swept in unrelated concurrent work, and confirm every commit's git show --stat matches its own claimed scope.

Report a clear verdict per engine (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED) plus an overall verdict (APPROVED / NEEDS_FIX) for the whole effort, with concrete evidence-cited findings. Be exhaustive -- the user explicitly does not want anything left half-done or silently skipped.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { auditSummaries: Object.fromEntries(auditSummaries), progressDisplayR, closeResults: Object.fromEntries(closeResults), review }
