#!/usr/bin/env python3
"""Per-protocol status for this project's real protocol_capability_registry.json.

This used to print one QUALIFICATION column next to a `status` column that read
`REAL_GENERATION_READY` for all 11 protocols -- including four with no
protocol-specific Python module behind them at all. The single column could not
tell "a generic UVM skeleton exists for this protocol" (true everywhere) apart
from "this protocol's own behaviour is modelled" (true for five), so it
overstated readiness for the rest. Both facts are now separate columns, sourced
from dv_harness/protocol_capability.py, and this command REFUSES to print at all
when the registry claims more than the code supports -- a status command that
can print a stale overstatement is how the overstatement survived in the first
place.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import protocol_capability as pc  # noqa: E402


def main() -> int:
    try:
        pc.assert_registry_matches_code(ROOT)
    except (pc.ProtocolCapabilityDriftError, FileNotFoundError) as exc:
        print(f"REFUSING TO REPORT STATUS -- {exc}", file=sys.stderr)
        print("Run `python -m dv_harness.protocol_capability --sync` after fixing the code.",
              file=sys.stderr)
        return 2

    registry = pc.load_registry(ROOT)["protocols"]
    print(f"{'PROTOCOL':34} {'CAPABILITY (code that exists)':30} "
          f"{'QUALIFICATION (proven)':24} PROTOCOL MODEL GENERATOR")
    print("-" * 132)
    for name in pc.known_protocols():
        entry = registry.get(name, {})
        model = entry.get("protocol_model_generator", "NONE")
        print(f"{name:34} {entry.get('capability_status', 'UNKNOWN'):30} "
              f"{entry.get('qualification_status', 'BUILDER_AVAILABLE'):24} {model}")
    print()
    print("CAPABILITY: what generation code exists -- GENERIC_SKELETON_ONLY means only the "
          "protocol-agnostic")
    print(f"            skeleton ({pc.GENERIC_SKELETON_GENERATOR}), nothing protocol-specific.")
    print("            PROTOCOL_MODEL_PARTIAL entries name their unmodelled layers in the "
          "registry's does_not_model.")
    print("QUALIFICATION: how far a generated environment has been PROVEN "
          "(dv_harness/qualification.py's 8-tier ladder).")
    print("Only USB is DUT_PROVEN. No other protocol has been bound to real RTL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
