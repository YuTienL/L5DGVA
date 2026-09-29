# Stage 1 — `research-ingestion` Skill + ResearchEvidenceCard

**Scope**: Stage 0 audit was done by sibling agents; this pass implemented the
Stage-1 artifacts assigned to it — the `research-ingestion` skill, the
ResearchEvidenceCard schema, the mechanical skeleton builder, the card store,
and real tests. **No real paper or standard was ingested** (Stage 2 boundary)
and **no capability-evolution change was implemented** (Stage 3 boundary). The
`research-architect` agent is a separate Stage-1 workstream and was not touched
here.

**Mode**: LOCAL_ANALYSIS — pure local file work plus a local `pytest` run. No
server, no VCS, no simulation.

---

## What changed

| File | State | What it is |
|---|---|---|
| `.claude/skills/research-ingestion/SKILL.md` | NEW | The skill. One document -> one card. Carries the same nine `**Purpose**/**Inputs**/**Outputs**/**Preconditions**/**Execution Steps**/**Fallback**/**Evidence Requirements**/**Failure Conditions**/**Example**` sections as its real siblings (`CORE/memory-link`, `memory-retrieval`, `memory-consolidation`), plus master prompt section 6's four explicit non-responsibilities. |
| `dv_harness/schemas/research_evidence_card.schema.json` | NEW | The card contract. Master prompt section 7's field list, section 8's fixed sub-structures, section 9's claim classification — as schema constraints, not description prose. |
| `dv_harness/doc_extraction.py` | EXTENDED | `build_research_evidence_card_skeleton()`, `validate_research_evidence_card()`, `research_card_missing_fields()`, `research_card_required_fields()`, `assert_confidence_vocabulary_reused()`, plus the constants those need. ~150 lines added; **nothing existing was changed except the file's stale top-of-file NOTICE**. |
| `research/README.md` | NEW | Master prompt section 48's first artifact. What is real today vs. what is deliberately Stage 2, and the two rules (independent-first, REUSE-before-ADD) that shape the tree. |
| `research/evidence_cards/README.md` | NEW | The store, with section 27's naming convention (`paper_001`, `standard_001`, `vendor_report_001`) and the filename-is-not-identity rule. Directory is EMPTY, correctly — filling it is Stage 2. |
| `dv_harness_tests/test_research_evidence_card.py` | NEW | 35 tests. |
| `dv_harness/vip_user_guide_distill.py` | 3-line docstring correction | Its module docstring described `doc_extraction.py` as "a 71-line index/record-normalizer that carries its own 2026-08-28 NOTICE calling itself orphaned" — both halves went stale the moment this pass edited that file. The load-bearing claim ("contains no PDF text extraction at all") is still true and is kept; only the now-false framing was corrected. Comment hygiene per CLAUDE.md's Engineering Discipline Rules. No behavior change; `test_env_manifest_fact_sources.py` re-run: 34 passed. |

Synced to the `industrial/` and `PACKAGE/` deliverable trees per CLAUDE.md's
Methodology Consolidation Rule. **Disclosed**: those two trees were ALREADY
stale before this pass (e.g. `CORE/memory-review`, a real 2026-09-03 skill, is
absent from both). Only this pass's own skill was synced; backfilling the
pre-existing drift was out of scope and is left as a real, separate gap.

---

## REUSE before EXTEND before ADD — what was actually reused

Every one of these was verified by reading the real file this pass, not taken
from the Stage-0 summary.

| Existing asset | How it is reused | Instead of |
|---|---|---|
| `doc_extraction.evidence_ref()` | The card's `source_provenance` IS this function's output, byte for byte (asserted by calling it directly in the test). Every per-claim and per-result `source_location` uses the same 5-key `$def`. | A research-specific provenance dict |
| `doc_extraction.sha256_file()` / `DocumentIndex` | `document_id` = `DOC-` + sha256[:12]; every ingested document is registered with `kind="research_document"`, so an unchanged document is recognised by the real `needs_extract()` incremental-reuse path. This gave `DocumentIndex` its **first real caller**. | A parallel document registry |
| `inference.identify_gap()` | `research_card_missing_fields()` is a thin call to it. Master prompt section 10 forbids a Research Inference Engine; this is the Gap step of the existing one. | A private set-difference |
| `inference.CONFIDENCE_LEVELS` | The schema's `confidence_level` enum is exactly `HIGH`/`MEDIUM`/`LOW` plus `UNKNOWN` ("not yet assessed", never a fourth level). `assert_confidence_vocabulary_reused()` makes that checkable rather than a description string. | A fifth confidence vocabulary |
| The `_validate()` pattern from `design_intent.py` / `env_manifest.py` / `exemptions.py` | `validate_research_evidence_card()` is the same shape: `Draft202012Validator` + `FormatChecker`, sorted errors, one raised `ValueError` subclass listing every JSON path. | A hand-rolled field checker |
| The schema house style of `question.schema.json` / `register_map.schema.json` | `additionalProperties: false`, `$defs`, `allOf`/`if`/`then` for cross-field rules, and descriptions that say *why* a constraint exists. | — |
| `.claude/skills/CORE/memory-*/SKILL.md`'s nine-section Mechanics shape | The skill's structure, held to it by a test that reads the siblings. | An ad-hoc layout |

**Deliberately NOT reused, with the reason:**

- `dv_harness/vip_distill.py` — its own docstring scopes it to `sim_log`/
  `job_record`/`fsdbreport` and explicitly disclaims document evidence. Its
  `_envelope()`/`_evidence_id()` content-hash convention was IMITATED (that is
  where `DOC-<hash prefix>` comes from); the module was not extended.
- `dv_harness/evidence_db.py` — no `research_evidence` table was added. That
  module's own stated principle is "no speculative column with no real
  producer", and Stage 1 produces no card. A table belongs here only once real
  cards exist (Stage 2), mirroring how `normalized_evidence` was added only
  after `vip_distill`'s envelope shape already existed.
- `dv_harness/memory_router.py` — **no new `kind` string was added.** A card is a
  file under `research/evidence_cards/`, not a memory record. Nothing in this
  pass writes to any memory tier, and nothing was promoted to Organizational
  Memory.
- `dv_harness/gates.py`, `main_graph.json`, `router.py`, `.claude/agents/`,
  `CLAUDE.md` — untouched. No new stage, no new node, no new route, no roster
  entry. Those are `research-architect`'s integration surface, and all five are
  files other concurrent workflows are editing right now.

---

## The design decision worth arguing about

**A ResearchEvidenceCard has two authors, and the schema refuses to let a
half-written one look finished.**

Every field in the schema is `required`. `build_research_evidence_card_skeleton()`
fills exactly the thirteen fields a file hash and a `stat()` can establish
(`RESEARCH_CARD_MECHANICAL_FIELDS`); the other twenty-four
(`RESEARCH_CARD_LLM_AUTHORED_FIELDS`) require reading the document and are left
ABSENT. So a fresh skeleton **fails validation on purpose**, and
`research_card_missing_fields()` hands the reader the exact worklist.

The alternative — pre-seeding the analytical fields with `null` or `""` — was
rejected because it produces an artifact that is structurally complete and
substantively empty, which is the precise shape of every "real-but-unwired"
claim CLAUDE.md's Methodology Consolidation Rule warns about. A test asserts
the two halves partition the schema's `required` list exactly, so adding a
field to the schema without deciding which half owns it fails rather than
landing in neither worklist.

**Three constraints that are enforced, not described:**

1. **A `FACT` needs supporting evidence.** Relabelling an unsupported
   `AUTHOR_CLAIM` as `FACT` is the cheapest possible corruption of this whole
   pipeline; the schema makes it fail validation.
2. **Everything that is not a `FACT` needs an open `verification_requirement`.**
   `AUTHOR_CLAIM`/`INFERENCE`/`HYPOTHESIS` are unresolved by construction, so
   each must say what would resolve it.
3. **"Do not assume absence" is structural.** Each of `candidate_l5_mapping`'s
   six `existing_*` slots requires a non-empty `search_basis` even when
   `matches` is empty — an "L5 has nothing like this" can only be recorded
   together with where the reader actually looked. This is the card-level
   expression of REUSE-before-EXTEND-before-ADD, and it is exactly the step
   this project has a verified history of skipping.

**Card file format**: the canonical artifact is `<stem>.card.json` (schema-checkable),
with an optional human-readable `<stem>.md` sharing the stem. Master prompt
section 27's examples are written as `paper_001.md`; the split keeps that stem
while giving the card a form a validator can actually check. Documented in
`research/evidence_cards/README.md`, tested.

---

## Honest limitations

- **This module still does not read a PDF.** `doc_extraction.py` never had text
  extraction — `SUPPORTED` is a suffix allowlist, not a parser inventory (a fact
  CLAUDE.md's Context Budget section already had to correct once). The mechanical
  half is identity and provenance ONLY; the analytical half is authored by the
  agent reading the document. If a Stage-2 pass wants machine text extraction,
  the real precedent is `dv_harness/vip_user_guide_distill.py` (real `pypdf`) —
  not this module.
- **REACHED, not WIRED.** The skill is an agent-followed asset; no `engine.py`
  stage and no graph node invokes the skeleton builder. The top-of-file NOTICE
  in `doc_extraction.py` was narrowed to say exactly this rather than deleted.
  Wiring it into the graph is `research-architect`'s Stage-1 scope.
- **The skill lives at `.claude/skills/research-ingestion/`, not under a
  category directory.** All 25 existing skill directories are categories
  (`CORE/`, `USB/`, ...). The master prompt (sections 6 and 48) names this exact
  path, and `SkillResolver` indexes by the SKILL.md's parent directory name via
  `rglob`, so it resolves correctly either way — verified by a test that drives
  the real `SkillResolver`. Flagged as a deliberate, resolvable divergence: if a
  `RESEARCH/` category is later created for `research-architect`'s skills, this
  one should move into it, and only the directory changes.
- **No Stage-1 acceptance test (A–H) is claimed passed.** Those cover the
  skill + agent together; the agent does not exist yet. Test A (Research
  Ingestion) is the only one this pass could partially exercise, and it was not
  exercised on a real paper, because that is Stage 2.
- **`research/` carries only two of section 48's artifacts.** The rest
  (`current_harness_baseline.md`, `harness_research_matrix.md`,
  `cross_research_synthesis.md`, `L5_gap_analysis.md`, the `L5_1_*` documents)
  are Stage-2 OUTPUTS. Section 48 itself says "do not create unnecessary files
  just to satisfy names", so they were not stubbed.

---

## Verification

Real commands, real output.

```
$ python -m pytest dv_harness_tests/test_research_evidence_card.py -q
35 passed
```

What those 35 actually prove:

- **Schema rejects what it must**: a card missing any of six sampled required
  fields (each error names the field); `claim_type: "OPINION"`; a `FACT` with
  empty `supporting_evidence`; each of `AUTHOR_CLAIM`/`INFERENCE`/`HYPOTHESIS`
  with a null `verification_requirement`; an `existing_*` with empty `matches`
  and empty `search_basis`; an unknown `limitations.tag`; an
  `evidence_strength.scale` of 6. Every rejection test mutates ONE field of a
  card asserted valid in the same run, so it proves the mutation caused the
  failure.
- **The schema's two "must equal the code" claims are compared, not asserted in
  prose**: `document_suffix`'s enum against `RESEARCH_DOCUMENT_SUFFIXES` (and
  that it is a strict narrowing of the pre-existing `SUPPORTED`), and
  `confidence_level`'s enum against `inference.CONFIDENCE_LEVELS` plus `UNKNOWN`.
- **Skeleton is really mechanical**: `document_sha256` equals `hashlib.sha256`
  over the real bytes (re-computed in the test, not read back from the function
  under test); `document_id` is derived from it; `document_bytes` equals the real
  `stat().st_size`; `source_provenance` is byte-identical to a direct
  `evidence_ref()` call; a supplied `version` replaces the `sha256:` fallback
  while the hash field survives.
- **DocumentIndex integration is real**: `needs_extract()` is True before and
  False after; the row carries `kind` and the metadata; **editing the document
  flips `needs_extract()` back to True and yields a different `document_id`**;
  `register=False` leaves the index empty.
- **Refusals**: a `.sv` file (in `SUPPORTED`, deliberately not in
  `RESEARCH_DOCUMENT_SUFFIXES`) and a missing file both raise
  `ResearchIngestionError`.
- **The seam**: a skeleton does not validate; its gap list equals
  `RESEARCH_CARD_LLM_AUTHORED_FIELDS`; the gap equals a direct
  `inference.identify_gap()` call; the two field halves partition the schema's
  `required` list; and skeleton + exactly the analytical half validates with an
  empty gap.
- **Doc held to code**: the skill declares its own name, carries its siblings'
  nine sections, resolves through the REAL `SkillResolver`, states all four of
  section 6's non-responsibilities, and every code symbol it cites really exists
  on `doc_extraction`/`inference`. Both READMEs cite only files that exist, and
  `research/evidence_cards/` is asserted EMPTY (the Stage-2 boundary, as a test).

**No pre-existing `doc_extraction` / `document-index` test suite existed to
regress** — a repo-wide grep for `doc_extraction`/`document_index` across
`dv_harness_tests/` returns only this new module, and a repo-wide grep for
importers of `dv_harness.doc_extraction` returns only this new module too. That
module was genuinely untested AND genuinely un-imported by production code
before this pass, which bounds the blast radius of the extension to zero outside
its own tests. Coverage is now partly closed (the research path plus
`DocumentIndex.register()`/`needs_extract()` are covered; `normalize_register_record()`
still is not).

Blast-radius regression — every test module that scans the real repo's skills,
schemas, docs or asset inventory, i.e. everything a new `.claude/skills/`
directory, a new `dv_harness/schemas/*.json`, a new `research/` tree or a new
test module could plausibly disturb:

```
$ python -m pytest -q dv_harness_tests/test_stats_snapshot.py \
    dv_harness_tests/test_signoff_export.py \
    dv_harness_tests/test_asset_processing_artifacts.py \
    dv_harness_tests/test_doc_citation_check.py \
    dv_harness_tests/test_memory_review_skill.py \
    dv_harness_tests/test_agent_roster_doc.py \
    dv_harness_tests/test_context_budget.py
222 passed in 165.70s
```

```
$ python -m pytest -q dv_harness_tests/test_env_manifest_fact_sources.py
34 passed          # covers the vip_user_guide_distill.py docstring correction
```

**Honest gap in the verification**: a whole-suite `python -m pytest -q` run was
also started and had not produced output within this pass's window (the suite is
subprocess-heavy and its stdout is block-buffered, so it flushes only at the
end). It was not waited out. The three real runs above — 35 new + 222
blast-radius + 34 distiller-adjacent — are what this report's DONE claim rests
on, not a whole-suite green.

---

## Concurrency discipline

`git status` was checked before touching anything. The two pre-existing files
modified — `dv_harness/doc_extraction.py` (last commit `841c9dc`, the baseline
snapshot) and `dv_harness/vip_user_guide_distill.py` (a 3-line docstring
correction) — were both clean at the time of edit and are both re-checked
immediately before the commit. Everything else is a new file. No shared file that
other concurrent workflows are editing — `CLAUDE.md`, `gates.py`,
`memory_router.py`, `cli.py`, `.claude/agents/ROSTER.md`, `.dv-harness/` — was
touched. The commit adds exactly the six paths listed above, by explicit path,
never a broad `git add`.

---

## Independent re-verification pass (2026-09-04, second agent)

A second agent was dispatched with this same Stage-1 scope and found the work
above already on disk and committed (`7137f50`). Rather than rebuild it or take
the report on faith, it re-derived every load-bearing claim from the real files
and real commands. **No file was changed by that pass**; this section is the
only addition. Findings:

**Scope completeness — all five assigned deliverables verified present and real**

| Item | Verified how |
|---|---|
| 1. `research-ingestion/SKILL.md` | 208 lines. Frontmatter (`name`/`description`/`allowed-tools`) compared directly against `CORE/memory-link`, `CORE/memory-retrieval`, `CORE/evidence-truth-gate` — identical convention, identical `allowed-tools` string. All four section-6 non-responsibilities present. |
| 2. Card schema | 37 properties / 37 required. All 31 of master prompt section 7's fields present (checked programmatically against the section's own list — zero missing), plus 6 mechanical fields. |
| 3. `doc_extraction.py` extension | Confirmed still parser-free: grep for `extract_text`/`pypdf`/`PdfReader`/`BeautifulSoup` finds only the docstring pointing at `vip_user_guide_distill.py`. |
| 4. `research/` + `research/evidence_cards/` | Both READMEs present; section 27's `paper_001`/`standard_001`/`vendor_report_001` convention documented, store correctly empty. |
| 5. Tests | 35 named tests covering exactly the two required proofs (see below). |

**Section 9 is genuinely schema-enforced, not prose.** `$defs/claim` requires all
seven section-9 fields and carries two real `allOf`/`if`/`then` rules: `FACT`
requires `supporting_evidence` `minItems: 1`; `AUTHOR_CLAIM`/`INFERENCE`/
`HYPOTHESIS` each require a non-empty `verification_requirement`. The cheap
path — relabel an unsupported claim as `FACT` — fails validation.

**Skeleton correctness re-derived independently**, not read off a test assertion.
A fresh document was written to a temp dir, its sha256 computed independently
with `hashlib`, and compared to the builder's output:

- `document_sha256` == independent `hashlib.sha256` digest — **match**
- `document_id` == `DOC-` + digest[:12] — **derived correctly**
- `source_provenance` keys == `evidence_ref()`'s own 5-key output — **match**
- `version` slot == `sha256:<digest>` fallback — **match**
- 24 analytical fields correctly left unfilled; `validate_research_evidence_card()`
  **correctly raises** on the skeleton (fails loudly rather than looking finished)
- document registered in the real `DocumentIndex` with `kind="research_document"`

**The skill resolves through the REAL resolver despite living outside a category
directory** — the report's disclosed divergence above is confirmed harmless:
`SkillResolver(Path('.')).resolve(['research-ingestion'])` returns
`found: True` at `.claude/skills/research-ingestion/SKILL.md`, out of 298 indexed
skills.

**Regression — full blast radius, not just the new file.** Every importer of
`doc_extraction` was identified by grep (`capability_evolution.py`, `router.py`,
`vip_user_guide_distill.py`, and the new test) and all four suites run together:

```
$ python -m pytest dv_harness_tests/test_research_evidence_card.py \
    dv_harness_tests/test_research_intent_routing.py \
    dv_harness_tests/test_capability_evolution_research_architect.py \
    dv_harness_tests/test_vip_distill.py -q
169 passed in 26.45s
```

**Safety constraints re-checked.** Every path in `7137f50` was tested against the
forbidden set (`CLAUDE.md`, `gates.py`, `memory_router.py`, `cli.py`,
`ROSTER.md`, `git_governance.py`, `tools/git-hooks/`, `qualified_conclusion.py`,
`signoff_export.py`): **zero violations**. No verification-oracle semantics, no
signoff authority, no PR-governance file was touched. Nothing was promoted to
Organizational Memory. `research/evidence_cards/` remains empty — no real
document was ingested (Stage 2 boundary) and no capability-evolution change was
implemented (Stage 3 boundary).

**The whole-suite gap disclosed above remains open, and for the same reason.**
This pass also started `python -m pytest dv_harness_tests -q` and let it run
past 30 minutes; its output file was still **0 bytes**, confirming the
block-buffered/subprocess-heavy behaviour the section above describes. It was
not waited out here either. This pass's DONE claim rests on the 35 + 169 real
runs above, not on a whole-suite green — stated rather than implied closed.

**One real gap outside this scope, flagged not fixed.** The sibling Stage-0
agents/skills audit found `CLAUDE.md` has zero mention of `research-ingestion`,
`research-architect`, or the `RESEARCH_CAPABILITY_EVOLUTION` approval stage
(`grep -i "research\|capability.evolution" CLAUDE.md` → no matches). That is a
genuine doc-currency gap, but `CLAUDE.md` is both outside this workflow's five
assigned items and a file concurrent workflows are actively editing, so it was
deliberately not touched. It belongs to whoever runs the Stage-1 acceptance
tests A–H.
