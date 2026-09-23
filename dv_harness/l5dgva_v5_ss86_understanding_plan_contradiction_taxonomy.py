"""dv_harness/l5dgva_v5_ss86_understanding_plan_contradiction_taxonomy.py --
L5DGVA V5 section 86 "Behavioral Proof of Understanding": the 6 named
example contradiction patterns as a closed taxonomy + a pure, deterministic
classifier over caller-declared boolean facts + the
`UNDERSTANDING_PLAN_CONTRADICTION` record schema section 86 itself names --
never a live comparison of a real generated plan against a real retrieved
understanding.

SCOPE DECISION. Section 86's own composite requirement
(`BehavioralProofOfUnderstanding_PASS` /
`UnderstandingPlanConsistency_PASS` /
`UnderstandingPlanContradictionGuard_PASS`) needs a real
`PhaseUnderstandingManifest` and a real generated architecture/plan to
actually compare -- that comparison is exactly the live-dispatch-dependent
half this session's prior agents (CAP236 included) correctly left open, and
this module does not attempt it. What section 86 DOES also hand over,
independent of any live comparison, is a closed set of 6 concretely named
contradiction PATTERNS and the shape of the record it requires be created
when one fires (`UNDERSTANDING_PLAN_CONTRADICTION`). Both are genuinely
extractable as a schema + pure classifier today -- the same "build the
mechanism, defer the wiring" split
`autonomy_governance_failure_classifier.py` (V5 SS89, this session's own
sibling module for this same chapter) already used for an 11-value root-cause
taxonomy sitting right next to this one in the same document.

PRIMARY SOURCE, quoted verbatim
(`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v5.md:1450-1470`):

    ## 86. Behavioral Proof of Understanding

    Reading a file, finding KC, loading a skill or listing a reference
    directory is not proof of understanding. Retrieved methods must be
    reflected in the architecture and plan.

    Before execution compare understanding vs plan.

    Examples that must block: - DE CPUWRITE exists but no APB/control-plane
    VIP in plan. - Reference partition compile exists but plan removes it. -
    Reference has material BLOCK bring-up but generated BLOCK is no-op. -
    External protocol requires Top IO but plan binds only internally. -
    Qualified Subsystem environments exist but System-Level plan regenerates
    them blindly. - Canonical reference filesystem entry points are
    relocated without justification.

    Create `UNDERSTANDING_PLAN_CONTRADICTION` and autonomously reconcile.

    Required: `BehavioralProofOfUnderstanding_PASS = true`
    `UnderstandingPlanConsistency_PASS = true`
    `UnderstandingPlanContradictionGuard_PASS = true`

REUSE CHECK (before writing this module). `grep -rln
"BehavioralProofOfUnderstanding\\|UnderstandingPlanConsistency\\|
UnderstandingPlanContradictionGuard\\|UNDERSTANDING_PLAN_CONTRADICTION"
dv_harness/ dv_harness_tests/` returned zero hits before this file. The 6
example patterns individually reference concepts this codebase already
models elsewhere (`shared_bus_resource_registry.py` for control-plane
VIP/APB, `makefile_capability_parity_gate.py` for partition-compile
preservation, `branch_ownership_resolver.py` for BLOCK bring-up,
`bind_protocol_boundary_rule.py` for Top-IO-vs-internal binds,
`environment_mode_router.py`/`soc_environment_composer.py` for qualified
Subsystem reuse, `reference_filesystem_parity_manifest.py` for entry-point
relocation) -- this module does not re-implement any of those detectors. It
only builds the ONE thing none of them build: the closed 6-pattern taxonomy
+ classifier + `UNDERSTANDING_PLAN_CONTRADICTION` record schema that section
86 itself names, operating over whatever boolean facts a caller (potentially
one of those other modules) already declares.

WHAT THIS MODULE ACTUALLY DOES.
  1. `CONTRADICTION_PATTERNS` -- the 6 named examples, verbatim, each
     reduced to a caller-supplied boolean-fact pair
     (`understanding_fact_key`, `plan_fact_key`) and the exact trigger rule
     section 86's own prose states for it.
  2. `classify_understanding_plan_contradictions(facts)` -- a pure,
     deterministic function: for each of the 6 patterns, evaluates its rule
     against a caller-supplied `Dict[str, bool]`. A fact key absent from the
     dict is treated as `False` (not "unknown" and never silently treated as
     "satisfied") -- so calling this with an empty dict correctly reports
     ZERO contradictions found, not because none exist, but because no
     evidence was supplied to look for any; this module never inflates an
     absence of input into a false negative OR a false positive.
  3. `UnderstandingPlanContradictionRecord` -- section 86's own
     `UNDERSTANDING_PLAN_CONTRADICTION` object, with the fields its two
     sentences ("Create ... and autonomously reconcile") actually imply:
     which pattern, which phase, the two conflicting facts' evidence
     citations, and a `reconciliation_verdict` the record starts `None` and
     only a caller can set to `"RECONCILED"`.
  4. `behavioral_proof_of_understanding_gate(records)` -- PASS only if every
     triggered contradiction in the supplied record list has
     `reconciliation_verdict == "RECONCILED"`; an empty list is reported
     `INSUFFICIENT_EVIDENCE`, never defaulted to PASS.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.
  * It does not retrieve a real `PhaseUnderstandingManifest` or a real
    generated plan, and does not itself decide the boolean facts it
    classifies -- those must come from a caller with real evidence (one of
    the reused detector modules named above, or a human). Calling this
    module in isolation, with invented facts, would be exactly the
    "attested string, not evidence" failure mode the Evidence Truth Rule and
    the No-Golden-Reference-Content-Mining discipline both forbid; this
    module's own tests only ever exercise it with clearly-labeled synthetic
    fixture facts, never a claim about this repo's own current plan state.
  * It does not autonomously reconcile anything -- section 86's own
    "autonomously reconcile" clause is a live remediation action this
    module has no mechanism to perform; it only tracks whether reconciliation
    already happened, structurally.
  * `BehavioralProofOfUnderstanding_PASS` /
    `UnderstandingPlanConsistency_PASS` /
    `UnderstandingPlanContradictionGuard_PASS` all stay honestly
    NOT_ATTEMPTED by this module for this codebase's own real state -- no
    fact-supplying caller is wired to it yet. That wiring is the genuinely
    live-dispatch-dependent residual CAP236 (correctly) left open.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

#: The 6 named example patterns, verbatim order, each as
#: (pattern_id, understanding_fact_key, plan_fact_key, description).
#: Trigger rule for every one of them, per section 86's own prose shape
#: ("X exists/true but plan does NOT reflect X"): the understanding fact is
#: True and the plan fact is False (or absent, treated as False).
CONTRADICTION_PATTERNS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "DE_CPUWRITE_NO_CONTROL_PLANE_VIP",
        "de_cpuwrite_exists",
        "control_plane_vip_in_plan",
        "DE CPUWRITE exists but no APB/control-plane VIP in plan.",
    ),
    (
        "REFERENCE_PARTITION_COMPILE_REMOVED_IN_PLAN",
        "reference_partition_compile_exists",
        "plan_preserves_partition_compile",
        "Reference partition compile exists but plan removes it.",
    ),
    (
        "REFERENCE_BLOCK_BRINGUP_BUT_GENERATED_NOOP",
        "reference_has_material_block_bringup",
        "generated_block_is_material",
        "Reference has material BLOCK bring-up but generated BLOCK is no-op.",
    ),
    (
        "EXTERNAL_PROTOCOL_TOPIO_BUT_PLAN_BINDS_INTERNALLY",
        "external_protocol_requires_top_io",
        "plan_binds_at_top_io",
        "External protocol requires Top IO but plan binds only internally.",
    ),
    (
        "QUALIFIED_SUBSYSTEM_EXISTS_BUT_PLAN_REGENERATES_BLINDLY",
        "qualified_subsystem_environments_exist",
        "system_level_plan_evaluates_reuse",
        "Qualified Subsystem environments exist but System-Level plan "
        "regenerates them blindly.",
    ),
    (
        "CANONICAL_FILESYSTEM_ENTRY_POINTS_RELOCATED_WITHOUT_JUSTIFICATION",
        "canonical_reference_filesystem_entry_points_relocated",
        "relocation_justification_recorded",
        "Canonical reference filesystem entry points are relocated without "
        "justification.",
    ),
)

PATTERN_IDS: Tuple[str, ...] = tuple(p[0] for p in CONTRADICTION_PATTERNS)


@dataclass(frozen=True)
class ContradictionFinding:
    pattern_id: str
    triggered: bool
    understanding_fact_key: str
    plan_fact_key: str
    description: str


def classify_understanding_plan_contradictions(
    facts: Dict[str, bool],
) -> Tuple[ContradictionFinding, ...]:
    """Pure, deterministic evaluation of the 6 `CONTRADICTION_PATTERNS`
    against caller-supplied `facts`. A missing key is treated as `False`.
    Returns one `ContradictionFinding` per pattern (triggered or not), never
    silently dropping a pattern the caller supplied no facts for."""
    findings = []
    for pattern_id, understanding_key, plan_key, description in CONTRADICTION_PATTERNS:
        understanding_true = bool(facts.get(understanding_key, False))
        plan_reflects_it = bool(facts.get(plan_key, False))
        triggered = understanding_true and not plan_reflects_it
        findings.append(
            ContradictionFinding(
                pattern_id=pattern_id,
                triggered=triggered,
                understanding_fact_key=understanding_key,
                plan_fact_key=plan_key,
                description=description,
            )
        )
    return tuple(findings)


RECONCILED = "RECONCILED"
UNRESOLVED = "UNRESOLVED"


@dataclass
class UnderstandingPlanContradictionRecord:
    """Section 86's own `UNDERSTANDING_PLAN_CONTRADICTION` object."""
    contradiction_id: str
    pattern_id: str
    phase: str
    understanding_evidence_ref: str
    plan_evidence_ref: str
    reconciliation_action: Optional[str] = None
    reconciliation_verdict: Optional[str] = None

    def __post_init__(self) -> None:
        if self.pattern_id not in PATTERN_IDS:
            raise ValueError(
                f"pattern_id {self.pattern_id!r} is not one of the 6 named "
                f"section-86 contradiction patterns: {PATTERN_IDS}"
            )


@dataclass(frozen=True)
class BehavioralProofVerdict:
    pass_: str  # "PASS" / "FAIL" / "INSUFFICIENT_EVIDENCE"
    unresolved_contradiction_ids: Tuple[str, ...]
    reason: str


def behavioral_proof_of_understanding_gate(
    records: Tuple[UnderstandingPlanContradictionRecord, ...],
) -> BehavioralProofVerdict:
    """PASS only if every record has `reconciliation_verdict == RECONCILED`.
    An empty tuple is `INSUFFICIENT_EVIDENCE` (this module has no way to
    know whether zero contradictions is real or simply un-surveyed) --
    never defaulted to PASS."""
    if not records:
        return BehavioralProofVerdict(
            pass_="INSUFFICIENT_EVIDENCE",
            unresolved_contradiction_ids=(),
            reason=(
                "No UNDERSTANDING_PLAN_CONTRADICTION records supplied -- "
                "BehavioralProofOfUnderstanding_PASS cannot be claimed from "
                "an absence of evidence."
            ),
        )
    unresolved = tuple(
        r.contradiction_id for r in records if r.reconciliation_verdict != RECONCILED
    )
    if unresolved:
        return BehavioralProofVerdict(
            pass_="FAIL",
            unresolved_contradiction_ids=unresolved,
            reason=(
                f"{len(unresolved)} of {len(records)} "
                f"UNDERSTANDING_PLAN_CONTRADICTION record(s) are not "
                f"RECONCILED: {list(unresolved)}."
            ),
        )
    return BehavioralProofVerdict(
        pass_="PASS",
        unresolved_contradiction_ids=(),
        reason=f"All {len(records)} recorded contradiction(s) are RECONCILED.",
    )
