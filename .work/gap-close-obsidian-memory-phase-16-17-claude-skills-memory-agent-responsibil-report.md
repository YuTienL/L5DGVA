# Gap-Close Pass — Phase 16 + Phase 17 (Claude Skills + Memory Agent responsibilities)

**Result: NO_ACTION_NEEDED**

Both phases were audited READY. Per the task's rule 1 ("for every sub-item marked
READY: do nothing; re-confirm the cited evidence yourself"), this pass
re-derived every citation from the real files/code rather than trusting the
audit's summary. Every one held. **No file was created, modified, or deleted;
nothing was committed.**

Working tree at start of this pass: branch `gap-close/env-manifest-fact-sources`,
with concurrent-workflow churn already present (`dv_harness/engine.py`,
`dv_harness/stage_profile_report.py`, `.dv-harness/**`, several `.work/*.md`).
None of those files is in this scope and none was touched.

---

## Phase 16 — Claude Skills — re-confirmed READY

### All 12 CORE memory skills exist on disk

`ls .claude/skills/CORE/` confirms all 12 the audit named:
`memory-retrieval`, `memory-link`, `memory-review`, `obsidian-cli`,
`organizational-memory`, `engineering-memory`, `memory-consolidation`,
`memory-gc`, `memory-confidence-gate`, `working-memory`, `job-memory`,
`project-memory`.

### The 9-section structure claim is real (and the audit's own grep shape was wrong)

The audit asserted every skill carries Purpose / Inputs / Outputs / Preconditions /
Execution Steps / Fallback / Evidence Requirements / Failure Conditions / Example.
A naive `^## <Section>` grep returns **0** for all 12 — the sections are
`**Bold**:` inline markers under one `## Mechanics (…)` heading, not `##`
headings (see `.claude/skills/CORE/memory-retrieval/SKILL.md:11-25`). Re-run
against the real marker shape:

```
$ grep -oE '\*\*(Purpose|Inputs|Outputs|Preconditions|Execution Steps|Fallback|Evidence Requirements?|Failure Conditions?|Examples?)\*\*' <skill>/SKILL.md | sort -u
```

returns **all nine, in all twelve files**. The audit's conclusion was correct;
this pass records the correct verification command so a future re-check does not
mistake the heading shape for a missing section.

### The spec-name mapping claim is real

Directory presence check:

| spec name | on disk |
|---|---|
| `memory-search` | ABSENT (covered by `memory-retrieval`) |
| `memory-write` | ABSENT (covered by the 5 tier skills) |
| `memory-promote` | ABSENT (covered by `organizational-memory` + `memory-consolidation`) |
| `memory-link` | PRESENT |
| `memory-review` | PRESENT |
| `obsidian-cli` | PRESENT |

Per the governing "keep the better existing architecture" instruction, no
`memory-search/` / `memory-write/` / `memory-promote/` directory was created —
each would either thinly wrap or contradict the tier-differentiated write skills'
real preconditions, which is the duplicate-skill outcome the phase itself forbids.

### The check counts the skills document are exactly the real ones

Run for real against this repo's own vault:

```
$ python -c "from dv_harness import memory_doctor as md; ..."
validate checks: 5  ['broken_links', 'duplicate_ids', 'invalid_yaml', 'schema', 'secrets']
doctor   checks: 11 ['broken_links', 'duplicate_ids', 'filesystem_fallback', 'git',
                     'invalid_yaml', 'large_files', 'memory_store_index', 'obsidian_cli',
                     'schema', 'secrets', 'vault_writable']
validate overall: READY | doctor overall: PARTIAL
```

5 and 11 exactly, matching `memory-review/SKILL.md` and `memory-agent.md:95-101`.
`doctor overall: PARTIAL` is the disclosed Obsidian-CLI-absent fallback, not a
defect — correct as-is per task rule 3.

### There is already a doc-held-to-code regression test for this

`dv_harness_tests/test_memory_review_skill.py` (docstring lines 1-18: *"These are
NOT parse tests. Every claim the skill makes about the code is re-derived from
the real code on every run"*) holds both `.claude/skills/CORE/memory-review/SKILL.md`
**and** `.claude/agents/memory-agent.md` (`AGENT_PATH`, line 36, asserted at line 107)
to reality, including the sibling nine-section discipline across the other memory
skills. Run in this pass: **12 passed in 27.74s**.

---

## Phase 17 — Memory Agent — re-confirmed READY

`.claude/agents/memory-agent.md`, **161 lines** (`wc -l`), read in full. The audit
said 152 — a count difference only; every line number it cited resolved to the
content it claimed.

### Every function the agent cites exists

Verified by direct `grep -n` against `dv_harness/*.py`:

| cited symbol | real location |
|---|---|
| `route_and_store()` | `dv_harness/memory_router.py:140` |
| `promote_to_organizational()` | `dv_harness/memory_router.py:988` |
| `MemoryGC` | `dv_harness/memory.py:640` |
| `MemoryGC.deprecate/supersede/retract/flag_stale/confirm` | `memory.py:642/657/668/682/694` (all five real, on `MemoryGC` — a bare `grep "def deprecate"` hits `knowledge_center.py:249` first, a different class) |
| `MemoryRetriever` | `dv_harness/memory.py:437` |
| `CornerCaseLibrary` | `dv_harness/memory.py:733` |
| `get_active_provider()` | `dv_harness/memory_vault.py:1303` |
| `validate_note()` | `dv_harness/memory_vault.py:444` |
| `validate_note_frontmatter()` | `dv_harness/memory_vault.py:232` |
| `validate_note_body_sections()` | `dv_harness/memory_vault.py:409` |
| `_verification_is_gate_validated()` | `dv_harness/memory_router.py:1097` |
| `list_links()` | `dv_harness/memory_vault.py:841` |
| `_add_or_confirm_engineering()` | `dv_harness/memory_router.py:651` |
| `_maybe_write_vault_note()` | `dv_harness/memory_router.py:863` |
| `memory_dedup.classify_note_candidate()` | `dv_harness/memory_dedup.py:160`, called on the CREATE path at `memory_router.py:760` |
| `build_failure_signature()` / `search_related_memory_for_debug()` | `memory_vault.py:1555` / `:1707` |

### The 5 promotion reason codes are the real ones

`grep -n` in `dv_harness/memory_router.py`: `NOT_ENGINEERING_TIER` (1054),
`NOT_ACTIVE` (1056), `QUALITATIVE_GATE_FAILED` (464, 1060), `CONFIDENCE_NOT_HIGH`
(475, 1064), `INSUFFICIENT_CONFIRMATION` (470, 1069) — exactly the five the agent's
Evidence Discipline section (lines 159-161) promises to report.

### The dedup result keys the agent documents are the real ones

`memory_router.py:801-802` (`note_created`, `folded_into`, `dedup_classification`,
`dedup_similarity`) and `:933-934` — backing `memory-agent.md:64-79`'s two-layer
dedup description.

### The declared skill roster has no dangling reference

All **13** frontmatter `skills:` entries (12 CORE + `EXPERT_FEEDBACK/knowledge-promotion-gate`)
resolve to a real `SKILL.md` — missing: **NONE**.

### Every agent named in the exclusion boundary exists

`implementation-agent`, `rtl-evidence-agent`, `build-agent`, `regression-agent`,
`debug-agent`, `review-agent`, `issue_triage`, `analysis_debug` — all present under
`.claude/agents/`. The 3 spec-required exclusions plus the 2 additional ones are
therefore real handoffs, not references into nothing.

### The tool-restriction claim, stated precisely

The audit credited `disallowedTools: Edit, Write` (line 5) with the mechanical
enforcement. The load-bearing half is actually the **allowlist** on line 4 —
`tools: Read, Grep, Glob, PowerShell, Skill, Agent` — which already omits
`Edit`/`Write`; `disallowedTools` is a second, redundant belt. The audit's
conclusion (the agent cannot hand-edit a memory file) holds either way, and
`disallowedTools` is the house convention here, used by 14 other agent files
under `.claude/agents/`. No change warranted — recording the precise mechanism so
the claim is not over-attributed to the weaker of the two fields.

### CLI verbs the agent tells its operators to run are real

```
$ python -m dv_harness.cli memory --help
  {status,search,show,add,promote,graph,validate,sync,resync-notes,doctor}
$ python -m dv_harness.memory_cli --help
  {search,get,deprecate,corner-case-search,corner-case-get,corner-case-add,
   corner-case-deprecate,index-check,reindex}
```

`memory validate`, `memory doctor`, `memory promote`, and `memory_cli reindex`
(cited at `memory-agent.md:95-101, 147`) all exist.

---

## Summary

| Phase | Audit verdict | This pass | Action |
|---|---|---|---|
| 16 (Claude Skills) | READY | **re-confirmed READY** | none — no skill directory created; the 3 unnamed spec directories are deliberately absent and covered |
| 17 (Memory Agent) | READY | **re-confirmed READY** | none — every function citation, reason code, skill reference and handoff agent resolves to real code/files |

**Test summary**: no change made, so no new test was written; the existing
doc-held-to-code suite covering both phases' artifacts,
`dv_harness_tests/test_memory_review_skill.py`, was run as corroboration —
**12 passed in 27.74s**.

**Corrections to the audit** (both cosmetic, neither changes a verdict):
`memory-agent.md` is 161 lines, not 152; and the 9 required skill sections are
`**Bold**:` markers, not `##` headings — a `##`-shaped grep reports 0 sections in
all 12 files and would wrongly read as a gap on any future re-audit.
