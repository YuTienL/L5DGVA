# M4 Final Report — Dependency / Schema / Contract Closure

## Closure regression — real, verified completion

```
FINAL_CANONICAL_HEAD (regression target) = b332d4171b0da97a95866b8fa6b8cfd993825c22
FINAL_CANONICAL_BRANCH = canonical/m4-dependency-closure
EXACT_PYTEST_COMMAND = python -m pytest -q --tb=no -o cache_dir=.pytest_cache_m4
COLLECTED = 13876 (27 failed + 13820 passed + 28 skipped + 1 xfailed)
PASSED = 13820
FAILED = 27
SKIPPED = 28
XFAILED = 1
REAL_CHILD_EXIT_CODE = 1 (pytest's normal "N failed" code)
DURATION = 4266.40s (1:11:06)
TIMEOUT_STATUS = NO
CRASH_STATUS = NO (0 Traceback/INTERNALERROR/Fatal Python error lines)
HEAD_DURING_RUN = unchanged (re-confirmed b332d417... at completion; zero
                   working-tree changes for the run's full duration --
                   the discipline established after the M1D
                   REGRESSION_HEAD_MISMATCH incident was followed
                   throughout: all M4 documentation was written and
                   committed BEFORE this launch, not during it)
```

## Failure-identity differential (script-computed, not eyeballed)

**M4 vs. M1D closure reference** (the most recent full-regression
checkpoint, `M1D_final_closure_regression_output.txt`, 28 failed at HEAD
`9a5c3ee`):
```
COMMON = 27, NEW = 0, GONE = 1
GONE: test_gui_intake_control_plane.py::test_real_server_post_answer_without_token_is_rejected_NEGATIVE_CONTROL
```
This is the exact test M1's own closure diagnosed as a load-sensitive
real-HTTP-server timing flake with zero code overlap with anything M1/M1D
touched — it simply did not trigger this run, consistent with a flake's
own nature (intermittent, not deterministic), not a suspicious
disappearance. **Zero new failures from M3 or M4's combined work.**

**M4 vs. frozen v50 baseline** (`_h2_6_final_run.log`, 21 failed):
```
COMMON = 21, NEW = 6, GONE = 0
```
The same 6 failures already fully diagnosed during M1
(`M1_FULL_REGRESSION_CLASSIFICATION.md`): 3 in
`test_sim_scripts_makefile_mechanisms.py` (gitignored `USB_UVM_Handoff/`
reference tree, a git-clone-bootstrap structural fact) + 3 in
`test_syoscb_result_taxonomy.py` (a fragile `parents[2]` directory-depth
test assumption, exposed by the canonical repo's sibling-of-Parent
placement) — both `TEST_INFRASTRUCTURE`, re-confirmed unchanged, not
re-investigated from scratch this wave.

## Classification

```
REGRESSION_CAUSED_BY_M3 = 0
REGRESSION_CAUSED_BY_M4 = 0
UNKNOWN_REGRESSION_FAILURES = 0
```

M4 closure gate: **passes** (`REGRESSION_CAUSED_BY_M4 = 0` and
`UNKNOWN_REGRESSION_FAILURES = 0`).

---

## Additional required reports

### GOVERNING_CONTRACT_AUTHORITY (the ~20 Parent-only contracts)

Real, on-disk investigation (not assumed): Parent's own working tree has a
`L5DGVA/` directory holding **25 real `.md` files, 4.0 MB, 106,132 lines
total** (V2 through V23 plus a Knowledge-Brain adversarial-review prompt and
an executable-specification prompt). This is the exact corpus
`l5dgva_contract_registry.py` expects at `ROOT / "L5DGVA"`
(`M4_M3_DEFERRED_CLOSURE.md`).

**Critical, newly-confirmed fact**: `git ls-files L5DGVA/` in Parent returns
**zero** tracked files — the entire corpus is untracked in Parent's own git
history, despite being large, real, and substantive (the same "real but
never committed" pattern already seen twice this session, `replay.ps1` and
`USB_UVM_Handoff`). Confirmed absent from v50 as well (`ls` — no such
directory).

```
GOVERNING_CONTRACT_AUTHORITY = UNRESOLVED, GENUINELY OUT OF M4/M5 SCOPE
  -- not a schema/contract foundation gap (there is no missing field or
     interface to define); it is a decision about whether/how a
     4MB/106K-line, entirely git-untracked, 25-document corpus becomes
     part of the canonical repository at all, and if so, by what
     mechanism (whole-corpus import? per-document review? a distilled
     summary, consistent with this project's own Tier-1
     "never-load-wholesale" reference-material discipline?).
  -- NOT classified via the existing 8-value canonical-authority taxonomy
     (PARENT_SUPERSET/V50_SUPERSET/etc.) -- none of those values describe
     "a corpus that exists on only one side and was never under git
     control there either."
```

### ClarificationService architecture — already decided, design remains

Checked `M_MINUS_1_ARCHITECTURE_DECISIONS.md` directly (not assumed):
**D2 already resolves the architecture question.** Verbatim: "`question_queue.py`
(v50) and `intake_clarification.py` (parent) will **not** both survive as
competing semantic authorities in the canonical repo. The canonical target
defines **one** service, `ClarificationService`... This directly resolves
[the] 'single most consequential reconciliation decision'... no longer an
open item."

What D2 does **not** yet resolve (its own text says so): "a real
feature-level comparison of what each of `question_queue.py`'s and
`intake_clarification.py`'s real, tested capabilities are... is real work
for the wave that builds it."

```
CLARIFICATION_ARCHITECTURE_DECISION = ALREADY_MADE (M-1, D2)
CLARIFICATION_DESIGN_WORK_REMAINING = YES (feature-level capability
  comparison + ClarificationService build itself -- M6/M7 territory,
  design/implementation, not an open architecture choice)
```

This corrects `M4_M6_CORE_PREREQUISITE_MATRIX.csv`'s engine.py row, which
had characterized this as `KNOWN_DECISION_PENDING_HUMAN_INPUT` — more
precisely, the DECISION is made; what remains PENDING is DESIGN, a
narrower and already-less-risky state than the matrix's own wording
implied. (Not amended in the CSV itself this wave, to avoid a
working-tree change after the regression's HEAD was frozen for this
report — noted here for the record, to be folded into the CSV in the wave
that actually starts that design work.)

### VERIFICATION_LEVEL_FOUNDATION

```
VERIFICATION_LEVEL_FOUNDATION = GENERICITY_FOUNDATION_GAP (disclosed, not closed)
  -- verification_level.py confirmed absent from canonical (Parent-only).
  -- Blocked on .question_queue (HUMAN_DECISION_SOURCE, QuestionQueueStore,
     make_question_id) -- a diverged, M3-excluded module; cannot be
     migrated as a clean leaf.
  -- Independently corroborated: canonical's own environment_mode_router.py
     has no IP_MODE concept at all today (re-confirmed this wave) --
     SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE only.
  -- Not resolvable by M4 alone: real resolution requires either (a)
     migrating question_queue.py's dependency chain first (M5/M6
     territory), or (b) the ClarificationService's own eventual design
     absorbing verification_level.py's dependency differently.
```

### M5 / M6 unresolved-prerequisite counts (tallied from the real matrices)

```
M5_UNRESOLVED_FOUNDATION_PREREQUISITES = 8
  (env_manifest.py=1, vip_capability_extraction.py=2,
   create_environment.py=1 [ARCH-01 not yet investigated],
   soc_environment_composer.py=1, amba_fabric_generator.py=1,
   functional_coverage_signoff.py=1, design_source_inventory.py=1;
   register_excel_extract.py/memory_vault.py/loop_telemetry.py = 0 each,
   resolved this wave or re-confirmed from M1)

M6_UNRESOLVED_FOUNDATION_PREREQUISITES = 2
  (cli.py/dashboard.py dispatch-mechanism decision -- counted once, not
   twice, since it is one decision affecting both files; lifecycle
   integration wiring-point identification;
   engine.py/ClarificationService/inference.py/multi-agent = 0 each,
   resolved or re-confirmed this wave)
```

Per the user's own stated success criterion for M4, **these two counts are
the real headline metric of this wave, not the count of migrated files**.
Both are non-zero and honestly reported as such — M4 reduced them from an
unquantified/undocumented state to a concrete, evidenced, addressable list
(every one of the 10 items has a named reason and, where investigated, a
specific missing piece), but did not drive either to zero. Driving them
further requires real symbol-level `ast` diffs for the 4 fully-UNRESOLVED
M5 targets and the cli.py/dashboard.py dispatch decision — both explicitly
larger-scope tasks than this wave's time budget covered, disclosed rather
than rushed or fabricated.

---

## Root-hygiene / location-independence / execution-profile / Article 0 re-confirmation

```
ROOT_LAYOUT_GATE = PASS
LOCATION_INDEPENDENT = YES
REPOSITORY_IDENTITY = PASS
EXECUTION_PROFILE_RESOLUTION = PASS
EXISTING_REMOTE_TRANSPORT_PRESERVED = YES
EXECUTION_SERVICE_OPERATIONALIZED = NO
REMOTE_EDA_BACKEND_OPERATIONALIZED = NO
KNOWLEDGE_BRAIN_PRESERVED = YES (unchanged this wave)
OBSIDIAN_CAPABILITY_PRESERVED = YES (unchanged this wave)
MULTI_AGENT_PROTECTED_CAPABILITY_RECORDED = YES
MULTI_AGENT_DIRTY_DIFF_APPLIED = NO
CANONICAL_SECURITY_FLOOR = PRESERVED (unchanged this wave)
KNOWN_SOURCE_B_DEFECT_STATUS = KNOWN_SOURCE_B_DEFECT_PRESERVED_FOR_LATER_FIX (unchanged)
EXECUTION_CONFIG_CONSUMER_STATUS = EXECUTION_CONFIG_CONSUMER_MIGRATION_PENDING (unchanged)
```

Constitution/anti-drift gate: `check_constitution_intact() -> PASS`, 0
`ARCHITECTURE_CONFLICT` raised this wave. Full `HIGHEST_PRINCIPLE_COMPLIANCE`
detail in `M4_CONSTITUTION_COMPLIANCE.md`.

## Source immutability (re-confirmed at closure, not just at launch)

```
SOURCE_A_CHANGED_SINCE_M0 = NO  (Parent HEAD 3e9dd7360f584078ed8f4b04120c9844acabd97b, unchanged)
SOURCE_B_CHANGED_SINCE_M0 = NO  (v50 HEAD f3fd17326cf3654aca6fd83fad991a3f247e6682, unchanged)
B7A_CHANGED = NO  (7b2a65a4dc2d40d493451b409669c90ed0b3d9a5)
B7B_CHANGED = NO  (c7c7fa09e9ee8336ba102b4495f4b8808408fe0b)
B8_CHANGED = NO   (c9cdd06ce586d44f4c0cef00310c10f95ea59f93)
REFERENCE_USB_ENV_CONSUMED = NO
```

---

## Final report

```
M4_STATUS = READY_FOR_APPROVAL
NEXT_GATE = M4.5_GOVERNING_CONTRACT_AUTHORITY
  (the ~20/25-document Parent-only governing-contract corpus requires an
   explicit human decision on whether/how to migrate it -- NOT silently
   folded into M5, which is scoped to N-way CODE semantic merge, not a
   106K-line document-corpus migration/distillation decision)

M4_BRANCH = canonical/m4-dependency-closure
M4_HEAD = b332d4171b0da97a95866b8fa6b8cfd993825c22

FOUNDATION_ITEMS_REVIEWED = 18 (10 M5 targets + 7 M6 targets + 1 formal
                                 M3->M4 deferred item)
FOUNDATION_ITEMS_MIGRATED = 2 (CAP-M4-001 schema field, CAP-M4-002
                                ipxact_register_import.py)
FOUNDATION_ITEMS_REUSED = 9 (memory_vault.py contract, create_environment.py
                              defect contract, engine.py 247-method
                              contract, inference.py core, multi-agent
                              protected-input status, and the Research/
                              Experience/Level-Protocol-Topology/vPlan-
                              Coverage-Traceability/Execution foundation
                              elements confirmed present and reused rather
                              than redesigned)
FOUNDATION_ITEMS_DEDUPLICATED = 1 (cli.py/dashboard.py's shared dispatch
                                    decision counted once, not twice)

M3_DEFERRED_TO_M4_RESOLVED = 0
M3_DEFERRED_REDEFERRED = 1 (reassigned to the new, unscheduled
                             M4.5_GOVERNING_CONTRACT_AUTHORITY decision,
                             not silently defaulted into M5)

M5_TARGETS_ANALYZED = 10
M5_UNRESOLVED_FOUNDATION_PREREQUISITES = 8

M6_CORE_TARGETS_ANALYZED = 7
M6_UNRESOLVED_FOUNDATION_PREREQUISITES = 2

GENERICITY_FOUNDATION_GAPS = 1 (verification_level.py absence)

VPLAN_COVERAGE_TRACEABILITY_FOUNDATION = READY
RESEARCH_EXPERIENCE_FOUNDATION = PARTIAL (deferred to M8, unchanged from M3)
EXECUTION_FOUNDATION = READY (unchanged, unextended)

MULTI_AGENT_PROTECTED_DIFF_APPLIED = NO

ROOT_LAYOUT_GATE = PASS
LOCATION_INDEPENDENT = YES

SOURCE_CAPABILITY_LOSS = 0
V50_CAPABILITY_LOSS = 0

CANONICAL_CAPABILITY_STRICT_SUPERSET = NOT_YET_QUALIFIED

HIGHEST_PRINCIPLE_COMPLIANCE = LOCATION_INDEPENDENT=PASS,
  EVIDENCE_GROUNDED=PASS, KNOWLEDGE_DRIVEN=PARTIAL(->M8),
  CONTINUOUS_EVOLUTION=PARTIAL(->M8), END_TO_END_DV_ALIGNMENT=PARTIAL(->M9-M11)

SOURCE_A_CHANGED_SINCE_M0 = NO
SOURCE_B_CHANGED_SINCE_M0 = NO
B7A_CHANGED = NO
B7B_CHANGED = NO
B8_CHANGED = NO

REFERENCE_USB_ENV_CONSUMED = NO

M5_STARTED = NO
M6_STARTED = NO
C6_STARTED = NO
PLATFORM_UPGRADE_STARTED = NO
```

**M4_STATUS = READY_FOR_APPROVAL, NEXT_GATE = M4.5_GOVERNING_CONTRACT_AUTHORITY.**

**STOP. Not starting M4.5, M5, or M6. Waiting for explicit approval and a
decision on the governing-contract corpus.**
