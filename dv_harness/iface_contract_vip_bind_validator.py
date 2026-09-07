"""dv_harness/iface_contract_vip_bind_validator.py -- spec section 219:
Interface Contract / VIP Bind Validator (2026-09-06).

THE GAP THIS CLOSES
--------------------
Section 219 asks a narrow, concrete question this repo could not previously
answer in code: a project DECLARES, somewhere upstream of generation (a vPlan
row, a spec-derived interface list, a human-authored intent doc), that
interface X is protocol P, direction D, and exposes signal bundle S -- does
the VIP bind this project's own tooling can already find ACTUALLY connect a
module whose real RTL evidence agrees with that declaration? Nothing in this
repo answered that before: a bind statement could target a module whose real
port list is missing half the declared signal bundle, or whose real
structural evidence resolves to a different AMBA protocol than the one a
vPlan row claims, and no code path would ever notice -- only a human reading
both documents side by side would catch the drift, and only if they thought
to look.

REUSE OVER REINVENT (per this task's own instruction, and confirmed by grep
before writing a line of this file: `interface_contract`/`iface_contract`/
`bind_validator` matched nothing executable anywhere in dv_harness/)
-----------------------------------------------------------------------
This is deliberately NOT a fourth independent binding validator.
`dv_harness/connectivity.py` already owns real bind-tier machinery this
module imports and calls rather than reimplements:

  * `grep_existing_binds()` / `find_existing_bind_for_target()` -- the real,
    already-written bind statement a target instance resolves to. This
    module validates against an ALREADY-DECIDED bind only (connectivity.py's
    own T1_ALREADY_DECIDED tier): a contract for a target instance with no
    real bind statement on disk has nothing "actually connected" to check
    against, and is reported UNPROVABLE rather than guessed at from a
    structural/naming candidate that was never actually written into a
    `.sv` file. Structural (T2) and naming (T3) CANDIDATE binds belong to
    connectivity.py's own planning pipeline, not to this validator, which
    answers a strictly narrower question about binds that already exist.
  * `classify_bind_tier()` -- called on every resolved bind so this
    module's cards carry the SAME tier vocabulary/rationale connectivity.py
    already established, instead of inventing a second "how sure are we
    about this bind" scale.
  * `build_interface_fingerprints()`, `match_protocol_fingerprint()`,
    `classify_amba_protocol()`, `AMBA4_PROTOCOLS`, `PROTOCOL_FINGERPRINTS` --
    the real structural-evidence machinery that turns a bound module's real
    (verible-extracted) port list into a protocol verdict. This module
    supplies no second signal-fingerprint table and no second AMBA
    classifier.
  * `determine_role_from_port_direction()` -- the real, name-free
    direction-to-role mapping, reused verbatim to annotate a PROVEN
    direction axis with the same role vocabulary connectivity.py's own
    matrix rows use.

`dv_harness/vip_api_card.py`'s CITATION-PROOF DISCIPLINE is reused just as
literally, not merely imitated: this module imports and reports through the
SAME five-value status vocabulary (`PROVEN` / `BLOCKED` / `UNPROVABLE` /
`OUT_OF_SCOPE` / `NOT_AVAILABLE`) rather than inventing a sixth,
incompatible one for what is structurally the identical question --
"can a claim be proven from a real, cited piece of evidence, and if not,
say exactly why rather than guessing". Read across:

  PROVEN        the declared axis (signal / protocol / direction) is backed
                by real evidence that AGREES with it.
  BLOCKED       the declared axis is backed by real evidence that
                CONTRADICTS it -- a signal the contract claims is present
                but the real bound module's port list provably lacks it, a
                protocol the real structural evidence resolves to something
                else (or to nothing, for a declared-AMBA protocol with zero
                AMBA evidence), or a direction the real port's own recorded
                direction disagrees with. This is section 219's "does not
                match" outcome, exactly as strong a claim as vip_api_card's
                own BLOCKED, and requires the same kind of closed-world
                evidence to assert.
  UNPROVABLE    evidence is insufficient to decide either way (no bind
                found for the target instance, the bound module's real
                ports were never supplied, an anchor signal absent from the
                real port list, an ambiguous/partial protocol resolution).
                Never silently read as a pass.
  OUT_OF_SCOPE  the contract itself declared nothing to check on this axis
                (no signals, no protocol, or no direction/anchor_signal) --
                counted, never a finding, and never allowed to manufacture a
                BLOCKED or a PROVEN.
  NOT_AVAILABLE nothing was checked at all (no contracts supplied, or every
                axis of every contract card was OUT_OF_SCOPE).

Worst-wins fold, per this project's house rule: one BLOCKED axis on one
interface fails that interface's card outright regardless of how many other
axes/interfaces are clean, and one BLOCKED card fails the whole report --
never averaged, never diluted into a percentage. This is the identical fold
`vip_api_card.validate_vip_api_usage()` already applies at the whole-report
level (BLOCKED > UNPROVABLE > PROVEN > NOT_AVAILABLE), reused at both the
per-card (axis -> card) and whole-report (card -> report) levels here.

WHAT THIS MODULE DOES NOT DO (disclosed, not implied)
-------------------------------------------------------
* It does not discover, capture or parse a live DUT instance tree, a UVM
  topology dump, or a config_db trace -- those remain connectivity.py's own
  Input 1 / Input 4 machinery, untouched and unduplicated here. This module
  consumes already-parsed RTL modules (the same `ModuleInfo`/dict shape
  `build_interface_fingerprints()` already accepts) and an already-grepped
  bind list; it performs no filesystem discovery of its own beyond the one
  real `grep_existing_binds()` walk a caller opts into via `--bind-root`.
* It does not decide WHERE a project's "declared interface contract" comes
  from. Exactly like `subsystem_contract.py`'s `requirements` field and
  `spec_vplan_readiness_gate.py`'s condition list, this repo has no single
  fixed producer path for a signal-list/protocol/direction interface
  declaration yet (a vPlan row, a spec-derived interface list, and a
  human-authored intent doc are all plausible real sources, and none of
  them emit this exact shape today) -- so the contract set is accepted as a
  caller-supplied, caller-named JSON record list rather than fetched by
  import from a module this task was not scoped to build.
* It emits no `bind` statement, writes no SystemVerilog, approves nothing,
  and holds no `dv-harness` CLI verb -- the front door is
  `python -m dv_harness.iface_contract_vip_bind_validator`, the same
  disclosed `cli.py`-avoidance several sibling 2026-09-06 modules already
  chose (this batch's own instruction: do not edit `cli.py`/`gates.py`).
* It resolves the ANCHOR-SIGNAL direction only -- the one real port a
  contract names as the interface's orientation-defining signal, mirroring
  `determine_role_from_port_direction()`'s own single-signal contract. It
  does NOT attempt connectivity.py's deeper per-bundle
  `determine_fabric_interface_roles()`/`AmbaInterfaceRoles` machinery: that
  is a separate, considerably larger system this task was not scoped to
  extend, and reimplementing a slice of it here would be exactly the
  "fourth binding validator" this task explicitly warns against.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import connectivity as conn
from .vip_api_card import BLOCKED, NOT_AVAILABLE, OUT_OF_SCOPE, PROVEN, UNPROVABLE

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# reason codes -- SCREAMING_SNAKE_CASE, this package's own convention
# ---------------------------------------------------------------------------
R_MISSING_FIELD = "DECLARED_CONTRACT_MISSING_REQUIRED_FIELD"
R_DUPLICATE_INTERFACE = "DUPLICATE_INTERFACE_NAME"
R_NO_BIND = "NO_EXISTING_BIND_FOUND_FOR_TARGET_INSTANCE"
R_MODULE_NOT_SUPPLIED = "BOUND_MODULE_REAL_PORTS_NOT_SUPPLIED"

R_SIGNAL_NONE_DECLARED = "NO_SIGNALS_DECLARED_IN_CONTRACT"
R_SIGNAL_MISSING = "DECLARED_SIGNAL_ABSENT_FROM_ACTUAL_BOUND_MODULE_PORTS"

R_PROTOCOL_NONE_DECLARED = "NO_PROTOCOL_DECLARED_IN_CONTRACT"
R_PROTOCOL_UNKNOWN_FINGERPRINT = "UNKNOWN_PROTOCOL_FINGERPRINT"
R_PROTOCOL_RESOLVED_MISMATCH = "REAL_PROTOCOL_CLASSIFICATION_DISAGREES_WITH_DECLARED"
R_PROTOCOL_NOT_AMBA = "NO_AMBA_EVIDENCE_FOUND_FOR_DECLARED_AMBA_PROTOCOL"
R_PROTOCOL_AMBIGUOUS = "REAL_PROTOCOL_CLASSIFICATION_AMBIGUOUS_OR_PARTIAL"
R_PROTOCOL_NO_EVIDENCE = "ZERO_STRUCTURAL_EVIDENCE_FOR_DECLARED_PROTOCOL"
R_PROTOCOL_PARTIAL_EVIDENCE = "PARTIAL_STRUCTURAL_EVIDENCE_FOR_DECLARED_PROTOCOL"

R_DIRECTION_NONE_DECLARED = "NO_DIRECTION_OR_ANCHOR_SIGNAL_DECLARED"
R_DIRECTION_ANCHOR_MISSING = "ANCHOR_SIGNAL_NOT_FOUND_IN_ACTUAL_BOUND_MODULE_PORTS"
R_DIRECTION_UNKNOWN = "ANCHOR_SIGNAL_REAL_DIRECTION_NOT_RECORDED"
R_DIRECTION_MISMATCH = "REAL_ANCHOR_DIRECTION_DISAGREES_WITH_DECLARED"

R_NO_CONTRACTS = "NO_DECLARED_INTERFACE_CONTRACTS_SUPPLIED"
R_NOTHING_DECIDABLE = "EVERY_CONTRACT_AXIS_WAS_OUT_OF_SCOPE"


class InterfaceContractError(ValueError):
    """Base class for every hard-fail this module raises: malformed input
    that cannot even be interpreted as a contract, never silently dropped or
    guessed at. `.reason` is a short machine-matchable code, `.detail` is the
    exact evidence that triggered it -- the same shape
    `connectivity.ConnectivityError` already established."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


REQUIRED_CONTRACT_FIELDS: Tuple[str, ...] = ("interface", "target_instance")


@dataclass
class DeclaredInterfaceContract:
    """One interface's declared contract: what a spec/vPlan/intent document
    CLAIMS about an interface, before any real evidence is consulted.
    `protocol`/`direction`/`anchor_signal`/`signals` are each independently
    optional -- an axis a caller does not declare is not silently assumed
    (e.g. an empty signal list does not read as "must have zero ports"), it
    reports `OUT_OF_SCOPE` for that axis, per this module's docstring."""

    interface: str
    target_instance: str
    protocol: Optional[str] = None
    direction: Optional[str] = None
    anchor_signal: Optional[str] = None
    signals: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, *, index: int = 0) -> "DeclaredInterfaceContract":
        if not isinstance(d, dict):
            raise InterfaceContractError(R_MISSING_FIELD, {
                "index": index, "field": "<record>",
                "hint": "each declared-contract record must be a JSON object", "record": d,
            })
        for req in REQUIRED_CONTRACT_FIELDS:
            if not d.get(req):
                raise InterfaceContractError(R_MISSING_FIELD, {
                    "index": index, "field": req, "record": d,
                })
        return cls(
            interface=str(d["interface"]),
            target_instance=str(d["target_instance"]),
            protocol=(str(d["protocol"]) if d.get("protocol") else None),
            direction=(str(d["direction"]) if d.get("direction") else None),
            anchor_signal=(str(d["anchor_signal"]) if d.get("anchor_signal") else None),
            signals=[str(s) for s in (d.get("signals") or [])],
        )


def load_declared_contracts(records: Sequence[dict]) -> List[DeclaredInterfaceContract]:
    """Whole-list form of `DeclaredInterfaceContract.from_dict()`. Raises on
    the first malformed record (never silently skipped) and on a duplicate
    `interface` name (never silently overwritten by a later record with the
    same key -- `verification_intake_contract.py`'s identical rule for a
    duplicate condition name)."""
    out: List[DeclaredInterfaceContract] = []
    seen: set = set()
    for i, rec in enumerate(records or []):
        c = DeclaredInterfaceContract.from_dict(rec, index=i)
        if c.interface in seen:
            raise InterfaceContractError(R_DUPLICATE_INTERFACE, {"interface": c.interface, "index": i})
        seen.add(c.interface)
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# real-evidence indexing over already-parsed modules (never a second parser)
# ---------------------------------------------------------------------------

def _index_module_ports(modules: Sequence) -> Dict[str, List[dict]]:
    """`{module name -> [{"name", "direction"}, ...]}` over the SAME
    `modules` shape `connectivity.build_interface_fingerprints()` already
    accepts (real `verible_parser.ModuleInfo`/`PortInfo` dataclasses, or
    their plain-dict form). Kept separate from
    `build_interface_fingerprints()` only because the direction axis needs
    each port's real recorded direction, which the upper-cased fingerprint
    SET deliberately discards -- this is not a second port extractor, it
    reads the exact same `name`/`ports`/`direction` accessors that function
    already uses."""
    out: Dict[str, List[dict]] = {}
    for mod in modules or []:
        name = mod.name if hasattr(mod, "name") else mod.get("name")
        ports = mod.ports if hasattr(mod, "ports") else mod.get("ports", [])
        if not name:
            continue
        plist = []
        for p in ports:
            pname = p.name if hasattr(p, "name") else p.get("name")
            pdir = p.direction if hasattr(p, "direction") else p.get("direction")
            if pname:
                plist.append({"name": pname, "direction": pdir})
        out[name] = plist
    return out


def _bind_evidence(bind: conn.BindStatement) -> dict:
    """The real bind statement's citation, plus its `classify_bind_tier()`
    verdict -- reused, not re-derived: a bind found by `grep_existing_binds()`
    is, by that function's own contract, real `existing_bind` evidence, so it
    always classifies as `T1_ALREADY_DECIDED`; calling the real classifier
    (rather than hardcoding that string here) means a future change to
    `classify_bind_tier()`'s T1 rule is picked up automatically."""
    tier_result = conn.classify_bind_tier(existing_bind={"target": bind.target})
    return {
        "target": bind.target,
        "bound_module": bind.bound_module,
        "instance_name": bind.instance_name,
        "source_file": bind.source_file,
        "line_no": bind.line_no,
        "raw_line": bind.raw_line,
        "tier": tier_result.tier.value,
        "tier_rationale": tier_result.rationale,
    }


# ---------------------------------------------------------------------------
# the three axes -- each independently PROVEN / BLOCKED / UNPROVABLE / OUT_OF_SCOPE
# ---------------------------------------------------------------------------

def _signal_axis(contract: DeclaredInterfaceContract, port_fingerprint: Optional[set]) -> dict:
    """Every declared signal must be a real, present port on the actually
    bound module. `port_fingerprint` is one value out of
    `connectivity.build_interface_fingerprints()` -- real, verible-derived
    port names, upper-cased -- never re-derived here."""
    declared = sorted({s.strip().upper() for s in contract.signals if s and s.strip()})
    if not declared:
        return {"status": OUT_OF_SCOPE, "reason": R_SIGNAL_NONE_DECLARED,
                "declared": [], "matched": [], "missing": []}
    if port_fingerprint is None:
        return {"status": UNPROVABLE, "reason": R_MODULE_NOT_SUPPLIED,
                "declared": declared, "matched": [], "missing": []}
    matched = sorted(s for s in declared if s in port_fingerprint)
    missing = sorted(s for s in declared if s not in port_fingerprint)
    if missing:
        return {"status": BLOCKED, "reason": R_SIGNAL_MISSING,
                "declared": declared, "matched": matched, "missing": missing}
    return {"status": PROVEN, "reason": None,
            "declared": declared, "matched": matched, "missing": []}


def _protocol_axis(contract: DeclaredInterfaceContract, port_fingerprint: Optional[set]) -> dict:
    """Declared protocol vs. real structural evidence. AMBA-4's ten
    classifications go through `connectivity.classify_amba_protocol()`
    (RESOLVED / AMBIGUOUS_* / UNRESOLVED_PARTIAL_EVIDENCE / NOT_AMBA);
    everything else (CSI2/DSI/USB/USB3/PCIE/SDIO, and the legacy
    AXI/AXI_LITE buckets) goes through
    `connectivity.match_protocol_fingerprint()`. Neither classifier is
    reimplemented -- this function only maps their real verdicts onto the
    PROVEN/BLOCKED/UNPROVABLE/OUT_OF_SCOPE vocabulary."""
    proto = (contract.protocol or "").strip()
    if not proto:
        return {"status": OUT_OF_SCOPE, "reason": R_PROTOCOL_NONE_DECLARED, "declared": None}
    proto_key = proto.upper().replace("-", "_")
    if port_fingerprint is None:
        return {"status": UNPROVABLE, "reason": R_MODULE_NOT_SUPPLIED, "declared": proto_key}

    if proto_key in conn.AMBA4_PROTOCOLS:
        result = conn.classify_amba_protocol(port_fingerprint)
        out = {
            "declared": proto_key,
            "resolved": result.protocol,
            "resolution_status": result.status,
            "evidence_signals": list(result.evidence_signals),
            "missing_signals": list(result.missing_signals),
            "discriminators": list(result.discriminators),
        }
        if result.status == conn.AmbaClassificationStatus.RESOLVED.value:
            if result.protocol == proto_key:
                out["status"], out["reason"] = PROVEN, None
            else:
                out["status"], out["reason"] = BLOCKED, R_PROTOCOL_RESOLVED_MISMATCH
            return out
        if result.status == conn.AmbaClassificationStatus.NOT_AMBA.value:
            out["status"], out["reason"] = BLOCKED, R_PROTOCOL_NOT_AMBA
            return out
        out["status"], out["reason"] = UNPROVABLE, R_PROTOCOL_AMBIGUOUS
        return out

    match = conn.match_protocol_fingerprint(port_fingerprint, proto_key)
    out = {
        "declared": proto_key,
        "matched_signals": list(match.get("matched_signals", [])),
        "missing_signals": list(match.get("missing_signals", [])),
        "match_method": match.get("match_method"),
    }
    if match.get("reason") == "UNKNOWN_PROTOCOL_FINGERPRINT":
        out["status"], out["reason"] = UNPROVABLE, R_PROTOCOL_UNKNOWN_FINGERPRINT
        return out
    if match["matched"]:
        out["status"], out["reason"] = PROVEN, None
        return out
    if match.get("matched_signals"):
        # Some, but not all, of the required signature is present: the
        # fingerprint table's own docstring is explicit that a full-set
        # requirement exists precisely so a wrong/partial fingerprint never
        # over-claims -- reported UNPROVABLE (real evidence is incomplete),
        # never rounded up to BLOCKED against a possibly-wrong illustrative
        # fingerprint (see connectivity.py's own honesty caveat on
        # PROTOCOL_FINGERPRINTS for the non-AMBA entries).
        out["status"], out["reason"] = UNPROVABLE, R_PROTOCOL_PARTIAL_EVIDENCE
        return out
    out["status"], out["reason"] = BLOCKED, R_PROTOCOL_NO_EVIDENCE
    return out


def _direction_axis(contract: DeclaredInterfaceContract, port_list: Optional[List[dict]]) -> dict:
    """Declared direction vs. the real recorded direction of the ONE port the
    contract names as its orientation-defining `anchor_signal` -- mirroring
    `connectivity.determine_role_from_port_direction()`'s own single-signal
    contract rather than attempting the deeper multi-signal
    `determine_fabric_interface_roles()` system (see module docstring)."""
    if not contract.direction or not contract.anchor_signal:
        return {"status": OUT_OF_SCOPE, "reason": R_DIRECTION_NONE_DECLARED}
    if port_list is None:
        return {"status": UNPROVABLE, "reason": R_MODULE_NOT_SUPPLIED,
                "anchor_signal": contract.anchor_signal}
    anchor = contract.anchor_signal.strip().upper()
    real = next((p for p in port_list if (p.get("name") or "").strip().upper() == anchor), None)
    if real is None:
        return {"status": UNPROVABLE, "reason": R_DIRECTION_ANCHOR_MISSING,
                "anchor_signal": contract.anchor_signal}
    real_dir = (real.get("direction") or "").strip().lower()
    if not real_dir:
        return {"status": UNPROVABLE, "reason": R_DIRECTION_UNKNOWN,
                "anchor_signal": contract.anchor_signal}
    declared_dir = contract.direction.strip().lower()
    out = {"anchor_signal": contract.anchor_signal, "declared": declared_dir, "actual": real_dir}
    if real_dir != declared_dir:
        out["status"], out["reason"] = BLOCKED, R_DIRECTION_MISMATCH
        return out
    try:
        out["derived_role"] = conn.determine_role_from_port_direction(real_dir)
    except conn.ConnectivityError:
        out["derived_role"] = None
    out["status"], out["reason"] = PROVEN, None
    return out


# ---------------------------------------------------------------------------
# fold: axis -> card, card -> report (vip_api_card's own worst-wins fold,
# reused literally rather than reinvented)
# ---------------------------------------------------------------------------

def _fold_statuses(statuses: Sequence[str]) -> str:
    """`BLOCKED > UNPROVABLE > PROVEN`, with `OUT_OF_SCOPE` excluded from the
    fold entirely (counted, never a finding -- `vip_api_card.py`'s own rule
    for OUT_OF_SCOPE cards). An all-`OUT_OF_SCOPE` input folds to
    `NOT_AVAILABLE`: nothing was actually decided, which must never read as a
    vacuous PROVEN."""
    relevant = [s for s in statuses if s != OUT_OF_SCOPE]
    if not relevant:
        return NOT_AVAILABLE
    if BLOCKED in relevant:
        return BLOCKED
    if UNPROVABLE in relevant:
        return UNPROVABLE
    return PROVEN


@dataclass
class InterfaceContractCard:
    """One declared interface's verdict: does the real, already-existing VIP
    bind for its `target_instance` actually connect a module whose real
    RTL evidence agrees with the contract's signal list / protocol /
    direction. Mirrors `vip_api_card.VipApiCard`'s shape -- a real citation
    (`bind`) plus a decided status and the exact reason -- one level up,
    over three axes instead of one citation kind."""

    interface: str
    target_instance: str
    status: str
    reason: Optional[str]
    bind: Optional[dict]
    signal_axis: dict
    protocol_axis: dict
    direction_axis: dict

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _validate_one(contract: DeclaredInterfaceContract, binds: List[conn.BindStatement],
                  fingerprints: Dict[str, set], port_lists: Dict[str, List[dict]]
                  ) -> InterfaceContractCard:
    bind = conn.find_existing_bind_for_target(binds, contract.target_instance)
    if bind is None:
        stub = {"status": UNPROVABLE, "reason": R_NO_BIND}
        return InterfaceContractCard(
            interface=contract.interface, target_instance=contract.target_instance,
            status=UNPROVABLE, reason=R_NO_BIND, bind=None,
            signal_axis=dict(stub), protocol_axis=dict(stub), direction_axis=dict(stub),
        )

    bind_ev = _bind_evidence(bind)
    port_fp = fingerprints.get(bind.bound_module)
    port_list = port_lists.get(bind.bound_module)

    sig = _signal_axis(contract, port_fp)
    proto = _protocol_axis(contract, port_fp)
    direc = _direction_axis(contract, port_list)

    status = _fold_statuses([sig["status"], proto["status"], direc["status"]])
    reason = None
    if status in (BLOCKED, UNPROVABLE):
        reason = next(a["reason"] for a in (sig, proto, direc) if a["status"] == status)

    return InterfaceContractCard(
        interface=contract.interface, target_instance=contract.target_instance,
        status=status, reason=reason, bind=bind_ev,
        signal_axis=sig, protocol_axis=proto, direction_axis=direc,
    )


@dataclass
class InterfaceContractValidationReport:
    status: str
    reason: Optional[str] = None
    counts: Dict[str, int] = field(default_factory=dict)
    cards: List[InterfaceContractCard] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["cards"] = [c.to_dict() for c in self.cards]
        return d

    def blocked(self) -> List[InterfaceContractCard]:
        return [c for c in self.cards if c.status == BLOCKED]

    def unprovable(self) -> List[InterfaceContractCard]:
        return [c for c in self.cards if c.status == UNPROVABLE]


def validate_interface_contracts(contracts: Sequence[DeclaredInterfaceContract], *,
                                 binds: Sequence[conn.BindStatement] = (),
                                 modules: Sequence = (),
                                 ) -> InterfaceContractValidationReport:
    """The whole check. `binds` is normally `connectivity.grep_existing_binds()`'s
    real output (or a caller-assembled equivalent list of real
    `BindStatement`s); `modules` is the same real `ModuleInfo`/dict shape
    `connectivity.build_interface_fingerprints()` already accepts. Neither is
    fetched by this function -- both are real evidence a caller supplies,
    exactly like `vip_api_card.validate_vip_api_usage()` takes its `sources`
    and `index` rather than discovering them itself."""
    report = InterfaceContractValidationReport(status=NOT_AVAILABLE)
    if not contracts:
        report.reason = R_NO_CONTRACTS
        return report

    fingerprints = conn.build_interface_fingerprints(modules)
    port_lists = _index_module_ports(modules)
    bind_list = list(binds or [])

    for c in contracts:
        report.cards.append(_validate_one(c, bind_list, fingerprints, port_lists))

    counts: Dict[str, int] = {PROVEN: 0, BLOCKED: 0, UNPROVABLE: 0, NOT_AVAILABLE: 0}
    for c in report.cards:
        counts[c.status] = counts.get(c.status, 0) + 1
    report.counts = counts

    if counts[BLOCKED]:
        report.status = BLOCKED
    elif counts[UNPROVABLE]:
        report.status = UNPROVABLE
    elif counts[PROVEN]:
        report.status = PROVEN
    else:
        report.status = NOT_AVAILABLE
        report.reason = R_NOTHING_DECIDABLE
    return report


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def format_report(report: InterfaceContractValidationReport) -> str:
    """Human-readable rendering, the same shape `vip_api_card.format_report()`
    uses: every non-PROVEN card names its own reason and its own real
    citation, so a finding is actionable without opening the JSON."""
    lines = [f"Interface contract / VIP bind validation: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.counts:
        lines.append("  cards: " + ", ".join(
            f"{k}={report.counts.get(k, 0)}" for k in (PROVEN, BLOCKED, UNPROVABLE, NOT_AVAILABLE)))
    for status, header in ((BLOCKED, "BLOCKED -- contract does not match the real bind"),
                           (UNPROVABLE, "UNPROVABLE -- cannot be decided from the evidence supplied")):
        rows = [c for c in report.cards if c.status == status]
        if not rows:
            continue
        lines += ["", f"  {header}:"]
        for c in rows:
            lines.append(f"    {c.interface} @ {c.target_instance}  [{c.reason}]")
            if c.bind:
                lines.append(f"      bind: {c.bind['source_file']}:{c.bind['line_no']} "
                             f"-> {c.bind['bound_module']} (tier={c.bind['tier']})")
            for axis_name, axis in (("signal", c.signal_axis), ("protocol", c.protocol_axis),
                                    ("direction", c.direction_axis)):
                if axis.get("status") == status:
                    lines.append(f"      {axis_name} axis: {axis.get('reason')}")
    proven = [c for c in report.cards if c.status == PROVEN]
    if proven:
        lines += ["", "  PROVEN:"]
        for c in proven:
            lines.append(f"    {c.interface} @ {c.target_instance} -> "
                         f"{c.bind['bound_module']} ({c.bind['source_file']}:{c.bind['line_no']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O + CLI front door (no `dv-harness` verb -- see module docstring)
# ---------------------------------------------------------------------------

def _load_records(path, *, key: str) -> List[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and key in doc:
        return doc[key] or []
    raise InterfaceContractError("MALFORMED_INPUT_DOCUMENT", {
        "path": str(path), "expected_shape": f"a JSON list, or an object with a {key!r} key",
    })


def execute_verb(contracts_path, *, bind_root=None, modules_path=None,
                 as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for the `python -m` front door. Returns
    (text, exit_code): 0 PROVEN, 1 BLOCKED, 2 NOT_AVAILABLE, 3 UNPROVABLE --
    the identical convention `vip_api_card.execute_verb()` already uses."""
    contracts = load_declared_contracts(_load_records(contracts_path, key="interfaces"))
    binds = conn.grep_existing_binds(bind_root) if bind_root else []
    modules = _load_records(modules_path, key="modules") if modules_path else []
    report = validate_interface_contracts(contracts, binds=binds, modules=modules)
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    return text, {PROVEN: 0, BLOCKED: 1, NOT_AVAILABLE: 2, UNPROVABLE: 3}[report.status]


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.iface_contract_vip_bind_validator",
        description="Spec section 219: validate that a declared interface contract (signal list, "
                    "protocol, direction) matches what a real, already-existing VIP bind actually "
                    "connects to. Reuses connectivity.py's bind-tier machinery and "
                    "vip_api_card.py's citation-proof discipline.")
    ap.add_argument("--contracts", required=True,
                    help="JSON file: a list of declared-interface-contract records, or "
                         "{\"interfaces\": [...]}. Each record needs 'interface' and "
                         "'target_instance'; 'protocol'/'direction'+'anchor_signal'/'signals' "
                         "are each independently optional.")
    ap.add_argument("--bind-root", default=None,
                    help="Root directory to grep for real 'bind ...' statements "
                         "(connectivity.grep_existing_binds()). Omitted => every contract is "
                         "reported UNPROVABLE (no bind evidence).")
    ap.add_argument("--modules", default=None,
                    help="JSON file of already-parsed RTL modules: a list of "
                         "verible_parser.ModuleInfo-shaped dicts, or "
                         "{\"modules\": [...]} (verible_parser.to_dict()'s own shape). "
                         "Omitted => every axis reports UNPROVABLE (no port evidence).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    ap.add_argument("--strict-unprovable", action="store_true",
                    help="Exit non-zero on UNPROVABLE cards too, not just BLOCKED ones.")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(a.contracts, bind_root=a.bind_root, modules_path=a.modules,
                                  as_json=a.json)
    except InterfaceContractError as exc:
        print(f"InterfaceContractError: {exc.reason}: {exc.detail}")
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"InterfaceContractError: INPUT_FILE_NOT_READABLE: {exc}")
        return 2
    print(text)
    if code == 3 and not a.strict_unprovable:
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
