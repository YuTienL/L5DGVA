// rca-multi-agent-fusion.js
//
// Real, saved multi-agent RCA workflow: fans real specialist agents out in
// genuine PARALLEL (via this Workflow tool's own concurrent agent()
// dispatch -- a real engine-level fan-out, distinct from both (a) the
// dv_harness Python engine's own ThreadPoolExecutor graph-node fan-out
// (dv_harness/engine.py's _advance_with_fanout(), see multi_agent.py's
// top-of-file NOTICE) and (b) CORE/multi-agent-orchestrator's documented
// "parallel" today, which is a human/LLM session manually issuing several
// Agent-tool calls in one turn. This script is a THIRD, additional, real
// mechanism: the Workflow tool concurrently runs the agent() calls in
// `parallel()` below up to its own concurrency cap -- see the
// workflow-authoring skill. It does not change what the dv_harness Python
// engine itself does; it is a separately-invokable saved script an
// orchestrating session calls when a failure genuinely needs multi-angle
// evidence gathering. See CORE/issue-triage-and-deep-rca's "Multi-Agent
// Evidence Fan-Out (Optional, Parallel Path)" section for when to reach for
// this vs. the existing single-sub-agent sequential analysis_debug path.
//
// Evidence sources fanned out over (RTL / Log / VIP+Spec, optionally FSDB):
//   - rtl-evidence-agent        (.claude/agents/rtl-evidence-agent.md, new)
//   - log-evidence-agent        (.claude/agents/log-evidence-agent.md, new)
//   - vip-spec-evidence-agent   (.claude/agents/vip-spec-evidence-agent.md, new)
//   - waveform-root-cause-agent (.claude/agents/waveform-root-cause-agent.md,
//                                 EXISTING -- reused, not duplicated, only
//                                 when args.includeWaveform is true)
// then a real Evidence Fusion stage that cross-references/dedups their
// structured findings and persists the merged result to the real Blackboard
// via `dv-harness blackboard write rca_evidence_fusion` (dv_harness/cli.py's
// "blackboard" subcommand -> dv_harness/commands.py's cmd_blackboard_write
// -> the real Blackboard.write() in dv_harness/blackboard.py -- this script
// itself has no filesystem/Python access, so the fusion agent performs the
// real write via its own PowerShell tool call), then an RCA Review stage
// that independently re-reads that persisted topic and produces the final
// verdict.

export const meta = {
  name: 'rca-multi-agent-fusion',
  description: 'Parallel multi-angle RCA evidence fan-out (RTL/Log/VIP+Spec, optionally FSDB) -> Evidence Fusion (real Blackboard.write of "rca_evidence_fusion") -> RCA Review verdict.',
  whenToUse: 'A REAL_ISSUE-classified failure (per CORE/issue-triage-and-deep-rca) where the evidence genuinely spans multiple independent angles (RTL/TB source, sim.log/trace/scoreboard text, VIP/spec, optionally FSDB waveform) and gathering them in parallel -- not sequentially inside one analysis_debug turn -- is worth the fan-out cost. For a simpler failure where one evidence type already explains the symptom, use the existing single-sub-agent sequential analysis_debug path instead (see the SKILL.md section this workflow is referenced from).',
  phases: [
    { title: 'Parallel Evidence Gathering' },
    { title: 'Evidence Fusion' },
    { title: 'RCA Review' },
  ],
}

// args shape:
// {
//   repoRoot: string        -- required, e.g. 'D:\\DV\\Task\\DV_Agent_Harness_L5\\v50'
//   failureId: string       -- required, a short id/name for this failure (used as a citation label
//                              and as part of the fused Blackboard record -- not a generated timestamp,
//                              scripts cannot call Date.now())
//   symptom: string         -- required, the observed symptom/error (exact UVM_ERROR/UVM_FATAL text,
//                              scoreboard mismatch summary, timeout description, etc.) -- real text
//                              from an actual failing run, never a guessed/generic description
//   commandTxtPath?: string -- path to the failing run's command.txt, when known
//   simLogPath?: string     -- path to the failing run's sim.log/trace, when known
//   rtlHint?: string        -- implicated module/instance/signal/interface hint, when known
//   vipSpecHint?: string    -- protocol/profile/VIP hint, when known
//   includeWaveform?: bool  -- default false; set true only when FSDB/waveform evidence is actually
//                              available and useful (per CLAUDE.md's Waveform Dump User Gate / Simulation
//                              Observability Default -- this script does not itself decide to dump waveform)
//   fsdbHint?: string       -- required when includeWaveform is true: FSDB file path / dump scope
// }

if (!args || !args.repoRoot || !args.failureId || !args.symptom) {
  throw new Error(
    'rca-multi-agent-fusion requires args: {repoRoot, failureId, symptom, commandTxtPath?, simLogPath?, ' +
    'rtlHint?, vipSpecHint?, includeWaveform?, fsdbHint?}. See the comment block at the top of this script ' +
    'for what each field means.'
  )
}
if (args.includeWaveform && !args.fsdbHint) {
  throw new Error(
    'rca-multi-agent-fusion: args.includeWaveform is true but args.fsdbHint was not given -- ' +
    'waveform-root-cause-agent needs a real FSDB file path / dump scope to read, not a blind request ' +
    'to open a waveform. Pass fsdbHint, or leave includeWaveform false/unset for the RTL+Log+VIP/Spec ' +
    'fan-out only.'
  )
}

const REPO_ROOT = args.repoRoot
const FAILURE_ID = args.failureId

const FINDING_ITEM_SCHEMA = {
  type: 'object',
  properties: {
    claim: { type: 'string' },
    source_file: { type: 'string' },
    location: { type: 'string' },
    evidence: { type: 'string', description: 'Verbatim citation (exact text/line/timestamp) backing this claim -- never a paraphrase from memory.' },
    confidence: { type: 'string', enum: ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'] },
  },
  required: ['claim', 'evidence', 'confidence'],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    agent: { type: 'string' },
    evidence_domain: { type: 'string' },
    findings: { type: 'array', items: FINDING_ITEM_SCHEMA },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['agent', 'findings'],
}

const FUSION_SCHEMA = {
  type: 'object',
  properties: {
    fused_findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          supporting_agents: { type: 'array', items: { type: 'string' } },
          source_citations: { type: 'array', items: { type: 'string' } },
          confidence: { type: 'string', enum: ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'] },
          cross_reference_note: { type: 'string', description: 'How this claim relates to/confirms/conflicts with claims from other evidence domains, or "" if standalone.' },
        },
        required: ['claim', 'supporting_agents', 'confidence'],
      },
    },
    disagreements: { type: 'array', items: { type: 'string' }, description: 'Claims where two or more evidence domains genuinely conflict; resolved here by direct re-inspection, never by voting.' },
    unresolved_open_questions: { type: 'array', items: { type: 'string' } },
    contributing_agents: { type: 'array', items: { type: 'string' } },
    fusion_confidence: { type: 'string', enum: ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'] },
    blackboard_write_confirmed: { type: 'boolean', description: 'true only if the `dv-harness blackboard write rca_evidence_fusion` command was actually run and returned the written payload -- never set true without having run it.' },
    blackboard_write_stdout: { type: 'string' },
  },
  required: ['fused_findings', 'contributing_agents', 'fusion_confidence', 'blackboard_write_confirmed'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    root_cause: { type: 'string' },
    first_bad_event: { type: 'string' },
    causal_chain: { type: 'array', items: { type: 'string' } },
    attribution: { type: 'string', enum: ['DUT_BUG', 'TB_BUG', 'VIP_ISSUE', 'TEST_ISSUE', 'SPEC_AMBIGUITY', 'INFRA_ISSUE', 'UNKNOWN'] },
    confidence: { type: 'string', enum: ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'] },
    counter_evidence: { type: 'string' },
    fix_plan: { type: 'string' },
    risk_assessment: { type: 'string' },
    affected_scope: { type: 'string' },
    regression_plan: { type: 'string' },
    rollback_plan: { type: 'string' },
    verified_fusion_topic_read: { type: 'boolean', description: 'true only if this stage actually ran `dv-harness blackboard read rca_evidence_fusion` itself and based the verdict on that re-read, rather than trusting the Evidence Fusion stage\'s own report blindly.' },
  },
  required: ['root_cause', 'confidence', 'attribution', 'verified_fusion_topic_read'],
}

log(`RCA Multi-Agent Fusion for failure "${FAILURE_ID}": fanning out RTL/Log/VIP+Spec evidence agents in real parallel${args.includeWaveform ? ' plus waveform-root-cause-agent (FSDB)' : ''} over ${REPO_ROOT}.`)

const commonContext = [
  `Repo: ${REPO_ROOT}.`,
  `Failure id: ${FAILURE_ID}.`,
  `Symptom (real, from an actual failing run -- do not second-guess this framing, but do not assume it is the full story either): ${args.symptom}`,
  args.commandTxtPath ? `command.txt for this run: ${args.commandTxtPath}` : 'command.txt path not given -- locate it yourself if the repo layout makes it discoverable, otherwise note it as an open question.',
  args.simLogPath ? `sim.log/trace for this run: ${args.simLogPath}` : 'sim.log/trace path not given -- locate it yourself if discoverable, otherwise note it as an open question.',
].join('\n')

phase('Parallel Evidence Gathering')

const branches = [
  {
    label: 'rtl-evidence',
    agentType: 'rtl-evidence-agent',
    prompt: [
      commonContext,
      '',
      'You are the RTL/TB evidence branch of a multi-angle RCA fan-out. Gather ONLY real RTL/testbench source evidence per your own agent instructions -- do not gather log/FSDB/VIP/spec evidence, other branches are doing that in parallel and blind to your work.',
      args.rtlHint ? `Module/instance/signal hint: ${args.rtlHint}` : 'No specific module/instance/signal hint was given -- derive the likely implicated area from the symptom text and real repo hierarchy evidence yourself; report exactly how you narrowed it down.',
      'Report structured findings with exact file/line citations.',
    ].join('\n'),
  },
  {
    label: 'log-evidence',
    agentType: 'log-evidence-agent',
    prompt: [
      commonContext,
      '',
      'You are the log/trace/scoreboard/command-semantic evidence branch of a multi-angle RCA fan-out. Gather ONLY real sim.log/trace/scoreboard-report/command.txt evidence per your own agent instructions -- do not gather RTL/TB/FSDB/VIP/spec evidence, other branches are doing that in parallel and blind to your work.',
      'Report structured findings with exact file/line/timestamp citations, plus any command_semantic_gaps.',
    ].join('\n'),
  },
  {
    label: 'vip-spec-evidence',
    agentType: 'vip-spec-evidence-agent',
    prompt: [
      commonContext,
      '',
      'You are the VIP-source/example/docs and protocol-Standard-spec/PHY-model evidence branch of a multi-angle RCA fan-out. Gather ONLY real VIP/spec evidence per your own agent instructions -- do not gather RTL/TB/log/FSDB evidence, other branches are doing that in parallel and blind to your work.',
      args.vipSpecHint ? `Protocol/VIP hint: ${args.vipSpecHint}` : 'No protocol/VIP hint was given -- route/confirm the protocol yourself (CORE/protocol-router) from real repo evidence before searching VIP/spec sources.',
      'Report structured findings with exact VIP file/line or spec document/clause citations, plus any spec_ambiguity_notes.',
    ].join('\n'),
  },
]

if (args.includeWaveform) {
  branches.push({
    label: 'fsdb-evidence',
    agentType: 'waveform-root-cause-agent',
    prompt: [
      commonContext,
      '',
      `FSDB/waveform scope for this branch (already confirmed via the Waveform Dump User Gate -- do not re-litigate scope, use it): ${args.fsdbHint}`,
      'You are the FSDB/waveform evidence branch of this multi-angle RCA fan-out -- the existing waveform-root-cause-agent role, reused here rather than duplicated as a new agent file. Drive the causal chain backward from the symptom to the first bad event per your own agent instructions. Other branches are gathering RTL/TB/log/VIP-spec evidence in parallel and blind to your work -- report your own findings in the same findings/evidence/confidence shape so Evidence Fusion can cross-reference them, in addition to your normal first_bad_event/causal_chain/root_cause_candidates output.',
    ].join('\n'),
  })
} else {
  log('includeWaveform not set: FSDB/waveform branch skipped for this run (RTL+Log+VIP/Spec evidence only). Set args.includeWaveform + args.fsdbHint to add it -- this is a real, logged omission, not silently-assumed full coverage.')
}

const branchResults = await parallel(
  branches.map((b) => () => agent(b.prompt, { label: b.label, phase: 'Parallel Evidence Gathering', agentType: b.agentType, schema: FINDINGS_SCHEMA, effort: 'high' }))
)

const gathered = branches.map((b, i) => ({ label: b.label, result: branchResults[i] })).filter((g) => g.result)
if (gathered.length === 0) {
  throw new Error('rca-multi-agent-fusion: every evidence-gathering branch failed or was skipped -- nothing to fuse. Check the individual agent errors above before retrying.')
}
const droppedBranches = branches.map((b, i) => ({ label: b.label, ok: !!branchResults[i] })).filter((b) => !b.ok)
if (droppedBranches.length > 0) {
  log(`${droppedBranches.length} branch(es) returned no result and are excluded from fusion: ${droppedBranches.map((b) => b.label).join(', ')}.`)
}

// Barrier justified here (see workflow-authoring): Evidence Fusion genuinely
// needs ALL branch results together to dedup/cross-reference before the
// single real Blackboard write -- this is the "dedup/merge across the full
// result set before expensive downstream work" pattern, not a transform
// that could live inside a pipeline stage.
phase('Evidence Fusion')

const reportBlock = gathered.map((g) => [`=== ${g.label.toUpperCase()} REPORT ===`, JSON.stringify(g.result, null, 2), ''].join('\n')).join('\n')

const fusionPrompt = [
  `Repo: ${REPO_ROOT}. Failure id: ${FAILURE_ID}. Symptom: ${args.symptom}`,
  '',
  `${gathered.length} INDEPENDENT evidence branches each read a different real evidence domain in parallel, blind to each other's work, and reported structured findings:`,
  '',
  reportBlock,
  'Your job -- Evidence Fusion:',
  '1. Build one merged findings list. Dedup findings that are really the same underlying fact seen from two domains (e.g. an RTL evidence branch citing a register default and a log evidence branch citing the same register\'s runtime value at the failure timestamp) -- merge these into ONE fused_findings entry with supporting_agents listing every branch that backs it and source_citations carrying every real citation.',
  '2. Cross-reference: for every fused finding, note in cross_reference_note how it relates to findings from OTHER domains (confirms, is silent on, or conflicts with).',
  '3. For any genuine disagreement between domains (not just different domains covering different things -- an actual conflicting claim about the same fact), do NOT vote or average it away: list it in `disagreements` with both sides\' citations, for RCA Review to resolve with its own judgment.',
  '4. List every open_questions entry from every branch in unresolved_open_questions (dedup exact duplicates only).',
  '5. Set fusion_confidence honestly: HIGH only if the branches converge on a coherent picture with no unresolved disagreement; otherwise MEDIUM/LOW/UNKNOWN.',
  '6. THEN ACTUALLY PERSIST this fused result to the real Blackboard -- this is not optional and not simulated. Using your PowerShell tool, from the repo root:',
  '   a. Save the JSON object {failure_id, symptom, contributing_agents, fused_findings, disagreements, unresolved_open_questions, fusion_confidence} to a temp file, e.g. via PowerShell\'s own `Set-Content -Encoding utf8`, at a path like `.dv-harness/tmp/rca_evidence_fusion_<failure-id-slug>.json` under the repo root (create the `.dv-harness/tmp` directory first if needed -- New-Item -ItemType Directory -Force).',
  `   b. Run: dv-harness --project-root "${REPO_ROOT}" blackboard write rca_evidence_fusion --file "<that temp file path>" --source rca-multi-agent-fusion --confidence <your fusion_confidence> (fall back to \`python -m dv_harness.cli\` in place of \`dv-harness\` if the console script is not on PATH).`,
  '   c. Confirm the command exited 0 and printed back a JSON payload with "topic": "rca_evidence_fusion" and your value inside "value" -- only then set blackboard_write_confirmed to true, and put the command\'s real stdout in blackboard_write_stdout. If the command fails for any reason, set blackboard_write_confirmed to false, report the real error, and do NOT claim success.',
  'This will be handed to an independent RCA Review stage that does NOT see your raw prompt -- it will itself re-read the rca_evidence_fusion Blackboard topic (not trust your report blindly), so the write in step 6 must be real.',
].join('\n')

const fusionResult = await agent(fusionPrompt, { label: 'evidence-fusion', phase: 'Evidence Fusion', agentType: 'review-agent', schema: FUSION_SCHEMA, effort: 'high' })

if (!fusionResult) {
  throw new Error('rca-multi-agent-fusion: Evidence Fusion stage returned no result -- cannot proceed to RCA Review without a fused/persisted evidence record.')
}
if (!fusionResult.blackboard_write_confirmed) {
  log('WARNING: Evidence Fusion did not confirm a successful Blackboard write of rca_evidence_fusion. RCA Review will independently re-read the topic and should report BLOCKED/UNKNOWN if it is genuinely absent, rather than trusting this run\'s in-memory fusion result.')
}

phase('RCA Review')

const reviewPrompt = [
  `Repo: ${REPO_ROOT}. Failure id: ${FAILURE_ID}. Symptom: ${args.symptom}`,
  '',
  'A multi-agent RCA evidence fan-out + fusion process just ran. It claims to have persisted its fused result to the real Blackboard topic "rca_evidence_fusion". Do NOT trust that claim blindly (CLAUDE.md: current evidence wins) -- using your own PowerShell tool, run:',
  `  dv-harness --project-root "${REPO_ROOT}" blackboard read rca_evidence_fusion (or python -m dv_harness.cli --project-root "${REPO_ROOT}" blackboard read rca_evidence_fusion if the console script is not on PATH)`,
  'and base your review on what that command ACTUALLY returns, not on the summary below. Set verified_fusion_topic_read to true only if you actually ran that command and it returned a non-null value for this failure.',
  '',
  'For context only (re-verify, do not assume correct), here is what the fusion stage itself reported it wrote:',
  JSON.stringify(fusionResult, null, 2),
  '',
  'Your job -- RCA Review (this is the final arbiter over already-gathered-and-fused evidence, not a re-run of raw evidence gathering):',
  '1. Read the real rca_evidence_fusion Blackboard entry as instructed above.',
  '2. Resolve every listed disagreement yourself by judgment over the cited evidence (re-read the cited source file directly yourself when a disagreement is not resolvable from the fusion record alone).',
  '3. Identify the first bad event and build the causal chain from it to the observed symptom.',
  '4. Classify attribution (DUT_BUG/TB_BUG/VIP_ISSUE/TEST_ISSUE/SPEC_AMBIGUITY/INFRA_ISSUE/UNKNOWN) -- never call a DUT bug solely from a scoreboard mismatch; require the RTL/TB-side evidence to back it.',
  '5. Set confidence honestly -- UNKNOWN/LOW stays UNKNOWN/LOW when evidence is genuinely insufficient; do not round up to look conclusive.',
  '6. Produce fix plan, risk assessment, affected scope, regression plan and rollback plan per CORE/issue-triage-and-deep-rca\'s "Before modify" requirements. Only a HIGH/VERIFIED-confidence RCA may recommend proceeding to modify.',
].join('\n')

const verdict = await agent(reviewPrompt, { label: 'rca-review', phase: 'RCA Review', agentType: 'analysis_debug', schema: VERDICT_SCHEMA, effort: 'high' })

return {
  failureId: FAILURE_ID,
  branchLabels: gathered.map((g) => g.label),
  droppedBranches: droppedBranches.map((b) => b.label),
  branchResults: gathered,
  fusionResult,
  verdict,
}
