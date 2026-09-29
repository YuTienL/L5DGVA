export const meta = {
  name: 'self-describing-env-mcp',
  description: 'env.manifest.json + read-only MCP server + 3-tier question-queue + bind-connectivity/checker-scoreboard system',
  phases: [
    { title: 'Build', detail: '4 parallel workstreams: env_manifest, mcp_server, question_queue, bind_connectivity' },
    { title: 'Finish', detail: 'consolidated report, independently re-verified' },
    { title: 'Review', detail: 'independent adversarial re-verification against real evidence' },
  ],
}

const USER_SPEC = `
User's original spec (this session, Traditional Chinese where quoted, English commentary preserved) -- the authoritative requirements. Nothing in your task may contradict this; where your task's brief below narrows scope, this is the fuller context for WHY.

## Part A -- env.manifest.json + MCP + 3-tier question queue

env.manifest.json is a generated, diffable, git-tracked fact file with three layers:
- VIP layer: captured via a zero-time UVM callback at end_of_elaboration_phase that dumps the VIP's own already-resolved config object to JSON -- "more reliable than reading the user guide because it reflects actually-applied values", not documentation.
- DUT layer: ports/params from verible --export_json (already real in this repo as dv_harness/verible_parser.py -- extend it, do not re-implement it); registers from a RAL/IP-XACT-style structured source, never a raw Excel/PDF scrape.
- Env layer: component hierarchy + config_db set/get pairing from uvm_top.print_topology() + +UVM_CONFIG_DB_TRACE -- "an agent asking whether a component is active or passive shouldn't guess."

This extends the harness's EXISTING JSON IR pipeline (verible_parser.py, evidence_db.py from the just-completed governance workflow) rather than inventing a parallel framework.

An internal, READ-ONLY MCP server exposes a FIXED set of verbs instead of free grep/file access: get_vip_config, get_dut_port, get_register, get_topology, query_regression. This is for auditability (every query is one of five known shapes), fixed schema (no free-text parsing of arbitrary greps), and enforced read-only permission (an agent literally cannot write through this interface). query_regression should read from evidence_db.EvidenceStore (dv_harness/evidence_db.py, already real -- has .query(sql, params) and insert_regression_verdict/insert_coverage_sample), not a new parallel store.

CLAUDE.md itself should hold only an index + rules, with details loaded on demand from skills/reference docs -- for a multi-protocol environment, one CLAUDE.md per protocol is suggested rather than one giant file.

## Part B -- 3-tier ask-a-human protocol

Three tiers for any question the harness encounters:
1. Self-resolve -- just query env.manifest.json/MCP; no human involved.
2. Safe-to-assume -- log the assumption and continue; judged by "worst case = one wasted regression" (i.e. low blast radius, cheaply detected and cheaply re-run).
3. Cannot-assume -- stop and escalate. Hard-coded trigger, not a judgment call: ANYTHING affecting pass/fail verdict, spec intent, or whether a read-only file should change.

Standardized one-question-per-entry JSON schema (Q-ID format), required fields: id, blocking, domain, owner, question, context_path, options[] (2-3 pre-researched options, never open-ended), recommendation, assumption_if_unanswered. Owner-routed: VIP-domain questions -> DV-owner/Synopsys-AE, DUT-domain -> designer, env-domain -> DV-owner. Batched into a daily/end-of-run digest, never real-time pings.

Answers MUST persist back to env.manifest.json / a decisions.md file, with date + basis, specifically to prevent re-asking the same question. Named failure mode if this isn't built: "L5退化成一個很吵的L3" (L5 degrades into a noisy L3 -- constant interruption with no memory).

4 tracking metrics: self-resolve rate (target >90%), blocking-questions/week (the direct human-cost proxy), repeat-question-rate (any nonzero value means persistence is broken), assumption-overturned-rate (too high means Tier-2's safe-to-assume criteria are too loose).

## Part C -- bind-location / VIP-connectivity / checker-scoreboard deep-dive (the user explicitly emphasized this: "尤其是bind location，和VIP種類和數量所對應的DUT instance hierarchy path及checker，scoreboard作法分析後的規劃建議和確認")

A connectivity manifest built from FOUR real inputs, never guessed:
1. DUT instance tree (e.g. simv -ucli -do "scope -tree", or a static AST tool like slang --ast-json)
2. Interface signal sets from module port lists, for protocol-fingerprint matching
3. Existing binds via a repo-wide grep -n "^\\s*bind " -- what's already decided must be read, not re-derived
4. VIP instances via uvm_top.print_topology() + config_db trace -- "a set with no get is direct evidence of a miswired vif, without waiting for simulation"

A 4-tier confidence system for EVERY bind-path match:
- T1 = already-decided (existing bind statement or config_db entry found) -- accept as-is, no re-litigation.
- T2 = structural protocol-fingerprint match (e.g. AXI needs AWVALID/AWREADY/WLAST/BRESP present; CSI-2 needs D-PHY + clock lanes present) -- high-confidence, auto-acceptable, but still LISTED in the report for visibility.
- T3 = naming-heuristic-only (e.g. matched via a name like u_usb3_top or i_pcie_x2 with no structural corroboration) -- ALWAYS requires human confirmation, NEVER auto-accepted. Flagged as the most error-prone tier, especially for multi-instance IP, generate-block paths, and inconsistent wrapper depth across a hierarchy.
- T4 = undecidable from any of the 4 inputs -- goes to the question queue (Part B), never guessed.

Count-matching self-check equations that must actually be computed, not eyeballed:
- VIP instance count must equal ACTIVE INTERFACE count, not raw IP instance count (a passive-monitor-only IP has 0 active interfaces).
- A passive monitor on a shared fabric is NOT the same count dimension as master-agent count -- the real scoreboard dimension is path-combination count (every master x every reachable slave).
- Whether a VIP must be configured as a bus slave/responder is determined from the DUT's PORT DIRECTION at that boundary, never from instance naming (DUT-as-initiator implies VIP-must-be-slave/responder).

Required output artifact: a matrix with columns DUT instance | interface | direction | role | VIP type | count | active/passive | bind target | tier -- one row per interface, and a hard self-check identity: sum(verified interfaces) = sum(VIP instances) + sum(explicitly-listed exemptions). Any mismatch requires a per-line explanation; no unexplained gap is acceptable.

4 FIXED CLAUDE.md bind-location rules (these are hard project rules, not suggestions):
1. Binding to a bare module name applies to ALL instances of that module -- appropriate at IP level, usually WRONG at SoC level, which must always bind by full instance path.
2. All bind statements live centralized in separate *_bind.sv files under tb/ -- RTL files are read-only, and an agent must never insert a bind statement directly into RTL.
3. Clock/reset must be passed explicitly through the bind's own port list, never grabbed via a cross-level hierarchical reference -- a hierarchical grab breaks at gate-level netlists or after a wrapper swap.
4. Any bind-target path containing a generate/for-loop construct must be expanded to explicit literal indices in the bind statement -- no wildcard/loop-based bind targets are accepted.

THREE MACHINE GATES a connectivity plan must pass BEFORE it is ever shown to a human for confirmation:
- Gate 1 (elaboration check): vcs -elab_only or an equivalent static elaboration tool (or slang) -- cheapest, catches a bind path that flatly does not exist.
- Gate 2 (static zero-time connectivity): at every claimed bind point, confirm the clock genuinely toggles, reset genuinely deasserts, and required signals are non-X at time zero -- a silent/dead interface is flagged red here, before any real transaction runs.
- Gate 3 (transaction activity): a minimal directed test confirming every VIP monitor actually receives >= 1 real transaction. Explicitly called out as "the only method that catches a path that's syntactically legal but wired to the wrong instance" -- recommend this become a standing 'just connectivity-check' recipe re-run on every RTL update, not a one-time check.

A checker/scoreboard PLANNING TABLE (not implementation -- a plan a human reviews and confirms) classifying every check needed as one of:
- Protocol-check: must reuse the VIP's own built-in checks. The agent's job here is ONLY to list which built-in checks are DISABLED and why -- that disabled-list is itself the actual review focus, not the enabled ones.
- Data-integrity (scoreboard): requires, per scoreboard: explicit endpoint pairs, a matching key, ORDERING semantics (in-order / out-of-order / an explicit allowed reorder window depth), transformation rules (width conversion, packetization, byte-enable handling), legal DROP/backpressure conditions, reset-flush behavior, and an orphan/unmatched-transaction threshold + timeout. ORDERING and LEGAL-DROP are explicitly flagged as the two fields where real scoreboard false-passes actually happen in practice -- these two fields specifically must never be left at an agent-chosen default; they require explicit human review every time.
- System-level: cross-interface-path scoreboards, performance checks, DECERR/error-response checks.

Confirmation granularity is PER-ROW (per-interface, per-scoreboard), never whole-document approval -- called out explicitly as meaningless at a 20-interface scale. A confirmed row is LOCKED: an agent cannot change it without a diff + explicit re-confirm cycle. After an RTL update, only the ROWS THAT ACTUALLY DIFFED need re-confirmation -- this is what keeps confirmation cost from scaling linearly with project size over time.

Final presentation is exactly 3 artifacts: (1) the connectivity matrix (table), (2) a hierarchy diagram showing bind points + VIP mount locations, (3) the question queue -- explicitly named as "the only piece requiring real human thought," everything else should already be machine-gated by the time a human looks at it.

## Explicit concurrency note for this workflow

This session currently has TWO other multi-agent efforts running concurrently in this same repo:
1. "evidence_db live wiring" -- touching dv_harness/regression_reporter.py, dv_harness/evidence_db.py, dv_harness/vip_distill.py, and dv_harness/config.py's evidence_db block. Read from evidence_db.EvidenceStore.query() freely (it is a stable, already-real API), but do NOT edit those 3 files.
2. "exemptions + harness reliability + self-test CI" -- touching dv_harness/exemptions.py (new), dv_harness/engine.py (dry-run/degradation wiring), dv_harness/session_snapshot.py (auto-checkpoint), .github/workflows/, dv_harness/config.py (its own new blocks), dv_harness/cli.py. Do NOT edit those files either.

To avoid the exact concurrent-edit collision this session already hit twice today (accidentally sweeping a sibling workstream's uncommitted hunks into your own commit via whole-file 'git add'):
1. Before your first edit to any shared file (config.py, cli.py, CLAUDE.md), run 'git status --short' and 'git diff <file>' to see what is already there uncommitted from a sibling effort. Never assume the file is clean.
2. Before committing, run 'git diff --cached <file>' and confirm it shows ONLY your own intended change. If it shows more, unstage ('git reset <file>'), then use a hand-built patch ('git apply --cached') scoped to just your own hunk -- search this repo's git log for "Fix real preflight-gate regression" or the run_profile.json commit message for a worked example of this exact technique if you have not done it before.

## Explicit overlap note for this workflow

The "Production-Grade Execution Governance" workflow just completed and landed REAL infrastructure this system must build on, not duplicate:
- dv_harness/verible_parser.py: parse_file(path) -> FileParseResult, to_dict(result) -- real verible --export_json wrapper, already extracts modules/ports/params/signals. The DUT layer of env.manifest.json extends this; it does not re-parse RTL from scratch.
- dv_harness/evidence_db.py: EvidenceStore class (insert_job_state, insert_job_memory_record, insert_regression_verdict, insert_coverage_sample, insert_rtl_parse, query(sql, params)), DuckDB-backed, schema real but the store itself has never been fed a real record yet (confirmed empty as of this workflow's start). query_regression's MCP verb should read through EvidenceStore.query(), and rtl-fact lookups (get_dut_port) should be able to read from insert_rtl_parse()'s own table shape rather than re-deriving one.
- dv_harness/vip_distill.py: distill_sim_log/distill_job_record/distill_fsdbreport/merge_evidence -- pure evidence normalization, explicitly scoped (AST-enforced) to never import orchestration/memory modules. If this system's VIP-config-dump layer needs its own normalization step, follow the same scoping discipline rather than importing vip_distill.py directly into an orchestration path.
`

phase('Build')

const envManifest = agent(`${USER_SPEC}

## Your task: env.manifest.json (Part A's manifest half only -- NOT the MCP server, NOT the question queue, NOT bind-connectivity; those are separate parallel workstreams you must not duplicate)

Build dv_harness/env_manifest.py: a generator producing env.manifest.json with exactly three top-level sections -- vip_config, dut_facts, env_topology -- as described in Part A above.

Concrete requirements:
1. dut_facts: extend dv_harness/verible_parser.py's real parse_file()/to_dict() output (module/port/param/signal facts) into the manifest shape. Do not re-implement RTL parsing. Add a register-facts sub-section sourced from a structured input (design a small, honest JSON/YAML register-map schema modeled on RAL/IP-XACT register fields -- name/address/width/fields/access -- since no live RAL model exists in this repo to read from; document this as the input contract, never invent register content for a specific project).
2. vip_config: this genuinely requires a live UVM simv to capture for real (the end_of_elaboration_phase JSON dump). Since no live simv exists in THIS repo (dv_harness is the meta-harness, not a generated project environment), build: (a) the real, generic UVM callback/base-class code that a GENERATED environment would include to perform this dump (goes into dv_harness/uvm_generator/templates/, following the existing template convention -- check dv_harness/uvm_generator/templates/ for the established structure first), (b) a parser in env_manifest.py that reads that dump's JSON once produced, (c) an honest NOT_AVAILABLE status when no real dump exists yet -- never a fabricated example VIP config. This mirrors the same "never guess a command contract, wire against a real installed instance only" discipline already established in this repo's memory_vault.py (see docs/MEMORY_ARCHITECTURE.md for the pattern you're matching).
3. env_topology: same treatment -- this needs uvm_top.print_topology()/+UVM_CONFIG_DB_TRACE output from a real run. Build the generic capture mechanism + parser, honest NOT_AVAILABLE when no real capture exists.
4. The manifest must be: generated (never hand-edited), diffable (deterministic key ordering, stable formatting), and designed to be git-tracked (no timestamps/nondeterministic fields baked into content that would produce noise diffs on regeneration with no real change).
5. Write a JSON Schema for env.manifest.json (schemas/env_manifest.schema.json, following the exact pattern dv_harness/uvm_generator/schemas/run_profile.schema.json already established this session -- read that file first as your template for style/rigor).
6. New CLI subcommand: dv-harness env-manifest generate (mirrors the dv-harness run-profile pattern already in dv_harness/cli.py -- read that section first).
7. Real tests: schema validation, extraction against a real small synthesized RTL fixture (never real project RTL) proving the dut_facts layer genuinely round-trips through verible_parser.py, and explicit tests asserting NOT_AVAILABLE is reported honestly (not silently omitted) for vip_config/env_topology when no real dump exists.

Write a report to .work/mcp-env-manifest-report.md covering what's real, what's NOT_AVAILABLE-by-honest-design, and any open question. Run the full new test file(s) yourself and confirm pass before reporting DONE. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:env_manifest', phase: 'Build'})

const mcpServer = agent(`${USER_SPEC}

## Your task: the internal read-only MCP server (Part A's MCP half only -- env.manifest.json itself is being built by a parallel workstream; you consume its OUTPUT SHAPE, described below, you do not build the manifest generator)

Build a read-only MCP server exposing exactly 5 fixed verbs: get_vip_config, get_dut_port, get_register, get_topology, query_regression. No free-text query verb, no write verb, no arbitrary file-read verb -- the whole point (per Part A) is a fixed, auditable schema instead of free grep/file access.

Concrete requirements:
1. Server implementation under dv_harness/mcp/ (new subpackage) -- check how this repo already structures similar boundaries (dv_harness/uvm_generator/ as a precedent for subpackage layout) before choosing your own structure.
2. Each verb's backing data source:
   - get_vip_config / get_dut_port / get_register / get_topology: read from env.manifest.json. Since the manifest-generator workstream is running in parallel, DO NOT wait on its finished file -- build against the env.manifest.json SCHEMA described in Part A (vip_config/dut_facts/env_topology sections) and the schemas/env_manifest.schema.json contract; write your own minimal synthetic fixture matching that schema for your own tests, and note in your report that final integration against the real generator's exact field names needs a short reconciliation pass once both land (this is expected and fine -- flag it, don't block on it).
   - query_regression: read through dv_harness/evidence_db.py's real EvidenceStore.query(sql, params) (already real and tested from the just-completed governance workflow -- read that file first). Design a small, fixed set of parameterized query shapes this verb accepts (e.g. by pattern name, by date range, by verdict) rather than accepting arbitrary raw SQL from a caller -- passing caller-supplied SQL through to query() would defeat the entire "fixed verb, not free access" design principle this system exists to enforce.
3. Enforce read-only at the code level, not just by convention: the server process must have no code path that can mutate env.manifest.json, the evidence DB, or any RTL/testbench file. Write a test that actively tries to find a write path and asserts none exists (mirror the AST-based scope-enforcement test style dv_harness/vip_distill.py's report describes using this session, for the same "prove the boundary, don't just document it" reason).
4. Follow whatever MCP server conventions/SDK this environment already has available (check for an existing MCP-related dependency/pattern in this repo/session context first -- do not invent a protocol from scratch if a standard library exists; if genuinely none is available, build the 5 verbs as a well-documented, schema-validated JSON-in/JSON-out function set first, with a thin MCP transport wrapper added only if a real MCP SDK is confirmed available, and clearly disclose which case applies).
5. Real tests for all 5 verbs against your synthetic fixtures, plus the read-only-boundary test from point 3.

Write a report to .work/mcp-server-report.md. Explicitly flag the reconciliation-pending note from point 2. Run your new tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:mcp_server', phase: 'Build'})

const questionQueue = agent(`${USER_SPEC}

## Your task: the 3-tier ask-a-human protocol + question-queue mechanics (Part B only)

Build the question-queue system described in Part B: the 3-tier self-resolve/safe-assume/escalate decision logic, the Q-ID JSON schema, decisions.md persistence, owner routing, digest batching, and the 4 tracking metrics.

Concrete requirements:
1. dv_harness/question_queue.py (new module):
   - A Q-ID JSON schema (schemas/question.schema.json, matching the rigor of dv_harness/uvm_generator/schemas/run_profile.schema.json as your style template) with the exact required fields from Part B: id, blocking, domain, owner, question, context_path, options[] (min 2 items), recommendation, assumption_if_unanswered.
   - A tier-classification function: given a decision context, return which of the 3 tiers applies. The Tier-3 (cannot-assume) trigger is HARD-CODED per Part B -- anything affecting pass/fail verdict, spec intent, or a read-only-file-should-change decision -- implement this as an explicit, testable predicate, not a vague heuristic.
   - Owner routing: VIP-domain -> DV-owner/Synopsys-AE, DUT-domain -> designer, env-domain -> DV-owner (as literal, testable routing rules).
   - Digest batching: questions accumulate and are emitted as a daily/end-of-run digest, never as individual real-time pings -- design the batching window/trigger explicitly (e.g. via existing session/regression-cycle boundaries this harness already tracks -- check dv_harness/engine.py's stage lifecycle for a natural batching hook point before inventing a new timer mechanism).
2. decisions.md persistence: once a question is answered (by a human, via whatever the harness's existing human-input mechanism is -- check dv_harness/cli.py's existing 'correct'/'constraint'/'approve' subcommands for the established pattern before inventing a new one), the answer + date + basis must be written back to both env.manifest.json's own record (or a dedicated decisions store, your call, document why) AND a human-readable decisions.md, specifically to make a REPEAT of the same question impossible. Write and run a real test that asks the same question twice and asserts the second time is a Tier-1 self-resolve (found in decisions.md) rather than a fresh Tier-3 escalation.
3. The 4 tracking metrics as computable functions over stored question/decision records: self-resolve rate, blocking-questions/week, repeat-question-rate (must be provably 0 given point 2's guarantee, and your test should assert this), assumption-overturned-rate. Wire a CLI subcommand (dv-harness question-queue status, following the existing dv-harness subcommand pattern in cli.py) to print these 4 numbers.
4. New CLI subcommands: dv-harness question-queue {add, list, answer, digest, status} -- read cli.py's existing subcommand-group pattern (e.g. the 'knowledge' or 'memory' subcommand groups) before adding yours, match the convention.
5. Real tests for the tier-classification predicate (both directions -- a genuine Tier-3 trigger and a genuine Tier-1/2 case), the repeat-question-rate=0 guarantee, owner routing, and digest batching.

Write a report to .work/mcp-question-queue-report.md. Run your new tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:question_queue', phase: 'Build'})

const bindConnectivity = agent(`${USER_SPEC}

## Your task: bind-location / VIP-connectivity / checker-scoreboard system (Part C only -- this is the part the user explicitly emphasized as most important)

Build the connectivity-manifest system, the 4-tier confidence classification, the count-check equations, the 3 machine gates, and the checker/scoreboard planning-table generator described in Part C above, plus land the 4 fixed CLAUDE.md bind-location rules.

Concrete requirements:
1. dv_harness/connectivity.py (new module) building a connectivity manifest from the 4 real inputs Part C names:
   - DUT instance tree: build a parser for slang --ast-json output if slang is available in this environment (check first), or design the input contract clearly and honestly mark NOT_AVAILABLE with a documented fallback path if not (do not fabricate a tree).
   - Interface signal sets: extend dv_harness/verible_parser.py's real port extraction (do not re-implement) to build per-module signal-set fingerprints for protocol matching.
   - Existing binds: a real repo-wide (or generated-environment-wide) grep -n "^\\s*bind " wrapper, parsed into structured (target, bound_module, instance_name) records.
   - VIP instances/config_db trace: same treatment as the env_manifest workstream's env_topology piece -- needs a real uvm_top.print_topology()/+UVM_CONFIG_DB_TRACE capture; build the generic capture+parser, honest NOT_AVAILABLE without a real dump. Coordinate conceptually with the env_manifest workstream's env_topology section (you are both consuming the same kind of capture) but do not block waiting for their file -- build against the same documented capture-output shape independently; a reconciliation pass across both workstreams' assumptions about that shape is expected and should be flagged in your report, not silently resolved by guessing.
2. The 4-tier confidence classifier (T1-T4) exactly as Part C defines it -- T1 accept-as-is, T2 auto-accept-but-list, T3 ALWAYS human-confirm (never auto-accept, even with high structural confidence), T4 goes to the question queue (call into dv_harness/question_queue.py's real Q-ID schema from the parallel workstream -- if that module isn't done yet when you need it, build against its documented schema shape from Part B above and flag reconciliation, same pattern as point 1).
3. The count-matching self-check equations as real, computable functions (not prose): VIP-instance-count == active-interface-count (not raw IP-instance-count); path-combination-count = master-count x reachable-slave-count for shared-fabric scoreboard sizing; slave/responder-role determination strictly from PORT DIRECTION, never from instance naming. Implement the hard self-check identity (sum(verified interfaces) == sum(VIP instances) + sum(explicit exemptions)) as an assertion that FAILS LOUDLY (not a warning) when it doesn't hold, per-line explanation required for any exemption.
4. Output the required matrix (DUT instance | interface | direction | role | VIP type | count | active/passive | bind target | tier) as both a structured JSON artifact and a human-readable table renderer.
5. The 3 machine gates as real, separately-invokable checks: Gate 1 (elaboration-check wrapper -- vcs -elab_only or slang, whichever is actually available; honest NOT_AVAILABLE + clear instructions if neither is installed here), Gate 2 (static zero-time connectivity -- design as a real waveform/testbench-probe check contract; since no live simv exists in this repo to run it against, build the real checking LOGIC plus a synthetic-signal-trace test fixture proving the logic itself is correct, and document the live-simv integration point honestly as NOT_AVAILABLE here), Gate 3 (transaction-activity check -- same treatment: real logic + synthetic fixture, live-simv integration documented not fabricated). A connectivity plan must be gated through all 3 before being presented for human confirmation -- implement this as an explicit pipeline function, not three independently-callable pieces a caller could skip.
6. A per-row confirmation/locking mechanism: once a row (interface or scoreboard-plan entry) is confirmed, store it as locked; a later regeneration must diff against locked rows and only re-surface rows that actually changed for re-confirmation. Real test: confirm a row, regenerate with no RTL change, assert zero rows need re-confirmation; regenerate with a simulated change to one row, assert exactly that one row needs re-confirmation.
7. The checker/scoreboard planning-table generator: classify each interface's needed checks into Protocol-check (VIP built-in -- output must explicitly list which built-ins are DISABLED and why, this list is the actual review deliverable per Part C) / Data-integrity (scoreboard, with all the required fields: endpoint pairs, matching key, ORDERING semantics, transformation rules, legal DROP/backpressure conditions, reset-flush behavior, orphan/unmatched threshold+timeout) / System-level. ORDERING and LEGAL-DROP fields must never receive a silent agent-chosen default -- the generator must emit these as explicitly REQUIRED-HUMAN-INPUT fields (null/TBD until a human fills them), never auto-filled with a guessed value.
8. Land the 4 fixed CLAUDE.md bind-location rules from Part C as a new, clearly-delimited CLAUDE.md section (read CLAUDE.md first -- it already has an "Architecture-conformance audit" section and other rule sections; follow its existing style/consolidation convention rather than inventing a new format). Also add a corresponding entry to the relevant existing skill (check .claude/skills/CORE/ for a bind/architecture-related skill already covering related ground -- e.g. anything referencing bind mechanics from the earlier USB_UVM_Handoff consolidation work -- cross-reference rather than duplicate if one exists).
9. Real tests for the tier classifier (all 4 tiers, including a genuine T3-must-never-auto-accept regression test), the count-check equations (both a passing and a deliberately-broken case), the per-row lock/diff mechanism, and the checker/scoreboard table generator's ORDERING/LEGAL-DROP-never-auto-filled guarantee.

Write a report to .work/mcp-bind-connectivity-report.md, explicitly listing every NOT_AVAILABLE-by-honest-design item (live-simv-dependent pieces) versus what's genuinely real and tested today. Run your new tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'build:bind_connectivity', phase: 'Build'})

const buildResults = await parallel([
  () => envManifest,
  () => mcpServer,
  () => questionQueue,
  () => bindConnectivity,
])

const [envManifestResult, mcpServerResult, questionQueueResult, bindConnectivityResult] = buildResults

phase('Finish')

const finishReport = await agent(`Write the final consolidated report for DV Agent Harness L5's "self-describing environment + MCP + question-queue + bind-connectivity" effort (4 workstreams: env_manifest, mcp_server, question_queue, bind_connectivity). Read all 4 workstream reports in full first:

D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-env-manifest-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-server-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-question-queue-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-bind-connectivity-report.md

Each workstream's own raw result text (for cross-referencing what each agent claimed vs its report file):

### env_manifest
${envManifestResult}

### mcp_server
${mcpServerResult}

### question_queue
${questionQueueResult}

### bind_connectivity
${bindConnectivityResult}

Your job, matching the standard this harness already applies (see the just-completed governance workflow's own finish-phase methodology as precedent -- it independently re-ran tests rather than trusting reported numbers):

1. Run the FULL project test suite yourself (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count -- do not trust any workstream's own reported numbers.
2. Specifically resolve the reconciliation points every workstream was told to flag rather than silently guess: the env.manifest.json field-shape assumptions made independently by env_manifest/mcp_server/bind_connectivity, and the Q-ID schema assumptions made independently by question_queue/bind_connectivity. State explicitly whether they actually agree, and if not, what the concrete mismatch is (do not paper over a real mismatch as "close enough").
3. Build an explicit READY/PARTIAL/BLOCKED table per workstream, matching the honesty standard the governance workflow's own finish report used (PARTIAL is a legitimate, expected status here given how much of Parts A/C genuinely requires a live simv this repo does not have -- report NOT_AVAILABLE-by-honest-design items as PARTIAL, not as failures).
4. List concretely what still needs the user's own action (e.g. running any of this against a real generated environment with a live simv, wiring the actual VIP-config-dump callback into a real project).
5. Note explicitly whether the CLAUDE.md bind-location-rules addition landed cleanly (check for section-numbering/duplication issues against CLAUDE.md's existing content).
6. Give a prioritized recommended-next-action list.

Write the consolidated report directly as your returned result (not a file this time -- the review agent will read your full returned text). Be exhaustive about real test numbers; this is the section most likely to get flagged by review if inflated.`, {label: 'finish', phase: 'Finish', model: 'claude-opus-5'})

phase('Review')

const review = await agent(`Independently review this entire 4-workstream "self-describing environment + MCP + question-queue + bind-connectivity" effort for DV Agent Harness L5, against the user's own stated bar from earlier in this same project: know when the harness must not act, be able to trace what it did, keep every change reversible -- AND against this specific effort's own core promise, that Tier-3/T3/T4 items are NEVER silently auto-resolved.

Read all 4 workstream reports plus the finish report:

D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-env-manifest-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-server-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-question-queue-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\mcp-bind-connectivity-report.md

Finish report (verify its own claims, do not trust it either):
${finishReport}

Specifically verify, by reading real code/running real commands yourself -- never by trusting any report's prose:
1. Re-run the full test suite yourself; confirm the finish report's pass/fail count independently.
2. Confirm the MCP server genuinely has no write code path (read the actual read-only-boundary test AND the server code itself -- a test asserting a property is not the same as the property being true).
3. Confirm the question-queue's Tier-3 trigger predicate genuinely cannot be bypassed to silently resolve a pass/fail-affecting or spec-intent question -- try to find a code path that would let it slip through as Tier-1/2.
4. Confirm the bind-connectivity system's T3 tier genuinely can never be auto-accepted -- read the classifier code directly, look for any default-to-accept fallthrough.
5. Confirm the checker/scoreboard table generator genuinely never auto-fills ORDERING or LEGAL-DROP fields -- find the actual field-population code and confirm it emits a required-human-input marker, not a guessed default, for both.
6. Confirm the repeat-question-rate=0 guarantee (decisions.md persistence) actually works by tracing the real code path, not just reading the test's assertion.
7. Check for git hygiene issues (uncommitted/unstaged files, whole-file staging accidentally sweeping in unrelated changes -- this exact failure mode occurred twice in the immediately-preceding governance workflow this session, so check for it explicitly here too).
8. Check whether any workstream silently invented plausible-but-unverified content (a fabricated example VIP config, a made-up register map, a guessed connectivity match) instead of honestly reporting NOT_AVAILABLE where a live simv/real tool was genuinely required and absent.

Report a clear verdict (APPROVED / NEEDS_FIX) with concrete, evidence-cited findings -- file:line where relevant. Distinguish real defects from honest, correctly-disclosed PARTIAL/NOT_AVAILABLE items (the latter are not defects).`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { envManifestResult, mcpServerResult, questionQueueResult, bindConnectivityResult, finishReport, review }
