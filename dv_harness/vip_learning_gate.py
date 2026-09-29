"""dv_harness/vip_learning_gate.py -- the VIP Learning Gate: ONE pre-generation
checkpoint that assembles four ALREADY-REAL signals into a single PASS/BLOCKED
verdict, so a generator has one place to ask "is it safe to generate now"
instead of an agent having to remember to run four separate checks and reason
about how their four separate vocabularies combine.

THE GAP THIS CLOSES
-------------------
`vip_api_card.py` (2026-09-06), `phy_boundary.py` (2026-09-04),
`connectivity.enforce_bind_tier_policy()` (2026-09-04) and
`env_manifest.py`'s `vip_config` layer (2026-09-04) each already answer their
own real question, each already fails closed on its own, and each is already
wired into ITS OWN generation path (`create_environment()` for the first,
`bind_mechanism_generator.emit_bind_sv()` for the second and third). What did
not exist anywhere was a SINGLE consolidated checkpoint an agent (or a future
engine call site) could run once, before generation, and get back one
PASS/BLOCKED answer naming exactly which of the four is the reason -- a
repo-wide grep for `vip_learning_gate`/`learning_gate`/`pre_generation_gate`
matched nothing executable. Without it, "did we check everything before
generating" was four separate manual invocations an agent had to remember,
in four different CLI shapes, with no single artifact recording that all
four were actually run together for this generation attempt.

REUSE, NOT REINVENTION -- every sub-check below calls the REAL function and
reports that module's OWN real status verbatim; nothing here re-derives a
fact any of those four modules already computes:

  * `vip_api_card.validate_vip_api_usage()` -- its own PROVEN / BLOCKED /
    UNPROVABLE / NOT_AVAILABLE vocabulary, read here, not re-derived. Per
    that module's own documented statuses: BLOCKED is the narrow, hard claim
    ("provably absent" -- see its docstring for the four conditions that must
    ALL hold before it fires) and is what BLOCKS this gate; UNPROVABLE is
    section 187's "UNKNOWN" -- not a pass, but also not a hard block on its
    own, so it surfaces here as a WARNING a human must still see, never
    silently dropped and never escalated into a block this gate's own task
    did not ask for.
  * `phy_boundary.assert_bind_location_allowed()` -- the REAL consumer gate
    that module already ships, which raises exactly when the boundary is not
    `EXTRACTED` (not decided) or not `bindable` (UNDECIDABLE, or a SERIAL-only
    boundary a monitor cannot decode). This module does not re-implement that
    decision; it calls the function and reports whether it raised.
  * `connectivity.enforce_bind_tier_policy()` -- the REAL whole-list bind-tier
    gate: raises `BindTierError` on the FIRST T4 entry (must go to the
    question queue, never emitted) or T3 entry lacking a real
    `question_queue.HUMAN_DECISION_SOURCE` confirmation. This module calls it
    once over the supplied bind entries and reports whether it raised.
  * `env_manifest.load_env_manifest()` -- loads and schema-validates a real
    `env.manifest.json`; this module reads that manifest's OWN `vip_config`
    layer `status`/`reason` verbatim (`"NOT_AVAILABLE"` vs `"CAPTURED"`,
    `build_vip_config_layer()`'s own vocabulary) rather than re-deriving
    whether a VIP config dump exists.

WHAT "IN SCOPE" MEANS, AND WHY ABSENCE IS NOT A BLOCK
------------------------------------------------------
Not every generation attempt has all four signals to check: an IP-level DUT
with no PHY sub-block genuinely has no boundary to decide
(`phy_boundary.py`'s own disclosed residual), and a generation run that binds
nothing yet has no bind entries to classify. Per the Evidence Truth Rule, an
absent signal is reported as an honest, DISTINCT status -- never silently
skipped and never conflated with a clean PASS:

  * `NOT_APPLICABLE` -- the caller supplied nothing for this sub-check, and
    that is a legitimate "not in scope for this generation" answer (no PHY
    boundary declared, no bind entries supplied, no VIP source/index pair to
    validate).
  * `NOT_AVAILABLE` -- something WAS supplied but the sub-check's own real
    function could not produce a decided answer from it (a malformed
    document, a boundary that failed to extract, a `vip_config` layer that is
    itself `NOT_AVAILABLE` for its own real reason). This is never treated as
    a pass.
  * `WARNING` -- a real, non-blocking finding this gate does not escalate
    (today, only `vip_api_card`'s UNPROVABLE).
  * `BLOCKING` -- the specific, real reason this generation attempt must
    stop.
  * `CLEAN` -- the sub-check ran and found nothing wrong.

The composite verdict is `BLOCKED` if and only if at least one sub-check is
`BLOCKING`, naming exactly which. It is `NOT_AVAILABLE` when NOTHING could be
evaluated at all (every sub-check `NOT_APPLICABLE`/`NOT_AVAILABLE` -- nobody
supplied anything real to check). Otherwise it is `PASS`, carrying any
`WARNING`s forward rather than hiding them.

WHAT THIS DOES NOT DO
----------------------
It decides nothing beyond reporting, and it authorizes nothing: no build, no
job, no approval, no memory write, no stage gate. `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()`, `HumanApprovalRequiredError`
and `ProductionWriteNotAuthorizedError` are untouched and unreferenced. It
also does not re-implement any of the four sub-checks' own judgment: a BLOCKED
vip_api_card finding is BLOCKED for the reasons that module's own docstring
gives, not a reason invented here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import connectivity, env_manifest, phy_boundary, vip_api_card

SCHEMA_VERSION = "1.0"

# Per-sub-check status vocabulary. Five distinct tokens, never collapsed:
# see module docstring's "WHAT 'IN SCOPE' MEANS" section for what each means.
CLEAN = "CLEAN"
BLOCKING = "BLOCKING"
WARNING = "WARNING"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_AVAILABLE = "NOT_AVAILABLE"

SUBCHECK_STATUSES = frozenset({CLEAN, BLOCKING, WARNING, NOT_APPLICABLE, NOT_AVAILABLE})

# Composite verdict vocabulary. Deliberately disjoint from
# `dv_harness.models.Status` (this gate persists no member of that
# vocabulary) and from the four sub-checks' own per-module vocabularies.
PASS = "PASS"
BLOCKED = "BLOCKED"
GATE_NOT_AVAILABLE = "NOT_AVAILABLE"

GATE_VERDICTS = frozenset({PASS, BLOCKED, GATE_NOT_AVAILABLE})

# The four sub-check names, in the fixed order they are always reported --
# a stable order makes a rendered report diffable run to run.
CHECK_VIP_API_CARD = "vip_api_card"
CHECK_PHY_BOUNDARY = "phy_boundary"
CHECK_BIND_TIER = "bind_tier"
CHECK_VIP_CONFIG_LAYER = "vip_config_layer"
CHECK_NAMES = (CHECK_VIP_API_CARD, CHECK_PHY_BOUNDARY, CHECK_BIND_TIER, CHECK_VIP_CONFIG_LAYER)


@dataclass
class SubCheckResult:
    name: str
    status: str
    reason: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VipLearningGateReport:
    verdict: str
    reason: Optional[str] = None
    blocking_checks: List[str] = field(default_factory=list)
    warning_checks: List[str] = field(default_factory=list)
    sub_checks: List[SubCheckResult] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["sub_checks"] = [c.to_dict() for c in self.sub_checks]
        return d

    def get(self, name: str) -> Optional[SubCheckResult]:
        for c in self.sub_checks:
            if c.name == name:
                return c
        return None


# ---------------------------------------------------------------------------
# sub-check 1: vip_api_card.py -- zero BLOCKED, UNPROVABLE is a warning
# ---------------------------------------------------------------------------

def check_vip_api_card(*, sources: Optional[Sequence] = None,
                       index: Optional[dict] = None,
                       index_path: Optional[Any] = None,
                       relative_to: Optional[Any] = None) -> SubCheckResult:
    """Calls `vip_api_card.validate_vip_api_usage()` -- never re-implements
    its BLOCKED/UNPROVABLE/PROVEN judgment -- and reports its real `status`
    verbatim. BLOCKED findings block this gate; UNPROVABLE findings are
    reported as a WARNING, per that module's own documented statuses."""
    if sources is None and index is None and index_path is None:
        return SubCheckResult(CHECK_VIP_API_CARD, NOT_APPLICABLE,
                              reason="no VIP sources/index supplied for this generation run "
                                     "-- no VIP API citations in scope to validate")
    if index is None:
        if index_path is None:
            return SubCheckResult(CHECK_VIP_API_CARD, NOT_AVAILABLE,
                                  reason="VIP sources were supplied but no vip_symbol_index "
                                         "was given to validate them against")
        try:
            index = vip_api_card.load_index(index_path)
        except (OSError, ValueError) as exc:
            return SubCheckResult(CHECK_VIP_API_CARD, NOT_AVAILABLE, reason=str(exc))
    if sources is None:
        return SubCheckResult(CHECK_VIP_API_CARD, NOT_AVAILABLE,
                              reason="a vip_symbol_index was supplied but no generated sources "
                                     "were given to validate against it")

    try:
        report = vip_api_card.validate_vip_api_usage(sources, index, relative_to=relative_to)
    except (OSError, ValueError) as exc:
        return SubCheckResult(CHECK_VIP_API_CARD, NOT_AVAILABLE, reason=str(exc))

    detail = {"status": report.status, "counts": dict(report.counts),
              "files_scanned": report.files_scanned, "protocol": report.protocol}
    if report.status == vip_api_card.PROVEN:
        return SubCheckResult(CHECK_VIP_API_CARD, CLEAN, detail=detail)
    if report.status == vip_api_card.BLOCKED:
        blocked = report.blocked()
        detail["blocked_citations"] = [c.citation for c in blocked]
        return SubCheckResult(
            CHECK_VIP_API_CARD, BLOCKING,
            reason=f"{len(blocked)} VIP API citation(s) BLOCKED (provably absent from the "
                   f"indexed VIP symbol index): {[c.citation for c in blocked]}",
            detail=detail,
        )
    if report.status == vip_api_card.UNPROVABLE:
        unprovable = report.unprovable()
        detail["unprovable_citations"] = [c.citation for c in unprovable]
        return SubCheckResult(
            CHECK_VIP_API_CARD, WARNING,
            reason=f"{len(unprovable)} VIP API citation(s) UNPROVABLE (section 187's UNKNOWN) "
                   f"-- not a block, but not proven either: {[c.citation for c in unprovable]}",
            detail=detail,
        )
    # report.status == vip_api_card.NOT_AVAILABLE
    return SubCheckResult(CHECK_VIP_API_CARD, NOT_AVAILABLE, reason=report.reason, detail=detail)


# ---------------------------------------------------------------------------
# sub-check 2: phy_boundary.py -- must be DECIDED (bindable), not UNDECIDABLE,
# when a boundary is in scope
# ---------------------------------------------------------------------------

def check_phy_boundary(*, doc: Optional[dict] = None,
                       doc_path: Optional[Any] = None) -> SubCheckResult:
    """Calls `phy_boundary.assert_bind_location_allowed()` -- the real
    consumer gate that module already ships -- and reports whether it
    raised. Never re-derives the serial/parallel classification itself."""
    if doc is None and doc_path is None:
        return SubCheckResult(CHECK_PHY_BOUNDARY, NOT_APPLICABLE,
                              reason="no phy_boundary document supplied -- no PHY boundary "
                                     "declared in scope for this generation run")
    if doc is None:
        try:
            doc = phy_boundary.load_phy_boundary(doc_path)
        except (OSError, ValueError) as exc:
            return SubCheckResult(CHECK_PHY_BOUNDARY, NOT_AVAILABLE, reason=str(exc))

    classification = doc.get("classification") or {}
    bind_decision = doc.get("bind_decision") or {}
    detail = {"status": doc.get("status"), "classification_kind": classification.get("kind"),
              "mount_layer": bind_decision.get("mount_layer")}

    if doc.get("status") != "EXTRACTED":
        detail["status"] = doc.get("status")
        return SubCheckResult(CHECK_PHY_BOUNDARY, NOT_AVAILABLE,
                              reason=doc.get("reason") or "phy_boundary document status is not "
                                     "EXTRACTED", detail=detail)

    try:
        phy_boundary.assert_bind_location_allowed(doc)
    except phy_boundary.PhyBoundaryValidationError as exc:
        return SubCheckResult(CHECK_PHY_BOUNDARY, BLOCKING, reason=str(exc), detail=detail)
    return SubCheckResult(CHECK_PHY_BOUNDARY, CLEAN, detail=detail)


# ---------------------------------------------------------------------------
# sub-check 3: connectivity.py -- no unresolved T3-without-human-confirmation
# or T4 entries
# ---------------------------------------------------------------------------

def check_bind_tier(*, bind_entries: Optional[list] = None,
                    bind_entries_path: Optional[Any] = None,
                    require_tier: bool = False) -> SubCheckResult:
    """Calls `connectivity.enforce_bind_tier_policy()` -- the real whole-list
    bind-tier gate -- over the supplied bind entries, and reports whether it
    raised `BindTierError` (a T4 entry, or a T3 entry lacking a real human
    confirmation). Never re-implements tier classification itself."""
    if bind_entries is None and bind_entries_path is None:
        return SubCheckResult(CHECK_BIND_TIER, NOT_APPLICABLE,
                              reason="no bind entries supplied -- no bind-location decisions "
                                     "in scope for this generation run")
    if bind_entries is None:
        try:
            bind_entries = json.loads(Path(bind_entries_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return SubCheckResult(CHECK_BIND_TIER, NOT_AVAILABLE,
                                  reason=f"could not read bind entries from {bind_entries_path!r}: {exc}")
    if not bind_entries:
        return SubCheckResult(CHECK_BIND_TIER, NOT_APPLICABLE,
                              reason="bind entries list is empty -- no bind-location decisions "
                                     "in scope for this generation run")

    try:
        decisions = connectivity.enforce_bind_tier_policy(bind_entries, require_tier=require_tier)
    except connectivity.BindTierError as exc:
        return SubCheckResult(CHECK_BIND_TIER, BLOCKING, reason=exc.reason, detail=dict(exc.detail))
    return SubCheckResult(CHECK_BIND_TIER, CLEAN, detail={"decisions": decisions})


# ---------------------------------------------------------------------------
# sub-check 4: env_manifest.py -- vip_config layer must not be NOT_AVAILABLE
# ---------------------------------------------------------------------------

def check_vip_config_layer(*, manifest: Optional[dict] = None,
                           manifest_path: Optional[Any] = None) -> SubCheckResult:
    """Reads `env.manifest.json`'s own `vip_config` layer `status`/`reason`
    verbatim (`build_vip_config_layer()`'s real vocabulary) -- never
    re-derives whether a VIP config dump exists."""
    if manifest is None and manifest_path is None:
        return SubCheckResult(CHECK_VIP_CONFIG_LAYER, NOT_AVAILABLE,
                              reason="no env.manifest.json supplied -- cannot determine the "
                                     "vip_config layer's real status")
    if manifest is None:
        try:
            manifest = env_manifest.load_env_manifest(manifest_path)
        except (OSError, ValueError) as exc:
            return SubCheckResult(CHECK_VIP_CONFIG_LAYER, NOT_AVAILABLE, reason=str(exc))

    vip_config = manifest.get("vip_config") or {}
    status = vip_config.get("status")
    detail = {"status": status, "vip_instances": len(vip_config.get("vip_instances") or [])}
    if status == "CAPTURED":
        return SubCheckResult(CHECK_VIP_CONFIG_LAYER, CLEAN, detail=detail)
    if status == "NOT_AVAILABLE":
        return SubCheckResult(CHECK_VIP_CONFIG_LAYER, BLOCKING,
                              reason=vip_config.get("reason") or
                                     "env.manifest.json vip_config layer status is NOT_AVAILABLE",
                              detail=detail)
    return SubCheckResult(CHECK_VIP_CONFIG_LAYER, NOT_AVAILABLE,
                          reason=f"unrecognized vip_config layer status {status!r}", detail=detail)


# ---------------------------------------------------------------------------
# composite: the checkpoint itself
# ---------------------------------------------------------------------------

def run_pre_generation_checkpoint(
    *,
    vip_sources: Optional[Sequence] = None,
    vip_index: Optional[dict] = None,
    vip_index_path: Optional[Any] = None,
    vip_relative_to: Optional[Any] = None,
    phy_boundary_doc: Optional[dict] = None,
    phy_boundary_path: Optional[Any] = None,
    bind_entries: Optional[list] = None,
    bind_entries_path: Optional[Any] = None,
    bind_require_tier: bool = False,
    env_manifest_doc: Optional[dict] = None,
    env_manifest_path: Optional[Any] = None,
) -> VipLearningGateReport:
    """Runs all four sub-checks and folds them into one PASS/BLOCKED/
    NOT_AVAILABLE verdict. BLOCKED whenever any sub-check is BLOCKING, naming
    exactly which; NOT_AVAILABLE only when NOTHING could be evaluated at all
    (every sub-check NOT_APPLICABLE/NOT_AVAILABLE); otherwise PASS, carrying
    forward any WARNING (never silently dropped, never escalated to a
    block)."""
    checks = [
        check_vip_api_card(sources=vip_sources, index=vip_index, index_path=vip_index_path,
                           relative_to=vip_relative_to),
        check_phy_boundary(doc=phy_boundary_doc, doc_path=phy_boundary_path),
        check_bind_tier(bind_entries=bind_entries, bind_entries_path=bind_entries_path,
                        require_tier=bind_require_tier),
        check_vip_config_layer(manifest=env_manifest_doc, manifest_path=env_manifest_path),
    ]
    blocking = [c.name for c in checks if c.status == BLOCKING]
    warnings = [c.name for c in checks if c.status == WARNING]
    evaluated = [c.name for c in checks if c.status in (CLEAN, BLOCKING, WARNING)]

    if blocking:
        verdict, reason = BLOCKED, None
    elif not evaluated:
        verdict = GATE_NOT_AVAILABLE
        reason = ("no sub-check had real evidence to evaluate for this generation run -- "
                  "every one of vip_api_card/phy_boundary/bind_tier/vip_config_layer was "
                  "NOT_APPLICABLE or NOT_AVAILABLE")
    else:
        verdict, reason = PASS, None

    return VipLearningGateReport(verdict=verdict, reason=reason, blocking_checks=blocking,
                                 warning_checks=warnings, sub_checks=checks)


def format_report(report: VipLearningGateReport) -> str:
    """Human-readable rendering. Every sub-check's own real status and reason
    is printed, so the composite verdict is never a bare word with no
    evidence behind it."""
    lines = [f"VIP Learning Gate: {report.verdict}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.blocking_checks:
        lines.append(f"  blocking sub-check(s): {', '.join(report.blocking_checks)}")
    if report.warning_checks:
        lines.append(f"  warning sub-check(s): {', '.join(report.warning_checks)}")
    lines.append("")
    for c in report.sub_checks:
        lines.append(f"  [{c.status}] {c.name}")
        if c.reason:
            lines.append(f"      reason: {c.reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: `python -m dv_harness.vip_learning_gate`
# ---------------------------------------------------------------------------

def execute_verb(*, vip_sources=None, vip_index_path=None, vip_relative_to=None,
                 phy_boundary_path=None, bind_entries_path=None, bind_require_tier=False,
                 env_manifest_path=None, as_json: bool = False) -> "tuple[str, int]":
    """Shared implementation for `python -m dv_harness.vip_learning_gate` (and
    a future `dv-harness` subcommand, should one be wired). Returns
    (text, exit_code): 0 PASS, 1 BLOCKED, 2 NOT_AVAILABLE."""
    report = run_pre_generation_checkpoint(
        vip_sources=vip_sources, vip_index_path=vip_index_path, vip_relative_to=vip_relative_to,
        phy_boundary_path=phy_boundary_path,
        bind_entries_path=bind_entries_path, bind_require_tier=bind_require_tier,
        env_manifest_path=env_manifest_path,
    )
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    code = {PASS: 0, BLOCKED: 1, GATE_NOT_AVAILABLE: 2}[report.verdict]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.vip_learning_gate",
        description="VIP Learning Gate: one pre-generation checkpoint over four already-real "
                    "signals -- vip_api_card.py, phy_boundary.py, connectivity.py bind-tier "
                    "resolution and env_manifest.py's vip_config layer.")
    ap.add_argument("--vip-source", action="append", dest="vip_sources", default=None,
                    help="Generated .sv/.svh source or directory to VIP-API-validate (repeatable).")
    ap.add_argument("--vip-index", default=None, help="vip_symbol_index JSON document.")
    ap.add_argument("--vip-relative-to", default=None, help="Root for reported VIP API usage paths.")
    ap.add_argument("--phy-boundary", default=None, help="A real phy_boundary.json document.")
    ap.add_argument("--bind-entries", default=None, help="A JSON file: a list of bind entries.")
    ap.add_argument("--require-tier", action="store_true",
                    help="Also refuse a bind entry carrying no tier at all (see connectivity.py).")
    ap.add_argument("--env-manifest", default=None, help="A real env.manifest.json document.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        vip_sources=a.vip_sources, vip_index_path=a.vip_index, vip_relative_to=a.vip_relative_to,
        phy_boundary_path=a.phy_boundary,
        bind_entries_path=a.bind_entries, bind_require_tier=a.require_tier,
        env_manifest_path=a.env_manifest, as_json=a.json,
    )
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
