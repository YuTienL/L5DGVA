# Gap-close: AI mechanism #7 — 5-Level Memory Engine

**Status: DONE** (one real wiring gap closed) — with two of the audit's named
gaps confirmed **NEEDS_SEPARATE_EFFORT / environment-blocked** and explicitly
*not* faked.

Date: 2026-09-04 · Branch: `gap-close/env-manifest-fact-sources`

> **Supersedes the earlier pass's report at this same path** (still in git
> history at `HEAD~`). That pass closed a *different, non-overlapping* gap on
> this mechanism — `EvidenceStore.insert_job_memory_record()` was dormant, and
> it was wired into `regression_reporter._write_reconciliation_evidence_if_
> configured()` so the JOB tier mirrors into DuckDB. That fix stands and is
> unchanged here. This pass addresses the **Engineering → Organizational**
> half instead.

---

## 1. Re-verification of the audit's evidence (done first, independently)

| audit claim | re-verified? | how |
|---|---|---|
| tier counts engineering 31 / project 46 / working 14 / job 1 / organizational 0 | **yes, exact** | `ls .dv-harness/memory/<tier>/*.json \| wc -l` |
| the one `job/` file is a hand-authored seed | **yes** | `MEM-95C1FFE3A0.json` carries `"note": "Illustrates CLAUDE.md rule…"`, `job_id: "J-2026-0431"`, and **none** of the real write schema's fields (`lsf_status`, `dv_analysis_status`, `uvm_error_count`, `terminal_signature`); its `memory_id` is not the `JOB-{jid}-TERMINAL-RECONCILE` form `lsf_client.job_tier_memory_id()` produces |
| no `bjobs` on PATH | **yes** | `which bjobs bsub` → not found; `.dv-harness/lsf/watcher.log` still logging `discover_live_jobs failed: bjobs not found on PATH` every cycle through 19:40:12 today |
| zero jobs ever registered | **yes** | `.dv-harness/lsf/jobs/` holds only `README.md` |
| the reconcile cycle degrades rather than crashes | **yes, and there is no code bug here** | `regression_reporter.run_reconciliation_cycle()` catches `LsfUnavailableError`, sets `live_jobs = []`, and still processes the disk half of the union — which is empty because nothing is registered. The job-memory write path is not bypassed by a defect; it has no input. |
| `confirmation_count >= 2` nowhere on disk | **yes** | highest anywhere is `1` |

**Conclusion on the two named gaps: the audit is right, and neither is a code
gap that this pass can honestly close.**

- **Job Memory** — an environment/connectivity gap. It needs a real Linux DV
  server with LSF, a submitted job reaching DONE/EXIT, and a real
  `lsf-reconcile`. Nothing in Python fixes it. Writing another
  `.dv-harness/memory/job/*.json` by hand would just add a second seed of
  exactly the kind the audit correctly called out. **Not attempted.**
- **Organizational Memory's third gate** — needs a *genuine second independent
  debug/verify run* re-deriving an already-recorded `root_cause`. Manufacturing
  one in this pass to bump `confirmation_count` would be "the same run reported
  twice", which CLAUDE.md forbids outright. **Not attempted.**

---

## 2. The real, in-scope code gap I did find and close

While verifying the organizational finding I found a concrete **wiring
asymmetry** in the production path — the kind of gap this pass exists for, and
the structural reason the organizational tier could not be reached organically
from the path that actually populates this project's store.

`promote_to_organizational()`'s third gate can only ever be cleared by
`MemoryGC.confirm()`, which `memory_router._add_or_confirm_engineering()` fires
when a write matches an ACTIVE engineering record on `(protocol, root_cause)`.
`route_and_store()` reports that as **`confirmed_existing`**.

`DVHarness` has **two** real Engineering-tier writers, both reachable from a
real `run_stage()` PASS, and both able to cause that confirmation:

| writer | stage | record kind | evaluated organizational promotion afterwards? |
|---|---|---|---|
| `_promote_verified_fix_knowledge()` | RE_AUDIT | `verified_fix` | **yes** |
| `_promote_experience_knowledge()` | EXPERT_FEEDBACK_LOOP | `debug_lesson` | **no — nothing listened** |

So an EXPERT_FEEDBACK_LOOP PASS independently re-deriving a root cause a
previous RE_AUDIT had already recorded would raise that record's
`confirmation_count` past `ORGANIZATIONAL_MIN_CONFIRMATIONS` — clearing the one
gate that has never been cleared in this repo's history — and **nothing would
ask whether the record now qualified.** The tier was reachable from that path
only if a human remembered to run `dv-harness memory promote` by hand. That
manual step is, notably, exactly what the audit's own "exact fix" text
prescribes ("*Then* call `promote_to_organizational()` via CLI") — it is the
workaround for this missing wire.

This also matters because the record being confirmed is typically the
*verified_fix* one, which already carries the RE_AUDIT verification shape that
satisfies gate 1 — i.e. the confirmation genuinely is the last gate standing.

### Why the wire could not simply be copied across

`promote_to_organizational()` needs `inference.score_confidence()`'s four
inputs, and only a real `root_cause_evidence_gate` evidence block yields them.
Per `gates.STAGE_GATES`, `experience_knowledge_gate` is registered on
**EXPERT_FEEDBACK_LOOP alone**, and `root_cause_evidence_gate` only on
RCA_JOIN/RE_AUDIT — so that call site has no root-cause evidence to score, and
inventing counts there would fabricate a HIGH confidence.

Fix: the run that *does* have a real block now **persists what it really
derived**, and the confirming run re-reads it from the durable store. No second
scoring system, no new derivation formula, no fabricated values. This also
narrows the limitation `organizational_admission_gate()`'s own docstring names
("score_confidence()'s inputs … are not persisted on the source engineering
record").

### Changes (3 hand-scoped hunks in `dv_harness/engine.py`, 1 new test file)

1. `_promote_verified_fix_knowledge()` — computes
   `self._root_cause_confidence_inputs(rc_block)` **once** and now also
   persists it on the record as `confidence_inputs`. (`MemoryStore.add()`
   preserves arbitrary fields; verified.)
2. New `DVHarness._evaluate_organizational_promotion(stage, memory_id,
   confidence_inputs)` — runs `promote_to_organizational()` and emits the
   `ORGANIZATIONAL_PROMOTION_EVALUATED` event. The emitted payload is
   **byte-identical** to the one `_promote_verified_fix_knowledge()` emitted
   inline before, so both writers now report one event vocabulary. A `None`
   input records `{"promoted": false, "reason": "NO_CONFIDENCE_INPUTS"}` —
   an honest, visible non-evaluation instead of a fabricated score.
3. `_promote_experience_knowledge()` — gains the missing hook, fired **only on
   `confirmed_existing`** (the precise moment gate 3 can newly clear; a
   freshly-minted record has count 0 and could only ever emit noise), reading
   the confirmed record's persisted `confidence_inputs` from the store.

Not a forgery surface on its own: gates 1 and 3 are re-read from the durable
store by `promote_to_organizational()` *and* independently re-checked at the
write boundary by `organizational_admission_gate()`, and `confirmation_count`
is writable only by `MemoryGC.confirm()` — persisted confidence inputs alone
promote nothing.

**No parallel mechanism was built.** `promote_to_organizational()`,
`score_confidence()`, `_root_cause_confidence_inputs()`,
`_add_or_confirm_engineering()` and `MemoryGC.confirm()` are all reused
verbatim.

---

## 3. Tests

New: `dv_harness_tests/test_organizational_promotion_evaluation_wiring.py` (4
tests). These run the **real cross-stage production sequence** — a real
`run_stage()` RE_AUDIT PASS followed by real EXPERT_FEEDBACK_LOOP
`run_stage()` PASSes, every mapped gate script executed as a real subprocess, a
real un-mocked `route_and_store()` against a real `MemoryStore`. Nothing calls
`promote_to_organizational()` or `MemoryGC.confirm()` directly; that is the
point — the old tests proved the function worked in isolation, which was never
the gap.

- `test_re_audit_persists_the_real_confidence_inputs_on_the_engineering_record`
  — the persisted inputs exist on disk, have exactly the four real keys, and
  really score HIGH (so a fixture change cannot silently make the next test
  vacuous).
- `test_expert_feedback_loop_pass_that_confirms_a_record_evaluates_organizational_promotion`
  — **the gap.** RE_AUDIT records the finding (count 0); EFL PASS #1 confirms
  it (count 1) and the evaluation fires and honestly refuses with
  `INSUFFICIENT_CONFIRMATION`; EFL PASS #2 confirms again (count 2) and the
  record **really lands in `ORGANIZATIONAL_MEMORY` by itself**, with
  `qualitative_shape == "re_audit_gate_shape"` and confidence `HIGH`. Still
  exactly one `verified_fix` record — confirming never mints a rival copy.
- `test_a_first_experience_pass_that_confirms_nothing_evaluates_nothing`
  — precision: bound to the confirmation event, not to "a record was written".
- `test_a_confirmed_record_without_persisted_confidence_inputs_is_not_scored_on_invented_ones`
  — honesty: a pre-existing record with the field stripped yields
  `NO_CONFIDENCE_INPUTS`, never a fabricated HIGH.

### Test summary

`test_organizational_promotion_evaluation_wiring.py` 4/4 passed (422s, real
gate subprocesses); `test_engineering_confirmation_accumulation.py` +
`test_inference_engine_wiring.py` + `test_memory_tier_integrity_and_admission.py`
+ `test_memory_vault.py` + `test_memory_doctor.py` 54/54 passed (exit 0);
`test_engine_gates_and_routing.py` passed.

---

## 4. Concurrency handling

`dv_harness/engine.py`, `memory.py` and `memory_router.py` all carried large
uncommitted changes from other workstreams in this session. I never rewrote a
shared file: all three edits were anchored `Edit` operations, and the commit
was staged with a **hand-scoped patch** (`git apply --cached` of only my three
hunks, extracted from `git diff -U3`, validated with `--check` first), so no
other workstream's in-flight engine.py work was swept into this commit.

---

## 5. What remains open (deliberately, for a separate effort)

1. **Job Memory tier — environment.** Needs a real LSF-bearing Linux DV server
   via `tools/remote/remote_exec.py`: submit one job, let it reach DONE/EXIT,
   run `dv-harness lsf-reconcile --job-ids <jid>`, then verify
   `lsf_client.load_job_tier_memory_record(root, jid)` returns a record at
   `.dv-harness/memory/job/JOB-<jid>-TERMINAL-RECONCILE.json` with the real
   schema fields. The code path is already wired into a live-running watcher;
   only the input is missing.
2. **A first real Organizational record in *this* project's store.** The
   evaluation now fires automatically on the real path, and the new test proves
   it promotes for real once the gate is cleared. Clearing it *in this repo*
   still requires a genuine second independent debug pass re-deriving an
   already-recorded `root_cause` — real verification work, not a code change,
   and never a hand-edited `confirmation_count`.
