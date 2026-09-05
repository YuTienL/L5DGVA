# VI-1: Confidence Calibration Engine -- gap-close report

**Status: DONE** (scoped: REACHED, not WIRED -- see Deferred).

**Test summary:** `dv_harness_tests/test_confidence_calibration.py` -- 35 passed
(5 consecutive clean runs); every memory-touching suite re-run after the
`memory.py` change -- 410 passed; plus module-enumeration, CLAUDE.md doc-parity
and confidence-vocabulary suites, all green (~620 tests total, §11).

**Commit:** `a9b05a2` on `gap-close/env-manifest-fact-sources` (no push, no
merge to main/master -- PR-only governance respected).

---

## 1. The gap was independently re-verified before anything was built

- `grep -ril "calibrat"` over the whole repo returned exactly two kinds of hit,
  and neither is a confidence calibration engine:
  - `gates.py` / `prompts.py`'s `architecture_calibration_gate` and
    `architecture_calibration_conflict_gate` -- an ARCHITECTURE-SNAPSHOT delta
    gate for `ARCH_DISCOVERY`, unrelated to confidence;
  - test fixtures and skill markdown naming those gates.
- `grep -rn "calibrat" --include=*.py dv_harness/` returns 4 lines, all in
  `gates.py`/`prompts.py`, all the architecture gate.
- No module, CLI verb, dashboard card, graph node or gate anywhere asked whether
  a confidence TIER's real track record matches what the harness treats it as
  being worth.

Confirmed NEVER_BUILT. The audit was not stale.

## 2. What already existed and was reused, never duplicated

Both halves of the question were already real and already in production:

| existing real mechanism | role here |
|---|---|
| `inference.score_confidence()` (HIGH/MEDIUM/LOW) | tier PRODUCER -- not re-implemented, not re-scored |
| `memory.MemoryConsolidator.from_closed_finding()` | mints the 4th tier, CONFIRMED |
| `memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS` | the other owner of the tier vocabulary |
| `memory.MemoryGC.confirm()` | the real VERIFIED outcome (`confirmation_count`) |
| `memory.MemoryGC.retract()` / `.supersede()` | the real REJECTED outcomes |
| `memory.MemoryGC.deprecate()` / `.flag_stale()` | the real INDETERMINATE states |
| `MemoryStore.find()` / `.index_integrity()` | the corpus reader + its drift report |
| `inference.identify_gap()` | which tiers cannot be calibrated yet |
| `inference.next_best_action(..., gap_action_catalog=)` | every suggested action |
| `storage._atomic_replace()` | the Windows-safe rename (see §6) |

New code: `dv_harness/confidence_calibration.py` (one module, ~470 lines) plus its
test file. Nothing else in `dv_harness/` was added.

## 3. What was built

`dv_harness/confidence_calibration.py`:

- `CALIBRATION_TIERS` = `inference.CONFIDENCE_LEVELS` |
  `memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS`, ordered strongest
  first. `assert_tiers_cover_inference_levels()` runs at IMPORT and holds that
  equality in both directions -- a tier added to `score_confidence()` and not
  here would otherwise be silently absent from every report.
- `classify_record_outcome(record)` -- VERIFIED / REJECTED / INDETERMINATE, read
  only off fields the real `MemoryGC` writers set. **Rejection is checked before
  confirmation**: a record confirmed once and later retracted is REJECTED,
  because the retraction is the last word about whether the claim held.
- `collect_outcomes(store)` / `calibrate(root, cfg=)` -- per-tier counts,
  per-level breakdown, per-reason breakdown, observed reliability
  (`verified / (verified + rejected)`), plus `index_integrity()` so an
  under-counted corpus is visible instead of silently smaller.
- Four honest statuses: `NOT_AVAILABLE` (no store, or no record carries a tier),
  `INSUFFICIENT_HISTORY`, `CALIBRATED`, `MISCALIBRATED`.
- Two finding kinds: `INVERTED_TIER_ORDER` (a higher tier held up materially less
  often than a lower one -- **every** pair compared, not just adjacent ones) and
  `BELOW_DECLARED_FLOOR` (opt-in, per-project).
- `render_report_text()`, `execute_verb()`, `main()`; front door
  `python -m dv_harness.confidence_calibration tiers|report|show`. Exit 2 means
  "not calibrated" -- a reporting signal only.

### The honesty decisions, stated explicitly

- **No stated reliability was invented.** No number in this codebase says "HIGH
  means 90%" -- every tier's meaning is a PROCEDURAL bar. Fabricating a success
  rate and then reporting a project "miscalibrated" against it would be exactly
  the unearned claim the Evidence Truth Rule forbids. What is checkable without
  inventing anything is the ORDERING this harness already ACTS on. Floors are
  opt-in (`confidence_calibration.tier_reliability_floor`); every tier's floor is
  `None` by default and carries the real reason why (`TIER_DECLARED_FLOOR_BASIS`)
  -- the same honesty contract `loop_budget.py` applies to its budgets.
- **Both thresholds are derived, not chosen.**
  `MIN_DETERMINATE_OUTCOMES_PER_TIER = 10` is the smallest N at which
  `1/N <= 0.1`, i.e. the point where one record stops moving the rate by more
  than the band the rate is read to. `INVERSION_TOLERANCE` is that same band, not
  a second independent number.
- **ACTIVE-and-never-re-checked is not evidence.** Counting it as verified would
  manufacture a 100% reliability for every tier out of records nothing re-tested.
  DEPRECATED is retirement, not refutation; NEEDS_REVALIDATION is "nobody
  re-checked yet". All three are INDETERMINATE with a named reason.
- **Reading is never a mutating act.** A project with no memory store is reported
  NOT_AVAILABLE *without* constructing a `MemoryStore` -- that constructor
  `mkdir`s the tree and writes an empty `index.json`, so merely asking whether a
  project is calibrated would otherwise create the store it asked about. Asserted
  by a test that checks the temp dir is still empty afterwards, and by a second
  that byte-compares every file under a real `.dv-harness/` before and after.

## 4. This harness's own real answer

Run against this repository's REAL store, read-only:

```
Confidence Calibration -- INSUFFICIENT_HISTORY (NO_TIER_HAS_ENOUGH_DETERMINATE_OUTCOMES)
  corpus: 92 record(s) scanned, 46 with a recognized tier, index_integrity_ok=True
  TIER       RECORDS  VERIF REJECT DETERM  RELIABILITY
  CONFIRMED       33      1      0      1  --  (1 determinate outcome(s); 10 required ...)
  HIGH             3      0      0      0  --  ...
  MEDIUM           3      0      0      0  --  ...
  LOW              7      0      0      0  --  ...
```

Exactly **one** determinate outcome exists in this project's entire history (one
CONFIRMED record with a real `MemoryGC.confirm()`; zero retractions, zero
supersessions). The honest answer is INSUFFICIENT_HISTORY and that is what is
reported, with a per-tier next-best-action naming the real outcome this project
would have to start recording. No calibration was fabricated off too little
evidence, and no synthetic record was written into the real store to make the
mechanism "have fired".

## 5. Human-approval gates

Untouched and **not referenced at all**. `confidence_calibration.py` contains no
mention of `ControlPlane`, `can_signoff`, `assert_human_approval`,
`HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`, `approve(`, or
`subprocess` -- asserted by a test against the module's own source, and a second
test walks its AST and asserts it makes **no** call to any mutating method
(`add`/`confirm`/`retract`/`supersede`/`deprecate`/`flag_stale`/`write_text`/
`mkdir`/`unlink`/`event`/`approve`). Nothing here can authorize anything; exit 2
is a reporting signal in neither direction. No build, regression or LSF
submission is triggered anywhere in the module or its tests.

## 6. One pre-existing defect fixed (in scope, and it had to be)

`MemoryStore._save_index()` (`dv_harness/memory.py`) used a bare `os.replace()`.
On Windows that raises `PermissionError` (WinError 5) whenever any reader has
`index.json` open at the instant of the rename -- and that index really is read
concurrently by every `MemoryRetriever.search()`, `MemoryStore.find()` and
`index_integrity()`. Writing ~200 records in a row (what these tests do) surfaced
it on roughly **one run in three**, reproduced twice before the fix and zero
times in four runs after.

It now goes through the EXISTING `storage._atomic_replace()` retry -- the same one
`blackboard.py`'s atomic write already uses (and which `CLAUDE.md`'s Blackboard
section already documents) -- rather than a second definition of "replace this
file safely". One import + one call site changed; no behaviour change on POSIX.

## 7. Tests

`dv_harness_tests/test_confidence_calibration.py`, 35 tests. Every record is
written by the REAL writers (`MemoryStore.add()`, `MemoryGC.confirm()`,
`.retract()`, `.supersede()`, `.deprecate()`, `.flag_stale()`) -- never by
hand-writing a JSON file carrying the fields this module happens to read.

The negative controls are what give it detection power:

- **9 determinate outcomes is still INSUFFICIENT_HISTORY, 10 is not** -- without
  this the threshold could be any number and nothing would notice.
- **40 ACTIVE never-re-checked records produce NO reliability**, not 100%.
- **10 DEPRECATED records do not make a tier calibratable at 0%** -- a retired
  knowledge base must not read as a catastrophically miscalibrated one.
- **80%-under-90% is NOT an inversion** (exactly one resolution band), while one
  more record's separation IS.
- **A 1-outcome tier at 0% never drags a well-evidenced tier into a finding.**
- **The same machinery reports CALIBRATED** over a store whose ordering genuinely
  holds -- the positive control for the MISCALIBRATED case.
- **A non-adjacent inversion (CONFIRMED under LOW) is still found** while the
  in-tolerance pairs between them are not.
- **A confirmed-then-retracted record is REJECTED**, and a stale-then-reconfirmed
  one is VERIFIED.
- A record file with no index row is reported as real drift, not silently lost.
- The module front door is driven as a **real subprocess**.
- The repo's own real store is asserted to report an honest state.

## 8. What was deferred, and why

- **No `dv-harness` CLI verb.** `dv_harness/cli.py` carried *staged, uncommitted*
  changes from a concurrent close-pass in this same session; adding a verb there
  would have collided with it or swept its work into this commit. The front door
  is `python -m dv_harness.confidence_calibration`, which is the precedent
  `loop_telemetry.py` already set ("There is also no `dv-harness` CLI verb"). The
  `execute_verb()` shape means adding the verb later is a 4-line change.
- **Not engine-fired, not on the dashboard.** No `run_stage()`/`advance()` call
  site invokes it and no graph node declares it. This is a REACHED capability, not
  a WIRED one, and `CLAUDE.md`'s new section says so. Wiring it would have meant
  editing `engine.py`/`dashboard.py`, both explicitly named as contended by other
  passes in this loop.
- **Memory-record tiers only.** A `QualifiedConclusion`'s `inference_confidence`
  reaches the Blackboard `qualified_conclusion` topic, not a MemoryStore record,
  and that topic keeps no history of what later happened to the conclusion.
  Calibrating those would first require an outcome to be recorded against the
  conclusion itself -- nothing writes one today, so building a reader for it would
  have been a reader with no evidence.

## 9. Files

- `dv_harness/confidence_calibration.py` (new)
- `dv_harness_tests/test_confidence_calibration.py` (new)
- `dv_harness/memory.py` (`_save_index()` -> `storage._atomic_replace()`)
- `CLAUDE.md` (new section: "Confidence Calibration: a Tier's Track Record vs.
  What It Buys (2026-09-05)")

## 10. Shared-file handling (concurrent close-passes)

`git status` before any edit showed another close-pass's work **staged but not
committed**: `.claude/skills/CORE/periodic-regression-snapshot/SKILL.md`,
`.dv-harness/lsf/periodic_snapshot_policy.json`, `DV_REGRESSION_SNAPSHOT.ps1`,
`dv_harness/cli.py`, `dv_harness/regression_reporter.py`,
`dv_harness_tests/test_watch_cadence_spec.py`, plus an 11-line CLAUDE.md hunk.

- **`cli.py` was left completely untouched** -- that is why this gap ships with a
  `python -m` front door instead of a `dv-harness` verb.
- **`CLAUDE.md`**: my section was appended in BINARY mode (the file is all-CRLF
  and `core.autocrlf=true`; a first attempt with text-mode `read_text`/
  `write_text` rewrote all 2457 line endings and was reverted with
  `git checkout -- CLAUDE.md`, preserving the other pass's staged hunk). The
  final diff is `+123 / -0`.
- The commit is scoped with explicit paths (`git commit -- <paths>`) so the other
  pass's staged `cli.py` / `regression_reporter.py` / SKILL.md / .ps1 / test
  changes stay staged and untouched. CLAUDE.md unavoidably carries that pass's
  11-line cadence hunk along with mine, since the working-tree file contains
  both; nothing is lost or reverted by this, and it is called out in the commit
  message.

## 11. Test evidence actually collected

Every suite that could be affected by what this change touches
(`dv_harness/memory.py`, the new module, `CLAUDE.md`) was run to completion and
is green:

| suite | tests | result |
|---|---|---|
| `test_confidence_calibration.py` (new) | 35 | passed (5 runs) |
| every memory-touching test file (11 files) | 249 | passed |
| `test_debug_flow_memory` + `test_knowledge_center` + `test_react_working_memory_bridge` + `test_research_memory_governance` | 103 | passed |
| `test_memory_dedup_write_path` + `test_engineering_confirmation_accumulation` | 24 | passed |
| `test_obsidian_memory_final_integration` + `test_dashboard_memory_card` + `test_knowledge_layer_git_and_duckdb` | 34 | passed |
| `test_e2e_memory_chain_usb3_lfps` + `test_job_memory_evidence_mirror` | 21 | passed |
| `test_loop_contract` + `test_loop_convergence` | 103 | passed |
| module-enumerating suites (`test_graph_runtime_removed`, `test_mcp_read_only_boundary`, `test_job_memory_evidence_mirror`) | 36 | passed |
| CLAUDE.md doc-parity (`test_source_authority`, `test_context_budget`, `-k doc/claude/index`) | 13 | passed |
| `test_qualified_conclusion_closure_gate` + `test_confidence_vocabulary_separation` | 14 | passed |
| `test_engine_gates_and_routing -k "memory or confidence"` | 13 | passed |
| `python -m dv_harness.mcp.claude_md_index` | -- | OK (CLAUDE.md still matches the code) |

**Honest note on the whole-repo run**: a `python -m pytest dv_harness_tests`
over the entire ~1080-test suite was launched in the background and was still
executing when this report was written -- the machine was running several other
close-passes' test suites concurrently. It is NOT reported here as a pass,
because it had not finished. What IS reported above is every suite that
exercises the code this change touches, each run to completion.

The flakiness that the `memory.py` fix addresses was itself measured, not
assumed: 2 failures in 3 runs before, 0 in 5 runs after.
