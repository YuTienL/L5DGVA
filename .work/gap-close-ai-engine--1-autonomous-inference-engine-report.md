# Gap-close pass: AI mechanism #1 -- Autonomous Inference Engine

**Date**: 2026-09-04
**Scope**: mechanism #1 only.
**Result**: **NO_ACTION_NEEDED on the primary verdict** (independently
re-verified WIRED_AND_FIRING; no engine/inference production code changed) +
**DONE on the audit's named secondary finding** (the three trust-ranking
vocabularies are now explicitly settled and test-held).

Commit: `4084531` -- *inference: settle the three trust-ranking vocabularies as
deliberately distinct*.

---

## 1. Primary verdict re-verified independently: WIRED_AND_FIRING

I re-read the cited evidence rather than trusting the audit's framing. All of it
holds, with line numbers shifted by concurrent edits to `engine.py` (which is
modified-uncommitted by another workstream in this same tree):

| Audit claim | Verified at (current tree) |
|---|---|
| `engine.py` imports the real functions | `dv_harness/engine.py:16` -- `from .inference import score_confidence, identify_gap, next_best_action, promote_if_high_confidence` |
| `_react_step_inference()` exists and calls the real math | `dv_harness/engine.py:1392-1491` -- real `effective_stage_gates()` -> `required`, evidence blocks -> `supplied`, `identify_gap()`, `score_confidence()`, `next_best_action()` |
| It fires for **every** stage attempt, not only RE_AUDIT | called at `dv_harness/engine.py:3568`, inside `run_stage()`'s step-4 block guarded only by `if node is not None:` |
| Its output is what actually persists | the same `self.react.record(...)` call at `engine.py:3589+` passes `confidence` / `next_action` / `gap` / `confidence_detail` straight from `step_inference` |
| `_score_root_cause_confidence()` remains the RE_AUDIT-scoped path | `dv_harness/engine.py:1497+` -- still real, but no longer the only wiring |

Ran the cited non-mocked production-path test myself:

```
python -m pytest dv_harness_tests/test_react_inference_wiring.py -q
-> 11 passed in 110.83s
```

That file drives a real `DVHarness.run_stage()` against the real shipped graph
and real gate subprocesses and asserts against the real persisted
`WM-REACT-*.json` / `iteration_NNN.json`, including that two different evidence
patterns with the same status produce different confidence.

**Nothing in `inference.py`'s functions or `engine.py`'s call sites was
changed.** The mechanism does not need wiring; it is wired.

The audit's disclosed residual is also confirmed and unchanged: every
`.dv-harness/react/**/*.json` on disk here predates the fix, so a reader
inspecting that directory still sees the old flat `"confidence": "MEDIUM"` shape.
Fabricating a fresh production artifact to make it look otherwise would be
writing invented content into this project's real audit trail, so I did not.

## 2. Secondary finding: closed, via option (b), with a real test

The audit's secondary finding is real and I re-confirmed it: grepping
`dv_harness/connectivity.py` and `dv_harness/question_queue.py` for
`inference` / `score_confidence` / `identify_gap` / `next_best_action` returned
**zero matches**, and a repo-wide grep for any written statement of the
distinction (`decision provenance`, `not a confidence score`, `separate
vocabulary`) also returned **zero**. So a future auditor really would find three
confidence-ish mechanisms with nothing on record about whether that is a defect.

### Judgment call: option (b), not option (a)

The audit offered two closures. I took (b) -- document the distinction as a
deliberately separate vocabulary -- and deliberately did **not** take (a)
(re-express the tiers through `score_confidence()`'s counts). Reason, from
reading the actual classifiers:

- `score_confidence()` scores evidence **quantity**: additive counts of
  independent sources, a verified-refs bonus, minus counter-evidence.
- `classify_bind_tier()` and `classify_tier()` rank evidence **kind** /
  decision **authority**, in a strict priority order that no count may reorder.

The mismatch is demonstrable, not stylistic. Mapping one existing bind (T1, the
highest-trust bind tier, "already decided, no re-litigation") onto the formula
gives `1*2 + 2 = 4` -> MEDIUM -- the *same* MEDIUM a T2 structural match gets,
so the strict `T1 > T2` ordering collapses. Counting each matched fingerprint
signal separately to break the tie *inverts* it (T2 -> HIGH, above T1). And on
the question-queue side, Tier 3 is reached from a hard trigger about blast
radius and authority; routing it through a confidence score would let
corroborating evidence downgrade a spec-intent escalation, which is the exact
failure that trigger exists to prevent.

I also adjusted the audit's suggested verification. It proposed a test asserting
"a T3 bind tier feeding into `multi_agent_consensus_count`" -- that would
manufacture a coupling that is semantically wrong, i.e. exactly the defect this
finding is about, inverted. What I wrote instead proves the two orderings
genuinely disagree.

### What changed

- **`dv_harness/inference.py`** -- module-docstring section naming both sibling
  classifiers, why neither is folded in, and the worked numbers above. No
  function body touched (`git diff --numstat` = `33 0`, docstring only).
- **`dv_harness/connectivity.py`** -- the banner `4-tier confidence system
  (Part C)` renamed to `4-tier bind-decision-provenance system (Part C)` with
  the pointer back. Comment/banner only; `classify_bind_tier()` unchanged.
- **`dv_harness/question_queue.py`** -- the tier constants now carry why Tier 3
  is an escalation route rather than a low score.
- **`dv_harness_tests/test_confidence_vocabulary_separation.py`** (new, 178
  lines, 6 tests) -- makes the claim checkable rather than asserted:
  1. `test_bind_tier_ordering_is_not_expressible_as_a_confidence_score` -- real
     calls into both modules showing T1/T2 collapse to the same score, and that
     the generous mapping inverts the order.
  2. `test_question_queue_tier3_is_an_escalation_route_not_a_low_score` -- a
     HIGH-confidence, richly-corroborated spec-intent question stays Tier 3.
  3. `test_no_token_is_shared_between_the_three_vocabularies` -- disjoint as
     sets *and* as substrings (a `HIGH_CONFIDENCE_MATCH` tier would defeat the
     point while passing a set check). Same discipline
     `protocol_capability.capability_status` keeps against `qualification.py`.
  4. `test_neither_tier_classifier_imports_the_inference_engine` -- the audit's
     own verification step, kept as a test.
  5. `test_each_module_carries_the_written_rationale_for_the_separation` -- the
     rationale cannot be silently deleted.
  6. `test_capability_evolution_is_the_counterexample_that_did_reuse_inference`
     -- keeps `capability_evolution.py`'s real reuse (and
     `next_best_action(..., gap_action_catalog=)`) as the contrast case, so this
     is a scoped judgment and not a blanket "never reuse inference.py".

### Comment hygiene (CLAUDE.md Engineering Discipline Rules)

While in `question_queue.py`: its module docstring still called Part A
(`env.manifest.json` + the read-only MCP server) a "SEPARATE, not-yet-built
workstream". Both exist today (`dv_harness/env_manifest.py`,
`dv_harness/mcp/server.py`). Corrected, and the real residual disclosed rather
than glossed: no production caller injects `manifest_lookup` yet -- a repo-wide
grep finds it only in `dv_harness_tests/test_question_queue.py` -- so Tier-1
manifest resolution is available but not in use on the real path.

## 3. Concurrency handling

`git status` was checked before touching anything, and again before committing.
`connectivity.py` was clean when I started and had **233 insertions from another
workstream** (`amba_signal_tokens()`, `match_protocol_fingerprint()`, and
`capture_dut_instance_tree` changes) by the time I staged -- so I used the
hand-scoped patch technique: extracted only my own hunk
(`@@ -119,7 +119,19 @@`) and `git apply --cached` it. `inference.py` and
`question_queue.py` were verified to contain only my hunks.
`engine.py`, `capability_evolution.py`, `memory.py`, `memory_router.py`,
`stage_profile_report.py` are modified by other workstreams and were **not**
staged or committed. The commit contains exactly 4 files.

## 4. Tests

```
python -m pytest \
  dv_harness_tests/test_confidence_vocabulary_separation.py \
  dv_harness_tests/test_react_inference_wiring.py \
  dv_harness_tests/test_inference_engine_wiring.py \
  dv_harness_tests/test_question_queue.py \
  dv_harness_tests/test_connectivity.py \
  dv_harness_tests/test_connectivity_check.py \
  dv_harness_tests/test_capability_evolution_research_architect.py \
  dv_harness_tests/test_source_authority.py \
  dv_harness_tests/test_qualified_conclusion.py -q
-> 372 passed in 219.43s
```

## 5. What is explicitly NOT closed

- The audit's disclosed residual stands: no fresh non-test `DVHarness` session
  has run in this project since the wiring landed, so `.dv-harness/react/`
  still shows only pre-fix records.
- This closure settles the *relationship* between the three mechanisms. It does
  not merge them, and it should not be read as one of them having been made to
  do more than it did.
