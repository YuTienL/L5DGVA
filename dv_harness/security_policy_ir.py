"""dv_harness/security_policy_ir.py -- SecurityPolicyIR: a secure/non-secure x
privileged/unprivileged ACCESS MATRIX per master/region, built ONLY from real
caller-supplied spec/RTL evidence (never invented), a classifier that decides
ALLOWED / DENIED / UNKNOWN for a proposed access against that declared matrix,
and a negative-test verification helper that checks a supplied test result
actually OBSERVED a denial for an access the matrix says should be denied --
never assumes a negative test passed just because a verdict field says so.

REUSE SEARCH PERFORMED FIRST (this task's own rule 2)
------------------------------------------------------
Grepped `dv_harness/` for `SecurityPolicyIR`, `security_policy`, `TrustZone`,
`secure_privileged`, `access_matrix`, `S_NS`/`ARM_TZ` and for the AMBA/SyoSil
family this task's own instructions name (`amba_fabric_discovery.py`,
`amba_port_registry.py`, `amba_fabric_analysis.py`, `amba_transaction_ir.py`,
`amba_route_transform_predictor.py`, `amba_scoreboard_env.py`,
`syoscb_compare_policy.py`, `syoscb_topology_plan.py`,
`syoscb_result_taxonomy.py`, `syoscb_phase1_report.py`,
`syoscb_source_audit.py`, `system_resource_inventory.py`,
`system_topology_analysis.py`, `system_scheduling_plan.py`) before writing a
line here. None of them carries a secure/non-secure or privileged/
unprivileged access-permission concept: the AMBA family models fabric
topology, transaction routing and route-transform prediction (address/ID/
size mapping across a bus matrix), never a security/privilege PERMISSION
axis; the SyoSil family models scoreboard compare/topology/result-taxonomy
concerns, an unrelated domain entirely; the `system_*` family models
cross-subsystem resource ownership and topology, not per-access security
policy. No security-policy vocabulary exists anywhere in this repo. This
module is therefore new, standalone territory -- it imports nothing from any
of those files, or from any other new module built in this same batch, per
this task's own file-safety scope. The only import is `dv_harness.models`
(a small, stable, unclaimed enum) for the vocabulary-disjointness check
several sibling modules in this project already run against it.

THE EVIDENCE TRUTH RULE, APPLIED TO A SECURITY-POLICY MATRIX
---------------------------------------------------------------
A SecurityPolicyIR is a set of caller-declared ACCESS RULES, each stating an
ALLOWED or DENIED decision for a (master, region, secure, privileged)
combination -- or a wildcard subset of it -- together with a REQUIRED,
non-empty `evidence` citation (a spec section, an RTL file:line, a register
programming-guide reference). A rule with no evidence citation is refused
outright (`SecurityPolicyIRError`) rather than silently accepted: an
uncited access-permission claim is exactly the "confident guess" the
Evidence Truth Rule forbids, and getting a security-permission fact wrong is
higher-consequence than most facts this harness handles. Nothing here
infers a decision from a master/region NAME, a naming convention, or any
other heuristic -- every decision traces to a rule a caller explicitly
declared, with its citation carried through to every classification result
that uses it.

An access combination no declared rule covers is classified `UNKNOWN`
(never defaulted to ALLOWED -- a fail-open default-allow guess on a security
matrix is exactly the kind of silent default this project forbids -- and
never defaulted to DENIED either, since that would fabricate a security
decision nobody declared). A caller MAY declare an explicit, cited
`default_decision` for the whole matrix (e.g. "undeclared regions/masters
default DENY, per <spec citation>") -- that default is applied only when no
specific rule matches, is always distinguishable in the result from a
matched-rule decision, and itself requires a citation like any other rule.

Two rules of equal specificity naming the SAME access combination with
DIFFERENT decisions is a genuine, uncited-into-agreement CONFLICT -- this
module never picks a winner (no source-authority order is declared here;
that arbitration, if wanted, belongs to a caller invoking a real conflict-
resolution mechanism such as `source_authority.py`, deliberately not
imported here). A conflict classifies as `UNKNOWN` and names both
conflicting rules and their citations.

THE NEGATIVE-TEST VERIFICATION HELPER
-----------------------------------------
Given an access the matrix says should be `DENIED`, `verify_denial_observed()`
checks a caller-supplied `test_result` dict actually PROVES that denial was
exercised and observed -- never assumes a negative test "passed" merely
because some overall verdict field says PASS. Three things must all be true
and cited:
  1. the access under test really classifies `DENIED` against the matrix
     (verifying "was a denial observed" is meaningless for an access the
     matrix does not even say should be denied -- that reports
     `NOT_A_DENIED_ACCESS`, not a false confirmation);
  2. `test_result` declares `access_attempted: true` -- a test that never
     actually attempted the access proves nothing about whether a denial
     path was exercised;
  3. `test_result` declares a real `observed_outcome` (one of
     `ACCESS_DENIED_OBSERVED` / `ACCESS_ALLOWED_OBSERVED` /
     `NO_RESPONSE_OBSERVED` / `UNKNOWN`) backed by a non-empty `evidence`
     citation (a sim.log line, an error/response code, a waveform offset).
Only `ACCESS_DENIED_OBSERVED` with a real citation confirms the denial
(`DENIAL_CONFIRMED`). `ACCESS_ALLOWED_OBSERVED` is the SECURITY-CRITICAL
finding this helper exists to catch -- an access the matrix declares should
be denied was actually observed succeeding -- reported as
`DENIAL_NOT_CONFIRMED` naming that finding explicitly rather than as a
generic failure. `NO_RESPONSE_OBSERVED`/timeout is likewise
`DENIAL_NOT_CONFIRMED`: an absent response is not proof of denial (a hung
bus, a dropped transaction and a genuine security-denial response are not
the same evidence, and conflating them would be exactly the "assume the
negative test passed without real evidence" failure this task guards
against). Any missing/false/uncited field is `INSUFFICIENT_EVIDENCE`,
naming exactly which fact was missing.

DELIBERATELY BOUNDED
------------------------
(1) This module DECIDES an access classification and CHECKS a supplied test
result against it; it never runs a simulation, never generates RTL/VIP/
checker content, and never picks a winner in a same-specificity rule
conflict. (2) There is no stage gate and no CLI verb wired into `cli.py`
(out of this task's scope) -- front door is
`python -m dv_harness.security_policy_ir rules|classify|verify-negative-test`.
(3) Region/master identity strings are opaque caller-declared tokens; this
module performs no address-decode or fabric-topology reasoning of its own
(that is `amba_fabric_discovery.py`/`amba_route_transform_predictor.py`'s
job, deliberately not imported here).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from dv_harness.models import Status


class SecurityPolicyIRError(ValueError):
    """A malformed/uncited access rule, a malformed test_result shape, or an
    unrecognised status/decision value -- raised rather than silently
    coerced or dropped, per the Evidence Truth Rule."""


# ===========================================================================
# Vocabularies
# ===========================================================================

STATUS_ALLOWED = "ALLOWED"
STATUS_DENIED = "DENIED"
STATUS_UNKNOWN = "UNKNOWN"
ACCESS_STATUS_VALUES: Tuple[str, ...] = (STATUS_ALLOWED, STATUS_DENIED, STATUS_UNKNOWN)

DECISION_VALUES: Tuple[str, ...] = (STATUS_ALLOWED, STATUS_DENIED)

#: Negative-test verification outcomes.
VERIFY_DENIAL_CONFIRMED = "DENIAL_CONFIRMED"
VERIFY_DENIAL_NOT_CONFIRMED = "DENIAL_NOT_CONFIRMED"
VERIFY_NOT_A_DENIED_ACCESS = "NOT_A_DENIED_ACCESS"
VERIFY_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
VERIFY_STATUS_VALUES: Tuple[str, ...] = (
    VERIFY_DENIAL_CONFIRMED, VERIFY_DENIAL_NOT_CONFIRMED,
    VERIFY_NOT_A_DENIED_ACCESS, VERIFY_INSUFFICIENT_EVIDENCE,
)

#: A test's own observed outcome vocabulary -- what the test evidence itself
#: says was seen, distinct from this module's own verification verdict.
OBSERVED_ACCESS_DENIED = "ACCESS_DENIED_OBSERVED"
OBSERVED_ACCESS_ALLOWED = "ACCESS_ALLOWED_OBSERVED"
OBSERVED_NO_RESPONSE = "NO_RESPONSE_OBSERVED"
OBSERVED_UNKNOWN = "UNKNOWN"
OBSERVED_OUTCOME_VALUES: Tuple[str, ...] = (
    OBSERVED_ACCESS_DENIED, OBSERVED_ACCESS_ALLOWED, OBSERVED_NO_RESPONSE, OBSERVED_UNKNOWN,
)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabularies (`ACCESS_STATUS_VALUES` minus the two
    words it deliberately shares in spelling only with common English --
    checked as exact string identity against `models.Status` members --
    plus `VERIFY_STATUS_VALUES`) must share no token with the real stage
    verdict vocabulary. Run at import so a future edit that reaches for a
    `Status` member's spelling fails loudly."""
    status_values = {s.value for s in Status}
    for value in (*ACCESS_STATUS_VALUES, *VERIFY_STATUS_VALUES):
        if value in status_values:
            raise AssertionError(
                f"security_policy_ir vocabulary value {value!r} collides with "
                f"dv_harness.models.Status -- pick a different token"
            )


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Access rule + IR
# ===========================================================================

@dataclass
class AccessRule:
    """One caller-declared access-permission rule. `master`/`region` are
    opaque caller-declared identity strings; `None` on `master`/`region`/
    `secure`/`privileged` means "matches ANY value of this axis" (a
    wildcard). `decision` must be ALLOWED or DENIED (never UNKNOWN -- a
    rule stating "we don't know" is not a rule). `evidence` is a REQUIRED,
    non-empty citation (spec section / RTL file:line / register doc
    reference); a rule with none is refused at construction.
    """

    master: Optional[str]
    region: Optional[str]
    secure: Optional[bool]
    privileged: Optional[bool]
    decision: str
    evidence: str
    rule_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.decision not in DECISION_VALUES:
            raise SecurityPolicyIRError(
                f"AccessRule.decision must be one of {DECISION_VALUES}, got {self.decision!r}"
            )
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise SecurityPolicyIRError(
                "AccessRule.evidence must be a non-empty citation string -- an uncited "
                "access-permission rule is not real evidence"
            )
        for name, value in (("master", self.master), ("region", self.region)):
            if value is not None and not isinstance(value, str):
                raise SecurityPolicyIRError(f"AccessRule.{name} must be a str or None, got {type(value).__name__!r}")
        for name, value in (("secure", self.secure), ("privileged", self.privileged)):
            if value is not None and not isinstance(value, bool):
                raise SecurityPolicyIRError(f"AccessRule.{name} must be a bool or None, got {type(value).__name__!r}")

    def specificity(self) -> int:
        """Number of non-wildcard (non-None) axes this rule pins down."""
        return sum(1 for v in (self.master, self.region, self.secure, self.privileged) if v is not None)

    def matches(self, master: str, region: str, secure: bool, privileged: bool) -> bool:
        if self.master is not None and self.master != master:
            return False
        if self.region is not None and self.region != region:
            return False
        if self.secure is not None and self.secure != secure:
            return False
        if self.privileged is not None and self.privileged != privileged:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityPolicyIR:
    """The declared access matrix: an ordered list of `AccessRule`s plus an
    optional cited `default_decision` applied only when no specific rule
    matches. Nothing here is derived -- every rule and the default (if any)
    is exactly what the caller supplied, validated for shape and citation.
    """

    rules: List[AccessRule] = field(default_factory=list)
    default_decision: Optional[str] = None
    default_evidence: Optional[str] = None

    def __post_init__(self) -> None:
        if self.default_decision is not None:
            if self.default_decision not in DECISION_VALUES:
                raise SecurityPolicyIRError(
                    f"default_decision must be one of {DECISION_VALUES}, got {self.default_decision!r}"
                )
            if not isinstance(self.default_evidence, str) or not self.default_evidence.strip():
                raise SecurityPolicyIRError(
                    "a default_decision was declared but default_evidence is missing/empty -- "
                    "an uncited default is not real evidence"
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rules": [r.to_dict() for r in self.rules],
            "default_decision": self.default_decision,
            "default_evidence": self.default_evidence,
        }


def build_security_policy_ir(
    rules: List[Dict[str, Any]],
    default_decision: Optional[str] = None,
    default_evidence: Optional[str] = None,
) -> SecurityPolicyIR:
    """Build a `SecurityPolicyIR` from a list of plain rule dicts (the
    duck-typed real-evidence input this task requires). Each dict's
    recognised keys are `master`/`region`/`secure`/`privileged`/`decision`/
    `evidence`/`rule_id`; an unrecognised key is ignored rather than
    rejected (forward-compatible with a richer upstream record), but every
    REQUIRED field (`decision`, `evidence`) is enforced by `AccessRule`
    itself. Raises `SecurityPolicyIRError` on any malformed/uncited rule.
    """
    if not isinstance(rules, list):
        raise SecurityPolicyIRError(f"rules must be a list of dicts, got {type(rules).__name__!r}")
    built: List[AccessRule] = []
    for idx, raw in enumerate(rules):
        if not isinstance(raw, dict):
            raise SecurityPolicyIRError(f"rules[{idx}] must be a dict, got {type(raw).__name__!r}")
        try:
            built.append(AccessRule(
                master=raw.get("master"),
                region=raw.get("region"),
                secure=raw.get("secure"),
                privileged=raw.get("privileged"),
                decision=raw.get("decision"),
                evidence=raw.get("evidence"),
                rule_id=raw.get("rule_id"),
            ))
        except SecurityPolicyIRError as exc:
            raise SecurityPolicyIRError(f"rules[{idx}]: {exc}") from exc
    return SecurityPolicyIR(rules=built, default_decision=default_decision, default_evidence=default_evidence)


# ===========================================================================
# Classification
# ===========================================================================

@dataclass
class AccessClassification:
    status: str
    master: str
    region: str
    secure: bool
    privileged: bool
    matched_rule: Optional[Dict[str, Any]]
    conflicting_rules: List[Dict[str, Any]]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_access(
    policy: SecurityPolicyIR,
    master: str,
    region: str,
    secure: bool,
    privileged: bool,
) -> AccessClassification:
    """Classify a proposed (master, region, secure, privileged) access
    against `policy`'s declared rules. Precedence: the most SPECIFIC
    matching rule(s) win (most non-wildcard axes pinned). Two or more
    max-specificity matching rules disagreeing on decision is an
    unresolved CONFLICT -> `STATUS_UNKNOWN`, naming both. No matching rule
    at all falls back to `policy.default_decision` (if declared, cited);
    otherwise `STATUS_UNKNOWN`. Never defaults to ALLOWED or DENIED on its
    own initiative.
    """
    for name, value in (("master", master), ("region", region)):
        if not isinstance(value, str) or not value:
            raise SecurityPolicyIRError(f"{name} must be a non-empty str, got {value!r}")
    for name, value in (("secure", secure), ("privileged", privileged)):
        if not isinstance(value, bool):
            raise SecurityPolicyIRError(f"{name} must be a bool, got {type(value).__name__!r}")

    matching = [r for r in policy.rules if r.matches(master, region, secure, privileged)]
    if matching:
        max_spec = max(r.specificity() for r in matching)
        winners = [r for r in matching if r.specificity() == max_spec]
        decisions = {r.decision for r in winners}
        if len(decisions) > 1:
            return AccessClassification(
                status=STATUS_UNKNOWN,
                master=master, region=region, secure=secure, privileged=privileged,
                matched_rule=None,
                conflicting_rules=[r.to_dict() for r in winners],
                reason=(
                    f"{len(winners)} rules at equal specificity ({max_spec} pinned axes) "
                    f"disagree on decision for this access -- unresolved conflict, "
                    f"reporting UNKNOWN rather than picking a winner"
                ),
            )
        winner = winners[0]
        return AccessClassification(
            status=winner.decision,
            master=master, region=region, secure=secure, privileged=privileged,
            matched_rule=winner.to_dict(),
            conflicting_rules=[],
            reason=(
                f"matched rule {winner.rule_id or '(unnamed)'} "
                f"(specificity {max_spec}), evidence: {winner.evidence!r}"
            ),
        )

    if policy.default_decision is not None:
        return AccessClassification(
            status=policy.default_decision,
            master=master, region=region, secure=secure, privileged=privileged,
            matched_rule=None,
            conflicting_rules=[],
            reason=(
                f"no specific rule matched; declared default_decision applied, "
                f"evidence: {policy.default_evidence!r}"
            ),
        )

    return AccessClassification(
        status=STATUS_UNKNOWN,
        master=master, region=region, secure=secure, privileged=privileged,
        matched_rule=None,
        conflicting_rules=[],
        reason=(
            "no specific rule matched this access combination and no default_decision "
            "was declared -- reporting UNKNOWN rather than guessing ALLOWED or DENIED"
        ),
    )


# ===========================================================================
# Negative-test verification
# ===========================================================================

@dataclass
class NegativeTestVerification:
    status: str
    classification: Dict[str, Any]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def verify_denial_observed(
    policy: SecurityPolicyIR,
    master: str,
    region: str,
    secure: bool,
    privileged: bool,
    test_result: Dict[str, Any],
) -> NegativeTestVerification:
    """Verify that `test_result` proves a denial was actually EXERCISED and
    OBSERVED for an access the matrix says should be `DENIED`. Never
    assumes a negative test passed without this real evidence -- see the
    module docstring for the full three-condition rule.

    Raises `SecurityPolicyIRError` on a malformed `test_result` shape
    (wrong types on a recognised key). A missing/absent fact is NOT a
    malformed shape -- it is honestly reported as `INSUFFICIENT_EVIDENCE`.
    """
    if not isinstance(test_result, dict):
        raise SecurityPolicyIRError(f"test_result must be a dict, got {type(test_result).__name__!r}")

    classification = classify_access(policy, master, region, secure, privileged)

    if classification.status != STATUS_DENIED:
        return NegativeTestVerification(
            status=VERIFY_NOT_A_DENIED_ACCESS,
            classification=classification.to_dict(),
            reason=(
                f"this access classifies {classification.status} against the declared matrix, "
                f"not DENIED -- verifying 'was a denial observed' does not apply to an access "
                f"the matrix does not say should be denied"
            ),
        )

    access_attempted = test_result.get("access_attempted")
    if access_attempted is not None and not isinstance(access_attempted, bool):
        raise SecurityPolicyIRError(
            f"test_result['access_attempted'] must be a bool or absent, got {type(access_attempted).__name__!r}"
        )
    if access_attempted is not True:
        return NegativeTestVerification(
            status=VERIFY_INSUFFICIENT_EVIDENCE,
            classification=classification.to_dict(),
            reason=(
                "test_result does not declare access_attempted: true -- a test that never "
                "actually attempted the access proves nothing about whether the denial path "
                "was exercised"
            ),
        )

    observed_outcome = test_result.get("observed_outcome")
    if observed_outcome is not None and observed_outcome not in OBSERVED_OUTCOME_VALUES:
        raise SecurityPolicyIRError(
            f"test_result['observed_outcome'] {observed_outcome!r} is not one of {OBSERVED_OUTCOME_VALUES}"
        )

    evidence = test_result.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        raise SecurityPolicyIRError(f"test_result['evidence'] must be a str or absent, got {type(evidence).__name__!r}")
    has_evidence = isinstance(evidence, str) and bool(evidence.strip())

    if observed_outcome is None or observed_outcome == OBSERVED_UNKNOWN or not has_evidence:
        missing = []
        if observed_outcome is None or observed_outcome == OBSERVED_UNKNOWN:
            missing.append("a real observed_outcome")
        if not has_evidence:
            missing.append("a non-empty evidence citation")
        return NegativeTestVerification(
            status=VERIFY_INSUFFICIENT_EVIDENCE,
            classification=classification.to_dict(),
            reason=f"test_result is missing {' and '.join(missing)} -- cannot confirm a denial was observed",
        )

    if observed_outcome == OBSERVED_ACCESS_DENIED:
        return NegativeTestVerification(
            status=VERIFY_DENIAL_CONFIRMED,
            classification=classification.to_dict(),
            reason=f"test_result observed the access denied, evidence: {evidence!r}",
        )

    if observed_outcome == OBSERVED_ACCESS_ALLOWED:
        return NegativeTestVerification(
            status=VERIFY_DENIAL_NOT_CONFIRMED,
            classification=classification.to_dict(),
            reason=(
                f"SECURITY FINDING: the matrix declares this access DENIED, but test_result "
                f"observed the access ALLOWED (evidence: {evidence!r}) -- the negative test "
                f"did not confirm a denial; it observed a security violation"
            ),
        )

    # NO_RESPONSE_OBSERVED
    return NegativeTestVerification(
        status=VERIFY_DENIAL_NOT_CONFIRMED,
        classification=classification.to_dict(),
        reason=(
            f"test_result observed no response (evidence: {evidence!r}) -- an absent response "
            f"is not proof of denial and must never be assumed to confirm one"
        ),
    )


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py is out of this task's scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    parser = argparse.ArgumentParser(prog="security_policy_ir")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("statuses", help="list the access-status and verification-status vocabularies")

    p_classify = sub.add_parser("classify", help="classify a proposed access against a declared policy")
    p_classify.add_argument("--policy", required=True, help="path to a JSON file of {rules, default_decision, default_evidence}")
    p_classify.add_argument("--master", required=True)
    p_classify.add_argument("--region", required=True)
    p_classify.add_argument("--secure", required=True, choices=["true", "false"])
    p_classify.add_argument("--privileged", required=True, choices=["true", "false"])
    p_classify.add_argument("--json", action="store_true")

    p_verify = sub.add_parser("verify-negative-test", help="verify a denial was actually observed")
    p_verify.add_argument("--policy", required=True)
    p_verify.add_argument("--master", required=True)
    p_verify.add_argument("--region", required=True)
    p_verify.add_argument("--secure", required=True, choices=["true", "false"])
    p_verify.add_argument("--privileged", required=True, choices=["true", "false"])
    p_verify.add_argument("--test-result", required=True, help="path to a JSON file of the test_result dict")
    p_verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "statuses":
        result = {
            "access_status_values": list(ACCESS_STATUS_VALUES),
            "verify_status_values": list(VERIFY_STATUS_VALUES),
            "observed_outcome_values": list(OBSERVED_OUTCOME_VALUES),
        }
        return 0, result, json.dumps(result, indent=2)

    with open(args.policy, "r", encoding="utf-8") as f:
        policy_doc = json.load(f)
    try:
        policy = build_security_policy_ir(
            rules=policy_doc.get("rules", []),
            default_decision=policy_doc.get("default_decision"),
            default_evidence=policy_doc.get("default_evidence"),
        )
    except SecurityPolicyIRError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    secure = args.secure == "true"
    privileged = args.privileged == "true"

    if args.verb == "classify":
        try:
            classification = classify_access(policy, args.master, args.region, secure, privileged)
        except SecurityPolicyIRError as exc:
            result = {"error": str(exc)}
            return 2, result, json.dumps(result, indent=2)
        result = classification.to_dict()
        text = json.dumps(result, indent=2) if args.json else (
            f"status: {classification.status}\nreason: {classification.reason}"
        )
        exit_code = 0 if classification.status != STATUS_UNKNOWN else 1
        return exit_code, result, text

    # verify-negative-test
    with open(args.test_result, "r", encoding="utf-8") as f:
        test_result = json.load(f)
    try:
        verification = verify_denial_observed(policy, args.master, args.region, secure, privileged, test_result)
    except SecurityPolicyIRError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)
    result = verification.to_dict()
    text = json.dumps(result, indent=2) if args.json else (
        f"status: {verification.status}\nreason: {verification.reason}"
    )
    exit_code = 0 if verification.status == VERIFY_DENIAL_CONFIRMED else 1
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
