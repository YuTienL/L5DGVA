# Excel Stale Workbook & Conflict Handling

Status: `EXCEL_STALE_WORKBOOK_DETECTION = DEFINED`,
`EXCEL_CONFLICT_DETECTION = DEFINED`, not implemented.

## Stale workbook detection

A workbook's own `SOURCE_SNAPSHOT` (stamped at generation time, per
`EXCEL_ROUND_TRIP_CONTRACT.md`) is compared against the CURRENT
Canonical Intake state at import time. If the workbook was generated
against snapshot S17 and the project is now at S18, this must be
**detected**, never silently applied as if it were still current.

Dispositions:

| Disposition | Meaning |
|---|---|
| `SAFE_TO_APPLY` | Nothing the workbook touches has changed since `SOURCE_SNAPSHOT`; import proceeds normally |
| `REBASE_REQUIRED` | Some fields the workbook touches have new evidence since `SOURCE_SNAPSHOT`, but no direct value conflict — the workbook's answers can be re-applied against the current state after re-checking each touched field |
| `CONFLICT` | A field the workbook answers now has a DIFFERENT resolved/discovered value than when the workbook was generated — cannot be silently reconciled |
| `REGENERATE_WORKBOOK` | Too much has changed (e.g. the field schema itself moved, or too many fields are stale) for a safe rebase; a fresh workbook should be generated instead |
| `HUMAN_REVIEW_REQUIRED` | The disposition itself is ambiguous (e.g. a field was removed from the schema entirely, or the snapshot chain cannot be resolved) — escalated rather than guessed |

## Conflict detection (Excel `DeclaredValue` vs. `AutoDiscoveredValue`)

When an Excel-declared value conflicts with the engine's own
auto-discovered (or derived) value for the same field:

1. **Both candidates are preserved**, with their own evidence —
   never a silent overwrite of one by the other. This is the exact
   behavior `intake_field_resolution.py`'s own `_decide()` already
   implements for a `DECLARED` vs. `AUTO_DISCOVERED` disagreement
   (Cohort 4's own `test_declared_versus_discovered_conflict_is_
   contradicted_never_silently_overwritten`) — Excel import triggers
   the SAME code path, not a parallel one.
2. **The conflict is marked** using the real Canonical
   `ValidationState`/`ConfirmationState` semantics
   (`ValidationState.CONTRADICTED`, `ConfirmationState.CONFLICT`) —
   never a bespoke Excel-only "conflict" flag disconnected from the
   engine's own vocabulary.
3. **The conflict routes** through Field Resolution's existing
   arbitration (9-level `source_authority` order, when both sides carry
   evidence-backed authority) and, when that cannot resolve it, to the
   future `ClarificationService`/`QuestionOwner` chain (M6-owned) —
   never silently chosen by the import process itself.

## Why this matters specifically for Excel (vs. other frontends)

Excel workbooks are the one frontend most likely to be edited OFFLINE,
away from the live Canonical Intake state, and re-imported after a real
delay — the interactive CLI and Native Claude CLI both operate against
the live state in real time, so staleness is structurally rare for them.
This is why stale-workbook detection is a first-class, explicitly
required contract for Excel specifically, not an incidental afterthought
borrowed from the other frontends.
