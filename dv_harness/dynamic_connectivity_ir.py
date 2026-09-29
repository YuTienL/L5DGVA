"""dv_harness/dynamic_connectivity_ir.py -- DynamicConnectivityIR: a model of
RUNTIME-RECONFIGURABLE routing paths through an AMBA (or AMBA-like) fabric --
e.g. a register-programmed address decode that can change which slave a
master reaches at runtime -- kept deliberately DISTINCT from the STATIC
connectivity this project's Batch 9 already built.

WHAT "STATIC" ALREADY MEANS IN THIS REPO, AND WHY THIS IS A DIFFERENT MODULE
-----------------------------------------------------------------------------
Read before writing a line here (this task's own rule 2): `amba_fabric_
discovery.py`/`amba_port_registry.py` establish fabric TOPOLOGY (which master
and slave ports exist, how they are bound); `amba_route_transform_predictor.py`
(SYOSCB-12/13) then predicts, STRUCTURALLY, whether a route exists between a
traced master and slave and whether the topology IMPLIES a transform along it
(ID extension, width conversion, burst split/merge, bridge behavior, ordering
domain -- its own module docstring lists all four already-detected transform
classes; read before assuming a similar concept is new). Every one of those is
computed from the topology as DISCOVERED -- a single, fixed decode/route the
harness read once from RTL/registered evidence. None of it models the fabric's
address decode or route selection as something that can CHANGE while the
design runs, and none of it asks "is this path programmable, and by what".
That is the gap this module closes, and it closes only that gap: it imports
nothing from the AMBA/SyoSil family (`amba_fabric_discovery.py`,
`amba_port_registry.py`, `amba_fabric_analysis.py`, `amba_transaction_ir.py`,
`amba_route_transform_predictor.py`, `amba_scoreboard_env.py`,
`syoscb_compare_policy.py`) and nothing from any other new module built in
this same batch -- the only imports are `dv_harness.connectivity`'s existing,
reused `render_markdown_table()` (this repo's one parameterized table
renderer -- no fourth hand-rolled table loop) and `dv_harness.models.Status`
(a small, stable, unclaimed enum), used solely for the vocabulary-
disjointness check several sibling modules in this project already run
against it.

THE FABRICATION-RISK RULE THIS MODULE EXISTS TO ENFORCE
---------------------------------------------------------
A "reconfigurable"/"dynamic" classification for a given path is asserted ONLY
when the caller-supplied evidence names a REAL controlling mechanism -- e.g. a
specific register field that actually controls address decode or route
selection. It is NEVER inferred from the fabric being an AMBA fabric in
general (a path's declared `protocol` field is carried through purely as
informational context and is never read by the classifier -- proven directly
by a test that drives identical evidence under different declared protocol
strings and asserts byte-identical results), and it is NEVER defaulted to
"static" or "dynamic" when no real evidence names a control mechanism: that
case reports `UNKNOWN_NO_EVIDENCE` instead, honestly, rather than guessing
either answer.

That rule is enforced two layers deep, not merely stated:

1. A caller must supply an actual, cited controlling-mechanism record (a real
   register/field name PLUS a non-empty evidence citation -- an RTL file:line,
   a register programming-guide reference, a spec section) to even be
   CONSIDERED for `RECONFIGURABLE_CONFIRMED`. `ControllingMechanism.
   __post_init__` refuses (raises `DynamicConnectivityIRError`) to construct
   one with an empty register name or an empty/missing evidence citation --
   the same "a rule/fact with no evidence citation is refused outright"
   discipline `security_policy_ir.AccessRule` and `qos_policy_ir` already
   apply to their own domains, applied here to a routing-control claim.
2. A declared mechanism's OWN evidence text must actually SAY it controls
   routing/decode -- a mechanism record whose evidence merely names a register
   without describing what it does (or describes something unrelated, e.g. an
   interrupt-mask field mislabeled as a routing control) is reported
   `UNKNOWN_MECHANISM_NOT_EVIDENCED_AS_ROUTING_CONTROL`, never silently
   promoted to `RECONFIGURABLE_CONFIRMED` on the strength of the caller's own
   label alone. This mirrors `arbitration_policy_ir.classify_arbitration_
   scheme()`'s "a scheme is classified ONLY from real evidence TEXT ... never
   from a component/instance/module NAME alone" discipline, applied to a
   routing-control claim instead of an arbiter scheme.

The symmetric rule holds for the STATIC side too: a caller may explicitly
assert a path has NO reconfiguration mechanism (a real, cited statement that
the decode is hardwired/fixed-function/non-programmable), which reports
`STATIC_CONFIRMED` only when that citation's own text actually says so;
otherwise `UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED`. Declaring BOTH a controlling
mechanism and a static claim for the same path is a genuine, uncited-into-
agreement CONFLICT -- `AMBIGUOUS_CONFLICTING_EVIDENCE`, never resolved by
picking one (the same "this module never picks a winner" boundary
`security_policy_ir.classify_access()` already keeps for a same-specificity
rule conflict).

DELIBERATELY BOUNDED
------------------------
This module classifies a caller-supplied claim about ONE routing path; it
never discovers a fabric's topology or ports itself (that stays the real AMBA
family's job, deliberately not imported here), never predicts a per-
transaction routed value, and never emits SystemVerilog or a bind statement.
It decides, approves, and arbitrates nothing beyond its own classification: no
build, no job, no approval, and there is deliberately no stage gate --
`gates.py`/`cli.py` are untouched, per this task's own file-safety scope. The
front door is `python -m dv_harness.dynamic_connectivity_ir
statuses|classify`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from dv_harness.connectivity import render_markdown_table
from dv_harness.models import Status


class DynamicConnectivityIRError(ValueError):
    """A malformed/uncited controlling-mechanism or static-routing claim, a
    path record missing required identity, or an unrecognised status value --
    raised rather than silently coerced or dropped, per the Evidence Truth
    Rule."""


# ===========================================================================
# Vocabularies
# ===========================================================================

#: The five honest outcomes a path's reconfigurability classification can
#: reach. Exactly two are "resolved" (a real, evidenced answer either way);
#: the other three are all real varieties of "we do not actually know" --
#: kept separate rather than collapsed into one UNKNOWN, because "nobody said
#: anything", "somebody said something but it does not evidence routing
#: control", and "two sides disagree" are three different facts a reviewer
#: needs to see differently.
STATUS_RECONFIGURABLE_CONFIRMED = "RECONFIGURABLE_CONFIRMED"
STATUS_STATIC_CONFIRMED = "STATIC_CONFIRMED"
STATUS_UNKNOWN_NO_EVIDENCE = "UNKNOWN_NO_EVIDENCE"
STATUS_UNKNOWN_MECHANISM_NOT_EVIDENCED = "UNKNOWN_MECHANISM_NOT_EVIDENCED_AS_ROUTING_CONTROL"
STATUS_UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED = "UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED"
STATUS_AMBIGUOUS_CONFLICTING_EVIDENCE = "AMBIGUOUS_CONFLICTING_EVIDENCE"

RECONFIG_STATUS_VALUES: Tuple[str, ...] = (
    STATUS_RECONFIGURABLE_CONFIRMED,
    STATUS_STATIC_CONFIRMED,
    STATUS_UNKNOWN_NO_EVIDENCE,
    STATUS_UNKNOWN_MECHANISM_NOT_EVIDENCED,
    STATUS_UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED,
    STATUS_AMBIGUOUS_CONFLICTING_EVIDENCE,
)

#: The only two statuses this module treats as "resolved" -- a real answer,
#: either way. Every other status honestly means "a human must look at this".
RESOLVED_STATUS_VALUES = frozenset({STATUS_RECONFIGURABLE_CONFIRMED, STATUS_STATIC_CONFIRMED})

#: Literal, case-insensitive phrases a controlling-mechanism's own evidence
#: text must contain at least one of for this module to accept that the
#: mechanism actually controls ADDRESS DECODE / ROUTE SELECTION, rather than
#: merely being A register the caller happened to cite. Deliberately a
#: closed, literal phrase list -- not a keyword/name heuristic -- matching
#: `arbitration_policy_ir.py`'s own "a scheme is classified ONLY from real
#: evidence TEXT ... phrase match, not a keyword/name heuristic" discipline.
#: A differently-worded but equally real statement is honestly reported
#: `UNKNOWN_MECHANISM_NOT_EVIDENCED_AS_ROUTING_CONTROL` rather than guessed
#: via a broader keyword scan -- narrower recognition is the deliberate,
#: disclosed trade for never fabricating a "dynamic" claim the evidence does
#: not actually state.
ROUTING_CONTROL_EVIDENCE_PHRASES: Tuple[str, ...] = (
    "controls address decode",
    "controls the address decode",
    "controls which slave",
    "control which slave",
    "selects the destination slave",
    "selects which slave",
    "select the destination slave",
    "select which slave",
    "remaps the address region",
    "remaps the address window",
    "remap the address region",
    "remap the address window",
    "remaps region",
    "route select",
    "route selection",
    "routing selection",
    "changes which slave",
    "change which slave",
    "reconfigure the decode",
    "reconfigures the decode",
    "reconfigurable address decode",
    "reconfigurable route",
    "programmable address map",
    "programmable address decode",
    "programmable route",
    "programmable routing",
    "redirects the transaction",
    "redirects transactions",
    "redirect the transaction",
    "runtime reconfigurable routing",
    "dynamic address decode",
    "dynamically reconfigure the route",
    "at runtime, this field selects",
    "selects the target slave",
)

#: The symmetric closed phrase list for an explicit STATIC (no reconfiguration
#: mechanism exists) claim. Same discipline: a caller's bare assertion "this is
#: static" is not enough on its own -- the cited evidence text must actually
#: say so.
STATIC_ROUTING_EVIDENCE_PHRASES: Tuple[str, ...] = (
    "hardwired",
    "hard-wired",
    "hard wired",
    "fixed-function decode",
    "fixed function decode",
    "fixed address decode",
    "fixed route",
    "fixed routing",
    "non-programmable",
    "not programmable",
    "not reconfigurable",
    "cannot be changed at runtime",
    "cannot be reconfigured at runtime",
    "no control register",
    "no programmable",
    "no reconfiguration mechanism",
    "decode is fixed",
    "route is fixed",
    "statically determined",
)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own `RECONFIG_STATUS_VALUES` must share no token with
    the real stage verdict vocabulary (`dv_harness.models.Status`). Run at
    import so a future edit that reaches for a `Status` member's spelling
    fails loudly -- the same guard `security_policy_ir.py` and several other
    sibling modules already run against their own vocabularies."""
    status_values = {s.value for s in Status}
    for value in RECONFIG_STATUS_VALUES:
        if value in status_values:
            raise AssertionError(
                f"dynamic_connectivity_ir vocabulary value {value!r} collides with "
                f"dv_harness.models.Status -- pick a different token"
            )


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Controlling-mechanism / static-claim evidence + the classifier
# ===========================================================================

@dataclass
class ControllingMechanism:
    """A caller-declared REAL routing-control mechanism: a specific register
    (and, when known, a specific field within it) whose evidence citation
    claims it controls this path's address decode / route selection.
    `mechanism_kind` is a free-text label (e.g. "ADDRESS_DECODE_REGISTER") --
    purely informational, NEVER consulted by the classifier, because a label
    the caller chose is exactly the kind of self-attested claim the Evidence
    Truth Rule forbids trusting on its own. `evidence` is the REQUIRED,
    non-empty citation (an RTL file:line, a register programming-guide
    reference, a spec section) whose own TEXT is what the classifier actually
    reads."""

    register_name: str
    evidence: str
    field_name: Optional[str] = None
    mechanism_kind: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.register_name, str) or not self.register_name.strip():
            raise DynamicConnectivityIRError(
                "ControllingMechanism.register_name must be a non-empty str -- a routing-"
                "control claim naming no real register is not real evidence"
            )
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise DynamicConnectivityIRError(
                "ControllingMechanism.evidence must be a non-empty citation string -- an "
                "uncited routing-control claim is not real evidence"
            )

    def evidence_text(self) -> str:
        """The full text this classifier reads for a routing-control phrase
        match: the evidence citation plus, when supplied, the caller's own
        `mechanism_kind` label -- so a caller who spells the control fact out
        in a structured `mechanism_kind` (e.g. "route select register that
        selects the destination slave") is not forced to repeat it verbatim
        inside `evidence` too."""
        parts = [self.evidence]
        if self.mechanism_kind:
            parts.append(self.mechanism_kind)
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StaticRoutingClaim:
    """A caller-declared, cited statement that a path's routing is FIXED --
    no reconfiguration mechanism exists. `evidence` is the REQUIRED, non-empty
    citation; same discipline as `ControllingMechanism`, applied to the
    opposite claim."""

    evidence: str
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise DynamicConnectivityIRError(
                "StaticRoutingClaim.evidence must be a non-empty citation string -- an "
                "uncited 'this path is static' claim is not real evidence"
            )

    def evidence_text(self) -> str:
        parts = [self.evidence]
        if self.note:
            parts.append(self.note)
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _matched_phrases(text: str, phrases: Tuple[str, ...]) -> List[str]:
    lowered = text.lower()
    return [p for p in phrases if p in lowered]


@dataclass
class PathReconfigClassification:
    status: str
    reason: str
    matched_phrases: List[str]
    requires_human_review: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_path_reconfigurability(
    controlling_mechanism: Optional[ControllingMechanism] = None,
    static_claim: Optional[StaticRoutingClaim] = None,
) -> PathReconfigClassification:
    """The classifier at the heart of this module's fabrication-risk rule.
    Takes ONLY the two evidence records a caller may supply for one path --
    never a protocol name, a fabric name, or any other identity field, none of
    which this function even accepts a parameter for. Precedence:

    1. BOTH supplied -> `AMBIGUOUS_CONFLICTING_EVIDENCE`. This module never
       picks a winner between a real reconfiguration claim and a real static
       claim for the same path -- that is a genuine, uncited-into-agreement
       conflict a human must resolve, the same boundary
       `security_policy_ir.classify_access()` already keeps for a
       same-specificity rule conflict.
    2. `controlling_mechanism` alone -> its own `evidence_text()` is checked
       against `ROUTING_CONTROL_EVIDENCE_PHRASES`. A match is
       `RECONFIGURABLE_CONFIRMED`; no match is
       `UNKNOWN_MECHANISM_NOT_EVIDENCED_AS_ROUTING_CONTROL` -- a mechanism was
       named, but its own cited text never actually says it controls
       routing/decode, so this module refuses to promote the caller's bare
       label into a confirmed dynamic-routing finding.
    3. `static_claim` alone -> the symmetric check against
       `STATIC_ROUTING_EVIDENCE_PHRASES`: a match is `STATIC_CONFIRMED`, no
       match is `UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED`.
    4. Neither supplied -> `UNKNOWN_NO_EVIDENCE`. This is the module's other
       hard rule made checkable: no real evidence at all NEVER defaults to
       either "static" or "dynamic"."""
    if controlling_mechanism is not None and static_claim is not None:
        return PathReconfigClassification(
            status=STATUS_AMBIGUOUS_CONFLICTING_EVIDENCE,
            reason=(
                "a controlling mechanism AND a static-routing claim were both declared for "
                "this path -- a genuine, uncited-into-agreement conflict; this module never "
                "picks a winner. Mechanism evidence: "
                f"{controlling_mechanism.evidence!r}; static claim evidence: "
                f"{static_claim.evidence!r}."
            ),
            matched_phrases=[],
            requires_human_review=True,
        )

    if controlling_mechanism is not None:
        matched = _matched_phrases(controlling_mechanism.evidence_text(), ROUTING_CONTROL_EVIDENCE_PHRASES)
        if matched:
            return PathReconfigClassification(
                status=STATUS_RECONFIGURABLE_CONFIRMED,
                reason=(
                    f"controlling mechanism {controlling_mechanism.register_name!r}"
                    + (f".{controlling_mechanism.field_name}" if controlling_mechanism.field_name else "")
                    + f" is evidenced as controlling routing/decode (matched: {sorted(matched)}), "
                      f"evidence: {controlling_mechanism.evidence!r}"
                ),
                matched_phrases=sorted(matched),
                requires_human_review=False,
            )
        return PathReconfigClassification(
            status=STATUS_UNKNOWN_MECHANISM_NOT_EVIDENCED,
            reason=(
                f"a controlling mechanism {controlling_mechanism.register_name!r} was declared, "
                f"but its own cited evidence {controlling_mechanism.evidence!r} does not state "
                f"that it controls address decode / route selection -- refusing to promote a "
                f"bare label into a confirmed dynamic-routing finding"
            ),
            matched_phrases=[],
            requires_human_review=True,
        )

    if static_claim is not None:
        matched = _matched_phrases(static_claim.evidence_text(), STATIC_ROUTING_EVIDENCE_PHRASES)
        if matched:
            return PathReconfigClassification(
                status=STATUS_STATIC_CONFIRMED,
                reason=(
                    f"static-routing claim is evidenced (matched: {sorted(matched)}), "
                    f"evidence: {static_claim.evidence!r}"
                ),
                matched_phrases=sorted(matched),
                requires_human_review=False,
            )
        return PathReconfigClassification(
            status=STATUS_UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED,
            reason=(
                f"a static-routing claim was declared, but its own cited evidence "
                f"{static_claim.evidence!r} does not state the decode/route is fixed -- "
                f"refusing to promote a bare label into a confirmed static finding"
            ),
            matched_phrases=[],
            requires_human_review=True,
        )

    return PathReconfigClassification(
        status=STATUS_UNKNOWN_NO_EVIDENCE,
        reason=(
            "no controlling-mechanism evidence and no static-routing claim were supplied for "
            "this path -- never defaulted to static or dynamic; reporting UNKNOWN rather than "
            "guessing"
        ),
        matched_phrases=[],
        requires_human_review=True,
    )


# ===========================================================================
# One path + the whole IR
# ===========================================================================

@dataclass
class DynamicConnectivityPath:
    """One routing path's reconfigurability record. `protocol` is carried
    through purely as informational context for a human reading the report --
    it is NEVER read by `classify_path_reconfigurability()`, proven directly
    by a dedicated test driving identical evidence under different declared
    `protocol` strings."""

    path_id: str
    master: str
    slave_or_region: str
    protocol: Optional[str] = None
    controlling_mechanism: Optional[ControllingMechanism] = None
    static_claim: Optional[StaticRoutingClaim] = None
    classification: PathReconfigClassification = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (("path_id", self.path_id), ("master", self.master),
                            ("slave_or_region", self.slave_or_region)):
            if not isinstance(value, str) or not value.strip():
                raise DynamicConnectivityIRError(
                    f"DynamicConnectivityPath.{name} must be a non-empty str, got {value!r}"
                )
        self.classification = classify_path_reconfigurability(
            self.controlling_mechanism, self.static_claim,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "master": self.master,
            "slave_or_region": self.slave_or_region,
            "protocol": self.protocol,
            "controlling_mechanism": self.controlling_mechanism.to_dict() if self.controlling_mechanism else None,
            "static_claim": self.static_claim.to_dict() if self.static_claim else None,
            "classification": self.classification.to_dict(),
        }

    def to_row(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "master": self.master,
            "slave_or_region": self.slave_or_region,
            "protocol": self.protocol or "",
            "status": self.classification.status,
            "requires_human_review": self.classification.requires_human_review,
            "reason": self.classification.reason,
        }


def _build_controlling_mechanism(raw: Optional[Dict[str, Any]]) -> Optional[ControllingMechanism]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DynamicConnectivityIRError(f"controlling_mechanism must be a dict or null, got {type(raw).__name__!r}")
    return ControllingMechanism(
        register_name=raw.get("register_name"),
        evidence=raw.get("evidence"),
        field_name=raw.get("field_name"),
        mechanism_kind=raw.get("mechanism_kind"),
    )


def _build_static_claim(raw: Optional[Dict[str, Any]]) -> Optional[StaticRoutingClaim]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DynamicConnectivityIRError(f"static_claim must be a dict or null, got {type(raw).__name__!r}")
    return StaticRoutingClaim(evidence=raw.get("evidence"), note=raw.get("note"))


def build_dynamic_connectivity_paths(path_specs: List[Dict[str, Any]]) -> List[DynamicConnectivityPath]:
    """Build a list of `DynamicConnectivityPath` from plain rule dicts (the
    duck-typed real-evidence input this task requires). Each dict's
    recognised keys are `path_id`/`master`/`slave_or_region`/`protocol`/
    `controlling_mechanism`/`static_claim`; a required identity field or an
    uncited evidence record raises `DynamicConnectivityIRError` naming the
    offending index."""
    if not isinstance(path_specs, list):
        raise DynamicConnectivityIRError(f"path_specs must be a list of dicts, got {type(path_specs).__name__!r}")
    built: List[DynamicConnectivityPath] = []
    for idx, raw in enumerate(path_specs):
        if not isinstance(raw, dict):
            raise DynamicConnectivityIRError(f"path_specs[{idx}] must be a dict, got {type(raw).__name__!r}")
        try:
            built.append(DynamicConnectivityPath(
                path_id=raw.get("path_id"),
                master=raw.get("master"),
                slave_or_region=raw.get("slave_or_region"),
                protocol=raw.get("protocol"),
                controlling_mechanism=_build_controlling_mechanism(raw.get("controlling_mechanism")),
                static_claim=_build_static_claim(raw.get("static_claim")),
            ))
        except DynamicConnectivityIRError as exc:
            raise DynamicConnectivityIRError(f"path_specs[{idx}]: {exc}") from exc
    return built


@dataclass
class DynamicConnectivityIR:
    """The whole model: every declared path plus its classification. Nothing
    here is derived from a fabric topology this module never reads -- every
    path is exactly what the caller supplied."""

    paths: List[DynamicConnectivityPath] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"paths": [p.to_dict() for p in self.paths]}

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {status: 0 for status in RECONFIG_STATUS_VALUES}
        for p in self.paths:
            counts[p.classification.status] = counts.get(p.classification.status, 0) + 1
        return {
            "total_paths": len(self.paths),
            "counts_by_status": counts,
            "requires_human_review_count": sum(1 for p in self.paths if p.classification.requires_human_review),
        }

    def render_markdown(self) -> str:
        columns = [
            ("path_id", "Path"), ("master", "Master"), ("slave_or_region", "Slave/Region"),
            ("protocol", "Protocol"), ("status", "Status"),
            ("requires_human_review", "Needs Human Review"), ("reason", "Reason"),
        ]
        rows = [p.to_row() for p in self.paths]
        return render_markdown_table(columns, rows, empty_note="(no dynamic-connectivity paths declared)")


def build_dynamic_connectivity_ir(path_specs: List[Dict[str, Any]]) -> DynamicConnectivityIR:
    return DynamicConnectivityIR(paths=build_dynamic_connectivity_paths(path_specs))


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py is out of this task's scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    parser = argparse.ArgumentParser(prog="dynamic_connectivity_ir")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("statuses", help="list the reconfigurability-status vocabulary")

    p_classify = sub.add_parser("classify", help="classify every declared path in a JSON path-spec file")
    p_classify.add_argument("--paths", required=True, help="path to a JSON file of {paths: [...]} or a bare list")
    p_classify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "statuses":
        result = {"statuses": list(RECONFIG_STATUS_VALUES), "resolved": sorted(RESOLVED_STATUS_VALUES)}
        return 0, result, json.dumps(result, indent=2)

    with open(args.paths, "r", encoding="utf-8") as f:
        doc = json.load(f)
    path_specs = doc.get("paths", doc) if isinstance(doc, dict) else doc
    try:
        ir = build_dynamic_connectivity_ir(path_specs)
    except DynamicConnectivityIRError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    result = ir.to_dict()
    result["summary"] = ir.summary()
    if args.json:
        text = json.dumps(result, indent=2)
    else:
        text = ir.render_markdown() + "\n\n" + json.dumps(ir.summary(), indent=2)
    exit_code = 0 if result["summary"]["requires_human_review_count"] == 0 else 1
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
