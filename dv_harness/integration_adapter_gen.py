"""dv_harness/integration_adapter_gen.py -- GENERATES the actual adapter glue
code once a SubsystemAdapterIR mapping has been resolved (2026-09-06).

THE GAP THIS CLOSES
--------------------
`dv_harness/subsystem_adapter_ir.py` resolves a caller-supplied mapping
against the FIXED 8-operation logical vocabulary
(configure/start/stop/reset/wait_ready/execute/monitor/get_status) and
reports, per operation, RESOLVED (a real mapped task/sequence name, carried
through verbatim) or UNSUPPORTED_OPERATION (no real mapping exists, and no
stub is synthesized). That module's own docstring is explicit about where it
stops: "It authors no task/sequence body and validates nothing about whether
a resolved task/sequence name is itself syntactically or semantically
correct... that is this batch's other, separately-scoped modules' job (or a
downstream generator's)." A repo-wide check (2026-09-06) confirmed no such
downstream generator existed anywhere in this codebase -- REUSE OVER
REINVENT was applied before writing a line of this file: `subsystem_adapter_
ir.py` already covers the resolution half completely and is left untouched;
this module is the additive generation step it names but does not perform.

WHAT THIS MODULE GENERATES, AND WHAT IT REFUSES TO INVENT
-------------------------------------------------------------
Not protocol-behavior content -- "No Golden-Reference Content Mining"
forbids that, and this module never authors what a task/sequence actually
DOES. What it generates is mechanical GLUE: for each of the 8 fixed logical
operations, a `` `define `` macro redirect from a fixed facade macro name
(`DV_ADAPTER_<OPERATION>`) to the real, already-resolved task/sequence name.
This is the SAME "macro redirect, placed before the real definitions it
forwards to" wiring convention `dv_harness/uvm_generator/
bind_mechanism_generator.py`'s `emit_hook_svh()` already establishes for
this project's DV_UVM hook -- reused here for the fixed 8-operation
vocabulary rather than invented from scratch.

A RESOLVED operation's macro forwards, byte-for-byte, to the caller's own
real mapped name (after `assert_resolved_name_is_callable_identifier()`
confirms it is at least a syntactically plausible SystemVerilog callable --
the one piece of validation `subsystem_adapter_ir.py`'s own docstring
explicitly leaves to "a downstream generator"). An UNSUPPORTED_OPERATION
NEVER gets a fabricated task/sequence name: its macro forwards instead to a
generated, deterministically-named failure task
(`dv_adapter_unsupported_operation_<subsystem>_<operation>`) whose body does
nothing but `` `uvm_fatal `` with the resolved IR's own real, honest
`reason` text for why no mapping exists -- so a caller who accidentally
wires an unmapped operation into a running environment gets a loud,
traceable failure at the point of use, never a silently-invented no-op or a
plausible-sounding guessed call.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .subsystem_adapter_ir import (
    LOGICAL_OPERATIONS,
    STATUS_RESOLVED,
    STATUS_UNSUPPORTED_OPERATION,
    SubsystemAdapterIR,
    SubsystemAdapterIRError,
    build_subsystem_adapter_ir,
)


class IntegrationAdapterGenError(ValueError):
    """Raised on malformed generator input, or a resolved task/sequence name
    that is not even a plausible SystemVerilog callable -- never silently
    repaired or dropped, mirroring `SubsystemAdapterIRError`'s own
    discipline."""

    def __init__(self, code: str, detail: Optional[Dict[str, Any]] = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {self.detail}")


# ---------------------------------------------------------------------------
# Identifier hygiene: this module's ONLY validation/naming responsibility.
# ---------------------------------------------------------------------------

_VALID_SV_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

FACADE_MACRO_PREFIX = "DV_ADAPTER_"


def _sanitize_identifier_component(text: str, *, fallback: str) -> str:
    """Turn arbitrary real text (a subsystem name) into a legal
    SystemVerilog identifier fragment. Never used to invent a task/sequence
    NAME -- only to build this module's OWN generated wrapper identifiers
    (the file guard, the unsupported-operation failure task name) from an
    already-known, real label."""
    if not text:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", text)
    if not cleaned:
        return fallback
    if not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = f"_{cleaned}"
    return cleaned


def facade_macro_name(operation: str) -> str:
    """The fixed facade macro name for one of the 8 logical operations --
    deterministic from `LOGICAL_OPERATIONS` alone, never from a resolved
    mapping."""
    return f"{FACADE_MACRO_PREFIX}{operation.upper()}"


def unsupported_operation_task_name(subsystem_name: Optional[str], operation: str) -> str:
    """The deterministic name of the honest-failure task an UNSUPPORTED_
    OPERATION macro forwards to. Built ONLY from the real subsystem name and
    the real (fixed-vocabulary) operation name -- never from anything a
    caller's mapping did or did not supply for this operation, since by
    definition nothing real was supplied."""
    subsystem_part = _sanitize_identifier_component(subsystem_name or "", fallback="")
    if subsystem_part:
        return f"dv_adapter_unsupported_operation_{subsystem_part}_{operation}"
    return f"dv_adapter_unsupported_operation_{operation}"


def assert_resolved_name_is_callable_identifier(operation: str, name: Optional[str]) -> None:
    """The one piece of validation `subsystem_adapter_ir.py`'s own docstring
    explicitly leaves to a downstream generator: is a RESOLVED task/sequence
    name actually a plausible SystemVerilog callable -- a simple identifier,
    or a dotted hierarchical call such as `env.vseqr.start_seq`?

    Refuses, rather than silently emitting a macro redirect to invalid text,
    a resolved name that is empty, contains whitespace, or carries any
    character outside a legal identifier in any dotted segment (including an
    empty segment from a leading/trailing/doubled `.`)."""
    if not name:
        raise IntegrationAdapterGenError("RESOLVED_NAME_EMPTY", {"operation": operation})
    segments = name.split(".")
    for seg in segments:
        if not _VALID_SV_IDENTIFIER_RE.match(seg):
            raise IntegrationAdapterGenError(
                "RESOLVED_NAME_NOT_A_VALID_SV_IDENTIFIER",
                {"operation": operation, "resolved_name": name, "bad_segment": seg},
            )


# ---------------------------------------------------------------------------
# Per-operation glue record: what this module decided to emit, and why.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterGlueOperationRecord:
    """One fixed logical operation's real generation outcome."""

    operation: str
    status: str
    macro_name: str
    forwards_to: str
    generated_stub: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "macro_name": self.macro_name,
            "forwards_to": self.forwards_to,
            "generated_stub": self.generated_stub,
            "reason": self.reason,
        }


def build_adapter_glue_records(ir: SubsystemAdapterIR) -> List[AdapterGlueOperationRecord]:
    """Build the per-operation generation plan from an already-resolved
    `SubsystemAdapterIR` -- requires a real `SubsystemAdapterIR` instance
    (never a plain dict/duck-typed stand-in): the resolution half is
    `subsystem_adapter_ir.build_subsystem_adapter_ir()`'s own job, and this
    module never re-implements or re-guesses it."""
    if not isinstance(ir, SubsystemAdapterIR):
        raise IntegrationAdapterGenError(
            "NOT_A_SUBSYSTEM_ADAPTER_IR", {"got": repr(type(ir))}
        )

    records: List[AdapterGlueOperationRecord] = []
    for op in LOGICAL_OPERATIONS:
        res = ir.resolve(op)
        macro = facade_macro_name(op)
        if res.status == STATUS_RESOLVED:
            name = res.resolved_task_or_sequence_name
            assert_resolved_name_is_callable_identifier(op, name)
            records.append(
                AdapterGlueOperationRecord(
                    operation=op,
                    status=res.status,
                    macro_name=macro,
                    forwards_to=name,
                    generated_stub=False,
                    reason=res.reason,
                )
            )
        elif res.status == STATUS_UNSUPPORTED_OPERATION:
            stub_name = unsupported_operation_task_name(ir.subsystem_name, op)
            records.append(
                AdapterGlueOperationRecord(
                    operation=op,
                    status=res.status,
                    macro_name=macro,
                    forwards_to=stub_name,
                    generated_stub=True,
                    reason=res.reason,
                )
            )
        else:  # pragma: no cover -- subsystem_adapter_ir pins exactly these two statuses
            raise IntegrationAdapterGenError(
                "UNKNOWN_RESOLUTION_STATUS", {"operation": op, "status": res.status}
            )
    return records


# ---------------------------------------------------------------------------
# SystemVerilog glue emission.
# ---------------------------------------------------------------------------


def generate_adapter_glue_svh(ir: SubsystemAdapterIR) -> str:
    """Pure textual macro-redirect assembly from an already-resolved IR
    only -- never invents a task/sequence name not present in (or
    deterministically derivable from the absence of a mapping for) the IR."""
    records = build_adapter_glue_records(ir)
    subsystem_label = ir.subsystem_name or "UNNAMED_SUBSYSTEM"
    guard = _sanitize_identifier_component(
        f"dv_adapter_{ir.subsystem_name or 'unnamed'}_svh", fallback="dv_adapter_unnamed_svh"
    ).upper()

    lines: List[str] = [
        "// GENERATED by dv_harness/integration_adapter_gen.py -- SubsystemAdapterIR glue code.",
        "// Mechanical `define macro redirect only, the same bridge-macro convention",
        "// dv_harness/uvm_generator/bind_mechanism_generator.py's emit_hook_svh() already",
        "// establishes for this project's DV_UVM hook. No task/sequence body is authored",
        "// here and no operation's real behavior is invented -- every RESOLVED macro below",
        "// forwards verbatim to a real, caller-supplied task/sequence name; every",
        "// UNSUPPORTED_OPERATION macro below forwards to an explicit failure task instead",
        "// of a fabricated stub.",
        f"// Subsystem: {subsystem_label}",
        "",
        f"`ifndef {guard}",
        f"`define {guard}",
        "",
    ]

    for rec in records:
        if rec.status == STATUS_RESOLVED:
            lines.append(
                f"// {rec.operation} -- RESOLVED: forwards to real task/sequence "
                f"'{rec.forwards_to}'"
            )
        else:
            lines.append(f"// {rec.operation} -- UNSUPPORTED_OPERATION: {rec.reason}")
            lines.append(
                "// no stub was synthesized; forwards instead to an explicit, honest "
                "failure task below."
            )
        lines.append(f"`define {rec.macro_name} {rec.forwards_to}")
        lines.append("")

    unsupported = [r for r in records if r.generated_stub]
    if unsupported:
        lines.append(
            "// -- explicit failure tasks for every UNSUPPORTED_OPERATION macro above --"
        )
        lines.append(
            "// Top-module scope (mirroring emit_hook_svh's own top-scope discipline: a"
        )
        lines.append(
            "// real task body, unlike a macro redirect, cannot be `bind`-ed into place)."
        )
        for rec in unsupported:
            escaped_reason = rec.reason.replace('"', '\\"')
            lines.append(f"task {rec.forwards_to}();")
            lines.append(
                f'  `uvm_fatal("DV_ADAPTER_UNSUPPORTED_OPERATION", "logical operation '
                f"'{rec.operation}' has no real mapped task/sequence for subsystem "
                f"'{subsystem_label}' -- {escaped_reason}\")"
            )
            lines.append("endtask")
            lines.append("")

    lines.append(f"`endif // {guard}")
    return "\n".join(lines) + "\n"


def write_adapter_glue_svh(ir: SubsystemAdapterIR, out_path: Union[str, Path]) -> str:
    """Generate the `.svh` glue file and write it to `out_path`. Returns the
    real path written (as a string)."""
    text = generate_adapter_glue_svh(ir)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# End-to-end: mapping entries -> resolved IR -> generated glue, one call.
# ---------------------------------------------------------------------------


def build_and_generate_adapter_glue(
    mapping_entries: Sequence[Any],
    subsystem_name: Optional[str] = None,
    *,
    out_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Resolve a caller-supplied mapping (via the untouched, unmodified
    `subsystem_adapter_ir.build_subsystem_adapter_ir()`) and generate its
    glue code in one call. Any `SubsystemAdapterIRError` from resolution
    propagates unmodified -- this function never swallows or reinterprets a
    resolution-time refusal."""
    ir = build_subsystem_adapter_ir(mapping_entries, subsystem_name=subsystem_name)
    records = build_adapter_glue_records(ir)
    svh = generate_adapter_glue_svh(ir)
    result: Dict[str, Any] = {
        "ir": ir.to_dict(),
        "operations": [r.to_dict() for r in records],
        "svh": svh,
    }
    if out_path is not None:
        result["written_to"] = write_adapter_glue_svh(ir, out_path)
    return result


# ---------------------------------------------------------------------------
# Standalone front door: `python -m dv_harness.integration_adapter_gen`.
# Deliberately no `dv-harness` CLI verb / no cli.py or gates.py edit -- see
# this item's own disclosed-choice convention (matching several other
# recent modules in this codebase that made the identical choice when
# cli.py/gates.py were under concurrent edit pressure).
# ---------------------------------------------------------------------------


def execute_verb(
    mapping_file: str, *, subsystem_name: Optional[str] = None, out_path: Optional[str] = None
) -> Tuple[str, int]:
    """Shared implementation for the CLI. Returns (text, exit_code): 0 on a
    successful generation (even one carrying UNSUPPORTED_OPERATION findings
    -- those are an honest, reportable fact about the mapping, not a
    generator failure), 1 on a resolution/generation error, 2 on a usage
    error."""
    try:
        data = json.loads(Path(mapping_file).read_text(encoding="utf-8"))
    except OSError as exc:
        return (f"could not read {mapping_file!r}: {exc}", 2)
    except json.JSONDecodeError as exc:
        return (f"{mapping_file!r} is not valid JSON: {exc}", 2)

    if isinstance(data, dict):
        entries = data.get("mapping_entries")
        subsystem_name = subsystem_name or data.get("subsystem_name")
    else:
        entries = data
    if entries is None:
        return (
            f"{mapping_file!r} must be a JSON list of mapping entries, or an object "
            f"carrying a 'mapping_entries' list",
            2,
        )

    try:
        result = build_and_generate_adapter_glue(
            entries, subsystem_name=subsystem_name, out_path=out_path
        )
    except (SubsystemAdapterIRError, IntegrationAdapterGenError) as exc:
        return (f"{exc}", 1)

    lines = [f"subsystem: {result['ir']['subsystem_name']}"]
    for op_record in result["operations"]:
        lines.append(
            f"  {op_record['operation']:<12} {op_record['status']:<22} "
            f"-> {op_record['forwards_to']}"
        )
    if "written_to" in result:
        lines.append(f"written: {result['written_to']}")
    else:
        lines.append("")
        lines.append(result["svh"])
    return ("\n".join(lines), 0)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.integration_adapter_gen",
        description="Generate adapter glue code (a `define macro-redirect .svh file) from "
        "an already-resolved subsystem_adapter_ir.SubsystemAdapterIR mapping. Runs "
        "no build/simulation and mints no approval.",
    )
    ap.add_argument(
        "mapping_file",
        help="JSON file: a bare list of {operation, existing_task_or_sequence_name} "
        "mapping entries, or an object carrying 'mapping_entries' and optionally "
        "'subsystem_name'.",
    )
    ap.add_argument("--subsystem-name", default=None, help="Override/supply the subsystem name.")
    ap.add_argument("--out", default=None, help="Write the generated .svh to this path.")
    args = ap.parse_args(argv)

    text, code = execute_verb(
        args.mapping_file, subsystem_name=args.subsystem_name, out_path=args.out
    )
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
