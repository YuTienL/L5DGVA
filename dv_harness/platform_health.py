"""dv_harness/platform_health.py -- PC-2: platform observability, per-subsystem
health state, and error budgets for the SLOs this harness can honestly measure
(2026-09-06, platform-observability task).

This harness already PRODUCES a lot of real operational signal, but every piece
of it lived in a different file behind a different verb, so no single question
"is this platform healthy right now, and against what objective" could be
answered. This module is the aggregator, and it is a READER only.

WHAT IT READS -- every number here comes from a mechanism that already existed;
nothing in this file measures anything itself, and nothing invents a metric:

  - `degradation.describe()`            -> the real NORMAL/DEGRADED mode and its
                                           three recorded triggers
                                           (adapter_unavailable / eda_license_full /
                                           farm_queue_congested)
  - `.dv-harness/events.jsonl`           -> the real EXECUTION_PREFLIGHT_PASS /
    via `loop_telemetry.read_events()`      EXECUTION_PREFLIGHT_BLOCKED audit trail
                                           `engine._execution_preflight_gate()`
                                           writes, each carrying the full
                                           `preflight.PreflightResult.to_dict()`,
                                           plus this harness's own `*_FAILED`
                                           best-effort side-channel failures
  - `connectivity_check.load_state()` +   -> the last real 3-gate run's per-gate
    `connectivity_check.evaluate_staleness()` GateStatus and whether those verdicts
                                           still describe the RTL on disk
  - `trend_analysis.trend_report()`      -> PASS->FAIL pattern regressions,
                                           repeat-fix-revert oscillation and
                                           passed-but-abnormally-slow runtime
                                           anomalies, read from the real
                                           evidence.duckdb (READ-ONLY)
  - `trend_analysis.daily_rollup()`      -> the real per-day regression verdict
                                           counts the pass-rate SLO is computed on

WHAT IT REFUSES TO DO. The gap this closes explicitly warned against fabricating
SLOs for capabilities this harness has no telemetry for. `UNMEASURABLE_SLIS`
below is that refusal made structural: it names the SLIs a normal SRE platform
would carry (uptime, request latency, availability) and states, per SLI, the
missing producer -- and `assert_no_unmeasurable_slo()` fails if one of those
names ever appears in `SLO_CATALOG`. Two SLOs are defined, and both count REAL
recorded events:

  - `regression_verdict_pass_rate`   -- good = a real recorded PASS verdict row
                                        in `regression_verdict_history`
  - `execution_preflight_pass_rate`  -- good = a real EXECUTION_PREFLIGHT_PASS
                                        event, bad = a real ..._BLOCKED event

UNKNOWN IS NOT HEALTHY. Every subsystem can report UNKNOWN, and UNKNOWN ranks
ABOVE HEALTHY in `HEALTH_SEVERITY`, so one unmeasured subsystem stops the whole
platform being reported HEALTHY. That is the same rule `connectivity.py` already
enforces for NOT_AVAILABLE ("never conflated with FAILED") applied to the other
side: an absent measurement is never conflated with a good one either. An SLO
window holding fewer than its `min_events` real events reports
INSUFFICIENT_EVIDENCE and no achieved percentage at all, rather than a 100%
computed from two samples.

AUTHORIZES NOTHING. This module imports no approval machinery, holds no writes,
starts no build/regression/LSF submission, and opens the evidence database
READ-ONLY through `trend_analysis`. A BREACHED error budget is a REPORT, never a
block: nothing here can stop a stage, and nothing here can let one through
either. `assert_authorizes_nothing()` asserts that against this file's own source.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import degradation as _degradation
from .loop_telemetry import read_events as read_harness_events

# --------------------------------------------------------------------------
# Health vocabulary
# --------------------------------------------------------------------------

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
CRITICAL = "CRITICAL"
UNKNOWN = "UNKNOWN"

HEALTH_STATES: Tuple[str, ...] = (HEALTHY, UNKNOWN, DEGRADED, CRITICAL)

#: Roll-up order. UNKNOWN deliberately outranks HEALTHY: a subsystem with no
#: evidence must never be averaged away into a green platform verdict. It ranks
#: BELOW DEGRADED because a measured problem is a stronger statement than an
#: unmeasured one.
HEALTH_SEVERITY: Dict[str, int] = {HEALTHY: 0, UNKNOWN: 1, DEGRADED: 2, CRITICAL: 3}


def worst(states) -> str:
    """The roll-up of several subsystem states, by `HEALTH_SEVERITY`. An empty
    set of subsystems is UNKNOWN -- never HEALTHY."""
    known = [s for s in states if s in HEALTH_SEVERITY]
    if not known:
        return UNKNOWN
    return max(known, key=lambda s: HEALTH_SEVERITY[s])


# Subsystem ids. Each names the concrete real thing it covers -- never a vague
# "backend"/"core" label a reader would have to guess at.
SUBSYS_AGENT_ADAPTER = "agent_adapter"
SUBSYS_EDA_LICENSE = "eda_license"
SUBSYS_LSF_QUEUE = "lsf_queue"
SUBSYS_EXECUTION_ENV = "execution_environment"
SUBSYS_CONNECTIVITY_GATES = "connectivity_gates"
SUBSYS_REGRESSION_QUALITY = "regression_quality"
SUBSYS_SELF_REPORTING = "harness_self_reporting"
SUBSYS_SLO_COMPLIANCE = "slo_compliance"

SUBSYSTEMS: Tuple[str, ...] = (
    SUBSYS_AGENT_ADAPTER,
    SUBSYS_EDA_LICENSE,
    SUBSYS_LSF_QUEUE,
    SUBSYS_EXECUTION_ENV,
    SUBSYS_CONNECTIVITY_GATES,
    SUBSYS_REGRESSION_QUALITY,
    SUBSYS_SELF_REPORTING,
    SUBSYS_SLO_COMPLIANCE,
)

#: The two real preflight event names `engine._execution_preflight_gate()`
#: emits. They are the whole producer for the execution-layer subsystems below
#: and for the `execution_preflight_pass_rate` SLO -- if the engine ever renames
#: one, this is the single place that has to follow.
EVENT_PREFLIGHT_PASS = "EXECUTION_PREFLIGHT_PASS"
EVENT_PREFLIGHT_BLOCKED = "EXECUTION_PREFLIGHT_BLOCKED"

#: `preflight.CheckOutcome.name` values, split by which subsystem owns them.
#: Verbatim from preflight.py's own `name = "..."` literals.
LICENSE_CHECKS = ("eda_license",)
QUEUE_CHECKS = ("lsf_queue_health",)
EXECUTION_ENV_CHECKS = ("host_reachability", "disk_space", "workdir", "eda_env_vars")

#: How many trailing events.jsonl lines one report reads. Same reader, same
#: bound as `loop_telemetry.DEFAULT_EVENT_SCAN_LINES`.
DEFAULT_EVENT_SCAN_LINES = 20000

#: Rolling window, in whole calendar days, both SLOs are measured over unless a
#: project overrides it in config.json's `platform_health` block.
DEFAULT_WINDOW_DAYS = 14

# TWO CLOCKS, NEVER MIXED. This harness's two recording surfaces are stamped by
# different clocks, and silently averaging them would drop or double-count a
# day's evidence around either midnight:
#   - events.jsonl carries `engine.now()`, an explicit ISO-8601 UTC stamp;
#   - evidence.duckdb's `recorded_at`/`ingested_at` default to DuckDB's own
#     `now()`, which stamps the machine's LOCAL wall clock.
# So each SLI's window is anchored in the clock its own source really uses, and
# every ErrorBudget carries `window_clock` saying which one it was.
CLOCK_UTC_EVENT = "utc_event_clock"
CLOCK_LOCAL_STORE = "local_store_clock"

CLOCK_DESCRIPTIONS: Dict[str, str] = {
    CLOCK_UTC_EVENT: "engine.now() -- ISO-8601 UTC, as written on every events.jsonl line",
    CLOCK_LOCAL_STORE: ("DuckDB now() -- the evidence store's own local wall-clock "
                        "recorded_at/ingested_at"),
}


@dataclass
class SubsystemHealth:
    """One subsystem's state plus the real evidence behind it. `fact_source`
    names the exact producer read, so a reader can go and check the claim."""
    subsystem: str
    state: str
    reason: str
    detail: str
    fact_source: str
    observations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# SLO catalog -- and the explicit refusal list
# --------------------------------------------------------------------------

#: SLIs this harness has NO producer for today, each with the missing producer
#: named. This list exists so nobody closes an "add SLOs" request by inventing a
#: 99.9% uptime number nothing measures. `assert_no_unmeasurable_slo()` enforces
#: that these ids can never appear in SLO_CATALOG.
UNMEASURABLE_SLIS: Dict[str, str] = {
    "harness_uptime": (
        "no heartbeat/supervisor writer exists -- the harness runs as one-shot CLI "
        "invocations and a foreground dashboard process, and nothing records "
        "process liveness over time, so any uptime percentage would be invented."),
    "request_latency": (
        "dashboard.py records no per-request timing; stage_profile.py times AGENT "
        "deliberation, which is a different thing and must never be relabelled as "
        "platform latency."),
    "service_availability": (
        "no external prober polls this harness, and the license/queue probes are "
        "opt-in (`degradation.probe_resources` defaults False), so absence of a "
        "recorded failure is not evidence of availability."),
    "simulator_farm_uptime": (
        "this harness reads no license manager (lmstat/FlexLM) or scheduler feed "
        "continuously -- see trend_analysis.LICENSE_HOURS_MODEL; it only sees the "
        "farm at the moments a preflight gate really ran."),
    "data_durability": (
        "no backup/replication of .dv-harness/ is performed or observed by this "
        "harness, so a durability objective would have no measurement at all."),
}


@dataclass
class SLODefinition:
    """One objective this harness can honestly compute TODAY. Every field that
    decides a verdict is explicit: `sli` states exactly what one good and one
    bad event is, and `fact_source` names the table or event trail counted."""
    slo_id: str
    subsystem: str
    description: str
    sli: str
    fact_source: str
    target_percent: float
    window_days: int = DEFAULT_WINDOW_DAYS
    min_events: int = 10
    clock: str = CLOCK_UTC_EVENT

    def to_dict(self) -> dict:
        return asdict(self)


SLO_CATALOG: Tuple[SLODefinition, ...] = (
    SLODefinition(
        slo_id="regression_verdict_pass_rate",
        subsystem=SUBSYS_REGRESSION_QUALITY,
        description=("Share of recorded regression verdicts that PASSed over the rolling "
                     "window -- the stage-gate outcome this harness genuinely measures "
                     "per run."),
        sli=("good = one row in regression_verdict_history with verdict_passed=true; "
             "bad = one row with verdict_passed=false. One event = one recorded verdict, "
             "counted by its own store-clock recorded_at."),
        fact_source=("evidence.duckdb regression_verdict_history, via "
                     "trend_analysis.daily_rollup() (opened READ-ONLY)"),
        target_percent=95.0,
        clock=CLOCK_LOCAL_STORE,
    ),
    SLODefinition(
        slo_id="execution_preflight_pass_rate",
        subsystem=SUBSYS_EXECUTION_ENV,
        description=("Share of execution-layer preflight gate runs that found the farm, "
                     "license and environment usable over the rolling window."),
        sli=(f"good = one {EVENT_PREFLIGHT_PASS} event; bad = one "
             f"{EVENT_PREFLIGHT_BLOCKED} event. One event = one real gate run by "
             f"engine._execution_preflight_gate(), counted by its own `ts`."),
        fact_source=".dv-harness/events.jsonl (append-only audit trail)",
        target_percent=90.0,
        min_events=5,
    ),
)

SLO_IDS: Tuple[str, ...] = tuple(s.slo_id for s in SLO_CATALOG)

#: Error-budget verdicts.
BUDGET_MEETING = "MEETING"
BUDGET_AT_RISK = "AT_RISK"
BUDGET_BREACHED = "BREACHED"
BUDGET_NO_EVIDENCE = "INSUFFICIENT_EVIDENCE"

#: Remaining error budget at or below which a still-meeting SLO is AT_RISK.
#: A warning band, not a second threshold on the objective itself.
AT_RISK_REMAINING_PERCENT = 25.0


def assert_no_unmeasurable_slo() -> None:
    """The catalog may never carry an SLI this harness has no producer for.
    Asserted by a test, and by `platform_health_report()` on every call."""
    overlap = sorted(set(SLO_IDS) & set(UNMEASURABLE_SLIS))
    if overlap:
        raise AssertionError(
            f"SLO_CATALOG defines {overlap}, which UNMEASURABLE_SLIS says this harness "
            f"has no real producer for. Either wire a real producer and delete the "
            f"UNMEASURABLE_SLIS entry, or drop the SLO -- never both.")


#: Identifiers this module must never reference. Observing a platform must not
#: become a way to grant, satisfy or bypass a human decision.
FORBIDDEN_AUTHORIZATION_SYMBOLS: Tuple[str, ...] = (
    "HumanApprovalRequiredError",
    "ProductionWriteNotAuthorizedError",
    "ControlPlane",
    "can_signoff",
    "assert_human_approval",
    "approve(",
)


def assert_authorizes_nothing(source_path: Optional[Path] = None) -> None:
    """This file's source may not mention any approval/authorization symbol.
    A health report is a statement about the world, never a permission."""
    path = Path(source_path) if source_path else Path(__file__)
    text = path.read_text(encoding="utf-8")
    # Skip this module's own declaration of the forbidden list and the docstring
    # sentence that explains the rule -- the check is about USE, not mention.
    body = text.split("FORBIDDEN_AUTHORIZATION_SYMBOLS: Tuple[str, ...] = (", 1)
    haystack = body[0].split('"""', 2)[-1] if len(body) > 1 else text
    hits = [s for s in FORBIDDEN_AUTHORIZATION_SYMBOLS if s in haystack]
    if hits:
        raise AssertionError(
            f"{path.name} references authorization machinery {hits}; a platform health "
            f"report must observe, never authorize.")


# --------------------------------------------------------------------------
# Event-window helpers
# --------------------------------------------------------------------------

def _parse_ts(raw: Any) -> Optional[datetime]:
    """`engine.now()`'s ISO-8601 UTC stamp, parsed. A record whose `ts` will not
    parse is dropped from the window rather than being counted at an assumed
    time -- an event of unknown age cannot honestly be placed in a window."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def window_bounds(window_days: int, asof: Optional[date] = None,
                  clock: str = CLOCK_UTC_EVENT) -> Tuple[date, date]:
    """The inclusive [start, end] calendar-day window, anchored in `clock` --
    see CLOCK_DESCRIPTIONS for why this harness has two. `asof` pins the end day
    explicitly, so a test's window is deterministic regardless of either clock."""
    if asof is not None:
        end = asof
    elif clock == CLOCK_LOCAL_STORE:
        end = datetime.now().date()
    else:
        end = datetime.now(timezone.utc).date()
    if window_days < 1:
        window_days = 1
    return end - timedelta(days=window_days - 1), end


def events_in_window(entries: List[Dict[str, Any]], window_days: int,
                     asof: Optional[date] = None) -> List[Dict[str, Any]]:
    """`entries` whose parseable `ts` falls in the window, oldest first. Always
    the UTC event clock -- `ts` is `engine.now()`'s explicit UTC stamp."""
    start, end = window_bounds(window_days, asof, CLOCK_UTC_EVENT)
    picked = []
    for e in entries:
        dt = _parse_ts(e.get("ts"))
        if dt is None:
            continue
        if start <= dt.date() <= end:
            picked.append(e)
    return picked


def latest_preflight_event(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The most recent real execution-preflight gate result in `entries`.

    Ordering is the file's own append order -- events.jsonl is append-only and
    single-writer through `storage.StateStore.event()`, so the last matching
    line IS the latest gate run, and no timestamp sort can be more correct than
    the order the harness actually wrote them in."""
    for e in reversed(entries):
        if e.get("event") in (EVENT_PREFLIGHT_PASS, EVENT_PREFLIGHT_BLOCKED):
            return e
    return None


def preflight_check_status(event: Optional[Dict[str, Any]], names) -> Dict[str, Dict[str, str]]:
    """The named `preflight.CheckOutcome`s carried by one recorded gate event,
    keyed by check name. Empty when the event carries none -- an older event
    written before a check existed must not be read as that check passing."""
    if not isinstance(event, dict):
        return {}
    checks = ((event.get("preflight") or {}).get("checks") or [])
    out: Dict[str, Dict[str, str]] = {}
    for c in checks:
        if isinstance(c, dict) and c.get("name") in names:
            out[c["name"]] = {"status": str(c.get("status") or ""),
                              "detail": str(c.get("detail") or "")}
    return out


# --------------------------------------------------------------------------
# Per-subsystem assessors
#
# Each takes already-read source data (never a path), so a test can drive every
# branch from real recorded shapes without needing the whole platform on disk,
# and `platform_health_report()` below is the one place that does the reading.
# --------------------------------------------------------------------------

def _from_checks(subsystem: str, checks: Dict[str, Dict[str, str]],
                 fact_source: str, *, absent_reason: str) -> Tuple[str, str, str, dict]:
    """Shared mapping from recorded preflight CheckOutcome statuses to a health
    state. FAIL -> CRITICAL (the gate really blocked on it); any SKIP -> UNKNOWN,
    whether or not its siblings passed, because a SKIP is missing evidence and
    not a measured problem -- calling a partially-measured subsystem DEGRADED
    would alert on this repo's own shipped config, which deliberately leaves
    `preflight.workdir` empty ("never guessed or hardcoded"); only all-PASS is
    HEALTHY."""
    if not checks:
        return UNKNOWN, "NO_RECORDED_CHECK", absent_reason, {}
    failed = sorted(n for n, c in checks.items() if c["status"] == "FAIL")
    skipped = sorted(n for n, c in checks.items() if c["status"] == "SKIP")
    passed = sorted(n for n, c in checks.items() if c["status"] == "PASS")
    obs = {"passed": passed, "failed": failed, "skipped": skipped,
           "details": {n: c["detail"] for n, c in sorted(checks.items())}}
    if failed:
        return (CRITICAL, "PREFLIGHT_CHECK_FAILED",
                f"last recorded preflight run FAILed {failed}", obs)
    if skipped:
        return (UNKNOWN, "PREFLIGHT_CHECK_SKIPPED",
                f"last recorded preflight run PASSed {passed} but SKIPped {skipped} -- "
                f"not configured here, so those were never measured", obs)
    return HEALTHY, "PREFLIGHT_CHECKS_PASSED", f"last recorded preflight run PASSed {passed}", obs


def assess_agent_adapter(degradation_desc: Dict[str, Any]) -> SubsystemHealth:
    """The LLM adapter, from `degradation.describe()`'s real recorded state.

    CRITICAL when the adapter trigger is set, because that is precisely the
    condition under which the engine will make no judgment call at all."""
    triggers = list(degradation_desc.get("triggers") or [])
    streak = int(degradation_desc.get("adapter_failure_streak") or 0)
    details = degradation_desc.get("trigger_details") or {}
    obs = {"adapter_failure_streak": streak,
           "degraded_cycles": int(degradation_desc.get("degraded_cycles") or 0),
           "mode": degradation_desc.get("mode")}
    src = "degradation.describe() (.dv-harness/degradation.json)"
    if _degradation.TRIGGER_ADAPTER in triggers:
        return SubsystemHealth(
            SUBSYS_AGENT_ADAPTER, CRITICAL, "ADAPTER_UNAVAILABLE",
            f"DEGRADED on {_degradation.TRIGGER_ADAPTER}: "
            f"{details.get(_degradation.TRIGGER_ADAPTER, '')}".strip(), src, obs)
    if streak > 0:
        return SubsystemHealth(
            SUBSYS_AGENT_ADAPTER, DEGRADED, "ADAPTER_FAILURE_STREAK",
            f"{streak} consecutive recorded adapter failure(s), below the trigger "
            f"threshold", src, obs)
    return SubsystemHealth(
        SUBSYS_AGENT_ADAPTER, HEALTHY, "NO_ADAPTER_FAILURE",
        "no adapter failure recorded and no adapter trigger set", src, obs)


def _resource_subsystem(subsystem: str, trigger: str, check_names,
                        degradation_desc: Dict[str, Any],
                        preflight_event: Optional[Dict[str, Any]],
                        absent_reason: str) -> SubsystemHealth:
    """Shared shape for the two farm-resource subsystems (license, queue), each
    of which has exactly two real producers: a `degradation` trigger, and the
    matching `preflight.CheckOutcome` carried by the last recorded gate event.

    The trigger is authoritative when set -- it is the recorded condition the
    engine is currently refusing to make judgment calls under, and it must
    outrank a stale PASS from an older gate run."""
    checks = preflight_check_status(preflight_event, check_names)
    state, reason, detail, obs = _from_checks(subsystem, checks,
                                              "", absent_reason=absent_reason)
    obs = dict(obs)
    obs["degradation_triggers"] = list(degradation_desc.get("triggers") or [])
    if preflight_event is not None:
        obs["preflight_event"] = preflight_event.get("event")
        obs["preflight_event_ts"] = preflight_event.get("ts")
    src = ("degradation.describe() + the last recorded "
           f"{EVENT_PREFLIGHT_PASS}/{EVENT_PREFLIGHT_BLOCKED} event in "
           ".dv-harness/events.jsonl")
    if trigger in (degradation_desc.get("triggers") or []):
        det = (degradation_desc.get("trigger_details") or {}).get(trigger, "")
        return SubsystemHealth(subsystem, CRITICAL, "DEGRADATION_TRIGGER_SET",
                               f"DEGRADED on {trigger}: {det}".strip(), src, obs)
    return SubsystemHealth(subsystem, state, reason, detail, src, obs)


def assess_eda_license(degradation_desc: Dict[str, Any],
                       preflight_event: Optional[Dict[str, Any]]) -> SubsystemHealth:
    return _resource_subsystem(
        SUBSYS_EDA_LICENSE, _degradation.TRIGGER_LICENSE, LICENSE_CHECKS,
        degradation_desc, preflight_event,
        absent_reason=("no execution preflight gate has recorded an eda_license check "
                       "here yet -- run `dv-harness preflight`, or a stage that routes "
                       "an execution-layer agent"))


def assess_lsf_queue(degradation_desc: Dict[str, Any],
                     preflight_event: Optional[Dict[str, Any]]) -> SubsystemHealth:
    return _resource_subsystem(
        SUBSYS_LSF_QUEUE, _degradation.TRIGGER_QUEUE, QUEUE_CHECKS,
        degradation_desc, preflight_event,
        absent_reason=("no execution preflight gate has recorded an lsf_queue_health "
                       "check here yet"))


def assess_execution_environment(preflight_event: Optional[Dict[str, Any]]
                                 ) -> SubsystemHealth:
    """Host reachability, disk, workdir and EDA env vars -- the four preflight
    checks that describe the machine a job would run on rather than the shared
    farm resources above."""
    checks = preflight_check_status(preflight_event, EXECUTION_ENV_CHECKS)
    state, reason, detail, obs = _from_checks(
        SUBSYS_EXECUTION_ENV, checks, "",
        absent_reason=("no execution preflight gate run has been recorded in this "
                       "project's events.jsonl yet"))
    obs = dict(obs)
    if preflight_event is not None:
        obs["preflight_event"] = preflight_event.get("event")
        obs["preflight_event_ts"] = preflight_event.get("ts")
        obs["blocked_on"] = list(preflight_event.get("blocked_on") or [])
    return SubsystemHealth(
        SUBSYS_EXECUTION_ENV, state, reason, detail,
        f"the last recorded {EVENT_PREFLIGHT_PASS}/{EVENT_PREFLIGHT_BLOCKED} event in "
        ".dv-harness/events.jsonl", obs)


#: Gate statuses `connectivity.GateStatus` can carry, mapped to health. FAIL is
#: CRITICAL (the bind is wrong); NOT_AVAILABLE / PENDING / NOT_YET_RUN stay
#: UNKNOWN and are never collapsed into either PASS or FAIL -- CLAUDE.md's
#: standing rule for exactly this enum.
_GATE_STATUS_TO_HEALTH: Dict[str, str] = {
    "PASS": HEALTHY,
    "FAIL": CRITICAL,
    "NOT_AVAILABLE": UNKNOWN,
    "PENDING": UNKNOWN,
    "NOT_YET_RUN": UNKNOWN,
}


def assess_connectivity_gates(state: Optional[Dict[str, Any]],
                              staleness: Optional[Dict[str, Any]]) -> SubsystemHealth:
    """The last real 3-gate connectivity run, plus whether its verdicts still
    describe the RTL currently on disk.

    A stale-but-passing run is DEGRADED, never HEALTHY: `evaluate_staleness()`
    already says those verdicts may not be cited once the RTL moved."""
    src = (".dv-harness/connectivity_check_state.json via connectivity_check.load_state()"
           " + connectivity_check.evaluate_staleness()")
    if not state:
        return SubsystemHealth(
            SUBSYS_CONNECTIVITY_GATES, UNKNOWN, "NEVER_RUN",
            "no connectivity-check gate run has ever been recorded for this project",
            src, {})
    gate_detail = state.get("gate_detail") or {}
    statuses = {g: str((d or {}).get("status") or "") for g, d in gate_detail.items()}
    obs: Dict[str, Any] = {"gate_statuses": statuses,
                           "recorded_at": state.get("recorded_at"),
                           "rtl_file_count": state.get("rtl_file_count")}
    if staleness is not None:
        obs["staleness"] = staleness
    if not statuses:
        return SubsystemHealth(
            SUBSYS_CONNECTIVITY_GATES, UNKNOWN, "NO_GATE_DETAIL",
            "a state file exists but records no per-gate status", src, obs)
    gate_states = [_GATE_STATUS_TO_HEALTH.get(s, UNKNOWN) for s in statuses.values()]
    state_now = worst(gate_states)
    failed = sorted(g for g, s in statuses.items() if s == "FAIL")
    if state_now == CRITICAL:
        return SubsystemHealth(SUBSYS_CONNECTIVITY_GATES, CRITICAL, "GATE_FAILED",
                               f"connectivity gate(s) {failed} FAILed on the last run",
                               src, obs)
    if staleness and staleness.get("stale"):
        return SubsystemHealth(
            SUBSYS_CONNECTIVITY_GATES, DEGRADED, f"STALE_{staleness.get('reason')}",
            f"recorded gate verdicts no longer describe the RTL on disk: "
            f"{staleness.get('detail')}", src, obs)
    if state_now == UNKNOWN:
        unmeasured = sorted(g for g, s in statuses.items()
                            if _GATE_STATUS_TO_HEALTH.get(s, UNKNOWN) == UNKNOWN)
        return SubsystemHealth(
            SUBSYS_CONNECTIVITY_GATES, UNKNOWN, "GATE_NOT_MEASURED",
            f"gate(s) {unmeasured} recorded a non-verdict status "
            f"({[statuses[g] for g in unmeasured]}) -- never read as PASS or FAIL",
            src, obs)
    return SubsystemHealth(SUBSYS_CONNECTIVITY_GATES, HEALTHY, "GATES_PASSED",
                           "all recorded connectivity gates PASSed against the current "
                           "RTL fingerprint", src, obs)


def assess_regression_quality(trend: Dict[str, Any]) -> SubsystemHealth:
    """Cross-run regression quality, from `trend_analysis.trend_report()`.

    A live PASS -> FAIL regression is CRITICAL; oscillation or an abnormally
    slow PASS is DEGRADED. Nothing here re-derives a detector -- the three
    verdicts are trend_analysis's own."""
    src = "trend_analysis.trend_report() over evidence.duckdb (READ-ONLY)"
    if not trend.get("available"):
        return SubsystemHealth(
            SUBSYS_REGRESSION_QUALITY, UNKNOWN, "NO_EVIDENCE_DATABASE",
            str(trend.get("reason") or "no evidence database to read"), src,
            {"db_path": trend.get("db_path")})
    regressions = trend.get("regressions") or []
    fix_reverts = trend.get("fix_reverts") or []
    anomalies = trend.get("runtime_anomalies") or []
    daily = trend.get("daily") or []
    obs = {"regression_count": len(regressions),
           "regressed_patterns": [r.get("pattern") for r in regressions],
           "fix_revert_count": len(fix_reverts),
           "oscillating_patterns": [o.get("pattern") for o in fix_reverts],
           "runtime_anomaly_count": len(anomalies),
           "days_with_evidence": len(daily)}
    if regressions:
        return SubsystemHealth(
            SUBSYS_REGRESSION_QUALITY, CRITICAL, "PATTERN_REGRESSION",
            f"{len(regressions)} pattern(s) went PASS -> FAIL: "
            f"{obs['regressed_patterns']}", src, obs)
    if fix_reverts or anomalies:
        return SubsystemHealth(
            SUBSYS_REGRESSION_QUALITY, DEGRADED, "REGRESSION_INSTABILITY",
            f"{len(fix_reverts)} repeat-fix-revert pattern(s) and "
            f"{len(anomalies)} passed-but-abnormally-slow job(s)", src, obs)
    if not daily:
        return SubsystemHealth(
            SUBSYS_REGRESSION_QUALITY, UNKNOWN, "NO_RUN_EVIDENCE",
            "the evidence database exists but holds no run evidence to trend yet",
            src, obs)
    return SubsystemHealth(
        SUBSYS_REGRESSION_QUALITY, HEALTHY, "NO_REGRESSION_DETECTED",
        f"no PASS -> FAIL regression, oscillation or runtime anomaly across "
        f"{len(daily)} day(s) of real evidence", src, obs)


#: Suffix of this harness's own best-effort side-channel failure events
#: (SIGNOFF_BUNDLE_EXPORT_FAILED, LOOP_TELEMETRY_EMIT_FAILED, ...). Every one is
#: written at a `except Exception` that deliberately did NOT fail the real work,
#: which is exactly why they need a place to be counted -- otherwise a harness
#: quietly failing half its side channels still looks healthy.
SELF_REPORTING_FAILURE_SUFFIX = "_FAILED"


def assess_harness_self_reporting(window_events: List[Dict[str, Any]],
                                  window_days: int) -> SubsystemHealth:
    """The harness reporting on itself: how many of its own best-effort side
    channels recorded a failure inside the window."""
    src = f".dv-harness/events.jsonl, trailing {window_days}-day window"
    if not window_events:
        return SubsystemHealth(
            SUBSYS_SELF_REPORTING, UNKNOWN, "NO_EVENTS_IN_WINDOW",
            f"no timestamped events at all in the last {window_days} day(s) -- "
            f"nothing to report on", src, {"events_in_window": 0})
    failures: Dict[str, int] = {}
    for e in window_events:
        name = e.get("event")
        if isinstance(name, str) and name.endswith(SELF_REPORTING_FAILURE_SUFFIX):
            failures[name] = failures.get(name, 0) + 1
    total_failures = sum(failures.values())
    obs = {"events_in_window": len(window_events),
           "failure_events": total_failures,
           "failure_event_names": dict(sorted(failures.items()))}
    if total_failures:
        return SubsystemHealth(
            SUBSYS_SELF_REPORTING, DEGRADED, "SELF_REPORTED_FAILURES",
            f"{total_failures} recorded `*_FAILED` side-channel event(s) across "
            f"{len(failures)} distinct kind(s) in the window", src, obs)
    return SubsystemHealth(
        SUBSYS_SELF_REPORTING, HEALTHY, "NO_SELF_REPORTED_FAILURE",
        f"{len(window_events)} event(s) in the window, none of them a recorded "
        f"side-channel failure", src, obs)


# --------------------------------------------------------------------------
# Error budgets
# --------------------------------------------------------------------------

@dataclass
class ErrorBudget:
    """One SLO's real error-budget arithmetic over the window.

    `error_budget_events` is `(1 - target) * total` -- the number of bad events
    the objective tolerates for the volume actually observed. Every field is a
    count of real recorded events or arithmetic on those counts; nothing is
    extrapolated, smoothed or projected."""
    slo_id: str
    subsystem: str
    status: str
    target_percent: float
    window_days: int
    window_start: str
    window_end: str
    window_clock: str
    total_events: int
    good_events: int
    bad_events: int
    achieved_percent: Optional[float]
    error_budget_events: Optional[float]
    budget_remaining_events: Optional[float]
    budget_remaining_percent: Optional[float]
    min_events: int
    sli: str
    fact_source: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_error_budget(slo: SLODefinition, good: int, bad: int,
                         *, asof: Optional[date] = None,
                         window_days: Optional[int] = None) -> ErrorBudget:
    """Turn one window's real good/bad event counts into an error-budget verdict.

    A window holding fewer than `slo.min_events` events yields
    INSUFFICIENT_EVIDENCE with `achieved_percent=None`: a 100% computed from two
    samples is not a measurement of a 95% objective, and reporting one would be
    the fabrication this module exists to avoid."""
    days = window_days or slo.window_days
    start, end = window_bounds(days, asof, slo.clock)
    total = int(good) + int(bad)
    common = dict(slo_id=slo.slo_id, subsystem=slo.subsystem,
                  target_percent=slo.target_percent, window_days=days,
                  window_start=start.isoformat(), window_end=end.isoformat(),
                  window_clock=slo.clock,
                  total_events=total, good_events=int(good), bad_events=int(bad),
                  min_events=slo.min_events, sli=slo.sli, fact_source=slo.fact_source)
    if total < slo.min_events:
        return ErrorBudget(status=BUDGET_NO_EVIDENCE, achieved_percent=None,
                           error_budget_events=None, budget_remaining_events=None,
                           budget_remaining_percent=None,
                           detail=(f"{total} recorded event(s) in the window, below the "
                                   f"{slo.min_events} this SLO requires before it will "
                                   f"claim a rate"), **common)
    achieved = round(100.0 * good / total, 4)
    allowed = round((1.0 - slo.target_percent / 100.0) * total, 6)
    remaining = round(allowed - bad, 6)
    if allowed > 0:
        remaining_pct = round(100.0 * remaining / allowed, 4)
    else:
        # A target of 100%, or a window so small the budget rounds to zero: any
        # bad event consumes the whole budget, and none leaves it whole.
        remaining_pct = 100.0 if bad == 0 else 0.0
    if achieved < slo.target_percent:
        status = BUDGET_BREACHED
        detail = (f"{achieved}% over {total} event(s) is below the {slo.target_percent}% "
                  f"objective; {bad} bad event(s) against a budget of {allowed}")
    elif remaining_pct <= AT_RISK_REMAINING_PERCENT:
        status = BUDGET_AT_RISK
        detail = (f"{achieved}% still meets {slo.target_percent}%, but only "
                  f"{remaining_pct}% of the error budget remains "
                  f"({bad} of {allowed} bad event(s) spent)")
    else:
        status = BUDGET_MEETING
        detail = (f"{achieved}% over {total} event(s) meets {slo.target_percent}%; "
                  f"{remaining_pct}% of the error budget remains")
    return ErrorBudget(status=status, achieved_percent=achieved,
                       error_budget_events=allowed, budget_remaining_events=remaining,
                       budget_remaining_percent=remaining_pct, detail=detail, **common)


def regression_pass_rate_counts(daily_points, window_days: int,
                                asof: Optional[date] = None) -> Tuple[int, int]:
    """(good, bad) recorded regression verdicts inside the window, summed from
    `trend_analysis.daily_rollup()`'s own per-day counts -- this module never
    re-queries the evidence database itself, so the SLO and the trend report can
    never disagree about how many verdicts a day held.

    Windowed on `CLOCK_LOCAL_STORE`, because `daily_rollup()`'s day keys are
    `strftime(recorded_at, ...)` over the store's own local-clock timestamps."""
    start, end = window_bounds(window_days, asof, CLOCK_LOCAL_STORE)
    good = bad = 0
    for p in daily_points:
        day = p.get("day") if isinstance(p, dict) else getattr(p, "day", None)
        if not day:
            continue
        try:
            d = date.fromisoformat(str(day))
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        total = int((p.get("verdict_count") if isinstance(p, dict)
                     else getattr(p, "verdict_count", 0)) or 0)
        passed = int((p.get("verdict_passed") if isinstance(p, dict)
                      else getattr(p, "verdict_passed", 0)) or 0)
        good += passed
        bad += max(total - passed, 0)
    return good, bad


def preflight_pass_rate_counts(window_events: List[Dict[str, Any]]) -> Tuple[int, int]:
    """(good, bad) real execution-preflight gate runs among already-windowed
    events."""
    good = sum(1 for e in window_events if e.get("event") == EVENT_PREFLIGHT_PASS)
    bad = sum(1 for e in window_events if e.get("event") == EVENT_PREFLIGHT_BLOCKED)
    return good, bad


#: How an error-budget verdict contributes to the `slo_compliance` subsystem.
#: BREACHED is CRITICAL *for that subsystem only*: the platform is not meeting an
#: objective it declared. It blocks nothing -- see this module's docstring.
_BUDGET_TO_HEALTH: Dict[str, str] = {
    BUDGET_MEETING: HEALTHY,
    BUDGET_AT_RISK: DEGRADED,
    BUDGET_BREACHED: CRITICAL,
    BUDGET_NO_EVIDENCE: UNKNOWN,
}


def assess_slo_compliance(budgets: List[ErrorBudget]) -> SubsystemHealth:
    src = "SLO_CATALOG error budgets computed in this report"
    if not budgets:
        return SubsystemHealth(SUBSYS_SLO_COMPLIANCE, UNKNOWN, "NO_SLO_EVALUATED",
                               "no SLO was evaluated", src, {})
    by_status = {b.slo_id: b.status for b in budgets}
    obs = {"slo_status": by_status,
           "breached": sorted(k for k, v in by_status.items() if v == BUDGET_BREACHED),
           "at_risk": sorted(k for k, v in by_status.items() if v == BUDGET_AT_RISK),
           "insufficient_evidence": sorted(k for k, v in by_status.items()
                                           if v == BUDGET_NO_EVIDENCE)}
    state = worst(_BUDGET_TO_HEALTH.get(b.status, UNKNOWN) for b in budgets)
    if obs["breached"]:
        reason, detail = "SLO_BREACHED", f"error budget exhausted for {obs['breached']}"
    elif obs["at_risk"]:
        reason, detail = "SLO_AT_RISK", f"error budget nearly spent for {obs['at_risk']}"
    elif state == UNKNOWN:
        reason, detail = ("SLO_INSUFFICIENT_EVIDENCE",
                          f"not enough recorded events to judge {obs['insufficient_evidence']}")
    else:
        reason, detail = "SLO_MET", f"every evaluated SLO is meeting its objective"
    return SubsystemHealth(SUBSYS_SLO_COMPLIANCE, state, reason, detail, src, obs)


# --------------------------------------------------------------------------
# The one report
# --------------------------------------------------------------------------

def slo_catalog_for(cfg: Optional[Dict[str, Any]] = None,
                    window_days: Optional[int] = None) -> List[SLODefinition]:
    """`SLO_CATALOG` with this project's real config.json overrides applied.

    A project may retune `target_percent`/`window_days`/`min_events` per SLO in
    config.json's `platform_health.slos` block; it may NOT add an SLO id, because
    an id with no producer in this module would compute nothing."""
    block = ((cfg or {}).get("platform_health") or {})
    default_days = window_days or int(block.get("window_days") or DEFAULT_WINDOW_DAYS)
    overrides = block.get("slos") or {}
    out = []
    for slo in SLO_CATALOG:
        o = dict(overrides.get(slo.slo_id) or {})
        out.append(SLODefinition(
            slo_id=slo.slo_id, subsystem=slo.subsystem, description=slo.description,
            sli=slo.sli, fact_source=slo.fact_source,
            target_percent=float(o.get("target_percent", slo.target_percent)),
            window_days=int(window_days or o.get("window_days", default_days)),
            min_events=int(o.get("min_events", slo.min_events)),
            # The clock is a property of where the evidence is STAMPED, never a
            # project preference -- deliberately not overridable.
            clock=slo.clock))
    return out


def _connectivity_sources(root: Path) -> Tuple[Optional[dict], Optional[dict]]:
    """The last recorded gate run and, when this project really declares its RTL
    sources, a FRESH staleness verdict computed by connectivity_check's own
    `evaluate_staleness()` against the RTL on disk right now.

    Best-effort: a project with no connectivity_check.json (this harness repo
    itself, for one) gets `staleness=None`, which `assess_connectivity_gates()`
    reports as "not evaluated" rather than as up-to-date."""
    try:
        from . import connectivity_check as cc
    except Exception:
        return None, None
    state_path = root / cc.DEFAULT_STATE_RELPATH
    try:
        state = cc.load_state(state_path)
    except Exception:
        return None, None
    if state is None:
        return None, None
    cfg_path = root / cc.DEFAULT_CONFIG_RELPATH
    if not cfg_path.is_file():
        return state, None
    try:
        cfg = cc.load_config(cfg_path)
        fp = cc.compute_rtl_fingerprint(root, cfg.rtl_sources)
        if fp["file_count"] == 0:
            return state, None
        return state, cc.evaluate_staleness(state, fp["fingerprint"])
    except Exception:
        return state, None


def platform_health_report(root, *, cfg: Optional[Dict[str, Any]] = None,
                           window_days: Optional[int] = None,
                           asof: Optional[date] = None,
                           scan_lines: int = DEFAULT_EVENT_SCAN_LINES) -> dict:
    """The whole platform health + error-budget picture as one JSON-serializable
    dict, read from this project's real recorded sources.

    Read-only end to end: `trend_analysis.trend_report()` opens the evidence
    database READ-ONLY, the events trail and the connectivity state file are
    read, and nothing on disk is written. No stage runs, no build starts, no job
    is submitted, and no approval is consulted or granted."""
    assert_no_unmeasurable_slo()
    root = Path(root)
    slos = slo_catalog_for(cfg, window_days)
    days = window_days or (slos[0].window_days if slos else DEFAULT_WINDOW_DAYS)
    # The report-level window is the EVENT clock's -- it is the one the
    # self-reporting subsystem is measured over. Each error budget below carries
    # its own `window_clock`, because the evidence store stamps a different one.
    start, end = window_bounds(days, asof, CLOCK_UTC_EVENT)

    entries, scanned, truncated = read_harness_events(root, scan_lines=scan_lines)
    windowed = events_in_window(entries, days, asof)
    latest_pf = latest_preflight_event(entries)

    try:
        deg = _degradation.describe(root)
    except Exception as e:  # a corrupt/absent state file must not crash a report
        deg = {"mode": _degradation.NORMAL, "triggers": [], "trigger_details": {},
               "adapter_failure_streak": 0, "degraded_cycles": 0, "read_error": str(e)}

    from . import trend_analysis as _trend
    try:
        trend = _trend.trend_report(root)
    except Exception as e:
        trend = {"available": False, "reason": f"trend_report failed: {e}"}

    conn_state, conn_staleness = _connectivity_sources(root)

    budgets: List[ErrorBudget] = []
    for slo in slos:
        if slo.slo_id == "regression_verdict_pass_rate":
            good, bad = regression_pass_rate_counts(trend.get("daily") or [],
                                                    slo.window_days, asof)
        elif slo.slo_id == "execution_preflight_pass_rate":
            good, bad = preflight_pass_rate_counts(
                events_in_window(entries, slo.window_days, asof))
        else:  # pragma: no cover - guarded by assert_slo_catalog_has_producers()
            raise AssertionError(f"SLO {slo.slo_id} has no producer in platform_health.py")
        budgets.append(compute_error_budget(slo, good, bad, asof=asof,
                                            window_days=slo.window_days))

    subsystems = [
        assess_agent_adapter(deg),
        assess_eda_license(deg, latest_pf),
        assess_lsf_queue(deg, latest_pf),
        assess_execution_environment(latest_pf),
        assess_connectivity_gates(conn_state, conn_staleness),
        assess_regression_quality(trend),
        assess_harness_self_reporting(windowed, days),
        assess_slo_compliance(budgets),
    ]
    overall = worst(s.state for s in subsystems)
    return {
        "project_root": str(root),
        "overall_state": overall,
        "window_days": days,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_clock": CLOCK_UTC_EVENT,
        "clock_descriptions": dict(CLOCK_DESCRIPTIONS),
        "degradation_mode": deg.get("mode"),
        "subsystems": [s.to_dict() for s in subsystems],
        "state_counts": {st: sum(1 for s in subsystems if s.state == st)
                         for st in HEALTH_STATES},
        "error_budgets": [b.to_dict() for b in budgets],
        "unmeasurable_slis": dict(UNMEASURABLE_SLIS),
        "event_scan": {"lines_scanned": scanned, "scan_truncated": truncated,
                       "scan_limit": scan_lines, "events_in_window": len(windowed)},
        "authorizes_nothing": ("read-only report: no stage run, no build, no LSF "
                               "submission, no approval consulted or granted"),
    }


def assert_slo_catalog_has_producers() -> None:
    """Every catalog id must be one `platform_health_report()` really computes.
    Asserted by a test -- an id with no producer would raise mid-report."""
    known = {"regression_verdict_pass_rate", "execution_preflight_pass_rate"}
    missing = sorted(set(SLO_IDS) - known)
    if missing:
        raise AssertionError(
            f"SLO_CATALOG carries {missing} with no counting branch in "
            f"platform_health_report() -- an SLO with no producer is a fabricated one.")


# --------------------------------------------------------------------------
# Rendering + CLI
# --------------------------------------------------------------------------

EXIT_OK = 0
#: DEGRADED/CRITICAL overall. UNKNOWN deliberately does NOT exit non-zero: it is
#: not an alert, it is an admission that the platform is unmeasured here -- and
#: it is never rendered as a pass either (the text output says so in as many
#: words, and `overall_state` carries UNKNOWN verbatim).
EXIT_UNHEALTHY = 2


def render_report_text(report: dict) -> str:
    lines = [f"DV Agent Harness L5 -- platform health ({report['project_root']})",
             f"OVERALL: {report['overall_state']}   "
             f"window {report['window_start']}..{report['window_end']} "
             f"({report['window_days']}d)   degradation mode: "
             f"{report['degradation_mode']}", ""]
    if report["overall_state"] == UNKNOWN:
        lines.append("UNKNOWN is not a pass: at least one subsystem has no evidence "
                     "here, so no health claim is made for it.")
        lines.append("")
    lines.append(f"{'SUBSYSTEM':<26}{'STATE':<10}REASON")
    lines.append("-" * 78)
    for s in report["subsystems"]:
        lines.append(f"{s['subsystem']:<26}{s['state']:<10}{s['reason']}")
        lines.append(f"{'':<26}{'':<10}{s['detail']}")
        lines.append(f"{'':<26}{'':<10}source: {s['fact_source']}")
    lines += ["", "ERROR BUDGETS", "-" * 78]
    for b in report["error_budgets"]:
        achieved = ("-" if b["achieved_percent"] is None
                    else f"{b['achieved_percent']}%")
        remaining = ("-" if b["budget_remaining_percent"] is None
                     else f"{b['budget_remaining_percent']}%")
        lines.append(f"- {b['slo_id']} [{b['status']}]  target {b['target_percent']}%  "
                     f"achieved {achieved}  budget left {remaining}")
        lines.append(f"    {b['good_events']} good / {b['bad_events']} bad over "
                     f"{b['window_start']}..{b['window_end']} ({b['window_clock']})")
        lines.append(f"    {b['detail']}")
        lines.append(f"    SLI: {b['sli']}")
        lines.append(f"    source: {b['fact_source']}")
    lines += ["", "NOT MEASURED HERE (no producer exists -- deliberately no SLO)", "-" * 78]
    for name, why in sorted(report["unmeasurable_slis"].items()):
        lines.append(f"- {name}: {why}")
    lines += ["", report["authorizes_nothing"]]
    return "\n".join(lines)


def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            as_json: bool = False, window_days: Optional[int] = None
            ) -> Tuple[int, dict, str]:
    """(exit_code, report, text) -- the one shared implementation behind both
    `dv-harness platform-health` and `python -m dv_harness.platform_health`."""
    report = platform_health_report(root, cfg=cfg, window_days=window_days)
    code = EXIT_UNHEALTHY if report["overall_state"] in (DEGRADED, CRITICAL) else EXIT_OK
    return code, report, render_report_text(report)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.platform_health",
        description="Per-subsystem platform health plus SLO error budgets, aggregated "
                    "from this project's real recorded sources. Read-only.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--window-days", type=int, default=None)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        from .config import load_config
        cfg = load_config(root)
    except Exception:
        cfg = None
    code, report, text = execute(root, cfg=cfg, as_json=args.json,
                                 window_days=args.window_days)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
