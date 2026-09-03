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
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# --- extraction --------------------------------------------------------------

# Generic on PREFIX (any run of [A-Z][A-Z0-9]* before WRITE/READ<N>B) so a
# not-yet-seen macro name is still extracted, never silently dropped -- this
# tool does not hardcode a fixed macro allowlist beyond the WRITE/READ<N>B
# suffix shape confirmed in the real files.
_MACRO_CALL_RE = re.compile(
    r"`(?P<macro>(?P<prefix>[A-Z][A-Z0-9]*)(?P<verb>WRITE|READ)(?P<width>[0-9]+)B)"
    r"\s*\(\s*(?P<addr>[0-9]+'h[0-9A-Fa-f_]+)\s*,\s*(?P<value>[0-9]+'h[0-9A-Fa-f_]+)\s*\)\s*;"
    r"[ \t]*(?://\s*(?P<comment>.*))?"
)

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


# --- single entry point -------------------------------------------------------

def audit_directory(
    pattern_dir: Path,
    glob: str = "*.txt",
    min_shared_offsets: int = DEFAULT_MIN_SHARED_OFFSETS,
    min_jaccard: float = DEFAULT_MIN_JACCARD,
) -> dict:
    """Run the full audit against `pattern_dir`: extract every register
    write, discover host/DUT paired register blocks, and flag every
    per-file symmetry gap. Returns a JSON-serializable dict; never raises
    on a directory with zero matches (reports zero files instead).
    """
    pattern_dir = Path(pattern_dir)
    writes = extract_directory(pattern_dir, glob=glob)
    active = [w for w in writes if not w.commented_out]
    paired_blocks = discover_paired_blocks(writes, min_shared_offsets=min_shared_offsets, min_jaccard=min_jaccard)
    findings = find_symmetry_asymmetries(writes, paired_blocks)

    files_scanned = sorted({w.file for w in writes}) or sorted(p.name for p in Path(pattern_dir).glob(glob) if p.is_file())

    return {
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
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pattern_dir", help="Directory of reference BFM pattern files (*.txt).")
    ap.add_argument("--glob", default="*.txt")
    ap.add_argument("--json", action="store_true", help="Print raw JSON instead of the human-readable report.")
    args = ap.parse_args(argv)
    result = audit_directory(Path(args.pattern_dir), glob=args.glob)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 0 if result["summary"]["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
