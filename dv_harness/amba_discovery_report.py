"""dv_harness/amba_discovery_report.py -- AMBA-26, AMBA-27, AMBA-28 and
AMBA-29: the four requirements that turn an already-discovered fabric topology
into the artifact a human actually reviews at AMBA-30's gate.

AMBA-26  L5 BRANCH MAPPING
AMBA-27  EVIDENCE + CONFIDENCE RULE
AMBA-28  DISCOVERY REPORT ORDER (the exact seventeen-item sequence)
AMBA-29  READINESS (per port, and the overall rollup derived from it)

WHY ONE MODULE, AND WHY NOT MORE OF `amba_fabric_discovery.py`
--------------------------------------------------------------
`amba_fabric_discovery.py` answers AMBA-7..20: what is on the other end of
each fabric port, and where a VIP could sit. `amba_port_registry.py` answers
AMBA-22, `amba_fabric_analysis.py` answers AMBA-23..25. All three PRODUCE
facts. The four requirements here CONSUME every one of those outputs and
produce nothing new about the RTL at all:

  * AMBA-26 is a naming projection of an already-computed port list and VIP
    plan onto this repo's existing L5 branch vocabulary.
  * AMBA-27 is a cross-cutting labelling rule over conclusions other modules
    already reached.
  * AMBA-28 is an ordering contract over renderers that already exist.
  * AMBA-29 is a reduction of already-computed per-port attributes.

Putting them in the discovery module would mean the module that DERIVES a
fact also decides how confident to be about it and how to present it, which
is exactly how a "confident" label drifts away from the evidence it was
supposed to summarise. So this module imports and COMPOSES:

  `amba_fabric_discovery.BIND_READINESS_READY/PARTIAL/BLOCKED/UNKNOWN`
      the ONLY readiness vocabulary (AMBA-29). AMBA-18's bind-readiness and
      AMBA-29's port readiness are the same four words on purpose; a second
      four-value enum spelled the same way is the duplicate-classifier failure
      this project has already had to unwind once.
  `amba_fabric_discovery._worst_readiness()`
      the ONLY worst-first reduction used, imported rather than restated so
      AMBA-18's per-port rollup and AMBA-29's overall rollup cannot disagree
      about which of two statuses is worse. (Underscore-named there and
      deliberately imported anyway: duplicating the severity map is the worse
      of the two sins.)
  `connectivity.BindTier` / `classify_bind_tier()`
      the ONLY bind-confidence classifier. AMBA-27's HIGH/MEDIUM/LOW/UNKNOWN
      is a DIFFERENT axis (how strong is the evidence for THIS conclusion) and
      is DERIVED from the tier plus the real structural facts -- it never
      re-classifies anything, and `classify_port_conclusions()` is the single
      place the derivation lives.

A FOURTH TRUST VOCABULARY, AND WHY IT IS NOT A DUPLICATE
--------------------------------------------------------
`dv_harness_tests/test_confidence_vocabulary_separation.py` already keeps three
trust-ranking mechanisms apart: `inference.score_confidence()` (HIGH/MEDIUM/LOW
by evidence QUANTITY), `connectivity.classify_bind_tier()` (T1-T4 by evidence
KIND/authority) and `question_queue.classify_tier()` (escalation route).
AMBA-27's scale reuses `inference`'s three words and adds UNKNOWN, so the
question has to be answered rather than left for the next auditor:

  * `score_confidence()` is ADDITIVE -- more independent sources, more
    consensus, fewer counter-evidence points, higher level.
  * AMBA-27's MEDIUM is defined by the doc as "strong structural evidence with
    ONE unresolved abstraction", and LOW as two or more (or naming-heavy
    evidence). That is a SUBTRACTIVE rule over a countable set of named
    unresolved abstractions (`unresolved_abstractions()`), and it is not a
    function of how many evidence references a conclusion cites: a port with
    six citations and three opaque hops is LOW here and HIGH there.

So `score_confidence()` cannot express this scale, and routing AMBA-27 through
it would report a heavily-cited but structurally-unresolved port as confirmed
topology -- exactly what AMBA-27's last line forbids.
`dv_harness_tests/test_amba_discovery_report.py` demonstrates that with real
calls into both, in the same executable form the existing separation test uses.
The three-way disjointness that test enforces is untouched: nothing here is
added to `inference.CONFIDENCE_LEVELS`, to `BindTier`, or to the question-queue
tiers, and this module imports none of them for classification.
  `connectivity.render_markdown_table()`
      the ONLY table renderer.
  every AMBA-16..25 renderer
      composed by AMBA-28's assembler, never reimplemented.
  `tools/verification_flow/branch_topology_gate.py`'s schema
      AMBA-26's output is emitted in exactly that gate's shape (`branch_a0..`,
      `branch_b0..`, `block`, `branch_fw`, `dut_port_count`, `vip_port_count`,
      `cross_branch_bus_model`) so it is checkable by the validator this repo
      already runs, not by a competing new one.

TWO PLACES THIS DELIBERATELY REFUSES TO ROUND UP
------------------------------------------------
  * AMBA-26's `branch_fw` applicability. The doc says "firmware/interrupt-
    triggered behavior WHEN APPLICABLE". Whether a fabric raises interrupts is
    established here only from real port names on the real fabric instance,
    which is a NAMING heuristic and is tiered as one (T3, LOW confidence,
    `requires_human_confirmation`). No interrupt evidence means
    `branch_fw_interrupt_driven` is False and the existing branch-topology gate
    will refuse the mapping until a human supplies the contract -- which is the
    honest outcome, not a bug to be papered over by defaulting it True.
  * AMBA-26's `cross_branch_bus_model.arbitration_policy`. Round-robin vs
    priority vs QoS is not derivable from a port list; it is
    `REQUIRED_HUMAN_INPUT` until someone reads the arbiter RTL.
    `branch_topology_gate_blockers()` names it rather than inventing one.

DISCOVERY AND PLANNING ONLY (AMBA-30 / AMBA-31)
-----------------------------------------------
Nothing here writes, renders or returns a SystemVerilog `bind` statement, and
the assembled report is self-checked with
`amba_fabric_discovery.assert_no_bind_statement()` before it is returned, for
the same reason every AMBA-16..25 artifact is. Section 17 of the report IS
AMBA-30's gate text; this module's whole output is what that gate is held
against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from dv_harness import amba_fabric_discovery as afd
from dv_harness.amba_fabric_discovery import (
    BIND_CHECK_FAILED,
    BIND_CHECK_UNKNOWN_VALUE,
    BIND_READINESS_BLOCKED,
    BIND_READINESS_PARTIAL,
    BIND_READINESS_READY,
    BIND_READINESS_UNKNOWN,
    BIND_READINESS_VALUES,
    FabricDiscoveryError,
    MULTIPLE_BRANCH_PARENT_BIND,
    StructuralRole,
    TraceTerminationStatus,
    assert_no_bind_statement,
    find_bundle,
    parse_instance_path,
    parent_matrix_rows,
    render_amba_topology_summary,
    render_fabric_vip_bind_matrix,
    render_unresolved_fabric_port_table,
    render_vip_instance_plan,
)
# Imported, not restated: AMBA-18's per-port branch rollup and AMBA-29's
# overall rollup must agree about which of two statuses is worse, and a second
# severity map is how they would stop agreeing.
from dv_harness.amba_fabric_discovery import _worst_readiness as worst_readiness
from dv_harness.amba_port_registry import (
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
    render_amba_port_registry,
)
from dv_harness.amba_scoreboard_env import render_scoreboard_env_report
from dv_harness.connectivity import (
    AMBA_PROTOCOL_UNRESOLVED,
    AmbaClassificationStatus,
    BindTier,
    REQUIRED_HUMAN_INPUT,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
    classify_bind_tier,
    render_markdown_table,
)


class DiscoveryReportError(FabricDiscoveryError):
    """Raised when a report/mapping/readiness contract is violated."""


# ===========================================================================
# AMBA-27: EVIDENCE + CONFIDENCE RULE
#
# "Every conclusion must reference actual evidence" and carry exactly one of
# four confidence levels. Both halves are enforced here rather than requested:
# a `Conclusion` cannot be constructed with an unknown evidence kind, a
# non-UNKNOWN conclusion cannot be constructed with no evidence at all, and an
# UNKNOWN one cannot be constructed without naming what is missing.
# ===========================================================================

#: The doc's own twelve evidence kinds, in the doc's own order. `(key, label)`.
#: The tuple is the contract: `EvidenceRef` validates against it, so a
#: conclusion cannot cite a thirteenth kind nobody agreed on.
AMBA27_EVIDENCE_KINDS: tuple = (
    ("RTL_INSTANCE", "RTL instance"),
    ("PORT_CONNECTION", "port connection"),
    ("ASSIGN", "assign"),
    ("INTERFACE", "interface"),
    ("GENERATE", "generate"),
    ("WRAPPER", "wrapper"),
    ("BRIDGE", "bridge"),
    ("PARAMETER", "parameter"),
    ("DEFINE", "define"),
    ("FILELIST", "filelist"),
    ("CONFIG", "config"),
    ("ADDRESS_MAP_SUPPORT", "address-map support"),
)

EVIDENCE_KIND_KEYS: frozenset = frozenset(k for k, _ in AMBA27_EVIDENCE_KINDS)
EVIDENCE_KIND_LABELS: dict = dict(AMBA27_EVIDENCE_KINDS)

#: AMBA-27's four levels, spelled exactly as the doc spells them.
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_UNKNOWN = "UNKNOWN"
CONFIDENCE_VALUES: tuple = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM,
                            CONFIDENCE_LOW, CONFIDENCE_UNKNOWN)

#: The doc's own definitions, carried with the values so a report can print
#: what a level MEANS instead of assuming the reader remembers.
CONFIDENCE_DEFINITIONS: dict = {
    CONFIDENCE_HIGH: "direct RTL connectivity",
    CONFIDENCE_MEDIUM: "strong structural evidence with one unresolved abstraction",
    CONFIDENCE_LOW: "incomplete or naming-heavy evidence",
    CONFIDENCE_UNKNOWN: "cannot prove",
}

#: "LOW/UNKNOWN must not be reported as confirmed topology." The two levels a
#: confirmed-topology claim may rest on, and nothing else.
CONFIRMED_TOPOLOGY_CONFIDENCE: frozenset = frozenset({CONFIDENCE_HIGH, CONFIDENCE_MEDIUM})

#: Worst-first, for reducing several conclusions about one port to the one
#: level that port's row carries.
_CONFIDENCE_SEVERITY: dict = {CONFIDENCE_UNKNOWN: 0, CONFIDENCE_LOW: 1,
                              CONFIDENCE_MEDIUM: 2, CONFIDENCE_HIGH: 3}


def worst_confidence(values) -> str:
    """The weakest of several confidence levels. A port is only as confidently
    known as its least-established attribute."""
    vals = [v for v in values if v in _CONFIDENCE_SEVERITY]
    if not vals:
        return CONFIDENCE_UNKNOWN
    return min(vals, key=lambda v: _CONFIDENCE_SEVERITY[v])


@dataclass(frozen=True)
class EvidenceRef:
    """One citation, of one of AMBA-27's twelve kinds.

    `detail` is required and must be non-empty: "RTL_INSTANCE" on its own is
    not a reference to actual evidence, it is a category name."""
    kind: str
    detail: str

    def __post_init__(self):
        if self.kind not in EVIDENCE_KIND_KEYS:
            raise DiscoveryReportError("AMBA27_UNKNOWN_EVIDENCE_KIND", {
                "kind": self.kind, "known_kinds": sorted(EVIDENCE_KIND_KEYS),
                "hint": "AMBA-27 lists the evidence kinds a conclusion may cite; a "
                        "kind outside that list is not a kind the reviewer agreed to",
            })
        if not str(self.detail or "").strip():
            raise DiscoveryReportError("AMBA27_EVIDENCE_WITHOUT_DETAIL", {
                "kind": self.kind,
                "hint": "a bare evidence KIND is not a reference to actual evidence; "
                        "cite the instance path, port, assign or file that shows it",
            })

    @property
    def label(self) -> str:
        return EVIDENCE_KIND_LABELS[self.kind]

    def render(self) -> str:
        return f"{self.label}: {self.detail}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label, "detail": self.detail}


@dataclass
class Conclusion:
    """One discovery conclusion, its cited evidence, and its confidence.

    Constructing one enforces both halves of AMBA-27's rule, so an unevidenced
    or unlabelled conclusion cannot reach a report at all."""
    subject: str          # what the conclusion is ABOUT, e.g. "u_fabric:S00_AXI_"
    attribute: str        # which attribute of it, e.g. "protocol"
    statement: str        # the conclusion itself
    confidence: str
    evidence: list = field(default_factory=list)          # list[EvidenceRef]
    missing_evidence: list = field(default_factory=list)  # list[str]

    def __post_init__(self):
        if self.confidence not in CONFIDENCE_VALUES:
            raise DiscoveryReportError("AMBA27_UNKNOWN_CONFIDENCE_LEVEL", {
                "confidence": self.confidence, "known": list(CONFIDENCE_VALUES),
                "subject": self.subject, "attribute": self.attribute,
            })
        bad = [e for e in self.evidence if not isinstance(e, EvidenceRef)]
        if bad:
            raise DiscoveryReportError("AMBA27_EVIDENCE_NOT_AN_EVIDENCE_REF", {
                "subject": self.subject, "attribute": self.attribute,
                "offending": [str(b) for b in bad],
                "hint": "evidence must be EvidenceRef records so its KIND is validated "
                        "against AMBA-27's list rather than being free prose",
            })
        if self.confidence != CONFIDENCE_UNKNOWN and not self.evidence:
            raise DiscoveryReportError("AMBA27_CONCLUSION_WITHOUT_EVIDENCE", {
                "subject": self.subject, "attribute": self.attribute,
                "confidence": self.confidence, "statement": self.statement,
                "hint": "AMBA-27: every conclusion must reference actual evidence. Only "
                        "UNKNOWN ('cannot prove') may cite none, and it must instead say "
                        "what is missing",
            })
        if self.confidence == CONFIDENCE_UNKNOWN and not self.missing_evidence:
            raise DiscoveryReportError("AMBA27_UNKNOWN_WITHOUT_MISSING_EVIDENCE", {
                "subject": self.subject, "attribute": self.attribute,
                "hint": "an UNKNOWN conclusion must name what would settle it, the same "
                        "contract AMBA-14's unresolved trace states already carry",
            })

    @property
    def confirmable(self) -> bool:
        """Whether this conclusion may be reported as confirmed topology."""
        return self.confidence in CONFIRMED_TOPOLOGY_CONFIDENCE

    def to_dict(self) -> dict:
        return {"subject": self.subject, "attribute": self.attribute,
                "statement": self.statement, "confidence": self.confidence,
                "confidence_definition": CONFIDENCE_DEFINITIONS[self.confidence],
                "evidence": [e.to_dict() for e in self.evidence],
                "missing_evidence": list(self.missing_evidence)}


def assert_not_reported_as_confirmed_topology(conclusions, confirmed_subjects) -> None:
    """AMBA-27's hard rule: "LOW/UNKNOWN must not be reported as confirmed
    topology."

    `confirmed_subjects` is whatever the caller is about to present AS
    confirmed -- the masters/slaves lists, a READY port set, a topology JSON.
    A subject in that set whose own conclusions are LOW or UNKNOWN raises."""
    confirmed = set(confirmed_subjects or ())
    offenders = [c for c in conclusions or ()
                 if c.subject in confirmed and not c.confirmable]
    if offenders:
        raise DiscoveryReportError("AMBA27_LOW_OR_UNKNOWN_REPORTED_AS_CONFIRMED", {
            "offending": [{"subject": c.subject, "attribute": c.attribute,
                           "confidence": c.confidence} for c in offenders],
            "hint": "AMBA-27: LOW/UNKNOWN must not be reported as confirmed topology. "
                    "Report the port in the unresolved table with its missing evidence "
                    "instead of promoting it into the confirmed set",
        })


# ---------------------------------------------------------------------------
# Deriving AMBA-27's level from facts AMBA-4..15 already established
# ---------------------------------------------------------------------------

#: Structural roles that are themselves an unresolved abstraction on a traced
#: path: the trace crossed something whose internals it could not establish.
_OPAQUE_HOP_ROLES: frozenset = frozenset({
    StructuralRole.OPAQUE_BLACK_BOX.value,
    StructuralRole.UNDECIDABLE_MULTI_BUNDLE.value,
})

_FOUND_STATUSES: frozenset = frozenset({
    TraceTerminationStatus.SOURCE_FOUND.value,
    TraceTerminationStatus.DESTINATION_FOUND.value,
})

_MULTIPLE_STATUSES: frozenset = frozenset({
    TraceTerminationStatus.MULTIPLE_SOURCE.value,
    TraceTerminationStatus.MULTIPLE_DESTINATION.value,
})


def unresolved_abstractions(netlist, trace, row=None) -> list:
    """Every abstraction on this port's evidence chain that did NOT resolve.

    This is what makes AMBA-27's MEDIUM ("strong structural evidence with ONE
    unresolved abstraction") a countable property rather than a feeling: a
    conclusion is MEDIUM when this list has exactly one entry, and LOW when it
    has two or more. Each entry names the abstraction and where it is, so a
    reviewer can go and resolve it."""
    out: list = []
    bundle = find_bundle(netlist, parse_instance_path(trace.fabric_instance_path),
                         trace.bundle_prefix) if netlist is not None else None
    if bundle is None or not bundle.resolved:
        status = (bundle.classification.status if bundle
                  else "NO_AMBA_BUNDLE_ON_THIS_BOUNDARY")
        out.append({"abstraction": "PROTOCOL_NOT_FULLY_CLASSIFIED",
                    "where": trace.interface_id, "detail": status})
    if bundle is not None and (bundle.roles is None or not bundle.roles.resolved):
        out.append({"abstraction": "FABRIC_SIDE_ROLE_UNRESOLVED",
                    "where": trace.interface_id,
                    "detail": (bundle.roles.unresolved_reason if bundle.roles
                               else "instance declares no port directions "
                                    "(not in the parsed source set)")})
    for branch in trace.branches or ():
        for hop in branch.hops or ():
            if hop.role in _OPAQUE_HOP_ROLES:
                out.append({"abstraction": "OPAQUE_STRUCTURAL_ELEMENT",
                            "where": hop.instance_path,
                            "detail": f"{hop.module_name} classified {hop.role}"})
            elif hop.role_tier == BindTier.T3_NAMING_HEURISTIC.value:
                out.append({"abstraction": "HOP_ROLE_RESTS_ON_A_NAME",
                            "where": hop.instance_path,
                            "detail": f"{hop.module_name} role {hop.role} at "
                                      f"{hop.role_tier}"})
    if trace.status in _MULTIPLE_STATUSES:
        out.append({"abstraction": "MULTIPLE_BRANCHES_NOT_NARROWED",
                    "where": trace.interface_id,
                    "detail": f"{len(trace.branches)} branches enumerated "
                              f"({trace.status}); AMBA-12/13 leave the choice open"})
    for bridge in trace.bridges or ():
        out.append({"abstraction": "ENDPOINT_LIES_BEYOND_A_PROTOCOL_BRIDGE",
                    "where": bridge.bridge_instance_path,
                    "detail": f"{bridge.upstream_protocol} -> "
                              f"{bridge.downstream_protocol}; what lies beyond is a "
                              f"separate trace"})
    return out


def _bundle_evidence(netlist, trace) -> list:
    """The real citations a fabric port always has, when it has a bundle."""
    bundle = find_bundle(netlist, parse_instance_path(trace.fabric_instance_path),
                         trace.bundle_prefix) if netlist is not None else None
    refs = [EvidenceRef("RTL_INSTANCE",
                        f"elaborated instance {trace.fabric_instance_path}")]
    if bundle is not None and bundle.ports:
        refs.append(EvidenceRef(
            "PORT_CONNECTION",
            f"{len(bundle.ports)} ports on {trace.interface_id}: "
            + ", ".join(sorted(bundle.ports)[:6])
            + (" ..." if len(bundle.ports) > 6 else "")))
        refs.append(EvidenceRef(
            "INTERFACE",
            f"{bundle.display_name} classified {bundle.classification.status} from "
            + (", ".join(bundle.classification.discriminators) or "its signal set")))
    return refs


def _path_evidence(branch) -> list:
    """Citations for what a traced path actually crossed."""
    refs: list = []
    for hop in branch.hops or ():
        if hop.role == StructuralRole.WIRE_ASSIGN_ALIAS.value:
            refs.append(EvidenceRef("ASSIGN",
                                    f"continuous assign at {hop.instance_path}"))
        elif hop.role == StructuralRole.PROTOCOL_PRESERVING_ADAPTER.value:
            refs.append(EvidenceRef("WRAPPER",
                                    f"{hop.instance_path} ({hop.module_name}) "
                                    f"{hop.role}"))
        elif hop.role == StructuralRole.PROTOCOL_BRIDGE.value:
            refs.append(EvidenceRef("BRIDGE",
                                    f"{hop.instance_path} ({hop.module_name}) "
                                    f"changes protocol"))
        else:
            refs.append(EvidenceRef("RTL_INSTANCE",
                                    f"{hop.instance_path} ({hop.module_name}) "
                                    f"{hop.role}"))
    return refs


def classify_port_conclusions(netlist, trace, row=None) -> list:
    """AMBA-27 applied to ONE fabric port: four conclusions, each with its own
    evidence and its own confidence.

    Four rather than one because the levels genuinely differ per axis -- an
    AXI4 port whose protocol is proven from its own signal set (HIGH) can sit
    on a black box whose endpoint cannot be established at all (UNKNOWN), and
    collapsing those into one label would either overstate the second or
    understate the first.

    `row` is the port's AMBA-16 matrix row when one exists; it supplies the
    proposed bind location and its AMBA-15 validation."""
    subject = trace.interface_id
    bundle = find_bundle(netlist, parse_instance_path(trace.fabric_instance_path),
                         trace.bundle_prefix) if netlist is not None else None
    base = _bundle_evidence(netlist, trace)
    abstractions = unresolved_abstractions(netlist, trace, row)
    out: list = []

    # -- 1. protocol -------------------------------------------------------
    instance = netlist.instance(parse_instance_path(trace.fabric_instance_path)) \
        if netlist is not None else None
    blackbox = bool(instance is not None and instance.is_blackbox)
    if bundle is None:
        out.append(Conclusion(
            subject=subject, attribute="protocol",
            statement="no AMBA bundle is present on this boundary",
            confidence=CONFIDENCE_UNKNOWN,
            missing_evidence=["the instance's declared port list; without it no signal "
                              "set exists to classify"]))
    elif bundle.resolved and not blackbox:
        out.append(Conclusion(
            subject=subject, attribute="protocol",
            statement=f"{bundle.display_name}", confidence=CONFIDENCE_HIGH,
            evidence=base))
    elif bundle.resolved:
        out.append(Conclusion(
            subject=subject, attribute="protocol",
            statement=f"{bundle.display_name} (on a black-box instance)",
            confidence=CONFIDENCE_MEDIUM, evidence=base))
    else:
        out.append(Conclusion(
            subject=subject, attribute="protocol",
            statement=f"{bundle.classification.status}: candidates "
                      + (", ".join(bundle.classification.candidates) or "none"),
            confidence=CONFIDENCE_LOW, evidence=base))

    # -- 2. fabric-side role ------------------------------------------------
    if bundle is not None and bundle.roles is not None and bundle.roles.resolved:
        out.append(Conclusion(
            subject=subject, attribute="role",
            statement=f"{bundle.roles.fabric_side_role} / "
                      f"{bundle.roles.external_endpoint_role}",
            confidence=CONFIDENCE_HIGH,
            evidence=base + [EvidenceRef("PORT_CONNECTION",
                                         bundle.roles.direction_evidence)]))
    elif bundle is not None and bundle.roles is not None:
        out.append(Conclusion(
            subject=subject, attribute="role",
            statement=ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
            confidence=CONFIDENCE_LOW, evidence=base))
    else:
        out.append(Conclusion(
            subject=subject, attribute="role", statement="no role could be derived",
            confidence=CONFIDENCE_UNKNOWN,
            missing_evidence=["per-signal port DIRECTIONS on this boundary; a black-box "
                              "instantiation names ports but never their directions"]))

    # -- 3. endpoint --------------------------------------------------------
    resolved_branches = [b for b in trace.branches or ()
                         if b.status in _FOUND_STATUSES]
    if resolved_branches:
        path_refs = [r for b in resolved_branches for r in _path_evidence(b)]
        endpoints = ", ".join(b.endpoint_instance_path for b in resolved_branches)
        count = len(abstractions)
        confidence = (CONFIDENCE_HIGH if count == 0 else
                      CONFIDENCE_MEDIUM if count == 1 else CONFIDENCE_LOW)
        out.append(Conclusion(
            subject=subject, attribute="endpoint",
            statement=f"{endpoints} ({trace.status})", confidence=confidence,
            evidence=base + path_refs,
            missing_evidence=[f"{a['abstraction']} at {a['where']}: {a['detail']}"
                              for a in abstractions]))
    elif trace.status == TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value:
        out.append(Conclusion(
            subject=subject, attribute="endpoint",
            statement="terminated at a protocol bridge; the real endpoint lies beyond "
                      "it and is a separate trace",
            confidence=CONFIDENCE_MEDIUM, evidence=base + [
                EvidenceRef("BRIDGE", f"{b.bridge_instance_path} "
                                      f"({b.upstream_protocol} -> "
                                      f"{b.downstream_protocol})")
                for b in trace.bridges or ()] or base,
            missing_evidence=["a trace of the bridge's downstream side"]))
    else:
        out.append(Conclusion(
            subject=subject, attribute="endpoint",
            statement=f"no endpoint established ({trace.status})",
            confidence=CONFIDENCE_UNKNOWN,
            missing_evidence=list(trace.missing_evidence)
            or [trace.reason or "the trace terminated without naming an endpoint"]))

    # -- 4. bind location ---------------------------------------------------
    candidate = trace.best_candidate
    validation = (row or {}).get("validation")
    bind = (row or {}).get("proposed_vip_bind_hierarchy")
    if candidate is None or bind in (None, "", REQUIRED_HUMAN_INPUT):
        out.append(Conclusion(
            subject=subject, attribute="bind_location",
            statement="no candidate VIP bind location was established",
            confidence=CONFIDENCE_UNKNOWN,
            missing_evidence=list(trace.missing_evidence)
            or ["an accessible AMBA boundary on this port's traced path"]))
    elif bind == MULTIPLE_BRANCH_PARENT_BIND:
        out.append(Conclusion(
            subject=subject, attribute="bind_location",
            statement="several candidate locations enumerated; AMBA-12/13 leave the "
                      "choice to a human",
            confidence=CONFIDENCE_MEDIUM, evidence=base,
            missing_evidence=["a human decision on which enumerated branch to observe"]))
    else:
        readiness = validation.readiness if validation is not None else None
        tier = candidate.bind_tier
        if tier == BindTier.T3_NAMING_HEURISTIC.value:
            confidence = CONFIDENCE_LOW
        elif tier == BindTier.T4_UNDECIDABLE.value:
            confidence = CONFIDENCE_UNKNOWN
        elif readiness == BIND_READINESS_READY:
            confidence = CONFIDENCE_HIGH
        elif readiness == BIND_READINESS_BLOCKED:
            confidence = CONFIDENCE_UNKNOWN
        else:
            confidence = CONFIDENCE_MEDIUM
        missing = ([f"AMBA-15 point unresolved: {p}" for p in validation.unknown_points]
                   + [f"AMBA-15 point DISPROVEN: {p}" for p in validation.failed_points]
                   ) if validation is not None else []
        out.append(Conclusion(
            subject=subject, attribute="bind_location",
            statement=f"{bind} [{candidate.priority}, {tier}]",
            confidence=confidence,
            evidence=(base + [EvidenceRef("RTL_INSTANCE", candidate.rationale)]
                      if confidence != CONFIDENCE_UNKNOWN else []),
            missing_evidence=missing or (["the AMBA-15 checklist for this location"]
                                         if confidence == CONFIDENCE_UNKNOWN else [])))
    return out


def build_conclusions(netlist, traces, matrix_rows=None) -> list:
    """AMBA-27 applied to every traced fabric port."""
    by_row = {r.get("row_id"): r for r in matrix_rows or ()}
    out: list = []
    for trace in traces or ():
        out.extend(classify_port_conclusions(netlist, trace,
                                             by_row.get(trace.interface_id)))
    return out


def conclusions_by_subject(conclusions) -> dict:
    out: dict = {}
    for c in conclusions or ():
        out.setdefault(c.subject, []).append(c)
    return out


_CONCLUSION_COLUMNS: tuple = (
    ("subject", "Subject"),
    ("attribute", "Attribute"),
    ("statement", "Conclusion"),
    ("confidence", "Confidence"),
    ("evidence", "Evidence"),
    ("missing_evidence", "Missing Evidence"),
)


def render_conclusions(conclusions) -> str:
    """Every conclusion with its evidence and its level, in one table."""
    rows = [{"subject": c.subject, "attribute": c.attribute,
             "statement": c.statement, "confidence": c.confidence,
             "evidence": " | ".join(e.render() for e in c.evidence) or "-",
             "missing_evidence": " | ".join(c.missing_evidence) or "-"}
            for c in conclusions or ()]
    return render_markdown_table(list(_CONCLUSION_COLUMNS), rows,
                                 empty_note="(no conclusion was reached)")


def render_confidence_legend() -> str:
    return render_markdown_table(
        [("confidence", "Confidence"), ("definition", "AMBA-27 definition")],
        [{"confidence": v, "definition": CONFIDENCE_DEFINITIONS[v]}
         for v in CONFIDENCE_VALUES])


# ===========================================================================
# AMBA-29: READINESS
#
# "Per port: READY / PARTIAL / BLOCKED / UNKNOWN. Overall AMBA verification
# readiness derives from per-port status."
#
# The four words are `amba_fabric_discovery`'s BIND_READINESS_* constants,
# imported rather than redeclared. What is new here is AMBA-29's own RULE:
# READY is defined over exactly five named attributes, and BLOCKED and UNKNOWN
# are two DIFFERENT failures the doc deliberately keeps apart --
#   BLOCKED  = we know what this port is; there is no usable endpoint or bind
#              location for it.
#   UNKNOWN  = we do not know what this port is; there is not enough evidence
#              to say anything.
# Collapsing them would send a reviewer to look for missing RTL when the real
# answer is "this port has nowhere a VIP can sit", or vice versa.
#
# NOTE the deliberate difference from AMBA-15/AMBA-18's readiness: that one is
# computed over THIRTEEN checks including every signal width. A port with an
# unprovable USER width is PARTIAL there and can still be READY here, because
# AMBA-29 names five attributes and a USER width is not one of them. The two
# are reported side by side rather than reconciled, and the one place they ARE
# coupled is enforced: an AMBA-15 DISPROVEN check makes the port BLOCKED here.
# ===========================================================================

#: AMBA-29's own attribute list, in the doc's own order. `(key, label)`.
#: "clock/reset" is ONE attribute in the doc's sentence and is kept as one.
AMBA29_REQUIRED_ATTRIBUTES: tuple = (
    ("protocol", "protocol"),
    ("role", "role"),
    ("endpoint", "endpoint"),
    ("bind_hierarchy", "bind hierarchy"),
    ("clock_reset", "clock/reset"),
)

#: The trace states in which an endpoint really was established.
_ENDPOINT_ESTABLISHED_STATUSES: frozenset = frozenset(
    _FOUND_STATUSES | _MULTIPLE_STATUSES
    | {TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value})

_UNRESOLVED_CELL_VALUES: frozenset = frozenset({
    "", REQUIRED_HUMAN_INPUT, BIND_CHECK_UNKNOWN_VALUE,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS, AMBA_PROTOCOL_UNRESOLVED,
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED, MULTIPLE_BRANCH_PARENT_BIND,
})


def _cell_resolved(value) -> bool:
    text = str(value or "").strip()
    return bool(text) and text not in _UNRESOLVED_CELL_VALUES


@dataclass
class ReadinessAttribute:
    """One of AMBA-29's five required attributes, answered for one port."""
    key: str
    label: str
    resolved: bool
    value: str
    evidence: str

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "resolved": self.resolved,
                "value": self.value, "evidence": self.evidence}


@dataclass
class PortReadiness:
    """AMBA-29's verdict for ONE fabric port, with the five attributes it rests
    on and the reason for anything other than READY."""
    port: str
    fabric_port: str
    protocol: str
    status: str
    reason: str
    attributes: list = field(default_factory=list)      # list[ReadinessAttribute]
    confidence: str = CONFIDENCE_UNKNOWN
    #: AMBA-15/AMBA-18's thirteen-point readiness for the same port, carried
    #: alongside rather than merged -- the two answer different questions.
    bind_location_readiness: Optional[str] = None

    @property
    def unresolved_attributes(self) -> list:
        return [a.label for a in self.attributes if not a.resolved]

    def to_dict(self) -> dict:
        return {"port": self.port, "fabric_port": self.fabric_port,
                "protocol": self.protocol, "status": self.status,
                "reason": self.reason, "confidence": self.confidence,
                "bind_location_readiness": self.bind_location_readiness,
                "attributes": [a.to_dict() for a in self.attributes],
                "unresolved_attributes": self.unresolved_attributes}


def _readiness_attributes(row: dict, trace=None) -> list:
    """The five attributes, read off the AMBA-16 matrix row that already
    carries them. Nothing is recomputed here: a readiness verdict that
    disagreed with the matrix a human read would be worse than no verdict."""
    protocol = row.get("protocol")
    role = row.get("fabric_role")
    endpoint = row.get("endpoint_instance_path")
    bind = row.get("proposed_vip_bind_hierarchy")
    clock, reset = row.get("clock"), row.get("reset")
    status = row.get("trace_status")
    endpoint_ok = _cell_resolved(endpoint) and status in _ENDPOINT_ESTABLISHED_STATUSES
    return [
        ReadinessAttribute("protocol", "protocol", _cell_resolved(protocol),
                           str(protocol or BIND_CHECK_UNKNOWN_VALUE),
                           "AMBA-4 signal-set classification of this bundle"),
        ReadinessAttribute("role", "role", _cell_resolved(role),
                           str(role or BIND_CHECK_UNKNOWN_VALUE),
                           "AMBA-5 fabric-side role from real port directions"),
        ReadinessAttribute("endpoint", "endpoint", endpoint_ok,
                           str(endpoint or ENDPOINT_HIERARCHY_NOT_ESTABLISHED),
                           f"AMBA-7..14 trace terminated {status}"),
        ReadinessAttribute("bind_hierarchy", "bind hierarchy", _cell_resolved(bind),
                           str(bind or REQUIRED_HUMAN_INPUT),
                           "AMBA-8 candidate location validated by AMBA-15"),
        ReadinessAttribute("clock_reset", "clock/reset",
                           _cell_resolved(clock) and _cell_resolved(reset),
                           f"{clock or BIND_CHECK_UNKNOWN_VALUE} / "
                           f"{reset or BIND_CHECK_UNKNOWN_VALUE}",
                           "AMBA-15 points 6-7 on the proposed bind location"),
    ]


def compute_port_readiness(row: dict, trace=None, conclusions=None) -> PortReadiness:
    """AMBA-29's four-state verdict for one fabric port.

    The rule, in the doc's own terms and in this order:

      * BLOCKED first when the AMBA-15 checklist DISPROVED something about the
        location (a hierarchy that does not exist is not a location a human can
        approve, and it must not average out to PARTIAL).
      * UNKNOWN when none of the five attributes resolved -- "insufficient
        evidence" to say anything at all.
      * BLOCKED when the port IS identified but has neither a usable endpoint
        nor a usable bind location: that is precisely "no usable endpoint/bind
        location", and it is a different problem from having no evidence.
      * READY when all five resolved.
      * PARTIAL otherwise -- "mostly resolved, one or more required attributes
        unresolved" -- and the unresolved ones are named.
    """
    attributes = _readiness_attributes(row, trace)
    by_key = {a.key: a for a in attributes}
    validation = row.get("validation")
    bind_readiness = validation.readiness if validation is not None else None
    port = row.get("row_id") or row.get("fabric_port") or ""
    conf = worst_confidence([c.confidence for c in conclusions or ()]) \
        if conclusions else CONFIDENCE_UNKNOWN

    def _mk(status: str, reason: str) -> PortReadiness:
        return PortReadiness(
            port=str(port), fabric_port=str(row.get("fabric_port") or port),
            protocol=str(row.get("protocol") or AMBA_PROTOCOL_UNRESOLVED),
            status=status, reason=reason, attributes=attributes, confidence=conf,
            bind_location_readiness=bind_readiness)

    if validation is not None and any(c.status == BIND_CHECK_FAILED
                                      for c in validation.checks):
        return _mk(BIND_READINESS_BLOCKED,
                   "the proposed bind location is DISPROVEN, not merely unproven: "
                   + "; ".join(validation.failed_points))

    resolved = [a for a in attributes if a.resolved]
    if not resolved:
        return _mk(BIND_READINESS_UNKNOWN,
                   "insufficient evidence: none of AMBA-29's five required attributes "
                   "could be established for this port")

    multiple = row.get("trace_status") in _MULTIPLE_STATUSES
    if (not multiple and not by_key["endpoint"].resolved
            and not by_key["bind_hierarchy"].resolved):
        return _mk(BIND_READINESS_BLOCKED,
                   "no usable endpoint and no usable bind location: the port is "
                   f"identified ({by_key['protocol'].value}) but nothing on its traced "
                   f"path can host a VIP -- {row.get('trace_status')}")

    unresolved = [a.label for a in attributes if not a.resolved]
    if not unresolved:
        return _mk(BIND_READINESS_READY,
                   "protocol, role, endpoint, bind hierarchy and clock/reset are all "
                   "established from real RTL evidence")
    note = (" (AMBA-12/13 enumerated several branches for this port and forbid "
            "choosing one, so the choice itself is the open item -- not an absent "
            "endpoint)" if multiple else "")
    return _mk(BIND_READINESS_PARTIAL,
               "mostly resolved; still unresolved: " + ", ".join(unresolved) + note)


def build_port_readiness(matrix_rows, traces=None, conclusions=None) -> list:
    """AMBA-29 for every fabric PORT.

    Parent rows only: a MULTIPLE_DESTINATION port is one port whose branches
    are enumerated, not several ports, and counting each branch would inflate
    every rollup below. AMBA-11 second-side rows are likewise evidence about a
    bridge, not fabric ports of their own."""
    by_subject = conclusions_by_subject(conclusions)
    by_interface = {t.interface_id: t for t in traces or ()}
    out: list = []
    for row in parent_matrix_rows(matrix_rows):
        if row.get("amba11_second_side"):
            continue
        subject = row.get("row_id")
        out.append(compute_port_readiness(row, by_interface.get(subject),
                                          by_subject.get(subject)))
    return out


def derive_overall_readiness(port_readiness) -> dict:
    """"Overall AMBA verification readiness derives from per-port status."

    Derived, never asserted: the overall value is the WORST per-port value,
    using `amba_fabric_discovery`'s own severity order, and the ports that
    produced it are named so the rollup is actionable rather than a mood. An
    empty port set is UNKNOWN, not READY -- a fabric nobody discovered ports
    on has not been proven ready for anything.

    The same `preflight.py` discipline it imitates: a worklist-driven status
    with the failing items attached, never a bare boolean."""
    ports = list(port_readiness or ())
    counts = {value: 0 for value in BIND_READINESS_VALUES}
    for pr in ports:
        counts[pr.status] = counts.get(pr.status, 0) + 1
    if not ports:
        return {"overall": BIND_READINESS_UNKNOWN, "counts": counts,
                "total_ports": 0, "ready_ports": 0, "governing_ports": [],
                "reason": "no fabric port was discovered, so no readiness can be derived"}
    overall = worst_readiness([pr.status for pr in ports])
    governing = [{"port": pr.port, "status": pr.status, "reason": pr.reason}
                 for pr in ports if pr.status == overall]
    return {
        "overall": overall, "counts": counts, "total_ports": len(ports),
        "ready_ports": counts.get(BIND_READINESS_READY, 0),
        "governing_ports": governing,
        "reason": f"the worst of {len(ports)} per-port status(es); "
                  f"{len(governing)} port(s) are at {overall}",
    }


def assert_readiness_respects_confidence(port_readiness) -> None:
    """The one place AMBA-27 and AMBA-29 are coupled, enforced.

    A READY port is a confirmed-topology claim. AMBA-27 forbids reporting
    LOW/UNKNOWN evidence as confirmed topology, so a port whose weakest
    conclusion is LOW or UNKNOWN may not be READY -- if it is, one of the two
    computations is wrong and the report must not be published either way."""
    offenders = [pr for pr in port_readiness or ()
                 if pr.status == BIND_READINESS_READY
                 and pr.confidence not in CONFIRMED_TOPOLOGY_CONFIDENCE]
    if offenders:
        raise DiscoveryReportError("AMBA29_READY_PORT_ON_LOW_OR_UNKNOWN_EVIDENCE", {
            "offending": [{"port": pr.port, "confidence": pr.confidence,
                           "reason": pr.reason} for pr in offenders],
            "hint": "AMBA-27: LOW/UNKNOWN must not be reported as confirmed topology, "
                    "and a READY port is a confirmed-topology claim",
        })


_READINESS_COLUMNS: tuple = (
    ("fabric_port", "Fabric Port"),
    ("protocol", "Protocol"),
    ("status", "Readiness"),
    ("confidence", "Confidence"),
    ("unresolved", "Unresolved Attributes"),
    ("bind_location_readiness", "AMBA-15 Location Readiness"),
    ("reason", "Reason"),
)


def render_port_readiness(port_readiness) -> str:
    rows = [{"fabric_port": pr.fabric_port, "protocol": pr.protocol,
             "status": pr.status, "confidence": pr.confidence,
             "unresolved": ", ".join(pr.unresolved_attributes) or "-",
             "bind_location_readiness": pr.bind_location_readiness or "-",
             "reason": pr.reason}
            for pr in port_readiness or ()]
    return render_markdown_table(list(_READINESS_COLUMNS), rows,
                                 empty_note="(no fabric port was discovered)")


def render_readiness_status(port_readiness) -> str:
    """AMBA-28 section 15: the per-port table, the tally, and the derived
    overall verdict."""
    overall = derive_overall_readiness(port_readiness)
    lines = [f"**OVERALL AMBA VERIFICATION READINESS: {overall['overall']}** "
             f"({overall['reason']})", "",
             render_markdown_table(
                 [("status", "Readiness"), ("ports", "Fabric Ports")],
                 [{"status": v, "ports": overall["counts"].get(v, 0)}
                  for v in BIND_READINESS_VALUES], aligns={"ports": "right"}),
             "", "### Per-port readiness (AMBA-29)", "",
             render_port_readiness(port_readiness)]
    if overall["governing_ports"]:
        lines += ["", "### Ports governing the overall status", ""]
        lines += [f"- {g['port']} [{g['status']}]: {g['reason']}"
                  for g in overall["governing_ports"]]
    return "\n".join(lines)


# ===========================================================================
# AMBA-26: L5 BRANCH MAPPING
#
# "Map topology into existing L5 naming ... Do not invent abstract branch
# names."
#
# EXISTING L5 naming, verified rather than assumed: the canonical form is
# `tools/verification_flow/branch_topology_gate.py`'s -- underscore separator,
# 0-indexed `branch_a0..`/`branch_b0..`, plus `block` and `branch_fw`. That
# gate's own header records it being canonicalised on 2026-08-28 after four
# incompatible conventions were found coexisting, and it declares itself "the
# single source of truth for the canonical form". The AMBA-26 section of the
# master prompt writes `branch-a1..N`; taking that spelling literally would
# reintroduce exactly the dash-separated, 1-indexed variant that gate was
# written to eliminate, and the resulting mapping would not be checkable by any
# validator in this repo. The doc's own instruction is to map into EXISTING L5
# naming, so the existing canonical spelling wins and this is recorded here
# rather than silently.
#
# The BRANCH UNIT is AMBA-26's, not the branch-mapper skill's placeholder:
#   branch_a{i} = one fabric-facing PHYSICAL INTERFACE (by actual port count)
#   branch_b{j} = one VIP ENDPOINT/SCENARIO branch (by discovered VIP count)
# The skill's 2026-09-01 placeholder instead used "one AMBA master agent" and
# "one AMBA slave agent". Those are a different axis: a fabric slave PORT and
# the master that initiates through it are two entities once AMBA-9/AMBA-10
# tracing exists, and the VIP count is not the slave count.
# ===========================================================================

L5_BRANCH_BLOCK = "block"
L5_BRANCH_FW = "branch_fw"


def l5_branch_a(index: int) -> str:
    """`branch_a{i}`, 0-indexed, per `branch_topology_gate.py`."""
    return f"branch_a{int(index)}"


def l5_branch_b(index: int) -> str:
    return f"branch_b{int(index)}"


#: Port-name tokens that suggest a fabric raises interrupts/events. This is a
#: NAMING heuristic and is tiered as one -- it can only ever make `branch_fw`
#: a question for a human, never an established fact.
INTERRUPT_PORT_TOKENS: tuple = ("IRQ", "INTR", "INTERRUPT", "EVENT", "ERR_INT",
                                "FAULT", "ALERT")

BRANCH_FW_APPLICABLE = "APPLICABLE_INTERRUPT_EVIDENCE_FOUND"
BRANCH_FW_NOT_APPLICABLE = "NOT_APPLICABLE_NO_INTERRUPT_OR_EVENT_PORT_FOUND"

_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def _interrupt_ports(instance) -> list:
    """Ports on the fabric instance whose NAME suggests an interrupt/event."""
    if instance is None:
        return []
    hits: list = []
    for port in instance.port_names or ():
        tokens = {t for t in _TOKEN_SPLIT.split(str(port).upper()) if t}
        upper = str(port).upper()
        if "INT" in tokens or any(tok in upper for tok in INTERRUPT_PORT_TOKENS):
            hits.append(port)
    return sorted(hits)


@dataclass
class L5BranchMapping:
    """AMBA-26's projection of a discovered fabric onto existing L5 naming."""
    fabric_instance_path: str
    branch_a: list = field(default_factory=list)   # one per fabric-facing interface
    branch_b: list = field(default_factory=list)   # one per discovered VIP
    branch_fw: dict = field(default_factory=dict)
    protocol: str = AMBA_PROTOCOL_UNRESOLVED
    cross_branch_bus_model: dict = field(default_factory=dict)

    @property
    def dut_port_count(self) -> int:
        return len(self.branch_a)

    @property
    def vip_port_count(self) -> int:
        return len(self.branch_b)

    @property
    def branch_names(self) -> list:
        return ([L5_BRANCH_BLOCK, L5_BRANCH_FW]
                + [e["branch"] for e in self.branch_a]
                + [e["branch"] for e in self.branch_b])

    def to_branch_topology(self) -> dict:
        """The document `tools/verification_flow/branch_topology_gate.py`
        validates, in exactly that gate's shape.

        `branch_fw_interrupt_driven` reflects real evidence and is False when
        none was found: the gate then FAILS, which is the correct and honest
        outcome for a fabric whose interrupt contract nobody has established.
        `branch_topology_gate_blockers()` says so in words."""
        return {
            "dut_port_count": self.dut_port_count,
            "vip_port_count": self.vip_port_count,
            "branches": list(self.branch_names),
            "branch_fw_interrupt_driven": bool(
                self.branch_fw.get("interrupt_driven")),
            "protocol": self.protocol,
            "cross_branch_bus_model": dict(self.cross_branch_bus_model),
        }

    def to_dict(self) -> dict:
        return {"fabric_instance_path": self.fabric_instance_path,
                "branch_a": [dict(e) for e in self.branch_a],
                "branch_b": [dict(e) for e in self.branch_b],
                "branch_fw": dict(self.branch_fw),
                "branch_topology": self.to_branch_topology()}


def build_l5_branch_mapping(netlist, matrix_rows, vip_plan, *,
                            fabric_instance_path: str = "",
                            scaling_plan=None, port_readiness=None) -> L5BranchMapping:
    """AMBA-26 from artifacts AMBA-16/AMBA-20/AMBA-25 already produced.

    `branch_a` is one entry per PARENT matrix row -- i.e. per fabric-facing
    physical interface, by actual port count. Child branch rows of a
    multiple-source port are not extra interfaces, and an AMBA-11 second-side
    row is a record about a bridge, not a fabric port.

    `branch_b` is one entry per row of the AMBA-20 VIP instance plan -- by
    discovered VIP count, which is NOT the slave count and NOT the branch_a
    count (a port with no validated location plans no VIP, and a bridge can
    add one).
    """
    readiness_by_port = {pr.port: pr for pr in port_readiness or ()}
    branch_a: list = []
    for row in parent_matrix_rows(matrix_rows):
        if row.get("amba11_second_side"):
            continue
        pr = readiness_by_port.get(row.get("row_id"))
        branch_a.append({
            "branch": l5_branch_a(len(branch_a)),
            "fabric_port": row.get("fabric_port"),
            "port_row_id": row.get("row_id"),
            "protocol": row.get("protocol"),
            "fabric_role": row.get("fabric_role"),
            "endpoint": row.get("endpoint_instance_path")
            or ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
            "readiness": pr.status if pr else row.get("status"),
            "confidence": pr.confidence if pr else REQUIRED_HUMAN_INPUT,
        })

    branch_b: list = []
    for vip in vip_plan or ():
        branch_b.append({
            "branch": l5_branch_b(len(branch_b)),
            "vip_id": vip.get("vip_id"),
            "protocol": vip.get("protocol"),
            "vip_mode": vip.get("vip_mode"),
            "bind_hierarchy": vip.get("bind_hierarchy"),
            "endpoint": vip.get("endpoint"),
            "source_branch_a": next(
                (a["branch"] for a in branch_a
                 if a["port_row_id"] == vip.get("source_row_id")),
                REQUIRED_HUMAN_INPUT),
        })

    path = fabric_instance_path or (
        matrix_rows[0].get("fabric_port", "").split(":")[0] if matrix_rows else "")
    instance = netlist.instance(parse_instance_path(path)) if netlist is not None else None
    irq_ports = _interrupt_ports(instance)
    tier = classify_bind_tier(naming_match=irq_ports[0]) if irq_ports else None
    branch_fw = {
        "branch": L5_BRANCH_FW,
        "applicability": BRANCH_FW_APPLICABLE if irq_ports else BRANCH_FW_NOT_APPLICABLE,
        "interrupt_driven": bool(irq_ports),
        "interrupt_ports": irq_ports,
        "evidence_tier": tier.tier.value if tier else BindTier.T4_UNDECIDABLE.value,
        "confidence": CONFIDENCE_LOW if irq_ports else CONFIDENCE_UNKNOWN,
        "requires_human_confirmation": True,
        "rationale": (
            "port names on the fabric instance suggest interrupt/event behaviour: "
            + ", ".join(irq_ports)
            + ". Naming heuristic only -- a human must confirm the interrupt contract "
              "before branch_fw is treated as established."
            if irq_ports else
            "no interrupt/event-shaped port was found on the fabric instance, so "
            "AMBA-26's 'when applicable' does not apply from RTL evidence alone. "
            "branch_fw is still named (existing L5 topology always carries it) but "
            "its interrupt contract is REQUIRED_HUMAN_INPUT."),
    }

    protocols = sorted({str(e.get("protocol")) for e in branch_a
                        if _cell_resolved(e.get("protocol"))})
    protocol = "AMBA4:" + ",".join(protocols) if protocols else AMBA_PROTOCOL_UNRESOLVED

    # AMBA-25 already decided which master pairs have a REAL dependency and
    # which are explicitly NO_INTERLOCK. Only the required ones are shared
    # resources; copying the whole list would report every unordered pair as
    # contended, which is the exact claim AMBA-25's refusal-by-default exists
    # to prevent.
    shared = [{"master_a": lock.get("master_a"), "master_b": lock.get("master_b"),
               "dependency": lock.get("dependency"),
               "shared_resources": list(lock.get("shared_resources") or ()),
               "rationale": lock.get("rationale")}
              for lock in (getattr(scaling_plan, "interlocks", None) or ())
              if lock.get("dependency")]
    cross = {
        "shared_resources": shared,
        # Round-robin vs priority vs QoS is not derivable from a port list or a
        # scoreboard matrix; it lives in arbiter RTL nobody has read yet.
        "arbitration_policy": REQUIRED_HUMAN_INPUT,
        "arbitration_policy_source": "AMBA-25 identified the shared resources; the "
                                     "POLICY must be read off the fabric's arbiter RTL "
                                     "or configuration and cannot be inferred here",
    }
    return L5BranchMapping(fabric_instance_path=path, branch_a=branch_a,
                           branch_b=branch_b, branch_fw=branch_fw,
                           protocol=protocol, cross_branch_bus_model=cross)


def branch_topology_gate_blockers(mapping: L5BranchMapping) -> list:
    """What a human must supply before `branch_topology_gate.py` would PASS
    this mapping.

    Computed against that gate's real rules rather than guessed, and returned
    as a list rather than raised: an AMBA-26 mapping with open questions is the
    normal, expected output of a discovery pass, and AMBA-30's whole point is
    that a human resolves them."""
    doc = mapping.to_branch_topology()
    blockers: list = []
    if not doc["branch_fw_interrupt_driven"]:
        blockers.append({
            "field": "branch_fw_interrupt_driven",
            "gate_reason": "BRANCH_FW_NOT_INTERRUPT_DRIVEN",
            "detail": mapping.branch_fw.get("rationale", ""),
        })
    amba = "amba" in str(doc.get("protocol") or "").lower()
    if doc["dut_port_count"] > 1 and amba:
        model = doc.get("cross_branch_bus_model") or {}
        if not model.get("shared_resources"):
            blockers.append({
                "field": "cross_branch_bus_model.shared_resources",
                "gate_reason": "MULTI_BRANCH_BUS_ARBITRATION_UNMODELED",
                "detail": "no shared fabric resource was identified; supply the AMBA-25 "
                          "scaling plan, or confirm the branches really are uncontended",
            })
        if model.get("arbitration_policy") in (None, "", REQUIRED_HUMAN_INPUT):
            blockers.append({
                "field": "cross_branch_bus_model.arbitration_policy",
                "gate_reason": "MULTI_BRANCH_BUS_ARBITRATION_UNMODELED",
                "detail": model.get("arbitration_policy_source", ""),
            })
    if not doc["dut_port_count"]:
        blockers.append({
            "field": "dut_port_count", "gate_reason": "MISSING_REQUIRED_BRANCHES",
            "detail": "no fabric-facing physical interface was discovered, so there is "
                      "no branch_a* to map",
        })
    return blockers


_BRANCH_A_COLUMNS: tuple = (
    ("branch", "L5 Branch"), ("fabric_port", "Fabric Port"),
    ("protocol", "Protocol"), ("fabric_role", "Fabric Role"),
    ("endpoint", "Endpoint"), ("readiness", "Readiness"),
    ("confidence", "Confidence"),
)

_BRANCH_B_COLUMNS: tuple = (
    ("branch", "L5 Branch"), ("vip_id", "VIP_ID"), ("protocol", "Protocol"),
    ("vip_mode", "VIP Mode"), ("bind_hierarchy", "Proposed Bind Hierarchy"),
    ("endpoint", "Endpoint"), ("source_branch_a", "Serves"),
)


def render_l5_branch_mapping_report(mapping: L5BranchMapping) -> str:
    """AMBA-26's mapping as a standalone review artifact.

    Deliberately NOT one of AMBA-28's seventeen sections: AMBA-28 says "produce
    exactly" that list, and quietly adding an eighteenth item to a mandated
    sequence is how a mandated sequence stops meaning anything. This is a
    separate document the same review covers."""
    doc = mapping.to_branch_topology()
    blockers = branch_topology_gate_blockers(mapping)
    lines = [
        "# AMBA-26 L5 Branch Mapping", "",
        f"Fabric instance: `{mapping.fabric_instance_path or '(unknown)'}`", "",
        f"`branch_a*` = fabric-facing physical interfaces (**{doc['dut_port_count']}** "
        f"by actual port count). `branch_b*` = VIP endpoint/scenario branches "
        f"(**{doc['vip_port_count']}** by discovered VIP count). Naming is "
        "`branch_topology_gate.py`'s canonical underscore, 0-indexed form.", "",
        "## branch_a* -- fabric-facing physical interfaces", "",
        render_markdown_table(list(_BRANCH_A_COLUMNS), mapping.branch_a,
                              empty_note="(no fabric-facing interface was discovered)"),
        "", "## branch_b* -- VIP endpoint/scenario branches", "",
        render_markdown_table(list(_BRANCH_B_COLUMNS), mapping.branch_b,
                              empty_note="(no VIP instance is proposed, so no "
                                         "branch_b* exists)"),
        "", "## branch_fw -- firmware/interrupt-triggered behaviour", "",
        f"- applicability: **{mapping.branch_fw.get('applicability')}**",
        f"- interrupt-driven: {mapping.branch_fw.get('interrupt_driven')}",
        f"- evidence tier: {mapping.branch_fw.get('evidence_tier')} "
        f"(confidence {mapping.branch_fw.get('confidence')})",
        f"- {mapping.branch_fw.get('rationale')}", "",
        "## Existing-gate readiness", "",
        f"`branch_topology_gate.py` document: {doc['branches']}", "",
    ]
    if blockers:
        lines += ["This mapping does NOT yet pass the existing branch-topology gate. "
                  "Open items:", ""]
        lines += [f"- `{b['field']}` ({b['gate_reason']}): {b['detail']}"
                  for b in blockers]
    else:
        lines.append("This mapping satisfies `branch_topology_gate.py`'s rules.")
    lines += ["",
              "Discovery and planning only (AMBA-30 / AMBA-31). No branch task, "
              "pattern or bind statement is generated from this mapping until a human "
              "approves the discovery report it belongs to."]
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    return text


# ===========================================================================
# AMBA-28: DISCOVERY REPORT ORDER
#
# "Produce exactly:" seventeen numbered items, in that order. Enforced two
# ways: the section list is a tuple that the assembler iterates (a section
# cannot be skipped, reordered or renamed by editing one call site), and
# `assert_report_section_order()` re-reads the finished text and checks the
# seventeen headings really appear once each, in order.
#
# A section whose input was not supplied renders a visible NOT-SUPPLIED note
# naming what to supply. It is never omitted: "this analysis was not run" and
# "this analysis found nothing" must not look alike, the same property
# AMBA-17's mandatory-even-when-empty table already has.
# ===========================================================================

AMBA28_SECTIONS: tuple = (
    (1, "INPUT RESOLUTION"),
    (2, "BUS FABRIC INSTANCE"),
    (3, "PORT ENUMERATION"),
    (4, "PROTOCOL CLASSIFICATION"),
    (5, "MASTER / SLAVE COUNTS"),
    (6, "PER-PORT RTL TRACE"),
    (7, "FABRIC PORT -> VIP BIND MATRIX"),
    (8, "UNRESOLVED PORTS"),
    (9, "TOPOLOGY TREE"),
    (10, "CLOCK / RESET MATRIX"),
    (11, "VIP INSTANCE PLAN"),
    (12, "SCOREBOARD REFERENCE ENVIRONMENT ANALYSIS"),
    (13, "SCOREBOARD CONNECTION PLAN"),
    (14, "AMBA_PORT_REGISTRY DRAFT"),
    (15, "READINESS STATUS"),
    (16, "OPEN QUESTIONS / MISSING EVIDENCE"),
    (17, "USER REVIEW GATE"),
)

#: AMBA-30's gate text, verbatim and in the doc's own order. Section 17 IS this.
AMBA30_REVIEW_GATE_LINES: tuple = (
    "AMBA FABRIC DISCOVERY COMPLETE",
    "FABRIC PORT CLASSIFICATION COMPLETE",
    "ENDPOINT TRACE COMPLETE",
    "VIP BIND PLAN COMPLETE",
    "SCOREBOARD MAPPING COMPLETE",
    "UVM IMPLEMENTATION NOT STARTED",
    "AWAITING USER REVIEW",
)


def _not_supplied(what: str, how: str) -> str:
    return (f"**NOT SUPPLIED.** {what} was not provided to this report.\n\n"
            f"To fill this section: {how}")


@dataclass
class DiscoveryInputs:
    """AMBA-28 section 1: what the discovery pass was actually given.

    Recorded rather than assumed, because every conclusion below rests on it --
    a port that "does not exist" because its RTL was never in the parse set is
    a different fact from one that does not exist."""
    top_module: str = ""
    fabric_instance_path: str = ""
    rtl_sources: list = field(default_factory=list)
    filelists: list = field(default_factory=list)
    address_map_sources: list = field(default_factory=list)
    scoreboard_env_roots: list = field(default_factory=list)
    defines: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"top_module": self.top_module,
                "fabric_instance_path": self.fabric_instance_path,
                "rtl_sources": list(self.rtl_sources),
                "filelists": list(self.filelists),
                "address_map_sources": list(self.address_map_sources),
                "scoreboard_env_roots": list(self.scoreboard_env_roots),
                "defines": list(self.defines), "notes": list(self.notes)}

    def render(self) -> str:
        def _rows(label, values, kind):
            return [{"input": label, "value": str(v), "evidence_kind": kind}
                    for v in values] or [
                {"input": label, "value": "(none supplied)", "evidence_kind": kind}]
        rows = ([{"input": "top module", "value": self.top_module or REQUIRED_HUMAN_INPUT,
                  "evidence_kind": "RTL_INSTANCE"},
                 {"input": "fabric instance",
                  "value": self.fabric_instance_path or REQUIRED_HUMAN_INPUT,
                  "evidence_kind": "RTL_INSTANCE"}]
                + _rows("RTL source", self.rtl_sources, "RTL_INSTANCE")
                + _rows("filelist", self.filelists, "FILELIST")
                + _rows("define", self.defines, "DEFINE")
                + _rows("address-map source", self.address_map_sources,
                        "ADDRESS_MAP_SUPPORT")
                + _rows("scoreboard env root", self.scoreboard_env_roots, "CONFIG"))
        out = [render_markdown_table(
            [("input", "Input"), ("value", "Resolved To"),
             ("evidence_kind", "AMBA-27 Evidence Kind")], rows)]
        if self.notes:
            out += [""] + [f"- {n}" for n in self.notes]
        return "\n".join(out)


def _render_port_enumeration(netlist, fabric_path: str) -> str:
    """AMBA-28 section 3, from `bundles_of()` -- every AMBA bundle on the
    fabric boundary including a partial one, which AMBA-3 forbids omitting."""
    if netlist is None:
        return _not_supplied("An elaborated netlist",
                             "pass the `FabricNetlist` built by "
                             "`amba_fabric_discovery.build_fabric_netlist()`")
    path = parse_instance_path(fabric_path)
    bundles = afd.bundles_of(netlist, path)
    rows = [{"bundle": b.prefix or "(unprefixed)", "interface_id": b.interface_id,
             "signals": len(b.ports),
             "ports": ", ".join(sorted(b.ports)[:8])
                      + (" ..." if len(b.ports) > 8 else "")}
            for b in bundles]
    instance = netlist.instance(path)
    total = len(instance.port_names) if instance else 0
    return "\n".join([
        f"{len(bundles)} AMBA bundle(s) enumerated on `{fabric_path}` "
        f"out of {total} declared port(s).", "",
        render_markdown_table(
            [("bundle", "Bundle Prefix"), ("interface_id", "Interface ID"),
             ("signals", "Signals"), ("ports", "Ports")], rows,
            aligns={"signals": "right"},
            empty_note="(no AMBA bundle was enumerated on this instance)")])


def _render_protocol_classification(netlist, fabric_path: str) -> str:
    """AMBA-28 section 4: each bundle's AMBA-4 verdict, its discriminators, and
    what is missing when it did not resolve."""
    if netlist is None:
        return _not_supplied("An elaborated netlist",
                             "pass the `FabricNetlist` this report is about")
    rows = []
    for b in afd.bundles_of(netlist, parse_instance_path(fabric_path)):
        cls = b.classification
        rows.append({
            "interface_id": b.interface_id, "protocol": b.display_name,
            "status": cls.status,
            "discriminators": "; ".join(cls.discriminators) or "-",
            "candidates": ", ".join(cls.candidates) or "-",
            "missing": ", ".join(cls.missing_signals) or "-",
        })
    return render_markdown_table(
        [("interface_id", "Interface ID"), ("protocol", "Protocol"),
         ("status", "Classification Status"), ("discriminators", "Discriminators"),
         ("candidates", "Candidates"), ("missing", "Missing Signals")], rows,
        empty_note="(no AMBA bundle was classified on this instance)")


def _render_fabric_instance(netlist, fabric_path: str) -> str:
    """AMBA-28 section 2."""
    if netlist is None:
        return _not_supplied("An elaborated netlist",
                             "pass the `FabricNetlist` this report is about")
    path = parse_instance_path(fabric_path)
    instance = netlist.instance(path)
    if instance is None:
        return (f"**`{fabric_path}` is NOT an elaborated instance of top module "
                f"`{netlist.top_module}`.** Every conclusion below would rest on a "
                "hierarchy that does not exist, so none is drawn.")
    rows = [{"property": "instance path", "value": instance.path_str},
            {"property": "module", "value": instance.module_name},
            {"property": "top module", "value": netlist.top_module},
            {"property": "in parsed source set",
             "value": "no (BLACK BOX)" if instance.is_blackbox else "yes"},
            {"property": "declared ports", "value": str(len(instance.port_names))},
            {"property": "declared parameters", "value": str(len(instance.parameters))},
            {"property": "child instances",
             "value": str(len(netlist.descendants_of(path)))}]
    return render_markdown_table([("property", "Property"), ("value", "Value")], rows)


def _render_open_questions(traces, plan, port_readiness, conclusions,
                           branch_mapping=None) -> str:
    """AMBA-28 section 16: everything still open, from every source, in one
    place -- unresolved traces, LOW/UNKNOWN conclusions, non-READY ports and
    the AMBA-26 gate blockers."""
    rows: list = []
    for trace in traces or ():
        for missing in trace.missing_evidence or ():
            rows.append({"source": "AMBA-14 trace", "subject": trace.interface_id,
                         "question": missing, "severity": trace.status})
    for c in conclusions or ():
        if c.confirmable:
            continue
        for missing in c.missing_evidence or ["(no missing evidence recorded)"]:
            rows.append({"source": f"AMBA-27 {c.attribute}", "subject": c.subject,
                         "question": missing, "severity": c.confidence})
    for pr in port_readiness or ():
        if pr.status == BIND_READINESS_READY:
            continue
        rows.append({"source": "AMBA-29 readiness", "subject": pr.fabric_port,
                     "question": pr.reason, "severity": pr.status})
    for blocker in (branch_topology_gate_blockers(branch_mapping)
                    if branch_mapping is not None else ()):
        rows.append({"source": "AMBA-26 branch mapping",
                     "subject": blocker["field"], "question": blocker["detail"],
                     "severity": blocker["gate_reason"]})
    return "\n".join([
        f"{len(rows)} open item(s). Every one must be answered by a human or by more "
        "evidence before AMBA-31 implementation may begin.", "",
        render_markdown_table(
            [("source", "Source"), ("subject", "Subject"), ("severity", "Severity"),
             ("question", "Open Question / Missing Evidence")], rows,
            empty_note="(nothing is open: every conclusion is evidenced and every port "
                       "is READY)")])


def _render_review_gate(port_readiness) -> str:
    """AMBA-28 section 17 / AMBA-30's gate, verbatim, plus the one thing the
    gate text does not itself say: what the discovery actually concluded."""
    overall = derive_overall_readiness(port_readiness)
    return "\n".join(
        ["```"] + list(AMBA30_REVIEW_GATE_LINES) + ["```", "",
         f"Overall AMBA verification readiness: **{overall['overall']}** "
         f"({overall['ready_ports']}/{overall['total_ports']} port(s) READY).", "",
         "No production UVM has been generated or modified. No bind statement is "
         "proposed, emitted or implied anywhere in this report. Per AMBA-31, "
         "AMBA_PORT_REGISTRY -> VIP configuration -> VIP instances -> virtual "
         "interfaces -> bind/connect -> UVM config_db -> monitors -> adapters -> "
         "scoreboard connections -> build -> verify -> run(WAVE=1) -> fsdbreport "
         "begins ONLY after a human explicitly approves this report."])


@dataclass
class AmbaDiscoveryReport:
    """The seventeen sections, in AMBA-28's order, each already rendered."""
    sections: list = field(default_factory=list)   # list[(number, title, body)]

    @property
    def titles(self) -> list:
        return [t for _, t, _ in self.sections]

    def section(self, number: int) -> str:
        for num, _, body in self.sections:
            if num == number:
                return body
        raise DiscoveryReportError("AMBA28_SECTION_NOT_PRESENT", {
            "number": number, "present": [n for n, _, _ in self.sections]})

    def to_dict(self) -> dict:
        return {"sections": [{"number": n, "title": t, "body": b}
                             for n, t, b in self.sections]}


def build_discovery_report(netlist, traces, plan, registry, *,
                           inputs: Optional[DiscoveryInputs] = None,
                           conclusions=None, port_readiness=None,
                           domain_analyses=None, scoreboard_env=None,
                           ingress_mapping=None, scaling_plan=None,
                           branch_mapping=None) -> AmbaDiscoveryReport:
    """AMBA-28's seventeen sections, assembled from artifacts other modules
    already computed.

    Nothing is recomputed here except the sections that have no renderer
    anywhere else (1, 2, 3, 4, 16, 17); items 5-15 are the existing AMBA-6,
    AMBA-7..14, AMBA-16..20, AMBA-22, AMBA-24 and AMBA-25 renderers called in
    the mandated order. That is the whole point of the requirement: a fixed
    sequence over artifacts a human has already been told how to read.

    `plan` is an `amba_fabric_discovery.VipBindPlan`. Optional arguments cover
    the analyses a caller may not have run; each renders a visible NOT SUPPLIED
    note rather than vanishing."""
    inputs = inputs or DiscoveryInputs()
    fabric_path = inputs.fabric_instance_path or (
        traces[0].fabric_instance_path if traces else "")
    conclusions = (conclusions if conclusions is not None
                   else build_conclusions(netlist, traces, plan.matrix))
    port_readiness = (port_readiness if port_readiness is not None
                      else build_port_readiness(plan.matrix, traces, conclusions))

    bodies = {
        1: inputs.render(),
        2: _render_fabric_instance(netlist, fabric_path),
        3: _render_port_enumeration(netlist, fabric_path),
        4: _render_protocol_classification(netlist, fabric_path),
        5: render_amba_topology_summary(plan.summary),
        6: afd.render_endpoint_trace_report(traces),
        7: render_fabric_vip_bind_matrix(plan.matrix),
        8: render_unresolved_fabric_port_table(plan.unresolved),
        9: "```\n" + plan.tree + "\n```",
        10: (afd_domain_report(domain_analyses) if domain_analyses is not None
             else _not_supplied(
                 "AMBA-24's clock/reset domain analysis",
                 "run `amba_fabric_analysis.analyze_all_bind_point_domains()` over "
                 "this matrix and pass its result as `domain_analyses`")),
        11: render_vip_instance_plan(plan.vip_instances),
        12: (render_scoreboard_env_report(scoreboard_env, ingress_mapping)
             if scoreboard_env is not None or ingress_mapping is not None
             else _not_supplied(
                 "AMBA-21's reference scoreboard environment analysis",
                 "run `amba_scoreboard_env.analyze_scoreboard_environment()` over the "
                 "reference environment and pass it as `scoreboard_env`")),
        13: (afd_scaling_report(scaling_plan) if scaling_plan is not None
             else _not_supplied(
                 "AMBA-25's registry-driven per-port scoreboard/scaling plan",
                 "run `amba_fabric_analysis.build_fabric_scaling_plan()` over the "
                 "AMBA-22 registry and pass it as `scaling_plan`")),
        14: render_amba_port_registry(registry),
        15: render_readiness_status(port_readiness),
        16: _render_open_questions(traces, plan, port_readiness, conclusions,
                                   branch_mapping),
        17: _render_review_gate(port_readiness),
    }
    return AmbaDiscoveryReport(
        sections=[(num, title, bodies[num]) for num, title in AMBA28_SECTIONS])


def afd_domain_report(domain_analyses) -> str:
    """Imported lazily: `amba_fabric_analysis` imports nothing from here, and
    keeping the dependency one-way at module scope means neither module can
    become unimportable because of the other."""
    from dv_harness.amba_fabric_analysis import render_clock_reset_domain_report
    return render_clock_reset_domain_report(domain_analyses)


def afd_scaling_report(scaling_plan) -> str:
    from dv_harness.amba_fabric_analysis import render_fabric_scaling_report
    return render_fabric_scaling_report(scaling_plan)


def _heading(number: int, title: str) -> str:
    return f"## {number}. {title}"


def render_discovery_report(report: AmbaDiscoveryReport, *,
                            title: str = "AMBA4 SoC Bus Fabric Discovery Report") -> str:
    """The whole report, in AMBA-28's exact order, self-checked.

    Two self-checks before it is returned: the seventeen headings really are
    present, once each, in order (`assert_report_section_order()`), and the
    text contains no bind statement (`assert_no_bind_statement()`)."""
    lines = [f"# {title}", "",
             "AMBA-28 mandates this exact seventeen-item order. Every section is "
             "present; one whose input was not supplied says so rather than being "
             "omitted.", "",
             "### AMBA-27 confidence legend", "", render_confidence_legend(), ""]
    for number, sec_title, body in report.sections:
        lines += [_heading(number, sec_title), "", body, ""]
    text = "\n".join(lines)
    assert_report_section_order(text)
    assert_no_bind_statement(text)
    return text


def assert_report_section_order(text: str) -> None:
    """AMBA-28's "produce exactly" this order, verified against the FINISHED
    text rather than against the list that produced it.

    Checking the source tuple would only prove the tuple agrees with itself. A
    heading that a section body accidentally swallowed, duplicated or emitted
    out of order is a real failure mode this catches and that one would not."""
    body = str(text or "")
    positions: list = []
    for number, title in AMBA28_SECTIONS:
        heading = _heading(number, title)
        count = body.count("\n" + heading + "\n") + (
            1 if body.startswith(heading + "\n") else 0)
        if count == 0:
            raise DiscoveryReportError("AMBA28_SECTION_MISSING", {
                "number": number, "title": title, "expected_heading": heading,
                "hint": "AMBA-28 mandates all seventeen sections; a section with no "
                        "input must render a NOT SUPPLIED note, never be omitted",
            })
        if count > 1:
            raise DiscoveryReportError("AMBA28_SECTION_DUPLICATED", {
                "number": number, "title": title, "occurrences": count})
        positions.append((number, body.index("\n" + heading + "\n")
                          if not body.startswith(heading + "\n") else 0))
    ordered = [n for n, _ in sorted(positions, key=lambda p: p[1])]
    expected = [n for n, _ in AMBA28_SECTIONS]
    if ordered != expected:
        raise DiscoveryReportError("AMBA28_SECTIONS_OUT_OF_ORDER", {
            "found_order": ordered, "required_order": expected,
            "hint": "AMBA-28 says 'produce exactly' this sequence; a reader who has "
                    "been told the order relies on it to know a section is missing",
        })
