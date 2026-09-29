"""dv_harness/intake_contract_stale_detection.py -- section 18: a real
detector that DRIVES a `verification_intake_contract.VerificationIntakeContract`
into `STALE` from real evidence.

WHAT WAS ACTUALLY MISSING, re-verified before this file was written.
`verification_intake_contract.py`'s own 13-state lifecycle already carries a
real `BASELINED -> STALE -> REVALIDATING` edge (`TRANSITIONS[BASELINED] ==
(STALE,)`, enforced by `assert_legal_transition()`), and its own docstring
already reasons about WHY that edge exists ("a baselined contract can be
invalidated by a later spec/RTL/config change exactly the way
`signoff_export.py`'s frozen baseline can... this module does not
re-implement that decision, it only accepts the caller's resulting STALE
transition once made"). A repo-wide grep for `intake_stale`/
`IntakeContractStale`/`intake_contract_stale` before this file was written
matched nothing executable anywhere in `dv_harness/`: `intake_modes.py`
reuses `evaluate_intake_readiness()` for a different question (which
critical conditions are in scope for which intake mode) and never touches
lifecycle staleness at all. So the STALE state had a real legal edge and a
real reason it should exist, but -- exactly the gap `loop_stale_detection.py`
closed one module over for `loop_contract.LoopState.STALE` -- no real
detector anywhere ever produced the STALE transition from real evidence; a
contract baselined months ago against RTL/spec that has since moved would
report BASELINED forever unless a human happened to notice and hand-typed a
`transition_contract(..., "STALE", ...)` call themselves.

WHAT THIS MODULE IS. Two real, independently-checkable signals, mirroring
`loop_stale_detection.py`'s own pattern for `LoopState.STALE` exactly --
reusing this harness's OWN existing evidence producers rather than inventing
a third, and applying the identical worst-wins / "an unresolved UNKNOWN
outranks a clean NOT_STALE" discipline that module already established:

  * TIME-BASED staleness -- how long ago this contract was last transitioned
    INTO `BASELINED`. Unlike a loop session (whose "just transitioned"
    record lives in `state.json` on disk), a `VerificationIntakeContract`
    already carries its OWN full `state_history` in memory
    (`transition_contract()` appends one real `{"from", "to", "reason",
    "by", "at"}` entry on every move), so this signal is read directly off
    the contract object -- no disk I/O, and never a state.json this module
    would have to know the shape of. Compared against a DECLARED staleness
    window (`policy.intake_stale_after_seconds` in `config.json`, or this
    module's own documented `DEFAULT_INTAKE_STALE_AFTER_SECONDS` when a
    project has not declared one -- never a number invented FOR this
    specific project). The default is deliberately a WEEK, not a day: an
    intake baseline is a slower-moving commitment than one loop session's
    "just ran" freshness, and inventing the loop module's own 24h default
    for a structurally different question would be exactly the "reuse a
    number, not just a discipline" mistake this project's own precedent
    warns against.
  * ENVIRONMENT-MOVED staleness -- the project's real current git HEAD has
    moved, by a REAL `git diff --name-only` computed through
    `change_impact.changed_files()` -- the exact function
    `loop_stale_detection.py`, `golden_scenario.evaluate_freshness()` and
    `signoff_export.evaluate_freeze_invalidation()` already reuse for the
    identical "did the design move" question at three other layers --
    classified through the SAME `change_impact.classify_risk()` HIGH/
    MEDIUM/LOW ladder those three callers already use. A LOW-risk-only diff
    (docs, `.dv-harness`/`.claude` bookkeeping) does not call the contract
    stale; a HIGH/MEDIUM one does. Because `VerificationIntakeContract`
    carries no built-in `git_sha` field of its own (unlike `state.json`),
    the recorded baseline SHA is read from a caller-declared convention --
    `contract.sub_domains["baseline_git_sha"]`, the same `sub_domain_data`
    bucket every other real per-domain fact already lives in, set by
    whoever baselined the contract (e.g.
    `transition_contract(c, "BASELINED", reason=..., sub_domain_data=
    {"baseline_git_sha": current_sha})`) -- or an explicit caller-supplied
    `recorded_sha` override. Neither present is honestly `UNKNOWN`, never a
    guessed "nothing moved".

Both signals are worst-wins with the Evidence Truth Rule's own "an
unresolved UNKNOWN is never silently read as clean" discipline: STALE from
either signal outranks everything; absent that, an UNKNOWN signal (no real
baseline-event evidence, no recorded SHA, no git) outranks a clean
NOT_STALE, because "we could not check" must never be presented as "we
checked and it is fine".

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

  * It does not decide anything on its own. `detect_intake_contract_
    staleness()` is a pure READ over real, already-persisted evidence (the
    contract's own history plus a real git diff) -- no build, no job, no
    approval, and no stage gate references it.
  * It does not re-implement `verification_intake_contract.py`'s own
    transition enforcement. `apply_stale_transition()` is a thin wrapper
    around that module's real, already-tested `transition_contract()` --
    the SAME `assert_legal_transition()` call every other transition in
    this project goes through decides whether `STALE` is actually reachable
    from the contract's current state (only `BASELINED` may move to
    `STALE`, per `TRANSITIONS`); this module never second-guesses that.
  * It does not decide what "the contract's own facts changed" means beyond
    the two signals above -- it does not open `env.manifest.json`, does not
    re-read `waiver_store.py`, does not query the evidence database. Adding
    a sub-domain-specific staleness signal (an expired waiver, a moved VIP
    release) is a real, disclosed extension point future work could add,
    not something this module invents to look more complete than it is.
  * It mints no `.dv-harness/` tree. `config.json` is read with a plain,
    tolerant `json.loads()` (never `config.load_config()`, which CREATES
    the file for a project that has never run) -- the same reasoning
    `loop_stale_detection.py`/`golden_flow_readiness.py` already record for
    themselves. A bare project with no `.dv-harness/` at all reports an
    honest `UNKNOWN` window/environment signal, and nothing is written to
    disk.

WIRING. There is no analogue to `loop_contract.derive_loop_state()`'s
`stale:` keyword to extend here, because `verification_intake_contract.py`'s
own lifecycle is not a derived-state function at all -- it is a real,
persisted `VerificationIntakeContract.state` field, and the sanctioned way
to move it is already `transition_contract()`. So the wiring this module
provides is `apply_stale_transition()` (a thin, enforced call into that real
function) and `detect_and_maybe_transition()` (detect, then apply only when
the evidence says STALE AND the contract is still legally eligible -- i.e.
currently `BASELINED`), rather than a new parameter on an existing
function. Both are best-effort at the CALLER's discretion: nothing in this
module runs automatically on any schedule or stage boundary.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field as _dc_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .verification_intake_contract import (
    IntakeContractError,
    IntakeContractState,
    VerificationIntakeContract,
    transition_contract,
)

#: This module's own three-value status vocabulary. `STALE` is deliberately
#: the SAME literal as `IntakeContractState.STALE.value` -- a disclosed reuse
#: of the exact section-18 name this module exists to produce evidence for,
#: never a second, differently-spelled vocabulary for the identical fact.
STALE = IntakeContractState.STALE.value
NOT_STALE = "NOT_STALE"
UNKNOWN = "UNKNOWN"
STALENESS_STATUSES: Tuple[str, ...] = (STALE, NOT_STALE, UNKNOWN)

#: The two real, independently-computed signals this module folds together.
SIGNAL_TIME_BASED = "TIME_BASED"
SIGNAL_ENVIRONMENT_MOVED = "ENVIRONMENT_MOVED"

#: The project-neutral default staleness window for a BASELINED intake
#: contract: a week with no real baselining event is treated as dormant
#: unless a project declares its own `policy.intake_stale_after_seconds`.
#: Deliberately NOT `loop_stale_detection.DEFAULT_STALE_AFTER_SECONDS` (24h)
#: -- an intake baseline is a slower-moving commitment than "this loop
#: session just ran", and this module states its own reason rather than
#: silently borrowing a number tuned for a different question.
DEFAULT_INTAKE_STALE_AFTER_SECONDS = 7 * 24 * 60 * 60

#: The `sub_domains` key convention this module reads a recorded baseline
#: git SHA from, when a caller does not supply one explicitly. Whoever moves
#: a contract to `BASELINED` is expected to record it here, e.g.
#: `transition_contract(c, "BASELINED", reason=..., sub_domain_data=
#: {"baseline_git_sha": current_sha})`.
RECORDED_SHA_SUB_DOMAIN_KEY = "baseline_git_sha"


def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """A plain, tolerant JSON read that mints nothing. Returns None for an
    absent, unreadable, or non-object file -- never raises, and never
    creates the file the way `config.load_config()` would."""
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse one `engine.now()`-shaped ISO-8601 UTC timestamp -- the same
    shape `transition_contract()`'s own `at` field always carries. Returns
    None for anything this cannot honestly parse -- never a guessed time."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def declared_intake_stale_window_seconds(root: Path,
                                         cfg: Optional[Dict[str, Any]] = None
                                         ) -> Tuple[float, str]:
    """(seconds, source). Reads a real `config.json`'s own
    `policy.intake_stale_after_seconds` when a project has declared one;
    `DEFAULT_INTAKE_STALE_AFTER_SECONDS` otherwise -- and says which
    applied, so a caller can never mistake the default for a
    project-specific measurement."""
    root = Path(root)
    if cfg is None:
        cfg = _read_json_file(root / ".dv-harness" / "config.json")
    policy = (cfg or {}).get("policy") or {}
    declared = policy.get("intake_stale_after_seconds")
    if isinstance(declared, (int, float)) and not isinstance(declared, bool) and declared > 0:
        return float(declared), "config.json policy.intake_stale_after_seconds"
    return (float(DEFAULT_INTAKE_STALE_AFTER_SECONDS),
            "DEFAULT_INTAKE_STALE_AFTER_SECONDS (this project has not declared "
            "policy.intake_stale_after_seconds)")


@dataclass
class LastBaselineEvidence:
    """The real timestamp `detect_time_based_staleness()` measured staleness
    against, and where it came from -- so a caller can go check it."""
    timestamp: Optional[str]
    source: str
    detail: Dict[str, Any] = _dc_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def last_baselined_event(contract: VerificationIntakeContract) -> LastBaselineEvidence:
    """The real, most recent `state_history` entry recording this contract's
    own move INTO `BASELINED` -- read directly off the contract object
    (`transition_contract()` already appends one such entry on every real
    transition; there is no second history this module could disagree
    with). A contract that has never reached `BASELINED` at all -- CREATED,
    still DISCOVERING, blocked in CONFLICT, or any other pre-baseline state
    -- carries no such evidence, and this reports that honestly rather than
    inventing one. If a contract was baselined more than once (a real
    `STALE -> REVALIDATING -> ... -> BASELINED` cycle), the MOST RECENT
    baselining event is the one that matters for freshness."""
    entries = [h for h in (contract.state_history or [])
              if isinstance(h, dict) and h.get("to") == IntakeContractState.BASELINED.value]
    if not entries:
        return LastBaselineEvidence(
            timestamp=None, source="NO_REAL_BASELINE_EVENT_EVIDENCE",
            detail={"checked": "contract.state_history[*].to == BASELINED", "found": 0})
    entries = sorted(entries, key=lambda h: h.get("at") or "")
    last = entries[-1]
    return LastBaselineEvidence(
        timestamp=last.get("at"), source="state_history_baselined_transition",
        detail={"reason": last.get("reason"), "by": last.get("by")})


def detect_time_based_staleness(contract: VerificationIntakeContract, root: Path,
                                cfg: Optional[Dict[str, Any]] = None, *,
                                staleness_window_seconds: Optional[float] = None,
                                now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """One signal: is this contract's last real BASELINED transition older
    than the declared window. `UNKNOWN` (never a guessed NOT_STALE) when
    this contract has never actually reached `BASELINED`."""
    root = Path(root)
    now_dt = now_dt or datetime.now(timezone.utc)
    if staleness_window_seconds is not None:
        window, window_source = float(staleness_window_seconds), "caller-supplied"
    else:
        window, window_source = declared_intake_stale_window_seconds(root, cfg)

    ev = last_baselined_event(contract)
    ts = _parse_ts(ev.timestamp)
    base = {"signal": SIGNAL_TIME_BASED, "window_seconds": window,
            "window_source": window_source, "last_baselined": ev.to_dict()}
    if ts is None:
        base.update(status=UNKNOWN,
                    reason=f"NO_REAL_BASELINE_EVENT_EVIDENCE: {ev.source} named no timestamp "
                            f"to measure staleness against")
        return base

    age_seconds = (now_dt - ts).total_seconds()
    base["age_seconds"] = age_seconds
    if age_seconds > window:
        base.update(status=STALE,
                    reason=(f"last baselined ({ev.source}) at {ev.timestamp} is "
                            f"{age_seconds:.0f}s old, exceeding the declared "
                            f"{window:.0f}s staleness window ({window_source})"))
    else:
        base.update(status=NOT_STALE,
                    reason=(f"last baselined ({ev.source}) at {ev.timestamp} is "
                            f"{age_seconds:.0f}s old, within the {window:.0f}s window "
                            f"({window_source})"))
    return base


def _recorded_baseline_sha(contract: VerificationIntakeContract,
                           recorded_sha: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """(sha, source). A caller-supplied `recorded_sha` always wins; absent
    that, the real `sub_domains["baseline_git_sha"]` convention (see the
    module docstring) is consulted. Neither present is (None, None) -- never
    a guessed SHA."""
    if recorded_sha:
        return recorded_sha, "caller-supplied"
    sub = contract.sub_domains or {}
    v = sub.get(RECORDED_SHA_SUB_DOMAIN_KEY)
    if v:
        return v, f"sub_domains.{RECORDED_SHA_SUB_DOMAIN_KEY}"
    return None, None


def detect_environment_moved_staleness(contract: VerificationIntakeContract, root: Path, *,
                                       recorded_sha: Optional[str] = None,
                                       head_sha: str = "HEAD") -> Dict[str, Any]:
    """One signal: has the project's real source moved (a real, HIGH/MEDIUM-
    risk git diff) since the git SHA this contract was baselined against.
    `UNKNOWN` (never a guessed NOT_STALE) with no recorded SHA to diff
    against, or when the real diff itself could not be computed
    (`change_impact.changed_files()`'s own NO_GIT/UNKNOWN_BASE/UNKNOWN_HEAD/
    DIFF_FAILED statuses, propagated rather than swallowed)."""
    root = Path(root)
    sha, sha_source = _recorded_baseline_sha(contract, recorded_sha)
    if not sha:
        return {"signal": SIGNAL_ENVIRONMENT_MOVED, "status": UNKNOWN,
                "reason": (f"NO_RECORDED_SHA: neither a caller-supplied recorded_sha nor "
                          f"contract.sub_domains['{RECORDED_SHA_SUB_DOMAIN_KEY}'] names a git "
                          f"SHA to compare against this project's current HEAD")}

    from .change_impact import changed_files, classify_risk
    diff = changed_files(root, sha, head_sha)
    base = {"signal": SIGNAL_ENVIRONMENT_MOVED, "recorded_sha": sha,
            "recorded_sha_source": sha_source, "head_sha": head_sha,
            "diff_status": diff.get("status")}
    if diff.get("status") != "REAL_DIFF":
        base.update(status=UNKNOWN,
                    reason=f"{diff.get('status')}: {diff.get('detail')}")
        return base

    files = diff.get("files") or []
    base.update(base_sha=diff.get("base_sha"), resolved_head_sha=diff.get("head_sha"),
               changed_files=files)
    if not files:
        base.update(status=NOT_STALE,
                    reason=f"NO_CHANGE_SINCE_RECORDED_SHA {diff.get('base_sha')}")
        return base

    risk_by_file = {f: classify_risk(f) for f in files}
    base["risk_by_file"] = risk_by_file
    substantive = [f for f, r in risk_by_file.items() if r != "LOW"]
    if substantive:
        base.update(status=STALE,
                    reason=(f"the project moved since {diff.get('base_sha')}: "
                            f"{len(substantive)} substantively-risky file(s) changed "
                            f"(e.g. {sorted(substantive)[:5]})"))
    else:
        base.update(status=NOT_STALE,
                    reason=(f"{len(files)} file(s) changed since {diff.get('base_sha')} "
                            f"but all classify LOW risk (docs/bookkeeping)"))
    return base


def detect_intake_contract_staleness(contract: VerificationIntakeContract, root: Path,
                                     cfg: Optional[Dict[str, Any]] = None, *,
                                     recorded_sha: Optional[str] = None,
                                     head_sha: str = "HEAD",
                                     staleness_window_seconds: Optional[float] = None,
                                     now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """The combined verdict, worst-wins: STALE if either real signal fired,
    else UNKNOWN if either could not be checked (never silently read as
    clean), else NOT_STALE. Every signal's own report is carried in full, so
    a caller (or a human) can see exactly which one decided the verdict."""
    root = Path(root)
    time_signal = detect_time_based_staleness(
        contract, root, cfg, staleness_window_seconds=staleness_window_seconds, now_dt=now_dt)
    env_signal = detect_environment_moved_staleness(
        contract, root, recorded_sha=recorded_sha, head_sha=head_sha)
    signals = [time_signal, env_signal]

    if any(s.get("status") == STALE for s in signals):
        status = STALE
    elif any(s.get("status") == UNKNOWN for s in signals):
        status = UNKNOWN
    else:
        status = NOT_STALE

    return {
        "root": str(root),
        "contract_id": contract.contract_id,
        "contract_state": contract.state,
        "status": status,
        "is_stale": status == STALE,
        "signals": signals,
    }


def _summarize_stale_reasons(report: Dict[str, Any]) -> str:
    stale_signals = [s for s in (report.get("signals") or []) if s.get("status") == STALE]
    if not stale_signals:
        return "intake contract stale"
    return "; ".join(f"{s['signal']}: {s['reason']}" for s in stale_signals)


def apply_stale_transition(contract: VerificationIntakeContract, report: Dict[str, Any], *,
                           reason: Optional[str] = None, by: Optional[str] = None,
                           now: Optional[str] = None) -> VerificationIntakeContract:
    """Drives `contract` into `STALE` using the real, already-enforced
    `verification_intake_contract.transition_contract()` -- this module
    never mutates a contract's state directly, and never second-guesses that
    function's own `assert_legal_transition()` (only a `BASELINED` contract
    may legally move to `STALE`; anything else raises
    `IntakeContractError("ILLEGAL_STATE_TRANSITION", ...)` exactly as it
    would for a hand-typed call).

    Refuses -- raising `IntakeContractError("STALENESS_REPORT_DOES_NOT_SAY_
    STALE", ...)` -- unless `report` itself is a real `detect_
    intake_contract_staleness()` result whose `status` is `STALE`: this
    function is the enforcement point that a real transition is never driven
    by anything less than real, checked evidence."""
    if not isinstance(report, dict) or report.get("status") != STALE:
        raise IntakeContractError("STALENESS_REPORT_DOES_NOT_SAY_STALE", {
            "report_status": (report or {}).get("status") if isinstance(report, dict) else None,
            "hint": "apply_stale_transition() requires a real detect_intake_contract_"
                    "staleness() result whose status is STALE",
        })
    real_reason = reason or _summarize_stale_reasons(report)
    return transition_contract(contract, STALE, reason=real_reason, by=by, now=now)


def detect_and_maybe_transition(contract: VerificationIntakeContract, root: Path,
                                cfg: Optional[Dict[str, Any]] = None, *,
                                recorded_sha: Optional[str] = None, head_sha: str = "HEAD",
                                staleness_window_seconds: Optional[float] = None,
                                now_dt: Optional[datetime] = None,
                                by: Optional[str] = None
                                ) -> Tuple[Dict[str, Any], Optional[VerificationIntakeContract]]:
    """Detect, then apply the real transition ONLY when both (a) the
    evidence says STALE and (b) the contract is still legally eligible right
    now (i.e. its current state is `BASELINED` -- a contract already moved
    on by a human, or already STALE, is left untouched). Returns
    `(report, new_contract_or_None)`; `new_contract` is `None` whenever no
    transition was made, so a caller can tell "checked, still fine" apart
    from "checked, moved"."""
    report = detect_intake_contract_staleness(
        contract, root, cfg, recorded_sha=recorded_sha, head_sha=head_sha,
        staleness_window_seconds=staleness_window_seconds, now_dt=now_dt)
    if report["status"] != STALE or contract.state != IntakeContractState.BASELINED.value:
        return report, None
    return report, apply_stale_transition(contract, report, by=by)


# --------------------------------------------------------------------------
# Front door -- no `dv-harness` CLI verb per this project's own file-safety
# convention (`cli.py` is on this batch's never-touch list); `python -m` is
# the sanctioned fallback several sibling modules already use.
# --------------------------------------------------------------------------
def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_contract_json(path: Path) -> VerificationIntakeContract:
    """Reconstructs a `VerificationIntakeContract` from a real, previously
    written `VerificationIntakeContract.to_dict()` JSON file -- this module
    never mints a contract of its own; that stays a caller's job (this
    project's own `verification_intake_contract.py` persists nothing to
    disk on its own, by design)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return VerificationIntakeContract(
        contract_id=d["contract_id"], state=d["state"],
        sub_domains=d.get("sub_domains") or {},
        state_history=d.get("state_history") or [],
        created_at=d.get("created_at") or _utcnow_iso(),
        updated_at=d.get("updated_at") or _utcnow_iso(),
    )


def execute_verb(root: Path, verb: str, *,
                 contract_path: Optional[str] = None,
                 cfg: Optional[Dict[str, Any]] = None,
                 recorded_sha: Optional[str] = None,
                 staleness_window_seconds: Optional[float] = None) -> Tuple[int, Any]:
    """One implementation behind
    `python -m dv_harness.intake_contract_stale_detection`, the same shared-
    `execute_verb()` convention `loop_stale_detection`/`loop_contract`/
    `loop_budget` already follow."""
    root = Path(root)
    if verb == "window":
        seconds, source = declared_intake_stale_window_seconds(root, cfg)
        return 0, {"window_seconds": seconds, "window_source": source}
    if verb == "detect":
        if not contract_path:
            return 2, {"ok": False, "error": "MISSING_CONTRACT",
                       "hint": "detect requires --contract <file.json> (a "
                               "VerificationIntakeContract.to_dict() serialization)"}
        try:
            contract = load_contract_json(Path(contract_path))
        except Exception as e:
            return 2, {"ok": False, "error": "CONTRACT_LOAD_FAILED", "detail": str(e)}
        report = detect_intake_contract_staleness(
            contract, root, cfg, recorded_sha=recorded_sha,
            staleness_window_seconds=staleness_window_seconds)
        exit_code = {STALE: 1, NOT_STALE: 0, UNKNOWN: 2}[report["status"]]
        return exit_code, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["window", "detect"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.intake_contract_stale_detection",
        description="Section 18: is a VerificationIntakeContract's BASELINED evidence still "
                    "fresh, real detection.")
    ap.add_argument("verb", choices=["window", "detect"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--contract", default=None,
                    help="For 'detect': path to a VerificationIntakeContract.to_dict() JSON file.")
    ap.add_argument("--recorded-sha", default=None)
    ap.add_argument("--window-seconds", type=float, default=None)
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 contract_path=args.contract, recorded_sha=args.recorded_sha,
                                 staleness_window_seconds=args.window_seconds)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
