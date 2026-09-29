"""dv_harness/holistic_clock_reset_power_consistency.py -- whole-environment
clock/reset/power consistency check over a CHOSEN set of binds, taken as
ONE WHOLE rather than one row/bind/boundary at a time.

THE GAP THIS CLOSES. Every existing consistency check in this codebase that
touches clock/reset/power evaluates ONE record at a time:
`connectivity.py`'s Bind-Location Rules are reviewed per bind statement (Rule
3: clock/reset must be passed through the bind's own port list, never an
XMR); `verification_architecture.AssertionIR.clock_domain_match`/
`reset_domain_match` compare ONE assertion candidate's own declared domain
against `env_manifest.build_dut_facts_clock_reset()`'s clock/reset map;
`power_intent.analyze_power_intent()` checks the UPF model against ITSELF
(a switchable domain has an isolation strategy, a supply reference resolves,
...) with no notion of which RTL instances an environment's own binds
actually observe. None of them ever asks the question this module answers:
given the FULL set of binds a chosen environment architecture actually
mounts, are they COLLECTIVELY consistent with the DUT's clock/reset
dependency structure and power-domain topology taken as one whole -- do the
binds inside one physical power domain agree on which reset network they
observe, does a domain the power intent says is unsafe to probe (switchable,
no isolation) have binds mounted inside it at all, does the chosen
architecture leave a whole declared clock domain completely unexercised.
Those are set-level facts; no pairwise comparison of two binds, or of one
bind against one domain, can produce them.

REAL EVIDENCE SOURCES, REUSED RATHER THAN RE-DERIVED.

"clock_reset_dependency_graph" is not a module that exists anywhere in this
repository (checked by grep before writing a line of this file). The real
evidence source with that shape is `env_manifest.build_dut_facts_clock_reset()`
-- and, producing the IDENTICAL field shape from a different source,
`interrupt_dma_clock_reset_extraction.py`'s `clock_reset_extension` block.
Both already model the DEPENDENCY this module needs as a graph, just never
as a class: each reset entry carries a `clock` field naming the clock it is
synchronised to and a `clock_resolved` verdict (RESOLVED / UNKNOWN_CLOCK /
NOT_SPECIFIED) for whether that dependency actually resolves against the
same document's own declared clocks. This module reads that dict verbatim
(`clock_reset_facts`, caller-supplied -- never re-parsed, never re-extracted)
and treats it AS a dependency graph: clocks are nodes, and each reset with
`clock_resolved == "RESOLVED"` is a real edge from that reset to its clock.

`power_intent.py` is imported and used directly: `PowerIntent.domains`
(each carrying real `-elements` RTL scope paths), `PowerIntent.
switchable_domains()` (the real, already-tested method deciding which
domains a power switch drives), and `PowerIntent.isolation`/`.retention`
(the real per-domain strategy lists `analyze_power_intent()` itself reads).
Nothing here re-parses UPF and nothing here re-implements the switchable/
isolation logic those real methods and lists already carry.

Per-bind clock/reset PORT identification reuses `connectivity.
find_amba_clock_reset_ports()` verbatim -- the real, already-tested
tokenizing tiered resolver AMBA-15 built for exactly this ("which of an
instance's real ports is this interface's clock, and which is its reset"),
applied here to a bind entry's own `ports` list rather than to one AMBA
interface's bundle. A bind entry is the same 3+-field shape
`connectivity.enforce_bind_tier_policy()`/`bind_mechanism_generator.
validate_bind_entries()` already consume (`target_instance`, `ports`,
`reason`, optional `tier`/`protocol`) -- this module reads that shape, it
does not define a second one.

WHAT "COLLECTIVELY CONSISTENT" MEANS HERE, CONCRETELY. Given the chosen
bind set:
- every declared power domain that carries at least one bound RTL instance
  (matched by real `-elements` scope-path containment, never by name alone)
  is checked as a GROUP: if the domain is switchable (a real power switch
  drives it) and carries no non-`no_isolation` isolation strategy, every
  bind mounted inside it is flagged together -- a fact only visible once the
  WHOLE group of binds under that domain is known, never from one bind
  alone;
- the group's own set of topology-resolved reset names is compared as a
  SET, not pairwise -- more than one distinct declared reset name observed
  across one physical power domain's own bind membership is reported;
- every clock the DUT's own topology declares is checked against the WHOLE
  bind set (directly referenced, or reached through a dependent reset) for
  whether ANY bind in the chosen architecture exercises it at all;
- a bind whose structurally-identified reset resolves to a real declared
  reset the topology itself could not tie to a clock (`UNKNOWN_CLOCK`/
  `NOT_SPECIFIED`) is flagged, connecting a WHOLE-topology fact (the
  document's own unresolved dependency) to a specific chosen bind.

EVIDENCE TRUTH RULE, ENFORCED STRUCTURALLY. `clock_reset_facts=None` (or a
document whose own `status` is not `"LOADED"`) and `power_intent=None` are
each independently, honestly recorded as NOT AVAILABLE -- every check that
needs that axis is skipped, never answered from a guess, and the report says
so by name (`clock_reset_topology_available`/`power_intent_available`).
A power domain declared with `-include_scope` and NO explicit `-elements` is
deliberately EXCLUDED from instance-to-domain matching: this module does not
track UPF's own `set_scope` nesting, and asserting broad coverage from an
absent element list would be exactly the unearned claim the Evidence Truth
Rule forbids -- only a domain with a real, explicit `-elements` list is used
to decide bind membership. A bind whose port list yields no structurally-
recognisable clock/reset candidate is reported (Bind-Location Rule 3 risk),
never silently skipped and never asserted to be actually missing one --
`find_amba_clock_reset_ports()`'s own naming-heuristic limits apply here
exactly as they do everywhere else it is used.

WHAT THIS MODULE DOES NOT DO. It emits no `bind` statement, decides no bind
target, and authors no RTL/UPF content. It never re-parses UPF (that stays
`power_intent.py`'s job) and never re-derives clock/reset facts from RTL
(that stays `env_manifest.py`/`interrupt_dma_clock_reset_extraction.py`'s
job). It ARBITRATES nothing -- a domain with genuinely different reset
networks feeding different sub-blocks is a real, legitimate design, and this
module reports the fact for a human to judge, never resolves it. There is
deliberately no stage gate: no build, job, or approval is touched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import connectivity as _connectivity
from . import power_intent as _power_intent_module

PowerIntent = _power_intent_module.PowerIntent

# ---------------------------------------------------------------------------
# Vocabulary -- deliberately disjoint from dv_harness.models.Status
# ---------------------------------------------------------------------------
STATUS_CONSISTENT = "CONSISTENT"
STATUS_INCONSISTENCIES_FOUND = "INCONSISTENCIES_FOUND"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
OVERALL_STATUSES = (STATUS_CONSISTENT, STATUS_INCONSISTENCIES_FOUND, STATUS_NOT_AVAILABLE)

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"
_SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

CODE_BIND_ENTRY_MALFORMED = "BIND_ENTRY_MALFORMED"
CODE_BIND_MISSING_CLOCK_OR_RESET_PORT = "BIND_MISSING_CLOCK_OR_RESET_PORT"
CODE_BIND_PORT_NOT_IN_DECLARED_TOPOLOGY = "BIND_PORT_NOT_IN_DECLARED_CLOCK_RESET_TOPOLOGY"
CODE_POWER_DOMAIN_RESET_SET_INCONSISTENT = "POWER_DOMAIN_RESET_SET_INCONSISTENT"
CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION = "SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION"
CODE_BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN = "BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN"
CODE_CLOCK_DOMAIN_NOT_EXERCISED_BY_ANY_BIND = "CLOCK_DOMAIN_NOT_EXERCISED_BY_ANY_BIND"
CODE_RESET_CLOCK_UNRESOLVED_REFERENCED_BY_BIND = "RESET_CLOCK_UNRESOLVED_REFERENCED_BY_BIND"


def assert_no_verification_verdict_vocabulary() -> None:
    """Import-time guard: this module's own status vocabulary must never
    collide with a real stage-gate verdict, the same discipline several
    sibling domain-vocabulary modules in this codebase already apply to
    themselves."""
    from . import models
    verdicts = {s.value for s in models.Status}
    collision = verdicts & set(OVERALL_STATUSES)
    if collision:  # pragma: no cover -- defensive, would only fire on a future edit
        raise AssertionError(
            f"holistic_clock_reset_power_consistency status vocabulary collides "
            f"with dv_harness.models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


class HolisticClockResetPowerConsistencyError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@dataclass
class ConsistencyFinding:
    severity: str
    code: str
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "evidence": dict(self.evidence)}


# ---------------------------------------------------------------------------
# Clock/reset "dependency graph" -- the real env_manifest/
# interrupt_dma_clock_reset_extraction shape, treated as a graph.
# ---------------------------------------------------------------------------
def _build_clock_reset_topology(clock_reset_facts: Optional[Mapping]) -> dict:
    if not clock_reset_facts or clock_reset_facts.get("status") != "LOADED":
        reason = (clock_reset_facts or {}).get("reason") or \
            "no clock/reset topology evidence supplied (see " \
            "env_manifest.build_dut_facts_clock_reset() / " \
            "interrupt_dma_clock_reset_extraction.py's clock_reset_extension)"
        return {"available": False, "reason": reason, "clocks": {}, "resets": {}}
    clocks = {c["name"]: dict(c) for c in (clock_reset_facts.get("clocks") or []) if c.get("name")}
    resets = {r["name"]: dict(r) for r in (clock_reset_facts.get("resets") or []) if r.get("name")}
    return {"available": True, "reason": None, "clocks": clocks, "resets": resets}


# ---------------------------------------------------------------------------
# Power-domain membership -- real -elements scope-path containment only.
# ---------------------------------------------------------------------------
def _normalize_hierarchy_path(path: str) -> str:
    return str(path).strip().replace("/", ".")


def _instance_under_element(instance_path: str, element_path: str) -> bool:
    inst = _normalize_hierarchy_path(instance_path)
    elem = _normalize_hierarchy_path(element_path)
    if not elem:
        return False
    return inst == elem or inst.startswith(elem + ".")


def domains_for_instance(instance_path: str, domains: Sequence) -> List[str]:
    """Which real, explicitly-`-elements`-scoped power domains this RTL
    instance path falls under. A domain declared with `-include_scope` and
    no explicit `-elements` never matches here -- see the module docstring's
    "Evidence Truth Rule, enforced structurally" section for why."""
    matched = []
    for d in domains or ():
        elements = getattr(d, "elements", None) or []
        if not elements:
            continue
        if any(_instance_under_element(instance_path, e) for e in elements):
            matched.append(d.name)
    return matched


def _domain_has_isolation(power_intent: PowerIntent, domain_name: str) -> bool:
    return any(s.domain == domain_name and not s.no_isolation
               for s in getattr(power_intent, "isolation", []) or [])


def _domain_has_retention(power_intent: PowerIntent, domain_name: str) -> bool:
    return any(s.domain == domain_name for s in getattr(power_intent, "retention", []) or [])


def _domain_evidence(power_intent: PowerIntent, domain_name: str) -> dict:
    d = power_intent.domain(domain_name) if power_intent else None
    return {"file": getattr(d, "file", ""), "line": getattr(d, "line", 0)} if d else {}


# ---------------------------------------------------------------------------
# Per-bind clock/reset resolution -- reuses connectivity.find_amba_clock_reset_ports
# ---------------------------------------------------------------------------
def resolve_bind_clock_reset_ports(entry: Mapping, topology: dict) -> dict:
    """One bind entry's own structural clock/reset resolution, then matched
    against the real declared clock/reset topology (when available). Never
    fabricates a match: `resolved_name` is populated ONLY when the
    structurally-identified port name is a literal key in `topology`."""
    ports = list(entry.get("ports") or [])
    protocol = entry.get("protocol")
    bundle_prefix = entry.get("bundle_prefix", "")
    raw = _connectivity.find_amba_clock_reset_ports(protocol, bundle_prefix, ports)
    out = {}
    for kind, key in (("clock", "clocks"), ("reset", "resets")):
        cand = raw[kind]
        port = cand.get("port")
        resolved_name = None
        in_topology = None
        if topology.get("available"):
            if port is not None:
                in_topology = port in topology[key]
                resolved_name = port if in_topology else None
        out[kind] = {
            "status": cand.get("status"),
            "port": port,
            "candidates": cand.get("candidates", []),
            "resolved_name": resolved_name,
            "in_declared_topology": in_topology,
        }
    return out


# ---------------------------------------------------------------------------
# The whole-environment report
# ---------------------------------------------------------------------------
def build_holistic_consistency_report(
    bind_entries: Optional[Sequence[Mapping]],
    *,
    clock_reset_facts: Optional[Mapping] = None,
    power_intent: Optional[PowerIntent] = None,
) -> dict:
    """The one entry point. `bind_entries` is the CHOSEN environment
    architecture's own bind set (the same shape `bind_mechanism_generator.
    validate_bind_entries()` consumes). `clock_reset_facts` is a real
    `env_manifest.build_dut_facts_clock_reset()`-shaped dict (or the
    equivalent `interrupt_dma_clock_reset_extraction.py` block).
    `power_intent` is a real `power_intent.PowerIntent` instance (from
    `power_intent.extract_power_intent()`), never a hand-shaped dict.

    Absence of either axis is honestly recorded, never guessed at: see the
    module docstring's "Evidence Truth Rule" section."""
    if power_intent is not None and not isinstance(power_intent, PowerIntent):
        raise HolisticClockResetPowerConsistencyError(
            "POWER_INTENT_NOT_A_REAL_POWERINTENT_INSTANCE",
            {"got": type(power_intent).__name__,
             "hint": "pass the real object power_intent.extract_power_intent() returns, "
                     "never a hand-shaped dict"})

    entries = list(bind_entries or [])
    if not entries:
        return {
            "status": STATUS_NOT_AVAILABLE,
            "reason": "no bind entries supplied -- nothing to check the topology against",
            "clock_reset_topology_available": False,
            "power_intent_available": False,
            "findings": [],
            "bind_resolution": [],
            "power_domain_membership": {},
            "clock_domain_coverage": {},
        }

    topology = _build_clock_reset_topology(clock_reset_facts)
    findings: List[ConsistencyFinding] = []

    # -- resolve every bind entry, isolating a malformed one rather than
    #    letting it sink the whole report ------------------------------
    resolved_binds: List[dict] = []
    for i, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, Mapping) or not raw_entry.get("target_instance") \
                or not raw_entry.get("ports"):
            findings.append(ConsistencyFinding(
                SEVERITY_WARNING, CODE_BIND_ENTRY_MALFORMED,
                f"bind entry at index {i} is missing target_instance/ports and was "
                f"skipped from this check",
                {"index": i}))
            continue
        target = raw_entry["target_instance"]
        cr = resolve_bind_clock_reset_ports(raw_entry, topology)
        domains = (domains_for_instance(target, power_intent.domains)
                  if power_intent is not None else [])
        resolved_binds.append({
            "target_instance": target,
            "reason": raw_entry.get("reason"),
            "clock": cr["clock"],
            "reset": cr["reset"],
            "power_domains": domains,
        })

        missing_sides = [side for side in ("clock", "reset") if cr[side]["status"] != "RESOLVED"]
        if missing_sides:
            findings.append(ConsistencyFinding(
                SEVERITY_WARNING, CODE_BIND_MISSING_CLOCK_OR_RESET_PORT,
                f"{target}: no structurally-recognisable {'/'.join(missing_sides)} port in "
                f"this bind's own port list ({sorted(raw_entry.get('ports') or [])}) -- verify "
                f"clock/reset are passed explicitly through the bind's own port connections "
                f"(Bind-Location Rule 3), not obtained via a hierarchical XMR",
                {"target_instance": target, "missing": missing_sides,
                 "ports": sorted(raw_entry.get("ports") or [])}))

        if topology["available"]:
            for side in ("clock", "reset"):
                c = cr[side]
                if c["status"] == "RESOLVED" and c["in_declared_topology"] is False:
                    findings.append(ConsistencyFinding(
                        SEVERITY_INFO, CODE_BIND_PORT_NOT_IN_DECLARED_TOPOLOGY,
                        f"{target}: structurally-identified {side} port {c['port']!r} does "
                        f"not literally match any name in the DUT's declared "
                        f"{'clocks' if side == 'clock' else 'resets'} -- expected for a "
                        f"deeply-nested bind target with a locally-renamed net, worth a "
                        f"second look for a top-level target",
                        {"target_instance": target, "side": side, "port": c["port"]}))

        if power_intent is not None and power_intent.domains and not domains:
            findings.append(ConsistencyFinding(
                SEVERITY_INFO, CODE_BIND_TARGET_NOT_IN_ANY_DECLARED_POWER_DOMAIN,
                f"{target}: not matched to any power domain's explicit -elements scope -- "
                f"either genuinely outside every declared domain, or nested under a domain "
                f"declared only with -include_scope (not matched by this module)",
                {"target_instance": target}))

    # -- power-domain GROUP checks: every domain with >=1 bound instance,
    #    examined as a whole set of binds, never pairwise ---------------
    power_domain_membership: Dict[str, dict] = {}
    if power_intent is not None:
        switchable = set(power_intent.switchable_domains())
        for d in power_intent.domains:
            members = [b for b in resolved_binds if d.name in b["power_domains"]]
            reset_names = sorted({b["reset"]["resolved_name"] for b in members
                                  if b["reset"]["resolved_name"]})
            power_domain_membership[d.name] = {
                "switchable": d.name in switchable,
                "isolated": _domain_has_isolation(power_intent, d.name),
                "retained": _domain_has_retention(power_intent, d.name),
                "bind_targets": [b["target_instance"] for b in members],
                "reset_names_used": reset_names,
            }
            if not members:
                continue
            if d.name in switchable and not _domain_has_isolation(power_intent, d.name):
                findings.append(ConsistencyFinding(
                    SEVERITY_ERROR, CODE_SWITCHABLE_DOMAIN_BINDS_LACK_ISOLATION,
                    f"power domain {d.name} is switchable (a real power switch drives it) "
                    f"and has no isolation strategy, yet {len(members)} bind(s) in this "
                    f"chosen architecture are mounted inside it -- their observed signals "
                    f"would float into always-on logic the instant the domain is powered "
                    f"down",
                    {"domain": d.name, "bind_targets": [b["target_instance"] for b in members],
                     **_domain_evidence(power_intent, d.name)}))
            if len(reset_names) > 1:
                findings.append(ConsistencyFinding(
                    SEVERITY_WARNING, CODE_POWER_DOMAIN_RESET_SET_INCONSISTENT,
                    f"power domain {d.name}'s {len(members)} bound instance(s) collectively "
                    f"reference {len(reset_names)} distinct declared reset names "
                    f"({reset_names}) -- review whether that is intentional (genuinely "
                    f"separate reset networks inside one power domain) or a naming "
                    f"inconsistency across the chosen architecture",
                    {"domain": d.name, "reset_names": reset_names,
                     "bind_targets": [b["target_instance"] for b in members]}))

    # -- whole-topology clock coverage + unresolved-reset cross-check ---
    clock_domain_coverage: Dict[str, dict] = {}
    if topology["available"]:
        referenced_clocks = set()
        for b in resolved_binds:
            if b["clock"]["resolved_name"]:
                referenced_clocks.add(b["clock"]["resolved_name"])
            rn = b["reset"]["resolved_name"]
            if rn:
                reset_clock = topology["resets"][rn].get("clock")
                if reset_clock:
                    referenced_clocks.add(reset_clock)
                if topology["resets"][rn].get("clock_resolved") in ("UNKNOWN_CLOCK", "NOT_SPECIFIED"):
                    findings.append(ConsistencyFinding(
                        SEVERITY_WARNING, CODE_RESET_CLOCK_UNRESOLVED_REFERENCED_BY_BIND,
                        f"{b['target_instance']}: bound to declared reset {rn!r}, whose own "
                        f"clock dependency the DUT's clock/reset topology could not resolve "
                        f"({topology['resets'][rn].get('clock_resolved')}) -- the topology's "
                        f"own graph is incomplete for a reset this chosen architecture relies "
                        f"on",
                        {"target_instance": b["target_instance"], "reset": rn,
                         "clock_resolved": topology["resets"][rn].get("clock_resolved")}))

        for clock_name in sorted(topology["clocks"]):
            exercised = clock_name in referenced_clocks
            clock_domain_coverage[clock_name] = {"exercised_by_any_bind": exercised}
            if not exercised:
                findings.append(ConsistencyFinding(
                    SEVERITY_INFO, CODE_CLOCK_DOMAIN_NOT_EXERCISED_BY_ANY_BIND,
                    f"declared clock {clock_name!r} is not referenced, directly or through a "
                    f"dependent reset, by any bind in this chosen architecture",
                    {"clock": clock_name}))

    findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.code))
    worst = min((_SEVERITY_ORDER[f.severity] for f in findings), default=None)
    if worst is not None and worst <= _SEVERITY_ORDER[SEVERITY_WARNING]:
        status = STATUS_INCONSISTENCIES_FOUND
    else:
        status = STATUS_CONSISTENT
    reason = None
    if status == STATUS_CONSISTENT and not topology["available"] and power_intent is None:
        reason = ("no clock/reset topology or power intent evidence supplied -- only the "
                  "bind entries' own port lists were checked")

    return {
        "status": status,
        "reason": reason,
        "clock_reset_topology_available": topology["available"],
        "clock_reset_topology_reason": topology.get("reason"),
        "power_intent_available": power_intent is not None,
        "findings": [f.to_dict() for f in findings],
        "bind_resolution": resolved_binds,
        "power_domain_membership": power_domain_membership,
        "clock_domain_coverage": clock_domain_coverage,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_report_markdown(report: dict) -> str:
    lines = [f"# Holistic Clock/Reset/Power Consistency: {report['status']}"]
    if report.get("reason"):
        lines.append(f"\n{report['reason']}")
    lines.append(
        f"\nClock/reset topology available: {report['clock_reset_topology_available']}  "
        f"Power intent available: {report['power_intent_available']}\n")
    rows = report["findings"]
    lines.append(_connectivity.render_markdown_table(
        [("severity", "Severity"), ("code", "Code"), ("message", "Message")],
        rows, empty_note="(no findings)"))
    if report.get("power_domain_membership"):
        lines.append("\n## Power Domain Membership\n")
        dom_rows = [{"domain": name, **info}
                    for name, info in sorted(report["power_domain_membership"].items())]
        lines.append(_connectivity.render_markdown_table(
            [("domain", "Domain"), ("switchable", "Switchable"), ("isolated", "Isolated"),
             ("retained", "Retained"), ("bind_targets", "Bind Targets"),
             ("reset_names_used", "Reset Names Used")],
            dom_rows, empty_note="(no power domains declared)"))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI front door -- standalone, per this project's own house rule against
# editing cli.py/gates.py while under concurrent batch edit pressure.
# ---------------------------------------------------------------------------
def execute_verb(argv: Sequence[str]) -> int:
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(prog="holistic_clock_reset_power_consistency")
    parser.add_argument("--bind-entries", required=True)
    parser.add_argument("--clock-reset-facts", default=None)
    parser.add_argument("--upf", nargs="*", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))

    try:
        with open(args.bind_entries, "r", encoding="utf-8") as fh:
            bind_entries = _json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"could not read --bind-entries: {exc}", file=_sys.stderr)
        return 2

    clock_reset_facts = None
    if args.clock_reset_facts:
        try:
            with open(args.clock_reset_facts, "r", encoding="utf-8") as fh:
                clock_reset_facts = _json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"could not read --clock-reset-facts: {exc}", file=_sys.stderr)
            return 2

    power_intent = None
    if args.upf:
        power_intent = _power_intent_module.extract_power_intent(args.upf)

    try:
        report = build_holistic_consistency_report(
            bind_entries, clock_reset_facts=clock_reset_facts, power_intent=power_intent)
    except HolisticClockResetPowerConsistencyError as exc:
        print(f"{exc.reason}: {exc.detail}", file=_sys.stderr)
        return 2

    if args.json:
        print(_json.dumps(report, indent=2))
    else:
        print(render_report_markdown(report))

    if report["status"] == STATUS_CONSISTENT:
        return 0
    if report["status"] == STATUS_INCONSISTENCIES_FOUND:
        return 1
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys as _sys
    return execute_verb(argv if argv is not None else _sys.argv[1:])


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))
