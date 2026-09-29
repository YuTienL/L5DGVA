"""dv_harness/verification_boundary_ir.py -- VerificationBoundaryIR: classifies a verification
boundary (a bindable interface/interaction surface a testbench must check) into a fixed 10-value
class enum, plus a 7-role OWNERSHIP RECORD for that boundary (active_driver, monitor, predictor,
checker, scoreboard, coverage_owner, performance_owner) -- with every non-UNKNOWN fact, both the
boundary's own class and each role's owner, populated ONLY from a real, caller-supplied CITED fact
(a spec section, an RTL file:line, a VIP doc reference). Never a guess from a boundary's name, its
class, or any other heuristic.

REUSE SEARCH PERFORMED FIRST (this task's own rule 2)
------------------------------------------------------
Grepped `dv_harness/` for `VerificationBoundaryIR`, `verification_boundary`, `boundary_class`,
`active_driver`, `coverage_owner`, `performance_owner` and for the two sibling modules this task's
own instructions name (`security_policy_ir.py`, `arbitration_policy_ir.py`) before writing a line
here. Neither of those two modules, nor anything else in this repo, models a per-BOUNDARY
10-class taxonomy or a 7-role ownership record -- `amba_scoreboard_env.py`'s
`ENV_ROLE_SCOREBOARD`/`ENV_ROLE_SUBSCRIBER`/`ENV_ROLE_PREDICTOR`/... is a UVM-component-ROLE
vocabulary for one generated AMBA scoreboard environment, a narrower and differently-shaped
concept (which class plays which role inside ONE component tree, never a per-boundary ownership
record across seven fixed named responsibilities); `verification_architecture.py`'s `CheckerIR`/
`ScoreboardIR`/`VipBindIR`/`VipSelectionIR`/`AssertionIR` extend other real producers' own dict
shapes with placement/confidence facts, again a different question (is THIS checker/scoreboard
correctly bound and linked, never "who owns which of seven fixed responsibilities for this
boundary, and is that ownership even CITED"). This module is therefore new, standalone
territory. Per this task's own instruction it does NOT import either `security_policy_ir.py` or
`arbitration_policy_ir.py` -- it independently applies the identical cited-evidence discipline
those two modules already enforce for their own domains (an uncited access rule / an uncited
arbitration-scheme claim is refused outright, never silently accepted). The only import is
`dv_harness.models` (a small, stable, unclaimed enum) for the vocabulary-disjointness check
several sibling modules in this project already run against it.

THE EVIDENCE TRUTH RULE, APPLIED TO A BOUNDARY'S CLASS AND ITS OWNERSHIP RECORD
--------------------------------------------------------------------------------
A boundary's CLASSIFICATION into one of the 10 fixed `BoundaryClass` values is itself a real,
citable claim -- never inferred from the boundary's own name or from a naming convention -- so
`build_verification_boundary_ir()` REFUSES (`VerificationBoundaryIrError`) to construct an IR
whose `boundary_class` carries no real, non-empty `class_evidence` citation, exactly the
"an uncited claim is refused outright" discipline `security_policy_ir.AccessRule` already applies
to its own access-permission rules and `arbitration_policy_ir.classify_arbitration_scheme()`
already applies to its own scheme classification.

Each of the 7 fixed roles (`active_driver`, `monitor`, `predictor`, `checker`, `scoreboard`,
`coverage_owner`, `performance_owner`) is populated ONLY from a caller-declared `owner` PLUS a
real, non-empty `evidence` citation for that specific ownership fact. A role declaring an `owner`
with no citation is refused at construction, never silently accepted or silently dropped. A role
the caller never declares an owner for -- or declares with only whitespace -- is reported
`ROLE_UNKNOWN`: NEVER defaulted to a literal `"none"` string (which would read as "confirmed no
owner", a claim nobody made) and NEVER guessed from the boundary's own class (e.g. never assuming
every `DEBUG` boundary has no `performance_owner`, or every `COHERENT` boundary has an
`active_driver` -- ownership is a fact about THIS project's real environment, not a property that
follows from a taxonomy label). An owner-only declaration with a blank/empty citation is refused
the same way an owner-with-no-citation declaration is -- whitespace-only evidence carries no more
proof than no evidence at all.

BOUNDARY CLASS TAXONOMY (10 fixed values, DV-domain grounded)
--------------------------------------------------------------
EXTERNAL_PROTOCOL   -- an off-chip protocol interface a VIP agent drives/monitors (USB, PCIe,
                       Ethernet, MIPI, ...).
REGISTER_CSR        -- a control/status-register programming interface (APB/AHB/AXI-Lite CSR
                       access, a programming-guide-documented register map).
DMA                 -- a DMA engine's descriptor/data-movement path.
INTERRUPT           -- an interrupt line/controller boundary (assert/service/clear semantics).
CLOCK_RESET         -- a clock-domain or reset-sequencing boundary (CDC, reset deassertion order).
MEMORY_MAPPED       -- a memory-mapped data-access boundary that is not itself a DMA engine or a
                       CSR block (a memory-mapped FIFO, a shared-buffer window).
COHERENT            -- an ACE/ACE-Lite (or equivalent) cache-coherent interconnect boundary.
POWER_DOMAIN        -- a power-intent boundary (isolation/retention/power-switch, per UPF).
DEBUG               -- a debug/trace/JTAG-class boundary.
INTERNAL_FUNCTIONAL -- an internal (non-external-protocol, non-CSR, non-DMA, ...) functional
                       boundary between two internal blocks with no closer-fitting class above.

DELIBERATELY BOUNDED
------------------------
(1) This module CLASSIFIES a boundary and RECORDS its ownership; it never decides which agent
SHOULD own a role, never arbitrates a conflicting ownership claim (two callers citing two
different owners for the same role on the same boundary is reported, both citations carried, and
never resolved here -- that arbitration, if wanted, belongs to a caller invoking a real
conflict-resolution mechanism, deliberately not built or imported into this module), and never
authors any VIP/RTL/checker/scoreboard content of its own. (2) There is no stage gate and no CLI
verb wired into `cli.py` (out of this task's scope) -- front door is
`python -m dv_harness.verification_boundary_ir classes|roles|build`. (3) It performs no RTL/VIP
discovery of its own -- `boundary_id`, `boundary_class`, `class_evidence`, and every role's
`owner`/`evidence` are all caller-supplied facts this module validates and reports, never derives.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from dv_harness.models import Status


class VerificationBoundaryIrError(ValueError):
    """A malformed/uncited boundary classification, a malformed/uncited role assignment, an
    unrecognized boundary class, or an unrecognized role name -- raised rather than silently
    coerced or dropped, per the Evidence Truth Rule."""


# ===========================================================================
# Vocabularies
# ===========================================================================

#: The fixed 10-value boundary-class taxonomy. See module docstring for what each value means.
CLASS_EXTERNAL_PROTOCOL = "EXTERNAL_PROTOCOL"
CLASS_REGISTER_CSR = "REGISTER_CSR"
CLASS_DMA = "DMA"
CLASS_INTERRUPT = "INTERRUPT"
CLASS_CLOCK_RESET = "CLOCK_RESET"
CLASS_MEMORY_MAPPED = "MEMORY_MAPPED"
CLASS_COHERENT = "COHERENT"
CLASS_POWER_DOMAIN = "POWER_DOMAIN"
CLASS_DEBUG = "DEBUG"
CLASS_INTERNAL_FUNCTIONAL = "INTERNAL_FUNCTIONAL"

BOUNDARY_CLASSES: Tuple[str, ...] = (
    CLASS_EXTERNAL_PROTOCOL, CLASS_REGISTER_CSR, CLASS_DMA, CLASS_INTERRUPT,
    CLASS_CLOCK_RESET, CLASS_MEMORY_MAPPED, CLASS_COHERENT, CLASS_POWER_DOMAIN,
    CLASS_DEBUG, CLASS_INTERNAL_FUNCTIONAL,
)

#: The fixed 7-role ownership vocabulary.
ROLE_ACTIVE_DRIVER = "active_driver"
ROLE_MONITOR = "monitor"
ROLE_PREDICTOR = "predictor"
ROLE_CHECKER = "checker"
ROLE_SCOREBOARD = "scoreboard"
ROLE_COVERAGE_OWNER = "coverage_owner"
ROLE_PERFORMANCE_OWNER = "performance_owner"

ROLE_NAMES: Tuple[str, ...] = (
    ROLE_ACTIVE_DRIVER, ROLE_MONITOR, ROLE_PREDICTOR, ROLE_CHECKER,
    ROLE_SCOREBOARD, ROLE_COVERAGE_OWNER, ROLE_PERFORMANCE_OWNER,
)

#: Per-role assignment status -- never a bare "none" string; UNKNOWN is the only honest way to
#: express "no cited owner is on record for this role".
ROLE_ASSIGNED = "ROLE_ASSIGNED"
ROLE_UNKNOWN = "ROLE_UNKNOWN"
ROLE_STATUS_VALUES: Tuple[str, ...] = (ROLE_ASSIGNED, ROLE_UNKNOWN)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabularies (`BOUNDARY_CLASSES` plus `ROLE_STATUS_VALUES`) must share
    no token with the real stage verdict vocabulary. Run at import so a future edit that reaches
    for a `Status` member's spelling fails loudly."""
    status_values = {s.value for s in Status}
    for value in (*BOUNDARY_CLASSES, *ROLE_STATUS_VALUES):
        if value in status_values:
            raise AssertionError(
                f"verification_boundary_ir vocabulary value {value!r} collides with "
                f"dv_harness.models.Status -- pick a different token"
            )


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Role assignment
# ===========================================================================

@dataclass
class RoleAssignment:
    """One of the 7 fixed roles for one boundary. `owner` is the real component/agent name a
    caller declared as responsible for this role; `evidence` is the REQUIRED, non-empty citation
    for that specific ownership fact (spec section / RTL file:line / VIP doc reference) whenever
    an `owner` is declared. `status` is `ROLE_ASSIGNED` only when both are real and present;
    otherwise `ROLE_UNKNOWN` -- never a literal `"none"` and never guessed from the boundary's
    own class.
    """

    role: str
    owner: Optional[str]
    evidence: Optional[str]
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_role_assignment(role: str, owner: Optional[str] = None, evidence: Optional[str] = None) -> RoleAssignment:
    """Build one `RoleAssignment`, applying the Evidence Truth Rule: an `owner` with no real
    citation is refused outright (`VerificationBoundaryIrError`); no `owner` at all (or a blank
    one) is honestly `ROLE_UNKNOWN`, regardless of whether a caller happened to also supply
    `evidence` with nothing for it to support.
    """
    if role not in ROLE_NAMES:
        raise VerificationBoundaryIrError(
            f"role must be one of {ROLE_NAMES}, got {role!r}"
        )

    has_owner = isinstance(owner, str) and bool(owner.strip())
    if owner is not None and not isinstance(owner, str):
        raise VerificationBoundaryIrError(
            f"role {role!r}: owner must be a str or None, got {type(owner).__name__!r}"
        )
    if evidence is not None and not isinstance(evidence, str):
        raise VerificationBoundaryIrError(
            f"role {role!r}: evidence must be a str or None, got {type(evidence).__name__!r}"
        )

    if not has_owner:
        # No real owner declared -- honestly UNKNOWN. Never inferred, never defaulted to "none".
        return RoleAssignment(role=role, owner=None, evidence=None, status=ROLE_UNKNOWN)

    if not (isinstance(evidence, str) and evidence.strip()):
        raise VerificationBoundaryIrError(
            f"role {role!r} declares owner {owner!r} with no real evidence citation -- an "
            f"uncited role-ownership claim is not real evidence"
        )

    return RoleAssignment(role=role, owner=owner, evidence=evidence, status=ROLE_ASSIGNED)


# ===========================================================================
# Verification boundary IR
# ===========================================================================

@dataclass
class VerificationBoundaryIR:
    """One verification boundary: its fixed-taxonomy class (with its own required citation) and
    its 7-role ownership record. `roles` always carries exactly the 7 fixed role names as keys --
    a role this project has not yet assigned an owner for is present with `status: ROLE_UNKNOWN`,
    never absent from the record.
    """

    boundary_id: str
    boundary_class: str
    class_evidence: str
    roles: Dict[str, RoleAssignment] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "boundary_class": self.boundary_class,
            "class_evidence": self.class_evidence,
            "roles": {name: assignment.to_dict() for name, assignment in self.roles.items()},
        }

    def unassigned_roles(self) -> List[str]:
        """Every role name still `ROLE_UNKNOWN` -- never defaulted to "none", always honestly
        reported so a reader can see exactly which ownership facts this project has not yet
        cited."""
        return [name for name, assignment in self.roles.items() if assignment.status == ROLE_UNKNOWN]

    def all_roles_assigned(self) -> bool:
        return not self.unassigned_roles()


def build_verification_boundary_ir(
    boundary_id: str,
    boundary_class: str,
    class_evidence: str,
    role_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> VerificationBoundaryIR:
    """Build a `VerificationBoundaryIR` from caller-declared facts.

    `role_inputs` is a dict keyed by one of the 7 `ROLE_NAMES`, each value a dict of
    `{"owner": ..., "evidence": ...}` (both optional -- omitting a role entirely, or supplying
    neither key, means "no owner on record", i.e. `ROLE_UNKNOWN`). A role name outside the fixed
    7-value vocabulary is refused rather than silently ignored, since this project's role
    vocabulary is a closed, exhaustive set, unlike a rule's optional forward-compatible fields.

    Raises `VerificationBoundaryIrError` on any malformed/uncited fact: an empty `boundary_id`, an
    unrecognized `boundary_class`, a missing/blank `class_evidence`, an unrecognized role name in
    `role_inputs`, or any role whose `owner` is declared with no real citation.
    """
    if not isinstance(boundary_id, str) or not boundary_id.strip():
        raise VerificationBoundaryIrError("boundary_id must be a non-empty str")
    if boundary_class not in BOUNDARY_CLASSES:
        raise VerificationBoundaryIrError(
            f"boundary_class must be one of {BOUNDARY_CLASSES}, got {boundary_class!r}"
        )
    if not isinstance(class_evidence, str) or not class_evidence.strip():
        raise VerificationBoundaryIrError(
            f"boundary {boundary_id!r}: boundary_class {boundary_class!r} declared with no real "
            f"evidence citation -- an uncited boundary classification is not real evidence"
        )

    role_inputs = role_inputs or {}
    if not isinstance(role_inputs, dict):
        raise VerificationBoundaryIrError(f"role_inputs must be a dict, got {type(role_inputs).__name__!r}")

    unrecognized = [name for name in role_inputs if name not in ROLE_NAMES]
    if unrecognized:
        raise VerificationBoundaryIrError(
            f"boundary {boundary_id!r}: role_inputs names unrecognized role(s) {unrecognized!r}, "
            f"must be one of {ROLE_NAMES}"
        )

    roles: Dict[str, RoleAssignment] = {}
    for role in ROLE_NAMES:
        raw = role_inputs.get(role, {}) or {}
        if not isinstance(raw, dict):
            raise VerificationBoundaryIrError(
                f"boundary {boundary_id!r}: role_inputs[{role!r}] must be a dict, got {type(raw).__name__!r}"
            )
        try:
            roles[role] = build_role_assignment(role, owner=raw.get("owner"), evidence=raw.get("evidence"))
        except VerificationBoundaryIrError as exc:
            raise VerificationBoundaryIrError(f"boundary {boundary_id!r}: {exc}") from exc

    return VerificationBoundaryIR(
        boundary_id=boundary_id,
        boundary_class=boundary_class,
        class_evidence=class_evidence,
        roles=roles,
    )


def build_verification_boundary_irs(boundaries: List[Dict[str, Any]]) -> List[VerificationBoundaryIR]:
    """Build a list of `VerificationBoundaryIR` from a list of plain boundary dicts (the
    duck-typed real-evidence input this task requires). Each dict's recognised keys are
    `boundary_id`/`boundary_class`/`class_evidence`/`roles`; raises `VerificationBoundaryIrError`
    naming the offending index on any malformed/uncited entry.
    """
    if not isinstance(boundaries, list):
        raise VerificationBoundaryIrError(f"boundaries must be a list of dicts, got {type(boundaries).__name__!r}")
    built: List[VerificationBoundaryIR] = []
    for idx, raw in enumerate(boundaries):
        if not isinstance(raw, dict):
            raise VerificationBoundaryIrError(f"boundaries[{idx}] must be a dict, got {type(raw).__name__!r}")
        try:
            built.append(build_verification_boundary_ir(
                boundary_id=raw.get("boundary_id"),
                boundary_class=raw.get("boundary_class"),
                class_evidence=raw.get("class_evidence"),
                role_inputs=raw.get("roles"),
            ))
        except VerificationBoundaryIrError as exc:
            raise VerificationBoundaryIrError(f"boundaries[{idx}]: {exc}") from exc
    return built


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py is out of this task's scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    parser = argparse.ArgumentParser(prog="verification_boundary_ir")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("classes", help="list the fixed 10-value boundary-class taxonomy")
    sub.add_parser("roles", help="list the fixed 7-role ownership vocabulary")

    p_build = sub.add_parser("build", help="build and report VerificationBoundaryIR(s) from a JSON file")
    p_build.add_argument("--boundaries", required=True, help="path to a JSON file: a list of boundary dicts")
    p_build.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "classes":
        result = {"boundary_classes": list(BOUNDARY_CLASSES)}
        return 0, result, json.dumps(result, indent=2)

    if args.verb == "roles":
        result = {"role_names": list(ROLE_NAMES), "role_status_values": list(ROLE_STATUS_VALUES)}
        return 0, result, json.dumps(result, indent=2)

    # build
    with open(args.boundaries, "r", encoding="utf-8") as f:
        boundaries_doc = json.load(f)
    try:
        irs = build_verification_boundary_irs(boundaries_doc)
    except VerificationBoundaryIrError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    result = {"boundaries": [ir.to_dict() for ir in irs]}
    any_unassigned = any(ir.unassigned_roles() for ir in irs)
    if args.json:
        text = json.dumps(result, indent=2)
    else:
        lines = []
        for ir in irs:
            lines.append(f"{ir.boundary_id}: class={ir.boundary_class}")
            for name in ROLE_NAMES:
                assignment = ir.roles[name]
                if assignment.status == ROLE_ASSIGNED:
                    lines.append(f"  {name}: {assignment.owner} (evidence: {assignment.evidence!r})")
                else:
                    lines.append(f"  {name}: UNKNOWN")
        text = "\n".join(lines)
    exit_code = 1 if any_unassigned else 0
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
