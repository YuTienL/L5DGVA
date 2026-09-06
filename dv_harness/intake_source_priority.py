"""dv_harness/intake_source_priority.py -- the 10-step INTAKE SOURCE PRIORITY
ladder as executable code: a DISCOVERY order, not a conflict-resolution
order.

WHY THIS MODULE EXISTS:
"Which source do I consult FIRST when a fact is not yet known" and "two
sources I already read disagree about the same fact -- which one is true"
are two different questions, and this repo already carries a documented
lesson about NOT confusing them. `dv_harness/source_authority.py`'s own
module docstring states it plainly: its `AUTHORITY_ORDER` is the CONFLICT
order (highest-authority-wins when two already-read sources disagree), and
it is explicitly "NOT the same list as
`tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER`" -- the
pre-existing 9-item DISCOVERY order (EXISTING_PROJECT_FILES ... ASK_USER)
that gate script enforces for one narrow evidence-trace shape. That
docstring records that the two 9-item lists have ALREADY caused one real
mis-identification, purely because they happened to be the same length.

This module is a THIRD list, and it is deliberately not a copy of either
of the other two:

  * It is a DISCOVERY order, like the gate script's `ORDER` -- not a
    conflict order like `source_authority.AUTHORITY_ORDER`. Consulting it
    answers "which of these ten source kinds should I look at next for a
    fact I don't have yet", never "which of two claims I already hold is
    true". `source_authority.resolve_conflict()` is the right tool for that
    second question and is untouched by anything here.
  * It is a WIDER, more general intake ladder than the gate script's 9-item
    `ORDER`. That `ORDER` is scoped to one evidence-trace shape used by one
    gate (`--trace <file>` carrying `attempted_sources`/
    `higher_priority_sources_exhausted`) and is intentionally left alone --
    re-deriving or wrapping it here would risk exactly the kind of silent
    two-lists-treated-as-one bug `source_authority.py` already had to
    document. This module's 10 steps are a superset re-grouping for the
    general "what should I look at first when building/extending a
    verification environment" intake question (repo files on disk,
    existing generated UVM, build/Makefile, RTL/PHY, register files, specs/
    datasheets, VIP examples, regression lists, git history, ask the user)
    -- ten items, deliberately not nine, so a length-based mix-up with
    EITHER existing 9-item list is structurally impossible from the start.
    `assert_distinct_from_known_discovery_and_conflict_orders()` below makes
    that a checked fact rather than a hopeful design note.

THREE THINGS THIS MODULE MAKES MACHINE-ENFORCED, not prose:

  1. The order itself (`INTAKE_SOURCE_ORDER`, `intake_rank`,
     `normalize_intake_source`) -- a real, alias-resolving, unknown-source-
     refusing lookup table, the same shape `source_authority.py` already
     established for its own (different) order.

  2. The lookup: `next_sources_to_check(fact_name, available_sources)`. A
     fact is not yet known; a caller states which of the 10 kinds are
     actually AVAILABLE for the current project (a project with no RTL tree
     of its own, say, never has "RTL/PHY source" to offer); this returns
     those available kinds in DISCOVERY-priority order, highest first,
     always ending at "ask the user" when it is offered at all -- never
     re-deriving a new order per fact, because the ladder is the same ten
     steps for every fact, exactly as the reference gate's own `ORDER`
     applies uniformly regardless of what is being discovered.

  3. The cross-check that keeps this list from ever being silently confused
     with either of the other two (`assert_distinct_from_known_discovery_
     and_conflict_orders()`): different lengths from BOTH, no CANONICAL id
     of either table silently accepted by the OTHER table's own lookup
     (ordinary alias-level vocabulary overlap between the two -- e.g. both
     tables legitimately discussing "RTL" or "register files" as real
     artifacts -- is expected and untouched; only a table's own id being
     mistaken for a name IN the other table is the dangerous case), and a
     live re-parse of the gate script's own `ORDER` constant (never
     imported -- see below) confirming this ladder's ten phrases are not
     that ORDER's nine, word for word.

WHY THE GATE SCRIPT'S MODULE IS NEVER IMPORTED:
`tools/verification_flow/evidence_source_priority_gate.py` calls
`argparse.parse_args()` at MODULE LEVEL (not guarded by
`if __name__ == "__main__":`), so `import`-ing it executes argument parsing
against whatever `sys.argv` this process happens to have and raises/exits
immediately outside its own CLI invocation. The cross-check instead reads
that file's real text off disk and regex-extracts its literal `ORDER = [...]`
list -- the same "parse the real artifact, never re-type it" discipline
`source_authority.parse_documented_order()` already applies to
`docs/RUN_PROFILE.md`'s prose paragraph.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The pre-existing 9-item discovery-order gate this module is deliberately
#: NOT a copy of. Read for the cross-check only (see module docstring for
#: why it is never imported).
EVIDENCE_SOURCE_PRIORITY_GATE_PATH = (
    REPO_ROOT / "tools" / "verification_flow" / "evidence_source_priority_gate.py"
)


class IntakeSourcePriorityError(ValueError):
    """Typed error, same convention as `source_authority.SourceAuthorityError`:
    a short SCREAMING_SNAKE_CASE `reason` plus a concrete `detail` dict --
    never a silently-dropped fact and never a silently-guessed rank."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class IntakeSource:
    """One rung of the discovery ladder. `rank` is 1-based, 1 = check FIRST.

    Mirrors `source_authority.AuthoritySource`'s shape deliberately, so a
    reader who already knows that dataclass recognizes this one -- but the
    two are separate types (never the same class reused across the two
    orders), which is one more structural barrier against a shared caller
    silently treating a record from one table as if it were the other's.
    """
    rank: int
    id: str
    phrase: str
    description: str
    aliases: tuple = ()


#: Check-first-to-check-last. Ten steps, per this module's task: repo files
#: already on disk, existing generated UVM environment, build scripts/
#: Makefile, RTL/PHY source, register files, specs/datasheets, VIP examples,
#: regression lists, git history, ask the user.
INTAKE_SOURCE_ORDER: tuple = (
    IntakeSource(
        1, "repo_files_on_disk", "repo files already on disk",
        "Whatever this project already has checked in or generated on disk -- "
        "manifests, prior env.manifest.json, project config, prior generator "
        "output. The cheapest possible look, and the one most likely to already "
        "answer a fact without touching anything else.",
        ("repo_files", "project_files", "files_on_disk", "existing_repo_files",
         "checked_in_files"),
    ),
    IntakeSource(
        2, "existing_uvm_environment", "existing UVM environment already generated",
        "A UVM environment this harness (or a prior session) already generated "
        "for this project -- agents/scoreboards/sequences/binds already on disk. "
        "If the fact is 'what does this environment already do', a generated "
        "environment answers it directly; re-deriving it from RTL or a doc "
        "first would ignore a real fixed point on disk.",
        ("existing_env", "generated_uvm_env", "generated_environment",
         "existing_environment", "prior_generated_env"),
    ),
    IntakeSource(
        3, "build_scripts_makefile", "build scripts / Makefile",
        "The project's own build/run scripts and Makefile -- what actually "
        "compiles/elaborates/runs this project today. Real execution-authority "
        "text, cheap to read, and often answers 'does X exist / how is X built' "
        "before any source needs opening.",
        ("build_scripts", "makefile", "make", "run_scripts", "sim_scripts",
         "build_makefile"),
    ),
    IntakeSource(
        4, "rtl_phy_source", "RTL/PHY source",
        "The DUT/PHY's own RTL source -- module ports, parameters, the real "
        "hierarchy. Authoritative about the design itself, but a real file to "
        "open and parse, one step more expensive than the first three. (Not "
        "`source_authority.AUTHORITY_ORDER`'s `dut_rtl` id/alias set -- kept "
        "deliberately non-overlapping; see the module docstring.)",
        ("rtl", "phy", "rtl_source", "phy_source", "verilog", "systemverilog"),
    ),
    IntakeSource(
        5, "register_files", "register files",
        "A machine-readable register description (regmap/RAL/register JSON) -- "
        "narrower and more specific than the RTL itself, consulted once the "
        "broader RTL/PHY look did not already answer the fact. (Not "
        "`source_authority.AUTHORITY_ORDER`'s `register_file` id -- this "
        "table's id is deliberately plural to keep the two distinct.)",
        ("regfile", "register_map", "regmap", "ral", "register_description"),
    ),
    IntakeSource(
        6, "specs_datasheets", "specs/datasheets",
        "Controller/IP specifications and datasheets -- documented design "
        "INTENT, consulted after the machine-checkable artifacts above because "
        "a spec can describe an intent the real RTL/build never implemented.",
        ("spec", "specs", "datasheet", "datasheets", "programming_guide",
         "ip_spec"),
    ),
    IntakeSource(
        7, "vip_examples", "VIP examples",
        "A VIP's own shipped example/reference environment -- real code, but "
        "written against the VIP's own demo DUT, not this project's. Useful "
        "once this project's own artifacts (1-6) have been checked and did not "
        "answer the fact. (Not `source_authority.AUTHORITY_ORDER`'s "
        "`vip_example` singular id -- this table's id is deliberately plural.)",
        ("vip_sample", "vip_reference_env", "vip_demo"),
    ),
    IntakeSource(
        8, "regression_lists", "regression lists",
        "Existing regression/test lists (regression.list, command.txt inventory, "
        "vPlan test tables) -- what this project already runs today, checked "
        "after the design-facing sources above rather than before them, since a "
        "test list describes coverage INTENT, not the design.",
        ("regression_list", "regression.list", "test_list", "vplan_test_table",
         "command_inventory"),
    ),
    IntakeSource(
        9, "git_history", "git history",
        "Commit history/messages for this project -- what changed, when, and "
        "why (per a real commit message), consulted after every present-tense "
        "artifact above has been checked and still leaves the fact open.",
        ("git", "git_log", "git_history", "commit_history", "commit_log"),
    ),
    IntakeSource(
        10, "ask_user", "ask the user",
        "The last resort: every other available source (of the ones actually "
        "offered for this project) has been checked and the fact is still "
        "unknown. This module never treats an absent higher-priority source as "
        "'checked' -- see `next_sources_to_check()`'s own docstring.",
        ("ask_the_user", "human", "user", "ask_human"),
    ),
)

_BY_ID = {s.id: s for s in INTAKE_SOURCE_ORDER}


def _key(name: str) -> str:
    """Lookup normalization, identical folding rule to
    `source_authority._key()` (case, whitespace/hyphen/slash folded to `_`) --
    kept as the SAME rule deliberately, so the two tables differ only in
    their real content, never in an incidental normalization quirk that could
    make one accept a name the other rejects for no real reason."""
    return re.sub(r"[\s\-/]+", "_", str(name or "").strip().lower())


_BY_ALIAS: Dict[str, IntakeSource] = {}
for _s in INTAKE_SOURCE_ORDER:
    for _name in (_s.id, _s.phrase, *_s.aliases):
        _BY_ALIAS[_key(_name)] = _s


def normalize_intake_source(name) -> str:
    """Canonical source id for `name` (an id, a phrase, or a registered
    alias). Raises rather than defaulting -- an unrecognized source must
    never be quietly ranked or quietly dropped from a returned order."""
    if isinstance(name, IntakeSource):
        return name.id
    k = _key(name)
    src = _BY_ALIAS.get(k)
    if src is None:
        raise IntakeSourcePriorityError("UNKNOWN_INTAKE_SOURCE", {
            "source": name,
            "known_ids": [s.id for s in INTAKE_SOURCE_ORDER],
            "hint": "Add the name to that step's `aliases` if it is a real synonym; "
                    "never rank an unrecognized source by guessing.",
        })
    return src.id


def intake_source(name) -> IntakeSource:
    """The full `IntakeSource` record for `name`."""
    return _BY_ID[normalize_intake_source(name)]


def intake_rank(name) -> int:
    """1 (check first) .. 10 (ask the user)."""
    return intake_source(name).rank


# ---------------------------------------------------------------------------
# The lookup this module exists to provide
# ---------------------------------------------------------------------------

def next_sources_to_check(fact_name: str, available_sources: Iterable[str]) -> List[dict]:
    """Given a FACT not yet known, and which of the 10 discovery-order source
    kinds are actually AVAILABLE for the current project, return those kinds
    in the order they should be checked -- highest discovery-priority first.

    The ladder itself never changes per fact: `fact_name` is carried through
    into every returned row purely so a caller's own evidence trail records
    which fact this particular ordered list was produced for, exactly the way
    a `SourceClaim`'s `evidence_path` is carried through
    `source_authority.py` rather than being ranking input. Two projects
    asking about two different facts but offering the SAME available sources
    get back the SAME order -- and that is correct: this is a ladder of
    SOURCE KINDS, not a per-fact heuristic.

    `available_sources` is REQUIRED to be non-empty: a caller with genuinely
    nothing available (not even a human to ask) has not stated a real
    intake situation, and defaulting to "ask_user" silently would hide that
    the caller never declared it. Any entry this module does not recognize
    raises via `normalize_intake_source()` rather than being silently
    dropped -- a caller that mistyped an id must find out, not get a
    shorter list back with no explanation.

    Never returns "ask_user" ahead of an offered higher-priority source --
    that ordering falls straight out of filtering `INTAKE_SOURCE_ORDER` by
    rank, so a caller cannot accidentally ask a human before it has even
    tried a source it declared it has.
    """
    if not str(fact_name or "").strip():
        raise IntakeSourcePriorityError("FACT_NAME_MUST_BE_STATED", {
            "hint": "Discovering a source order for an unnamed fact cannot be "
                    "recorded as evidence for anything.",
        })
    available = list(available_sources)
    if not available:
        raise IntakeSourcePriorityError("NO_AVAILABLE_SOURCES_DECLARED", {
            "fact_name": fact_name,
            "hint": "State which of the 10 source kinds this project actually has "
                    "access to -- even if the only one is 'ask_user'. An empty list "
                    "must never silently become 'ask the user'.",
        })
    normalized_available = {normalize_intake_source(s) for s in available}
    ordered = [s for s in INTAKE_SOURCE_ORDER if s.id in normalized_available]
    return [
        {
            "fact_name": fact_name,
            "rank": s.rank,
            "id": s.id,
            "phrase": s.phrase,
            "description": s.description,
        }
        for s in ordered
    ]


def first_source_to_check(fact_name: str, available_sources: Iterable[str]) -> dict:
    """Convenience: just the single next thing to look at."""
    return next_sources_to_check(fact_name, available_sources)[0]


# ---------------------------------------------------------------------------
# Cross-check: this ladder is never the same list as the other two
# ---------------------------------------------------------------------------

_GATE_ORDER_RE = re.compile(r"ORDER\s*=\s*\[(.*?)\]")


def parse_evidence_source_priority_gate_order(text: Optional[str] = None) -> List[str]:
    """Extract the real 9-item `ORDER` list out of
    `tools/verification_flow/evidence_source_priority_gate.py`'s own source
    text. Reads the FILE, never imports the module (see module docstring for
    why importing it is unsafe), and never re-types the list by hand -- a
    hand-typed copy is exactly the kind of second place for a fact to be
    wrong this codebase's house style forbids."""
    if text is None:
        text = EVIDENCE_SOURCE_PRIORITY_GATE_PATH.read_text(encoding="utf-8")
    m = _GATE_ORDER_RE.search(text)
    if not m:
        raise IntakeSourcePriorityError("EVIDENCE_SOURCE_PRIORITY_GATE_ORDER_NOT_FOUND", {
            "path": str(EVIDENCE_SOURCE_PRIORITY_GATE_PATH),
        })
    items = re.findall(r"'([^']+)'", m.group(1))
    if not items:
        raise IntakeSourcePriorityError("EVIDENCE_SOURCE_PRIORITY_GATE_ORDER_EMPTY", {
            "path": str(EVIDENCE_SOURCE_PRIORITY_GATE_PATH),
        })
    return items


def assert_distinct_from_known_discovery_and_conflict_orders(
    gate_order_text: Optional[str] = None,
) -> dict:
    """Raise unless `INTAKE_SOURCE_ORDER` is provably a DIFFERENT list from
    both (a) `source_authority.AUTHORITY_ORDER` (the CONFLICT order -- a
    different KIND of list entirely) and (b) the gate script's own 9-item
    discovery `ORDER` (the same KIND of list, and therefore the one most at
    risk of being silently treated as identical to this one). This is the
    explicit self-check this module's task calls for, mirroring
    `source_authority.assert_doc_matches_code()`'s "parse the real artifact
    and compare, never eyeball it" pattern -- except here the assertion is
    DIFFERENCE, not agreement, because these three ladders must never merge
    into one under a shared caller.

    Three independent checks, any one of which failing means a shared caller
    could confuse this list with one of the other two:

      1. LENGTH. `source_authority.py`'s own docstring records that its
         9-item list and the gate script's 9-item list have ALREADY been
         mis-identified once purely because they were the same length. This
         module is 10 items so it cannot repeat that exact coincidence with
         EITHER other list -- checked here rather than merely asserted in
         prose, so a future edit that trimmed a step would fail loudly.
      2. CANONICAL-ID CROSS-RESOLUTION with `source_authority.AUTHORITY_
         ORDER`. Deliberately NOT "no shared vocabulary at all" -- the two
         tables legitimately discuss some of the same real artifacts (RTL,
         register files, VIP examples), so ordinary synonyms overlapping in
         each table's own `aliases` is expected and harmless. What must
         never happen is a table's own CANONICAL id being silently ACCEPTED
         by the OTHER table's lookup: that is the concrete way "a shared
         caller treats these as the same list" would actually manifest --
         code holding a `source.id` from one table and, without checking
         which table it came from, handing it to the other table's
         normalize/rank function and getting a confident answer instead of
         the `UNKNOWN_*_SOURCE` refusal that is supposed to catch exactly
         this. Checked in both directions.
      3. CONTENT vs. the gate script's real, freshly re-parsed `ORDER` --
         this ladder's 10 phrases must not equal that list's 9 phrases
         (impossible on length alone, checked anyway so this function still
         means something if the gate script's list ever changed length too).
    """
    from . import source_authority

    if len(INTAKE_SOURCE_ORDER) == len(source_authority.AUTHORITY_ORDER):
        raise IntakeSourcePriorityError(
            "INTAKE_LADDER_LENGTH_CONFUSABLE_WITH_AUTHORITY_ORDER", {
                "intake_levels": len(INTAKE_SOURCE_ORDER),
                "authority_levels": len(source_authority.AUTHORITY_ORDER),
            })

    intake_ids = {s.id for s in INTAKE_SOURCE_ORDER}
    authority_ids = {s.id for s in source_authority.AUTHORITY_ORDER}

    authority_ids_accepted_here = [i for i in authority_ids if _key(i) in _BY_ALIAS]
    if authority_ids_accepted_here:
        raise IntakeSourcePriorityError(
            "AUTHORITY_ORDER_ID_RESOLVES_IN_INTAKE_LADDER", {
                "ids": sorted(authority_ids_accepted_here),
                "hint": "A source_authority.AUTHORITY_ORDER canonical id must never also "
                        "resolve through this table's own normalize_intake_source().",
            })

    intake_ids_accepted_there = []
    for i in intake_ids:
        try:
            source_authority.normalize_source(i)
        except source_authority.SourceAuthorityError:
            continue
        intake_ids_accepted_there.append(i)
    if intake_ids_accepted_there:
        raise IntakeSourcePriorityError(
            "INTAKE_LADDER_ID_RESOLVES_IN_AUTHORITY_ORDER", {
                "ids": sorted(intake_ids_accepted_there),
                "hint": "This table's own canonical id must never also resolve through "
                        "source_authority.normalize_source().",
            })

    # Content checked BEFORE length here, deliberately: an equal-length,
    # identical-content fabrication must be caught as IDENTICAL (the more
    # specific, more alarming finding) rather than being pre-empted by the
    # length check below -- which would make the content check dead code,
    # never reachable because equal length always raises first.
    gate_order = parse_evidence_source_priority_gate_order(gate_order_text)
    intake_phrases = [s.phrase for s in INTAKE_SOURCE_ORDER]
    if intake_phrases == gate_order:
        raise IntakeSourcePriorityError(
            "INTAKE_LADDER_IDENTICAL_TO_EVIDENCE_SOURCE_PRIORITY_GATE_ORDER", {
                "order": gate_order,
            })
    if len(INTAKE_SOURCE_ORDER) == len(gate_order):
        raise IntakeSourcePriorityError(
            "INTAKE_LADDER_LENGTH_CONFUSABLE_WITH_EVIDENCE_SOURCE_PRIORITY_GATE_ORDER", {
                "intake_levels": len(INTAKE_SOURCE_ORDER),
                "gate_order_levels": len(gate_order),
            })

    return {
        "status": "DISTINCT",
        "intake_levels": len(INTAKE_SOURCE_ORDER),
        "authority_order_levels": len(source_authority.AUTHORITY_ORDER),
        "evidence_source_priority_gate_order_levels": len(gate_order),
    }


# ---------------------------------------------------------------------------
# Rendering / standalone front door
# ---------------------------------------------------------------------------

def describe_order() -> List[dict]:
    """JSON-serializable rendering of the 10 steps."""
    return [{"rank": s.rank, "id": s.id, "phrase": s.phrase,
             "description": s.description} for s in INTAKE_SOURCE_ORDER]


def format_order() -> str:
    lines = ["Intake source priority ladder (check first -> last), "
             "dv_harness/intake_source_priority.py:"]
    for s in INTAKE_SOURCE_ORDER:
        lines.append(f"  {s.rank}. {s.phrase}")
        lines.append(f"       {s.description}")
    return "\n".join(lines)


def execute_verb(argv: Optional[List[str]] = None) -> int:
    """Shared front door: `python -m dv_harness.intake_source_priority ...`.
    No `dv-harness` CLI subcommand is added -- this is a small, standalone
    lookup table with no natural home in the existing argparse tree, per
    this project's own "skip the CLI wiring when it would be awkward" rule.

    Exit codes follow this package's own convention: 0 = at least one
    non-'ask_user' source is available to check next; 1 = a real finding --
    'ask_user' is the ONLY available source, i.e. a human must be asked;
    2 = nothing to report (no sources declared, or a malformed request).
    """
    ap = argparse.ArgumentParser(prog="python -m dv_harness.intake_source_priority")
    sub = ap.add_subparsers(dest="verb", required=True)

    sub.add_parser("order", help="Print the 10-step discovery ladder.")

    p_next = sub.add_parser(
        "next", help="Order the AVAILABLE sources for one not-yet-known fact.")
    p_next.add_argument("--fact", required=True)
    p_next.add_argument("--available", required=True,
                         help="Comma-separated source ids/aliases actually available.")
    p_next.add_argument("--json", action="store_true")

    sub.add_parser(
        "self-check",
        help="Assert this ladder is distinct from both known 9-item lists.")

    args = ap.parse_args(argv)

    if args.verb == "order":
        print(format_order())
        return 0

    if args.verb == "self-check":
        try:
            result = assert_distinct_from_known_discovery_and_conflict_orders()
        except IntakeSourcePriorityError as exc:
            print(json.dumps({"status": "FAIL", "reason": exc.reason, "detail": exc.detail}))
            return 2
        print(json.dumps(result))
        return 0

    # args.verb == "next"
    try:
        available = [a for a in (x.strip() for x in args.available.split(",")) if a]
        rows = next_sources_to_check(args.fact, available)
    except IntakeSourcePriorityError as exc:
        print(json.dumps({"status": "FAIL", "reason": exc.reason, "detail": exc.detail}))
        return 2

    if args.json:
        print(json.dumps(rows))
    else:
        print(f"Intake order for fact '{args.fact}':")
        for row in rows:
            print(f"  {row['rank']}. {row['phrase']}")

    if len(rows) == 1 and rows[0]["id"] == "ask_user":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(execute_verb())
