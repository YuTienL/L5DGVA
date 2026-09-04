# Phase 16 (Claude Skills) + Phase 17 (Memory Agent) — Gap Close

**Verdict: DONE.** One real, closeable gap (`memory-review`) was built and bound;
everything else in the incoming audit was re-confirmed READY and left untouched.

Test summary: `12 passed` for the new `dv_harness_tests/test_memory_review_skill.py`
(mutation-checked — renaming one documented check key really fails 2 of them), and
`294 passed in 281.36s` across all 14 memory test files plus
`test_agent_dispatch_map.py` / `test_skill_resolver.py`.

---

## What changed

| File | Change |
|---|---|
| `.claude/skills/CORE/memory-review/SKILL.md` | **NEW.** The skill that covers `dv_harness/memory_doctor.py` and the `dv-harness memory validate` / `memory doctor` subcommands. |
| `.claude/agents/memory-agent.md` | Binds `CORE/memory-review` (`:18`); new **Review** responsibility (`:86-92`); "Periodic hygiene" now starts from a real `doctor` run instead of an ad-hoc scan (`:130-140`). +17/−3, no other hunk.<br>Now 152 lines. |
| `dv_harness_tests/test_memory_review_skill.py` | **NEW**, 12 tests. |

Commits: `memory(review): teach the doctor sweep as a skill and bind it to the
Memory Agent` and the `docs:` commit carrying this report.

---

## PHASE 16 — the one BLOCKED item, now closed

The audit's `memory-review` finding was re-verified before building, not assumed:

- `grep -rl "memory_doctor\|run_doctor\|run_validate\|memory doctor\|memory validate" .claude/`
  returned **zero files**. No skill under any name taught this.
- `memory-gc/SKILL.md:19-33` really is actions-only (`deprecate`/`supersede`/
  `retract`/`flag_stale`/`confirm`) with no review/decide step; `memory-consolidation`
  really is scoped to `_verification_is_gate_validated()` alone.
- `memory-agent.md`'s "Validate" responsibility really did cite only
  `validate_note()` + the consolidation gate — the store-wide sweep had no
  bound skill behind it.
- Both CLI subcommands are real and callable: `dv-harness memory validate`
  (`cli.py:2208` → `memory_doctor.run_validate`, `memory_doctor.py:285`) and
  `dv-harness memory doctor` (`cli.py:2237` → `run_doctor`, `:309`).

The new skill carries the same 9-section structure as its siblings (asserted
against `memory-link`/`memory-gc`/`memory-retrieval` by test) and teaches:

- the **5** `run_validate()` correctness checks and the **11** `run_doctor()`
  checks, each named with what it really catches;
- `validate_note_frontmatter()`'s COMPLETE-vs-PARTIAL result over
  `MEMORY_NOTE_REQUIRED_FIELDS` (`memory_vault.py:204`, `:128`), and the body
  half that catches an Obsidian-GUI edit which deleted or reordered a section;
- the `BLOCKED > PARTIAL > READY` aggregation and the CLI's exit-1-only-on-
  BLOCKED rule;
- the two states that **look** like defects and are not — `git: DISABLED`
  (`check_git()`, `:104`) and `obsidian_cli: PARTIAL`, i.e. this effort's own
  disclosed fallback, so the skill cannot become a reason to "fix" it;
- that repairs go through the real API (`provider.update()`, `MemoryGC`,
  `memory_cli reindex`), never a hand-edit — the same non-bypassable boundary
  `disallowedTools: Edit, Write` already enforces on the agent.

**The skill is held to the code by test, not by review.** `test_memory_review_skill.py`
parses the skill's two documented check lists out of `<!-- validate-checks -->` /
`<!-- doctor-checks -->` anchors and asserts they **equal** the keys
`run_validate()`/`run_doctor()` really return for a real bootstrapped vault; it
drives both CLI subcommands as real subprocesses against a real temp project root;
and it builds a vault with a genuinely schema-PARTIAL note, a real broken
wiki-link and a real duplicate id to prove PARTIAL/BLOCKED are actually produced
and that every status the code emits is one the skill documents. Same
doc-held-to-code discipline as `mcp/claude_md_index.py` and
`source_authority.assert_doc_matches_code()`.

Mutation check (evidence the binding is real, not decorative): renaming
`large_files` → `large_filez` in the skill made
`test_documented_doctor_checks_equal_real_run_doctor_keys` and the `doctor` CLI
parametrization fail; restoring it returned all 12 to pass.

## PHASE 16 — the five READY items, re-confirmed, NOT rebuilt

Each was re-read this pass. All five are real, differently-named-but-equivalent,
and already bound — building spec-literal duplicates would have been the
"parallel/conflicting framework" this effort forbids.

| Required name | Real skill | Re-confirmed |
|---|---|---|
| `memory-search` | `CORE/memory-retrieval/SKILL.md` (72 lines) | All 9 sections present; two real backends + the CLI filter surface; `rg`→pure-Python fallback. Bound `memory-agent.md:16`. |
| `memory-write` | 5 per-tier skills (`working`/`job`/`project`/`engineering`/`organizational-memory`, 57–80 lines each) | Kept as the more precise split — each tier's preconditions genuinely differ (job = none; project/engineering = `verified:true`; organizational = promotion-only, never a direct write). |
| `memory-promote` | `CORE/organizational-memory` (90 lines) + `EXPERT_FEEDBACK/knowledge-promotion-gate` (64 lines) | Bound `:13,:19`. |
| `memory-link` | `CORE/memory-link` (77 lines) — exact name | Bound `:17`. Its own "links are never validated at write time" Failure Condition is now the periodic sweep `memory-review`'s `broken_links` check answers — cross-referenced in the new skill. |
| `obsidian-cli` | `CORE/obsidian-cli` (81 lines) — exact name | Bound `:19` (was `:18`, shifted by one line by this change). |

## PHASE 17 — Memory Agent: READY, extended not rebuilt

`.claude/agents/memory-agent.md` already had all 10 required
responsibilities and an exclusion list that exceeds the required 3. No new agent
was created. The audit's one linkage note was the follow-up this pass closed:
with `memory-review` now existing, the agent's skill list, its Validate
responsibility and its Periodic-hygiene step cite it.

The structural enforcement re-verified unchanged: frontmatter
`disallowedTools: Edit, Write` (`:5`) still blocks the agent from ever calling
Edit/Write, so every memory mutation must go through the real router/provider API.

## Boundaries and non-actions

- **No PARTIAL item was in scope.** Phase 16/17's audit produced only READY and
  one BLOCKED; the Obsidian-CLI-absent fallback is a correctly disclosed boundary
  and the new skill documents it as such rather than treating it as a gap.
- **Shared files**: only `.claude/agents/memory-agent.md` is shared, and it was
  clean before this change; its diff is +17/−3, entirely my three hunks.
  `CLAUDE.md`, `cli.py`, `memory.py`, `memory_router.py` were **not** modified.
- **No stale comment or dead code** was found in anything touched; the one
  outdated sentence encountered (memory-agent's hygiene step describing an
  ad-hoc `schema_status` scan that a real command already does better) was
  rewritten rather than left beside the new text.
- `industrial` / `PACKAGE` deliverable trees are not present in this repo
  (`git ls-files` returns nothing under either), so the Methodology
  Consolidation Rule's sync clause is a no-op here.
