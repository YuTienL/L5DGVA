"""dv_harness/cpuread_byte_shift_checker.py -- generalizable checker for
self_check_list.md #25: does a project's CPUREAD task/bridge implementation
perform the byte-shift correction an unaligned sub-word read needs (item's
own Chinese text: "要先確認原來的 DE所使用的 CPUREAD task 是否做 read byte
shift 的額外動作 (由其是 address 不 align 的時後)" -- "confirm whether the
DE's own CPUREAD task performs the extra read-byte-shift action, especially
when the address is not aligned").

WHAT "BYTE-SHIFT CORRECTION" MEANS HERE, grounded in real evidence, not
assumed. `reference/USB_UVM_Handoff/uvm/tb/top/usb_apb_arb.sv` -- this
project's own real reference implementation -- dispatches every CPU-side APB
access at a WORD-ALIGNED address (`{addr[31:2], 2'b00}`) regardless of the
macro's own transfer width, because the underlying bus always returns a full
32-bit word. For a sub-word read (`READ1B`/`READ2B`) the returned word is
therefore NOT yet the requested byte/halfword -- it still has to be shifted
into the correct lane using the address's own low bits, exactly as the real
model this bridge stands in for already does:
    MODEL_ALL.v:2031  rdata <= prdata[raddr[1:0]*8  +: 8];   // GSIHOSTREAD1B
    MODEL_ALL.v:2116  rdata <= prdata[raddr[1]*16   +: 16];  // GSIHOSTREAD2B
and which `usb_apb_arb.sv` itself reproduces:
    READ1B (line ~592-601): `int lane = addr[1:0]; ... data = 32'(tmp[8*lane +: 8]);`
    READ2B (line ~603-613): `int lane = addr[1:0]; ... data = 32'(tmp[16*lane[1] +: 16]);`
    READ4B (line ~617-637): `data = tmp;` -- no shift: a full 32-bit word needs
        no byte-lane correction at all, whatever address bits happen to be set.
A full-word (>= the assumed bus word width) CPUREAD task therefore never
needs this check; a genuinely sub-word one does, and "byte-shift present"
means the task's OWN output-data computation references the address's low
bits (directly, or through a local variable it was assigned from) combined
with a lane-selecting multiply/shift -- never merely that the task RUNS.

REUSE OVER REINVENT, exactly as this item instructs ("reuse their real
task-resolution machinery rather than writing a second one; this item adds
the CORRECTNESS check on top of task resolution, not a new resolver"):
  * `command_task_trace.trace_command()` is the ONLY thing in this module
    that decides how a DE command name resolves inside a real generated
    environment (`env_dir`) -- its TASK_MACRO leg (direct `task <name>`
    declaration, `` `define <name> <target> `` macro redirect, case-dispatch
    handler, or `patterns_registry`-shaped file mapping). This module never
    re-derives that resolution and never treats a leg it reports AMBIGUOUS or
    NOT_FOUND as anything but exactly that.
  * `de_command_style_learning.build_de_command_registry()` is reused (via
    `discover_cpuread_commands()`) to find which CPUREAD-shaped commands a
    real DE `command.txt`-style file actually contains, filtered to DUT-side
    register-read context through `reference_pattern_audit._classify_context`
    -- this project's own real HOST-vs-DUT naming convention -- rather than a
    second, independently-invented filter.
  * The ONE new step this module adds on top of `trace_command()`'s TASK_MACRO
    leg is following a macro-redirect target ONE level further (the same
    "one level of macro redirect, never further" discipline
    `command_task_trace._resolve_uvm_bridge()` already applies for its own
    UVM_BRIDGE leg) to locate the actual task BODY, using that same module's
    own `_TASK_BODY_RE_TMPL` task-body regex rather than a second one.

GROUNDED AGAINST REAL GENERATED OUTPUT, per this item's own instruction
("Ground the check in real generated bridge-task source text
(bind_mechanism_generator.py / dv_uvm_hook.svh convention) -- never assume
the pattern, verify against real generated output where available"):
  * `examples/generated_usb_real_evidence_v1/bind/dv_uvm_hook.svh` is this
    repo's own real generated `` `define CPUWRITE1B dv_uvm_cpuwrite1b ``-style
    macro-redirect shape, which `_locate_task_body()`'s macro-redirect branch
    below is built to follow.
  * `audit_apb_bridge_entries_byte_shift()` runs this module's byte-shift
    analysis over `bind_mechanism_generator.emit_apb_bridge_tasks_sv()`'s own
    REAL generated task text -- never a hand-authored stand-in for it -- for
    a `direction="READ"` bridge entry. Doing so is itself a real, disclosed
    finding of this gap-close: that generator's current READ-direction
    template (`data = req.{data_field};`) references the VIP data field only
    and never the address argument at all, so this checker reports
    `BYTE_SHIFT_MISSING` for any sub-word entry built from it. Fixing that
    generator is NOT this item's scope (which is "build a ... checker", not
    "fix the generator"); it is disclosed here rather than silently left
    unmentioned.

EVIDENCE TRUTH RULE: a command this module cannot resolve at all
(`COMMAND_NOT_FOUND`), one whose task-macro leg is genuinely ambiguous
(`AMBIGUOUS_TASK_RESOLUTION`), one whose real task body could not be located
after following one macro-redirect level (`TASK_BODY_NOT_LOCATED`), one whose
own name does not match this project's real register-macro naming convention
so its transfer width cannot be determined without guessing (`WIDTH_UNKNOWN`),
or one whose signature carries no recognizable address/data argument
(`ARGUMENTS_UNKNOWN`) is reported as exactly that -- never silently folded
into `BYTE_SHIFT_PRESENT` or `BYTE_SHIFT_MISSING`, both of which require a
real, located task body and a real, cited textual match (or the real absence
of one) for their verdict.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import command_task_trace
from . import de_command_style_learning as decsl
from . import reference_pattern_audit as rpa
from .uvm_generator import bind_mechanism_generator as bmg

# --- vocabulary ---------------------------------------------------------------

STATUS_PRESENT = "BYTE_SHIFT_PRESENT"
STATUS_MISSING = "BYTE_SHIFT_MISSING"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE_FULL_WORD_TRANSFER"
STATUS_WIDTH_UNKNOWN = "WIDTH_UNKNOWN"
STATUS_ARGUMENTS_UNKNOWN = "ARGUMENTS_UNKNOWN"
STATUS_COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
STATUS_AMBIGUOUS = "AMBIGUOUS_TASK_RESOLUTION"
STATUS_TASK_BODY_NOT_LOCATED = "TASK_BODY_NOT_LOCATED"
STATUS_BLOCKED = "BLOCKED"

# Statuses that represent a genuine PASS/FAIL verdict about byte-shift
# correctness (as opposed to "this module could not determine an answer").
DECIDED_STATUSES = (STATUS_PRESENT, STATUS_MISSING)

# Default assumed bus/dispatch word width in bytes. Grounded in the real
# reference implementation's own comments ("PDATA_WIDTH_32",
# `{addr[31:2], 2'b00}` clearing exactly 2 low bits) -- a 32-bit APB word.
# Always an explicit, overridable parameter, never a silent hardcode: a
# project whose bus word width differs passes `word_bytes=` accordingly.
DEFAULT_WORD_BYTES = 4


class CpureadByteShiftCheckerError(ValueError):
    """Programmer misuse (e.g. an empty command-name list), never a
    could-not-decide outcome -- those are reported as findings with one of
    the non-decided statuses above, not raised."""


@dataclass
class CpureadByteShiftFinding:
    command_name: str
    status: str
    width_bytes: Optional[int] = None
    word_bytes: int = DEFAULT_WORD_BYTES
    task_body_source: Optional[str] = None
    task_name: Optional[str] = None
    addr_arg: Optional[str] = None
    data_arg: Optional[str] = None
    addr_candidates: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    task_macro_citations: list = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --- reused task-resolution machinery -----------------------------------------

def discover_cpuread_commands(command_txt_path, *, context: str = "DUT") -> list:
    """Reuse `de_command_style_learning.build_de_command_registry()` over a
    real DE `command.txt`-style file and return the distinct register-READ
    command names it actually contains, filtered to `context` (default
    `"DUT"`, this project's own real naming convention for CPU/DEV-prefixed
    register access -- see `reference_pattern_audit._classify_context`).
    Never a fixed CPUREAD1B/2B/4B allowlist -- whatever width suffixes the
    real file actually uses are what is returned, in file order.
    """
    registry = decsl.build_de_command_registry(Path(command_txt_path))
    seen: set = set()
    names: list = []
    for entry in registry.entries:
        if entry.kind != decsl.K_REGISTER_READ:
            continue
        m = rpa._REGISTER_MACRO_NAME_RE.match(entry.command_name)
        if not m or m.group("verb") != "READ":
            continue
        if rpa._classify_context(m.group("prefix")) != context:
            continue
        if entry.command_name in seen:
            continue
        seen.add(entry.command_name)
        names.append(entry.command_name)
    return names


def _width_bytes_from_command_name(command_name: str) -> Optional[int]:
    """Reuse `reference_pattern_audit`'s own real `<PREFIX>READ<N>B` macro-
    name shape (`_MACRO_NAME_FRAGMENT`/`_REGISTER_MACRO_NAME_RE`) rather than
    re-deriving a second convention for "what width does this command name
    mean". Returns None (never a guess) for a name that does not match it, or
    whose verb is not READ."""
    m = rpa._REGISTER_MACRO_NAME_RE.match(command_name)
    if not m or m.group("verb") != "READ":
        return None
    return int(m.group("width"))


def _read_source_files(env_path: Path) -> dict:
    """Read every real source file under `env_dir` this repo's own resolver
    already scans (`command_task_trace.SOURCE_EXTENSIONS`) -- a plain,
    read-only file read, not a second resolution pass."""
    out: dict = {}
    for p in sorted(env_path.rglob("*")):
        if p.is_file() and p.suffix.lower() in command_task_trace.SOURCE_EXTENSIONS:
            try:
                out[str(p)] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return out


def _find_task_body_by_name(name: str, files_text: dict):
    """First `task ... <name> ... endtask` span found -- reuses
    `command_task_trace._TASK_BODY_RE_TMPL` verbatim (the exact regex that
    module's own leg-2 macro-redirect follow-through already uses), rather
    than a second "what does a task declaration look like" regex."""
    pat = re.compile(command_task_trace._TASK_BODY_RE_TMPL.format(re.escape(name)), re.DOTALL)
    for path, text in files_text.items():
        m = pat.search(text)
        if m:
            return path, m.group(0)
    return None, None


_MACRO_TARGET_RE_TMPL = r"`define\s+{0}\s+(\S+)"


def _macro_redirect_target(command_name: str, define_snippet: str) -> Optional[str]:
    """Extract the RHS of a `` `define <command_name> <target> `` citation
    snippet (the real `dv_uvm_hook.svh` shape:
    `` `define CPUREAD1B  sysn063.u_usb_apb_arb.READ1B `` or
    `` `define CPUWRITE1B dv_uvm_cpuwrite1b ``). Never a guess: returns None
    if the snippet does not literally contain that redirect."""
    m = re.search(_MACRO_TARGET_RE_TMPL.format(re.escape(command_name)), define_snippet)
    return m.group(1) if m else None


def _task_name_from_target(target: str) -> str:
    """A macro-redirect target may be a bare identifier (this repo's own
    `dv_uvm_cpuwrite1b`-style bridge convention) or a full hierarchical path
    (the real reference project's `sysn063.u_usb_apb_arb.READ1B`) -- either
    way the task itself is declared under its own last name segment."""
    return target.rsplit(".", 1)[-1]


def _locate_task_body(command_name: str, citations, files_text: dict):
    """The ONE new step this module adds on top of `trace_command()`'s
    TASK_MACRO leg: given that leg's own real citations, follow AT MOST one
    more hop -- a direct declaration needs none, a case-dispatch handler or a
    macro redirect needs exactly one, a `patterns_registry`-mapped file's own
    content is used directly -- to locate the real task BODY text for
    correctness analysis. Never invents a body: returns None when none of
    the real citations lead to one.

    Returns (file_path, resolved_task_name, body_text) or None.
    """
    by_kind: dict = {}
    for c in citations:
        by_kind.setdefault(c.kind, []).append(c)

    if "task_declaration" in by_kind:
        c = by_kind["task_declaration"][0]
        _, body = _find_task_body_by_name(command_name, {c.file_path: files_text.get(c.file_path, "")})
        if body:
            return c.file_path, command_name, body

    if "handler_task_declaration" in by_kind:
        c = by_kind["handler_task_declaration"][0]
        handler_name = c.detail or command_name
        path, body = _find_task_body_by_name(handler_name, files_text)
        if body:
            return path, handler_name, body

    if "macro_definition" in by_kind:
        c = by_kind["macro_definition"][0]
        target = _macro_redirect_target(command_name, c.snippet)
        if target:
            task_name = _task_name_from_target(target)
            path, body = _find_task_body_by_name(task_name, files_text)
            if body:
                return path, task_name, body

    if "registry_mapped_file" in by_kind:
        c = by_kind["registry_mapped_file"][0]
        text = files_text.get(c.file_path)
        if text:
            _, body = _find_task_body_by_name(command_name, {c.file_path: text})
            if body:
                return c.file_path, command_name, body
            # A `patterns_registry`-mapped file's own content IS the pattern
            # body (command_task_trace's own registry_mapped_file shape) --
            # no `task ... endtask` wrapper is guaranteed to exist in it.
            return c.file_path, command_name, text

    return None


# --- correctness check: does the task body shift by the address's low bits ---

_LANE_ASSIGN_RE_TMPL = r"\b([A-Za-z_]\w*)\s*=\s*\b{0}\b\s*(\[[^\]]*\])"


def _find_lane_candidates(body_text: str, addr_arg: str) -> list:
    """Local variables assigned directly from a bit-select of the address
    argument (e.g. `int lane = addr[1:0];`, the real `usb_apb_arb.sv`
    convention) -- these, plus the address argument itself, are the only
    names a byte-shift expression is credited for referencing."""
    candidates = [addr_arg]
    pat = re.compile(_LANE_ASSIGN_RE_TMPL.format(re.escape(addr_arg)))
    for m in pat.finditer(body_text):
        name = m.group(1)
        if name not in candidates:
            candidates.append(name)
    return candidates


def _shift_factor_pattern(candidates: list) -> Optional[re.Pattern]:
    """A lane-selecting multiply-by-8/16 (either operand order, streaming
    part-select or plain multiply) or an equivalent shift, referencing one of
    `candidates` -- the shape both real citations use:
    `tmp[8*lane +: 8]` (READ1B) and `tmp[16*lane[1] +: 16]` (READ2B)."""
    if not candidates:
        return None
    alts = []
    for name in candidates:
        esc = re.escape(name)
        alts.append(rf"\b{esc}\b\s*(?:\[[^\]]*\])?\s*\*\s*(?:8|16)\b")
        alts.append(rf"\b(?:8|16)\b\s*\*\s*\b{esc}\b")
        alts.append(rf">>\s*\(?\s*\b{esc}\b")
        alts.append(rf"\b{esc}\b\s*<<\s*3\b")
    return re.compile("|".join(alts))


def _find_shift_evidence(body_text: str, addr_arg: str, data_arg: str):
    """Every real assignment (`=` or `<=`, never `==`) to the output data
    argument, checked for a lane-selecting shift/part-select expression on
    its own RHS referencing the address argument or a local variable
    genuinely derived from it. Returns (evidence_list, candidate_names)."""
    candidates = _find_lane_candidates(body_text, addr_arg)
    factor_re = _shift_factor_pattern(candidates)
    data_assign_re = re.compile(
        r"\b" + re.escape(data_arg) + r"\b\s*(?:<=|=(?!=))\s*(?P<rhs>[^;]*);", re.DOTALL)
    evidence: list = []
    if factor_re is None:
        return evidence, candidates
    for m in data_assign_re.finditer(body_text):
        rhs = m.group("rhs")
        if factor_re.search(rhs):
            evidence.append({
                "statement": " ".join(m.group(0).split()),
                "matched_rhs": " ".join(rhs.split()),
            })
    return evidence, candidates


# --- task-signature parsing ---------------------------------------------------

_TASK_HEADER_RE = re.compile(
    r"\btask\s+(?:automatic\s+)?\w+\s*\((?P<params>[^)]*)\)", re.DOTALL)
_PARAM_DIRECTION_RE = re.compile(r"^(input|output|inout|ref)\b(.*)$", re.DOTALL)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def _parse_task_params(body_text: str) -> list:
    """[(direction, name), ...] parsed from the FIRST `task ...(...)`
    header found in `body_text`. A best-effort, evidence-only parse -- an
    unrecognized parameter is skipped rather than guessed at."""
    m = _TASK_HEADER_RE.search(body_text)
    if not m:
        return []
    params = []
    for raw in m.group("params").split(","):
        raw = raw.split("=", 1)[0].strip()  # drop a default value
        if not raw:
            continue
        dm = _PARAM_DIRECTION_RE.match(raw)
        if not dm:
            continue
        direction = dm.group(1)
        tokens = _IDENT_RE.findall(dm.group(2))
        if not tokens:
            continue
        params.append((direction, tokens[-1]))
    return params


def _select_addr_arg(params: list) -> Optional[str]:
    inputs = [name for direction, name in params if direction == "input"]
    for name in inputs:
        if "addr" in name.lower():
            return name
    return inputs[0] if inputs else None


def _select_data_arg(params: list) -> Optional[str]:
    outputs = [name for direction, name in params
               if direction in ("output", "inout", "ref")]
    for name in outputs:
        if "data" in name.lower():
            return name
    return outputs[0] if outputs else None


def analyze_task_body_byte_shift(body_text: str, *, addr_arg: str = None,
                                  data_arg: str = None) -> dict:
    """The core correctness check over one already-located task body's raw
    text. `addr_arg`/`data_arg` are taken from the task's own signature when
    not supplied. Returns a plain dict (never a verdict guessed from
    anything but a real, cited textual match)."""
    params = _parse_task_params(body_text)
    resolved_addr = addr_arg or _select_addr_arg(params)
    resolved_data = data_arg or _select_data_arg(params)
    if not resolved_addr or not resolved_data:
        return {
            "status": STATUS_ARGUMENTS_UNKNOWN,
            "addr_arg": resolved_addr, "data_arg": resolved_data,
            "evidence": [], "addr_candidates": [],
            "reason": ("could not identify both an address (input) and a "
                       "data (output/inout) argument in this task's own "
                       "signature; byte-shift correctness cannot be "
                       "decided without one"),
        }
    evidence, candidates = _find_shift_evidence(body_text, resolved_addr, resolved_data)
    if evidence:
        return {"status": STATUS_PRESENT, "addr_arg": resolved_addr,
                "data_arg": resolved_data, "evidence": evidence,
                "addr_candidates": candidates, "reason": None}
    return {
        "status": STATUS_MISSING, "addr_arg": resolved_addr,
        "data_arg": resolved_data, "evidence": [], "addr_candidates": candidates,
        "reason": (f"no assignment to output '{resolved_data}' references the "
                   f"address argument '{resolved_addr}' (or a local variable "
                   f"derived from it, e.g. 'lane = {resolved_addr}[1:0]') "
                   f"combined with a byte/halfword-lane shift or part-select; "
                   f"an unaligned sub-word read would return the wrong byte "
                   f"lane"),
    }


# --- public entry points -------------------------------------------------------

def audit_cpuread_byte_shift(env_dir, command_names, *,
                              word_bytes: int = DEFAULT_WORD_BYTES,
                              use_verible: bool = False) -> list:
    """Audit one or more DE CPUREAD-style command names against a real
    generated environment (`env_dir`), via `command_task_trace.trace_command()`
    for resolution and this module's own `_locate_task_body()`/
    `analyze_task_body_byte_shift()` for the correctness check on top of it.
    """
    if not command_names:
        raise CpureadByteShiftCheckerError("command_names must be a non-empty sequence")
    env_path = Path(env_dir)
    files_text = _read_source_files(env_path)
    findings: list = []
    for command_name in command_names:
        findings.append(_audit_one_command(command_name, env_path, files_text,
                                            word_bytes=word_bytes,
                                            use_verible=use_verible))
    return findings


def _audit_one_command(command_name: str, env_path: Path, files_text: dict, *,
                        word_bytes: int, use_verible: bool) -> CpureadByteShiftFinding:
    width_bytes = _width_bytes_from_command_name(command_name)
    trace = command_task_trace.trace_command(
        command_name, env_path, use_verible=use_verible)

    if trace.status == command_task_trace.STATUS_BLOCKED:
        return CpureadByteShiftFinding(
            command_name=command_name, status=STATUS_BLOCKED,
            width_bytes=width_bytes, word_bytes=word_bytes, reason=trace.reason)

    leg1 = trace.legs.get(command_task_trace.LEG_TASK_MACRO)
    if leg1 is None or leg1.status == command_task_trace.LEG_NOT_FOUND:
        return CpureadByteShiftFinding(
            command_name=command_name, status=STATUS_COMMAND_NOT_FOUND,
            width_bytes=width_bytes, word_bytes=word_bytes,
            reason=(leg1.reason if leg1 is not None else trace.reason))

    if leg1.status == command_task_trace.LEG_AMBIGUOUS:
        return CpureadByteShiftFinding(
            command_name=command_name, status=STATUS_AMBIGUOUS,
            width_bytes=width_bytes, word_bytes=word_bytes, reason=leg1.reason,
            task_macro_citations=[c.to_dict() for c in leg1.citations])

    located = _locate_task_body(command_name, leg1.citations, files_text)
    if located is None:
        return CpureadByteShiftFinding(
            command_name=command_name, status=STATUS_TASK_BODY_NOT_LOCATED,
            width_bytes=width_bytes, word_bytes=word_bytes,
            reason=("the task-macro leg resolved, but no real task body "
                    "could be located by following its citation(s) one "
                    "level further (direct declaration, case-dispatch "
                    "handler, macro-redirect target, or registry-mapped "
                    "file)"),
            task_macro_citations=[c.to_dict() for c in leg1.citations])

    task_file, task_name, body_text = located

    if width_bytes is None:
        return CpureadByteShiftFinding(
            command_name=command_name, status=STATUS_WIDTH_UNKNOWN,
            word_bytes=word_bytes, task_body_source=task_file, task_name=task_name,
            reason=(f"command name {command_name!r} does not match this "
                    f"project's real register-macro convention "
                    f"(reference_pattern_audit's <PREFIX>READ<N>B shape); "
                    f"the transfer width cannot be determined without "
                    f"guessing, so byte-shift necessity cannot be decided"))

    if width_bytes >= word_bytes:
        return CpureadByteShiftFinding(
            command_name=command_name, status=STATUS_NOT_APPLICABLE,
            width_bytes=width_bytes, word_bytes=word_bytes,
            task_body_source=task_file, task_name=task_name,
            reason=(f"{width_bytes}-byte transfer is >= the assumed "
                    f"{word_bytes}-byte bus word; a full-word read returns "
                    f"the whole word and needs no byte-lane shift"))

    result = analyze_task_body_byte_shift(body_text)
    return CpureadByteShiftFinding(
        command_name=command_name, status=result["status"],
        width_bytes=width_bytes, word_bytes=word_bytes,
        task_body_source=task_file, task_name=task_name,
        addr_arg=result["addr_arg"], data_arg=result["data_arg"],
        addr_candidates=result["addr_candidates"], evidence=result["evidence"],
        reason=result["reason"])


def audit_apb_bridge_entries_byte_shift(bridge_entries, *,
                                         word_bytes: int = DEFAULT_WORD_BYTES) -> list:
    """Ground the check against REAL generated output (this item's own
    instruction): run the byte-shift correctness analysis over
    `bind_mechanism_generator.emit_apb_bridge_tasks_sv()`'s own generated
    text for every `direction="READ"` entry -- never a hand-authored stand-in
    for that generator's output. `bridge_entries` is the module's own real
    entry schema (`task_name`/`direction`/`sequencer_path`/
    `vip_transaction_type`/`vip_addr_field`/`vip_data_field`/`addr_width`/
    `data_width`/`reason`, see `bind_mechanism_generator.
    validate_apb_bridge_entries`); this function reuses that module's own
    validation and emission, never re-deriving either."""
    read_entries = [e for e in bridge_entries if e.get("direction") == "READ"]
    if not read_entries:
        return []
    generated_text = bmg.emit_apb_bridge_tasks_sv(bridge_entries)
    findings: list = []
    for entry in read_entries:
        task_name = entry["task_name"]
        width_bytes = max(1, int(entry["data_width"]) // 8)
        _, body_text = _find_task_body_by_name(task_name, {"<generated>": generated_text})
        if not body_text:
            findings.append(CpureadByteShiftFinding(
                command_name=task_name, status=STATUS_TASK_BODY_NOT_LOCATED,
                width_bytes=width_bytes, word_bytes=word_bytes,
                task_body_source="<bind_mechanism_generator.emit_apb_bridge_tasks_sv>",
                reason="emit_apb_bridge_tasks_sv() did not emit a locatable "
                       "task body for this entry"))
            continue
        if width_bytes >= word_bytes:
            findings.append(CpureadByteShiftFinding(
                command_name=task_name, status=STATUS_NOT_APPLICABLE,
                width_bytes=width_bytes, word_bytes=word_bytes, task_name=task_name,
                task_body_source="<bind_mechanism_generator.emit_apb_bridge_tasks_sv>",
                reason=(f"{width_bytes}-byte transfer is >= the assumed "
                        f"{word_bytes}-byte bus word; no byte-lane shift is "
                        f"needed")))
            continue
        result = analyze_task_body_byte_shift(body_text)
        findings.append(CpureadByteShiftFinding(
            command_name=task_name, status=result["status"],
            width_bytes=width_bytes, word_bytes=word_bytes, task_name=task_name,
            task_body_source="<bind_mechanism_generator.emit_apb_bridge_tasks_sv>",
            addr_arg=result["addr_arg"], data_arg=result["data_arg"],
            addr_candidates=result["addr_candidates"], evidence=result["evidence"],
            reason=result["reason"]))
    return findings


def format_finding(finding: CpureadByteShiftFinding) -> str:
    lines = [f"{finding.command_name} -> {finding.status}"
             + (f" ({finding.reason})" if finding.reason else "")]
    if finding.task_body_source:
        lines.append(f"  task_body_source: {finding.task_body_source} "
                      f"(resolved task name: {finding.task_name})")
    if finding.evidence:
        for e in finding.evidence:
            lines.append(f"  evidence: {e['statement']}")
    return "\n".join(lines)


def overall_exit_code(findings) -> int:
    if any(f.status == STATUS_MISSING for f in findings):
        return 1
    if any(f.status not in DECIDED_STATUSES + (STATUS_NOT_APPLICABLE,) for f in findings):
        return 2
    return 0
