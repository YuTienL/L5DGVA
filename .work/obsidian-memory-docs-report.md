# Workstream 4a Report — Documentation, Skill Consolidation, Memory Agent, Engineering Memory Policy

Scope: Phases 15, 16, 17, 24 of the Obsidian+Git/Markdown Hybrid Engineering
Memory integration. Depends on Workstream 1 (core), confirmed DONE at
commit `ceab932`.

## Files created

- `.claude/agents/memory-agent.md` — new agent (Phase 17). Frontmatter/structure
  matches `debug-agent.md`/`regression-agent.md` convention. Responsibilities:
  search/retrieve/summarize/write/link/deduplicate/promote/demote/archive/
  validate, always through the real API (`route_and_store()`,
  `promote_to_organizational()`, `MemoryGC`, `MemoryProvider`), never by
  hand-editing a memory file or vault note — hence `tools:` has no
  `Edit`/`Write`. Explicitly names what it does NOT do and which existing
  agent owns it instead (RTL/UVM edits → `implementation-agent`; simulation/
  build/regression → `build-agent`/`regression-agent`; root-causing →
  `debug-agent`; independent signoff → `review-agent`).
- `.claude/skills/CORE/memory-link/SKILL.md` — new skill (Phase 16). Confirmed
  via broad grep (`obsidian|wiki.?link|backlink|list_links|vault` across
  `.claude/skills`, zero hits) that no existing skill covered wiki-link
  graph/traversal before this. Documents `FileSystemMarkdownAdapter.list_links()`
  (forward_links/backlinks), `sections_patch` append pattern, and how
  `build_sections_from_memory_record()` auto-links a promotion to its source.
- `.claude/skills/CORE/obsidian-cli/SKILL.md` — new skill (Phase 16). Same
  grep confirmed zero existing coverage. Documents `detect_obsidian_cli()`'s
  real (not hardcoded) probe, why `ObsidianAdapter.status()` stays `PARTIAL`
  even if a binary is ever found, and `HybridMemoryProvider`'s per-call
  fallback design.
- `docs/MEMORY_ARCHITECTURE.md` (Phase 24) — the 3-store comparison
  (MemoryStore vs. Vault vs. Knowledge Center), the 5-tier routing table,
  the Engineering→Organizational 3-gate promotion boundary, Corner Case
  Library, confidence scoring, and config.
- `docs/OBSIDIAN_INTEGRATION.md` (Phase 24) — honest current status
  (`installed: false` on this machine, live-verified command included),
  why `status` stays `PARTIAL`, the real `FileSystemMarkdownAdapter` write
  path, Vault directory structure, opening the Vault in the real Obsidian
  app, config, and the intentionally-scoped YAML-frontmatter subset.
- `docs/MEMORY_AGENT.md` (Phase 24) — how to invoke the Memory Agent, its
  responsibilities/exclusions table, and a worked before/after debug-cycle
  example.
- `docs/MEMORY_SCHEMA.md` (Phase 24) — field-level reference for every
  record shape: MemoryStore record, the two real `verification` shapes,
  Corner Case Library record, Vault note frontmatter/body sections (with a
  full rendered example), and the router destination table.
- `docs/MEMORY_OPERATIONS.md` (Phase 24) — concrete, verified-working
  commands: `memory_cli.py` search/get/deprecate/corner-case-*, Python
  router/vault/GC snippets, `score_confidence()` examples, git-backed
  vault opt-in, and the existing `DV_MEMORY_SEARCH.ps1`/`DV_MEMORY_GET.ps1`
  wrappers. Every command in this file was actually executed against a
  real temp project during this workstream and its output checked before
  being written into the doc (see Verification below).

## Files modified

- `CLAUDE.md` — added `## Engineering Memory Policy (2026-09-03)` section
  (Before/During/After/Never), positioned directly after the Evidence
  Truth Rule and cross-referencing it plus the Core Operating Rules'
  "Memory is prior knowledge" rule rather than restating either. Every
  clause cites the real function/gate that enforces it
  (`route_memory()`'s `REJECT`, `promote_to_organizational()`'s 3 gates,
  `inference.score_confidence()`).
- `.claude/agents/ROSTER.md` — added entry 11 (`memory-agent`), renumbered
  12–20, updated the "Real Agents (19)" header to "(20)". `agent_count` in
  `dv_harness/stats_snapshot.py` is computed live from the directory
  listing, so no code change was needed there.
- `.claude/skills/CORE/working-memory/SKILL.md`
- `.claude/skills/CORE/job-memory/SKILL.md`
- `.claude/skills/CORE/project-memory/SKILL.md`
- `.claude/skills/CORE/engineering-memory/SKILL.md`
- `.claude/skills/CORE/organizational-memory/SKILL.md`
- `.claude/skills/CORE/memory-confidence-gate/SKILL.md`
- `.claude/skills/CORE/memory-consolidation/SKILL.md`
- `.claude/skills/CORE/memory-gc/SKILL.md`
- `.claude/skills/CORE/memory-retrieval/SKILL.md`
- `.claude/skills/EXPERT_FEEDBACK/knowledge-promotion-gate/SKILL.md`

  All 10 extended IN PLACE (original frontmatter/one-line policy statement
  untouched, per the task's explicit instruction not to create a new,
  parallel skill family) with a `## Mechanics (2026-09-03, real wiring)`
  section following the required Purpose/Inputs/Outputs/Preconditions/
  Execution Steps/Fallback/Evidence Requirements/Failure Conditions/
  Examples shape, each grounded in the real module/class/function it
  documents (verified against source, not invented): `MemoryStore`/
  `WorkingMemoryStore`/`JobMemoryStore`/`ProjectMemoryStore`/
  `OrganizationalMemoryStore`, `MemoryGC`, `MemoryRetriever`,
  `MemoryConsolidator`, `memory_router.route_and_store()`/
  `route_memory()`/`promote_to_organizational()`/
  `_verification_is_gate_validated()`/`_add_or_confirm_engineering()`,
  and `inference.score_confidence()`.

## Verification performed

- Read `dv_harness/memory.py`, `dv_harness/memory_router.py`,
  `dv_harness/memory_vault.py`, `dv_harness/inference.py`,
  `dv_harness/memory_cli.py`, `dv_harness/config.py`'s `memory` section,
  and 3 existing agent files (`debug-agent.md`, `regression-agent.md`,
  `review-agent.md`) before writing anything, so every doc/skill/agent
  claim traces to real code, not the spec's abstract description.
- Confirmed via grep across `.claude/skills` that `memory-link` and
  `obsidian-cli` had zero prior coverage under any name before creating
  them as new skills (per the task's explicit "double check" instruction).
- Executed and checked output for every code example that appears in
  `docs/MEMORY_OPERATIONS.md`:
  - `dv_harness.inference.score_confidence()` — both example calls,
    corrected one example's expected output after it did not match my
    first draft (independent_sources_count=2 draft actually scores HIGH,
    not MEDIUM — fixed the example inputs, re-ran, confirmed MEDIUM/HIGH
    outputs shown are exact real output).
  - `python -m dv_harness.memory_cli search/get/deprecate` — ran against
    a real temp project, confirmed real output shape.
  - `dv_harness.memory_vault.get_active_provider()` — `create`/`update`/
    `list_tags`/`list_links`/`search`/`delete`, all run against a real
    bootstrapped temp vault, output matches the doc.
  - `dv_harness.memory_router.route_and_store()` +
    `promote_to_organizational()` — ran with `cfg={}` (documented as the
    explicit local-only opt-out), confirmed the dedup/confirm mechanism
    (`confirmed_existing: True` on the 2nd write) and the promotion gate's
    `INSUFFICIENT_CONFIRMATION` reason/counts exactly as documented;
    corrected the promotion example's comment after the live run showed
    `confirmation_count: 0` on a freshly-created record, not the `>= 2`
    I'd initially assumed the example needed to narrate.
  - `detect_obsidian_cli()` — confirmed live `installed: false,
    status: "PARTIAL"` on this machine, matching Workstream 1's own
    discovery.

## Concern found during verification (not in this workstream's scope — flagging for coordination)

While verifying `route_and_store()` with a real (non-empty) `cfg` — the
normal, non-opt-out call shape shown in `MEMORY_OPERATIONS.md`'s primary
example — it raised `NameError: name '_write_back_knowledge_commit_sha'
is not defined` at `dv_harness/memory_router.py:167` (also referenced at
line 187). This function is called but never defined anywhere in the
codebase; it is also referenced only in comments (not called) in
`dv_harness/memory_vault.py`.

This is **not a regression I introduced or a file I touched** —
`dv_harness/memory_router.py`, `dv_harness/memory_vault.py`, and
`dv_harness/cli.py` all showed as already-modified against the `ceab932`
baseline (`git status`/`git diff --stat`, +106/+306/+219 lines
respectively) before I made any edit, and further changed on disk between
two of my own `Read` calls during this session — i.e. another workstream
(evidently building out Phase 9-14 git-integration, Phase 18 dedup, and a
new `dv-harness memory status/search/show/add/promote/graph/validate/
sync/doctor` CLI surface, per that diff's own comments) is actively
editing these exact files concurrently, in this same shared working tree,
uncommitted. The undefined-name crash is almost certainly a transient
mid-edit state of that other work, not a finished/shipped defect.

I did not fix it — it is squarely inside Workstream 1's/that concurrent
workstream's files, not this workstream's Phase 15/16/17/24 scope, and
editing a file another agent is actively mid-edit on risks corrupting
their work. `MEMORY_OPERATIONS.md`'s router/promotion example was verified
instead with `cfg={}` (the documented local-only path, which does not
reach the buggy line) and its output matches exactly what is documented.
The doc's primary example still shows `cfg=cfg` (the normal, intended
usage) since that is the correct real API once the concurrent work lands
cleanly — I did not want to document a workaround as if it were the
normal usage pattern. Recommend the orchestrator confirm this is resolved
before/when that concurrent workstream commits.

I also added one hedge sentence to `MEMORY_OPERATIONS.md` noting that a
native `dv-harness memory ...` CLI surface was under separate, active
development in this tree at the time of writing, without documenting its
exact flags (which I observed only as an in-progress, uncommitted diff,
not a stable, verified interface) — to avoid the doc going stale the
moment that other workstream commits, while still pointing readers at
`dv-harness memory --help` as the place to look.

## Commit scope note

This commit includes only the files listed above (CLAUDE.md, the 10
extended skills + 2 new skills, the new agent file, ROSTER.md, and the 5
new docs). It deliberately excludes `dv_harness/memory_router.py`,
`dv_harness/memory_vault.py`, `dv_harness/cli.py`, and the several
`.dv-harness/*` runtime-state files showing as modified/untracked in
`git status` — all of those belong to the concurrent workstream described
above, not to this one, and staging them here would risk committing
someone else's in-progress (and, as shown above, currently broken) work
under this workstream's name.
