#!/usr/bin/env python3
import argparse, json, pathlib, sys

ALLOWED = {"STATUS","WHY","EVIDENCE","REVIEW","PAUSE","RESUME","REDIRECT","APPROVE","REJECT","STOP","TAKEOVER"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.request).read_text())

    if d.get("mode") not in ("SUBSYSTEM_ENV_MODE","SYSTEM_LEVEL_ENV_MODE"):
        print(json.dumps({"status":"FAIL","reason":"INVALID_ENV_MODE"})); return 2

    cmd=d.get("remote_command")
    if cmd not in ALLOWED:
        print(json.dumps({"status":"FAIL","reason":"INVALID_REMOTE_COMMAND","command":cmd})); return 3

    # Remote control supervises an environment flow; it must not masquerade as a third env mode
    if d.get("remote_control_as_environment_mode"):
        print(json.dumps({"status":"FAIL","reason":"REMOTE_CONTROL_IS_NOT_ENV_MODE"})); return 4

    if cmd in ("APPROVE","REJECT","REDIRECT","STOP","TAKEOVER") and not d.get("target_stage"):
        print(json.dumps({"status":"FAIL","reason":"CONTROL_ACTION_WITHOUT_TARGET_STAGE"})); return 5

    print(json.dumps({"status":"PASS","mode":d["mode"],"command":cmd}))
    return 0

if __name__=="__main__":
    sys.exit(main())
