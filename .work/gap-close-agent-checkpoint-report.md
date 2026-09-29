# Gap #4 closure -- Long-running build/investigation agent checkpoint discipline

**Date:** 2026-09-03
**Scope:** Formalize the resume-state-artifact convention that let a fresh
agent recover a real, lost IP_UVM_DV_Gen investigation session this session,
so a less-disciplined agent losing its session the same way is no longer
left with no formal fallback.

## The confirmed gap

The IP_UVM_DV_Gen build agent investigating the TCA NC->USB hang in
`D:\DV\Task\USB\usb31_dev_uvm` became permanently unresumable mid-
investigation this session: a real `No transcript found for agent ID`
failure on `SendMessage`, after the agent had accumulated many hours of
context. A fresh agent picked the investigation back up successfully --
but only because the lost agent's own documentation habits (`CLAUDE.md`'s
trap catalogue, `uvm/docs/dut-request.md`'s open-items list, in-code
retraction comments) happened to already be thorough. That was a side
effect of one agent's general good practice, not a checked, required
convention -- a less disciplined agent losing its session the same way
would have had no formal fallback and the work would have been lost.

## Scope-boundary check performed before building anything

Read `dv_harness/session_snapshot.py` first, per the workflow's own
instruction. Confirmed it covers only the **engine's own CURRENT-RUN
layer** -- `state.json`, `blackboard/`, `plans/`, `react/`, `agents/`,
`lsf/`, rooted at a DVHarness project's `.dv-harness/`, saved at
`DVHarness.run_stage()`/`loop()` stage transitions. It has no reach into a
separately-dispatched Agent-tool subagent's own accumulated context inside
an arbitrary build tree -- `usb31_dev_uvm` has no `.dv-harness/` of its own
and is not a DVHarness project at all. This gap and that mechanism are
genuinely disjoint; nothing here duplicates `session_snapshot.py`.

## What was built

1. **`.claude/skills/CORE/agent-checkpoint-discipline/SKILL.md`** (new) --
   the required convention. Defines the five-section resume-state schema
   (current hypothesis/status, evidence gathered with citations, next
   planned step, decisions pending user/coordinator confirmation, files
   touched this session), the concrete file-location convention (the real
   dual-file `CLAUDE.md` + `docs/dut-request.md` layout as the preferred
   pattern, `RESUME.md`/`STATUS.md` as a single-file fallback), the update
   cadence (after every round that changes investigation state, not only
   at session end), and an explicit table mapping the real
   `usb31_dev_uvm/CLAUDE.md` + `uvm/docs/dut-request.md` content onto each
   schema section -- codifying the pattern that actually worked, per the
   task's explicit instruction, rather than inventing an unrelated format.

2. **`.claude/agents/IP_UVM_DV_Gen.md`** (updated) --
   - Added `CORE/agent-checkpoint-discipline` to the agent's declared
     `skills:` frontmatter list.
   - Added a standing-rule note at the existing file-manifest anchor point
     (where `CLAUDE.md`'s trap catalogue and `docs/dut-request.md` are
     already listed as real deliverables in Step 11's directory tree)
     stating explicitly that these two files are the **required**
     resume-state checkpoint per the new skill, not optional documentation
     polish, with the update-cadence requirement and a pointer to the
     verification checker.
   - Note: while re-reading this file for a stable insertion point, a
     concurrent workstream's own edit (the "Mandatory bind-verification
     checkpoint (2026-09-03, Gap #2 closure)" section, unrelated to this
     gap) landed on disk between my first read and my edits. My two edits
     (frontmatter line, and the standing-rule block after the file-manifest
     tree) applied cleanly against their own surrounding context and are
     scoped to exactly those two insertions -- confirmed via `git diff`
     that no other content was touched or reverted.

3. **`dv_harness/agent_checkpoint_check.py`** (new) -- the concrete,
   checkable verification method. Given a build-tree path:
   - Locates a resume-state artifact under either recognized layout
     (dual-file: `CLAUDE.md` at the root + a `dut-request.md`/`open-items`/
     `RESUME`/`STATUS`-named file under `docs/`, `uvm/docs/`, or the root;
     single-file: `RESUME.md`/`STATUS.md` at the root or under `docs/`).
   - Checks all five schema sections are present, via keyword/pattern
     detection (not requiring a literal header matching the schema name --
     the real `CLAUDE.md`/`dut-request.md` example satisfies every section
     using its own organic vocabulary: `Owner:`, `To close:`, `grep -rn
     "DV_UVM HOOK"`, and dense `file:line` citations throughout the trap
     catalogue) plus a minimum file:line-citation-density check for the
     evidence section.
   - Checks the artifact's mtime against the newest other file in the tree
     (excluding `.git`/`__pycache__`/`node_modules`/`.dv-harness` and, per
     this same agent's own established Step-2 rule that `DUT/`+`VIP/` are
     read-only vendor source, those two directories as well) and flags
     `RESUME_ARTIFACT_STALE` when the gap exceeds a configurable threshold
     (default 6 hours).
   - Typed result (`CheckpointCheckResult` with `.ok`/`.reason`/`.detail`),
     matching this codebase's existing `.reason`/`.detail` typed-error
     convention (`address_map_verifier.AddressMapVerificationError` et al.).
   - CLI entry point: `python -m dv_harness.agent_checkpoint_check
     <build_tree> [--stale-threshold-hours N]`.

4. **`dv_harness_tests/test_agent_checkpoint_check.py`** (new) -- 13 tests,
   synthetic fixtures plus one real, read-only positive case:
   - no artifact present -> `NO_RESUME_ARTIFACT_FOUND`
   - nonexistent build-tree path -> `BUILD_TREE_NOT_FOUND`
   - complete single-file `RESUME.md` -> `RESUME_ARTIFACT_CURRENT`
   - incomplete single-file artifact (missing citations, pending-decisions,
     files-touched sections) -> `RESUME_ARTIFACT_INCOMPLETE`, with the
     correct missing-section set and the sections it DID satisfy correctly
     not flagged
   - single-file artifact resolved from a `docs/` subdirectory
   - complete synthetic dual-file artifact (`CLAUDE.md` trap-catalogue-
     shaped + `docs/dut-request.md` open-items-shaped) -> passes
   - `CLAUDE.md` alone, with no open-items file -> correctly NOT recognized
     as a complete dual-file artifact
   - stale artifact (20h old vs. a file touched now, 6h threshold) ->
     `RESUME_ARTIFACT_STALE`, with the correct staleness gap reported
   - fresh artifact (not stale) -> `RESUME_ARTIFACT_CURRENT`
   - a file freshly touched inside `DUT/` must NOT trigger staleness (the
     vendor-directory exclusion) -> confirmed excluded
   - `check_schema_sections()` unit-level citation-count and missing-set
     behavior (including the fully-empty-text case)
   - **real, read-only check against `D:\DV\Task\USB\usb31_dev_uvm`**:
     confirms the checker recognizes its actual, already-existing
     `CLAUDE.md` + `uvm/docs/dut-request.md` as a schema-complete dual-file
     resume-state artifact (`layout: "dual"`, `missing_sections: []`), and
     asserts both real files' mtimes are byte-for-byte unchanged before and
     after the check (proving the checker never wrote to that tree). Guarded
     with `pytest.mark.skipif` in case the tree is absent on a given host.

## Verification run (this session)

```
$ python -m pytest dv_harness_tests/test_agent_checkpoint_check.py -v
...
13 passed in 0.50s
```

Additionally ran the CLI directly against the real tree as a second, manual
confirmation:

```
$ python -m dv_harness.agent_checkpoint_check "D:/DV/Task/USB/usb31_dev_uvm"
{
  "ok": true,
  "reason": "RESUME_ARTIFACT_CURRENT",
  "detail": {
    "layout": "dual",
    "artifact_paths": [
      "D:\\DV\\Task\\USB\\usb31_dev_uvm\\CLAUDE.md",
      "D:\\DV\\Task\\USB\\usb31_dev_uvm\\uvm\\docs\\dut-request.md"
    ],
    "missing_sections": [],
    "citation_count": 56,
    "staleness_gap_seconds": ~4223,
    "stale_threshold_seconds": 21600
  }
}
```
Exit code 0. No file under `D:\DV\Task\USB\usb31_dev_uvm` was created,
modified, or deleted by this work -- confirmed both by the test's own
before/after mtime assertions and by the module containing no write/edit
calls at all (read-only `Path.stat()`/`Path.read_text()` only).

## Constraint compliance

- No build/simulation command was ever run against the live
  `usb31_dev_uvm` tree.
- No file under `D:\DV\Task\USB\usb31_dev_uvm\uvm\tb\` (or anywhere else in
  that tree) was created, modified, or deleted.
- `usb31_dev_uvm` was used strictly as a read-only test subject, exactly as
  the task requested, to prove the checker recognizes the real artifact
  that already worked.
- Every file this deliverable touches lives inside the v50 harness repo:
  `.claude/skills/CORE/agent-checkpoint-discipline/SKILL.md` (new),
  `.claude/agents/IP_UVM_DV_Gen.md` (updated, scoped diff confirmed),
  `dv_harness/agent_checkpoint_check.py` (new),
  `dv_harness_tests/test_agent_checkpoint_check.py` (new).
- `dv_harness/config.py`, `dv_harness/cli.py`, `dv_harness/engine.py`, and
  `CLAUDE.md` (all flagged as possibly having concurrent uncommitted work)
  were left untouched entirely -- this deliverable needed none of them.
- No commit was made; all four files above are left as uncommitted working-
  tree changes/additions for the user (or a subsequent consolidation pass)
  to review and commit, consistent with not mixing this workstream's diff
  into `.claude/agents/IP_UVM_DV_Gen.md`'s other concurrent (Gap #2) hunk
  in one commit without explicit review.

## Files touched

- `D:\DV\Task\DV_Agent_Harness_L5\v50\.claude\skills\CORE\agent-checkpoint-discipline\SKILL.md` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\.claude\agents\IP_UVM_DV_Gen.md` (updated: +1 frontmatter line, +1 standing-rule block)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\agent_checkpoint_check.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_agent_checkpoint_check.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\gap-close-agent-checkpoint-report.md` (this report)
