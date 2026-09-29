# M1 — Source Immutability Re-Check (Instruction #15)

Re-verified fresh at the end of M1 execution, against the M0/M0.5/M0.6
baseline facts, before M1 closure.

## Parent (SOURCE_A)

No M0 manifest re-hash performed in this pass (not needed — M1 touched no
Parent file; the only Parent file read this session, `dv_harness/multi_agent.py`,
was read-only, never modified/staged/committed, per the standing rule).
`git status --short` on Parent shows the same, pre-existing, already-known
dirty `dv_harness/multi_agent.py` delta (101 insertions/5 deletions) —
unchanged in nature from what M0/M0.6 already recorded; not newly caused
by M1.

```
SOURCE_A_CHANGED_SINCE_M0 = NO
```

## v50 (SOURCE_B)

```
HEAD (expected) = f3fd17326cf3654aca6fd83fad991a3f247e6682
HEAD (actual)   = f3fd17326cf3654aca6fd83fad991a3f247e6682   -- MATCH
```

`git status --short` shows only the same two already-known, already-approved
dirty deltas from before M0 (`tools/remote/remote_exec.py`,
`tools/remote/remote_relay.py` — `IN-005`/`IN-006`, re-applied INTO the
canonical repo this session, never modified IN v50 itself) plus ordinary
`.dv-harness/events.jsonl` runtime-log churn (not source content).

```
SOURCE_B_CHANGED_SINCE_M0 = NO
```

## Worktrees b7a / b7b / b8 (`D:\wt\<name>`)

| Worktree | HEAD | Dirty files | M0.6 baseline dirty-count | Match |
|---|---|---|---|---|
| b7a | `7b2a65a4dc2d40d493451b409669c90ed0b3d9a5` | 1 (`?? dv_harness/rtl_filelist_parser.py`, untracked) | 1 | YES |
| b7b | `c7c7fa09e9ee8336ba102b4495f4b8808408fe0b` | 2 (`M dv_harness/vip_capability_extraction.py`, `M dv_harness_tests/test_vip_capability_extraction.py`) | 2 | YES |
| b8 | `c9cdd06ce586d44f4c0cef00310c10f95ea59f93` | 1 (`M dv_harness/uvm_generator/amba_fabric_generator.py`) | 1 | YES |

**Process note, disclosed**: an initial pass filtered `git status --short`
output with `grep -v "^??"` (staged/modified only), which made `b7a` appear
to have 0 dirty files — a false discrepancy against the expected count of 1.
Caught immediately by re-running the check without that filter: the "1 dirty
file" for b7a was always an **untracked** file, correctly still present,
never lost. Corrected before recording the table above.

```
B7A_CHANGED = NO
B7B_CHANGED = NO
B8_CHANGED = NO
```

## Overall

```
SOURCE_A_CHANGED_SINCE_M0 = NO
SOURCE_B_CHANGED_SINCE_M0 = NO
B7A_CHANGED = NO
B7B_CHANGED = NO
B8_CHANGED = NO
```

No source changed. Per instruction #15, this means M1 does not stop and does
not need to regenerate M0.
