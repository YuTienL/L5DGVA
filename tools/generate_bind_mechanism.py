#!/usr/bin/env python3
# Mirrors tools/generate_amba_fabric_environment.py's exact shape -- a
# standalone script, not a dv-harness CLI subcommand.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.uvm_generator.bind_mechanism_generator import emit_bind_sv, emit_hook_svh

ap = argparse.ArgumentParser()
ap.add_argument('--topology', required=True,
                help='JSON: {"protocol", "bind_entries": [...], '
                     '"macro_redirects": {...}, "top_scope_decls": [...]}')
ap.add_argument('--out', required=True)
ap.add_argument('--require-tier', action='store_true',
                help='Require every bind entry to carry a classify_bind_tier() tier. '
                     'An unconfirmed T3 or any T4 entry is ALWAYS refused regardless '
                     'of this flag; this only additionally refuses untiered entries.')
ap.add_argument('--phy-boundary',
                help='Path to a real phy_boundary.json (dv_harness.phy_boundary). Its '
                     'bind_decision fixes the MOUNT LAYER before any target path is '
                     'accepted (CLAUDE.md Bind-Location Rule 5): a SERIAL-only or '
                     'UNDECIDABLE boundary refuses emission outright, and an entry '
                     'declaring phy_boundary_signals is additionally checked against the '
                     'sanctioned parallel port set. Also read from the topology JSON key '
                     '"phy_boundary" when this flag is absent.')
ap.add_argument('--require-phy-boundary', action='store_true',
                help='Refuse to emit at all unless a phy_boundary document is supplied. '
                     'The strict reading of Rule 5 -- the mount-layer decision must exist '
                     'BEFORE a bind target is chosen, not be optional metadata.')
a = ap.parse_args()
t = json.loads(pathlib.Path(a.topology).read_text(encoding="utf-8"))
phy_doc = None
_phy_path = a.phy_boundary or t.get("phy_boundary")
if _phy_path:
    from dv_harness.phy_boundary import load_phy_boundary
    phy_doc = load_phy_boundary(_phy_path)
out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
(out / f"{t['protocol']}_uvm_bind_inst.sv").write_text(
    emit_bind_sv(t["bind_entries"], require_tier=a.require_tier,
                 phy_boundary_doc=phy_doc,
                 require_phy_boundary=a.require_phy_boundary), encoding="utf-8")
(out / "dv_uvm_hook.svh").write_text(
    emit_hook_svh(t["protocol"], t.get("macro_redirects", {}), t.get("top_scope_decls", [])),
    encoding="utf-8")
print(json.dumps({"status": "OK", "out": str(out)}))
