"""dv_harness/system_transaction_ir.py -- SystemTransactionIR: a SYSTEM-SCOPE
transaction record composing `amba_transaction_ir.py`'s per-fabric transaction
facts across multiple composed subsystems' fabrics, 2026-09-07.

REUSE SEARCH PERFORMED FIRST
-----------------------------
Grepped `dv_harness/` for `SystemTransactionIR`/`system_transaction_ir` before
writing anything here -- no hit. `amba_transaction_ir.py` (SYOSCB-10) already
gives ONE fabric's per-port transaction a typed 22-field shape
(`AMBA_TRANSACTION_IR_FIELDS`), built per `AMBA_PORT_REGISTRY` row via
`build_transaction_ir_template()`/`build_transaction_ir_templates()`. That
module is entirely SINGLE-FABRIC / SINGLE-SUBSYSTEM scope by construction --
its own docstring is about one SoC's own registry rows, and it has no notion
of a second, separately-composed subsystem's fabric existing at all.
`transaction_correlation_ir.py` (SYOSCB-11) sits one layer ABOVE that IR and
correlates request/response/data-beat/split-merge facts CROSS-TRANSACTION --
but strictly within one fabric's already-observed evidence stream; it has no
subsystem-namespace concept either, and this module never imports it (a
correlation record it produces, if a caller has one, is simply outside this
module's scope).

`environment_mode_router.py` already draws the line this module reuses for
"system-level" (>= 2 composed subsystems, exactly `system_configuration_ir.py`'s
own `MIN_SUBSYSTEMS_FOR_SYSTEM_LEVEL` precedent); `system_scoreboard_ir.py` is
the closest SIBLING in shape (a system-scope IR that COMPOSES an existing
per-domain analysis across subsystems, never re-deriving it) and this module
follows its exact pattern: caller-declared, evidence-cited facts in, an
honest per-entry composition verdict out, no discovery of its own.

WHAT THIS MODULE REUSES, LITERALLY -- NEVER A SECOND TRANSACTION VOCABULARY
-----------------------------------------------------------------------------
`AMBA_TRANSACTION_IR_FIELDS` (the real 22-field tuple), `REQUIRED_HUMAN_INPUT`
(the real "trace never established this fact" sentinel) and
`unresolved_ir_fields()`/`assert_ir_templates_complete()` (the real per-fabric
completeness checks) are IMPORTED from `amba_transaction_ir.py` and called
verbatim. This module authors no 23rd field, no new sentinel value, and no
second `unresolved_fields` computation -- a system-scope transaction record's
`fields` dict uses EXACTLY the same 22 keys a single-fabric template already
uses, because a transaction's shape does not change when it crosses a
subsystem boundary; only WHOSE fabric observed which side of it does.

THE COMPOSITION QUESTION, PRECISELY
--------------------------------------
Each composed SUBSYSTEM already has its own per-fabric transaction IR --
i.e. a caller has ALREADY run `amba_transaction_ir.build_transaction_ir_templates()`
over that subsystem's own `AMBA_PORT_REGISTRY` rows (this module never calls
that builder itself, and never discovers a subsystem's own fabric facts --
see "what this module does not do" below). `subsystem_fabrics` is
`{subsystem_id: [per-fabric IR template, ...]}`, one list per subsystem,
each entry the REAL dict shape `build_transaction_ir_template()` returns.

A caller separately declares `system_transaction_links`: real, cited facts
about which TWO subsystems' own ports are the master/slave ends of one
system-level transaction path that physically crosses a subsystem boundary
(an SoC interconnect bridging subsystem A's fabric port to subsystem B's,
say) -- the SAME kind of caller-declared, evidence-cited fact
`system_scoreboard_ir.py`'s own `system_interactions` and
`system_topology_analysis.py`'s cross-subsystem address/interrupt/clock
facts already are, applied here to transaction identity instead.

For each declared link, `build_system_transaction_entry()`:
1. Looks up the master subsystem's own per-fabric template for the declared
   master port, and the slave subsystem's own per-fabric template for the
   declared slave port -- both REUSED VERBATIM, never rebuilt or
   re-interpreted. A referenced (subsystem, port) pair this module was not
   handed a template for is `LINK_UNKNOWN_PORT`, never a guess.
2. For every one of the 22 fields, echoes BOTH sides' own already-computed
   `{value, origin}` side by side (`SystemTransactionFieldComposition`) --
   this module NEVER merges the two into one composed value, and never picks
   a winner when they differ. A master-side AXI4 port bridged to a
   slave-side APB port genuinely SHOULD disagree on `protocol`; that is a
   real, expected bridge fact, not a defect to arbitrate. Deciding whether a
   disagreement implies a real transform (width conversion, ID remap, a
   burst split/merge) is `amba_route_transform_predictor.py`'s job
   (SYOSCB-12), untouched and unimported here -- this module only reports
   what each side's own fabric-level analysis already said, honestly, next
   to each other.
3. Reports the link's own composition status from each side's own REAL
   `unresolved_ir_fields()` result -- `LINK_BOTH_SIDES_RESOLVED` (neither
   side's own per-fabric analysis left a `REQUIRED_HUMAN_INPUT` gap),
   `LINK_SIDES_PARTIALLY_RESOLVED` (at least one side still has one), or
   `LINK_UNKNOWN_PORT` (point 1). Worst-wins across every declared link
   folds the whole `SystemTransactionIR`'s own overall status the same way
   every composite IR/gate in this project already folds one.

A project declaring NO cross-subsystem transaction links at all (a
single-subsystem project, or a multi-subsystem one nobody has yet supplied
link evidence for) reports the whole IR `NOT_APPLICABLE` -- never a vacuous
`COMPLETE` over zero links, and never a fabricated `INCOMPLETE` either,
exactly `system_scoreboard_ir.py`'s own precedent.

WHAT THIS MODULE DOES NOT DO, disclosed rather than implied closed
---------------------------------------------------------------------
(1) It discovers no subsystem's own fabric, port, or transaction fact --
    `subsystem_fabrics` is entirely caller-supplied, ALREADY-BUILT
    `amba_transaction_ir` templates; this module never calls
    `build_transaction_ir_template()`/`build_transaction_ir_templates()`
    itself, and never reads an `AMBA_PORT_REGISTRY` row. A real project's
    own per-subsystem `amba_transaction_ir` output is the natural source.
(2) It never decides which subsystems are composed into one system, and
    performs no subsystem-registry lookup of its own -- exactly
    `system_configuration_ir.py`'s own disclosed boundary against
    `environment_mode_router.py`.
(3) It never merges, arbitrates, or judges a genuine cross-fabric field
    disagreement, and never predicts a route transform -- that stays
    `amba_route_transform_predictor.py`'s (SYOSCB-12) job, untouched.
(4) It never correlates request/response/data-beat/split-merge evidence --
    that stays `transaction_correlation_ir.py`'s (SYOSCB-11) job, untouched
    and unimported.
(5) It decides, approves and arbitrates nothing beyond its own per-link
    composition report: no build, no job, no approval, and there is
    deliberately no stage gate -- a `SystemTransactionIR` is an input to a
    human's system-composition review, never a substitute for one.
(6) There is no `dv-harness` CLI verb and `gates.py`/`cli.py`/`CLAUDE.md`
    were not touched, per this project's own file-safety scope (avoid
    editing either file when it is under heavy edit pressure from many
    concurrent items in the same batch). Front door is
    `python -m dv_harness.system_transaction_ir fields|build`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dv_harness.amba_transaction_ir import (
    AMBA_TRANSACTION_IR_FIELDS,
    REQUIRED_HUMAN_INPUT,
    AmbaTransactionIrError,
    assert_ir_templates_complete,
    unresolved_ir_fields,
)


class SystemTransactionIRError(ValueError):
    """A malformed `subsystem_fabrics`/`system_transaction_links` declaration
    -- a missing identity, a subsystem's own per-fabric template list failing
    `amba_transaction_ir`'s own completeness check, or a link with no
    evidence citation. Raised rather than silently dropped or defaulted."""


# ===========================================================================
# This module's OWN vocabulary -- distinct from `dv_harness.models.Status`,
# checked at call time by `assert_no_verification_verdict_vocabulary()`
# rather than merely claimed.
# ===========================================================================

LINK_BOTH_SIDES_RESOLVED = "LINK_BOTH_SIDES_RESOLVED"
LINK_SIDES_PARTIALLY_RESOLVED = "LINK_SIDES_PARTIALLY_RESOLVED"
LINK_UNKNOWN_PORT = "LINK_UNKNOWN_PORT"

LINK_STATUSES: Tuple[str, ...] = (
    LINK_BOTH_SIDES_RESOLVED, LINK_SIDES_PARTIALLY_RESOLVED, LINK_UNKNOWN_PORT,
)

#: Anything that is not fully resolved -- used to fold the whole-IR status.
_NON_COMPLETE_LINK_STATUSES = frozenset({LINK_SIDES_PARTIALLY_RESOLVED, LINK_UNKNOWN_PORT})

OVERALL_COMPLETE = "SYSTEM_TRANSACTION_COMPOSITION_COMPLETE"
OVERALL_INCOMPLETE = "SYSTEM_TRANSACTION_COMPOSITION_INCOMPLETE"
OVERALL_NOT_APPLICABLE = "NOT_APPLICABLE"

OVERALL_STATUSES: Tuple[str, ...] = (OVERALL_COMPLETE, OVERALL_INCOMPLETE, OVERALL_NOT_APPLICABLE)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status tokens must share no token with
    `dv_harness.models.Status` -- the same collision guard several sibling
    modules in this project already run against their own vocabularies.
    Imported lazily so a caller that only wants the pure composition
    functions never pays for pulling in the engine's stage-verdict model."""
    from dv_harness.models import Status
    verdict_tokens = {member.value for member in Status}
    own_tokens = set(LINK_STATUSES) | set(OVERALL_STATUSES)
    collided = verdict_tokens & own_tokens
    if collided:
        raise SystemTransactionIRError(
            f"system_transaction_ir vocabulary collides with dv_harness.models.Status: {sorted(collided)}"
        )


def known_transaction_fields() -> Tuple[str, ...]:
    """The reused 22-field `amba_transaction_ir` shape, verbatim, for a
    caller/report that wants to state which fields this module composes
    without re-deriving them."""
    return AMBA_TRANSACTION_IR_FIELDS


# ===========================================================================
# Records
# ===========================================================================

@dataclass
class SystemTransactionFieldComposition:
    """One of the 22 reused fields, echoed side by side from each of the two
    subsystems' own already-computed per-fabric facts. Never merged into one
    composed value -- a genuine cross-fabric disagreement (protocol, width,
    id-space) is a real bridge/transform fact this module reports rather
    than judges."""

    field_name: str
    master_value: Any
    master_origin: Optional[str]
    master_resolved: bool
    slave_value: Any
    slave_origin: Optional[str]
    slave_resolved: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "master_value": self.master_value,
            "master_origin": self.master_origin,
            "master_resolved": self.master_resolved,
            "slave_value": self.slave_value,
            "slave_origin": self.slave_origin,
            "slave_resolved": self.slave_resolved,
        }


@dataclass
class SystemTransactionEntry:
    """One declared cross-subsystem transaction link's composition verdict."""

    link_id: str
    master_subsystem: str
    master_port_id: str
    slave_subsystem: str
    slave_port_id: str
    link_status: str
    fields: Dict[str, SystemTransactionFieldComposition]
    master_unresolved_fields: List[str]
    slave_unresolved_fields: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "link_id": self.link_id,
            "master_subsystem": self.master_subsystem,
            "master_port_id": self.master_port_id,
            "slave_subsystem": self.slave_subsystem,
            "slave_port_id": self.slave_port_id,
            "link_status": self.link_status,
            "fields": {name: comp.to_dict() for name, comp in self.fields.items()},
            "master_unresolved_fields": list(self.master_unresolved_fields),
            "slave_unresolved_fields": list(self.slave_unresolved_fields),
            "reason": self.reason,
        }

    def to_row(self) -> Dict[str, Any]:
        return {
            "link_id": self.link_id,
            "master": f"{self.master_subsystem}.{self.master_port_id}",
            "slave": f"{self.slave_subsystem}.{self.slave_port_id}",
            "link_status": self.link_status,
            "master_unresolved": ", ".join(self.master_unresolved_fields) or "(none)",
            "slave_unresolved": ", ".join(self.slave_unresolved_fields) or "(none)",
            "reason": self.reason,
        }


@dataclass
class SystemTransactionIR:
    """The system-scope record: how every declared cross-subsystem
    transaction link's own composition question resolved, plus one
    worst-wins overall verdict."""

    entries: List[SystemTransactionEntry] = field(default_factory=list)
    overall_status: str = OVERALL_NOT_APPLICABLE
    overall_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "overall_status": self.overall_status,
            "overall_reason": self.overall_reason,
            "reused_fields": list(AMBA_TRANSACTION_IR_FIELDS),
        }


# ===========================================================================
# Per-fact helpers
# ===========================================================================

def _require_str(value: Any, field_name: str, item_desc: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemTransactionIRError(
            f"{item_desc}: '{field_name}' must be a non-empty string, got {value!r}"
        )
    return value


def index_subsystem_fabrics(
    subsystem_fabrics: Optional[Dict[str, List[Dict[str, Any]]]],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Validate and index every subsystem's own ALREADY-BUILT per-fabric IR
    templates by `port_id`. Reuses `amba_transaction_ir.assert_ir_templates_complete()`
    verbatim -- this module never re-validates a template's own field shape
    by hand, and never builds a template itself."""
    if subsystem_fabrics is None:
        return {}
    if not isinstance(subsystem_fabrics, dict):
        raise SystemTransactionIRError(
            f"subsystem_fabrics must be a dict of {{subsystem_id: [templates]}}, "
            f"got {type(subsystem_fabrics).__name__!r}"
        )
    indexed: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for subsystem_id, templates in subsystem_fabrics.items():
        if not isinstance(subsystem_id, str) or not subsystem_id.strip():
            raise SystemTransactionIRError(
                f"subsystem_fabrics: every key must be a non-empty subsystem id, got {subsystem_id!r}"
            )
        if not isinstance(templates, list):
            raise SystemTransactionIRError(
                f"subsystem_fabrics[{subsystem_id!r}] must be a list of per-fabric IR "
                f"templates, got {type(templates).__name__!r}"
            )
        try:
            assert_ir_templates_complete(templates)
        except AmbaTransactionIrError as exc:
            raise SystemTransactionIRError(
                f"subsystem_fabrics[{subsystem_id!r}]: {exc}"
            ) from exc
        by_port: Dict[str, Dict[str, Any]] = {}
        for template in templates:
            port_id = template.get("port_id")
            if not isinstance(port_id, str) or not port_id.strip():
                raise SystemTransactionIRError(
                    f"subsystem_fabrics[{subsystem_id!r}]: a per-fabric template is missing "
                    f"a real 'port_id'"
                )
            if port_id in by_port:
                raise SystemTransactionIRError(
                    f"subsystem_fabrics[{subsystem_id!r}]: duplicate port_id {port_id!r} "
                    f"among per-fabric templates"
                )
            by_port[port_id] = template
        indexed[subsystem_id] = by_port
    return indexed


def _compose_field(
    field_name: str,
    master_template: Optional[Dict[str, Any]],
    slave_template: Optional[Dict[str, Any]],
) -> SystemTransactionFieldComposition:
    master_entry = (master_template.get("fields") or {}).get(field_name) if master_template else None
    slave_entry = (slave_template.get("fields") or {}).get(field_name) if slave_template else None
    master_value = master_entry.get("value") if master_entry else None
    slave_value = slave_entry.get("value") if slave_entry else None
    return SystemTransactionFieldComposition(
        field_name=field_name,
        master_value=master_value,
        master_origin=master_entry.get("origin") if master_entry else None,
        master_resolved=master_entry is not None and master_value != REQUIRED_HUMAN_INPUT,
        slave_value=slave_value,
        slave_origin=slave_entry.get("origin") if slave_entry else None,
        slave_resolved=slave_entry is not None and slave_value != REQUIRED_HUMAN_INPUT,
    )


def build_system_transaction_entry(
    link: Dict[str, Any],
    indexed_subsystems: Dict[str, Dict[str, Dict[str, Any]]],
) -> SystemTransactionEntry:
    """Validate one `system_transaction_links` entry and compose its
    per-field, side-by-side report from each subsystem's own ALREADY-BUILT
    per-fabric template. Raises `SystemTransactionIRError` on a malformed
    entry (no identity, no evidence citation, or a self-loop link naming the
    same subsystem on both ends -- a within-one-fabric transaction is
    `amba_transaction_ir.py`'s own concern, not a system-level link)."""
    if not isinstance(link, dict):
        raise SystemTransactionIRError(
            f"expected a dict describing a system transaction link, got {type(link).__name__!r}"
        )
    link_id = _require_str(link.get("link_id"), "link_id", "system_transaction_links entry")
    item_desc = f"system_transaction_links[{link_id!r}]"
    master_subsystem = _require_str(link.get("master_subsystem"), "master_subsystem", item_desc)
    master_port_id = _require_str(link.get("master_port_id"), "master_port_id", item_desc)
    slave_subsystem = _require_str(link.get("slave_subsystem"), "slave_subsystem", item_desc)
    slave_port_id = _require_str(link.get("slave_port_id"), "slave_port_id", item_desc)
    _require_str(link.get("evidence"), "evidence", item_desc)
    if master_subsystem == slave_subsystem:
        raise SystemTransactionIRError(
            f"{item_desc}: master_subsystem and slave_subsystem are both {master_subsystem!r} -- "
            "a within-one-subsystem transaction is amba_transaction_ir.py's own single-fabric "
            "concern, not a cross-subsystem system_transaction_links entry"
        )

    master_template = indexed_subsystems.get(master_subsystem, {}).get(master_port_id)
    slave_template = indexed_subsystems.get(slave_subsystem, {}).get(slave_port_id)

    if master_template is None or slave_template is None:
        missing = []
        if master_template is None:
            missing.append(f"master {master_subsystem}.{master_port_id}")
        if slave_template is None:
            missing.append(f"slave {slave_subsystem}.{slave_port_id}")
        return SystemTransactionEntry(
            link_id=link_id,
            master_subsystem=master_subsystem, master_port_id=master_port_id,
            slave_subsystem=slave_subsystem, slave_port_id=slave_port_id,
            link_status=LINK_UNKNOWN_PORT,
            fields={},
            master_unresolved_fields=[], slave_unresolved_fields=[],
            reason=(
                f"no per-fabric IR template was supplied for: {', '.join(missing)} -- this "
                "module never builds one itself, only composes already-built templates"
            ),
        )

    fields = {
        name: _compose_field(name, master_template, slave_template)
        for name in AMBA_TRANSACTION_IR_FIELDS
    }
    master_unresolved = unresolved_ir_fields(master_template)
    slave_unresolved = unresolved_ir_fields(slave_template)

    if master_unresolved or slave_unresolved:
        status = LINK_SIDES_PARTIALLY_RESOLVED
        reason = (
            f"at least one side's own per-fabric analysis left a real discovery gap -- "
            f"master {master_subsystem}.{master_port_id} unresolved: "
            f"{master_unresolved or '(none)'}; slave {slave_subsystem}.{slave_port_id} "
            f"unresolved: {slave_unresolved or '(none)'}"
        )
    else:
        status = LINK_BOTH_SIDES_RESOLVED
        reason = (
            f"both {master_subsystem}.{master_port_id} and {slave_subsystem}.{slave_port_id} "
            "own per-fabric analyses resolved every field their own fabric discovery could "
            "establish -- composed side by side, never merged into one value"
        )

    return SystemTransactionEntry(
        link_id=link_id,
        master_subsystem=master_subsystem, master_port_id=master_port_id,
        slave_subsystem=slave_subsystem, slave_port_id=slave_port_id,
        link_status=status,
        fields=fields,
        master_unresolved_fields=master_unresolved,
        slave_unresolved_fields=slave_unresolved,
        reason=reason,
    )


# ===========================================================================
# Composition
# ===========================================================================

def build_system_transaction_ir(
    subsystem_fabrics: Optional[Dict[str, List[Dict[str, Any]]]],
    system_transaction_links: Optional[List[Dict[str, Any]]],
) -> SystemTransactionIR:
    """Build the whole-system `SystemTransactionIR`.

    `subsystem_fabrics` and `system_transaction_links` are both entirely
    caller-declared, cited facts -- see the module docstring. Neither is
    discovered here."""
    if system_transaction_links is None:
        system_transaction_links = []
    if not isinstance(system_transaction_links, list):
        raise SystemTransactionIRError(
            f"system_transaction_links must be a list, got {type(system_transaction_links).__name__!r}"
        )

    if not system_transaction_links:
        return SystemTransactionIR(
            entries=[],
            overall_status=OVERALL_NOT_APPLICABLE,
            overall_reason=(
                "no system_transaction_links were declared -- either this is a "
                "single-subsystem project with no cross-subsystem transaction to compose, "
                "or no link evidence has been supplied yet. Reporting NOT_APPLICABLE rather "
                "than a vacuous COMPLETE or a fabricated INCOMPLETE."
            ),
        )

    indexed = index_subsystem_fabrics(subsystem_fabrics)

    entries: List[SystemTransactionEntry] = []
    seen_ids: set = set()
    for link in system_transaction_links:
        entry = build_system_transaction_entry(link, indexed)
        if entry.link_id in seen_ids:
            raise SystemTransactionIRError(
                f"duplicate link_id {entry.link_id!r} in system_transaction_links"
            )
        seen_ids.add(entry.link_id)
        entries.append(entry)

    non_complete = [e for e in entries if e.link_status in _NON_COMPLETE_LINK_STATUSES]
    if non_complete:
        overall_status = OVERALL_INCOMPLETE
        overall_reason = (
            f"{len(non_complete)} of {len(entries)} declared link(s) are not fully resolved "
            f"({', '.join(sorted({e.link_status for e in non_complete}))}) -- worst-wins: a "
            "single unresolved link blocks the whole system's transaction-composition verdict "
            "regardless of how many others are fully resolved."
        )
    else:
        overall_status = OVERALL_COMPLETE
        overall_reason = (
            f"all {len(entries)} declared cross-subsystem transaction link(s) compose from "
            "two fully-resolved per-fabric templates."
        )

    return SystemTransactionIR(entries=entries, overall_status=overall_status, overall_reason=overall_reason)


# ===========================================================================
# Rendering
# ===========================================================================

def render_system_transaction_markdown(ir: SystemTransactionIR) -> str:
    """Reuses `connectivity.render_markdown_table()` -- this repo's one
    parameterized table renderer -- rather than a second hand-rolled table
    loop. Imported lazily so a caller wanting only the pure composition
    functions above never needs `connectivity.py` on the import path."""
    from dv_harness.connectivity import render_markdown_table
    columns = [
        ("link_id", "Link"),
        ("master", "Master"),
        ("slave", "Slave"),
        ("link_status", "Status"),
        ("master_unresolved", "Master Unresolved"),
        ("slave_unresolved", "Slave Unresolved"),
        ("reason", "Reason"),
    ]
    rows = [e.to_row() for e in ir.entries]
    table = render_markdown_table(columns, rows, empty_note="(no system transaction links declared)")
    return (
        f"**Overall: {ir.overall_status}** -- {ir.overall_reason}\n\n"
        f"Reused 22-field amba_transaction_ir shape: {', '.join(AMBA_TRANSACTION_IR_FIELDS)}\n\n"
        f"{table}"
    )


# ===========================================================================
# CLI front door -- no dv-harness verb (cli.py/gates.py are out of scope)
# ===========================================================================

def execute_verb(argv: Optional[list] = None) -> Tuple[int, Dict[str, Any], str]:
    assert_no_verification_verdict_vocabulary()
    parser = argparse.ArgumentParser(prog="system_transaction_ir")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("fields", help="list the reused 22-field amba_transaction_ir shape")

    p_build = sub.add_parser("build", help="build the SystemTransactionIR from declared facts")
    p_build.add_argument("--fabrics", required=True,
                          help="path to a JSON file: {subsystem_id: [per-fabric IR templates]}")
    p_build.add_argument("--links", required=True,
                          help="path to a JSON file: a list of system_transaction_links entries")
    p_build.add_argument("--json", action="store_true", help="print machine-readable JSON only")

    args = parser.parse_args(argv)

    if args.verb == "fields":
        result = {"fields": list(AMBA_TRANSACTION_IR_FIELDS)}
        return 0, result, json.dumps(result, indent=2)

    with open(args.fabrics, "r", encoding="utf-8") as f:
        subsystem_fabrics = json.load(f)
    with open(args.links, "r", encoding="utf-8") as f:
        system_transaction_links = json.load(f)

    try:
        ir = build_system_transaction_ir(subsystem_fabrics, system_transaction_links)
    except SystemTransactionIRError as exc:
        result = {"error": str(exc)}
        return 2, result, json.dumps(result, indent=2)

    result = ir.to_dict()
    if args.json:
        text = json.dumps(result, indent=2)
    else:
        text = render_system_transaction_markdown(ir)

    exit_code = 0 if ir.overall_status in (OVERALL_COMPLETE, OVERALL_NOT_APPLICABLE) else 1
    return exit_code, result, text


def main(argv: Optional[list] = None) -> int:
    exit_code, _result, text = execute_verb(argv)
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
