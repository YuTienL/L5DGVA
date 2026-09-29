# Excel Schema and Validation Requirements

Status: `EXCEL_SCHEMA_VALIDATION = DEFINED`, not implemented.

## Validation surface

Required checks before any imported value reaches Field Resolution:

- **Sheets**: expected sheet names/roles present for the declared
  `WORKBOOK_TYPE`.
- **Metadata**: the round-trip identity block
  (`EXCEL_ROUND_TRIP_CONTRACT.md`) present and well-formed.
- **Columns**: expected columns present for each sheet's own field
  schema (`EXCEL_INTAKE_FIELD_MAPPING.csv`).
- **Field IDs**: every `FIELD_ID` in the workbook resolves to a real
  Canonical field — an unrecognized `FIELD_ID` is a validation failure,
  never silently dropped or silently accepted.
- **Value types**: a cell's real content type matches the field's
  declared type (string/enum/number/date/etc.).
- **Enums**: `USER_ACTION` and any other enum-valued column contains
  only a value from its own real, closed vocabulary
  (`EXCEL_INTAKE_FIELD_MAPPING.csv`'s `USER_ACTION` mapping table).
- **Blanks**: a blank `USER_VALUE` with a non-`NO_ACTION_REQUIRED`
  `USER_ACTION` is a validation failure (an action implies a value,
  except `REJECT_VALUE`/`DEFER`/`REQUEST_EXPLANATION`/`WAIVE_IF_ALLOWED`,
  which are legitimately value-less).
- **Duplicates**: no `FIELD_ID` appears twice with conflicting
  `USER_ACTION`/`USER_VALUE` on the same sheet.
- **Unknown fields**: a column or field not recognized by the current
  schema version is reported, never silently ignored (it may indicate a
  workbook generated against a newer/older schema — see staleness
  handling).
- **Malformed workbook**: a corrupt or unreadable `.xlsx`/`.xlsm`
  structure fails safely with a clear diagnostic, never a partial silent
  import.
- **Unsupported schema version**: a `SCHEMA_VERSION` this importer does
  not recognize is refused, not guessed at.
- **Formulas / merged cells**: where relevant to a value cell, the
  computed/displayed value is read, never a raw formula string
  misinterpreted as a literal value; a merged cell's value is resolved
  to its single logical cell, never silently duplicated or dropped
  across the merge range.
- **Hidden metadata consistency**: the hidden metadata sheet (or
  equivalent) must agree with any visible duplicate of the same
  identity fields, if the workbook format carries both — a mismatch is
  a validation failure, not silently resolved by picking one.

## Security posture (record the requirement, do not build the subsystem now)

Fail safely on every check above. Do **not** depend on macros, and do
**not** execute arbitrary macro content under any circumstance — this is
a hard requirement, not a "prefer not to."

Future security acceptance criteria to be satisfied before Excel import
is exposed to any untrusted or externally-sourced workbook (recorded
here as a requirement, not built now — see
`EXCEL_SECURITY_REQUIREMENTS.md` for the full list):

- Path safety (no path traversal via embedded links/references).
- Resource limits (a workbook cannot exhaust memory/CPU/disk via a
  crafted zip-bomb-style `.xlsx`, which is itself a ZIP container).
- Malformed XLSX/ZIP handling (a corrupt container fails safely, never
  crashes the importer or the host process).
- External links (a workbook referencing an external resource is never
  silently fetched).
- Formula injection (a cell value that looks like a formula/command
  injection payload for a downstream consumer — e.g. a CSV-export
  target — is neutralized, never passed through raw).
- Macro content (VBA/macro-enabled workbook content is never executed,
  regardless of format).
- Hidden sheets (a hidden sheet's content is validated with the same
  rigor as a visible one — "hidden" is not a trust boundary).
- Unexpected objects (embedded OLE objects, images with active content,
  etc. are never executed or auto-opened).
- Untrusted text (any free-text cell, such as `USER_COMMENT`, is treated
  as data, never as a template/command string).
- Secret leakage (no credential/token/password-classed field is ever
  written into a generated workbook — same discipline as the "never
  exposes secrets" requirement in
  `EXCEL_ROLE_BASED_WORKBOOK_REQUIREMENTS.md`'s Project Intake view).

No new security subsystem is built by this reconciliation — this is a
recorded requirement for whichever future wave implements Excel import.
