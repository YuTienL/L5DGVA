"""dv_harness/answer_inconsistency_fatigue_detection.py -- detects a contradictory or
degrading-quality answer pattern across ONE intake session's real sequence of answers,
and offers (never forces) a save-and-resume checkpoint through intake_baseline.py's
existing, unmodified freeze mechanism.

THE GAP THIS CLOSES. Nothing in this repo looked at a whole intake SESSION's worth of
answers together. `user_answer_validator.py` checks exactly one raw answer against real
evidence at a time and reports VALIDATED / PARTIALLY_VALIDATED / CONTRADICTED /
UNVERIFIABLE -- a real, per-answer signal, but it has no notion of a SEQUENCE: an agent
(or a tired human) could contradict an earlier answer, or could start producing a run of
CONTRADICTED/UNVERIFIABLE answers as a session drags on, and nothing would ever notice
the pattern across the session. `intake_baseline.py` freezes the twelve intake facts a
project commits to, on demand, but nothing ever suggested WHEN a human should actually
use that freeze as a stop-and-review point.

REUSE, NOT REINVENTION.
  - Every per-answer signal in this module is `user_answer_validator.validate_answer()`,
    called once per answer, unmodified. This module never re-implements claim extraction
    or evidence checking -- `AnswerValidation.claim_type`/`.target`/`.status` are read
    straight off that module's own real result. "Contradiction detection" as required by
    this item's own task text IS that module's own CONTRADICTED status (checked against
    real RTL/build evidence); this module's OWN, additional contradiction check (below)
    is a different, narrower, purely textual one this module adds on top, never a
    duplicate of the evidence-based one.
  - The save-and-resume checkpoint IS `intake_baseline.freeze_intake_baseline()`, called
    unmodified. This module writes no state file of its own and never re-implements the
    twelve-field capture; it only decides WHETHER to recommend calling that function and
    composes the human-readable reason that ends up in its existing `note` field.

TWO INDEPENDENT SIGNALS, NEVER COLLAPSED INTO ONE.
  (1) SELF-CONTRADICTION -- a real, checkable logical conflict INDEPENDENT of whether any
      RTL/build evidence was ever supplied. A design has exactly ONE "DUT top module", so
      two answers in the same session both claiming to state it, with two different
      (case/whitespace-normalized) module names, are a genuine contradiction regardless of
      whether either name can currently be checked against real RTL. This is deliberately
      narrow: an ORDINARY CLAIM_MODULE_EXISTENCE claim ("module X exists") is NEVER treated
      as contradicting a different module's existence claim -- a real design legitimately
      has many modules, and inventing a broader "these two claims disagree" rule would be
      exactly the fabricated inconsistency the Evidence Truth Rule forbids. Only the
      explicit "DUT top" / "top module" phrasing -- a real, project-singular fact -- is
      compared across the session.
  (2) DEGRADING-QUALITY (FATIGUE) TREND -- a real, disclosed, HEURISTIC pattern over the
      per-answer CONTRADICTED/UNVERIFIABLE ("bad") signal already produced by
      `user_answer_validator.py`. Never presented as a measured constant: both thresholds
      below are declared, project-overridable heuristics, following the same disclosed-
      heuristic convention several sibling pattern-detection modules in this project
      already use (`perf_function_extraction.DEFAULT_THROUGHPUT_BOUND...`,
      `loop_convergence`'s plateau window, `potential_spec_gap_detector.
      SUBJECT_MATCH_THRESHOLD`). Two independent occurrences before a claim is trusted is
      this project's own recurring floor (`REPEAT_FAILURE_MIN_OCCURRENCES`,
      `ORGANIZATIONAL_MIN_CONFIRMATIONS`, `STABILITY_WINDOW_MIN_RUNS` are all 2); this
      module's own tail-run floor is 3, one above that bar, since a run-of-3 is the
      smallest run that cannot be explained by one bad answer immediately followed by one
      good one.

INSUFFICIENT_DATA IS NEVER SILENTLY READ AS "CLEAN". A session too short to run even the
weakest fatigue check (fewer than `FATIGUE_MIN_CONSECUTIVE_BAD` answers) reports the
honest `INSUFFICIENT_DATA` status -- never a fabricated `NO_PATTERN_DETECTED`, which would
claim a check ran and found nothing when no check actually ran at all. A real
self-contradiction is reported regardless of session length (even two answers can
genuinely contradict each other), and always outranks every other status.

WHAT THIS MODULE DOES NOT DO. It does not decide which of two contradicting answers is
correct -- that stays a human decision, the same ARBITRATION boundary this project's other
conflict-detecting modules already keep. It never writes a checkpoint on its own
initiative: `offer_save_and_resume_checkpoint()` REFUSES (raises) to freeze anything
unless a real pattern was found or the caller explicitly overrides with `force=True` -- an
unrequested checkpoint minted for no stated reason is not a save-and-resume checkpoint,
it is noise. It runs no build, job, gate, or approval, and it does not itself decide which
evidence (rtl_files/dut_facts_rtl/manifest) is correct for a given answer -- that is
exactly `user_answer_validator.py`'s own job, reused here unchanged.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from dv_harness import intake_baseline
from dv_harness import user_answer_validator as uav

# ---------------------------------------------------------------------------
# Vocabulary -- the whole-session verdict, never `models.Status`.
# ---------------------------------------------------------------------------

STATUS_NO_PATTERN = "NO_PATTERN_DETECTED"
STATUS_CONTRADICTORY = "CONTRADICTORY_ANSWERS_DETECTED"
STATUS_FATIGUE = "FATIGUE_DEGRADING_QUALITY_DETECTED"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

SESSION_FATIGUE_STATUSES = (
    STATUS_CONTRADICTORY,
    STATUS_FATIGUE,
    STATUS_NO_PATTERN,
    STATUS_INSUFFICIENT_DATA,
)

#: Per-answer statuses (from user_answer_validator.py, reused verbatim) that count as
#: "bad" for the fatigue trend -- an answer this project could not trust, whether because
#: it was proven wrong (CONTRADICTED) or could not be checked at all (UNVERIFIABLE). Kept
#: as a tuple of the real, imported status constants rather than re-typed strings, so a
#: future rename in user_answer_validator.py cannot silently desync this module.
BAD_STATUSES = (uav.CONTRADICTED, uav.UNVERIFIABLE)

#: A run of this many CONSECUTIVE bad answers at the tail of a session is this module's
#: own declared floor for "a real fatigue run", never a measured constant. One above this
#: project's own recurring "2 independent occurrences" bar (REPEAT_FAILURE_MIN_OCCURRENCES
#: / ORGANIZATIONAL_MIN_CONFIRMATIONS / STABILITY_WINDOW_MIN_RUNS), since a run of 2 can be
#: explained by one bad answer with a good neighbour on either side; a run of 3 cannot.
FATIGUE_MIN_CONSECUTIVE_BAD = 3

#: A session needs at least this many answers before the (separate) bad-RATE trend check
#: is even attempted -- two windows of >= 2 answers each.
MIN_ANSWERS_FOR_RATE_TREND = 4

#: How much the second-half bad-rate must exceed the first-half bad-rate before it is
#: reported as a real trend. A declared, project-overridable heuristic, not a measured
#: constant -- the same disclosed-heuristic convention this project's own
#: `potential_spec_gap_detector.SUBJECT_MATCH_THRESHOLD` (0.34) and
#: `perf_function_extraction`'s own bound already use.
FATIGUE_RATE_INCREASE_THRESHOLD = 0.34

FINDING_TAIL_RUN = "TAIL_RUN_OF_BAD_ANSWERS"
FINDING_RATE_TREND = "INCREASING_BAD_RATE_TREND"

#: The one singular-per-project sub-signal this module layers onto
#: user_answer_validator.py's own CLAIM_MODULE_EXISTENCE extraction: "the DUT top module"
#: names exactly one real thing per project. Deliberately narrow and disclosed -- an
#: ordinary "module X exists" claim naming a DIFFERENT module is never compared against
#: this one, since a design legitimately has many modules and that would not be a real
#: contradiction.
_SINGULAR_DUT_TOP_MARKER_RE = re.compile(r"\b(?:dut\s+top|top\s+module)\b", re.IGNORECASE)
SINGULAR_FIELD_DUT_TOP = "dut_top_module"


# ---------------------------------------------------------------------------
# Per-answer record
# ---------------------------------------------------------------------------

@dataclass
class SessionAnswer:
    index: int
    raw_text: str
    validation: "uav.AnswerValidation"
    singular_field: Optional[str] = None
    asked_at: Optional[str] = None
    answer_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "raw_text": self.raw_text,
            "validation": self.validation.to_dict(),
            "singular_field": self.singular_field,
            "asked_at": self.asked_at,
            "answer_id": self.answer_id,
        }

    @property
    def is_bad(self) -> bool:
        return self.validation.status in BAD_STATUSES


def _normalize_target(target: Optional[str]) -> Optional[str]:
    if target is None:
        return None
    return " ".join(target.strip().lower().split())


def _entry_field(entry: Union[str, Mapping[str, Any]], key: str, default: Any = None) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return default


def validate_session_answers(
        answers: Sequence[Union[str, Mapping[str, Any]]], *,
        rtl_files=None, dut_facts_rtl=None, manifest: Optional[dict] = None,
        verible_bin: str = uav.verible_parser.DEFAULT_VERIBLE_BIN) -> List[SessionAnswer]:
    """Runs user_answer_validator.validate_answer() -- unmodified -- over every raw answer
    in a session, in order. Each entry may be a bare string (using the session-level
    rtl_files/dut_facts_rtl/manifest), or a dict carrying its own `raw_text` plus optional
    per-answer overrides of any of those three -- a real intake session's evidence
    typically accumulates as more of the project is discovered, so a later answer may
    legitimately be checked against a fuller env.manifest.json than an earlier one was."""
    if answers is None:
        raise ValueError("answers is required (a session with no answers is not a session)")
    out: List[SessionAnswer] = []
    for i, entry in enumerate(answers):
        if isinstance(entry, Mapping):
            raw_text = entry.get("raw_text")
            if raw_text is None:
                raise ValueError(f"answer at index {i} carries no 'raw_text'")
        else:
            raw_text = entry
        eff_rtl_files = _entry_field(entry, "rtl_files", rtl_files)
        eff_dut_facts_rtl = _entry_field(entry, "dut_facts_rtl", dut_facts_rtl)
        eff_manifest = _entry_field(entry, "manifest", manifest)
        validation = uav.validate_answer(
            raw_text, rtl_files=eff_rtl_files, dut_facts_rtl=eff_dut_facts_rtl,
            manifest=eff_manifest, verible_bin=verible_bin)
        singular_field = None
        if (validation.claim_type == uav.CLAIM_MODULE_EXISTENCE
                and _SINGULAR_DUT_TOP_MARKER_RE.search(raw_text or "")):
            singular_field = SINGULAR_FIELD_DUT_TOP
        out.append(SessionAnswer(
            index=i, raw_text=raw_text, validation=validation,
            singular_field=singular_field,
            asked_at=_entry_field(entry, "asked_at"),
            answer_id=_entry_field(entry, "answer_id")))
    return out


# ---------------------------------------------------------------------------
# Signal 1: self-contradiction
# ---------------------------------------------------------------------------

@dataclass
class ContradictionFinding:
    field_key: str
    established_index: int
    established_target: str
    established_raw_text: str
    conflicting_index: int
    conflicting_target: str
    conflicting_raw_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_key": self.field_key,
            "established_index": self.established_index,
            "established_target": self.established_target,
            "established_raw_text": self.established_raw_text,
            "conflicting_index": self.conflicting_index,
            "conflicting_target": self.conflicting_target,
            "conflicting_raw_text": self.conflicting_raw_text,
        }


def detect_contradictions(session_answers: Sequence[SessionAnswer]) -> List[ContradictionFinding]:
    """Walks each singular field's own answers in session order; every time a later
    answer's normalized target disagrees with the most recently established one for that
    field, records a real ContradictionFinding and moves the 'established' value forward
    to the new one -- so a session that flip-flops A -> B -> A reports BOTH the A-vs-B and
    the B-vs-A disagreement, rather than only the first."""
    findings: List[ContradictionFinding] = []
    established: Dict[str, Any] = {}  # field_key -> (SessionAnswer, normalized_target)
    for ans in session_answers:
        if ans.singular_field is None:
            continue
        norm = _normalize_target(ans.validation.target)
        if norm is None:
            continue
        prior = established.get(ans.singular_field)
        if prior is None:
            established[ans.singular_field] = (ans, norm)
            continue
        prior_ans, prior_norm = prior
        if norm != prior_norm:
            findings.append(ContradictionFinding(
                field_key=ans.singular_field,
                established_index=prior_ans.index,
                established_target=prior_ans.validation.target,
                established_raw_text=prior_ans.raw_text,
                conflicting_index=ans.index,
                conflicting_target=ans.validation.target,
                conflicting_raw_text=ans.raw_text))
            established[ans.singular_field] = (ans, norm)
        # identical (normalized) restatement: leave the established value as-is.
    return findings


# ---------------------------------------------------------------------------
# Signal 2: degrading-quality (fatigue) trend
# ---------------------------------------------------------------------------

@dataclass
class FatigueTrendFinding:
    kind: str
    detail: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail}


def detect_fatigue_trend(session_answers: Sequence[SessionAnswer]) -> List[FatigueTrendFinding]:
    """Two independent, disclosed-heuristic checks over the real per-answer bad/good
    signal already produced by user_answer_validator.py. Neither check ever runs, and
    neither can ever fire, on a session shorter than its own stated floor -- see
    FATIGUE_MIN_CONSECUTIVE_BAD / MIN_ANSWERS_FOR_RATE_TREND."""
    n = len(session_answers)
    findings: List[FatigueTrendFinding] = []
    bad = [a.is_bad for a in session_answers]

    if n >= FATIGUE_MIN_CONSECUTIVE_BAD:
        run = 0
        for b in reversed(bad):
            if b:
                run += 1
            else:
                break
        if run >= FATIGUE_MIN_CONSECUTIVE_BAD:
            tail = session_answers[n - run:]
            findings.append(FatigueTrendFinding(
                kind=FINDING_TAIL_RUN,
                detail={
                    "run_length": run,
                    "start_index": tail[0].index,
                    "end_index": tail[-1].index,
                    "statuses": [a.validation.status for a in tail],
                }))

    if n >= MIN_ANSWERS_FOR_RATE_TREND:
        split = n // 2
        first_half, second_half = bad[:split], bad[split:]
        first_rate = sum(first_half) / len(first_half)
        second_rate = sum(second_half) / len(second_half)
        if second_rate - first_rate >= FATIGUE_RATE_INCREASE_THRESHOLD:
            findings.append(FatigueTrendFinding(
                kind=FINDING_RATE_TREND,
                detail={
                    "first_half_bad_rate": round(first_rate, 3),
                    "second_half_bad_rate": round(second_rate, 3),
                    "split_index": split,
                    "increase": round(second_rate - first_rate, 3),
                    "threshold": FATIGUE_RATE_INCREASE_THRESHOLD,
                }))

    return findings


# ---------------------------------------------------------------------------
# Combined session report
# ---------------------------------------------------------------------------

@dataclass
class SessionFatigueReport:
    status: str
    answer_count: int
    reason: str
    contradictions: List[ContradictionFinding] = field(default_factory=list)
    fatigue_findings: List[FatigueTrendFinding] = field(default_factory=list)
    answers: List[SessionAnswer] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "answer_count": self.answer_count,
            "reason": self.reason,
            "contradictions": [c.to_dict() for c in self.contradictions],
            "fatigue_findings": [f.to_dict() for f in self.fatigue_findings],
            "answers": [a.to_dict() for a in self.answers],
        }


def analyze_session_fatigue(
        answers: Sequence[Union[str, Mapping[str, Any]]], *,
        rtl_files=None, dut_facts_rtl=None, manifest: Optional[dict] = None,
        verible_bin: str = uav.verible_parser.DEFAULT_VERIBLE_BIN) -> SessionFatigueReport:
    """The one entry point: validates every answer in the session (reusing
    user_answer_validator.validate_answer() as the per-answer signal), then folds the two
    independent signals above into one honest, worst-wins status.

    Precedence, most severe first:
      1. STATUS_CONTRADICTORY -- a real self-contradiction was found. Reported regardless
         of session length: even two answers can genuinely contradict each other, and a
         real contradiction is never diluted by "not enough data yet".
      2. STATUS_FATIGUE -- no contradiction, but a real degrading-quality trend was found.
      3. STATUS_NO_PATTERN -- neither check found anything, AND at least one check
         genuinely ran (session length >= FATIGUE_MIN_CONSECUTIVE_BAD) -- a real, checked
         clean result.
      4. STATUS_INSUFFICIENT_DATA -- the session is too short for either fatigue check to
         have run at all. Never collapsed into STATUS_NO_PATTERN, which would claim a
         check happened and found nothing when no check actually ran."""
    session_answers = validate_session_answers(
        answers, rtl_files=rtl_files, dut_facts_rtl=dut_facts_rtl, manifest=manifest,
        verible_bin=verible_bin)
    n = len(session_answers)
    contradictions = detect_contradictions(session_answers)

    if contradictions:
        status = STATUS_CONTRADICTORY
        reason = (f"{len(contradictions)} contradictory answer(s) found for the same "
                  "singular field within this session")
        fatigue_findings: List[FatigueTrendFinding] = []
    else:
        fatigue_findings = detect_fatigue_trend(session_answers)
        if fatigue_findings:
            status = STATUS_FATIGUE
            reason = (f"{len(fatigue_findings)} degrading-quality fatigue finding(s) "
                      "detected across this session's real answer sequence")
        elif n >= FATIGUE_MIN_CONSECUTIVE_BAD:
            status = STATUS_NO_PATTERN
            reason = (f"checked {n} answers: no self-contradiction and no degrading-"
                      "quality trend was found")
        else:
            status = STATUS_INSUFFICIENT_DATA
            reason = (f"only {n} answer(s) recorded -- fewer than "
                      f"{FATIGUE_MIN_CONSECUTIVE_BAD} required before a fatigue trend "
                      "check can honestly run at all")

    return SessionFatigueReport(
        status=status, answer_count=n, reason=reason, contradictions=contradictions,
        fatigue_findings=fatigue_findings, answers=session_answers)


# ---------------------------------------------------------------------------
# Save-and-resume checkpoint offer -- wraps intake_baseline.py, never reinvents it.
# ---------------------------------------------------------------------------

@dataclass
class CheckpointRecommendation:
    recommended: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"recommended": self.recommended, "reason": self.reason}


def recommend_checkpoint(report: SessionFatigueReport) -> CheckpointRecommendation:
    """Decides whether a save-and-resume checkpoint should be OFFERED to a human, from a
    real SessionFatigueReport -- never forced, and never recommended for a session that
    was never actually checked (STATUS_INSUFFICIENT_DATA)."""
    if report.status == STATUS_CONTRADICTORY:
        return CheckpointRecommendation(
            True,
            f"{len(report.contradictions)} contradictory answer(s) detected in this "
            "session -- recommend a save-and-resume checkpoint so a human can review "
            "before intake continues.")
    if report.status == STATUS_FATIGUE:
        return CheckpointRecommendation(
            True,
            "answer quality is degrading within this session (a real fatigue pattern "
            "was detected) -- recommend a save-and-resume checkpoint.")
    if report.status == STATUS_INSUFFICIENT_DATA:
        return CheckpointRecommendation(
            False,
            "not enough answers recorded yet to evaluate a fatigue/inconsistency "
            "pattern -- no checkpoint recommended on this basis.")
    return CheckpointRecommendation(
        False, "no fatigue or inconsistency pattern was detected in this session.")


def offer_save_and_resume_checkpoint(
        root, facts: Optional[Dict[str, Any]], *, frozen_by: str,
        report: SessionFatigueReport, note: str = "",
        force: bool = False) -> Dict[str, Any]:
    """Offers -- and, once accepted, WRITES -- a save-and-resume checkpoint through
    intake_baseline.freeze_intake_baseline(), unmodified. Refuses (raises ValueError) to
    freeze anything when the report itself found no real reason to and the caller did not
    explicitly override with `force=True` -- a checkpoint minted for no stated reason is
    not a save-and-resume checkpoint, it is noise. `frozen_by` is passed straight through;
    an unattributable freeze is refused by intake_baseline.py itself, exactly as it
    already is for every other caller of that function."""
    rec = recommend_checkpoint(report)
    if not rec.recommended and not force:
        raise ValueError(
            "save-and-resume checkpoint not offered: "
            f"{rec.reason} (pass force=True to checkpoint anyway)")
    composed_note = (f"{note} " if note else "") + \
        f"[answer_inconsistency_fatigue_detection] {rec.reason}"
    freeze_record = intake_baseline.freeze_intake_baseline(
        root, facts, frozen_by=frozen_by, note=composed_note.strip())
    return {
        "freeze": freeze_record,
        "fatigue_report": report.to_dict(),
        "recommendation": rec.to_dict(),
    }


# ---------------------------------------------------------------------------
# Front door -- deliberately standalone (no dv-harness CLI verb, no gates.py entry;
# cli.py/gates.py are explicitly out of scope for this item per the governing task).
# ---------------------------------------------------------------------------

def _load_json_file(path: str):
    p = Path(path)
    if not p.is_file():
        return None, f"FILE_NOT_FOUND: {p}"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"FILE_UNREADABLE: {type(exc).__name__}: {exc}"
    return doc, None


def execute_verb(argv: Sequence[str]) -> int:
    """`python -m dv_harness.answer_inconsistency_fatigue_detection analyze --answers
    <file.json> [--manifest <file.json>] [--dut-facts-rtl <file.json>] [--json]`. The
    answers file is a bare JSON list of strings/objects in the shape
    validate_session_answers() itself documents. Exit 0 STATUS_NO_PATTERN, 1
    STATUS_CONTRADICTORY/STATUS_FATIGUE (a real finding), 2 STATUS_INSUFFICIENT_DATA or a
    usage/refusal error."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="answer-inconsistency-fatigue-detection",
        description="Detect a contradictory or degrading-quality answer pattern across "
                    "one intake session's real answer sequence.")
    ap.add_argument("verb", choices=["analyze"])
    ap.add_argument("--answers", required=True,
                    help="path to a JSON list of raw answer strings/objects")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--dut-facts-rtl", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv))

    answers, err = _load_json_file(args.answers)
    if err:
        print(json.dumps({"status": "REFUSED", "reason": err}, indent=2))
        return 2
    if not isinstance(answers, list):
        print(json.dumps({"status": "REFUSED", "reason": "ANSWERS_MUST_BE_A_JSON_LIST"},
                         indent=2))
        return 2

    manifest = None
    if args.manifest:
        manifest, err = _load_json_file(args.manifest)
        if err:
            print(json.dumps({"status": "REFUSED", "reason": err}, indent=2))
            return 2

    dut_facts_rtl = None
    if getattr(args, "dut_facts_rtl", None):
        dut_facts_rtl, err = _load_json_file(args.dut_facts_rtl)
        if err:
            print(json.dumps({"status": "REFUSED", "reason": err}, indent=2))
            return 2

    report = analyze_session_fatigue(answers, dut_facts_rtl=dut_facts_rtl, manifest=manifest)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"status: {report.status}")
        print(f"reason: {report.reason}")
        print(f"answer_count: {report.answer_count}")
        for c in report.contradictions:
            print(f"  CONTRADICTION[{c.field_key}]: answer #{c.established_index} said "
                  f"'{c.established_target}', answer #{c.conflicting_index} said "
                  f"'{c.conflicting_target}'")
        for f in report.fatigue_findings:
            print(f"  FATIGUE[{f.kind}]: {f.detail}")

    if report.status in (STATUS_CONTRADICTORY, STATUS_FATIGUE):
        return 1
    if report.status == STATUS_INSUFFICIENT_DATA:
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
