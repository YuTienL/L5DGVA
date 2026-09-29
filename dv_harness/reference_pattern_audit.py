"""Systematic reference-pattern coverage audit (Gap #1 close, 2026-09-03).

Confirmed finding this tool exists to close (see
.work/gap-close-reference-audit-report.md): reference/bfm_patterns/*.txt
files (the DE-provided originals) were only ever consulted reactively, bug
by bug, never with an upfront systematic pass. This cost 3 real debugging
rounds finding that `usb_p2_switch_en` is written on the host-side TCA
register (`HOSTWRITE4B(32'h161A_0020, ...)`) but never on the DUT-side TCA
register (`CPUWRITE4B(32'h1272_0020, ...)`) in any HS-speed pattern -- a
mechanically-detectable host/DUT write asymmetry a systematic audit would
have caught on day one.

Grounded against real reference/bfm_patterns/*.txt files (USB2_bulkin.txt,
USB2_bulkout.txt, and cross-checked against USB2_susres.txt/USB3_susres.txt/
USB31_SSPcon.txt) under
D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns/, read-only, 2026-09-03.
The real macro-call idiom confirmed there is:

    `<PREFIX><WRITE|READ><N>B(<addr literal>, <value literal>); //<comment>

e.g. `` `HOSTWRITE4B(32'h161A_0020, 32'h2600); //usb_p2_switch_en=1, ...``.
PREFIX in {HOST, CPU, DEV, ...} is this project's own real HOST-vs-DUT
naming convention (`HOSTWRITE*` writes the host-side xHCI/TCA-host block,
`CPUWRITE*`/`DEVWRITE*` write the DUT-side block) -- confirmed by reading
the real files, not guessed. Base/offset splitting uses the SAME literal
convention those files already use: every address is written
`<width>'h<BASE>_<OFFSET>` with the underscore placed exactly at the
register-block boundary (e.g. `1272_0020` -> base `1272`, offset `0020`).

This module owns extraction (`extract_register_writes`/`extract_directory`)
and the symmetry/coverage detector (`discover_paired_blocks`/
`find_symmetry_asymmetries`) built on top of it. `audit_directory` is the
single entry point a caller (CLI or another tool) should use.

SECOND LAYER, ADDED 2026-09-04: SYS-7 command.txt grammar / control-flow /
dependency analysis (`extract_command_statements` .. `analyze_command_file`,
see the "SYS-7" section below). The write-symmetry audit above reads exactly
one statement shape and deliberately DISCARDS everything else -- READ-verb
calls, waits, delays, forces, model/VIP task calls, block structure. That is
correct for a write-symmetry audit and useless for the System-Level
Verification Integration workflow's SYS-7, which mandates ordering,
dependencies, delays/waits, interrupt waits, VIP sequence invocation,
termination, reset handling and loops/repetition for every subsystem's
command.txt. The second layer reads the SAME files with the SAME macro-name
shape (`_MACRO_NAME_FRAGMENT` is now the one place that shape is written, and
both layers are built from it) and classifies every statement instead of one.
Both layers are strictly READ-ONLY: SYS-7's own rule is "Do not modify
command.txt during discovery", and nothing in this module has ever had a
write path.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Optional

# --- extraction --------------------------------------------------------------

# Generic on PREFIX (any run of [A-Z][A-Z0-9]* before WRITE/READ<N>B) so a
# not-yet-seen macro name is still extracted, never silently dropped -- this
# tool does not hardcode a fixed macro allowlist beyond the WRITE/READ<N>B
# suffix shape confirmed in the real files.
#
# The macro-NAME shape is written once, here, and both layers of this module
# are built from it: the write-symmetry extractor's full call regex below, and
# the SYS-7 statement classifier's `_REGISTER_MACRO_NAME_RE`. Two independent
# spellings of "what a register-access macro name looks like" is exactly how
# the two layers would come to disagree about the same call.
_MACRO_NAME_FRAGMENT = r"(?P<prefix>[A-Z][A-Z0-9]*)(?P<verb>WRITE|READ)(?P<width>[0-9]+)B"

_MACRO_CALL_RE = re.compile(
    rf"`(?P<macro>{_MACRO_NAME_FRAGMENT})"
    r"\s*\(\s*(?P<addr>[0-9]+'h[0-9A-Fa-f_]+)\s*,\s*(?P<value>[0-9]+'h[0-9A-Fa-f_]+)\s*\)\s*;"
    r"[ \t]*(?://\s*(?P<comment>.*))?"
)

_REGISTER_MACRO_NAME_RE = re.compile(rf"^{_MACRO_NAME_FRAGMENT}$")

_HEX_UNDERSCORE_RE = re.compile(r"^[0-9]+'h([0-9A-Fa-f]+)_([0-9A-Fa-f]+)$")
_HEX_PLAIN_RE = re.compile(r"^[0-9]+'h([0-9A-Fa-f]+)$")


@dataclass
class RegisterWrite:
    """One mechanically-extracted register-write-style macro call.

    `address_or_register`/`value` keep the original literal text (never
    re-encoded) so a human can grep the source file for the exact string
    this record came from. `base`/`offset` are a derived convenience split
    of `address_or_register`, used by the symmetry detector below.
    """
    file: str
    line: int
    macro: str
    prefix: str
    address_or_register: str
    value: str
    host_or_dut_context: str  # "HOST" | "DUT" | "OTHER"
    base: Optional[str] = None
    offset: Optional[str] = None
    comment: str = ""
    commented_out: bool = False


def _classify_context(prefix: str) -> str:
    """HOST vs DUT context from the macro prefix's own real naming
    convention (`HOSTWRITE*` = host-side; `CPUWRITE*`/`DEVWRITE*` = DUT-side
    -- confirmed against the real reference files, see module docstring).
    A substring check, not a fixed enum, so a differently-spelled DUT-side
    prefix that still contains CPU/DEV is classified correctly rather than
    falling through to OTHER.
    """
    if "HOST" in prefix:
        return "HOST"
    if "CPU" in prefix or "DEV" in prefix:
        return "DUT"
    return "OTHER"


def _split_base_offset(addr_literal: str) -> tuple[Optional[str], Optional[str]]:
    """Split an address literal into (base, offset) hex strings, using the
    real files' own underscore-delimited convention first (`1272_0020` ->
    `1272`/`0020`); falls back to a fixed lower-16-bit split only for an
    address literal with no underscore, at the same granularity the
    underscore convention uses everywhere else in these files.
    """
    m = _HEX_UNDERSCORE_RE.match(addr_literal)
    if m:
        return m.group(1).upper(), m.group(2).upper()
    m = _HEX_PLAIN_RE.match(addr_literal)
    if m:
        digits = m.group(1)
        if len(digits) > 4:
            return digits[:-4].upper(), digits[-4:].upper()
        return None, digits.upper()
    return None, None


def extract_register_writes(path: Path) -> list[RegisterWrite]:
    """Mechanically extract every register-write macro call from one
    reference BFM pattern file. Read-only -- never writes to `path`.
    """
    writes: list[RegisterWrite] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        commented_out = raw.strip().startswith("//")
        for m in _MACRO_CALL_RE.finditer(raw):
            if m.group("verb") != "WRITE":
                continue  # READ-style calls are out of scope for this write-symmetry audit
            prefix = m.group("prefix")
            addr = m.group("addr")
            base, offset = _split_base_offset(addr)
            writes.append(RegisterWrite(
                file=path.name,
                line=lineno,
                macro=m.group("macro"),
                prefix=prefix,
                address_or_register=addr,
                value=m.group("value"),
                host_or_dut_context=_classify_context(prefix),
                base=base,
                offset=offset,
                comment=(m.group("comment") or "").strip(),
                commented_out=commented_out,
            ))
    return writes


def extract_directory(pattern_dir: Path, glob: str = "*.txt") -> list[RegisterWrite]:
    """Extract register writes from every file matching `glob` under
    `pattern_dir`, in sorted filename order. Read-only.
    """
    writes: list[RegisterWrite] = []
    for p in sorted(Path(pattern_dir).glob(glob)):
        if p.is_file():
            writes.extend(extract_register_writes(p))
    return writes


# --- register-block pairing + symmetry detector -------------------------------

DEFAULT_MIN_SHARED_OFFSETS = 2
DEFAULT_MIN_JACCARD = 0.3


@dataclass
class PairedBlock:
    """A HOST-context base address and a DUT-context base address the
    detector believes represent the same logical/mirrored register block
    (e.g. host-side TCA at base 161A, DUT-side TCA at base 1272), found
    generically from corpus-wide offset-set overlap -- never a hardcoded
    base-address table.
    """
    host_base: str
    dut_base: str
    shared_offsets: list[str]
    jaccard: float
    host_only_offsets: list[str]  # written HOST-side somewhere in the corpus, never DUT-side anywhere
    dut_only_offsets: list[str]   # written DUT-side somewhere in the corpus, never HOST-side anywhere


@dataclass
class AsymmetryFinding:
    """One flagged host/DUT write asymmetry: within a single file, one side
    of a paired block writes an offset the other side never touches, in
    that same file.
    """
    file: str
    host_base: str
    dut_base: str
    offset: str
    written_side: str  # "HOST" | "DUT"
    missing_side: str  # "DUT" | "HOST"
    example_line: int
    example_macro: str
    example_address: str
    field_hint: str  # the writing side's own trailing comment, e.g. "usb_p2_switch_en=1, ss_hdshk_req=0"


def discover_paired_blocks(
    writes: list[RegisterWrite],
    min_shared_offsets: int = DEFAULT_MIN_SHARED_OFFSETS,
    min_jaccard: float = DEFAULT_MIN_JACCARD,
) -> list[PairedBlock]:
    """Corpus-wide structural pairing: which HOST-context base address and
    which DUT-context base address represent the same logical register
    block, detected generically from offset-set overlap (Jaccard similarity
    of the two bases' write-offset sets, aggregated across every file) --
    e.g. HOST base 161A and DUT base 1272 both write offsets
    {0004, 0008, 0010, 0014, 0020, ...}, so they pair as one mirrored block.

    A commented-out macro call is never a real write and is excluded before
    pairing.
    """
    active = [w for w in writes if not w.commented_out and w.base and w.offset]
    host_offsets: dict[str, set[str]] = {}
    dut_offsets: dict[str, set[str]] = {}
    for w in active:
        if w.host_or_dut_context == "HOST":
            host_offsets.setdefault(w.base, set()).add(w.offset)
        elif w.host_or_dut_context == "DUT":
            dut_offsets.setdefault(w.base, set()).add(w.offset)

    pairs: list[PairedBlock] = []
    for hbase, hoff in host_offsets.items():
        best: Optional[tuple[str, float, set[str]]] = None
        for dbase, doff in dut_offsets.items():
            shared = hoff & doff
            union = hoff | doff
            if len(shared) < min_shared_offsets or not union:
                continue
            jac = len(shared) / len(union)
            if jac < min_jaccard:
                continue
            if best is None or jac > best[1]:
                best = (dbase, jac, shared)
        if best is None:
            continue
        dbase, jac, shared = best
        doff = dut_offsets[dbase]
        pairs.append(PairedBlock(
            host_base=hbase,
            dut_base=dbase,
            shared_offsets=sorted(shared),
            jaccard=round(jac, 3),
            host_only_offsets=sorted(hoff - doff),
            dut_only_offsets=sorted(doff - hoff),
        ))
    return pairs


def find_symmetry_asymmetries(
    writes: list[RegisterWrite],
    paired_blocks: list[PairedBlock],
) -> list[AsymmetryFinding]:
    """Per-file symmetry check on top of `paired_blocks`: for each paired
    block and each file that touches either side of it, flag any offset
    written on one side within that file but never on the paired base, in
    that SAME file. Per-file (not corpus-aggregate) is deliberate: it is
    exactly what reproduces the real usb_p2_switch_en bug, where offset
    0020 IS written DUT-side in USB3_susres.txt (an SS-speed pattern) but
    is never written DUT-side in any HS-speed pattern file even though every
    one of those files writes it HOST-side -- an aggregate-only check would
    see 0020 as "covered somewhere" and miss the per-pattern gap entirely.
    """
    findings: list[AsymmetryFinding] = []
    active = [w for w in writes if not w.commented_out and w.base and w.offset]

    for pb in paired_blocks:
        # file -> side -> {offset: RegisterWrite} (first occurrence kept as the citation)
        per_file: dict[str, dict[str, dict[str, RegisterWrite]]] = {}
        for w in active:
            if w.base == pb.host_base and w.host_or_dut_context == "HOST":
                per_file.setdefault(w.file, {"HOST": {}, "DUT": {}})["HOST"].setdefault(w.offset, w)
            elif w.base == pb.dut_base and w.host_or_dut_context == "DUT":
                per_file.setdefault(w.file, {"HOST": {}, "DUT": {}})["DUT"].setdefault(w.offset, w)

        relevant_offsets = sorted(set(pb.shared_offsets) | set(pb.host_only_offsets) | set(pb.dut_only_offsets))

        for fname, sides in per_file.items():
            for off in relevant_offsets:
                host_hit = sides["HOST"].get(off)
                dut_hit = sides["DUT"].get(off)
                if host_hit and not dut_hit:
                    findings.append(AsymmetryFinding(
                        file=fname, host_base=pb.host_base, dut_base=pb.dut_base,
                        offset=off, written_side="HOST", missing_side="DUT",
                        example_line=host_hit.line, example_macro=host_hit.macro,
                        example_address=host_hit.address_or_register,
                        field_hint=host_hit.comment,
                    ))
                elif dut_hit and not host_hit:
                    findings.append(AsymmetryFinding(
                        file=fname, host_base=pb.host_base, dut_base=pb.dut_base,
                        offset=off, written_side="DUT", missing_side="HOST",
                        example_line=dut_hit.line, example_macro=dut_hit.macro,
                        example_address=dut_hit.address_or_register,
                        field_hint=dut_hit.comment,
                    ))
    # Deterministic order for stable output/tests.
    findings.sort(key=lambda f: (f.file, f.host_base, f.dut_base, f.offset))
    return findings


# --- escalation: an asymmetry finding -> a real question-queue entry ---------

def asymmetry_conflict(finding) -> dict:
    """Turn one `AsymmetryFinding` into a resolved `source_authority` conflict.

    Both sides of a host/DUT write asymmetry come from the SAME authority
    level -- the reference pattern file itself (tier 2, "the reference
    Makefile/command.txt itself") -- so `resolve_conflict()` returns
    UNDECIDABLE_SAME_AUTHORITY every time. That is the honest answer and the
    reason this escalation exists: no amount of re-reading the pattern file
    settles whether the missing write is a real bug (the DUT-side register
    was forgotten) or intended (this speed/mode genuinely does not need it).
    Only the designer knows, so it goes to the queue.

    The second claim's evidence path is an ABSENCE, and it is cited the way
    an absence has to be cited to be checkable: the file, the exact base and
    offset, and the fact that no write to it exists anywhere in that file.
    """
    from . import source_authority as sa

    f = finding if isinstance(finding, dict) else asdict(finding)
    written_base = f["host_base"] if f["written_side"] == "HOST" else f["dut_base"]
    missing_base = f["dut_base"] if f["missing_side"] == "DUT" else f["host_base"]
    hint = f" // {f['field_hint']}" if f.get("field_hint") else ""
    return sa.resolve_conflict([
        sa.SourceClaim(
            source="reference_pattern_file",
            claim=(f"offset {f['offset']} IS programmed {f['written_side']}-side "
                   f"(base {written_base}) in this pattern"),
            evidence_path=(f"{f['file']}:{f['example_line']} "
                           f"`{f['example_macro']}({f['example_address']}){hint}"),
        ),
        sa.SourceClaim(
            source="reference_pattern_file",
            claim=(f"offset {f['offset']} is NEVER programmed {f['missing_side']}-side "
                   f"(base {missing_base}) in this pattern"),
            evidence_path=(f"{f['file']} (whole file): no {f['missing_side']}-side write to "
                           f"base {missing_base} offset {f['offset']}"),
        ),
    ])


def escalate_asymmetries(result: dict, question_store, *, now=None) -> list[dict]:
    """File every finding in an `audit_directory()` result into the REAL
    question queue, one Tier-3 question per asymmetry, and return the
    persisted records.

    `domain="dut"` (-> owner `designer` via `question_queue.route_owner`): a
    missing DUT-side register write is a question about the DUT's programming
    sequence, not about the VIP or the environment.

    Idempotent by construction, and deliberately so: the question key is
    derived from the question text, which is derived from the finding's own
    file/base/offset/line, so re-running the audit over unchanged patterns
    re-mints the SAME Q-ID instead of a duplicate ask. That is what makes it
    safe to wire this into `audit_directory()` itself rather than leaving it
    as a thing a human has to remember to run once.
    """
    from . import source_authority as sa

    records = []
    for f in result.get("findings", []):
        conflict = asymmetry_conflict(f)
        rec = sa.escalate_conflict(
            question_store, conflict, domain="dut",
            subject=(f"host/DUT register-write symmetry for offset {f['offset']} "
                     f"in {f['file']}"),
            context_path=f"{f['file']}:{f['example_line']}",
            now=now,
        )
        if rec is not None:
            records.append(rec)
    return records


# ============================================================================
# SYS-7: command.txt grammar / control-flow / dependency analysis
#
# Everything below is READ-ONLY over the same command.txt / reference pattern
# files the write-symmetry audit above reads. SYS-7's own closing sentence is
# "Do not modify command.txt during discovery", and this module has no write
# path of any kind.
#
# The statement vocabulary is grounded in the REAL command.txt corpus, not
# invented: D:/DV/Task/USB/command.txt and D:/DV/Task/USB/patterns/*.txt (23
# files, read-only, 2026-09-04) use exactly these idioms --
#   `<PFX>WRITE<N>B(addr, value);      register write through a BFM macro
#   `<PFX>READ<N>B(addr, dest);        register read into a variable
#   `<INST>.<task>;  `<INST>.<task>(a) model/VIP task call (GMODEL.GLOBAL_INIT,
#                                      SS_VOUT_MODEL.ss_vout_init_flow,
#                                      SMEMMODEL.FILLMEM("...", 4, 40'h..., 'd32))
#   wait(<hier.signal>);               level wait on a DUT/host signal
#   #<n>;  #(`TIMEBASE*100);           delay
#   force <hier> = <v>;  release <hier>;
#   <hier>.mem_array[3] = 128'h...;    backdoor memory write
#   $display(...)  $finish              observation / termination
#   `include  `ifdef/`else/`endif       preprocessor
# Loop and fork/join constructs are classified too and are HONESTLY ABSENT
# from that corpus (`analyze_command_file` reports loops_and_repetition
# NOT_FOUND for it) -- the classifier covers them because SYS-7 mandates the
# analysis, not because the corpus exercised them.
# ============================================================================

# Statement kinds. One flat vocabulary; a statement gets exactly one kind.
K_REGISTER_WRITE = "REGISTER_WRITE"
K_REGISTER_READ = "REGISTER_READ"
K_MODEL_TASK_CALL = "MODEL_TASK_CALL"
K_MACRO_CALL = "MACRO_CALL"
K_WAIT_CONDITION = "WAIT_CONDITION"
K_EVENT_WAIT = "EVENT_WAIT"
K_DELAY = "DELAY"
K_FORCE = "FORCE"
K_RELEASE = "RELEASE"
K_BACKDOOR_ASSIGN = "BACKDOOR_ASSIGN"
K_ASSIGNMENT = "ASSIGNMENT"
K_DISPLAY = "DISPLAY"
K_ERROR_REPORT = "ERROR_REPORT"
K_TERMINATION = "TERMINATION"
K_MEMORY_LOAD = "MEMORY_LOAD"
K_LOOP = "LOOP"
K_CONDITIONAL = "CONDITIONAL"
K_FORK = "FORK"
K_JOIN = "JOIN"
K_DISABLE = "DISABLE"
K_BLOCK_BEGIN = "BLOCK_BEGIN"
K_BLOCK_END = "BLOCK_END"
K_PROCESS = "PROCESS"
K_DECLARATION = "DECLARATION"
K_DIRECTIVE = "DIRECTIVE"
K_UNCLASSIFIED = "UNCLASSIFIED"

STATEMENT_KINDS: tuple = (
    K_REGISTER_WRITE, K_REGISTER_READ, K_MODEL_TASK_CALL, K_MACRO_CALL,
    K_WAIT_CONDITION, K_EVENT_WAIT, K_DELAY, K_FORCE, K_RELEASE,
    K_BACKDOOR_ASSIGN, K_ASSIGNMENT, K_DISPLAY, K_ERROR_REPORT, K_TERMINATION,
    K_MEMORY_LOAD, K_LOOP, K_CONDITIONAL, K_FORK, K_JOIN, K_DISABLE,
    K_BLOCK_BEGIN, K_BLOCK_END, K_PROCESS, K_DECLARATION, K_DIRECTIVE,
    K_UNCLASSIFIED,
)

# SYS-7's own "init/config/traffic commands" wording, made derivable. Only
# categories a mechanical reading of the statement can actually support are
# assigned; a register write is REGISTER_ACCESS and NOT split into
# config-vs-traffic, because nothing in the file says which it is and
# guessing would be the fabrication the Evidence Truth Rule forbids. A caller
# holding a real classification (e.g. command_inventory.csv's own USER_SCOPE)
# may override per command name.
C_INITIALIZATION = "INITIALIZATION"
C_REGISTER_ACCESS = "REGISTER_ACCESS"
C_SYNCHRONIZATION = "SYNCHRONIZATION"
C_OBSERVATION = "OBSERVATION"
C_MEMORY_BACKDOOR = "MEMORY_BACKDOOR"
C_FORCE_OVERRIDE = "FORCE_OVERRIDE"
C_MODEL_TASK = "MODEL_TASK"
C_TERMINATION = "TERMINATION"
C_CONTROL_FLOW = "CONTROL_FLOW"
C_DECLARATION = "DECLARATION"
C_PREPROCESSOR = "PREPROCESSOR"
C_UNCLASSIFIED = "UNCLASSIFIED"

COMMAND_CATEGORIES: tuple = (
    C_INITIALIZATION, C_REGISTER_ACCESS, C_SYNCHRONIZATION, C_OBSERVATION,
    C_MEMORY_BACKDOOR, C_FORCE_OVERRIDE, C_MODEL_TASK, C_TERMINATION,
    C_CONTROL_FLOW, C_DECLARATION, C_PREPROCESSOR, C_UNCLASSIFIED,
)

# Name tokens that make a wait an INTERRUPT wait rather than a plain level
# wait. Token-based and the MATCHED TOKEN IS CITED on every classification,
# because "the signal name contains evt" is real evidence but is not proof
# that the signal is an interrupt -- a reader must be able to check it.
INTERRUPT_NAME_TOKENS: tuple = ("evt", "event", "irq", "intr", "_int", "int_",
                                "eint", "interrupt", "sts", "status")
RESET_NAME_TOKENS: tuple = ("rst", "reset", "por_")
INIT_NAME_TOKENS: tuple = ("init", "global_init", "bringup", "bring_up")
DMA_NAME_TOKENS: tuple = ("dma", "descriptor", "trb", "scatter")
MEMORY_MODEL_NAME_TOKENS: tuple = ("mem", "dram", "ddr", "sram", "smem")

# Bound on emitted ordering edges. A real pattern file carries >1300 register
# accesses; a pairwise edge set over that is unusable as a report and useless
# as evidence. Only the SEMANTIC edges below are emitted (never implicit
# program order), and a truncated edge list SAYS it was truncated rather than
# presenting a partial graph as complete.
MAX_ORDERING_EDGES = 4000

_NO_SEMICOLON_CONSTRUCTS = (
    (re.compile(r"^(initial|final|always(_comb|_ff|_latch)?)\b"), K_PROCESS),
    (re.compile(r"^begin\b"), K_BLOCK_BEGIN),
    (re.compile(r"^end(module|task|function|case|generate|specify)?\b"), K_BLOCK_END),
    (re.compile(r"^fork\b"), K_FORK),
    (re.compile(r"^join(_any|_none)?\b"), K_JOIN),
    (re.compile(r"^`(include|ifdef|ifndef|else|elsif|endif|define|undef|timescale|"
                r"celldefine|endcelldefine|resetall|default_nettype)\b"), K_DIRECTIVE),
)

_DECLARATION_RE = re.compile(
    r"^(reg|wire|logic|bit|byte|int|integer|real|realtime|time|event|string|"
    r"parameter|localparam|genvar|typedef|enum|struct)\b")
_HIER_ROOT_RE = re.compile(r"(?<![\w.])(`?[A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^\]]*\])?\s*\.")
_MACRO_INVOCATION_RE = re.compile(r"^`(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<tail>.*)$", re.S)
_SYSTEM_TASK_RE = re.compile(r"^\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_ADDR_LITERAL_RE = re.compile(r"^[0-9]*'[hH][0-9A-Fa-f_]+$")


@dataclass
class CommandStatement:
    """One logical statement of a command.txt, comment-stripped and
    classified. `line`/`end_line` are the real physical line span so every
    downstream claim is citable as `<file>:<line>`; `text` is the code with
    comments removed and whitespace collapsed, never a re-rendering."""
    file: str
    line: int
    end_line: int
    kind: str
    text: str
    name: str = ""
    arguments: list = field(default_factory=list)
    comment: str = ""
    block_depth: int = 0
    context: str = ""            # HOST | DUT | OTHER, for register macros
    address: str = ""
    base: Optional[str] = None
    offset: Optional[str] = None
    hierarchy_roots: list = field(default_factory=list)
    category: str = C_UNCLASSIFIED


def _strip_comments(text: str) -> tuple:
    """Strip `//` and `/* */` comments from one file's raw text, string-aware.

    Returns (code_lines, comment_by_line). Comment text is kept per line
    rather than discarded because the real corpus carries the engineering
    meaning of a register write in its trailing comment
    (`//usb_p2_switch_en=1, ss_hdshk_req=0`), and that is the only field hint
    a reader has for what a bare hex value means.
    """
    code_lines: list = []
    comments: dict = {}
    in_block = False
    for idx, raw in enumerate(text.splitlines(), start=1):
        out: list = []
        comment = ""
        i = 0
        in_string = False
        while i < len(raw):
            ch = raw[i]
            if in_block:
                if raw.startswith("*/", i):
                    in_block = False
                    i += 2
                    continue
                i += 1
                continue
            if in_string:
                out.append(ch)
                if ch == "\\" and i + 1 < len(raw):
                    out.append(raw[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
                i += 1
                continue
            if ch == '"':
                in_string = True
                out.append(ch)
                i += 1
                continue
            if raw.startswith("//", i):
                comment = raw[i + 2:].strip()
                break
            if raw.startswith("/*", i):
                in_block = True
                i += 2
                continue
            out.append(ch)
            i += 1
        code_lines.append("".join(out))
        if comment:
            comments[idx] = comment
    return code_lines, comments


def _split_top_level_args(arg_text: str) -> list:
    """Split a call's argument text on commas at bracket depth 0, string-aware.
    `FILLMEM("/home/.../dev_ctrltrb.hex", 4, 40'h2000_1000, 'd32)` -> 4 args,
    and a comma inside the path string or inside a `[7:0]` never splits."""
    args: list = []
    buf: list = []
    depth = 0
    in_string = False
    i = 0
    while i < len(arg_text):
        ch = arg_text[i]
        if in_string:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(arg_text):
                buf.append(arg_text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _outermost_call_args(text: str) -> Optional[str]:
    """Text between the first `(` and its matching `)`, or None when the
    statement is not a call. String-aware so a `(` inside a path literal does
    not open a level."""
    start = None
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start + 1:i]
        i += 1
    return None


def _hierarchy_roots(text: str) -> list:
    """Root identifiers of every dotted hierarchical reference in a statement
    (`sysn063.u_usbmodel_host...` -> `sysn063`; `` `SS_VOUT.u_usbtop[0]... ``
    -> `` `SS_VOUT ``). This is what identifies WHICH environment/model a
    statement reaches into -- SYS-7's COMMAND CONSUMER, derived from the
    reference itself rather than from a class name."""
    # String literals are blanked first: `include "wave.txt" and
    # $display("=>Start 2nd Address Device Command.") both contain a dotted
    # token that is text, not a hierarchical reference, and admitting them
    # would put `wave` and `Command` in the CONSUMER list.
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    roots: list = []
    for m in _HIER_ROOT_RE.finditer(text):
        root = m.group(1)
        if root.startswith("$"):
            continue
        if root not in roots:
            roots.append(root)
    return roots


def _classify_statement(code: str) -> tuple:
    """(kind, name, arguments) for one comment-stripped logical statement."""
    text = code.strip()
    if not text:
        return K_UNCLASSIFIED, "", []
    for pattern, kind in _NO_SEMICOLON_CONSTRUCTS:
        if pattern.match(text):
            name = text.split()[0] if text.split() else ""
            return kind, name.lstrip("`"), []
    body = text.rstrip(";").strip()

    if _DECLARATION_RE.match(body):
        return K_DECLARATION, body.split()[0], []
    if re.match(r"^(repeat|while|for|forever|do)\b", body):
        return K_LOOP, body.split()[0], []
    if re.match(r"^(if|else)\b", body):
        return K_CONDITIONAL, body.split()[0], []
    if re.match(r"^disable\b", body):
        return K_DISABLE, "disable", []
    if re.match(r"^force\b", body):
        return K_FORCE, "force", []
    if re.match(r"^release\b", body):
        return K_RELEASE, "release", []
    if re.match(r"^wait\b", body):
        return K_WAIT_CONDITION, "wait", _split_top_level_args(_outermost_call_args(body) or "")
    if body.startswith("@"):
        return K_EVENT_WAIT, "@", []
    if body.startswith("#"):
        return K_DELAY, "#", [body[1:].strip()]

    sys_task = _SYSTEM_TASK_RE.match(body)
    if sys_task:
        name = "$" + sys_task.group("name")
        args = _split_top_level_args(_outermost_call_args(body) or "")
        if sys_task.group("name") in ("finish", "stop"):
            return K_TERMINATION, name, args
        if sys_task.group("name") in ("error", "fatal", "warning"):
            return K_ERROR_REPORT, name, args
        if sys_task.group("name").startswith("readmem"):
            return K_MEMORY_LOAD, name, args
        return K_DISPLAY, name, args

    macro = _MACRO_INVOCATION_RE.match(body)
    if macro:
        head = macro.group("name")
        tail = macro.group("tail")
        args = _split_top_level_args(_outermost_call_args(body) or "")
        if _REGISTER_MACRO_NAME_RE.match(head):
            verb = _REGISTER_MACRO_NAME_RE.match(head).group("verb")
            kind = K_REGISTER_WRITE if verb == "WRITE" else K_REGISTER_READ
            return kind, head, args
        if tail.lstrip().startswith("."):
            # `GMODEL.trapvalue[13:0]=... is a backdoor assign through a macro
            # root; `GMODEL.GLOBAL_INIT / `SMEMMODEL.FILLMEM(...) is a task call.
            if "=" in tail and _outermost_call_args(body) is None:
                return K_BACKDOOR_ASSIGN, "`" + head + tail.split("=")[0].strip(), []
            dotted = re.match(r"^\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)", tail)
            task = dotted.group(1) if dotted else ""
            return K_MODEL_TASK_CALL, f"`{head}.{task}" if task else "`" + head, args
        return K_MACRO_CALL, "`" + head, args

    if "=" in body and not re.search(r"[=!<>]=", body.split("=")[0] + "="):
        lhs = body.split("=", 1)[0].strip()
        if "." in lhs:
            return K_BACKDOOR_ASSIGN, lhs, []
        return K_ASSIGNMENT, lhs, []
    return K_UNCLASSIFIED, "", []


def _categorize(kind: str, name: str) -> str:
    lowered = (name or "").lower()
    if kind in (K_REGISTER_WRITE, K_REGISTER_READ):
        return C_REGISTER_ACCESS
    if kind == K_MODEL_TASK_CALL:
        if any(tok in lowered for tok in INIT_NAME_TOKENS):
            return C_INITIALIZATION
        if any(tok in lowered for tok in MEMORY_MODEL_NAME_TOKENS) or "fillmem" in lowered:
            return C_MEMORY_BACKDOOR
        return C_MODEL_TASK
    if kind in (K_WAIT_CONDITION, K_EVENT_WAIT, K_DELAY):
        return C_SYNCHRONIZATION
    if kind in (K_DISPLAY, K_ERROR_REPORT):
        return C_OBSERVATION
    if kind == K_TERMINATION:
        return C_TERMINATION
    if kind in (K_BACKDOOR_ASSIGN, K_MEMORY_LOAD):
        return C_MEMORY_BACKDOOR
    if kind in (K_FORCE, K_RELEASE):
        return C_FORCE_OVERRIDE
    if kind in (K_LOOP, K_CONDITIONAL, K_FORK, K_JOIN, K_BLOCK_BEGIN,
                K_BLOCK_END, K_PROCESS, K_DISABLE):
        return C_CONTROL_FLOW
    if kind == K_DECLARATION:
        return C_DECLARATION
    if kind == K_DIRECTIVE:
        return C_PREPROCESSOR
    return C_UNCLASSIFIED


def extract_command_statements(path: Path) -> list:
    """Parse one command.txt into classified `CommandStatement`s. Read-only.

    Statements are accumulated across physical lines until bracket depth
    returns to 0 and the buffer terminates -- the real corpus's
    `SMEMMODEL.FILLMEM("...", 4, 40'h2000_1000, 'd32);` spans four lines, and
    a line-at-a-time reader (which is what the write-symmetry layer above is)
    sees four fragments instead of one call.
    """
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    code_lines, comments = _strip_comments(raw)

    statements: list = []
    buf: list = []
    buf_start = 0
    depth = 0
    block_depth = 0

    def flush(end_line: int) -> None:
        nonlocal buf, block_depth
        code = " ".join(part.strip() for part in buf if part.strip())
        buf = []
        if not code.strip():
            return
        kind, name, args = _classify_statement(code)
        if kind == K_UNCLASSIFIED and not code.strip(" ;"):
            return
        depth_at = block_depth
        if kind in (K_BLOCK_BEGIN, K_FORK):
            block_depth += 1
        elif kind in (K_BLOCK_END, K_JOIN):
            block_depth = max(0, block_depth - 1)
            depth_at = block_depth
        comment = " ".join(comments[n] for n in range(buf_start, end_line + 1)
                           if n in comments).strip()
        stmt = CommandStatement(
            file=path.name, line=buf_start, end_line=end_line, kind=kind,
            text=re.sub(r"\s+", " ", code).strip(), name=name,
            arguments=args, comment=comment, block_depth=depth_at,
            hierarchy_roots=_hierarchy_roots(code),
            category=_categorize(kind, name),
        )
        if kind in (K_REGISTER_WRITE, K_REGISTER_READ):
            stmt.context = _classify_context(
                _REGISTER_MACRO_NAME_RE.match(name).group("prefix"))
            if args and _ADDR_LITERAL_RE.match(args[0].replace(" ", "")):
                stmt.address = args[0].replace(" ", "")
                stmt.base, stmt.offset = _split_base_offset(stmt.address)
        statements.append(stmt)

    for lineno, code in enumerate(code_lines, start=1):
        if not code.strip() and not buf:
            continue
        if not buf:
            buf_start = lineno
        buf.append(code)
        for ch in code:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
        joined = " ".join(part.strip() for part in buf if part.strip()).strip()
        if depth > 0:
            continue
        if joined.endswith(";"):
            flush(lineno)
            continue
        if any(p.match(joined) for p, _ in _NO_SEMICOLON_CONSTRUCTS):
            flush(lineno)
    if buf:
        flush(len(code_lines))
    return statements


def _matched_tokens(text: str, tokens) -> list:
    lowered = (text or "").lower()
    return [t for t in tokens if t in lowered]


def classify_wait(stmt: CommandStatement) -> dict:
    """Classify one wait/event statement as an INTERRUPT_EVENT_WAIT or a
    SIGNAL_LEVEL_WAIT, citing the token that decided it.

    SYS-7 lists "interrupt waits" as a distinct thing to analyze. Nothing in a
    command.txt declares that a signal is an interrupt, so this is a
    NAME-EVIDENCE classification and says so: `matched_tokens` is the actual
    evidence, and a wait with no matching token is SIGNAL_LEVEL_WAIT rather
    than a guess in either direction."""
    condition = " ".join(stmt.arguments) or stmt.text
    tokens = _matched_tokens(condition, INTERRUPT_NAME_TOKENS)
    return {
        "line": stmt.line,
        "condition": condition,
        "wait_class": "INTERRUPT_EVENT_WAIT" if tokens else "SIGNAL_LEVEL_WAIT",
        "matched_tokens": tokens,
        "basis": "SIGNAL_NAME_TOKEN_MATCH" if tokens else "NO_INTERRUPT_NAME_TOKEN",
        "hierarchy_roots": stmt.hierarchy_roots,
        "evidence": f"{stmt.file}:{stmt.line}",
    }


def classify_command_roles(statements, *,
                           declared_producer: str = "",
                           macro_definition_sources=None) -> dict:
    """SYS-7's COMMAND PRODUCER / CONSUMER / PARSER / DISPATCHER / TARGET
    VIP-SEQUENCE identification, each derived from the file's own evidence and
    each carrying an explicit UNRESOLVED state rather than a plausible guess.

    - DISPATCHER: the distinct macro names the file invokes. A command.txt's
      dispatch mechanism IS its macro layer; these names are the dispatch
      table, read off the calls themselves.
    - CONSUMER: the hierarchical roots those statements reach into, plus the
      HOST/DUT side each register macro drives (from the same
      `_classify_context()` the write-symmetry layer uses -- one HOST/DUT
      convention in this module, not two).
    - TARGET VIP-SEQUENCE: the model/VIP instance task calls (`INST.task`),
      which is the only thing in a command.txt that names a sequence-like
      entry point.
    - PARSER: whatever DEFINES the invoked macros. A command.txt does not
      contain its own parser, so this is UNRESOLVED unless the caller supplies
      the macro-definition sources to resolve against -- naming a guessed
      parser would be worse than saying it is unresolved.
    - PRODUCER: the caller's declared producer, else UNRESOLVED with the file
      itself cited. The file cannot say who wrote it.
    """
    dispatchers: dict = {}
    consumers: dict = {}
    target_sequences: dict = {}
    includes: list = []
    for stmt in statements:
        if stmt.kind in (K_REGISTER_WRITE, K_REGISTER_READ, K_MACRO_CALL):
            entry = dispatchers.setdefault(stmt.name, {
                "dispatcher": stmt.name, "kind": stmt.kind, "invocations": 0,
                "context": stmt.context or "OTHER",
                "first_evidence": f"{stmt.file}:{stmt.line}"})
            entry["invocations"] += 1
        elif stmt.kind == K_MODEL_TASK_CALL:
            entry = target_sequences.setdefault(stmt.name, {
                "target_sequence": stmt.name,
                # The instance name without the macro backtick: `SMEMMODEL is
                # macro syntax, SMEMMODEL is the model instance, and the
                # contract layer's MEMORY_MODEL:/MODEL: resource ids are built
                # from the latter -- one spelling, not two.
                "target_vip": stmt.name.split(".")[0].lstrip("`"),
                "invocations": 0,
                "first_evidence": f"{stmt.file}:{stmt.line}"})
            entry["invocations"] += 1
        elif stmt.kind == K_DIRECTIVE and stmt.name == "include":
            includes.append({"directive": stmt.text, "evidence": f"{stmt.file}:{stmt.line}"})
        for root in stmt.hierarchy_roots:
            c = consumers.setdefault(root, {"consumer": root, "references": 0,
                                            "first_evidence": f"{stmt.file}:{stmt.line}"})
            c["references"] += 1
        if stmt.context in ("HOST", "DUT"):
            c = consumers.setdefault(f"<{stmt.context}_SIDE_BFM>", {
                "consumer": f"<{stmt.context}_SIDE_BFM>", "references": 0,
                "first_evidence": f"{stmt.file}:{stmt.line}"})
            c["references"] += 1

    invoked_macros = sorted(set(dispatchers) | set(target_sequences))
    defined: dict = {}
    for source in (macro_definition_sources or []):
        try:
            text = Path(source).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in invoked_macros:
            bare = name.lstrip("`").split(".")[0]
            if re.search(rf"`define\s+{re.escape(bare)}\b", text):
                defined.setdefault(bare, []).append(str(source))
    unresolved = sorted({n.lstrip("`").split(".")[0] for n in invoked_macros} - set(defined))

    return {
        "producer": {
            "status": "DECLARED" if declared_producer else "UNRESOLVED",
            "value": declared_producer,
            "reason": "" if declared_producer else (
                "a command.txt does not record who authored it; supply "
                "declared_producer (e.g. command_inventory.csv's USER_SCOPE) "
                "to resolve"),
            "evidence": [s.file for s in statements[:1]] or [],
        },
        "parser": {
            "status": "RESOLVED" if defined and not unresolved else
                      ("PARTIAL" if defined else "UNRESOLVED"),
            "resolved_macros": {k: sorted(set(v)) for k, v in sorted(defined.items())},
            "unresolved_macros": unresolved,
            "includes": includes,
            "reason": ("" if defined and not unresolved else
                       "no macro-definition source resolves these macro names; the "
                       "parser of this command.txt is whatever defines them"),
        },
        "dispatchers": sorted(dispatchers.values(),
                              key=lambda d: (-d["invocations"], d["dispatcher"])),
        "consumers": sorted(consumers.values(),
                            key=lambda c: (-c["references"], c["consumer"])),
        "target_vip_sequences": sorted(target_sequences.values(),
                                       key=lambda t: (-t["invocations"], t["target_sequence"])),
    }


@dataclass
class OrderingEdge:
    """One SEMANTIC ordering/dependency edge between two statements. Implicit
    program order is never emitted -- every statement follows the one before
    it, so an edge saying so carries no information and would bury the edges
    that do."""
    relation: str
    from_line: int
    to_line: int
    from_command: str
    to_command: str
    detail: str
    evidence: str


ORDERING_RELATIONS: tuple = (
    "ADDRESS_READ_AFTER_WRITE",
    "ADDRESS_WRITE_AFTER_WRITE",
    "WAIT_GATED",
    "DELAY_GATED",
    "INITIALIZATION_PRECEDES",
    "FORCE_ACTIVE_DURING",
)


def build_ordering_constraints(statements) -> dict:
    """SYS-7's "dependencies, ordering, delays/waits" as a real edge set.

    Six relations, each mechanically derivable from the statement stream:
      ADDRESS_READ_AFTER_WRITE / ADDRESS_WRITE_AFTER_WRITE -- consecutive
        accesses to the SAME address literal (consecutive only; the transitive
        closure is implied and emitting it would square the edge count).
      WAIT_GATED / DELAY_GATED -- the access immediately before a wait/delay
        and the access immediately after it. This is the edge that actually
        matters for System-Level scheduling: two subsystems' commands may not
        be interleaved across one of these without changing what the wait
        observes.
      INITIALIZATION_PRECEDES -- an INITIALIZATION-category call and the first
        register access after it.
      FORCE_ACTIVE_DURING -- a force and its matching release; every statement
        in between executes under that override.
    """
    edges: list = []
    truncated = False

    def add(edge: OrderingEdge) -> None:
        nonlocal truncated
        if len(edges) >= MAX_ORDERING_EDGES:
            truncated = True
            return
        edges.append(edge)

    accesses = [s for s in statements if s.kind in (K_REGISTER_WRITE, K_REGISTER_READ)]
    by_address: dict = {}
    for stmt in accesses:
        if stmt.address:
            by_address.setdefault(stmt.address, []).append(stmt)
    for address, stmts in sorted(by_address.items()):
        for prev, nxt in zip(stmts, stmts[1:]):
            relation = ("ADDRESS_READ_AFTER_WRITE"
                        if nxt.kind == K_REGISTER_READ and prev.kind == K_REGISTER_WRITE
                        else "ADDRESS_WRITE_AFTER_WRITE")
            if prev.kind == K_REGISTER_READ:
                continue  # read-then-anything carries no ordering obligation
            add(OrderingEdge(
                relation=relation, from_line=prev.line, to_line=nxt.line,
                from_command=prev.name, to_command=nxt.name,
                detail=f"both access {address}",
                evidence=f"{prev.file}:{prev.line} -> {nxt.file}:{nxt.line}"))

    ordered = list(statements)
    for idx, stmt in enumerate(ordered):
        if stmt.kind in (K_WAIT_CONDITION, K_EVENT_WAIT, K_DELAY):
            relation = "DELAY_GATED" if stmt.kind == K_DELAY else "WAIT_GATED"
            before = next((s for s in reversed(ordered[:idx])
                           if s.kind in (K_REGISTER_WRITE, K_REGISTER_READ,
                                         K_MODEL_TASK_CALL, K_BACKDOOR_ASSIGN)), None)
            after = next((s for s in ordered[idx + 1:]
                          if s.kind in (K_REGISTER_WRITE, K_REGISTER_READ,
                                        K_MODEL_TASK_CALL, K_BACKDOOR_ASSIGN)), None)
            if before is not None and after is not None:
                add(OrderingEdge(
                    relation=relation, from_line=before.line, to_line=after.line,
                    from_command=before.name, to_command=after.name,
                    detail=f"separated by {stmt.text}",
                    evidence=f"{stmt.file}:{stmt.line}"))
        elif stmt.category == C_INITIALIZATION:
            after = next((s for s in ordered[idx + 1:]
                          if s.kind in (K_REGISTER_WRITE, K_REGISTER_READ)), None)
            if after is not None:
                add(OrderingEdge(
                    relation="INITIALIZATION_PRECEDES", from_line=stmt.line,
                    to_line=after.line, from_command=stmt.name, to_command=after.name,
                    detail="initialization call precedes the first register access after it",
                    evidence=f"{stmt.file}:{stmt.line}"))
        elif stmt.kind == K_FORCE:
            target = stmt.text.split("=")[0].replace("force", "", 1).strip()
            release = next((s for s in ordered[idx + 1:]
                            if s.kind == K_RELEASE and target and target in s.text), None)
            add(OrderingEdge(
                relation="FORCE_ACTIVE_DURING", from_line=stmt.line,
                to_line=release.line if release else ordered[-1].end_line,
                from_command=stmt.name,
                to_command=release.name if release else "<end-of-file>",
                detail=(f"{target} is forced over this span"
                        + ("" if release else "; no matching release found")),
                evidence=f"{stmt.file}:{stmt.line}"))

    edges.sort(key=lambda e: (e.from_line, e.to_line, e.relation))
    return {"edges": [asdict(e) for e in edges], "truncated": truncated,
            "relations_used": sorted({e.relation for e in edges})}


def analyze_command_file(path: Path, *,
                         declared_producer: str = "",
                         macro_definition_sources=None) -> dict:
    """SYS-7's full mandated analysis for ONE command.txt. Read-only.

    Every one of SYS-7's named aspects gets an explicit verdict, including the
    ones this file does not exercise: `loops_and_repetition`,
    `error_handling` and `expected_responses` report NOT_FOUND with the search
    that was performed, rather than being silently omitted. A missing aspect
    that is never mentioned is indistinguishable from an aspect nobody looked
    for.
    """
    path = Path(path)
    statements = extract_command_statements(path)
    by_kind: dict = {}
    for stmt in statements:
        by_kind.setdefault(stmt.kind, []).append(stmt)

    waits = [classify_wait(s) for s in statements
             if s.kind in (K_WAIT_CONDITION, K_EVENT_WAIT)]
    interrupt_waits = [w for w in waits if w["wait_class"] == "INTERRUPT_EVENT_WAIT"]
    delays = [{"line": s.line, "delay": s.text, "evidence": f"{s.file}:{s.line}"}
              for s in by_kind.get(K_DELAY, [])]
    resets = [{"line": s.line, "statement": s.text,
               "matched_tokens": _matched_tokens(s.text + " " + s.comment, RESET_NAME_TOKENS),
               "evidence": f"{s.file}:{s.line}"}
              for s in statements
              if s.kind in (K_REGISTER_WRITE, K_MODEL_TASK_CALL)
              and _matched_tokens(s.text + " " + s.comment, RESET_NAME_TOKENS)]
    dma = [{"line": s.line, "statement": s.text,
            "matched_tokens": _matched_tokens(s.text + " " + s.comment, DMA_NAME_TOKENS),
            "evidence": f"{s.file}:{s.line}"}
           for s in statements
           if _matched_tokens(s.text + " " + s.comment, DMA_NAME_TOKENS)]
    loops = [{"line": s.line, "construct": s.name, "statement": s.text,
              "evidence": f"{s.file}:{s.line}"} for s in by_kind.get(K_LOOP, [])]
    forks = [{"line": s.line, "construct": s.name, "evidence": f"{s.file}:{s.line}"}
             for s in by_kind.get(K_FORK, []) + by_kind.get(K_JOIN, [])]
    errors = [{"line": s.line, "statement": s.text, "evidence": f"{s.file}:{s.line}"}
              for s in by_kind.get(K_ERROR_REPORT, [])]
    conditionals = [{"line": s.line, "statement": s.text, "evidence": f"{s.file}:{s.line}"}
                    for s in by_kind.get(K_CONDITIONAL, [])]
    reads = by_kind.get(K_REGISTER_READ, [])
    termination = by_kind.get(K_TERMINATION, [])

    roles = classify_command_roles(
        statements, declared_producer=declared_producer,
        macro_definition_sources=macro_definition_sources)
    ordering = build_ordering_constraints(statements)

    def found(items, kind_label, searched):
        return {"status": "FOUND" if items else "NOT_FOUND", "count": len(items),
                kind_label: items, "searched_for": searched}

    return {
        "command_file": str(path),
        "file": path.name,
        "statement_count": len(statements),
        "statements_by_kind": {k: len(v) for k, v in sorted(by_kind.items())},
        "statements_by_category": {
            c: sum(1 for s in statements if s.category == c)
            for c in sorted({s.category for s in statements})},
        "statements": [asdict(s) for s in statements],
        "roles": roles,
        "ordering": ordering,
        # SYS-7's named aspects, each with an explicit verdict.
        "waits": found(waits, "waits", "wait(...) and @(...) statements"),
        "interrupt_waits": found(
            interrupt_waits, "interrupt_waits",
            f"wait conditions whose signal name contains one of {list(INTERRUPT_NAME_TOKENS)}"),
        "delays": found(delays, "delays", "#<delay> statements"),
        "reset_handling": found(
            resets, "reset_statements",
            f"register writes / model calls naming one of {list(RESET_NAME_TOKENS)}"),
        "dma_operations": found(
            dma, "dma_statements",
            f"statements naming one of {list(DMA_NAME_TOKENS)}"),
        "loops_and_repetition": found(
            loops, "loops", "repeat/while/for/forever constructs"),
        "concurrency": found(forks, "fork_join", "fork/join/join_any/join_none constructs"),
        "error_handling": found(
            errors + conditionals, "error_handling",
            "$error/$fatal/$warning calls and if/else conditionals"),
        "expected_responses": found(
            [{"line": s.line, "statement": s.text, "destination": (s.arguments or ["", ""])[-1],
              "evidence": f"{s.file}:{s.line}"} for s in reads],
            "register_reads",
            "register READ calls, whose destination variable is the only place this "
            "file states an expected response"),
        "termination": {
            "status": "EXPLICIT" if termination else "NOT_FOUND",
            "statements": [{"line": s.line, "statement": s.text,
                            "evidence": f"{s.file}:{s.line}"} for s in termination],
            "searched_for": "$finish / $stop",
        },
        "read_only": True,
    }


def analyze_command_files(paths) -> dict:
    """SYS-7 across every command.txt of ONE subsystem. Read-only."""
    analyses = [analyze_command_file(Path(p)) for p in paths]
    return {
        "command_files": [a["command_file"] for a in analyses],
        "analyses": analyses,
        "summary": {
            "files": len(analyses),
            "statements": sum(a["statement_count"] for a in analyses),
            "interrupt_waits": sum(a["interrupt_waits"]["count"] for a in analyses),
            "ordering_edges": sum(len(a["ordering"]["edges"]) for a in analyses),
        },
    }


def format_command_analysis(analysis: Mapping) -> str:
    """Human-readable rendering of one `analyze_command_file()` result."""
    lines = [f"command.txt analysis (SYS-7): {analysis['command_file']}",
             f"  statements: {analysis['statement_count']}",
             "  by category: " + ", ".join(
                 f"{k}={v}" for k, v in analysis["statements_by_category"].items())]
    roles = analysis["roles"]
    lines.append(f"  PRODUCER: {roles['producer']['status']} "
                 f"{roles['producer']['value'] or '-'}")
    lines.append(f"  PARSER:   {roles['parser']['status']} "
                 f"(unresolved macros: {roles['parser']['unresolved_macros']})")
    lines.append("  DISPATCHERS: " + ", ".join(
        f"{d['dispatcher']}x{d['invocations']}" for d in roles["dispatchers"][:8]) or "  DISPATCHERS: -")
    lines.append("  CONSUMERS:   " + ", ".join(
        c["consumer"] for c in roles["consumers"][:8]) or "  CONSUMERS: -")
    lines.append("  TARGET VIP SEQUENCES: " + (", ".join(
        t["target_sequence"] for t in roles["target_vip_sequences"]) or "-"))
    for aspect in ("waits", "interrupt_waits", "delays", "reset_handling",
                   "dma_operations", "loops_and_repetition", "concurrency",
                   "error_handling", "expected_responses"):
        block = analysis[aspect]
        lines.append(f"  {aspect}: {block['status']} ({block['count']})")
    lines.append(f"  termination: {analysis['termination']['status']}")
    lines.append(f"  ordering edges: {len(analysis['ordering']['edges'])} "
                 f"({', '.join(analysis['ordering']['relations_used']) or 'none'})"
                 + (" [TRUNCATED]" if analysis["ordering"]["truncated"] else ""))
    return "\n".join(lines)


# --- single entry point -------------------------------------------------------

def audit_directory(
    pattern_dir: Path,
    glob: str = "*.txt",
    min_shared_offsets: int = DEFAULT_MIN_SHARED_OFFSETS,
    min_jaccard: float = DEFAULT_MIN_JACCARD,
    question_store=None,
) -> dict:
    """Run the full audit against `pattern_dir`: extract every register
    write, discover host/DUT paired register blocks, and flag every
    per-file symmetry gap. Returns a JSON-serializable dict; never raises
    on a directory with zero matches (reports zero files instead).

    `question_store` (a `question_queue.QuestionQueueStore` or a project-root
    path): when supplied, every finding is ALSO escalated into the real
    question queue via `escalate_asymmetries()`, and the returned dict gains
    an `escalated_questions` list of Q-IDs. Before this existed, a finding
    terminated at report text -- the 2026-09-04 audit's confirmed gap ("the
    mismatch detectors exist and are real; the question-queue mechanism
    exists and is real; the wire between them does not"). It stays opt-in so
    `audit_directory()` remains a pure, side-effect-free read for the
    report-only callers that already exist.
    """
    pattern_dir = Path(pattern_dir)
    writes = extract_directory(pattern_dir, glob=glob)
    active = [w for w in writes if not w.commented_out]
    paired_blocks = discover_paired_blocks(writes, min_shared_offsets=min_shared_offsets, min_jaccard=min_jaccard)
    findings = find_symmetry_asymmetries(writes, paired_blocks)

    files_scanned = sorted({w.file for w in writes}) or sorted(p.name for p in Path(pattern_dir).glob(glob) if p.is_file())

    result = {
        "pattern_dir": str(pattern_dir),
        "glob": glob,
        "files_scanned": files_scanned,
        "total_writes_extracted": len(writes),
        "active_writes": len(active),
        "commented_out_writes": len(writes) - len(active),
        "paired_blocks": [asdict(pb) for pb in paired_blocks],
        "findings": [asdict(f) for f in findings],
        "summary": {
            "files_scanned_count": len(files_scanned),
            "paired_blocks_count": len(paired_blocks),
            "findings_count": len(findings),
            "verdict": "ASYMMETRY_FOUND" if findings else "CLEAN",
        },
    }

    if question_store is not None:
        escalated = escalate_asymmetries(result, question_store)
        result["escalated_questions"] = [r["id"] for r in escalated]
        result["summary"]["escalated_questions_count"] = len(escalated)

    return result


def format_report(result: dict) -> str:
    """Human-readable rendering of `audit_directory`'s result -- the same
    data as the JSON, for a terminal reader (matches this codebase's
    `explain`/`checklist` human-readable-alongside-JSON convention)."""
    lines = [
        f"Reference-pattern coverage audit: {result['pattern_dir']}",
        f"  files scanned: {result['summary']['files_scanned_count']}",
        f"  register writes extracted: {result['total_writes_extracted']} "
        f"({result['active_writes']} active, {result['commented_out_writes']} commented-out)",
        f"  host/DUT paired register blocks discovered: {result['summary']['paired_blocks_count']}",
    ]
    for pb in result["paired_blocks"]:
        lines.append(
            f"    HOST base {pb['host_base']} <-> DUT base {pb['dut_base']} "
            f"(jaccard={pb['jaccard']}, shared_offsets={pb['shared_offsets']})"
        )
    lines.append("")
    if not result["findings"]:
        lines.append("VERDICT: CLEAN -- no host/DUT write asymmetry found.")
        return "\n".join(lines)
    lines.append(f"VERDICT: ASYMMETRY_FOUND -- {result['summary']['findings_count']} finding(s):")
    for f in result["findings"]:
        lines.append(
            f"  [{f['file']}] offset {f['offset']} written {f['written_side']}-side "
            f"(base {f['host_base'] if f['written_side'] == 'HOST' else f['dut_base']}) "
            f"but NEVER {f['missing_side']}-side (base "
            f"{f['dut_base'] if f['missing_side'] == 'DUT' else f['host_base']}) in this file -- "
            f"citation: {f['example_macro']}({f['example_address']}) at line {f['example_line']}"
            + (f" // {f['field_hint']}" if f['field_hint'] else "")
        )
    if "escalated_questions" in result:
        lines.append("")
        lines.append(f"Escalated to the question queue ({len(result['escalated_questions'])} "
                     f"Tier-3 entries, each carrying both sides' evidence paths): "
                     + ", ".join(result["escalated_questions"]))
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pattern_dir", help="Directory of reference BFM pattern files (*.txt).")
    ap.add_argument("--glob", default="*.txt")
    ap.add_argument("--json", action="store_true", help="Print raw JSON instead of the human-readable report.")
    ap.add_argument("--commands", action="store_true",
                    help="Run the SYS-7 command.txt grammar/ordering/dependency analysis "
                         "over every matching file instead of the host/DUT write-symmetry "
                         "audit. Read-only; never modifies a command.txt.")
    args = ap.parse_args(argv)
    if args.commands:
        paths = sorted(p for p in Path(args.pattern_dir).glob(args.glob) if p.is_file())
        result = analyze_command_files(paths)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for analysis in result["analyses"]:
                print(format_command_analysis(analysis))
                print()
        return 0
    result = audit_directory(Path(args.pattern_dir), glob=args.glob)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 0 if result["summary"]["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
