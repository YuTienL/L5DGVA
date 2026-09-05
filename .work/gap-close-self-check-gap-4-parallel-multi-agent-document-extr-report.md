# Gap 4 — Parallel Multi-Agent Document-Extraction Orchestration

**Verdict: DONE.** The audit finding was confirmed accurate on both halves, and
the missing half was built for real.

Mode: **LOCAL_ANALYSIS** throughout. No network call, no VCS/simv invocation, no
LSF submission, no remote server contact.

---

## 1. Re-confirmation of the audit's evidence

Both of the audit's Part B claims re-verified from source before building
anything:

- `.dv-harness/graph/main_graph.json` — `grep -n "parallel_group"` returns 30+
  rows, of which exactly **three** are non-null and all three are `ANALYSIS_G1`
  (lines 112, 122, 138). No document-extraction group exists.
- `.claude/workflows/` contains exactly two files:
  `gap-closing-evidence-consensus.js`, `rca-multi-agent-fusion.js`. Neither
  names any extractor module.
- `grep -n "ThreadPoolExecutor\|concurrent.futures" dv_harness/*.py` finds real
  fan-out in exactly two places: `engine.py:4477` (`_advance_with_fanout`, the
  graph `parallel_group` executor) and
  `subsystem_architecture_analysis.py:742` (`run_per_subsystem_analyses`).
  Neither is scoped to documents.

**One correction to the audit.** The audit's Part B says the codebase "has
exactly two real parallel-dispatch mechanisms" and names `_advance_with_fanout`
plus the two workflow scripts. It missed
`subsystem_architecture_analysis.run_per_subsystem_analyses()`
(`dv_harness/subsystem_architecture_analysis.py:721-747`) — a real
`ThreadPoolExecutor` fan-out over independent read-only analysis units, with an
explicit written justification for why parallelism is safe there and a
deterministic sort of collected results. That omission mattered: it is the
in-repo precedent this gap should be closed by following, and following it is
what kept this from being a new bespoke concurrency mechanism.

Part A's per-category table was spot-checked and holds, including the two
`NEVER_BUILT` categories (40c VIP examples, 40h IP source) and
`doc_extraction.py:1-7`'s self-declared orphan status.

---

## 2. What was built

### `dv_harness/doc_extraction_fanout.py` (new, 807 lines)

The dispatch layer, and nothing else. Every category's work is performed by the
same real extractor its own single-purpose CLI verb already calls; no adapter
contains extraction logic of its own.

- **Concurrency pattern reused, not invented.** One `ThreadPoolExecutor` over
  independent read-only units, results sorted back into declared category order
  — `run_per_subsystem_analyses()`'s shape. No new `parallel_group` graph node
  was added: these extractors are not graph stages, and inventing one would put
  document conversion on the verification-closure path.
- **`doc_extraction.py` finally has its pipeline caller.** Every consumed
  SOURCE document is registered in the existing `DocumentIndex` with
  `kind = doc_extraction:<category_id>`, and `--incremental` asks the existing
  `needs_extract()` whether a source really changed. That module's NOTICE has
  said since 2026-08-28 that nothing invoked `DocumentIndex`/`needs_extract()`/
  `register()`; that is now false in a checkable way.

### `dv_harness/doc_extraction_categories.json` (new, 129 lines)

Policy-as-data — same shape as `context_budget.policy.json` and
`harness_deploy.manifest.json`. Declares all eleven of item #40's categories
(40a–40k) with checklist letter, the real `module.callable` handling each, and
its input keys. HOW to invoke lives in `CATEGORY_EXTRACTORS` because eleven
extractors have eleven different signatures;
`assert_extractor_table_matches_categories()` holds data and code together in
both directions, plus resolves every declared callable through the import
system.

### `dv_harness/cli.py` (+44 lines, 2 hunks)

`dv-harness doc-extract categories | plan | run`. Exit 1 if any category
FAILED, 2 on a malformed request. The identical
`python -m dv_harness.doc_extraction_fanout` shares one `execute_verb()`.

### `CLAUDE.md` (+111 lines)

New section documenting the mechanism, the four enforced properties, and the
disclosed residual.

---

## 3. Real run over all eleven categories

Real extractors, real inputs (`examples/asset_processing/inputs/`, this repo's
own `dv_harness/uvm_generator/templates/sim_scripts/Makefile`):

```
 40a vip_user_guide             EXTRACTED       artifacts=3  thr=doc-extract_0
 40b vip_source                 EXTRACTED       artifacts=2  thr=doc-extract_1
 40c vip_examples               NO_EXTRACTOR    artifacts=0  thr=doc-extract_2
 40d dut_document_registers     EXTRACTED       artifacts=2  thr=doc-extract_2
 40e ip_document                EXTRACTED       artifacts=1  thr=doc-extract_3
 40f programming_guide          EXTRACTED       artifacts=1  thr=doc-extract_4
 40g dut_rtl                    EXTRACTED       artifacts=1  thr=doc-extract_5
 40h ip_source                  NO_EXTRACTOR    artifacts=0  thr=doc-extract_6
 40i top_testbench_runscript    EXTRACTED       artifacts=1  thr=doc-extract_6
 40j reference_command_txt      EXTRACTED       artifacts=1  thr=doc-extract_7
 40k standard_spec              EXTRACTED       artifacts=3  thr=doc-extract_7
counts: {EXTRACTED: 9, UP_TO_DATE: 0, INPUT_NOT_SUPPLIED: 0, NO_EXTRACTOR: 2, FAILED: 0}
wall=0.739s  worker_seconds_sum=4.459s  distinct_worker_threads=8
```

6.0x overlap across 8 threads — a measurement, not an assertion.

---

## 4. Four properties, each enforced in code and each tested

1. **An absent extractor is reported, never faked.** 40c and 40h report
   `NO_EXTRACTOR` with the real reason from the data file. `INPUT_NOT_SUPPLIED`
   is a third, distinct outcome. Collapsing any two would let an empty fan-out
   read as a complete one.
2. **One failing category never sinks the fan-out.** A raising extractor is that
   category's `FAILED` with its real exception text; the other ten still run.
3. **Concurrent writes cannot collide.** Each category writes into its own
   `<out_root>/<category_id>/`, asserted distinct before any worker starts. The
   one genuinely shared mutable resource — `DocumentIndex.register()`'s
   read-modify-write over a single JSON file — is serialized behind
   `_INDEX_LOCK`.
4. **Reading is never a mutating act.** No adapter escalates to the question
   queue, writes a Blackboard topic, mints an approval, or touches memory — even
   where the underlying extractor supports it (`audit_directory()` takes a
   `question_store=`; the fan-out never passes one).

Two further honesty carries: `dut_rtl` reports each `env.manifest.json` layer's
OWN status verbatim (checked against the manifest on disk, not against a
hardcoded vocabulary), and `top_testbench_runscript` records
`hierarchy_json: NOT_PRODUCED_NO_NON_AGENT_EXTRACTOR`.

---

## 5. Tests

`dv_harness_tests/test_doc_extraction_fanout.py` — **39 tests, all passing**.
Nothing is mocked: a fan-out that only ever dispatched stubs would prove the
fan-out and nothing about whether the eleven categories actually convert.

Both concurrency claims carry **negative controls that were actually run**:

- *Overlap*: four adapters block on one `threading.Barrier(4)` a sequential
  dispatcher provably cannot satisfy. Verified by forcing `max_workers=1`:
  four `FAILED` results, one thread.
- *No lost index rows*: verified by temporarily replacing `_INDEX_LOCK` with a
  `nullcontext()`, which made the test fail with a `JSONDecodeError` from a torn
  read. The lock was restored immediately.

Also covered: category/adapter drift in both directions (with its own detection-
power control), declared-order determinism, per-category output isolation,
colliding document stems refused rather than silently overwritten, `--incremental`
skip and re-extract on a real edit, `--no-register`, the pypdf branch against
this repo's own committed PDF, `plan` writing nothing, and the CLI verb driven as
a real subprocess through `python -m dv_harness`.

---

## 6. Test summary

**One line: 5,514 passed across the full `dv_harness_tests/` suite; the only 11
non-passes are pre-existing `pueue`-daemon environment failures, each reproduced
identically on a clean detached-HEAD worktree carrying none of this change.**

---

## 7. Full-suite result

The suite was run in four alphabetical chunks because this environment
terminates a background task before a single ~80-minute serial run of all 223
test files can finish (three whole-suite attempts were killed at 67%, 72% and
70%). The chunks are a partition of `dv_harness_tests/test_*.py` — 55/55/55/55
files, no file run twice and none omitted.

| chunk | files | result |
|---|---|---|
| 0 (`test_active_stages_read_sites` … `test_doc_extraction_fanout`) | 55 | **1485 passed, 5 failed** (13:29) |
| 1 (`test_e2e_memory_chain_usb3_lfps` … `test_memory_dedup`) | 55 | **1546 passed, 0 failed** (28:17) |
| 2 (`test_memory_dedup_write_path` … `test_resource_cost_autonomy`) | 55 | **1110 passed, 6 errors** (14:51) |
| 3 (`test_root_cause_evidence_gate` … `test_workflow_rca_multi_agent_fusion`) | 55 | **1373 passed, 0 failed** (19:42) |
| **total** | **220** | **5514 passed; 5 failed + 6 errors** |

### Per-failure attribution — all 11 are pre-existing, none are mine

Every non-pass is the same environment cause: the `pueue` task daemon does not
come up on this machine. `pueue` is an external local task-orchestration binary
(`dv_harness/pueue_client.py`), untouched by this change.

- **5 failures**, `test_cli_pueue.py` (`TestPueueAddAndStatus` ×3,
  `TestPueueChain` ×2) — `dv-harness pueue add` exits 1.
- **6 errors**, `test_pueue_client.py::TestRealPueueIntegration` — setup fails
  with `AssertionError: real pueued did not come up`.

**Proven pre-existing, not assumed.** A clean detached worktree was created at
`HEAD` *before* this commit (`git worktree add --detach /tmp/gap4_baseline HEAD`,
verified to contain no `doc_extraction_fanout.py`) and both test files were
re-run there:

- baseline `test_cli_pueue.py` → **5 failed, 1 passed** — the identical five.
- baseline `test_pueue_client.py` → **30 passed, 6 errors** — the identical six,
  with the same `real pueued did not come up` message.

### Targeted runs (before the chunked full suite)

- 9 document/extractor test files (`test_doc_extraction_fanout`,
  `test_research_evidence_card`, `test_asset_processing_artifacts`,
  `test_env_manifest`, `test_env_manifest_fact_sources`,
  `test_makefile_to_run_profile`, `test_reference_pattern_audit`,
  `test_context_budget`, `test_doc_citation_check`) — **360 passed, 0 failed**.
- 10 `test_cli_*` files — **77 passed**, plus the 5 pueue failures above.
- `test_doc_extraction_fanout.py` alone — **39 passed**.

---

## 8. Commit

`2842fc8 doc_extraction_fanout: parallel multi-extractor dispatch over item
#40's 11 document categories` — 5 files, 1668 insertions, 0 deletions:

```
 CLAUDE.md                                      | 110 ++++
 dv_harness/cli.py                              |  44 ++
 dv_harness/doc_extraction_categories.json      | 129 ++++
 dv_harness/doc_extraction_fanout.py            | 809 ++++++++++++++++++++++
 dv_harness_tests/test_doc_extraction_fanout.py | 576 +++++++++++++++
```

Scoped by hand, as required. `dv_harness/cli.py` and `CLAUDE.md` both carried
other agents' concurrent in-flight edits, so patches were generated, trimmed to
this scope's hunks only (with the trailing hunk's `+` line numbers recomputed
for the dropped hunk), verified with `git apply --cached --check`, then staged.

**One real concurrency hazard was hit and handled.** Mid-task, three sibling
agents committed (`996c5cc` loop_convergence, `cc3a383` golden_flow_readiness,
`2a6b722`/`87007e9` reports), which consumed the shared index and cleared my
staged hunks. Verified afterwards that none of those commits contains any of my
files, and that `git log -S` finds neither
`"Parallel Document-Extraction Fan-Out"` nor the `doc-extract` verb in any
earlier commit — so nothing of mine was swept into someone else's commit and
nothing of theirs into mine. The final commit was made with an explicit
pathspec (`git commit -F <msg> -- <5 paths>`) so index churn could not widen it;
`git show --stat HEAD` confirms exactly those five files.

---

## 9. Disclosed residual

This closes the **DISPATCH layer**, not new extraction capability.

- 40c (VIP examples) and 40h (IP source) still have **no extractor**; the fan-out
  reports that rather than inventing one.
- 40d/40e/40f remain **input-CONTRACT transcription pipelines** — `design_intent.py`'s
  own docstring: "transcribes and validates; never authors". The
  `.doc`/`.xlsx` → structured-source step is still performed by a human or an
  agent reading the document.
- 40g's **interrupts** remain agent-skill-driven (`interrupt-event-dispatch`).
- 40i's **`hierarchy.json`** half is still agent-produced (`CORE/hierarchy-discovery`),
  and the fan-out says so per run rather than leaving it to be assumed.
- **Not engine-fired.** No `run_stage()`/`advance()` call site invokes it and no
  graph node declares it. This is a **REACHED** capability (a real CLI caller
  exists), not a **WIRED** one — stated in the same terms
  `harness-deploy` and `loop_convergence` state theirs.

Also worth naming as a separate, larger effort rather than silently implied
closed: item #40's phrase is "multiple **agents**". What was built dispatches
multiple real **extractors** concurrently in-process. Dispatching multiple
`claude -p` subagents concurrently over these categories would reuse
`engine.py`'s adapter layer and is a genuinely separate scoped effort — it needs
a per-category agent profile, a token/context budget per branch, and a join
contract. It was not attempted here.
