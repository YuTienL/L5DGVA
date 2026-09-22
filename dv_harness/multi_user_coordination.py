"""Multi-user coordination CONFLICT DETECTION (spec section 239).

WHAT WAS ALREADY REAL, AND WHAT WAS NOT
---------------------------------------
Re-verified by direct search on 2026-09-06 before any of this was written.

Section 239 ("MULTI-USER COLLABORATION") lists ownership, authorized role,
stale SHA detection, edit conflict, duplicate regression, shared-resource
reservation, conflicting Human Gates, simultaneous memory promotion and
simultaneous capability changes, and closes with two rules: "Do not use chat
history as the coordination mechanism" and "Concurrency conflicts remain
explicit."

The TRANSPORT and AUTHORIZATION half of that list is real and is NOT touched
here:
  * `docs/workflow/USAGE_MULTI_USER_SAFETY.md` is the standing policy for the shared
    `/home/svcacct/AI/Agent` deployment, including its "never share a
    `--project-root`" rule -- which is precisely WHY detection has to be a
    cross-ROOT comparison: each user has their own `.dv-harness/`, so no single
    root can see a second user at all.
  * `dashboard_auth.py` (GUI-19) is the real token gate on the dashboard's
    mutating verbs.
  * `user_info.summarize_user_access()` already answers "who has used THIS
    project root, and when" off the real `CLI_ACCESS`/`GUI_ACCESS` events in
    `.dv-harness/events.jsonl`.
  * `tools/remote/remote_relay.py`'s `handle_request()` lock serializes command
    execution on one shared relay.

The DETECTION half was NEVER BUILT. A repo-wide grep for `stale_sha` /
`duplicate_regression` / `edit_conflict` / `reservation_conflict` /
`cross_session` / `peer_session` / `coordination_conflict` over `dv_harness/`
and `tools/` returned only an unrelated subsystem-registry `release_sha` test
fixture. Nothing anywhere compared TWO users' concurrent work. The consequence
is exactly what section 239 forbids: two people's only way to discover that
they were rebuilding the same regression against different SHAs, or both
driving the same VIP instance, was to tell each other in chat.

THREE DETECTORS, EACH OVER STATE THAT ALREADY EXISTS
----------------------------------------------------
No new coordination store is introduced. Every fact below is read off a real
per-project artifact some existing mechanism already writes:

  (a) STALE_SHA_CONFLICT -- two sessions whose in-flight work is based on
      DIFFERENT git SHAs and whose changed-file sets INTERSECT. Both halves come
      from `change_impact.read_computed_selection()`
      (`.dv-harness/regression/computed_selection.json`), which is a real
      `git diff --name-only <base>..<head>` written by the REGRESSION_SELECT
      stage -- not a claim a user typed. Severity is
      `change_impact.classify_risk()` over the overlapping files, so "how much
      does this file matter" has ONE answer in this codebase.

  (b) DUPLICATE_REGRESSION_SUBMISSION -- two sessions about to burn farm time on
      the same pattern against the same commit. SUBMITTED claims come from the
      real `lsf_client.JobState` records in `.dv-harness/lsf/jobs/*.json`
      (`pattern` + `git_sha`, in-flight = LSF `PEND`/`RUN`); PLANNED claims come
      from the same `computed_selection.json`'s selected test sets against its
      `head_sha`. A submitted-vs-planned pair is HIGH (one user is about to
      re-run what is already running); planned-vs-planned is MEDIUM (nothing is
      burning yet).

  (c) SHARED_RESOURCE_RESERVATION_CONFLICT -- two sessions holding a WRITE claim
      on the same genuinely-shared resource. The claim ledger is the EXISTING
      `AgentTaskStore.acquire()` mechanism engine.py already uses for
      parallel_group fan-out, extended with a `scope` (see multi_agent.py's own
      SCOPE_LOCAL/SCOPE_SHARED comment for why the scope had to be recorded
      rather than inferred: fan-out topic names are identical in every project
      and would collide between any two sessions).

WHAT THIS MODULE IS NOT
-----------------------
  * It is NOT a lock and NOT an arbiter. Detection is what was wired;
    ARBITRATION is untouched. A conflict is REPORTED, with both sides' evidence
    and who claimed first, for two humans to resolve. Nothing here kills a job,
    revokes a reservation, rewrites another user's state, picks a winner, or
    decides whose SHA is authoritative.
  * It is NOT a gate. There is deliberately no `STAGE_GATES` entry: a gate that
    passed because a scan could not see the other user's project root would be
    worse than no gate. Every existing human-approval gate stands exactly as
    before.
  * It is NOT an auth layer. It never reads a token, never authorizes anything,
    and takes user identity as an input (declared, or read off the peer root's
    own real access trail).
  * It is NOT a new store. It writes exactly one thing: a
    `MULTI_USER_COORDINATION_SCAN` event into the SCANNING project's own
    `.dv-harness/events.jsonl`, through the same `StateStore.event()` every
    other audited action uses.

"We could not check" is UNKNOWN with a real reason, never CLEAR.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import change_impact
from . import multi_agent
from .multi_agent import MODE_WRITE, SCOPE_SHARED

SCHEMA_VERSION = "1.0"

#: The one events.jsonl event name this module writes.
EVENT_NAME = "MULTI_USER_COORDINATION_SCAN"

CONFLICT_STALE_SHA = "STALE_SHA_CONFLICT"
CONFLICT_DUPLICATE_REGRESSION = "DUPLICATE_REGRESSION_SUBMISSION"
CONFLICT_SHARED_RESOURCE = "SHARED_RESOURCE_RESERVATION_CONFLICT"

CONFLICT_KINDS = (CONFLICT_STALE_SHA, CONFLICT_DUPLICATE_REGRESSION,
                  CONFLICT_SHARED_RESOURCE)

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
_SEVERITY_ORDER = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}

STATUS_CLEAR = "CLEAR"
STATUS_CONFLICTS = "CONFLICTS_DETECTED"
STATUS_UNKNOWN = "UNKNOWN"

#: LSF statuses that mean the job is still consuming (or queued to consume) farm
#: capacity. Terminal ones (`DONE`/`EXIT`/`KILLED`) are finished work: two users
#: having both run pattern X against commit Y last week is history, not a
#: collision. `UNKNOWN` is neither -- it becomes an UNKNOWN finding, never a
#: silent "not in flight".
IN_FLIGHT_LSF_STATUSES = ("PEND", "RUN")
TERMINAL_LSF_STATUSES = ("DONE", "EXIT", "KILLED")

STAGE_SUBMITTED = "SUBMITTED"
STAGE_PLANNED = "PLANNED"

#: The four selected-test sets `change_impact.select_regression()` produces. All
#: four are real submissions-to-be, so all four count as PLANNED claims.
_SELECTION_TEST_KEYS = ("targeted_tests", "dependency_tests", "safety_tests",
                        "mandatory_signoff_tests")


class CoordinationError(ValueError):
    """A coordination scan was asked for something it cannot honestly do."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- session snapshots -----------------------------------------------------


@dataclass
class SessionSnapshot:
    """One user's in-flight work, read off THEIR project root.

    Every field is either read from a real artifact or left None/empty with a
    matching entry in `unknowns` -- there is no default that reads as "clean".
    """
    session_id: str
    project_root: str
    user: Optional[str] = None
    user_source: str = "UNKNOWN"
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    state_git_sha: Optional[str] = None
    changed_files: List[str] = field(default_factory=list)
    planned_patterns: List[str] = field(default_factory=list)
    jobs: List[Dict[str, Any]] = field(default_factory=list)
    reservations: List[Dict[str, Any]] = field(default_factory=list)
    unknowns: List[Dict[str, str]] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def note_unknown(self, reason: str, detail: str) -> None:
        self.unknowns.append({"reason": reason, "detail": detail})


def _read_state_git_sha(root: Path) -> Tuple[Optional[str], Optional[str]]:
    """(git_sha, unknown_reason). Read straight off state.json rather than
    through StateStore.load(), which CREATES a state.json when none exists --
    a scan must never write into a peer's project root."""
    p = root / ".dv-harness" / "state.json"
    if not p.exists():
        return None, "NO_STATE_JSON"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - corrupt file
        return None, f"STATE_JSON_UNREADABLE: {type(e).__name__}"
    if not isinstance(data, dict):
        return None, "STATE_JSON_NOT_AN_OBJECT"
    return data.get("git_sha"), None


def _derive_user(root: Path) -> Tuple[Optional[str], str]:
    """Who really drove this project root, read off the SAME access trail
    `dv-harness user-access`/the dashboard already surface -- never guessed
    from a path or an environment variable of the SCANNING process (which
    would label every peer session with the scanner's own account)."""
    try:
        from .user_info import summarize_user_access
        summary = summarize_user_access(root)
    except Exception:  # pragma: no cover - defensive
        return None, "UNKNOWN"
    users = summary.get("users") or []
    if not users:
        return None, "UNKNOWN"
    # summarize_user_access() sorts by last_seen descending.
    return users[0].get("user"), "EVENTS_ACCESS_TRAIL"


def _collect_jobs(root: Path, snap: SessionSnapshot) -> None:
    jobs_dir = root / ".dv-harness" / "lsf" / "jobs"
    if not jobs_dir.is_dir():
        return
    from .lsf_client import load_job_state
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            jid = int(path.stem)
        except ValueError:
            continue
        try:
            st = load_job_state(root, jid)
        except Exception as e:  # pragma: no cover - corrupt record
            snap.note_unknown("JOB_RECORD_UNREADABLE", f"{path}: {type(e).__name__}")
            continue
        row = {
            "job_id": st.job_id, "pattern": st.pattern,
            "regression_id": st.regression_id, "seed": st.seed,
            "git_sha": st.git_sha, "lsf_status": st.lsf_status,
            "source": str(path),
        }
        snap.jobs.append(row)
        if st.lsf_status in IN_FLIGHT_LSF_STATUSES:
            if not st.pattern:
                snap.note_unknown("IN_FLIGHT_JOB_HAS_NO_PATTERN",
                                  f"job {st.job_id} ({st.lsf_status}) records no pattern")
            elif not st.git_sha:
                snap.note_unknown("IN_FLIGHT_JOB_HAS_NO_SHA",
                                  f"job {st.job_id} pattern={st.pattern} records no git_sha")
        elif st.lsf_status not in TERMINAL_LSF_STATUSES:
            snap.note_unknown(
                "JOB_STATUS_UNKNOWN",
                f"job {st.job_id} lsf_status={st.lsf_status!r} -- cannot tell whether it is "
                "in flight")
    if snap.jobs:
        snap.evidence.append(str(jobs_dir))


def collect_session_snapshot(root, *, session_id: Optional[str] = None,
                              user: Optional[str] = None) -> SessionSnapshot:
    """Read ONE user's project root into a comparable snapshot. Read-only: it
    creates no file and no directory anywhere under `root`."""
    root = Path(root)
    snap = SessionSnapshot(session_id=session_id or root.name, project_root=str(root))

    if not (root / ".dv-harness").is_dir():
        snap.note_unknown("NO_HARNESS_STATE",
                          f"{root} has no .dv-harness/ -- nothing to compare")
        snap.user, snap.user_source = (user, "DECLARED") if user else (None, "UNKNOWN")
        return snap

    if user:
        snap.user, snap.user_source = user, "DECLARED"
    else:
        snap.user, snap.user_source = _derive_user(root)
        if not snap.user:
            snap.note_unknown(
                "USER_IDENTITY_UNKNOWN",
                f"{root} has no CLI_ACCESS/GUI_ACCESS event carrying a user -- pass the "
                "user explicitly")

    sha, reason = _read_state_git_sha(root)
    snap.state_git_sha = sha
    if reason:
        snap.note_unknown(reason, str(root / ".dv-harness" / "state.json"))

    selection = change_impact.read_computed_selection(root)
    if selection is None:
        snap.note_unknown(
            "NO_CHANGE_IMPACT_COMPUTATION",
            f"{root} has no {'/'.join(change_impact.COMPUTED_SELECTION_PARTS)} -- this "
            "session's touched-file set and planned regression are both unknown")
    else:
        snap.base_sha = selection.get("base_sha")
        snap.head_sha = selection.get("head_sha")
        snap.changed_files = sorted(
            str(f) for f in (selection.get("changed_files") or []))
        sel = selection.get("selection") or {}
        planned = set()
        for key in _SELECTION_TEST_KEYS:
            planned.update(str(t) for t in (sel.get(key) or []))
        snap.planned_patterns = sorted(planned)
        snap.evidence.append(str(change_impact.computed_selection_path(root)))
        if not snap.base_sha:
            snap.note_unknown("SELECTION_HAS_NO_BASE_SHA",
                              "computed_selection.json records no base_sha")
        if not snap.changed_files:
            snap.note_unknown(
                "SELECTION_HAS_NO_CHANGED_FILES",
                f"computed_selection.json diff_status={selection.get('diff_status')!r} "
                "lists no changed files")

    _collect_jobs(root, snap)

    snap.reservations = multi_agent.read_reservations(root, scope=SCOPE_SHARED)
    if snap.reservations:
        snap.evidence.append(str(multi_agent.ownership_path(root)))
    return snap


# --- detectors -------------------------------------------------------------


def _conflict(kind: str, severity: str, sessions: Sequence[SessionSnapshot],
              summary: str, detail: Dict[str, Any],
              next_best_action: str) -> Dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "sessions": [s.session_id for s in sessions],
        "users": [s.user for s in sessions],
        "project_roots": [s.project_root for s in sessions],
        "summary": summary,
        "detail": detail,
        "evidence": sorted({e for s in sessions for e in s.evidence}),
        # Section 239's "concurrency conflicts remain explicit" + section 240's
        # notification package. This NAMES a decision for two humans; it never
        # takes one.
        "next_best_action": next_best_action,
        "arbitration": "NOT_PERFORMED -- detection only; a human decides",
    }


def detect_stale_sha_conflict(a: SessionSnapshot,
                              b: SessionSnapshot) -> List[Dict[str, Any]]:
    """(a) Two users' in-flight work based on DIFFERENT git SHAs while touching
    the same file. Same base SHA is not a stale-SHA conflict (both are working
    from the same baseline); a missing base SHA on either side is UNKNOWN, which
    `detect_conflicts()` reports separately rather than treating as clear."""
    if not a.base_sha or not b.base_sha:
        return []
    if a.base_sha == b.base_sha:
        return []
    overlap = sorted(set(a.changed_files) & set(b.changed_files))
    if not overlap:
        return []
    risks = {f: change_impact.classify_risk(f) for f in overlap}
    if change_impact.RISK_HIGH in risks.values():
        severity = SEVERITY_HIGH
    elif change_impact.RISK_MEDIUM in risks.values():
        severity = SEVERITY_MEDIUM
    else:
        severity = SEVERITY_LOW
    return [_conflict(
        CONFLICT_STALE_SHA, severity, (a, b),
        f"{a.session_id} (base {a.base_sha}) and {b.session_id} (base {b.base_sha}) are "
        f"both working on {len(overlap)} shared file(s) from different baselines",
        {
            "base_shas": {a.session_id: a.base_sha, b.session_id: b.base_sha},
            "head_shas": {a.session_id: a.head_sha, b.session_id: b.head_sha},
            "overlapping_files": overlap,
            "file_risk": risks,
            "max_risk": max(risks.values(), key=lambda r: {"HIGH": 0, "MEDIUM": 1}.get(r, 2)),
        },
        "Reconcile the two baselines before either result is trusted: rebase one session "
        "onto the other's base SHA, or agree an owner per file. Neither result is "
        "invalidated by this detection -- CLAUDE.md's 'same regression batch must use the "
        "same source/build/config identity' rule is what makes the divergence matter.")]


def _pattern_claims(snap: SessionSnapshot) -> List[Dict[str, Any]]:
    """This session's (pattern, sha) claims -- submitted first, then planned."""
    claims: List[Dict[str, Any]] = []
    for job in snap.jobs:
        if job.get("lsf_status") not in IN_FLIGHT_LSF_STATUSES:
            continue
        if not job.get("pattern") or not job.get("git_sha"):
            continue
        claims.append({"pattern": job["pattern"], "sha": job["git_sha"],
                       "stage": STAGE_SUBMITTED, "job_id": job.get("job_id"),
                       "lsf_status": job.get("lsf_status"), "seed": job.get("seed"),
                       "regression_id": job.get("regression_id")})
    if snap.head_sha:
        for pattern in snap.planned_patterns:
            claims.append({"pattern": pattern, "sha": snap.head_sha,
                           "stage": STAGE_PLANNED, "job_id": None,
                           "lsf_status": None, "seed": None, "regression_id": None})
    return claims


def detect_duplicate_regression(a: SessionSnapshot,
                                b: SessionSnapshot) -> List[Dict[str, Any]]:
    """(b) Two users about to submit -- or already running -- the same pattern
    against the SAME commit. Different commits are two legitimately different
    runs and are never reported."""
    claims_a = _pattern_claims(a)
    claims_b = _pattern_claims(b)
    if not claims_a or not claims_b:
        return []
    index_b: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for c in claims_b:
        index_b.setdefault((c["pattern"], c["sha"]), []).append(c)

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for ca in claims_a:
        key = (ca["pattern"], ca["sha"])
        for cb in index_b.get(key, []):
            dedup = (key, ca["stage"], cb["stage"], ca.get("job_id"), cb.get("job_id"))
            if dedup in seen:
                continue
            seen.add(dedup)
            both_planned = ca["stage"] == STAGE_PLANNED and cb["stage"] == STAGE_PLANNED
            severity = SEVERITY_MEDIUM if both_planned else SEVERITY_HIGH
            out.append(_conflict(
                CONFLICT_DUPLICATE_REGRESSION, severity, (a, b),
                f"pattern {ca['pattern']!r} against commit {ca['sha']} is claimed by both "
                f"{a.session_id} ({ca['stage']}) and {b.session_id} ({cb['stage']})",
                {
                    "pattern": ca["pattern"],
                    "commit": ca["sha"],
                    "claims": {a.session_id: ca, b.session_id: cb},
                },
                "Agree one owner for this pattern/commit before submitting: a second "
                "identical submission burns farm time and license seats for a result the "
                "first run already produces. Nothing was cancelled by this detection."))
    return out


def detect_shared_resource_conflict(a: SessionSnapshot,
                                    b: SessionSnapshot) -> List[Dict[str, Any]]:
    """(c) Two users holding a claim on the same genuinely-shared resource. Two
    READ claims are not a conflict; any WRITE claim against another claim is."""
    if not a.reservations or not b.reservations:
        return []
    index_b: Dict[Tuple[Optional[str], str], List[Dict[str, Any]]] = {}
    for r in b.reservations:
        index_b.setdefault((r.get("kind"), r["resource"]), []).append(r)

    out: List[Dict[str, Any]] = []
    for ra in a.reservations:
        key = (ra.get("kind"), ra["resource"])
        for rb in index_b.get(key, []):
            if ra.get("mode") != MODE_WRITE and rb.get("mode") != MODE_WRITE:
                continue
            stamps = {a.session_id: ra.get("claimed_at"), b.session_id: rb.get("claimed_at")}
            known = {k: v for k, v in stamps.items() if isinstance(v, (int, float))}
            first = min(known, key=known.get) if len(known) == 2 else None
            out.append(_conflict(
                CONFLICT_SHARED_RESOURCE, SEVERITY_HIGH, (a, b),
                f"{key[0]} {ra['resource']!r} is claimed by both {a.session_id} "
                f"({ra.get('mode')}) and {b.session_id} ({rb.get('mode')})",
                {
                    "resource": ra["resource"],
                    "kind": ra.get("kind"),
                    "claims": {a.session_id: ra, b.session_id: rb},
                    "claimed_at": stamps,
                    "claimed_first": first,
                    "claimed_first_basis": ("CLAIM_TIMESTAMP" if first
                                            else "UNKNOWN_ONE_CLAIM_HAS_NO_TIMESTAMP"),
                },
                "Decide which session keeps the resource, then have the other release it "
                "with `dv-harness coord release`. This report does not revoke either "
                "claim -- 'claimed_first' is stated as information for that decision, not "
                "applied as a rule."))
    return out


_DETECTORS = (
    (CONFLICT_STALE_SHA, detect_stale_sha_conflict),
    (CONFLICT_DUPLICATE_REGRESSION, detect_duplicate_regression),
    (CONFLICT_SHARED_RESOURCE, detect_shared_resource_conflict),
)


# --- top level -------------------------------------------------------------


def detect_conflicts(snapshots: Sequence[SessionSnapshot]) -> Dict[str, Any]:
    """Compare every pair of DISTINCT-user sessions. Two snapshots recorded for
    the SAME user are that one person's own two working copies, not a
    multi-user conflict, and are skipped with an explicit note -- but a session
    whose user could not be identified is never quietly assumed to be someone
    else, it is compared AND reported as an unknown-identity comparison."""
    snapshots = list(snapshots)
    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analyzed_at": _now_iso(),
        "session_count": len(snapshots),
        "sessions": [s.to_dict() for s in snapshots],
        "conflicts": [],
        "skipped_pairs": [],
        "unknowns": [],
        "counts": {k: 0 for k in CONFLICT_KINDS},
        "status": STATUS_UNKNOWN,
    }
    for snap in snapshots:
        for u in snap.unknowns:
            report["unknowns"].append(dict(u, session=snap.session_id))

    if len(snapshots) < 2:
        report["status"] = STATUS_UNKNOWN
        report["unknowns"].append({
            "session": None, "reason": "INSUFFICIENT_SESSIONS",
            "detail": f"{len(snapshots)} session(s) supplied -- coordination detection "
                      "compares two or more concurrent sessions"})
        return report

    for i in range(len(snapshots)):
        for j in range(i + 1, len(snapshots)):
            a, b = snapshots[i], snapshots[j]
            if a.user and b.user and a.user == b.user:
                report["skipped_pairs"].append({
                    "sessions": [a.session_id, b.session_id],
                    "reason": "SAME_USER",
                    "detail": f"both roots are driven by {a.user!r}"})
                continue
            if not a.user or not b.user:
                report["unknowns"].append({
                    "session": None, "reason": "PAIR_USER_IDENTITY_UNKNOWN",
                    "detail": f"{a.session_id}(user={a.user!r}) vs "
                              f"{b.session_id}(user={b.user!r}) -- compared anyway; a "
                              "reported conflict may be one person's own two roots"})
            for kind, fn in _DETECTORS:
                for c in fn(a, b):
                    report["conflicts"].append(c)
                    report["counts"][kind] += 1

    report["conflicts"].sort(
        key=lambda c: (_SEVERITY_ORDER.get(c["severity"], 9), c["kind"], c["summary"]))
    if report["conflicts"]:
        report["status"] = STATUS_CONFLICTS
    elif report["unknowns"]:
        report["status"] = STATUS_UNKNOWN
    else:
        report["status"] = STATUS_CLEAR
    return report


def scan(session_specs: Sequence[Tuple[Optional[str], str]]) -> Dict[str, Any]:
    """`session_specs` is a sequence of `(user, project_root)` pairs -- `user`
    may be None to read it off that root's own access trail."""
    snaps = []
    for idx, (user, root) in enumerate(session_specs):
        rp = Path(root)
        session_id = f"{user}@{rp.name}" if user else (rp.name or f"session{idx}")
        base_id, n = session_id, 1
        while any(s.session_id == session_id for s in snaps):
            n += 1
            session_id = f"{base_id}#{n}"
        snaps.append(collect_session_snapshot(rp, session_id=session_id, user=user))
    return detect_conflicts(snaps)


def record_scan_event(project_root, report: Dict[str, Any], *, store=None) -> None:
    """One `MULTI_USER_COORDINATION_SCAN` entry in the SCANNING project's real
    `.dv-harness/events.jsonl`, via the same `StateStore.event()` every other
    audited action uses -- never a second parallel audit file, and never a write
    into a PEER's root. A CLEAR scan is recorded too: "we checked and found
    nothing" is itself citable evidence. Best-effort, mirroring
    harness_deploy.record_event()'s convention -- an audit-write failure must
    never turn a completed scan into a crash."""
    try:
        if store is None:
            from .storage import StateStore
            store = StateStore(Path(project_root))
        store.event({
            "ts": _now_iso(),
            "event": EVENT_NAME,
            "status": report.get("status"),
            "session_count": report.get("session_count"),
            "sessions": [s.get("session_id") for s in (report.get("sessions") or [])],
            "counts": report.get("counts"),
            "conflict_summaries": [
                {"kind": c["kind"], "severity": c["severity"], "summary": c["summary"]}
                for c in (report.get("conflicts") or [])],
            "unknown_count": len(report.get("unknowns") or []),
            "user": os.environ.get("USERNAME") or os.environ.get("USER"),
        })
    except Exception:
        pass


# --- rendering + verb ------------------------------------------------------


def format_report(report: Dict[str, Any]) -> str:
    lines = [f"MULTI-USER COORDINATION: {report['status']} "
             f"({report['session_count']} session(s))"]
    for s in report.get("sessions") or []:
        lines.append(f"  session {s['session_id']}  user={s['user']} "
                     f"({s['user_source']})  root={s['project_root']}")
        lines.append(f"    base_sha={s['base_sha']} head_sha={s['head_sha']} "
                     f"changed_files={len(s['changed_files'])} "
                     f"planned_patterns={len(s['planned_patterns'])} "
                     f"jobs={len(s['jobs'])} shared_reservations={len(s['reservations'])}")
    conflicts = report.get("conflicts") or []
    if conflicts:
        lines.append(f"\n{len(conflicts)} conflict(s):")
        for c in conflicts:
            lines.append(f"  [{c['severity']}] {c['kind']}: {c['summary']}")
            lines.append(f"      next-best-action: {c['next_best_action']}")
    else:
        lines.append("\nno conflicts detected between the supplied sessions")
    for p in report.get("skipped_pairs") or []:
        lines.append(f"  skipped {p['sessions']}: {p['reason']} -- {p['detail']}")
    unknowns = report.get("unknowns") or []
    if unknowns:
        lines.append(f"\n{len(unknowns)} UNKNOWN (not a clear result):")
        for u in unknowns:
            lines.append(f"  {u.get('session') or '-'}: {u['reason']} -- {u['detail']}")
    return "\n".join(lines)


def _parse_session_spec(spec: str) -> Tuple[Optional[str], str]:
    """`user=/path/to/root` or a bare `/path/to/root`. Split on the FIRST `=`
    only, and only when the left side is non-empty and contains no path
    separator -- so a Windows path or a path that legitimately contains `=` is
    not silently reinterpreted as a user name."""
    if "=" in spec:
        left, right = spec.split("=", 1)
        if left and not any(sep in left for sep in ("/", "\\", ":")):
            return left, right
    return None, spec


def execute_verb(verb: str, *, root, sessions: Optional[Sequence[str]] = None,
                 resource: Optional[str] = None, kind: Optional[str] = None,
                 agent: Optional[str] = None, task_id: Optional[str] = None,
                 mode: str = MODE_WRITE, as_json: bool = False,
                 record_event: bool = True) -> Tuple[str, int]:
    """Shared implementation for `dv-harness coord <verb>` and
    `python -m dv_harness.multi_user_coordination <verb>`.

    Exit codes: 0 CLEAR / reservation made, 1 CONFLICTS_DETECTED or a refused
    reservation, 2 UNKNOWN or a malformed request. Nothing here runs, builds,
    submits, cancels or approves anything.
    """
    root = Path(root)

    if verb == "reserve":
        if not resource or not kind:
            return ("coord reserve requires --resource <id> and --kind "
                    f"<{'|'.join(multi_agent.SHARED_RESOURCE_KINDS)}>", 2)
        store = multi_agent.AgentTaskStore(root)
        try:
            ok, owner = store.acquire(f"{kind}:{resource}",
                                      task_id or f"COORD-{kind}-{resource}",
                                      agent or "human", scope=SCOPE_SHARED,
                                      kind=kind, mode=mode)
        except multi_agent.ResourceKindError as e:
            return (f"ResourceKindError: {e}", 2)
        payload = {"acquired": ok, "resource": f"{kind}:{resource}", "owner": owner}
        if as_json:
            return json.dumps(payload, indent=2), (0 if ok else 1)
        if ok:
            return (f"reserved {kind}:{resource} for task {owner['task_id']} "
                    f"(agent={owner['agent']}, mode={owner['mode']})"), 0
        return (f"REFUSED: {kind}:{resource} is already claimed in THIS root by task "
                f"{owner.get('task_id')} (agent={owner.get('agent')})"), 1

    if verb == "release":
        if not resource or not kind:
            return "coord release requires --resource <id> and --kind <kind>", 2
        store = multi_agent.AgentTaskStore(root)
        ok, cur = store.release(f"{kind}:{resource}",
                                task_id or f"COORD-{kind}-{resource}")
        payload = {"released": ok, "resource": f"{kind}:{resource}", "record": cur}
        if as_json:
            return json.dumps(payload, indent=2), (0 if ok else 1)
        if ok:
            return f"released {kind}:{resource}", 0
        if cur is None:
            return f"NOT_HELD: {kind}:{resource} is not claimed in this root", 1
        return (f"REFUSED: {kind}:{resource} is held by task {cur.get('task_id')}, "
                "not by the task requesting the release"), 1

    if verb == "list":
        rows = multi_agent.read_reservations(root, scope=SCOPE_SHARED)
        if as_json:
            return json.dumps(rows, indent=2), (0 if rows else 2)
        if not rows:
            return f"no SHARED reservations recorded in {root}", 2
        lines = [f"{len(rows)} SHARED reservation(s) in {root}:"]
        for r in rows:
            lines.append(f"  {r.get('kind')}  {r['resource']}  mode={r.get('mode')}  "
                         f"task={r.get('task_id')}  agent={r.get('agent')}")
        return "\n".join(lines), 0

    if verb == "detect":
        specs = [_parse_session_spec(s) for s in (sessions or [])]
        if len(specs) < 2:
            return ("coord detect compares two or more concurrent sessions: pass "
                    "--session [<user>=]<project-root> at least twice", 2)
        report = scan(specs)
        if record_event:
            record_scan_event(root, report)
        text = json.dumps(report, indent=2) if as_json else format_report(report)
        code = {STATUS_CLEAR: 0, STATUS_CONFLICTS: 1, STATUS_UNKNOWN: 2}[report["status"]]
        return text, code

    return f"unknown coord verb {verb!r}", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.multi_user_coordination",
        description="Spec section 239 multi-user coordination CONFLICT DETECTION: "
                    "stale-SHA, duplicate-regression and shared-resource-reservation "
                    "conflicts between two or more concurrent users' project roots. "
                    "Detects and reports only -- it arbitrates nothing, locks nothing, "
                    "and cancels nothing.")
    ap.add_argument("verb", choices=("detect", "reserve", "release", "list"))
    ap.add_argument("--root", default=".",
                    help="This session's own project root (where a reserve/release lands, "
                         "and where a detect scan's audit event is written).")
    ap.add_argument("--session", action="append", default=None, dest="sessions",
                    metavar="[USER=]PROJECT_ROOT",
                    help="detect: one concurrent session (repeatable, at least twice).")
    ap.add_argument("--resource", default=None, help="reserve/release: the resource id.")
    ap.add_argument("--kind", default=None, choices=multi_agent.SHARED_RESOURCE_KINDS,
                    help="reserve/release: what kind of shared resource this is.")
    ap.add_argument("--agent", default=None, help="reserve: who is claiming it.")
    ap.add_argument("--task", default=None, dest="task_id",
                    help="reserve/release: the claiming task id (a release must come "
                         "from the holding task).")
    ap.add_argument("--mode", default=MODE_WRITE, choices=(MODE_WRITE, "READ"),
                    help="reserve: WRITE (exclusive intent) or READ.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(a.verb, root=a.root, sessions=a.sessions,
                                  resource=a.resource, kind=a.kind, agent=a.agent,
                                  task_id=a.task_id, mode=a.mode, as_json=a.json)
    except CoordinationError as e:
        print(f"{type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
