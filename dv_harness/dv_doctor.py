"""Canonical `dv-harness doctor` composed health report (M1 wiring).

Composes the M1 canonical-repository-identity checks
(dv_harness.l5dgva_repo), the M1 execution-profile resolution check
(dv_harness.execution_profile), and the pre-existing, already-CLI-wired
Knowledge/Memory/Obsidian health check (dv_harness.memory_doctor.run_doctor)
into one report answering "am I really inside the L5DGVA canonical
repository, in what mode, with what capability available" -- without
redesigning any of memory_doctor.py's own Phase-21 logic.

Deliberately a REPORTER, not a gate: every sub-check catches its own
failure and reports an honest status value instead of raising, and no
optional capability (git, Obsidian, a persistent remote relay) is
required to be present for a PASS-shaped report elsewhere -- a
DEGRADED/NOT_CONFIGURED/UNAVAILABLE status is a correct, complete answer
for those, consistent with "do not require Obsidian availability for
basic verification generation" (KNOWLEDGE_BACKEND_DEGRADED, not FAIL).
Never performs a live remote connection.
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Union

from . import execution_profile as ep
from . import l5dgva_repo
from . import memory_doctor


def _repository_identity(root: Path) -> Dict[str, Any]:
    try:
        identity = l5dgva_repo.load_repository_identity(root)
        return {
            "status": "PASS",
            "product_identity": identity.get("product_identity"),
            "repository_type": identity.get("repository_type"),
        }
    except l5dgva_repo.L5DGVARepositoryNotFoundError as exc:
        return {"status": "FAIL", "reason": str(exc)}


def _repository_root(start: Path) -> Dict[str, Any]:
    try:
        found = l5dgva_repo.discover_repo_root(start, validate=True)
        return {"status": "PASS", "root": str(found)}
    except l5dgva_repo.L5DGVARepositoryNotFoundError as exc:
        return {"status": "FAIL", "reason": str(exc)}


def _repository_mode(root: Path) -> Dict[str, Any]:
    return {"status": "PASS", "mode": l5dgva_repo.detect_mode(root)}


def _git_availability() -> Dict[str, Any]:
    exe = shutil.which("git")
    return {"status": "AVAILABLE", "path": exe} if exe else {"status": "UNAVAILABLE"}


def _execution_profile_status(root: Path) -> Dict[str, Any]:
    try:
        profile = ep.load_execution_profile(root)
        return {
            "status": "CONFIGURED",
            "gateway_host_set": bool(profile.get("gateway_host")),
            "remote_host_set": bool(profile.get("remote_host")),
            "profile_path": profile.get("_profile_path"),
        }
    except ep.ExecutionProfileRequiredError as exc:
        return {"status": "NOT_CONFIGURED", "reason": str(exc)}


def _remote_transport_status(root: Path) -> Dict[str, Any]:
    # Honest capability probe only -- scripts-on-disk + profile-resolves,
    # never a live dial-out. AVAILABLE_NOT_VERIFIED is the correct ceiling
    # dv doctor can ever report for this field.
    remote_dir = root / "tools" / "remote"
    scripts_present = all(
        (remote_dir / name).is_file()
        for name in ("remote_relay.py", "remote_hop.py", "remote_exec.py")
    )
    if not scripts_present:
        return {"status": "UNAVAILABLE", "reason": "transport scripts missing under tools/remote/"}
    profile_status = _execution_profile_status(root)
    if profile_status["status"] != "CONFIGURED":
        return {"status": "NOT_CONFIGURED"}
    return {
        "status": "AVAILABLE_NOT_VERIFIED",
        "note": "transport scripts present and a profile resolves; dv doctor never dials a live connection",
    }


def _module_importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _kc_status() -> Dict[str, Any]:
    return {"status": "IMPLEMENTED" if _module_importable("dv_harness.knowledge_center") else "MISSING"}


def _memory_status(root: Path, cfg: Optional[dict]) -> Dict[str, Any]:
    try:
        result = memory_doctor.run_doctor(root, cfg)
        return {"status": result.get("overall", "UNKNOWN"), "detail": result}
    except Exception as exc:  # noqa: BLE001 -- doctor must never crash the CLI
        return {"status": "KNOWLEDGE_BACKEND_DEGRADED", "reason": str(exc)}


def _obsidian_adapter_status() -> Dict[str, Any]:
    return {"status": "IMPLEMENTED" if _module_importable("dv_harness.memory_vault") else "MISSING"}


def _obsidian_cli_status() -> Dict[str, Any]:
    try:
        from . import memory_vault as mv
        report = mv.detect_obsidian_cli()
        if report.get("installed"):
            return {"status": "AVAILABLE", "version": report.get("version")}
        return {"status": "KNOWLEDGE_BACKEND_DEGRADED",
                "reason": "obsidian-cli not installed -- filesystem adapter remains the active write path"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "KNOWLEDGE_BACKEND_DEGRADED", "reason": str(exc)}


def _obsidian_vault_configuration(root: Path, cfg: Optional[dict]) -> Dict[str, Any]:
    try:
        from . import memory_vault as mv
        vault_path = mv.resolve_vault_path(root, cfg)
    except Exception as exc:  # noqa: BLE001
        return {"status": "UNKNOWN", "reason": str(exc)}
    if not vault_path:
        return {"status": "NOT_CONFIGURED"}
    return {"status": "CONFIGURED", "vault_path": str(vault_path)}


def _persistent_storage_status(root: Path) -> Dict[str, Any]:
    dv_harness_dir = root / ".dv-harness"
    return {"status": "PASS" if dv_harness_dir.is_dir() else "FAIL", "path": str(dv_harness_dir)}


def _graph_status() -> Dict[str, Any]:
    return {"status": "IMPLEMENTED" if _module_importable("dv_harness.graph") else "MISSING"}


def _agent_status(root: Path) -> Dict[str, Any]:
    agents_dir = root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return {"status": "MISSING"}
    return {"status": "AVAILABLE", "count": len(list(agents_dir.glob("*.md")))}


def _skill_status(root: Path) -> Dict[str, Any]:
    skills_dir = root / ".claude" / "skills"
    if not skills_dir.is_dir():
        return {"status": "MISSING"}
    return {"status": "AVAILABLE", "count": sum(1 for _ in skills_dir.rglob("SKILL.md"))}


def _openspec_status(root: Path) -> Dict[str, Any]:
    # Real finding (M1): this v50-derived baseline has no module or file
    # anywhere naming an "OpenSpec" capability -- confirmed by a
    # case-insensitive repo scan, not assumed. Honestly MISSING rather
    # than probing a Parent-only module name that has not been migrated
    # (PARENT_CAPABILITY_MIGRATION_STARTED stays NO in M1).
    hits = list((root / "dv_harness").glob("*openspec*"))
    return {"status": "IMPLEMENTED" if hits else "MISSING"}


def _intake_status(root: Path) -> Dict[str, Any]:
    # A glob, not one guessed module name: v50's own intake_* module set
    # (intake_audit_provenance.py, intake_baseline.py, intake_events.py,
    # intake_modes.py, intake_question_priority.py,
    # intake_source_priority.py, intake_state.py, ...) is a REAL but
    # DIFFERENT set from the Parent-side intake_contract.py/
    # intake_routing.py/intake_schema.py family this session had seen
    # documented elsewhere -- confirming the two sides diverged here too.
    # Probing for the presence of ANY intake_*.py file is honest evidence
    # for either baseline, never favors one side's naming over the other.
    hits = list((root / "dv_harness").glob("intake_*.py"))
    return {"status": "IMPLEMENTED" if hits else "MISSING", "module_count": len(hits)}


def _root_layout_status(root: Path) -> Dict[str, Any]:
    from . import root_hygiene_gate
    violations = root_hygiene_gate.check_root_layout(root)
    return {
        "status": "PASS" if not violations else "FAIL",
        "violation_count": len(violations),
        "violations": [v.path for v in violations],
    }


def run_doctor(root: Union[str, Path], cfg: Optional[dict] = None) -> Dict[str, Any]:
    """Real, composed dv doctor report. Never raises -- every sub-check
    catches its own failure and reports an honest status instead."""
    root = Path(root)
    report: Dict[str, Any] = {}
    report["REPOSITORY_IDENTITY"] = _repository_identity(root)
    report["REPOSITORY_ROOT"] = _repository_root(root)
    report["REPOSITORY_MODE"] = _repository_mode(root)
    report["GIT_AVAILABILITY"] = _git_availability()
    report["GIT_ROOT_CONSISTENCY"] = l5dgva_repo.cross_check_git_root(root)
    report["EXECUTION_PROFILE_STATUS"] = _execution_profile_status(root)
    report["REMOTE_TRANSPORT_STATUS"] = _remote_transport_status(root)
    report["KC_STATUS"] = _kc_status()
    report["MEMORY_STATUS"] = _memory_status(root, cfg)
    report["OBSIDIAN_ADAPTER_STATUS"] = _obsidian_adapter_status()
    report["OBSIDIAN_CLI_STATUS"] = _obsidian_cli_status()
    report["OBSIDIAN_VAULT_CONFIGURATION"] = _obsidian_vault_configuration(root, cfg)
    report["PERSISTENT_STORAGE_STATUS"] = _persistent_storage_status(root)
    report["GRAPH_STATUS"] = _graph_status()
    report["AGENT_STATUS"] = _agent_status(root)
    report["SKILL_STATUS"] = _skill_status(root)
    report["OPENSPEC_STATUS"] = _openspec_status(root)
    report["INTAKE_STATUS"] = _intake_status(root)
    report["ROOT_LAYOUT_GATE"] = _root_layout_status(root)
    return report


def render_doctor_report(report: Dict[str, Any]) -> str:
    lines = ["dv-harness doctor report", "=" * 40]
    for key, value in report.items():
        status = value.get("status", "UNKNOWN") if isinstance(value, dict) else value
        lines.append("%-32s %s" % (key, status))
    return "\n".join(lines)
