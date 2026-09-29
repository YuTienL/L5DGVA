# Gap close: SPEC-4 -- VIPApiCard evidence-gated artifact + "unprovable API -> BLOCKED" (spec section 187)

**Status: DONE**
**Tests: 26 new tests in `dv_harness_tests/test_vip_api_card.py` -- all pass; regression suites
`test_asset_processing_artifacts.py`, `test_uvm_structural_lint.py`,
`test_system_level_soc_composition_wiring.py`, `test_environment_mode_router.py` (142 passed) and
`test_protocol_model_layer_wiring.py`, `test_system_level_track_b_gate_crosscheck.py` (+ this file,
81 passed) all pass.**
**Commit: `1b9064f`.**

## 1. Gap independently re-verified before building

- `grep -rn "VIPApiCard\|vip_api_card\|validate_vip_api_usage\|UNPROVABLE" --include=*.py --include=*.md .`
  -> **no output**. No artifact, no validator, no mention anywhere in code or docs.
- Section 187 of `CLAUDE_DV_Agent_Harness_L5_SPEC_TO_SYSTEM_UVM_COMPLETE.md` (line 6249) really
  states the flow `Need Operation -> Search VIP Example -> Manual / Source / Class Reference ->
  Extract Exact API -> Validate Signature -> VIPApiCard -> Generate Sequence` and the stop
  condition `If API cannot be proven: UNKNOWN / BLOCKED`.
- The only carrier of that rule was prose: `.claude/skills/CORE/vip-scenario-branch/SKILL.md:38`
  (`禁止憑猜測 invent VIP API/class/sequence。`) plus the same ladder at lines 30-36, and the same
  wording in `pcie-environment-builder`.
- `dv_harness/vip_symbol_index.py` was confirmed to be the closest real cousin and confirmed NOT to
  validate: its consumer function is `find_symbol()` (case-insensitive substring -> `file:line`, a
  navigation aid by its own docstring), and its only non-test importer is
  `dv_harness/amba_scoreboard_env.py`, which reuses `index_source_text()`/`iter_source_files()` for
  scoreboard discovery, never for call validation.
- Confirmed on real generator output that the gap is live: `examples/generated_usb_real_evidence_v12/
  tb/seq/usb_base_vseq.sv` calls `l_agent.reconfigure(cfg)`, `xfer.fix_anchors(0,0,0)`,
  `xfer.get_setup_data_w_value_val()` etc. with nothing in the repo capable of checking any of them.

## 2. What was built

### `dv_harness/vip_api_card.py` (new, 766 lines)

Reuses `vip_symbol_index` rather than rebuilding it -- `index_source_text()` is imported and used
for BOTH halves: reading the real VIP index, and discovering the classes the validated sources
declare themselves. There is no second SystemVerilog scanner.

- **`VipApiCard`** -- the section 187 artifact. One record per citation: `citation`, `kind`
  (CLASS / METHOD / SCOPE_CLASS), `vip_class`, `member`, `status`, the generated-code
  `usage_file:usage_line` + the actual source line, the REAL `resolved_file`/`resolved_line`/
  `resolved_signature`/`resolved_kind` the index resolved it to, `declared_by` (the class in the
  inheritance chain that really declares it), `inheritance_chain`, `chain_closed`, and a
  SCREAMING_SNAKE_CASE `reason` on every non-PROVEN card.
- **`validate_vip_api_usage(sources, index, ...)`** -- the check. Schema-validates the index (a
  hand-made dict cannot pass as one), derives the VIP naming scope from the index itself, extracts
  citations, resolves each through the real inheritance chain, returns a
  `VipApiValidationReport` whose `status` is BLOCKED / UNPROVABLE / PROVEN / NOT_AVAILABLE.
- **Four statuses**, with `BLOCKED` deliberately narrow (four conjunctive conditions -- see the
  module docstring and the new CLAUDE.md section). `UNPROVABLE` is section 187's UNKNOWN and is
  never a silent pass. `OUT_OF_SCOPE` covers locally-declared classes, base-library methods and
  unresolvable receivers and is never blocked.
- **`derive_vip_scope_prefixes()`** -- the VIP naming scope is derived from the real index, never
  hardcoded. Nothing in the module knows the string `svt`.
- `format_report()`, `write_vip_api_cards()` (deterministic, no timestamp), `load_index()`,
  `execute_verb()`, `main()`.

### `dv_harness/uvm_generator/create_environment.py` (wired)

`_run_vip_api_validation()` runs in BOTH modes at the same point `_run_structural_lint()` does --
the last point before a generated environment leaves for a compile. It runs only when the manifest
carries `vip_symbol_index: <path>` (a deliberate opt-in: the index must be an index of the VIP this
environment actually binds). Returns `vip_api_validation` on the result, writes
`<out_dir>/vip_api_cards.json`. **Non-blocking by default** (same convention as
`StructuralLintFailedError`); `"strict_vip_api": true` raises the new `VipApiUnprovableError`.
A missing/unreadable index reports `NOT_AVAILABLE` with a real reason -- never PROVEN.

### `dv_harness/cli.py` (new verb)

`dv-harness vip-api-check --source <file|dir> --index <vip_symbol_index.json> [--relative-to]
[--out-dir] [--strict-unprovable] [--json]`, sharing one implementation with
`python -m dv_harness.vip_api_card` (the same `execute_verb` convention `power-intent` /
`golden-scenario` / `config-variants` use). Exit 0 PROVEN, 1 BLOCKED, 2 NOT_AVAILABLE,
3 UNPROVABLE (non-fatal unless `--strict-unprovable`).

### Docs

- `CLAUDE.md`: new "VIP API Card / Unprovable-API BLOCKED (2026-09-06)" section, including the
  six explicitly disclosed bounds.
- `.claude/skills/CORE/vip-scenario-branch/SKILL.md`: the prose rule now points at the real coded
  enforcement, and states explicitly that a VIPApiCard proves DECLARATION only, not semantics --
  the example/manual/source/class-reference ladder is still required for meaning.

## 3. Tests (`dv_harness_tests/test_vip_api_card.py`, 26 tests)

Same discipline as `test_power_intent.py` / `test_uvm_structural_lint.py`.

- Inputs are REAL: the index is built by the REAL `vsi.build_symbol_index()` over
  `examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv` (this repo's existing synthetic VIP
  source, which is explicitly not vendor code), and the clean generated sequence is a new fixture
  `dv_harness_tests/fixtures/vip_api/demo_env_seq.sv` whose every citation is really declared there.
- **Clean baseline all-PROVEN**, and every PROVEN card's `resolved_line` is asserted to be a line
  in the real VIP source that actually declares that symbol (not merely non-null). Signature and
  kind are asserted verbatim (`apply_preset` -> `function`, `(input int preset_id)`,
  `vip_src/svt_demo_pkg.sv:26`).
- **Every rule driven by mutating that one clean source**: fabricated method name -> BLOCKED
  `METHOD_NOT_DECLARED_IN_INDEXED_VIP_CHAIN`; fabricated class name -> BLOCKED
  `VIP_CLASS_NOT_IN_SYMBOL_INDEX`; a real method called on the WRONG class -> BLOCKED (while the
  same name still resolves on the class that declares it); fabricated `Class::` scope -> BLOCKED.
- **False-positive directions tested separately**: base-library method on a VIP handle, a class the
  validated sources declare themselves, an unresolvable receiver, fabricated names inside block
  comments / line comments / string literals, an OPEN inheritance chain (UNPROVABLE, with the SAME
  index blocking the same fabrication on a closed-chain class -- proving the difference is the
  chain, not the name), and `examples/generated_pcie_uvm_env/` (a real environment this project's
  generator produced) reporting zero BLOCKED and zero UNPROVABLE against an unrelated VIP's index.
- **"Could not check" is never a pass**: missing index raises, empty index -> NOT_AVAILABLE,
  missing source root raises.
- **Real entry points end to end**: the real `create_environment()` SUBSYSTEM_MODE dispatch,
  `_run_vip_api_validation()` with/without a declared index, with a mistyped index, non-blocking
  default vs. `strict_vip_api` raise, plus `python -m dv_harness.vip_api_card` and
  `dv-harness vip-api-check` as REAL subprocesses with asserted exit codes (0/1/2/3) and asserted
  artifact contents.

## 4. Constraints honoured

- **No human-approval gate weakened.** This module raises no approval, grants none, and imports
  none. It runs nothing, builds nothing, submits nothing. SYS-39/40's stop boundary and the
  active-driver-conflict human-arbitration requirement were not touched (this pass touched no
  `system_*` module, no gate script, no `gates.py`, no `engine.py`).
- **No production build/regression/LSF.** Every test runs against synthetic/local fixtures and
  `tmp_path`. The only real environments read are this repo's own committed `examples/` (read-only).
- **No parallel mechanism.** `vip_symbol_index` is imported and reused, not reimplemented; the
  wiring sits beside the existing `_run_structural_lint()` in the one real CREATE ENVIRONMENT entry
  point; the CLI follows the existing `execute_verb` convention.
- **Hand-scoped patch used for the shared file.** `dv_harness/cli.py` carried another concurrent
  pass's uncommitted `coord` verb. I generated `git diff dv_harness/cli.py`, programmatically
  stripped the `pmuc`/`coord` hunks, asserted no `coord` text survived, ran
  `git apply --cached --check` then `--cached`, and verified `git diff --cached dv_harness/cli.py |
  grep -c "pmuc\|coord"` == 0 before committing. `dv_harness/multi_agent.py` and
  `.dv-harness/events.jsonl` (other passes' work) were left unstaged and untouched.
- **`dv_harness/dashboard.py` not touched.**

## 5. Deliberately NOT built (disclosed, not implied closed)

1. **Property access is not decided.** `vip_symbol_index._FIELD_RE` indexes only a restricted set
   of data types, so a field's absence from the index does not prove it does not exist. Deciding
   `cfg.some_field` would manufacture false failures. Only method calls, class type citations and
   `Class::` class-half citations are judged.
2. **`Class::MEMBER` decides the class half only.** The index models no enum constants, parameters
   or typedefs, so the member half is not judged.
3. **The `BASE_LIBRARY_METHODS` allowlist is the one false-positive risk.** It can only DOWNGRADE a
   finding (BLOCKED -> OUT_OF_SCOPE), so an omission yields a false BLOCKED and never a false
   PROVEN -- which is precisely why the generation-path wiring is non-blocking unless opted in.
4. **No stage gate.** A `tools/verification_flow/*_gate.py` that passed on VIPApiCards nobody
   cross-checked, or that blocked on the allowlist gap above, would be worse than none. The check is
   reachable from the real generation entry point and the real CLI; making it a mandatory
   PASS/FAIL gate is a separate decision needing a real VIP index in a real project.
5. **A signature-COMPATIBILITY check** (does the call site's argument list match the indexed
   `arguments` string?) is not implemented. The card carries the real declared signature so a human
   or a later pass can do it; deciding argument compatibility needs argument-type resolution this
   declaration-level scan does not have.
6. **No real vendor VIP index exists in this repo** to point the check at (context-budget tier 1
   forbids VIP source here). The mechanism is proven against the repo's own synthetic VIP source and
   a real generated environment; it was not made to "have fired" against a vendor tree by
   fabricating an index.

## 6. Files

- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/vip_api_card.py` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/uvm_generator/create_environment.py` (wired)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/cli.py` (`vip-api-check` verb)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_vip_api_card.py` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/fixtures/vip_api/demo_env_seq.sv` (new)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md` (new section)
- `D:/DV/Task/DV_Agent_Harness_L5/v50/.claude/skills/CORE/vip-scenario-branch/SKILL.md` (points at
  the coded enforcement)
