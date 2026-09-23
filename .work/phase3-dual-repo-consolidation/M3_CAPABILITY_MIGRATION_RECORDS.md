# M3 — Capability Migration Records (Cohort 1)

Migration unit is CAPABILITY, not file. Straight `git`-tracked copy per the
`17_CANONICAL_MIGRATION_WAVES.md` M3 definition — no semantic merge, no
`engine.py`/`cli.py` wiring performed (that is M6/M7's job). Each capability
below is a genuinely new, standalone module with no v50 counterpart and no
dependency on an excluded/diverged/unmigrated module.

**Cohort 1 result: 4 of 7 originally-eligible candidates migrated.** 3 were
removed after real test execution surfaced dependency gaps invisible to
static import analysis alone — disclosed in full at the end of this
document, not silently dropped.

**SOURCE_HEAD for all 4 Parent-sourced capabilities below**:
`3e9dd7360f584078ed8f4b04120c9844acabd97b` (Parent's real, fresh-checked
HEAD on `feature/l5-standard-flow` at the moment of this migration — matches
the HEAD recorded at this session's very start, confirming Parent did not
advance during this whole session's work).

---

## CAP-M3-001: `lifecycle.py`

```
CAPABILITY_ID = CAP-M3-001
CAPABILITY_NAME = Standard Flow persistent project lifecycle
CAPABILITY_DOMAIN = project-lifecycle / governance

SOURCE_CLASS = MIGRATE_REQUIRED_DIRECT
SOURCE_REPO = PARENT (D:\DV\Task\DV_Agent_Harness_L5)
SOURCE_BRANCH = feature/l5-standard-flow
SOURCE_HEAD = 3e9dd736 (Parent HEAD at time of this cohort's investigation)
SOURCE_PATH = dv_harness/lifecycle.py
SOURCE_SYMBOLS = LifecycleError, Milestone (Enum), LifecycleStore, _now(), _as_milestone()

SOURCE_OPERATIONALIZATION:
  IMPLEMENTED: yes
  WIRED: not verified as part of this cohort (would require engine.py
         consumer evidence, out of M3 scope -- CLAUDE.md's own Module Index
         entry describes it as "16 milestones, separate from Status,
         transition history + bypass records", consistent with a real,
         used capability on the Parent side, but this cohort does not wire
         it into this canonical repo's own engine.py)
  TRIGGERED / CONSUMED / OBSERVED: not verified in this cohort (M6 territory)
  TESTED: yes (dv_harness_tests/test_lifecycle.py, real Parent test file, ported as-is)

DEPENDENCIES = none (zero internal dv_harness.* imports; stdlib only --
                     json, os, tempfile, datetime, enum, pathlib, typing)

CANONICAL_TARGET_PATH = dv_harness/lifecycle.py
CANONICAL_SYMBOLS = same as SOURCE_SYMBOLS (unmodified copy)

MIGRATION_ACTION = straight copy (file + its own test file), zero adaptation

TESTS = dv_harness_tests/test_lifecycle.py -- real pass, not fabricated
        (part of the 57/57 cohort-wide pass)

PROVENANCE = Parent dv_harness/lifecycle.py, copied verbatim

CANONICAL_OPERATIONALIZATION_AFTER_M3 = IMPLEMENTED, TESTED (module present
  and independently testable; NOT wired into this canonical repo's own
  engine.py/cli.py -- that remains M6/M7's job)

DEFERRED_WIRING = engine.py's own lifecycle integration (M6)
```

## CAP-M3-002: `debug_evidence_behavioral_firewall_gate.py`

```
CAPABILITY_ID = CAP-M3-002
CAPABILITY_NAME = GUI-Escalation + Debug-Behavioral-Firewall pre-declaration checklist gate
CAPABILITY_DOMAIN = debug-governance

SOURCE_CLASS = MIGRATE_REQUIRED_DIRECT
SOURCE_REPO = PARENT
SOURCE_PATH = dv_harness/debug_evidence_behavioral_firewall_gate.py
SOURCE_SYMBOLS = DebugEvidenceChecklist, DebugBehavioralFirewallResult,
                 evaluate_debug_behavioral_firewall()

SOURCE_OPERATIONALIZATION:
  IMPLEMENTED: yes
  WIRED/TRIGGERED/CONSUMED/OBSERVED: not verified in this cohort (M6/M8 territory)
  TESTED: yes (dv_harness_tests/test_debug_evidence_behavioral_firewall_gate.py, ported as-is)

DEPENDENCIES = none (zero internal dv_harness.* imports)

CANONICAL_TARGET_PATH = dv_harness/debug_evidence_behavioral_firewall_gate.py
CANONICAL_SYMBOLS = same as source

MIGRATION_ACTION = straight copy, zero adaptation
TESTS = real pass (part of the 57/57 cohort-wide pass)
PROVENANCE = Parent dv_harness/debug_evidence_behavioral_firewall_gate.py, copied verbatim
CANONICAL_OPERATIONALIZATION_AFTER_M3 = IMPLEMENTED, TESTED, not wired
DEFERRED_WIRING = debug-agent/engine.py consumer wiring (M6/M8)
```

## CAP-M3-003: `l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py`

```
CAPABILITY_ID = CAP-M3-003
CAPABILITY_NAME = V5 SS86 Behavioral Proof of Understanding / plan-contradiction taxonomy
CAPABILITY_DOMAIN = L5DGVA governance-contract audit

SOURCE_CLASS = MIGRATE_REQUIRED_DIRECT
SOURCE_REPO = PARENT
SOURCE_PATH = dv_harness/l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py
SOURCE_SYMBOLS = ContradictionFinding, classify_understanding_plan_contradictions(),
                 UnderstandingPlanContradictionRecord, BehavioralProofVerdict,
                 behavioral_proof_of_understanding_gate()

SOURCE_OPERATIONALIZATION:
  IMPLEMENTED: yes
  WIRED/TRIGGERED/CONSUMED/OBSERVED: not verified in this cohort
  TESTED: yes (ported as-is)

DEPENDENCIES = none (zero internal dv_harness.* imports)

CANONICAL_TARGET_PATH = dv_harness/l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py
CANONICAL_SYMBOLS = same as source

MIGRATION_ACTION = straight copy, zero adaptation
TESTS = real pass (part of the 57/57 cohort-wide pass)
PROVENANCE = Parent, copied verbatim
CANONICAL_OPERATIONALIZATION_AFTER_M3 = IMPLEMENTED, TESTED, not wired
DEFERRED_WIRING = L5DGVA governance-contract audit-program wiring (a later,
  not-yet-scheduled wave -- this module is part of the ~1150-item audit
  program tracked in this session's own memory, out of scope for M3 itself)
```

## CAP-M3-004: `diagnostic_bound_compatibility.py`

```
CAPABILITY_ID = CAP-M3-004
CAPABILITY_NAME = Diagnostic Bound Compatibility (V17 SS471)
CAPABILITY_DOMAIN = debug-governance / diagnostic-evidence

SOURCE_CLASS = MIGRATE_REQUIRED_DIRECT
SOURCE_REPO = PARENT
SOURCE_PATH = dv_harness/diagnostic_bound_compatibility.py
SOURCE_SYMBOLS = classify_diagnostic_bound_compatibility(), _as_number(),
                 _candidate_field(), classify_candidate_bound_compatibility(),
                 filter_bound_compatible_candidates(), recommend_evidence_grounded_bound()

SOURCE_OPERATIONALIZATION:
  IMPLEMENTED: yes
  WIRED/TRIGGERED/CONSUMED/OBSERVED: not verified in this cohort
  TESTED: yes (ported as-is)

DEPENDENCIES = none (zero internal dv_harness.* imports)

CANONICAL_TARGET_PATH = dv_harness/diagnostic_bound_compatibility.py
CANONICAL_SYMBOLS = same as source

MIGRATION_ACTION = straight copy, zero adaptation
TESTS = real pass (part of the 57/57 cohort-wide pass)
PROVENANCE = Parent, copied verbatim
CANONICAL_OPERATIONALIZATION_AFTER_M3 = IMPLEMENTED, TESTED, not wired
DEFERRED_WIRING = debug-agent evidence-bound consumer wiring (M6/M8)
```

---

## Removed from Cohort 1 after real test execution (disclosed, not hidden)

Static import analysis alone said these 3 had zero/small dependency risk;
**running their actual test suites** surfaced real gaps static analysis could
not see. Removed rather than forced through, per "do not force it into M3."

### `ipxact_register_import.py` (b7a worktree, DUT-04)

- **Gap found**: `RegisterFieldIR.__init__()` in this canonical repo's
  `register_excel_extract.py` does not accept an `enum_values` keyword —
  the b7a worktree's `ipxact_register_import.py` was built against a NEWER
  `register_excel_extract.py` (evidently including the b7a-side DUT-10
  field addition) than what exists in v50/this canonical repo.
- **Real evidence**: 4 of its own tests fail with
  `TypeError: RegisterFieldIR.__init__() got an unexpected keyword argument 'enum_values'`.
- **Disposition**: `DEFERRED_TO_M5` (needs the `register_excel_extract.py` +
  DUT-10 3-way reconciliation `17_CANONICAL_MIGRATION_WAVES.md`'s M5 section
  already names: "`register_excel_extract.py` (+ DUT-10 from `b7a`)" —
  confirming this is genuinely M5's job, not M3's, exactly as that document
  predicted when it called this "gated ... on `register_excel_extract.py`'s
  pre-DUT-10 API surface").

### `reference_irq_event_to_service_flow_discovery.py` (Parent)

- **Gap found**: one of its tests
  (`test_real_repos_own_usb_uvm_handoff_reference_is_found`) asserts
  `(repo_root / "USB_UVM_Handoff").is_dir()` — a real dependency on the
  Reference USB Environment being physically present at repo root, which
  is Parent's own layout convention (Parent keeps `USB_UVM_Handoff` loose
  at its root), not this canonical repo's (which only has `reference/USB_UVM_Handoff/`
  under v50's own reference tree, itself gitignored per the M1 findings).
- **Real evidence**: `AssertionError: assert False -- where False = WindowsPath('D:/DV/Task/L5_DGVA/USB_UVM_Handoff').is_dir()`.
- **Disposition**: `DEFERRED` -- not assigned to a numbered wave, because
  the real blocker is `REFERENCE_USB_ENV_CONSUMED` policy itself (must stay
  `NO` through M10; USB Golden Qualification is M11's job), not a module
  dependency a later wave resolves by migrating another file. Revisit at M11.

### `l5dgva_requirement_dependency_closure.py` (Parent)

- **Gap found**: 2 of its tests import `dv_harness.l5dgva_contract_registry`
  (`build_master_registry`) for a real-registry integration check — a
  Parent-only module not in this cohort and not yet migrated.
- **Real evidence**: `ModuleNotFoundError: No module named 'dv_harness.l5dgva_contract_registry'`.
- **Disposition**: `DEFERRED_TO_M4` (pair with `l5dgva_contract_registry.py`'s
  own future migration; the module's own OTHER tests, which don't touch the
  registry, would pass standalone, but per this cohort's "adequate test
  evidence to qualify" bar, the whole file is held rather than partially
  imported with 2 known-red tests).

---

# M3 — Cohort 2: Research/Experience-Learning Capability-Family Preservation Audit

Per the explicit capability-preservation addendum. A dedicated read-only
audit agent traced RESEARCH_INGESTION/DV_PAPER_DISTILLATION/... and
PROJECT_EXPERIENCE_EXTRACTION/USER_INTERACTION_LEARNING/... across Parent,
v50/canonical, and worktrees b7a/b7b/b8 -- modules, agents, skills,
workflows, hooks, graph nodes, tests, CLAUDE.md, Obsidian/memory/KC
integration. Full findings folded into `CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`'s
new capability-family section.

## Headline finding

**Canonical (cloned from v50) already had the overwhelming majority of both
families' real implementation** -- v50 was materially ahead of Parent here,
not behind it, at the time of this audit. Already present and preserved via
the M1 bootstrap (re-verified present in this canonical repo just now, not
assumed): `self_learning_readiness.py`, `memory_lineage.py`,
`memory_quality_policy.py`, `user_correction_trigger.py`,
`coverage_closure_hole_correlation.py`, the confidence-reweight functions in
`confidence_calibration.py`/`capability_evolution.py`,
`coverage_closure_action_utility.py`, `cross_project_mining.py`.

## CAP-M3-005: `coverage_hole_generation_candidate_queue.py`

```
CAPABILITY_ID = CAP-M3-005
CAPABILITY_NAME = Autonomous Hole-Driven Test Generation, DETECTION/RANKING half (V9 SS205)
CAPABILITY_DOMAIN = COVERAGE_CLOSURE_LEARNING

SOURCE_CLASS = MIGRATE_REQUIRED_DIRECT
SOURCE_REPO = PARENT
SOURCE_HEAD = 3e9dd7360f584078ed8f4b04120c9844acabd97b
SOURCE_PATH = dv_harness/coverage_hole_generation_candidate_queue.py
SOURCE_SYMBOLS = SCHEMA_VERSION + the real join logic over
  coverage_analysis.classify_coverage_hole()'s eligibility classification
  and coverage_closure_action_utility.rank_coverage_closure_actions()'s
  ranking. Explicitly, by its own docstring, does NOT generate test
  content -- detection/ranking only.

SOURCE_OPERATIONALIZATION: IMPLEMENTED, TESTED. WIRED/TRIGGERED/CONSUMED/
  OBSERVED not independently re-verified this cohort (would require
  engine.py consumer evidence, out of M3 scope).

DEPENDENCIES = .coverage_analysis (CLASSES_REQUIRING_HUMAN_ESCALATION,
  CLASSES_REQUIRING_MORE_SEEDS, CLASSES_REQUIRING_TEST_REGENERATION,
  classify_coverage_hole) + .coverage_closure_action_utility
  (CoverageClosureRanking, format_ranking_report, rank_coverage_closure_actions)
  -- IMPORTANT CORRECTION recorded here: an earlier pass in this same
  session had deferred this file to M5 on the coarse-grained finding that
  "coverage_analysis.py is diverged" (per 09_TRANSITIVE_DEPENDENCY_CLOSURE.md's
  71-file diverged list). Re-checked at the SPECIFIC-SYMBOL level for this
  cohort: canonical's coverage_analysis.py lacks only 2 unrelated functions
  Parent added (classify_coverage_kind, tag_categories_by_kind) -- all 4
  symbols this file actually imports are present and unchanged. The file-level
  "diverged" flag was too coarse to correctly gate this specific migration;
  the real test run (12/12 pass) is the evidence that resolved it, not the
  file-level flag alone.

CANONICAL_TARGET_PATH = dv_harness/coverage_hole_generation_candidate_queue.py
CANONICAL_SYMBOLS = same as source (unmodified copy)

MIGRATION_ACTION = straight copy, zero adaptation
TESTS = dv_harness_tests/test_coverage_hole_generation_candidate_queue.py -- 12/12 real pass
PROVENANCE = Parent, copied verbatim
CANONICAL_OPERATIONALIZATION_AFTER_M3 = IMPLEMENTED, TESTED, not wired
DEFERRED_WIRING = engine.py consumer wiring (M6)
```

## Investigated, deferred: `coverage_closure_loop_leg_matrix.py`

Zero Python-import dependencies (a clean leaf by that measure), but 8 of
its own real tests fail in canonical: the module self-checks against
`cli.py`'s and CLAUDE.md's literal source text/shape (e.g. confirming a
leg is "wired" by inspecting cli.py's actual dispatch source), and
canonical's `cli.py`/CLAUDE.md structurally diverge from Parent's (M1's
own router-style CLAUDE.md rewrite, different cli.py dispatch shape). A
real, hidden TEXT-SHAPE dependency invisible to import-graph analysis --
caught only by running its actual tests. `DEFERRED_TO_M6/M7` (needs
canonical's own cli.py shape finalized first).

## Confirmed-broken mechanism, common to every tree (a pre-existing defect, not a migration gap)

The `EXPERIENCE_READY` promotion-gate mechanism
(`tools/verification_flow/promotion_chain_audit_gate.py` requires it;
`gates.py`/`prompts.py` never emit it; `memory_router.route_and_store()`
has no caller in the prompt/gate pipeline) is confirmed identically broken
on Parent, v50, AND this canonical repo -- re-verified fresh this cohort,
not merely cited from the pre-existing `_tmp_experience_loop_design.txt`
design note (itself present, byte-identical, on both Parent and v50/canonical).
This is the concrete reason `SIGNOFF_EXPERIENCE_CONSOLIDATION` and the
INTERNAL learning-loop half of `CONTINUOUS_CAPABILITY_EVOLUTION` are
recorded `ABSENT`/`PARTIAL` in the capability matrix -- a real, disclosed,
still-open gap this migration inherits, explicitly assigned to M8, not
silently claimed closed and not fixed here (M3 must not expand into M8
implementation, per the addendum's own explicit instruction).

## Capabilities confirmed absent on every tree (not merely unwired)

`CLARIFICATION_LEARNING` (`QUESTION_AVOIDABLE` or equivalent: zero hits
anywhere), `GENERATION_EXPERIENCE_LEARNING` (no generation-decision ->
build/sim-result -> reusable-experience mechanism found), and a literal
unified `Experience`-shaped record type (zero hits anywhere) are all
confirmed ABSENT by direct evidence, not merely unwired -- these are real
future-build items for M8, not migration omissions.
