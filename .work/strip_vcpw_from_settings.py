"""One-off remediation: remove every permission-rule string containing a
literal VCPW= credential from .claude/settings.local.json and its 3 stray
backups. Real, confirmed incident (2026-09-02): 756 permission-rule strings
in the LIVE settings file embedded a plaintext remote vc-machine password,
recorded there because past Bash commands that inlined VCPW=... got
auto-approved and permanently allowlisted verbatim. Not committed to git
(settings.local.json is untracked), but present on disk in the live file
and all 3 backups.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

FILES = [
    ROOT / ".claude" / "settings.local.json",
    ROOT / ".claude" / "settings.local.json.bak-1788271629",
    ROOT / ".claude" / "settings.local.json.bak-1788271706",
    ROOT / ".claude" / "settings.local.json.bak-1788274169",
]


def main() -> int:
    for path in FILES:
        if not path.exists():
            print(f"SKIP (missing): {path.name}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        allow = data.get("permissions", {}).get("allow", [])
        before = len(allow)
        cleaned = [rule for rule in allow if "VCPW" not in rule]
        removed = before - len(cleaned)
        data["permissions"]["allow"] = cleaned

        remaining_vcpw = sum(1 for rule in cleaned if "VCPW" in rule)
        assert remaining_vcpw == 0, f"{path.name}: still has VCPW after filter"

        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{path.name}: {before} -> {len(cleaned)} rules ({removed} removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
