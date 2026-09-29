"""dv_harness/waveform_dump_gate.py -- the HUMAN half of CLAUDE.md's
"Waveform Dump User Gate", as a real, verifiable decision record.

Why this module exists (2026-09-04, AI-mechanism #12 "AI Debug Closed Loop"
gap closure). CLAUDE.md requires that before any waveform-enabled simulation
the user confirms dump scope and level/depth.
`tools/verification_flow/focused_wave_debug_window_gate.py` enforced that by
requiring `dump_scope_confirmed.confirmed_by` to be a non-empty STRING --
which the agent writing the evidence block fills in itself. On the
interactive path a human really was asked, so the string was honest. On the
autonomous path it cannot be: `engine.loop()` dispatches a headless
`claude -p --dangerously-skip-permissions` subprocess (see
`dv_harness/adapters/cli.py`) with the prompt piped once through stdin and no
live channel back to a human, so there is no mechanism by which an
in-flight question could be answered. A self-filled `confirmed_by` therefore
satisfied the machine check while violating the rule the check exists to
enforce -- the gate passed precisely when nobody had been asked.

What closes it: the confirmation is no longer a claim inside the evidence
block, it is a lookup against the question queue's own decisions store.
`verify_dump_scope_confirmation()` re-derives the question_key from the
DECLARED SCOPE, finds the persisted decision for it, and requires
`current.source == question_queue.HUMAN_DECISION_SOURCE`. That is the same
single sanctioned "a human really decided this" source
`connectivity.enforce_bind_tier_policy()` / `apply_answered_questions()`
already use for T3 binds and unfilled scoreboard fields -- deliberately the
same one, so the harness cannot answer its own waveform escalation with its
own earlier guess, and so there is exactly one notion of "confirmed" in this
codebase rather than two.

The ask half (`ask_dump_scope_confirmation()`, `dv-harness waveform-dump-scope
ask`) files the question through the real `QuestionQueueStore` so the gate is
satisfiable the intended way and no other: a human answers it with the
already-existing `dv-harness question-queue answer <Q-ID>`, and the loop
resumes. Nothing here writes a decision -- only `answer_question()` does, and
only a human runs that.

Tier: the question is filed with `blast_radius="unbounded"`, which
`classify_tier()` maps to Tier 3 (CANNOT_ASSUME, blocking, stays OPEN with no
answer). That is not a label chosen to force an escalation -- an unconfirmed
dump scope's worst case IS unbounded (the full-chip/full-depth dump CLAUDE.md
forbids defaulting to costs disk and simulation time with no ceiling), which
is exactly Part B's own bar for "wider than one cheaply-re-run regression".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import question_queue
from .question_queue import QuestionQueueStore

#: Waveform dump scope/level is an ENVIRONMENT decision, so it routes to the
#: DV-owner through question_queue's own DOMAIN_OWNER_ROUTING table -- not a
#: routing rule restated here.
WAVEFORM_DUMP_DOMAIN = "env"

#: The canonical question text. It is part of the question_key (see
#: make_question_key), so it must be stable: changing this string re-keys
#: every future ask and orphans decisions already answered against the old
#: wording. Scope-specific detail belongs in `context_path`, never here.
WAVEFORM_DUMP_QUESTION = (
    "Confirm the waveform dump scope and level/depth for this targeted rerun "
    "(CLAUDE.md Waveform Dump User Gate: prefer the minimum sufficient "
    "waveform for the current failure cone; do not default to "
    "full-chip/full-depth)."
)

#: Failure reasons this module can return, all of which mean the same thing:
#: a human has not confirmed dump scope for this exact scope. They are
#: distinct strings because they need distinct remedies -- file the question,
#: get it answered, or fix the evidence block's attribution.
REASON_NOT_ASKED = "WAVEFORM_DUMP_SCOPE_NOT_ASKED"
REASON_AWAITING_ANSWER = "WAVEFORM_DUMP_SCOPE_AWAITING_ANSWER"
REASON_NOT_HUMAN_ANSWERED = "WAVEFORM_DUMP_SCOPE_NOT_HUMAN_ANSWERED"
REASON_CONFIRMED_BY_MISMATCH = "WAVEFORM_DUMP_SCOPE_CONFIRMED_BY_MISMATCH"

#: Every reason -- from this module and from the gate script's own earlier
#: shape checks -- that means "stop and ask a human", as opposed to "the
#: agent supplied wrong evidence". `dv_harness/gates.py` maps exactly this
#: set to the NEEDS_USER_INPUT verdict, which `engine.run_stage()` turns into
#: Status.WAIT_USER and `engine.loop()` stops cleanly on. Kept here, next to
#: the reasons themselves, so a new reason cannot be added without the
#: routing question being answered in the same edit.
NEEDS_USER_INPUT_REASONS = frozenset({
    "WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED",
    "WAVEFORM_DUMP_SCOPE_CONFIRMATION_INCOMPLETE",
    REASON_NOT_ASKED,
    REASON_AWAITING_ANSWER,
    REASON_NOT_HUMAN_ANSWERED,
    REASON_CONFIRMED_BY_MISMATCH,
})


def dump_scope_context_path(scope: str) -> str:
    """The `context_path` a waveform-dump-scope question is filed under.

    The declared scope IS the context: two reruns proposing different dump
    scopes are two different decisions and must not share one answer, while
    a rerun re-proposing an already-confirmed scope must resolve from the
    decision already on file rather than re-asking (question_queue's
    "once answered, never asked again" guarantee, keyed on question_key,
    which is derived from this)."""
    return f"waveform_dump_scope::{str(scope or '').strip()}"


def dump_scope_question_key(scope: str) -> str:
    """The stable question_key for one dump scope. Derived through
    `question_queue.make_question_key()` rather than hand-formatted, so the
    ask side and the verify side cannot drift into disagreeing about what
    "the same question" means."""
    return question_queue.make_question_key(
        WAVEFORM_DUMP_DOMAIN, WAVEFORM_DUMP_QUESTION, dump_scope_context_path(scope))


def _resolve_store(root, store: Optional[QuestionQueueStore]) -> QuestionQueueStore:
    return store if store is not None else QuestionQueueStore(Path(root))


def ask_dump_scope_confirmation(root, *, scope: str, proposed_level_or_depth: str,
                                  failure_cone: str = "", store: Optional[QuestionQueueStore] = None,
                                  now=None) -> Dict[str, Any]:
    """File the dump-scope confirmation question and return the persisted
    record (its `id` is the Q-ID a human answers).

    Persisting only -- never a ping, per Part B; `dv-harness question-queue
    digest` is the batching path, unchanged. Idempotent in the way the queue
    already is: the Q-ID is derived from the question_key, so re-asking for
    the same scope re-mints the same id, and once a human has answered it the
    record comes back SELF_RESOLVED from the decisions store instead of
    escalating again.

    Raises ValueError on an empty scope or an empty proposed level/depth: a
    question that does not say what is being proposed cannot be answered
    yes/no by the person receiving it."""
    scope = str(scope or "").strip()
    proposed_level_or_depth = str(proposed_level_or_depth or "").strip()
    if not scope:
        raise ValueError("scope is required -- a dump-scope question with no scope cannot be answered")
    if not proposed_level_or_depth:
        raise ValueError(
            "proposed_level_or_depth is required -- CLAUDE.md's gate covers scope AND level/depth")

    return _resolve_store(root, store).add_question(
        domain=WAVEFORM_DUMP_DOMAIN,
        question=WAVEFORM_DUMP_QUESTION,
        context_path=dump_scope_context_path(scope),
        question_key=dump_scope_question_key(scope),
        options=[
            {"label": f"APPROVE scope={scope} level_or_depth={proposed_level_or_depth}",
             "rationale": ("Minimum sufficient waveform for the current failure cone"
                            + (f": {failure_cone}" if failure_cone else ""))},
            {"label": "NARROW the scope or level/depth before dumping",
             "rationale": "The proposal dumps more than this failure cone needs."},
            {"label": "WIDEN the scope or level/depth",
             "rationale": "The proposal is too narrow to contain the failure cone."},
        ],
        recommendation=f"APPROVE scope={scope} level_or_depth={proposed_level_or_depth}",
        # Deliberately NOT an auto-usable default: a Tier-3 question stays
        # OPEN with no answer, so this text is what the digest reports would
        # happen absent an answer, not something the harness may act on.
        assumption_if_unanswered="No waveform dump is performed until this is answered.",
        context={
            # See the module docstring: an unconfirmed dump scope's worst
            # case is genuinely unbounded, which is Part B's own Tier-3
            # blast-radius bar -- not a hard trigger asserted to force one.
            "blast_radius": "unbounded",
            "domain": WAVEFORM_DUMP_DOMAIN,
            "proposed_scope": scope,
            "proposed_level_or_depth": proposed_level_or_depth,
            "failure_cone": failure_cone,
        },
        now=now,
    )


def verify_dump_scope_confirmation(root, confirm: Any, *,
                                     store: Optional[QuestionQueueStore] = None) -> Tuple[bool, Dict[str, Any]]:
    """Verify one evidence block's `dump_scope_confirmed` against the real
    question-queue decision for its declared scope.

    Returns `(ok, detail)`. `detail` always carries `question_key` and
    `question_id` so a failing gate tells the reader exactly which Q-ID to
    answer, and on failure carries `reason` (one of this module's REASON_*)
    plus `needs_user_input: True`.

    Three things must hold, and none of them is attestable by the agent
    writing the evidence block:
      1. A decision exists for this scope's question_key. Its absence splits
         into two DIFFERENT remedies, so it reports two different reasons:
         the question was never filed (REASON_NOT_ASKED -> file it), or it is
         filed and sitting OPEN (REASON_AWAITING_ANSWER -> a human answers
         it). A Tier-3 question creates no decision, so "no decision" alone
         cannot tell those apart -- the questions store has to be consulted.
      2. Its CURRENT source is `question_queue.HUMAN_DECISION_SOURCE` -- a
         Tier-2 auto-assumption the harness minted for itself is rejected,
         same rule `classify_tier()` and `connectivity.apply_answered_questions()`
         apply.
      3. The block's `confirmed_by` names the human who actually decided it
         (`current.decided_by`), compared case-insensitively after stripping.
         Without this the block could cite a real answered decision while
         attributing it to someone who never saw it.
    """
    confirm = confirm if isinstance(confirm, dict) else {}
    scope = str(confirm.get("scope") or "").strip()
    confirmed_by = str(confirm.get("confirmed_by") or "").strip()
    key = dump_scope_question_key(scope)
    qid = question_queue.make_question_id(WAVEFORM_DUMP_DOMAIN, key)
    base = {"question_key": key, "question_id": qid, "scope": scope}

    store = _resolve_store(root, store)
    decision = store.find_decision(key)
    current = (decision or {}).get("current") or {}
    if not current:
        if store.get_question(qid) is not None:
            return False, dict(base, reason=REASON_AWAITING_ANSWER, needs_user_input=True,
                                remedy=(f"{qid} is already filed and waiting. A human answers it with "
                                         f"`dv-harness question-queue answer {qid} --answer ... --basis ... "
                                         f"--decided-by ...`."))
        return False, dict(base, reason=REASON_NOT_ASKED, needs_user_input=True,
                            remedy=(f"Run `dv-harness waveform-dump-scope ask --scope {scope or '<scope>'} "
                                     f"--level-or-depth <level>`, then have a human answer {qid} with "
                                     f"`dv-harness question-queue answer {qid} --answer ... --basis ... "
                                     f"--decided-by ...`."))
    if current.get("source") != question_queue.HUMAN_DECISION_SOURCE or not str(current.get("answer") or "").strip():
        return False, dict(base, reason=REASON_NOT_HUMAN_ANSWERED, needs_user_input=True,
                            decision_source=current.get("source"),
                            remedy=(f"A decision exists for {qid} but it is not a human answer "
                                     f"(source={current.get('source')!r}). Have a human answer it with "
                                     f"`dv-harness question-queue answer {qid} ...`."))
    decided_by = str(current.get("decided_by") or "").strip()
    if confirmed_by.lower() != decided_by.lower():
        return False, dict(base, reason=REASON_CONFIRMED_BY_MISMATCH, needs_user_input=True,
                            confirmed_by=confirmed_by, decided_by=decided_by,
                            remedy=(f"`confirmed_by` must name the human who answered {qid} "
                                     f"({decided_by!r}), not {confirmed_by!r}."))
    return True, dict(base, confirmed_by=decided_by, answer=current.get("answer"),
                       decided_at=current.get("decided_at"))
