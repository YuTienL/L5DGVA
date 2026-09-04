---
name: research-ingestion
description: One external technical document -> one independent ResearchEvidenceCard. Mechanical identity/provenance from doc_extraction.py, analytical fields from actually reading the document, every claim classified FACT/AUTHOR_CLAIM/INFERENCE/HYPOTHESIS. Never decides architecture, never synthesizes across documents, never touches production code.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# research-ingestion

External Technical Document -> Structured Research Evidence. ONE document ->
ONE independent ResearchEvidenceCard.

核心原則：research is not implementation, and an author's claim is not a fact.

## Responsibility boundary

This skill is responsible for reading one external technical document and
turning it into one card. It is explicitly NOT responsible for, and must
refuse to do, any of the following (master prompt sections 6 / 2.4 / 27):

- **deciding final L5 architecture** — `candidate_l5_mapping.possible_enhancement`
  records a candidate for `research-architect` to weigh; it is never a decision
  and never an instruction to implement.
- **cross-paper synthesis** — comparing two documents, declaring convergence,
  resolving a contradiction between them. That is `research-architect`'s job
  (master prompt section 28) and doing it here would violate section 27's
  no-cross-document-contamination rule: first-pass extraction must be
  independent, or "three independent papers agree" stops meaning anything.
- **modifying production code** — nothing under `dv_harness/`,
  `tools/verification_flow/`, `.dv-harness/`, or any generated environment.
  A card is written under `research/evidence_cards/` and nowhere else.
- **declaring verification PASS** — this skill produces no verdict about any
  DUT, testbench, gate, or stage. It has no verification authority of any kind.

## Mechanics (2026-09-04)

Every function named below is real and tested
(`dv_harness_tests/test_research_evidence_card.py`). The siblings in
`.claude/skills/CORE/memory-*` head this section "real wiring"; this one does
not, because no `engine.py` stage and no graph node invokes any of it — an agent
following this skill is the only caller today. REACHED, not WIRED.


**Purpose**: produce the single, schema-checked, independently-readable unit of
research evidence this harness reasons over. Everything downstream — the
research-to-harness matrix, cross-document synthesis, any eventual capability
proposal — reads cards, never raw documents, so a card is the point at which an
external document stops being prose and starts being evidence with provenance.

**Inputs**:
- One document file. Supported suffixes are
  `dv_harness.doc_extraction.RESEARCH_DOCUMENT_SUFFIXES` —
  `.pdf` `.docx` `.html` `.htm` `.txt` `.md`. Deliberately narrower than that
  module's older `SUPPORTED` set: `.sv`/`.v`/`.vh`/`.svh`/`.csv`/`.xls*` are
  project design/data inputs, and one arriving here means the wrong path was
  taken. Supported source types (master prompt section 6): academic / arXiv /
  conference papers, standards, Accellera documents, vendor technical reports
  and application notes, architecture reports, engineering articles, benchmark
  reports, internal engineering and verification reports, technical design
  documents.
- The project root, for the `DocumentIndex` this skill registers into.
- Optionally the document's own version string and `document_type`; both have
  honest defaults (`sha256:<digest>` and `UNCLASSIFIED`) when not supplied.

**Outputs**: one ResearchEvidenceCard, valid against
`dv_harness/schemas/research_evidence_card.schema.json`, written to
`research/evidence_cards/<stem>.card.json` with the section-27 stem convention
(`paper_001`, `standard_001`, `vendor_report_001`, ...). An optional
human-readable `research/evidence_cards/<stem>.md` may accompany it, sharing the
stem; the `.card.json` is the canonical artifact — it is the one the schema
checks. See `research/evidence_cards/README.md` for the naming rules and
`research/README.md` for where cards sit in the wider Stage 0-3 flow.

**Preconditions**:
- The document is on disk and readable. This skill never fetches, and never
  writes a card about a document it did not read.
- Stage boundary: `research-ingestion` may run whenever a document is supplied.
  Filling a card does NOT authorize Stage 3 (implementing anything), which
  requires separate explicit human approval.

**Execution Steps**:
1. Build the mechanical half, without reading the document:
   `doc_extraction.build_research_evidence_card_skeleton(path, project_root)`.
   This computes the sha256, derives `document_id` (`DOC-<12 hex>`), stats the
   file, fills `source_provenance` via the existing
   `doc_extraction.evidence_ref()` shape, and registers the document in the
   real `DocumentIndex`. Do not hand-write any of these fields — a
   hand-typed hash is a fabricated identity.
2. Ask what is still owed:
   `doc_extraction.research_card_missing_fields(card)` returns the worklist, in
   schema order, via the harness's existing
   `dv_harness.inference.identify_gap()` Gap step (master prompt section 10
   forbids a parallel research inference engine). On a fresh skeleton this is
   exactly `RESEARCH_CARD_LLM_AUTHORED_FIELDS`.
3. Read the document and fill those fields. Per master prompt section 8:
   `problem_statement`; `core_method` in mechanism terms, never restated
   marketing; `architecture_pattern` as its six fixed stages
   (INPUT -> TRANSFORMATION -> DECISION -> TOOL -> EVIDENCE -> NEXT ACTION);
   `feedback_loop` as its seven (hypothesis -> evidence_needed -> tool_action ->
   observation -> confidence_update -> gap -> next_best_action); `ai_role` vs
   `deterministic_tool_role` split explicitly, because a document where the LLM
   itself is the oracle is exactly the finding that must not be lost;
   `quantitative_results` exactly as printed, never normalised, never invented;
   `limitations` tagged from the schema's closed twelve-tag list.
4. Classify every important claim (master prompt section 9) into `claim_set`.
   Exactly one of `FACT` / `AUTHOR_CLAIM` / `INFERENCE` / `HYPOTHESIS`, each
   with `claim_text`, `source_location` (a real page/section), `supporting_evidence`,
   `confidence`, `uncertainty`, `verification_requirement`. Never silently
   convert an AUTHOR_CLAIM into a FACT — the schema enforces the two halves of
   that rule (a FACT needs supporting evidence; everything else needs an open
   verification requirement), so the shortcut fails validation rather than
   passing review.
5. Fill `candidate_l5_mapping` by REALLY SEARCHING this repo, not by recall.
   "Do not assume absence" is enforced structurally: each of the six
   `existing_*` slots requires a `search_basis` even when `matches` is empty.
   Search `dv_harness/` (`inference.py`, `change_impact.py`, `memory_router.py`,
   `blackboard.py`, `gates.py`, `evidence_db.py`), `.claude/agents/ROSTER.md`,
   `.claude/skills/**/SKILL.md`, and `.dv-harness/graph/main_graph.json` before
   writing an empty `matches`. This is the card-level expression of
   REUSE-before-EXTEND-before-ADD (master prompt sections 2.2 / 14).
6. Validate before filing:
   `doc_extraction.validate_research_evidence_card(card)`. Only a card that
   validates is written under `research/evidence_cards/`.

**Fallback**:
- A document this skill cannot read at all (scanned image PDF, encrypted, a
  paywalled abstract only) produces NO card. Write nothing rather than a card
  whose analytical fields were inferred from a title — a fabricated card is
  worse than a missing one, because a missing document is visibly missing.
- A document with no quantitative results is a normal, valid card: empty
  `quantitative_results`, `evidence_strength.scale` 1, and a rationale saying
  so. Do not pad the array to make the card look stronger.
- A genuinely novel mechanism that fits none of section 8's example names goes
  into `key_mechanisms` under its own name — that list is illustrative, not a
  closed enum — while `limitations.tag` and `claim_type` ARE closed, and a case
  that fits none of their values is a real signal to escalate, not to force.

**Evidence Requirements**: every analytical field must come from the document
in front of you. Every `claim_set` entry and every `quantitative_results` entry
carries its own `source_location` naming a real page/section. `document_sha256`
and `document_id` come from `sha256_file()` on the real bytes and from nowhere
else. Per CLAUDE.md's Evidence Truth Rule, nothing in a card is verification
evidence about this project's DUT: a card records what an external document
demonstrated about ITS design, and that never substitutes for current RTL /
sim.log / waveform evidence here.

**Failure Conditions**:
- Silently promoting AUTHOR_CLAIM to FACT — the single most damaging failure of
  this skill, and the reason `claim_type` exists.
- Filling `candidate_l5_mapping` from memory of this repo rather than a real
  search, then recording an empty `matches`. This is the exact
  build-a-parallel-mechanism failure mode the master prompt's section 2.2 exists
  to prevent, and it starts here.
- Reading a second document before this card is finished — cross-document
  contamination, forbidden by section 27.
- Writing a card that has not passed `validate_research_evidence_card()`.
- Any edit outside `research/`.

**Example**:
```python
import json
from pathlib import Path
from dv_harness import doc_extraction as dx

root = Path(".")
card = dx.build_research_evidence_card_skeleton(
    root / "research" / "sources" / "semantic_change_impact.pdf", root,
    title="Semantic Change Impact Analysis for RTL Verification",
    source="arXiv:2501.00000", document_type="ARXIV_PAPER")

dx.research_card_missing_fields(card)
# ['authors', 'date', 'verification_domain', 'problem_statement', ...]
# -> read the document, fill exactly those, then:

dx.validate_research_evidence_card(card)          # raises until complete
Path("research/evidence_cards/paper_001.card.json").write_text(
    json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
```

One filled `claim_set` entry, showing the classification discipline:
```json
{
  "claim_text": "Semantic change impact reduced the selected regression by 62% with no missed failures.",
  "claim_type": "AUTHOR_CLAIM",
  "source_location": {"document": "semantic_change_impact.pdf", "version": "sha256:9f2c...",
                      "page": "7", "section": "5.2 Results", "source_location": "Table 3"},
  "supporting_evidence": ["Table 3: 62% selection reduction over 4 designs"],
  "confidence": "MEDIUM",
  "uncertainty": "No independent reproduction; 'no missed failures' is measured only on the authors' own 4-design set.",
  "verification_requirement": "Re-run the selection against this harness's own change_impact.select_regression() TARGETED/DEPENDENCY/SAFETY output on a real regression with known escapes."
}
```
It stays `AUTHOR_CLAIM` even though Table 3 exists: the table is the authors'
own measurement of their own method, which is what `supporting_evidence` on an
AUTHOR_CLAIM records. Promoting it to `FACT` would need evidence independent of
the authors — and the schema would still let it through, so this one is on the
reader.
