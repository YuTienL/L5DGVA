# Gap-close — Phase 23 (E2E synthetic test) + Phase 24 (Documentation) + Phase 15 (CLAUDE.md policy)

**Verdict: DONE** — one real, boundable gap closed (Phase 23's "proven once, never
re-run" axis). The other two phases re-verified as already correct; one audit
finding had already been fixed by concurrent in-session work and is now confirmed
green rather than re-fixed.

Execution mode: **LOCAL_ANALYSIS** — 「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」
No remote Linux/LSF/VCS execution was attempted.

---

## What the audit asked for, and what was actually found this pass

### Phase 23 — End-to-end DV test: was PARTIAL on one axis. **Closed.**

The audit's finding was correct and precise: the synthetic USB3 Polling.LFPS chain
at `.work/e2e_usb3_lfps_demo.py` was real and re-runnable, but nothing under
`dv_harness_tests/` or `.claude/` referenced it. It was a one-off script whose
correctness depended on a human remembering to run it — which CLAUDE.md's own
**Methodology Consolidation Rule** explicitly says is not "done":

> A validated code-level capability ... is consolidated into the actual engine
> source under `dv_harness/`, with regression tests ... never left as a
> hand-edited one-off file outside the engine.

**What was built** (three files, one shared driver, no duplicated chain):

| File | Role |
|---|---|
| `dv_harness_tests/e2e_memory_chain_usb3_lfps.py` (new, 351 lines) | The chain itself, as ONE reusable driver: `run_memory_chain(project_root, cfg, echo)`. Makes no assertions — returns every fact each of the 14 steps really produced. |
| `dv_harness_tests/test_e2e_memory_chain_usb3_lfps.py` (new, 183 lines) | The regression net: 15 tests, one per link, over a module-scoped real run against a `tmp_path` project with real git. |
| `.work/e2e_usb3_lfps_demo.py` (rewritten, 374 → 76 lines) | Now a thin narrated runner over the same driver. |

One driver means the narration and the regression net **cannot describe different
chains** — a `test_the_demo_script_and_this_test_drive_the_same_chain` test pins
that structurally.

What the 15 tests actually assert (all against the real
`memory_router`/`memory_vault`/`inference`/`session_snapshot`, nothing mocked):

- fresh-vault search reports an **honest 0**, not "everything" (`count == 0`,
  `results == []`) — a search that "finds" prior knowledge on an empty vault makes
  every later hypothesis look pre-confirmed;
- `build_failure_signature()` derives `abnormal_termination` itself from the real
  terminal-signature marker (this corrected one of my own initial expectations —
  the code is right, the assertion was wrong, and the test now documents why);
- confidence is **independently recomputed** with `score_confidence()` from the
  same inputs and compared — the chain cannot report a level the scorer would not
  produce;
- `next_best_action()` returns one action per identified gap, each citing a real
  `source` (`protocol_builder_registry`), never a generic "investigate further";
- the PASS job AND the FAILED attempt both land in `JOB_MEMORY` only;
- the verified root cause clears `engineering_admission_gate()` and the on-disk
  record really carries root_cause/fix/evidence/confidence together (CLAUDE.md's
  "one record" requirement);
- `promote_to_organizational()` **refuses** with `INSUFFICIENT_CONFIRMATION`,
  `confirmation_count == 0`, `required == ORGANIZATIONAL_MIN_CONFIRMATIONS == 2`
  — asserted against the real constant, not a literal;
- `[[WikiLink]]` forward + back both resolve between the two notes, and the note
  body really contains `[[<job note id>]]`;
- the vault note's frontmatter `confidence` equals the measured level (a note
  reading UNKNOWN over a HIGH verified fix is a traceability break between the JSON
  system of record and its human-browsable mirror);
- `knowledge_commit_sha` is resolved with a real `git rev-parse --verify <sha>^{commit}`
  **in the vault**, not just string-matched against `git log` output, and the log
  carries the real `memory(USB):` message format;
- session restore produces a resume summary carrying this run's stage and measured
  confidence, with the snapshot really on disk;
- no `.fsdb` payload and no log-dump-sized body reaches the vault note (CLAUDE.md's
  "Never" — cite a path/offset/signature only);
- **`test_step_7_real_execution_half_stays_honestly_partial`** pins the disclosed
  boundary: `real_execution_status == "PARTIAL_NOT_PERFORMED"`. If that ever starts
  claiming a real verdict without a real LSF/VCS run behind it, this test fails.

**The LSF/VCS boundary itself was left exactly as-is** — it is a correctly-disclosed
boundary (`REMOTE_EXECUTION` needs real credentials and a real server), not a gap,
and per this workflow's own instructions such boundaries stay PARTIAL by name rather
than being closed. Phase 23's verdict is therefore now: **chain READY, regression-
guarded READY, real-execution half PARTIAL (named boundary)**.

**Deliberately NOT wired into the `justfile`.** The audit named the justfile as a
missing entry point; on inspection that is the wrong home. `justfile`'s `memory-*`
namespace is contract-locked by `dv_harness_tests/test_justfile.py::
test_every_memory_cli_subcommand_has_a_recipe`, which asserts the recipe set
**equals** the `dv-harness memory` subcommand set — adding a demo recipe there would
break that contract to gain nothing. The pytest suite is the entry point that
actually runs automatically (CI `dv-harness-ci.yml`, and this repo's live
`tools/git-hooks/pre-push`), which is what consolidation requires.

### Phase 24 — Documentation: **READY**. The one failing sub-item was already fixed.

The audit found `python -m dv_harness.doc_citation_check --memory-docs` exiting 1 on
3 drifted `memory_router.py` citations, caused by a then-uncommitted concurrent edit.
Re-checked live this pass:

```
$ python -m dv_harness.doc_citation_check --memory-docs
8 citation(s) checked across 5 doc(s): 8 OK, 0 drifted, 0 unverifiable
EXIT=0
```

`docs/MEMORY_ARCHITECTURE.md` now cites `memory_router.py:1124/140/988` (lines 90/92/217),
which resolve correctly. The drift was closed by concurrent commits `2dac81d`/`398a3de`/
`1836b0b` on `memory_router.py` plus the doc's own re-derivation. `test_doc_citation_check.py`
and `test_memory_docs_mirror_source.py`: **24 passed**, no failures. All 5 docs re-confirmed
present and current (447 / 143 / 146 / 307 / 275 lines). **No re-fix was needed; nothing
was rewritten to claim credit for a fix another workflow made.**

One real addition: `docs/MEMORY_OPERATIONS.md` gained a **"Checking the whole chain end
to end"** section naming both entry points, what the chain covers, and the honest
`PARTIAL_NOT_PERFORMED` boundary — because an operations doc that documents `memory
doctor`, `memory validate` and the citation checker but not "how do I verify the whole
memory system still works end to end" had a real hole in it. Written citation-free by
design, so it cannot itself drift.

### Phase 15 — CLAUDE.md Engineering Memory Policy: **READY**. Nothing changed.

Re-read directly. All four required sub-sections present and current
(`CLAUDE.md:35` section header, `:44` Before debugging, `:54` During debugging,
`:61` After verified PASS, `:106` Never — the audit's `:93` for "Never" had shifted
because the section grew, content unchanged). Every claim in it was exercised for
real by the Phase 23 chain this pass, not merely read: `search_related_memory_for_debug()`
returned an honest 0, `score_confidence()`/`identify_gap()`/`next_best_action()` all
produced real results, `engineering_admission_gate()` admitted, and
`promote_to_organizational()` refused on the confirmation gate. **No gap. No edit.**

---

## Stale-reference cleanup (Engineering Discipline Rules — comment hygiene)

Two live source comments pointed at the chain's old home and were corrected in place:

- `dv_harness/inference.py:222` — caller list now names
  `dv_harness_tests/e2e_memory_chain_usb3_lfps.py`, not `.work/e2e_usb3_lfps_demo.py`.
- `dv_harness_tests/test_memory_vault.py:746` — same pointer, in the docstring that
  explains why the record carries `score_confidence()`'s real result.

(Historical `.work/*-report.md` files that cite the old path were left alone — they are
dated records of what was true when written, not live guidance.)

---

## Test summary

`python -m pytest dv_harness_tests/test_e2e_memory_chain_usb3_lfps.py dv_harness_tests/test_debug_flow_memory.py dv_harness_tests/test_memory_vault.py dv_harness_tests/test_memory_docs_mirror_source.py dv_harness_tests/test_doc_citation_check.py dv_harness_tests/test_justfile.py dv_harness_tests/test_cli_memory_commands.py dv_harness_tests/test_memory_dedup_write_path.py -q` → **176 passed** (103s), plus the
new module alone **15 passed** (29s), the demo script re-run green (exit 0, real vault
git log with 3 real `memory(USB):` commits), and `doc_citation_check --memory-docs`
exit 0.

**Full-suite caveat, stated rather than hidden**: a whole-`dv_harness_tests` run was
attempted and showed failures/errors in the `test_p*` band. Those are in
`protocol_capability` / protocol-builder territory, which is **being actively edited
by a concurrent workflow right now** (`git status` shows uncommitted
`dv_harness/protocol_capability.py`, `.dv-harness/qualification/protocol_capability_registry.json`,
two `PROTOCOL_BUILDERS/*/SKILL.md`, `create_environment.py`, `engine.py`). Nothing in
this change can reach them: this change adds two test-only modules and edits two
docstrings, one markdown doc, and a `.work/` script. Reported as an observation about
repo state, not as a claim that this change is implicated or exonerated by a run I did
not complete.

---

## Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\e2e_memory_chain_usb3_lfps.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_e2e_memory_chain_usb3_lfps.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\e2e_usb3_lfps_demo.py` (rewritten as a narrated runner)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\docs\MEMORY_OPERATIONS.md` (new end-to-end section)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\inference.py` (stale pointer)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_memory_vault.py` (stale pointer)

Committed with a pathspec-limited commit (`git commit -- <paths>`), deliberately NOT a
broad `git add`, because the shared index already carried another workflow's staged
`system_resource_registry` work at the time.
