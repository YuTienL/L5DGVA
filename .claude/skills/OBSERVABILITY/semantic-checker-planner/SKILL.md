---
name: semantic-checker-planner
description: Identify protocol/state/configuration/address/interrupt/response semantics that require explicit checkers.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# semantic-checker-planner

Identify protocol/state/configuration/address/interrupt/response semantics that require explicit checkers.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.

## Deciding whether a CHECKER/ASSERTION reduces to the state_machine_checks DSL

(checker-sva-generator task, 2026-09-01 -- see
`dv_harness/uvm_generator/state_machine_checks.py` and
`.work/checker-sva-generator-design-report.md`.) Once a semantic requirement
is past the "End-to-end compare → scoreboard" triage above and has landed on
CHECKER or ASSERTION, apply this 3-question decision procedure BEFORE
hand-authoring it, to find out whether it mechanically reduces to the real,
evidence-gated `state_machine_checks` DSL instead of a `1'b1; // TODO`
placeholder or a hand-written checker body:

- **Q1**: Fully decidable from a FINITE, currently-enumerable set of legal
  values/states plus a legality relation, checkable using only
  current+immediately-previous cycle values (no cross-transaction memory)?
  → **PROTOCOL-STATE-MACHINE LEGALITY**. Record
  `"classification": "PROTOCOL_STATE_MACHINE_LEGALITY"` on the
  `recommended_mechanisms[]` entry and add a `"state_machine_check"` opt-in
  (`kind`: `"valid_transition_table"` | `"mutual_exclusion"` |
  `"legal_value_set"`, per that module's schema) so
  `generate_observability_plan.py`'s ASSERTION branch compiles a real
  property/assert instead of a placeholder.
  *Worked example*: PCIe LTSSM transition legality
  (`pcie_ltssm_generator.py`'s own `LTSSM_TRANSITIONS` table, generalized) --
  state `DETECT` may legally transition only to `{POLLING, HOT_RESET,
  DISABLED}`; any other observed `to_state` is a real defect signature,
  mechanically checkable from `$past(state)`/`state` alone, no
  cross-transaction context needed. (CAN-FD single-winner bus arbitration
  and a register field's fixed legal-encoding set are the same idiom's
  `mutual_exclusion`/`legal_value_set` variants.)
- **Q2** (if Q1 NO): Requires binding a specific stimulus event to a
  specific LATER response event via correlating context
  (address/tag/pending-request table) needing FIELD/PAYLOAD interpretation?
  → **INTERRUPT/RESPONSE SEMANTIC**. Record
  `"classification": "INTERRUPT_RESPONSE_SEMANTIC"` and stay hand-authored
  -- NOT DSL'd. Populate the CHECKER branch's REQUIRED-FIELD SCAFFOLD
  (`arm_event`, `correlation_key`, `response_window`, `window_evidence`)
  from real evidence instead of leaving the generic TODO comment; this is
  already enforceable by the existing, wired
  `checker_semantic_trace_consistency_gate.py` (VERIFY stage) -- no new gate
  needed for this branch.
  *Worked example*: USB `SET_ADDRESS` -- a device must not honor the new bus
  address until the Status stage of THAT SPECIFIC control transfer (USB 2.0
  spec section 9.4.6, p.256) completes; this needs a per-transfer
  pending-request correlation, not a fixed state table.
- **Q3** (if Q1, Q2 both NO): Pure signal-level temporal relationship,
  bounded spec-cited cycle count or unconditional stability, no
  field/payload interpretation? → **CROSS-CYCLE TEMPORAL INVARIANT**.
  Record `"classification": "CROSS_CYCLE_TEMPORAL_INVARIANT"` and stay
  hand-authored this pass -- no bounded-latency/stability generator exists
  yet to ground a DSL against (a plausible SECOND small idiom-DSL,
  flagged as a follow-up, not silently guessed into an existing shape).
  *Worked example*: a bounded-response handshake `req |-> ##[1:16] ack`
  cited to a real spec max-latency figure, or an unconditional stability
  requirement `$stable(sig) throughout (...)`.
- **Else**: `"classification": "OTHER_HAND_AUTHORED"` -- remains
  hand-authored, no safe DSL reduction identified.

Recording `"classification"` is not optional busywork: it is what lets
`assertion_placeholder_closure_gate.py`
(`STAGE_GATES["VERIFICATION_ARCHITECTURE"]`) tell a real, DSL-generated
PROTOCOL-STATE-MACHINE-LEGALITY assertion apart from one that still silently
carries the ASSERTION branch's placeholder text -- an omitted or wrong
classification either hides a real gap from that gate or wrongly demands
DSL treatment for a genuinely hand-authored case.
