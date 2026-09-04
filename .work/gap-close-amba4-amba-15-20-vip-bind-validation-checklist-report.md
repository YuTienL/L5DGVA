# AMBA-15..20 gap close: VIP bind validation checklist, bind matrix, unresolved table, topology summary/tree, VIP instance plan

**Status: DONE**

Scope: AMBA-15 through AMBA-20 of the master prompt
(`DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_AMBA4_CCE_Research.md`,
lines 3956-4041). Discovery / planning / reporting only, per the document's own
AMBA-30 (mandatory human review gate) and AMBA-31 (implementation only after
explicit approval): **no bind statement is written anywhere**, and that is
asserted in code, not just claimed — see "AMBA-30/31 gate" below.

---

## What the audit found, and what was actually built

The audit for this scope ran before AMBA-7..14 landed (commit `35614ce`,
`dv_harness/amba_fabric_discovery.py`), so its verdicts were measured against a
tree with no endpoint tracer. Re-verified against the current tree, its
substantive findings held:

| Req | Audit verdict | What was missing | What was built |
|---|---|---|---|
| AMBA-15 | PARTIALLY_WIRED | no function assembles the 13 points; clock/reset had no evidence source at any layer; widths/parameterization had real but unwired primitives | `validate_vip_bind_location()` + the clock/reset and per-signal-role width vocabulary |
| AMBA-16 | PARTIALLY_WIRED | no 12-column matrix, no parameterized renderer | `build_fabric_vip_bind_matrix()` / `render_fabric_vip_bind_matrix()` |
| AMBA-17 | NEVER_BUILT | no unresolved-port table type at all; no `Missing Evidence` / `Next-Best-Action` field anywhere | `build_unresolved_fabric_port_table()` + `NEXT_BEST_ACTION_BY_STATUS` |
| AMBA-18 | DORMANT + NEVER_BUILT | count arithmetic uncalled; 6 of 10 protocols unclassifiable; no READY/PARTIAL/BLOCKED/UNKNOWN vocabulary | `build_amba_topology_summary()` reusing the AMBA-6 table; `BIND_READINESS_*` |
| AMBA-19 | PARTIALLY_WIRED | mermaid only, no `├──` text tree; no protocol/role labels on nodes | `render_topology_tree()` |
| AMBA-20 | PARTIALLY_WIRED | `VipInstanceRecord` carries 3 of 11 columns; no renderer | `build_vip_instance_plan()` + `assert_vip_plan_defaults_passive()` |

Two audit findings were **superseded** by work that landed between the audit and
this step, and were re-checked rather than assumed:

* The audit's "6 of 10 AMBA protocols have no signal set" is **no longer true**.
  Commit `be19720` (AMBA-4) added `AMBA4_PROTOCOLS` with all ten
  (`connectivity.py:735-743`) and `classify_amba_protocol()` resolves them from
  real signal evidence. No fingerprint work was needed here, and none was done —
  AMBA-18's per-protocol counts read that classifier's verdicts.
* The audit's "no generic parameterized table renderer exists anywhere in the
  repo" **was** still true, and is now closed by one function rather than three
  more hand-rolled loops.

---

## Files changed

### `dv_harness/connectivity.py` (+257/-1)

The AMBA-15 **evidence vocabulary**, placed here because this module is already
the single owner of "what an AMBA signal is called" and a second signal table
elsewhere is exactly the duplication this project has been burned by:

* `AXI_USER_SIDEBAND_SIGNALS` (`AWUSER`/`WUSER`/`BUSER`/`ARUSER`/`RUSER`), added
  to the `_ALL_AMBA_SIGNALS` union. Not a discriminator — their presence
  distinguishes nothing — but a port whose token is unknown to the union is not
  grouped into its interface's bundle at all, so without this AMBA-15 point 11
  (USER widths) could never read one.
* `AMBA_PROTOCOL_FAMILY` — the ten protocols to their `AHB`/`APB`/`AXI_MM`/
  `AXI_STREAM` family, so a bare protocol string (e.g. one re-loaded from a
  persisted artifact) resolves the same way a live classification's `.family`
  does.
* `AMBA_FAMILY_CLOCK_SIGNALS` / `AMBA_FAMILY_RESET_SIGNALS` (ACLK/ARESETn,
  HCLK/HRESETn, PCLK/PRESETn) plus a lower-tier `GENERIC_*` fallback, and
  `find_amba_clock_reset_ports()`. Four evidence tiers, best-first, first
  non-empty tier decides; **more than one candidate in the deciding tier is
  AMBIGUOUS, never a pick** — choosing between `ACLK` and `ACLK2` by alphabet
  would be exactly the invented fact AMBA-15's "use UNKNOWN where not provable"
  forbids. Clock/reset carry no AMBA data-signal token, so
  `group_ports_into_amba_bundles()` deliberately excludes them from every
  bundle; this reads the whole instance's port list instead.
* `AMBA_SIGNAL_ROLE_TOKENS` / `AMBA_PROTOCOL_SIGNAL_ROLES` / `amba_signal_role()`
  — which signal's width IS the address/data/ID/USER width (`AWLEN` is
  address-channel signalling and is deliberately absent), and which roles each
  protocol HAS. That second table is what makes NOT_APPLICABLE a *derived*
  verdict: AXI4-Lite has no ID width by definition, AXI4-Stream has no address,
  and reporting UNKNOWN for those would send a reviewer looking for a fact that
  does not exist.
* `render_markdown_table(columns, rows, aligns=, empty_note=)` — the repo's one
  parameterized markdown table renderer. `render_matrix_table()` is untouched:
  it renders a fixed-width aligned block, not markdown, and is what
  `emit_connectivity_artifacts()` already writes.

### `dv_harness/amba_fabric_discovery.py` (+1170)

Two small additions to the existing netlist layer, then the AMBA-15..20 block:

* `ModuleDef` / `ElaboratedInstance` now carry `port_data_types` (verible's own
  raw `data_type` text, kept unparsed) and `parameters`. Both are empty for a
  black box — an instantiation names ports and nets, never declared types or
  parameters — and that emptiness is the real reason a black box's widths report
  UNKNOWN, distinct from a parsed module that genuinely declares no parameters.
* **AMBA-15**: `validate_vip_bind_location()` answers all 13 points, always, in
  the doc's own order, by iterating `BIND_LOCATION_CHECK_POINTS` — a check
  cannot be silently skipped and a renderer cannot omit a row. Four outcomes:
  `KNOWN` / `UNKNOWN` / `NOT_APPLICABLE` / `FAILED`. `FAILED` is separate from
  `UNKNOWN` because a bind location whose hierarchy does not exist is disproven,
  not unproven, and must not average out to PARTIAL.
  Width parsing is `phy_boundary.parse_port_width()` **imported, not
  re-implemented** (the audit's own recommendation #2): it already answers None
  rather than a defaulted 1 for a parameterized `[DW-1:0]`, and a second width
  parser would be a second chance to disagree about that. Two ports of the same
  role that disagree on width is UNKNOWN with both named — a fabric port whose
  read and write address widths differ is a real finding, not something to
  silently pick one of.
* **Readiness** (`BIND_READINESS_READY/PARTIAL/BLOCKED/UNKNOWN`) is deliberately
  a separate vocabulary from `BindTier`, for the reason the audit identified: a
  tier is how much *confidence* the evidence supports, readiness is how much of
  the required evidence exists at all. A T2 structural match with an unknown
  clock is high-confidence and not ready, and one vocabulary cannot say both.
* **AMBA-16**: one row per fabric port (every traced port appears, including one
  that resolved nothing), child rows per branch for MULTIPLE_SOURCE/
  MULTIPLE_DESTINATION, and one AMBA-11 **VIP-B** subordinate row per protocol
  bridge crossed, whose protocol is the bridge's own independent classification
  — never inherited from the upstream side. A multi-branch parent is capped
  below READY however clean its branches are: AMBA-12/13 leave the choice of
  which branches to observe to a human, so the port carries an open decision.
* **AMBA-17**: mandatory even when empty (the renderer says "none — every traced
  fabric port resolved" rather than printing a bare header, because "nothing
  unresolved" and "this table was never produced" must not look alike). Covers
  two populations: an unresolved AMBA-14 trace, and a resolved trace whose bind
  location failed AMBA-15. `NEXT_BEST_ACTION_BY_STATUS` is keyed on the
  termination state, so two ports that failed for the same reason cannot get
  differently-worded advice.
* **AMBA-18**: the per-protocol counts are
  `connectivity.build_protocol_interface_count_table()`'s — the AMBA-6 table,
  **reused rather than recomputed**, so AMBA-6 and AMBA-18 can never report
  different totals for the same fabric. Readiness is tallied over parent rows
  only, so a multiple-destination port counts once.
* **AMBA-19**: the doc's literal ASCII tree. `connectivity.render_hierarchy_diagram()`'s
  mermaid flowchart is kept — it is the right artifact for a rendered document —
  and this is the one the doc mandates and the one that survives a plain-text
  review comment.
* **AMBA-20**: eleven columns, `PASSIVE_MONITOR` / `passive` / `MONITOR`
  everywhere by construction. `assert_vip_plan_defaults_passive()` **enforces**
  "do not default ACTIVE unless verification architecture explicitly requires
  driving": an ACTIVE row must name its `driving_requirement` or is refused, and
  the `active_passive` vocabulary check is `connectivity.assert_active_passive_vocabulary()`,
  reused so a plan cannot carry a third value that drops out of every count.
  `Scoreboard Connection` is `REQUIRED_HUMAN_INPUT` by construction — which
  scoreboard a monitor feeds is AMBA-21/25's output, computed by
  `amba_fabric_generator.build_scoreboard_matrix()` from an *approved* topology,
  and guessing it here would pre-empt the review gate.
* `build_vip_bind_plan()` computes all five artifacts from ONE trace set and ONE
  set of validations, so the matrix, unresolved table, summary, tree and VIP
  plan cannot disagree with each other about a port.

### Reuse actually taken (not just cited)

`classify_amba_protocol` / `determine_fabric_interface_roles` / `classify_bind_tier`
/ `amba_structural_match` / `build_protocol_interface_count_table` /
`render_protocol_interface_count_table` / `assert_active_passive_vocabulary` /
`VipInstanceRecord` / `check_vip_instance_count_matches_active_interfaces` /
`REQUIRED_HUMAN_INPUT` / `PASSIVE_INTERFACE` / `parse_bind_line` from
`connectivity.py`; `parse_port_width` from `phy_boundary.py`; `RowLockStore`
used with **zero changes** (it is already generic over `(row_id, dict)` — the
audit's finding #4, confirmed by a test that really locks a matrix row).
`discovered_topology_ids()`'s masters/slaves shape is unchanged, so the
artifacts stay schema-compatible with
`tools/verification_flow/fabric_topology_completeness_gate.py` rather than
competing with it.

---

## AMBA-30 / AMBA-31 gate

No `bind` statement is written by any of this. Enforced, not asserted:
`assert_no_bind_statement()` runs every line through
`connectivity.parse_bind_line()` — the repo's one definition of what a bind
statement is, so this cannot drift from the grep that finds real binds in real
source — and `render_vip_bind_plan_report()` runs it on its own finished output
before returning. The tree prints `VIP_BIND_CANDIDATE = <hierarchy>`, which that
parser does not recognise as a bind. A test asserts the same of the module's own
source file, of every rendered artifact, and (negatively) that the assertion
really fires on a real bind line.

The synthetic RTL fixture lives only inside the test file and contains no bind
construct.

---

## Tests

`dv_harness_tests/test_amba_vip_bind_plan.py` — **62 tests, all passing**,
against a REAL `verible-verilog-syntax` parse of a synthetic 2-master /
multi-slave AMBA4 SoC written to a tmp dir (never a hand-built graph, which
would only prove the code works on the shape the test author imagined).

The fixture is deliberately **not** a clean topology — five of its seven fabric
ports are built so that a specific AMBA-15 point is genuinely unprovable, and
the READY row is the minority case:

| Fabric port | Designed obstacle | Asserted outcome |
|---|---|---|
| S00_AXI_ | none (the clean case) | READY, all four widths read back (32/64/4/4) |
| S01_AXI_ | two clock ports (`ACLK`, `ACLK2`) | clock UNKNOWN naming both, reset still KNOWN, PARTIAL |
| M00_AXI_ | data width is `[DW-1:0]` | data width UNKNOWN, parameterization KNOWN, address width unaffected |
| M01_AXI_ | AXI4→APB4 bridge | both sides recorded, downstream classified APB4 with PCLK/PRESETn, not auto-planned |
| M02_AXI_ | decoder fan-out | MULTIPLE_DESTINATION, 2 child rows, parent chooses none and is capped at PARTIAL |
| M03_AXI_ | unparsed black box with a second bundle | TRACE_BLOCKED, in the unresolved table, next action names the missing RTL |
| M04_AXI_ | nothing connected | DESTINATION_NOT_FOUND, P4 fallback candidate, in the unresolved table |

Plus: a nonexistent hierarchy is BLOCKED with all 13 points FAILED; an APB4
location reports ID/USER as NOT_APPLICABLE and stays READY; an ACTIVE VIP with
no driving requirement is refused; an out-of-vocabulary `active_passive` is
refused; the readiness tally is proved to agree with the matrix it came from;
the plan round-trips through `json.dumps`.

Full suite for everything touched: `dv_harness_tests/` — see the run summary in
the commit message.

---

## Not done here (deliberately, and named)

* **No caller wiring.** `build_vip_bind_plan()` is reachable and end-to-end
  callable from real parse results, but nothing in `connectivity_check.py` or
  the graph invokes it yet. AMBA-27+ in this same build sequence is where a
  standing runner belongs; adding a half-owner here would be the parallel
  mechanism this project keeps catching.
* **AMBA-21..29** (scoreboard analysis, address-map cross-check, ID-width
  planning, L5 branch mapping) are later steps in the sequence and are
  untouched. `branch-mapper/SKILL.md`'s "UNTESTED" label is AMBA-26's to close,
  not this step's.
* **`render_hierarchy_diagram()` was not replaced.** AMBA-19's ASCII tree is an
  additional renderer over the same facts, not a rewrite of the mermaid one.
