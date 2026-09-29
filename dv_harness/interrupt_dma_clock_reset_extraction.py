"""dv_harness/interrupt_dma_clock_reset_extraction.py -- interrupt
architecture, DMA architecture, and a clock/reset FACT EXTENSION, all read
from whatever real spec/programming-guide/RTL text a caller actually
supplies.

THE SHAPE THIS STAYS COMPATIBLE WITH. `env_manifest.build_dut_facts_clock_reset()`
already produces `dut_facts.clock_reset` as
`{"status", "source", "reason", "clocks": [...], "resets": [...]}`, with each
reset carrying `name` / `active_level` / `synchronous` / `clock` /
`clock_resolved` / `evidence` / `description` -- and `active_level` is
REQUIRED there, never defaulted (see env_manifest.py's own "dut_facts.
address_map / dut_facts.clock_reset" section and CLAUDE.md's "env.manifest.json
Fact Sources" entry). That module's own input is `soc_arch_map.schema.json`,
a documented, human-authored input contract -- deliberately an INPUT CONTRACT
and not an extractor, per that module's own docstring, because "dv_harness is
the meta-harness and owns no SoC, so there is nothing here to extract FROM".

This module is the extractor that input contract's docstring says does not
belong there: it reads REAL RTL and REAL spec/programming-guide TEXT a caller
supplies (never a schema a human already distilled) and produces reset/clock
entries in the SAME field shape, so a caller can merge or cross-check the two
without translating field names. It is a sibling producer, not a rewrite --
nothing here imports or edits env_manifest.py, and nothing here decides which
of the two sources wins on a disagreement (that is Source Authority Order's
job, `dv_harness/source_authority.py`, untouched here).

WHY A LINE-SCAN, MIRRORING `vip_symbol_index.py` RATHER THAN `verible_parser.py`.
`verible_parser.py` is this repo's real SystemVerilog parser and is the right
tool wherever module/port facts are already used (env_manifest.py,
phy_boundary.py, uvm_structural_lint.py) -- but it requires a real verible
binary, and a spec/programming-guide document is not SystemVerilog at all, so
a parser-only approach could never read the prose half of this task
("priority/masking scheme if stated" almost never appears in the RTL). This
module instead does DECLARATION-LEVEL LINE SCANNING over whatever text a
caller supplies -- RTL port lists, `always_ff` sensitivity lists, `typedef
struct packed` bodies, and plain prose sentences -- exactly
`vip_symbol_index.py`'s own graceful-degradation discipline: a construct or
sentence this scan does not recognise contributes NOTHING, never a guessed
fact. Every one of the eight facets below (interrupt sources, priority scheme,
masking scheme, DMA channel count, DMA descriptor model, and the three
clock/reset facts) is independently NOT_AVAILABLE with a real, specific reason
when the supplied text does not state it -- never a shared "no data" verdict a
reader would have to guess the cause of, and never an inferred priority order,
channel count or descriptor layout that is not literally written down (the
"honest NOT_AVAILABLE per-facet" requirement this module exists to satisfy).

WHAT IS DELIBERATELY NOT ATTEMPTED. This is a regex line-scan, not a
compiler: preprocessor conditionals (`` `ifdef ``) are not evaluated,
multi-line macro expansions are not resolved, and a construct spanning an
unusual continuation this scan's patterns do not anticipate contributes no
citation rather than a wrong one. Priority/masking extraction is bounded to
EXPLICIT statement forms (an ordering chain, a "has the highest/lowest
priority" sentence, an explicit mask-register/enable-bit sentence) -- it never
infers a fixed-priority or round-robin scheme from register field names or
from the mere presence of an "IRQ" list, because that would be exactly the
kind of unwritten architectural claim CLAUDE.md's No Golden-Reference Content
Mining and Evidence Truth Rule forbid. Reset synchronicity/active-level is
decided ONLY from the two RTL shapes an `always_ff` sensitivity list and its
immediate first `if` can prove (async: reset edge present in the sensitivity
list itself; sync: no reset edge in the sensitivity list, but the very next
conditional inside the block tests a reset-named signal) -- an ambiguous or
unrecognised reset idiom is skipped, never guessed at either polarity.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0"

RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")
TEXT_SUFFIXES = (".txt", ".md", ".rst", ".pgv", ".spec")

# How many lines after an `always`/`always_ff` header this module will look
# for the block's first `if` before giving up on a synchronous-reset read --
# bounded so a scan can never wander into an unrelated later block and
# misattribute its condition to this always block's reset.
_SYNC_RESET_LOOKAHEAD_LINES = 6

# ---------------------------------------------------------------------------
# Interrupt sources -- RTL port declarations whose NAME matches an interrupt
# naming convention. This records the NAME the RTL actually declares; it makes
# no claim about polarity, priority or masking, which are separate facets
# below and independently gated on their own explicit evidence.
# ---------------------------------------------------------------------------
_PORT_LINE_RE = re.compile(
    r"^\s*(?P<dir>input|output|inout)\s+"
    r"(?:wire\s+|reg\s+|logic\s+)?(?:signed\s+)?"
    r"(?:\[(?P<width>[^\]]+)\]\s*)?"
    r"(?P<name>[A-Za-z_]\w*)\s*[,;)]"
    r"(?:\s*//\s*(?P<comment>.*))?"
)
_IRQ_NAME_RE = re.compile(r"(?:^|_)(irq|intr|interrupt)(?:_|$)", re.IGNORECASE)
_RESET_NAME_RE = re.compile(r"(?:^|_)(rst|reset)(?:_|$)", re.IGNORECASE)


def _scan_interrupt_sources(lines: list, path: str) -> list:
    found = []
    for lineno, line in enumerate(lines, start=1):
        m = _PORT_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if not _IRQ_NAME_RE.search(name):
            continue
        found.append({
            "name": name,
            "direction": m.group("dir").lower(),
            "width": m.group("width"),
            "description": (m.group("comment") or "").strip() or None,
            "evidence": f"{path}:{lineno}",
        })
    return found


# ---------------------------------------------------------------------------
# Priority / masking scheme -- EXPLICIT prose statements only.
# ---------------------------------------------------------------------------
_PRIORITY_ORDER_RE = re.compile(
    r"priorit\w*[^\n>]*?"
    r"(?P<chain>[A-Za-z_]\w*(?:\s*>\s*[A-Za-z_]\w*)+)",
    re.IGNORECASE,
)
_PRIORITY_EXTREME_RE = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\s+has\s+(?:the\s+)?(?P<extreme>highest|lowest)\s+priority",
    re.IGNORECASE,
)


def _scan_priority_statements(lines: list, path: str) -> list:
    statements = []
    for lineno, line in enumerate(lines, start=1):
        m = _PRIORITY_ORDER_RE.search(line)
        if m:
            order = [tok.strip() for tok in m.group("chain").split(">")]
            statements.append({
                "type": "ORDERED_CHAIN",
                "order": order,
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            })
            continue
        m = _PRIORITY_EXTREME_RE.search(line)
        if m:
            statements.append({
                "type": m.group("extreme").upper(),
                "source": m.group("name"),
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            })
    return statements


_MASK_SENTENCE_RE = re.compile(
    r"\b(mask\w*|IMR|interrupt\s+enable\s+register|enable\s*/\s*disable)\b.*"
    r"\b(interrupt\w*|irq\w*|intr\w*)\b"
    r"|\b(interrupt\w*|irq\w*|intr\w*)\b.*"
    r"\b(mask\w*|IMR|interrupt\s+enable\s+register)\b",
    re.IGNORECASE,
)


def _scan_masking_statements(lines: list, path: str) -> list:
    statements = []
    for lineno, line in enumerate(lines, start=1):
        if _MASK_SENTENCE_RE.search(line):
            statements.append({
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            })
    return statements


# ---------------------------------------------------------------------------
# DMA channel count -- an RTL parameter naming the channel count, or an
# explicit "<N> DMA channels" prose sentence. Never a value counted from an
# unrelated enumeration (e.g. counting matched descriptor structs), because
# that would be reporting a fact this scan estimated, not one that is stated.
# ---------------------------------------------------------------------------
_DMA_CHAN_PARAM_RE = re.compile(
    r"parameter\s+(?:int\s+|integer\s+|logic(?:\s*\[[^\]]*\])?\s+)?"
    r"(?P<pname>\w*(?:NUM_DMA_CHAN\w*|DMA_NUM_CHAN\w*|DMA_CHANNELS?|NUM_CHANNELS)\w*)"
    r"\s*=\s*(?P<value>\d+)",
    re.IGNORECASE,
)
_DMA_CHAN_TEXT_RE = re.compile(
    r"(?P<value>\d+)\s+(?:independent\s+|separate\s+)?DMA\s+channels?",
    re.IGNORECASE,
)


def _scan_dma_channel_count(lines: list, path: str) -> Optional[dict]:
    for lineno, line in enumerate(lines, start=1):
        m = _DMA_CHAN_PARAM_RE.search(line)
        if m:
            return {
                "value": int(m.group("value")),
                "declared_as": m.group("pname"),
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            }
    for lineno, line in enumerate(lines, start=1):
        m = _DMA_CHAN_TEXT_RE.search(line)
        if m:
            return {
                "value": int(m.group("value")),
                "declared_as": None,
                "text": line.strip(),
                "evidence": f"{path}:{lineno}",
            }
    return None


# ---------------------------------------------------------------------------
# DMA descriptor model -- a `typedef struct packed { ... } <name>;` whose
# closing name names a descriptor (contains "desc"). Fields are read directly
# off the struct body; a member line this pattern does not recognise (a
# nested struct, a union, a macro) is skipped rather than guessed.
# ---------------------------------------------------------------------------
_STRUCT_START_RE = re.compile(r"typedef\s+struct\s+packed\s*\{", re.IGNORECASE)
_STRUCT_END_RE = re.compile(r"^\s*\}\s*(?P<name>[A-Za-z_]\w*)\s*;")
_STRUCT_FIELD_RE = re.compile(
    r"^\s*(?P<dtype>logic|bit|reg)\s*(?:\[(?P<width>[^\]]+)\])?\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*;"
)
_DESC_NAME_RE = re.compile(r"desc", re.IGNORECASE)


def _scan_dma_descriptor_model(lines: list, path: str) -> Optional[dict]:
    i = 0
    n = len(lines)
    while i < n:
        if _STRUCT_START_RE.search(lines[i]):
            start_line = i + 1
            fields = []
            j = i + 1
            end_name = None
            end_line = None
            while j < n:
                end_m = _STRUCT_END_RE.match(lines[j])
                if end_m:
                    end_name = end_m.group("name")
                    end_line = j + 1
                    break
                field_m = _STRUCT_FIELD_RE.match(lines[j])
                if field_m:
                    fields.append({
                        "name": field_m.group("name"),
                        "dtype": field_m.group("dtype"),
                        "width": field_m.group("width"),
                    })
                j += 1
            if end_name and _DESC_NAME_RE.search(end_name):
                return {
                    "struct_name": end_name,
                    "fields": fields,
                    "evidence": f"{path}:{start_line}-{end_line}",
                }
            i = j if end_line else i + 1
            continue
        i += 1
    return None


# ---------------------------------------------------------------------------
# Clock/reset extension -- read from `always`/`always_ff` sensitivity lists
# and, for a synchronous idiom, the block's own first `if`.
# ---------------------------------------------------------------------------
_ALWAYS_RE = re.compile(r"always(?:_ff)?\s*@\s*\(([^)]*)\)", re.IGNORECASE)
_EDGE_TOKEN_RE = re.compile(r"(posedge|negedge)\s+([A-Za-z_]\w*)", re.IGNORECASE)
_SYNC_RESET_IF_RE = re.compile(
    r"if\s*\(\s*(?P<neg>!\s*)?(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:==\s*1'b[01]\s*)?\)"
)


def _scan_clock_reset(lines: list, path: str) -> dict:
    clocks = {}   # name -> evidence (first sighting)
    resets = {}   # name -> reset dict (first sighting wins)
    n = len(lines)
    for idx, line in enumerate(lines):
        m = _ALWAYS_RE.search(line)
        if not m:
            continue
        header_lineno = idx + 1
        sens = m.group(1)
        edges = _EDGE_TOKEN_RE.findall(sens)
        clock_names = [name for edge, name in edges
                       if edge.lower() == "posedge" and not _RESET_NAME_RE.search(name)]
        reset_edges = [(edge, name) for edge, name in edges if _RESET_NAME_RE.search(name)]
        clock_name = clock_names[0] if clock_names else None
        if clock_name and clock_name not in clocks:
            clocks[clock_name] = f"{path}:{header_lineno}"

        if reset_edges:
            edge, rname = reset_edges[0]
            if rname not in resets:
                resets[rname] = {
                    "name": rname,
                    "active_level": "LOW" if edge.lower() == "negedge" else "HIGH",
                    "synchronous": False,
                    "clock": clock_name,
                    "evidence": f"{path}:{header_lineno}",
                    "description": f"asynchronous reset in sensitivity list of always block "
                                    f"at {path}:{header_lineno}",
                }
            continue

        if clock_name is None:
            continue
        # No reset edge in the sensitivity list -- look at the block's own
        # first `if` for a synchronous-reset idiom, bounded so this can never
        # misattribute a later, unrelated block's condition.
        for look in range(idx + 1, min(idx + 1 + _SYNC_RESET_LOOKAHEAD_LINES, n)):
            body_line = lines[look]
            if not body_line.strip():
                continue
            if_m = _SYNC_RESET_IF_RE.search(body_line)
            if if_m and _RESET_NAME_RE.search(if_m.group("name")):
                rname = if_m.group("name")
                if rname not in resets:
                    active_level = "LOW" if if_m.group("neg") else "HIGH"
                    resets[rname] = {
                        "name": rname,
                        "active_level": active_level,
                        "synchronous": True,
                        "clock": clock_name,
                        "evidence": f"{path}:{look + 1}",
                        "description": f"synchronous reset tested in first `if` of always "
                                        f"block at {path}:{header_lineno}",
                    }
            break  # only the block's own FIRST real statement is examined

    clocks_list = [{"name": name, "evidence": ev, "description": None}
                   for name, ev in sorted(clocks.items())]
    resets_list = sorted(resets.values(), key=lambda r: r["name"])
    return {"clocks": clocks_list, "resets": resets_list}


def _resolve_reset_clocks(resets: list, clock_names: set) -> list:
    """Mirrors `env_manifest.build_dut_facts_clock_reset()`'s own
    RESOLVED/UNKNOWN_CLOCK/NOT_SPECIFIED reasoning, so a reader checking one
    reset's `clock_resolved` never has to learn a second vocabulary for it --
    this module has a different SOURCE (RTL text, not soc_arch_map.json), so
    the computation is independently re-derived here rather than imported."""
    out = []
    for r in resets:
        r = dict(r)
        clock = r.get("clock")
        if clock is None:
            r["clock_resolved"] = "NOT_SPECIFIED"
        elif clock in clock_names:
            r["clock_resolved"] = "RESOLVED"
        else:
            r["clock_resolved"] = "UNKNOWN_CLOCK"
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------
def classify_source(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in RTL_SUFFIXES:
        return "rtl"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "unknown"


def extract_interrupt_dma_clock_reset(source_paths) -> dict:
    """Extract interrupt architecture, DMA architecture, and a clock/reset
    fact extension from real RTL and/or spec/programming-guide TEXT files a
    caller supplies. `source_paths` is a list of str/Path; every file is read
    (never fabricated), and a missing/unreadable file is recorded as an
    honest per-source failure rather than silently skipped or raised past the
    caller. Every facet below carries its OWN status/reason -- absence of one
    fact never masks the presence of another."""
    source_paths = list(source_paths or [])
    read_sources = []
    missing_sources = []
    unrecognized_sources = []

    interrupt_sources = []
    priority_statements = []
    masking_statements = []
    dma_channel_count = None
    dma_descriptor_model = None
    clocks_by_name = {}
    resets_by_name = {}

    for raw_path in source_paths:
        p = Path(raw_path)
        if not p.is_file():
            missing_sources.append(str(raw_path))
            continue
        kind = classify_source(p)
        if kind == "unknown":
            unrecognized_sources.append(str(raw_path))
            # An unrecognised extension is still read: a supplied file with
            # no suffix (or an unlisted one) may still be real prose or RTL
            # text, and refusing to scan it would silently under-report.
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            missing_sources.append(f"{raw_path} ({exc})")
            continue
        lines = text.splitlines()
        path_str = str(raw_path)
        read_sources.append(path_str)

        interrupt_sources.extend(_scan_interrupt_sources(lines, path_str))
        priority_statements.extend(_scan_priority_statements(lines, path_str))
        masking_statements.extend(_scan_masking_statements(lines, path_str))
        if dma_channel_count is None:
            dma_channel_count = _scan_dma_channel_count(lines, path_str)
        if dma_descriptor_model is None:
            dma_descriptor_model = _scan_dma_descriptor_model(lines, path_str)

        cr = _scan_clock_reset(lines, path_str)
        for c in cr["clocks"]:
            clocks_by_name.setdefault(c["name"], c)
        for r in cr["resets"]:
            resets_by_name.setdefault(r["name"], r)

    clocks_list = sorted(clocks_by_name.values(), key=lambda c: c["name"])
    resets_list = _resolve_reset_clocks(
        sorted(resets_by_name.values(), key=lambda r: r["name"]),
        set(clocks_by_name.keys()),
    )

    # --- interrupt architecture ---
    if interrupt_sources:
        sources_status, sources_reason = "LOADED", None
    else:
        sources_status = "NOT_AVAILABLE"
        sources_reason = ("no port declaration in the supplied sources matches an interrupt "
                           "naming convention (irq/intr/interrupt) -- nothing was found to list, "
                           "and none is assumed")
    if priority_statements:
        priority_status, priority_reason = "LOADED", None
    else:
        priority_status = "NOT_AVAILABLE"
        priority_reason = ("no explicit priority statement (an ordered chain, or an explicit "
                            "'X has the highest/lowest priority' sentence) was found in the "
                            "supplied sources -- a priority scheme is never inferred from the "
                            "interrupt source list alone")
    if masking_statements:
        masking_status, masking_reason = "LOADED", None
    else:
        masking_status = "NOT_AVAILABLE"
        masking_reason = ("no explicit masking/enable statement was found in the supplied "
                           "sources -- a masking scheme is never inferred from a register's "
                           "name alone")

    interrupt_architecture = {
        "status": "LOADED" if sources_status == "LOADED" else "NOT_AVAILABLE",
        "reason": None if sources_status == "LOADED" else sources_reason,
        "sources": interrupt_sources,
        "priority_scheme": {
            "status": priority_status,
            "reason": priority_reason,
            "statements": priority_statements,
        },
        "masking_scheme": {
            "status": masking_status,
            "reason": masking_reason,
            "statements": masking_statements,
        },
    }

    # --- DMA architecture ---
    if dma_channel_count is not None:
        channel_count_block = {"status": "LOADED", "reason": None, **dma_channel_count}
    else:
        channel_count_block = {
            "status": "NOT_AVAILABLE",
            "reason": ("no DMA channel count was found -- neither an RTL parameter named for a "
                       "channel count (e.g. NUM_DMA_CHANNELS) nor an explicit '<N> DMA channels' "
                       "sentence appears in the supplied sources"),
            "value": None, "declared_as": None, "text": None, "evidence": None,
        }
    if dma_descriptor_model is not None:
        descriptor_block = {"status": "LOADED", "reason": None, **dma_descriptor_model}
    else:
        descriptor_block = {
            "status": "NOT_AVAILABLE",
            "reason": ("no `typedef struct packed {...} <name>;` whose closing name names a "
                       "descriptor (contains 'desc') was found in the supplied sources"),
            "struct_name": None, "fields": [], "evidence": None,
        }
    dma_architecture = {
        "status": "LOADED" if (dma_channel_count is not None or dma_descriptor_model is not None)
                   else "NOT_AVAILABLE",
        "reason": None if (dma_channel_count is not None or dma_descriptor_model is not None)
                  else "neither a DMA channel count nor a DMA descriptor model was found in the "
                       "supplied sources",
        "channel_count": channel_count_block,
        "descriptor_model": descriptor_block,
    }

    # --- clock/reset extension ---
    if clocks_list or resets_list:
        cr_status, cr_reason = "LOADED", None
    else:
        cr_status = "NOT_AVAILABLE"
        cr_reason = ("no `always`/`always_ff` block with a recognisable clock/reset sensitivity "
                     "or first-statement reset idiom was found in the supplied sources")
    clock_reset_extension = {
        "status": cr_status,
        "reason": cr_reason,
        "clocks": clocks_list,
        "resets": resets_list,
    }

    facets_loaded = any(block["status"] == "LOADED" for block in
                         (interrupt_architecture, dma_architecture, clock_reset_extension))
    if not source_paths:
        top_status, top_reason = "NOT_AVAILABLE", "no source files were supplied"
    elif not read_sources:
        top_status = "NOT_AVAILABLE"
        top_reason = f"none of the {len(source_paths)} supplied source path(s) could be read: " \
                     f"{missing_sources}"
    elif facets_loaded:
        top_status, top_reason = "LOADED", None
    else:
        top_status = "NOT_AVAILABLE"
        top_reason = ("supplied sources were read but none of interrupt architecture, DMA "
                      "architecture, or clock/reset facts could be extracted from them")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": top_status,
        "source": {
            "kind": "interrupt_dma_clock_reset_source_text",
            "paths": read_sources,
            "missing": missing_sources,
            "unrecognized": unrecognized_sources,
        },
        "reason": top_reason,
        "interrupt_architecture": interrupt_architecture,
        "dma_architecture": dma_architecture,
        "clock_reset_extension": clock_reset_extension,
    }


# ---------------------------------------------------------------------------
# CLI front door -- same shared `execute_verb()` convention as
# `power-intent`/`golden-scenario`/`config-variants`. Not wired into cli.py
# (this task's file-safety scope forbids editing it); the integrator may add
# a `dv-harness interrupt-dma-clock-reset --sources <f> [<f> ...] [--json]`
# verb calling `execute_verb(argv)` below.
# ---------------------------------------------------------------------------
def execute_verb(argv: list) -> int:
    import json as _json
    import sys as _sys

    if not argv or argv[0] not in ("extract",):
        print("usage: interrupt_dma_clock_reset_extraction extract --sources <f> [<f> ...] [--json]",
              file=_sys.stderr)
        return 2
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if "--sources" in args:
        idx = args.index("--sources")
        sources = args[idx + 1:]
    else:
        sources = args
    report = extract_interrupt_dma_clock_reset(sources)
    if as_json:
        print(_json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}" + (f" ({report['reason']})" if report["reason"] else ""))
        ia = report["interrupt_architecture"]
        print(f"  interrupt sources: {ia['status']} ({len(ia['sources'])} found)")
        print(f"  priority scheme:   {ia['priority_scheme']['status']}")
        print(f"  masking scheme:    {ia['masking_scheme']['status']}")
        da = report["dma_architecture"]
        print(f"  dma channel count: {da['channel_count']['status']}")
        print(f"  dma descriptor:    {da['descriptor_model']['status']}")
        cr = report["clock_reset_extension"]
        print(f"  clock/reset:       {cr['status']} "
              f"({len(cr['clocks'])} clocks, {len(cr['resets'])} resets)")
    return 0 if report["status"] == "LOADED" else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
