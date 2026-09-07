"""dv_harness/feature_enablement_matrix.py -- Feature Enablement Matrix: which RTL parameter or
config bit enables which NAMED FEATURE, built ONLY from real, cited evidence (a parameter/bit name
plus a spec/comment citation proving what it enables) -- never guessed from a parameter's name
alone.

THE GAP THIS CLOSES. A repo-wide grep (`feature_enablement`/`enablement_matrix`/`EnablementMatrix`,
and free-text `which feature`/`named feature`) returned zero hits before this module -- nothing in
this project ever built the matrix spec section 285 asks for. Several near-neighbour modules were
read first, per REUSE OVER REINVENT, and each answers a genuinely different question:
`sys_regmap.py`'s `required_preconditions()`/`unverifiable_bits()` decide whether a MODE-DETERMINING
bit's precondition is met before a connectivity Gate-2 check, never what named capability a bit
turns on; `register_rtl_trace.py` proves whether a register FIELD NAME corresponds to a real,
referenced RTL signal (declaration-level existence), never what feature that field enables;
`design_knowledge_correlation.py` correlates arbitrary cross-source facts generically, with no
parameter/feature vocabulary of its own. None of them builds a parameter-to-feature enablement
matrix, and none needs to be extended to do so -- this is a genuine, narrow gap.

THE EVIDENCE TRUTH RULE, APPLIED LITERALLY -- identical to `arbitration_policy_ir.py`'s and
`coherency_capability_ir.py`'s rule, restated here for this module's own domain: a parameter/config
bit is matched to a feature ONLY from real evidence TEXT the caller supplies (an RTL comment, a
register/programming-guide paragraph, a spec section) -- NEVER from the parameter/bit's own NAME.
`classify_feature_enablement()` never reads `parameter_name`/`config_bit` when deciding which
feature a parameter enables; they are carried through purely as LABELS for the result. This is
proven directly by a dedicated negative-control test: a parameter literally named `usb3_enable`,
whose supplied evidence text states it enables PCIe Gen3 mode, classifies PCIe Gen3 mode -- not the
name-implied USB3 -- and a parameter named `usb3_enable` with NO supplied evidence text at all
classifies honestly `NOT_AVAILABLE`, never a guessed feature from the name.

CLASSIFICATION IS A LITERAL PHRASE MATCH, NOT A NAME/KEYWORD HEURISTIC -- the same discipline
`arbitration_policy_ir.classify_arbitration_scheme()` and `backpressure_model.py` already apply to
their own domains, reused here rather than re-invented. `ENABLEMENT_PATTERNS` is a small, fixed list
of literal, case-insensitive regex phrases that state an enablement relationship explicitly (e.g.
"enable bit for X", "when set, ... enables X", "must be asserted to enable X", "controls whether X
is enabled", the generic "enables X"), each capturing the feature name from the SAME sentence that
states the relationship. Evidence text using none of these forms is honestly `NOT_AVAILABLE` --
narrower recognition is the deliberate, disclosed trade for never fabricating an enablement
relationship the evidence does not literally state.

Evidence citing genuinely distinct features for the same parameter (after normalizing whitespace/
case) is honestly `AMBIGUOUS`, naming every feature it found -- this module never arbitrates which
citation is correct, the same ARBITRATION boundary `requirement_contract.py`/
`design_knowledge_correlation.py`/`security_policy_ir.py` already keep for their own conflicting-
claim findings. Multiple citations naming the SAME feature (after normalization) are merged into one
RESOLVED entry citing every one of them, never treated as a conflict.

EVERY CITED EXCERPT REQUIRES A REAL, NON-EMPTY CITATION, ENFORCED AT CONSTRUCTION -- the same
"an uncited claim is refused outright" discipline `security_policy_ir.AccessRule`,
`arbitration_policy_ir`'s de-facto evidence requirement, and `qos_policy_ir.build_qos_policy_ir()`
already apply to their own domains. An evidence excerpt with real text but no citation (a spec
section, an RTL `file:line`, a register/programming-guide reference) is refused outright
(`FeatureEnablementError`) rather than silently accepted or silently dropped -- an enablement claim
this project cannot point a human at to verify is exactly the unsupported claim the Evidence Truth
Rule forbids.

FILE-SAFETY / REUSE NOTE. This module imports only `dv_harness.connectivity.render_markdown_table`
(this repo's one parameterized table renderer, pre-existing and outside the current batch) and
`dv_harness.models.Status` (solely to assert this module's own status vocabulary shares no token
with a real stage verdict, the same `assert_no_verification_verdict_vocabulary()` discipline several
sibling modules already apply to themselves). It imports nothing from `sys_regmap.py`,
`register_rtl_trace.py`, `arbitration_policy_ir.py`, `coherency_capability_ir.py`, or any other
new/concurrently-built module in this project's current batch -- there is a low but non-zero
collision risk in a multi-agent batch, and this module is small enough to stand entirely on its own.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it does not read RTL or a spec document itself (the
caller supplies the evidence text, exactly as `arbitration_policy_ir.py` does for its own evidence
text); it does not decide a parameter's LEGAL values or precondition (`sys_regmap.py`'s job); it
does not prove a parameter/bit corresponds to a real RTL signal (`register_rtl_trace.py`'s job); it
never invents a feature name, a citation, or an enablement relationship the evidence does not
literally state; it writes nothing, gates nothing, approves nothing, and there is deliberately no
stage gate -- a gate that passed on a matrix nobody reviewed would be worse than none.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: The three honest states one parameter's feature-enablement classification can be in. RESOLVED
#: means exactly one real feature (after normalization) was cited across all supplied evidence.
#: AMBIGUOUS means two or more genuinely distinct features were cited with no resolution -- never
#: resolved by guessing. NOT_AVAILABLE means no evidence was supplied, or none of it matched a
#: recognized enablement phrase.
ENABLEMENT_STATUSES: Sequence[str] = ("RESOLVED", "AMBIGUOUS", "NOT_AVAILABLE")

#: Literal, case-insensitive enablement phrase patterns, checked in this fixed PRECEDENCE ORDER
#: (most specific first) so a more specific phrase's feature-name capture is preferred over the
#: generic catch-all matching the same span. Each pattern captures the feature-name segment from the
#: SAME sentence that states the enablement relationship -- never a bare keyword scan.
_FEATURE_SEGMENT = r"([A-Za-z0-9][A-Za-z0-9 _\-/]{1,60}?)"

ENABLEMENT_PATTERNS: Sequence[Tuple[str, str]] = (
    ("ENABLE_BIT_FOR", r"enable\s+bit\s+for\s+" + _FEATURE_SEGMENT + r"(?:\.|,|;|$)"),
    ("MUST_BE_SET_TO_ENABLE",
     r"must\s+be\s+(?:set|asserted|written\s+to\s+1)\s+to\s+enable\s+" + _FEATURE_SEGMENT
     + r"(?:\.|,|;|$)"),
    ("WHEN_SET_ENABLES",
     r"when\s+(?:set|asserted|written\s+to\s+(?:1|'b1|1'b1))[^.,;]*?enables?\s+(?:the\s+)?"
     + _FEATURE_SEGMENT + r"(?:\s+feature)?(?:\.|,|;|$)"),
    ("CONTROLS_WHETHER_ENABLED",
     r"controls?\s+whether\s+" + _FEATURE_SEGMENT + r"\s+is\s+enabled"),
    ("GENERIC_ENABLES",
     r"enables?\s+(?:the\s+)?" + _FEATURE_SEGMENT + r"(?:\s+feature)?(?:\.|,|;|$)"),
)


def _normalize_feature_name(raw: str) -> str:
    """Normalize a captured feature-name segment for equality comparison: collapse whitespace,
    lowercase, strip a trailing generic word ("feature"/"support"/"mode") that several phrasings
    optionally carry so "PCIe Gen3 mode" and "PCIe Gen3" are recognized as the same feature."""
    s = re.sub(r"\s+", " ", raw).strip().lower()
    for suffix in (" feature", " support", " mode"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)].strip()
    return s


class FeatureEnablementError(Exception):
    """Raised only for a genuinely malformed caller input (a missing parameter identity, an
    evidence excerpt with real text but no citation, a duplicate parameter/bit declaration) --
    never for an honest absence of evidence, which is always a reported NOT_AVAILABLE result."""


@dataclass
class EvidenceExcerpt:
    """One real evidence excerpt a caller supplies for one parameter/config bit: real text plus a
    real, non-empty citation (a spec section, an RTL `file:line`, a register/programming-guide
    reference). Construction REFUSES an excerpt with real text but no citation -- an uncited
    enablement claim is exactly the unsupported claim the Evidence Truth Rule forbids."""
    text: str
    citation: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise FeatureEnablementError(
                "an evidence excerpt must carry real, non-empty text")
        if not isinstance(self.citation, str) or not self.citation.strip():
            raise FeatureEnablementError(
                f"evidence excerpt {self.text[:60]!r} has no citation -- an enablement claim "
                f"a human cannot verify against a real source is refused outright")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureCitation:
    """One real matched (feature_name, matched_phrase, citation) triple supporting a classification
    result."""
    feature_name: str
    matched_text: str
    citation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureEnablementResult:
    """The honest classification for one parameter/config bit: RESOLVED names exactly one real
    feature (after normalization); AMBIGUOUS names every distinct feature the evidence cited with no
    resolution; NOT_AVAILABLE means nothing matched (or no evidence was supplied at all)."""
    status: str  # one of ENABLEMENT_STATUSES
    feature: Optional[str]
    citations: List[FeatureCitation]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "feature": self.feature,
            "citations": [c.to_dict() for c in self.citations],
            "reason": self.reason,
        }


@dataclass
class FeatureEnablementEntry:
    """One row of the matrix: a real parameter/config-bit identity plus its classification result."""
    parameter_name: str
    config_bit: Optional[str]
    result: FeatureEnablementResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "config_bit": self.config_bit,
            **self.result.to_dict(),
        }

    def to_row(self) -> Dict[str, Any]:
        citations = "; ".join(
            f"{c.feature_name} <- {c.citation}" for c in self.result.citations
        ) or "-"
        return {
            "parameter": self.parameter_name,
            "config_bit": self.config_bit or "-",
            "feature": self.result.feature or "-",
            "status": self.result.status,
            "evidence": citations,
            "reason": self.result.reason,
        }


@dataclass
class FeatureEnablementMatrix:
    """The full matrix over every declared parameter/config bit."""
    entries: List[FeatureEnablementEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}

    def to_rows(self) -> List[Dict[str, Any]]:
        return [e.to_row() for e in self.entries]

    def resolved_entries(self) -> List[FeatureEnablementEntry]:
        return [e for e in self.entries if e.result.status == "RESOLVED"]

    def ambiguous_entries(self) -> List[FeatureEnablementEntry]:
        return [e for e in self.entries if e.result.status == "AMBIGUOUS"]

    def not_available_entries(self) -> List[FeatureEnablementEntry]:
        return [e for e in self.entries if e.result.status == "NOT_AVAILABLE"]

    def render_markdown(self) -> str:
        from dv_harness.connectivity import render_markdown_table
        columns = [
            ("parameter", "Parameter / Config Bit Source"),
            ("config_bit", "Config Bit"),
            ("feature", "Feature Enabled"),
            ("status", "Status"),
            ("evidence", "Evidence Citation"),
            ("reason", "Reason"),
        ]
        return render_markdown_table(
            columns, self.to_rows(),
            empty_note="(no parameters declared -- nothing to classify)")


def classify_feature_enablement(parameter_name: str,
                                 evidence: Optional[Sequence[Any]] = None,
                                 *, config_bit: Optional[str] = None) -> FeatureEnablementResult:
    """Classify which real feature `parameter_name`/`config_bit` enables STRICTLY from
    `evidence` -- a sequence of `EvidenceExcerpt`-shaped items (an `EvidenceExcerpt`, or a
    `{"text": ..., "citation": ...}` mapping). `parameter_name`/`config_bit` are accepted ONLY as
    labels for the result; this function never reads either when deciding a feature (proven
    directly by a dedicated negative-control test)."""
    excerpts: List[EvidenceExcerpt] = []
    if evidence:
        for item in evidence:
            if isinstance(item, EvidenceExcerpt):
                excerpts.append(item)
            elif isinstance(item, Mapping):
                excerpts.append(EvidenceExcerpt(
                    text=item.get("text", ""), citation=item.get("citation", "")))
            else:
                raise FeatureEnablementError(
                    f"unrecognized evidence item shape for parameter {parameter_name!r}: "
                    f"{item!r}")

    if not excerpts:
        return FeatureEnablementResult(
            status="NOT_AVAILABLE", feature=None, citations=[],
            reason="no evidence supplied -- an enablement relationship cannot be classified "
                   "from a parameter/config-bit name alone")

    # normalized_feature -> list of FeatureCitation (one per real matched excerpt/pattern hit).
    # Patterns are checked in ENABLEMENT_PATTERNS' own fixed precedence order (most specific
    # first); a later, more generic pattern (e.g. the catch-all "enables X") is never allowed to
    # claim a text span an earlier, more specific pattern (e.g. "enable bit for X") already
    # matched -- otherwise one real sentence could be double-counted as two disagreeing claims
    # and manufacture a false AMBIGUOUS out of a single, unambiguous statement.
    matched: Dict[str, List[FeatureCitation]] = {}
    for excerpt in excerpts:
        claimed_spans: List[Tuple[int, int]] = []
        for _pattern_id, pattern in ENABLEMENT_PATTERNS:
            for m in re.finditer(pattern, excerpt.text, re.IGNORECASE):
                span = (m.start(), m.end())
                if any(span[0] < c_end and span[1] > c_start
                       for c_start, c_end in claimed_spans):
                    continue
                raw_feature = m.group(1)
                normalized = _normalize_feature_name(raw_feature)
                if not normalized:
                    continue
                claimed_spans.append(span)
                citation = FeatureCitation(
                    feature_name=raw_feature.strip(), matched_text=m.group(0).strip(),
                    citation=excerpt.citation)
                matched.setdefault(normalized, []).append(citation)

    if not matched:
        return FeatureEnablementResult(
            status="NOT_AVAILABLE", feature=None, citations=[],
            reason="no recognized enablement phrase found in the supplied evidence text")

    if len(matched) == 1:
        normalized = next(iter(matched))
        citations = matched[normalized]
        feature_name = citations[0].feature_name
        return FeatureEnablementResult(
            status="RESOLVED", feature=feature_name, citations=citations,
            reason=f"matched enablement phrase(s) citing {feature_name!r} in the supplied "
                   f"evidence")

    all_citations = [c for group in matched.values() for c in group]
    features = sorted({c.feature_name for c in all_citations})
    return FeatureEnablementResult(
        status="AMBIGUOUS", feature=None, citations=all_citations,
        reason=f"multiple distinct features cited for this parameter with no resolution: "
               f"{features}")


def _identity_key(parameter_name: str, config_bit: Optional[str]) -> Tuple[str, Optional[str]]:
    return (parameter_name, config_bit)


def build_feature_enablement_matrix(
        parameter_facts: Sequence[Mapping[str, Any]]) -> FeatureEnablementMatrix:
    """Build the full matrix from a caller-declared list of parameter facts, each shaped
    `{"parameter_name": str, "config_bit": str|None, "evidence": [{"text", "citation"}, ...]}`.
    Refuses (raises `FeatureEnablementError`) a fact with no `parameter_name`, or a second fact
    declaring the identical (parameter_name, config_bit) identity -- a real duplicate declaration
    is a caller-input defect, never silently merged or overwritten."""
    if not isinstance(parameter_facts, Sequence) or isinstance(parameter_facts, (str, bytes)):
        raise FeatureEnablementError("parameter_facts must be a list of parameter fact mappings")

    seen: Dict[Tuple[str, Optional[str]], int] = {}
    entries: List[FeatureEnablementEntry] = []
    for i, fact in enumerate(parameter_facts):
        if not isinstance(fact, Mapping):
            raise FeatureEnablementError(f"parameter fact at index {i} is not a mapping: {fact!r}")
        parameter_name = fact.get("parameter_name")
        if not isinstance(parameter_name, str) or not parameter_name.strip():
            raise FeatureEnablementError(
                f"parameter fact at index {i} has no real parameter_name")
        config_bit = fact.get("config_bit")
        if config_bit is not None and not isinstance(config_bit, str):
            raise FeatureEnablementError(
                f"parameter fact {parameter_name!r} has a non-string config_bit: {config_bit!r}")

        key = _identity_key(parameter_name, config_bit)
        if key in seen:
            raise FeatureEnablementError(
                f"duplicate parameter/config-bit declaration: {parameter_name!r} "
                f"(config_bit={config_bit!r}) already declared at index {seen[key]}")
        seen[key] = i

        evidence = fact.get("evidence")
        if evidence is not None and (
                not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes))):
            raise FeatureEnablementError(
                f"parameter fact {parameter_name!r} has a non-list evidence field: {evidence!r}")

        result = classify_feature_enablement(parameter_name, evidence, config_bit=config_bit)
        entries.append(FeatureEnablementEntry(
            parameter_name=parameter_name, config_bit=config_bit, result=result))

    return FeatureEnablementMatrix(entries=entries)


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status vocabulary must share no token with a real stage verdict --
    the same guard several sibling domain-vocabulary modules in this project already apply to
    themselves."""
    from dv_harness.models import Status
    verdict_tokens = {s.value for s in Status}
    collisions = verdict_tokens.intersection(set(ENABLEMENT_STATUSES))
    if collisions:
        raise AssertionError(
            f"feature_enablement_matrix status vocabulary collides with models.Status: "
            f"{collisions}")


assert_no_verification_verdict_vocabulary()


def overall_status(matrix: FeatureEnablementMatrix) -> str:
    """Worst-wins composite: a single AMBIGUOUS entry makes the whole matrix AMBIGUOUS regardless
    of how many entries are cleanly RESOLVED; short of that, any NOT_AVAILABLE entry makes it
    NOT_AVAILABLE (never a fabricated fully-RESOLVED claim over an incomplete matrix); only when
    every entry is RESOLVED (and at least one entry exists) is the matrix RESOLVED."""
    if not matrix.entries:
        return "NOT_AVAILABLE"
    statuses = {e.result.status for e in matrix.entries}
    if "AMBIGUOUS" in statuses:
        return "AMBIGUOUS"
    if "NOT_AVAILABLE" in statuses:
        return "NOT_AVAILABLE"
    return "RESOLVED"


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """Shared CLI/verb implementation, the same convention several sibling standalone modules in
    this project already follow (`power-intent`, `golden-scenario`, ...). No `dv-harness` CLI verb
    or `gates.py` STAGE_GATES entry was added -- both files are large and under concurrent edit
    pressure from many other items in this same batch, the same disclosed choice several very
    recent sibling modules in this codebase already make. This is a REACHED capability (a real
    `python -m` caller exists), not a WIRED one."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.feature_enablement_matrix",
        description="Build a Feature Enablement Matrix (which RTL parameter/config bit enables "
                    "which named feature) strictly from supplied, cited evidence text. Reads and "
                    "reports only -- writes nothing, gates nothing, approves nothing.")
    ap.add_argument("verb", choices=["build"], help="The one supported verb.")
    ap.add_argument("--parameters", required=True,
                     help="Path to a JSON file: a list of {parameter_name, config_bit, evidence} "
                          "facts (evidence: a list of {text, citation} excerpts).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable matrix.")
    args = ap.parse_args(argv)

    with open(args.parameters, "r", encoding="utf-8") as f:
        parameter_facts = json.load(f)
    if isinstance(parameter_facts, Mapping):
        parameter_facts = parameter_facts.get("parameters", [])

    try:
        matrix = build_feature_enablement_matrix(parameter_facts)
    except FeatureEnablementError as e:
        print(f"MALFORMED_INPUT: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(matrix.to_dict(), indent=2))
    else:
        print(matrix.render_markdown())

    status = overall_status(matrix)
    if status == "AMBIGUOUS":
        return 1
    if status == "NOT_AVAILABLE":
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    raise SystemExit(main())
