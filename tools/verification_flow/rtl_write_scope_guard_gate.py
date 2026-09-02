#!/usr/bin/env python3
"""rtl_write_scope_guard_gate.py -- closes a real enforcement gap found by a
code-audit workflow comparing DEBUG_WORKFLOW_GUIDE.md's claims against the
actual wired pipeline (2026-09-02): the ONLY thing that ever stopped the
harness from writing DUT/VIP RTL was a hand-added `.claude/settings.json`
`deny` rule scoped to the Edit tool alone, for one project's hardcoded
paths -- it never covered the Write tool, never covered a Bash/PowerShell-
level write (`>`, `cp`, `sed -i`, ...; see block-destructive.ps1's own new
pattern for that half), and nothing in dv_harness itself generated or
verified that the rule was even present for a new project.

This gate is the code-level half of the fix: it is the first STAGE_GATES
check in IMPLEMENT that inspects WHAT the agent's own edit actually touched
(not what evidence it claims to have gathered before editing, which is all
manual_lookup_before_edit_gate/protocol_isolation_gate check) against the
project's own declared RTL protection boundary. It can only be as strong as
the `touched_paths` list the agent supplies -- like every other STAGE_GATES
script, it cannot itself observe the real Edit/Write tool calls a session
made; closing THAT half is what the settings.json deny rules and the
block-destructive.ps1 hook are for. This gate's job is the one thing those
two cannot do: give the generic, non-Claude-Code-specific dv_harness engine
itself a real, tested check that FAILs IMPLEMENT outright if the agent's own
attested edit list names a path under the project's protected DUT/VIP RTL
tree.

Protected paths are read from `.dv-harness/config.json`'s
`rtl_protection.protected_paths` (see dv_harness/config.py's DEFAULT_CONFIG)
-- never hardcoded here, so a new project registers its own DUT/VIP roots
instead of this script guessing a path shape. An empty/absent list is a
honest, legal default (no protection configured yet) and PASSes -- it is
the project's responsibility to populate it, exactly like every other
project-specific config key in DEFAULT_CONFIG.
"""
import argparse, json, os, pathlib, sys

# Finding I7 fix (2026-09-02 final-review follow-up): prefer the real
# dv_harness package location run_gate() (dv_harness/gates.py) already knows
# and passes via env -- the parents[2] guess only holds in this repo's own
# dogfooding layout, not in a real deployed project running its own copy of
# tools/verification_flow/. Fall back to the guess only for direct/manual
# invocation outside run_gate().
_env_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
_ROOT = pathlib.Path(_env_root) if _env_root else pathlib.Path(__file__).resolve().parents[2]  # dogfooding/legacy fallback
sys.path.insert(0, str(_ROOT))
from dv_harness.config import load_config  # noqa: E402


def _resolved_protected_paths(root_str):
    """Real project config's rtl_protection.protected_paths, each resolved
    to an absolute path (relative entries are anchored under the real
    project root, matching feature_continuity_gate.py's own required_paths
    convention). Never trusts an agent-supplied root -- the caller always
    passes the harness-supplied ContextFlag value."""
    root = pathlib.Path(root_str)
    cfg = load_config(root)
    raw = cfg.get("rtl_protection", {}).get("protected_paths", [])
    out = []
    for entry in raw:
        if not entry:
            continue
        p = pathlib.Path(entry)
        if not p.is_absolute():
            p = root / p
        out.append(p.resolve())
    return out


def _is_under(candidate: pathlib.Path, protected: pathlib.Path) -> bool:
    try:
        candidate.relative_to(protected)
        return True
    except ValueError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", required=True)
    ap.add_argument("--root", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.edit).read_text())

    touched = d.get("touched_paths")
    if not isinstance(touched, list):
        print(json.dumps({"status": "FAIL", "reason": "TOUCHED_PATHS_MISSING_OR_INVALID"}))
        return 2

    protected = _resolved_protected_paths(a.root)
    if not protected:
        # Honest no-op: this project has not declared an RTL protection
        # boundary yet. Never fabricated as a PASS-with-teeth -- see this
        # gate's own module docstring on what still requires a populated
        # rtl_protection.protected_paths list to actually bite.
        print(json.dumps({"status": "PASS", "reason": "NO_PROTECTED_PATHS_CONFIGURED",
                          "touched": len(touched)}))
        return 0

    violations = []
    for raw_path in touched:
        if not raw_path:
            continue
        cand = pathlib.Path(str(raw_path))
        if not cand.is_absolute():
            cand = pathlib.Path(a.root) / cand
        cand = cand.resolve()
        for prot in protected:
            if _is_under(cand, prot):
                violations.append({"path": str(raw_path), "protected_root": str(prot)})
                break

    if violations:
        print(json.dumps({"status": "FAIL", "reason": "RTL_WRITE_SCOPE_VIOLATION",
                          "violations": violations}))
        return 3

    print(json.dumps({"status": "PASS", "touched": len(touched), "protected_paths": len(protected)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
