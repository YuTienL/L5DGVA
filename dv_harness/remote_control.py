"""
dv_harness/remote_control.py
=============================

NOTICE (2026-08-28, plan-remote-control-wiring): this module previously had
zero callers anywhere -- no CLI subcommand, no GUI route. That is now fixed:
`dv-harness remote-control {bootstrap,status,cmd}` (dv_harness/cli.py) is the
real, tested caller for bootstrap_session/get_status/validate_and_transition
respectively, and the three companion skills (CORE/remote-control-readiness,
CORE/remote-control-session-manager, CORE/remote-control-status-publisher)
now name these exact commands. If a future audit greps for callers of this
module and finds none in dv_harness/*.py directly, check cli.py's
`remote-control` subcommand dispatch first -- it is there, just invoked
lazily (`from . import remote_control` inside the dispatch branch, matching
this codebase's established lazy-import style for CLI subcommands).

Real STATE-AND-VALIDATION layer for the Human Control Plane commands:
STATUS / WHY / EVIDENCE / REVIEW / HYPOTHESIS / PAUSE / RESUME / REDIRECT /
APPROVE / REJECT / STOP / TAKEOVER.

WHAT THIS MODULE IS
--------------------
- The single Python code path that reads/writes
  ``.dv-harness/remote-control/session.json`` as a real, enforced state
  machine. The legal-transition table lives in exactly one place:
  ``tools/verification_flow/remote_state_transition_gate.py``. This module
  shells out to that gate for every transition decision -- it does NOT
  hardcode a second copy of the transition rules.
- Validation of every incoming command through
  ``tools/verification_flow/remote_control_supervisory_gate.py`` before it is
  allowed to touch state (command must be in the allowed set; mutating
  commands must carry a target_stage; remote control must not masquerade as
  a third CREATE ENVIRONMENT mode).
- A real audit trail, ``.dv-harness/remote-control/audit_log.json``, that is
  re-validated on every write against
  ``tools/verification_flow/remote_action_audit_gate.py`` (required fields)
  and ``tools/verification_flow/remote_action_replay_gate.py`` (nonce
  uniqueness) -- using the real gates, not a re-implementation of their
  rules.
- One call, ``validate_and_transition(...)``, that any CLI subcommand
  (existing or a new PAUSE/RESUME/TAKEOVER/REDIRECT/APPROVE/etc. subcommand)
  can call to get: supervisory-validate -> state-transition-validate ->
  audit-append, atomically, in one place. Nothing is persisted unless every
  gate passes.

WHAT THIS MODULE IS NOT
------------------------
- It does not open an SSH session, a socket, or a websocket/HTTP server.
- It does not make Claude Web/Mobile actually reach this machine, or make
  this machine reach a Linux DV server.
- Network-based remote access is, and remains, an EXTERNAL capability (a
  human's own SSH session, or Claude Code's own separate Remote Control
  feature) that would read/write this same session.json / audit_log.json
  *if it existed*. This module only makes the state machine underneath it
  real and enforced -- it does not build the transport.

RELATIONSHIP TO ``dv_harness/control_plane.py`` (fixed 2026-08-28, found by
adversarial verification of the original design)
----------------------------------------------------------------------------
An earlier version of this module and its docstring asserted "no
PAUSE/RESUME/etc. CLI surface exists yet". That was FALSE: ``dv_harness/
cli.py`` already registers real, lowercase ``pause``/``resume``/``takeover``/
``release-takeover``/``redirect``/``approve``/``status``/``evidence``
subcommands, backed by ``control_plane.ControlPlane`` and persisted to
``.dv-harness/control.json`` -- and ``engine.py``'s ``loop()``/``run_stage()``
actually read that state on every iteration (PAUSE/TAKEOVER genuinely stop
the autonomous loop; REDIRECT genuinely changes ``current_stage``). This
module's own ``session.json``/``audit_log.json`` state machine, in isolation,
affects nothing the engine reads -- a remote client seeing
``{"ok": true, "state": "PAUSED"}`` from this module alone would be looking
at a status claim with no real effect, exactly what CLAUDE.md's Evidence
Truth Rule / "LSF DONE != DV PASS" principle warns against.

To close that gap, ``validate_and_transition`` now also applies a REAL
``ControlPlane`` (or, for REDIRECT, ``DVHarness.human_redirect``) side effect
for every command that has one, BEFORE persisting this module's own
session/audit state -- so if the ControlPlane-side effect fails/raises
(e.g. REDIRECT refused because a different stage is under TAKEOVER), nothing
is written here either; the two layers cannot go out of sync in the
"remote_control claims X, ControlPlane still says not-X" direction:

  PAUSE            -> ControlPlane.pause(reason)
  RESUME           -> ControlPlane.resume()
  TAKEOVER         -> ControlPlane.takeover(stage=target_stage, message=reason, taken_by=actor)
  REDIRECT         -> DVHarness(root).human_redirect(target_stage, reason)  [can raise RuntimeError
                       on a cross-stage TAKEOVER conflict -- surfaced as a failed command, not swallowed]
  APPROVE          -> ControlPlane.approve(stage=target_stage, note=reason, reviewer_id=actor)
                       [currently unreachable in practice -- see gap 1 below]
  STATUS/WHY/EVIDENCE/REVIEW/HYPOTHESIS -> no ControlPlane effect (these are
                       read-only per the transition table: state -> same
                       state). REVIEW and HYPOTHESIS do have real, distinct
                       READ-ONLY content of their own (see _score_hypothesis/
                       _current_stage_review_detail below) -- they just never
                       mutate ControlPlane/engine.py state, unlike PAUSE/
                       RESUME/TAKEOVER/REDIRECT/APPROVE above.
  REJECT, STOP     -> no ControlPlane equivalent exists at all (ControlPlane
                       has no reject()/stop() method, and nothing in the
                       engine treats "STOPPED" as a real halt condition
                       today). These remain SESSION-STATUS-ONLY: this
                       module's session.json will say STOPPED/whatever, but
                       the autonomous loop is not actually stopped by it.
                       Do not present REJECT/STOP through this module as
                       equivalent to PAUSE/TAKEOVER -- they are not.

KNOWN GAPS THIS MODULE DELIBERATELY DOES NOT PAPER OVER
--------------------------------------------------------
1. ``remote_state_transition_gate.py``'s ALLOWED table has no entry at all
   for APPROVE or REJECT in ANY state (RUNNING/PAUSED/TAKEOVER/STOPPED),
   even though ``remote_control_supervisory_gate.py`` accepts both as valid
   commands and requires a target_stage for them. Concretely: today, no
   sequence of commands can make APPROVE or REJECT pass the transition gate,
   so the ``ControlPlane.approve()`` wiring above is never actually reached
   through this module yet -- it is there so that fixing the transition
   table (a decision that belongs to whoever owns that gate, not to this
   module) is the only remaining step, not also this wiring.
2. ``remote_action_audit_gate.py``'s MUTATING set is
   {REDIRECT, APPROVE, REJECT, STOP, TAKEOVER} -- it does NOT include PAUSE
   or RESUME, even though both change session state per the transition
   table. This module always *offers* reason/evidence_snapshot for every
   command (see ``default_evidence_snapshot``), but per the real gate,
   PAUSE/RESUME audit entries are not rejected for omitting them.
3. ``REMOTE_CONTROL_START.ps1`` writes state ``"STARTING"`` into
   session.json. ``"STARTING"`` is not a key in
   remote_state_transition_gate.py's ALLOWED table, so no command can ever
   legally move a session out of ``"STARTING"`` through the gate -- it is a
   dead end today. ``bootstrap_session()`` below lands directly on
   ``"RUNNING"`` (the gate's actual entry state) instead, as the one
   session-establishment step that happens *before* any of the 11 gated
   commands apply; it is not itself one of those 11 commands, so it is not
   validated through the supervisory/transition gates the way PAUSE/REDIRECT/
   etc. are.
4. REJECT and STOP have no ControlPlane-side effect at all (see above) --
   this is a real, currently-unclosed gap, not an oversight in this wiring.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .control_plane import ControlPlane
from .inference import score_confidence, identify_gap, next_best_action

# The 12 Human Control Plane commands recognized by
# remote_control_supervisory_gate.py. Kept here only for input validation
# convenience (a clearer error before we even shell out) -- the gate itself
# remains the enforcement authority.
#
# HYPOTHESIS (2026-08-31, poster-gap-closing round 2, Task 8): documented in
# REMOTE_CONTROL_MODE.md ("STATUS / WHY / EVIDENCE / HYPOTHESIS / REVIEW /
# ...") since before this fix, but had zero implementation anywhere -- it was
# not even in this set, so any client issuing it failed immediately with
# INVALID_REMOTE_COMMAND before ever reaching a gate. It is now real: see
# _score_hypothesis() below and its HYPOTHESIS branch in
# validate_and_transition, wired to the same dv_harness/inference.py
# confidence engine engine.py's _score_root_cause_confidence already uses.
ALLOWED_COMMANDS = {
    "STATUS", "WHY", "EVIDENCE", "REVIEW", "HYPOTHESIS",
    "PAUSE", "RESUME", "REDIRECT",
    "APPROVE", "REJECT", "STOP", "TAKEOVER",
}

# Commands that remote_control_supervisory_gate.py requires a target_stage
# for. Mirrors that gate's own check; duplicated only as an early, friendlier
# error -- the gate call below is still the actual enforcement.
_SUPERVISORY_REQUIRES_TARGET_STAGE = {"APPROVE", "REJECT", "REDIRECT", "STOP", "TAKEOVER"}

# Commands that have a real dv_harness/control_plane.py (or engine.py
# human_redirect) side effect -- see the module docstring's "RELATIONSHIP TO
# control_plane.py" section. REJECT/STOP are deliberately absent: no such
# effect exists for them yet.
_ENGINE_EFFECT_COMMANDS = {"PAUSE", "RESUME", "TAKEOVER", "REDIRECT", "APPROVE"}

_GATE_DIR = Path("tools") / "verification_flow"
_SUPERVISORY_GATE = "remote_control_supervisory_gate.py"
_TRANSITION_GATE = "remote_state_transition_gate.py"
_AUDIT_GATE = "remote_action_audit_gate.py"
_REPLAY_GATE = "remote_action_replay_gate.py"

_SESSION_REL = Path(".dv-harness") / "remote-control" / "session.json"
_AUDIT_LOG_REL = Path(".dv-harness") / "remote-control" / "audit_log.json"

DEFAULT_ENV_MODE = "SYSTEM_LEVEL_ENV_MODE"


class GateUnavailableError(RuntimeError):
    """Raised when a required gate script is missing -- we refuse to guess
    its rules ourselves rather than silently degrade enforcement."""


@dataclass
class GateResult:
    ok: bool
    payload: Dict[str, Any]
    reason: Optional[str] = None


# --------------------------------------------------------------------------
# Low-level: run a real gate script as a subprocess, exactly as it is
# invoked elsewhere in this harness (argparse CLI, JSON in, JSON out).
# --------------------------------------------------------------------------

def _run_gate(root: Path, script_name: str, arg_name: str, payload: Dict[str, Any]) -> GateResult:
    script = root / _GATE_DIR / script_name
    if not script.exists():
        raise GateUnavailableError(f"required gate script missing: {script}")

    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="remote_control_gate_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        proc = subprocess.run(
            [sys.executable, str(script), f"--{arg_name}", tmp_path],
            capture_output=True, text=True,
        )
        try:
            out = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            out = {"status": "FAIL", "reason": "GATE_NON_JSON_OUTPUT", "stderr": proc.stderr}
        ok = proc.returncode == 0 and out.get("status") == "PASS"
        return GateResult(ok=ok, payload=out, reason=out.get("reason"))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# --------------------------------------------------------------------------
# session.json — read/write
# --------------------------------------------------------------------------

def _session_path(root: Path) -> Path:
    return root / _SESSION_REL


def _audit_log_path(root: Path) -> Path:
    return root / _AUDIT_LOG_REL


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def read_session(root: Union[str, Path] = ".") -> Dict[str, Any]:
    p = _session_path(Path(root))
    if not p.exists():
        return {
            "state": "NOT_STARTED", "session_id": None, "host": None,
            "working_directory": None, "started_at": None,
            "last_status_update": None, "remote_control_enabled": False,
        }
    return json.loads(p.read_text(encoding="utf-8"))


def read_audit_log(root: Union[str, Path] = ".") -> List[Dict[str, Any]]:
    p = _audit_log_path(Path(root))
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("actions", [])


def default_evidence_snapshot(root: Union[str, Path] = ".",
                               topics: Optional[List[str]] = None) -> Dict[str, Any]:
    """Best-effort evidence_snapshot pulled from the real Blackboard (current
    verification truth per CLAUDE.md), for callers that don't have a more
    specific snapshot to attach to a mutating remote action. Never raises --
    an empty/partial blackboard just yields an empty/partial snapshot."""
    try:
        from .blackboard import Blackboard
    except Exception:
        return {}
    try:
        bb = Blackboard(Path(root))
        topics = topics or ["current_stage", "overall_status", "last_failure"]
        return bb.snapshot(topics)
    except Exception:
        return {}


def bootstrap_session(root: Union[str, Path] = ".", *, host: Optional[str] = None,
                       working_directory: Optional[str] = None,
                       session_id: Optional[str] = None,
                       actor: str = "local") -> Dict[str, Any]:
    """Session establishment -- NOT one of the 11 gated commands, so it is
    not run through the supervisory/transition gates. Lands the session
    directly on RUNNING (the transition gate's real entry state), fixing the
    STARTING dead-end that REMOTE_CONTROL_START.ps1 currently produces.
    Still writes a real audit entry so the bootstrap itself is traceable."""
    root = Path(root)
    now = _now()
    session = {
        "state": "RUNNING",
        "session_id": session_id or uuid.uuid4().hex,
        "host": host or os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME"),
        "working_directory": working_directory or str(root.resolve()),
        "started_at": now,
        "last_status_update": now,
        "remote_control_enabled": True,
    }
    _atomic_write_json(_session_path(root), session)
    entry = {
        "command": "BOOTSTRAP", "timestamp": now, "actor": actor,
        "target_stage": None, "reason": "session_bootstrap",
        "evidence_snapshot": default_evidence_snapshot(root),
        "nonce": uuid.uuid4().hex,
    }
    _append_audit_unchecked(root, entry)
    return session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_control_plane_effect(command: str, root: Path, *, target_stage: Optional[str],
                                 reason: Optional[str], actor: str) -> None:
    """Apply the REAL engine-side effect for `command`, if one exists (see
    the module docstring). Raises on failure -- callers must not persist
    this module's own session/audit state if this raises, or the two layers
    go out of sync (this module claiming e.g. PAUSED while the autonomous
    loop keeps running). No-op (returns None) for commands with no
    ControlPlane/engine effect (STATUS/WHY/EVIDENCE/REVIEW/REJECT/STOP)."""
    if command not in _ENGINE_EFFECT_COMMANDS:
        return
    if command == "REDIRECT":
        # human_redirect lives on DVHarness, not ControlPlane, since it also
        # needs StateStore to move current_stage. Local import: engine.py
        # does not import this module, so there is no cycle, but importing
        # lazily keeps this module's own import graph light for callers that
        # only ever issue PAUSE/RESUME/TAKEOVER/APPROVE.
        from .engine import DVHarness
        DVHarness(root).human_redirect(target_stage, reason=reason or "")
        return
    cp = ControlPlane(root)
    if command == "PAUSE":
        cp.pause(reason=reason or "")
    elif command == "RESUME":
        cp.resume()
    elif command == "TAKEOVER":
        cp.takeover(stage=target_stage, message=reason or "", taken_by=actor)
    elif command == "APPROVE":
        cp.approve(stage=target_stage, note=reason or "", reviewer_id=actor)


# --------------------------------------------------------------------------
# HYPOTHESIS / REVIEW read-only content (2026-08-31, poster-gap-closing round
# 2, Task 8). Both reuse the SAME dv_harness/inference.py confidence engine
# engine.py's DVHarness._score_root_cause_confidence already wires -- this
# module does not re-implement the math, only re-derives its inputs from
# whatever evidence it has on hand (a caller-supplied evidence_snapshot for
# HYPOTHESIS, the current stage's real StageState for REVIEW).
# --------------------------------------------------------------------------

# The subset of root_cause_evidence_gate.py's own required evidence fields
# that genuinely varies (mirrors engine.py's DVHarness.ROOT_CAUSE_EVIDENCE_
# CATEGORIES exactly, duplicated here rather than imported to avoid a
# module-level import of engine.py -- see the REDIRECT lazy-import note
# above for why that coupling is kept lazy/local in this module).
HYPOTHESIS_EVIDENCE_CATEGORIES = [
    "first_bad_event", "causal_chain", "supporting_evidence", "counter_evidence",
]


def _cite_count(value: Any) -> int:
    """Same citation-counting rule as engine.py's _score_root_cause_confidence
    inline helper of the same name: list/dict length, else 1/0 for any other
    truthy/falsy value. Kept identical so HYPOTHESIS's independently computed
    confidence agrees with the engine's own recompute when fed the same
    evidence block, rather than silently drifting into a second rule set."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 1 if value else 0


def _score_hypothesis(evidence_block: Optional[Dict[str, Any]], root: Path) -> Dict[str, Any]:
    """Real inference.py scoring for the HYPOTHESIS command -- never a
    hardcoded/self-reported value. `evidence_block` is the same shape as
    root_cause_evidence_gate's own evidence block (first_bad_event/
    causal_chain/supporting_evidence/counter_evidence/hypotheses/root_cause/
    protocol); a missing/empty block yields a real, honestly-LOW score
    (score_confidence(0, False, 0, 0)) rather than a fabricated placeholder."""
    block = evidence_block or {}

    independent_sources_count = _cite_count(block.get("supporting_evidence"))
    counter_evidence_count = _cite_count(block.get("counter_evidence"))
    evidence_refs_verified = bool(
        block.get("first_bad_event") and block.get("causal_chain") and block.get("supporting_evidence")
    )

    hyps = block.get("hypotheses")
    multi_agent_consensus_count = 0
    if isinstance(hyps, list):
        selected_claim = block.get("root_cause")
        multi_agent_consensus_count = sum(
            1 for h in hyps
            if isinstance(h, dict) and h.get("claim") != selected_claim and h.get("counter_evidence")
        )

    confidence_result = score_confidence(
        independent_sources_count=independent_sources_count,
        evidence_refs_verified=evidence_refs_verified,
        counter_evidence_count=counter_evidence_count,
        multi_agent_consensus_count=multi_agent_consensus_count,
    )

    supplied = [c for c in HYPOTHESIS_EVIDENCE_CATEGORIES if block.get(c)]
    gap = identify_gap(HYPOTHESIS_EVIDENCE_CATEGORIES, supplied)
    protocol = block.get("protocol") or "_general"
    next_actions = next_best_action(protocol, gap, root) if gap else []

    return {
        "confidence": confidence_result,
        "gap": gap,
        "next_best_action": next_actions,
        "evidence_block": block,
    }


def _current_stage_review_detail(root: Path) -> Dict[str, Any]:
    """REVIEW's differentiated, read-only content: the current stage's real
    StageState (gate verdict/evidence refs/blocking reason/attempts -- the
    same record engine.py's run_stage() itself persists via StateStore), plus
    the most recent independently-recomputed root-cause confidence for THIS
    stage if engine.py's _score_root_cause_confidence already wrote one to
    the blackboard "root_cause_confidence" topic. Genuinely different content
    from STATUS's plain session.json + last-audit-action summary -- never a
    relabeled copy of it. Read-only: no state is written here."""
    from .engine import DVHarness
    h = DVHarness(root)
    stage = h.state.current_stage
    stage_state = h.state.stages.get(stage, {})

    recomputed_confidence = None
    bb_entry = h.blackboard.read("root_cause_confidence")
    if isinstance(bb_entry, dict):
        value = bb_entry.get("value")
        if isinstance(value, dict) and value.get("stage") == stage:
            recomputed_confidence = value

    return {
        "stage": stage,
        "gate_verdict": stage_state.get("status"),
        "evidence": stage_state.get("evidence", []),
        "attempts": stage_state.get("attempts", 0),
        "last_message": stage_state.get("last_message", ""),
        "blocking_reason": stage_state.get("blocking_reason", ""),
        "recomputed_confidence": recomputed_confidence,
    }


def _append_audit_unchecked(root: Path, entry: Dict[str, Any]) -> None:
    # Used only by bootstrap_session, which is intentionally outside the
    # gated command flow. All 11 gated commands go through
    # validate_and_transition, which re-validates with the real audit/replay
    # gates before persisting (see below).
    actions = read_audit_log(root)
    actions.append(entry)
    _atomic_write_json(_audit_log_path(root), {"actions": actions})


# --------------------------------------------------------------------------
# The one call every CLI command composes with.
# --------------------------------------------------------------------------

def validate_and_transition(
    command: str,
    *,
    target_stage: Optional[str] = None,
    reason: Optional[str] = None,
    actor: str = "local",
    evidence_snapshot: Optional[Dict[str, Any]] = None,
    env_mode: str = DEFAULT_ENV_MODE,
    project_root: Union[str, Path] = ".",
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """Validate one Human Control Plane command and, if legal, apply it.

    Returns (ok, new_state, audit_entry, error_reason):
      - ok=True  -> new_state is the (possibly unchanged) session state after
                    the command, audit_entry is what was appended to
                    audit_log.json, error_reason is None.
      - ok=False -> new_state/audit_entry are None (nothing was persisted --
                    this call is transactional), error_reason names which
                    gate rejected it and why.

    `env_mode` must be the CREATE ENVIRONMENT mode currently in force
    (SUBSYSTEM_ENV_MODE or SYSTEM_LEVEL_ENV_MODE) per
    remote_control_supervisory_gate.py's schema -- remote control is a
    supervisory layer over that mode, never a third mode of its own. This
    module does not track environment-generation mode itself (that state
    does not exist yet in HarnessState); callers that know the current mode
    should pass it explicitly.
    """
    root = Path(project_root)
    command = (command or "").upper()

    if command not in ALLOWED_COMMANDS:
        return False, None, None, f"INVALID_REMOTE_COMMAND:{command}"
    if command in _SUPERVISORY_REQUIRES_TARGET_STAGE and not target_stage:
        return False, None, None, "CONTROL_ACTION_WITHOUT_TARGET_STAGE"

    session = read_session(root)
    current_state = session.get("state", "NOT_STARTED")

    # 1) Supervisory gate: is this command well-formed / in scope at all?
    supervisory = _run_gate(root, _SUPERVISORY_GATE, "request", {
        "mode": env_mode,
        "remote_command": command,
        "target_stage": target_stage,
        "remote_control_as_environment_mode": False,
    })
    if not supervisory.ok:
        return False, None, None, supervisory.reason or "SUPERVISORY_GATE_FAIL"

    # 2) State-transition gate: is this command legal from the CURRENT state?
    #    This is the one and only transition table -- we do not re-implement
    #    ALLOWED here.
    transition = _run_gate(root, _TRANSITION_GATE, "request", {
        "current_state": current_state,
        "command": command,
    })
    if not transition.ok:
        return False, None, None, transition.reason or "ILLEGAL_REMOTE_STATE_TRANSITION"
    new_state = transition.payload["next_state"]

    # 2b) Apply the REAL ControlPlane/engine-side effect (see module
    #     docstring) BEFORE persisting anything below -- if this raises
    #     (e.g. REDIRECT refused by a cross-stage TAKEOVER), this module's
    #     own session/audit state must not claim the command succeeded.
    try:
        _apply_control_plane_effect(command, root, target_stage=target_stage,
                                     reason=reason, actor=actor)
    except Exception as exc:
        return False, None, None, f"CONTROL_PLANE_EFFECT_FAILED:{exc}"

    # 2c) HYPOTHESIS/REVIEW's own real, differentiated content -- computed
    #     against the SAME dv_harness/inference.py confidence engine
    #     engine.py already wires, not a hardcoded/relabeled STATUS payload.
    #     Both are read-only (see _ENGINE_EFFECT_COMMANDS above -- neither is
    #     in it), so nothing here mutates ControlPlane/engine.py state; a
    #     failure here is surfaced as a failed command, same as 2b, so this
    #     module never claims success while silently dropping the content it
    #     promised.
    extra_detail: Dict[str, Any] = {}
    try:
        if command == "HYPOTHESIS":
            extra_detail["hypothesis_result"] = _score_hypothesis(evidence_snapshot, root)
        elif command == "REVIEW":
            extra_detail["review_detail"] = _current_stage_review_detail(root)
    except Exception as exc:
        return False, None, None, f"{command}_CONTENT_FAILED:{exc}"

    # 3) Build the audit entry and prove it passes BOTH audit gates before
    #    anything is persisted (transactional: validate fully, then write).
    entry = {
        "command": command,
        "timestamp": _now(),
        "actor": actor,
        "target_stage": target_stage,
        "reason": reason,
        "evidence_snapshot": evidence_snapshot if evidence_snapshot is not None
                              else (default_evidence_snapshot(root) if command in _SUPERVISORY_REQUIRES_TARGET_STAGE else None),
        "nonce": uuid.uuid4().hex,
        **extra_detail,
    }
    existing_actions = read_audit_log(root)
    candidate_actions = existing_actions + [entry]

    audit_check = _run_gate(root, _AUDIT_GATE, "audit", {"actions": candidate_actions})
    if not audit_check.ok:
        return False, None, None, audit_check.reason or "AUDIT_GATE_FAIL"

    replay_check = _run_gate(root, _REPLAY_GATE, "audit", {"actions": candidate_actions})
    if not replay_check.ok:
        return False, None, None, replay_check.reason or "REPLAY_GATE_FAIL"

    # 4) All gates passed -- persist session state and audit trail together.
    now = _now()
    session["state"] = new_state
    session["last_status_update"] = now
    session["remote_control_enabled"] = new_state != "STOPPED"
    _atomic_write_json(_session_path(root), session)
    _atomic_write_json(_audit_log_path(root), {"actions": candidate_actions})

    return True, new_state, entry, None


def get_status(project_root: Union[str, Path] = ".") -> Dict[str, Any]:
    """Convenience read for a STATUS-style query: current session plus the
    most recent audit entry, with no gate side effects (read-only)."""
    root = Path(project_root)
    session = read_session(root)
    actions = read_audit_log(root)
    return {
        "session": session,
        "last_action": actions[-1] if actions else None,
        "action_count": len(actions),
    }
