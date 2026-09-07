"""Per-ARTIFACT completeness, a genuinely different axis from per-TARGET missing-artifact detection.

`target_conditioned_missing_artifact_detector.py` answers "which artifact CATEGORIES are missing
for downstream target T" -- a per-(target, category) presence question, three-valued
(PRESENT / MISSING / NOT_ASSESSED) at the granularity of a whole category (`vip_config_dump`,
`register_map`, `waiver_ledger`, ...). It never asks the orthogonal question this module answers:
given that a category IS present, is that ARTIFACT itself internally complete -- does it actually
carry the specific sub-facts a real downstream consumer of that artifact needs, or is it a
half-populated stand-in that merely satisfies "present == True" while missing the content that
makes it usable?

Before writing this module, this repo's real per-category producers were checked for whether any
of them already answers this (per the REUSE OVER REINVENT rule): `env_manifest.py`'s per-layer
`status`/`reason`, `requirement_contract.py`'s five-value status, `golden_scenario.py`'s capsule
fields, `waiver_store.py`'s derived per-waiver status, `signoff_export.py`'s per-field CAPTURED/
NOT_AVAILABLE, `connectivity.py`'s bind-tier classification, and several others each answer this
question -- but only for their OWN one artifact category, in their OWN incompatible vocabulary
(COMPUTED/PARTIAL/NOT_AVAILABLE here, VALID/EXPIRED/REVOKED there, CAPTURED/NOT_AVAILABLE
elsewhere). Nothing joins them into one per-artifact-category completeness table sharing a single,
explicit, named list of the real sub-facts each category needs -- exactly the same gap
`target_conditioned_missing_artifact_detector.py`'s own docstring describes for the per-target
question ("no code in this repo asked ... a target-specific answer"), one level down.

This module is deliberately the SMALL, additive piece that closes that: a fixed table,
`ARTIFACT_REQUIRED_SUBFACTS`, mapping each of the SAME artifact category ids
`target_conditioned_missing_artifact_detector.ARTIFACT_CATEGORY_DESCRIPTIONS` already declares
(imported here, never duplicated -- there is exactly one place in this repo that names the real
artifact-category vocabulary) to the handful of real, concretely-named sub-facts that category's
own real downstream consumer in this codebase actually needs before the artifact is genuinely
complete, each sub-fact carrying its own per-category reason (never a shared generic reason).

**Three-valued sub-fact presence, never guessed -- the identical discipline
`target_conditioned_missing_artifact_detector.py` already applies one level up, reapplied here at
the sub-fact level.** A sub-fact in the caller's inventory can be `True` (confirmed present),
`False` (confirmed absent), or anything else / omitted (NOT_ASSESSED). An omitted key is never
silently read as present (which would let a half-populated artifact claim completeness it never
earned) and never silently read as absent either (which would report a false missing-sub-fact
finding about something nobody has actually checked yet).

**Per this batch's low-collision environment** (per the confirmed real-time state: the only other
work in flight is a documentation-writing workflow that does not touch `dv_harness/` code), this
module imports directly from `target_conditioned_missing_artifact_detector.py` rather than
duplicating its category vocabulary -- there is no file-safety reason to duck-type that import
away, unlike several other same-day modules in this repo that were built under real concurrent
code-editing pressure.

**The overall verdict per artifact is the strict worst of what was found**, mirroring
`target_conditioned_missing_artifact_detector.py`'s own fold rule and this project's Worst-Wins
Composite Gates house rule: any confirmed-MISSING required sub-fact makes the artifact's status
`ARTIFACT_INCOMPLETE` (naming every missing sub-fact, each with its own reason) even if every other
sub-fact is present; with none missing but at least one NOT_ASSESSED, the status is
`ARTIFACT_ASSESSMENT_INCOMPLETE`; only when every required sub-fact for that category reports
confirmed-present does the status read `ARTIFACT_COMPLETE`. An unrecognized category is
`ARTIFACT_UNKNOWN_CATEGORY` with no fabricated sub-fact findings -- inventing a plausible-looking
sub-fact list for a category this module does not define would be exactly the fabrication the
Evidence Truth Rule forbids.

This module decides and authorizes nothing beyond classification: it reads no file, runs no build,
job, or gate, and there is deliberately no stage gate -- an `ArtifactCompletenessReport` is an
input to a caller's own downstream decision (e.g. whether to trust an artifact category the
target-conditioned detector already reported PRESENT), never a substitute for one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dv_harness.target_conditioned_missing_artifact_detector import (
    ARTIFACT_CATEGORY_DESCRIPTIONS,
)

# --- Sub-fact status vocabulary ----------------------------------------------
# Deliberately the same three-valued shape target_conditioned_missing_artifact_detector.py's own
# PRESENT/MISSING/NOT_ASSESSED uses for a whole category, reapplied here one level down to a
# single sub-fact of one artifact. Distinct module-level names so the two modules' constants never
# collide when both are imported into one caller.

SUBFACT_PRESENT = "PRESENT"
SUBFACT_MISSING = "MISSING"
SUBFACT_NOT_ASSESSED = "NOT_ASSESSED"
_SUBFACT_STATUSES = frozenset({SUBFACT_PRESENT, SUBFACT_MISSING, SUBFACT_NOT_ASSESSED})

ARTIFACT_COMPLETE = "ARTIFACT_COMPLETE"
ARTIFACT_INCOMPLETE = "ARTIFACT_INCOMPLETE"
ARTIFACT_ASSESSMENT_INCOMPLETE = "ARTIFACT_ASSESSMENT_INCOMPLETE"
ARTIFACT_UNKNOWN_CATEGORY = "ARTIFACT_UNKNOWN_CATEGORY"
_ARTIFACT_STATUSES = frozenset(
    {ARTIFACT_COMPLETE, ARTIFACT_INCOMPLETE, ARTIFACT_ASSESSMENT_INCOMPLETE, ARTIFACT_UNKNOWN_CATEGORY}
)


# --- The category -> required-subfacts table ---------------------------------
# A small, explicit table over the SAME category ids ARTIFACT_CATEGORY_DESCRIPTIONS already
# declares. Each sub-fact names a concrete, real fact a real downstream consumer of that artifact
# in this codebase actually needs -- never a generic "needs more content" placeholder, and never a
# sub-fact invented for a category it is not genuinely tied to.

@dataclass(frozen=True)
class SubFactRequirement:
    subfact_id: str
    reason: str


ARTIFACT_REQUIRED_SUBFACTS: Dict[str, Tuple[SubFactRequirement, ...]] = {
    "vip_config_dump": (
        SubFactRequirement(
            "vip_instance_identity",
            "vip_config_dump is only usable once it names a real VIP instance path and type "
            "(env.manifest.json's vip_config.vip_instances shape) -- a dump that names no real "
            "instance is a category marked present with nothing inside it.",
        ),
        SubFactRequirement(
            "vip_release_resolved",
            "vip_config_dump must resolve to a real installed VIP release (vip_release's own "
            "status, from the $DESIGNWARE_HOME scan) -- an unresolved release means the dump "
            "names a VIP nobody has confirmed is actually installed.",
        ),
    ),
    "dut_rtl_source": (
        SubFactRequirement(
            "module_hierarchy_parsed",
            "dut_rtl_source is only usable once verible has actually parsed a real module "
            "hierarchy -- a category marked present with an empty module list has nothing for a "
            "generator to bind against.",
        ),
        SubFactRequirement(
            "port_table_parsed",
            "dut_rtl_source's parsed modules must carry a real port table -- module names alone, "
            "with no ports, give a generator no signal list to connect a VIP interface to.",
        ),
    ),
    "register_map": (
        SubFactRequirement(
            "register_fields_present",
            "register_map is only usable once it carries real field/offset facts -- a category "
            "marked present with no field entries has nothing for a register-access sequence to "
            "read.",
        ),
        SubFactRequirement(
            "register_access_types_present",
            "register_map's fields must each carry a real access type (RW/RO/WO/W1C/...) -- a "
            "field with no declared access type cannot be checked for a legal read or write.",
        ),
    ),
    "bind_topology": (
        SubFactRequirement(
            "bind_entries_present",
            "bind_topology is only usable once it carries at least one real bind entry -- a "
            "category marked present with zero entries has nothing for connectivity.py's tier "
            "gate to validate.",
        ),
        SubFactRequirement(
            "bind_entries_tier_validated",
            "bind_topology's entries must each carry a real classified tier (T1-T4) -- an "
            "untiered entry cannot be checked against Bind-Location Rule 5's confidence policy "
            "before a bind file is written.",
        ),
    ),
    "phy_boundary_decision": (
        SubFactRequirement(
            "boundary_layer_decided",
            "phy_boundary_decision is only usable once the serial/parallel mount layer has "
            "actually been decided -- an UNDECIDABLE boundary is a category marked present that "
            "answers nothing Bind-Location Rule 5 needs.",
        ),
        SubFactRequirement(
            "boundary_bindable_determined",
            "phy_boundary_decision must resolve whether the decided layer is actually bindable -- "
            "a decision with no resolved bindable flag cannot stop a monitor being bound where it "
            "would decode nothing.",
        ),
    ),
    "vip_symbol_index": (
        SubFactRequirement(
            "class_declarations_indexed",
            "vip_symbol_index is only usable once it carries real indexed VIP class declarations "
            "-- a category marked present with no class list gives vip_api_card.py nothing to "
            "prove a cited class against.",
        ),
        SubFactRequirement(
            "method_declarations_indexed",
            "vip_symbol_index's classes must carry real indexed method declarations with "
            "file:line locations -- without them a generated sequence's method call cannot be "
            "proven to exist on the class it is called against.",
        ),
    ),
    "regression_evidence": (
        SubFactRequirement(
            "job_records_present",
            "regression_evidence is only usable once it carries at least one real recorded LSF "
            "job -- a category marked present with no job records carries no proof a regression "
            "ever actually ran.",
        ),
        SubFactRequirement(
            "normalized_evidence_present",
            "regression_evidence's jobs must carry real normalized evidence rows (vip_distill's "
            "own envelope) -- a job record with no normalized evidence cannot be read back as a "
            "real PASS/FAIL verdict.",
        ),
    ),
    "coverage_summary": (
        SubFactRequirement(
            "coverage_categories_present",
            "coverage_summary is only usable once it carries real coverage categories -- a "
            "category marked present with an empty category list has no functional-coverage "
            "content to report.",
        ),
        SubFactRequirement(
            "coverage_bin_counts_present",
            "coverage_summary's categories must each carry real bins_total/bins_hit counts -- a "
            "category name with no bin counts cannot compute a Closure percentage.",
        ),
    ),
    "waiver_ledger": (
        SubFactRequirement(
            "waiver_ledger_present",
            "waiver_ledger is only usable once the real waiver store (waivers.json) actually "
            "exists and is readable -- a category marked present with no readable store carries "
            "no waiver a status can be derived from.",
        ),
        SubFactRequirement(
            "every_waiver_has_expiry_or_trigger",
            "waiver_ledger's recorded waivers must each carry a real expiry or revalidation "
            "trigger -- a waiver with neither cannot have its VALID/EXPIRED/REVALIDATION_REQUIRED "
            "status derived, and would sit self-attested forever.",
        ),
    ),
    "golden_scenario_capsule": (
        SubFactRequirement(
            "capsule_verified_sha_present",
            "golden_scenario_capsule is only usable once it carries a real verified_sha -- a "
            "capsule marked present with no recorded commit identity cannot be checked for "
            "freshness against the current RTL/TB.",
        ),
        SubFactRequirement(
            "capsule_evidence_id_present",
            "golden_scenario_capsule must carry a real evidence_id linking to a normalized_"
            "evidence PASS row -- without it the capsule's own claimed PASS is unverifiable "
            "self-attestation, not a recorded reproducibility record.",
        ),
    ),
    "signoff_gate_evidence": (
        SubFactRequirement(
            "signoff_stage_gates_run",
            "signoff_gate_evidence is only usable once the real SIGNOFF-stage gates were actually "
            "run -- a category marked present with no gate-run record carries no evidence "
            "distinguishing a real run from an agent's own unverified claim.",
        ),
        SubFactRequirement(
            "signoff_stage_gates_cleared",
            "signoff_gate_evidence's SIGNOFF-stage gates must have actually cleared -- a run that "
            "did not pass every real gate is not evidence a project is ready to freeze a baseline.",
        ),
    ),
    "requirement_contract": (
        SubFactRequirement(
            "requirement_status_complete",
            "requirement_contract is only usable once its own re-derived status reads COMPLETE "
            "(requirement_contract.py's derive_status()) -- a record marked present that is "
            "actually PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN is not settled enough for a "
            "generator to treat as a requirement.",
        ),
        SubFactRequirement(
            "requirement_no_unresolved_ambiguity_or_contradiction",
            "requirement_contract's filed ambiguities/contradictions must each be resolved -- an "
            "unresolved one hidden behind a present-looking record is exactly the "
            "UNRESOLVED_BLOCKER_HIDDEN defect requirement_contract.py's own analysis exists to "
            "catch.",
        ),
    ),
    "testplan_correspondence": (
        SubFactRequirement(
            "testplan_items_present",
            "testplan_correspondence is only usable once real vPlan items are actually "
            "enumerated -- a category marked present with an empty item list has no testplan/"
            "vPlan/coverage join to report.",
        ),
        SubFactRequirement(
            "testplan_items_linked_to_coverage",
            "testplan_correspondence's items must resolve LINKED (a real measured coverage bin), "
            "not NOT_CHECKED -- a vPlan item whose coverage claim was never actually checked is "
            "merely claimed, not correspondence.",
        ),
    ),
    "regression_list": (
        SubFactRequirement(
            "regression_list_present",
            "regression_list is only usable once the real regression-list/command-inventory "
            "artifact actually exists -- a category marked present with no readable list carries "
            "nothing to hand to LSF.",
        ),
        SubFactRequirement(
            "regression_list_nonempty",
            "regression_list's inventory must enumerate at least one real test pattern -- an "
            "empty inventory is not a set of tests to submit.",
        ),
    ),
}

ARTIFACT_CATEGORY_NAMES: Tuple[str, ...] = tuple(ARTIFACT_REQUIRED_SUBFACTS.keys())


# --- Classification -----------------------------------------------------------

def _classify_subfact_presence(raw_value: Any) -> str:
    """True -> PRESENT, False -> MISSING, anything else (including an absent key, represented by
    the caller passing _SENTINEL_ABSENT) -> NOT_ASSESSED. Never guessed either direction from an
    ambiguous value (None, a string, a number, ...).
    """
    if raw_value is True:
        return SUBFACT_PRESENT
    if raw_value is False:
        return SUBFACT_MISSING
    return SUBFACT_NOT_ASSESSED


_SENTINEL_ABSENT = object()


@dataclass(frozen=True)
class SubFactFinding:
    subfact_id: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in _SUBFACT_STATUSES:
            raise ValueError(f"unrecognized sub-fact status: {self.status!r}")


@dataclass(frozen=True)
class ArtifactCompletenessReport:
    category: str
    category_known: bool
    artifact_status: str
    description: str = ""
    findings: Tuple[SubFactFinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.artifact_status not in _ARTIFACT_STATUSES:
            raise ValueError(f"unrecognized artifact status: {self.artifact_status!r}")

    @property
    def missing_subfacts(self) -> Tuple[str, ...]:
        return tuple(f.subfact_id for f in self.findings if f.status == SUBFACT_MISSING)

    @property
    def not_assessed_subfacts(self) -> Tuple[str, ...]:
        return tuple(f.subfact_id for f in self.findings if f.status == SUBFACT_NOT_ASSESSED)

    @property
    def present_subfacts(self) -> Tuple[str, ...]:
        return tuple(f.subfact_id for f in self.findings if f.status == SUBFACT_PRESENT)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "category_known": self.category_known,
            "artifact_status": self.artifact_status,
            "description": self.description,
            "findings": [
                {"subfact_id": f.subfact_id, "status": f.status, "reason": f.reason}
                for f in self.findings
            ],
            "missing_subfacts": list(self.missing_subfacts),
            "not_assessed_subfacts": list(self.not_assessed_subfacts),
            "present_subfacts": list(self.present_subfacts),
        }


def known_artifact_categories() -> Tuple[str, ...]:
    """The category ids this module has a real required-subfact table for."""
    return ARTIFACT_CATEGORY_NAMES


def required_subfacts_for_category(category: str) -> Tuple[SubFactRequirement, ...]:
    """The (subfact_id, reason) pairs a real artifact category requires, or empty for a category
    this module does not define a subfact table for.
    """
    return ARTIFACT_REQUIRED_SUBFACTS.get(category, ())


def assess_artifact_completeness(
    category: str,
    subfact_inventory: Optional[Mapping[str, Any]] = None,
) -> ArtifactCompletenessReport:
    """Derive the SPECIFIC sub-facts missing for artifact `category`'s own internal completeness,
    from this module's own explicit category -> required-subfacts table, cross-checked against
    `subfact_inventory` -- a plain caller-supplied mapping of subfact_id -> True (confirmed
    present) / False (confirmed absent) / anything-else-or-omitted (not assessed).

    An unrecognized category yields `ARTIFACT_UNKNOWN_CATEGORY` and no per-subfact findings: this
    module never invents a plausible-looking subfact list for a category it does not define.
    """
    requirements = ARTIFACT_REQUIRED_SUBFACTS.get(category)
    description = ARTIFACT_CATEGORY_DESCRIPTIONS.get(category, "")
    if requirements is None:
        return ArtifactCompletenessReport(
            category=category,
            category_known=False,
            artifact_status=ARTIFACT_UNKNOWN_CATEGORY,
            description=description,
        )

    inv = subfact_inventory or {}
    findings: List[SubFactFinding] = []
    for req in requirements:
        raw_value = inv[req.subfact_id] if req.subfact_id in inv else _SENTINEL_ABSENT
        status = _classify_subfact_presence(raw_value)
        findings.append(SubFactFinding(subfact_id=req.subfact_id, status=status, reason=req.reason))

    if any(f.status == SUBFACT_MISSING for f in findings):
        overall = ARTIFACT_INCOMPLETE
    elif any(f.status == SUBFACT_NOT_ASSESSED for f in findings):
        overall = ARTIFACT_ASSESSMENT_INCOMPLETE
    else:
        overall = ARTIFACT_COMPLETE

    return ArtifactCompletenessReport(
        category=category,
        category_known=True,
        artifact_status=overall,
        description=description,
        findings=tuple(findings),
    )


def assess_all_artifacts(
    inventories: Mapping[str, Mapping[str, Any]],
) -> Dict[str, ArtifactCompletenessReport]:
    """Convenience batch form: assess every category the caller supplied an inventory for, in the
    order given. A category the caller never mentions is simply not assessed here -- this function
    never assumes silence means completeness, and never invents an empty inventory for a category
    nobody asked about.
    """
    return {
        category: assess_artifact_completeness(category, subfacts)
        for category, subfacts in inventories.items()
    }


def render_report_text(report: ArtifactCompletenessReport) -> str:
    lines: List[str] = [f"category: {report.category}  artifact_status: {report.artifact_status}"]
    if not report.category_known:
        known = ", ".join(known_artifact_categories())
        lines.append(f"  unrecognized category -- known categories: {known}")
        return "\n".join(lines)
    for f in report.findings:
        lines.append(f"  [{f.status:<12}] {f.subfact_id}: {f.reason}")
    return "\n".join(lines)


def assert_table_covers_declared_categories() -> None:
    """Every category_id in ARTIFACT_REQUIRED_SUBFACTS is a real category
    target_conditioned_missing_artifact_detector.py already declares, and every requirement it
    lists carries a real, non-empty, per-category reason. Run at import time so a table entry
    citing an unrecognized category, or an empty reason, fails loudly rather than silently
    rendering a hollow finding.
    """
    for category, reqs in ARTIFACT_REQUIRED_SUBFACTS.items():
        if category not in ARTIFACT_CATEGORY_DESCRIPTIONS:
            raise AssertionError(
                f"artifact_completeness declares an unrecognized category {category!r} -- not in "
                "target_conditioned_missing_artifact_detector.ARTIFACT_CATEGORY_DESCRIPTIONS"
            )
        if not reqs:
            raise AssertionError(f"category {category!r} declares zero required sub-facts")
        seen_ids = set()
        for req in reqs:
            if not req.subfact_id or not req.subfact_id.strip():
                raise AssertionError(f"category {category!r} declares a blank subfact_id")
            if req.subfact_id in seen_ids:
                raise AssertionError(
                    f"category {category!r} declares subfact_id {req.subfact_id!r} more than once"
                )
            seen_ids.add(req.subfact_id)
            if not req.reason or not req.reason.strip():
                raise AssertionError(
                    f"category {category!r} subfact {req.subfact_id!r} carries an empty reason"
                )


assert_table_covers_declared_categories()


# --- Minimal ad hoc front door -------------------------------------------------
# No dv-harness CLI verb: cli.py must not be touched by this task. `python -m
# dv_harness.artifact_completeness <CATEGORY> [subfact_inventory.json]` is the only entry point,
# the same disclosed "python -m only" convention target_conditioned_missing_artifact_detector.py's
# own front door already uses.

def execute_verb(argv: Optional[Sequence[str]] = None) -> Tuple[int, ArtifactCompletenessReport, str]:
    import json
    import sys as _sys

    args = list(_sys.argv[1:] if argv is None else argv)
    if not args:
        text = "usage: artifact_completeness <CATEGORY> [subfact_inventory.json]\n" \
               f"known categories: {', '.join(known_artifact_categories())}"
        report = ArtifactCompletenessReport(
            category="", category_known=False, artifact_status=ARTIFACT_UNKNOWN_CATEGORY
        )
        return 2, report, text

    category = args[0]
    subfact_inventory: Dict[str, Any] = {}
    if len(args) > 1:
        with open(args[1], "r", encoding="utf-8") as fh:
            subfact_inventory = json.load(fh)

    report = assess_artifact_completeness(category, subfact_inventory)
    text = render_report_text(report)
    if report.artifact_status == ARTIFACT_UNKNOWN_CATEGORY:
        code = 2
    elif report.artifact_status in (ARTIFACT_INCOMPLETE, ARTIFACT_ASSESSMENT_INCOMPLETE):
        code = 1
    else:
        code = 0
    return code, report, text


def main(argv: Optional[Sequence[str]] = None) -> int:
    code, _report, text = execute_verb(argv)
    print(text)
    return code


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
