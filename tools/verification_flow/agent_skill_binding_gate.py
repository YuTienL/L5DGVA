#!/usr/bin/env python3
import argparse,json,pathlib,sys
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); a=ap.parse_args()
    root=pathlib.Path(a.root)
    flow=json.loads((root/".dv-harness/workflow/verification_flow_v13.json").read_text())
    issues=[]
    for k,v in flow.items():
        if isinstance(v,str) and v.startswith(".claude/agents/") and not (root/v).exists():
            issues.append({"type":"MISSING_AGENT","key":k,"path":v})
        if isinstance(v,str) and v.startswith(".claude/skills/") and not (root/v).exists():
            issues.append({"type":"MISSING_SKILL","key":k,"path":v})
    for p in (root/".claude/skills").rglob("SKILL.md"):
        txt=p.read_text(encoding="utf-8",errors="ignore")
        if not txt.startswith("---"):
            issues.append({"type":"SKILL_WITHOUT_FRONTMATTER","path":str(p.relative_to(root))})
    if issues:
        print(json.dumps({"status":"FAIL","issues":issues},indent=2)); return 2
    print(json.dumps({"status":"PASS"})); return 0
if __name__=="__main__": sys.exit(main())
