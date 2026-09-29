# Obsidian+Git/Markdown Hybrid Engineering Memory — Debug Flow, Regression Memory, Git Policy, Session Save/Restore (Workstream 3 of 4)

**Date**: 2026-09-03
**Scope**: Phases 10, 11, 13, 14 of the 25-phase spec, built on top of Workstream 1's
foundational `dv_harness/memory_vault.py`/`dv_harness/memory_router.py` layer (commit
`ceab932`, see `.work/obsidian-memory-core-report.md`). Workstream 2 (skills/CLI/dedup/
security/docs) and Workstream 4 (`.claude/agents/memory-agent.md`, `docs/MEMORY_*.md`)
were found already in flight/landed on disk during this work — see "Coordination with
concurrent workstreams" below for how this workstream's changes relate to theirs.

## What was built

### Phase 10 — Debug Flow (`dv_harness/engine.py`)

Real FAILURE_RECOVERY/RE_AUDIT stage handling in `DVHarness.run_stage()` was read in full
before changing anything (the existing step-1b/1b-2 Memory-tier and shared-Knowledge-Center
pre-stage reads, and `react_loop.InnerReactLoop`'s existing Reason→Act→Observe→Reflect
mechanism, both already real and wired — see Workstream 1's discovery notes, confirmed
correct here).

**BEFORE a debug attempt** — new step "1b-3", scoped to `FAILURE_RECOVERY`/`RE_AUDIT`
(same two stages step 1b-2's shared-KC search already covers):
- Builds a real `failure_signature` from the same already-available Blackboard `findings`
  last_report (symptom/root_cause) + `route_info["protocol_decision"]` step 1b-2 already
  reads, via the new shared `memory_vault.build_failure_signature()`.
- Searches the Workstream-1 `HybridMemoryProvider` vault (a *different* store than the
  shared Knowledge Center searched in 1b-2, and a *different* store than the plain
  per-project `MemoryRetriever` searched in 1b) via `memory_vault.search_related_memory_for_debug()`.
- Folds the ranked hits into the stage prompt as **prior evidence only** via a new,
  purely-additive `build_stage_prompt(..., vault_related_cases=...)` kwarg
  (`dv_harness/prompts.py`) — disclaimed with the exact same Evidence-Truth-Rule language
  as `relevant_memory`/`kc_search_results`, plus the spec's own explicit
  "不得直接假設 previous root cause == current root cause" line. Never presented as an
  assumed answer.

**DURING debug** — deliberately did **not** build a second parallel loop. The existing
`react_loop.build_menu()` already calls `inference.identify_gap()`/`next_best_action()`
for its `REQUEST_EVIDENCE` menu options (confirmed by reading `react_loop.py` in full
before touching it), and `engine._score_root_cause_confidence()` already calls
`inference.score_confidence()` on RE_AUDIT's `root_cause_evidence_gate` block. This
workstream's only change here is a refactor, not new logic: the
independent_sources_count/evidence_refs_verified/counter_evidence_count/
multi_agent_consensus_count derivation was factored out of `_score_root_cause_confidence()`
into a new `_root_cause_confidence_inputs()` helper so a second call site
(`_promote_verified_fix_knowledge()`, below) can reuse the *exact same* real
Hypothesis→Evidence→Confidence derivation instead of inventing a second one.

**AFTER debug**:
- **On FAIL/PARTIAL** (new step "3c", `FAILURE_RECOVERY`/`RE_AUDIT`, `ss["status"] in
  (FAIL, PARTIAL)`): new `DVHarness._record_debug_attempt_job_memory()` calls
  `route_and_store()` with `kind="job_failure"` — routes to **Job Memory only**
  (`route_memory()`'s existing `kind in ("job_result","job_failure","job_rerun") ->
  JOB_MEMORY` rule, unchanged) — carrying the stage/attempt/status/blocking_reason/the
  SAME `failure_signature` built in step 1b-3, and `git_sha`. Never
  `kind="root_cause"/"verified_fix"/"debug_lesson"`, so it structurally cannot reach
  ENGINEERING_MEMORY or trigger promotion — "no promotion" is enforced by construction,
  not by an extra check. `WAIT_USER`/`NEEDS_USER_INPUT` are excluded (those are "PASS
  pending a human action" / "needs an answer", not a failed debug attempt).
- **On PASS** (RE_AUDIT only — `FAILURE_RECOVERY`'s own `STAGE_GATES` never include
  `fix_effectiveness_gate`, so a `FAILURE_RECOVERY` PASS is "triage complete", not "debug
  succeeded", and correctly writes nothing on this path): extended the existing
  `_promote_verified_fix_knowledge()` (already recorded symptom/root_cause/fix/
  verification/confidence — see Workstream 1's discovery notes) with the three missing
  fields the spec names — **git SHA / test / result**:
  - `git_sha`: `fix_regression_non_regression_gate`'s own real `fix_commit_hash` when the
    closure gate captured one (that gate *requires* a non-empty one to PASS at all), else
    this harness's own `state.git_sha` as an honest fallback.
  - `rtl_sha`/`tb_sha`: `state.dut_version`/`state.tb_version` — the same real,
    gate-validated VERIFY-stage identity fields `models.HarnessState` already carries
    (never a second, differently-sourced identity).
  - `test`/`result`: `fix_regression_non_regression_gate`'s own real
    `target_testcase_id`/`target_post_fix_result` (cross-checked against the real JobState
    registry by that gate itself when a job_id was supplied).
  - Then **triggers** (the spec's own word — "trigger the Workstream-1 promotion
    evaluation", not "force a promotion") `memory_router.promote_to_organizational()` the
    moment the ENGINEERING_MEMORY write succeeds, using `_root_cause_confidence_inputs()`
    on the *same* `root_cause_evidence_gate` block `_score_root_cause_confidence()` already
    reads — composing with the real existing confidence framework, never a parallel one.
    Verified live (see Test Results): on a fixture whose evidence genuinely clears the
    qualitative gate and the confidence gate (HIGH), the real, non-trivial outcome is
    `INSUFFICIENT_CONFIRMATION` (`confirmation_count=0`) — a single verified fix does not
    yet clear `ORGANIZATIONAL_MIN_CONFIRMATIONS=2`, exactly the "no unverified/single-PASS
    jump to Organizational" guarantee the spec requires. Wrapped in try/except: a broken
    evaluation can never affect the already-completed `VERIFIED_FIX_PROMOTED` event.

### Phase 11 — Regression Integration (`dv_harness/lsf_client.py`, shared interface in `dv_harness/memory_vault.py`)

Read `lsf_client.py`/`regression_reporter.py` in full first, per the task's instruction.
The real UVM_ERROR/UVM_FATAL/timeout/abnormal-termination detection point already exists:
`_write_job_tier_memory_on_terminal_reconcile()`'s own `is_failure` derivation
(`state.lsf_status=="EXIT"`, `uvm_fatal_count>0`, `assertion_failure`, `simulator_crash` —
the same real fields `evaluate_auto_kill()` already treats as terminal triggers), which
already writes a real `kind="job_failure"` record to Job Memory on that signal. Extended
(never replaced) that one real call site:

- On `is_failure` only (never for a plain `job_result` — searching would be noise), builds
  a `failure_signature` (`pattern`, `uvm_error_count`/`uvm_fatal_count`/
  `assertion_failure`/`simulator_crash`/`terminal_signature`/`lsf_status`, plus
  `extra_text=state.pattern` so the real testcase name participates in the vault's text
  search — the one text signal available at this low level) and calls the **same** shared
  `memory_vault.search_related_memory_for_debug()` function engine.py's debug flow calls.
- **A real timing gap found and closed**: `_write_job_tier_memory_on_terminal_reconcile()`'s
  CRITICAL-discrepancy-gated write fires the FIRST time a job reaches a terminal LSF status
  (via `reconcile_batch()`, called from `regression_reporter.run_reconciliation_cycle()`),
  which is *before* that same cycle's real sim.log epilogue parse a few lines later — at
  write time, `uvm_error_count`/`uvm_fatal_count` can still be their pre-cycle values, so a
  job whose real failure only shows up in the log body (e.g. `lsf_status=="DONE"` with a
  real `UVM_FATAL` inside) could be mis-recorded `kind="job_result"`. Refactored the write
  body into a reusable `_upsert_job_tier_memory_record(root, jid, state)` and added a
  **second real call site** in `regression_reporter.run_reconciliation_cycle()`, right after
  it derives the real epilogue verdict/counts — upserting the same deterministic
  `JOB-{jid}-TERMINAL-RECONCILE` record with the accurate classification once better
  evidence exists. Also fixed `is_failure` itself to include `state.sim_status == "FAIL"`
  (a real "FAILED" epilogue verdict with both UVM counts genuinely zero — a timeout or a
  phase-declared failure — was not previously recognized as a failure at all). Covered by a
  new regression test in `test_regression_reporter.py` for exactly this scenario.
- Attaches `failure_signature` and (when any hit) `prior_related_knowledge` onto the
  **same** `job_failure` record already being written — so the Debug Agent that later
  picks this job up has it without a second search, but per CLAUDE.md's Evidence Truth
  Rule this is candidate prior evidence only: **the Debug Agent must always independently
  re-verify against current RTL/VIP/log/waveform evidence and must never copy a previous
  fix verbatim** — this workstream does not, and cannot, enforce that from `lsf_client.py`
  alone (it is a downstream agent-behavior discipline, already codified in CLAUDE.md's
  Evidence Truth Rule / Core Operating Rules, and now also in `docs/MEMORY_AGENT.md`'s
  "Evidence discipline this agent enforces on itself", built by Workstream 4). Best-effort:
  a search failure never blocks the real job-memory write.

**Shared interface definition (coordinating with the not-yet-integrated Memory Agent, per
the task's explicit instruction)** — both real callers above use the exact same two
functions, added to `dv_harness/memory_vault.py` (the natural shared location — already
Workstream 1's own module):

```python
memory_vault.build_failure_signature(*, protocol=None, pattern=None, symptom=None,
    root_cause_hint=None, uvm_error_count=0, uvm_fatal_count=0, assertion_failure=False,
    simulator_crash=False, terminal_signature=None, lsf_status=None, extra_text=None) -> dict
    # -> {..., "abnormal_termination": bool}

memory_vault.search_related_memory_for_debug(root, cfg, failure_signature, limit=5) -> dict
    # -> {"ok": bool, "failure_signature": {...}, "related_cases": [...], "count": int}
```

Both never raise (best-effort, wrapped). An empty/no-signal `failure_signature`
deliberately returns `related_cases: []` rather than the vault's own "empty query lists
everything" convention — unscoped noise is not useful prior evidence for a specific
failure.

### Phase 13 — Git Integration (`dv_harness/memory_vault.py`, `dv_harness/memory_router.py`)

Workstream 1 already built real, tested, opt-in (`memory.git_enabled`) git integration
(`git init` on first use, repo-local identity, a commit per vault file operation) — this
workstream turned it into the **real commit policy** the spec names, additively:

1. **`commit_message` becomes a real, policy-driven parameter**, not always the adapter's
   own generic default. `FileSystemMarkdownAdapter.create()`/`update()`/`delete()` (and the
   `MemoryProvider` ABC / `ObsidianAdapter` / `HybridMemoryProvider` around them) gained an
   additive `commit_message: Optional[str] = None` parameter — omitting it (every
   pre-existing caller, including `cli.py`'s `memory add` subcommand and every Workstream-1
   test) reproduces the exact prior generic message (`"memory-vault: create {note_id}"`
   etc.) unchanged. `memory_router._maybe_write_vault_note()` (the one real
   policy-aware caller) now builds and passes the spec's exact required format —
   `memory(<protocol>): <short description>` — via new `_build_vault_commit_message()`
   (falls back to `_general` for a record with no real protocol, never fabricating one).
2. **Vault write-through extended to the two remaining named commit-worthy events.**
   `ENGINEERING_MEMORY`/`ORGANIZATIONAL_MEMORY` already wrote through (Workstream 1); this
   workstream added a new `_VAULT_WRITE_THROUGH_DESTINATIONS = {"JOB_MEMORY",
   "PROJECT_MEMORY"}` set, applied in `route_and_store()`'s generic per-tier dispatch
   branch — covering "verified Job result" and "Project Memory update". **`WORKING_MEMORY`
   is deliberately absent** — the spec's own explicit negative ("NOT on every Working
   Memory update") is satisfied *by construction* (no branch reaches it), not by a
   separate runtime check. `JOB_MEMORY` is "verified" in this codebase's own real-evidence
   sense even though `route_memory()` itself never gates it on a `verified` flag the way
   `PROJECT_MEMORY`/`ENGINEERING_MEMORY` do: the only two real writers of a `JOB_MEMORY`
   record in this codebase (`lsf_client.py`'s terminal-reconcile hook, and this
   workstream's new FAILURE_RECOVERY/RE_AUDIT-fail hook) only ever fire from a real,
   already-reconciled LSF/gate fact, never a guess.
   - `memory_vault.build_frontmatter_from_memory_record()`'s destination→`memory_level`
     mapping was a real, previously-latent bug for this extension: it only ever
     distinguished `ENGINEERING_MEMORY` from "everything else is organizational" (correct
     back when only those two destinations ever called it). Fixed with a real
     `_DESTINATION_TO_MEMORY_LEVEL` map covering all four destinations, so a JOB_MEMORY/
     PROJECT_MEMORY note now lands in `06_Agent_Memory/Job`/`Project` (per
     `VAULT_STRUCTURE`), not mislabeled `organizational`.
3. **"Preserve RTL SHA / TB SHA / Knowledge-commit SHA cross-references for
   traceability."** `rtl_sha`/`tb_sha` already existed in the Phase-7 schema (Workstream
   1); **`knowledge_commit_sha` did not** — added as a new `MEMORY_NOTE_OPTIONAL_FIELDS`
   entry. `_commit_vault_change()` now returns the real resulting commit's SHA (`git
   rev-parse HEAD`, never fabricated — `None` when there was nothing to commit or git
   failed), surfaced as `knowledge_commit_sha` in `create()`/`update()`/`delete()`'s result.
   New `memory_router._write_back_knowledge_commit_sha()` then patches the **underlying
   JSON MemoryStore record** (not the vault note itself — the note's content was already
   committed by the time the SHA is known, so writing it back into that same note would
   need a second, circular commit) with the real SHA, for `ENGINEERING_MEMORY`/
   `JOB_MEMORY`/`PROJECT_MEMORY` (not `ORGANIZATIONAL_MEMORY`, which has no local file
   store to patch — see `memory.py`'s `OrganizationalMemoryStore` design). Best-effort,
   never affects the already-completed local/vault write.

Git integration itself stays **opt-in** (`memory.git_enabled` defaults `false`) — this is
Workstream 1's own evidence-driven decision (a real full-suite regression run found
`git_enabled: true` broke 10 pre-existing tests via a Windows `PermissionError` on
`shutil.rmtree()` of a `.git` tree), re-confirmed still correct here rather than silently
reversed: every git-dependent test in this workstream is `pytest.skip`'d when `git` is
absent, following the same precedent.

### Phase 14 — Session Save/Restore (`dv_harness/session_snapshot.py`)

Read `session_snapshot.py` in full (365 lines) and
`.work/session-snapshot-extension-implementation-report.md` before writing anything, per
the task's instruction — extended it, did not rebuild it. `SESSION_FILES`/`SESSION_DIRS`
(state.json, `react/`, `lsf/`, etc.) already covered every raw file a resume needs; what
was missing was a lightweight, save-time **summary** of them in `session_manifest.json`
itself, so a restored session can answer the four required questions by reading the
manifest, without needing to know `react.py`'s/`lsf_client.py`'s own private directory
layouts.

New fields on `save_session()`'s manifest, each a **real read of an already-real file**,
never a new write path:
- `current_project`: `state.get("project")` (already-real state field).
- `current_job`: new `_collect_current_job_reference()` — a lightweight reference
  (job_id/pattern/lsf_status/sim_status/uvm_error_count/uvm_fatal_count) to the
  most-recently-changed record under `.dv-harness/lsf/jobs/*.json` (already copied
  wholesale by `SESSION_DIRS`' `lsf` entry — this only indexes it). `None`, honestly, when
  no job has ever been recorded.
- `current_hypothesis`/`current_evidence`/`current_confidence`/`pending_action`: new
  `_read_latest_react_iteration()` — reads the highest-numbered `iteration_NNN.json` under
  `.dv-harness/react/<current_stage>/`, the **exact same file** `react.ReactRecorder.
  record()` already writes once per stage attempt (`reason_summary`/`evidence`/
  `confidence`/`next_action` — real hypothesis/evidence/confidence/next-action content,
  not new fields invented for this task).
- `related_memory`: new `_collect_related_memory_references()` — **REFERENCES ONLY**
  (memory_id/level/title/root_cause/confidence), reusing the exact same
  `MemoryRetriever.search()` engine.py's own `run_stage()` already calls for its
  `relevant_memory` prompt context. The durable Memory tier itself stays deliberately
  excluded from the snapshot (unchanged design intent from the module's original
  docstring) — this is an index of *which* records were relevant at save time, not a copy
  of their content.

New `describe_resume_point(manifest) -> str`: a plain-language answer to "where we stopped
/ what was proven / what remains unknown / what action should execute next", built purely
from fields the manifest already carries (a formatting convenience over real data, not a
re-analysis). Wired into `restore_session()`'s return value as `resume_summary`, degrading
safely (an honest fallback line, never a `KeyError`) for a snapshot saved before this
feature existed.

## Coordination with concurrent workstreams

This session found Workstream 2 (CLI/skills/dedup/security: `memory_security.py`,
`memory_dedup.py`, `memory_doctor.py`, `docs/MEMORY_*.md`, a new CLAUDE.md "Engineering
Memory Policy" section, `cli.py`'s `memory` subcommands including `memory promote`) and
Workstream 4 (`.claude/agents/memory-agent.md`, dispatched by `debug-agent`/
`regression-agent` for the same before/after debug-cycle shape) **already landed on disk**
mid-session — `memory_vault.py` changed under me between reads (Phase 19 redaction wired
into `create()`/`update()`). Handled by re-reading the live file before each edit rather
than reverting/ignoring the concurrent changes (per the harness's own file-watch guidance).

Relationship to Workstream 4's Memory Agent: `docs/MEMORY_AGENT.md` describes an
LLM-dispatched agent (`debug-agent` calls it via the `Agent` tool, before forming a
hypothesis and after a verified fix) that searches via `python -m dv_harness.memory_cli`
subcommands — a different, higher-level (LLM-orchestrated) mechanism from this
workstream's `search_related_memory_for_debug()` (a deterministic Python call inside
`run_stage()`/the LSF reconcile hook, guaranteed to run on every real attempt regardless of
which agent is dispatched). The two are complementary, not conflicting: this workstream's
wiring guarantees the stage prompt/job record already carries vault-searched prior
evidence before any agent starts reasoning; the Memory Agent is available for a deeper,
on-request search. `memory_cli.py` was not extended with a new subcommand for
`search_related_memory_for_debug()` (out of this workstream's stated scope, and not needed
by either of its two real callers) — a natural, low-risk follow-up for whichever workstream
next touches `memory_cli.py`/`memory-agent.md`, noted here rather than done silently.

`_re_audit_pass_text()` in `dv_harness_tests/test_inference_engine_wiring.py` gained one
new optional keyword arg (`target_testcase_id`, defaulting to the prior behavior) rather
than a new duplicate fixture, to test the new `test`/`result` fields against the same real
11-gate RE_AUDIT PASS fixture Workstream-1-era tests already built and still use unmodified.

## Files touched

- **New**: `dv_harness_tests/test_debug_flow_memory.py` (18 tests, described above)
- **Modified**:
  - `dv_harness/memory_vault.py` — `commit_message`/`knowledge_commit_sha` on
    create/update/delete (Phase 13), `_DESTINATION_TO_MEMORY_LEVEL` fix, new
    `MEMORY_NOTE_OPTIONAL_FIELDS` entry, `build_failure_signature()`/
    `search_related_memory_for_debug()` (Phase 10/11).
  - `dv_harness/memory_router.py` — `_VAULT_WRITE_THROUGH_DESTINATIONS`, JOB_MEMORY/
    PROJECT_MEMORY vault write-through, `_build_vault_commit_message()`,
    `_write_back_knowledge_commit_sha()` (Phase 13).
  - `dv_harness/engine.py` — step 1b-3 (vault prior-evidence search), step 3c (FAIL/PARTIAL
    Job-Memory-only hook), `_root_cause_confidence_inputs()` (factored out, reused),
    `_promote_verified_fix_knowledge()` extended (git_sha/rtl_sha/tb_sha/test/result +
    `promote_to_organizational()` trigger), new `_record_debug_attempt_job_memory()`
    (Phase 10).
  - `dv_harness/prompts.py` — `build_stage_prompt(..., vault_related_cases=...)`, purely
    additive (Phase 10).
  - `dv_harness/lsf_client.py` — `_write_job_tier_memory_on_terminal_reconcile()` extended
    with failure-signature capture + prior-knowledge search on a real failure signal
    (Phase 11).
  - `dv_harness/session_snapshot.py` — `_read_latest_react_iteration()`,
    `_collect_current_job_reference()`, `_collect_related_memory_references()`,
    `describe_resume_point()`; `save_session()`/`restore_session()` wired to use them
    (Phase 14).
  - `dv_harness_tests/test_memory_tier_completion.py` — one pre-existing assertion updated
    (pops the new, additive `vault_write` key on a JOB_MEMORY route_and_store() result,
    same precedent Workstream 1 already established for ORGANIZATIONAL_MEMORY).
  - `dv_harness_tests/test_inference_engine_wiring.py` — `_re_audit_pass_text()` gained one
    optional kwarg; 5 new tests (git_sha/rtl_sha/tb_sha/test/result fields, the fallback
    path, the real promotion-evaluation trigger, and its exception-safety).
  - `dv_harness_tests/test_session_and_info.py` — 6 new tests (Phase 14 fields, honest
    absence with no debug activity, `resume_summary`, explicit save→restore round-trip,
    `describe_resume_point()`'s backward-compat degrade, `_collect_current_job_reference()`
    recency selection).
  - `dv_harness_tests/test_stats_snapshot.py` — one pre-existing hardcoded agent-count
    assertion updated 19→20. **Not caused by this workstream**: Workstream 4 added a new
    real agent file (`.claude/agents/memory-agent.md`, commit `17ebcaf`) during this same
    session, which this test's hardcoded expectation had not been updated for. Found by
    this workstream's own full-suite regression run (the task's own instruction to "re-run
    the broader existing test suite... to confirm nothing regressed"); fixed here as a
    trivial, same-pattern one-line update (the test's own docstring already documents this
    exact "N -> N+1 profiles" update pattern from a prior agent addition) rather than left
    broken or silently worked around.
  - `CLAUDE.md` — one new paragraph under the existing "Engineering Memory Policy" section
    (added by Workstream 2), naming this workstream's real functions/policy for future
    sessions.
  - `docs/MEMORY_OPERATIONS.md` — extended the existing "Git-backed vault history" section
    with the real commit-message-policy/knowledge_commit_sha detail this workstream added.

## Test results

- **New tests**: `test_debug_flow_memory.py` (18), plus additions to
  `test_inference_engine_wiring.py` (+5, now 12 total in that file),
  `test_session_and_info.py` (+6, now 34 total in that file), and
  `test_regression_reporter.py` (+2, now 29 total in that file) = **31 new tests, all
  passing**.
- **Focused re-runs during development** (all passing, individually confirmed before the
  final full-suite run below): `test_memory_vault.py` + `test_memory_tier_completion.py`
  (60), `test_engine_gates_and_routing.py` + `test_inference_engine_wiring.py` +
  `test_qualified_conclusion.py` + `test_react_working_memory_bridge.py` +
  `test_self_tuning.py` + `test_self_tuning_proposal_gate.py` +
  `test_deep_rca_evidence_gate.py` + `test_fix_risk_approval_gate.py` (356),
  `test_session_and_info.py` (34), `test_lsf_client.py` + `test_regression_reporter.py` +
  `test_debug_flow_memory.py` (124), `test_stats_snapshot.py` (5).
- **Full repository test suite** (`pytest` at repo root, real regression run, twice):
  - **First run** (before the two fixes below): **2008 passed, 1 failed** —
    `test_stats_snapshot.py::test_agent_count_matches_real_glob` (`assert 20 == 19`).
    Independently confirmed **not caused by this workstream**: `.claude/agents/` really
    does contain 20 real agent profiles now (`git log` shows `memory-agent.md` added by
    Workstream 4's commit `17ebcaf`), and this test's own hardcoded expectation was never
    updated for it. Fixed (19→20, see "Files touched").
  - **Second, final run** (after the `test_stats_snapshot.py` fix and the
    `_upsert_job_tier_memory_record`/`is_failure` fix below): **2010 passed, 0 failed**
    (1081.19s / 18m01s, exit code 0) — a fully clean regression.
  - A separate, real gap was found and fixed by this workstream's OWN full-suite run
    itself (not a pre-existing failure, but a correctness gap this run's own new coverage
    exposed during development, already fixed before the two runs above): the Phase 11
    `is_failure` derivation didn't account for a real `sim_status=="FAIL"` epilogue verdict
    with zero UVM counts, and the Job-tier memory write only ever fired once per job at the
    coarse bjobs-only reconcile point — see Phase 11's "A real timing gap found and closed"
    above.

## Explicitly out of scope for this workstream

- `.claude/agents/memory-agent.md` (Phase 17) and its docs — already built by Workstream 4
  during this session; not modified here (see "Coordination" above).
- `.claude/skills/CORE/*` mechanics extension (Phase 16) — Workstream 2's scope; this
  workstream's CLAUDE.md addition supplements, does not replace, its existing "Engineering
  Memory Policy" section.
- `memory_cli.py` subcommand surfacing of `search_related_memory_for_debug()` — noted as a
  natural follow-up above, not needed by either real caller this workstream built.

## Module/function names for reference

- `dv_harness.memory_vault`: `build_failure_signature()`, `search_related_memory_for_debug()`,
  `_DESTINATION_TO_MEMORY_LEVEL`, `commit_message`/`knowledge_commit_sha` on
  `create()`/`update()`/`delete()`.
- `dv_harness.memory_router`: `_VAULT_WRITE_THROUGH_DESTINATIONS`,
  `_build_vault_commit_message()`, `_write_back_knowledge_commit_sha()`.
- `dv_harness.engine.DVHarness`: `_root_cause_confidence_inputs()`,
  `_record_debug_attempt_job_memory()`, extended `_promote_verified_fix_knowledge()`.
- `dv_harness.session_snapshot`: `_read_latest_react_iteration()`,
  `_collect_current_job_reference()`, `_collect_related_memory_references()`,
  `describe_resume_point()`.
- `dv_harness.lsf_client`: `_upsert_job_tier_memory_record()` (factored out of
  `_write_job_tier_memory_on_terminal_reconcile()`, second real caller in
  `regression_reporter.run_reconciliation_cycle()`).
