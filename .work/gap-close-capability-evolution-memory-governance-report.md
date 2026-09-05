# Gap-close: 5-Level Memory governance for research/capability-evolution records + the Three Autonomy Levels

**Status: DONE.** Commit `ed7a546` on `gap-close/env-manifest-fact-sources`.
Scope was Stage 0 + Stage 1 only: machinery installed, operated on no real
external document, no capability-evolution change made to production code.

**Test summary**: `444 passed in 344.62s` across the new suite plus the full
memory-router / memory-tier / vault / CLI-memory / research suites; the new
`dv_harness_tests/test_research_memory_governance.py` is 43 of those and passes
standalone in 1.9s.

---

## What changed

Six files, all staged by hand-scoped patch (see "Concurrency handling" below).

| File | Change |
|---|---|
| `dv_harness/memory_router.py` | +269/-2. Research/capability-evolution `kind` branches in the existing `route_memory()` dispatch; the fourth research admission bar on the Engineering and Organizational gates. |
| `dv_harness/autonomy_levels.py` | NEW, 289 lines. Section 61's three levels, and the LEVEL C enforcement index with checkable citations. |
| `dv_harness/capability_evolution.py` | The Three Autonomy Levels narrative as a comment block immediately above the two functions enforcing the LEVEL B→C boundary, plus LEVEL C annotations in their docstrings. |
| `dv_harness/git_governance.py` | +8. LEVEL C annotation on `PROTECTED_BRANCHES` naming which section-61 example it enforces. |
| `dv_harness/self_tuning.py` | +10. LEVEL C annotation in `_compute_protected_removals()`, including the two scope limits that make it PARTIAL rather than ENFORCED. |
| `dv_harness_tests/test_research_memory_governance.py` | NEW, 43 tests. |

### 1. Memory routing (master prompt section 12)

Four research `kind` strings — `research_evidence`, `research_claim`,
`research_hypothesis`, `capability_evolution_candidate` — plus
`architecture_decision` are now **named branches in the existing
`route_memory()` dispatch function**. Not a parallel router, not a sixth tier,
not a new store. They previously reached Working Memory through the function's
final fallthrough, i.e. by default rather than by decision, so nothing recorded
why that tier was right.

Tier defaults: Working by default, Job when the record carries a real `job_id`,
and Project only for a `verified` `architecture_decision` — which is the
**ceiling** for that kind, not a waypoint. `verified: true` deliberately does
nothing on the research kinds: that flag is what unlocks the Engineering tier
for `root_cause`/`verified_fix`/`debug_lesson`, and letting it work here would
merge the exact two things section 12 separates — "the paper says so" and "this
harness verified it".

### 2. The fourth admission bar (sections 71/72)

Engineering and Organizational are unreachable by kind alone. A research-origin
record additionally faces `research_engineering_admission_reasons()` /
`research_organizational_admission_reasons()` **on top of** the three gates
every record already faces — because all three of those are satisfiable from
inside a single freshly-ingested card (the paper's own abstract as `evidence`,
the ingesting agent's own `confidence: HIGH`, the paper's own `lesson`).

Three properties worth naming, each test-covered:

- **Origin is detected by field shape, not by the `kind` string.** The
  laundering path is one edit wide: relabel a ResearchEvidenceCard-shaped
  record's `kind` to `debug_lesson`, set `verified: true`. The card's
  `document_id` / `source_provenance` / `claim_set` survive that relabelling, so
  those are what `research_provenance_signals()` recognizes.
- **Corroboration is re-read off the real store and counted by DISTINCT source
  document.** The same paper cited twice is one occurrence; ids that resolve to
  nothing are not sources. The count is `ORGANIZATIONAL_MIN_CONFIRMATIONS`
  itself (2), not a separate looser research threshold — asserted by a test that
  reads the function's own source, so a future edit cannot quietly fork them.
- **Organizational is an authority check, not an evidence check.** Section 72's
  "Research Agent alone must not promote policy into Organizational Memory" is
  enforced as a live `ControlPlane` approval lookup. A record that merely
  *contains* an approval-shaped dict is a record that wrote its own approval, and
  is refused with `RESEARCH_HUMAN_APPROVAL_NOT_ON_RECORD`.

The bar is proven **clearable** as well as strict (two distinct sources plus
either a gate-validated `verification` block or a complete four-field
`internal_benchmark`) — a gate nothing can ever pass is a gate somebody deletes.

### 3. Stage 1 Acceptance Test H

`test_acceptance_h_fresh_card_cannot_reach_organizational_memory`, driven
through the real router end to end. The record is deliberately given every
advantage a determined caller could give it: a real card skeleton built by
`doc_extraction.build_research_evidence_card_skeleton()` from a real file,
relabelled to the `methodology` kind that `route_memory()` genuinely does send
to `ORGANIZATIONAL_MEMORY`, with `verified: true`, `confidence: HIGH`, and a
`verification` block in a shape `_verification_is_gate_validated()` really
accepts. It lands in Working Memory carrying
`RESEARCH_ORIGIN_REQUIRES_HUMAN_APPROVAL`, and both durable tiers are empty.

Three companion tests extend it: the rejection names the missing *authority*
rather than an evidence deficiency, a self-written approval block is refused
while a real `ControlPlane.approve()` clears it, and the property holds for
every research kind rather than just the one card shape.

---

## LEVEL C: items with NO real existing enforcement today

**Five of section 61's nine examples have no item-specific enforcement.** They
are flagged here and NOT closed in this pass, per instruction:

1. **changing default production workflow** — `.dv-harness/graph/main_graph.json` and `gates.STAGE_GATES` are guarded by nothing against direct edit. `self_tuning.PROTECTED_REMOVALS` is narrower in both directions: gate membership only (not node/edge topology), and only along the self-tuning override path. `propose_add_override()` has no protected list at all.
2. **changing verification oracle semantics** — the highest-consequence gap in the table. No protected list, checksum or gate covers the *content* of any `tools/verification_flow/*.py` gate script. `PROTECTED_REMOVALS` protects a gate's membership in a stage and says nothing about what that gate decides once it runs, so a gate can keep its protected slot while its verdict logic is rewritten underneath it. This is the mechanism by which a false PASS becomes possible.
3. **changing regression selection policy used for signoff** — `change_impact.select_regression()` and `regression_tiers.py` carry no protected-parameter entry. `self_tuning.PROTECTED_PARAMETERS` does hold two regression entries, but they govern `regression_submission_policy_gate` (waveform default, prior-failure reference) — how a regression is *submitted*, not which tests are *selected* as sufficient for signoff. Adjacent policy, different question; a test asserts the two are not conflated into a false ENFORCED.
4. **changing shared schemas with production impact** — `dv_harness/schemas/*.json` are validated against, never guarded against edit. A loosened `required` list weakens every consumer at once and nothing notices.
5. **changing remote execution/security policy** — the SSH/Remote Transport Intake gate, the `remote_relay.py` invocation prohibition and its single-user amendment are all CLAUDE.md prose. `context_budget.policy.json` is schema-validated on load, which checks a policy is well-formed, never that it was not weakened.

**"NONE" is scoped, not alarmist**: every item is covered at the last mile by
the generic PR gate, because `git_governance.py` keys on the destination branch
and nothing else. NONE means nothing refuses the edit *at the point it is made*
and a human reviewing the PR is the only thing in between.

**Why these were not built in this pass**: a safety mechanism authored by the
same pass that decided it was needed has had no independent review — the exact
failure mode this governance model exists to prevent. They want a separate,
dedicated effort.

### The four with real enforcement (confirmed against the real modules, not assumed)

| Example | Status | Real enforcement |
|---|---|---|
| merging to main | **ENFORCED** | `git_governance.PROTECTED_BRANCHES` + `evaluate_pre_push()` / `evaluate_pre_merge_commit()`. Keys on destination branch alone, so a capability-evolution change is blocked on the same terms as any other agent push. Live (`core.hooksPath = tools/git-hooks`), driven against a real push/merge by `test_git_hooks_e2e.py`. Residual (pre-existing, disclosed in CLAUDE.md): server-side branch protection is not in force because `origin` is empty. |
| changing signoff policy | **PARTIAL** | `self_tuning.PROTECTED_REMOVALS`, computed from the **real** `STAGE_GATES["PROMOTION_READINESS"]`/`["SIGNOFF"]` lists — so a gate added to either stage is protected the moment it is registered. A test iterates every real gate on both stages and asserts `propose_remove_override()` returns False for each. Plus `policy.can_signoff()`. Residual: membership only, self-tuning path only. |
| changing organizational verification policy | **PARTIAL** | `memory_router.promote_to_organizational()` / `organizational_admission_gate()` / `ORGANIZATIONAL_MIN_CONFIRMATIONS`, now including this pass's research authority check. Residual: enforces the policy, does not guard the policy — lowering the constant from 2 to 1 is an ordinary source edit. |
| enabling new autonomous destructive actions | **PARTIAL** | Real registered `PreToolUse` hooks: `.claude/hooks/block-destructive.ps1` (Bash\|PowerShell) and the context-budget guard. Residual: nothing constrains editing the hooks or the `settings.json` that registers them, and both fail **open** when Python is unavailable (pre-existing, disclosed). |

The claims above are not prose. Each row's `cites` names real importable
symbols and `assert_level_c_citations_resolve()` raises if one is renamed or
deleted, so a stale claim becomes a test failure instead of a confident, false
table. `LEVEL_C_UNENFORCED` is *derived* from the table, and a test pins the
exact five — quietly shrinking the list fails, and honestly closing one is a
deliberate edit to both the table and the test.

---

## One design decision worth reviewing

The LEVEL C table lives in a **new module** (`dv_harness/autonomy_levels.py`)
rather than in `capability_evolution.py` beside the narrative. This was forced
by a real existing guard, and the alternative was worse.

`test_capability_evolution_research_architect.py`'s Acceptance Test E scans
`capability_evolution.py`'s non-comment source for verdict vocabulary
(`"PASS"`, `can_signoff`, `signoff`, …) so that module can never quietly acquire
verification authority. Section 61's own example wording — "changing signoff
policy", "changing regression selection policy used for signoff" — contains
exactly that vocabulary. **My first attempt put the table there and broke that
test.** Weakening the guard to accommodate a docstring would have traded a real,
enforced safety property for the convenience of co-locating prose with it.

`autonomy_levels.py` is also the more honest home: LEVEL C enforcement is spread
across `git_governance.py`, `self_tuning.py`, `gates.py`, `policy.py` and
`memory_router.py`, and belongs to none of them individually. The requirement
that the levels be documented *at the enforcement point* is met by real comments
at three real points — the narrative comment block above
`assert_human_approval()` / `assert_no_production_write_authorized()`, the
annotation on `git_governance.PROTECTED_BRANCHES`, and the annotation in
`self_tuning._compute_protected_removals()` — each asserted by a test.
A further test pins the placement decision so a later edit does not "simplify"
by moving the table back and relaxing Acceptance Test E.

---

## Concurrency handling

`memory_router.py` carried **two** uncommitted workstreams. The research work
was in-flight from an earlier pass of this same scope; hunks 1 and 9 of its diff
were a different concurrent effort (the
`memory.find_confirming_engineering_match` refactor, paired with uncommitted
`memory.py` and `engine.py` changes and the untracked
`test_engineering_confirmation_accumulation.py`).

Only my hunks were committed. Method: split the diff, reverse-apply the two
concurrent hunks out of the working file, verify the result stands alone
(`121 passed` against exactly the staged content, with the private
`_find_confirming_engineering_match` correctly restored), stage the six files by
explicit path, commit, then forward-apply the concurrent patch to restore the
working tree. The committed `memory_router.py` delta is purely additive
(+269/-2). No broad `git add` was used, and `memory.py`, `engine.py`,
`stage_profile_report.py` and `CLAUDE.md` were left untouched.

**CLAUDE.md was deliberately not edited.** The Stage 0 audit flagged it as
lacking any record of the research assets — that gap is real, but it is a
shared file several concurrent workflows are touching this session, and it is
outside this task's stated scope.

## Honest limits

- **Nothing was promoted to Organizational Memory**, and the new code makes that
  structurally harder rather than merely avoiding it.
- **This has been run against no real external paper.** Acceptance Test H uses a
  real card skeleton built from a real file by the real `doc_extraction` path,
  which is the correct Stage 1 bar — it is not evidence that ingestion works on
  a real conference PDF.
- **One flaky test, not a regression**:
  `test_memory_tier_integrity_and_admission.py::test_concurrent_processes_writing_memory_never_lose_each_others_index_rows`
  hit a Windows `PermissionError` on an atomic index rename during one combined
  run. It passed in the 444-test run and passes in isolation (`1 passed in
  2.57s`). It is a multiprocessing rename-contention test, plausibly aggravated
  by other workflows active in this repo; my commit does not touch memory index
  writing.
- **The five unenforced LEVEL C items remain open.** Naming them is the
  deliverable here; closing them is not.
