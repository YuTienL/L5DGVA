# Route/Skill Resolver Dynamic Implementation Report

## What was built

Two new, real, callable resolver modules and one new gate close the gap the
2026-09-01 AI-mechanism architecture audit confirmed: `dv_harness/router.py`'s
`RouteResolver` and `dv_harness/skill_resolver.py`'s `SkillResolver` are real
callers, but only ever do a **static** dict lookup on the graph node's own
pre-declared `route`/`agent`/`skills` fields -- the same answer every time a
given Stage runs, no matter what protocol/failure/evidence the run actually
has. The genuinely input-driven rules only ever existed as prose.

**`dv_harness/protocol_router.py`** -- `resolve_protocol(evidence: dict) -> dict`.
Transcribes `.claude/skills/CORE/protocol-router/SKILL.md`'s real primary-route
table, normalization aliases (USB3/SuperSpeed/SS, PCI Express, CSI2/CSI-2,
CANFD/CAN FD, AMAB4/AIX4 typo-corrections, AXIS/AXI Stream, MMC, SDIO, plus
AMBA's own further-resolution vocabulary AXI3/AXI4/APB2-4/AHB-Lite/ACE-Lite
pulled from the real `protocol_builder_registry.json` discover list) and
tie-break order (`user intent -> failing test -> active config -> modified
files -> subsystem boundary`, mapped 1:1 onto evidence-dict keys
`protocol_hint`/`failing_test_name`/`active_config`/`modified_files`/
`subsystem_boundary`) into real code. It also implements the one rule that
isn't a simple lookup: "Do not make AMBA the primary protocol merely because
another DUT uses an AXI/APB backend" (AMBA is dropped from a field's candidate
set whenever another protocol also matched in that same field). An unresolved
input returns a structured result rather than raising, mirroring
`RouteResolver`/`SkillResolver`'s own never-raise contract.

**`dv_harness/environment_mode_router.py`** -- `resolve_environment_mode(evidence: dict) -> dict`
computes SUBSYSTEM_MODE vs SYSTEM_LEVEL_MODE from `requested_subsystems`
(what this run wants) and `existing_registered_subsystems` (read from the
real runtime registry via `read_registered_subsystem_names()`, never the
empty `subsystem_environment_registry_template.json`), applying CLAUDE.md's
"Environment Generation Mode" rules verbatim: one requested subsystem ->
SUBSYSTEM_MODE; two or more -> SYSTEM_LEVEL_MODE; a SYSTEM_LEVEL_MODE request
naming a subsystem missing from the registry surfaces
`needs_subsystem_mode_first`/`missing_subsystems` (CLAUDE.md: "build it
through SUBSYSTEM_MODE then return to composition"); zero requested
subsystems is an explicit unresolved result, not a guessed default
(`environment_mode_policy.json`'s `mode_must_be_explicit_before_generation`).

**`tools/verification_flow/environment_mode_selection_gate.py`** -- a new
STAGE_GATES-registered check (wired into `PROJECT_MODEL`, alongside the
existing `project_model_topology_completeness_gate`) that finally gives the
`environment_mode_selection` evidence block dashboard.py's own
`_environment_mode_selected()` docstring documented as having "no stage, no
gate, no writer" a real producer and a real verifier. It independently
re-derives SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE from the agent's declared
`requested_subsystems` plus the real subsystem registry (read relative to its
own subprocess `cwd`, which `gates.run_gate()` always sets to the real
project root -- the same trust boundary a `ContextFlag` would give it,
without needing one), and FAILs/CONFLICTs if the agent's declared
`environment_mode` disagrees.

**Engine wiring** (`dv_harness/engine.py`): `run_stage()` now calls
`resolve_protocol()` and `resolve_environment_mode()` right alongside the
existing `self.router.resolve(node)` / `self.skills.resolve(node.skills)`
calls, feeding real per-run evidence built from genuinely available sources:
`user_goal` text (protocol_hint), the real INTAKE-written `"project"`
Blackboard topic's `protocols`/`selected_subsystems` fields
(`subsystem_boundary`, `requested_subsystems`), the real `"verify"`
Blackboard topic's `verification_state.results` (`failing_test_name` --
first non-PASS `testcase_id`), a real `git diff --name-only HEAD`
(`modified_files`), and the real subsystem registry file
(`existing_registered_subsystems`). Both decisions are folded into
`route_info["protocol_decision"]`/`route_info["environment_mode_decision"]`,
which `_build_plan_section()` already renders into the prompt sent to the
LLM -- genuinely load-bearing, not a disconnected module.

`prompts.py`'s PROJECT_MODEL instructions now tell the agent to echo the
harness's own pre-computed environment-mode decision back as a real
`environment_mode_selection` evidence block. `dashboard.py`'s
`_environment_mode_selected()` docstring and the dashboard HTML's "Environment
Mode Router" card note (both of which explicitly documented the gap as still
open) are updated to reflect that it is now closed -- comment hygiene per
CLAUDE.md.

## Rulings made

1. **`active_config` has no real backing source in this engine.** No
   `config.json`/`state.json` field records a per-run "active build config"
   anywhere in this codebase today. RULING: leave it explicitly `None` in
   `engine.py`'s evidence-building rather than repurpose an ill-fitting field
   (e.g. a VERIFY result's `config_hash`) or fabricate one. `resolve_protocol()`
   is documented and tested to work correctly with this field always absent.

2. **Regex boundary must NOT be plain `\b`.** Python's `\b` treats `_` as a
   word character, so `\busb\b` never matches inside a realistic snake_case
   `failing_test_name` (`test_pcie_link_train`) or `modified_files` path
   (`usb_host_controller.sv`) -- exactly the two fields most likely to BE
   snake_case. RULING: use an alnum-only boundary
   (`(?<![A-Za-z0-9])...(?![A-Za-z0-9])`) so `_`/`-`/`.`/`/` act as valid
   separators, while still preventing `usb` from firing inside `usb2` (kept
   as its own explicit alias, matching the real registry's own "USB2/USB3
   mode" wording) or `SS` from firing inside an unrelated word.

3. **`environment_mode_selection_gate` placed in `PROJECT_MODEL`.** CLAUDE.md
   says "Before CREATE ENVIRONMENT, select: SUBSYSTEM_MODE / SYSTEM_LEVEL_MODE"
   with no stage named. RULING: PROJECT_MODEL, since it already establishes
   `verification_boundary`/topology (the existing
   `project_model_topology_completeness_gate`) and sits one stage before
   PROTOCOL_CAPABILITY's per-protocol discovery -- the natural point to also
   fix the project's overall shape (single subsystem vs. full-SoC) before
   protocol-specific work begins.

4. **Gate re-derives the rule independently instead of importing
   `environment_mode_router`.** A subprocess gate script that imported
   `dv_harness.environment_mode_router` via the `sys.path.insert(0,
   parents[2])` trick a few older gates use (e.g.
   `qualification_matrix_consistency_gate.py`) silently breaks the moment
   it's copied standalone into a temp test-fixture project without a full
   `dv_harness/` package alongside it. RULING: keep the gate script
   self-contained (same "derive independently, compare against the agent's
   declared value" discipline `execution_mode_validator.py` already uses for
   PURE_LOCAL_READ_ANALYSIS vs REMOTE_EXECUTION_REQUIRED) -- the REAL
   `resolve_environment_mode()` function is exercised in-process by
   `engine.py` (never subprocessed) and by its own dedicated unit tests.

5. **Gate is single-flag, not a `ContextFlag`-carrying multi-flag gate, and
   its `gate_id` is `"environment_mode_selection"` (not `"..._gate"`, unlike
   every other STAGE_GATES entry where `gate_id` == script filename stem).**
   `dashboard.py`'s pre-existing `_environment_mode_selected()` reads
   `payload.get("environment_mode")` directly off a block keyed exactly
   `"environment_mode_selection"`, with no sub-key nesting -- a multi-flag
   gate's evidence body is `{key: subpayload}` (the established convention
   for e.g. `spec_rtl_change_impact_gate`'s `{"impact": {...}}`), which would
   have broken that pre-existing, unrelated consumer. RULING: keep the
   evidence block flat and single-flag; read the real registry relative to
   the gate script's own subprocess `cwd` (harness-controlled via
   `gates.run_gate()`, never agent-attested) instead of a `ContextFlag`.

6. **Resolvers never raise on an unresolved input; they return a structured
   `{"resolved": False, ...}` result.** Matches `RouteResolver.resolve()`/
   `SkillResolver.resolve()`'s own never-raise contract (the two modules
   these sit alongside), not `uvm_generator.py`'s typed-`ValueError` manifest-
   schema-validator convention -- a best-effort detector over uncertain
   free-text evidence is a different kind of contract than a manifest that is
   supposed to already be well-formed. Every return still carries a
   mandatory, non-empty `"evidence"` string, matching that same discipline.

7. **`subsystem_boundary` evidence is the real INTAKE-written `"project"`
   Blackboard topic's `protocols`/`selected_subsystems`, never the graph
   node's own `route` field.** `node.route` (e.g. `"build-route"`) is a
   *workflow* routing category, unrelated to a DUT's protocol/subsystem
   scope; using it would have been actively misleading under the
   `subsystem_boundary` name rather than merely unhelpful.

## Tests and results

New test files (all passing):
- `dv_harness_tests/test_protocol_router.py` (18 tests) -- normalization
  aliases, tie-break order, the AMBA-deprioritization rule, unresolved cases,
  and the crux test (`test_two_structurally_different_evidence_dicts_pick_different_real_routes`):
  USB vs. PCIe `protocol_hint` evidence resolves to two different real
  `PRIMARY_ROUTES` entries from the same function.
- `dv_harness_tests/test_environment_mode_router.py` (8 tests) -- single vs.
  multi-subsystem requests picking different real modes, missing-subsystem
  escalation, unresolved-with-no-input, and real registry-file reading.
- `dv_harness_tests/test_environment_mode_selection_gate.py` (9 tests) --
  subprocess-level PASS/CONFLICT/FAIL cases against the real script, with an
  explicit `cwd` since the gate's whole point is reading the registry
  relative to it.
- `dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py`
  (3 tests) -- the engine-integration crux tests, mirroring
  `test_react_loop.py`'s own two-different-real-inputs shape: two different
  real `user_goal` strings produce two different real `protocol_decision`
  values in the actual prompt sent to the adapter; two different real
  INTAKE-shaped Blackboard subsystem counts produce two different real
  `environment_mode_decision` values; and a full `PROJECT_MODEL` run now
  makes `dashboard._environment_mode_selected()` return a real value where it
  previously always returned `None` (asserted both before and after the
  stage runs, as a genuine before/after proof).

One pre-existing test needed updating because adding a second mandatory gate
to an already-gated stage is expected to require it (same pattern as every
prior STAGE_GATES addition in this codebase's own history):
`test_project_model_requires_topology_completeness` in
`test_engine_gates_and_routing.py` asserted PASS/PASS for two payloads that
now also need a passing `environment_mode_selection` block; both were given
one (`{"environment_mode": "SUBSYSTEM_MODE", "requested_subsystems": ["usb"]}`).
The two `PROJECT_MODEL` tests in the same file that promote Project Memory on
PASS were updated the same way. No other pre-existing test needed a change --
notably, `test_dashboard_interactive.py`'s multi-stage `loop()` test (which
drives every stage through PROMOTION_READINESS with only `"fine"` as adapter
text, so `PROJECT_MODEL` was already failing its one existing gate and
advancing via the graph's FAIL-edge path) required no change, since a second
simultaneously-failing gate doesn't change that qualitative outcome.

Full results:
- `dv_harness_tests/test_engine_gates_and_routing.py`: 188 passed (after the
  fixture update above).
- `dv_harness_tests/test_react_loop.py`, `test_skill_resolver.py`,
  `test_dashboard_interactive.py`, `test_qualification.py`, plus all four new
  test files together: 138 passed.
- `dv_harness_tests/test_dashboard_interactive.py` alone (re-run after a
  second, comment-only dashboard.py edit): 54 passed.
- `dv_harness_tests/test_hard_gate_script_smoke.py` (the `--help` smoke
  contract over all 169 previously-registered hard-gate scripts, unrelated
  to but adjacent to the new gate): 177 passed.
- A whole-`dv_harness_tests/` background sweep (81 files) was also started
  as an extra backstop; it was still running after ~10 minutes (this
  repo's suite is large and subprocess-heavy) when this report was
  finalized and was not blocked on, since every file that imports or
  exercises any module this task touched (router.py, skill_resolver.py,
  gates.py, engine.py, prompts.py, dashboard.py) was already independently
  confirmed above at 100% pass -- the remaining untested files (protocol
  UVM generators, coverage analysis, LSF client, memory tiers, etc.) have
  zero import/call relationship to any file this task changed.

No pre-existing bug was found in the modules this task touched (the one test
update above was an expected consequence of a new mandatory gate, not a bug
fix).

## Residual gaps / concerns

- `active_config` (ruling 1 above) has no real per-run source anywhere in
  this engine; a future stage that introduces one should populate it in
  `DVHarness._protocol_router_evidence()` rather than leave it `None`
  forever.
- `resolve_environment_mode()`'s subsystem-name matching is case-insensitive
  exact string comparison, not alias-normalized through
  `protocol_router`'s canonical keys -- the real subsystem registry's `name`
  field has no documented normalization convention to match against, so
  exact-after-casefold was chosen as the least-invented option. If the real
  registry later standardizes on `protocol_builder_registry.json`'s lowercase
  keys, this comparison could be tightened to reuse `protocol_router`'s
  alias table.
- `environment_mode_selection_gate.py` and `resolve_environment_mode()` both
  encode the "1 subsystem -> SUBSYSTEM_MODE, 2+ -> SYSTEM_LEVEL_MODE" rule
  (ruling 4: deliberately not shared code, for gate-script robustness). A
  future change to that rule must be applied in both places; this is called
  out in both files' headers.
