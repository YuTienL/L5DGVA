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

HARDENING (2026-09-01, trust-boundary-hardening design pass): the exported
`manifest.json`'s "bundle_hash" field previously had ZERO real producer
anywhere in this codebase -- tools/verification_flow/
signoff_bundle_completeness_gate.py required an agent-self-reported
"bundle_hash" string with nothing to recompute it against. `compute_bundle_hash`
is the real producer, modeled on tools/remote/source_identity.py's
`aggregate_source_id` (sort deterministic per-artifact lines, newline-join,
sha256 hex digest); `collect_signoff_bundle` now calls it for real and
writes the result into both its return dict and `manifest.json`'s own
content, so the gate can read the real manifest.json back and recompute the
same hash independently rather than trusting a bare self-reported value.

GATE-AWARENESS (2026-09-04, mechanism #8 Qualification/Signoff Engine
gap-close): this module knew nothing about the SIGNOFF stage gate. A
re-audit ran `dv-harness signoff-export` against this repo's own real
`.dv-harness/state.json` -- `current_stage: ENV_CHECK`,
`stages["SIGNOFF"]["status"] == "NOT_STARTED"`, zero `"SIGNOFF"` records in
any `events.jsonl`, no
`.dv-harness/soc-composer/subsystem_environment_registry.json` -- and got
back a `status: OK` bundle indistinguishable from one produced after a real
gate-verified signoff. The bundled `self_audit_result.json` made that worse:
it is `self_audit.run_self_audit()`, a HARNESS meta-integrity check over the
harness's own registries/schemas, NOT the 9 real `gates.STAGE_GATES["SIGNOFF"]`
gates (false_pass_resistance_gate, evidence_freshness_gate,
signoff_trace_crosscheck_gate, ...) -- so a complete-looking bundle proved
nothing about whether the project's SIGNOFF gate battery had ever run.

`read_signoff_stage_status()` reads the REAL, harness-owned
`.dv-harness/state.json` / `events.jsonl` / subsystem registry (never an
agent-attested claim) and `collect_signoff_bundle()` stamps the result into
`signoff_stage_status.json` inside the bundle, into `manifest.json`'s
top-level `signoff_stage` key, and into its own return dict, plus a
`bundle_kind` of `SIGNOFF_GATE_VERIFIED` vs `PRE_SIGNOFF_GATE_INPUT`.
`require_signoff_pass=True` (`dv-harness signoff-export
--require-signoff-pass`) turns that into a hard refusal that writes nothing.

Why refusal is OPT-IN and not the default: `signoff_bundle_completeness_gate`
-- one of those 9 SIGNOFF gates -- takes a real `bundle_dir` produced by this
function as its INPUT and recomputes `compute_bundle_hash()` over its real
manifest.json. A bundle therefore has to be producible BEFORE SIGNOFF can
pass; defaulting to refusal would make the SIGNOFF gate battery unsatisfiable
by construction. The honest fix is that a pre-gate bundle can no longer look
like a gate-verified one, not that pre-gate bundles are forbidden.

`engine.py:_export_signoff_bundle()` is the real production-path caller that
produces the `SIGNOFF_GATE_VERIFIED` bundle, on an actual gate-verified
SIGNOFF PASS.

SIGNOFF FREEZE / BASELINE (2026-09-06, spec section 238): the bundle above
packages ARTIFACTS. Section 238 asks for something the bundle did not carry:
a frozen, reproducible BASELINE naming fifteen identity fields (spec version,
requirement/vPlan version, DUT SHA, TB SHA, agent/skill versions, VIP/tool
versions, schema/policy versions, configuration, test list, coverage
databases, assertion status, waivers, evidence hashes/references, dashboard
snapshot, reproducibility capsules), plus the rule that "post-freeze material
changes trigger impact analysis and invalidate/revalidate affected signoff
evidence". Neither existed: `compute_bundle_hash()` hashes only
`artifact:present:bundled_path` -- artifact PRESENCE, never artifact CONTENT
-- so a bundled file could be replaced wholesale without moving the hash, and
nothing anywhere recorded a baseline that a later run could be compared
against. `grep -rn "freeze|frozen"` over `dv_harness/`/`tools/` matched only
`frozenset`.

`capture_baseline()` derives all fifteen fields from REAL producers this
project already has, or reports NOT_AVAILABLE with the real reason -- never a
fabricated version string. `freeze_signoff_baseline()` records one immutable
freeze record; `evaluate_freeze_invalidation()` re-derives the same baseline
NOW and reports VALID / INVALIDATED / UNKNOWN, running the same
`change_impact.changed_files()` + `classify_risk()` post-freeze impact
analysis `golden_scenario.evaluate_freshness()` already uses, so "did the
design move" has one answer in this codebase.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    # REAL COMPAT BUG (found deploying to the real remote server, Python
    # 3.7): shutil.copytree()'s dirs_exist_ok kwarg was only added in
    # Python 3.8. Manual recursive merge-copy below works identically on
    # every Python 3.x version without relying on any version-gated stdlib
    # kwarg (no distutils.dir_util.copy_tree either -- that module was
    # removed entirely in Python 3.12, which would just trade one
    # incompatibility for the opposite one).
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _copy_dir(item, target)
        else:
            shutil.copy2(item, target)


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


def compute_bundle_hash(manifest: List[Dict[str, Any]]) -> str:
    """The real, independently-recomputable `bundle_hash` producer -- closes
    the fact that no code anywhere in this project ever produced this value
    before (signoff_bundle_completeness_gate.py required a self-reported
    "bundle_hash" string with nothing real to check it against).

    Modeled on tools/remote/source_identity.py's aggregate_source_id: sort
    "{artifact}:{present}:{bundled_path}" lines (deterministic regardless of
    the manifest list's own order), newline-join, sha256 hex digest. Any
    caller with the real manifest content (e.g. a gate reading manifest.json
    back off disk) can recompute the identical value independently.
    """
    lines = sorted(
        f"{m.get('artifact')}:{m.get('present')}:{m.get('bundled_path')}"
        for m in manifest
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# The one stage-status value that means the 9 real gates.STAGE_GATES["SIGNOFF"]
# gates were actually satisfied by engine.run_stage() (which is the only
# writer of stages[...]["status"] == "PASS" for a gate-mapped stage).
SIGNOFF_VERIFIED_STATUS = "PASS"
# Returned as stage_status when the project has no state.json at all, or its
# state.json carries no `stages` map (a real shape found in this repo:
# .work/_e2e_demo_usb3_lfps/.dv-harness/state.json is a 3-key stub). This is
# deliberately NOT collapsed into "NOT_STARTED" -- "the harness never recorded
# a SIGNOFF stage here" and "the harness recorded that SIGNOFF has not started"
# are different facts, and only one of them is evidence about the project.
SIGNOFF_STATUS_NOT_RECORDED = "NOT_RECORDED"


def read_signoff_stage_status(root: Path) -> Dict[str, Any]:
    """Read the REAL SIGNOFF stage-gate outcome for the project at `root`.

    Every field comes from a harness-written file, never from an agent claim:
      - `.dv-harness/state.json` -> `stages["SIGNOFF"]["status"]` (written
        only by engine.run_stage()/storage.StateStore.save()),
      - `.dv-harness/events.jsonl` -> how many audit-trail records name the
        SIGNOFF stage at all,
      - `.dv-harness/soc-composer/subsystem_environment_registry.json` -> the
        file engine._persist_subsystem_registry_entry() writes ONLY on a real
        SIGNOFF PASS, so its presence is independent corroboration.

    Deliberately reads state.json with a plain json.loads instead of going
    through storage.StateStore: StateStore.load() CREATES a state.json (and
    the whole .dv-harness dir) when none exists, which would make merely
    exporting a bundle mutate the project's governance state and turn
    "this project has no recorded SIGNOFF" into "this project has a freshly
    minted NOT_STARTED SIGNOFF". An export must never write governance state.
    """
    root = Path(root)
    state_path = root / ".dv-harness" / "state.json"
    events_path = root / ".dv-harness" / "events.jsonl"
    registry_path = root / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"

    stage_status = SIGNOFF_STATUS_NOT_RECORDED
    current_stage: Optional[str] = None
    state_present = state_path.is_file()
    if state_present:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if isinstance(state, dict):
            current_stage = state.get("current_stage")
            stages = state.get("stages")
            if isinstance(stages, dict) and isinstance(stages.get("SIGNOFF"), dict):
                stage_status = stages["SIGNOFF"].get("status") or SIGNOFF_STATUS_NOT_RECORDED

    signoff_event_count = 0
    if events_path.is_file():
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("stage") == "SIGNOFF":
                    signoff_event_count += 1
        except OSError:
            pass

    # Imported lazily: gates.py pulls in the whole gate-registry module, and
    # signoff_export is also imported by tools/verification_flow/
    # signoff_bundle_completeness_gate.py, which must stay a cheap subprocess.
    from .gates import STAGE_GATES
    required_gates = [gid for gid, _, _ in STAGE_GATES.get("SIGNOFF", [])]

    # EVIDENCE PROVENANCE (2026-09-06, TH-9). Signoff is exactly where a
    # headline claim gets believed, so the bundle a human reads before signing
    # must say which of those claims nothing but the agent stands behind.
    # `summarize_project_provenance()` reads the same state.json this function
    # already read, with the same plain read_text/json.loads (never
    # StateStore, which would MINT one) -- so asking the question still cannot
    # bring a project's governance state into existence.
    from .evidence_provenance import summarize_project_provenance

    return {
        "state_file_present": state_present,
        "current_stage": current_stage,
        "stage_status": stage_status,
        "gate_verified": stage_status == SIGNOFF_VERIFIED_STATUS,
        "signoff_event_count": signoff_event_count,
        "subsystem_registry_present": registry_path.is_file(),
        "required_signoff_gates": required_gates,
        "evidence_provenance": summarize_project_provenance(root),
    }


# ===========================================================================
# SIGNOFF FREEZE / BASELINE -- spec section 238 (2026-09-06)
# ===========================================================================

FREEZE_SCHEMA_VERSION = "1.0"

#: Per-field capture outcome. CAPTURED means a REAL producer answered;
#: NOT_AVAILABLE means nothing in this project can answer it and says why.
#: A NOT_AVAILABLE field is never collapsed into a captured-but-empty one --
#: "this project records no coverage database" and "this project's coverage
#: database is empty" are different facts about a signoff baseline.
CAPTURED = "CAPTURED"
NOT_AVAILABLE = "NOT_AVAILABLE"

#: Invalidation verdict for a frozen baseline. VALID/UNKNOWN are spelled the
#: same way `waiver_store.derive_status()` already spells them (one project
#: vocabulary for "still good" / "we could not check"); INVALIDATED is
#: section 238's own word. None of the three is a member of
#: `models.Status` -- a freeze verdict is not a stage-gate verdict.
FREEZE_VALID = "VALID"
FREEZE_INVALIDATED = "INVALIDATED"
FREEZE_UNKNOWN = "UNKNOWN"

#: Worst-wins, and UNKNOWN outranks VALID for the same reason
#: `platform_health.HEALTH_SEVERITY` puts UNKNOWN above HEALTHY: an
#: unmeasurable field must never be reported as a still-good one.
_FREEZE_SEVERITY = {FREEZE_VALID: 0, FREEZE_UNKNOWN: 1, FREEZE_INVALIDATED: 2}

#: A finding either invalidates the freeze or leaves it indeterminate.
SEV_INVALIDATING = "INVALIDATING"
SEV_INDETERMINATE = "INDETERMINATE"

#: Spec section 238's own baseline list, verbatim and in its own order,
#: normalized only into identifier form. `assert_baseline_covers_section_238()`
#: holds this tuple and the capture table equal in BOTH directions at import,
#: so a field can never be silently dropped from a freeze record and a capture
#: function can never quietly add a sixteenth field section 238 does not name.
SECTION_238_FIELDS: Tuple[str, ...] = (
    "spec_version",
    "requirement_vplan_version",
    "dut_sha",
    "tb_sha",
    "agent_skill_versions",
    "vip_tool_versions",
    "schema_policy_versions",
    "configuration",
    "test_list",
    "coverage_databases",
    "assertion_status",
    "waivers",
    "evidence_hashes",
    "dashboard_snapshot",
    "reproducibility_capsules",
)

#: The harness's own root (the directory holding `dv_harness/`, `tools/` and
#: `.claude/`) -- the agent/skill/schema/policy identity fields describe the
#: HARNESS that produced a signoff, which is not necessarily the project being
#: signed off (a deployed project runs its own copy from elsewhere).
_HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _tree_manifest(base: Path) -> Dict[str, str]:
    """{relative posix path: sha256} for every real file under `base`, so a
    directory has a content identity that is independent of filesystem
    enumeration order (`_aggregate` sorts)."""
    base = Path(base)
    out: Dict[str, str] = {}
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*")):
        if p.is_file():
            try:
                out[p.relative_to(base).as_posix()] = _sha256_file(p)
            except OSError:
                continue
    return out


def _aggregate(manifest: Dict[str, str]) -> str:
    """Collapse a {name: digest} manifest into one token, through the real,
    already-tested `tools/remote/source_identity.aggregate_source_id()` --
    the same primitive `harness_deploy.py` uses to compute a SOURCE_ID and
    `server_sync_identity_gate.py` uses to verify one. There is no second
    aggregation rule in this codebase."""
    from .harness_deploy import aggregate_source_id
    return aggregate_source_id(manifest)


def _artifact_content_digest(path: Path) -> Optional[str]:
    p = Path(path)
    try:
        if p.is_dir():
            return _aggregate(_tree_manifest(p))
        if p.is_file():
            return _sha256_file(p)
    except OSError:
        return None
    return None


def _baseline_field(name: str, status: str, *, reason: str,
                    source: Optional[str] = None,
                    digest: Optional[str] = None,
                    detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "field": name,
        "status": status,
        "reason": reason,
        "source": source,
        "digest": digest,
        "detail": detail or {},
    }


def _files_field(name: str, root: Path, rel_paths: Sequence[str], *,
                 absent_reason: str) -> Dict[str, Any]:
    """A baseline field whose identity is the content of a fixed set of real
    files. Absent files are named as absent rather than skipped, so a field
    that loses a file after the freeze diverges instead of quietly matching."""
    present: Dict[str, str] = {}
    missing: List[str] = []
    for rel in rel_paths:
        p = Path(root) / rel
        if p.is_file():
            present[rel] = _sha256_file(p)
        elif p.is_dir():
            for sub, digest in _tree_manifest(p).items():
                present[f"{rel}/{sub}"] = digest
        else:
            missing.append(rel)
    if not present:
        return _baseline_field(name, NOT_AVAILABLE, reason=absent_reason,
                               detail={"looked_for": list(rel_paths)})
    return _baseline_field(name, CAPTURED, reason="REAL_ARTIFACT_CONTENT",
                           source=", ".join(rel_paths),
                           digest=_aggregate(present),
                           detail={"files": present, "absent": missing})


# --- the fifteen capture functions ----------------------------------------
# Each takes (project_root, declared) and returns one baseline field. Each
# reads a REAL producer or reports NOT_AVAILABLE naming the missing one --
# nothing here invents a version, a SHA or a status.


def _capture_spec_version(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    value = (declared or {}).get("spec_version")
    if value:
        return _baseline_field(
            "spec_version", CAPTURED, reason="DECLARED_BY_FREEZING_HUMAN",
            source="caller-declared", digest=_sha256_text(value),
            detail={"value": str(value), "attested": True,
                    "machine_verified": False})
    return _baseline_field(
        "spec_version", NOT_AVAILABLE, reason="NO_SPEC_VERSION_PRODUCER",
        detail={"explanation":
                "the only `spec_revision` anywhere in this codebase is "
                "agent-attested evidence-block text (dv_harness/prompts.py); "
                "no artifact producer writes a spec version, and freezing an "
                "agent's own claim as a baseline FACT would break the Evidence "
                "Truth Rule. A human may declare one explicitly, which is then "
                "recorded as attested rather than derived."})


def _capture_requirement_vplan_version(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    return _files_field(
        "requirement_vplan_version", root,
        [".dv-harness/vplan", ".dv-harness/requirements.csv"],
        absent_reason="NO_VPLAN_OR_TRACEABILITY_REGISTRY")


def _capture_dut_sha(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """The DUT identity is the real CONTENT fingerprint of the RTL this
    project declares, computed by `connectivity_check.compute_rtl_fingerprint()`
    -- the same function the standing `just connectivity-check` recipe uses to
    decide whether the RTL moved. Never a git SHA standing in for RTL content
    (a git SHA moves when a README moves), and never a guess: a project with no
    `.dv-harness/connectivity_check.json` has not declared what its RTL IS, and
    that is reported rather than approximated."""
    from . import connectivity_check as cc
    cfg_path = Path(root) / cc.DEFAULT_CONFIG_RELPATH
    if not cfg_path.is_file():
        return _baseline_field(
            "dut_sha", NOT_AVAILABLE, reason="CONNECTIVITY_CHECK_NOT_CONFIGURED",
            detail={"expected_config": str(cfg_path),
                    "explanation": "this project has not declared its RTL source "
                                   "globs, so there is no declared DUT to fingerprint"})
    try:
        cfg = cc.load_config(cfg_path)
        fp = cc.compute_rtl_fingerprint(root, cfg.rtl_sources)
    except Exception as exc:  # config error / unreadable RTL
        return _baseline_field(
            "dut_sha", NOT_AVAILABLE, reason="RTL_FINGERPRINT_FAILED",
            source=str(cfg_path), detail={"error": f"{type(exc).__name__}: {exc}"})
    if not fp.get("file_count"):
        return _baseline_field(
            "dut_sha", NOT_AVAILABLE, reason="RTL_SOURCES_MATCH_NO_FILES",
            source=str(cfg_path),
            detail={"rtl_sources": list(cfg.rtl_sources)})
    return _baseline_field(
        "dut_sha", CAPTURED, reason="REAL_RTL_CONTENT_FINGERPRINT",
        source=f"{cc.DEFAULT_CONFIG_RELPATH} -> connectivity_check.compute_rtl_fingerprint()",
        digest=fp["fingerprint"],
        detail={"file_count": fp["file_count"], "files": fp["files"]})


def _capture_tb_sha(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """Content identity of the real generated testbench source -- discovered
    by the SAME `_find_tb_source_dir()` the bundle itself uses, so the frozen
    TB SHA and the bundled `tb_source/` can never describe different trees."""
    tb_dir = _find_tb_source_dir(Path(root))
    if tb_dir is None:
        return _baseline_field(
            "tb_sha", NOT_AVAILABLE, reason="NO_GENERATED_TB_SOURCE",
            detail={"explanation":
                    "no ENV_GENERATED environment_manifest.json beside a real tb/ "
                    "directory was found under this project root (see "
                    "_find_tb_source_dir)"})
    files = _tree_manifest(tb_dir)
    return _baseline_field(
        "tb_sha", CAPTURED, reason="REAL_TB_SOURCE_CONTENT",
        source=str(tb_dir), digest=_aggregate(files),
        detail={"file_count": len(files),
                "tb_source_dir": str(tb_dir)})


def _capture_agent_skill_versions(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """Which agent/skill assets produced this signoff, as one aggregate
    identity over the REAL `.claude/skills` + `.claude/agents` trees resolved
    through `harness_deploy.load_manifest()`/`collect_local_files()` -- the
    module that already owns "what the harness IS". No skill declares a
    version string anywhere in this repo, so content identity is the only
    honest answer; a version field would have to be invented."""
    try:
        from . import harness_deploy as hd
        manifest = hd.load_manifest()
        files = [f for f in hd.collect_local_files(_HARNESS_ROOT, manifest)
                 if f.startswith(".claude/skills/") or f.startswith(".claude/agents/")]
    except Exception as exc:
        return _baseline_field(
            "agent_skill_versions", NOT_AVAILABLE,
            reason="HARNESS_ASSET_SCAN_FAILED",
            detail={"error": f"{type(exc).__name__}: {exc}"})
    if not files:
        return _baseline_field(
            "agent_skill_versions", NOT_AVAILABLE,
            reason="NO_AGENT_OR_SKILL_ASSETS",
            source=str(_HARNESS_ROOT),
            detail={"explanation": "no .claude/skills or .claude/agents files "
                                   "under the harness root"})
    per_file = hd.compute_local_manifest(_HARNESS_ROOT, files)
    return _baseline_field(
        "agent_skill_versions", CAPTURED, reason="REAL_HARNESS_ASSET_CONTENT",
        source=f"{_HARNESS_ROOT} :: .claude/skills + .claude/agents",
        digest=_aggregate(per_file),
        detail={"harness_root": str(_HARNESS_ROOT),
                "skill_file_count": sum(1 for f in files if f.startswith(".claude/skills/")),
                "agent_file_count": sum(1 for f in files if f.startswith(".claude/agents/"))})


def _capture_vip_tool_versions(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """`env.manifest.json`'s `vip_config.vip_release` -- the real filesystem
    scan of `$DESIGNWARE_HOME` `env_manifest.scan_designware_home()` performs.
    Its OWN status/reason is carried verbatim: a NOT_AVAILABLE VIP release
    stays NOT_AVAILABLE here rather than being summarized away."""
    mpath = Path(root) / ".dv-harness" / "env.manifest.json"
    if not mpath.is_file():
        return _baseline_field(
            "vip_tool_versions", NOT_AVAILABLE, reason="NO_ENV_MANIFEST",
            detail={"expected": str(mpath),
                    "producer": "dv-harness env-manifest generate"})
    try:
        doc = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _baseline_field(
            "vip_tool_versions", NOT_AVAILABLE, reason="ENV_MANIFEST_MALFORMED",
            source=str(mpath), detail={"error": str(exc)})
    release = ((doc.get("vip_config") or {}).get("vip_release")
               if isinstance(doc, dict) else None)
    if not isinstance(release, dict):
        return _baseline_field(
            "vip_tool_versions", NOT_AVAILABLE,
            reason="ENV_MANIFEST_HAS_NO_VIP_RELEASE_LAYER", source=str(mpath))
    packages = release.get("packages")
    if release.get("status") != "AVAILABLE" or not packages:
        return _baseline_field(
            "vip_tool_versions", NOT_AVAILABLE,
            reason=f"VIP_RELEASE_{release.get('status') or 'UNKNOWN'}",
            source=str(mpath),
            detail={"layer_status": release.get("status"),
                    "layer_reason": release.get("reason")})
    pinned = {}
    for pkg in packages if isinstance(packages, list) else []:
        if isinstance(pkg, dict) and pkg.get("name"):
            pinned[str(pkg["name"])] = str(pkg.get("version") or "UNKNOWN")
    return _baseline_field(
        "vip_tool_versions", CAPTURED, reason="REAL_VIP_INSTALL_SCAN",
        source=f"{mpath} :: vip_config.vip_release",
        digest=_aggregate(pinned), detail={"packages": pinned})


def _capture_schema_policy_versions(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """The harness-owned schema + policy-as-data files a signoff was produced
    under. Content identity, not a declared version: these files carry no
    version field, and the whole point of freezing them is that an edit to a
    schema or a policy JSON after signoff is exactly a 'schema/policy version'
    change section 238 wants surfaced."""
    per_file: Dict[str, str] = {}
    schemas = _HARNESS_ROOT / "dv_harness" / "schemas"
    for rel, digest in _tree_manifest(schemas).items():
        per_file[f"dv_harness/schemas/{rel}"] = digest
    for rel in ("dv_harness/context_budget.policy.json",
                "dv_harness/harness_deploy.manifest.json",
                "dv_harness/doc_extraction_categories.json"):
        p = _HARNESS_ROOT / rel
        if p.is_file():
            per_file[rel] = _sha256_file(p)
    graph = Path(root) / ".dv-harness" / "graph" / "main_graph.json"
    if graph.is_file():
        per_file[".dv-harness/graph/main_graph.json"] = _sha256_file(graph)
    if not per_file:
        return _baseline_field(
            "schema_policy_versions", NOT_AVAILABLE,
            reason="NO_SCHEMA_OR_POLICY_FILES_FOUND",
            detail={"harness_root": str(_HARNESS_ROOT)})
    return _baseline_field(
        "schema_policy_versions", CAPTURED, reason="REAL_SCHEMA_AND_POLICY_CONTENT",
        source=f"{_HARNESS_ROOT} :: dv_harness/schemas + policy JSONs; "
               f"{root} :: .dv-harness/graph/main_graph.json",
        digest=_aggregate(per_file), detail={"file_count": len(per_file)})


def _capture_configuration(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    return _files_field("configuration", root, [".dv-harness/config.json"],
                        absent_reason="NO_PROJECT_CONFIG")


def _capture_test_list(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """The regression/test-suite identity: the `regression.list` PASS-list
    `regression_list_manager.py` maintains, plus the REGRESSION_SELECT-computed
    selection `change_impact.compute_and_write()` writes."""
    return _files_field(
        "test_list", root,
        [".dv-harness/regression.list",
         ".dv-harness/regression/computed_selection.json"],
        absent_reason="NO_REGRESSION_LIST_OR_COMPUTED_SELECTION")


def _capture_coverage_databases(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """The real coverage artifacts `dashboard._read_coverage_state()` reads --
    the coverage tool's own summary plus the sample history
    `dashboard.append_coverage_history_sample()` accumulates."""
    return _files_field(
        "coverage_databases", root,
        [".dv-harness/coverage/summary.json", ".dv-harness/coverage/history.json"],
        absent_reason="NO_COVERAGE_SUMMARY_OR_HISTORY")


def _capture_assertion_status(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """Assertion outcome per real recorded job. `lsf_client.JobState` carries
    `assertion_failure` (set by the real sim-log reconciliation, not by an
    agent), so the frozen assertion status is the set of
    (job, assertion_failure, uvm_fatal_count, uvm_error_count) tuples across
    every job this project actually recorded."""
    jobs_dir = Path(root) / ".dv-harness" / "lsf" / "jobs"
    if not jobs_dir.is_dir():
        return _baseline_field(
            "assertion_status", NOT_AVAILABLE, reason="NO_RECORDED_JOBS",
            detail={"expected": str(jobs_dir),
                    "producer": "lsf_client.save_job_state()"})
    job_files = sorted(jobs_dir.glob("*.json"))
    if not job_files:
        # A jobs/ directory holding only a README (this repo's own real
        # shape) is "no job was ever recorded", not "the records are
        # unreadable" -- two different operator problems.
        return _baseline_field(
            "assertion_status", NOT_AVAILABLE, reason="NO_RECORDED_JOBS",
            source=str(jobs_dir),
            detail={"producer": "lsf_client.save_job_state()"})
    per_job: Dict[str, str] = {}
    failing = 0
    for p in job_files:
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(st, dict):
            continue
        jid = str(st.get("job_id") or p.stem)
        assertion_failure = bool(st.get("assertion_failure"))
        if assertion_failure:
            failing += 1
        per_job[jid] = _sha256_text(
            f"{assertion_failure}|{st.get('uvm_fatal_count')}|"
            f"{st.get('uvm_error_count')}|{st.get('sim_status')}")
    if not per_job:
        return _baseline_field(
            "assertion_status", NOT_AVAILABLE, reason="NO_READABLE_JOB_RECORDS",
            source=str(jobs_dir))
    return _baseline_field(
        "assertion_status", CAPTURED, reason="REAL_RECORDED_JOB_STATE",
        source=str(jobs_dir), digest=_aggregate(per_job),
        detail={"job_count": len(per_job), "jobs_with_assertion_failure": failing})


def _capture_waivers(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """Every recorded waiver with the status `waiver_store.derive_status()`
    DERIVES for it right now -- the same ledger the three real waiver gates
    read (TH-7). Freezing the derived status is what makes a waiver that
    EXPIRES after signoff show up as a post-freeze material change."""
    from . import waiver_store
    report = waiver_store.status_report(Path(root))
    if report.get("status") == "NOT_AVAILABLE":
        return _baseline_field(
            "waivers", NOT_AVAILABLE, reason=report.get("reason") or "NO_WAIVER_STORE",
            detail={"path": report.get("path")})
    rows = {str(r.get("waiver_id")): f"{r.get('status')}" for r in report.get("waivers") or []}
    if not rows:
        return _baseline_field(
            "waivers", NOT_AVAILABLE, reason="WAIVER_LEDGER_EMPTY",
            detail={"path": report.get("path")})
    return _baseline_field(
        "waivers", CAPTURED, reason="REAL_WAIVER_LEDGER_DERIVED_STATUS",
        source=".dv-harness/waivers/waivers.json -> waiver_store.status_report()",
        digest=_aggregate(rows),
        detail={"waiver_count": len(rows), "not_valid": report.get("not_valid"),
                "statuses": rows})


def _capture_evidence_hashes(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """`normalized_evidence.evidence_id` is `vip_distill`'s OWN deterministic
    content hash of the real evidence, so the set of evidence ids in the
    evidence store IS section 238's "evidence hashes/references". Read-only:
    a store that does not exist is never created to answer this."""
    from .evidence_db import default_db_path
    db = default_db_path(Path(root))
    if not Path(db).exists():
        return _baseline_field(
            "evidence_hashes", NOT_AVAILABLE, reason="NO_EVIDENCE_DATABASE",
            detail={"expected": str(db)})
    try:
        from .evidence_db import EvidenceStore
        store = EvidenceStore(db, read_only=True)
    except Exception as exc:
        return _baseline_field(
            "evidence_hashes", NOT_AVAILABLE, reason="EVIDENCE_DATABASE_UNREADABLE",
            source=str(db), detail={"error": f"{type(exc).__name__}: {exc}"})
    try:
        rows = store.query(
            "SELECT evidence_id, verdict FROM normalized_evidence ORDER BY evidence_id")
    except Exception as exc:
        return _baseline_field(
            "evidence_hashes", NOT_AVAILABLE, reason="NORMALIZED_EVIDENCE_UNREADABLE",
            source=str(db), detail={"error": f"{type(exc).__name__}: {exc}"})
    finally:
        store.close()
    ids = {str(r["evidence_id"]): str(r.get("verdict")) for r in rows}
    if not ids:
        return _baseline_field(
            "evidence_hashes", NOT_AVAILABLE, reason="NO_NORMALIZED_EVIDENCE_ROWS",
            source=str(db))
    return _baseline_field(
        "evidence_hashes", CAPTURED, reason="REAL_NORMALIZED_EVIDENCE_IDS",
        source=f"{db} :: normalized_evidence", digest=_aggregate(ids),
        detail={"evidence_count": len(ids)})


def _capture_dashboard_snapshot(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    return _baseline_field(
        "dashboard_snapshot", NOT_AVAILABLE, reason="NO_DASHBOARD_SNAPSHOT_PRODUCER",
        detail={"explanation":
                "dv_harness/dashboard.py renders live from state.json, the "
                "blackboard topic files, the coverage summary and the LSF job "
                "records on every request; it persists no snapshot artifact. "
                "Every source it renders from is frozen by another field of this "
                "baseline (configuration / coverage_databases / assertion_status / "
                "evidence_hashes), so re-deriving a 'snapshot' here would be a "
                "rendering of already-frozen inputs presented as an independent "
                "one, not new evidence."})


def _capture_reproducibility_capsules(root: Path, declared: Dict[str, Any]) -> Dict[str, Any]:
    """`golden_scenario.py`'s capsules ARE section 238's reproducibility
    capsules: test + seed + configuration + the real `verified_sha` the PASS
    was recorded against. Read-only, and never re-evaluated for freshness
    here -- that is `golden_scenario.evaluate_freshness()`'s job."""
    from .evidence_db import default_db_path
    db = default_db_path(Path(root))
    if not Path(db).exists():
        return _baseline_field(
            "reproducibility_capsules", NOT_AVAILABLE,
            reason="NO_EVIDENCE_DATABASE", detail={"expected": str(db)})
    try:
        from . import golden_scenario
        store = golden_scenario._open_store(Path(root), None, read_only=True)
        if store is None:
            return _baseline_field(
                "reproducibility_capsules", NOT_AVAILABLE,
                reason="NO_EVIDENCE_DATABASE", detail={"expected": str(db)})
        try:
            capsules = golden_scenario.load_golden_scenarios(store)
        finally:
            store.close()
    except Exception as exc:
        return _baseline_field(
            "reproducibility_capsules", NOT_AVAILABLE,
            reason="GOLDEN_SCENARIO_STORE_UNREADABLE", source=str(db),
            detail={"error": f"{type(exc).__name__}: {exc}"})
    if not capsules:
        return _baseline_field(
            "reproducibility_capsules", NOT_AVAILABLE,
            reason="NO_GOLDEN_SCENARIO_CAPSULES_RECORDED", source=str(db))
    rows = {c.capsule_id: f"{c.test_name}|{c.seed}|{c.verified_sha}"
            for c in capsules}
    return _baseline_field(
        "reproducibility_capsules", CAPTURED,
        reason="REAL_GOLDEN_SCENARIO_CAPSULES",
        source=f"{db} :: golden_scenarios", digest=_aggregate(rows),
        detail={"capsule_count": len(rows), "capsule_ids": sorted(rows)})


#: field -> capture function. Held equal to SECTION_238_FIELDS in both
#: directions at import time.
BASELINE_CAPTURES = {
    "spec_version": _capture_spec_version,
    "requirement_vplan_version": _capture_requirement_vplan_version,
    "dut_sha": _capture_dut_sha,
    "tb_sha": _capture_tb_sha,
    "agent_skill_versions": _capture_agent_skill_versions,
    "vip_tool_versions": _capture_vip_tool_versions,
    "schema_policy_versions": _capture_schema_policy_versions,
    "configuration": _capture_configuration,
    "test_list": _capture_test_list,
    "coverage_databases": _capture_coverage_databases,
    "assertion_status": _capture_assertion_status,
    "waivers": _capture_waivers,
    "evidence_hashes": _capture_evidence_hashes,
    "dashboard_snapshot": _capture_dashboard_snapshot,
    "reproducibility_capsules": _capture_reproducibility_capsules,
}


def assert_baseline_covers_section_238() -> None:
    """Both directions: a section 238 field with no capture function would be
    silently absent from every freeze record, and a capture function for a
    field section 238 does not name would widen the baseline without anyone
    deciding to. Runs at import, so either failure is a test failure rather
    than a quietly shorter freeze."""
    declared = set(SECTION_238_FIELDS)
    implemented = set(BASELINE_CAPTURES)
    missing = sorted(declared - implemented)
    extra = sorted(implemented - declared)
    if missing or extra:
        raise AssertionError(
            f"signoff baseline drifted from spec section 238: "
            f"no capture for {missing}; capture for undeclared field {extra}")


assert_baseline_covers_section_238()


def _repo_head_sha(root: Path) -> Tuple[Optional[str], str]:
    """The project's real git HEAD, used ONLY to anchor the post-freeze impact
    analysis (`change_impact.changed_files()` needs a base commit). It is not
    a DUT SHA and is never reported as one -- `dut_sha` above is RTL content."""
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                             capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return None, f"GIT_UNAVAILABLE: {type(exc).__name__}: {exc}"
    if out.returncode != 0:
        return None, "NOT_A_GIT_REPOSITORY_OR_NO_COMMITS"
    sha = (out.stdout or "").strip()
    return (sha, "REAL_GIT_HEAD") if sha else (None, "GIT_REPORTED_NO_HEAD")


def capture_baseline(root: Path, declared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """All fifteen of spec section 238's baseline fields, each from a REAL
    producer or NOT_AVAILABLE with the reason. Reading is not a mutating act:
    no store, state file or `.dv-harness/` tree is created to answer any
    field, and nothing here runs a build, a regression or an LSF submission."""
    root = Path(root).resolve()
    fields = {name: BASELINE_CAPTURES[name](root, declared or {})
              for name in SECTION_238_FIELDS}
    head_sha, head_reason = _repo_head_sha(root)
    captured = sum(1 for f in fields.values() if f["status"] == CAPTURED)
    return {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "captured_at": _now_iso(),
        "project_root": str(root),
        "harness_root": str(_HARNESS_ROOT),
        "repo_head_sha": head_sha,
        "repo_head_sha_reason": head_reason,
        "fields": fields,
        "captured_field_count": captured,
        "not_available_field_count": len(SECTION_238_FIELDS) - captured,
    }


def collect_signoff_bundle(root: Path, out_dir: Path, notifier=None,
                           require_signoff_pass: bool = False,
                           freeze: Optional[bool] = None,
                           frozen_by: Optional[str] = None,
                           declared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`notifier` (2026-09-03, dv_harness/escalation_notify.py): an
    optional EscalationNotifier. Omitted (the default) means no
    notification is ever attempted, keeping this function pure for the
    existing test suite. When supplied (dv_harness/cli.py's
    `signoff-export` command builds one from `h.cfg["escalation"]"), it
    fires EXACTLY when the self-audit result bundled below (see step 6)
    reports a real gate failure -- this project's own most direct
    "signoff blocked" signal (CLAUDE.md: "All actionable findings must
    close before Final Deep Audit"), never on a clean audit.

    `require_signoff_pass` (2026-09-04): refuse to produce a bundle at all
    unless the project's REAL SIGNOFF stage gate has passed -- see this
    module's docstring for why that is opt-in rather than the default (the
    SIGNOFF gate battery consumes a bundle as input, so it must be
    producible before SIGNOFF passes). Refusal writes nothing at all, not
    even an empty out_dir, so a refused export cannot leave behind a
    directory a later reader mistakes for a partial bundle.

    `freeze` (2026-09-06, spec section 238): capture and record the frozen
    baseline for this bundle. `None` -- the default -- means AUTO: freeze
    exactly when the bundle is `SIGNOFF_GATE_VERIFIED`, i.e. when the 9 real
    SIGNOFF gates really passed. That makes `engine._export_signoff_bundle()`
    -- the one production caller that produces a gate-verified bundle -- the
    real, wired producer of section 238's "at signoff, capture a frozen
    reproducible baseline", with no engine change and no second entry point.
    A `PRE_SIGNOFF_GATE_INPUT` bundle is deliberately NOT frozen: freezing a
    baseline the gates never accepted would mint exactly the
    indistinguishable-from-verified artifact `bundle_kind` exists to prevent.
    `True`/`False` force it either way (a human may freeze a pre-gate
    baseline deliberately; the record still carries the real `bundle_kind`)."""
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()

    # Read BEFORE anything is written: the status must describe the project
    # as it stood when the export was asked for, and a refusal must be able
    # to happen before out_dir exists.
    signoff_stage = read_signoff_stage_status(root)
    if require_signoff_pass and not signoff_stage["gate_verified"]:
        return {
            "status": "REFUSED",
            "reason": "SIGNOFF_STAGE_NOT_PASSED",
            "detail": (
                f"SIGNOFF stage status is {signoff_stage['stage_status']}, not "
                f"{SIGNOFF_VERIFIED_STATUS}: the {len(signoff_stage['required_signoff_gates'])} "
                f"SIGNOFF gates have not been satisfied by a real stage transition for this "
                f"project, so no gate-verified signoff bundle can be produced."
            ),
            "out_dir": str(out_dir),
            "signoff_stage": signoff_stage,
            "bundle_kind": None,
            "manifest": [],
            "bundle_hash": None,
            "bundled_count": 0,
            "missing_count": 0,
        }

    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: List[Dict[str, Any]] = []

    def record(artifact: str, present: bool, bundled_rel: Optional[Path]) -> None:
        # `content_sha256` (2026-09-06, section 238 "evidence hashes/
        # references"): compute_bundle_hash() below reads ONLY
        # artifact/present/bundled_path, so a bundled file could be replaced
        # wholesale without moving bundle_hash. This is the content half.
        # Deliberately a FOURTH key rather than material for
        # compute_bundle_hash: that function's contract is the artifact list,
        # and signoff_bundle_completeness_gate.py recomputes it independently
        # off manifest.json -- widening it would change every previously
        # computed bundle_hash and break that gate for existing bundles.
        content = None
        if present and bundled_rel is not None:
            content = _artifact_content_digest(out_dir / bundled_rel)
        manifest.append({
            "artifact": artifact,
            "present": present,
            "bundled_path": bundled_rel.as_posix() if bundled_rel is not None else None,
            "content_sha256": content,
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
    if notifier is not None and audit_result["summary"]["fail"] > 0:
        failing = [g["gate_id"] for g in audit_result["gates"] if g["status"] == "FAIL"]
        notifier.signoff_blocked(stage="SIGNOFF", reasons=failing)

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

    # 11: the real SIGNOFF stage-gate status -- generated, never copied, like
    # step 6's self-audit. Recorded as a real manifest entry (so its presence
    # is covered by bundle_hash, and a legacy bundle produced before this
    # existed hashes differently) AND written out as its own file, so a
    # reader who only ever opens the bundle directory still sees whether the
    # 9 real SIGNOFF gates were ever satisfied for this project.
    stage_rel = Path("signoff_stage_status.json")
    (out_dir / stage_rel).write_text(
        json.dumps(signoff_stage, ensure_ascii=False, indent=2), encoding="utf-8")
    record("signoff_stage_status", True, stage_rel)

    bundle_hash = compute_bundle_hash(manifest)

    # manifest.json's content is {"manifest": [...], "bundle_hash": "..."}
    # (RULING, trust-boundary-hardening: promoted from a bare list to a
    # dict so bundle_hash has a real, on-disk, independently-re-readable
    # location -- signoff_bundle_completeness_gate.py reads this file back
    # and recomputes compute_bundle_hash(manifest_list) itself, never
    # trusting this written bundle_hash value on its own).
    #
    # `signoff_stage` is a third top-level key (2026-09-04): the real
    # stage-gate status, readable straight off manifest.json without opening
    # signoff_stage_status.json. It is deliberately OUTSIDE compute_bundle_hash's
    # material -- that function's contract (and signoff_bundle_completeness_gate's
    # independent recomputation of it) is over the artifact list only, and
    # widening it would change every previously-computed bundle_hash for a
    # value the gate can read directly anyway.
    bundle_kind = "SIGNOFF_GATE_VERIFIED" if signoff_stage["gate_verified"] else "PRE_SIGNOFF_GATE_INPUT"
    (out_dir / "manifest.json").write_text(
        json.dumps({"manifest": manifest, "bundle_hash": bundle_hash,
                    "signoff_stage": signoff_stage, "bundle_kind": bundle_kind},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    bundled_count = sum(1 for m in manifest if m["present"])
    missing_count = sum(1 for m in manifest if not m["present"])

    should_freeze = (bundle_kind == "SIGNOFF_GATE_VERIFIED") if freeze is None else bool(freeze)
    freeze_record = None
    if should_freeze:
        freeze_record = freeze_signoff_baseline(
            root, out_dir, frozen_by=frozen_by, declared=declared,
            bundle_hash=bundle_hash, bundle_kind=bundle_kind,
            signoff_stage=signoff_stage)

    return {
        "status": "OK",
        "out_dir": str(out_dir),
        "manifest": manifest,
        "bundle_hash": bundle_hash,
        "bundled_count": bundled_count,
        "missing_count": missing_count,
        # An honest bundle can no longer claim, by omission, to be a
        # gate-verified signoff: PRE_SIGNOFF_GATE_INPUT says outright that
        # the 9 real SIGNOFF gates have not passed for this project.
        "bundle_kind": bundle_kind,
        "signoff_stage": signoff_stage,
        "freeze": freeze_record,
    }


# --- freeze record: write, load, list --------------------------------------

#: Where a project's freeze records live. Under the project's own
#: `.dv-harness/` (the same state directory `state.json`/`events.jsonl`/
#: `waivers/` already live in), never a new parallel state root, and NOT only
#: inside the bundle -- a bundle directory can be moved or deleted, and a
#: baseline that disappears with it could never invalidate anything.
FREEZE_DIR_PARTS = (".dv-harness", "signoff", "freezes")

#: The one events.jsonl event name this subsystem writes, so "was a signoff
#: baseline frozen, when, by whom, over what bundle" is answerable from the
#: real audit trail `dv-harness audit` already surfaces.
FREEZE_EVENT = "SIGNOFF_BASELINE_FROZEN"


def freeze_dir(root: Path) -> Path:
    return Path(root).joinpath(*FREEZE_DIR_PARTS)


def _freeze_id(baseline: Dict[str, Any], bundle_hash: Optional[str],
               frozen_at: str) -> str:
    material = [f"frozen_at:{frozen_at}", f"bundle_hash:{bundle_hash}"]
    material += [f"{name}:{baseline['fields'][name]['status']}:"
                 f"{baseline['fields'][name]['digest']}"
                 for name in SECTION_238_FIELDS]
    return hashlib.sha256("\n".join(material).encode("utf-8")).hexdigest()[:16]


def freeze_signoff_baseline(root: Path, bundle_dir: Optional[Path] = None, *,
                            frozen_by: Optional[str] = None,
                            declared: Optional[Dict[str, Any]] = None,
                            bundle_hash: Optional[str] = None,
                            bundle_kind: Optional[str] = None,
                            signoff_stage: Optional[Dict[str, Any]] = None,
                            note: str = "") -> Dict[str, Any]:
    """Record one immutable frozen baseline for the project at `root`.

    Every identity field comes from `capture_baseline()`, i.e. from a real
    producer; `bundle_hash`/`bundle_kind`/`signoff_stage` are passed in by
    `collect_signoff_bundle()` (which just computed them) or RECOMPUTED off
    the bundle's own `manifest.json` when this is called standalone -- never
    accepted as a caller's claim about a bundle nobody looked at.

    Writes the record to `.dv-harness/signoff/freezes/<freeze_id>.json` and,
    when a bundle directory was given, a copy to
    `<bundle_dir>/signoff_freeze.json`, plus one real
    `SIGNOFF_BASELINE_FROZEN` event. It approves nothing, runs no stage and
    grants no gate: a freeze is a RECORD of what a signoff was produced
    against.
    """
    root = Path(root).resolve()
    bundle_dir = Path(bundle_dir).resolve() if bundle_dir is not None else None

    if bundle_dir is not None and (bundle_hash is None or bundle_kind is None):
        mpath = bundle_dir / "manifest.json"
        if mpath.is_file():
            try:
                doc = json.loads(mpath.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
            if isinstance(doc, dict):
                mlist = doc.get("manifest")
                # RECOMPUTED, never read off the file: a manifest.json whose
                # stored bundle_hash was edited must not be frozen as if it
                # were what the artifact list really hashes to.
                if isinstance(mlist, list) and bundle_hash is None:
                    bundle_hash = compute_bundle_hash(mlist)
                if bundle_kind is None:
                    bundle_kind = doc.get("bundle_kind")
                if signoff_stage is None:
                    signoff_stage = doc.get("signoff_stage")

    if signoff_stage is None:
        signoff_stage = read_signoff_stage_status(root)

    baseline = capture_baseline(root, declared)
    frozen_at = _now_iso()
    fid = _freeze_id(baseline, bundle_hash, frozen_at)
    record = {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "freeze_id": fid,
        "frozen_at": frozen_at,
        "frozen_by": frozen_by,
        "note": note,
        "project_root": str(root),
        "bundle_dir": str(bundle_dir) if bundle_dir is not None else None,
        "bundle_hash": bundle_hash,
        "bundle_kind": bundle_kind,
        "signoff_stage": signoff_stage,
        "baseline": baseline,
    }

    fdir = freeze_dir(root)
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / (fid + ".json")).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if bundle_dir is not None and bundle_dir.is_dir():
        (bundle_dir / "signoff_freeze.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # Best-effort audit trail -- a bookkeeping failure must never turn an
    # already-written freeze record into a failed export.
    try:
        from .storage import StateStore
        StateStore(root).event({
            "ts": frozen_at, "event": FREEZE_EVENT, "stage": "SIGNOFF",
            "freeze_id": fid, "frozen_by": frozen_by,
            "bundle_kind": bundle_kind, "bundle_hash": bundle_hash,
            "captured_fields": baseline["captured_field_count"],
            "not_available_fields": baseline["not_available_field_count"],
            "repo_head_sha": baseline["repo_head_sha"],
        })
    except Exception:
        pass
    return record


def list_freezes(root: Path) -> List[Dict[str, Any]]:
    fdir = freeze_dir(root)
    out: List[Dict[str, Any]] = []
    if not fdir.is_dir():
        return out
    for p in sorted(fdir.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("freeze_id"):
            out.append(doc)
    out.sort(key=lambda r: str(r.get("frozen_at") or ""))
    return out


def load_freeze(root: Path, freeze_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One freeze record. With no `freeze_id`, the most recently frozen one --
    `frozen_at` order, not filesystem mtime, so copying the freeze tree does
    not reorder history."""
    records = list_freezes(root)
    if not records:
        return None
    if freeze_id is None:
        return records[-1]
    for r in records:
        if r.get("freeze_id") == freeze_id:
            return r
    return None


# --- post-freeze invalidation ---------------------------------------------

#: Changed-file risks that make a post-freeze change MATERIAL. The same
#: intent as `golden_scenario.STALENESS_RISKS`, decided by the same
#: `change_impact.classify_risk()` -- HIGH is design RTL, MEDIUM is
#: testbench/sequence/command.txt/config, LOW is docs and
#: `.dv-harness`/`.claude` bookkeeping, which must not invalidate a signoff
#: (a signoff export writes into `.dv-harness/` itself).
MATERIAL_CHANGE_RISKS = ("HIGH", "MEDIUM")


def _finding(code: str, severity: str, field: Optional[str],
             detail: Dict[str, Any]) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "field": field, "detail": detail}


def evaluate_freeze_invalidation(root: Path, frozen: Dict[str, Any], *,
                                 head: str = "HEAD",
                                 diff: Optional[Dict[str, Any]] = None,
                                 declared: Optional[Dict[str, Any]] = None,
                                 current_baseline: Optional[Dict[str, Any]] = None
                                 ) -> Dict[str, Any]:
    """VALID / INVALIDATED / UNKNOWN for one frozen baseline, from real
    evidence only -- section 238's "post-freeze material changes trigger
    impact analysis and invalidate/revalidate affected signoff evidence", as
    a check rather than a sentence.

    Three independent comparisons, worst-wins:

    1. **Baseline field divergence.** All fifteen fields are re-derived NOW by
       the same capture functions and compared by digest. A field CAPTURED at
       freeze that no longer matches, or that can no longer be captured at
       all, INVALIDATES. A field that was NOT_AVAILABLE at freeze and is
       CAPTURED now is INDETERMINATE, not invalidating -- evidence appearing
       after a signoff is a real change, but it is not proof the frozen
       evidence went wrong.
    2. **Post-freeze impact analysis.** The REAL
       `change_impact.changed_files()` + `classify_risk()` over the freeze's
       recorded git HEAD, exactly as `golden_scenario.evaluate_freshness()`
       runs it, so "did the design move" has ONE answer in this codebase.
       HIGH/MEDIUM changed files INVALIDATE and are named; LOW do not.
    3. **Bundle integrity.** The frozen bundle's `manifest.json` is re-read
       and `compute_bundle_hash()` recomputed independently; a bundle that
       moved since the freeze INVALIDATES, one that is gone is INDETERMINATE.

    `diff` and `current_baseline` are injectable for the same reason
    `evaluate_freshness()`'s `diff` is: one recomputation can serve many
    freezes, and a test can drive the UNKNOWN branches without breaking a
    repository. Nothing here writes, approves, revalidates or re-runs
    anything -- REVALIDATION is a human act, and this reports what would have
    to be revalidated.
    """
    root = Path(root).resolve()
    frozen_baseline = (frozen or {}).get("baseline") or {}
    frozen_fields = frozen_baseline.get("fields") or {}
    current = (current_baseline if current_baseline is not None
               else capture_baseline(root, declared))
    findings: List[Dict[str, Any]] = []

    # 1. field-by-field divergence
    for name in SECTION_238_FIELDS:
        was = frozen_fields.get(name)
        now = current["fields"][name]
        if not isinstance(was, dict):
            findings.append(_finding(
                "FIELD_NOT_IN_FROZEN_BASELINE", SEV_INDETERMINATE, name,
                {"explanation": "the frozen record predates this baseline field, "
                                "so nothing about it can be compared",
                 "current_status": now["status"]}))
            continue
        if was.get("status") == CAPTURED and now["status"] == CAPTURED:
            if was.get("digest") != now.get("digest"):
                findings.append(_finding(
                    "BASELINE_FIELD_CHANGED", SEV_INVALIDATING, name,
                    {"frozen_digest": was.get("digest"),
                     "current_digest": now.get("digest"),
                     "source": now.get("source")}))
        elif was.get("status") == CAPTURED and now["status"] == NOT_AVAILABLE:
            findings.append(_finding(
                "BASELINE_EVIDENCE_DISAPPEARED", SEV_INVALIDATING, name,
                {"frozen_digest": was.get("digest"),
                 "frozen_source": was.get("source"),
                 "current_reason": now.get("reason")}))
        elif was.get("status") == NOT_AVAILABLE and now["status"] == CAPTURED:
            findings.append(_finding(
                "NEW_EVIDENCE_AFTER_FREEZE", SEV_INDETERMINATE, name,
                {"frozen_reason": was.get("reason"),
                 "current_digest": now.get("digest"),
                 "current_source": now.get("source")}))

    # 2. post-freeze impact analysis over the real git history
    base_sha = frozen_baseline.get("repo_head_sha")
    impact: Dict[str, Any] = {"status": None, "changed_files": [],
                              "material_changes": [], "base_sha": base_sha,
                              "head": head}
    if not base_sha:
        impact["status"] = "NO_RECORDED_HEAD_SHA"
        findings.append(_finding(
            "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE", SEV_INDETERMINATE, None,
            {"reason": frozen_baseline.get("repo_head_sha_reason")
                       or "the freeze recorded no git HEAD, so no change since it "
                          "can be computed"}))
    else:
        from . import change_impact
        d = diff if diff is not None else change_impact.changed_files(root, base_sha, head)
        impact["status"] = d.get("status")
        impact["detail"] = d.get("detail")
        impact["head_sha"] = d.get("head_sha")
        if d.get("status") != "REAL_DIFF":
            findings.append(_finding(
                "POST_FREEZE_IMPACT_ANALYSIS_UNAVAILABLE", SEV_INDETERMINATE, None,
                {"reason": "GIT_HISTORY_UNAVAILABLE: " + str(d.get("status")),
                 "detail": d.get("detail"), "base_sha": base_sha}))
        else:
            files = list(d.get("files") or [])
            impact["changed_files"] = files
            material = [{"path": f, "risk": change_impact.classify_risk(f)}
                        for f in files
                        if change_impact.classify_risk(f) in MATERIAL_CHANGE_RISKS]
            impact["material_changes"] = material
            if material:
                findings.append(_finding(
                    "POST_FREEZE_MATERIAL_CHANGE", SEV_INVALIDATING, None,
                    {"base_sha": base_sha, "head": head,
                     "changed_file_count": len(files),
                     "material_changes": material}))

    # 3. bundle integrity
    bundle_dir = (frozen or {}).get("bundle_dir")
    bundle: Dict[str, Any] = {"bundle_dir": bundle_dir,
                              "frozen_bundle_hash": (frozen or {}).get("bundle_hash")}
    if bundle_dir:
        mpath = Path(bundle_dir) / "manifest.json"
        if not mpath.is_file():
            bundle["status"] = "BUNDLE_NOT_FOUND"
            findings.append(_finding(
                "FROZEN_BUNDLE_NOT_FOUND", SEV_INDETERMINATE, None,
                {"bundle_dir": bundle_dir,
                 "explanation": "the frozen bundle is gone, so its contents cannot "
                                "be checked against the freeze"}))
        else:
            try:
                doc = json.loads(mpath.read_text(encoding="utf-8"))
                mlist = doc.get("manifest") if isinstance(doc, dict) else None
                recomputed = compute_bundle_hash(mlist) if isinstance(mlist, list) else None
            except (OSError, ValueError):
                recomputed = None
            bundle["recomputed_bundle_hash"] = recomputed
            if recomputed is None:
                bundle["status"] = "BUNDLE_MANIFEST_MALFORMED"
                findings.append(_finding(
                    "FROZEN_BUNDLE_MANIFEST_MALFORMED", SEV_INDETERMINATE, None,
                    {"bundle_dir": bundle_dir}))
            elif frozen.get("bundle_hash") and recomputed != frozen["bundle_hash"]:
                bundle["status"] = "BUNDLE_CHANGED"
                findings.append(_finding(
                    "FROZEN_BUNDLE_CHANGED", SEV_INVALIDATING, None,
                    {"bundle_dir": bundle_dir,
                     "frozen": frozen.get("bundle_hash"), "recomputed": recomputed}))
            else:
                bundle["status"] = "BUNDLE_UNCHANGED"

    if any(f["severity"] == SEV_INVALIDATING for f in findings):
        status = FREEZE_INVALIDATED
    elif findings:
        status = FREEZE_UNKNOWN
    else:
        status = FREEZE_VALID

    return {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "status": status,
        "freeze_id": (frozen or {}).get("freeze_id"),
        "frozen_at": (frozen or {}).get("frozen_at"),
        "frozen_by": (frozen or {}).get("frozen_by"),
        "bundle_kind": (frozen or {}).get("bundle_kind"),
        "evaluated_at": _now_iso(),
        "findings": findings,
        "invalidating_count": sum(1 for f in findings if f["severity"] == SEV_INVALIDATING),
        "indeterminate_count": sum(1 for f in findings if f["severity"] == SEV_INDETERMINATE),
        "impact_analysis": impact,
        "bundle": bundle,
        "current_baseline": current,
    }


def evaluate_all_freezes(root: Path, *, head: str = "HEAD",
                         declared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every recorded freeze, evaluated against ONE re-derived current
    baseline. The report's own status is the WORST present -- one invalidated
    freeze makes the report INVALIDATED, because a caller asking "is my
    signoff still good" must not read a mostly-valid set as an all-clear."""
    root = Path(root).resolve()
    frozen = list_freezes(root)
    if not frozen:
        return {"schema_version": FREEZE_SCHEMA_VERSION,
                "status": "NOT_AVAILABLE", "reason": "NO_FROZEN_SIGNOFF_BASELINE",
                "freeze_dir": str(freeze_dir(root)), "freezes": []}
    current = capture_baseline(root, declared)
    results = [evaluate_freeze_invalidation(root, f, head=head,
                                            current_baseline=current)
               for f in frozen]
    worst = max(results, key=lambda r: _FREEZE_SEVERITY[r["status"]])["status"]
    return {"schema_version": FREEZE_SCHEMA_VERSION, "status": worst,
            "freeze_count": len(results),
            "counts": {s: sum(1 for r in results if r["status"] == s)
                       for s in (FREEZE_VALID, FREEZE_UNKNOWN, FREEZE_INVALIDATED)},
            "freezes": results, "evaluated_at": _now_iso()}


# --- freeze acceptance: revalidation is a human act, made real -------------
#
# WIRING_GAP_EXISTING_MODULE closure (signoff-freeze-revalidation-explicitly-
# undone): evaluate_freeze_invalidation() computes a real INVALIDATED/VALID/
# UNKNOWN verdict, but its own docstring's "REVALIDATION is a human act" had
# no code behind it -- confirmed by direct grep before writing this: no
# cmd_revalidate (or equivalent) verb existed anywhere in commands.py, and no
# persisted record let a human accept an INVALIDATED/UNKNOWN freeze.
#
# REUSE OVER REINVENT: this is the SAME digest-pinned-Control-Plane-approval
# pattern change_blast_radius.py already established one gate over (its own
# module docstring: "the pin is what stops it degrading into a permanent
# blanket bypass, since growing the change moves the digest and retires the
# approval") -- never a second approval mechanism, never a second store.
# SIGNOFF_FREEZE_REVALIDATION_STAGE is a FOURTH APPROVAL_ONLY_STAGES key
# (commands.py), so `dv-harness approve SIGNOFF_FREEZE_REVALIDATION --note
# '<freeze_id> <digest>: ...' --reviewer-id ... --reviewer-confidence ...` is
# real, already-reachable CLI usage the instant this key is registered there
# -- and the SAME generic "APPROVE" /api/control command dashboard.py already
# dispatches for any stage string, so no dashboard.py dispatch branch or
# gui_action_safety.py declaration is needed either: "APPROVE" is declared
# there ONCE, generically, not once per approvable stage.
#
# "Trigger an attributed re-freeze" is deliberately NOT a second verb here.
# freeze_signoff_baseline(root, ..., frozen_by=...) -- already reachable via
# `... freeze --frozen-by <human>` and via collect_signoff_bundle()'s own
# automatic freeze on a real SIGNOFF_GATE_VERIFIED bundle -- IS that action: a
# fresh freeze_id/frozen_at/frozen_by is exactly a new, attributed re-freeze.
# A second function that only re-called freeze_signoff_baseline() would be
# the parallel mechanism this project forbids.
#
# THIS MODULE STILL TOUCHES NO APPROVAL MACHINERY
# (test_the_freeze_module_touches_no_approval_machinery, pre-existing):
# every function below is a PURE function over an `approval` record the
# CALLER already fetched from the real Human Control Plane store -- this file
# imports no approval class at all, anywhere. The real fetch-then-judge
# composition lives in commands.py (cmd_signoff_freeze_acceptance_status),
# the established location in this codebase for combining a domain module's
# real output with a Control-Plane approval read (see cmd_research_approve,
# which composes capability_evolution.py the identical way).
SIGNOFF_FREEZE_REVALIDATION_STAGE = "SIGNOFF_FREEZE_REVALIDATION"


def freeze_acceptance_digest(evaluation: Dict[str, Any]) -> str:
    """A real, deterministic digest over exactly what a human is being asked
    to accept: the freeze_id plus every real finding's own (code, field,
    severity) -- never the WHOLE evaluation, whose `current_baseline`/
    `impact_analysis` carry volatile, non-decision-bearing detail (a fresh
    git HEAD sha on every call) that would make the digest churn for no real
    reason. The SAME finding set on the SAME freeze produces the SAME digest;
    a NEW divergence (a finding this evaluation did not have) moves it --
    the identical anti-blanket-approval property change_blast_radius.py's own
    `_digest()` already established for a change's own touched-file set."""
    freeze_id = str(evaluation.get("freeze_id") or "")
    material = [f"freeze_id:{freeze_id}"]
    for f in sorted(evaluation.get("findings") or [],
                     key=lambda f: (str(f.get("code")), str(f.get("field")), str(f.get("severity")))):
        material.append(f"{f.get('code')}:{f.get('field')}:{f.get('severity')}")
    return hashlib.sha256("\n".join(material).encode("utf-8")).hexdigest()[:16]


def freeze_acceptance_command(freeze_id: str, digest: str) -> str:
    """The exact, real command a human runs to accept this evaluation --
    returned so a caller (a block message, a dashboard note) can show it
    copy-pasteable rather than describing an approval that has to be looked
    up, mirroring change_blast_radius.confirmation_command()."""
    return (f"dv-harness approve {SIGNOFF_FREEZE_REVALIDATION_STAGE} "
            f"--note 'freeze {freeze_id} {digest}: <why this is acceptable>' "
            f"--reviewer-id <you> --reviewer-confidence HIGH|MEDIUM|LOW")


def freeze_acceptance_status(evaluation: Dict[str, Any],
                              approval: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Is `approval` -- a record the CALLER already fetched via the real
    Control Plane's `get_approval(SIGNOFF_FREEZE_REVALIDATION_STAGE)`, or
    `None` when there is none on file -- a real, PINNED human acceptance of
    THIS exact evaluation (this freeze_id, and this exact finding set)? This
    function itself never reads `.dv-harness/control.json` or imports the
    approval class; it only judges a record it is handed, preserving this
    module's own "touches no approval machinery" boundary.

    An approval whose note does not carry both the freeze_id and the digest
    is reported PRESENT BUT NOT MATCHING rather than silently ignored or
    silently trusted: "a human accepted a DIFFERENT divergence of this
    freeze" is a different, more useful fact than either "accepted" or
    "never reviewed at all"."""
    freeze_id = str(evaluation.get("freeze_id") or "")
    digest = freeze_acceptance_digest(evaluation)
    if not approval:
        return {"accepted": False, "state": "ABSENT", "digest": digest, "approval": None}
    note = str(approval.get("note") or "")
    if freeze_id and freeze_id in note and digest in note:
        return {"accepted": True, "state": "PINNED_MATCH", "digest": digest, "approval": approval}
    return {"accepted": False, "state": "PRESENT_BUT_NOT_MATCHING", "digest": digest,
            "approval": approval}


def evaluate_freeze_invalidation_with_acceptance(root: Path, frozen: Dict[str, Any], *,
                                                  approval: Optional[Dict[str, Any]] = None,
                                                  head: str = "HEAD",
                                                  diff: Optional[Dict[str, Any]] = None,
                                                  declared: Optional[Dict[str, Any]] = None,
                                                  current_baseline: Optional[Dict[str, Any]] = None
                                                  ) -> Dict[str, Any]:
    """evaluate_freeze_invalidation()'s own report, additively carrying one new
    "acceptance" block naming whether `approval` -- a real Control-Plane
    approval record the CALLER already fetched for
    SIGNOFF_FREEZE_REVALIDATION_STAGE, or `None` -- covers THIS EXACT
    INVALIDATED/UNKNOWN verdict. Never changes evaluate_freeze_invalidation()'s
    own status/findings/severity computation, which stays the single,
    unmodified source of truth for whether a freeze is still good; this
    function itself fetches nothing from that store (see freeze_acceptance_
    status's own docstring for why).

    A VALID evaluation needs no acceptance at all (`required: False`); only a
    real INVALIDATED/UNKNOWN evaluation is checked against `approval`."""
    report = evaluate_freeze_invalidation(root, frozen, head=head, diff=diff,
                                           declared=declared, current_baseline=current_baseline)
    if report["status"] == FREEZE_VALID:
        report["acceptance"] = {"required": False, "accepted": True, "state": "NOT_REQUIRED",
                                 "digest": None, "approval": None, "command": None}
        return report
    status = freeze_acceptance_status(report, approval)
    report["acceptance"] = {
        "required": True, **status,
        "command": freeze_acceptance_command(str(report.get("freeze_id") or ""), status["digest"]),
    }
    return report


# --- Second-reviewer status for the CURRENT signoff evidence bundle --------
#
# Real gap this closes (2026-09-07, item id
# "no-second-reviewer-mechanism-at-signoff-scope"): before
# `add_bundle_review()`/`get_bundle_reviews()` (the Human Control Plane's
# own store, control_plane.py) existed, nothing recorded MORE THAN ONE
# reviewer against a signoff evidence bundle at all -- the Control Plane's
# own `approvals[stage]` holds exactly one entry, overwritten on every
# fresh `approve()` call (archived, never lost -- but never concurrent
# either), and this module's own freeze/manifest machinery carried no
# reviewer concept whatsoever. `add_decision_cosign()` (question_queue.py)
# is the nearest-looking real mechanism and was deliberately not extended:
# it co-signs one already-recorded Tier-3 INTAKE DECISION keyed on that
# decision's own exact answer text, a different object entirely from a
# whole signoff evidence bundle.
#
# THIS MODULE STILL TOUCHES NO APPROVAL MACHINERY
# (test_the_freeze_module_touches_no_approval_machinery, pre-existing,
# see SIGNOFF_FREEZE_REVALIDATION_STAGE's own comment above): the function
# below is a PURE function over a `reviews` list the CALLER already
# fetched from the real Human Control Plane's own store (control_plane.py's
# `get_bundle_reviews("SIGNOFF", bundle_hash)` method) -- this file imports
# no Control-Plane class anywhere, exactly like `freeze_acceptance_status()`
# one section above.

def bundle_second_review_status(manifest: List[Dict[str, Any]],
                                 reviews: Optional[Sequence[Dict[str, Any]]],
                                 approver_id: Optional[str] = None) -> Dict[str, Any]:
    """Is this signoff bundle's REAL, current content -- `compute_bundle_hash
    (manifest)`, the SAME real content-derived hash `freeze_signoff_baseline()`
    and `evaluate_freeze_invalidation()` already use -- covered by a real,
    independent SECOND human reviewer?

    `manifest` is a real `collect_signoff_bundle()` (or `load_freeze()`)
    result's own `"manifest"` list. `reviews` is the list the caller
    already fetched via the real Human Control Plane store's own
    `get_bundle_reviews("SIGNOFF", compute_bundle_hash(manifest))` method
    (or `None`/`[]` when nobody has ever reviewed anything for this
    project yet). `approver_id`, when supplied, excludes that one person's
    own review from counting as the required SECOND, independent one --
    mirroring that same store's `has_independent_bundle_review()` method's
    own same-person rule.

    A review whose own recorded `bundle_hash` does not equal the
    manifest's CURRENT hash is reported separately as a STALE reviewer
    (the bundle changed content since that human looked at it) rather than
    silently trusted or silently dropped -- mirroring
    `freeze_acceptance_status()`'s own PRESENT_BUT_NOT_MATCHING
    distinction one section above."""
    bundle_hash = compute_bundle_hash(manifest)
    reviews = list(reviews or [])
    current = [r for r in reviews if str(r.get("bundle_hash") or "").strip() == bundle_hash]
    stale = [r for r in reviews if str(r.get("bundle_hash") or "").strip() != bundle_hash]
    if not current:
        return {"independently_reviewed": False,
                "state": "PRESENT_BUT_STALE" if stale else "ABSENT",
                "bundle_hash": bundle_hash, "reviewers": [],
                "stale_reviewers": [r.get("reviewer_id") for r in stale]}
    approver_norm = str(approver_id).strip().casefold() if approver_id else None
    independent = [r for r in current
                   if approver_norm is None
                   or str(r.get("reviewer_id") or "").strip().casefold() != approver_norm]
    return {
        "independently_reviewed": bool(independent),
        "state": "REVIEWED" if independent else "SAME_PERSON_ONLY",
        "bundle_hash": bundle_hash,
        "reviewers": [r.get("reviewer_id") for r in current],
        "stale_reviewers": [r.get("reviewer_id") for r in stale],
    }


# --- Filing a clarifying question tied to ONE signoff-stage evidence item ---
#
# Gap (2026-09-07): a human reviewing THIS module's own real output -- a
# collect_signoff_bundle() manifest artifact, an evaluate_freeze_invalidation()
# finding -- had no reachable path to file a NEW clarifying question tied to
# that one specific evidence item. Confirmed by direct grep before writing
# this: this file had zero add_question()/build_multiple_choice_question()
# call sites. Both functions below are REUSE, not a second filing mechanism:
# each locates and cites ONE real item of this module's own already-produced
# evidence, then hands that citation straight to question_queue.py's new
# file_signoff_evidence_question() (added the same day, for exactly this gap)
# -- the tier classification, routing, dedup and persistence are all that
# function's, unmodified.

def file_bundle_artifact_question(store, manifest: List[Dict[str, Any]], artifact: str, *,
                                    question: str, options: Any, recommendation: str,
                                    raised_by: Optional[str] = None,
                                    now: Optional[Any] = None) -> Dict[str, Any]:
    """File a real, new Tier-3 question tied to ONE named artifact entry of an
    already-produced `collect_signoff_bundle()` manifest -- e.g. "why is
    tb_source reported absent" or "is this content_sha256 the revision we
    actually reviewed". `manifest` is that call's own real `"manifest"` list
    (or a `load_freeze()`/on-disk `manifest.json`'s own `"manifest"` list --
    the identical shape either way).

    `store` may be a real `question_queue.QuestionQueueStore` or a project
    root (str/Path) to build one from, mirroring `source_authority.
    escalate_conflict()`'s own convenience.

    Raises KeyError naming every real artifact on the manifest when
    `artifact` does not match one of them -- this function never files a
    question about an evidence item that was not actually produced."""
    entry = next((m for m in manifest if m.get("artifact") == artifact), None)
    if entry is None:
        known = sorted({str(m.get("artifact")) for m in manifest})
        raise KeyError(f"no manifest artifact named {artifact!r}; known artifacts: {known}")
    evidence_path = f"manifest.json#manifest[artifact={artifact!r}]"
    summary = (
        f"signoff bundle artifact {artifact!r}: present={entry.get('present')!r}, "
        f"bundled_path={entry.get('bundled_path')!r}, "
        f"content_sha256={entry.get('content_sha256')!r}"
    )
    from . import question_queue
    qstore = (question_queue.QuestionQueueStore(Path(store))
              if isinstance(store, (str, Path)) else store)
    return question_queue.file_signoff_evidence_question(
        qstore,
        evidence_kind=question_queue.SIGNOFF_EVIDENCE_KIND_BUNDLE,
        evidence_path=evidence_path,
        evidence_summary=summary,
        question=question,
        options=options,
        recommendation=recommendation,
        raised_by=raised_by,
        now=now,
    )


def file_freeze_finding_question(store, evaluation: Dict[str, Any], finding_index: int, *,
                                   question: str, options: Any, recommendation: str,
                                   raised_by: Optional[str] = None,
                                   now: Optional[Any] = None) -> Dict[str, Any]:
    """File a real, new Tier-3 question tied to ONE named finding of an
    already-computed `evaluate_freeze_invalidation()` report -- e.g. a real
    `BASELINE_FIELD_CHANGED`/`POST_FREEZE_MATERIAL_CHANGE` finding a human
    wants a second opinion on before trusting the frozen baseline further.

    `store` may be a real `question_queue.QuestionQueueStore` or a project
    root (str/Path) to build one from.

    Raises IndexError naming the real finding count when `finding_index` is
    out of range -- this function never files a question about a finding
    that does not actually exist on this report."""
    findings = evaluation.get("findings") or []
    if not (0 <= finding_index < len(findings)):
        raise IndexError(
            f"finding_index {finding_index} out of range for {len(findings)} real "
            f"finding(s) on this evaluate_freeze_invalidation() report"
        )
    finding = findings[finding_index]
    freeze_id = evaluation.get("freeze_id")
    evidence_path = f"freeze:{freeze_id}#findings[{finding_index}].code={finding.get('code')}"
    summary = (
        f"freeze {freeze_id!r} finding {finding.get('code')!r} "
        f"(severity={finding.get('severity')!r}, field={finding.get('field')!r}): "
        f"{finding.get('detail')!r}"
    )
    from . import question_queue
    qstore = (question_queue.QuestionQueueStore(Path(store))
              if isinstance(store, (str, Path)) else store)
    return question_queue.file_signoff_evidence_question(
        qstore,
        evidence_kind=question_queue.SIGNOFF_EVIDENCE_KIND_BUNDLE,
        evidence_path=evidence_path,
        evidence_summary=summary,
        question=question,
        options=options,
        recommendation=recommendation,
        raised_by=raised_by,
        now=now,
    )


# --- front door ------------------------------------------------------------

def execute_verb(argv: Sequence[str]) -> int:
    """Shared implementation for `python -m dv_harness.signoff_export <verb>`.
    Exit 0 clear, 1 a real finding (a freeze is INVALIDATED), 2 nothing to
    report / usage refusal. A reporting signal, never an approval signal in
    either direction: no verb here approves, revalidates or runs anything.
    Acceptance-status reporting (whether a real human has accepted an
    INVALIDATED/UNKNOWN evaluation) lives in commands.cmd_signoff_freeze_
    acceptance_status(), which needs a real Control-Plane approval read this
    module deliberately never performs -- see SIGNOFF_FREEZE_REVALIDATION_
    STAGE's own comment above."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="signoff-export",
        description="Signoff freeze / baseline (spec section 238).")
    ap.add_argument("verb", choices=["fields", "baseline", "freeze", "list", "status"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--bundle-dir", default=None)
    ap.add_argument("--freeze-id", default=None)
    ap.add_argument("--frozen-by", default=None)
    ap.add_argument("--spec-version", default=None,
                    help="declare the spec version this signoff is against "
                         "(recorded as attested, never as derived)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))
    root = Path(args.root).resolve()
    declared = {"spec_version": args.spec_version} if args.spec_version else None

    if args.verb == "fields":
        print(json.dumps({"section_238_fields": list(SECTION_238_FIELDS),
                          "field_statuses": [CAPTURED, NOT_AVAILABLE],
                          "freeze_statuses": [FREEZE_VALID, FREEZE_UNKNOWN,
                                              FREEZE_INVALIDATED]}, indent=2))
        return 0

    if args.verb == "baseline":
        b = capture_baseline(root, declared)
        print(json.dumps(b, ensure_ascii=False, indent=2))
        return 0 if b["captured_field_count"] else 2

    if args.verb == "freeze":
        if not args.frozen_by:
            print(json.dumps({"status": "REFUSED", "reason": "FROZEN_BY_REQUIRED",
                              "detail": "a freeze records who froze it; an "
                                        "unattributable baseline is not a signoff "
                                        "baseline"}, indent=2))
            return 2
        rec = freeze_signoff_baseline(root, args.bundle_dir,
                                      frozen_by=args.frozen_by, declared=declared)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    if args.verb == "list":
        rows = list_freezes(root)
        print(json.dumps([{k: r.get(k) for k in
                           ("freeze_id", "frozen_at", "frozen_by", "bundle_kind",
                            "bundle_hash")} for r in rows], indent=2))
        return 0 if rows else 2

    # `accept`/acceptance-status is deliberately NOT a verb here: reporting it
    # honestly needs a real Control-Plane get_approval() read, and this module
    # touches no approval machinery at all (test_the_freeze_module_touches_
    # no_approval_machinery) -- see commands.cmd_signoff_freeze_acceptance_
    # status(), which composes THIS module's pure functions with a real
    # Control-Plane fetch, the established location in this codebase for that
    # combination.

    # status
    if args.freeze_id:
        rec = load_freeze(root, args.freeze_id)
        if rec is None:
            print(json.dumps({"status": "NOT_AVAILABLE",
                              "reason": "FREEZE_ID_NOT_FOUND",
                              "freeze_id": args.freeze_id}, indent=2))
            return 2
        report = evaluate_freeze_invalidation(root, rec, head=args.head,
                                              declared=declared)
    else:
        report = evaluate_all_freezes(root, head=args.head, declared=declared)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == FREEZE_INVALIDATED:
        return 1
    if report["status"] in ("NOT_AVAILABLE", FREEZE_UNKNOWN):
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys
    return execute_verb(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys
    sys.exit(main())
