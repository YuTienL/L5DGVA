# SYOSCB-14/15/16 gap close — dynamic scoreboard topology / producer-queue mapping planner

**Result: DONE**

**Test summary**: `python -m pytest dv_harness_tests/test_syoscb_topology_plan.py
dv_harness_tests/test_amba_route_transform_predictor.py dv_harness_tests/test_amba_port_registry.py
dv_harness_tests/test_amba_transaction_ir.py dv_harness_tests/test_syoscb_source_audit.py
dv_harness_tests/test_amba_fabric_generator.py dv_harness_tests/test_address_map_verifier.py -q`
→ **305 passed in 138.04s**, of which 39 are the new module's own tests.

Commit: `4cdc913 syoscb(SYOSCB-14/15/16): SyoSil producer/queue/route plan from the real
AMBA_PORT_REGISTRY` — exactly two files, both new.

---

## What the audit said, and what was built

The audit's verdicts were `SYOSCB-14 PARTIALLY_WIRED` (stages 1–2 real and tested, stages 3–4
never built) and `SYOSCB-15` / `SYOSCB-16` `NEVER_BUILT` with the real
`cl_syoscb_cfg::set_producer()` / `set_queues()` API confirmed API-compatible with a
registry-derived mapping. That is the "genuinely structurally new capability" case, so a new,
clearly-scoped module that IMPORTS and composes the existing primitives is correct — not an
extension of `amba_port_registry.py` (whose job is the 19-column registry) and not a copy of any
existing logic.

**New**: `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/syoscb_topology_plan.py` (981 lines)
**New**: `D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness_tests/test_syoscb_topology_plan.py` (704 lines)

No existing file was modified. `connectivity.py`, `amba_port_registry.py`,
`amba_fabric_discovery.py`, `amba_scoreboard_env.py`, `amba_route_transform_predictor.py` and
`CLAUDE.md` were checked with `git status` before and after and are untouched; a concurrent
agent's staged `system_resource_registry` work was preserved by committing with a pathspec
(`git commit -F <msg> -- <two paths>`) rather than a broad `git add`.

## Reuse, not reimplementation

The module re-derives nothing. Every routing/ordering/transform fact is read off
`amba_route_transform_predictor.predict_routes()`, which itself runs
`amba_port_registry.project_to_fabric_topology()` → `amba_fabric_generator.build_scoreboard_matrix()`
/ `compute_address_regions()`. Imports are: `predict_routes` output shape and its
`ORDERING_DOMAIN_*` / `ROUTE_LEGAL` / `ROUTE_WAIVED` / `TRANSFORM_PREDICTED_FROM_TOPOLOGY`
vocabulary, `connectivity.REQUIRED_HUMAN_INPUT` and `render_markdown_table`,
`syoscb_source_audit.assert_no_emittable_sv` and `audit_syoscb_source`,
`amba_fabric_discovery.assert_no_bind_statement`, and `amba_port_registry.PortRegistryError` as the
error base. `test_the_module_reuses_the_predictors_vocabulary_rather_than_copying_it` asserts the
re-exported constants are the predictor's own objects, so no second ordering-domain or
route-status vocabulary can appear.

## SYOSCB-14 — the plan collapses instead of multiplying

One scoreboard per **(destination class, ordering domain)**, never one per route. Three AXI4
masters into one DDR produce 1 scoreboard, 2 queues and 3 producers — not 3 scoreboards or 6
queues. The plan's `scaling` block states the naive one-scoreboard-per-route figure it is measured
against, and its `planned_subscriber_count` is `cl_syoscb::build_phase()`'s own
(producer, queue-in-its-list) loop arithmetic (`src/cl_syoscb.svh:114-125`), not an estimate.
Adding a fourth master changes the producer count and nothing else — tested.

`assert_not_one_scoreboard_per_route()` refuses a plan whose scoreboard count equals its route
count **while two routes share a key**; a 1-master-per-destination topology legitimately is
one-per-route and passes (both cases tested).

## SYOSCB-15 — master endpoint → producer

A producer is a bare string (`set_producer(string producer, queue_names[])`, verified against
source), so the mapping's whole content is which queues it may feed. Names derive from the
registry's `port_id` column, which AMBA-22 already refuses to let be a generic `master0`.
`assert_producer_names_derive_from_registry()` refuses a producer no registry row backs.

A master always feeds its group's master-side queue (its own monitor observes its own
transactions). It feeds the **slave-side** queue only where that group's producer attribution
resolved — see the refusal below.

## SYOSCB-16 — destination / ordering domain → queue

Two queues per group (master-side observation, slave-side observation), named for the destination
class and ordering domain, never for a port; the master-side queue is proposed as primary because
`cl_syoscb_compare_base::get_primary_queue_name()` selects the queue the algorithm walks, and
walking the stimulus side makes an unmatched primary item "a transaction that never arrived".

The destination **class** is an INPUT, not a derivation — whether `u_ddr` and `u_sram` are one
memory class is a project decision nobody discovered. Supplied, they collapse into one scoreboard
(tested); unsupplied, each traced destination is its own class, recorded as
`TRACED_DESTINATION_ENDPOINT_FALLBACK` and raised as a `DESTINATION_CLASS_NOT_SUPPLIED` open
question quoting the doc's own "Do not blindly create one queue per physical port".

`assert_queues_are_not_per_physical_port()` re-derives the grouping from the plan's own route
index and refuses a fragmented key — a real recomputation with power over a reloaded or
hand-edited plan (tested against a deliberately split plan).

## The API is cited from source, never assumed

SYOSCB-15's own instruction ("verify exact SyoSil producer semantics/API from source before
generation. Do not hardcode API calls from assumptions") is implemented as data.
`SYOSIL_CFG_API` carries 8 entries with class, method, exact argument string and `file:line`;
`assert_cited_syosil_api_matches_source()` holds every one against a real read-only
`audit_syoscb_source('D:/DV/Scoreboard/uvm_syoscb-1.0.2.4')` pass. Both halves are tested: the real
tree matches bit-for-bit, and a synthetic drifted audit produces `SIGNATURE_DRIFTED` /
`METHOD_NOT_FOUND` / `CLASS_NOT_FOUND` and raises.

Three preconditions the real API enforces silently at runtime are therefore checkable in Phase 1:

| Upstream refusal | Cited at | Enforced by |
|---|---|---|
| duplicate queue name in a producer list | `src/cl_syoscb_cfg.svh:154-160` | `assert_producer_queue_lists_have_no_duplicates()` |
| queue name that was never declared | `src/cl_syoscb_cfg.svh:163-166` | `assert_every_producer_queue_is_declared()` |
| primary queue that does not exist | `src/cl_syoscb_cfg.svh:206-209` | same declaration rule |

The plan calls `set_queues()` and never `set_queue()`, because `build_phase()` constructs the queue
objects and registers the handles itself (`src/cl_syoscb.svh:89-95`) — a decision made by reading
the source, not by guessing which setter to use.

## What it deliberately refuses to decide (the missing-evidence paths)

Four, all tested as real behavior rather than as a happy path:

1. **Slave-side producer attribution** — `cl_syoscb_compare_iop` matches two items only when their
   producers are equal (`src/cl_syoscb_compare_iop.svh:119`). Two id-less APB4 masters into one
   APB4 slave therefore cannot be attributed from the topology: the group is reported
   `REQUIRED_HUMAN_INPUT`, listed in `scoreboards_blocked_on_producer_attribution`, the slave-side
   queue is **withheld** from both producers (carried in `withheld_queues` with the evidence), and
   `syosil_configuration_calls()` proposes **no call at all** for that group. A single-master route
   is attributable with no id at all (`ATTRIBUTION_SINGLE_MASTER`), and AXI4 masters with a
   predicted fabric id are attributable by it (`ATTRIBUTION_BY_FABRIC_ID`) — all three tested.
2. **Unresolved protocol** → the ordering domain is undecidable, so the route is excluded as
   `ORDERING_DOMAIN_UNRESOLVED` with its evidence, its master becomes no producer, and it appears
   in the open questions rather than vanishing. `assert_plan_complete()` refuses a route that is
   neither grouped nor excluded.
3. **Waived route** → no queue (traffic on it is a finding, not a transaction to match), still
   reported.
4. **Reorder-window depth** → stays `REQUIRED_HUMAN_INPUT` on an out-of-order route, exactly as
   SYOSCB-12 left it; an in-order APB route carries a real derived depth of 0. Filling it here
   would be answering on the predictor's behalf.

The **compare algorithm** is `DEFERRED_TO_SYOSCB_17` on every group and is never derived from the
ordering domain — the domain is the key items are grouped by, the algorithm is what runs inside a
group, and conflating them is how an out-of-order route silently gets an in-order comparison.

## Hard-constraint compliance

- **Nothing copied from `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`.** The tree was read read-only for
  signatures and line numbers. `test_the_module_carries_no_upstream_source_body` checks the module
  text carries no `endfunction` / `endclass` / `` `uvm_info `` / `this.producers[`, and the existing
  `test_real_source_is_not_vendored_into_this_repository` (in the suite above) passed.
- **No SystemVerilog is emitted.** A configuration call is a `{api_id, arguments, citation}` record
  with a dict `arguments`, never a formatted statement — asserted in
  `test_the_configuration_calls_are_structured_records_not_systemverilog`. Every rendered artifact
  passes both `assert_no_emittable_sv()` and `assert_no_bind_statement()`, on the synthetic and the
  real fixture.
- **No VCS/UVM build was invoked or simulated.** The only real external tool used is
  `verible-verilog-syntax`, already the existing fixture's parser.
- **No scoreboard super-agent** (SYOSCB-32): no file under `.claude/agents/` was added or touched.

## Verdict after this change

| Req | Before | After |
|---|---|---|
| SYOSCB-14 | PARTIALLY_WIRED (stages 3–4 missing) | **WIRED_AND_FIRING** — all four stages real, tested end-to-end from real RTL through a real registry to a real config plan |
| SYOSCB-15 | NEVER_BUILT | **WIRED_AND_FIRING** — `map_masters_to_producers()`, names from `port_id`, API verified against source |
| SYOSCB-16 | NEVER_BUILT | **WIRED_AND_FIRING** — `plan_queues()` keyed on (destination class, ordering domain), fallback reported as a question |

Phase-2 items remain Phase-2 (SYOSCB-33/34): the real `cl_syoscb_cfg` configuration code, the
vendored source, and any compile against it.
