"""dv_harness/backpressure_model.py -- classifies legal-BACKPRESSURE-TOLERANCE (how long a named
AMBA channel may legally stall before its own protocol/spec/RTL evidence considers that stall a
violation) strictly from caller-supplied evidence -- never invents a stall-tolerance number the
evidence does not state.

THE GAP THIS CLOSES. `design_intent.py` already models `backpressure_conditions` -- a documented,
citation-required list of conditions under which backpressure/stalling is LEGAL AT ALL (a boolean
per named condition: "is stalling here permitted, yes/no, per this spec section"). Nothing in this
repo answers the adjacent, narrower quantitative question a scoreboard/checker actually needs next:
GIVEN that a stall is legal on this named channel, HOW LONG may it legally last -- a bounded number
of cycles/wait-states, or an unbounded stall the spec/RTL evidence explicitly permits -- and is a
caller-supplied OBSERVED worst-case stall within that bound. A repo-wide grep
(`stall_tolerance`/`legal_backpressure`/`BackpressureToleranceIR`) returned zero hits before this
module. The real AMBA/SyoSil family (`amba_fabric_discovery.py`, `amba_port_registry.py`,
`amba_fabric_analysis.py`, `amba_transaction_ir.py`, `amba_route_transform_predictor.py`,
`amba_scoreboard_env.py`) discovers fabric TOPOLOGY, PORTS, TRANSACTIONS and ROUTE TRANSFORMS --
none of them classifies a CHANNEL'S legal stall duration, and this session's own
`arbitration_policy_ir.py` classifies an ARBITER'S scheme/starvation risk, a different concern
(who gets granted next, not how long a handshake channel may legally hold VALID/READY apart).

THE EVIDENCE TRUTH RULE, APPLIED LITERALLY: a channel's tolerance is classified ONLY from real
evidence TEXT the caller supplies (an RTL comment, a protocol/programming-guide paragraph, a
register/timing-spec sentence) -- never from the CHANNEL NAME alone. `AXI_AW`/`AHB_HREADY`/
`APB_PREADY`/`GENERIC_VALID_READY` are fixed, exhaustive LABELS this module classifies against;
none of them carries an assumed legal-stall duration from the protocol's own general reputation
(e.g. "AXI READY may always be held low indefinitely" is a real architectural fact about some AMBA
protocols, but this module refuses to assert it unless the caller's own supplied evidence text
states it for THIS channel) -- proven directly by a dedicated negative-control test (a channel
literally named `AXI_AW` with no supplied evidence text classifies `NOT_AVAILABLE`, never a guessed
UNBOUNDED). Evidence text matching neither a bounded nor an unbounded phrase is honestly
`NOT_AVAILABLE` -- never a guessed tolerance. Evidence citing BOTH a bounded stall AND an unbounded
stall for the same channel (no containment relationship between the two claims) is honestly
`AMBIGUOUS`, naming both matched phrases, rather than picking one.

CLASSIFICATION IS A LITERAL PHRASE MATCH, NOT A KEYWORD/NAME HEURISTIC -- the same discipline
`arbitration_policy_ir.classify_arbitration_scheme()` already applies to its own five-scheme
vocabulary, reused here for the two-class BOUNDED/UNBOUNDED vocabulary. `BOUNDED_STALL_PATTERNS` are
a small, fixed list of literal, case-insensitive regex phrases capturing a real declared integer
cycle/wait-state count (e.g. "maximum stall of N cycles", "must assert READY within N cycles",
"up to N wait states", "stall no more than N clock cycles"). `UNBOUNDED_STALL_PHRASES` are a small,
fixed list of literal phrases stating no bound exists (e.g. "may stall indefinitely", "no bound on
the number of wait states", "unbounded backpressure is legal"). Text using different wording is
honestly `NOT_AVAILABLE` rather than guessed via a broader keyword scan -- narrower recognition is
the deliberate, disclosed trade for never fabricating a tolerance the evidence does not literally
state.

STALL-VIOLATION DETECTION NEVER INVENTS AN OBSERVED VALUE. `detect_stall_violation()` compares a
`ChannelToleranceResult` already classified from real evidence against a caller-DECLARED observed
worst-case stall duration (a real simulation/waveform measurement, or a formal-proof/documented
worst-case figure; this module performs none of those measurements itself and never derives this
number). A `NOT_AVAILABLE`/`AMBIGUOUS` tolerance can never judge a violation (honestly `UNKNOWN` --
there is no resolved bound, or two disagreeing claims, to compare against); an `UNBOUNDED` tolerance
can never be violated by construction (`WITHIN_TOLERANCE`, since no bound exists to exceed); a
`BOUNDED` tolerance compares the caller's real observed figure against the extracted cycle count --
within it is `WITHIN_TOLERANCE`, exceeding it is `VIOLATION`. An absent observed value against a
resolved `BOUNDED` tolerance is honestly `UNKNOWN` (a bound exists, but nothing to compare it
against was supplied).

REUSE / FILE-SAFETY NOTE. Per this batch's isolation rule, this module imports nothing from any
other new-this-batch file -- not `arbitration_policy_ir.py`, not `amba_master_slave_constraint_ir.py`,
not any other module built in this same session's batch. It reuses only `dv_harness.connectivity.
render_markdown_table` (a stable, pre-existing, non-claimed module -- this repo's one parameterized
table renderer) for its optional markdown rendering, and `dv_harness.models.Status` (also stable and
pre-existing) purely to assert this module's own status vocabulary never collides with a real
stage-gate verdict. `evidence` is accepted as a generic, duck-typed parameter (a bare string treated
as evidence text, or any mapping/attribute-bearing object carrying `evidence_text`/`text`/
`citation`), read via a small local `.get()`-or-`getattr()` reader -- the same convention
`arbitration_policy_ir._lookup()`/`requirement_risk_ir._lookup()` already established, re-derived
locally here rather than imported.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it does not read RTL or a spec document itself (the
caller supplies the evidence text); it does not model a channel's cycle-accurate handshake
behaviour; it does not decide a declared bound is CORRECT, only whether a caller-declared observed
stall fits inside a declared bound; it never invents a stall-tolerance number, an observed stall
duration, or a channel's legality the evidence does not literally state; it writes nothing, gates
nothing, and approves nothing. There is deliberately no `dv-harness` CLI verb and no `STAGE_GATES`
entry (`gates.py`/`cli.py`/`CLAUDE.md` are untouched, per this batch's file-safety scope) -- the
front door is `python -m dv_harness.backpressure_model`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence


class BackpressureModelError(Exception):
    """Raised only for a genuinely malformed caller input (an unrecognized channel name, an invalid
    observed-stall value) -- never for an honest absence of evidence, which is always a reported
    NOT_AVAILABLE/UNKNOWN result."""


#: The eight named channels this module classifies, fixed and exhaustive -- a caller iterates this,
#: never a hand-rolled list. The five real AXI channels, AHB's single READY-gated handshake signal,
#: APB's single READY-gated handshake signal, and one generic VALID/READY handshake for a protocol
#: with no fixed channel-name convention of its own.
AMBA_CHANNELS: Sequence[str] = (
    "AXI_AW",
    "AXI_W",
    "AXI_B",
    "AXI_AR",
    "AXI_R",
    "AHB_HREADY",
    "APB_PREADY",
    "GENERIC_VALID_READY",
)

#: The three honest states a channel's tolerance classification can be in. RESOLVED means exactly
#: one real tolerance class (BOUNDED xor UNBOUNDED) matched the supplied evidence. AMBIGUOUS means
#: both were cited with no resolution. NOT_AVAILABLE means no evidence was supplied, or none of the
#: recognized phrases matched anything in it.
TOLERANCE_CLASSIFICATION_STATUSES = ("RESOLVED", "AMBIGUOUS", "NOT_AVAILABLE")

#: The three honest tolerance classes a resolved channel can carry. UNKNOWN is the class recorded
#: alongside AMBIGUOUS/NOT_AVAILABLE status -- never BOUNDED or UNBOUNDED without a RESOLVED status.
TOLERANCE_CLASSES = ("BOUNDED", "UNBOUNDED", "UNKNOWN")

#: The three honest stall-violation verdicts. Never a fourth value -- an unmeasurable or unresolved
#: case is always UNKNOWN, never silently folded into WITHIN_TOLERANCE.
STALL_VIOLATION_STATUSES = ("VIOLATION", "WITHIN_TOLERANCE", "UNKNOWN")

#: Regex patterns for a declared BOUNDED stall duration, each with a captured integer value and an
#: optional captured unit. Checked in order; the first match wins. Never invented -- these only
#: extract a number the evidence text itself literally states.
BOUNDED_STALL_PATTERNS: Sequence[str] = (
    r"(?:maximum|max)\s+stall(?:\s+duration)?\s+of\s+(\d+)\s*(cycles|clock cycles|clocks)?",
    r"must\s+assert\s+\w*ready\w*\s+within\s+(\d+)\s*(cycles|clock cycles|clocks)?",
    r"(?:up\s+to|at\s+most)\s+(\d+)\s*(wait\s+states|cycles|clock cycles)",
    r"bounded\s+to\s+(\d+)\s*(cycles|wait states)",
    r"stall(?:s|ing)?\s+no\s+more\s+than\s+(\d+)\s*(cycles|clock cycles)",
    r"legal\s+stall\s+(?:duration|window)\s+of\s+(\d+)\s*(cycles)?",
    r"(\d+)\s*(cycles|clock cycles)\s+maximum\s+wait\s+states?",
)

#: Literal, case-insensitive phrases stating an UNBOUNDED legal stall -- checked only when at least
#: one appears verbatim in the evidence text. Never inferred from a protocol/channel name.
UNBOUNDED_STALL_PHRASES: Sequence[str] = (
    "may stall indefinitely",
    "may be held low indefinitely",
    "may be deasserted indefinitely",
    "may deassert ready indefinitely",
    "hold off ready indefinitely",
    "no bound on the number of wait states",
    "no upper bound on stall duration",
    "unbounded backpressure is legal",
    "an unbounded number of cycles",
    "no maximum number of wait states",
)


@dataclass
class EvidenceCitation:
    """One real matched phrase, tied to the tolerance class it supports."""
    tolerance_class: str
    matched_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChannelToleranceResult:
    """The honest tolerance classification for one named channel: RESOLVED names exactly one real
    class (BOUNDED with a real cycle count, or UNBOUNDED); AMBIGUOUS names both classes the evidence
    cited with no resolution; NOT_AVAILABLE means nothing matched."""
    channel: str  # one of AMBA_CHANNELS
    tolerance_class: str  # one of TOLERANCE_CLASSES
    status: str  # one of TOLERANCE_CLASSIFICATION_STATUSES
    max_stall_cycles: Optional[int]
    evidence: List[EvidenceCitation]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "tolerance_class": self.tolerance_class,
            "status": self.status,
            "max_stall_cycles": self.max_stall_cycles,
            "evidence": [e.to_dict() for e in self.evidence],
            "reason": self.reason,
        }


@dataclass
class StallViolationResult:
    """The honest stall-violation verdict: a caller-DECLARED observed worst-case stall duration
    compared against an already-classified `ChannelToleranceResult` -- never a bound or observation
    this module invents."""
    status: str  # one of STALL_VIOLATION_STATUSES
    channel: str
    observed_max_stall_cycles: Optional[float]
    declared_max_stall_cycles: Optional[int]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackpressureModel:
    """The full per-project record: one `ChannelToleranceResult` for every channel in
    `AMBA_CHANNELS`, built from whatever evidence the caller actually supplied per channel."""
    results: Dict[str, ChannelToleranceResult]

    def to_dict(self) -> Dict[str, Any]:
        return {ch: r.to_dict() for ch, r in self.results.items()}


def _lookup(obj: Any, key: str) -> Any:
    """Duck-typed read of one field from `obj`: a Mapping (dict-like, via `.get`) or any
    attribute-bearing object. Never raises on an object that has neither -- returns None, same as a
    missing key. Mirrors `arbitration_policy_ir._lookup()`'s contract; re-derived locally rather than
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


def _evidence_text(evidence: Any) -> Optional[str]:
    """Extract the real evidence TEXT from a duck-typed `evidence` value: a bare string is used
    directly; a mapping/attribute-bearing object is read via `evidence_text` then `text`. Never
    invents text from a channel name or any other field."""
    if evidence is None:
        return None
    if isinstance(evidence, str):
        return evidence
    for key in ("evidence_text", "text"):
        val = _lookup(evidence, key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def classify_channel_tolerance(channel: str, evidence: Any) -> ChannelToleranceResult:
    """Classify one named channel's legal-backpressure-tolerance strictly from `evidence`'s own real
    text -- never from `channel` itself, which is used purely as a label. `channel` must be one of
    `AMBA_CHANNELS`; an unrecognized name raises `BackpressureModelError` (a genuine caller-usage
    defect, distinct from an honest absence of evidence)."""
    if channel not in AMBA_CHANNELS:
        raise BackpressureModelError(
            f"channel={channel!r} is not one of the recognized AMBA_CHANNELS: {list(AMBA_CHANNELS)}")

    evidence_text = _evidence_text(evidence)
    if not evidence_text or not evidence_text.strip():
        return ChannelToleranceResult(
            channel=channel, tolerance_class="UNKNOWN", status="NOT_AVAILABLE",
            max_stall_cycles=None, evidence=[],
            reason="no evidence text supplied -- a legal stall tolerance cannot be classified from "
                   "a channel name alone")

    lower = evidence_text.lower()

    bounded_matches: List[EvidenceCitation] = []
    bounded_value: Optional[int] = None
    for pattern in BOUNDED_STALL_PATTERNS:
        m = re.search(pattern, evidence_text, re.IGNORECASE)
        if m:
            bounded_value = int(m.group(1))
            bounded_matches.append(EvidenceCitation(tolerance_class="BOUNDED", matched_text=m.group(0)))
            break

    unbounded_matches = [EvidenceCitation(tolerance_class="UNBOUNDED", matched_text=phrase)
                          for phrase in UNBOUNDED_STALL_PHRASES if phrase in lower]

    if bounded_matches and unbounded_matches:
        evidence_list = bounded_matches + unbounded_matches
        return ChannelToleranceResult(
            channel=channel, tolerance_class="UNKNOWN", status="AMBIGUOUS",
            max_stall_cycles=None, evidence=evidence_list,
            reason="evidence cites both a BOUNDED and an UNBOUNDED legal stall for this channel "
                   "with no resolution between the two claims")

    if bounded_matches:
        return ChannelToleranceResult(
            channel=channel, tolerance_class="BOUNDED", status="RESOLVED",
            max_stall_cycles=bounded_value, evidence=bounded_matches,
            reason=f"matched a declared bounded-stall phrase in evidence: "
                   f"{bounded_matches[0].matched_text!r} ({bounded_value} cycles)")

    if unbounded_matches:
        return ChannelToleranceResult(
            channel=channel, tolerance_class="UNBOUNDED", status="RESOLVED",
            max_stall_cycles=None, evidence=unbounded_matches,
            reason=f"matched an unbounded-legal-stall phrase in evidence: "
                   f"{unbounded_matches[0].matched_text!r}")

    return ChannelToleranceResult(
        channel=channel, tolerance_class="UNKNOWN", status="NOT_AVAILABLE",
        max_stall_cycles=None, evidence=[],
        reason="no recognized bounded- or unbounded-stall phrase found in the supplied evidence text")


def build_backpressure_model(channel_evidence: Any = None) -> BackpressureModel:
    """Build the full `BackpressureModel` over every channel in `AMBA_CHANNELS`. `channel_evidence`
    is a duck-typed mapping of channel name -> evidence (string or evidence-shaped object); a channel
    absent from it is classified with `evidence=None`, which always resolves to `NOT_AVAILABLE` --
    never silently omitted from the model."""
    channel_evidence = channel_evidence if channel_evidence is not None else {}
    results: Dict[str, ChannelToleranceResult] = {}
    for channel in AMBA_CHANNELS:
        entry = _lookup(channel_evidence, channel)
        results[channel] = classify_channel_tolerance(channel, entry)
    return BackpressureModel(results=results)


def detect_stall_violation(tolerance_result: ChannelToleranceResult,
                            observed_max_stall_cycles: Any = None) -> StallViolationResult:
    """Compare a caller-DECLARED observed worst-case stall (a real simulation/waveform measurement
    or documented worst-case figure; this module performs none of those measurements itself) against
    an already-classified `tolerance_result`. Never invents an observed value or a bound."""
    channel = tolerance_result.channel

    if tolerance_result.status != "RESOLVED":
        return StallViolationResult(
            status="UNKNOWN", channel=channel,
            observed_max_stall_cycles=None, declared_max_stall_cycles=None,
            reason=(f"tolerance for {channel} is {tolerance_result.status}, not RESOLVED -- there is "
                    f"no reliable bound (or class) to compare an observed stall against"))

    if tolerance_result.tolerance_class == "UNBOUNDED":
        return StallViolationResult(
            status="WITHIN_TOLERANCE", channel=channel,
            observed_max_stall_cycles=(observed_max_stall_cycles
                                        if isinstance(observed_max_stall_cycles, (int, float))
                                        and not isinstance(observed_max_stall_cycles, bool) else None),
            declared_max_stall_cycles=None,
            reason=f"{channel}'s legal stall tolerance is UNBOUNDED -- no declared bound exists to "
                   f"exceed")

    # tolerance_class == "BOUNDED"
    if observed_max_stall_cycles is None:
        return StallViolationResult(
            status="UNKNOWN", channel=channel,
            observed_max_stall_cycles=None,
            declared_max_stall_cycles=tolerance_result.max_stall_cycles,
            reason=(f"a declared bound exists for {channel} "
                    f"({tolerance_result.max_stall_cycles} cycles) but no observed worst-case stall "
                    f"was supplied to compare against it"))

    if isinstance(observed_max_stall_cycles, bool) or not isinstance(observed_max_stall_cycles, (int, float)):
        raise BackpressureModelError(
            f"observed_max_stall_cycles={observed_max_stall_cycles!r} is not a valid numeric "
            f"worst-case stall figure")

    if observed_max_stall_cycles <= tolerance_result.max_stall_cycles:
        return StallViolationResult(
            status="WITHIN_TOLERANCE", channel=channel,
            observed_max_stall_cycles=observed_max_stall_cycles,
            declared_max_stall_cycles=tolerance_result.max_stall_cycles,
            reason=(f"observed worst-case stall ({observed_max_stall_cycles}) is within the declared "
                    f"legal bound ({tolerance_result.max_stall_cycles} cycles) for {channel}"))

    return StallViolationResult(
        status="VIOLATION", channel=channel,
        observed_max_stall_cycles=observed_max_stall_cycles,
        declared_max_stall_cycles=tolerance_result.max_stall_cycles,
        reason=(f"observed worst-case stall ({observed_max_stall_cycles}) exceeds the declared legal "
                f"bound ({tolerance_result.max_stall_cycles} cycles) for {channel}"))


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status vocabularies (`TOLERANCE_CLASSIFICATION_STATUSES`,
    `STALL_VIOLATION_STATUSES`) must share no token with `dv_harness.models.Status` -- the same
    discipline several sibling modules in this project already apply to their own vocabularies, so a
    reader can never mistake a tolerance-classification status for a real stage-gate verdict."""
    from dv_harness.models import Status
    verdict_tokens = {s.value for s in Status}
    this_module_tokens = set(TOLERANCE_CLASSIFICATION_STATUSES) | set(STALL_VIOLATION_STATUSES)
    collision = verdict_tokens & this_module_tokens
    if collision:
        raise AssertionError(
            f"backpressure_model vocabulary collides with dv_harness.models.Status: {collision}")


def format_backpressure_report(model: BackpressureModel) -> str:
    """Human-readable rendering of a full `BackpressureModel`, reusing `connectivity.py`'s one
    parameterized markdown-table renderer rather than a second hand-rolled table loop."""
    from dv_harness.connectivity import render_markdown_table
    rows = []
    for channel in AMBA_CHANNELS:
        r = model.results[channel]
        rows.append({
            "channel": channel,
            "tolerance_class": r.tolerance_class,
            "status": r.status,
            "max_stall_cycles": r.max_stall_cycles if r.max_stall_cycles is not None else "",
            "reason": r.reason,
        })
    columns = [("channel", "Channel"), ("tolerance_class", "Tolerance Class"),
               ("status", "Status"), ("max_stall_cycles", "Max Stall (cycles)"),
               ("reason", "Reason")]
    return render_markdown_table(columns, rows, empty_note="(no channels classified)")


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.backpressure_model",
        description="Classify legal-backpressure-tolerance (BOUNDED/UNBOUNDED/NOT_AVAILABLE, plus a "
                    "declared max-stall-cycles figure where BOUNDED) on named AMBA channels (AXI "
                    "AW/W/B/AR/R, AHB HREADY, APB PREADY, generic VALID/READY) strictly from supplied "
                    "per-channel RTL/spec evidence text. Reads and reports only -- writes nothing, "
                    "gates nothing.")
    ap.add_argument("--evidence-file", default=None,
                     help="JSON file: {\"<channel>\": \"<evidence text>\", ...}. A channel absent "
                          "from the file classifies NOT_AVAILABLE.")
    ap.add_argument("--observed-stalls-file", default=None,
                     help="JSON file: {\"<channel>\": <observed max stall cycles>, ...} for an "
                          "optional per-channel stall-violation check.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable model.")
    a = ap.parse_args(argv)

    channel_evidence: Dict[str, Any] = {}
    if a.evidence_file:
        with open(a.evidence_file, "r", encoding="utf-8") as f:
            channel_evidence = json.load(f)

    model = build_backpressure_model(channel_evidence)

    observed_stalls: Dict[str, Any] = {}
    if a.observed_stalls_file:
        with open(a.observed_stalls_file, "r", encoding="utf-8") as f:
            observed_stalls = json.load(f)

    violations = {}
    if observed_stalls:
        for channel, observed in observed_stalls.items():
            if channel in model.results:
                violations[channel] = detect_stall_violation(model.results[channel], observed).to_dict()

    if a.json:
        out = model.to_dict()
        if violations:
            out["stall_violations"] = violations
        print(json.dumps(out, indent=2))
    else:
        print(format_backpressure_report(model))
        if violations:
            print()
            print("Stall Violations:")
            for channel, v in violations.items():
                print(f"  {channel}: {v['status']}  ({v['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
