"""dv_harness/register_rtl_trace.py -- attempts to trace a register field's
DECLARED behavior (its name, and optionally a document-stated expected RTL
signal name) to a real RTL signal / control-logic reference, using
`dv_harness/verible_parser.py`'s existing declaration-level parse -- import
only, read-only, no second SystemVerilog parser in this package.

WHAT WAS ACTUALLY MISSING (re-verified by grep before this module was
written): a repo-wide search for `register_rtl_trace`/`RegisterRtlTrace`/
`TRACE_CONFIRMED`/`TRACE_PARTIAL` matched nothing executable. A register
field's declared control/status meaning (`register_map.schema.json`'s own
`fields[].name`/`description`) had no code path connecting it to the RTL a
generated environment actually binds against -- the closest neighbours,
`sys_regmap.py` (mode-determining CONTROL BITS -> a Gate-2 precondition) and
`connectivity.py` (bind-location/tier confidence for a whole INTERFACE), both
operate one level away: neither asks "does the RTL this project parsed even
contain a signal this specific register field's name plausibly refers to".

THE PARSER-VS-ELABORATION BOUNDARY, stated up front because it drives every
status this module can report (the same discipline
`dv_harness/uvm_structural_lint.py` already applies to its own declaration
-level limits, applied here to registers instead of UVM classes):

  `verible_parser.py` parses SOURCE TEXT into a syntax tree. It never
  elaborates: it does not resolve a `generate`/`ifdef` condition, does not
  evaluate a parameter, does not simulate a single clock edge, and does not
  know what value any signal ever actually carries. So the STRONGEST claim
  this module can ever make is "a signal (or port) with this name exists in
  the parsed sources, and it is wired to something (not just an unused local
  declaration)". That proves the NAME is real and REFERENCED. It NEVER proves
  that this signal is the field's control/status logic at run time, that the
  field's declared semantics match what the RTL actually does with the
  signal, or that the wiring is even reachable under the design's real
  configuration. TRACE_CONFIRMED is this module's ceiling, not a claim of
  verified behavior -- and it is worded that way in every TRACE_CONFIRMED
  result's own `reason` text, not only here.

FOUR STATUSES, and the rule that keeps them honest:

  TRACE_CONFIRMED   exactly one RTL site (port or signal) matches the
                    searched name EXACTLY (case/underscore-normalized), and
                    that site is REFERENCED elsewhere in the parsed sources
                    (a port -- inherently a real external connection point --
                    or an internal signal that appears in a continuous
                    assign's or an instance connection's own net list).
                    Unambiguous existence + reference. Nothing stronger.
  TRACE_PARTIAL     a plausible reference exists but is AMBIGUOUS: more than
                    one exact-name site (which module's signal is the real
                    one?), an exact-name site that is only a bare, unused
                    declaration (no evidence it is wired to anything), or
                    only a SUBSTRING/fuzzy name match (no exact name found).
                    Never silently upgraded to TRACE_CONFIRMED, no matter how
                    plausible the fuzzy match looks -- this is the module's
                    one hard rule.
  TRACE_NOT_FOUND   a real search was performed over real parsed RTL and no
                    matching site, exact or fuzzy, was found anywhere.
  BLOCKED           the trace could not be ATTEMPTED at all: no field name to
                    search for, no parsed RTL supplied, or verible itself
                    could not produce a parse for every supplied source
                    (VeribleUnavailableError / VeribleParseError). Distinct
                    from TRACE_NOT_FOUND on purpose -- "we never looked" must
                    never be reported as "we looked and found nothing" (the
                    Evidence Truth Rule's honest-distinct-status requirement).

INPUT SHAPE, deliberately duck-typed and independent of any other
concurrently-developed module (per this batch's file-safety scope: this file
imports only `dv_harness.verible_parser`, the module the task names directly,
and `dv_harness.env_manifest` for its existing `load_register_map()` /
`RegisterMapValidationError` -- an established module outside this batch and
outside the separately-running batch this task must not depend on).
Register fields may be handed in as plain dicts (the shape
`register_map.schema.json`'s own `fields[]` entries already have, optionally
carrying `register_name`/`block_name` context and an extra, non-schema
`rtl_signal_hint` key for a document-stated expected RTL signal name) or as
`RegisterFieldRef` instances built from one. The RTL corpus this module
searches is a plain list, accepting -- interchangeably, and duck-typed rather
than isinstance-checked -- `verible_parser.FileParseResult` objects,
`verible_parser.to_dict()`'s own per-file dict shape, or a bare list of
`verible_parser.ModuleInfo` objects / their `to_dict()`-shaped module dicts.
`parse_rtl_sources()` is the convenience path that runs the real
`verible_parser.parse_file()` over real source paths for a caller that has
not already parsed anything.

This module decides nothing beyond reporting a trace status: no build, no
job, no approval, no memory write, and there is deliberately no stage gate --
a gate that passed on a trace this module itself says is ambiguous would be
worse than none.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import verible_parser
from .verible_parser import DEFAULT_VERIBLE_BIN, VeribleParseError, VeribleUnavailableError

# --- status vocabulary -------------------------------------------------------

TRACE_CONFIRMED = "TRACE_CONFIRMED"
TRACE_PARTIAL = "TRACE_PARTIAL"
TRACE_NOT_FOUND = "TRACE_NOT_FOUND"
TRACE_BLOCKED = "BLOCKED"

TRACE_STATUSES = (TRACE_CONFIRMED, TRACE_PARTIAL, TRACE_NOT_FOUND, TRACE_BLOCKED)

# A substring/fuzzy match shorter than this is too common across real RTL
# naming (e.g. "en", "rst", "clk" as bare substrings of dozens of unrelated
# signals) to carry any real evidentiary weight, in either direction.
MIN_FUZZY_MATCH_LEN = 4

# CLI/report exit-code mapping, same convention `vip_api_card.py` uses for
# its own four-status vocabulary: 0 best, 1 a real hard finding
# (NOT_FOUND -- a search that came up empty), 2 could-not-check (BLOCKED),
# 3 a non-fatal, disclosed ambiguity (PARTIAL) unless a caller opts into
# strict handling.
STATUS_EXIT_CODE = {
    TRACE_CONFIRMED: 0,
    TRACE_NOT_FOUND: 1,
    TRACE_BLOCKED: 2,
    TRACE_PARTIAL: 3,
}
# Worst-first order used to fold many per-field results into one exit code.
_EXIT_PRIORITY = (TRACE_NOT_FOUND, TRACE_BLOCKED, TRACE_PARTIAL, TRACE_CONFIRMED)


def normalize_signal_name(name: Optional[str]) -> str:
    """Case/underscore/punctuation-insensitive canonical form used for every
    name comparison in this module (e.g. `phy_reset_n`, `PHY_RESET_N` and
    `PhyResetN` all normalize to `physresetn`). Deliberately loose: RTL naming
    convention varies by author, and the alternative -- exact string equality
    -- would silently turn every stylistic difference into a false
    TRACE_NOT_FOUND. It never rewrites polarity/suffix conventions like a
    trailing `_n`, which is why a plausible-but-not-identical name still
    falls through to the (never auto-confirmed) fuzzy path rather than being
    silently treated as identical."""
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(name).strip().lower())


# --- register field input ----------------------------------------------------

@dataclass
class RegisterFieldRef:
    """One register field this module will attempt to trace. `name` is the
    field's own declared name (`register_map.schema.json`'s `fields[].name`).
    `rtl_signal_hint` is NOT part of that schema -- it is an optional extra a
    caller may set when a programming guide/RTL doc already states the
    expected RTL signal name explicitly, and is searched BEFORE `name` itself
    (a document-stated expected signal name is stronger evidence than
    guessing from the register field's own, possibly differently-styled,
    name)."""
    name: str
    register_name: Optional[str] = None
    block_name: Optional[str] = None
    description: Optional[str] = None
    access: Optional[str] = None
    rtl_signal_hint: Optional[str] = None

    @property
    def qualified_name(self) -> str:
        parts = [p for p in (self.block_name, self.register_name, self.name) if p]
        return ".".join(parts) if parts else (self.name or "<unnamed field>")


def field_ref_from_dict(d: dict) -> RegisterFieldRef:
    """Builds a RegisterFieldRef from a plain dict -- the shape a caller
    already holding `register_map.schema.json` field/register/block records
    (via `dv_harness.env_manifest.load_register_map()`/`validate_register_map()`)
    would naturally have on hand. Duck-typed rather than schema-bound so this
    module needs no dependency on any other concurrently-developed module,
    and accepts either the schema's own key names (`register_name`) or the
    shorter aliases a caller assembling context by hand is more likely to use
    (`register`/`block`)."""
    if not isinstance(d, dict) or not d.get("name"):
        raise ValueError("register field record must be a dict carrying a real 'name'")
    return RegisterFieldRef(
        name=d["name"],
        register_name=d.get("register_name") or d.get("register"),
        block_name=d.get("block_name") or d.get("block"),
        description=d.get("description"),
        access=d.get("access"),
        rtl_signal_hint=d.get("rtl_signal_hint"),
    )


def field_refs_from_register_map(doc: dict) -> List[RegisterFieldRef]:
    """Flattens a real, already-validated `register_map.schema.json` document
    (see `dv_harness.env_manifest.load_register_map()`) into one
    RegisterFieldRef per field, carrying its real block/register context.
    This module never invents a register-map document -- an empty/absent
    `blocks` list simply yields an empty list here, exactly as
    `verible_parser.extract_modules()` returning `[]` for a module-less file
    is a legitimate result, not an error."""
    refs: List[RegisterFieldRef] = []
    for block in doc.get("blocks", []) or []:
        for register in block.get("registers", []) or []:
            for f in register.get("fields", []) or []:
                refs.append(RegisterFieldRef(
                    name=f["name"],
                    register_name=register.get("name"),
                    block_name=block.get("name"),
                    description=f.get("description"),
                    access=f.get("access"),
                ))
    return refs


# --- generic accessor over an RTL module: works identically whether given a
# verible_parser dataclass instance (ModuleInfo/PortInfo/...) or a plain dict
# (e.g. verible_parser.to_dict()'s own shape) --------------------------------

def _mv_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_corpus_entries(corpus: Optional[Sequence]) -> List[Tuple[Optional[str], Any]]:
    """Turns a heterogeneous corpus (see module docstring) into a flat list of
    (file_path, module) pairs. An entry that is neither a file-level record
    (carries a real `modules` list) nor a module-shaped record (carries a
    `ports` or `signals` list, or at least a `name`) is silently skipped --
    it is not RTL this module knows how to read, not a match failure."""
    out: List[Tuple[Optional[str], Any]] = []
    for entry in corpus or []:
        modules = _mv_get(entry, "modules", None)
        if modules is not None:
            file_path = _mv_get(entry, "file_path", None)
            for m in modules:
                out.append((file_path, m))
            continue
        has_module_shape = (
            _mv_get(entry, "ports", None) is not None
            or _mv_get(entry, "signals", None) is not None
            or _mv_get(entry, "name", None) is not None
        )
        if has_module_shape:
            out.append((_mv_get(entry, "file_path", None), entry))
    return out


def _module_used_names(mod: Any) -> set:
    """The set of normalized names this module's OWN continuous assigns and
    instance port connections reference -- i.e. the evidence a bare
    declaration lacks. Reuses `verible_parser`'s own extraction shape
    (`continuous_assigns[].lhs_nets`/`rhs_nets`, `instances[].connections[].nets`)
    rather than re-deriving reference/net identity a second way."""
    used: set = set()
    for ca in _mv_get(mod, "continuous_assigns", []) or []:
        for n in list(_mv_get(ca, "lhs_nets", []) or []) + list(_mv_get(ca, "rhs_nets", []) or []):
            norm = normalize_signal_name(n)
            if norm:
                used.add(norm)
    for inst in _mv_get(mod, "instances", []) or []:
        for conn in _mv_get(inst, "connections", []) or []:
            for n in _mv_get(conn, "nets", []) or []:
                norm = normalize_signal_name(n)
                if norm:
                    used.add(norm)
    return used


@dataclass
class RtlSite:
    """One candidate RTL location (a port or a module-level signal) a
    register field's name could refer to."""
    module_name: str
    kind: str  # "port" | "signal"
    raw_name: str
    normalized_name: str
    direction: Optional[str] = None
    file_path: Optional[str] = None
    referenced: bool = False
    reference_evidence: List[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "module": self.module_name,
            "kind": self.kind,
            "name": self.raw_name,
            "direction": self.direction,
            "file_path": self.file_path,
            "referenced": self.referenced,
            "reference_evidence": list(self.reference_evidence),
        }


def collect_rtl_sites(corpus: Optional[Sequence]) -> List[RtlSite]:
    """Flattens every parsed module's ports and module-level signals into a
    searchable list of RtlSite records, each already carrying its own
    "referenced elsewhere" evidence -- computed once here so tracing many
    fields against one corpus does not repeat the same net-usage scan per
    field.

    A PORT is always `referenced=True`: by definition it is the module's own
    external connection surface (real wiring appears wherever this module is
    instantiated), which is a materially different fact from a bare internal
    declaration nothing in the parsed sources ever uses. An internal SIGNAL
    is `referenced=True` only when its normalized name appears in this same
    module's own continuous-assign or instance-connection nets -- a
    control-logic REFERENCE, not merely a declaration."""
    sites: List[RtlSite] = []
    for file_path, mod in _normalize_corpus_entries(corpus):
        mod_name = _mv_get(mod, "name", None) or "<unnamed module>"
        used = _module_used_names(mod)
        for p in _mv_get(mod, "ports", []) or []:
            raw = _mv_get(p, "name", None)
            if not raw:
                continue
            norm = normalize_signal_name(raw)
            if not norm:
                continue
            direction = _mv_get(p, "direction", None)
            evidence = [f"declared as a '{direction or 'unknown-direction'}' port of module '{mod_name}'"]
            if norm in used:
                evidence.append(
                    "also appears in this module's own continuous assign(s)/instance connection(s)")
            sites.append(RtlSite(
                module_name=mod_name, kind="port", raw_name=raw, normalized_name=norm,
                direction=direction, file_path=file_path, referenced=True,
                reference_evidence=evidence,
            ))
        for s in _mv_get(mod, "signals", []) or []:
            raw = _mv_get(s, "name", None)
            if not raw:
                continue
            norm = normalize_signal_name(raw)
            if not norm:
                continue
            referenced = norm in used
            evidence = (
                ["referenced in this module's own continuous assign(s)/instance connection(s)"]
                if referenced else []
            )
            sites.append(RtlSite(
                module_name=mod_name, kind="signal", raw_name=raw, normalized_name=norm,
                direction=None, file_path=file_path, referenced=referenced,
                reference_evidence=evidence,
            ))
    return sites


def _find_candidates(target_norm: str, sites: List[RtlSite]) -> Tuple[List[RtlSite], List[RtlSite]]:
    """(exact_matches, fuzzy_matches) for one normalized target name. A fuzzy
    match requires BOTH names to clear `MIN_FUZZY_MATCH_LEN` and one to be a
    substring of the other -- guarding against a short, generic fragment
    ("en", "clk") spuriously "matching" dozens of unrelated real signals."""
    exact = [s for s in sites if s.normalized_name == target_norm]
    fuzzy: List[RtlSite] = []
    if len(target_norm) >= MIN_FUZZY_MATCH_LEN:
        for s in sites:
            if s.normalized_name == target_norm:
                continue
            if len(s.normalized_name) < MIN_FUZZY_MATCH_LEN:
                continue
            if target_norm in s.normalized_name or s.normalized_name in target_norm:
                fuzzy.append(s)
    return exact, fuzzy


@dataclass
class TraceCandidate:
    site: RtlSite
    match_kind: str  # "EXACT" | "FUZZY"

    def to_dict(self) -> dict:
        d = self.site.to_dict()
        d["match_kind"] = self.match_kind
        return d


@dataclass
class RegisterTraceResult:
    field_ref: RegisterFieldRef
    status: str
    reason: str
    searched_name: str = ""
    modules_searched: int = 0
    candidates: List[TraceCandidate] = dataclass_field(default_factory=list)
    parse_warnings: List[dict] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "field": self.field_ref.qualified_name if self.field_ref else None,
            "field_name": self.field_ref.name if self.field_ref else None,
            "rtl_signal_hint": self.field_ref.rtl_signal_hint if self.field_ref else None,
            "status": self.status,
            "reason": self.reason,
            "searched_name": self.searched_name,
            "modules_searched": self.modules_searched,
            "candidates": [c.to_dict() for c in self.candidates],
            "parse_warnings": list(self.parse_warnings),
        }


def trace_register_field(
    field_ref: RegisterFieldRef,
    corpus: Optional[Sequence] = None,
    *,
    sites: Optional[List[RtlSite]] = None,
    parse_warnings: Optional[List[dict]] = None,
) -> RegisterTraceResult:
    """Traces ONE register field against a parsed RTL corpus (or, for a
    caller batching many fields, an already-built `sites` list from
    `collect_rtl_sites()` -- pass exactly one of `corpus`/`sites`). See the
    module docstring for the full status vocabulary and its rationale."""
    parse_warnings = list(parse_warnings or [])
    if field_ref is None or not getattr(field_ref, "name", None):
        return RegisterTraceResult(
            field_ref=field_ref, status=TRACE_BLOCKED,
            reason="register field record carries no real name to trace",
            parse_warnings=parse_warnings,
        )

    if sites is None:
        sites = collect_rtl_sites(corpus)

    if not sites:
        reason = "no parsed RTL modules were supplied to trace against"
        if parse_warnings:
            detail = "; ".join(f"{w.get('file_path')}: {w.get('reason')}" for w in parse_warnings)
            reason += f" ({len(parse_warnings)} source file(s) failed to parse: {detail})"
        reason += " -- the trace could not be attempted, which is not the same as finding no match"
        return RegisterTraceResult(
            field_ref=field_ref, status=TRACE_BLOCKED, reason=reason,
            searched_name=field_ref.name, modules_searched=0, parse_warnings=parse_warnings,
        )

    modules_searched = len({s.module_name for s in sites})
    search_terms = [t for t in (field_ref.rtl_signal_hint, field_ref.name) if t]

    for term in search_terms:
        norm = normalize_signal_name(term)
        if not norm:
            continue
        exact, fuzzy = _find_candidates(norm, sites)
        if len(exact) == 1:
            site = exact[0]
            if site.referenced:
                return RegisterTraceResult(
                    field_ref=field_ref, status=TRACE_CONFIRMED,
                    reason=(
                        f"unambiguous RTL {site.kind} '{site.raw_name}' in module "
                        f"'{site.module_name}' matches '{term}' by name and is referenced "
                        f"elsewhere in the parsed sources. This PROVES the signal NAME exists "
                        f"and is wired to something; it does NOT prove elaboration-time "
                        f"behavior, that this signal implements the field's declared "
                        f"semantics, or that this wiring is reachable under the design's "
                        f"real configuration -- a parser can never establish that."
                    ),
                    searched_name=term, modules_searched=modules_searched,
                    candidates=[TraceCandidate(site, "EXACT")],
                    parse_warnings=parse_warnings,
                )
            return RegisterTraceResult(
                field_ref=field_ref, status=TRACE_PARTIAL,
                reason=(
                    f"RTL {site.kind} '{site.raw_name}' in module '{site.module_name}' matches "
                    f"'{term}' by name exactly, but no reference to it (a continuous assign or "
                    f"instance connection) was found in the parsed sources -- a bare, unused "
                    f"declaration is not evidence of a live control path. Plausible but "
                    f"unconfirmed; never upgraded to TRACE_CONFIRMED on name match alone."
                ),
                searched_name=term, modules_searched=modules_searched,
                candidates=[TraceCandidate(site, "EXACT")],
                parse_warnings=parse_warnings,
            )
        if len(exact) > 1:
            distinct_modules = len({s.module_name for s in exact})
            return RegisterTraceResult(
                field_ref=field_ref, status=TRACE_PARTIAL,
                reason=(
                    f"{len(exact)} RTL site(s) across {distinct_modules} module(s) match "
                    f"'{term}' by name exactly -- plausible but AMBIGUOUS which one is the "
                    f"real control reference. Never upgraded to TRACE_CONFIRMED while more "
                    f"than one candidate exists."
                ),
                searched_name=term, modules_searched=modules_searched,
                candidates=[TraceCandidate(s, "EXACT") for s in exact],
                parse_warnings=parse_warnings,
            )
        if fuzzy:
            return RegisterTraceResult(
                field_ref=field_ref, status=TRACE_PARTIAL,
                reason=(
                    f"no exact name match for '{term}', but {len(fuzzy)} RTL site(s) contain, "
                    f"or are contained in, that name (substring match) -- plausible but "
                    f"ambiguous. Never upgraded to TRACE_CONFIRMED on a fuzzy match."
                ),
                searched_name=term, modules_searched=modules_searched,
                candidates=[TraceCandidate(s, "FUZZY") for s in fuzzy],
                parse_warnings=parse_warnings,
            )

    hint_note = f" or hinted name '{field_ref.rtl_signal_hint}'" if field_ref.rtl_signal_hint else ""
    return RegisterTraceResult(
        field_ref=field_ref, status=TRACE_NOT_FOUND,
        reason=(
            f"no RTL port or signal name (exact or substring) across {modules_searched} "
            f"parsed module(s) matches '{field_ref.name}'{hint_note}"
        ),
        searched_name=field_ref.name, modules_searched=modules_searched,
        parse_warnings=parse_warnings,
    )


def trace_register_fields(
    field_refs: Sequence[RegisterFieldRef],
    corpus: Optional[Sequence] = None,
    *,
    parse_warnings: Optional[List[dict]] = None,
) -> List[RegisterTraceResult]:
    """Batch form of `trace_register_field()`: builds the RTL site index
    ONCE and traces every field against it, rather than re-scanning the
    corpus per field."""
    sites = collect_rtl_sites(corpus)
    return [
        trace_register_field(f, sites=sites, parse_warnings=parse_warnings)
        for f in field_refs
    ]


def summarize_trace(results: Sequence[RegisterTraceResult]) -> dict:
    """Per-status counts over a batch of results, plus the worst-first
    aggregate exit code (see STATUS_EXIT_CODE / _EXIT_PRIORITY)."""
    counts = {s: 0 for s in TRACE_STATUSES}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    if not results:
        exit_code = 2
    else:
        present = {r.status for r in results}
        exit_code = 0
        for s in _EXIT_PRIORITY:
            if s in present:
                exit_code = STATUS_EXIT_CODE[s]
                break
    return {"total": len(results), "counts": counts, "exit_code": exit_code}


# --- convenience: parse real RTL source files with the real verible front end

def parse_rtl_sources(
    paths: Sequence,
    verible_bin: str = DEFAULT_VERIBLE_BIN,
) -> Tuple[List["verible_parser.FileParseResult"], List[dict]]:
    """Runs the REAL `verible_parser.parse_file()` over each real RTL source
    path. Returns `(parsed, warnings)`: `parsed` is every file that produced a
    real `FileParseResult` (hand straight to `trace_register_field(s)` /
    `collect_rtl_sites()`); `warnings` is one `{"file_path", "reason"}` dict
    per file verible could not parse at all (`VeribleUnavailableError` -- the
    binary itself did not run -- or `VeribleParseError` -- a real syntax
    error in that file). One bad file never blocks the rest, mirroring
    `doc_extraction_fanout.py`'s own "one failing category never sinks the
    fan-out" discipline."""
    parsed: List["verible_parser.FileParseResult"] = []
    warnings: List[dict] = []
    for p in paths or []:
        try:
            parsed.append(verible_parser.parse_file(p, verible_bin=verible_bin))
        except VeribleUnavailableError as exc:
            warnings.append({"file_path": str(p), "reason": f"VERIBLE_UNAVAILABLE: {exc}"})
        except VeribleParseError as exc:
            warnings.append({"file_path": str(p), "reason": f"VERIBLE_PARSE_ERROR: {exc}"})
    return parsed, warnings


# --- rendering / CLI ---------------------------------------------------------

def format_report(results: Sequence[RegisterTraceResult]) -> str:
    lines = [f"Register-to-RTL trace: {len(results)} field(s)"]
    summary = summarize_trace(results)
    lines.append(
        "  " + ", ".join(f"{k}={v}" for k, v in summary["counts"].items()))
    lines.append("")
    for r in results:
        lines.append(f"[{r.status:<14}] {r.field_ref.qualified_name if r.field_ref else '<none>'}")
        lines.append(f"                 {r.reason}")
        for c in r.candidates[:5]:
            lines.append(
                f"                 - {c.match_kind} {c.site.kind} '{c.site.raw_name}' "
                f"in module '{c.site.module_name}'"
                + (f" ({c.site.file_path})" if c.site.file_path else ""))
        if len(r.candidates) > 5:
            lines.append(f"                 ... and {len(r.candidates) - 5} more candidate(s)")
    lines.append("")
    lines.append(
        "SCOPE: this is a declaration-level PARSER trace (verible_parser.py), never an "
        "elaborator. TRACE_CONFIRMED proves a signal name exists and is referenced -- it "
        "never proves elaboration-time behavior.")
    return "\n".join(lines)


def execute_verb(
    register_map_path: str,
    rtl_paths: Sequence,
    as_json: bool = False,
    verible_bin: str = DEFAULT_VERIBLE_BIN,
    strict_partial: bool = False,
) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.register_rtl_trace`.
    Reads a real `register_map.schema.json` document via the existing
    `dv_harness.env_manifest.load_register_map()` (reused, not re-derived),
    parses `rtl_paths` with the real verible front end, and traces every
    declared field. Returns (text, exit_code)."""
    from . import env_manifest  # local import: avoids a hard dependency for pure library callers

    try:
        doc = env_manifest.load_register_map(register_map_path)
    except env_manifest.RegisterMapValidationError as exc:
        text = f"register-map at {register_map_path!r} failed validation: {exc}"
        return text, 2

    field_refs = field_refs_from_register_map(doc)
    parsed, warnings = parse_rtl_sources(rtl_paths, verible_bin=verible_bin)
    results = trace_register_fields(field_refs, parsed, parse_warnings=warnings)
    summary = summarize_trace(results)

    if as_json:
        text = json.dumps(
            {"summary": {"total": summary["total"], "counts": summary["counts"]},
             "fields": [r.to_dict() for r in results]},
            indent=2,
        )
    else:
        text = format_report(results)

    exit_code = summary["exit_code"]
    if exit_code == 3 and not strict_partial:
        exit_code = 0
    return text, exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.register_rtl_trace",
        description=(
            "Trace register_map.schema.json fields to RTL signal/control-logic "
            "references via the real verible declaration-level parse. Reads files "
            "only; never proves elaboration-time behavior."))
    ap.add_argument("--register-map", required=True, help="Path to a register_map.schema.json document.")
    ap.add_argument("--rtl", action="append", required=True, dest="rtl_paths",
                     help="An RTL source file to parse (repeatable).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    ap.add_argument("--strict-partial", action="store_true",
                     help="Exit non-zero when any field's trace is TRACE_PARTIAL (ambiguous).")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.register_map, a.rtl_paths, as_json=a.json, strict_partial=a.strict_partial)
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
