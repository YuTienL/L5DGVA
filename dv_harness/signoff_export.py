"""dv_harness/signoff_export.py -- one-click final signoff export bundle
(vPlan/UVM TB/Test Suite/Report packaging), closing the
"一鍵最終 Signoff 匯出" poster-compliance gap: only individual cards/artifacts
(Audit Trail, Stage Execution Profile) existed with no single "collect
everything into one signoff package" action.

collect_signoff_bundle copies each real candidate artifact under `root` into
`out_dir` ONLY if it actually exists -- never fabricates a placeholder for a
missing one (CLAUDE.md Evidence Truth Rule) -- and always runs a fresh
dv_harness.self_audit.run_self_audit() into the bundle as
self_audit_result.json, since that one is generated, not merely copied.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import self_audit

# Blackboard topic files (dv_harness/blackboard.py: Blackboard writes each
# topic to .dv-harness/blackboard/<topic>.json).
BLACKBOARD_CANDIDATES = [
    "signoff_state.json",
    "regression_state.json",
    "requirements.json",
    "findings.json",
]


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_dir(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def collect_signoff_bundle(root: Path, out_dir: Path) -> Dict[str, Any]:
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, Any]] = []

    def record(artifact: str, present: bool, bundled_rel: Optional[Path]) -> None:
        manifest.append({
            "artifact": artifact,
            "present": present,
            "bundled_path": bundled_rel.as_posix() if bundled_rel is not None else None,
        })

    # 1-4: blackboard state files (.dv-harness/blackboard/<topic>.json).
    for fname in BLACKBOARD_CANDIDATES:
        artifact = f"blackboard/{fname}"
        src = root / ".dv-harness" / "blackboard" / fname
        rel = Path("blackboard") / fname
        if src.exists():
            _copy_file(src, out_dir / rel)
            record(artifact, True, rel)
        else:
            record(artifact, False, None)

    # 5: vPlan output (.dv-harness/vplan/ -- real dir confirmed under this
    # project root; no separate per-run instance file convention exists, so
    # the directory itself is the real candidate).
    src = root / ".dv-harness" / "vplan"
    rel = Path("vplan")
    if src.is_dir():
        _copy_dir(src, out_dir / rel)
        record("vplan", True, rel)
    else:
        record("vplan", False, None)

    # 6: fresh self-audit result -- always generated, never merely copied.
    audit_result = self_audit.run_self_audit(root)
    audit_rel = Path("self_audit_result.json")
    (out_dir / audit_rel).write_text(
        json.dumps(audit_result, ensure_ascii=False, indent=2), encoding="utf-8")
    record("self_audit_result", True, audit_rel)

    # 7: stage execution profile telemetry (.dv-harness/telemetry/ --
    # see dv_harness/stage_profile.py's StageExecutionProfiler).
    src = root / ".dv-harness" / "telemetry"
    rel = Path("telemetry")
    if src.is_dir():
        _copy_dir(src, out_dir / rel)
        record("telemetry", True, rel)
    else:
        record("telemetry", False, None)

    # 8: pattern registry output (.dv-harness/pattern_registry/ -- no such
    # directory convention currently exists anywhere in this project; checked
    # honestly rather than guessed, per CLAUDE.md's Evidence Truth Rule).
    src = root / ".dv-harness" / "pattern_registry"
    rel = Path("pattern_registry")
    if src.is_dir():
        _copy_dir(src, out_dir / rel)
        record("pattern_registry", True, rel)
    else:
        record("pattern_registry", False, None)

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    bundled_count = sum(1 for m in manifest if m["present"])
    missing_count = sum(1 for m in manifest if not m["present"])

    return {
        "status": "OK",
        "out_dir": str(out_dir),
        "manifest": manifest,
        "bundled_count": bundled_count,
        "missing_count": missing_count,
    }
