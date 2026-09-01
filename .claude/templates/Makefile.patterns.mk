# Pattern management API
# Integrate with the project's existing Makefile rather than replacing canonical build/run logic.
#
# BUG FIX (2026-08-29, poster-compliance-audit item #49): every target below used to be a bare
# `@echo` stub with no real logic behind it, while a separate, differently-named target set
# (list_patterns/add_pattern/remove_pattern, underscore) was independently emitted by
# dv_harness/uvm_generator/pattern_registry_generator.py's emit_makefile_fragment() -- two
# disconnected command surfaces claiming to do the same job. add-pattern/validate-pattern/
# list-patterns/show-pattern below now call that same real, tested pipeline (via
# tools/generate_pattern_registry.py / tools/verification_flow/pattern_registry_completeness_gate.py)
# against a project-maintained PATTERNS_JSON source file; regression-add/regression-remove call
# dv_harness/uvm_generator/regression_list_manager.py's real pipeline (via
# tools/regression_list_cli.py).
#
# BUG FIX (2026-09-01, make-pattern-api-stub-targets-implementation): the remaining five targets
# (run-pattern/verify-pattern/regression/regression-monitor/regression-report) used to be silent
# `@echo`-only no-ops that always exited 0 -- an agent running e.g. `make run-pattern` got a
# confident-looking "Run foo ..." line and a clean exit code with NO simulator ever invoked, which
# is a worse trap than a missing-target error (see .work/make-pattern-api-doc-fix-report.md, which
# first found this). Two of the five (regression-monitor/regression-report) now have a real,
# generic, already-tested implementation to wire to as of this same date: `dv-harness lsf-watch-*`
# and `dv_harness.regression_reporter`'s one-shot snapshot render (dv_harness/cli.py's
# lsf-watch-start/-stop/-status subcommands, added for the 2026-09-01 sim-output-layout-and-
# background-job-monitor spec) read/report `.dv-harness/lsf/jobs/*.json` state that this fragment's
# own REGRESSION_LIST bookkeeping already lives next to -- no per-project knowledge required, so
# these two now really run something instead of stubbing. The other three (run-pattern/
# verify-pattern/regression) each need one genuinely project-specific fact this template cannot
# invent: WHERE the real generated per-IP sim Makefile lives (its `run`/`check`/`sim`/`regress`
# targets -- see dv_harness/uvm_generator/templates/sim_scripts/Makefile, ~3650 lines, real source
# of truth for the actual VCS/simulator invocation). RULING: rather than leave those three as
# no-ops OR fabricate a guessed VCS command line (forbidden -- CLAUDE.md's Evidence Truth Rule /
# No Golden-Reference Content Mining), they now delegate via `$(MAKE) -C $(SIM_DIR) <real target>`
# once the project sets SIM_DIR to that directory, and fail loudly with $(error) -- not a silent
# echo -- when SIM_DIR is unset, naming exactly what real target they would have run and where to
# point it. verify-pattern has no single Layer-1 target at all (confirmed in the doc-fix report
# above); its real equivalent is the two-step check (static) + sim RECORD=1 (dynamic, verdict
# recorded) sequence, so that is what it now runs, still gated on SIM_DIR for the same reason.

.PHONY: add-pattern validate-pattern list-patterns show-pattern run-pattern verify-pattern \
        regression-add regression-remove regression regression-monitor regression-report

WAVE ?= 0
PA ?= 0
FSDB_START ?= 0
FSDB_STOP ?= simulation_end
TIMEOUT ?=
SEED ?= 1
SUITE ?= all
JOBS ?= 1
LSF ?= 0

# Project-maintained source of truth: append/edit pattern entries here, then `make add-pattern`
# regenerates and validates the registry from it (pattern_registry_generator.build_registry() takes
# the full pattern list, not one incremental entry -- see its own docstring).
PATTERNS_JSON ?= patterns.json
PATTERN_REGISTRY_OUT ?= .dv-harness/pattern_registry
REGRESSION_LIST ?= .dv-harness/regression.list

# Project's own top-level source tree, for the two dv_harness CLI/module invocations below
# (regression-monitor/regression-report) -- defaults to the directory this Makefile fragment is
# `include`d from, same convention PATTERNS_JSON/REGRESSION_LIST above already use.
PROJECT_ROOT ?= .

# Directory containing the REAL generated per-IP sim Makefile (the one with the actual `run`/
# `check`/`sim`/`regress` targets -- dv_harness/uvm_generator/templates/sim_scripts/Makefile is its
# template). Left unset by default on purpose: this fragment is a generic cross-protocol template
# and has no way to know a specific project's layout (SIM_ROOT_PATH/UVM_ROOT_PATH vary per project,
# per that Makefile's own `help:` target). Set it in the including project's top-level Makefile,
# e.g. `SIM_DIR := uvm/sim/scripts`, to make run-pattern/verify-pattern/regression real.
SIM_DIR ?=

add-pattern:
	@echo "Registering pattern: $(PATTERN) (regenerating registry from $(PATTERNS_JSON))"
	python3 tools/generate_pattern_registry.py --patterns $(PATTERNS_JSON) --out $(PATTERN_REGISTRY_OUT)

validate-pattern:
	python3 tools/verification_flow/pattern_registry_completeness_gate.py --registry $(PATTERN_REGISTRY_OUT)/registry.json

list-patterns:
	@cat $(PATTERN_REGISTRY_OUT)/pattern_list.txt

show-pattern:
	@grep "^$(PATTERN) " $(PATTERN_REGISTRY_OUT)/pattern_list.txt || echo "pattern not found: $(PATTERN)"

# Delegates to the real per-IP sim Makefile's own `run` target ("run PATTERN=<n> run one pattern,
# never builds -- what LSF jobs use", per that Makefile's help: text) once SIM_DIR points at it.
run-pattern:
	@$(if $(SIM_DIR),,$(error run-pattern needs SIM_DIR=<path to the generated sim environment's scripts dir>; it has no real simulator to invoke without it -- see the generated per-IP Makefile's own "run" target))
	@$(MAKE) -C $(SIM_DIR) run PATTERN=$(PATTERN) SEED=$(SEED) WAVE=$(WAVE) PA=$(PA) FSDB_START=$(FSDB_START) FSDB_STOP=$(FSDB_STOP)

# No single Layer-1 target verifies a pattern (confirmed against
# dv_harness/uvm_generator/templates/sim_scripts/Makefile's real target list) -- the closest real
# equivalent is a static check followed by a recorded dynamic run, so that is what this runs.
verify-pattern:
	@$(if $(SIM_DIR),,$(error verify-pattern needs SIM_DIR=<path to the generated sim environment's scripts dir>; there is no single Layer-1 "verify" target -- this chains its own real check + sim RECORD=1 once SIM_DIR is set))
	@$(MAKE) -C $(SIM_DIR) check
	@$(MAKE) -C $(SIM_DIR) sim PATTERN=$(PATTERN) SEED=$(SEED) WAVE=$(WAVE) PA=$(PA) RECORD=1

regression-add:
	python3 tools/regression_list_cli.py --list $(REGRESSION_LIST) record-verdict --pattern $(PATTERN) --passed

regression-remove:
	python3 tools/regression_list_cli.py --list $(REGRESSION_LIST) record-verdict --pattern $(PATTERN) --failed

# Delegates to the real per-IP sim Makefile's own `regress` target ("run every pattern in the
# suite -- JOBS=<n> locally, or LSF=1 on the farm", per that Makefile's help: text).
regression:
	@$(if $(SIM_DIR),,$(error regression needs SIM_DIR=<path to the generated sim environment's scripts dir>; it has no real regression to submit without it -- see the generated per-IP Makefile's own "regress" target))
	@$(MAKE) -C $(SIM_DIR) regress SUITE=$(SUITE) JOBS=$(JOBS) LSF=$(LSF)

# Real and generic (no SIM_DIR needed): reads the same .dv-harness/lsf/jobs/*.json job state this
# fragment's own REGRESSION_LIST bookkeeping lives next to, via dv_harness/cli.py's lsf-watch-status
# (background watcher liveness) and lsf (per-job state dump) subcommands.
regression-monitor:
	@echo "=== background job/log monitor status ==="
	@python3 -m dv_harness --project-root $(PROJECT_ROOT) lsf-watch-status
	@echo ""
	@echo "=== registered LSF job states (.dv-harness/lsf/jobs/*.json) ==="
	@python3 -m dv_harness --project-root $(PROJECT_ROOT) lsf

# Real and generic (no SIM_DIR needed): one-shot human-readable snapshot render of the same job
# state above, via dv_harness/regression_reporter.py's own CLI entry point.
regression-report:
	@python3 -m dv_harness.regression_reporter --project-root $(PROJECT_ROOT)
