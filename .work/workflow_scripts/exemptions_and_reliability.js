export const meta = {
  name: 'exemptions-and-harness-reliability',
  description: 'exemptions.yaml structured-exception system + dry-run mode + degradation path + harness self-test CI',
  phases: [
    { title: 'Build', detail: '3 parallel, file-disjoint workstreams' },
    { title: 'Review', detail: 'independent verification' },
  ],
}

const NOTE = `
Context: this session already has TWO other multi-agent efforts running
concurrently in this same repo -- an "evidence_db live wiring" workflow
(touching dv_harness/regression_reporter.py, dv_harness/evidence_db.py,
dv_harness/vip_distill.py, and dv_harness/config.py's evidence_db block)
and a separate template-extraction project in a different directory. To
avoid the exact concurrent-edit collision this session already hit twice
today (accidentally sweeping a sibling workstream's uncommitted hunks into
your own commit via whole-file \`git add\`), you MUST:
1. Before your first edit to any shared file (config.py, cli.py, CLAUDE.md),
   run \`git status --short\` and \`git diff <file>\` to see what is already
   there uncommitted from a sibling effort. Never assume the file is clean.
2. Before committing, run \`git diff --cached <file>\` and confirm it shows
   ONLY your own intended change. If it shows more, unstage
   (\`git reset <file>\`), then use a hand-built patch (\`git apply --cached\`)
   scoped to just your own hunk -- see how this was done earlier today
   (search git log for "Fix real preflight-gate regression" or the
   run_profile.json commit message for the pattern) if you've never done
   this before.
3. Do NOT touch dv_harness/regression_reporter.py, dv_harness/evidence_db.py,
   or dv_harness/vip_distill.py at all -- those belong to the other
   concurrently-running workflow.
`

phase('Build')

const exemptions = agent(`${NOTE}

## Your task: build a structured exemptions.yaml system for DV Agent Harness L5

User's own spec (Traditional Chinese, authoritative): "這個 check 關掉是因為 IP 限制」這類知識，如果只在註解或口耳相傳，agent 每次都會重新質疑或誤刪。建議 exemptions.yaml：條目、理由、依據文件、有效期、owner。有效期是關鍵欄位 —— 過期的豁免自動進 review queue，避免臨時 workaround 變成永久事實。"

Translation of the requirement: a structured file recording why a given check/gate/assertion is deliberately disabled or relaxed for a specific IP/project reason, so an agent never re-litigates or silently deletes a deliberate exemption -- but an exemption with an expired validity date must surface for human re-review rather than silently staying in force forever.

Concrete requirements:
1. dv_harness/exemptions.py (new module) + schemas/exemptions.schema.json (follow the exact rigor/style of dv_harness/uvm_generator/schemas/run_profile.schema.json as your template -- read that file first). Required fields per entry: id, check_id (what is being exempted -- e.g. a specific static-check rule id, a specific coverage bin, a specific assertion name), reason (free text, the actual "why"), basis_document (a citation -- file path, doc reference, or ticket id; never empty), owner, valid_until (a date; REQUIRED, no permanent/no-expiry exemptions allowed by the schema -- this is the field the user explicitly called "關鍵欄位").
2. A real, callable expiry-check function: given the current date and the exemptions file, return the list of entries whose valid_until has passed. Wire a CLI subcommand (dv-harness exemptions {list, add, check, expire-report} -- read dv_harness/cli.py's existing subcommand-group conventions first, e.g. the \`knowledge\`/\`memory\` groups, and match the style) where \`check\`/\`expire-report\` exits nonzero (CI-friendly, matches the exit-code convention dv_harness/uvm_generator/templates/sim_scripts/dv-check's run_all.sh already uses in the template-extraction sibling project if you want a second reference point) when any entry has expired.
3. Design the "goes to a review queue" mechanism honestly: dv_harness/question_queue.py does NOT exist in this repo yet (it is part of a separate, not-yet-launched effort). Do not depend on it. Instead, build a standalone, well-documented review-queue output (e.g. a real dv_harness/exemptions.py function producing a list of {exemption_id, expired_since, ...} records, written to a known path like .dv-harness/exemptions/review_queue.json) and clearly document in the module's own docstring that this is the integration point a future question-queue system should read from, without inventing that system yourself.
4. Real tests: schema validation, expiry-detection (both a not-yet-expired and a genuinely-expired case), the CLI subcommands, and the review-queue file's real content shape.
5. A short docs/EXEMPTIONS.md explaining the mechanism and a worked real example exemption entry (you may use a genuinely real fact from this repo if one exists -- e.g. check dv_harness/uvm_generator/templates/sim_scripts/Makefile or check/*.py for any place a check is deliberately disabled with a documented reason already, and use that as your real worked example rather than a fabricated one).

Write a report to .work/exemptions-yaml-report.md. Run your new tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:exemptions', phase: 'Build'})

const reliability = agent(`${NOTE}

## Your task: dry-run mode + degradation path + auto-checkpoint wiring for DV Agent Harness L5's engine

User's own spec (Traditional Chinese, authoritative):
"dry-run 模式：agent 產出完整計畫但不執行，人可事前檢視。導入初期與大改動前必用"
"checkpoint 與回滾：每個階段留可回復點，agent 走偏時不必從頭"
"降級路徑：Claude API 不可用、license 全滿、farm 塞車時，harness 應降級成「只收集資料、不做判斷」，而不是整個停擺或胡亂重試"

Read dv_harness/engine.py's DVHarness.run_stage()/loop() in full first (2700+ lines -- use targeted grep for the sections relevant to your task, do not try to read the whole file at once). Also read dv_harness/session_snapshot.py in full -- it ALREADY implements real save_session()/restore_session()/list_sessions() with source-identity (git SHA) mismatch protection, which substantially covers the "checkpoint 與回滾" requirement already. Do not rebuild this from scratch.

Concrete requirements:
1. **Dry-run mode**: add a real, wired \`dry_run: bool\` capability to run_stage()/loop() (or a new explicit \`plan_stage()\`-style entry point if that composes more cleanly with the existing code -- your call, document why). In dry-run mode, the harness must produce its full intended plan/evidence-request for the stage (whatever it would normally do to decide what to execute) WITHOUT: calling the LLM adapter for an action that mutates state, submitting any real LSF job, writing any state-mutating file beyond an explicit dry-run report. Identify the actual side-effect call sites in run_stage() precisely (grep for adapter calls, lsf_client.bsub_submit*, state.save()-style writes) rather than guessing where they are. Wire a CLI flag (\`dv-harness run-stage --dry-run\`) and a config.json toggle. Real test: run a stage in dry-run mode against a real/synthetic project state, assert no LSF submission happened, no adapter call happened, and a real plan artifact was produced.
2. **Auto-checkpoint at stage transitions**: session_snapshot.save_session() already does the real work -- wire it to fire automatically at each real stage transition in run_stage()/loop() (not just on-demand via the existing \`dv-harness save-session\` CLI command), following the SAME "best-effort, wrapped in try/except, never break the real cycle" pattern already established in this codebase (see dv_harness/regression_reporter.py's _escalate_uvm_fatal_burst_if_needed as the precedent style -- read it for the pattern even though you must not edit that file). Make this configurable (a config.json toggle, default on since it's cheap local snapshotting) and give it a real retention policy (do not let auto-checkpoints accumulate unbounded -- check session_snapshot.py's existing list_sessions()/on-disk layout and add a bounded-retention prune, e.g. keep last N auto-checkpoints, documented and tested).
3. **Degradation path**: define a real DEGRADED mode the harness enters when explicitly detecting: (a) the Claude/adapter call fails repeatedly (check dv_harness/config.py's "claude" block and wherever the adapter is invoked in engine.py for existing retry/error-handling to build on, don't invent a parallel retry mechanism), (b) EDA license is full (dv_harness/preflight.py already has a real license check -- \`eda_license\` -- reuse its CheckOutcome, don't re-implement license checking), (c) the farm/LSF queue is congested (preflight.py's queue check, same reuse principle). In DEGRADED mode, the harness must continue collecting/persisting real data (job status polling, log collection, snapshot saves) but must NOT attempt any judgment-requiring stage transition (no adapter calls proposing a verdict/next action) until the condition clears. Wire this as an explicit, observable state (e.g. a DEGRADED status surfaced in \`dv-harness status\`), not a silent internal branch. Real tests: simulate each of the 3 trigger conditions and assert the harness enters DEGRADED and continues data collection without attempting a judgment call; assert it exits DEGRADED and resumes normal operation once the condition is simulated as cleared.
4. Update relevant docs (check for an existing architecture doc under docs/ describing engine.py's stage lifecycle -- extend it rather than creating a competing one if you find one).

Write a report to .work/harness-reliability-report.md. Run the full engine.py-related test suite (not just your own new tests) yourself and confirm pass before reporting DONE -- run_stage()/loop() are heavily tested already and a change here has real regression risk. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:reliability', phase: 'Build', model: 'claude-opus-5'})

const selfTestCi = agent(`${NOTE}

## Your task: harness self-test CI for DV Agent Harness L5

User's own spec (Traditional Chinese, authoritative): "harness 自我測試：對 harness 本身的腳本做 CI。agent 的基礎設施壞掉比 agent 判斷錯更難察覺" (the harness's own infrastructure breaking is harder to notice than the agent making a wrong judgment call -- CI for the harness's own scripts).

This repo currently has NO CI configuration at all (confirmed: no .github/workflows/ directory exists). It has a large real pytest suite (dv_harness_tests/, 2300+ tests) and, per the just-completed "Production-Grade Execution Governance" effort's own finish-report finding, an EXISTING but load-sensitive \`test_collection_health_gate\`/self-audit mechanism -- read dv_harness/cli.py's \`self-audit\` subcommand and whatever module backs it FIRST (grep for "self_audit" or "self-audit" across dv_harness/) before building anything new; your job is to wire CI around what's real, not duplicate it.

Concrete requirements:
1. Add a real GitHub Actions workflow (.github/workflows/dv-harness-ci.yml) that runs on push/PR: install deps, run \`python -m pytest dv_harness_tests/ -q\`, and run the existing self-audit/collection-health check. Since this repo has no GitHub remote configured yet (confirmed earlier this session -- \`git remote -v\` is empty), this workflow file will not actually execute anywhere until a remote exists; write it as real, correct, ready-to-activate infrastructure and disclose this honestly in your report exactly like the gh-CLI/PR-only effort disclosed its own "coded but not yet installed" hooks -- do not claim it is "running" when it cannot be.
2. Because the harness ALSO runs meaningful checks that are not plain pytest (dv_harness/preflight.py's own checks, git_governance.py's hook logic, the static checkers this repo's own generated environments use), add a second, lighter-weight local-runnable script (e.g. tools/self_test.sh or a new \`dv-harness self-test\` CLI subcommand, whichever composes better with what already exists -- check first) that a developer or a scheduled task can run WITHOUT needing GitHub Actions, covering at minimum: the full pytest suite, an import-sanity check across every module in dv_harness/ (catches a broken import before any real usage does), and a check that every documented CLI subcommand at least parses its own --help without crashing (a real, cheap regression net against the "harness's own scripts are broken" failure mode the user named).
3. If test_collection_health_gate's own hard-coded 25s timeout (flagged as a known, load-sensitive flake by the just-completed governance effort's finish report) is something you can reasonably widen without deep investigation, do so as a small, clearly-labeled fix-up (this was explicitly named as a low-urgency hygiene item in that report's own recommended-next-action list) -- but do not treat this as your primary task; only fix it if it's a quick, low-risk touch to a file you're already reading for point 1.
4. Real test: run your new self-test entry point yourself against this actual repo and confirm it genuinely passes/fails correctly (e.g. temporarily break an import in a scratch copy, or use a synthetic fixture, to prove the import-sanity check actually catches something -- don't just assert it runs without checking it detects a real problem).

Write a report to .work/harness-self-test-ci-report.md. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:self-test-ci', phase: 'Build'})

const [exemptionsResult, reliabilityResult, selfTestCiResult] = await parallel([
  () => exemptions,
  () => reliability,
  () => selfTestCi,
])

phase('Review')

const review = await agent(`Independently review this 3-workstream "exemptions.yaml + harness reliability (dry-run/checkpoint/degradation) + self-test CI" effort for DV Agent Harness L5. Read all 3 reports in full first:

D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\exemptions-yaml-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\harness-reliability-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\harness-self-test-ci-report.md

Raw returned results (cross-reference against the report files):

### exemptions
${exemptionsResult}

### reliability
${reliabilityResult}

### self-test-ci
${selfTestCiResult}

Verify by running real commands yourself -- never by trusting any report's prose:
1. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count. This is the highest-risk item to check given the reliability workstream touched engine.py's core run_stage()/loop() -- specifically confirm no regression in the existing engine/gates/routing test files.
2. Confirm dry-run mode genuinely makes zero adapter calls / zero LSF submissions -- read the actual gating code, don't trust a test's assertion alone; try to construct a case that would slip through if you can.
3. Confirm the auto-checkpoint retention policy actually bounds disk usage (read the prune logic, confirm a test exercises it past the retention limit).
4. Confirm DEGRADED mode genuinely reuses preflight.py's existing license/queue checks rather than re-implementing them (grep for duplicate license-check logic).
5. Confirm exemptions.yaml's valid_until field is genuinely required by the schema (try to construct a schema-valid entry with no expiry and confirm it's rejected).
6. Confirm the exemptions review-queue mechanism doesn't silently assume dv_harness/question_queue.py exists (grep for any import of a module that doesn't exist in this repo).
7. Confirm the CI workflow file and self-test script are both honestly disclosed as "not yet running anywhere" given no GitHub remote exists, not overclaimed as active.
8. Check for git hygiene issues: confirm none of the 3 workstreams touched dv_harness/regression_reporter.py, evidence_db.py, or vip_distill.py (those belonged to a different concurrent effort), and confirm no whole-file 'git add' swept in unrelated uncommitted changes to config.py/cli.py/CLAUDE.md.

Report a clear verdict (APPROVED / NEEDS_FIX) with concrete, evidence-cited findings.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { exemptionsResult, reliabilityResult, selfTestCiResult, review }
