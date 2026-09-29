# Gap #3 Closure: Generalized Register-Write-Safety Static Check

Date: 2026-09-03
Status: DONE

## The confirmed gap

A blind literal register write — `` `CPUWRITE4B(`TCA_CTRLSYNCMODE(0), 32'h00000400)` `` in
`D:\DV\Task\USB\usb31_dev_uvm` instead of a read-modify-write — silently clobbered 4 unexamined
bits at their non-zero reset defaults. Because the write "landed" (a readback showed the intended
bit set) and the symptom under investigation did not change, the team spent several further
debugging rounds on a wrong root-cause conclusion ("the fix is ineffective") before recognising
that other live bits had been corrupted by the same write and that the readback proved nothing
about them. "The write landed but the symptom didn't change" is not sound evidence when other live
bits may have been corrupted by the same write.

## What was read first (read-only, per instructions)

- `D:\DV\Task\USB\usb31_dev_uvm\sim\scripts\usb_static_check.py` (1190 lines, all 15 categories) —
  established this project's per-category static-check convention: a `Finding` class, comment/
  string-stripping helpers, depth-aware arg splitting, category numbering with a docstring
  explaining *why* the category exists and citing the real incident that motivated it (category 13,
  the DUT-path-corruption guard, and category 15, the `define`-continuation truncation guard, were
  both read in full as the requested worked examples).
- `dv_harness/uvm_generator/templates/sim_scripts/check/reg_audit.py`, `zero_delay_loops.py`,
  `gen_scaledown.py`, `pattern_rules.py`, and briefly `include_order.py` / `macro_selfcontained.py`
  / `vip_guards.py` / `vip_members.py` / `make_order.py` — established this session's already-
  working genericization convention for this directory: `TARGET_IP`/`IP_PREFIX` env vars (USB kept
  only as the illustrative default), a docstring that explicitly separates "the FRAMEWORK is
  generic" from "the CHECKS content is this template's original USB worked example", no argparse
  (plain `sys.argv` positional args, `main(argv)` prints `__doc__` to stderr and returns 2 on
  missing args), `if __name__ == '__main__': sys.exit(main(sys.argv))`.
- No file under `D:\DV\Task\USB\usb31_dev_uvm\uvm\tb\` was modified, and no build/simulation
  command was run against that tree, per the instruction that a separate investigation agent
  currently owns it.

## What was built

**`dv_harness/uvm_generator/templates/sim_scripts/check/reg_write_safety.py`** (new file, 596
lines combined with its test) — a generic, protocol-agnostic static check:

- **Macro-name pattern is generalized, not hardcoded.** Default regex matches any macro whose name
  ends `...WRITE<digits>B` (covers `CPUWRITE1B/2B/4B`, `HOSTWRITE4B`, and a differently-prefixed
  macro like `HOSTWRITE4B` for a non-USB protocol equally) — overridable via
  `REG_WRITE_MACRO_PATTERN`/`REG_READ_MACRO_PATTERN` env vars for a project whose macros don't
  follow that shape at all.
- **Detection logic**: a write macro call's *value* argument, after stripping one level of wrapping
  parens, is tested as a bare Verilog/C-style literal (`32'h0000_0400`, `'h32`, `0x400`, `1024`).
  It is excluded (not flagged) when either:
  - (a) the value argument is not a bare literal at all — a real RMW's final write hands over an
    expression (`reg_val`, or `(reg_val | 32'h00000400)`), which is exactly the shape a correct RMW
    produces; or
  - (b) a read-modify-write sequence for the *same register macro* is found textually upstream in
    the same file — a variable assigned from a `...READ<digits>B(<same register>...)` call, later
    combined with `|`, `|=`, `&`, or `&=`.
  A candidate surviving both exclusions is reported.
- **Optional register/bit-field table** (`--reg-table PATH.json` or `REG_TABLE_JSON` env var), JSON
  mapping register name → `{width, reset, fields:[{name,hi,lo}]}`. With a table entry available,
  a finding is sharpened from generic WARN into an ERROR naming every field whose reset value
  differs from what the literal leaves there — the exact TCA_CTRLSYNCMODE shape. **Without a table
  (or without an entry for that register), the check never silently passes**: it emits WARN
  "register semantics unknown -- verify manually", per the explicit requirement.

## Real test — run myself, passing

Two layers of verification, both actually executed (not just written):

1. **Direct CLI run** against a synthetic fixture directory
   (`%TEMP%\...\scratchpad\regsafety_fixture`, three `.svh` files, never real project content):
   - `good_rmw.svh` — a real RMW pattern (`CPUREAD4B` → OR with literal → write back the variable).
   - `bad_blind_write.svh` — a blind literal write to a synthetic multi-field register
     (`FAKE_SCALEMODE`).
   - `historical_bug.svh` — the historical-bug-shaped fixture: `` `CPUWRITE4B(`TCA_CTRLSYNCMODE(port), 32'h00000400)` ``
     with a comment noting the register's real non-zero reset default, replicating the actual
     incident.

   Result without `--reg-table`: `good_rmw.svh` never appears in output; `bad_blind_write.svh` and
   `historical_bug.svh` both come back `WARN ... "verify manually"`; exit code 0.

   Result with `--reg-table regmap.json` (synthetic table covering both registers): `good_rmw.svh`
   still never appears; `bad_blind_write.svh` comes back `ERROR` naming 3 clobbered fields
   (EN, POL, GATE); **`historical_bug.svh` comes back `ERROR`, "clobbers 4 field(s) at their
   non-zero reset default -- EN: reset=0x1 -> 0x0, POL: reset=0x1 -> 0x0, MODE: reset=0x1 -> 0x0,
   SEL: reset=0x1 -> 0x0"**, correctly excluding `SYNCEN` (the field the write actually targets,
   reset=0 there); exit code 1.

   This is the direct confirmation that the checker would have flagged the real historical bug: 4
   clobbered fields at non-zero reset default is exactly the "4 unexamined bits...at their
   non-zero reset defaults" from the real incident.

2. **Permanent pytest suite**: `dv_harness_tests/test_reg_write_safety_check.py`, 9 tests, real
   `subprocess` invocation of the actual script (same style as
   `test_makefile_patterns_stub_targets.py`), against fixtures built in `tmp_path`. Covers: no-table
   WARN behavior and exact "verify manually" phrasing; the real-RMW-never-flagged distinction
   (with and without a table); the historical-bug-shape ERROR with the 4 named fields and `SYNCEN`
   correctly *not* named; exit-code-1-on-ERROR (CI-blocking signal); the generic macro-name pattern
   catching a non-USB-style macro name (`HOSTWRITE4B`/`PCIE_LTSSMCTRL`); and the no-argv
   `--help`-equivalent docstring-to-stderr + exit 2 path.

   ```
   dv_harness_tests/test_reg_write_safety_check.py::TestNoRegTable::test_blind_writes_flagged_verify_manually PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestNoRegTable::test_real_rmw_not_mentioned PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestNoRegTable::test_exit_code_is_zero_when_only_warn PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestWithRegTable::test_synthetic_multi_field_register_flagged_as_error PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestWithRegTable::test_historical_bug_shape_is_caught PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestWithRegTable::test_real_rmw_pattern_never_flagged PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestWithRegTable::test_exit_code_nonzero_signals_ci_blocking PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestGenericMacroNamePattern::test_non_usb_style_macro_name_is_still_caught PASSED
   dv_harness_tests/test_reg_write_safety_check.py::TestGenericMacroNamePattern::test_no_help_argv_prints_docstring_and_exits_2 PASSED

   9 passed in 8.63s
   ```

`python -m py_compile` on the new template script also confirmed clean.

## Scope discipline honored

- `D:\DV\Task\USB\usb31_dev_uvm\uvm\tb\` was never written to; no build/sim command was run against
  that tree — the concurrent TCA-hang investigation agent's ownership of that tree was respected.
- Before touching any shared file, `git status --short` was run first; it showed
  `dv_harness/config.py`, `cli.py`, `engine.py`, `CLAUDE.md` already modified by other concurrent
  work. This task's two new files (`reg_write_safety.py`,
  `test_reg_write_safety_check.py`) never overlapped any of those, so no shared file was edited at
  all and no hand-built `git apply --cached` scoping trick was needed.
- `git status --short` before committing confirmed only the two new files were staged (`git add`
  named them explicitly, not `-A`); the commit (`b24290c`, "Add generic register-write-safety
  static check (Gap #3 closure)") contains exactly those two files — verified via the post-commit
  `git status --short` output, which still lists the other workstream's pre-existing modified files
  as untouched (` M`), not staged.

## Recommended next step (explicitly out of scope for this task)

Once the separate TCA-hang investigation concludes and the live `usb31_dev_uvm` build is no longer
being actively worked, run this checker against that real tree, e.g.:

```
python dv_harness/uvm_generator/templates/sim_scripts/check/reg_write_safety.py \
    D:\DV\Task\USB\usb31_dev_uvm\uvm --reg-table <a real DWC_usb31 register/bit-field table>
```

A real register table for that DUT was not built as part of this task (the synthetic
`FAKE_SCALEMODE`/`TCA_CTRLSYNCMODE` table used above exists only under the scratchpad, for testing
this checker) — building the real table from the DWC_usb31 programming guide, and running the
checker against the live tree, is follow-up work for whoever owns that tree next.

## Files touched

- `dv_harness/uvm_generator/templates/sim_scripts/check/reg_write_safety.py` (new)
- `dv_harness_tests/test_reg_write_safety_check.py` (new)
- `.work/gap-close-register-write-safety-report.md` (this report)

Committed as `b24290c` on `master` (two files only, verified isolated).
