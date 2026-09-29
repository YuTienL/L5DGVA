"""dv_harness/arbitration_policy_ir.py -- the Arbitration Policy IR: classifies a fabric's real
arbitration scheme (FIXED_PRIORITY, ROUND_ROBIN, WEIGHTED_ROUND_ROBIN, AGE_BASED, QOS_BASED, or
UNKNOWN) strictly from real RTL/spec evidence text the caller supplies, plus a starvation-risk
detector comparing a declared service-window/fairness bound against a declared request pattern.

THE GAP THIS CLOSES. The Engineering Discipline Rules already state a hard project rule ("Concurrent
bus arbitration": APB/AXI transactions across `block`/`branch_a*`/other branches sharing a resource
"must have an explicit, RTL-evidence-based arbitration policy modeled"), but nothing in this repo ever
classified WHAT that policy actually is, or asked whether it can starve a requester. A repo-wide grep
(`FIXED_PRIORITY`/`ROUND_ROBIN`/`WEIGHTED_ROUND_ROBIN`/`AGE_BASED`/`QOS_BASED`/`arbitration_scheme`/
`ArbitrationPolicy`) returned zero hits before this module. The real AMBA/SyoSil family
(`amba_fabric_discovery.py`, `amba_port_registry.py`, `amba_fabric_analysis.py`,
`amba_transaction_ir.py`, `amba_route_transform_predictor.py`, `amba_scoreboard_env.py`) discovers
fabric TOPOLOGY, PORTS, TRANSACTIONS and ROUTE TRANSFORMS -- none of them names or classifies an
arbitration SCHEME, and `shared_bus_resource_registry.py` (built earlier in this same batch) detects a
concurrency RACE between two task groups over a shared lock, never asking what the underlying
arbiter's own real policy is. This module fills exactly that one narrow gap and nothing else.

THE EVIDENCE TRUTH RULE, APPLIED LITERALLY: a scheme is classified ONLY from real evidence TEXT the
caller supplies (an RTL comment, an arbiter module's header, a spec/programming-guide paragraph) --
never from a component/instance/module NAME alone. `component_name`/`fabric_name` are accepted purely
as LABELS for the result; `classify_arbitration_scheme()` never reads either when deciding a scheme,
proven directly by a dedicated negative-control test (a component literally named
"round_robin_arbiter" whose supplied evidence text describes FIXED_PRIORITY arbitration classifies
FIXED_PRIORITY, not the name-implied scheme). Absent evidence text, or evidence text matching none of
the five real schemes' own phrase vocabulary, is honestly `NOT_AVAILABLE`/UNKNOWN -- never a guessed
scheme. Evidence citing more than one genuinely distinct scheme (with no containment relationship
between the matched phrases) is honestly `AMBIGUOUS`/UNKNOWN, naming every scheme it found, rather
than picking one arbitrarily.

CLASSIFICATION IS A LITERAL PHRASE MATCH, NOT A KEYWORD/NAME HEURISTIC. Each of the five real schemes
is recognised only via a small, fixed list of literal, case-insensitive phrases that unambiguously
name that scheme's arbitration behaviour (e.g. "weighted round robin arbitration", "fixed priority
arbitration", "arbitrated according to qos"). Text using different wording is honestly UNKNOWN rather
than guessed via a broader keyword scan -- narrower recognition is the deliberate, disclosed trade for
never fabricating a scheme the evidence does not actually state. One real, documented de-duplication
rule exists: a WEIGHTED_ROUND_ROBIN phrase (e.g. "weighted round robin arbitration") necessarily
contains the literal substring "round robin arbitration", which the plain ROUND_ROBIN phrase list also
matches as a real substring -- this is containment, not ambiguity, so WEIGHTED_ROUND_ROBIN (the more
specific, more informative fact) wins and plain ROUND_ROBIN is dropped from the matched set in that
one case only. Every other combination of two or more distinct matched schemes is reported AMBIGUOUS.

STARVATION-RISK DETECTION NEVER INVENTS A FAIRNESS BOUND. `extract_fairness_bound()` looks for a
declared service-window/fairness bound in the SAME evidence text the scheme was classified from (a
"maximum wait of N cycles", "no requester shall wait more than N cycles", "bounded to N grants",
"starvation-free within N cycles", or "fairness bound of N cycles" style statement) -- never a second,
separately-supplied number, and never a value this module computes on its own. Absent such a bound in
the evidence, this module never fabricates one:
  * If the classified scheme is FIXED_PRIORITY and the caller's DECLARED request pattern states a
    continuously-active high-priority requester alongside a present lower-priority requester, that is
    real, general arbitration theory (not RTL-specific): fixed-priority arbitration with continuous
    high-priority traffic can deny a lower-priority requester indefinitely, with no fairness mechanism
    on record to bound it -- reported `POTENTIAL_STARVATION`.
  * Otherwise, with no bound on record, the honest answer is `UNKNOWN` -- there is no evidence either
    way, and reporting `BOUNDED` would be an unearned claim.
When a bound IS found, it is compared against the caller's own DECLARED request pattern -- specifically
`max_grants_between_service`, a real caller-supplied worst-case wait figure (from a real simulation
measurement, a formal proof, or a documented worst-case analysis; this module performs none of those
itself and never derives this number). A pattern within the bound is `BOUNDED`; one exceeding it is
`POTENTIAL_STARVATION`; a bound with no such figure supplied at all is honestly `UNKNOWN` (a bound
exists, but nothing to compare it against was declared).

REUSE / FILE-SAFETY NOTE. Per this batch's isolation rule, this module imports nothing from any other
file in this project -- not `amba_fabric_analysis.py`, not `shared_bus_resource_registry.py`, not any
other new module in this batch. `evidence_text`, `request_pattern`, `fabric_name`/`component_name` are
all accepted as generic, duck-typed parameters (`request_pattern` tolerates a plain dict or any
attribute-bearing object via a small `.get()`-or-`getattr()` reader, the same convention
`requirement_risk_ir.py`'s `_lookup()` already established, re-derived locally here rather than
imported).

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it does not read RTL or a spec document itself (the caller
supplies the evidence text); it does not model a real arbiter's cycle-accurate grant sequence; it does
not decide a fairness bound is CORRECT, only whether a declared pattern fits inside a declared bound;
it never invents a fairness bound, a request pattern, or a scheme the evidence does not literally
state; it writes nothing, gates nothing, and approves nothing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: The five real arbitration schemes this module can classify, plus the honest catch-all. Fixed and
#: exhaustive -- a caller iterates this, never a hand-rolled list.
ARBITRATION_SCHEMES: Sequence[str] = (
    "FIXED_PRIORITY",
    "ROUND_ROBIN",
    "WEIGHTED_ROUND_ROBIN",
    "AGE_BASED",
    "QOS_BASED",
    "UNKNOWN",
)

#: The three honest states a scheme classification can be in. RESOLVED means exactly one real scheme's
#: phrase vocabulary matched (after the WRR/round-robin de-duplication rule). AMBIGUOUS means two or
#: more genuinely distinct schemes were cited with no containment relationship -- never resolved by
#: guessing. NOT_AVAILABLE means no evidence text was supplied, or none of the five schemes' phrases
#: matched anything in it.
SCHEME_CLASSIFICATION_STATUSES = ("RESOLVED", "AMBIGUOUS", "NOT_AVAILABLE")

#: The three honest starvation-risk verdicts. Never a fourth value, never a fifth -- an unmeasurable
#: case is always UNKNOWN, never silently folded into BOUNDED.
STARVATION_STATUSES = ("POTENTIAL_STARVATION", "BOUNDED", "UNKNOWN")

#: Literal, case-insensitive phrase vocabulary per scheme. Checked in this fixed PRECEDENCE ORDER
#: (most specific first) so a WEIGHTED_ROUND_ROBIN phrase's real ROUND_ROBIN substring is resolved by
#: the de-duplication rule below rather than misread as two schemes disagreeing.
SCHEME_PRECEDENCE_ORDER: Sequence[str] = (
    "WEIGHTED_ROUND_ROBIN",
    "QOS_BASED",
    "AGE_BASED",
    "FIXED_PRIORITY",
    "ROUND_ROBIN",
)

SCHEME_PHRASES: Dict[str, Sequence[str]] = {
    "WEIGHTED_ROUND_ROBIN": (
        "weighted round robin arbitration",
        "weighted round-robin arbitration",
        "weighted round robin scheme",
        "weighted round-robin scheme",
        "weighted round robin (wrr)",
        "wrr arbitration",
    ),
    "QOS_BASED": (
        "qos-based arbitration",
        "qos based arbitration",
        "arbitration based on qos",
        "quality-of-service based arbitration",
        "quality of service based arbitration",
        "arbitrated according to qos",
        "qos priority arbitration",
    ),
    "AGE_BASED": (
        "age-based arbitration",
        "age based arbitration",
        "oldest request is granted",
        "oldest pending request is granted",
        "arbitration based on request age",
        "aging-based arbitration",
        "arbitration is based on the age of each request",
    ),
    "FIXED_PRIORITY": (
        "fixed priority arbitration",
        "fixed-priority arbitration",
        "static priority arbitration",
        "fixed priority scheme",
        "strict priority arbitration",
        "priority order is fixed",
        "highest priority requester is always granted",
    ),
    "ROUND_ROBIN": (
        "round robin arbitration",
        "round-robin arbitration",
        "round robin scheme",
        "round-robin scheme",
        "rotating priority arbitration",
        "circular priority arbitration",
    ),
}

#: Regex patterns for a declared service-window/fairness bound, each with a captured integer value and
#: an optional captured unit. Checked in order; the first match wins. Never invented -- these only
#: extract a number the evidence text itself literally states.
FAIRNESS_BOUND_PATTERNS: Sequence[str] = (
    r"(?:maximum|max)\s+wait(?:\s+time)?\s+of\s+(\d+)\s*(cycles|clock cycles|clocks|ns)?",
    r"no\s+requester\s+(?:shall|will|can|may)\s+wait\s+more\s+than\s+(\d+)\s*(cycles|clock cycles|clocks)?",
    r"bounded\s+to\s+(\d+)\s*(cycles|grants)",
    r"starvation-free\s+within\s+(\d+)\s*(cycles|grants|arbitration cycles)",
    r"fairness\s+bound\s+of\s+(\d+)\s*(cycles|grants)?",
    r"guaranteed\s+(?:a\s+)?grant\s+within\s+(\d+)\s*(cycles|arbitration cycles)",
)


class ArbitrationPolicyIRError(Exception):
    """Raised only for a genuinely malformed caller input (an invalid request_pattern value) -- never
    for an honest absence of evidence, which is always a reported UNKNOWN/NOT_AVAILABLE result."""


@dataclass
class EvidenceCitation:
    """One real matched phrase, tied to the scheme it supports."""
    scheme: str
    matched_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FairnessBound:
    """A declared service-window/fairness bound extracted verbatim from real evidence text -- never a
    caller-supplied bare number and never a value this module invents."""
    value: int
    unit: str
    matched_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArbitrationSchemeResult:
    """The honest scheme classification: RESOLVED names exactly one real scheme; AMBIGUOUS names every
    distinct scheme the evidence cited with no resolution; NOT_AVAILABLE means nothing matched."""
    scheme: str  # one of ARBITRATION_SCHEMES
    status: str  # one of SCHEME_CLASSIFICATION_STATUSES
    evidence: List[EvidenceCitation]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheme": self.scheme,
            "status": self.status,
            "evidence": [e.to_dict() for e in self.evidence],
            "reason": self.reason,
        }


@dataclass
class StarvationRiskResult:
    """The honest starvation-risk verdict: a declared fairness bound (if any, cited verbatim) compared
    against a caller-declared request pattern -- never a bound or pattern this module invented."""
    status: str  # one of STARVATION_STATUSES
    fairness_bound: Optional[FairnessBound]
    reason: str
    request_pattern_summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "fairness_bound": self.fairness_bound.to_dict() if self.fairness_bound else None,
            "reason": self.reason,
            "request_pattern_summary": dict(self.request_pattern_summary),
        }


@dataclass
class ArbitrationPolicyIR:
    """The full record for one fabric/arbiter: its classified scheme plus its starvation-risk
    assessment, both derived strictly from the same supplied evidence text."""
    fabric_name: Optional[str]
    component_name: Optional[str]
    scheme_result: ArbitrationSchemeResult
    starvation_result: StarvationRiskResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fabric_name": self.fabric_name,
            "component_name": self.component_name,
            "scheme": self.scheme_result.to_dict(),
            "starvation_risk": self.starvation_result.to_dict(),
        }


def _lookup(obj: Any, key: str) -> Any:
    """Duck-typed read of one field from `obj`: a Mapping (dict-like, via `.get`) or any
    attribute-bearing object. Never raises on an object that has neither -- returns None, same as a
    missing key. Mirrors `requirement_risk_ir._lookup()`'s contract; re-derived locally rather than
    imported per this batch's file-safety scope (no cross-import between new modules in this batch)."""
    if obj is None:
        return None
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except TypeError:
            pass
    return getattr(obj, key, None)


def classify_arbitration_scheme(evidence_text: Optional[str], *,
                                 component_name: Optional[str] = None) -> ArbitrationSchemeResult:
    """Classify a fabric's real arbitration scheme strictly from `evidence_text` -- real RTL/spec
    prose the caller supplies. `component_name` is accepted ONLY as a label; it is never read by the
    classification logic below (proven directly by a dedicated negative-control test)."""
    if not evidence_text or not evidence_text.strip():
        return ArbitrationSchemeResult(
            scheme="UNKNOWN", status="NOT_AVAILABLE", evidence=[],
            reason="no evidence text supplied -- an arbitration scheme cannot be classified from a "
                   "component/instance name alone")

    lower = evidence_text.lower()
    matched: Dict[str, List[str]] = {}
    for scheme in SCHEME_PRECEDENCE_ORDER:
        hits = [phrase for phrase in SCHEME_PHRASES[scheme] if phrase in lower]
        if hits:
            matched[scheme] = hits

    # De-duplication rule: a WEIGHTED_ROUND_ROBIN phrase always contains the literal substring a plain
    # ROUND_ROBIN phrase also matches (e.g. "weighted round robin arbitration" contains "round robin
    # arbitration"). That is containment, not two disagreeing schemes -- the more specific fact wins.
    if "WEIGHTED_ROUND_ROBIN" in matched and "ROUND_ROBIN" in matched:
        del matched["ROUND_ROBIN"]

    if not matched:
        return ArbitrationSchemeResult(
            scheme="UNKNOWN", status="NOT_AVAILABLE", evidence=[],
            reason="no recognized arbitration-scheme phrase found in the supplied evidence text")

    if len(matched) == 1:
        scheme = next(iter(matched))
        hits = matched[scheme]
        evidence = [EvidenceCitation(scheme=scheme, matched_text=h) for h in hits]
        return ArbitrationSchemeResult(
            scheme=scheme, status="RESOLVED", evidence=evidence,
            reason=f"matched {scheme} phrase(s) in evidence: {hits}")

    evidence = [EvidenceCitation(scheme=scheme, matched_text=h)
                for scheme, hits in matched.items() for h in hits]
    return ArbitrationSchemeResult(
        scheme="UNKNOWN", status="AMBIGUOUS", evidence=evidence,
        reason=f"multiple distinct arbitration schemes cited in evidence with no resolution: "
               f"{sorted(matched)}")


def extract_fairness_bound(evidence_text: Optional[str]) -> Optional[FairnessBound]:
    """Extract a declared service-window/fairness bound from real evidence text via a fixed set of
    literal patterns. Returns None -- never a guessed or defaulted bound -- when nothing matches."""
    if not evidence_text:
        return None
    for pattern in FAIRNESS_BOUND_PATTERNS:
        m = re.search(pattern, evidence_text, re.IGNORECASE)
        if m:
            unit = (m.group(2) or "cycles").strip()
            return FairnessBound(value=int(m.group(1)), unit=unit, matched_text=m.group(0))
    return None


def detect_starvation_risk(evidence_text: Optional[str], scheme: str,
                            request_pattern: Any = None) -> StarvationRiskResult:
    """Compare a declared fairness bound (extracted from the SAME `evidence_text` the scheme was
    classified from -- never a second, separately-invented number) against a caller-DECLARED request
    pattern. Never invents a bound the evidence does not state, and never claims BOUNDED without a
    real declared worst-case figure to compare against."""
    request_pattern = request_pattern if request_pattern is not None else {}
    summary: Dict[str, Any] = {}
    for key in ("continuous_high_priority_traffic", "low_priority_requester_present",
                "max_grants_between_service", "requester_count"):
        val = _lookup(request_pattern, key)
        if val is not None:
            summary[key] = val

    bound = extract_fairness_bound(evidence_text)

    if bound is None:
        continuous_high_priority = bool(_lookup(request_pattern, "continuous_high_priority_traffic"))
        low_priority_present_raw = _lookup(request_pattern, "low_priority_requester_present")
        low_priority_present = True if low_priority_present_raw is None else bool(low_priority_present_raw)
        if scheme == "FIXED_PRIORITY" and continuous_high_priority and low_priority_present:
            return StarvationRiskResult(
                status="POTENTIAL_STARVATION", fairness_bound=None,
                reason=("no fairness/service-window bound declared in evidence; FIXED_PRIORITY "
                        "arbitration with a continuously-active high-priority requester can "
                        "indefinitely deny a lower-priority requester"),
                request_pattern_summary=summary)
        return StarvationRiskResult(
            status="UNKNOWN", fairness_bound=None,
            reason=("no fairness/service-window bound found in the supplied evidence text; cannot "
                    "assess starvation risk from this evidence alone"),
            request_pattern_summary=summary)

    observed = _lookup(request_pattern, "max_grants_between_service")
    if observed is None:
        return StarvationRiskResult(
            status="UNKNOWN", fairness_bound=bound,
            reason=(f"a declared fairness bound exists ({bound.value} {bound.unit}) but the request "
                    f"pattern declares no observed/measured worst-case wait to compare against it"),
            request_pattern_summary=summary)

    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise ArbitrationPolicyIRError(
            f"request_pattern['max_grants_between_service']={observed!r} is not a valid numeric "
            f"worst-case wait figure")

    if observed <= bound.value:
        return StarvationRiskResult(
            status="BOUNDED", fairness_bound=bound,
            reason=(f"declared worst-case wait ({observed}) is within the declared fairness bound "
                    f"({bound.value} {bound.unit})"),
            request_pattern_summary=summary)

    return StarvationRiskResult(
        status="POTENTIAL_STARVATION", fairness_bound=bound,
        reason=(f"declared worst-case wait ({observed}) exceeds the declared fairness bound "
                f"({bound.value} {bound.unit})"),
        request_pattern_summary=summary)


def build_arbitration_policy_ir(evidence_text: Optional[str], *,
                                 fabric_name: Optional[str] = None,
                                 component_name: Optional[str] = None,
                                 request_pattern: Any = None) -> ArbitrationPolicyIR:
    """Build the full `ArbitrationPolicyIR` for one fabric/arbiter: classify its scheme, then assess
    starvation risk against the SAME evidence text plus the caller's declared request pattern."""
    scheme_result = classify_arbitration_scheme(evidence_text, component_name=component_name)
    starvation_result = detect_starvation_risk(evidence_text, scheme_result.scheme, request_pattern)
    return ArbitrationPolicyIR(
        fabric_name=fabric_name, component_name=component_name,
        scheme_result=scheme_result, starvation_result=starvation_result)


def format_arbitration_policy_report(ir: ArbitrationPolicyIR) -> str:
    """Human-readable rendering of one `ArbitrationPolicyIR`."""
    label = ir.fabric_name or ir.component_name or "UNKNOWN"
    lines = [f"Arbitration Policy IR: {label}",
             f"  scheme: {ir.scheme_result.scheme}  [{ir.scheme_result.status}]",
             f"    {ir.scheme_result.reason}"]
    for e in ir.scheme_result.evidence:
        lines.append(f"    evidence[{e.scheme}]: {e.matched_text!r}")
    lines.append(f"  starvation_risk: {ir.starvation_result.status}")
    lines.append(f"    {ir.starvation_result.reason}")
    if ir.starvation_result.fairness_bound:
        b = ir.starvation_result.fairness_bound
        lines.append(f"    fairness_bound: {b.value} {b.unit}  (evidence: {b.matched_text!r})")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.arbitration_policy_ir",
        description="Classify a fabric's real arbitration scheme (FIXED_PRIORITY, ROUND_ROBIN, "
                    "WEIGHTED_ROUND_ROBIN, AGE_BASED, QOS_BASED, or UNKNOWN) strictly from supplied "
                    "RTL/spec evidence text, plus a starvation-risk assessment against a declared "
                    "request pattern. Reads and reports only -- writes nothing, gates nothing.")
    ap.add_argument("--evidence-file", default=None,
                     help="Path to a text file containing the real RTL/spec evidence to classify.")
    ap.add_argument("--request-pattern-file", default=None,
                     help="JSON file with a declared request pattern (continuous_high_priority_traffic, "
                          "low_priority_requester_present, max_grants_between_service, requester_count).")
    ap.add_argument("--fabric-name", default=None, help="Label only -- never used for classification.")
    ap.add_argument("--component-name", default=None, help="Label only -- never used for classification.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable IR.")
    a = ap.parse_args(argv)

    evidence_text = ""
    if a.evidence_file:
        with open(a.evidence_file, "r", encoding="utf-8") as f:
            evidence_text = f.read()

    request_pattern: Dict[str, Any] = {}
    if a.request_pattern_file:
        with open(a.request_pattern_file, "r", encoding="utf-8") as f:
            request_pattern = json.load(f)

    ir = build_arbitration_policy_ir(
        evidence_text, fabric_name=a.fabric_name, component_name=a.component_name,
        request_pattern=request_pattern)

    if a.json:
        print(json.dumps(ir.to_dict(), indent=2))
    else:
        print(format_arbitration_policy_report(ir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
