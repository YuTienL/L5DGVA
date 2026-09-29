# SYOSCB-12/13 gap close -- AMBA Route/Transform Predictor + Address Map Evidence

**Status: DONE**

Scope: Phase-1 PLANNING machinery only (SYOSCB-33). Nothing was copied out of
`D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`, no SystemVerilog was written, and no
VCS/UVM build was invoked.

## What the audit said, and what changed

| Req | Audit verdict | After this change |
|---|---|---|
| SYOSCB-12 | PARTIALLY_WIRED -- static address-decode / connectivity-legality / ID-width-sizing existed; per-route address translation, ID remap, width conversion, burst split/merge, bridge behavior, response behavior and ordering-domain *computation* were NEVER_BUILT | All ten responsibilities answered per route by `dv_harness/amba_route_transform_predictor.py`, structurally, on top of the existing primitives |
| SYOSCB-13 | WIRED_AND_FIRING, with a named minor gap: no *named* ingestion path for "fabric generated configuration" / "firmware headers" | Re-confirmed by running the real `verify_address_map()` unchanged; the naming gap is closed as DATA (`ADDRESS_MAP_EVIDENCE_TYPES`), and the join onto traced topology plus SYOSCB-13's "supports but does not replace" rule are now enforced code |

## New files

* `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/amba_route_transform_predictor.py`
* `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_amba_route_transform_predictor.py`

No existing file was modified, so no shared-file patch was needed.

## SYOSCB-12: what is now computed, and from what

`predict_routes()` returns one prediction per (master, slave) pair with all ten
of SYOSCB-12's responsibilities answered. Every answer carries one of five
statuses and a list of citable evidence strings; `assert_predictions_complete()`
refuses a prediction missing a responsibility, carrying an eleventh, or stating
no basis.

Reused, never re-derived:

* route enumeration and legality -- `amba_port_registry.project_to_fabric_topology()`,
  i.e. `amba_fabric_generator.build_scoreboard_matrix()`. An UNRESOLVED_PAIR still
  raises out of that function; the predictor does not soften the evidence gate.
* address decode -- `amba_fabric_generator.compute_address_regions()`.
* fabric-side ID width -- `amba_fabric_generator.compute_id_width()`.
* "does this protocol have a burst/id/response at all" --
  `amba_transaction_ir.ir_field_applicability()`, which derives it from
  `connectivity.py`'s spec-fixed signal sets. No AMBA signal name appears in the
  new module at all, and a test asserts that.
* the ordering vocabulary -- `syoscb_source_audit.ORDERING_IN_ORDER` /
  `ORDERING_OUT_OF_ORDER`, the same values that module maps onto the real
  `cl_syoscb_compare_{io,iop,ooo}` classes.

Genuinely new (the detection layer):

* `detect_width_conversion()` -- DOWNSIZE/UPSIZE + integer ratio from the two
  rows' `data_width`; a non-integer ratio goes to a human rather than becoming a
  computed fraction.
* `detect_burst_split_merge()` -- a destination with no burst concept forces
  SPLIT_TO_SINGLE_TRANSFERS; otherwise the beat count follows the width ratio.
* `detect_id_remap()` -- turns `compute_id_width()`'s W_out into the per-route
  statement it never made: how many master-index bits are prefixed onto THIS
  master's id, or whether a narrower slave port forces a reissue.
* `detect_bridge_behavior()` -- family change vs. sub-protocol change.
* `detect_expected_response()` -- response-signal set comparison plus any
  declared DECODE_ERROR region.
* `detect_ordering_domain()` -- the domain KEY (per-route, or per-route-and-id)
  and the route's ordering expectation. The reorder-window DEPTH is never
  derived; it is `REQUIRED_HUMAN_INPUT` beside the domain, always.

**Honest refusals, tested:** `address_translation` is `REQUIRED_HUMAN_INPUT` on
every route unless a caller supplies real evidence -- whether an interconnect
presents a slave the full system address or a base-relative offset is a fabric
CONFIGURATION fact the topology cannot imply, and computing one would be
SYOSCB-12's own forbidden routing guess. Unknown widths, unresolved protocols and
slaves with no address region all refuse the same way rather than defaulting.
`assert_no_route_guessed()` hard-blocks a DERIVED answer (the burst expectation)
that outlived its own `REQUIRED_HUMAN_INPUT` input.

`RUNTIME_PREDICTION_PHASE_2` is kept distinct from `REQUIRED_HUMAN_INPUT`: "the
shape is settled, the per-transaction value needs approval" and "nobody
established this fact" are the two sides of SYOSCB-33/34's gate.

## SYOSCB-13: re-confirmed and joined

`cross_check_address_map_evidence()` calls the real
`address_map_verifier.verify_address_map()` whole -- its decoder/histogram/doc
method, its ZERO_ACCESS_HISTOGRAM refusal, its DISAGREES recording and its
optional question-queue escalation are reused, not reimplemented (a test proves
the zero-access refusal still fires through the new entry point). On top it adds
only the join SYOSCB-13 asks for: which traced slave each verified base belongs
to.

* `ADDRESS_MAP_EVIDENCE_TYPES` maps all seven of SYOSCB-13's evidence types onto
  the `verify_address_map()` argument they are supplied through and onto a real
  `source_authority.AUTHORITY_ORDER` level (checked at import). "Prefer direct
  implementation evidence when sources conflict" is then a rank comparison, and
  a test asserts the decoder outranks every document-slot evidence type. The two
  types with no purpose-built parser are recorded as `GENERIC_DOC_SLOT` data
  rather than left for a reader to discover by finding no parser.
* `assert_address_map_does_not_replace_topology()` makes SYOSCB-13's last line
  checkable: an address-map instance naming no traced endpoint is reported as
  `ADDRESS_MAP_INSTANCE_NOT_IN_TOPOLOGY` and never becomes a slave.
* `address_map_conflicts()` resolves a doc disagreement through the existing
  `doc_disagreement_conflict()` / `source_authority` path -- the decoder wins,
  and the verified base is unchanged.

## Feeding the existing scoreboard-plan schema

`propose_scoreboard_plan_fields()` returns PROPOSALS for exactly three of
`connectivity.SCOREBOARD_PLAN_FIELDS` (`endpoint_pairs`, `ordering`,
`transformation_rules`), each with `confirmed: False` and its basis.
`assert_plan_proposals_are_not_confirmations()` refuses one that marks itself
confirmed. `generate_scoreboard_entry()`'s "NEVER computes a default for ANY of
the nine fields" contract is untouched -- the predictor feeds the row-lock gate,
it does not answer it. `PREDICTOR_INFORMED_PLAN_FIELDS` is asserted at import to
be a subset of the real schema, so no second scoreboard-plan vocabulary exists.

## Phase-1 boundary

`render_route_transform_report()` self-checks through
`syoscb_source_audit.assert_no_emittable_sv()` and
`amba_fabric_discovery.assert_no_bind_statement()`, and tests apply both gates to
the module's own source as well. Tests also assert the module contains no
`D:/DV/Scoreboard` path and no `uvm_syoscb-1.0.2.4` string.

## Tests

`python -m pytest dv_harness_tests/test_amba_route_transform_predictor.py
dv_harness_tests/test_amba_transaction_ir.py
dv_harness_tests/test_amba_port_registry.py
dv_harness_tests/test_amba_fabric_generator.py
dv_harness_tests/test_address_map_verifier.py
dv_harness_tests/test_syoscb_source_audit.py
dv_harness_tests/test_amba_vip_bind_plan.py
dv_harness_tests/test_source_authority.py -q` -- see the commit message for the
recorded pass count. 90 of those are the new file's own, split between synthetic
`AMBA_PORT_REGISTRY` rows and the REAL verible-parsed AMBA4 SoC fixture, whose
`u_ddr` port genuinely has no established `data_width` -- so the missing-evidence
path is proven against real discovery output, not only a hand-built dict.

## What is still NOT_AVAILABLE (Phase-2 only)

* Any per-transaction prediction against real traffic: needs a real adapter and a
  live run, both behind SYOSCB-34's approval.
* Address translation VALUES: need the fabric's own generated configuration,
  which no artifact in this repo carries.
* SYOSCB-14/15/16's SyoSil producer/queue configuration layer: still
  `NEVER_BUILT`, unchanged by this pass and out of its scope.
