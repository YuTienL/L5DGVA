# CAP-M5-ATL004-001 — task_boundary_conformance.py — Task Boundary Analysis

## Correction to the record (Evidence Truth Rule)

Two facts asserted earlier this Cohort (`PARENT_CALLERS = 0`,
`PARENT_TESTS = 0`) were **wrong**, caused by an unscoped background grep
across Parent's entire (large) repo root silently returning no matches
instead of failing loudly. Re-run scoped to `dv_harness`/`dv_harness_tests`/
`tools`/`.claude`, the real facts are:

- **`PARENT_TESTS`**: `dv_harness_tests/test_task_boundary_conformance.py`
  exists (200 lines, committed `705c469b`, dated 2026-09-16). Independently
  re-run in Parent's own tree: **19/19 pass**.
- **`PARENT_CALLERS`**: `dv_harness/cli.py` has a real, wired CLI verb,
  `task-boundary-conformance` (lines 4284-4295), dispatching to
  `TaskBoundary.from_dict()` / `check_working_tree_conformance()` /
  `check_committed_range_conformance()`, with its own exit-code convention
  (`0` for `HELD`/`NO_CHANGES`, `1` otherwise).
- **The module's own docstring is stale**: its own point 3 claims "not
  wired into any stage gate, engine.py or cli.py" — real Parent evidence
  contradicts this. Not propagated into the canonical migration (corrected
  in canonical's own copy — see `M5_COHORT_4_SEMANTIC_MERGE_PLAN.md`).

## Operationality classification (per instruction: do not treat a low
## caller count as proof of uselessness — classify each axis separately)

| Axis | Parent | Canonical (pre-migration) | Canonical (post-migration, this Cohort) |
|---|---|---|---|
| `IMPLEMENTED` | YES (330 lines, self-contained) | NO | YES (migrated, 330 lines, byte-adapted docstring only) |
| `WIRED` | YES (`cli.py` `task-boundary-conformance` verb) | N/A | **NO** — deliberately not wired; see rationale below |
| `CONSUMED` | YES (the CLI verb is a real dispatch path; the module's own docstring cites a real precedent — this repo's own multi-agent dispatch prompts already issue this exact shape of instruction in prose) | N/A | NO (0 real canonical callers as of this migration) |
| `TESTED` | YES (19/19 real tests, independently re-run and confirmed) | N/A | YES (19/19, ported and independently re-run in canonical: **19/19 pass**) |
| `OPERATIONAL` | YES in Parent (a human/script can run the real CLI verb and get a real verdict) | N/A | **NOT YET** — importable and structurally sound, but not reachable from any canonical entry point |

## Why WIRED=NO is the correct Cohort 4 decision, not an oversight

Parent's own CLI wiring is real and safe there. Replicating it into
canonical's `cli.py` was considered and explicitly rejected for this
Cohort: `CAP-M6-DISPATCH-001` (`cli.py`/`dashboard.py`'s own
dispatch-mechanism decision) is an open, `HUMAN_DECISION_REQUIRED` P0
blocker in `MASTER_CAPABILITY_STATUS_MATRIX.csv`, owned by M6. Adding a
new verb to `cli.py` now would pre-empt that not-yet-made decision rather
than build on it — the same discipline this project already applies to
`CAP-M5M6-VLEVEL-001` (M5 "must not create foundation architecture that
conflicts with M6's still-pending design"). The capability is therefore
delivered as a real, tested, importable FOUNDATION module; wiring it into
`cli.py` (or any other real dispatch point) is registered as an explicit
`CAP-M6-DISPATCH-001` dependency, not silently dropped.

## Required-by-an-accepted-contract check (instruction's own framing)

Is this capability nevertheless required by an accepted Canonical
contract, even with 0 canonical callers today? **Yes, indirectly but
really**: this entire M5 program's own standing rules ("never modify
Parent/v50/b7a/b7b/b8," "every required artifact set must be produced
under `.work/phase3-dual-repo-consolidation/`, never in repo root," named
per-cohort file allow/forbid lists issued in every cohort's own dispatch
instruction) are EXACTLY the shape of boundary this module can now check
mechanically, and have so far been enforced only by this session's own
git-status/git-diff discipline — human/AI attention, not a machine-checked
artifact. That is a real, accepted (if implicit) governance pattern this
module now has a genuine, evidence-backed capability to formalize, not a
speculative future use.

## Task-Boundary Security evaluation (instruction item 14)

| Requirement | Status |
|---|---|
| Path normalization | `_norm()`: strips whitespace, normalizes `\` to `/`, strips trailing `/` |
| Repository boundary | Operates on whatever `root` the caller passes; does not itself validate `root` is the intended repository — a caller error, not a module defect (documented as a caller-declared input, point 2 of the module's own docstring) |
| Read/write distinction | Read-only: only ever runs `git status`/`git diff`/`git rev-parse`; never writes |
| Protected artifacts | Caller-declared via `forbidden_paths`; forbidden always wins over allowed even when nested under an allowed prefix (`classify_path()`, verified by `test_forbidden_wins_even_if_nested_under_an_allowed_prefix`) |
| Explicit allow/deny scope | `allowed_path_prefixes` / `forbidden_paths`, both caller-declared, both real path-prefix matches (not substring — verified by `test_prefix_match_is_a_real_path_segment_not_a_substring`) |
| Unexpected path | Anything not matching an allowed prefix is `CLASS_OUTSIDE`, not silently accepted |
| Symlink/path-traversal | Not evaluated by this module — it classifies `git status`/`git diff` OUTPUT paths (already resolved relative paths from git itself), not raw filesystem input; git's own path resolution is the trust boundary here, not re-implemented |
| Fail-closed behavior | A `NO_GIT`/`STATUS_FAILED`/`DIFF_FAILED` result is a distinct verdict (`VERDICT_NO_GIT`), never silently treated as `BOUNDARY_HELD` |

No redesign of the security architecture was performed or proposed — this
is a review of the existing, migrated contract only, per instruction.

## VELM / Agent Task Lifecycle / Fast Maintenance compatibility (instruction item 10)

This module's own output shape (`{task_id, verdict, git_status, detail,
findings, scope_caveat}`) is generic enough to serve any of the following
future callers without modification, since none of them require anything
beyond "declare a boundary, get a structural verdict against real git
evidence":

- **Agent Task Lifecycle** (`CAP-ATL-*`): `TaskBoundary.task_id` is
  already a plain string field — compatible with whatever task-identity
  scheme M6/M7 eventually build (see `AGENT_TASK_LIFECYCLE_ANALYSIS.md`'s
  own `TASK_IDENTITY` finding: 3 composable primitives, no single ID
  scheme yet). No coupling to a specific ID format is introduced.
- **Native Claude Fast Maintenance / Full L5DGVA maintenance**: both need
  scoped modification authority per this Cohort's own instruction (item
  15) — this module is exactly a scoped-modification CHECK, usable by
  either execution mode without change.
  `Change Workspace` / `Controlled Environment Modification`: a future
  M10.5 change-workspace mechanism can declare a `TaskBoundary` for
  exactly the files a change is permitted to touch and check conformance
  before/after, with no new capability needed from this module.
- **Fast-to-Full Context Handoff**: a `TaskBoundary` object round-trips
  through `TaskBoundary.from_dict()`/dataclass fields cleanly — a natural
  fit for a handoff payload, though this Cohort does not implement any
  handoff mechanism itself (M10.5 territory, not touched).

No M10.5 functionality is implemented by this analysis or by the
migration itself — this section establishes compatibility, not a build.
