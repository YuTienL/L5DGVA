# Gap-close: Phase 4+5 — 5-Level Memory tiers + Promotion Engine

**Status: DONE** — one real gap found and closed. The incoming audit's two
READY verdicts were re-confirmed on the code, but re-verification of Phase 5
found the audit's *reasoning* for gate 3 unsound, and the gap it hid was real
and reproducible.

Scope: audit re-verification + gap closure only. No other workflow's files
were touched (`connectivity.py`/`test_connectivity.py`, `CLAUDE.md` and the
live `.dv-harness/memory/**` data files are modified by concurrent efforts and
were deliberately left alone — see "Concurrency" below).

---

## Phase 4 — 5-Level Memory Architecture: **READY** (re-confirmed, no action)

Every cited item re-read at source and re-counted live. All accurate:

| Tier | Class | file:line | Live count |
|---|---|---|---|
| Working | `WorkingMemoryStore(_TierMemoryStore)` | `dv_harness/memory.py:793` | 14 |
| Job | `JobMemoryStore(_TierMemoryStore)` | `dv_harness/memory.py:806` | 1 |
| Project | `ProjectMemoryStore(_TierMemoryStore)` | `dv_harness/memory.py:809` | 46 |
| Engineering | plain `MemoryStore.add("engineering",…)`, no wrapper by design | `memory_router.py:41-50` | 31 |
| Organizational | `OrganizationalMemoryStore` → `KnowledgeCenterClient` | `dv_harness/memory.py:829` | 0 local (by design) |

Also independently re-checked (the audit's other Phase 4 claims): the Job-tier
field set at `lsf_client.py:1106-1129` really carries `job_id`/`pattern`/
`lsf_status` kept separate from `dv_result` (= `state.sim_status`, per
"LSF DONE ≠ DV PASS")/`uvm_error_count`/`uvm_fatal_count`/`terminal_signature`
and the `root_cause_status`/`fix_proposal_status` fix-attempt pair; and
`docs/MEMORY_ARCHITECTURE.md:74-97`'s tier/routing/verified-required table
matches `route_memory()` exactly.

- `MEMORY_LEVELS` confirmed at `dv_harness/memory.py:10`.
- The "no local organizational file store" design is real and load-bearing,
  not an omission — `memory_router.py:148-158` routes that destination
  straight to the Knowledge Center and explicitly documents why it does *not*
  fall through to the generic `MemoryStore.add("organizational", …)` dispatch.
  (This detail mattered: it invalidated a first draft of one of my new tests,
  which tried to read a promoted record back off disk.)
- Line numbers shifted ~+45 vs. the incoming audit because of my own edit to
  this file; the classes and design notes are the ones cited.

## Phase 5 — Memory Promotion Engine: audit said READY; **corrected to a real gap, now closed**

Gates 1 and 2 re-confirmed exactly as audited (`memory_router.py:246` /
`:445` / `:544`; `inference.score_confidence()` at `inference.py:25-64`,
including the counter-evidence safety floor).

### The gap: gate 3's input was forgeable by the record it gates

`promote_to_organizational()`'s third gate reads `confirmation_count` back off
the stored record. `MemoryStore.add()` set that field with a plain
`setdefault("confirmation_count", 0)` — so **a value supplied in the record
body passed straight through to disk**, and the gate then read it as if it had
been earned. One creation event could self-declare the repeated confirmation
the gate exists to require.

Reproduced live before writing any fix — a **single** `route_and_store()` call:

```
SINGLE creation event -> stored confirmation_count = 7 | last_confirmed_at = None
PROMOTED -> destination = ORGANIZATIONAL_MEMORY
gate = {"qualitative_shape": "finding_consolidation_shape",
        "confidence_result": {"level": "HIGH", "score": 10}, "confirmation_count": 7}
```

This directly violated three things that all already said otherwise:
- the Phase 5 spec ("must NOT let … single-PASS results jump straight to
  Organizational"),
- `promote_to_organizational()`'s own docstring ("one creation event is not
  revalidation"),
- CLAUDE.md:70 ("a second independent run re-deriving the same
  root_cause/protocol — **not the same run reported twice**") and
  `docs/MEMORY_SCHEMA.md:25` ("incremented ONLY by `MemoryGC.confirm()`").

The prose was already correct everywhere. Only the code failed to enforce it,
so this was a code/doc divergence, not a design change.

**Why the audit missed it.** It reasoned from the observed data
distribution — "all 31 engineering records have `confirmation_count` 0,
therefore the gate binds" — rather than testing whether the counter could be
forged. An all-zeros distribution is consistent both with a binding gate and
with a bypass nobody had happened to use yet.

**Two live-truth corrections to the audit's evidence**, both re-measured:
1. The distribution is now `Counter({0: 30, 1: 1})`, not `{0: 31}` — another
   workflow wrote a record since. Notably that record (`MEM-34FD025AD6`) has
   `confirmation_count=1` with `last_confirmed_at=None`, and since
   `MemoryGC.confirm()` always sets the two together, that value was **never a
   real confirmation** — it is live evidence of the forgeable path being
   exercised in production, not hypothetically.
2. The audit's claim that all records "would return `INSUFFICIENT_CONFIRMATION`
   regardless of confidence inputs" is wrong about gate ordering: with maximum
   confidence inputs, 30 return `QUALITATIVE_GATE_FAILED` (gate 1 fires first)
   and 1 returns `INSUFFICIENT_CONFIRMATION`. Zero promoted — the conclusion
   held, the stated mechanism did not.

### The fix

`confirmation_count`, `last_confirmed_at` and `last_confirmation_evidence` are
now **integrity-owned**: `MemoryStore.add()` discards whatever the record body
carries and restores the real on-disk value
(`_apply_confirmation_integrity()`, `dv_harness/memory.py:194`).
`MemoryGC.confirm()` — which increments from the stored value under its own
read-modify-write — is the one authorized writer and passes a private
`_confirmation_write=True` (`memory.py:596`).

Deliberately symmetric: a re-add can neither **invent** confirmations nor
silently **drop** them, so the ordinary round-trip writers (`mark_used()`, the
`knowledge_commit_sha` write-back, `MemoryGC`'s revalidation paths) keep the
earned count exactly.

Also fixed a smaller latent issue this exposed: `promote_to_organizational()`
built the new organizational record with `"confirmation_count":
confirmation_count`, copying the *source* record's count under the field name
that means "this record's own confirmations". Renamed to
`source_confirmation_count` (`memory_router.py:533`), so a freshly-promoted
record cannot look pre-confirmed.

Scoped to `MemoryStore` only. `CornerCaseLibrary` has its own separate
`confirm()`/counter and is not read by the organizational gate — left untouched.

### Files changed

| File | Change |
|---|---|
| `dv_harness/memory.py` | `_CONFIRMATION_OWNED_FIELDS`, `_apply_confirmation_integrity()`, `add(..., _confirmation_write=False)`; `MemoryGC.confirm()` becomes the authorized writer |
| `dv_harness/memory_router.py` | `confirmation_count` → `source_confirmation_count` on the promoted record |
| `dv_harness_tests/test_memory_tier_integrity_and_admission.py` | new section 4: 6 regression tests |
| `dv_harness_tests/test_cli_memory_commands.py` | `test_memory_promote_succeeds_through_all_gates` now EARNS its two confirmations via `MemoryGC.confirm()` — see below |
| `docs/MEMORY_ARCHITECTURE.md` | gate-3 integrity paragraph + the provenance-field note |
| `docs/MEMORY_SCHEMA.md` | the three fields' rows now say the invariant is enforced, and by what |

### Tests

Six new tests in `test_memory_tier_integrity_and_admission.py`, all
behavioral — no parse/import smoke tests:

- the forged value is discarded at creation (**fails pre-fix**: stored 7);
- a single creation event carrying `ORGANIZATIONAL_MIN_CONFIRMATIONS` is
  refused with `INSUFFICIENT_CONFIRMATION` (**fails pre-fix**: promoted — this
  is the reproduction above, frozen as a regression test);
- a direct `MemoryStore.add()` cannot forge it either, proving the guard sits
  at the store and not only at the router (**fails pre-fix**: stored 5);
- an ordinary re-add neither invents nor drops confirmations (**fails
  pre-fix**: a re-add carrying 0 silently un-confirmed the record);
- the promoted record carries `source_confirmation_count`, not its own
  (**fails pre-fix**: the field was named `confirmation_count`);
- two genuine `MemoryGC.confirm()` calls still reach `ORGANIZATIONAL_MEMORY`
  — the positive half, which **passed pre-fix too** and is included precisely
  so the fix cannot close the forged path by breaking the earned one.

**One pre-existing test had to change, and it is the most telling artifact of
this gap.** `test_cli_memory_commands.py::test_memory_promote_succeeds_through_all_gates`
seeded `"confirmation_count": 2` directly into the record body and asserted the
CLI promoted it — i.e. the CLI's entire happy path was proven against exactly
the forged input the gate exists to reject, which is part of why the hole
survived review. It now earns the two confirmations through
`MemoryGC.confirm()` and additionally asserts the stored count really is 2
before invoking the CLI. Two other tests already seeded the field
(`test_obsidian_memory_final_integration.py`, which asserts a
`QUALITATIVE_GATE_FAILED` rejection, and `test_memory_vault.py`, which already
used genuine `confirm()` calls) and needed no change.

**One-line test summary:** the full memory-adjacent suite passes —
**233 passed, 0 failed** across 10 files, all re-run against the final code.

| Suite | Result |
|---|---|
| `test_memory_tier_integrity_and_admission.py` (incl. the 6 new) | 29 passed |
| `test_memory_vault.py` + `test_memory_tier_completion.py` + `test_cli_memory_commands.py` | 77 passed |
| `test_inference.py` + `test_debug_flow_memory.py` | 45 passed |
| `test_obsidian_memory_final_integration.py` | 14 passed |
| `test_engine_gates_and_routing.py` | 28 passed |
| `test_inference_engine_wiring.py` + `test_knowledge_center.py` | 42 passed |

### Concurrency

Only `dv_harness/memory.py`, `dv_harness/memory_router.py`,
`dv_harness_tests/test_memory_tier_integrity_and_admission.py`,
`docs/MEMORY_ARCHITECTURE.md` and `docs/MEMORY_SCHEMA.md` were touched; all
five were verified clean of other workflows' edits before staging, and
`git diff` on each contained only my hunks, so a path-scoped `git add` was
sufficient and no hand-trimmed patch was needed. `CLAUDE.md` was modified by a
concurrent workflow and was deliberately **not** edited — its line 70 already
states this rule correctly, so no prose change was required.

`MEM-34FD025AD6`'s stale `confirmation_count=1` was left in place: it is live
memory data owned by concurrent efforts, it is below the threshold of 2 so it
is inert, and the new guard preserves on-disk values rather than rewriting
them. Flagged here rather than silently mutated.
