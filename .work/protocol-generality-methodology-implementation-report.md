# Protocol Generality Methodology Extension — Implementation Report

**Date:** 2026-09-01
**Scope:** Documentation/methodology extension only. No code, no generator changes, no pytest
suite. This closes the two SPECIFIC structural gaps identified by this session's
protocol-genericity audit (`.work/2026-09-01-consolidated-pipeline-and-genericity-audit-report.md`,
Part B) by extending the two implicated CORE skill methodology documents plus one cross-reference
in CLAUDE.md — it does **not** run, or claim to have run, a real non-USB pilot project.

## What this is, and what it explicitly is NOT

This task added **generic, clearly-labeled, explicitly UNTESTED placeholder guidance** to two
`SKILL.md` files so that a *future* real non-USB pilot project has a documented starting shape to
confirm, correct, or replace — instead of zero guidance and a silent assumption that the
USB-derived framing "just works." Per the task's own Evidence Truth Rule / No Golden-Reference
Content Mining constraint, no fake PCIe/MIPI/AMBA pilot evidence, register names, or "results" were
invented anywhere. Nothing here changes any protocol's `genericity_status` from
`UNTESTED`/`STRUCTURALLY_INCOMPATIBLE` to `WORKING`. Both new sections say so explicitly, more than
once, in their own text — this is deliberate, not an oversight to be tightened later.

## What was built

### 1. `.claude/skills/CORE/interrupt-event-dispatch/SKILL.md` — new section "Simplex Streaming
branch_fw Variant (2026-09-01, generic placeholder guidance -- UNTESTED, awaiting a real
simplex-streaming pilot project to validate)"

Appended after the existing "Real worked example (USB, DWC_usb31 wrapper)" section (so the
USB-validated worked example stays intact and unmodified, and the new section is clearly additive,
not a rewrite). Defines a generic alternate `branch_fw` loop shape for a simplex RX-only or TX-only
DUT (MIPI CSI-2/DSI-shaped, named only as illustrative protocol examples, no invented register
names for either):

- **ARM → WAIT → WAKE/DECODE → CLEAR → ADVANCE** — replacing the bidirectional
  command-arm/response-wait loop with a buffer/frame-completion-driven loop: arm a buffer
  descriptor, wait on a buffer-done interrupt (event-driven, same no-polling discipline as the
  existing "CPU Task 層級實作模式" rule), decode the completion status/tag, clear only the bit(s)
  serviced (reusing the existing aggregated-W1C rule), then advance to the next buffer and re-arm —
  the ADVANCE step being the one genuinely new step with no analogue in the bidirectional loop.
- All register/field names are deliberate generic placeholders as the task specified:
  `BUFFER_DESC_REG`, `BUFFER_DONE_IRQ_EN`, `BUFFER_DONE_IRQ`, `STATUS_REG`, `FRAME_ID`/`BUFFER_ID`
  — explicitly marked as placeholders a real project must replace with real
  RTL/programming-guide-sourced names, exactly as the file's existing `SOURCE_HIER` rule already
  requires.
- A "What is genuinely different from the bidirectional framing" subsection explains why this
  needed a full section rather than a footnote (no command register, branch-B becomes a continuous
  stream driver/absorber rather than a request/response peer, `PATTERN_ID`/`COMMAND_ID` may
  legitimately be N/A) — and separately notes that the per-port-parallelism generalization to
  multi-lane/multi-stream DUTs is a low-risk extension of *already-validated* logic, not itself an
  unvalidated claim, to keep the "what's actually untested" boundary honest and precise rather than
  blanket-hedging everything.
- Reuses the existing `IRQ_ID...` and `SERVICE_LOOP_ID...` record shapes unchanged (no new record
  schema invented) with guidance on how `TRIGGER`/`PATTERN_ID`/`COMMAND_ID` map for a streaming
  source.
- Closes with an explicit, bolded UNTESTED disclaimer restating the awaiting-real-pilot condition.

### 2. `.claude/skills/CORE/branch-mapper/SKILL.md` — new section "AMBA-as-Primary-DUT
Master/Slave Redefinition (2026-09-01, generic placeholder guidance -- UNTESTED, awaiting a real
AMBA-fabric pilot project to validate)"

Appended after the existing "Real-World Reference Mapping" section (again additive, USB worked
example untouched). Redefines `branch_a*`/`branch_b*` for the case where an AMBA/AHB/AXI/ACE-Lite
fabric IS the primary DUT rather than a shared-resource overlay on pre-existing per-port branches:

- **`block`** unchanged (SoC-global init, still single/non-per-agent).
- **`branch_a0..branch_aN`** redefined as **AMBA MASTER agents** (one per bus-master/initiator:
  CPU core, DMA engine, other bus-mastering IP).
- **`branch_b0..branch_bM`** redefined as **AMBA SLAVE/memory agents** (one per addressable
  slave/target: memory controller, peripheral register block, bridge).
- **`branch_fw`** generalized from "per-port FW loop dispatching DUT interrupts to VIP scenarios"
  to a shared fabric arbitration/routing service loop, with the existing `interrupt-event-dispatch`
  ARM/WAIT/WAKE/DECODE/CLEAR loop reused unchanged for fabric-level interrupts (e.g. interconnect
  error/security-violation IRQs) — same "block=SoC init, branch_fw=shared service loop" framing the
  task asked for, generalized to a fabric context.
- A "Mapping record implications" subsection confirms the existing `MAP_ID,A_BRANCH,B_BRANCH,...`
  record shape and the existing AMBA M×N arbitration-policy rules (round-robin/priority/QoS from
  real RTL evidence, shared-arbitration-domain tracking) apply completely unchanged — only the
  identity of what `A_BRANCH`/`B_BRANCH` name changes, not the record schema or the arbitration
  rules themselves. This was a deliberate design choice (see Rulings below): reuse, don't fork, the
  mapping schema.
- A "What still needs real-pilot confirmation" subsection lists two specific open questions (VIP
  topology granularity per slave; whether `block`/`branch_a*` boundaries are as cleanly separable
  in real interconnect RTL as in the USB per-port case) that this task deliberately leaves open
  rather than guessing an answer to, per the Evidence Truth Rule.
- Closes with the same style of explicit, bolded UNTESTED disclaimer.

### 3. `CLAUDE.md` — "Engineering Discipline Rules" section

Added one new bullet, "Non-USB topology variants (2026-09-01, UNTESTED placeholder guidance)",
cross-referencing both new sections by exact section title and file, explicitly restating that
neither has been validated end-to-end and neither changes any protocol's genericity_status, and
telling a future agent building a non-USB (CSI-2/DSI, or AMBA-fabric/`SYSTEM_LEVEL_MODE`)
environment to read them first. Placed immediately after the existing "Architecture-conformance
audit" bullet (the bullet that already names the USB reference environment and the canonical
naming architecture), so the new bullet reads as a direct follow-on to that one rather than an
unrelated insertion.

## Rulings

- **RULING: reuse the existing mapping/record schemas unchanged for both new sections, rather than
  inventing new field names.** The simplex-streaming section reuses `IRQ_ID...`/`SERVICE_LOOP_ID...`
  verbatim; the AMBA-as-fabric section reuses `MAP_ID,A_BRANCH,B_BRANCH,...` verbatim. Rationale:
  the task asked for "the SAME framing generalized," and CLAUDE.md's own additive/backward-compatible
  convention (new content should not silently fork established shapes) argues for redefining what a
  field *means* over adding new fields a real pilot hasn't asked for yet. A real pilot project is
  free to propose schema extensions once it exists with real evidence; inventing them speculatively
  now would itself be a small instance of "inventing content" this task was told to avoid.
- **RULING: place both new sections at the end of their respective files, after the existing
  USB worked example, rather than interleaving them into the existing flow.** This keeps the
  USB-validated content byte-for-byte intact (verified via diff: only additions, zero deletions in
  either SKILL.md) and makes the new content unambiguously additive and easy to later remove or
  revise in isolation if a real pilot's findings contradict this placeholder guidance.
- **RULING: keep the new sections in English, matching the most recent existing section in
  `interrupt-event-dispatch/SKILL.md`** ("Two generic rules on decode/clear (2026-09-01,
  distilled and genericized)"), rather than the older mixed Chinese/English style used by the
  file's original sections. Precedent set by the file's own most recent prior edit.
- **RULING: explicitly call out, inside each new section, which specific sub-claims are
  low-risk extensions of already-validated logic (per-port/per-stream parallelism) versus
  genuinely unvalidated (the loop shape and register placeholders themselves).** A blanket
  "everything here is untested" would have been simpler to write but less honest and less useful
  to a future agent trying to triage what to check first.

## Verification performed (no pytest — documentation task)

- Read both target `SKILL.md` files in full before editing (see transcript above).
- Re-read the full diff of both edited files after writing them to confirm: (a) zero characters
  changed or removed in any pre-existing line — `git diff --stat` shows insertions only for both
  SKILL.md files; (b) the new sections' internal record-field references (`IRQ_ID...`,
  `SERVICE_LOOP_ID...`, `MAP_ID,A_BRANCH,B_BRANCH,...`) exactly match the field names as literally
  spelled in the pre-existing "記錄:" blocks earlier in each file — no drifted/renamed fields.
- Confirmed neither new section contradicts an existing rule: the simplex-streaming section
  explicitly reuses (not overrides) the existing no-polling/watchdog-as-checker rule and the
  aggregated-W1C clear rule; the AMBA-as-fabric section explicitly reuses (not overrides) the
  existing AMBA M×N arbitration-policy rules and explicitly says the existing per-port-overlay
  "AMBA M×N Mapping" section is unchanged and still applies to the pre-existing per-port-primary
  case — this new section is an *alternate* framing for a different topology shape, not a
  replacement.
- Confirmed the new CLAUDE.md bullet's file/section-title references are byte-exact matches to the
  actual new `##`-level headings added in each `SKILL.md` (copy-checked, not retyped from memory).
- Checked this repo for `industrial`/`PACKAGE` deliverable-tree copies of these skill files (per
  CLAUDE.md's "Methodology Consolidation Rule" sync step) — none exist in this repo, so no
  parallel-tree sync was needed or performed.
- `git diff --stat` confirms only the three intended files changed (plus two pre-existing unrelated
  working-tree modifications, `.dv-harness/events.jsonl` and `.dv-harness/state.json`, that were
  already modified before this task started and are deliberately excluded from this task's commit).

## Concerns / residual gaps

- This is placeholder guidance by design and by the task's own explicit instruction — it has zero
  empirical validation. A real simplex-streaming pilot or a real AMBA-fabric-as-DUT pilot may well
  surface a materially different loop shape or agent redefinition than what's written here; nothing
  in this task should be read as reducing the priority of actually running one.
- `SYSTEM_LEVEL_MODE` (the mode meant to exercise the AMBA-as-fabric redefinition) is still, per the
  audit report referenced above, "a real gate with zero generator code behind it" as of this
  session — this task adds only the *methodology* doc guidance the audit asked for, and does not
  add or modify any generator code, so that separate code gap remains fully open.
- No new automated check enforces that a future edit to the USB-specific sections of either
  SKILL.md keeps these new sections consistent; that's a manual-review responsibility going
  forward, same as the rest of these files today.

## Commit

One commit covering all three file edits (`branch-mapper/SKILL.md`, `interrupt-event-dispatch/SKILL.md`,
`CLAUDE.md`). See parent task result for the short SHA.
