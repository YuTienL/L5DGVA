"""dv_harness/degradation.py -- explicit, observable DEGRADED mode.

User spec (2026-09-03): "降級路徑：Claude API 不可用、license 全滿、farm 塞車時,
harness 應降級成「只收集資料、不做判斷」, 而不是整個停擺或胡亂重試."

The three real trigger conditions, and where each one's evidence comes from
(every one REUSES an existing real mechanism -- this module deliberately
implements no checking of its own):

1. TRIGGER_ADAPTER ("Claude API 不可用"): a run of CONSECUTIVE ADAPTER_FAIL
   outcomes. The counter is fed by engine.run_stage()'s already-existing
   `result.ok is False` branch (the one that sets Status.FAIL +
   "ADAPTER_FAIL" and calls replan_stage()) -- this module never calls the
   adapter, never retries anything, and adds NO parallel retry mechanism.
   Stage-level retry stays exactly where it already lives:
   `policy.max_stage_retries` in engine.loop(). The default threshold (3) is
   deliberately max_stage_retries(2) + 1, i.e. "the existing retry budget was
   already spent and the adapter is STILL failing" -- degradation begins only
   after the mechanism that already exists has demonstrably not helped.

2. TRIGGER_LICENSE ("license 全滿"): preflight.check_license()'s own
   CheckOutcome, unmodified. That function already parses real `lmutil
   lmstat` output and already distinguishes license starvation
   ("fully checked out") from a down server or a missing feature. No second
   license check exists anywhere in this module.

3. TRIGGER_QUEUE ("farm 塞車"): preflight.check_queue_health()'s own
   CheckOutcome, unmodified -- real `bqueues <queue>` output, Open:Active
   criterion.

WHAT DEGRADED ACTUALLY CHANGES (the "只收集資料、不做判斷" half): while
degraded, engine.run_stage() refuses to make the JUDGMENT-requiring call --
no adapter.run() proposing a verdict/next action, no gate promotion, no
stage transition. It still performs real DATA COLLECTION on every cycle: it
re-probes the triggers, writes a real auto-checkpoint session snapshot
(session_snapshot.save_session), and appends a real DEGRADED_CYCLE event to
events.jsonl. Job status polling and log collection are unaffected for a
different and better reason -- they run in the detached LSF watcher process
(regression_reporter.ensure_watcher_running()), which has never gone through
run_stage() at all, so a DEGRADED engine cannot stop them.

WHY RESOURCE PROBING IS OPT-IN (`degradation.probe_resources`, default
False): preflight.py's own docstring is explicit that LocalCommandRunner is
only the correct transport when dv_harness runs server-side on the Linux DV
server, where lmutil/bqueues are natively on PATH. On a PC-side session they
are simply absent, and check_license/check_queue_health would FAIL for
"command not found" -- which is not evidence of a full license or a
congested farm. Turning a missing binary into a DEGRADED verdict would be
exactly the kind of invented conclusion CLAUDE.md's Evidence Truth Rule
forbids, so a project opts in once it is really running where those commands
exist (or injects its own Runner, as the tests do).

WHY require_license_configured IS FORCED False FOR THE PROBE: the preflight
GATE must block on an unconfirmed license ("沒過就 BLOCKED，不派 job" -- an
unconfigured license_server FAILs there on purpose, see
PreflightConfig.require_license_configured). This MONITOR must not: a
project that has simply never filled in `preflight.license_server` has not
told us the license is full, it has told us nothing. Forcing the flag off
here makes that case preflight's own SKIP status, and SKIP never triggers
degradation -- reusing preflight's existing three-valued outcome instead of
inventing a fourth.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .preflight import (
    CheckOutcome,
    PreflightConfig,
    Runner,
    check_license,
    check_queue_health,
    config_from_dict,
)

# Explicit, observable state values -- surfaced verbatim by
# engine.DVHarness.summary() (i.e. `dv-harness status`), never a silent
# internal branch.
NORMAL = "NORMAL"
DEGRADED = "DEGRADED"

TRIGGER_ADAPTER = "adapter_unavailable"
TRIGGER_LICENSE = "eda_license_full"
TRIGGER_QUEUE = "farm_queue_congested"

# Which preflight check backs which trigger. The keys are
# preflight.CheckOutcome.name values exactly as those functions already set
# them ("eda_license" / "lsf_queue_health") -- if preflight ever renames one,
# this mapping is the single place that has to follow.
_CHECK_TO_TRIGGER = {
    "eda_license": TRIGGER_LICENSE,
    "lsf_queue_health": TRIGGER_QUEUE,
}

STATE_FILENAME = "degradation.json"

DEFAULTS = {
    "enabled": True,
    "adapter_failure_threshold": 3,
    "probe_resources": False,
    "probe_min_interval_sec": 60,
}


def _cfg(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merges a config.json `degradation` block over DEFAULTS. Accepts the
    whole config dict or just the block, so a caller with either in hand does
    not have to remember which."""
    block = cfg or {}
    if "degradation" in block and isinstance(block.get("degradation"), dict):
        block = block["degradation"]
    merged = dict(DEFAULTS)
    for k, v in (block or {}).items():
        if k in DEFAULTS and v is not None:
            merged[k] = v
    return merged


def state_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / STATE_FILENAME


def _blank_state() -> Dict[str, Any]:
    return {
        "mode": NORMAL,
        "triggers": {},          # trigger name -> {"detail":..., "since":...}
        "adapter_failure_streak": 0,
        "entered_at": None,
        "cleared_at": None,
        "last_probe_at": None,
        "cycles": 0,             # completed data-collection-only cycles
    }


def load_state(root: Path) -> Dict[str, Any]:
    p = state_path(root)
    if not p.exists():
        return _blank_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _blank_state()
    if not isinstance(data, dict):
        return _blank_state()
    merged = _blank_state()
    merged.update(data)
    return merged


def save_state(root: Path, st: Dict[str, Any]) -> Dict[str, Any]:
    """Atomic tmpfile + os.replace, the same discipline storage.StateStore.
    save() / config.save_config() already use -- a concurrent
    `dv-harness status` (or the dashboard's own state read) must never
    observe a half-written file."""
    from .storage import _atomic_replace
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="degradation.", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return st


def is_degraded(root: Path) -> bool:
    return load_state(root).get("mode") == DEGRADED


def _apply_mode(st: Dict[str, Any]) -> Dict[str, Any]:
    """Single place that derives `mode` from `triggers`. Any trigger present
    means DEGRADED; none means NORMAL. entered_at/cleared_at are stamped only
    on a real edge (NORMAL->DEGRADED / DEGRADED->NORMAL), so `entered_at`
    keeps answering "since when" across many cycles instead of resetting on
    every re-evaluation."""
    was = st.get("mode")
    now_mode = DEGRADED if st.get("triggers") else NORMAL
    if now_mode == DEGRADED and was != DEGRADED:
        st["entered_at"] = time.time()
        st["cleared_at"] = None
        st["cycles"] = 0
    elif now_mode == NORMAL and was == DEGRADED:
        st["cleared_at"] = time.time()
    st["mode"] = now_mode
    return st


def _set_trigger(st: Dict[str, Any], name: str, detail: str) -> None:
    triggers = st.setdefault("triggers", {})
    if name in triggers:
        triggers[name]["detail"] = detail          # keep the ORIGINAL `since`
    else:
        triggers[name] = {"detail": detail, "since": time.time()}


def _clear_trigger(st: Dict[str, Any], name: str) -> None:
    st.setdefault("triggers", {}).pop(name, None)


# --- trigger 1: adapter availability -----------------------------------


def record_adapter_failure(root: Path, cfg: Optional[Dict[str, Any]] = None,
                            stage: str = "", detail: str = "") -> Dict[str, Any]:
    """Called from engine.run_stage()'s EXISTING ADAPTER_FAIL branch (the
    `else` of `if result.ok:`). Counts, never retries -- see this module's
    docstring on why the retry mechanism stays in loop()."""
    conf = _cfg(cfg)
    st = load_state(root)
    st["adapter_failure_streak"] = int(st.get("adapter_failure_streak") or 0) + 1
    threshold = int(conf["adapter_failure_threshold"])
    if st["adapter_failure_streak"] >= threshold:
        _set_trigger(st, TRIGGER_ADAPTER,
                     f"{st['adapter_failure_streak']} consecutive adapter failures "
                     f"(threshold {threshold}); last on stage {stage or 'unknown'}: "
                     f"{(detail or '')[:400]}")
    _apply_mode(st)
    return save_state(root, st)


def record_adapter_success(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Called from engine.run_stage()'s EXISTING `if result.ok:` branch. One
    real successful adapter call is sufficient evidence that the adapter is
    reachable again, so the streak resets and this trigger clears -- but any
    OTHER trigger (license/queue) stays, so a project that is degraded for a
    full license does not get quietly promoted back to NORMAL by an unrelated
    successful call."""
    st = load_state(root)
    if not st.get("adapter_failure_streak") and TRIGGER_ADAPTER not in (st.get("triggers") or {}):
        return st
    st["adapter_failure_streak"] = 0
    _clear_trigger(st, TRIGGER_ADAPTER)
    _apply_mode(st)
    return save_state(root, st)


# --- triggers 2 & 3: real preflight resource probes ---------------------


def probe_resources(cfg: Optional[Dict[str, Any]] = None,
                     runner: Optional[Runner] = None) -> List[CheckOutcome]:
    """Runs preflight's OWN check_license()/check_queue_health() and returns
    their CheckOutcomes unchanged. `cfg` is the full config dict (or just its
    `preflight` block); `runner` is injected exactly the way
    dv_harness_tests/test_preflight.py already injects one, so this never
    talks to a live license/scheduler server in a test.

    require_license_configured is forced False here -- see this module's
    docstring for why the GATE and the MONITOR must differ on that one flag.
    """
    block = cfg or {}
    if "preflight" in block and isinstance(block.get("preflight"), dict):
        block = block["preflight"]
    pf: PreflightConfig = config_from_dict(block, require_license_configured=False)
    if runner is None:
        from .preflight import LocalCommandRunner
        runner = LocalCommandRunner()
    return [check_license(runner, pf), check_queue_health(runner, pf)]


def evaluate(root: Path, cfg: Optional[Dict[str, Any]] = None,
             runner: Optional[Runner] = None, force_probe: bool = False) -> Dict[str, Any]:
    """Re-evaluates the license/queue triggers against REAL current evidence
    and persists the result. The adapter trigger is deliberately untouched
    here: it is evidence about this harness's own adapter calls, not about
    the farm, and only a real successful/failed adapter call may change it.

    A FAIL sets that check's trigger; a PASS clears it; a SKIP clears it too
    -- SKIP means "this check genuinely does not apply here" (preflight's own
    semantics), which is never evidence of a problem.

    Probing is skipped entirely (state returned unchanged) when
    `degradation.probe_resources` is off, or when the last probe was more
    recent than `probe_min_interval_sec` and `force_probe` is False -- a
    stage transition must not fire an lmstat/bqueues round trip every few
    seconds."""
    conf = _cfg(cfg)
    st = load_state(root)
    if not conf["probe_resources"]:
        return st
    last = st.get("last_probe_at")
    if (not force_probe and last is not None
            and (time.time() - float(last)) < float(conf["probe_min_interval_sec"])):
        return st
    for outcome in probe_resources(cfg, runner=runner):
        trigger = _CHECK_TO_TRIGGER.get(outcome.name)
        if trigger is None:
            continue
        if outcome.status == "FAIL":
            _set_trigger(st, trigger, outcome.detail)
        else:
            _clear_trigger(st, trigger)
    st["last_probe_at"] = time.time()
    _apply_mode(st)
    return save_state(root, st)


def force_trigger(root: Path, name: str, detail: str) -> Dict[str, Any]:
    """Explicitly raise one trigger without probing. Exists for the real
    operational case where a human (or an out-of-band monitor) already knows
    the farm is jammed and wants the harness to stop making judgment calls
    now -- and it is what the tests use to simulate a condition without
    faking a whole license server."""
    st = load_state(root)
    _set_trigger(st, name, detail)
    _apply_mode(st)
    return save_state(root, st)


def clear_trigger(root: Path, name: str) -> Dict[str, Any]:
    st = load_state(root)
    _clear_trigger(st, name)
    if name == TRIGGER_ADAPTER:
        st["adapter_failure_streak"] = 0
    _apply_mode(st)
    return save_state(root, st)


def note_cycle(root: Path) -> Dict[str, Any]:
    """Records that one real data-collection-only cycle completed while
    degraded. Kept separate from evaluate() so the count reflects cycles the
    engine actually performed, not probes."""
    st = load_state(root)
    st["cycles"] = int(st.get("cycles") or 0) + 1
    return save_state(root, st)


def describe(root: Path) -> Dict[str, Any]:
    """The compact, observable projection engine.DVHarness.summary() folds
    into `dv-harness status`. Reports real recorded values only -- an absent
    degradation.json yields mode=NORMAL with no triggers, never a fabricated
    one."""
    st = load_state(root)
    triggers = st.get("triggers") or {}
    return {
        "mode": st.get("mode") or NORMAL,
        "degraded": (st.get("mode") == DEGRADED),
        "triggers": sorted(triggers.keys()),
        "trigger_details": {k: v.get("detail", "") for k, v in triggers.items()},
        "entered_at": st.get("entered_at"),
        "cleared_at": st.get("cleared_at"),
        "adapter_failure_streak": int(st.get("adapter_failure_streak") or 0),
        "degraded_cycles": int(st.get("cycles") or 0),
    }


def blocking_reason(root: Path) -> str:
    """One human-readable line explaining why no judgment call will be made,
    built from the real recorded trigger details."""
    st = load_state(root)
    triggers = st.get("triggers") or {}
    if not triggers:
        return ""
    parts = [f"{name} ({info.get('detail', '')})" for name, info in sorted(triggers.items())]
    return ("DEGRADED: collecting data only, no judgment-requiring stage transition attempted "
            "until the condition clears -- " + "; ".join(parts))
