"""Tests for dv_harness/security_policy_ir.py."""
import json
import subprocess
import sys

import pytest

from dv_harness.security_policy_ir import (
    SecurityPolicyIRError,
    STATUS_ALLOWED,
    STATUS_DENIED,
    STATUS_UNKNOWN,
    VERIFY_DENIAL_CONFIRMED,
    VERIFY_DENIAL_NOT_CONFIRMED,
    VERIFY_NOT_A_DENIED_ACCESS,
    VERIFY_INSUFFICIENT_EVIDENCE,
    build_security_policy_ir,
    classify_access,
    verify_denial_observed,
    execute_verb,
)


# ===========================================================================
# Fixtures
# ===========================================================================

def _basic_rules():
    return [
        {
            "master": "CPU0",
            "region": "SRAM_SECURE",
            "secure": True,
            "privileged": None,
            "decision": "ALLOWED",
            "evidence": "spec section 4.2: secure CPU0 masters may access SRAM_SECURE",
            "rule_id": "R1",
        },
        {
            "master": "CPU0",
            "region": "SRAM_SECURE",
            "secure": False,
            "privileged": None,
            "decision": "DENIED",
            "evidence": "spec section 4.2: non-secure masters denied SRAM_SECURE",
            "rule_id": "R2",
        },
        {
            "master": "CPU0",
            "region": "SRAM_SECURE",
            "secure": True,
            "privileged": False,
            "decision": "DENIED",
            "evidence": "spec section 4.3: unprivileged secure access from CPU0 to "
                        "SRAM_SECURE denied (fully-pinned override of R1's privileged wildcard)",
            "rule_id": "R3",
        },
    ]


def _policy():
    return build_security_policy_ir(_basic_rules())


# ===========================================================================
# Positive path: building the IR
# ===========================================================================

class TestBuildSecurityPolicyIR:
    def test_builds_from_real_declared_rules(self):
        policy = _policy()
        assert len(policy.rules) == 3
        assert policy.rules[0].evidence.startswith("spec section 4.2")

    def test_rejects_uncited_rule(self):
        with pytest.raises(SecurityPolicyIRError, match="evidence"):
            build_security_policy_ir([
                {"master": "CPU0", "region": "R", "secure": True, "privileged": True,
                 "decision": "ALLOWED", "evidence": ""},
            ])

    def test_rejects_missing_evidence_key(self):
        with pytest.raises(SecurityPolicyIRError):
            build_security_policy_ir([
                {"master": "CPU0", "region": "R", "secure": True, "privileged": True,
                 "decision": "ALLOWED"},
            ])

    def test_rejects_invalid_decision(self):
        with pytest.raises(SecurityPolicyIRError, match="decision"):
            build_security_policy_ir([
                {"master": "CPU0", "region": "R", "secure": True, "privileged": True,
                 "decision": "MAYBE", "evidence": "cite"},
            ])

    def test_rejects_non_bool_secure_field(self):
        with pytest.raises(SecurityPolicyIRError):
            build_security_policy_ir([
                {"master": "CPU0", "region": "R", "secure": "yes", "privileged": True,
                 "decision": "ALLOWED", "evidence": "cite"},
            ])

    def test_rejects_non_list_rules(self):
        with pytest.raises(SecurityPolicyIRError):
            build_security_policy_ir({"not": "a list"})

    def test_rejects_non_dict_rule_entry(self):
        with pytest.raises(SecurityPolicyIRError):
            build_security_policy_ir(["not a dict"])

    def test_default_decision_requires_evidence(self):
        with pytest.raises(SecurityPolicyIRError, match="default_evidence"):
            build_security_policy_ir([], default_decision="DENIED", default_evidence=None)

    def test_default_decision_must_be_valid(self):
        with pytest.raises(SecurityPolicyIRError):
            build_security_policy_ir([], default_decision="NOPE", default_evidence="cite")

    def test_default_decision_with_real_evidence_is_accepted(self):
        policy = build_security_policy_ir([], default_decision="DENIED", default_evidence="spec 1.1: default-deny")
        assert policy.default_decision == "DENIED"


# ===========================================================================
# Positive path: classification
# ===========================================================================

class TestClassifyAccess:
    def test_exact_rule_allowed(self):
        policy = _policy()
        result = classify_access(policy, "CPU0", "SRAM_SECURE", True, True)
        # R1 (specificity 3) vs R3 (specificity 3, secure=True privileged=False -> does not
        # match privileged=True) -- only R1 matches at privileged=True.
        assert result.status == STATUS_ALLOWED
        assert result.matched_rule["rule_id"] == "R1"

    def test_more_specific_rule_overrides_wildcard(self):
        policy = _policy()
        # secure=True, privileged=False: R1 matches (specificity 3: master+region+secure,
        # privileged wildcard) and R3 matches (specificity 4: all four axes pinned).
        # R3 is strictly more specific and DENIES.
        result = classify_access(policy, "CPU0", "SRAM_SECURE", True, False)
        assert result.status == STATUS_DENIED
        assert result.matched_rule["rule_id"] == "R3"

    def test_non_secure_denied(self):
        policy = _policy()
        result = classify_access(policy, "CPU0", "SRAM_SECURE", False, True)
        assert result.status == STATUS_DENIED
        assert result.matched_rule["rule_id"] == "R2"

    def test_no_matching_rule_and_no_default_is_unknown(self):
        policy = _policy()
        result = classify_access(policy, "CPU9", "UNRELATED_REGION", True, True)
        assert result.status == STATUS_UNKNOWN
        assert "UNKNOWN" in result.reason or "no specific rule matched" in result.reason
        assert result.matched_rule is None

    def test_no_matching_rule_falls_back_to_declared_default(self):
        policy = build_security_policy_ir(
            _basic_rules(), default_decision="DENIED", default_evidence="spec 1.1: default-deny for undeclared regions",
        )
        result = classify_access(policy, "CPU9", "UNRELATED_REGION", True, True)
        assert result.status == STATUS_DENIED
        assert "default" in result.reason.lower()

    def test_conflicting_equal_specificity_rules_is_unknown(self):
        rules = [
            {"master": "CPU1", "region": "R1", "secure": True, "privileged": True,
             "decision": "ALLOWED", "evidence": "doc A section 1", "rule_id": "A"},
            {"master": "CPU1", "region": "R1", "secure": True, "privileged": True,
             "decision": "DENIED", "evidence": "doc B section 9", "rule_id": "B"},
        ]
        policy = build_security_policy_ir(rules)
        result = classify_access(policy, "CPU1", "R1", True, True)
        assert result.status == STATUS_UNKNOWN
        assert len(result.conflicting_rules) == 2
        ids = {r["rule_id"] for r in result.conflicting_rules}
        assert ids == {"A", "B"}

    def test_rejects_bad_master_type(self):
        policy = _policy()
        with pytest.raises(SecurityPolicyIRError):
            classify_access(policy, "", "R", True, True)

    def test_rejects_bad_bool_type(self):
        policy = _policy()
        with pytest.raises(SecurityPolicyIRError):
            classify_access(policy, "CPU0", "R", "yes", True)


# ===========================================================================
# Negative-test verification helper -- core requirement of this task
# ===========================================================================

class TestVerifyDenialObserved:
    def test_confirmed_denial_with_real_evidence(self):
        policy = _policy()
        test_result = {
            "access_attempted": True,
            "observed_outcome": "ACCESS_DENIED_OBSERVED",
            "evidence": "sim.log:4021 UVM_INFO ... RESP=SLVERR (security violation trap)",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_DENIAL_CONFIRMED

    def test_not_a_denied_access_never_falsely_confirms(self):
        """Verifying denial for an access the matrix actually ALLOWS must never
        be reported as confirmed -- it is a different, honest status."""
        policy = _policy()
        test_result = {
            "access_attempted": True,
            "observed_outcome": "ACCESS_DENIED_OBSERVED",
            "evidence": "sim.log:1 (irrelevant, access is not declared denied)",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", True, True, test_result)
        assert verification.status == VERIFY_NOT_A_DENIED_ACCESS

    def test_security_finding_access_allowed_when_should_be_denied(self):
        """The headline negative control: a test that actually observed the
        access SUCCEED, for an access the matrix says must be DENIED, must
        never be reported as a confirmed denial."""
        policy = _policy()
        test_result = {
            "access_attempted": True,
            "observed_outcome": "ACCESS_ALLOWED_OBSERVED",
            "evidence": "sim.log:889 UVM_INFO ... RESP=OKAY (transaction completed)",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_DENIAL_NOT_CONFIRMED
        assert "SECURITY FINDING" in verification.reason

    def test_no_response_is_never_assumed_to_be_a_denial(self):
        policy = _policy()
        test_result = {
            "access_attempted": True,
            "observed_outcome": "NO_RESPONSE_OBSERVED",
            "evidence": "sim.log: no response seen before test end, bus timeout",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_DENIAL_NOT_CONFIRMED
        assert "not proof of denial" in verification.reason

    def test_access_never_attempted_is_insufficient_evidence(self):
        policy = _policy()
        test_result = {
            "access_attempted": False,
            "observed_outcome": "ACCESS_DENIED_OBSERVED",
            "evidence": "sim.log:1",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_INSUFFICIENT_EVIDENCE
        assert "access_attempted" in verification.reason

    def test_missing_access_attempted_field_is_insufficient_evidence(self):
        policy = _policy()
        test_result = {
            "observed_outcome": "ACCESS_DENIED_OBSERVED",
            "evidence": "sim.log:1",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_INSUFFICIENT_EVIDENCE

    def test_missing_evidence_citation_is_insufficient_even_with_denied_outcome(self):
        """Never assume a negative test passed without real cited evidence --
        an observed_outcome alone, with no evidence citation, is not enough."""
        policy = _policy()
        test_result = {
            "access_attempted": True,
            "observed_outcome": "ACCESS_DENIED_OBSERVED",
            "evidence": "",
        }
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_INSUFFICIENT_EVIDENCE
        assert "evidence citation" in verification.reason

    def test_missing_observed_outcome_is_insufficient_evidence(self):
        policy = _policy()
        test_result = {"access_attempted": True, "evidence": "sim.log:1"}
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_INSUFFICIENT_EVIDENCE

    def test_unknown_observed_outcome_is_insufficient_evidence(self):
        policy = _policy()
        test_result = {"access_attempted": True, "observed_outcome": "UNKNOWN", "evidence": "sim.log:1"}
        verification = verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)
        assert verification.status == VERIFY_INSUFFICIENT_EVIDENCE

    def test_rejects_invalid_observed_outcome_value(self):
        policy = _policy()
        test_result = {"access_attempted": True, "observed_outcome": "MAYBE_DENIED", "evidence": "x"}
        with pytest.raises(SecurityPolicyIRError):
            verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)

    def test_rejects_non_bool_access_attempted(self):
        policy = _policy()
        test_result = {"access_attempted": "yes", "observed_outcome": "ACCESS_DENIED_OBSERVED", "evidence": "x"}
        with pytest.raises(SecurityPolicyIRError):
            verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, test_result)

    def test_rejects_non_dict_test_result(self):
        policy = _policy()
        with pytest.raises(SecurityPolicyIRError):
            verify_denial_observed(policy, "CPU0", "SRAM_SECURE", False, True, "not a dict")


# ===========================================================================
# CLI front door
# ===========================================================================

class TestCLI:
    def test_statuses_verb(self):
        code, result, _text = execute_verb(["statuses"])
        assert code == 0
        assert "ALLOWED" in result["access_status_values"]

    def test_classify_verb_via_files(self, tmp_path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": _basic_rules()}), encoding="utf-8")
        code, result, _text = execute_verb([
            "classify", "--policy", str(policy_path),
            "--master", "CPU0", "--region", "SRAM_SECURE",
            "--secure", "false", "--privileged", "true", "--json",
        ])
        assert code == 0
        assert result["status"] == STATUS_DENIED

    def test_verify_negative_test_verb_via_files(self, tmp_path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": _basic_rules()}), encoding="utf-8")
        test_result_path = tmp_path / "test_result.json"
        test_result_path.write_text(json.dumps({
            "access_attempted": True,
            "observed_outcome": "ACCESS_DENIED_OBSERVED",
            "evidence": "sim.log:4021",
        }), encoding="utf-8")
        code, result, _text = execute_verb([
            "verify-negative-test", "--policy", str(policy_path),
            "--master", "CPU0", "--region", "SRAM_SECURE",
            "--secure", "false", "--privileged", "true",
            "--test-result", str(test_result_path), "--json",
        ])
        assert code == 0
        assert result["status"] == VERIFY_DENIAL_CONFIRMED

    def test_real_subprocess_invocation(self, tmp_path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"rules": _basic_rules()}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.security_policy_ir", "classify",
             "--policy", str(policy_path), "--master", "CPU0", "--region", "SRAM_SECURE",
             "--secure", "true", "--privileged", "true", "--json"],
            capture_output=True, text=True,
        )
        assert proc.returncode in (0, 1)
        payload = json.loads(proc.stdout)
        assert payload["status"] == STATUS_ALLOWED
