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
# tools/regression_list_cli.py). run-pattern/verify-pattern/regression/regression-monitor/
# regression-report remain project-specific stubs -- real VCS/LSF/Verdi invocation is not something
# a generic cross-protocol template can know in advance (see .claude/skills/USB/usb-regression/
# SKILL.md for a worked real-project Makefile with this logic filled in).

.PHONY: add-pattern validate-pattern list-patterns show-pattern run-pattern verify-pattern \
        regression-add regression-remove regression regression-monitor regression-report

WAVE ?= 0
PA ?= 0
FSDB_START ?= 0
FSDB_STOP ?= simulation_end
TIMEOUT ?=

# Project-maintained source of truth: append/edit pattern entries here, then `make add-pattern`
# regenerates and validates the registry from it (pattern_registry_generator.build_registry() takes
# the full pattern list, not one incremental entry -- see its own docstring).
PATTERNS_JSON ?= patterns.json
PATTERN_REGISTRY_OUT ?= .dv-harness/pattern_registry
REGRESSION_LIST ?= .dv-harness/regression.list

add-pattern:
	@echo "Registering pattern: $(PATTERN) (regenerating registry from $(PATTERNS_JSON))"
	python3 tools/generate_pattern_registry.py --patterns $(PATTERNS_JSON) --out $(PATTERN_REGISTRY_OUT)

validate-pattern:
	python3 tools/verification_flow/pattern_registry_completeness_gate.py --registry $(PATTERN_REGISTRY_OUT)/registry.json

list-patterns:
	@cat $(PATTERN_REGISTRY_OUT)/pattern_list.txt

show-pattern:
	@grep "^$(PATTERN) " $(PATTERN_REGISTRY_OUT)/pattern_list.txt || echo "pattern not found: $(PATTERN)"

run-pattern:
	@echo "Run $(PATTERN) WAVE=$(WAVE) PA=$(PA) FSDB_START=$(FSDB_START) FSDB_STOP=$(FSDB_STOP) TIMEOUT=$(TIMEOUT)"
	@echo "-- project-specific: wire to the real VCS/simulator invocation (see usb-regression/SKILL.md)"

verify-pattern:
	@echo "Verify $(PATTERN) with formal project flow"
	@echo "-- project-specific: not modeled generically"

regression-add:
	python3 tools/regression_list_cli.py --list $(REGRESSION_LIST) record-verdict --pattern $(PATTERN) --passed

regression-remove:
	python3 tools/regression_list_cli.py --list $(REGRESSION_LIST) record-verdict --pattern $(PATTERN) --failed

regression:
	@echo "Run LSF regression"
	@echo "-- project-specific: wire to dv_harness/lsf_client.py bsub_submit (see CORE/lsf-regression skill)"

regression-monitor:
	@echo "Monitor LSF regression"
	@echo "-- project-specific: wire to dv_harness/lsf_client.py bjobs_query"

regression-report:
	@echo "Generate regression report"
	@echo "-- project-specific: wire to dv_harness/regression_reporter.py"
