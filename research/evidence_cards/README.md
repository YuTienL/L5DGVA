# research/evidence_cards/

One external technical document -> one ResearchEvidenceCard. Nothing else lives
here.

**Empty as of 2026-09-04, and correctly so.** Stage 1 installs the machinery;
ingesting real documents is Stage 2, which must not start until
`research-ingestion` and `research-architect` are proven through the Stage-1
acceptance tests (master prompt sections 57 / 82). A card sitting here before
then would be a card produced by unproven machinery.

## Naming

Master prompt section 27's stem convention, one stem per document:

```
paper_001        paper_002        ...   academic / arXiv / conference papers
standard_001     standard_002     ...   standards, Accellera documents
vendor_report_001                 ...   vendor technical reports, application notes
internal_report_001               ...   internal engineering / verification reports
```

Numbers are assigned in ingestion order within their own prefix and are never
reused, so `paper_003` always means the third paper ever ingested even after a
card is superseded.

## Two files per card, one stem

| File | Role |
|---|---|
| `<stem>.card.json` | **Canonical.** The machine-checkable card. Must validate against `dv_harness/schemas/research_evidence_card.schema.json`. |
| `<stem>.md` | Optional human-readable rendering of the same card. Convenience only — never the source of truth, never edited independently. |

The master prompt's section-27 examples are written as `paper_001.md`; the split
above keeps that filename while giving the card a form a schema can actually
check. If the two ever disagree, the `.card.json` wins and the `.md` is
regenerated — a card whose prose and data have drifted is not evidence.

## Identity: the filename is not the identity

`document_id` is `DOC-` plus the first 12 hex characters of the document's
sha256 (`dv_harness.doc_extraction.sha256_file`). So:

- renaming or re-filing a document does **not** change its `document_id`;
- editing the document **does**, which is exactly what makes
  `DocumentIndex.needs_extract()`'s incremental reuse correct;
- two cards citing each other in `related_prior_research` cite `document_id`,
  never a filename.

Cards are cross-referenced by `document_id` for that reason. A filename is a
filing decision; the hash is the document.

## Before you add a card here

1. It was built by
   `dv_harness.doc_extraction.build_research_evidence_card_skeleton()` — the
   sha256, `document_id`, path, size and `source_provenance` were computed from
   the real file, never typed.
2. It passes `dv_harness.doc_extraction.validate_research_evidence_card()`.
   An invalid card must not be filed: a later synthesis pass reads whatever is
   in this directory as settled evidence.
3. It was written from that document **alone** — no cross-document synthesis
   (master prompt section 27). Comparing cards is `research-architect`'s job.
4. Every claim in `claim_set` carries the right `claim_type`. An
   `AUTHOR_CLAIM` silently filed as a `FACT` is the one defect this whole
   directory exists to prevent.
