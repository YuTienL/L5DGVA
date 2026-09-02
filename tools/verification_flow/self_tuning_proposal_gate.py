"""Mechanically enforces the autonomous gate self-tuning protected list
against an LLM-proposed batch of adjustments -- see
docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md's
"Safety boundary" section. This is the real backstop: the protected list
is enforced HERE in code, not merely described in the analysis prompt the
LLM saw."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dv_harness.self_tuning import PROTECTED_REMOVALS  # noqa: E402

PROTECTED_PARAMETERS = {
    ("fix_risk_approval_gate", "risk_classification_threshold"),
    ("deep_rca_evidence_gate", "min_hypothesis_count"),
    ("root_cause_evidence_gate", "min_hypothesis_count"),
    ("regression_submission_policy_gate", "wave_default_off"),
    ("regression_submission_policy_gate", "require_prior_failure_ref"),
}

REQUIRED_FIELDS = {"gate_id", "change", "rationale", "confidence", "risk_level"}


def _strip_reason(proposal):
    if not REQUIRED_FIELDS.issubset(proposal.keys()):
        return "MISSING_REQUIRED_FIELD"
    change = proposal.get("change") or {}
    if change.get("action") == "remove":
        stage = proposal.get("stage", "")
        target_gate = change.get("gate_id", proposal.get("gate_id"))
        if (stage, target_gate) in PROTECTED_REMOVALS:
            return "PROTECTED_REMOVAL"
        return None
    param = change.get("param")
    if param is not None and (proposal.get("gate_id"), param) in PROTECTED_PARAMETERS:
        return "PROTECTED_PARAMETER"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True)
    a = ap.parse_args()

    try:
        payload = json.loads(Path(a.proposal).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"status": "FAIL", "reason": "PAYLOAD_UNREADABLE", "detail": str(e)}))
        return 2

    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_PROPOSALS_LIST"}))
        return 2

    surviving = []
    stripped = []
    for p in proposals:
        if not isinstance(p, dict):
            stripped.append({"strip_reason": "NOT_A_DICT", "raw": p})
            continue
        reason = _strip_reason(p)
        if reason:
            entry = dict(p)
            entry["strip_reason"] = reason
            stripped.append(entry)
        else:
            surviving.append(p)

    print(json.dumps({"status": "PASS", "surviving_proposals": surviving, "stripped": stripped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
