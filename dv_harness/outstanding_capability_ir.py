"""dv_harness/outstanding_capability_ir.py -- a MORE GRANULAR, standalone structured
breakdown of AMBA outstanding-transaction capability limits, deliberately NOT a replacement
for the flat `outstanding` dimension already modeled in Batch 9's
`amba_master_slave_constraint_ir.py`.

WHY THIS EXISTS ALONGSIDE THE EXISTING `outstanding` DIMENSION
---------------------------------------------------------------
`amba_master_slave_constraint_ir.py` (read read-only before writing this module) models
`outstanding` as ONE of its six fixed protocol-legal/DUT-capability/scenario-constraint
dimensions -- a single flat notion of "how many outstanding transactions are legal/confirmed"
per the three-layer model that module builds. It never asks the more granular questions a
real fabric/port capability model needs answered separately:

  - is the limit different for READS vs WRITES (`read_max` vs `write_max`)?
  - is there a PER-ID limit (how many outstanding transactions a single AXI ID may have)
    distinct from a GLOBAL limit (how many outstanding transactions the whole master/port
    may have in flight at once, across all IDs)?
  - what does the SLAVE side accept (`slave_accept_limit` -- a slave's own outstanding-
    request acceptance capacity, which can differ from what a master is capable of issuing)?
  - what does the FABRIC itself impose (`fabric_limit` -- an interconnect-wide ceiling that
    can be tighter than any single master's or slave's own limit)?
  - what does an intervening BRIDGE impose (`bridge_limit` -- a width-conversion/protocol-
    bridge stage frequently caps outstanding depth independently of either endpoint; see
    `amba_route_transform_predictor.py`'s already-real bridge-behavior detection, which this
    module does NOT import or re-derive -- it only reserves a field a caller populates
    independently once that or any other analysis confirms a bridge exists on the path).

THIS MODULE IS A STANDALONE STRUCTURE, NOT A CONSUMER OF THE ABOVE MODULE
--------------------------------------------------------------------------
Per this batch's strict file-safety scope, this module does NOT import
`amba_master_slave_constraint_ir.py` (or any other new module from this or any other
in-flight batch). A caller who already has BOTH IRs may cross-reference them at the call
site (e.g. treat this module's finer-grained fields as a REFINEMENT of that module's flat
`outstanding` dimension for the same master/slave pair) -- this module performs no such
cross-reference itself, and accepts no object from that module as an input. Every field
here is populated independently by a caller, exactly like every existing IR in this project
that models a DUT/fabric capability from real evidence.

EVERY FIELD DEFAULTS TO UNKNOWN/NOT_AVAILABLE -- NEVER A GUESSED LIMIT
------------------------------------------------------------------------
This is the one hard rule this module exists to enforce, mirroring
`amba_master_slave_constraint_ir.py`'s own DUT-capability discipline: a numeric outstanding
limit is a claim about real hardware/fabric behavior, and this module refuses to invent one.
Every one of the seven granular fields (`read_max`, `write_max`, `per_id_limit`,
`global_limit`, `slave_accept_limit`, `fabric_limit`, `bridge_limit`) is `None` (reported as
the sentinel status `OUTSTANDING_CAPABILITY_UNKNOWN`) unless the caller supplies BOTH a real
integer value AND a non-empty evidence citation (a real RTL parameter/register field, a
spec/programming-guide citation, or an explicit human confirmation) for that specific field.
A field supplied with a value but no citation is REFUSED at construction time
(`OutstandingCapabilityIRError`) rather than silently accepted -- an uncited numeric limit is
exactly the unsupported claim the Evidence Truth Rule forbids. `NOT_AVAILABLE` (distinct from
`UNKNOWN`) is used when a caller explicitly states evidence was sought and genuinely could
not be obtained for a field (e.g. "no register documents this bridge's own outstanding
cap"), which is a stronger, more informative statement than a field simply never having been
asked about -- `UNKNOWN` and `NOT_AVAILABLE` are kept honestly distinct rather than
collapsed into one word, the same discipline several sibling IRs in this project already
apply (e.g. `register_rtl_trace.py`'s `TRACE_NOT_FOUND` vs `BLOCKED`).

PHASE-1 ONLY
------------
This module builds a structured capability record a human/generator reads. It runs no
build, no simulation, and mints no approval; there is deliberately no stage gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class OutstandingCapabilityError(Exception):
    """A capability record this module refuses to build: a numeric field supplied with no
    real evidence citation, or a malformed/unrecognized field name."""

    def __init__(self, code: str, detail=None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


# ===========================================================================
# Status vocabulary -- three honestly distinct states, never collapsed
# ===========================================================================

#: No evidence was ever supplied for this field. The default state of every field.
STATUS_UNKNOWN = "OUTSTANDING_CAPABILITY_UNKNOWN"

#: Evidence was genuinely sought for this field and none could be found/confirmed.
#: Distinct from STATUS_UNKNOWN: this is a stronger, more informative negative --
#: "we looked and could not confirm a value" rather than "nobody has asked yet".
STATUS_NOT_AVAILABLE = "OUTSTANDING_CAPABILITY_NOT_AVAILABLE"

#: A real, cited numeric value was confirmed for this field.
STATUS_CONFIRMED = "OUTSTANDING_CAPABILITY_CONFIRMED"

ALL_STATUSES = (STATUS_UNKNOWN, STATUS_NOT_AVAILABLE, STATUS_CONFIRMED)

#: The seven granular outstanding-capability dimensions this IR models, in a fixed order.
#: A tuple because it is the contract every field-level operation is validated against.
FIELD_NAMES: tuple = (
    "read_max",
    "write_max",
    "per_id_limit",
    "global_limit",
    "slave_accept_limit",
    "fabric_limit",
    "bridge_limit",
)

#: Real evidence source kinds this module accepts for a CONFIRMED field. A caller citing an
#: unrecognized source kind is refused rather than silently accepted -- the same discipline
#: `amba_master_slave_constraint_ir.py`'s DUT-capability evidence acceptance already applies
#: (there, specifically to forbid VIP-sourced "confirmation"; here, generalized to any
#: recognizable real-evidence kind).
RECOGNIZED_EVIDENCE_KINDS = (
    "rtl_parameter",
    "rtl_port",
    "register_map",
    "register_field",
    "spec_document",
    "programming_guide",
    "human_confirmation",
)


@dataclass(frozen=True)
class OutstandingCapabilityField:
    """One granular outstanding-capability field: its status, its value (only when
    CONFIRMED), and the evidence that confirmed it (only when CONFIRMED)."""

    name: str
    status: str = STATUS_UNKNOWN
    value: Optional[int] = None
    evidence: Optional[str] = None
    evidence_kind: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "evidence": self.evidence,
            "evidence_kind": self.evidence_kind,
            "reason": self.reason,
        }


def _build_unknown_field(name: str) -> OutstandingCapabilityField:
    return OutstandingCapabilityField(name=name, status=STATUS_UNKNOWN, value=None,
                                       evidence=None, evidence_kind=None, reason=None)


def _build_not_available_field(name: str, reason: str) -> OutstandingCapabilityField:
    if not reason or not str(reason).strip():
        raise OutstandingCapabilityError(
            "NOT_AVAILABLE_REASON_MISSING",
            {"field": name,
             "message": ("A field marked NOT_AVAILABLE must carry a real, non-empty "
                         "reason explaining what was sought and why it could not be "
                         "confirmed -- never a bare NOT_AVAILABLE with no explanation.")},
        )
    return OutstandingCapabilityField(name=name, status=STATUS_NOT_AVAILABLE, value=None,
                                       evidence=None, evidence_kind=None,
                                       reason=str(reason).strip())


def _build_confirmed_field(name: str, value, evidence: str,
                            evidence_kind: str) -> OutstandingCapabilityField:
    if not isinstance(value, int) or isinstance(value, bool):
        raise OutstandingCapabilityError(
            "CONFIRMED_VALUE_NOT_INTEGER",
            {"field": name, "value": value,
             "message": "A confirmed outstanding-capability limit must be a real integer."},
        )
    if value < 0:
        raise OutstandingCapabilityError(
            "CONFIRMED_VALUE_NEGATIVE",
            {"field": name, "value": value,
             "message": "A confirmed outstanding-capability limit cannot be negative."},
        )
    if not evidence or not str(evidence).strip():
        raise OutstandingCapabilityError(
            "CONFIRMED_WITH_NO_EVIDENCE",
            {"field": name, "value": value,
             "message": ("A numeric outstanding-capability limit was supplied with no "
                         "evidence citation. This is exactly the unsupported claim the "
                         "Evidence Truth Rule forbids -- never guess a limit.")},
        )
    if evidence_kind not in RECOGNIZED_EVIDENCE_KINDS:
        raise OutstandingCapabilityError(
            "UNRECOGNIZED_EVIDENCE_KIND",
            {"field": name, "evidence_kind": evidence_kind,
             "recognized_kinds": RECOGNIZED_EVIDENCE_KINDS,
             "message": ("Evidence kind is not one of this module's recognized real "
                         "evidence sources; refusing to confirm a limit from an "
                         "unrecognized source kind.")},
        )
    return OutstandingCapabilityField(name=name, status=STATUS_CONFIRMED, value=value,
                                       evidence=str(evidence).strip(),
                                       evidence_kind=evidence_kind, reason=None)


@dataclass(frozen=True)
class OutstandingCapabilityIR:
    """A structured, per-field outstanding-transaction capability record over seven
    granular dimensions: read_max, write_max, per_id_limit, global_limit,
    slave_accept_limit, fabric_limit, bridge_limit.

    Every field is an `OutstandingCapabilityField` defaulting to UNKNOWN. Build one via
    `build_outstanding_capability_ir()` rather than constructing this dataclass directly,
    so every field passes through the same validation.
    """

    read_max: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("read_max"))
    write_max: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("write_max"))
    per_id_limit: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("per_id_limit"))
    global_limit: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("global_limit"))
    slave_accept_limit: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("slave_accept_limit"))
    fabric_limit: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("fabric_limit"))
    bridge_limit: OutstandingCapabilityField = field(
        default_factory=lambda: _build_unknown_field("bridge_limit"))

    #: Optional identity labels, purely informational -- never consulted by any
    #: classification logic in this module.
    master_name: Optional[str] = None
    slave_name: Optional[str] = None
    fabric_name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "master_name": self.master_name,
            "slave_name": self.slave_name,
            "fabric_name": self.fabric_name,
            "fields": {name: getattr(self, name).to_dict() for name in FIELD_NAMES},
        }

    def field_by_name(self, name: str) -> OutstandingCapabilityField:
        if name not in FIELD_NAMES:
            raise OutstandingCapabilityError(
                "UNKNOWN_FIELD_NAME",
                {"name": name, "known_fields": FIELD_NAMES},
            )
        return getattr(self, name)

    def confirmed_fields(self) -> tuple:
        """Names of every field currently CONFIRMED, in FIELD_NAMES order."""
        return tuple(n for n in FIELD_NAMES if getattr(self, n).status == STATUS_CONFIRMED)

    def unknown_fields(self) -> tuple:
        """Names of every field currently UNKNOWN (never asked about), in FIELD_NAMES order."""
        return tuple(n for n in FIELD_NAMES if getattr(self, n).status == STATUS_UNKNOWN)

    def not_available_fields(self) -> tuple:
        """Names of every field currently NOT_AVAILABLE (asked about, not confirmable),
        in FIELD_NAMES order."""
        return tuple(n for n in FIELD_NAMES
                     if getattr(self, n).status == STATUS_NOT_AVAILABLE)


def build_outstanding_capability_ir(field_inputs: Optional[dict] = None,
                                     master_name: Optional[str] = None,
                                     slave_name: Optional[str] = None,
                                     fabric_name: Optional[str] = None
                                     ) -> OutstandingCapabilityIR:
    """Build an OutstandingCapabilityIR from a caller-supplied, per-field input mapping.

    `field_inputs` is an optional `{field_name: spec}` mapping. Any field name absent from
    it defaults to UNKNOWN. `field_name` must be one of `FIELD_NAMES`; an unrecognized key
    raises `OutstandingCapabilityError`.

    Each `spec` is one of:
      - `None`, or the literal string `"UNKNOWN"` -- the field stays UNKNOWN.
      - `{"status": "NOT_AVAILABLE", "reason": "<why this could not be confirmed>"}`
      - `{"value": <int>, "evidence": "<citation>", "evidence_kind": "<one of
         RECOGNIZED_EVIDENCE_KINDS>"}` -- confirms the field. Missing/invalid evidence or an
         unrecognized evidence_kind raises rather than silently defaulting.

    No field is ever guessed: a caller who has no evidence for a field should simply omit
    it (or pass `None`), leaving it honestly UNKNOWN.
    """
    if field_inputs is None:
        field_inputs = {}
    if not isinstance(field_inputs, dict):
        raise OutstandingCapabilityError(
            "FIELD_INPUTS_NOT_A_MAPPING",
            {"type": type(field_inputs).__name__},
        )

    unknown_keys = set(field_inputs.keys()) - set(FIELD_NAMES)
    if unknown_keys:
        raise OutstandingCapabilityError(
            "UNKNOWN_FIELD_NAME",
            {"unknown_keys": sorted(unknown_keys), "known_fields": FIELD_NAMES},
        )

    built = {}
    for name in FIELD_NAMES:
        spec = field_inputs.get(name)
        if spec is None or spec == "UNKNOWN":
            built[name] = _build_unknown_field(name)
            continue
        if not isinstance(spec, dict):
            raise OutstandingCapabilityError(
                "MALFORMED_FIELD_SPEC",
                {"field": name, "type": type(spec).__name__,
                 "message": ("A field spec must be None, the literal string 'UNKNOWN', or "
                             "a dict with either a NOT_AVAILABLE reason or a confirmed "
                             "value+evidence+evidence_kind.")},
            )
        status = spec.get("status")
        if status == STATUS_NOT_AVAILABLE or status == "NOT_AVAILABLE":
            built[name] = _build_not_available_field(name, spec.get("reason"))
            continue
        if "value" in spec or "evidence" in spec or "evidence_kind" in spec:
            built[name] = _build_confirmed_field(
                name, spec.get("value"), spec.get("evidence"), spec.get("evidence_kind"),
            )
            continue
        raise OutstandingCapabilityError(
            "MALFORMED_FIELD_SPEC",
            {"field": name, "spec": spec,
             "message": ("Field spec dict recognized neither a NOT_AVAILABLE status nor a "
                         "confirmed value/evidence/evidence_kind triple.")},
        )

    return OutstandingCapabilityIR(
        read_max=built["read_max"],
        write_max=built["write_max"],
        per_id_limit=built["per_id_limit"],
        global_limit=built["global_limit"],
        slave_accept_limit=built["slave_accept_limit"],
        fabric_limit=built["fabric_limit"],
        bridge_limit=built["bridge_limit"],
        master_name=master_name,
        slave_name=slave_name,
        fabric_name=fabric_name,
    )


def render_outstanding_capability_markdown(ir: OutstandingCapabilityIR) -> str:
    """Render a small markdown table of every field's status/value/evidence, reusing
    `dv_harness.connectivity.render_markdown_table` -- this repo's one parameterized table
    renderer -- rather than a second hand-rolled table loop. Imported lazily so this module
    stays importable even in a stripped-down environment missing that dependency chain."""
    from dv_harness.connectivity import render_markdown_table

    columns = [
        ("field", "Field"),
        ("status", "Status"),
        ("value", "Value"),
        ("evidence", "Evidence"),
        ("evidence_kind", "Evidence Kind"),
        ("reason", "Reason"),
    ]
    rows = []
    for name in FIELD_NAMES:
        f = ir.field_by_name(name)
        rows.append({
            "field": name,
            "status": f.status,
            "value": "" if f.value is None else str(f.value),
            "evidence": f.evidence or "",
            "evidence_kind": f.evidence_kind or "",
            "reason": f.reason or "",
        })
    return render_markdown_table(columns, rows)
