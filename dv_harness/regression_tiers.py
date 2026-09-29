"""dv_harness/regression_tiers.py -- tiered regression cadence
(SMOKE / NIGHTLY / WEEKLY), 2026-09-04.

GAP THIS CLOSES (audited this session, Section 3 item 3c "資源與成本的自主管理
-- 分層 regression"): regression in this harness was FLAT. One submission
mechanism (Stage.REGRESSION + regression_submission_policy_gate), one
escalation config, one threshold (`escalation_notify.EscalationConfig.
uvm_fatal_burst_threshold = 3`) applied identically no matter what kind of
run produced the burst. The only occurrence of the word "nightly" anywhere in
the repo was a bare bullet in `.claude/skills/CORE/devops-pipeline/SKILL.md`
line 61 -- prose, no thresholds, no budget, no code.

WHAT THIS IS NOT: `dv_harness/qualification.py`'s SMOKE_QUALIFIED /
REGRESSION_QUALIFIED / PRODUCTION_QUALIFIED ladder is a protocol MATURITY
state machine ("has this protocol been proven to a given confidence level at
all"). It is deliberately untouched here and shares no code with this module:
a tier is a recurring CADENCE + cost envelope, and the two answer different
questions. The name overlap is unavoidable domain vocabulary, not a
duplication.

THE THREE REAL KNOBS a tier owns, and only these three:
  1. WHICH TESTS -- expressed as which `change_impact` selection classes the
     tier admits (see `TierPolicy.selection_classes` / `tests_for_tier()`).
     SMOKE deliberately admits NO impact-derived class: it is the fixed
     sanity/critical-path set, which is exactly `verification-change-impact/
     SKILL.md`'s own definition of SAFETY ("固定 smoke/sanity/critical-path
     regression, 防止 impact model 漏判") -- a tier whose whole job is to be
     independent of the impact model cannot be selected by it.
  2. TIME BUDGET -- `time_budget_minutes`, the cost envelope the cadence is
     sized for. This module RECORDS and REPORTS the budget (it is what makes
     "fast subset on a 10-minute budget" a real, checkable number rather
     than prose); it does not kill jobs. Job kill/timeout already has a real
     owner -- `lsf_client`'s auto-kill scan -- and duplicating that here
     would create two mechanisms racing for the same decision.
  3. ESCALATION THRESHOLD -- `uvm_fatal_burst_threshold`, per tier.

THRESHOLD DIRECTION (why SMOKE is 1 and WEEKLY is 5). The existing flat
default of 3 was justified against a NIGHTLY-sized batch (see
EscalationConfig's own docstring: "THREE OR MORE jobs in the SAME
reconciliation cycle ... strongly suggests a systemic cause"). That
justification is a statement about the FRACTION of a batch that failed, so
holding the absolute count fixed across batch sizes is what is actually
wrong:
  - SMOKE is a handful of fixed sanity patterns that are expected to pass
    every single time. ONE UVM_FATAL there is already the systemic signal --
    waiting for a third in a set that may only have five members means the
    escalation can never fire before the whole (short) run is over.
  - NIGHTLY keeps 3, byte-for-byte the pre-existing default, so wiring a
    tier in changes nothing for the batch size that number was chosen for.
  - WEEKLY is the widest run (full universe, long tail of rarely-exercised
    patterns); 3 isolated fatals across thousands of jobs is the routine
    debug noise the existing docstring already says is NOT escalation-worthy.
Every one of these is a default, overridable per project via
`.dv-harness/config.json` -- never hardcoded deeper than this module.

THE ACTIVE-TIER RECORD. `record_active_tier()` writes
`.dv-harness/regression/active_tier.json` when a tiered run is launched, and
`escalation_notify`/`regression_reporter` read it to pick the right
threshold. It is a real file rather than a threaded parameter for the same
reason `regression_reporter._escalate_uvm_fatal_burst_if_needed()` reads
config.json fresh each cycle instead of threading a notifier through
ensure_watcher_running()/_run_one_cycle()/main(): the watcher process that
observes the burst is not the process that launched the regression. NO
active-tier record means NO tier -- callers fall back to the flat
pre-existing threshold, so an un-migrated project behaves exactly as before.

CADENCE / SCHEDULING. This module defines the cadence (`TierPolicy.cadence`)
and `dv-harness regression-tier` executes one tier on demand. The recurring
TRIGGER is deliberately external and documented rather than a daemon this
harness owns -- see the `regression-smoke`/`regression-nightly`/
`regression-weekly` recipes in this repo's justfile and the cron/Task
Scheduler lines documented there. HONEST DISCLOSURE: no cron entry is
installed by this module; installing one is a machine-level act outside this
repo, and claiming otherwise would be exactly the fabricated-evidence
failure this project's Evidence Truth Rule forbids.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _now() -> str:
    """Same UTC-ISO stamp `control_plane.now()`/`engine.now()` already use --
    duplicated as a 2-line local helper rather than imported, so this module
    stays importable (e.g. by a gate subprocess) without pulling the engine
    or the control plane in."""
    return datetime.now(timezone.utc).isoformat()

# --- selection classes ----------------------------------------------------
# The four categories Stage.REGRESSION_SELECT's own evidence block already
# uses (prompts.py: targeted_tests / dependency_tests / safety_tests /
# mandatory_signoff_tests) and that dv_harness/change_impact.py computes.
# Named here as constants so a tier policy can reference them without
# re-typing string literals in two modules.
CLASS_TARGETED = "TARGETED"
CLASS_DEPENDENCY = "DEPENDENCY"
CLASS_SAFETY = "SAFETY"
CLASS_MANDATORY = "MANDATORY_SIGNOFF"

# selection-class -> the key it occupies in a REGRESSION_SELECT evidence
# payload / change_impact.select_regression() result.
CLASS_TO_EVIDENCE_KEY: Dict[str, str] = {
    CLASS_TARGETED: "targeted_tests",
    CLASS_DEPENDENCY: "dependency_tests",
    CLASS_SAFETY: "safety_tests",
    CLASS_MANDATORY: "mandatory_signoff_tests",
}


class RegressionTier(str, Enum):
    """`str` mixin so a tier round-trips through JSON/CSV/config as its own
    plain name -- the same convention dv_harness.models.Stage uses."""

    SMOKE = "SMOKE"
    NIGHTLY = "NIGHTLY"
    WEEKLY = "WEEKLY"


def coerce_tier(value: Any) -> RegressionTier:
    """Accepts a RegressionTier, its name, or its lowercase form. Raises
    ValueError for anything else -- an unknown tier must never silently
    fall back to a default one, or a typo in a cron line would quietly run
    (and escalate like) the wrong cadence."""
    if isinstance(value, RegressionTier):
        return value
    name = str(value or "").strip().upper()
    try:
        return RegressionTier(name)
    except ValueError:
        raise ValueError(
            f"Unknown regression tier {value!r}; must be one of "
            f"{[t.value for t in RegressionTier]}"
        ) from None


@dataclass
class TierPolicy:
    """One tier's complete, overridable policy. `full_regression` means the
    tier ignores impact-derived narrowing entirely and runs the whole known
    pattern universe -- the "nothing may be skipped this week" backstop that
    makes it safe for the other two tiers to narrow at all."""

    tier: str
    cadence: str
    time_budget_minutes: int
    selection_classes: Tuple[str, ...]
    uvm_fatal_burst_threshold: int
    full_regression: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["selection_classes"] = list(self.selection_classes)
        return d


DEFAULT_TIER_POLICIES: Dict[str, TierPolicy] = {
    RegressionTier.SMOKE.value: TierPolicy(
        tier=RegressionTier.SMOKE.value,
        cadence="per-change (pre-submit / post-push)",
        time_budget_minutes=10,
        selection_classes=(CLASS_SAFETY, CLASS_MANDATORY),
        uvm_fatal_burst_threshold=1,
    ),
    RegressionTier.NIGHTLY.value: TierPolicy(
        tier=RegressionTier.NIGHTLY.value,
        cadence="daily",
        time_budget_minutes=240,
        selection_classes=(CLASS_TARGETED, CLASS_DEPENDENCY, CLASS_SAFETY, CLASS_MANDATORY),
        uvm_fatal_burst_threshold=3,  # == the pre-existing flat default
    ),
    RegressionTier.WEEKLY.value: TierPolicy(
        tier=RegressionTier.WEEKLY.value,
        cadence="weekly",
        time_budget_minutes=1440,
        selection_classes=(CLASS_TARGETED, CLASS_DEPENDENCY, CLASS_SAFETY, CLASS_MANDATORY),
        uvm_fatal_burst_threshold=5,
        full_regression=True,
    ),
}

_TIER_POLICY_FIELDS = set(TierPolicy.__dataclass_fields__.keys())

# `.dv-harness/config.json` block this module reads. Same forward-compatible
# "unknown keys ignored" convention as preflight/pueue/escalation configs.
CONFIG_KEY = "regression_tiers"


def policy_for(tier: Any, cfg: Optional[dict] = None) -> TierPolicy:
    """The effective policy for one tier: the module default above, with
    `cfg[CONFIG_KEY][<TIER>]`'s keys overlaid. `cfg` is the whole
    `.dv-harness/config.json` dict (or just the `regression_tiers` block --
    both shapes are accepted, since callers hold one or the other).
    Unknown keys are ignored; `tier`/`selection_classes` supplied as a list
    are normalized."""
    t = coerce_tier(tier)
    base = DEFAULT_TIER_POLICIES[t.value]
    block: Dict[str, Any] = {}
    if isinstance(cfg, dict):
        raw = cfg.get(CONFIG_KEY, cfg)
        if isinstance(raw, dict) and isinstance(raw.get(t.value), dict):
            block = dict(raw[t.value])
    merged = base.to_dict()
    for k, v in block.items():
        if k in _TIER_POLICY_FIELDS and k != "tier" and v is not None:
            merged[k] = v
    merged["tier"] = t.value
    merged["selection_classes"] = tuple(merged.get("selection_classes") or ())
    return TierPolicy(**merged)


def all_policies(cfg: Optional[dict] = None) -> Dict[str, TierPolicy]:
    return {t.value: policy_for(t, cfg) for t in RegressionTier}


# --- test-set resolution --------------------------------------------------


def tests_for_tier(tier: Any, selection: Optional[dict] = None, *,
                    cfg: Optional[dict] = None,
                    full_pattern_universe: Optional[Sequence[str]] = None) -> dict:
    """Resolve the concrete pattern list one tier runs.

    `selection` is a `change_impact.select_regression()` result (or any dict
    carrying the same four `*_tests` keys -- e.g. a REGRESSION_SELECT
    evidence payload). `full_pattern_universe` is every pattern the project
    knows about (change_impact.full_pattern_universe()); it is used ONLY by
    a `full_regression` tier, and its absence there is reported honestly
    (`full_universe_available: False`) rather than silently degrading a
    WEEKLY run into a narrowed one without saying so.

    Returns a dict with the resolved `tests`, the per-class breakdown that
    produced them, and the policy actually applied -- everything a caller
    needs to write an auditable record of why this run had these jobs in it.
    """
    policy = policy_for(tier, cfg)
    selection = selection or {}
    by_class: Dict[str, List[str]] = {}
    for cls in policy.selection_classes:
        key = CLASS_TO_EVIDENCE_KEY[cls]
        by_class[cls] = [str(x) for x in (selection.get(key) or [])]

    ordered: List[str] = []
    seen = set()
    for cls in policy.selection_classes:
        for name in by_class[cls]:
            if name not in seen:
                seen.add(name)
                ordered.append(name)

    universe = [str(x) for x in (full_pattern_universe or [])]
    if policy.full_regression:
        for name in universe:
            if name not in seen:
                seen.add(name)
                ordered.append(name)

    return {
        "tier": policy.tier,
        "policy": policy.to_dict(),
        "tests": ordered,
        "by_class": by_class,
        "full_regression": policy.full_regression,
        "full_universe_available": bool(universe),
        "full_universe_size": len(universe),
    }


# --- active-tier record ---------------------------------------------------

ACTIVE_TIER_PATH_PARTS = (".dv-harness", "regression", "active_tier.json")


def active_tier_path(root: Path) -> Path:
    return Path(root).joinpath(*ACTIVE_TIER_PATH_PARTS)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Same atomic-replace discipline as question_queue._atomic_write_json:
    the escalation path reads this file from a DIFFERENT process (the
    lsf-watch reconciliation loop), so a half-written file must never be
    observable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_active_tier(root: Path, tier: Any, *, cfg: Optional[dict] = None,
                        tests: Optional[Sequence[str]] = None,
                        selection_evidence_id: Optional[str] = None,
                        started_at: Optional[str] = None) -> dict:
    """Declare which tier the regression now being submitted belongs to.
    Returns the record it wrote."""
    policy = policy_for(tier, cfg)
    record = {
        "tier": policy.tier,
        "policy": policy.to_dict(),
        "started_at": started_at or _now(),
        "tests": [str(x) for x in (tests or [])],
        "test_count": len(tests or []),
        "selection_evidence_id": selection_evidence_id,
    }
    _atomic_write_json(active_tier_path(root), record)
    return record


def read_active_tier(root: Path) -> Optional[dict]:
    """The active-tier record, or None when no tiered run has been declared.
    Never raises -- a corrupt/partially-written file degrades to None (i.e.
    the flat pre-existing threshold), never to an exception inside the
    escalation path it feeds."""
    p = active_tier_path(root)
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("tier") else None


def clear_active_tier(root: Path) -> bool:
    p = active_tier_path(root)
    try:
        p.unlink()
        return True
    except OSError:
        return False


def active_uvm_fatal_burst_threshold(root: Path, cfg: Optional[dict] = None) -> Optional[int]:
    """The per-tier UVM_FATAL burst threshold for whatever tier is currently
    active, or None when no tier is active. `None` is the signal to the
    caller (`escalation_notify`) to keep using the flat
    `EscalationConfig.uvm_fatal_burst_threshold` exactly as before."""
    record = read_active_tier(root)
    if not record:
        return None
    try:
        policy = policy_for(record["tier"], cfg)
    except ValueError:
        return None
    # An explicitly recorded threshold on the record itself wins over a
    # later config edit: the run that is being observed was launched under
    # the policy stamped into its own record, and re-reading config mid-run
    # would judge it by a threshold nobody agreed to when it started.
    recorded = (record.get("policy") or {}).get("uvm_fatal_burst_threshold")
    if isinstance(recorded, int) and recorded > 0:
        return recorded
    return policy.uvm_fatal_burst_threshold


def render_tier_table(cfg: Optional[dict] = None) -> str:
    """Human-readable `dv-harness regression-tier list` output."""
    rows = [("TIER", "CADENCE", "BUDGET(min)", "UVM_FATAL", "CLASSES")]
    for t in RegressionTier:
        p = policy_for(t, cfg)
        classes = "FULL+" + ",".join(p.selection_classes) if p.full_regression else ",".join(p.selection_classes)
        rows.append((p.tier, p.cadence, str(p.time_budget_minutes),
                     str(p.uvm_fatal_burst_threshold), classes))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in rows)
