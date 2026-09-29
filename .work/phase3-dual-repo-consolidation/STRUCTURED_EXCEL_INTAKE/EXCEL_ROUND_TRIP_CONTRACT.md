# Excel Round-Trip Contract

Status: `EXCEL_ROUND_TRIP = DEFINED`, not implemented.

## Workbook identity (never filename-based)

```
PROJECT_ID          -- which Canonical project this workbook belongs to
WORKBOOK_ID          -- a stable identifier for this specific workbook instance
WORKBOOK_TYPE         -- one of the 8 role/task views (or an equivalent)
SCHEMA_VERSION        -- the field-schema version this workbook was generated against
GENERATION_ID         -- a stable identifier for this specific generation event
GENERATED_AT          -- real timestamp
SOURCE_SNAPSHOT        -- the Canonical Intake state snapshot this workbook was generated from
FIELD_SET_ID          -- which subset of fields this workbook covers
ROLE_VIEW             -- DE / DV / SHARED (or ALL for Project Intake)
CHANGE_ID (optional)   -- for a Change Impact workbook, the change this workbook is scoped to
```

May be carried in a hidden metadata sheet or a safe structural
equivalent. A workbook whose filename was renamed, copied, or emailed
around must still be correctly identified from its own internal
metadata — never inferred from the filename a human happened to save it
under.

## Export (generation) contract

Generated FROM the current Canonical Intake state (per
`STRUCTURED_EXCEL_INTAKE_ARCHITECTURE.md`'s "Excel generation" section):
prioritizes `UNRESOLVED`/`NEEDS_CONFIRMATION`/`CONFLICT`/
`LOW_CONFIDENCE`/`HUMAN_AUTHORITY_REQUIRED` fields; already-resolved
fields may render `READ_ONLY`. Every generated workbook stamps its own
`SOURCE_SNAPSHOT` at generation time — the anchor the import-time
staleness check (`EXCEL_STALE_CONFLICT_HANDLING.md`) compares against.

## Import contract

`STRUCTURED_EXCEL_INTAKE_IMPORT`:

1. Validate workbook identity/version (the metadata block above is
   present, well-formed, and internally consistent).
2. Validate schema (field IDs recognized, value types correct, allowed
   actions recognized — see `EXCEL_SCHEMA_AND_VALIDATION_REQUIREMENTS.md`).
3. Detect staleness (compare `SOURCE_SNAPSHOT` against the CURRENT
   Canonical Intake state — see `EXCEL_STALE_CONFLICT_HANDLING.md`).
4. Preserve provenance/evidence for every imported value (see
   `EXCEL_INTAKE_FIELD_MAPPING.csv`'s import-provenance columns).
5. Route every update through Canonical Field Resolution
   (`resolve_field()`/`resolve_recorded()`-shaped arbitration) — **never**
   a direct assignment to `EffectiveValue`.

## The one hard invariant this whole contract exists to enforce

**An Excel cell's value is a candidate, never a verdict.** Whatever a
human wrote in a spreadsheet cell becomes exactly one more `Candidate`
in the real Field Resolution engine's own arbitration — subject to the
same evidence-based, no-source-kind-precedence rules that already govern
every other source (auto-discovery, derivation, another human's answer
via a different frontend). This is the literal operationalization of
`EXCEL_IS_FRONTEND=YES` / `EXCEL_IS_SOURCE_OF_TRUTH=NO`.
