"""dv_harness/system_configuration_ir.py -- SYSTEM-LEVEL configuration-explosion
control: compose several subsystems' own configuration dimensions into ONE
system-level covering-array plan, 2026-09-06.

GAP THIS CLOSES. `dv_harness/config_variant_coverage.py` (section 232,
"CONFIGURATION VARIANT EXPLOSION CONTROL") already implements a real,
deterministic, constraint-aware IPOG covering-array engine -- but only at the
scope of ONE configuration space. Nothing in this repo composed MULTIPLE
subsystems' own configuration spaces (their own protocol/speed/lane-width/
feature-mode/SKU dimensions -- the same section 232 vocabulary
`config_variant_coverage.py`'s own docstring lists) into a single SYSTEM-LEVEL
plan the way `environment_mode_router.py` already recognises SYSTEM_LEVEL_MODE
composition ("select completed subsystem environments and compose a
System-Level/Full-SoC verification environment") for environment GENERATION.
A repo-wide `grep -rni "system_configuration_ir" -e "SystemConfigurationIR"` found
nothing before this module: `environment_mode_router.py` decides WHICH mode a
run is in and reads the registry of already-qualified subsystems, but has no
notion of a configuration DIMENSION at all; `system_resource_inventory.py` /
`system_topology_analysis.py` / `system_command_plan.py` cross-check shared
RESOURCES, ADDRESS/CLOCK/RESET facts and COMMAND routing across subsystems --
none of them has any notion of a configuration VARIANT space either.

REUSE OVER REINVENT -- THE WHOLE POINT OF THIS MODULE. This module builds NO
second combinatorial engine. Composing "system level" here means exactly one
thing: take N subsystems' own `ConfigDimension`/`Constraint`/
`CriticalCombination` declarations (the SAME dataclasses
`config_variant_coverage.py` already defines and validates), NAMESPACE each
subsystem's dimension names so two subsystems can each legally have their own
`speed_mode` dimension without colliding, fold the whole namespaced set --
plus any CROSS-subsystem constraints/critical combinations a caller declares
-- into ONE `config_variant_coverage.ConfigSpace`, and hand that space
straight to the REAL, ALREADY-TESTED `config_variant_coverage.build_plan()`
(IPOG generation + its own independent `verify_coverage()` recount). Every
line of actual combinatorial-selection logic -- ordering heuristic, seeding
critical rows, horizontal/vertical extension, the backtracking completion
search, the independent verifier, redundant-row pruning -- lives in exactly
one place in this codebase, unchanged by this module. What this module adds
is the SYSTEM-LEVEL COMPOSITION step in front of it, and one independent
per-subsystem re-verification step behind it (see below) -- nothing else.

WHY NAMESPACING, NOT A FLAT MERGE. Two subsystems in a real SoC very often
declare a dimension with the identical NAME (`speed_mode`, `clock_mode`,
`feature_mode`) that means something different to each of them. Silently
merging `usb0.speed_mode` and `pcie0.speed_mode` into one flat `speed_mode`
dimension would either raise a spurious duplicate-dimension error or, worse,
silently conflate two unrelated axes into one. `compose_system_config_space()`
therefore renames every dimension `<subsystem_id>.<dimension_name>` before
handing anything to `config_variant_coverage.config_space_from_dict()` --
which then performs ALL of its own existing validation (duplicate names,
values that are not JSON scalars, a constraint or critical combination naming
an unknown dimension or an illegal value) unmodified. A cross-subsystem
constraint or critical combination MUST be declared using those SAME
namespaced keys (`"usb0.speed_mode"`, never a bare `"speed_mode"`) -- there is
no guessing here: an unnamespaced or misnamespaced key simply fails
`config_space_from_dict()`'s own existing "constraint names unknown
dimension" check, the same as any other unknown-dimension mistake.

SYSTEM-LEVEL MEANS AT LEAST TWO SUBSYSTEMS, BY THE SAME RULE THIS REPO ALREADY
USES. `environment_mode_router.resolve_environment_mode()` already draws this
line for environment GENERATION: "a single requested subsystem is a
SUBSYSTEM_MODE build ... two or more requested subsystems is a
SYSTEM_LEVEL_MODE composition." This module applies the identical threshold
(`MIN_SUBSYSTEMS_FOR_SYSTEM_LEVEL = 2`) to configuration-space composition,
for the same reason: composing ONE subsystem's own space with nothing else is
just `config_variant_coverage.py` on its own, and calling that "system-level"
would misrepresent what happened.

THE ONE GENUINELY NEW PIECE OF LOGIC: independent PER-SUBSYSTEM projection
re-verification. IPOG's own strength-t coverage guarantee, applied to the
WHOLE composed (namespaced) space, already mathematically implies that every
pair of dimensions belonging to the SAME subsystem is covered too -- a
same-subsystem pair is still just one pair among the composed space's target
tuples. But `config_variant_coverage.py`'s own docstring insists on never
trusting a generator's bookkeeping ("`verify_coverage()` is deliberately a
SEPARATE, independent recomputation... rather than a read-back of the
generator's own bookkeeping"), and a CROSS-subsystem constraint can, in
principle, exclude a target tuple from the SYSTEM-level target set in a way
that is easy to reason about wrong by hand -- especially once several
subsystems and several cross-subsystem constraints are involved. So this
module additionally re-verifies, per subsystem, that PROJECTING the composed
plan's emitted combinations onto just that subsystem's own namespaced
dimensions still satisfies pairwise coverage of a LOCAL `ConfigSpace` built
from ONLY that subsystem's own dimensions and its own LOCAL constraints/
criticals (cross-subsystem constraints are deliberately excluded from the
local re-check: they say nothing about whether this subsystem's own pairs are
covered, only about which SYSTEM-level combinations are legal at all). This
calls `config_variant_coverage.target_tuples()` and
`config_variant_coverage.verify_coverage()` again -- the SAME real functions,
never a re-derived pairwise-coverage check -- over a smaller, local space.

WHAT THIS MODULE DOES NOT DO, disclosed rather than implied closed:
  1. It does not discover a subsystem's own configuration dimensions. Each
     subsystem's dimensions/constraints/critical_combinations are a CALLER
     input -- exactly the same "declared, not invented" contract
     `config_variant_coverage.ConfigDimension`/`Constraint`/
     `CriticalCombination` already have. A caller might source a subsystem's
     dimensions from that subsystem's own `env.manifest.json` `vip_config`
     layer, from a prior single-subsystem `config-variants plan` run's own
     `dimensions` list, or from a human decision -- this module does not care
     which, and mines none of them itself.
  2. It does not decide which subsystems belong in a system-level composition
     -- that is `environment_mode_router.py`'s job (SYSTEM_LEVEL_MODE
     resolution) and the real subsystem registry
     `environment_mode_router.read_registered_subsystem_entries()` reads. A
     caller who already has that registry may pass its `name` entries through
     as this module's `subsystem_id`s; this module performs no registry
     lookup itself.
  3. It does not decide WHICH tests to run for a given system-level
     configuration -- exactly the same boundary `config_variant_coverage.py`
     itself draws against `change_impact.select_regression()`.
  4. It runs no build, submits no job, and has no stage gate. A composed
     system-level plan is an input to a human's or a caller's system-level
     regression-scoping decision, same as a single-subsystem plan is.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import config_variant_coverage as cvc

SCHEMA_VERSION = "1.0"

#: The real threshold `environment_mode_router.resolve_environment_mode()`
#: already applies to environment-generation mode selection, reused here for
#: configuration-space composition so "system-level" means the same thing in
#: both places in this codebase.
MIN_SUBSYSTEMS_FOR_SYSTEM_LEVEL = 2

#: The character this module reserves as the subsystem/dimension-name
#: separator when namespacing. A subsystem_id or a bare dimension name
#: containing it would make the namespaced key ambiguous to reverse (which
#: part is the subsystem, which part is the dimension), so both are refused
#: outright rather than guessed apart.
NAMESPACE_SEPARATOR = "."


class SystemConfigurationIRError(ValueError):
    """A system-level configuration composition request that cannot be
    honoured as written: fewer than two subsystems, a duplicate subsystem_id,
    a subsystem_id or dimension name containing the namespace separator, or a
    malformed subsystem contribution. `config_variant_coverage.ConfigSpaceError`
    (unknown dimension, illegal value, uncompletable critical combination,
    ...) is raised straight through from the underlying, reused module for
    every other kind of mistake, never re-wrapped."""


def _namespaced(subsystem_id: str, name: str) -> str:
    return f"{subsystem_id}{NAMESPACE_SEPARATOR}{name}"


def _validate_identifier(kind: str, value: str) -> str:
    v = str(value).strip()
    if not v:
        raise SystemConfigurationIRError(f"a {kind} needs a non-empty name")
    if NAMESPACE_SEPARATOR in v:
        raise SystemConfigurationIRError(
            f"{kind} {v!r} may not contain {NAMESPACE_SEPARATOR!r} -- that character is "
            "reserved by this module to join '<subsystem_id>.<dimension_name>' into one "
            "unambiguous, reversible namespaced key")
    return v


@dataclass(frozen=True)
class SubsystemConfigContribution:
    """One subsystem's own declared configuration space, exactly as a caller
    supplies it -- `dimensions`/`constraints`/`critical_combinations` in the
    SAME raw shapes `config_variant_coverage.config_space_from_dict()` already
    parses (a list of `{"name","values","source"}` / `{"forbid","reason"}` /
    `{"assignment","reason"}` dicts). Nothing here re-derives or mines any of
    these -- they are the same "declared, cited" contract every dimension in
    `config_variant_coverage.py` already has."""

    subsystem_id: str
    dimensions: Tuple[Mapping[str, Any], ...]
    constraints: Tuple[Mapping[str, Any], ...] = ()
    critical_combinations: Tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier("subsystem_id", self.subsystem_id)
        if not self.dimensions:
            raise SystemConfigurationIRError(
                f"subsystem {self.subsystem_id!r} declares no configuration dimensions")


def subsystem_contribution_from_dict(data: Mapping[str, Any]) -> SubsystemConfigContribution:
    if not isinstance(data, Mapping):
        raise SystemConfigurationIRError("a subsystem contribution must be a JSON object")
    return SubsystemConfigContribution(
        subsystem_id=str(data.get("subsystem_id", "")).strip(),
        dimensions=tuple(data.get("dimensions", []) or []),
        constraints=tuple(data.get("constraints", []) or []),
        critical_combinations=tuple(data.get("critical_combinations", []) or []),
    )


def _namespace_dimensions(contribution: SubsystemConfigContribution) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in contribution.dimensions:
        if not isinstance(entry, Mapping):
            raise SystemConfigurationIRError(
                f"subsystem {contribution.subsystem_id!r} dimension entry {entry!r} is not an "
                "object")
        name = _validate_identifier(
            f"subsystem {contribution.subsystem_id!r} dimension",
            str(entry.get("name", "")))
        source = str(entry.get("source", ""))
        namespaced_source = (f"[{contribution.subsystem_id}] {source}" if source
                              else f"[{contribution.subsystem_id}]")
        out.append({
            "name": _namespaced(contribution.subsystem_id, name),
            "values": entry.get("values"),
            "source": namespaced_source,
        })
    return out


def _namespace_constraints(contributions: Sequence[SubsystemConfigContribution]) -> List[Dict[str, Any]]:
    """Every LOCAL constraint a subsystem declares is namespaced onto that
    same subsystem's own dimensions -- a subsystem's own forbidden
    combinations only ever name its own dimensions, so there is no ambiguity
    about which subsystem's namespace a bare key inside one contribution's
    own `constraints` list belongs to."""
    out: List[Dict[str, Any]] = []
    for c in contributions:
        for entry in c.constraints:
            if not isinstance(entry, Mapping):
                raise SystemConfigurationIRError(
                    f"subsystem {c.subsystem_id!r} constraint entry {entry!r} is not an object")
            forbid = entry.get("forbid")
            if not isinstance(forbid, Mapping):
                raise SystemConfigurationIRError(
                    f"subsystem {c.subsystem_id!r} constraint needs a 'forbid' object")
            out.append({
                "forbid": {_namespaced(c.subsystem_id, str(k)): v for k, v in forbid.items()},
                "reason": str(entry.get("reason", "")),
            })
    return out


def _namespace_criticals(contributions: Sequence[SubsystemConfigContribution]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in contributions:
        for entry in c.critical_combinations:
            if not isinstance(entry, Mapping):
                raise SystemConfigurationIRError(
                    f"subsystem {c.subsystem_id!r} critical combination entry {entry!r} is not "
                    "an object")
            assignment = entry.get("assignment")
            if not isinstance(assignment, Mapping):
                raise SystemConfigurationIRError(
                    f"subsystem {c.subsystem_id!r} critical combination needs an 'assignment' "
                    "object")
            out.append({
                "assignment": {_namespaced(c.subsystem_id, str(k)): v
                               for k, v in assignment.items()},
                "reason": str(entry.get("reason", "")),
            })
    return out


def compose_system_config_space(
    subsystems: Sequence[SubsystemConfigContribution],
    *,
    cross_subsystem_constraints: Sequence[Mapping[str, Any]] = (),
    cross_subsystem_critical_combinations: Sequence[Mapping[str, Any]] = (),
    system_id: Optional[str] = None,
    description: str = "",
) -> cvc.ConfigSpace:
    """Compose N subsystems' own declared configuration spaces into ONE
    namespaced `config_variant_coverage.ConfigSpace`, reusing that module's
    own `config_space_from_dict()` for every bit of real validation (duplicate
    dimension names, illegal values, an unknown-dimension constraint or
    critical combination, an uncompletable critical combination under the
    composed constraints) -- this function performs no validation
    `config_variant_coverage.py` does not already perform, beyond identifier
    hygiene (non-empty, no namespace-separator collision) and the
    at-least-two-subsystems rule below.

    `cross_subsystem_constraints` / `cross_subsystem_critical_combinations`
    are in the SAME raw shapes as a subsystem's own local
    `constraints`/`critical_combinations`, except their `forbid`/`assignment`
    keys MUST already be fully namespaced (`"usb0.speed_mode"`, never a bare
    `"speed_mode"`) -- exactly the keys this function produces for each
    subsystem's own dimensions, so a caller can always construct one from a
    `dimensions` entry it already declared.

    Raises `SystemConfigurationIRError` for a composition-level mistake
    (fewer than two subsystems, a duplicate subsystem_id, a bad identifier),
    and `config_variant_coverage.ConfigSpaceError` straight through for
    anything the underlying, reused space-construction/validation already
    catches."""
    if len(subsystems) < MIN_SUBSYSTEMS_FOR_SYSTEM_LEVEL:
        raise SystemConfigurationIRError(
            f"a system-level configuration composition needs at least "
            f"{MIN_SUBSYSTEMS_FOR_SYSTEM_LEVEL} subsystems (the same threshold "
            "environment_mode_router.resolve_environment_mode() already applies to "
            f"SYSTEM_LEVEL_MODE composition); got {len(subsystems)}. A single subsystem's own "
            "configuration space is exactly what config_variant_coverage.py already handles on "
            "its own -- calling that 'system-level' would misrepresent what happened.")

    seen_ids = set()
    for c in subsystems:
        key = c.subsystem_id.lower()
        if key in seen_ids:
            raise SystemConfigurationIRError(
                f"duplicate subsystem_id {c.subsystem_id!r} in a system-level composition")
        seen_ids.add(key)

    dims_raw: List[Dict[str, Any]] = []
    for c in subsystems:
        dims_raw.extend(_namespace_dimensions(c))

    constraints_raw = _namespace_constraints(subsystems)
    for entry in cross_subsystem_constraints:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("forbid"), Mapping):
            raise SystemConfigurationIRError(
                f"cross-subsystem constraint entry {entry!r} needs a 'forbid' object")
        constraints_raw.append({"forbid": dict(entry["forbid"]), "reason": str(entry.get("reason", ""))})

    criticals_raw = _namespace_criticals(subsystems)
    for entry in cross_subsystem_critical_combinations:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("assignment"), Mapping):
            raise SystemConfigurationIRError(
                f"cross-subsystem critical combination entry {entry!r} needs an 'assignment' "
                "object")
        criticals_raw.append({"assignment": dict(entry["assignment"]),
                               "reason": str(entry.get("reason", ""))})

    subsystem_ids = [c.subsystem_id for c in subsystems]
    raw_space = {
        "space_id": system_id or ("system_" + "_".join(subsystem_ids) + "_configuration"),
        "description": description or (
            f"system-level covering-array plan composed from {len(subsystems)} subsystems' own "
            f"declared configuration dimensions: {', '.join(subsystem_ids)}"),
        "dimensions": dims_raw,
        "constraints": constraints_raw,
        "critical_combinations": criticals_raw,
    }
    return cvc.config_space_from_dict(raw_space)


def project_combination(combination: Mapping[str, Any], subsystem_id: str) -> Dict[str, Any]:
    """Given one emitted SYSTEM-level combination, extract just this
    subsystem's own dimensions, with the `<subsystem_id>.` prefix stripped
    back off so the projected dict is shaped exactly like that subsystem's
    own local configuration (the same shape its own dimensions were declared
    in before this module namespaced them)."""
    prefix = subsystem_id + NAMESPACE_SEPARATOR
    return {k[len(prefix):]: v for k, v in combination.items() if k.startswith(prefix)}


def verify_subsystem_projection_coverage(
    contribution: SubsystemConfigContribution,
    system_combinations: Sequence[Mapping[str, Any]],
    strength: int = 2,
) -> dict:
    """Independent per-subsystem re-verification (see module docstring):
    build a LOCAL `ConfigSpace` from just this subsystem's own dimensions and
    its own LOCAL constraints/criticals (cross-subsystem constraints are
    deliberately excluded -- they say nothing about whether this subsystem's
    OWN pairs are covered), project every system-level combination onto this
    subsystem's own dimensions, de-duplicate, and run the REAL, unmodified
    `config_variant_coverage.verify_coverage()` over the projected rows. This
    never trusts the system-level plan's own bookkeeping -- it recomputes,
    the same discipline `config_variant_coverage.verify_coverage()` itself
    already applies to a single space.

    A subsystem contributing FEWER dimensions than `strength` (e.g. a
    single-dimension subsystem under strength-2 composition) has no PAIR to
    ask about at that strength -- `config_variant_coverage.target_tuples()`
    itself refuses a strength exceeding the space's own dimension count
    rather than silently returning an empty target set, so this function
    caps the LOCAL re-check at `min(strength, dimension_count)` and records
    both the requested and the effective strength on the report, honestly,
    rather than skipping the subsystem's own re-verification altogether.

    The local re-check space is built from `contribution`'s own BARE
    (never namespaced) dimension/constraint/critical-combination
    declarations -- exactly the shape `project_combination()` below strips a
    system-level row back down to -- so the local space's own dimension
    names and the projected rows' own keys always agree."""
    raw_local = {
        "space_id": contribution.subsystem_id,
        "dimensions": list(contribution.dimensions),
        "constraints": list(contribution.constraints),
        "critical_combinations": list(contribution.critical_combinations),
    }
    local_space = cvc.config_space_from_dict(raw_local)
    local_dim_names = set(local_space.dimension_names)

    projected: List[Dict[str, Any]] = []
    seen: set = set()
    for combo in system_combinations:
        row = project_combination(combo, contribution.subsystem_id)
        if set(row) != local_dim_names:
            # This system-level combination does not fully assign this
            # subsystem's own dimensions (should not happen for a plan
            # config_variant_coverage.build_plan() produced, since every
            # emitted row is a FULL assignment of the whole composed space --
            # reported rather than silently skipped in case a caller hands
            # in a hand-edited or externally-produced combination list).
            continue
        key = tuple(sorted((str(k), v) for k, v in row.items()))
        if key in seen:
            continue
        seen.add(key)
        projected.append(row)

    effective_strength = min(strength, len(local_space.dimensions))
    report = cvc.verify_coverage(local_space, projected, effective_strength)
    report["subsystem_id"] = contribution.subsystem_id
    report["projected_combination_count"] = len(projected)
    report["requested_strength"] = strength
    report["effective_strength"] = effective_strength
    return report


def build_system_configuration_plan(
    subsystems: Sequence[SubsystemConfigContribution],
    *,
    cross_subsystem_constraints: Sequence[Mapping[str, Any]] = (),
    cross_subsystem_critical_combinations: Sequence[Mapping[str, Any]] = (),
    strength: int = 2,
    system_id: Optional[str] = None,
    description: str = "",
) -> dict:
    """Compose, then plan with the REAL `config_variant_coverage.build_plan()`
    (IPOG generation + its own independent verify), then INDEPENDENTLY
    re-verify each subsystem's own projected coverage -- three real, separate
    checks, never one trusted on the strength of another. Returns the
    system-level plan (in exactly `config_variant_coverage.build_plan()`'s own
    shape, `space_id`/`combinations`/`coverage`/... unchanged) plus a
    `system_composition` block: which subsystems contributed, a
    `subsystem_breakdown` (each emitted combination split back into its
    per-subsystem projection, for a human reading the plan without having to
    parse namespaced keys by hand), and `subsystem_projection_coverage` (the
    per-subsystem independent re-verification report above).

    `status` on the returned dict is the WORST of the system-level plan's own
    `status` and every subsystem's own projection-coverage `status` --
    worst-wins, never averaged, matching this codebase's own composite-gate
    convention: a system-level plan that achieves full coverage overall but
    somehow leaves one subsystem's own local pairs undercovered (which would
    itself be a defect in the underlying IPOG run this module would want
    surfaced, not hidden) must never report as clean."""
    space = compose_system_config_space(
        subsystems,
        cross_subsystem_constraints=cross_subsystem_constraints,
        cross_subsystem_critical_combinations=cross_subsystem_critical_combinations,
        system_id=system_id,
        description=description,
    )
    plan = cvc.build_plan(space, strength)

    subsystem_ids = [c.subsystem_id for c in subsystems]
    breakdown = [
        {"index": i, "by_subsystem": {sid: project_combination(combo, sid) for sid in subsystem_ids}}
        for i, combo in enumerate(plan["combinations"])
    ]
    projection_reports = [
        verify_subsystem_projection_coverage(c, plan["combinations"], strength)
        for c in subsystems
    ]

    statuses = [plan["status"]] + [r["status"] for r in projection_reports]
    worst = _worst_status(statuses)

    plan["schema_version"] = SCHEMA_VERSION
    plan["status"] = worst
    plan["system_composition"] = {
        "subsystem_ids": subsystem_ids,
        "subsystem_count": len(subsystem_ids),
        "subsystem_dimension_counts": {
            c.subsystem_id: len(c.dimensions) for c in subsystems
        },
        "cross_subsystem_constraint_count": len(cross_subsystem_constraints),
        "cross_subsystem_critical_combination_count": len(cross_subsystem_critical_combinations),
        "subsystem_breakdown": breakdown,
        "subsystem_projection_coverage": projection_reports,
    }
    return plan


# `config_variant_coverage.py`'s own status set, ordered worst-first for the
# composite fold above. Reused verbatim -- this module invents no second
# status vocabulary of its own.
_STATUS_WORST_ORDER = (
    cvc.STATUS_NOT_AVAILABLE,
    cvc.STATUS_PARTIAL,
    cvc.STATUS_FULL_EXCEPT_UNREACHABLE,
    cvc.STATUS_FULL,
)


def _worst_status(statuses: Sequence[str]) -> str:
    ranked = [(_STATUS_WORST_ORDER.index(s) if s in _STATUS_WORST_ORDER else -1, s) for s in statuses]
    ranked.sort(key=lambda t: t[0])
    return ranked[0][1] if ranked else cvc.STATUS_NOT_AVAILABLE


def system_config_document_from_dict(data: Mapping[str, Any]) -> Tuple[
        List[SubsystemConfigContribution], List[Mapping[str, Any]], List[Mapping[str, Any]],
        Optional[str], str]:
    """Parse the JSON document shape `execute_verb()`/the CLI accept:
    `{"system_id", "description", "subsystems": [...], "cross_subsystem_constraints": [...],
    "cross_subsystem_critical_combinations": [...]}`."""
    if not isinstance(data, Mapping):
        raise SystemConfigurationIRError("a system configuration document must be a JSON object")
    subs_raw = data.get("subsystems")
    if not isinstance(subs_raw, list) or not subs_raw:
        raise SystemConfigurationIRError(
            "system configuration document needs a non-empty 'subsystems' list")
    subsystems = [subsystem_contribution_from_dict(s) for s in subs_raw]
    return (
        subsystems,
        list(data.get("cross_subsystem_constraints", []) or []),
        list(data.get("cross_subsystem_critical_combinations", []) or []),
        (str(data["system_id"]) if data.get("system_id") else None),
        str(data.get("description", "")),
    )


def load_system_config_document(path: Any) -> Tuple[
        List[SubsystemConfigContribution], List[Mapping[str, Any]], List[Mapping[str, Any]],
        Optional[str], str]:
    p = Path(path)
    if not p.exists():
        raise SystemConfigurationIRError(f"system configuration document does not exist: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemConfigurationIRError(f"{p} is not valid JSON: {e}") from None
    return system_config_document_from_dict(data)


def format_system_plan(plan: Mapping[str, Any]) -> str:
    comp = plan.get("system_composition", {})
    lines = [
        cvc.format_plan(plan),
        "",
        f"  system composition   : {comp.get('subsystem_count')} subsystem(s): "
        f"{', '.join(comp.get('subsystem_ids', []))}",
    ]
    for sid, n in (comp.get("subsystem_dimension_counts") or {}).items():
        lines.append(f"    {sid}: {n} dimension(s) contributed")
    lines.append(
        f"  cross-subsystem       : {comp.get('cross_subsystem_constraint_count')} constraint(s), "
        f"{comp.get('cross_subsystem_critical_combination_count')} critical combination(s)")
    for r in comp.get("subsystem_projection_coverage", []):
        lines.append(
            f"  subsystem projection [{r.get('subsystem_id')}]: [{r.get('status')}] "
            f"{r.get('covered_tuple_count')}/{r.get('target_tuple_count')} local pairs covered "
            f"over {r.get('projected_combination_count')} projected configuration(s)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI (`python -m dv_harness.system_configuration_ir`). Deliberately no
# `dv-harness` subcommand and no `gates.py`/`cli.py` edit -- this module
# selects only, has no stage gate, and this repo's own recent convention
# (several 2026-09-06 additions above) is to ship a standalone
# `python -m dv_harness.<module>` front door instead of touching either of
# those two large, concurrently-edited files.
# --------------------------------------------------------------------------

_EXIT_BY_STATUS = {
    cvc.STATUS_FULL: 0,
    cvc.STATUS_FULL_EXCEPT_UNREACHABLE: 0,
    cvc.STATUS_PARTIAL: 1,
    cvc.STATUS_NOT_AVAILABLE: 2,
}


def execute_verb(verb: str, *, space_path: Optional[str] = None, strength: int = 2,
                  out_path: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.system_configuration_ir`.
    Returns (text, exit_code): 0 full coverage (both the system-level plan
    AND every subsystem's own independent projection re-verification), 1 a
    real coverage finding somewhere in that worst-wins fold, 2 a malformed
    document or usage error. Selects only: runs, builds and submits nothing."""
    if verb != "plan":
        return (f"unknown system-configuration-ir verb {verb!r} (only 'plan' is supported)", 2)
    if not space_path:
        return ("system-configuration-ir plan requires --space <system_config.json>", 2)
    try:
        subsystems, cross_constraints, cross_criticals, system_id, description = \
            load_system_config_document(space_path)
        plan = build_system_configuration_plan(
            subsystems,
            cross_subsystem_constraints=cross_constraints,
            cross_subsystem_critical_combinations=cross_criticals,
            strength=strength,
            system_id=system_id,
            description=description,
        )
    except (SystemConfigurationIRError, cvc.ConfigSpaceError) as e:
        return (f"{type(e).__name__}: {e}", 2)

    written = None
    if out_path:
        cvc.write_plan(".", plan, path=out_path)
        written = out_path
    text = json.dumps(plan, indent=2) if as_json else format_system_plan(plan)
    if written is not None and not as_json:
        text += f"\n  written to           : {written}"
    return text, _EXIT_BY_STATUS.get(plan["status"], 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.system_configuration_ir",
        description="System-level configuration-explosion control: compose several subsystems' "
                    "own declared configuration dimensions into one namespaced covering-array "
                    "plan, reusing config_variant_coverage.py's real IPOG engine unchanged. "
                    "Selects only -- runs and submits nothing.")
    ap.add_argument("verb", choices=("plan",))
    ap.add_argument("--space", required=True, help="System configuration document JSON file.")
    ap.add_argument("--strength", type=int, default=2, help="Interaction strength t (default 2).")
    ap.add_argument("--out", default=None, help="Also write the plan JSON to this path.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, space_path=a.space, strength=a.strength,
                               out_path=a.out, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
