"""Deterministic Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action
scoring module.

This implements, as real Python, the confidence/gap/next-action math that the
CORE skills (hypothesis-generation, hypothesis-ranking, next-best-action,
inference-confidence-gate) previously only described in prose. The confidence
level strings are intentionally kept to the 3 values gates.py already defines
in REVIEWER_CONFIDENCE_LEVELS ("HIGH", "MEDIUM", "LOW") -- current evidence
(gates.py) wins over any skill prose that mentions a 4th "CONFIRMED" level.
"""

import json
from pathlib import Path

CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW"]


def _require_non_negative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative int, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative int, got {value!r}")


def score_confidence(independent_sources_count, evidence_refs_verified, counter_evidence_count,
                      multi_agent_consensus_count):
    """Score confidence per the DV-expert-specified formula.

    base = min(independent_sources_count, 3) * 2
           + (2 if evidence_refs_verified else 0)
           - counter_evidence_count * 3
    if multi_agent_consensus_count >= 2: base += 2
    level = HIGH if base >= 6 else MEDIUM if base >= 3 else LOW

    Safety floor: known unaddressed counter-evidence (counter_evidence_count > 0)
    can never coexist with a reported HIGH level -- it is downgraded to MEDIUM
    and capped_by_counter_evidence is set True.
    """
    _require_non_negative_int(independent_sources_count, "independent_sources_count")
    _require_non_negative_int(counter_evidence_count, "counter_evidence_count")
    _require_non_negative_int(multi_agent_consensus_count, "multi_agent_consensus_count")
    if not isinstance(evidence_refs_verified, bool):
        raise ValueError(
            f"evidence_refs_verified must be a bool, got {evidence_refs_verified!r}"
        )

    base = min(independent_sources_count, 3) * 2
    base += 2 if evidence_refs_verified else 0
    base -= counter_evidence_count * 3
    if multi_agent_consensus_count >= 2:
        base += 2

    level = "HIGH" if base >= 6 else "MEDIUM" if base >= 3 else "LOW"

    capped_by_counter_evidence = False
    if counter_evidence_count > 0 and level == "HIGH":
        level = "MEDIUM"
        capped_by_counter_evidence = True

    return {
        "level": level,
        "score": base,
        "capped_by_counter_evidence": capped_by_counter_evidence,
    }


def identify_gap(required_evidence_categories, supplied_evidence_categories):
    """Pure set-difference: required minus supplied, preserving required's order.

    Case-sensitive exact match, no fuzzy matching.
    """
    if not isinstance(required_evidence_categories, list) or not all(
        isinstance(x, str) for x in required_evidence_categories
    ):
        raise ValueError("required_evidence_categories must be a list of strings")
    if not isinstance(supplied_evidence_categories, list) or not all(
        isinstance(x, str) for x in supplied_evidence_categories
    ):
        raise ValueError("supplied_evidence_categories must be a list of strings")

    supplied_set = set(supplied_evidence_categories)
    return [cat for cat in required_evidence_categories if cat not in supplied_set]


def _load_registry(root):
    try:
        return json.loads(
            (Path(root) / ".dv-harness" / "builder" / "protocol_builder_registry.json").read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None


def _find_protocol_entry(registry, protocol):
    entries = (registry or {}).get("protocols") or {}
    key = str(protocol).strip().lower().replace(" ", "-").replace("_", "-")
    entry = entries.get(key)
    if entry is None:
        for k, v in entries.items():
            if k in key or key in k:
                entry = v
                break
    return entry


def promote_if_high_confidence(kc_client, category, protocol, finding, confidence_result):
    """Promote a finding into the shared, cross-user Knowledge Center
    (KnowledgeCenterClient.add) ONLY when confidence_result (the exact dict
    score_confidence() already returns) has level=="HIGH". The shared store
    is durable, cross-checked knowledge, not per-run noise, so MEDIUM/LOW
    findings are never sent -- and a HIGH finding whose kc_client.add() call
    itself reports failure (its own "ok" key) is never reported as promoted.
    """
    if confidence_result.get("level") != "HIGH":
        return {
            "promoted": False,
            "reason": "CONFIDENCE_NOT_HIGH",
            "level": confidence_result.get("level"),
        }

    kc_result = kc_client.add(category, protocol, finding)
    if not kc_result.get("ok"):
        return {
            "promoted": False,
            "reason": "KC_ADD_FAILED",
            "kc_result": kc_result,
        }

    result = dict(kc_result)
    result["promoted"] = True
    return result


def next_best_action(protocol, gaps, root):
    """For each gap, suggest a concrete next step by cross-referencing the
    real per-protocol discover/build lists in protocol_builder_registry.json.

    Mirrors gates.py's _protocol_discover_checklist protocol-name-matching
    logic (normalize to lower-kebab-case, exact key match, then substring
    alias-fallback loop) so behavior stays consistent with the INTAKE-stage
    fix already shipped.
    """
    registry = _load_registry(root)
    entry = _find_protocol_entry(registry, protocol)
    discover = (entry or {}).get("discover") or []
    build = (entry or {}).get("build") or []
    candidates = list(discover) + list(build)

    results = []
    for gap in gaps:
        gap_lower = str(gap).lower()
        match = None
        for item in candidates:
            if gap_lower in item.lower() or item.lower() in gap_lower:
                match = item
                break
        if match is not None:
            results.append(
                {
                    "gap": gap,
                    "suggested_action": f"check registry item '{match}' for protocol '{protocol}'",
                    "source": "protocol_builder_registry",
                }
            )
        else:
            results.append(
                {
                    "gap": gap,
                    "suggested_action": (
                        f"no concrete registry item found for gap '{gap}' -- "
                        "inspect current RTL/spec/VIP evidence directly"
                    ),
                    "source": "generic",
                }
            )
    return results
