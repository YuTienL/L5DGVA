# Gap closure: confirmation granularity + locking + 3-artifact presentation

**Scope**: `dv_harness/connectivity.py` — per-row confirmation, lock enforcement,
diff-triggered re-confirmation, and the 3 final presentation artifacts.

**Verdict: DONE.**

**Test summary**: `python -m pytest dv_harness_tests/test_connectivity.py -q` →
**162 passed** (28 new); the wider blast radius
(`test_connectivity_check.py`, `test_question_queue.py`, `test_env_manifest.py`,
`test_bind_mechanism_generator.py`, `test_bind_verification_lint.py`,
`test_mcp_verbs.py`, `test_mcp_manifest_and_schema.py`,
`test_protocol_profile_binding_gate.py`) → **250 + 84 passed**, no failures.

Commit: scoped to `dv_harness/connectivity.py` + `dv_harness_tests/test_connectivity.py`
+ this report only (committed by pathspec — several other workflows had unrelated
files staged in the index concurrently and none were swept in).

---

## Per requirement

### 1. Per-row confirmation, writing `confirmed_by` / `confirmed_date` / `evidence` back to the manifest — was PARTIAL → now CLOSED

Per-row keying was already real (`ConnectivityRow.row_id()` = `dut_instance::interface`,
`scoreboard_entry_row_id()` = `scoreboard::<id>`) and is unchanged. What was missing was
the identity and evidence on the record, and any writeback into the manifest.

- `RowLockStore.confirm_row()` now takes required keyword-only `confirmed_by` and
  `evidence`. Empty/blank/non-string `confirmed_by` raises
  `ROW_CONFIRMATION_REQUIRES_CONFIRMED_BY`; empty `evidence` (None/""/`[]`/`{}`)
  raises `ROW_CONFIRMATION_REQUIRES_EVIDENCE`. Both are hard `ConnectivityError`s
  before any write, so an anonymous or unsourced confirmation cannot be persisted.
  The record is now
  `{content_hash, content, confirmed_by, confirmed_date, evidence, supersedes_hash,
  confirmed_at}` (`confirmed_at` kept as an alias so pre-existing lock files and
  readers of either key stay valid).
- `annotate_rows_with_confirmation()` (new) + `write_connectivity_manifest(..., lock_store=)`
  write that state **into the manifest itself**: every row gains a `confirmation`
  block `{status, row_id, confirmed_by, confirmed_date, evidence, content_hash}`,
  plus a manifest-level `confirmation_summary` with per-status counts and
  `all_rows_confirmed`.
- Omitting `lock_store` is honest rather than silent: every row is stamped
  `UNCONFIRMED` and `all_rows_confirmed: false`, so a manifest can never read as
  reviewed merely because it lacks the evidence that it wasn't.

Tests: `test_confirm_row_records_confirmed_by_date_and_evidence`,
`test_confirm_row_refuses_an_anonymous_confirmation`,
`test_confirm_row_refuses_a_confirmation_with_no_evidence`,
`test_manifest_writes_back_confirmed_by_date_and_evidence`,
`test_manifest_without_a_lock_store_stamps_every_row_unconfirmed`.

### 2. Locking genuinely enforced — was BLOCKED → now CLOSED

The audit's live repro (a second `confirm_row()` with a different `bind_target`/`tier`
on an already-locked row succeeding silently, no error, no diff) no longer reproduces.
`is_locked()` was a passive query nothing consulted; the lock check is now inside
`confirm_row()` itself:

- Locked row + **different** content + no/`wrong supersedes_hash` →
  `RowLockConflictError("LOCKED_ROW_CHANGED_REQUIRES_EXPLICIT_RECONFIRM")`, and the
  existing lock is left untouched (verified on disk, not just in memory).
- `.detail` carries the real field-level `diff`, `expected_supersedes_hash`,
  `previously_confirmed_by`, `previously_confirmed_date` — the error *is* the diff
  artifact a reviewer reads.
- The sanctioned way through is the explicit diff+reconfirm flow: read
  `store.row_diff(row_id, new_content)`, show it, then
  `confirm_row(..., supersedes_hash=store.locked_hash(row_id))`.
- Re-confirming a locked row with **identical** content stays allowed without a
  supersedes hash — a countersignature on unchanged content is not a silent overwrite.

Live re-run of the audit's own repro against the new code:

```
confirmed_by: dv-lead@example.com | evidence: rtl/usb_top.sv:214
locked: True
REFUSED: LOCKED_ROW_CHANGED_REQUIRES_EXPLICIT_RECONFIRM
chip.core.usb0::usb3_if:
  CHANGED  bind_target: 'chip.core.usb0' -> 'chip.core.SOMETHING_ELSE'
  CHANGED  tier: 'T2_STRUCTURAL_MATCH' -> 'T3_NAMING_HEURISTIC'
reconfirm-with-supersedes OK, now confirmed_by: designer@example.com
```

Tests: `test_locked_row_cannot_be_silently_overwritten_with_changed_content`,
`test_lock_conflict_error_carries_the_real_field_level_diff`,
`test_explicit_diff_then_reconfirm_with_supersedes_hash_succeeds`,
`test_reconfirm_with_a_stale_supersedes_hash_is_still_refused`,
`test_reconfirming_identical_content_is_allowed_without_supersedes_hash`.

### 3. Diff-triggered re-confirmation — was READY-with-a-gap → gap CLOSED

The hash-diff core (`diff_rows_needing_reconfirmation()`) was already correct and is
unchanged: an unchanged, already-confirmed row is still genuinely excluded, so a no-op
regeneration stays a no-op for the reviewer. The gap was that it produced a
changed/unchanged flag, never an actual old-vs-new diff.

- `diff_row_fields(old, new)` (new): one entry per differing key,
  `{field, change: ADDED|REMOVED|CHANGED, old, new}`. `old=None` (never-confirmed row)
  yields all-`ADDED`, which is what a first review is.
- `render_row_diff()` (new): the human-readable rendering.
- `RowLockStore.row_diff()`, `confirmation()`, `locked_content()`,
  `confirmation_status()` (new).
- `RowLockStore.pending_reconfirmations()` (new): the actual review worklist — per row
  `{row_id, status, supersedes_hash, current_hash, diff, row}`. The old function answers
  *which* rows moved; this one answers *what* moved in each, which is what a human needs
  to re-confirm.

Tests: `test_diff_row_fields_reports_added_removed_and_changed`,
`test_diff_row_fields_against_never_confirmed_row_is_all_added`,
`test_pending_reconfirmations_returns_what_changed_not_only_which_rows`,
`test_pending_reconfirmations_marks_a_never_confirmed_row_unconfirmed`,
`test_manifest_marks_a_row_changed_since_confirmation_and_shows_the_diff`.

### 4a. Connectivity matrix artifact — READY, re-confirmed, unchanged

`MATRIX_COLUMNS` / `ConnectivityRow` / `build_connectivity_matrix()` /
`render_matrix_table()` re-verified against the current file; columns and the
role-provenance + self-check guards on `write_connectivity_manifest()` are untouched
except for the additive `confirmation` block and `lock_store`/`row_id_fn` parameters.

### 4b. Hierarchy diagram — was PARTIAL (flat edge list, unwired) → now CLOSED

Both sub-gaps were bounded and are closed in place; no separate effort needed.

- **True nesting.** `render_hierarchy_diagram(rows, instance_tree=...)` now accepts the
  real `DutInstanceNode` tree that `capture_dut_instance_tree()` /
  `parse_slang_ast_json()` / `parse_scope_tree_dump()` already produce, and renders the
  actual nested module hierarchy as nested mermaid `subgraph`s labelled
  `instance : module`, with `classDef bindpoint` on every node that is a bind target and
  a dashed `vipmount` node per VIP hanging off it. A bind target **not present in the
  captured tree** goes into an explicit `UNRESOLVED_BIND_TARGETS` subgraph rather than
  being silently dropped — that is precisely the T3/T4 error class this module exists to
  surface. Live output (real run, fabricated bind target deliberately):

  ```mermaid
  flowchart TB
    classDef bindpoint stroke-width:3px;
    classDef vipmount stroke-dasharray: 4 3;
    subgraph N_chip["chip : chip_top"]
      direction TB
      subgraph N_chip_core["core : chip_core"]
        direction TB
        N_chip_core_usb0["usb0 : usb3_subsystem"]
      end
    end
    subgraph UNRESOLVED_BIND_TARGETS["UNRESOLVED_BIND_TARGETS"]
      ...NOT FOUND IN CAPTURED DUT TREE
  ```

  With no tree supplied the original flat `flowchart LR` overview mode is kept
  unchanged and is explicitly documented as such — with no captured instance tree there
  is no hierarchy to draw, and inventing nesting from dotted path strings alone would be
  a guess about module structure this module never makes elsewhere.
- **Confirmation visible on the diagram.** Passing `lock_store` appends each row's
  `[CONFIRMED]` / `[UNCONFIRMED]` / `[CHANGED_SINCE_CONFIRMATION]` to its VIP node label,
  so unreviewed bind points are visible at a glance instead of every edge reading as
  equally settled.
- **Wiring.** `emit_connectivity_artifacts()` (new) is the single entry point that emits
  all three artifacts from one matrix into one directory, with fixed filenames
  (`ARTIFACT_FILENAMES`) so a downstream reader/CI step can find all three by name:
  `connectivity_matrix.json`, `connectivity_matrix.md`, `connectivity_hierarchy.md`,
  `connectivity_questions.md`. It runs `write_connectivity_manifest()`'s guards first, so
  a matrix that fails role provenance or the self-check identity leaves **no** partial
  artifact set behind. It also returns the `pending_reconfirmations` worklist alongside
  the files.

Tests: `test_hierarchy_diagram_renders_nested_subgraphs_and_marks_bind_points`,
`test_hierarchy_diagram_surfaces_a_bind_target_absent_from_the_captured_tree`,
`test_hierarchy_diagram_without_a_tree_keeps_the_flat_overview_mode`,
`test_hierarchy_diagram_shows_confirmation_status_per_bind_point`,
`test_emit_connectivity_artifacts_writes_all_three`,
`test_emit_connectivity_artifacts_pending_worklist_empties_once_confirmed`,
`test_emit_connectivity_artifacts_writes_nothing_when_the_matrix_does_not_reconcile`.

### 4c. Question queue artifact — READY, re-confirmed; presentation added

`build_t4_question_queue_entry()` re-verified: it still delegates into the real
`question_queue.QuestionQueueStore` (2–3 pre-researched options enforced, recommendation
required to be one of them, `affects_pass_fail_verdict=True`). Unchanged.

What was added is only the *presentation* half, which the 3-artifact bullet requires:
`render_question_queue_artifact(question_store)` renders the OPEN/ASSUMED entries read
off `store.list_questions()` — the real persisted queue, never a hand-built list, so the
artifact cannot drift from the queue it claims to present. Optional `context_prefix`
filters to one manifest's own questions when several subsystems share a queue. When no
store is passed, `emit_connectivity_artifacts()` writes an explicit
"this is NOT an assertion that no questions exist" note rather than an empty-looking
clean bill.

---

## Honest residuals (not claimed closed)

- `emit_connectivity_artifacts()` is a real, tested entry point but is still not wired
  into `dv_harness/cli.py` or the `just connectivity-check` recipe — those cover the
  3 **gates**, not the 3 **artifacts**. Wiring artifact emission into the standing
  recipe is a separate, deliberate decision (it needs a per-project source for the
  matrix rows and the captured instance tree, neither of which
  `.dv-harness/connectivity_check.json` currently declares), so it was not silently
  bolted on here.
- The nested-hierarchy mode needs a real captured `DutInstanceNode` tree, which in this
  environment requires `slang` or a live `simv` — neither is on PATH (unchanged
  `NOT_AVAILABLE` reality this module already documents). The renderer is tested against
  a synthetic tree of the exact shape both parsers produce, as this module does
  throughout; it is not claimed to have been run against a live capture.
- Backward incompatibility, deliberate: `confirm_row()` now requires `confirmed_by` and
  `evidence`. All 7 in-repo call sites (all in `test_connectivity.py`) were updated. An
  optional-with-default `confirmed_by` would have re-created the exact hole the
  requirement names, so the break is the point.
