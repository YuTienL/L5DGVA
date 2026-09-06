"""IP-level (single-subsystem) active/passive VIP-vs-legacy-BFM ownership
conflict check.

WHY THIS IS NARROWER THAN system_resource_inventory.py'S ACTIVE_DRIVER_CONFLICT
---------------------------------------------------------------------------
`system_resource_inventory.py`'s SYS-11/SYS-12 machinery classifies resource
relationships and stops automatic integration when a DRIVER_CONFLICT is found,
but it is a CROSS-SUBSYSTEM mechanism by construction: its own module
docstring says the gap it closes is that no single-subsystem check has "any
rows to match against" a SECOND subsystem's resources, and every one of its
entry points (`build_subsystem_resource_inventory`,
`detect_duplicate_resources`, `real_cross_subsystem_findings`) takes MULTIPLE
subsystems' evidence at once. That leaves a real, narrower question
unanswered at plain IP-level intake (a single subsystem, before any SoC
composition even exists): does THIS ONE subsystem's own environment declare a
real VIP agent AND a legacy hand-written BFM/driver BOTH active on the SAME
interface/port? Two independently-driving owners on one physical interface
are exactly as hazardous within one subsystem as they are across two, and
nothing upstream of `system_resource_inventory.py` ever checks for it.

`connectivity.find_active_bind_target_collisions()` comes close -- it is the
real, already-shipped SINGLE-MATRIX version of SYS-12's rule -- but it
requires BOTH colliding rows to carry a real VIP (`_row_has_vip()`), so a row
whose `vip_type` is a `NO_VIP_MARKERS` value (exactly what a hand-written,
non-VIP BFM/driver looks like in that schema) is excluded from the check
entirely. A real VIP agent and a legacy driver sharing one bind target is
therefore invisible to that function by construction, and is invisible to
`reconcile_exemptions_against_matrix()` too (an exempted no-VIP row is
accepted as an explained gap, never cross-checked against whether a VIP
elsewhere in the SAME manifest already claims that exact interface). This
module closes exactly that gap and nothing else.

VOCABULARY REUSED, NOT REINVENTED
----------------------------------
Per this project's own rule against a second vocabulary for one concept, the
per-pair finding when a real conflict is found reuses
`system_resource_inventory.REL_DRIVER_CONFLICT` verbatim (never a renamed
synonym), together with that module's own `INTEGRATION_STOPPED` resolution
token and its `SYS12_PREFERRED_MODEL` human-facing text -- SYS-12's stop rule
and its preferred resolution model are carried through unchanged rather than
restated. `connectivity.ACTIVE_INTERFACE` / `PASSIVE_INTERFACE` /
`ACTIVE_PASSIVE_VALUES` / `NO_VIP_MARKERS` / `build_connectivity_matrix()` are
the SAME active/passive vocabulary and matrix normaliser
`system_resource_inventory.py` itself imports -- there is no second
active/passive spelling anywhere in this module.

The three (four, honestly) report-level statuses this module produces
(CONFLICT / CLEAR / NOT_APPLICABLE / UNKNOWN) are a NEW, IP-scoped vocabulary
answering a different question from SYS-11's seven relationship classes
(which classify what kind of duplicate a pair of CROSS-subsystem resources
is) -- this module never renders a SYS-11 class as its own report status,
which the test suite holds apart from SYS-11's own class names (excepting
`UNKNOWN`, a generic honest-absence word this codebase already reuses across
many unrelated modules, not proprietary SYS-11 vocabulary).

WHAT COUNTS AS "vip_config plus any declared BFM/driver entries"
------------------------------------------------------------------
The VIP half is real, existing evidence: `env_manifest.json`'s own
`vip_config.vip_instances` (the schema `env_manifest.parse_vip_config_dump()`
already writes -- `instance_path` / `vip_type` / `config_fields`, a real
zero-time UVM config-dump capture). An entry whose `vip_type` is one of
`connectivity.NO_VIP_MARKERS` is not a real VIP agent (the identical rule
`system_resource_inventory._build_resources_for_subsystem()` already applies
-- "an interface with no VIP is not a resource") and is excluded from the VIP
side here too.

The legacy BFM/driver half is deliberately NOT read from any producer,
because no producer for it exists anywhere in this codebase (confirmed by
direct search before writing this module: no `bfm`/`legacy_driver`/
`hand_written` field appears in `env_manifest.py`'s real schema). It is
therefore, honestly, a CALLER-DECLARED fact -- the same status
`system_resource_inventory.SubsystemResourceSources.declared_physical_
interfaces` already carries ("a project's own explicit statement... a human's
decision, never this module's inference"). `legacy_bfm_declarations` is that
input: a list of `{"port_id", "driver_name", "active_passive", "evidence"}`
records a human or an upstream tool supplies. `port_id` must equal a real
`vip_config.vip_instances[].instance_path` EXACTLY for the two sides to be
considered the same interface -- this module performs no fuzzy or
name-derived port matching (SYS-10's own "do not decide by names alone"
principle, applied to the match key itself).

A real VIP instance's own ACTIVE/PASSIVE state is not carried by
`vip_config.vip_instances` at all (confirmed against its real schema --
`instance_path`/`vip_type`/`config_fields` only); it lives in the
connectivity matrix `system_resource_inventory.py` also depends on for the
identical fact. `connectivity_rows` is therefore an OPTIONAL second input --
real rows in `connectivity.build_connectivity_matrix()`'s own shape for the
SAME subsystem -- resolved to each VIP instance's active/passive by the
IDENTICAL match-candidate convention (`bind_target`, then `dut_instance`, then
`"dut_instance.interface"`) `system_resource_inventory._build_resources_for_
subsystem()` already uses the other direction. Omitting it never invents an
active/passive value for the VIP side: it reports the affected pair(s)
UNDETERMINED instead.

SCOPE BOUNDARY -- DETECTION ONLY
---------------------------------
This module names a conflict for a human to resolve. It never picks a
winner, never disables an agent, never edits an environment, and never
touches any approval/governance mechanism -- exactly the boundary
`system_resource_inventory.py`'s own SCOPE BOUNDARY section states for its
cross-subsystem sibling.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import connectivity as conn
from . import system_resource_inventory as sri

# ---------------------------------------------------------------------------
# Report-level vocabulary (NEW, IP-scoped; distinct from SYS-11's seven
# relationship classes and from models.Status)
# ---------------------------------------------------------------------------

STATUS_CONFLICT = "CONFLICT"
STATUS_CLEAR = "CLEAR"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_UNKNOWN = "UNKNOWN"

REPORT_STATUSES: Tuple[str, ...] = (
    STATUS_CONFLICT, STATUS_CLEAR, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Per-pair sub-status vocabulary. PAIR_CONFLICT is `sri.REL_DRIVER_CONFLICT`
# itself, imported rather than re-spelled, per this module's own reuse rule.
# ---------------------------------------------------------------------------

PAIR_CONFLICT = sri.REL_DRIVER_CONFLICT
PAIR_CLEAR_NO_VIP_MATCH = "NO_MATCHING_VIP_INSTANCE"
PAIR_CLEAR_VIP_PASSIVE = "VIP_RESOLVED_PASSIVE"
PAIR_CLEAR_LEGACY_PASSIVE = "LEGACY_DRIVER_DECLARED_PASSIVE"
PAIR_UNDETERMINED_NO_CONNECTIVITY = "VIP_ACTIVE_PASSIVE_UNKNOWN_NO_CONNECTIVITY_ROWS"
PAIR_UNDETERMINED_NO_MATCHING_ROW = "VIP_ACTIVE_PASSIVE_UNKNOWN_NO_MATCHING_CONNECTIVITY_ROW"
PAIR_UNDETERMINED_LEGACY_UNDECLARED = "LEGACY_ACTIVE_PASSIVE_NOT_DECLARED_OR_INVALID"


class IpOwnershipConflictError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# VIP side -- real evidence, env_manifest.json's own vip_config layer
# ===========================================================================

def real_vip_instances(env_manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Real VIP agents declared for this subsystem, off
    `vip_config.vip_instances` -- `env_manifest.parse_vip_config_dump()`'s own
    schema (`instance_path` / `vip_type` / `config_fields`). An entry whose
    `vip_type` is a `connectivity.NO_VIP_MARKERS` value is not a real VIP
    agent (the identical rule `system_resource_inventory.py`'s own resource
    builder applies) and is excluded. An entry with no `instance_path` cannot
    be matched to anything and is excluded too -- never guessed at."""
    vip_config = (env_manifest or {}).get("vip_config") or {}
    out: List[Dict[str, Any]] = []
    for entry in vip_config.get("vip_instances") or []:
        vip_type = str((entry or {}).get("vip_type") or "")
        if vip_type.strip().upper() in conn.NO_VIP_MARKERS:
            continue
        instance_path = str((entry or {}).get("instance_path") or "")
        if not instance_path:
            continue
        out.append({
            "instance_path": instance_path,
            "vip_type": vip_type,
            "config_fields": dict((entry or {}).get("config_fields") or {}),
        })
    return out


def _vip_active_passive_from_connectivity(
        vip_instance_paths: Sequence[str],
        connectivity_rows: Optional[Sequence[Mapping[str, Any]]],
) -> Dict[str, Optional[str]]:
    """Resolves each VIP `instance_path` to a real active/passive value from
    a real connectivity matrix for the SAME subsystem, using the SAME
    match-candidate convention `system_resource_inventory.
    _build_resources_for_subsystem()` already applies the other direction
    (`bind_target`, then `dut_instance`, then `"dut_instance.interface"`).
    An `instance_path` no row resolves stays `None` -- never a guessed
    default of active or passive."""
    result: Dict[str, Optional[str]] = {p: None for p in vip_instance_paths}
    if not connectivity_rows:
        return result
    matrix = conn.build_connectivity_matrix(list(connectivity_rows))
    candidates: Dict[str, str] = {}
    for row in matrix:
        active_passive = str(row.get("active_passive") or "").strip().lower()
        if active_passive not in conn.ACTIVE_PASSIVE_VALUES:
            continue
        dut_instance = str(row.get("dut_instance") or "")
        interface = str(row.get("interface") or "")
        bind_target = str(row.get("bind_target") or "")
        for key in (bind_target, dut_instance,
                    f"{dut_instance}.{interface}" if dut_instance and interface else ""):
            if key and key not in candidates:
                candidates[key] = active_passive
    for path in vip_instance_paths:
        if path in candidates:
            result[path] = candidates[path]
    return result


# ===========================================================================
# The check itself
# ===========================================================================

def analyze_ip_ownership_conflict(
        env_manifest: Mapping[str, Any], *,
        legacy_bfm_declarations: Optional[Sequence[Mapping[str, Any]]] = None,
        connectivity_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """The IP-level (single-subsystem) VIP-vs-legacy-BFM ownership check.

    `env_manifest`: a real env.manifest.json dict (or any dict carrying its
    `vip_config` layer) for ONE subsystem -- never multiple subsystems'
    evidence combined, which is `system_resource_inventory.py`'s job.

    `legacy_bfm_declarations`: caller-declared legacy driver/BFM records (see
    module docstring -- there is no real producer for this fact in this
    codebase). Empty/omitted -> NOT_APPLICABLE: there is nothing hand-written
    declared to check a VIP agent against, which is the honest common case
    for a subsystem built entirely on VIP.

    `connectivity_rows`: optional real connectivity-matrix rows for this SAME
    subsystem, supplying each VIP instance's real active/passive state.
    Omitted -> a legacy-active/VIP-present pair reports UNDETERMINED rather
    than assuming the VIP is active.

    Returns a dict with `status` (one of REPORT_STATUSES), `reason`, and the
    per-pair `conflicts` / `cleared` / `undetermined` lists, each entry
    carrying its own real basis.
    """
    vip_instances = real_vip_instances(env_manifest)
    vip_by_path = {v["instance_path"]: v for v in vip_instances}
    legacy = list(legacy_bfm_declarations or [])

    if not legacy:
        return {
            "status": STATUS_NOT_APPLICABLE,
            "reason": ("no legacy BFM/driver was declared for this subsystem "
                       "(legacy_bfm_declarations is empty) -- there is nothing "
                       "hand-written to check a real VIP agent against"),
            "vip_instance_count": len(vip_instances),
            "legacy_declaration_count": 0,
            "connectivity_rows_supplied": bool(connectivity_rows),
            "conflicts": [], "cleared": [], "undetermined": [],
        }

    vip_active_passive = _vip_active_passive_from_connectivity(
        list(vip_by_path.keys()), connectivity_rows)

    conflicts: List[Dict[str, Any]] = []
    cleared: List[Dict[str, Any]] = []
    undetermined: List[Dict[str, Any]] = []

    for i, raw_entry in enumerate(legacy):
        entry = raw_entry or {}
        port_id = str(entry.get("port_id") or "")
        driver_name = str(entry.get("driver_name") or "") or f"legacy_bfm_declarations[{i}]"
        raw_ap = str(entry.get("active_passive") or "").strip().lower()
        legacy_ap = raw_ap if raw_ap in conn.ACTIVE_PASSIVE_VALUES else None
        evidence = entry.get("evidence") or "declared by caller -- no real producer for this fact"

        record: Dict[str, Any] = {
            "port_id": port_id,
            "legacy_driver_name": driver_name,
            "legacy_active_passive": raw_ap or None,
            "evidence": evidence,
        }

        if not port_id or port_id not in vip_by_path:
            record["sub_status"] = PAIR_CLEAR_NO_VIP_MATCH
            record["detail"] = (
                f"declared port_id {port_id!r} does not match any real "
                "vip_config.vip_instances[].instance_path in this subsystem's env.manifest.json "
                "-- no VIP is present on this port to conflict with")
            cleared.append(record)
            continue

        vip = vip_by_path[port_id]
        record["vip_instance_path"] = vip["instance_path"]
        record["vip_type"] = vip["vip_type"]

        if legacy_ap is None:
            record["sub_status"] = PAIR_UNDETERMINED_LEGACY_UNDECLARED
            record["detail"] = (
                f"legacy driver {driver_name!r} on {port_id!r} declared no valid "
                f"active_passive (expected one of {sorted(conn.ACTIVE_PASSIVE_VALUES)}); a real "
                f"VIP instance ({vip['vip_type']}) IS present on this port but ownership cannot "
                "be judged without the declared driver's own active/passive state")
            undetermined.append(record)
            continue

        if legacy_ap == conn.PASSIVE_INTERFACE:
            record["sub_status"] = PAIR_CLEAR_LEGACY_PASSIVE
            record["detail"] = (
                f"legacy driver {driver_name!r} on {port_id!r} is declared PASSIVE -- a passive "
                "monitor alongside a VIP agent is not an ownership conflict")
            cleared.append(record)
            continue

        # legacy_ap == conn.ACTIVE_INTERFACE from here.
        vip_ap = vip_active_passive.get(port_id)
        if vip_ap is None:
            no_rows = not connectivity_rows
            record["sub_status"] = (PAIR_UNDETERMINED_NO_CONNECTIVITY if no_rows
                                     else PAIR_UNDETERMINED_NO_MATCHING_ROW)
            record["detail"] = (
                f"legacy driver {driver_name!r} on {port_id!r} is declared ACTIVE and a real VIP "
                f"instance ({vip['vip_type']}) is present on the same instance_path, but the "
                "VIP's own active/passive state could not be resolved -- " +
                ("no connectivity_rows were supplied for this subsystem"
                 if no_rows else
                 "no connectivity-matrix row resolves this instance_path"))
            undetermined.append(record)
            continue

        if vip_ap == conn.PASSIVE_INTERFACE:
            record["sub_status"] = PAIR_CLEAR_VIP_PASSIVE
            record["detail"] = (
                f"VIP instance {vip['instance_path']} is PASSIVE on this port; the active legacy "
                f"driver {driver_name!r} is the sole active owner -- no two active drivers on "
                "one interface")
            cleared.append(record)
            continue

        # both ACTIVE: the real conflict.
        record["sub_status"] = PAIR_CONFLICT
        record["relationship"] = sri.REL_DRIVER_CONFLICT
        record["resolution"] = sri.INTEGRATION_STOPPED
        record["preferred_model"] = sri.SYS12_PREFERRED_MODEL
        record["detail"] = (
            f"real VIP agent {vip['instance_path']} ({vip['vip_type']}) and legacy hand-written "
            f"driver/BFM {driver_name!r} are BOTH declared ACTIVE on port {port_id!r} -- two "
            "independently-driving owners on one physical interface. This is detection only: a "
            "human must decide which one owns the interface; nothing here picks a winner.")
        conflicts.append(record)

    if conflicts:
        status = STATUS_CONFLICT
        reason = (f"{len(conflicts)} port(s) carry BOTH an active real VIP agent and an active "
                  "legacy hand-written BFM/driver -- see 'conflicts'")
    elif undetermined:
        status = STATUS_UNKNOWN
        reason = (f"{len(undetermined)} declared legacy driver(s) share a real VIP instance's "
                  "port but ownership could not be conclusively judged -- see 'undetermined'")
    else:
        status = STATUS_CLEAR
        reason = (f"{len(legacy)} declared legacy BFM/driver(s) checked against "
                  f"{len(vip_instances)} real VIP instance(s); no active/active ownership "
                  "conflict found")

    return {
        "status": status,
        "reason": reason,
        "vip_instance_count": len(vip_instances),
        "legacy_declaration_count": len(legacy),
        "connectivity_rows_supplied": bool(connectivity_rows),
        "conflicts": conflicts,
        "cleared": cleared,
        "undetermined": undetermined,
    }


# ===========================================================================
# Rendering + shared CLI front door
# ===========================================================================

def format_report(report: Mapping[str, Any]) -> str:
    lines = [f"IP OWNERSHIP CONFLICT (VIP vs. legacy BFM/driver): {report['status']}", ""]
    lines.append(report["reason"])
    lines.append("")
    lines.append(f"  real VIP instances       : {report.get('vip_instance_count', 0)}")
    lines.append(f"  legacy declarations      : {report.get('legacy_declaration_count', 0)}")
    lines.append(f"  connectivity rows given  : {report.get('connectivity_rows_supplied', False)}")
    for label, key in (("CONFLICTS", "conflicts"), ("UNDETERMINED", "undetermined"),
                        ("CLEARED", "cleared")):
        rows = report.get(key) or []
        if not rows:
            continue
        lines.append("")
        lines.append(f"{label}:")
        for r in rows:
            lines.append(f"  [{r.get('sub_status')}] port={r.get('port_id')!r} "
                         f"legacy_driver={r.get('legacy_driver_name')!r}")
            lines.append(f"      {r.get('detail')}")
    lines.append("")
    lines.append("SCOPE: detection only. This module never picks a winner between an active VIP")
    lines.append("agent and an active legacy driver -- a human resolves ownership, per SYS-12's")
    lines.append("preferred model carried on each conflict record.")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(env_manifest_path, *, legacy_bfm_path=None, connectivity_rows_path=None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.ip_ownership_conflict`
    (no `dv-harness` CLI verb was wired -- `cli.py`'s argparse tree is large
    and this check has no natural home in it yet; the ad hoc front door below
    is the sanctioned fallback the house style already uses for several
    recent modules). Returns (text, exit_code): 0 CLEAR, 1 CONFLICT,
    2 NOT_APPLICABLE or UNKNOWN."""
    manifest = _load_json(env_manifest_path)
    legacy = _load_json(legacy_bfm_path) if legacy_bfm_path else None
    connectivity_rows = _load_json(connectivity_rows_path) if connectivity_rows_path else None
    report = analyze_ip_ownership_conflict(
        manifest, legacy_bfm_declarations=legacy, connectivity_rows=connectivity_rows)
    text = json.dumps(report, indent=2) if as_json else format_report(report)
    code = {STATUS_CONFLICT: 1, STATUS_CLEAR: 0,
            STATUS_NOT_APPLICABLE: 2, STATUS_UNKNOWN: 2}[report["status"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.ip_ownership_conflict",
        description="IP-level (single-subsystem) check: is a real VIP agent AND a legacy "
                    "hand-written BFM/driver both declared ACTIVE on the same interface/port? "
                    "Detection only -- never picks a winner.")
    ap.add_argument("--env-manifest", required=True, dest="env_manifest_path",
                    help="Path to this subsystem's env.manifest.json (or any JSON carrying its "
                         "vip_config layer).")
    ap.add_argument("--legacy-bfm", dest="legacy_bfm_path",
                    help="Path to a JSON array of caller-declared legacy BFM/driver records "
                         "({\"port_id\", \"driver_name\", \"active_passive\", \"evidence\"}).")
    ap.add_argument("--connectivity-rows", dest="connectivity_rows_path",
                    help="Path to a JSON array of real connectivity-matrix rows for this SAME "
                         "subsystem, supplying each VIP instance's real active/passive state.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.env_manifest_path, legacy_bfm_path=a.legacy_bfm_path,
        connectivity_rows_path=a.connectivity_rows_path, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
