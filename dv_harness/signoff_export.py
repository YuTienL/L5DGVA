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

BUG FIX (2026-08-31, poster-gap-closing-round2 Task 7): the bundle used to
stop at blackboard state / vPlan / telemetry / pattern registry / self-audit,
never packaging the real generated UVM testbench source or a regression/
test-suite manifest even though the harness generates both elsewhere (see
dv_harness/uvm_generator/protocol_env_generator.py and
dv_harness/uvm_generator/regression_list_manager.py). Added `tb_source` and
`regression_manifest` candidates below, following the exact same
copy-if-real/report-absence-honestly pattern already used for every other
candidate.

BUG FIX (2026-08-31, Task 7 review round 2): `tb_source`'s first cut checked
one hardcoded guessed path (`.dv-harness/generated_uvm_env/tb`) that no
generator, skill doc, or template anywhere in this project ever writes to --
ProtocolEnvGenerator's `--out` is always caller-supplied with no default
(tools/generate_protocol_uvm_environment.py, every PROTOCOL_BUILDERS
SKILL.md). That made the candidate real-but-unwired: it would report
"absent" for essentially every real invocation, even right after a
successful generation run. Replaced with `_find_tb_source_dir`, which
DISCOVERS the real output location by locating the marker file
ProtocolEnvGenerator itself writes (environment_manifest.json,
qualification_status ENV_GENERATED -- protocol_env_generator.py's own
`generate()`) alongside a real `tb/` subdirectory, wherever it was actually
generated under `root`.

BUG FIX (2026-08-31, poster-gap-closing-round2 fix wave, finding C1): an
unrestricted `root.rglob("environment_manifest.json")` also matches demo/
example trees that are NOT this project's real testbench source -- against
the real repo it matched a dozen `examples/generated_usb_real_evidence_v*/`
fixture trees and would silently bundle one of them into the signoff
deliverable as if it were real TB source (confidently wrong, worse than
honestly reporting absence). `_find_tb_source_dir` now excludes
`examples/`, `.claude/worktrees/` (nested worktrees carry their own copies
of this whole project), `.claude/skills/_deprecated/`, and the signoff
export's own `out_dir` (so a previous export's bundled copy is never
rediscovered as if it were a fresh generation on a later run) from the
search scope.
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


# Directory-name markers that, if present anywhere in a manifest's path
# parts (relative to `root`), disqualify it from being real signoff TB
# source -- see finding C1 in the fix-wave report for the concrete
# false-positive this excludes (examples/generated_usb_real_evidence_v*/).
_TB_SOURCE_EXCLUDED_PARTS = {"examples", ".git"}


def _is_excluded_tb_source_path(rel_parts: tuple, out_dir_rel_parts: Optional[tuple]) -> bool:
    parts = list(rel_parts)
    for excluded in _TB_SOURCE_EXCLUDED_PARTS:
        if excluded in parts:
            return True
    # ".claude/worktrees/<name>/..." -- nested worktrees carry their own full
    # copy of this project (including its own examples/ and .dv-harness/),
    # none of which is real TB source for THIS signoff run.
    if len(parts) >= 2 and parts[0] == ".claude" and parts[1] == "worktrees":
        return True
    # ".claude/skills/_deprecated/..." -- retired skill fixtures/snapshots.
    if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "skills" and parts[2] == "_deprecated":
        return True
    # The signoff export's own out_dir -- excluded so a PREVIOUS export's
    # bundled tb_source/ copy is never rediscovered as if it were a fresh
    # generation on a later run into a different/same out_dir under root.
    if out_dir_rel_parts is not None and tuple(parts[:len(out_dir_rel_parts)]) == out_dir_rel_parts:
        return True
    return False


def _find_tb_source_dir(root: Path, out_dir: Optional[Path] = None) -> Optional[Path]:
    """Discover ProtocolEnvGenerator's real output location instead of
    guessing one -- its `--out` is always caller-supplied with no fixed
    default anywhere in this project (tools/generate_protocol_uvm_environment.py,
    every .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md), so a single hardcoded
    candidate path would report "absent" for essentially every real
    invocation.

    Searches `root` for the marker file ProtocolEnvGenerator itself writes --
    environment_manifest.json with "qualification_status": "ENV_GENERATED"
    (protocol_env_generator.py's generate(), line ~88) -- next to a real
    `tb/` subdirectory. The `tb/` check matters: the older, deprecated flat
    generator.py path stamps the SAME qualification_status onto its own
    environment_manifest.json (confirmed on-disk at
    examples/generated_pcie_uvm_env/environment_manifest.json) but never
    creates a tb/ subdirectory at all -- only ProtocolEnvGenerator's real
    tb/agents,env,seq,tests,top subdirectory-shaped output qualifies as real
    TB source.

    Matches under `examples/`, `.claude/worktrees/`,
    `.claude/skills/_deprecated/`, or `out_dir` itself are excluded from the
    search scope entirely (see `_is_excluded_tb_source_path`) -- these are
    demo/example/nested-copy/previous-export locations, never this run's
    real signoff TB source, even when they carry a byte-identical
    ENV_GENERATED marker + tb/ shape.

    If more than one real match exists, the most recently modified manifest
    wins (the freshest generation run is the one relevant to a current
    signoff); returns None -- honest absence, never a guess -- if none do.
    """
    out_dir_rel_parts = None
    if out_dir is not None:
        try:
            out_dir_rel_parts = Path(out_dir).resolve().relative_to(root).parts
        except ValueError:
            out_dir_rel_parts = None  # out_dir is outside root -- nothing to exclude

    candidates = []
    for manifest_path in root.rglob("environment_manifest.json"):
        rel_parts = manifest_path.relative_to(root).parts
        if _is_excluded_tb_source_path(rel_parts, out_dir_rel_parts):
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("qualification_status") != "ENV_GENERATED":
            continue
        tb_dir = manifest_path.parent / "tb"
        if tb_dir.is_dir():
            candidates.append((manifest_path.stat().st_mtime, tb_dir))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


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

    # 9: UVM testbench source -- discovered via _find_tb_source_dir (see its
    # docstring): ProtocolEnvGenerator's real tb/agents,env,seq,tests,top
    # subdirectory-shaped output, located by its own environment_manifest.json
    # marker rather than a guessed fixed path, since no such fixed default
    # exists anywhere in this project.
    tb_src = _find_tb_source_dir(root, out_dir)
    rel = Path("tb_source")
    if tb_src is not None:
        _copy_dir(tb_src, out_dir / rel)
        record("tb_source", True, rel)
    else:
        record("tb_source", False, None)

    # 10: regression/test-suite manifest (.dv-harness/regression.list -- the
    # plain grep/comm-friendly PASS-list format dv_harness/uvm_generator/
    # regression_list_manager.py's record_verdict/record_suite produce,
    # written at the REGRESSION_LIST default pinned in
    # .claude/templates/Makefile.patterns.mk and tools/regression_list_cli.py).
    src = root / ".dv-harness" / "regression.list"
    rel = Path("regression.list")
    if src.is_file():
        _copy_file(src, out_dir / rel)
        record("regression_manifest", True, rel)
    else:
        record("regression_manifest", False, None)

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
