# Implementation: `transaction_scoreboards` DSL (TRANSACTION_SCOREBOARDS)

Implements `.work/scoreboard-generator-design-report.md` in full. Read that design report
end-to-end before doing any of this work, along with the real generator code it cites
(`generator.py`'s `scoreboard()`/`_emit_scoreboard_check()`/`base_vseq()`, the `connections`
`kind="call"` machinery, `sv_id()`), per this task's own instruction.

## What was built

`dv_harness/uvm_generator/generator.py` gains a new top-level manifest key
`"transaction_scoreboards"` on the existing `scoreboard()` method, plus:

- `MalformedTransactionScoreboardError` -- new typed-error class, same `reason`/`detail`
  convention as `MalformedScoreboardCheckError`, with the full validation-branch list documented
  in its own docstring.
- `UVMEnvironmentGenerator._validate_transaction_scoreboard(entry)` -- validates one manifest
  entry against the schema in full, raising on the first malformed piece found.
- `UVMEnvironmentGenerator._validate_tx_disposition(base_detail, disposition, prefix)` -- shared
  severity/`message_template` validator, reused for `on_mismatch` (per `compare_fields` entry),
  `on_orphan_predicted`, `on_orphan_observed`, and the optional `on_duplicate` (one validated
  shape, four use sites, per the design report's point 7).
- `UVMEnvironmentGenerator._tx_field_mismatch_expr(field, compare_op, mask)` -- compiles one
  `compare_fields` entry's mismatch condition, reusing `SCOREBOARD_CHECKS`'s existing
  `eq|neq|lt|lte|gt|gte|mask_eq` shapes verbatim plus the one new `array_eq`.
- `UVMEnvironmentGenerator._emit_transaction_scoreboard_macros()` / `_emit_transaction_scoreboard(p, entry)`
  -- emit the `uvm_analysis_imp_decl` macro pair (once per file) and one complete
  `uvm_scoreboard`-extending class per entry (TLM ports, `predicted_q` queue, a shared `key_eq()`
  match-key helper, `write_predicted`/`write_observed`, `report_phase` drain check).
- `scoreboard()` itself gains a third, independent branch: after building the existing
  `<p>_scoreboard` class (`scoreboard_rules`/`SCOREBOARD_CHECKS` output, byte-identical to
  before), every `transaction_scoreboards` entry is validated (all of them, before any emission --
  a malformed 3rd entry never leaves the first two partially emitted), then appended as one
  separate class each, using `base_vseq()`'s class-append-splice technique (`parts.append(...)`),
  not `_emit_scoreboard_check`'s function-append-into-one-class technique -- exactly as the design
  report's point 2 requires, since a TLM-port-bearing scoreboard needs its own component identity.

A manifest with no `"transaction_scoreboards"` key, or an empty list, produces byte-identical
output to before this change (verified by test and by re-running every existing
`SCOREBOARD_CHECKS`/`scoreboard()`-touching test unchanged). Zero changes were made to
`protocol_env_generator.py`, `vip_components`, or `connections` handling -- per the design
report's scope boundary, instantiating and wiring a generated transaction-scoreboard class reuses
those mechanisms completely unchanged (an ordinary `vip_components` class-handle entry; TLM-port
wiring via the existing `connections` `kind="call"` shape, e.g.
`predicted_predictor.ap.connect(<sb_instance>.predicted_export);`).

New test module: `dv_harness_tests/test_transaction_scoreboard_dsl.py`, 46 tests -- a worked
`OUT_OF_ORDER` + `array_eq` + `on_duplicate` DMA-scoreboard example; an `IN_ORDER`, no-`on_duplicate`
variant (proving the queue-head-only search and the "no history queue/counter when `on_duplicate`
is absent" simplification); backward-compat (absent key / empty list, byte-identical); a mixed
manifest (existing `scoreboard_rules` check entries coexist with a `transaction_scoreboards` class,
correct position/order); the macro-declaration-once guard across two entries; one test per
`MalformedTransactionScoreboardError` reason code; and an end-to-end integration group proving the
generated class instantiates via an ordinary `vip_components` entry and wires its ports via the
existing `connections` `kind="call"` shape, with no changes needed to either mechanism.

Documentation consolidated into `.claude/skills/CORE/ip-uvm-dv-gen/SKILL.md`'s "Checkers and
scoreboard" section (per CLAUDE.md's Methodology Consolidation Rule) with the schema summary, v1
scope-boundary notes, and the real wiring-evidence citation; the module-pointer note near the top
of that file now also names `transaction_scoreboards`. No `industrial`/`PACKAGE` deliverable-tree
sync was performed -- searching this repo found no directory matching that description (only
unrelated `PACKAGE_INVENTORY.json`/`FINAL_PACKAGE_INDEX.md` release-manifest files at the repo
root and inside `.worktrees/runtime-progress-visibility/`), so there was nothing to sync `.claude/`
into; flagged here rather than silently skipped.

## Rulings (open questions + underspecified emission details)

The design report's own "Open Questions for User" section explicitly invited a ruling rather than
a stop-and-ask, for every item:

1. **RULING (gate field-name direction ambiguity):** left unresolved, exactly as the design report
   itself concluded it should be -- out of this task's scope. No auto-population of
   `scoreboard_transaction_liveness_gate.py`/`expected_data_provenance_gate.py`'s JSON evidence
   shape from this generator's runtime counters was implemented; that gate-side ambiguity
   (`missing_expected_transactions` vs. `missing_actual_transactions` direction) is a separate,
   later evidence-assembly concern per the design's own Scope Boundary "OUT" list, not a
   code-generation concern this task closes.
2. **RULING (register_decode/enum_translation on compare_fields): deferred to v2**, matching the
   design's own recommendation. v1 ships the smaller, reviewable core (queue/match/compare/orphan)
   without per-field register-bit-decode or enum-translation; a manifest needing that today must
   fall back to comparing the raw field value. This keeps the diff reviewable and matches
   `SCOREBOARD_CHECKS`'s own historical rollout shape (plain compare first, register_decode/
   enum_translation added once the base shape was proven).
3. **RULING (report_phase-only orphan/drop detection is acceptable for v1): confirmed, ship it.**
   Live per-transaction timeout detection needs real per-protocol clock-period/timescale evidence
   this generator does not currently model anywhere (confirmed absent, same read-first pass as the
   design report's), and a materially different code shape (`fork`/`wait`-with-timeout). Shipping
   report_phase-drain-only now, honestly documented as a known limitation (both in code docstrings
   and here), is the correct v1 tradeoff -- consistent with this project's Evidence Truth Rule:
   never claim a capability the generator does not actually have.
4. **RULING (fixed 2-port predicted/observed shape is sufficient for v1): confirmed.** No example
   manifest anywhere in `examples/` demonstrates a 3-way (e.g. PCIe non-posted request/response/
   completion) need, so there is no real evidence to design against yet; a genuine N-port topology
   is deferred to a future, evidence-backed extension rather than speculatively built now.
5. **RULING (top-level key name): `transaction_scoreboards`, exactly as the design report's own
   Proposed Design already named it.** No existing file in the repo contradicts this name; it
   reads clearly as a sibling to `virtual_sequences`/`vip_components`/`connections`.

Additional rulings made while filling in emission details the design report's own pseudocode left
as `...` ellipses (documented in the corresponding code docstrings, repeated here for visibility):

6. **RULING (`array_eq` mismatch operator): plain `!=`, not `!==`.** The design report's own
   prose section is internally inconsistent -- it correctly states real IEEE 1800 SystemVerilog
   gives `==`/`!=` element-wise semantics on same-element-type dynamic arrays/queues, but its own
   compiled-code sketch then showed `!==`. `===`/`!==` (4-state case (in)equality) are defined only
   for packed/integral types, not for unpacked array types (dynamic arrays, queues); emitting
   `!==` on a queue field would be a real VCS compile error, not merely non-idiomatic style. Since
   this generator's stated posture is to never knowingly emit SystemVerilog that cannot compile,
   `array_eq` uses `!=` while every other `compare_op` keeps the exact `!==`/`===` `SCOREBOARD_CHECKS`
   precedent already uses. This is a correctness fix relative to the design document's own sketch,
   not a deviation from working code -- flagged explicitly since the task instructions called for
   following the proposed design "exactly" and this is the one place doing so verbatim would have
   produced broken SystemVerilog.
7. **RULING (`message_template` `$sformatf` argument conventions):** the design's own pseudocode
   left these as unspecified `<...>` placeholders. Chosen conventions (documented in
   `scoreboard()`'s docstring and enforced structurally, not just by convention):
   `on_mismatch` (per `compare_fields` entry) gets exactly 3 args, `(field_name, expected_value,
   observed_value)` -- the same (identifying-name, lhs, rhs) shape `_emit_scoreboard_check`
   already uses for its own `message_template`, with "field name" playing `check_name`'s role
   since one `write_observed()` call can run more than one `compare_fields` check.
   `on_orphan_predicted` gets exactly 2 args, `(scoreboard_name, predicted_q.size())`, fired once
   in `report_phase` for the whole remaining queue (matching the design's own aggregate-count
   sketch, not a per-item loop). `on_orphan_observed` and `on_duplicate` each get exactly
   `len(match_key)` args -- the observed transaction's match-key field values, in `match_key`
   order -- giving concrete per-event debug context without assuming any other field exists on a
   protocol-agnostic `item_class`.
8. **RULING (shared `key_eq()` helper, not three inline copies):** the design's pseudocode
   abstracted match-key comparison behind an ellipsis at three logical use sites (`IN_ORDER`
   head-check, `OUT_OF_ORDER` full-queue search, and the optional duplicate-history search). These
   are implemented as one `local function bit key_eq(<item_class> a, <item_class> b)` per emitted
   class, reused at all three sites -- an implementation-detail choice that reduces generated code
   size and keeps the match-key semantics defined in exactly one place, not a schema change.
9. **RULING (`DUPLICATE_PORT_NAME` added, not in the design's enumerated reason-code list):** a
   manifest entry whose `predicted_port`/`observed_port` resolve to the identical `port_name`
   would compile to two identically-named class members -- a real VCS compile error, not merely a
   style issue. Added as its own typed-error branch rather than silently accepted, consistent with
   this generator's never-emit-known-broken-SV posture; documented explicitly in
   `MalformedTransactionScoreboardError`'s docstring as an addition beyond the design's own list.
10. **RULING (`on_duplicate`'s own severity/`message_template` sub-validation, `INVALID_ON_DUPLICATE_SEVERITY`/
    `MISSING_ON_DUPLICATE_MESSAGE_TEMPLATE`, not explicitly enumerated by the design):** since
    `on_duplicate` shares the exact `{severity, message_template}` shape as the three required
    dispositions, a present-but-malformed `on_duplicate` is validated identically via the shared
    `_validate_tx_disposition` helper rather than accepted unchecked just because the key itself
    is optional.

## Test results

- New module: `python -m pytest dv_harness_tests/test_transaction_scoreboard_dsl.py -q` --
  **46 passed** (43 unit-level DSL tests plus 3 end-to-end integration tests confirming the
  generated scoreboard class instantiates and wires via the existing, unmodified
  `vip_components`/`connections` machinery -- design report point 6).
- Full existing suite: `python -m pytest dv_harness_tests/ -q` -- **1287 passed in 979.38s
  (0:16:19), 0 failed**. This is the complete `dv_harness_tests/` suite (`pyproject.toml`'s
  `testpaths`), confirming zero regressions anywhere in the codebase from this change. A separate
  targeted run of every test file that exercises
  `scoreboard()`/`SCOREBOARD_CHECKS`/`base_vseq()`/`protocol_env_generator.py` directly
  (`test_scoreboard_check_dsl.py`, `test_sequence_body_dsl.py`, `test_protocol_env_generator.py`,
  `test_connect_phase.py`) was also run in isolation and passed cleanly (55/55) before the full-suite
  run finished.
- Backward-compatibility: every `examples/generated_usb_real_evidence_v*` manifest input was
  re-checked -- none carries a `"transaction_scoreboards"` key, so `scoreboard()`'s new third
  branch is a no-op for all of them (the `if tx_entries:` guard means the new code path is never
  entered), and the addition is provably additive by construction, not just by spot-check.
- No pre-existing bug was found in `generator.py`'s scoreboard-related code during this task
  (the one genuine defect found -- the design report's own internally-inconsistent `array_eq`
  operator choice -- was in the *design document*, not in existing shipped code, and is corrected
  per Ruling 6 above).

## Concerns / residual gaps (all deliberate v1 scope, not oversights)

- `predicted_q` (and the optional `matched_history_q`) can grow unboundedly against a stuck or
  misbehaving DUT -- flagged in the design report's own Scope Boundary and left unsolved in v1, as
  directed.
- Orphan-predicted detection only fires at `report_phase` (end of test), not live with a
  per-transaction timeout -- Ruling 3 above.
- No `register_decode`/`enum_translation` on `compare_fields` yet -- Ruling 2 above.
- Exactly 2 fixed named ports (`predicted`/`observed`), both carrying the same `item_class` -- no
  N-way match, no per-side item-class mapping -- Ruling 4 and the design's own Scope Boundary.
- This DSL never synthesizes reference-model prediction logic itself; it only consumes an
  existing predicted-side analysis port, same posture as `virtual_sequences` never inventing
  item-randomization values without manifest evidence.
- The three real runtime-evidence gates already wired into `STAGE_GATES["VERIFY"]`
  (`scoreboard_transaction_liveness_gate.py`, `scoreboard_reference_model_independence_gate.py`,
  `expected_data_provenance_gate.py`) are untouched and still expect a hand-assembled JSON evidence
  block; no code in this task maps this DSL's runtime counters onto their exact field names
  (Ruling 1 / design's own Scope Boundary "OUT" item -- correctly out of scope for a
  code-generation task).
