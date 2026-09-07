"""dv_harness/iface_classification.py -- EXTERNAL/INTERNAL RTL port classification: an
additive pass over design_architecture_ir.py's already-built full instance tree.

THE GAP THIS CLOSES (spec section 283)
---------------------------------------
Nothing in this repo classified an RTL port as EXTERNAL (it crosses the DUT top boundary --
a real chip-level pin/pad as far as this parsed build is concerned) or INTERNAL (it connects
one module to another module inside the hierarchy only). `dv_harness/connectivity.py` already
derives a VIP-facing ROLE (active/passive) from a port's DIRECTION for one already-chosen bind
target -- a different question, decided per bind candidate, never per the whole parsed design.
`dv_harness/phy_boundary.py` classifies a SERIAL-vs-PARALLEL PHY<->controller boundary from the
same verible-parsed port table -- a real, adjacent, but different axis (which LAYER a monitor may
mount at, not which ports are chip-level pins). `dv_harness/verification_boundary_ir.py`
classifies a caller-DECLARED verification boundary into a 10-value taxonomy (EXTERNAL_PROTOCOL,
REGISTER_CSR, ...) plus a 7-role ownership record -- it never parses RTL and never asks "does this
port cross the DUT top boundary" at all. None of the three overlaps this module's question, and a
repo-wide search before writing this file confirmed nothing else does either.

REUSE OVER REINVENT
--------------------
This is deliberately NOT a new parser. `dv_harness/design_architecture_ir.py` already builds the
one real fact this classification needs: a full, recursive, multi-file INSTANCE TREE (which
module is a root -- a DUT top, explicitly forced via `top_module` or structurally derived as
"never instantiated by anything else this build parsed" -- and which module is reached only as an
instantiated CHILD somewhere under a root). This module imports `design_architecture_ir` and
walks that already-built tree; it does not touch `verible_parser.py` or invoke verible itself.

THE CLASSIFICATION RULE
------------------------
A port belongs to a MODULE, and a module's ports are classified together, from the module's own
ROLE in the already-built instance tree -- never from a per-port signal-level trace (which would
need a second, connectivity-level analysis this module deliberately does not perform):

  * ROLE_TOP     -- the module is a root of the instance tree (the DUT top, or one of a real
                    multi-top forest) in every tree it appears in. Every one of its ports is
                    EXTERNAL: as far as this parsed build can tell, it is a real chip-level pin.
  * ROLE_SUBMODULE -- the module is reached ONLY as a resolved instantiated child (at depth >= 1)
                    somewhere under a root, never itself a root. Every one of its ports is
                    INTERNAL: it connects this module to whatever instantiates it, never directly
                    to the outside world.
  * ROLE_AMBIGUOUS -- the module appears as BOTH a root in one tree AND an instantiated child in
                    another (only reachable through a genuine instantiation CYCLE among the parsed
                    modules, where `build_instance_tree()` itself has no unambiguous single root to
                    fall back to and reports every parsed module as its own root). Its ports are
                    honestly UNKNOWN, never resolved by guessing -- a real conflicting fact is
                    surfaced as a warning, not silently picked one way.
  * ROLE_UNREACHED -- the module was parsed into the registry but never appears anywhere in this
                    build's actual instance tree (root or child) -- a dead/unreferenced module, or
                    a structural root excluded by an explicit `top_module` override. Its ports are
                    honestly UNKNOWN: this module was never placed in the hierarchy this build
                    resolved, so neither EXTERNAL nor INTERNAL is a claim this build can support.

An instance whose `module_name` was never parsed at all (an external module, a VIP BFM, a std
cell -- `design_architecture_ir.py`'s own honest "unresolved leaf" case) contributes no port data
here either, for the same reason: this build never parsed that module's own port list, so nothing
about its ports can be classified.

BOUNDARY, stated rather than implied closed
--------------------------------------------
  * This is a STRUCTURAL, hierarchy-position classification, not a signal-level trace. A
    submodule's port that happens to be wired straight through to a top-level port (a genuine
    pass-through/feedthrough) is still reported INTERNAL: it is the SUBMODULE's own port, and the
    submodule is not the DUT top. Whether a net is *also* reachable from the boundary is a
    different, connectivity-level question this module does not answer.
  * It never picks a winner for ROLE_AMBIGUOUS/ROLE_UNREACHED -- both are reported as real,
    distinctly-named UNKNOWN outcomes with the evidence that produced them, never silently
    defaulted to EXTERNAL or INTERNAL.
  * It is a pure, read-only pass over an already-built `design_architecture_ir` result (or an
    equivalently-shaped `{"modules": ..., "instance_tree": ...}` dict); it runs no build, no
    simulation, and mints no approval.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import design_architecture_ir as dai

SCHEMA_VERSION = "1.0"

ROLE_TOP = "TOP"
ROLE_SUBMODULE = "SUBMODULE"
ROLE_AMBIGUOUS = "AMBIGUOUS_BOTH_ROLES"
ROLE_UNREACHED = "UNREACHED"
MODULE_ROLES = (ROLE_TOP, ROLE_SUBMODULE, ROLE_AMBIGUOUS, ROLE_UNREACHED)

CLASS_EXTERNAL = "EXTERNAL"
CLASS_INTERNAL = "INTERNAL"
CLASS_UNKNOWN = "UNKNOWN"
PORT_CLASSES = (CLASS_EXTERNAL, CLASS_INTERNAL, CLASS_UNKNOWN)

_ROOT_OCCURRENCE = "root"
_CHILD_OCCURRENCE = "child"

__all__ = [
    "SCHEMA_VERSION",
    "ROLE_TOP",
    "ROLE_SUBMODULE",
    "ROLE_AMBIGUOUS",
    "ROLE_UNREACHED",
    "MODULE_ROLES",
    "CLASS_EXTERNAL",
    "CLASS_INTERNAL",
    "CLASS_UNKNOWN",
    "PORT_CLASSES",
    "IfaceClassificationError",
    "classify_module_roles",
    "classify_interfaces",
    "format_report",
    "execute_verb",
    "main",
]


class IfaceClassificationError(Exception):
    """Raised only for a malformed input (an `architecture_ir`/`instance_tree` argument that is
    not even a mapping). Never raised for an absent/unresolvable RTL fact -- those are reported as
    an honest module role / port classification on the result itself, per the Evidence Truth
    Rule."""


# ---------------------------------------------------------------------------
# Module-role derivation -- a pure walk over an already-built instance_tree
# ---------------------------------------------------------------------------

def _walk_tree_occurrences(instance_tree: dict) -> Dict[str, List[str]]:
    """Walks every tree in `instance_tree['trees']` and records, for every RESOLVED module_name
    that appears anywhere, one evidence citation per occurrence (never deduped away -- a genuine
    both-roles finding needs every citation it was built from, not just one)."""
    occurrences: Dict[str, List[str]] = {}

    def record(name: str, note: str) -> None:
        occurrences.setdefault(name, []).append(note)

    def walk(node: dict, is_root: bool, tree_root_name: str) -> None:
        name = node.get("module_name")
        if name and node.get("resolved"):
            if is_root:
                record(name, "root of the instance tree rooted at %r" % tree_root_name)
            else:
                inst = node.get("instance_name") or "<unnamed instance>"
                record(name, "instantiated as %r at depth %s under root %r"
                       % (inst, node.get("depth"), tree_root_name))
        for child in node.get("children", []) or []:
            walk(child, False, tree_root_name)

    for tree in instance_tree.get("trees", []) or []:
        root_name = tree.get("module_name")
        walk(tree, True, root_name)

    return occurrences


def classify_module_roles(instance_tree: dict) -> Dict[str, Dict[str, Any]]:
    """Derives each module's real ROLE (see module docstring) purely from `instance_tree`'s own
    already-built roots/children -- a module never appearing in `instance_tree` at all is simply
    absent from the returned mapping (the caller's own module registry decides ROLE_UNREACHED for
    a module absent here, since this function only sees what the tree actually reached)."""
    if not isinstance(instance_tree, dict):
        raise IfaceClassificationError(
            "instance_tree must be a dict, got %r" % type(instance_tree).__name__)
    occurrences = _walk_tree_occurrences(instance_tree)
    out: Dict[str, Dict[str, Any]] = {}
    for name, notes in occurrences.items():
        is_root_somewhere = any(n.startswith("root of") for n in notes)
        is_child_somewhere = any(n.startswith("instantiated as") for n in notes)
        if is_root_somewhere and is_child_somewhere:
            role = ROLE_AMBIGUOUS
        elif is_root_somewhere:
            role = ROLE_TOP
        else:
            role = ROLE_SUBMODULE
        out[name] = {"role": role, "evidence": list(notes)}
    return out


# ---------------------------------------------------------------------------
# Top-level classification
# ---------------------------------------------------------------------------

_ROLE_PORT_CLASS = {
    ROLE_TOP: CLASS_EXTERNAL,
    ROLE_SUBMODULE: CLASS_INTERNAL,
}


def _port_classification_for_role(name: str, role: str, evidence: List[str]) -> Tuple[str, str]:
    if role == ROLE_TOP:
        return CLASS_EXTERNAL, (
            "module %r is a DUT top (an instance-tree root) -- every one of its ports crosses "
            "the DUT top boundary" % name)
    if role == ROLE_SUBMODULE:
        return CLASS_INTERNAL, (
            "module %r is reached only as an instantiated child inside this build's instance "
            "tree -- its ports are module-to-module only, never a direct DUT-top boundary "
            "crossing" % name)
    if role == ROLE_AMBIGUOUS:
        return CLASS_UNKNOWN, (
            "module %r appears BOTH as an instance-tree root and as an instantiated child "
            "elsewhere in this build (a real instantiation cycle among the parsed modules "
            "left no unambiguous single root) -- refusing to guess a single EXTERNAL/INTERNAL "
            "classification: %s" % (name, "; ".join(evidence)))
    # ROLE_UNREACHED
    return CLASS_UNKNOWN, (
        "module %r was parsed but never appears in this build's actual instance tree (neither "
        "as a root nor as an instantiated child) -- possibly dead/unreferenced RTL, or a "
        "structural root excluded by an explicit top_module override" % name)


def classify_interfaces(architecture_ir: Union[dict, Any]) -> dict:
    """The one real entry point. `architecture_ir` is a `design_architecture_ir.build_architecture_ir()`
    result (or an equivalently-shaped dict carrying real `modules`/`instance_tree` keys, `status`
    optional -- a caller may hand in `{"modules": ..., "instance_tree": ...}` directly). Returns a
    report classifying every parsed module's own ports as EXTERNAL/INTERNAL/UNKNOWN. Never raises
    for an absent/unresolvable RTL fact; raises `IfaceClassificationError` only for a malformed
    (non-mapping) argument."""
    if not isinstance(architecture_ir, dict):
        raise IfaceClassificationError(
            "architecture_ir must be a dict, got %r" % type(architecture_ir).__name__)

    status = architecture_ir.get("status")
    if status is not None and status != "BUILT":
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NOT_AVAILABLE",
            "reason": "architecture_ir status is %r (%s) -- nothing to classify"
                      % (status, architecture_ir.get("reason")),
            "dut_top_modules": [],
            "modules": {},
            "summary": {"external_port_count": 0, "internal_port_count": 0, "unknown_port_count": 0},
            "warnings": [],
        }

    modules = architecture_ir.get("modules") or {}
    instance_tree = architecture_ir.get("instance_tree") or {"top_modules": [], "trees": []}
    if not isinstance(modules, dict):
        raise IfaceClassificationError("architecture_ir['modules'] must be a dict, got %r"
                                        % type(modules).__name__)

    if not modules:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NOT_AVAILABLE",
            "reason": "architecture_ir carries no parsed modules -- nothing to classify",
            "dut_top_modules": [],
            "modules": {},
            "summary": {"external_port_count": 0, "internal_port_count": 0, "unknown_port_count": 0},
            "warnings": [],
        }

    module_roles = classify_module_roles(instance_tree)

    out_modules: Dict[str, Any] = {}
    ext_count = internal_count = unknown_count = 0
    warnings: List[str] = []

    for name in sorted(modules):
        mod = modules[name] or {}
        role_info = module_roles.get(name)
        if role_info is None:
            role, evidence = ROLE_UNREACHED, []
        else:
            role, evidence = role_info["role"], role_info["evidence"]

        port_class, port_reason = _port_classification_for_role(name, role, evidence)
        if role in (ROLE_AMBIGUOUS, ROLE_UNREACHED):
            warnings.append("module %r: role=%s -- %s" % (name, role, port_reason))

        ports_out = []
        for p in (mod.get("ports") or []):
            ports_out.append({
                "name": p.get("name"),
                "direction": p.get("direction"),
                "data_type": p.get("data_type"),
                "classification": port_class,
                "reason": port_reason,
            })
            if port_class == CLASS_EXTERNAL:
                ext_count += 1
            elif port_class == CLASS_INTERNAL:
                internal_count += 1
            else:
                unknown_count += 1

        out_modules[name] = {
            "role": role,
            "role_evidence": evidence,
            "ports": ports_out,
        }

    dut_top_modules = sorted(n for n, m in out_modules.items() if m["role"] == ROLE_TOP)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CLASSIFIED",
        "reason": None,
        "dut_top_modules": dut_top_modules,
        "modules": out_modules,
        "summary": {
            "external_port_count": ext_count,
            "internal_port_count": internal_count,
            "unknown_port_count": unknown_count,
        },
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Reporting / standalone front door
# ---------------------------------------------------------------------------

def format_report(report: dict) -> str:
    if report["status"] != "CLASSIFIED":
        return "%s: %s" % (report["status"], report["reason"])
    lines = [
        "iface_classification schema %s: %d module(s) classified, DUT top module(s)=%s"
        % (report["schema_version"], len(report["modules"]), report["dut_top_modules"])
    ]
    for w in report["warnings"]:
        lines.append("  WARNING: %s" % w)
    for name, mod in report["modules"].items():
        lines.append("  module %s (role=%s):" % (name, mod["role"]))
        for p in mod["ports"]:
            lines.append("    %s %s : %s" % (p.get("direction") or "?", p.get("name"), p["classification"]))
    s = report["summary"]
    lines.append("  summary: EXTERNAL=%d INTERNAL=%d UNKNOWN=%d"
                 % (s["external_port_count"], s["internal_port_count"], s["unknown_port_count"]))
    return "\n".join(lines)


def execute_verb(rtl_files: Sequence[Union[str, Path]], *,
                  verible_bin: str = dai.DEFAULT_VERIBLE_BIN,
                  top_module: Optional[str] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.iface_classification` (there is no
    `dv-harness` CLI verb for this yet -- see the module docstring's disclosed residual). Builds
    the real `design_architecture_ir` first (never re-parses RTL itself), then runs
    `classify_interfaces()` over it. Returns (text, exit_code): 0 the classification was produced
    (at least one module classified), 2 NOT_AVAILABLE (no files supplied, or nothing could be
    parsed/classified). Reads and reports only; runs, builds, submits and approves nothing."""
    ir = dai.build_architecture_ir(rtl_files, verible_bin=verible_bin, top_module=top_module)
    report = classify_interfaces(ir)
    text = json.dumps(report, indent=2) if as_json else format_report(report)
    code = 0 if report["status"] == "CLASSIFIED" else 2
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.iface_classification",
        description="Classify every parsed RTL module's ports as EXTERNAL (crosses the DUT top "
                    "boundary) or INTERNAL (module-to-module only), from design_architecture_ir.py's "
                    "already-built full instance tree. Reads and reports only; runs nothing.")
    ap.add_argument("--rtl", action="append", required=True, dest="rtl_files",
                    help="An RTL file to include in this build (repeatable).")
    ap.add_argument("--top-module", default=None,
                    help="Force this module as the sole instance-tree root (the DUT top).")
    ap.add_argument("--verible-bin", default="verible-verilog-syntax")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(a.rtl_files, verible_bin=a.verible_bin,
                                   top_module=a.top_module, as_json=a.json)
    except dai.DesignArchitectureIRError as exc:
        print(str(exc))
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
