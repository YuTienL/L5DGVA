# Gap-close: MCP query interface (5 exact verbs + read-only + CLAUDE.md index-only)

**Verdict: DONE** (one real gap closed, one re-scoped, one reported as a separate effort).

Scope: `dv_harness/mcp/`, `CLAUDE.md`. Re-verified against current HEAD on
`gap-close/env-manifest-fact-sources`, not against the prior session's claims.

---

## Requirement 1 — exactly 5 verbs, correct signatures: **READY, re-confirmed**

No change made. Re-confirmed with current evidence:

- `dv_harness/mcp/verbs.py:268-274` — `VERBS` holds exactly the 5 names and nothing else.
- `dv_harness/mcp/verbs.py:277-293` — one `dispatch()`, raising `McpUnknownVerbError` for any
  name outside that set (verbs.py:283-285). No catch-all branch exists.
- `dv_harness/mcp/server.py:57-105` — exactly 5 `@server.tool()` registrations, each with
  individually-typed keyword args; no free-text/raw-SQL parameter anywhere.
- `dv_harness/mcp/schema.py:44-93` — `PARAM_SCHEMAS`, `additionalProperties: false` on all 5.

Live run this session, before any of my edits:
`python -m pytest <the 6 existing mcp test modules> -q` → **98 passed in 148.88s**.

## Requirement 2 — auditability / fixed schema / read-only: **READY, re-confirmed**

No change to the enforcement itself. Re-confirmed:

- `manifest_source.py:22-38` — `load_manifest()` is the package's only manifest access and only
  ever `Path.read_text()`s; no writer exists in the module.
- `runtime.py:78` — `EvidenceStore(self.evidence_db_path, read_only=True)`; `evidence_db.py:272`
  opens `duckdb.connect(path, read_only=True)`, refused at the engine level. The 2026-09-03 fix is
  present and unchanged.
- `test_mcp_read_only_boundary.py` — AST scan across every file in `dv_harness/mcp/` plus a
  behavioral SHA-256-unchanged proof. It is genuinely load-bearing, not decorative: **it caught a
  real hit in my own new module during this pass** (`claude_md_index.py:283: replace(...)`, from a
  harmless `str.replace(".", "/")` the name-based scanner cannot distinguish from `Path.replace`,
  a filesystem rename). I conformed to the conservative rule rather than weakening the scanner —
  `claude_md_index.py` now builds that path with `Path(REPO_ROOT, *SERVER_MODULE.split("."))`, with
  a comment saying why, so nobody reintroduces it.

### One real accuracy defect found and fixed

`schema.py`'s `RESULT_SCHEMAS` header comment claimed "**`verb` + `status` are present on every
single result**". That is false for `get_topology`, whose real required envelope
(`schema.py:130-141`) is `component_hierarchy_status` + `config_db_trace_status` — two sub-layer
statuses, deliberately, because `uvm_top.print_topology()` output and `+UVM_CONFIG_DB_TRACE` are
separate real sources and either can be absent while the other is captured. Found by a test I wrote
asserting the documented envelope, which failed against the real runtime. Comment corrected; the
code was right, the comment was wrong.

## Requirement 3a — CLAUDE.md MCP index: was BLOCKED, **now CLOSED**

The audit's "zero references to manifest/verb/get_vip_config" finding was accurate **when taken**
but is now stale in one direction: a concurrent workstream landed
`## Context Budget: 3 Tiers + MCP-First Routing` (CLAUDE.md:818-881), whose closing paragraph
(CLAUDE.md:873-880) does name all 5 verbs and does say read-only. CLAUDE.md is now 940→989 lines,
not the audited 608.

What that paragraph still did **not** provide, and what an index has to: which verb answers which
question, what each verb's required arguments are, which two on-disk paths this server reads, how
to run it, and where the protocol list comes from. An agent could learn 5 verbs exist without
learning which one to call.

**Built:**

1. **`CLAUDE.md:884-931`** — new `## MCP Query Interface: the 5 Verbs (index) (2026-09-04)`.
   Index + rules only: a one-line "ask it when" and required-args cell per verb, the two read-only
   fact sources, the run command, and pointers to `dv_harness/mcp/schema.py` /
   `.work/mcp-server-report.md` for detail. ~48 lines; no schemas, no mechanics inlined.

2. **`dv_harness/mcp/claude_md_index.py`** (new, 340 lines) — the index is **parsed and compared
   against the code**, following this repo's own established
   `source_authority.assert_doc_matches_code()` precedent. `check_index()` / `assert_index_matches_code()`
   enforce, with a concrete message per failure:
   - verb rows == `verbs.VERBS` (both directions — a 6th verb with no row fails, a row for a
     deleted verb fails);
   - each row's required args == that verb's real `schema.PARAM_SCHEMAS[verb]["required"]`;
   - the shapes named == `regression_queries.QUERY_SHAPES`;
   - the fact-source paths == the **code-owned** paths, read not retyped:
     `evidence_db.DB_PATH_PARTS` and `context_budget.policy.json`'s tier-2 `env.manifest.json`
     artifact declaration;
   - the `python -m` invocation names a module that exists and flags `server.py`'s argparse really
     defines (parsed out of its source, so this check still runs without the `mcp` SDK installed);
   - every `.py`/`.md` path the index cites for detail really exists (a dead "details on demand"
     pointer turns the index into a dead end);
   - the index **routes** "which protocols exist" to `get_vip_config` rather than inlining a
     protocol list.

   That last rule is deliberate and is the requirement-3a "which protocols exist" answer. A
   hardcoded protocol list in CLAUDE.md would be a per-environment manifest fact frozen into a
   rules file — stale the day a second environment is built, and exactly the "details, not index"
   bloat requirement 3b is about. `get_vip_config` with no arguments returns every captured
   instance's `vip_type`, which is the live answer; a test proves that route really works.

   Also runnable standalone: `python -m dv_harness.mcp.claude_md_index` →
   `CLAUDE.md MCP index OK -- 5 verbs, 4 query shapes, 2 read-only fact sources, all match the code.`

3. **`dv_harness_tests/test_mcp_claude_md_index.py`** (new, 26 tests, three layers):
   - **non-drift on the real file** — `assert_index_matches_code()` against the real repo CLAUDE.md
     and the real verbs/schemas/shapes;
   - **the checker actually checks** — every drift class is exercised by mutating a copy of the
     real section and asserting the checker reports that exact problem: a 6th verb in code with no
     row, a row for a nonexistent verb, a wrong required arg, a dropped required arg, a stale query
     shape, a wrong fact-source path, a third fact source, a wrong server module, an invented
     `--allow-write` flag, a dead detail citation, an inlined protocol list, and a missing section.
     Without this layer a checker that returned `[]` unconditionally would pass forever;
   - **the index's claims are true end-to-end** — every advertised verb really answers through a
     real `ReadOnlyMcpContext` over a real on-disk manifest file (not a mock, not an in-memory
     dict), each result carrying every key its real `RESULT_SCHEMAS[verb]["required"]` names;
     omitting a documented-required arg really raises `McpValidationError`; `get_vip_config` with
     no args really returns per-instance `vip_type`; and a verb outside the 5 (`read_file`) is
     really refused.

## Requirement 3b — "index + rules only" for CLAUDE.md as a whole: **NEEDS_SEPARATE_EFFORT**

Confirmed still real and, if anything, worse: CLAUDE.md is now **989 lines / ~68 KB**, up from the
audited 608/39 KB, because several concurrent workstreams each landed a section during this
session. Large inlined-mechanics sections remain (Engineering Memory Policy, gh CLI + PR-Only
Governance, Bind-Location Rules, Context Budget, Source Authority Order).

This is not closeable inside this scope, for two honest reasons rather than one:

1. **Ownership.** Trimming those sections means rewriting other workstreams' in-flight content
   while they are still editing the same file. That is a merge conflict machine, and the trimming
   agent is not the one who knows which sentence in someone else's section is load-bearing.
2. **It needs a target and a gate, not a cleanup pass.** Doing it properly means a byte budget per
   section, a destination for what gets moved out (skills / `docs/` / `.work/` reports), and a
   check that fails when the file exceeds budget — otherwise it regrows within a session, which is
   demonstrably what happened here.

My own section is written to that standard as a worked example (index + rules only, ~48 lines,
detail deferred to two cited files, machine-checked), but making the *whole file* meet it is a
separate, coordinated effort.

## Requirement 4 — per-protocol CLAUDE.md split: **not applicable, re-confirmed**

Re-verified: `project_input/04_protocol/{amba,canfd,ethernet,mipi,pcie,usb}` still hold only sparse
placeholder/spec files and no per-protocol built environment exists, so a single global CLAUDE.md
remains correct. Note the new index section is written so this stays true without edits: it routes
the protocol question to `get_vip_config` instead of listing protocols, so a second environment
does not make the file wrong.

---

## Test summary

`python -m pytest` over the 6 existing MCP modules + the new index module + `test_context_budget.py`
+ `test_source_authority.py` (the two other suites that parse CLAUDE.md) →
**246 passed in 245.92s (0:04:05)**, exit 0. The 26 new tests in
`dv_harness_tests/test_mcp_claude_md_index.py` are included in that count, and
`python -m dv_harness.mcp.claude_md_index` prints
`CLAUDE.md MCP index OK -- 5 verbs, 4 query shapes, 2 read-only fact sources, all match the code.`
and exits 0.

Baseline for comparison: the same 6 pre-existing MCP modules alone were **98 passed** before any of
my edits, so nothing that was passing stopped passing.

## Files changed

- `CLAUDE.md` — +48 lines, one new section inserted between `## Context Budget` and
  `## Source Authority Order`. No existing line touched.
- `dv_harness/mcp/schema.py` — corrected one inaccurate `RESULT_SCHEMAS` header comment. No code.
- `dv_harness/mcp/claude_md_index.py` — new.
- `dv_harness_tests/test_mcp_claude_md_index.py` — new.

Concurrency note: `git status` showed no other agent had modified any of these four paths, and
`git diff --stat` on the two edited files showed only my hunks, so a path-scoped `git add` of
exactly these four was sufficient — no patch trimming was needed.
