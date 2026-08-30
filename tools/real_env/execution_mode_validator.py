#!/usr/bin/env python3
import argparse, json, pathlib, sys

VALID={"PURE_LOCAL_READ_ANALYSIS","REMOTE_EXECUTION_REQUIRED"}

# CLAUDE.md "SSH/Remote Transport Connection Intake": when REMOTE_EXECUTION
# needs SSH/network transport to a Linux DV server, the agent must have
# already asked the user and collected these four non-secret fields before
# this gate can PASS. `password` is deliberately NOT one of them -- it must
# never be written into this (persisted) evidence block, so its presence
# anywhere in the payload is treated as a hard failure, not just ignored.
REQUIRED_REMOTE_CONNECTION_FIELDS = ("account", "vc_machine", "ssh_machine", "working_path")


def _contains_password(node) -> bool:
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() == "password":
                return True
            if _contains_password(v):
                return True
    elif isinstance(node, list):
        return any(_contains_password(x) for x in node)
    return False


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--request",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.request).read_text())
    declared_mode=d.get("execution_mode")
    actions=[str(x).lower() for x in d.get("actions",[])]
    if declared_mode not in VALID:
        print(json.dumps({"status":"FAIL","reason":"INVALID_MODE","declared_mode":declared_mode}))
        return 2

    if _contains_password(d):
        print(json.dumps({"status":"FAIL","reason":"CREDENTIAL_IN_EVIDENCE_BLOCKED",
                          "detail":"password must never be written into gate evidence/state; "
                                   "it is used only at the moment of the actual interactive "
                                   "connection and is never persisted by the harness."}))
        return 4

    # Derive the mode from the actions actually taken rather than trusting the
    # agent's self-declared field -- an agent claiming PURE_LOCAL_READ_ANALYSIS
    # while its actions list a remote/build/sim term is the exact false-negative
    # this gate exists to catch.
    remote_terms=("vcs","simulation","compile","regression","lsf","server","remote","ssh")
    conflicts=[x for x in actions if any(t in x for t in remote_terms)]
    derived_mode="REMOTE_EXECUTION_REQUIRED" if conflicts else "PURE_LOCAL_READ_ANALYSIS"

    if declared_mode!=derived_mode:
        print(json.dumps({"status":"CONFLICT","declared_mode":declared_mode,"derived_mode":derived_mode,
                          "conflicting_actions":conflicts}))
        return 3

    # SSH/network transport specifically (a subset of REMOTE_EXECUTION_REQUIRED,
    # e.g. actions mentioning "server"/"remote"/"ssh") requires the user to have
    # been asked and to have supplied connection identity before this can PASS.
    ssh_terms=("ssh","remote","server")
    needs_ssh_transport = any(t in a for a in actions for t in ssh_terms)
    if derived_mode=="REMOTE_EXECUTION_REQUIRED" and needs_ssh_transport:
        rc=d.get("remote_connection")
        if not isinstance(rc, dict):
            print(json.dumps({"status":"FAIL","reason":"MISSING_REMOTE_CONNECTION_INFO",
                              "required_fields":list(REQUIRED_REMOTE_CONNECTION_FIELDS)}))
            return 5
        missing=[f for f in REQUIRED_REMOTE_CONNECTION_FIELDS if not str(rc.get(f) or "").strip()]
        if missing:
            print(json.dumps({"status":"FAIL","reason":"MISSING_REMOTE_CONNECTION_INFO",
                              "missing_fields":missing}))
            return 5

    print(json.dumps({"status":"PASS","mode":derived_mode}))
    return 0

if __name__=="__main__":
    sys.exit(main())
