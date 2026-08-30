#!/usr/bin/env python3
# protocol_builder_registry_conformance_gate (PROTOCOL_CAPABILITY) -- added
# 2026-08-28 (plan-protocol-registry-crosscheck design pass): closes the gap
# where .dv-harness/builder/protocol_builder_registry.json's per-protocol
# discover/build checklists were real, substantive content agents were meant
# to read and follow, but no gate ever cross-checked whether an agent's
# PROJECT_MODEL/PROTOCOL_CAPABILITY evidence actually covered them --
# PROTOCOL_CAPABILITY's evidence fell through to the generic blackboard
# fallback with no structured registry cross-check at all.
#
# The registry has NO stable per-item IDs (every discover/build entry is a
# bare free-text string). Item keys are DERIVED by slugging the registry's
# own live strings on every run (never hardcoded), so a checklist item
# renamed in the registry forces re-declaration rather than silently keeping
# stale evidence valid.
#
# EXTENDED 2026-08-29 (industrial-grade-audit follow-up, confirmed gap: "the
# one protocol-identity check trusts the agent's own self-declared protocol
# string, never independently verifying it against real repo evidence"):
# everything above only proves the profile is INTERNALLY well-formed for
# whatever `protocol` string the agent happened to type -- an agent that
# declares "pcie" while every discover/build item's `evidence`/
# `waiver_evidence` text is actually USB material (stale template, wrong
# session, copy/paste mistake) still sailed through with a bare
# UNKNOWN_PROTOCOL-only check. The only session evidence this gate script
# actually receives is this same `profile` payload (see
# dv_harness/gates.py's EvidenceFlag("--profile", "profile") wiring for
# PROTOCOL_CAPABILITY) -- so `_protocol_registry_tokens`/
# `_distinctive_keywords`/`_cited_evidence_text` below cross-check the
# declared `protocol` against the free-text evidence strings already
# required for every SATISFIED/WAIVED item, using vocabulary already present
# in the registry (no new field, no new fence, no hardcoded per-protocol
# word list).
import argparse, json, pathlib, re, sys


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def _slug_map(items):
    m = {}
    for s in items:
        k = _slug(s)
        m[k] = s
    return m


def _tokenize_for_keywords(text):
    """Lowercase alnum-run tokens, len>=3 -- long enough to carry protocol
    meaning (drops noise like "hs"/"fs"/"rx"/"tx"/"x" abbreviations), short
    enough to still catch acronyms like "usb2"/"tlp"/"aer"."""
    return {t for t in re.findall(r"[a-z0-9]+", str(text).lower()) if len(t) >= 3}


def _protocol_registry_tokens(protocols):
    """Each protocol's raw keyword set, built ONLY from its own registry
    entry (id + display_name + discover[] + build[]) -- real content
    already in protocol_builder_registry.json, nothing invented here."""
    tokens = {}
    for pid, entry in protocols.items():
        parts = [pid, entry.get("display_name", "")]
        parts += [str(s) for s in entry.get("discover", [])]
        parts += [str(s) for s in entry.get("build", [])]
        tokens[pid] = _tokenize_for_keywords(" ".join(parts))
    return tokens


def _distinctive_keywords(protocol_tokens):
    """A token is DISTINCTIVE to a protocol only when it appears in that
    protocol's own registry text and in NO other registered protocol's --
    generic shared terms ("vip", "topology", "scoreboard", "coverage",
    "error", "role", "smoke", "tests", ...) drop out automatically because
    they occur in >=2 protocols' checklists. Derived entirely from the live
    registry on every run; zero hardcoded per-protocol vocabulary."""
    counts = {}
    for toks in protocol_tokens.values():
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
    return {pid: {t for t in toks if counts[t] == 1} for pid, toks in protocol_tokens.items()}


def _cited_evidence_text(profile):
    """Every free-text evidence/waiver_evidence string the agent attached to
    a discover/build item -- the only real session evidence this gate
    script has access to (the profile IS the agent's evidence block; no
    other CLI flag exists for PROTOCOL_CAPABILITY). This is the "cited
    evidence" a self-declared protocol string must not contradict."""
    parts = []
    for namespace in ("discover_items", "build_items"):
        for item in profile.get(namespace, []):
            if not isinstance(item, dict):
                continue
            for field in ("evidence", "waiver_evidence"):
                v = item.get(field)
                if isinstance(v, str):
                    parts.append(v)
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry-root", required=True)
    ap.add_argument("--profile", required=True)
    a = ap.parse_args()

    profile = json.loads(pathlib.Path(a.profile).read_text(encoding="utf-8"))

    # Escape hatch first, same convention as fabric_topology_completeness_gate
    # / protocol_structural_completeness_gate / system_level_* gates.
    if profile.get("registry_applicable") is False:
        reason = profile.get("registry_not_applicable_reason")
        if not reason:
            print(json.dumps({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 4
        print(json.dumps({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}))
        return 0

    registry_path = pathlib.Path(a.registry_root) / ".dv-harness" / "builder" / "protocol_builder_registry.json"
    if not registry_path.exists():
        print(json.dumps({"status": "FAIL", "reason": "REGISTRY_FILE_MISSING", "path": str(registry_path)}))
        return 5
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    protocol = profile.get("protocol")
    protocols = registry.get("protocols", {})
    if not protocol or protocol not in protocols:
        print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_PROTOCOL", "protocol": protocol,
                           "known_protocols": sorted(protocols)}))
        return 6

    entry = protocols[protocol]
    namespace_maps = {}
    for key in ("discover", "build"):
        slugs = [_slug(s) for s in entry.get(key, [])]
        if len(slugs) != len(set(slugs)):
            print(json.dumps({"status": "FAIL", "reason": "REGISTRY_KEY_COLLISION",
                               "protocol": protocol, "namespace": key}))
            return 7
        namespace_maps[key] = _slug_map(entry.get(key, []))

    covered = {"discover": set(), "build": set()}
    for namespace in ("discover", "build"):
        field = f"{namespace}_items"
        seen_keys = set()
        for item in profile.get(field, []):
            key = item.get("key")
            if key in seen_keys:
                print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_CHECKLIST_KEY",
                                   "namespace": namespace, "key": key}))
                return 8
            seen_keys.add(key)

            if key not in namespace_maps[namespace]:
                print(json.dumps({"status": "FAIL", "reason": "FABRICATED_CHECKLIST_KEY",
                                   "namespace": namespace, "key": key, "protocol": protocol}))
                return 9

            status = item.get("status")
            if status == "SATISFIED":
                if not item.get("evidence"):
                    print(json.dumps({"status": "FAIL", "reason": "INVALID_ITEM_STATUS",
                                       "namespace": namespace, "key": key,
                                       "detail": "SATISFIED requires non-empty evidence"}))
                    return 10
            elif status == "WAIVED":
                if not item.get("waiver_approved") or not item.get("waiver_evidence"):
                    print(json.dumps({"status": "FAIL", "reason": "UNAPPROVED_WAIVER",
                                       "namespace": namespace, "key": key}))
                    return 11
            else:
                print(json.dumps({"status": "FAIL", "reason": "INVALID_ITEM_STATUS",
                                   "namespace": namespace, "key": key, "value": status}))
                return 10

            covered[namespace].add(key)

    missing = {}
    for namespace in ("discover", "build"):
        required = set(namespace_maps[namespace])
        gap = required - covered[namespace]
        if gap:
            missing[namespace] = sorted(namespace_maps[namespace][k] for k in gap)
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_CHECKLIST_ITEMS",
                           "protocol": protocol, "missing": missing}))
        return 12

    # INDEPENDENT PROTOCOL-IDENTITY CROSS-CHECK -- everything above only
    # proves the profile is internally well-formed for whatever `protocol`
    # the agent declared; it never asks whether that declaration is itself
    # credible. Cross-check it against the cited evidence text already
    # collected above: if NONE of the declared protocol's own
    # registry-distinctive keywords appear anywhere in its cited evidence,
    # but keywords distinctive to a DIFFERENT registered protocol do, the
    # self-declaration looks inconsistent with what was actually evidenced.
    all_tokens = _protocol_registry_tokens(protocols)
    distinctive = _distinctive_keywords(all_tokens)
    evidence_tokens = _tokenize_for_keywords(_cited_evidence_text(profile))

    self_hit = bool(evidence_tokens & distinctive.get(protocol, set()))
    if not self_hit:
        foreign_hits = {}
        for other_pid, other_keywords in distinctive.items():
            if other_pid == protocol:
                continue
            hit = evidence_tokens & other_keywords
            if hit:
                foreign_hits[other_pid] = sorted(hit)
        if foreign_hits:
            suspected = max(foreign_hits, key=lambda k: len(foreign_hits[k]))
            print(json.dumps({
                "status": "FAIL", "reason": "PROTOCOL_EVIDENCE_MISMATCH",
                "protocol": protocol, "suspected_protocol": suspected,
                "matched_keywords": foreign_hits[suspected],
                "detail": (
                    f"declared protocol '{protocol}' has zero registry-distinctive "
                    f"keyword hit anywhere in its own cited discover/build evidence, "
                    f"but that evidence contains keyword(s) {foreign_hits[suspected]} "
                    f"distinctive to registered protocol '{suspected}' -- the "
                    f"self-declared protocol is not independently corroborated by "
                    f"the evidence cited for it."
                ),
            }))
            return 13

    print(json.dumps({"status": "PASS", "protocol": protocol,
                       "discover_covered": len(covered["discover"]),
                       "build_covered": len(covered["build"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
