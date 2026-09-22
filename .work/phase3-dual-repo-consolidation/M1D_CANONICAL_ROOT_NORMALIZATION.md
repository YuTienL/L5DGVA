# M1D — Canonical Root Normalization

Full evidence-based root-layout cleanup, executed AFTER the pre-normalization
reference regression was captured and frozen (`M1_FULL_REGRESSION_CLASSIFICATION.md`,
`REGRESSION_CAUSED_BY_M1 = 0`, `UNKNOWN_REGRESSION_FAILURES = 0`), per the
governing instruction's explicit sequencing.

## Method (not the Phase-2 "has consumer => keep in root" shortcut)

For every root-level MD/PS1/CMD/JSON/TCL/SH file: (1) read its real content/
purpose (not filename guessing), (2) enumerate every real consumer via
repo-wide grep across `.py`/`.md`/`.ps1`/`.cmd`/`.json`/`.tcl`/`.sh`, (3)
distinguish a real functional dependency (code that `open()`s/`read_text()`s
the file by path) from a textual citation (comment/docstring/doc-link), (4)
move + rewrite every functional and citation consumer, verified by running
the affected tests, (5) leave historical/frozen content (`.work/**`,
`docs/legacy/**`, `.dv-harness/memory/**`, dated `TC_2026-09-0x`/`_assembled_draft`
snapshots, dated design specs) untouched, disclosed rather than silently
skipped.

## What moved

**24 MD documents**, by real semantic domain:
- `docs/architecture/`: EVIDENCE_TRUTH_RULE, OPERATING_MODES, SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE, SOC_SYSTEM_LEVEL_COMPOSER, VERIFICATION_ARCHITECTURE_MECHANISM_FIRST
- `docs/workflow/`: CREATE_ENVIRONMENT, DEBUG_WORKFLOW_GUIDE, DV_EXPERT_FEEDBACK_CLOSED_LOOP, GIT_DEVOPS_ONE_PAGE, LSF_PER_JOB_AGENT_MONITORING_v16_1, LSF_STRICT_PER_JOB_IRON_RULES_v19_1, STAGE_EXECUTION_PROFILE, USAGE_MULTI_USER_SAFETY, WORKFLOW_CLOSURE_ONE_PAGE
- `docs/verification/`: DUT_ARCHITECTURE_DISCOVERY_AND_CALIBRATION, SCOREBOARD_CHECKER_ASSERTION_ANALYZER, VPLAN_DRIVEN_SPEC_COVERAGE, VPLAN_INTAKE_WIZARD
- `docs/protocol/`: PROTOCOL_SUPPORT_MATRIX
- `docs/remote/`: REMOTE_CONTROL_MODE, REMOTE_LOGIN_GUIDE
- `docs/knowledge/`: KNOWLEDGE_CENTER_GUIDE
- `docs/release/`: CHANGELOG_v0_to_v50, FINAL_PACKAGE_INDEX

**1 flagged-UNKNOWN scratch file** (content preserved, never deleted): `_tmp_experience_loop_design.txt` → `docs/legacy/` (Phase-1 hygiene audit's own `UNKNOWN` disposition, blocking deletion, left un-overridden).

**2 PS1 scripts with real functional test dependencies**, found and fixed before/after moving: `DV_GRAPH_STATUS.ps1`, `DV_REGRESSION_SNAPSHOT.ps1` → `scripts/powershell/`.

**4 superseded launcher scripts** (only referenced from `docs/legacy/`/`.work/`): `START_AI_AGENT_HARNESS_L5.ps1`, `START_ULTIMATE_AI_AGENT_HARNESS_L5.ps1`, `START_CLAUDE_DV.ps1`, `START_CLAUDE_DV.cmd` → `scripts/powershell/legacy/`.

## What stayed (`ROOT_AUTHORITY_EXCEPTION`, each with a recorded reason)

`.gitignore`, `.claudeignore`, `README.md`, `START_HERE.md`, `CLAUDE.md`,
`pyproject.toml`, `justfile`, `requirements-harness.txt` (root-authority
config/build/entry-point docs); `WORKFLOW_MANIFEST.json` (real, root-anchored
consumer: `tools/verification_flow/gate_manifest_registry_consistency_gate.py`
hardcodes `root/"WORKFLOW_MANIFEST.json"`); `replay.ps1` +
11 other `*.ps1` (each already a 2-30 line thin shim over canonical
`dv_harness/*.py` logic, each with a real, live, multi-surface consumer
expectation — `START_HERE.md`, `docs/remote/REMOTE_CONTROL_MODE.md`,
`docs/MEMORY_OPERATIONS.md`, and a live `.claude/skills/CORE/memory-retrieval/SKILL.md`
— all invoking these by a root-relative path; moving them would only add
indirection, never reduce root file count, since a root-level shim would
still be required either way).

## TCL / SH (explicit follow-up request)

Zero `.tcl`/`.sh` files exist at this repository's root (confirmed via
`git ls-files`); the codebase's single `.tcl` file already lives correctly
under `dv_harness/uvm_generator/templates/sim_scripts/waves.tcl`. Nothing to
move. `root_hygiene_gate.py`'s `GOVERNED_EXTENSIONS` still covers both, so a
future root-level `.tcl`/`.sh` file would be caught.

## Root-hygiene gate (installed)

`dv_harness/root_hygiene_gate.py` — real `PRODUCT_ROOT_ALLOWLIST` (21 files,
each evidenced above) + `check_root_layout()`, flags any new unlisted root
MD/PS1/CMD/JSON/TCL/SH file. 12 real tests, including a live assertion that
the actual canonical root currently passes with 0 violations. Wired into
`dv-harness doctor`'s new `ROOT_LAYOUT_GATE` field (confirmed `PASS` live,
including from a relocated copy and a git-free deployment copy).

## A process bug caught and fixed during this work

A citation-rewrite pass re-run over an already-functionally-rewritten line
(for the 2 moved PS1 scripts) produced a doubled `scripts/powershell/scripts/powershell/`
path in 2 test files. Caught immediately by re-running the affected tests
(2 failures), root-caused exactly, fixed directly, and a repo-wide follow-up
scan confirmed zero other instances of the same bug (including in the much
larger 24-MD-file batch, which used the same script pattern).

## Capability preservation re-verification (after normalization)

- `dv_harness_tests/test_root_hygiene_gate.py`: 12/12 pass
- Moved-file/consumer tests (`test_graph_runtime_removed.py`,
  `test_watch_cadence_spec.py`, `test_remote_control.py`,
  `test_multi_user_coordination.py`, `test_inference_engine_wiring.py`,
  `test_harness_deploy.py`, `test_remote_exec.py`): all pass (125 + 52 in
  part 1, re-confirmed as part of the 203-test relocated-copy run below)
- `dv-harness doctor`: `ROOT_LAYOUT_GATE: PASS`, all other fields unchanged
- **Location-independence re-verified after normalization**: fresh `git clone`
  to a different path/basename, synthetic test profile (never the real
  one) → identity/git-root/execution-profile/doctor all correct; 203/203
  tests pass from the relocated copy (includes every M1+M1D-relevant suite)
- **Deployment-copy-mode re-verified after normalization**: fresh
  `git archive | tar -x` (no `.git`) → `DEPLOYMENT_COPY_MODE` correctly
  detected, `GIT_ROOT_CONSISTENCY: GIT_CAPABILITY_UNAVAILABLE` (honest
  capability gap, not a generic failure), `ROOT_LAYOUT_GATE: PASS`
- Final M1-closure full-suite regression: launched against normalized HEAD
  `f88ddd524a505511c7cae456aa1433c3f4609451`; see the closure-regression
  addendum below once it completes (the earlier full run,
  `M1_FULL_REGRESSION_CLASSIFICATION.md`, is the pre-normalization
  reference only, per this instruction's own explicit sequencing).

## Report

```
M1D_STATUS = PASS
ROOT_TRACKED_FILES_BEFORE = 52
ROOT_TRACKED_FILES_AFTER = 21
ROOT_ALLOWLIST_FILES = 21
FILES_MOVED_TO_DOCS = 25 (24 MD by domain + 1 flagged-UNKNOWN scratch file to docs/legacy/)
FILES_MOVED_TO_SCRIPTS = 6 (2 to scripts/powershell/, 4 to scripts/powershell/legacy/)
FILES_MOVED_TO_CONFIG = 0
COMPATIBILITY_SHIMS = 0 (every consumer was directly rewritten to the new
                          path rather than leaving an old-location redirect
                          stub; the 12 ROOT_AUTHORITY_EXCEPTION scripts were
                          already thin shims and were not moved at all)
UNRESOLVED_ROOT_FILES = 0
ROOT_LAYOUT_GATE = PASS
CAPABILITY_LOSS_FROM_NORMALIZATION = 0
LOCATION_INDEPENDENT = YES
```

Per instruction: continue to final M1 qualification since
`CAPABILITY_LOSS_FROM_NORMALIZATION = 0`, `UNRESOLVED_ROOT_FILES = 0`, and
`ROOT_LAYOUT_GATE = PASS` all hold — pending the final closure regression's
own completion (addendum below).

---

## Closure-regression addendum (appended once the background run completes)

*(pending)*
