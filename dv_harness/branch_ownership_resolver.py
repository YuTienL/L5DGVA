"""dv_harness/branch_ownership_resolver.py -- turns the CLAUDE.md Engineering
Discipline Rules' "Concurrent bus arbitration" / "Architecture-conformance
audit" prose into an actually-checkable classifier + validator over the
canonical `block` / `branch_a*` / `branch_fw` / `branch_b*` task-composition
architecture.

GROUNDING (read first, per this task's own instruction -- this module must
operationalize the vocabulary these two documents already define, never
invent a competing one):

  `.claude/skills/CORE/branch-mapper/SKILL.md` -- "Initialization Task
  Hierarchy" section: `block` = SoC-global init task, single, non-per-port;
  `branch_a*` = DUT+PHY init task, one parallel branch per DUT port.
  `.claude/skills/CORE/pattern-architecture/SKILL.md` -- section 1, "The
  five-layer shape": `block` (one-shot, chip/SoC-global prologue, BLOCKING,
  non-per-port); `branch_a*` (one non-blocking per-port DUT+PHY init task per
  DUT port, launched from a shared include); `branch_fw` (a per-port service
  loop launched ONCE, non-blocking, never returns -- and, per that section's
  own USB illustration, guarded against a second launch precisely because a
  second launch site is a real hazard); `branch_b*` (one VIP-driven test body
  per port, forked/joined at the pattern's own top level -- "the actual
  scenario-under-test's stimulus and per-port assertions live here").
  CLAUDE.md's own "Engineering Discipline Rules" (2026-08-29) section restates
  the same four terms verbatim ("Architecture-conformance audit" bullet) and
  adds the "Concurrent bus arbitration" bullet this module's
  `SHARED_RESOURCE_ARBITRATED_ACCESS` operation kind operationalizes.

WHAT THIS MODULE IS, AND WHAT IT IS NOT.
`classify_operation_ownership()` maps a PROPOSED action's DECLARED operation
type (plus its declared per-port shape and declared driver) onto the tier
that owns it under the architecture above -- GLOBAL (`block`), DUT
(`branch_a*`), FW (`branch_fw`) or VIP (`branch_b*`). `validate_branch_
assignment()` then checks an EXISTING assignment (a branch label plus that
same declared operation) against that classification and against the
canonical naming convention, and reports VALID / INVALID / AMBIGUOUS with the
specific rule violated. Neither function reads RTL, a VIP index, or a
command.txt file -- there is no evidence source in this repo that could tell
this module, from a bare register address or macro name, which task group
issues a given write. Per the Evidence Truth Rule, the operation's nature
(is this VIP-driven, is this per-port, who issues it) is therefore a
DECLARED input the caller must supply from its own real evidence (a
generated pattern's own header, a reviewed command.txt, a bind-topology
review); this module reasons over that declaration, it does not derive it.
An operation kind or a declared fact this module cannot resolve reports
AMBIGUOUS or UNKNOWN with the concrete missing/contradictory fact named --
never a confident guess at ownership.

Canonical branch-label naming (`block`, `branch_a{i}`, `branch_fw`,
`branch_b{i}`, underscore-separated, 0-indexed) is REUSED from
`dv_harness/amba_discovery_report.py`'s `L5_BRANCH_BLOCK`/`L5_BRANCH_FW`/
`l5_branch_a`/`l5_branch_b` -- that module's own header records
`tools/verification_flow/branch_topology_gate.py` as "the single source of
truth for the canonical form" after four incompatible conventions were found
coexisting in this repo, and re-deriving a second naming convention here
would reopen exactly that drift. This module does not duplicate that gate's
job (checking that a whole branch SET is complete for a given port count) --
it checks whether ONE proposed action's assignment to ONE branch label is
the correct tier for that action's declared nature, which
`branch_topology_gate.py` never asks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dv_harness.amba_discovery_report import (
    L5_BRANCH_BLOCK,
    L5_BRANCH_FW,
    l5_branch_a,
    l5_branch_b,
)

# ---------------------------------------------------------------------------
# Ownership tiers -- the four words the task itself names.
# ---------------------------------------------------------------------------

OWNER_GLOBAL = "GLOBAL"
OWNER_DUT = "DUT"
OWNER_FW = "FW"
OWNER_VIP = "VIP"

OWNER_TIERS = (OWNER_GLOBAL, OWNER_DUT, OWNER_FW, OWNER_VIP)

#: Which canonical branch label (family) each tier owns, for human-readable
#: reasons only -- the real mapping used for parsing/validation lives in
#: `_parse_branch_label()` below.
TIER_BRANCH_FAMILY = {
    OWNER_GLOBAL: L5_BRANCH_BLOCK,
    OWNER_DUT: "branch_a*",
    OWNER_FW: L5_BRANCH_FW,
    OWNER_VIP: "branch_b*",
}

# Classification / validation status vocabulary. Deliberately distinct from
# `models.Status` (this module is imported by nothing that branches on that
# enum, and shares no token with it) -- per the Evidence Truth Rule, ambiguity
# here is reported as AMBIGUOUS/UNKNOWN, never silently defaulted.
RESOLVED = "RESOLVED"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"

VALID = "VALID"
INVALID = "INVALID"

# ---------------------------------------------------------------------------
# Operation-kind taxonomy. Every entry is grounded in the two SKILL.md
# sections cited above (or, for the two context-dependent kinds, in the
# CLAUDE.md Engineering Discipline Rules bullets named in the task). Adding a
# kind not grounded in one of those documents is exactly the "invented
# command.txt semantics" this project's #1 defect risk names -- extend this
# table only from real skill/CLAUDE.md text.
# ---------------------------------------------------------------------------

#: Fixed-tier kinds: the tier follows directly from the kind, no further
#: declared fact is needed to resolve it. `canonical_per_port` and
#: `expected_driven_by` are used only as a CONSISTENCY check against whatever
#: the caller additionally declares -- a caller-declared fact that
#: contradicts the kind's own grounding is reported AMBIGUOUS rather than
#: silently overridden in either direction.
_FIXED_TIER_KINDS = {
    "SOC_GLOBAL_ONE_SHOT_INIT": {
        "tier": OWNER_GLOBAL,
        "canonical_per_port": False,
        "expected_driven_by": frozenset({"DUT_BRINGUP_FLOW", "HOST_SCRIPT_INIT"}),
        "basis": (
            "pattern-architecture SKILL.md section 1 'block' -- one blocking, "
            "non-per-port task run to completion before anything else starts "
            "(global reset/clock sequencing, a global-init call, a self-check "
            "of the register access path itself)."
        ),
    },
    "DUT_PHY_PORT_BRINGUP": {
        "tier": OWNER_DUT,
        "canonical_per_port": True,
        "expected_driven_by": frozenset({"DUT_BRINGUP_FLOW", "HOST_SCRIPT_INIT"}),
        "basis": (
            "pattern-architecture SKILL.md section 1 'branch_a*' -- one "
            "non-blocking per-port DUT+PHY init task per DUT port, launched "
            "from a single shared include (PHY calibration, per-port reset "
            "release, per-port register/mode config, link training)."
        ),
    },
    "FW_EVENT_SERVICE_LOOP": {
        "tier": OWNER_FW,
        "canonical_per_port": True,
        "expected_driven_by": frozenset({"FW_FIRMWARE_MODEL"}),
        "basis": (
            "pattern-architecture SKILL.md section 1 'branch_fw' -- a "
            "per-port firmware/event-service loop launched ONCE, "
            "non-blocking, never returns, and must be idempotent against "
            "being invoked more than once."
        ),
    },
    "VIP_DRIVEN_TEST_BODY": {
        "tier": OWNER_VIP,
        "canonical_per_port": True,
        "expected_driven_by": frozenset({"VIP_SEQUENCE"}),
        "basis": (
            "pattern-architecture SKILL.md section 1 'branch_b*' -- one "
            "VIP-driven test body per port, explicitly forked and joined at "
            "the pattern's own top level; the actual scenario-under-test's "
            "stimulus and per-port assertions live here."
        ),
    },
    "VIP_DRIVEN_DATA_TRANSFER": {
        "tier": OWNER_VIP,
        "canonical_per_port": True,
        "expected_driven_by": frozenset({"VIP_SEQUENCE"}),
        "basis": (
            "CLAUDE.md Engineering Discipline Rules -- 'branch_b* = "
            "VIP-driven parallel tasks'; a VIP-driven data transfer is "
            "branch_b*-owned content by definition, never branch_a*/block "
            "content."
        ),
    },
}

#: Context-dependent kinds: the same operation kind can legitimately belong
#: to more than one tier, and this module refuses to guess which without the
#: caller declaring the deciding fact(s).
_CONTEXT_DEPENDENT_KINDS = frozenset(
    {"RAW_DUT_REGISTER_WRITE", "SHARED_RESOURCE_ARBITRATED_ACCESS"}
)

#: Recognized `driven_by` vocabulary. An unrecognized value is treated the
#: same as a contradiction -- never guessed past.
KNOWN_DRIVEN_BY_VALUES = frozenset(
    {"DUT_BRINGUP_FLOW", "HOST_SCRIPT_INIT", "FW_FIRMWARE_MODEL", "VIP_SEQUENCE"}
)

ALL_OPERATION_KINDS = frozenset(_FIXED_TIER_KINDS) | _CONTEXT_DEPENDENT_KINDS


@dataclass
class ClassificationResult:
    status: str  # RESOLVED / AMBIGUOUS / UNKNOWN
    tier: Optional[str]  # one of OWNER_TIERS, or None
    operation_kind: Optional[str]
    reason: str
    basis: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "tier": self.tier,
            "operation_kind": self.operation_kind,
            "reason": self.reason,
            "basis": self.basis,
        }


def classify_operation_ownership(
    operation_kind: Optional[str],
    *,
    per_port: Optional[bool] = None,
    driven_by: Optional[str] = None,
    arbitration_policy: Optional[str] = None,
) -> ClassificationResult:
    """Classify a proposed action's ownership as GLOBAL/DUT/FW/VIP from its
    declared `operation_kind` (plus, for the two context-dependent kinds,
    its declared `per_port`/`driven_by`/`arbitration_policy`).

    Returns a RESOLVED classification only when the operation kind's own
    grounding, and every additionally-declared fact, agree. Any missing or
    contradictory fact reports AMBIGUOUS naming exactly what is missing or
    in conflict; an operation kind outside `ALL_OPERATION_KINDS` reports
    UNKNOWN -- this module never defaults an unrecognized or under-specified
    action to a guessed tier.
    """
    if not operation_kind or not isinstance(operation_kind, str):
        return ClassificationResult(
            status=UNKNOWN,
            tier=None,
            operation_kind=operation_kind,
            reason=(
                "no operation_kind declared; ownership cannot be classified "
                "without knowing what the proposed action actually does"
            ),
        )

    if operation_kind not in ALL_OPERATION_KINDS:
        return ClassificationResult(
            status=UNKNOWN,
            tier=None,
            operation_kind=operation_kind,
            reason=(
                f"operation_kind '{operation_kind}' is not in the recognized "
                "taxonomy (ALL_OPERATION_KINDS); extend it from real "
                "branch-mapper/pattern-architecture/CLAUDE.md evidence before "
                "classifying, never guess a tier for an unrecognized kind"
            ),
        )

    if driven_by is not None and driven_by not in KNOWN_DRIVEN_BY_VALUES:
        return ClassificationResult(
            status=AMBIGUOUS,
            tier=None,
            operation_kind=operation_kind,
            reason=(
                f"declared driven_by '{driven_by}' is not a recognized value "
                f"(expected one of {sorted(KNOWN_DRIVEN_BY_VALUES)}); cannot "
                "classify ownership from an unrecognized driver"
            ),
        )

    if operation_kind in _FIXED_TIER_KINDS:
        spec = _FIXED_TIER_KINDS[operation_kind]
        if per_port is not None and bool(per_port) != spec["canonical_per_port"]:
            return ClassificationResult(
                status=AMBIGUOUS,
                tier=None,
                operation_kind=operation_kind,
                reason=(
                    f"declared per_port={per_port!r} contradicts operation_kind "
                    f"'{operation_kind}''s canonical per-port shape "
                    f"({spec['canonical_per_port']!r}); a contradiction between "
                    "the declared kind and the declared shape must be resolved "
                    "by a human, not silently overridden in either direction"
                ),
                basis=spec["basis"],
            )
        if driven_by is not None and driven_by not in spec["expected_driven_by"]:
            return ClassificationResult(
                status=AMBIGUOUS,
                tier=None,
                operation_kind=operation_kind,
                reason=(
                    f"declared driven_by '{driven_by}' contradicts operation_kind "
                    f"'{operation_kind}''s expected driver(s) "
                    f"({sorted(spec['expected_driven_by'])}); this looks like a "
                    "mislabeled operation, not a classifiable one"
                ),
                basis=spec["basis"],
            )
        return ClassificationResult(
            status=RESOLVED,
            tier=spec["tier"],
            operation_kind=operation_kind,
            reason=f"'{operation_kind}' is a fixed-tier operation kind",
            basis=spec["basis"],
        )

    # Context-dependent kinds below: RAW_DUT_REGISTER_WRITE and
    # SHARED_RESOURCE_ARBITRATED_ACCESS. Neither has one owning tier by
    # itself -- ownership follows WHO issues the access, per CLAUDE.md's
    # "branch-A / branch_fw changes: query DUT RTL source ... FIRST" and
    # "Concurrent bus arbitration" bullets, never the register/resource name
    # alone.
    if operation_kind == "RAW_DUT_REGISTER_WRITE":
        if driven_by == "VIP_SEQUENCE":
            return ClassificationResult(
                status=AMBIGUOUS,
                tier=None,
                operation_kind=operation_kind,
                reason=(
                    "operation_kind 'RAW_DUT_REGISTER_WRITE' declares a "
                    "DUT-side write, but driven_by='VIP_SEQUENCE' declares a "
                    "VIP-issued one; these are contradictory declared facts "
                    "-- per CLAUDE.md's 'NO SoC REGISTER CONTENT MAY BE ADDED "
                    "TO A HOST SCRIPT' class of hazard "
                    "(pattern-architecture SKILL.md 3.1), a register write "
                    "reaching one shared sequencer from two differently-named "
                    "task groups must be resolved by a human, not classified "
                    "past"
                ),
            )
        if driven_by not in (None, "DUT_BRINGUP_FLOW", "HOST_SCRIPT_INIT"):
            return ClassificationResult(
                status=AMBIGUOUS,
                tier=None,
                operation_kind=operation_kind,
                reason=(
                    f"declared driven_by '{driven_by}' does not identify a "
                    "DUT-side bring-up flow for a raw DUT register write"
                ),
            )
        if per_port is None:
            return ClassificationResult(
                status=AMBIGUOUS,
                tier=None,
                operation_kind=operation_kind,
                reason=(
                    "per_port not declared; a raw DUT register write is "
                    "GLOBAL ('block') if it is a one-shot chip-level write "
                    "and DUT ('branch_a*') if it is per-port, per "
                    "pattern-architecture SKILL.md section 1's block/"
                    "branch_a* distinction -- cannot decide which without "
                    "knowing which"
                ),
            )
        tier = OWNER_DUT if per_port else OWNER_GLOBAL
        return ClassificationResult(
            status=RESOLVED,
            tier=tier,
            operation_kind=operation_kind,
            reason=(
                "a DUT-bring-up-flow-issued raw register write is "
                f"{tier}-owned given per_port={per_port!r}"
            ),
            basis=(
                "pattern-architecture SKILL.md section 1 ('block' one-shot "
                "vs. 'branch_a*' per-port)"
            ),
        )

    # SHARED_RESOURCE_ARBITRATED_ACCESS
    if per_port is None:
        return ClassificationResult(
            status=AMBIGUOUS,
            tier=None,
            operation_kind=operation_kind,
            reason=(
                "per_port not declared for a shared-resource bus access; "
                "cannot decide GLOBAL ('block') vs. DUT ('branch_a*') "
                "ownership without it"
            ),
        )
    if not arbitration_policy:
        return ClassificationResult(
            status=AMBIGUOUS,
            tier=None,
            operation_kind=operation_kind,
            reason=(
                "no arbitration_policy declared; CLAUDE.md's 'Concurrent bus "
                "arbitration' rule (branch-mapper SKILL.md 'AMBA M×N "
                "Mapping') requires an explicit, RTL-evidence-based "
                "arbitration policy before a shared-resource access across "
                "block/branch_a* can be assigned ownership"
            ),
        )
    tier = OWNER_DUT if per_port else OWNER_GLOBAL
    return ClassificationResult(
        status=RESOLVED,
        tier=tier,
        operation_kind=operation_kind,
        reason=(
            f"shared-resource access with a declared arbitration_policy is "
            f"{tier}-owned given per_port={per_port!r}; the arbitration "
            "policy's own RTL grounding is NOT verified by this module"
        ),
        basis="CLAUDE.md Engineering Discipline Rules 'Concurrent bus arbitration'",
    )


# ---------------------------------------------------------------------------
# Branch-label parsing (canonical naming) + assignment validation.
# ---------------------------------------------------------------------------

_BRANCH_A_RE = re.compile(r"^branch_a(\d+)$")
_BRANCH_B_RE = re.compile(r"^branch_b(\d+)$")

#: Legacy/malformed forms this codebase has actually seen (per
#: `amba_discovery_report.py`'s own header, quoting
#: `branch_topology_gate.py`'s 2026-08-28 canonicalization note: "four
#: incompatible conventions were found coexisting" -- dash-separated,
#: 1-indexed `branch-a1`, uppercase category tags like `BRANCH_A_DUT`, and a
#: missing `branch_fw`). Listed only so a legacy match can be named in the
#: reason text; any string that fails BOTH the canonical regexes above and
#: these markers is still reported MALFORMED, just without a specific
#: legacy-family label.
_LEGACY_MARKERS = (
    re.compile(r"^branch-a\d*$", re.IGNORECASE),
    re.compile(r"^branch-b\d*$", re.IGNORECASE),
    re.compile(r"^branch-fw$", re.IGNORECASE),
    re.compile(r"^branch_a$", re.IGNORECASE),
    re.compile(r"^branch_b$", re.IGNORECASE),
    re.compile(r"^branch_a_dut$", re.IGNORECASE),
    re.compile(r"^branch_b_vip$", re.IGNORECASE),
)


@dataclass
class BranchNameCheck:
    canonical: bool
    tier: Optional[str]
    index: Optional[int]
    reason: Optional[str] = None


def _parse_branch_label(branch_label) -> BranchNameCheck:
    if not isinstance(branch_label, str) or not branch_label:
        return BranchNameCheck(
            canonical=False,
            tier=None,
            index=None,
            reason="branch label is missing or not a string",
        )
    if branch_label == L5_BRANCH_BLOCK:
        return BranchNameCheck(canonical=True, tier=OWNER_GLOBAL, index=None)
    if branch_label == L5_BRANCH_FW:
        return BranchNameCheck(canonical=True, tier=OWNER_FW, index=None)
    match = _BRANCH_A_RE.match(branch_label)
    if match:
        return BranchNameCheck(canonical=True, tier=OWNER_DUT, index=int(match.group(1)))
    match = _BRANCH_B_RE.match(branch_label)
    if match:
        return BranchNameCheck(canonical=True, tier=OWNER_VIP, index=int(match.group(1)))
    for pattern in _LEGACY_MARKERS:
        if pattern.match(branch_label):
            return BranchNameCheck(
                canonical=False,
                tier=None,
                index=None,
                reason=(
                    f"'{branch_label}' is a legacy/pre-v8 naming form (non-underscore "
                    "or non-0-indexed branch_a{i}/branch_b{i}, or a bare category tag) "
                    "-- CLAUDE.md's Architecture-conformance audit requires the "
                    "canonical `block + branch_a0/1/2/3... + branch_fw + "
                    "branch_b0/1/2/3...` naming and states legacy naming found during "
                    "review 'must be flagged and corrected, not silently left in place'"
                ),
            )
    return BranchNameCheck(
        canonical=False,
        tier=None,
        index=None,
        reason=(
            f"'{branch_label}' does not match the canonical branch naming ("
            f"'{L5_BRANCH_BLOCK}', '{L5_BRANCH_FW}', 'branch_a{{i}}', 'branch_b{{i}}', "
            "underscore-separated, 0-indexed) -- per the Architecture-conformance "
            "audit rule, any non-canonical branch label must be flagged and corrected"
        ),
    )


#: Named violation rule ids for the three headline examples this task
#: names, plus the generic form used for every other tier mismatch. Kept as
#: an explicit table (not a generated f-string) so each entry's citation is
#: reviewable and matches this codebase's naming style for its own rule ids
#: (e.g. `MISSING_REQUIRED_BRANCHES`, `WAIVER_NOT_IN_STORE`).
_VIOLATION_TABLE = {
    (OWNER_VIP, OWNER_DUT): (
        "VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_A",
        (
            "a VIP-driven operation was assigned to branch_a* -- branch_a* is "
            "DUT+PHY init task content only (pattern-architecture SKILL.md "
            "section 1); VIP-driven work belongs in branch_b*"
        ),
    ),
    (OWNER_DUT, OWNER_VIP): (
        "RAW_DUT_OPERATION_ASSIGNED_TO_BRANCH_B",
        (
            "a DUT-owned operation was assigned to branch_b* -- branch_b* is "
            "VIP-driven parallel task content only (CLAUDE.md Engineering "
            "Discipline Rules 'Architecture-conformance audit'); a raw DUT "
            "register write/init step belongs in branch_a* (or block, if "
            "chip-global)"
        ),
    ),
    (OWNER_FW, OWNER_VIP): (
        "FW_SERVICE_LOOP_DUPLICATED_IN_BRANCH_B",
        (
            "the FW/event-service loop was assigned to (duplicated inside) "
            "branch_b* -- branch_fw is the sole, single launch site for the "
            "per-port firmware/event-service loop, launched once and required "
            "to be idempotent against a second launch (pattern-architecture "
            "SKILL.md section 1); re-implementing it inside a branch_b* test "
            "body creates a second scheduler for the same responsibility"
        ),
    ),
    (OWNER_GLOBAL, OWNER_DUT): (
        "GLOBAL_INIT_SPLIT_ACROSS_BRANCH_A",
        (
            "a chip-global, non-per-port init task was assigned to branch_a* "
            "-- block is the single non-per-port task for SoC-global "
            "initialization (branch-mapper SKILL.md 'Initialization Task "
            "Hierarchy'); splitting it per port contradicts its own "
            "one-shot, chip-global nature"
        ),
    ),
    (OWNER_DUT, OWNER_GLOBAL): (
        "PER_PORT_DUT_INIT_COLLAPSED_INTO_BLOCK",
        (
            "a per-port DUT+PHY init task was assigned to block -- block is "
            "reserved for the single, non-per-port SoC-global prologue "
            "(pattern-architecture SKILL.md section 1); collapsing per-port "
            "bring-up into block silently serializes ports that must default "
            "to running in parallel"
        ),
    ),
    (OWNER_FW, OWNER_DUT): (
        "FW_SERVICE_LOOP_ASSIGNED_TO_BRANCH_A",
        (
            "the FW/event-service loop was assigned to branch_a* -- branch_a* "
            "is DUT+PHY init content, not the firmware/event-service loop, "
            "which is branch_fw's sole responsibility (pattern-architecture "
            "SKILL.md section 1)"
        ),
    ),
    (OWNER_FW, OWNER_GLOBAL): (
        "FW_SERVICE_LOOP_ASSIGNED_TO_BLOCK",
        (
            "the FW/event-service loop was assigned to block -- block is the "
            "one-shot SoC-global prologue, not the per-port firmware/"
            "event-service loop, which is branch_fw's sole responsibility "
            "(pattern-architecture SKILL.md section 1)"
        ),
    ),
    (OWNER_VIP, OWNER_GLOBAL): (
        "VIP_DRIVEN_WORK_ASSIGNED_TO_BLOCK",
        (
            "a VIP-driven operation was assigned to block -- block is "
            "SoC-global initial-task content only (CLAUDE.md Engineering "
            "Discipline Rules); VIP-driven work belongs in branch_b*"
        ),
    ),
    (OWNER_GLOBAL, OWNER_VIP): (
        "GLOBAL_INIT_ASSIGNED_TO_BRANCH_B",
        (
            "a chip-global SoC init task was assigned to branch_b* -- "
            "branch_b* is VIP-driven parallel task content only (CLAUDE.md "
            "Engineering Discipline Rules); chip-global init belongs in block"
        ),
    ),
    (OWNER_GLOBAL, OWNER_FW): (
        "GLOBAL_INIT_ASSIGNED_TO_BRANCH_FW",
        (
            "a chip-global SoC init task was assigned to branch_fw -- "
            "branch_fw is the per-port firmware/event-service loop, not "
            "SoC-global init content, which belongs in block"
        ),
    ),
    (OWNER_DUT, OWNER_FW): (
        "DUT_INIT_ASSIGNED_TO_BRANCH_FW",
        (
            "a per-port DUT+PHY init task was assigned to branch_fw -- "
            "branch_fw is the per-port firmware/event-service loop launched "
            "AFTER branch_a* completes, not the DUT+PHY init task itself, "
            "which belongs in branch_a*"
        ),
    ),
    (OWNER_VIP, OWNER_FW): (
        "VIP_DRIVEN_WORK_ASSIGNED_TO_BRANCH_FW",
        (
            "a VIP-driven operation was assigned to branch_fw -- branch_fw "
            "is the firmware/event-service loop, not VIP-driven test-body "
            "content, which belongs in branch_b*"
        ),
    ),
}

ARCH_CONFORMANCE_NAMING_VIOLATION = "ARCH_CONFORMANCE_NAMING_VIOLATION"


@dataclass
class ValidationResult:
    verdict: str  # VALID / INVALID / AMBIGUOUS
    violated_rule: Optional[str]
    assigned_tier: Optional[str]
    expected_tier: Optional[str]
    reason: str
    classification: Optional[ClassificationResult] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "violated_rule": self.violated_rule,
            "assigned_tier": self.assigned_tier,
            "expected_tier": self.expected_tier,
            "reason": self.reason,
            "classification": (
                self.classification.to_dict() if self.classification else None
            ),
        }


def validate_branch_assignment(
    branch_label,
    operation_kind: Optional[str],
    *,
    per_port: Optional[bool] = None,
    driven_by: Optional[str] = None,
    arbitration_policy: Optional[str] = None,
) -> ValidationResult:
    """Validate an EXISTING branch assignment against the canonical
    `block`/`branch_a*`/`branch_fw`/`branch_b*` ownership rules.

    Two independent checks, either of which can produce a verdict:
    1. Is `branch_label` itself a canonical branch name? A non-canonical
       (legacy/malformed) label is INVALID under the Architecture-conformance
       audit rule regardless of the operation's classification.
    2. Does the operation's classified ownership tier match the tier the
       branch label implies? A mismatch is INVALID, naming the specific
       violated rule from `_VIOLATION_TABLE`. A classification that could
       not be resolved (AMBIGUOUS/UNKNOWN) makes the whole validation
       AMBIGUOUS -- an assignment cannot be judged correct or incorrect
       without knowing what the operation actually is.
    """
    name_check = _parse_branch_label(branch_label)
    if not name_check.canonical:
        return ValidationResult(
            verdict=INVALID,
            violated_rule=ARCH_CONFORMANCE_NAMING_VIOLATION,
            assigned_tier=None,
            expected_tier=None,
            reason=name_check.reason,
        )

    classification = classify_operation_ownership(
        operation_kind,
        per_port=per_port,
        driven_by=driven_by,
        arbitration_policy=arbitration_policy,
    )
    if classification.status != RESOLVED:
        return ValidationResult(
            verdict=AMBIGUOUS,
            violated_rule=None,
            assigned_tier=name_check.tier,
            expected_tier=None,
            reason=(
                "cannot validate this assignment: "
                f"{classification.reason}"
            ),
            classification=classification,
        )

    expected_tier = classification.tier
    assigned_tier = name_check.tier
    if expected_tier == assigned_tier:
        return ValidationResult(
            verdict=VALID,
            violated_rule=None,
            assigned_tier=assigned_tier,
            expected_tier=expected_tier,
            reason=(
                f"'{branch_label}' is the canonical {assigned_tier} branch, "
                f"which matches operation_kind '{operation_kind}''s classified "
                f"ownership ({expected_tier})"
            ),
            classification=classification,
        )

    violation_id, violation_reason = _VIOLATION_TABLE[(expected_tier, assigned_tier)]
    return ValidationResult(
        verdict=INVALID,
        violated_rule=violation_id,
        assigned_tier=assigned_tier,
        expected_tier=expected_tier,
        reason=violation_reason,
        classification=classification,
    )


# ---------------------------------------------------------------------------
# Ad hoc CLI, following this codebase's `execute_verb()` convention (e.g.
# `power_intent`, `golden_scenario`). No `dv-harness` verb is registered here
# -- `cli.py` is out of scope for this task; the integration step wires one.
# ---------------------------------------------------------------------------


def execute_verb(verb: str, *, payload_path: Optional[str] = None) -> tuple:
    """Returns (exit_code, result_dict). `verb` is 'classify' or 'validate';
    `payload_path` names a JSON file carrying `operation_kind`, optional
    `per_port`/`driven_by`/`arbitration_policy`, and (for 'validate') a
    `branch_label`."""
    if not payload_path:
        return 2, {"status": UNKNOWN, "reason": "--payload is required"}
    try:
        data = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 2, {"status": UNKNOWN, "reason": f"could not read payload: {exc}"}

    operation_kind = data.get("operation_kind")
    per_port = data.get("per_port")
    driven_by = data.get("driven_by")
    arbitration_policy = data.get("arbitration_policy")

    if verb == "classify":
        result = classify_operation_ownership(
            operation_kind,
            per_port=per_port,
            driven_by=driven_by,
            arbitration_policy=arbitration_policy,
        )
        exit_code = {RESOLVED: 0, AMBIGUOUS: 1, UNKNOWN: 2}[result.status]
        return exit_code, result.to_dict()

    if verb == "validate":
        branch_label = data.get("branch_label")
        result = validate_branch_assignment(
            branch_label,
            operation_kind,
            per_port=per_port,
            driven_by=driven_by,
            arbitration_policy=arbitration_policy,
        )
        exit_code = {VALID: 0, INVALID: 1, AMBIGUOUS: 2}[result.verdict]
        return exit_code, result.to_dict()

    return 2, {"status": UNKNOWN, "reason": f"unrecognized verb '{verb}'"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify/validate branch_a*/branch_fw/branch_b*/block ownership."
    )
    parser.add_argument("verb", choices=("classify", "validate"))
    parser.add_argument("--payload", required=True, help="JSON file with the declared facts")
    args = parser.parse_args(argv)
    exit_code, result = execute_verb(args.verb, payload_path=args.payload)
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
