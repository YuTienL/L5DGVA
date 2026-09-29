export const meta = {
  name: 'obsidian-memory-25phase-reverify',
  description: 'Inventory + re-verify Claude CLI + Obsidian CLI + Git/Markdown Hybrid Engineering Memory against the user 25-phase spec with current real evidence, close only genuine gaps, emit the Phase-25 final report',
  phases: [
    { title: 'Inventory', detail: 'Phase 1+2: real repo inventory + Obsidian CLI capability detection' },
    { title: 'Audit', detail: '10 phase-group audits against the spec, in parallel, using the inventory' },
    { title: 'Close', detail: 'sequential fix pass over every confirmed real, in-scope gap' },
    { title: 'Report', detail: 'Phase 25 final report format, independently verified' },
  ],
}

const CORE_PRINCIPLES = `
Cross-cutting rules that apply to EVERY part of this effort (the user's own
words, authoritative):

- Claude CLI is the primary orchestration/reasoning/execution engine.
- Markdown + YAML + Git is the PERMANENT Engineering Memory storage layer.
- Obsidian CLI is a Knowledge Tool Layer, NOT the only storage interface --
  even if Obsidian CLI is unavailable, the whole Harness must still work.
  Obsidian GUI must never be a required dependency.
- Windows PC is the primary Claude CLI development end; Linux Server handles
  VCS/LSF/Verdi/fsdbreport/regression execution. Memory must support both.
- Never stuff large sim.log/FSDB/coverage databases directly into the
  Obsidian Vault. The Vault only holds condensed, reusable, traceable
  Engineering Knowledge -- large artifacts are referenced by path, not
  embedded.
- Do NOT analyze only -- implement. Do NOT stop just because Obsidian CLI is
  absent (fall back to filesystem Markdown mode; report PARTIAL, not
  BLOCKED). Inventory existing architecture FIRST. Prefer extending existing
  code over building a parallel/conflicting framework -- if you find the
  existing implementation is ALREADY MORE MATURE than what a phase below
  describes, KEEP the better existing architecture; do not downgrade it just
  to match this spec's wording literally.
- Remove stale comments/dead code in anything you touch. Every capability
  claim needs real evidence. When uncertain, report PARTIAL -- never claim
  READY without proof. All memory promotion needs verified evidence. Never
  store secrets. Never put large simulation artifacts in the Vault.
- If something requires human credentials/remote login, mark an explicit
  boundary and do not bypass security restrictions -- do not attempt any
  actual remote Linux execution in this effort; use local/synthetic tests
  for anything that would otherwise need it, and report that piece PARTIAL.
- The target is production-ready, not a demo.

Known prior work this session already built under this exact theme (real,
already committed -- verify current truth, do not assume these summaries
are still accurate without checking): a full "Obsidian+Git/Markdown Hybrid
Memory Integration" effort (memory_vault.py, memory_dedup.py,
memory_doctor.py, promote_to_organizational()), CLAUDE.md's own
"Engineering Memory Policy (2026-09-03)" section, and a later
"Debug-flow / regression / git-integration mechanics (2026-09-03,
obsidian-memory-debugflow, Workstream 3)" addendum describing
build_failure_signature()/search_related_memory_for_debug(), Job-Memory-only
FAIL updates, RE_AUDIT-PASS-triggers-promotion-evaluation, and
memory(<protocol>): <description> git commit conventions with
rtl_sha/tb_sha/knowledge_commit_sha traceability. Also a separate,
concurrently-running fresh audit of the "5-Level Memory Engine" AI
mechanism is in flight elsewhere in this session (different workflow,
different task) -- do not duplicate that effort's exact scope; this
workflow's job is to check against the user's 25-phase STRUCTURAL spec
specifically (vault layout, adapters, schema, skills, CLI commands, tests,
docs), which that other audit does not cover.

Verdict format for every phase/requirement you check, one of:
- READY: real, working, evidenced.
- PARTIAL: real but incomplete, or working only via a disclosed fallback
  (e.g. filesystem mode because Obsidian CLI is genuinely absent).
- BLOCKED: does not exist and nothing currently prevents building it (i.e.
  a real, closeable gap) -- distinct from a deliberately-scoped-out
  boundary (credentials/remote execution), which is PARTIAL with a named
  boundary, not BLOCKED.
Cite real file:line or real command output for every verdict. Do not modify
any file during audit -- audit only.
`

phase('Inventory')

const inventory = await agent(`${CORE_PRINCIPLES}

## Your task: Phase 1 (Repository Discovery) + Phase 2 (Obsidian CLI Capability Detection)

Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

### Phase 1 -- Repository Discovery
Fully inventory the current repository before anything else. At minimum check: CLAUDE.md, .claude/, .claude/agents/, .claude/skills/, tools/, scripts/, memory/, docs/, config/. Search for: memory, knowledge, blackboard, evidence, confidence, hypothesis, debug, regression, signoff, session, restore, traceability, change-impact. Build a real inventory (real file paths, real line counts/citations) of what already exists relevant to Engineering Memory. Do not assume anything is absent without checking. Build on the existing implementation; do not invent a conflicting parallel framework.

### Phase 2 -- Obsidian CLI Capability Detection
Confirm whether the PC environment has an installed Obsidian CLI or any usable Obsidian command-line interface. Run real capability detection (search PATH, check for known Obsidian CLI packages/binaries, check dv_harness's own code for any existing detect()/status() logic already built for this). Produce the exact required capability report:

Obsidian CLI Capability
-----------------------
Installed: YES / NO
Version:
Executable:
Vault access:
Search:
Read:
Create:
Update:
Properties:
Tags:
Links:
Status: READY / PARTIAL / BLOCKED

If Obsidian CLI does not exist: status is PARTIAL (never BLOCKED for this reason alone), with automatic fallback to filesystem Markdown mode -- confirm whether that fallback already exists in code (memory_vault.py or elsewhere) or is a real gap.

Return BOTH the full Phase 1 inventory (as structured text, organized by area: memory tiers, vault/adapters, schema, skills, CLI commands, tests, docs) AND the Phase 2 capability report. This combined output will be handed to 10 parallel follow-up audits as their shared ground truth -- be thorough and precise about exact file paths and line numbers so they don't have to re-discover the same things.`, {label: 'inventory', phase: 'Inventory', model: 'claude-opus-5'})

phase('Audit')

const AUDIT_HEADER = (inv) => `${CORE_PRINCIPLES}

## Shared inventory from Phase 1+2 (real, gathered just now -- your ground truth, do not re-discover from scratch)

${inv}
`

const auditVaultAdapter = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 3 (DV-Knowledge Vault structure) + Phase 8 (Obsidian CLI Adapter abstraction)

### Phase 3 requirements
A configurable knowledge root (not hardcoded path) -- example config shape:
memory: {provider: hybrid, vault_path: D:/DV/DV-Knowledge, obsidian_cli: auto, git_enabled: true}
Suggested vault structure (check what real structure exists, if any, and whether it matches or reasonably covers this shape -- exact folder names are illustrative, not sacred, per Core Principles):
00_Inbox/, 01_Projects/, 02_Protocols/{USB,PCIe,Ethernet,AMBA,MIPI,CAN-FD}/, 03_Verification/{UVM,VIP,vPlan,Coverage,Regression}/, 04_Debug/{Known_Issues,Failure_Patterns,Root_Cause}/, 05_Tools/{VCS,Verdi,ZeBu,HAPS,LSF}/, 06_Agent_Memory/{Working,Job,Project,Engineering,Organizational}/, 07_Signoff/{Requirements,Traceability,Coverage,Reports}/. If a vault already exists, it must NOT be destroyed or restructured destructively -- check only, do not touch.

### Phase 8 requirements
An ObsidianAdapter (or equivalent abstraction) providing at least: detect(), status(), search(), read(), create(), update(), delete(), list_tags(), list_links(), get_properties(), set_properties(). Anything Obsidian CLI can't do falls back to a FileSystemMarkdownAdapter. The Memory Agent must depend ONLY on a MemoryProvider interface -- never hard-code Obsidian commands scattered throughout the codebase. Architecture: MemoryAgent -> MemoryProvider -> {ObsidianAdapter, FileSystemMarkdownAdapter}.

Check real code (memory_vault.py and anywhere else relevant) against both. Report your verdict per the required format, for the vault structure and for the adapter abstraction separately -- if the real implementation is more mature/different-but-equivalent, say so explicitly rather than marking it a gap just for not matching the spec's exact class/folder names.`, {label: 'audit:vault-adapter', phase: 'Audit'})

const auditMemoryTiersPromotion = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 4 (5-Level Memory Architecture) + Phase 5 (Memory Promotion Engine)

### Phase 4 requirements
5 real tiers: Working (short-term reasoning: current hypothesis/evidence/files/test/simulator state, not permanently saved), Job (one sim/regression job: job_id/pattern/command/LSF job/start/end time/status/UVM_ERROR/UVM_FATAL/timeout/failure signature/evidence refs/fix attempt/result), Project (DUT/subsystem/project-specific experience), Engineering (cross-project reusable methodology), Organizational (team-standard knowledge after repeated verification).

### Phase 5 requirements
Promotion must NOT be unrestricted. Working -> Job -> Project -> Engineering -> Organizational, each promotion evaluated on reusability/confidence/evidence strength/repeatability/scope/verification status -- suggested promotion_score as a weighted function extending the Harness's existing confidence framework, e.g. confidence>=0.90 AND verified==true AND evidence_count>=threshold AND reusable==true before Engineering promotion. Organizational must be stricter still -- never promote on a single PASS alone.

Check dv_harness/memory.py, memory_router.py's real promote_to_organizational() and CLAUDE.md's documented gate (qualitative CLOSED/VERIFIED + HIGH confidence + confirmation_count>=2, per the Engineering Memory Policy section already in CLAUDE.md). Run a real check of current tier populations if possible (this may overlap with a separate concurrent audit elsewhere in this session -- that's fine, re-verify independently rather than citing it). Report your verdict per the required format for tiers and for the promotion engine separately.`, {label: 'audit:memory-tiers-promotion', phase: 'Audit'})

const auditInferenceDebugFlow = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 6 (Autonomous Inference Engine integration) + Phase 10 (Debug Flow)

### Phase 6 requirements
Memory Agent must integrate with the Autonomous Inference Engine's Hypothesis->Evidence->Confidence->Gap->Next-Best-Action loop. Before debug: current failure -> search memory -> retrieve related cases -> compare current evidence -> generate hypotheses. CRITICAL: historical memory is evidence/prior ONLY -- must never assume previous root cause == current root cause; current RTL/VIP/log/waveform evidence must always be re-validated.

### Phase 10 requirements
Before Debug: (1) capture failure signature, (2) search related memory, (3) rank related cases, (4) present relevant prior evidence, (5) generate hypotheses, (6) validate against current environment. During Debug: maintain Hypothesis/Evidence/Confidence/Gap/Next-Best-Action. After Debug: if FAIL, update Job Memory only, do not promote; if PASS, record symptom/root cause/evidence/fix/verification/confidence/git SHA/test/result, then run promotion evaluation.

Check dv_harness/inference.py's real functions, memory_vault.py's build_failure_signature()/search_related_memory_for_debug() (per CLAUDE.md's own documented Workstream-3 addendum), and whether engine.py's real FAILURE_RECOVERY/RE_AUDIT stages actually call this integration for real (not just that both pieces exist separately). Report your verdict per the required format for the inference-integration and the debug-flow-mechanics separately.`, {label: 'audit:inference-debug-flow', phase: 'Audit'})

const auditSchema = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 7 (Memory Note Schema)

All formal Engineering Memory notes must use YAML frontmatter with required fields (id, memory_level, protocol, subsystem, category, failure, status, confidence, project, rtl_sha, tb_sha, vip_vendor, vip_version, simulator, created, updated, tags) and a standard body-section shape (Symptom/Context/Hypothesis/Evidence/Root Cause/Fix/Verification/Confidence/Reusability/Known Limitations/Related Knowledge with [[wiki-links]]). Schema validation is required -- a note missing required fields must be marked PARTIAL, never silently written as if valid.

Check: is there a real, current schema definition and a real validator function/class that actually enforces this (grep memory.py/memory_vault.py for schema validation logic)? Find or create a real synthetic test note and try validating it against whatever real validator exists (or confirm none exists). Report your verdict per the required format.`, {label: 'audit:schema', phase: 'Audit'})

const auditSearchDedup = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 9 (Search Strategy) + Phase 18 (Knowledge Deduplication)

### Phase 9 requirements
Retrieval must support at least: exact search, keyword search, tag search, YAML property search, wiki-link traversal, protocol filtering, project filtering, memory-level filtering, confidence filtering, status filtering. No embedding/vector DB required yet (rg/grep/filesystem index/Obsidian CLI search/metadata index is fine for now) but the design should not preclude adding semantic search/embedding/vector DB/RAG later.

### Phase 18 requirements
Prevent near-duplicate notes (e.g. USB3_LFPS_issue1.md/issue2.md/issue3.md all really the same root cause) via a similarity/fingerprint strategy using at least protocol + failure signature + root cause + configuration + error pattern, classifying a new note candidate as NEW / RELATED / DUPLICATE / UPDATE_EXISTING.

Check dv_harness/memory_dedup.py (already built earlier this session per the inventory) and memory.py's real search functions against each of the required filter/search types above -- which are real, which are missing. Report your verdict per the required format for search and for deduplication separately.`, {label: 'audit:search-dedup', phase: 'Audit'})

const auditRegressionArtifactSecurity = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 11 (Regression Integration) + Phase 12 (Large Artifact Policy) + Phase 19 (Security)

### Phase 11 requirements
For every LSF job, track Job/Pattern/LSF ID/Status/UVM_ERROR/UVM_FATAL/Failure Signature/Related Memory/Confidence/Action. On UVM_ERROR/UVM_FATAL/timeout/abnormal termination, the Memory Agent extracts a failure signature, searches previous knowledge, and provides related root causes -- but the Debug Agent must always re-verify, never blindly copy a previous fix.

### Phase 12 requirements
FSDB/VPD/coverage database/VCS build database/full sim.log/full regression logs/binary artifacts must NEVER go directly into the Vault -- only references (evidence: {sim_log: path, fsdb: path, coverage: path, lsf_job: id}) plus condensed evidence.

### Phase 19 requirements
Absolutely forbidden in Memory: password/token/API key/VC password/SSH private key/license credentials/personal credentials. If a secret pattern is detected in a log being processed, it must be redacted before being written to Memory.

Check dv_harness/lsf_client.py's real '_write_job_tier_memory_on_terminal_reconcile()' (per CLAUDE.md's documented mechanics) against Phase 11, check memory.py/memory_vault.py's real handling of large-artifact references vs. embedding against Phase 12, and check memory_router.route_memory()'s real hard-REJECT-by-kind logic (per CLAUDE.md's Engineering Memory Policy: 'kind' credential/password/token/secret is REJECTed as enforced code, not policy prose) plus whether any REAL secret-pattern REDACTION (not just rejection-by-kind) exists for content embedded inside an otherwise-legitimate memory record. Report your verdict per the required format for all three sub-scopes separately.`, {label: 'audit:regression-artifact-security', phase: 'Audit'})

const auditGitSession = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 13 (Git Integration) + Phase 14 (Session Save/Restore)

### Phase 13 requirements
DV-Knowledge must support Git, with a commit policy -- NOT every Working Memory update commits. Commit only on: verified Job result, Project Memory update, Engineering Memory promotion, Organizational Memory approval. Commit message format: memory(<protocol>): <short description>. Must preserve RTL SHA, TB SHA, and the Knowledge commit SHA itself for traceability.

### Phase 14 requirements
Memory system must integrate with the Harness's Session Save/Restore. Save: current job, current project, current hypothesis, current evidence, current confidence, related memory, pending action. After Restore, the Claude Agent must know: where it stopped, what was proven, what remains unknown, what action to execute next -- avoiding re-analysis from zero.

Check memory_vault.py's real git-commit logic (per CLAUDE.md's documented Workstream-3 mechanics: fires only on verified Job result/Project update/Engineering promotion/Organizational approval, 'memory(<protocol>): <description>' format, 'knowledge_commit_sha' written back onto the underlying record alongside 'rtl_sha'/'tb_sha') against Phase 13. Separately, check dv_harness/session_snapshot.py's REAL current integration with the memory system specifically -- does a session snapshot actually capture/restore hypothesis/evidence/confidence/related-memory/pending-action as Phase 14 requires (this may overlap with a separate concurrent audit of Session Save/Restore as a general AI mechanism elsewhere in this session -- re-verify independently for the MEMORY-specific integration angle, which is this phase's actual focus). Report your verdict per the required format for Git integration and for Session Save/Restore separately.`, {label: 'audit:git-session', phase: 'Audit'})

const auditSkillsAgent = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 16 (Claude Skills) + Phase 17 (Memory Agent)

### Phase 16 requirements
Check .claude/skills for existing memory-related skills. If genuinely absent, real skills are needed: memory-search/, memory-write/, memory-promote/, memory-link/, memory-review/, obsidian-cli/ -- each with SKILL.md covering Purpose/Inputs/Outputs/Preconditions/Execution Steps/Fallback/Evidence Requirements/Failure Conditions/Examples. Do not create duplicate/conflicting skills -- if an existing skill already covers the function, extend it instead.

### Phase 17 requirements
If a Memory Agent already exists, extend it; only create one if genuinely absent. Responsibilities: search, retrieve, summarize, write, link, deduplicate, promote, demote, archive, validate. Explicitly NOT responsible for: directly modifying RTL, directly modifying UVM, directly running simulation (those belong to other agents).

Check the real current .claude/skills/ tree for anything memory-related (memory-retrieval, memory-confidence-gate, memory-consolidation were named elsewhere in this project's CLAUDE.md -- confirm their real current scope against the 6 skill names above; they likely already cover most of this under different names -- do not treat a differently-named-but-equivalent skill as a gap). Report your verdict per the required format for skills coverage and for the Memory Agent's real responsibility boundary separately.`, {label: 'audit:skills-agent', phase: 'Audit'})

const auditCliHealthTests = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 20 (CLI Commands) + Phase 21 (Health Check) + Phase 22 (Tests)

### Phase 20 requirements
Harness-level CLI commands or equivalent interface for at least: memory status, memory search "<query>", memory show <id>, memory add, memory promote <id>, memory graph <id>, memory validate, memory sync, memory doctor. If an existing CLI framework exists (dv_harness/cli.py), integrate into it -- do not build a separate one.

### Phase 21 requirements
A "memory doctor" health check covering at least: Vault exists, Vault writable, Git status, Obsidian CLI detected, Filesystem fallback, Schema valid, Broken Wiki Links, Duplicate IDs, Invalid YAML, Missing required metadata, Large files, Secret leakage -- output READY/PARTIAL/BLOCKED.

### Phase 22 requirements
Minimal but complete real tests covering at least: (1) no Obsidian CLI -> filesystem fallback PASS, (2) Obsidian CLI exists -> adapter PASS, (3) create note, (4) search note, (5) update note, (6) YAML parse, (7) wiki link, (8) memory promotion, (9) duplicate detection, (10) invalid note rejection, (11) secret redaction, (12) Git metadata, (13) session save, (14) session restore.

Check dv_harness/cli.py's real memory-related subcommands against the Phase 20 list, dv_harness/memory_doctor.py's real current checks against the Phase 21 list, and the real current test suite (grep for memory-related test files) against all 14 Phase 22 test cases -- which exist and pass right now, which are missing. Report your verdict per the required format for CLI commands, health check, and tests separately (tests: give a literal 14-item present/missing table).`, {label: 'audit:cli-health-tests', phase: 'Audit'})

const auditE2eDocsClaudemd = agent(`${AUDIT_HEADER(inventory)}

## Your scope: Phase 23 (End-to-End DV Test) + Phase 24 (Documentation) + Phase 15 (CLAUDE.md)

### Phase 23 requirements
A synthetic USB3 Polling.LFPS timeout example exercising the full flow: failure -> search memory -> hypothesis -> evidence -> confidence -> root cause -> verified fix -> Job Memory -> promotion evaluation -> Engineering Memory -> wiki links -> Git traceability. Do NOT launch real dangerous/credential-requiring remote execution -- if real Linux-server execution would be needed and environment/credentials aren't safely available, mark PARTIAL and use a local/synthetic test to verify the memory flow instead.

### Phase 24 requirements
docs/MEMORY_ARCHITECTURE.md, docs/OBSIDIAN_INTEGRATION.md, docs/MEMORY_AGENT.md, docs/MEMORY_SCHEMA.md, docs/MEMORY_OPERATIONS.md -- written so a general DV/DE engineer can use them directly.

### Phase 15 requirements
CLAUDE.md must have an Engineering Memory Policy covering: before-debugging (search memory, treat as prior evidence only, validate against current RTL/VIP/log/waveform), during-debugging (Hypothesis->Evidence->Confidence->Gap->Next-Best-Action), after-verified-PASS (record root cause/evidence/fix/verification/confidence, evaluate promotion), and Never (secrets/passwords/giant logs/FSDB/promote unverified hypotheses).

Check: does a real synthetic end-to-end test/demo of this exact USB3 LFPS flow exist anywhere in this project (run it if it does)? Which of the 5 docs files in Phase 24 already exist and are accurate vs. missing/stale? Confirm CLAUDE.md's ALREADY-PRESENT "Engineering Memory Policy (2026-09-03)" section (read it directly) actually covers all 4 required sub-sections of Phase 15 -- this is very likely already done, confirm rather than assume, and note precisely if anything is missing. Report your verdict per the required format for all three sub-scopes separately.`, {label: 'audit:e2e-docs-claudemd', phase: 'Audit'})

const auditResults = await parallel([
  () => auditVaultAdapter, () => auditMemoryTiersPromotion, () => auditInferenceDebugFlow,
  () => auditSchema, () => auditSearchDedup, () => auditRegressionArtifactSecurity,
  () => auditGitSession, () => auditSkillsAgent, () => auditCliHealthTests, () => auditE2eDocsClaudemd,
])
const [vaultAdapterR, memoryTiersPromotionR, inferenceDebugFlowR, schemaR, searchDedupR,
  regressionArtifactSecurityR, gitSessionR, skillsAgentR, cliHealthTestsR, e2eDocsClaudemdR] = auditResults

phase('Close')

const auditSummaries = [
  ['Phase 3+8: Vault structure + Obsidian/FileSystem Adapter abstraction', vaultAdapterR],
  ['Phase 4+5: 5-Level Memory tiers + Promotion Engine', memoryTiersPromotionR],
  ['Phase 6+10: Inference Engine integration + Debug Flow mechanics', inferenceDebugFlowR],
  ['Phase 7: Memory Note Schema (YAML frontmatter + validation)', schemaR],
  ['Phase 9+18: Search Strategy + Knowledge Deduplication', searchDedupR],
  ['Phase 11+12+19: Regression Integration + Large Artifact Policy + Security/redaction', regressionArtifactSecurityR],
  ['Phase 13+14: Git Integration policy + Session Save/Restore (memory-specific)', gitSessionR],
  ['Phase 16+17: Claude Skills + Memory Agent responsibilities', skillsAgentR],
  ['Phase 20+21+22: CLI Commands + memory doctor Health Check + Tests', cliHealthTestsR],
  ['Phase 23+24+15: End-to-end synthetic test + Documentation + CLAUDE.md policy', e2eDocsClaudemdR],
]

log('Audit phase complete. Closing confirmed real BLOCKED gaps (and completing genuine PARTIAL items where boundable) one at a time, sequentially, to avoid concurrent-edit collisions with the other workflows/agents active in this session.')

const closeResults = []
for (const [name, report] of auditSummaries) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CORE_PRINCIPLES}

This is a sequential gap-closing pass over a fresh audit of DV Agent Harness L5's Claude CLI + Obsidian CLI + Git/Markdown Hybrid Engineering Memory implementation against the user's 25-phase spec. You are handling exactly ONE scope: **${name}**.

NOTE: other agents/workflows are concurrently active in this repo (a 14-AI-mechanism audit+close workflow, a governance-architecture reverify workflow, a live remote USB build). Check git status/git diff on any file before touching it; use the hand-scoped patch technique (git diff > patch, trim to your hunk, git apply --cached --check then --cached) for any shared file (especially CLAUDE.md, dv_harness/cli.py, dv_harness/memory.py, dv_harness/memory_router.py) rather than a broad git add.

Its real, current audit finding (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. For every sub-item marked READY: do nothing. Re-confirm the cited evidence yourself.
2. For every sub-item marked BLOCKED (a real, closeable gap): build it for real, following this scope's phase requirements above. Prefer extending/reusing existing code (memory.py, memory_router.py, memory_vault.py, memory_dedup.py, memory_doctor.py, cli.py, and any already-covering skill under .claude/skills/) over creating a parallel mechanism. If the existing implementation already covers the intent via a different but equivalent design, do not force it to literally match the spec's class/file/folder names -- just confirm and report READY instead of rebuilding.
3. For every sub-item marked PARTIAL: assess whether it's a genuinely deliberate, disclosed boundary (Obsidian CLI absent -> filesystem fallback; needs real remote credentials -> synthetic test used instead) -- leave those as-is, they are correct. If it's PARTIAL only because something small and boundable is missing (e.g. one required YAML field not validated, one CLI subcommand not wired, one doc file not yet written), complete it for real in this pass.
4. Write real tests proving whatever you build/complete actually works (not just that it parses/imports).
5. Run the full relevant test suite for whatever you touched and confirm pass.
6. Commit your change for real (if you made one) with a clear, scoped commit message following the memory(<protocol>): <description> convention where applicable, or a normal scoped message otherwise.
7. Remove any stale/outdated comment or dead code in anything you touch, per this project's own Engineering Discipline Rules.

Write a report to .work/gap-close-obsidian-memory-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 50)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `close:${name}`, phase: 'Close', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Report')

const finalReport = await agent(`${CORE_PRINCIPLES}

Independently review this entire "inventory + re-verify Claude CLI + Obsidian CLI + Git/Markdown Hybrid Engineering Memory against the 25-phase spec + close every confirmed real gap" effort for DV Agent Harness L5, then produce the EXACT final report format the user's own Phase 25 requires below. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read the full Phase 1+2 inventory, every audit report, and every close-pass report in full first (search .work/ for files matching gap-close-obsidian-memory-*-report.md).

Raw returned results, for cross-reference:

### Inventory (Phase 1+2)
${inventory}

### Audits
${auditSummaries.map(([name, report]) => `#### ${name}\n${report}`).join('\n\n')}

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass that reported DONE: did the fix actually work, verified by you running something real (a real test, a real CLI command, a real note create/search/promote round-trip)?
2. Run dv_harness_tests/ relevant to memory (and the full suite if feasible: python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
3. Actually exercise the Phase 23 end-to-end synthetic USB3 LFPS flow yourself if it exists, and confirm each step genuinely fires.
4. Check git hygiene across all commits this pass made.

Then produce the user's EXACT required Phase 25 report format below, filled in with real, verified values (use READY/PARTIAL/BLOCKED honestly per line, not an inflated "all READY" if evidence doesn't support it):

====================================================
DV AI HARNESS -- ENGINEERING MEMORY INTEGRATION
====================================================

Architecture:
Claude CLI:
Obsidian CLI:
Filesystem Fallback:
Vault:
Git:
Memory Agent:

5-Level Memory:
Working:
Job:
Project:
Engineering:
Organizational:

Obsidian:
Detected:
Version:
Mode:

Capabilities:
Search:
Read:
Write:
Properties:
Tags:
Links:
Git:
Session Restore:

Tests:
Passed:
Failed:

Readiness:
Memory:
Obsidian:
Fallback:
Git:
Integration:
Overall:

Status:
READY / PARTIAL / BLOCKED

Files Created:
Files Modified:

Remaining Gaps:

Recommended Next Action:
====================================================

Fill in "Files Created"/"Files Modified" with the REAL aggregate list across every close-pass commit (grep git log for this session's relevant commits), and "Remaining Gaps" with every genuinely still-open item across all 10 audit scopes (including correctly-deferred PARTIAL boundary items, labeled as such).`, {label: 'final-report', phase: 'Report', model: 'claude-opus-5'})

return { inventory, auditSummaries: Object.fromEntries(auditSummaries), closeResults: Object.fromEntries(closeResults), finalReport }
