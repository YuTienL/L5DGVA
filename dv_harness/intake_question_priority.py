"""dv_harness/intake_question_priority.py -- three related, small mechanisms
for deciding what to ask a human during intake, and how: (a) a Confidence x
Criticality GATING TABLE deciding whether a pending question is even worth
asking, (b) a NEXT-BEST-QUESTION ranking over the questions that ARE worth
asking, and (c) a BATCHING rule that groups closely-related LOW-risk
questions into one round while never merging an architecture-defining/
high-risk question with anything else.

WHY THIS DOES NOT IMPORT question_queue.py
-------------------------------------------
`question_queue.py` already owns the real 3-tier (self-resolve / auto-assume
/ blocking) ask-a-human queue, its own `QuestionQueueStore`, its own Tier
classifier (`classify_tier()`), and its own digest/metrics machinery. This
module's task was explicitly scoped to NOT import it: pending-question data
arrives as a generic list of dicts, so this module can be exercised (and
reused) against ANY caller's notion of a "pending question" -- a
`question_queue.py` record, a plain planning ticket, a research candidate's
open item -- without coupling to that module's schema or its `QuestionQueue
Store` file-locking semantics. Every fact this module needs about a question
(its confidence, its criticality, its four ranking factors, its declared
topic/relatedness key, whether it is architecture-defining) is read directly
off the caller-supplied dict; nothing here re-derives, re-classifies, or
second-guesses a fact `question_queue.py` (or any other real producer) would
otherwise be the authority on. Per this batch's own file-safety scope, no
other module's vocabulary was imported either -- every constant below is
defined fresh in this file.

(a) THE CONFIDENCE x CRITICALITY GATING TABLE
-----------------------------------------------
Two independent axes, each with a fourth "we do not honestly know" value so
an absent or unrecognized fact is never silently guessed into a numeric
axis: CONFIDENCE_LEVELS = (LOW, MEDIUM, HIGH, UNKNOWN) -- how sure the
harness already is about the answer it would otherwise assume; and
CRITICALITY_LEVELS = (MINOR, MAJOR, BLOCKER, UNKNOWN) -- how much getting it
wrong would cost (BLOCKER = architecture-defining / highest-risk, per this
task's own vocabulary). That is 16 explicit cells, not a formula computed at
call time: `GATING_TABLE` below spells out every one of them by hand,
because a computed risk score can silently drift as thresholds are tuned
while an explicit table cannot -- a reviewer can read every cell and its
reason directly.

The table's only two DO_NOT_ASK-eligible axis values are HIGH confidence
paired with MINOR or MAJOR criticality (both "non-critical", the task's own
worked example: "HIGH confidence + non-critical -> do not ask"). Every other
cell -- including MEDIUM confidence + BLOCKER criticality, the task's other
worked example ("MEDIUM confidence + critical -> ask") -- is ASK. Two
deliberate asymmetries carry real weight, not filler: (1) BLOCKER
criticality is ASK at every confidence level including HIGH -- an
architecture-defining decision is confirmed regardless of how sure the
harness already is, the same "a human decides regardless of confidence"
posture `connectivity.py`'s Bind-Location Tier 3/4 rules and
`qualified_conclusion.py`'s closure gate already take for their own
highest-stakes cases. (2) An UNKNOWN value on EITHER axis is always ASK,
never averaged toward the middle or defaulted to the more common case: an
unclassified criticality must never be read as evidence the item is safe to
skip, and an unclassified confidence must never be read as evidence the
harness is sure.

(b) NEXT-BEST-QUESTION RANKING
--------------------------------
`score_question()` computes exactly the formula this task names --
`blocking_value * downstream_impact * expected_confidence_gain /
user_effort` -- over four caller-supplied numeric factors, and does nothing
else. It does not invent how any of the four is measured (per this task's
own instruction); a factor's real meaning and unit are entirely the
caller's, this module only multiplies and divides the numbers it is handed.
A missing factor, a non-numeric one, a negative `blocking_value`/
`downstream_impact`/`expected_confidence_gain`, or a `user_effort` that is
not strictly positive (the denominator: zero or negative would either
divide-by-zero or invert the ranking's meaning) all report `UNVERIFIABLE`
with the real missing/invalid field named, rather than substituting a
placeholder number and silently producing a confident-looking score.
`rank_questions()` scores every question in a list and returns the scorable
ones sorted by score descending (ties broken by a stable, deterministic
question-id sort, never by input order alone) alongside the unrankable ones
with their real reasons -- an unrankable question is reported, never
dropped silently.

(c) BATCHING: GROUP LOW-RISK, NEVER GROUP HIGH-RISK
------------------------------------------------------
`classify_batch_risk()` decides, per question, whether it may ever be
batched with another question at all. Only a question whose declared
`criticality` is exactly MINOR (and which does not separately declare
`architecture_defining: true`) is LOW risk and batchable. BLOCKER
criticality, an explicit `architecture_defining: true` flag, MAJOR
criticality, and an absent/unrecognized criticality are ALL treated as HIGH
risk for batching purposes and are always placed in their own solo batch --
deliberately more conservative than the ask-gating table's own MAJOR
handling, because batching several questions into one round changes what a
human actually reads together, and only an explicitly-declared MINOR fact
is strong enough evidence to license that. `build_question_batches()` then
groups the LOW-risk questions by a caller-declared relatedness key (the
first present of `topic` / `related_topic` / `related_group` / `group_key`
on each question dict -- never an inferred/NLP-derived similarity, which
this module does not attempt) into one batch per distinct key, splitting an
oversized group deterministically when `max_batch_size` is given; a
LOW-risk question with no declared relatedness key gets its own singleton
batch too, since nothing here invents a relationship the caller did not
state. Every HIGH-risk question always lands in a batch of exactly one,
whatever its topic -- the property the task's own "NEVER batches an
architecture-defining/high-risk question with anything else" rule demands,
and it is asserted directly by this module's own tests.

WHAT THIS MODULE DOES NOT DO
-------------------------------
It reads no file, writes no state, files no question, answers no question,
runs no build/regression/LSF job, and touches no approval/governance
mechanism. It computes three real-but-small decisions over data the caller
supplies and nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ===========================================================================
# Shared vocabulary (self-contained -- nothing imported from any other
# dv_harness module, per this batch's file-safety scope)
# ===========================================================================

CONFIDENCE_LEVELS: Tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "UNKNOWN")
CRITICALITY_LEVELS: Tuple[str, ...] = ("MINOR", "MAJOR", "BLOCKER", "UNKNOWN")

DECISION_ASK = "ASK"
DECISION_DO_NOT_ASK = "DO_NOT_ASK"

BATCH_RISK_LOW = "LOW"
BATCH_RISK_HIGH = "HIGH"

SCORE_STATUS_SCORED = "SCORED"
SCORE_STATUS_UNVERIFIABLE = "UNVERIFIABLE"

REQUIRED_SCORE_FACTORS: Tuple[str, ...] = (
    "blocking_value", "downstream_impact", "expected_confidence_gain", "user_effort",
)


class IntakeQuestionPriorityError(ValueError):
    """A malformed input this module refuses to guess through -- an
    unrecognized top-level shape, never a bad-but-honestly-reported per-item
    value (those are reported inline as UNKNOWN/UNVERIFIABLE instead)."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


def _question_id(question: Mapping[str, Any], index: int) -> str:
    for key in ("question_id", "id", "q_id"):
        value = question.get(key)
        if value:
            return str(value)
    return f"q{index}"


def _normalize_axis_value(value: Any, levels: Sequence[str]) -> Tuple[str, bool]:
    """Uppercases/strips `value` and checks it against `levels`. Returns
    (level, recognized). A missing, blank, or unrecognized value normalizes
    to the axis's own "UNKNOWN" member with `recognized=False` -- an honest
    "we do not know" rather than a guessed default, never raised as an
    error, since an unrecognized value is exactly the circumstance the
    UNKNOWN cell of the gating table exists to catch."""
    if value is None:
        return "UNKNOWN", False
    text = str(value).strip().upper()
    if not text:
        return "UNKNOWN", False
    if text in levels:
        return text, True
    return "UNKNOWN", False


def normalize_confidence(value: Any) -> Tuple[str, bool]:
    """See `_normalize_axis_value`. Public so a caller can check how a raw
    confidence value would be read before it reaches the gating table."""
    return _normalize_axis_value(value, CONFIDENCE_LEVELS)


def normalize_criticality(value: Any) -> Tuple[str, bool]:
    """See `_normalize_axis_value`."""
    return _normalize_axis_value(value, CRITICALITY_LEVELS)


# ===========================================================================
# (a) Confidence x Criticality gating table -- 16 explicit cells, never a
# computed risk score. Keyed (confidence, criticality) -> (decision, reason).
# ===========================================================================

GATING_TABLE: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("LOW", "MINOR"): (DECISION_ASK,
        "LOW confidence: even a MINOR-consequence guess is too likely to be wrong to skip confirming"),
    ("LOW", "MAJOR"): (DECISION_ASK,
        "LOW confidence and MAJOR consequence-of-error -- ask"),
    ("LOW", "BLOCKER"): (DECISION_ASK,
        "LOW confidence and BLOCKER (architecture-defining) consequence-of-error -- ask"),
    ("LOW", "UNKNOWN"): (DECISION_ASK,
        "LOW confidence and an unclassified criticality -- an unclassified consequence is never "
        "treated as evidence it is safe to skip"),

    ("MEDIUM", "MINOR"): (DECISION_DO_NOT_ASK,
        "MEDIUM confidence is enough tolerance for a MINOR-consequence item -- do not ask"),
    ("MEDIUM", "MAJOR"): (DECISION_ASK,
        "MEDIUM confidence is not enough certainty for a MAJOR-consequence item -- ask"),
    ("MEDIUM", "BLOCKER"): (DECISION_ASK,
        "MEDIUM confidence and BLOCKER (architecture-defining) consequence-of-error -- ask "
        "(this task's own worked example)"),
    ("MEDIUM", "UNKNOWN"): (DECISION_ASK,
        "MEDIUM confidence and an unclassified criticality -- ask"),

    ("HIGH", "MINOR"): (DECISION_DO_NOT_ASK,
        "HIGH confidence and non-critical (MINOR) consequence-of-error -- do not ask "
        "(this task's own worked example)"),
    ("HIGH", "MAJOR"): (DECISION_DO_NOT_ASK,
        "HIGH confidence and non-critical (MAJOR is still not BLOCKER) consequence-of-error -- "
        "do not ask"),
    ("HIGH", "BLOCKER"): (DECISION_ASK,
        "BLOCKER (architecture-defining) consequence-of-error is confirmed regardless of "
        "confidence -- ask even at HIGH confidence"),
    ("HIGH", "UNKNOWN"): (DECISION_ASK,
        "HIGH confidence does not offset an unclassified criticality -- an unclassified "
        "consequence is never treated as evidence it is safe to skip -- ask"),

    ("UNKNOWN", "MINOR"): (DECISION_ASK,
        "an unclassified confidence is never treated as evidence the harness is sure -- ask"),
    ("UNKNOWN", "MAJOR"): (DECISION_ASK,
        "unclassified confidence and MAJOR consequence-of-error -- ask"),
    ("UNKNOWN", "BLOCKER"): (DECISION_ASK,
        "unclassified confidence and BLOCKER (architecture-defining) consequence-of-error -- ask"),
    ("UNKNOWN", "UNKNOWN"): (DECISION_ASK,
        "both axes unclassified -- ask"),
}


def _assert_gating_table_complete() -> None:
    """Every (confidence, criticality) pair must have an explicit cell --
    a missing cell would make `gate_question()` raise on a value this
    module's own vocabulary declares legal."""
    missing = [(c, k) for c in CONFIDENCE_LEVELS for k in CRITICALITY_LEVELS
               if (c, k) not in GATING_TABLE]
    if missing:
        raise AssertionError(f"GATING_TABLE is missing cells: {missing}")
    bad_decisions = [key for key, (decision, _r) in GATING_TABLE.items()
                     if decision not in (DECISION_ASK, DECISION_DO_NOT_ASK)]
    if bad_decisions:
        raise AssertionError(f"GATING_TABLE has non-ASK/DO_NOT_ASK decisions: {bad_decisions}")


_assert_gating_table_complete()


def gate_question(confidence: Any, criticality: Any) -> Dict[str, Any]:
    """The ask/do-not-ask decision for one (confidence, criticality) pair,
    per `GATING_TABLE`. Raw values are normalized first (see
    `normalize_confidence`/`normalize_criticality`), so an unrecognized or
    absent value reads as that axis's own UNKNOWN member rather than
    raising -- the UNKNOWN row/column is exactly how this table already
    handles that case."""
    norm_confidence, confidence_recognized = normalize_confidence(confidence)
    norm_criticality, criticality_recognized = normalize_criticality(criticality)
    decision, reason = GATING_TABLE[(norm_confidence, norm_criticality)]
    return {
        "confidence_input": confidence,
        "criticality_input": criticality,
        "confidence": norm_confidence,
        "criticality": norm_criticality,
        "confidence_recognized": confidence_recognized,
        "criticality_recognized": criticality_recognized,
        "decision": decision,
        "reason": reason,
    }


def gate_pending_questions(questions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Runs `gate_question()` over a whole pending-question list (generic
    dicts -- see module docstring). Each entry reads its own `confidence`
    and `criticality` fields; a question dict missing either field gates on
    UNKNOWN for that axis, which this table always resolves to ASK for a
    missing/unrecognized criticality (see GATING_TABLE), so a question that
    never declared its own risk is never silently skipped."""
    results: List[Dict[str, Any]] = []
    to_ask: List[str] = []
    do_not_ask: List[str] = []
    for i, raw in enumerate(questions or []):
        q = raw or {}
        qid = _question_id(q, i)
        gate = gate_question(q.get("confidence"), q.get("criticality"))
        gate["question_id"] = qid
        results.append(gate)
        (to_ask if gate["decision"] == DECISION_ASK else do_not_ask).append(qid)
    return {
        "gated": results,
        "to_ask": to_ask,
        "do_not_ask": do_not_ask,
        "total": len(results),
    }


# ===========================================================================
# (b) Next-best-question ranking
# ===========================================================================

def score_question(factors: Mapping[str, Any]) -> Dict[str, Any]:
    """`blocking_value * downstream_impact * expected_confidence_gain /
    user_effort`, over exactly the four caller-supplied factors this task
    names -- nothing here measures or invents any of the four. Missing,
    non-numeric, or out-of-range inputs (a negative blocking_value/
    downstream_impact/expected_confidence_gain, or a user_effort that is
    not strictly positive) report SCORE_STATUS_UNVERIFIABLE naming the real
    problem field rather than substituting a placeholder number."""
    values: Dict[str, float] = {}
    for name in REQUIRED_SCORE_FACTORS:
        if name not in factors or factors.get(name) is None:
            return {"status": SCORE_STATUS_UNVERIFIABLE, "score": None,
                    "reason": f"required factor '{name}' was not supplied", "factors": dict(factors)}
        raw = factors.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return {"status": SCORE_STATUS_UNVERIFIABLE, "score": None,
                    "reason": f"factor '{name}' is not numeric (got {raw!r})",
                    "factors": dict(factors)}
        values[name] = float(raw)

    for name in ("blocking_value", "downstream_impact", "expected_confidence_gain"):
        if values[name] < 0:
            return {"status": SCORE_STATUS_UNVERIFIABLE, "score": None,
                    "reason": f"factor '{name}' is negative ({values[name]}) -- not a valid weight",
                    "factors": dict(factors)}
    if values["user_effort"] <= 0:
        return {"status": SCORE_STATUS_UNVERIFIABLE, "score": None,
                "reason": f"factor 'user_effort' must be strictly positive "
                          f"(got {values['user_effort']}) -- it is the divisor",
                "factors": dict(factors)}

    score = (values["blocking_value"] * values["downstream_impact"]
             * values["expected_confidence_gain"] / values["user_effort"])
    return {"status": SCORE_STATUS_SCORED, "score": score, "reason": None,
            "factors": dict(factors)}


def rank_questions(questions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Scores every question in `questions` (generic dicts, each read for
    its own `blocking_value`/`downstream_impact`/`expected_confidence_gain`/
    `user_effort`) and returns the scorable ones sorted by score descending.
    Ties are broken by question id ascending, so ranking output is
    deterministic across runs regardless of input ordering. An unrankable
    question is reported in `unrankable` with its real reason -- never
    dropped, and never merged into the ranked list with a fabricated score.
    """
    ranked: List[Dict[str, Any]] = []
    unrankable: List[Dict[str, Any]] = []
    for i, raw in enumerate(questions or []):
        q = raw or {}
        qid = _question_id(q, i)
        result = score_question(q)
        if result["status"] == SCORE_STATUS_SCORED:
            ranked.append({"question_id": qid, "score": result["score"],
                           "factors": result["factors"]})
        else:
            unrankable.append({"question_id": qid, "reason": result["reason"],
                               "factors": result["factors"]})
    ranked.sort(key=lambda r: (-r["score"], r["question_id"]))
    for position, entry in enumerate(ranked, start=1):
        entry["rank"] = position
    return {
        "ranked": ranked,
        "unrankable": unrankable,
        "next_best_question_id": ranked[0]["question_id"] if ranked else None,
    }


# ===========================================================================
# (c) Batching: group LOW-risk, never group HIGH-risk
# ===========================================================================

_TOPIC_FIELDS: Tuple[str, ...] = ("topic", "related_topic", "related_group", "group_key")


def _topic_of(question: Mapping[str, Any]) -> Optional[str]:
    for key in _TOPIC_FIELDS:
        value = question.get(key)
        if value:
            return str(value)
    return None


def classify_batch_risk(question: Mapping[str, Any]) -> Tuple[str, str]:
    """Whether `question` may EVER be merged into a batch with another
    question. Returns (BATCH_RISK_LOW | BATCH_RISK_HIGH, reason).

    Only a question whose declared `criticality` is exactly MINOR, and
    which does not separately declare `architecture_defining: true`, is
    LOW risk. BLOCKER criticality, an explicit `architecture_defining:
    true` flag, MAJOR criticality, and an absent/unrecognized criticality
    are ALL HIGH risk for batching purposes -- deliberately stricter than
    the ask-gating table's own MAJOR handling, because grouping several
    questions into one round changes what a human reads together, and only
    an explicitly-declared MINOR fact is strong enough evidence to license
    that."""
    if question.get("architecture_defining") is True:
        return BATCH_RISK_HIGH, "declared architecture_defining=true -- never batched with anything else"
    criticality, recognized = normalize_criticality(question.get("criticality"))
    if criticality == "BLOCKER":
        return BATCH_RISK_HIGH, "criticality BLOCKER (architecture-defining/highest risk) -- never batched"
    if criticality == "MAJOR":
        return BATCH_RISK_HIGH, "criticality MAJOR is not treated as LOW risk for batching -- only MINOR is"
    if criticality == "MINOR" and recognized:
        return BATCH_RISK_LOW, "criticality MINOR -- eligible to batch with closely-related MINOR questions"
    return BATCH_RISK_HIGH, ("criticality absent/unrecognized -- an unclassified consequence is never "
                             "treated as evidence it is safe to batch")


def build_question_batches(questions: Sequence[Mapping[str, Any]], *,
                            max_batch_size: Optional[int] = None) -> Dict[str, Any]:
    """Groups `questions` (generic dicts) into rounds. Every HIGH-risk
    question (see `classify_batch_risk`) is placed alone in its own batch,
    regardless of any declared topic -- the property this task's own
    "NEVER batches an architecture-defining/high-risk question with
    anything else" rule requires. Every LOW-risk question is grouped with
    other LOW-risk questions sharing the same caller-declared topic key
    (see `_TOPIC_FIELDS`); a LOW-risk question with no declared topic gets
    its own singleton batch too, since this module invents no relatedness
    the caller did not state. `max_batch_size`, if given, splits an
    oversized topic group into multiple batches, in original input order,
    rather than silently exceeding it."""
    if max_batch_size is not None and max_batch_size < 1:
        raise IntakeQuestionPriorityError(
            "MAX_BATCH_SIZE_MUST_BE_POSITIVE", {"max_batch_size": max_batch_size})

    solo_entries: List[Dict[str, Any]] = []
    topic_groups: Dict[str, List[Dict[str, Any]]] = {}
    topic_group_order: List[str] = []

    for i, raw in enumerate(questions or []):
        q = raw or {}
        qid = _question_id(q, i)
        risk, reason = classify_batch_risk(q)
        entry = {"question_id": qid, "risk": risk, "risk_reason": reason,
                 "topic": _topic_of(q)}
        if risk == BATCH_RISK_HIGH:
            solo_entries.append(entry)
            continue
        topic = entry["topic"]
        if topic is None:
            solo_entries.append(entry)
            continue
        if topic not in topic_groups:
            topic_groups[topic] = []
            topic_group_order.append(topic)
        topic_groups[topic].append(entry)

    batches: List[Dict[str, Any]] = []
    batch_counter = 0

    def _new_batch(entries: List[Dict[str, Any]], risk: str, topic: Optional[str]) -> Dict[str, Any]:
        nonlocal batch_counter
        batch_counter += 1
        return {
            "batch_id": f"batch-{batch_counter}",
            "risk": risk,
            "topic": topic,
            "question_ids": [e["question_id"] for e in entries],
            "size": len(entries),
        }

    for entry in solo_entries:
        batches.append(_new_batch([entry], entry["risk"], entry["topic"]))

    for topic in topic_group_order:
        entries = topic_groups[topic]
        chunk_size = max_batch_size or len(entries)
        for start in range(0, len(entries), chunk_size):
            chunk = entries[start:start + chunk_size]
            batches.append(_new_batch(chunk, BATCH_RISK_LOW, topic))

    return {
        "batches": batches,
        "total_questions": sum(b["size"] for b in batches),
        "solo_batch_count": sum(1 for b in batches if b["size"] == 1),
        "grouped_batch_count": sum(1 for b in batches if b["size"] > 1),
    }


# ===========================================================================
# Integrated pipeline + rendering + shared CLI front door
# ===========================================================================

def analyze_pending_questions(questions: Sequence[Mapping[str, Any]], *,
                               max_batch_size: Optional[int] = None) -> Dict[str, Any]:
    """Runs all three mechanisms over one pending-question list, in the
    order a caller would actually want them: gate first (drop DO_NOT_ASK),
    rank the remainder for next-best-question, then batch the remainder
    for a single round. A question this module decided DO_NOT_ASK on is
    never ranked and never batched -- there is no reason to schedule a
    question the gating table already said should not be asked."""
    gating = gate_pending_questions(questions)
    by_id = {_question_id((q or {}), i): (q or {}) for i, q in enumerate(questions or [])}
    to_ask_questions = [by_id[qid] for qid in gating["to_ask"]]
    # Re-attach ids so downstream ranking/batching agree with the gating
    # pass's own id assignment even when a question dict carries no id.
    to_ask_with_ids = []
    for qid in gating["to_ask"]:
        q = dict(by_id[qid])
        q.setdefault("question_id", qid)
        to_ask_with_ids.append(q)
    ranking = rank_questions(to_ask_with_ids)
    batching = build_question_batches(to_ask_with_ids, max_batch_size=max_batch_size)
    return {
        "gating": gating,
        "ranking": ranking,
        "batching": batching,
    }


def render_report_text(report: Mapping[str, Any]) -> str:
    lines = ["INTAKE QUESTION PRIORITY", ""]
    gating = report.get("gating") or {}
    lines.append(f"gating: {len(gating.get('to_ask') or [])} to ask, "
                 f"{len(gating.get('do_not_ask') or [])} do-not-ask "
                 f"(of {gating.get('total', 0)} total)")
    ranking = report.get("ranking") or {}
    lines.append(f"ranking: next_best_question_id={ranking.get('next_best_question_id')!r}, "
                 f"{len(ranking.get('ranked') or [])} ranked, "
                 f"{len(ranking.get('unrankable') or [])} unrankable")
    for r in ranking.get("ranked") or []:
        lines.append(f"  #{r['rank']} {r['question_id']} score={r['score']:.4g}")
    for u in ranking.get("unrankable") or []:
        lines.append(f"  UNVERIFIABLE {u['question_id']}: {u['reason']}")
    batching = report.get("batching") or {}
    lines.append(f"batching: {len(batching.get('batches') or [])} batch(es), "
                 f"{batching.get('solo_batch_count', 0)} solo, "
                 f"{batching.get('grouped_batch_count', 0)} grouped")
    for b in batching.get("batches") or []:
        lines.append(f"  [{b['batch_id']}] risk={b['risk']} topic={b['topic']!r} "
                     f"questions={b['question_ids']}")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(pending_questions_path, *, max_batch_size: Optional[int] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.intake_question_priority`
    (no `dv-harness` CLI verb was wired -- per this batch's own file-safety
    scope, `cli.py` must never be edited here). Returns (text, exit_code):
    0 if every pending question was gated/ranked/batched cleanly, 1 if any
    question is unrankable, 2 on a usage error."""
    questions = _load_json(pending_questions_path)
    if not isinstance(questions, list):
        return (json.dumps({"error": "PENDING_QUESTIONS_MUST_BE_A_JSON_ARRAY"})
                if as_json else "pending questions file must contain a JSON array"), 2
    report = analyze_pending_questions(questions, max_batch_size=max_batch_size)
    text = json.dumps(report, indent=2) if as_json else render_report_text(report)
    code = 1 if report["ranking"]["unrankable"] else 0
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.intake_question_priority",
        description="Confidence x Criticality ask-gating, next-best-question ranking, and "
                    "LOW-risk batching over a generic list of pending-question dicts.")
    ap.add_argument("--pending-questions", required=True, dest="pending_questions_path",
                    help="Path to a JSON array of pending-question dicts.")
    ap.add_argument("--max-batch-size", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.pending_questions_path, max_batch_size=a.max_batch_size,
                              as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
