"""dv_harness/subsystem_contract.py -- ONE authoritative
`SubsystemVerificationContract` record, ASSEMBLED, never re-derived.

THE GAP THIS CLOSES
-------------------
A subsystem's verification truth -- which spec/DUT/TB it was verified against,
which protocols/interfaces it exercises, what its requirements say, what its
vPlan/test/coverage correspondence looks like, whether regression passed,
whether SIGNOFF happened and against what frozen baseline, which evidence and
reproducibility capsules back it, which waivers apply to it -- already exists
as REAL, separately-queryable facts across `env_manifest.py`,
`requirement_contract.py`, `golden_scenario.py`, `signoff_export.py` and
`waiver_store.py`. Nothing assembled them into ONE record a human (or a later
audit) could read without re-running six different readers and manually
cross-referencing their outputs. Two audits of the same project could
therefore describe the "verification contract" of a subsystem differently,
even though every fact each drew on was identical.

WHAT THIS MODULE IS NOT
-----------------------
  * It is not a NEW evidence source. Every field is read through an
    already-real function this repo already ships; nothing here re-parses RTL,
    re-runs a gate, re-derives a hash, or re-implements a status vocabulary a
    cited module already owns. Where a value genuinely has no producer in this
    repo (`spec_version` with nothing declared, a requirement-contract file
    nobody has written, an evidence database that was never created), the
    field is `NOT_AVAILABLE` with the real reason -- never guessed, never
    silently omitted, and never collapsed with a *different* kind of absence
    (a missing manifest is not the same fact as a manifest that failed schema
    validation, and both are reported by their own distinct reason string).
  * It DECIDES, ARBITRATES and WRITES NO GOVERNANCE STATE. No stage runs, no
    gate script is invoked, no build/regression/LSF submission starts, no
    approval is minted. `ControlPlane.approve()`, `policy.can_signoff()`,
    `assert_human_approval()`, `HumanApprovalRequiredError`,
    `ProductionWriteNotAuthorizedError` and the PR-only main/master governance
    are untouched and unreferenced. There is deliberately no stage gate: a
    gate that passed because a contract record existed, or failed because one
    did not, would be worse than none.
  * `assemble_subsystem_contract()` itself is READ-ONLY -- it constructs no
    `StateStore`, mints no `.dv-harness/` tree, and creates no evidence
    database or memory store where none exists (every reader it calls already
    honours that contract on its own: `env_manifest.default_manifest_path()`
    returns `None` rather than generating, `signoff_export.read_signoff_stage_
    status()` reads state.json with a plain `json.loads` rather than
    `StateStore.load()`, `golden_scenario._open_store()` returns `None` for an
    absent evidence.duckdb rather than creating one, `waiver_store.
    status_report()` reports `NO_WAIVER_STORE` rather than minting a ledger).
    Persisting the assembled record to
    `.dv-harness/subsystem_contract.json` is a SEPARATE, explicit act
    (`write_subsystem_contract()` / the `snapshot` verb) -- assembling and
    reading a project's own truth must never itself become new truth about
    that project.

WHAT EACH FIELD REUSES, AND WHY NOT SOMETHING ELSE
---------------------------------------------------
  * `spec_version` / `dut_sha` / `tb_sha` -- `signoff_export.capture_baseline()`,
    LIVE (not the frozen copy): that function is already section 238's real,
    tested reader for exactly these three identities (a content fingerprint of
    the declared RTL via `connectivity_check.compute_rtl_fingerprint()` for
    `dut_sha`, the real generated TB source tree for `tb_sha`, and a
    human-declared `spec_version` recorded as attested-not-derived). Building
    a second RTL/TB fingerprinter here would silently diverge from the one
    `just connectivity-check` and every signoff bundle already trust.
  * `protocols` / `interfaces` / `vplan_tests_coverage` --
    `env_manifest.load_env_manifest()` plus `env_manifest.
    summarize_for_blackboard()` (the SAME prompt-sized summary the
    `env_manifest` Blackboard topic already carries onto every reading stage,
    reused rather than re-flattening the manifest a second way).
    `protocols` is the distinct `vip_type` values off `vip_config.vip_instances`
    and `interfaces` is those instances' own `instance_path` bindings --
    literally the environment's declared DUT/VIP interface points, never
    invented topology. `vplan_tests_coverage` is `env_topology.
    testplan_correspondence` verbatim, carrying its own COMPUTED/PARTIAL/
    NOT_AVAILABLE status and reason exactly as the manifest recorded them.
  * `requirements` -- `requirement_contract.execute_verb()`, given a
    requirement-contract-shaped JSON file. This repo has no fixed producer
    path for that file yet (the same disclosed boundary
    `generation_readiness.py`'s Spec Parsing / Requirement IR row already
    states), so a caller may pass `requirements_path` explicitly; absent that,
    a small set of conventional per-project locations is checked and, finding
    none, the field is `NOT_AVAILABLE` naming exactly what was looked for --
    never a fabricated "no requirements" verdict standing in for "nobody told
    me where to look".
  * `regression` -- `regression_reporter.load_jobs()` +
    `dashboard._lsf_summary()`, the same real per-job LSF summary
    `golden_flow_readiness.py`'s own LSF Regression row already reads (DV
    PASS/FAIL counts, never `lsf_status` alone -- LSF DONE is not DV PASS).
  * `signoff` -- `signoff_export.read_signoff_stage_status()` for the
    real-time stage verdict, PLUS -- only when one was ever recorded --
    `signoff_export.load_freeze()` / `evaluate_freeze_invalidation()` for the
    frozen baseline a real gate-verified SIGNOFF produced and whether it is
    still `VALID` now. A project that has never frozen a baseline reports
    `NO_SIGNOFF_FREEZE_RECORDED` rather than a live re-capture standing in for
    "the signoff baseline" section 238 names -- a baseline is a thing someone
    froze, not a thing this module recomputes on request.
  * `evidence_references` / `reproducibility_capsules` --
    `golden_scenario.py`'s own `evidence_db.EvidenceStore` (opened exactly the
    way `golden_scenario._open_store()` already does, read-only, absent ->
    `None` rather than created) backs both: `evidence_references` is the real
    `normalized_evidence` rows (the same table/columns
    `golden_scenario._fetch_normalized_evidence()` already reads, unfiltered
    here rather than looked up by one id), and `reproducibility_capsules` is
    `golden_scenario.evaluate_store_freshness()` -- the real capsule list AND
    its real FRESH/STALE/UNKNOWN freshness verdict, never a bare listing that
    hides whether a capsule is still good to reuse.
  * `waivers` -- `waiver_store.status_report()`, EXPLICITLY (not
    `signoff_export`'s own digest-only waiver capture): this module wants the
    full per-waiver DERIVED status (VALID/EXPIRED/REVALIDATION_REQUIRED/
    REVOKED/UNKNOWN, TH-7), not an identity hash of the ledger.

SUBSYSTEM SCOPE
---------------
When a caller names `subsystem`, `environment_mode_router.
read_registered_subsystem_entries()` -- the real registry
`engine._persist_subsystem_registry_entry()` writes ONLY on a gate-verified
SIGNOFF PASS for that subsystem -- is consulted for a matching entry. Finding
one narrows the manifest lookup to that entry's own `environment_manifest`
path; finding none does not fail the assembly, it records
`SUBSYSTEM_NOT_REGISTERED` (a real, named unknown) and falls back to the
project's own default `env.manifest.json` -- most subsystem-mode/IP-level
projects in this repo have never reached a registered SIGNOFF and still have a
real single-environment contract worth assembling. Omitting `subsystem`
entirely assembles the project-scope contract, which is the common case this
repo's own USB example represents.

`unknowns` IS THE HONESTY SURFACE. Every field this module could not assemble
lands there as `{"field", "reason"}` -- never silently dropped from the
record and never defaulted to an empty-but-present value. `completeness` is
`COMPLETE` (zero unknowns), `NOT_AVAILABLE` (every tracked aspect unknown --
a bare, uninitialized root), or `PARTIAL` (anything between), scored against a
fixed denominator (`TRACKED_ASPECTS`) so the count itself cannot silently grow
or shrink.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import environment_mode_router as emr
from . import env_manifest as em
from . import golden_scenario as gs
from . import requirement_contract as rc
from . import signoff_export as se
from . import waiver_store as ws

SCHEMA_VERSION = "1.0"

STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_PRESENT = "PRESENT"

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
NOT_AVAILABLE_OVERALL = "NOT_AVAILABLE"
COMPLETENESS_CLASSES: Tuple[str, ...] = (COMPLETE, PARTIAL, NOT_AVAILABLE_OVERALL)

#: Every aspect this contract tracks, in assembly order. A fixed denominator
#: for `completeness` scoring -- never a list a caller can silently widen or
#: narrow by adding/removing an `unknowns` entry elsewhere.
TRACKED_ASPECTS: Tuple[str, ...] = (
    "spec_version", "dut_sha", "tb_sha", "protocols_interfaces", "requirements",
    "vplan_tests_coverage", "regression", "signoff_baseline_freeze",
    "evidence_references", "reproducibility_capsules", "waivers",
)

#: Conventional per-project locations checked for a requirement-contract file
#: when the caller does not name one. This repo has no fixed producer for this
#: artifact (see module docstring); these are candidate CONSUMPTION locations
#: only, never invented content.
DEFAULT_REQUIREMENTS_CANDIDATES: Tuple[str, ...] = (
    ".dv-harness/requirements/requirement_contract.json",
    ".dv-harness/requirements.json",
    ".dv-harness/traceability/requirement_contract.json",
)


class SubsystemContractError(Exception):
    """Base for every refusal in this module."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable(reason: str, **detail: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"status": STATUS_NOT_AVAILABLE, "reason": reason}
    out.update(detail)
    return out


# ---------------------------------------------------------------------------
# Subsystem scope resolution -- environment_mode_router's real registry
# ---------------------------------------------------------------------------

def _resolve_subsystem_scope(root: Path, subsystem: Optional[str]
                              ) -> Tuple[Dict[str, Any], Optional[str]]:
    """(scope, unknown_reason_or_None). `scope["registry_entry"]` is the full
    real registered entry (environment_manifest/release_sha/qualification_
    state/interface_compatibility/clock_reset_compatibility) when one was
    found -- never fabricated fields for a subsystem that was never
    registered."""
    if not subsystem:
        return {"requested": None, "resolved_name": None,
                "source": "PROJECT_SCOPE_NO_SUBSYSTEM_REQUESTED",
                "registry_entry": None}, None
    entries = emr.read_registered_subsystem_entries(root)
    match = next((e for e in entries
                  if str(e.get("name", "")).strip().lower() == subsystem.strip().lower()),
                 None)
    if match is not None:
        return {"requested": subsystem, "resolved_name": match.get("name"),
                "source": "REGISTERED_SUBSYSTEM_ENTRY", "registry_entry": match}, None
    reason = (
        f"subsystem {subsystem!r} requested but has no entry in "
        f"{emr.registry_path(root)} -- registry entries are written only on a real "
        "gate-verified SIGNOFF PASS for that subsystem "
        "(environment_mode_router.read_registered_subsystem_entries()); falling back to "
        "this project's own default env.manifest.json for spec/dut/vip facts")
    return {"requested": subsystem, "resolved_name": None,
            "source": "SUBSYSTEM_NOT_REGISTERED", "registry_entry": None}, reason


def _resolve_manifest_path(root: Path, manifest_path: Optional[str],
                            registry_entry: Optional[Dict[str, Any]]) -> Optional[Path]:
    if manifest_path:
        return Path(manifest_path)
    if registry_entry and registry_entry.get("environment_manifest"):
        candidate = Path(str(registry_entry["environment_manifest"]))
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_file():
            return candidate
    return em.default_manifest_path(root)


# ---------------------------------------------------------------------------
# env.manifest.json -- protocols / interfaces / vplan+tests+coverage
# ---------------------------------------------------------------------------

def _env_manifest_section(manifest_path: Optional[Path]
                           ) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """(protocols, interfaces, vip_config_block, vplan_tests_coverage_block).

    `vip_config_block["status"]` and `vplan_tests_coverage["status"]` are the
    REAL statuses `env_manifest.py` itself records for those two layers
    (`CAPTURED`/`NOT_AVAILABLE` for vip_config; `COMPUTED`/`PARTIAL`/
    `NOT_AVAILABLE` for testplan_correspondence) -- never remapped into a
    second vocabulary this module would then have to keep in sync."""
    if manifest_path is None or not Path(manifest_path).is_file():
        reason = ("no env.manifest.json found" +
                  (f" at {manifest_path}" if manifest_path else
                   " (env_manifest.default_manifest_path() resolved nothing)"))
        vip_block = _unavailable(reason, manifest_path=str(manifest_path) if manifest_path else None)
        tp_block = _unavailable(reason)
        return [], [], vip_block, tp_block
    try:
        manifest = em.load_env_manifest(manifest_path)
    except Exception as exc:
        reason = (f"env.manifest.json at {manifest_path} failed schema validation: "
                  f"{type(exc).__name__}: {exc}")
        vip_block = _unavailable(reason, manifest_path=str(manifest_path))
        tp_block = _unavailable(reason)
        return [], [], vip_block, tp_block

    summary = em.summarize_for_blackboard(manifest, manifest_path=manifest_path)
    vip_cfg = summary.get("vip_config") or {}
    instances = vip_cfg.get("instances") or []
    protocols = sorted({i["vip_type"] for i in instances if i.get("vip_type")})
    interfaces = [
        {"instance_path": i.get("instance_path"), "vip_type": i.get("vip_type"),
         "config_field_count": i.get("config_field_count")}
        for i in instances
    ]
    vip_block = {"status": vip_cfg.get("status") or STATUS_NOT_AVAILABLE,
                 "reason": vip_cfg.get("reason"),
                 "instance_count": vip_cfg.get("instance_count", len(instances)),
                 "manifest_path": str(manifest_path)}
    tp_block = dict((summary.get("env_topology") or {}).get("testplan_correspondence") or {})
    if not tp_block:
        tp_block = _unavailable("env.manifest.json carries no env_topology.testplan_correspondence")
    return protocols, interfaces, vip_block, tp_block


# ---------------------------------------------------------------------------
# requirements -- requirement_contract.execute_verb() over a real file
# ---------------------------------------------------------------------------

def _requirements_section(root: Path, requirements_path: Optional[str]) -> Dict[str, Any]:
    checked: List[str] = []
    if requirements_path:
        candidates = [Path(requirements_path)]
    else:
        candidates = [root / rel for rel in DEFAULT_REQUIREMENTS_CANDIDATES]
    chosen: Optional[Path] = None
    for c in candidates:
        checked.append(str(c))
        if c.is_file():
            chosen = c
            break
    if chosen is None:
        return _unavailable(
            "no requirement-contract artifact found; this repo has no fixed producer path "
            "for one yet -- pass requirements_path explicitly, or place one at one of the "
            "checked locations",
            checked_paths=checked)
    text, _code = rc.execute_verb(str(chosen), as_json=True)
    try:
        result = json.loads(text)
    except ValueError:
        return _unavailable(f"requirement_contract.execute_verb() returned unparseable output "
                            f"for {chosen}", checked_paths=checked)
    result["source_path"] = str(chosen)
    if result.get("status") == "NOT_AVAILABLE" and "reason" not in result:
        result["reason"] = "requirement_contract reported NOT_AVAILABLE with no reason"
    return result


# ---------------------------------------------------------------------------
# regression -- regression_reporter.load_jobs() + dashboard._lsf_summary()
# ---------------------------------------------------------------------------

def _regression_section(root: Path) -> Dict[str, Any]:
    jobs_dir = root / ".dv-harness" / "lsf" / "jobs"
    if not jobs_dir.is_dir():
        return _unavailable("NO_RECORDED_JOBS", expected=str(jobs_dir))
    from . import regression_reporter
    from .dashboard import _lsf_summary
    jobs = regression_reporter.load_jobs(root)
    if not jobs:
        return _unavailable("NO_RECORDED_JOBS", expected=str(jobs_dir))
    summary = dict(_lsf_summary(jobs))
    summary["status"] = STATUS_PRESENT
    return summary


# ---------------------------------------------------------------------------
# signoff -- real-time stage status, plus the frozen baseline if one exists
# ---------------------------------------------------------------------------

def _signoff_baseline_freeze_section(root: Path) -> Dict[str, Any]:
    freeze = se.load_freeze(root)
    if freeze is None:
        return _unavailable(
            "NO_SIGNOFF_FREEZE_RECORDED",
            hint="freeze one via signoff_export.freeze_signoff_baseline() (or "
                 "`python -m dv_harness.signoff_export freeze --frozen-by <name>`) after a "
                 "real gate-verified SIGNOFF -- a signoff baseline is a thing someone froze, "
                 "not a thing this module recomputes on request")
    try:
        invalidation = se.evaluate_freeze_invalidation(root, freeze)
    except Exception as exc:
        invalidation = {"status": "UNKNOWN", "reason": f"{type(exc).__name__}: {exc}"}
    fields = ((freeze.get("baseline") or {}).get("fields") or {})
    return {
        "status": STATUS_PRESENT,
        "freeze_id": freeze.get("freeze_id"),
        "frozen_at": freeze.get("frozen_at"),
        "frozen_by": freeze.get("frozen_by"),
        "bundle_kind": freeze.get("bundle_kind"),
        "invalidation_status": invalidation.get("status"),
        "invalidation_findings": invalidation.get("findings", []),
        "spec_version": fields.get("spec_version"),
        "dut_sha": fields.get("dut_sha"),
        "tb_sha": fields.get("tb_sha"),
    }


# ---------------------------------------------------------------------------
# evidence_references / reproducibility_capsules -- one shared evidence store
# ---------------------------------------------------------------------------

def _evidence_and_capsules_section(root: Path, db_path: Optional[str]
                                    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    store = gs._open_store(root, db_path, read_only=True)
    if store is None:
        from .evidence_db import default_db_path
        expected = db_path or str(default_db_path(root))
        na = _unavailable("NO_EVIDENCE_DATABASE", expected=expected)
        return dict(na), dict(na)
    try:
        rows = store.query(
            "SELECT evidence_id, source_kind, job_id, pattern, protocol, verdict "
            "FROM normalized_evidence ORDER BY evidence_id")
        cols = ("evidence_id", "source_kind", "job_id", "pattern", "protocol", "verdict")
        items = [dict(zip(cols, r)) for r in rows]
        if items:
            evidence_section: Dict[str, Any] = {
                "status": STATUS_PRESENT, "count": len(items), "items": items}
        else:
            evidence_section = _unavailable("NO_NORMALIZED_EVIDENCE_ROWS")

        capsule_report = gs.evaluate_store_freshness(root, store)
        if capsule_report.get("status") == "NOT_AVAILABLE":
            capsule_section: Dict[str, Any] = _unavailable("NO_GOLDEN_SCENARIO_CAPSULES_RECORDED")
        else:
            capsule_section = dict(capsule_report)
            capsule_section["freshness_status"] = capsule_report.get("status")
            capsule_section["status"] = STATUS_PRESENT
    except Exception as exc:
        na = _unavailable(f"evidence database unreadable: {type(exc).__name__}: {exc}")
        return dict(na), dict(na)
    finally:
        store.close()
    return evidence_section, capsule_section


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_subsystem_contract(root, *, subsystem: Optional[str] = None,
                                 manifest_path: Optional[str] = None,
                                 requirements_path: Optional[str] = None,
                                 db_path: Optional[str] = None,
                                 declared_spec_version: Optional[str] = None
                                 ) -> Dict[str, Any]:
    """Assemble ONE SubsystemVerificationContract record over `root`.

    Read-only: no store, state file or `.dv-harness/` tree is created to
    answer any field (see module docstring). Every field either carries real
    content from an already-real reader or is `NOT_AVAILABLE` with a real
    reason recorded in that field AND in `unknowns`.
    """
    root = Path(root).resolve()
    unknowns: List[Dict[str, str]] = []

    def _note(field: str, reason: Optional[str]) -> None:
        unknowns.append({"field": field, "reason": reason or f"{field} not available"})

    scope, scope_reason = _resolve_subsystem_scope(root, subsystem)
    if scope_reason:
        _note("subsystem_scope", scope_reason)

    declared = {"spec_version": declared_spec_version} if declared_spec_version else {}
    try:
        baseline = se.capture_baseline(root, declared)
        bl_fields = baseline["fields"]
    except Exception as exc:
        # capture_baseline() captures all fifteen section-238 fields in one
        # call, including several this contract does not otherwise need
        # (assertion_status, dashboard_snapshot, ...). A failure in one of
        # those must not crash this whole assembly -- it is reported as an
        # honest NOT_AVAILABLE on the three fields this contract DOES use,
        # never silently swallowed.
        reason = f"signoff_export.capture_baseline() raised {type(exc).__name__}: {exc}"
        bl_fields = {name: _unavailable(reason) for name in ("spec_version", "dut_sha", "tb_sha")}
    for name in ("spec_version", "dut_sha", "tb_sha"):
        if bl_fields[name]["status"] != se.CAPTURED:
            _note(name, bl_fields[name]["reason"])

    resolved_manifest_path = _resolve_manifest_path(root, manifest_path, scope.get("registry_entry"))
    protocols, interfaces, vip_block, tp_block = _env_manifest_section(resolved_manifest_path)
    if vip_block.get("status") == STATUS_NOT_AVAILABLE:
        _note("protocols_interfaces", vip_block.get("reason"))
    if tp_block.get("status") == STATUS_NOT_AVAILABLE:
        _note("vplan_tests_coverage", tp_block.get("reason"))

    requirements_section = _requirements_section(root, requirements_path)
    if requirements_section.get("status") == STATUS_NOT_AVAILABLE:
        _note("requirements", requirements_section.get("reason"))

    regression_section = _regression_section(root)
    if regression_section.get("status") == STATUS_NOT_AVAILABLE:
        _note("regression", regression_section.get("reason"))

    signoff_stage = se.read_signoff_stage_status(root)
    signoff_baseline_freeze = _signoff_baseline_freeze_section(root)
    if signoff_baseline_freeze.get("status") == STATUS_NOT_AVAILABLE:
        _note("signoff_baseline_freeze", signoff_baseline_freeze.get("reason"))

    evidence_section, capsule_section = _evidence_and_capsules_section(root, db_path)
    if evidence_section.get("status") == STATUS_NOT_AVAILABLE:
        _note("evidence_references", evidence_section.get("reason"))
    if capsule_section.get("status") == STATUS_NOT_AVAILABLE:
        _note("reproducibility_capsules", capsule_section.get("reason"))

    waivers_report = ws.status_report(root)
    if waivers_report.get("status") == "NOT_AVAILABLE":
        _note("waivers", waivers_report.get("reason") or "NO_WAIVER_STORE")

    tracked_total = len(TRACKED_ASPECTS)
    unavailable_count = len(unknowns) - (1 if scope_reason else 0)
    unavailable_count = max(unavailable_count, 0)
    if unavailable_count == 0:
        completeness = COMPLETE
    elif unavailable_count >= tracked_total:
        completeness = NOT_AVAILABLE_OVERALL
    else:
        completeness = PARTIAL

    return {
        "schema_version": SCHEMA_VERSION,
        "assembled_at": _now_iso(),
        "project_root": str(root),
        "subsystem": scope,
        "spec_version": bl_fields["spec_version"],
        "dut_sha": bl_fields["dut_sha"],
        "tb_sha": bl_fields["tb_sha"],
        "protocols": protocols,
        "interfaces": interfaces,
        "vip_config": vip_block,
        "requirements": requirements_section,
        "vplan_tests_coverage": tp_block,
        "regression": regression_section,
        "signoff": {"stage": signoff_stage, "baseline_freeze": signoff_baseline_freeze},
        "evidence_references": evidence_section,
        "reproducibility_capsules": capsule_section,
        "waivers": waivers_report,
        "unknowns": unknowns,
        "tracked_aspect_count": tracked_total,
        "unavailable_aspect_count": unavailable_count,
        "completeness": completeness,
    }


CONTRACT_RELPATH = Path(".dv-harness") / "subsystem_contract.json"


def write_subsystem_contract(root, record: Dict[str, Any]) -> Path:
    """Persist `record` to `<root>/.dv-harness/subsystem_contract.json`.

    Only when called on a real project root: `root` itself must already
    exist. This is a separate, explicit write -- `assemble_subsystem_contract()`
    never calls it, so reading a project's contract never mutates the project."""
    root = Path(root)
    if not root.is_dir():
        raise SubsystemContractError(f"not a real project root (does not exist): {root}")
    out_path = root / CONTRACT_RELPATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Rendering + shared front door (execute_verb -> `assemble`/`snapshot`)
# ---------------------------------------------------------------------------

def render_contract_text(record: Dict[str, Any]) -> str:
    subsystem = record["subsystem"]
    lines = [
        f"SUBSYSTEM VERIFICATION CONTRACT: {record['completeness']} "
        f"({record['project_root']})",
        f"  subsystem: {subsystem.get('requested') or '(project scope)'}  "
        f"source: {subsystem.get('source')}",
        f"  spec_version={record['spec_version']['status']}  "
        f"dut_sha={record['dut_sha']['status']}  tb_sha={record['tb_sha']['status']}",
        f"  protocols: {', '.join(record['protocols']) or '(none)'}   "
        f"interfaces: {len(record['interfaces'])}",
        f"  requirements={record['requirements'].get('status')}  "
        f"vplan/tests/coverage={record['vplan_tests_coverage'].get('status')}",
        f"  regression={record['regression'].get('status')}  "
        f"signoff_stage={record['signoff']['stage'].get('stage_status')}  "
        f"signoff_baseline_freeze={record['signoff']['baseline_freeze'].get('status')}",
        f"  evidence_references={record['evidence_references'].get('status')}  "
        f"reproducibility_capsules={record['reproducibility_capsules'].get('status')}  "
        f"waivers={record['waivers'].get('status')}",
        "",
    ]
    if record["unknowns"]:
        lines.append(f"UNKNOWNS ({len(record['unknowns'])}):")
        for u in record["unknowns"]:
            lines.append(f"  - {u['field']}: {u['reason']}")
    else:
        lines.append("no unknowns -- every tracked aspect was assembled from a real source")
    if record.get("written_to"):
        lines.append(f"\nwritten to {record['written_to']}")
    return "\n".join(lines)


_EXIT_CODES = {COMPLETE: 0, PARTIAL: 1, NOT_AVAILABLE_OVERALL: 2}


def execute_verb(verb: str, *, root, subsystem: Optional[str] = None,
                  manifest_path: Optional[str] = None,
                  requirements_path: Optional[str] = None,
                  db_path: Optional[str] = None,
                  declared_spec_version: Optional[str] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.subsystem_contract
    assemble|snapshot`. Returns (text, exit_code): 0 COMPLETE, 1 PARTIAL,
    2 NOT_AVAILABLE (a bare/uninitialized root) or a usage error.
    `assemble` reads only; `snapshot` additionally writes
    `.dv-harness/subsystem_contract.json`."""
    if verb not in ("assemble", "snapshot"):
        msg = f"unknown subsystem-contract verb {verb!r} (expected assemble|snapshot)"
        return (json.dumps({"status": "NOT_AVAILABLE", "reason": msg}) if as_json else msg), 2
    root = Path(root)
    record = assemble_subsystem_contract(
        root, subsystem=subsystem, manifest_path=manifest_path,
        requirements_path=requirements_path, db_path=db_path,
        declared_spec_version=declared_spec_version)
    if verb == "snapshot":
        written = write_subsystem_contract(root, record)
        record["written_to"] = str(written)
    code = _EXIT_CODES[record["completeness"]]
    text = json.dumps(record, indent=2) if as_json else render_contract_text(record)
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.subsystem_contract",
        description="Assemble one authoritative SubsystemVerificationContract record from "
                    "this project's existing real readers (env_manifest, requirement_contract, "
                    "golden_scenario, signoff_export, waiver_store). 'assemble' reads only; "
                    "'snapshot' additionally writes .dv-harness/subsystem_contract.json.")
    ap.add_argument("verb", choices=("assemble", "snapshot"))
    ap.add_argument("--root", default=".")
    ap.add_argument("--subsystem", default=None,
                    help="Registered subsystem name (environment_mode_router registry). "
                         "Omit for project scope.")
    ap.add_argument("--manifest", default=None, dest="manifest_path",
                    help="Explicit env.manifest.json path (default: this project's own).")
    ap.add_argument("--requirements", default=None, dest="requirements_path",
                    help="Requirement-contract JSON file (default: a few conventional paths).")
    ap.add_argument("--db", default=None, dest="db_path",
                    help="Evidence database path (default: <root>/.dv-harness/evidence/evidence.duckdb).")
    ap.add_argument("--declared-spec-version", default=None,
                    help="A human-declared spec version (attested, never machine-verified).")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.verb, root=a.root, subsystem=a.subsystem, manifest_path=a.manifest_path,
            requirements_path=a.requirements_path, db_path=a.db_path,
            declared_spec_version=a.declared_spec_version, as_json=a.json)
    except SubsystemContractError as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
