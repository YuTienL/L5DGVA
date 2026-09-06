"""dv_harness/verification_architecture.py -- typed Intermediate Representations
(IRs) for the "which VIP/checker/scoreboard/assertion is placed WHERE, and does
that placement make structural sense" question, plus the comparators that
answer it.

WHY THIS EXISTS
---------------
Every piece of real evidence this module needs already has a producer:
`env_manifest.py` captures which VIP is configured and which release is
installed; `connectivity.py` classifies bind confidence (T1-T4) and already
has planning-entry generators for protocol checks and data-integrity
scoreboards; `phy_boundary.py` decides at which layer a bind may legally
mount. What did NOT exist anywhere in this repo is a single typed record
that ties a placement decision (VIP bind / checker / scoreboard / assertion)
back to that evidence with an honest confidence and status, and a
comparator that walks a whole subsystem's worth of those records looking for
a placement that contradicts the evidence it was built from -- a VIP bound
behind a bridge, a checker mounted on the wrong side of one, an assertion
declared against a clock domain the DUT does not have, a scoreboard
comparing two endpoints a real boundary classification says are not
comparable, two VIPs claiming the same instance, or the same real-behaviour
check quietly duplicated across a VIP checker/SVA/scoreboard.

REUSE, NOT REINVENTION
-----------------------
- Confidence vocabulary: `inference.CONFIDENCE_LEVELS` (HIGH/MEDIUM/LOW),
  plus one honest fourth value, UNKNOWN, for "no evidence to grade" --
  never a second confidence vocabulary. See
  `test_confidence_vocabulary_separation.py`'s standing rule: this module
  adds no fifth mechanism, it reuses the one score_confidence()/
  classify_bind_tier() already established the boundaries of.
- Bind-tier evidence: `connectivity.BindTier` / `classify_bind_tier()` /
  `AUTO_EMITTABLE_TIERS` / `BIND_TIER_UNCLASSIFIED` -- this module classifies
  no bind confidence of its own; it reads the tier a caller already computed
  (or the honest UNCLASSIFIED sentinel) and grades IR confidence from it.
- Bind-entry / protocol-check / scoreboard shapes:
  `connectivity.generate_protocol_check_entry()` /
  `generate_scoreboard_entry()` / `SCOREBOARD_PLAN_FIELDS` /
  `unfilled_plan_fields()` / `REQUIRED_HUMAN_INPUT`. Every IR here EXTENDS
  one of those existing shapes (or, for VipBindIR, the existing
  target_instance/ports/reason bind-entry shape `enforce_bind_tier_policy()`
  already validates) by carrying the original dict as `raw` and adding typed
  placement fields on top -- never a competing, differently-spelled record.
- Boundary decision: `phy_boundary.classify_boundary()` /
  `decide_bind_location()`. This module derives no serial/parallel/MIXED
  verdict of its own; it reads one already computed and reasons about what
  a MIXED boundary means for a hierarchy CHAIN (see
  `classify_wrapper_bridge_hop()` below), which `phy_boundary.py` does not
  attempt (it classifies one PHY<->controller pair, not a multi-hop chain).
- Table rendering: `connectivity.render_markdown_table()`, the repo's one
  parameterized markdown-table renderer -- no second one is added here.

DUCK-TYPED INPUTS, NOT A HARD IMPORT OF A CONCURRENTLY-BUILT MODULE
--------------------------------------------------------------------
Per this task's file-safety scope, this module imports ONLY
`inference.py`, `connectivity.py` and `phy_boundary.py` -- all three stable,
pre-existing modules outside both the 23-agent batch this task is part of
and the separately-running 12-agent batch. Several real facts a fuller
pipeline would supply (which hierarchy hops sit between a DUT top and a
bind target, which checker mounts on which side of a bridge, which VIP
instance is ACTIVE vs PASSIVE) are accepted here as plain caller-supplied
dicts/lists rather than pulled from another new module's output, so this
module is independently testable today. Where a richer producer would
plug in, the parameter docstring says so by name (e.g. a future
`subsystem_contract.py` hierarchy walk could supply `chain_by_target`
directly instead of a hand-built hop list) -- but no import statement for
any such module exists here.

NEVER FABRICATED
----------------
No VIP API, RTL content, or protocol behavior is invented anywhere in this
module. Every derived field traces to a real input the caller supplied (a
real `env_manifest.build_vip_config()`/`build_vip_release()`/
`build_dut_facts_clock_reset()` result, a real bind-tier/boundary
classification) and is recorded in that IR's `source_evidence` list. Where a
placement question cannot be answered from the evidence supplied (no
boundary evidence for an endpoint, no declared clock/reset map, no chain
data at all), the honest answer is `status="UNKNOWN"`/`confidence="UNKNOWN"`
with a real reason string -- never a silently-assumed pass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .connectivity import (
    AUTO_EMITTABLE_TIERS,
    BIND_TIER_UNCLASSIFIED,
    REQUIRED_HUMAN_INPUT,
    BindTier,
    BindTierResult,
    render_markdown_table,
    unfilled_plan_fields,
)
from .inference import CONFIDENCE_LEVELS

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "verification_architecture.schema.json"

#: This module's confidence vocabulary is `inference.CONFIDENCE_LEVELS`
#: PLUS one honest addition, never a second, independently-invented scale.
#: UNKNOWN means "no real evidence exists to grade this record" -- distinct
#: from LOW, which means real evidence exists and it is weak.
IR_CONFIDENCE_LEVELS: tuple = tuple(CONFIDENCE_LEVELS) + ("UNKNOWN",)

#: Per-record honesty status. RESOLVED: every field this IR needs was
#: derived from real evidence. PARTIAL: some fields resolved, others still
#: need more evidence or a human answer. NOT_AVAILABLE: the underlying
#: producer (env_manifest/connectivity/phy_boundary) itself reported no
#: evidence. UNKNOWN: this module could not classify the record at all
#: (e.g. no chain/boundary data was supplied for it).
IR_STATUS_VALUES: tuple = ("RESOLVED", "PARTIAL", "NOT_AVAILABLE", "UNKNOWN")

#: How a bind-tier value grades IR confidence. Mirrors
#: `connectivity.AUTO_EMITTABLE_TIERS`'s own T1/T2 > T3 > T4 ordering --
#: this module invents no second tier-to-confidence mapping rationale.
_TIER_CONFIDENCE = {
    BindTier.T1_ALREADY_DECIDED.value: "HIGH",
    BindTier.T2_STRUCTURAL_MATCH.value: "HIGH",
    BindTier.T3_NAMING_HEURISTIC.value: "MEDIUM",
    BindTier.T4_UNDECIDABLE.value: "LOW",
    BIND_TIER_UNCLASSIFIED: "UNKNOWN",
}


class VerificationArchitectureError(ValueError):
    """A caller-supplied record violates this module's own vocabulary
    (an unrecognized status/confidence value), or a structural precondition
    a comparator depends on is missing. Raised rather than silently
    coerced, matching env_manifest.py's/phy_boundary.py's fail-closed
    discipline for their own generated artifacts."""


def _validate_vocab(value: str, allowed: tuple, field_name: str, context: str) -> None:
    if value not in allowed:
        raise VerificationArchitectureError(
            f"{field_name} must be one of {list(allowed)}, got {value!r} (record: {context})"
        )


def _evidence(fact_source: str, **detail) -> dict:
    """One `source_evidence` entry: which real function/module this fact
    came from, plus whatever detail helps a reviewer re-derive it. Never a
    bare unattributed value."""
    return {"fact_source": fact_source, "detail": detail}


def _tier_value(tier_info: Any) -> str:
    """Normalize a caller-supplied bind-tier reference -- a
    `connectivity.BindTierResult`, a bare `BindTier`, a dict carrying a
    `tier` key, a plain tier-value string, or nothing at all -- to its
    string value. Never guesses a tier this module was not told."""
    if tier_info is None or tier_info == "":
        return BIND_TIER_UNCLASSIFIED
    if isinstance(tier_info, BindTierResult):
        return tier_info.tier.value
    if isinstance(tier_info, BindTier):
        return tier_info.value
    if isinstance(tier_info, dict):
        return tier_info.get("tier") or BIND_TIER_UNCLASSIFIED
    return str(tier_info)


# ===========================================================================
# 1. VipSelectionIR
# ===========================================================================

@dataclass
class VipSelectionIR:
    """One selected VIP instance: `raw` is exactly one
    `env_manifest.build_vip_config()["vip_instances"]` entry
    (`instance_path`/`vip_type`/`config_fields`), unmodified. Everything
    else is derived evidence about why this instance was selected and how
    much that selection is trusted."""
    raw: dict
    bind_tier: str
    release_status: str
    release_version: Optional[str]
    active_passive: Optional[str]
    status: str
    confidence: str
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.status, IR_STATUS_VALUES, "status", self.vip_instance_path)
        _validate_vocab(self.confidence, IR_CONFIDENCE_LEVELS, "confidence", self.vip_instance_path)

    @property
    def vip_instance_path(self) -> Optional[str]:
        return self.raw.get("instance_path")

    @property
    def vip_type(self) -> Optional[str]:
        return self.raw.get("vip_type")

    def to_dict(self) -> dict:
        return {
            "ir_kind": "vip_selection",
            **self.raw,
            "bind_tier": self.bind_tier,
            "release_status": self.release_status,
            "release_version": self.release_version,
            "active_passive": self.active_passive,
            "status": self.status,
            "confidence": self.confidence,
            "source_evidence": self.source_evidence,
        }


def build_vip_selection_ir(
    vip_config: dict,
    vip_release: Optional[dict] = None,
    bind_tiers: Optional[dict] = None,
    active_passive_by_instance: Optional[dict] = None,
) -> list:
    """Assemble one `VipSelectionIR` per real captured VIP instance.

    `vip_config`: `env_manifest.build_vip_config()`'s own return dict. A
    NOT_AVAILABLE vip_config yields an EMPTY list, never fabricated
    instances -- there is nothing captured to build an IR from.
    `vip_release`: `env_manifest.build_vip_release()`'s own return dict,
    optional. Matched to an instance by `vip_type` == a scanned package
    `name`; a VIP type with no matching installed package records its
    release status honestly rather than guessing a version.
    `bind_tiers`: optional `{instance_path: <tier evidence>}`, where each
    value is anything `_tier_value()` accepts (a `connectivity.BindTierResult`,
    a bare tier, or a tier-value string) -- e.g. the result of running
    `connectivity.classify_bind_tier()` per instance upstream. Absent
    entries grade `BIND_TIER_UNCLASSIFIED` / confidence UNKNOWN, never a
    guessed tier.
    `active_passive_by_instance`: optional `{instance_path: "ACTIVE"|"PASSIVE"}`,
    e.g. read off a real `connectivity` matrix row for this instance.
    """
    if not isinstance(vip_config, dict) or vip_config.get("status") != "CAPTURED":
        return []

    release_packages = {}
    if isinstance(vip_release, dict) and vip_release.get("status") == "SCANNED":
        for pkg in vip_release.get("packages", []):
            release_packages.setdefault(pkg["name"], pkg)

    out = []
    for inst in vip_config.get("vip_instances", []):
        path = inst["instance_path"]
        vtype = inst["vip_type"]
        tier = _tier_value((bind_tiers or {}).get(path))
        confidence = _TIER_CONFIDENCE.get(tier, "UNKNOWN")
        evidence = [_evidence("env_manifest.build_vip_config", instance_path=path, vip_type=vtype)]

        pkg = release_packages.get(vtype)
        if pkg:
            release_status, release_version = "INSTALLED", pkg.get("version")
            evidence.append(_evidence("env_manifest.build_vip_release",
                                       package=vtype, version=pkg.get("version"),
                                       install_path=pkg.get("install_path")))
        elif isinstance(vip_release, dict):
            release_status, release_version = vip_release.get("status", "NOT_AVAILABLE"), None
            evidence.append(_evidence("env_manifest.build_vip_release", reason=vip_release.get("reason")))
        else:
            release_status, release_version = "NOT_AVAILABLE", None

        if tier != BIND_TIER_UNCLASSIFIED:
            evidence.append(_evidence("connectivity.classify_bind_tier", tier=tier))

        active_passive = (active_passive_by_instance or {}).get(path)
        if active_passive:
            evidence.append(_evidence("caller_declared_active_passive", value=active_passive))

        if tier in (BindTier.T1_ALREADY_DECIDED.value, BindTier.T2_STRUCTURAL_MATCH.value) and pkg:
            status = "RESOLVED"
        elif tier != BIND_TIER_UNCLASSIFIED or pkg:
            status = "PARTIAL"
        else:
            status = "UNKNOWN"

        out.append(VipSelectionIR(
            raw=inst, bind_tier=tier, release_status=release_status, release_version=release_version,
            active_passive=active_passive, status=status, confidence=confidence, source_evidence=evidence,
        ))
    return out


# ===========================================================================
# 2. VipBindIR -- extends the existing bind-entry shape with boundary +
#    wrapper/bridge classification
# ===========================================================================

#: A chain hop's classified role. WRAPPER: a clean passthrough hierarchy
#: level (same boundary kind on both sides -- no protocol/width
#: conversion). BRIDGE: a real protocol/width conversion point (a MIXED
#: boundary, per `phy_boundary.classify_boundary()`'s own documented
#: bridge/wrapper-module case). UNCLASSIFIED: no boundary evidence for this
#: hop, or the boundary itself is UNDECIDABLE -- never guessed from the
#: instance/module NAME (Bind-Location Rule 5's naming-evidence discipline,
#: applied here to a whole chain rather than one boundary pair).
CHAIN_HOP_ROLES: tuple = ("WRAPPER", "BRIDGE", "UNCLASSIFIED")


def classify_wrapper_bridge_hop(hop: dict) -> dict:
    """One hop between a DUT top and a VIP bind target. `hop` is a
    duck-typed dict: `{"instance": <path>, "module": <name>,
    "boundary_classification": <phy_boundary.classify_boundary() result>}`.
    `boundary_classification` is optional; absent or UNDECIDABLE evidence
    classifies UNCLASSIFIED rather than guessed.

    A MIXED boundary (both a parallel bus and a serial lane set genuinely
    present) is `phy_boundary.classify_boundary()`'s own documented shape
    for "a real PHY exposing both its serial pins and its parallel
    controller-facing port" -- i.e. a bridge/wrapper module by that
    module's own words. A boundary that is cleanly SERIAL or PARALLEL on
    both sides carries no conversion and is a passthrough WRAPPER hop."""
    instance = hop.get("instance")
    module = hop.get("module")
    classification = hop.get("boundary_classification")
    if not isinstance(classification, dict) or not classification.get("kind"):
        return {"instance": instance, "module": module, "role": "UNCLASSIFIED",
                "rationale": "no boundary classification evidence was supplied for this hop"}
    kind = classification["kind"]
    if kind == "MIXED":
        return {"instance": instance, "module": module, "role": "BRIDGE",
                "rationale": "boundary carries both parallel and serial payload signals "
                             "(phy_boundary.classify_boundary MIXED) -- a protocol/width "
                             "conversion point, not a passthrough hierarchy level"}
    if kind in ("PARALLEL", "SERIAL"):
        return {"instance": instance, "module": module, "role": "WRAPPER",
                "rationale": f"boundary is a single clean {kind} interface on both sides -- "
                             "a passthrough hierarchy level, no protocol conversion evidenced"}
    return {"instance": instance, "module": module, "role": "UNCLASSIFIED",
            "rationale": classification.get("rationale") or "boundary kind is UNDECIDABLE"}


def derive_wrapper_bridge_chain(hops: Optional[list]) -> list:
    """Classify every hop in a declared hierarchy chain. An empty/absent
    `hops` returns `[]` -- "no intermediate hops were declared", read by
    `build_vip_bind_ir()` as a DIRECT bind, never as an unclassified one."""
    return [classify_wrapper_bridge_hop(h) for h in (hops or [])]


@dataclass
class VipBindIR:
    """Extends the existing bind-entry shape (`target_instance`/`ports`/
    `reason`, plus whatever tier/human_confirmation fields
    `connectivity.enforce_bind_tier_policy()` already validates) with the
    boundary decision and wrapper/bridge chain classification. `raw` is the
    original bind entry, untouched."""
    raw: dict
    bind_tier: str
    boundary_kind: str
    bindable: Optional[bool]
    mount_layer: Optional[str]
    chain_classification: str
    chain_path: list
    status: str
    confidence: str
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.status, IR_STATUS_VALUES, "status", self.target_instance)
        _validate_vocab(self.confidence, IR_CONFIDENCE_LEVELS, "confidence", self.target_instance)

    @property
    def target_instance(self) -> Optional[str]:
        return self.raw.get("target_instance")

    def to_dict(self) -> dict:
        return {
            "ir_kind": "vip_bind",
            **self.raw,
            "bind_tier": self.bind_tier,
            "boundary_kind": self.boundary_kind,
            "bindable": self.bindable,
            "mount_layer": self.mount_layer,
            "chain_classification": self.chain_classification,
            "chain_path": self.chain_path,
            "status": self.status,
            "confidence": self.confidence,
            "source_evidence": self.source_evidence,
        }


#: `chain_classification` values. DIRECT: no intermediate hops declared (a
#: bind straight off the DUT top, or the chain was not supplied at all).
#: WRAPPER_ONLY: every declared hop is a passthrough. BRIDGE_IN_PATH: at
#: least one hop is a real protocol/width conversion point. UNKNOWN: hops
#: were declared but none could be classified.
CHAIN_CLASSIFICATIONS: tuple = ("DIRECT", "WRAPPER_ONLY", "BRIDGE_IN_PATH", "UNKNOWN")


def build_vip_bind_ir(
    bind_entries: list,
    boundary_by_target: Optional[dict] = None,
    chain_by_target: Optional[dict] = None,
) -> list:
    """Assemble one `VipBindIR` per bind entry.

    `bind_entries`: the existing bind-entry shape (`target_instance`/
    `ports`/`reason`, optionally `tier`) already produced upstream (e.g. by
    a bind-mechanism planning step) -- this module invents no bind entry of
    its own.
    `boundary_by_target`: optional `{target_instance: phy_boundary.decide_bind_location()
    result}`.
    `chain_by_target`: optional `{target_instance: <hops list for derive_wrapper_bridge_chain()>}`.
    """
    out = []
    for entry in bind_entries or []:
        target = entry.get("target_instance")
        tier = _tier_value(entry.get("tier"))
        # `raw` must stay JSON-serializable: a caller-supplied `tier` may be
        # a real `connectivity.BindTierResult`/`BindTier`, neither of which
        # `json.dumps()` can encode. Store the same normalized string value
        # this IR already computed, so `raw["tier"]` and `bind_tier` can
        # never disagree and the merged `to_dict()` output stays plain data.
        raw_entry = dict(entry)
        if "tier" in raw_entry:
            raw_entry["tier"] = tier
        evidence = [_evidence("connectivity.bind_entry", target_instance=target, tier=tier)]

        boundary = (boundary_by_target or {}).get(target)
        if isinstance(boundary, dict):
            boundary_kind = boundary.get("mount_layer") or "NOT_EVALUATED"
            bindable = boundary.get("bindable")
            mount_layer = boundary.get("mount_layer")
            evidence.append(_evidence("phy_boundary.decide_bind_location",
                                       mount_layer=mount_layer, bindable=bindable))
        else:
            boundary_kind, bindable, mount_layer = "NOT_EVALUATED", None, None

        chain = derive_wrapper_bridge_chain((chain_by_target or {}).get(target))
        if chain:
            evidence.append(_evidence("verification_architecture.derive_wrapper_bridge_chain",
                                       hop_count=len(chain),
                                       roles=[h["role"] for h in chain]))

        bridge_hops = [h for h in chain if h["role"] == "BRIDGE"]
        if bridge_hops:
            chain_classification = "BRIDGE_IN_PATH"
        elif not chain:
            chain_classification = "DIRECT"
        elif all(h["role"] == "WRAPPER" for h in chain):
            chain_classification = "WRAPPER_ONLY"
        else:
            chain_classification = "UNKNOWN"

        if boundary is not None and chain_classification != "UNKNOWN":
            status = "RESOLVED"
        elif boundary is not None or chain_by_target and target in (chain_by_target or {}):
            status = "PARTIAL"
        else:
            status = "UNKNOWN"

        out.append(VipBindIR(
            raw=raw_entry, bind_tier=tier, boundary_kind=boundary_kind, bindable=bindable,
            mount_layer=mount_layer, chain_classification=chain_classification, chain_path=chain,
            status=status, confidence=_TIER_CONFIDENCE.get(tier, "UNKNOWN"), source_evidence=evidence,
        ))
    return out


# ===========================================================================
# 3. CheckerIR -- extends connectivity.generate_protocol_check_entry()
# ===========================================================================

@dataclass
class CheckerIR:
    """Extends `connectivity.generate_protocol_check_entry()`'s
    `protocol_check` shape. `target_instance`/`mount_side` are this
    module's own additions -- neither exists on the underlying entry --
    naming which bind target this checker watches and, when the caller
    knows, which side of a bridge (if any) it is mounted on. Both default
    to `None`: an unlinked checker is reported PARTIAL, never guessed."""
    raw: dict
    target_instance: Optional[str]
    mount_side: Optional[str]
    status: str
    confidence: str
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.status, IR_STATUS_VALUES, "status", self.interface_row_id)
        _validate_vocab(self.confidence, IR_CONFIDENCE_LEVELS, "confidence", self.interface_row_id)

    @property
    def interface_row_id(self) -> Optional[str]:
        return self.raw.get("interface_row_id")

    def to_dict(self) -> dict:
        return {
            "ir_kind": "checker",
            **self.raw,
            "target_instance": self.target_instance,
            "mount_side": self.mount_side,
            "status": self.status,
            "confidence": self.confidence,
            "source_evidence": self.source_evidence,
        }


#: Legal `mount_side` values, meaningful only relative to a bind target
#: whose chain crosses a bridge. PRE_BRIDGE: mounted before the conversion
#: point (DUT-facing side of the bridge). POST_BRIDGE: mounted after it
#: (the side actually reaching the declared bind target).
CHECKER_MOUNT_SIDES: tuple = ("PRE_BRIDGE", "POST_BRIDGE")


def build_checker_ir(protocol_check_entries: list, checker_links: Optional[dict] = None) -> list:
    """Assemble one `CheckerIR` per protocol-check plan entry.

    `protocol_check_entries`: `connectivity.generate_protocol_check_entry()`
    shaped dicts.
    `checker_links`: optional `{interface_row_id: {"target_instance": ...,
    "mount_side": "PRE_BRIDGE"|"POST_BRIDGE"}}` -- project-declared linkage
    from a checker's interface row to the bind target it watches. Without
    it a checker cannot be cross-checked against a bind's chain
    classification at all (see `detect_placement_conflicts()`), and this
    function reports that honestly rather than guessing a link from the
    interface/vip_type name."""
    out = []
    for entry in protocol_check_entries or []:
        row_id = entry.get("interface_row_id")
        link = (checker_links or {}).get(row_id) or {}
        target = link.get("target_instance")
        mount_side = link.get("mount_side")
        if mount_side is not None and mount_side not in CHECKER_MOUNT_SIDES:
            raise VerificationArchitectureError(
                f"mount_side must be one of {list(CHECKER_MOUNT_SIDES)}, got {mount_side!r} "
                f"(checker interface_row_id={row_id!r})"
            )
        evidence = [_evidence("connectivity.generate_protocol_check_entry", interface_row_id=row_id)]
        if link:
            evidence.append(_evidence("caller_declared_checker_link",
                                       target_instance=target, mount_side=mount_side))
        if target and mount_side:
            status = "RESOLVED"
        elif target:
            status = "PARTIAL"
        else:
            status = "UNKNOWN"
        confidence = "HIGH" if (target and mount_side) else ("MEDIUM" if target else "UNKNOWN")
        out.append(CheckerIR(
            raw=entry, target_instance=target, mount_side=mount_side,
            status=status, confidence=confidence, source_evidence=evidence,
        ))
    return out


# ===========================================================================
# 4. ScoreboardIR -- extends connectivity.generate_scoreboard_entry()
# ===========================================================================

def assess_scoreboard_comparability(entry: dict, boundary_by_endpoint: Optional[dict] = None):
    """Whether a scoreboard's declared `endpoint_pairs` are structurally
    comparable. Conservative by construction: with no `endpoint_pairs`
    resolved yet, or no boundary evidence supplied for either endpoint,
    this returns `(None, <reason>)` -- UNKNOWN, never a guessed True.
    Comparability is judged `False` only when real
    `phy_boundary.classify_boundary()`-derived boundary KIND evidence for
    the two endpoints actually disagrees (one endpoint's declared boundary
    is SERIAL/PARALLEL and the other's is a different one) -- two
    UNDECIDABLE boundaries are not a disagreement, they are two unresolved
    facts, so they do not fail comparability by themselves.

    Returns `(comparable: Optional[bool], reason: str)`.
    """
    pairs = entry.get("endpoint_pairs")
    if not isinstance(pairs, list) or not pairs:
        return None, "endpoint_pairs is not yet resolved (REQUIRED_HUMAN_INPUT or empty) -- comparability unknown"
    if not boundary_by_endpoint:
        return None, "no boundary evidence supplied for either endpoint -- comparability unknown"

    disagreements = []
    any_evidence = False
    for pair in pairs:
        if isinstance(pair, dict):
            src, sink = pair.get("source"), pair.get("sink")
        else:
            src, sink = pair[0], pair[1]
        src_b = boundary_by_endpoint.get(src)
        sink_b = boundary_by_endpoint.get(sink)
        src_kind = src_b.get("kind") if isinstance(src_b, dict) else None
        sink_kind = sink_b.get("kind") if isinstance(sink_b, dict) else None
        if src_kind and sink_kind:
            any_evidence = True
            if src_kind != sink_kind and "UNDECIDABLE" not in (src_kind, sink_kind):
                disagreements.append(f"{src} boundary={src_kind} vs {sink} boundary={sink_kind}")
    if not any_evidence:
        return None, "boundary evidence supplied but neither endpoint of any pair resolved a real kind"
    if disagreements:
        return False, "; ".join(disagreements)
    return True, "endpoint boundary kinds agree for every declared pair"


@dataclass
class ScoreboardIR:
    """Extends `connectivity.generate_scoreboard_entry()`'s
    `data_integrity_scoreboard` shape with structural comparability
    evidence. `raw` is the original entry, untouched -- including any
    `REQUIRED_HUMAN_INPUT` sentinels `unfilled_fields` also names, since
    `raw` is what a downstream consumer (e.g.
    `route_unfilled_fields_to_question_queue()`) still needs verbatim."""
    raw: dict
    unfilled_fields: list
    comparable: Optional[bool]
    comparability_reason: str
    status: str
    confidence: str
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.status, IR_STATUS_VALUES, "status", self.scoreboard_id)
        _validate_vocab(self.confidence, IR_CONFIDENCE_LEVELS, "confidence", self.scoreboard_id)

    @property
    def scoreboard_id(self) -> Optional[str]:
        return self.raw.get("scoreboard_id")

    @property
    def endpoint_pairs(self):
        return self.raw.get("endpoint_pairs")

    def to_dict(self) -> dict:
        return {
            "ir_kind": "scoreboard",
            **self.raw,
            "unfilled_fields": self.unfilled_fields,
            "comparable": self.comparable,
            "comparability_reason": self.comparability_reason,
            "status": self.status,
            "confidence": self.confidence,
            "source_evidence": self.source_evidence,
        }


def build_scoreboard_ir(scoreboard_entries: list, boundary_by_endpoint: Optional[dict] = None) -> list:
    """Assemble one `ScoreboardIR` per `connectivity.generate_scoreboard_entry()`
    plan entry. `boundary_by_endpoint`: optional `{endpoint_path:
    phy_boundary.classify_boundary() result}`, keyed by the exact endpoint
    hierarchy-path string used in the entry's `endpoint_pairs`."""
    out = []
    for entry in scoreboard_entries or []:
        unfilled = unfilled_plan_fields(entry)
        comparable, comparability_reason = assess_scoreboard_comparability(entry, boundary_by_endpoint)
        evidence = [_evidence("connectivity.generate_scoreboard_entry", scoreboard_id=entry.get("scoreboard_id"))]
        if boundary_by_endpoint:
            evidence.append(_evidence("phy_boundary.classify_boundary", reason=comparability_reason))

        endpoint_pairs = entry.get("endpoint_pairs")
        if not isinstance(endpoint_pairs, list) or not endpoint_pairs:
            status = "NOT_AVAILABLE"
        elif unfilled or comparable is None:
            status = "PARTIAL"
        else:
            status = "RESOLVED"

        if comparable is False:
            confidence = "LOW"
        elif status == "RESOLVED":
            confidence = "HIGH"
        elif status == "PARTIAL":
            confidence = "MEDIUM"
        else:
            confidence = "UNKNOWN"

        out.append(ScoreboardIR(
            raw=entry, unfilled_fields=unfilled, comparable=comparable,
            comparability_reason=comparability_reason, status=status, confidence=confidence,
            source_evidence=evidence,
        ))
    return out


# ===========================================================================
# 5. AssertionIR
# ===========================================================================

@dataclass
class AssertionIR:
    """One SVA assertion placement claim. There is no pre-existing
    assertion-plan producer in `connectivity.py`/`env_manifest.py`/
    `phy_boundary.py` to extend (unlike the other four IRs), so `raw` is
    the caller-supplied candidate dict itself: `{"assertion_id",
    "target_signal", "target_instance", "clock_domain", "reset_domain",
    "checked_property"}` -- `checked_property` is optional free text naming
    which protocol rule/behaviour this assertion checks, used only by the
    intra-subsystem duplicate check below."""
    raw: dict
    clock_domain_match: Optional[bool]
    reset_domain_match: Optional[bool]
    status: str
    confidence: str
    source_evidence: list

    def __post_init__(self) -> None:
        _validate_vocab(self.status, IR_STATUS_VALUES, "status", self.assertion_id)
        _validate_vocab(self.confidence, IR_CONFIDENCE_LEVELS, "confidence", self.assertion_id)

    @property
    def assertion_id(self) -> Optional[str]:
        return self.raw.get("assertion_id")

    @property
    def target_instance(self) -> Optional[str]:
        return self.raw.get("target_instance")

    @property
    def checked_property(self) -> Optional[str]:
        return self.raw.get("checked_property")

    def to_dict(self) -> dict:
        return {
            "ir_kind": "assertion",
            **self.raw,
            "clock_domain_match": self.clock_domain_match,
            "reset_domain_match": self.reset_domain_match,
            "status": self.status,
            "confidence": self.confidence,
            "source_evidence": self.source_evidence,
        }


def _clock_reset_lookup(clock_reset: Optional[dict]):
    """Real declared clock/reset names + domains from
    `env_manifest.build_dut_facts_clock_reset()`'s own shape. Returns
    `(clock_names, clock_domain_by_name, reset_domain_by_name, loaded)`.
    `loaded=False` when the layer itself is NOT_AVAILABLE -- nothing here
    is a substitute for that layer actually having real evidence."""
    if not isinstance(clock_reset, dict) or clock_reset.get("status") != "LOADED":
        return set(), {}, {}, False
    clock_domain_by_name = {}
    for c in clock_reset.get("clocks", []):
        clock_domain_by_name[c["name"]] = c.get("domain") or c["name"]
    reset_domain_by_name = {}
    for r in clock_reset.get("resets", []):
        clk = r.get("clock")
        reset_domain_by_name[r["name"]] = clock_domain_by_name.get(clk, clk)
    return set(clock_domain_by_name), clock_domain_by_name, reset_domain_by_name, True


def build_assertion_ir(assertion_candidates: list, clock_reset: Optional[dict] = None) -> list:
    """Assemble one `AssertionIR` per candidate.

    `assertion_candidates`: caller-supplied dicts (see `AssertionIR.raw`
    above) -- this module authors no assertion content of its own (No
    Golden-Reference Content Mining: assertion CONTENT is out of this
    module's scope entirely).
    `clock_reset`: `env_manifest.build_dut_facts_clock_reset()`'s own
    return dict. When it is not LOADED, every candidate's domain-match
    fields are honestly `None` (UNKNOWN) -- there is no real clock/reset
    map to check against, so this module never claims a match or a
    mismatch it cannot support."""
    clock_names, clock_domain_by_name, reset_domain_by_name, loaded = _clock_reset_lookup(clock_reset)
    known_domains = set(clock_domain_by_name.values())
    out = []
    for cand in assertion_candidates or []:
        declared_clock_domain = cand.get("clock_domain")
        declared_reset_domain = cand.get("reset_domain")
        evidence = [_evidence("caller_declared_assertion_candidate", assertion_id=cand.get("assertion_id"))]

        if not loaded:
            clock_domain_match = None
            reset_domain_match = None
            evidence.append(_evidence("env_manifest.build_dut_facts_clock_reset",
                                       reason=(clock_reset or {}).get("reason") if isinstance(clock_reset, dict)
                                       else "no clock_reset layer supplied"))
        else:
            evidence.append(_evidence("env_manifest.build_dut_facts_clock_reset",
                                       known_clock_domains=sorted(known_domains)))
            clock_domain_match = (declared_clock_domain in known_domains
                                   or declared_clock_domain in clock_names) if declared_clock_domain else None
            reset_domain_match = (declared_reset_domain in set(reset_domain_by_name.values())
                                   or declared_reset_domain in known_domains) if declared_reset_domain else None

        if clock_domain_match is None and reset_domain_match is None:
            status = "UNKNOWN" if not loaded else "NOT_AVAILABLE"
        elif clock_domain_match is False or reset_domain_match is False:
            status = "PARTIAL"
        else:
            status = "RESOLVED"

        if not loaded:
            confidence = "UNKNOWN"
        elif clock_domain_match is False or reset_domain_match is False:
            confidence = "LOW"
        elif clock_domain_match and (reset_domain_match or reset_domain_match is None):
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"

        out.append(AssertionIR(
            raw=cand, clock_domain_match=clock_domain_match, reset_domain_match=reset_domain_match,
            status=status, confidence=confidence, source_evidence=evidence,
        ))
    return out


# ===========================================================================
# Comparators
# ===========================================================================

#: Every kind `detect_placement_conflicts()` can report. Fixed and closed --
#: an unrecognized kind string appearing in a returned finding is a bug in
#: this module, never a caller-extensible open vocabulary (a comparator with
#: a silently-growable finding vocabulary is exactly the kind of drift
#: `assert_active_passive_vocabulary()`-style guards exist elsewhere to
#: prevent).
PLACEMENT_CONFLICT_KINDS: tuple = (
    "VIP_AFTER_BRIDGE",
    "CHECKER_WRONG_SIDE_OF_BRIDGE",
    "ASSERTION_WRONG_CLOCK_DOMAIN",
    "SCOREBOARD_INPUTS_NOT_COMPARABLE",
    "DUPLICATE_ACTIVE_VIP",
    "WRONG_RESET_DOMAIN",
)


def _finding(kind: str, *, severity: str, summary: str, evidence: list, **extra) -> dict:
    if kind not in PLACEMENT_CONFLICT_KINDS and kind not in _DUPLICATE_KINDS:
        raise VerificationArchitectureError(f"unrecognized finding kind {kind!r}")
    d = {"kind": kind, "severity": severity, "summary": summary, "evidence": evidence}
    d.update(extra)
    return d


def detect_placement_conflicts(
    *, vip_selections: Optional[list] = None, vip_binds: Optional[list] = None,
    checkers: Optional[list] = None, scoreboards: Optional[list] = None,
    assertions: Optional[list] = None,
) -> list:
    """Walk a subsystem's assembled IRs and report every placement conflict
    the evidence they carry can actually support. Every argument defaults
    to an empty list -- a caller need only pass the IR kinds it has; a
    conflict class whose IRs were not supplied simply contributes no
    findings, rather than raising."""
    vip_selections = vip_selections or []
    vip_binds = vip_binds or []
    checkers = checkers or []
    scoreboards = scoreboards or []
    assertions = assertions or []

    findings = []

    # VIP_AFTER_BRIDGE: a VIP instance whose own hierarchy path sits below
    # (i.e. is a descendant of) a bind target whose chain crosses a real
    # bridge hop. Real structural evidence: the instance path prefix match
    # plus the bind's own already-derived chain_classification.
    bridge_binds = [b for b in vip_binds if b.chain_classification == "BRIDGE_IN_PATH"]
    for b in bridge_binds:
        target = b.target_instance
        if not target:
            continue
        for sel in vip_selections:
            path = sel.vip_instance_path
            if path and (path == target or path.startswith(target + ".")):
                findings.append(_finding(
                    "VIP_AFTER_BRIDGE", severity="MEDIUM",
                    summary=f"VIP instance {path!r} sits at or below bind target {target!r}, whose "
                            "hierarchy chain crosses a bridge/protocol-conversion hop -- confirm the "
                            "bound VIP protocol matches what actually reaches this point post-conversion",
                    evidence=b.source_evidence + sel.source_evidence,
                    vip_instance_path=path, target_instance=target,
                ))

    # CHECKER_WRONG_SIDE_OF_BRIDGE: a checker declaring PRE_BRIDGE for a
    # target whose chain shows a bridge in path. The only side a checker
    # mounted AT the declared bind target (the chain's own terminus) can
    # legitimately observe is the side reached AFTER every hop -- i.e.
    # POST_BRIDGE. PRE_BRIDGE at that same target is not "an earlier point
    # in the pipeline", it names the wrong side of the very bridge already
    # crossed to reach the target this checker is linked to.
    bind_by_target = {b.target_instance: b for b in vip_binds if b.target_instance}
    for c in checkers:
        b = bind_by_target.get(c.target_instance)
        if b and b.chain_classification == "BRIDGE_IN_PATH" and c.mount_side == "PRE_BRIDGE":
            findings.append(_finding(
                "CHECKER_WRONG_SIDE_OF_BRIDGE", severity="HIGH",
                summary=f"checker on interface {c.interface_row_id!r} declares mount_side=PRE_BRIDGE "
                        f"for bind target {c.target_instance!r}, but the chain to that target already "
                        "crosses a bridge -- a checker mounted at the target observes only the "
                        "POST_BRIDGE side",
                evidence=c.source_evidence + b.source_evidence,
                interface_row_id=c.interface_row_id, target_instance=c.target_instance,
            ))

    # ASSERTION_WRONG_CLOCK_DOMAIN / WRONG_RESET_DOMAIN: derived, not
    # re-checked here -- AssertionIR already computed the match against the
    # real dut_facts.clock_reset map.
    for a in assertions:
        if a.clock_domain_match is False:
            findings.append(_finding(
                "ASSERTION_WRONG_CLOCK_DOMAIN", severity="HIGH",
                summary=f"assertion {a.assertion_id!r} declares clock_domain "
                        f"{a.raw.get('clock_domain')!r}, which is not among this DUT's real declared "
                        "clock domains",
                evidence=a.source_evidence, assertion_id=a.assertion_id,
            ))
        if a.reset_domain_match is False:
            findings.append(_finding(
                "WRONG_RESET_DOMAIN", severity="HIGH",
                summary=f"assertion {a.assertion_id!r} declares reset_domain "
                        f"{a.raw.get('reset_domain')!r}, which is not among this DUT's real declared "
                        "reset domains",
                evidence=a.source_evidence, assertion_id=a.assertion_id,
            ))

    # SCOREBOARD_INPUTS_NOT_COMPARABLE: ScoreboardIR already computed this.
    for s in scoreboards:
        if s.comparable is False:
            findings.append(_finding(
                "SCOREBOARD_INPUTS_NOT_COMPARABLE", severity="HIGH",
                summary=f"scoreboard {s.scoreboard_id!r}'s declared endpoints carry disagreeing real "
                        f"boundary evidence: {s.comparability_reason}",
                evidence=s.source_evidence, scoreboard_id=s.scoreboard_id,
            ))

    # DUPLICATE_ACTIVE_VIP: two or more selections on the identical
    # instance path where neither is affirmatively declared PASSIVE. Two
    # passive monitors sharing an instance path is not a conflict (two
    # observers, no ownership contention); an unknown active_passive value
    # errs toward flagging rather than silently assuming PASSIVE.
    by_path: dict = {}
    for sel in vip_selections:
        if sel.vip_instance_path:
            by_path.setdefault(sel.vip_instance_path, []).append(sel)
    for path, sels in by_path.items():
        if len(sels) < 2:
            continue
        if all(s.active_passive == "PASSIVE" for s in sels):
            continue
        evidence = []
        for s in sels:
            evidence.extend(s.source_evidence)
        findings.append(_finding(
            "DUPLICATE_ACTIVE_VIP", severity="HIGH",
            summary=f"{len(sels)} VIP selections claim the same instance path {path!r} and at least "
                    "one is not affirmatively declared PASSIVE",
            evidence=evidence, vip_instance_path=path, vip_types=[s.vip_type for s in sels],
        ))

    return findings


#: Every kind `detect_intra_subsystem_duplicates()` can report.
_DUPLICATE_KINDS: tuple = (
    "VIP_CHECKER_DUPLICATES_SVA",
    "SCOREBOARD_DUPLICATES_CHECKER",
    "DUPLICATE_SCOREBOARD_PATH",
)

#: Tokens (checked case-insensitively, split on "_") in a checker's
#: `enabled_builtin_checks` names that indicate the VIP's own built-in
#: check ALREADY performs data-integrity comparison equivalent to a
#: scoreboard -- used only by `SCOREBOARD_DUPLICATES_CHECKER`. This is a
#: naming-convention heuristic over the checker's OWN declared check names
#: (real evidence the plan already carries), not a guess about VIP
#: internals; a project whose VIP spells this differently supplies no
#: matching token and the check simply never fires for it, rather than a
#: false positive being invented.
_DATA_INTEGRITY_CHECK_TOKENS = frozenset({"integrity", "compare", "scoreboard", "match", "checksum"})


def detect_intra_subsystem_duplicates(
    *, checkers: Optional[list] = None, scoreboards: Optional[list] = None,
    assertions: Optional[list] = None,
) -> list:
    """The intra-subsystem duplicate-check: the same real-behaviour check
    performed twice by two different mechanisms in the same subsystem.
    Three checks, each grounded in fields the IRs above already carry:

    - VIP_CHECKER_DUPLICATES_SVA: a checker's `enabled_builtin_checks`
      contains a name equal (case-insensitive) to an assertion's declared
      `checked_property`, for a checker/assertion pair sharing the same
      `target_instance` -- the VIP's own built-in check and a hand-authored
      SVA are asserting the identical property on the identical target.
    - SCOREBOARD_DUPLICATES_CHECKER: a checker whose enabled checks name a
      data-integrity token (see `_DATA_INTEGRITY_CHECK_TOKENS`) is linked
      to a `target_instance` that also appears as one of a scoreboard's
      declared endpoint hierarchy paths -- the VIP checker and the
      scoreboard are comparing the same path.
    - DUPLICATE_SCOREBOARD_PATH: two scoreboards declare an identical
      (source, sink) endpoint pair.
    """
    checkers = checkers or []
    scoreboards = scoreboards or []
    assertions = assertions or []
    findings = []

    for c in checkers:
        if not c.target_instance:
            continue
        enabled_lower = {str(x).lower() for x in (c.raw.get("enabled_builtin_checks") or [])}
        for a in assertions:
            prop = a.checked_property
            if prop and a.target_instance == c.target_instance and prop.lower() in enabled_lower:
                findings.append(_finding(
                    "VIP_CHECKER_DUPLICATES_SVA", severity="MEDIUM",
                    summary=f"checker on {c.target_instance!r} already enables built-in check "
                            f"{prop!r}, which assertion {a.assertion_id!r} re-checks on the same target",
                    evidence=c.source_evidence + a.source_evidence,
                    target_instance=c.target_instance, checked_property=prop, assertion_id=a.assertion_id,
                ))

    for c in checkers:
        if not c.target_instance:
            continue
        enabled = c.raw.get("enabled_builtin_checks") or []
        tokens = set()
        for name in enabled:
            tokens.update(str(name).lower().split("_"))
        if not (tokens & _DATA_INTEGRITY_CHECK_TOKENS):
            continue
        for s in scoreboards:
            pairs = s.endpoint_pairs
            if not isinstance(pairs, list):
                continue
            for pair in pairs:
                src, sink = (pair.get("source"), pair.get("sink")) if isinstance(pair, dict) else (pair[0], pair[1])
                if c.target_instance in (src, sink):
                    findings.append(_finding(
                        "SCOREBOARD_DUPLICATES_CHECKER", severity="MEDIUM",
                        summary=f"scoreboard {s.scoreboard_id!r} compares endpoint {c.target_instance!r}, "
                                "which a VIP checker on the same target already data-integrity-checks",
                        evidence=c.source_evidence + s.source_evidence,
                        target_instance=c.target_instance, scoreboard_id=s.scoreboard_id,
                    ))

    seen_pairs: dict = {}
    for s in scoreboards:
        pairs = s.endpoint_pairs
        if not isinstance(pairs, list):
            continue
        for pair in pairs:
            key = (pair.get("source"), pair.get("sink")) if isinstance(pair, dict) else tuple(pair)
            seen_pairs.setdefault(key, []).append(s)
    for key, sbs in seen_pairs.items():
        if len(sbs) < 2:
            continue
        evidence = []
        for s in sbs:
            evidence.extend(s.source_evidence)
        findings.append(_finding(
            "DUPLICATE_SCOREBOARD_PATH", severity="MEDIUM",
            summary=f"{len(sbs)} scoreboards declare the identical endpoint pair {key!r}",
            evidence=evidence, endpoint_pair=list(key), scoreboard_ids=[s.scoreboard_id for s in sbs],
        ))

    return findings


# ===========================================================================
# Rendering -- reuses connectivity.render_markdown_table()'s one
# parameterized markdown-table pattern; no second renderer added here.
# ===========================================================================

def render_vip_bind_matrix(vip_binds: list) -> str:
    """VIP Bind Matrix."""
    columns = [
        ("target_instance", "Target Instance"), ("bind_tier", "Tier"),
        ("boundary_kind", "Boundary"), ("bindable", "Bindable"),
        ("chain_classification", "Chain"), ("status", "Status"), ("confidence", "Confidence"),
    ]
    rows = [{"target_instance": b.target_instance, "bind_tier": b.bind_tier,
             "boundary_kind": b.boundary_kind, "bindable": b.bindable,
             "chain_classification": b.chain_classification, "status": b.status,
             "confidence": b.confidence} for b in vip_binds]
    return render_markdown_table(columns, rows, empty_note="(no VIP binds)")


def render_interface_to_verification_matrix(
    vip_binds: list, checkers: list, scoreboards: list, assertions: list,
    conflicts: Optional[list] = None,
) -> str:
    """Interface-to-Verification Matrix: one row per bind target, showing
    how many checkers/scoreboards/assertions are linked to it and whether
    any conflict names it."""
    conflicts = conflicts or []
    targets = {b.target_instance for b in vip_binds if b.target_instance}
    targets |= {c.target_instance for c in checkers if c.target_instance}
    checker_count: dict = {}
    for c in checkers:
        if c.target_instance:
            checker_count[c.target_instance] = checker_count.get(c.target_instance, 0) + 1
    scoreboard_count: dict = {}
    for s in scoreboards:
        pairs = s.endpoint_pairs
        if isinstance(pairs, list):
            for pair in pairs:
                src, sink = (pair.get("source"), pair.get("sink")) if isinstance(pair, dict) else (pair[0], pair[1])
                for ep in (src, sink):
                    if ep:
                        scoreboard_count[ep] = scoreboard_count.get(ep, 0) + 1
                        targets.add(ep)
    assertion_count: dict = {}
    for a in assertions:
        if a.target_instance:
            assertion_count[a.target_instance] = assertion_count.get(a.target_instance, 0) + 1
            targets.add(a.target_instance)
    conflict_count: dict = {}
    for f in conflicts:
        for key in ("target_instance", "vip_instance_path"):
            t = f.get(key)
            if t:
                conflict_count[t] = conflict_count.get(t, 0) + 1

    columns = [
        ("interface", "Interface / Target Instance"), ("checkers", "Checkers"),
        ("scoreboards", "Scoreboards"), ("assertions", "Assertions"), ("conflicts", "Conflicts"),
    ]
    rows = [{"interface": t, "checkers": checker_count.get(t, 0),
             "scoreboards": scoreboard_count.get(t, 0), "assertions": assertion_count.get(t, 0),
             "conflicts": conflict_count.get(t, 0)} for t in sorted(targets)]
    return render_markdown_table(columns, rows, empty_note="(no interfaces)")


def render_function_to_checker_matrix(checkers: list) -> str:
    """Function-to-Checker Matrix."""
    columns = [
        ("interface_row_id", "Interface Row"), ("vip_type", "VIP Type"),
        ("target_instance", "Target Instance"), ("mount_side", "Mount Side"),
        ("enabled_builtin_checks", "Enabled Checks"), ("disabled_builtin_checks", "Disabled Checks"),
        ("status", "Status"),
    ]
    rows = [{"interface_row_id": c.interface_row_id, "vip_type": c.raw.get("vip_type"),
             "target_instance": c.target_instance, "mount_side": c.mount_side,
             "enabled_builtin_checks": ", ".join(c.raw.get("enabled_builtin_checks") or []),
             "disabled_builtin_checks": ", ".join(
                 d.get("check", "") for d in (c.raw.get("disabled_builtin_checks") or [])),
             "status": c.status} for c in checkers]
    return render_markdown_table(columns, rows, empty_note="(no checkers)")


def render_assertion_placement_matrix(assertions: list) -> str:
    """Assertion Placement Matrix."""
    columns = [
        ("assertion_id", "Assertion"), ("target_instance", "Target Instance"),
        ("clock_domain", "Clock Domain"), ("clock_domain_match", "Clock OK"),
        ("reset_domain", "Reset Domain"), ("reset_domain_match", "Reset OK"),
        ("status", "Status"), ("confidence", "Confidence"),
    ]
    rows = [{"assertion_id": a.assertion_id, "target_instance": a.target_instance,
             "clock_domain": a.raw.get("clock_domain"), "clock_domain_match": a.clock_domain_match,
             "reset_domain": a.raw.get("reset_domain"), "reset_domain_match": a.reset_domain_match,
             "status": a.status, "confidence": a.confidence} for a in assertions]
    return render_markdown_table(columns, rows, empty_note="(no assertions)")


def render_scoreboard_architecture_matrix(scoreboards: list) -> str:
    """Scoreboard Architecture Matrix."""
    columns = [
        ("scoreboard_id", "Scoreboard"), ("endpoint_pairs", "Endpoint Pairs"),
        ("matching_key", "Matching Key"), ("comparable", "Comparable"),
        ("unfilled_fields", "Unfilled Fields"), ("status", "Status"), ("confidence", "Confidence"),
    ]
    rows = []
    for s in scoreboards:
        pairs = s.endpoint_pairs
        pairs_str = "; ".join(
            f"{(p.get('source') if isinstance(p, dict) else p[0])}->{(p.get('sink') if isinstance(p, dict) else p[1])}"
            for p in pairs
        ) if isinstance(pairs, list) else str(pairs)
        rows.append({"scoreboard_id": s.scoreboard_id, "endpoint_pairs": pairs_str,
                     "matching_key": s.raw.get("matching_key"), "comparable": s.comparable,
                     "unfilled_fields": ", ".join(s.unfilled_fields), "status": s.status,
                     "confidence": s.confidence})
    return render_markdown_table(columns, rows, empty_note="(no scoreboards)")


# ===========================================================================
# Top-level assembly + schema validation
# ===========================================================================

def assemble_verification_architecture(
    *,
    vip_config: Optional[dict] = None, vip_release: Optional[dict] = None,
    bind_tiers: Optional[dict] = None, active_passive_by_instance: Optional[dict] = None,
    bind_entries: Optional[list] = None, boundary_by_target: Optional[dict] = None,
    chain_by_target: Optional[dict] = None,
    protocol_check_entries: Optional[list] = None, checker_links: Optional[dict] = None,
    scoreboard_entries: Optional[list] = None, boundary_by_endpoint: Optional[dict] = None,
    assertion_candidates: Optional[list] = None, clock_reset: Optional[dict] = None,
) -> dict:
    """One call assembling all five IR lists, both comparators, and the
    five rendered matrices. Every argument is optional -- a caller building
    only, say, VIP-bind evidence gets empty lists (never errors) for the
    IR kinds it did not supply."""
    vip_selections = build_vip_selection_ir(vip_config or {"status": "NOT_AVAILABLE"}, vip_release,
                                             bind_tiers, active_passive_by_instance)
    vip_binds = build_vip_bind_ir(bind_entries or [], boundary_by_target, chain_by_target)
    checkers = build_checker_ir(protocol_check_entries or [], checker_links)
    scoreboards = build_scoreboard_ir(scoreboard_entries or [], boundary_by_endpoint)
    assertions = build_assertion_ir(assertion_candidates or [], clock_reset)

    conflicts = detect_placement_conflicts(
        vip_selections=vip_selections, vip_binds=vip_binds, checkers=checkers,
        scoreboards=scoreboards, assertions=assertions,
    )
    duplicates = detect_intra_subsystem_duplicates(
        checkers=checkers, scoreboards=scoreboards, assertions=assertions,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "vip_selection": [v.to_dict() for v in vip_selections],
        "vip_bind": [v.to_dict() for v in vip_binds],
        "checker": [v.to_dict() for v in checkers],
        "scoreboard": [v.to_dict() for v in scoreboards],
        "assertion": [v.to_dict() for v in assertions],
        "placement_conflicts": conflicts,
        "intra_subsystem_duplicates": duplicates,
        "matrices": {
            "vip_bind": render_vip_bind_matrix(vip_binds),
            "interface_to_verification": render_interface_to_verification_matrix(
                vip_binds, checkers, scoreboards, assertions, conflicts),
            "function_to_checker": render_function_to_checker_matrix(checkers),
            "assertion_placement": render_assertion_placement_matrix(assertions),
            "scoreboard_architecture": render_scoreboard_architecture_matrix(scoreboards),
        },
        "_irs": {  # not part of the JSON schema -- convenience for a Python caller
            "vip_selections": vip_selections, "vip_binds": vip_binds, "checkers": checkers,
            "scoreboards": scoreboards, "assertions": assertions,
        },
    }


class VerificationArchitectureValidationError(ValueError):
    """The assembled document (with `_irs` stripped) fails
    verification_architecture.schema.json validation."""


def validate_verification_architecture(doc: dict) -> None:
    """Validate `doc` (as returned by `assemble_verification_architecture()`,
    minus its `_irs` convenience key) against
    `verification_architecture.schema.json`. Raises
    `VerificationArchitectureValidationError` on any violation -- matching
    `phy_boundary.py`'s/`env_manifest.py`'s fail-closed discipline."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise VerificationArchitectureValidationError(
            "jsonschema package is not installed; cannot validate against "
            "verification_architecture.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    to_check = {k: v for k, v in doc.items() if k != "_irs"}
    errors = sorted(validator.iter_errors(to_check), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise VerificationArchitectureValidationError(
            "verification_architecture.schema.json validation failed:\n" + "\n".join(lines)
        )
