"""dv_harness/session_question_sequencer.py -- a SESSION-LEVEL question-order
strategy sitting one layer above `dv_harness/intake_question_priority.py`'s
per-question NEXT-BEST-QUESTION ranking.

WHY THIS MODULE EXISTS (the gap it closes)
-------------------------------------------
`intake_question_priority.rank_questions()` scores each pending question in
isolation -- `blocking_value * downstream_impact * expected_confidence_gain /
user_effort` -- and sorts the WHOLE batch by that one number. It never asks a
different, real question a human staring at a pile of five pending questions
actually has: "if I answer THIS one first, does that make several of the
OTHERS unnecessary?" A question whose own per-question score is merely
middling can still be the single best one to ask FIRST if answering it is
expected to let two or three other pending questions self-resolve (skip
being asked at all, e.g. via `question_queue.py`'s own Tier-1 self-resolve
path) -- pure per-question ranking has no way to express that, because it
never looks at relationships BETWEEN questions at all.

This module adds exactly that missing layer -- a SESSION-LEVEL sequencer --
and nothing else. It never re-derives `rank_questions()`'s own scoring
formula: every per-question score used here is read straight out of that
function's real return value (or a caller-supplied ranking result computed
by it), per this task's own instruction to reuse those scores as input
rather than re-deriving them.

WHY THIS DOES NOT IMPORT question_queue.py
-------------------------------------------
Same reasoning `intake_question_priority.py`'s own module docstring already
gives for itself, extended one layer up: pending-question data arrives as a
generic list of dicts, so this module can be exercised against ANY caller's
notion of a "pending question" without coupling to `question_queue.py`'s own
schema or file-locking semantics. A question's expectation that answering it
would let other pending questions self-resolve is read from a caller-
declared field (`unlocks` / `downstream_unlocks` / `expected_unlocks` -- the
first present of the three, mirroring `intake_question_priority._TOPIC_FIELDS`'s
own "try several real field-name spellings, never guess a relationship" con
vention). This module NEVER infers that a question would unlock another one
from the two questions' own content, topic, or wording -- that would be
exactly the invented relatedness `intake_question_priority.
build_question_batches()`'s own docstring already refuses to guess for
topic-based batching, applied here to a stronger, more consequential claim
(a whole other pending question becoming unnecessary).

THE ALGORITHM
--------------
1. `build_unlock_graph()` turns every question's own declared unlock list
   into a directed edge (question_id -> unlocked_question_id), validated
   against the real batch: a declared target absent from the batch is never
   silently counted -- it is reported as an `UNKNOWN_UNLOCK_TARGET` finding
   and excluded from the graph, and a question declaring itself as its own
   unlock target is reported `SELF_UNLOCK_IGNORED` and likewise excluded.
   Both are this module's own negative-control-worthy refusal to fabricate a
   downstream-impact claim the caller's own data does not actually support.
2. `compute_downstream_reach()` walks that graph breadth-first from every
   question to the full set of OTHER questions transitively reachable via
   declared unlock edges -- a real, finite computation even over a graph
   containing a cycle (A unlocks B, B unlocks A): a visited-set BFS can never
   loop forever and a cycle collapses to exactly the reachable set it really
   describes, never a double-counted or fabricated larger one.
3. `sequence_questions()` reuses `intake_question_priority.rank_questions()`
   (or a caller-supplied ranking result already computed by it) for every
   question's own per-question score, then orders the WHOLE batch by:
   `(downstream_reach_count DESC, has_a_real_score, base_score DESC,
   question_id ASC)`. Downstream reach is the PRIMARY key -- this is the
   "unblock the maximum downstream work first" strategy the task names --
   and the reused per-question score is the tie-break among questions that
   would unlock an equal number of others. A question `rank_questions()`
   itself could not score at all (a missing/invalid factor) is never
   silently dropped or given a fabricated numeric score to sort by: it stays
   in the sequence, carrying its own real UNVERIFIABLE reason, and -- because
   its true utility is genuinely unknown rather than known-to-be-zero -- it
   is placed AFTER every equally-reach-count question that DOES carry a real
   score, never ahead of one and never silently treated as worthless either.

WHAT THIS MODULE DOES NOT DO
-------------------------------
It reads no file, writes no state, files no question, answers no question,
gates nothing (Tier/ask-vs-do-not-ask stays `intake_question_priority.
gate_pending_questions()`'s own job, reused verbatim by
`sequence_session_queue()` below), batches nothing (that stays
`build_question_batches()`'s own job), and invents no relationship between
two questions the caller did not itself declare.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from dv_harness import intake_question_priority as iqp

# ===========================================================================
# ID assignment -- mirrors intake_question_priority._question_id() exactly,
# re-derived locally (rather than importing that module's own private
# helper) per this project's own established convention of each module
# owning its own small, deterministic, independently-testable helper. This
# MUST stay byte-for-byte identical to that function's own logic, since this
# module correlates its own graph nodes against rank_questions()'s own
# assigned question_ids by string equality -- proven by a dedicated test.
# ===========================================================================

def _question_id(question: Mapping[str, Any], index: int) -> str:
    for key in ("question_id", "id", "q_id"):
        value = question.get(key)
        if value:
            return str(value)
    return f"q{index}"


_UNLOCK_FIELDS: Tuple[str, ...] = ("unlocks", "downstream_unlocks", "expected_unlocks")


def _declared_unlocks(question: Mapping[str, Any]) -> List[str]:
    """The first present of the caller-declared unlock-list field spellings,
    normalized to a list of strings. Never inferred from the question's own
    content -- an absent field means an honestly empty declared-unlock list,
    not a guessed one."""
    for key in _UNLOCK_FIELDS:
        value = question.get(key)
        if value:
            if isinstance(value, (list, tuple, set)):
                return [str(v) for v in value]
            return [str(value)]
    return []


FINDING_UNKNOWN_UNLOCK_TARGET = "UNKNOWN_UNLOCK_TARGET"
FINDING_SELF_UNLOCK_IGNORED = "SELF_UNLOCK_IGNORED"


# ===========================================================================
# The downstream-unlock graph
# ===========================================================================

def build_unlock_graph(questions: Sequence[Mapping[str, Any]],
                        ids: Optional[Sequence[str]] = None
                        ) -> Tuple[Dict[str, List[str]], List[Dict[str, str]]]:
    """Builds a directed adjacency map (question_id -> [unlocked question_id,
    ...]) purely from each question's own declared unlock field, validated
    against the real question_ids present in this batch. Returns (graph,
    findings). `findings` names every declared-but-unusable edge -- a target
    not present in the batch, or a question naming itself -- so an
    unsupportable claim is reported rather than silently dropped OR silently
    counted."""
    questions = list(questions or [])
    if ids is None:
        ids = [_question_id(q or {}, i) for i, q in enumerate(questions)]
    else:
        ids = list(ids)
    id_set = set(ids)
    graph: Dict[str, List[str]] = {qid: [] for qid in ids}
    findings: List[Dict[str, str]] = []
    for qid, raw in zip(ids, questions):
        q = raw or {}
        seen: set = set()
        for target in _declared_unlocks(q):
            if target == qid:
                findings.append({
                    "question_id": qid, "kind": FINDING_SELF_UNLOCK_IGNORED,
                    "detail": f"question {qid!r} declares itself as an unlock target -- "
                              f"ignored (a question cannot unlock itself)",
                })
                continue
            if target not in id_set:
                findings.append({
                    "question_id": qid, "kind": FINDING_UNKNOWN_UNLOCK_TARGET,
                    "detail": f"question {qid!r} declares unlock target {target!r}, which is "
                              f"not present in this batch -- not counted toward downstream reach",
                })
                continue
            if target in seen:
                continue
            seen.add(target)
            graph[qid].append(target)
    return graph, findings


def compute_downstream_reach(graph: Mapping[str, Sequence[str]]) -> Dict[str, FrozenSet[str]]:
    """For every node, the full set of OTHER nodes transitively reachable via
    declared unlock edges, computed by a visited-set breadth-first search --
    safe against a cycle (A unlocks B, B unlocks A) by construction: `start`
    is never re-added once visited, so a cycle collapses to the real,
    finite reachable set it describes rather than looping forever or being
    double-counted."""
    reach: Dict[str, FrozenSet[str]] = {}
    for start in graph:
        visited: set = set()
        queue: deque = deque(graph.get(start, []))
        while queue:
            node = queue.popleft()
            if node == start or node in visited:
                continue
            visited.add(node)
            queue.extend(graph.get(node, []))
        reach[start] = frozenset(visited)
    return reach


# ===========================================================================
# Session-level sequencing
# ===========================================================================

def sequence_questions(questions: Sequence[Mapping[str, Any]], *,
                        ranking: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Orders `questions` (generic dicts -- see module docstring) to unblock
    the maximum downstream work first. `ranking`, when supplied, MUST be a
    result already produced by `intake_question_priority.rank_questions()`
    over this exact `questions` list (in this exact order) -- the shape
    `sequence_session_queue()` below passes through from `analyze_pending_
    questions()`'s own already-computed ranking, so no score is ever
    computed twice. Omitting it calls `rank_questions()` here, once, for the
    same reuse guarantee."""
    questions = list(questions or [])
    ids = [_question_id(q or {}, i) for i, q in enumerate(questions)]

    if ranking is None:
        ranking = iqp.rank_questions(questions)

    score_by_id: Dict[str, float] = {}
    for entry in ranking.get("ranked") or []:
        score_by_id[entry["question_id"]] = entry["score"]
    reason_by_id: Dict[str, str] = {}
    for entry in ranking.get("unrankable") or []:
        reason_by_id[entry["question_id"]] = entry["reason"]

    graph, findings = build_unlock_graph(questions, ids)
    reach = compute_downstream_reach(graph)

    entries: List[Dict[str, Any]] = []
    for qid in ids:
        score = score_by_id.get(qid)
        reachable = reach.get(qid, frozenset())
        entries.append({
            "question_id": qid,
            "downstream_reach_count": len(reachable),
            "downstream_unlocks": sorted(reachable),
            "base_score": score,
            "base_score_status": (iqp.SCORE_STATUS_SCORED if score is not None
                                   else iqp.SCORE_STATUS_UNVERIFIABLE),
            "base_score_reason": reason_by_id.get(qid),
        })

    # Primary: unblock the most downstream work first. Tie-break: a real
    # reused score outranks an honestly-unknown one; among two real scores,
    # the higher one goes first; final tie-break is the question_id itself,
    # so the sequence is fully deterministic regardless of input order.
    entries.sort(key=lambda e: (
        -e["downstream_reach_count"],
        0 if e["base_score"] is not None else 1,
        -(e["base_score"] if e["base_score"] is not None else 0.0),
        e["question_id"],
    ))
    for position, entry in enumerate(entries, start=1):
        entry["sequence_position"] = position

    return {
        "sequence": entries,
        "unlock_graph_findings": findings,
        "total_questions": len(entries),
        "first_question_id": entries[0]["question_id"] if entries else None,
    }


def sequence_session_queue(questions: Sequence[Mapping[str, Any]], *,
                            max_batch_size: Optional[int] = None) -> Dict[str, Any]:
    """The full-pipeline convenience entry point: runs `intake_question_
    priority.analyze_pending_questions()` (gate -> rank -> batch, all reused
    verbatim, none of it re-derived here) and then sequences the SAME
    to-ask subset using that call's own already-computed ranking. A
    DO_NOT_ASK question is never sequenced, exactly as it is never ranked or
    batched by the reused pipeline."""
    report = iqp.analyze_pending_questions(questions, max_batch_size=max_batch_size)

    by_id = {_question_id((q or {}), i): (q or {}) for i, q in enumerate(questions or [])}
    to_ask_questions: List[Dict[str, Any]] = []
    for qid in report["gating"]["to_ask"]:
        q = dict(by_id[qid])
        q.setdefault("question_id", qid)
        to_ask_questions.append(q)

    sequencing = sequence_questions(to_ask_questions, ranking=report["ranking"])

    return {
        "gating": report["gating"],
        "ranking": report["ranking"],
        "batching": report["batching"],
        "sequencing": sequencing,
    }


# ===========================================================================
# Rendering + shared CLI front door
# ===========================================================================

def render_report_text(report: Mapping[str, Any]) -> str:
    lines = ["SESSION-LEVEL QUESTION-ORDER STRATEGY", ""]
    gating = report.get("gating") or {}
    lines.append(f"gating: {len(gating.get('to_ask') or [])} to ask, "
                 f"{len(gating.get('do_not_ask') or [])} do-not-ask "
                 f"(of {gating.get('total', 0)} total)")
    seq = report.get("sequencing") or {}
    lines.append(f"sequence: {seq.get('total_questions', 0)} question(s) ordered, "
                 f"first_question_id={seq.get('first_question_id')!r}")
    for e in seq.get("sequence") or []:
        if e["base_score"] is not None:
            score_txt = f"{e['base_score']:.4g}"
        else:
            score_txt = f"UNVERIFIABLE ({e['base_score_reason']})"
        unlocks_txt = ", ".join(e["downstream_unlocks"]) or "none"
        lines.append(f"  #{e['sequence_position']} {e['question_id']}: "
                     f"unlocks={e['downstream_reach_count']} downstream ({unlocks_txt}), "
                     f"score={score_txt}")
    findings = seq.get("unlock_graph_findings") or []
    if findings:
        lines.append(f"unlock graph findings ({len(findings)}):")
        for f in findings:
            lines.append(f"  [{f['kind']}] {f['detail']}")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(pending_questions_path, *, max_batch_size: Optional[int] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.session_question_sequencer`
    (no `dv-harness` CLI verb was wired -- per this batch's own file-safety
    scope, `cli.py` must never be edited here). Returns (text, exit_code):
    0 if every pending question was gated/ranked/sequenced cleanly (no
    unrankable question, no unlock-graph finding), 1 if either exists,
    2 on a usage error."""
    questions = _load_json(pending_questions_path)
    if not isinstance(questions, list):
        return (json.dumps({"error": "PENDING_QUESTIONS_MUST_BE_A_JSON_ARRAY"})
                if as_json else "pending questions file must contain a JSON array"), 2
    report = sequence_session_queue(questions, max_batch_size=max_batch_size)
    text = json.dumps(report, indent=2) if as_json else render_report_text(report)
    has_issue = bool(report["ranking"]["unrankable"]) or bool(
        report["sequencing"]["unlock_graph_findings"])
    code = 1 if has_issue else 0
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.session_question_sequencer",
        description="Orders a whole session's pending-question queue to unblock the maximum "
                    "downstream work first, reusing intake_question_priority.py's own "
                    "gate/rank/batch pipeline and per-question scores as input.")
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
