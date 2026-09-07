"""dv_harness/gen_code_quality_gate.py -- the Generated-Code Quality Gate
(spec section 221, 2026-09-06).

THE GAP THIS CLOSES
--------------------
Two real, independently-built checks already run against generated UVM/SV
artifacts and each answers its own question honestly:

  * `uvm_structural_lint.py` (section 220) parses generated `.sv`/`.svh` with
    the real verible front end and reports PASS/FAIL/NOT_AVAILABLE from real
    ERROR findings (missing factory registration, wrong phase-method
    signature, an unconnected TLM port, an unbalanced objection, ...).
  * `vip_api_card.py` (section 187) resolves every VIP API citation a
    generated source makes against a real `vip_symbol_index` and reports
    PROVEN / BLOCKED / UNPROVABLE / NOT_AVAILABLE -- BLOCKED being the
    provable-fabrication case: a VIP class/method the index proves does not
    exist.

Before this module, nothing joined the two into one composite verdict. A
caller wanting "is this generated environment's CODE actually good" had to
open two separate reports by hand and apply the worst-wins reasoning
themselves -- and re-deriving even a small approximation of either check here
(instead of reusing the real one) would be exactly the "several very similar
-sounding capabilities already exist" duplication this project's own house
style forbids. Repo-wide search before writing this confirmed the gap: no
module imports BOTH `uvm_structural_lint` and `vip_api_card` for a single
two-input composite fold (`subsystem_maturity_gate.py` uses `vip_api_card`
alone as one of six unrelated conditions and never touches
`uvm_structural_lint` at all; `vip_learning_gate.py` is a PRE-generation VIP
checkpoint over four different sources and likewise never touches
`uvm_structural_lint`).

WHAT THIS MODULE IS -- AND IS NOT
-----------------------------------
It is a thin composite: two conditions, each read verbatim off one real
report's own already-computed `status`/`findings`/`cards` fields, folded
worst-wins into one PASS/FAIL/INCOMPLETE_EVIDENCE verdict. It reuses
`uvm_structural_lint.lint_uvm_environment()`/`lint_uvm_sources()` and
`vip_api_card.validate_vip_api_usage()` -- called AT MOST ONCE each, and only
when a caller has not already supplied a report -- and never re-implements
one line of either module's own parsing/resolution logic. It is not a third
lint, not a second VIP-API validator, and it derives no new fact about a
generated source that those two modules did not already compute.

THE WORST-WINS FOLD (this project's mandatory rule for a gate/rollup item)
----------------------------------------------------------------------------
Two conditions, `STRUCTURAL_LINT_CLEAN` and `VIP_API_NO_BLOCKED_CITATIONS`,
each classified MET / UNMET / UNKNOWN / NOT_APPLICABLE from its own real
report:

  STRUCTURAL_LINT_CLEAN
    MET             `uvm_structural_lint`'s own `status == "PASS"` (real
                     ERROR-severity finding count is exactly zero).
    UNMET           `status == "FAIL"` -- at least one real ERROR finding
                     (factory registration missing, wrong phase signature, an
                     unconnected TLM port, an unbalanced objection, ...),
                     each carried through with its own rule/file/line/message.
    UNKNOWN         `status == "NOT_AVAILABLE"` -- verible could not be run,
                     or there was nothing to lint at all. "We could not
                     check" is never read as clean.

  VIP_API_NO_BLOCKED_CITATIONS
    MET             `vip_api_card`'s own `status == "PROVEN"` -- every VIP
                     API citation resolved to a real declaration, zero
                     BLOCKED and zero UNPROVABLE.
    UNMET           `status == "BLOCKED"` -- at least one citation the real
                     VIP symbol index PROVES does not exist: a fabricated VIP
                     class or method. This is the condition the task names
                     explicitly ("vip_api_card.py's BLOCKED-citation
                     findings"), and it is the one this module folds on.
    UNKNOWN         `status == "UNPROVABLE"` (section 187's own honest
                     UNKNOWN -- an inheritance chain the index does not fully
                     cover, with zero BLOCKED citations), or a NOT_AVAILABLE
                     whose reason is something other than "there were no VIP
                     API citations to check" (no source files, an empty
                     index, no VIP naming scope derivable). Never silently
                     folded into MET: UNPROVABLE is section 187's own
                     "cannot be proven" state, not a pass.
    NOT_APPLICABLE  `status == "NOT_AVAILABLE"` with reason
                     `NO_VIP_API_CITATIONS_FOUND` -- this generated
                     environment made no VIP API citations at all (a
                     perfectly ordinary DUT-only/no-VIP environment), so the
                     condition legitimately does not apply. NOT_APPLICABLE is
                     the one status that never forces the composite verdict
                     off PASS.

A condition supplied no report at all (the caller passed neither a
pre-computed report nor enough to produce one) is UNKNOWN, honestly, never
defaulted to MET.

`fold_conditions()` is the mandatory worst-wins arithmetic, matching this
project's other composite-gate modules
(`system_readiness_gates.py`/`spec_vplan_readiness_gate.py`/
`functional_coverage_signoff.py`) rather than inventing a fourth shape:

  FAIL                any condition UNMET -- a single real BLOCKED citation
                       or a single real structural-lint ERROR finding fails
                       the WHOLE gate, regardless of how clean the other
                       condition is. Never averaged, never weighted.
  INCOMPLETE_EVIDENCE  no UNMET condition, but at least one condition is
                       UNKNOWN -- insufficient evidence to call this PASS,
                       and a materially different claim from a confirmed
                       FAIL.
  PASS                 every condition is MET or NOT_APPLICABLE. Nothing
                       less.

VOCABULARY
----------
`GATE_PASS`/`GATE_FAIL` deliberately reuse `dv_harness.models.Status.PASS`/
`.FAIL`'s own string values -- the same disclosed, deliberate precedent
`protocol_compliance_aggregation.py` already establishes ("this module's
whole subject IS a pass/fail verdict... reusing the two real verdict words is
correct here rather than a collision to guard against"). The one token this
module ADDS, `GATE_INCOMPLETE_EVIDENCE`, is asserted at import time to share
no token with `dv_harness.models.Status`.

DELIBERATELY BOUNDED, AND STATED RATHER THAN IMPLIED CLOSED
--------------------------------------------------------------
  * It decides, approves and arbitrates nothing beyond its own two-condition
    fold: no build/job/approval is touched, and there is deliberately no
    `gates.py` `STAGE_GATES` entry -- a gate that passed because generated
    code was never actually linted/validated would be worse than none.
  * It never runs verible or the VIP symbol indexer itself beyond the one
    real call each underlying module already makes on its own -- when a
    caller already holds both reports (e.g. from a prior
    `create_environment()` run, which already writes both
    `uvm_structural_lint.json` and `vip_api_cards.json` next to a generated
    environment), this module makes NO call into either module at all.
  * `uvm_structural_lint`'s own WARNING/INFO findings (e.g. an unmatched
    `uvm_config_db` key, a run-time-built key) and `vip_api_card`'s own
    UNPROVABLE citations are surfaced on the condition detail but never on
    their own force a FAIL -- only a real ERROR finding (lint) or a real
    BLOCKED citation (VIP API) does, exactly matching the two source
    modules' own severity contracts.
  * No `dv-harness` CLI verb was added, and `cli.py`/`gates.py` were not
    touched, per this project's own house rule against editing either file
    while it is under heavy concurrent edit pressure from other items in the
    same batch. The front door is this module's own Python API plus
    `python -m dv_harness.gen_code_quality_gate`.

Proven by `dv_harness_tests/test_gen_code_quality_gate.py` against the REAL
`uvm_structural_lint` and `vip_api_card` modules over real synthetic UVM/VIP
fixtures (including the existing shared `demo_env_seq.sv` / `svt_demo_pkg.sv`
fixture pair those two modules' own test suites already use) -- including a
real BLOCKED citation, a real structural-lint ERROR finding, both at once
(worst-wins), a real UNPROVABLE (INCOMPLETE_EVIDENCE, never FAIL), and a
negative control proving this module never re-derives either check: with
both real underlying functions monkeypatched to raise, supplying
already-computed reports directly still folds correctly with neither
function ever called.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import uvm_structural_lint
from . import vip_api_card
from .connectivity import render_markdown_table
from .models import Status

SCHEMA_VERSION = "1.0"

# --- condition-level vocabulary --------------------------------------------
COND_MET = "MET"
COND_UNMET = "UNMET"
COND_UNKNOWN = "UNKNOWN"
COND_NOT_APPLICABLE = "NOT_APPLICABLE"
CONDITION_STATUSES: Tuple[str, ...] = (COND_MET, COND_UNMET, COND_UNKNOWN, COND_NOT_APPLICABLE)

# --- gate-level vocabulary --------------------------------------------------
# PASS/FAIL are a deliberate, disclosed reuse of dv_harness.models.Status's
# own words -- see the module docstring's VOCABULARY section. This module's
# whole subject is itself a pass/fail verdict over generated code.
GATE_PASS = Status.PASS.value
GATE_FAIL = Status.FAIL.value
GATE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: Tuple[str, ...] = (GATE_PASS, GATE_FAIL, GATE_INCOMPLETE_EVIDENCE)

CONDITION_STRUCTURAL_LINT = "STRUCTURAL_LINT_CLEAN"
CONDITION_VIP_API = "VIP_API_NO_BLOCKED_CITATIONS"
CONDITION_NAMES: Tuple[str, ...] = (CONDITION_STRUCTURAL_LINT, CONDITION_VIP_API)


class GenCodeQualityGateError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _assert_incomplete_evidence_disjoint_from_status() -> None:
    """Import-time guard: the one vocabulary token this module ADDS beyond
    its deliberate PASS/FAIL reuse must never collide with a real
    `dv_harness.models.Status` member -- the same guard several sibling
    composite-gate modules already run against their own added tokens."""
    if GATE_INCOMPLETE_EVIDENCE in {member.value for member in Status}:
        raise GenCodeQualityGateError(
            "GATE_INCOMPLETE_EVIDENCE_COLLIDES_WITH_STATUS",
            {"value": GATE_INCOMPLETE_EVIDENCE})


_assert_incomplete_evidence_disjoint_from_status()


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------

@dataclass
class GenCodeQualityCondition:
    name: str
    status: str
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenCodeQualityReport:
    status: str
    reason: str = ""
    conditions: List[GenCodeQualityCondition] = field(default_factory=list)
    structural_lint_status: Optional[str] = None
    vip_api_status: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["conditions"] = [c.to_dict() for c in self.conditions]
        return d

    def condition(self, name: str) -> Optional[GenCodeQualityCondition]:
        for c in self.conditions:
            if c.name == name:
                return c
        return None


# ---------------------------------------------------------------------------
# classification: read each real report's own already-computed fields
# ---------------------------------------------------------------------------

def _condition(name: str, status: str, reason: str, **detail: Any) -> GenCodeQualityCondition:
    if status not in CONDITION_STATUSES:
        raise GenCodeQualityGateError(
            "UNKNOWN_CONDITION_STATUS", {"condition": name, "status": status})
    return GenCodeQualityCondition(name=name, status=status, reason=reason, detail=detail)


def classify_structural_lint_condition(
        report: Optional[uvm_structural_lint.UvmLintReport]) -> GenCodeQualityCondition:
    """`STRUCTURAL_LINT_CLEAN`, read verbatim off a real `UvmLintReport` --
    never a re-parse, never a re-run of any rule. `report` is exactly what
    `uvm_structural_lint.lint_uvm_environment()`/`lint_uvm_sources()` already
    returned (or a caller's own previously-saved one)."""
    if report is None:
        return _condition(
            CONDITION_STRUCTURAL_LINT, COND_UNKNOWN,
            "no uvm_structural_lint report was supplied, and none could be produced "
            "(no env_dir/sources given)")
    if report.status == "PASS":
        return _condition(
            CONDITION_STRUCTURAL_LINT, COND_MET,
            f"uvm_structural_lint PASS over {len(report.files)} file(s), "
            f"{report.classes_analyzed} class(es) analysed, 0 ERROR finding(s)",
            error_count=report.error_count, warning_count=report.warning_count,
            info_count=report.info_count, classes_analyzed=report.classes_analyzed,
            files_scanned=len(report.files))
    if report.status == "FAIL":
        errors = [f.to_dict() for f in report.findings if f.severity == "ERROR"]
        return _condition(
            CONDITION_STRUCTURAL_LINT, COND_UNMET,
            f"uvm_structural_lint FAIL: {report.error_count} real ERROR finding(s) -- "
            + "; ".join(f"{e['rule']} {e['file_path']}:{e['line']}" for e in errors),
            error_count=report.error_count, findings=errors)
    # NOT_AVAILABLE -- verible could not be run, or there was nothing to lint.
    return _condition(
        CONDITION_STRUCTURAL_LINT, COND_UNKNOWN,
        f"uvm_structural_lint NOT_AVAILABLE: {report.reason}",
        reason_code=report.reason)


def classify_vip_api_condition(
        report: Optional[vip_api_card.VipApiValidationReport]) -> GenCodeQualityCondition:
    """`VIP_API_NO_BLOCKED_CITATIONS`, read verbatim off a real
    `VipApiValidationReport` -- never a re-resolution of any citation.
    `report` is exactly what `vip_api_card.validate_vip_api_usage()` already
    returned (or a caller's own previously-saved one)."""
    if report is None:
        return _condition(
            CONDITION_VIP_API, COND_UNKNOWN,
            "no vip_api_card report was supplied, and none could be produced "
            "(no vip_sources/vip_index given)")
    if report.status == vip_api_card.BLOCKED:
        blocked = [c.to_dict() for c in report.blocked()]
        return _condition(
            CONDITION_VIP_API, COND_UNMET,
            f"vip_api_card BLOCKED: {len(blocked)} VIP API citation(s) the real VIP "
            "symbol index proves do not exist -- " + "; ".join(
                f"{c['citation']} [{c['reason']}] at {c['usage_file']}:{c['usage_line']}"
                for c in blocked),
            blocked_count=len(blocked), blocked_cards=blocked)
    if report.status == vip_api_card.PROVEN:
        return _condition(
            CONDITION_VIP_API, COND_MET,
            f"vip_api_card PROVEN: {report.counts.get(vip_api_card.PROVEN, 0)} VIP API "
            "citation(s) resolved to a real declaration, 0 BLOCKED, 0 UNPROVABLE",
            counts=dict(report.counts))
    if report.status == vip_api_card.UNPROVABLE:
        # validate_vip_api_usage() checks BLOCKED before UNPROVABLE, so a real
        # BLOCKED citation is never hiding behind this branch. Section 187's
        # own UNKNOWN is still not a pass -- honestly UNKNOWN here too, never
        # silently folded into MET on the strength of "at least it's not
        # BLOCKED".
        unprovable = [c.to_dict() for c in report.unprovable()]
        return _condition(
            CONDITION_VIP_API, COND_UNKNOWN,
            f"vip_api_card UNPROVABLE: {len(unprovable)} VIP API citation(s) cannot be "
            "decided from the supplied index (0 BLOCKED)",
            unprovable_count=len(unprovable), counts=dict(report.counts))
    # NOT_AVAILABLE. "No VIP API citations at all" is a legitimate, common
    # state (a DUT-only/no-VIP generated environment) and never blocks this
    # gate; every other NOT_AVAILABLE reason (no source files, an empty
    # index, no derivable VIP naming scope) is an honest "we could not check".
    if report.reason == "NO_VIP_API_CITATIONS_FOUND":
        return _condition(
            CONDITION_VIP_API, COND_NOT_APPLICABLE,
            "vip_api_card found no VIP API citations in the validated sources -- "
            "nothing to prove or block")
    return _condition(
        CONDITION_VIP_API, COND_UNKNOWN,
        f"vip_api_card NOT_AVAILABLE: {report.reason}",
        reason_code=report.reason)


# ---------------------------------------------------------------------------
# the worst-wins fold (mandatory house rule for a gate/rollup item)
# ---------------------------------------------------------------------------

def fold_conditions(conditions: Sequence[GenCodeQualityCondition]) -> Tuple[str, str]:
    """`(verdict, reason)`. A single UNMET condition FAILs the whole gate
    regardless of how many other conditions are clean -- never averaged,
    never weighted. Only once nothing is UNMET does an UNKNOWN condition make
    the verdict INCOMPLETE_EVIDENCE rather than PASS. NOT_APPLICABLE never
    blocks PASS on its own."""
    unmet = [c for c in conditions if c.status == COND_UNMET]
    if unmet:
        return GATE_FAIL, "unmet condition(s): " + "; ".join(
            f"{c.name}: {c.reason}" for c in unmet)
    unknown = [c for c in conditions if c.status == COND_UNKNOWN]
    if unknown:
        return GATE_INCOMPLETE_EVIDENCE, "insufficient evidence: " + "; ".join(
            f"{c.name}: {c.reason}" for c in unknown)
    return GATE_PASS, f"all {len(conditions)} required condition(s) MET or NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# front door
# ---------------------------------------------------------------------------

def evaluate_gen_code_quality_gate(
        *,
        lint_report: Optional[uvm_structural_lint.UvmLintReport] = None,
        vip_api_report: Optional[vip_api_card.VipApiValidationReport] = None,
        env_dir: Optional[Union[str, Path]] = None,
        verible_bin: str = uvm_structural_lint.DEFAULT_VERIBLE_BIN,
        vip_sources: Optional[Sequence] = None,
        vip_index: Optional[Union[Dict[str, Any], str, Path]] = None,
        vip_relative_to: Optional[Union[str, Path]] = None,
) -> GenCodeQualityReport:
    """The composite gate. Reuses `uvm_structural_lint.lint_uvm_environment()`
    and `vip_api_card.validate_vip_api_usage()` -- called AT MOST ONCE each,
    and only when the caller has not already supplied that report -- never
    re-implemented.

    A caller already holding one or both reports (e.g. from a prior
    `create_environment()` run, which already writes both
    `uvm_structural_lint.json` and `vip_api_cards.json` next to a generated
    environment) should pass them directly via `lint_report`/`vip_api_report`;
    this function then makes NO call into that underlying module at all for
    that input. Otherwise: supplying `env_dir` runs the real lint over that
    generated environment directory; supplying both `vip_sources` and
    `vip_index` runs the real VIP API check (`vip_index` may be an
    already-loaded document, or a path `vip_api_card.load_index()` loads).

    Every bit of this function's own logic is classification
    (`classify_structural_lint_condition()`/`classify_vip_api_condition()`)
    and the worst-wins fold (`fold_conditions()`) over each real report's own
    already-computed fields -- neither check is ever re-derived."""
    if lint_report is None and env_dir is not None:
        lint_report = uvm_structural_lint.lint_uvm_environment(env_dir, verible_bin=verible_bin)

    if vip_api_report is None and vip_sources is not None and vip_index is not None:
        index = vip_index if isinstance(vip_index, dict) else vip_api_card.load_index(vip_index)
        vip_api_report = vip_api_card.validate_vip_api_usage(
            vip_sources, index, relative_to=vip_relative_to)

    conditions = [
        classify_structural_lint_condition(lint_report),
        classify_vip_api_condition(vip_api_report),
    ]
    status, reason = fold_conditions(conditions)
    return GenCodeQualityReport(
        status=status,
        reason=reason,
        conditions=conditions,
        structural_lint_status=(lint_report.status if lint_report is not None else None),
        vip_api_status=(vip_api_report.status if vip_api_report is not None else None),
    )


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def render_gen_code_quality_table(report: GenCodeQualityReport) -> str:
    rows = [{"Condition": c.name, "Status": c.status, "Reason": c.reason}
            for c in report.conditions]
    return render_markdown_table(
        [("Condition", "Condition"), ("Status", "Status"), ("Reason", "Reason")],
        rows, empty_note="(no conditions evaluated)")


def format_report(report: GenCodeQualityReport) -> str:
    lines = [f"Generated-Code Quality Gate: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.structural_lint_status:
        lines.append(f"  uvm_structural_lint status: {report.structural_lint_status}")
    if report.vip_api_status:
        lines.append(f"  vip_api_card status: {report.vip_api_status}")
    lines.append("")
    lines.append(render_gen_code_quality_table(report))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (no `dv-harness` verb -- see module docstring's disclosed residual)
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.gen_code_quality_gate`.
    Returns (text, exit_code): 0 PASS, 1 FAIL, 2 INCOMPLETE_EVIDENCE or a
    usage/lookup error."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.gen_code_quality_gate",
        description="Composite PASS/FAIL/INCOMPLETE_EVIDENCE quality gate over generated "
                    "UVM/SV code: folds uvm_structural_lint.py's real findings and "
                    "vip_api_card.py's real BLOCKED-citation findings worst-wins. Reuses "
                    "both checks; re-derives neither.")
    ap.add_argument("--env-dir", default=None,
                    help="Generated UVM environment directory to lint (uvm_structural_lint).")
    ap.add_argument("--verible-bin", default=uvm_structural_lint.DEFAULT_VERIBLE_BIN)
    ap.add_argument("--vip-source", action="append", default=None, dest="vip_sources",
                    help="Generated .sv/.svh file or directory to VIP-API-validate "
                         "(repeatable; requires --vip-index).")
    ap.add_argument("--vip-index", default=None, help="vip_symbol_index JSON document.")
    ap.add_argument("--relative-to", default=None,
                    help="Root for reported VIP-API usage paths (default: --env-dir).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)

    if a.env_dir is None and not a.vip_sources:
        return ("gen_code_quality_gate: at least one of --env-dir or "
                "--vip-source (with --vip-index) must be supplied", 2)

    try:
        report = evaluate_gen_code_quality_gate(
            env_dir=a.env_dir, verible_bin=a.verible_bin,
            vip_sources=a.vip_sources, vip_index=a.vip_index,
            vip_relative_to=a.relative_to or a.env_dir)
    except vip_api_card.VipApiValidationError as exc:
        return (f"gen_code_quality_gate: {exc}", 2)

    text = json.dumps(report.to_dict(), indent=2) if a.json else format_report(report)
    return text, {GATE_PASS: 0, GATE_FAIL: 1, GATE_INCOMPLETE_EVIDENCE: 2}[report.status]


def main(argv: Optional[Sequence[str]] = None) -> int:
    text, code = execute_verb(argv)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
