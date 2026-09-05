# Gap 1 — Cross-loop coupling: auto-file a CapabilityEvolutionCandidate at DISCOVERED

**Status: DONE**

**Test summary:** `dv_harness_tests/test_capability_evolution_auto_discovery.py` 23 passed;
`test_capability_evolution_research_architect.py` + the 4 sibling research suites 225 passed;
full `dv_harness_tests/` suite run to completion (see "Verification" below).

> Filename note: the requested path `.work/gap-close-3loop-gap 1:-report.md` contains a `:`,
> which is not a legal filename character on Windows/NTFS. Written as
> `.work/gap-close-3loop-gap-1-report.md`.

---

## The gap, restated from evidence

Three loops were each individually real and firing:

| loop | real, firing mechanism |
|---|---|
| Verification Closure | `engine.DVHarness.run_stage()` → `STAGE_GATES` → verdict → Job/Engineering memory |
| Project Learning | `memory_router.route_and_store()` / `promote_to_organizational()` tier promotions |
| Capability Evolution | `capability_evolution.py`'s 11-state §70 machine + `ControlPlane` human gate |

The **edge between the first and the third did not exist**. Confirmed by grep:
`router.resolve_intent()` (the research route) has zero callers in `engine.py`, and `engine.py`
carried no reference to `capability_evolution` at all. So the Capability Evolution Loop was
reachable only by a human typing `dv-harness research <doc>`. The same real failure could recur
across independent runs forever, be faithfully recorded in Job Memory every time, and never once
raise a question about the harness's own capability.

## What was built

### 1. `dv_harness/capability_evolution.py` (+456 lines, purely additive, end of file)

New public surface, all reusing existing machinery:

- `repeated_unresolved_failure_patterns(root, *, min_occurrences=2)` — a pure read. Groups Job
  Memory `kind="job_failure"` records by **`evidence_db.signature_key()`** (the same stable hash
  the evidence store already accumulates `occurrence_count` on — deliberately *not* a second
  definition of "the same failure"), read through the shared `MemoryStore.find()`.
- `failure_resolution_claims()` / `resolved_failure_claim_texts()` — the UNRESOLVED half.
- `build_repeated_failure_candidate()` — assembles the candidate through the **existing
  `build_candidate()`**, so the recommendation is DERIVED and the confidence is recomputed
  through the real `inference.score_confidence()`.
- `file_repeated_failure_candidate()` / `file_candidates_for_repeated_failures()` — writes
  through the **existing `persist_candidate()`**, landing on the one
  `capability_evolution_candidates` Blackboard topic and the one Working Memory audit trail.

Threshold, defined concretely and conservatively:

- `REPEAT_FAILURE_MIN_OCCURRENCES = 2` **independent runs**. Independence is the run
  (`job_id`, else `git_sha`) and nothing else — three retries of one stage against one commit are
  ONE observation, matching `ORGANIZATIONAL_MIN_CONFIRMATIONS`'s "not the same run reported
  twice". A record carrying neither identity contributes **zero** independent runs rather than
  one each, so a single bad session cannot manufacture its own capability proposal.
- **UNRESOLVED = no gate-verified fix.** Only `kind="verified_fix"` closes a pattern, because
  `engine._promote_verified_fix_knowledge()` writes it exactly once, on an RE_AUDIT verdict whose
  `fix_effectiveness_gate` AND `fix_regression_non_regression_gate` both cleared. A bare
  `root_cause`/`debug_lesson` record is an explanation, not a closure.
- The join is **exact equality on normalized claim text** (signature `symptom`/`root_cause_hint`
  vs. fix record `root_cause`/`symptoms`), never fuzzy. Both sides really are sourced from the
  same Blackboard `findings.last_report` evidence on the real path.

### 2. `dv_harness/engine.py` (+81 lines)

`DVHarness._file_capability_evolution_candidates_from_repeated_failures(stage)`, called
immediately after `_record_debug_attempt_job_memory()` — the one place in this engine a real
`job_failure` record carrying a real `build_failure_signature()` dict reaches Job Memory. The
coupling therefore reads evidence the closure loop wrote one line earlier, on the real
autonomous path.

Best-effort (mirrors every sibling `_promote_*`/`_record_*` method): a failure records
`CAPABILITY_EVOLUTION_AUTO_DISCOVERY_FAILED` and never turns an already-computed stage result
into a crash. Every outcome — including "no pattern qualified" — is one
`CAPABILITY_EVOLUTION_AUTO_DISCOVERY` event in `.dv-harness/events.jsonl`.

### 3. `CLAUDE.md` (+105 lines)

New section "Cross-Loop Coupling: Repeated Failure -> Auto-Filed Capability Candidate
(2026-09-05)", per the Methodology Consolidation Rule, including the disclosed residual.

### 4. `dv_harness_tests/test_capability_evolution_auto_discovery.py` (new, 23 tests)

---

## The human-approval boundary was not weakened — three independent reasons

Requirement 3 was the load-bearing constraint. Auto-filing reaches **DISCOVERED and no further**,
and each of these alone would be sufficient:

1. `file_repeated_failure_candidate()` never calls `transition()`, and
   `build_repeated_failure_candidate()` raises `IllegalPromotionTransitionError` if the assembled
   candidate is not at DISCOVERED.
2. **Structural, not policy.** The auto-filer performed no repository search and says so — all six
   `existing_*` slots carry `search_conclusive: false` with an honest `search_basis` quoting that
   question's real next-best-action out of the existing `RESEARCH_GAP_ACTION_CATALOG`. So
   `derive_overlap_status()` returns UNKNOWN → `decide_recommendation()` returns UNKNOWN → the
   candidate schema's own `allOf` **pins `current_status` to
   DISCOVERED/EVIDENCE_GATHERING/REJECTED**. Reaching PROPOSED requires six conclusive searches
   only a real `research-architect` pass can produce. `evidence_strength.scale = 2` additionally
   keeps ADD unreachable even then.
3. Every gate above is untouched — not one line changed: `assert_legal_transition()`,
   `assert_human_approval()`'s real `ControlPlane` read, `HumanApprovalRequiredError`,
   `ProductionWriteNotAuthorizedError`, `PRODUCTION_WRITE_AUTHORIZED_STATES`.

Also preserved: a candidate a human has already moved past DISCOVERED is **never dragged back**
(`ALREADY_BEYOND_DISCOVERED`, writes nothing), and unchanged evidence writes nothing
(`ALREADY_ON_FILE_UNCHANGED`) so a retrying stage does not append a duplicate audit record per
attempt. `persist_candidate()`'s WORKING_MEMORY assertion still holds.

Tests that hold this boundary specifically:
`test_an_auto_filed_candidate_cannot_be_advanced_to_PROPOSED`,
`test_skipping_governance_states_is_still_refused`,
`test_the_human_approval_gate_is_untouched_by_an_auto_filed_candidate`,
`test_the_auto_filed_candidate_never_reaches_a_tier_above_working_memory`,
`test_a_candidate_a_human_moved_on_is_never_dragged_back`.

---

## No parallel mechanism

| needed | reused (not rebuilt) |
|---|---|
| failure identity | `evidence_db.signature_key()` |
| failure signature shape | `memory_vault.build_failure_signature()` (read only) |
| evidence enumeration | `memory.MemoryStore.find()` |
| candidate assembly / decision | `capability_evolution.build_candidate()` + `decide_recommendation()` + `inference.score_confidence()` |
| persistence | `capability_evolution.persist_candidate()` → one Blackboard topic + `memory_router.route_and_store()` |
| next-action text | existing `RESEARCH_GAP_ACTION_CATALOG` |
| human surface | existing `dashboard.py` already renders `Blackboard.capability_evolution_counts()` — **no new CLI verb added on purpose** |

---

## Verification

- `python -m pytest dv_harness_tests/test_capability_evolution_auto_discovery.py -q` → **23 passed**
- `python -m pytest dv_harness_tests/test_capability_evolution_research_architect.py
  dv_harness_tests/test_research_memory_governance.py
  dv_harness_tests/test_research_stage1_acceptance_a_g.py
  dv_harness_tests/test_research_intent_routing.py
  dv_harness_tests/test_research_evidence_card.py -q` → **225 passed**
  (this includes Stage-1 Acceptance Test E's source scan of `capability_evolution.py`, which the
  new code had to be written to satisfy — no verdict-vocabulary token in non-comment source)
- Full `dv_harness_tests/` suite run.

The end-to-end test is genuinely end-to-end: two real `DVHarness.run_stage()` calls over the real
shipped `main_graph.json` that do not close, against two different commits, writing two real Job
Memory records through the real `memory_router`, producing a real candidate on the real Blackboard
whose `evidence_refs` are exactly those two real `memory_id`s — with no human involved and no
approval minted. Only the agent adapter is stubbed (it would otherwise dispatch a subprocess).

---

## Disclosed residual (honest scope)

This closes the **automatic-discovery** half of the coupling and only that half. The auto-filed
candidate parks at DISCOVERED with UNKNOWN overlap and UNKNOWN recommendation until a human runs
`dv-harness research` (or an equivalent `research-architect` pass) to perform the six current-L5
searches. Nothing in the engine performs those searches, and `.claude/agents/ROSTER.md` correctly
still records `research-architect` as `NOT_DISPATCHED` — no graph node declares `research-route`.
What changed is that the loop now *raises the question* from real repeated evidence instead of
waiting for a human to notice the pattern.

Nothing was deferred relative to the assigned scope.
