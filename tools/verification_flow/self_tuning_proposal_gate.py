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
# PROTECTED_PARAMETERS (Finding I1 fix, 2026-09-02 final-review fix wave):
# now the SAME real constant dv_harness/self_tuning.py's apply_proposal()
# itself enforces (previously this script kept its own separate copy, which
# meant the CLI approve path -- which calls apply_proposal() directly and
# never re-runs this gate script -- had no protection at all). Imported,
# same pattern as PROTECTED_REMOVALS already used.
from dv_harness.self_tuning import PROTECTED_REMOVALS, PROTECTED_PARAMETERS  # noqa: E402

REQUIRED_FIELDS = {"gate_id", "change", "rationale", "confidence", "risk_level"}


def _strip_reason(proposal):
    if not REQUIRED_FIELDS.issubset(proposal.keys()):
        return "MISSING_REQUIRED_FIELD"
    change = proposal.get("change") or {}
    if not isinstance(change, dict):
        return "INVALID_CHANGE_SHAPE"
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

    if not isinstance(payload, dict):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_PROPOSALS_LIST"}))
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
