"""dv_harness/amba_scoreboard_env.py -- AMBA-21: inspect a user-supplied UVM
scoreboard / reference environment WITHOUT MODIFYING IT, and map each proposed
VIP monitor to the real scoreboard ingress it would have to feed.

WHY THIS IS A SEPARATE MODULE FROM amba_fabric_discovery.py
-----------------------------------------------------------
Every other AMBA-1..20 step answers a question about RTL: a port set, a net
graph, an elaborated instance tree. AMBA-21 is the only step that reads
SYSTEMVERILOG CLASS SOURCE -- an existing testbench's scoreboards, predictors,
reference models and transaction types -- which is a different parser, a
different corpus, and a different failure mode (an encrypted or generated file
that must degrade rather than raise). Mixing it into the netlist module would
put a class scanner behind a `FabricNetlist` that has nothing to do with it.

WHAT IT REUSES RATHER THAN REBUILDS
-----------------------------------
  * `vip_symbol_index.index_source_text()` / `iter_source_files()` are the ONLY
    SystemVerilog class scanner used here. That module already guarantees the
    property AMBA-21 needs most -- it retains DECLARATIONS AND LOCATIONS ONLY,
    never a method body (`assert_no_bodies_retained()`) -- so "inspect, do not
    modify, do not absorb" is structural rather than promised. Its analysis-port
    capture (`uvm_analysis_port`/`_export`/`_imp*`/`uvm_tlm_analysis_fifo`) was
    added for exactly this consumer.
  * `connectivity.BindTier` is the ONLY confidence vocabulary. A role read off a
    real `extends` chain is T2_STRUCTURAL_MATCH; one resting on a class or
    member NAME is T3_NAMING_HEURISTIC and can never be auto-accepted; nothing
    established is T4_UNDECIDABLE. No second confidence scale is introduced.
  * `connectivity.SCOREBOARD_PLAN_FIELDS`' vocabulary (`ordering`,
    `ordering_tolerance_depth`, ...) names the assumption fields, so the
    DISCOVERED assumptions of an existing scoreboard and the PLANNED fields of a
    to-be-built one speak the same words instead of two dialects.
  * `connectivity.REQUIRED_HUMAN_INPUT` is the sentinel for every assumption a
    declaration-level scan genuinely cannot settle.

THE HONEST LIMIT, STATED UP FRONT
---------------------------------
A declaration-level scan can find WHERE transactions enter a scoreboard and
WHAT TYPE they are. It cannot read an ordering rule, an outstanding-transaction
limit or an address-map assumption, because those live in method bodies this
module deliberately never retains. So every assumption field below reports
`REQUIRED_HUMAN_INPUT` together with the CANDIDATE DECLARATIONS that bear on it
(cited file:line, for a targeted read) rather than a guessed value. AMBA-21 asks
for these to be "identified"; identifying where the answer lives and refusing to
invent the answer is the only honest reading of that for a static scan.

DISCOVERY ONLY (AMBA-30 / AMBA-31)
----------------------------------
Nothing here writes to the inspected environment. `assert_sources_unmodified()`
makes that checkable rather than asserted: every inspected file's sha256 is
recorded at scan time and re-verified on demand. No `bind` statement, no UVM
source and no connection code is emitted anywhere in this module.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dv_harness import vip_symbol_index
from dv_harness.connectivity import (
    AMBA4_DISPLAY_NAMES,
    AMBA4_PROTOCOLS,
    AMBA_PROTOCOL_UNRESOLVED,
    ConnectivityError,
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    REQUIRED_HUMAN_INPUT,
    ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS,
    BindTier,
    render_markdown_table,
)


class ScoreboardEnvError(ConnectivityError):
    """A scoreboard-environment root that does not exist, or a read-only
    violation detected after the fact. Subclasses `ConnectivityError` so a
    caller already handling this pipeline's errors handles these too."""


# ===========================================================================
# Class roles inside a reference environment
# ===========================================================================

ENV_ROLE_TRANSACTION = "TRANSACTION_CLASS"
ENV_ROLE_SCOREBOARD = "SCOREBOARD"
ENV_ROLE_SUBSCRIBER = "SUBSCRIBER"
ENV_ROLE_PREDICTOR = "PREDICTOR"
ENV_ROLE_REFERENCE_MODEL = "REFERENCE_MODEL"
ENV_ROLE_ADAPTER = "ADAPTER"
ENV_ROLE_UNCLASSIFIED = "UNCLASSIFIED"

ENV_ROLE_VALUES: tuple = (
    ENV_ROLE_TRANSACTION, ENV_ROLE_SCOREBOARD, ENV_ROLE_SUBSCRIBER,
    ENV_ROLE_PREDICTOR, ENV_ROLE_REFERENCE_MODEL, ENV_ROLE_ADAPTER,
    ENV_ROLE_UNCLASSIFIED,
)

#: UVM base class -> the role deriving from it is a STRUCTURAL fact (T2): the
#: source really says `extends uvm_scoreboard`. Resolved transitively, so a
#: project's own `my_env_scoreboard_base` between the class and `uvm_scoreboard`
#: does not downgrade its children to a naming guess.
STRUCTURAL_ROLE_BY_BASE_CLASS: dict = {
    "uvm_scoreboard": ENV_ROLE_SCOREBOARD,
    "uvm_subscriber": ENV_ROLE_SUBSCRIBER,
    "uvm_reg_predictor": ENV_ROLE_PREDICTOR,
    "uvm_reg_adapter": ENV_ROLE_ADAPTER,
    "uvm_sequence_item": ENV_ROLE_TRANSACTION,
    "uvm_transaction": ENV_ROLE_TRANSACTION,
}

#: Name token -> role. ALWAYS T3: a class called `axi_predictor` that extends
#: `uvm_component` is a predictor by convention only, and Part C's tier rule
#: ("T3 ALWAYS requires human confirmation, NEVER auto-accepted") applies to
#: this exactly as it does to a bind candidate.
NAMING_ROLE_HINTS: tuple = (
    ("reference_model", ENV_ROLE_REFERENCE_MODEL),
    ("ref_model", ENV_ROLE_REFERENCE_MODEL),
    ("refmodel", ENV_ROLE_REFERENCE_MODEL),
    ("golden_model", ENV_ROLE_REFERENCE_MODEL),
    ("predictor", ENV_ROLE_PREDICTOR),
    ("scoreboard", ENV_ROLE_SCOREBOARD),
    ("adapter", ENV_ROLE_ADAPTER),
    ("subscriber", ENV_ROLE_SUBSCRIBER),
    ("transaction", ENV_ROLE_TRANSACTION),
    ("seq_item", ENV_ROLE_TRANSACTION),
)

#: How far `extends` is followed before giving up. A cyclic or pathological
#: inheritance chain must terminate as UNCLASSIFIED, never hang.
MAX_BASE_CLASS_HOPS = 16


def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^A-Za-z0-9]+", str(text or "").lower()) if t}


def _resolve_structural_role(class_name: str, by_name: dict) -> Optional[tuple]:
    """Walk the real `extends` chain to the first UVM base class that decides a
    role. Returns `(role, chain)` or None. `chain` is the actual class names
    walked, so the evidence a caller reports is the inheritance path, not the
    word "structural"."""
    chain, seen, current = [], set(), class_name
    for _ in range(MAX_BASE_CLASS_HOPS):
        entry = by_name.get(current)
        base = (entry or {}).get("base_class")
        if not base:
            return None
        chain.append(f"{current} extends {base}")
        if base in STRUCTURAL_ROLE_BY_BASE_CLASS:
            return STRUCTURAL_ROLE_BY_BASE_CLASS[base], chain
        if base in seen:
            return None
        seen.add(base)
        current = base
    return None


def classify_env_class(entry: dict, by_name: dict) -> dict:
    """One reference-environment class's role, with the tier its evidence
    supports. Structural inheritance outranks a name, exactly as
    `classify_bind_tier()` ranks T2 over T3 -- a class both named
    `*_scoreboard` and extending `uvm_scoreboard` is T2, never a blend."""
    structural = _resolve_structural_role(entry["name"], by_name)
    if structural is not None:
        role, chain = structural
        return {"role": role, "tier": BindTier.T2_STRUCTURAL_MATCH.value,
                "evidence": " -> ".join(chain)}
    lowered = entry["name"].lower()
    for token, role in NAMING_ROLE_HINTS:
        if token in lowered:
            return {"role": role, "tier": BindTier.T3_NAMING_HEURISTIC.value,
                    "evidence": f"class name contains {token!r}; no `extends` chain reaches a "
                                "UVM base class that would settle this structurally"}
    return {"role": ENV_ROLE_UNCLASSIFIED, "tier": BindTier.T4_UNDECIDABLE.value,
            "evidence": f"neither an `extends` chain nor a name token settles the role of "
                        f"{entry['name']}"}


# ===========================================================================
# Protocol / endpoint hints read off declared names and types
# ===========================================================================

#: Longest-first, so `axi4_lite` is recognised before `axi4` and `apb4` before
#: `apb`. Both the registry key and the doc's display spelling are accepted,
#: since a real testbench writes either.
_PROTOCOL_NEEDLES: tuple = tuple(sorted(
    {(needle.lower(), key)
     for key in AMBA4_PROTOCOLS
     for needle in (key, AMBA4_DISPLAY_NAMES[key].replace("-", "_"))},
    key=lambda pair: (-len(pair[0]), pair[0])))

_ENDPOINT_NEEDLES: tuple = (
    ("initiator", EXTERNAL_ENDPOINT_MASTER),
    ("master", EXTERNAL_ENDPOINT_MASTER),
    ("mst", EXTERNAL_ENDPOINT_MASTER),
    ("subordinate", EXTERNAL_ENDPOINT_SLAVE),
    ("target", EXTERNAL_ENDPOINT_SLAVE),
    ("slave", EXTERNAL_ENDPOINT_SLAVE),
    ("slv", EXTERNAL_ENDPOINT_SLAVE),
)


def protocol_hint(*texts) -> str:
    """The AMBA4 protocol a declared name/type suggests, or
    `AMBA_PROTOCOL_UNRESOLVED`.

    A HINT, never a classification: `connectivity.classify_amba_protocol()` is
    this repo's only protocol verdict and it needs a signal set, which a
    scoreboard's class source does not have. Two different protocols suggested
    by two of the supplied texts resolve to UNRESOLVED rather than to whichever
    came first."""
    found = set()
    for text in texts:
        blob = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower())
        for needle, key in _PROTOCOL_NEEDLES:
            if needle in blob:
                found.add(key)
                break
    return found.pop() if len(found) == 1 else AMBA_PROTOCOL_UNRESOLVED


def endpoint_hint(*texts) -> str:
    """MASTER_ENDPOINT / SLAVE_ENDPOINT suggested by a declared name, or the
    unresolved sentinel. Same rule: a text suggesting both settles nothing."""
    found = set()
    for text in texts:
        toks = _tokens(text)
        # Every matching token, not the first: `master_slave_export` names both
        # perspectives and must settle nothing. Stopping at the first match
        # would silently report it as a master ingress.
        found |= {role for needle, role in _ENDPOINT_NEEDLES if needle in toks}
    return found.pop() if len(found) == 1 else ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS


# ===========================================================================
# The discovered assumptions (AMBA-21's own list)
# ===========================================================================

#: AMBA-21's assumption categories. The first four names are deliberately the
#: vocabulary `connectivity.SCOREBOARD_PLAN_FIELDS` already uses for a
#: to-be-built scoreboard's plan, so the discovered and the planned artifact
#: can be read side by side.
SCOREBOARD_ASSUMPTION_FIELDS: tuple = (
    "address_map_assumptions",
    "ordering",
    "ordering_tolerance_depth",
    "outstanding_transactions",
    "protocol_specific_assumptions",
)

#: Declaration name tokens that would BEAR ON each assumption. Matching one does
#: not answer the assumption -- it cites a place a human can read the answer.
_ASSUMPTION_TOKENS: dict = {
    "address_map_assumptions": {"addr", "address", "base", "map", "region",
                                "decode", "decoder", "range", "aperture"},
    "ordering": {"order", "ordered", "inorder", "ooo", "reorder", "reordering",
                 "sequential", "strict"},
    "ordering_tolerance_depth": {"depth", "window", "tolerance", "slack", "skew"},
    "outstanding_transactions": {"outstanding", "pending", "inflight", "credit",
                                 "credits", "queue", "fifo", "max"},
    "protocol_specific_assumptions": {"burst", "exclusive", "atomic", "cache",
                                      "prot", "strb", "resp", "lock", "qos",
                                      "narrow", "wrap", "incr"},
}


def _assumption_candidates(entry: dict) -> dict:
    """Every declared field/analysis port of one class, bucketed by which
    AMBA-21 assumption it bears on. Cited by file:line for a targeted read."""
    out = {k: [] for k in SCOREBOARD_ASSUMPTION_FIELDS}
    decls = [(f["name"], f.get("data_type"), f["file"], f["line"])
             for f in entry.get("config_fields", [])]
    decls += [(p["name"], p.get("port_type"), p["file"], p["line"])
              for p in entry.get("analysis_ports", [])]
    for name, dtype, file, line in decls:
        toks = _tokens(name) | _tokens(dtype)
        for field_key, needles in _ASSUMPTION_TOKENS.items():
            if toks & needles:
                out[field_key].append({"declaration": name, "data_type": dtype,
                                       "file": file, "line": line})
    return out


def build_assumptions(entry: dict) -> dict:
    """AMBA-21's assumption block for one scoreboard/reference class.

    Every value is `REQUIRED_HUMAN_INPUT` BY CONSTRUCTION. An ordering rule or
    an outstanding-transaction limit lives in a method body, and this module
    never retains one -- so the honest output is "here are the declarations that
    bear on it, at these file:lines" plus an explicit unanswered marker, not a
    value inferred from a field name."""
    candidates = _assumption_candidates(entry)
    return {
        key: {
            "value": REQUIRED_HUMAN_INPUT,
            "candidate_declarations": candidates[key],
            "why_unanswered": "a declaration-level scan retains no method body, so this "
                              "assumption cannot be read statically; the cited declarations "
                              "are where to look",
        }
        for key in SCOREBOARD_ASSUMPTION_FIELDS
    }


# ===========================================================================
# Ingress points
# ===========================================================================

INGRESS_KIND_EXPORT = "ANALYSIS_EXPORT"
INGRESS_KIND_IMP = "ANALYSIS_IMP"
INGRESS_KIND_FIFO = "ANALYSIS_FIFO"
#: A `uvm_subscriber` gets an `analysis_export` from the UVM class library
#: itself; it is never declared in the subclass's own source. Recorded as a real
#: ingress with that as its evidence, because a monitor genuinely can connect to
#: it and omitting it would make a whole class of scoreboard look ingress-less.
INGRESS_KIND_IMPLICIT_SUBSCRIBER = "IMPLICIT_SUBSCRIBER_EXPORT"

INGRESS_KINDS: tuple = (INGRESS_KIND_EXPORT, INGRESS_KIND_IMP, INGRESS_KIND_FIFO,
                        INGRESS_KIND_IMPLICIT_SUBSCRIBER)

#: Roles whose ingress a fabric VIP monitor could legitimately feed.
INGRESS_BEARING_ROLES: frozenset = frozenset({
    ENV_ROLE_SCOREBOARD, ENV_ROLE_SUBSCRIBER, ENV_ROLE_PREDICTOR,
    ENV_ROLE_REFERENCE_MODEL,
})


@dataclass
class ScoreboardIngress:
    """One place a transaction can really enter the existing environment."""
    ingress_id: str
    component_class: str
    component_role: str
    component_role_tier: str
    member: str
    port_type: str
    kind: str
    transaction_type: Optional[str]
    array_dimension: Optional[str]
    file: str
    line: int
    protocol_hint: str
    endpoint_hint: str
    evidence: str

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict:
        return {
            "ingress_id": self.ingress_id, "component_class": self.component_class,
            "component_role": self.component_role,
            "component_role_tier": self.component_role_tier,
            "member": self.member, "port_type": self.port_type, "kind": self.kind,
            "transaction_type": self.transaction_type,
            "array_dimension": self.array_dimension,
            "file": self.file, "line": self.line,
            "protocol_hint": self.protocol_hint, "endpoint_hint": self.endpoint_hint,
            "evidence": self.evidence,
        }


@dataclass
class InspectedFile:
    """One file this module read, and the digest proving it was not changed."""
    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


@dataclass
class ScoreboardEnvAnalysis:
    """AMBA-21's complete read-only result for one reference environment."""
    roots: list
    files: list                      # list[InspectedFile]
    classes: list                    # list[dict], vip_symbol_index class entries
    roles: dict                      # class name -> {role, tier, evidence}
    ingress: list                    # list[ScoreboardIngress]
    assumptions: dict                # class name -> assumption block
    transaction_classes: list        # list[str]

    def classes_with_role(self, role: str) -> list:
        return [c["name"] for c in self.classes if self.roles[c["name"]]["role"] == role]

    @property
    def scoreboard_classes(self) -> list:
        return self.classes_with_role(ENV_ROLE_SCOREBOARD)

    def ingress_by_id(self, ingress_id: str) -> Optional[ScoreboardIngress]:
        return next((i for i in self.ingress if i.ingress_id == ingress_id), None)

    def to_dict(self) -> dict:
        return {
            "roots": list(self.roots),
            "inspected_files": [f.to_dict() for f in self.files],
            "classes": [{"name": c["name"], "base_class": c.get("base_class"),
                         "file": c["file"], "line": c["line"],
                         **self.roles[c["name"]]} for c in self.classes],
            "transaction_classes": list(self.transaction_classes),
            "scoreboard_ingress": [i.to_dict() for i in self.ingress],
            "assumptions": self.assumptions,
        }


def _sha256(path: Path) -> tuple:
    blob = path.read_bytes()
    return hashlib.sha256(blob).hexdigest(), len(blob)


def _ingress_id(component_class: str, member: str) -> str:
    return f"{component_class}.{member}"


def analyze_scoreboard_environment(roots, *, relative_to=None) -> ScoreboardEnvAnalysis:
    """AMBA-21's inspection pass over a user-supplied scoreboard / reference
    environment. Reads; never writes.

    `roots` are directories or files of SystemVerilog class source. A root that
    does not exist raises (via `vip_symbol_index.iter_source_files()`), because
    a mistyped path must never be indistinguishable from an environment that
    genuinely has no scoreboard in it -- the second is a finding, the first is
    an operator error."""
    try:
        files = vip_symbol_index.iter_source_files(roots)
    except vip_symbol_index.VipSymbolIndexError as exc:
        raise ScoreboardEnvError("SCOREBOARD_ENV_ROOT_NOT_FOUND", {
            "roots": [str(r) for r in roots], "detail": str(exc)}) from exc

    base = Path(relative_to) if relative_to else None
    inspected, classes = [], []
    for path in files:
        digest, size = _sha256(path)
        label = vip_symbol_index._relativize(path, base)
        inspected.append(InspectedFile(path=str(path).replace("\\", "/"),
                                       sha256=digest, bytes=size))
        classes.extend(vip_symbol_index.index_source_text(
            path.read_text(encoding="utf-8", errors="replace"), label))
    classes.sort(key=lambda c: (c["file"], c["line"]))

    # The no-body invariant is asserted on the scanned result too, not only
    # inside vip_symbol_index's own save path -- this module never writes an
    # index file, so that assertion would otherwise never run here.
    vip_symbol_index.assert_no_bodies_retained({"classes": classes})

    by_name = {c["name"]: c for c in classes}
    roles = {c["name"]: classify_env_class(c, by_name) for c in classes}
    ingress = _discover_ingress(classes, roles)
    assumptions = {c["name"]: build_assumptions(c) for c in classes
                   if roles[c["name"]]["role"] in INGRESS_BEARING_ROLES}
    transactions = [c["name"] for c in classes
                    if roles[c["name"]]["role"] == ENV_ROLE_TRANSACTION]
    return ScoreboardEnvAnalysis(
        roots=[str(r) for r in roots], files=inspected, classes=classes, roles=roles,
        ingress=ingress, assumptions=assumptions, transaction_classes=transactions)


def _discover_ingress(classes, roles) -> list:
    """Every declared analysis EXPORT/IMP/FIFO on an ingress-bearing class, plus
    the implicit export a `uvm_subscriber` inherits.

    An `analysis_port` is deliberately excluded: it SENDS, so connecting a VIP
    monitor to one would be backwards, and listing it as a candidate ingress is
    how a reviewer ends up approving a connection that can never carry a
    transaction."""
    out: list = []
    for entry in classes:
        role_info = roles[entry["name"]]
        if role_info["role"] not in INGRESS_BEARING_ROLES:
            continue
        declared = [p for p in entry.get("analysis_ports", [])
                    if p.get("direction") == "INGRESS"]
        for port in declared:
            out.append(ScoreboardIngress(
                ingress_id=_ingress_id(entry["name"], port["name"]),
                component_class=entry["name"],
                component_role=role_info["role"],
                component_role_tier=role_info["tier"],
                member=port["name"], port_type=port["port_type"], kind=port["kind"],
                transaction_type=port.get("transaction_type"),
                array_dimension=port.get("array_dimension"),
                file=port["file"], line=port["line"],
                protocol_hint=protocol_hint(port["name"], port.get("transaction_type"),
                                            entry["name"]),
                endpoint_hint=endpoint_hint(port["name"], port.get("transaction_type")),
                evidence=f"declared {port['port_type']} at {port['file']}:{port['line']}"))
        if role_info["role"] == ENV_ROLE_SUBSCRIBER and not declared:
            out.append(ScoreboardIngress(
                ingress_id=_ingress_id(entry["name"], "analysis_export"),
                component_class=entry["name"],
                component_role=role_info["role"],
                component_role_tier=role_info["tier"],
                member="analysis_export", port_type="uvm_analysis_export",
                kind=INGRESS_KIND_IMPLICIT_SUBSCRIBER,
                transaction_type=None, array_dimension=None,
                file=entry["file"], line=entry["line"],
                protocol_hint=protocol_hint(entry["name"]),
                endpoint_hint=endpoint_hint(entry["name"]),
                evidence="uvm_subscriber supplies `analysis_export` from the UVM class "
                         "library; it is not declared in this class's own source"))
    return out


def assert_sources_unmodified(analysis: ScoreboardEnvAnalysis) -> None:
    """AMBA-21's "Do not modify during discovery phase", as a CHECKABLE
    property rather than a promise.

    Re-reads every inspected file and compares its sha256 against the digest
    recorded at scan time. A file that moved, vanished or changed raises. Call
    it at the end of a discovery run: it turns "we did not touch the user's
    scoreboard" from something a reviewer has to trust into something the
    report can cite."""
    for item in analysis.files:
        path = Path(item.path)
        if not path.exists():
            raise ScoreboardEnvError("SCOREBOARD_SOURCE_DISAPPEARED_DURING_DISCOVERY", {
                "path": item.path,
                "hint": "AMBA-21 is read-only; a file inspected at the start of discovery "
                        "must still be there at the end"})
        digest, _ = _sha256(path)
        if digest != item.sha256:
            raise ScoreboardEnvError("SCOREBOARD_SOURCE_MODIFIED_DURING_DISCOVERY", {
                "path": item.path, "sha256_at_scan": item.sha256, "sha256_now": digest,
                "hint": "AMBA-21 forbids modifying the reference environment during "
                        "discovery; a change here means something wrote to it"})


# ===========================================================================
# Mapping a proposed VIP monitor to a real scoreboard ingress
# ===========================================================================

INGRESS_MAP_MATCHED = "INGRESS_MATCHED"
#: Several ingress points fit and nothing in the evidence separates them. NOT
#: resolved by picking the first: the same rule AMBA-12/13 apply to a
#: multiple-source trace applies here, for the same reason.
INGRESS_MAP_AMBIGUOUS = "INGRESS_AMBIGUOUS_MULTIPLE_CANDIDATES"
INGRESS_MAP_NOT_FOUND = "INGRESS_NOT_FOUND"
INGRESS_MAP_NO_ENVIRONMENT = "NO_SCOREBOARD_ENVIRONMENT_SUPPLIED"

INGRESS_MAP_STATUSES: tuple = (INGRESS_MAP_MATCHED, INGRESS_MAP_AMBIGUOUS,
                               INGRESS_MAP_NOT_FOUND, INGRESS_MAP_NO_ENVIRONMENT)

ADAPTATION_NONE = "NONE_IDENTIFIED"
ADAPTATION_UNTYPED_INGRESS = "INGRESS_TRANSACTION_TYPE_UNDECLARED"
ADAPTATION_PROTOCOL_UNCONFIRMED = "INGRESS_PROTOCOL_UNCONFIRMED_HUMAN_MUST_VERIFY"
ADAPTATION_NEW_INGRESS_REQUIRED = "NEW_SCOREBOARD_INGRESS_REQUIRED"
ADAPTATION_HUMAN_CHOICE = "HUMAN_MUST_CHOOSE_AMONG_CANDIDATE_INGRESS"
ADAPTATION_NO_ENVIRONMENT = "SUPPLY_THE_REFERENCE_ENVIRONMENT_OR_PLAN_A_NEW_SCOREBOARD"

AMBA21_INGRESS_MAP_COLUMNS: tuple = (
    ("vip_id", "VIP_ID"),
    ("protocol", "Protocol"),
    ("bind_hierarchy", "Proposed VIP Bind Hierarchy"),
    ("endpoint_role", "Observed Endpoint Role"),
    ("scoreboard_channel", "Scoreboard Ingress"),
    ("ingress_transaction_type", "Ingress Transaction Type"),
    ("match_evidence", "Match Evidence"),
    ("status", "Status"),
    ("required_adaptation", "Required Adaptation"),
)

_DISPLAY_TO_PROTOCOL: dict = {v: k for k, v in AMBA4_DISPLAY_NAMES.items()}


def protocol_key(value: str) -> str:
    """"AXI4-Lite" (a rendered table cell) -> "AXI4_LITE" (the registry key).
    A value already in key form passes through, so a caller need not know which
    spelling the row it holds happens to carry."""
    text = str(value or "")
    if text in AMBA4_DISPLAY_NAMES:
        return text
    return _DISPLAY_TO_PROTOCOL.get(text, text)


def map_vip_monitors_to_scoreboard_ingress(vip_plan, analysis: Optional[ScoreboardEnvAnalysis]
                                           ) -> list:
    """AMBA-21's "Map each proposed VIP monitor to the proper scoreboard
    ingress. Report mismatches and required adaptation."

    One row per planned VIP, always -- a VIP with no ingress is the finding, and
    dropping it from the table is what would hide it. Candidate narrowing is
    protocol first, then the master/slave endpoint hint; if more than one
    survives, the row is AMBIGUOUS and NAMES every candidate rather than
    choosing. `analysis=None` (no reference environment supplied at all) is a
    distinct, honestly-reported state, not an empty match."""
    rows: list = []
    for vip in vip_plan or ():
        protocol = protocol_key(vip.get("protocol"))
        endpoint = vip.get("observed_endpoint_role") or \
            ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS
        base = {
            "vip_id": vip.get("vip_id"),
            "protocol": vip.get("protocol"),
            "bind_hierarchy": vip.get("bind_hierarchy"),
            "endpoint_role": endpoint,
            "row_id": vip.get("vip_id"),
        }
        if analysis is None:
            rows.append({**base, "scoreboard_channel": REQUIRED_HUMAN_INPUT,
                         "ingress_transaction_type": REQUIRED_HUMAN_INPUT,
                         "match_evidence": "no reference environment was supplied to AMBA-21",
                         "status": INGRESS_MAP_NO_ENVIRONMENT,
                         "required_adaptation": ADAPTATION_NO_ENVIRONMENT,
                         "candidate_ingress_ids": []})
            continue
        candidates = _narrow_candidates(analysis.ingress, protocol, endpoint)
        rows.append({**base, **_map_cells(candidates, protocol)})
    return rows


def _narrow_candidates(ingress, protocol: str, endpoint: str) -> list:
    """Protocol first, then endpoint. An ingress whose protocol hint is
    UNRESOLVED stays a candidate at the protocol step -- it is unknown, not
    known-different, and eliminating it would silently rule out the untyped
    generic export most real scoreboards actually have."""
    pool = [i for i in ingress
            if i.protocol_hint in (protocol, AMBA_PROTOCOL_UNRESOLVED)]
    if len(pool) <= 1 or endpoint == ROLE_UNRESOLVED_REQUIRES_STRUCTURAL_ANALYSIS:
        return pool
    narrowed = [i for i in pool if i.endpoint_hint == endpoint]
    return narrowed or pool


def _map_cells(candidates, protocol: str) -> dict:
    if not candidates:
        return {"scoreboard_channel": REQUIRED_HUMAN_INPUT,
                "ingress_transaction_type": REQUIRED_HUMAN_INPUT,
                "match_evidence": "no analysis export/imp/fifo in the supplied environment "
                                  f"accepts a {protocol} transaction",
                "status": INGRESS_MAP_NOT_FOUND,
                "required_adaptation": ADAPTATION_NEW_INGRESS_REQUIRED,
                "candidate_ingress_ids": []}
    if len(candidates) > 1:
        return {"scoreboard_channel": REQUIRED_HUMAN_INPUT,
                "ingress_transaction_type": REQUIRED_HUMAN_INPUT,
                "match_evidence": "; ".join(f"{c.ingress_id} @ {c.location}"
                                            for c in candidates),
                "status": INGRESS_MAP_AMBIGUOUS,
                "required_adaptation": ADAPTATION_HUMAN_CHOICE,
                "candidate_ingress_ids": [c.ingress_id for c in candidates]}
    only = candidates[0]
    if only.transaction_type is None:
        adaptation = ADAPTATION_UNTYPED_INGRESS
    elif only.protocol_hint == AMBA_PROTOCOL_UNRESOLVED:
        adaptation = ADAPTATION_PROTOCOL_UNCONFIRMED
    else:
        adaptation = ADAPTATION_NONE
    return {"scoreboard_channel": only.ingress_id,
            "ingress_transaction_type": only.transaction_type or REQUIRED_HUMAN_INPUT,
            "match_evidence": f"{only.evidence}; component role {only.component_role} "
                              f"[{only.component_role_tier}]",
            "status": INGRESS_MAP_MATCHED,
            "required_adaptation": adaptation,
            "candidate_ingress_ids": [only.ingress_id]}


def scoreboard_channel_by_vip_id(mapping) -> dict:
    """`vip_id -> scoreboard_channel`, for AMBA-22's registry column. An
    unmatched or ambiguous VIP maps to `REQUIRED_HUMAN_INPUT`, which is what the
    registry must carry rather than a blank."""
    return {row["vip_id"]: row.get("scoreboard_channel") or REQUIRED_HUMAN_INPUT
            for row in mapping or ()}


# ===========================================================================
# Reporting
# ===========================================================================

_INGRESS_COLUMNS: tuple = (
    ("ingress_id", "Ingress"),
    ("component_role", "Component Role"),
    ("component_role_tier", "Role Tier"),
    ("kind", "Kind"),
    ("transaction_type", "Transaction Type"),
    ("array_dimension", "Per-Port Structure"),
    ("protocol_hint", "Protocol Hint"),
    ("endpoint_hint", "Endpoint Hint"),
    ("location", "Location"),
)

_CLASS_COLUMNS: tuple = (
    ("name", "Class"),
    ("base_class", "Extends"),
    ("role", "Role"),
    ("tier", "Evidence Tier"),
    ("evidence", "Evidence"),
    ("location", "Location"),
)


def render_scoreboard_class_table(analysis: ScoreboardEnvAnalysis) -> str:
    rows = [{"name": c["name"], "base_class": c.get("base_class") or "-",
             "location": f"{c['file']}:{c['line']}", **analysis.roles[c["name"]]}
            for c in analysis.classes]
    return render_markdown_table(list(_CLASS_COLUMNS), rows,
                                 empty_note="(no class was found in the supplied roots)")


def render_scoreboard_ingress_table(analysis: ScoreboardEnvAnalysis) -> str:
    rows = [{**i.to_dict(), "location": i.location,
             "transaction_type": i.transaction_type or REQUIRED_HUMAN_INPUT,
             "array_dimension": i.array_dimension or "scalar"}
            for i in analysis.ingress]
    return render_markdown_table(
        list(_INGRESS_COLUMNS), rows,
        empty_note="(no analysis export/imp/fifo was found: this environment has no "
                   "ingress a VIP monitor could be connected to)")


def render_vip_to_ingress_map(mapping) -> str:
    return render_markdown_table(
        list(AMBA21_INGRESS_MAP_COLUMNS), mapping,
        empty_note="(no VIP instance was planned, so nothing was mapped)")


def render_scoreboard_env_report(analysis: Optional[ScoreboardEnvAnalysis], mapping) -> str:
    """AMBA-21's review artifact. Read-only by construction: it reports what was
    found and what a human must decide, and emits no connection code."""
    lines = ["# AMBA-21 Scoreboard / Reference Environment Analysis (read-only)", ""]
    if analysis is None:
        lines += ["No reference environment was supplied. Every proposed VIP monitor "
                  "therefore has an unresolved scoreboard ingress.", ""]
    else:
        lines += [f"Inspected {len(analysis.files)} file(s) under "
                  f"{', '.join(analysis.roots)}; nothing was modified "
                  "(sha256 recorded per file, re-checkable with "
                  "`assert_sources_unmodified()`).", "",
                  "## Reference environment classes", "",
                  render_scoreboard_class_table(analysis), "",
                  "## Scoreboard ingress points", "",
                  render_scoreboard_ingress_table(analysis), "",
                  "## Assumptions per ingress-bearing component", ""]
        for name in sorted(analysis.assumptions):
            lines += [f"### {name}", ""]
            rows = []
            for key in SCOREBOARD_ASSUMPTION_FIELDS:
                block = analysis.assumptions[name][key]
                cites = ", ".join(f"{c['declaration']} @ {c['file']}:{c['line']}"
                                  for c in block["candidate_declarations"]) or "-"
                rows.append({"assumption": key, "value": block["value"],
                             "where_to_look": cites})
            lines += [render_markdown_table(
                [("assumption", "Assumption"), ("value", "Discovered Value"),
                 ("where_to_look", "Candidate Declarations (targeted read)")], rows), ""]
    lines += ["## Proposed VIP monitor -> scoreboard ingress", "",
              render_vip_to_ingress_map(mapping), "",
              "Discovery only. The inspected environment was read and not written; no "
              "connection, adapter or bind is generated by this analysis (AMBA-30 / "
              "AMBA-31). Every ingress above is a candidate a human approves."]
    return "\n".join(lines)
