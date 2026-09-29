"""Which artifacts are missing depends on WHAT the caller is trying to build next.

A verification harness accumulates many kinds of partial evidence over a project's life --
a VIP config dump, a parsed RTL port table, a coverage summary, a waiver ledger, a signed-off
gate history. "What's missing" is not one fixed checklist: an agent about to generate a
subsystem UVM environment needs a completely different subset of that evidence than an agent
about to export a signoff bundle, or one trying to decide whether functional coverage is closed
enough to report. Before this module, no code in this repo asked "missing FOR WHAT" -- every
existing readiness/gate reader (`generation_readiness.py`, `golden_flow_readiness.py`,
`functional_coverage_signoff.py`, `vip_learning_gate.py`, ...) answers its own single fixed
question well, but none of them takes a target name as an input and derives a target-specific
answer from it. A generic "you're missing some files" message is exactly the failure mode this
module exists to refuse: it names no category, gives a caller nothing to act on, and (per the
Evidence Truth Rule) risks becoming a vague catch-all that quietly covers for a table nobody
actually wrote down.

`dv_harness/target_conditioned_missing_artifact_detector.py` is that missing piece, and it is
deliberately small and self-contained. It defines ONE thing: a fixed table mapping a small,
explicit set of real downstream TARGETS to the specific artifact CATEGORIES each target needs,
with a per-(target, category) REASON string that says why that category matters for that
particular target (never a generic "need more files" line -- see `TARGET_ARTIFACT_TABLE`
below). Per this batch's file-safety scope, this module imports nothing from any other new
module in the batch and nothing from the claimed/frozen file list -- it accepts the caller's
current source-inventory facts as a plain, duck-typed mapping (`category_id -> True/False/other`)
rather than reading `env.manifest.json`, the evidence database, or any other artifact itself.
Wiring a real project's own facts into that mapping (e.g. from `env_manifest.py`'s per-layer
`status` fields, or `waiver_store.status_report()`) is the caller's job, not this module's --
exactly the boundary `subsystem_contract.py` draws between "assembles known facts" and
"discovers new ones", except this module does not even assemble; it only classifies.

**Three-valued presence, never guessed.** A category in the caller's inventory can be `True`
(confirmed present), `False` (confirmed absent -- someone actually checked and it is not there),
or anything else / simply omitted (NOT_ASSESSED -- nobody has reported on it either way). These
are never collapsed: an omitted key must not silently read as "present" (that would let a
half-populated inventory claim readiness it never earned) and must not silently read as "absent"
either (that would report a false MISSING finding about a category the caller genuinely has not
looked at yet). This is the same three-way honesty discipline `subsystem_contract.py`'s
`unknowns` list and `coverage_db_integrity.py`'s `MERGE_NOT_VERIFIABLE` verdict already apply in
their own domains, applied here to a single boolean-shaped fact per category.

**The overall verdict is the strict worst of what was found**, mirroring
`generation_readiness.py`'s own fold rule: any confirmed-MISSING required category makes the
target's overall status `MISSING_ARTIFACTS` (naming every one, each with its own reason) even if
every other category is present; with none missing but at least one NOT_ASSESSED, the status is
`INCOMPLETE_EVIDENCE` (a caller cannot be told "you are ready" when part of the picture was never
checked); only when every required category for that target reports confirmed-present does the
status read `READY`. An unrecognized target name is `UNKNOWN_TARGET` and yields no per-category
findings at all -- inventing a plausible-looking requirement list for a target this module does
not define would be exactly the fabrication the Evidence Truth Rule forbids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# --- Status vocabulary -------------------------------------------------------
# Deliberately distinct from dv_harness.models.Status (a stage-gate PASS/FAIL/... verdict
# vocabulary) -- this module never runs a stage and never produces a verification verdict, only
# an artifact-presence classification. No import of dv_harness.models occurs anywhere here.

PRESENT = "PRESENT"
MISSING = "MISSING"
NOT_ASSESSED = "NOT_ASSESSED"
_FINDING_STATUSES = frozenset({PRESENT, MISSING, NOT_ASSESSED})

READY = "READY"
MISSING_ARTIFACTS = "MISSING_ARTIFACTS"
INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
UNKNOWN_TARGET = "UNKNOWN_TARGET"
_OVERALL_STATUSES = frozenset({READY, MISSING_ARTIFACTS, INCOMPLETE_EVIDENCE, UNKNOWN_TARGET})


# --- Artifact category vocabulary -------------------------------------------
# Each id names a real, concretely-identifiable kind of evidence this project's own established
# conventions already recognize (env.manifest.json's own layers, the waiver ledger, the coverage
# summary, a signoff gate history, ...). This module does not read any of them itself -- it only
# classifies whether the CALLER reports one present, absent, or unassessed, and explains, per
# target, why that category matters for that target.

ARTIFACT_CATEGORY_DESCRIPTIONS: Dict[str, str] = {
    "vip_config_dump": (
        "A real VIP instance/config identity for the environment (e.g. env.manifest.json's own "
        "vip_config.vip_instances / vip_release layer) -- which VIP package and version this "
        "environment is really built against."
    ),
    "dut_rtl_source": (
        "A verible-parsed RTL port/module table for the DUT (env.manifest.json's dut_facts.rtl "
        "layer) -- what the design's own ports and hierarchy actually are."
    ),
    "register_map": (
        "A parsed register map for the DUT (env.manifest.json's dut_facts.registers layer) -- "
        "field/offset/address facts a generator or a coverage-closure reviewer needs."
    ),
    "bind_topology": (
        "A validated bind-entry table (target_instance/ports/tier/human_confirmation per entry) "
        "for whatever binds the environment needs -- the artifact connectivity.py's own tier gate "
        "and phy_boundary.py's mount-layer check are run against."
    ),
    "phy_boundary_decision": (
        "A real serial/parallel PHY-boundary decision (phy_boundary.json) -- required before any "
        "bind-location choice is made, per Bind-Location Rule 5."
    ),
    "vip_symbol_index": (
        "A real indexed VIP source tree (class/method declarations with file:line locations) -- "
        "what vip_api_card.py's citation check and vip_learning_gate.py's own sub-check need to "
        "prove a generated VIP API call is not fabricated."
    ),
    "regression_evidence": (
        "Real recorded regression results (LSF job records plus normalized evidence rows) -- not "
        "an agent's own claim that a run passed."
    ),
    "coverage_summary": (
        "A real, already-reduced coverage summary (categories with bins_total/bins_hit) from "
        "whatever coverage tool the project uses -- not a percentage an agent typed."
    ),
    "waiver_ledger": (
        "A real waiver store (waivers.json) with each waiver's own expiry/revalidation triggers "
        "-- so a waived requirement's status can be derived rather than self-attested."
    ),
    "golden_scenario_capsule": (
        "A recorded golden-scenario capsule (test/seed/config verified PASS against a specific "
        "commit) -- the reproducibility record a signoff bundle can cite."
    ),
    "signoff_gate_evidence": (
        "Evidence that the real SIGNOFF-stage gates were run and cleared (not merely that an "
        "agent asserts the project is done)."
    ),
    "requirement_contract": (
        "A canonical requirement-contract record (section 184 shape) whose status is COMPLETE "
        "with no unresolved ambiguity/contradiction -- required before a downstream generator or "
        "a signoff bundle may treat a requirement as settled."
    ),
    "testplan_correspondence": (
        "The real three-way join of testlist/vPlan/coverage model (env.manifest.json's "
        "env_topology.testplan_correspondence) -- which vPlan items are actually LINKED to a "
        "measured coverage bin, rather than merely claimed."
    ),
    "regression_list": (
        "A real regression-list / command.txt-pattern inventory (.dv-workflow/command_inventory.csv "
        "or an equivalent) -- which test patterns actually exist to submit."
    ),
}


# --- The target -> required-categories table ---------------------------------
# A small, explicit, real target-name set. Each target maps to the categories THAT PARTICULAR
# downstream goal needs, each with its own reason -- never a shared generic reason string reused
# across targets, and never a category invented for a target it is not genuinely tied to.

@dataclass(frozen=True)
class ArtifactRequirement:
    category_id: str
    reason: str


TARGET_VIP_UVM_CREATION = "VIP_UVM_CREATION"
TARGET_SIGNOFF_PACKAGE = "SIGNOFF_PACKAGE"
TARGET_COVERAGE_CLOSURE = "COVERAGE_CLOSURE"
TARGET_REGRESSION_SUBMISSION = "REGRESSION_SUBMISSION"

TARGET_ARTIFACT_TABLE: Dict[str, Tuple[ArtifactRequirement, ...]] = {
    TARGET_VIP_UVM_CREATION: (
        ArtifactRequirement(
            "vip_config_dump",
            "VIP_UVM_CREATION generates agents/sequences against a specific VIP release; without "
            "a real config dump the generator has no VIP identity to build against and would emit "
            "an environment that cites a VIP nobody confirmed is installed.",
        ),
        ArtifactRequirement(
            "dut_rtl_source",
            "VIP_UVM_CREATION binds the generated environment to real DUT ports; without a "
            "verible-parsed RTL port table there is no port list to bind the VIP's interface "
            "against.",
        ),
        ArtifactRequirement(
            "register_map",
            "VIP_UVM_CREATION's register-access sequences and scoreboard checks need real "
            "field/offset facts; without a parsed register map the generator would have to invent "
            "field widths and offsets.",
        ),
        ArtifactRequirement(
            "phy_boundary_decision",
            "Per Bind-Location Rule 5, the PHY-boundary mount-layer decision must be settled "
            "BEFORE any bind target is chosen; without it a monitor could be bound on a serial "
            "lane it cannot decode.",
        ),
        ArtifactRequirement(
            "bind_topology",
            "VIP_UVM_CREATION must emit real bind statements at a validated tier; without a "
            "validated bind-entry table there is nothing for connectivity.py's tier gate to check "
            "before generation writes a .sv bind file.",
        ),
        ArtifactRequirement(
            "vip_symbol_index",
            "VIP_UVM_CREATION cites real VIP API calls in the generated sequences/agents; without "
            "an indexed VIP source tree there is no way to prove a cited method actually exists on "
            "the class it is called against.",
        ),
    ),
    TARGET_SIGNOFF_PACKAGE: (
        ArtifactRequirement(
            "signoff_gate_evidence",
            "SIGNOFF_PACKAGE freezes a baseline only once the real SIGNOFF-stage gates cleared; "
            "without that evidence there is nothing distinguishing a genuine signoff from an "
            "agent's own unverified claim of completion.",
        ),
        ArtifactRequirement(
            "regression_evidence",
            "SIGNOFF_PACKAGE's frozen baseline must point at a real, reproducible regression "
            "result; without recorded LSF job/evidence rows the bundle would carry no evidence a "
            "regression ever actually ran.",
        ),
        ArtifactRequirement(
            "coverage_summary",
            "SIGNOFF_PACKAGE reports the coverage state it froze; without a real coverage summary "
            "the bundle cannot say what functional coverage looked like at freeze time.",
        ),
        ArtifactRequirement(
            "waiver_ledger",
            "SIGNOFF_PACKAGE's baseline must record which waivers were in force and whether they "
            "are VALID; without a real waiver ledger a waived requirement's status cannot be "
            "derived and an expired waiver could go unnoticed.",
        ),
        ArtifactRequirement(
            "golden_scenario_capsule",
            "SIGNOFF_PACKAGE's reproducibility field cites recorded golden-scenario capsules; "
            "without at least one recorded capsule the bundle has no reproducible test/seed/"
            "config/commit record to point at.",
        ),
        ArtifactRequirement(
            "requirement_contract",
            "SIGNOFF_PACKAGE closes requirements traceability; without a COMPLETE requirement "
            "contract record the bundle cannot state which requirements this signoff actually "
            "settles.",
        ),
    ),
    TARGET_COVERAGE_CLOSURE: (
        ArtifactRequirement(
            "coverage_summary",
            "COVERAGE_CLOSURE's Closure percentage is computed directly from recorded "
            "bins_hit/bins_total numbers; without a real coverage summary there is no numerator or "
            "denominator to compute it from.",
        ),
        ArtifactRequirement(
            "testplan_correspondence",
            "COVERAGE_CLOSURE scopes itself to the bins the project's own testplan actually "
            "declares as goals; without the real testplan/vPlan/coverage join the declared goal "
            "set is unknown and Closure cannot be scoped honestly.",
        ),
        ArtifactRequirement(
            "waiver_ledger",
            "COVERAGE_CLOSURE credits a missing bin toward Closure only when a matching waiver is "
            "VALID; without a real waiver ledger no bin can be credited this way and an expired or "
            "revoked waiver already in force cannot block signoff as it should.",
        ),
        ArtifactRequirement(
            "regression_evidence",
            "COVERAGE_CLOSURE only credits a bin as ProvenUnreachable after a real, adequate "
            "seed-attempt history clears an under-sampling floor; without recorded regression/job "
            "evidence there is no seed-attempt count to check that floor against.",
        ),
    ),
    TARGET_REGRESSION_SUBMISSION: (
        ArtifactRequirement(
            "dut_rtl_source",
            "REGRESSION_SUBMISSION's standing connectivity-check recipe re-runs whenever the RTL's "
            "own content fingerprint moves; without a parsed RTL source there is no fingerprint to "
            "compare and a stale gate result could be submitted against.",
        ),
        ArtifactRequirement(
            "bind_topology",
            "REGRESSION_SUBMISSION should not be dispatched against an environment whose bind "
            "gates never ran; without a validated bind-entry table there is no record that Gates "
            "1-3 were even attempted for this environment.",
        ),
        ArtifactRequirement(
            "vip_config_dump",
            "REGRESSION_SUBMISSION runs real VIP-driven traffic; without a confirmed VIP identity "
            "the submission cannot state which VIP release the regression is actually exercising.",
        ),
        ArtifactRequirement(
            "regression_list",
            "REGRESSION_SUBMISSION needs a real enumerated set of test patterns to submit; without "
            "a regression-list/command-inventory artifact there is nothing concrete to hand to "
            "LSF.",
        ),
    ),
}

TARGET_NAMES: Tuple[str, ...] = tuple(TARGET_ARTIFACT_TABLE.keys())


# --- Classification -----------------------------------------------------------

def _classify_presence(raw_value: Any) -> str:
    """True -> PRESENT, False -> MISSING, anything else (including an absent key,
    represented by the caller passing _SENTINEL_ABSENT) -> NOT_ASSESSED. Never guessed either
    direction from an ambiguous value (None, a string, a number, ...).
    """
    if raw_value is True:
        return PRESENT
    if raw_value is False:
        return MISSING
    return NOT_ASSESSED


_SENTINEL_ABSENT = object()


@dataclass(frozen=True)
class ArtifactFinding:
    category_id: str
    status: str
    reason: str
    description: str

    def __post_init__(self) -> None:
        if self.status not in _FINDING_STATUSES:
            raise ValueError(f"unrecognized finding status: {self.status!r}")


@dataclass(frozen=True)
class MissingArtifactReport:
    target: str
    target_known: bool
    overall_status: str
    findings: Tuple[ArtifactFinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.overall_status not in _OVERALL_STATUSES:
            raise ValueError(f"unrecognized overall status: {self.overall_status!r}")

    @property
    def missing_categories(self) -> Tuple[str, ...]:
        return tuple(f.category_id for f in self.findings if f.status == MISSING)

    @property
    def not_assessed_categories(self) -> Tuple[str, ...]:
        return tuple(f.category_id for f in self.findings if f.status == NOT_ASSESSED)

    @property
    def present_categories(self) -> Tuple[str, ...]:
        return tuple(f.category_id for f in self.findings if f.status == PRESENT)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "target_known": self.target_known,
            "overall_status": self.overall_status,
            "findings": [
                {
                    "category_id": f.category_id,
                    "status": f.status,
                    "reason": f.reason,
                    "description": f.description,
                }
                for f in self.findings
            ],
            "missing_categories": list(self.missing_categories),
            "not_assessed_categories": list(self.not_assessed_categories),
            "present_categories": list(self.present_categories),
        }


def known_targets() -> Tuple[str, ...]:
    """The small, explicit, real target-name set this module recognizes."""
    return TARGET_NAMES


def required_categories_for_target(target: str) -> Tuple[ArtifactRequirement, ...]:
    """The (category_id, reason) pairs a real target requires, or empty for an unknown target."""
    return TARGET_ARTIFACT_TABLE.get(target, ())


def detect_missing_artifacts(
    target: str,
    inventory: Optional[Mapping[str, Any]] = None,
) -> MissingArtifactReport:
    """Derive the SPECIFIC artifacts missing for `target`, from this module's own explicit
    target -> required-artifact-categories table, cross-checked against `inventory` -- a plain
    caller-supplied mapping of category_id -> True (confirmed present) / False (confirmed
    absent) / anything-else-or-omitted (not assessed).

    An unrecognized target yields `UNKNOWN_TARGET` and no per-category findings: this module
    never invents a plausible-looking requirement list for a target it does not define.
    """
    requirements = TARGET_ARTIFACT_TABLE.get(target)
    if requirements is None:
        return MissingArtifactReport(target=target, target_known=False, overall_status=UNKNOWN_TARGET)

    inv = inventory or {}
    findings: List[ArtifactFinding] = []
    for req in requirements:
        raw_value = inv[req.category_id] if req.category_id in inv else _SENTINEL_ABSENT
        status = _classify_presence(raw_value)
        description = ARTIFACT_CATEGORY_DESCRIPTIONS.get(req.category_id, "")
        findings.append(
            ArtifactFinding(
                category_id=req.category_id,
                status=status,
                reason=req.reason,
                description=description,
            )
        )

    if any(f.status == MISSING for f in findings):
        overall = MISSING_ARTIFACTS
    elif any(f.status == NOT_ASSESSED for f in findings):
        overall = INCOMPLETE_EVIDENCE
    else:
        overall = READY

    return MissingArtifactReport(
        target=target,
        target_known=True,
        overall_status=overall,
        findings=tuple(findings),
    )


def render_report_text(report: MissingArtifactReport) -> str:
    lines: List[str] = [f"target: {report.target}  overall_status: {report.overall_status}"]
    if not report.target_known:
        known = ", ".join(known_targets())
        lines.append(f"  unrecognized target -- known targets: {known}")
        return "\n".join(lines)
    for f in report.findings:
        lines.append(f"  [{f.status:<12}] {f.category_id}: {f.reason}")
    return "\n".join(lines)


def assert_table_covers_declared_categories() -> None:
    """Every category_id cited by TARGET_ARTIFACT_TABLE carries a real description. Run at
    import time so a table entry citing an undocumented category fails loudly rather than
    silently rendering an empty description.
    """
    for target, reqs in TARGET_ARTIFACT_TABLE.items():
        for req in reqs:
            if req.category_id not in ARTIFACT_CATEGORY_DESCRIPTIONS:
                raise AssertionError(
                    f"target {target!r} requires undocumented category {req.category_id!r}"
                )
            if not req.reason or not req.reason.strip():
                raise AssertionError(
                    f"target {target!r} category {req.category_id!r} carries an empty reason"
                )


assert_table_covers_declared_categories()


# --- Minimal ad hoc front door -------------------------------------------------
# No dv-harness CLI verb: cli.py must not be touched by this task. `python -m
# dv_harness.target_conditioned_missing_artifact_detector <TARGET> [inventory.json]` is the
# only entry point, following the disclosed "python -m only" convention several very recent
# same-day additions in this project also use when cli.py is off-limits.

def execute_verb(argv: Optional[Sequence[str]] = None) -> Tuple[int, MissingArtifactReport, str]:
    import json
    import sys as _sys

    args = list(_sys.argv[1:] if argv is None else argv)
    if not args:
        text = "usage: target_conditioned_missing_artifact_detector <TARGET> [inventory.json]\n" \
               f"known targets: {', '.join(known_targets())}"
        report = MissingArtifactReport(target="", target_known=False, overall_status=UNKNOWN_TARGET)
        return 2, report, text

    target = args[0]
    inventory: Dict[str, Any] = {}
    if len(args) > 1:
        with open(args[1], "r", encoding="utf-8") as fh:
            inventory = json.load(fh)

    report = detect_missing_artifacts(target, inventory)
    text = render_report_text(report)
    if report.overall_status == UNKNOWN_TARGET:
        code = 2
    elif report.overall_status == MISSING_ARTIFACTS:
        code = 1
    elif report.overall_status == INCOMPLETE_EVIDENCE:
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
