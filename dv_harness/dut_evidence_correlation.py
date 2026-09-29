"""dv_harness/dut_evidence_correlation.py -- correlates a requirement-declared
fact (an interrupt, a clock/reset signal, a mode, a feature) against
env.manifest.json's `dut_facts` and reports a per-item verdict: RTL_CONFIRMED /
RTL_PARTIAL / RTL_NOT_FOUND / RTL_CONTRADICTS_SPEC / NOT_AVAILABLE.

WHY THIS EXISTS. A requirement record (however it is authored -- see
requirement_contract.py's fifteen-field contract, e.g. its `feature` /
`protocol` / `precondition` text fields) can NAME a DUT-facing fact --
"usb_wake_irq fires on remote wake", "por_rst_n is active-low", "TEST_MODE bit
in CTRL0" -- and nothing in this repo checked whether that name corresponds to
anything the DUT actually has. `env_manifest.py` already assembles exactly the
facts needed to answer that (RTL ports/signals/parameters via
`verible_parser.to_dict()`, registers/fields via the register-map input
contract, clocks/resets and address regions via the SoC-arch-map input
contract) -- this module reads that assembled manifest and does the join.

REUSE OVER REINVENT. This module parses NOTHING itself: it calls
`env_manifest.load_env_manifest()` (read-only, schema-validated) and reads the
`dut_facts` layers exactly as `build_dut_facts_rtl()` / `_registers()` /
`_address_map()` / `_clock_reset()` already produced them. There is no second
RTL parser, no second register-map reader and no second SoC-arch-map reader in
this module.

INPUT SHAPE IS DELIBERATELY GENERIC (duck-typed), per this batch's file-safety
scope: this task must not import from, or wait on, any other item in this or
the concurrently-running batch. A "declared fact" is accepted as a plain
dict -- `{"item_id", "fact_type", "name", ...}` -- rather than a
`requirement_contract.RequirementContract` object, even though that module
already exists in this repo (it was not created by, and is not owned by, this
task). A caller sitting in front of a real, schema-validated, COMPLETE
`requirement_contract` record would build this module's `items` list from that
record's own `feature` / `protocol` / `precondition` / `observability` text
(e.g. one item per DUT-facing name a human or a future extractor picks out of
those fields) and pass it in here -- this module does not parse that prose
itself, because turning free text into a set of candidate signal/register/mode
names is a different, extraction-shaped problem this task does not attempt
(the same reasoning `doc_extraction_fanout.py` gives for why 40d/40e/40f
"remain input-CONTRACT transcription pipelines ... performed by a human or an
agent reading the document").

THE FIVE-STATUS VERDICT, and what earns each one:
  RTL_CONFIRMED         an EXACT name match exists in at least one relevant
                         dut_facts layer that was actually available, and
                         every attribute the item declared under `expected`
                         that this match's layer can express agrees with it.
  RTL_CONTRADICTS_SPEC  an EXACT name match exists, but at least one
                         `expected` attribute this match's layer records
                         (active_level, frequency_mhz, direction, access,
                         width, reset_value, base_address, bus, synchronous)
                         disagrees with the manifest's real recorded value.
                         This module reports the disagreement; it does not
                         decide which side is right (Evidence Truth Rule /
                         Source Authority Order -- arbitration is a human
                         decision, the same boundary
                         `requirement_contract.py`'s own docstring keeps for a
                         CONTRADICTORY requirement).
  RTL_PARTIAL           no exact match, but a case-insensitive substring match
                         was found in an available layer -- a plausible but
                         unproven correspondence (naming drift, a prefix/
                         suffix convention, a description hit).
  RTL_NOT_FOUND         every layer relevant to this fact_type was available
                         and searched, and none of them contains anything
                         resembling the declared name. This is a real
                         negative, not an absence of evidence.
  NOT_AVAILABLE         every layer relevant to this fact_type was itself
                         NOT_AVAILABLE (or the manifest does not exist at
                         all), so nothing could be searched. Per the Evidence
                         Truth Rule this is never collapsed into
                         RTL_NOT_FOUND -- "we looked and it is not there" and
                         "we could not look" are different claims, and only
                         the first is a real finding about the DUT.

DELIBERATELY BOUNDED, stated rather than implied closed.
(1) Matching is name-based (exact / case-insensitive substring), never
    semantic: "usb_wake_irq" and "USB Wake Interrupt" will not correlate
    unless the caller supplies the RTL-shaped name as an `alias`. No fuzzy
    edit-distance, no synonym table -- either would risk manufacturing a
    correspondence the DUT does not actually have.
(2) RTL ports/signals/parameters and register/field entries carry no source
    LINE number anywhere upstream (`verible_parser.to_dict()`'s PortInfo/
    SignalInfo/ParamInfo dataclasses record name/direction/type only;
    register_map.schema.json records no line either) -- this module cites the
    real file `path` plus a structural locator (module/port, block/register/
    field) instead of fabricating a line number neither producer recorded.
    Where the upstream fact DOES carry a real evidence string with a line
    (`clock_reset`'s clocks/resets and `address_map`'s entries, sourced from
    soc_arch_map.schema.json's own `evidence` field), that string is cited
    verbatim.
(3) It DECIDES nothing beyond the verdict: no build, no job, no approval, no
    stage gate, no memory write. It reads `env.manifest.json` once, read-only,
    through the existing loader.
(4) An item whose `fact_type` is not one of the five named kinds is not
    rejected -- it is searched against every dut_facts layer (the same
    breadth as "feature") and the report carries a warning naming the
    unrecognised value, never a silent narrowing of the search.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import env_manifest

#: The four fact kinds the task names, plus "feature" as the deliberately
#: broadest catch-all. Order carries no meaning.
FACT_TYPES: Tuple[str, ...] = ("interrupt", "clock", "reset", "mode", "feature")

STATUS_RTL_CONFIRMED = "RTL_CONFIRMED"
STATUS_RTL_PARTIAL = "RTL_PARTIAL"
STATUS_RTL_NOT_FOUND = "RTL_NOT_FOUND"
STATUS_RTL_CONTRADICTS_SPEC = "RTL_CONTRADICTS_SPEC"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
CORRELATION_STATUSES: Tuple[str, ...] = (
    STATUS_RTL_CONFIRMED, STATUS_RTL_CONTRADICTS_SPEC, STATUS_RTL_PARTIAL,
    STATUS_RTL_NOT_FOUND, STATUS_NOT_AVAILABLE,
)

#: Which dut_facts layers are worth searching for each fact_type. "feature"
#: (and any unrecognised fact_type) searches every layer.
_ALL_LAYERS: Tuple[str, ...] = ("rtl", "registers", "clock_reset", "address_map")
FACT_TYPE_LAYERS: Dict[str, Tuple[str, ...]] = {
    "interrupt": ("rtl", "registers"),
    "clock": ("clock_reset", "rtl"),
    "reset": ("clock_reset", "rtl"),
    "mode": ("registers", "rtl"),
    "feature": _ALL_LAYERS,
}

#: Layer status field this module treats as "usable" -- must match the exact
#: value each real build_dut_facts_* function stamps on success.
_LAYER_LOADED_STATUS: Dict[str, str] = {
    "rtl": "PARSED",
    "registers": "LOADED",
    "clock_reset": "LOADED",
    "address_map": "LOADED",
}

_MIN_FUZZY_LEN = 3  # below this a substring match is noise, not evidence


class DutEvidenceCorrelationError(ValueError):
    """A caller usage error -- a malformed declared-fact item, not an
    evidence finding. Raised loudly rather than silently skipping the item,
    the same fail-closed shape as env_manifest.py's own *ValidationError
    classes."""


def _normalize(name: str) -> str:
    return "".join(ch.lower() for ch in (name or "") if ch.isalnum())


def _names_for(item: Dict[str, Any]) -> List[str]:
    names = [item["name"]]
    names.extend(item.get("aliases") or [])
    return [n for n in names if n]


def _match_kind(query_names: Sequence[str], candidate: Optional[str]) -> Optional[Tuple[str, str]]:
    """Returns (match_kind, matched_query_name) or None. EXACT beats FUZZY;
    callers should prefer the first EXACT result across all candidate
    fields/queries before accepting a FUZZY one."""
    if not candidate:
        return None
    cand_norm = _normalize(candidate)
    if not cand_norm:
        return None
    best: Optional[Tuple[str, str]] = None
    for q in query_names:
        q_norm = _normalize(q)
        if not q_norm:
            continue
        if q_norm == cand_norm:
            return ("EXACT", q)
        if len(q_norm) >= _MIN_FUZZY_LEN and len(cand_norm) >= _MIN_FUZZY_LEN and \
                (q_norm in cand_norm or cand_norm in q_norm):
            best = best or ("FUZZY", q)
    return best


def _layer_availability(dut_facts: Dict[str, Any], layer: str) -> Tuple[bool, Optional[str]]:
    section = dut_facts.get(layer) or {}
    status = section.get("status")
    expected = _LAYER_LOADED_STATUS[layer]
    if status == expected:
        return True, None
    reason = section.get("reason") or f"dut_facts.{layer}.status is {status!r}, not {expected!r}"
    return False, reason


def _search_rtl(dut_facts: Dict[str, Any], query_names: Sequence[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for f in (dut_facts.get("rtl") or {}).get("files") or []:
        file_path = f.get("file_path")
        for mod in f.get("modules") or []:
            mod_name = mod.get("name")
            m = _match_kind(query_names, mod_name)
            if m:
                matches.append({
                    "layer": "rtl", "kind": "module", "match_kind": m[0], "matched_query": m[1],
                    "name": mod_name, "module": mod_name, "file_path": file_path,
                    "evidence_ref": f"{file_path}::module {mod_name}",
                })
            for port in mod.get("ports") or []:
                m = _match_kind(query_names, port.get("name"))
                if m:
                    matches.append({
                        "layer": "rtl", "kind": "port", "match_kind": m[0], "matched_query": m[1],
                        "name": port.get("name"), "module": mod_name, "file_path": file_path,
                        "direction": port.get("direction"), "data_type": port.get("data_type"),
                        "evidence_ref": f"{file_path}::module {mod_name}::port {port.get('name')}",
                    })
            for sig in mod.get("signals") or []:
                m = _match_kind(query_names, sig.get("name"))
                if m:
                    matches.append({
                        "layer": "rtl", "kind": "signal", "match_kind": m[0], "matched_query": m[1],
                        "name": sig.get("name"), "module": mod_name, "file_path": file_path,
                        "data_type": sig.get("data_type"),
                        "evidence_ref": f"{file_path}::module {mod_name}::signal {sig.get('name')}",
                    })
            for p in mod.get("parameters") or []:
                m = _match_kind(query_names, p.get("name"))
                if m:
                    matches.append({
                        "layer": "rtl", "kind": "parameter", "match_kind": m[0], "matched_query": m[1],
                        "name": p.get("name"), "module": mod_name, "file_path": file_path,
                        "default_text": p.get("default_text"),
                        "evidence_ref": f"{file_path}::module {mod_name}::parameter {p.get('name')}",
                    })
    return matches


def _search_registers(dut_facts: Dict[str, Any], query_names: Sequence[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    layer = dut_facts.get("registers") or {}
    path = (layer.get("source") or {}).get("path")
    for block in layer.get("blocks") or []:
        block_name = block.get("name")
        m = _match_kind(query_names, block_name)
        if m:
            matches.append({
                "layer": "registers", "kind": "block", "match_kind": m[0], "matched_query": m[1],
                "name": block_name, "path": path,
                "evidence_ref": f"{path}::block {block_name}",
            })
        for reg in block.get("registers") or []:
            reg_name = reg.get("name")
            m = _match_kind(query_names, reg_name)
            if not m and reg.get("description"):
                dm = _match_kind(query_names, reg.get("description"))
                if dm:
                    m = ("FUZZY", dm[1])
            if m:
                matches.append({
                    "layer": "registers", "kind": "register", "match_kind": m[0], "matched_query": m[1],
                    "name": reg_name, "block": block_name, "path": path,
                    "address_offset": reg.get("address_offset"), "width": reg.get("width"),
                    "access": reg.get("access"), "reset_value": reg.get("reset_value"),
                    "evidence_ref": f"{path}::block {block_name}::register {reg_name}",
                })
            for fld in reg.get("fields") or []:
                fld_name = fld.get("name")
                fm = _match_kind(query_names, fld_name)
                if fm:
                    matches.append({
                        "layer": "registers", "kind": "field", "match_kind": fm[0], "matched_query": fm[1],
                        "name": fld_name, "block": block_name, "register": reg_name, "path": path,
                        "bit_offset": fld.get("bit_offset"), "bit_width": fld.get("bit_width"),
                        "access": fld.get("access"), "reset_value": fld.get("reset_value"),
                        "evidence_ref": f"{path}::block {block_name}::register {reg_name}::field {fld_name}",
                    })
    return matches


def _search_clock_reset(dut_facts: Dict[str, Any], query_names: Sequence[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    layer = dut_facts.get("clock_reset") or {}
    path = (layer.get("source") or {}).get("path")
    for clk in layer.get("clocks") or []:
        m = _match_kind(query_names, clk.get("name"))
        if m:
            evidence = clk.get("evidence")
            matches.append({
                "layer": "clock_reset", "kind": "clock", "match_kind": m[0], "matched_query": m[1],
                "name": clk.get("name"), "path": path,
                "frequency_mhz": clk.get("frequency_mhz"), "source_pll": clk.get("source"),
                "domain": clk.get("domain"),
                "evidence_ref": evidence or f"{path}::clock {clk.get('name')}",
            })
    for rst in layer.get("resets") or []:
        m = _match_kind(query_names, rst.get("name"))
        if m:
            evidence = rst.get("evidence")
            matches.append({
                "layer": "clock_reset", "kind": "reset", "match_kind": m[0], "matched_query": m[1],
                "name": rst.get("name"), "path": path,
                "active_level": rst.get("active_level"), "synchronous": rst.get("synchronous"),
                "clock": rst.get("clock"),
                "evidence_ref": evidence or f"{path}::reset {rst.get('name')}",
            })
    return matches


def _search_address_map(dut_facts: Dict[str, Any], query_names: Sequence[str]) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    layer = dut_facts.get("address_map") or {}
    path = (layer.get("source") or {}).get("path")
    for e in layer.get("entries") or []:
        m = _match_kind(query_names, e.get("name"))
        if m:
            evidence = e.get("evidence")
            matches.append({
                "layer": "address_map", "kind": "address_region", "match_kind": m[0], "matched_query": m[1],
                "name": e.get("name"), "path": path,
                "base_address": e.get("base_address"), "size_bytes": e.get("size_bytes"),
                "target": e.get("target"), "bus": e.get("bus"),
                "evidence_ref": evidence or f"{path}::address_map {e.get('name')}",
            })
    return matches


_LAYER_SEARCHERS = {
    "rtl": _search_rtl,
    "registers": _search_registers,
    "clock_reset": _search_clock_reset,
    "address_map": _search_address_map,
}

#: expected-key -> (candidate kinds it applies to, candidate field name,
#: comparator). A key absent from an exact match's own recorded fields is
#: simply not checked (unverifiable is not a contradiction).
def _cmp_eq_ci(a, b) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _cmp_num_close(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= max(1e-6, 0.01 * abs(float(a)))
    except (TypeError, ValueError):
        return str(a) == str(b)


_ATTRIBUTE_CHECKS: Dict[str, Tuple[Tuple[str, ...], str, Any]] = {
    "active_level": (("reset",), "active_level", _cmp_eq_ci),
    "synchronous": (("reset",), "synchronous", lambda a, b: bool(a) == bool(b)),
    "frequency_mhz": (("clock",), "frequency_mhz", _cmp_num_close),
    "direction": (("port",), "direction", _cmp_eq_ci),
    "access": (("register", "field"), "access", _cmp_eq_ci),
    "width": (("register",), "width", lambda a, b: int(a) == int(b)),
    "bit_width": (("field",), "bit_width", lambda a, b: int(a) == int(b)),
    "reset_value": (("register", "field"), "reset_value", _cmp_eq_ci),
    "base_address": (("address_region",), "base_address", _cmp_eq_ci),
    "bus": (("address_region",), "bus", _cmp_eq_ci),
    "target": (("address_region",), "target", _cmp_eq_ci),
}


def _check_contradictions(exact_matches: List[Dict[str, Any]], expected: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for key, exp_val in (expected or {}).items():
        check = _ATTRIBUTE_CHECKS.get(key)
        if check is None or exp_val is None:
            continue
        kinds, field_name, comparator = check
        for match in exact_matches:
            if match["kind"] not in kinds:
                continue
            actual = match.get(field_name)
            if actual is None:
                continue  # not recorded upstream -- unverifiable, not a contradiction
            try:
                agrees = comparator(exp_val, actual)
            except Exception:
                agrees = str(exp_val) == str(actual)
            if not agrees:
                findings.append({
                    "attribute": key, "expected": exp_val, "actual": actual,
                    "evidence_ref": match.get("evidence_ref"), "match": match,
                })
    return findings


def correlate_item(item: Dict[str, Any], dut_facts: Dict[str, Any]) -> Dict[str, Any]:
    """Correlates ONE declared fact against an already-loaded manifest's
    `dut_facts` dict. `item` requires `item_id`, `fact_type`, `name`; may
    carry `aliases` (list[str]) and `expected` (dict of attribute->value, see
    `_ATTRIBUTE_CHECKS` for the recognised keys). Raises
    DutEvidenceCorrelationError on a malformed item -- a caller mistake, not
    an evidence finding."""
    for required in ("item_id", "fact_type", "name"):
        if not item.get(required):
            raise DutEvidenceCorrelationError(f"declared-fact item missing required field {required!r}: {item!r}")
    fact_type = item["fact_type"]
    warnings: List[str] = []
    if fact_type not in FACT_TYPES:
        warnings.append(
            f"fact_type {fact_type!r} is not one of {FACT_TYPES}; searched every dut_facts layer "
            "rather than narrowing (an unrecognised fact_type must never silently narrow the search)"
        )
    layers = FACT_TYPE_LAYERS.get(fact_type, _ALL_LAYERS)
    query_names = _names_for(item)

    layer_status: Dict[str, Dict[str, Any]] = {}
    matches: List[Dict[str, Any]] = []
    any_available = False
    for layer in layers:
        available, reason = _layer_availability(dut_facts, layer)
        layer_status[layer] = {"available": available, "reason": reason}
        if not available:
            continue
        any_available = True
        matches.extend(_LAYER_SEARCHERS[layer](dut_facts, query_names))

    exact_matches = [m for m in matches if m["match_kind"] == "EXACT"]
    fuzzy_matches = [m for m in matches if m["match_kind"] == "FUZZY"]
    contradictions: List[Dict[str, Any]] = []

    if exact_matches:
        contradictions = _check_contradictions(exact_matches, item.get("expected") or {})
        status = STATUS_RTL_CONTRADICTS_SPEC if contradictions else STATUS_RTL_CONFIRMED
        reason = (
            f"{len(contradictions)} declared attribute(s) disagree with the manifest's recorded value"
            if contradictions else
            f"exact name match in dut_facts.{sorted({m['layer'] for m in exact_matches})}"
        )
    elif fuzzy_matches:
        status = STATUS_RTL_PARTIAL
        reason = (
            f"no exact match; {len(fuzzy_matches)} substring match(es) in "
            f"dut_facts.{sorted({m['layer'] for m in fuzzy_matches})} -- unproven correspondence"
        )
    elif any_available:
        status = STATUS_RTL_NOT_FOUND
        reason = (
            f"searched dut_facts.{list(layers)} (all available) for {query_names!r}; no match found"
        )
    else:
        status = STATUS_NOT_AVAILABLE
        reason = (
            f"every dut_facts layer relevant to fact_type={fact_type!r} "
            f"({list(layers)}) was itself NOT_AVAILABLE -- nothing could be searched"
        )

    return {
        "item_id": item["item_id"],
        "fact_type": fact_type,
        "name": item["name"],
        "status": status,
        "reason": reason,
        "layers_searched": list(layers),
        "layer_status": layer_status,
        "exact_matches": exact_matches,
        "fuzzy_matches": fuzzy_matches,
        "contradictions": contradictions,
        "warnings": warnings,
    }


def correlate_items(items: Sequence[Dict[str, Any]], manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Correlates every item in `items` against an already-loaded `manifest`
    dict (or None). A None manifest reports NOT_AVAILABLE for every item,
    never a guess -- see `correlate()` for the disk-loading front door that
    produces this None in the "no env.manifest.json exists yet" case."""
    dut_facts = (manifest or {}).get("dut_facts") or {}
    results = []
    for item in items:
        if manifest is None:
            results.append({
                "item_id": item.get("item_id"), "fact_type": item.get("fact_type"), "name": item.get("name"),
                "status": STATUS_NOT_AVAILABLE,
                "reason": "no env.manifest.json is available for this project -- every dut_facts layer is "
                          "unknown, never guessed",
                "layers_searched": [], "layer_status": {}, "exact_matches": [], "fuzzy_matches": [],
                "contradictions": [], "warnings": [],
            })
            continue
        results.append(correlate_item(item, dut_facts))

    summary = {s: 0 for s in CORRELATION_STATUSES}
    for r in results:
        summary[r["status"]] += 1
    return {
        "manifest_status": "NOT_AVAILABLE" if manifest is None else "LOADED",
        "items": results,
        "summary": summary,
    }


def correlate(items: Sequence[Dict[str, Any]], manifest_path) -> Dict[str, Any]:
    """The disk-loading front door. `manifest_path` missing entirely reports
    NOT_AVAILABLE for every item (per this module's own contract); a path
    that exists but fails schema validation is NOT swallowed -- it propagates
    as env_manifest.EnvManifestValidationError, the same real-error-not-
    silently-downgraded discipline env_manifest.py itself uses for a real
    parse failure against a real supplied file."""
    manifest: Optional[Dict[str, Any]]
    if manifest_path is None or not Path(manifest_path).is_file():
        manifest = None
    else:
        manifest = env_manifest.load_env_manifest(manifest_path)
    report = correlate_items(items, manifest)
    report["manifest_path"] = str(manifest_path) if manifest_path is not None else None
    if manifest is None and manifest_path is not None:
        report["manifest_status"] = "NOT_AVAILABLE"
        report["manifest_reason"] = f"env.manifest.json does not exist at {manifest_path}"
    return report


# ---------------------------------------------------------------------------
# CLI front door -- python -m dv_harness.dut_evidence_correlation
# (no dv-harness verb: cli.py is out of scope for this task; the exact
# STAGE_GATES / CLI-verb snippet an integrator could wire in is returned in
# this task's structured output rather than written here.)
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="dut-evidence-correlation")
    parser.add_argument("--manifest", required=True, help="path to env.manifest.json")
    parser.add_argument("--items", required=True, help="path to a JSON file: a list of declared-fact items")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    try:
        report = correlate(items, args.manifest)
    except env_manifest.EnvManifestValidationError as e:
        print(f"env.manifest.json failed validation: {e}", file=sys.stderr)
        return 2
    except DutEvidenceCorrelationError as e:
        print(f"malformed declared-fact item: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["items"]:
            print(f"{r['item_id']:30s} {r['fact_type']:10s} {r['status']:22s} {r['reason']}")
        print(f"\nsummary: {report['summary']}")

    if report["manifest_status"] == "NOT_AVAILABLE":
        return 2
    bad = report["summary"][STATUS_RTL_CONTRADICTS_SPEC] + report["summary"][STATUS_RTL_NOT_FOUND]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(execute_verb())
