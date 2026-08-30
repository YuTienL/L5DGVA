export const meta = {
  name: 'gap-closing-evidence-consensus',
  description: 'Reusable 4-phase Multi-Agent Evidence Consensus workflow: N blind independent readers of one real source region -> consensus synthesis (ties broken by direct re-inspection, never voting) -> implement exactly the synthesized spec -> independent re-verify + honest before/after measurement.',
  whenToUse: 'Any important DUT/PHY/Register/VIP or generator-schema change where a real source file/region must be read and modeled faithfully. Generalized from DV Agent Harness L5 v50 sessions (2026-08) that closed the USB_UVM_Handoff generator-fidelity gap round by round. Pass args to point it at a new target instead of writing a new one-off script.',
  phases: [
    { title: 'Parallel Evidence Gathering' },
    { title: 'Consensus Synthesis' },
    { title: 'Implement' },
    { title: 'Re-verify and measure' },
  ],
}

// args shape (all required unless marked optional):
// {
//   repoRoot: string                 -- e.g. 'D:\\DV\\Task\\DV_Agent_Harness_L5\\v50'
//   evidenceFile: string              -- real source file every agent must read from scratch
//   evidenceRegion: string             -- what to read inside it, e.g. "the full connect_phase function
//                                        (search 'function void connect_phase', read to matching endfunction)"
//   gapDescription: string             -- what is currently unmodeled / why this round exists, with any
//                                        already-known partial evidence so agents know the context, not the answer
//   agentCount?: number                -- default 3; scale with how important/risky the change is (CLAUDE.md:
//                                        "Important DUT/PHY/Register/VIP changes require Multi-Agent evidence
//                                        acquisition plus independent synthesis") -- not "more is always better"
//   synthesisGoal: string              -- what the consensus spec must decide/output (schema shape, field names, etc.)
//   implementTask: string              -- concrete implement instructions: which engine file(s) to touch, which
//                                        existing tests must stay green, what new test file to write, exact
//                                        py_compile/pytest commands to run and report verbatim
//   reverifyTask: string               -- concrete re-verify instructions: re-read real code directly (do not
//                                        trust the implementer's report), rerun the full test suite + self-audit,
//                                        apply the new capability to a next real example, report honest
//                                        before/after numbers, state plainly what (if anything) still isn't modeled
// }

if (!args || !args.repoRoot || !args.evidenceFile || !args.evidenceRegion || !args.gapDescription
    || !args.synthesisGoal || !args.implementTask || !args.reverifyTask) {
  throw new Error(
    'gap-closing-evidence-consensus requires args: {repoRoot, evidenceFile, evidenceRegion, gapDescription, ' +
    'synthesisGoal, implementTask, reverifyTask, agentCount?}. See the comment block at the top of this script ' +
    'for what each field means and a worked example (the USB connect_phase call-statement round this workflow ' +
    'was generalized from).'
  )
}

const AGENT_COUNT = args.agentCount && args.agentCount >= 2 ? args.agentCount : 3
const LABELS = ['A', 'B', 'C', 'D', 'E', 'F'].slice(0, AGENT_COUNT)

log(`Multi-Agent Evidence Consensus: ${AGENT_COUNT} independent blind readers of ${args.evidenceFile} (${args.evidenceRegion}), matching CLAUDE.md's "Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent synthesis" rule literally -- not a sequential implement-then-recheck pattern.`)

const evidencePrompt = (label) => [
  `You are agent ${label} in a ${AGENT_COUNT}-way INDEPENDENT evidence-gathering exercise. You do NOT see what the other ${AGENT_COUNT - 1} agents find -- read the real file yourself, from scratch, and report only what YOU directly observe. Do not assume any prior session's findings are complete or correct; re-derive everything yourself.`,
  '',
  'Read-only investigation. Do NOT modify anything anywhere.',
  '',
  `Read ${args.evidenceFile}'s ${args.evidenceRegion} in complete detail.`,
  '',
  `Context (why this round exists -- do not just confirm this, independently re-derive it): ${args.gapDescription}`,
  '',
  'Do a FULL, fresh, independent re-enumeration of everything in that region -- not just the parts already flagged as gaps. A full re-enumeration is the point: it is how a prior pass\'s omission or miscount gets caught. For each real element found, report exact line number(s), exact verbatim text, and its shape/kind.',
  '',
  `Synthesis goal this evidence will feed (for context on what to pay attention to, not something to assume the answer to): ${args.synthesisGoal}`,
  '',
  'Report everything you found, in order, with verbatim line citations.',
].join('\n')

phase('Parallel Evidence Gathering')
const reports = await parallel(
  LABELS.map((label) => () => agent(evidencePrompt(label), { label: `evidence-${label}`, phase: 'Parallel Evidence Gathering', effort: 'high' }))
)

phase('Consensus Synthesis')
const reportBlock = LABELS.map((label, i) => [`=== REPORT ${label} ===`, String(reports[i] || '(no result)'), ''].join('\n')).join('\n')
const synthesisPrompt = [
  `You are given ${AGENT_COUNT} INDEPENDENT reports from agents who each separately read the same real region (${args.evidenceFile}: ${args.evidenceRegion}) without seeing each other's work. Your job is Multi-Agent Evidence Consensus + Independent Synthesis: reconcile them into ONE authoritative, agreed finding.`,
  '',
  reportBlock,
  'Steps:',
  '1. Build a master list cross-referencing all reports by line number/citation. Flag any element only some agents found (a disagreement).',
  '2. For every disagreement: do NOT vote or average. Re-read the real file yourself, right now, and resolve it by your own direct observation -- state which report(s) were right and why, with your own fresh citation.',
  `3. Produce the final synthesis this round needs: ${args.synthesisGoal}`,
  '4. Output the final spec as ONE self-contained, unambiguous design. This will be handed directly to an implementation agent that does NOT get to see the raw reports above -- only your synthesis. If it is not fully self-contained, the implementer will have to guess, which defeats the point of this process.',
].join('\n')

const consensusSpec = await agent(synthesisPrompt, { label: 'consensus-synthesis', phase: 'Consensus Synthesis', effort: 'high' })

phase('Implement')
const implementPrompt = [
  `Repo: ${args.repoRoot}.`,
  '',
  'A Multi-Agent Evidence Consensus process (independent blind readers + a reconciliation pass that resolved every disagreement by direct re-inspection of the real source, never by voting) already analyzed the real target and produced the following FINAL, AGREED spec. Implement EXACTLY this spec -- do not re-derive evidence yourself, the consensus process already did that rigorously. If something in the spec is genuinely ambiguous or does not match the real code when you check, STOP and report the discrepancy rather than silently improvising.',
  '',
  '=== CONSENSUS SPEC ===',
  String(consensusSpec || '(no result)'),
  '=== END CONSENSUS SPEC ===',
  '',
  args.implementTask,
].join('\n')

const implementResult = await agent(implementPrompt, { label: 'implement-from-consensus', phase: 'Implement', effort: 'high' })

phase('Re-verify and measure')
const reverifyPrompt = [
  `Repo: ${args.repoRoot}. Consensus spec used for this round:`,
  '=== CONSENSUS SPEC ===', String(consensusSpec || '(no result)'), '=== END ===',
  '',
  'Implementation report:',
  String(implementResult || '(no result)'),
  '',
  'Verify the real code matches both the spec and the report by reading it directly yourself -- do not trust the implementer\'s report blindly.',
  '',
  args.reverifyTask,
].join('\n')

const reverifyResult = await agent(reverifyPrompt, { label: 'reverify-and-measure', phase: 'Re-verify and measure', effort: 'high' })

return { reports, consensusSpec, implementResult, reverifyResult }
