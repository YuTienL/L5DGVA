export const meta = {
  name: 'self-describing-bind-reverify',
  description: 'Re-verify with CURRENT real evidence that env.manifest.json / MCP query interface / question-queue protocol / bind-connectivity system genuinely matches the detailed spec (4 fact sources, 3-tier ask protocol, T1-T4 confidence, 3 machine gates, checker/scoreboard table, per-row lock), close only genuine remaining gaps',
  phases: [
    { title: 'Audit', detail: '10 spec-section audits against already-built code, in parallel' },
    { title: 'Close', detail: 'sequential fix pass over every confirmed real, in-scope gap' },
    { title: 'Report', detail: 'independent verification' },
  ],
}

const CORE_PRINCIPLES = `
This exact "self-describing environment + MCP + question-queue +
bind-connectivity" theme was already built earlier this session, in a
4-workstream effort (task wbe6kxdx2): dv_harness/env_manifest.py +
schemas/env_manifest.schema.json + schemas/register_map.schema.json +
templates/uvm_env_manifest/dv_env_manifest_pkg.sv; dv_harness/mcp/ (7 files,
real mcp==2.1.1 SDK, exactly 5 verbs: get_vip_config, get_dut_port,
get_register, get_topology, query_regression); dv_harness/question_queue.py
+ schemas/question.schema.json (3-tier classify_tier(), owner routing,
QuestionQueueStore with add/list/answer/digest/metrics/revoke);
dv_harness/connectivity.py (4-tier bind classifier T1-T4,
assert_t3_never_auto_accepted(), 4 real input collectors, count-check
self-check identity verify_self_check_identity(), 3-gate pipeline, per-row
lock/diff store, checker/scoreboard table generator with
REQUIRED_HUMAN_INPUT sentinel). CLAUDE.md gained a "Bind-Location Rules
(2026-09-03)" section (4 hard rules). Two real defects found by an
independent review were later fixed (MCP read-only enforcement genuinely
enforced via duckdb read_only=True; question_queue Tier-3 escalation
bypass fixed via hard-trigger-first reordering + human-decision-source
gating). A separate later effort added dv_harness/reference_pattern_audit.py
(reference command.txt line-by-line register-write audit),
dv_harness/uvm_generator/bind_verification_lint.py + connectivity.py's
GateStatus.PENDING/NOT_YET_RUN + assert_bind_gates_checkpoint() (making the
3 gates a REQUIRED, not just available, checkpoint), and
dv_harness/uvm_generator/templates/sim_scripts/check/reg_write_safety.py
(generic blind-register-write detector).

Your job is NOT to assume this prior work already satisfies the CURRENT,
more detailed spec below just because the theme matches -- re-verify with
CURRENT real evidence (grep real call sites, read real code, run real
commands where possible) whether EVERY specific requirement in your
assigned section is genuinely real and matches, not just that something
similarly-named exists. Pay special attention to anything in the spec below
that is MORE specific than what was built before (e.g. the exact 4 tracked
metrics, the exact env.manifest.json 3-layer fact sources, decisions.md
answer-persistence, hierarchy-diagram visualization) -- these are real
candidates for genuine remaining gaps.

Verdict format per requirement, one of:
- READY: real, working, evidenced, matches the spec's specifics.
- PARTIAL: real but incomplete -- name exactly what's missing vs. the spec.
- BLOCKED: does not exist, a real closeable gap.
Cite real file:line or real command output for every verdict. Audit only --
do not modify any file in this phase.
`

phase('Audit')

const auditEnvManifest = agent(`${CORE_PRINCIPLES}

## Your scope: "讓環境自我描述" -- env.manifest.json's 3 fact-source layers

### VIP layer
- svt_*_configuration real field values via a zero-time dump test (end_of_elaboration_phase, config object sprint()/JSON) -- reflects what THIS environment actually applied, not doc defaults.
- VIP version/release-notes/feature-matrix extracted from $DESIGNWARE_HOME + version files.
- User guide PDF distilled OFFLINE into a reference file, never loaded into runtime context.

### DUT layer
- port/parameter via slang or 'verible-verilog-syntax --export_json'.
- register map via RAL or IP-XACT converted to JSON -- agent must never read the raw Excel.
- address map / clock-reset topology from the existing SoC spec pipeline.

### Env layer
- uvm_top.print_topology() + +UVM_CONFIG_DB_TRACE from ONE smoke run -- full component hierarchy + every config_db set/get pair. This is explicitly called out as the most underrated self-description tool (agent should never guess "is this agent active or passive").
- testlist/vPlan/coverage-model correspondence.

All of this unifies into env.manifest.json: script-generated, diffable, git-tracked. The spec explicitly says: extend the EXISTING JSON IR pipeline (run_profile.json et al), don't build a new one.

Check dv_harness/env_manifest.py against every bullet above -- which are real and which are still missing/stubbed. Report your verdict per the required format, once per bullet (group by VIP/DUT/Env layer).`, {label: 'audit:env-manifest', phase: 'Audit'})

const auditMcpInterface = agent(`${CORE_PRINCIPLES}

## Your scope: MCP query interface (not free file reads)

Exactly 5 verbs required: get_vip_config(protocol, instance), get_dut_port(module, pattern), get_register(name), get_topology(path), query_regression(filter). Benefits claimed: queries are auditable, results have fixed schema, permissions are controllable (read-only tool really is read-only), and context only holds the response, never the whole file. CLAUDE.md should hold only an index + rules (which protocols exist, where the manifest is, which paths are read-only); details live in skills/reference, loaded on demand. Multi-protocol environments should get one CLAUDE.md per protocol.

Check dv_harness/mcp/'s real verb signatures against these 5 exactly (names AND parameter shapes). Confirm the read-only enforcement is genuinely real (re-verify the earlier-fixed duckdb read_only=True boundary still holds). Check whether CLAUDE.md's current content actually follows the "index + rules only, details on demand" principle, or has grown to include large amounts of detail that should have been pushed to skills/reference instead (this file has grown very large this session -- an honest self-assessment is warranted). Check whether a per-protocol CLAUDE.md split exists or is needed given this project is still USB-only today (if there's only one protocol, this requirement may be correctly not-yet-applicable -- say so rather than flagging it as a gap).

Report your verdict per the required format for the 5 verbs, the auditability/schema/read-only-permission properties, and the CLAUDE.md index-only principle, separately.`, {label: 'audit:mcp-interface', phase: 'Audit'})

const auditQuestionProtocol = agent(`${CORE_PRINCIPLES}

## Your scope: 問人的協定 (the ask-protocol) -- 3-tier default-don't-ask + exact question schema + routing + batching

### 3-tier disposition
1. Can self-check -> check, don't ask.
2. Can't find but safe to assume -> record the assumption, note it in the report, keep going. Test: "if this assumption is wrong, the worst outcome is wasting one regression run."
3. Cannot assume -> stop, write to question queue, escalate. Hard-coded criterion: anything affecting pass/fail determination, spec intent, or whether a read-only file should change is NEVER assumable.

### Exact question JSON schema required (verbatim)
{"id": "Q-20260903-007", "blocking": true, "domain": "vip", "owner": "dv-owner", "question": "...", "context_path": "logs/csi/fail_042/", "options": ["...", "..."], "recommendation": "...", "assumption_if_unanswered": null}

### 3 design points required
- Give OPTIONS, never open-ended questions -- agent should pre-do the homework and propose 2-3 candidates + a recommendation, so a human's reply cost drops from 5 minutes to 10 seconds.
- Route by owner: VIP questions -> DV owner or Synopsys AE, DUT questions -> designer, env questions -> DV owner. Without routing, everything lands on one person.
- Batch into a digest (once/day or once-per-run-escalation), never real-time ping.
- Answers written back in the SAME format, agent resumes from that session.

Check dv_harness/question_queue.py's classify_tier() against the exact 3-tier logic and hard-coded escalation criterion, question.schema.json against the exact JSON shape above (field-by-field), and whether owner-routing + options-not-open-ended + digest-batching are all real, working behaviors (not just schema fields that happen to exist unused). Report your verdict per the required format for each of: 3-tier logic, exact schema match, options-required, owner-routing, digest-batching, answer-format-symmetry.`, {label: 'audit:question-protocol', phase: 'Audit'})

const auditAnswerPersistenceMetrics = agent(`${CORE_PRINCIPLES}

## Your scope: 答案沉澱 (answer persistence) + 4 tracked metrics

### Answer persistence
Every answered question MUST be written back into the manifest or a decisions.md, with date and basis. Without this step, the same question gets asked again next week -- the exact failure mode that degrades L5 back into "a noisy L3."

### 4 metrics (exact)
1. Self-resolve rate -- fraction of questions the agent answered itself, target > 90%.
2. Blocking questions/week -- a direct proxy for human labor cost.
3. Repeat-question rate -- greater than 0 means the persistence mechanism isn't working.
4. Assumption-overturn rate -- too high means Tier-2's criterion is set too loose.

Check: does answering a question in question_queue.py actually write back to env_manifest.json or a real decisions.md file (grep for this write-back path)? Does anything actually COMPUTE these 4 exact metrics today (question_queue.py's real metrics() function, per earlier session work -- confirm what it currently computes vs. these 4 named ones specifically)? Run it against real or synthetic data if possible and show real numbers.

Report your verdict per the required format for answer-persistence and for each of the 4 metrics separately.`, {label: 'audit:answer-persistence-metrics', phase: 'Audit'})

const auditConnectivityManifest = agent(`${CORE_PRINCIPLES}

## Your scope: connectivity manifest -- the 4 real fact-extraction inputs

1. DUT instance tree -- 'simv -ucli -do "scope -tree"' OR 'slang --ast-json' -> full hierarchy path.
2. Interface signal set -- module port list, for protocol-fingerprint matching.
3. Existing binds -- repo-wide 'grep -n "^\\s*bind "' -> already-settled facts.
4. VIP instances -- uvm_top.print_topology() + +UVM_CONFIG_DB_TRACE -> VIP count + virtual-interface bindings. Explicitly called out: a set with no matching get is direct, pre-simulation-completion evidence of a wrong vif connection.

Check dv_harness/connectivity.py's 4 real input collectors against these 4 exactly -- method used, what it extracts, and specifically confirm the config_db set-without-get detection is real and actually implemented (not just conceptually described). Report your verdict per the required format for each of the 4 inputs.`, {label: 'audit:connectivity-manifest', phase: 'Audit'})

const auditTiersSelfCheck = agent(`${CORE_PRINCIPLES}

## Your scope: T1-T4 confidence tiers + the count self-check equation

### Tiers (exact)
T1 settled -- existing bind or config_db already specifies the path. Adopt directly, no re-derivation.
T2 structural match -- port signal set matches a protocol fingerprint (AXI needs AWVALID/AWREADY/WLAST/BRESP...; CSI-2 needs D-PHY lane + clock lane). High confidence, can auto-adopt but must be listed in the report.
T3 naming heuristic -- inferred only from names like u_usb3_top/i_pcie_x2. ALWAYS needs human confirmation, must never be auto-adopted. Named as the most error-prone tier: multi-instance IP, generate-block-produced paths, inconsistent wrapper depth all make a name look right while the path is wrong.
T4 undecidable -- goes to question queue.

### 3 typical VIP-count-mismatch sources
- Multiple instances: VIP count should equal ACTIVE interface count, not IP count.
- Interconnect: on one AXI fabric, passive-monitor count != master-agent count -- the PATH COMBINATION count is the scoreboard's real comparison dimension.
- Role inversion: when DUT is initiator, VIP should be slave/responder -- determined from PORT DIRECTION, never from naming.

### Required output
A matrix: DUT instance | interface | direction | role | VIP type | count | active/passive | bind target | tier -- plus a self-check equation: sum(interfaces needing verification) = sum(VIP instances) + sum(explicitly listed exemptions). A mismatch requires an explicit per-row explanation (e.g. "this port is tied off, not verified") -- no unexplained gap allowed.

Check dv_harness/connectivity.py's tier classifier and verify_self_check_identity() against this exact equation and the 3 mismatch-source handling (especially role-determined-by-port-direction-not-naming). Confirm assert_t3_never_auto_accepted() genuinely blocks T3 auto-adoption. Report your verdict per the required format for tiers, the matrix output, and the self-check equation separately.`, {label: 'audit:tiers-self-check', phase: 'Audit'})

const auditBindGates = agent(`${CORE_PRINCIPLES}

## Your scope: bind-location 4 hard rules + 3 machine gates

### 4 hard rules (must be in CLAUDE.md, not left to agent judgment)
1. Binding to a bare module name applies to ALL instances -- fine at IP level, usually wrong at SoC level (SoC must use full instance path).
2. All bind statements centralized in a standalone *_bind.sv under tb/. RTL files are read-only -- agent must never insert a bind directly into RTL.
3. Clock/reset passed explicitly through the bind's own port list -- hierarchical cross-level XMR grabs are forbidden (they break at gate-level or after a wrapper swap).
4. Any bind-target path containing generate/for-loop constructs must be expanded to explicit literal indices -- no wildcards accepted.

### 3 machine gates (must run BEFORE a human reviews the plan -- what the human sees must be "a verified proposal," not "my guess")
1. Elaboration check -- 'vcs -elab_only' or slang. A nonexistent bind path errors immediately, cheapest check, run first.
2. Static connectivity -- zero-time run. Every bind point checked: clock toggles, reset deasserts, required signals are non-X. An interface with no activity is flagged.
3. Transaction activity -- one shortest directed test, confirm every VIP monitor receives >=1 transaction. A monitor receiving 0 is a wrong connection. This gate catches the vast majority of bind errors and is the ONLY method that catches "path is legal but connected to the wrong instance." Recommended: make this a standing 'just connectivity-check' run on every RTL update.

Check CLAUDE.md's Bind-Location Rules section against the 4 rules exactly, and dv_harness/connectivity.py + bind_verification_lint.py against the 3 gates exactly (including whether gate 3 is genuinely wired as a standing 'just connectivity-check' recipe run on every RTL update, or only available as a manually-invoked function). Report your verdict per the required format for the 4 rules and the 3 gates separately.`, {label: 'audit:bind-gates', phase: 'Audit'})

const auditScoreboardTable = agent(`${CORE_PRINCIPLES}

## Your scope: checker/scoreboard planning table

Every check must be classified into exactly one of 3 categories, no ambiguity:
- Protocol check -> use the VIP's BUILT-IN checks, never hand-write. The agent's job is to list which built-in checks are disabled and why -- that list IS the review focus.
- Data integrity -> scoreboard.
- System level -> cross-interface-path scoreboard, performance, DECERR.

Every scoreboard must fill EVERY one of these fields, and an empty field automatically becomes a question-queue entry:
- Comparison endpoints (source port / sink port, with hierarchy path)
- Matching key (ID / tag / address / frame number)
- Ordering (in-order, out-of-order, and the tolerance window depth)
- Transform rules (width conversion, packetization, byte enable)
- Legal drop/backpressure conditions
- Reset-time flush behavior
- Orphan/unmatched threshold and detection timing

Explicitly called out: false-pass scoreboards are almost always caused by "ordering" and "legal drop" being left undefined -- these two fields should be MANDATORY HUMAN REVIEW, agent defaults not accepted.

Check dv_harness/connectivity.py's checker/scoreboard table generator against the exact 3-category classification and the exact 7 required fields, and confirm the REQUIRED_HUMAN_INPUT sentinel is specifically applied to ordering AND legal-drop (not just "some fields"). Report your verdict per the required format for the 3-category classification and each of the 7 fields separately.`, {label: 'audit:scoreboard-table', phase: 'Audit'})

const auditConfirmationLocking = agent(`${CORE_PRINCIPLES}

## Your scope: confirmation granularity + locking + presentation

- Human confirmation must be PER-ROW (per-interface / per-scoreboard), never a single whole-document approve -- a whole-doc approve on 20 interfaces is equivalent to no review at all.
- Confirmation writes back to the manifest: confirmed_by, confirmed_date, evidence.
- A confirmed row is LOCKED -- the agent must never change it; changing it requires proposing a diff and re-confirming.
- After an RTL update, only the rows that actually diffed need re-confirmation -- this is what keeps confirmation cost from scaling linearly with time.
- Recommended presentation: 3 artifacts together -- connectivity matrix (table), hierarchy diagram (marking bind points and VIP mount locations), question queue. The first two let a human spot mismatches at a glance; the third is the only piece that needs real human thought.

Check dv_harness/connectivity.py's real per-row lock/diff store against every bullet above -- especially: is locking genuinely enforced (an attempt to silently change a locked/confirmed row should fail or require an explicit diff+reconfirm flow, not silently succeed)? Does a diff-triggered-re-confirmation-only path exist (vs. requiring full re-confirmation after any RTL change)? Does a real hierarchy-diagram artifact get generated (this is the least likely piece to already exist -- check honestly), or does the system only produce the matrix + question queue (2 of the 3 recommended artifacts)?

Report your verdict per the required format for per-row confirmation, locking, diff-triggered-reconfirmation, and each of the 3 presentation artifacts separately.`, {label: 'audit:confirmation-locking', phase: 'Audit'})

const results = await parallel([
  () => auditEnvManifest, () => auditMcpInterface, () => auditQuestionProtocol,
  () => auditAnswerPersistenceMetrics, () => auditConnectivityManifest, () => auditTiersSelfCheck,
  () => auditBindGates, () => auditScoreboardTable, () => auditConfirmationLocking,
])
const [envManifestR, mcpInterfaceR, questionProtocolR, answerPersistenceMetricsR,
  connectivityManifestR, tiersSelfCheckR, bindGatesR, scoreboardTableR, confirmationLockingR] = results

phase('Close')

const auditSummaries = [
  ['env.manifest.json 3 fact-source layers (VIP/DUT/Env)', envManifestR],
  ['MCP query interface (5 exact verbs + read-only + CLAUDE.md index-only)', mcpInterfaceR],
  ['Ask-protocol: 3-tier disposition + exact question JSON schema + routing/batching', questionProtocolR],
  ['Answer persistence + 4 tracked metrics', answerPersistenceMetricsR],
  ['Connectivity manifest: 4 real fact-extraction inputs', connectivityManifestR],
  ['T1-T4 confidence tiers + count self-check equation', tiersSelfCheckR],
  ['Bind-location 4 hard rules + 3 machine gates', bindGatesR],
  ['Checker/scoreboard planning table (3-category + 7 required fields)', scoreboardTableR],
  ['Confirmation granularity + locking + 3-artifact presentation', confirmationLockingR],
]

log('Audit phase complete. Closing confirmed real BLOCKED gaps one at a time, sequentially, to avoid concurrent-edit collisions with the other workflows active in this session.')

const closeResults = []
for (const [name, report] of auditSummaries) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CORE_PRINCIPLES}

This is a sequential gap-closing pass over a fresh re-verification of DV Agent Harness L5's self-describing-environment + MCP + question-queue + bind-connectivity system against a detailed spec. You are handling exactly ONE scope: **${name}**.

NOTE: MANY other agents/workflows are concurrently active in this repo right now (a 14-AI-mechanism audit+close workflow, a governance-architecture reverify workflow, an Obsidian-memory 25-phase reverify workflow, a verification-knowledge-assets reverify workflow, a live remote USB build). This file set (env_manifest.py, mcp/, question_queue.py, connectivity.py, CLAUDE.md) is exactly what several of those OTHER workflows may also be touching -- check git status/git diff on any file BEFORE touching it, and use the hand-scoped patch technique (git diff > patch, trim to your hunk, git apply --cached --check then --cached) for every file, never a broad git add. If a file you need to touch shows unexpected concurrent changes, re-read it fresh before patching, and re-diff after any conflict rather than forcing your original patch.

Its real, current audit finding (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. For every requirement marked READY: do nothing, just re-confirm the cited evidence.
2. For every requirement marked BLOCKED (a real, closeable gap): build it for real, extending the existing real code (env_manifest.py, mcp/, question_queue.py, connectivity.py) rather than a parallel mechanism.
3. For every requirement marked PARTIAL: complete the missing piece if genuinely bounded; if it's a large separate effort (e.g. a real hierarchy-diagram-rendering pipeline, if that's the gap), report NEEDS_SEPARATE_EFFORT instead.
4. Write real tests proving whatever you build actually works end-to-end.
5. Run the full relevant test suite for whatever you touched and confirm pass.
6. Commit your change for real (if you made one) with a clear, scoped commit.

Write a report to .work/gap-close-sdbind-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 40)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `close:${name}`, phase: 'Close', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Report')

const finalReport = await agent(`${CORE_PRINCIPLES}

Independently review this "re-verify self-describing-environment + MCP + question-queue + bind-connectivity against a detailed spec + close every confirmed real gap" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every audit report and every close-pass report in full first (search .work/ for files matching gap-close-sdbind-*-report.md).

Raw returned results, for cross-reference:

### Audits
${auditSummaries.map(([name, report]) => `#### ${name}\n${report}`).join('\n\n')}

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE: did the fix actually work, verified by you running something real?
2. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
3. Check git hygiene across all commits this pass made -- pay special attention here since this workflow ran concurrently with several others touching overlapping files; confirm no commit accidentally swept in another workflow's unrelated in-progress changes.

Report a clear verdict per section (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings.`, {label: 'final-report', phase: 'Report', model: 'claude-opus-5'})

return { auditSummaries: Object.fromEntries(auditSummaries), closeResults: Object.fromEntries(closeResults), finalReport }
