"""dv_harness/syoscb_compare_policy.py -- SYOSCB-17 (COMPARE STRATEGY) and
SYOSCB-18 (AXI MATCHING MUST NOT BE RAW OBJECT COMPARE), as a POLICY TABLE and
a MATCH-KEY SCHEMA rather than as SystemVerilog.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
Two things, and only two:

  1. SYOSCB-17's own "Protocol starting policy:" list, as a real table --
     protocol class -> STARTING ordering value -> the real upstream compare
     class that implements it. `syoscb_topology_plan.group_routes_into_
     scoreboards()` stamps every scoreboard group `COMPARE_STRATEGY_DEFERRED
     = "DEFERRED_TO_SYOSCB_17"`; `resolve_plan_compare_strategies()` is what
     that deferral defers TO.
  2. SYOSCB-18's composite match key, as a per-axis SCHEMA over the AMBA
     Transaction IR -- route, master, AXI ID, read/write domain, ordering
     domain, sequence/burst -- plus the one axis SYOSCB-17 adds for ACE-Lite
     (coherency attributes).

It is a SCHEMA and a DEFAULT-POLICY TABLE. Nothing here compares a
transaction, holds a transaction, or knows a transaction value: there is no
compare loop, no queue, and no item. A "match key" here is the LIST OF AXES a
Phase-2 comparison would key on and the evidence each axis is available from,
never a computed key over real traffic.

STARTING POLICY, NOT DECIDED POLICY
------------------------------------
SYOSCB-17 ends with "Validate every policy against the actual DUT/fabric
behavior." Every resolution this module returns therefore carries
`confirmed: False` and a `validation_question`, in exactly the shape
`amba_route_transform_predictor.propose_scoreboard_plan_fields()` already
uses: a table entry is a STARTING POINT a reviewer confirms, and
`connectivity.unfilled_plan_fields()` still reports `ordering` unfilled until
a human answers. A policy table that marked itself confirmed would be this
module answering the row-lock gate on the human's behalf.

WHY THE TABLE NAMES NO CLASS
-----------------------------
"Use actual class/config names from source" (SYOSCB-17). No upstream class
name is typed in this file. The table's values are `syoscb_source_audit.
ORDERING_VALUES` -- L5's own three-value ordering vocabulary -- and the class
behind one is resolved at call time by `compare_class_for_ordering()` against
a real read-only `audit_syoscb_source()` pass. Supply no audit and the
resolution says `COMPARE_CLASS_AUDIT_NOT_SUPPLIED`; supply a tree that
implements only two of the three and the third comes back
`REQUIRED_HUMAN_INPUT` from that function rather than silently substituting a
neighbouring algorithm. `assert_policy_table_resolves_to_real_classes()` holds
the whole table against a real tree, so a starting policy nothing upstream can
execute fails loudly instead of planning a class that does not exist.

The real selection MECHANISM matters as much as the class name and is
recorded in `COMPARE_SELECTION_MECHANISM`: `cl_syoscb_cfg` carries NO compare
selector field, so a Phase-2 plan that configured one would be planning a knob
the library does not have. Selection is a UVM factory type override on
`cl_syoscb_compare_base`, which is a testbench/environment decision, and
`primary_queue` is the one real per-scoreboard compare-loop knob.

WHERE THE EVIDENCE COMES FROM (nothing is re-derived here)
-----------------------------------------------------------
  * Per-protocol field applicability: `amba_transaction_ir.ir_field_
    applicability()`, which derives it from `connectivity.py`'s spec-fixed
    AMBA signal sets. No AMBA signal name is typed in this file except through
    `connectivity.ACE_LITE_COHERENCY_SIGNALS`, imported whole.
  * Per-route ordering domain: the SYOSCB-12 prediction's own
    `ordering_domain` responsibility. This module never re-decides whether a
    route is out-of-order; it reads the predictor's answer and REFINES the
    protocol default against it.
  * Master count per scoreboard: the SYOSCB-14/15 plan's own producer list.
    "AHB Multi-Master -> producer-aware WHERE NECESSARY" is a question about
    how many masters really feed one scoreboard, and that number is already in
    the plan.

THE HONEST-GAP CASES THIS MODULE IS BUILT TO REPORT
----------------------------------------------------
  * Full AHB with an unknown master count. AHB's fingerprint carries HMASTER,
    so the bus CAN be multi-master, and "where necessary" makes the master
    count the deciding evidence. With no count, the answer is
    `REQUIRED_HUMAN_INPUT` -- not IN_ORDER (which false-FAILs a real
    multi-master AHB) and not IN_ORDER_PER_PRODUCER either, because
    producer-aware compare needs slave-side producer attribution that
    `syoscb_topology_plan` may itself have reported blocked.
  * An unresolved protocol. `PROTOCOL_UNRESOLVED` is kept distinct from
    `REQUIRED_HUMAN_INPUT` for the same reason `amba_transaction_ir` keeps
    `IR_FIELD_APPLICABILITY_UNKNOWN` distinct from `NOT_APPLICABLE`: "nobody
    established what this bus is" is a discovery gap, not a policy question.
  * ACE-Lite coherency. SYOSCB-17 asks for "coherency attributes where
    applicable" and `AMBA_TRANSACTION_IR_FIELDS` carries NO field for
    AxSNOOP/AxDOMAIN/AxBAR. The axis is reported APPLICABLE (the signals are
    real, from `connectivity.ACE_LITE_COHERENCY_SIGNALS`) with status
    `NO_IR_FIELD_CARRIES_THIS_AXIS` -- a named IR gap for SYOSCB-9/10, not a
    silently dropped axis.
  * A scoreboard group whose masters do not share one protocol. Two starting
    policies, no arbitration rule in the doc, so the group is reported
    `REQUIRED_HUMAN_INPUT` with both protocols named.

PHASE-1 ONLY (SYOSCB-33 / SYOSCB-34)
-------------------------------------
No SystemVerilog is emitted, no `expected.compare(actual)` is ever executed,
and nothing is copied out of `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`. The
citations name a path and a line; verification reads that tree read-only
through `syoscb_source_audit.audit_syoscb_source()`.
"""
from __future__ import annotations

from dv_harness.amba_port_registry import PortRegistryError
from dv_harness.amba_route_transform_predictor import (
    ORDERING_DOMAIN_PER_ROUTE,
    ORDERING_DOMAIN_PER_ROUTE_AND_ID,
    ROUTE_RESPONSIBILITIES,
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
    TRANSFORM_REQUIRED_HUMAN_INPUT,
)
from dv_harness.amba_transaction_ir import (
    AMBA_TRANSACTION_IR_FIELDS,
    IR_FIELD_APPLICABILITY_UNKNOWN,
    IR_FIELD_APPLICABLE,
    IR_FIELD_NOT_APPLICABLE,
    ir_field_applicability,
    protocol_signal_vocabulary,
)
from dv_harness.connectivity import (
    ACE_LITE_COHERENCY_SIGNALS,
    AMBA4_DISPLAY_NAMES,
    AMBA4_PROTOCOLS,
    REQUIRED_HUMAN_INPUT,
    SCOREBOARD_PLAN_FIELDS,
    render_markdown_table,
)
from dv_harness.syoscb_source_audit import (
    ORDERING_IN_ORDER,
    ORDERING_IN_ORDER_PER_PRODUCER,
    ORDERING_OUT_OF_ORDER,
    ORDERING_VALUES,
    compare_class_for_ordering,
)
from dv_harness.syoscb_topology_plan import COMPARE_STRATEGY_DEFERRED


class CompareStrategyError(PortRegistryError):
    """A compare policy or match key that named an ordering value the harness
    does not have, dropped an axis the protocol makes discriminating, cited a
    doc line for a protocol the table does not cover, or claimed a confirmation
    only a human gives.

    Subclasses `PortRegistryError` so a caller already handling the
    AMBA_PORT_REGISTRY -> predictor -> topology-plan pipeline's errors handles
    these too."""


# ===========================================================================
# SYOSCB-17's protocol starting-policy table
# ===========================================================================

#: The document this table transcribes, so a reviewer can diff the table
#: against the requirement without searching for it.
POLICY_DOC = ("DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_"
              "SystemLevel_AMBA4_SyoSil_CCE_Research.md")

#: The starting ordering for this protocol is not a constant: it depends on how
#: many masters really feed the scoreboard. Only full AHB uses it -- AHB's own
#: fingerprint carries HMASTER, and SYOSCB-17 says "producer-aware WHERE
#: NECESSARY", which is a statement about the topology, not about the bus.
POLICY_MASTER_COUNT_DECIDES = "DECIDED_BY_MASTER_COUNT"

#: The starting policy came straight off `PROTOCOL_COMPARE_POLICY`.
POLICY_FROM_PROTOCOL_TABLE = "STARTING_POLICY_FROM_PROTOCOL_TABLE"
#: Real topology evidence -- a master count, or a SYOSCB-12 ordering domain --
#: moved the policy off the protocol default. The entry carries both values.
POLICY_REFINED_BY_TOPOLOGY = "REFINED_BY_TOPOLOGY_EVIDENCE"
#: The protocol itself never resolved, so no starting policy applies. Kept
#: distinct from REQUIRED_HUMAN_INPUT: this is a discovery gap upstream, not a
#: question about compare strategy.
POLICY_PROTOCOL_UNRESOLVED = "PROTOCOL_UNRESOLVED"
#: Discovery resolved the protocol but not the fact the policy turns on.
POLICY_REQUIRED_HUMAN_INPUT = REQUIRED_HUMAN_INPUT

POLICY_STATUS_VALUES: tuple = (
    POLICY_FROM_PROTOCOL_TABLE,
    POLICY_REFINED_BY_TOPOLOGY,
    POLICY_PROTOCOL_UNRESOLVED,
    POLICY_REQUIRED_HUMAN_INPUT,
)

#: No audit was supplied, so no upstream class was resolved. NOT an error and
#: NOT `REQUIRED_HUMAN_INPUT`: the caller simply did not ask for the class, and
#: `compare_class_for_ordering()` is one read-only call away.
COMPARE_CLASS_AUDIT_NOT_SUPPLIED = "COMPARE_CLASS_AUDIT_NOT_SUPPLIED"

#: SYOSCB-17's "Protocol starting policy:" list, one entry per protocol in
#: `connectivity.AMBA4_PROTOCOLS`, each carrying the doc's own words and the
#: line they were transcribed from.
#:
#: `starting_ordering` is one of `syoscb_source_audit.ORDERING_VALUES` (or
#: `POLICY_MASTER_COUNT_DECIDES`). No upstream class name appears -- that
#: resolution is `compare_class_for_ordering()`'s job against a real tree.
#:
#: `required_axes` is the part that makes a starting policy SAFE rather than
#: merely stated: AXI4-Lite is IN_ORDER only because its independent read and
#: write channels are separated by the match key's `read_write_domain` axis, so
#: a plan that took the IN_ORDER default and dropped that axis would false-FAIL
#: on legal read/write interleaving. `assert_policy_required_axes_present()`
#: enforces it against a real schema.
PROTOCOL_COMPARE_POLICY: dict = {
    "APB": {
        "doc_label": "APB/APB3/APB4",
        "doc_policy": "primarily In-Order",
        "doc_line": 4961,
        "starting_ordering": ORDERING_IN_ORDER,
        "required_axes": ("route",),
        "rationale": "APB is a single-transfer, no-pipelining, no-id bus: a transfer "
                     "completes before the next begins, so arrival order at the slave "
                     "is send order",
    },
    "APB3": {
        "doc_label": "APB/APB3/APB4",
        "doc_policy": "primarily In-Order",
        "doc_line": 4961,
        "starting_ordering": ORDERING_IN_ORDER,
        "required_axes": ("route",),
        "rationale": "APB3 adds PREADY/PSLVERR to APB; wait states defer a transfer but "
                     "never reorder two",
    },
    "APB4": {
        "doc_label": "APB/APB3/APB4",
        "doc_policy": "primarily In-Order",
        "doc_line": 4961,
        "starting_ordering": ORDERING_IN_ORDER,
        "required_axes": ("route",),
        "rationale": "APB4 adds PSTRB/PPROT to APB3; neither affects transfer ordering",
    },
    "AHB_LITE": {
        "doc_label": "AHB-Lite",
        "doc_policy": "primarily In-Order",
        "doc_line": 4964,
        "starting_ordering": ORDERING_IN_ORDER,
        "required_axes": ("route",),
        "rationale": "AHB-Lite is single-master by definition (its fingerprint carries no "
                     "HMASTER), so one producer drives one pipelined, ordered stream",
    },
    "AHB": {
        "doc_label": "AHB Multi-Master",
        "doc_policy": "producer-aware where necessary",
        "doc_line": 4967,
        "starting_ordering": POLICY_MASTER_COUNT_DECIDES,
        "required_axes": ("route", "master"),
        "rationale": "full AHB's fingerprint carries HMASTER, so the bus CAN be "
                     "multi-master; 'where necessary' makes the number of masters really "
                     "feeding this scoreboard the deciding evidence, not the bus name",
    },
    "AXI4_LITE": {
        "doc_label": "AXI4-Lite",
        "doc_policy": "address/order aware",
        "doc_line": 4970,
        "starting_ordering": ORDERING_IN_ORDER,
        "required_axes": ("route", "read_write_domain"),
        "rationale": "AXI4-Lite has no transaction id, so within one direction ordering "
                     "holds; its read and write channels are independent, which is why "
                     "the IN_ORDER default is only safe once the match key separates the "
                     "read domain from the write domain",
    },
    "AXI3": {
        "doc_label": "AXI3",
        "doc_policy": "ID + route + ordering + OOO aware",
        "doc_line": 4973,
        "starting_ordering": ORDERING_OUT_OF_ORDER,
        "required_axes": ("route", "transaction_id", "read_write_domain", "ordering_domain"),
        "rationale": "AXI3 carries AWID/ARID and permits completion out of order between "
                     "ids, so ordering holds only within an id and the route as a whole "
                     "is out of order",
    },
    "AXI4": {
        "doc_label": "AXI4",
        "doc_policy": "ID + route + ordering-domain + OOO aware",
        "doc_line": 4976,
        "starting_ordering": ORDERING_OUT_OF_ORDER,
        "required_axes": ("route", "transaction_id", "read_write_domain", "ordering_domain"),
        "rationale": "AXI4 keeps AXI3's id-scoped ordering and drops write interleaving; "
                     "the ordering DOMAIN key is what a scoreboard groups by, and the "
                     "route as a whole still completes out of order",
    },
    "ACE_LITE": {
        "doc_label": "ACE-Lite",
        "doc_policy": "AXI ordering plus coherency attributes where applicable",
        "doc_line": 4979,
        "starting_ordering": ORDERING_OUT_OF_ORDER,
        "required_axes": ("route", "transaction_id", "read_write_domain",
                          "ordering_domain", "coherency_attributes"),
        "rationale": "ACE-Lite is AXI4 plus AxSNOOP/AxDOMAIN/AxBAR, so it inherits AXI's "
                     "id-scoped out-of-order completion and adds coherency attributes "
                     "two otherwise-identical transactions can differ on",
    },
    "AXI4_STREAM": {
        "doc_label": "AXI4-Stream",
        "doc_policy": "stream/packet/order aware",
        "doc_line": 4982,
        "starting_ordering": ORDERING_IN_ORDER_PER_PRODUCER,
        "required_axes": ("route", "transaction_id"),
        "rationale": "AXI4-Stream carries TID, and ordering is guaranteed WITHIN a stream "
                     "while streams may interleave on the same physical link -- which is "
                     "exactly in-order-per-producer, with the stream id as the producer",
    },
}

#: SYOSCB-17's closing instruction, carried on every resolution rather than
#: stated once in a docstring nobody reads at review time.
POLICY_VALIDATION_INSTRUCTION = (
    "Validate every policy against the actual DUT/fabric behavior "
    f"({POLICY_DOC}:4984)")

#: SYOSCB-17's "Use actual class/config names from source" applied to the
#: SELECTION mechanism, not just the class names. Read from the real tree
#: read-only; each citation is a path and a line, never copied text.
COMPARE_SELECTION_MECHANISM: dict = {
    "mechanism": "UVM_FACTORY_TYPE_OVERRIDE",
    "overridden_type": "cl_syoscb_compare_base",
    "created_at": "src/cl_syoscb_compare.svh:65 "
                  "(cl_syoscb_compare_base::type_id::create)",
    "container": "src/cl_syoscb_compare.svh:21 (cl_syoscb_compare extends uvm_component), "
                 "held by cl_syoscb at src/cl_syoscb.svh:30",
    "config_selector_field": None,
    "config_selector_note": "cl_syoscb_cfg / cl_syoscb_cfg_pl carry NO compare-algorithm "
                            "selector field; a Phase-2 plan that configured one would be "
                            "planning a knob the library does not have",
    "real_cfg_knob": "primary_queue (src/cl_syoscb_cfg.svh:30, accessors at :197-216) -- "
                     "which queue the compare loop treats as primary, NOT which algorithm "
                     "runs",
    "consequence_for_this_plan": "a starting policy resolves to a CLASS the environment "
                                 "type-overrides to, so the policy table's output is a "
                                 "factory-override decision for Phase-2, not a cfg field "
                                 "to set",
}

#: Why SYOSCB-18 exists, in the upstream library's own code. All three compare
#: algorithms delegate the ENTIRE match test to `cl_syoscb_item::compare()`,
#: which is `uvm_object` field automation over the wrapped sequence item -- a
#: raw object compare with no route, master, id or ordering awareness anywhere.
RAW_OBJECT_COMPARE_CITATIONS: tuple = (
    "src/cl_syoscb_compare_io.svh:117 -- sih.compare(primary_item) is the whole match test",
    "src/cl_syoscb_compare_iop.svh:120 -- same, after a get_producer() filter at :119",
    "src/cl_syoscb_compare_ooo.svh:118 -- same, scanning the whole secondary queue",
    "src/cl_syoscb_item.svh:44 -- `uvm_field_object(item, UVM_DEFAULT) makes that compare "
    "plain UVM field automation over the wrapped uvm_sequence_item",
)


def _assert_policy_table_covers_amba4() -> None:
    """Every AMBA-4 protocol the harness classifies must have a starting
    policy, and no other key may appear.

    Runs at import. A protocol added to `connectivity.AMBA4_PROTOCOLS` with no
    entry here would otherwise reach `resolve_compare_policy()` and come back
    "unresolved" as if discovery had failed, hiding a table gap behind a
    discovery verdict."""
    missing = sorted(set(AMBA4_PROTOCOLS) - set(PROTOCOL_COMPARE_POLICY))
    if missing:
        raise CompareStrategyError("COMPARE_POLICY_TABLE_INCOMPLETE", {
            "protocols": missing,
            "hint": "SYOSCB-17 names a starting policy for every AMBA-4 protocol; "
                    "a protocol with no entry has no starting point at all"})
    extra = sorted(set(PROTOCOL_COMPARE_POLICY) - set(AMBA4_PROTOCOLS))
    if extra:
        raise CompareStrategyError("COMPARE_POLICY_TABLE_UNKNOWN_PROTOCOL", {
            "protocols": extra,
            "hint": "the table must not invent a protocol connectivity.py's "
                    "classifier cannot produce"})
    for protocol, entry in PROTOCOL_COMPARE_POLICY.items():
        ordering = entry["starting_ordering"]
        if ordering not in ORDERING_VALUES and ordering != POLICY_MASTER_COUNT_DECIDES:
            raise CompareStrategyError("COMPARE_POLICY_UNKNOWN_ORDERING", {
                "protocol": protocol, "starting_ordering": ordering,
                "allowed": list(ORDERING_VALUES) + [POLICY_MASTER_COUNT_DECIDES],
                "hint": "the table speaks syoscb_source_audit's ordering vocabulary; "
                        "it must not invent a fourth ordering value"})


# ===========================================================================
# SYOSCB-18's composite match key, as a schema over the AMBA Transaction IR
# ===========================================================================

#: SYOSCB-18's own six axes, in the document's order (lines 4998-5003), plus
#: the seventh SYOSCB-17 adds for ACE-Lite (line 4979). The split is kept
#: visible in `MATCH_KEY_AXIS_SPEC["doc_source"]` so a reader can tell which
#: axes the match-key requirement itself names.
MATCH_KEY_AXES: tuple = (
    "route",
    "master",
    "transaction_id",
    "read_write_domain",
    "ordering_domain",
    "sequence_burst",
    "coherency_attributes",
)

#: The six from SYOSCB-18's list, kept separately so a test can hold this
#: module's axis order against the document's.
SYOSCB18_MATCH_KEY_AXES: tuple = MATCH_KEY_AXES[:6]

#: An axis whose evidence is a per-transaction IR field the protocol carries.
AXIS_APPLICABLE = IR_FIELD_APPLICABLE
#: The protocol carries none of the axis's IR fields (a transaction id on APB,
#: an address on AXI4-Stream). A settled fact, not a gap.
AXIS_NOT_APPLICABLE = IR_FIELD_NOT_APPLICABLE
#: The protocol never resolved, so the axis's availability is undecided.
AXIS_PROTOCOL_UNRESOLVED = IR_FIELD_APPLICABILITY_UNKNOWN
#: The axis is real for this protocol -- the signals exist -- but NO field in
#: `AMBA_TRANSACTION_IR_FIELDS` carries it, so a Phase-2 comparison could not
#: read it off an IR item. A named IR gap for SYOSCB-9/10, never a silent drop.
AXIS_NO_IR_FIELD = "NO_IR_FIELD_CARRIES_THIS_AXIS"
#: The axis is supplied by a SYOSCB-12 route prediction and no prediction was
#: given, or the prediction itself reported REQUIRED_HUMAN_INPUT.
AXIS_REQUIRED_HUMAN_INPUT = REQUIRED_HUMAN_INPUT

AXIS_STATUS_VALUES: tuple = (
    AXIS_APPLICABLE, AXIS_NOT_APPLICABLE, AXIS_PROTOCOL_UNRESOLVED,
    AXIS_NO_IR_FIELD, AXIS_REQUIRED_HUMAN_INPUT,
)

#: Per axis: the doc term it transcribes, which `AMBA_TRANSACTION_IR_FIELDS`
#: supply it, which SYOSCB-12 responsibility must have NORMALIZED it before a
#: comparison ("Normalize expected behavior before comparison", line 5005), and
#: what it discriminates that a raw object compare does not.
#:
#: Every `ir_fields` entry is checked against the real IR schema at import and
#: every `normalized_by` entry against `ROUTE_RESPONSIBILITIES`, so a renamed
#: field or responsibility breaks loudly here rather than quietly producing an
#: axis backed by nothing.
MATCH_KEY_AXIS_SPEC: dict = {
    "route": {
        "doc_term": "route",
        "doc_source": "SYOSCB-18",
        "doc_line": 4998,
        "ir_fields": ("route_id", "master_port_id", "slave_port_id"),
        "normalized_by": ("address_decode", "address_translation"),
        "discriminates": "two transactions with identical payloads that took different "
                         "master->slave routes through the fabric",
    },
    "master": {
        "doc_term": "master",
        "doc_source": "SYOSCB-18",
        "doc_line": 4999,
        "ir_fields": ("master_port_id", "source_hierarchy"),
        "normalized_by": (),
        "discriminates": "which producer sent an item, which is what "
                         "cl_syoscb_compare_iop's get_producer() filter "
                         "(src/cl_syoscb_compare_iop.svh:119) keys on",
    },
    "transaction_id": {
        "doc_term": "AXI ID",
        "doc_source": "SYOSCB-18",
        "doc_line": 5000,
        "ir_fields": ("transaction_id", "original_id", "fabric_id"),
        "normalized_by": ("id_remap",),
        "discriminates": "the ordering scope itself -- AXI orders responses only within "
                         "an id, and an interconnect may have remapped that id, which is "
                         "why original_id and fabric_id are both in the key",
    },
    "read_write_domain": {
        "doc_term": "read/write domain",
        "doc_source": "SYOSCB-18",
        "doc_line": 5001,
        "ir_fields": ("transaction_type",),
        "normalized_by": (),
        "discriminates": "a read from a write on protocols whose read and write channels "
                         "are independent, so legal interleaving is not read as reordering",
    },
    "ordering_domain": {
        "doc_term": "ordering domain",
        "doc_source": "SYOSCB-18",
        "doc_line": 5002,
        "ir_fields": (),
        "normalized_by": ("ordering_domain",),
        "discriminates": "which group of transactions must be compared in order at all; "
                         "supplied by the SYOSCB-12 prediction, never re-derived here",
    },
    "sequence_burst": {
        "doc_term": "sequence/burst information",
        "doc_source": "SYOSCB-18",
        "doc_line": 5003,
        "ir_fields": ("burst_type", "burst_len", "burst_size", "sequence_number"),
        "normalized_by": ("width_conversion", "burst_split_merge"),
        "discriminates": "repeats of an identical transfer, and the beats a fabric split "
                         "or merged -- the reassembly a scoreboard must undo before the "
                         "two sides are comparable at all",
    },
    "coherency_attributes": {
        "doc_term": "coherency attributes where applicable",
        "doc_source": "SYOSCB-17 (ACE-Lite)",
        "doc_line": 4979,
        "ir_fields": (),
        "normalized_by": (),
        "witness_signals": tuple(sorted(ACE_LITE_COHERENCY_SIGNALS)),
        "discriminates": "two ACE-Lite transactions identical on every AXI field but "
                         "differing in snoop type, shareability domain or barrier",
    },
}


def _assert_axis_spec_is_backed_by_real_schemas() -> None:
    """Every axis names only real IR fields and real SYOSCB-12
    responsibilities, and `MATCH_KEY_AXES` and the spec agree.

    Runs at import for the same reason `amba_transaction_ir._assert_join_
    columns_exist()` does: an axis pointing at a field that no longer exists
    would report NOT_APPLICABLE for every protocol and look like a protocol
    fact rather than a broken reference."""
    if tuple(MATCH_KEY_AXIS_SPEC) != MATCH_KEY_AXES:
        raise CompareStrategyError("MATCH_KEY_AXIS_SPEC_OUT_OF_SYNC", {
            "axes": list(MATCH_KEY_AXES), "spec": list(MATCH_KEY_AXIS_SPEC)})
    for axis, spec in MATCH_KEY_AXIS_SPEC.items():
        unknown = sorted(set(spec["ir_fields"]) - set(AMBA_TRANSACTION_IR_FIELDS))
        if unknown:
            raise CompareStrategyError("MATCH_KEY_AXIS_UNKNOWN_IR_FIELD", {
                "axis": axis, "fields": unknown,
                "hint": "SYOSCB-18's key is composed of AMBA Transaction IR fields; "
                        "it must not name a field the IR does not define"})
        unknown = sorted(set(spec["normalized_by"]) - set(ROUTE_RESPONSIBILITIES))
        if unknown:
            raise CompareStrategyError("MATCH_KEY_AXIS_UNKNOWN_RESPONSIBILITY", {
                "axis": axis, "responsibilities": unknown,
                "hint": "'Normalize expected behavior before comparison' is discharged by "
                        "the SYOSCB-12 predictor's own responsibilities"})


def _assert_required_axes_are_real() -> None:
    """Every `required_axes` entry in the policy table is a real match-key
    axis. Otherwise a policy could demand an axis no schema ever produces and
    `assert_policy_required_axes_present()` would fail on every plan."""
    for protocol, entry in PROTOCOL_COMPARE_POLICY.items():
        unknown = sorted(set(entry["required_axes"]) - set(MATCH_KEY_AXES))
        if unknown:
            raise CompareStrategyError("COMPARE_POLICY_UNKNOWN_REQUIRED_AXIS", {
                "protocol": protocol, "axes": unknown, "known": list(MATCH_KEY_AXES)})


_assert_policy_table_covers_amba4()
_assert_axis_spec_is_backed_by_real_schemas()
_assert_required_axes_are_real()


# ===========================================================================
# Resolving one protocol's starting policy
# ===========================================================================

def _ordering_from_master_count(master_count):
    """AHB's "producer-aware where necessary", decided by the only evidence
    that can decide it.

    `None` is answered with `REQUIRED_HUMAN_INPUT`, deliberately -- neither
    default is free. IN_ORDER on a real multi-master AHB produces a
    `COMPARE_ERROR` on every legally-interleaved transfer
    (src/cl_syoscb_compare_io.svh:121), and IN_ORDER_PER_PRODUCER needs
    slave-side producer attribution that `syoscb_topology_plan` may itself
    have reported blocked. So the count is asked for, not guessed."""
    if master_count is None:
        return None, [
            "full AHB carries HMASTER, so the bus may be multi-master, and SYOSCB-17's "
            "'producer-aware where necessary' turns on how many masters really feed this "
            "scoreboard -- a number the topology did not establish",
            "neither default is free: IN_ORDER false-FAILs a real multi-master AHB "
            "(src/cl_syoscb_compare_io.svh:121 raises COMPARE_ERROR on the first "
            "interleaved transfer), and IN_ORDER_PER_PRODUCER needs slave-side producer "
            "attribution that may itself be unresolved"]
    if int(master_count) >= 2:
        return ORDERING_IN_ORDER_PER_PRODUCER, [
            f"{int(master_count)} masters feed this scoreboard, so producer-aware compare "
            f"is 'necessary' in SYOSCB-17's sense: the primary queue's front item is not "
            f"necessarily from the same producer as a secondary queue's"]
    return ORDERING_IN_ORDER, [
        "exactly one master feeds this scoreboard, so producer-awareness is not "
        "'necessary' in SYOSCB-17's sense -- one producer's stream is one ordered stream"]


def resolve_compare_policy(protocol, *, master_count=None,
                           route_ordering_expectation=None, audit=None) -> dict:
    """SYOSCB-17's starting policy for one protocol, refined by whatever real
    topology evidence the caller has.

    `master_count` is the number of masters feeding the scoreboard this policy
    is for -- the SYOSCB-14/15 plan already knows it. `route_ordering_
    expectation` is the SYOSCB-12 prediction's own `ordering_domain.value
    ["route_ordering_expectation"]`; supplying it lets a protocol default be
    ESCALATED by real routing evidence, and this module never re-derives it.
    `audit` is a real `syoscb_source_audit.audit_syoscb_source()` result; with
    one, the resolution also names the upstream class that implements the
    chosen ordering.

    Never returns a confirmed value. SYOSCB-17's own last line makes every
    entry here a starting point a reviewer validates against the real DUT."""
    entry = PROTOCOL_COMPARE_POLICY.get(protocol)
    if entry is None:
        return {
            "protocol": protocol,
            "protocol_display": AMBA4_DISPLAY_NAMES.get(protocol, str(protocol)),
            "status": POLICY_PROTOCOL_UNRESOLVED,
            "starting_ordering": None,
            "ordering": None,
            "doc_policy": None,
            "doc_citation": None,
            "required_axes": (),
            "compare_class": COMPARE_CLASS_AUDIT_NOT_SUPPLIED if audit is None else None,
            "confirmed": False,
            "validation_question": POLICY_VALIDATION_INSTRUCTION,
            "evidence": [
                f"{protocol!r} is not one of connectivity.AMBA4_PROTOCOLS, so no "
                f"SYOSCB-17 starting policy applies; the gap is in protocol "
                f"classification, not in compare strategy"],
            "cautions": [],
        }

    status = POLICY_FROM_PROTOCOL_TABLE
    evidence = [f"{POLICY_DOC}:{entry['doc_line']} -- {entry['doc_label']} -> "
                f"{entry['doc_policy']}",
                entry["rationale"]]
    starting = entry["starting_ordering"]
    ordering = starting
    if starting == POLICY_MASTER_COUNT_DECIDES:
        ordering, why = _ordering_from_master_count(master_count)
        evidence.extend(why)
        status = POLICY_REFINED_BY_TOPOLOGY if ordering is not None else \
            POLICY_REQUIRED_HUMAN_INPUT

    if (ordering is not None
            and route_ordering_expectation == ORDERING_OUT_OF_ORDER
            and ordering != ORDERING_OUT_OF_ORDER):
        evidence.append(
            f"the SYOSCB-12 prediction for this scoreboard's routes reports "
            f"{ORDERING_OUT_OF_ORDER}, which outranks the {ordering} protocol default: "
            f"an in-order compare on a route that legally completes out of order raises "
            f"COMPARE_ERROR on correct traffic (src/cl_syoscb_compare_io.svh:121)")
        ordering, status = ORDERING_OUT_OF_ORDER, POLICY_REFINED_BY_TOPOLOGY

    cautions = []
    if ordering == ORDERING_OUT_OF_ORDER and (master_count or 0) >= 2:
        cautions.append(
            "cl_syoscb_compare_ooo scans a secondary queue with NO producer filter "
            "(src/cl_syoscb_compare_ooo.svh:118, contrast src/cl_syoscb_compare_iop."
            "svh:119), so with more than one master the compare cannot itself tell two "
            "producers apart -- the match key's `master` axis has to")
    if ordering == ORDERING_IN_ORDER and (master_count or 0) >= 2:
        cautions.append(
            "more than one producer feeds this scoreboard's queues, and "
            "cl_syoscb_compare_io compares FRONT items with no producer filter "
            "(src/cl_syoscb_compare_io.svh:117), so the in-order policy assumes both "
            "queues observe the same global order across producers -- validate that "
            "against the real fabric arbitration before adopting it")
    if ordering == ORDERING_IN_ORDER_PER_PRODUCER:
        cautions.append(
            "in-order-per-producer needs a slave-side monitor able to say WHICH master "
            "sent an item; syoscb_topology_plan reports that attribution and may have "
            "reported it blocked")

    resolved = {
        "protocol": protocol,
        "protocol_display": AMBA4_DISPLAY_NAMES.get(protocol, protocol),
        "status": status if ordering is not None else POLICY_REQUIRED_HUMAN_INPUT,
        "starting_ordering": starting,
        "ordering": ordering if ordering is not None else REQUIRED_HUMAN_INPUT,
        "doc_policy": entry["doc_policy"],
        "doc_citation": f"{POLICY_DOC}:{entry['doc_line']}",
        "required_axes": tuple(entry["required_axes"]),
        "compare_class": None,
        "confirmed": False,
        "validation_question": POLICY_VALIDATION_INSTRUCTION,
        "evidence": evidence,
        "cautions": cautions,
    }
    resolved["compare_class"] = _compare_class(audit, ordering)
    _assert_resolution_shape(resolved)
    return resolved


def _compare_class(audit, ordering):
    """The real upstream class for an ordering, or a sentinel saying why not.

    No class name is typed here: `compare_class_for_ordering()` reads it off a
    real audit of the real tree, and returns its own REQUIRED_HUMAN_INPUT entry
    when the tree implements no such algorithm."""
    if ordering is None:
        return {"class": REQUIRED_HUMAN_INPUT,
                "reason": "NO_ORDERING_RESOLVED_TO_LOOK_UP"}
    if audit is None:
        return {"class": COMPARE_CLASS_AUDIT_NOT_SUPPLIED,
                "reason": "no syoscb_source_audit result was supplied; the class is one "
                          "read-only audit_syoscb_source() call away and is never "
                          "hardcoded here"}
    return compare_class_for_ordering(audit, ordering)


def _assert_resolution_shape(resolved: dict) -> None:
    if resolved["status"] not in POLICY_STATUS_VALUES:
        raise CompareStrategyError("COMPARE_POLICY_UNKNOWN_STATUS", {
            "protocol": resolved.get("protocol"), "status": resolved["status"],
            "allowed": list(POLICY_STATUS_VALUES)})
    ordering = resolved["ordering"]
    if ordering not in ORDERING_VALUES and ordering != REQUIRED_HUMAN_INPUT:
        raise CompareStrategyError("COMPARE_POLICY_RESOLVED_UNKNOWN_ORDERING", {
            "protocol": resolved.get("protocol"), "ordering": ordering,
            "allowed": list(ORDERING_VALUES) + [REQUIRED_HUMAN_INPUT]})
    if not resolved["evidence"]:
        raise CompareStrategyError("COMPARE_POLICY_WITHOUT_EVIDENCE", {
            "protocol": resolved.get("protocol"),
            "hint": "a starting policy with no stated basis is the guess SYOSCB-17's "
                    "'validate every policy' instruction exists to prevent"})


def assert_policy_table_resolves_to_real_classes(audit) -> None:
    """Every ordering the table can produce is implemented by a real class in
    the audited tree.

    The whole point of a starting-policy table is that its outputs are
    executable. An ordering the upstream library does not implement is a policy
    that cannot be carried out, and finding that at Phase-2 elaboration time --
    after approval, mid-build -- is exactly the late failure this Phase-1 check
    moves forward."""
    wanted = {e["starting_ordering"] for e in PROTOCOL_COMPARE_POLICY.values()
              if e["starting_ordering"] in ORDERING_VALUES}
    # The two orderings only reachable by refinement are just as required.
    wanted |= {ORDERING_IN_ORDER, ORDERING_IN_ORDER_PER_PRODUCER, ORDERING_OUT_OF_ORDER}
    unimplemented = []
    for ordering in sorted(wanted):
        hit = compare_class_for_ordering(audit, ordering)
        if hit.get("class") == REQUIRED_HUMAN_INPUT:
            unimplemented.append({"ordering": ordering, "reason": hit.get("reason"),
                                  "hint": hit.get("hint")})
    if unimplemented:
        raise CompareStrategyError("COMPARE_POLICY_ORDERING_NOT_IMPLEMENTED_UPSTREAM", {
            "root": str(getattr(audit, "root", "")), "orderings": unimplemented,
            "hint": "the protocol starting-policy table can produce an ordering this "
                    "tree implements no compare class for; either the tree is wrong or "
                    "the policy needs an upstream extension a human decides"})


# ===========================================================================
# Building one protocol's match-key schema
# ===========================================================================

def _axis_from_ir(axis: str, spec: dict, applicability: dict, protocol: str) -> dict:
    """An IR-backed axis's status: APPLICABLE if the protocol carries any of
    its fields, NOT_APPLICABLE if none, UNRESOLVED if the protocol is not one
    of the ten.

    Both lists are reported, not just the verdict. "APB's sequence/burst axis
    is available, but only through `sequence_number` -- burst_type, burst_len
    and burst_size are NOT_APPLICABLE_FOR_PROTOCOL" is a materially different
    fact from "the axis is available", and the difference is what tells a
    reviewer the key is thinner than it looks."""
    available, unavailable, unresolved = [], [], []
    for field in spec["ir_fields"]:
        status = applicability.get(field, {}).get("status")
        if status == IR_FIELD_APPLICABLE:
            available.append(field)
        elif status == IR_FIELD_NOT_APPLICABLE:
            unavailable.append(field)
        else:
            unresolved.append(field)
    if unresolved and not available:
        return {"status": AXIS_PROTOCOL_UNRESOLVED, "ir_fields_available": [],
                "ir_fields_not_applicable": [], "ir_fields_unresolved": unresolved,
                "evidence": [f"protocol {protocol!r} never resolved, so this axis's "
                             f"availability is undecided"]}
    if available:
        evidence = [f"{AMBA4_DISPLAY_NAMES.get(protocol, protocol)} carries "
                    f"{', '.join(available)}"]
        if unavailable:
            evidence.append(
                f"the axis is thinner than its full definition here: "
                f"{', '.join(unavailable)} are NOT_APPLICABLE_FOR_PROTOCOL")
        if unresolved:
            evidence.append(
                f"the axis survives an unresolved protocol only through its "
                f"protocol-independent fields; {', '.join(unresolved)} stay undecided "
                f"until classification lands")
        return {"status": AXIS_APPLICABLE, "ir_fields_available": available,
                "ir_fields_not_applicable": unavailable,
                "ir_fields_unresolved": unresolved, "evidence": evidence,
                "partial": bool(unavailable)}
    return {"status": AXIS_NOT_APPLICABLE, "ir_fields_available": [],
            "ir_fields_not_applicable": unavailable, "ir_fields_unresolved": unresolved,
            "evidence": [f"{AMBA4_DISPLAY_NAMES.get(protocol, protocol)} carries none of "
                         f"{', '.join(spec['ir_fields'])}"]}


def _ordering_domain_axis(protocol: str, prediction) -> dict:
    """The ordering-domain axis, read off a SYOSCB-12 prediction.

    No IR field carries an ordering domain -- it is a per-ROUTE property the
    predictor derives, not a per-transaction one a monitor observes. With no
    prediction the axis is REQUIRED_HUMAN_INPUT with the producer named, rather
    than quietly dropped from a key that then compares across domains."""
    if prediction is None:
        return {"status": AXIS_REQUIRED_HUMAN_INPUT, "ir_fields_available": [],
                "ir_fields_not_applicable": [], "ir_fields_unresolved": [],
                "evidence": ["no SYOSCB-12 route prediction was supplied; the ordering "
                             "domain is amba_route_transform_predictor.detect_ordering_"
                             "domain()'s answer and is never re-derived here"]}
    entry = (prediction.get("responsibilities") or {}).get("ordering_domain") or {}
    if entry.get("status") != TRANSFORM_PREDICTED_FROM_TOPOLOGY:
        return {"status": AXIS_REQUIRED_HUMAN_INPUT, "ir_fields_available": [],
                "ir_fields_not_applicable": [], "ir_fields_unresolved": [],
                "evidence": ([f"the route prediction's ordering_domain is "
                              f"{entry.get('status', 'ABSENT')}"]
                             + list(entry.get("evidence") or []))}
    value = entry.get("value") or {}
    return {"status": AXIS_APPLICABLE, "ir_fields_available": [],
            "ir_fields_not_applicable": [], "ir_fields_unresolved": [],
            "domain_key": value.get("domain_key"),
            "route_ordering_expectation": value.get("route_ordering_expectation"),
            "ordering_tolerance_depth": value.get("ordering_tolerance_depth"),
            "evidence": list(entry.get("evidence") or [])}


def _coherency_axis(protocol: str) -> dict:
    """ACE-Lite's coherency attributes -- real signals, no IR field.

    Reported APPLICABLE-but-uncarriable rather than APPLICABLE (which would
    imply a Phase-2 comparison could read it) or NOT_APPLICABLE (which would
    deny signals `connectivity.ACE_LITE_COHERENCY_SIGNALS` says are there)."""
    if protocol not in AMBA4_PROTOCOLS:
        return {"status": AXIS_PROTOCOL_UNRESOLVED, "ir_fields_available": [],
                "ir_fields_not_applicable": [], "ir_fields_unresolved": [],
                "evidence": [f"protocol {protocol!r} never resolved"]}
    present = sorted(ACE_LITE_COHERENCY_SIGNALS & protocol_signal_vocabulary(protocol))
    if not present:
        return {"status": AXIS_NOT_APPLICABLE, "ir_fields_available": [],
                "ir_fields_not_applicable": [], "ir_fields_unresolved": [],
                "evidence": [f"{AMBA4_DISPLAY_NAMES[protocol]} carries none of "
                             f"{', '.join(sorted(ACE_LITE_COHERENCY_SIGNALS))}"]}
    return {"status": AXIS_NO_IR_FIELD, "ir_fields_available": [],
            "ir_fields_not_applicable": [], "ir_fields_unresolved": [],
            "witness_signals": present,
            "evidence": [f"{AMBA4_DISPLAY_NAMES[protocol]} carries {', '.join(present)}, "
                         f"so SYOSCB-17's 'coherency attributes where applicable' applies "
                         f"to it",
                         "no field in AMBA_TRANSACTION_IR_FIELDS carries a snoop type, "
                         "shareability domain or barrier, so this axis has no IR slot to "
                         "be read from -- an IR gap for SYOSCB-9/10, named here rather "
                         "than dropped"]}


def _normalization(axis: str, spec: dict, prediction) -> dict:
    """"Normalize expected behavior before comparison" (SYOSCB-18:5005), as a
    per-axis status over the SYOSCB-12 responsibilities that would do it.

    With no prediction the answer is not "no normalization needed" -- it is
    "nobody checked", and the difference is the whole point: an unnormalized
    id-remapping route compared on a raw id matches nothing."""
    required = list(spec["normalized_by"])
    if not required:
        return {"status": "NO_NORMALIZATION_REQUIRED", "responsibilities": [],
                "evidence": [f"the {axis} axis is not altered by any fabric transform "
                             f"SYOSCB-12 predicts"]}
    if prediction is None:
        return {"status": AXIS_REQUIRED_HUMAN_INPUT, "responsibilities": required,
                "evidence": [f"no route prediction supplied, so whether {', '.join(required)} "
                             f"transforms this axis is unchecked -- treating that as "
                             f"'no transform' is the silent false-PASS SYOSCB-18 names"]}
    answers = prediction.get("responsibilities") or {}
    applied, open_items = [], []
    for name in required:
        entry = answers.get(name) or {}
        if entry.get("status") == TRANSFORM_PREDICTED_FROM_TOPOLOGY:
            applied.append({"responsibility": name, "value": entry.get("value"),
                            "evidence": list(entry.get("evidence") or [])})
        elif entry.get("status") == TRANSFORM_REQUIRED_HUMAN_INPUT:
            open_items.append({"responsibility": name,
                               "evidence": list(entry.get("evidence") or [])})
    if open_items:
        return {"status": AXIS_REQUIRED_HUMAN_INPUT, "responsibilities": required,
                "applied": applied, "open": open_items,
                "evidence": [f"{o['responsibility']} is REQUIRED_HUMAN_INPUT on this "
                             f"route, so this axis cannot be normalized yet"
                             for o in open_items]}
    return {"status": ("NORMALIZATION_PREDICTED" if applied else "NO_TRANSFORM_PREDICTED"),
            "responsibilities": required, "applied": applied,
            "evidence": ([f"{a['responsibility']} predicted from topology" for a in applied]
                         or [f"the prediction implies no {'/'.join(required)} on this "
                             f"route, so the axis passes through unchanged"])}


def build_match_key_schema(protocol, *, prediction=None) -> dict:
    """SYOSCB-18's composite match key for one protocol, as a per-axis schema.

    A SCHEMA: which axes exist, which the protocol can actually supply, which
    IR field each is read from, and what must be normalized first. It carries
    no transaction and computes no key.

    `prediction` is one `amba_route_transform_predictor.predict_routes()` entry.
    Supply one and the ordering-domain axis and every normalization status
    resolve from real routing evidence; supply none and both say so."""
    applicability = ir_field_applicability(protocol)
    axes: dict = {}
    for axis in MATCH_KEY_AXES:
        spec = MATCH_KEY_AXIS_SPEC[axis]
        if axis == "ordering_domain":
            entry = _ordering_domain_axis(protocol, prediction)
        elif axis == "coherency_attributes":
            entry = _coherency_axis(protocol)
        else:
            entry = _axis_from_ir(axis, spec, applicability, protocol)
        entry.update({
            "axis": axis,
            "doc_term": spec["doc_term"],
            "doc_citation": f"{POLICY_DOC}:{spec['doc_line']}",
            "doc_source": spec["doc_source"],
            "discriminates": spec["discriminates"],
            "normalization": _normalization(axis, spec, prediction),
        })
        axes[axis] = entry

    schema = {
        "protocol": protocol,
        "protocol_display": AMBA4_DISPLAY_NAMES.get(protocol, str(protocol)),
        "route_id": (prediction or {}).get("route_id"),
        "axes": axes,
        "included_axes": [a for a in MATCH_KEY_AXES
                          if axes[a]["status"] == AXIS_APPLICABLE],
        "raw_object_compare_is_insufficient_because": list(RAW_OBJECT_COMPARE_CITATIONS),
        "confirmed": False,
    }
    schema["unresolved_axes"] = unresolved_match_key_axes(schema)
    assert_schema_shape(schema)
    return schema


def assert_schema_shape(schema: dict) -> None:
    """Every axis present, each with a legal status and a stated basis."""
    axes = schema.get("axes") or {}
    missing = [a for a in MATCH_KEY_AXES if a not in axes]
    if missing:
        raise CompareStrategyError("MATCH_KEY_SCHEMA_INCOMPLETE", {
            "protocol": schema.get("protocol"), "missing": missing})
    for axis, entry in axes.items():
        if entry.get("status") not in AXIS_STATUS_VALUES:
            raise CompareStrategyError("MATCH_KEY_AXIS_UNKNOWN_STATUS", {
                "protocol": schema.get("protocol"), "axis": axis,
                "status": entry.get("status"), "allowed": list(AXIS_STATUS_VALUES)})
        if not entry.get("evidence"):
            raise CompareStrategyError("MATCH_KEY_AXIS_WITHOUT_EVIDENCE", {
                "protocol": schema.get("protocol"), "axis": axis,
                "hint": "an axis with no stated basis cannot be reviewed; even a "
                        "NOT_APPLICABLE verdict names the signals it looked for"})


def unresolved_match_key_axes(schema: dict) -> list:
    """The axes still waiting on a human or on an IR extension.

    NOT the NOT_APPLICABLE ones -- "AXI4-Stream has no address" is a settled
    fact, not an open question -- and not the PROTOCOL_UNRESOLVED ones either,
    which are a discovery gap reported by whoever owns classification."""
    return [a for a in MATCH_KEY_AXES
            if (schema.get("axes") or {}).get(a, {}).get("status")
            in (AXIS_REQUIRED_HUMAN_INPUT, AXIS_NO_IR_FIELD)]


# ===========================================================================
# SYOSCB-18's actual rule, as a check
# ===========================================================================

#: The axes that make a match key more than a payload comparison. A key that
#: drops every one of these on a protocol that supplies them IS
#: `expected.compare(actual)` with extra steps.
DISCRIMINATING_AXES: tuple = ("route", "transaction_id", "ordering_domain",
                              "master", "read_write_domain")


def assert_not_raw_object_compare(schema: dict, proposed_axes=None) -> None:
    """SYOSCB-18's rule, enforced: "Do not rely solely on expected.compare(
    actual) when the fabric may legitimately transform transactions."

    Refuses a proposed key that keeps NONE of the discriminating axes the
    protocol actually supplies. That is the exact shape upstream gives you for
    free -- all three compare algorithms delegate the whole match test to
    `cl_syoscb_item::compare()`, i.e. UVM field automation over the wrapped
    sequence item (see `RAW_OBJECT_COMPARE_CITATIONS`) -- so a key that adds
    nothing to it is not a match key at all.

    Passing no `proposed_axes` checks the schema's own applicable axes, which
    is how a protocol whose every discriminating axis is unresolved gets
    caught rather than quietly planned."""
    available = [a for a in DISCRIMINATING_AXES
                 if (schema.get("axes") or {}).get(a, {}).get("status") == AXIS_APPLICABLE]
    proposed = list(schema["included_axes"] if proposed_axes is None else proposed_axes)
    unknown = sorted(set(proposed) - set(MATCH_KEY_AXES))
    if unknown:
        raise CompareStrategyError("MATCH_KEY_UNKNOWN_AXIS", {
            "protocol": schema.get("protocol"), "axes": unknown,
            "known": list(MATCH_KEY_AXES)})
    if not available:
        return
    kept = [a for a in available if a in proposed]
    if not kept:
        raise CompareStrategyError("MATCH_KEY_IS_RAW_OBJECT_COMPARE", {
            "protocol": schema.get("protocol"), "route_id": schema.get("route_id"),
            "dropped_discriminating_axes": available, "proposed_axes": proposed,
            "citations": list(RAW_OBJECT_COMPARE_CITATIONS),
            "hint": "SYOSCB-18: a key that keeps none of the axes the protocol supplies "
                    "is exactly the field-automation compare uvm_syoscb already does"})


def assert_policy_required_axes_present(policy: dict, schema: dict) -> None:
    """The starting policy's own `required_axes` are actually available in the
    match-key schema.

    This is what makes a starting policy safe rather than merely stated:
    AXI4-Lite's IN_ORDER default is only correct once `read_write_domain`
    separates its two independent channels, and AXI's OUT_OF_ORDER default is
    only implementable once `transaction_id` is really there. A policy applied
    to a schema that cannot supply its own preconditions is a false PASS
    waiting to happen, so it raises."""
    axes = schema.get("axes") or {}
    unmet = []
    for axis in policy.get("required_axes") or ():
        status = axes.get(axis, {}).get("status")
        if status != AXIS_APPLICABLE:
            unmet.append({"axis": axis, "status": status,
                          "evidence": list(axes.get(axis, {}).get("evidence") or [])})
    if unmet:
        raise CompareStrategyError("COMPARE_POLICY_REQUIRED_AXIS_UNAVAILABLE", {
            "protocol": policy.get("protocol"), "ordering": policy.get("ordering"),
            "doc_citation": policy.get("doc_citation"), "unmet": unmet,
            "hint": "the starting policy's preconditions are not met by the match key "
                    "this protocol can actually supply; the policy cannot be adopted as "
                    "it stands"})


# ===========================================================================
# Feeding connectivity.SCOREBOARD_PLAN_FIELDS -- as PROPOSALS
# ===========================================================================

#: Which existing scoreboard-plan columns this module can inform. Two: the
#: compare strategy proposes into `ordering`, and the composite key proposes
#: into `matching_key`. `transformation_rules` is deliberately NOT here -- the
#: SYOSCB-12 predictor already proposes into it, and a second proposer for one
#: column is how two mechanisms end up disagreeing about one field.
#:
#: Checked against the real schema at import so a renamed column breaks loudly
#: rather than proposing into a field that no longer exists.
COMPARE_POLICY_INFORMED_PLAN_FIELDS: tuple = ("matching_key", "ordering")


def _assert_informed_fields_are_real() -> None:
    unknown = sorted(set(COMPARE_POLICY_INFORMED_PLAN_FIELDS) - set(SCOREBOARD_PLAN_FIELDS))
    if unknown:
        raise CompareStrategyError("COMPARE_POLICY_PLAN_FIELD_NOT_IN_SCHEMA", {
            "fields": unknown,
            "hint": "SYOSCB-17/18 extend connectivity.SCOREBOARD_PLAN_FIELDS' existing "
                    "matching_key and ordering columns; they must not invent a second "
                    "scoreboard-plan vocabulary"})


_assert_informed_fields_are_real()


def propose_scoreboard_plan_fields(policy: dict, schema: dict) -> dict:
    """What one policy + schema PROPOSE for the existing scoreboard-plan
    schema.

    Proposals, and every entry says so. `connectivity.generate_scoreboard_
    entry()` computes no default for any of its nine fields, and
    `unfilled_plan_fields()` must keep reporting `matching_key` and `ordering`
    unfilled until a human answers -- SYOSCB-17's "validate every policy
    against the actual DUT/fabric behavior" is that answer, not this table.

    The `matching_key` proposal is the point of SYOSCB-18: the existing field's
    three canned options each name ONE field, and what goes in here is a
    composite -- an ordered axis list, each axis carrying the IR fields it
    reads and the normalization it needs first."""
    composite = []
    for axis in schema["included_axes"]:
        entry = schema["axes"][axis]
        composite.append({
            "axis": axis,
            "doc_term": entry["doc_term"],
            "ir_fields": entry.get("ir_fields_available", []),
            "normalization": entry["normalization"]["status"],
            "discriminates": entry["discriminates"],
        })
    return {
        "matching_key": {
            "proposal": {
                "kind": "COMPOSITE_MATCH_KEY",
                "protocol": schema["protocol"],
                "route_id": schema.get("route_id"),
                "axes": composite,
                "unresolved_axes": schema["unresolved_axes"],
            },
            "confirmed": False,
            "basis": "SYOSCB-18's composite key over the AMBA Transaction IR; each axis's "
                     "availability comes from amba_transaction_ir.ir_field_applicability(), "
                     "which derives it from connectivity.py's AMBA signal sets",
        },
        "ordering": {
            "proposal": {
                "ordering": policy["ordering"],
                "starting_ordering": policy["starting_ordering"],
                "status": policy["status"],
                "compare_class": policy["compare_class"],
                "doc_citation": policy["doc_citation"],
                "cautions": policy["cautions"],
            },
            "confirmed": False,
            "basis": "SYOSCB-17's protocol starting policy, refined by the topology's own "
                     "master count and the SYOSCB-12 ordering domain; the reorder-window "
                     "DEPTH is not proposed here -- ordering_tolerance_depth stays the "
                     "predictor's REQUIRED_HUMAN_INPUT",
        },
    }


def assert_plan_proposals_are_not_confirmations(proposals: dict) -> None:
    """A proposal that marked itself confirmed would be this table answering
    the row-lock gate on the human's behalf -- and SYOSCB-17 explicitly ends by
    asking for that human validation."""
    claimed = sorted(f for f, entry in (proposals or {}).items() if entry.get("confirmed"))
    if claimed:
        raise CompareStrategyError("COMPARE_POLICY_PROPOSAL_CLAIMS_CONFIRMATION", {
            "fields": claimed,
            "hint": "only a human answering the question queue confirms a "
                    "SCOREBOARD_PLAN_FIELDS value"})


# ===========================================================================
# Resolving the SYOSCB-14/16 plan's own deferred compare strategy
# ===========================================================================

#: A scoreboard group whose masters do not all speak one protocol. Two starting
#: policies, and SYOSCB-17 supplies no rule for arbitrating them, so the group
#: is reported open with both protocols named rather than resolved to whichever
#: one sorted first.
GROUP_MIXED_PROTOCOL = "MIXED_PROTOCOL_GROUP"


def _group_master_protocols(plan: dict, group: dict) -> list:
    """The distinct protocols of the masters that really feed one scoreboard
    group, read off the plan's OWN producer list.

    No new join: `map_masters_to_producers()` already carried each producer's
    registry protocol and route ids, so this cannot disagree with the plan a
    reviewer read."""
    route_ids = set(group.get("route_ids") or ())
    protocols = []
    for producer in plan.get("producers") or ():
        if not route_ids & set(producer.get("route_ids") or ()):
            continue
        protocol = producer.get("protocol")
        if protocol not in protocols:
            protocols.append(protocol)
    return protocols


def _group_master_count(plan: dict, group: dict) -> int:
    route_ids = set(group.get("route_ids") or ())
    return sum(1 for p in plan.get("producers") or ()
               if route_ids & set(p.get("route_ids") or ()))


def resolve_plan_compare_strategies(plan: dict, *, audit=None) -> list:
    """SYOSCB-17's answer for every scoreboard group in a SYOSCB-14/16 plan.

    `syoscb_topology_plan.group_routes_into_scoreboards()` stamps each group
    `compare_strategy = COMPARE_STRATEGY_DEFERRED`; this is what it was
    deferred to. Every input comes from the plan itself -- the master count
    from its producer list, the ordering expectation from the group's own
    `route_ordering_expectation`, which the SYOSCB-12 predictor put there --
    so a resolution cannot contradict the plan a reviewer already read.

    Returns one record per group. The plan is NOT mutated: a policy is a
    proposal, and overwriting `DEFERRED_TO_SYOSCB_17` in place would make the
    plan look decided."""
    resolutions = []
    for group in plan.get("scoreboards") or ():
        protocols = _group_master_protocols(plan, group)
        master_count = _group_master_count(plan, group)
        expectation = group.get("route_ordering_expectation")
        record = {
            "scoreboard_id": group.get("scoreboard_id"),
            "deferred_marker": COMPARE_STRATEGY_DEFERRED,
            "master_count": master_count,
            "master_protocols": protocols,
            "ordering_domain_key": group.get("ordering_domain_key"),
            "route_ordering_expectation": expectation,
        }
        if len(protocols) != 1:
            record.update({
                "policy": None,
                "status": POLICY_REQUIRED_HUMAN_INPUT,
                "reason": GROUP_MIXED_PROTOCOL if len(protocols) > 1
                          else "NO_PRODUCER_FEEDS_THIS_GROUP",
                "evidence": [
                    f"the masters feeding {group.get('scoreboard_id')} report protocols "
                    f"{protocols or '[]'}; SYOSCB-17 gives one starting policy per "
                    f"protocol and no rule for arbitrating two, so the group's compare "
                    f"strategy is a human decision"],
            })
            resolutions.append(record)
            continue
        policy = resolve_compare_policy(
            protocols[0], master_count=master_count,
            route_ordering_expectation=expectation, audit=audit)
        record.update({
            "policy": policy,
            "status": policy["status"],
            "reason": None,
            "evidence": list(policy["evidence"]),
        })
        resolutions.append(record)
    return resolutions


def unresolved_compare_strategies(resolutions) -> list:
    """The scoreboard ids whose compare strategy is still an open question."""
    return sorted(r["scoreboard_id"] for r in resolutions or ()
                  if r.get("status") in (POLICY_REQUIRED_HUMAN_INPUT,
                                         POLICY_PROTOCOL_UNRESOLVED))


# ===========================================================================
# Rendering -- tables and a report, never SystemVerilog
# ===========================================================================

def render_protocol_policy_table(audit=None) -> str:
    """SYOSCB-17's starting-policy list as a real table. With an audit, the
    upstream class column is filled from the real tree; without one it says so
    rather than naming a class from memory."""
    rows = []
    for protocol in AMBA4_PROTOCOLS:
        entry = PROTOCOL_COMPARE_POLICY[protocol]
        resolved = resolve_compare_policy(protocol, audit=audit)
        rows.append({
            "Protocol": AMBA4_DISPLAY_NAMES[protocol],
            "Doc policy": entry["doc_policy"],
            "Doc line": str(entry["doc_line"]),
            "Starting ordering": entry["starting_ordering"],
            "Upstream compare class": str(resolved["compare_class"].get("class")),
            "Required key axes": ", ".join(entry["required_axes"]),
        })
    return render_markdown_table(
        ["Protocol", "Doc policy", "Doc line", "Starting ordering",
         "Upstream compare class", "Required key axes"], rows)


def render_match_key_table(schema: dict) -> str:
    """One protocol's match-key schema, axis by axis."""
    rows = []
    for axis in MATCH_KEY_AXES:
        entry = schema["axes"][axis]
        rows.append({
            "Axis": axis,
            "Doc term": entry["doc_term"],
            "Status": entry["status"],
            "IR fields": ", ".join(entry.get("ir_fields_available") or []) or "-",
            "Normalization": entry["normalization"]["status"],
        })
    return render_markdown_table(
        ["Axis", "Doc term", "Status", "IR fields", "Normalization"], rows)


def render_compare_strategy_table(resolutions) -> str:
    """The per-scoreboard compare-strategy resolution for a whole plan."""
    rows = []
    for record in resolutions or ():
        policy = record.get("policy") or {}
        rows.append({
            "Scoreboard": record["scoreboard_id"],
            "Masters": str(record["master_count"]),
            "Protocol": ", ".join(record["master_protocols"]) or "-",
            "Ordering": str(policy.get("ordering", REQUIRED_HUMAN_INPUT)),
            "Compare class": str((policy.get("compare_class") or {}).get(
                "class", REQUIRED_HUMAN_INPUT)),
            "Status": record["status"],
        })
    return render_markdown_table(
        ["Scoreboard", "Masters", "Protocol", "Ordering", "Compare class", "Status"], rows)


def render_compare_policy_report(resolutions=None, schemas=None, audit=None) -> str:
    """The SYOSCB-17/18 section of a Phase-1 report.

    Structured text only. Nothing here is SystemVerilog, and the report is
    expected to be run through `syoscb_source_audit.assert_no_emittable_sv()`
    by its caller, exactly as `syoscb_topology_plan`'s report is."""
    out = ["## SYOSCB-17 -- Compare strategy (protocol starting policy)", ""]
    out.append(render_protocol_policy_table(audit))
    out += ["", "Selection mechanism (read from the real source, read-only):", ""]
    for key in ("mechanism", "overridden_type", "created_at", "container",
                "config_selector_note", "real_cfg_knob"):
        out.append(f"  - {key}: {COMPARE_SELECTION_MECHANISM[key]}")
    out += ["", f"  - validation: {POLICY_VALIDATION_INSTRUCTION}", ""]

    if resolutions:
        out += ["### Per-scoreboard resolution", "", render_compare_strategy_table(resolutions), ""]
        open_ids = unresolved_compare_strategies(resolutions)
        out.append(f"  - unresolved compare strategies: "
                   f"{', '.join(open_ids) if open_ids else 'none'}")
        out.append("")

    out += ["## SYOSCB-18 -- Match key (a composite key, not a raw object compare)", ""]
    out.append("Why a raw object compare is insufficient, in the library's own code:")
    out.append("")
    for citation in RAW_OBJECT_COMPARE_CITATIONS:
        out.append(f"  - {citation}")
    out.append("")
    for schema in schemas or ():
        out += [f"### {schema['protocol_display']}"
                + (f" -- {schema['route_id']}" if schema.get("route_id") else ""), "",
                render_match_key_table(schema), ""]
        if schema["unresolved_axes"]:
            out.append(f"  - axes still open: {', '.join(schema['unresolved_axes'])}")
            out.append("")
    return "\n".join(out)
