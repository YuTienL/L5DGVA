"""dv_harness/vip_version_drift_detection.py -- cross-environment VIP version
drift detection across a project's MULTIPLE subsystem environments, 2026-09-07.

THE GAP THIS CLOSES
--------------------
`example_composition.check_vip_version_compatibility()` (built 2026-09-06) already
compares VIP versions -- but ONLY among the examples named in one composition
request, i.e. within ONE scenario a caller is about to assemble. It has no
notion of a PROJECT that has already built several SEPARATE subsystem
environments over time, each with its own real, independently-scanned
`env.manifest.json` (env_manifest.py's `vip_config.vip_release` layer -- a
real `$DESIGNWARE_HOME` filesystem scan, never a version typed into a
document). Two subsystems can each look internally consistent -- subsystem A
was built last month against `usb_svt/R-2019.06`, subsystem B was built this
week against `usb_svt/R-2021.12` -- and nothing in this repo ever compared
the two. That silent drift is exactly what this module surfaces.

Confirmed a genuine gap by direct search before writing anything: a repo-wide
grep for `vip_version_drift`/`version_drift` matched only `golden_scenario.py`'s
own `_version_drift()` -- a DIFFERENT, narrower mechanism answering "has THIS
ONE recorded golden capsule's own VIP versions moved since it was verified",
never a cross-SUBSYSTEM comparison.

REUSE OVER REINVENT
--------------------
This module invents no new VIP-version fact of its own. It reuses:
  - `env_manifest.load_env_manifest()` / `env_manifest.EnvManifestValidationError`
    -- the one real reader+validator for an env.manifest.json document.
  - The already-real `vip_config.vip_release` layer that document carries
    (built by `env_manifest.build_vip_release()`/`scan_designware_home()`):
    `status` ("SCANNED" or "NOT_AVAILABLE", with its own real `reason`) and
    `packages` (one entry per real installed VIP package/version directory
    `scan_designware_home()` actually found, each `{name, version,
    install_path, release_notes, feature_matrix}`).
  - `environment_mode_router.read_registered_subsystem_entries()` -- the REAL
    runtime subsystem registry (`.dv-harness/soc-composer/
    subsystem_environment_registry.json`, written only by
    `engine.py`'s `_persist_subsystem_registry_entry()` on a real, gate-
    verified SIGNOFF PASS), whose entries already carry each subsystem's own
    `environment_manifest` path -- the multi-subsystem discovery mechanism
    this module needs, never a second registry.

"SAME PROTOCOL'S VIP" MEANS THE SAME REAL PACKAGE DIRECTORY NAME
------------------------------------------------------------------
`scan_designware_home()`'s own docstring is explicit: one installed VIP
package/version directory answers "which VIP release this environment is
actually built against". Its `name` field is that package's real, on-disk
directory name in `$DESIGNWARE_HOME` (e.g. `usb_svt`, `pcie_svt`) -- a single
protocol's VIP package, by construction of how `dw_vip_setup` lays out an
install tree. This module therefore groups packages ACROSS subsystems by that
real, normalised `name` -- never by guessing a correspondence between a
package's directory name and a `vip_config.vip_instances[].vip_type` class
name (a different naming domain entirely: `vip_type` is a UVM config class's
own `get_type_name()`, not an install-tree directory name). Inventing that
correspondence would be exactly the "confident guess" the Evidence Truth Rule
forbids -- the same discipline `arbitration_policy_ir.py`/
`coherency_capability_ir.py`/`feature_enablement_matrix.py` already apply:
never infer identity from a name alone when the two names live in different
vocabularies with no real, cited link between them.

TWO PACKAGES OF THE SAME NAME ACROSS TWO SUBSYSTEMS WITH DIFFERENT REAL
VERSIONS IS THE DRIFT FINDING -- NEVER ARBITRATED
--------------------------------------------------------------------------
A shared package name reported by fewer than two DISTINCT subsystems has
nothing to compare against and is silently excluded from findings (it is not
evidence of anything). A shared package name reported by two or more
subsystems whose real `version` values (compared by exact string equality --
`None`, "the package directory has no version level", is itself a real,
distinct value, never treated as equal to a real version string) disagree is
a real `VipVersionDriftFinding`, citing every subsystem's own real version
and real `install_path`. This module never decides which subsystem's version
is "correct" -- that is a human/project decision, the same ARBITRATION
boundary every comparison-only module in this codebase already keeps.

THE EVIDENCE TRUTH RULE, APPLIED TO THE OVERALL VERDICT
-----------------------------------------------------------
`STATUS_NOT_AVAILABLE` (zero subsystems supplied, or fewer than two carry
usable SCANNED evidence -- there is nothing to compare) is kept honestly
distinct from `STATUS_INCOMPLETE_EVIDENCE` (two or more subsystems WERE
compared and no drift was found among them, but at least one OTHER declared
subsystem's own `vip_release` layer could not be scanned at all -- a real
absence that must never be silently read as "this subsystem agrees", per
this project's own house rule that an unmeasured fact must never be folded
into a clean pass). `STATUS_DRIFT_DETECTED` outranks both -- a real
conflicting-version finding is reported regardless of how many OTHER
subsystems could or could not be checked. Only when every declared subsystem
carries real SCANNED evidence and no shared package disagrees does this
module report `STATUS_NO_DRIFT`.

WHAT THIS MODULE DOES NOT DO
-------------------------------
It discovers no subsystem of its own beyond the real registry (or an explicit
caller-declared manifest map); it never generates, builds, or runs anything;
it never edits an env.manifest.json; it decides, approves and arbitrates
nothing -- there is deliberately no stage gate, and per this task's own
file-safety scope `dv_harness/cli.py`, `dv_harness/gates.py` and
`dv_harness/dashboard.py` were not touched. The front door is this module's
own Python API plus `python -m dv_harness.vip_version_drift_detection`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import env_manifest
from . import environment_mode_router

#: Per-subsystem status vocabulary. SCANNED is the exact real token
#: env_manifest.py's own vip_release layer already uses -- reused
#: deliberately, since it names the identical real fact, not re-spelled.
STATUS_SCANNED = "SCANNED"
STATUS_SUBSYSTEM_NOT_AVAILABLE = "NOT_AVAILABLE"

#: Overall (project-wide) status vocabulary. Checked disjoint from
#: dv_harness.models.Status at import time -- see assert_no_status_
#: vocabulary_collision() below.
STATUS_DRIFT_DETECTED = "DRIFT_DETECTED"
STATUS_NO_DRIFT = "NO_DRIFT"
STATUS_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

OVERALL_STATUSES = (STATUS_DRIFT_DETECTED, STATUS_NO_DRIFT, STATUS_INCOMPLETE_EVIDENCE,
                     STATUS_NOT_AVAILABLE)


class VipVersionDriftDetectionError(ValueError):
    """A caller-usage error -- a malformed subsystem_manifests mapping, or an
    unreadable project root. Raised loudly rather than silently degrading,
    since that is a bug in the CALL, not an honest absence of evidence."""


def assert_no_status_vocabulary_collision(statuses: Optional[tuple] = None) -> None:
    """This module's own status tokens must share no member with
    dv_harness.models.Status -- the same guard several sibling
    domain-vocabulary modules in this codebase already run against
    themselves, so a drift verdict can never be mistaken for a stage-gate
    verdict. `statuses` defaults to this module's own OVERALL_STATUSES; a
    caller may pass a different tuple to prove this guard has real
    detection power against a deliberately-colliding vocabulary."""
    from .models import Status
    verdict_values = {s.value for s in Status}
    collision = verdict_values & set(statuses if statuses is not None else OVERALL_STATUSES)
    if collision:
        raise AssertionError(
            f"vip_version_drift_detection status vocabulary collides with "
            f"dv_harness.models.Status: {sorted(collision)}"
        )


assert_no_status_vocabulary_collision()


def _normalize_package_name(name: Any) -> str:
    return str(name).strip().lower()


def discover_subsystem_manifest_paths(root) -> Dict[str, str]:
    """Real subsystem discovery: environment_mode_router.
    read_registered_subsystem_entries() -- the same runtime registry a real
    SIGNOFF PASS writes into, never a second registry file. Returns
    {subsystem_name: environment_manifest_path}, skipping any entry missing
    either a real `name` or a real `environment_manifest` (an incomplete
    registry entry is not this module's to repair)."""
    entries = environment_mode_router.read_registered_subsystem_entries(Path(root))
    out: Dict[str, str] = {}
    for entry in entries:
        name = entry.get("name")
        manifest_path = entry.get("environment_manifest")
        if name and manifest_path:
            out[str(name)] = str(manifest_path)
    return out


def load_subsystem_vip_release_fact(subsystem_name: str, manifest_path,
                                     project_root=None) -> Dict[str, Any]:
    """Loads ONE subsystem's real env.manifest.json and extracts its
    vip_config.vip_release layer verbatim. Never fabricates: a missing file,
    an unparseable document, a schema-invalid document, or a manifest whose
    vip_release layer is itself not SCANNED all report the honest
    STATUS_SUBSYSTEM_NOT_AVAILABLE with the real reason -- the manifest's own
    reason when one exists, never a guessed one."""
    manifest_path = str(manifest_path)
    path = Path(manifest_path)
    if project_root is not None and not path.is_absolute():
        path = Path(project_root) / path
    try:
        manifest = env_manifest.load_env_manifest(path)
    except env_manifest.EnvManifestValidationError as exc:
        return {
            "subsystem": subsystem_name, "manifest_path": manifest_path,
            "status": STATUS_SUBSYSTEM_NOT_AVAILABLE,
            "reason": f"env.manifest.json at {manifest_path!r} failed schema validation: {exc}",
            "designware_home": None, "packages": [],
        }
    except (OSError, ValueError) as exc:
        return {
            "subsystem": subsystem_name, "manifest_path": manifest_path,
            "status": STATUS_SUBSYSTEM_NOT_AVAILABLE,
            "reason": f"env.manifest.json could not be read at {manifest_path!r}: {exc}",
            "designware_home": None, "packages": [],
        }
    vip_release = ((manifest.get("vip_config") or {}).get("vip_release")) or {}
    if vip_release.get("status") != STATUS_SCANNED:
        return {
            "subsystem": subsystem_name, "manifest_path": manifest_path,
            "status": STATUS_SUBSYSTEM_NOT_AVAILABLE,
            "reason": (vip_release.get("reason")
                       or "vip_config.vip_release layer is not SCANNED in this manifest"),
            "designware_home": vip_release.get("designware_home"),
            "packages": [],
        }
    return {
        "subsystem": subsystem_name, "manifest_path": manifest_path,
        "status": STATUS_SCANNED, "reason": None,
        "designware_home": vip_release.get("designware_home"),
        "packages": list(vip_release.get("packages") or []),
    }


def find_package_version_drift(subsystem_facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups every real installed VIP package across every SCANNED
    subsystem fact by its normalised package `name`, and reports a finding
    for every group whose real `version` values disagree across two or more
    DISTINCT subsystems. A package reported by only one subsystem has
    nothing to compare against and is silently excluded -- that is not
    drift, it is a package only one subsystem happens to use."""
    by_package: Dict[str, List[Dict[str, Any]]] = {}
    for fact in subsystem_facts:
        if fact.get("status") != STATUS_SCANNED:
            continue
        for pkg in fact.get("packages") or []:
            key = _normalize_package_name(pkg.get("name"))
            by_package.setdefault(key, []).append({
                "subsystem": fact["subsystem"],
                "package_name": pkg.get("name"),
                "version": pkg.get("version"),
                "install_path": pkg.get("install_path"),
            })

    findings: List[Dict[str, Any]] = []
    for key in sorted(by_package):
        occurrences = by_package[key]
        distinct_subsystems = {occ["subsystem"] for occ in occurrences}
        if len(distinct_subsystems) < 2:
            continue
        distinct_versions = {occ["version"] for occ in occurrences}
        if len(distinct_versions) > 1:
            findings.append({
                "package_name": key,
                "occurrences": sorted(occurrences, key=lambda o: (o["subsystem"], o["package_name"])),
                "distinct_versions": sorted(
                    (v if v is not None else "NO_VERSION_DIRECTORY") for v in distinct_versions
                ),
            })
    return findings


def _overall_status(subsystem_facts: List[Dict[str, Any]],
                     findings: List[Dict[str, Any]]) -> tuple:
    if not subsystem_facts:
        return STATUS_NOT_AVAILABLE, "no subsystem environments were supplied for comparison"
    if findings:
        names = ", ".join(f["package_name"] for f in findings)
        return (STATUS_DRIFT_DETECTED,
                f"{len(findings)} VIP package(s) show conflicting installed versions across "
                f"subsystem environments: {names}")
    unavailable = [f for f in subsystem_facts if f["status"] != STATUS_SCANNED]
    scanned = [f for f in subsystem_facts if f["status"] == STATUS_SCANNED]
    if unavailable:
        return (STATUS_INCOMPLETE_EVIDENCE,
                f"{len(unavailable)} of {len(subsystem_facts)} declared subsystem environment(s) "
                "have no usable VIP release evidence (see each subsystem's own `reason`), so this "
                "comparison cannot rule out drift involving them")
    if len(scanned) < 2:
        return (STATUS_NOT_AVAILABLE,
                "fewer than two subsystem environments carry real VIP release evidence to "
                "compare against each other")
    return (STATUS_NO_DRIFT,
            "every declared subsystem environment's VIP release evidence was checked and no "
            "shared VIP package shows conflicting installed versions")


def aggregate_vip_version_drift(root, subsystem_manifests: Optional[Dict[str, str]] = None
                                 ) -> Dict[str, Any]:
    """The one entry point. `subsystem_manifests`, when supplied, is a
    caller-declared {subsystem_name: environment_manifest_path} mapping that
    OVERRIDES real registry discovery entirely -- a real, explicit caller
    fact, never merged with the registry (merging an explicit declaration
    with a discovered one would blur which subsystems the caller actually
    asked about). Omitted, the real
    `environment_mode_router.read_registered_subsystem_entries()` registry is
    used instead. Relative manifest paths are resolved against `root`."""
    root = Path(root)
    if subsystem_manifests is not None:
        if not isinstance(subsystem_manifests, dict):
            raise VipVersionDriftDetectionError(
                "subsystem_manifests must be a {subsystem_name: manifest_path} mapping")
        manifests = {str(k): str(v) for k, v in subsystem_manifests.items()}
        source = "caller_declared"
    else:
        manifests = discover_subsystem_manifest_paths(root)
        source = "subsystem_environment_registry"

    subsystem_facts = [
        load_subsystem_vip_release_fact(name, manifests[name], project_root=root)
        for name in sorted(manifests)
    ]
    findings = find_package_version_drift(subsystem_facts)
    status, reason = _overall_status(subsystem_facts, findings)
    return {
        "status": status,
        "reason": reason,
        "source": source,
        "subsystem_count": len(subsystem_facts),
        "subsystems": subsystem_facts,
        "findings": findings,
    }


def render_report_markdown(report: Dict[str, Any]) -> str:
    """Two markdown tables -- per-subsystem status, and every drift finding
    -- reusing connectivity.render_markdown_table(), this repo's one
    parameterized table renderer, rather than a second hand-rolled one."""
    from .connectivity import render_markdown_table

    subsystem_rows = [
        {"subsystem": s["subsystem"], "status": s["status"],
         "package_count": len(s.get("packages") or []), "reason": s.get("reason") or ""}
        for s in report["subsystems"]
    ]
    lines = [
        f"# VIP Version Drift Report ({report['status']})",
        "",
        report["reason"],
        "",
        "## Subsystems",
        render_markdown_table(
            [("subsystem", "Subsystem"), ("status", "Status"),
             ("package_count", "Packages"), ("reason", "Reason")],
            subsystem_rows, empty_note="(no subsystem environments supplied)"),
        "",
        "## Findings",
    ]
    if not report["findings"]:
        lines.append("(no conflicting VIP package versions found)")
    else:
        finding_rows = []
        for f in report["findings"]:
            for occ in f["occurrences"]:
                finding_rows.append({
                    "package": f["package_name"], "subsystem": occ["subsystem"],
                    "version": occ["version"] if occ["version"] is not None else "NO_VERSION_DIRECTORY",
                    "install_path": occ["install_path"] or "",
                })
        lines.append(render_markdown_table(
            [("package", "Package"), ("subsystem", "Subsystem"),
             ("version", "Version"), ("install_path", "Install Path")],
            finding_rows, empty_note="(no rows)"))
    return "\n".join(lines)


def execute_verb(args: List[str]) -> int:
    """Standalone `python -m dv_harness.vip_version_drift_detection` front
    door -- deliberately no `dv-harness` CLI verb, per this task's own
    instruction not to edit cli.py/gates.py/dashboard.py.

    Usage: vip_version_drift_detection --root <dir>
               [--manifests name=path[,name=path...]] [--json]
    Exit 0 STATUS_NO_DRIFT, 1 STATUS_DRIFT_DETECTED, 2 STATUS_INCOMPLETE_EVIDENCE
    or STATUS_NOT_AVAILABLE or a usage error."""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m dv_harness.vip_version_drift_detection")
    parser.add_argument("--root", required=True)
    parser.add_argument("--manifests", default=None,
                         help="comma-separated name=path pairs overriding registry discovery")
    parser.add_argument("--json", action="store_true")
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    subsystem_manifests = None
    if ns.manifests:
        subsystem_manifests = {}
        for pair in ns.manifests.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                print(f"error: --manifests entry {pair!r} is not name=path", file=sys.stderr)
                return 2
            name, _, path = pair.partition("=")
            subsystem_manifests[name.strip()] = path.strip()

    try:
        report = aggregate_vip_version_drift(ns.root, subsystem_manifests)
    except VipVersionDriftDetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if ns.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_report_markdown(report))

    if report["status"] == STATUS_DRIFT_DETECTED:
        return 1
    if report["status"] in (STATUS_INCOMPLETE_EVIDENCE, STATUS_NOT_AVAILABLE):
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> None:
    sys.exit(execute_verb(list(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    main()
