#!/usr/bin/env python3
"""protocol_profile_binding_gate.py -- 2026-08-31 full-harness wiring audit
finding B2: no protocol's profile/vip-lookup skill chain was ever required
to be consulted before PROTOCOL_CAPABILITY proceeds -- protocol-router's
own SKILL.md named the routes in prose but nothing enforced an agent
actually read them. This gate cross-checks an agent's self-reported
profile_skills_consulted list against the REAL registry entry for that
protocol (harness-supplied truth, not agent-attested) -- a protocol whose
registry entry has profile_skill/vip_lookup_skill set to null requires no
consultation for that field (several real protocols genuinely have no
profile skill yet)."""
import argparse, json, pathlib, sys

REGISTRY_PATH = pathlib.Path(__file__).resolve().parents[2] / ".dv-harness" / "builder" / "protocol_builder_registry.json"


def _load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binding", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.binding).read_text())
    registry = _load_registry()["protocols"]

    for p in d.get("protocols", []):
        name = p.get("protocol")
        entry = registry.get(name)
        if entry is None:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_PROTOCOL", "protocol": name}))
            return 2
        required = [s for s in (entry.get("profile_skill"), entry.get("vip_lookup_skill")) if s]
        consulted = set(p.get("profile_skills_consulted") or [])
        missing = [s for s in required if s not in consulted]
        if missing:
            print(json.dumps({"status": "FAIL", "reason": "PROFILE_SKILL_NOT_CONSULTED",
                               "protocol": name, "missing": missing}))
            return 3

    print(json.dumps({"status": "PASS", "protocols": len(d.get("protocols", []))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
