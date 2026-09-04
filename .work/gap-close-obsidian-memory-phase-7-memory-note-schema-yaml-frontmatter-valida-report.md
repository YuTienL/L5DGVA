# Gap-close: Phase 7 — Memory Note Schema (YAML frontmatter + validation)

**Status: DONE**
**Commit: `9d1ab74` — `memory(note-schema): validate the note body's 11-section shape on read, and report the spec's non-gating fields`**
**Tests: 69 passed (`test_memory_vault.py` + `test_memory_doctor.py`, 7 new), 203 passed across the full memory suite (11 files).**

---

## 1. READY sub-items — re-confirmed, not modified

Each cited line re-read this pass at its current line number (they moved by my
own edits; the pre-edit numbers in the audit were correct).

| Audit claim | Re-confirmed at |
|---|---|
| `MEMORY_NOTE_REQUIRED_FIELDS` = 7 identity/trust fields | `dv_harness/memory_vault.py:128` (was `:122`) |
| `MEMORY_NOTE_OPTIONAL_FIELDS` = 11 enrichment fields | `dv_harness/memory_vault.py:146-149` |
| `MEMORY_NOTE_BODY_SECTIONS` = the spec's 11 sections, same order | `dv_harness/memory_vault.py:179-182` |
| `validate_note_frontmatter()` is a real pure function | `dv_harness/memory_vault.py:204` |
| Called from `create()` | `dv_harness/memory_vault.py:900-901` |
| Called from `update()` | `dv_harness/memory_vault.py:949-950` |
| `schema_status` baked into the note's own frontmatter, note still written | confirmed live, see §4 |
| `protocol` required again at the CLI (`argparse required=True`) | `dv_harness/cli.py:918` |
| Existing unit test | `dv_harness_tests/test_memory_vault.py:145` |

No change made to any of these. Gating semantics are byte-for-byte unchanged:
`schema_status` still flips on exactly the same seven fields, and the 9 real
vault notes still report exactly the PARTIAL verdicts they did before (§4).

## 2. PARTIAL sub-item "Body-section shape validation" — CLOSED for real

The audit's finding was accurate: `MEMORY_NOTE_BODY_SECTIONS` was referenced
only at render time and never at any validation call site, so a note
hand-edited in the Obsidian GUI that deletes a `## Fix` header would be flagged
by nothing.

**Built** — `dv_harness/memory_vault.py:381-411`, `validate_note_body_sections(body)`:

- Reuses the existing `_body_to_sections()` parser (no second body parser).
- Returns `{"body_status", "missing_sections", "unexpected_sections", "out_of_order"}`.
- `PARTIAL` when a required header is **missing** OR the required headers appear
  **out of canonical order** — order is part of the contract because the sections
  are a reasoning sequence (Symptom → Hypothesis → Root Cause → Fix →
  Verification), not an unordered bag.
- An **extra** `##` header a human added is listed in `unexpected_sections` and
  never downgrades the status: adding a section is not a violation, deleting or
  reshuffling one is. This also makes the check robust against a `## `-prefixed
  line inside a section's own content.

**Wired** — `dv_harness/memory_doctor.py:153-185`, `check_schema()` now calls
`mv.validate_note()` (both halves) instead of `validate_note_frontmatter()`
alone. A body-shape failure lands in the same `partial` list with
`missing_sections` and `body_out_of_order` named, and reaches
`dv-harness memory doctor` and `dv-harness memory validate` (both already dump
the raw report JSON — no renderer needed).

**Not** re-validated on write: `render_note_markdown()` builds the shape, so
re-checking its own output would be dead work. The check is exactly where the
gap was — on read.

## 3. PARTIAL sub-item "Field-list scope vs. spec wording" — CLOSED as reporting, gating deliberately unchanged

The audit correctly flagged this as a human-visible scope decision. I did **not**
change gating: promoting `subsystem`/`category`/`failure`/`project`/`rtl_sha`/
`tb_sha`/`vip_vendor`/`vip_version`/`simulator` to gating would flip all 9 real
notes and change promotion behaviour, and the narrower set is a documented,
defensible design (`memory_vault.py:121-127`).

What was genuinely closeable is that those nine spec-listed fields were **not
checked at all** — the scope difference was invisible in every real report.
Now:

- `MEMORY_NOTE_SPEC_RECOMMENDED_FIELDS` (`memory_vault.py:153-169`) names them,
  derived from `MEMORY_NOTE_OPTIONAL_FIELDS` rather than re-typed, with the
  required-vs-optional rationale in its comment.
- `validate_note_frontmatter()` returns `missing_recommended` — **report-only**,
  asserted by test to never affect `schema_status`.
- `memory_doctor.check_schema()` surfaces it in its own
  `notes_missing_recommended` list, spanning complete and partial notes alike,
  and it never contributes to `status`.
- `tags` (router-derived) and `knowledge_commit_sha` (only exists after a real
  vault commit) are excluded on purpose so a correctly-written note reports
  nothing.

`validate_note(frontmatter, body)` (`memory_vault.py:416-428`) is the single
whole-note entry point: `note_status` is COMPLETE only when both halves are,
with `schema_status`/`body_status` kept separate because they have different
repairs.

**Remaining human decision, unchanged and still disclosed**: whether the
narrower gating set is what the spec author intended. It is now *visible* in
every doctor/validate run rather than silent; making it *gating* is a
one-constant change a human should approve, not an audit-pass side effect.

## 4. Live proof against real production data (read-only)

`memory_doctor.run_validate()` over the real `.dv-harness/vault`:

```
status PARTIAL complete 0 partial 9
 PARTIAL MEM-0953BEC4D8 missing_required= ['protocol'] missing_sections= [] out_of_order= False
 ... (all 9 identical shape)
missing_recommended notes: 9
   MEM-0953BEC4D8 ['project', 'rtl_sha', 'tb_sha', 'vip_vendor', 'vip_version', 'simulator']
```

Three things this proves: the construction guarantee holds live (all 9 real
notes have `missing_sections: []`); the pre-existing `protocol: null` data gap
is unchanged (the same 9 PARTIAL verdicts the audit reported, so gating did not
move); and the new report names real absent enrichment fields —
`subsystem`/`category`/`failure` are correctly *not* listed, because those 9
notes do carry them.

## 5. Tests written (all real behaviour, none import-only)

`dv_harness_tests/test_memory_vault.py`:
- `test_missing_recommended_reports_spec_fields_without_gating_schema_status` — the non-gating contract, plus the `tags`/`knowledge_commit_sha` exclusions.
- `test_validate_note_body_sections_accepts_a_rendered_note`
- `test_validate_note_body_sections_flags_a_hand_deleted_section` — renders a real note, deletes `## Fix` from the rendered text, asserts `missing_sections == ["Fix"]`.
- `test_validate_note_body_sections_flags_reordered_sections` — swaps Root Cause/Fix, asserts `out_of_order` with `missing_sections == []`.
- `test_validate_note_body_sections_tolerates_an_extra_human_section`
- `test_validate_note_body_sections_flags_a_frontmatter_only_note`
- `test_validate_note_requires_both_halves_complete` — all three failure combinations.

`dv_harness_tests/test_memory_doctor.py`:
- `test_doctor_flags_a_note_whose_body_section_was_hand_deleted` — end-to-end: the **real** `FileSystemMarkdownAdapter` writes a COMPLETE note into a real temp vault, the test edits that file **on disk** (simulating the Obsidian GUI edit, the only way this state is reachable), and asserts `run_doctor()` reports it PARTIAL with `missing_sections == ["Fix"]`, `missing_required == []`, and `overall != BLOCKED`. This is the exact scenario the audit named as uncatchable before.
- `test_doctor_reports_missing_recommended_fields_without_marking_the_note_partial` — a real note with every gating field and no enrichment field: `status: READY`, `partial: []`, and the nine absent fields still named.

Existing `test_validate_note_frontmatter_flags_missing_required_fields_as_partial`
was loosened from exact-dict equality to per-key assertions (the return dict
gained `missing_recommended`); its two original assertions are intact.

## 6. Files touched

- `dv_harness/memory_vault.py` — new constant + 2 new functions, extended validator, module docstring's Phase 7 entry refreshed.
- `dv_harness/memory_doctor.py` — `check_schema()` rewired, module docstring line refreshed (it named `validate_note_frontmatter()`, now stale).
- `dv_harness/cli.py` — 2 help strings only (`memory validate`/`memory doctor` said "schema", now say what schema covers). No behaviour change; staged as a hand-scoped 4-line diff, verified before commit.
- `dv_harness_tests/test_memory_vault.py`, `dv_harness_tests/test_memory_doctor.py` — 9 tests added/adjusted.
- `docs/MEMORY_SCHEMA.md` — documents the new constant, the read-side body check, and `validate_note()`. Also corrected a stale line: the optional-field list was missing `knowledge_commit_sha`.
- `.claude/agents/memory-agent.md` — its "Validate" bullet named only the frontmatter validator; now names both halves.

Nothing else was staged. `CLAUDE.md`, `config.py`, `engine.py`, `policy.py`
carry other concurrent agents' uncommitted work and were deliberately left
untouched and unstaged (`git diff --cached --stat` verified before commit).

## 7. Stale comment / dead code removed

- `memory_doctor.py`'s module docstring claimed schema validity was checked by `validate_note_frontmatter()` — no longer true after this change; corrected rather than left behind.
- `memory_vault.py`'s Phase 7 docstring entry did not mention the body-shape half at all; rewritten to state what is guaranteed on write vs. re-checked on read.
- `.claude/agents/memory-agent.md`'s Validate bullet, same reason.
- `docs/MEMORY_SCHEMA.md`'s `MEMORY_NOTE_OPTIONAL_FIELDS` list was missing `knowledge_commit_sha` (added by a later phase and never back-filled into the doc).
- No dead code introduced; `check_schema()`'s discarded `complete` list was replaced by a plain counter, since only its length was ever used.
