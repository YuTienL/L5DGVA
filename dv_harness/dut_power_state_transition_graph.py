"""dv_harness/dut_power_state_transition_graph.py -- DUT power-state
transition graph, built ONLY from DOCUMENTED transition sequences.

THE GAP THIS CLOSES. `power_intent.py` is a real UPF (IEEE 1801) reader and
self-consistency analysis over a project's own POWER-INTENT file -- power
DOMAINS, SUPPLY topology, SWITCH/ISOLATION/RETENTION strategies. Its own
module docstring is explicit about a boundary it deliberately does not cross:
"Power STATE tables (`add_power_state`, `create_pst`, `add_pst_state`) are
parsed as unsupported-but-recorded rather than modelled." So a UPF file can
name real power *states* (`add_power_state ... -state {ON ...}`), but nothing
in `power_intent.py` ever turns those into a *transition graph* -- which
state may legally move to which other state, and under what documented
trigger. That is the gap this module closes, and ONLY that gap: it is not a
UPF parser, and it does not touch `power_intent.py` at all (no import, no
edit).

WHY THIS IS NOT, AND STRUCTURALLY CANNOT BE, A SIMULATION-DERIVED GRAPH. This
project owns no live simulator, no low-power DUT of its own, and no
power-aware simulation flow -- `power_intent.py`'s own docstring says so in
as many words ("This project owns no low-power DUT and no real UPF of its
own"). A power-state transition graph derived by actually EXERCISING a DUT
through its state machine would need exactly that infrastructure. What this
project *can* honestly produce is a graph built from what a real spec/
programming-guide/UPF-adjacent DOCUMENT already SAYS about legal transitions
-- a state diagram described in prose, an arrow chain, a transition table --
never a claim about what silicon or RTL actually does. Every node and every
edge in the graph this module produces carries a real `file:line` citation
back to the sentence/row that asserted it; there is no other way into this
graph, and `GRAPH_NOT_SIMULATION_DISCLOSURE` is carried on every report this
module produces so a reader can never mistake it for verified behaviour.

WHY A LINE-SCAN OVER CALLER-SUPPLIED TEXT, AND `spec_doc_map.py`'s REAL ROLE.
`spec_doc_map.py` is this project's real STRUCTURAL distiller for a DUT spec/
programming-guide PDF -- and its own docstring is explicit that it retains
NO body prose, ever: "No document body text appears in this file, ever."
So `spec_doc_map.py`'s real, honest role here is DISCOVERY, not extraction:
its `.structure_map.json` record can tell a caller WHERE a power-state/power-
mode section or a transition TABLE lives (a heading whose title names power
states, a `Table N-M: Power State Transitions`-shaped caption, each with a
real page number) -- never what it says. This module is the sibling that
then reads the real TEXT at that location (a caller-supplied source file,
exactly the same "spec/programming-guide TEXT a caller supplies" convention
`design_lifecycle_flow.py`/`interrupt_dma_clock_reset_extraction.py`/
`perf_function_extraction.py` already use) and extracts the actual
transition graph from it. Neither `spec_doc_map.py` nor
`design_lifecycle_flow.py` is imported here -- this module re-derives its own
small, bounded heading-detection helper, per this codebase's own established
convention (see e.g. `memory_buffer_arch_extraction.py`,
`rtl_data_path_extraction.py`, `amba_command_txt_extension.py`, each of which
owns its own small regex helper rather than importing a sibling's private
one) and per the identical two reasons `spec_doc_map.py`'s own docstring
states for staying independent of `vip_user_guide_distill.py`: scope
(this module extracts GRAPH content, `spec_doc_map.py`'s own contract forbids
it from ever retaining any) and independent testability across a
multi-agent batch.

WHAT COUNTS AS A DOCUMENTED TRANSITION, and only three real shapes. Within a
heading-detected power-state/power-mode section, a line is recognized as one
or more real transition EDGES only when it takes one of three explicit,
disclosed shapes: (1) an ARROW line (`D0 -> D1`, `D0 <-> D3`, optionally
followed by a `(trigger)`/`: trigger`/`on <event>`/`when <condition>`
annotation -- a bidirectional arrow yields TWO edges, both citing the same
line, both flagged `bidirectional_pair: true` so a reader knows the trigger
text may not apply identically in both directions); (2) a "From X to Y[,:]
<trigger>" sentence, the real prose form a power-management chapter
routinely uses instead of a diagram; (3) a Markdown-table row under a real
`From | To | Trigger` (or `.../Condition/Event`) header. A line matching
none of the three contributes nothing -- never a guessed edge. This module
performs NO domain reasoning about what a real DUT's power states typically
look like; a state's NAME is never validated against any known vocabulary,
because doing so would risk silently dropping a real, project-specific state
name this scan has never seen before.

GRAPH FACTS COMPUTED FROM THE EXTRACTED EDGES ARE MECHANICAL, NEVER A DOMAIN
CLAIM. `nodes` is the union of every `from_state`/`to_state` seen across
every extracted edge (a state is never independently "declared" -- it exists
in this graph because a real transition named it). `terminal_states` (no
outgoing edge) and `source_states` (no incoming edge) are a real degree
count, nothing more -- neither is presented as "these are illegal deadlock
states" or "these are legal entry points", only as the structural fact a
reader can interpret themselves. `has_cycle` is a real DFS-based cycle
detection over the extracted edges -- a genuinely computed graph property,
not a guess. `default_state` is populated ONLY from an explicit, cited
"default/initial power state is X" or "reset (power) state is X" sentence
found in the same section text; absent one, it is honestly `None` with
`default_state_status = "NOT_DOCUMENTED"` -- never inferred from graph
structure (e.g. "the state with the most incoming edges is probably the
default"), which would be exactly the confident guess the Evidence Truth
Rule forbids.

DELIBERATELY BOUNDED, and stated rather than implied closed. (1) This is a
line/regex scan, not a document-structure parser or a diagram-image reader:
a transition described only as an embedded state-diagram IMAGE, or as prose
narrative with none of the three recognized shapes, contributes nothing
rather than a guessed reconstruction. (2) A state's identity is matched by
exact string (after whitespace trimming) only -- "D0" and "d0" are two
different nodes, and no fuzzy/case-insensitive merging is attempted, because
merging incorrectly would silently misrepresent the document's own two
possibly-distinct names as one. (3) It decides, approves and arbitrates
nothing beyond reporting: no build, job, or approval is touched, and there is
deliberately no stage gate. (4) There is no `dv-harness` CLI verb and
`cli.py`/`gates.py` were not touched, matching this project's own disclosed
convention for a standalone module built while those two files are under
concurrent edit pressure -- the front door is
`python -m dv_harness.dut_power_state_transition_graph extract --sources <f>
[<f> ...] [--json]`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

STATUS_LOADED = "LOADED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

DEFAULT_STATE_STATUS_DOCUMENTED = "DOCUMENTED"
DEFAULT_STATE_STATUS_NOT_DOCUMENTED = "NOT_DOCUMENTED"

GRAPH_NOT_SIMULATION_DISCLOSURE = (
    "This graph is built ONLY from what a real spec/programming-guide/UPF-adjacent document "
    "already documents about power-state transitions -- an arrow chain, a 'From X to Y' "
    "sentence, or a From/To transition table, each cited to a real file:line. This project owns "
    "no live simulator and no low-power DUT of its own, so this graph is structurally NEVER "
    "derived from a simulation or from real silicon/RTL behaviour, and no edge or node here is a "
    "claim that a real DUT actually implements the documented transition."
)

TEXT_SUFFIXES = (".txt", ".md", ".rst", ".pgv", ".spec")


# ---------------------------------------------------------------------------
# Heading detection -- re-derived locally (never imported from
# design_lifecycle_flow.py/spec_doc_map.py), per this module's own docstring.
# A heading-CANDIDATE line (matched or not) always ends the current section,
# so unrelated content beneath an unrelated heading can never leak into a
# power-state block.
# ---------------------------------------------------------------------------
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
_PROSE_HEADING_RE = re.compile(r"^(?P<title>[A-Z][\w /&\-]{2,70}):?\s*$")
_FENCE_LINE_RE = re.compile(r"^\s*```")
_LOWER_LINK_WORDS = frozenset({"of", "and", "the", "for", "to", "in", "a", "or", "on", "if", "is"})
_TITLE_CASE_WORD_RE = re.compile(r"^[A-Za-z0-9][a-zA-Z0-9]*$")

POWER_STATE_HEADING_RE = re.compile(
    r"\bpower\s+(?:state|mode)s?\b"
    r"|\b(?:state|mode)\s+power\b"
    r"|\bpower\s+management\b"
    r"|\blow[-\s]?power\s+(?:state|mode)s?\b"
    r"|\bpower\s+sequenc\w*\b"
    r"|\bpower\s+transition\w*\b",
    re.IGNORECASE,
)


def _is_title_case_heading(title: str, *, colon_terminated: bool) -> bool:
    """Same discipline `design_lifecycle_flow.py`'s own identically-named
    helper uses -- re-derived here rather than imported. See that module's
    own docstring note for the exact reasoning: a bare, single-word,
    non-colon-terminated line is resolved in favor of being ordinary
    content, not a heading."""
    words = re.findall(r"[A-Za-z0-9&]+", title)
    if not words:
        return False
    if len(words) < 2 and not colon_terminated:
        return False
    for w in words:
        if w.lower() in _LOWER_LINK_WORDS:
            continue
        if not _TITLE_CASE_WORD_RE.match(w):
            return False
        if not (w[0].isupper() or w.isupper()):
            return False
    return True


def _heading_title(line: str) -> Optional[str]:
    stripped = line.rstrip()
    if not stripped or len(stripped) > 100:
        return None
    m = _MARKDOWN_HEADING_RE.match(stripped)
    if m:
        return m.group("title").strip()
    if stripped.endswith("."):
        return None
    if re.match(r"^\s*[-*•]\s", stripped):
        return None
    if re.match(r"^\s*\d+[.)]\s", stripped):
        return None
    if _FENCE_LINE_RE.match(stripped):
        return None
    m = _PROSE_HEADING_RE.match(stripped)
    if m and _is_title_case_heading(m.group("title"), colon_terminated=stripped.endswith(":")):
        return m.group("title").strip()
    return None


def _find_power_state_sections(lines: List[str]) -> List[Tuple[int, List[str]]]:
    """Walk `lines` once, splitting on every heading-candidate line. Returns
    every block whose OWN heading matched `POWER_STATE_HEADING_RE`, as
    `(heading_lineno_1based, content_lines)` -- a document may legitimately
    carry more than one such heading (a top-level "Power Management" chapter
    plus a nested "Power State Transitions" subsection), so every block is
    preserved rather than only the first."""
    blocks: List[Tuple[int, List[str]]] = []
    matched = False
    start: Optional[int] = None
    content: List[str] = []

    def _flush() -> None:
        if matched and start is not None:
            blocks.append((start, content[:]))

    for lineno, line in enumerate(lines, start=1):
        title = _heading_title(line)
        if title is not None:
            _flush()
            matched = bool(POWER_STATE_HEADING_RE.search(title))
            start = lineno
            content = []
            continue
        if matched:
            content.append("" if _FENCE_LINE_RE.match(line) else line)
    _flush()
    return blocks


# ---------------------------------------------------------------------------
# Edge extraction: an arrow line, a "From X to Y" sentence, or a From/To
# Markdown table row -- tried per-line, in that order, within one
# power-state block's own content.
# ---------------------------------------------------------------------------
_ARROW_LINE_RE = re.compile(
    r"^\s*(?P<from>[A-Za-z][A-Za-z0-9_./ -]{0,39}?)\s*"
    r"(?P<arrow><->|<=>|->|=>|↔|→)\s*(?P<rest>.+?)\s*$"
)
_BIDIRECTIONAL_ARROWS = frozenset({"<->", "<=>", "↔"})

_TO_TRIG_PAREN_COLON_RE = re.compile(
    r"^(?P<to>[^():]{1,40}?)\s*(?:\((?P<trig_p>.+?)\)\s*$|:\s*(?P<trig_c>.+)$)?$"
)
_KEYWORD_TRIGGER_RE = re.compile(
    r"^(?P<to>.+?)\s+(?P<kw>on|when|via|triggered by|due to)\s+(?P<trig>.+)$",
    re.IGNORECASE,
)

_FROM_TO_RE = re.compile(
    r"^\s*(?:\d+[.)]\s*)?From\s+(?P<from>[A-Za-z][A-Za-z0-9_./ -]{0,39}?)\s+to\s+"
    r"(?P<to>[A-Za-z][A-Za-z0-9_./ -]{0,39}?)"
    r"(?:\s*[:,]\s*(?P<trig>.+?))?\.?\s*$",
    re.IGNORECASE,
)

_TABLE_ROW_RE = re.compile(r"^\s*\|?(?P<body>.+?)\|?\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_TABLE_HEADER_RE = re.compile(
    r"^\s*\|?\s*From\s*\|\s*To\s*(?:\|\s*(?P<trig_col>Trigger|Condition|Event)[^|]*)?\|?\s*$",
    re.IGNORECASE,
)


def _split_to_and_trigger(rest: str) -> Tuple[str, Optional[str]]:
    """Given the text after an arrow, return `(to_state, trigger)`. See the
    module docstring's shape (1) for the three recognized trailing-trigger
    forms this handles: `(trigger)`, `: trigger`, and a bare
    `on/when/via/triggered by/due to <trigger>` suffix with no punctuation
    at all."""
    rest = rest.strip()
    m = _TO_TRIG_PAREN_COLON_RE.match(rest)
    if not m:
        return rest, None
    to = m.group("to").strip()
    trig = m.group("trig_p") or m.group("trig_c")
    trig = trig.strip() if trig else None
    if trig is None:
        km = _KEYWORD_TRIGGER_RE.match(to)
        if km:
            to = km.group("to").strip()
            trig = f"{km.group('kw')} {km.group('trig')}".strip()
    return to, trig


@dataclass
class PowerStateEdge:
    from_state: str
    to_state: str
    trigger: Optional[str]
    evidence: str
    bidirectional_pair: bool = False

    def to_dict(self) -> dict:
        return {
            "from_state": self.from_state, "to_state": self.to_state,
            "trigger": self.trigger, "evidence": self.evidence,
            "bidirectional_pair": self.bidirectional_pair,
        }


@dataclass
class PowerStateNode:
    name: str
    evidence: str

    def to_dict(self) -> dict:
        return {"name": self.name, "evidence": self.evidence}


def _match_arrow_line(line: str, evidence: str) -> List[PowerStateEdge]:
    m = _ARROW_LINE_RE.match(line)
    if not m:
        return []
    frm = m.group("from").strip()
    arrow = m.group("arrow")
    to, trig = _split_to_and_trigger(m.group("rest"))
    if not to:
        return []
    bidirectional = arrow in _BIDIRECTIONAL_ARROWS
    if bidirectional:
        return [
            PowerStateEdge(from_state=frm, to_state=to, trigger=trig, evidence=evidence,
                            bidirectional_pair=True),
            PowerStateEdge(from_state=to, to_state=frm, trigger=trig, evidence=evidence,
                            bidirectional_pair=True),
        ]
    return [PowerStateEdge(from_state=frm, to_state=to, trigger=trig, evidence=evidence)]


def _match_from_to_sentence(line: str, evidence: str) -> List[PowerStateEdge]:
    m = _FROM_TO_RE.match(line)
    if not m:
        return []
    frm = m.group("from").strip()
    to = m.group("to").strip()
    trig = m.group("trig")
    trig = trig.strip() if trig else None
    return [PowerStateEdge(from_state=frm, to_state=to, trigger=trig, evidence=evidence)]


def _parse_table_row(line: str) -> Optional[List[str]]:
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return None
    cells = [c.strip() for c in m.group("body").split("|")]
    if len(cells) < 2 or not cells[0] or not cells[1]:
        return None
    return cells


def _extract_edges_from_block(content: List[str], start_lineno: int, path: str) -> List[PowerStateEdge]:
    """Walk one power-state block's own content lines once, recognizing a
    Markdown From/To table (stateful across consecutive rows), an arrow
    line, or a "From X to Y" sentence -- tried in that priority order per
    line, since a table row could otherwise be mis-parsed as an arrow-less
    sentence. A blank line ends an in-progress table (a table's own rows are
    always contiguous)."""
    edges: List[PowerStateEdge] = []
    in_table = False
    table_has_trigger = False

    for offset, raw_line in enumerate(content):
        lineno = start_lineno + offset
        stripped = raw_line.strip()
        evidence = f"{path}:{lineno}"
        if not stripped:
            in_table = False
            continue
        if in_table:
            if _TABLE_SEPARATOR_RE.match(stripped):
                continue
            row = _parse_table_row(stripped)
            if row is not None:
                trig = row[2] if (table_has_trigger and len(row) > 2 and row[2]) else None
                edges.append(PowerStateEdge(from_state=row[0], to_state=row[1], trigger=trig,
                                             evidence=evidence))
                continue
            in_table = False
            # fall through -- this line may still be a real arrow/sentence edge
        header = _TABLE_HEADER_RE.match(stripped)
        if header is not None:
            in_table = True
            table_has_trigger = header.group("trig_col") is not None
            continue
        edges.extend(_match_arrow_line(stripped, evidence))
        edges.extend(_match_from_to_sentence(stripped, evidence))

    return edges


# ---------------------------------------------------------------------------
# Default/initial power-state citation -- explicit sentence only, never
# inferred from graph structure.
# ---------------------------------------------------------------------------
_DEFAULT_STATE_RE = re.compile(
    r"\b(?:default|initial)\s+power\s+(?:state|mode)\s+is\s+['\"]?"
    r"(?P<state>[A-Za-z][\w./-]{0,20})['\"]?",
    re.IGNORECASE,
)
_RESET_STATE_RE = re.compile(
    r"\breset\s+(?:power\s+)?(?:state|mode)\s+is\s+['\"]?"
    r"(?P<state>[A-Za-z][\w./-]{0,20})['\"]?",
    re.IGNORECASE,
)


def _find_default_state(content: List[str], start_lineno: int, path: str) -> Tuple[Optional[str], Optional[str]]:
    for offset, line in enumerate(content):
        m = _DEFAULT_STATE_RE.search(line) or _RESET_STATE_RE.search(line)
        if m:
            state = m.group("state").rstrip(".,;:")
            return state, f"{path}:{start_lineno + offset}"
    return None, None


# ---------------------------------------------------------------------------
# Graph assembly + mechanical graph facts
# ---------------------------------------------------------------------------
def _dedupe_edges(edges: Sequence[PowerStateEdge]) -> List[PowerStateEdge]:
    seen = set()
    out: List[PowerStateEdge] = []
    for e in edges:
        key = (e.from_state, e.to_state, e.trigger)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _build_nodes(edges: Sequence[PowerStateEdge]) -> List[PowerStateNode]:
    first_evidence: Dict[str, str] = {}
    order: List[str] = []
    for e in edges:
        for name in (e.from_state, e.to_state):
            if name not in first_evidence:
                first_evidence[name] = e.evidence
                order.append(name)
    return [PowerStateNode(name=n, evidence=first_evidence[n]) for n in order]


def detect_cycle(node_names: Sequence[str], edges: Sequence[PowerStateEdge]) -> Optional[List[str]]:
    """A real, DFS-based cycle detection over the extracted directed graph.
    Returns the first cycle found as an ordered list of state names (the
    last entry repeats the first, closing the loop), or `None` when the
    graph is acyclic. This is a genuinely computed graph property, not a
    guess -- and it is never presented as a defect: a real power-state
    machine legitimately has cycles (e.g. ACTIVE <-> IDLE)."""
    adj: Dict[str, List[str]] = {n: [] for n in node_names}
    for e in edges:
        adj.setdefault(e.from_state, []).append(e.to_state)
        adj.setdefault(e.to_state, [])

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {n: WHITE for n in adj}
    path: List[str] = []
    result: Optional[List[str]] = None

    def dfs(u: str) -> None:
        nonlocal result
        color[u] = GRAY
        path.append(u)
        for v in adj[u]:
            if result is not None:
                return
            if color[v] == GRAY:
                idx = path.index(v)
                result = path[idx:] + [v]
                return
            if color[v] == WHITE:
                dfs(v)
                if result is not None:
                    return
        path.pop()
        color[u] = BLACK

    for n in list(adj.keys()):
        if result is not None:
            break
        if color[n] == WHITE:
            dfs(n)
    return result


def _degree_facts(node_names: Sequence[str], edges: Sequence[PowerStateEdge]) -> Tuple[List[str], List[str]]:
    out_deg = {n: 0 for n in node_names}
    in_deg = {n: 0 for n in node_names}
    for e in edges:
        out_deg[e.from_state] = out_deg.get(e.from_state, 0) + 1
        in_deg[e.to_state] = in_deg.get(e.to_state, 0) + 1
    terminal = sorted(n for n in node_names if out_deg.get(n, 0) == 0)
    source = sorted(n for n in node_names if in_deg.get(n, 0) == 0)
    return terminal, source


def _extract_single_source_graph(lines: List[str], path: str) -> Tuple[List[PowerStateEdge], Optional[str], Optional[str]]:
    """Extract every edge and the (at most one, first-found) default-state
    citation from one already-read source file's own lines."""
    blocks = _find_power_state_sections(lines)
    edges: List[PowerStateEdge] = []
    default_state: Optional[str] = None
    default_evidence: Optional[str] = None
    for heading_lineno, content in blocks:
        edges.extend(_extract_edges_from_block(content, heading_lineno + 1, path))
        if default_state is None:
            default_state, default_evidence = _find_default_state(content, heading_lineno + 1, path)
    return edges, default_state, default_evidence


def classify_source(path) -> str:
    suffix = Path(path).suffix.lower()
    return "text" if suffix in TEXT_SUFFIXES else "unknown"


def extract_power_state_transition_graph(source_paths) -> dict:
    """Extract the DUT power-state transition graph from real spec/
    programming-guide TEXT files a caller supplies. `source_paths` is a list
    of str/Path; every file is read (never fabricated), and a missing/
    unreadable file is recorded as an honest per-source failure rather than
    silently skipped or raised past the caller."""
    source_paths = list(source_paths or [])
    read_sources: List[str] = []
    missing_sources: List[str] = []
    unrecognized_sources: List[str] = []
    any_heading_found = False

    all_edges: List[PowerStateEdge] = []
    default_state: Optional[str] = None
    default_evidence: Optional[str] = None

    for raw_path in source_paths:
        p = Path(raw_path)
        if not p.is_file():
            missing_sources.append(str(raw_path))
            continue
        if classify_source(p) == "unknown":
            unrecognized_sources.append(str(raw_path))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            missing_sources.append(f"{raw_path} ({exc})")
            continue
        path_str = str(raw_path)
        read_sources.append(path_str)
        lines = text.splitlines()

        blocks = _find_power_state_sections(lines)
        if blocks:
            any_heading_found = True
        this_edges, this_default, this_default_evidence = _extract_single_source_graph(lines, path_str)
        all_edges.extend(this_edges)
        if default_state is None and this_default is not None:
            default_state, default_evidence = this_default, this_default_evidence

    if not source_paths:
        return _not_available_report([], [], [], "no source files were supplied")
    if not read_sources:
        return _not_available_report(
            read_sources, missing_sources, unrecognized_sources,
            f"none of the {len(source_paths)} supplied source path(s) could be read: {missing_sources}")

    edges = _dedupe_edges(all_edges)
    if not edges:
        if not any_heading_found:
            reason = "no heading naming a power-state/power-mode section was found in the supplied sources"
        else:
            reason = ("a power-state/power-mode heading was found but no recognizable transition edge "
                      "(an arrow line, a 'From X to Y' sentence, or a From/To transition table row) "
                      "was found beneath it")
        return _not_available_report(read_sources, missing_sources, unrecognized_sources, reason)

    nodes = _build_nodes(edges)
    node_names = [n.name for n in nodes]
    cycle = detect_cycle(node_names, edges)
    terminal_states, source_states = _degree_facts(node_names, edges)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_LOADED,
        "reason": None,
        "disclosure": GRAPH_NOT_SIMULATION_DISCLOSURE,
        "source": {"kind": "power_state_transition_source_text", "paths": read_sources,
                   "missing": missing_sources, "unrecognized": unrecognized_sources},
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "terminal_states": terminal_states,
        "source_states": source_states,
        "has_cycle": cycle is not None,
        "example_cycle": cycle,
        "default_state": default_state,
        "default_state_evidence": default_evidence,
        "default_state_status": (DEFAULT_STATE_STATUS_DOCUMENTED if default_state is not None
                                  else DEFAULT_STATE_STATUS_NOT_DOCUMENTED),
    }


def _not_available_report(read_sources, missing_sources, unrecognized_sources, reason) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_NOT_AVAILABLE,
        "reason": reason,
        "disclosure": GRAPH_NOT_SIMULATION_DISCLOSURE,
        "source": {"kind": "power_state_transition_source_text", "paths": read_sources,
                   "missing": missing_sources, "unrecognized": unrecognized_sources},
        "nodes": [],
        "edges": [],
        "node_count": 0,
        "edge_count": 0,
        "terminal_states": [],
        "source_states": [],
        "has_cycle": False,
        "example_cycle": None,
        "default_state": None,
        "default_state_evidence": None,
        "default_state_status": DEFAULT_STATE_STATUS_NOT_DOCUMENTED,
    }


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's status/default-state vocabulary must share no token
    with `models.Status` -- the same guarantee several sibling extraction/
    analysis modules already hold for their own vocabularies."""
    from .models import Status

    verdicts = {s.value for s in Status}
    own = {STATUS_LOADED, STATUS_NOT_AVAILABLE, DEFAULT_STATE_STATUS_DOCUMENTED,
           DEFAULT_STATE_STATUS_NOT_DOCUMENTED}
    overlap = own & verdicts
    if overlap:
        raise AssertionError(
            f"dut_power_state_transition_graph vocabulary collides with models.Status: {sorted(overlap)}")


assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Ad hoc entry point -- same shared convention as
# `design_lifecycle_flow.py`/`interrupt_dma_clock_reset_extraction.py`. Not
# wired into cli.py (per this batch's file-safety scope); the integrator may
# add a `dv-harness power-state-graph --sources <f> [<f> ...] [--json]` verb
# calling `execute_verb()` below.
# ---------------------------------------------------------------------------
def execute_verb(argv: list) -> int:
    import sys as _sys

    if not argv or argv[0] not in ("extract",):
        print("usage: dut_power_state_transition_graph extract --sources <f> [<f> ...] [--json]",
              file=_sys.stderr)
        return 2
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if "--sources" in args:
        idx = args.index("--sources")
        sources = args[idx + 1:]
    else:
        sources = args
    report = extract_power_state_transition_graph(sources)
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}" + (f" ({report['reason']})" if report["reason"] else ""))
        print(f"  nodes: {report['node_count']}  edges: {report['edge_count']}  "
              f"has_cycle: {report['has_cycle']}")
        print(f"  default_state: {report['default_state']} ({report['default_state_status']})")
        if report["terminal_states"]:
            print(f"  terminal_states: {report['terminal_states']}")
        if report["source_states"]:
            print(f"  source_states: {report['source_states']}")
        for e in report["edges"]:
            trig = f"  [{e['trigger']}]" if e["trigger"] else ""
            print(f"  {e['from_state']} -> {e['to_state']}{trig}  ({e['evidence']})")
    return 0 if report["status"] == STATUS_LOADED else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
