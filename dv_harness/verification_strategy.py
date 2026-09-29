"""VI-4 -- the Verification Strategy Optimizer.

WHICH verification strategy fits a given goal: simulation, formal, PSS,
emulation (ZeBu-class) or FPGA prototyping (HAPS-class). Until 2026-09-06
nothing in this harness answered that question -- a repo-wide grep for
`strategy_optimizer` / `verification_strategy` / `strategy_recommend` returned
nothing, and the only occurrences of "formal" in `dv_harness/**.py` were
Verilog FORMAL PORTS in the verible parser and the fabric discovery. "ZeBu" and
"HAPS" appeared exactly once, as two `memory_vault.py` vault FOLDER NAMES.

WHAT THIS MODULE IS NOT, stated first because it is the whole design
constraint
--------------------------------------------------------------------------
This harness's real, provable execution capability is SIMULATION: a VCS
regression submitted to LSF (`lsf_client.bsub_submit_with_preflight()`) behind
`preflight.run_preflight()`'s license/queue/host checks. There is no formal
tool, no PSS tool, no emulator and no FPGA prototype integrated ANYWHERE in
this repository -- no adapter, no client module, no config key, no command
template. A recommendation engine that emitted "run formal on this" as though
the harness could then go do it would be exactly the overstatement
`protocol_capability.py` was written to delete from the protocol registry, one
layer up.

So EXECUTABILITY IS DERIVED FROM CODE, NEVER TYPED IN. Every strategy declares
the backend module + entry point it would need (`STRATEGY_BACKENDS`), and
`derive_executability()` resolves it through the real import system. SIMULATION
resolves and is `EXECUTABLE_HERE`. The other four do not resolve and are
`RECOMMEND_ONLY_NO_BACKEND`. Build a real `dv_harness/formal_client.py` with
the named entry point one day and FORMAL flips to executable on its own; delete
`lsf_client.bsub_submit_with_preflight` and SIMULATION stops claiming to be
executable -- both without editing a status string.
`assert_no_unexecutable_strategy_claimed_executable()` re-checks that on the
way out of every recommendation, and `assert_executability_matches_code()` (run
by the `capabilities` verb) fails the moment the derived answer stops matching
this repository's documented state -- so a future edit cannot quietly
re-collapse the two, and a genuinely NEW backend forces the docs and tests to be
updated with it rather than drifting.

A RECOMMEND_ONLY strategy that this module RECOMMENDS therefore always carries
an `executable_next_action`: the real thing THIS harness can do about it today
(file the decision as a Tier-3 question, escalate the unreachable bins, file the
capability candidate). "Recommend formal" alone is not an answer a harness that
cannot run formal is entitled to stop at.

WHAT IT REASONS OVER -- real signals this harness already computes
--------------------------------------------------------------------------
Nothing here measures anything new. Every signal is another module's existing
output, imported rather than reimplemented:

  * **coverage-closure difficulty** -- `loop_convergence.classify_loop_convergence()`
    (which itself reads the real series through `trend_analysis.daily_rollup()`
    and runs `investigate_plateau()` over `coverage_analysis.classify_coverage_hole()`'s
    per-bin verdicts). Its four per-bin classes are the difference between
    "nobody has run this yet" and "randomization structurally cannot get there",
    which is precisely the simulation/formal decision.
  * **bug / failure density** -- `capability_evolution.repeated_unresolved_failure_patterns()`
    for signatures that recur across INDEPENDENT runs and no `verified_fix`
    closes, plus the aggregate `failure_signatures` table read READ-ONLY out of
    `evidence_db`. Failure identity is `evidence_db.signature_key()` in both --
    never a second definition of "the same failure".
  * **per-protocol capability** -- `protocol_capability.capability_for()`'s real
    `capability_status` and the model's own `does_not_model` layers.
  * **multi-subsystem scope** -- `environment_mode_router.read_registered_subsystem_entries()`,
    the gate-validated registry `engine.py` writes on a real SIGNOFF PASS.

NOTHING HERE WRITES. Like `loop_convergence.PlateauInvestigation`, this module
NAMES the real escalation path and takes it for none of them: no question is
filed, no candidate is minted, no memory record is written, no evidence
database is created or migrated, and no build/regression/LSF submission is
triggered by any code path in this file.

THE GOAL IS RECORDED, NOT PARSED. `goal_text` is carried verbatim and
`goal_text_machine_evaluated` is False, the same contract
`capability_evolution` puts on `acceptance_criteria_machine_evaluated`.
Structured facts a caller can actually state (scope, protocol, holes) drive the
rules; free text never silently becomes a verdict.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "STRATEGIES", "STRATEGY_VERDICTS", "EXECUTABILITY_VALUES",
    "StrategyBackend", "StrategySignals", "StrategyRecommendation",
    "StrategyReport", "StrategyExecutabilityOverstatedError",
    "derive_executability", "executability_rows",
    "assert_executability_matches_code",
    "assert_no_unexecutable_strategy_claimed_executable",
    "assert_no_verification_verdict_vocabulary",
    "assert_named_escalators_resolve",
    "gather_signals", "recommend_strategies", "render_strategy_report_text",
    "execute_verb",
]


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------
#: The five strategies the question is actually about. Deliberately NOT a
#: superset -- "directed test" and "constrained random" are both SIMULATION
#: here, because the thing that differs between them is stimulus authoring,
#: not which engine executes it, and this module's whole job is the engine
#: choice.
STRATEGY_SIMULATION = "SIMULATION"
STRATEGY_FORMAL = "FORMAL"
STRATEGY_PSS = "PSS"
STRATEGY_EMULATION = "EMULATION"
STRATEGY_FPGA_PROTOTYPE = "FPGA_PROTOTYPE"

STRATEGIES: Tuple[str, ...] = (
    STRATEGY_SIMULATION, STRATEGY_FORMAL, STRATEGY_PSS,
    STRATEGY_EMULATION, STRATEGY_FPGA_PROTOTYPE,
)

#: What this harness can DO about a strategy, derived by `derive_executability()`
#: from the import system -- never asserted by a literal in a table.
EXECUTABLE_HERE = "EXECUTABLE_HERE"
RECOMMEND_ONLY_NO_BACKEND = "RECOMMEND_ONLY_NO_BACKEND"
EXECUTABILITY_VALUES: Tuple[str, ...] = (EXECUTABLE_HERE, RECOMMEND_ONLY_NO_BACKEND)

#: What the SIGNALS say about a strategy. Separate axis from executability on
#: purpose: "formal is the right answer here" and "this harness cannot run
#: formal" are both true at once, and one field carrying both is the collapsed
#: label `protocol_capability.py` exists to refuse.
VERDICT_RECOMMENDED = "RECOMMENDED"
VERDICT_NOT_INDICATED = "NOT_INDICATED"
VERDICT_NO_SIGNAL = "NO_SIGNAL"
VERDICT_SUPPRESSED = "SUPPRESSED"

STRATEGY_VERDICTS: Tuple[str, ...] = (
    VERDICT_RECOMMENDED, VERDICT_NOT_INDICATED, VERDICT_NO_SIGNAL, VERDICT_SUPPRESSED,
)

#: Declared verification scope. An explicit caller-supplied fact, never
#: inferred from `goal_text`.
SCOPE_BLOCK = "BLOCK"
SCOPE_SUBSYSTEM = "SUBSYSTEM"
SCOPE_SYSTEM = "SYSTEM"
SCOPE_UNDECLARED = "UNDECLARED"
SCOPES: Tuple[str, ...] = (SCOPE_BLOCK, SCOPE_SUBSYSTEM, SCOPE_SYSTEM, SCOPE_UNDECLARED)


class StrategyExecutabilityOverstatedError(RuntimeError):
    """A recommendation claimed a strategy is executable here when the backend
    it named does not resolve. Raised rather than returned: a report that has
    already overstated what this harness can do must not reach a caller at
    all."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's three vocabularies must share no token with
    `models.Status`, the harness's verification verdict vocabulary -- the same
    disjointness `capability_evolution.assert_no_verification_verdict_vocabulary()`
    enforces, for the same reason: a STRATEGY recommendation must never be
    confusable, by a reader or a log grep, with a PASS/FAIL verification
    result."""
    from .models import Status

    verdicts = {s.value for s in Status}
    for name, vocabulary in (
        ("STRATEGIES", STRATEGIES),
        ("STRATEGY_VERDICTS", STRATEGY_VERDICTS),
        ("EXECUTABILITY_VALUES", EXECUTABILITY_VALUES),
        ("SCOPES", SCOPES),
    ):
        collision = verdicts.intersection(vocabulary)
        if collision:
            raise StrategyExecutabilityOverstatedError(
                f"{name} collides with dv_harness.models.Status on {sorted(collision)}")


# --------------------------------------------------------------------------
# Executability: derived from the import system, never declared
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class StrategyBackend:
    """What a strategy would need for this harness to EXECUTE it, and what it
    is scored against.

    `required` is a tuple of `"module:attribute"` entry points. ALL must
    resolve for the strategy to be `EXECUTABLE_HERE` -- a module that imports
    but has lost the callable is not a backend. This is the same real
    import+getattr resolution `protocol_capability.resolve_generator_class()`
    does, for the same reason: a string check would keep passing after the
    thing it names is gone.

    For the four strategies with no backend, `required` names the module that
    WOULD have to exist. That is deliberate and load-bearing: it makes the
    absence a resolvable, greppable fact instead of a footnote, and it means
    building the real thing at that name is all it takes to flip the row.
    """
    strategy: str
    required: Tuple[str, ...]
    what_it_would_run: str
    absent_note: str = ""


#: SIMULATION's two entry points are the ones a real regression actually goes
#: through in this repo -- verified present on 2026-09-06 and re-verified by
#: `assert_executability_matches_code()` on every call.
STRATEGY_BACKENDS: Tuple[StrategyBackend, ...] = (
    StrategyBackend(
        strategy=STRATEGY_SIMULATION,
        required=("dv_harness.lsf_client:bsub_submit_with_preflight",
                  "dv_harness.preflight:run_preflight"),
        what_it_would_run="a VCS regression submitted to LSF behind the real "
                          "license/queue/host preflight",
    ),
    StrategyBackend(
        strategy=STRATEGY_FORMAL,
        required=("dv_harness.formal_client:prove_property",),
        what_it_would_run="a property/assertion proof run on a formal engine "
                          "(VC Formal / JasperGold class)",
        absent_note="no formal engine is integrated in this harness: no client "
                    "module, no adapter, no config key, no command template",
    ),
    StrategyBackend(
        strategy=STRATEGY_PSS,
        required=("dv_harness.pss_client:generate_scenario",),
        what_it_would_run="a portable-stimulus model compiled into per-target "
                          "scenario tests",
        absent_note="no PSS tool is integrated in this harness; `router.py`'s "
                    "RESEARCH_FOCUS_DOMAINS lists 'pss' as a RESEARCH topic, "
                    "which is a reading list, not an execution path",
    ),
    StrategyBackend(
        strategy=STRATEGY_EMULATION,
        required=("dv_harness.emulation_client:submit_emulation_run",),
        what_it_would_run="a compiled emulation image run on a ZeBu-class box",
        absent_note="no emulator is integrated in this harness; 'ZeBu' occurs "
                    "once in the repository, as a memory_vault.py vault folder "
                    "name",
    ),
    StrategyBackend(
        strategy=STRATEGY_FPGA_PROTOTYPE,
        required=("dv_harness.prototype_client:submit_prototype_run",),
        what_it_would_run="a synthesized prototype bitstream run on a "
                          "HAPS-class board",
        absent_note="no FPGA prototype flow is integrated in this harness; "
                    "'HAPS' occurs once in the repository, as a memory_vault.py "
                    "vault folder name",
    ),
)

_BACKEND_BY_STRATEGY: Dict[str, StrategyBackend] = {b.strategy: b for b in STRATEGY_BACKENDS}


def _resolve_entry_point(entry: str) -> Tuple[bool, str]:
    """`"module:attr"` -> (resolved, reason). Real import + getattr."""
    module_name, _, attr = entry.partition(":")
    try:
        if importlib.util.find_spec(module_name) is None:
            return False, f"{module_name}: no such module"
    except (ImportError, ValueError, AttributeError) as exc:
        return False, f"{module_name}: not importable ({type(exc).__name__}: {exc})"
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - a module that specs but fails to import
        return False, f"{module_name}: import failed ({type(exc).__name__}: {exc})"
    if attr and getattr(mod, attr, None) is None:
        return False, f"{module_name}: has no {attr!r} entry point"
    return True, f"{entry}: resolved"


def derive_executability(strategy: str) -> Dict[str, Any]:
    """What this harness can really do about `strategy`, from the import
    system only.

    Returns `{"strategy", "executability", "execution_path", "unresolved",
    "basis", "what_it_would_run", "absent_note"}`. `execution_path` is None
    for anything not `EXECUTABLE_HERE` -- there is no path to name, and naming
    a hypothetical one is how a recommendation becomes a claim.
    """
    backend = _BACKEND_BY_STRATEGY.get(strategy)
    if backend is None:
        raise ValueError(f"unknown strategy {strategy!r}; known: {list(STRATEGIES)}")
    resolved: List[str] = []
    unresolved: List[str] = []
    for entry in backend.required:
        ok, reason = _resolve_entry_point(entry)
        (resolved if ok else unresolved).append(reason)
    executable = not unresolved
    return {
        "strategy": strategy,
        "executability": EXECUTABLE_HERE if executable else RECOMMEND_ONLY_NO_BACKEND,
        "execution_path": list(backend.required) if executable else None,
        "unresolved": unresolved,
        "basis": ("; ".join(resolved) if executable else "; ".join(unresolved)),
        "what_it_would_run": backend.what_it_would_run,
        "absent_note": backend.absent_note,
    }


def executability_rows() -> List[Dict[str, Any]]:
    """One derived row per strategy, in `STRATEGIES` order."""
    return [derive_executability(s) for s in STRATEGIES]


def assert_executability_matches_code() -> None:
    """The one invariant this module cannot be allowed to lose: SIMULATION is
    the ONLY strategy with a real backend in this repository.

    This is not a restatement of the table -- it is a check that the DERIVED
    answer still matches the documented state of the repo. If someone builds a
    real `formal_client.prove_property`, this assertion fires and forces the
    docstring, CLAUDE.md and the tests to be updated together, rather than
    letting a genuine new capability land silently in a module whose whole
    contract is honesty about what exists.
    """
    rows = {r["strategy"]: r["executability"] for r in executability_rows()}
    problems = []
    if rows.get(STRATEGY_SIMULATION) != EXECUTABLE_HERE:
        problems.append(
            f"{STRATEGY_SIMULATION} is {rows.get(STRATEGY_SIMULATION)} -- this harness's "
            "one real execution backend no longer resolves")
    for strategy in (STRATEGY_FORMAL, STRATEGY_PSS, STRATEGY_EMULATION,
                     STRATEGY_FPGA_PROTOTYPE):
        if rows.get(strategy) != RECOMMEND_ONLY_NO_BACKEND:
            problems.append(
                f"{strategy} now resolves a real backend -- update this module's "
                "docstring, CLAUDE.md and the tests together with the new capability")
    if problems:
        raise StrategyExecutabilityOverstatedError("; ".join(problems))


def assert_no_unexecutable_strategy_claimed_executable(
        recommendations: Sequence["StrategyRecommendation"]) -> None:
    """Two checks over a finished report, both re-derived from the import
    system rather than trusted from the record:

    1. no row claims `EXECUTABLE_HERE` (or names an `execution_path`) unless
       its backend really resolves right now;
    2. every RECOMMENDED row that is `RECOMMEND_ONLY_NO_BACKEND` carries a
       non-empty `executable_next_action`. Handing back "use formal" with no
       act this harness can perform is the failure mode this module exists to
       avoid -- it reads as a capability and is not one.
    """
    problems: List[str] = []
    for rec in recommendations:
        derived = derive_executability(rec.strategy)
        if rec.executability != derived["executability"]:
            problems.append(
                f"{rec.strategy}: reports {rec.executability} but the backend derives "
                f"{derived['executability']} ({derived['basis']})")
        if rec.execution_path and derived["executability"] != EXECUTABLE_HERE:
            problems.append(
                f"{rec.strategy}: names execution_path {rec.execution_path} with no "
                f"resolvable backend")
        if (rec.verdict == VERDICT_RECOMMENDED
                and derived["executability"] == RECOMMEND_ONLY_NO_BACKEND
                and not (rec.executable_next_action or "").strip()):
            problems.append(
                f"{rec.strategy}: RECOMMENDED, not executable here, and names no "
                f"executable_next_action this harness can actually take")
    if problems:
        raise StrategyExecutabilityOverstatedError("; ".join(problems))


# --------------------------------------------------------------------------
# Thresholds -- project-overridable, each with its real justification
# --------------------------------------------------------------------------
STRATEGY_CONFIG_KEY = "verification_strategy"

#: Measured wall-clock simulation hours per observed day above which THROUGHPUT
#: (not stimulus quality) is treated as the binding constraint, which is the
#: textbook indication for emulation/prototyping.
#:
#: JUSTIFICATION, and why it is an overridable default rather than a constant:
#: this harness reads no farm capacity, no license pool size and no schedule,
#: so no universal number exists and inventing one would be fabricated
#: precision. What the harness DOES measure is real `jobs.runtime_seconds`
#: wall-clock summed per day by `trend_analysis.daily_rollup()`. 24 hours/day
#: is the smallest defensible bar: below one machine-day of simulation per
#: calendar day, "we are compute-bound" is not a claim this evidence supports.
#: Override per project via config.json: `verification_strategy.
#: throughput_bound_runtime_hours_per_day`.
DEFAULT_THROUGHPUT_BOUND_RUNTIME_HOURS_PER_DAY = 24.0

#: Days of real runtime evidence required before the throughput signal is
#: computed at all. One busy day is a day, not a trend -- the same
#: "2 independent observations" bar `capability_evolution.
#: REPEAT_FAILURE_MIN_OCCURRENCES`, `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS`
#: and `loop_convergence.DEFAULT_OSCILLATION_REPEAT_THRESHOLD` already use.
DEFAULT_MIN_RUNTIME_DAYS = 2

#: Distinct subsystems that must be REGISTERED (gate-validated, via a real
#: SIGNOFF PASS) before "this goal spans multiple subsystems that must be
#: coordinated" -- PSS's actual indication -- is a measured fact rather than an
#: aspiration. Two, for the same reason as above.
DEFAULT_MIN_SUBSYSTEMS_FOR_PSS = 2


def _config_block(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(cfg, dict):
        block = cfg.get(STRATEGY_CONFIG_KEY)
        if isinstance(block, dict):
            return block
    return {}


def throughput_bound_hours_per_day(cfg: Optional[Dict[str, Any]] = None) -> float:
    value = _config_block(cfg).get("throughput_bound_runtime_hours_per_day")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return DEFAULT_THROUGHPUT_BOUND_RUNTIME_HOURS_PER_DAY


def min_runtime_days(cfg: Optional[Dict[str, Any]] = None) -> int:
    value = _config_block(cfg).get("min_runtime_days")
    if isinstance(value, int) and value >= 2:
        return value
    return DEFAULT_MIN_RUNTIME_DAYS


def min_subsystems_for_pss(cfg: Optional[Dict[str, Any]] = None) -> int:
    value = _config_block(cfg).get("min_subsystems_for_pss")
    if isinstance(value, int) and value >= 2:
        return value
    return DEFAULT_MIN_SUBSYSTEMS_FOR_PSS


# --------------------------------------------------------------------------
# Signals -- gathered from the modules that already compute them
# --------------------------------------------------------------------------
@dataclass
class StrategySignals:
    """Every real fact the rules below are allowed to reason over, and the
    module each one came from.

    Every count is Optional-free but `*_available` flags are not decoration:
    "zero unreachable bins were found" and "no coverage evidence exists to look
    in" must never look the same to a rule, which is the exact defect
    `coverage_analysis.seed_history_available()` was added to prevent one layer
    down."""
    root: str = ""
    # -- coverage-closure difficulty (loop_convergence / coverage_analysis)
    coverage_evidence_available: bool = False
    convergence_verdict: str = "UNKNOWN"
    convergence_reason: str = ""
    plateau_investigated: bool = False
    under_sampled_bins: List[str] = field(default_factory=list)
    stimulus_gap_bins: List[str] = field(default_factory=list)
    unreachable_bins: List[str] = field(default_factory=list)
    unclassified_bins: List[str] = field(default_factory=list)
    plateau_recommended_action: Optional[str] = None
    oscillating: bool = False
    fix_revert_patterns: List[str] = field(default_factory=list)
    # -- failure density (capability_evolution / evidence_db)
    failure_evidence_available: bool = False
    distinct_failure_signatures: int = 0
    total_failure_occurrences: int = 0
    unresolved_repeated_signatures: List[str] = field(default_factory=list)
    # -- throughput (trend_analysis daily rollup, via the evidence db)
    runtime_evidence_days: int = 0
    total_runtime_hours: Optional[float] = None
    mean_runtime_hours_per_day: Optional[float] = None
    # -- protocol capability (protocol_capability)
    protocol: Optional[str] = None
    protocol_known: bool = False
    protocol_capability_status: Optional[str] = None
    protocol_unmodelled_layers: List[str] = field(default_factory=list)
    # -- declared scope + real subsystem registry (environment_mode_router)
    scope: str = SCOPE_UNDECLARED
    registered_subsystems: List[str] = field(default_factory=list)
    # -- provenance
    sources: Dict[str, Any] = field(default_factory=dict)
    unavailable: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _failure_density_from_evidence_db(root: Path) -> Tuple[bool, int, int, str]:
    """`(available, distinct_signatures, total_occurrences, source)` from the
    real `failure_signatures` table.

    Opened READ-ONLY, exactly as `trend_analysis.trend_report()` opens it: this
    module must never create an evidence database that does not exist, migrate
    one that does, or block a concurrently-running `lsf-watch` writer. A
    missing database is reported unavailable, never as "0 failures" -- which a
    rule would read as a clean design."""
    try:
        from . import evidence_db as _evidence_db
    except Exception as exc:  # pragma: no cover - import guard
        return False, 0, 0, f"evidence_db unavailable: {exc}"
    path = _evidence_db.default_db_path(root)
    if not path.exists():
        return False, 0, 0, f"{path} does not exist"
    try:
        store = _evidence_db.EvidenceStore(path, read_only=True)
    except Exception as exc:
        return False, 0, 0, f"{path}: {type(exc).__name__}: {exc}"
    try:
        rows = store.query(
            "SELECT count(*), coalesce(sum(occurrence_count), 0) FROM failure_signatures")
    except Exception as exc:  # pragma: no cover - schema older than the table
        return False, 0, 0, f"{path}: {type(exc).__name__}: {exc}"
    finally:
        store.close()
    distinct, total = (int(rows[0][0] or 0), int(rows[0][1] or 0)) if rows else (0, 0)
    return True, distinct, total, str(path)


def gather_signals(root, *,
                   cfg: Optional[Dict[str, Any]] = None,
                   scope: str = SCOPE_UNDECLARED,
                   protocol: Optional[str] = None,
                   holes: Optional[List[Dict[str, Any]]] = None,
                   convergence: Optional[Dict[str, Any]] = None,
                   daily: Optional[List[Dict[str, Any]]] = None,
                   db_path=None) -> StrategySignals:
    """Read every signal from the module that owns it. Writes nothing.

    `convergence` and `daily` let a caller (and the tests) hand in the
    `loop_convergence.classify_loop_convergence()` report and the
    `trend_analysis.daily_rollup()` rows it already has, instead of this
    function re-reading the same evidence database twice more and risking two
    halves of one answer describing different runs -- the same reason
    `classify_loop_convergence()` itself accepts `points`.
    """
    root = Path(root)
    sig = StrategySignals(root=str(root), scope=scope if scope in SCOPES else SCOPE_UNDECLARED)

    # ---- coverage-closure difficulty -------------------------------------
    if convergence is None:
        from . import loop_convergence as _lc
        convergence = _lc.classify_loop_convergence(
            root, cfg=cfg, holes=holes, db_path=db_path).to_dict()
    sig.sources["convergence"] = "loop_convergence.classify_loop_convergence()"
    sig.coverage_evidence_available = bool(convergence.get("available"))
    sig.convergence_verdict = str(convergence.get("verdict") or "UNKNOWN")
    sig.convergence_reason = str(convergence.get("reason") or "")
    if not sig.coverage_evidence_available:
        sig.unavailable.append(
            f"NO_COVERAGE_SERIES: {sig.convergence_reason or 'no usable coverage series'}")
    investigation = convergence.get("plateau_investigation")
    if isinstance(investigation, dict):
        sig.plateau_investigated = True
        sig.under_sampled_bins = list(investigation.get("under_sampled_candidates") or [])
        sig.stimulus_gap_bins = list(investigation.get("stimulus_gap_candidates") or [])
        sig.unreachable_bins = list(investigation.get("unreachable_candidates") or [])
        sig.unclassified_bins = list(investigation.get("unclassified") or [])
        sig.plateau_recommended_action = investigation.get("recommended_action")
        sig.sources["plateau_investigation"] = (
            "loop_convergence.investigate_plateau() over "
            "coverage_analysis.classify_coverage_hole()")
    osc = convergence.get("oscillation") or {}
    sig.oscillating = bool(osc.get("oscillating"))
    sig.fix_revert_patterns = [
        str(o.get("pattern")) for o in (osc.get("repeat_fix_revert") or [])
        if isinstance(o, dict) and o.get("pattern")]

    # ---- failure density --------------------------------------------------
    available, distinct, total, source = _failure_density_from_evidence_db(root)
    sig.failure_evidence_available = available
    sig.distinct_failure_signatures = distinct
    sig.total_failure_occurrences = total
    sig.sources["failure_signatures"] = source
    if not available:
        sig.unavailable.append(f"NO_FAILURE_SIGNATURE_EVIDENCE: {source}")
    from .cross_project_mining import has_memory_store
    if not has_memory_store(root):
        # Checked BEFORE calling into capability_evolution, whose
        # repeated_unresolved_failure_patterns() constructs a MemoryStore
        # unconditionally -- that constructor mkdir()s the 5-tier tree and
        # writes an empty index.json. A pure recommend() must never bring a
        # memory store into existence just by asking whether one exists
        # (the same guard confidence_calibration.calibrate() and
        # cross_project_mining already use for exactly this reason).
        sig.unavailable.append("NO_JOB_MEMORY_FAILURE_HISTORY: no memory store on disk")
    else:
        try:
            from . import capability_evolution as _ce
            patterns = _ce.repeated_unresolved_failure_patterns(root)
            sig.unresolved_repeated_signatures = [
                str(p.get("signature_key")) for p in patterns if p.get("signature_key")]
            sig.sources["unresolved_repeated_signatures"] = (
                "capability_evolution.repeated_unresolved_failure_patterns()")
        except Exception as exc:
            sig.unavailable.append(
                f"NO_JOB_MEMORY_FAILURE_HISTORY: {type(exc).__name__}: {exc}")

    # ---- throughput -------------------------------------------------------
    if daily is None:
        daily = _daily_rollup_rows(root, db_path=db_path)
    if daily:
        hours = [d.get("total_runtime_hours") for d in daily
                 if isinstance(d, dict) and isinstance(d.get("total_runtime_hours"), (int, float))]
        sig.runtime_evidence_days = len(hours)
        if hours:
            sig.total_runtime_hours = round(sum(hours), 6)
            sig.mean_runtime_hours_per_day = round(sum(hours) / len(hours), 6)
        sig.sources["runtime"] = "trend_analysis.daily_rollup() -> jobs.runtime_seconds"
    if not sig.runtime_evidence_days:
        sig.unavailable.append("NO_RUNTIME_EVIDENCE: no day carries measured job runtime")

    # ---- protocol capability ---------------------------------------------
    if protocol:
        from . import protocol_capability as _pc
        sig.protocol = protocol
        cap = _pc.capability_for(protocol)
        sig.sources["protocol_capability"] = "protocol_capability.capability_for()"
        if cap is None:
            sig.protocol_known = False
            sig.unavailable.append(
                f"UNKNOWN_PROTOCOL: {protocol!r} is not in protocol_capability."
                f"PROTOCOL_CAPABILITIES ({list(_pc.known_protocols())})")
        else:
            sig.protocol_known = True
            sig.protocol_capability_status = _pc.derive_status(cap)
            sig.protocol_unmodelled_layers = list(
                cap.model.does_not_model if cap.model else ())

    # ---- declared scope + real subsystem registry -------------------------
    try:
        from .environment_mode_router import read_registered_subsystem_entries
        sig.registered_subsystems = [
            str(e.get("name")) for e in read_registered_subsystem_entries(root)
            if e.get("name")]
        sig.sources["subsystems"] = (
            "environment_mode_router.read_registered_subsystem_entries()")
    except Exception as exc:  # pragma: no cover - import guard
        sig.unavailable.append(f"NO_SUBSYSTEM_REGISTRY: {type(exc).__name__}: {exc}")
    return sig


def _daily_rollup_rows(root: Path, *, db_path=None) -> List[Dict[str, Any]]:
    """`trend_analysis.daily_rollup()` rows, read READ-ONLY, or [] when this
    project has no evidence database. Never creates or migrates one."""
    try:
        from . import evidence_db as _evidence_db
        from . import trend_analysis as _ta
    except Exception:  # pragma: no cover - import guard
        return []
    path = Path(db_path) if db_path else _evidence_db.default_db_path(root)
    if not Path(path).exists():
        return []
    try:
        store = _evidence_db.EvidenceStore(path, read_only=True)
    except Exception:
        return []
    try:
        return [p.to_dict() for p in _ta.daily_rollup(store)]
    except Exception:  # pragma: no cover
        return []
    finally:
        store.close()


# --------------------------------------------------------------------------
# The recommendation
# --------------------------------------------------------------------------
@dataclass
class StrategyRecommendation:
    """One strategy's answer, on BOTH axes, with the basis for each.

    `verdict` is what the signals say. `executability` is what this harness can
    do. They are never merged, and `executable_next_action` is what makes a
    RECOMMENDED-but-not-executable row actionable rather than decorative."""
    strategy: str
    verdict: str
    executability: str
    basis: List[str] = field(default_factory=list)
    rules_fired: List[str] = field(default_factory=list)
    execution_path: Optional[List[str]] = None
    what_it_would_run: str = ""
    no_backend_reason: str = ""
    executable_next_action: str = ""
    next_action_owner: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyReport:
    root: str
    goal_text: str = ""
    #: Always False. `goal_text` is recorded verbatim and never parsed into a
    #: verdict -- the same contract `capability_evolution` puts on
    #: `acceptance_criteria_machine_evaluated`.
    goal_text_machine_evaluated: bool = False
    scope: str = SCOPE_UNDECLARED
    protocol: Optional[str] = None
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    recommended_strategies: List[str] = field(default_factory=list)
    executable_here: List[str] = field(default_factory=list)
    recommend_only: List[str] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)
    disclosure: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


#: Printed on every report, whatever it recommends. Not a footnote: the report
#: is the surface an agent or a human reads, and the one thing it must never
#: leave ambiguous is which half of its own output this harness could act on.
REPORT_DISCLOSURE = (
    "This harness can EXECUTE simulation only (VCS regression via "
    "lsf_client.bsub_submit_with_preflight behind preflight.run_preflight). "
    "FORMAL / PSS / EMULATION / FPGA_PROTOTYPE are RECOMMEND_ONLY: no such "
    "backend exists anywhere in this repository, so a recommendation for one "
    "is engineering advice for a human to act on with tools this harness does "
    "not have -- never a capability it can invoke. Every executability value "
    "here is derived from the import system at report time, not declared."
)

#: The real escalation paths this module NAMES and takes for none of them --
#: the same contract `loop_convergence.PlateauInvestigation.escalator` has.
ESCALATOR_QUESTION_QUEUE = "coverage_analysis.escalate_unreachable_holes()"
ESCALATOR_CAPABILITY_CANDIDATE = "capability_evolution.file_repeated_failure_candidate()"
ESCALATOR_TOOL_DECISION = ("question_queue.QuestionQueueStore.add_question() "
                           "(Tier 3, tool-budget owner)")


#: What each named escalator must really resolve to, so a renamed function
#: fails a check instead of leaving a dead name in a recommendation a human is
#: being asked to act on. Same real import+getattr resolution
#: `derive_executability()` uses for the backends.
_ESCALATOR_ENTRY_POINTS: Tuple[str, ...] = (
    "dv_harness.coverage_analysis:escalate_unreachable_holes",
    "dv_harness.capability_evolution:file_repeated_failure_candidate",
    "dv_harness.question_queue:QuestionQueueStore",
)


def assert_named_escalators_resolve() -> None:
    """Every escalation path this module NAMES must really exist.

    A recommendation whose only actionable content is "call X" is worth exactly
    as much as X being real. This module does not take these paths -- which is
    precisely why nothing else would catch it if one were renamed away."""
    unresolved = [reason for entry in _ESCALATOR_ENTRY_POINTS
                  for ok, reason in [_resolve_entry_point(entry)] if not ok]
    if unresolved:
        raise StrategyExecutabilityOverstatedError(
            "named escalator does not resolve: " + "; ".join(unresolved))


def _sim_next_action(signals: StrategySignals) -> Tuple[str, str]:
    """The real simulation action the plateau investigation already computed,
    reused verbatim rather than re-derived here."""
    if signals.plateau_recommended_action:
        return signals.plateau_recommended_action, "dv-harness loop-contract convergence"
    return "", ""


def recommend_strategies(root, *,
                         goal_text: str = "",
                         scope: str = SCOPE_UNDECLARED,
                         protocol: Optional[str] = None,
                         holes: Optional[List[Dict[str, Any]]] = None,
                         cfg: Optional[Dict[str, Any]] = None,
                         signals: Optional[StrategySignals] = None,
                         convergence: Optional[Dict[str, Any]] = None,
                         daily: Optional[List[Dict[str, Any]]] = None,
                         db_path=None) -> StrategyReport:
    """The optimizer. Returns one `StrategyRecommendation` per strategy --
    never a single pick, and never a silently omitted strategy: a strategy this
    project has no signal for says so.

    PRECEDENCE, and why it is this way round: it is
    `loop_convergence.investigate_plateau()`'s per-bin precedence lifted one
    level, for the same reason. A bin randomization has not fairly attempted
    cannot support ANY structural conclusion -- so while under-sampled bins
    exist, FORMAL is `SUPPRESSED`, not merely unrecommended. Recommending an
    engine this harness cannot even run, on the strength of bins nobody has
    run yet, would be the most expensive possible wrong answer.
    """
    assert_no_verification_verdict_vocabulary()
    assert_named_escalators_resolve()
    root = Path(root)
    if signals is None:
        signals = gather_signals(root, cfg=cfg, scope=scope, protocol=protocol,
                                 holes=holes, convergence=convergence, daily=daily,
                                 db_path=db_path)

    recs: Dict[str, StrategyRecommendation] = {}
    for strategy in STRATEGIES:
        derived = derive_executability(strategy)
        recs[strategy] = StrategyRecommendation(
            strategy=strategy,
            verdict=VERDICT_NO_SIGNAL,
            executability=derived["executability"],
            execution_path=derived["execution_path"],
            what_it_would_run=derived["what_it_would_run"],
            no_backend_reason=derived["absent_note"] if derived["execution_path"] is None else "",
        )

    def fire(strategy: str, rule: str, basis: str, verdict: str,
             next_action: str = "", owner: str = "") -> None:
        rec = recs[strategy]
        # A SUPPRESSED verdict is terminal for this report: it means a cheaper,
        # strictly-prerequisite move exists, and a later rule must not talk
        # over it.
        if rec.verdict == VERDICT_SUPPRESSED and verdict != VERDICT_SUPPRESSED:
            rec.basis.append(f"{rule}: {basis} (not acted on -- suppressed)")
            rec.rules_fired.append(rule)
            return
        rec.rules_fired.append(rule)
        rec.basis.append(f"{rule}: {basis}")
        if verdict == VERDICT_RECOMMENDED and rec.verdict in (
                VERDICT_NO_SIGNAL, VERDICT_NOT_INDICATED, VERDICT_RECOMMENDED):
            rec.verdict = VERDICT_RECOMMENDED
        elif verdict == VERDICT_SUPPRESSED:
            rec.verdict = VERDICT_SUPPRESSED
        elif verdict == VERDICT_NOT_INDICATED and rec.verdict == VERDICT_NO_SIGNAL:
            rec.verdict = VERDICT_NOT_INDICATED
        if next_action and not rec.executable_next_action:
            rec.executable_next_action = next_action
            rec.next_action_owner = owner

    # ---- R1: under-sampled bins -- seeds first, and formal is SUPPRESSED ---
    under_sampled = bool(signals.under_sampled_bins)
    if under_sampled:
        action, owner = _sim_next_action(signals)
        fire(STRATEGY_SIMULATION, "R1_UNDER_SAMPLED_BINS",
             f"{len(signals.under_sampled_bins)} coverage bin(s) have not had a fair "
             f"randomization attempt ({signals.under_sampled_bins}); more seeds is the "
             f"cheapest move and this harness can run it",
             VERDICT_RECOMMENDED, action or "ADD_SEEDS_AND_RERUN", owner or "dv-harness")
        fire(STRATEGY_FORMAL, "R1_UNDER_SAMPLED_BINS",
             "a bin randomization has not fairly attempted cannot support a structural "
             "unreachability claim, so no formal recommendation is supportable until "
             "those bins have been sampled (loop_convergence.PLATEAU_PREMATURE_UNDER_SAMPLED)",
             VERDICT_SUPPRESSED)

    # ---- R2: stimulus-gap bins -- simulation work, no human decision ------
    if signals.stimulus_gap_bins:
        action, owner = _sim_next_action(signals)
        fire(STRATEGY_SIMULATION, "R2_STIMULUS_GAP_BINS",
             f"{len(signals.stimulus_gap_bins)} bin(s) are a real stimulus gap "
             f"({signals.stimulus_gap_bins}) -- a missing test or a constraint that never "
             f"reaches them; that is simulation work, not an engine change",
             VERDICT_RECOMMENDED, action or "GENERATE_TESTCASE_AND_RERUN", owner or "dv-harness")

    # ---- R3: adequately-sampled unreachable bins -- the formal indication --
    if signals.unreachable_bins and not under_sampled:
        fire(STRATEGY_FORMAL, "R3_UNREACHABLE_AFTER_FAIR_SAMPLING",
             f"{len(signals.unreachable_bins)} adequately-sampled bin(s) "
             f"({signals.unreachable_bins}) are claimed structurally unreachable. Writing "
             f"another testcase provably cannot settle that; an exhaustive proof is the "
             f"class of tool that can -- and this harness has none",
             VERDICT_RECOMMENDED,
             f"escalate the bins to the question queue via {ESCALATOR_QUESTION_QUEUE} "
             f"(Tier 3, designer-owned) -- the one act this harness CAN take on them",
             "designer")
        fire(STRATEGY_SIMULATION, "R3_UNREACHABLE_AFTER_FAIR_SAMPLING",
             "these bins are adequately sampled, so more simulation of the same stimulus "
             "is not indicated for them",
             VERDICT_NOT_INDICATED)
    elif signals.unreachable_bins and under_sampled:
        pass  # R1 already recorded the suppression and its reason.
    elif signals.plateau_investigated:
        fire(STRATEGY_FORMAL, "R3_UNREACHABLE_AFTER_FAIR_SAMPLING",
             "the plateau investigation found no adequately-sampled unreachable bin",
             VERDICT_NOT_INDICATED)

    # ---- R4: the loop keeps re-breaking the same thing ---------------------
    if signals.oscillating or signals.unresolved_repeated_signatures:
        detail = []
        if signals.fix_revert_patterns:
            detail.append(f"fix-revert cycles on {signals.fix_revert_patterns}")
        if signals.unresolved_repeated_signatures:
            detail.append(f"{len(signals.unresolved_repeated_signatures)} failure "
                          f"signature(s) recurring across independent runs with no "
                          f"verified_fix closing them")
        fire(STRATEGY_FORMAL, "R4_UNRESOLVED_RECURRING_FAILURE",
             "; ".join(detail) + " -- a property the loop keeps fixing and re-breaking is "
             "the classic case for proving it rather than re-sampling it",
             VERDICT_RECOMMENDED,
             f"file the recurring pattern as a capability candidate via "
             f"{ESCALATOR_CAPABILITY_CANDIDATE}; the proof itself needs a tool this "
             f"harness does not have",
             "verification-lead")
    elif signals.failure_evidence_available:
        fire(STRATEGY_FORMAL, "R4_UNRESOLVED_RECURRING_FAILURE",
             f"{signals.distinct_failure_signatures} distinct failure signature(s) recorded, "
             f"none recurring unresolved across independent runs",
             VERDICT_NOT_INDICATED)

    # ---- R5: throughput -- the emulation / prototyping indication ---------
    days = min_runtime_days(cfg)
    bound = throughput_bound_hours_per_day(cfg)
    # The two verdicts under which "throughput is the binding constraint"
    # cannot be claimed, named from loop_convergence's OWN vocabulary rather
    # than re-spelt here: a curve that is still climbing is not blocked on
    # compute, and UNKNOWN means there was no series to judge.
    from .loop_convergence import CONVERGING as _CONVERGING, UNKNOWN as _UNKNOWN
    coverage_open = signals.convergence_verdict not in (_CONVERGING, _UNKNOWN)
    for strategy in (STRATEGY_EMULATION, STRATEGY_FPGA_PROTOTYPE):
        if signals.runtime_evidence_days < days:
            fire(strategy, "R5_THROUGHPUT_BOUND",
                 f"only {signals.runtime_evidence_days} day(s) of measured job runtime "
                 f"(minimum {days}) -- INSUFFICIENT_RUNTIME_EVIDENCE, so whether throughput "
                 f"binds is not a question this evidence can answer",
                 VERDICT_NO_SIGNAL)
        elif (signals.mean_runtime_hours_per_day or 0.0) >= bound and coverage_open:
            fire(strategy, "R5_THROUGHPUT_BOUND",
                 f"{signals.mean_runtime_hours_per_day}h of measured simulation per day over "
                 f"{signals.runtime_evidence_days} days (>= {bound}h) while coverage is "
                 f"{signals.convergence_verdict} -- throughput, not stimulus quality, is the "
                 f"binding constraint",
                 VERDICT_RECOMMENDED,
                 f"this harness cannot run it; record the tool decision as a Tier-3 question "
                 f"via {ESCALATOR_TOOL_DECISION}",
                 "tool-budget owner")
        else:
            fire(strategy, "R5_THROUGHPUT_BOUND",
                 f"{signals.mean_runtime_hours_per_day}h of measured simulation per day over "
                 f"{signals.runtime_evidence_days} days (bound {bound}h), coverage "
                 f"{signals.convergence_verdict} -- simulation throughput is not the binding "
                 f"constraint",
                 VERDICT_NOT_INDICATED)

    # ---- R6: multi-subsystem coordination -- the PSS indication -----------
    min_subs = min_subsystems_for_pss(cfg)
    subs = signals.registered_subsystems
    if signals.scope == SCOPE_SYSTEM and len(subs) >= min_subs:
        fire(STRATEGY_PSS, "R6_MULTI_SUBSYSTEM_SCOPE",
             f"declared scope is {SCOPE_SYSTEM} and {len(subs)} subsystems are REGISTERED "
             f"({subs}) -- coordinating one scenario across independently-verified "
             f"subsystems is what portable stimulus is for",
             VERDICT_RECOMMENDED,
             f"this harness cannot run it; record the tool decision as a Tier-3 question "
             f"via {ESCALATOR_TOOL_DECISION}",
             "tool-budget owner")
    elif signals.scope == SCOPE_UNDECLARED:
        fire(STRATEGY_PSS, "R6_MULTI_SUBSYSTEM_SCOPE",
             f"no verification scope was declared, and this module does not infer one from "
             f"goal text -- PSS's indication is a multi-subsystem SCOPE, which is a caller "
             f"fact, not a measurement ({len(subs)} subsystem(s) registered)",
             VERDICT_NO_SIGNAL)
    else:
        fire(STRATEGY_PSS, "R6_MULTI_SUBSYSTEM_SCOPE",
             f"scope {signals.scope} with {len(subs)} registered subsystem(s) (minimum "
             f"{min_subs} at {SCOPE_SYSTEM} scope) -- no multi-subsystem coordination to "
             f"model",
             VERDICT_NOT_INDICATED)

    # ---- R7: the protocol's own modelling ceiling -------------------------
    if signals.protocol and signals.protocol_known:
        from . import protocol_capability as _pc
        if signals.protocol_capability_status == _pc.STATUS_GENERIC_SKELETON_ONLY:
            fire(STRATEGY_SIMULATION, "R7_PROTOCOL_MODEL_CEILING",
                 f"{signals.protocol} is {signals.protocol_capability_status}: this harness "
                 f"generates only the protocol-agnostic skeleton for it, so simulating "
                 f"protocol-specific behaviour needs a protocol model built FIRST -- an "
                 f"engine change would not help",
                 VERDICT_RECOMMENDED,
                 "build the protocol model behind protocol_capability.PROTOCOL_CAPABILITIES "
                 "before choosing any engine",
                 "harness owner")
        elif signals.protocol_unmodelled_layers:
            # A CAVEAT, deliberately not a verdict. Whether THIS goal touches
            # one of the unmodelled layers is a caller fact, and this module
            # does not parse goal text into verdicts -- so it records the
            # ceiling and leaves the judgement to the reader rather than
            # downgrading simulation on a guess.
            fire(STRATEGY_SIMULATION, "R7_PROTOCOL_MODEL_CEILING",
                 f"CAVEAT -- {signals.protocol} is {signals.protocol_capability_status}; its "
                 f"model explicitly does not model {signals.protocol_unmodelled_layers}. A goal "
                 f"about those layers is outside what this harness can currently stimulate; "
                 f"whether this goal is one is not machine-evaluated",
                 VERDICT_NO_SIGNAL)
        else:
            fire(STRATEGY_SIMULATION, "R7_PROTOCOL_MODEL_CEILING",
                 f"{signals.protocol} is {signals.protocol_capability_status} with no declared "
                 f"unmodelled layer -- no modelling ceiling stands in the way",
                 VERDICT_NO_SIGNAL)

    # ---- R8: the honest default -------------------------------------------
    # Simulation is this harness's one executable engine, so "we have no signal
    # either way" must still leave a caller with the engine they already have,
    # LABELLED as a default rather than as a finding.
    sim = recs[STRATEGY_SIMULATION]
    if sim.verdict == VERDICT_NO_SIGNAL:
        fire(STRATEGY_SIMULATION, "R8_NO_SIGNAL_DEFAULT",
             "no coverage-closure, failure-density or protocol signal indicated a change of "
             "engine; simulation is this harness's one executable engine and stays the "
             "default -- this is a default, not a measurement"
             + (f" (unavailable: {signals.unavailable})" if signals.unavailable else ""),
             VERDICT_RECOMMENDED,
             "continue the existing regression loop", "dv-harness")

    # ---- R9: no rule reached this strategy at all --------------------------
    # A row with an empty basis is the silent omission this report structurally
    # refuses: "we looked and found nothing" and "nothing looked" must never
    # render the same. So a strategy no rule reached says so, and names what
    # was missing.
    for strategy in STRATEGIES:
        rec = recs[strategy]
        if rec.basis:
            continue
        fire(strategy, "R9_NO_RULE_REACHED_THIS_STRATEGY",
             "no rule had the evidence to reach a view on this strategy"
             + (f" (unavailable: {signals.unavailable})" if signals.unavailable
                else " (every signal was available and none indicated it)"),
             VERDICT_NO_SIGNAL)

    ordered = [recs[s] for s in STRATEGIES]
    assert_no_unexecutable_strategy_claimed_executable(ordered)

    return StrategyReport(
        root=str(root),
        goal_text=goal_text,
        goal_text_machine_evaluated=False,
        scope=signals.scope,
        protocol=signals.protocol,
        recommendations=[r.to_dict() for r in ordered],
        recommended_strategies=[r.strategy for r in ordered if r.verdict == VERDICT_RECOMMENDED],
        executable_here=[r.strategy for r in ordered if r.executability == EXECUTABLE_HERE],
        recommend_only=[r.strategy for r in ordered
                        if r.executability == RECOMMEND_ONLY_NO_BACKEND],
        signals=signals.to_dict(),
        disclosure=REPORT_DISCLOSURE,
    )


# --------------------------------------------------------------------------
# Rendering + front door
# --------------------------------------------------------------------------
def render_strategy_report_text(report: Dict[str, Any]) -> str:
    lines = [f"DV Agent Harness L5 -- verification strategy ({report.get('root')})", ""]
    if report.get("goal_text"):
        lines += [f"GOAL (recorded verbatim, never parsed): {report['goal_text']}",
                  f"  goal_text_machine_evaluated: {report.get('goal_text_machine_evaluated')}",
                  ""]
    lines.append(f"SCOPE {report.get('scope')}"
                 + (f"   PROTOCOL {report['protocol']}" if report.get("protocol") else ""))
    lines.append("")
    lines.append(f"{'STRATEGY':<16}{'VERDICT':<16}{'THIS HARNESS':<26}")
    lines.append("-" * 58)
    for rec in report.get("recommendations", []):
        lines.append(f"{rec['strategy']:<16}{rec['verdict']:<16}{rec['executability']:<26}")
    for rec in report.get("recommendations", []):
        lines += ["", f"{rec['strategy']} -- {rec['verdict']} / {rec['executability']}"]
        if rec.get("execution_path"):
            lines.append(f"  executes via : {', '.join(rec['execution_path'])}")
        else:
            lines.append(f"  would run    : {rec.get('what_it_would_run')}")
            if rec.get("no_backend_reason"):
                lines.append(f"  no backend   : {rec['no_backend_reason']}")
        for b in rec.get("basis", []):
            lines.append(f"  basis        : {b}")
        if rec.get("executable_next_action"):
            lines.append(f"  next action  : {rec['executable_next_action']}"
                         + (f"  [owner: {rec['next_action_owner']}]"
                            if rec.get("next_action_owner") else ""))
    signals = report.get("signals") or {}
    if signals.get("unavailable"):
        lines += ["", "SIGNALS NOT AVAILABLE"]
        lines += [f"  - {u}" for u in signals["unavailable"]]
    lines += ["", "SIGNAL SOURCES"]
    for k, v in sorted((signals.get("sources") or {}).items()):
        lines.append(f"  {k:<28} {v}")
    lines += ["", report.get("disclosure", "")]
    return "\n".join(lines)


def execute_verb(root, verb: str, *,
                 cfg: Optional[Dict[str, Any]] = None,
                 goal: str = "",
                 scope: str = SCOPE_UNDECLARED,
                 protocol: Optional[str] = None,
                 holes_path: Optional[str] = None) -> tuple:
    """`(exit_code, payload, text)`. One implementation, shared by
    `dv-harness verification-strategy` and
    `python -m dv_harness.verification_strategy` -- two handlers over one
    behaviour is the parallel-mechanism defect this project forbids, at CLI
    scale.

    Exit codes: 0 for a completed report (whatever it recommends -- NO_SIGNAL
    is an honest answer about the evidence, not a failure of the command),
    1 for a bad invocation, 2 when this report recommends a strategy this
    harness CANNOT execute, which is a CI-visible "a human has to decide
    something" signal and never an approval in either direction.
    """
    root = Path(root)
    if verb == "capabilities":
        assert_executability_matches_code()
        payload = {"strategies": executability_rows(), "disclosure": REPORT_DISCLOSURE}
        text = "\n".join(
            [f"{r['strategy']:<16}{r['executability']:<26}"
             f"{(', '.join(r['execution_path']) if r['execution_path'] else r['absent_note'])}"
             for r in payload["strategies"]] + ["", REPORT_DISCLOSURE])
        return 0, payload, text

    if verb != "recommend":
        return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
                   "known": ["recommend", "capabilities"]}, ""

    if scope not in SCOPES:
        return 1, {"ok": False, "error": "UNKNOWN_SCOPE", "scope": scope,
                   "known": list(SCOPES)}, ""

    holes: Optional[List[Dict[str, Any]]] = None
    if holes_path:
        p = Path(holes_path)
        if not p.exists():
            return 1, {"ok": False, "error": "HOLES_FILE_NOT_FOUND", "path": str(p)}, ""
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            return 1, {"ok": False, "error": "HOLES_FILE_UNPARSEABLE",
                       "path": str(p), "detail": str(exc)}, ""
        holes = loaded.get("holes") if isinstance(loaded, dict) else loaded
        if not isinstance(holes, list):
            return 1, {"ok": False, "error": "HOLES_FILE_SHAPE",
                       "expected": "a JSON list of holes, or {\"holes\": [...]}"}, ""

    report = recommend_strategies(root, goal_text=goal, scope=scope, protocol=protocol,
                                  holes=holes, cfg=cfg).to_dict()
    code = 2 if any(r["verdict"] == VERDICT_RECOMMENDED
                    and r["executability"] == RECOMMEND_ONLY_NO_BACKEND
                    for r in report["recommendations"]) else 0
    return code, report, render_strategy_report_text(report)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.verification_strategy",
        description="VI-4 verification strategy optimizer (read-only).")
    ap.add_argument("verb", choices=["recommend", "capabilities"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--goal", default="")
    ap.add_argument("--scope", default=SCOPE_UNDECLARED, choices=list(SCOPES))
    ap.add_argument("--protocol", default=None)
    ap.add_argument("--holes", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    code, payload, text = execute_verb(
        Path(args.project_root), args.verb, goal=args.goal, scope=args.scope,
        protocol=args.protocol, holes_path=args.holes)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json or not text else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
