"""dv_harness/contextual_source_precedence.py -- an ADDITIVE, per-fact-type
override layer on top of `source_authority.py`'s fixed 9-level
`AUTHORITY_ORDER`. This module never edits, monkeypatches, or re-derives that
order -- it is imported read-only, exactly as `design_source_inventory.py`
itself already imports it "by import only, never redefines or re-derives".

WHY THIS EXISTS (contextual_source_precedence gap-close, dut_discovery item).
`design_source_inventory.py`'s registry (`evaluate_source()` /
`_resolve_authority()`) resolves a source's authority tier through
`source_authority.authority_source()` for EVERY row, unconditionally --
the same fixed 9-level order regardless of what KIND of fact that row is
about. That is correct for most facts (a functional-behavior claim really
should be decided DUT RTL > register file > controller doc, as
`AUTHORITY_ORDER` already states), but it is not universally correct: a
project's own timing budget (setup/hold windows, clock frequency, electrical
levels) is routinely CONTRACTED by the controller doc / programming guide /
datasheet, and an RTL comment restating that budget is a convenience note
that can silently drift from it -- see `dv_harness/
timing_requirement_extraction.py`'s own module docstring, which extracts
"documented setup/hold/latency bounds ... never a measured value" from
spec/programming-guide text specifically because that is where a design's
timing CONTRACT is authored, not merely restated. For a fact of THAT kind,
the fixed order (DUT RTL, tier 3, outranking controller doc, tier 6) gets the
conflict backwards. Source Authority Order itself never claims to be a
universal ranking for every possible KIND of fact -- it is one order for
"functional behavior" conflicts, which is the overwhelming majority of what
this project resolves, and this module is the place a DIFFERENT, documented,
evidence-cited order may be declared for a DIFFERENT class of fact.

WHAT THIS MODULE IS NOT. It is not a second `AUTHORITY_ORDER` -- every
override declared here is a REORDERING of the SAME 9 canonical levels
`source_authority.AUTHORITY_ORDER` already defines
(`FactTypeOverride.__post_init__` enforces this: an override's `order` must
be a real permutation of the base 9 ids, never a subset, never an invented
level). It never arbitrates a REAL disagreement either -- exactly like
`source_authority.resolve_conflict()` itself, deciding which VALUE wins never
means the losing artifact is fine to leave wrong; that stays a human
decision (`source_authority.escalate_conflict()`'s own job, untouched here).

THE EVIDENCE TRUTH RULE, applied to the override table itself. An override is
a POLICY claim ("for fact type X, source A outranks source B") every bit as
much as a `SourceClaim` is a factual claim, and it is refused the identical
way an uncited `SourceClaim`/`AccessRule`/`ControllingMechanism` already is
elsewhere in this project: `FactTypeOverride.__post_init__` raises
`ContextualSourcePrecedenceError` on a missing/blank `evidence` citation. An
override with no stated justification is exactly the unsupported claim the
Evidence Truth Rule forbids -- this module never lets one exist.

FACT TYPE with NO declared override (including "functional", the task's own
worked example of the unchanged case) resolves EXACTLY through
`source_authority`'s own base order -- proven directly in this module's test
suite by running the same claims through both `source_authority.
resolve_conflict()` and this module's `resolve_conflict_for_fact_type()` with
an unknown/undeclared fact_type and asserting byte-identical verdicts. This
is the "never replace source_authority.py's own order" guarantee made
checkable, not merely stated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import source_authority

__all__ = [
    "ContextualSourcePrecedenceError",
    "FactTypeOverride",
    "FACT_TYPE_OVERRIDES",
    "known_fact_types",
    "contextual_rank",
    "contextual_sort_key",
    "contextual_rank_for_fact_type",
    "resolve_conflict_for_fact_type",
    "describe_fact_type_overrides",
    "format_fact_type_overrides",
]


class ContextualSourcePrecedenceError(ValueError):
    """Typed error, same convention as the rest of this package (a short
    SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict) -- never a
    silently-accepted malformed override and never a silently-guessed rank."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class FactTypeOverride:
    """One documented, evidence-cited reordering of `source_authority.
    AUTHORITY_ORDER`'s 9 levels for a single named fact type.

    `order` must be a PERMUTATION of the base order's own canonical ids
    (accepted as any id/doc-phrase/alias `source_authority.normalize_source`
    already recognises, then normalised to canonical ids) -- never a subset,
    never a new invented level. `evidence` is a mandatory, non-empty citation
    justifying WHY this fact type's precedence genuinely differs from the
    base functional-behavior order; an override with none is refused at
    construction, never silently accepted.
    """
    fact_type: str
    order: Tuple[str, ...]
    evidence: str
    rationale: str = ""

    def __post_init__(self):
        fact_type = str(self.fact_type or "").strip()
        if not fact_type:
            raise ContextualSourcePrecedenceError("FACT_TYPE_MUST_BE_STATED", {})
        object.__setattr__(self, "fact_type", fact_type)

        if not str(self.evidence or "").strip():
            raise ContextualSourcePrecedenceError("OVERRIDE_MUST_CITE_EVIDENCE", {
                "fact_type": fact_type,
                "hint": "A per-fact-type precedence override changes which real source "
                        "wins a conflict; an uncited override is exactly the unsupported "
                        "claim the Evidence Truth Rule forbids. Cite the real project "
                        "convention, spec section, or written decision this reordering "
                        "reflects.",
            })

        base_ids = tuple(s.id for s in source_authority.AUTHORITY_ORDER)
        base_id_set = set(base_ids)
        try:
            given_ids = tuple(source_authority.normalize_source(x) for x in self.order)
        except source_authority.SourceAuthorityError as exc:
            raise ContextualSourcePrecedenceError("OVERRIDE_NAMES_UNKNOWN_SOURCE", {
                "fact_type": fact_type, "reason": exc.reason, "detail": exc.detail,
            }) from exc

        if len(given_ids) != len(base_ids) or set(given_ids) != base_id_set:
            raise ContextualSourcePrecedenceError(
                "OVERRIDE_MUST_BE_A_PERMUTATION_OF_AUTHORITY_ORDER", {
                    "fact_type": fact_type,
                    "given": list(given_ids),
                    "required_ids": sorted(base_id_set),
                    "hint": "A per-fact-type override may only REORDER the 9 canonical "
                            "levels source_authority.py already defines -- it may never "
                            "invent a new level, drop an existing one, or repeat one.",
                })
        object.__setattr__(self, "order", given_ids)

    @property
    def rank_of(self) -> Dict[str, int]:
        """canonical source id -> 1-based contextual rank for this fact type."""
        return {sid: i + 1 for i, sid in enumerate(self.order)}


#: The declared, evidence-cited overrides. Every entry is checked (at
#: construction, i.e. at import time) to be a real permutation of
#: `source_authority.AUTHORITY_ORDER`'s own 9 ids -- adding a fact type here
#: with a malformed `order` fails the import loudly rather than silently
#: shipping a broken table.
#:
#: "timing" is the task's own worked example ("a timing datasheet might
#: outrank an RTL comment for one class of fact"). `simulation_result` and
#: `reference_command_txt` stay at the very top: what a tool actually did, or
#: the reference execution asset itself, still outranks any document for a
#: timing claim too -- a real measured/elaborated result is never demoted by
#: this override. `controller_doc` / `ip_user_guide` (the closest existing
#: AUTHORITY_ORDER levels to "a project's programming guide/datasheet") move
#: above `dut_rtl` / `register_file`, because a timing BUDGET is contracted
#: in the doc and an RTL comment restating it is a convenience note that can
#: drift -- see `dv_harness/timing_requirement_extraction.py`'s own module
#: docstring for the concrete, cited reasoning this override reflects.
#: Everything else keeps its base relative order.
_TIMING_OVERRIDE = FactTypeOverride(
    fact_type="timing",
    order=(
        "simulation_result",       # 1 (unchanged) -- what actually happened still wins
        "reference_command_txt",   # 2 (unchanged) -- the execution-authority asset
        "controller_doc",          # 3 (was 6) -- the contracted timing budget lives here
        "ip_user_guide",           # 4 (was 7) -- one step further, still doc-authored
        "dut_rtl",                 # 5 (was 3) -- RTL restates the budget; can drift from it
        "register_file",           # 6 (was 4) -- a machine-readable register description
        "existing_testbench_bind", # 7 (was 5) -- unrelated to a documented timing budget
        "vip_example",             # 8 (unchanged)
        "vip_document",            # 9 (unchanged)
    ),
    evidence=(
        "dv_harness/timing_requirement_extraction.py's own module docstring: documented "
        "setup/hold/latency bounds are extracted from spec/programming-guide text "
        "specifically because that is where a design's timing budget is CONTRACTED, "
        "never from a live measurement or from an RTL comment restating it. This is the "
        "concrete, in-repo grounding for this task's own worked example ('a timing "
        "datasheet might outrank an RTL comment for one class of fact')."
    ),
    rationale=(
        "A timing value (clock frequency, setup/hold window, electrical level) is "
        "typically authored once in the controller doc/programming guide/datasheet as "
        "the CONTRACT an implementation must meet; an RTL `//` comment stating the same "
        "number is a convenience restatement that is not re-verified against the doc on "
        "every edit and can silently go stale. Functional-behavior facts keep the base "
        "order (RTL is authoritative for what the silicon actually does); this override "
        "applies to timing facts specifically."
    ),
)

FACT_TYPE_OVERRIDES: Dict[str, FactTypeOverride] = {
    _TIMING_OVERRIDE.fact_type: _TIMING_OVERRIDE,
}


def known_fact_types() -> Tuple[str, ...]:
    """Every fact type with a declared override. NOT an exhaustive list of
    every fact type a caller may legally pass -- any fact type not in this
    tuple (including the task's own "functional" example) simply falls back
    to `source_authority`'s own unmodified base order, which is the correct,
    intentional default, not an error."""
    return tuple(FACT_TYPE_OVERRIDES.keys())


def contextual_rank(source_id: str, fact_type: Optional[str]) -> Tuple[int, str]:
    """(rank, authority_order_used) for one source under `fact_type`.

    `authority_order_used` is "PER_FACT_TYPE_OVERRIDE" when a declared
    override for `fact_type` applied, else "BASE_AUTHORITY_ORDER" -- so a
    caller (or a report) can always tell whether the fixed 9-level order or a
    contextual reordering actually decided this rank, never left to infer it.
    Raises exactly as `source_authority.normalize_source`/`authority_rank`
    already do on an unrecognised source -- an unknown source is never
    silently ranked here either.
    """
    src_id = source_authority.normalize_source(source_id)
    override = FACT_TYPE_OVERRIDES.get(fact_type) if fact_type else None
    if override is None:
        return source_authority.authority_rank(src_id), "BASE_AUTHORITY_ORDER"
    return override.rank_of[src_id], "PER_FACT_TYPE_OVERRIDE"


#: Backwards-compatible alias matching `design_source_inventory.py`'s own
#: naming convention for the identical two-value result.
contextual_rank_for_fact_type = contextual_rank


def contextual_sort_key(name, fact_type: Optional[str],
                         qualifier: Optional[str] = None) -> Tuple[int, int]:
    """Total ordering key `(contextual_rank, subrank)` for `name` under
    `fact_type` -- the fact-type-contextual sibling of
    `source_authority.sort_key()`. The register-file DUT-then-Global
    tie-break is REUSED, not re-derived: `source_authority.sort_key()` is
    called once purely to obtain (and validate) `qualifier`'s own subrank,
    which is the same regardless of which fact type's rank ordering applies
    -- there is exactly one place in this codebase that knows the
    REGISTER_FILE_SUBORDER tie-break.
    """
    _, sub = source_authority.sort_key(name, qualifier)
    rank, _ = contextual_rank(name, fact_type)
    return (rank, sub)


def _claim_dict_with_contextual_rank(claim: source_authority.SourceClaim,
                                      fact_type: Optional[str]) -> dict:
    d = claim.to_dict()
    rank, order_used = contextual_rank(claim.source, fact_type)
    d["contextual_rank"] = rank
    d["authority_order_used"] = order_used
    return d


def resolve_conflict_for_fact_type(claims: Sequence[source_authority.SourceClaim],
                                    fact_type: Optional[str]) -> dict:
    """Fact-type-contextual sibling of `source_authority.resolve_conflict()`.

    Applies the SAME verdict algorithm that function documents
    (NO_CONFLICT / RESOLVED / UNDECIDABLE_SAME_AUTHORITY) over the SAME
    `SourceClaim` objects that module's own construction already validates
    (a claim with no evidence path, an unknown source, or an invalid
    register-file qualifier still refuses to construct -- this function
    reuses `SourceClaim`, it never re-implements its guarantees). The only
    thing that changes is WHICH order breaks the tie: when `fact_type` names
    a declared override, that reordering decides; for any other fact_type
    (including one nobody has declared an override for, e.g. "functional"),
    this reduces to EXACTLY `source_authority.resolve_conflict()`'s own
    result -- proven directly in this module's test suite, not merely
    asserted here.

    Refuses fewer than 2 claims and a non-`SourceClaim` member with the
    SAME `source_authority.SourceAuthorityError` reasons that function
    itself raises, so a caller cannot tell the two functions apart by their
    error behaviour, only by which order decided the winner.
    """
    claims = list(claims)
    if len(claims) < 2:
        raise source_authority.SourceAuthorityError("CONFLICT_NEEDS_AT_LEAST_TWO_CLAIMS", {
            "claim_count": len(claims),
        })
    for c in claims:
        if not isinstance(c, source_authority.SourceClaim):
            raise source_authority.SourceAuthorityError("CLAIMS_MUST_BE_SOURCECLAIM", {
                "got": type(c).__name__,
            })
    fact_type = str(fact_type or "").strip() or None

    keys = {id(c): contextual_sort_key(c.source, fact_type, c.qualifier) for c in claims}
    ordered = sorted(claims, key=lambda c: (keys[id(c)], c.source))

    evidence_paths: Dict[str, List[str]] = {}
    for c in ordered:
        evidence_paths.setdefault(c.source, []).append(c.evidence_path)

    override_used = fact_type in FACT_TYPE_OVERRIDES
    distinct = {c.claim.strip() for c in claims}
    base = {
        "fact_type": fact_type,
        "authority_order_used": "PER_FACT_TYPE_OVERRIDE" if override_used else "BASE_AUTHORITY_ORDER",
        "claims": [_claim_dict_with_contextual_rank(c, fact_type) for c in ordered],
        "evidence_paths": evidence_paths,
        "distinct_claim_count": len(distinct),
    }

    if len(distinct) == 1:
        return {**base, "verdict": source_authority.VERDICT_NO_CONFLICT, "winner": None,
                "losers": [], "tied": [], "authority_gap": None,
                "rule": "All sources state the same thing; no authority ordering needed."}

    top = keys[id(ordered[0])]
    at_top = [c for c in ordered if keys[id(c)] == top]
    if len({c.claim.strip() for c in at_top}) > 1:
        top_phrase = source_authority.authority_source(at_top[0].source).doc_phrase
        return {**base, "verdict": source_authority.VERDICT_UNDECIDABLE, "winner": None,
                "losers": [], "tied": [_claim_dict_with_contextual_rank(c, fact_type) for c in at_top],
                "authority_gap": 0,
                "rule": (f"{len(at_top)} claims sit at the same "
                         f"{('%s-contextual ' % fact_type) if override_used else ''}"
                         f"authority level ({top_phrase}, contextual tier {top[0]}) and "
                         f"disagree. The authority order cannot break a tie inside one "
                         f"level -- a human must.")}

    winner = at_top[0]
    losers = [c for c in ordered if c is not winner]
    best_loser = losers[0]
    winner_rank = keys[id(winner)][0]
    loser_rank = keys[id(best_loser)][0]
    winner_phrase = source_authority.authority_source(winner.source).doc_phrase
    loser_phrase = source_authority.authority_source(best_loser.source).doc_phrase
    return {**base, "verdict": source_authority.VERDICT_RESOLVED,
            "winner": _claim_dict_with_contextual_rank(winner, fact_type),
            "losers": [_claim_dict_with_contextual_rank(c, fact_type) for c in losers],
            "tied": [],
            "authority_gap": winner_rank - loser_rank,
            "rule": (f"For fact_type={fact_type!r}: {winner_phrase} (contextual tier "
                     f"{winner_rank}) outranks {loser_phrase} (contextual tier "
                     f"{loser_rank}) -- "
                     f"{'per-fact-type override' if override_used else 'base authority order'}, "
                     f"highest first.")}


def describe_fact_type_overrides() -> List[dict]:
    """JSON-serializable rendering of every declared override -- what
    `python -m dv_harness.contextual_source_precedence describe` prints."""
    out = []
    for ft, override in FACT_TYPE_OVERRIDES.items():
        out.append({
            "fact_type": ft,
            "order": list(override.order),
            "order_doc_phrases": [source_authority.authority_source(sid).doc_phrase
                                   for sid in override.order],
            "evidence": override.evidence,
            "rationale": override.rationale,
        })
    return out


def format_fact_type_overrides() -> str:
    lines = ["Per-fact-type source-precedence overrides (additive -- "
             "source_authority.AUTHORITY_ORDER is the default for every fact type "
             "not listed here):"]
    for entry in describe_fact_type_overrides():
        lines.append(f"  fact_type={entry['fact_type']!r}")
        for i, phrase in enumerate(entry["order_doc_phrases"], start=1):
            lines.append(f"    {i}. {phrase}")
        lines.append(f"    evidence: {entry['evidence']}")
    return "\n".join(lines)


def main(argv=None) -> int:  # pragma: no cover - thin CLI wrapper
    import argparse
    parser = argparse.ArgumentParser(prog="dv_harness.contextual_source_precedence")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("describe")
    args = parser.parse_args(argv)
    if args.cmd == "describe":
        print(format_fact_type_overrides())
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
