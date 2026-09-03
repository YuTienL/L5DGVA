# Gap close — Phase 23 (E2E synthetic test) + Phase 24 (Documentation) + Phase 15 (CLAUDE.md policy)

Execution Mode: **LOCAL_ANALYSIS** (pure local read/analysis + local Python tests; no server,
no VCS, no LSF).

**Result: DONE.**

Two real gaps closed, both small and boundable, both inside this scope's own files. Nothing
touched in `CLAUDE.md`, `dv_harness/cli.py`, `dv_harness/memory.py`, `dv_harness/memory_router.py`
or any other file a concurrent workflow had modified (`git status` re-checked immediately before
each edit — every file I wrote was clean or new).

Test summary: **244 passed, 0 failed** across the 14 memory/doc test files (226 before this pass;
+17 new `test_doc_citation_check.py` cases, +1 new `test_memory_vault.py` case), plus a clean
`python .work/e2e_usb3_lfps_demo.py` re-run (exit 0, all 14 steps' internal asserts passing).

---

## Phase 24 — Documentation: gap CLOSED (was READY-with-staleness)

### What the audit found, and what was actually true

The audit reported 2 of 3 cited line numbers in `docs/MEMORY_ARCHITECTURE.md` had drifted. I built
a checker and ran it: **all 7 line citations across the 5 docs had drifted**, not 2 — the audit's
own numbers had themselves aged between the audit and this pass, because `memory_router.py` and
`memory.py` were edited again by concurrent work in between.

Real "before" output (`python -m dv_harness.doc_citation_check --memory-docs`, exit 1):

```
DRIFT  docs/MEMORY_ARCHITECTURE.md:71   cites dv_harness/memory.py:6      MEMORY_LEVELS is really at line 10
DRIFT  docs/MEMORY_ARCHITECTURE.md:84   cites memory_router.py:386        route_memory is really at line 571
DRIFT  docs/MEMORY_ARCHITECTURE.md:86   cites memory_router.py:59         route_and_store is really at line 91
DRIFT  docs/MEMORY_ARCHITECTURE.md:183  cites memory.py:479-501           OrganizationalMemoryStore.add is really at line 783
DRIFT  docs/MEMORY_ARCHITECTURE.md:193  cites memory_router.py:260        promote_to_organizational is really at line 445
DRIFT  docs/MEMORY_SCHEMA.md:12         cites memory.py:44                MemoryStore.add is really at line 185
DRIFT  docs/MEMORY_SCHEMA.md:55         cites memory.py:290               CornerCaseLibrary.add is really at line 576
7 citation(s) checked across 5 doc(s): 0 OK, 7 drifted, 0 unverifiable
```

Because these numbers had now rotted **twice** in two days, refreshing them by hand would have
closed nothing — the same finding would reappear at the next audit. So the fix is the numbers
**and** a mechanism that keeps them true.

### What was built

**`dv_harness/doc_citation_check.py`** (new, 288 lines) — a symbol-anchored citation checker:

- `parse_citations()` extracts every `` `module.py:<line>` `` / `` `module.py:<start>-<end>` ``
  span from a doc, skipping fenced code blocks (a snippet is an illustration, not a claim).
- `collect_definitions()` maps each Python source to its citable symbols. Methods are registered
  under their qualified `Class.method` name **only** when the bare name is ambiguous — `add` is
  defined on 4 classes in `memory.py`, and a bare-name match would wave a citation pointing at
  any of them straight through.
- `context_symbols()` reads the prose around the citation (±3 lines, so a naming section heading
  a line or two up still counts) and expands dotted chains, so
  `dv_harness.memory_router.route_memory` also offers `route_memory`.
- A citation is `OK` only when a symbol the prose actually names is really defined inside the
  cited line/range. Otherwise: `DRIFT` (reported **with the correct line**, so the fix is
  mechanical), `UNVERIFIABLE` (prose names no symbol in that file — nothing checkable, exit 2),
  `MISSING_SOURCE`, or `OUT_OF_RANGE`.
- CLI: `python -m dv_harness.doc_citation_check --memory-docs` (exit 1 on drift, 2 on
  unverifiable).

It is standalone by design — it does **not** touch `cli.py`, `memory_doctor.py` or the CI
workflow file, all of which other workflows are editing concurrently. It reaches CI through the
test suite instead.

### Docs updated

- `docs/MEMORY_ARCHITECTURE.md` — 5 citations corrected (`memory.py:6→10`,
  `memory_router.py:386→571`, `memory_router.py:59→91`, `memory.py:479-501→783-789`,
  `memory_router.py:260→445`), and the header's own claim ("file:line references are given so any
  claim here can be checked") now names the checker and the test that back it, instead of asking
  the reader to trust a number.
- `docs/MEMORY_SCHEMA.md` — 2 citations corrected (`memory.py:44→185`, `memory.py:290→576`).
- `docs/MEMORY_OPERATIONS.md` — new "Checking these docs' own file:line citations" section with
  the copy-pasteable commands, matching the file's existing operations-recipe style.
- `docs/OBSIDIAN_INTEGRATION.md`, `docs/MEMORY_AGENT.md` — carry no line citations; unchanged.

"After" output is `7 citation(s) checked across 5 doc(s): 7 OK, 0 drifted, 0 unverifiable`,
exit 0.

### Re-confirmed READY (unchanged, checked myself)

All 5 Phase-24 docs exist and every artifact they reference is real:
`.claude/agents/memory-agent.md` (134 lines), `DV_MEMORY_SEARCH.ps1`, `DV_MEMORY_GET.ps1`,
`.work/obsidian-memory-debugflow-report.md` (382 lines); and
`MEMORY_NOTE_REQUIRED_FIELDS` (`memory_vault.py:122`), `MEMORY_NOTE_BODY_SECTIONS`
(`memory_vault.py:156`), `bootstrap_vault()` (`memory_vault.py:398`), `detect_obsidian_cli()`
(`memory_vault.py:503`), `FileSystemMarkdownAdapter` (`memory_vault.py:689`),
`build_failure_signature()` (`memory_vault.py:1186`), `search_related_memory_for_debug()`
(`memory_vault.py:1338`) are all real. The function names, signatures and described behavior in
the docs were accurate throughout — only the numbers were wrong, which is exactly the failure
mode the checker now owns.

---

## Phase 23 — E2E USB3 Polling.LFPS synthetic flow: boundary CONFIRMED correct, one real sub-gap CLOSED

### The PARTIAL verdict is correct and stays PARTIAL

I re-ran `python .work/e2e_usb3_lfps_demo.py` fresh (exit 0). It rebuilt
`.work/_e2e_demo_usb3_lfps/`, drove all 14 steps against real unmocked
`memory_vault`/`inference`/`memory_router`/`session_snapshot` code, and every internal assert
passed: JOB_MEMORY / ENGINEERING_MEMORY destinations, `INSUFFICIENT_CONFIRMATION` promotion
outcome, forward-link + backlink traversal, and a `knowledge_commit_sha`
(`62aa5d9866cf0d611126b36d7abed0acf2e834ec` on that run) matching the real `git log --oneline`
head in the demo vault.

Step 7's `"real_execution_status": "PARTIAL_NOT_PERFORMED"` is a **deliberate, disclosed
boundary**, not a closable gap: no LSF/VCS run was submitted, per this effort's own instruction
not to attempt real remote execution. Left exactly as-is. The memory-flow mechanics are READY;
the remote-execution leg is the named boundary. Overall Phase 23 stays **PARTIAL**.

### The audit's "minor cosmetic note" was real — and mis-attributed

The audit noted the Engineering note's frontmatter read `confidence: UNKNOWN` over a HIGH-
confidence verified fix, and attributed it to `build_frontmatter_from_memory_record()` "only
reading a literal `confidence` key". I read that function (`memory_vault.py:1090-1128`) and the
demo's own stored record, and the attribution is wrong in a way worth correcting:

- The builder is **right**. It mirrors `mem.get("confidence", "UNKNOWN")` faithfully. Making it
  infer HIGH from a gate-validated `verification` block would have it invent a confidence label
  the record never asserted — strictly worse than reporting UNKNOWN.
- The stored record really did carry `confidence: "UNKNOWN"` — `MemoryStore.add()`'s `setdefault`
  — because the **demo script never put the confidence it had just measured onto the record**.
  Step 7 computed `{'level': 'HIGH', 'score': 10}` via the real `inference.score_confidence()`,
  printed it, and then step 10 built the Engineering record without it.

That is a genuine defect, and specifically a violation of the very policy Phase 15 requires:
CLAUDE.md's Engineering Memory Policy says to "record root cause, evidence, fix, verification,
**and confidence** together as one Engineering Memory record." The demo was demonstrating a chain
that dropped one of the five.

**Closed at the correct layer** — the writer, not the frontmatter builder:

- `.work/e2e_usb3_lfps_demo.py` STEP 10 now sets `"confidence": confidence_post_fix["level"]` on
  the Engineering record (the chain's own measured value, nothing fabricated), with a comment
  stating why.
- STEP 12 now **asserts** the note's frontmatter confidence equals the measured level, so this
  cannot silently regress on a future run.
- Re-run confirms: `Engineering note frontmatter confidence: HIGH`, exit 0, chain result COMPLETE.

`.work/mem_journal_9.txt` Gap #6 (the earlier self-disclosure of this cosmetic item) is now
closed by this change; the journal itself is left as the historical record it is.

A suite-level regression test was added too, since the demo script is not part of the test suite:
`dv_harness_tests/test_memory_vault.py::test_vault_note_frontmatter_carries_the_records_measured_confidence`
drives the real `route_and_store()` and asserts both halves — a record carrying `confidence: HIGH`
produces `confidence: HIGH` (and a `high` tag) in the note, **and** a record admitted through the
gate-validated-`verification` path with no `confidence` key still reads `UNKNOWN`, so nobody
"fixes" the second case later by inventing a value.

---

## Phase 15 — CLAUDE.md Engineering Memory Policy: READY, re-confirmed, NO ACTION

Re-confirmed by reading `CLAUDE.md`'s "## Engineering Memory Policy (2026-09-03)" section
directly. All 4 required sub-sections are present and substantively correct:

- **Before debugging** — search Project + Engineering Memory before the first hypothesis, names
  the real `python -m dv_harness.memory_cli search --protocol <p> --text <symptom>` and the
  `memory-retrieval` skill, and states any hit is "a candidate hypothesis to rank higher, never an
  accepted root cause."
- **During debugging** — Hypothesis → Evidence → Confidence → Gap → Next-Best-Action, citing the
  real `inference.score_confidence()`/`identify_gap()`/`next_best_action()`, with each transition
  a persisted Working Memory record (`kind="react_reasoning_step"`).
- **After verified PASS** — root cause + evidence + fix + verification + confidence as one
  Engineering Memory record, then promotion only through the real 3-gate
  `promote_to_organizational()`; direct writes and re-wording gate inputs are both explicitly
  forbidden. (This is the clause the Phase 23 demo was violating, now fixed.)
- **Never** — secrets/passwords/tokens/credentials (backed by `route_memory()`'s hard REJECT),
  giant logs / raw FSDB content (cite path/offset/signature only), and promoting an unverified
  hypothesis straight to Engineering/Organizational.

The section has since grown an `engineering_admission_gate()` paragraph and the "Debug-flow /
regression / git-integration mechanics" addendum; both reinforce rather than contradict the
required policy. **Nothing needed changing, and I did not modify `CLAUDE.md`** — it is under
concurrent edit by other workflows (confirmed: a new "Blackboard Topics Written Outside the Graph
(2026-09-04)" section appeared mid-pass).

---

## Files changed

| File | Change |
|---|---|
| `dv_harness/doc_citation_check.py` | **new** — symbol-anchored file:line citation checker + CLI |
| `dv_harness_tests/test_doc_citation_check.py` | **new** — 17 tests |
| `dv_harness/memory_vault.py` | *unchanged* — investigated, found correct as written |
| `dv_harness_tests/test_memory_vault.py` | +1 test: note frontmatter carries the record's measured confidence (both directions) |
| `docs/MEMORY_ARCHITECTURE.md` | 5 stale citations corrected; header claim now names its own check |
| `docs/MEMORY_SCHEMA.md` | 2 stale citations corrected |
| `docs/MEMORY_OPERATIONS.md` | new citation-check operations section |
| `.work/e2e_usb3_lfps_demo.py` | STEP 10 carries the measured confidence onto the record; STEP 12 asserts the note reflects it |

## Tests

```
python -m dv_harness.doc_citation_check --memory-docs
  -> 7 citation(s) checked across 5 doc(s): 7 OK, 0 drifted, 0 unverifiable   (exit 0)

python .work/e2e_usb3_lfps_demo.py
  -> Engineering note frontmatter confidence: HIGH
  -> Chain result: COMPLETE (14 real steps; step 7's real-execution portion honestly PARTIAL)
  -> exit 0

python -m pytest dv_harness_tests/test_doc_citation_check.py \
  dv_harness_tests/test_agent_roster_doc.py dv_harness_tests/test_memory_vault.py \
  dv_harness_tests/test_memory_doctor.py dv_harness_tests/test_memory_dedup.py \
  dv_harness_tests/test_memory_security.py dv_harness_tests/test_memory_tier_completion.py \
  dv_harness_tests/test_memory_tier_integrity_and_admission.py \
  dv_harness_tests/test_memory_search_filters.py \
  dv_harness_tests/test_memory_write_guard_and_job_evidence.py \
  dv_harness_tests/test_cli_memory_commands.py dv_harness_tests/test_debug_flow_memory.py \
  dv_harness_tests/test_react_working_memory_bridge.py \
  dv_harness_tests/test_obsidian_memory_final_integration.py -q
  -> 244 passed in 212.04s
```

**One disclosed flake, not caused by this change.** An intermediate run of the same 14 files hit
`test_memory_tier_integrity_and_admission.py::test_concurrent_processes_writing_memory_never_lose_each_others_index_rows`
with a Windows `PermissionError` on `index.json.tmp-59540 -> index.json` (an `os.replace` losing a
race against a transient file lock, under a machine currently running several concurrent
workflows). It passed on the run before it, passed 3/3 when re-run in isolation, and passed again
on the final full run above. Neither that test file nor `dv_harness/memory.py` is modified by this
change or by anyone else (`git status` clean on both), and nothing this pass touched is reachable
from that test. Reported rather than quietly dropped.

The drift detection is proven load-bearing, not decorative: the checker reported 7 real DRIFTs
against the live docs before the fix and 0 after, and the unit tests independently confirm it
catches an off-by-one, a wrong class's identically-named method, a range that excludes the
definition, and a citation to a symbol that does not exist — while a citation whose prose names no
checkable symbol is reported `UNVERIFIABLE` rather than quietly passing.

## Verdicts

| Scope | Verdict after this pass |
|---|---|
| Phase 23 (E2E USB3 LFPS test) | **PARTIAL** — unchanged and correct. Memory-flow mechanics READY and independently re-run; the no-LSF/VCS leg is the task-mandated disclosed boundary. One real sub-gap (measured confidence never reaching the Engineering record, in violation of CLAUDE.md's own policy) is now CLOSED and regression-tested. |
| Phase 24 (5 docs) | **READY** — staleness gap closed at the mechanism level, not just the symptom. All 7 citations corrected; drift is now a test failure. |
| Phase 15 (CLAUDE.md policy) | **READY** — re-confirmed by direct reading, no change needed, no edit made. |
