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
    # SYS-2 (System-Level Verification Integration workflow, 2026-09-04):
    # this gate's own verdict vocabulary is binary PASS/FAIL with named FAIL
    # reasons, but SYS-2 mandates a five-way classification per subsystem
    # (EXISTS_READY / EXISTS_PARTIAL / EXISTS_BLOCKED / EXISTS_UNKNOWN /
    # NOT_FOUND). --classify is PURELY ADDITIVE: it adds a "classification"
    # key to the emitted JSON and changes no verdict, no exit code and no
    # check above it, so the STAGE_GATES["SYSTEM_LEVEL"] wiring in
    # dv_harness/gates.py is unaffected whether or not it is passed. The
    # mapping from this gate's FAIL reasons onto the five classes lives in
    # dv_harness/subsystem_discovery.classify_registry_claim() -- one place,
    # shared with the pre-selection discovery path, rather than a second
    # copy of the same rules here.
    ap.add_argument("--classify",action="store_true",
                    help="Additionally report the SYS-2 five-way existence class per "
                         "subsystem. Does not change the PASS/FAIL verdict or exit code.")
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.registry).read_text())

    registered_by_name = {}
    if a.registered:
        try:
            registered_subs = json.loads(pathlib.Path(a.registered).read_text()).get("subsystems", [])
        except (OSError, json.JSONDecodeError):
            registered_subs = []
        registered_by_name = {s.get("name"): s for s in registered_subs if s.get("name")}

    def emit(payload, code):
        """Print the gate verdict, plus the SYS-2 classification when
        --classify was passed. The classification is attached to the SAME
        JSON object rather than printed separately so a caller parsing one
        line keeps parsing one line."""
        if a.classify:
            payload = dict(payload)
            payload["classification"] = _classify(d.get("subsystems") or [],
                                                   registered_by_name,
                                                   bool(a.registered))
        print(json.dumps(payload))
        return code

    # Escape hatch (added 2026-08-28, same convention as
    # system_level_subsystem_set_completeness_gate/system_level_traceability_gate):
    # this gate previously had no way for a pure IP-level (non-multi-subsystem)
    # flow to legitimately decline it -- it always demanded a non-empty
    # registry even when SYSTEM_LEVEL composition genuinely does not apply.
    if d.get("system_level_applicable") is False:
        reason = d.get("system_level_not_applicable_reason")
        if not reason:
            return emit({"status":"FAIL","reason":"NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}, 4)
        return emit({"status":"SKIPPED_NOT_APPLICABLE","reason":reason}, 0)

    subs=d.get("subsystems",[])
    if not subs:
        return emit({"status":"FAIL","reason":"NO_SUBSYSTEMS"}, 2)

    invalid=[]
    for i,s in enumerate(subs):
        missing=[k for k in REQUIRED if not s.get(k)]
        if missing:
            invalid.append({"index":i,"name":s.get("name"),"missing":missing})

    if invalid:
        return emit({"status":"FAIL","invalid":invalid}, 3)

    if a.registered:
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
            return emit({"status":"FAIL","reason":"SUBSYSTEM_NOT_REGISTERED","names":unregistered}, 5)
        if sha_mismatch:
            return emit({"status":"FAIL","reason":"SUBSYSTEM_RELEASE_SHA_MISMATCH","mismatches":sha_mismatch}, 6)

    return emit({"status":"PASS","subsystem_count":len(subs)}, 0)


def _classify(subs, registered_by_name, registry_cross_check_available):
    """SYS-2's five-way class per claimed subsystem, delegated to
    dv_harness.subsystem_discovery.classify_registry_claim() -- the single
    place the FAIL-reason -> EXISTS_* mapping lives. Imported lazily and
    inside a try, so the default (no --classify) gate path never imports
    dv_harness at all and a missing package can never turn this gate's real
    verdict into a crash: it degrades to an explicit
    CLASSIFICATION_UNAVAILABLE, never to a fabricated class."""
    import os
    _root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
    root = pathlib.Path(_root) if _root else pathlib.Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from dv_harness.subsystem_discovery import classify_registry_claim
    except ImportError as exc:
        return {"status": "CLASSIFICATION_UNAVAILABLE", "detail": str(exc)}
    out = []
    for s in subs:
        result = classify_registry_claim(
            s, registered_by_name.get(s.get("name")),
            registry_cross_check_available=registry_cross_check_available)
        out.append({"name": s.get("name"), **result})
    return {"status": "OK", "subsystems": out}

if __name__=="__main__":
    sys.exit(main())
