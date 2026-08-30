#!/usr/bin/env python3
import argparse, json, pathlib, sys

# Multi-hypothesis extension (2026-08-28): .dv-harness/inference/inference_policy.json
# declares a real "generate >=1 alternative hypothesis, record counter_evidence,
# only then pick one" inference policy (hypothesis_fields/confidence_levels/
# counter_evidence_required) but was never read by any code -- confirmed by
# `grep -rn inference_policy dv_harness/ tools/` matching only a Chinese-prose
# reference in prompts.py's RE_AUDIT stage text, never a json.loads() call.
# This was the ONLY gate touching root-cause reasoning (STAGE_GATES["RE_AUDIT"]),
# and it only ever validated a single root_cause/supporting_evidence/
# counter_evidence/confidence claim -- a lone, never-refuted hypothesis could
# PASS directly, with no structural proof that an alternative was ever
# generated or ruled out. Extending this gate (rather than adding a new one)
# because the new checks test the SAME underlying claim this gate already
# owns ("is the root cause properly evidenced"), just closing the gap that
# "evidenced" never required considering and refuting an alternative.
# rca_replay_fix_closure_gate (the stage's other gate) stays separate: it is a
# genuinely different concern (fix/replay closure), not root-cause evidence.
#
# The hypothesis field list is read from the policy file at runtime (never
# hardcoded here) specifically so this gate cannot silently drift from
# .dv-harness/inference/inference_policy.json if that file is ever edited.

POLICY_PATH = pathlib.Path(".dv-harness/inference/inference_policy.json")

# Fallback only used if the policy file is ever deleted/unreadable -- kept
# byte-identical to today's actual policy file so behavior doesn't change
# silently; see the POLICY_FILE_UNREADABLE branch below, which still FAILs
# the gate (a missing policy is itself a finding), this is not a silent
# bypass.
_FALLBACK_HYPOTHESIS_FIELDS = ["claim", "category", "supporting_evidence",
                               "counter_evidence", "missing_evidence",
                               "confidence", "next_action"]
_FALLBACK_CONFIDENCE_LEVELS = ["LOW", "MEDIUM", "HIGH", "CONFIRMED"]


def load_policy():
    if not POLICY_PATH.exists():
        return None
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root-cause", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.root_cause).read_text())

    required = ["symptom", "first_bad_event", "causal_chain", "root_cause",
                "supporting_evidence", "counter_evidence", "confidence"]
    missing = [k for k in required if k not in d]
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing})); return 2

    if not d["first_bad_event"]:
        print(json.dumps({"status": "FAIL", "reason": "NO_FIRST_BAD_EVENT"})); return 3
    if not d["causal_chain"]:
        print(json.dumps({"status": "FAIL", "reason": "NO_CAUSAL_CHAIN"})); return 4
    if not d["supporting_evidence"]:
        print(json.dumps({"status": "FAIL", "reason": "NO_SUPPORTING_EVIDENCE"})); return 5

    policy = load_policy()
    if policy is None:
        print(json.dumps({"status": "FAIL", "reason": "INFERENCE_POLICY_UNREADABLE",
                          "path": str(POLICY_PATH)})); return 7
    hypothesis_fields = policy.get("hypothesis_fields") or _FALLBACK_HYPOTHESIS_FIELDS
    confidence_levels = policy.get("confidence_levels") or _FALLBACK_CONFIDENCE_LEVELS
    # Policy's own top confidence tier -- the two highest-ranked entries in
    # confidence_levels -- is what triggers the "counter_evidence is
    # mandatory" bar. This replaces the old hardcoded ("HIGH","VERIFIED")
    # check, which had actually drifted from the policy file already:
    # "VERIFIED" never appears in confidence_levels (["LOW","MEDIUM","HIGH",
    # "CONFIRMED"]) -- the real top tier is HIGH/CONFIRMED. Fixed here.
    high_tier = set(confidence_levels[-2:]) if len(confidence_levels) >= 2 else set(confidence_levels)

    if d["confidence"] not in confidence_levels:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_CONFIDENCE_LEVEL",
                          "confidence": d["confidence"], "allowed": confidence_levels})); return 17

    if d["confidence"] in high_tier and not d["counter_evidence"]:
        print(json.dumps({"status": "FAIL", "reason": "HIGH_CONFIDENCE_WITHOUT_COUNTER_EVIDENCE_REVIEW"})); return 6

    # ---- Alternative-hypothesis structural check -----------------------
    # "Non-trivial" findings must show >=2 candidate hypotheses were
    # actually generated, with the SELECTED root_cause claim structurally
    # traceable to one array entry, and at least one OTHER entry carrying
    # recorded counter_evidence -- i.e. an alternative was concretely
    # considered and refuted, not just declared in prose. A finding may
    # explicitly opt out via a justified trivial_finding escape hatch
    # (same convention as fabric_topology_completeness_gate's
    # topology_applicable/topology_not_applicable_reason), which skips only
    # this block -- the base root-cause fields above are still mandatory.
    if d.get("trivial_finding") is True:
        just = d.get("trivial_finding_justification")
        if not just:
            print(json.dumps({"status": "FAIL", "reason": "TRIVIAL_FINDING_WITHOUT_JUSTIFICATION"})); return 8
    else:
        hyps = d.get("hypotheses")
        if not isinstance(hyps, list) or len(hyps) < 2:
            print(json.dumps({"status": "FAIL", "reason": "INSUFFICIENT_HYPOTHESES",
                              "required_min": 2,
                              "supplied": len(hyps) if isinstance(hyps, list) else 0})); return 9

        seen_claims = {}
        for i, h in enumerate(hyps):
            if not isinstance(h, dict):
                print(json.dumps({"status": "FAIL", "reason": "HYPOTHESIS_NOT_OBJECT", "index": i})); return 10
            hmissing = [f for f in hypothesis_fields if f not in h]
            if hmissing:
                print(json.dumps({"status": "FAIL", "reason": "HYPOTHESIS_MISSING_FIELDS",
                                  "index": i, "missing": hmissing})); return 11
            if not h.get("claim"):
                print(json.dumps({"status": "FAIL", "reason": "HYPOTHESIS_EMPTY_CLAIM", "index": i})); return 12
            if h.get("confidence") not in confidence_levels:
                print(json.dumps({"status": "FAIL", "reason": "HYPOTHESIS_INVALID_CONFIDENCE_LEVEL",
                                  "index": i, "confidence": h.get("confidence"),
                                  "allowed": confidence_levels})); return 13
            claim = h["claim"]
            if claim in seen_claims:
                print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_HYPOTHESIS_CLAIM",
                                  "claim": claim, "indices": [seen_claims[claim], i]})); return 14
            seen_claims[claim] = i

        selected_idx = seen_claims.get(d["root_cause"])
        if selected_idx is None:
            print(json.dumps({"status": "FAIL", "reason": "ROOT_CAUSE_NOT_IN_HYPOTHESES",
                              "root_cause": d["root_cause"],
                              "hypothesis_claims": list(seen_claims.keys())})); return 15

        alt_refuted = any(
            i != selected_idx and hyps[i].get("counter_evidence")
            for i in range(len(hyps))
        )
        if not alt_refuted:
            print(json.dumps({"status": "FAIL", "reason": "NO_ALTERNATIVE_HYPOTHESIS_REFUTED",
                              "selected_index": selected_idx,
                              "hypothesis_count": len(hyps)})); return 16

    print(json.dumps({"status": "PASS", "confidence": d["confidence"]}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
