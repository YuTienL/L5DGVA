"""dv_harness/syoscb_phase1_report.py -- SYOSCB-29 (REQUIRED ARCHITECTURE
REPRESENTATION) and SYOSCB-30 (the twenty-nine-item REQUIRED PHASE-1 REPORT).

WHAT THIS MODULE IS, AND WHAT IT REFUSES TO BE
----------------------------------------------
It PRODUCES NOTHING NEW ABOUT THE DESIGN. Every fact it prints was already
derived, with its own evidence, by a module that owns that fact:

    amba_fabric_discovery.py      AMBA-7..20   fabric ports, traces, VIP plan
    amba_port_registry.py         AMBA-22      the AMBA_PORT_REGISTRY itself
    amba_fabric_analysis.py       AMBA-23..25  address map, clock/reset domains
    amba_scoreboard_env.py        AMBA-21      the existing reference env
    amba_discovery_report.py      AMBA-26..29  readiness vocabulary + rollup
    amba_transaction_ir.py        SYOSCB-9/10  IR templates + adapter plan
    amba_route_transform_predictor.py SYOSCB-12/13 route/transform prediction
    syoscb_source_audit.py        SYOSCB-1/3   the real read-only source audit
    syoscb_topology_plan.py       SYOSCB-14..16 producer/queue/scoreboard plan
    syoscb_compare_policy.py      SYOSCB-17/18 compare strategy + match key
    syoscb_result_taxonomy.py     SYOSCB-21/22 result taxonomy + counters

This module CALLS their renderers in the order SYOSCB-30 mandates and adds
only the sections nobody else renders (1, 3, 4, 5, 17, 18, 24, 25, 26, 27, 28,
29). Recomputing any of the other sections here -- "just the summary line" --
is precisely how a report drifts away from the artifact it claims to describe,
which this project has already had to unwind once for tiered-confidence
classifiers. Hence: no second tree renderer, no second readiness vocabulary, no
second table renderer, no second address-decode algorithm.

SYOSCB-29, AND WHY THE TREE IS NOT A NEW RENDERER
-------------------------------------------------
`amba_fabric_discovery._tree_child_lines()` is already this repo's ASCII-tree
primitive and is protocol-agnostic (it takes `[(label, [children...])]` and
returns `|--`/`\\--`-connected lines). `render_topology_tree()` already uses it
for the PHYSICAL fabric subtree. SYOSCB-29 asks for a LOGICAL CAPABILITY tree
rooted at "DV Agent Harness L5", which is a different tree over the same
primitive -- so `build_architecture_tree()` projects real artifacts onto
`SYOSCB29_SPEC` and `render_architecture_tree()` hands the result to that one
primitive. `assert_architecture_tree_covers_spec()` then checks the RENDERED
TEXT contains every label the doc mandates, so a branch that a projection
accidentally dropped fails loudly instead of silently disappearing.

THREE PLACES THIS DELIBERATELY REFUSES TO ROUND UP
---------------------------------------------------
  * An adapter leaf for a protocol the AMBA_PORT_REGISTRY does not carry is
    rendered `NOT_PRESENT_IN_FABRIC`, never as a planned adapter. SYOSCB-8
    forbids instantiating support for nonexistent protocols merely because
    the framework can model them, and SYOSCB-29's tree naming all ten
    adapters is a VOCABULARY, not an instruction to plan ten.
  * `Expected Transaction Generator` and `Actual Transaction Collector` have
    no implementation anywhere in this repository and are rendered
    `NOT_BUILT_PHASE_2_ONLY`. The queue sides the SYOSCB-14 plan really
    computed are shown underneath them as the plan's own evidence, which is a
    different claim from "the collector exists".
  * SYOSCB-29's six `Evidence` leaves are COARSER than
    `syoscb_result_taxonomy.ScoreboardResult`'s fourteen values. The mapping
    is explicit, and the three values no SYOSCB-29 leaf names
    (BURST_ERROR, PROTOCOL_TRANSFORM_ERROR, UNKNOWN) are rendered as an
    explicit unmapped leaf rather than dropped.
    `_assert_every_result_is_placed()` runs at import and makes a future
    fifteenth taxonomy value a hard failure here.

PLANNING ONLY (SYOSCB-33 / SYOSCB-34)
--------------------------------------
Nothing here vendors, copies or quotes a body of upstream source; nothing here
emits SystemVerilog. The assembled report is self-checked with
`amba_fabric_discovery.assert_no_bind_statement()` and
`syoscb_source_audit.assert_no_emittable_sv()` before it is returned, and
section 29 IS SYOSCB-33's stop report -- which refuses to render its
"COMPLETE" lines while any of its own preconditions is unmet, following
`capability_evolution.render_stop_report()`'s proven shape (replicated, not
called: that function's lines and preconditions are hardcoded to the
research-capability-evolution wording).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dv_harness import amba_fabric_discovery as afd
from dv_harness import amba_route_transform_predictor as artp
from dv_harness import amba_transaction_ir as air
from dv_harness import syoscb_compare_policy as scp
from dv_harness import syoscb_result_taxonomy as srt
from dv_harness import syoscb_source_audit as ssa
from dv_harness import syoscb_topology_plan as stp
from dv_harness.amba_discovery_report import (
    DiscoveryReportError,
    _not_supplied,
    derive_overall_readiness,
)
from dv_harness.amba_fabric_discovery import (
    BIND_READINESS_BLOCKED,
    BIND_READINESS_PARTIAL,
    BIND_READINESS_READY,
    BIND_READINESS_UNKNOWN,
    assert_no_bind_statement,
)
from dv_harness.amba_port_registry import render_amba_port_registry
from dv_harness.amba_scoreboard_env import render_scoreboard_env_report
from dv_harness.connectivity import (
    AMBA4_DISPLAY_NAMES,
    AMBA4_PROTOCOLS,
    REQUIRED_HUMAN_INPUT,
    render_markdown_table,
)
from dv_harness.knowledge_center import THIRD_PARTY_COMPONENT_FIELDS


class SyoscbPhase1ReportError(DiscoveryReportError):
    """A SYOSCB-29 / SYOSCB-30 / SYOSCB-33 contract was violated."""


#: The document this module renders, cited so a reader can check the wording.
SYOSCB_DOC = ("DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_"
              "SystemLevel_AMBA4_SyoSil_CCE_Research.md")


# ===========================================================================
# SYOSCB-29: REQUIRED ARCHITECTURE REPRESENTATION
# ===========================================================================

#: SYOSCB-29's ten adapters, in the DOCUMENT's order (`{SYOSCB_DOC}:5250-5259`),
#: which is NOT `connectivity.AMBA4_PROTOCOLS`' order. Keys are the
#: `AMBA4_PROTOCOLS` keys so a leaf label always comes from
#: `AMBA4_DISPLAY_NAMES` rather than being spelled a second way here.
SYOSCB29_ADAPTER_ORDER: tuple = (
    "AXI3", "AXI4", "AXI4_LITE", "ACE_LITE", "AXI4_STREAM",
    "AHB", "AHB_LITE", "APB", "APB3", "APB4",
)


def _assert_adapter_order_is_the_real_protocol_set() -> None:
    """The ten adapter leaves are the ten real protocols, permuted -- not a
    parallel list that can drift from `AMBA4_PROTOCOLS`."""
    if sorted(SYOSCB29_ADAPTER_ORDER) != sorted(AMBA4_PROTOCOLS):
        raise SyoscbPhase1ReportError("SYOSCB29_ADAPTER_SET_DIVERGED", {
            "adapter_order": list(SYOSCB29_ADAPTER_ORDER),
            "amba4_protocols": list(AMBA4_PROTOCOLS)})


#: SYOSCB-29's five predictor leaves -> the `ROUTE_RESPONSIBILITIES` each one
#: is answered by. `Width/Burst Transform` is one leaf over TWO real
#: responsibilities; the mapping records that rather than hiding it.
SYOSCB29_PREDICTOR_LEAVES: tuple = (
    ("Address Decode", ("address_decode", "address_translation")),
    ("Master -> Slave Routing", ("master_slave_route", "routing_legality")),
    ("ID Transform", ("id_remap",)),
    ("Width/Burst Transform", ("width_conversion", "burst_split_merge")),
    ("Protocol Bridge Model", ("bridge_behavior",)),
)

#: SYOSCB-29's six Evidence leaves -> the `ScoreboardResult` values each covers.
SYOSCB29_EVIDENCE_LEAVES: tuple = (
    ("Match", ("MATCH",)),
    ("Mismatch", ("DATA_MISMATCH", "ADDRESS_MISMATCH", "RESPONSE_MISMATCH")),
    ("Missing", ("MISSING_TRANSACTION", "TIMEOUT")),
    ("Unexpected", ("UNEXPECTED_TRANSACTION", "DUPLICATE_TRANSACTION")),
    ("Route Error", ("ROUTE_ERROR", "ID_MAPPING_ERROR")),
    ("Ordering Error", ("ORDERING_ERROR",)),
)

#: The taxonomy values SYOSCB-29's six leaves do NOT name. Rendered as their
#: own leaf so the coarsening is visible in the tree, not just in this comment.
SYOSCB29_EVIDENCE_UNMAPPED: tuple = (
    "BURST_ERROR", "PROTOCOL_TRANSFORM_ERROR", "UNKNOWN",
)


def _assert_every_result_is_placed() -> None:
    """Every one of `srt.SCOREBOARD_RESULT_VALUES` is either under a SYOSCB-29
    Evidence leaf or explicitly listed as unmapped. A fifteenth taxonomy value
    added later fails HERE, at import, rather than quietly vanishing from the
    architecture tree a human reviews at the gate."""
    placed: list = []
    for _, values in SYOSCB29_EVIDENCE_LEAVES:
        placed.extend(values)
    placed.extend(SYOSCB29_EVIDENCE_UNMAPPED)
    missing = [v for v in srt.SCOREBOARD_RESULT_VALUES if v not in placed]
    unknown = [v for v in placed if v not in srt.SCOREBOARD_RESULT_VALUES]
    duplicated = sorted({v for v in placed if placed.count(v) > 1})
    if missing or unknown or duplicated:
        raise SyoscbPhase1ReportError("SYOSCB29_EVIDENCE_MAPPING_DIVERGED", {
            "unplaced_results": missing, "unknown_results": unknown,
            "duplicated": duplicated,
            "taxonomy": list(srt.SCOREBOARD_RESULT_VALUES)})


def _spec_children(labels) -> tuple:
    return tuple((label, ()) for label in labels)


#: SYOSCB-29's tree, verbatim (`{SYOSCB_DOC}:5240-5284`), as
#: `(label, (children...))`. The document's `Master → Slave Routing` is spelled
#: with an ASCII arrow here for the same reason `_tree_child_lines()` uses
#: `|--` rather than box-drawing characters: this text is written to logs and
#: files whose encoding is not guaranteed.
SYOSCB29_SPEC: tuple = (
    ("AMBA SoC Fabric Verification", ()),
    ("Fabric Discovery", (("AMBA_PORT_REGISTRY", ()),)),
    ("VIP Bind Planning", ()),
    ("AMBA Transaction Normalization",
     _spec_children(f"{AMBA4_DISPLAY_NAMES[p]} Adapter" for p in SYOSCB29_ADAPTER_ORDER)),
    ("AMBA Route / Transform Predictor",
     _spec_children(label for label, _ in SYOSCB29_PREDICTOR_LEAVES)),
    ("AMBA Scoreboard", (
        ("Expected Transaction Generator", ()),
        ("Actual Transaction Collector", ()),
        ("SyoSil UVM SCB", _spec_children((
            "Queue Engine", "Producer Management", "In-Order Compare",
            "Producer-Aware Compare", "Out-of-Order Compare"))),
    )),
    ("Evidence", _spec_children(label for label, _ in SYOSCB29_EVIDENCE_LEAVES)),
)

SYOSCB29_ROOT_LABEL = "DV Agent Harness L5"

#: A branch was projected from a real artifact the caller supplied.
BRANCH_POPULATED = "POPULATED_FROM_REAL_ARTIFACT"
#: The artifact that would populate this branch was not supplied to the
#: renderer. NOT the same as "the capability does not exist".
BRANCH_NOT_SUPPLIED = "ARTIFACT_NOT_SUPPLIED"
#: No implementation exists anywhere in this repository and none may be built
#: before the SYOSCB-33/34 gate. NOT the same as "nobody supplied it".
BRANCH_NOT_BUILT = "NOT_BUILT_PHASE_2_ONLY"

BRANCH_STATUS_VALUES: tuple = (BRANCH_POPULATED, BRANCH_NOT_SUPPLIED, BRANCH_NOT_BUILT)

#: SYOSCB-8's refusal, as a leaf annotation.
ADAPTER_NOT_PRESENT = "NOT_PRESENT_IN_FABRIC"


@dataclass
class ArchitectureRepresentation:
    """SYOSCB-29's tree plus, for each top-level branch, WHY it looks the way
    it does. The status dict is the part a reviewer needs: an empty-looking
    branch because nobody ran the analysis and an empty-looking branch because
    the fabric genuinely has nothing there are different findings."""
    entries: list = field(default_factory=list)     # [(label, [children...])]
    branch_status: dict = field(default_factory=dict)  # label -> {status, detail}

    def to_dict(self) -> dict:
        return {"root": SYOSCB29_ROOT_LABEL,
                "branch_status": {k: dict(v) for k, v in self.branch_status.items()}}


def _leaf(label: str, annotation: str = "") -> tuple:
    return (f"{label} = {annotation}" if annotation else label, [])


def _fabric_discovery_branch(registry, traces) -> tuple:
    """SYOSCB-29's `Fabric Discovery -> AMBA_PORT_REGISTRY`. Counted from the
    real registry rows; never re-derived from the netlist a second way."""
    if not registry:
        return ([("AMBA_PORT_REGISTRY", [_leaf("STATUS", BRANCH_NOT_SUPPLIED)])],
                {"status": BRANCH_NOT_SUPPLIED,
                 "detail": "no AMBA_PORT_REGISTRY rows were supplied; run "
                           "amba_port_registry.build_amba_port_registry()"})
    by_protocol: dict = {}
    for row in registry:
        by_protocol[row.get("protocol")] = by_protocol.get(row.get("protocol"), 0) + 1
    children = [_leaf("ROWS", str(len(registry)))]
    children += [_leaf(f"PROTOCOL {p}", str(n)) for p, n in sorted(by_protocol.items())]
    if traces:
        children.append(_leaf("TRACED_FABRIC_PORTS", str(len(list(traces)))))
    return ([("AMBA_PORT_REGISTRY", children)],
            {"status": BRANCH_POPULATED,
             "detail": f"{len(registry)} AMBA_PORT_REGISTRY row(s)"})


def _vip_bind_branch(plan) -> tuple:
    if plan is None:
        return ([_leaf("STATUS", BRANCH_NOT_SUPPLIED)],
                {"status": BRANCH_NOT_SUPPLIED,
                 "detail": "no VipBindPlan was supplied; run "
                           "amba_fabric_discovery.build_vip_bind_plan()"})
    matrix = list(getattr(plan, "matrix", ()) or ())
    unresolved = list(getattr(plan, "unresolved", ()) or ())
    instances = list(getattr(plan, "vip_instances", ()) or ())
    children = [_leaf("BIND_MATRIX_ROWS", str(len(matrix))),
                _leaf("UNRESOLVED_PORTS", str(len(unresolved))),
                _leaf("PLANNED_VIP_INSTANCES", str(len(instances)))]
    return (children,
            {"status": BRANCH_POPULATED,
             "detail": f"{len(matrix)} bind-matrix row(s), {len(unresolved)} unresolved"})


def _normalization_branch(registry, adapter_plans) -> tuple:
    """One leaf per SYOSCB-29 adapter name, annotated with what the real
    adapter plan decided -- or with SYOSCB-8's refusal when the fabric does
    not carry that protocol at all."""
    # ADAPTER_NOT_PRESENT is a claim about the FABRIC and may only be made when
    # a registry was really supplied. With no registry there is no evidence
    # about which protocols exist, and "not present" would be a fabricated
    # negative -- so every leaf falls back to ARTIFACT_NOT_SUPPLIED instead.
    if not registry:
        return ([_leaf(f"{AMBA4_DISPLAY_NAMES[p]} Adapter", BRANCH_NOT_SUPPLIED)
                 for p in SYOSCB29_ADAPTER_ORDER],
                {"status": BRANCH_NOT_SUPPLIED,
                 "detail": "no AMBA_PORT_REGISTRY was supplied, so which protocols the "
                           "fabric carries is unknown and no adapter leaf may claim "
                           f"{ADAPTER_NOT_PRESENT}"})
    present = set(air.discovered_protocols(registry))
    by_protocol = {p.get("protocol"): p for p in adapter_plans or ()}
    children: list = []
    planned = 0
    for protocol in SYOSCB29_ADAPTER_ORDER:
        label = f"{AMBA4_DISPLAY_NAMES[protocol]} Adapter"
        entry = by_protocol.get(protocol)
        if entry is not None:
            planned += 1
            children.append((f"{label} = {entry['verdict']}",
                             [_leaf("PORTS", ", ".join(str(p) for p in entry["port_ids"])
                                    or "(none)"),
                              _leaf("RATIONALE", str(entry["rationale"]))]))
        elif protocol in present:
            children.append(_leaf(label, BRANCH_NOT_SUPPLIED))
        else:
            children.append(_leaf(label, ADAPTER_NOT_PRESENT))
    if adapter_plans is None:
        status = {"status": BRANCH_NOT_SUPPLIED,
                  "detail": "no adapter plan was supplied; run "
                            "amba_transaction_ir.plan_amba_adapters()"}
    else:
        status = {"status": BRANCH_POPULATED,
                  "detail": f"{planned} of {len(SYOSCB29_ADAPTER_ORDER)} adapter(s) "
                            f"planned; the rest carry {ADAPTER_NOT_PRESENT} per SYOSCB-8"}
    return (children, status)


def _predictor_branch(predictions) -> tuple:
    """One leaf per SYOSCB-29 predictor stage, annotated with how many real
    route predictions resolved that responsibility and how many did not."""
    rows = list(predictions or ())
    children: list = []
    for label, responsibilities in SYOSCB29_PREDICTOR_LEAVES:
        if not rows:
            children.append(_leaf(label, BRANCH_NOT_SUPPLIED))
            continue
        resolved = 0
        open_ = 0
        for prediction in rows:
            for name in responsibilities:
                entry = prediction.get(name) or {}
                if entry.get("status") == REQUIRED_HUMAN_INPUT:
                    open_ += 1
                else:
                    resolved += 1
        children.append((f"{label} = {resolved} resolved / {open_} open",
                         [_leaf("RESPONSIBILITIES", ", ".join(responsibilities))]))
    if not rows:
        return (children, {"status": BRANCH_NOT_SUPPLIED,
                           "detail": "no route predictions were supplied; run "
                                     "amba_route_transform_predictor.predict_routes()"})
    return (children, {"status": BRANCH_POPULATED,
                       "detail": f"{len(rows)} predicted route(s)"})


def _syosil_scb_node(syoscb_plan, audit) -> tuple:
    """The `SyoSil UVM SCB` node and its five leaves.

    Queue/producer counts come from the real SYOSCB-14 plan; the three compare
    leaves come from the REAL upstream class names the read-only source audit
    found (`compare_class_for_ordering()`), never from a guess -- the library
    is sitting on disk and inventing a class name for it would be the exact
    fabrication this whole pass exists to avoid."""
    if syoscb_plan is not None:
        children = [
            _leaf("Queue Engine",
                  f"{len(syoscb_plan.get('queues') or ())} planned queue(s)"),
            _leaf("Producer Management",
                  f"{len(syoscb_plan.get('producers') or ())} planned producer(s)")]
    else:
        children = [_leaf("Queue Engine", BRANCH_NOT_SUPPLIED),
                    _leaf("Producer Management", BRANCH_NOT_SUPPLIED)]

    for label, ordering in (("In-Order Compare", ssa.ORDERING_IN_ORDER),
                            ("Producer-Aware Compare",
                             ssa.ORDERING_IN_ORDER_PER_PRODUCER),
                            ("Out-of-Order Compare", ssa.ORDERING_OUT_OF_ORDER)):
        if audit is None:
            children.append(_leaf(label, BRANCH_NOT_SUPPLIED))
            continue
        found = ssa.compare_class_for_ordering(audit, ordering)
        if found is None:
            children.append(_leaf(label, REQUIRED_HUMAN_INPUT))
        else:
            children.append(
                (f"{label} = {found['class']}",
                 [_leaf("EVIDENCE", f"{found['file']}:{found['line']} (read-only)")]))
    return ("SyoSil UVM SCB", children)


def _scoreboard_branch(syoscb_plan, audit) -> tuple:
    """SYOSCB-29's `AMBA Scoreboard`.

    The generator and the collector are rendered NOT_BUILT, with the plan's
    real per-side queue counts underneath as the nearest real evidence. That is
    deliberately a weaker claim than "the collector exists": no expected-
    transaction generator or actual-transaction collector is implemented
    anywhere in this repository, and Phase 1 may not implement one."""
    queues = list((syoscb_plan or {}).get("queues") or ())
    master_side = [q for q in queues if q.get("side") == stp.QUEUE_SIDE_MASTER]
    slave_side = [q for q in queues if q.get("side") == stp.QUEUE_SIDE_SLAVE]

    def _side(label: str, side_queues: list, side_note: str):
        detail = [_leaf("STATUS", BRANCH_NOT_BUILT),
                  _leaf("PHASE_2_GATE", "SYOSCB-33 human review / SYOSCB-34")]
        if syoscb_plan is not None:
            detail.append(_leaf(side_note, str(len(side_queues))))
        return (label, detail)

    children = [_side("Expected Transaction Generator", master_side,
                      "PLANNED_MASTER_SIDE_QUEUES"),
                _side("Actual Transaction Collector", slave_side,
                      "PLANNED_SLAVE_SIDE_QUEUES"),
                _syosil_scb_node(syoscb_plan, audit)]

    if syoscb_plan is None and audit is None:
        status = {"status": BRANCH_NOT_SUPPLIED,
                  "detail": "neither a SYOSCB-14 configuration plan nor a SYOSCB-1 "
                            "source audit was supplied"}
    else:
        status = {"status": BRANCH_POPULATED,
                  "detail": f"{len(queues)} planned queue(s); the expected-transaction "
                            f"generator and actual-transaction collector are "
                            f"{BRANCH_NOT_BUILT}"}
    return (children, status)


def _evidence_branch(taxonomy_rows) -> tuple:
    """SYOSCB-29's `Evidence`. Always populated: the taxonomy is a fixed
    vocabulary that exists whether or not any port was discovered. The
    per-port counters, which DO need a registry, are annotated separately."""
    children: list = []
    for label, values in SYOSCB29_EVIDENCE_LEAVES:
        children.append((f"{label} = {', '.join(values)}", []))
    children.append(_leaf("NOT_NAMED_BY_SYOSCB29",
                          ", ".join(SYOSCB29_EVIDENCE_UNMAPPED)))
    if taxonomy_rows:
        open_counters = srt.unresolved_port_visibility_counters(taxonomy_rows)
        children.append(_leaf("PER_PORT_COUNTERS",
                              f"{len(list(taxonomy_rows))} port row(s), "
                              f"{len(open_counters)} counter(s) still blocked"))
    else:
        children.append(_leaf("PER_PORT_COUNTERS", BRANCH_NOT_SUPPLIED))
    return (children,
            {"status": BRANCH_POPULATED,
             "detail": f"{len(srt.SCOREBOARD_RESULT_VALUES)} taxonomy value(s) placed "
                       f"under {len(SYOSCB29_EVIDENCE_LEAVES)} SYOSCB-29 leaf/leaves; "
                       f"{len(SYOSCB29_EVIDENCE_UNMAPPED)} named by no leaf"})


def build_architecture_tree(*, registry=None, traces=None, plan=None,
                            adapter_plans=None, predictions=None,
                            syoscb_plan=None, audit=None,
                            taxonomy_rows=None) -> ArchitectureRepresentation:
    """SYOSCB-29's logical architecture, projected from whatever real artifacts
    the caller has.

    Every argument is optional and every omission is VISIBLE: a branch with no
    artifact renders `ARTIFACT_NOT_SUPPLIED` and names the function that would
    produce it. Nothing is fabricated for a branch nobody computed."""
    _assert_adapter_order_is_the_real_protocol_set()
    entries: list = []
    status: dict = {}

    entries.append(("AMBA SoC Fabric Verification", []))
    status["AMBA SoC Fabric Verification"] = {
        "status": BRANCH_POPULATED,
        "detail": "this repository's AMBA4 multi-master/multi-slave capability, "
                  "audited in section 1 of the SYOSCB-30 report"}

    children, branch = _fabric_discovery_branch(registry, traces)
    entries.append(("Fabric Discovery", children))
    status["Fabric Discovery"] = branch

    children, branch = _vip_bind_branch(plan)
    entries.append(("VIP Bind Planning", children))
    status["VIP Bind Planning"] = branch

    children, branch = _normalization_branch(registry, adapter_plans)
    entries.append(("AMBA Transaction Normalization", children))
    status["AMBA Transaction Normalization"] = branch

    children, branch = _predictor_branch(predictions)
    entries.append(("AMBA Route / Transform Predictor", children))
    status["AMBA Route / Transform Predictor"] = branch

    children, branch = _scoreboard_branch(syoscb_plan, audit)
    entries.append(("AMBA Scoreboard", children))
    status["AMBA Scoreboard"] = branch

    children, branch = _evidence_branch(taxonomy_rows)
    entries.append(("Evidence", children))
    status["Evidence"] = branch

    return ArchitectureRepresentation(entries=entries, branch_status=status)


def render_architecture_tree(representation: ArchitectureRepresentation) -> str:
    """The tree, through `amba_fabric_discovery._tree_child_lines()` -- this
    repo's ONE ASCII-tree primitive, imported rather than reimplemented."""
    lines = [SYOSCB29_ROOT_LABEL] + afd._tree_child_lines(representation.entries, "")
    text = "\n".join(lines)
    assert_architecture_tree_covers_spec(text)
    assert_no_bind_statement(text)
    return text


def _spec_labels(spec=SYOSCB29_SPEC) -> list:
    out: list = []
    for label, children in spec:
        out.append(label)
        out.extend(_spec_labels(children))
    return out


def assert_architecture_tree_covers_spec(text: str) -> None:
    """Every label SYOSCB-29 mandates really appears in the RENDERED text.

    Checked against the finished string, not against the tuple that produced
    it, for the same reason `amba_discovery_report.assert_report_section_order()`
    is: verifying the source tuple against itself proves nothing about the
    artifact a human will read."""
    body = str(text or "")
    missing = [label for label in _spec_labels() if label not in body]
    if SYOSCB29_ROOT_LABEL not in body:
        missing.insert(0, SYOSCB29_ROOT_LABEL)
    if missing:
        raise SyoscbPhase1ReportError("SYOSCB29_ARCHITECTURE_BRANCH_MISSING", {
            "missing_labels": missing,
            "hint": "SYOSCB-29 mandates this exact tree; a branch with no real "
                    "artifact must render ARTIFACT_NOT_SUPPLIED, never be omitted"})


def unpopulated_architecture_branches(
        representation: ArchitectureRepresentation) -> list:
    """The top-level branches no real artifact reached, in tree order."""
    return [label for label, _ in representation.entries
            if representation.branch_status.get(label, {}).get("status")
            != BRANCH_POPULATED]


# ===========================================================================
# SYOSCB-30: THE TWENTY-NINE-ITEM PHASE-1 REPORT
# ===========================================================================

#: `{SYOSCB_DOC}:5294-5322`, verbatim and in the document's own order.
SYOSCB30_SECTIONS: tuple = (
    (1, "CURRENT L5 AMBA CAPABILITY AUDIT"),
    (2, "SYOSIL SOURCE DIRECTORY AUDIT"),
    (3, "SYOSIL LICENSE / PROVENANCE CHECK"),
    (4, "EXISTING THIRD-PARTY LOCATION DISCOVERY"),
    (5, "PROPOSED COMPLETE DIRECTORY INTEGRATION LOCATION"),
    (6, "BUS FABRIC INSTANCE"),
    (7, "AMBA PORT ENUMERATION"),
    (8, "PROTOCOL CLASSIFICATION"),
    (9, "MASTER / SLAVE COUNTS"),
    (10, "PER-PORT SOURCE / DESTINATION TRACE"),
    (11, "VIP BIND MATRIX"),
    (12, "UNRESOLVED PORTS"),
    (13, "AMBA_PORT_REGISTRY"),
    (14, "CLOCK / RESET MATRIX"),
    (15, "ADDRESS / ROUTE ANALYSIS"),
    (16, "EXISTING SCOREBOARD ENVIRONMENT ANALYSIS"),
    (17, "SYOSIL CAPABILITY MAPPING"),
    (18, "SYOSIL LIMITATION ANALYSIS"),
    (19, "AMBA TRANSACTION IR PLAN"),
    (20, "AMBA ADAPTER PLAN"),
    (21, "ROUTE / TRANSFORM PREDICTOR PLAN"),
    (22, "PRODUCER / QUEUE MAPPING PLAN"),
    (23, "PROTOCOL-SPECIFIC MATCHING POLICY"),
    (24, "SCOREBOARD TEST PLAN"),
    (25, "VCS / BUILD INTEGRATION PLAN"),
    (26, "KNOWLEDGE CENTER UPDATE PLAN"),
    (27, "READINESS"),
    (28, "OPEN BLOCKERS"),
    (29, "USER REVIEW GATE"),
)

#: SYOSCB-33's stop report (`{SYOSCB_DOC}:5384-5394`), verbatim and in order.
SYOSCB33_GATE_LINES: tuple = (
    "AMBA FABRIC DISCOVERY COMPLETE",
    "AMBA PORT REGISTRY COMPLETE",
    "VIP BIND PLAN COMPLETE",
    "SYOSIL SOURCE AUDIT COMPLETE",
    "SYOSIL INTEGRATION PLAN COMPLETE",
    "AMBA SCOREBOARD ARCHITECTURE COMPLETE",
    "PRODUCER / QUEUE MAPPING PLAN COMPLETE",
    "AMBA ADAPTER PLAN COMPLETE",
    "ROUTE PREDICTOR PLAN COMPLETE",
    "IMPLEMENTATION NOT STARTED",
    "AWAITING USER APPROVAL",
)

#: The nine gate lines that are CLAIMS about work (the last two are constants
#: of Phase 1, not claims) -> the precondition key each one rests on. Following
#: `capability_evolution.STOP_REPORT_PRECONDITIONS`' shape: the report may not
#: print "COMPLETE" over work nobody did.
SYOSCB33_GATE_PRECONDITIONS: tuple = (
    ("AMBA FABRIC DISCOVERY COMPLETE", "amba_fabric_discovery_complete"),
    ("AMBA PORT REGISTRY COMPLETE", "amba_port_registry_complete"),
    ("VIP BIND PLAN COMPLETE", "vip_bind_plan_complete"),
    ("SYOSIL SOURCE AUDIT COMPLETE", "syosil_source_audit_complete"),
    ("SYOSIL INTEGRATION PLAN COMPLETE", "syosil_integration_plan_complete"),
    ("AMBA SCOREBOARD ARCHITECTURE COMPLETE", "amba_scoreboard_architecture_complete"),
    ("PRODUCER / QUEUE MAPPING PLAN COMPLETE", "producer_queue_mapping_plan_complete"),
    ("AMBA ADAPTER PLAN COMPLETE", "amba_adapter_plan_complete"),
    ("ROUTE PREDICTOR PLAN COMPLETE", "route_predictor_plan_complete"),
)


def _assert_gate_preconditions_cover_every_claim() -> None:
    """Each of the nine claim lines has exactly one precondition, and the two
    unconditional lines have none."""
    claimed = [line for line, _ in SYOSCB33_GATE_PRECONDITIONS]
    unconditional = ["IMPLEMENTATION NOT STARTED", "AWAITING USER APPROVAL"]
    if claimed + unconditional != list(SYOSCB33_GATE_LINES):
        raise SyoscbPhase1ReportError("SYOSCB33_GATE_LINES_DIVERGED", {
            "with_preconditions": claimed, "unconditional": unconditional,
            "gate_lines": list(SYOSCB33_GATE_LINES)})


# ---------------------------------------------------------------------------
# The sections nobody else renders
# ---------------------------------------------------------------------------

#: The `protocol_capability` key for this document's subject.
AMBA4_CAPABILITY_KEY = "AMBA4_MULTI_MASTER_MULTI_SLAVE"

#: Item 1's L5-module inventory: which real module answers which SYOSCB
#: requirement. Real dotted module names; `_render_capability_audit()` imports
#: each one and reports whether it is genuinely importable, so a renamed or
#: deleted module shows up as a gap rather than as a confident claim.
L5_AMBA_CAPABILITY_MODULES: tuple = (
    ("dv_harness.amba_fabric_discovery", "AMBA-7..20 fabric discovery / VIP bind plan"),
    ("dv_harness.amba_port_registry", "AMBA-22 AMBA_PORT_REGISTRY"),
    ("dv_harness.amba_fabric_analysis", "AMBA-23..25 address map / clock-reset / scaling"),
    ("dv_harness.amba_scoreboard_env", "AMBA-21 existing scoreboard environment"),
    ("dv_harness.amba_discovery_report", "AMBA-26..29 report / confidence / readiness"),
    ("dv_harness.uvm_generator.amba_fabric_generator",
     "address regions / id width / scoreboard matrix algorithms"),
    ("dv_harness.uvm_generator.address_map_verifier", "3-source address-map corroboration"),
    ("dv_harness.amba_transaction_ir", "SYOSCB-9/10 AMBA transaction IR + adapter plan"),
    ("dv_harness.amba_route_transform_predictor", "SYOSCB-12/13 route/transform predictor"),
    ("dv_harness.syoscb_source_audit", "SYOSCB-1/3 read-only SyoSil source audit"),
    ("dv_harness.syoscb_topology_plan", "SYOSCB-14..16 producer/queue/scoreboard plan"),
    ("dv_harness.syoscb_compare_policy", "SYOSCB-17/18 compare strategy + match key"),
    ("dv_harness.syoscb_result_taxonomy", "SYOSCB-21/22 result taxonomy + counters"),
    ("dv_harness.syoscb_phase1_report", "SYOSCB-29/30 architecture tree + Phase-1 report"),
)


def _render_capability_audit() -> str:
    """Item 1. The AMBA capability this repository REALLY has today, read from
    `protocol_capability` (the one registry that already tracks it) plus a
    real importability check over the modules that implement it."""
    from importlib import import_module

    from dv_harness import protocol_capability as pc

    cap = pc.capability_for(AMBA4_CAPABILITY_KEY)
    header = [
        f"`protocol_capability` key: `{AMBA4_CAPABILITY_KEY}`",
        f"- capability_status: **{pc.derive_status(cap) if cap else REQUIRED_HUMAN_INPUT}**",
        "",
        "The status above is DERIVED by `protocol_capability.derive_status()` from what "
        "really imports and what has really been proven against a DUT; it is not "
        "asserted here.",
        "",
    ]
    rows = []
    for dotted, role in L5_AMBA_CAPABILITY_MODULES:
        try:
            import_module(dotted)
            state = "IMPORTABLE"
        except Exception as exc:                      # pragma: no cover - a real gap
            state = f"NOT_IMPORTABLE ({type(exc).__name__})"
        rows.append({"module": dotted, "role": role, "state": state})
    return "\n".join(header + [render_markdown_table(
        [("module", "L5 Module"), ("role", "Requirement It Answers"),
         ("state", "Import Check")], rows)])


def _render_source_directory_audit(audit) -> str:
    """Item 2. The SYOSCB-1 checklist and class inventory, from the read-only
    audit. Nothing is copied out of the upstream tree: the audit carries
    declarations and file:line citations only."""
    if audit is None:
        return _not_supplied(
            "The SYOSCB-1 read-only source audit",
            "run `syoscb_source_audit.audit_syoscb_source(D:/DV/Scoreboard/"
            "uvm_syoscb-1.0.2.4)` and pass its result as `audit`")
    unanswered = ssa.unanswered_audit_items(audit)
    order = audit.package.get("compile_order") or []
    return "\n".join([
        f"- SOURCE_ROOT: `{audit.root}` (read-only; nothing copied into this repository)",
        f"- VERSION: `{audit.version}` ({audit.version_evidence or REQUIRED_HUMAN_INPUT})",
        f"- FILES AUDITED: {len(audit.files)}",
        f"- AUDIT FINGERPRINT: `{ssa.audit_fingerprint(audit)}`",
        f"- UVM DEPENDENCY: requires_uvm={audit.uvm_dependency['requires_uvm']}, "
        f"version={audit.uvm_dependency['uvm_version']}",
        "", "### SYOSCB-1 checklist", "", ssa.render_checklist_table(audit), "",
        ("UNANSWERED ITEMS: " + ", ".join(unanswered)) if unanswered
        else "UNANSWERED ITEMS: (none)",
        "", "### Class inventory", "", ssa.render_class_table(audit), "",
        "### Compile order (package include sequence, source order)", "",
        "\n".join(f"{i}. `{inc}`" for i, inc in enumerate(order, start=1))
        or "(no package file with includes was found)",
    ])


def _render_license_provenance(audit) -> str:
    """Item 3, kept separate from item 2 because a license finding is the one
    fact a legal reviewer reads on its own."""
    if audit is None:
        return _not_supplied(
            "The SYOSCB-1 read-only source audit",
            "run `syoscb_source_audit.audit_syoscb_source()` and pass it as `audit`")
    lic = audit.license
    rows = [{"field": "SPDX id", "value": lic["spdx_id"],
             "evidence": lic["license_file"] or REQUIRED_HUMAN_INPUT},
            {"field": "copyright", "value": lic["copyright"],
             "evidence": lic["copyright_evidence"] or REQUIRED_HUMAN_INPUT},
            {"field": "version", "value": audit.version,
             "evidence": audit.version_evidence or REQUIRED_HUMAN_INPUT},
            {"field": "audited file count", "value": str(len(audit.files)),
             "evidence": f"every file under {audit.root}, hashed"},
            {"field": "root fingerprint", "value": ssa.audit_fingerprint(audit),
             "evidence": "sha256 over (relative path, file sha256) for every file"},
            {"field": "vendored into this repository", "value": "no",
             "evidence": "SYOSCB-2 vendoring is a Phase-2 action gated by "
                         "SYOSCB-33/34; see section 4"}]
    return render_markdown_table(
        [("field", "Field"), ("value", "Value"), ("evidence", "Evidence")], rows)


def _render_third_party_discovery(repo_root, audit) -> str:
    """Item 4. Whether any upstream file is ALREADY inside this repository --
    checked by running `assert_not_vendored()`, not by asserting it."""
    if repo_root is None:
        return _not_supplied(
            "The repository root to scan",
            "pass `repo_root=<this repository>`; `syoscb_source_audit."
            "assert_not_vendored()` then runs a real name AND content scan")
    try:
        evidence = ssa.assert_not_vendored(repo_root, audit)
    except ssa.SyoscbSourceAuditError as exc:
        return ("**SYOSCB-2 VIOLATION.** Upstream source is already inside this "
                f"repository before the SYOSCB-33 gate: `{exc.reason}` "
                f"{exc.detail}")
    rows = [{"check": k, "result": str(v)} for k, v in sorted(evidence.items())]
    return "\n".join([
        "`syoscb_source_audit.assert_not_vendored()` was really run against this "
        "repository. It has two independent detectors: a path-name check "
        "(`uvm_syoscb*`) and a content-digest check against the audit's own file "
        "hashes, so a renamed copy is caught too.", "",
        render_markdown_table([("check", "Check"), ("result", "Result")], rows)])


def _render_proposed_location(proposed_integration_location, payload) -> str:
    """Item 5. A PATH, not a copy. Left REQUIRED_HUMAN_INPUT unless a human
    supplied one, because where the tree lands is a SYOSCB-2 decision made
    AFTER the SYOSCB-33 gate."""
    proposed = (proposed_integration_location
                or (payload or {}).get("L5_DESTINATION")
                or REQUIRED_HUMAN_INPUT)
    return "\n".join([
        f"- PROPOSED_L5_DESTINATION: `{proposed}`",
        "- ACTION TAKEN IN PHASE 1: **none**. No directory was created, no file was "
        "copied, and no build file references the upstream tree.",
        "- The complete `uvm_syoscb-1.0.2.4` directory (tree and provenance intact) is "
        "copied only under SYOSCB-34, after the SYOSCB-33 approval in section 29.",
    ] + ([] if proposed != REQUIRED_HUMAN_INPUT else [
        "", "This is `REQUIRED_HUMAN_INPUT` on purpose: writing a plausible-looking "
        "path here would publish a location nothing is at."]))


#: SYOSCB-17's mapping: one row per SyoSil capability this plan actually
#: depends on. `audit_lookup` names how the row is evidenced FROM THE REAL
#: SOURCE, so no row is a claim about a library nobody read.
SYOSIL_CAPABILITY_MAP: tuple = (
    ("queue engine", "SYOSCB-16 destination/ordering-domain -> queue mapping", "QUEUE"),
    ("queue iterators", "ordering-tolerant search within a queue", "QUEUE_ITERATOR"),
    ("producer registration",
     "SYOSCB-15 master -> producer mapping", "SCOREBOARD_CORE"),
    ("compare strategies",
     "SYOSCB-17 in-order / in-order-per-producer / out-of-order", "COMPARE_STRATEGY"),
    ("configuration object", "SYOSCB-14 topology configuration", "CONFIGURATION"),
    ("subscriber fan-out", "one analysis write per (queue, producer)", "SUBSCRIBER"),
    ("item wrapper", "SYOSCB-10 adapter output -> a comparable item", "ITEM_WRAPPER"),
    ("report catcher", "SYOSCB-21 result reporting", "REPORT_CATCHER"),
)


def _render_capability_mapping(audit) -> str:
    """Item 17. Each SyoSil capability this plan leans on, the AMBA
    requirement it serves, and the REAL class(es) the read-only audit found
    for it. A capability with no class found is REQUIRED_HUMAN_INPUT, never
    an assumed one."""
    if audit is None:
        return _not_supplied(
            "The SYOSCB-1 read-only source audit",
            "run `syoscb_source_audit.audit_syoscb_source()` and pass it as `audit`; "
            "every row below is evidenced by a real class this audit found")
    rows = []
    for capability, requirement, role in SYOSIL_CAPABILITY_MAP:
        found = audit.classes_with_role(role)
        rows.append({
            "capability": capability, "requirement": requirement, "role": role,
            "classes": ", ".join(c["name"] for c in found) or REQUIRED_HUMAN_INPUT,
            "evidence": "; ".join(f"{c['file']}:{c['line']}" for c in found[:3])
                        or REQUIRED_HUMAN_INPUT})
    return "\n".join([
        render_markdown_table(
            [("capability", "SyoSil Capability"), ("requirement", "AMBA Requirement"),
             ("role", "Audited Role"), ("classes", "Real Class(es)"),
             ("evidence", "Evidence (read-only)")], rows),
        "",
        "### SYOSCB-17 starting compare policy per protocol", "",
        scp.render_protocol_policy_table(audit)])


def _render_limitation_analysis(audit, registry) -> str:
    """Item 18. What SyoSil does NOT do for AMBA -- derived from the audit,
    not asserted. The central finding (the library is protocol-agnostic and
    therefore carries no AMBA route/id/width concept) is CHECKED by looking
    for any AMBA token in the real class names, so it cannot be a stale
    claim about a library that grew one."""
    if audit is None:
        return _not_supplied(
            "The SYOSCB-1 read-only source audit",
            "run `syoscb_source_audit.audit_syoscb_source()` and pass it as `audit`")
    tokens = tuple(p.split("_")[0].lower() for p in AMBA4_PROTOCOLS) + ("amba",)
    amba_aware = sorted({c["name"] for c in audit.classes
                         if any(t in c["name"].lower() for t in tokens)})
    rows = [
        {"limitation": "no AMBA protocol awareness",
         "consequence": "an AMBA transaction must be normalised before it can be "
                        "queued -- SYOSCB-9/10's IR and adapters exist for this",
         "evidence": (f"{len(audit.classes)} audited class(es); classes whose name "
                      f"carries an AMBA token: "
                      f"{', '.join(amba_aware) if amba_aware else 'none'}")},
        {"limitation": "no address decode / routing model",
         "consequence": "which slave a master transaction should reach is decided "
                        "OUTSIDE the library -- SYOSCB-12's route predictor",
         "evidence": "no audited class carries a QUEUE/COMPARE role that consumes an "
                     "address map; see the class inventory in section 2"},
        {"limitation": "ordering is per queue, not per AMBA ordering domain",
         "consequence": "the AXI id/route ordering domain must be mapped onto queues "
                        "by SYOSCB-16 before a compare strategy means anything",
         "evidence": "; ".join(f"{k} -> {v['class']} ({v['file']}:{v['line']})"
                               for k, v in sorted(audit.compare_algorithms.items()))
                     or REQUIRED_HUMAN_INPUT},
    ]
    for limitation in audit.known_limitations:
        rows.append({"limitation": limitation,
                     "consequence": REQUIRED_HUMAN_INPUT,
                     "evidence": "stated by the upstream release notes"})
    if registry:
        protocols = air.discovered_protocols(registry)
        rows.append({
            "limitation": "the library models no protocol, so every discovered "
                          "protocol needs its own adapter",
            "consequence": f"{len(protocols)} adapter(s) planned in section 20",
            "evidence": f"protocols really carried by the registry: "
                        f"{', '.join(protocols) or 'none'}"})
    return render_markdown_table(
        [("limitation", "Limitation"), ("consequence", "Consequence For This Plan"),
         ("evidence", "Evidence")], rows)


#: Item 24's test intents. Each is a NAMED INTENT plus the SYOSCB-21 results
#: it is supposed to be able to produce -- never SystemVerilog, never a test
#: file. `build_scoreboard_test_plan()` instantiates these against the REAL
#: scoreboard groups the SYOSCB-14 plan computed.
SCOREBOARD_TEST_INTENTS: tuple = (
    ("targeted_route", "one transaction per legal route, in isolation",
     ("MATCH", "ROUTE_ERROR", "ADDRESS_MISMATCH")),
    ("targeted_transform", "a transaction on each route with a predicted "
     "id/width/burst transform",
     ("ID_MAPPING_ERROR", "BURST_ERROR", "PROTOCOL_TRANSFORM_ERROR")),
    ("ordering_stress", "concurrent traffic within one ordering domain",
     ("ORDERING_ERROR", "DUPLICATE_TRANSACTION")),
    ("multi_master_stress", "all masters of a scoreboard driving concurrently",
     ("UNEXPECTED_TRANSACTION", "MISSING_TRANSACTION", "TIMEOUT")),
    ("reset_flush", "reset asserted with transactions outstanding",
     ("MISSING_TRANSACTION", "UNKNOWN")),
)


def build_scoreboard_test_plan(syoscb_plan) -> list:
    """Item 24. One test intent per (scoreboard group x intent), derived from
    the REAL SYOSCB-14 plan -- never a fixed list of test names.

    A group whose producer attribution is unresolved yields intents marked
    `REQUIRED_HUMAN_INPUT`: a stress test over a scoreboard that cannot say
    which master produced an item would report noise, not a failure."""
    if not syoscb_plan:
        return []
    blocked = set(syoscb_plan.get("scoreboards_blocked_on_producer_attribution") or ())
    plans: list = []
    for group in syoscb_plan.get("scoreboards") or ():
        sid = group["scoreboard_id"]
        # The group's OWN route list, not a re-filter of `plan["routes"]`:
        # `group_routes_into_scoreboards()` already decided which routes belong
        # to this group and excluded the rest, and re-deciding it here is how
        # two counts of "the same" thing drift apart.
        group_routes = list(group.get("route_ids") or ())
        for intent, description, results in SCOREBOARD_TEST_INTENTS:
            plans.append({
                "test_intent": f"{sid}__{intent}",
                "scoreboard_id": sid,
                "description": description,
                "route_count": len(group_routes),
                "expected_results": list(results),
                "status": REQUIRED_HUMAN_INPUT if sid in blocked else "PLANNED",
                "blocked_reason": ("the scoreboard's slave-side producer attribution "
                                   "is unresolved; see section 22")
                                  if sid in blocked else "",
                "implementation_status": "PHASE_2_ONLY_NO_SV_EMITTED_HERE",
            })
    return plans


def _render_test_plan(test_plan, syoscb_plan) -> str:
    if syoscb_plan is None:
        return _not_supplied(
            "The SYOSCB-14 producer/queue configuration plan",
            "run `syoscb_topology_plan.build_syoscb_configuration_plan()` and pass it "
            "as `syoscb_plan`; test intents are derived per real scoreboard group")
    rows = test_plan if test_plan is not None else build_scoreboard_test_plan(syoscb_plan)
    return "\n".join([
        f"{len(rows)} test intent(s), derived as (real scoreboard group) x "
        f"({len(SCOREBOARD_TEST_INTENTS)} intent). No test source is written, named or "
        "generated in Phase 1.", "",
        render_markdown_table(
            [("test_intent", "Test Intent"), ("scoreboard_id", "Scoreboard"),
             ("description", "What It Drives"), ("route_count", "Routes"),
             ("status", "Status")],
            [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in r.items()}
             for r in rows],
            empty_note="(the plan produced no scoreboard group, so no test intent "
                       "could be derived)")])


def _render_build_integration_plan(audit) -> str:
    """Item 25. SYOSCB-25/26 need a real VCS/UVM toolchain run, which Phase 1
    may not perform -- so the COMPILE is NOT_AVAILABLE, stated as such. What
    IS available today is the real compile order and the real vendor makefiles
    the read-only audit found, and those are reported."""
    lines = [
        "**The build itself is NOT_AVAILABLE in Phase 1.** SYOSCB-25 (filelist / "
        "compile-order integration) and SYOSCB-26 (baseline compile and run) both "
        "require invoking a real VCS/UVM toolchain against a vendored copy of the "
        "upstream tree. Both are Phase-2-only per SYOSCB-33/34: nothing is vendored "
        "yet (section 4) and no toolchain is invoked here.", "",
        "What Phase 1 CAN establish, read-only, is the compile order a Phase-2 "
        "filelist has to honour and the build files upstream already ships:", "",
    ]
    if audit is None:
        return "\n".join(lines + [_not_supplied(
            "The SYOSCB-1 read-only source audit",
            "run `syoscb_source_audit.audit_syoscb_source()` and pass it as `audit`")])
    order = audit.package.get("compile_order") or []
    rows = [{"item": "package file",
             "value": audit.package.get("file") or REQUIRED_HUMAN_INPUT},
            {"item": "package name",
             "value": audit.package.get("name") or REQUIRED_HUMAN_INPUT},
            {"item": "include count in compile order", "value": str(len(order))},
            {"item": "requires UVM",
             "value": str(audit.uvm_dependency["requires_uvm"])},
            {"item": "UVM version stated upstream",
             "value": str(audit.uvm_dependency["uvm_version"])},
            {"item": "upstream build scripts",
             "value": ", ".join(audit.scripts) or "(none found)"}]
    return "\n".join(lines + [
        render_markdown_table([("item", "Build Input"), ("value", "Value")], rows), "",
        "Compile order (source order of the package's own includes):", "",
        "\n".join(f"{i}. `{inc}`" for i, inc in enumerate(order, start=1))
        or "(no package file with includes was found)"])


def _render_knowledge_center_plan(payload) -> str:
    """Item 26. The SYOSCB-3 registration record, BUILT and not published.
    Publishing is an explicit `KnowledgeCenterClient.record_component()` call
    on the existing shared store -- there is no second store anywhere here."""
    if payload is None:
        return _not_supplied(
            "The SYOSCB-3 registration payload",
            "run `syoscb_source_audit.build_component_registration_payload(audit)` "
            "and pass it as `registration_payload`")
    blockers = ssa.registration_blockers(payload)
    rows = [{"field": k, "value": _short(payload.get(k))}
            for k in THIRD_PARTY_COMPONENT_FIELDS]
    return "\n".join([
        "The record below is BUILT, not published. It is keyed by "
        "`knowledge_center.THIRD_PARTY_COMPONENT_FIELDS` and is written to the "
        "EXISTING Knowledge Center through `KnowledgeCenterClient.record_component()`; "
        "no parallel store is created.", "",
        render_markdown_table([("field", "Field"), ("value", "Value")], rows), "",
        ("REGISTRATION BLOCKERS (fields a human still owes this record): "
         + ", ".join(blockers)) if blockers else "REGISTRATION BLOCKERS: (none)"])


def _short(value, limit: int = 220) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + f"... ({len(text)} chars)"


def _render_readiness(port_readiness, checklist) -> str:
    """Item 27. Two readiness rollups, neither invented here: AMBA-29's
    per-port bind readiness (`derive_overall_readiness()`, the ONLY readiness
    vocabulary in this repo) and the SYOSCB-33 gate checklist."""
    parts: list = []
    if port_readiness is None:
        parts.append(_not_supplied(
            "AMBA-29's per-port readiness",
            "run `amba_discovery_report.build_port_readiness()` and pass it as "
            "`port_readiness`"))
    else:
        overall = derive_overall_readiness(port_readiness)
        parts += [
            f"Overall AMBA verification readiness: **{overall['overall']}** "
            f"({overall['ready_ports']}/{overall['total_ports']} port(s) "
            f"{BIND_READINESS_READY}).", "",
            render_markdown_table(
                [("status", "Readiness"), ("count", "Ports")],
                [{"status": s, "count": str(overall["counts"].get(s, 0))}
                 for s in (BIND_READINESS_READY, BIND_READINESS_PARTIAL,
                           BIND_READINESS_BLOCKED, BIND_READINESS_UNKNOWN)]),
        ]
    parts += ["", "### SYOSCB-33 gate checklist", "",
              render_markdown_table(
                  [("line", "Gate Line"), ("precondition", "Precondition"),
                   ("complete", "Complete")],
                  [{"line": line, "precondition": key,
                    "complete": "yes" if checklist.get(key) is True else "NO"}
                   for line, key in SYOSCB33_GATE_PRECONDITIONS])]
    return "\n".join(parts)


def collect_open_blockers(*, audit=None, ir_templates=None, adapter_plans=None,
                          predictions=None, syoscb_plan=None,
                          compare_resolutions=None, match_key_schemas=None,
                          taxonomy_rows=None, registration_payload=None) -> list:
    """Item 28. Every open question, from every module that already knows how
    to name its own -- aggregated, never re-derived.

    Each source is that module's OWN `unresolved_*` / `unanswered_*` function,
    so a question this report shows is exactly the question its owning module
    would raise, and adding one there makes it appear here for free."""
    rows: list = []

    def _add(source, subject, question):
        rows.append({"source": source, "subject": str(subject),
                     "question": str(question)})

    for item in ssa.unanswered_audit_items(audit) if audit is not None else ():
        _add("SYOSCB-1 source audit", item, "checklist item unanswered from the tree")
    for template in ir_templates or ():
        for field_name in air.unresolved_ir_fields(template):
            _add("SYOSCB-9 IR", template.get("port_id"), f"IR field `{field_name}`")
    for entry in air.unresolved_adapter_plans(adapter_plans or []):
        _add("SYOSCB-10 adapter plan", entry.get("adapter_id"), entry.get("rationale"))
    for prediction in predictions or ():
        for name in artp.unresolved_responsibilities(prediction):
            _add("SYOSCB-12 predictor", prediction.get("route_id"),
                 f"route responsibility `{name}`")
    for question in (stp.unresolved_plan_questions(syoscb_plan)
                     if syoscb_plan else ()):
        _add("SYOSCB-14/16 plan", question["subject"], question["question"])
    for sid in scp.unresolved_compare_strategies(compare_resolutions or []):
        _add("SYOSCB-17 compare strategy", sid, "no compare strategy resolved")
    for schema in match_key_schemas or ():
        for axis in schema.get("unresolved_axes") or ():
            _add("SYOSCB-18 match key", schema.get("protocol"), f"axis `{axis}`")
    for counter in srt.unresolved_port_visibility_counters(taxonomy_rows or []):
        _add("SYOSCB-22 counters", counter.get("port_id"),
             f"{counter.get('counter')}: {counter.get('status')}")
    for field_name in (ssa.registration_blockers(registration_payload)
                       if registration_payload is not None else ()):
        _add("SYOSCB-3 registration", field_name, REQUIRED_HUMAN_INPUT)
    return rows


def _render_open_blockers(blockers) -> str:
    return "\n".join([
        f"{len(blockers)} open item(s). Every one must be answered by a human or by "
        "more evidence before SYOSCB-34 implementation may begin. Each row is raised "
        "by the module that owns the question, not re-derived here.", "",
        render_markdown_table(
            [("source", "Source"), ("subject", "Subject"),
             ("question", "Open Question / Missing Evidence")], blockers,
            empty_note="(nothing is open -- every planning artifact resolved)")])


def build_phase1_gate_checklist(*, netlist=None, traces=None, registry=None,
                                plan=None, audit=None, registration_payload=None,
                                adapter_plans=None, predictions=None,
                                syoscb_plan=None) -> dict:
    """SYOSCB-33's nine preconditions, DERIVED from what was really supplied.

    A precondition is True only when the artifact that backs its gate line
    really exists and is non-empty. `build_phase1_gate_checklist()` never
    reads a caller-supplied boolean: a checklist an agent can fill in for
    itself is not a gate.

    WHAT "COMPLETE" MEANS HERE, AND WHAT IT DOES NOT
    ------------------------------------------------
    A plan is complete when it EXISTS and has an entry for everything it was
    asked about -- including entries that honestly read `REQUIRED_HUMAN_INPUT`.
    It is emphatically NOT "no question remains": the open questions ARE the
    thing the human reads at this gate, and they are listed in section 28.
    Requiring zero open questions would make the gate unreachable on any real
    fabric and would push a planner toward guessing values to clear it, which
    is the failure this whole taxonomy exists to prevent. Two preconditions
    are stricter because their OWNING module defines an unanswered item as an
    incomplete artifact rather than an open question: the SYOSCB-1 checklist
    (`unanswered_audit_items()`, a file that was never read) and the SYOSCB-10
    adapter verdict (`unresolved_adapter_plans()`, meaning the mandated search
    for an existing adapter was never performed)."""
    return {
        "amba_fabric_discovery_complete": bool(netlist is not None and traces),
        "amba_port_registry_complete": bool(registry),
        "vip_bind_plan_complete": bool(plan is not None
                                       and list(getattr(plan, "matrix", ()) or ())),
        "syosil_source_audit_complete": bool(
            audit is not None and not ssa.unanswered_audit_items(audit)),
        "syosil_integration_plan_complete": bool(registration_payload is not None),
        "amba_scoreboard_architecture_complete": bool(
            syoscb_plan is not None and (syoscb_plan.get("scoreboards") or ())),
        "producer_queue_mapping_plan_complete": bool(
            syoscb_plan is not None and (syoscb_plan.get("producers") or ())
            and (syoscb_plan.get("queues") or ())),
        "amba_adapter_plan_complete": bool(
            adapter_plans is not None
            and not air.unresolved_adapter_plans(adapter_plans)),
        "route_predictor_plan_complete": bool(predictions),
    }


def phase1_gate_blockers(checklist: dict) -> list:
    """Which of SYOSCB-33's nine preconditions are not complete, in gate order."""
    return [key for _, key in SYOSCB33_GATE_PRECONDITIONS
            if checklist.get(key) is not True]


def render_phase1_gate_report(checklist: dict) -> str:
    """SYOSCB-33's stop report, EXACTLY -- eleven lines then a blank line then
    STOP.

    Refuses to render while any of the nine preconditions is incomplete, for
    the reason `capability_evolution.render_stop_report()` refuses: printing
    "AMBA ADAPTER PLAN COMPLETE" over an adapter plan nobody finished is a
    false claim to the human who is about to approve Phase 2. The refusal
    names what is missing."""
    blockers = phase1_gate_blockers(checklist)
    if blockers:
        raise SyoscbPhase1ReportError("SYOSCB33_GATE_PRECONDITIONS_INCOMPLETE", {
            "incomplete": blockers,
            "hint": "SYOSCB-33's stop report may not be rendered while a precondition "
                    "is unmet; report the incomplete checklist instead"})
    return "\n".join(SYOSCB33_GATE_LINES) + "\n\nSTOP."


def _render_review_gate(checklist: dict, open_blockers=None) -> str:
    """Section 29. The gate text when it is honestly earnable, and the exact
    reason it is not when it is not.

    The open-blocker count is printed next to the gate text on purpose: nine
    lines reading COMPLETE must never be mistaken for "nothing is open". They
    mean every planning artifact exists; section 28 says what it still asks."""
    tail = [
        "",
        f"{len(list(open_blockers or ()))} open item(s) remain in section 28. "
        "COMPLETE above means every planning artifact EXISTS and has an entry for "
        "everything it was asked about -- including entries that read "
        f"`{REQUIRED_HUMAN_INPUT}`. It does not mean nothing is open; the open items "
        "are exactly what this gate asks a human to read.",
        "", "Nothing in this report vendors, copies or quotes upstream source; nothing "
        "here emits SystemVerilog; no VCS/UVM build was invoked. Per SYOSCB-34, "
        "copying the complete `uvm_syoscb-1.0.2.4` tree into this repository, updating "
        "build/filelists, the baseline compile, and any adapter/IR/predictor/topology "
        "CODE begin ONLY after a human explicitly approves this report.",
    ]
    try:
        return "\n".join(["```", render_phase1_gate_report(checklist), "```"] + tail)
    except SyoscbPhase1ReportError as exc:
        blockers = exc.detail["incomplete"]
        return "\n".join([
            "**SYOSCB-33's stop report is NOT rendered.** It may not claim COMPLETE "
            "over work that is not complete. The unmet preconditions are:", "",
            render_markdown_table(
                [("line", "Gate Line It Would Claim"), ("precondition", "Precondition")],
                [{"line": line, "precondition": key}
                 for line, key in SYOSCB33_GATE_PRECONDITIONS if key in blockers]),
        ] + tail)


# ---------------------------------------------------------------------------
# The assembler
# ---------------------------------------------------------------------------

@dataclass
class SyoscbPhase1Report:
    """The twenty-nine sections, in SYOSCB-30's order, each already rendered."""
    sections: list = field(default_factory=list)     # [(number, title, body)]
    architecture: Optional[ArchitectureRepresentation] = None
    gate_checklist: dict = field(default_factory=dict)
    open_blockers: list = field(default_factory=list)

    @property
    def titles(self) -> list:
        return [t for _, t, _ in self.sections]

    def section(self, number: int) -> str:
        for num, _, body in self.sections:
            if num == number:
                return body
        raise SyoscbPhase1ReportError("SYOSCB30_SECTION_NOT_PRESENT", {
            "number": number, "present": [n for n, _, _ in self.sections]})

    def to_dict(self) -> dict:
        return {"sections": [{"number": n, "title": t, "body": b}
                             for n, t, b in self.sections],
                "architecture": (self.architecture.to_dict()
                                 if self.architecture else None),
                "gate_checklist": dict(self.gate_checklist),
                "open_blockers": [dict(b) for b in self.open_blockers]}


def build_syoscb_phase1_report(*, netlist=None, traces=None, plan=None, registry=None,
                               audit=None, registration_payload=None, repo_root=None,
                               domain_analyses=None, address_cross_check=None,
                               scoreboard_env=None, ingress_mapping=None,
                               ir_templates=None, adapter_plans=None,
                               predictions=None, route_cross_check=None,
                               syoscb_plan=None, compare_resolutions=None,
                               match_key_schemas=None, taxonomy_rows=None,
                               port_readiness=None, test_plan=None,
                               proposed_integration_location=None
                               ) -> SyoscbPhase1Report:
    """SYOSCB-30's twenty-nine sections, assembled from artifacts other modules
    already computed.

    Every argument is optional and every omission renders a visible NOT
    SUPPLIED note naming the function that would fill it -- a section is never
    silently dropped, because a reader told there are twenty-nine sections uses
    that to notice one is missing.

    Sections 6-16 and 19-23 are the EXISTING AMBA-6..25 and SYOSCB-9..22
    renderers called in the mandated order. Nothing they render is recomputed
    here."""
    architecture = build_architecture_tree(
        registry=registry, traces=traces, plan=plan, adapter_plans=adapter_plans,
        predictions=predictions, syoscb_plan=syoscb_plan, audit=audit,
        taxonomy_rows=taxonomy_rows)
    checklist = build_phase1_gate_checklist(
        netlist=netlist, traces=traces, registry=registry, plan=plan, audit=audit,
        registration_payload=registration_payload, adapter_plans=adapter_plans,
        predictions=predictions, syoscb_plan=syoscb_plan)
    blockers = collect_open_blockers(
        audit=audit, ir_templates=ir_templates, adapter_plans=adapter_plans,
        predictions=predictions, syoscb_plan=syoscb_plan,
        compare_resolutions=compare_resolutions, match_key_schemas=match_key_schemas,
        taxonomy_rows=taxonomy_rows, registration_payload=registration_payload)

    fabric_missing = _not_supplied(
        "The AMBA-7..20 fabric discovery artifacts",
        "run `amba_fabric_discovery.build_fabric_netlist()`, "
        "`trace_all_fabric_ports()` and `build_vip_bind_plan()`, then pass "
        "`netlist`, `traces` and `plan`")

    bodies = {
        1: _render_capability_audit(),
        2: _render_source_directory_audit(audit),
        3: _render_license_provenance(audit),
        4: _render_third_party_discovery(repo_root, audit),
        5: _render_proposed_location(proposed_integration_location,
                                     registration_payload),
        6: (afd.render_amba_topology_summary(plan.summary) if plan is not None
            else fabric_missing),
        7: (afd.render_fabric_vip_bind_matrix(plan.matrix) if plan is not None
            else fabric_missing),
        8: (_render_protocol_classification(registry) if registry
            else _not_supplied(
                "The AMBA_PORT_REGISTRY",
                "run `amba_port_registry.build_amba_port_registry()` and pass "
                "`registry`")),
        9: (afd.render_amba_topology_summary(plan.summary) if plan is not None
            else fabric_missing),
        10: (afd.render_endpoint_trace_report(traces) if traces else fabric_missing),
        11: (afd.render_fabric_vip_bind_matrix(plan.matrix) if plan is not None
             else fabric_missing),
        12: (afd.render_unresolved_fabric_port_table(plan.unresolved)
             if plan is not None else fabric_missing),
        13: (render_amba_port_registry(registry) if registry else _not_supplied(
            "The AMBA_PORT_REGISTRY",
            "run `amba_port_registry.build_amba_port_registry()` and pass `registry`")),
        14: (_clock_reset_report(domain_analyses) if domain_analyses is not None
             else _not_supplied(
                 "AMBA-24's clock/reset domain analysis",
                 "run `amba_fabric_analysis.analyze_all_bind_point_domains()` and pass "
                 "it as `domain_analyses`")),
        15: _render_address_route_analysis(address_cross_check, route_cross_check),
        16: (render_scoreboard_env_report(scoreboard_env, ingress_mapping)
             if scoreboard_env is not None or ingress_mapping is not None
             else _not_supplied(
                 "AMBA-21's reference scoreboard environment analysis",
                 "run `amba_scoreboard_env.analyze_scoreboard_environment()` and pass "
                 "it as `scoreboard_env`")),
        17: _render_capability_mapping(audit),
        18: _render_limitation_analysis(audit, registry),
        19: (air.render_ir_template_table(ir_templates) if ir_templates
             else _not_supplied(
                 "SYOSCB-9's AMBA transaction IR templates",
                 "run `amba_transaction_ir.build_transaction_ir_templates(registry)` "
                 "and pass them as `ir_templates`")),
        20: (air.render_adapter_plan_table(adapter_plans)
             if adapter_plans is not None else _not_supplied(
                 "SYOSCB-10's adapter plan",
                 "run `amba_transaction_ir.plan_amba_adapters(registry, "
                 "existing_adapters)` and pass it as `adapter_plans`")),
        21: (artp.render_route_transform_report(predictions, route_cross_check)
             if predictions else _not_supplied(
                 "SYOSCB-12's route/transform predictions",
                 "run `amba_route_transform_predictor.predict_routes(registry)` and "
                 "pass them as `predictions`")),
        22: (stp.render_syoscb_configuration_plan_report(syoscb_plan)
             if syoscb_plan is not None else _not_supplied(
                 "SYOSCB-14/15/16's producer/queue mapping plan",
                 "run `syoscb_topology_plan.build_syoscb_configuration_plan(registry, "
                 "predictions)` and pass it as `syoscb_plan`")),
        23: scp.render_compare_policy_report(
            compare_resolutions, match_key_schemas, audit),
        24: _render_test_plan(test_plan, syoscb_plan),
        25: _render_build_integration_plan(audit),
        26: _render_knowledge_center_plan(registration_payload),
        27: _render_readiness(port_readiness, checklist),
        28: _render_open_blockers(blockers),
        29: _render_review_gate(checklist, blockers),
    }
    return SyoscbPhase1Report(
        sections=[(num, title, bodies[num]) for num, title in SYOSCB30_SECTIONS],
        architecture=architecture, gate_checklist=checklist, open_blockers=blockers)


def _render_protocol_classification(registry) -> str:
    """Section 8. Read off the registry's own `protocol` column -- the same
    column sections 9, 13, 19 and 20 read, so no two sections of this report
    can disagree about what protocol a port speaks."""
    counts: dict = {}
    for row in registry:
        counts[row.get("protocol")] = counts.get(row.get("protocol"), 0) + 1
    rows = [{"protocol": p, "display": AMBA4_DISPLAY_NAMES.get(p, p),
             "ports": str(n)} for p, n in sorted(counts.items())]
    return render_markdown_table(
        [("protocol", "Protocol Key"), ("display", "Display Name"),
         ("ports", "Registry Rows")], rows,
        empty_note="(no AMBA_PORT_REGISTRY row carried a protocol)")


def _clock_reset_report(domain_analyses) -> str:
    """Imported lazily for the reason `amba_discovery_report` does it: keeping
    the dependency one-way at module scope means neither module can become
    unimportable because of the other."""
    from dv_harness.amba_fabric_analysis import render_clock_reset_domain_report
    return render_clock_reset_domain_report(domain_analyses)


def _render_address_route_analysis(address_cross_check, route_cross_check) -> str:
    parts: list = []
    if address_cross_check is not None:
        from dv_harness.amba_fabric_analysis import render_address_map_cross_check_report
        parts += ["### AMBA-23 address-map cross-check", "",
                  render_address_map_cross_check_report(address_cross_check), ""]
    if route_cross_check is not None:
        parts += ["### SYOSCB-13 address-map evidence cross-check", "",
                  artp.render_address_map_cross_check(route_cross_check), ""]
    if not parts:
        return _not_supplied(
            "An address-map cross-check",
            "run `amba_fabric_analysis.cross_check_address_map()` and/or "
            "`amba_route_transform_predictor.cross_check_address_map_evidence()` and "
            "pass the result as `address_cross_check` / `route_cross_check`")
    parts += ["### SYOSCB-13 address-map evidence types", "",
              artp.render_address_map_evidence_types()]
    return "\n".join(parts)


def _heading(number: int, title: str) -> str:
    return f"## {number}. {title}"


def render_syoscb_phase1_report(
        report: SyoscbPhase1Report, *,
        title: str = "SYOSCB AMBA SoC Bus Scoreboard -- Phase-1 Report") -> str:
    """The whole report, in SYOSCB-30's exact order, self-checked.

    Three self-checks before it is returned: the twenty-nine headings really
    are present, once each, in order; the text contains no bind statement; and
    it contains no emittable SystemVerilog."""
    lines = [f"# {title}", "",
             f"SYOSCB-30 mandates this exact twenty-nine-item order "
             f"(`{SYOSCB_DOC}:5294-5322`). Every section is present; one whose input "
             "was not supplied says so rather than being omitted.", "",
             "## SYOSCB-29 ARCHITECTURE REPRESENTATION", ""]
    if report.architecture is not None:
        lines += ["```", render_architecture_tree(report.architecture), "```", ""]
        unpopulated = unpopulated_architecture_branches(report.architecture)
        lines += [f"Branches with no real artifact behind them: "
                  f"{', '.join(unpopulated) if unpopulated else '(none)'}", ""]
    for number, sec_title, body in report.sections:
        lines += [_heading(number, sec_title), "", body, ""]
    text = "\n".join(lines)
    assert_report_section_order(text)
    assert_no_bind_statement(text)
    ssa.assert_no_emittable_sv(text, label="SYOSCB-30 Phase-1 report")
    return text


def assert_report_section_order(text: str) -> None:
    """SYOSCB-30's "produce" order, verified against the FINISHED text.

    Checking the source tuple would only prove the tuple agrees with itself. A
    heading a section body accidentally swallowed, duplicated or emitted out of
    order is a real failure mode this catches and that one would not."""
    body = str(text or "")
    positions: list = []
    for number, sec_title in SYOSCB30_SECTIONS:
        heading = _heading(number, sec_title)
        count = body.count("\n" + heading + "\n") + (
            1 if body.startswith(heading + "\n") else 0)
        if count == 0:
            raise SyoscbPhase1ReportError("SYOSCB30_SECTION_MISSING", {
                "number": number, "title": sec_title, "expected_heading": heading,
                "hint": "SYOSCB-30 mandates all twenty-nine sections; a section with "
                        "no input must render a NOT SUPPLIED note, never be omitted"})
        if count > 1:
            raise SyoscbPhase1ReportError("SYOSCB30_SECTION_DUPLICATED", {
                "number": number, "title": sec_title, "occurrences": count})
        positions.append((number, 0 if body.startswith(heading + "\n")
                          else body.index("\n" + heading + "\n")))
    ordered = [n for n, _ in sorted(positions, key=lambda p: p[1])]
    expected = [n for n, _ in SYOSCB30_SECTIONS]
    if ordered != expected:
        raise SyoscbPhase1ReportError("SYOSCB30_SECTIONS_OUT_OF_ORDER", {
            "found_order": ordered, "required_order": expected})


_assert_adapter_order_is_the_real_protocol_set()
_assert_every_result_is_placed()
_assert_gate_preconditions_cover_every_claim()
