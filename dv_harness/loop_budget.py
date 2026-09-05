"""Unified loop budget engine, failure-type taxonomy and circuit breaker
(LOOP_ENGINEERING sections 91 / 92 / 93).

WHAT WAS ACTUALLY MISSING, RE-VERIFIED BEFORE THIS FILE WAS WRITTEN
-------------------------------------------------------------------
A repo-wide grep on 2026-09-05 returned ZERO hits for `circuit_breaker` /
`CircuitBreaker` anywhere, and exactly ONE hit for `TRANSIENT` -- an unrelated
sentence in `connectivity.py`'s Gate-3 docstring. Real budgets existed and were
being spent (`policy.max_stage_retries` in `engine.loop()`,
`policy.inner_react_max_iterations` / `inner_react_max_adapter_calls` in
`react_loop.InnerReactLoop`, `context_budget.MAX_PACK_BYTES` for the resident
pack) but each lived alone: nothing could answer "what has this RUN spent, on
which dimension, against which limit, and has any of it run out". And nothing
classified WHY a stage failed, so `loop()`'s retry decision was
`ss["attempts"] <= max_retry` and nothing else -- a deterministic compile error
and a dropped API connection were retried identically.

THREE THINGS, ONE MODULE, BECAUSE THEY ARE ONE MECHANISM
---------------------------------------------------------
Section 93's circuit breaker trips on section 91's budget exhaustion, and
decides retry-vs-stop from section 93's own failure taxonomy, which section 92's
resource-pressure signal also feeds (a LICENSE failure is not the kind of
failure you retry, it is the kind you defer for). Splitting them across three
modules would put the trip condition in one file and the thing it trips in
another.

REUSE, NOT PARALLEL INFRASTRUCTURE -- every input names its real producer
-------------------------------------------------------------------------
  * The LIMITS are read from the budgets this harness already has
    (`policy.max_stage_retries`, `policy.inner_react_max_iterations`,
    `policy.inner_react_max_adapter_calls`, `context_budget.MAX_PACK_BYTES`),
    never retyped. `build_engine()` records the real config key each limit came
    from, or -- for a dimension nothing in this harness bounds -- the honest
    reason nothing does, the same `budget_sources` honesty contract
    `loop_contract.validate_contract()` already enforces on a `LoopContract`.
  * The EXHAUSTION VOCABULARY is `loop_contract.LoopState.BUDGET_EXHAUSTED`,
    imported, never a second name for the same state.
  * The FAILURE TRIAGE CATEGORIES map from
    `sim_log_analysis.TRIAGE_CATEGORIES` -- whose own docstring invites exactly
    this ("a caller that classifies something OTHER than a log line can route
    its own findings into this triage vocabulary instead of inventing a second
    one") -- and from `tools/senior_dv/failure_attribution.py`'s existing
    TB_BUG/DUT_BUG/UNKNOWN classification, recomputed the same way
    `dashboard._failure_attribution()` recomputes it.
  * The RESOURCE-PRESSURE EVIDENCE is `preflight.check_license()` /
    `check_queue_health()`'s own `CheckOutcome`s, reached through
    `degradation.probe_resources()` -- the one function that already runs those
    two with the monitor's (not the gate's) `require_license_configured` rule.
    No second license check exists here.
  * The OSCILLATION verdict is
    `loop_contract.detect_oscillation_from_debug_loop_history()`, CALLED.

WHAT THIS MODULE DOES NOT DO
-----------------------------
  * It weakens no human-approval gate. `ControlPlane.approve()`,
    `policy.can_signoff()`, `capability_evolution.assert_human_approval()`,
    `HumanApprovalRequiredError` and `ProductionWriteNotAuthorizedError` are
    untouched and uncalled from here. Everything this module can do is STOP
    work; nothing here authorizes any.
  * It mints no `models.Status` and no verification verdict. A
    `FailureType` is a statement about why an attempt failed, never about
    whether the DUT is correct.
  * It never probes a license server or a scheduler by itself: every resource
    reading arrives through an injected `preflight.Runner`, exactly as
    `degradation.evaluate()` requires one.
  * It never silently resets a budget. `reset()` REQUIRES a reason and a
    `by`, appends an append-only ledger entry, and leaves the previous spend
    recorded -- section 91's "budget exhaustion is explicit and cannot silently
    reset", enforced rather than described.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .loop_contract import LoopState

LEDGER_FILENAME = "loop_budget.json"
LEDGER_SCHEMA_VERSION = "1.0"


# ==========================================================================
# Section 93: the failure-type taxonomy
# ==========================================================================
class FailureType(str, Enum):
    """Section 93's ten failure classes, verbatim and complete.

    A separate vocabulary from `models.Status` for the same reason
    `loop_contract.LoopState` is: `Status` answers "what did this stage's gate
    conclude", this answers "what KIND of thing went wrong", and a stage can be
    `FAIL` for any of these ten reasons.
    """
    TRANSIENT = "TRANSIENT"
    DETERMINISTIC = "DETERMINISTIC"
    RESOURCE = "RESOURCE"
    LICENSE = "LICENSE"
    ENVIRONMENT = "ENVIRONMENT"
    TEST = "TEST"
    DUT = "DUT"
    VIP = "VIP"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


FAILURE_TYPE_VALUES: Tuple[str, ...] = tuple(t.value for t in FailureType)

#: Whether repeating the SAME action is, on this failure type's own evidence, a
#: useful thing to do -- section 93's "Retry only when evidence supports it".
#:
#: UNKNOWN is retryable ON PURPOSE. It is what an unclassified failure gets, and
#: refusing to retry a failure nobody understood yet would silently shrink every
#: existing project's retry budget on the strength of this module's ignorance.
#: The conservative direction for an unclassified failure is the behaviour that
#: already exists.
#:
#: LICENSE / RESOURCE / INFRASTRUCTURE are retryable because the condition is
#: genuinely expected to clear on its own (a checked-out license is returned, a
#: PEND-ing queue drains) -- but they are the failure types section 92's
#: deferral applies to, i.e. "retry LATER", which is why they are also the ones
#: `resource_pressure()` reads.
RETRYABLE_FAILURE_TYPES: Dict[str, bool] = {
    FailureType.TRANSIENT.value: True,
    FailureType.DETERMINISTIC.value: False,
    FailureType.RESOURCE.value: True,
    FailureType.LICENSE.value: True,
    FailureType.ENVIRONMENT.value: False,
    FailureType.TEST.value: False,
    FailureType.DUT.value: False,
    FailureType.VIP.value: False,
    FailureType.INFRASTRUCTURE.value: True,
    FailureType.UNKNOWN.value: True,
}


def assert_retry_policy_total() -> None:
    """Every `FailureType` member must have a decided retry meaning. Called by
    the tests, so a new member added without deciding whether retrying it helps
    fails a test rather than falling through to a default nobody chose."""
    missing = [t.value for t in FailureType if t.value not in RETRYABLE_FAILURE_TYPES]
    if missing:
        raise AssertionError(
            f"FailureType members with no retry decision: {missing}. "
            f"Add them to RETRYABLE_FAILURE_TYPES (and say why in its comment).")
    unknown = [k for k in RETRYABLE_FAILURE_TYPES if k not in FAILURE_TYPE_VALUES]
    if unknown:
        raise AssertionError(f"RETRYABLE_FAILURE_TYPES names non-FailureType keys: {unknown}")


#: `sim_log_analysis`'s OWN triage categories -> this taxonomy. That module is
#: the existing classifier of a real sim.log, and re-deriving "what does a
#: scoreboard mismatch mean" here would be the second-vocabulary defect this
#: project keeps catching. `assert_triage_mapping_total()` holds the two
#: together, so a category added there fails a test here.
#:
#: uvm_fatal/uvm_error/scoreboard_mismatch/assertion -> TEST, not DUT: the
#: attribution of a functional miscompare to the DUT rather than the testbench
#: is decided by `tools/senior_dv/failure_attribution.py`'s boundary trace, and
#: a log marker alone cannot make that call. Claiming DUT from a `UVM_ERROR`
#: line would be exactly the unearned conclusion the Evidence Truth Rule
#: forbids. `classify_failure()` upgrades TEST -> DUT only when a real
#: boundary-trace attribution says DUT_BUG.
TRIAGE_CATEGORY_TO_FAILURE_TYPE: Dict[str, str] = {
    "uvm_fatal": FailureType.TEST.value,
    "uvm_error": FailureType.TEST.value,
    "bare_error": FailureType.DETERMINISTIC.value,
    "scoreboard_mismatch": FailureType.TEST.value,
    "assertion": FailureType.TEST.value,
    "timeout": FailureType.TRANSIENT.value,
    "other": FailureType.UNKNOWN.value,
}

#: `tools/senior_dv/failure_attribution.py`'s existing classification ->
#: this taxonomy. TB_BUG is a testbench defect (TEST); DUT_BUG is an RTL defect
#: (DUT). UNKNOWN deliberately maps to nothing so it never overrides a verdict
#: some other evidence source did earn.
ATTRIBUTION_TO_FAILURE_TYPE: Dict[str, str] = {
    "TB_BUG": FailureType.TEST.value,
    "DUT_BUG": FailureType.DUT.value,
}

#: Which `preflight.CheckOutcome.name` (those functions' own literal names)
#: means which failure type when it FAILs. The keys are read off preflight.py
#: verbatim -- if a check is ever renamed there, this table is the one place
#: that has to follow, the same single-mapping discipline
#: `degradation._CHECK_TO_TRIGGER` already uses for its two.
PREFLIGHT_CHECK_TO_FAILURE_TYPE: Dict[str, str] = {
    "eda_license": FailureType.LICENSE.value,
    "lsf_queue_health": FailureType.INFRASTRUCTURE.value,
    "host_reachability": FailureType.INFRASTRUCTURE.value,
    "disk_space": FailureType.RESOURCE.value,
    "workdir": FailureType.ENVIRONMENT.value,
    "eda_env_vars": FailureType.ENVIRONMENT.value,
}

#: Text rules, applied in order, first match wins. Every pattern here matches a
#: string this harness or its real toolchain actually produces -- an adapter
#: stderr, a VCS/LSF/FlexLM message, or one of `gates.py`'s own verdict tokens
#: -- and each rule carries the id it records in the classification, so a
#: verdict can always be traced to the exact rule that produced it.
#:
#: Ordering is load-bearing: LICENSE before RESOURCE (a "license queue" message
#: is about licenses), RESOURCE before ENVIRONMENT (a "No space left on device"
#: is a resource fact even though it surfaces as a file error), and
#: DETERMINISTIC last among the tool-error rules so a specific cause is never
#: shadowed by the generic "the tool reported an error" pattern.
_TEXT_RULES: Tuple[Tuple[str, str, "re.Pattern"], ...] = (
    # --- LICENSE (FlexLM / Synopsys SCL wording, plus preflight's own) -----
    ("license_checkout_failed", FailureType.LICENSE.value, re.compile(
        r"license.{0,40}(checkout|check-out|check out).{0,20}fail"
        r"|cannot checkout|unable to checkout|no such feature exists"
        r"|licensed number of users already reached|all licenses in use"
        r"|fully checked out|flexlm|flexnet|lmgrd|\bSCL\b.{0,20}licen", re.IGNORECASE)),
    # --- RESOURCE (the farm/host ran out of something measurable) ---------
    ("resource_exhausted", FailureType.RESOURCE.value, re.compile(
        r"no space left on device|disk quota exceeded|quota exceeded"
        r"|out of memory|cannot allocate memory|memory allocation failed"
        r"|TERM_MEMLIMIT|TERM_SWAPLIMIT|MemoryError"
        r"|cannot fork|resource temporarily unavailable", re.IGNORECASE)),
    # --- INFRASTRUCTURE (the scheduler/farm/transport itself) -------------
    ("scheduler_or_transport_failure", FailureType.INFRASTRUCTURE.value, re.compile(
        r"\bbsub\b.{0,40}(fail|error|not found)|batch system daemon not responding"
        r"|TERM_RUNLIMIT|job (was )?killed by (LSF|the scheduler)"
        r"|queue .{0,40}(closed|inactive)|not Open:Active"
        r"|RELAY_NOT_READY|RELAY_UNREACHABLE|VC_HOST_HOP_NOT_CONFIGURED"
        r"|host (is )?unreachable|no route to host", re.IGNORECASE)),
    # --- TRANSIENT (retrying the identical action can genuinely work) -----
    ("transient_io_or_api", FailureType.TRANSIENT.value, re.compile(
        r"\btimed out\b|\btimeout\b|connection reset|connection refused"
        r"|broken pipe|ECONNRESET|ETIMEDOUT|EAGAIN"
        r"|temporary failure in name resolution|rate limit|429 |Too Many Requests"
        r"|\b50[234]\b|service unavailable|overloaded_error|server had an error",
        re.IGNORECASE)),
    # --- ENVIRONMENT (this machine/session is not set up to do the work) --
    ("environment_not_set_up", FailureType.ENVIRONMENT.value, re.compile(
        r"command not found|No such file or directory|is not recognized as an internal"
        r"|Undefined variable|VCS_HOME|UVM_HOME|VERDI_HOME|DESIGNWARE_HOME"
        r"|_UNSET\b|not writable|does not exist|Permission denied", re.IGNORECASE)),
    # --- DETERMINISTIC (the same input will produce the same failure) -----
    ("compile_or_elaboration_error", FailureType.DETERMINISTIC.value, re.compile(
        r"\bError-\[[A-Z]|syntax error|parse error|\*E,|compilation (failed|aborted)"
        r"|elaboration (failed|error)|unresolved reference|undefined (module|macro)",
        re.IGNORECASE)),
    ("gate_rejected_evidence", FailureType.DETERMINISTIC.value, re.compile(
        r"\bMISSING_EVIDENCE\b|\bGATE_FAIL\b|\bDV_REVIEW_PENDING\b"
        r"|\bNEEDS_USER_INPUT\b", re.IGNORECASE)),
)

#: The Synopsys VIP component-name prefix this project's own generated
#: environments really use (`svt_*`, throughout `dv_harness/uvm_generator/`).
#: A UVM report whose reporting component sits under one of these is VIP-side.
#: Declared as data, and overridable per project through
#: `loop_budget.vip_component_prefixes`, because a project using a different
#: VIP vendor has a different prefix and guessing one would be fabrication.
DEFAULT_VIP_COMPONENT_PREFIXES: Tuple[str, ...] = ("svt_", "svt.")


def assert_triage_mapping_total() -> None:
    """Every `sim_log_analysis` triage category must have a decided failure
    type. A category added there without a decision here fails a test rather
    than silently classifying as UNKNOWN."""
    from .sim_log_analysis import TRIAGE_CATEGORIES
    missing = [c for c in TRIAGE_CATEGORIES if c not in TRIAGE_CATEGORY_TO_FAILURE_TYPE]
    if missing:
        raise AssertionError(
            f"sim_log_analysis triage categories with no FailureType meaning: {missing}. "
            f"Add them to TRIAGE_CATEGORY_TO_FAILURE_TYPE.")
    unknown = [c for c in TRIAGE_CATEGORY_TO_FAILURE_TYPE if c not in TRIAGE_CATEGORIES]
    if unknown:
        raise AssertionError(
            f"TRIAGE_CATEGORY_TO_FAILURE_TYPE names categories sim_log_analysis does not "
            f"have: {unknown}")
    bad = [f"{k}->{v}" for k, v in TRIAGE_CATEGORY_TO_FAILURE_TYPE.items()
           if v not in FAILURE_TYPE_VALUES]
    if bad:
        raise AssertionError(f"TRIAGE_CATEGORY_TO_FAILURE_TYPE values must be FailureType: {bad}")


@dataclass
class FailureClassification:
    """One classification plus the evidence it was derived from.

    `evidence` is the point of this dataclass, exactly as it is for
    `loop_contract.LoopObservation`: a reader can re-derive the verdict without
    trusting it, and `rule` names the exact rule that fired."""
    failure_type: str
    retryable: bool
    rule: str
    signature: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_failure_text(text: str) -> str:
    """The stable per-failure signature two attempts are compared on.

    Reuses `sim_log_analysis.normalize_failure_signature()` -- the same
    timestamp/hex/seed/counter stripping that module already applies so repeated
    occurrences of one root issue collapse to one signature. Re-implementing it
    here would give this harness two different answers to "is this the same
    failure", which is precisely the question the circuit breaker is deciding.
    """
    from .sim_log_analysis import normalize_failure_signature
    return normalize_failure_signature(text or "")[:600]


def _attribution_from_boundary_trace(trace: Any) -> Optional[str]:
    """`tools/senior_dv/failure_attribution.py`'s own rule, recomputed exactly
    as `dashboard._failure_attribution()` recomputes it: the FIRST boundary
    stage where expected != observed decides. Deliberately does NOT trust an
    agent-written `classification` field, for the same reason that function
    does not."""
    if not isinstance(trace, list):
        return None
    for step in trace:
        if not isinstance(step, dict):
            continue
        if step.get("expected") != step.get("observed"):
            st = step.get("stage")
            if st in ("SEQUENCE", "DRIVER", "MONITOR", "CHECKER", "SCOREBOARD"):
                return "TB_BUG"
            if st in ("DUT_INTERNAL", "INTERFACE_OUT"):
                return "DUT_BUG"
            return "UNKNOWN"
    return None


def classify_failure(text: str = "",
                     *,
                     verdict: str = "",
                     gate_reasons: Optional[List[Any]] = None,
                     adapter_ok: Optional[bool] = None,
                     preflight_checks: Optional[List[Any]] = None,
                     triage_categories: Optional[List[str]] = None,
                     boundary_trace: Any = None,
                     vip_component_prefixes: Optional[Tuple[str, ...]] = None,
                     ) -> FailureClassification:
    """Classify ONE failed attempt into section 93's taxonomy, from real
    evidence only.

    Every argument is a fact some real producer in this harness already writes:
      * `text` -- `state.json`'s `stages[stage].blocking_reason` (which
        `run_stage()` fills with either `"<verdict>: <gate reasons>"` or the
        adapter's own stderr), or a sim.log excerpt.
      * `verdict` / `gate_reasons` -- `gates.evaluate_stage_evidence()`'s own
        return values.
      * `adapter_ok` -- `AgentResult.ok`, i.e. whether the `claude` subprocess
        itself succeeded.
      * `preflight_checks` -- real `preflight.CheckOutcome`s.
      * `triage_categories` -- `sim_log_analysis.classify_signatures()`'s own
        `category` values.
      * `boundary_trace` -- the FAILURE_RECOVERY `failure_attribution` evidence
        block's `boundary_trace`.

    PRECEDENCE, highest first, and it matters -- strongest evidence wins:
      1. A real preflight FAIL. A measured license/queue/disk/env condition is
         a MEASUREMENT, not an inference from prose.
      2. A real boundary-trace attribution (DUT_BUG/TB_BUG). It is the one
         mechanism in this harness that actually separates a DUT defect from a
         testbench defect, and it is gate-enforced.
      3. A VIP-side UVM reporter in the text.
      4. The text rules, in their declared order.
      5. `sim_log_analysis`'s own triage category.
      6. `adapter_ok is False` with nothing else to say -> TRANSIENT is NOT
         assumed; an adapter failure with no recognizable cause is UNKNOWN, and
         UNKNOWN is retryable anyway, so nothing is lost by refusing to guess.

    Returns UNKNOWN with `rule="no_rule_matched"` when nothing matched. That is
    a real answer -- "this harness could not tell" -- and is deliberately
    distinct from every classified one.
    """
    reasons_text = "; ".join(str(r) for r in (gate_reasons or []))
    haystack = "\n".join(p for p in (verdict, reasons_text, text or "") if p)
    evidence: Dict[str, Any] = {
        "text_sample": (text or "")[:400],
        "verdict": verdict or None,
        "gate_reason_count": len(gate_reasons or []),
        "adapter_ok": adapter_ok,
    }
    signature = normalize_failure_text(haystack)

    # 1. measured resource facts
    for outcome in (preflight_checks or []):
        name = getattr(outcome, "name", None) or (
            outcome.get("name") if isinstance(outcome, dict) else None)
        status = getattr(outcome, "status", None) or (
            outcome.get("status") if isinstance(outcome, dict) else None)
        if status == "FAIL" and name in PREFLIGHT_CHECK_TO_FAILURE_TYPE:
            ft = PREFLIGHT_CHECK_TO_FAILURE_TYPE[name]
            evidence["preflight_check"] = name
            evidence["preflight_detail"] = getattr(outcome, "detail", None) or (
                outcome.get("detail") if isinstance(outcome, dict) else None)
            return FailureClassification(ft, RETRYABLE_FAILURE_TYPES[ft],
                                          f"preflight:{name}", signature, evidence)

    # 2. gate-enforced DUT-vs-TB attribution
    attribution = _attribution_from_boundary_trace(boundary_trace)
    if attribution in ATTRIBUTION_TO_FAILURE_TYPE:
        ft = ATTRIBUTION_TO_FAILURE_TYPE[attribution]
        evidence["failure_attribution"] = attribution
        return FailureClassification(ft, RETRYABLE_FAILURE_TYPES[ft],
                                      f"failure_attribution:{attribution}", signature, evidence)

    # 3. a VIP-side reporter
    prefixes = vip_component_prefixes or DEFAULT_VIP_COMPONENT_PREFIXES
    for prefix in prefixes:
        if prefix and prefix.lower() in haystack.lower():
            evidence["vip_component_prefix"] = prefix
            ft = FailureType.VIP.value
            return FailureClassification(ft, RETRYABLE_FAILURE_TYPES[ft],
                                          "vip_component_prefix", signature, evidence)

    # 4. the text rules
    for rule_id, ft, pattern in _TEXT_RULES:
        m = pattern.search(haystack)
        if m:
            evidence["matched_text"] = m.group(0)[:200]
            return FailureClassification(ft, RETRYABLE_FAILURE_TYPES[ft],
                                          rule_id, signature, evidence)

    # 5. sim_log_analysis's own triage category
    for category in (triage_categories or []):
        ft = TRIAGE_CATEGORY_TO_FAILURE_TYPE.get(category)
        if ft and ft != FailureType.UNKNOWN.value:
            evidence["triage_category"] = category
            return FailureClassification(ft, RETRYABLE_FAILURE_TYPES[ft],
                                          f"sim_log_triage:{category}", signature, evidence)

    ft = FailureType.UNKNOWN.value
    return FailureClassification(ft, RETRYABLE_FAILURE_TYPES[ft],
                                  "no_rule_matched", signature, evidence)


# ==========================================================================
# Section 91: the unified budget engine
# ==========================================================================
#: Section 91's eleven budget dimensions, verbatim. `unit` exists so a spend is
#: never a bare number a reader has to guess at.
DIMENSIONS: Tuple[Tuple[str, str], ...] = (
    ("max_iterations", "loop iterations (stage dispatches)"),
    ("max_wall_time", "seconds"),
    ("max_lsf_jobs", "submitted LSF jobs"),
    ("max_parallel_jobs", "concurrently running jobs"),
    ("max_retries", "stage retry attempts"),
    ("max_failed_experiments", "failed controlled experiments"),
    ("max_compute", "core-seconds"),
    ("max_license_usage", "license-seconds"),
    ("max_token_cost", "adapter tokens"),
    ("max_external_calls", "adapter (LLM) calls"),
    ("max_code_change_scope", "files changed"),
)
DIMENSION_NAMES: Tuple[str, ...] = tuple(name for name, _ in DIMENSIONS)

#: `None` limit == NOT ENFORCED. Same sentinel and same honesty contract as
#: `loop_contract.NOT_ENFORCED`: a `None` must always carry a real reason in
#: `BudgetEngine.sources`, because a `None` with no reason reads to a human as
#: a bound that exists.
NOT_ENFORCED = None


class BudgetResetRequiresReasonError(ValueError):
    """Raised by `BudgetEngine.reset()` without a real reason and actor.

    Section 91: "Budget exhaustion is explicit and cannot silently reset." A
    reset that leaves no record of who did it and why IS a silent reset, so the
    only way to clear a spend is to say both."""


class BudgetDimensionUnknownError(KeyError):
    """Raised on a spend against a dimension section 91 does not name."""


@dataclass
class BudgetState:
    """One dimension's real limit, its real spend, and where the limit came
    from."""
    name: str
    unit: str
    limit: Optional[float]
    source: str
    spent: float = 0.0
    exhausted_at: Optional[str] = None

    @property
    def enforced(self) -> bool:
        return self.limit is not None

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.spent >= float(self.limit)

    @property
    def remaining(self) -> Optional[float]:
        return None if self.limit is None else max(0.0, float(self.limit) - self.spent)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["enforced"] = self.enforced
        d["exhausted"] = self.exhausted
        d["remaining"] = self.remaining
        return d


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _config_block(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Accepts the whole config dict or just the `loop_budget` block -- the
    same forgiving shape `degradation._cfg()` already accepts, so a caller with
    either in hand does not have to remember which."""
    block = cfg or {}
    if isinstance(block, dict) and isinstance(block.get("loop_budget"), dict):
        block = block["loop_budget"]
    return block if isinstance(block, dict) else {}


DEFAULTS: Dict[str, Any] = {
    # Every run-scoped LIMIT defaults to None (NOT ENFORCED) with a stated
    # reason, exactly as loop_contract's own budget_sources do. This harness
    # genuinely has no wall-clock deadline, no run-scoped iteration cap and no
    # token accounting today; inventing one here would make a loop look bounded
    # when nothing bounds it, and would silently shorten every existing
    # project's runs.
    "limits": {},
    # Section 93's circuit breaker. `repeated_identical_failure_threshold`
    # defaults to None for the same reason: with policy.max_stage_retries=2 a
    # stage already runs at most three attempts, so any default here would
    # change the meaning of an existing project's retry budget without being
    # asked. A project that wants section 93's "repeating the identical
    # UVM_FATAL is not a useful retry" rule enforced sets a real number.
    "repeated_identical_failure_threshold": None,
    # A REAL wired trigger (engine._spend_retry_exhaustion_budget() calls
    # loop_contract.detect_oscillation_from_debug_loop_history() over the real
    # Blackboard entries), off by default with a real reason: loop() currently
    # routes an oscillating stage onto its graph FAIL edge, and sections 88-90's
    # `STOP BLIND RETRY -> reassess -> materially different strategy` RESPONSE
    # half is explicitly not built, so tripping here by default would change
    # routing this harness has not decided to change.
    "trip_on_oscillation": False,
    "breaker_blocks_loop": True,
    # Section 93's retry-vs-stop enforcement. OFF by default, and disclosed:
    # turning it on shortens a stage's real retry budget whenever the
    # classifier lands on a non-retryable type, which is a decision a project
    # makes, not one this module makes for it. The CLASSIFICATION itself is
    # always computed and recorded regardless of this flag.
    "enforce_retry_policy": False,
    # Section 92's deferral. OFF by default for the same reason, and it can
    # only ever fire where a REAL resource probe is already armed.
    "defer_low_value_under_pressure": False,
    "license_pressure_fraction": 0.10,
    "vip_component_prefixes": list(DEFAULT_VIP_COMPONENT_PREFIXES),
    "critical_stages": [],
}


def _merged_cfg(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    block = _config_block(cfg)
    merged = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAULTS.items()}
    for k, v in block.items():
        if k in DEFAULTS and v is not None:
            merged[k] = v
    return merged


def resolve_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """This module's settings for `cfg`, with every DEFAULT filled in.

    Public because `engine.py` needs the same merged answer this module uses --
    two places merging the same block with two different notions of "absent"
    is how a flag ends up meaning one thing to the engine and another to the
    ledger."""
    return _merged_cfg(cfg)


def _declared_limit(conf: Dict[str, Any], name: str) -> Optional[float]:
    limits = conf.get("limits") or {}
    if not isinstance(limits, dict):
        return None
    v = limits.get(name)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_dimension_states(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, BudgetState]:
    """The eleven dimensions with their REAL limits and REAL sources.

    Every limit that this harness genuinely enforces today is READ from the
    config key that enforces it, never retyped -- change
    `policy.max_stage_retries` and this engine's `max_retries` limit changes
    with it. Every limit nothing enforces is `None` AND carries the honest
    reason, and a project may declare a real run-scoped limit for any dimension
    through `loop_budget.limits`, which then wins and says so.
    """
    full = cfg or {}
    conf = _merged_cfg(full)
    policy = (full.get("policy") or {}) if isinstance(full, dict) else {}

    # The existing scattered budgets, read from their real owners.
    max_stage_retries = policy.get("max_stage_retries")
    inner_iterations = policy.get("inner_react_max_iterations")
    inner_adapter_calls = policy.get("inner_react_max_adapter_calls")
    try:
        from .context_budget import MAX_PACK_BYTES as _pack_bytes
    except Exception:  # pragma: no cover - context_budget is a first-party module
        _pack_bytes = None

    base: Dict[str, Tuple[Optional[float], str]] = {
        "max_retries": (
            NOT_ENFORCED,
            f"NOT ENFORCED run-wide: policy.max_stage_retries ({max_stage_retries}) is a "
            f"PER-GRAPH-NODE attempt budget, spent by engine.loop()'s own "
            f"`ss['attempts'] <= max_retry` test and reset the moment current_stage moves "
            f"on -- so it cannot answer a whole-run question, and treating it as a run-wide "
            f"cap would report every second retry-exhausted stage as an exhausted RUN. The "
            f"per-node spends ARE accumulated here so the run-wide total is visible; declare "
            f"loop_budget.limits.max_retries for a real run-scoped cap."),
        "max_iterations": (
            NOT_ENFORCED,
            f"NOT ENFORCED run-wide: engine.loop() is an unbounded `while True` over "
            f"the graph. policy.inner_react_max_iterations "
            f"({inner_iterations}) caps ONE stage's inner ReAct loop, not the run. "
            f"Declare loop_budget.limits.max_iterations for a real run-scoped cap."),
        "max_external_calls": (
            NOT_ENFORCED,
            f"NOT ENFORCED run-wide: policy.inner_react_max_adapter_calls "
            f"({inner_adapter_calls}) caps ONE stage's inner-loop adapter calls, "
            f"not the run's."),
        "max_wall_time": (
            NOT_ENFORCED,
            "NOT ENFORCED: no wall-clock deadline exists anywhere in engine.py. "
            "The elapsed seconds are still MEASURED and recorded here."),
        "max_lsf_jobs": (
            NOT_ENFORCED,
            "NOT ENFORCED by this loop: LSF job caps are the farm's own. "
            "preflight.check_queue_health() checks the queue before a submission; "
            "nothing caps how many this run may submit."),
        "max_parallel_jobs": (
            NOT_ENFORCED,
            "NOT ENFORCED: engine._advance_with_fanout()'s ThreadPoolExecutor is "
            "sized by the graph's own parallel_group membership, not by a cap."),
        "max_failed_experiments": (
            NOT_ENFORCED,
            "NOT ENFORCED: capability_evolution.run_controlled_experiment() is "
            "human-paced and REJECTED is a human decision, not an attempt-count "
            "outcome."),
        "max_compute": (
            NOT_ENFORCED,
            "NOT ENFORCED: no compute accounting exists in this harness."),
        "max_license_usage": (
            NOT_ENFORCED,
            "NOT ENFORCED: preflight.check_license() CHECKS availability before a "
            "build but caps no spend."),
        "max_token_cost": (
            NOT_ENFORCED,
            f"NOT ENFORCED: claude.max_turns caps ONE adapter call's turns, not the "
            f"run's token spend. context_budget.MAX_PACK_BYTES ({_pack_bytes}) caps "
            f"the resident context pack, which is a different resource."),
        "max_code_change_scope": (
            NOT_ENFORCED,
            "NOT ENFORCED numerically: change scope is governed by the PR-only "
            "main/master policy and change_impact.py, not a cap."),
    }

    states: Dict[str, BudgetState] = {}
    for name, unit in DIMENSIONS:
        limit, source = base[name]
        declared = _declared_limit(conf, name)
        if declared is not None:
            limit, source = declared, f"config loop_budget.limits.{name} (project-declared)"
        try:
            limit = None if limit is None else float(limit)
        except (TypeError, ValueError):
            limit = None
        states[name] = BudgetState(name=name, unit=unit, limit=limit, source=source)
    return states


def assert_sources_total(states: Dict[str, BudgetState]) -> None:
    """Every dimension must carry a real source string -- the real config key
    that enforces it, or the honest reason nothing does. The same rule
    `loop_contract.validate_contract()` enforces on a contract's
    `budget_sources`, enforced here on the live engine."""
    missing = sorted(n for n in DIMENSION_NAMES
                     if not (states.get(n) and (states[n].source or "").strip()))
    if missing:
        raise AssertionError(
            f"budget dimensions with no source recorded: {missing}. Every budget must name "
            f"either the real config key that enforces it or the honest reason nothing does.")


@dataclass
class BudgetDecision:
    """The result of one `spend()`/`check()`. `allowed` is what a caller acts
    on; every other field is why."""
    dimension: str
    allowed: bool
    exhausted: bool
    spent: float
    limit: Optional[float]
    remaining: Optional[float]
    loop_state: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BudgetEngine:
    """The unified ledger: one persisted record of what this RUN has spent on
    each of section 91's eleven dimensions, against the limits its real config
    declares.

    Persisted to `.dv-harness/loop_budget.json` with the same atomic
    tmpfile + `storage._atomic_replace()` discipline `degradation.save_state()`
    and `StateStore.save()` already use, so a concurrent `dv-harness status` or
    dashboard read never observes a half-written ledger.
    """

    def __init__(self, root: Path, cfg: Optional[Dict[str, Any]] = None):
        self.root = Path(root)
        self.cfg = cfg or {}
        self.conf = _merged_cfg(self.cfg)
        self.states = build_dimension_states(self.cfg)
        self._load()

    # -- persistence ------------------------------------------------------
    @property
    def path(self) -> Path:
        return self.root / ".dv-harness" / LEDGER_FILENAME

    def _blank(self) -> Dict[str, Any]:
        return {"schema_version": LEDGER_SCHEMA_VERSION, "created_at": _iso_now(),
                "spent": {}, "exhausted_at": {}, "resets": [], "breaker": _blank_breaker()}

    def _load(self) -> None:
        self.record = self._blank()
        p = self.path
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            # An unreadable ledger is reported as a fresh one rather than
            # crashing a run -- but the previous spend is NOT silently dropped
            # into a reset: `reset()` is the only thing that may clear a spend,
            # and this path records that it could not read the old one.
            self.record["load_error"] = "LEDGER_UNREADABLE"
            return
        if not isinstance(data, dict):
            self.record["load_error"] = "LEDGER_NOT_AN_OBJECT"
            return
        self.record.update(data)
        for name, value in (self.record.get("spent") or {}).items():
            if name in self.states:
                try:
                    self.states[name].spent = float(value)
                except (TypeError, ValueError):
                    pass
        for name, ts in (self.record.get("exhausted_at") or {}).items():
            if name in self.states:
                self.states[name].exhausted_at = ts

    def save(self) -> Dict[str, Any]:
        from .storage import _atomic_replace
        self.record["spent"] = {n: s.spent for n, s in self.states.items() if s.spent}
        self.record["exhausted_at"] = {n: s.exhausted_at for n, s in self.states.items()
                                       if s.exhausted_at}
        self.record["updated_at"] = _iso_now()
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="loop_budget.", suffix=".json", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.record, f, ensure_ascii=False, indent=2)
            _atomic_replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.record

    # -- spending ---------------------------------------------------------
    def check(self, dimension: str) -> BudgetDecision:
        """Is there budget left on this dimension? Never mutates anything."""
        st = self._state(dimension)
        return BudgetDecision(
            dimension=dimension, allowed=not st.exhausted, exhausted=st.exhausted,
            spent=st.spent, limit=st.limit, remaining=st.remaining,
            loop_state=(LoopState.BUDGET_EXHAUSTED.value if st.exhausted else None),
            reason=(f"{dimension} exhausted: {st.spent} of {st.limit} {st.unit}"
                    if st.exhausted else
                    (f"{dimension}: {st.spent} of {st.limit} {st.unit} spent"
                     if st.enforced else
                     f"{dimension}: NOT ENFORCED -- {st.source}")))

    def spend(self, dimension: str, amount: float = 1.0, *,
              note: str = "", save: bool = True) -> BudgetDecision:
        """Record real consumption. Returns the decision AFTER the spend.

        A spend that crosses a declared limit stamps `exhausted_at` ONCE and
        leaves it stamped: only `reset()` may clear it, and only with a reason.
        A spend against a NOT-ENFORCED dimension is still recorded -- measuring
        what a run costs is useful even where nothing caps it, and section 95's
        utility telemetry needs exactly these numbers.
        """
        st = self._state(dimension)
        try:
            st.spent = float(st.spent) + float(amount)
        except (TypeError, ValueError):
            raise ValueError(f"spend amount must be numeric, got {amount!r}")
        if st.exhausted and not st.exhausted_at:
            st.exhausted_at = _iso_now()
            self.record.setdefault("exhaustion_log", []).append({
                "at": st.exhausted_at, "dimension": dimension, "spent": st.spent,
                "limit": st.limit, "unit": st.unit, "note": note[:400],
                "loop_state": LoopState.BUDGET_EXHAUSTED.value,
            })
        if save:
            self.save()
        return self.check(dimension)

    def _state(self, dimension: str) -> BudgetState:
        if dimension not in self.states:
            raise BudgetDimensionUnknownError(
                f"unknown budget dimension {dimension!r}; section 91 names "
                f"{list(DIMENSION_NAMES)}")
        return self.states[dimension]

    # -- exhaustion, visibly ---------------------------------------------
    def exhausted_dimensions(self) -> List[str]:
        return sorted(n for n, s in self.states.items() if s.exhausted)

    def loop_state(self) -> Optional[str]:
        """`LoopState.BUDGET_EXHAUSTED` when any declared budget has run out,
        else None. Imported from `loop_contract` -- this module coins no second
        name for the state section 86 already named."""
        return LoopState.BUDGET_EXHAUSTED.value if self.exhausted_dimensions() else None

    def reset(self, dimension: str, *, reason: str, by: str, save: bool = True) -> Dict[str, Any]:
        """Clear one dimension's spend. REQUIRES a reason and an actor, appends
        an append-only ledger entry recording the spend that was cleared, and
        keeps the exhaustion_log intact.

        Section 91's "cannot silently reset", enforced: there is no code path in
        this module that zeroes a spend without producing this record."""
        if not (reason or "").strip() or not (by or "").strip():
            raise BudgetResetRequiresReasonError(
                f"resetting budget {dimension!r} requires BOTH a real `reason` and a real "
                f"`by` (who decided). Section 91: budget exhaustion cannot silently reset.")
        st = self._state(dimension)
        entry = {"at": _iso_now(), "dimension": dimension, "spent_before": st.spent,
                 "limit": st.limit, "was_exhausted": st.exhausted,
                 "exhausted_at": st.exhausted_at, "reason": reason[:1000], "by": by[:200]}
        self.record.setdefault("resets", []).append(entry)
        st.spent = 0.0
        st.exhausted_at = None
        if save:
            self.save()
        return entry

    def describe(self) -> Dict[str, Any]:
        """The compact, observable projection -- every dimension, its limit, its
        source, its spend, plus the exhaustion and reset history. A NOT-ENFORCED
        dimension reports its real reason, never an implied bound."""
        return {
            "root": str(self.root),
            "schema_version": LEDGER_SCHEMA_VERSION,
            "dimensions": {n: s.to_dict() for n, s in sorted(self.states.items())},
            "exhausted": self.exhausted_dimensions(),
            "loop_state": self.loop_state(),
            "exhaustion_log": list(self.record.get("exhaustion_log") or []),
            "resets": list(self.record.get("resets") or []),
            "breaker": self.breaker_state(),
            "load_error": self.record.get("load_error"),
        }

    # -- section 93: the circuit breaker ---------------------------------
    def breaker_state(self) -> Dict[str, Any]:
        br = self.record.get("breaker")
        return br if isinstance(br, dict) else _blank_breaker()

    def breaker_open(self) -> bool:
        return self.breaker_state().get("state") == BREAKER_OPEN

    def trip_breaker(self, trigger: str, detail: str, *,
                     evidence: Optional[Dict[str, Any]] = None,
                     save: bool = True) -> Dict[str, Any]:
        """Section 93's `STOP NEW ACTIONS -> PRESERVE STATE -> COLLECT EVIDENCE
        -> BLOCK -> ESCALATE -> REQUIRE RECOVERY CONDITION`, as far as this
        module is responsible for it.

        This half PRESERVES (the ledger and its history are never rewritten),
        COLLECTS (the trip carries the real evidence dict it was decided from)
        and BLOCKS (`breaker_open()` is what `engine.loop()` reads). The
        recovery condition is `reset_breaker()`, which -- exactly like
        `reset()` -- requires a real reason and a real actor. ESCALATION is the
        caller's: `engine` records a real event, which is the audit trail
        `dv-harness audit` already reads.

        Re-tripping an already-OPEN breaker APPENDS to its trigger list and
        never restamps `opened_at`, so "since when" keeps answering across
        cycles -- the same rule `degradation._apply_mode()` applies to
        `entered_at`."""
        if trigger not in BREAKER_TRIGGERS:
            raise ValueError(f"unknown circuit-breaker trigger {trigger!r}; "
                             f"section 93 names {list(BREAKER_TRIGGERS)}")
        br = dict(self.breaker_state())
        if br.get("state") != BREAKER_OPEN:
            br["state"] = BREAKER_OPEN
            br["opened_at"] = _iso_now()
            br["triggers"] = []
        triggers = list(br.get("triggers") or [])
        triggers.append({"at": _iso_now(), "trigger": trigger, "detail": detail[:1000],
                         "evidence": evidence or {}})
        br["triggers"] = triggers
        self.record["breaker"] = br
        if save:
            self.save()
        return br

    def reset_breaker(self, *, reason: str, by: str, save: bool = True) -> Dict[str, Any]:
        """The REQUIRE RECOVERY CONDITION half. A breaker that any code path
        could clear on its own is not a breaker, so this is the only way back to
        CLOSED and it takes a real reason and a real actor -- the same contract
        `reset()` takes for a budget.

        It authorizes nothing: closing the breaker only lets the loop attempt
        work again, and every approval gate that stood before it still stands."""
        if not (reason or "").strip() or not (by or "").strip():
            raise BudgetResetRequiresReasonError(
                "closing the circuit breaker requires BOTH a real `reason` (what recovery "
                "condition was actually met) and a real `by` (who decided).")
        br = dict(self.breaker_state())
        history = list(self.record.get("breaker_history") or [])
        if br.get("state") == BREAKER_OPEN:
            history.append({"opened_at": br.get("opened_at"), "closed_at": _iso_now(),
                            "triggers": br.get("triggers") or [],
                            "recovery_reason": reason[:1000], "closed_by": by[:200]})
        self.record["breaker_history"] = history
        self.record["breaker"] = _blank_breaker()
        if save:
            self.save()
        return self.record["breaker"]

    def blocking_reason(self) -> str:
        """One human-readable line explaining why no new action will be taken,
        built from the real recorded trip evidence. Empty when the breaker is
        closed."""
        br = self.breaker_state()
        if br.get("state") != BREAKER_OPEN:
            return ""
        parts = [f"{t.get('trigger')} ({t.get('detail', '')})"
                 for t in (br.get("triggers") or [])]
        return ("CIRCUIT_BREAKER_OPEN: no new loop action will be attempted until a recovery "
                "condition is recorded (`dv-harness loop-budget breaker-reset --reason ... "
                "--by ...`) -- " + "; ".join(parts))


BREAKER_CLOSED = "CLOSED"
BREAKER_OPEN = "OPEN"

#: Section 93's own trigger list, verbatim. Every one names real evidence:
#:   * BUDGET_EXHAUSTION           -- this ledger's own exhausted dimensions
#:   * REPEATED_IDENTICAL_FAILURE  -- N attempts sharing one normalized
#:                                    signature (sim_log_analysis's own
#:                                    normalization)
#:   * OSCILLATION                 -- loop_contract.
#:                                    detect_oscillation_from_debug_loop_history()
#:   * NO_PROGRESS                 -- loop_convergence's NO_PROGRESS/PLATEAU
#:   * EVIDENCE_INTEGRITY_FAILURE  -- a gate rejecting the evidence's own
#:                                    integrity (hash/identity), not its content
#:   * CRITICAL_ENVIRONMENT_FAILURE-- a preflight ENVIRONMENT/RESOURCE FAIL
#:   * UNSAFE_MUTATION             -- a refused out-of-scope write
#:                                    (capability_evolution's containment check,
#:                                    rtl_protection.protected_paths)
#:   * DESTRUCTIVE_ACTION          -- a refused destructive operation
#:                                    (git_governance's protected-branch block)
BREAKER_TRIGGERS: Tuple[str, ...] = (
    "BUDGET_EXHAUSTION",
    "REPEATED_IDENTICAL_FAILURE",
    "OSCILLATION",
    "NO_PROGRESS",
    "EVIDENCE_INTEGRITY_FAILURE",
    "CRITICAL_ENVIRONMENT_FAILURE",
    "UNSAFE_MUTATION",
    "DESTRUCTIVE_ACTION",
)


def _blank_breaker() -> Dict[str, Any]:
    return {"state": BREAKER_CLOSED, "opened_at": None, "triggers": []}


# ==========================================================================
# Section 92: license/resource-aware PRIORITIZATION and deferral
# ==========================================================================
PRESSURE_NONE = "NONE"
PRESSURE_ELEVATED = "ELEVATED"
PRESSURE_CRITICAL = "CRITICAL"
#: A probe that did not run, or ran and could not tell. NEVER treated as
#: pressure -- section 92's own rule is "Do not invent availability", and
#: deferring real work because nothing was measured would be inventing scarcity
#: in the other direction.
PRESSURE_UNKNOWN = "UNKNOWN"

PRIORITY_PROCEED = "PROCEED"
PRIORITY_PROCEED_CRITICAL = "PROCEED_CRITICAL"
PRIORITY_DEFER = "DEFER"

#: Section 92's "critical signoff work may receive higher priority under
#: policy". These are the closure-family `models.Stage` members -- the stages
#: whose completion IS the project closing -- and the list is overridable per
#: project through `loop_budget.critical_stages`.
DEFAULT_CRITICAL_STAGES: Tuple[str, ...] = (
    "SIGNOFF", "PROMOTION_READINESS", "REQUIREMENT_CLOSURE", "RE_AUDIT",
)


@dataclass
class ResourcePressure:
    """A measured statement about scarce EDA resources, with the real check
    outcomes it was derived from."""
    level: str
    reason: str
    license_headroom: Optional[float] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def pressure_from_checks(checks: List[Any], *,
                         license_pressure_fraction: float = 0.10) -> ResourcePressure:
    """Derive section 92's resource-pressure level from REAL
    `preflight.CheckOutcome`s -- never from a probe of this module's own.

    Three genuinely different facts, kept apart:
      * A FAIL on the license or queue check is CRITICAL. That is the same
        condition `degradation.evaluate()` already trips DEGRADED on, read from
        the same outcome, so the two can never disagree.
      * A PASS whose measured headroom is below `license_pressure_fraction` is
        ELEVATED. This band exists precisely BETWEEN "plenty" and "full": it is
        the range degradation deliberately says nothing about, and it is where
        deferring low-value work actually helps, because there are still
        licenses to be had and the question is who gets them.
      * A SKIP, or no license check at all, is UNKNOWN -- never NONE. "Nobody
        measured" and "measured, and there is room" are different facts.
    """
    evidence: Dict[str, Any] = {}
    headroom: Optional[float] = None
    saw_license = False
    for outcome in checks or []:
        name = getattr(outcome, "name", None)
        status = getattr(outcome, "status", None)
        detail = getattr(outcome, "detail", "") or ""
        raw = getattr(outcome, "evidence", None) or ""
        if name not in ("eda_license", "lsf_queue_health"):
            continue
        evidence[name] = {"status": status, "detail": detail[:400]}
        if status == "FAIL":
            return ResourcePressure(
                PRESSURE_CRITICAL,
                f"preflight {name} FAIL: {detail[:300]}",
                license_headroom=None, evidence=evidence)
        if name == "eda_license":
            saw_license = status == "PASS"
            if status == "PASS":
                headroom = _license_headroom(raw, detail)
                evidence[name]["headroom_fraction"] = headroom

    if not saw_license:
        return ResourcePressure(
            PRESSURE_UNKNOWN,
            "no PASSing eda_license outcome in the supplied preflight checks -- nothing "
            "was measured, so no availability is claimed (section 92: do not invent "
            "availability).",
            evidence=evidence)
    if headroom is None:
        return ResourcePressure(
            PRESSURE_UNKNOWN,
            "eda_license PASSed but carried no parseable issued/in-use counts, so the real "
            "headroom is unknown.",
            evidence=evidence)
    if headroom < float(license_pressure_fraction):
        return ResourcePressure(
            PRESSURE_ELEVATED,
            f"measured license headroom {headroom:.3f} is below the configured "
            f"loop_budget.license_pressure_fraction ({license_pressure_fraction}).",
            license_headroom=headroom, evidence=evidence)
    return ResourcePressure(
        PRESSURE_NONE,
        f"measured license headroom {headroom:.3f} at or above the configured "
        f"loop_budget.license_pressure_fraction ({license_pressure_fraction}).",
        license_headroom=headroom, evidence=evidence)


_DETAIL_HEADROOM_RE = re.compile(r":\s*(\d+)\s*/\s*(\d+)\s+available")


def _license_headroom(raw_lmstat: str, detail: str) -> Optional[float]:
    """The scarcest configured feature's available/issued fraction.

    Prefers the RAW lmstat text, parsed by `preflight`'s OWN
    `parse_license_availability()` -- the same parse `check_license()` itself
    used to reach its verdict, so this can never read the output differently
    than the check did. Falls back to the check's own formatted detail only
    when no raw output was carried, and returns None rather than a guess when
    neither is parseable."""
    if raw_lmstat:
        try:
            from .preflight import parse_license_availability
            parsed = parse_license_availability(raw_lmstat)
        except Exception:
            parsed = None
        features = (parsed or {}).get("features") or {}
        fractions = [
            (v["issued"] - v["in_use"]) / float(v["issued"])
            for v in features.values()
            if isinstance(v, dict) and v.get("issued")
        ]
        if fractions:
            return min(fractions)
    fractions = [int(a) / float(b) for a, b in _DETAIL_HEADROOM_RE.findall(detail or "")
                 if int(b) > 0]
    return min(fractions) if fractions else None


@dataclass
class PriorityDecision:
    """PROCEED / PROCEED_CRITICAL / DEFER for one unit of work, with why."""
    decision: str
    stage: str
    pressure: str
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def deferred(self) -> bool:
        return self.decision == PRIORITY_DEFER

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["deferred"] = self.deferred
        return d


def prioritize_stage(stage: str,
                     pressure: ResourcePressure,
                     *,
                     consumes_scarce_resource: bool,
                     critical_stages: Optional[Tuple[str, ...]] = None
                     ) -> PriorityDecision:
    """Section 92's missing half: which work is DEFERRED when a scarce resource
    is under real, measured pressure.

    The check-before-submit half is already real and lives in `preflight.py`
    (and `lsf_client.bsub_submit_with_preflight()`); this decides ORDER, not
    permission, and it can only ever DEFER. It never authorizes work a gate
    refused: a stage `preflight` BLOCKED stays blocked whatever this returns.

    Three rules, each with a reason a human can check:
      1. No measured pressure (NONE / UNKNOWN) -> PROCEED. Section 92: do not
         invent availability -- and equally, do not invent scarcity.
      2. Work that consumes NONE of the scarce resource -> PROCEED. Deferring a
         pure analysis stage because licenses are tight would delay the project
         and free nothing. `consumes_scarce_resource` is decided by the caller
         from the graph node's OWN declared execution-layer skills
         (`engine.EXECUTION_PREFLIGHT_SKILLS`: `vcs-build` / `devops-pipeline`),
         never from a stage-name guess here.
      3. Critical signoff-family work -> PROCEED_CRITICAL even under pressure,
         which is section 92's own "critical signoff work may receive higher
         priority under policy". Everything else consuming the scarce resource
         -> DEFER.
    """
    critical = tuple(critical_stages or DEFAULT_CRITICAL_STAGES)
    ev = {"pressure_reason": pressure.reason, "license_headroom": pressure.license_headroom,
          "consumes_scarce_resource": consumes_scarce_resource,
          "critical_stages": list(critical)}
    if pressure.level in (PRESSURE_NONE, PRESSURE_UNKNOWN):
        return PriorityDecision(PRIORITY_PROCEED, stage, pressure.level,
                                f"no deferral: measured pressure is {pressure.level} "
                                f"({pressure.reason})", ev)
    if not consumes_scarce_resource:
        return PriorityDecision(PRIORITY_PROCEED, stage, pressure.level,
                                "no deferral: this stage's graph node declares no "
                                "execution-layer skill, so it consumes none of the scarce "
                                "resource under pressure.", ev)
    if stage in critical:
        return PriorityDecision(PRIORITY_PROCEED_CRITICAL, stage, pressure.level,
                                f"critical signoff-family stage proceeds under "
                                f"{pressure.level} pressure (section 92: critical signoff "
                                f"work may receive higher priority under policy).", ev)
    return PriorityDecision(PRIORITY_DEFER, stage, pressure.level,
                            f"DEFERRED under {pressure.level} EDA resource pressure: "
                            f"{pressure.reason} This stage consumes the scarce resource and "
                            f"is not on the critical signoff path.", ev)


def measure_resource_pressure(cfg: Optional[Dict[str, Any]] = None,
                              runner: Optional[Any] = None,
                              checks: Optional[List[Any]] = None) -> ResourcePressure:
    """Measure pressure from real evidence.

    `checks` -- already-run `preflight.CheckOutcome`s, e.g. the ones
    `engine._execution_preflight_gate()` just obtained -- is preferred and costs
    nothing: re-probing a license server this run already probed would be a
    second round trip for the same fact.

    Otherwise, and only when a `runner` is explicitly injected (never by
    default), the probe goes through `degradation.probe_resources()`, i.e.
    `preflight.check_license()` / `check_queue_health()` themselves. With no
    checks and no runner this returns UNKNOWN and probes nothing -- the same
    evidence-based arming rule `degradation.evaluate()` uses, for the same
    reason: reading a missing binary as a full license is a fabricated verdict.
    """
    conf = _merged_cfg(cfg)
    fraction = float(conf.get("license_pressure_fraction") or 0.0)
    if checks:
        return pressure_from_checks(checks, license_pressure_fraction=fraction)
    if runner is None:
        return ResourcePressure(
            PRESSURE_UNKNOWN,
            "no preflight outcomes supplied and no probe transport injected -- nothing was "
            "measured. Section 92: do not invent availability.")
    from . import degradation
    return pressure_from_checks(degradation.probe_resources(cfg, runner=runner),
                                license_pressure_fraction=fraction)


# ==========================================================================
# The retry decision the engine actually consults
# ==========================================================================
@dataclass
class RetryDecision:
    """Whether `engine.loop()` should spend another attempt on this stage."""
    retry: bool
    reason: str
    failure_type: str
    enforced: bool
    repeats: int = 1
    classification: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def decide_retry(classification: FailureClassification,
                 *,
                 repeats: int = 1,
                 cfg: Optional[Dict[str, Any]] = None) -> RetryDecision:
    """Section 93's "Retry only when evidence supports it", as one decision.

    `repeats` is how many CONSECUTIVE attempts on this stage have carried this
    exact normalized signature -- the engine counts it off `state.json`, and it
    is what turns "this failed" into "this failed identically again", which is
    section 93's own example of a useless retry.

    ENFORCEMENT IS OPT-IN and the default is `retry=True`, matching the
    behaviour that exists today. `loop_budget.enforce_retry_policy` is what a
    project sets to make a non-retryable classification actually stop a retry,
    and `loop_budget.repeated_identical_failure_threshold` is what makes an
    identical repeat stop one. Both default off because either would otherwise
    silently shorten every existing project's `policy.max_stage_retries` on the
    strength of a classifier they never asked for -- the same disclosed-default
    discipline `require_tier` and `probe_resources` already use in this
    codebase. The classification is computed and recorded either way.
    """
    conf = _merged_cfg(cfg)
    enforce = bool(conf.get("enforce_retry_policy"))
    threshold = conf.get("repeated_identical_failure_threshold")
    try:
        threshold = None if threshold is None else int(threshold)
    except (TypeError, ValueError):
        threshold = None

    if threshold is not None and repeats >= threshold:
        return RetryDecision(
            False,
            f"REPEATED_IDENTICAL_FAILURE: {repeats} consecutive attempts produced the same "
            f"normalized failure signature (threshold {threshold}). Section 93: repeating "
            f"the same compile error or identical UVM_FATAL is not a useful retry.",
            classification.failure_type, True, repeats, classification.to_dict())

    if not classification.retryable and enforce:
        return RetryDecision(
            False,
            f"NON_RETRYABLE_FAILURE_TYPE: classified {classification.failure_type} by rule "
            f"{classification.rule}; retrying the identical action cannot resolve it.",
            classification.failure_type, True, repeats, classification.to_dict())

    if not classification.retryable:
        return RetryDecision(
            True,
            f"classified {classification.failure_type} (rule {classification.rule}), which "
            f"retrying does not resolve -- but loop_budget.enforce_retry_policy is off, so "
            f"the existing policy.max_stage_retries budget decides. Recorded, not enforced.",
            classification.failure_type, False, repeats, classification.to_dict())

    return RetryDecision(
        True,
        f"classified {classification.failure_type} (rule {classification.rule}); evidence "
        f"supports another attempt within the existing retry budget.",
        classification.failure_type, enforce, repeats, classification.to_dict())


# ==========================================================================
# Front door
# ==========================================================================
def execute_verb(root: Path, verb: str, *,
                 cfg: Optional[Dict[str, Any]] = None,
                 dimension: Optional[str] = None,
                 reason: str = "",
                 by: str = "",
                 text: str = "") -> tuple:
    """Returns (exit_code, payload). One implementation, reused by
    `dv-harness loop-budget` and `python -m dv_harness.loop_budget` -- two
    handlers over the same behaviour is the parallel-mechanism defect this
    project forbids, at CLI scale."""
    root = Path(root)
    if cfg is None:
        from .config import load_config
        cfg = load_config(root)

    if verb == "dimensions":
        states = build_dimension_states(cfg)
        assert_sources_total(states)
        return 0, {"dimensions": {n: s.to_dict() for n, s in sorted(states.items())},
                   "failure_types": list(FAILURE_TYPE_VALUES),
                   "retryable": dict(RETRYABLE_FAILURE_TYPES),
                   "breaker_triggers": list(BREAKER_TRIGGERS)}

    if verb == "status":
        engine = BudgetEngine(root, cfg)
        payload = engine.describe()
        # Exit 2 when work is actually stopped -- a CI signal, not an approval
        # signal in either direction.
        return (2 if (engine.breaker_open() or engine.exhausted_dimensions()) else 0), payload

    if verb == "classify":
        if not text:
            return 1, {"ok": False, "error": "TEXT_REQUIRED",
                       "hint": "pass the failing attempt's blocking_reason / log excerpt"}
        return 0, classify_failure(text).to_dict()

    if verb == "reset":
        if not dimension:
            return 1, {"ok": False, "error": "DIMENSION_REQUIRED",
                       "known": list(DIMENSION_NAMES)}
        engine = BudgetEngine(root, cfg)
        try:
            entry = engine.reset(dimension, reason=reason, by=by)
        except BudgetResetRequiresReasonError as exc:
            return 1, {"ok": False, "error": "RESET_REQUIRES_REASON_AND_BY", "detail": str(exc)}
        except BudgetDimensionUnknownError as exc:
            return 1, {"ok": False, "error": "UNKNOWN_DIMENSION", "detail": str(exc),
                       "known": list(DIMENSION_NAMES)}
        return 0, {"ok": True, "reset": entry}

    if verb == "breaker-reset":
        engine = BudgetEngine(root, cfg)
        if not engine.breaker_open():
            return 1, {"ok": False, "error": "BREAKER_NOT_OPEN",
                       "breaker": engine.breaker_state()}
        try:
            br = engine.reset_breaker(reason=reason, by=by)
        except BudgetResetRequiresReasonError as exc:
            return 1, {"ok": False, "error": "RECOVERY_REQUIRES_REASON_AND_BY",
                       "detail": str(exc)}
        return 0, {"ok": True, "breaker": br,
                   "history": engine.record.get("breaker_history") or []}

    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["dimensions", "status", "classify", "reset", "breaker-reset"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    ap = argparse.ArgumentParser(prog="python -m dv_harness.loop_budget",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=["dimensions", "status", "classify", "reset",
                                     "breaker-reset"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--dimension", default=None)
    ap.add_argument("--reason", default="")
    ap.add_argument("--by", default="")
    ap.add_argument("--text", default="")
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 dimension=args.dimension, reason=args.reason,
                                 by=args.by, text=args.text)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
