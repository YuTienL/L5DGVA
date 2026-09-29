# `.claude/templates/Makefile.patterns.mk` stub-targets implementation report

Date: 2026-09-01

## Task

`.work/make-pattern-api-doc-fix-report.md` (an earlier pass this session) found that while fixing
`.claude/skills/CORE/make-pattern-api/SKILL.md`'s fictional 11-target list, a *second*, genuinely
real Layer-2 system exists at `.claude/templates/Makefile.patterns.mk` (a project-`include`d
Makefile fragment operating on `.dv-harness/` pattern-registry/regression bookkeeping). 6 of its 11
targets were real and tested; the other 5
(`run-pattern`/`verify-pattern`/`regression`/`regression-monitor`/`regression-report`) were bare
`@echo`-only stubs that always exited 0 having done nothing real -- worse than a missing-target
error, because an agent running e.g. `make run-pattern` gets a confident-looking "Run foo ..." line
and a clean exit with no simulator ever invoked, and can mistake that for "already ran". This task
closes that gap.

## What was read first

- `.work/make-pattern-api-doc-fix-report.md` (the flagging report), full.
- `.claude/templates/Makefile.patterns.mk`, full (72 lines before the fix).
- `dv_harness/uvm_generator/templates/sim_scripts/Makefile`'s real target list and its own
  `help:` target text (the Layer-1 source of truth for what `run`/`check`/`sim`/`regress` actually
  do and which variables they take).
- `dv_harness/cli.py`'s subcommand list (`sub.add_parser(...)` calls) and `dv_harness/
  regression_reporter.py`'s `__main__` block, to find what real, already-tested, generic (non
  project-specific) tooling already exists to wire the monitor/report targets to.
- `dv_harness/lsf_client.py` (confirmed: library only, no CLI `__main__` of its own -- its
  functionality is reached exclusively through `dv_harness/cli.py`'s `lsf-*` subcommands).

## What was built

All 5 targets now either perform their real, stated purpose, or fail loudly with `$(error ...)`
naming exactly what real, project-specific configuration is missing -- never a silent no-op.

**`regression-monitor` / `regression-report` -- made fully real, no new configuration needed.**
These need no per-project fact: `dv_harness` itself is the generic, already-tested tool that reads
`.dv-harness/lsf/jobs/*.json`, the exact state tree this fragment's own `REGRESSION_LIST`
bookkeeping already lives next to.
- `regression-monitor` now runs `python3 -m dv_harness --project-root $(PROJECT_ROOT)
  lsf-watch-status` (is the background job/log monitor running) followed by `... lsf` (the full
  per-job state table) -- both real `dv_harness/cli.py` subcommands, added this same session for
  the 2026-09-01 sim-output-layout-and-background-job-monitor spec, previously wired to nothing in
  this fragment.
- `regression-report` now runs `python3 -m dv_harness.regression_reporter --project-root
  $(PROJECT_ROOT)`, `regression_reporter.py`'s own real CLI entry point, which renders a one-shot
  human-readable snapshot of the same job state (verified empty-state-safe and populated-state-
  correct by this task's own tests, see below).

**`run-pattern` / `verify-pattern` / `regression` -- made real, gated on one new required
variable.** These three cannot generically know a project's actual VCS/simulator invocation
(forbidden to fabricate one, per CLAUDE.md's Evidence Truth Rule / No Golden-Reference Content
Mining) -- but Layer 1 (`dv_harness/uvm_generator/templates/sim_scripts/Makefile`) already has real
`run`/`check`/`sim`/`regress` targets that do exactly what these three claim to do. The one missing
fact is *where* a given project's generated copy of that Makefile lives (`SIM_ROOT_PATH`/
`UVM_ROOT_PATH` vary per project, by that Makefile's own `help:` text) -- so a new `SIM_DIR ?=`
variable (empty by default) was added; the including project's own top-level Makefile sets
`SIM_DIR := <path>` to supply it.
- `run-pattern` -> `$(MAKE) -C $(SIM_DIR) run PATTERN=... SEED=... WAVE=... PA=... FSDB_START=...
  FSDB_STOP=...` (Layer 1's real `run` target: "run one pattern, never builds -- what LSF jobs
  use").
- `regression` -> `$(MAKE) -C $(SIM_DIR) regress SUITE=... JOBS=... LSF=...` (Layer 1's real
  `regress` target: "run every pattern in the suite, JOBS=<n> locally or LSF=1 on the farm").
- `verify-pattern` -> the doc-fix report's own finding was that Layer 1 has **no single**
  "verify" target; its closest real equivalent is a static check followed by a recorded dynamic
  run. So `verify-pattern` now chains `$(MAKE) -C $(SIM_DIR) check` then `$(MAKE) -C $(SIM_DIR) sim
  PATTERN=... SEED=... WAVE=... PA=... RECORD=1` -- a real two-step action, not a guessed single
  target name.
- When `SIM_DIR` is unset, each of these three fails immediately via `$(if $(SIM_DIR),,$(error
  ...))` inside its recipe (GNU Make's standard per-target-invocation error-guard idiom -- the
  `$(error)` is expanded, and make aborts, only when that specific target's recipe line is about to
  run, not at parse time for unrelated targets like `list-patterns`). The message names the real
  Layer-1 target it would have delegated to and what `SIM_DIR` needs to point at.

New variables added: `SEED ?= 1`, `SUITE ?= all`, `JOBS ?= 1`, `LSF ?= 0` (matching Layer 1's own
real defaults, confirmed by grep against the sim Makefile template), `PROJECT_ROOT ?= .`, and
`SIM_DIR ?=` (empty). `WAVE`/`PA`/`FSDB_START`/`FSDB_STOP`/`TIMEOUT` already existed and were left
unchanged. The 6 pre-existing real targets (`add-pattern`/`validate-pattern`/`list-patterns`/
`show-pattern`/`regression-add`/`regression-remove`) are untouched.

`.claude/skills/CORE/make-pattern-api/SKILL.md` (the doc fixed in the prior pass) was also updated:
its Layer-2 table and surrounding prose previously described these 5 as "Stub — only echo,
executes without error but does nothing real" -- now stale and actively misleading given the fix,
so it was rewritten to describe the real SIM_DIR-gated delegation and the now-generic monitor/
report behavior. Leaving it unrevised would have re-introduced exactly the kind of
doc-vs-reality gap the prior pass existed to close.

## Rulings

- **RULING**: `run-pattern`/`verify-pattern`/`regression` are made real via a new required
  `SIM_DIR` variable that delegates to Layer 1's own already-real targets, rather than either (a)
  leaving them as no-ops, or (b) fabricating a guessed VCS/LSF command line. This satisfies "(a)
  actually perform their stated purpose if that's feasible generically" -- the delegation mechanism
  itself *is* generic; only the one missing path is project-specific, and the project supplies it
  explicitly rather than the template guessing it. `$(error)` still fires when it's absent, so a
  project that has not wired `SIM_DIR` gets a loud, exact failure instead of a silent no-op.
- **RULING**: `verify-pattern`'s real action is `check` (static) then `sim ... RECORD=1` (dynamic,
  recorded) chained together, per the doc-fix report's own explicit finding that this is the
  closest real Layer-1 equivalent to "verify a pattern" and no single target exists. This is
  content-faithful to that prior finding, not a newly-invented mapping.
- **RULING**: `regression-monitor`/`regression-report` are wired to `dv_harness`'s own CLI
  (`lsf-watch-status`/`lsf`/`regression_reporter`'s `--project-root` entry point) rather than to
  Layer 1's `lsf_status`/`regress_summary`/`lsf_report` targets (which would also have required
  `SIM_DIR`). `dv_harness` ships as part of the harness itself (not per-project config), and its
  job-state store (`.dv-harness/lsf/jobs/*.json`) already sits next to this very fragment's own
  `REGRESSION_LIST`/`PATTERN_REGISTRY_OUT` state under `.dv-harness/` -- so these two needed zero
  new configuration to become fully real, which is a strictly better outcome than gating them on
  `SIM_DIR` too. (A project that also wants the Layer-1 LSF-farm view can still run `make
  regression LSF=1` directly, or `make -C $(SIM_DIR) lsf_status` by hand -- this fragment's
  `regression-monitor` intentionally reports the harness's own cross-run job ledger, not the raw
  farm queue.)
- **RULING**: the `$(if $(SIM_DIR),,$(error ...))` guard was written inline in each affected
  recipe (rather than as a top-level `ifndef SIM_DIR` block, the style Layer 1's own Makefile uses
  for its unconditional-per-build requirements like `VIP_HOME`) because the requirement here is
  target-specific, not build-wide -- `make list-patterns` must keep working with no `SIM_DIR` set
  at all. This is the standard GNU Make idiom for a per-target runtime precondition.

## Tests

Added `dv_harness_tests/test_makefile_patterns_stub_targets.py` (32 tests, all passing). Since
`make` itself is not installed in this sandbox (`command -v make` finds nothing anywhere on the
box), it verifies the fix two ways instead of a live `make <target>` run:
1. **Static structural assertions** on the actual recipe text (regex-extracted per target): no
   fixed target's body is echo-only any more; each either contains a `$(error` guard mentioning
   `SIM_DIR` or a real `$(MAKE) -C $(SIM_DIR) ...` / `python3 -m dv_harness...` invocation;
   `run-pattern`/`verify-pattern`/`regression` are cross-checked against the *actual* Layer-1
   `sim_scripts/Makefile` template to confirm the real target names they delegate to
   (`run`/`check`/`regress`) still exist there, so a future Layer-1 rename cannot silently leave
   this fragment stale again; `verify-pattern` is checked to actually chain `check` then `sim ...
   RECORD=1`; the 6 pre-existing real targets and the full `.PHONY` list are checked unchanged.
2. **Direct subprocess execution of the exact command lines** the regression-monitor/
   regression-report recipes now contain (bypassing `make`, since it is unavailable here, but
   running the identical `python3 -m dv_harness[...]` invocations against a real temp project
   root): confirms `lsf-watch-status`/`lsf`/`regression_reporter` all exit 0 and produce real,
   non-fabricated output on an empty project, and that `regression-report`'s snapshot genuinely
   reflects a registered job (writes a real `JobState` via `dv_harness.lsf_client.save_job_state`,
   then asserts the job id/pattern/count show up in the rendered report) -- proving this is a real
   report, not a hardcoded string.

**Full existing suite**: `python3 -m pytest dv_harness_tests/ -q` -> **1182 passed, 1 failed** in
739.91s (includes the 32 new tests above, all passing). The one failure,
`test_graph_parallel_dispatch.py::test_engine_dispatches_all_three_branches_concurrently_and_joins`,
is a pre-existing timing-sensitive assertion (`span < SLEEP * 1.8` on real wall-clock thread
scheduling) in an unrelated module (the graph/engine parallel-dispatch layer -- nothing this task
touched). Re-running that single test in isolation 3 times reproduced 1 failure and 2 passes,
confirming it is flaky under this sandbox's scheduling variance and not a regression introduced by
this change. It was left as-is: fixing a pre-existing flaky wall-clock timing assertion in an
unrelated subsystem is out of this task's scope, and CLAUDE.md's "fix a pre-existing bug you find"
guidance is best applied to bugs the fix's own test surface actually implicates, not an unrelated
flaky test discovered only by running the full suite as a regression check.

## Files changed

- `.claude/templates/Makefile.patterns.mk` -- 5 stub targets replaced with real/loud-failing
  implementations; new `SEED`/`SUITE`/`JOBS`/`LSF`/`PROJECT_ROOT`/`SIM_DIR` variables; header
  comment extended with the 2026-09-01 bug-fix note and ruling.
- `.claude/skills/CORE/make-pattern-api/SKILL.md` -- Layer-2 section updated to describe the real
  behavior instead of the now-stale "silent stub" description.
- `dv_harness_tests/test_makefile_patterns_stub_targets.py` -- new, 32 tests.

## Concerns / residual gaps

- `make` itself is not installed anywhere in this sandbox, so the Makefile's own control flow
  (the `$(if)`/`$(error)` gating, the `$(MAKE) -C` recursion) could not be exercised end-to-end by
  actually invoking `make run-pattern` etc. Static content verification plus direct execution of
  the exact wired `python3 -m dv_harness...` commands was the closest verification achievable here.
  Recommend a follow-up smoke check on a machine with GNU Make available: `make -n run-pattern`
  (should print the `$(error)` and abort) and `make -n run-pattern SIM_DIR=/some/dir` (should print
  the real `$(MAKE) -C /some/dir run ...` line) as a first real-Make confirmation.
- `run-pattern`/`verify-pattern`/`regression` still require a project to actually set `SIM_DIR` --
  by design (see Rulings above), but this means a project that adopts `Makefile.patterns.mk`
  without also setting `SIM_DIR` in its own top-level Makefile will still see these three fail
  (loudly, not silently) until it does. That is the intended and correct behavior, not a gap, but
  worth flagging so it isn't mistaken for an incomplete fix.
- The pre-existing flaky `test_graph_parallel_dispatch.py` timing test (see Tests above) is
  unrelated to this task and was left unfixed; noting it here per the task's "note any pre-existing
  bug found" instruction even though fixing it is out of scope.
