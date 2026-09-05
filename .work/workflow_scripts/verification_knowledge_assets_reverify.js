export const meta = {
  name: 'verification-knowledge-assets-reverify',
  description: 'Re-verify with CURRENT real evidence that DV Agent Harness L5 genuinely implements "verification knowledge as executable assets" (vPlan/exemptions, cross-run trend+regression-detection, resource/cost autonomy, harness reliability, org accountability), close only genuine remaining gaps',
  phases: [
    { title: 'Audit', detail: '6 section audits against the spec, in parallel' },
    { title: 'Close', detail: 'sequential fix pass over every confirmed real, in-scope gap' },
    { title: 'Report', detail: 'independent verification + priority-3 status check' },
  ],
}

const CORE_PRINCIPLES = `
This exact spec ("把驗證知識變成可執行的資產" -- verification knowledge as
executable assets) has been sent to this session multiple times already
today. Real work already landed under this theme earlier this session:

- A 6-workstream "Production-Grade Execution Governance" workflow (commits
  1459f99 preflight, c2dc146 just, 64bdf6e verible+DuckDB evidence_db,
  1875494 gh+PR-only+git_governance.py, 4ab5f44 pueue+escalation_notify,
  36d0595 vip_distill scoping).
- A separate "exemptions_and_reliability" workflow (commits dded1e1, 0b69dca)
  that built dv_harness/exemptions.py (schema-validated exemptions with
  mandatory valid_until, expiry -> review queue), dv_harness/degradation.py
  + engine.py dry-run/auto-checkpoint/DEGRADED-mode wiring, and
  tools/testing/self_test.py + .github/workflows/dv-harness-ci.yml.
- CLAUDE.md gained "Agent-Authored Change Accountability (2026-09-03)" and
  "Trust Progression for Autonomous/Semi-Autonomous Work (2026-09-03)"
  sections (commit 4d7b81b) covering the organizational-accountability ask.

Your job is NOT to assume these already close the user's ask -- re-verify
with CURRENT real evidence (grep real call sites, read real code, run real
commands) whether each specific numbered item in the spec below is genuinely
real and working, not just that something adjacent was built under a similar
name. Several items in this spec (cross-run SQLite trend database with daily
pass-rate/coverage/runtime/license-hour curves, automatic bisect-to-RTL-
commit regression detection, runtime-anomaly detection, RTL-diff-driven test
selection, seed-vs-constraint differentiation, tiered smoke/nightly/weekly
regression escalation) are NOT obviously covered by the above prior work --
treat these as real candidates for genuine gaps, not assume-covered.

Verdict format per numbered item, one of:
- READY: real, working, evidenced end-to-end.
- PARTIAL: real but incomplete -- name exactly what's missing.
- BLOCKED: does not exist, no disclosed reason it can't be built now (a
  real, closeable gap).
Cite real file:line or real command output for every verdict. Audit only --
do not modify any file in this phase.
`

phase('Audit')

const auditVplanExemptions = agent(`${CORE_PRINCIPLES}

## Your scope: Section 1 -- 把驗證知識變成可執行的資產 (vPlan as single source of truth + structured exemptions)

### Item 1a: vPlan as single source of truth
vPlan -> coverage model -> testlist -> regression results should be one machine-readable chain (extending any existing Excel->YAML->IR pipeline), so an agent can answer "which features have no corresponding test" (verification PROGRESS), not just "which coverage bins are unhit" (a number). Check dv_harness/vplan_writer.py and any Excel/YAML/IR pipeline for vPlan -- does real code actually let an agent query "feature X has zero corresponding tests" as a first-class question, or does the current implementation only ever report coverage-bin misses? Be concrete about which query shapes are actually answerable today via real code (not by a human reading a report).

### Item 1b: Structured exemptions
"This check is disabled because of an IP limitation"-type knowledge needs structure: entry/reason/basis-document/valid_until/owner, with valid_until as the key field -- expired exemptions auto-enter a review queue so a temporary workaround never silently becomes permanent fact. Check dv_harness/exemptions.py (built earlier this session) against this exact shape: does it have all 5 fields (entry, reason, basis document, valid_until, owner), does valid_until actually gate expiry-review-queue behavior for real (not just schema presence), and does an agent actually consult this store before re-questioning or auto-deleting something an exemption already covers (i.e. is it actually READ from anywhere in the real flow, not just written-to)?

Report your verdict per the required format for 1a and 1b separately.`, {label: 'audit:vplan-exemptions', phase: 'Audit'})

const auditCrossRunTime = agent(`${CORE_PRINCIPLES}

## Your scope: Section 2 -- 跨 run 的時間維度 (cross-run time dimension)

### Item 2a: Trend database (SQLite)
Daily curves of pass rate, coverage, runtime, license hours -- an agent judging "today got worse" needs yesterday's baseline. Check: does a real SQLite (or equivalent) trend database exist anywhere in dv_harness/ that stores DAILY time-series of these 4 specific metrics, queryable for day-over-day comparison? (Note: evidence_db.py is DuckDB-based and stores per-job/per-reconciliation evidence -- check specifically whether it also supports/enables a daily-rollup trend query, or whether that's a distinct, currently-missing capability.)

### Item 2b: Regression detection (auto-bisect)
A test that goes from pass to fail should auto-bisect to the responsible RTL commit -- mechanical, painful for humans, ideal for an agent. Check: does any real code implement automated bisection against RTL git history when a previously-passing test starts failing?

### Item 2c: Runtime anomaly detection
A test that doesn't fail but runs 3x longer is often a hang precursor or a loosened timeout -- this "not red but wrong" signal is only visible cross-run. Check: does any real code compare a test's current runtime against its own historical baseline and flag anomalous-but-passing runs?

Report your verdict per the required format for 2a, 2b, 2c separately.`, {label: 'audit:cross-run-time', phase: 'Audit'})

const auditResourceCost = agent(`${CORE_PRINCIPLES}

## Your scope: Section 3 -- 資源與成本的自主管理 (autonomous resource/cost management)

### Item 3a: Test selection by RTL-diff impact scope
RTL diff -> impact scope -> only run relevant tests, full regression reserved for nightly -- the single most effective license-cost saver. Check: does real code compute an impact scope from a git diff and select a test subset accordingly (grep for anything resembling change-impact test selection -- note CLAUDE.md already documents a general "command.txt change-impact check" against command_inventory.csv; determine whether that same mechanism, or a different one, actually drives REGRESSION TEST SELECTION specifically, not just command.txt-authoring guidance).

### Item 3b: Seed strategy (differentiate "not run enough" vs "stimulus can't reach")
When coverage stalls, adding seeds doesn't help if the real issue is a constraint problem. An agent should distinguish "hasn't run enough yet" (add seeds) from "stimulus structurally can't reach this bin" (escalate to question queue) -- not just blindly add seeds. Check: does any real code implement this differentiation, or does the current implementation (if any) only ever do blind seed-count increases?

### Item 3c: Tiered regression escalation
Smoke (10 min) / nightly / weekly tiers, each with different escalation thresholds. Check: does real code define and enforce distinct tiers with distinct escalation behavior, or is regression currently flat (one tier, one threshold)?

Report your verdict per the required format for 3a, 3b, 3c separately.`, {label: 'audit:resource-cost', phase: 'Audit'})

const auditHarnessReliability = agent(`${CORE_PRINCIPLES}

## Your scope: Section 4 -- Harness 自身的可靠性 (harness self-reliability)

### Item 4a: Dry-run mode
Agent produces a full plan without executing, for human pre-review -- required during initial rollout and before major changes. Check dv_harness/engine.py's dry-run wiring (built in the exemptions_and_reliability workflow) -- is it real, does it actually produce a complete, humanly-reviewable plan without executing, and is it actually usable/documented for the "before major changes" use case?

### Item 4b: Checkpoint and rollback
Every stage leaves a recoverable point so an agent that goes off-track doesn't restart from zero. Check the real auto-checkpoint wiring in engine.py -- does a real rollback path exist (not just checkpoint-save), and has it ever been exercised for real (even synthetically)?

### Item 4c: Degradation path
When Claude API is unavailable, license is full, or the farm is congested, the harness should degrade to "collect data only, make no judgment calls" -- not fully halt, and not blindly retry. Check dv_harness/degradation.py (built earlier this session) against this EXACT trigger set (Claude API unavailable / license full / farm congested) -- does it detect and respond to all three real conditions, or only some? Does DEGRADED mode actually behave as "collect only, no judgment" as specified, or does it do something else (e.g. just pause)?

### Item 4d: Harness self-test (CI on the harness's own scripts)
Infrastructure breaking is harder to notice than an agent misjudging. Check tools/testing/self_test.py + .github/workflows/dv-harness-ci.yml (built earlier this session) -- is this real, does it actually run, and does it cover the harness's OWN scripts/infrastructure (not just dv_harness's application logic)?

Report your verdict per the required format for 4a, 4b, 4c, 4d separately.`, {label: 'audit:harness-reliability', phase: 'Audit'})

const auditOrganizational = agent(`${CORE_PRINCIPLES}

## Your scope: Section 5 -- 組織面的三件事 (organizational: accountability, trust progression, knowledge asymmetry)

### Item 5a: Accountability
If an agent-opened PR causes an escape, who is responsible? Should be explicit: the agent is a tool; the PR approver bears the same responsibility as if they'd authored the change by hand. Check CLAUDE.md's "Agent-Authored Change Accountability (2026-09-03)" section (built earlier this session) -- confirm it's real, present, and states exactly this principle.

### Item 5b: Trust progression
Start with the lowest-risk tasks (log triage, report generation, coverage summarization) where mistakes are cheap; only after accuracy data accumulates should autonomy extend toward stimulus/pattern modification. Check CLAUDE.md's "Trust Progression for Autonomous/Semi-Autonomous Work (2026-09-03)" section -- confirm it's real and covers this staged-adoption principle.

### Item 5c: Knowledge asymmetry
As the harness gets better at autonomous debug, new engineers get fewer chances to debug real failures by hand -- a real long-term cost. Recommendation: deliberately route some fraction of real failures to a human rather than letting the harness resolve everything it technically could. Check: is there ANY real mechanism (not just prose acknowledgment) implementing this -- e.g. a configurable fraction of failures deliberately NOT auto-triaged, routed to a human queue instead? This is very likely still prose-only (CLAUDE.md's Trust Progression section already discusses it as a stated principle) -- confirm honestly whether it's mechanized or still just documented intent, and if prose-only, that is a real, correctly-scoped-as-organizational (not necessarily code-enforceable) situation -- say so rather than treating "no code" as automatically BLOCKED for this specific item.

Report your verdict per the required format for 5a, 5b, 5c separately.`, {label: 'audit:organizational', phase: 'Audit'})

const results = await parallel([
  () => auditVplanExemptions, () => auditCrossRunTime, () => auditResourceCost,
  () => auditHarnessReliability, () => auditOrganizational,
])
const [vplanExemptionsR, crossRunTimeR, resourceCostR, harnessReliabilityR, organizationalR] = results

phase('Close')

const auditSummaries = [
  ['Section 1: vPlan single-source-of-truth + structured exemptions', vplanExemptionsR],
  ['Section 2: Cross-run trend DB + regression bisect-detection + runtime anomaly', crossRunTimeR],
  ['Section 3: Resource/cost autonomy (test selection, seed strategy, tiered regression)', resourceCostR],
  ['Section 4: Harness reliability (dry-run, checkpoint/rollback, degradation, self-test)', harnessReliabilityR],
  ['Section 5: Organizational (accountability, trust progression, knowledge asymmetry)', organizationalR],
]

log('Audit phase complete. Closing confirmed real BLOCKED gaps one at a time, sequentially, to avoid concurrent-edit collisions with the other workflows active in this session.')

const closeResults = []
for (const [name, report] of auditSummaries) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CORE_PRINCIPLES}

This is a sequential gap-closing pass over a fresh audit of DV Agent Harness L5's "verification knowledge as executable assets" implementation. You are handling exactly ONE scope: **${name}**.

NOTE: other agents/workflows are concurrently active in this repo (a 14-AI-mechanism audit+close workflow, a governance-architecture reverify workflow, an Obsidian-memory 25-phase reverify workflow, a live remote USB build). Check git status/git diff on any file before touching it; use the hand-scoped patch technique for any shared file (especially CLAUDE.md, dv_harness/engine.py, dv_harness/cli.py) rather than a broad git add.

Its real, current audit finding (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. For every item marked READY: do nothing, just re-confirm the cited evidence.
2. For every item marked BLOCKED (a real, closeable gap): build it for real. Prefer extending existing code (exemptions.py, degradation.py, evidence_db.py, vplan_writer.py, engine.py) over a new parallel mechanism. Keep scope bounded to exactly what the item asks -- do not gold-plate.
3. For every item marked PARTIAL: complete the missing piece if it's genuinely bounded; if it's actually a large separate effort, report NEEDS_SEPARATE_EFFORT instead of attempting it here.
4. Item 5c (knowledge asymmetry) is explicitly organizational/process guidance, not necessarily a code gap -- do not force a code mechanism onto it if the audit correctly found it's prose-only by design; NO_ACTION_NEEDED is a valid, correct answer there unless the audit specifically identified a bounded, real code opportunity.
5. Write real tests proving whatever you build actually works end-to-end (not just unit-level in isolation).
6. Run the full relevant test suite for whatever you touched and confirm pass.
7. Commit your change for real (if you made one) with a clear, scoped commit.

Write a report to .work/gap-close-vka-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 40)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `close:${name}`, phase: 'Close', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Report')

const finalReport = await agent(`${CORE_PRINCIPLES}

Independently review this "re-verify verification-knowledge-as-executable-assets + close every confirmed real gap" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every audit report and every close-pass report in full first (search .work/ for files matching gap-close-vka-*-report.md).

Raw returned results, for cross-reference:

### Audits
${auditSummaries.map(([name, report]) => `#### ${name}\n${report}`).join('\n\n')}

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE: did the fix actually work, verified by you running something real?
2. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
3. Check git hygiene across all commits this pass made.

Then specifically answer the user's own stated priority ("六、值得先做的三件" -- the 3 items the user said were worth doing FIRST if only picking from this round): (a) cross-run trend database (low cost, prerequisite for both regression-bisect-detection and flaky-test judgment), (b) exemptions.yaml (directly solves the agent repeatedly re-questioning the same settled thing), (c) written accountability consensus (zero technical cost, but blocks everything downstream if undone). For EACH of these 3, give an explicit final READY/PARTIAL/BLOCKED status as of right now, post-close-pass, since these are the highest-value items to get unambiguously right even if other sections remain partial.

Report a clear verdict per section (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED) plus an overall verdict (APPROVED / NEEDS_FIX), plus the explicit 3-priority-item status. Be honest -- inflated "all done" claims are a disservice given how many times this exact spec has now been sent.`, {label: 'final-report', phase: 'Report', model: 'claude-opus-5'})

return { auditSummaries: Object.fromEntries(auditSummaries), closeResults: Object.fromEntries(closeResults), finalReport }
