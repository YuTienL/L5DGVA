#!/usr/bin/env python3
import argparse, json, pathlib, sys

REQUIRED=[
  "name",
  "environment_manifest",
  "release_sha",
  "qualification_state",
  "interface_compatibility",
  "clock_reset_compatibility"
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--registry",required=True)
    # BUG FIX (2026-08-28, plan-subsystem-registry design pass): optional,
    # harness-supplied (never agent-attested) path to the REAL persisted
    # registry (.dv-harness/soc-composer/subsystem_environment_registry.json,
    # written by dv_harness/engine.py's _persist_subsystem_registry_entry on
    # a real SIGNOFF PASS via subsystem_environment_registration_gate).
    # Before this, an agent's --registry claim was checked only for internal
    # shape consistency, never cross-checked against whether any of the
    # claimed subsystems were ever actually SIGNOFF-registered -- an agent
    # could claim any subsystem "ready" with zero real prior evidence. Kept
    # optional (default None -> no cross-check) so direct-script tests that
    # predate this field, and any deployment that hasn't accumulated a real
    # registry file yet, are unaffected.
    ap.add_argument("--registered",default=None)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.registry).read_text())

    # Escape hatch (added 2026-08-28, same convention as
    # system_level_subsystem_set_completeness_gate/system_level_traceability_gate):
    # this gate previously had no way for a pure IP-level (non-multi-subsystem)
    # flow to legitimately decline it -- it always demanded a non-empty
    # registry even when SYSTEM_LEVEL composition genuinely does not apply.
    if d.get("system_level_applicable") is False:
        reason = d.get("system_level_not_applicable_reason")
        if not reason:
            print(json.dumps({"status":"FAIL","reason":"NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 4
        print(json.dumps({"status":"SKIPPED_NOT_APPLICABLE","reason":reason}))
        return 0

    subs=d.get("subsystems",[])
    if not subs:
        print(json.dumps({"status":"FAIL","reason":"NO_SUBSYSTEMS"}))
        return 2

    invalid=[]
    for i,s in enumerate(subs):
        missing=[k for k in REQUIRED if not s.get(k)]
        if missing:
            invalid.append({"index":i,"name":s.get("name"),"missing":missing})

    if invalid:
        print(json.dumps({"status":"FAIL","invalid":invalid}))
        return 3

    if a.registered:
        try:
            registered_subs = json.loads(pathlib.Path(a.registered).read_text()).get("subsystems", [])
        except (OSError, json.JSONDecodeError):
            registered_subs = []
        registered_by_name = {s.get("name"): s for s in registered_subs if s.get("name")}
        unregistered=[]
        sha_mismatch=[]
        for s in subs:
            reg = registered_by_name.get(s.get("name"))
            if reg is None:
                unregistered.append(s.get("name"))
            elif reg.get("release_sha") != s.get("release_sha"):
                sha_mismatch.append({"name": s.get("name"), "claimed_release_sha": s.get("release_sha"),
                                      "registered_release_sha": reg.get("release_sha")})
        if unregistered:
            print(json.dumps({"status":"FAIL","reason":"SUBSYSTEM_NOT_REGISTERED","names":unregistered}))
            return 5
        if sha_mismatch:
            print(json.dumps({"status":"FAIL","reason":"SUBSYSTEM_RELEASE_SHA_MISMATCH","mismatches":sha_mismatch}))
            return 6

    print(json.dumps({"status":"PASS","subsystem_count":len(subs)}))
    return 0

if __name__=="__main__":
    sys.exit(main())
