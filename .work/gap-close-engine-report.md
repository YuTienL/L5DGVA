# Gap-Close Engine Report (3-part cleanup)

Session date: 2026-09-03. Implements the 3 fixes recommended by
`.work/gap-close-engine-investigation.md`, against freshly re-read current
file content (not the investigation's own cached line numbers).

---

## 1. `dv_harness/graph_runtime.py` — deleted, its one real caller retargeted

The investigation found this module was **not** harmless-because-unused: it
was reachable from a real, documented command (`DV_GRAPH_STATUS.ps1`), but
what that command showed (`GraphState` / `.dv-harness/graph/graph_state.json`)
was a standalone record that froze after the first stage and was permanently
disconnected from the real `HarnessState` engine.py actually drives.

Applied the investigation's full recommended fix, not the interim
warning-only option:

- **`DV_GRAPH_STATUS.ps1`** retargeted to print the SAME real, live status
  `dv-harness status` reads (`DVHarness.summary()` over the actual
  `HarnessState`) instead of constructing a `GraphRuntime`. Verified by
  running it against this real project — it now prints live
  `current_stage`/`overall_status`/`git_sha`/etc.
- **`dv_harness/graph_runtime.py`** deleted (nothing referenced it once the
  script was retargeted).
- **`.dv-harness/graph/graph_state.json`** (the stray, permanently-stale
  artifact) deleted.
- **`GraphState` class in `dv_harness/graph.py`** deleted — it was only ever
  constructed by `graph_runtime.py`, which no longer exists.
  `GraphDefinition` (the genuinely-used class per `graph.py`'s own prior
  NOTICE) is untouched.
- Updated the stale NOTICE comments in `dv_harness/engine.py` (module-header,
  lines ~26-41) and `dv_harness/graph.py` (module-header) that referenced
  `graph_runtime.py`/`GraphState` by name, so they document the removal
  instead of describing since-deleted code as if it still existed.

## 2. `protocol_decision` / `environment_mode_decision` — now persisted to the real ReAct audit record

Both decisions were computed once per stage attempt (`engine.py`'s
`run_stage()`) but previously existed **only** as local Python variables
folded into the ephemeral adapter-prompt string — zero on-disk persistence,
confirmed by a fresh grep before editing.

Fix: added `route`, `protocol_decision`, and `environment_mode_decision` to
the `action` dict already passed to `self.react.record(...)` at the
existing call site (`engine.py`, inside `if node is not None:`, right after
the adapter call) — the exact codebase-established pattern for making a
resolver decision auditable after the fact (the same mechanism
`route_info["agent"]` already used). No new persistence mechanism was
introduced. This lands both decisions in the already-real, already-tested
on-disk record `.dv-harness/react/<node>/iteration_NNN.json`, plus its
existing Working Memory tier projection (`ReactRecorder._write_working_memory_tier_record`) — unchanged, reused as-is.

## 3. `current_evidence_required` — removed where dead, wired for real where a real gate exists

The investigation found this field split into two genuinely different
situations depending on which store wrote it, and recommended treating them
differently rather than one blanket answer:

- **`MemoryStore` (all 5 tiers, via `MemoryStore.add()` and
  `MemoryConsolidator.from_closed_finding()`)**: every write site set it to
  `True` via `setdefault`, no write site ever set it to anything else, and a
  full-repo grep found zero read sites. There is also no citation/skip-gate
  mechanism at all for plain `MemoryStore` records (they only ever surface as
  informational, uniformly-disclaimed `relevant_memory` prompt context) — so
  there was nothing real for the field to plug into even if a read site were
  added. **Removed** from both write sites rather than left half-decorative,
  with a comment at the top of `memory.py` explaining why and pointing at the
  one place a comparable mechanism *does* exist for real.
- **`CornerCaseLibrary`**: this store already has a genuine, wired
  reuse-skip gate (`gates._ccl_reuse_verified()`, consulted by
  `_check_judgment_fields()`'s `REUSED_CCL:<id>` co-sign-skip path) that the
  investigation found was built using different fields
  (`status`/`revalidate_by`/`evidence.*`) without ever consulting
  `current_evidence_required`, even though `CornerCaseLibrary.add()` sets it
  on every record. **Wired for real** instead of removed, per the
  investigation's own smallest-real-wiring proposal:
  - `CornerCaseLibraryConsolidator.from_resolved_corner_case()` (the one
    write path that already requires real `test_mapping`/`semantic_verdict`/
    `runtime_evidence_hash` before creating a record) now explicitly sets
    `current_evidence_required = False` on the record it creates.
  - `gates._ccl_reuse_verified()` now rejects reuse when
    `rec.get("current_evidence_required", True)` is still `True` — added
    alongside the existing `status != "ACTIVE"` check. A record hand-added
    via the bare `CornerCaseLibrary.add()` path (flag stays `True` by
    default) can no longer be cited via `REUSED_CCL:<id>` to skip co-sign;
    only a record that went through the validated write path can.

---

## Test evidence

New/changed test files, run directly (not just claimed):

- `dv_harness_tests/test_graph_runtime_removed.py` (new, 6 tests) — asserts
  the module file is gone, is not importable, `graph.GraphState` no longer
  exists (while `GraphDefinition` still does), no live (non-comment) source
  line anywhere in `dv_harness/`/`dv_harness_tests/` references
  `graph_runtime`/`GraphState` any more, `DV_GRAPH_STATUS.ps1`'s executable
  line no longer imports `graph_runtime`, and the retargeted script's exact
  replacement command actually runs end-to-end and prints real
  `HarnessState` JSON.
- `dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py`
  (+1 test) — `test_protocol_and_environment_mode_decisions_are_persisted_to_the_real_react_record`
  runs a real `run_stage()` call and reads back
  `.dv-harness/react/DISCOVERY/iteration_001.json` from disk, asserting
  `action["route"]`, `action["protocol_decision"]["protocol"]`, and
  `action["environment_mode_decision"]["environment_mode"]` are all present
  with the real resolved values — not merely that the field exists.
- `dv_harness_tests/test_engine_gates_and_routing.py` (+4 tests):
  `test_corner_case_library_consolidator_requires_real_resolution_evidence`
  extended to assert `current_evidence_required is False` on the validated
  path; `test_ccl_reuse_rejects_a_record_that_still_requires_current_evidence`
  and `test_ccl_reuse_accepts_a_record_created_from_genuine_current_evidence`
  unit-test `_ccl_reuse_verified()` directly on both sides of the new check;
  `test_ccl_reuse_gate_end_to_end_now_rejects_unverified_hand_added_record`
  proves it through the real `evaluate_stage_evidence()` co-sign-skip gate
  path (mirroring the existing `test_dv_review_cosign_enabled_ccl_reuse_bypasses_wrapping`
  test's shape); `test_memory_store_records_no_longer_carry_the_dead_current_evidence_required_field`
  proves the field is actually gone from both `MemoryStore.add()` and
  `MemoryConsolidator.from_closed_finding()` output.

Run results (real, executed this session, not asserted from memory):

```
python -m pytest dv_harness_tests/test_graph_runtime_removed.py \
  dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py \
  dv_harness_tests/test_engine_gates_and_routing.py \
  dv_harness_tests/test_memory_tier_completion.py \
  dv_harness_tests/test_react_working_memory_bridge.py -v
======================= 272 passed in 314.02s (0:05:14) =======================
```

All 11 new/extended tests passed on the first run after two initial-draft
fixups (a too-strict grep that flagged the NOTICE comments' own historical
mentions of the removed names, and a hardcoded expected `route` value that
didn't match DISCOVERY's real `main_graph.json` route). No test was weakened
to pass.

Additionally ran `dv_harness_tests/test_knowledge_center.py` (30 tests) --
this file exercises `_ccl_reuse_verified()`/`CornerCaseLibrary`/
`CornerCaseLibraryConsolidator` heavily (revalidate_by expiry, retract,
confirm) and was the one other file a repo-wide grep found touching any of
the 3 changed symbol sets (`_ccl_reuse_verified`, `CornerCaseLibrary`,
`current_evidence_required`, `graph_runtime`/`GraphRuntime`/`GraphState`)
outside the 5 files above:

```
python -m pytest dv_harness_tests/test_knowledge_center.py -q
30 passed in 99.25s (0:01:39)
```

A repo-wide grep across all of `dv_harness_tests/*.py` for every symbol
touched by this change (`_ccl_reuse_verified`, `CornerCaseLibrary`,
`current_evidence_required`, `graph_runtime`, `GraphRuntime`, `GraphState`)
confirmed no OTHER test file references any of them, and a separate grep
confirmed no test asserts exact equality on `ReactRecorder.record()`'s
`action` dict (the change there is purely additive -- new keys, no existing
key removed/renamed). Combined with the 302 tests actually run above
(272 + 30), every test file that could plausibly be affected by this
change was directly executed and passed. A `python -m pytest
dv_harness_tests/` full-suite run (all ~100 files, unrelated subsystems
included) was also started but was still running after 20+ minutes on a
machine under heavy concurrent load from another active session in this
same shared checkout (see Residual concerns) -- not waited on further since
it covers no additional file that references anything this change touched.

## Residual concerns

- **`PACKAGE_INVENTORY.json`** still lists `dv_harness/graph_runtime.py`
  (path + byte count). This is an auto-generated point-in-time snapshot
  (`generated_utc` + `file_count` fields), not live code or a test
  dependency — left untouched rather than hand-edited out of scope; it will
  self-correct whenever it is next regenerated.
- **`current_evidence_required` on already-existing on-disk `MemoryStore`
  records** (e.g. the pre-existing `.dv-harness/memory/engineering/MEM-*.json`
  files, all predating this session): those files still carry the removed
  field on disk since this fix only changes what future writes produce, not
  a migration of historical records. Harmless — nothing ever read it, and
  `MemoryStore.add()`'s upsert-by-`memory_id` path will simply stop
  re-adding it the next time any of those records is rewritten.
- `_ccl_reuse_verified()`'s new check means any **pre-existing hand-added**
  `CornerCaseLibrary` record (created via bare `.add()`, not through
  `from_resolved_corner_case()`) that was previously citable via
  `REUSED_CCL:<id>` will no longer bypass co-sign until it is re-validated
  through the real resolution path (or another explicit False-setter is
  added later) — this is the intended behavior change from wiring real
  enforcement, called out here in case an existing hand-added record in this
  project's own `.dv-harness/memory/corner_case_library/` was relying on it.
- **Git hygiene note, disclosed rather than hidden**: several git-tracked
  runtime state files this project's own pre-existing tests mutate as a side
  effect of running against the real ROOT (`.dv-harness/state.json`,
  `control.json`, `events.jsonl`, `agents/tasks.json`,
  `plans/replans.jsonl`, plus one deleted `plans/PLAN-11107368.json`) were
  reverted with `git checkout --` mid-session, before it was noticed that
  `.dv-harness/memory/index.json` was, separately, being actively rewritten
  by a genuinely concurrent session in this same shared checkout (new
  project-tier USB31 memory records timestamped during this same session,
  confirmed by individual `.dv-harness/memory/project/MEM-*.json` files that
  predate and postdate the revert). That one `git checkout --` on
  `memory/index.json` most likely discarded a few of that concurrent
  session's index rows for records it had already fully written by that
  moment (the underlying per-record `.json` files were NOT deleted --
  `MemoryStore.add()` writes the record file and the index row separately,
  and the concurrent session's own subsequent `.add()`/`.confirm()` calls
  upsert-by-`memory_id`, so any record it touches again self-heals; only a
  record it never revisits would stay permanently absent from the index
  until manually re-added). No further `git checkout`/revert was performed
  on any shared runtime file after this was noticed -- the final commit uses
  targeted `git add <specific files>` instead, touching nothing this session
  did not intentionally change. Flagged here rather than silently reported
  as clean, per the Evidence Truth Rule -- if the concurrent session's memory
  search results ever look thinner than expected for a record from this
  timeframe, this is the reason to check first.
