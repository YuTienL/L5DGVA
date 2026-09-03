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
"""
from __future__ import annotations

import hashlib
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

    return {
        "state_file_present": state_present,
        "current_stage": current_stage,
        "stage_status": stage_status,
        "gate_verified": stage_status == SIGNOFF_VERIFIED_STATUS,
        "signoff_event_count": signoff_event_count,
        "subsystem_registry_present": registry_path.is_file(),
        "required_signoff_gates": required_gates,
    }


def collect_signoff_bundle(root: Path, out_dir: Path, notifier=None,
                           require_signoff_pass: bool = False) -> Dict[str, Any]:
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
    directory a later reader mistakes for a partial bundle."""
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
    }
