# gap-close: research-architect + CapabilityEvolutionCandidate (Stage 1)

**Mode: LOCAL_ANALYSIS** — pure local file work. No server, no VCS, no simulation.

**Scope held**: Stage 1 only (install the machinery). No real external paper or
standard was ingested or analyzed anywhere in this pass (Stage 2 boundary). No
capability-evolution change to production code was implemented (Stage 3
boundary) — the one thing this pass installs is the gate that *refuses* to let
that happen without a human.

---

## What landed

| file | new/changed | what |
|---|---|---|
| `.claude/agents/research-architect.md` | NEW | The Principal Verification Research Architect profile (master prompt §13). Read-only of production (`disallowedTools: Edit, Write`). |
| `dv_harness/schemas/capability_evolution_candidate.schema.json` | NEW | §63's 30 fields verbatim + 5 structural additions, §70's 11-state vocabulary, and three `allOf` rules that make REUSE-before-ADD and UNKNOWN-vs-MISSING schema-enforced rather than reviewed. |
| `dv_harness/capability_evolution.py` | NEW | The decision engine, promotion policy, persistence and Human Approval Gate. |
| `dv_harness/inference.py` | CHANGED | One backward-compatible keyword-only parameter on `next_best_action()`. |
| `dv_harness/blackboard.py` | CHANGED | Three additive wrappers for the `capability_evolution_candidates` topic, following the existing `findings` shape exactly. |
| `dv_harness/memory.py` | CHANGED | `MemoryStore.find()` — the shared query the Stage 0 audit asked for, additive. |
| `.claude/agents/ROSTER.md` | CHANGED | One entry (`NOT_DISPATCHED`, with its required "How this role really runs" note) + count line. |
| `dv_harness_tests/test_capability_evolution_research_architect.py` | NEW | 30 tests, including Stage-1 acceptance tests B/C/D/E. |
| `dv_harness_tests/test_stats_snapshot.py` | CHANGED | Agent count 22 → 23, with the reason appended in the docstring's own running log. |
| `docs/MEMORY_ARCHITECTURE.md`, `docs/MEMORY_SCHEMA.md` | CHANGED | Two `memory.py:<line>` citations that `MemoryStore.find()` shifted. Real drift I caused; `test_doc_citation_check.py` caught it. |

---

## 1. REUSE before EXTEND before ADD — what this pass did NOT build

Checked against the real tree before writing anything, per §2.2/§14:

- **No Research Inference Engine.** §10 forbids one. Confidence, gap and
  next-best-action all route through the existing `dv_harness/inference.py`:
  `score_confidence()` unchanged, `identify_gap()` unchanged (used twice — the
  ten-question check and the §43 precondition list), `next_best_action()` with
  one added keyword.
- **No parallel approval mechanism.** The Human Approval Gate is
  `dv_harness/control_plane.py`'s real `ControlPlane.approve()`/
  `get_approval()`, which `engine.loop()` already re-reads every iteration.
  `stage` is an arbitrary string key, not a `models.Stage` member, so this
  needed **no new graph node** — the Stage 0 audit's finding, confirmed by use.
- **No parallel Research Blackboard** (§11). One new topic on the existing
  `Blackboard`, in the existing `{"items": {id: ...}}` registry shape the
  `findings` topic established, with one real caller as the sync point.
- **No new `kind` in `memory_router.route_memory()`.** `capability_evolution_candidate`
  reaches `WORKING_MEMORY` through that function's existing fallthrough. The
  audit's recommendation was that this needs zero new kind strings; a test
  (`test_no_new_kind_was_added_to_the_memory_router_dispatch_table`) fails if a
  future edit adds one.
- **No new evidence-DB table, no new memory store, no new router, no new
  confidence vocabulary.** The schema borrows `inference.CONFIDENCE_LEVELS`,
  the same borrow `research_evidence_card.schema.json` already makes.
- **No new graph node, no new stage, no new gate script.**

### The one genuinely new module, and why

The Stage 0 audit compared `self_tuning.py` against §63/§70 concretely and
**split** the answer. This pass followed that split rather than re-litigating it:

**Reused from self_tuning's shape, not forked:**
- the persistence primitive underneath `record_adjustment()` — reached here one
  level up, through the real `memory_router.route_and_store()` router;
- the `_index()`-then-`get()`-then-filter enumeration `gate_ids_with_recent_reverts()`,
  `read_recent_adjustment_records()` and `cli.py`'s `_project_self_tuning_records()`
  each hand-roll. This pass would have been the **fourth** copy, so the audit's
  concrete recommendation was taken: it is now `MemoryStore.find()` in
  `memory.py`, the module that owns the index. The three existing copies are
  deliberately left alone — they are the obvious next callers, not a behaviour
  change this pass needs to make;
- the orchestration shape: assemble evidence → decide with a *pure* classifier →
  persist the outcome → never let the LLM's own say-so be the gate.

**Not reused, with the reason:** `classify_proposal()` (binary AUTO_APPLY/DEFER,
rule list keyed to hardcoded gate_id/parameter sets), `apply_proposal()` (every
change is a JSON key write against a `(gate_id[, stage])` pair), and the 4-value
PENDING/APPLIED/REJECTED/REVERTED status. A gate parameter's "experiment" is
just watching the next slice of `gate_history`, and its rollback is always
"restore the prior value". Neither holds once `proposed_action` can be "write a
new skill" — which is exactly why §70 specifies eleven governance states where
self_tuning has two outcomes. Forcing them through would have been a bad reuse.

**Deliberately NOT copied:** `classify_proposal()` trusts an LLM's own
`"confidence": "HIGH"` string verbatim. `recompute_confidence()` re-derives the
level from the stored inputs through the real `score_confidence()` and rejects a
stored level that disagrees — following `engine._score_root_cause_confidence()`'s
precedent, per §10's mandate. Proven by
`test_E_confidence_is_recomputed_never_believed`.

---

## 2. The `inference.py` change: real before/after

```python
# BEFORE
def next_best_action(protocol, gaps, root):

# AFTER
def next_best_action(protocol, gaps, root, *, gap_action_catalog=None):
```

Plus one private helper, `_next_best_action_from_catalog()`. Nothing else in the
file changed — `score_confidence()`, `identify_gap()`, `promote_if_high_confidence()`,
`_load_registry()` and `_find_protocol_entry()` are byte-identical.

**Why it was needed rather than reusing the fallback verbatim.** The Stage 0
audit offered two options: (a) branch the registry lookup, or (b) reuse the
generic fallback branch as-is. Option (b) was rejected on real evidence: that
fallback emits *"no concrete registry item found for gap '<gap>' — inspect
current RTL/spec/VIP evidence directly"*, which is wrong advice for "you have
not yet searched `.claude/agents/ROSTER.md`". Reusing it would have produced
misleading output and let the report claim a reuse that did not work. Only the
two DV-simulation-specific halves are replaced (the registry it reads, the
fallback text); the Gap → Next-Best-Action architecture — the part §10 forbids
re-implementing — is reused unchanged.

**Every existing caller still passes.** All call sites use three positional
arguments, so a keyword-only parameter cannot reach them:

| caller | call |
|---|---|
| `dv_harness/engine.py:1357` (`_react_step_inference`) | `next_best_action(protocol or "_general", gap, self.root)` |
| `dv_harness/engine.py:1467` (`_score_root_cause_confidence`) | `next_best_action(protocol, gap, self.root)` |
| `.work/e2e_usb3_lfps_demo.py:163` | `next_best_action("USB", gaps, REPO_ROOT)` |

`test_next_best_action_registry_path_is_unchanged_without_the_new_parameter`
asserts the three-arg call and the explicit `gap_action_catalog=None` call return
identical results. `test_inference.py` (all pre-existing cases),
`test_inference_engine_wiring.py` and `test_react_inference_wiring.py` were
re-run green.

---

## 3. The decision is code, not the agent's judgement

`decide_recommendation()` is a pure function over the candidate's own recorded
evidence — reads no file, writes no file, calls no model. The agent supplies the
six searches and the four confidence inputs; the code decides. `build_candidate()`
**derives** `recommendation` and `overlap_status` and raises if the caller states
something the evidence does not support (`test_B_add_is_refused_even_when_the_agent_asks_for_it`).

Rule order, and why:

1. **UNKNOWN** — the ten-question check is incomplete, or any of the six
   searches carries `search_conclusive: false`.
2. **KEEP** — a real overlap exists and `exact_gap` is empty. Before REJECT
   because there is nothing to reject.
3. **REJECT** — unrefuted counter-evidence with a LOW *recomputed* confidence.
4. **ENHANCE** — any search returned a match and something is still missing.
   **ADD is unreachable from here at all.**
5. **ADD** — only from a conclusively empty `MISSING`, *and* a stated reason
   ENHANCE is insufficient (§14 Q10), *and* HIGH recomputed confidence, *and*
   `evidence_strength >= 3`. Any one short falls back to EXPERIMENT.

The `search_conclusive` field is what makes Test C real: it separates "searched,
found nothing" from "could not look". A single `false` forces UNKNOWN and makes
ADD unreachable — and the schema independently refuses a `MISSING` claim over an
inconclusive search, so the rule holds even for a candidate this module did not
build.

---

## 4. Persisted state, not conversational output

`persist_candidate()` writes twice, both through existing mechanisms:
- Blackboard topic `capability_evolution_candidates` — the live state machine
  (route_memory already sends live-state kinds like `active_hypothesis` there);
- a Working Memory audit record through the real `memory_router.route_and_store()`.

The routed destination is **asserted** to be `WORKING_MEMORY` and raises
otherwise. That is the global constraint made mechanical: a single design
session is not the "repeated, human-approved" evidence the Engineering or
Organizational tier requires, and this pass must be structurally unable to reach
them even by a later editing accident. The record deliberately carries no
`verified` flag. `test_candidate_audit_record_routes_to_working_memory_only`
additionally asserts the engineering and organizational tiers are empty after a
full run.

---

## 5. Human Approval Gate + §43 stop

`assert_human_approval()` raises `HumanApprovalRequiredError` unless a real
`ControlPlane` approval exists on disk for stage `RESEARCH_CAPABILITY_EVOLUTION`.
`transition(..., "HUMAN_APPROVED")` calls it and copies the real approval record
(reviewer_id / reviewer_confidence / approved_at) into the candidate's own
`status_history`. §70's *"a successful experiment does not automatically imply
HUMAN_APPROVED"* is `test_a_successful_experiment_does_not_imply_human_approved`,
which walks all six governance states, hits the wall, runs a **real**
`ControlPlane.approve()`, and gets through.

`assert_no_production_write_authorized()` is the Stage 2/3 boundary as a callable
check for any future Stage-3 caller: it refuses unless the candidate is
HUMAN_APPROVED/PRODUCTION **and** an approval backs it.

`render_stop_report()` emits §43's seven lines + `STOP.` exactly, and **refuses
to render** while any of the nine preconditions is incomplete, naming what is
missing. Printing "L5.x PROPOSAL COMPLETE" over an incomplete proposal is a false
claim made to the one human about to decide whether to approve it.

---

## 6. Tests

`python -m pytest dv_harness_tests/test_capability_evolution_research_architect.py -q`
→ **30 passed**.

| acceptance test | test name | what it proves |
|---|---|---|
| **B** | `test_B_overlapping_technique_produces_enhance_not_add` | A synthetic card on semantic change-impact — overlapping the real `dv_harness/change_impact.py` `compute_change_impact()`/`select_regression()`, `CORE/verification-change-impact`, `CHANGE_IMPACT`/`REGRESSION_SELECT` — decides **ENHANCE**, `overlap_status: PARTIAL_MATCH`. Backed by `test_B_add_is_reachable_only_from_a_conclusively_empty_search` (PSS, the one genuinely-absent capability the Stage 0 audit found, decides ADD through the same code path) so ENHANCE is not merely hardcoded, and by `test_B_missing_without_a_stated_enhance_reason_falls_back_to_experiment`. |
| **C** | `test_C_insufficient_repository_evidence_produces_unknown_not_missing` | The identical card with one `search_conclusive: false` decides **UNKNOWN**, explicitly not MISSING and not ADD/ENHANCE/KEEP/REJECT. Plus `test_C_unknown_is_reported_with_the_real_next_best_action` (the real `next_best_action()` names what would settle it, and none of it is the DV-simulation fallback) and `test_C_a_missing_claim_over_an_inconclusive_search_does_not_validate` (the schema refuses it independently). |
| **D** | `test_D_running_the_decision_logic_modifies_no_repo_file` | sha256-fingerprints **every file** under `dv_harness/` and `.claude/`, runs decide → build → persist → transition → read-back → approval-status → stop-report, and asserts zero bytes changed. Paired with `test_D_everything_persisted_lands_under_the_project_state_dir`, which proves it really did write (a "nothing changed" test alone would also pass if the module wrote nothing) and that every written path is under `<root>/.dv-harness/`. |
| **E** | `test_E_no_decision_vocabulary_can_be_read_as_a_verification_verdict` | All three vocabularies are disjoint from `models.Status` (which is why `PARTIAL_MATCH` is spelled that way — `PARTIAL` is a real verdict). Plus `test_E_the_module_never_names_a_verification_verdict_at_all` (source-level: no `"PASS"`/`"FAIL"` literal, no `run_gate`, no `evaluate_stage_evidence`, no `can_signoff`, no `QualifiedConclusion`, no `signoff`), `test_E_decision_output_is_always_inside_its_own_closed_vocabulary` (a 768-combination sweep of the real decision function reaching all six outcomes, never anything outside them), and `test_E_confidence_is_recomputed_never_believed`. **No code path resembling an LLM-derived PASS exists in this design; none had to be removed.** |

Existing suites re-run after the changes:

| suite | result |
|---|---|
| `test_inference.py`, `test_inference_engine_wiring.py`, `test_react_inference_wiring.py`, `test_react_loop.py`, `test_react_working_memory_bridge.py` | pass |
| `test_agent_dispatch_map.py`, `test_agent_roster_doc.py`, `test_stats_snapshot.py` | pass |
| `test_self_tuning.py`, `test_self_tuning_cli.py`, `test_self_tuning_proposal_gate.py` | pass |
| `test_research_evidence_card.py` | pass |
| memory suites (`tier_integrity_and_admission`, `dedup`, `search_filters`, `security`, `tier_completion`, `docs_mirror_source`, `doctor`, `review_skill`, `cli_memory_commands`, `write_guard_and_job_evidence`) | pass |
| `test_cli_blackboard.py`, `test_blackboard_subsystem_wiring.py` | pass |
| `test_doc_citation_check.py` | pass after fixing the two line citations `MemoryStore.find()` shifted |

**One disclosed flake, not caused by this change**:
`test_memory_tier_integrity_and_admission.py::test_concurrent_processes_writing_memory_never_lose_each_others_index_rows`
failed once under a 5-suite parallel load with a Windows `PermissionError` on
`index.json.tmp-*` → `index.json` (an OS-level atomic-replace race), then passed
3/3 in isolation. `MemoryStore.find()` only reads, so it cannot affect index
writing.

---

## 7. Honest limits

- **REACHED, not WIRED.** No `engine.py` stage and no graph node dispatches
  `research-architect`; an agent following the profile is the only caller today.
  `ROSTER.md` records it `NOT_DISPATCHED` with the required "How this role really
  runs" note, exactly as `memory-agent` and `audit-change-governance-agent` are.
  Calling it a stage-owning role would be the overstatement this repo's roster
  machinery exists to prevent.
- **Never operated on real content.** Every candidate in the test suite is
  synthetic. The pipeline has ingested nothing and analyzed nothing.
- **The pre-existing 3-vs-4-level confidence ambiguity is untouched.**
  `inference.py`/`gates.py` use 3 levels; `memory_router.py`'s
  `ENGINEERING_ADMISSION_CONFIDENCE_LEVELS` and `memory.py`'s
  `MemoryConsolidator` use a 4th (`CONFIRMED`). This schema reuses the 3-level
  vocabulary rather than resolving or extending the ambiguity — flagged for a
  human, not silently decided here.
- **The review-cycle counter was deliberately not built.** The Stage 0 audit
  noted `read_execution_state`/`increment_execution_counter` generalize by a
  `family` parameter. Stage 1 does not operate the pipeline, so there is nothing
  for a counter to trigger; adding an unused mechanism would violate the same
  principle this pass is enforcing. It is the obvious next step when Stage 2
  begins.
- **`PROPOSED → PROMOTION_CANDIDATE` is the one forward edge that bypasses the
  three experiment states**, and only for a candidate whose own
  `experiment_required` is `False` — enforced in `assert_legal_transition()`,
  not left to the transition table. It shortens nothing on the human-approval
  half of the path. Stated explicitly because §70 says "do not skip governance
  states" and this is the single place that judgement was exercised.
- **`self_tuning.py` still tunes zero real gate behaviour** (no production gate
  script calls `get_param()`). Unchanged by this pass and not this pass's to fix,
  but relevant: the pattern reused above is proven machinery with no live
  parameter surface yet.

---

## Status

**DONE** — Stage 0 + Stage 1 scope only. Stage 2 (analyzing real papers/standards)
and Stage 3 (implementing an approved change) both remain not started, which is
what §57/§82's First-Run Control Instruction requires.
