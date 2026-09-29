# Implementation Report: Checker/SVA Generator (state_machine_checks DSL)

## What was built

This closes the gap in `.work/checker-sva-generator-design-report.md`: every
ASSERTION-classified requirement previously compiled to a literal,
unconditional `1'b1; // TODO: replace with evidence-backed temporal
property` (`tools/observability/generate_observability_plan.py`'s ASSERTION
branch) with zero real generation mechanics.

1. **New module `dv_harness/uvm_generator/state_machine_checks.py`** --
   `StateMachineCheckError(ValueError)` (SCREAMING_SNAKE_CASE `reason` +
   `detail` dict, same convention as `generator.py`'s other typed errors)
   plus a pure `emit_check(entry, clk, rst)` implementing the 3 idioms the
   design specified: `valid_transition_table` (generalizes
   `pcie_ltssm_generator.py`'s hardcoded `LTSSM_TRANSITIONS` ->
   `ltssm_transition_legal` case-statement pattern to any manifest-supplied
   state/transition table), `mutual_exclusion` (`$onehot`/`$onehot0`,
   generalizing the real but previously-unimplemented CAN-FD
   single-winner-arbitration fact), and `legal_value_set` (the degenerate,
   no-history idiom). Every entry requires non-empty `assertion_name`,
   `kind`, and `evidence`; every compiled assert label is
   `<sv_id(assertion_name)>_a`, so `assertion_id == sv_id(assertion_name)`
   always holds for the already-wired, unmodified
   `assertion_vacuity_gate.py`/`assertion_vacuity_and_reachability_gate.py`.

2. **`UVMEnvironmentGenerator.assertions(self, m, p)`** in `generator.py`,
   wired into `generate()`'s `files` dict and `pkg()`'s include list (a new
   `<p>_assertions.sv` file, always emitted -- placeholder-only when
   `state_machine_checks` is absent/empty, mirroring `scoreboard()`/
   `coverage()`'s own always-emitted-file-with-placeholder-body shape).
   Reuses the generator's existing `clocks`/`resets` manifest fields (no new
   per-check clock/reset field). Also wired into `ProtocolEnvGenerator`
   (`protocol_env_generator.py`) -- the real, non-deprecated generation
   entry point -- so the capability is reachable outside the deprecated flat
   `generate()` path too (see Ruling 6 below).

3. **`generate_observability_plan.py`'s ASSERTION branch** extended
   additively: a `recommended_mechanisms[]` entry carrying an opt-in
   `"state_machine_check"` key now compiles through `emit_check()` into real
   SV instead of the TODO placeholder. A new `"assertion_entries"` array in
   `implementation_manifest.json` records, per target,
   `generation_method` (`"state_machine_checks_dsl:<kind>"` or
   `"placeholder"`) and the propagated `"classification"` field (see
   Ruling 3). Absent the opt-in key, output is byte-identical to before.

4. **The 3-question decision procedure**, with the exact worked examples
   from the design report, written verbatim into all three OBSERVABILITY
   planner SKILL.md files (`semantic-checker-planner`,
   `assertion-placement-planner`, `scoreboard-checker-assertion-analyzer`),
   per the Methodology Consolidation Rule's "same worked example in all
   three" requirement.

5. **`tools/verification_flow/assertion_placeholder_closure_gate.py`**,
   mirroring `observability_sufficiency_gate.py`'s file shape, wired into
   `dv_harness/gates.py`'s `STAGE_GATES["VERIFICATION_ARCHITECTURE"]`
   (adjacent to `observability_sufficiency_gate`, per the design's own
   ruling). It reads `implementation_manifest.json`'s `assertion_entries`
   and FAILs only when an entry classified `PROTOCOL_STATE_MACHINE_LEGALITY`
   still shows `generation_method: "placeholder"` -- a deliberately narrow
   check, leaving Q2/Q3/hand-authored assertions untouched. Also registered
   in `.dv-harness/workflow/hard_gate_registry.json` and
   `verification_flow_v13.json`, and added to
   `dv_harness_tests/test_hard_gate_script_smoke.py`'s
   `ALL_GATE_TOOL_FILES`, to keep the existing
   `gate_manifest_registry_consistency_gate.py`/`hard_gate_registry_audit.py`
   self-checks passing (they were clean before this change and remain
   clean after -- verified both ways).

6. **Tests**: `dv_harness_tests/test_state_machine_checks.py` (29 tests --
   per-idiom legal/illegal compiled-output cases, every typed-error branch,
   plus a `generator.py` integration section proving `assertions()` is
   byte-identical when the key is absent/empty and correctly extends when
   present, including a duplicate-`assertion_name` refusal),
   `dv_harness_tests/test_generate_observability_plan_assertions.py` (4
   tests -- backward-compat TODO text, DSL opt-in compiling real SV,
   plan-level clocks/resets reuse, a mixed plan), and
   `dv_harness_tests/test_assertion_placeholder_closure_gate.py` (7 tests --
   PASS/FAIL matrix over classification x generation_method).

## Rulings made (design gaps resolved during implementation)

1. **`state_type` field (not in the design's field list, but its own
   compiled-code sketch needs one)**: added as an OPTIONAL
   `valid_transition_table` field, default `"logic [31:0]"` -- a
   deliberately generic default consistent with this package's other
   generic-type defaults (`_emit_scoreboard_check`'s plain `int`/`bit[N:0]`
   defaults). A manifest targeting a real protocol with an already-declared
   enum type sets it explicitly.
2. **`on_violation.message_template` default arg-count mismatch**: the
   design's literal default text (`"%s: illegal value/transition
   observed"`, one `%s`) doesn't match the 2-arg `$sformatf` call its own
   `valid_transition_table` sketch shows. Kept the literal default text
   verbatim and relied on IEEE 1800's defined behavior that `$sformatf`
   silently ignores excess positional arguments beyond consumed format
   specifiers (not a compile or runtime error) -- the same accepted
   tradeoff `generator.py`'s own `scoreboard()` docstring already documents
   for its own message_template argument-count contract.
3. **`mutual_exclusion`/`legal_value_set` `$sformatf` argument list** (not
   spelled out in the design, only `valid_transition_table`'s is):
   `mutual_exclusion` passes the concatenated signal-group expression
   (`{sig1,sig2,...}`); `legal_value_set` passes the `value_signal`
   expression. Both play the same "value that violated the property" role
   `$past(state_signal)`/`state_signal` play for `valid_transition_table`.
4. **`INVALID_TRANSITIONS_MAP` reason code** (design lists
   `UNKNOWN_TRANSITION_SOURCE_STATE`/`UNKNOWN_TRANSITION_TARGET_STATE` for a
   malformed individual transition, but no code for `"transitions"` itself
   being absent/not-a-dict): added this one extra SCREAMING_SNAKE_CASE
   reason code to close that one gap without silently guessing an empty
   table were legal.
5. **`"classification"` field on `recommended_mechanisms[]` entries** (the
   design's field list for `implementation_manifest.json` only names
   `"generation_method"`, but `assertion_placeholder_closure_gate.py`'s
   assigned job -- "FAILs if any assertion entry classified as
   'protocol-state-machine legality' still shows placeholder" -- has no
   other data source to check against): added `"classification"` as an
   optional field the planner skill's own 3-question procedure sets
   (`PROTOCOL_STATE_MACHINE_LEGALITY` / `INTERRUPT_RESPONSE_SEMANTIC` /
   `CROSS_CYCLE_TEMPORAL_INVARIANT` / `OTHER_HAND_AUTHORED`), propagated
   verbatim into `implementation_manifest.json`. Documented in the SKILL.md
   files and in `generate_observability_plan.py`'s own header comment.
6. **`ProtocolEnvGenerator` wiring (beyond the design's literal IN SCOPE
   item 2, which only names `generator.py`'s own `generate()`/`pkg()`)**:
   wired `assertions()` into `protocol_env_generator.py` too, since that is
   the actual non-deprecated generation entry point per `generator.py`'s own
   header NOTICE -- omitting it would leave the new DSL unreachable from
   real environment generation, undermining the point of building it. Low
   risk (one line, reusing the unchanged `assertions()` method, verified
   against the existing `test_protocol_env_generator.py` suite with no
   assertions changed).
7. **CHECKER branch's REQUIRED-FIELD SCAFFOLD** (mentioned in the design
   report's prose, but filed under its "OUT OF SCOPE" section, and absent
   from the IN SCOPE numbered list of 1-6 items): treated as genuinely out
   of scope for this pass per the task's explicit instruction to implement
   "everything in the design's scope_boundary IN SCOPE list" -- left
   `generate_observability_plan.py`'s CHECKER branch completely untouched.
   This is a residual gap the design report itself flags as future work,
   not something silently dropped.
8. **Gate registry bookkeeping** (`hard_gate_registry.json`,
   `verification_flow_v13.json`, `test_hard_gate_script_smoke.py`'s
   `ALL_GATE_TOOL_FILES`): not mentioned by the design report at all, but
   required to avoid regressing `gate_manifest_registry_consistency_gate.py`
   (confirmed by running it before and after: PASS both times) and the
   drift-guard test `test_gate_tool_list_matches_registry`.
9. **Circular import** between `generator.py` and `state_machine_checks.py`
   (the latter needs `sv_id` from the former, per the same import shape
   `pcie_ltssm_generator.py` already uses; the former needs the latter's
   `emit_check`): resolved by placing `generator.py`'s
   `from . import state_machine_checks` textually AFTER `sv_id`'s own
   definition, relying on Python's partial-module-import semantics (safe
   here since nothing at `state_machine_checks.py`'s own module level calls
   `sv_id()` -- it's only referenced inside function bodies, which run
   later). Verified working via the full test run below.

## Tests run

- New tests: `test_state_machine_checks.py` (29 passed),
  `test_generate_observability_plan_assertions.py` (4 passed),
  `test_assertion_placeholder_closure_gate.py` (7 passed) -- all passing in
  isolation.
- Full existing suite: `python -m pytest dv_harness_tests/ -q` ->
  **1331 passed** in ~12 minutes, zero regressions (this count includes all
  40 new tests above).
- Manually re-verified `tools/verification_flow/gate_manifest_registry_consistency_gate.py --root .`
  and `tools/verification_flow/hard_gate_registry_audit.py --root .` both
  PASS before and after this change (no new drift introduced).

## Concerns / residual gaps

- The CROSS_CYCLE_TEMPORAL_INVARIANT (Q3) idiom remains explicitly
  unimplemented, per the design report's own scope boundary (no existing
  bounded-latency/stability generator to ground it against) -- flagged as
  future work in the SKILL.md text, not attempted here.
- INTERRUPT_RESPONSE_SEMANTIC (Q2) requirements and the CHECKER branch
  remain fully hand-authored; the REQUIRED-FIELD SCAFFOLD improvement the
  design report's prose mentions for the CHECKER branch was left out per
  Ruling 7 above (it sits under "OUT OF SCOPE" in the design text, outside
  the numbered IN SCOPE list this task was told to implement).
- `verification_flow_v13.json`/`hard_gate_registry.json` are informal,
  independently-maintained catalogs (confirmed via `test_engine_gates_and_routing.py`'s
  own comment that this consistency gate has genuinely drifted before in
  this repo's history); I kept them in sync for this one new gate, but this
  is a manually-maintained convention, not something either script
  automatically derives from `STAGE_GATES`.
- The `state_machine_checks` DSL's only real-protocol precedent is
  `pcie_ltssm_generator.py`'s own PCIe LTSSM table; per the design's own
  "deferred, not silently dropped" note, no manifest wires a real (non-test,
  non-illustrative) `state_machine_checks`/`state_machine_check` entry yet
  -- the design explicitly scoped shipping with unit-test + illustrative
  coverage only for this pass.

## Files touched

- New: `dv_harness/uvm_generator/state_machine_checks.py`,
  `tools/verification_flow/assertion_placeholder_closure_gate.py`,
  `dv_harness_tests/test_state_machine_checks.py`,
  `dv_harness_tests/test_generate_observability_plan_assertions.py`,
  `dv_harness_tests/test_assertion_placeholder_closure_gate.py`.
- Modified: `dv_harness/uvm_generator/generator.py`,
  `dv_harness/uvm_generator/protocol_env_generator.py`,
  `tools/observability/generate_observability_plan.py`, `dv_harness/gates.py`,
  `.claude/skills/OBSERVABILITY/{semantic-checker-planner,
  assertion-placement-planner,scoreboard-checker-assertion-analyzer}/SKILL.md`,
  `.dv-harness/workflow/hard_gate_registry.json`,
  `.dv-harness/workflow/verification_flow_v13.json`,
  `dv_harness_tests/test_hard_gate_script_smoke.py`,
  `dv_harness_tests/test_engine_gates_and_routing.py` (added a passing
  evidence block for the new gate to `_VERIFICATION_ARCHITECTURE_EXTRA_GATES`
  so existing `VERIFICATION_ARCHITECTURE` stage-evidence tests keep passing
  now that the stage has one more gate).
