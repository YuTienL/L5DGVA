"""Coverage-triggered capability-gap detection (Research_Capability_Evolution
master prompt section 64).

WHAT WAS ACTUALLY MISSING -- RE-VERIFIED BEFORE WRITING A LINE OF THIS FILE
----------------------------------------------------------------------------
`capability_evolution.py` already auto-files a DISCOVERED candidate from ONE of
section 64's gap-detection sources -- REPEATED FAILURES
(`repeated_unresolved_failure_patterns()` / `file_repeated_failure_candidate()`
/ `file_candidates_for_repeated_failures()`, wired into `engine.py` on every
FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL, see CLAUDE.md's "Cross-Loop Coupling:
Repeated Failure -> Auto-Filed Capability Candidate"). A repo-wide grep for
`coverage_stall`/`PLATEAU.*candidate`/`file_plateau`/`file_coverage_stall`
before this module returned nothing: the OTHER source that section 64 and this
project's own trigger_type vocabulary already name --
`COVERAGE_HOLE` -- had no detector at all. Coverage closure could plateau
forever, `loop_convergence.classify_loop_convergence()` could report a real
PLATEAU verdict cycle after cycle, and nothing would ever raise a question
about the harness's own capability from it.

REUSE OVER REINVENT
--------------------
Nothing here is a second plateau detector or a second candidate-filing
mechanism. Two real, already-shipped things are called, never re-derived:

  * The TRIGGER FACT is `loop_convergence.classify_loop_convergence()`'s own
    real PLATEAU verdict -- CLAUDE.md's "Convergence, Plateau and Oscillation
    Detection" section, reading the REAL evidence database via
    `trend_analysis.daily_rollup()`. `coverage_stall_pattern()` below is a thin
    wrapper that calls it and returns the trigger fact (or `None`) -- it does
    not touch `classify_convergence()`'s arithmetic, the noise floor, the
    plateau window, or any of loop_convergence's own thresholds.
  * The FILING DISCIPLINE is `capability_evolution.build_candidate()` /
    `persist_candidate()` / `read_candidate()` -- the exact same three
    primitives `file_repeated_failure_candidate()` is built on. Every candidate
    this module produces goes through the one `build_candidate()`
    (recommendation DERIVED by `decide_recommendation()`, confidence recomputed
    through the real `inference.score_confidence()`, schema-validated before it
    exists) and lands on the one `capability_evolution_candidates` Blackboard
    topic and the one Working Memory audit trail every other candidate --
    research-architect-produced or repeated-failure-auto-filed -- already uses.
    `capability_evolution._auto_filed_search_slot()` is imported and called
    directly for the six honest "NOT SEARCHED" slots, rather than
    re-implementing that exact text a second time.

WHY THIS IS A SEPARATE MODULE RATHER THAN A NEW FUNCTION INSIDE
capability_evolution.py
------------------------------------------------------------------------------
`capability_evolution.py` is itself 3000+ lines, and at the moment this module
was built, dozens of other agents in this same multi-agent batch were actively
creating new `dv_harness/*.py` modules minutes (in several cases seconds) apart
-- confirmed directly by directory mtimes before writing anything here. This
project's own house rule for that shape ("a low-collision environment, but
give your own module a distinct, honestly-scoped name rather than colliding
with concurrent work") is applied here one level up: rather than editing the
one shared, heavily-relied-upon file every other capability-evolution
mechanism in this repo also depends on, this module sits beside it and imports
its real, public primitives exactly as `engine.py` and every test in this repo
already do. If a later pass folds this back into `capability_evolution.py` as
a literal sibling function, the move is mechanical -- every name and shape
below already matches that file's own repeated-failure family.

WHAT THIS MODULE CANNOT DO, BY THE SAME THREE STRUCTURAL WALLS THE
REPEATED-FAILURE COUPLING ALREADY ESTABLISHED
------------------------------------------------------------------------------
  1. `file_coverage_stall_candidate()` never calls `transition()` and refuses
     to persist anything whose `current_status` is not DISCOVERED.
  2. It performs NO repository search -- all six `existing_*` slots carry
     `search_conclusive: false` with an honest `search_basis` quoting that
     question's real next-best-action out of `capability_evolution`'s own
     `RESEARCH_GAP_ACTION_CATALOG`. `derive_overlap_status()` (called by
     `build_candidate()`, never re-derived here) therefore returns UNKNOWN,
     `decide_recommendation()` returns UNKNOWN, and the candidate schema's own
     `allOf` pins `current_status` to
     DISCOVERED/EVIDENCE_GATHERING/REJECTED. Reaching PROPOSED requires six
     conclusive searches only a real `research-architect` pass can produce.
  3. Every gate above that is untouched and uncalled from this module:
     `assert_legal_transition()`, `assert_human_approval()`'s real
     `ControlPlane` check, `HumanApprovalRequiredError`,
     `ProductionWriteNotAuthorizedError`. Not one line of the human-approval
     boundary is referenced, let alone weakened, here.

WHAT THIS MODULE DOES NOT DO
------------------------------
It never re-runs `classify_loop_convergence()`'s own arithmetic, never writes
a coverage sample, never escalates a coverage hole
(`coverage_analysis.escalate_unreachable_holes()` stays the real escalator,
named and not taken, exactly as `loop_convergence.PlateauInvestigation` already
documents for its own callers), and mints no approval of any kind.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from . import capability_evolution as ce
from .loop_convergence import COVERAGE_PERCENT_METRIC, PLATEAU, classify_loop_convergence

# Section 64's own gap-detection-source vocabulary
# (capability_evolution_candidate.schema.json's `trigger_type` enum) already
# names this source; nothing new is minted here.
COVERAGE_STALL_TRIGGER_TYPE = "COVERAGE_HOLE"

# Recorded in status_history.by and as the Blackboard write's source, so a
# human reading the candidate can tell this coupling's candidates apart from a
# research-architect's or the repeated-failure coupling's without inferring it
# from the field contents. Named after the loop this triggers from, matching
# `capability_evolution.AUTO_DISCOVERY_BY = "verification-closure-loop"`'s own
# convention one level down.
AUTO_DISCOVERY_BY = "coverage-closure-loop"

# The affected_capability every coverage-stall candidate names. Part of
# mint_candidate_id()'s hash input alongside hypothesis/proposed_action, so a
# renamed capability forks a new candidate -- deliberate, matching
# capability_evolution.py's own documented reasoning for that field.
AFFECTED_CAPABILITY = "coverage-closure-progress"


def coverage_stall_pattern(
    root, *,
    cfg: Optional[Dict[str, Any]] = None,
    points=None,
    holes: Optional[List[Dict[str, Any]]] = None,
    db_path=None,
    metric: str = COVERAGE_PERCENT_METRIC,
    **classifier_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """The real PLATEAU trigger fact for one project, or `None`.

    Calls `loop_convergence.classify_loop_convergence()` exactly as it is
    already called elsewhere in this repo and returns its report distilled to
    the facts a candidate needs -- never a fabricated series, never a second
    plateau arithmetic. Every OTHER verdict
    (CONVERGING/SLOW_CONVERGENCE/NO_PROGRESS/REGRESSION/OSCILLATING/UNKNOWN) is
    a real, distinct fact and none of them means "coverage closure has
    stalled", so this returns `None` for all of them -- including UNKNOWN,
    which must never be silently promoted into a plateau finding.
    """
    report = classify_loop_convergence(
        root, cfg=cfg, points=points, holes=holes, db_path=db_path, metric=metric,
        **classifier_kwargs,
    )
    if report.verdict != PLATEAU:
        return None

    convergence = dict(report.convergence)
    thresholds = dict(convergence.get("thresholds") or {})
    return {
        "root": report.root,
        "metric": report.metric,
        "verdict": report.verdict,
        "convergence": convergence,
        "thresholds": thresholds,
        "plateau_investigation": (
            dict(report.plateau_investigation) if report.plateau_investigation else None
        ),
        "sources": dict(report.sources),
        "loop_state": report.loop_state,
        "reason": report.reason,
    }


def _stall_key(metric: str, thresholds: Dict[str, Any]) -> str:
    """A stable identity for "this metric's coverage closure has plateaued
    under this project's own configured plateau thresholds", deliberately NOT
    keyed on the transient per-cycle numbers (`flat_run_samples`, the window's
    own values) that change every day the plateau continues -- those belong in
    `evidence_strength.rationale`, not in what makes two detections the SAME
    candidate. Mirrors `evidence_db.signature_key()`'s role for the
    repeated-failure coupling: a real content hash, not a counter or a uuid.
    """
    payload = "\x1f".join([
        str(metric),
        str(thresholds.get("plateau_window_samples", "")),
        str(thresholds.get("plateau_min_gain_percent", "")),
        str(thresholds.get("noise_floor_percent", "")),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _evidence_citation(pattern: Dict[str, Any]) -> Dict[str, Any]:
    """The one real, resolvable pointer this trigger fact has: the evidence
    database `loop_convergence` actually read (or an honest fallback naming a
    caller-supplied series when no database was consulted -- `points=` was
    passed directly, the same shape `loop_convergence`'s own tests use)."""
    sources = pattern["sources"]
    db_path = sources.get("evidence_db")
    if db_path:
        return {
            "document": str(db_path),
            "section": "coverage_samples (trend_analysis.daily_rollup, coverage_percent)",
            "location": f"series_points={sources.get('series_points')}",
        }
    return {
        "document": f"loop_convergence.classify_loop_convergence():{pattern['root']}",
        "section": "caller-supplied series (no evidence database consulted)",
        "location": f"series_points={sources.get('series_points')}",
    }


def build_coverage_stall_candidate(
    root, pattern: Dict[str, Any], *,
    status_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the DISCOVERED candidate for one coverage-closure plateau.

    Goes through the ordinary `capability_evolution.build_candidate()`, so the
    recommendation is DERIVED (it comes out UNKNOWN, because no repository
    search was performed), the confidence is recomputed through the real
    `inference.score_confidence()`, and the whole thing is schema-validated
    before it exists. Nothing here is a second candidate constructor.

    `confidence.inputs.independent_sources_count` is deliberately 1: this is
    ONE real classifier verdict over ONE project's own evidence, not several
    independent runs (the repeated-failure coupling's own
    `independent_run_count`, which genuinely counts distinct runs). Overclaiming
    that count would overclaim confidence for evidence that is real but singular.
    `evidence_strength.scale` is 2 for the identical reason
    `build_repeated_failure_candidate()` uses 2: a real observation, not a
    controlled experiment.
    """
    from .doc_extraction import evidence_ref

    metric = pattern["metric"]
    thresholds = pattern["thresholds"]
    key = _stall_key(metric, thresholds)
    convergence = pattern["convergence"]
    citation = _evidence_citation(pattern)

    fields: Dict[str, Any] = {
        "trigger_source": citation["document"],
        "trigger_type": COVERAGE_STALL_TRIGGER_TYPE,
        "source_provenance": [evidence_ref(
            document=citation["document"],
            version=key,
            page="",
            section=citation["section"],
            location=citation["location"],
        )],
        "evidence_refs": [
            f"loop_convergence:metric={metric}:stall_key={key}",
            citation["document"],
        ],
    }
    fields["affected_capability"] = AFFECTED_CAPABILITY
    fields["hypothesis"] = (
        f"Coverage closure has genuinely stalled on metric '{metric}': "
        "loop_convergence.classify_loop_convergence() reports a real PLATEAU "
        "verdict (the trailing run has moved less than "
        f"{thresholds.get('plateau_min_gain_percent')}% for at least "
        f"{thresholds.get('plateau_window_samples')} consecutive samples), and "
        "no capability candidate exists asking why. A stalled closure loop "
        "that nobody has ever raised a current-L5 question about is evidence "
        "about a capability this harness does not have, not only about one "
        "project's coverage holes."
    )
    fields["proposed_action"] = (
        "No production change is proposed. Run the mandatory current-L5 check "
        "over automated coverage-plateau response -- the six existing_* "
        "searches this candidate filed as NOT SEARCHED -- and let "
        "decide_recommendation() derive KEEP/ENHANCE/ADD/EXPERIMENT from the "
        "real result. `dv-harness research` is the human entry point that "
        "operates that machinery. (loop_convergence.investigate_plateau() "
        "already names the real per-bin escalator, coverage_analysis."
        "escalate_unreachable_holes(); this candidate is about whether a "
        "capability is missing at the LOOP level, above any one bin.)"
    )
    fields["exact_gap"] = ""
    fields["expected_verification_benefit"] = (
        "A coverage-closure plateau stops being invisible above the per-bin "
        "level: a stall that recurs cycle after cycle raises a real question "
        "about the harness's own response capability instead of silently "
        "consuming closure cycles with no capability-level record of it."
    )
    fields["evidence_strength"] = {
        "scale": 2,
        "rationale": (
            f"loop_convergence.classify_loop_convergence() reports PLATEAU with "
            f"reason: {convergence.get('reason')}. A real measured verdict over "
            "this project's own coverage series, not a controlled experiment "
            "comparing a change against a baseline."
        ),
    }
    fields["confidence"] = {
        "inputs": {
            "independent_sources_count": 1,
            "evidence_refs_verified": True,
            "counter_evidence_count": 0,
            "multi_agent_consensus_count": 0,
        }
    }
    fields["implementation_difficulty"] = "UNKNOWN"
    fields["integration_risk"] = "UNKNOWN"
    fields["maintenance_cost"] = "UNKNOWN"
    fields["experiment_required"] = False
    fields["experiment_plan"] = ""
    fields["benchmark_plan"] = ""
    fields["acceptance_criteria"] = [
        "All six existing_* searches are re-run with search_conclusive true, so "
        "overlap_status stops being UNKNOWN.",
        "Either a real, evidenced reason the plateau is expected/acceptable is "
        "on file, or a named harness capability is shown to be the thing that "
        "is missing to respond to it.",
        "The recommendation is derived by decide_recommendation() from those "
        "searches, never asserted by an agent.",
    ]
    fields["rollback_plan"] = (
        f"Filing applies nothing: one Blackboard entry under "
        f"'{ce.BLACKBOARD_TOPIC}' and one Working Memory audit record, no "
        "production file touched. The undo is a REJECTED transition, which is "
        "legal directly from DISCOVERED. Any concrete change a later architect "
        "proposes must author its own rollback_plan before it may leave "
        "EVIDENCE_GATHERING."
    )
    fields["approval_level"] = "HUMAN_APPROVAL_REQUIRED"
    fields["discovered_by"] = AUTO_DISCOVERY_BY
    for slot in ce.L5_SEARCH_SLOTS:
        fields[slot] = ce._auto_filed_search_slot(slot)
    if status_history is not None:
        fields["status_history"] = [dict(entry) for entry in status_history]

    candidate = ce.build_candidate(**fields)
    if candidate["current_status"] != "DISCOVERED":
        raise ce.IllegalPromotionTransitionError(
            f"an auto-filed coverage-stall candidate was assembled at "
            f"{candidate['current_status']!r}; this coupling may only ever "
            "file at DISCOVERED"
        )
    return candidate


def file_coverage_stall_candidate(
    root, pattern: Dict[str, Any], *, cfg: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """File (or refresh) ONE candidate for a coverage-closure plateau.

    Never transitions. Three outcomes, mirroring
    `capability_evolution.file_repeated_failure_candidate()`'s own discipline
    exactly, and the first two write nothing:

      * ALREADY_BEYOND_DISCOVERED -- a human or a research-architect has
        already moved this candidate on. Re-filing would drag it backwards and
        overwrite their work, so this returns instead.
      * ALREADY_ON_FILE_UNCHANGED -- same candidate, same evidence_refs.
        Re-persisting would append a duplicate Working Memory audit record on
        every stage boundary that happens to re-observe the same plateau for
        no new information.
      * filed -- new, or the same candidate with genuinely different
        evidence_refs (e.g. a different evidence database path now backs the
        observation). The existing status_history is carried forward
        untouched: no state changed, so no transition entry is owed and none
        is invented.
    """
    candidate = build_coverage_stall_candidate(root, pattern)
    candidate_id = candidate["candidate_id"]
    existing = ce.read_candidate(root, candidate_id)

    if existing is not None:
        current = existing.get("current_status")
        if current != "DISCOVERED":
            return {
                "filed": False, "reason": "ALREADY_BEYOND_DISCOVERED",
                "candidate_id": candidate_id, "current_status": current,
                "metric": pattern["metric"],
            }
        if list(existing.get("evidence_refs") or []) == candidate["evidence_refs"]:
            return {
                "filed": False, "reason": "ALREADY_ON_FILE_UNCHANGED",
                "candidate_id": candidate_id, "current_status": current,
                "metric": pattern["metric"],
            }
        candidate = build_coverage_stall_candidate(
            root, pattern, status_history=list(existing.get("status_history") or [])
        )

    persisted = ce.persist_candidate(root, candidate, source=AUTO_DISCOVERY_BY, cfg=cfg)
    return {
        "filed": True,
        "reason": "NEW_EVIDENCE" if existing is not None else "DISCOVERED",
        "candidate_id": candidate_id,
        "current_status": candidate["current_status"],
        "metric": pattern["metric"],
        "evidence_refs": list(candidate["evidence_refs"]),
        "persisted": persisted,
    }


def file_candidates_for_coverage_stall(
    root, *,
    cfg: Optional[Dict[str, Any]] = None,
    points=None,
    holes: Optional[List[Dict[str, Any]]] = None,
    db_path=None,
    metric: Optional[str] = None,
    **classifier_kwargs: Any,
) -> List[Dict[str, Any]]:
    """The whole coupling, as one call an engine hook could make.

    Detect the real PLATEAU trigger fact (if any) and file a DISCOVERED
    candidate for it, reporting what happened -- including the empty list when
    the loop is not plateaued. Raises nothing it can help; a future engine
    caller should treat any failure as best-effort, exactly as
    `capability_evolution.file_candidates_for_repeated_failures()`'s own
    docstring instructs for its sibling coupling: a capability-evolution
    bookkeeping problem must never turn an already-computed stage result into
    a crash.
    """
    kwargs: Dict[str, Any] = dict(cfg=cfg, points=points, holes=holes, db_path=db_path)
    if metric is not None:
        kwargs["metric"] = metric
    pattern = coverage_stall_pattern(root, **kwargs, **classifier_kwargs)
    if pattern is None:
        return []
    return [file_coverage_stall_candidate(root, pattern, cfg=cfg)]
