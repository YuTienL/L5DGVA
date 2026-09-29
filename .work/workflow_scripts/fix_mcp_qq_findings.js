export const meta = {
  name: 'fix-mcp-question-queue-findings',
  description: 'Fix the 2 core-promise-breaking defects (MCP not actually read-only; question-queue Tier-3 can be silently bypassed) plus git hygiene, then commit all 4 workstreams',
  phases: [
    { title: 'Fix', detail: 'read-only MCP fix + tier-bypass fix, in parallel (disjoint files)' },
    { title: 'Integrate', detail: 'minor fixes + gitignore + Q-ID delegation + commit everything per-path' },
  ],
}

const CONTEXT = `
Background: the just-completed "self-describing environment + MCP + question-queue +
bind-connectivity" effort's independent review found 2 defects that break the effort's
own core promises, plus several minor issues and a real git-hygiene hazard. Nothing has
been committed yet for these 4 workstreams. This session has other concurrent workstreams
that may still be active in the same shared tree -- before editing any shared file, run
'git status --short' and 'git diff <file>' first. Before committing, verify 'git diff
--cached <file>' shows only your own intended change.
`

phase('Fix')

const readOnlyFix = agent(`${CONTEXT}

## Your task: fix the MCP server's read-only violation (REAL defect, proven by the reviewer)

The review proved dv_harness/mcp/ is NOT actually read-only, despite its whole design premise being enforced read-only access. Read dv_harness/mcp/runtime.py and dv_harness/evidence_db.py in full first.

The exact defect: dv_harness/mcp/runtime.py's ReadOnlyMcpContext opens an EvidenceStore via \`EvidenceStore(self.evidence_db_path)\`, which in evidence_db.py's __init__ does:
\`\`\`
self.db_path.parent.mkdir(parents=True, exist_ok=True)   # filesystem write
self._conn = duckdb.connect(str(self.db_path))           # READ-WRITE, creates the file if missing
for stmt in _SCHEMA_STATEMENTS:
    self._conn.execute(stmt)                              # CREATE TABLE / CREATE SEQUENCE
\`\`\`
The reviewer proved this live: calling query_regression through the MCP context against a non-existent DB path created the directories and a real ~536KB duckdb file; against a pre-existing partial-schema DB it added 9 tables and changed the file's hash.

Why the existing tests miss it: the AST-based read-only-boundary test only scans files under dv_harness/mcp/ -- the actual mkdir/execute calls live in evidence_db.py, outside that scan's scope. The byte-identical-files test seeds the DB via EvidenceStore first, so by hash-comparison time the schema already exists and the DDL calls are no-ops -- the non-existent-DB and partial-schema cases were never exercised.

Concrete fix required:
1. Add real \`read_only: bool = False\` support to EvidenceStore.__init__ in dv_harness/evidence_db.py -- when True, use \`duckdb.connect(str(self.db_path), read_only=True)\` (verified by the reviewer to raise duckdb.IOException on a missing file and block DDL with InvalidInputException) and skip the mkdir/schema-creation entirely.
2. Change dv_harness/mcp/runtime.py's ReadOnlyMcpContext to open its EvidenceStore with read_only=True.
3. Since query_regression against a genuinely non-existent DB must still behave sensibly for a caller (not just throw an unhandled IOException), decide and implement the right MCP-level behavior: likely catching the read-only-open failure and returning a clean "no evidence database exists yet" result (matching this module's own established honest-NOT_AVAILABLE convention) rather than a raw exception propagating to the MCP client. Document your choice.
4. Add a NEW test (the review explicitly names this as missing) that points the MCP context at a genuinely non-existent DB path and confirms: (a) no directory is created, (b) no file is created, (c) a clean result/error is returned, not an unhandled exception. Add a second test confirming a pre-existing DB's file hash is byte-identical after driving every verb AND confirming this holds even when the DB does NOT already have the full schema pre-seeded (the exact gap the review found in the existing test) -- i.e. seed the DB with only a partial/different table set first, then verify no new tables get added.
5. Run the full relevant test suite (dv_harness_tests/test_mcp_*.py, test_evidence_db*.py) and confirm pass, including your new tests.

Write a report to .work/gap-fix-mcp-readonly-report.md, explicitly showing the before/after: reproduce the reviewer's exact repro (create-dirs-and-file, add-9-tables) against the FIXED code and confirm it no longer happens. Report DONE/BLOCKED with a one-line test summary.`, {label: 'fix:mcp-readonly', phase: 'Fix'})

const tierBypassFix = agent(`${CONTEXT}

## Your task: fix the question-queue Tier-3 bypass (2 REAL, proven defects that break the system's core promise)

The review proved dv_harness/question_queue.py's classify_tier() can be bypassed in two independent, both-reachable-through-shipped-code ways, letting a genuine Tier-3 (cannot-assume, must-escalate) question resolve silently at Tier 1 with a machine-generated answer. Read dv_harness/question_queue.py and dv_harness/schemas/question.schema.json in full first.

### Defect F3-a: a Tier-2 auto-assumption permanently suppresses a later genuine Tier-3 escalation
classify_tier() returns Tier 1 for ANY prior decision found in decisions.json, without checking whether that decision came from a human or from the harness's own earlier Tier-2 auto-assumption (add_question persists a machine decision for every Tier-2 case, with source="tier2_auto_assumption"). Reviewer's exact repro: ask a low-risk-looking question first (no risk flags) -> Tier 2, auto-assumed, decision persisted. Ask the SAME question_key again, this time with affects_pass_fail_verdict=True, affects_spec_intent=True, affects_read_only_file_change=True, blast_radius="unbounded" (i.e. every Tier-3 hard trigger set) -> classify_tier() STILL returns Tier 1 ("decisions_store_hit"), answered with the harness's own earlier guess. Zero human ever sees it. It doesn't appear in any digest (build_digest only batches status in OPEN/ASSUMED, and this resolves as SELF_RESOLVED). It's not reversible (no CLI verb clears a persisted decision).

### Defect F3-b: manifest_lookup resolves before the hard-trigger check even runs, and doesn't verify relevance
The resolvable_from_manifest check runs BEFORE the hard-trigger block in classify_tier()'s ordering, and the lookup itself is keyed only on context_path -- it never checks whether the fact it found actually answers the question being asked. Reviewer's exact repro: a pure spec-intent question ("Is a dropped packet flagged in TX_ERR a legal drop per spec, or a real DUT failure?") with affects_pass_fail_verdict/affects_spec_intent/unbounded blast_radius all set -> resolves at Tier 1 via "resolvable_from_manifest", answered with an unrelated register dict from the manifest. This matters especially because the just-completed effort's own finish report recommends wiring manifest_lookup into every QuestionQueueStore caller as a next step -- doing so with this ordering bug active would make the bypass live in production immediately.

### Required fix (the review names the minimal shape; implement it precisely)
1. Move the hard-trigger check (is_cannot_assume(), the affects_pass_fail_verdict/affects_spec_intent/affects_read_only_file_change checks) to run FIRST in classify_tier(), before either the prior-decision shortcut or the manifest_lookup shortcut.
2. Only treat a prior decision as a valid Tier-1 shortcut when current.source == "human_answer" -- a "tier2_auto_assumption"-sourced prior decision must NOT suppress a later Tier-3-triggering ask of the same question_key; that later ask must still classify as Tier 3 and escalate for real, even though the question_key has an existing decision on file.
3. Gate the manifest_lookup shortcut on is_cannot_assume(context) == False -- if the question's own context already triggers a hard Tier-3 condition, no manifest lookup should ever be consulted to resolve it, regardless of what the lookup would return.
4. Add \`if tier==3 then blocking==true\` as a real, enforced \`allOf\`/\`if\`/\`then\` rule in question.schema.json (the review proved a hand-built {tier:3, blocking:false, status:"SELF_RESOLVED"} record currently passes validate_question() cleanly -- it must not after this fix).
5. Add a new \`question-queue revoke\` CLI verb (and the underlying QuestionQueueStore method) that clears/invalidates a persisted decision for a given question_key -- the review notes there is currently no way to undo an auto-assumed decision short of hand-editing decisions.json, which decisions.md itself says not to do.
6. Reproduce BOTH of the reviewer's exact repros (F3-a and F3-b) as new tests, confirm they now correctly classify as Tier 3 / escalate / do NOT silently resolve, after your fix. These are the two most important tests in this entire fix -- do not consider this task done until both repros are literally reproduced and shown fixed.
7. Run the full dv_harness_tests/test_question_queue.py + test_cli_question_queue.py suite and confirm pass, including all new tests.

Write a report to .work/gap-fix-question-queue-tier-bypass-report.md with the explicit before/after repro output for F3-a and F3-b. Report DONE/BLOCKED with a one-line test summary.`, {label: 'fix:tier-bypass', phase: 'Fix', model: 'claude-opus-5'})

const [readOnlyFixResult, tierBypassFixResult] = await parallel([() => readOnlyFix, () => tierBypassFix])

phase('Integrate')

const integrate = await agent(`${CONTEXT}

## Read-only fix result:
${readOnlyFixResult}

## Tier-bypass fix result:
${tierBypassFixResult}

## Your task: minor fixes, git hygiene, Q-ID delegation, then commit all 4 original workstreams + these fixes

Read .work/mcp-env-manifest-report.md, .work/mcp-server-report.md, .work/mcp-question-queue-report.md, .work/mcp-bind-connectivity-report.md for the original 4 workstreams' full file lists, plus the two fix reports above.

### Minor fixes required (all confirmed real by the review, all small)

**F4 (env_manifest.py traceability)**: env_manifest.py's dump-path handling (3 call sites, check around lines 215/253/322) treats a SUPPLIED-BUT-NONEXISTENT dump path identically to "no path was supplied at all" -- both report NOT_AVAILABLE with reason "no VIP config dump exists yet", silently discarding the actually-supplied (wrong) path. Fix: when a path IS supplied but does not exist, report a distinct reason making the real problem traceable, e.g. "supplied path does not exist: <path>", recording source.path as the real supplied path rather than None. Contrast with build_dut_facts_rtl, which already correctly lets a real failure against a real supplied file propagate -- match that honesty standard.

**F5 (stale comments)**: dv_harness/connectivity.py (around line 1158-1162 and again around 1360-1361) still contains comments asserting "dv_harness/question_queue.py does NOT exist yet" -- it exists now. Correct both to reflect reality (it exists; whether it's actually wired to yet is a separate, still-partially-open question depending on F6 below).

**F6 (Q-ID delegation)**: connectivity.build_t4_question_queue_entry(...)'s output currently fails question_queue.validate_question() outright (7 schema errors reproduced by the reviewer, including a caller-supplied q_id that defeats the repeat-question-rate=0 id-derivation guarantee, and a hardcoded blocking=True that isn't derived from tier classification). Fix: replace build_t4_question_queue_entry's body to delegate into the real, now-fixed dv_harness.question_queue.QuestionQueueStore.add_question() (its keyword parameters are domain, question, context_path, options, recommendation, assumption_if_unanswered -- exactly what build_t4_question_queue_entry already takes minus q_id and blocking, which the store now derives itself) rather than hand-building a dict. Verify the fixed function's output now passes validate_question() cleanly, and that connectivity.py's own tests still pass after this change.

**Also fix**: bind_connectivity's PROTOCOL_FINGERPRINTS unverified signal names (CSI2 CLK_LANE_HS/CLK_LANE_LP, DSI TE, USB3 TX_HS_P/N, PCIE PERST_N/TX_P/RX_P) are presented with no honesty caveat -- the review confirmed this fails SAFE today (a wrong fingerprint falls through to T3 human-confirmation, never a silent T2 auto-accept), so this is not a blocking defect, but add a short comment in connectivity.py documenting that these specific signal-name sets are illustrative/unverified-against-a-real-VIP-example and that the fail-safe behavior (full-set-required, case-sensitive match) is what makes that acceptable -- do not change the matching logic itself, it's correct as-is.

### Git hygiene (real, live hazard confirmed by the review)

.dv-harness/ is a git-tracked directory with 280 tracked files, and .gitignore currently excludes only .dv-harness/evidence/. The review found real, currently-modified/untracked runtime-state churn under it (events.jsonl, state.json, memory/index.json, 50+ new memory/**/MEM-*.json records, blackboard/*.json, and critically lsf/watcher.pid + lsf/watcher.log) that a careless \`git add -A\` would sweep into any commit. Fix: extend .gitignore with entries for .dv-harness/lsf/, .dv-harness/blackboard/, .dv-harness/state.json, .dv-harness/events.jsonl (check existing .gitignore conventions first, match the style; do not remove or weaken the existing .dv-harness/evidence/ entry).

### Final step: commit everything, per-path, carefully

This shared working tree has MANY files from concurrent workstreams. Run \`git status --short\` and identify precisely which files belong to THIS effort (the original 4 workstreams' files, listed in their 4 report files, PLUS every file touched by the 2 fix workstreams above, PLUS your own .gitignore change and minor fixes) versus anything else still uncommitted from a different concurrent effort (do not touch or commit anything you cannot positively attribute to this effort's own file list). For any SHARED file (cli.py, CLAUDE.md, .claude/skills/CORE/ip-uvm-dv-gen/SKILL.md, .gitignore) that may carry hunks from other concurrent work, use the hand-scoped 'git apply --cached' patch technique (used successfully many times today in this repo -- search git log for worked examples) to stage only this effort's own hunks. Verify with 'git diff --cached <file>' before each commit. You may split into as many commits as makes sense for clean attribution (e.g. one per original workstream plus one for the fixes), but do not commit anything outside this effort's real scope, and NEVER use 'git add -A' or 'git add .dv-harness' given the hazard just described -- add .dv-harness paths (if any belong to this effort, e.g. a new .dv-harness/exemptions/ path from an earlier unrelated workstream -- check first) individually by exact path only.

Run the full project test suite (python -m pytest dv_harness_tests/ -q) one final time and confirm pass (expect pre-existing pueue-daemon-related failures unrelated to this effort, as already triaged by the review -- do not attempt to fix those, they belong to a different workstream).

Report DONE/BLOCKED with: confirmation of all minor fixes, confirmation .gitignore was updated, the exact commit SHAs and file lists, and final git status showing nothing from this effort remains uncommitted.`, {label: 'integrate-and-commit', phase: 'Integrate', model: 'claude-opus-5'})

return { readOnlyFixResult, tierBypassFixResult, integrate }
