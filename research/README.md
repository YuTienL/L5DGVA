# research/ — external research evidence for L5 capability evolution

This tree holds what this harness has read from OUTSIDE itself: papers,
standards, vendor reports, internal engineering reports — turned into
structured, provenance-carrying evidence, and the reasoning built on top of it.

It exists because of one distinction, and everything here is arranged around it:

> **Nothing in this tree is verification evidence about this project's DUT.**
> A card records what an external document demonstrated about ITS design. Per
> CLAUDE.md's Evidence Truth Rule, that never substitutes for current RTL /
> `sim.log` / waveform evidence here, and it never authorizes a change to
> production code on its own.

## What is real today (2026-09-04)

Installed, tested, usable:

| Artifact | State |
|---|---|
| `.claude/skills/research-ingestion/SKILL.md` | REAL — one document -> one ResearchEvidenceCard |
| `dv_harness/schemas/research_evidence_card.schema.json` | REAL — the card contract, every field required |
| `dv_harness/doc_extraction.py` `build_research_evidence_card_skeleton()` | REAL — mechanical identity/provenance half |
| `research/evidence_cards/` | REAL directory + naming convention; **contains no card yet** |
| `dv_harness_tests/test_research_evidence_card.py` | REAL — schema rejection cases + skeleton correctness |

Not built yet, and deliberately so — the master prompt's own First-Run Control
Instruction (sections 57 / 82) says install the machinery before operating it:

- `research-architect` (the agent that synthesizes across cards, master prompt
  section 13) — separate Stage-1 work.
- `research/current_harness_baseline.md`, `harness_research_matrix.md`,
  `cross_research_synthesis.md`, `L5_gap_analysis.md`, and the
  `DV_AGENT_HARNESS_L5_1_*` blueprint/priority/implementation/benchmark/
  risk documents (section 48) — all **Stage 2** outputs. They are produced by
  analyzing real documents, so creating empty files with those names now would
  be creating artifacts to satisfy names, which section 48 explicitly forbids.

## The stage boundaries this tree lives inside

| Stage | What happens | Gate to the next |
|---|---|---|
| 0 | Audit what L5 already has | — |
| 1 | Install the research capability (skill, schema, card store, tests) | The 8 acceptance tests A–H (master prompt section 23) |
| 2 | Read real documents, produce cards, then synthesis and gap analysis | — |
| 3 | Implement an approved change | **Explicit, separate human approval.** Never inferred from a card, a synthesis, or a strong result. |

Stage 2 must not begin until `research-ingestion` and `research-architect` are
both proven operational through the Stage-1 acceptance tests. Stage 3 must not
begin without a human decision made specifically for that change — and even
then, per CLAUDE.md's gh/PR-Only Governance Policy, it reaches `main`/`master`
only through a human-approved PR, never an agent push.

## The one rule that shapes the card store

Each document is read **independently first** (master prompt section 27). A card
is written from that document alone, with no glance at what the other cards say.
Only after independent cards exist may `research-architect` look across them.

This is not tidiness. Independent convergence — three unrelated papers reaching
the same mechanism — is the only thing in this tree that legitimately raises
confidence, and it stops meaning anything the moment card #2 was written while
looking at card #1. Repeated vendor marketing is not convergence.

## The other rule: REUSE before EXTEND before ADD

Every card carries a `candidate_l5_mapping` block whose six `existing_*` slots
each require a `search_basis` — a statement of what was actually searched —
even when nothing was found. "Do not assume absence" (master prompt section 8)
is enforced by the schema, not by good intentions, because this project has a
verified history of building parallel mechanisms beside real ones that already
worked. A card that records "L5 has nothing like this" without showing the
search is the first step of exactly that failure.

## Layout

```
research/
  README.md              <- this file
  evidence_cards/        <- one card per document; see its own README for naming
    README.md
  sources/               <- optional: local copies of ingested documents
                            (not created by default; documents may live anywhere,
                             since a card cites its own absolute path + sha256)
```

## Where the mechanism actually lives

- Card contract: `dv_harness/schemas/research_evidence_card.schema.json`
- Skeleton builder / validator / gap: `dv_harness/doc_extraction.py`
  (`build_research_evidence_card_skeleton()`, `validate_research_evidence_card()`,
  `research_card_missing_fields()`)
- The reading discipline: `.claude/skills/research-ingestion/SKILL.md`
- Confidence / gap math, reused not reinvented: `dv_harness/inference.py`
- Source spec: `DV_Agent_Harness_L5_Research_Capability_Evolution_Master_Prompt_vLatest.md`
  (repo parent directory), sections 5–9, 27, 48, 57.
