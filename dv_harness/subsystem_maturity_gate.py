"""dv_harness/subsystem_maturity_gate.py -- the 9.0 / 9.5 / 10.0 SUBSYSTEM
MATURITY GATES as three composite qualification-gate definitions.

WHAT THIS MODULE IS
--------------------
Three named maturity levels, each a fixed SET of already-real conditions this
project's own gates/artifacts already establish. This is a COMPOSITE CHECK,
not a new measurement layer: every condition below either calls a real
function this repo already has, or -- where no such function exists --
reports that honestly rather than inventing one. Confirmed by direct search
before writing a line of evaluation logic:

  * `golden_flow_readiness.derive_golden_flow_readiness()` already answers
    whether the Spec -> Requirement -> UVM-generation -> single-test-PASS
    chain is connected end-to-end with evidence (its own `spec_in` /
    `requirement_extraction` / `vip_uvm_generation` / `single_test_proof`
    rows), and `system_build_proof.py`'s `SYSTEM_READY` is the composed-system
    smoke-proof ladder's own aggregate verdict. Neither is re-derived here.
  * `vip_api_card.validate_vip_api_usage()` already decides, over a real
    `vip_symbol_index`, whether a generated environment cites a VIP
    class/method the index can prove -- BLOCKED is its own "provably
    fabricated" verdict.
  * `connectivity.assert_bind_entry_tier_allows_emission()` /
    `enforce_bind_tier_policy()` already classify a bind entry's tier and
    refuse a T4 (question-queue-only) or an unconfirmed T3 (naming-heuristic,
    "ALWAYS requires human confirmation") from ever being emitted.
  * `evidence_db.EvidenceStore` already holds the real per-job and
    per-evidence-envelope rows a regression run produces.
  * A repo-wide `grep -rn "false_pass\\|FALSE_PASS\\|false positive" -i
    dv_harness/*.py` (recorded in this module's own condition table) found
    `tools/verification_flow/false_pass_resistance_gate.py` -- a PER-STAGE,
    AGENT-ATTESTED evidence-block shape check, not a count -- and no
    producer anywhere, including `golden_scenario.py` and
    `requirement_contract.py` (the two modules this task named as the
    likeliest home for one), that persists a false-PASS COUNT over a
    qualification set. That condition is reported `NOT_MEASURABLE` rather
    than inventing a counter, per the Evidence Truth Rule.

WHAT THIS MODULE DOES NOT DO
-----------------------------
It does not run a stage, invoke a gate script, submit a build/regression/LSF
job, write any state/control/approval file, or authorize a promotion/signoff.
Every condition either reads a project's own already-real artifacts (through
the module it belongs to) or reads evidence the CALLER supplies (a VIP API
cards artifact, a bind topology JSON, an evidence.duckdb path, a
`system_build_proof.SmokeProofReport.to_dict()`) -- never an agent's typed
claim about its own work. A QUALIFIED verdict is an input to a human's
qualification decision, never a substitute for one.

Deliberately NOT imported here: `dv_harness/subsystem_practicality_score.py`.
Per this task's own instruction, this module derives its conditions
independently from the same underlying real sources so the two files' change
histories stay independent of each other.

WHY EACH CONDITION RESOLVES THROUGH THE IMPORT SYSTEM
------------------------------------------------------
Every `ConditionSpec.fact_source` entry is a dotted name resolved by
`assert_fact_sources_resolvable()`, the same style
`golden_flow_readiness.assert_fact_sources_resolvable()` already established:
a condition citing a renamed or removed function fails a test instead of
silently reporting a fabricated MET/PASS.

WHY THE VOCABULARY IS NOT `models.Status`
-------------------------------------------
A condition's own outcome (MET / UNMET / NOT_AVAILABLE / NOT_MEASURABLE) and
this gate's verdict (QUALIFIED / NOT_QUALIFIED / INCOMPLETE_EVIDENCE) share no
token with `dv_harness.models.Status` -- checked at import time by
`assert_no_verification_verdict_vocabulary()`, the same guard
`capability_evolution.py` / `benchmark_dataset.py` /
`dependency_supply_chain.py` already apply to their own domain-specific
vocabularies. A maturity-gate condition being "MET" is not a stage reaching
`Status.PASS`, and conflating the two would let this module's verdict be
misread as a graph-routing signal.

HOW A LEVEL'S REQUIREMENT SET IS BUILT
-----------------------------------------
`LEVEL_REQUIREMENTS` is a strictly monotonic ladder: 9.0's required
conditions are a subset of 9.5's, which are a subset of 10.0's
(`assert_levels_are_monotonic()`). A condition whose status is
`NOT_MEASURABLE` for a REQUIRED condition never blocks `QUALIFIED` -- there is
nothing this project could do today to make it PASS/MET, so blocking on it
would make that level permanently unreachable rather than honestly disclosed
-- but it IS always carried on the report's `disclosed_caveats` list, so a
QUALIFIED verdict at 10.0 is never silently read as "every dimension was
checked and clean". An `UNMET` condition always makes the level
`NOT_QUALIFIED`; a `NOT_AVAILABLE` one (evidence genuinely missing, not
structurally unmeasurable) makes it `INCOMPLETE_EVIDENCE` -- a level this
gate could not evaluate is a different fact from one it evaluated and found
wanting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"


class SubsystemMaturityGateError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Vocabularies -- both deliberately disjoint from `models.Status`
# ===========================================================================

#: One condition's outcome. `NOT_AVAILABLE` (evidence genuinely absent/unread)
#: is kept distinct from `NOT_MEASURABLE` (no producer for this fact exists in
#: this codebase at all) -- two different operator problems with two
#: different remedies, never collapsed into one "unknown".
MET = "MET"
UNMET = "UNMET"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_MEASURABLE = "NOT_MEASURABLE"
CONDITION_STATUSES: Tuple[str, ...] = (MET, UNMET, NOT_AVAILABLE, NOT_MEASURABLE)

#: This gate's own verdict over one maturity level's required conditions.
QUALIFIED = "QUALIFIED"
NOT_QUALIFIED = "NOT_QUALIFIED"
INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: Tuple[str, ...] = (QUALIFIED, NOT_QUALIFIED, INCOMPLETE_EVIDENCE)

LEVEL_9_0 = "9.0"
LEVEL_9_5 = "9.5"
LEVEL_10_0 = "10.0"
MATURITY_LEVELS: Tuple[str, ...] = (LEVEL_9_0, LEVEL_9_5, LEVEL_10_0)


def assert_no_verification_verdict_vocabulary() -> None:
    """Import-time guard: neither vocabulary above shares a token with
    `models.Status`. The same discipline `capability_evolution.py` /
    `benchmark_dataset.py` / `dependency_supply_chain.py` already enforce on
    their own domain vocabularies, applied to this one."""
    from .models import Status
    known = {s.value for s in Status}
    clash = sorted((set(CONDITION_STATUSES) | set(GATE_VERDICTS)) & known)
    if clash:
        raise SubsystemMaturityGateError("VERDICT_VOCABULARY_COLLIDES_WITH_MODELS_STATUS", {
            "clash": clash, "known_status_values": sorted(known)})


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Caller-supplied evidence bundle
# ===========================================================================

@dataclass
class GateInputs:
    """Every optional caller-supplied evidence artifact a condition may need.

    Nothing here is ever fabricated when absent -- a missing input makes its
    condition `NOT_AVAILABLE` naming exactly what would produce it, never a
    default value standing in for the fact.
    """
    cfg: Optional[Dict[str, Any]] = None
    # zero_vip_api_hallucination: EITHER an already-written vip_api_cards.json
    # artifact (create_environment()'s own output), OR sources + an index to
    # run validate_vip_api_usage() fresh.
    vip_api_cards_path: Any = None
    vip_sources: Optional[Sequence[Any]] = None
    vip_index_path: Any = None
    # bind_validation_clean: an already-loaded bind entry list, OR a bind
    # topology JSON path carrying a "bind_entries" list (the real
    # manifest_inputs/*_bind_topology.json shape).
    bind_entries: Optional[List[dict]] = None
    bind_topology_path: Any = None
    require_tier: bool = False
    # regression_evidence_exists: override the default evidence.duckdb path.
    evidence_db_path: Any = None
    # system_smoke_proof_ready: a real `system_build_proof.SmokeProofReport
    # .to_dict()` (or `execute_verb()`'s JSON), produced by actually running
    # the ladder -- this module never assembles the ladder's own heavy inputs
    # (composed sources, filelists, fsdb) itself.
    smoke_proof_report: Optional[Mapping[str, Any]] = None


# ===========================================================================
# Condition result + declaration
# ===========================================================================

@dataclass
class ConditionResult:
    condition_id: str
    status: str
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    fact_source: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"condition_id": self.condition_id, "status": self.status,
                "reason": self.reason, "evidence": self.evidence,
                "fact_source": list(self.fact_source)}


@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    description: str
    fact_source: Tuple[str, ...]
    evaluator: Callable[[Path, GateInputs], ConditionResult]


# ===========================================================================
# Condition 1: repeatable Spec-to-UVM-to-PASS path
# (golden_flow_readiness rows -- the structural half)
# ===========================================================================

COND_GOLDEN_FLOW_SPEC_TO_PASS = "golden_flow_spec_to_uvm_to_pass"

#: The four `golden_flow_readiness` rows that together are section 47's
#: Spec -> Requirement -> UVM generation -> single-test-PASS chain. Deliberately
#: NOT `lsf_regression` (a repeated-run signal): that evidence is read
#: directly off `evidence_db` by `regression_evidence_exists` below instead,
#: so the two conditions do not silently restate the same fact.
GOLDEN_FLOW_ROWS_FOR_SPEC_TO_UVM: Tuple[str, ...] = (
    "spec_in", "requirement_extraction", "vip_uvm_generation", "single_test_proof",
)


def _evaluate_golden_flow_spec_to_pass(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import golden_flow_readiness as gfr
    matrix = gfr.derive_golden_flow_readiness(root, inputs.cfg)
    rows = {r["row_id"]: r for r in (matrix.get("rows") or ())}
    missing = [rid for rid in GOLDEN_FLOW_ROWS_FOR_SPEC_TO_UVM if rid not in rows]
    if missing:
        # golden_flow_readiness always returns all twenty rows; this branch
        # only fires if that contract itself has drifted.
        return ConditionResult(COND_GOLDEN_FLOW_SPEC_TO_PASS, NOT_AVAILABLE,
            f"golden_flow_readiness did not report row(s) {missing}",
            {"missing_rows": missing})
    statuses = {rid: rows[rid]["status"] for rid in GOLDEN_FLOW_ROWS_FOR_SPEC_TO_UVM}
    gaps = {rid: rows[rid]["gap"] for rid in GOLDEN_FLOW_ROWS_FOR_SPEC_TO_UVM
            if statuses[rid] != gfr.READY}
    evidence = {"row_statuses": statuses, "row_gaps": gaps}
    if all(s == gfr.READY for s in statuses.values()):
        return ConditionResult(COND_GOLDEN_FLOW_SPEC_TO_PASS, MET,
            "golden_flow_readiness reports spec_in, requirement_extraction, "
            "vip_uvm_generation and single_test_proof all READY", evidence)
    blocked = [rid for rid, s in statuses.items() if s == gfr.BLOCKED]
    if blocked:
        return ConditionResult(COND_GOLDEN_FLOW_SPEC_TO_PASS, UNMET,
            f"golden_flow_readiness reports BLOCKED for: {sorted(blocked)}", evidence)
    return ConditionResult(COND_GOLDEN_FLOW_SPEC_TO_PASS, NOT_AVAILABLE,
        "golden_flow_readiness reports PARTIAL/UNKNOWN (not BLOCKED, not all READY) for at "
        "least one Spec-to-UVM-to-PASS row -- not yet proven connected end-to-end", evidence)


# ===========================================================================
# Condition 2: composed-system smoke proof (system_build_proof.SYSTEM_READY)
# -- the ladder half of "repeatable Spec-to-UVM-to-PASS path"
# ===========================================================================

COND_SYSTEM_SMOKE_PROOF_READY = "system_smoke_proof_ready"


def _evaluate_system_smoke_proof_ready(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import system_build_proof as sbp
    report = inputs.smoke_proof_report
    if report is None:
        return ConditionResult(COND_SYSTEM_SMOKE_PROOF_READY, NOT_AVAILABLE,
            "no system_build_proof.SmokeProofReport was supplied -- run "
            "`dv-harness system-smoke-proof --json` (or "
            "system_build_proof.run_system_smoke_proof()) and pass its .to_dict() as "
            "GateInputs.smoke_proof_report", {})
    verdict = (report or {}).get("verdict")
    if verdict not in sbp.SMOKE_VERDICTS:
        return ConditionResult(COND_SYSTEM_SMOKE_PROOF_READY, NOT_AVAILABLE,
            f"supplied smoke_proof_report carries an unrecognized verdict {verdict!r}, not one "
            f"of {list(sbp.SMOKE_VERDICTS)} -- refusing to trust it",
            {"supplied_verdict": verdict})
    evidence = {"verdict": verdict, "smoke_proof_evidence": report.get("evidence")}
    if verdict == sbp.SYSTEM_READY:
        return ConditionResult(COND_SYSTEM_SMOKE_PROOF_READY, MET,
            f"system_build_proof reported {sbp.SYSTEM_READY}: {report.get('evidence')}", evidence)
    if verdict == sbp.SMOKE_FAIL:
        return ConditionResult(COND_SYSTEM_SMOKE_PROOF_READY, UNMET,
            f"system_build_proof reported {sbp.SMOKE_FAIL}: {report.get('evidence')}", evidence)
    return ConditionResult(COND_SYSTEM_SMOKE_PROOF_READY, NOT_AVAILABLE,
        f"system_build_proof reported {verdict} -- not yet proven SYSTEM_READY", evidence)


# ===========================================================================
# Condition 3: zero VIP-API hallucination in the qualification set
# ===========================================================================

COND_ZERO_VIP_API_HALLUCINATION = "zero_vip_api_hallucination"


def _evaluate_zero_vip_api_hallucination(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import vip_api_card as vac
    if inputs.vip_api_cards_path:
        p = Path(inputs.vip_api_cards_path)
        if not p.exists():
            return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, NOT_AVAILABLE,
                f"vip_api_cards_path does not exist: {p}", {"vip_api_cards_path": str(p)})
        try:
            report_dict = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, NOT_AVAILABLE,
                f"vip_api_cards artifact at {p} could not be read: {type(e).__name__}: {e}",
                {"vip_api_cards_path": str(p)})
        status = report_dict.get("status")
        counts = report_dict.get("counts") or {}
        reason_absent = report_dict.get("reason")
    elif inputs.vip_sources and inputs.vip_index_path:
        try:
            index = vac.load_index(inputs.vip_index_path)
            report = vac.validate_vip_api_usage(list(inputs.vip_sources), index,
                                                 relative_to=root)
        except vac.VipApiValidationError as e:
            return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, NOT_AVAILABLE,
                f"VIP API validation could not run: {e}", {})
        status, counts, reason_absent = report.status, report.counts, report.reason
    else:
        return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, NOT_AVAILABLE,
            "no VIP API validation evidence supplied (GateInputs.vip_api_cards_path, or "
            "vip_sources + vip_index_path)", {})

    evidence = {"status": status, "counts": counts}
    if status == vac.NOT_AVAILABLE:
        return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, NOT_AVAILABLE,
            f"VIP API validation reported NOT_AVAILABLE: {reason_absent}", evidence)
    blocked = int(counts.get(vac.BLOCKED, 0) or 0)
    if blocked:
        return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, UNMET,
            f"{blocked} BLOCKED VIP API citation(s): a provably fabricated VIP class/method "
            "usage exists in the qualification set", evidence)
    return ConditionResult(COND_ZERO_VIP_API_HALLUCINATION, MET,
        f"zero BLOCKED VIP API citations (status={status}, counts={counts})", evidence)


# ===========================================================================
# Condition 4: bind validation clean -- no unresolved T3/T4
# ===========================================================================

COND_BIND_VALIDATION_CLEAN = "bind_validation_clean"


def _load_bind_entries(inputs: GateInputs) -> Optional[List[dict]]:
    if inputs.bind_entries is not None:
        return list(inputs.bind_entries)
    if inputs.bind_topology_path:
        p = Path(inputs.bind_topology_path)
        if not p.exists():
            return None
        doc = json.loads(p.read_text(encoding="utf-8"))
        entries = doc.get("bind_entries")
        return list(entries) if isinstance(entries, list) else []
    return None


def _evaluate_bind_validation_clean(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import connectivity as conn
    entries = _load_bind_entries(inputs)
    if entries is None:
        return ConditionResult(COND_BIND_VALIDATION_CLEAN, NOT_AVAILABLE,
            "no bind entries supplied (GateInputs.bind_entries, or bind_topology_path naming a "
            "real manifest_inputs/*_bind_topology.json)", {})
    if not entries:
        return ConditionResult(COND_BIND_VALIDATION_CLEAN, NOT_AVAILABLE,
            "the supplied bind entry set is empty -- nothing to resolve", {"entry_count": 0})

    decisions: List[dict] = []
    violations: List[dict] = []
    for i, entry in enumerate(entries):
        try:
            tier = conn.assert_bind_entry_tier_allows_emission(
                entry, index=i, require_tier=inputs.require_tier)
            decisions.append({"index": i, "target_instance": entry.get("target_instance"),
                              "tier": tier})
        except conn.BindTierError as e:
            violations.append({"index": i, "target_instance": entry.get("target_instance"),
                               "reason": e.reason, "detail": e.detail})
    evidence = {"entry_count": len(entries), "decisions": decisions, "violations": violations}
    if violations:
        return ConditionResult(COND_BIND_VALIDATION_CLEAN, UNMET,
            f"{len(violations)} of {len(entries)} bind entries are unresolved: an unconfirmed "
            "T3 naming-heuristic bind or a T4 undecidable bind that must go to the question "
            f"queue ({[v['reason'] for v in violations]})", evidence)
    return ConditionResult(COND_BIND_VALIDATION_CLEAN, MET,
        f"all {len(entries)} bind entries resolve to an auto-emittable tier (T1/T2) or a "
        "human-confirmed T3; no unresolved T3/T4", evidence)


# ===========================================================================
# Condition 5: real regression evidence exists (evidence_db rows)
# ===========================================================================

COND_REGRESSION_EVIDENCE_EXISTS = "regression_evidence_exists"


def _evaluate_regression_evidence_exists(root: Path, inputs: GateInputs) -> ConditionResult:
    from . import evidence_db as edb
    db_path = Path(inputs.evidence_db_path) if inputs.evidence_db_path \
        else edb.default_db_path(Path(root))
    if not db_path.exists():
        return ConditionResult(COND_REGRESSION_EVIDENCE_EXISTS, NOT_AVAILABLE,
            f"no evidence database on disk at {db_path}", {"db_path": str(db_path)})
    try:
        with edb.EvidenceStore(db_path, read_only=True) as store:
            job_count = store.query("SELECT COUNT(*) FROM jobs")[0][0]
            evidence_count = store.query("SELECT COUNT(*) FROM normalized_evidence")[0][0]
    except Exception as e:
        return ConditionResult(COND_REGRESSION_EVIDENCE_EXISTS, NOT_AVAILABLE,
            f"evidence database at {db_path} could not be read: {type(e).__name__}: {e}",
            {"db_path": str(db_path)})
    evidence = {"db_path": str(db_path), "job_rows": int(job_count),
                "normalized_evidence_rows": int(evidence_count)}
    if job_count or evidence_count:
        return ConditionResult(COND_REGRESSION_EVIDENCE_EXISTS, MET,
            f"{job_count} real regression job row(s) and {evidence_count} normalized evidence "
            "row(s) recorded", evidence)
    return ConditionResult(COND_REGRESSION_EVIDENCE_EXISTS, NOT_AVAILABLE,
        f"evidence database exists at {db_path} but holds zero job rows and zero "
        "normalized_evidence rows -- no real regression evidence recorded yet", evidence)


# ===========================================================================
# Condition 6: false-PASS count is zero -- NOT_MEASURABLE, honestly, always
# ===========================================================================

COND_FALSE_PASS_COUNT_ZERO = "false_pass_count_zero"

#: Recorded verbatim rather than paraphrased on every report, so the search
#: this condition rests on is checkable by a reader without re-running it.
#: Re-verify with `grep -rn "false_pass\\|FALSE_PASS\\|false positive" -i
#: dv_harness/*.py` before ever changing this to something other than
#: NOT_MEASURABLE.
FALSE_PASS_SIGNAL_SEARCH_NOTE = (
    "Checked dv_harness.golden_scenario and dv_harness.requirement_contract (the two modules "
    "this gate's own spec named as the likeliest home for an existing false-PASS signal), plus "
    "a repo-wide grep for false_pass/FALSE_PASS/false positive across dv_harness/*.py: neither "
    "module, nor any other real producer in this codebase, persists a COUNT of confirmed "
    "false-PASS verdicts over a qualification set. tools/verification_flow/"
    "false_pass_resistance_gate.py is a PER-STAGE, AGENT-ATTESTED evidence-block shape check "
    "(five boolean claims plus a proof-bundle hash) -- not a count, and TH-9's "
    "evidence_provenance.py work already treats a gate shaped like it as AGENT_SELF_ATTESTED "
    "unless a real tool/simulation artifact backs it. Inventing a counter here would be "
    "exactly the fabrication the Evidence Truth Rule forbids."
)


def _evaluate_false_pass_count_zero(root: Path, inputs: GateInputs) -> ConditionResult:
    return ConditionResult(COND_FALSE_PASS_COUNT_ZERO, NOT_MEASURABLE,
        FALSE_PASS_SIGNAL_SEARCH_NOTE,
        {"checked_modules": ["dv_harness.golden_scenario", "dv_harness.requirement_contract"]})


# ===========================================================================
# The condition table + the maturity ladder
# ===========================================================================

CONDITIONS: Tuple[ConditionSpec, ...] = (
    ConditionSpec(
        COND_GOLDEN_FLOW_SPEC_TO_PASS,
        "Spec -> Requirement -> UVM generation -> single-test-PASS is connected end-to-end "
        "with evidence (golden_flow_readiness's own rows).",
        ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",
         "dv_harness.golden_flow_readiness.READY",
         "dv_harness.golden_flow_readiness.BLOCKED"),
        _evaluate_golden_flow_spec_to_pass),
    ConditionSpec(
        COND_SYSTEM_SMOKE_PROOF_READY,
        "The composed-system smoke-proof ladder (system_build_proof.py) reports SYSTEM_READY.",
        ("dv_harness.system_build_proof.SYSTEM_READY",
         "dv_harness.system_build_proof.SMOKE_FAIL",
         "dv_harness.system_build_proof.SMOKE_VERDICTS"),
        _evaluate_system_smoke_proof_ready),
    ConditionSpec(
        COND_ZERO_VIP_API_HALLUCINATION,
        "Zero BLOCKED VIP API citations in the qualification set (vip_api_card.py).",
        ("dv_harness.vip_api_card.validate_vip_api_usage",
         "dv_harness.vip_api_card.load_index",
         "dv_harness.vip_api_card.BLOCKED",
         "dv_harness.vip_api_card.NOT_AVAILABLE"),
        _evaluate_zero_vip_api_hallucination),
    ConditionSpec(
        COND_BIND_VALIDATION_CLEAN,
        "Bind validation clean: no unresolved T3 (unconfirmed) or T4 (undecidable) bind "
        "entries (connectivity.py's tier resolution).",
        ("dv_harness.connectivity.assert_bind_entry_tier_allows_emission",
         "dv_harness.connectivity.BindTierError"),
        _evaluate_bind_validation_clean),
    ConditionSpec(
        COND_REGRESSION_EVIDENCE_EXISTS,
        "Real regression evidence exists (evidence_db.py rows: jobs / normalized_evidence).",
        ("dv_harness.evidence_db.EvidenceStore", "dv_harness.evidence_db.default_db_path"),
        _evaluate_regression_evidence_exists),
    ConditionSpec(
        COND_FALSE_PASS_COUNT_ZERO,
        "False-PASS count over the qualification set is zero. NOT_MEASURABLE in this codebase "
        "today -- no real counter exists; see FALSE_PASS_SIGNAL_SEARCH_NOTE.",
        ("dv_harness.golden_scenario", "dv_harness.requirement_contract"),
        _evaluate_false_pass_count_zero),
)

CONDITIONS_BY_ID: Dict[str, ConditionSpec] = {c.condition_id: c for c in CONDITIONS}

#: A strictly monotonic ladder: every level's required set is a superset of
#: the level below it (`assert_levels_are_monotonic()`).
LEVEL_REQUIREMENTS: Dict[str, Tuple[str, ...]] = {
    LEVEL_9_0: (COND_GOLDEN_FLOW_SPEC_TO_PASS, COND_REGRESSION_EVIDENCE_EXISTS),
    LEVEL_9_5: (COND_GOLDEN_FLOW_SPEC_TO_PASS, COND_REGRESSION_EVIDENCE_EXISTS,
                COND_ZERO_VIP_API_HALLUCINATION, COND_BIND_VALIDATION_CLEAN),
    LEVEL_10_0: (COND_GOLDEN_FLOW_SPEC_TO_PASS, COND_REGRESSION_EVIDENCE_EXISTS,
                 COND_ZERO_VIP_API_HALLUCINATION, COND_BIND_VALIDATION_CLEAN,
                 COND_SYSTEM_SMOKE_PROOF_READY, COND_FALSE_PASS_COUNT_ZERO),
}


def _assert_conditions_and_requirements_consistent() -> None:
    ids = [c.condition_id for c in CONDITIONS]
    if len(set(ids)) != len(ids):
        raise SubsystemMaturityGateError("DUPLICATE_CONDITION_ID", {"condition_ids": ids})
    known = set(CONDITIONS_BY_ID)
    for level, required in LEVEL_REQUIREMENTS.items():
        unknown = [cid for cid in required if cid not in known]
        if unknown:
            raise SubsystemMaturityGateError("LEVEL_REQUIRES_UNDECLARED_CONDITION", {
                "level": level, "unknown_condition_ids": unknown})


def assert_levels_are_monotonic() -> None:
    """9.0's required conditions are a subset of 9.5's, which are a subset of
    10.0's -- a maturity ladder that got EASIER at a higher level would not be
    one."""
    prior: set = set()
    for level in MATURITY_LEVELS:
        current = set(LEVEL_REQUIREMENTS[level])
        if not prior <= current:
            raise SubsystemMaturityGateError("LEVEL_REQUIREMENTS_NOT_MONOTONIC", {
                "level": level, "missing_from_this_level": sorted(prior - current)})
        prior = current


_assert_conditions_and_requirements_consistent()
assert_levels_are_monotonic()


def assert_fact_sources_resolvable() -> List[str]:
    """Every declared `fact_source` still resolves through the import system.

    Mirrors `golden_flow_readiness.assert_fact_sources_resolvable()`: a
    condition citing a renamed/removed function must fail a test, not
    silently report a fabricated MET."""
    import importlib
    resolved: List[str] = []
    for spec in CONDITIONS:
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
                raise SubsystemMaturityGateError("FACT_SOURCE_MODULE_UNIMPORTABLE", {
                    "fact_source": dotted, "condition_id": spec.condition_id})
            for name in rest:
                if not hasattr(obj, name):
                    raise SubsystemMaturityGateError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                        "fact_source": dotted, "condition_id": spec.condition_id,
                        "missing_attribute": name})
                obj = getattr(obj, name)
            resolved.append(dotted)
    return resolved


# ===========================================================================
# The gate
# ===========================================================================

def derive_maturity_gate(level: str, root: Any,
                         inputs: Optional[GateInputs] = None) -> Dict[str, Any]:
    """Evaluate every declared condition once, then fold the LEVEL's own
    required subset into one verdict.

    Every condition is evaluated (not only the ones this level requires) so a
    caller comparing 9.0/9.5/10.0 against one project gets one full report
    rather than re-deriving the shared facts three times.
    """
    if level not in MATURITY_LEVELS:
        raise SubsystemMaturityGateError("UNKNOWN_MATURITY_LEVEL", {
            "level": level, "known_levels": list(MATURITY_LEVELS)})
    root = Path(root)
    inputs = inputs or GateInputs()

    results: Dict[str, ConditionResult] = {}
    for cid, spec in CONDITIONS_BY_ID.items():
        try:
            result = spec.evaluator(root, inputs)
        except Exception as e:  # an evaluator bug must read as NOT_AVAILABLE, never crash the gate
            result = ConditionResult(cid, NOT_AVAILABLE,
                f"condition evaluator raised {type(e).__name__}: {e}", {})
        if result.status not in CONDITION_STATUSES:
            raise SubsystemMaturityGateError("CONDITION_RETURNED_UNKNOWN_STATUS", {
                "condition_id": cid, "status": result.status,
                "legal_values": list(CONDITION_STATUSES)})
        result.fact_source = spec.fact_source
        results[cid] = result

    required = LEVEL_REQUIREMENTS[level]
    required_results = {cid: results[cid] for cid in required}
    unmet = sorted(cid for cid, r in required_results.items() if r.status == UNMET)
    unavailable = sorted(cid for cid, r in required_results.items() if r.status == NOT_AVAILABLE)
    disclosed_caveats = sorted(cid for cid, r in required_results.items()
                               if r.status == NOT_MEASURABLE)

    if unmet:
        verdict = NOT_QUALIFIED
    elif unavailable:
        verdict = INCOMPLETE_EVIDENCE
    else:
        verdict = QUALIFIED

    return {
        "schema_version": SCHEMA_VERSION,
        "level": level,
        "root": str(root),
        "verdict": verdict,
        "required_conditions": list(required),
        "conditions": {cid: r.to_dict() for cid, r in results.items()},
        "unmet_conditions": unmet,
        "unavailable_conditions": unavailable,
        "disclosed_caveats": disclosed_caveats,
        "verdict_rule": (
            "QUALIFIED requires every REQUIRED condition to be MET or NOT_MEASURABLE (a "
            "condition this harness structurally cannot measure never blocks a level -- it is "
            "instead surfaced under disclosed_caveats, never silently cleared); one UNMET "
            "required condition -> NOT_QUALIFIED; otherwise, with no UNMET but at least one "
            "required condition NOT_AVAILABLE (evidence not supplied/found) -> "
            "INCOMPLETE_EVIDENCE."),
        "authorizes": (
            "nothing. This gate approves no promotion, no signoff and no production write -- "
            "it is a composite READ over conditions this project's own real gates/artifacts "
            "already establish, for a human to weigh."),
    }


# ===========================================================================
# Rendering + CLI
# ===========================================================================

MATURITY_GATE_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("condition_id", "Condition"),
    ("required", "Required"),
    ("status", "Status"),
    ("reason", "Reason"),
)


def render_maturity_gate_table(report: Mapping[str, Any]) -> str:
    from .connectivity import render_markdown_table
    required = set(report.get("required_conditions") or ())
    rows = []
    for cid, r in (report.get("conditions") or {}).items():
        rows.append({"condition_id": cid, "required": "yes" if cid in required else "no",
                     "status": r["status"], "reason": r["reason"]})
    rows.sort(key=lambda r: (r["required"] != "yes", r["condition_id"]))
    return render_markdown_table(list(MATURITY_GATE_COLUMNS), rows,
                                 empty_note="(no condition evaluated -- this is a bug)")


def format_maturity_gate_report(report: Mapping[str, Any]) -> str:
    out = [
        f"# SUBSYSTEM MATURITY GATE {report['level']}",
        "",
        f"**{report['verdict']}**",
        "",
        f"Project root: `{report['root']}`",
        "",
        render_maturity_gate_table(report),
        "",
        report["verdict_rule"],
        "",
        f"This verdict authorizes: {report['authorizes']}",
    ]
    if report.get("disclosed_caveats"):
        out += ["", "## Disclosed caveats (never block QUALIFIED, never silently cleared)", ""]
        conds = report["conditions"]
        out += [f"- **{cid}** -- {conds[cid]['reason']}" for cid in report["disclosed_caveats"]]
    return "\n".join(out)


def execute_verb(level: str, root: Any, *, inputs: Optional[GateInputs] = None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.subsystem_maturity_gate
    evaluate`. Exit 0 QUALIFIED, 1 NOT_QUALIFIED, 2 INCOMPLETE_EVIDENCE."""
    report = derive_maturity_gate(level, root, inputs)
    text = json.dumps(report, indent=2) if as_json else format_maturity_gate_report(report)
    code = {QUALIFIED: 0, NOT_QUALIFIED: 1, INCOMPLETE_EVIDENCE: 2}[report["verdict"]]
    return text, code


def render_conditions_report(*, as_json: bool = False) -> str:
    rows = [{
        "condition_id": c.condition_id,
        "description": c.description,
        "fact_source": list(c.fact_source),
        "required_at_levels": [lvl for lvl in MATURITY_LEVELS
                               if c.condition_id in LEVEL_REQUIREMENTS[lvl]],
    } for c in CONDITIONS]
    if as_json:
        return json.dumps({"schema_version": SCHEMA_VERSION, "conditions": rows,
                           "level_requirements": {lvl: list(LEVEL_REQUIREMENTS[lvl])
                                                  for lvl in MATURITY_LEVELS}}, indent=2)
    lines = ["# Subsystem maturity gate conditions", ""]
    for r in rows:
        lines.append(f"- **{r['condition_id']}** (required at: "
                     f"{', '.join(r['required_at_levels']) or 'none'})")
        lines.append(f"  {r['description']}")
        lines.append(f"  fact_source: {', '.join(r['fact_source']) or '(none)'}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.subsystem_maturity_gate",
        description="Composite 9.0/9.5/10.0 subsystem maturity qualification gates. "
                    "Reads only; runs no stage, gate script, build, regression or LSF job.")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_conditions = sub.add_parser("conditions", help="list the declared conditions")
    p_conditions.add_argument("--json", action="store_true", dest="as_json")

    p_eval = sub.add_parser("evaluate", help="evaluate one maturity level")
    p_eval.add_argument("--level", required=True, choices=list(MATURITY_LEVELS))
    p_eval.add_argument("--root", default=".")
    p_eval.add_argument("--json", action="store_true", dest="as_json")
    p_eval.add_argument("--vip-api-cards", default=None,
                        help="path to a written vip_api_cards.json artifact")
    p_eval.add_argument("--vip-source", action="append", default=None, dest="vip_sources",
                        help="generated SystemVerilog source/dir to validate (repeatable); "
                             "used only if --vip-api-cards is not given")
    p_eval.add_argument("--vip-index", default=None,
                        help="a vip_symbol_index document, used with --vip-source")
    p_eval.add_argument("--bind-topology", default=None,
                        help="a manifest_inputs/*_bind_topology.json path")
    p_eval.add_argument("--require-tier", action="store_true")
    p_eval.add_argument("--evidence-db", default=None,
                        help="override the default .dv-harness/evidence/evidence.duckdb path")
    p_eval.add_argument("--smoke-proof-report", default=None,
                        help="a JSON file holding a system_build_proof.SmokeProofReport.to_dict()")
    args = parser.parse_args(argv)

    if args.verb == "conditions":
        print(render_conditions_report(as_json=args.as_json))
        return 0

    smoke_proof_report = None
    if args.smoke_proof_report:
        smoke_proof_report = json.loads(Path(args.smoke_proof_report).read_text(encoding="utf-8"))
    inputs = GateInputs(
        vip_api_cards_path=args.vip_api_cards,
        vip_sources=args.vip_sources,
        vip_index_path=args.vip_index,
        bind_topology_path=args.bind_topology,
        require_tier=args.require_tier,
        evidence_db_path=args.evidence_db,
        smoke_proof_report=smoke_proof_report,
    )
    text, code = execute_verb(args.level, Path(args.root), inputs=inputs, as_json=args.as_json)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
