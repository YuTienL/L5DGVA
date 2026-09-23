# Excel Security Requirements

Status: recorded requirement, not implemented, not a built security
subsystem. This document exists so a future implementation wave has an
explicit acceptance checklist rather than discovering these concerns ad
hoc.

## Hard requirements (non-negotiable, apply from the first implementation)

- **No macro dependency**: Excel import/export must not depend on
  macros for any core functionality.
- **No macro execution**: a workbook's VBA/macro content, if present, is
  never executed under any circumstance, regardless of file format
  (`.xlsx`, `.xlsm`, `.xls`).
- **Fail safely**: every validation failure (schema, security, or
  otherwise) fails the import cleanly with a diagnostic — never a
  partial import, never a crash that could leave Canonical Intake state
  inconsistent.

## Future acceptance criteria (recorded now, satisfied before untrusted-workbook exposure)

| Concern | Requirement |
|---|---|
| Path safety | No path-traversal via any embedded reference, link, or generated file path derived from workbook content |
| Resource limits | Bounded memory/CPU/disk consumption even against a crafted `.xlsx` (a ZIP container) designed to exhaust resources (zip-bomb-style) |
| Malformed XLSX/ZIP | A corrupt or truncated container is detected and refused, never causes a crash or undefined behavior |
| External links | A workbook referencing an external resource (URL, network path, another file) is never silently fetched or followed |
| Formula injection | A cell value is never passed unescaped to any downstream consumer where it could be interpreted as a formula/command (e.g. CSV export opened in a spreadsheet application, the classic `=cmd|...` / `@SUM(...)` injection class) |
| Macro content | VBA/macro presence is detected and reported, never silently stripped-and-continued (stripping without disclosure could hide a real tampering signal) nor executed |
| Hidden sheets | Validated with the same rigor as visible sheets — hidden is a UX convenience, never a trust boundary |
| Unexpected objects | Embedded OLE objects, active-content images, or other embedded objects are never auto-opened or executed |
| Untrusted text | Free-text fields (`USER_COMMENT`, etc.) are always treated as inert data, never interpolated into a template, shell command, or query |
| Secret leakage | No credential/token/password/API-key-classed value is ever written into a generated workbook, matching this project's own `memory_router.route_memory()` hard-REJECT precedent for the same class of data |

## Explicit non-goal of this reconciliation

**No new security subsystem is built now.** This document is the
requirements list a future implementation wave (Excel import build,
whichever wave that ends up being — likely alongside or after M12's own
productization work) must satisfy, not a design for a scanner/sandbox/
validator that exists today.
