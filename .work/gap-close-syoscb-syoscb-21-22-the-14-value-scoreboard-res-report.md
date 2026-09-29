# SYOSCB-21/22 gap close -- scoreboard result taxonomy + per-port visibility counters

**Status: DONE**

Commit `0850735` -- `syoscb(SYOSCB-21/22): 14-value result taxonomy + per-port
visibility counter shape`.

## What the audit found, re-verified before building

Both items were `PARTIALLY_WIRED`, and both findings held up:

- **SYOSCB-21**: no enum, no constant table, no partial subset under another
  name. `connectivity.GateStatus` (`dv_harness/connectivity.py:3267-3307`) is
  real but answers a different question -- one status per machine GATE RUN
  (PASS/FAIL/NOT_AVAILABLE/PENDING/NOT_YET_RUN), not one verdict per compared
  transaction. `tools/verification_flow/scoreboard_transaction_liveness_gate.py`
  carries plural gate-reason codes for a whole run's summary counters.
  `connectivity.SCOREBOARD_PLAN_FIELDS` (`connectivity.py:3991`) is a PLAN
  schema and carries no result field at all.
- **SYOSCB-22**: `amba_port_registry.AMBA_PORT_REGISTRY_FIELDS`
  (`dv_harness/amba_port_registry.py:83-103`) is the right join-keyed row and
  carries zero of the 13 counters; every one of its 19 columns is static
  topology/identity/config metadata.

## What was built

### `dv_harness/syoscb_result_taxonomy.py` (new, 745 lines)

A new module rather than an edit to `connectivity.py`, because the capability
is structurally new and `connectivity.py` is a 4511-line file other agents were
concurrently touching. It IMPORTS and composes the existing primitives; it
copies none of them.

**SYOSCB-21.** `ScoreboardResult` is a `str` Enum carrying the doc's fourteen
values in the doc's own order, each entry citing the master-prompt line
(5049-5062) it transcribes. `assert_result_taxonomy_is_disjoint_from_gate_status()`
runs at import and keeps the taxonomy and `GateStatus` from ever sharing a
token -- the "distinct from GateStatus" requirement as code rather than as a
comment.

`RESULT_TRIAGE` is SYOSCB-21's "Feed these into existing L5 failure-triage" as
a real routing table into `sim_log_analysis`'s OWN categories. Severity is
never stored here: `triage_for_result()` reads it from
`sim_log_analysis.severity_for_category()` at call time, so this module cannot
carry a severity the log-triage path disagrees with.

Both mappings are lossy, and every loss is recorded as data:

| Loss | Handling |
|---|---|
| L5 triage has no protocol-violation category | `BURST_ERROR` / `PROTOCOL_TRANSFORM_ERROR` route `COARSER` onto `scoreboard_mismatch` (HIGH), not onto `other` (LOW) -- routing a real fabric transform bug into the LOW bucket is how it would be buried |
| SYOSCB-22's counter list has no duplicate counter | `DUPLICATE_TRANSACTION` increments `unexpected_transaction_count`, marked `COARSER` -- the per-port view genuinely cannot tell the two apart, and that is the doc's own limitation, not a modelling choice |
| One `mismatches` counter for three mismatch axes | `ADDRESS_MISMATCH` / `RESPONSE_MISMATCH` marked `COARSER`; `DATA_MISMATCH` `EXACT` |
| An unclassifiable comparison verdict | `UNKNOWN` routes to `REQUIRED_HUMAN_INPUT` on BOTH sides (category and counter). `assert_unknown_is_never_silently_triaged()` proves it, and `coerce_result()` refuses a value outside the taxonomy rather than coercing it to UNKNOWN -- so "a real comparison produced something unclassifiable" stays distinguishable from "the caller passed a typo" |

`classify_result_counts()` makes the SYOSCB-21 -> SYOSCB-22 mapping executable
rather than only declared: it aggregates caller-supplied per-result counts into
the per-port counters, reports UNKNOWN's count separately as `unclassified`, and
returns the lossy mappings it applied. It produces no counts and cannot.

**SYOSCB-22.** `AMBA_PORT_VISIBILITY_COUNTER_FIELDS` is the doc's own thirteen
(lines 5074-5086), hung off the AMBA_PORT_REGISTRY row via
`attach_port_visibility_counters()` and joined on the registry's own `port_id`.
Two things make this more than a field list:

- **Feasibility is derived, never assumed** -- SYOSCB-22 says "expose where
  feasible", and three real inputs decide it. Per-protocol applicability comes
  from `amba_transaction_ir.ir_field_applicability()` (so `burst_count` is
  `NOT_APPLICABLE_FOR_PROTOCOL` on APB4 and the response counters are on
  AXI4-Stream) -- no AMBA signal name is typed in the new module, and a test
  holds it against `connectivity.ALL_AMBA_SIGNAL_NAMES`. `vip_mode ==
  NO_VIP_PLANNED` blocks every counter. `scoreboard_channel ==
  REQUIRED_HUMAN_INPUT` blocks only the compare-derived counters, which is why
  `COUNTER_SOURCE` splits PORT_MONITOR from SCOREBOARD_COMPARE: a port with a
  monitor and no ingress keeps its real monitor observability instead of
  reporting nothing.
- **No counter starts at zero.** A `0` is a measurement, and no transaction has
  run (nor can one before SYOSCB-34). Every counter starts at
  `COUNTER_NOT_OBSERVED`, a string, so a consumer summing counters gets a type
  error rather than a plausible-looking zero total.
  `assert_counters_unobserved()` refuses any numeric value or unrecognised
  status. `unresolved_port_visibility_counters()` reports only CLOSABLE gaps --
  a NOT_APPLICABLE counter is a property of the bus, not a work item.

`render_result_taxonomy_report()` self-checks with both
`amba_fabric_discovery.assert_no_bind_statement()` and
`syoscb_source_audit.assert_no_emittable_sv()`, per the convention every AMBA /
SYOSCB planning artifact in this repo follows.

### `dv_harness/sim_log_analysis.py` (+23 / -1)

Exports `TRIAGE_CATEGORIES` (derived from `_CATEGORY_SEVERITY`, so it cannot
drift) and `severity_for_category()`, and refactors `classify_signatures()` onto
the same accessor. The alternative -- reading the private `_CATEGORY_SEVERITY`
across module boundaries, or re-typing the map -- is exactly how one severity
scale becomes two that disagree.

## Tests

`dv_harness_tests/test_syoscb_result_taxonomy.py`, 50 tests, three fixture
kinds:

- the REAL master prompt, so the fourteen values and the thirteen counter nouns
  are held line-by-line against `...Research.md:5049-5062` and `:5074-5086`;
- the REAL verible-parsed AMBA4 SoC fixture carried through a real
  `build_amba_port_registry()`;
- synthetic registry rows (reusing `test_amba_route_transform_predictor`'s own
  `master()`/`slave()` helpers) for the feasibility cases the real fixture
  cannot produce.

Genuinely-missing-evidence cases, not only happy paths:
`test_a_port_with_no_scoreboard_channel_keeps_its_monitor_counters`,
`test_a_port_with_no_vip_planned_has_no_feasible_counter_at_all`,
`test_an_unresolved_protocol_is_undecided_applicability_not_not_applicable`
(and `test_no_vip_planned_outranks_an_unresolved_protocol` for the precedence
when both are true), `test_unknown_reaches_a_human_rather_than_a_severity_bucket`,
`test_a_value_outside_the_taxonomy_is_refused_rather_than_coerced_to_unknown`,
`test_a_numeric_counter_value_is_refused_as_an_observed_run`,
`test_the_report_renders_with_no_registry_at_all`.

**One-line test summary**: `50 passed` (new suite); `403 passed` across
`test_syoscb_result_taxonomy / test_sim_log_analysis / test_amba_port_registry /
test_amba_transaction_ir / test_syoscb_compare_policy / test_syoscb_topology_plan /
test_amba_route_transform_predictor / test_syoscb_source_audit`; `99 passed`
across the downstream `sim_log_analysis` consumers (`test_evidence_db`,
`test_vip_distill`, `test_regression_reporter`, `test_escalation_notify`).

## Hard constraints honored

- Nothing was copied, vendored or written from `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`.
  The new module cites that path only in its own Phase-1 scope note; no file
  under it was read for this step and none was written anywhere.
- No SystemVerilog is emitted. The report is checked by
  `assert_no_bind_statement()` and `assert_no_emittable_sv()` on every render.
- No VCS/UVM build or simulation was invoked. Every counter reads a real
  not-observed sentinel precisely because no run happened.
- No new agent was added (SYOSCB-32). `.claude/agents/` is untouched.
- Hand-scoped staging: `git diff -- dv_harness/sim_log_analysis.py` >
  patch, `git apply --cached --check` then `--cached`, plus explicit
  `git add --` of the two new files. `git diff --cached --name-only` confirmed
  exactly three paths before committing; a concurrent agent's SYS-15..17 work
  (`d87c3b8`) was neither swept in nor disturbed.

## Not done here (out of this step's scope)

SYOSCB-23's second half (calling
`system_resource_inventory.apply_active_driver_conflict_rule()` from the VIP-plan
path before an ACTIVE row is accepted) and SYOSCB-24's
KEEP/ENHANCE/REUSE/REPLACE/EXPERIMENT/REJECT disposition layer over
`amba_scoreboard_env.ScoreboardEnvAnalysis` are both still open. They are named
in this workflow's own audit and belong to the next steps in the sequence, not
to SYOSCB-21/22.
