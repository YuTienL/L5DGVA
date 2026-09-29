# Gap-Close: Connectivity Manifest — 4 Real Fact-Extraction Inputs

**Verdict: NO_ACTION_NEEDED** — no file modified, no commit made.

**Scope**: `dv_harness/connectivity.py` (now **2749** lines, was 1452 at audit time),
`dv_harness_tests/test_connectivity.py` (now **1899** lines / **162** tests, was 975 / 90).

## Why no action

The audit handed me exactly one closeable item: Input 1's PARTIAL — the
`simv -ucli -do "scope -tree"` half of the spec's OR-alternative had zero
implemented parsing code, docstring prose only.

**That gap was closed by a concurrent workflow before I started**, in commit
`36379b6` "connectivity: implement the simv -ucli \"scope -tree\" half of Input 1".
Confirmed an ancestor of HEAD (`git merge-base --is-ancestor 36379b6 HEAD` → exit 0).
Building it again would have been a duplicate parallel mechanism — exactly what the
task brief says not to do.

## Re-verification of all 4 inputs against current code

| # | Input | Verdict | Current evidence |
|---|-------|---------|------------------|
| 1 | DUT instance tree | **READY** (was PARTIAL) | both halves now real |
| 2 | Interface signal set | **READY** | unchanged, re-confirmed |
| 3 | Existing binds | **READY** | unchanged, re-confirmed |
| 4 | VIP instances / config_db | **READY** | unchanged, re-confirmed |

### Input 1 — DUT instance tree — now READY

- `parse_scope_tree_dump()` at `dv_harness/connectivity.py:479-540` is real code, not
  prose: indent-column-based parent-stack nesting (`connectivity.py:518-538`) producing
  the **same** `DutInstanceNode` type `parse_slang_ast_json()` produces, so the two
  capture methods are genuinely interchangeable downstream.
- `_SCOPE_TREE_ROW_RE` (`connectivity.py:469-476`) handles all three real UCLI
  module-annotation forms (`name (module)` / `name {module}` / `name : module`), ASCII
  tree-glyph indentation, and deliberately **excludes** backslash from the indent class
  so a SystemVerilog escaped identifier (`\u_phy[0]`) does not silently shift a level.
- Fail-closed: unrecognized lines go to `ScopeTreeParseResult.unparsed_lines`
  (`connectivity.py:431-441`, `516`) and surface as `REAL_PARTIAL` / `PARSE_FAILED`
  from `capture_dut_instance_tree()` (`connectivity.py:585-590`) — a silently-dropped
  row would be a silently-missing bind target.
- `capture_dut_instance_tree(scope_tree_path=...)` wired at `connectivity.py:582-601`;
  `check_simv_available()` at `connectivity.py:370-377`; supplying **both** sources
  raises `AMBIGUOUS_DUT_TREE_SOURCE` (`connectivity.py:570-577`) rather than silently
  preferring one and hiding a disagreement; the `NOT_AVAILABLE` detail
  (`connectivity.py:625-639`) now names both capture recipes.
- 9 dedicated tests (`test_connectivity.py:297-427`), including the one that proves the
  point of the work: `test_capture_dut_instance_tree_both_methods_agree_on_flat_paths`
  (`test_connectivity.py:415-430`) asserts `from_scope["instance_paths"] ==
  slang_paths == ["usb0", "usb0.phy"]`.
- Environment honesty re-confirmed live this session: `which slang` → exit 1,
  `which simv` → exit 1, so the no-input path genuinely returns `NOT_AVAILABLE`
  (`connectivity.py:625`), never a fabricated tree.

### Input 2 — Interface signal set — READY (re-confirmed)

- `build_interface_fingerprints()` `connectivity.py:685-706` — extends
  `verible_parser.ModuleInfo.ports`, does not re-implement RTL parsing; accepts both
  live-dataclass and persisted-dict forms.
- `match_protocol_fingerprint()` `connectivity.py:709-725` — `matched = not missing`,
  i.e. full-required-subset only; a partial hit reports `matched=False` and falls to T3
  rather than a false T2 auto-accept. `PROTOCOL_FINGERPRINTS` at `connectivity.py:671`
  with its honest unverified-non-AMBA caveat at `connectivity.py:654-670`.
- `which verible-verilog-syntax` → `/c/Users/peter.lin/bin/verible-verilog-syntax`
  (exit 0), so this input is genuinely usable today.

### Input 3 — Existing binds — READY (re-confirmed)

- `grep_existing_binds()` `connectivity.py:757-787` — real `Path.rglob` walk +
  per-line regex, no external `grep` binary dependency, works identically on this
  Windows environment. `_BIND_LINE_RE` `connectivity.py:732`;
  `parse_bind_line()` `connectivity.py:745-754`;
  `find_existing_bind_for_target()` `connectivity.py:790`.
- The one input with no tooling dependency at all — works unconditionally.

### Input 4 — VIP instances / config_db — READY (re-confirmed)

- `parse_topology_dump()` `connectivity.py:819`, `_TOPOLOGY_ROW_RE`
  `connectivity.py:816` — hierarchy recovered from real leading-whitespace indent.
- `parse_config_db_trace()` `connectivity.py:881-893`, `_CFGDB_RE`
  `connectivity.py:876-878`.
- **The set-without-get check is genuinely implemented**, not conceptual:
  `find_set_with_no_get()` `connectivity.py:896-903` —
  `gets = {(e.field, e.context_path) for e in events if e.op == "GET"}` then returns
  every SET whose key is absent. Test-verified against a fixture carrying a real
  orphaned `orphan_vif` SET.
- `capture_vip_topology()` `connectivity.py:913-944` — honest `NOT_AVAILABLE` with the
  real capture recipe when no logs supplied; `REAL` structured
  `components`/`config_db_events`/`set_with_no_get` when they are.

## Test summary

`python -m pytest dv_harness_tests/test_connectivity.py -q` → **162 passed in 6.23s**
(all green on unmodified HEAD; the audit's baseline was 90, the concurrent scope-tree
work plus other concurrent connectivity commits brought it to 162).

## Files touched

None. No commit made — there was nothing left to build in this scope.
