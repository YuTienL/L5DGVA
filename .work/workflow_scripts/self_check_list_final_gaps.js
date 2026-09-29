export const meta = {
  name: 'self-check-list-final-gaps',
  description: 'Close the 5 genuine remaining gaps surfaced by cross-checking self_check_list.md against this session\'s completed audits: cross-run trend DB, question-queue digest auto-trigger + 4 metrics, harness-to-remote-Agent-path deployment mechanism, parallel multi-agent document-extraction orchestration, and 10-minute job/log monitor cadence',
  phases: [
    { title: 'Audit', detail: '5 parallel audits, one per gap, against current real code' },
    { title: 'Build', detail: 'sequential, reuse-first close pass -- build the mechanism, never auto-invoke real remote deployment' },
    { title: 'Review', detail: 'independent re-verification' },
  ],
}

const CONTEXT = `
LOCAL_ANALYSIS declaration: this workflow is local read/build only. Item 3
below (harness-to-remote deployment) must build the DEPLOYMENT MECHANISM
(a real, testable sync/deploy tool) but must NEVER actually execute a real
rsync/scp/ssh call against the live Linux server as part of this workflow --
that would be REMOTE_EXECUTION requiring a fresh SSH/Remote Transport
Connection Intake confirmation per CLAUDE.md, which this workflow does not
have. Test the mechanism with a local/synthetic target path or dry-run mode
only.

This project has an extremely strong, repeatedly-enforced norm against
building parallel/duplicate mechanisms. Before building anything, search
dv_harness/ and .claude/ for a real existing equivalent and prefer
extending it.

Five gaps, each independently confirmed real by a synthesis of this
session's 9 already-completed audit/gap-close workflows against a
user-supplied master checklist (self_check_list.md items #2, #11-14,
#37-39, #40, #41):

1. Cross-run trend database + regression bisect-detection + runtime
   anomaly detection -- confirmed BLOCKED by an earlier audit this session
   (verification_knowledge_assets_reverify.js's Section 2 audit): no
   daily-rollup pass-rate/coverage/runtime/license-hour time series exists
   (evidence_db.py's regression_verdicts table is upsert-only, overwrites
   each cycle), no automated git-bisect-style regression detection exists,
   no runtime-vs-historical-baseline anomaly detection exists. JobState
   (lsf_client.py) doesn't even capture a runtime/duration field, which
   blocks 2 of these 3 sub-items until it does.

2. Question-queue digest auto-triggering + the 4 tracked metrics -- an
   earlier audit (self_describing_bind_reverify.js) found build_digest()
   (question_queue.py) is real and correctly never-real-time, but nothing
   calls it automatically (zero callers in engine.py, no cron/scheduled
   config anywhere). Separately, confirm whether the 4 metrics (self-resolve
   rate target >90%, blocking-questions/week, repeat-question-rate,
   assumption-overturn-rate) are actually computed by real code today, not
   just described as a design goal.

3. Harness-to-remote-Agent-path deployment -- self_check_list.md items
   #37-39 require that when multiple users share this harness, ANY update
   must sync to the real Linux server's Agent deployment path, and that
   distilled new skills/capabilities must be written back to the remote
   Knowledge Center DB path. The Knowledge Center write-back half
   (dv_harness/knowledge_center.py, KnowledgeCenterClient) is already real
   and wired (confirmed by multiple audits this session). What's unconfirmed:
   does any real mechanism exist for syncing the HARNESS CODEBASE ITSELF
   (dv_harness/, .claude/skills, .claude/agents) to a remote deployment
   path? Check REMOTE_LOGIN_GUIDE.md, tools/remote/*.py, and any deploy/sync
   script under tools/ or dv_harness/ for real existing machinery before
   concluding this needs to be built from scratch.

4. Parallel multi-agent document-extraction orchestration -- self_check_list.md
   item #40 asks for multiple agents launched SIMULTANEOUSLY to convert/
   extract different document categories (VIP doc/source/examples, DUT doc/
   registers, IP doc, programming guide, DUT RTL, IP source, top TB,
   command.txt, standard specs) for a VIP-based verification environment.
   The individual extractors are confirmed real (doc_extraction.py,
   vip_symbol_index.py, vip_user_guide_distill.py, design_intent.py,
   address_map_verifier.py, env_manifest.py per CLAUDE.md's Context Budget
   section) -- but check whether any real orchestration layer actually
   DISPATCHES them as a parallel multi-agent fan-out (e.g. a real Workflow
   script, a CLI subcommand that fans out concurrent subprocess/thread calls,
   or an agent-dispatch pattern), or whether each is only ever invoked
   individually/sequentially/on-demand today.

5. Background job/log monitor 10-minute cadence -- CLAUDE.md's "Background
   Job/Log Monitor Auto-Start" section documents \`dv-harness lsf-watch-start\`
   as a detached background process that discovers/reconciles live LSF jobs.
   Confirm with real code (grep the watcher's polling-interval implementation)
   whether it actually operates on a ~10-minute cadence as self_check_list.md
   specifies, a different real interval, or an event-driven (non-interval)
   model -- and if the interval differs from 10 minutes, that is not
   automatically a defect (a different real cadence may be a deliberate,
   reasonable choice) but must be reported accurately rather than assumed.

Verdict format per item, one of:
- WIRED_AND_FIRING / PARTIALLY_WIRED / DORMANT / NEVER_BUILT, with real
  evidence (file:line, real command output). Never assert from memory.
`

phase('Audit')

const trendDbR = agent(`${CONTEXT}

## Your scope: Gap 1 -- cross-run trend DB + bisect detection + runtime anomaly

Re-verify the confirmed-BLOCKED finding with fresh evidence (grep dv_harness/evidence_db.py, dv_harness/lsf_client.py's JobState, dv_harness/regression_reporter.py). Confirm current state and describe EXACTLY what real code would need to add: (a) a runtime/duration field on JobState + its reconciliation write path, (b) a daily-rollup query/table in evidence_db.py (DuckDB already has real timestamped rows in coverage_samples/regression_verdicts -- but regression_verdicts is upsert-only; determine the minimal real schema change to retain history), (c) a bisect helper that walks real RTL git history given a pass->fail transition, (d) a runtime-anomaly comparator against a real historical baseline. Report your verdict per the required format.`, {label: 'audit:trend-db', phase: 'Audit'})

const digestMetricsR = agent(`${CONTEXT}

## Your scope: Gap 2 -- question-queue digest auto-trigger + 4 metrics

Re-verify with fresh evidence: does anything call dv_harness/question_queue.py's build_digest() automatically today (grep engine.py, cli.py, any scheduled-task config, .github/workflows/)? Separately, grep question_queue.py's real metrics()-shaped function(s) and confirm exactly which of the 4 named metrics (self-resolve rate, blocking-questions/week, repeat-question-rate, assumption-overturn-rate) are actually computed by real code today vs. only described in a docstring/CLAUDE.md. Report your verdict per the required format for auto-triggering and for each of the 4 metrics separately.`, {label: 'audit:digest-metrics', phase: 'Audit'})

const remoteDeployR = agent(`${CONTEXT}

## Your scope: Gap 3 -- harness-to-remote-Agent-path deployment mechanism

Read REMOTE_LOGIN_GUIDE.md, tools/remote/*.py (remote_hop.py, remote_relay.py, remote_exec.py, source_identity.py) in full. Grep the whole repo for any real sync/deploy/rsync/push-to-remote mechanism targeting a harness-deployment path (as opposed to the already-confirmed-real Knowledge Center DB write-back, which is a DIFFERENT, already-solved concern -- do not re-audit that). Determine concretely: is there a real, callable "deploy/sync the harness codebase to the shared Linux Agent path" tool today, or does this not exist? If it doesn't exist, describe what a real, TESTABLE (dry-run/local-target-capable, never auto-invoking a real remote call) deployment mechanism would need: source manifest (which files/dirs constitute "the harness" -- dv_harness/, .claude/skills, .claude/agents, CLAUDE.md), a diff/sync strategy, and a safe dry-run mode. Report your verdict per the required format.`, {label: 'audit:remote-deploy', phase: 'Audit'})

const parallelExtractR = agent(`${CONTEXT}

## Your scope: Gap 4 -- parallel multi-agent document-extraction orchestration

Confirm each individual extractor's real existence (doc_extraction.py, vip_symbol_index.py, vip_user_guide_distill.py, design_intent.py, address_map_verifier.py, env_manifest.py, and any others covering the 11 categories in self_check_list.md item #40: VIP doc/user-guide, VIP source/reference-class, VIP examples, DUT doc/registers, IP doc/user-guide, programming guide, DUT RTL/source/interrupts/registers, IP source/model, top testbench/running-script/filelist, reference command.txt, standard specs). Then check specifically: is there any real CLI subcommand, Workflow script, or code path that DISPATCHES multiple of these as a genuine parallel/concurrent fan-out (not just "each is individually callable")? Report your verdict per the required format for the extractor coverage and for the orchestration-layer separately.`, {label: 'audit:parallel-extract', phase: 'Audit'})

const monitorCadenceR = agent(`${CONTEXT}

## Your scope: Gap 5 -- background job/log monitor cadence

Find the real implementation behind \`dv-harness lsf-watch-start\` (grep cli.py, lsf_client.py, or a dedicated watcher module). Read its real polling-loop code and report the ACTUAL cadence/model it uses today (a fixed sleep interval in seconds/minutes, an event-driven model, or something else) -- quote the real line of code. Report your verdict per the required format, explicitly stating whether the real cadence matches, differs from, or has no fixed cadence compared to the "every 10 minutes" spec.`, {label: 'audit:monitor-cadence', phase: 'Audit'})

const results = await parallel([
  () => trendDbR, () => digestMetricsR, () => remoteDeployR, () => parallelExtractR, () => monitorCadenceR,
])
const [trendDbA, digestMetricsA, remoteDeployA, parallelExtractA, monitorCadenceA] = results

phase('Build')

const gaps = [
  ['Gap 1: cross-run trend DB + bisect detection + runtime anomaly', trendDbA],
  ['Gap 2: question-queue digest auto-trigger + 4 metrics', digestMetricsA],
  ['Gap 3: harness-to-remote-Agent-path deployment mechanism', remoteDeployA],
  ['Gap 4: parallel multi-agent document-extraction orchestration', parallelExtractA],
  ['Gap 5: background job/log monitor cadence', monitorCadenceA],
]

log('Audit phase complete. Closing confirmed real gaps sequentially, reuse-first, never auto-invoking a real remote deployment call.')

const closeResults = []
for (const [name, report] of gaps) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CONTEXT}

This is a sequential gap-closing pass over a fresh audit of DV Agent Harness L5 against self_check_list.md's remaining open items. You are handling exactly ONE scope: **${name}**.

NOTE: this repo now has real git history (pushed to https://github.com/YuTienL/DV_Agent_Harness.git, branches master and gap-close/env-manifest-fact-sources) -- check git status/git diff before touching any file, use the hand-scoped patch technique for shared files (git diff > patch, trim to your hunk, git apply --cached --check then --cached).

Its real, current audit finding (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. If WIRED_AND_FIRING with no real gap: do nothing, re-confirm the cited evidence.
2. If a real, concrete, bounded gap exists: close it for real, extending existing code (evidence_db.py, lsf_client.py, question_queue.py, cli.py) rather than a parallel mechanism.
3. Gap 3 specifically: build the deployment MECHANISM (a real, testable tool/script) but NEVER execute a real network call to the actual Linux server as part of closing this gap -- test only against a local/synthetic target directory or a dry-run mode that prints what it would do.
4. Gap 4 specifically: if building a parallel-dispatch orchestration layer, prefer a real CLI subcommand or a documented Workflow-script pattern over inventing a new bespoke concurrency mechanism -- check how other multi-step tools in this codebase (e.g. dv_harness/cli.py's existing subcommand structure) already handle fan-out, if at all.
5. If something is a genuine, large, separate effort, report NEEDS_SEPARATE_EFFORT with a clear scoped description instead of attempting it.
6. Write real tests proving whatever you build works.
7. Run the full relevant test suite and confirm pass.
8. Commit your change for real (if you made one) with a clear, scoped commit.

Write a report to .work/gap-close-self-check-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 40)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `close:${name}`, phase: 'Build', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Review')

const review = await agent(`Independently review this "close the 5 genuine remaining self_check_list.md gaps" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification.

Read every audit report and every close-pass report in full first (search .work/ for files matching gap-close-self-check-*-report.md).

Raw returned results, for cross-reference:

### Audits
${gaps.map(([name, report]) => `#### ${name}\n${report}`).join('\n\n')}

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE: did the fix actually work, verified by you running something real?
2. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
3. Check git hygiene across all commits this pass made.
4. CRITICAL, top-priority check for Gap 3: grep the entire diff/commit history from this pass for any evidence a real network/SSH/rsync call was made against a real remote host -- this must never have happened. If found, flag this as a severe finding, not a minor note.

Report a clear verdict per gap (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED) plus an overall verdict (APPROVED / NEEDS_FIX).`, {label: 'final-review', phase: 'Review', model: 'claude-opus-5'})

return { gaps: Object.fromEntries(gaps), closeResults: Object.fromEntries(closeResults), review }
