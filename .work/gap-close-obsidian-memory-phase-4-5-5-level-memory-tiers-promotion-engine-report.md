# Gap-close — Phase 4 (5-Level Memory tiers) + Phase 5 (Promotion Engine)

**Status: DONE** — one real, closeable gap built and proven; everything else
re-confirmed as already correct.

Commit: `1836b0b memory(_general): make the Engineering->Organizational
confirmation gate reachable from the real writers`

---

## 1. Phase 4 (READY) — re-confirmed, nothing changed

I re-checked the audit's citations myself against the current tree rather than
trusting the summary. All five tiers hold up:

- **Working** — `react.py`'s `ReactRecorder.record()` routes
  `kind="react_reasoning_step"` through `route_and_store()` to
  `WorkingMemoryStore`. Real records on disk.
- **Job** — `lsf_client._upsert_job_tier_memory_record()` writes the full
  spec'd field set (job_id / pattern / command / LSF status / timing /
  UVM_ERROR+FATAL counts / terminal signature / evidence refs / fix-attempt
  status / result).
- **Project** — `route_memory()` routes
  `project_fact`/`project_topology`/`tool_flow`/`known_issue` (verified only)
  to `PROJECT_MEMORY`; 46 real records, genuine DUT/subsystem content.
- **Engineering** — `engineering_admission_gate()` hard-gates entry
  (evidence-or-gate-validated verification + HIGH/CONFIRMED confidence +
  a reusable claim); a failing record is demoted to Working with
  `engineering_admission_rejected`.
- **Organizational** — no local file store by design
  (`OrganizationalMemoryStore` is Knowledge-Center-backed), reachable only
  through the Phase 5 gate.

The one spec-wording divergence (Working Memory documented as *durable*, not
"not permanently saved") is a deliberate, documented design choice —
crash-survivable reasoning trail — and was left alone per the effort's own
"keep the better existing architecture" instruction.

---

## 2. Phase 5a (READY) — re-confirmed, nothing changed

Gate structure, weighted scoring, and the three all-required gates in
`promote_to_organizational()` are real, hard-enforced, and independently
re-verified. `inference.score_confidence()` is genuinely extended rather than
duplicated. `engineering_admission_gate()` / `organizational_admission_gate()`
re-derive gates from the durable store, not from the payload.

---

## 3. Phase 5b (was the real gap) — BUILT

### What was actually broken

`promote_to_organizational()`'s third gate is
`confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS` (2). Only
`MemoryGC.confirm()` may advance that field, and it fires from
`_add_or_confirm_engineering()` when a later record matches an ACTIVE
engineering record on `(protocol, root_cause)`.

That mechanism was real, correct and tested — but **only ever exercised by
tests calling `MemoryGC.confirm()` directly**. Both real production writers
took the record's `protocol` off a gate evidence block, and neither
`experience_knowledge_gate`'s nor `root_cause_evidence_gate`'s
`JUDGMENT_FIELDS` (`gates.py`) includes `protocol` — no gate ever required or
judged it.

Confirmed against this project's own live store before touching anything:

```
engineering records: 31
protocol is None:    30
confirmation_count:  {0: 29, 1: 1, None: 1}   # zero ever reached 2
```

So every re-derivation minted a fresh record, and the Organizational tier was
unreachable by its own intended organic route. `memory_router.py`'s own
`_add_or_confirm_engineering()` docstring had carried a KNOWN LIMITATION note
saying exactly this.

A third writer compounded it: `MemoryConsolidator.from_closed_finding()` — the
path `memory-consolidation/SKILL.md` documents as the sanctioned initial
Engineering Memory write — called `store.add("engineering", ...)` directly, so
calling it twice for one finding minted two records and zero confirmations.

### What was built

- **`dv_harness/engine.py`** — `_promote_experience_knowledge()` and
  `_promote_verified_fix_knowledge()` take the attempt's resolved protocol and
  build the record's `protocol` through the new
  `DVHarness._engineering_record_protocol()`. That helper prefers
  `protocol_router.resolve_protocol()`'s **canonical** value (e.g. `"usb"`) —
  the only source that is both real and *stable across independent runs*,
  which an equality-matched dedup key requires — and keeps the gate block's
  unjudged value as the fallback for a run whose protocol genuinely did not
  resolve. Neither source present still yields `None`; never a fabricated
  placeholder. Both `run_stage()` call sites pass it using the same
  `((route_info or {}).get("protocol_decision") or {}).get("protocol")` idiom
  already used for `InnerReactLoop`.
- **`dv_harness/memory.py`** — the dedup match is now the shared
  `find_confirming_engineering_match()`, and
  `MemoryConsolidator.from_closed_finding()` **confirms** a re-derived closed
  finding instead of minting a competing copy. It lives in `memory.py` (not
  the router) so both Engineering-tier write paths share one definition of
  "the same finding again" — the router imports `memory`, so the consolidator
  could not have reused a router-side helper.
- **`dv_harness/memory_router.py`** — reuses the shared matcher; the now-false
  KNOWN LIMITATION paragraph is gone (Engineering Discipline Rules: comment
  hygiene).
- **Docs/skills** — `CLAUDE.md`'s Engineering Memory Policy,
  `docs/MEMORY_ARCHITECTURE.md`, `.claude/skills/CORE/memory-consolidation`
  and `memory-gc` now describe the real mechanism, including that it was
  previously unreachable. `docs/MEMORY_ARCHITECTURE.md` /
  `docs/MEMORY_SCHEMA.md` citation line numbers were re-derived for the moved
  symbols (`doc_citation_check` is a real suite test).

### Why this is not just "a field got filled in"

Keying on the canonical protocol cannot over-confirm unrelated findings: the
match additionally requires exact (case-insensitive) `root_cause` equality, so
a hit means the same root cause was re-derived within the same protocol —
which is the definition of a confirmation. The integrity model is untouched:
`confirmation_count` is still writable only by `MemoryGC.confirm()`, so no
caller can forge it.

---

## 4. Tests

New: `dv_harness_tests/test_engineering_confirmation_accumulation.py`
(12 tests). It exercises the **real** path, not the API:
a real `DVHarness.run_stage()` against the **real shipped
`main_graph.json`**, all 11 real `STAGE_GATES["RE_AUDIT"]` gate scripts run as
real subprocesses, a real un-mocked `route_and_store()` writing a real
`MemoryStore` — and **no direct `MemoryGC.confirm()` call anywhere**, which is
the whole point (the pre-existing `organizational_promotion_fixture.py` earns
its confirmations by calling `confirm()` twice by hand, which is exactly what
never proved the production writers could get there).

What it proves:
- three independent gate-verified RE_AUDIT PASSes leave **one** engineering
  record at `confirmation_count == 2` (previously: three records, all 0);
- `promote_to_organizational()` then really lands it in
  `ORGANIZATIONAL_MEMORY`, with `promotion_gate` showing the real
  `re_audit_gate_shape` / HIGH confidence / count 2 — and still refuses after
  a single PASS with `INSUFFICIENT_CONFIRMATION`;
- negatives: a different protocol's identical `root_cause` stays two records
  (the key is a pair, not similar words); an unresolved protocol still writes
  its record with `protocol: None` and never fabricates a key; the
  no-protocol consolidator finding is still added fresh;
- a guard test pinning `resolve_protocol()`'s real output for the fixture
  goal, so an alias change cannot silently turn the accumulation tests into
  vacuous no-ops.

**Test summary: 593 passed, 0 failed** — every relevant suite, run against the
**committed tree in an isolated `git worktree`** so another workflow's
uncommitted edits could not contaminate the signal:

| Run | Result |
|---|---|
| new accumulation tests + `test_doc_citation_check` | 29 passed |
| full memory suite (15 modules) + `test_inference_engine_wiring` + `test_protocol_and_environment_mode_engine_wiring` | 307 passed |
| `test_engine_gates_and_routing` + `test_system_level_soc_composition_wiring` + `test_qualified_conclusion_closure_gate` | 257 passed (exit 0) |

An earlier full-suite run over the *working* tree was deliberately abandoned
rather than reported: that tree also holds a concurrent workflow's uncommitted
`engine.py` / `blackboard.py` / `env_manifest.py` / `question_queue.py`
changes, so a pass or a failure there would not have been attributable to this
change. The isolated committed-tree runs above cover every module this change
touches, which is the stronger signal, not a weaker substitute.

---

## 5. Concurrency handling (important for whoever reads the history)

`dv_harness/engine.py` and `dv_harness/memory_router.py` both carried another
in-flight workflow's uncommitted changes in the same working tree. I did not
do a broad `git add`. I trimmed `git diff` to only my own hunks, recomputed
each kept hunk's new-side start, and staged via
`git apply --cached --check` → `git apply --cached`:

- `engine.py`: 7 of 10 hunks staged (the other 3 are that workflow's
  stage-progress-display work, left untouched and still unstaged).
- `memory_router.py`: 2 of 10 hunks staged.

Mid-pass that other workflow committed its `memory_router.py` change
(`ed7a546`), moving HEAD under me; I re-derived the doc citation line numbers
against the real post-move tree and re-verified with
`test_doc_citation_check.py`. I also unstaged one of that workflow's report
files that had appeared in the shared index, so it is not swept into my commit.

---

## 6. Known-unrelated failures observed (NOT caused by this change)

`dv_harness_tests/test_cli_pueue.py` — 5 failures. Environmental: the module's
skip guard only checks that the `pueue` binary exists, but the tests need a
running `pueued` daemon, and this machine has none:

```
Failed to connect to the daemon on 127.0.0.1:6924. Did you start it?
```

Nothing in this change touches pueue. Flagged rather than fixed (out of
scope); the real defect there is the skip guard testing for the binary
instead of daemon reachability.

---

## 7. Remaining, deliberately not done

`MemoryConsolidator.from_closed_finding()` still bypasses
`engineering_admission_gate()` (it writes via `store.add()` directly, and
routing it through `route_and_store()` would be a circular import —
`memory_router` imports `memory`). Its own bar (single_sim PASS + regression
PASS/NOT_REQUIRED + reaudit CLEAN + `CONFIRMED` confidence) is *stricter* than
the admission gate's, and it has zero production call sites today, so this is
a noted boundary rather than an open risk. Closing it properly means moving
the admission gate itself down into `memory.py` — a separate, larger refactor.
