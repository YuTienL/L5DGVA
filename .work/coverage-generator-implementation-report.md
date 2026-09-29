# Coverage Generator + Ingestion -- Implementation Report

Implements `.work/coverage-generator-design-report.md`. Ran sequentially
after the scoreboard-generator and checker-sva-generator tasks in the same
workflow, both of which also touched `generator.py` -- this task re-read
the CURRENT state of that file before editing rather than trusting the
design doc's cited line numbers (which had already drifted: `coverage()`
was at line 1427/`scoreboard()` at line 695/`_emit_scoreboard_check` at
line 987 by the time this task started, not the design doc's original
873-883/735-871/787-845).

## Part 1 -- `coverage_points` structured DSL (COMPLETE)

**Discriminator**: a `coverage_points` entry that is a dict AND carries a
`cg_name` key opts into the new DSL; every other entry falls through
unchanged to the pre-existing `// COVER: <json.dumps(x)>` comment line --
verified byte-identical for every manifest with no `cg_name`-carrying entry,
including a scan of all 12 real `examples/generated_usb_real_evidence_v*`
manifests (none use the new key).

**Shared `_decode_and_translate` helper**: `_emit_scoreboard_check`'s own
`emit_side()` closure (register_decode bit-slice + enum_translation
value-map case table) was factored into a new
`UVMEnvironmentGenerator._decode_and_translate()` static method, called by
BOTH `_emit_scoreboard_check` (SCOREBOARD_CHECKS, unchanged behavior --
every pre-existing `test_scoreboard_check_dsl.py` test still passes
byte-for-byte) and the new `_compile_coverage_group` (coverage_points). A
new `declare_dest` parameter distinguishes the two callers' different
target shapes: SCOREBOARD_CHECKS declares a fresh function-local
(`declare_dest=True`, e.g. `bit [1:0] lhs = ...;`); coverage_points assigns
an already-declared persistent class member instead (`declare_dest=False`,
e.g. `cp_eptype = ...;`, no type prefix).

**`uvm_subscriber` base-class fix (the load-bearing sampling fix)**: when
any `coverage_points` entry uses `sample_trigger.kind == "subscriber_write"`,
the generated `<p>_coverage` class now extends
`uvm_subscriber #(<item_class>)` instead of the previous fixed
`uvm_component` -- reusing uvm_subscriber's own built-in `analysis_export`
+ `write()` hook, exactly the shape
`.dv-harness/universal-protocol-platform/templates/coverage.sv.tpl`'s real
(previously unused) template already showed was correct. Wiring a real VIP
monitor's analysis port to `cov.analysis_export` needs no new mechanism at
all -- an ordinary `connections` entry with `kind: "call"` (the same
`<receiver>.<method>(<args>)` idiom `_connect_phase` already emits, real
evidence `usb_top_env.sv:531`) does it; `env()`/`_connect_phase` needed
zero changes, confirmed by not touching either.

**Emission** (`_compile_coverage_group`, called per-entry from `coverage()`):
compiles one `coverage_points` entry into a real
`covergroup cg_<cg_name>; coverpoint ...; cross ...; endgroup`, one
`bins`/`bins_array`/`ignore_bins`/`illegal_bins` line per declared bin, one
shadow class member `cp_<cp_name>` per coverpoint (typed from
`_decode_and_translate`'s resolved type), a `function new()` that
`new()`s every covergroup (the actual missing wiring step
`amba_fabric_generator.py`'s own `cg_ms_cross` precedent never had --
that precedent declares `master_idx`/`slave_idx` but never assigns them or
calls `.sample()`, which this task's design doc flagged explicitly as
"proves syntax, not sampling wiring"), and either a shared `write(<item_class> t)`
override (one per manifest, all `subscriber_write` entries' body fragments
appended into it, each followed by its own `cg_<name>.sample();`) or a
`function void sample_<cg_name>(<params>);` per `explicit_call` entry.
Multiple `coverage_points` entries splice additively into the same class,
same technique `scoreboard()`/`env()` already use for their own DSL
extensions.

### Rulings made (documented here and in the commit message)

1. **RULING -- every coverpoint gets a persistent class-member shadow
   variable (`cp_<cp_name>`), never a write()-local, regardless of whether
   it carries `register_decode`/`enum_translation`.** The design doc's own
   prose ("each coverpoint whose expr needs decode/translate gets a shadow
   local") could be read as implying plain coverpoints reference the
   write()-parameter `t` directly inside the covergroup declaration --
   but a no-argument `cg.sample()` call (the shape the design doc's own
   text uses, `cg_<cg_name>.sample();`) can only read symbols in scope at
   the CLASS level, not a function-local parameter, so a covergroup
   coverpoint can never reference `t` directly no matter how simple its
   expression is. Applying the shadow-member treatment uniformly (via
   `_decode_and_translate` for every coverpoint, decode/translate present
   or not) is the simplest design that is unconditionally valid
   SystemVerilog, and it is what actually fixes the sampling-wiring gap
   the design doc flagged against the amba_fabric precedent.
2. **RULING -- `explicit_call` coverpoints derive their generated function
   parameter name from `cp_name` (`in_<cp_name>`), not from `expr`.**
   `expr` in the shared coverpoint schema is only meaningful as a
   `t.<field>`-style read path when a live item is in scope
   (`subscriber_write`); for `explicit_call` there is no such item, only
   the function's own parameters. `expr` is still validated as
   required/non-empty for every coverpoint (per the design doc's own error
   list, which does not condition that requirement on trigger kind), but
   for `explicit_call` entries it is accepted-but-unused for naming
   purposes -- the same "accepted but not itself rendered" posture
   `_connect_phase`'s optional `ctor_class` field already holds.
3. **RULING -- `CONFLICTING_ITEM_CLASS`.** Two `subscriber_write` entries
   in one manifest naming different `item_class` values is unsatisfiable
   (the generated class can only extend one `uvm_subscriber #(T)`) and is
   rejected with a new `MalformedCoveragePointError` reason not
   enumerated in the original design pass's list, added for the same
   defect-prevention posture `MalformedTransactionScoreboardError`'s
   `DUPLICATE_SCOREBOARD_NAME` already holds elsewhere in this file.
4. **RULING -- `DUPLICATE_CP_NAME`.** Two coverpoints in the same group
   sharing a `cp_name` is rejected (would collide on the same generated
   `cp_<cp_name>` member/coverpoint label) -- same additional
   defect-prevention posture as (3), not in the original design pass's
   list either.
5. **RULING -- subscriber-write plain coverpoints assign directly with no
   `int'(...)` cast** (unlike SCOREBOARD_CHECKS' plain-field branch, which
   casts for strict comparison purposes). A coverage shadow member's
   declared type already comes from `sv_type`/register_decode, so an
   extra cast added no value and only diverged from the coverpoint's own
   declared type unnecessarily.

Every other validation branch (`MISSING_CG_NAME`, `MISSING_COVERAGE_EVIDENCE`,
`INVALID_SAMPLE_TRIGGER_KIND`, `MISSING_ITEM_CLASS`, `EMPTY_COVERPOINTS`,
`MALFORMED_COVERPOINT`, `EMPTY_BINS`, `INVALID_BIN_KIND`, `MALFORMED_BIN`,
`MALFORMED_CROSS`, `UNDECLARED_CROSS_COVERPOINT`,
`MALFORMED_CROSS_IGNORE_BIN`, plus the shared `INVALID_REGISTER_DECODE`/
`UNSUPPORTED_ENUM_TRANSLATION_KIND`/`MISSING_ENUM_TRANSLATION_MAP`/
`MISSING_ENUM_TRANSLATION_NOTE`) follows the design doc's list exactly, all
raising the new `MalformedCoveragePointError` (same
SCREAMING_SNAKE_CASE-reason + detail-dict convention as every other typed
error in this file).

## Part 2 -- `tools/coverage/urg_summary_reduce.py` (SKELETON ONLY -- deliberately incomplete)

Built exactly what the design doc says is safe to build now, and stopped
exactly where it says to stop:

- Real CLI parsing (`--urg-report`, `--out`, both required).
- `build_summary()` calls `dv_harness.coverage_analysis.parse_coverage_summary()`
  on the candidate `{"categories": [...]}` dict BEFORE returning it --
  self-validation against the real downstream reader, proven in tests via
  monkeypatching the (blocked) parse step to return both well-formed and
  deliberately-malformed category lists.
- `write_summary_atomic()` reuses `dv_harness.storage._atomic_replace` (the
  same primitive `coverage_analysis.append_history_sample()` already uses)
  for a torn-write-safe write, creating the parent directory as needed.
- `CODE_COVERAGE_METRICS = ("line","cond","fsm","tgl","branch")` (verbatim
  from the real Makefile's `CM_OPTS` at
  `dv_harness/uvm_generator/templates/sim_scripts/Makefile:1364`) and
  `FUNCTIONAL_COVERAGE_CATEGORY = "functional"` declared as constants, not
  yet populated from any real parse.
- The script's own docstring documents the real, already-committed
  `tools/remote/remote_exec.py --get` transport for pulling a
  Linux-produced `summary.json` back to the PC-side `.dv-harness/coverage/`
  tree -- no new transport code written, per the design doc's instruction.

**`parse_urg_report()` raises `NotImplementedError("BLOCKED: no real urg
report sample or version-pinned schema available in this repo -- see
.work/coverage-generator-design-report.md Open Questions 1-2 (...)")`** at
exactly the point real per-category percent/bins_hit/bins_total extraction
would go. This is a genuine, unresolved gap, not a stylistic placeholder:
this repository contains no real `urg` `dashboard.txt`/`dashboard.html`
sample to derive a column layout or DOM structure from, and no confirmation
of which VCS/urg version the real Linux DV server has installed (the
report layout is version-dependent). Implementing the actual parse without
that evidence would be exactly the fabricated-evidence mistake CLAUDE.md's
Evidence Truth Rule and "No Golden-Reference Content Mining" sections exist
to prevent. **Part 2's real parsing logic remains fully blocked and
unsized** -- it is not "mostly done," it is a skeleton around a
deliberately unimplemented core, and closing it requires the real evidence
named in Open Questions 1-2 (a real urg report sample, and the actual
VCS/urg version on the real Linux DV server), neither of which this task
had access to.

## Tests

New files:
- `dv_harness_tests/test_coverage_points_dsl.py` (34 tests): backward-compat
  (absent key / empty list / legacy freeform entries byte-identical to the
  pre-existing placeholder/comment-dump templates), a worked
  `subscriber_write` example (register_decode + enum_translation + a plain
  coverpoint + a cross with an evidence-cited `ignore_bins`), an
  `explicit_call` example, a mixed legacy+structured manifest, multiple
  `subscriber_write` entries sharing one `write()` override, every
  validation-error reason code, and a regression spot-check proving the
  `_decode_and_translate` refactor left SCOREBOARD_CHECKS' own compiled
  output unchanged.
- `dv_harness_tests/test_urg_summary_reduce.py` (13 tests): constants, the
  `NotImplementedError` itself (message content and CLI exit code 2), CLI
  required-flag enforcement, self-validation (both accept and reject paths,
  via monkeypatching the blocked parse step), atomic write (including
  parent-dir creation and overwrite-of-stale-file), and one end-to-end
  `main()` happy path.

Full existing suite (`python -m pytest dv_harness_tests -q`) was run twice:
once immediately after the `generator.py` refactor/extension (1331 passed,
0 failed -- before the two new test files existed, confirming the
`_decode_and_translate` refactor and `coverage()` rewrite caused zero
regressions against the pre-existing suite), and once more after adding
both new test files (1364 passed, 1 failed). The one failure,
`test_graph_parallel_dispatch.py::test_engine_dispatches_all_three_branches_concurrently_and_joins`,
is a pre-existing, timing-based concurrency assertion (`span < SLEEP*1.8`)
in a file this task never touched (`git log` shows it unmodified since the
initial commit) and unrelated to generator.py/coverage in any way;
re-running it in isolation three times reproduced both a pass and a fail
under real system load, confirming it is flaky/load-sensitive rather than
a regression introduced by this task. `test_coverage_points_dsl.py` and
`test_urg_summary_reduce.py` were additionally run standalone and pass
(34 and 13, respectively), as did the pre-existing
`test_scoreboard_check_dsl.py`/`test_transaction_scoreboard_dsl.py`/
`test_coverage_analysis.py` files together with the two new ones (135
passed, 0 failed).

## Residual gaps / concerns

- **Part 2's real urg-report parsing is a confirmed, residual, BLOCKED gap
  -- not a completed item.** `parse_urg_report()` raises
  `NotImplementedError` by design; nothing in this repository lets that be
  closed without external evidence (a real urg report sample and a
  confirmed VCS/urg version). Flagging explicitly per this task's
  instructions.
- The optional `coverage_summary_provenance_gate.py` cross-check gate named
  in the design doc's Open Question 3 was, per that doc's own ruling,
  deliberately deferred -- not built, not in this task's scope.
- No change was made to `coverage_analysis.py`'s pure-function/no-database-
  parsing boundary, `env()`/`_connect_phase`, or any per-class UVM
  agent/driver/monitor emitter -- all explicitly out of scope per the
  design doc.
