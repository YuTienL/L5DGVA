# M7 V1 -- L5DGVA_MODEL_RESULT_V1 Contract

Real, implemented contract: `dv_harness/model_result.py`.

## Fields

| Field | Purpose | Implementation |
|---|---|---|
| `RESULT_VERSION` | protocol version, checked but not yet cross-validated against `HANDOFF_VERSION` (a real, disclosed V1 simplification -- see `M7_FINAL_QUALIFICATION_REPORT.md`'s own gap list) | `model_result.RESULT_VERSION` |
| `TASK_ID` | round-trip identity | validated against the matching handoff's own `task_id` |
| `PRODUCER_MODEL` | which model actually produced this | validated against the matching handoff's own `target_model` |
| `TASK_TYPE` | round-trip compatibility | validated equal to the handoff's own `task_type` (exact match, never "close enough") |
| `RESULT_STATUS` | one of `PASS`/`FAIL`/`PARTIAL`/`BLOCKED`/`HUMAN_DECISION_REQUIRED`/`INSUFFICIENT_EVIDENCE`/`INVALID_SCOPE`/`INVALID_RESULT` | `model_result.RESULT_STATUSES` -- an unrecognized value is a real `ResultParseError`, never silently accepted |
| `CLAIMS` / `FINDINGS` | the model's own assertions | kept SEPARATE from `EVIDENCE_REFS` -- "a model result is not evidence merely because a model produced it" |
| `EVIDENCE_REFS` | what actually backs a claim/finding | required whenever `CLAIMS`/`FINDINGS` is non-empty (`evidence_validated`) |
| `COUNTER_EVIDENCE` / `UNKNOWN_ITEMS` | preserved, never dropped | never resolved by majority vote -- both sides of a disagreement stay on the record |
| `FILES_REFERENCED` | scope enforcement input | checked against the handoff's own `TaskBoundary` via `task_boundary_conformance.classify_path()`, reused verbatim |
| `VALIDATION_PERFORMED` | what the producer model itself claims to have checked | free-form list, carried through, never itself trusted as THIS project's own validation |
| `RECOMMENDED_ACTIONS` | free-form | carried through to the Canonical Consumer |
| `HUMAN_DECISIONS_REQUIRED` | routes to the real HITL mechanism | see `M7_RESULT_INGESTION_AND_CONSUMPTION.md` |
| `SCOPE_EXCEPTIONS` | a producer's own declared exceptions to scope | carried through, NEVER auto-honored -- an actual `FILES_REFERENCED` violation still fails `scope_validated` regardless of what `SCOPE_EXCEPTIONS` claims |
| `RETURNED_ARTIFACTS` | any files/content the producer model returns | carried through |

## Round-trip validation chain (`validate_result()`)

Six real, independent checks, each with its own boolean outcome (never
collapsed into one opaque pass/fail):

```
task_id_validated       -- TASK_ID == handoff.task_id
producer_validated      -- PRODUCER_MODEL == handoff.target_model
task_type_validated     -- TASK_TYPE == handoff.task_type
scope_validated         -- every FILES_REFERENCED entry classifies
                            WITHIN_DECLARED_BOUNDARY against the
                            handoff's own TaskBoundary
schema_validated        -- RESULT_STATUS already real (from_markdown()
                            enforces this) AND PRODUCER_MODEL is a real
                            target model
evidence_validated       -- CLAIMS/FINDINGS non-empty implies
                            EVIDENCE_REFS non-empty
```

`ValidationOutcome.accepted` is `True` only when ALL SIX are `True` --
never a majority, never a weighted score. Model confidence is never read
by this function; only structural, evidence-backed facts.

## Test evidence

`dv_harness_tests/test_model_handoff_v1.py`: valid round-trip, malformed
markdown, missing required fields, invalid `RESULT_STATUS`, task ID
mismatch, producer mismatch, scope violation (including a file that is
BOTH plausible-sounding and forbidden), missing evidence for real
claims, and the negative case (no claims/findings needs no evidence) --
all real, passing tests, not merely described.

## Ingestion semantics added by M7-V1-CODEX-REVIEW-002 remediation (GAP-V2-009/012/013)

Authoritative code: `dv_harness/md_kv_codec.py`, `dv_harness/model_result.py`.

**Two encodings, explicit marker.** A document carrying
`<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->` (every `to_markdown()` output)
is an exact, lossless encoding of any string (CR, LF, Unicode line
boundaries, edge whitespace, leading `#`, empty items, literal `(none)`).
A document without the marker is RAW (what an external model writes by
hand): values are taken verbatim and are never unescaped, so `a\rb` or
`C:\new` in external text is never silently transformed.

**Fail-closed structure (both encodings).** Duplicate section, unknown
section, stray non-title content before the first section, and a wrapped
(non-bullet) line inside a list section are `ResultParseError`s. A
document is never "last header wins".

**Evidence grammar.** A path token is a repo-style path with a recognised
extension, optionally `:line`/`:start-end`. An `EVIDENCE_REFS` entry is a
*citation* when, after an optional `EVIDENCE:`/`COUNTER_EVIDENCE:` label,
it begins with a path token: every path token in it must exist and lie in
the read boundary. Any other entry is *narrative*: disclosed
(`evidence_unverifiable`, `evidence_narrative_mentions`), never
verification. A result with status PASS/FAIL/PARTIAL that makes claims or
findings needs at least one verified citation
(`NO_VERIFIED_EVIDENCE_FOR_VERDICT`).

**Scope.** `FILES_REFERENCED` and evidence citations are READ claims
checked against the read boundary; `RETURNED_ARTIFACTS` are OUTPUT claims
checked against ALLOWED_FILES only, plus the one caller-derived exemption
for the result document's own path. `EXPECTED_OUTPUT_SCHEMA` must be the
supported schema.

## Ingestion semantics added by M7-V1-CODEX-REVIEW-003 remediation (GAP-V2-011/012/013)

- **Canonical paths.** Every scope comparison (FILES_REFERENCED, RETURNED_ARTIFACTS,
  evidence citations, governance refs, the own-result exemption) is done on the
  canonical root-relative path (`..`/`.` collapsed; absolute, UNC, drive,
  NTFS-stream, escaping or invalid-character paths are `UNSAFE_PATH`) and, for
  paths that exist, on the true filesystem identity (case, trailing dots,
  symlinks). Either view being out of bounds fails the result.
- **Content identity.** A result is identified by the SHA-256 of the bytes that
  were parsed (single read). State and registry record it; a retry with
  different content is `CONSUMPTION_CONFLICT`; replaying a different file after
  consumption is flagged `RESULT_CONTENT_DIFFERS_FROM_CONSUMED`.
- **Document identity.** Exactly one canonical `# L5DGVA_MODEL_RESULT_V1` title
  first; the escaped-encoding marker only in the slot after it; duplicate title
  or marker is an error. In the escaped encoding None is `(none)` and the empty
  string is `(empty)`.
- **Interruption.** An exception during consumption persists
  `AUTO_RETRY_INTERRUPTED_IMPORT` before propagating; imports of one task are
  serialized by a lock.
- **Automatic ingestion.** A returned RESULT_V1 placed at its registered
  EXPECTED_RESULT_FILE is detected, stability-checked, hashed and imported by
  the watcher / startup scan through the same `import_result()`; no import
  command is part of the human's task (`M7_RESULT_WATCHER_ARCHITECTURE.md`).
