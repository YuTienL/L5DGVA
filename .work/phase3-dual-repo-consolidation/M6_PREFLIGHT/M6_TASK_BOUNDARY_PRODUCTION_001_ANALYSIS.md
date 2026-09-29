# M6-TASK-BOUNDARY-PRODUCTION-001 -- Gap Re-Verification

Prime Directive V2. Re-verifies the Task Boundary production-connectivity
gap from real evidence rather than trusting `CAP-M5M6-VLEVEL-001`'s own
prior report blindly, per this task's own explicit instruction.

## What CAP-ATL-004 actually is (confirmed by direct source read, not assumed)

`dv_harness/task_boundary_conformance.py`'s own module docstring is
explicit: this is a **structural, GIT-CHANGE-SET boundary checker**. It
answers one narrow, mechanically-provable question -- did the FILES a real
git change (working tree or a committed range) actually touch stay inside a
caller-DECLARED allow-list/forbid-list? It does NOT judge file content, does
not decide whether a declared boundary is the RIGHT one, and (module
docstring point 2) a `TaskBoundary` is explicitly "a plain, caller-declared
input... never derived."

This matters for what "production-connect Task Boundary" can honestly mean:
the check is a GOVERNANCE OVERLAY over a task's own git footprint, not a
business-logic gate that reads `protocol`/`role`/`verification_level`
values. Unlike those three fields (all REQUIRED generation FieldControls
after `CAP-M6-C1-001`/GAP-V2-002/`CAP-M5M6-VLEVEL-001`), `TaskBoundary`
remains, by the module's own design, genuinely OPTIONAL -- `task_boundary:
Optional[TaskBoundary] = None`. Omitting it is not a gap; it is the
documented default.

## Stage record (dispatch section 2's own required fields)

```
PRODUCER               = a caller-declared scope contract (a dispatch prompt,
                          a work-item record, or -- as of this task -- a real
                          CLI flag set / dashboard JSON field)
INPUT                   = TaskBoundary(task_id, allowed_path_prefixes,
                          forbidden_paths, require_new_file)
BOUNDARY_CONTRACT       = classify_path(): FORBIDDEN wins over ALLOWED;
                          outside every allowed prefix is OUTSIDE; an
                          add-only boundary rejects a modification
OUTPUT                  = {"task_id", "verdict" (BOUNDARY_HELD /
                          BOUNDARY_VIOLATION / NO_GIT_EVIDENCE /
                          NO_CHANGES_TO_CHECK), "findings", "scope_caveat"}
CONSUMER                = engine.py start_lifecycle()'s own real
                          "if task_boundary is not None:" block
NEXT_STAGE              = the generation dispatch block (VerificationLevel
                          routing -> create_environment()) -- reached ONLY
                          if the verdict is not BOUNDARY_VIOLATION
PRODUCTION_ENTRY_PATH   = BEFORE this task: none (see below). AFTER this
                          task: cli.py `start --task-boundary-id/-allow/
                          -forbid/-new-file-only`; dashboard.py POST
                          /api/start's `task_boundary` JSON field
FAILURE_PATH            = AgentResult(ok=False, raw={"blocked_by":
                          "task_boundary", ...}); a real TASK_BOUNDARY_
                          BLOCKED event; the ordinary Stage-graph dispatch
                          AND the generation dispatch both never run
HUMAN_AUTHORITY         = n/a -- a structural check, not a human decision
                          point (no QuestionOwner/HumanGate involved; the
                          boundary VALUE is a caller declaration, not
                          resolved through Field Resolution/Clarification)
```

## Classification: BEFORE this task

**PARTIAL.** The mechanism itself (`_conform()`/`classify_path()`/
`check_working_tree_conformance()`) and its wiring inside `start_lifecycle()`
were both real, correct, and already tested (`test_task_boundary_
conformance.py`, 19/19; `test_start_lifecycle_dispatch.py`'s own
`test_task_boundary_violation_blocks_dispatch`/`test_task_boundary_none_
declared_is_a_structural_no_op`). What was DISCONNECTED: **zero real
production entry point** could ever construct and supply a real
`TaskBoundary` -- `grep -rln "task_boundary_conformance|TaskBoundary" *.py`
(production files only) found exactly `engine.py` (the consumer) and
`task_boundary_conformance.py` (the module itself); `cli.py` and
`dashboard.py` had no reference at all before this task. Every real caller
(CLI, dashboard, all 11 PROTOCOL_BUILDERS skills) always passed
`task_boundary=None` -- a structural no-op, confirmed by direct source read,
not merely absence of a test.

## A second gap found during re-verification (not assumed, discovered)

Constructing the FIRST-EVER real PASS-path test (a real `TaskBoundary`, a
real git repo, going through `start_lifecycle()`'s own actual field-
resolution/dispatch flow, not a hand-assembled evidence dict) immediately
surfaced a genuine defect: `start_lifecycle()` writes real `.dv-harness/`
bookkeeping files (`lifecycle.json`, `state.json`, `events.jsonl`,
`agents/...`) as an intrinsic, required part of its own operation, BEFORE
the Task Boundary check runs. Every one of those files then appears as a
real, untracked `ADDED` entry in `working_tree_changes()`'s own evidence --
and unless a caller's declared boundary happened to separately allow
`.dv-harness`, EVERY real production call would have spuriously VIOLATED,
regardless of what the caller's own task actually touched. This was
invisible before this task because the only prior test of the mechanism
inside `start_lifecycle()` (`test_task_boundary_violation_blocks_dispatch`)
only ever exercised the FAIL path, where a genuine violation was already
expected -- there was no PASS-path test to reveal the false negative.
Registered and fixed as `GAP-V2-008` (`L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv`)
-- see `M6_TASK_BOUNDARY_PRODUCTION_001_FINAL_REPORT.md` for the fix.

## Classification: AFTER this task

**CONNECTED**, for the sense CAP-ATL-004's own design supports: a real
caller CAN supply real production data through a real supported entry
point (CLI/dashboard), and when supplied, the result genuinely governs
whether the downstream generation dispatch runs. Still, correctly,
OPTIONAL -- omitting it remains a real, documented, non-weakening default,
not a residual gap. See `M6_TASK_BOUNDARY_PRODUCTION_001_PATH_PROOF.md` for
the full per-entry-point, per-level proof.
