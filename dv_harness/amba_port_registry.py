"""dv_harness/amba_port_registry.py -- AMBA-22: the AMBA_PORT_REGISTRY.

One row per discovered fabric port, carrying the nineteen columns AMBA-22
mandates, assembled by JOINING facts real mechanisms already produced -- never
by re-deriving any of them a second way:

  AMBA-16 matrix row (`amba_fabric_discovery.build_fabric_vip_bind_matrix`)
      fabric_port, protocol, fabric_role, endpoint_role, endpoint_hierarchy,
      vip_bind_hierarchy, clock, reset, trace_status, readiness, confidence
  AMBA-15 validation (`validate_vip_bind_location`, carried on that same row)
      address_width, data_width, id_width, user_widths, source_evidence
  AMBA-20 VIP plan (`build_vip_instance_plan`)
      vip_mode
  AMBA-21 ingress map (`amba_scoreboard_env.map_vip_monitors_to_...`)
      scoreboard_channel

Because every field is READ OFF those artifacts rather than recomputed, a
registry row cannot disagree with the matrix row, the checklist or the VIP plan
a human reviewed at AMBA-16..21. That is the whole point of building it here
instead of tracing the netlist a second time.

SCHEMA COMPATIBILITY, NOT A COMPETING SCHEMA
--------------------------------------------
`project_to_fabric_topology()` projects the registry DOWN into the exact
top-level shape `tools/verification_flow/fabric_topology_completeness_gate.py`
already validates (`masters` / `slaves` / `scoreboard_matrix` / `address_map`),
using `uvm_generator/amba_fabric_generator.py`'s own
`build_scoreboard_matrix()` and `compute_address_regions()` for the two
computed halves. The registry is a strict SUPERSET of that document -- it adds
per-port protocol, clock, reset, widths, readiness, confidence and evidence the
gate does not model -- so the projection loses information deliberately and in
one direction only. No second topology schema is introduced.

DISCOVERY AND PLANNING ONLY (AMBA-30 / AMBA-31)
-----------------------------------------------
`vip_bind_hierarchy` is a proposed LOCATION string a human reviews. Nothing in
this module emits, renders or implies a SystemVerilog `bind` statement, and
`amba_fabric_discovery.assert_no_bind_statement()` is run over this module's
own rendered report for the same reason it is run over AMBA-16..20's.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from dv_harness import amba_fabric_discovery as afd
from dv_harness.amba_fabric_discovery import (
    BIND_CHECK_UNKNOWN_VALUE,
    BIND_READINESS_VALUES,
    FabricDiscoveryError,
    MULTIPLE_BRANCH_PARENT_BIND,
    TraceTerminationStatus,
    assert_no_bind_statement,
    parent_matrix_rows,
)
from dv_harness.amba_scoreboard_env import scoreboard_channel_by_vip_id
from dv_harness.connectivity import (
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    FABRIC_SIDE_MASTER_INTERFACE,
    FABRIC_SIDE_SLAVE_INTERFACE,
    REQUIRED_HUMAN_INPUT,
    render_markdown_table,
)
from dv_harness.uvm_generator.amba_fabric_generator import (
    AddressMapError,
    build_scoreboard_matrix,
    compute_address_regions,
)


class PortRegistryError(FabricDiscoveryError):
    """An AMBA_PORT_REGISTRY that is internally incomplete or that violates
    AMBA-22's own naming rule. Subclasses `FabricDiscoveryError` so a caller
    already handling the discovery pipeline's errors handles these too."""


#: AMBA-22's nineteen fields, in the doc's own order. The tuple is the
#: contract: rows are built by iterating it and `assert_registry_complete()`
#: checks against it, so a field cannot be quietly dropped from either end.
AMBA_PORT_REGISTRY_FIELDS: tuple = (
    "port_id",
    "fabric_port",
    "protocol",
    "fabric_role",
    "endpoint_role",
    "endpoint_hierarchy",
    "vip_bind_hierarchy",
    "vip_mode",
    "clock",
    "reset",
    "address_width",
    "data_width",
    "id_width",
    "user_widths",
    "scoreboard_channel",
    "trace_status",
    "readiness",
    "confidence",
    "source_evidence",
)

#: The AMBA-15 check whose VALUE fills each width column. Named here so the
#: registry cannot drift from the checklist a human approved: change the check
#: and this mapping fails loudly rather than silently reading a missing key.
_WIDTH_FIELD_TO_CHECK: dict = {
    "address_width": "address_width_known",
    "data_width": "data_width_known",
    "id_width": "id_width_known",
    "user_widths": "user_width_known",
}

#: `vip_mode` of a port for which AMBA-20 planned no VIP instance -- a port with
#: no validated bind location, or an AMBA-11 downstream side recorded but
#: deliberately not proposed. A real value, not a blank: "no VIP is planned
#: here" is a finding a reviewer must see, and an empty cell reads as an
#: oversight.
VIP_MODE_NOT_PLANNED = "NO_VIP_PLANNED"

#: What `endpoint_hierarchy` carries when the trace established none. AMBA-14's
#: own rule ("Never invent endpoint hierarchy") makes this mandatory: the cell
#: names the trace status instead of a path.
ENDPOINT_HIERARCHY_NOT_ESTABLISHED = "ENDPOINT_NOT_ESTABLISHED"

#: The only two statuses that establish a real transaction endpoint. Everything
#: else -- a bridge crossing, a blocked or ambiguous trace, the parent row of a
#: multiple-source/destination port -- leaves the endpoint open. Spelled as
#: `.value` strings because a registry row carries strings, including one
#: re-loaded from a persisted JSON registry.
_ENDPOINT_ESTABLISHED_STATUSES: frozenset = frozenset({
    TraceTerminationStatus.SOURCE_FOUND.value,
    TraceTerminationStatus.DESTINATION_FOUND.value,
})

#: AMBA-22: "Do not hardcode generic master0/master1/slave0/slave1 unless
#: project conventions demand them." Enforced by
#: `assert_no_generic_port_ids()`; the escape hatch is an explicit argument, so
#: a project convention is a decision someone made rather than a default.
_GENERIC_PORT_ID_RE = re.compile(r"^(?:master|slave|mst|slv|m|s)\d+$", re.IGNORECASE)

_PORT_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9]+")


def _port_id(row: dict) -> str:
    """A stable port id derived from the port's REAL hierarchical interface id
    (`u_fabric:S00_AXI_`), never a positional counter.

    That is the direct implementation of AMBA-22's naming rule: a registry keyed
    on `master0`/`master1` loses the one fact that makes a row traceable back to
    the RTL, and re-ordering the discovery would silently renumber every row."""
    raw = str(row.get("row_id") or row.get("fabric_port") or "")
    return _PORT_ID_SAFE_RE.sub("_", raw).strip("_").upper() or "PORT_UNIDENTIFIED"


def _source_evidence(row: dict) -> list:
    """Where every fact in this row came from, as citable strings.

    The AMBA-15 checklist's own per-check evidence is reused verbatim rather
    than re-worded: the registry must cite the same sentences the reviewer read
    on the checklist, or the two artifacts drift the moment either is edited."""
    out = [f"AMBA-16 matrix row {row.get('row_id')}",
           f"trace status {row.get('trace_status')}"]
    validation = row.get("validation")
    if validation is not None:
        out.append(f"AMBA-15 bind location validation of {validation.instance_path}:"
                   f"{validation.bundle_prefix} [{validation.readiness}]")
        out += [f"point {c.point} {c.key}={c.status}: {c.evidence}"
                for c in validation.checks]
    return out


def _endpoint_hierarchy(row: dict) -> str:
    """AMBA-22's `endpoint_hierarchy` column, and the one place AMBA-14's
    "Never invent endpoint hierarchy" is enforced for the registry.

    A blocked or ambiguous branch DOES carry an instance path -- the last known
    hierarchy where the trace stopped, which AMBA-17's unresolved table reports
    as exactly that. Copying it into `endpoint_hierarchy` would turn "we got as
    far as u_opaque and could see no further" into "u_opaque is the endpoint",
    which is a different and unsupported claim. So the column is filled ONLY
    from a trace that really established an endpoint; the last-known path is
    kept beside it under its own name."""
    if row.get("trace_status") not in _ENDPOINT_ESTABLISHED_STATUSES:
        return ENDPOINT_HIERARCHY_NOT_ESTABLISHED
    return row.get("endpoint_instance_path") or ENDPOINT_HIERARCHY_NOT_ESTABLISHED


def build_amba_port_registry(netlist, traces, plan=None, ingress_mapping=None) -> list:
    """AMBA-22's registry, assembled from one already-computed AMBA-15..21 pass.

    `plan` is an `amba_fabric_discovery.VipBindPlan`; when omitted it is
    computed here so a caller with only traces still gets a registry, but a
    caller that already built the review artifact should pass its own plan --
    rebuilding would produce a second, separately-computed set of rows that
    could differ from the one a human actually reviewed.

    `ingress_mapping` is AMBA-21's VIP-monitor-to-scoreboard-ingress table. With
    no mapping supplied, `scoreboard_channel` is `REQUIRED_HUMAN_INPUT` on every
    row -- which is the truth: nothing has established where these monitors
    would feed."""
    plan = plan if plan is not None else afd.build_vip_bind_plan(netlist, traces)
    vip_by_source_row = {v.get("source_row_id"): v for v in plan.vip_instances}
    channels = scoreboard_channel_by_vip_id(ingress_mapping)

    rows: list = []
    seen: dict = {}
    for row in plan.matrix:
        port_id = _port_id(row)
        if port_id in seen:
            raise PortRegistryError("AMBA_PORT_REGISTRY_DUPLICATE_PORT_ID", {
                "port_id": port_id, "first_row": seen[port_id],
                "second_row": row.get("row_id"),
                "hint": "two matrix rows produced the same port_id; the registry is keyed "
                        "on it and a collision would silently merge two fabric ports"})
        seen[port_id] = row.get("row_id")
        vip = vip_by_source_row.get(row.get("row_id"))
        validation = row.get("validation")
        entry = {
            "port_id": port_id,
            "fabric_port": row.get("fabric_port"),
            "protocol": row.get("protocol"),
            "fabric_role": row.get("fabric_role"),
            "endpoint_role": row.get("external_endpoint_role"),
            "endpoint_hierarchy": _endpoint_hierarchy(row),
            "vip_bind_hierarchy": row.get("proposed_vip_bind_hierarchy"),
            "vip_mode": vip["vip_mode"] if vip else VIP_MODE_NOT_PLANNED,
            "clock": row.get("clock") or BIND_CHECK_UNKNOWN_VALUE,
            "reset": row.get("reset") or BIND_CHECK_UNKNOWN_VALUE,
            "scoreboard_channel": (channels.get(vip["vip_id"]) if vip
                                   else REQUIRED_HUMAN_INPUT) or REQUIRED_HUMAN_INPUT,
            "trace_status": row.get("trace_status"),
            "readiness": row.get("status"),
            "confidence": row.get("confidence"),
            "source_evidence": _source_evidence(row),
            # Beyond the nineteen columns: the join keys back to the artifacts
            # this row was assembled from, so a reviewer can walk from a
            # registry row to the matrix row and checklist it came from.
            "row_id": row.get("row_id"),
            "parent_row_id": row.get("parent_row_id"),
            "vip_id": vip["vip_id"] if vip else None,
            "amba11_second_side": bool(row.get("amba11_second_side")),
            "last_known_hierarchy": row.get("endpoint_instance_path") or "",
        }
        for field, check_key in _WIDTH_FIELD_TO_CHECK.items():
            entry[field] = (validation.value_of(check_key) if validation is not None
                            else BIND_CHECK_UNKNOWN_VALUE)
        rows.append(entry)
    assert_registry_complete(rows)
    return rows


def assert_registry_complete(rows) -> None:
    """Every one of AMBA-22's nineteen fields present and non-empty on every
    row.

    A registry is what "drives later VIP/UVM construction"; a row with a silently
    absent column is how a downstream consumer ends up defaulting a width or a
    clock it was never given. An unknown value must be a visible
    `UNKNOWN`/`REQUIRED_HUMAN_INPUT`, never a missing key."""
    for row in rows or ():
        missing = [f for f in AMBA_PORT_REGISTRY_FIELDS
                   if f not in row or row[f] in (None, "", [])]
        if missing:
            raise PortRegistryError("AMBA_PORT_REGISTRY_INCOMPLETE_ROW", {
                "port_id": row.get("port_id"), "missing_fields": missing,
                "hint": "every AMBA-22 field must carry a real value; use the explicit "
                        "UNKNOWN / REQUIRED_HUMAN_INPUT sentinels rather than omitting a "
                        "column"})
        if row["readiness"] not in BIND_READINESS_VALUES:
            raise PortRegistryError("AMBA_PORT_REGISTRY_UNKNOWN_READINESS", {
                "port_id": row.get("port_id"), "readiness": row["readiness"],
                "allowed": list(BIND_READINESS_VALUES)})


def assert_no_generic_port_ids(rows, *, project_convention_allows_generic: bool = False) -> None:
    """AMBA-22: "Do not hardcode generic master0/master1/slave0/slave1 unless
    project conventions demand them."

    The exception is a parameter a caller must pass deliberately, not a default:
    an id like `master0` carries no way back to the RTL, and a registry that
    quietly renumbers when discovery order changes is worse than one that
    refuses to build."""
    if project_convention_allows_generic:
        return
    offenders = [r.get("port_id") for r in rows or ()
                 if _GENERIC_PORT_ID_RE.match(str(r.get("port_id") or ""))]
    if offenders:
        raise PortRegistryError("AMBA_PORT_REGISTRY_GENERIC_PORT_ID", {
            "port_ids": offenders,
            "hint": "derive port_id from the real hierarchical interface id; pass "
                    "project_convention_allows_generic=True only when the project's own "
                    "convention genuinely demands master0/slave0 naming"})


# ===========================================================================
# Projection into fabric_topology_completeness_gate.py's schema
# ===========================================================================

def registry_endpoints(rows) -> dict:
    """`{"masters": [...], "slaves": [...], "unresolved": [...]}` from the
    registry alone.

    A port on the fabric's SLAVE_INTERFACE is fed BY a master, so its endpoint
    goes in `masters`; a MASTER_INTERFACE port drives a slave. The endpoint's
    own AMBA-5 role is used when it resolved, and the fabric-side role is the
    fallback -- the two are opposite perspectives on the same link, never
    independent facts. A row whose trace never established an endpoint
    contributes to `unresolved`, so a topology built from this can never claim
    a master nobody traced."""
    masters, slaves, unresolved = [], [], []
    for row in rows or ():
        # An AMBA-11 second-side row records the far side of a bridge as
        # EVIDENCE; what lies beyond that bridge is a separate trace, so
        # counting the bridge itself as an endpoint would invent one.
        if row.get("amba11_second_side"):
            continue
        # The parent row of a multiple-source/destination port enumerates no
        # endpoint of its own -- its child branch rows carry the real ones.
        # Counting it would double-count the port, and listing it as
        # unresolved would report a port its branches DID resolve as open.
        if row.get("vip_bind_hierarchy") == MULTIPLE_BRANCH_PARENT_BIND:
            continue
        path = row.get("endpoint_hierarchy")
        if (not path or path == ENDPOINT_HIERARCHY_NOT_ESTABLISHED
                or row.get("trace_status") not in _ENDPOINT_ESTABLISHED_STATUSES):
            unresolved.append({"port_id": row.get("port_id"),
                               "trace_status": row.get("trace_status")})
            continue
        role = row.get("endpoint_role")
        if role == EXTERNAL_ENDPOINT_MASTER:
            bucket = masters
        elif role == EXTERNAL_ENDPOINT_SLAVE:
            bucket = slaves
        elif row.get("fabric_role") == FABRIC_SIDE_SLAVE_INTERFACE:
            bucket = masters
        elif row.get("fabric_role") == FABRIC_SIDE_MASTER_INTERFACE:
            bucket = slaves
        else:
            unresolved.append({"port_id": row.get("port_id"),
                               "trace_status": row.get("trace_status")})
            continue
        if path not in bucket:
            bucket.append(path)
    return {"masters": masters, "slaves": slaves, "unresolved": unresolved}


def assert_projection_agrees_with_traces(rows, traces) -> None:
    """The registry's own master/slave lists must equal the ones AMBA-14's
    traces produced (`discovered_topology_ids()`).

    Cheap, and it is the check that keeps this module honest: the registry is
    assembled from matrix rows, `discovered_topology_ids()` is computed from the
    traces directly, and if the two ever disagree one of them is inventing an
    endpoint."""
    from_registry = registry_endpoints(rows)
    from_traces = afd.discovered_topology_ids(traces)
    for key in ("masters", "slaves"):
        if sorted(from_registry[key]) != sorted(from_traces[key]):
            raise PortRegistryError("AMBA_PORT_REGISTRY_TOPOLOGY_DISAGREES_WITH_TRACES", {
                "list": key, "from_registry": sorted(from_registry[key]),
                "from_traces": sorted(from_traces[key]),
                "hint": "the registry and the raw traces must name the same endpoints; a "
                        "difference means one of them derived an endpoint the other did not"})


def project_to_fabric_topology(rows, *, address_map_slaves=None, reserved_regions=None,
                               address_width: Optional[int] = None,
                               connectivity=None,
                               assume_full_connectivity: bool = False) -> dict:
    """Project the registry into the exact document
    `tools/verification_flow/fabric_topology_completeness_gate.py` validates.

    The two computed halves are NOT recomputed here: `scoreboard_matrix` comes
    from `amba_fabric_generator.build_scoreboard_matrix()` and `address_map`
    from its `compute_address_regions()`, which already enforce the same
    exclusive-end adjacency semantics that gate does.

    `address_map_slaves` is supplied by the caller because an address map is
    AMBA-23's evidence (an RTL decoder, a fabric configuration, an address-map
    package), not something a port registry can know. Omit it and the projection
    carries an EMPTY `address_map`, which the gate will correctly refuse -- an
    honest refusal rather than a fabricated map that would pass."""
    endpoints = registry_endpoints(rows)
    masters, slaves = endpoints["masters"], endpoints["slaves"]
    if not masters or not slaves:
        raise PortRegistryError("AMBA_PORT_REGISTRY_TOPOLOGY_INCOMPLETE", {
            "masters": masters, "slaves": slaves,
            "unresolved": endpoints["unresolved"],
            "hint": "a topology document needs at least one traced master and one traced "
                    "slave; every unresolved port is listed above rather than filled in"})
    matrix = build_scoreboard_matrix(
        [{"id": m} for m in masters], [{"id": s} for s in slaves],
        connectivity, assume_full_connectivity)
    address_map: list = []
    if address_map_slaves:
        try:
            regions = compute_address_regions(address_map_slaves, reserved_regions,
                                              address_width)
        except AddressMapError as exc:
            raise PortRegistryError("AMBA_PORT_REGISTRY_ADDRESS_MAP_INVALID", {
                "reason": exc.reason, "detail": exc.detail}) from exc
        address_map = [{"owner": r["owner"], "owner_kind": r["owner_kind"],
                        "start_addr": r["start"], "end_addr": r["end"]} for r in regions]
    return {
        "masters": masters,
        "slaves": slaves,
        "scoreboard_matrix": matrix,
        "address_map": address_map,
        # Not part of the gate's schema and ignored by it, carried so the
        # projected document says which registry produced it.
        "amba_port_registry": {"port_count": len(rows or ()),
                               "unresolved_ports": endpoints["unresolved"]},
    }


# ===========================================================================
# Reporting / persistence
# ===========================================================================

AMBA22_REGISTRY_COLUMNS: tuple = (
    ("port_id", "port_id"),
    ("fabric_port", "fabric_port"),
    ("protocol", "protocol"),
    ("fabric_role", "fabric_role"),
    ("endpoint_role", "endpoint_role"),
    ("endpoint_hierarchy", "endpoint_hierarchy"),
    ("vip_bind_hierarchy", "vip_bind_hierarchy"),
    ("vip_mode", "vip_mode"),
    ("clock", "clock"),
    ("reset", "reset"),
    ("address_width", "address_width"),
    ("data_width", "data_width"),
    ("id_width", "id_width"),
    ("user_widths", "user_widths"),
    ("scoreboard_channel", "scoreboard_channel"),
    ("trace_status", "trace_status"),
    ("readiness", "readiness"),
    ("confidence", "confidence"),
    ("source_evidence", "source_evidence"),
)


def _renderable(rows) -> list:
    """`source_evidence` is a list; a markdown cell is one line. Joined here
    only for RENDERING -- the registry row itself keeps the list, so a JSON
    consumer gets individually-citable strings rather than one blob."""
    return [{**r, "source_evidence": " | ".join(r.get("source_evidence") or [])}
            for r in rows or ()]


def render_amba_port_registry(rows) -> str:
    return render_markdown_table(
        list(AMBA22_REGISTRY_COLUMNS), _renderable(rows),
        empty_note="(no fabric port was discovered, so the registry is empty)")


def render_amba_port_registry_report(rows, traces=None) -> str:
    """The AMBA-22 review artifact. Self-checked against
    `assert_no_bind_statement()` for the same reason AMBA-16..20's report is:
    a planning artifact that accidentally rendered emittable SystemVerilog would
    be a way past AMBA-30's gate."""
    endpoints = registry_endpoints(rows)
    lines = ["# AMBA-22 AMBA_PORT_REGISTRY", "",
             f"{len(parent_matrix_rows(rows))} fabric port(s), {len(rows or ())} registry "
             f"row(s) including branch and AMBA-11 second-side rows.", "",
             f"Traced masters: {', '.join(endpoints['masters']) or '(none)'}", "",
             f"Traced slaves: {', '.join(endpoints['slaves']) or '(none)'}", "",
             render_amba_port_registry(rows), ""]
    if endpoints["unresolved"]:
        lines += ["## Ports with no established endpoint", "",
                  render_markdown_table(
                      [("port_id", "port_id"), ("trace_status", "Trace Status")],
                      endpoints["unresolved"]), ""]
    lines.append(
        "This registry drives later VIP/UVM construction only AFTER a human approves it "
        "(AMBA-30 / AMBA-31). Every `vip_bind_hierarchy` above is a proposed location, not "
        "a bind statement; nothing here is emitted into any environment.")
    text = "\n".join(lines)
    assert_no_bind_statement(text)
    return text


def save_amba_port_registry(rows, path) -> None:
    """Validate, then write deterministically -- no timestamp anywhere, so an
    unchanged fabric regenerates a byte-identical file and a diff is a real
    change (env_manifest.py's Diffability contract)."""
    assert_registry_complete(rows)
    doc = {"amba_port_registry_fields": list(AMBA_PORT_REGISTRY_FIELDS),
           "rows": [{k: v for k, v in r.items() if k != "validation"} for r in rows]}
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n",
                          encoding="utf-8")


def load_amba_port_registry(path) -> list:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = doc.get("rows", [])
    assert_registry_complete(rows)
    return rows
