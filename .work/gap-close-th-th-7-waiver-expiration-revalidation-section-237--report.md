# TH-7 -- Waiver Expiration / Revalidation (spec section 237)

**Result: DONE**

**Test summary:** `dv_harness_tests/test_waiver_store_gate_wiring.py` -- 41 passed;
regression suites re-run and green: `test_waiver_store.py` + `test_hard_gate_script_smoke.py`
(182 passed), `test_engine_gates_and_routing.py` (239 passed),
`test_dashboard_interactive.py` (54 passed), `test_gate_package_root_env.py` /
`test_react_loop.py` / `test_self_tuning.py` / `test_stage_scoped_completion_percent.py` /
`test_requirement_contract.py` / `test_signoff_stage_gate_e2e.py` (191 passed), and
`-k "prompt or waiver"` across the whole suite (70 passed).

---

## 1. The gap, independently re-verified before building

Re-verified by direct search on 2026-09-06, not taken from the audit:

- `dv_harness/waiver_store.py` existed with a 4-field schema
  (`gate_id`/`item_id`/`approved`/`evidence`, `REQUIRED_FIELDS`) and **no status concept at all**.
  Its own module docstring disclosed the disconnection verbatim: *"There is no fixed harness code
  path today that reads a waivers store from a known location before invoking a gate. This module
  intentionally does not force an integration point into that ad hoc flow."*
- `dashboard.py`'s Waiver Authoring card said the same thing to the human operator: *"This store is
  not wired into any gate script's own `--waivers`/`--holes`/`--coverage` input today."*
- `grep -rl waiver tools/verification_flow/` found the three real gates
  (`waiver_scope_consistency_gate.py`, `waiver_revision_freshness_gate.py`,
  `waiver_revalidation_gate.py`), all registered in `STAGE_GATES["REQUIREMENTS_TRACEABILITY"]`, all
  reading records assembled by `gates.run_gate()` **purely from the agent's own fenced
  ```dv-harness-evidence:<gate_id>``` block**.
- Consequence: a waiver was self-attested end to end -- the same agent wrote the waiver and the
  evidence it was still valid. An expired waiver was not re-flagged; it simply stopped being
  mentioned.
- Schema mismatch confirmed: the store's four field names share **not one** name with what the three
  gates read (`waiver_id`, `requirement_ids`, `subsystem`, `spec_revision`, `design_evidence_hash`,
  `approval_id`, `scope_hash`, `rtl_hash`, `revision`, `expires_at`, `revalidated_for_revision`,
  `trigger_conditions_changed`, ...), and section 237's status vocabulary
  (VALID / REVALIDATION_REQUIRED / EXPIRED / REVOKED / UNKNOWN) appeared nowhere in the repo.

This was a wiring/integration task and was scoped as one: no new gate script, no new stage gate, no
second waiver mechanism.

## 2. What was built

### `dv_harness/waiver_store.py` (rewritten, back-compatible)

- Section 237's record shape (`CANONICAL_REQUIRED_FIELDS`: waiver_id / item / reason / evidence /
  scope / approver / affected_version / risk / created_at, plus expiry and/or revalidation trigger).
- `WAIVER_STATUSES` = section 237's five values, verbatim.
- `derive_status(record, now, current)` -- **derived on every read, never stored**
  (`record_waiver()` refuses a caller-supplied `status`), the same reason
  `golden_scenario.evaluate_freshness()` computes rather than stores. Worst-first:
  REVOKED -> UNKNOWN -> EXPIRED -> REVALIDATION_REQUIRED -> VALID, so a human's revocation outranks
  the clock.
- "We could not check" is never VALID: missing section 237 fields, no expiry *and* no revalidation
  trigger, and an unparseable timestamp each derive UNKNOWN with a real reason.
- `SUPPORTED_TRIGGER_KEYS` (`spec_revision`/`rtl_hash`/`revision`) + `GATE_STATUS_CONTEXT` +
  `assert_trigger_coverage()` (runs at import): a trigger no gate measures cannot be declared, and a
  gate is never handed a fact it did not observe.
- `gate_records()` / `_projection()` -- the single place that knows how the three scripts spell the
  same waiver. `unbacked_declared_ids()` -- the ids an agent cites that the ledger has no record of.
- `record_waiver()` (canonical writer, refuses stored status / unsupported trigger / incomplete
  scope / duplicate id / neither-expiry-nor-trigger), `revoke_waiver()` (requires a named human AND
  a reason), `status_report()`, and `execute_verb()` front door
  (`python -m dv_harness.waiver_store statuses|list|status`; exit 0/1/2).
- Legacy `append_waiver()`/`read_waivers()`/`REQUIRED_FIELDS` unchanged in behaviour; writes now go
  through the existing `storage._atomic_replace()` rather than a truncate-then-write.

### The three real gates (`tools/verification_flow/waiver_*.py`)

Each now imports `dv_harness.waiver_store` through the `DV_HARNESS_PACKAGE_ROOT` env var
`run_gate()` already supplied for exactly this (same idiom as `rtl_write_scope_guard_gate.py`).
When `.dv-harness/waivers/waivers.json` exists it is authoritative:

- records evaluated are the ledger's, projected into that script's own field names;
- an agent-cited `waiver_id` with no ledger record FAILs `WAIVER_NOT_IN_STORE` (new exit 8);
- a non-VALID derived status FAILs with `WAIVER_EXPIRED` / `WAIVER_REVALIDATION_REQUIRED` (the
  scripts' OWN pre-existing tokens) / `WAIVER_REVOKED` / `WAIVER_STATUS_UNKNOWN`;
- every pre-existing check still runs over those records, unchanged;
- every result carries `"source": "waiver_store" | "agent_evidence_block"`.

Fail-closed if `dv_harness` is not importable (`WAIVER_STORE_UNAVAILABLE`, exit 9) -- we cannot then
tell whether a ledger exists, and that is not a pass.

### `dv_harness/gates.py`

One new helper, `_gate_env(root)`, replacing the two inline env dicts. It adds
`DV_HARNESS_PROJECT_ROOT` alongside the existing `DV_HARNESS_PACKAGE_ROOT`: a harness-supplied fact
with the same trust property as a `ContextFlag` (never read from agent text, so a gate cannot be
pointed at a fabricated root). Chosen over a `ContextFlag` because two of the three scripts take a
single whole-payload flag, and converting them to multi-flag form would change the evidence-block
shape every existing project's prompt emits. No gate registration, verdict mapping or approval
behaviour changed.

### `dv_harness/dashboard.py`, `dv_harness/prompts.py`

- Corrected the now-false "not wired into any gate script" note (stale-comment hygiene) and extended
  the Waiver Authoring form with section 237's fields so a human can record a *checkable* waiver;
  the original 4-field submission still works (`waiver_id` absent -> legacy body). The POST handler
  is unchanged in structure -- `WaiverStoreError` subclasses `ValueError`, so every refusal reaches
  the caller as a 400 with its real reason.
- `prompts.py`'s REQUIREMENTS_TRACEABILITY prompt now states that the ledger is the source of truth,
  that fabricating a `waiver_id` FAILs `WAIVER_NOT_IN_STORE`, that status is derived and not
  overridable, and that `current`/`current_revision` must still be reported honestly.

## 3. The test that proves it

`test_expired_ledger_waiver_reflags_the_item_the_agent_never_mentioned` -- the requested proof:

1. a waiver is recorded in a REAL ledger on disk via `record_waiver()`, waiving `REQ-USB-014`, with
   an expiry in the past;
2. the agent's own evidence block declares **no waivers at all** (exactly what a self-attested flow
   produces once a waiver becomes inconvenient);
3. the REAL `gates.evaluate_stage_evidence()` runs the REAL shipped
   `STAGE_GATES["REQUIREMENTS_TRACEABILITY"]` scripts as subprocesses and returns `GATE_FAIL` with
   `WAIVER_EXPIRED`, naming `W-USB-001` and `"source": "waiver_store"`;
4. the ledger names the requirement that is no longer waived.

Negative control: the identical ledger, agent text and gates with only the expiry moved reach a real
`PASS`. Nothing is mocked. Other tests cover fabricated citations, a legitimate citation, revocation,
a moved `rtl_hash` and its clearance by real revalidation evidence, legacy records reading UNKNOWN,
the gates' own pre-existing checks over ledger records, the un-migrated project's original PASS and
`WAIVER_REVISION_STALE` paths, all five derived statuses, every `record_waiver()` refusal, a
byte-level proof that reading writes nothing, and both CLI exit codes as real subprocesses.

## 4. Boundaries preserved

- **No human-approval gate weakened.** `ControlPlane.approve()`, `policy.can_signoff()`,
  `assert_human_approval()` and the PR-only main/master governance are untouched and uncalled from
  any file changed here. Everything added can only REFUSE a waiver; nothing grants one. Recording
  and revoking stay human acts.
- **No production build/regression/LSF submission.** Every test runs gate scripts as local
  subprocesses over synthetic fixtures in `tmp_path`.
- **No arbitration.** The store reports what a record's content implies; it revalidates nothing and
  picks no winner.

## 5. Deferred, and why

- The other three waiver-consuming gates (`coverage_hole_regeneration_gate`,
  `coverage_hole_to_test_generation_gate`, `sequence_coverage_closure_gate`) are **not** wired: they
  read coverage-hole and sequence payloads, a different domain from section 237's waiver record.
- **No `dv-harness` CLI verb** -- `dv_harness/cli.py` was being modified by concurrent work in this
  same session, so the front door is `python -m dv_harness.waiver_store` (the same convention
  `confidence_calibration.py` and `resource_orchestrator.py` adopted for the same reason).
- **This repository has no ledger of its own** and none was fabricated to make the mechanism look
  like it had fired here; a test asserts that, so adopting one later cannot silently change the
  pre-existing gate test's meaning.

## 6. Files

- `dv_harness/waiver_store.py` (rewritten)
- `tools/verification_flow/waiver_revalidation_gate.py`
- `tools/verification_flow/waiver_revision_freshness_gate.py`
- `tools/verification_flow/waiver_scope_consistency_gate.py`
- `dv_harness/gates.py` (`_gate_env()`)
- `dv_harness/dashboard.py`, `dv_harness/prompts.py`
- `dv_harness_tests/test_waiver_store_gate_wiring.py` (new, 41 tests)
- `CLAUDE.md` (new section: "Waiver Ledger Is the Source of Truth for the Waiver Gates")

## 7. Commit note (shared-worktree race, recorded honestly)

This work's content landed in commit `4b51502`, whose message reads
"SPEC-6: add REMOVE_DUPLICATE, SYS-17's eighth decision (spec section 198)". That is not a
mis-scoped commit by this pass: a concurrently-running close-pass in the SAME worktree ran its own
`git commit` against the shared index in the window between this pass staging its hand-scoped patch
and running its own pathspec commit, so its commit swept in every TH-7 file. Nothing was lost and
nothing of that pass's work was disturbed; the history was deliberately NOT rewritten (another agent
is actively working on this branch and an amend/rebase there is destructive). This section is the
attribution record: `4b51502` carries TH-7 as listed in section 6 above.
