# M4.6 — CLAUDE Context Normalization — Final Report

## Safety (S1, re-verified at closure)

```
PROCESS_CWD = D:\DV\Task\L5_DGVA
REPO_ROOT   = D:\DV\Task\L5_DGVA
is_l5dgva_repo() = True
CURRENT_BRANCH = canonical/m4-dependency-closure
CURRENT_HEAD (closure) = c877944be30b0d969d89bc57b5703974c6bf211f
git status --short = " M .dv-harness/events.jsonl" only (append-only event log)

SOURCE_A (Parent) HEAD = 3e9dd7360f584078ed8f4b04120c9844acabd97b  UNCHANGED
SOURCE_B (v50) HEAD    = f3fd17326cf3654aca6fd83fad991a3f247e6682  UNCHANGED
B7A HEAD = 7b2a65a4dc2d40d493451b409669c90ed0b3d9a5  UNCHANGED
B7B HEAD = c7c7fa09e9ee8336ba102b4495f4b8808408fe0b  UNCHANGED
B8  HEAD = c9cdd06ce586d44f4c0cef00310c10f95ea59f93  UNCHANGED

Constitution/Anti-Drift gate (before editing) = PASS, 0 reasons
Constitution/Anti-Drift gate (at closure)     = PASS, 0 reasons
```

## Commit chain (checkpoint vs. fix vs. this report — kept distinct)

```
M4_6_CAPABILITY_CHECKPOINT_SHA = 030c4eb  -- the M4.6 implementation
  (CLAUDE.md split + 7 registered detail docs + claude_reference_graph.py).
  The FIRST regression run was against this SHA and found a real,
  confirmed regression (see below) -- this checkpoint did NOT itself
  close clean.
030c4eb -> c877944  -- the REAL FIX commit (not report-only): restored
  3 Research Front Door discoverability facts to CLAUDE.md's ALWAYS_ON
  content. A SECOND full regression ran against c877944.
c877944  -- CURRENT_HEAD, the SHA this final report and its
  READY_FOR_APPROVAL verdict are issued against.
```

## Regression run 1 — against 030c4eb (found a real regression)

```
REGRESSION_HEAD = 030c4eb  -- MATCHES the required checkpoint (no mismatch)
EXACT_COMMAND = python -m pytest -q --tb=no -o cache_dir=.pytest_cache_m4_6
COLLECTED = 13896 (30 failed + 13837 passed + 28 skipped + 1 xfailed)
PASSED = 13837
FAILED = 30
SKIPPED = 28
XFAILED = 1
DURATION = 4172.82s (1:09:32)
CHILD_EXIT_CODE = 1 (captured via `$?`, real pytest exit -- the
  background task's own reported "exit code 0" was the shell chain's
  trailing `echo`, not pytest; the real value was read from the
  redirected EXIT_CODE= line in the output file, not assumed)
CRASH_STATUS = NO (0 Traceback/INTERNALERROR/Fatal Python error lines)
TIMEOUT_STATUS = NO
COMPLETION_MARKER = "30 failed, 13837 passed, 28 skipped, 1 xfailed, 1 warning in 4172.82s"
```

**Failure-set differential vs. the accepted M4 closure regression** (27
failures, `M4_closure_regression_output.txt`), by `TEST_IDENTITY`:

```
COMMON = 27, NEW = 3, GONE = 0
NEW (all in dv_harness_tests/test_research_intent_routing.py):
  test_claude_md_documents_the_research_front_door
  test_claude_md_names_the_real_approval_stage_not_a_retyped_one
  test_claude_md_records_that_slash_research_is_not_this_repos_mechanism
```

**Root cause, confirmed by isolated rerun** (`pytest -k claude_md` on
just this file): these tests assert specific research-entry-point facts
exist as **literal substrings in CLAUDE.md itself** —
`"dv-harness research"`, `".claude/skills/research-ingestion/SKILL.md"`,
`".claude/agents/research-architect.md"`, the research-ingestion ->
research-architect route order, `"Human Approval Gate"`,
`"dv-harness approve RESEARCH_CAPABILITY_EVOLUTION"` (verified against
the real `capability_evolution.HUMAN_APPROVAL_STAGE` constant, not
assumed), and `".claude/commands/"`. By each test's own docstring, this
is deliberate: a future reader must discover the research front door
"without the master prompt in hand." M4.6's classifier correctly routed
the *detailed* Research Front Door/Stage Boundaries sections to
`KNOWLEDGE_MEMORY_RESEARCH.md`, but missed that this specific
fact-subset is itself a universal discoverability guarantee that
belongs `ALWAYS_ON` under this file's own S4 criteria
("stop/escalation rules that apply universally").

**Classification: `REGRESSION_CAUSED_BY_M4_6 = 3` at checkpoint
`030c4eb`** (genuinely caused by this wave — not `PRE_EXISTING`,
`ENVIRONMENT`, `TEST_INFRASTRUCTURE`, or `UNKNOWN`). The other 27 are
the identical `PRE_EXISTING` set M4 already closed with (byte-identical
test-ID list; see the diff below). `UNKNOWN_REGRESSION_FAILURES = 0`
even at this first checkpoint.

No production/governance code was modified during this classification
step — the fix followed only after root cause was confirmed.

## Fix (commit `c877944`)

Added a compact `ALWAYS_ON` "Research Front Door" paragraph under
CLAUDE.md's existing "Continuous Research Evolution" section (+18 net
lines), restating the required facts directly, cross-referenced to the
full detail in `KNOWLEDGE_MEMORY_RESEARCH.md`. Also fixed a second,
related reference-drift bug in the same paragraph ("see the ... sections
above," which had gone stale). Verified immediately:
`test_research_intent_routing.py` 87/87 (was 84/87);
`test_governance_registry.py` + `test_l5dgva_constitution.py` +
`test_claude_reference_graph.py` + `test_context_budget.py` 113/113;
Constitution gate PASS; registry reachability 0 broken.

## Regression run 2 — against `c877944` (real closure verification)

```
REGRESSION_HEAD = c877944  -- MATCHES the fix commit
EXACT_COMMAND = python -m pytest -q --tb=no -o cache_dir=.pytest_cache_m4_6b
COLLECTED = 13896 (27 failed + 13840 passed + 28 skipped + 1 xfailed)
PASSED = 13840
FAILED = 27
SKIPPED = 28
XFAILED = 1
DURATION = 4269.14s (1:11:09)
CHILD_EXIT_CODE = 1 (captured via `$?`, real value, same discipline as run 1)
CRASH_STATUS = NO
TIMEOUT_STATUS = NO
COMPLETION_MARKER = "27 failed, 13840 passed, 28 skipped, 1 xfailed, 1 warning in 4269.14s"
```

**Failure-set differential vs. the accepted M4 closure regression**,
computed with `diff` on sorted `FAILED ` lines (not eyeballed):

```
diff .../M4_closure_regression_output.txt(sorted) .../M4_6b_output.txt(sorted)
=> zero output -- the two 27-line sorted failure lists are BYTE-IDENTICAL
COMMON = 27, NEW = 0, GONE = 0
```

**Part B — against the frozen v50/M1D baseline**: not re-derived from
scratch (per instruction #2, reuse accepted evidence) — M4's own
closure already established `COMMON = 21, NEW = 6` against the frozen
v50 baseline (`_h2_6_final_run.log`), with those 6 fully diagnosed as
`TEST_INFRASTRUCTURE` during M1. Since this run's failure set is
byte-identical to M4's own already-reconciled set, that relationship is
unchanged and does not need re-computation.

```
REGRESSION_CAUSED_BY_M4_6 = 0
UNKNOWN_REGRESSION_FAILURES = 0
```

## Content-preservation + routing/reachability reconfirmation (S6)

A verbatim move alone is insufficient if a rule becomes undiscoverable
— both were checked, not assumed:

```
CONTENT PRESERVATION: all 321 relocated sections present verbatim in
  their 7 target documents, cited by original CLAUDE.md line range in
  M4_6_CLAUDE_SECTION_INVENTORY.csv. Byte totals re-verified this wave
  (VIP_PROTOCOL_GENERATION.md 897,867 B; GOVERNANCE_SAFETY_AUDIT.md
  276,566 B; GUI_DASHBOARD_WEB.md 245,047 B; KNOWLEDGE_MEMORY_RESEARCH.md
  213,051 B; EXECUTION_REMOTE_REGRESSION_RCA.md 158,510 B;
  INTAKE_CLARIFICATION_QUESTION.md 124,807 B; HISTORICAL_AUDIT_NOTES.md
  58,330 B).
ROUTING/REACHABILITY PRESERVATION: dv_harness.governance_registry.
  check_reachability() = 0 broken (re-run at closure HEAD c877944).
  dv_harness.claude_reference_graph.validate_reference_graph() = VALID
  (7/7 CLAUDE.md routing-table ids match real registry entries).
  validate_authority_execution_graph() resolves all 5 required
  conceptual scopes to real governance + real .claude/skills or
  .claude/agents evidence (test_claude_reference_graph.py, 10/10,
  re-run at closure HEAD).
  The regression run itself is additional, stronger proof: the one case
  where a rule DID become effectively undiscoverable (the Research
  Front Door facts) was caught by a REAL failing test, not missed --
  the safety net worked as designed.
```

## Master Capability Status Matrix (S7 of the follow-up instruction — applied in commit 030c4eb, confirmed still correct at closure)

```
TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL
CLAUDE_ALWAYS_ON_CONTEXT_NORMALIZATION = OPERATIONAL
  (CAP-M4.6-001; now confirmed justified -- final closure passes)
MINIMUM_SUFFICIENT_CONTEXT = PARTIAL
  (real improvement; no per-domain further distillation yet -- SUMMARY_PATH
   == FULL_SPEC_PATH for all 6 new TASK_SCOPED entries, disclosed)
CHATGPT_PLANNING_OFFLOAD = NOT_PRESENT (HUMAN_MEDIATED as established), OWNER = M7
CODEX_REVIEW_OFFLOAD = NOT_PRESENT (HUMAN_MEDIATED as established), OWNER = M7
STRUCTURED_AGENT_HANDOFF = PARTIAL, OWNER = M7
TOKEN_USAGE_OBSERVABILITY = PARTIAL, OWNER = M7
TOKEN_REDUCTION_MEASURED = NO
```

No M7 capability's `CANONICAL_STATE` was marked operational — only the
`PRIMARY_OWNER_WAVE` was reassigned M8->M7, per instruction.

## Required fields (S25 / follow-up S8)

```
M4_6_STATUS = READY_FOR_APPROVAL
M4_6_CAPABILITY_CHECKPOINT_SHA = 030c4eb
M4_6_BRANCH = canonical/m4-dependency-closure
M4_6_HEAD (closure / this report) = c877944be30b0d969d89bc57b5703974c6bf211f

CLAUDE_MD_LINES_BEFORE = 22461
CLAUDE_MD_LINES_AFTER  = 1655
CLAUDE_MD_BYTES_BEFORE = 2067655
CLAUDE_MD_BYTES_AFTER  = 113125
CLAUDE_MD_BYTE_REDUCTION = 1954530 bytes (~94.53%)

SECTIONS_RELOCATED = 321
REGISTERED_GOVERNANCE_DOCUMENTS = 7
ALWAYS_ON_SECTIONS = 42 (+ the 1 compact Research Front Door paragraph
  added at closure, inside the pre-existing Continuous Research
  Evolution ALWAYS_ON section -- not a new section, a real addition to
  an existing one)
TASK_SCOPED_SECTIONS = 301
EVIDENCE_ON_DEMAND_SECTIONS = 20

AUTHORITY_LOSS = 0
BEHAVIORAL_GOVERNANCE_LOSS = 0
  (the one instance found -- Research Front Door discoverability --
   was CLOSED by the c877944 fix before this report was finalized, per
   this program's standing "actionable findings must close before
   Final Deep Audit" rule; it is disclosed above, not hidden)
UNRESOLVED_CONTEXT_CLASSIFICATION = 0

TASK_SCOPED_GOVERNANCE_RETRIEVAL = OPERATIONAL
MINIMUM_SUFFICIENT_CONTEXT = PARTIAL
CLAUDE_REFERENCE_GRAPH = VALID
CLAUDE_AUTHORITY_EXECUTION_GRAPH = VALID
  (disclosed bound, unchanged from the pre-fix report: indexes
   governance docs + agent/skill files; does not yet separately index
   contracts/templates/tools as distinct node types)

TOKEN_REDUCTION_MEASURED = NO

REGRESSION_CAUSED_BY_M4_6 = 0
UNKNOWN_REGRESSION_FAILURES = 0

ARTICLE_0_REACHABLE = YES
P1_P5_REACHABLE = YES
ANTI_DRIFT_REACHABLE = YES
REPOSITORY_ROOT_CONTRACT_REACHABLE = YES (naming equivalence disclosed:
  no literal "Repository Root Contract" heading exists in canonical;
  satisfied via the "AI Agent Harness L5 Canonical Identity" heading +
  the real, tested dv_harness.l5dgva_repo identity-verification code)
GOVERNANCE_DUMP = PROHIBITED (test-verified)
ROOT_LAYOUT_GATE = PASS
LOCATION_INDEPENDENT = YES

M5_STARTED = NO
M6_STARTED = NO
M7_STARTED = NO
REFERENCE_USB_ENV_CONSUMED = NO
PLATFORM_UPGRADE_STARTED = NO
```

## Known, disclosed limitations (unchanged from the pre-fix report, still real)

1. `MINIMUM_SUFFICIENT_CONTEXT` stays `PARTIAL` — verbatim relocation
   only, no per-domain distillation yet.
2. The 65,536-byte `claude_md_index` residency budget is not fully met
   (113,125 bytes, ~1.7x over — down from ~31.6x over before M4.6).
3. `CLAUDE_AUTHORITY_EXECUTION_GRAPH` does not yet separately index
   contracts/templates/tools as distinct node types.
4. 14 of 363 sections were classified via a lower-confidence keyword
   fallback (still decisive, not `UNKNOWN`), disclosed in
   `M4_6_CONTEXT_CLASSIFICATION.csv`.
5. One section (`S063`) was manually re-targeted after an initial
   keyword misroute (disclosed in `M4_6_TASK_SCOPED_ROUTING.md`).
6. One real regression (3 tests, `REGRESSION_CAUSED_BY_M4_6 = 3` at
   checkpoint `030c4eb`) was found, root-caused, and closed by commit
   `c877944` before this report — disclosed above in full, not omitted.

**STOP. M4_6_STATUS = READY_FOR_APPROVAL. Do not start M5/M6/M7. Waiting
for explicit approval.**
