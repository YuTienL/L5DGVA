"""dv_harness/first_time_user_onboarding.py -- intake_interaction:
first_time_user_onboarding.

WHAT WAS MISSING, verified before a line of this was written. A repo-wide
grep for `first_time`/`onboarding`/`tutorial`/`new_user`/`is_new_user`
across `dv_harness/*.py` matched nothing that answers this question --
`gates.py`'s `protocol_onboarding_gate` is a DIFFERENT, unrelated concept
(protocol-onboarding *content completeness*, an evidence-block shape check),
and no module anywhere adapted question phrasing/explanation depth to
whether the human on the other end has done this before. Two real
mechanisms this module reuses rather than duplicates already existed and
were never wired together for this purpose:

  * `dv_harness/user_info.py`'s `summarize_user_access()` -- the real,
    already-tested per-project access-history rollup, built from the SAME
    `.dv-harness/events.jsonl` every other subsystem in this harness reads
    and writes through, answering "who has used THIS deployment, and when"
    (its own module docstring). It has never before answered "is the
    CURRENT session this specific user's first one."
  * `dv_harness/question_queue.py`'s `request_clarification()` -- a real,
    already-tested EXPANDED rendering of one persisted question (a plain-
    English restatement of `tier_reason` via `_explain_tier_reason()`, plus
    every option's own pre-researched `rationale` laid out under an
    "evidence" heading) that a human currently has to explicitly ask for by
    name. Nothing made that expanded rendering the DEFAULT for someone who
    has never seen this harness's questions before.

WHAT THIS MODULE IS. A detector (`detect_first_time_user()`) that classifies
"has this user answered intake questions before" from real, evidence-cited
project state -- never a second question-answering mechanism, never a
second question-rendering engine -- plus a thin composition layer
(`render_question_for_user()` / `render_questions_for_user()`) that reuses
`request_clarification(..., record=False)` verbatim for a first-time user
and `build_escalation_package()` verbatim for everyone else. `record=False`
matters: this is an AUTOMATIC, policy-driven rendering choice, not a human
explicitly asking for clarification, so it must never mint a
`clarifications.json` audit entry claiming a human requested one.

THE DETECTOR'S EVIDENCE, IN ORDER OF STRENGTH -- never a single fixed rule,
and every step is real, cited evidence, never a guess:

  1. DIRECT: does `.dv-harness/question_queue/decisions.json` already carry
     a LIVE decision whose `current.decided_by == user` AND
     `current.source == HUMAN_DECISION_SOURCE` -- i.e. has this user
     literally answered an intake question in this project before? A
     Tier-2 `tier2_auto_assumption` entry is never counted here: it is this
     harness's OWN guess, not evidence the user has ever answered anything
     (the exact "not evidence, not the human" distinction `_is_human_
     decision()`/`find_redundant_decision()` already draw one module over).
  2. REAL ACCESS-HISTORY (`user_info.py`, "reusing user_info.py's real
     access-history data if it exists" per this item's own instruction):
     when the direct check finds nothing, is this user's own real,
     session-gap-inferred `session_count` for this project (via
     `summarize_user_access()`) >= 2 -- i.e. real evidence of at least one
     earlier, gap-separated visit -- or exactly the 1 session on record
     that IS the current one?
  3. PROJECT-COUNT HEURISTIC ("or a project-count heuristic", the item's own
     named fallback): only once NEITHER of the two per-user sources above
     found anything at all for this user in this project (no access-history
     entry exists -- a fresh project, or a caller invoked before any
     CLI_ACCESS/GUI_ACCESS event fired) -- count real SIBLING directories
     next to `root` that carry their own `.dv-harness/` tree, a plain,
     self-contained, filesystem-evidenced proxy for "has this workspace set
     this harness up before." Explicitly weaker and disclosed as such: it is
     a fact about the WORKSPACE, not this specific user's own identity (no
     per-user identity is recorded at the workspace level anywhere in this
     codebase to check against).
  4. A genuine READ FAILURE on BOTH stronger sources (a malformed
     decisions.json AND an unreadable events.jsonl) is the required
     negative control this item's own house style demands: honestly
     `UNKNOWN_INSUFFICIENT_EVIDENCE`, never silently defaulted toward either
     FIRST_TIME or RETURNING.

Six statuses total (`DETECTION_STATUSES`), checked at import to share no
token with `dv_harness.models.Status` -- the same guard many sibling modules
in this codebase already apply to their own vocabularies, so a reader can
never mistake this module's own onboarding classification for a real
stage-gate verdict.

RENDERING POLICY is kept explicitly SEPARATE from the raw evidence-based
`status` (`should_use_explanatory_rendering()`): true for both FIRST_TIME_*
statuses AND for the honest `UNKNOWN_INSUFFICIENT_EVIDENCE` status -- a
deliberate, disclosed conservative default. Rendering the extra explanation
for an experienced user costs a few lines nobody has to read twice;
rendering the terse default for a genuine first-time user costs real
confusion. The raw STATUS is never fabricated toward FIRST_TIME to reach
this outcome -- only this one downstream policy function treats an honest
"we could not tell" the same way it treats a confirmed first-time finding.

DECIDES NOTHING BEYOND CLASSIFICATION AND RENDERING. This module answers no
question itself (only a human, via `QuestionQueueStore.answer_question()`,
does that), files no question, runs no build/regression/LSF job, and
touches no approval/governance mechanism. There is deliberately no stage
gate and no `dv-harness` CLI verb -- `cli.py`/`gates.py`/`dashboard.py` are
on this batch's own never-touch list (several other concurrent workflows
are actively editing those files); the front door is the standalone
`python -m dv_harness.first_time_user_onboarding`, the same disclosed choice
several sibling modules in this codebase already make.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import user_info
from .question_queue import (
    HUMAN_DECISION_SOURCE,
    QuestionQueueStore,
    build_escalation_package,
    render_escalation_package_markdown,
    request_clarification,
)

# ---------------------------------------------------------------------------
# Detection vocabulary
# ---------------------------------------------------------------------------

#: Direct, real evidence: at least one live HUMAN_DECISION_SOURCE decision
#: on file in THIS project with decided_by == this user.
RETURNING_ANSWERED_BEFORE = "RETURNING_ANSWERED_BEFORE"
#: No direct decision evidence, but real user_info.py access history shows
#: >= MIN_RETURNING_SESSION_COUNT session(s) for this user in this project.
RETURNING_ACCESS_HISTORY = "RETURNING_ACCESS_HISTORY"
#: No per-user evidence at all in this project, but the project-count
#: heuristic found >= 1 sibling dv-harness project alongside this one.
RETURNING_HEURISTIC = "RETURNING_HEURISTIC"
#: Real access-history entry found for this user, but it is exactly their
#: first (and only) recorded session, and no decision is on file either.
FIRST_TIME_ACCESS_HISTORY = "FIRST_TIME_ACCESS_HISTORY"
#: No per-user evidence anywhere, and the project-count heuristic found no
#: sibling dv-harness project either.
FIRST_TIME_HEURISTIC = "FIRST_TIME_HEURISTIC"
#: Both stronger evidence sources (decisions.json, user_info.py access
#: history) genuinely failed to read -- honestly unresolved, never guessed.
UNKNOWN_INSUFFICIENT_EVIDENCE = "UNKNOWN_INSUFFICIENT_EVIDENCE"

DETECTION_STATUSES: Tuple[str, ...] = (
    RETURNING_ANSWERED_BEFORE,
    RETURNING_ACCESS_HISTORY,
    RETURNING_HEURISTIC,
    FIRST_TIME_ACCESS_HISTORY,
    FIRST_TIME_HEURISTIC,
    UNKNOWN_INSUFFICIENT_EVIDENCE,
)

#: See should_use_explanatory_rendering()'s own docstring for the
#: conservative-default reasoning behind including UNKNOWN here.
_EXPLANATORY_STATUSES = frozenset({
    FIRST_TIME_ACCESS_HISTORY, FIRST_TIME_HEURISTIC, UNKNOWN_INSUFFICIENT_EVIDENCE,
})

RENDERING_STANDARD = "STANDARD"
RENDERING_EXPLANATORY = "EXPLANATORY_FIRST_TIME"

#: A single recorded session IS this user's first session on record; a
#: SECOND, real, session-gap-separated (user_info.SESSION_GAP_SECONDS)
#: session is the first real evidence they have been back.
MIN_RETURNING_SESSION_COUNT = 2


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status/rendering-mode vocabularies must share no
    token with `dv_harness.models.Status` -- the same discipline several
    sibling modules in this project already apply to their own vocabularies."""
    from .models import Status
    verdict_tokens = {s.value for s in Status}
    this_module_tokens = set(DETECTION_STATUSES) | {RENDERING_STANDARD, RENDERING_EXPLANATORY}
    collision = verdict_tokens & this_module_tokens
    if collision:
        raise AssertionError(
            f"first_time_user_onboarding vocabulary collides with "
            f"dv_harness.models.Status: {collision}"
        )


def _default_user() -> str:
    # Same env-var fallback chain control_plane.py/cli.py's own
    # _access_user() and question-queue answer --decided-by default already
    # use for the identical identity question -- kept as a private copy
    # rather than a cross-import, matching this codebase's established
    # pattern (cli.py's own _access_user() docstring states the same choice).
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


# ---------------------------------------------------------------------------
# Evidence readers -- each a thin, read-only wrapper over an existing
# producer; none re-derives a fact the producer already computes.
# ---------------------------------------------------------------------------

def real_prior_decisions_by_user(store: QuestionQueueStore, user: str) -> List[Dict[str, Any]]:
    """Every LIVE decision in this project's own decisions.json whose
    current answer both (a) was recorded by decided_by == `user`, and (b)
    is a real human answer (source == HUMAN_DECISION_SOURCE) -- never a
    Tier-2 auto-assumption, which is this harness's own guess, not evidence
    the user has ever answered anything.

    Reads `store._load_decisions()`, the same private accessor this
    module's own real production path (decisions.md rendering) and at least
    one other sibling test file in this codebase already use externally --
    there is no second, bulk decisions reader in question_queue.py to call
    instead; `find_decision()` only looks up ONE question_key at a time,
    and this needs every one on file."""
    data = store._load_decisions()
    hits: List[Dict[str, Any]] = []
    for key in sorted((data.get("decisions") or {}).keys()):
        entry = data["decisions"][key]
        cur = (entry or {}).get("current") or {}
        if cur.get("source") == HUMAN_DECISION_SOURCE and cur.get("decided_by") == user:
            hits.append({
                "question_key": key,
                "decided_at": cur.get("decided_at"),
                "question_id_of_answer": cur.get("question_id_of_answer"),
            })
    return hits


def user_access_summary(root: Path, user: str) -> Optional[Dict[str, Any]]:
    """This user's own real per-project access-history rollup from
    `user_info.summarize_user_access()` -- the same CLI_ACCESS/GUI_ACCESS
    (plus control-plane) events every other real access-history consumer in
    this codebase already reads, rolled into inferred sessions. `None` when
    this user has no recorded access event in this project at all -- never
    "0 sessions", which would misrepresent "we never looked" as "we looked
    and found none"."""
    summary = user_info.summarize_user_access(root)
    for u in summary.get("users", []):
        if u.get("user") == user:
            return u
    return None


def sibling_harness_project_count(root: Path, *, parent: Optional[Path] = None) -> int:
    """Project-count heuristic fallback -- used ONLY once neither of the two
    stronger, per-user evidence sources above found anything for this user
    in this project. Counts real SIBLING directories (immediate children of
    `parent`, defaulting to `root`'s own parent directory) that carry their
    own `.dv-harness/` tree -- i.e. other dv-harness PROJECTS this same
    workspace already has: a plain, self-contained, filesystem-evidenced
    proxy for "has this workspace set up this harness before", never a
    claim about this SPECIFIC user's own identity (no per-user identity is
    recorded at the workspace level anywhere in this codebase to check
    against, so this heuristic is deliberately weaker and named as such).
    `root` itself is excluded. A nonexistent/unreadable parent reports 0,
    honestly -- "nothing found" rather than an error, since an absent
    parent directory is itself real evidence there is nothing else here."""
    root = Path(root).resolve()
    parent_dir = Path(parent).resolve() if parent is not None else root.parent
    if not parent_dir.is_dir():
        return 0
    try:
        children = list(parent_dir.iterdir())
    except OSError:
        return 0
    count = 0
    for child in children:
        try:
            if not child.is_dir():
                continue
            if child.resolve() == root:
                continue
            if (child / ".dv-harness").is_dir():
                count += 1
        except OSError:
            continue
    return count


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------

def _result(status: str, user: str, evidence: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    return {
        "status": status,
        "user": user,
        "reason": reason,
        "evidence": evidence,
        "rendering_mode": RENDERING_EXPLANATORY if status in _EXPLANATORY_STATUSES else RENDERING_STANDARD,
    }


def detect_first_time_user(root: Path, user: Optional[str] = None, *,
                            store: Optional[QuestionQueueStore] = None,
                            sibling_scan_parent: Optional[Path] = None) -> Dict[str, Any]:
    """Classify whether `user` (default: `_default_user()`) has answered
    intake questions before, from real, cited project evidence -- see the
    module docstring for the full 4-step evidence order. Never raises on a
    read failure: a genuine problem reading either underlying store is
    itself recorded as evidence and, if both fail, reported as the honest
    `UNKNOWN_INSUFFICIENT_EVIDENCE` status rather than propagated as an
    exception that would crash an onboarding check over a project a human
    is trying to get INTO."""
    root = Path(root)
    user = user or _default_user()
    evidence: Dict[str, Any] = {}

    # 1. Direct: has this user ever answered a real intake question in this
    #    project's own queue?
    decisions_error: Optional[str] = None
    prior_decisions: List[Dict[str, Any]] = []
    try:
        qstore = store if store is not None else QuestionQueueStore(root)
        prior_decisions = real_prior_decisions_by_user(qstore, user)
    except Exception as exc:  # noqa: BLE001 -- a store-read failure is real evidence, not a crash
        decisions_error = f"{type(exc).__name__}: {exc}"
    evidence["prior_decisions_by_user"] = prior_decisions
    if decisions_error is not None:
        evidence["decisions_read_error"] = decisions_error

    if decisions_error is None and prior_decisions:
        return _result(
            RETURNING_ANSWERED_BEFORE, user, evidence,
            reason=(
                f"{len(prior_decisions)} real decision(s) on file with "
                f"decided_by={user!r} and source={HUMAN_DECISION_SOURCE!r} in "
                "this project's own question_queue"
            ),
        )

    # 2. Real access-history rollup (user_info.py).
    access_error: Optional[str] = None
    access: Optional[Dict[str, Any]] = None
    try:
        access = user_access_summary(root, user)
    except Exception as exc:  # noqa: BLE001
        access_error = f"{type(exc).__name__}: {exc}"
    evidence["access_history"] = access
    if access_error is not None:
        evidence["access_history_read_error"] = access_error

    if access_error is None and access is not None:
        session_count = int(access.get("session_count") or 0)
        if session_count >= MIN_RETURNING_SESSION_COUNT:
            return _result(
                RETURNING_ACCESS_HISTORY, user, evidence,
                reason=(
                    f"{session_count} recorded sessions on file for {user!r} in "
                    f"this project (first_seen={access.get('first_seen')!r}) -- "
                    "real evidence of at least one prior, gap-separated visit"
                ),
            )
        return _result(
            FIRST_TIME_ACCESS_HISTORY, user, evidence,
            reason=(
                f"only {session_count} recorded session on file for {user!r}, "
                "and no real human-answered intake decision on file either -- "
                "this looks like this user's first session in this project"
            ),
        )

    # 3. Genuine read failure on BOTH stronger sources -> honestly UNKNOWN.
    if decisions_error is not None and access_error is not None:
        return _result(
            UNKNOWN_INSUFFICIENT_EVIDENCE, user, evidence,
            reason=(
                "could not read either this project's question_queue "
                "decisions or its user_info access-history trail -- neither "
                "real per-user evidence source could be checked"
            ),
        )

    # 4. Neither stronger source found ANYTHING for this user (no error, just
    #    nothing on file) -- project-count heuristic fallback.
    sibling_count = sibling_harness_project_count(root, parent=sibling_scan_parent)
    evidence["sibling_harness_project_count"] = sibling_count
    if sibling_count > 0:
        return _result(
            RETURNING_HEURISTIC, user, evidence,
            reason=(
                f"no per-user decision/access-history evidence for {user!r} "
                f"in this project, but {sibling_count} sibling dv-harness "
                "project(s) were found alongside it -- weak, workspace-level "
                "evidence this is an experienced multi-project setup"
            ),
        )
    return _result(
        FIRST_TIME_HEURISTIC, user, evidence,
        reason=(
            f"no per-user decision/access-history evidence for {user!r}, and "
            "no sibling dv-harness projects found either -- nothing on file "
            "suggests this user (or this workspace) has done this before"
        ),
    )


def should_use_explanatory_rendering(detection: Dict[str, Any]) -> bool:
    """Policy layer, deliberately kept separate from the raw evidence-based
    `status` produced by detect_first_time_user() -- see this module's
    docstring for the conservative-default reasoning. Equivalent to reading
    `detection["rendering_mode"] == RENDERING_EXPLANATORY`; provided as its
    own named predicate so a caller need not know that field's exact
    spelling."""
    return detection.get("rendering_mode") == RENDERING_EXPLANATORY


# ---------------------------------------------------------------------------
# Adapted question rendering
# ---------------------------------------------------------------------------

def render_question_for_user(store: QuestionQueueStore, question_id: str, *,
                              explanatory: bool) -> Dict[str, Any]:
    """One question's rendering, adapted to `explanatory` (see
    should_use_explanatory_rendering()).

    STANDARD mode is exactly `build_escalation_package()`'s existing 9-field
    view -- unchanged, no re-derivation.

    EXPLANATORY_FIRST_TIME mode reuses `request_clarification()`'s already-
    real rendering (plain_summary + evidence, built entirely from fields the
    persisted record already carries -- see that function's own module-level
    comment on why this project has no free-text paraphrase capability and
    never invents one) with `record=False`: this is an AUTOMATIC, policy-
    driven rendering choice, not a human explicitly asking for clarification,
    so it must never mint a clarifications.json audit entry that claims a
    human requested one.

    Raises KeyError -- the same raise build_escalation_package()/
    get_escalation_package()/request_clarification() already use -- when no
    such question exists."""
    if explanatory:
        rendering = dict(request_clarification(
            store, question_id,
            requested_by="first_time_user_onboarding(auto)",
            reason="automatic first-time-user explanatory rendering",
            record=False,
        ))
        rendering["rendering_mode"] = RENDERING_EXPLANATORY
        return rendering
    record = store.get_question(question_id)
    if record is None:
        raise KeyError(f"No question with id {question_id!r}")
    return {
        "question_id": question_id,
        "package": build_escalation_package(record),
        "rendering_mode": RENDERING_STANDARD,
    }


def render_question_markdown(rendering: Dict[str, Any]) -> str:
    """Human-readable rendering matching `rendering['rendering_mode']`.
    STANDARD reuses `render_escalation_package_markdown()` unchanged.
    EXPLANATORY_FIRST_TIME layers `request_clarification()`'s own
    plain_summary/evidence lists on top of that SAME markdown -- never a
    second, competing rendering of the 9 core fields."""
    package = rendering.get("package")
    body = render_escalation_package_markdown(package) if package else ""
    if rendering.get("rendering_mode") != RENDERING_EXPLANATORY:
        return body
    lines = [body, "", "**Why we're asking, in plain terms:**"]
    for line in rendering.get("plain_summary") or []:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("**Evidence behind each option:**")
    for line in rendering.get("evidence") or []:
        lines.append(f"- {line}")
    lines.append("")
    lines.append(
        "_(Shown expanded because this looks like your first time answering "
        "intake questions here -- see `dv_harness.first_time_user_onboarding` "
        "for why.)_"
    )
    return "\n".join(lines)


def render_questions_for_user(root: Path, question_ids: Optional[List[str]] = None, *,
                               user: Optional[str] = None,
                               store: Optional[QuestionQueueStore] = None,
                               sibling_scan_parent: Optional[Path] = None) -> Dict[str, Any]:
    """Detect whether `user` is first-time in `root` (detect_first_time_user()),
    then render every question in `question_ids` (default: every OPEN or
    ASSUMED question currently on file -- the ones a human would actually be
    looking at) with the resulting mode. This is the one function that wires
    the detector and the rendering mode together end to end; every fact
    either half uses still comes from the same real, existing producers
    (question_queue.py, user_info.py) documented in this module's own
    docstring."""
    root = Path(root)
    qstore = store if store is not None else QuestionQueueStore(root)
    detection = detect_first_time_user(root, user, store=qstore, sibling_scan_parent=sibling_scan_parent)
    explanatory = should_use_explanatory_rendering(detection)
    if question_ids is None:
        question_ids = [
            q["id"] for q in
            qstore.list_questions(status="OPEN") + qstore.list_questions(status="ASSUMED")
        ]
    renderings: List[Dict[str, Any]] = []
    for qid in question_ids:
        try:
            renderings.append(render_question_for_user(qstore, qid, explanatory=explanatory))
        except KeyError as exc:
            renderings.append({"question_id": qid, "error": str(exc)})
    return {
        "detection": detection,
        "rendering_mode": detection["rendering_mode"],
        "renderings": renderings,
    }


assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Front door -- no `dv-harness` CLI verb per this batch's own file-safety
# convention (cli.py/gates.py/dashboard.py are all under concurrent edit by
# other work in this same batch); `python -m` is the sanctioned fallback
# several sibling modules in this codebase already use.
# ---------------------------------------------------------------------------

def execute_verb(root: Path, verb: str, *, user: Optional[str] = None,
                  question_id: Optional[str] = None) -> Tuple[int, Any]:
    """One implementation behind `python -m
    dv_harness.first_time_user_onboarding`, the same shared `execute_verb()`
    convention several sibling modules in this codebase already follow."""
    root = Path(root)
    if verb == "detect":
        detection = detect_first_time_user(root, user)
        if detection["status"] == UNKNOWN_INSUFFICIENT_EVIDENCE:
            code = 2
        elif detection["status"] in _EXPLANATORY_STATUSES:
            code = 1
        else:
            code = 0
        return code, detection
    if verb == "render":
        if not question_id:
            return 2, {"ok": False, "error": "MISSING_QUESTION_ID",
                       "hint": "render requires --question-id Q-..."}
        qstore = QuestionQueueStore(root)
        detection = detect_first_time_user(root, user, store=qstore)
        try:
            rendering = render_question_for_user(
                qstore, question_id, explanatory=should_use_explanatory_rendering(detection))
        except KeyError as exc:
            return 2, {"ok": False, "error": "QUESTION_NOT_FOUND", "detail": str(exc)}
        code = 1 if should_use_explanatory_rendering(detection) else 0
        return code, {
            "detection": detection,
            "rendering": rendering,
            "markdown": render_question_markdown(rendering),
        }
    if verb == "digest":
        result = render_questions_for_user(root, user=user)
        if not result["renderings"]:
            return 2, result
        code = 1 if should_use_explanatory_rendering(result["detection"]) else 0
        return code, result
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["detect", "render", "digest"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.first_time_user_onboarding",
        description="Is this user's intake session first-time or returning, and what "
                     "question rendering mode should this project use for them.",
    )
    ap.add_argument("verb", choices=["detect", "render", "digest"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--user", default=None)
    ap.add_argument("--question-id", default=None)
    args = ap.parse_args(argv)
    code, payload = execute_verb(
        Path(args.project_root), args.verb, user=args.user, question_id=args.question_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
