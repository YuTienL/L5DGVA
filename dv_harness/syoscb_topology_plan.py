"""dv_harness/syoscb_topology_plan.py -- SYOSCB-14 (multi-master/multi-slave
scoreboard model), SYOSCB-15 (master -> producer mapping) and SYOSCB-16
(destination / ordering domain -> queue mapping), as a PLAN rather than as
SystemVerilog.

WHAT THIS IS
------------
SYOSCB-14's own preferred pipeline is four stages:

    AMBA_PORT_REGISTRY
      -> Dynamic Scoreboard Topology Generator
      -> Producer / Queue / Route Mapping
      -> SyoSil Configuration

The first two stages already exist and are tested: `amba_port_registry.
build_amba_port_registry()` assembles the registry, and its
`project_to_fabric_topology()` projects it through
`amba_fabric_generator.build_scoreboard_matrix()` into a topology whose route
set scales with what discovery really found. This module is the third and
fourth stages, and ONLY those -- it consumes `amba_route_transform_predictor.
predict_routes()`' output and produces a SyoSil producer/queue/route
configuration PLAN. It re-derives no route, no address region, no ordering
domain and no width: every one of those is read off a prediction that already
carries its own evidence, so a plan entry cannot disagree with the SYOSCB-12
prediction a reviewer read.

THE API SHAPE IS CITED FROM THE REAL SOURCE, NEVER ASSUMED
-----------------------------------------------------------
SYOSCB-15's own instruction is "verify exact SyoSil producer semantics/API
from source before generation. Do not hardcode API calls from assumptions."
`SYOSIL_CFG_API` is that verification as data: one entry per upstream method
this plan depends on, carrying the class, the argument list and the
`file:line` it was read at. `assert_cited_syosil_api_matches_source()` holds
every entry against a real `syoscb_source_audit.audit_syoscb_source()` pass
over the upstream tree, so a citation that drifts from the library fails
loudly instead of quietly planning a call that does not exist.

Three real preconditions the upstream API enforces are therefore checkable
here rather than discovered at Phase-2 elaboration time:

  * `set_producer()` refuses a queue-name list containing duplicates
    (src/cl_syoscb_cfg.svh:154-160) -- `assert_producer_queue_lists_have_no_
    duplicates()`.
  * `set_producer()` refuses a queue name that was never declared
    (src/cl_syoscb_cfg.svh:163-166) -- `assert_every_producer_queue_is_
    declared()`.
  * `set_primary_queue()` refuses a queue that does not exist
    (src/cl_syoscb_cfg.svh:206-209) -- checked by the same declaration rule.

The plan calls `set_queues()` and never `set_queue()`, because
`cl_syoscb::build_phase()` constructs the queue objects itself and registers
each handle with `set_queue()` (src/cl_syoscb.svh:89-95). A configuration that
also called `set_queue()` would be planning work the library already does.

"DO NOT BLINDLY CREATE ONE QUEUE PER PHYSICAL PORT" (SYOSCB-16)
---------------------------------------------------------------
A queue here is keyed on (destination class, ordering domain), never on a
port. Every route sharing that key shares the queue, which is what makes the
plan collapse rather than multiply: three masters into one DDR are one
scoreboard with two queues, not three scoreboards or six queues.
`assert_queues_are_not_per_physical_port()` re-derives the grouping from the
plan's own route index and refuses a plan whose queues fragmented a key -- a
real recomputation, so a hand-edited or reloaded plan is checked too.

The destination CLASS itself is an INPUT, not a derivation. Whether
`soc_top.u_ddr` and `soc_top.u_sram` are one "memory" class or two is a
project decision nobody discovered; inventing one would be exactly the blind
grouping SYOSCB-16 forbids, in the other direction. Supply nothing and each
traced destination becomes its own class, recorded with
`GROUPING_BY_TRACED_DESTINATION` and listed in the plan's own review
questions so a reviewer is told that the per-destination shape is a fallback
rather than a decision.

WHAT THIS DELIBERATELY REFUSES TO DECIDE
-----------------------------------------
  * The COMPARE ALGORITHM. `cl_syoscb_compare_{io,iop,ooo}` is SYOSCB-17's
    decision and is reported as `DEFERRED_TO_SYOSCB_17` on every group, never
    guessed from the ordering domain -- the domain is the KEY items are
    grouped by, the algorithm is what runs inside a group, and conflating the
    two is how an out-of-order route silently gets an in-order comparison.
  * SLAVE-SIDE PRODUCER ATTRIBUTION when more than one master reaches a
    destination and no route carries a predicted id remap. `cl_syoscb_compare_
    iop` matches items only when `get_producer()` agrees on both sides
    (src/cl_syoscb_compare_iop.svh:119), so a slave-side monitor must be able
    to say WHICH master a transaction came from. On a bus with no transaction
    id that is undecidable from the topology, and the group is reported
    blocked with the question named rather than configured on a guess.

PHASE-1 ONLY (SYOSCB-33 / SYOSCB-34)
------------------------------------
Nothing here emits SystemVerilog. A configuration call is a structured
`{api, arguments, citation}` record, never a formatted statement, and every
rendered artifact is run through `syoscb_source_audit.assert_no_emittable_sv()`
and `amba_fabric_discovery.assert_no_bind_statement()`. Nothing is copied out
of the upstream tree: the citations name a path and a line, and the
verification reads that tree read-only.
"""
from __future__ import annotations

import re

from dv_harness.amba_fabric_discovery import assert_no_bind_statement
from dv_harness.amba_port_registry import PortRegistryError
from dv_harness.amba_route_transform_predictor import (
    ORDERING_DOMAIN_PER_ROUTE,
    ORDERING_DOMAIN_PER_ROUTE_AND_ID,
    ROUTE_LEGAL,
    ROUTE_WAIVED,
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
)
from dv_harness.connectivity import REQUIRED_HUMAN_INPUT, render_markdown_table
from dv_harness.syoscb_source_audit import assert_no_emittable_sv


class SyoscbTopologyPlanError(PortRegistryError):
    """A SyoSil configuration plan that fragmented a queue key, named a
    producer no AMBA_PORT_REGISTRY row backs, planned a call the upstream API
    would refuse, or cited an API signature the real source does not carry.

    Subclasses `PortRegistryError` so a caller already handling the
    AMBA_PORT_REGISTRY pipeline's errors handles these too."""


# ===========================================================================
# The upstream API this plan depends on, cited from the real source
# ===========================================================================

#: Every upstream method the plan calls or reasons from, with the argument list
#: and `file:line` READ from `D:/DV/Scoreboard/uvm_syoscb-1.0.2.4`. The
#: `arguments` strings are the declarations verbatim as
#: `syoscb_source_audit.audit_syoscb_source()` indexes them, so
#: `assert_cited_syosil_api_matches_source()` is a bit-for-bit comparison
#: rather than a fuzzy name check.
SYOSIL_CFG_API: tuple = (
    {"api_id": "cl_syoscb_cfg::set_queues",
     "class": "cl_syoscb_cfg", "method": "set_queues",
     "arguments": "(string queue_names[])",
     "file": "src/cl_syoscb_cfg.svh", "line": 67,
     "used_for": "SYOSCB-16: declare the legal queue names for one scoreboard"},
    {"api_id": "cl_syoscb_cfg::exist_queue",
     "class": "cl_syoscb_cfg", "method": "exist_queue",
     "arguments": "(string queue_name)",
     "file": "src/cl_syoscb_cfg.svh", "line": 68,
     "used_for": "the precondition set_producer()/set_primary_queue() check a name against"},
    {"api_id": "cl_syoscb_cfg::set_producer",
     "class": "cl_syoscb_cfg", "method": "set_producer",
     "arguments": "(string producer, queue_names[])",
     "file": "src/cl_syoscb_cfg.svh", "line": 71,
     "used_for": "SYOSCB-15: associate one AMBA master endpoint with the queues it feeds"},
    {"api_id": "cl_syoscb_cfg::get_producer",
     "class": "cl_syoscb_cfg", "method": "get_producer",
     "arguments": "(string producer)",
     "file": "src/cl_syoscb_cfg.svh", "line": 70,
     "used_for": "returns the cl_syoscb_cfg_pl holding that producer's queue-name list"},
    {"api_id": "cl_syoscb_cfg::set_primary_queue",
     "class": "cl_syoscb_cfg", "method": "set_primary_queue",
     "arguments": "(string primary_queue_name)",
     "file": "src/cl_syoscb_cfg.svh", "line": 75,
     "used_for": "SYOSCB-14: which of a group's two queues the compare algorithm walks"},
    {"api_id": "cl_syoscb_cfg_pl::set_list",
     "class": "cl_syoscb_cfg_pl", "method": "set_list",
     "arguments": "(string list[])",
     "file": "src/cl_syoscb_cfg_pl.svh", "line": 40,
     "used_for": "the queue-name list a producer is stored as; a producer is a bare "
                 "string, not a typed master object"},
    {"api_id": "cl_syoscb::add_item",
     "class": "cl_syoscb", "method": "add_item",
     "arguments": "(string queue_name, string producer, uvm_sequence_item item)",
     "file": "src/cl_syoscb.svh", "line": 58,
     "used_for": "the ingest boundary a Phase-2 AMBA adapter reaches with one IR item"},
    {"api_id": "cl_syoscb::build_phase",
     "class": "cl_syoscb", "method": "build_phase",
     "arguments": "(uvm_phase phase)",
     "file": "src/cl_syoscb.svh", "line": 53,
     "used_for": "constructs one queue object per declared name and one subscriber per "
                 "(producer, queue) pair -- the real component count this plan predicts"},
)

#: Where `build_phase` creates one subscriber per (producer, queue-in-its-list)
#: pair. Cited by name because the plan's `planned_subscriber_count` is that
#: loop's own arithmetic, not an estimate.
SUBSCRIBER_FANOUT_CITATION = (
    "uvm_syoscb-1.0.2.4 src/cl_syoscb.svh:114-125 -- build_phase() creates one "
    "cl_syoscb_subscriber per (producer, queue name in that producer's list) pair")

#: `set_producer()`'s two documented refusals, cited so the plan's own
#: assertions say which upstream lines they are enforcing.
SET_PRODUCER_DUPLICATE_QUEUE_CITATION = (
    "uvm_syoscb-1.0.2.4 src/cl_syoscb_cfg.svh:154-160 -- set_producer() returns 1'b0 "
    "when the queue-name list contains duplicates")
SET_PRODUCER_UNKNOWN_QUEUE_CITATION = (
    "uvm_syoscb-1.0.2.4 src/cl_syoscb_cfg.svh:163-166 -- set_producer() returns 1'b0 "
    "when a named queue was never declared")
SET_PRIMARY_QUEUE_UNKNOWN_CITATION = (
    "uvm_syoscb-1.0.2.4 src/cl_syoscb_cfg.svh:206-209 -- set_primary_queue() returns "
    "1'b0 when the named queue does not exist")
IOP_PRODUCER_MATCH_CITATION = (
    "uvm_syoscb-1.0.2.4 src/cl_syoscb_compare_iop.svh:119 -- the in-order-per-producer "
    "algorithm compares two items only when their producers are equal")
BUILD_PHASE_CREATES_QUEUE_OBJECTS_CITATION = (
    "uvm_syoscb-1.0.2.4 src/cl_syoscb.svh:89-95 -- build_phase() constructs each queue "
    "and registers its handle with set_queue(), so a configuration plan declares names "
    "with set_queues() and never sets a handle itself")


def verify_cited_syosil_api(audit) -> list:
    """Hold every `SYOSIL_CFG_API` citation against a real source audit.

    Returns one row per citation: `MATCHES`, `CLASS_NOT_FOUND`,
    `METHOD_NOT_FOUND`, or `SIGNATURE_DRIFTED` with the real declaration
    beside the cited one. Reporting rather than raising is the point -- a
    caller that wants the hard check calls
    `assert_cited_syosil_api_matches_source()`, and a caller producing a
    review artifact wants the table."""
    rows: list = []
    for entry in SYOSIL_CFG_API:
        found = audit.class_named(entry["class"])
        if found is None:
            rows.append({**entry, "status": "CLASS_NOT_FOUND", "observed": None})
            continue
        methods = [m for m in found["api"] if m["name"] == entry["method"]]
        if not methods:
            rows.append({**entry, "status": "METHOD_NOT_FOUND", "observed": None})
            continue
        observed = [{"arguments": m.get("arguments"), "file": m["file"], "line": m["line"]}
                    for m in methods]
        exact = [o for o in observed
                 if o["arguments"] == entry["arguments"]
                 and o["file"] == entry["file"] and o["line"] == entry["line"]]
        rows.append({**entry,
                     "status": "MATCHES" if exact else "SIGNATURE_DRIFTED",
                     "observed": observed})
    return rows


def assert_cited_syosil_api_matches_source(audit) -> None:
    """SYOSCB-15's "Do not hardcode API calls from assumptions", enforced.

    A plan whose cited API has drifted from the library is planning calls
    against a version that is not there -- which is worse than an unplanned
    integration, because it looks verified."""
    bad = [r for r in verify_cited_syosil_api(audit) if r["status"] != "MATCHES"]
    if bad:
        raise SyoscbTopologyPlanError("SYOSIL_CITED_API_DOES_NOT_MATCH_SOURCE", {
            "root": audit.root,
            "citations": [{"api_id": r["api_id"], "status": r["status"],
                           "cited": f"{r['file']}:{r['line']} {r['arguments']}",
                           "observed": r["observed"]} for r in bad],
            "hint": "re-read the upstream declaration and update SYOSIL_CFG_API; never "
                    "plan a call whose signature this repo cannot cite from source"})


# ===========================================================================
# SYOSCB-16: destination class and queue identity
# ===========================================================================

#: A destination class a caller really supplied -- a project decision, cited.
GROUPING_BY_DESTINATION_CLASS = "DESTINATION_CLASS_SUPPLIED"
#: No destination class was supplied, so the traced destination endpoint is
#: its own class. A FALLBACK, reported as one: SYOSCB-16's "do not blindly
#: create one queue per physical port" is a rule about not defaulting, and a
#: fallback presented as a decision is exactly that default.
GROUPING_BY_TRACED_DESTINATION = "TRACED_DESTINATION_ENDPOINT_FALLBACK"

#: The two observation sides one destination group compares. A queue is a
#: named bucket with no ordering semantics of its own (`cl_syoscb_queue`
#: exposes only `add_item(producer, item)`), and `cl_syoscb_compare_base`
#: compares the primary queue against the others -- so the comparison a route
#: needs is "what the masters sent" against "what arrived", i.e. two queues.
QUEUE_SIDE_MASTER = "MASTER_SIDE"
QUEUE_SIDE_SLAVE = "SLAVE_SIDE"
QUEUE_SIDES: tuple = (QUEUE_SIDE_MASTER, QUEUE_SIDE_SLAVE)

#: SYOSCB-17 owns the compare-algorithm choice. Named, not blank, so a reader
#: of a group entry sees an owner rather than an omission.
COMPARE_STRATEGY_DEFERRED = "DEFERRED_TO_SYOSCB_17"

#: Why a discovered route carries no queue.
EXCLUDED_ROUTE_WAIVED = "ROUTE_WAIVED_NO_EXPECTED_TRAFFIC"
EXCLUDED_ORDERING_DOMAIN_UNRESOLVED = "ORDERING_DOMAIN_UNRESOLVED"

#: How a slave-side monitor's item is attributed to the producer that sent it.
ATTRIBUTION_SINGLE_MASTER = "UNAMBIGUOUS_SINGLE_MASTER_ROUTE"
ATTRIBUTION_BY_FABRIC_ID = "IDENTIFIED_BY_PREDICTED_FABRIC_TRANSACTION_ID"

#: A producer/queue name becomes part of a real UVM component name
#: (`{producer, "_", queue, "_subscr"}`, src/cl_syoscb.svh:120), so a name
#: carrying a dot or a bracket would produce an illegal component path.
_SYOSIL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9]+")


def _safe_name(raw: str) -> str:
    return _NAME_SAFE_RE.sub("_", str(raw or "")).strip("_").upper()


def destination_class_of(prediction: dict, destination_classes=None) -> dict:
    """The destination class one route's slave endpoint belongs to.

    Keyed on the traced `slave_endpoint` hierarchy, falling back to the
    slave's registry `port_id` key, because a caller supplying classes has
    only those two identifiers to name them by."""
    supplied = destination_classes or {}
    endpoint = prediction.get("slave_endpoint")
    port_id = prediction.get("slave_port_id")
    for key in (endpoint, port_id):
        if key in supplied:
            return {"destination_class": _safe_name(supplied[key]),
                    "grouping_basis": GROUPING_BY_DESTINATION_CLASS,
                    "evidence": [f"caller supplied destination class "
                                 f"{supplied[key]!r} for {key}"]}
    return {"destination_class": _safe_name(port_id or endpoint),
            "grouping_basis": GROUPING_BY_TRACED_DESTINATION,
            "evidence": [f"no destination class was supplied for {endpoint}; the traced "
                         f"destination is its own class",
                         'SYOSCB-16\'s own rule is "Do not blindly create one queue per '
                         'physical port": confirm this per-destination shape is intended, '
                         'or supply a destination class that groups it with others']}


def _ordering_domain(prediction: dict) -> dict:
    return prediction["responsibilities"]["ordering_domain"]


def _routing_legality(prediction: dict) -> dict:
    return prediction["responsibilities"]["routing_legality"]


def route_index(predictions, destination_classes=None) -> list:
    """One row per predicted route, carrying the two facts the grouping is
    keyed on and the reason a route is excluded.

    Kept ON the plan so `assert_queues_are_not_per_physical_port()` can
    re-derive the grouping from the plan alone -- including a plan reloaded
    from disk or edited by hand, which is the only case where fragmenting a
    key is actually reachable."""
    rows: list = []
    for prediction in predictions or ():
        klass = destination_class_of(prediction, destination_classes)
        ordering = _ordering_domain(prediction)
        legality = _routing_legality(prediction)
        ordering_known = ordering["status"] == TRANSFORM_PREDICTED_FROM_TOPOLOGY
        excluded = None
        if legality["value"].get("pair_status") == ROUTE_WAIVED:
            excluded = EXCLUDED_ROUTE_WAIVED
        elif not ordering_known:
            excluded = EXCLUDED_ORDERING_DOMAIN_UNRESOLVED
        rows.append({
            "route_id": prediction["route_id"],
            "master_endpoint": prediction["master_endpoint"],
            "slave_endpoint": prediction["slave_endpoint"],
            "master_port_id": prediction["master_port_id"],
            "slave_port_id": prediction["slave_port_id"],
            "destination_class": klass["destination_class"],
            "grouping_basis": klass["grouping_basis"],
            "grouping_evidence": klass["evidence"],
            "ordering_domain_key": (ordering["value"]["domain_key"] if ordering_known
                                    else REQUIRED_HUMAN_INPUT),
            "route_ordering_expectation": (
                ordering["value"]["route_ordering_expectation"] if ordering_known
                else REQUIRED_HUMAN_INPUT),
            "ordering_tolerance_depth": (
                ordering["value"]["ordering_tolerance_depth"] if ordering_known
                else REQUIRED_HUMAN_INPUT),
            "ordering_evidence": list(ordering.get("evidence") or []),
            "id_remap_status": prediction["responsibilities"]["id_remap"]["status"],
            "id_remap_evidence": list(
                prediction["responsibilities"]["id_remap"].get("evidence") or []),
            "excluded": excluded,
            "excluded_evidence": (list(ordering.get("evidence") or [])
                                  if excluded == EXCLUDED_ORDERING_DOMAIN_UNRESOLVED
                                  else list(legality.get("evidence") or [])
                                  if excluded == EXCLUDED_ROUTE_WAIVED else []),
        })
    return rows


def _group_key(row: dict) -> tuple:
    return (row["destination_class"], row["ordering_domain_key"])


def _scoreboard_id(destination_class: str, domain_key: str) -> str:
    return f"SB_{destination_class}__{_safe_name(domain_key)}"


def _slave_side_attribution(rows) -> dict:
    """Whether a slave-side monitor can name the producer of an item it saw.

    `cl_syoscb_compare_iop` matches items only when both sides report the same
    producer, so this is not a nicety: a group whose slave side cannot be
    attributed has no producer to register the slave-side queue under, and
    registering one anyway would claim an attribution nothing established."""
    masters = sorted({r["master_endpoint"] for r in rows})
    if len(masters) == 1:
        return {"status": ATTRIBUTION_SINGLE_MASTER,
                "evidence": [f"only {masters[0]} routes into this destination and "
                             f"ordering domain, so every item observed at the "
                             f"destination came from it",
                             IOP_PRODUCER_MATCH_CITATION]}
    unresolved = [r for r in rows
                  if r["id_remap_status"] != TRANSFORM_PREDICTED_FROM_TOPOLOGY]
    if not unresolved:
        evidence = [f"{len(masters)} masters reach this destination; every route carries "
                    f"a predicted fabric transaction id, so the id identifies the "
                    f"originating master", IOP_PRODUCER_MATCH_CITATION]
        for row in rows:
            evidence += [f"{row['route_id']}: {line}" for line in row["id_remap_evidence"]]
        return {"status": ATTRIBUTION_BY_FABRIC_ID, "evidence": evidence}
    return {"status": REQUIRED_HUMAN_INPUT,
            "evidence": [f"{len(masters)} masters reach this destination and "
                         + ", ".join(sorted(r["route_id"] for r in unresolved))
                         + " carry no predicted fabric transaction id, so an item observed "
                           "at the destination cannot be attributed to the master that "
                           "sent it",
                         IOP_PRODUCER_MATCH_CITATION,
                         "supply the fabric's own master-identification evidence (a "
                         "sideband master id, a per-master slave port, or an address "
                         "window that only one master may use) rather than assuming one"]}


def group_routes_into_scoreboards(predictions, *, destination_classes=None) -> dict:
    """SYOSCB-14's Dynamic Scoreboard Topology stage, as groups.

    One group per (destination class, ordering domain) -- NOT one per route,
    which is the "4 Masters x 8 Slaves = 32 independent scoreboard instances"
    shape the doc names as the thing to avoid. The group count is a
    consequence of what discovery found; nothing here carries a constant."""
    routes = route_index(predictions, destination_classes)
    groups: dict = {}
    for row in routes:
        if row["excluded"]:
            continue
        key = _group_key(row)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "scoreboard_id": _scoreboard_id(*key),
                "destination_class": row["destination_class"],
                "grouping_basis": row["grouping_basis"],
                "grouping_evidence": list(row["grouping_evidence"]),
                "ordering_domain_key": row["ordering_domain_key"],
                "route_ordering_expectation": row["route_ordering_expectation"],
                "ordering_tolerance_depth": row["ordering_tolerance_depth"],
                "ordering_evidence": list(row["ordering_evidence"]),
                "compare_strategy": COMPARE_STRATEGY_DEFERRED,
                "route_ids": [],
                "master_endpoints": [],
                "slave_endpoints": [],
            }
        group["route_ids"].append(row["route_id"])
        for field, value in (("master_endpoints", row["master_endpoint"]),
                             ("slave_endpoints", row["slave_endpoint"])):
            if value not in group[field]:
                group[field].append(value)

    ordered = [groups[k] for k in sorted(groups)]
    by_id = {r["route_id"]: r for r in routes}
    for group in ordered:
        group["slave_side_producer_attribution"] = _slave_side_attribution(
            [by_id[r] for r in group["route_ids"]])
    return {"groups": ordered,
            "routes": routes,
            "excluded_routes": [r for r in routes if r["excluded"]]}


def plan_queues(groups) -> list:
    """SYOSCB-16's queue plan: two queues per group, named for the destination
    class and ordering domain they represent -- never for a port.

    The master-side queue is proposed as the primary one: `cl_syoscb_compare_
    base::get_primary_queue_name()` selects the queue the algorithm walks, and
    walking the stimulus side means an unmatched primary item is a transaction
    that never arrived -- the finding a bus scoreboard exists to produce."""
    queues: list = []
    for group in groups or ():
        for side in QUEUE_SIDES:
            queues.append({
                "queue_name": f"{group['scoreboard_id']}_{side}",
                "scoreboard_id": group["scoreboard_id"],
                "side": side,
                "represents_destination_class": group["destination_class"],
                "represents_ordering_domain": group["ordering_domain_key"],
                "member_route_ids": list(group["route_ids"]),
                "is_primary": side == QUEUE_SIDE_MASTER,
                "basis": list(group["grouping_evidence"]) + list(group["ordering_evidence"]),
            })
    return queues


# ===========================================================================
# SYOSCB-15: master endpoint -> producer
# ===========================================================================

#: Which AMBA_PORT_REGISTRY column a producer name is derived from. Named as
#: data so `assert_producer_names_derive_from_registry()` checks the real
#: column rather than a convention described in prose. AMBA-22 already refuses
#: a generic `master0` port_id, so deriving from it inherits that refusal
#: instead of re-implementing it.
PRODUCER_NAME_SOURCE_COLUMN = "port_id"


def map_masters_to_producers(rows, grouping: dict) -> list:
    """SYOSCB-15's "AMBA Master Endpoint -> SyoSil Producer", one entry per
    traced master endpoint that really reaches a grouped destination.

    A producer is a bare string in this API (`set_producer(string producer,
    queue_names[])`), so the mapping's whole content is WHICH queues that
    string may feed. A master always feeds the master-side queue of every
    group it routes into -- the monitor at its own port observes its own
    transactions, which is unambiguous. It feeds the SLAVE-side queue only
    where that group's attribution resolved; where it did not, the queue is
    withheld and the reason is carried, because `set_producer()` naming a
    queue whose items cannot be attributed to that producer would be a claim
    nothing supports."""
    by_port_id = {r.get("port_id"): r for r in rows or ()}
    producers: dict = {}
    for group in grouping["groups"]:
        attribution = group["slave_side_producer_attribution"]
        slave_side_available = attribution["status"] != REQUIRED_HUMAN_INPUT
        member_rows = [r for r in grouping["routes"] if r["route_id"] in group["route_ids"]]
        for row in member_rows:
            name = row["master_port_id"]
            producer = producers.get(name)
            if producer is None:
                registry_row = by_port_id.get(name)
                producer = producers[name] = {
                    "producer_name": name,
                    "master_endpoint": row["master_endpoint"],
                    "derived_from": f"AMBA_PORT_REGISTRY {name}."
                                    f"{PRODUCER_NAME_SOURCE_COLUMN}",
                    "registry_row_id": (registry_row or {}).get("row_id"),
                    "protocol": (registry_row or {}).get("protocol", REQUIRED_HUMAN_INPUT),
                    "queue_names": [],
                    "route_ids": [],
                    "withheld_queues": [],
                }
            if row["route_id"] not in producer["route_ids"]:
                producer["route_ids"].append(row["route_id"])
            master_queue = f"{group['scoreboard_id']}_{QUEUE_SIDE_MASTER}"
            if master_queue not in producer["queue_names"]:
                producer["queue_names"].append(master_queue)
            slave_queue = f"{group['scoreboard_id']}_{QUEUE_SIDE_SLAVE}"
            if slave_side_available:
                if slave_queue not in producer["queue_names"]:
                    producer["queue_names"].append(slave_queue)
            elif not any(w["queue_name"] == slave_queue
                         for w in producer["withheld_queues"]):
                producer["withheld_queues"].append({
                    "queue_name": slave_queue,
                    "scoreboard_id": group["scoreboard_id"],
                    "reason": REQUIRED_HUMAN_INPUT,
                    "evidence": list(attribution["evidence"])})
    return [producers[k] for k in sorted(producers)]


# ===========================================================================
# The composed plan
# ===========================================================================

def build_syoscb_configuration_plan(rows, predictions, *,
                                    destination_classes=None) -> dict:
    """SYOSCB-14's third and fourth stages: Producer/Queue/Route Mapping and
    the SyoSil Configuration that follows from it.

    `rows` is the AMBA_PORT_REGISTRY and is used ONLY to back producer
    identity; every routing, ordering and transform fact comes from
    `predictions`, which already carry their own evidence."""
    grouping = group_routes_into_scoreboards(
        predictions, destination_classes=destination_classes)
    queues = plan_queues(grouping["groups"])
    producers = map_masters_to_producers(rows, grouping)

    blocked = [g["scoreboard_id"] for g in grouping["groups"]
               if g["slave_side_producer_attribution"]["status"] == REQUIRED_HUMAN_INPUT]
    legal_routes = [r for r in grouping["routes"] if not r["excluded"]]
    plan = {
        "scoreboards": grouping["groups"],
        "queues": queues,
        "producers": producers,
        "routes": grouping["routes"],
        "excluded_routes": grouping["excluded_routes"],
        "scoreboards_blocked_on_producer_attribution": blocked,
        "scaling": {
            "discovered_master_count": len({r["master_endpoint"] for r in legal_routes}),
            "discovered_slave_count": len({r["slave_endpoint"] for r in legal_routes}),
            "legal_route_count": len(legal_routes),
            "naive_one_scoreboard_per_route_count": len(legal_routes),
            "planned_scoreboard_count": len(grouping["groups"]),
            "planned_queue_count": len(queues),
            "planned_subscriber_count": sum(len(p["queue_names"]) for p in producers),
            "subscriber_count_basis": SUBSCRIBER_FANOUT_CITATION,
            "basis": "every count is derived from the AMBA_PORT_REGISTRY routes discovery "
                     "produced; SYOSCB-14's N x M instance count appears only as the "
                     "naive figure this plan is measured against",
        },
        "api_citations": [dict(e) for e in SYOSIL_CFG_API],
        "implementation_status": "PHASE_2_ONLY_NO_SV_EMITTED_HERE",
    }
    assert_plan_complete(plan)
    assert_queues_are_not_per_physical_port(plan)
    assert_not_one_scoreboard_per_route(plan)
    assert_every_producer_queue_is_declared(plan)
    assert_producer_queue_lists_have_no_duplicates(plan)
    assert_names_are_legal_syosil_identifiers(plan)
    assert_producer_names_derive_from_registry(plan, rows)
    return plan


def syosil_configuration_calls(plan: dict) -> list:
    """The ordered `cl_syoscb_cfg` calls this plan proposes, as STRUCTURED
    records -- `{api_id, arguments, citation}` -- never as formatted
    SystemVerilog.

    Only groups whose producer attribution resolved appear: a group missing a
    slave-side producer has no configuration a Phase-2 implementer could
    write, and emitting one anyway would hand them a call that silently
    compares nothing."""
    by_api = {e["api_id"]: e for e in SYOSIL_CFG_API}
    calls: list = []
    blocked = set(plan.get("scoreboards_blocked_on_producer_attribution") or ())
    for group in plan["scoreboards"]:
        if group["scoreboard_id"] in blocked:
            continue
        queues = [q for q in plan["queues"]
                  if q["scoreboard_id"] == group["scoreboard_id"]]
        names = [q["queue_name"] for q in queues]
        primary = next((q["queue_name"] for q in queues if q["is_primary"]), None)
        calls.append({"scoreboard_id": group["scoreboard_id"],
                      "api_id": "cl_syoscb_cfg::set_queues",
                      "arguments": {"queue_names": names},
                      "citation": f"{by_api['cl_syoscb_cfg::set_queues']['file']}:"
                                  f"{by_api['cl_syoscb_cfg::set_queues']['line']}",
                      "basis": [BUILD_PHASE_CREATES_QUEUE_OBJECTS_CITATION]})
        calls.append({"scoreboard_id": group["scoreboard_id"],
                      "api_id": "cl_syoscb_cfg::set_primary_queue",
                      "arguments": {"primary_queue_name": primary},
                      "citation": f"{by_api['cl_syoscb_cfg::set_primary_queue']['file']}:"
                                  f"{by_api['cl_syoscb_cfg::set_primary_queue']['line']}",
                      "basis": [SET_PRIMARY_QUEUE_UNKNOWN_CITATION]})
        for producer in plan["producers"]:
            feeds = [n for n in producer["queue_names"] if n in names]
            if not feeds:
                continue
            calls.append({"scoreboard_id": group["scoreboard_id"],
                          "api_id": "cl_syoscb_cfg::set_producer",
                          "arguments": {"producer": producer["producer_name"],
                                        "queue_names": feeds},
                          "citation": f"{by_api['cl_syoscb_cfg::set_producer']['file']}:"
                                      f"{by_api['cl_syoscb_cfg::set_producer']['line']}",
                          "basis": [SET_PRODUCER_UNKNOWN_QUEUE_CITATION,
                                    SET_PRODUCER_DUPLICATE_QUEUE_CITATION]})
    return calls


def unresolved_plan_questions(plan: dict) -> list:
    """Everything in this plan a human must answer before it can be
    configured, each with the evidence that says why nothing decided it.

    Deliberately includes the destination-class FALLBACK: a per-destination
    grouping nobody confirmed is precisely SYOSCB-16's "do not blindly create
    one queue per physical port", and reporting it only in a field a reader
    might not open is how a fallback becomes a default."""
    questions: list = []
    for group in plan["scoreboards"]:
        attribution = group["slave_side_producer_attribution"]
        if attribution["status"] == REQUIRED_HUMAN_INPUT:
            questions.append({
                "subject": group["scoreboard_id"],
                "question": "SLAVE_SIDE_PRODUCER_ATTRIBUTION",
                "evidence": list(attribution["evidence"])})
        if group["grouping_basis"] == GROUPING_BY_TRACED_DESTINATION:
            questions.append({
                "subject": group["scoreboard_id"],
                "question": "DESTINATION_CLASS_NOT_SUPPLIED",
                "evidence": list(group["grouping_evidence"])})
        if group["ordering_tolerance_depth"] == REQUIRED_HUMAN_INPUT:
            questions.append({
                "subject": group["scoreboard_id"],
                "question": "ORDERING_TOLERANCE_DEPTH",
                "evidence": list(group["ordering_evidence"])})
        questions.append({
            "subject": group["scoreboard_id"],
            "question": "COMPARE_STRATEGY",
            "evidence": [f"the ordering domain is {group['ordering_domain_key']} and the "
                         f"route expectation is {group['route_ordering_expectation']}; "
                         f"which cl_syoscb_compare_* algorithm implements that is "
                         f"SYOSCB-17's decision and is not made here"]})
    for row in plan["excluded_routes"]:
        questions.append({"subject": row["route_id"], "question": row["excluded"],
                          "evidence": list(row["excluded_evidence"])})
    return questions


# ===========================================================================
# Assertions
# ===========================================================================

_GROUP_REQUIRED_KEYS: tuple = (
    "scoreboard_id", "destination_class", "grouping_basis", "ordering_domain_key",
    "route_ordering_expectation", "compare_strategy", "route_ids",
    "slave_side_producer_attribution",
)


def assert_plan_complete(plan: dict) -> None:
    """Every group carries the fields a reviewer needs, every route is either
    grouped or excluded with a reason, and every group has both of its
    queues. An absent key is how a downstream consumer defaults a decision
    nobody made."""
    grouped = {r for g in plan.get("scoreboards") or () for r in g["route_ids"]}
    excluded = {r["route_id"] for r in plan.get("excluded_routes") or ()}
    orphan = sorted({r["route_id"] for r in plan.get("routes") or ()} - grouped - excluded)
    if orphan:
        raise SyoscbTopologyPlanError("SYOSCB_PLAN_ROUTE_NEITHER_GROUPED_NOR_EXCLUDED", {
            "route_ids": orphan,
            "hint": "a discovered route must land in a scoreboard group or be excluded "
                    "with a stated reason; silently dropping it hides a route nobody "
                    "decided how to check"})
    for group in plan.get("scoreboards") or ():
        missing = [k for k in _GROUP_REQUIRED_KEYS if not group.get(k)]
        if missing:
            raise SyoscbTopologyPlanError("SYOSCB_PLAN_GROUP_INCOMPLETE", {
                "scoreboard_id": group.get("scoreboard_id"), "missing_fields": missing})
        sides = sorted(q["side"] for q in plan.get("queues") or ()
                       if q["scoreboard_id"] == group["scoreboard_id"])
        if sides != sorted(QUEUE_SIDES):
            raise SyoscbTopologyPlanError("SYOSCB_PLAN_GROUP_QUEUE_SIDES_INCOMPLETE", {
                "scoreboard_id": group["scoreboard_id"], "sides": sides,
                "expected": sorted(QUEUE_SIDES),
                "hint": "a comparison needs both observation sides; one queue alone has "
                        "nothing to be compared against"})


def assert_queues_are_not_per_physical_port(plan: dict) -> None:
    """SYOSCB-16: "Do not blindly create one queue per physical port."

    Re-derives the grouping from the plan's own route index and refuses a plan
    in which two routes sharing a (destination class, ordering domain) landed
    in different scoreboards -- the fragmentation that turns a destination
    grouping back into a per-port one."""
    by_route = {r["route_id"]: r for r in plan.get("routes") or ()}
    key_to_group: dict = {}
    for group in plan.get("scoreboards") or ():
        for route_id in group["route_ids"]:
            row = by_route.get(route_id)
            if row is None:
                raise SyoscbTopologyPlanError("SYOSCB_PLAN_GROUP_CITES_UNKNOWN_ROUTE", {
                    "scoreboard_id": group["scoreboard_id"], "route_id": route_id})
            key = _group_key(row)
            owner = key_to_group.setdefault(key, group["scoreboard_id"])
            if owner != group["scoreboard_id"]:
                raise SyoscbTopologyPlanError("SYOSCB_PLAN_QUEUE_KEY_FRAGMENTED", {
                    "destination_class": key[0], "ordering_domain_key": key[1],
                    "scoreboard_ids": sorted({owner, group["scoreboard_id"]}),
                    "route_id": route_id,
                    "hint": "routes sharing a destination class and ordering domain share "
                            "one scoreboard and one queue pair; splitting them recreates "
                            "the per-physical-port queue shape SYOSCB-16 forbids"})


def assert_not_one_scoreboard_per_route(plan: dict) -> None:
    """SYOSCB-14: "Do not hard-code one scoreboard per N x M path unless the
    architecture truly requires it."

    A one-to-one plan is legal when every route really does have its own
    destination class and ordering domain -- a 1x1 fabric, or four masters
    each with their own private slave. It is a defect only when two routes
    that SHARE a key were nonetheless given separate scoreboards, which is
    what this refuses."""
    scaling = plan.get("scaling") or {}
    if scaling.get("planned_scoreboard_count") != scaling.get("legal_route_count"):
        return
    keys = [_group_key(r) for r in plan.get("routes") or () if not r["excluded"]]
    shared = sorted({k for k in keys if keys.count(k) > 1})
    if shared:
        raise SyoscbTopologyPlanError("SYOSCB_PLAN_ONE_SCOREBOARD_PER_ROUTE", {
            "planned_scoreboard_count": scaling.get("planned_scoreboard_count"),
            "legal_route_count": scaling.get("legal_route_count"),
            "shared_keys": [{"destination_class": k[0], "ordering_domain_key": k[1]}
                            for k in shared],
            "hint": "these routes share a destination class and ordering domain, so one "
                    "scoreboard per route is the N x M instance count SYOSCB-14 names as "
                    "the shape to avoid"})


def assert_every_producer_queue_is_declared(plan: dict) -> None:
    """`set_producer()` returns 1'b0 for a queue name that was never declared
    (src/cl_syoscb_cfg.svh:163-166). A plan that would trip that check is a
    plan whose Phase-2 configuration silently does nothing."""
    declared = {q["queue_name"] for q in plan.get("queues") or ()}
    for producer in plan.get("producers") or ():
        undeclared = sorted(set(producer["queue_names"]) - declared)
        if undeclared:
            raise SyoscbTopologyPlanError("SYOSCB_PLAN_PRODUCER_QUEUE_NOT_DECLARED", {
                "producer": producer["producer_name"], "queue_names": undeclared,
                "citation": SET_PRODUCER_UNKNOWN_QUEUE_CITATION})


def assert_producer_queue_lists_have_no_duplicates(plan: dict) -> None:
    """`set_producer()` returns 1'b0 for a duplicate queue name in the list
    (src/cl_syoscb_cfg.svh:154-160)."""
    for producer in plan.get("producers") or ():
        names = list(producer["queue_names"])
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise SyoscbTopologyPlanError("SYOSCB_PLAN_PRODUCER_QUEUE_DUPLICATED", {
                "producer": producer["producer_name"], "queue_names": duplicates,
                "citation": SET_PRODUCER_DUPLICATE_QUEUE_CITATION})


def assert_names_are_legal_syosil_identifiers(plan: dict) -> None:
    """Every producer and queue name becomes part of a real UVM component name
    (`{producer, "_", queue, "_subscr"}`, src/cl_syoscb.svh:120), so a name
    carrying a dot, a bracket or a leading digit produces an illegal component
    path. A traced hierarchy string used raw is exactly that."""
    offenders = (
        [{"kind": "queue", "name": q["queue_name"]} for q in plan.get("queues") or ()
         if not _SYOSIL_NAME_RE.match(str(q["queue_name"]))]
        + [{"kind": "producer", "name": p["producer_name"]}
           for p in plan.get("producers") or ()
           if not _SYOSIL_NAME_RE.match(str(p["producer_name"]))])
    if offenders:
        raise SyoscbTopologyPlanError("SYOSCB_PLAN_ILLEGAL_SYOSIL_NAME", {
            "names": offenders,
            "hint": "a producer/queue name is concatenated into a UVM component name at "
                    "src/cl_syoscb.svh:120; derive it from the AMBA_PORT_REGISTRY port_id "
                    "rather than from a traced hierarchy path"})


def assert_producer_names_derive_from_registry(plan: dict, rows) -> None:
    """SYOSCB-15's producer names must come from real AMBA_PORT_REGISTRY rows.

    AMBA-22 already refuses a generic `master0`/`slave0` port_id, so deriving
    the producer name from `port_id` inherits that refusal. A producer name
    matching no registry row is one somebody typed -- and a positional
    `master0` producer is exactly what would renumber the moment discovery
    order changed."""
    known = {r.get("port_id") for r in rows or ()}
    unknown = sorted({p["producer_name"] for p in plan.get("producers") or ()
                      if p["producer_name"] not in known})
    if unknown:
        raise SyoscbTopologyPlanError("SYOSCB_PLAN_PRODUCER_NOT_IN_PORT_REGISTRY", {
            "producers": unknown,
            "hint": f"a producer name is derived from an AMBA_PORT_REGISTRY row's "
                    f"{PRODUCER_NAME_SOURCE_COLUMN}; a name no row backs cannot be traced "
                    f"to the fabric port it claims to represent"})


# ===========================================================================
# Reporting
# ===========================================================================

def render_scoreboard_group_table(plan: dict) -> str:
    rows = [{"scoreboard_id": g["scoreboard_id"],
             "destination_class": g["destination_class"],
             "grouping_basis": g["grouping_basis"],
             "ordering_domain_key": g["ordering_domain_key"],
             "route_ordering_expectation": g["route_ordering_expectation"],
             "compare_strategy": g["compare_strategy"],
             "routes": ", ".join(g["route_ids"]),
             "attribution": g["slave_side_producer_attribution"]["status"]}
            for g in plan.get("scoreboards") or ()]
    return render_markdown_table(
        [("scoreboard_id", "Scoreboard"), ("destination_class", "Destination Class"),
         ("grouping_basis", "Grouping Basis"), ("ordering_domain_key", "Ordering Domain"),
         ("route_ordering_expectation", "Route Expectation"),
         ("compare_strategy", "Compare Strategy"), ("routes", "Routes"),
         ("attribution", "Slave-Side Producer Attribution")], rows,
        empty_note="(no discovered route could be grouped, so no scoreboard is planned)")


def render_queue_table(plan: dict) -> str:
    rows = [{"queue_name": q["queue_name"], "scoreboard_id": q["scoreboard_id"],
             "side": q["side"], "represents": q["represents_destination_class"],
             "ordering_domain": q["represents_ordering_domain"],
             "primary": "yes" if q["is_primary"] else "no",
             "routes": ", ".join(q["member_route_ids"])}
            for q in plan.get("queues") or ()]
    return render_markdown_table(
        [("queue_name", "Queue"), ("scoreboard_id", "Scoreboard"), ("side", "Observed Side"),
         ("represents", "Represents"), ("ordering_domain", "Ordering Domain"),
         ("primary", "Primary"), ("routes", "Routes It Carries")], rows,
        empty_note="(no queue is planned)")


def render_producer_table(plan: dict) -> str:
    rows = [{"producer_name": p["producer_name"], "protocol": p["protocol"],
             "master_endpoint": p["master_endpoint"], "derived_from": p["derived_from"],
             "queue_names": ", ".join(p["queue_names"]),
             "withheld": ", ".join(w["queue_name"] for w in p["withheld_queues"]) or "(none)"}
            for p in plan.get("producers") or ()]
    return render_markdown_table(
        [("producer_name", "Producer"), ("protocol", "Protocol"),
         ("master_endpoint", "AMBA Master Endpoint"), ("derived_from", "Derived From"),
         ("queue_names", "Queues It May Feed"),
         ("withheld", "Queues Withheld Pending Attribution")], rows,
        empty_note="(no traced master reaches a grouped destination, so no producer is "
                   "planned)")


def render_configuration_call_table(plan: dict) -> str:
    rows = [{"scoreboard_id": c["scoreboard_id"], "api_id": c["api_id"],
             "arguments": "; ".join(f"{k}={v}" for k, v in c["arguments"].items()),
             "citation": c["citation"]}
            for c in syosil_configuration_calls(plan)]
    return render_markdown_table(
        [("scoreboard_id", "Scoreboard"), ("api_id", "SyoSil API"),
         ("arguments", "Arguments"), ("citation", "Cited At")], rows,
        empty_note="(every planned scoreboard is blocked on an open question, so no "
                   "configuration call is proposed)")


def render_api_citation_table(plan: dict) -> str:
    rows = [{"api_id": e["api_id"], "arguments": e["arguments"],
             "location": f"{e['file']}:{e['line']}", "used_for": e["used_for"]}
            for e in plan.get("api_citations") or ()]
    return render_markdown_table(
        [("api_id", "Upstream API"), ("arguments", "Declared Arguments"),
         ("location", "Read At"), ("used_for", "Used For")], rows)


def render_open_question_table(plan: dict) -> str:
    rows = [{"subject": q["subject"], "question": q["question"],
             "evidence": " | ".join(q["evidence"])}
            for q in unresolved_plan_questions(plan)]
    return render_markdown_table(
        [("subject", "Subject"), ("question", "Open Question"), ("evidence", "Why")], rows,
        empty_note="(no open question)")


def render_syoscb_configuration_plan_report(plan: dict) -> str:
    """The SYOSCB-14/15/16 review artifact.

    Self-checked against both emission gates for the reason SYOSCB-33 exists:
    a Phase-1 planning document that rendered compilable SystemVerilog would be
    a way past the approval gate standing between this plan and any code."""
    scaling = plan["scaling"]
    lines = [
        "# SYOSCB-14 / SYOSCB-15 / SYOSCB-16 SyoSil Configuration Plan", "",
        f"{scaling['legal_route_count']} legal route(s) across "
        f"{scaling['discovered_master_count']} traced master(s) and "
        f"{scaling['discovered_slave_count']} traced destination(s) map to "
        f"{scaling['planned_scoreboard_count']} scoreboard instance(s), "
        f"{scaling['planned_queue_count']} queue(s) and "
        f"{len(plan['producers'])} producer(s).", "",
        f"SYOSCB-14's naive one-scoreboard-per-route shape would be "
        f"{scaling['naive_one_scoreboard_per_route_count']} instance(s). "
        f"{scaling['planned_subscriber_count']} subscriber(s) follow from the "
        f"producer/queue pairs -- {scaling['subscriber_count_basis']}.", "",
        "## Scoreboard groups (SYOSCB-14)", "", render_scoreboard_group_table(plan), "",
        "## Queues (SYOSCB-16)", "", render_queue_table(plan), "",
        "## Producers (SYOSCB-15)", "", render_producer_table(plan), "",
        "## Proposed configuration calls", "", render_configuration_call_table(plan), "",
        "## Upstream API this plan is built on", "", render_api_citation_table(plan), "",
        "## Open questions", "", render_open_question_table(plan), "",
    ]
    if plan["excluded_routes"]:
        lines += ["## Discovered routes carrying no queue", "",
                  render_markdown_table(
                      [("route_id", "Route"), ("excluded", "Reason")],
                      [{"route_id": r["route_id"], "excluded": r["excluded"]}
                       for r in plan["excluded_routes"]]), ""]
    lines.append(
        "Phase-1 planning only (SYOSCB-33). Every row above is a proposal a human reviews; "
        "no scoreboard, queue, producer or configuration code is emitted here, and nothing "
        "was copied out of the upstream tree -- the API rows cite a path and a line that "
        "were read read-only (SYOSCB-2 / SYOSCB-34).")
    text = "\n".join(lines)
    assert_no_emittable_sv(text, label="SYOSCB-14/15/16 SyoSil configuration plan")
    assert_no_bind_statement(text)
    return text


#: Re-exported so a caller reading this module's ordering-domain grouping does
#: not have to import the predictor to name the two keys it groups on.
ORDERING_DOMAIN_KEYS: tuple = (ORDERING_DOMAIN_PER_ROUTE, ORDERING_DOMAIN_PER_ROUTE_AND_ID)

#: Re-exported for the same reason: a route's legality vocabulary belongs to
#: the predictor, and a second copy of it here would be a second vocabulary.
ROUTE_STATUS_VALUES: tuple = (ROUTE_LEGAL, ROUTE_WAIVED)
