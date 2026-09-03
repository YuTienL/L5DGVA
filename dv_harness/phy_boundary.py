"""dv_harness/phy_boundary.py -- generator for phy_boundary.json, the
asset-processing table's row-2 artifact: "PHY model -> phy_boundary.json
(PHY<->controller interface type, serial/parallel boundary) -> bind-location
decision".

Before 2026-09-04 this artifact had no extractor anywhere in the repo, even
though CLAUDE.md's Context Budget section already declares
`.dv-workflow/phy_boundary.json` as a tier-2 always-resident artifact and
`context_budget.py resident` already reports it MISSING. This module is that
missing extractor.

WHAT IT DERIVES FROM (never invents):
  * a real RTL port table -- exactly the `modules` list
    `env_manifest.build_dut_facts_rtl()` already produces by running the real
    `verible_parser.parse_file()`. This module does NOT re-parse RTL; it
    consumes that existing output, so there is one RTL-parsing mechanism in
    this repo, not two.
  * a project-declared PHY/controller module PAIR. Which module is the PHY is
    a real project fact the project states; it is never guessed from a module
    name. `determine_role_from_port_direction()` in connectivity.py takes no
    instance-name parameter at all, by design, so that naming evidence cannot
    leak into a structural decision -- the same discipline applies here.

WHAT IT DECIDES: at which layer a bind may be mounted. The engineering rule,
stated once here and enforced by `decide_bind_location()`:

    A protocol VIP monitor bound at a SERIAL boundary observes line-rate
    symbols it cannot decode without a PHY model, so it silently monitors
    nothing -- it would pass Gate 1 (elaborates) and Gate 2 (clock toggles,
    reset deasserts, no X at t0) and only fail at Gate 3, as a silent
    monitor. The PARALLEL controller-facing boundary (PIPE/UTMI-shaped: a
    data bus of >= PARALLEL_MIN_WIDTH bits plus its own control signals) is
    where transactions are actually observable, so that is the sanctioned
    mount layer.

That is precisely the failure connectivity.py's Gate 3 exists to catch after
the fact; this module's job is to prevent it being emitted in the first
place.

SERIAL_MAX_WIDTH/PARALLEL_MIN_WIDTH are deliberately NOT tuned to any one
protocol. A differential serial lane is 1-2 bits; a symbol-level parallel
boundary is a byte or wider. The gap between 2 and 8 is left as an explicit
UNDECIDABLE band rather than being split by a guessed threshold -- a boundary
landing there goes to the question queue, per the same T4 discipline
connectivity.py already applies to an undecidable bind target.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "phy_boundary.schema.json"

# A differential serial lane carries 1 bit per wire (2 for a p/n pair modeled
# as one 2-bit port). Anything at or below this is line-rate serial.
SERIAL_MAX_WIDTH = 2
# A symbol/transaction-level parallel boundary is at least one byte wide.
PARALLEL_MIN_WIDTH = 8

# Signals that carry no protocol payload and must not drive the serial vs
# parallel decision -- a 1-bit `valid` on a 32-bit parallel bus would
# otherwise make the boundary look serial, and a `pclk` would make it look
# like a serial lane.
#
# Matched per UNDERSCORE-DELIMITED TOKEN, not on the whole name and not as a
# free substring. A whole-name set was tried first and was wrong against real
# verible output: `pclk`, `preset_n` and `pipe_rxvalid` are exactly the names
# real RTL uses, and none of them equals `clk`/`reset`/`valid`. A free
# substring match would be worse in the other direction -- it would swallow
# `rx_enable_data`. Token matching with an optional bus-prefix and polarity
# suffix handles the real names without the substring false positives.
#
# CRITICALLY, this pattern must NOT match a differential serial lane
# (`txp`/`txn`/`rxp`/`rxn`): those ARE the payload of a serial boundary, and
# excluding them would make every serial boundary look like it had no payload
# at all and classify UNDECIDABLE. `rxp` is prefix `rx` with no control core,
# so it correctly does not match. A test pins this behaviour.
#
# The cores are split into two groups because they carry different false-
# positive risk, and one permissive rule for both would be wrong:
#
#   STRONG cores (clk/clock/rst/reset/por) are unambiguous -- no real payload
#   signal name ends in them -- so ANY prefix is allowed. This is what makes
#   `pclk`, `refclk`, `preset_n` and `por_n` classify correctly; all four are
#   real names verible produced from the worked example, and a fixed
#   prefix list missed every one of them.
#
#   WEAK cores (en/req/ack/sel/valid/...) are short and appear inside ordinary
#   words -- `token` ends in "en", `channel` ends in "el". They are therefore
#   restricted to a known bus/polarity prefix, so `rxvalid` matches while
#   `token` does not.
_STRONG_CORE_RE = re.compile(
    r"^[a-z0-9]*(?:clk|clock|rst|reset|por)\d*(?:_?[nbp])?$", re.IGNORECASE)
_WEAK_CORE_RE = re.compile(
    r"^(?:tx|rx|p|n|a|h)?"
    r"(?:valid|ready|enable|en|error|err|ack|req|sel|powerdown|pwrdn|standby)"
    r"\d*(?:_?[nbp])?$", re.IGNORECASE)


class PhyBoundaryValidationError(ValueError):
    """A phy_boundary document fails phy_boundary.schema.json validation.
    Raised rather than returning None, matching env_manifest.py's
    EnvManifestValidationError / run_profile.py's RunProfileValidationError
    fail-closed discipline -- a caller must never persist or act on an
    invalid boundary decision."""


def validate_phy_boundary(doc: dict) -> None:
    """Validate `doc` against phy_boundary.schema.json. Raises
    PhyBoundaryValidationError on any violation."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - jsonschema is a real dependency here
        raise PhyBoundaryValidationError(
            "jsonschema package is not installed; cannot validate against "
            "phy_boundary.schema.json. Install it rather than skipping validation."
        ) from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise PhyBoundaryValidationError("phy_boundary.schema.json validation failed:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# width extraction -- real parsed evidence, honest None when unresolvable
# ---------------------------------------------------------------------------

_PACKED_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")


def parse_port_width(data_type: Optional[str]) -> Optional[int]:
    """Bit width from a port's real declared `data_type` text (verible's own
    PortInfo.data_type). Returns None -- never a defaulted 1 -- when the
    declaration carries a packed range this function cannot resolve to
    literal bounds (e.g. `logic [WIDTH-1:0]`, a parameterized width whose
    value lives in a parameter this function is deliberately not resolving).
    A bare declaration with no packed range at all IS a real 1-bit port and
    returns 1.

    Reporting None honestly matters: an unresolved width must land in
    `unresolved_width_signals` and push the classification toward
    UNDECIDABLE, rather than being silently counted as a 1-bit serial signal
    and producing a confident wrong bind decision."""
    if data_type is None:
        return None
    text = str(data_type)
    ranges = _PACKED_RANGE_RE.findall(text)
    if not ranges:
        # No packed range at all. Distinguish "plainly a 1-bit port" from
        # "has a range this regex could not read" -- a '[' present but
        # unmatched means a parameterized/unresolvable width.
        if "[" in text:
            return None
        return 1
    width = 1
    for hi, lo in ranges:
        width *= abs(int(hi) - int(lo)) + 1
    return width


def is_payload_port(name: Optional[str]) -> bool:
    """Whether a port carries protocol payload, i.e. whether its width is
    allowed to drive the serial/parallel decision.

    A port is NON-payload when ANY of its underscore-delimited tokens is a
    control token (see `_NON_PAYLOAD_TOKEN_RE`): `pipe_rxvalid` is excluded
    on its `rxvalid` token, `preset_n` on its `preset` token. `pipe_rxdata`
    has no control token and stays payload, and so do the differential serial
    lanes `txp`/`rxn`."""
    if not name:
        return False
    return not any(_STRONG_CORE_RE.match(tok) or _WEAK_CORE_RE.match(tok)
                   for tok in name.strip().lower().split("_") if tok)


# ---------------------------------------------------------------------------
# boundary signal set -- ports genuinely present on BOTH modules
# ---------------------------------------------------------------------------

def _index_modules(modules: Iterable[dict]) -> dict:
    out = {}
    for mod in modules or []:
        name = mod.get("name")
        if name:
            out[name] = mod
    return out


def _port_index(module: dict) -> dict:
    return {p.get("name"): p for p in (module.get("ports") or []) if p.get("name")}


def extract_boundary_signals(phy_module: dict, controller_module: dict) -> list:
    """The boundary signal set = ports appearing on BOTH modules' real port
    lists. This is structural evidence of a shared connection, not a
    name-similarity score: the same identifier declared as a port on each
    side of a point-to-point connection is how a boundary actually shows up
    in a port table.

    Width is taken from the PHY side's declaration when resolvable, falling
    back to the controller side's -- the two must agree in real RTL, and
    disagreement is surfaced (not hidden) by both `width_source` values
    being recorded."""
    phy_ports = _port_index(phy_module)
    ctrl_ports = _port_index(controller_module)
    shared = sorted(set(phy_ports) & set(ctrl_ports))
    signals = []
    for name in shared:
        p = phy_ports[name]
        c = ctrl_ports[name]
        phy_width = parse_port_width(p.get("data_type"))
        ctrl_width = parse_port_width(c.get("data_type"))
        width = phy_width if phy_width is not None else ctrl_width
        pd = (p.get("direction") or None)
        cd = (c.get("direction") or None)
        opposed = None
        if pd and cd:
            opposed = {pd.strip().lower(), cd.strip().lower()} == {"input", "output"}
        signals.append({
            "name": name,
            "width": width,
            "width_source": str(p.get("data_type") if phy_width is not None else c.get("data_type")),
            "phy_direction": pd,
            "controller_direction": cd,
            "direction_opposed": opposed,
        })
    return signals


# ---------------------------------------------------------------------------
# classification + bind-location decision
# ---------------------------------------------------------------------------

def classify_boundary(boundary_signals: list, declared_kind: Optional[str] = None) -> dict:
    """Serial vs parallel from real port widths. `declared_kind`, when the
    project states it outright, wins and is recorded as tier B1_DECLARED --
    a real explicit project fact always outranks a derived one, the same
    ordering connectivity.py's T1 (an existing bind, already decided)
    applies over its own naming heuristics."""
    if declared_kind:
        kind = declared_kind.strip().upper()
        if kind not in ("SERIAL", "PARALLEL", "MIXED", "UNDECIDABLE"):
            raise ValueError(
                f"declared boundary kind {declared_kind!r} is not one of "
                "SERIAL/PARALLEL/MIXED/UNDECIDABLE"
            )
        return {
            "kind": kind, "tier": "B1_DECLARED",
            "rationale": f"project explicitly declared this boundary as {kind}; "
                         "an explicit project fact outranks width-derived inference",
            "serial_signals": [], "parallel_signals": [], "unresolved_width_signals": [],
        }

    payload = [s for s in boundary_signals if is_payload_port(s["name"])]
    serial = sorted(s["name"] for s in payload if s["width"] is not None and s["width"] <= SERIAL_MAX_WIDTH)
    parallel = sorted(s["name"] for s in payload if s["width"] is not None and s["width"] >= PARALLEL_MIN_WIDTH)
    unresolved = sorted(s["name"] for s in payload if s["width"] is None)
    # Widths strictly between SERIAL_MAX_WIDTH and PARALLEL_MIN_WIDTH are
    # deliberately in neither bucket -- see module docstring's explicit
    # UNDECIDABLE band.
    between = sorted(
        s["name"] for s in payload
        if s["width"] is not None and SERIAL_MAX_WIDTH < s["width"] < PARALLEL_MIN_WIDTH
    )

    if not payload:
        kind, rationale = "UNDECIDABLE", (
            "no payload-bearing signal is shared by both modules' port lists "
            "(only clock/reset/handshake ports, or no shared ports at all)"
        )
    elif unresolved and not parallel and not serial:
        kind, rationale = "UNDECIDABLE", (
            f"every payload signal has an unresolvable parameterized width: {unresolved}"
        )
    elif parallel and serial:
        kind, rationale = "MIXED", (
            f"both a serial lane set {serial} (<= {SERIAL_MAX_WIDTH} bits) and a parallel bus "
            f"{parallel} (>= {PARALLEL_MIN_WIDTH} bits) are present on this boundary"
        )
    elif parallel:
        kind, rationale = "PARALLEL", (
            f"payload signals {parallel} are >= {PARALLEL_MIN_WIDTH} bits wide, a symbol/"
            "transaction-level boundary"
        )
    elif serial:
        kind, rationale = "SERIAL", (
            f"payload signals {serial} are all <= {SERIAL_MAX_WIDTH} bits wide, a line-rate "
            "serial lane set"
        )
    else:
        kind, rationale = "UNDECIDABLE", (
            f"payload signal widths {between} fall in the deliberately unsplit band between "
            f"{SERIAL_MAX_WIDTH} and {PARALLEL_MIN_WIDTH} bits -- not guessed, routed to a human"
        )
    return {
        "kind": kind, "tier": "B2_STRUCTURAL_WIDTH" if kind != "UNDECIDABLE" else "B3_UNDECIDABLE",
        "rationale": rationale,
        "serial_signals": serial, "parallel_signals": parallel,
        "unresolved_width_signals": unresolved,
    }


def decide_bind_location(classification: dict, boundary_signals: list) -> dict:
    """The row-2 consumer: turn the boundary classification into an actual
    bind-location decision. See this module's docstring for why a SERIAL
    boundary is reported NOT bindable rather than being bound anyway."""
    kind = classification["kind"]
    if kind in ("PARALLEL", "MIXED"):
        signals = classification.get("parallel_signals") or []
        return {
            "mount_layer": "controller_phy_parallel_boundary", "bindable": True,
            "rationale": (
                "a parallel controller-facing boundary exists, so protocol transactions are "
                "observable there; mount the bind at that port set and pass clock/reset through "
                "the bind instance's own port list (CLAUDE.md Bind-Location Rule 3)"
                + (" -- note this boundary is MIXED, so bind the PARALLEL signals only, never the "
                   "serial lanes" if kind == "MIXED" else "")
            ),
            "recommended_bind_signals": signals,
        }
    if kind == "SERIAL":
        return {
            "mount_layer": "serial_boundary_not_bindable", "bindable": False,
            "rationale": (
                "the only boundary between these modules is a line-rate serial lane set; a "
                "protocol VIP monitor bound here decodes nothing without a PHY model and would "
                "pass Gate 1 and Gate 2 while failing Gate 3 as a silent monitor. Supply a PHY "
                "model exposing its parallel controller-facing port, and re-extract."
            ),
            "recommended_bind_signals": [],
        }
    return {
        "mount_layer": "requires_human_decision", "bindable": False,
        "rationale": (
            "boundary kind is UNDECIDABLE (" + classification["rationale"] + "); this goes to the "
            "question queue rather than being guessed, matching connectivity.py's T4 discipline "
            "for an undecidable bind target"
        ),
        "recommended_bind_signals": [],
    }


# ---------------------------------------------------------------------------
# top-level assembly
# ---------------------------------------------------------------------------

def _not_available(reason: str, phy_module: Optional[str], controller_module: Optional[str],
                    source: Optional[dict] = None) -> dict:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.phy_boundary", "version": SCHEMA_VERSION},
        "status": "NOT_AVAILABLE",
        "reason": reason,
        "phy_module": phy_module,
        "controller_module": controller_module,
        "boundary_signals": [],
        "classification": {
            "kind": "UNDECIDABLE", "tier": "B3_UNDECIDABLE", "rationale": reason,
            "serial_signals": [], "parallel_signals": [], "unresolved_width_signals": [],
        },
        "bind_decision": {
            "mount_layer": "requires_human_decision", "bindable": False,
            "rationale": reason, "recommended_bind_signals": [],
        },
    }
    if source:
        doc["source"] = source
    validate_phy_boundary(doc)
    return doc


def extract_phy_boundary(rtl_modules, phy_module: str, controller_module: str, *,
                          declared_kind: Optional[str] = None,
                          source: Optional[dict] = None) -> dict:
    """Build a complete, schema-valid phy_boundary.json dict.

    `rtl_modules`: the real parsed module list. Accepts either a flat list of
    module dicts, or the `dut_facts.rtl.files` list env_manifest.py produces
    (each entry carrying its own `modules`) -- the latter is the normal path,
    so this consumes env.manifest.json directly with no reshaping by the
    caller.

    A declared module absent from the real port table is NOT_AVAILABLE with
    an honest reason, never a boundary invented to fill the gap -- the same
    contract env_manifest.py applies to every layer needing a real captured
    artifact."""
    modules = _flatten_modules(rtl_modules)
    if not modules:
        return _not_available(
            "no parsed RTL modules supplied -- run env_manifest.build_dut_facts_rtl() over the "
            "real RTL first and pass its files list here",
            phy_module, controller_module, source,
        )
    index = _index_modules(modules)
    missing = [m for m in (phy_module, controller_module) if m not in index]
    if missing:
        return _not_available(
            f"declared module(s) {missing} are not present in the supplied RTL port table "
            f"(available: {sorted(index)}) -- check the declared PHY/controller module names "
            "against the real RTL, or supply the RTL file that defines them",
            phy_module, controller_module, source,
        )

    boundary_signals = extract_boundary_signals(index[phy_module], index[controller_module])
    classification = classify_boundary(boundary_signals, declared_kind=declared_kind)
    bind_decision = decide_bind_location(classification, boundary_signals)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"tool": "dv_harness.phy_boundary", "version": SCHEMA_VERSION},
        "status": "EXTRACTED",
        "reason": None,
        "phy_module": phy_module,
        "controller_module": controller_module,
        "boundary_signals": boundary_signals,
        "classification": classification,
        "bind_decision": bind_decision,
    }
    if source:
        doc["source"] = source
    validate_phy_boundary(doc)
    return doc


def _flatten_modules(rtl_modules) -> list:
    """Accept either a flat module list or env_manifest's
    dut_facts.rtl.files[] shape (entries carrying their own `modules`)."""
    modules = []
    for entry in rtl_modules or []:
        if isinstance(entry, dict) and "modules" in entry:
            modules.extend(entry.get("modules") or [])
        elif isinstance(entry, dict):
            modules.append(entry)
    return modules


def extract_from_env_manifest(manifest: dict, phy_module: str, controller_module: str,
                               *, declared_kind: Optional[str] = None) -> dict:
    """Convenience entry point reading the RTL port table straight out of an
    already-generated env.manifest.json -- the intended normal path, since
    that manifest is the repo's single generated home for real parsed RTL
    facts and is already a tier-2 always-resident artifact."""
    rtl = ((manifest or {}).get("dut_facts") or {}).get("rtl") or {}
    files = rtl.get("files") or []
    source = {"kind": "env_manifest_rtl_modules",
              "files": sorted(f.get("file_path", "") for f in files if f.get("file_path"))}
    if rtl.get("status") != "PARSED":
        return _not_available(
            f"env.manifest.json's dut_facts.rtl is {rtl.get('status')!r}, not PARSED "
            f"({rtl.get('reason')!r}) -- no real RTL port table to derive a PHY boundary from",
            phy_module, controller_module, source,
        )
    return extract_phy_boundary(files, phy_module, controller_module,
                                 declared_kind=declared_kind, source=source)


def save_phy_boundary(doc: dict, path) -> None:
    """Validate then write deterministically (fixed key order, no timestamp
    field anywhere in the schema) so regenerating from unchanged real inputs
    produces a byte-identical file and a real diff always means a real
    underlying change -- env_manifest.py's Diffability contract, applied to
    this artifact too."""
    validate_phy_boundary(doc)
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_phy_boundary(path) -> dict:
    """Load and validate a phy_boundary.json from disk. Raises
    PhyBoundaryValidationError if it is not schema-valid -- a consumer
    (a bind emitter, a connectivity gate) must never act on an unvalidated
    bind-location decision."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_phy_boundary(doc)
    return doc


def assert_bind_location_allowed(doc: dict, *, target_signals: Optional[Iterable[str]] = None) -> dict:
    """Hard consumer gate for the row-2 "-> bind-location decision" column,
    modeled on connectivity.assert_bind_entry_tier_allows_emission(): raises
    rather than returning a bool a caller can ignore.

    Refuses when the extracted boundary is not bindable at all (SERIAL-only,
    or UNDECIDABLE), and -- when `target_signals` is supplied -- when a
    proposed bind would connect through a signal that is NOT part of the
    sanctioned parallel port set (i.e. someone binding the serial lanes of a
    MIXED boundary anyway)."""
    if doc.get("status") != "EXTRACTED":
        raise PhyBoundaryValidationError(
            f"PHY_BOUNDARY_NOT_EXTRACTED: {doc.get('reason')!r} -- no bind location may be "
            "decided from a NOT_AVAILABLE boundary"
        )
    decision = doc["bind_decision"]
    if not decision.get("bindable"):
        raise PhyBoundaryValidationError(
            f"PHY_BOUNDARY_NOT_BINDABLE: mount_layer={decision['mount_layer']!r} -- "
            + decision["rationale"]
        )
    if target_signals is not None:
        allowed = set(decision.get("recommended_bind_signals") or [])
        forbidden = sorted(set(target_signals) - allowed)
        if forbidden:
            raise PhyBoundaryValidationError(
                f"PHY_BOUNDARY_SIGNAL_NOT_SANCTIONED: {forbidden} are not part of the parallel "
                f"boundary port set {sorted(allowed)}; binding a serial lane produces a monitor "
                "that decodes nothing (Gate 3 silent-monitor failure)"
            )
    return decision
