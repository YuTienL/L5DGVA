"""dv_harness/low_confidence_human_checkpoint.py -- the missing HUMAN-FACING
pre-action low-confidence checkpoint (gap-close, 2026-09-07, item id
no-human-facing-preaction-low-confidence-checkpoint).

THE GAP THIS CLOSES, stated precisely, per the evidence that opened this
item. `dv_harness/inference.py` already has a real mid-task low-confidence
signal, `build_deeper_investigation_signal()` -- but its own module comment
says outright it is "AGENT-FACING (never human-facing)": it never files a
question, never blocks a stage, and (before this module existed) had
exactly one real consumer, `engine.DVHarness._record_agent_escalation_
signal()`, which appends it to a Blackboard topic ("agent_escalation_
signals") that no graph node's `blackboard_read` ever names and no GUI
surface ever reads -- confirmed by grep returning zero hits for
"agent_escalation_signals" in both `.dv-harness/graph/main_graph.json` and
`dv_harness/dashboard.py` before this module was written. So a
low-confidence root-cause conclusion could be reached, acted on, and
reported with nothing anywhere ever pausing to show a human the reasoning
chain behind it and ask "proceed?" -- exactly the gap this item names.

REUSE OVER REINVENT, checked before writing a line of this. Two existing
mechanisms are called, never re-implemented:
  * `inference.build_deeper_investigation_signal()` decides WHETHER a
    checkpoint is warranted at all (a real LOW confidence result, and only
    LOW) -- this module never recomputes or second-guesses
    `score_confidence()`'s own result, the same reuse discipline
    `engine._record_agent_escalation_signal()` itself already follows for
    the agent-facing signal.
  * `question_queue.QuestionQueueStore.add_question()` is the ONE real
    human-facing, blocking-question mechanism this project already has
    (3-tier ask-a-human protocol, spec Part B). This module files a
    genuine Tier-3 (CANNOT_ASSUME) question through it -- reusing its own
    hard-trigger/tier/owner/persistence/schema-validation machinery
    wholesale -- rather than building a second ask-a-human protocol.

DELIBERATELY DISTINCT from `inference.py`'s own agent-facing signal, and the
two are never conflated. This module's filed question is addressed to a
PERSON, sits in the real persisted question queue
(`.dv-harness/question_queue/questions.json`), and BLOCKS
(`tier == TIER3_CANNOT_ASSUME`, `"blocking": True`) until a human answers it
via `QuestionQueueStore.answer_question()` -- none of which the agent-facing
Blackboard signal (or the Blackboard topic it appends to) ever does.

IDEMPOTENT ON `question_key`, mirroring `source_authority.escalate_
conflict()`'s own dedup-before-add discipline verbatim (that function's own
docstring: "`QuestionQueueStore.add_question()` appends unconditionally...
fine for hand-called escalations, and wrong for a detector wired into
something that reruns... An already-asked question is not asked again; the
EXISTING record is returned"). A checkpoint call for the SAME
stage/context_path/gap that already has a live record on file returns the
EXISTING record rather than filing a duplicate on every retry -- checked
here, never inside `add_question()` itself, since that behaviour is this
call site's own responsibility per that established precedent.

Disclosed residual, mirroring several sibling gates in this codebase (see
CLAUDE.md's "Waveform Dump User Gate" section for the identical shape):
filing a real Tier-3 blocking question here does NOT, by itself, pause
`run_stage()` mid-call -- a bare persisted "blocking" question is a fact a
human/GUI/CLI can already query (`dv-harness question-queue list
--blocking-only`, `harness_status.py`'s own `blockers.human_gates` read),
but actually halting a stage's forward progress needs a real STAGE_GATE
mapping a NEEDS_USER_INPUT verdict onto `Status.WAIT_USER` -- exactly the
mechanism the Waveform Dump User Gate uses, and exactly the further,
separate integration step this item's own scope does not require. What
this module closes is the part that was genuinely and totally missing:
a real, evidence-cited, human-readable reasoning chain landing in the one
place a human already checks for open questions, gated behind a real
blocking Tier-3 question rather than an unread Blackboard topic.

WHAT THIS SECTION DELIBERATELY DOES NOT DO.
  * It never re-derives or overrides `score_confidence()`'s own result --
    only `inference.build_deeper_investigation_signal()`'s already-computed
    verdict decides whether to file anything at all.
  * It never picks the answer for the human -- "proceed" vs. "stop and
    investigate further" is always a real, unresolved OPEN Tier-3 question
    until a human resolves it through `QuestionQueueStore.answer_question()`.
  * It never touches `classify_tier()`'s own hard-trigger rule -- it only
    asserts the one context flag (`affects_pass_fail_verdict`) that is
    honestly true of a low-confidence root-cause conclusion about to be
    acted on and reported as this stage's own result.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from . import inference
from . import question_queue as _qq

#: The two real decisions a human is offered. Deliberately worded as
#: actions, never a restatement of the confidence label the reasoning
#: chain already shows -- the human is being asked what to DO next.
OPTION_PROCEED = "Proceed despite low confidence"
OPTION_INVESTIGATE_FURTHER = "Stop and investigate further before proceeding"

#: Per `question_queue.DOMAIN_OWNER_ROUTING` (vip -> DV-owner/Synopsys-AE,
#: dut -> designer, env -> DV-owner): a mid-investigation confidence
#: checkpoint is not specifically a VIP-fact or a DUT-fact question, so it
#: routes to the DV-owner -- the human actually running this harness -- the
#: same "env" domain the module docstring above names.
DOMAIN = "env"

#: The one real Tier-3 hard trigger this checkpoint asserts
#: (`question_queue.hard_triggers()` / `is_cannot_assume()`), honestly true
#: of a low-confidence root-cause conclusion about to be acted on and
#: reported as a stage's own result -- never a second, invented trigger.
CHECKPOINT_CONTEXT: Dict[str, Any] = {"affects_pass_fail_verdict": True}


def render_reasoning_chain(signal: Dict[str, Any]) -> str:
    """Render `inference.build_deeper_investigation_signal()`'s own real,
    already-computed dict into a human-readable Hypothesis -> Evidence ->
    Confidence -> Gap chain -- the exact chain CLAUDE.md's Engineering
    Memory Policy already names for this record kind, laid out for a human
    reader rather than left as a nested dict a person would have to parse.
    A pure rendering function: it never invents a fact `signal` does not
    already carry, and reports an absent field honestly rather than
    guessing a value for it."""
    confidence_detail = signal.get("confidence_detail") or {}
    level = confidence_detail.get("level", "LOW")
    score = confidence_detail.get("score")
    capped = confidence_detail.get("capped_by_counter_evidence")
    gap = signal.get("gap") or []
    stage = signal.get("stage", "?")
    context_path = signal.get("context_path")
    reason = signal.get("reason", "")

    lines: List[str] = []
    lines.append(f"Stage: {stage}")
    if context_path:
        lines.append(f"Evidence path: {context_path}")
    lines.append(
        f"Confidence: {level}" + (f" (score={score})" if score is not None else "")
    )
    if capped:
        lines.append(
            "Note: this score was capped by unresolved counter-evidence "
            "(score_confidence()'s own capped_by_counter_evidence flag)."
        )
    if gap:
        lines.append("Gap (missing evidence categories): " + ", ".join(gap))
    else:
        lines.append("Gap: none reported by identify_gap() for this attempt.")
    lines.append(f"Why this checkpoint fired: {reason}")
    return "\n".join(lines)


def build_low_confidence_checkpoint_question_key(
    stage: str, context_path: Optional[str], gap: Optional[List[str]]
) -> str:
    """Stable across retries of the SAME investigation (same stage, same
    evidence path, same missing-evidence categories) so re-computing an
    unchanged LOW-confidence signal on a stage retry never mints a second,
    duplicate blocking question -- see `file_low_confidence_checkpoint()`'s
    own dedup-before-add check, mirroring `source_authority.escalate_
    conflict()`'s identical, already-established discipline."""
    gap_key = ",".join(sorted(gap)) if gap else ""
    return _qq.make_question_key(
        DOMAIN,
        f"low_confidence_checkpoint:{stage}",
        f"{context_path or stage}|gap={gap_key}",
    )


def file_low_confidence_checkpoint(
    store: Union["_qq.QuestionQueueStore", str, Path],
    stage: str,
    step_inference: Dict[str, Any],
    *,
    context_path: Optional[str] = None,
    now=None,
) -> Optional[Dict[str, Any]]:
    """The one entry point. Reuses `inference.build_deeper_investigation_
    signal()` to decide whether a checkpoint is warranted at all -- only a
    real LOW `confidence_detail` warrants one; every other outcome returns
    `None`, the identical "an absent finding is a real answer, not an
    error" convention the agent-facing signal itself already follows (see
    `engine._record_agent_escalation_signal()`'s own docstring).

    When warranted, files (or returns an already-filed, still-live) real
    Tier-3 blocking question through `QuestionQueueStore.add_question()`,
    carrying the full rendered reasoning chain (`render_reasoning_chain()`)
    in the question text so a human reads the Hypothesis/Evidence/
    Confidence/Gap chain BEFORE answering "proceed?".

    `store` may be an already-constructed `QuestionQueueStore` or a
    project-root path (the same convenience `source_authority.escalate_
    conflict()` already offers, so callers accept either interchangeably).

    Returns `None` when no checkpoint was warranted; the persisted (or
    already-live) question record otherwise. Deliberately raises rather
    than swallowing an error -- unlike `engine._record_agent_escalation_
    signal()`'s own best-effort wrapping, a failure to file a genuinely
    warranted human checkpoint must be loud at THIS layer; a caller
    wrapping this call at the engine's own per-attempt hot path is
    responsible for its own best-effort discipline, matching every sibling
    `_record_*`/`_file_*` method in `engine.py`."""
    confidence_detail = (
        step_inference.get("confidence_detail") if isinstance(step_inference, dict) else None
    )
    if not isinstance(confidence_detail, dict):
        return None

    gap = step_inference.get("gap") if isinstance(step_inference, dict) else None
    signal = inference.build_deeper_investigation_signal(
        confidence_detail, stage=stage, context_path=context_path, gap=gap
    )
    if signal is None:
        return None

    if isinstance(store, (str, Path)):
        store = _qq.QuestionQueueStore(Path(store))

    question_key = build_low_confidence_checkpoint_question_key(
        stage, context_path, signal.get("gap")
    )

    # Dedup on question_key BEFORE adding -- see this module's own docstring
    # for why (source_authority.escalate_conflict()'s identical discipline,
    # reused here rather than re-derived differently).
    for existing in store.list_questions():
        if existing.get("question_key") == question_key:
            return existing

    reasoning_chain = render_reasoning_chain(signal)
    question_text = (
        f"Low-confidence checkpoint at stage {stage}: this agent's own "
        f"mid-investigation self-assessment (score_confidence()) landed "
        f"LOW. Review the reasoning chain below before this conclusion is "
        f"acted on and reported.\n\n{reasoning_chain}"
    )

    return store.add_question(
        domain=DOMAIN,
        question=question_text,
        context_path=context_path or f"stage:{stage}",
        options=[OPTION_PROCEED, OPTION_INVESTIGATE_FURTHER],
        recommendation=OPTION_INVESTIGATE_FURTHER,
        assumption_if_unanswered=(
            "No default action is taken -- this is a real Tier-3 blocking "
            "checkpoint (CANNOT_ASSUME); the question stays OPEN pending a "
            "real human answer, never an auto-assumed default."
        ),
        question_key=question_key,
        context=dict(CHECKPOINT_CONTEXT),
        now=now,
    )
