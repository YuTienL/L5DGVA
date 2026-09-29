# Bind-Location / VIP-Connectivity / Checker-Scoreboard System (Part C)

2026-09-03. Scope: the connectivity-manifest system, the 4-tier confidence
classification, the count-check equations, the 3 machine gates, the
checker/scoreboard planning-table generator, and the 4 fixed CLAUDE.md
bind-location rules -- Part C of the user's env.manifest.json spec, the
piece the user explicitly emphasized ("尤其是bind location，和VIP種類和數量所
對應的DUT instance hierarchy path及checker，scoreboard作法分析後的規劃建議
和確認").

## What was built

- `dv_harness/connectivity.py` (new module, ~900 lines) -- the real
  connectivity-manifest system: 4-input collectors, the T1-T4 tier
  classifier, the count-check equations, the connectivity matrix
  (JSON + human-readable renderer + mermaid hierarchy diagram), the 3
  machine gates (as a mandatory, non-skippable pipeline), the per-row
  lock/diff mechanism, the checker/scoreboard planning-table generator,
  and a Part-B-schema-shaped T4 question-queue-entry builder.
- `dv_harness_tests/test_connectivity.py` -- 69 tests, all passing
  (`python -m pytest dv_harness_tests/test_connectivity.py -q` ->
  `69 passed in 0.90s`).
- `CLAUDE.md` -- new "Bind-Location Rules (2026-09-03)" section (appended
  after "Trust Progression...", following the file's existing
  dated-section convention; `CLAUDE.md` was clean/unmodified by any
  sibling workstream before this edit, confirmed via `git diff CLAUDE.md`
  before touching it).
- `.claude/skills/CORE/ip-uvm-dv-gen/SKILL.md` -- cross-reference added at
  the exact point that skill already states "Everything else uses `bind`,
  targeted at where the signals actually are" (the section this repo's
  own bind mechanics, distilled from the USB_UVM_Handoff consolidation
  work, already lives in). Rules are stated once, in CLAUDE.md; the skill
  points at them rather than restating them, matching this repo's
  existing "point at the same module rather than restating its schema"
  convention (see that skill's own header note about
  `bind_mechanism_generator.py`).

No sibling-workstream file was touched: `git status --short` before and
after this work confirms `dv_harness/config.py`, `cli.py`, `evidence_db.py`,
`regression_reporter.py`, `vip_distill.py`, `exemptions.py`, `engine.py`,
`session_snapshot.py` all carry only their own pre-existing uncommitted
changes from the two concurrent workstreams, untouched by this one.

## 4-tier confidence classifier (T1-T4) -- real and tested

`classify_bind_tier()` implements the exact priority order Part C
specifies (T1 > T2 > T3 > T4, evaluated on real evidence dicts, never
inferred from a "confidence score"):

- **T1 (already-decided)**: an existing bind statement or config_db
  entry was found. Accepted as-is.
- **T2 (structural match)**: a protocol-fingerprint match against the
  module's real, verible-extracted port set (`AXI` needs
  `AWVALID/AWREADY/WLAST/BRESP`, `CSI2` needs D-PHY clock-lane signals,
  etc. -- `PROTOCOL_FINGERPRINTS`). Auto-acceptable, but still listed.
  A **partial** hit never rounds up to a match (tested).
- **T3 (naming-heuristic-only)**: a name match with no full structural
  corroboration. `auto_acceptable` and `requires_human_confirmation` are
  hard-coded in the classifier's own return value with no parameter that
  can flip them -- `test_tier3_never_auto_accepted_even_with_partial_structural_hint`
  proves a naming match plus a *partial* (non-matching) structural hint is
  still classified T3, and `assert_t3_never_auto_accepted()` is a
  defense-in-depth regression guard any downstream "act on auto-acceptable
  rows" consumer can call before acting -- `test_assert_t3_never_auto_accepted_catches_a_corrupted_result`
  proves it actually raises on a corrupted/hand-built T3 result.
- **T4 (undecidable)**: routed to `build_t4_question_queue_entry()`,
  never guessed.

## Count-check equations -- real, computable, tested (passing + broken cases)

- `check_vip_instance_count_matches_active_interfaces()` -- VIP count
  must equal *active interface* count, not raw IP-instance count. Test
  proves a passive-monitor-only IP (1 IP instance, 0 active interfaces)
  is correctly reported as a mismatch against a naive "IP instance ==
  VIP" assumption.
- `determine_role_from_port_direction()` -- takes **only** a port
  direction string (no instance-name parameter exists in its signature at
  all -- `test_determine_role_from_port_direction_never_takes_a_name_parameter`
  asserts this via `inspect.signature`), so a slave/responder
  determination can never be name-driven even by accident at a call site.
- `compute_path_combination_count()` -- master-count x reachable-slave-
  count, with an optional non-full-mesh `reachability` map for a
  partitioned fabric; tested both in full-mesh default and restricted-
  reachability form.
- `verify_self_check_identity()` -- the hard identity
  `sum(verified interfaces) == sum(VIP instances) + sum(exemptions)`,
  implemented as a real exception (`ConnectivitySelfCheckError`), not a
  bool/warning. Tested passing, tested deliberately-broken (gap of 2,
  asserted in the exception detail), and tested rejecting an exemption
  with no per-line reason before the identity is even evaluated.

## Connectivity matrix

`build_connectivity_matrix()` / `render_matrix_table()` /
`write_connectivity_manifest()` emit the exact required column set
(`dut_instance | interface | direction | role | vip_type | count |
active_passive | bind_target | tier`) as both a JSON artifact and a
fixed-width human-readable table. `render_hierarchy_diagram()` adds a
minimal mermaid flowchart (DUT instance -> bind target -> VIP type, tier
on the edge label) as the second of Part C's 3 final artifacts; the third
(question queue) is `build_t4_question_queue_entry()`'s output.

## 3 machine gates -- mandatory pipeline, real logic, honest availability

`run_machine_gates()` is the single entry point; it always runs all 3
gates in order and returns an aggregate `GateReport` -- there is no way
to invoke it and get back fewer than 3 results, though each underlying
gate function (`run_gate1_elaboration_check`, `evaluate_zero_time_connectivity`,
`evaluate_transaction_activity`) remains separately importable for
targeted unit tests.

- **Gate 1 (elaboration check)**: real subprocess wrapper preferring
  `slang` then `vcs`. **Confirmed live in this environment (2026-09-03,
  `which slang` / `which vcs`): neither is installed** -- Gate 1 honestly
  reports `NOT_AVAILABLE` with the exact install/invoke instructions for
  either tool (`test_run_gate1_elaboration_check_honest_not_available_in_this_environment`
  is a real, unmocked check against this actual machine). The real
  subprocess-invocation logic itself is tested via dependency-injected
  `which_fn`/`run_fn` (PASS and FAIL-on-nonzero-exit cases), so it is
  ready the moment either tool is actually installed here.
- **Gate 2 (static zero-time connectivity)**: real logic
  (`evaluate_zero_time_connectivity()`) operating on a `SignalTrace`
  (time, value) sample contract -- checks clock toggling, reset
  deassertion, and non-X/non-Z at time zero for a caller-specified
  signal list. Three synthetic fixtures prove the logic: a passing
  trace, a dead-clock trace (FAIL), and an X-at-t0 trace (FAIL).
  `run_gate2_against_live_simv()` is the honest NOT_AVAILABLE integration
  point (no live simv in this repo) with the real capture recipe
  documented (targeted `$dumpvars`, per this project's own Waveform Dump
  User Gate -- minimum sufficient scope).
- **Gate 3 (transaction activity)**: real logic
  (`evaluate_transaction_activity()`) over a monitor-instance ->
  transaction-count dict; flags any monitor with 0 transactions --
  exactly the "syntactically legal, structurally wired, wrong instance"
  case Part C calls out. `run_gate3_against_live_simv()` is the honest
  NOT_AVAILABLE integration point, with the standing "just
  connectivity-check" directed-test recipe documented as Part C
  recommends (re-run on every RTL update, not one-time).
- `GateReport.ready_for_human_review()` blocks presentation on any real
  FAIL but allows NOT_AVAILABLE through (visibly, via
  `not_available_gates()`) -- tested both ways
  (`test_run_machine_gates_pipeline_blocks_on_a_real_fail` /
  `test_run_machine_gates_pipeline_runs_all_three_in_order`).

## Per-row lock/diff mechanism -- real test per the spec's own prescription

`RowLockStore` is a JSON-file-backed lock store keyed by row id
(`dut_instance::interface` for a connectivity row,
`scoreboard::<scoreboard_id>` for a scoreboard-plan row). Exactly the two
tests the spec asked for, plus persistence and never-confirmed coverage:

- confirm a row, regenerate with **no** change -> **zero** rows need
  reconfirmation (`test_row_lock_confirm_then_no_op_regeneration_needs_zero_reconfirmation`).
- confirm two rows, regenerate with a simulated change to **one** ->
  **exactly** that one row is flagged, the other is not
  (`test_row_lock_changed_row_is_flagged_for_reconfirmation_others_are_not`).
- a never-yet-confirmed row always needs (re)confirmation
  (`test_row_lock_never_confirmed_row_needs_reconfirmation`).
- locks persist across a fresh `RowLockStore` instance reading the same
  file (`test_row_lock_persists_across_store_reload`).

## Checker/scoreboard planning-table generator

- `generate_protocol_check_entry()` -- lists enabled vs. disabled
  VIP built-in checks; a disabled check with no reason, or a disabled
  check not present in the built-in list at all, is a hard error
  (`ConnectivityError`), never a silent omission. The disabled list is
  what the entry foregrounds, per Part C's own framing of it as the
  actual review focus.
- `generate_scoreboard_entry()` -- **the never-auto-filled guarantee**:
  `ordering` and `legal_drop_conditions` default to the
  `REQUIRED_HUMAN_INPUT` sentinel unless a caller explicitly supplies a
  value; the function contains no logic path that computes or guesses
  either. Directly tested
  (`test_generate_scoreboard_entry_ordering_and_legal_drop_default_to_required_human_input`)
  alongside the explicit-human-supplied-value path
  (`test_generate_scoreboard_entry_accepts_explicit_human_supplied_values`).
  `reset_flush_behavior`/`orphan_unmatched_threshold`/`orphan_unmatched_timeout`
  get the same treatment, since each is a place a false-pass could hide.
- `generate_system_level_entry()` / `build_checker_scoreboard_plan()` --
  cross-interface-path / performance / error-response entries, grouped
  into the final 3-kind plan structure (protocol / data-integrity /
  system-level).

## 4 fixed CLAUDE.md bind-location rules -- landed

New "Bind-Location Rules (2026-09-03)" section in `CLAUDE.md`: bare
module name vs. full instance path, centralized `*_bind.sv` files under
`tb/` (RTL read-only), clock/reset through the bind's own port list (no
hierarchical grab), no generate/for-loop bind targets (explicit literal
indices only). Cross-referenced (not duplicated) from
`ip-uvm-dv-gen/SKILL.md`'s existing bind-mechanics section, which already
covers the two-hook bridge/`bind` convention distilled from the
USB_UVM_Handoff consolidation work.

## NOT_AVAILABLE-by-honest-design vs. genuinely real-and-tested-today

| Item | Status | Why |
|---|---|---|
| Existing-bind grep/parse (`grep_existing_binds`) | **REAL** | Pure filesystem walk + regex; tested against a real `tmp_path` fixture with real files on disk. |
| Interface signal-set fingerprints (`build_interface_fingerprints`) | **REAL** | Extends `verible_parser.ModuleInfo`/`PortInfo` directly -- the real, already-verified verible port extraction, not re-implemented. |
| Protocol fingerprint matching (`match_protocol_fingerprint`) | **REAL** | Pure set logic over real port names; fingerprint signal sets themselves are taken verbatim from Part C's own worked examples. |
| 4-tier classifier | **REAL** | Pure function over evidence dicts; no external tool dependency at all. |
| Count-check equations + self-check identity | **REAL** | Pure Python; no external tool dependency. |
| Connectivity matrix / JSON+table/mermaid renderers | **REAL** | Pure Python. |
| Row lock/diff store | **REAL** | JSON file I/O only; no external tool dependency. |
| Checker/scoreboard planning-table generator | **REAL** | Pure Python; deliberately accepts evidence as input rather than deriving it, per the "never guess ORDERING/LEGAL_DROP" requirement. |
| DUT instance tree via `slang --ast-json` | **NOT_AVAILABLE** (confirmed live: `slang` not on PATH) | Parser logic (`parse_slang_ast_json`) is real and unit-tested against a synthetic fixture built to slang's documented `--ast-json` shape; the live confirmation against a real slang run is the honest gap. Fallback path (`simv -ucli -do "scope -tree"`) documented, not implemented (no live simv either). |
| VIP topology / config_db trace capture | **NOT_AVAILABLE** (no live simv in this repo) | `parse_topology_dump`/`parse_config_db_trace`/`find_set_with_no_get` are real and unit-tested against synthetic fixtures built to UVM's own documented `print_topology()` table format and `+UVM_CONFIG_DB_TRACE` message shape. Live capture recipe documented in `capture_vip_topology()`'s own NOT_AVAILABLE detail. |
| Gate 1 (elaboration check) | **NOT_AVAILABLE** (confirmed live: neither `slang` nor `vcs` on PATH) | Real subprocess wrapper logic tested via dependency injection; this machine genuinely has neither tool. |
| Gate 2 (static zero-time connectivity) | Logic **REAL and tested**; live-simv integration **NOT_AVAILABLE** | No live simv to pull a real signal trace from; `evaluate_zero_time_connectivity()` itself is fully real and tested against synthetic traces. |
| Gate 3 (transaction activity) | Logic **REAL and tested**; live-simv integration **NOT_AVAILABLE** | Same treatment as Gate 2. |

## Reconciliation flags (explicit, not silently resolved)

1. **VIP topology / config_db capture shape vs. the env.manifest.json
   (Part A) workstream.** Both this module and that workstream's
   env-topology section consume the same underlying real UVM mechanisms
   (`uvm_top.print_topology()` + `+UVM_CONFIG_DB_TRACE`). This module's
   `parse_topology_dump()`/`parse_config_db_trace()` were built
   independently against UVM's own documented default report/trace
   format (see each function's docstring for the exact shape assumed),
   without reading or importing that sibling workstream's file, per this
   task's own instruction not to block on it. **A reconciliation pass is
   needed**: confirm both workstreams parse the same real capture-file
   shape (indentation width, column layout, exact `[CFGDB/SET]`/
   `[CFGDB/GET]` message text) once a real live capture exists, and
   converge on one shared parser if the shapes genuinely coincide, rather
   than maintaining two independently-tested-but-possibly-divergent
   parsers long-term.
2. **T4 question-queue schema vs. the question-queue (Part B)
   workstream.** `dv_harness/question_queue.py` does not exist yet in
   this repo (confirmed: no such file). `build_t4_question_queue_entry()`
   was built directly against Part B's own documented Q-ID schema
   (`id`, `blocking`, `domain`, `owner`, `question`, `context_path`,
   `options[]`, `recommendation`, `assumption_if_unanswered`; 2-3
   pre-researched options enforced as a hard length check; owner routed
   by domain: vip -> DV-owner/Synopsys-AE, dut -> designer, env ->
   DV-owner) rather than calling into a real module. **Once
   `dv_harness/question_queue.py` lands**, `build_t4_question_queue_entry()`
   should be reconciled against its real implementation (either replaced
   by a direct call into that module, or kept as a thin adapter if the
   real module's own entry-point signature differs from what's assumed
   here) -- flagged here rather than guessed.

## Test summary

`python -m pytest dv_harness_tests/test_connectivity.py -q` -> **69
passed in 0.90s**. Covers: all 4 tiers including the T3-never-auto-accept
regression test and its defense-in-depth guard; interface fingerprinting;
existing-bind grep+parse against real files; topology/config_db-trace
parsing against documented-shape synthetic fixtures (+ a real
set-with-no-get miswired-vif detection); the honest slang/DUT-tree
NOT_AVAILABLE check plus a synthetic-fixture parser test; all 3 count-check
equations including a deliberately-broken case each; the connectivity
matrix (JSON, table, mermaid); all 3 machine gates (a real, live
NOT_AVAILABLE check for Gate 1 in this actual environment, synthetic PASS/
FAIL fixtures for Gates 1-3, and the mandatory-pipeline behavior including
a real-FAIL-blocks-review case and an all-NOT_AVAILABLE-by-default case);
the per-row lock/diff mechanism (no-op regeneration, single-row-changed
regeneration, never-confirmed, and cross-instance persistence); and the
checker/scoreboard planning-table generator's disabled-check-reason
enforcement and ORDERING/LEGAL-DROP never-auto-filled guarantee.

## Status

**DONE.**
