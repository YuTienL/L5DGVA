"""Question "Why Am I Being Asked This" Grounding (2026-09-08).

Closes CLAUDE.md's own "'Why Am I Being Asked This' Grounding: Already
Substantively Closed by Sibling Work, No Dedicated Module Built for This
Item" section, which explicitly named the follow-up work: "A future pass
wanting a dedicated `question_why_grounding` entry point should build a
thin, explicitly-named wrapper over `request_clarification()`/
`build_escalation_package()` rather than a third, independently-derived
explanation mechanism." That is exactly what this module is, and only that
-- it computes NO new fact about a question record, no plain-English
translation of its own, and no evidence citation logic of its own. Every
byte this module returns is read straight out of `question_queue.
request_clarification()`'s own real result.

**REUSE OVER REINVENT, checked and confirmed before writing a line here.**
`request_clarification(store, question_id, record=False)` already computes
the identical composition this item's own spec asks for: it re-renders one
already-filed question record via `build_escalation_package()` (the real
9-field structured view), translates `classify_tier()`'s own closed
`tier_reason` vocabulary into plain-English sentences via
`_explain_tier_reason()`, and lays every option's own already-researched
`rationale` out under a labeled "evidence" heading. There is no second,
independently-derived "why" mechanism anywhere in this repository, and this
module deliberately does not build one -- `explain_why_asked()` below is a
pure re-shaping of `request_clarification()`'s own real return value.

**Why a distinct, purpose-named entry point rather than callers reaching
for `request_clarification()` directly.** `request_clarification()`'s own
framing is REACTIVE: a human signals "I don't understand this question I
was already asked" and, by default, that signal is itself recorded as an
audit entry (`record=True`) in `store.clarifications_path`. "Why am I being
asked this" is a genuinely different, PROACTIVE use: a human or agent
reading a pending question wants the SAME grounding context shown
*before* attempting to answer, with no implication that anyone was
confused and nothing filed as if they were. `explain_why_asked()` therefore
always calls the reused function with `record=False` -- this module never
writes to `clarifications.json`, and has no code path that could (proven
directly by an AST-based test over this module's own source, mirroring the
"never authorizes/writes" structural guards several sibling modules in
this codebase already establish for themselves).

Deliberately bounded, and stated rather than implied closed: this module
never files a question, never answers one, and never decides anything --
it only re-renders, under an intent-revealing name, exactly what
`request_clarification()` already computes from real, already-persisted
evidence. There is no `dv-harness` CLI verb (`cli.py`/`gates.py` were not
touched, per this session's own established convention for a standalone
module built while those files are under concurrent edit pressure from
other work in this same multi-agent session) -- the front door is
`python -m dv_harness.question_why_grounding explain --root <dir>
--question-id <id> [--json]`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .question_queue import QuestionQueueStore, request_clarification


class QuestionWhyGroundingError(Exception):
    """Raised only when the underlying real lookup itself fails (an
    unknown question_id) -- never fabricated, and never swallowed into a
    guessed-empty result."""


def explain_why_asked(store: QuestionQueueStore, question_id: str) -> Dict[str, Any]:
    """The real "why am I being asked this" grounding for one already-filed
    question, computed ENTIRELY by re-shaping `question_queue.
    request_clarification(store, question_id, record=False)`'s own real
    return value -- no new evidence, no new plain-English translation, no
    new citation logic is computed here.

    Raises `QuestionWhyGroundingError` (wrapping the real `KeyError`
    `request_clarification()`/`store.get_question()` raise for an unknown
    `question_id`) rather than a silently empty explanation -- this module
    can never explain a question that does not exist.

    Returns
    -------
    {
      "question_id": str,
      "why": [str, ...],       # request_clarification()'s own real
                                # plain_summary, verbatim
      "evidence": [str, ...],  # request_clarification()'s own real
                                # per-option evidence list, verbatim
      "package": {...},        # build_escalation_package()'s own real
                                # 9-field projection, carried through
                                # unmodified (via request_clarification())
    }

    This function NEVER writes to `store.clarifications_path` -- it always
    calls the reused function with `record=False`, since this is a
    proactive "here is the context" render, never a "a human signaled
    confusion" event."""
    try:
        result = request_clarification(store, question_id, record=False)
    except KeyError as exc:
        raise QuestionWhyGroundingError(str(exc)) from exc

    return {
        "question_id": result["question_id"],
        "why": result["plain_summary"],
        "evidence": result["evidence"],
        "package": result["package"],
    }


def render_why_asked_markdown(explanation: Dict[str, Any]) -> str:
    """Human-readable rendering of an `explain_why_asked()` result -- the
    same "one labeled section per block" shape this module's reused
    `question_queue.render_clarification_markdown()`/
    `render_escalation_package_markdown()` already establish, applied here
    under a "why" heading rather than a "clarification" one, matching this
    function's own proactive-not-reactive intent."""
    lines: List[str] = [f"### Why you're being asked: {explanation['question_id']}", ""]
    lines.append("**In plain terms:**")
    for line in explanation["why"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("**Evidence already found, per option:**")
    for line in explanation["evidence"]:
        lines.append(f"- {line}")
    pkg = explanation.get("package") or {}
    if pkg.get("recommended_option"):
        lines.append("")
        lines.append(f"- **Recommended option:** {pkg['recommended_option']}")
    if pkg.get("urgency"):
        lines.append(f"- **Urgency:** {pkg['urgency']}")
    return "\n".join(lines)


# --- front door ---------------------------------------------------------

def execute_verb(argv) -> int:
    """`python -m dv_harness.question_why_grounding explain --root <dir>
    --question-id <id> [--json]`. Exit 0: explained. Exit 2: the question
    could not be found, or a usage error."""
    ap = argparse.ArgumentParser(
        prog="question-why-grounding",
        description="Proactive 'why am I being asked this' grounding over an "
                    "already-filed question_queue.py record -- a thin, "
                    "explicitly-named wrapper over request_clarification()/"
                    "build_escalation_package(), never a second explanation "
                    "mechanism.")
    ap.add_argument("verb", choices=["explain"])
    ap.add_argument("--root", required=True, help="project root")
    ap.add_argument("--question-id", required=True, dest="question_id")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))

    store = QuestionQueueStore(Path(args.root))
    try:
        explanation = explain_why_asked(store, args.question_id)
    except QuestionWhyGroundingError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, indent=2))
        return 2

    if args.json:
        print(json.dumps(explanation, indent=2))
    else:
        print(render_why_asked_markdown(explanation))
    return 0


def main(argv: Optional[Any] = None) -> int:
    import sys as _sys
    return execute_verb(list(_sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
