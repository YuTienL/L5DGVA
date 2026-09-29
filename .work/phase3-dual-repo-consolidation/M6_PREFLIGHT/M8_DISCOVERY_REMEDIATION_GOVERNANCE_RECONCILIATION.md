# M8 Discovery/Remediation Governance Reconciliation

Analysis + governance reconciliation only, per explicit instruction. No
production code touched. M7 not reopened. Reference USB not consumed. M8
implementation not started. No new governance framework created --
everything below maps the proposed P7/P8 semantics onto REAL, already-
existing, already-used mechanisms, verified against the real repository
state, not assumed.

## Method

Compared the proposal against six real, currently-committed artifacts:

1. `L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv` (`M6_PREFLIGHT/`) -- real
   schema: `GAP_ID,TITLE,RE_VERIFY_ITEM,SCOPE,DISPOSITION,PRODUCER,
   OUTPUT,CONSUMER,PRODUCTION_ENTRY_PATH,ROOT_CAUSE,FIX,TEST_REF,STATUS`.
   Real `DISPOSITION` vocabulary in use today (6 values, re-parsed via
   `csv.DictReader`, not eyeballed): `FIXED`,
   `FIX_NOW_CORRECTNESS_BLOCKER`, `FIX_NOW_CURRENT_SCOPE`,
   `NOT_APPLICABLE_WITH_EVIDENCE`, `REGISTER_AND_DEFER_WITH_OWNER`,
   `SUPERSEDED_WITH_EVIDENCE`. 19 real rows (GAP-V2-001..019), each with a
   real `STATUS` narrative (`CLOSED`, `DEFERRED (owner: ...)`,
   `FIXED_AND_VERIFIED_BY_AUTHOR (...)`, `OPEN (owner: ...)`) -- zero
   rows with no owner/disposition at all.
2. `MASTER_WAVE_OWNERSHIP_MATRIX.csv` -- real schema: `CAPABILITY_ID,
   CAPABILITY_NAME,PRIMARY_OWNER_WAVE,SECONDARY_DEPENDENCY,PRIORITY,
   BLOCKER_TYPE`.
3. `MASTER_CAPABILITY_STATUS_MATRIX.csv` -- real schema (23 columns,
   re-parsed): `CAPABILITY_ID,DOMAIN,CAPABILITY_NAME,SOURCE_ORIGINS,
   STRONGEST_SOURCE_STATE,CANONICAL_STATE,IMPLEMENTED,WIRED,TRIGGERED,
   CONSUMED,OBSERVED,TESTED,PRESERVED,SUPERSEDED,ENHANCED,BLOCKER,
   PRIMARY_OWNER_WAVE,SECONDARY_DEPENDENCY,PRIORITY,EVIDENCE_REFS,
   TEST_REFS,ARTICLE0_DIMENSION,NOTES`.
4. `dv_harness/question_queue.py`'s real Tier-2/Tier-3 model
   (`classify_tier()`, `DOMAIN_OWNER_ROUTING`, `context={"affects_pass_
   fail_verdict": True}` forcing Tier-3/`HUMAN_DECISION_REQUIRED`,
   Tier-2 auto-resolving to `ASSUMED`) -- the real, already-operating
   Human Authority disposition mechanism.
5. `M6_PREFLIGHT/M7_IMPLEMENTATION_COHORT_PLAN.md` -- a real, already-
   used 7-cohort, dependency-ordered implementation plan (`Cohort N:
   <name>`, `**Depends on**: Cohort M`), with a real text dependency
   graph.
6. `M6_PREFLIGHT/M7_FINAL_CONVERGENCE_AND_CLOSURE_REPORT.md` -- this
   session's own real, already-executed 8-category closure taxonomy:
   `CURRENT_SCOPE_CORRECTNESS_BLOCKER`, `CURRENT_SCOPE_SECURITY_BLOCKER`,
   `HUMAN_AUTHORITY_ITEM`, `HOST_DEPENDENT_LIMITATION`,
   `PRE_EXISTING_OWNED_GAP`, `POST_M7_HARDENING`, `M8_CAPABILITY`,
   `CLOSED` -- built and applied to close M7 two tasks before this one,
   independently of the current P7/P8 proposal, and already structurally
   near-identical to it.

## Headline finding

**The proposed P7/P8 semantics are not new governance -- they are a
formal restatement of the discipline this program has already been
running under for the entire M7 cycle**, evidenced by: every M7
dispatch's own explicit "Do not implement X, report only" scoping; every
`MASTER_PROGRAM_STATUS.md` wave-transition entry's own "STOP. Naming X as
the next gate is reporting, not starting it" pattern (verbatim, repeated
at every single wave boundary from M4.5 through M7); the Gap Register's
own zero-rows-without-a-disposition track record; and this session's own
M7 closure report independently arriving at an 8-category taxonomy
functionally equivalent to the proposed 9-category P8 model, before this
reconciliation was ever requested.

```
DISCOVERY_REMEDIATION_SEPARATION = ADOPT
NO_DISCOVERED_GAP_MAY_DISAPPEAR   = ADOPT
```

Both ADOPT, not ADAPT: no real conflict or gap was found between the
proposal and existing governance requiring the proposal itself to change
-- only naming/documentation conventions are needed (below), never a
schema or code change.

## Gap disposition model -- mapped against real existing terminology

| Proposed (P8) | Existing mechanism | Verdict |
|---|---|---|
| `CURRENT_MILESTONE_BLOCKER` | Gap Register `DISPOSITION=FIX_NOW_CORRECTNESS_BLOCKER`; M7 closure taxonomy `CURRENT_SCOPE_CORRECTNESS_BLOCKER` | `ALREADY_SUPPORTED` (exact existing terms, direct match) |
| `CURRENT_MILESTONE_SCOPE` | Gap Register `DISPOSITION=FIX_NOW_CURRENT_SCOPE` | `ALREADY_SUPPORTED` |
| `COHORT_HARDENING` | No exact existing label, but the real Cohort model (`M7_IMPLEMENTATION_COHORT_PLAN.md`'s own `Cohort N: <name>` + `Depends on:` shape) already supports an arbitrary named, ordered, dependency-linked cohort -- a "Cohort H (Hardening/Cleanup)" is a NAMING CONVENTION within that existing shape, not a new mechanism | `NEEDS_SMALL_GOVERNANCE_EXTENSION` (a documented naming convention only -- see below) |
| `POST_MILESTONE_HARDENING` | This session's own `POST_M7_HARDENING` (used live, 2 tasks ago, to classify the `CURRENT_SESSION_EXECUTOR` activation mechanism and REVIEW-002's CG2-3/CG2-4 findings); Gap Register `REGISTER_AND_DEFER_WITH_OWNER` + `STATUS=DEFERRED (owner: ...)` | `ALREADY_SUPPORTED` (direct precedent, same session) |
| `PRE_EXISTING_OWNED_GAP` | This session's own exact term (GAP-V2-014, `test_bounded_self_healing.py` gap, `Q-ENV-7B9230FF`, all classified this way in the M7 closure report) | `ALREADY_SUPPORTED` (verbatim term already in use) |
| `HOST_DEPENDENT_LIMITATION` | This session's own exact term (`PROCESS_INDEPENDENT_AUTONOMY=PARTIAL`, `CLAUDE_DETACHED_WORKER` blocked) | `ALREADY_SUPPORTED` (verbatim term already in use) |
| `HUMAN_AUTHORITY_ITEM` | This session's own exact term; the real Question Queue's Tier-3 `HUMAN_DECISION_REQUIRED` mechanism (`Q-ENV-57D420FA`, `context={"affects_pass_fail_verdict": True}`) | `ALREADY_SUPPORTED` (both the label and the real enforcing code exist) |
| `FUTURE_MILESTONE_CAPABILITY` | `MASTER_WAVE_OWNERSHIP_MATRIX.csv`'s own `PRIMARY_OWNER_WAVE` field (a gap/capability assigned `PRIMARY_OWNER_WAVE=M9` etc. already IS this) | `ALREADY_SUPPORTED` (existing schema field, no change needed) |
| `OUT_OF_SCOPE` | No exact existing `DISPOSITION` value (`NOT_APPLICABLE_WITH_EVIDENCE` means something different -- "not actually a defect", not "real defect, not this program's to own") | `NEEDS_SMALL_GOVERNANCE_EXTENSION` (a documented convention: reuse `REGISTER_AND_DEFER_WITH_OWNER` with the owner explicitly named as outside the current program's ownership, rather than a new `DISPOSITION` enum value -- see below) |

`ALREADY_SUPPORTED = 7 of 9`. `NEEDS_SMALL_GOVERNANCE_EXTENSION = 2 of 9`
(`COHORT_HARDENING`, `OUT_OF_SCOPE`), both resolved by a naming/
documentation convention, neither by a schema or code change.
`CONFLICTS_WITH_EXISTING_CONTRACT = 0`. `REDUNDANT_WITH_EXISTING_
MECHANISM`: the overall "Discovery != Implementation Authorization"
principle itself is redundant with (already fully enforced by) this
program's own standing dispatch discipline -- not a gap needing new
governance, a norm that already governs every dispatch in this session,
simply not previously written down as a named, numbered principle.

## Existing mechanisms reused (no new mechanism built)

- Gap Register schema and `DISPOSITION` vocabulary (`L5DGVA_CURRENT_
  SCOPE_GAP_REGISTER.csv`) -- reused as-is for `GAP_ID`, `CAPABILITY_ID`
  (via `SCOPE`/cross-reference to the Capability Matrix), `SEVERITY` (via
  `DISPOSITION`'s own blocker/current-scope/defer split), `DESCRIPTION`
  (`TITLE`), `ROOT_CAUSE`, `REQUIRED_FIX` (`FIX`), `EXIT_TEST`
  (`TEST_REF`), `STATUS`, `EVIDENCE` (`RE_VERIFY_ITEM`/`PRODUCTION_
  ENTRY_PATH`).
- `MASTER_WAVE_OWNERSHIP_MATRIX.csv`'s `PRIMARY_OWNER_WAVE`/`SECONDARY_
  DEPENDENCY`/`PRIORITY` for `TARGET_PHASE`/`BLOCKS_EXIT_CRITERIA`-
  adjacent fields and cross-capability dependency ordering.
- `MASTER_CAPABILITY_STATUS_MATRIX.csv`'s `BLOCKER`/`PRIORITY` columns
  for `OWNER`/blocking-reason narrative.
- `dv_harness/question_queue.py`'s real Tier-2/Tier-3 classification for
  `HUMAN_AUTHORITY_ITEM` disposition and for deciding whether a gap's own
  disposition itself needs a human decision.
- The real Cohort Plan shape (`M7_IMPLEMENTATION_COHORT_PLAN.md`) for
  `TARGET_COHORT` and for `COHORT_HARDENING`'s own representation.
- This session's own M7 closure taxonomy (`M7_FINAL_CONVERGENCE_AND_
  CLOSURE_REPORT.md`) as the direct precedent for the whole P8 model,
  and for the `M7_EXIT_CRITERIA_TOTAL/PASS/PARTIAL` reporting shape that
  `UNCLASSIFIED_GAPS=0`/`UNOWNED_GAPS=0`/`OPEN_BLOCKING_GAPS=0` (without
  `ALL_GAPS_CLOSED=YES`) directly generalizes.

## Minimum governance changes required (documentation/convention only)

1. **`COHORT_HARDENING` naming convention**: when an M8 implementation
   cohort plan is produced (M8 Preflight, not this task), it MAY reserve
   an optional, explicitly-named `Cohort H (Hardening/Cleanup)` using the
   exact same `Cohort N: <name>` / `**Depends on**: <prior cohorts>`
   shape `M7_IMPLEMENTATION_COHORT_PLAN.md` already uses -- placed after
   the functional cohorts and before final convergence, scoped ONLY to
   well-understood, bounded, low-architectural-risk, M8-related non-
   blocking issues with a clear exit test. No schema change; a
   documented convention for how to NAME and BOUND one specific cohort.
2. **`OUT_OF_SCOPE` convention**: a gap whose real, reproducible defect
   is confirmed but whose owner is genuinely outside the current
   program's mandate is recorded with `DISPOSITION=REGISTER_AND_DEFER_
   WITH_OWNER` and a `STATUS` narrative that explicitly names the owner
   as outside the current program (e.g. `"OUT_OF_SCOPE (owner: <external
   team/repo/program>)"`) -- reusing the existing free-text `STATUS`
   field's own established pattern (`STATUS=DEFERRED (owner: ...)` is
   already exactly this shape for GAP-V2-003/006/007/014), never a new
   `DISPOSITION` enum value.
3. **`PREFLIGHT_BLOCKER` escalation**: formalized as a NAME pointing to
   real, already-built detectors, not a new mechanism --
   `controlled_process_executor.verify_canonical_repository_identity()`'s
   fail-closed `NOT_A_GIT_WORKTREE`/`NO_OWN_DV_HARNESS_STATE`/`REPO_ROOT_
   MISMATCH` reasons (repo-identity corruption), and the standing frozen-
   reference-source re-verification discipline (a changed frozen source
   is exactly this class of finding) already ARE the real, evidence-
   grounded conditions this label should be attached to when they occur
   during a Preflight pass. Documented as a naming convention over
   existing code, not new code.
4. **Preflight closure exit-condition wording** (process documentation
   for the M8 Preflight task itself, to be applied there, not here):
   `M8_SCOPE_FROZEN=YES`, `M8_DEPENDENCIES_MAPPED=YES`, `M8_EXIT_
   CRITERIA_FROZEN=YES`, `UNCLASSIFIED_GAPS=0`, `UNOWNED_GAPS=0`,
   `UNKNOWN_CURRENT_SCOPE_BLOCKERS=0` -- explicitly NOT `ALL_GAPS_
   CLOSED=YES`. This generalizes the exact shape `M7_FINAL_CONVERGENCE_
   AND_CLOSURE_REPORT.md` already used (`M7_EXIT_CRITERIA_TOTAL/PASS/
   PARTIAL`, zero `CURRENT_SCOPE_CORRECTNESS_BLOCKERS`, non-blocking
   categories left open by design) -- a wording convention for the
   Preflight task's own exit report, not a schema or code change.

`PRODUCTION_CODE_CHANGES_REQUIRED = 0`. No `dv_harness/*.py` file, no CSV
schema, and no Question Queue mechanism needs to change for P7/P8 to be
representable.

## Hardening cohort policy

`COHORT_HARDENING` fits the existing cohort model as-is (see item 1
above). It is explicitly bounded: only well-understood, bounded, low-
architectural-risk, M8-related, non-blocking issues with a clear exit
test are eligible; it must never become "fix every open issue before M8
can close" -- consistent with the Gap Register's own already-real
`REGISTER_AND_DEFER_WITH_OWNER` disposition existing specifically to let
a non-blocking gap remain open without blocking closure. Whether M8
Preflight actually reserves this cohort, and what it would contain, is
M8 Preflight's own decision -- not decided or pre-populated by this
reconciliation.

## Post-M8 hardening policy

A short, explicitly time-boxed Post-M8 Hardening Sweep before the later
USB Generation Vertical Slice is representable the same way `POST_M7_
HARDENING` already was for M7 -- a real, disclosed, non-blocking
category that does not require clearing the full backlog. Whether one
actually runs, and its scope, is a decision for after M8 closes -- not
started, not scoped further, by this reconciliation, per instruction.

## USB operational feedback principle

"Deferred != forgotten" is already structurally guaranteed by the Gap
Register's own append-only, every-gap-gets-a-row discipline (zero rows
observed missing a disposition across 19 real entries) -- a deferred
gap's row persists and remains re-derivable; nothing in this program's
real mechanism silently drops a row. Whether a formal RE-PRIORITIZATION
SCORING mechanism (frequency/workflow-disruption/debug-cost/regression-
impact/coverage-signoff-impact/user-operator-friction) exists today was
checked: **no such scoring mechanism was found in the real codebase this
reconciliation searched** (the Gap Register's `PRIORITY` field is a
static P0-P3 label set at discovery time, not a dynamically-recomputed
operational-frequency score). This is recorded as `UNKNOWN_ITEMS` below,
not fixed -- it is explicitly out of scope until real USB Generation
Vertical Slice operational evidence exists to score against, per
instruction ("do not start this work").

## M8 Preflight integration

If M8 Preflight proceeds (a separate, already-authorized task), it
should apply this reconciliation's real, already-supported terminology
directly:

- Every reproduced gap gets a real Gap Register row (`GAP_ID` +
  `DISPOSITION` from the existing 6-value vocabulary, extended only by
  the 2 documented conventions above).
- Every gap's owner/target is the real `PRIMARY_OWNER_WAVE`/`SECONDARY_
  DEPENDENCY` fields, already schema-supported.
- Preflight closure requires `UNCLASSIFIED_GAPS=0`/`UNOWNED_GAPS=0`/
  `OPEN_BLOCKING_GAPS=0`, explicitly not `ALL_GAPS_CLOSED=YES` -- the
  same shape the real M7 closure report already used.
- A defect that prevents trustworthy Preflight itself (corrupted scope,
  broken repo identity, evidence-integrity failure) is named
  `PREFLIGHT_BLOCKER`, pointing at the real existing fail-closed
  detectors named above, and STOPS Preflight for a separately authorized
  remediation dispatch -- never silently fixed inside Preflight.

## Conflicts found

`CONFLICTS_WITH_EXISTING_CONTRACT = 0`. No proposed P7/P8 semantic
contradicts any real existing rule, schema, or disposition value found in
this repository.

## Unknown items

1. No real dynamic re-prioritization SCORING mechanism exists yet for
   the USB-operational-feedback criteria (frequency/disruption/debug-
   cost/regression-impact/coverage-signoff-impact/user-friction) -- the
   Gap Register's `PRIORITY` field is static, set at discovery. Deferred,
   per instruction, until real USB Generation Vertical Slice evidence
   exists.
2. Whether a `Cohort H` should actually be reserved in the real M8
   cohort plan, and what it would contain, is not decided here -- M8
   Preflight's own decision, informed by real M8-owned capability
   evidence this reconciliation does not itself gather.

```
DISCOVERY_REMEDIATION_SEPARATION   = ADOPT
NO_DISCOVERED_GAP_MAY_DISAPPEAR    = ADOPT
CONFLICTS_FOUND                    = 0
PRODUCTION_CODE_CHANGES_REQUIRED   = 0
NEXT_CANONICAL_GATE                = M8_PREFLIGHT
```

**STOP. Governance reconciliation complete and compatible with existing
Canonical governance. M8 implementation not started. M7 not reopened.
Reference USB not consumed. No production source modified. Naming
`M8_PREFLIGHT` as the next gate is reporting, not starting it -- M8
Preflight itself remains a separate, already-authorized-but-not-yet-
resumed task.**
