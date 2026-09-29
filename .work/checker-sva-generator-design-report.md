# Design: Checker/SVA Generator (state_machine_checks DSL)

## Gap

`generate_observability_plan.py`'s ASSERTION branch (`tools/observability/generate_observability_plan.py:43-52`) emits a literal `1'b1; // TODO: replace with evidence-backed temporal property` inside every `property`/`assert property` block, for every target, unconditionally — zero generation mechanics, only a placeholder. Its CHECKER branch (lines 29-42) is equally a stub. The 5+ OBSERVABILITY planner skills that feed it (semantic-checker-planner, assertion-placement-planner, scoreboard-checker-assertion-analyzer, verification-architecture-mechanism-planner, observability-gap-closure-engine, observability-traceability-linker) give no decision procedure and no generation mechanics — all share the same 5-bullet boilerplate with no worked example. `dv_harness/uvm_generator/generator.py` already has two REAL, working, evidence-gated DSLs (virtual_sequences, SCOREBOARD_CHECKS) for adjacent problems, and `pcie_ltssm_generator.py` already has a real, tested Python model (`LTSSM_TRANSITIONS` + `validate_transition` + a generated case-statement `ltssm_transition_legal` SV function) solving the exact "state-machine legality" sub-problem for PCIe only — hardcoded to PCIe's own 11 states, not a manifest-driven DSL, never connected to `generate_observability_plan.py`.

## Real existing patterns to reuse

1. `generator.py`'s manifest-driven DSL convention (read in full, 1565 lines): every extension is (i) ADDITIVE/backward-compatible — a manifest lacking the new key produces byte-identical output; (ii) opted into by a discriminator field (`scoreboard_rules`' `"check_name"` key, `generator.py:636-639`); (iii) every non-structural fact requires a non-empty `"evidence"` string, enforced by a typed `ValueError` subclass with SCREAMING_SNAKE_CASE `reason` + `detail` dict (`MissingSequenceBodyEvidenceError`, `MalformedScoreboardCheckError`, `MissingVirtualSequencerFieldEvidenceError`, `MissingConnectionEvidenceError` — `generator.py:81-184`); (iv) emission is string-splice appended after an unchanged placeholder body (`scoreboard()`: `generator.py:729-733`), never replacing the old path outright. `SCOREBOARD_CHECKS`' own `register_decode`/`enum_translation` (`generator.py:787-845`) is the closest precedent for "compile a structural fact into a real runtime SV case/compare".
2. `pcie_ltssm_generator.py` (421 lines): real Python transition table (`LTSSM_TRANSITIONS`, `dict[str, frozenset[str]]`), a pure validator (`validate_transition`, raising typed `LTSSMError` — `UNKNOWN_LTSSM_STATE`/`ILLEGAL_LTSSM_TRANSITION`), and a generated SV `ltssm_pkg` method (lines 353-381) compiling the SAME table into a real `case (from_state) ... endcase` function, documented as "kept in lockstep with the Python model by construction" (lines 372-373). Reuse this shape, generalized to any manifest-supplied state/transition table.
3. `canfd_arbitration_generator.py`'s `resolve_arbitration()` — real evidence that a mutual-exclusion/one-hot-shaped legality property exists conceptually (CAN-FD bus arbitration: exactly one node may win), though no `$onehot`/`$onehot0` idiom is emitted anywhere yet (grep-confirmed).
4. `address_map_verifier.py`'s multi-source-agreement pattern (decoder = mandatory primary, histogram = mandatory corroboration, doc = corroboration-only) — reference shape for judging evidence sufficiency.
5. `tools/verification_flow/assertion_vacuity_gate.py` / `assertion_vacuity_and_reachability_gate.py` (STAGE_GATES["COVERAGE_CLOSURE"], `dv_harness/gates.py:164-165`) are ALREADY real and wired, gating on `antecedent_reached`/`antecedent_attempts`/`negative_control_failed` per `assertion_id` — protocol-agnostic, require NO change; the new DSL only needs every emitted assertion to carry a stable `assertion_id == sv_id(assertion_name)` so these gates can be pointed at them. `observability_sufficiency_gate.py` (STAGE_GATES["VERIFICATION_ARCHITECTURE"]) already requires every non-waived vPlan requirement to name an ASSERTION/CHECKER evidence_point — it does not yet distinguish "real DSL-generated" from "still-a-placeholder" (the one real gap left in the gate layer).
6. `generator.py`'s existing `m.get('clocks')`/`m.get('resets')` manifest fields (line 1553-1554, defaulting to `"clk"`/`"rst_n"`) — reuse, don't invent new per-check clock/reset fields.

## Proposed design

**Decision procedure** (write into semantic-checker-planner/assertion-placement-planner/scoreboard-checker-assertion-analyzer SKILL.md files, same worked example in all three per the Methodology Consolidation Rule):

Given one classified semantic requirement (already past the existing "end-to-end content compare -> scoreboard" triage):

- **Q1**: Fully decidable from a FINITE, currently-enumerable set of legal values/states plus a legality relation, checkable using only current+immediately-previous cycle values (no cross-transaction memory)? → **PROTOCOL-STATE-MACHINE LEGALITY** (PCIe LTSSM transition legality; CAN-FD single-winner arbitration; a register field's fixed legal-encoding set) → goes to the `state_machine_checks` DSL below.
- **Q2** (if Q1 NO): Requires binding a specific stimulus event to a specific later response event via correlating context (address/tag/pending-request table) needing FIELD/PAYLOAD interpretation? → **INTERRUPT/RESPONSE SEMANTIC** (e.g. USB SET_ADDRESS: device must not honor new address until Status stage of THAT SPECIFIC transfer) → stays hand-authored checker, NOT DSL'd.
- **Q3** (if Q1,Q2 both NO): Pure signal-level temporal relationship, bounded spec-cited cycle count or unconditional stability, no field/payload interpretation? → **CROSS-CYCLE TEMPORAL INVARIANT** (bounded-response `req |-> ##[1:N] ack`, stability `$stable(sig) throughout (...)`) — flagged as a plausible SECOND small idiom-DSL, sketched but NOT fully schema'd in this pass (no existing bounded-latency/stability generator exists to ground against).
- Else: remains hand-authored, no safe DSL reduction.

**DSL for PROTOCOL-STATE-MACHINE LEGALITY (fully specified):**

New module `dv_harness/uvm_generator/state_machine_checks.py`, mirroring `address_map_verifier.py`'s shape (typed error class + pure validate function + pure emit function). Imported by BOTH `generator.py` (manifest-driven env generation) and `tools/observability/generate_observability_plan.py` (plan-driven path) — one shared emission function.

`StateMachineCheckError(ValueError)`: same `reason` (SCREAMING_SNAKE_CASE) + `detail` (dict) convention.

Manifest key `"state_machine_checks"`: list of dicts, opted in via `"kind"` key (manifest with no key, or empty list = complete no-op, byte-identical to today).

Common required fields on every entry:
- `"assertion_name"`: str, non-empty → `MISSING_ASSERTION_NAME` if absent. Becomes the SV identifier via existing `sv_id()` helper.
- `"kind"`: one of `"valid_transition_table"` | `"mutual_exclusion"` | `"legal_value_set"` → `INVALID_STATE_MACHINE_CHECK_KIND` otherwise.
- `"evidence"`: str, non-empty → `MISSING_STATE_MACHINE_CHECK_EVIDENCE`.
Optional: `"on_violation"`: `{"severity": "UVM_ERROR"|"UVM_WARNING"|"UVM_INFO" (default UVM_ERROR, → INVALID_VIOLATION_SEVERITY if present-but-invalid), "message_template": str (optional, auto-derived default: "%s: illegal value/transition observed")}`.

**kind="valid_transition_table"** (generalizes `pcie_ltssm_generator`'s `LTSSM_TRANSITIONS` → `ltssm_transition_legal`):
- `"state_signal"`: str, non-empty SV expr → `MISSING_STATE_SIGNAL`.
- `"states"`: list[str], non-empty, unique → `INVALID_STATES_LIST`.
- `"transitions"`: dict[str, list[str]] — every key must be in `"states"` → `UNKNOWN_TRANSITION_SOURCE_STATE`; every listed target must be in `"states"` → `UNKNOWN_TRANSITION_TARGET_STATE`.
- Emits:
```
function automatic bit <name>_transition_legal(<state_type> from_state, <state_type> to_state);
  case (from_state)
    <STATE_A>: return (to_state inside {<STATE_B>, <STATE_C>});
    ... (one arm per states entry, manifest order)
    default: return 1'b0;
  endcase
endfunction
property <name>_p;
  @(posedge <clk>) disable iff (!<rst_n>)
    $changed(<state_signal>) |-> <name>_transition_legal($past(<state_signal>), <state_signal>);
endproperty
<name>_a: assert property (<name>_p)
  else `<uvm_severity>("<NAME>_ILLEGAL_TRANSITION", $sformatf(<message_template>, $past(<state_signal>), <state_signal>));
```

**kind="mutual_exclusion"** (generalizes CAN-FD single-winner into standard `$onehot`/`$onehot0`):
- `"signals"`: list[str], length>=2 → `INVALID_MUTEX_SIGNAL_LIST`.
- `"mode"`: `"exactly_one"` ($onehot) | `"at_most_one"` ($onehot0) → `INVALID_MUTEX_MODE`.
- `"guard"`: optional SV bool expr, default `"1'b1"`.
- Emits: `property <name>_p; @(posedge <clk>) disable iff (!<rst_n>) (<guard>) |-> $onehot[0](<{sig1,sig2,...}>); endproperty` + assert with the same else-clause shape.

**kind="legal_value_set"** (degenerate transition idiom, no history needed):
- `"value_signal"`: str, non-empty → `MISSING_VALUE_SIGNAL`.
- `"legal_values"`: list[str], non-empty → `INVALID_LEGAL_VALUES_LIST`.
- `"guard"`: optional, default `"1'b1"`.
- Emits: `property <name>_p; @(posedge <clk>) disable iff (!<rst_n>) (<guard>) |-> (<value_signal> inside {<legal_values>}); endproperty` + assert.

Clock/reset for all 3 idioms reuse EXISTING manifest fields (`m.get('clocks')`/`m.get('resets')`) — no new field.

**Wiring point 1** (`generator.py`): new method `UVMEnvironmentGenerator.assertions(self, m, p)` alongside `scoreboard()`/`coverage()`, reading `m.get('state_machine_checks')`, calling `state_machine_checks.emit_check(entry, clk, rst)` per opted-in entry, splicing after a placeholder comment identical to `scoreboard()`'s `_emit_scoreboard_check` splice technique. Wired into `generate()`'s `files` dict as `files[p+'_assertions.sv']=self.assertions(m,p)` and into `pkg()`'s include list.

**Wiring point 2** (`generate_observability_plan.py`): ASSERTION branch extended additively — if `recommended_mechanism` dict carries opt-in key `"state_machine_check"`, call `state_machine_checks.emit_check(...)` and write real output instead of TODO; a `"generation_method"` field (`"state_machine_checks_dsl:<kind>"` or `"placeholder"`) added to each entry recorded in `implementation_manifest.json`. Absent the opt-in key, output is byte-identical to today.

**Gate addition** (small, same convention as existing gate scripts): new `assertion_placeholder_closure_gate.py` (argparse `--implementation`, load `implementation_manifest.json`) that FAILs if any assertion entry classified as "protocol-state-machine legality" still shows `"generation_method":"placeholder"`. Reuses `observability_sufficiency_gate.py`'s exact file shape. Sits in STAGE_GATES["VERIFICATION_ARCHITECTURE"] or ["IMPLEMENT"] (exact stage: implementer's ruling call — pick VERIFICATION_ARCHITECTURE since that's where `observability_sufficiency_gate.py` already lives, keeping the two adjacent).

Existing `assertion_vacuity_gate.py`/`assertion_vacuity_and_reachability_gate.py` need NO change.

## Scope boundary

**IN SCOPE**: (1) new `dv_harness/uvm_generator/state_machine_checks.py` with `StateMachineCheckError` + validation + emission for exactly the 3 named idioms. (2) `UVMEnvironmentGenerator.assertions()` in `generator.py`, wired into `generate()`/`pkg()`, backward-compatible no-op on absent/empty key. (3) additive `"state_machine_check"` opt-in on `generate_observability_plan.py`'s ASSERTION branch + `generation_method` field on `implementation_manifest.json`. (4) the 3-question decision-procedure text with this exact worked example, written into semantic-checker-planner/assertion-placement-planner/scoreboard-checker-assertion-analyzer SKILL.md files. (5) `dv_harness_tests/test_state_machine_checks.py` mirroring `test_pcie_ltssm_generator.py`'s style (pure-function tests: legal/illegal transition cases, onehot/onehot0 validation, unknown-state refusal, missing-evidence refusal) plus a generator.py integration test (with/without `state_machine_checks` → byte-identical-vs-extended). (6) `assertion_placeholder_closure_gate.py`, wired into STAGE_GATES["VERIFICATION_ARCHITECTURE"].

**OUT OF SCOPE**: INTERRUPT/RESPONSE SEMANTIC requirements (Q2-YES) — stay hand-authored; CHECKER branch's generic TODO comment is replaced with a non-boilerplate REQUIRED-FIELD SCAFFOLD (`arm_event`, `correlation_key`, `response_window`, `window_evidence`) emitted as structured comments the agent must fill from real evidence — already enforceable by the existing, wired `checker_semantic_trace_consistency_gate.py` (VERIFY stage), no new gate needed. CROSS-CYCLE TEMPORAL INVARIANTS (Q3) — not fully schema'd this pass (no existing generator to ground against); flag as a follow-up. No change to `coverage_analysis.py`, `address_map_verifier.py`, or existing assertion_vacuity*/checker_semantic_trace gates' internal logic.

## Open questions (resolve via implementer ruling if not answered — document the ruling in the commit)

1. Manifest key naming: new top-level `state_machine_checks` key (proposed, use this) vs. folding into `scoreboard_rules`'s discriminator space.
2. First real target protocol for real (non-illustrative) manifest entries — deferred; ship with the 3 idioms proven only via unit tests + one illustrative example manifest (state clearly that it's illustrative, not from a real target project).
3. New gate script (`assertion_placeholder_closure_gate.py`) vs. folding into `observability_sufficiency_gate.py` — ruling: build as a NEW gate script (cleaner separation, lower risk of regressing the existing gate).
4. Which STAGE_GATES stage hosts the new gate — ruling: STAGE_GATES["VERIFICATION_ARCHITECTURE"], same stage as `observability_sufficiency_gate.py`.
5. Interrupt/response checker scaffold required-field set — ruling: use `{arm_event, correlation_key, response_window, window_evidence}` as proposed (no existing repo convention contradicts it).

## Estimated task count

5-7 tasks.
