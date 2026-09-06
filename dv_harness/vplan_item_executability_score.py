"""dv_harness/vplan_item_executability_score.py -- a per-vPlan-item
IMPLEMENTATION-READINESS axis on a distinct 0/20/50/80/100 scale, deliberately
NOT the same concept as `vplan_artifact.py`'s nine-dimension completeness
analysis and NOT the same concept as `subsystem_practicality_score.py`'s
whole-subsystem maturity rollup.

WHY A THIRD, DISTINCT AXIS
--------------------------
This repo already has two real per-vPlan-adjacent readers, and neither
answers this module's question:

  * `vplan_artifact.py` scores a vPlan ROW across NINE independent dimensions
    (requirement link, hierarchy integrity, ownership, coverage/checker/test
    linkage, ...), each READY/PARTIAL/BLOCKED/UNKNOWN, NEVER averaged into
    one number -- by design, because folding nine independently-meaningful
    axes into one score would let a caller reading only the fold mistake a
    vPlan that is BLOCKED on one axis and READY on the other eight for a
    vPlan that is "mostly fine".
  * `subsystem_practicality_score.py` rolls up TEN whole-SUBSYSTEM maturity
    signals (spec correctness, DUT discovery, VIP mapping, ...) into one
    weighted 0-100 SUBSYSTEM score, read off already-derived module verdicts,
    never per-item.

Neither answers "for THIS ONE vPlan item, how far along is turning it into a
runnable generated test -- has anything even been identified, is it mapped to
real implementation artifacts yet, and if so is that mapping still open on
unresolved questions?" That is an IMPLEMENTATION-READINESS axis, not a
completeness audit and not a maturity rollup: a vPlan row can score READY on
every one of `vplan_artifact.py`'s nine completeness dimensions (a
well-written row: requirement link present, coverage/checker/test fields all
declared) while this module's own answer is still 20 (IDENTIFIED_UNMAPPED),
because "the vPlan row's own fields are filled in" and "the underlying
sequence/checker/test files this row POINTS AT have actually been mapped by a
human or a generator" are different facts. This module reads only the
second. A repo-wide grep for `executability`/`implementation_readiness` /
`IDENTIFIED_UNMAPPED` before this change matched nothing.

THE FIVE-VALUE SCALE, AND WHY IT IS FIVE FIXED POINTS RATHER THAN A PERCENT
----------------------------------------------------------------------------
    0   NO_EVIDENCE            -- nothing at all: the item carries no
                                   identity (no id/title/description) and no
                                   mapping fact was even supplied to check.
    20  IDENTIFIED_UNMAPPED     -- the item is known to exist (it has an
                                   identity, or the caller declared a real set
                                   of mapping facts to check) but ZERO of its
                                   declared mapping facts are present.
    50  PARTIALLY_MAPPED        -- some, but not all, declared mapping facts
                                   are present.
    80  MAPPED_OPEN_QUESTIONS   -- every declared mapping fact is present, but
                                   at least one open question against the item
                                   is still unresolved.
    100 FULLY_READY             -- every declared mapping fact is present and
                                   no open question against the item remains
                                   unresolved.
A percent-style score invites averaging across items and across the nine
completeness dimensions above, which is exactly the collapsing this module
exists to avoid being read as. Five named, ordered checkpoints are a
different kind of value: a status, not a measurement, matching the
non-numeric-but-ordered discipline `requirement_contract.py`'s five-value
status vocabulary and `waiver_store.py`'s five-value waiver status already
use for the same reason.

DUCK-TYPED INPUT, ON PURPOSE
-----------------------------
Per this batch's file-safety scope this module must not import
`vplan_artifact.py`, `verification_intent_ir.py`, or any other in-flight
sibling module, and must not assume any of their still-moving internal
shapes. So a vPlan item is accepted as a plain `Mapping` carrying whatever
identity fields a caller has (`item_id`/`id`/`req_id`, `title`/`description`),
a `mapping_facts` value (a `{fact_name: bool}` dict, OR a list of
`{"name"/"fact": ..., "present"/"mapped"/"done"/"satisfied": bool}` records,
OR a bare list of fact-name strings each counted present -- callers using the
bare-string form should also declare `required_mapping_facts` so a fact that
was never even asked about can be told apart from one asked about and found
absent; see `normalize_mapping_facts()`'s own doc for the honest limit when
they do not), an `open_questions` list (each optionally `resolved`), and a
`blockers` list (each optionally carrying a `severity`). Nothing here decides
what a "mapping fact" IS -- unlike `vplan_artifact.py`'s nine named
dimensions, this module does not mint a second opinion about what
"coverage-linked" or "checker-linked" means. It only counts how many of
whatever facts the caller declared are present, which keeps this module
correct today and automatically compatible with whatever shape a future
generator (or `vplan_artifact.py` itself, once it lands its own final shape)
produces, by converting that shape's own facts into this same plain
dict/list form at the call site.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE: SCORE AND BLOCKER ARE NEVER MERGED
--------------------------------------------------------------------------------
A vPlan item can be scored 100 (FULLY_READY: every mapping fact present, no
open question outstanding) and STILL carry a separately-flagged CRITICAL
blocker (e.g. a caller-recorded "this sequence's DUT register write was
proven wrong by RTL evidence" finding). `score_item_executability()` NEVER
folds a blocker into the numeric score, and NEVER suppresses, downgrades, or
even reads a blocker to decide the score at all -- blockers are collected and
reported on the SAME record, in their OWN field
(`critical_blockers`/`other_blockers`), entirely independent of `score`.
`ItemExecutabilityReport.to_dict()` and `render_executability_matrix()` both
ALWAYS render the blocker columns beside the score column rather than
folding one into the other's text, and
`assert_score_never_hides_a_critical_blocker()` is a real, run-at-test-time
proof that a synthetic item scoring 100 with an attached CRITICAL blocker
reports `score == 100` AND `critical_blockers` non-empty in the same record --
never a record where the high score silently drops the blocker, and never a
record where a present blocker silently drags the score down.

WHAT THIS MODULE DOES NOT DO
-------------------------------
It reads a caller-supplied record and scores it; it does not parse a spec,
does not extract vPlan rows from prose, does not check a mapping claim
against real RTL/VIP/coverage evidence, and does not decide whether a
`mapping_facts` value the caller supplied is actually TRUE -- per the
Evidence Truth Rule that verification stays with whatever real producer
populated the fact in the first place (e.g. `existing_command_reuse_score.py`
for a reuse-candidate mapping, `vip_api_card.py` for a VIP-API citation). It
DECIDES, APPROVES and RUNS nothing: no stage executes, no gate script is
invoked, no file is written, and there is deliberately no stage gate -- an
executability score is an input to a human's vPlan-review decision, never a
substitute for one. `ControlPlane.approve()`, `policy.can_signoff()`,
`assert_human_approval()` and the PR-only main/master governance are
untouched and unreferenced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

# The five fixed checkpoints. Deliberately not a percent: see module docstring.
SCORE_NO_EVIDENCE = 0
SCORE_IDENTIFIED_UNMAPPED = 20
SCORE_PARTIALLY_MAPPED = 50
SCORE_MAPPED_OPEN_QUESTIONS = 80
SCORE_FULLY_READY = 100

EXECUTABILITY_SCALE: Tuple[int, ...] = (
    SCORE_NO_EVIDENCE,
    SCORE_IDENTIFIED_UNMAPPED,
    SCORE_PARTIALLY_MAPPED,
    SCORE_MAPPED_OPEN_QUESTIONS,
    SCORE_FULLY_READY,
)

SCORE_LABELS: Dict[int, str] = {
    SCORE_NO_EVIDENCE: "NO_EVIDENCE",
    SCORE_IDENTIFIED_UNMAPPED: "IDENTIFIED_UNMAPPED",
    SCORE_PARTIALLY_MAPPED: "PARTIALLY_MAPPED",
    SCORE_MAPPED_OPEN_QUESTIONS: "MAPPED_OPEN_QUESTIONS",
    SCORE_FULLY_READY: "FULLY_READY",
}

# Severity strings this module recognizes as "critical", case-insensitively.
# Kept small and explicit rather than inferred, per the Evidence Truth Rule --
# an unrecognized severity is reported as its own bucket (see
# `normalize_blockers()`), never silently treated as non-critical.
_CRITICAL_SEVERITY_ALIASES = frozenset({"critical", "blocker", "p0", "sev0", "sev1"})


class VPlanItemExecutabilityError(ValueError):
    """Raised for a malformed input this module refuses to guess about."""

    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(f"{reason}: {self.detail}" if self.detail else reason)


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


@dataclass(frozen=True)
class NormalizedMappingFacts:
    """The result of reading a caller's `mapping_facts` value into a flat
    `{fact_name: bool}` table, plus honesty about what could not be told."""

    facts: Dict[str, bool]
    declared_total: int
    present_count: int
    missing_fact_names: Tuple[str, ...]
    unknowns: Tuple[str, ...]


def normalize_mapping_facts(
    raw: Any,
    *,
    required_mapping_facts: Optional[Sequence[str]] = None,
) -> NormalizedMappingFacts:
    """Turn a duck-typed `mapping_facts` value into a flat present/absent
    table.

    Accepted shapes:
      * `None` / missing -- zero facts declared.
      * A `Mapping[str, Any]` -- each key is a fact name, its value's
        truthiness decides present/absent.
      * A list of records, each a `Mapping` naming the fact
        (`name`/`fact`/`id`) and its presence
        (`present`/`mapped`/`done`/`satisfied`) -- a record missing either is
        an `unknowns` entry, never silently dropped or guessed present.
      * A bare list of strings -- each string is a fact name considered
        PRESENT (the caller is asserting these facts hold). This form cannot,
        by itself, say anything about a fact that was never mentioned at
        all -- pass `required_mapping_facts` (the full set that SHOULD have
        been checked) so an unmentioned required fact reports as declared-
        but-absent rather than being invisible to the count. Without
        `required_mapping_facts`, a bare-string list's `declared_total` is
        only what was actually named -- an honest, documented limit, not a
        silent one.

    Anything else (an int, a plain string, ...) raises
    `VPlanItemExecutabilityError` rather than guessing a shape.
    """
    facts: Dict[str, bool] = {}
    unknowns: List[str] = []

    if raw is None:
        pass
    elif isinstance(raw, Mapping):
        for key, value in raw.items():
            facts[str(key)] = bool(value)
    elif isinstance(raw, (list, tuple)):
        for entry in raw:
            if isinstance(entry, str):
                facts[entry] = True
            elif isinstance(entry, Mapping):
                name = _first_present(entry, ["name", "fact", "id", "fact_name"])
                present = _first_present(
                    entry, ["present", "mapped", "done", "satisfied", "value"]
                )
                if name is None or present is None:
                    unknowns.append(
                        f"UNRECOGNIZED_MAPPING_FACT_RECORD:{entry!r}"
                    )
                    continue
                facts[str(name)] = bool(present)
            else:
                unknowns.append(f"UNRECOGNIZED_MAPPING_FACT_ENTRY:{entry!r}")
    else:
        raise VPlanItemExecutabilityError(
            "MAPPING_FACTS_UNRECOGNIZED_SHAPE",
            {"type": type(raw).__name__},
        )

    if required_mapping_facts:
        for name in required_mapping_facts:
            facts.setdefault(str(name), False)

    present_count = sum(1 for v in facts.values() if v)
    missing = tuple(sorted(name for name, present in facts.items() if not present))
    return NormalizedMappingFacts(
        facts=facts,
        declared_total=len(facts),
        present_count=present_count,
        missing_fact_names=missing,
        unknowns=tuple(unknowns),
    )


@dataclass(frozen=True)
class NormalizedQuestions:
    total: int
    unresolved: int
    unknowns: Tuple[str, ...]


def normalize_open_questions(raw: Any) -> NormalizedQuestions:
    """A question is UNRESOLVED unless it explicitly declares itself
    resolved (`resolved is True`, or a `status` that reads as closed). A bare
    string is an unresolved question by construction -- filing it at all is
    the open fact. Anything not a list/tuple/None raises."""
    if raw is None:
        return NormalizedQuestions(total=0, unresolved=0, unknowns=())
    if not isinstance(raw, (list, tuple)):
        raise VPlanItemExecutabilityError(
            "OPEN_QUESTIONS_UNRECOGNIZED_SHAPE", {"type": type(raw).__name__}
        )
    unresolved = 0
    unknowns: List[str] = []
    closed_status_tokens = {"resolved", "closed", "answered"}
    for entry in raw:
        if isinstance(entry, str):
            unresolved += 1
            continue
        if isinstance(entry, Mapping):
            resolved = entry.get("resolved")
            status = str(entry.get("status", "")).strip().lower()
            if resolved is True or status in closed_status_tokens:
                continue
            unresolved += 1
            continue
        unknowns.append(f"UNRECOGNIZED_QUESTION_ENTRY:{entry!r}")
    return NormalizedQuestions(
        total=len(raw), unresolved=unresolved, unknowns=tuple(unknowns)
    )


@dataclass(frozen=True)
class NormalizedBlocker:
    text: str
    severity: str
    is_critical: bool


@dataclass(frozen=True)
class NormalizedBlockers:
    all_blockers: Tuple[NormalizedBlocker, ...]
    critical: Tuple[NormalizedBlocker, ...]
    other: Tuple[NormalizedBlocker, ...]
    unknowns: Tuple[str, ...]


def normalize_blockers(raw: Any) -> NormalizedBlockers:
    """Blockers are collected but NEVER read to influence `score` -- see the
    module docstring's "score and blocker are never merged" rule. A blocker
    record is a `Mapping` (or bare string, treated as an uncategorized
    blocker of unknown severity) carrying an optional `severity`; a
    severity in `_CRITICAL_SEVERITY_ALIASES` (case-insensitive) is critical,
    anything else is `other`, and an item carrying no `severity` field at
    all is `other` with severity reported as `UNSPECIFIED` -- never silently
    assumed critical or silently assumed non-critical-and-therefore-ignored;
    it is always present in `other`."""
    if raw is None:
        return NormalizedBlockers((), (), (), ())
    if not isinstance(raw, (list, tuple)):
        raise VPlanItemExecutabilityError(
            "BLOCKERS_UNRECOGNIZED_SHAPE", {"type": type(raw).__name__}
        )
    all_blockers: List[NormalizedBlocker] = []
    unknowns: List[str] = []
    for entry in raw:
        if isinstance(entry, str):
            all_blockers.append(NormalizedBlocker(text=entry, severity="UNSPECIFIED", is_critical=False))
            continue
        if isinstance(entry, Mapping):
            text = str(_first_present(entry, ["text", "description", "summary", "reason"]) or "(no text supplied)")
            severity_raw = entry.get("severity")
            severity = str(severity_raw).strip() if severity_raw not in (None, "") else "UNSPECIFIED"
            is_critical = severity.strip().lower() in _CRITICAL_SEVERITY_ALIASES
            all_blockers.append(NormalizedBlocker(text=text, severity=severity, is_critical=is_critical))
            continue
        unknowns.append(f"UNRECOGNIZED_BLOCKER_ENTRY:{entry!r}")
    critical = tuple(b for b in all_blockers if b.is_critical)
    other = tuple(b for b in all_blockers if not b.is_critical)
    return NormalizedBlockers(
        all_blockers=tuple(all_blockers), critical=critical, other=other, unknowns=tuple(unknowns)
    )


@dataclass(frozen=True)
class ItemExecutabilityReport:
    item_id: Optional[str]
    score: int
    level_label: str
    reason: str
    mapping_facts_present: int
    mapping_facts_total: int
    missing_fact_names: Tuple[str, ...]
    unresolved_open_questions: int
    open_questions_total: int
    critical_blockers: Tuple[Dict[str, str], ...]
    other_blockers: Tuple[Dict[str, str], ...]
    unknowns: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "item_id": self.item_id,
            "score": self.score,
            "level_label": self.level_label,
            "reason": self.reason,
            "mapping_facts_present": self.mapping_facts_present,
            "mapping_facts_total": self.mapping_facts_total,
            "missing_fact_names": list(self.missing_fact_names),
            "unresolved_open_questions": self.unresolved_open_questions,
            "open_questions_total": self.open_questions_total,
            # Deliberately its own top-level field, beside `score` and never
            # folded into it -- see module docstring.
            "critical_blockers": [dict(b) for b in self.critical_blockers],
            "other_blockers": [dict(b) for b in self.other_blockers],
            "has_critical_blocker": bool(self.critical_blockers),
            "unknowns": list(self.unknowns),
        }


def score_item_executability(
    item: Mapping[str, Any],
    *,
    required_mapping_facts: Optional[Sequence[str]] = None,
) -> ItemExecutabilityReport:
    """Score one vPlan item's implementation readiness on the fixed
    0/20/50/80/100 scale. `item` is duck-typed -- see module docstring for
    the accepted shape. Raises `VPlanItemExecutabilityError` on a value this
    module refuses to guess about (a malformed `mapping_facts`/
    `open_questions`/`blockers` shape, or `item` not itself a Mapping)."""
    if not isinstance(item, Mapping):
        raise VPlanItemExecutabilityError(
            "ITEM_NOT_A_MAPPING", {"type": type(item).__name__}
        )

    item_id = _first_present(item, ["item_id", "id", "req_id", "vplan_item_id"])
    identity_text = _first_present(item, ["title", "description", "name", "summary"])

    facts = normalize_mapping_facts(
        item.get("mapping_facts"), required_mapping_facts=required_mapping_facts
    )
    questions = normalize_open_questions(item.get("open_questions"))
    blockers = normalize_blockers(item.get("blockers"))

    unknowns: List[str] = list(facts.unknowns) + list(questions.unknowns) + list(blockers.unknowns)

    identified = bool(item_id) or bool(identity_text) or facts.declared_total > 0

    if not identified:
        score = SCORE_NO_EVIDENCE
        reason = "NO_ITEM_IDENTITY_OR_MAPPING_FACTS_SUPPLIED"
    elif facts.declared_total == 0 or facts.present_count == 0:
        score = SCORE_IDENTIFIED_UNMAPPED
        reason = (
            "ITEM_IDENTIFIED_BUT_ZERO_MAPPING_FACTS_DECLARED"
            if facts.declared_total == 0
            else "ITEM_IDENTIFIED_BUT_NO_DECLARED_MAPPING_FACT_IS_PRESENT"
        )
    elif facts.present_count < facts.declared_total:
        score = SCORE_PARTIALLY_MAPPED
        reason = f"PARTIAL_MAPPING:{facts.present_count}_OF_{facts.declared_total}_FACTS_PRESENT"
    elif questions.unresolved > 0:
        score = SCORE_MAPPED_OPEN_QUESTIONS
        reason = f"ALL_MAPPING_FACTS_PRESENT_BUT_{questions.unresolved}_OPEN_QUESTION(S)_UNRESOLVED"
    else:
        score = SCORE_FULLY_READY
        reason = "ALL_MAPPING_FACTS_PRESENT_NO_UNRESOLVED_OPEN_QUESTIONS"

    return ItemExecutabilityReport(
        item_id=str(item_id) if item_id is not None else None,
        score=score,
        level_label=SCORE_LABELS[score],
        reason=reason,
        mapping_facts_present=facts.present_count,
        mapping_facts_total=facts.declared_total,
        missing_fact_names=facts.missing_fact_names,
        unresolved_open_questions=questions.unresolved,
        open_questions_total=questions.total,
        critical_blockers=tuple(
            {"text": b.text, "severity": b.severity} for b in blockers.critical
        ),
        other_blockers=tuple(
            {"text": b.text, "severity": b.severity} for b in blockers.other
        ),
        unknowns=tuple(unknowns),
    )


def score_vplan_items(
    items: Sequence[Mapping[str, Any]],
    *,
    required_mapping_facts: Optional[Sequence[str]] = None,
) -> List[ItemExecutabilityReport]:
    """Score every item in a caller-supplied vPlan item list. A single
    malformed item's error is annotated with its position and re-raised --
    this module never silently skips an item it could not score."""
    reports: List[ItemExecutabilityReport] = []
    for index, item in enumerate(items):
        try:
            reports.append(
                score_item_executability(item, required_mapping_facts=required_mapping_facts)
            )
        except VPlanItemExecutabilityError as exc:
            exc.detail = dict(exc.detail)
            exc.detail["item_index"] = index
            raise
    return reports


def render_executability_matrix(reports: Sequence[ItemExecutabilityReport]) -> str:
    """A markdown table over per-item reports, through this repo's only
    parameterized table renderer (`connectivity.render_markdown_table()`),
    rather than a second hand-rolled pipe-table loop. The Critical Blocker
    column is rendered BESIDE Score, never folded into it -- a reader must
    never be able to mistake a high score for "no blocker"."""
    from . import connectivity as _connectivity  # local import: this module's

    columns = [
        ("item_id", "Item"),
        ("level_label", "Executability"),
        ("score", "Score"),
        ("mapping", "Facts Mapped"),
        ("open_questions", "Open Qs"),
        ("critical_blocker", "CRITICAL Blocker"),
    ]
    rows = []
    for r in reports:
        rows.append(
            {
                "item_id": r.item_id or "(no id)",
                "level_label": r.level_label,
                "score": str(r.score),
                "mapping": f"{r.mapping_facts_present}/{r.mapping_facts_total}",
                "open_questions": str(r.unresolved_open_questions),
                "critical_blocker": (
                    "; ".join(b["text"] for b in r.critical_blockers)
                    if r.critical_blockers
                    else "-"
                ),
            }
        )
    return _connectivity.render_markdown_table(columns, rows, empty_note="(no vPlan items scored)")


def assert_score_never_hides_a_critical_blocker(report: ItemExecutabilityReport) -> None:
    """A structural proof helper (also exercised by the test suite): a
    report's own dict form must carry `critical_blockers` verbatim whatever
    `score` reads, and the score field must never be recomputed from the
    blocker list. Raises AssertionError naming which guarantee broke."""
    payload = report.to_dict()
    if bool(payload["critical_blockers"]) != bool(report.critical_blockers):
        raise AssertionError("CRITICAL_BLOCKERS_DROPPED_IN_TO_DICT")
    if payload["score"] != report.score:
        raise AssertionError("SCORE_MUTATED_IN_TO_DICT")
    if payload["score"] not in EXECUTABILITY_SCALE:
        raise AssertionError("SCORE_OUTSIDE_FIXED_SCALE")


def execute_verb(args: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.vplan_item_executability_score --items <file.json>
    [--required-facts a,b,c] [--json]`. Exit 0 if every item scored
    FULLY_READY and none carries a critical blocker, 1 if at least one item
    scored below FULLY_READY or carries a critical blocker, 2 on a usage/
    input error."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="vplan-item-executability-score")
    parser.add_argument("--items", required=True, help="JSON file: a list of vPlan item records")
    parser.add_argument("--required-facts", default=None, help="comma-separated fact names")
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(list(args) if args is not None else None)

    try:
        with open(ns.items, "r", encoding="utf-8") as fh:
            raw_items = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"NOT_AVAILABLE: could not read --items: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_items, list):
        print("NOT_AVAILABLE: --items must contain a JSON list", file=sys.stderr)
        return 2

    required = [f.strip() for f in ns.required_facts.split(",") if f.strip()] if ns.required_facts else None

    try:
        reports = score_vplan_items(raw_items, required_mapping_facts=required)
    except VPlanItemExecutabilityError as exc:
        print(f"NOT_AVAILABLE: {exc}", file=sys.stderr)
        return 2

    all_ready = all(r.score == SCORE_FULLY_READY and not r.critical_blockers for r in reports)

    if ns.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print(render_executability_matrix(reports))

    return 0 if all_ready else 1


if __name__ == "__main__":
    import sys

    sys.exit(execute_verb())
