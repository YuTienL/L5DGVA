"""dv_harness/verification_intent_ir.py -- a semantic-bridge Verification
Intent IR, one record per requirement, between a requirement_contract.py
record and a downstream generator (vPlan writer, scenario planner, checker/
coverage generator).

THE GAP THIS CLOSES. requirement_contract.py (section 184) answers "is this
requirement internally coherent and safe to generate from" over fifteen
PROSE fields. Nothing in this repo turns a COMPLETE requirement into the
INTERPRETIVE shape a generator actually consumes: what is the test's
objective, what stimulus does it imply, what should check it, what should be
covered -- plus, because DV requirements routinely cut across more than one
structural domain of the DUT, a per-domain reading for state-machine,
register/CSR, interrupt, reset/clock, error/recovery, low-power and
performance concerns. A repo-wide grep for `verification_intent_ir` /
`VerificationIntentIR` / `semantic bridge` returned nothing.

WHAT THIS IS NOT. It is not a requirement extractor (requirement_contract.py
owns that), not a spec parser, not a scenario/command.txt generator, and it
runs no simulation. It reads ONE requirement record plus whatever real
DUT-evidence a caller supplies and produces an INTERPRETIVE bridge record --
never a generated test, never a verified fact.

EVIDENCE TRUTH RULE, applied to something inherently interpretive. Turning
"the DUT shall enter LOW_POWER on WFI" into "drive WFI, check the low-power
handshake, cover entry/exit" is an INTERPRETIVE act -- a judgment about what a
requirement implies, not a measurement. So every `VerificationIntentIR`
record declares `evidence_provenance.AGENT_SELF_ATTESTED` (imported, never
re-typed) on itself, carrying that vocabulary's own caveat text
(`evidence_provenance.caveat_for()`) rather than a bespoke one. That is
DIFFERENT from the per-domain DUT EVIDENCE each sub-planner attaches: where a
real producer already exists (power_intent.py's UPF model,
interrupt_dma_clock_reset_extraction.py's RTL/spec scan, sys_regmap.py's
mode-determining bits, protocol_capability.py's state-graph-model registry),
that producer's OWN real facts and OWN real status vocabulary are carried
through verbatim -- never re-derived, never rewritten into a happier status.
The IR's interpretation of what those facts MEAN for a test is still
self-attested; the facts themselves are not.

REUSE OVER REINVENT, one producer per domain, never a second implementation:
  * low_power    -- dv_harness.power_intent.analyze_power_intent()'s own
                    PowerIntentReport, PASS/FAIL/NOT_AVAILABLE PRESERVED
                    verbatim (see plan_low_power()'s own note on why its
                    status is NOT translated into this module's vocabulary).
  * interrupt,
    reset_clock  -- dv_harness.interrupt_dma_clock_reset_extraction.
                    extract_interrupt_dma_clock_reset()'s own
                    interrupt_architecture / clock_reset_extension blocks.
  * register_csr -- dv_harness.sys_regmap.required_preconditions() /
                    unverifiable_bits(), scoped to the requirement's own
                    protocol/feature as the interface name.
  * state_machine -- dv_harness.protocol_capability.capability_for() /
                    derive_status(), reading whichever of a protocol's
                    declared models name a state graph (e.g. PCIe's
                    ltssm_top_level_state_graph) -- never a second state
                    model.
  * error_recovery,
    performance  -- THIS HARNESS HAS NO EVIDENCE PRODUCER FOR EITHER. No
                    module here derives an acceptable-error-rate/recovery-
                    time bound or a throughput/latency/bandwidth target from
                    any real source. Rather than leaving these domains silent
                    (which would read as "not relevant") or inventing a
                    number, both report a real, distinct sentinel --
                    `ERROR_TARGET_UNKNOWN` / `PERFORMANCE_TARGET_UNKNOWN` --
                    naming exactly what is missing.

Every requirement's own `requirement_contract` shape (or absence of one) is
also carried through, via `requirement_contract.declares_contract_shape()` /
`downstream_consumable()` -- IMPORTED, never re-checked by hand -- so a
reader can see in one place whether the SOURCE requirement was itself fit to
generate from, without this module repeating that analysis.

DELIBERATELY BOUNDED, and stated rather than implied closed.
 1. Domain APPLICABILITY is a structural fact only for two domains
    (state_machine / register_csr, which need a named protocol/interface to
    look anything up); the other five are always attempted, gated on the
    caller supplying real evidence. This module never guesses that a
    requirement is "about" a domain from keyword matching on its prose --
    that would be exactly the interpretive overreach the AGENT_SELF_ATTESTED
    marking exists to flag, not something a status field can silently do
    instead.
 2. It ARBITRATES nothing and GENERATES nothing: no scenario, command.txt,
    checker or covergroup content is emitted, and there is deliberately no
    stage gate -- a gate that passed on an interpretive IR nobody reviewed
    would be worse than none. `system_resource_inventory`'s driver-conflict
    DETECTION-vs-ARBITRATION boundary is the same shape applied here.
 3. It never re-derives a DUT fact a real module already computes -- every
    `dut_evidence` block is that producer's own output (or a verbatim slice
    of it), never rebuilt from source text a second time.
 4. Register/CSR and state-machine evidence both need the requirement to
    NAME a protocol/interface; a requirement that does not is `NOT_APPLICABLE`
    for those two domains, not `NOT_AVAILABLE` (a domain with nothing to look
    up is a different fact from a domain that was asked and had no answer).
 5. No JSON schema file accompanies this IR: nothing in this repo persists or
    validates against it yet, so adding one now would be an unused artifact
    kept in sync with nobody.

Proven by dv_harness_tests/test_verification_intent_ir.py, driven against the
real `power_intent`, `interrupt_dma_clock_reset_extraction`, `sys_regmap` and
`protocol_capability` producers over small real fixtures -- never mocked.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import power_intent
from . import interrupt_dma_clock_reset_extraction as idcr
from . import sys_regmap
from . import protocol_capability
from . import requirement_contract
from .evidence_provenance import AGENT_SELF_ATTESTED, PROVENANCE_FIELD, caveat_for
from .models import Status

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------
# Domain vocabulary
# --------------------------------------------------------------------------

DOMAIN_STATE_MACHINE = "state_machine"
DOMAIN_REGISTER_CSR = "register_csr"
DOMAIN_INTERRUPT = "interrupt"
DOMAIN_RESET_CLOCK = "reset_clock"
DOMAIN_ERROR_RECOVERY = "error_recovery"
DOMAIN_LOW_POWER = "low_power"
DOMAIN_PERFORMANCE = "performance"

#: Declaration order -- also the order format_ir() renders domain rows in.
DOMAINS: Tuple[str, ...] = (
    DOMAIN_STATE_MACHINE, DOMAIN_REGISTER_CSR, DOMAIN_INTERRUPT, DOMAIN_RESET_CLOCK,
    DOMAIN_ERROR_RECOVERY, DOMAIN_LOW_POWER, DOMAIN_PERFORMANCE,
)

#: A real, structurally-modelled DUT fact was found for this domain.
DUT_EVIDENCE_FOUND = "DUT_EVIDENCE_FOUND"
#: Some real evidence exists but is incomplete for a decision (e.g. a
#: mode-determining bit is named but its required value was never documented).
#: Deliberately NOT the bare "PARTIAL" spelling `models.Status` already owns
#: (see assert_no_verification_verdict_vocabulary() below).
DUT_EVIDENCE_PARTIAL = "DUT_EVIDENCE_PARTIAL"
#: Per rule 1's own honest-status vocabulary, reused verbatim: evidence was
#: sought and none was found (absent producer input, or a producer that ran
#: and found nothing).
NOT_AVAILABLE = "NOT_AVAILABLE"
#: This domain has nothing to look up for this requirement at all (it names
#: no protocol/interface) -- a structural fact, distinct from NOT_AVAILABLE.
NOT_APPLICABLE = "NOT_APPLICABLE"
#: performance/error_recovery: no evidence producer exists in this harness at
#: all. Never conflated with NOT_AVAILABLE (a producer that ran and found
#: nothing) -- this says no producer was ever asked because none exists.
PERFORMANCE_TARGET_UNKNOWN = "PERFORMANCE_TARGET_UNKNOWN"
ERROR_TARGET_UNKNOWN = "ERROR_TARGET_UNKNOWN"


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's OWN dut_evidence_status vocabulary must share no token
    with models.Status -- a domain sub-plan's status is a statement about
    evidence availability, never a stage-gate verdict. The same guard
    capability_evolution.py (BENCHMARK_OUTCOMES) and benchmark_dataset.py
    already run for their own vocabularies.

    Deliberately excludes NOT_AVAILABLE/NOT_APPLICABLE (neither is a
    models.Status member, and both are this repo's own shared honest-status
    convention across dozens of modules) and excludes power_intent.py's
    PASS/FAIL/NOT_AVAILABLE, which plan_low_power() preserves verbatim BY
    DESIGN and discloses via `status_vocabulary_source` rather than folding
    into this module's own vocabulary."""
    status_values = {s.value for s in Status}
    domain_values = {DUT_EVIDENCE_FOUND, DUT_EVIDENCE_PARTIAL,
                      PERFORMANCE_TARGET_UNKNOWN, ERROR_TARGET_UNKNOWN}
    overlap = status_values & domain_values
    if overlap:
        raise AssertionError(
            "verification_intent_ir's own status vocabulary collides with "
            f"models.Status: {sorted(overlap)}")


assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------

@dataclass
class DomainSubPlan:
    """One domain's reading of one requirement. `dut_evidence` is always a
    verbatim (or verbatim-sliced) copy of a real producer's own output --
    never rebuilt from source a second time."""
    domain: str
    applicable: bool
    dut_evidence_status: str
    dut_evidence_reason: Optional[str] = None
    dut_evidence_source: Optional[str] = None
    dut_evidence: Dict[str, Any] = field(default_factory=dict)
    plan_notes: List[str] = field(default_factory=list)
    #: Set only for domains (today: low_power) whose dut_evidence_status is a
    #: DIFFERENT real vocabulary preserved verbatim from its own producer,
    #: rather than this module's DUT_EVIDENCE_*/NOT_AVAILABLE/NOT_APPLICABLE
    #: set -- so a reader is told, rather than left to assume, which
    #: vocabulary a given status value belongs to.
    status_vocabulary_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "applicable": self.applicable,
            "dut_evidence_status": self.dut_evidence_status,
            "dut_evidence_reason": self.dut_evidence_reason,
            "dut_evidence_source": self.dut_evidence_source,
            "dut_evidence": self.dut_evidence,
            "plan_notes": list(self.plan_notes),
            "status_vocabulary_source": self.status_vocabulary_source,
        }


@dataclass
class VerificationIntentIR:
    requirement_id: str
    objective: str
    stimulus_intent: str
    checker_intent: str
    coverage_intent: str
    domain_plans: Dict[str, DomainSubPlan]
    requirement_contract_status: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    #: Always AGENT_SELF_ATTESTED (see module docstring) -- not a caller
    #: option, because this record's interpretive nature is a fact about what
    #: this module IS, not a claim a caller could reasonably override.
    evidence_provenance: str = AGENT_SELF_ATTESTED
    evidence_provenance_caveat: str = ""

    def __post_init__(self) -> None:
        self.evidence_provenance = AGENT_SELF_ATTESTED
        self.evidence_provenance_caveat = caveat_for(self.evidence_provenance)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requirement_id": self.requirement_id,
            PROVENANCE_FIELD: self.evidence_provenance,
            "evidence_provenance_caveat": self.evidence_provenance_caveat,
            "objective": self.objective,
            "stimulus_intent": self.stimulus_intent,
            "checker_intent": self.checker_intent,
            "coverage_intent": self.coverage_intent,
            "requirement_contract_status": self.requirement_contract_status,
            "domain_plans": {name: self.domain_plans[name].to_dict()
                             for name in DOMAINS if name in self.domain_plans},
        }


# --------------------------------------------------------------------------
# Core semantic-bridge fields (objective / stimulus / checker / coverage)
# --------------------------------------------------------------------------

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def derive_objective(record: Dict[str, Any]) -> str:
    """objective is built ONLY from the record's own `feature` +
    `expected_result` text -- never invented, and never resolved by anything
    other than requirement_contract.is_resolved()'s own sentinel rule
    (reused, not re-typed, so "TBD"/"UNKNOWN"/etc. cannot silently read as a
    real objective here either)."""
    feature = record.get("feature")
    expected = record.get("expected_result")
    feature_ok = requirement_contract.is_resolved(feature, "feature")
    expected_ok = requirement_contract.is_resolved(expected, "expected_result")
    if not feature_ok and not expected_ok:
        return ("OBJECTIVE_UNKNOWN: requirement record resolves neither 'feature' nor "
                "'expected_result'")
    parts = []
    if feature_ok:
        parts.append(f"Verify {_text(feature)}")
    if expected_ok:
        parts.append(f"such that {_text(expected)}")
    return " ".join(parts)


def derive_stimulus_intent(record: Dict[str, Any]) -> str:
    stimulus = record.get("stimulus")
    if not requirement_contract.is_resolved(stimulus, "stimulus"):
        return "STIMULUS_INTENT_UNKNOWN: requirement record does not resolve 'stimulus'"
    return _text(stimulus)


def derive_checker_intent(record: Dict[str, Any]) -> str:
    checker = record.get("checker")
    if not requirement_contract.is_resolved(checker, "checker"):
        return "CHECKER_INTENT_UNKNOWN: requirement record does not resolve 'checker'"
    return _text(checker)


def derive_coverage_intent(record: Dict[str, Any]) -> str:
    coverage = record.get("coverage_intent")
    if not requirement_contract.is_resolved(coverage, "coverage_intent"):
        return "COVERAGE_INTENT_UNKNOWN: requirement record does not resolve 'coverage_intent'"
    return _text(coverage)


def _requirement_contract_status(record: Dict[str, Any]) -> Dict[str, Any]:
    """Carries requirement_contract.py's own verdict on the SOURCE record
    through verbatim -- reused, never re-checked by hand. A record that does
    not declare `contract_schema_version` is reported as such rather than run
    through schema validation it never opted into."""
    if not isinstance(record, dict):
        return {"contract_shaped": False, "downstream_consumable": None,
                "reason": "record is not a dict"}
    if not requirement_contract.declares_contract_shape(record):
        return {"contract_shaped": False, "downstream_consumable": None,
                "declared_status": record.get("status"),
                "reason": ("record does not declare contract_schema_version; "
                           "requirement_contract.py's richer status/consumability check "
                           "was not run against it")}
    try:
        ok, reason = requirement_contract.downstream_consumable(record)
    except Exception as exc:  # contract-shaped but content the analyzer rejects
        return {"contract_shaped": True, "downstream_consumable": None,
                "declared_status": record.get("status"),
                "reason": f"requirement_contract analysis raised: {exc}"}
    return {"contract_shaped": True, "downstream_consumable": ok, "reason": reason,
            "declared_status": record.get("status")}


# --------------------------------------------------------------------------
# Per-domain sub-planners
# --------------------------------------------------------------------------

def plan_state_machine(record: Dict[str, Any]) -> DomainSubPlan:
    """Reuses protocol_capability.capability_for()/derive_status() -- the
    real, code-derived answer to "which protocols have a state-graph model
    module" (e.g. PCIe's ltssm_top_level_state_graph). Never a second state
    model, and never a guess at which states/transitions exist beyond what
    that registry's own `models`/`does_not_model` tuples say."""
    protocol = record.get("protocol")
    if not requirement_contract.is_resolved(protocol, "protocol"):
        return DomainSubPlan(
            domain=DOMAIN_STATE_MACHINE, applicable=False,
            dut_evidence_status=NOT_APPLICABLE,
            dut_evidence_reason=("requirement record names no protocol/interface to look up "
                                  "a state-machine model for"),
        )
    cap = protocol_capability.capability_for(str(protocol))
    if cap is None:
        return DomainSubPlan(
            domain=DOMAIN_STATE_MACHINE, applicable=True,
            dut_evidence_status=NOT_AVAILABLE,
            dut_evidence_reason=(f"protocol_capability.capability_for({protocol!r}) returned "
                                  "no registered capability entry for this protocol"),
            dut_evidence_source="dv_harness.protocol_capability.capability_for",
        )
    cap_status = protocol_capability.derive_status(cap)
    model = cap.model
    state_models = tuple(m for m in (model.models if model else ()) if "state" in m.lower())
    if not state_models:
        reason = (f"capability_status is {cap_status}; " + (
            f"model module {model.module} declares no state-graph model "
            f"(models={list(model.models)!r})" if model is not None else
            "no protocol-specific model module exists for this protocol (generic skeleton only)"
        ))
        return DomainSubPlan(
            domain=DOMAIN_STATE_MACHINE, applicable=True,
            dut_evidence_status=NOT_AVAILABLE, dut_evidence_reason=reason,
            dut_evidence_source="dv_harness.protocol_capability.capability_for",
            dut_evidence={"protocol": cap.protocol, "capability_status": cap_status},
        )
    return DomainSubPlan(
        domain=DOMAIN_STATE_MACHINE, applicable=True,
        dut_evidence_status=DUT_EVIDENCE_FOUND,
        dut_evidence_source="dv_harness.protocol_capability.capability_for",
        dut_evidence={"protocol": cap.protocol, "capability_status": cap_status,
                      "state_models": list(state_models),
                      "does_not_model": list(model.does_not_model)},
        plan_notes=[f"a real state-graph model exists ({', '.join(state_models)}); "
                    "stimulus/coverage intent for this domain should target its declared "
                    "transitions, never a re-derived state model"],
    )


def plan_register_csr(record: Dict[str, Any],
                       sys_regmap_doc: Optional[Dict[str, Any]]) -> DomainSubPlan:
    """Reuses sys_regmap.required_preconditions()/unverifiable_bits(), scoped
    to the requirement's own protocol/feature as the governed interface --
    the same real mode-determining-bit classification init_seq.py's Gate-2
    precondition check already uses, never a second CSR reader."""
    interface = record.get("protocol") if requirement_contract.is_resolved(
        record.get("protocol"), "protocol") else record.get("feature")
    interface_resolved = requirement_contract.is_resolved(interface, "feature")
    if sys_regmap_doc is None:
        return DomainSubPlan(
            domain=DOMAIN_REGISTER_CSR, applicable=interface_resolved,
            dut_evidence_status=NOT_AVAILABLE if interface_resolved else NOT_APPLICABLE,
            dut_evidence_reason=(
                "no sys_regmap document was supplied (sys_regmap.py's own input contract -- "
                "a real chip-level programming-guide transcription or system RAL export)"
                if interface_resolved else
                "requirement record names no protocol/feature to scope mode-determining bits to"
            ),
        )
    if not interface_resolved:
        return DomainSubPlan(
            domain=DOMAIN_REGISTER_CSR, applicable=False,
            dut_evidence_status=NOT_APPLICABLE,
            dut_evidence_reason=("requirement record names no protocol/feature to scope "
                                  "mode-determining bits to"),
        )
    try:
        sys_regmap.validate_sys_regmap(sys_regmap_doc)
        required = sys_regmap.required_preconditions(sys_regmap_doc, str(interface))
        unverifiable = sys_regmap.unverifiable_bits(sys_regmap_doc, str(interface))
    except sys_regmap.SysRegmapValidationError as exc:
        return DomainSubPlan(
            domain=DOMAIN_REGISTER_CSR, applicable=True,
            dut_evidence_status=NOT_AVAILABLE,
            dut_evidence_reason=f"supplied sys_regmap document failed schema validation: {exc}",
            dut_evidence_source="dv_harness.sys_regmap.validate_sys_regmap",
        )
    if not required and not unverifiable:
        return DomainSubPlan(
            domain=DOMAIN_REGISTER_CSR, applicable=True,
            dut_evidence_status=NOT_AVAILABLE,
            dut_evidence_reason=(f"no mode-determining bit in the supplied sys_regmap document "
                                  f"governs interface {interface!r}"),
            dut_evidence_source="dv_harness.sys_regmap.mode_determining_bits",
            dut_evidence={"interface": str(interface)},
        )
    status = DUT_EVIDENCE_FOUND if required else DUT_EVIDENCE_PARTIAL
    reason = None if required else (
        f"{len(unverifiable)} mode-determining bit(s) govern {interface!r} but none document a "
        "required_value -- listed for a human reviewer, never guessed")
    return DomainSubPlan(
        domain=DOMAIN_REGISTER_CSR, applicable=True,
        dut_evidence_status=status, dut_evidence_reason=reason,
        dut_evidence_source="dv_harness.sys_regmap.required_preconditions+unverifiable_bits",
        dut_evidence={"interface": str(interface), "required_preconditions": required,
                      "unverifiable_bits": unverifiable},
        plan_notes=[f"{len(required)} verifiable precondition(s), {len(unverifiable)} "
                    "documented-but-unverifiable bit(s)"],
    )


def plan_interrupt(record: Dict[str, Any], idcr_report: Optional[Dict[str, Any]]) -> DomainSubPlan:
    """Reuses interrupt_dma_clock_reset_extraction.extract_interrupt_dma_clock_reset()'s
    own `interrupt_architecture` block verbatim -- never a second RTL/spec scan."""
    if idcr_report is None:
        return DomainSubPlan(
            domain=DOMAIN_INTERRUPT, applicable=True,
            dut_evidence_status=NOT_AVAILABLE,
            dut_evidence_reason=("no RTL/spec source files were supplied for "
                                  "interrupt_dma_clock_reset_extraction.py to scan"),
        )
    block = idcr_report.get("interrupt_architecture") or {}
    found = block.get("status") == "LOADED"
    notes = []
    if found:
        notes.append(
            f"{len(block.get('sources', []))} interrupt source(s); priority scheme "
            f"{block.get('priority_scheme', {}).get('status')}; masking scheme "
            f"{block.get('masking_scheme', {}).get('status')}")
    return DomainSubPlan(
        domain=DOMAIN_INTERRUPT, applicable=True,
        dut_evidence_status=DUT_EVIDENCE_FOUND if found else NOT_AVAILABLE,
        dut_evidence_reason=block.get("reason"),
        dut_evidence_source=("dv_harness.interrupt_dma_clock_reset_extraction."
                              "extract_interrupt_dma_clock_reset"),
        dut_evidence=block, plan_notes=notes,
    )


def plan_reset_clock(record: Dict[str, Any], idcr_report: Optional[Dict[str, Any]]) -> DomainSubPlan:
    """Reuses the SAME extract_interrupt_dma_clock_reset() call's
    `clock_reset_extension` block -- deliberately the identical report object
    plan_interrupt() reads, so a caller supplying one set of source_paths
    gets both domains from a single real scan."""
    if idcr_report is None:
        return DomainSubPlan(
            domain=DOMAIN_RESET_CLOCK, applicable=True,
            dut_evidence_status=NOT_AVAILABLE,
            dut_evidence_reason=("no RTL/spec source files were supplied for "
                                  "interrupt_dma_clock_reset_extraction.py to scan"),
        )
    block = idcr_report.get("clock_reset_extension") or {}
    found = block.get("status") == "LOADED"
    notes = []
    if found:
        notes.append(f"{len(block.get('clocks', []))} clock(s), "
                      f"{len(block.get('resets', []))} reset(s)")
    return DomainSubPlan(
        domain=DOMAIN_RESET_CLOCK, applicable=True,
        dut_evidence_status=DUT_EVIDENCE_FOUND if found else NOT_AVAILABLE,
        dut_evidence_reason=block.get("reason"),
        dut_evidence_source=("dv_harness.interrupt_dma_clock_reset_extraction."
                              "extract_interrupt_dma_clock_reset"),
        dut_evidence=block, plan_notes=notes,
    )


def plan_low_power(record: Dict[str, Any], *,
                    power_intent_report: Optional["power_intent.PowerIntentReport"] = None,
                    upf_paths: Optional[Sequence] = None) -> DomainSubPlan:
    """DIRECTLY reuses power_intent.py's UPF model as the DUT-evidence
    source. A caller may hand in an already-computed
    `power_intent.analyze_power_intent()` report (the preferred path, so this
    module never re-parses UPF a caller already parsed), or `upf_paths` for
    this function to extract+analyze itself via the SAME two real functions
    -- never a re-derivation of power facts.

    `dut_evidence_status` is set to power_intent's OWN PASS/FAIL/NOT_AVAILABLE
    value, PRESERVED VERBATIM rather than translated into this module's
    DUT_EVIDENCE_*/NOT_AVAILABLE vocabulary -- section 224's own honest
    UNSUPPORTED/UNKNOWN framing is exactly what NOT_AVAILABLE already means
    there, and remapping it would blur that distinction rather than keep it.
    `status_vocabulary_source` names this so a reader is told, not left to
    assume, that this one domain's status belongs to a different vocabulary
    than its six siblings."""
    report = power_intent_report
    source = "dv_harness.power_intent.analyze_power_intent (caller-supplied report)"
    if report is None:
        if not upf_paths:
            return DomainSubPlan(
                domain=DOMAIN_LOW_POWER, applicable=True,
                dut_evidence_status=NOT_AVAILABLE,
                dut_evidence_reason=(
                    "no power_intent_report or upf_paths was supplied -- low-power DUT "
                    "evidence was never asked for; per section 224 this is never assumed "
                    "absent, it is reported as not asked"),
            )
        # extract_power_intent() itself never raises UpfParseError -- a
        # per-file parse failure is caught internally and recorded as a real
        # UPF_FILE_UNPARSEABLE issue on the returned intent (surfaced below,
        # inside dut_evidence["power_intent"]["issues"], since analyze_power_
        # intent() then honestly reports NOT_AVAILABLE over an intent with no
        # domains rather than this module inventing a second failure path).
        intent = power_intent.extract_power_intent(list(upf_paths))
        report = power_intent.analyze_power_intent(intent)
        source = "dv_harness.power_intent.extract_power_intent+analyze_power_intent"
    notes = []
    if report.status != "NOT_AVAILABLE":
        notes.append(f"{len(report.errors)} ERROR / {len(report.warnings)} WARNING finding(s) "
                      "from power_intent.py's own self-check")
    return DomainSubPlan(
        domain=DOMAIN_LOW_POWER, applicable=True,
        dut_evidence_status=report.status,
        dut_evidence_reason=report.reason,
        dut_evidence_source=source,
        dut_evidence=report.to_dict(),
        plan_notes=notes,
        status_vocabulary_source=(
            "dv_harness.power_intent.PowerIntentReport.status (PASS/FAIL/NOT_AVAILABLE, "
            "preserved verbatim rather than translated)"),
    )


def plan_error_recovery(record: Dict[str, Any]) -> DomainSubPlan:
    """No evidence producer exists in this harness for an error-injection or
    fault-recovery TARGET (an acceptable error rate, a required recovery-time
    bound, a fault taxonomy). Reported honestly rather than fabricated or
    silently omitted."""
    return DomainSubPlan(
        domain=DOMAIN_ERROR_RECOVERY, applicable=True,
        dut_evidence_status=ERROR_TARGET_UNKNOWN,
        dut_evidence_reason=(
            "this harness has no evidence producer for an error/fault-recovery target -- "
            "no module derives an acceptable error rate, a recovery-time bound, or a fault "
            "taxonomy from any real source; never fabricated"),
        plan_notes=["an error/recovery target for this requirement, if needed, must be sourced "
                    "from a primary spec/programming-guide citation by a human or a future "
                    "evidence producer"],
    )


def plan_performance(record: Dict[str, Any]) -> DomainSubPlan:
    """No evidence producer exists in this harness for a performance TARGET
    (throughput/latency/bandwidth). Reported honestly rather than fabricated
    or silently omitted."""
    return DomainSubPlan(
        domain=DOMAIN_PERFORMANCE, applicable=True,
        dut_evidence_status=PERFORMANCE_TARGET_UNKNOWN,
        dut_evidence_reason=(
            "this harness has no evidence producer for a performance target -- no module "
            "derives a throughput/latency/bandwidth number from any real source; never "
            "fabricated"),
        plan_notes=["a performance target for this requirement, if needed, must be sourced "
                    "from a primary spec/datasheet citation by a human or a future evidence "
                    "producer"],
    )


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def build_verification_intent_ir(
    record: Dict[str, Any],
    *,
    source_paths: Optional[Sequence] = None,
    sys_regmap_doc: Optional[Dict[str, Any]] = None,
    power_intent_report: Optional["power_intent.PowerIntentReport"] = None,
    upf_paths: Optional[Sequence] = None,
) -> VerificationIntentIR:
    """Build one VerificationIntentIR from one requirement record.

    `record` may be a full requirement_contract-shaped record or any plain
    dict carrying a subset of its fields (this module's input shape is
    deliberately duck-typed over requirement_contract.py's own field names --
    `requirement_id`/`feature`/`protocol`/`stimulus`/`expected_result`/
    `checker`/`coverage_intent` -- rather than requiring the full fifteen-
    field/schema-validated shape, so a partial requirement still gets an
    honest IR instead of a hard failure).

    `source_paths`/`sys_regmap_doc`/`power_intent_report`/`upf_paths` are all
    real DUT-evidence inputs a caller supplies; every one is optional, and its
    absence is reported per-domain as NOT_AVAILABLE with a real reason,
    never silently as a clean pass."""
    if not isinstance(record, dict):
        raise TypeError("record must be a dict (a requirement_contract-shaped record, or any "
                         "plain requirement dict carrying a subset of its fields)")

    idcr_report = idcr.extract_interrupt_dma_clock_reset(source_paths) if source_paths else None

    domain_plans: Dict[str, DomainSubPlan] = {
        DOMAIN_STATE_MACHINE: plan_state_machine(record),
        DOMAIN_REGISTER_CSR: plan_register_csr(record, sys_regmap_doc),
        DOMAIN_INTERRUPT: plan_interrupt(record, idcr_report),
        DOMAIN_RESET_CLOCK: plan_reset_clock(record, idcr_report),
        DOMAIN_ERROR_RECOVERY: plan_error_recovery(record),
        DOMAIN_LOW_POWER: plan_low_power(record, power_intent_report=power_intent_report,
                                          upf_paths=upf_paths),
        DOMAIN_PERFORMANCE: plan_performance(record),
    }
    req_id = record.get("requirement_id") or record.get("req_id")
    return VerificationIntentIR(
        requirement_id=str(req_id) if req_id else "REQUIREMENT_ID_UNKNOWN",
        objective=derive_objective(record),
        stimulus_intent=derive_stimulus_intent(record),
        checker_intent=derive_checker_intent(record),
        coverage_intent=derive_coverage_intent(record),
        domain_plans=domain_plans,
        requirement_contract_status=_requirement_contract_status(record),
    )


def build_verification_intent_ir_set(records: Sequence[Dict[str, Any]],
                                      **kwargs: Any) -> List[VerificationIntentIR]:
    """Same DUT-evidence inputs (source_paths/sys_regmap_doc/
    power_intent_report/upf_paths) applied across every record in `records` --
    those are DUT-level facts, not per-requirement ones, so they are supplied
    once rather than re-derived per requirement."""
    return [build_verification_intent_ir(r, **kwargs) for r in records]


# --------------------------------------------------------------------------
# Rendering + CLI (same execute_verb() convention as power_intent /
# golden_scenario / requirement_contract). Not wired into cli.py (this task's
# file-safety scope forbids editing it); see the structured-output field for
# the suggested `dv-harness verification-intent-ir` verb.
# --------------------------------------------------------------------------

def format_ir(ir: VerificationIntentIR) -> str:
    lines = [
        f"Verification Intent IR -- requirement {ir.requirement_id}",
        f"  {PROVENANCE_FIELD} : {ir.evidence_provenance}",
        f"  {ir.evidence_provenance_caveat}",
        f"  objective       : {ir.objective}",
        f"  stimulus_intent : {ir.stimulus_intent}",
        f"  checker_intent  : {ir.checker_intent}",
        f"  coverage_intent : {ir.coverage_intent}",
        "  domain plans:",
    ]
    for name in DOMAINS:
        plan = ir.domain_plans.get(name)
        if plan is None:
            continue
        suffix = f" ({plan.dut_evidence_reason})" if plan.dut_evidence_reason else ""
        lines.append(f"    {name:14s} : {plan.dut_evidence_status}{suffix}")
    return "\n".join(lines)


def execute_verb(requirements_path: str, *,
                  source_paths: Optional[Sequence[str]] = None,
                  sys_regmap_path: Optional[str] = None,
                  upf_paths: Optional[Sequence[str]] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Build the IR set for every requirement in `requirements_path` (a JSON
    file holding either a bare list of requirement records or
    `{"requirements": [...]}`). Exit codes: 0 built, 2 nothing to build / a
    supplied input could not be used."""
    try:
        raw = json.loads(Path(requirements_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"could not read/parse {requirements_path}: {exc}"
        return (json.dumps({"status": "NOT_AVAILABLE", "reason": msg}) if as_json else msg), 2

    records = raw.get("requirements") if isinstance(raw, dict) else raw
    if not isinstance(records, list) or not records:
        msg = f"{requirements_path} carries no requirement records"
        return (json.dumps({"status": "NOT_AVAILABLE", "reason": msg}) if as_json else msg), 2

    sys_regmap_doc = None
    if sys_regmap_path:
        try:
            sys_regmap_doc = sys_regmap.load_sys_regmap(sys_regmap_path)
        except (OSError, json.JSONDecodeError, sys_regmap.SysRegmapValidationError) as exc:
            msg = f"--sys-regmap {sys_regmap_path} could not be loaded: {exc}"
            return (json.dumps({"status": "NOT_AVAILABLE", "reason": msg}) if as_json else msg), 2

    irs = build_verification_intent_ir_set(
        records, source_paths=source_paths, sys_regmap_doc=sys_regmap_doc, upf_paths=upf_paths,
    )
    if as_json:
        out = json.dumps({"schema_version": SCHEMA_VERSION,
                           "requirements": [ir.to_dict() for ir in irs]}, indent=2)
    else:
        out = "\n\n".join(format_ir(ir) for ir in irs)
    return out, 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="verification-intent-ir")
    parser.add_argument("--requirements", required=True,
                         help="JSON file: a bare list of requirement records, or "
                              '{"requirements": [...]}')
    parser.add_argument("--source-paths", nargs="*", default=None,
                         help="RTL/spec text files for interrupt_dma_clock_reset_extraction.py")
    parser.add_argument("--sys-regmap", default=None, help="sys_regmap.json path")
    parser.add_argument("--upf", nargs="*", default=None, help="UPF file(s) for power_intent.py")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    out, code = execute_verb(
        args.requirements, source_paths=args.source_paths, sys_regmap_path=args.sys_regmap,
        upf_paths=args.upf, as_json=args.json,
    )
    print(out)
    return code


if __name__ == "__main__":  # pragma: no cover - thin shell
    sys.exit(main())
