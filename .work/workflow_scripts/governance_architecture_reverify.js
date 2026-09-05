export const meta = {
  name: 'governance-architecture-reverify',
  description: 'Re-verify with CURRENT real evidence that production-grade execution governance genuinely implements the Engineer->Claude CLI->L5 Harness->Knowledge/Governance/Execution/Evidence layered architecture, then close every confirmed real gap',
  phases: [
    { title: 'Audit', detail: '8 layer/node audits against the diagram, in parallel' },
    { title: 'Close', detail: 'sequential fix pass over every confirmed real, in-scope gap' },
    { title: 'Review', detail: 'independent end-to-end re-verification' },
  ],
}

const DIAGRAM = `
                    Engineer
                       |
                       v
                  Claude CLI
                       |
              +--------v--------+
              |   L5 Harness    |
              | Graph/Planner   |
              +--------+--------+
                       |
       +---------------+----------------+
       v               v                v
   Knowledge        Governance       Execution
    Layer             Layer            Layer
       |               |                |
 Obsidian CLI       gh / git         just
 Markdown/Git       PR Gate          pueue
 DuckDB              Audit             |
       |               |                v
       |               |          Preflight Agent
       |               |            - lmstat
       |               |            - disk
       |               |            - env
       |               |            - queue
       |               |            - host
       |               |                |
       |               |                v
       |               |          LSF / Slurm
       |               |          bsub / sbatch
       |               |                |
       |               |                v
       |               |          VCS / Verdi
       |               |          ZeBu / HAPS
       |               |                |
       +---------------+----------------+
                       v
                 Evidence Layer
          +------------+------------+
          v            v            v
        logs          FSDB       coverage
          |            |            |
          +------> Distillation <---+
                       |
                vip_distill.py
                       |
              verible JSON / parsers
                       |
                       v
                    DuckDB
                       |
            +----------+----------+
            v                     v
      Debug / RCA            Memory Agent
                                   |
                           Obsidian Knowledge
                                   |
                           Git / PR / Audit
`

const AUDIT_RULES = `
You are re-verifying ONE part of DV Agent Harness L5's "production-grade
execution governance" architecture, against this exact diagram the user has
given as the authoritative target shape:

${DIAGRAM}

Real components were built earlier this session under this exact theme (a
6-workstream "Production-Grade Execution Governance" effort, commits
1459f99/c2dc146/64bdf6e/1875494/4ab5f44/36d0595, plus later fixes and a
separate effort that wired evidence_db into the reconciliation cycle for
real, commit 06b3e68). Your job is NOT to assume these pieces exist and are
correctly wired just because they were reported built before -- re-verify
with CURRENT real evidence (grep real call sites, read real code, run a real
command where possible) whether YOUR assigned part of the diagram is real
AND correctly connected to its neighbors exactly as the diagram draws it,
not just present in isolation.

Required verdict format per node/edge you check, one of:
- REAL_AND_CONNECTED: real code exists, is callable/callled from a real
  path, and is wired to the neighboring node(s) the diagram shows (e.g. if
  the diagram shows A -> B, real evidence A's output is actually consumed
  by B, not just that both A and B separately exist).
- REAL_BUT_DISCONNECTED: the node itself is real, but the specific edge(s)
  the diagram draws to/from it are NOT real (cite exactly which edge is
  missing).
- PARTIALLY_REAL: real code exists but only covers part of what the
  diagram's box implies (e.g. diagram says "VCS / Verdi / ZeBu / HAPS" but
  only VCS is real).
- ASPIRATIONAL: diagram text only, no real implementation.

Evidence standard: cite real file:line, run a real command yourself and
show its real output, or grep for real callers -- never assert from memory
or from this prompt's own framing.

If you find a real, confirmed, fixable gap, describe EXACTLY what closing it
would require (concrete file(s)/function(s), concrete verification method)
so a separate fix pass can act without re-investigating from scratch. Do not
fix anything yourself -- audit only, do not modify any file.
`

phase('Audit')

const auditRouting = agent(`${AUDIT_RULES}

## Your scope: Engineer -> Claude CLI -> L5 Harness Graph/Planner -> (fan-out to Knowledge/Governance/Execution layers)

Check: does dv_harness's real engine (main_graph.json + dv_harness/engine.py's run_stage()/loop(), already independently audited elsewhere this session as the "Graph Orchestrator") actually ROUTE work into the three named layers below it as the diagram implies -- i.e. does a real stage transition in engine.py actually invoke/dispatch into Knowledge-layer code (memory_vault.py / DuckDB), Governance-layer code (git_governance.py / gh), and Execution-layer code (just / pueue / preflight) as part of its own real flow? Or does each of those three "layers" only get invoked by separate, disconnected CLI subcommands a human runs manually, with no real central Graph/Planner dispatch tying them together as one system? Be concrete and cite real call sites either way -- this is the most likely place for the diagram to be aspirational (a clean box-and-arrow shape imposed after the fact on what may really be several separate, not-unified subsystems).

Report your verdict per the required format.`, {label: 'audit:routing', phase: 'Audit'})

const auditKnowledge = agent(`${AUDIT_RULES}

## Your scope: Knowledge Layer -- Obsidian CLI / Markdown+Git / DuckDB

Check: dv_harness/memory_vault.py (Obsidian+Git/Markdown Hybrid Memory Integration, built earlier this session) -- is there a real, callable Obsidian CLI integration (or is "Obsidian CLI" aspirational and it's really just plain markdown+git with no actual Obsidian-specific tooling)? Confirm real git-commit-backed markdown notes exist (grep .dv-harness/memory/ or wherever the vault persists, for real files with real git history). Confirm DuckDB is real and used for more than just evidence_db (dv_harness/evidence_db.py) -- does the Knowledge layer specifically (not just the separate Evidence layer at the bottom of the diagram) have its own DuckDB usage, or does the diagram's Knowledge-layer DuckDB box actually just point at the SAME evidence_db.py the Evidence layer uses (which would mean the diagram's two separate DuckDB mentions are really one shared store -- note this explicitly if true, it's not necessarily wrong, just worth being honest about).

Report your verdict per the required format for each of the 3 sub-components (Obsidian CLI, Markdown/Git, DuckDB).`, {label: 'audit:knowledge', phase: 'Audit'})

const auditGovernance = agent(`${AUDIT_RULES}

## Your scope: Governance Layer -- gh/git PR Gate + Audit

Check: dv_harness/git_governance.py, tools/git-hooks/pre-push and pre-merge-commit, dv-harness git-guard CLI, the "gh CLI + PR-Only Governance Policy" CLAUDE.md section. Per that section's own honest self-disclosure (re-read it), the local hooks are CODED but NOT YET INSTALLED (core.hooksPath unset) and there's no GitHub remote configured, so there's no live PR gate today. Re-confirm this is still the real current state (or has it changed?). Separately, confirm the Audit half: .claude/agents/audit-change-governance-agent.md and the GIT_GUARD_DECISION event trail in .dv-harness/events.jsonl -- is there real evidence of actual logged decisions, or is the audit trail empty/theoretical because git-guard has never actually fired (since the hooks aren't installed)?

Report your verdict per the required format for gh/git PR Gate and for Audit separately.`, {label: 'audit:governance', phase: 'Audit'})

const auditJustPueue = agent(`${AUDIT_RULES}

## Your scope: Execution Layer -- just + pueue

Check: the justfile-derivation pipeline (run_profile_to_justfile.py, this session's own run_profile.json work) and the pueue integration (dv_harness/cli.py's pueue subcommands, test_cli_pueue.py/test_pueue_client.py -- note these are the exact tests the concurrent MCP-effort's full suite run just reported as 12 pre-existing failures requiring a live pueue daemon, real evidence pueue integration exists in code but has never been verified against a genuinely running daemon in this environment). Confirm: is 'just' actually used as the real invocation layer for simulation runs (grep real Makefile/justfile call sites from engine.py or lsf_client.py), or does the real execution path bypass 'just' and call vcs/make directly somewhere, making the diagram's "just" box aspirational for at least part of the real flow?

Report your verdict per the required format for 'just' and 'pueue' separately.`, {label: 'audit:just-pueue', phase: 'Audit'})

const auditPreflight = agent(`${AUDIT_RULES}

## Your scope: Preflight Agent -- lmstat / disk / env / queue / host checks

Check: the Preflight Agent built in this session's own governance workflow (commit 1459f99) -- find its real source file, confirm it actually implements all 5 named checks (lmstat license-server check, disk space, environment/env-var sanity, queue/LSF-queue status, host reachability) as real, callable checks (not stubs), and confirm it's actually invoked BEFORE a real job submission in the real flow (i.e. does lsf_client.py or engine.py's build/run stage actually call the Preflight Agent first, or does it exist as a standalone tool nothing calls automatically)?

Report your verdict per the required format, per sub-check (lmstat/disk/env/queue/host) if their status differs.`, {label: 'audit:preflight', phase: 'Audit'})

const auditLsfExec = agent(`${AUDIT_RULES}

## Your scope: LSF/Slurm bsub/sbatch -> VCS/Verdi/ZeBu/HAPS

Check: dv_harness/lsf_client.py -- confirm real LSF (bsub) job-submission code exists and is exercised (this session's own live USB build used it for real). Is there any real Slurm (sbatch) support, or is LSF the only one actually implemented (Slurm may be diagram-aspirational -- confirm honestly)? For the simulation-tool box: confirm VCS invocation is real (obviously yes, used throughout this session's live USB build) and Verdi (waveform/debug tool) integration is real. For ZeBu/HAPS specifically: these are hardware-emulation platforms, structurally very different from VCS/Verdi software simulation -- grep the entire dv_harness/ tree for any real ZeBu or HAPS-specific code path. Note: a peer Claude Code session on this machine is literally named "haps-af" per this session's own environment -- do NOT assume that implies dv_harness itself has real HAPS support; check dv_harness's own source, not what other sessions on this machine happen to be named.

Report your verdict per the required format, separately for LSF, Slurm, VCS, Verdi, ZeBu, HAPS.`, {label: 'audit:lsf-exec', phase: 'Audit'})

const auditEvidence = agent(`${AUDIT_RULES}

## Your scope: Evidence Layer -- logs/FSDB/coverage -> Distillation -> vip_distill.py -> verible JSON/parsers -> DuckDB

Check: dv_harness/vip_distill.py (scoped in this session's own governance workflow, commit 36d0595) and dv_harness/evidence_db.py (recently gained real reconciliation-cycle wiring + a normalized_evidence bridge from vip_distill.py, per a concurrent effort this session -- commit 06b3e68 and the just-completed MCP-effort's separate uncommitted normalized_evidence/vip_distill hunk in evidence_db.py, flagged by that effort as "out of scope, left uncommitted" -- check whether that hunk is still uncommitted now and whether it represents a real, needed piece of THIS diagram's Evidence layer that's sitting unfinished). Confirm the real, current data flow: do real logs/FSDB-report-output/coverage-report files actually get read by vip_distill.py, actually get combined with verible-derived JSON/parser output, and actually land in DuckDB as queryable rows (run a real query against the real evidence_db if one exists in this project)? Or does this pipeline only work in isolated unit tests with synthetic fixtures, never proven against real generated evidence from a real build?

Report your verdict per the required format for each stage of the pipeline (logs/FSDB/coverage -> Distillation -> vip_distill.py -> verible -> DuckDB), and explicitly address the uncommitted normalized_evidence hunk.`, {label: 'audit:evidence', phase: 'Audit'})

const auditDebugMemoryLoop = agent(`${AUDIT_RULES}

## Your scope: DuckDB -> Debug/RCA + Memory Agent -> Obsidian Knowledge -> Git/PR/Audit (the closing loop back to Governance)

Check: does anything real read FROM the DuckDB evidence store to drive Debug/RCA (e.g. the debug-agent.md skill, or dv_harness/inference.py's hypothesis-evidence loop, actually querying evidence_db for real historical/current evidence) -- or does DuckDB only ever get WRITTEN to, with nothing reading it back for RCA? Separately: is there a real "Memory Agent" that takes a Debug/RCA conclusion and writes it into Obsidian Knowledge (memory_vault.py's real promote/write path), and does THAT in turn ever produce a real git commit and/or PR (closing the loop back to the Governance layer's gh/git PR Gate, per this session's own git_governance.py)? This is the diagram's most speculative-looking closing arrow (Obsidian Knowledge -> Git/PR/Audit) -- determine honestly whether a real, automatic knowledge-commit ever becomes a real PR, or whether the loop dead-ends at a local git commit with no PR ever opened (note CLAUDE.md's own honest disclosure that no GitHub remote is configured in this repo -- if true, a real PR is structurally impossible right now regardless of code readiness, which is a different verdict than "the code to open one doesn't exist").

Report your verdict per the required format for: DuckDB->Debug/RCA read path, Debug/RCA->Memory Agent, Memory Agent->Obsidian Knowledge, Obsidian Knowledge->Git/PR/Audit.`, {label: 'audit:debug-memory-loop', phase: 'Audit'})

const results = await parallel([
  () => auditRouting, () => auditKnowledge, () => auditGovernance, () => auditJustPueue,
  () => auditPreflight, () => auditLsfExec, () => auditEvidence, () => auditDebugMemoryLoop,
])
const [routingR, knowledgeR, governanceR, justPueueR, preflightR, lsfExecR, evidenceR, debugMemoryLoopR] = results

phase('Close')

const auditSummaries = [
  ['Routing: Engineer->Claude CLI->L5 Harness Graph/Planner->3 layers', routingR],
  ['Knowledge Layer: Obsidian CLI / Markdown+Git / DuckDB', knowledgeR],
  ['Governance Layer: gh/git PR Gate + Audit', governanceR],
  ['Execution Layer: just + pueue', justPueueR],
  ['Preflight Agent: lmstat/disk/env/queue/host', preflightR],
  ['Execution Layer: LSF/Slurm -> VCS/Verdi/ZeBu/HAPS', lsfExecR],
  ['Evidence Layer: logs/FSDB/coverage -> Distillation -> vip_distill.py -> verible -> DuckDB', evidenceR],
  ['Closing loop: DuckDB -> Debug/RCA + Memory Agent -> Obsidian -> Git/PR/Audit', debugMemoryLoopR],
]

log('Audit phase complete. Closing confirmed real, in-scope gaps one at a time (sequential, to avoid concurrent-edit collisions with the other workflows/agents running this session).')

const closeResults = []
for (const [name, report] of auditSummaries) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

This is a sequential gap-closing pass over a fresh re-verification of DV Agent Harness L5's "production-grade execution governance" architecture against the user's own layered diagram (Engineer -> Claude CLI -> L5 Harness Graph/Planner -> Knowledge/Governance/Execution layers -> Evidence Layer -> Debug/RCA + Memory Agent -> Obsidian -> Git/PR/Audit). You are handling exactly ONE part: **${name}**.

NOTE: other agents and workflows are concurrently active in this same repo right now (a separate 14-AI-mechanism audit+close workflow, a live remote USB build). Check git status/git diff on any file before touching it, and use the hand-scoped patch technique for any shared file (git diff > patch, trim to your hunk, git apply --cached --check then --cached) rather than a broad git add.

Its real, current audit finding (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. If the audit verdict is REAL_AND_CONNECTED with no real gap named: do nothing to the code. Re-confirm the cited evidence yourself and report NO_ACTION_NEEDED with why.
2. If the audit found a real, concrete, in-scope gap (REAL_BUT_DISCONNECTED or PARTIALLY_REAL with a fixable, bounded cause): close it for real -- wire the missing connection, complete the missing coverage. Prioritize wiring REAL existing pieces together over building new parallel mechanisms.
3. If the audit found something genuinely out of scope for a quick fix (e.g. "no GitHub remote configured" -- that's an environment/account decision, not a code gap; or "ZeBu/HAPS hardware-emulation support" -- that's a large new capability, not a wiring fix; or "install the git hooks" -- re-read CLAUDE.md's gh/git PR-Only Governance Policy section carefully, since this may be an intentional, already-disclosed deferred state rather than an oversight), do NOT attempt it. Report NO_ACTION_NEEDED (if it's a correctly-deferred/disclosed state) or NEEDS_SEPARATE_EFFORT (if it's a real gap too large for this pass) with a clear explanation of which, and do not modify any file.
4. Write real tests proving any fix actually connects the two things the diagram says should be connected (not just that each piece still works in isolation).
5. Run the full relevant test suite for whatever you touched and confirm pass.
6. Commit your change for real (if you made one) with a clear, scoped commit.

Write a report to .work/gap-close-governance-arch-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 60)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `close:${name}`, phase: 'Close', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Review')

const review = await agent(`Independently review this "re-verify the production-grade execution governance layered architecture against the user's diagram, close every confirmed real gap" effort for DV Agent Harness L5.

The diagram being verified against:
${DIAGRAM}

Read every audit report and every close-pass report in full first (search .work/ for files matching gap-close-governance-arch-*-report.md).

Raw returned results, for cross-reference:

### Audits
${auditSummaries.map(([name, report]) => `#### ${name}\n${report}`).join('\n\n')}

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

For EVERY part of the diagram, verify independently (run real commands yourself, do not trust prose):
1. Was the audit's evidence actually real (re-run whatever command/grep it cited, confirm the same result)?
2. For every part the close-pass touched: did the fix actually create a real, verified connection between the two things the diagram draws an arrow between -- verified by you running something real, not just reading the new code and agreeing it looks right?
3. For every part marked NO_ACTION_NEEDED or NEEDS_SEPARATE_EFFORT: is that call correct? Distinguish clearly between "correctly deferred, already disclosed in CLAUDE.md" (e.g. no GitHub remote) vs. "the close-pass under-scoped something actually fixable now."
4. Trace the FULL diagram end-to-end yourself as a single coherent narrative: starting from a hypothetical engineer's Claude CLI invocation, through the Graph/Planner, through however much of Knowledge/Governance/Execution is real, down to Evidence, back up through Debug/RCA and Memory Agent, to Obsidian, to Git/PR/Audit -- and report, node by node, exactly where the real, current implementation's actual data/control flow diverges from this diagram's shape. This narrative is the single most important output of your review -- do not just list per-node verdicts, connect them into one honest account of what the SYSTEM actually does today end-to-end versus what the diagram draws.
5. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
6. Check git hygiene across all commits this pass made.

Report a clear verdict per diagram part (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED) plus an overall verdict (APPROVED / NEEDS_FIX), plus the end-to-end narrative from point 4. Be exhaustive and honest -- this diagram is being used as a genuine engineering commitment, not a marketing slide, so an inflated "yes it all matches" verdict is a real disservice.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { auditSummaries: Object.fromEntries(auditSummaries), closeResults: Object.fromEntries(closeResults), review }
