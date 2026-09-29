"""dv_harness/test_suite_lifecycle.py -- Test Suite Center: per-pattern test
lifecycle state, derived ONLY from real evidence_db.py job/regression records
and golden_scenario.py capsules (dashboard_test_suite_center gap-close,
2026-09-07).

THE GAP
-------
Real, separately-queryable evidence about one test pattern's own life already
exists across three places in this codebase -- evidence_db.py's `jobs` table
(has this pattern's job been submitted/run, what did LSF report),
evidence_db.py's `regression_verdicts` table (is this pattern CURRENTLY
verified PASS, the exact "currently verified PASS" snapshot semantics
`regression_list_manager.py`'s own regression.list already carries), and
golden_scenario.py's `golden_scenarios` capsule store (has a human/agent ever
recorded this pattern as a proven, reusable golden result) -- but nothing in
this repo ever joined the three into one lifecycle state per pattern.

The document this task cites (a Web Control Plane master prompt naming a
lifecycle vocabulary "GENERATED through CLOSURE_PROVEN, plus
SEMANTIC_DUPLICATE/SUBSUMED/SUPERSET") is not present in this checkout --
confirmed by a repo-wide search before writing anything, the same honest gap
several other CLAUDE.md sections in this project already disclose for a
master-prompt document this repo does not carry. So the seven-state core
progression below is this module's own defensible derivation, grounded
entirely in what IS real and already queryable in this codebase:
evidence_db.py's own real `lsf_status` vocabulary (see `lsf_client.JobState`:
PEND/RUN/DONE/EXIT), its `regression_verdicts` "currently verified PASS/FAIL"
snapshot, and golden_scenario.py's own PASS-evidence-gated capsule contract.
CLOSURE_PROVEN is reserved, literally, for `record_golden_scenario()`'s own
strongest real guarantee: that function REFUSES to persist a capsule unless
it can prove, against a real `normalized_evidence` row, that the cited
evidence is a genuine PASS for this exact pattern.

EVIDENCE TRUTH RULE, enforced structurally
-------------------------------------------
A pattern with NO real row in ANY of the three sources is `UNKNOWN` -- never
silently promoted to `GENERATED`, since "a job was generated" is itself a
real claim (a job record exists) this module refuses to fabricate.

The three RELATIONSHIP tags (SEMANTIC_DUPLICATE/SUBSUMED/SUPERSET) have no
real producer anywhere in this codebase -- a repo-wide grep before writing
this module found no pattern-similarity/dedup engine over test PATTERNS
(the nearest real analogue, `spec_intelligence.py`'s `requirement_similarity()`,
operates over REQUIREMENT records, a different domain, and is not imported
here). So a relationship is NEVER derived by this module -- it is recorded
ONLY from a caller-declared, evidence-cited fact, the same "accept an
explicit caller-declared fact the real evidence store cannot supply, rather
than invent one" discipline `ip_ownership_conflict.py`'s
`legacy_bfm_declarations` and `existing_command_reuse_score.py`'s
`existing_commands` already establish. A relationship with no citation, or
naming an unrecognized `relation` value, or naming a `pattern_a`/`pattern_b`
this module's own lifecycle report has no real evidence for at all, is
refused outright (`TestSuiteLifecycleError`) rather than silently accepted.

REUSE OVER REINVENT
--------------------
This module opens the real `evidence.duckdb` READ-ONLY
(`evidence_db.EvidenceStore(db_path, read_only=True)` -- the exact contract
`dv_harness/mcp/runtime.py`'s `ReadOnlyMcpContext` already relies on: DuckDB
itself refuses a write at the engine level in that mode) and reads its
`jobs`/`regression_verdicts` tables through that store's own generic
`query()` method -- the same read-back convention
`consolidated_kpi_benchmark.py`/`coverage_analysis.py`/
`protocol_compliance_aggregation.py` already use rather than a second SQL
layer. Golden-scenario capsules are `golden_scenario.load_golden_scenarios()`,
called verbatim -- never a second capsule reader. Table-existence checks
mirror `golden_scenario.py`'s own `_golden_scenario_rows()` (`duckdb_tables()`)
so an evidence.duckdb created before a table existed is read as "nothing
recorded there", never a crash.

This module decides, approves and arbitrates nothing beyond its own
classification: no build, job, or approval is touched, and there is
deliberately no stage gate."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import golden_scenario as gs
from .models import Status

# --- vocabulary --------------------------------------------------------

#: The core, ordered progression -- "GENERATED through CLOSURE_PROVEN".
#: Ordered earliest-to-latest; a pattern's own `lifecycle_state` is exactly
#: one of these, or the honest `STATE_UNKNOWN` below when no real evidence
#: exists for it at all.
#: Note: "RUNNING" is deliberately NOT used here even though it would read
#: naturally -- it collides with `dv_harness.models.Status.RUNNING`, and this
#: module's own vocabulary must share no token with that real stage-verdict
#: enum (checked at import by `_assert_no_verification_verdict_vocabulary()`).
#: `JOB_RUNNING` is the distinct spelling used instead.
CORE_LIFECYCLE_STATES: tuple = (
    "GENERATED",
    "SUBMITTED",
    "JOB_RUNNING",
    "EXECUTED_UNVERIFIED",
    "VERIFIED_FAIL",
    "VERIFIED_PASS",
    "CLOSURE_PROVEN",
)

#: A pattern with no real row in `jobs`, `regression_verdicts`, or
#: `golden_scenarios` reads this -- never a fabricated "generated".
STATE_UNKNOWN = "UNKNOWN"

#: The relationship tags -- never derived by this module, only recorded from
#: a caller-declared, evidence-cited fact. See module docstring.
RELATIONSHIP_KINDS: tuple = ("SEMANTIC_DUPLICATE", "SUBSUMED", "SUPERSET")

ALL_LIFECYCLE_STATES: tuple = CORE_LIFECYCLE_STATES + (STATE_UNKNOWN,)

# LSF status vocabulary this module recognizes -- lsf_client.JobState's own
# real values. Anything else (a status this module has never seen) degrades
# to GENERATED-with-a-named-reason rather than a guessed further state.
_LSF_DONE_LIKE = frozenset({"DONE", "EXIT"})
_LSF_RUNNING = "RUN"
_LSF_PENDING = "PEND"


def _assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status/relationship tokens must never collide with
    `dv_harness.models.Status` -- the same guard several sibling
    domain-vocabulary modules in this codebase already apply to themselves."""
    collision = set(ALL_LIFECYCLE_STATES) & {s.value for s in Status}
    if collision:
        raise AssertionError(
            f"test_suite_lifecycle vocabulary collides with models.Status: {sorted(collision)}")
    collision2 = set(RELATIONSHIP_KINDS) & {s.value for s in Status}
    if collision2:
        raise AssertionError(
            f"test_suite_lifecycle relationship vocabulary collides with models.Status: {sorted(collision2)}")


_assert_no_verification_verdict_vocabulary()


class TestSuiteLifecycleError(Exception):
    """A caller-declared relationship fact is malformed, uncited, or names a
    pattern/relation this module cannot honor."""


@dataclass
class PatternRelationship:
    """One caller-declared, evidence-cited relationship between two test
    patterns. Never derived by this module -- see module docstring."""
    pattern_a: str
    pattern_b: str
    relation: str
    evidence: str
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "pattern_a": self.pattern_a,
            "pattern_b": self.pattern_b,
            "relation": self.relation,
            "evidence": self.evidence,
            "reason": self.reason,
        }


def relationship_from_dict(raw: dict) -> PatternRelationship:
    if not isinstance(raw, dict):
        raise TestSuiteLifecycleError(f"relationship entry must be a dict, got {type(raw).__name__}")
    pattern_a = raw.get("pattern_a")
    pattern_b = raw.get("pattern_b")
    relation = raw.get("relation")
    evidence = raw.get("evidence")
    if not pattern_a or not isinstance(pattern_a, str):
        raise TestSuiteLifecycleError(f"relationship missing a real pattern_a: {raw!r}")
    if not pattern_b or not isinstance(pattern_b, str):
        raise TestSuiteLifecycleError(f"relationship missing a real pattern_b: {raw!r}")
    if relation not in RELATIONSHIP_KINDS:
        raise TestSuiteLifecycleError(
            f"relationship names an unrecognized relation {relation!r}; must be one of {RELATIONSHIP_KINDS}")
    if not evidence or not isinstance(evidence, str) or not evidence.strip():
        raise TestSuiteLifecycleError(
            f"relationship between {pattern_a!r} and {pattern_b!r} ({relation}) carries no real evidence "
            "citation -- an uncited relationship claim is refused, never silently accepted")
    return PatternRelationship(pattern_a=pattern_a, pattern_b=pattern_b, relation=relation,
                                evidence=evidence.strip(), reason=raw.get("reason"))


@dataclass
class PatternLifecycle:
    """One pattern's derived lifecycle state plus the real evidence behind
    it -- never just the bare state, so a reader can always check the claim."""
    pattern: str
    lifecycle_state: str
    reason: str
    job_count: int
    latest_lsf_status: Optional[str]
    regression_verdict_passed: Optional[bool]
    golden_capsule_ids: List[str] = field(default_factory=list)
    relationships: List[PatternRelationship] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "lifecycle_state": self.lifecycle_state,
            "reason": self.reason,
            "job_count": self.job_count,
            "latest_lsf_status": self.latest_lsf_status,
            "regression_verdict_passed": self.regression_verdict_passed,
            "golden_capsule_ids": list(self.golden_capsule_ids),
            "relationships": [r.to_dict() for r in self.relationships],
        }


def _table_exists(store, table_name: str) -> bool:
    """Mirrors golden_scenario.py's own `_golden_scenario_rows()` guard: an
    evidence.duckdb created before a table existed is read as "nothing
    recorded there", never a crash."""
    row = store.query(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [table_name])
    return bool(row)


def _fetch_jobs_by_pattern(store) -> Dict[str, List[dict]]:
    """pattern -> jobs rows (most-recent-`ingested_at`-first), read via the
    store's own generic `query()` method -- never a second SQL layer."""
    if not _table_exists(store, "jobs"):
        return {}
    cols = ["job_id", "pattern", "lsf_status", "sim_status", "ingested_at"]
    rows = store.query(
        f"SELECT {', '.join(cols)} FROM jobs WHERE pattern IS NOT NULL "
        "ORDER BY ingested_at DESC NULLS LAST, job_id DESC")
    by_pattern: Dict[str, List[dict]] = {}
    for row in rows:
        record = dict(zip(cols, row))
        by_pattern.setdefault(record["pattern"], []).append(record)
    return by_pattern


def _fetch_regression_verdicts(store) -> Dict[str, dict]:
    """pattern -> its one regression_verdicts row (a real PRIMARY KEY on
    pattern, so at most one row per pattern -- the "currently verified
    PASS/FAIL" snapshot regression.list's own semantics already carry)."""
    if not _table_exists(store, "regression_verdicts"):
        return {}
    cols = ["pattern", "verdict_passed", "job_id", "recorded_at"]
    rows = store.query(f"SELECT {', '.join(cols)} FROM regression_verdicts")
    return {row[0]: dict(zip(cols, row)) for row in rows}


def _fetch_golden_capsules_by_pattern(store) -> Dict[str, List[str]]:
    """test_name -> [capsule_id, ...], via golden_scenario.load_golden_
    scenarios() verbatim -- never a second capsule reader."""
    by_pattern: Dict[str, List[str]] = {}
    for capsule in gs.load_golden_scenarios(store):
        by_pattern.setdefault(capsule.test_name, []).append(capsule.capsule_id)
    return by_pattern


def derive_pattern_lifecycle(pattern: str, *, jobs_rows: Sequence[dict],
                              verdict_row: Optional[dict],
                              golden_capsule_ids: Sequence[str]) -> PatternLifecycle:
    """Derive one pattern's lifecycle state from its own real evidence only.

    Precedence (most-advanced-real-fact wins, never averaged):
      1. A real golden_scenario capsule exists for this pattern ->
         CLOSURE_PROVEN. record_golden_scenario() itself refuses to persist
         one unless it already proved a real PASS, so this is the strongest
         real fact this module can read.
      2. A regression_verdicts row exists (the CURRENT snapshot) -> its own
         verdict_passed decides VERIFIED_PASS / VERIFIED_FAIL.
      3. No verdict recorded yet -> read the most recent real jobs row's own
         lsf_status: DONE/EXIT -> EXECUTED_UNVERIFIED (LSF DONE is not DV
         PASS, per this project's own Core Operating Rules); RUN -> RUNNING;
         PEND -> SUBMITTED; anything else (including no lsf_status at all)
         -> GENERATED.
      4. No jobs row, no verdict row, no capsule -> UNKNOWN. Never
         fabricated as GENERATED."""
    if golden_capsule_ids:
        return PatternLifecycle(
            pattern=pattern, lifecycle_state="CLOSURE_PROVEN",
            reason=("a golden_scenario capsule (%s) is recorded for this pattern, citing a real "
                    "PASS evidence row -- evidence-gated by record_golden_scenario()"
                    % ", ".join(golden_capsule_ids)),
            job_count=len(jobs_rows),
            latest_lsf_status=(jobs_rows[0].get("lsf_status") if jobs_rows else None),
            regression_verdict_passed=(verdict_row.get("verdict_passed") if verdict_row else None),
            golden_capsule_ids=list(golden_capsule_ids))

    if verdict_row is not None and verdict_row.get("verdict_passed") is not None:
        passed = bool(verdict_row["verdict_passed"])
        state = "VERIFIED_PASS" if passed else "VERIFIED_FAIL"
        reason = (
            "regression_verdicts reports this pattern currently verified %s "
            "(mirrors regression.list's own one-pattern-per-line semantics)"
            % ("PASS" if passed else "FAIL"))
        return PatternLifecycle(
            pattern=pattern, lifecycle_state=state, reason=reason,
            job_count=len(jobs_rows),
            latest_lsf_status=(jobs_rows[0].get("lsf_status") if jobs_rows else None),
            regression_verdict_passed=passed, golden_capsule_ids=[])

    if not jobs_rows:
        return PatternLifecycle(
            pattern=pattern, lifecycle_state=STATE_UNKNOWN,
            reason="no jobs row, no regression_verdicts row, and no golden_scenario capsule "
                   "exist for this pattern -- nothing here is fabricated",
            job_count=0, latest_lsf_status=None, regression_verdict_passed=None,
            golden_capsule_ids=[])

    latest = jobs_rows[0]
    lsf_status = (latest.get("lsf_status") or "").strip().upper()
    if lsf_status in _LSF_DONE_LIKE:
        state = "EXECUTED_UNVERIFIED"
        reason = ("the most recent LSF job for this pattern reports lsf_status=%s, but no "
                   "regression_verdicts row exists yet -- LSF DONE is not equal to DV PASS"
                   % lsf_status)
    elif lsf_status == _LSF_RUNNING:
        state = "JOB_RUNNING"
        reason = "the most recent LSF job for this pattern reports lsf_status=RUN"
    elif lsf_status == _LSF_PENDING:
        state = "SUBMITTED"
        reason = "the most recent LSF job for this pattern reports lsf_status=PEND"
    else:
        state = "GENERATED"
        reason = ("a job record exists for this pattern with no recognized lsf_status yet"
                   if not lsf_status else
                   "a job record exists for this pattern with an unrecognized lsf_status (%r)"
                   % latest.get("lsf_status"))

    return PatternLifecycle(
        pattern=pattern, lifecycle_state=state, reason=reason,
        job_count=len(jobs_rows), latest_lsf_status=(latest.get("lsf_status")),
        regression_verdict_passed=None, golden_capsule_ids=[])


def build_test_suite_lifecycle_report(store, *,
                                       relationships: Optional[Sequence[dict]] = None) -> dict:
    """The whole-store report: every pattern this evidence store has ANY real
    row for (jobs, regression_verdicts, or golden_scenarios), each with its
    own derived lifecycle state, plus any caller-declared relationship facts
    attached to the patterns they name.

    `relationships` is a plain list of {"pattern_a", "pattern_b", "relation",
    "evidence", "reason"?} dicts -- see relationship_from_dict(). A
    relationship naming a pattern this report has no real evidence for at
    all (never seen in jobs/regression_verdicts/golden_scenarios) is refused
    -- attaching a relationship to a pattern nobody has evidence exists would
    itself be a fabricated claim."""
    jobs_by_pattern = _fetch_jobs_by_pattern(store)
    verdicts_by_pattern = _fetch_regression_verdicts(store)
    capsules_by_pattern = _fetch_golden_capsules_by_pattern(store)

    all_patterns = sorted(set(jobs_by_pattern) | set(verdicts_by_pattern) | set(capsules_by_pattern))

    parsed_relationships: List[PatternRelationship] = []
    for raw in (relationships or []):
        rel = relationship_from_dict(raw)
        for name in (rel.pattern_a, rel.pattern_b):
            if name not in all_patterns:
                raise TestSuiteLifecycleError(
                    f"relationship {rel.relation} between {rel.pattern_a!r} and {rel.pattern_b!r} "
                    f"names {name!r}, which has no real jobs/regression_verdicts/golden_scenario "
                    "evidence in this store -- refused rather than attached to a pattern nobody "
                    "has evidence exists")
        parsed_relationships.append(rel)

    rel_by_pattern: Dict[str, List[PatternRelationship]] = {}
    for rel in parsed_relationships:
        rel_by_pattern.setdefault(rel.pattern_a, []).append(rel)
        rel_by_pattern.setdefault(rel.pattern_b, []).append(rel)

    patterns_out: List[dict] = []
    state_counts: Dict[str, int] = {s: 0 for s in ALL_LIFECYCLE_STATES}
    for pattern in all_patterns:
        lc = derive_pattern_lifecycle(
            pattern,
            jobs_rows=jobs_by_pattern.get(pattern, []),
            verdict_row=verdicts_by_pattern.get(pattern),
            golden_capsule_ids=capsules_by_pattern.get(pattern, []))
        lc.relationships = rel_by_pattern.get(pattern, [])
        state_counts[lc.lifecycle_state] = state_counts.get(lc.lifecycle_state, 0) + 1
        patterns_out.append(lc.to_dict())

    return {
        "patterns": patterns_out,
        "pattern_count": len(all_patterns),
        "state_counts": state_counts,
        "relationship_count": len(parsed_relationships),
        "lifecycle_states": list(ALL_LIFECYCLE_STATES),
        "relationship_kinds": list(RELATIONSHIP_KINDS),
    }


def _open_store(root: Path, db_path: Optional[str]):
    """Mirrors golden_scenario.py's own `_open_store()`: a nonexistent
    evidence.duckdb reads as "nothing recorded", never a crash."""
    from .evidence_db import EvidenceStore, default_db_path
    path = Path(db_path) if db_path else default_db_path(root)
    if not path.exists():
        return None
    return EvidenceStore(path, read_only=True)


def derive_test_suite_lifecycle(root, *, db_path: Optional[str] = None,
                                 relationships: Optional[Sequence[dict]] = None) -> dict:
    """The one entry point a caller (this module's own dashboard card, the
    CLI below, or a test) needs: open the real evidence.duckdb read-only,
    build the report, close the store. Returns an honest
    {"available": False, "reason": ...} when no evidence database has ever
    been created for this project -- never a fabricated empty-but-clean
    report."""
    root = Path(root)
    store = _open_store(root, db_path)
    if store is None:
        from .evidence_db import default_db_path
        path = Path(db_path) if db_path else default_db_path(root)
        return {"available": False, "report": None,
                "reason": f"no evidence database at {path} -- no jobs, regressions, or golden "
                          "scenarios have ever been recorded for this project"}
    try:
        report = build_test_suite_lifecycle_report(store, relationships=relationships)
    finally:
        store.close()
    return {"available": True, "report": report, "reason": None}


# --- CLI / ad hoc front door -------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None):
    """`python -m dv_harness.test_suite_lifecycle [--root DIR] [--db-path PATH]
    [--relationships FILE.json] [--json]`. No `dv-harness` CLI verb is wired
    here -- `cli.py`/`gates.py` were left untouched, per this batch's own
    file-safety scope. Exit 0 when the report was built (regardless of
    content -- this is a report, not a pass/fail gate), 2 when no evidence
    database exists to report on."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog="dv_harness.test_suite_lifecycle")
    parser.add_argument("--root", default=".")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--relationships", default=None,
                         help="path to a JSON file of caller-declared relationship facts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    relationships = None
    if args.relationships:
        relationships = _json.loads(Path(args.relationships).read_text(encoding="utf-8"))
        if isinstance(relationships, dict) and "relationships" in relationships:
            relationships = relationships["relationships"]

    result = derive_test_suite_lifecycle(args.root, db_path=args.db_path, relationships=relationships)
    if args.json:
        print(_json.dumps(result, indent=2))
    else:
        if not result["available"]:
            print(f"NOT_AVAILABLE: {result['reason']}")
        else:
            r = result["report"]
            print(f"patterns: {r['pattern_count']}  relationships: {r['relationship_count']}")
            for k in ALL_LIFECYCLE_STATES:
                print(f"  {k}: {r['state_counts'].get(k, 0)}")
    return 0 if result["available"] else 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    import sys
    sys.exit(main())
