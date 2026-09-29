# M6 Core Blocker Map

Per-blocker detail for all three `PRIMARY_OWNER_WAVE == M6`, `PRIORITY == P0`
rows. Every field below is sourced from a direct read of real code or a real,
named document — never carried forward from a prior report's summary without
re-checking.

---

## CAP-M6-DISPATCH-001

**Capability name**: `cli.py`/`dashboard.py` dispatch-mechanism decision.

```
CURRENT_STATE = PARTIAL (conflict named and understood, per Master matrix;
  this preflight's own re-investigation narrows exactly what the conflict is)
FOUNDATION_AVAILABLE = PARTIAL -- the underlying execution engines
  (DVHarness.loop(), DVHarness.run_stage()) are real, wired, and
  operational in canonical; a unifying INTAKE_FIRST dispatch wrapper
  around them is NOT available in canonical
FOUNDATION_EVIDENCE:
  - Canonical dv_harness/cli.py's "start" command (elif args.cmd == "start":)
    calls h.loop(args.goal, ...) when --loop is passed, else h.run_stage(args.goal, ...)
    -- confirmed by direct read.
  - Canonical dv_harness/dashboard.py's _start_background_run() constructs a
    raw DVHarness(root) and calls h.loop(goal) or h.run_stage(goal) directly
    -- confirmed by direct read. No UX-policy wrapping, no lifecycle check.
  - Neither canonical entry point calls anything resembling start_lifecycle():
    grep for "start_lifecycle" across dv_harness/ returns zero matches.
  - Canonical's engine.py has no ROUTING_STAGE constant, no
    _intake_first_guard(), no _run_intake_routing_stage() -- confirmed by
    grep, zero matches for all three.
  - Parent's engine.py (read-only reference, D:\DV\Task\DV_Agent_Harness_L5)
    DOES have all of the above: a real DVHarness.start_lifecycle(user_goal,
    *, loop=False, dry_run=False, level=None, protocols=(), advanced=False)
    method (~70 lines) that creates/resumes a dv_harness.lifecycle.py Standard-
    Flow record, then delegates to the same _start_dispatch() -> loop()/
    run_stage() pair canonical already has. A companion _intake_first_guard()
    is called from inside Parent's own run_stage() body (confirmed: line
    ~9231, "intake_first_block = self._intake_first_guard(stage)"), refusing
    any post-INTAKE stage until the lifecycle reaches INTAKE_READY -- UNLESS
    no lifecycle file exists yet, in which case the guard is a structural
    no-op (return None immediately). This makes Parent's gate backward-
    compatible by construction: a project/test that never calls
    start_lifecycle() is completely unaffected by it.
  - Canonical's own dv_harness/lifecycle.py (the Standard-Flow 16-milestone
    model itself) IS real, tested, and present -- CAP-M3-001's own row
    confirms "IMPLEMENTED,TESTED,NOT_WIRED". This preflight independently
    re-confirmed by reading lifecycle.py's own module docstring, which
    already uses the exact same "intake-first gate"/"LIFECYCLE_BYPASS"
    language Parent's start_lifecycle()/CLAUDE.md use -- the vocabulary is
    shared, the wiring is not.
REMAINING_WORK: migrate (or independently design) a unifying dispatch entry
  point + the run_stage()-embedded intake-first guard, IF that pattern is
  adopted -- this is exactly the open question, not yet a scoped task.
DEPENDENCIES: dv_harness/lifecycle.py (present, real); a decision on whether
  intake_routing.py (present, real, but currently zero callers in engine.py/
  cli.py -- confirmed by grep) becomes a mandatory dispatch-time node.
CURRENT_CALLERS: cli.py's "start"/"run-stage" subcommands; dashboard.py's
  POST /api/start (via _start_background_run); ~13000+ dv_harness_tests/
  call sites that construct DVHarness directly and call .loop()/.run_stage().
CURRENT_WIRING: cli.py and dashboard.py each call loop()/run_stage() directly,
  with no shared, canonical unifying entry point and no lifecycle gate.
TARGET_OPERATIONAL_PATH: whichever the human decision below selects -- see
  M6_DISPATCH_001_HUMAN_DECISION.md.
```

---

## CAP-M6-CLARSVC-001

**Capability name**: `ClarificationService` design + build.

```
CURRENT_STATE = BLOCKED (decision made, design/build pending)
FOUNDATION_AVAILABLE = YES -- the architecture decision itself, and both
  real source implementations to compare, exist.
FOUNDATION_EVIDENCE:
  - M-1 Architecture Decision Freeze, D2 (read directly from
    D:\DV\Task\DV_Agent_Harness_L5\.work\phase3-dual-repo-consolidation\
    M_MINUS_1_ARCHITECTURE_DECISIONS.md -- Parent-side, read-only reference;
    this file was never created in canonical and canonical's own git
    history has zero commits for it): "question_queue.py (v50) and
    intake_clarification.py (parent) will not both survive as competing
    semantic authorities... The canonical target defines one service,
    ClarificationService, that preserves the maximum verified capability
    from both real implementations." D2 explicitly says the TARGET SHAPE
    is decided; the real feature-level comparison + build is "real work
    for the wave that builds it," i.e. M6/M7, not an open architecture
    choice.
  - Canonical has dv_harness/question_queue.py (present, but per
    CAP-M5M6-VLEVEL-001's own blocker text, "diverged, M3-excluded" -- an
    N-way merge was deferred, not yet done).
  - Canonical does NOT have intake_clarification.py at all (confirmed:
    find returns nothing) -- it exists only in Parent.
REMAINING_WORK: (1) the question_queue.py N-way merge M3 deferred
  (CAP-M5-ENV-001-adjacent, not itself one of the 3 M6 P0 blockers but a
  real prerequisite); (2) a real feature-level comparison of question_queue.py's
  vs. intake_clarification.py's real, tested capabilities (D2's own explicit
  next step); (3) the ClarificationService build itself, continuing into M7
  per its own SECONDARY_DEPENDENCY.
DEPENDENCIES: CAP-M5M6-VLEVEL-001 (VerificationLevel must not be owned by
  question_queue.py -- see that capability's own entry below); M7 (build
  continuation, per the Master matrix's own SECONDARY_DEPENDENCY field).
CURRENT_CALLERS: question_queue.py has real callers today (e.g. the
  waveform-dump-scope gate, per this session's own M5 Final Closure
  Regression failure classification, which found 3 pre-existing
  question_queue-related test failures unrelated to M5/M6).
CURRENT_WIRING: question_queue.py is live and load-bearing today;
  intake_clarification.py is not present in canonical to be wired at all.
TARGET_OPERATIONAL_PATH: build ClarificationService per D2's already-decided
  shape; NOT part of this preflight's scope to design further (Section:
  "Do NOT start CAP-M6-CLARSVC-001").
```

---

## CAP-M5M6-VLEVEL-001

**Capability name**: `verification_level.py` genericity foundation
(IP/SUBSYSTEM/SYSTEM_LEVEL).

```
CURRENT_STATE = BLOCKED (GENERICITY_FOUNDATION_GAP)
FOUNDATION_AVAILABLE = PARTIAL -- the two-mode half (SUBSYSTEM_MODE/
  SYSTEM_LEVEL_MODE) is real, wired, and operational; the IP_MODE /
  VerificationLevel three-way genericity layer is entirely absent.
FOUNDATION_EVIDENCE:
  - Canonical's own CLAUDE.md "Environment Generation Mode" section (line
    967) defines only TWO modes -- SUBSYSTEM_MODE and SYSTEM_LEVEL_MODE --
    "Dispatched in code at the generation entry point (2026-09-04)" via
    dv_harness/uvm_generator/create_environment.py and
    environment_mode_router.resolve_environment_mode(). Confirmed real and
    wired: this is genuine FOUNDATION+WIRED+OPERATIONAL territory, not a
    gap, for the two modes it covers.
  - dv_harness/environment_mode_router.py, read directly: only
    "SUBSYSTEM_MODE"/"SYSTEM_LEVEL_MODE" string literals appear; there is
    no "IP_MODE" branch anywhere in the file (confirmed by grep).
  - dv_harness/verification_level.py does NOT exist in canonical at all
    (confirmed: find returns nothing).
  - Parent's own dv_harness/verification_level.py (read-only reference)
    defines VerificationLevel(IP/SUBSYSTEM/SYSTEM_LEVEL) with a
    LEVEL_SEMANTICS table (intake_mode/environment_mode/topology_model/
    min_subsystems per level) and states "the level is a HUMAN decision
    (owner ruling D2)... resolve_verification_level() resolves from exactly
    two sources -- an explicit --level flag or a question-queue decision
    whose source is HUMAN_DECISION_SOURCE." NOTE, disclosed precisely so it
    is never conflated with the M-1 freeze's own D2 (Clarification): this
    is Parent's CLAUDE.md's own dated "owner ruling 2026-09-21" for
    VerificationLevel specifically, a DIFFERENT decision from the M-1
    freeze's D2. Canonical's own CLAUDE.md has no equivalent "owner ruling"
    entry for VerificationLevel at all today.
  - Parent's start_lifecycle() (see CAP-M6-DISPATCH-001 above) already
    threads a --level flag straight into the lifecycle's own facts
    (declared_level = parse_level(level); facts.update(verification_level=...)),
    i.e. Parent's own real code already couples the dispatch decision and
    the verification-level decision at the same entry point.
REMAINING_WORK: migrate/build verification_level.py (currently ABSENT from
  canonical); add an IP_MODE branch to environment_mode_router.py; complete
  the still-deferred question_queue.py N-way merge (M3-excluded) since
  VerificationLevel must not be owned by question_queue.py per the
  requirements-reconciliation guidance in
  L5DGVA_MASTER_REQUIREMENTS_AND_REMAINING_WORK_RECONCILIATION.md Section 15
  (a later requirements doc, not one of the frozen M-1 D1-D10 items itself --
  cited at its own, distinct evidence tier).
DEPENDENCIES: CAP-M6-CLARSVC-001 (per the Master matrix's own
  SECONDARY_DEPENDENCY field -- VerificationLevel and Clarification are
  reciprocally coupled: Clarification must not own the level, and the
  level's own human-decision channel is a question-queue-shaped mechanism);
  CAP-M5-ENV-001 (question_queue N-way merge).
CURRENT_CALLERS: none in canonical (the module does not exist to be called).
CURRENT_WIRING: environment_mode_router.py's real two-mode dispatch has no
  hook point for a third IP_MODE at all today.
TARGET_OPERATIONAL_PATH: not part of this preflight's scope to design
  further (Section: "Do NOT implement VerificationLevel yet").
```
