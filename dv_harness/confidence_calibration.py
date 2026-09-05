# dv_harness/confidence_calibration.py -- the Confidence Calibration Engine
# (VERIFICATION_INTELLIGENCE gap VI-1, 2026-09-05).
#
# THE GAP THIS CLOSES, re-verified by full-repo grep before it was written:
# `grep -ril calibrat --include=*.py .` returned exactly two kinds of hit, and
# neither is this -- `gates.py`/`prompts.py`'s `architecture_calibration_gate`
# (an ARCHITECTURE-snapshot delta gate, nothing to do with confidence) and test
# fixtures naming it. Nothing anywhere asked whether a CONFIDENCE TIER's real
# track record matches what this harness treats that tier as being worth.
#
# The two halves this composes were both already real and both already used in
# production, and neither is re-implemented here:
#   - `inference.score_confidence()` PRODUCES a tier (HIGH/MEDIUM/LOW) from
#     citation counts, and `MemoryConsolidator.from_closed_finding()` mints the
#     fourth, CONFIRMED, behind its single_sim + regression + re-audit bar.
#     Those tiers are then SPENT as if their reliability were known:
#     `inference.promote_if_high_confidence()` pushes a HIGH finding into the
#     shared cross-user Knowledge Center, `memory_router`'s
#     ENGINEERING_ADMISSION_CONFIDENCE_LEVELS admits only HIGH/CONFIRMED to the
#     Engineering tier, and `qualified_conclusion.build_qualified_conclusion()`
#     refuses to qualify a LOW conclusion at all.
#   - `memory.py` RECORDS what later happened to each of those conclusions.
#     `MemoryGC.confirm()` -- the single authorized writer of
#     `confirmation_count`, i.e. "an independent, later run re-derived the SAME
#     conclusion with fresh evidence" -- is a real verified outcome.
#     `MemoryGC.retract()` ("found to be wrong outright") and
#     `MemoryGC.supersede()` ("a newer, corrected record replaces this one")
#     are real rejected outcomes.
#
# So the evidence to check a tier against its own history was being written the
# whole time and nothing read it back. This module reads it back. It computes
# NOTHING about a conclusion itself -- it never re-scores, never re-runs a gate,
# never writes a record -- it only counts real outcomes per tier and reports
# where the ordering this harness ACTS on is not the ordering its own history
# supports.
#
# WHAT IT DELIBERATELY DOES NOT DO: invent a stated reliability. No number in
# this codebase says "HIGH means 90%" -- every tier's meaning is a PROCEDURAL
# bar (how much corroboration, which gates cleared), not a declared success
# rate. Fabricating one and then reporting a project "miscalibrated" against it
# would be exactly the unearned claim CLAUDE.md's Evidence Truth Rule forbids.
# What IS checkable without inventing anything is the ORDERING: this harness
# treats CONFIRMED > HIGH > MEDIUM > LOW, and a history in which a higher tier
# holds up materially LESS often than a lower one contradicts that ordering
# using only the project's own records. A project that does want an absolute
# bar declares one itself (`confidence_calibration.tier_reliability_floor`);
# every tier's floor is None by default and says why, the same honesty contract
# `loop_budget.py` applies to its own eleven budget dimensions.
from __future__ import annotations

import importlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .inference import CONFIDENCE_LEVELS, identify_gap, next_best_action
from .memory import MEMORY_LEVELS, MemoryStore
from .memory_router import ENGINEERING_ADMISSION_CONFIDENCE_LEVELS

#: The tiers this engine calibrates, strongest first. NOT a new vocabulary:
#: HIGH/MEDIUM/LOW are `inference.CONFIDENCE_LEVELS` verbatim, and CONFIRMED is
#: the one additional label `MemoryConsolidator.from_closed_finding()` writes and
#: `memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS` admits alongside HIGH.
#: `assert_tiers_cover_inference_levels()` holds that in both directions.
CALIBRATION_TIERS = ("CONFIRMED", "HIGH", "MEDIUM", "LOW")

#: Rank 0 is the strongest tier. Used only for the ordering check.
TIER_RANK = {tier: i for i, tier in enumerate(CALIBRATION_TIERS)}

#: Where each tier's own definition lives. Resolved through the import system by
#: `assert_tier_sources_resolvable()`, the same provenance discipline
#: `golden_flow_readiness.assert_fact_sources_resolvable()` applies to its rows:
#: a tier citing a symbol that no longer exists is a tier whose provenance is
#: fiction.
TIER_DEFINITION_SOURCE = {
    "CONFIRMED": "dv_harness.memory:MemoryConsolidator.from_closed_finding",
    "HIGH": "dv_harness.inference:score_confidence",
    "MEDIUM": "dv_harness.inference:score_confidence",
    "LOW": "dv_harness.inference:score_confidence",
}

OUTCOME_VERIFIED = "VERIFIED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_INDETERMINATE = "INDETERMINATE"

#: The record writers whose real output each outcome is read off. Same
#: resolvability discipline as TIER_DEFINITION_SOURCE.
OUTCOME_SOURCE = {
    OUTCOME_VERIFIED: "dv_harness.memory:MemoryGC.confirm",
    OUTCOME_REJECTED: "dv_harness.memory:MemoryGC.retract",
    OUTCOME_INDETERMINATE: "dv_harness.memory:MemoryStore.add",
}

#: `status` values that mean the claim as stated did not hold. SUPERSEDED is
#: counted here deliberately: `MemoryGC.supersede()`'s own docstring is "a
#: newer, CORRECTED record replaces this one", so the original claim was at
#: least partly wrong. It is kept as its own reason string rather than folded
#: into RETRACTED, because "replaced by something better" and "found wrong with
#: no replacement" are different facts a reader may want to weigh differently.
REJECTING_STATUSES = ("RETRACTED", "SUPERSEDED")

#: `status` values that are not an outcome either way, each with the reason a
#: reader needs to tell them apart. DEPRECATED is retirement, not refutation;
#: NEEDS_REVALIDATION is an explicit "nobody has re-checked this yet".
INDETERMINATE_STATUS_REASONS = {
    "DEPRECATED": "RETIRED_NOT_REFUTED",
    "NEEDS_REVALIDATION": "FLAGGED_STALE_NOT_YET_RECHECKED",
}

#: An ACTIVE record that no independent run has re-derived. This is the honest
#: default state of most records and is NOT evidence the conclusion was right --
#: counting it as a verified outcome would manufacture a reliability of 1.0 for
#: every tier out of records nothing ever re-tested.
INDETERMINATE_NEVER_RECHECKED = "NEVER_INDEPENDENTLY_RECHECKED"

#: The band a reliability rate in this report is meaningful to. A rate computed
#: from N determinate outcomes moves by 1/N per outcome, so at N < 10 a single
#: record moves it by more than 10 percentage points and the number carries less
#: resolution than the band it is being compared across. This is derived from
#: the arithmetic, not chosen: it is the smallest N at which 1/N <= 0.1.
RELIABILITY_RESOLUTION = 0.1
MIN_DETERMINATE_OUTCOMES_PER_TIER = 10

#: How far a higher tier may sit BELOW a lower tier before that is reported as a
#: real inversion rather than noise. One resolution band, for the same reason:
#: a gap smaller than the resolution of either rate is not a measured
#: disagreement. Deliberately the same constant, not a second independent
#: threshold -- `loop_convergence.py` derives its own thresholds from
#: `coverage_analysis.FLAT_TREND_TOLERANCE_PERCENT` for exactly this reason.
INVERSION_TOLERANCE = RELIABILITY_RESOLUTION

FINDING_INVERTED_TIER_ORDER = "INVERTED_TIER_ORDER"
FINDING_BELOW_DECLARED_FLOOR = "BELOW_DECLARED_FLOOR"

STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
STATUS_CALIBRATED = "CALIBRATED"
STATUS_MISCALIBRATED = "MISCALIBRATED"

#: Why no tier carries a declared numeric reliability out of the box. Each entry
#: names the real procedural bar that tier actually stands on, so a reader can
#: see that the absence is a fact about this harness rather than an omission
#: here. `validate_config()` refuses a tier missing from this map for the same
#: reason `loop_contract.validate_contract()` refuses a budget with no reason: a
#: None with no explanation reads to a human as a bound that exists.
TIER_DECLARED_FLOOR_BASIS = {
    "CONFIRMED": (
        "no numeric reliability is declared for CONFIRMED anywhere in this harness. "
        "MemoryConsolidator.from_closed_finding() mints CONFIRMED behind single_sim "
        "PASS + regression PASS/NOT_REQUIRED + re-audit CLEAN -- a procedural bar, "
        "not a stated success rate"
    ),
    "HIGH": (
        "no numeric reliability is declared for HIGH. inference.score_confidence() "
        "returns it at base >= 6, promote_if_high_confidence() pushes only HIGH to "
        "the shared Knowledge Center and memory_router."
        "ENGINEERING_ADMISSION_CONFIDENCE_LEVELS admits only HIGH/CONFIRMED -- all "
        "procedural bars, none a stated success rate"
    ),
    "MEDIUM": (
        "no numeric reliability is declared for MEDIUM. score_confidence() returns it "
        "at base >= 3 and qualified_conclusion.build_qualified_conclusion() will "
        "qualify it -- a threshold on evidence quantity, not a stated success rate"
    ),
    "LOW": (
        "no numeric reliability is declared for LOW. build_qualified_conclusion() "
        "refuses to qualify a LOW conclusion at all -- a refusal rule, not a stated "
        "success rate"
    ),
}

#: The catalog shape `inference.next_best_action()` documents. Every action this
#: report suggests is produced by that REAL function through its
#: `gap_action_catalog` parameter -- the domain-neutral Gap -> Next-Best-Action
#: engine `capability_evolution.py` and `golden_flow_readiness.py` already drive
#: the same way, and the one the master prompt's section 10 forbids
#: re-implementing.
CALIBRATION_GAP_ACTION_CATALOG = {
    "source": "confidence_calibration",
    "fallback": "no calibration action is registered for '{gap}' -- inspect the tier's own records",
    "actions": {
        f"tier_{tier}_insufficient_history": (
            f"{tier} has fewer than {MIN_DETERMINATE_OUTCOMES_PER_TIER} determinate "
            f"outcomes; a rate from fewer moves by more than one "
            f"{int(RELIABILITY_RESOLUTION * 100)}-point band per record. Record real "
            f"outcomes on {tier} conclusions (MemoryGC.confirm on an independent "
            f"re-derivation, MemoryGC.retract/supersede on a refuted one) rather than "
            f"leaving them ACTIVE and never re-checked"
        )
        for tier in CALIBRATION_TIERS
    } | {
        FINDING_INVERTED_TIER_ORDER: (
            "a higher tier held up LESS often than a lower one in this project's own "
            "records -- treat the higher tier as no stronger than the lower one until "
            "the inversion is explained, and review what score_confidence() inputs the "
            "inverted tier's records were built from"
        ),
        FINDING_BELOW_DECLARED_FLOOR: (
            "this tier is below the reliability floor this project declared in "
            "confidence_calibration.tier_reliability_floor -- either the floor is "
            "wrong for this project or the tier is being awarded too easily"
        ),
    },
}

#: Project-configurable settings, merged the same way `loop_budget.resolve_config()`
#: merges its own block. `tier_reliability_floor` is the only knob and every tier
#: defaults to None -- see TIER_DECLARED_FLOOR_BASIS for why.
DEFAULTS = {
    "tier_reliability_floor": {tier: None for tier in CALIBRATION_TIERS},
}


class CalibrationConfigError(ValueError):
    """A `confidence_calibration` config block this module refuses to run on --
    an unknown tier name, or a floor that is not a fraction in [0, 1]. Follows
    the typed-error convention of `qualified_conclusion.InvalidGateVerdictError`:
    a SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict, never a
    silently-ignored bad value that would make the report say something the
    operator did not ask for."""

    def __init__(self, reason: str, detail: Dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def assert_tiers_cover_inference_levels() -> None:
    """CALIBRATION_TIERS must be exactly `inference.CONFIDENCE_LEVELS` plus the
    tiers `memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS` names -- no
    more, no fewer. Held in BOTH directions so neither a new level added to
    score_confidence() nor a tier invented here can slip past: an uncalibrated
    tier would be silently absent from every report, and an invented one would
    always read as having no history.

    Called at import, the same way `loop_contract.assert_status_mapping_total()`
    is, so the failure is a loud import error rather than a quiet gap in a
    report a human is reading as complete."""
    expected = set(CONFIDENCE_LEVELS) | set(ENGINEERING_ADMISSION_CONFIDENCE_LEVELS)
    actual = set(CALIBRATION_TIERS)
    if expected != actual:
        raise AssertionError(
            "CALIBRATION_TIERS must equal inference.CONFIDENCE_LEVELS | "
            f"memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    missing_basis = [t for t in CALIBRATION_TIERS if t not in TIER_DECLARED_FLOOR_BASIS]
    missing_source = [t for t in CALIBRATION_TIERS if t not in TIER_DEFINITION_SOURCE]
    if missing_basis or missing_source:
        raise AssertionError(
            f"every tier needs a declared-floor basis and a definition source; "
            f"missing_basis={missing_basis} missing_source={missing_source}"
        )


def _resolve_symbol(spec: str) -> Any:
    module_name, _, attr_path = spec.partition(":")
    obj: Any = importlib.import_module(module_name)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def assert_tier_sources_resolvable() -> Dict[str, str]:
    """Every symbol TIER_DEFINITION_SOURCE / OUTCOME_SOURCE cites must resolve
    through the real import system. A report claiming to read
    `MemoryGC.confirm()` after that method was renamed away is a report whose
    provenance column is decoration."""
    unresolved: Dict[str, str] = {}
    for label, spec in list(TIER_DEFINITION_SOURCE.items()) + list(OUTCOME_SOURCE.items()):
        try:
            _resolve_symbol(spec)
        except (ImportError, AttributeError) as exc:
            unresolved[label] = f"{spec}: {exc}"
    if unresolved:
        raise AssertionError(f"unresolvable calibration sources: {unresolved}")
    return dict(TIER_DEFINITION_SOURCE)


assert_tiers_cover_inference_levels()


def normalize_tier(value: Any) -> Optional[str]:
    """The record's `confidence` field as one of CALIBRATION_TIERS, or None.

    None is returned for `UNKNOWN` (MemoryStore.add()'s own default for a record
    whose writer stated no confidence) and for anything else unrecognized. Those
    records are counted and reported separately, never mapped onto a tier: a
    record nobody assigned a confidence to says nothing about how any tier
    performs."""
    if value is None:
        return None
    tier = str(value).strip().upper()
    return tier if tier in TIER_RANK else None


def classify_record_outcome(record: Dict[str, Any]) -> Dict[str, Any]:
    """What really happened to one stored conclusion, read off the fields the
    real `MemoryGC` writers set. No re-scoring, no judgment about the claim
    itself.

    REJECTION IS CHECKED FIRST, and that ordering is load-bearing: a record that
    was confirmed once and later retracted is a REJECTED outcome. The last word
    about whether a claim held is the retraction, and counting it as verified
    because an earlier run agreed would let a tier's worst records improve its
    score."""
    status = str(record.get("status") or "").strip().upper()
    try:
        confirmations = int(record.get("confirmation_count") or 0)
    except (TypeError, ValueError):
        confirmations = 0

    if status in REJECTING_STATUSES:
        return {"outcome": OUTCOME_REJECTED, "reason": status,
                "confirmation_count": confirmations}
    if confirmations > 0:
        return {"outcome": OUTCOME_VERIFIED, "reason": "INDEPENDENTLY_RECONFIRMED",
                "confirmation_count": confirmations}
    if status in INDETERMINATE_STATUS_REASONS:
        return {"outcome": OUTCOME_INDETERMINATE,
                "reason": INDETERMINATE_STATUS_REASONS[status],
                "confirmation_count": confirmations}
    if status == "ACTIVE":
        return {"outcome": OUTCOME_INDETERMINATE,
                "reason": INDETERMINATE_NEVER_RECHECKED,
                "confirmation_count": confirmations}
    return {"outcome": OUTCOME_INDETERMINATE, "reason": f"UNRECOGNIZED_STATUS:{status or 'NONE'}",
            "confirmation_count": confirmations}


def resolve_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """This module's settings for `cfg`, with every DEFAULT filled in and every
    supplied value validated. Public for the same reason
    `loop_budget.resolve_config()` is: two callers merging the same block with
    two different notions of "absent" is how a knob comes to mean one thing to
    the report and another to whoever set it."""
    block = ((cfg or {}).get("confidence_calibration") or {})
    if not isinstance(block, dict):
        raise CalibrationConfigError("CONFIDENCE_CALIBRATION_BLOCK_NOT_A_DICT",
                                     {"block": block})
    floors = dict(DEFAULTS["tier_reliability_floor"])
    supplied = block.get("tier_reliability_floor") or {}
    if not isinstance(supplied, dict):
        raise CalibrationConfigError("TIER_RELIABILITY_FLOOR_NOT_A_DICT",
                                     {"tier_reliability_floor": supplied})
    for tier, value in supplied.items():
        key = str(tier).strip().upper()
        if key not in TIER_RANK:
            raise CalibrationConfigError("UNKNOWN_CALIBRATION_TIER",
                                         {"tier": tier, "known": list(CALIBRATION_TIERS)})
        if value is None:
            continue
        try:
            fraction = float(value)
        except (TypeError, ValueError):
            raise CalibrationConfigError("TIER_RELIABILITY_FLOOR_NOT_A_NUMBER",
                                         {"tier": key, "value": value}) from None
        if not 0.0 <= fraction <= 1.0:
            raise CalibrationConfigError("TIER_RELIABILITY_FLOOR_OUT_OF_RANGE",
                                         {"tier": key, "value": fraction})
        floors[key] = fraction
    return {"tier_reliability_floor": floors}


def _memory_index_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "memory" / "index.json"


def collect_outcomes(store: MemoryStore) -> Dict[str, Any]:
    """Every stored record's (tier, outcome) pair, read through the real
    `MemoryStore.find()`.

    `find()` is index-driven, which is deliberately the SAME view
    `MemoryRetriever.search()` has of this store -- calibrating against records
    a search could never surface would describe a corpus this harness does not
    actually use. Because that view can genuinely under-count (this project's
    own store really did have 31 record files with no index row, see
    `MemoryStore._index_lock()`'s note), `index_integrity()` is reported
    alongside the counts so an under-counted corpus is visible rather than
    silently smaller."""
    per_tier: Dict[str, Dict[str, Any]] = {
        tier: {"records": 0, OUTCOME_VERIFIED: 0, OUTCOME_REJECTED: 0,
               OUTCOME_INDETERMINATE: 0, "outcome_reasons": {}, "levels": {}}
        for tier in CALIBRATION_TIERS
    }
    untiered: Dict[str, int] = {}
    scanned = 0
    for record in store.find():
        scanned += 1
        tier = normalize_tier(record.get("confidence"))
        if tier is None:
            label = str(record.get("confidence") or "ABSENT").strip().upper() or "ABSENT"
            untiered[label] = untiered.get(label, 0) + 1
            continue
        verdict = classify_record_outcome(record)
        bucket = per_tier[tier]
        bucket["records"] += 1
        bucket[verdict["outcome"]] += 1
        bucket["outcome_reasons"][verdict["reason"]] = (
            bucket["outcome_reasons"].get(verdict["reason"], 0) + 1)
        level = str(record.get("level") or "unknown")
        bucket["levels"][level] = bucket["levels"].get(level, 0) + 1
    return {
        "records_scanned": scanned,
        "per_tier": per_tier,
        "records_without_recognized_tier": untiered,
        "memory_levels": list(MEMORY_LEVELS),
        "index_integrity": store.index_integrity(),
    }


def _tier_report(tier: str, bucket: Dict[str, Any], floor: Optional[float]) -> Dict[str, Any]:
    verified = bucket[OUTCOME_VERIFIED]
    rejected = bucket[OUTCOME_REJECTED]
    determinate = verified + rejected
    calibratable = determinate >= MIN_DETERMINATE_OUTCOMES_PER_TIER
    return {
        "tier": tier,
        "rank": TIER_RANK[tier],
        "definition_source": TIER_DEFINITION_SOURCE[tier],
        "records": bucket["records"],
        "verified": verified,
        "rejected": rejected,
        "indeterminate": bucket[OUTCOME_INDETERMINATE],
        "determinate": determinate,
        "outcome_reasons": dict(sorted(bucket["outcome_reasons"].items())),
        "levels": dict(sorted(bucket["levels"].items())),
        "observed_reliability": (verified / determinate) if calibratable else None,
        "calibratable": calibratable,
        "insufficient_reason": None if calibratable else (
            f"{determinate} determinate outcome(s); "
            f"{MIN_DETERMINATE_OUTCOMES_PER_TIER} required before a rate has "
            f"resolution finer than {int(RELIABILITY_RESOLUTION * 100)} percentage points"
        ),
        "declared_floor": floor,
        "declared_floor_basis": TIER_DECLARED_FLOOR_BASIS[tier],
    }


def _ordering_findings(tiers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every (stronger, weaker) pair whose measured reliabilities contradict the
    ordering this harness acts on, by more than one resolution band.

    Every calibratable pair is compared, not just adjacent ones: CONFIRMED
    sitting below LOW is a real inversion even when HIGH and MEDIUM sit between
    them and each individually looks fine."""
    findings: List[Dict[str, Any]] = []
    ranked = [t for t in CALIBRATION_TIERS if tiers[t]["calibratable"]]
    for i, stronger in enumerate(ranked):
        for weaker in ranked[i + 1:]:
            hi = tiers[stronger]["observed_reliability"]
            lo = tiers[weaker]["observed_reliability"]
            margin = lo - hi
            if margin > INVERSION_TOLERANCE:
                findings.append({
                    "kind": FINDING_INVERTED_TIER_ORDER,
                    "higher_tier": stronger,
                    "lower_tier": weaker,
                    "higher_observed_reliability": hi,
                    "lower_observed_reliability": lo,
                    "margin": margin,
                    "tolerance": INVERSION_TOLERANCE,
                    "detail": (
                        f"{stronger} held up {hi:.0%} of the time over "
                        f"{tiers[stronger]['determinate']} determinate outcomes while "
                        f"{weaker} held up {lo:.0%} over "
                        f"{tiers[weaker]['determinate']} -- this project's own records "
                        f"do not support treating {stronger} as stronger than {weaker}"
                    ),
                })
    return findings


def _floor_findings(tiers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for tier in CALIBRATION_TIERS:
        row = tiers[tier]
        floor = row["declared_floor"]
        if floor is None or not row["calibratable"]:
            continue
        if row["observed_reliability"] < floor:
            findings.append({
                "kind": FINDING_BELOW_DECLARED_FLOOR,
                "tier": tier,
                "observed_reliability": row["observed_reliability"],
                "declared_floor": floor,
                "detail": (
                    f"{tier} held up {row['observed_reliability']:.0%} of the time over "
                    f"{row['determinate']} determinate outcomes, below the "
                    f"{floor:.0%} floor this project declared in "
                    f"confidence_calibration.tier_reliability_floor"
                ),
            })
    return findings


def calibrate(root: Path, *, cfg: Optional[Dict[str, Any]] = None,
              store: Optional[MemoryStore] = None) -> Dict[str, Any]:
    """The calibration report for one project, computed only from that project's
    REAL MemoryStore records.

    Reading is never a mutating act. A project with no memory store on disk is
    reported NOT_AVAILABLE WITHOUT constructing a `MemoryStore` -- that
    constructor calls `mkdir(parents=True)` and writes an empty `index.json`, so
    merely asking whether a project is calibrated would otherwise create the
    store it was asking about. Nothing here writes a record, a decision, an
    approval or a file.

    Four honest statuses, and the difference between the first two matters:
      NOT_AVAILABLE        no memory store, or no record carries any recognized
                           confidence tier -- there is nothing to calibrate.
      INSUFFICIENT_HISTORY records exist and carry tiers, but no tier has yet
                           accumulated MIN_DETERMINATE_OUTCOMES_PER_TIER real
                           verified/rejected outcomes. This is a real answer,
                           not a failure, and it is this harness's OWN current
                           state.
      CALIBRATED           at least one tier is calibratable and nothing
                           contradicts the ordering or a declared floor.
      MISCALIBRATED        at least one finding.
    """
    root = Path(root)
    conf = resolve_config(cfg)
    floors = conf["tier_reliability_floor"]
    generated_at = time.time()
    base = {
        "generated_at": generated_at,
        "project_root": str(root),
        "source": str(_memory_index_path(root)),
        "min_determinate_outcomes_per_tier": MIN_DETERMINATE_OUTCOMES_PER_TIER,
        "reliability_resolution": RELIABILITY_RESOLUTION,
        "inversion_tolerance": INVERSION_TOLERANCE,
        "tier_order": list(CALIBRATION_TIERS),
        "outcome_sources": dict(OUTCOME_SOURCE),
    }

    if store is None and not _memory_index_path(root).exists():
        gaps = [f"tier_{t}_insufficient_history" for t in CALIBRATION_TIERS]
        return dict(base, status=STATUS_NOT_AVAILABLE,
                    reason="NO_MEMORY_STORE",
                    detail=(
                        "no .dv-harness/memory/index.json in this project. A calibration "
                        "engine has nothing to calibrate until real conclusions have been "
                        "recorded and real outcomes recorded against them."
                    ),
                    tiers={}, calibratable_tiers=[],
                    uncalibratable_tiers=list(CALIBRATION_TIERS),
                    findings=[], gaps=gaps,
                    next_best_actions=next_best_action(
                        None, gaps, root,
                        gap_action_catalog=CALIBRATION_GAP_ACTION_CATALOG))

    store = store if store is not None else MemoryStore(root)
    collected = collect_outcomes(store)
    tiers = {tier: _tier_report(tier, collected["per_tier"][tier], floors[tier])
             for tier in CALIBRATION_TIERS}
    base["corpus"] = {
        "records_scanned": collected["records_scanned"],
        "records_with_recognized_tier": sum(t["records"] for t in tiers.values()),
        "records_without_recognized_tier": collected["records_without_recognized_tier"],
        "index_integrity_ok": collected["index_integrity"]["ok"],
        "index_rows_without_file": len(collected["index_integrity"]["index_rows_without_file"]),
        "record_files_missing_from_index": len(
            collected["index_integrity"]["files_missing_from_index"]),
    }

    calibratable = [t for t in CALIBRATION_TIERS if tiers[t]["calibratable"]]
    # inference.identify_gap(): required tiers minus the ones with enough
    # history. The same pure set-difference every other gap consumer uses --
    # deliberately not a hand-rolled list comprehension here.
    gap_tiers = identify_gap(list(CALIBRATION_TIERS), calibratable)

    findings: List[Dict[str, Any]] = []
    if calibratable:
        findings = _ordering_findings(tiers) + _floor_findings(tiers)

    gaps = [f"tier_{t}_insufficient_history" for t in gap_tiers]
    gaps += sorted({f["kind"] for f in findings})
    actions = next_best_action(None, gaps, root,
                               gap_action_catalog=CALIBRATION_GAP_ACTION_CATALOG) if gaps else []

    if base["corpus"]["records_with_recognized_tier"] == 0:
        status, reason, detail = (
            STATUS_NOT_AVAILABLE, "NO_RECORD_CARRIES_A_CONFIDENCE_TIER",
            f"{collected['records_scanned']} record(s) scanned; none carries a "
            f"confidence in {list(CALIBRATION_TIERS)}. MemoryStore.add() defaults "
            f"an unstated confidence to UNKNOWN, which is not a tier and is never "
            f"mapped onto one.")
    elif not calibratable:
        status, reason, detail = (
            STATUS_INSUFFICIENT_HISTORY, "NO_TIER_HAS_ENOUGH_DETERMINATE_OUTCOMES",
            "records carry confidence tiers, but no tier has accumulated "
            f"{MIN_DETERMINATE_OUTCOMES_PER_TIER} verified/rejected outcomes yet. "
            "Most records are ACTIVE and never independently re-checked, which is "
            "not evidence either way.")
    elif findings:
        status, reason, detail = (
            STATUS_MISCALIBRATED, "FINDINGS_PRESENT",
            f"{len(findings)} finding(s) over {len(calibratable)} calibratable tier(s).")
    else:
        status, reason, detail = (
            STATUS_CALIBRATED, "NO_FINDINGS",
            f"{len(calibratable)} calibratable tier(s); ordering holds and no declared "
            f"floor is breached.")

    return dict(base, status=status, reason=reason, detail=detail, tiers=tiers,
                calibratable_tiers=calibratable, uncalibratable_tiers=gap_tiers,
                findings=findings, gaps=gaps, next_best_actions=actions)


def render_report_text(report: Dict[str, Any]) -> str:
    """Human-readable form of `calibrate()`'s payload. Every tier is always
    printed, including the ones with no history -- "this tier could not be
    calibrated" and "this tier was omitted" must not look alike once the report
    is on screen."""
    lines = [
        f"Confidence Calibration -- {report['status']} ({report['reason']})",
        f"  {report.get('detail','')}",
        f"  source: {report['source']}",
    ]
    corpus = report.get("corpus")
    if corpus:
        lines.append(
            f"  corpus: {corpus['records_scanned']} record(s) scanned, "
            f"{corpus['records_with_recognized_tier']} with a recognized tier, "
            f"index_integrity_ok={corpus['index_integrity_ok']}")
        if corpus["records_without_recognized_tier"]:
            lines.append(f"  without a tier: {corpus['records_without_recognized_tier']}")
    tiers = report.get("tiers") or {}
    if tiers:
        lines.append("")
        lines.append(f"  {'TIER':<10} {'RECORDS':>7} {'VERIF':>6} {'REJECT':>6} "
                     f"{'DETERM':>6}  RELIABILITY")
        for tier in report["tier_order"]:
            row = tiers[tier]
            rel = ("--  (%s)" % row["insufficient_reason"]
                   if row["observed_reliability"] is None
                   else f"{row['observed_reliability']:.0%}")
            lines.append(f"  {tier:<10} {row['records']:>7} {row['verified']:>6} "
                         f"{row['rejected']:>6} {row['determinate']:>6}  {rel}")
    for finding in report.get("findings") or []:
        lines.append("")
        lines.append(f"  FINDING {finding['kind']}: {finding['detail']}")
    for action in report.get("next_best_actions") or []:
        lines.append(f"  NEXT [{action['gap']}] {action['suggested_action']}")
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *, as_json: bool = False,
                 cfg: Optional[Dict[str, Any]] = None) -> "tuple[int, Any]":
    """One implementation behind `python -m dv_harness.confidence_calibration` and
    any future CLI front door -- the same shared-`execute_verb()` convention
    `loop_contract`, `loop_budget` and `loop_telemetry` follow.

    Exit 2 means "not calibrated": NOT_AVAILABLE, INSUFFICIENT_HISTORY or
    MISCALIBRATED. It is a reporting signal, never an approval signal in either
    direction -- nothing in this module can authorize anything."""
    root = Path(root)
    if verb == "tiers":
        return 0, {
            "tier_order": list(CALIBRATION_TIERS),
            "tier_definition_source": dict(TIER_DEFINITION_SOURCE),
            "declared_floor_basis": dict(TIER_DECLARED_FLOOR_BASIS),
            "outcome_sources": dict(OUTCOME_SOURCE),
            "rejecting_statuses": list(REJECTING_STATUSES),
            "min_determinate_outcomes_per_tier": MIN_DETERMINATE_OUTCOMES_PER_TIER,
            "inversion_tolerance": INVERSION_TOLERANCE,
        }
    if verb in ("report", "show"):
        report = calibrate(root, cfg=cfg)
        code = 0 if report["status"] == STATUS_CALIBRATED else 2
        if verb == "show" and not as_json:
            return code, render_report_text(report)
        return code, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["tiers", "report", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.confidence_calibration",
        description="Does a confidence tier's real track record in this project's "
                    "Memory records match the ordering this harness acts on?")
    p.add_argument("verb", choices=["tiers", "report", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.project_root)
    cfg = None
    config_file = root / ".dv-harness" / "config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = None
    code, payload = execute_verb(root, args.verb, as_json=args.json, cfg=cfg)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
