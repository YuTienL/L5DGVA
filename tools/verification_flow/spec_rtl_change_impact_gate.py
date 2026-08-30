#!/usr/bin/env python3
# BUG FIX (2026-08-28, audit-impact-arbitration-naming): this gate previously
# only diffed two agent-SELF-REPORTED sets (required_revalidation_artifacts
# vs completed_revalidation_artifacts) -- an agent that scoped its own impact
# analysis narrowly (e.g. "only testcase X is affected") passed cleanly even
# if a different, un-flagged command.txt elsewhere in the project was
# actually impacted, since nothing ever compared against a real,
# harness-supplied enumeration of every command.txt in the project.
# --command-txt-root is harness-supplied (never agent-attested): the gate
# globs it directly rather than trusting a project-supplied list, so an
# agent cannot narrow the triage set by omission.
import argparse,json,pathlib,sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--impact",required=True)
    ap.add_argument("--command-txt-root",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.impact).read_text())

    changed=set(d.get("changed_items",[]))
    if not changed:
        print(json.dumps({"status":"PASS","reason":"NO_CHANGE"})); return 0

    required=set(d.get("required_revalidation_artifacts",[]))
    completed=set(d.get("completed_revalidation_artifacts",[]))
    missing=sorted(required-completed)
    if missing:
        print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_CHANGE_REVALIDATION","missing":missing})); return 2

    root=pathlib.Path(a.command_txt_root)
    all_command_txt=sorted(str(p.relative_to(root)).replace("\\","/") for p in root.rglob("command.txt"))
    if all_command_txt:
        verdicts=d.get("command_txt_impact_verdict") or {}
        untriaged=sorted(set(all_command_txt)-set(verdicts.keys()))
        if untriaged:
            print(json.dumps({"status":"FAIL","reason":"COMMAND_TXT_NOT_TRIAGED","missing":untriaged})); return 6
        invalid=[p for p,v in verdicts.items()
                 if not isinstance(v,dict) or v.get("status") not in ("IMPACTED","NOT_IMPACTED") or not v.get("reason")]
        if invalid:
            print(json.dumps({"status":"FAIL","reason":"INVALID_COMMAND_TXT_VERDICT","invalid":sorted(invalid)})); return 7

    if d.get("spec_changed") and not d.get("vplan_reanalyzed"):
        print(json.dumps({"status":"FAIL","reason":"SPEC_CHANGED_WITHOUT_VPLAN_REANALYSIS"})); return 3
    if d.get("rtl_interface_or_arch_changed") and not d.get("architecture_rediscovered"):
        print(json.dumps({"status":"FAIL","reason":"RTL_CHANGED_WITHOUT_ARCHITECTURE_REDISCOVERY"})); return 4
    if d.get("rtl_interface_or_arch_changed") and not d.get("mechanism_plan_revalidated"):
        print(json.dumps({"status":"FAIL","reason":"RTL_CHANGED_WITHOUT_MECHANISM_REVALIDATION"})); return 5

    print(json.dumps({"status":"PASS","changed_items":sorted(changed)})); return 0
if __name__=="__main__":
    sys.exit(main())
