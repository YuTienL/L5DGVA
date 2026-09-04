# Gap-close: Phase 23 + 24 + 15 — E2E synthetic test / Documentation / CLAUDE.md policy

**Status: DONE** (one real, closeable doc gap found and closed; everything
else re-confirmed as-is).

Scope: Phase 23 (end-to-end DV test), Phase 24 (documentation), Phase 15
(CLAUDE.md Engineering Memory Policy). Audit-only verdicts re-verified live,
then the one boundable gap completed for real.

---

## Phase 23 — End-to-End DV Test: **PARTIAL** (re-confirmed, correctly bounded — NO_ACTION_NEEDED)

Re-ran `python .work/e2e_usb3_lfps_demo.py` fresh this pass:

- `Chain result : COMPLETE (14 real steps; step 7's real-execution portion
  honestly marked PARTIAL -- no real LSF/VCS run was performed)`, exit 0.
- `.work/_e2e_demo_usb3_lfps/e2e_run_log.json` re-read: `execution_mode:
  LOCAL_ANALYSIS`; the only step carrying a `real_execution_status` is
  `verified_fix` → `PARTIAL_NOT_PERFORMED`. Every other step in the chain
  (failure → search_memory → hypothesis → evidence → confidence_pre_fix →
  gap_and_next_best_action → root_cause → job_memory (+ a FAIL attempt) →
  engineering_memory → promotion_evaluation → wiki_links → git_traceability →
  session_save_restore) ran against real, unmocked code.
- This run's real artifacts: Job note `MEM-A58A7B925F`, Engineering note
  `MEM-CC28D02388`, forward-link/backlink traversal both resolved through the
  real `list_links()`, vault git SHA `a35319c19fde88d036d15d7f596afdd49196f9d5`
  matched against the record's own `knowledge_commit_sha`, session
  save/restore returned a real resume summary.
- The backing regression test the audit cited still exists and passes — it has
  moved with concurrent edits, so citing it by name rather than line:
  `dv_harness_tests/test_memory_vault.py::test_vault_note_frontmatter_carries_the_records_measured_confidence`
  (currently line 606, was 518 at audit time).

The single PARTIAL leg (no real LSF/VCS submission) is the deliberate,
disclosed boundary this effort's own rules require — left as-is, not a
closable gap.

## Phase 24 — Documentation: **DONE** (one real drift closed, plus a machine check so it cannot recur silently)

### The audit's reported gap was already closed by concurrent work

`docs/MEMORY_SCHEMA.md`'s `MEMORY_NOTE_OPTIONAL_FIELDS` block **already**
contains `knowledge_commit_sha` at HEAD (`docs/MEMORY_SCHEMA.md:94`), added by
another workflow's commit `9d1ab74` (2026-09-04 09:24). Verified by comparing
the doc block against the live constant — all three field lists and the
11-entry body-section list match `dv_harness/memory_vault.py` exactly. Nothing
to fix there.

### A different, still-open drift of the same class was found and fixed

`docs/MEMORY_AGENT.md` quotes the Memory Agent's frontmatter as "real", but
had fallen a skill behind the live profile: commit `e1d328d`
(`memory(review): teach the doctor sweep as a skill and bind it to the Memory
Agent`) bound `CORE/memory-review` to `.claude/agents/memory-agent.md` without
updating the doc. Machine-verified before the fix — live 13 skills, doc 12,
`in live not doc: ['CORE/memory-review']` — and `memory-review` appeared
nowhere in `docs/` at all.

Fixed in `docs/MEMORY_AGENT.md`:
- `CORE/memory-review` added to the mirrored frontmatter block in the live
  file's own position (between `memory-link` and `obsidian-cli`).
- The "On request, for hygiene" invocation bullet rewritten to name the skill
  and its real backing (`memory_doctor.run_validate()`/`run_doctor()` —
  schema/`schema_status: PARTIAL`, duplicate ids, invalid YAML, broken
  `[[WikiLink]]`s, secrets, `memory_store_index` drift) and to state the real
  ordering constraint: `memory-review` decides, `memory-gc` acts. This
  replaces the vaguer previous wording, which described that hygiene work
  without naming the skill that now owns it (stale prose removed, not
  appended to).

### Why the existing checker did not catch either drift, and what now does

`python -m dv_harness.doc_citation_check --memory-docs` is symbol-anchored:
it proves a `module.py:123` citation still lands on the symbol the prose
names. It is structurally blind to a doc that **quotes a list** the source of
truth has since grown — the citation stays right while the copied list beside
it goes wrong. It reported `0 drifted` through both of these.

New regression test module, `dv_harness_tests/test_memory_docs_mirror_source.py`
(7 tests), comparing each quoted block against the live source of truth:
- `test_memory_agent_doc_frontmatter_mirrors_the_live_agent_profile` — parses
  both YAML blocks and asserts `name`/`tools`/`disallowedTools`/`model`/
  `skills` are equal (skill order included).
- `test_memory_agent_doc_names_every_bound_skill_in_its_prose_or_frontmatter`
  — a bound skill the doc never mentions is undiscoverable to its reader.
- `test_memory_schema_doc_field_lists_mirror_the_live_vault_constants`
  (parametrized ×3) — `MEMORY_NOTE_REQUIRED_FIELDS`,
  `MEMORY_NOTE_OPTIONAL_FIELDS`, `MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS`, order
  included (the doc presents them as the emitted frontmatter field order,
  which `render_note_markdown()` really honours).
- `test_memory_schema_doc_body_sections_mirror_the_live_vault_constant` —
  the 11-section body contract.
- `test_architecture_doc_tier_list_mirrors_the_live_memory_levels` —
  `MEMORY_ARCHITECTURE.md:76` quotes `MEMORY_LEVELS` inline as the tier order
  the whole doc is built on; asserted against `dv_harness.memory` (currently
  matching). Sensitivity confirmed by running the same extraction over a
  mutated string with `organizational` dropped → mismatch detected.

**Proven to actually catch the defect, not just to parse**: run against the
unfixed doc it failed with
`At index 10 diff: 'CORE/obsidian-cli' != 'CORE/memory-review'` and
`docs/MEMORY_AGENT.md never names bound skill(s) ['CORE/memory-review']`
(2 failed, 4 passed); after the doc fix, 7 passed. The 4 schema-doc tests
passing from the start is itself the live evidence that the audit's reported
`knowledge_commit_sha` gap is already closed.

All 5 required docs still present and cross-referencing correctly
(`MEMORY_ARCHITECTURE.md` 366, `MEMORY_SCHEMA.md` 273, `MEMORY_AGENT.md` 146,
`MEMORY_OPERATIONS.md` 253, `OBSIDIAN_INTEGRATION.md` 143 lines);
`python -m dv_harness.doc_citation_check --memory-docs` →
`8 citation(s) checked across 5 doc(s): 8 OK, 0 drifted, 0 unverifiable`,
exit 0, before and after the change.

## Phase 15 — CLAUDE.md Engineering Memory Policy: **READY** (re-confirmed — NO_ACTION_NEEDED)

Read `CLAUDE.md:35-107` directly this pass. All four required sub-sections are
present and substantively correct:

- **Before debugging** (`CLAUDE.md:44`) — search Project + Engineering Memory
  before a first hypothesis, names the real
  `python -m dv_harness.memory_cli search` command and the `memory-retrieval`
  skill, "candidate hypothesis to rank higher, never an accepted root cause".
- **During debugging** (`CLAUDE.md:54`) — Hypothesis → Evidence → Confidence →
  Gap → Next-Best-Action over the real `dv_harness.inference` functions, each
  transition a persisted Working Memory record (`kind="react_reasoning_step"`).
- **After verified PASS** (`CLAUDE.md:61`) — one Engineering Memory record
  carrying root cause + evidence + fix + verification + confidence; promotion
  only through `promote_to_organizational()`'s three gates, plus the
  `engineering_admission_gate()` and (since 2026-09-04)
  `organizational_admission_gate()` write-boundary enforcement paragraphs.
- **Never** (`CLAUDE.md:93`) — all three items present: secrets (backed by
  `route_memory()`'s hard `REJECT`), giant logs/raw FSDB (cite path/offset/
  signature only), promoting an unverified hypothesis.

Untouched — no change needed, and the section has only strengthened since the
audit.

---

## Files changed

- `docs/MEMORY_AGENT.md` — `CORE/memory-review` added to the mirrored
  frontmatter; hygiene invocation bullet rewritten to name the skill and its
  real doctor backing.
- `dv_harness_tests/test_memory_docs_mirror_source.py` — new, 7 tests.

No source module was modified; no other agent's in-flight file was touched
(`git diff -- docs/MEMORY_AGENT.md` showed only the two hunks above before
staging).

## Commits — and one history caveat worth knowing

- `45ee8eb` `memory(docs): guard the memory docs' quoted lists against source
  drift` — this pass's own commit, carrying the full rationale.
- **Caveat**: the doc fix and this test module's first 141 lines were staged
  (path-scoped `git add` on only my two files) when a concurrently-running
  agent's broad `git commit` swept the whole index into **`c43a9ed`**
  (`docs: record independent re-verification of VKA Section 3`) — a commit
  whose subject is unrelated to them. The content is correct and present at
  HEAD; only its commit message home is wrong. Deliberately **not** rewritten:
  other agents are actively committing on `gap-close/env-manifest-fact-sources`,
  and a rebase/amend there would be more damaging than a mis-attributed
  message. `45ee8eb` records the real rationale for all of it.

## Test summary

163 passed, 0 failed — `test_memory_docs_mirror_source` (7, new),
`test_doc_citation_check`, `test_agent_roster_doc`, `test_memory_review_skill`,
`test_memory_vault`, `test_memory_doctor`,
`test_obsidian_memory_final_integration`, `test_memory_dedup`,
`test_memory_security`, `test_cli_memory_commands` — re-run at final HEAD
(65s). Plus `doc_citation_check --memory-docs` 8/8 OK exit 0, and the Phase 23
e2e demo re-run to `COMPLETE`, exit 0.

A whole-`dv_harness_tests/` run was also started but exceeded 10 minutes
against a repo several other agents are concurrently writing to; it is not
reported as evidence here rather than reported on partial output. The change
under test is one doc edit plus one new isolated test module — no source
module was touched, so no suite outside the ten above can be affected by it.
