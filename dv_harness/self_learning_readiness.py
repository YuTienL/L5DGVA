"""dv_harness/self_learning_readiness.py -- CLAUDE.md section 55's SELF-LEARNING
READINESS MATRIX (22 rows), as a real, auto-generated artifact.

THE GAP THIS CLOSES
--------------------
`golden_flow_readiness.py` (section 47) already proved the pattern this module
copies: an aggregating readiness table is worth nothing if two audits of the
same project can disagree about the same facts, so every cell must be sourced
from an already-real reader rather than assembled by hand. That module's own
CLAUDE.md section explicitly disclosed the gap this module closes:

    "section 55's SELF-LEARNING READINESS MATRIX (22 rows over the
    research/capability-evolution and five-tier-memory surfaces) is NOT built
    by this module -- it is a different row set over different sources, and
    producing a half-sourced version of it would be the fabrication this
    module exists to prevent."

This module is that different row set over those different sources: it reads
`capability_evolution.py` (research ingestion, the 11-state promotion machine,
human approval, controlled-experiment benchmarking, shadow-replication
stability windows, repeated-failure auto-discovery, the candidate audit
trail), `memory.py` / `memory_router.py` (the five-tier store's index
integrity, the Engineering/Organizational admission gates re-verified against
what is actually stored, the revalidation/retraction/supersede/confirmation
surfaces MemoryGC owns, the Corner-Case Library), `confidence_calibration.py`
(whether this project's own confidence tiers hold up against their own
outcome history) and `cross_project_mining.py` (the registry and the
cross-project pattern miner). None of `golden_flow_readiness.py`'s twenty rows
are repeated here, and none of this module's rows are read through
`golden_flow_readiness.py`'s sources (`dashboard.py`, `gates.py`,
`env_manifest.py`) -- the two matrices are deliberately disjoint.

WHAT THIS MODULE IS NOT (same three boundaries `golden_flow_readiness.py`
draws, and for the same reasons)
-----------------------------------------------------------------------------
  * It DERIVES NOTHING an existing reader already supplies. Every row records
    the real function(s) its probe calls in `fact_source`, and
    `assert_fact_sources_resolvable()` proves each one still resolves through
    the import system -- a row claiming to read
    `memory_router.engineering_admission_gate` after that function is renamed
    away is a row whose provenance is fiction.
  * It WRITES NO STATE and RUNS NOTHING. No candidate is filed, no experiment
    is run, no memory record is added, retracted or confirmed, no approval is
    minted. Several of the real readers this module calls construct a class
    whose `__init__` unconditionally `mkdir()`s a directory (`MemoryStore`,
    `Blackboard`) or, worse, a class whose `load()` MINTS a default file when
    none exists (`ControlPlane.load()` writes a fresh `control.json`). Calling
    any of those on a project that has never used the surface being probed
    would make asking the question change the answer, so every such
    constructor is called ONLY after this module has independently confirmed,
    by a plain file-existence check, that the artifact it owns already exists
    on disk -- see `_gather_facts()`. A project that has never run reports 22
    honest UNKNOWNs, not 22 freshly-minted empty stores.
  * It APPROVES NOTHING. A READY verdict here is not
    `capability_evolution.assert_human_approval()`, is not a promotion to
    Organizational Memory, and authorizes no production write. Section 61's
    Level C boundary (`autonomy_levels.py`) is untouched and uncalled.

WHY THE STATUS VOCABULARY AND THE Next-Best-Action MECHANISM ARE BORROWED
---------------------------------------------------------------------------
READY/PARTIAL/BLOCKED/UNKNOWN is `subsystem_discovery`'s own four words,
reused verbatim exactly as `golden_flow_readiness.py` reuses them one level
up -- a third restatement of the same vocabulary would be the parallel
mechanism section 10 forbids. The Next-Best-Action column is produced by the
REAL `inference.next_best_action()` through its `gap_action_catalog`
parameter, the same domain-neutral engine `capability_evolution.py` and
`golden_flow_readiness.py` already drive with their own catalogs.

WHY THIS MODULE'S 22 ROW LABELS ARE ITS OWN DECLARATION, NOT A TRANSCRIPTION
------------------------------------------------------------------------------
`golden_flow_readiness.py` could transcribe section 47's exact twenty row
labels because section 47 names them one by one. Section 55 names the row
COUNT (22) and the two SURFACES (research/capability-evolution,
five-tier-memory) but not individual row labels -- there is no spec text to
transcribe them from. Claiming otherwise would itself be a fabrication.
`SELF_LEARNING_ROW_LABELS` below is therefore this module's own frozen
declaration of its 22 rows, checked at import time only against `ROWS` itself
(so a row cannot silently be dropped or renamed later), not against a
specification document that does not exist at that granularity.

WHAT REMAINS A REAL, DISCLOSED GAP (see also the CLAUDE.md section for this
module)
-----------------------------------------------------------------------------
This module is a REACHED capability (`python -m
dv_harness.self_learning_readiness` and its CLI wrapper below), not a WIRED
one: no `run_stage()`/`advance()` call site invokes it and no graph node
declares it, exactly as section 55's own residual text says of
`golden_flow_readiness.py`. It is proven against real, separately-constructed
project trees in `dv_harness_tests/test_self_learning_readiness.py`, never
against this repository claiming to be its own two-project cross-project
sample (`cross_project_mining.production_status()`'s own honesty disclosure
about this repo applies here unchanged).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from . import subsystem_discovery as sd

SCHEMA_VERSION = "1.0"

READY = sd.READY
PARTIAL = sd.PARTIAL
BLOCKED = sd.BLOCKED
UNKNOWN = sd.UNKNOWN
SELF_LEARNING_READINESS_CLASSES: tuple = sd.READINESS_CLASSES

_SEVERITY = {READY: 0, UNKNOWN: 1, PARTIAL: 2, BLOCKED: 3}

SELF_LEARNING_MATRIX_COLUMNS: tuple = (
    ("row", "Self-Learning Surface"),
    ("status", "Status"),
    ("evidence", "Evidence"),
    ("gap", "Gap"),
    ("next_best_action", "Next-Best-Action"),
)

NONE_CELL = "-"


class SelfLearningReadinessError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def combine_readiness(values) -> str:
    """Worst-wins over a set of readiness classes -- identical rule to
    `golden_flow_readiness.combine_readiness()`, restated locally rather than
    imported so this module carries no runtime dependency on the other
    matrix's internals (only on the shared `subsystem_discovery` vocabulary
    both are built from)."""
    vals = [v for v in (values or ()) if v]
    if not vals:
        return UNKNOWN
    for v in vals:
        if v not in _SEVERITY:
            raise SelfLearningReadinessError("UNKNOWN_READINESS_CLASS", {
                "value": v, "legal_values": list(SELF_LEARNING_READINESS_CLASSES)})
    if all(v == READY for v in vals):
        return READY
    if any(v == BLOCKED for v in vals):
        return BLOCKED
    if all(v == UNKNOWN for v in vals):
        return UNKNOWN
    return PARTIAL


# ===========================================================================
# Row declarations
# ===========================================================================

@dataclass(frozen=True)
class SelfLearningRowSpec:
    row_id: str
    label: str
    fact_source: Tuple[str, ...]
    basis: str


ROWS: Tuple[SelfLearningRowSpec, ...] = (
    SelfLearningRowSpec(
        "research_evidence_cards", "Research Evidence Cards",
        ("dv_harness.capability_evolution.read_evidence_cards",
         "dv_harness.capability_evolution.prior_research_relations"),
        "Every `*.card.json` filed under research/evidence_cards/, read through "
        "capability_evolution's own reader rather than a second directory walk."),
    SelfLearningRowSpec(
        "prior_research_links", "Prior-Research Contradiction / Supersede Links",
        ("dv_harness.capability_evolution.PRIOR_RESEARCH_LINK_MEMORY_KIND",
         "dv_harness.memory.MemoryStore.find"),
        "Section 28's cross-card comparisons, persisted as `research_claim` Working "
        "Memory records by persist_prior_research_links(); this row reads them back "
        "rather than re-deriving a relation."),
    SelfLearningRowSpec(
        "l5_check_completeness", "Current-L5 Check Completeness (10 Questions)",
        ("dv_harness.capability_evolution.unanswered_l5_check_questions",
         "dv_harness.capability_evolution.read_candidates"),
        "Section 14's ten-question REUSE-before-ADD check, per live candidate on the "
        "capability_evolution_candidates Blackboard topic."),
    SelfLearningRowSpec(
        "overlap_recommendation_decisions", "Overlap / Recommendation Decisions",
        ("dv_harness.capability_evolution.read_candidates",
         "dv_harness.capability_evolution.RECOMMENDATIONS"),
        "decide_recommendation()'s own KEEP/ENHANCE/ADD/EXPERIMENT/REJECT/UNKNOWN "
        "vocabulary, read off each candidate's own stored `recommendation` field."),
    SelfLearningRowSpec(
        "promotion_state_governance", "Promotion-State Governance (11-State Machine)",
        ("dv_harness.blackboard.Blackboard.capability_evolution_counts",
         "dv_harness.capability_evolution.PROMOTION_STATES"),
        "Section 70's eleven governance states, counted per real candidate by the "
        "Blackboard's own capability_evolution_counts() rather than a second tally."),
    SelfLearningRowSpec(
        "human_approval_gate", "Human Approval Gate (RESEARCH_CAPABILITY_EVOLUTION)",
        ("dv_harness.capability_evolution.human_approval_status",),
        "The LEVEL B -> LEVEL C boundary's real ControlPlane-backed state, read "
        "through human_approval_status() -- never a second approval mechanism."),
    SelfLearningRowSpec(
        "controlled_experiment_benchmark", "Controlled-Experiment Benchmark Evidence",
        ("dv_harness.capability_evolution.read_candidates",
         "dv_harness.capability_evolution.BENCHMARK_OUTCOMES"),
        "Section 133's before/after arm comparison, read from each candidate's own "
        "`benchmark_result` -- only run_controlled_experiment() ever writes that field."),
    SelfLearningRowSpec(
        "shadow_replication_stability", "Shadow-Replication Stability Window",
        ("dv_harness.capability_evolution.stability_window_status",
         "dv_harness.capability_evolution.BENCHMARKED_STATE"),
        "Section 134's 'a single successful shadow run is not sufficient proof', "
        "re-checked live per BENCHMARKED candidate through stability_window_status()."),
    SelfLearningRowSpec(
        "production_rollback_history", "Production Rollback History",
        ("dv_harness.capability_evolution.read_candidates",
         "dv_harness.capability_evolution.PRODUCTION_WRITE_AUTHORIZED_STATES"),
        "Every candidate that ever reached PRODUCTION or ROLLED_BACK, and whether "
        "each still carries the non-empty rollback_plan section 134 requires."),
    SelfLearningRowSpec(
        "repeated_failure_auto_filed", "Repeated-Failure Auto-Filed Candidates",
        ("dv_harness.capability_evolution.repeated_unresolved_failure_patterns",
         "dv_harness.capability_evolution.AUTO_DISCOVERY_BY"),
        "Section 64's cross-loop coupling: real repeated, unresolved Job Memory "
        "failure signatures versus how many DISCOVERED candidates the verification "
        "closure loop has actually auto-filed for them."),
    SelfLearningRowSpec(
        "candidate_decision_audit_trail", "Candidate Decision Audit Trail",
        ("dv_harness.capability_evolution.candidate_audit_records",),
        "The Working Memory audit trail persist_candidate() writes alongside every "
        "Blackboard transition, read through the shared MemoryStore.find()."),
    SelfLearningRowSpec(
        "architecture_decision_history", "Architecture Decision History",
        ("dv_harness.memory_router.ARCHITECTURE_DECISION_KIND",
         "dv_harness.memory.MemoryStore.find"),
        "Section 12's Project-tier `architecture_decision` kind -- a DECIDED L5.x "
        "proposal, read back rather than re-derived from a live candidate."),
    SelfLearningRowSpec(
        "memory_index_integrity", "Memory Index Integrity",
        ("dv_harness.memory.MemoryStore.index_integrity",),
        "The real drift report between per-tier record FILES and index.json's rows "
        "-- the same check memory_doctor's memory_store_index finding backs."),
    SelfLearningRowSpec(
        "engineering_admission_health", "Engineering-Tier Admission Health",
        ("dv_harness.memory_router.engineering_admission_gate",
         "dv_harness.memory.MemoryStore.find"),
        "Every real Engineering-tier record, RE-VERIFIED against the same "
        "engineering_admission_gate() route_and_store() ran at write time -- a "
        "record that no longer clears its own admission gate is a real drift, not "
        "a hypothetical one."),
    SelfLearningRowSpec(
        "organizational_admission_health", "Organizational-Tier Admission Health",
        ("dv_harness.memory_router.organizational_admission_gate",
         "dv_harness.memory.MemoryStore.find"),
        "The Organizational-tier counterpart of the row above, through "
        "organizational_admission_gate()'s own store-backed re-check of provenance, "
        "confirmation count and confidence."),
    SelfLearningRowSpec(
        "revalidation_queue", "Revalidation Queue",
        ("dv_harness.memory.MemoryGC.flag_stale", "dv_harness.memory.MemoryStore.find"),
        "Every record MemoryGC.flag_stale() has marked NEEDS_REVALIDATION and no "
        "later MemoryGC.confirm() has restored to ACTIVE."),
    SelfLearningRowSpec(
        "retraction_supersede_ledger", "Retraction / Supersede Ledger",
        ("dv_harness.memory.MemoryGC.retract", "dv_harness.memory.MemoryGC.supersede",
         "dv_harness.memory.MemoryStore.find"),
        "Every RETRACTED ('found wrong, no replacement') and SUPERSEDED ('a newer, "
        "corrected record replaces this one') record, MemoryGC's own two contradiction "
        "outcomes."),
    SelfLearningRowSpec(
        "confirmed_conclusion_accumulation", "Confirmed-Conclusion Accumulation",
        ("dv_harness.memory.MemoryConsolidator.from_closed_finding",
         "dv_harness.memory.MemoryGC.confirm", "dv_harness.memory.MemoryStore.find"),
        "CONFIRMED-tier Engineering records and every record whose confirmation_count "
        "MemoryGC.confirm() has raised above zero -- the accumulation mechanism "
        "confidence_calibration.py reads back one level up."),
    SelfLearningRowSpec(
        "corner_case_library", "Corner-Case Library",
        ("dv_harness.memory.CornerCaseLibrary.add",),
        "The cross-project stimulus/configuration-pattern store's own index.json, "
        "read directly rather than through a constructor that would mkdir a store "
        "for a project that never used it."),
    SelfLearningRowSpec(
        "confidence_tier_calibration", "Confidence Tier Calibration",
        ("dv_harness.confidence_calibration.calibrate",),
        "VI-1's own calibration engine: whether this project's CONFIRMED/HIGH/"
        "MEDIUM/LOW tiers hold up against their own recorded VERIFIED/REJECTED "
        "outcome history."),
    SelfLearningRowSpec(
        "cross_project_registry", "Cross-Project Registry",
        ("dv_harness.cross_project_mining.production_status",),
        "VI-2's own honest production-status reader: how many genuinely independent "
        "projects are registered and readable, never inflated by counting one store "
        "twice."),
    SelfLearningRowSpec(
        "cross_project_pattern_mining", "Cross-Project Pattern Mining",
        ("dv_harness.cross_project_mining.mine_cross_project_patterns",
         "dv_harness.cross_project_mining.ProjectRegistry.roots"),
        "A real, pure-read mining pass over every registered project's own memory "
        "store -- never a promotion, never a write of any kind."),
)


def row_ids() -> List[str]:
    return [r.row_id for r in ROWS]


def row_labels() -> List[str]:
    return [r.label for r in ROWS]


#: This module's OWN frozen 22-row declaration -- see the module docstring for
#: why this is not a transcription of section 55 (which names no individual
#: row labels) the way golden_flow_readiness.SECTION_47_ROW_LABELS is a
#: transcription of section 47. The check below still catches a row silently
#: dropped, renamed or duplicated after this module was written.
SELF_LEARNING_ROW_LABELS: tuple = tuple(r.label for r in ROWS)


def _assert_22_rows_declared() -> None:
    if len(ROWS) != 22:
        raise SelfLearningReadinessError("ROW_COUNT_IS_NOT_22", {
            "declared_count": len(ROWS),
            "hint": "CLAUDE.md section 55 mandates exactly 22 rows"})
    ids = [r.row_id for r in ROWS]
    if len(set(ids)) != len(ids):
        raise SelfLearningReadinessError("DUPLICATE_ROW_ID", {"row_ids": ids})
    labels = [r.label for r in ROWS]
    if len(set(labels)) != len(labels):
        raise SelfLearningReadinessError("DUPLICATE_ROW_LABEL", {"labels": labels})


_assert_22_rows_declared()


# ===========================================================================
# Gap -> Next-Best-Action catalog
# ===========================================================================

SELF_LEARNING_GAP_ACTION_CATALOG: Dict[str, Any] = {
    "source": "self_learning_readiness_row",
    "fallback": (
        "no next action is registered for '{gap}' -- name the missing evidence and "
        "the real command that would produce it before treating this row as closed"
    ),
    "actions": {
        "research_evidence_cards": (
            "run `dv-harness research <document>` to ingest a real external document "
            "through research-ingestion; a card is filed at research/evidence_cards/"),
        "prior_research_links": (
            "with two or more evidence cards on disk, run the research-architect's "
            "cross-document comparison (link_prior_research() + "
            "persist_prior_research_links()) so section 28's overlap/contradiction "
            "links are actually persisted"),
        "l5_check_completeness": (
            "for each candidate, complete the six existing_* searches "
            "(agent/skill/graph-node/state/memory/files) L5_SEARCH_SLOTS names -- "
            "q1/q2 cannot be answered any other way"),
        "overlap_recommendation_decisions": (
            "finish the current-L5 check first (see l5_check_completeness); "
            "decide_recommendation() derives the recommendation from it and refuses "
            "to guess while a search is inconclusive"),
        "promotion_state_governance": (
            "advance a DISCOVERED candidate through capability_evolution.transition(); "
            "a status outside PROMOTION_STATES means the Blackboard record was hand-"
            "edited and needs repair, not a transition"),
        "human_approval_gate": (
            "a human runs: dv-harness approve RESEARCH_CAPABILITY_EVOLUTION --note "
            "'<what you are approving>' --reviewer-id <you> --reviewer-confidence "
            "HIGH|MEDIUM|LOW"),
        "controlled_experiment_benchmark": (
            "run capability_evolution.run_controlled_experiment() on an "
            "EXPERIMENTING candidate over an isolated fixture; only its own output "
            "may populate benchmark_result"),
        "shadow_replication_stability": (
            "run capability_evolution.run_shadow_replication() again over the same "
            "arms and stages until stability_window_status() reports established -- "
            "section 134 requires at least 2 agreeing, regression-safe runs"),
        "production_rollback_history": (
            "a candidate reaching PRODUCTION or ROLLED_BACK must carry a non-empty "
            "rollback_plan; author one before transition() moves it further"),
        "repeated_failure_auto_filed": (
            "run capability_evolution.file_candidates_for_repeated_failures() so "
            "every qualifying repeated pattern gets a real DISCOVERED candidate on "
            "the Blackboard, not just a detected pattern"),
        "candidate_decision_audit_trail": (
            "persist_candidate() writes this automatically on every transition; an "
            "empty trail with live candidates on the Blackboard means a write path "
            "bypassed persist_candidate()"),
        "architecture_decision_history": (
            "route a decided L5.x architecture proposal through "
            "memory_router.route_and_store() with kind=architecture_decision so it "
            "lands in Project Memory rather than staying conversational"),
        "memory_index_integrity": (
            "run `dv-harness memory doctor` (memory_doctor.check_index_integrity) and "
            "MemoryStore.reindex() to repair drift between index.json and the real "
            "per-tier record files"),
        "engineering_admission_health": (
            "a record that no longer clears engineering_admission_gate() has drifted "
            "since it was admitted (e.g. reusable/confidence hand-edited); "
            "MemoryGC.deprecate() it rather than leaving a falsely-trusted record live"),
        "organizational_admission_health": (
            "a record that no longer clears organizational_admission_gate() has lost "
            "its source engineering record, its confirmation count, or its stamped "
            "HIGH confidence result -- investigate before trusting it further"),
        "revalidation_queue": (
            "for each NEEDS_REVALIDATION record, get fresh independent evidence and "
            "call MemoryGC.confirm() (restores ACTIVE) or MemoryGC.retract()/"
            "supersede() if it does not hold up"),
        "confirmed_conclusion_accumulation": (
            "route a CLOSED/VERIFIED finding through "
            "MemoryConsolidator.from_closed_finding() with real single_sim PASS + "
            "regression PASS/NOT_REQUIRED + reaudit CLEAN evidence"),
        "corner_case_library": (
            "add a real, evidence-backed stimulus pattern through "
            "CornerCaseLibrary.add() or CornerCaseLibraryConsolidator, never a "
            "hand-written index row; a record file with no index row needs its "
            "index.json rebuilt from the real *.json files in that directory"),
        "confidence_tier_calibration": (
            "record real outcomes against tiered conclusions -- MemoryGC.confirm() "
            "on an independent re-derivation, MemoryGC.retract()/supersede() on a "
            "refuted one -- until at least one tier reaches "
            "MIN_DETERMINATE_OUTCOMES_PER_TIER"),
        "cross_project_registry": (
            "register a second genuinely independent project's root via "
            "cross_project_mining.ProjectRegistry(root).register(other_root); a "
            "root sharing a memory_id with one already registered is refused, not "
            "silently accepted"),
        "cross_project_pattern_mining": (
            "with 2+ readable registered projects, run "
            "`python -m dv_harness.cross_project_mining` (or "
            "mine_registered_projects()) to produce a real cross-project result"),
    },
}


def _next_best_actions(root: Path, gaps: List[str]) -> Dict[str, str]:
    if not gaps:
        return {}
    from .inference import next_best_action
    results = next_best_action(None, gaps, root,
                               gap_action_catalog=SELF_LEARNING_GAP_ACTION_CATALOG)
    return {r["gap"]: r["suggested_action"] for r in results}


# ===========================================================================
# Fact gathering. Every constructor below that mkdir()s or mints a file on
# construction (MemoryStore, Blackboard, ControlPlane) is called ONLY after
# confirming, via a plain file-existence check, that the artifact it owns
# already exists -- see the module docstring's second boundary.
# ===========================================================================

@dataclass
class _Facts:
    root: Path
    memory_available: bool
    store: Optional[Any]
    blackboard_available: bool
    candidates: Dict[str, Any] = field(default_factory=dict)
    control_available: bool = False


#: The exact filename Blackboard._path() derives for a topic with no '/' in
#: its name -- `t.strip('/').replace('/', '__') + '.json'` collapses to
#: `<topic>.json` when `t` carries no slash, which is true of
#: capability_evolution.BLACKBOARD_TOPIC. Read here as a plain path so this
#: module never has to construct Blackboard() (which mkdir()s the whole
#: blackboard/ directory) just to ask whether it has ever been used.
def _blackboard_candidates_path(root: Path) -> Path:
    from .capability_evolution import BLACKBOARD_TOPIC
    return root / ".dv-harness" / "blackboard" / f"{BLACKBOARD_TOPIC}.json"


def _gather_facts(root) -> _Facts:
    from .cross_project_mining import has_memory_store

    root = Path(root)
    memory_available = has_memory_store(root)
    store = None
    if memory_available:
        # Safe: has_memory_store() already proved index.json exists, so this
        # constructor's mkdir(parents=True, exist_ok=True) is a real no-op and
        # its "if not index_file.exists(): write '[]'" branch is not taken.
        from .memory import MemoryStore
        store = MemoryStore(root)

    blackboard_path = _blackboard_candidates_path(root)
    blackboard_available = blackboard_path.is_file()
    candidates: Dict[str, Any] = {}
    if blackboard_available:
        from .capability_evolution import read_candidates
        candidates = read_candidates(root)

    control_available = (root / ".dv-harness" / "control.json").is_file()

    return _Facts(root=root, memory_available=memory_available, store=store,
                  blackboard_available=blackboard_available, candidates=candidates,
                  control_available=control_available)


# ===========================================================================
# Per-row probes. Contract, held by every probe below: returns
# {"status", "evidence", "gap"}; reads only through the readers named in the
# row's own fact_source (plus a small number of direct, guarded file reads
# documented above); never raises for a project that has never used the
# surface -- absence is a verdict (UNKNOWN, with a gap naming what is
# absent), not an error.
# ===========================================================================

def _probe_research_evidence_cards(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import read_evidence_cards
    cards = read_evidence_cards(facts.root)
    if not cards:
        return {"status": UNKNOWN, "evidence": "0 research evidence card(s) on disk",
                "gap": "no research document has been ingested into "
                       "research/evidence_cards/ yet"}
    with_id = sum(1 for c in cards if str(c.get("document_id") or "").strip())
    ev = f"{len(cards)} card(s) filed; {with_id} carry a document_id"
    if with_id < len(cards):
        return {"status": PARTIAL, "evidence": ev,
                "gap": f"{len(cards) - with_id} card(s) missing document_id"}
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_prior_research_links(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import PRIOR_RESEARCH_LINK_MEMORY_KIND, read_evidence_cards
    cards = read_evidence_cards(facts.root)
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": f"{len(cards)} evidence card(s); no memory "
                                                f"store on disk",
                "gap": "no cross-document comparison can have been persisted yet"}
    links = facts.store.find("working", kind=PRIOR_RESEARCH_LINK_MEMORY_KIND)
    if not links:
        return {"status": UNKNOWN,
                "evidence": f"0 comparison record(s); {len(cards)} evidence card(s) on disk",
                "gap": "no cross-card comparison has been persisted "
                       "(persist_prior_research_links())"}
    relations: Dict[str, int] = {}
    for link in links:
        r = str(link.get("relation") or "UNKNOWN")
        relations[r] = relations.get(r, 0) + 1
    ev = f"{len(links)} comparison record(s): " + ", ".join(
        f"{k}={v}" for k, v in sorted(relations.items()))
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_l5_check_completeness(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import L5_CHECK_QUESTIONS, unanswered_l5_check_questions
    if not facts.candidates:
        return {"status": UNKNOWN, "evidence": "0 capability-evolution candidate(s) on "
                                                "the Blackboard",
                "gap": "no candidate has been discovered yet"}
    total = len(facts.candidates)
    complete = 0
    worst = 0
    for cand in facts.candidates.values():
        unanswered = unanswered_l5_check_questions(cand)
        if not unanswered:
            complete += 1
        worst = max(worst, len(unanswered))
    ev = (f"{complete}/{total} candidate(s) have answered all "
          f"{len(L5_CHECK_QUESTIONS)} L5-check questions")
    if complete == total:
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": PARTIAL, "evidence": ev,
            "gap": f"{total - complete} candidate(s) leave up to {worst} question(s) "
                   "unanswered"}


def _probe_overlap_recommendation(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    if not facts.candidates:
        return {"status": UNKNOWN, "evidence": "0 candidate(s) recorded",
                "gap": "no candidate has been discovered yet"}
    total = len(facts.candidates)
    counts: Dict[str, int] = {}
    for cand in facts.candidates.values():
        rec = str(cand.get("recommendation") or "UNKNOWN")
        counts[rec] = counts.get(rec, 0) + 1
    unknown_n = counts.get("UNKNOWN", 0)
    ev = f"{total} candidate(s): " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    if unknown_n == 0:
        return {"status": READY, "evidence": ev, "gap": ""}
    if unknown_n == total:
        return {"status": UNKNOWN, "evidence": ev,
                "gap": "every candidate's current-L5 check is incomplete"}
    return {"status": PARTIAL, "evidence": ev,
            "gap": f"{unknown_n} candidate(s) still resolve to UNKNOWN"}


def _probe_promotion_state_governance(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .blackboard import Blackboard
    from .capability_evolution import PROMOTION_STATES
    if not facts.blackboard_available:
        return {"status": UNKNOWN,
                "evidence": "no capability_evolution_candidates topic on the Blackboard",
                "gap": "no candidate has ever been filed"}
    counts = Blackboard(facts.root).capability_evolution_counts()
    total = counts.get("total", 0)
    by_status = counts.get("by_status", {}) or {}
    if total == 0:
        return {"status": UNKNOWN, "evidence": "0 candidate(s)",
                "gap": "no candidate has ever been filed"}
    bad = sorted(s for s in by_status if s not in PROMOTION_STATES)
    ev = f"{total} candidate(s): " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
    if bad:
        return {"status": BLOCKED, "evidence": ev,
                "gap": f"{bad} is/are not a legal section-70 promotion state"}
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_human_approval_gate(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import HUMAN_APPROVAL_STAGE, human_approval_status
    if not facts.control_available:
        return {"status": UNKNOWN, "evidence": "no .dv-harness/control.json on disk",
                "gap": f"no human approval has ever been recorded for "
                       f"{HUMAN_APPROVAL_STAGE}"}
    status = human_approval_status(facts.root)
    ev = (f"approved={status['approved']}; paused={status['paused']}; "
          f"{len(status['history'])} approval_history entr(y/ies)")
    if status["approved"]:
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": PARTIAL, "evidence": ev,
            "gap": f"no active approval for {HUMAN_APPROVAL_STAGE}; run: "
                   f"{status['approve_command']}"}


def _probe_controlled_experiment_benchmark(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import BENCHMARK_OUTCOMES
    if not facts.candidates:
        return {"status": UNKNOWN, "evidence": "0 candidate(s) recorded",
                "gap": "no candidate has been discovered yet"}
    measured = [c for c in facts.candidates.values()
                if isinstance(c.get("benchmark_result"), dict)]
    if not measured:
        return {"status": UNKNOWN,
                "evidence": f"0/{len(facts.candidates)} candidate(s) carry a "
                            "benchmark_result",
                "gap": "no controlled experiment has been run yet "
                       "(run_controlled_experiment())"}
    outcomes: Dict[str, int] = {}
    off_vocab: List[str] = []
    for cand in measured:
        outcome = str(cand["benchmark_result"].get("outcome"))
        if outcome not in BENCHMARK_OUTCOMES:
            off_vocab.append(outcome)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    ev = (f"{len(measured)}/{len(facts.candidates)} candidate(s) measured: "
          + ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())))
    if off_vocab:
        return {"status": BLOCKED, "evidence": ev,
                "gap": f"benchmark_result.outcome off-vocabulary: {sorted(set(off_vocab))}"}
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_shadow_replication_stability(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import BENCHMARKED_STATE, stability_window_status
    if not facts.candidates:
        return {"status": UNKNOWN, "evidence": "0 candidate(s) recorded",
                "gap": "no candidate has been discovered yet"}
    benchmarked = [c for c in facts.candidates.values()
                   if c.get("current_status") == BENCHMARKED_STATE]
    if not benchmarked:
        return {"status": UNKNOWN, "evidence": f"0 candidate(s) at {BENCHMARKED_STATE}",
                "gap": f"no candidate has reached {BENCHMARKED_STATE} yet"}
    established = 0
    blockers: List[str] = []
    for cand in benchmarked:
        try:
            status = stability_window_status(facts.root, cand)
        except Exception as e:  # a corrupt run record must not delete the row
            blockers.append(f"{cand.get('candidate_id')}: stability read failed: {e}")
            continue
        if status["established"]:
            established += 1
        else:
            blockers.append(f"{cand.get('candidate_id')}: " + "; ".join(status["blockers"][:1]))
    ev = (f"{established}/{len(benchmarked)} {BENCHMARKED_STATE} candidate(s) have an "
          "established stability window")
    if established == len(benchmarked):
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": PARTIAL, "evidence": ev, "gap": "; ".join(blockers[:3])}


def _probe_production_rollback_history(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    if not facts.candidates:
        return {"status": UNKNOWN, "evidence": "0 candidate(s) recorded",
                "gap": "no candidate has been discovered yet"}
    in_prod = [c for c in facts.candidates.values()
               if c.get("current_status") in ("PRODUCTION", "ROLLED_BACK")]
    if not in_prod:
        return {"status": UNKNOWN,
                "evidence": "0 candidate(s) have ever reached PRODUCTION or ROLLED_BACK",
                "gap": "no candidate has been promoted to production yet"}
    missing_plan = [c.get("candidate_id") for c in in_prod
                    if not str(c.get("rollback_plan") or "").strip()]
    ev = f"{len(in_prod)} candidate(s) at PRODUCTION/ROLLED_BACK"
    if missing_plan:
        return {"status": BLOCKED, "evidence": ev,
                "gap": f"rollback_plan empty for: {missing_plan}"}
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_repeated_failure_auto_filed(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import (
        AUTO_DISCOVERY_BY, REPEAT_FAILURE_MIN_OCCURRENCES,
        repeated_unresolved_failure_patterns,
    )
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "no job_failure evidence has been recorded yet"}
    patterns = repeated_unresolved_failure_patterns(facts.root)
    auto_filed = 0
    if facts.candidates:
        for cand in facts.candidates.values():
            history = cand.get("status_history") or []
            if history and history[0].get("by") == AUTO_DISCOVERY_BY:
                auto_filed += 1
    ev = (f"{len(patterns)} repeated unresolved failure pattern(s) "
          f"(>= {REPEAT_FAILURE_MIN_OCCURRENCES} independent runs); "
          f"{auto_filed} auto-filed candidate(s) on the Blackboard")
    if not patterns:
        return {"status": READY, "evidence": ev, "gap": ""}
    if auto_filed >= len(patterns):
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": PARTIAL, "evidence": ev,
            "gap": f"{len(patterns)} repeated pattern(s) detected but only "
                   f"{auto_filed} auto-filed candidate(s) on record -- some may not "
                   "have been auto-filed yet"}


def _probe_candidate_decision_audit_trail(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .capability_evolution import candidate_audit_records
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "no candidate audit record has ever been written"}
    records = candidate_audit_records(facts.root)
    if not records:
        return {"status": UNKNOWN, "evidence": "0 Working-Memory audit record(s)",
                "gap": "no capability-evolution candidate has ever been persisted"}
    distinct = len({r.get("candidate_id") for r in records})
    return {"status": READY,
            "evidence": f"{len(records)} audit record(s) across {distinct} candidate(s)",
            "gap": ""}


def _probe_architecture_decision_history(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from . import memory_router as mr
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "no architecture_decision record has ever been written"}
    records = facts.store.find("project", kind=mr.ARCHITECTURE_DECISION_KIND)
    if not records:
        return {"status": UNKNOWN, "evidence": "0 architecture_decision record(s) in "
                                                "Project Memory",
                "gap": "no L5.x architecture proposal has been decided and recorded yet"}
    return {"status": READY,
            "evidence": f"{len(records)} architecture_decision record(s) in Project Memory",
            "gap": ""}


def _probe_memory_index_integrity(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "the store has never been written to"}
    integrity = facts.store.index_integrity()
    ev = (f"{integrity['index_row_count']} index row(s), "
          f"{integrity['record_file_count']} record file(s)")
    if integrity["ok"]:
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": BLOCKED, "evidence": ev,
            "gap": f"{len(integrity['files_missing_from_index'])} file(s) missing from "
                   f"index, {len(integrity['index_rows_without_file'])} index row(s) with "
                   "no file"}


def _probe_engineering_admission_health(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .memory_router import engineering_admission_gate
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "no engineering-tier record exists yet"}
    records = facts.store.find("engineering")
    if not records:
        return {"status": UNKNOWN, "evidence": "0 engineering-tier record(s)",
                "gap": "no record has ever been admitted to Engineering Memory"}
    admitted = 0
    reasons: List[str] = []
    for rec in records:
        ok, why = engineering_admission_gate(rec, facts.root)
        if ok:
            admitted += 1
        else:
            reasons.extend(why)
    ev = f"{admitted}/{len(records)} engineering-tier record(s) still clear the gate"
    if admitted == len(records):
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": BLOCKED, "evidence": ev,
            "gap": f"{len(records) - admitted} record(s) no longer clear "
                   f"engineering_admission_gate(): {sorted(set(reasons))}"}


def _probe_organizational_admission_health(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from .memory_router import organizational_admission_gate
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "no organizational-tier record exists yet"}
    records = facts.store.find("organizational")
    if not records:
        return {"status": UNKNOWN, "evidence": "0 organizational-tier record(s)",
                "gap": "no record has ever been promoted to Organizational Memory"}
    admitted = 0
    reasons: List[str] = []
    for rec in records:
        ok, why = organizational_admission_gate(facts.root, rec)
        if ok:
            admitted += 1
        else:
            reasons.extend(why)
    ev = f"{admitted}/{len(records)} organizational-tier record(s) still clear the gate"
    if admitted == len(records):
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": BLOCKED, "evidence": ev,
            "gap": f"{len(records) - admitted} record(s) no longer clear "
                   f"organizational_admission_gate(): {sorted(set(reasons))}"}


def _probe_revalidation_queue(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "the store has never been written to"}
    flagged = facts.store.find(None, status="NEEDS_REVALIDATION")
    ev = f"{len(flagged)} record(s) flagged NEEDS_REVALIDATION"
    if not flagged:
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": PARTIAL, "evidence": ev,
            "gap": f"{len(flagged)} record(s) await revalidation via "
                   "MemoryGC.confirm()/retract()"}


def _probe_retraction_supersede_ledger(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "the store has never been written to"}
    retracted = facts.store.find(None, status="RETRACTED")
    superseded = facts.store.find(None, status="SUPERSEDED")
    ev = f"{len(retracted)} RETRACTED, {len(superseded)} SUPERSEDED record(s)"
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_confirmed_conclusion_accumulation(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    if not facts.memory_available:
        return {"status": UNKNOWN, "evidence": "no memory store on disk",
                "gap": "the store has never been written to"}
    confirmed_tier = facts.store.find("engineering", confidence="CONFIRMED")
    reconfirmed = [r for r in facts.store.find(None)
                   if int(r.get("confirmation_count") or 0) > 0]
    ev = (f"{len(confirmed_tier)} CONFIRMED-tier engineering record(s); "
          f"{len(reconfirmed)} record(s) with confirmation_count>0")
    if not confirmed_tier and not reconfirmed:
        return {"status": UNKNOWN, "evidence": ev,
                "gap": "no record has ever been independently re-confirmed "
                       "(MemoryGC.confirm())"}
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_corner_case_library(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    ccl_dir = facts.root / ".dv-harness" / "memory" / "corner_case_library"
    path = ccl_dir / "index.json"
    if not path.is_file():
        return {"status": UNKNOWN, "evidence": "no corner_case_library/index.json on disk",
                "gap": "no corner case has ever been added"}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": BLOCKED, "evidence": "corner_case_library/index.json unreadable",
                "gap": str(e)}
    if not isinstance(rows, list):
        rows = []
    # CornerCaseLibrary carries no index_integrity() of its own (unlike
    # MemoryStore -- see memory_index_integrity above), so this row runs the
    # same files-vs-index-rows check by hand: a record FILE with no matching
    # index row is invisible to any future CornerCaseLibrary.get()-by-search
    # caller even though the file is real, exactly the "lost update" class
    # memory.py's own MemoryStore.index_integrity() docstring measured in this
    # project's history. Reported here rather than silently trusting an index
    # that says 0 while record files sit right next to it.
    indexed_ids = {str(r.get("ccl_id")) for r in rows if isinstance(r, dict) and r.get("ccl_id")}
    on_disk_ids = {p.stem for p in ccl_dir.glob("CCL-*.json")} if ccl_dir.is_dir() else set()
    missing_from_index = sorted(on_disk_ids - indexed_ids)
    if not rows and not on_disk_ids:
        return {"status": UNKNOWN, "evidence": "0 corner case(s) recorded",
                "gap": "no corner case has ever been added"}
    if missing_from_index:
        return {"status": BLOCKED,
                "evidence": f"{len(rows)} indexed corner case(s), {len(on_disk_ids)} record "
                            "file(s) on disk",
                "gap": f"{len(missing_from_index)} record file(s) exist with no index row "
                       f"(e.g. {missing_from_index[0]}): index.json cannot be trusted to "
                       "enumerate every corner case on disk"}
    active = sum(1 for r in rows if isinstance(r, dict) and r.get("status") == "ACTIVE")
    by_risk: Dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            tier = str(row.get("risk_tier") or "UNKNOWN")
            by_risk[tier] = by_risk.get(tier, 0) + 1
    ev = (f"{len(rows)} corner case(s), {active} ACTIVE; risk tiers: "
          + ", ".join(f"{k}={v}" for k, v in sorted(by_risk.items())))
    return {"status": READY, "evidence": ev, "gap": ""}


def _probe_confidence_tier_calibration(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from . import confidence_calibration as cc
    report = cc.calibrate(facts.root)
    status = report["status"]
    ev = (f"{status} ({report['reason']}); "
          f"{len(report.get('calibratable_tiers') or [])} calibratable tier(s)")
    if status == cc.STATUS_CALIBRATED:
        return {"status": READY, "evidence": ev, "gap": ""}
    if status == cc.STATUS_MISCALIBRATED:
        findings = "; ".join(f["kind"] for f in (report.get("findings") or []))
        return {"status": BLOCKED, "evidence": ev,
                "gap": findings or "miscalibration finding present"}
    return {"status": UNKNOWN, "evidence": ev, "gap": str(report.get("detail") or "")}


def _probe_cross_project_registry(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from . import cross_project_mining as cpm
    status = cpm.production_status(facts.root)
    ev = (f"{status['registered_project_count']} registered project(s), "
          f"{status['registered_with_readable_store']} readable")
    if status["can_produce_cross_project_result"]:
        return {"status": READY, "evidence": ev, "gap": ""}
    if status["registered_project_count"] == 0:
        return {"status": UNKNOWN, "evidence": ev,
                "gap": "no project has ever been registered"}
    return {"status": PARTIAL, "evidence": ev,
            "gap": f"fewer than {status['min_projects']} readable registered projects"}


def _probe_cross_project_pattern_mining(facts: _Facts, spec: SelfLearningRowSpec) -> Dict[str, str]:
    from . import cross_project_mining as cpm
    registry = cpm.ProjectRegistry(facts.root)
    report = cpm.mine_cross_project_patterns(registry.roots())
    ev = (f"{report['status']}: {report['projects_mined']} project(s) mined, "
          f"{len(report['cross_project_patterns'])} cross-project pattern(s), "
          f"{report['transferable_fix_count']} transferable fix(es)")
    if report["status"] == cpm.STATUS_OK:
        return {"status": READY, "evidence": ev, "gap": ""}
    return {"status": UNKNOWN, "evidence": ev, "gap": str(report["disclosure"])}


PROBES: Dict[str, Callable[[_Facts, SelfLearningRowSpec], Dict[str, str]]] = {
    "research_evidence_cards": _probe_research_evidence_cards,
    "prior_research_links": _probe_prior_research_links,
    "l5_check_completeness": _probe_l5_check_completeness,
    "overlap_recommendation_decisions": _probe_overlap_recommendation,
    "promotion_state_governance": _probe_promotion_state_governance,
    "human_approval_gate": _probe_human_approval_gate,
    "controlled_experiment_benchmark": _probe_controlled_experiment_benchmark,
    "shadow_replication_stability": _probe_shadow_replication_stability,
    "production_rollback_history": _probe_production_rollback_history,
    "repeated_failure_auto_filed": _probe_repeated_failure_auto_filed,
    "candidate_decision_audit_trail": _probe_candidate_decision_audit_trail,
    "architecture_decision_history": _probe_architecture_decision_history,
    "memory_index_integrity": _probe_memory_index_integrity,
    "engineering_admission_health": _probe_engineering_admission_health,
    "organizational_admission_health": _probe_organizational_admission_health,
    "revalidation_queue": _probe_revalidation_queue,
    "retraction_supersede_ledger": _probe_retraction_supersede_ledger,
    "confirmed_conclusion_accumulation": _probe_confirmed_conclusion_accumulation,
    "corner_case_library": _probe_corner_case_library,
    "confidence_tier_calibration": _probe_confidence_tier_calibration,
    "cross_project_registry": _probe_cross_project_registry,
    "cross_project_pattern_mining": _probe_cross_project_pattern_mining,
}


def _assert_every_row_has_a_probe() -> None:
    missing = [r.row_id for r in ROWS if r.row_id not in PROBES]
    orphan = [k for k in PROBES if k not in {r.row_id for r in ROWS}]
    if missing or orphan:
        raise SelfLearningReadinessError("ROW_PROBE_SET_MISMATCH", {
            "rows_without_probe": missing, "probes_without_row": orphan})


_assert_every_row_has_a_probe()


def assert_fact_sources_resolvable() -> List[str]:
    """Every `fact_source` a row declares still resolves through the import
    system -- identical discipline and identical algorithm to
    `golden_flow_readiness.assert_fact_sources_resolvable()`, restated here so
    this module's provenance claim is checkable without importing that
    module's internals. Returns the resolved names."""
    import importlib
    resolved: List[str] = []
    for spec in ROWS:
        for dotted in spec.fact_source:
            parts = dotted.split(".")
            obj = None
            for cut in range(len(parts), 1, -1):
                try:
                    obj = importlib.import_module(".".join(parts[:cut]))
                except Exception:
                    continue
                rest = parts[cut:]
                break
            else:
                raise SelfLearningReadinessError("FACT_SOURCE_MODULE_UNIMPORTABLE", {
                    "fact_source": dotted, "row": spec.row_id})
            for name in rest:
                if not hasattr(obj, name):
                    raise SelfLearningReadinessError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                        "fact_source": dotted, "row": spec.row_id,
                        "missing_attribute": name})
                obj = getattr(obj, name)
            resolved.append(dotted)
    return resolved


# ===========================================================================
# The matrix
# ===========================================================================

def derive_self_learning_readiness(root, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Section 55's matrix for one real project root.

    Read-only and total: all 22 rows always appear, including rows whose
    sources reported absence -- "this row is UNKNOWN" and "this row was
    omitted" must not look alike once the table is printed.
    """
    root = Path(root)
    facts = _gather_facts(root)
    rows: List[Dict[str, Any]] = []
    for spec in ROWS:
        try:
            probed = PROBES[spec.row_id](facts, spec)
        except Exception as e:  # a probe bug must not delete a mandatory row
            probed = {"status": UNKNOWN, "evidence": NONE_CELL,
                      "gap": f"probe raised {type(e).__name__}: {e}"}
        status = probed.get("status") or UNKNOWN
        if status not in SELF_LEARNING_READINESS_CLASSES:
            raise SelfLearningReadinessError("PROBE_RETURNED_UNKNOWN_READINESS_CLASS", {
                "row": spec.row_id, "status": status,
                "legal_values": list(SELF_LEARNING_READINESS_CLASSES)})
        rows.append({
            "row_id": spec.row_id,
            "row": spec.label,
            "status": status,
            "evidence": (probed.get("evidence") or "").strip() or NONE_CELL,
            "gap": (probed.get("gap") or "").strip() or NONE_CELL,
            "next_best_action": NONE_CELL,
            "fact_source": list(spec.fact_source),
            "basis": spec.basis,
        })

    open_rows = [r["row_id"] for r in rows if r["status"] != READY]
    actions = _next_best_actions(root, open_rows)
    for r in rows:
        if r["row_id"] in actions:
            r["next_best_action"] = actions[r["row_id"]]

    counts = {cls: sum(1 for r in rows if r["status"] == cls)
              for cls in SELF_LEARNING_READINESS_CLASSES}
    verdict = combine_readiness([r["status"] for r in rows])
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rows": rows,
        "summary": {
            "rows_total": len(rows),
            **{f"rows_{cls.lower()}": counts[cls] for cls in SELF_LEARNING_READINESS_CLASSES},
        },
        "self_learning_readiness": verdict,
        "readiness_rule": (
            "Every row READY, with no PARTIAL, BLOCKED or UNKNOWN row -- mirroring "
            "golden_flow_readiness's own section-47 rule, applied to the "
            "research/capability-evolution and five-tier-memory surfaces instead."),
        "authorizes": (
            "nothing. This matrix is an input to a human's review of this harness's "
            "own self-learning machinery; it approves no promotion, no experiment, no "
            "production write, and moves no capability-evolution candidate to a new "
            "state."),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_self_learning_matrix(matrix: Mapping[str, Any]) -> str:
    from .connectivity import render_markdown_table
    keys = [k for k, _ in SELF_LEARNING_MATRIX_COLUMNS]
    rows = [{k: _cell(r.get(k, NONE_CELL)) for k in keys} for r in (matrix.get("rows") or ())]
    return render_markdown_table(
        list(SELF_LEARNING_MATRIX_COLUMNS), rows,
        empty_note="(no row was produced -- this is a bug: section 55's 22 rows are "
                   "mandatory even when every one is UNKNOWN)")


def format_self_learning_readiness_report(matrix: Mapping[str, Any]) -> str:
    summary = matrix["summary"]
    out = [
        "# SELF-LEARNING READINESS MATRIX (section 55)",
        "",
        f"**{matrix['self_learning_readiness']}** -- {summary['rows_ready']} ready / "
        f"{summary['rows_partial']} partial / {summary['rows_blocked']} blocked / "
        f"{summary['rows_unknown']} unknown, of {summary['rows_total']} rows.",
        "",
        f"Project root: `{matrix['root']}`  (generated {matrix['generated_at']})",
        "",
        render_self_learning_matrix(matrix),
        "",
        matrix["readiness_rule"],
        "",
        f"This verdict authorizes: {matrix['authorizes']}",
    ]
    blocked = [r for r in matrix.get("rows") or () if r["status"] == BLOCKED]
    if blocked:
        out += ["", "## Blocked rows", ""]
        out += [f"- **{r['row']}** -- {r['gap']}" for r in blocked]
    return "\n".join(out)


# ===========================================================================
# One shared entry point for `python -m dv_harness.self_learning_readiness`.
#
# DISCLOSED: unlike golden_flow_readiness, this module has NO
# `dv-harness self-learning-readiness` CLI subcommand. dv_harness/cli.py is
# under heavy edit pressure from concurrent work in this batch (see this
# module's CLAUDE.md section), so the CLI wiring is a deliberate, disclosed
# residual -- a standalone `python -m` front door, matching several recent
# modules in this codebase that made the same choice for the same reason.
# ===========================================================================

def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            as_json: bool = False) -> Tuple[int, Dict[str, Any], str]:
    matrix = derive_self_learning_readiness(root, cfg)
    text = (format_self_learning_readiness_report(matrix) if not as_json else "")
    return (0 if matrix["self_learning_readiness"] == READY else 2), matrix, text


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.self_learning_readiness",
        description="Section 55's SELF-LEARNING READINESS MATRIX (22 rows), aggregated "
                    "from this project's real research/capability-evolution and "
                    "five-tier-memory sources. Reads only; runs and writes nothing.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    code, matrix, text = execute(Path(args.project_root), as_json=args.as_json)
    print(_json.dumps(matrix, ensure_ascii=False, indent=2) if args.as_json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
