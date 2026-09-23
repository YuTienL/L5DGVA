# M12 Excel Productization Requirements

Status: recorded for M12, `M12_STARTED = NO`. M12 is the existing
roadmap wave already named "Canonical Cutover/Productization +
Role-Based Action Dashboard" in `MASTER_PROGRAM_STATUS.md` — this
document adds Excel productization as a named slice of that existing
wave, not a new wave.

## What M12 owns for Excel specifically

Per the product contract's Wave Ownership section: **M6 owns
`ClarificationService`, `QuestionOwner` routing, Field Resolution
wiring, Task Boundary wiring, `HumanGate` integration — not polished
Excel UX.** M12 is the primary owner of Excel PRODUCTIZATION: the
polished, user-facing quality of the Excel frontend once its underlying
engine wiring (M6) exists.

This is a real, deliberate sequencing: Excel cannot be productized
before the engine it fronts (`ClarificationService`, the
`intake_field_resolution.py`/`intake_state.py` reconciliation) is
actually wired live — M12's own Excel work is necessarily downstream of
M6's.

## M12 Excel productization scope (recorded now, not built now)

- Polished workbook formatting/styling for each of the 8 role/task
  views (conditional formatting for `BLOCKING`/`CONFLICT` rows, column
  widths, frozen headers, etc. — cosmetic productization, not new
  semantics).
- Streamlined generation/import UX (e.g. a single-command
  generate-and-open flow, a single-command validate-and-import flow).
- Role-Based Action Dashboard integration (per M12's own existing named
  scope): surfacing Excel-sourced unresolved/blocking fields inside
  whatever dashboard M12 builds, not just inside the workbook itself.
- Error-message quality for the validation/security/staleness/conflict
  paths defined in this reconciliation's sibling documents — this
  wave's job is making those real, already-specified failure modes
  understandable to a human user, not inventing new failure modes.

## Explicit non-goals for M12 (owned elsewhere)

- `ClarificationService`/`QuestionOwner` routing itself — M6.
- The Field Resolution engine's own arbitration algorithm — already
  real (Cohort 4), reconciliation with `intake_state.py` is M6's job.
- vPlan/coverage/signoff authoritative computation — M10.
- Change-impact/maintenance authoritative lifecycle behavior — M10.5.
- Any benchmark/measurement of Excel's own productivity impact — M14
  (`may later measure clarification time, manual entry, context
  re-explanation, intake completion time, error rate — do not start M14
  or claim gains now`, per this reconciliation's own product contract).

## M14 forward-reference (not started, no claim made)

M14 (`L5DGVA Productivity & Expertise Amplification Benchmark`, already
roadmap-registered per the earlier M14 reconciliation) may eventually
measure whether Excel intake (vs. Native Claude CLI direct intake, vs.
the interactive L5DGVA CLI) reduces Junior DV clarification time, manual
entry, context re-explanation, and intake error rate. This reconciliation
records that FUTURE measurement obligation only — consistent with M14's
own `Pre-M13 Telemetry Requirements` doc's existing pattern of recording
non-invasive telemetry foundations without implementing or claiming
anything now. No such measurement exists today, and no claim of Excel's
own productivity benefit is made anywhere in this reconciliation's
artifacts.
