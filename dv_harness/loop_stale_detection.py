"""dv_harness/loop_stale_detection.py -- Section 97: STALE is a defined
`LoopState` vocabulary value with legal transitions but, until this module,
no real detector produced it (`loop_contract.py`'s own disclosed residual,
CLAUDE.md's "Loop Persistence / Resume / Stale Detection" section for the
full history).

WHAT WAS ACTUALLY MISSING, re-verified before this file was written. A
repo-wide grep for `STALE`/`stale` found the WORD everywhere `LoopState.STALE`
is named (the enum member, `LEGAL_LOOP_TRANSITIONS`'s five real edges into it,
`RESUMABLE_LOOP_STATES`) and nowhere a real DECISION about it: `derive_loop_
state()` had no `stale` input at all, and `loop_telemetry.LOOP_STATE_WITHOUT_
EVENT_REASON[LoopState.STALE.value]` said outright "Section 97's stale
detection... has no producer in this harness." So a resumed loop session could
sit on a `git_sha` from three real commits ago, or on a `last_transition`
timestamp from a week-old run, and `derive_loop_state()` would report it
CONVERGING/READY/RUNNING/STOPPED exactly as if it had just happened -- the same
kind of unearned-freshness claim `golden_scenario.py`'s own capsule freshness
check exists to prevent one level down (one test's PASS, not a whole loop
session).

WHAT THIS MODULE IS. Two real, independently-checkable signals, reusing this
harness's OWN existing evidence producers rather than inventing a third:

  * TIME-BASED staleness -- this loop session's last REAL event (read from
    `.dv-harness/events.jsonl` via `loop_telemetry.read_loop_telemetry()` when
    a `run_id` is supplied, else the project's own `state.json` `last_
    transition`/per-stage `started_at`/`finished_at` timestamps -- the SAME
    "just transitioned" record `dashboard.py`'s own Last-Transition banner
    reads) is older than a DECLARED staleness window
    (`policy.loop_stale_after_seconds` in `config.json`, or this module's own
    documented `DEFAULT_STALE_AFTER_SECONDS` when a project has not declared
    one -- never a number invented FOR this specific project).
  * ENVIRONMENT-MOVED staleness -- the project's own RECORDED `state.json`
    `git_sha` no longer matches its real current git HEAD, by a REAL
    `git diff --name-only` computed through `change_impact.changed_files()`
    (the exact function `golden_scenario.evaluate_freshness()` and
    `signoff_export.evaluate_freeze_invalidation()` already reuse for the
    identical "did the design move" question one layer down), classified
    through the SAME `change_impact.classify_risk()` HIGH/MEDIUM/LOW ladder
    those two callers already use -- a LOW-risk-only diff (docs, `.dv-harness`/
    `.claude` bookkeeping) does not call the session stale; a HIGH/MEDIUM one
    does.

Both signals are worst-wins with the Evidence Truth Rule's own "an unresolved
UNKNOWN is never silently read as clean" discipline: STALE from either signal
outranks everything; absent that, an UNKNOWN signal (no git, no recorded SHA,
no real event evidence at all) outranks a clean NOT_STALE, because "we could
not check" must never be presented as "we checked and it is fine".

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

  * It does not decide anything on its own. `detect_loop_staleness()` is a
    pure READ over real, already-persisted evidence -- no build, no job, no
    approval, and no stage gate references it.
  * It does not mint a project's `.dv-harness/` tree. Both `state.json` and
    `config.json` are read with a plain, tolerant `json.loads()` (never
    `storage.StateStore.load()`/`config.load_config()`, both of which CREATE
    those files for a project that has never run -- the same reasoning
    `golden_flow_readiness.py`/`signoff_export.read_signoff_stage_status()`
    already record for themselves). A bare project with no `.dv-harness/` at
    all reports honest `UNKNOWN` signals, and nothing is written to disk.
  * It does not invent a staleness window "for this project" -- an
    undeclared window falls back to a real, documented, project-neutral
    default (`DEFAULT_STALE_AFTER_SECONDS`), and the report always names
    which one applied and where it came from.
  * It emits no section-108 event. Section 108's nineteen names are a fixed,
    closed vocabulary `loop_telemetry.emit()` refuses to widen; this module's
    report reaches `derive_loop_state()`'s `stale` parameter directly, as a
    fact, exactly the way `loop_convergence.classify_loop_convergence()`'s
    report already reaches its `plateau`/`progress_oscillating` parameters.

WIRING. `loop_contract.derive_loop_state()` gained a `stale: bool = False`
keyword; `loop_contract.observe_verification_closure_loop()` gained a
`staleness: Optional[dict] = None` keyword (this module's own report) and
`loop_contract.observe_all()` computes one best-effort (never crashing the
caller) and passes it through. The override is scoped to exactly the five
`LoopState`s section 86's own `LEGAL_LOOP_TRANSITIONS` allows a STALE edge
FROM (READY/RUNNING/VERIFYING/CONVERGING/STOPPED -- see `loop_contract.
STALE_ELIGIBLE_BASE_STATES`, derived from that table rather than hand-typed a
second time) and is checked LAST, after every other real finding
(TAKEOVER/PAUSE/BUDGET_EXHAUSTED/oscillation/plateau/loop_done), so staleness
can never re-route or hide a genuine human-control or budget/convergence
finding -- it only ever narrows "the loop looks idle/ready/converging/stopped"
into the more specific, more useful "...and its evidence predates a real
change since then."
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .loop_contract import LoopState

#: This module's own three-value status vocabulary. `STALE` is deliberately
#: the SAME literal as `LoopState.STALE.value` -- a disclosed reuse of the
#: exact section-86 name this module exists to produce evidence for, never a
#: second, differently-spelled vocabulary for the identical fact. Neither
#: `STALE` nor its two siblings collides with any `models.Status` member
#: (`Status` has no `STALE`/`NOT_STALE`/`UNKNOWN` value at all).
STALE = LoopState.STALE.value
NOT_STALE = "NOT_STALE"
UNKNOWN = "UNKNOWN"
STALENESS_STATUSES: Tuple[str, ...] = (STALE, NOT_STALE, UNKNOWN)

#: The two real, independently-computed signals this module folds together.
SIGNAL_TIME_BASED = "TIME_BASED"
SIGNAL_ENVIRONMENT_MOVED = "ENVIRONMENT_MOVED"

#: The project-neutral default staleness window: a loop session with no real
#: event in a full day is treated as dormant unless a project declares its
#: own `policy.loop_stale_after_seconds`. Chosen for the same reason
#: `regression_reporter.DEFAULT_INTERVAL_MINUTES` documents its own default --
#: a real, stated project decision, not a guess about any one project's real
#: cadence, and always reported alongside the report so it is never mistaken
#: for a measured fact.
DEFAULT_STALE_AFTER_SECONDS = 24 * 60 * 60


def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """A plain, tolerant JSON read that mints nothing. Returns None for an
    absent, unreadable, or non-object file -- never raises, and never creates
    the file the way `storage.StateStore.load()`/`config.load_config()`
    would."""
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse one `engine.now()`-shaped ISO-8601 UTC timestamp. Returns None
    for anything this cannot honestly parse -- never a guessed time."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def declared_stale_window_seconds(root: Path,
                                  cfg: Optional[Dict[str, Any]] = None
                                  ) -> Tuple[float, str]:
    """(seconds, source). Reads a real `config.json`'s own
    `policy.loop_stale_after_seconds` when a project has declared one;
    `DEFAULT_STALE_AFTER_SECONDS` otherwise -- and says which applied, so a
    caller can never mistake the default for a project-specific measurement."""
    root = Path(root)
    if cfg is None:
        cfg = _read_json_file(root / ".dv-harness" / "config.json")
    policy = (cfg or {}).get("policy") or {}
    declared = policy.get("loop_stale_after_seconds")
    if isinstance(declared, (int, float)) and not isinstance(declared, bool) and declared > 0:
        return float(declared), "config.json policy.loop_stale_after_seconds"
    return (float(DEFAULT_STALE_AFTER_SECONDS),
            "DEFAULT_STALE_AFTER_SECONDS (this project has not declared "
            "policy.loop_stale_after_seconds)")


@dataclass
class LastEventEvidence:
    """The real timestamp `detect_time_based_staleness()` measured staleness
    against, and where it came from -- so a caller can go check it."""
    timestamp: Optional[str]
    source: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def last_real_event(root: Path, *, run_id: Optional[str] = None) -> LastEventEvidence:
    """The most specific real evidence of "when did this loop session last do
    something" this harness has:

      1. `run_id` given -- that session's own `last_event_at` out of
         `loop_telemetry.read_loop_telemetry()`, the real fold over section-108
         events for exactly that session.
      2. Otherwise (or (1) found nothing) -- `state.json`'s own real
         `last_transition.at`, the "just transitioned" record `engine.
         run_stage()` already writes every time a stage reaches a terminal
         status.
      3. Otherwise -- the latest `started_at`/`finished_at` across every
         per-stage record in `state.json`'s `stages` dict.
      4. Otherwise -- no real event evidence exists for this project at all.

    Never raises; a read failure at any step falls through to the next real
    source rather than crashing the caller."""
    root = Path(root)
    if run_id:
        try:
            from .loop_telemetry import read_loop_telemetry
            payload = read_loop_telemetry(root, run_id=run_id)
            row = next((r for r in (payload.get("rows") or [])
                       if r.get("run_id") == run_id), None)
            last_at = (row or {}).get("last_event_at")
            if last_at:
                return LastEventEvidence(
                    timestamp=last_at, source="loop_telemetry_session",
                    detail={"run_id": run_id, "state": (row or {}).get("state")})
        except Exception:
            pass

    state = _read_json_file(root / ".dv-harness" / "state.json")
    if isinstance(state, dict):
        lt = state.get("last_transition")
        if isinstance(lt, dict) and lt.get("at"):
            return LastEventEvidence(
                timestamp=lt.get("at"), source="state_last_transition",
                detail={"stage": lt.get("stage"), "status": lt.get("status")})
        stamps: List[Tuple[str, str, str]] = []
        stages = state.get("stages") or {}
        if isinstance(stages, dict):
            for sid, rec in stages.items():
                if not isinstance(rec, dict):
                    continue
                for key in ("finished_at", "started_at"):
                    v = rec.get(key)
                    if isinstance(v, str) and v:
                        stamps.append((v, str(sid), key))
        if stamps:
            stamps.sort(key=lambda t: t[0])
            v, sid, key = stamps[-1]
            return LastEventEvidence(
                timestamp=v, source="stage_state_timestamp",
                detail={"stage": sid, "field": key})

    return LastEventEvidence(
        timestamp=None, source="NO_REAL_EVENT_EVIDENCE",
        detail={"checked": ["loop_telemetry_session" if run_id else None,
                            "state.json last_transition",
                            "state.json stages[*].finished_at/started_at"]})


def detect_time_based_staleness(root: Path, cfg: Optional[Dict[str, Any]] = None, *,
                                run_id: Optional[str] = None,
                                staleness_window_seconds: Optional[float] = None,
                                now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """One signal: is this session's last REAL event older than the declared
    window. `UNKNOWN` (never a guessed NOT_STALE) when this harness has no
    real event evidence to measure age from at all."""
    root = Path(root)
    now_dt = now_dt or datetime.now(timezone.utc)
    if staleness_window_seconds is not None:
        window, window_source = float(staleness_window_seconds), "caller-supplied"
    else:
        window, window_source = declared_stale_window_seconds(root, cfg)

    ev = last_real_event(root, run_id=run_id)
    ts = _parse_ts(ev.timestamp)
    base = {"signal": SIGNAL_TIME_BASED, "window_seconds": window,
            "window_source": window_source, "last_event": ev.to_dict()}
    if ts is None:
        base.update(status=UNKNOWN,
                    reason=f"NO_REAL_EVENT_EVIDENCE: {ev.source} named no timestamp "
                            f"to measure staleness against")
        return base

    age_seconds = (now_dt - ts).total_seconds()
    base["age_seconds"] = age_seconds
    if age_seconds > window:
        base.update(status=STALE,
                    reason=(f"last real event ({ev.source}) at {ev.timestamp} is "
                            f"{age_seconds:.0f}s old, exceeding the declared "
                            f"{window:.0f}s staleness window ({window_source})"))
    else:
        base.update(status=NOT_STALE,
                    reason=(f"last real event ({ev.source}) at {ev.timestamp} is "
                            f"{age_seconds:.0f}s old, within the {window:.0f}s window "
                            f"({window_source})"))
    return base


def detect_environment_moved_staleness(root: Path, *,
                                       recorded_sha: Optional[str] = None,
                                       head_sha: str = "HEAD") -> Dict[str, Any]:
    """One signal: has the project's real source moved (a real, HIGH/MEDIUM-
    risk git diff) since the `git_sha` this loop session's `state.json` last
    recorded. `UNKNOWN` (never a guessed NOT_STALE) with no recorded SHA to
    diff against, or when the real diff itself could not be computed
    (`change_impact.changed_files()`'s own NO_GIT/UNKNOWN_BASE/UNKNOWN_HEAD/
    DIFF_FAILED statuses, propagated rather than swallowed)."""
    root = Path(root)
    if recorded_sha is None:
        state = _read_json_file(root / ".dv-harness" / "state.json")
        recorded_sha = (state or {}).get("git_sha")
    if not recorded_sha:
        return {"signal": SIGNAL_ENVIRONMENT_MOVED, "status": UNKNOWN,
                "reason": "NO_RECORDED_SHA: state.json carries no git_sha to compare "
                          "against this project's current HEAD"}

    from .change_impact import changed_files, classify_risk
    diff = changed_files(root, recorded_sha, head_sha)
    base = {"signal": SIGNAL_ENVIRONMENT_MOVED, "recorded_sha": recorded_sha,
            "head_sha": head_sha, "diff_status": diff.get("status")}
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


def detect_loop_staleness(root: Path, cfg: Optional[Dict[str, Any]] = None, *,
                          run_id: Optional[str] = None,
                          staleness_window_seconds: Optional[float] = None,
                          recorded_sha: Optional[str] = None,
                          head_sha: str = "HEAD",
                          now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """The combined verdict, worst-wins: STALE if either real signal fired,
    else UNKNOWN if either could not be checked (never silently read as
    clean), else NOT_STALE. Every signal's own report is carried in full, so
    a caller (or a human) can see exactly which one decided the verdict."""
    root = Path(root)
    time_signal = detect_time_based_staleness(
        root, cfg, run_id=run_id, staleness_window_seconds=staleness_window_seconds,
        now_dt=now_dt)
    env_signal = detect_environment_moved_staleness(
        root, recorded_sha=recorded_sha, head_sha=head_sha)
    signals = [time_signal, env_signal]

    if any(s.get("status") == STALE for s in signals):
        status = STALE
    elif any(s.get("status") == UNKNOWN for s in signals):
        status = UNKNOWN
    else:
        status = NOT_STALE

    return {
        "root": str(root),
        "run_id": run_id,
        "status": status,
        "is_stale": status == STALE,
        "signals": signals,
    }


# --------------------------------------------------------------------------
# Front door
# --------------------------------------------------------------------------
def execute_verb(root: Path, verb: str, *,
                 cfg: Optional[Dict[str, Any]] = None,
                 run_id: Optional[str] = None,
                 staleness_window_seconds: Optional[float] = None) -> Tuple[int, Any]:
    """One implementation behind `python -m dv_harness.loop_stale_detection`,
    the same shared-`execute_verb()` convention `loop_contract`/`loop_budget`/
    `loop_telemetry` already follow."""
    root = Path(root)
    if verb == "window":
        seconds, source = declared_stale_window_seconds(root, cfg)
        return 0, {"window_seconds": seconds, "window_source": source}
    if verb == "detect":
        report = detect_loop_staleness(
            root, cfg, run_id=run_id, staleness_window_seconds=staleness_window_seconds)
        exit_code = {STALE: 1, NOT_STALE: 0, UNKNOWN: 2}[report["status"]]
        return exit_code, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["window", "detect"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.loop_stale_detection",
        description="Section 97: is a loop session's evidence still fresh, real detection.")
    ap.add_argument("verb", choices=["window", "detect"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--window-seconds", type=float, default=None)
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 run_id=args.run_id,
                                 staleness_window_seconds=args.window_seconds)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
