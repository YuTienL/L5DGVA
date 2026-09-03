"""dv_harness/source_authority.py -- the 9-level SOURCE AUTHORITY ORDER as
executable code, plus the one path that turns a detected mismatch into a real
question-queue entry carrying BOTH sides' evidence paths.

WHY THIS MODULE EXISTS (2026-09-04 audit finding, verbatim gap):
The 9-level ordering was real and accurate but lived ONLY as documentation
prose in `docs/RUN_PROFILE.md` ("Authority order when documentation and the
real source disagree (highest first): 1) ... 9) VIP document."). A repo-wide
grep for its distinctive terms found zero hits outside that one paragraph --
no `AUTHORITY_ORDER` constant, no `resolve_conflict()`, nothing that applied
it. It was a convention an agent was TRUSTED to read and self-apply: exactly
the failure class CLAUDE.md itself names ("prose-only skill guidance
describing a desired mechanism an LLM subagent is merely trusted to enact").

It is NOT the same list as `tools/verification_flow/evidence_source_priority_
gate.py`'s `ORDER` (EXISTING_PROJECT_FILES ... ASK_USER). That one answers
"which source do I consult FIRST when discovering a fact I don't have yet"
(a search order). This one answers "two sources I already read state
DIFFERENT things -- which one is true" (a conflict-resolution order). Both
are 9 items long, which is a coincidence that has already caused one
mis-identification; they are deliberately kept as separate mechanisms.

THREE THINGS THIS MODULE MAKES MACHINE-ENFORCED, not prose:

  1. The order itself (`AUTHORITY_ORDER`, `authority_rank`,
     `resolve_conflict`). Including the tie-break the prose leaves implicit:
     "register file (DUT then Global)" is a real sub-ordering inside tier 4,
     encoded as `REGISTER_FILE_SUBORDER`, so a DUT register file beats a
     Global one without a human having to remember that clause.

  2. Doc/code non-drift (`parse_documented_order`, `assert_doc_matches_code`).
     The markdown paragraph is PARSED and compared against the code's own
     order. If someone edits either one, a test fails. Without this, moving
     the order into code would just create a SECOND place for it to be wrong.

  3. The escalation that did not exist (`escalate_conflict`). Two claims that
     genuinely disagree become a `question_queue.QuestionQueueStore`
     question -- Tier-3 by the queue's own `affects_spec_intent` hard trigger
     -- whose OPTIONS ARE THE TWO SIDES and whose per-option `rationale`
     carries that side's evidence path. `assert_both_evidence_paths_present()`
     runs BEFORE the record is persisted, so a conflict question that names a
     side without citing where that side's evidence lives can never reach the
     queue at all.

WHAT AUTHORITY ORDER DOES *NOT* DO. Ranking two claims decides which value to
USE. It does not explain why they disagree, and it never means the losing
source is fine to leave wrong: a doc that contradicts the RTL is either stale
or the RTL is buggy, and only a human can say which. That is why
`resolve_conflict()` returning `RESOLVED` still warrants an escalation --
the two are different questions ("which value do I use now" vs "which of
these two artifacts is wrong"), and only the first is decidable mechanically.
A same-rank disagreement (`UNDECIDABLE_SAME_AUTHORITY`) is not decidable even
for the first question, and escalating it is mandatory, not advisory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The real markdown paragraph this module's order is kept in sync with.
#: `assert_doc_matches_code()` parses this file, so the prose can never
#: silently drift from `AUTHORITY_ORDER` below (in either direction).
DOC_PATH = REPO_ROOT / "docs" / "RUN_PROFILE.md"


class SourceAuthorityError(ValueError):
    """Typed error, same convention as the rest of this package (a short
    SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict) -- never a
    silently-dropped claim or a silently-guessed rank."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class AuthoritySource:
    """One level of the order.

    `rank` is 1-based and 1 is HIGHEST -- deliberately matching how the doc
    paragraph numbers them, so a reader comparing the two never has to invert
    anything in their head.

    `doc_phrase` is the exact wording the markdown paragraph uses for this
    level; `parse_documented_order()` matches against it. `aliases` are the
    other names real call sites already use for the same thing (e.g. a
    reference-pattern audit says "reference pattern file"; the address-map
    verifier says "decoder"), so a caller never has to know the canonical id.
    """
    rank: int
    id: str
    doc_phrase: str
    description: str
    aliases: tuple = ()


#: Highest authority first. Sourced from docs/RUN_PROFILE.md's own paragraph,
#: which is itself parsed and compared in assert_doc_matches_code().
AUTHORITY_ORDER: tuple = (
    AuthoritySource(
        1, "simulation_result", "elaboration/actual simulation result",
        "What the tool actually did: an elaboration error, a real sim.log, a real "
        "waveform. Outranks every description of what should happen.",
        ("simulation", "sim_log", "sim.log", "elaboration", "elab", "waveform", "fsdb",
         "actual_simulation_result", "simulation_result"),
    ),
    AuthoritySource(
        2, "reference_command_txt", "the reference Makefile/command.txt itself",
        "The single execution-authority asset -- the real Makefile / reference "
        "command.txt / BFM pattern file, read literally. run_profile.json sits here "
        "by construction (a mechanical reflection of that file, never a guess).",
        ("reference_makefile", "makefile", "command.txt", "command_txt", "run_profile",
         "run_profile.json", "reference_pattern", "reference_pattern_file", "bfm_pattern"),
    ),
    AuthoritySource(
        3, "dut_rtl", "DUT RTL",
        "The DUT's own RTL source: the address comparator/decoder, the port list, the "
        "parameter, the FSM. What the silicon will actually do.",
        ("rtl", "dut", "decoder", "address_decoder", "rtl_source", "verilog", "systemverilog"),
    ),
    AuthoritySource(
        4, "register_file", "register file (DUT then Global)",
        "A machine-readable register description. Sub-ordered DUT-first, Global-second "
        "(see REGISTER_FILE_SUBORDER) -- a DUT-local register file outranks a chip-wide one.",
        ("regfile", "register_map", "regmap", "ral", "register_description"),
    ),
    AuthoritySource(
        5, "existing_testbench_bind", "existing testbench binds",
        "What the top testbench already binds today -- a working bind is evidence of a "
        "real, elaborated hierarchy path, and outranks any doc describing that hierarchy.",
        ("existing_bind", "testbench_bind", "top_testbench_bind", "bind", "bind_file", "tb_bind"),
    ),
    AuthoritySource(
        6, "controller_doc", "controller doc/programming guide",
        "The controller's own documentation / programming guide / register document -- "
        "spec INTENT. Corroborates; never decides against tiers 1-5.",
        ("programming_guide", "controller_document", "register_doc", "register_document",
         "reg_doc", "spec_doc", "programming_doc"),
    ),
    AuthoritySource(
        7, "ip_user_guide", "IP user guide",
        "The IP vendor's user guide -- one step further from this instance than the "
        "controller's own doc, and correspondingly less authoritative about it.",
        ("user_guide", "ip_ug", "ug", "ip_userguide"),
    ),
    AuthoritySource(
        8, "vip_example", "VIP example",
        "A VIP's shipped example/reference environment. Real code, but written against "
        "the VIP's own demo DUT, not this one.",
        ("vip_sample", "vip_reference_env", "vip_demo", "vip_env_example"),
    ),
    AuthoritySource(
        9, "vip_document", "VIP document",
        "VIP documentation -- lowest. A description of a reference implementation of "
        "somebody else's DUT is the furthest thing here from this DUT's truth.",
        ("vip_doc", "vip_documentation", "vip_user_guide", "vip_ug"),
    ),
)

#: The tie-break INSIDE tier 4 that the doc's "(DUT then Global)" clause
#: states and that prose alone left to a reader to remember. Earlier is
#: higher authority. A claim may carry `qualifier="dut"` / `"global"`; any
#: other qualifier on a register_file claim is refused rather than silently
#: sorted last, because "which register file did you mean" is exactly the
#: thing a silent default gets wrong.
REGISTER_FILE_SUBORDER: tuple = ("dut", "global")

_BY_ID = {s.id: s for s in AUTHORITY_ORDER}

def _key(name: str) -> str:
    """Lookup normalization: case, and whitespace/hyphen/slash all folded to
    `_`. Every alias, id and doc phrase goes through the SAME function on both
    the registration and the lookup side -- registering a raw `.lower()` and
    looking up a `_key()` is how "existing testbench binds" silently became an
    unknown source in the first draft of this module."""
    return re.sub(r"[\s\-/]+", "_", str(name or "").strip().lower())


_BY_ALIAS: Dict[str, AuthoritySource] = {}
for _s in AUTHORITY_ORDER:
    for _name in (_s.id, _s.doc_phrase, *_s.aliases):
        _BY_ALIAS[_key(_name)] = _s


def normalize_source(name) -> str:
    """Canonical source id for `name` (an id, a doc phrase, or any registered
    alias). Raises rather than defaulting: an unrecognized source must never
    be quietly ranked, because the natural silent default (last) would make
    an unknown source LOSE every conflict it takes part in."""
    if isinstance(name, AuthoritySource):
        return name.id
    k = _key(name)
    src = _BY_ALIAS.get(k)
    if src is None:
        raise SourceAuthorityError("UNKNOWN_AUTHORITY_SOURCE", {
            "source": name,
            "known_ids": [s.id for s in AUTHORITY_ORDER],
            "hint": "Add the name to that level's `aliases` if it is a real synonym; "
                    "never rank an unknown source by guessing.",
        })
    return src.id


def authority_source(name) -> AuthoritySource:
    """The full `AuthoritySource` record for `name`."""
    return _BY_ID[normalize_source(name)]


def authority_rank(name) -> int:
    """1 (highest) .. 9 (lowest)."""
    return authority_source(name).rank


def sort_key(name, qualifier: Optional[str] = None) -> tuple:
    """Total ordering key: `(rank, subrank)`. `subrank` is 0 for every level
    without a sub-ordering, and the `REGISTER_FILE_SUBORDER` index for a
    register file -- which is what makes "register file (DUT then Global)"
    a real, testable comparison instead of a parenthetical."""
    src = authority_source(name)
    sub = 0
    if src.id == "register_file" and qualifier is not None:
        q = _key(qualifier)
        if q not in REGISTER_FILE_SUBORDER:
            raise SourceAuthorityError("UNKNOWN_REGISTER_FILE_QUALIFIER", {
                "qualifier": qualifier, "allowed": list(REGISTER_FILE_SUBORDER),
            })
        sub = REGISTER_FILE_SUBORDER.index(q)
    return (src.rank, sub)


def outranks(a, b, *, a_qualifier: Optional[str] = None,
             b_qualifier: Optional[str] = None) -> bool:
    """True iff source `a` is strictly higher authority than source `b`."""
    return sort_key(a, a_qualifier) < sort_key(b, b_qualifier)


# ---------------------------------------------------------------------------
# Claims and conflict resolution
# ---------------------------------------------------------------------------

@dataclass
class SourceClaim:
    """One source stating one thing, WITH the file:line (or real command
    output) it was read from.

    `evidence_path` is mandatory and non-empty by construction. That is the
    whole point of the type: the escalation this module exists to build must
    carry both sides' evidence paths, and the only reliable way to guarantee
    that is to make a claim without one unconstructable, rather than
    checking for it at the far end where it is already too late.
    """
    source: str
    claim: str
    evidence_path: str
    qualifier: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        self.source = normalize_source(self.source)
        if not str(self.claim or "").strip():
            raise SourceAuthorityError("CLAIM_MUST_BE_STATED", {"source": self.source})
        if not str(self.evidence_path or "").strip():
            raise SourceAuthorityError("CLAIM_MUST_CITE_EVIDENCE_PATH", {
                "source": self.source, "claim": self.claim,
                "hint": "file:line, a real command's output, or the exact artifact path. "
                        "An uncited claim is not evidence and may not enter a conflict.",
            })
        # Validates the qualifier eagerly (sort_key raises on a bad one), so a
        # bad register-file qualifier fails at construction, not at compare time.
        sort_key(self.source, self.qualifier)

    @property
    def rank(self) -> int:
        return authority_rank(self.source)

    @property
    def sort_key(self) -> tuple:
        return sort_key(self.source, self.qualifier)

    @property
    def label(self) -> str:
        """Human-facing one-liner used as a question-queue option label."""
        src = _BY_ID[self.source]
        qual = f" ({self.qualifier})" if self.qualifier else ""
        return f"Trust the {src.doc_phrase}{qual} (tier {src.rank}): {self.claim}"

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "doc_phrase": _BY_ID[self.source].doc_phrase,
            "rank": self.rank,
            "qualifier": self.qualifier,
            "claim": self.claim,
            "evidence_path": self.evidence_path,
            "detail": dict(self.detail),
        }


VERDICT_NO_CONFLICT = "NO_CONFLICT"
VERDICT_RESOLVED = "RESOLVED"
VERDICT_UNDECIDABLE = "UNDECIDABLE_SAME_AUTHORITY"


def resolve_conflict(claims: Sequence[SourceClaim]) -> dict:
    """Apply the 9-level order to two or more claims about the same fact.

    Returns a dict with:
      verdict            NO_CONFLICT (every claim states the same thing) |
                         RESOLVED (a single strictly-highest-authority claim) |
                         UNDECIDABLE_SAME_AUTHORITY (the top authority level is
                         occupied by two claims that disagree -- the order
                         cannot break that tie and must not pretend to)
      winner / losers    the ranked claims (winner is None when UNDECIDABLE)
      tied               the disagreeing top-rank claims, when UNDECIDABLE
      authority_gap      winner.rank - best loser rank (negative = how many
                         levels of authority separate the two), None otherwise
      evidence_paths     every claim's cited path, keyed by source id -- the
                         payload the question-queue escalation carries
      rule               the exact ordering sentence this verdict applied

    Refuses fewer than 2 claims: "resolving" a single claim is not a conflict
    resolution, it is just believing the only thing you read, and returning a
    confident-looking verdict for it would be the exact overreach this module
    is meant to remove.
    """
    claims = list(claims)
    if len(claims) < 2:
        raise SourceAuthorityError("CONFLICT_NEEDS_AT_LEAST_TWO_CLAIMS", {
            "claim_count": len(claims),
        })
    for c in claims:
        if not isinstance(c, SourceClaim):
            raise SourceAuthorityError("CLAIMS_MUST_BE_SOURCECLAIM", {"got": type(c).__name__})

    ordered = sorted(claims, key=lambda c: (c.sort_key, c.source))
    evidence_paths = {}
    for c in ordered:
        evidence_paths.setdefault(c.source, []).append(c.evidence_path)

    distinct = {c.claim.strip() for c in claims}
    base = {
        "claims": [c.to_dict() for c in ordered],
        "evidence_paths": evidence_paths,
        "distinct_claim_count": len(distinct),
    }

    if len(distinct) == 1:
        return {**base, "verdict": VERDICT_NO_CONFLICT, "winner": None, "losers": [],
                "tied": [], "authority_gap": None,
                "rule": "All sources state the same thing; no authority ordering needed."}

    top = ordered[0].sort_key
    at_top = [c for c in ordered if c.sort_key == top]
    if len({c.claim.strip() for c in at_top}) > 1:
        return {**base, "verdict": VERDICT_UNDECIDABLE, "winner": None,
                "losers": [], "tied": [c.to_dict() for c in at_top],
                "authority_gap": 0,
                "rule": (f"{len(at_top)} claims sit at the same authority level "
                         f"({_BY_ID[at_top[0].source].doc_phrase}, tier {at_top[0].rank}) and "
                         f"disagree. The authority order cannot break a tie inside one level -- "
                         f"a human must.")}

    winner = at_top[0]
    losers = [c for c in ordered if c is not winner]
    best_loser = losers[0]
    return {**base, "verdict": VERDICT_RESOLVED,
            "winner": winner.to_dict(),
            "losers": [c.to_dict() for c in losers],
            "tied": [],
            "authority_gap": winner.rank - best_loser.rank,
            "rule": (f"{_BY_ID[winner.source].doc_phrase} (tier {winner.rank}) outranks "
                     f"{_BY_ID[best_loser.source].doc_phrase} (tier {best_loser.rank}) -- "
                     f"authority order, highest first.")}


# ---------------------------------------------------------------------------
# Doc <-> code non-drift
# ---------------------------------------------------------------------------

_DOC_PARAGRAPH_RE = re.compile(
    r"Authority order when documentation and the real source disagree.*?(?=\n\n)",
    re.DOTALL,
)
_DOC_LEAD_IN = "(highest first):"
#: Matches only a `N)` that opens a level -- i.e. one preceded by the lead-in
#: or by ", ". A bare `\d\)` would also match inside a phrase, and a
#: `[^,.]` item body would truncate "Makefile/command.txt" at its own dot.
_DOC_ITEM_START_RE = re.compile(r"(?:(?<=:)|(?<=,))\s*(\d)\)\s*")
_DOC_LAST_ITEM_END_RE = re.compile(r"\.(?:\s|$)")


def parse_documented_order(text: Optional[str] = None) -> List[str]:
    """Extract the 9 numbered levels from the real markdown paragraph.

    Reads the DOC, not the code -- a comparison where both sides came from the
    same place would prove nothing. Whitespace/newlines inside the paragraph
    are collapsed first, because the markdown is hard-wrapped and a level's
    phrase routinely straddles a line break.
    """
    if text is None:
        text = DOC_PATH.read_text(encoding="utf-8")
    m = _DOC_PARAGRAPH_RE.search(text)
    if not m:
        raise SourceAuthorityError("AUTHORITY_ORDER_PARAGRAPH_NOT_FOUND", {
            "doc": str(DOC_PATH),
            "expected_lead_in": "Authority order when documentation and the real source disagree",
        })
    para = " ".join(m.group(0).split())
    if _DOC_LEAD_IN not in para:
        raise SourceAuthorityError("AUTHORITY_ORDER_LEAD_IN_NOT_FOUND", {
            "doc": str(DOC_PATH), "expected": _DOC_LEAD_IN,
        })
    # Keep the lead-in's own colon: it is the left boundary the first level's
    # `1)` is recognized by (`(?<=:)`), and splitting it away loses level 1.
    seg = ":" + para.split(_DOC_LEAD_IN, 1)[1]
    starts = [(int(mm.group(1)), mm.start(), mm.end())
              for mm in _DOC_ITEM_START_RE.finditer(seg)]
    items = []
    for i, (n, s, e) in enumerate(starts):
        if i + 1 < len(starts):
            body = seg[e:starts[i + 1][1]]
        else:
            # Last level: runs to the sentence-ending period.
            tail = seg[e:]
            stop = _DOC_LAST_ITEM_END_RE.search(tail)
            body = tail[:stop.start()] if stop else tail
        items.append((n, body.strip().rstrip(",").strip()))
    items.sort()
    if [n for n, _ in items] != list(range(1, len(items) + 1)):
        raise SourceAuthorityError("AUTHORITY_ORDER_PARAGRAPH_NOT_CONSECUTIVE", {
            "parsed": items, "doc": str(DOC_PATH),
        })
    return [p for _, p in items]


def assert_doc_matches_code(text: Optional[str] = None) -> dict:
    """Raise unless the documented paragraph and `AUTHORITY_ORDER` are the
    same list, level for level. Comparison is on the doc phrase, normalized
    for case/whitespace only -- not on a loose "looks similar", which would
    let a reordering through.

    This is the guard that makes moving the order into code an improvement
    rather than a second place for it to be wrong.
    """
    documented = parse_documented_order(text)
    coded = [s.doc_phrase for s in AUTHORITY_ORDER]
    norm = lambda xs: [" ".join(x.lower().split()) for x in xs]
    if norm(documented) != norm(coded):
        raise SourceAuthorityError("AUTHORITY_ORDER_DOC_CODE_DRIFT", {
            "doc": str(DOC_PATH),
            "documented": documented,
            "coded": coded,
            "first_difference": next(
                (i + 1 for i, (d, c) in enumerate(zip(norm(documented), norm(coded))) if d != c),
                min(len(documented), len(coded)) + 1),
        })
    return {"levels": len(coded), "doc": str(DOC_PATH), "status": "IN_SYNC"}


# ---------------------------------------------------------------------------
# Mismatch -> question-queue escalation
# ---------------------------------------------------------------------------

#: Hard-coded Tier-3 context for EVERY source-conflict escalation, mirroring
#: connectivity.T4_QUESTION_CONTEXT's pattern (a fixed, honest context dict
#: rather than a hardcoded tier). `affects_spec_intent` is the queue's own
#: hard trigger and it is the correct one here by definition: two sources
#: disagreeing about the same fact means the stated intent and the real
#: behavior have diverged, and which of the two is wrong is not something any
#: amount of re-reading settles. A caller may override any field via
#: `extra_context=` -- that is the caller asserting a different fact honestly,
#: the same contract every other evidence dict in this codebase carries.
CONFLICT_QUESTION_CONTEXT: dict = {"affects_spec_intent": True}

#: What a conflict escalation says when nobody answers. Deliberately NOT a
#: value: a Tier-3 question never silently uses its assumption, and writing a
#: plausible value here would be the one string a future tier relaxation could
#: pick up and act on.
NO_SAFE_ASSUMPTION = (
    "NONE IS SAFE -- a source conflict is Tier-3 by construction; the higher-authority "
    "value may be used to keep running, but the disagreement itself stays open until a "
    "human says which artifact is wrong."
)


def _option_for(claim: SourceClaim) -> dict:
    """One question-queue option = one side of the conflict, with THAT side's
    evidence path as its rationale. This is the shape that makes "carries both
    evidence paths" a structural property of the record rather than a hope
    about how the question text was phrased."""
    return {"label": claim.label, "rationale": f"evidence: {claim.evidence_path}"}


def format_conflict_question(conflict: dict, *, subject: str) -> str:
    """The question text. Names every side with its evidence path inline, so
    the paths survive even in a rendering (digest, markdown table) that shows
    only `question` and drops the options."""
    lines = [f"Source conflict on {subject}: "]
    parts = []
    for c in conflict["claims"]:
        parts.append(f"{c['doc_phrase']} (tier {c['rank']}) says \"{c['claim']}\" "
                     f"[evidence: {c['evidence_path']}]")
    lines.append("; ".join(parts))
    lines.append(f". {conflict['rule']}")
    if conflict["verdict"] == VERDICT_RESOLVED:
        lines.append(" The higher-authority value is what execution uses; this question is "
                     "which of the two artifacts is wrong/stale, which authority order "
                     "cannot answer.")
    return "".join(lines)


def assert_both_evidence_paths_present(question_text: str, options: Sequence[dict],
                                       conflict: dict) -> None:
    """Refuse a conflict question that fails to carry EVERY side's evidence
    path. Runs before the record is handed to the queue -- an escalation that
    names a disagreement without saying where to go look at both halves of it
    is worse than none, because it reads as actioned work while leaving the
    reader with nowhere to start."""
    blob = question_text + " " + " ".join(
        f"{o.get('label','')} {o.get('rationale','')}" for o in options)
    missing = [c["evidence_path"] for c in conflict["claims"]
               if c["evidence_path"] not in blob]
    if missing:
        raise SourceAuthorityError("CONFLICT_QUESTION_MISSING_EVIDENCE_PATH", {
            "missing_evidence_paths": missing,
            "claim_count": len(conflict["claims"]),
        })


def escalate_conflict(store, conflict: dict, *, domain: str, subject: str,
                      context_path: Optional[str] = None,
                      question_key: Optional[str] = None,
                      extra_context: Optional[dict] = None,
                      now=None) -> Optional[dict]:
    """File one resolved/undecidable source conflict into the REAL question
    queue and return the persisted record. Returns None (asks nothing) for a
    NO_CONFLICT verdict -- agreement is not a question.

    `store` is a `question_queue.QuestionQueueStore` or a project-root path to
    build one from (same convenience `connectivity.build_t4_question_queue_
    entry()` already offers, so the two escalation paths accept the same
    argument).

    The queue's own machinery is reused wholesale and none of it is
    re-implemented here: the Q-ID is DERIVED from the question key (so
    re-running a detector over unchanged sources re-mints the SAME id instead
    of a duplicate), the owner comes from `route_owner(domain)`, and the tier
    comes from `classify_tier()` against `CONFLICT_QUESTION_CONTEXT`.

    A conflict with more than 3 sides is refused rather than truncated: the
    queue's schema allows 2-3 pre-researched options, and silently dropping
    the 4th source would drop its evidence path with it.
    """
    from . import question_queue  # local import: keeps this module importable
                                  # without pulling in the queue's own deps

    if conflict.get("verdict") == VERDICT_NO_CONFLICT:
        return None
    if conflict.get("verdict") not in (VERDICT_RESOLVED, VERDICT_UNDECIDABLE):
        raise SourceAuthorityError("UNKNOWN_CONFLICT_VERDICT", {"verdict": conflict.get("verdict")})

    if isinstance(store, (str, Path)):
        store = question_queue.QuestionQueueStore(Path(store))

    claims = [SourceClaim(source=c["source"], claim=c["claim"],
                          evidence_path=c["evidence_path"], qualifier=c.get("qualifier"))
              for c in conflict["claims"]]
    if not (2 <= len(claims) <= 3):
        raise SourceAuthorityError("CONFLICT_SIDES_MUST_BE_2_TO_3", {
            "side_count": len(claims),
            "hint": "The question schema allows 2-3 pre-researched options; splitting a "
                    "wider conflict into pairwise questions keeps every evidence path.",
        })

    options = [_option_for(c) for c in claims]
    question_text = format_conflict_question(conflict, subject=subject)
    assert_both_evidence_paths_present(question_text, options, conflict)

    if conflict["verdict"] == VERDICT_RESOLVED:
        recommendation = next(o["label"] for o, c in zip(options, claims)
                              if c.source == conflict["winner"]["source"]
                              and c.claim == conflict["winner"]["claim"])
    else:
        # No authority-derived winner exists. Recommending one anyway would be
        # this module inventing the very tie-break it just reported it cannot
        # make, so the recommendation is the highest-authority side ONLY as a
        # starting point and the question text says the order could not decide.
        recommendation = options[0]["label"]

    ctx = dict(CONFLICT_QUESTION_CONTEXT)
    ctx.update(extra_context or {})

    # Dedup on question_key BEFORE adding. `QuestionQueueStore.add_question()`
    # appends unconditionally -- two asks of the same key mint the same Q-ID
    # but produce two records -- which is fine for the hand-called escalations
    # it was written for, and wrong for a detector wired into an audit that
    # reruns. Caught for real: running `audit_directory(question_store=...)`
    # twice over the real reference/bfm_patterns/ corpus took the queue from
    # 12 questions to 24, all duplicate ids. An already-asked question is not
    # asked again; the EXISTING record is returned, so a caller sees its
    # current status (still OPEN, or since ANSWERED in place) rather than a
    # fresh OPEN copy that hides the answer.
    key = question_key or question_queue.make_question_key(
        domain, question_text, context_path or claims[0].evidence_path)
    for existing in store.list_questions():
        if existing.get("question_key") == key:
            return existing

    return store.add_question(
        domain=domain,
        question=question_text,
        context_path=context_path or claims[0].evidence_path,
        options=options,
        recommendation=recommendation,
        assumption_if_unanswered=NO_SAFE_ASSUMPTION,
        question_key=question_key,
        context=ctx,
        now=now,
    )


def describe_order() -> List[dict]:
    """JSON-serializable rendering of the 9 levels -- what
    `dv-harness authority order --json` prints."""
    return [{"rank": s.rank, "id": s.id, "doc_phrase": s.doc_phrase,
             "description": s.description,
             "sub_order": list(REGISTER_FILE_SUBORDER) if s.id == "register_file" else None}
            for s in AUTHORITY_ORDER]


def format_order() -> str:
    lines = ["Source authority order (highest first) -- docs/RUN_PROFILE.md, "
             "enforced by dv_harness/source_authority.py:"]
    for s in AUTHORITY_ORDER:
        lines.append(f"  {s.rank}. {s.doc_phrase}")
        lines.append(f"       {s.description}")
        if s.id == "register_file":
            lines.append(f"       sub-order within this tier: {' > '.join(REGISTER_FILE_SUBORDER)}")
    return "\n".join(lines)
