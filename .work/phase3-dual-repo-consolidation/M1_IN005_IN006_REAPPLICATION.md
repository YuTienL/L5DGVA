# M1 — IN-005 / IN-006 Canonical Re-Application

Per instruction #5: re-apply the already-approved `IN-005`/`IN-006` canonical
inputs, not by blindly copying v50's dirty working tree.

## IN-005: tools/remote/remote_exec.py

- **Capability**: clarifies (docstring only) that `remote_exec.py` may be invoked
  after a relay started either by a human directly, or by a governed agent
  invocation of `replay.ps1` under the sanctioned auto-reconnect exemption.
- **Source path**: `D:\DV\Task\DV_Agent_Harness_L5\v50\tools\remote\remote_exec.py` (dirty working tree, uncommitted)
- **Source hash**: HEAD blob `ee812e2`; working-tree diff `+6/-4` lines (pure docstring)
- **Source class**: `MIGRATE_REQUIRED_DIRECT` (M0.6 disposition — zero behavioral delta)
- **Canonical target**: `D:\DV\Task\L5_DGVA\tools\remote\remote_exec.py`
- **Provenance / adaptation disclosed**: v50's dirty text says ".\v50\replay.ps1"
  (its own historical relative path, since v50 was itself nested under a parent
  checkout). Adapted to say "replay.ps1" (repository root) to match this
  canonical repo's real layout — `replay.ps1` lives at the canonical repo root,
  not under a `v50\` subdirectory. Also added a forward-reference to the M1
  migration-provenance record for `v1/l5/execution/connectivity.py`'s
  cross-repo status, since that file (cited in the original text) is
  confirmed **absent** from this canonical repo (Parent-only, per M0.6's own
  prior finding, re-confirmed here).
- **Focused test**: `dv_harness_tests/test_remote_exec.py` (18/18 pass,
  pre-existing suite, unaffected by a docstring-only change) + a fresh
  `ast.parse()` syntax check on the edited file.

## IN-006: tools/remote/remote_relay.py

- **Capability**: the "R5-B6 note" reconciling the AI-agent SECURITY BLOCK
  warning with the sanctioned `replay.ps1` auto-reconnect exemption (docstring
  only — `running_inside_ai_agent()`'s actual enforcement code is untouched).
- **Source path**: `D:\DV\Task\DV_Agent_Harness_L5\v50\tools\remote\remote_relay.py` (dirty working tree, uncommitted)
- **Source hash**: HEAD blob `a0d36da`; working-tree diff `+13/-0` lines (pure docstring)
- **Source class**: `MIGRATE_REQUIRED_DIRECT` (M0.6 disposition — zero behavioral delta)
- **Canonical target**: `D:\DV\Task\L5_DGVA\tools\remote\remote_relay.py`
- **Provenance / adaptation disclosed**: same `.\v50\replay.ps1` → `replay.ps1`
  path adaptation as IN-005, plus the same `v1/l5/execution/connectivity.py`
  absence forward-reference.
- **Focused test**: no dedicated `test_remote_relay.py` exists in this suite
  (confirmed: `remote_relay.py`'s own module docstring explicitly forbids
  invoking it live from any agent tool call — see CLAUDE.md's "Remote Linux
  Execution" section — so its logic is tested via `RelayServer.handle_request()`
  unit tests elsewhere, unaffected by this docstring-only change) + a fresh
  `ast.parse()` syntax check.

## Verification performed

```
git diff (v50 working tree) confirmed both diffs are docstring-only, zero
  functional/behavioral code change (re-verified fresh in this task, not
  assumed from the M0.6 record).
ast.parse() on both edited canonical files: OK, no syntax errors.
dv_harness_tests/test_remote_exec.py: 18/18 PASS.
v1/l5/execution/connectivity.py: confirmed absent from this canonical repo
  (ls: No such file or directory) -- Parent-only, consistent with M0.6's
  prior finding, not newly claimed as migrated.
```

## Not done (correctly out of scope)

`v1/l5/execution/connectivity.py` itself is **not** created/migrated here —
that would be Parent capability migration, explicitly excluded from M1.
Both edited files' docstrings now correctly reference it as conditional
("if that file exists in this checkout") rather than asserting it is present.
