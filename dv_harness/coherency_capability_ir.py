"""dv_harness/coherency_capability_ir.py -- CoherencyCapabilityIR: a full ACE-style
coherency BEHAVIORAL CAPABILITY model, classified only from real caller-supplied
RTL/spec/simulation evidence.

WHAT THIS IS, AND WHY IT IS A DIFFERENT, LARGER SCOPE THAN THE EXISTING STUB
-----------------------------------------------------------------------------
`syoscb_compare_policy.py` already has a `_coherency_axis()` function, and this
module deliberately does NOT import it -- reading it first is exactly what
confirmed the two are not the same thing. `_coherency_axis()` answers one
narrow question for one narrow purpose: "does this protocol's real signal
vocabulary carry an ACE-Lite coherency signal at all", used ONLY to decide one
field of a SYOSCB compare-KEY schema (`MATCH_KEY_AXES`'s `coherency_attributes`
entry) -- it returns `AXIS_NO_IR_FIELD` for every protocol that carries a
coherency signal, because `AMBA_TRANSACTION_IR_FIELDS` has no slot for a snoop
type, a domain, or a barrier, and that is the ENTIRE fact it exists to record.

This module is a full BEHAVIORAL CAPABILITY model over four separately
classified axes -- snoop-type support, coherency-domain membership,
barrier-transaction support, and dirty/clean cache-line tracking -- each
carrying its own status, its own evidence basis, and its own citation. It
answers "what can this DUT/interface actually DO", not "what compare-key
field would a queue need". Nothing here feeds a SYOSCB match key, and nothing
in `syoscb_compare_policy.py` is read, imported, or re-derived by this module.

THE EVIDENCE TRUTH RULE, ENFORCED IN THE FUNCTION SIGNATURE ITSELF
-------------------------------------------------------------------
"ACE support must never be assumed from an AXI base protocol" is not merely
stated in this docstring -- it is a structural property of `classify_axis()`:
that function's signature is `classify_axis(axis_name, evidence)`. It takes no
`protocol` argument at all, so there is no code path by which a protocol
string (`"AXI_MM"`, `"AMBA4"`, ...) could influence an axis's classification.
`protocol`/`dut_name` are accepted only by `build_coherency_capability_ir()`,
recorded on the resulting IR purely as informational context for a human
reader, and never consulted by any classification decision. A caller who
passes the identical `evidence` dict with a different `protocol` string gets
back byte-identical axis results -- proven directly by
`test_axis_classification_never_reads_the_protocol_field`.

Every axis is therefore classified from one of three real evidence kinds,
each requiring a real citation, never a guess:
  1. `simulation_observed_values` -- dynamic evidence: a real waveform/sim.log
     record that this capability's encoding was actually driven/observed.
     The strongest evidence this module recognizes.
  2. `spec_statement` -- an explicit spec/programming-guide sentence saying
     this capability is (or is not) supported, cited by document+location.
  3. `signals_present` / `signals_checked` -- RTL/VIP-config port evidence: a
     real observed signal set (from a verible port parse, a VIP config dump,
     or a bind-topology document) is compared against this module's own FIXED
     ACE/ACE-Lite witness-signal vocabulary (`AXIS_WITNESS_SIGNALS`, the same
     "witness signal proves the field" convention `amba_transaction_ir.py`'s
     own `IR_FIELD_WITNESS_SIGNALS` already uses). A witness signal present
     proves SUPPORTED; the FULL witness set checked and absent proves
     NOT_SUPPORTED -- a caller who supplies only a PARTIAL signal list can
     never manufacture a "not supported" conclusion this way, because
     `signals_checked` must be a real superset of the axis's own witness set.

Absent any of the three, the honest answer is `CAP_UNKNOWN` -- never a
default, never a guess, and never quietly reported as unsupported. An
explicit `declared_not_applicable` (itself requiring a real reason and
citation) is the only way to reach `CAP_NOT_APPLICABLE`, and it is a
DECLARATION the caller makes from their own evidence, never something this
module infers on its own from a protocol name or family.

DUCK-TYPED, NO IMPORT FROM ANY CLAIMED OR CONCURRENT-BATCH FILE
-----------------------------------------------------------------
`evidence` (per axis) and the outer `protocol`/`dut_name` are plain,
duck-typed parameters -- this module imports nothing from
`amba_transaction_ir.py`, `amba_port_registry.py`, `syoscb_compare_policy.py`,
or any other file in this session's claimed-file list or new-module batch.
The only imports are `dv_harness.models.Status` (a stable, unclaimed
vocabulary-collision reference) and `dv_harness.connectivity.
render_markdown_table` (this repo's one parameterized table renderer, reused
rather than a fourth hand-rolled table loop -- also unclaimed and pre-existing
outside this batch).

DELIBERATELY BOUNDED
--------------------
This module classifies four capability axes from evidence a caller already
has; it parses no RTL, runs no verible subprocess, and reads no waveform
itself. It decides, approves and arbitrates nothing beyond its own
classification: no build, no job, no approval, and there is deliberately no
stage gate -- a `CoherencyCapabilityIR` is an input to a human's coverage/
architecture decision, never a substitute for one. There is no `dv-harness`
CLI verb (`cli.py`/`gates.py` were not touched, per this task's file-safety
scope); the front door is `python -m dv_harness.coherency_capability_ir`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dv_harness.models import Status
from dv_harness.connectivity import render_markdown_table


class CoherencyCapabilityIRError(Exception):
    """A malformed evidence record, an unrecognized axis name, or a
    declaration (spec statement / not-applicable / simulation observation)
    missing the real citation it must carry."""

    def __init__(self, code: str, detail: Optional[dict] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


# ===========================================================================
# Fixed axis vocabulary
# ===========================================================================

AXIS_SNOOP_TYPE = "snoop_type_support"
AXIS_DOMAIN_MEMBERSHIP = "coherency_domain_membership"
AXIS_BARRIER_TRANSACTION = "barrier_transaction_support"
AXIS_DIRTY_CLEAN_TRACKING = "dirty_clean_line_tracking"

#: The four ACE-style coherency capability axes this IR models, in a fixed
#: order -- never re-derived, never widened at runtime.
AXIS_NAMES: tuple = (
    AXIS_SNOOP_TYPE,
    AXIS_DOMAIN_MEMBERSHIP,
    AXIS_BARRIER_TRANSACTION,
    AXIS_DIRTY_CLEAN_TRACKING,
)

#: Real AMBA5 ACE/ACE-Lite signal names, one witness set per axis -- this
#: module's OWN fixed known-vocabulary table (the same convention
#: `amba_transaction_ir.py`'s own `IR_FIELD_WITNESS_SIGNALS` already uses: a
#: witness signal's PRESENCE in a caller's real observed port/signal list is
#: what proves an axis, never a protocol name). ARSNOOP/AWSNOOP encode the
#: ACE snoop type directly; ARDOMAIN/AWDOMAIN plus the AC snoop channel
#: (ACVALID/ACREADY/ACADDR/ACSNOOP/ACPROT) evidence real coherency-domain
#: participation (a port that can be snooped is a member of a shareable
#: domain); ARBAR/AWBAR plus WACK/RACK are ACE's barrier/DVM acknowledge
#: signals; CRRESP (carrying PassDirty/IsShared/WasUnique) plus the CR/CD
#: channels evidence real dirty/clean cache-line tracking.
AXIS_WITNESS_SIGNALS: dict = {
    AXIS_SNOOP_TYPE: frozenset({"ARSNOOP", "AWSNOOP"}),
    AXIS_DOMAIN_MEMBERSHIP: frozenset({
        "ARDOMAIN", "AWDOMAIN", "ACVALID", "ACREADY", "ACADDR", "ACSNOOP", "ACPROT"}),
    AXIS_BARRIER_TRANSACTION: frozenset({"ARBAR", "AWBAR", "WACK", "RACK"}),
    AXIS_DIRTY_CLEAN_TRACKING: frozenset({
        "CRRESP", "CRVALID", "CRREADY", "CDVALID", "CDREADY", "CDDATA", "CDLAST"}),
}

_ALL_WITNESS_SIGNALS: frozenset = frozenset().union(*AXIS_WITNESS_SIGNALS.values())


# ===========================================================================
# Per-axis status vocabulary
# ===========================================================================

#: Real evidence (simulation, spec, or a full-vocabulary RTL/VIP signal
#: check) proves this axis's capability is present.
CAP_SUPPORTED = "SUPPORTED"
#: Real evidence -- an explicit spec statement, or the FULL witness set
#: checked and confirmed absent -- proves this axis's capability is absent.
CAP_NOT_SUPPORTED = "NOT_SUPPORTED"
#: No evidence of any recognized kind was supplied for this axis. The
#: default, honest answer whenever nothing proves either direction.
CAP_UNKNOWN = "UNKNOWN"
#: The caller explicitly declared (with a real reason and citation) that this
#: axis does not apply to this interface -- never inferred by this module.
CAP_NOT_APPLICABLE = "NOT_APPLICABLE"

AXIS_STATUS_VALUES: tuple = (CAP_SUPPORTED, CAP_NOT_SUPPORTED, CAP_UNKNOWN, CAP_NOT_APPLICABLE)

#: Which real evidence kind produced an axis's status -- so a reader can see
#: WHY a status was reached, not only what it is.
BASIS_SIMULATION_OBSERVED = "SIMULATION_OBSERVED"
BASIS_SPEC_DOCUMENTED = "SPEC_DOCUMENTED"
BASIS_RTL_SIGNAL_PRESENT = "RTL_SIGNAL_PRESENT"
BASIS_RTL_SIGNAL_ABSENT_FULL_ENUMERATION = "RTL_SIGNAL_ABSENT_FULL_ENUMERATION"
BASIS_DECLARED_NOT_APPLICABLE = "DECLARED_NOT_APPLICABLE"
BASIS_NO_EVIDENCE = "NO_EVIDENCE"

EVIDENCE_BASIS_VALUES: tuple = (
    BASIS_SIMULATION_OBSERVED, BASIS_SPEC_DOCUMENTED, BASIS_RTL_SIGNAL_PRESENT,
    BASIS_RTL_SIGNAL_ABSENT_FULL_ENUMERATION, BASIS_DECLARED_NOT_APPLICABLE, BASIS_NO_EVIDENCE)

# ---------------------------------------------------------------------------
# Whole-IR rollup vocabulary -- worst-wins, an UNKNOWN axis always outranks
# an otherwise-clean picture (the same "an unresolved fact must never
# silently disappear into an average" discipline this project applies
# everywhere: golden_flow_readiness.py, subsystem_maturity_gate.py,
# spec_vplan_readiness_gate.py, ...).
# ---------------------------------------------------------------------------
OVERALL_FULL_SUPPORT = "FULL_ACE_COHERENCY_SUPPORT"
OVERALL_PARTIAL_SUPPORT = "PARTIAL_ACE_COHERENCY_SUPPORT"
OVERALL_NO_SUPPORT = "NO_ACE_COHERENCY_SUPPORT"
OVERALL_NOT_APPLICABLE = "COHERENCY_NOT_APPLICABLE"
OVERALL_UNKNOWN = "COHERENCY_CAPABILITY_UNKNOWN"

OVERALL_VALUES: tuple = (
    OVERALL_FULL_SUPPORT, OVERALL_PARTIAL_SUPPORT, OVERALL_NO_SUPPORT,
    OVERALL_NOT_APPLICABLE, OVERALL_UNKNOWN)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary (axis statuses, evidence bases, overall
    rollup values) must share no token with `dv_harness.models.Status` -- the
    same guard several sibling domain-vocabulary modules in this project
    already apply to themselves. A capability classification is not a stage
    verdict, and a future edit that accidentally reused e.g. `"PASS"` here
    would let this module's report be misread as one."""
    verdicts = {s.value for s in Status}
    collision = verdicts & set(AXIS_STATUS_VALUES) | verdicts & set(EVIDENCE_BASIS_VALUES) \
        | verdicts & set(OVERALL_VALUES)
    if collision:
        raise CoherencyCapabilityIRError("VOCABULARY_COLLIDES_WITH_STATUS", {
            "collision": sorted(collision),
            "hint": "this module's vocabulary must share no token with dv_harness.models.Status"})


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Per-axis classification
# ===========================================================================

def _require(condition: bool, code: str, detail: dict) -> None:
    if not condition:
        raise CoherencyCapabilityIRError(code, detail)


def classify_axis(axis_name: str, evidence: Optional[dict]) -> dict:
    """Classify ONE axis from ONE axis's evidence. Deliberately takes no
    `protocol`/`dut_name` argument -- see the module docstring's "Evidence
    Truth Rule, enforced in the function signature itself".

    `evidence` (a plain dict, or `None`/falsy for "nothing was supplied") may
    carry, in the checked precedence order:
      - `declared_not_applicable`: `{"reason": str, "citation": str}` -- an
        explicit human/caller declaration this axis does not apply here.
      - `simulation_observed_values`: a non-empty list of real observed
        encodings (e.g. domain/snoop-type/dirty-response values actually
        seen), plus a required `simulation_evidence_source` citation.
      - `spec_statement`: `{"supported": bool, "citation": str, "text": str?}`
        -- an explicit spec/programming-guide statement, cited.
      - `signals_present` (list of observed real signal names) and/or
        `signals_checked` (the full real signal/port set that was actually
        examined), plus a required `signals_evidence_source` citation.

    Returns `{"status", "evidence_basis", "matched_signals", "citations",
    "reason"}`. Absent all four evidence kinds, returns `CAP_UNKNOWN` with
    `BASIS_NO_EVIDENCE` -- never a guessed status."""
    if axis_name not in AXIS_WITNESS_SIGNALS:
        raise CoherencyCapabilityIRError("UNKNOWN_AXIS", {
            "axis": axis_name, "known_axes": list(AXIS_NAMES)})
    evidence = evidence or {}
    if not isinstance(evidence, dict):
        raise CoherencyCapabilityIRError("EVIDENCE_NOT_A_MAPPING", {
            "axis": axis_name, "evidence_type": type(evidence).__name__})
    witnesses = AXIS_WITNESS_SIGNALS[axis_name]

    # 1. Explicit, caller-declared not-applicable -- never inferred.
    declared_na = evidence.get("declared_not_applicable")
    if declared_na:
        _require(isinstance(declared_na, dict), "DECLARED_NOT_APPLICABLE_NOT_A_MAPPING",
                  {"axis": axis_name})
        reason = declared_na.get("reason")
        citation = declared_na.get("citation")
        _require(bool(reason) and bool(citation), "DECLARED_NOT_APPLICABLE_MISSING_CITATION", {
            "axis": axis_name, "hint": "declared_not_applicable requires a real reason and a "
                                        "real citation -- an undocumented declaration would be "
                                        "indistinguishable from a guess"})
        return {"status": CAP_NOT_APPLICABLE, "evidence_basis": BASIS_DECLARED_NOT_APPLICABLE,
                "matched_signals": [], "citations": [citation], "reason": reason}

    # 2. Dynamic simulation/waveform evidence -- the strongest positive proof.
    sim_values = evidence.get("simulation_observed_values")
    if sim_values:
        _require(isinstance(sim_values, (list, tuple)) and len(sim_values) > 0,
                  "SIMULATION_EVIDENCE_EMPTY", {"axis": axis_name})
        sim_source = evidence.get("simulation_evidence_source")
        _require(bool(sim_source), "SIMULATION_EVIDENCE_MISSING_SOURCE", {
            "axis": axis_name, "hint": "simulation_observed_values requires a real "
                                        "simulation_evidence_source citation"})
        return {"status": CAP_SUPPORTED, "evidence_basis": BASIS_SIMULATION_OBSERVED,
                "matched_signals": [], "citations": [sim_source],
                "reason": f"real simulation/waveform evidence recorded observed value(s) "
                          f"{list(sim_values)} for this axis"}

    # 3. Explicit spec/programming-guide statement.
    spec_statement = evidence.get("spec_statement")
    if spec_statement:
        _require(isinstance(spec_statement, dict), "SPEC_STATEMENT_NOT_A_MAPPING",
                  {"axis": axis_name})
        supported = spec_statement.get("supported")
        citation = spec_statement.get("citation")
        _require(isinstance(supported, bool) and bool(citation), "SPEC_STATEMENT_INCOMPLETE", {
            "axis": axis_name, "hint": "spec_statement requires a real boolean 'supported' and a "
                                        "real citation"})
        text = spec_statement.get("text") or (
            "spec documents support for this axis" if supported
            else "spec documents this axis as unsupported")
        return {"status": CAP_SUPPORTED if supported else CAP_NOT_SUPPORTED,
                "evidence_basis": BASIS_SPEC_DOCUMENTED, "matched_signals": [],
                "citations": [citation], "reason": text}

    # 4. Real observed RTL/VIP-config signal evidence, checked against this
    #    module's own fixed witness vocabulary for the axis.
    signals_present = set(evidence.get("signals_present") or [])
    signals_checked = set(evidence.get("signals_checked") or [])
    source = evidence.get("signals_evidence_source")
    matched = sorted(signals_present & witnesses)
    if matched:
        _require(bool(source), "SIGNAL_EVIDENCE_MISSING_SOURCE", {
            "axis": axis_name, "hint": "signals_present requires a real "
                                        "signals_evidence_source citation"})
        return {"status": CAP_SUPPORTED, "evidence_basis": BASIS_RTL_SIGNAL_PRESENT,
                "matched_signals": matched, "citations": [source],
                "reason": f"observed signal(s) {matched} present in the real cited "
                          f"port/signal evidence"}
    if signals_checked and witnesses <= signals_checked:
        _require(bool(source), "SIGNAL_EVIDENCE_MISSING_SOURCE", {
            "axis": axis_name, "hint": "signals_checked requires a real "
                                        "signals_evidence_source citation"})
        return {"status": CAP_NOT_SUPPORTED,
                "evidence_basis": BASIS_RTL_SIGNAL_ABSENT_FULL_ENUMERATION,
                "matched_signals": [], "citations": [source],
                "reason": f"the full witness vocabulary {sorted(witnesses)} was checked "
                          f"against the real cited port/signal evidence and none is present"}

    # 5. Nothing recognized was supplied -- the honest default.
    return {"status": CAP_UNKNOWN, "evidence_basis": BASIS_NO_EVIDENCE, "matched_signals": [],
            "citations": [],
            "reason": "no simulation evidence, spec statement, or RTL/VIP signal evidence "
                      "(present or a full enumeration confirming absence) was supplied for "
                      "this axis"}


def derive_overall_capability(axes: dict) -> str:
    """Worst-wins rollup over the four axis statuses. `CAP_UNKNOWN` on any
    axis always wins -- a capability model with one undetermined axis must
    never be reported as either fully supported or fully unsupported."""
    statuses = {axes[a]["status"] for a in AXIS_NAMES}
    if CAP_UNKNOWN in statuses:
        return OVERALL_UNKNOWN
    supported = [a for a in AXIS_NAMES if axes[a]["status"] == CAP_SUPPORTED]
    not_supported = [a for a in AXIS_NAMES if axes[a]["status"] == CAP_NOT_SUPPORTED]
    if not supported and not not_supported:
        return OVERALL_NOT_APPLICABLE
    if not supported:
        return OVERALL_NO_SUPPORT
    if not not_supported:
        return OVERALL_FULL_SUPPORT
    return OVERALL_PARTIAL_SUPPORT


# ===========================================================================
# The IR itself
# ===========================================================================

@dataclass
class CoherencyCapabilityIR:
    """One ACE-style coherency capability record for one DUT interface/port.

    `protocol`/`dut_name`/`ir_id` are recorded purely as informational
    context -- see the module docstring's Evidence Truth Rule section for why
    they are never consulted by classification itself."""
    axes: dict
    overall_capability: str
    unresolved_axes: list
    protocol: Optional[str] = None
    dut_name: Optional[str] = None
    ir_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ir_id": self.ir_id,
            "protocol": self.protocol,
            "dut_name": self.dut_name,
            "axes": self.axes,
            "overall_capability": self.overall_capability,
            "unresolved_axes": self.unresolved_axes,
        }


def build_coherency_capability_ir(evidence_by_axis: Optional[dict], *,
                                   protocol: Optional[str] = None,
                                   dut_name: Optional[str] = None,
                                   ir_id: Optional[str] = None) -> CoherencyCapabilityIR:
    """Classify all four axes from `evidence_by_axis` (`{axis_name: evidence}`,
    a missing axis key treated as no evidence for that axis) and roll them up
    into one `CoherencyCapabilityIR`.

    `protocol`/`dut_name` are recorded on the result and NEVER passed to
    `classify_axis()` -- so no axis's classification can ever depend on
    them."""
    if evidence_by_axis is not None and not isinstance(evidence_by_axis, dict):
        raise CoherencyCapabilityIRError("EVIDENCE_BY_AXIS_NOT_A_MAPPING", {
            "evidence_type": type(evidence_by_axis).__name__})
    unknown_axes = sorted(set((evidence_by_axis or {}).keys()) - set(AXIS_NAMES))
    if unknown_axes:
        raise CoherencyCapabilityIRError("UNKNOWN_AXIS_IN_EVIDENCE", {
            "unknown_axes": unknown_axes, "known_axes": list(AXIS_NAMES)})
    axes = {a: classify_axis(a, (evidence_by_axis or {}).get(a)) for a in AXIS_NAMES}
    overall = derive_overall_capability(axes)
    unresolved = [a for a in AXIS_NAMES if axes[a]["status"] == CAP_UNKNOWN]
    return CoherencyCapabilityIR(axes=axes, overall_capability=overall,
                                  unresolved_axes=unresolved, protocol=protocol,
                                  dut_name=dut_name, ir_id=ir_id)


def assert_ir_complete(ir: CoherencyCapabilityIR) -> None:
    """Every one of the four fixed axes must be present, each with a
    recognized status and evidence basis -- an absent key is how a downstream
    reader ends up treating a missing axis as a quiet SUPPORTED/NOT_SUPPORTED
    default."""
    missing = [a for a in AXIS_NAMES if a not in (ir.axes or {})]
    if missing:
        raise CoherencyCapabilityIRError("IR_MISSING_AXES", {"missing_axes": missing})
    for axis, entry in ir.axes.items():
        if entry.get("status") not in AXIS_STATUS_VALUES:
            raise CoherencyCapabilityIRError("IR_AXIS_STATUS_UNRECOGNIZED", {
                "axis": axis, "status": entry.get("status")})
        if entry.get("evidence_basis") not in EVIDENCE_BASIS_VALUES:
            raise CoherencyCapabilityIRError("IR_AXIS_BASIS_UNRECOGNIZED", {
                "axis": axis, "evidence_basis": entry.get("evidence_basis")})


# ===========================================================================
# Rendering
# ===========================================================================

def render_coherency_capability_table(ir: CoherencyCapabilityIR) -> str:
    rows = [{"axis": a, "status": ir.axes[a]["status"],
             "evidence_basis": ir.axes[a]["evidence_basis"],
             "matched_signals": ", ".join(ir.axes[a]["matched_signals"]) or "-",
             "citations": "; ".join(ir.axes[a]["citations"]) or "-",
             "reason": ir.axes[a]["reason"]}
            for a in AXIS_NAMES]
    table = render_markdown_table(
        [("axis", "Axis"), ("status", "Status"), ("evidence_basis", "Evidence Basis"),
         ("matched_signals", "Matched Signals"), ("citations", "Citation(s)"),
         ("reason", "Reason")], rows)
    lines = [f"# ACE-Style Coherency Capability -- {ir.protocol or '(protocol not recorded)'} "
             f"{('/ ' + ir.dut_name) if ir.dut_name else ''}".rstrip(), "",
             f"Overall: **{ir.overall_capability}**", "", table]
    if ir.unresolved_axes:
        lines += ["", f"Unresolved axes (no evidence supplied): "
                      f"{', '.join(ir.unresolved_axes)}"]
    return "\n".join(lines)


# ===========================================================================
# CLI front door
# ===========================================================================

def execute_verb(args) -> tuple:
    """Shared implementation for the `python -m` front door. Returns
    `(exit_code, ir_or_none, text)`. `args` is an `argparse.Namespace` with
    `evidence` (path to a JSON document `{"protocol"?, "dut_name"?, "ir_id"?,
    "axes": {axis_name: evidence, ...}}`) and `json` (bool)."""
    import json as _json

    try:
        with open(args.evidence, "r", encoding="utf-8") as fh:
            doc = _json.load(fh)
    except (OSError, ValueError) as exc:
        return 2, None, f"NOT_AVAILABLE: could not read/parse {args.evidence!r}: {exc}"
    if not isinstance(doc, dict):
        return 2, None, "NOT_AVAILABLE: evidence document must be a JSON object"
    try:
        ir = build_coherency_capability_ir(
            doc.get("axes"), protocol=doc.get("protocol"), dut_name=doc.get("dut_name"),
            ir_id=doc.get("ir_id"))
        assert_ir_complete(ir)
    except CoherencyCapabilityIRError as exc:
        return 2, None, f"NOT_AVAILABLE: {exc.code}: {exc.detail}"

    text = _json.dumps(ir.to_dict(), indent=2) if getattr(args, "json", False) \
        else render_coherency_capability_table(ir)
    exit_code = 1 if ir.unresolved_axes else 0
    return exit_code, ir, text


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m dv_harness.coherency_capability_ir")
    parser.add_argument("--evidence", required=True,
                         help="path to a JSON evidence document, "
                              '{"protocol"?, "dut_name"?, "ir_id"?, "axes": {...}}')
    parser.add_argument("--json", action="store_true", help="emit the IR as JSON")
    args = parser.parse_args(argv)
    exit_code, _ir, text = execute_verb(args)
    print(text)
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
