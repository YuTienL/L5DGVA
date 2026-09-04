"""Deterministic Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action
scoring module.

This implements, as real Python, the confidence/gap/next-action math that the
CORE skills (hypothesis-generation, hypothesis-ranking, next-best-action,
inference-confidence-gate) previously only described in prose. The confidence
level strings are intentionally kept to the 3 values gates.py already defines
in REVIEWER_CONFIDENCE_LEVELS ("HIGH", "MEDIUM", "LOW") -- current evidence
(gates.py) wins over any skill prose that mentions a 4th "CONFIRMED" level.

NOT the same thing as the two TIER classifiers (2026-09-04). Two sibling
modules also rank how much a decision can be trusted, and both were built on
2026-09-03, the day BEFORE this module got its first real caller -- so
neither could have reused it and neither does today:
`connectivity.classify_bind_tier()` (T1_ALREADY_DECIDED / T2_STRUCTURAL_MATCH
/ T3_NAMING_HEURISTIC / T4_UNDECIDABLE) and `question_queue.classify_tier()`
(SELF_RESOLVE / SAFE_TO_ASSUME / CANNOT_ASSUME). They are deliberately NOT
folded into score_confidence(), and the reason is semantic, not historical:

  - score_confidence() scores evidence QUANTITY. It counts independent
    sources, adds a verified-refs bonus, subtracts counter-evidence, and
    the result is ordinal and additive -- more corroboration scores higher.
  - Both tier classifiers rank evidence KIND, in strict priority order, and
    the ranking is NOT a function of any count. A single already-existing
    bind (T1) outranks a structural fingerprint match on several signals
    (T2) precisely because of WHERE the evidence came from, not how much of
    it there is; T3's `requires_human_confirmation` is hard-coded True with
    no input that can flip it; and question_queue's Tier 3 is an ESCALATION
    ROUTE ("a human must decide this"), not a low score.

Mapping either onto this module's four counts would lose exactly the
property they exist for. Counting T1's one existing bind as one verified
independent source scores 1*2 + 2 = 4 -> MEDIUM, the same MEDIUM a T2
structural match scores -- so the strict T1 > T2 ordering collapses, and
the highest-trust bind tier in the codebase reports as merely MEDIUM
confidence. The two vocabularies therefore share no token with
CONFIDENCE_LEVELS by design, the same way protocol_capability.py's
`capability_status` deliberately shares none with qualification.py's tier
ladder. `dv_harness_tests/test_confidence_vocabulary_separation.py` holds
that separation, and this rationale, in place so a future auditor finding
"three confidence-ish mechanisms, none consolidated" does not have to
re-derive whether that is a defect.
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


def _next_best_action_from_catalog(gaps, catalog):
    """The catalog branch of next_best_action() -- see its docstring for the
    catalog shape. Kept as a private helper rather than inlined so the
    registry path above stays exactly the code it was."""
    if not isinstance(catalog, dict):
        raise ValueError(f"gap_action_catalog must be a dict, got {type(catalog).__name__}")
    actions = catalog.get("actions")
    if not isinstance(actions, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in actions.items()
    ):
        raise ValueError("gap_action_catalog['actions'] must be a dict of str -> str")
    source = catalog.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("gap_action_catalog['source'] must be a non-empty string")
    fallback = catalog.get("fallback")
    if not isinstance(fallback, str) or not fallback:
        raise ValueError("gap_action_catalog['fallback'] must be a non-empty string")

    results = []
    for gap in gaps:
        gap_str = str(gap)
        action = actions.get(gap_str)
        if action is None:
            gap_lower = gap_str.lower()
            for key, value in actions.items():
                if gap_lower in key.lower() or key.lower() in gap_lower:
                    action = value
                    break
        if action is not None:
            results.append({"gap": gap, "suggested_action": action, "source": source})
        else:
            results.append({
                "gap": gap,
                "suggested_action": fallback.replace("{gap}", gap_str),
                "source": "generic",
            })
    return results


def next_best_action(protocol, gaps, root, *, gap_action_catalog=None):
    """For each gap, suggest a concrete next step by cross-referencing the
    real per-protocol discover/build lists in protocol_builder_registry.json.

    Mirrors gates.py's _protocol_discover_checklist protocol-name-matching
    logic (normalize to lower-kebab-case, exact key match, then substring
    alias-fallback loop) so behavior stays consistent with the INTAKE-stage
    fix already shipped.

    `gap_action_catalog` (2026-09-04, Research-Capability Evolution Stage 1)
    lets a NON-protocol caller supply its own gap->action lookup instead of the
    protocol builder registry, without duplicating this function's matching
    logic in a second module. Omit it and behavior is byte-identical to before
    -- every existing caller (engine.py's `_react_step_inference` and
    `_score_root_cause_confidence`, dv_harness_tests/e2e_memory_chain_usb3_lfps.py)
    passes the same three positional arguments and is unaffected.

    It exists because the two DV-specific halves of this function are wrong for
    a non-simulation gap, and only those two: the registry it reads, and the
    "inspect current RTL/spec/VIP evidence directly" fallback. The Gap ->
    Next-Best-Action ARCHITECTURE around them is domain-neutral and is what the
    master prompt's section 10 forbids re-implementing ("Do NOT create a
    Research Inference Engine"). A catalog is:

        {"source": "<name recorded in each result's `source` field>",
         "actions": {"<gap key>": "<the concrete next step>", ...},
         "fallback": "<text, may contain {gap}>"}

    Matching is exact key first, then the same substring pass the registry path
    uses, so a caller may key its catalog by gap name or by a distinctive
    fragment of one. An unmatched gap gets `fallback` with {gap} filled in and
    `source` "generic", exactly as the registry path's own miss does.
    """
    if gap_action_catalog is not None:
        return _next_best_action_from_catalog(gaps, gap_action_catalog)

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
