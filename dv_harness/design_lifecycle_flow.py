"""dv_harness/design_lifecycle_flow.py -- Design Initialization / Shutdown /
Recovery flow extraction (spec sections 311-313).

WHAT THIS IS. Sections 311-313 of `CLAUDE_L5_SUBSYSTEM_DESIGN_INTELLIGENCE.md`
ask for three documented lifecycle flows to be built "from evidence" (never
invented): an INITIALIZATION flow (Reset -> Clock/PHY readiness -> Base
config -> Mode config -> Buffer/DMA setup -> Interrupt setup -> Enable block
-> Wait ready -> Start operation, the section's own generic illustration --
"actual sequence must come from source evidence"), a SHUTDOWN flow (stop
traffic -> wait idle -> disable engine -> clear pending status -> disable
interrupts -> power/clock transition -> reset if required), and a RECOVERY
flow keyed by named trigger conditions (timeout, protocol error, PHY error,
DMA error, buffer error, software abort, link loss).

This module reads whatever real spec/programming-guide TEXT a caller
supplies, locates a heading-like line naming one of the three flow domains,
and extracts the ordered step chain documented directly beneath it -- a
numbered list, a bulleted list, or an arrow chain (`->`/`=>`/the literal `->`
glyph), matching the same shape the master prompt's own illustrations use.
A section with none of those three step-chain shapes contributes nothing,
never a guessed flow.

REUSING `programming_sequence_ir.py`'s PHASE VOCABULARY DIRECTLY -- the
task's own explicit instruction, and this module's whole reason for not
building a second phase taxonomy. `PHASE_INIT` / `PHASE_CONFIGURE` /
`PHASE_ENABLE` / `PHASE_RUN` / `PHASE_WAIT` / `PHASE_VERIFY` /
`PHASE_DISABLE` / `PHASE_RESET`, `PHASE_RANK`, and `CANONICAL_PHASES` are all
IMPORTED from `programming_sequence_ir.py`, never re-declared here. Every
extracted step is classified into exactly one of those eight phases (or
reported UNCLASSIFIED, honestly, when no keyword pattern matches) --
`classify_step_phase()` is a real, cited, keyword-based classifier, never a
guess from step position alone.

WHY NOT A DIRECT CALL INTO `programming_sequence_ir.validate_step_ordering()`.
That function's own PHASE-ORDERING check (its item 1) is correct and exactly
what this module wants, but it is gated behind a non-empty `register_facts`
argument: `if not facts_list: return NOT_AVAILABLE` fires BEFORE the phase
check ever runs, because that function's other three checks (access-type
legality, `depends_on` ordering, the illegal-sequence catalog) all genuinely
need real register facts and the function reports one combined status. A
documented lifecycle-flow step ("Enable block", "Wait ready") routinely names
no specific register at all, so this module would supply an empty facts list
on every real call and never see the phase-ordering verdict it exists to
compute. Rather than force a placeholder register fact into every call (which
would misrepresent an unattached prose step as tied to a specific register),
`check_phase_order()` below is a small, local, REGISTER-FREE monotonicity
check reusing `PHASE_RANK` -- the SAME table, imported, never re-declared --
exactly the piece `validate_step_ordering()`'s own item 1 uses internally.
This is a disclosed, deliberate choice, not a silent duplication: the two
functions decide phase ordering identically (same rank table, same
non-decreasing rule), and `to_programming_sequence_ir()` below still builds
the real `programming_sequence_ir.ProgrammingSequenceStep` /
`ProgrammingSequenceIR` objects (imported types, not re-declared) so a caller
who DOES have real register facts for a given flow (once a step is tied to a
concrete register, e.g. through a future `init_seq.py`/
`register_excel_extract.py` join) can pass the SAME IR into
`programming_sequence_ir.validate_step_ordering()` for the fuller
access-type/`depends_on` check, with no re-parsing needed.

WHY NOT `init_seq.py`. That module already owns register WRITE ORDER for one
specific interface's bring-up, loaded from a project's own hand-authored
`init_seq.yaml` (a structured document, not spec prose) -- it is a Gate-2
precondition input, not a spec-text extractor, and it has no shutdown or
recovery concept at all. Nothing in `init_seq.py` is duplicated here, and
this module imports nothing from it.

EVIDENCE TRUTH RULE, applied to every layer of this module. A flow with no
recognized heading in the supplied sources is `NOT_AVAILABLE` naming that
absence. A recognized heading with no recognizable step-chain shape beneath
it is `NOT_AVAILABLE` naming THAT absence, distinctly, rather than reporting
zero steps as if the flow had been checked and found empty. A step whose text
matches no phase keyword is UNCLASSIFIED, never coerced onto the nearest-
sounding canonical phase. A recovery trigger (timeout / protocol_error /
phy_error / dma_error / buffer_error / software_abort / link_loss) with no
matching evidence anywhere in the supplied sources is independently
`NOT_AVAILABLE`, per trigger -- one trigger's absence never masks another's
presence, mirroring `interrupt_dma_clock_reset_extraction.py`'s own
per-facet-independent-status discipline.

WHAT IS DELIBERATELY NOT ATTEMPTED. This is a line/regex scan, not a
document-structure parser: a flow described across multiple disconnected
paragraphs, or one whose steps are expressed as a prose narrative with no
list/arrow shape at all, contributes nothing rather than a guessed
reconstruction. Recovery-trigger detection matches a small, fixed set of
documented phrasings (see `TRIGGER_PATTERNS`); a differently-worded but
equally real trigger condition is honestly not recognized rather than
approximated by a broader keyword scan. `classify_step_phase()`'s keyword
tables are per-flow-context (the SAME step text can classify differently in
an initialization vs. a shutdown context -- e.g. a bare "Reset" step is the
INIT-phase precondition at the START of bring-up, while "reset if required"
is the RESET-phase teardown action at the END of shutdown) -- this is real,
disclosed, structural evidence (which heading the step was extracted from),
never a guess independent of that context.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .programming_sequence_ir import (
    ACTION_WAIT,
    CANONICAL_PHASES,
    PHASE_CONFIGURE,
    PHASE_DISABLE,
    PHASE_ENABLE,
    PHASE_INIT,
    PHASE_RANK,
    PHASE_RESET,
    PHASE_RUN,
    PHASE_VERIFY,
    PHASE_WAIT,
    ProgrammingSequenceIR,
    ProgrammingSequenceStep,
)

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Flow / status vocabulary. Deliberately NOT `models.Status` -- see
# `assert_no_verification_verdict_vocabulary()` below.
# ---------------------------------------------------------------------------
FLOW_INITIALIZATION = "initialization"
FLOW_SHUTDOWN = "shutdown"
FLOW_RECOVERY = "recovery"
FLOW_KINDS = (FLOW_INITIALIZATION, FLOW_SHUTDOWN, FLOW_RECOVERY)

STATUS_LOADED = "LOADED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"

PHASE_STATUS_CLASSIFIED = "CLASSIFIED"
PHASE_STATUS_UNCLASSIFIED = "UNCLASSIFIED"
_UNCLASSIFIED_PHASE_TOKEN = "UNCLASSIFIED"  # never a member of PHASE_RANK

PHASE_ORDER_VALID = "PHASE_ORDER_VALID"
PHASE_ORDER_VIOLATION = "PHASE_ORDER_VIOLATION"
PHASE_ORDER_NOT_APPLICABLE = "PHASE_ORDER_NOT_APPLICABLE"

# Section 313's own seven named recovery trigger conditions.
TRIGGER_TIMEOUT = "timeout"
TRIGGER_PROTOCOL_ERROR = "protocol_error"
TRIGGER_PHY_ERROR = "phy_error"
TRIGGER_DMA_ERROR = "dma_error"
TRIGGER_BUFFER_ERROR = "buffer_error"
TRIGGER_SOFTWARE_ABORT = "software_abort"
TRIGGER_LINK_LOSS = "link_loss"
RECOVERY_TRIGGERS = (
    TRIGGER_TIMEOUT, TRIGGER_PROTOCOL_ERROR, TRIGGER_PHY_ERROR, TRIGGER_DMA_ERROR,
    TRIGGER_BUFFER_ERROR, TRIGGER_SOFTWARE_ABORT, TRIGGER_LINK_LOSS,
)

TRIGGER_PATTERNS: Dict[str, "re.Pattern"] = {
    TRIGGER_TIMEOUT: re.compile(r"\btimeout\b", re.IGNORECASE),
    TRIGGER_PROTOCOL_ERROR: re.compile(r"\bprotocol\s+error\b", re.IGNORECASE),
    TRIGGER_PHY_ERROR: re.compile(r"\bphy\s+error\b", re.IGNORECASE),
    TRIGGER_DMA_ERROR: re.compile(r"\bdma\s+error\b", re.IGNORECASE),
    TRIGGER_BUFFER_ERROR: re.compile(r"\bbuffer\s+(?:error|overflow|underflow)\b", re.IGNORECASE),
    TRIGGER_SOFTWARE_ABORT: re.compile(r"\bsoftware\s+abort\b|\bsw\s+abort\b", re.IGNORECASE),
    TRIGGER_LINK_LOSS: re.compile(r"\blink\s+(?:loss|down)\b", re.IGNORECASE),
}

TEXT_SUFFIXES = (".txt", ".md", ".rst", ".pgv", ".spec")


class DesignLifecycleFlowError(ValueError):
    """A design-lifecycle-flow input is malformed -- raised rather than
    silently coerced."""


@dataclass
class FlowStep:
    index: int
    text: str
    evidence: str
    phase: Optional[str] = None  # one of CANONICAL_PHASES, or None (UNCLASSIFIED)

    @property
    def phase_status(self) -> str:
        return PHASE_STATUS_CLASSIFIED if self.phase is not None else PHASE_STATUS_UNCLASSIFIED

    def to_dict(self) -> dict:
        return {
            "index": self.index, "text": self.text, "evidence": self.evidence,
            "phase": self.phase, "phase_status": self.phase_status,
        }


# ---------------------------------------------------------------------------
# Heading detection -- generic, section-marker line scan, mirroring the
# "section resets at every heading-like line, matched or not" discipline
# `phy_model_behavior_ir.py` already established for the identical reason: a
# heading candidate that does NOT name a recognized flow domain still ends
# the current flow's content block, so unrelated section content can never
# leak into a flow's step chain.
# ---------------------------------------------------------------------------
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
_PROSE_HEADING_RE = re.compile(r"^(?P<title>[A-Z][\w /&\-]{2,70}):?\s*$")
_FENCE_LINE_RE = re.compile(r"^\s*```")

INIT_HEADING_RE = re.compile(r"initializ|power[-\s]?up|powerup|bring[-\s]?up", re.IGNORECASE)
SHUTDOWN_HEADING_RE = re.compile(r"shutdown|power[-\s]?down|powerdown|disable\s+sequence", re.IGNORECASE)
RECOVERY_HEADING_RE = re.compile(r"recovery|error\s+handling", re.IGNORECASE)

_FLOW_HEADING_PATTERNS = (
    (FLOW_INITIALIZATION, INIT_HEADING_RE),
    (FLOW_SHUTDOWN, SHUTDOWN_HEADING_RE),
    (FLOW_RECOVERY, RECOVERY_HEADING_RE),
)

# A bare numbered section heading with no markdown "#" prefix (e.g. a raw
# "311. DESIGN INITIALIZATION FLOW" line) is deliberately NOT recognized as
# a heading here -- its own line shape ("<digits>. <text>") is structurally
# indistinguishable from a numbered STEP list item ("1. Assert reset"), and
# guessing which one a bare numbered line is would risk silently truncating
# a real step chain the moment its own numbering looks heading-like. A
# project's own spec-distillation pipeline (`vip_user_guide_distill.py` /
# `spec_doc_map.py`) already renders a distilled document's real section
# structure as markdown/plain headings before this module would read it, so
# this is a disclosed, deliberate scope boundary rather than an oversight.
_LOWER_LINK_WORDS = frozenset({"of", "and", "the", "for", "to", "in", "a", "or", "on", "if", "is"})
_TITLE_CASE_WORD_RE = re.compile(r"^[A-Za-z0-9][a-zA-Z0-9]*$")


def _is_title_case_heading(title: str, *, colon_terminated: bool) -> bool:
    """A prose line only counts as a heading candidate when it reads like a
    real section title -- every significant word capitalized (or the whole
    word in caps), short link words excepted -- AND is either multi-word or
    ends with a colon. This is what keeps two real ambiguities from being
    mistaken for a section boundary: an ordinary sentence-fragment step
    ("Example generic form:" -- fails the title-case check, since "generic"
    is neither capitalized nor a link word), and a BARE SINGLE-WORD flow
    step with no trailing punctuation ("Reset", the literal first step of
    section 311's own arrow-chain illustration -- a single capitalized word
    is exactly as plausible as a step as it is a heading, so this module
    resolves the ambiguity in the step's favor unless it is either
    multi-word ("Timeout Recovery") or colon-terminated ("Timeout:"), both
    real, stronger heading signals a bare step word does not carry)."""
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
    """A heading-CANDIDATE line's title text, or None if `line` is not
    heading-shaped at all. A prose sentence (ends in '.') or a list item
    (leading `-`/`*`/bullet/numbered-list marker) is never a heading
    candidate, so an ordinary flow step never gets mistaken for a section
    boundary."""
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


def _classify_heading(title: str) -> Optional[str]:
    for kind, pattern in _FLOW_HEADING_PATTERNS:
        if pattern.search(title):
            return kind
    return None


def _find_flow_sections(lines: List[str]) -> Dict[str, List[Tuple[int, List[str]]]]:
    """Walk `lines` once, splitting on every heading-CANDIDATE line (matched
    or not -- see the module note above). Returns
    `{flow_kind: [(heading_lineno_1based, content_lines), ...]}` -- a flow
    domain may legitimately have more than one recognized heading in one
    document (e.g. a per-trigger recovery sub-section still under a top-level
    "Error Handling" heading), so every block is preserved rather than only
    the first."""
    sections: Dict[str, List[Tuple[int, List[str]]]] = {k: [] for k in FLOW_KINDS}
    current_kind: Optional[str] = None
    current_start: Optional[int] = None
    current_content: List[str] = []

    def _flush() -> None:
        if current_kind is not None:
            sections[current_kind].append((current_start, current_content[:]))

    for lineno, line in enumerate(lines, start=1):
        title = _heading_title(line)
        if title is not None:
            new_kind = _classify_heading(title)
            if new_kind is not None and new_kind == current_kind:
                # A NESTED heading of the SAME flow domain (most notably:
                # a per-trigger recovery sub-heading such as "Timeout
                # Recovery" underneath a top-level "Error Recovery" heading
                # -- both match RECOVERY_HEADING_RE) stays part of the SAME
                # content block rather than starting a new top-level
                # section. Its own heading TEXT is kept in the content
                # (never blanked), so `extract_recovery_triggers()`'s own
                # nested heading scan can still see and classify it.
                current_content.append(line)
                continue
            _flush()
            current_kind = new_kind
            current_start = lineno
            current_content = []
            continue
        if current_kind is not None:
            # A markdown code-fence marker line is blanked (never dropped,
            # so 1:1 line-offset alignment with real evidence line numbers
            # is preserved) -- it is not a step, a heading, or content.
            current_content.append("" if _FENCE_LINE_RE.match(line) else line)
    _flush()
    return sections


# ---------------------------------------------------------------------------
# Step-chain extraction: numbered list, bulleted list, or arrow chain --
# tried in that order against one flow section's content lines. The first
# recognized shape wins; a section matching none of the three contributes no
# steps.
# ---------------------------------------------------------------------------
_NUMBERED_STEP_RE = re.compile(r"^\s*(?:Step\s+)?(?P<num>\d+)[.)]\s+(?P<text>.+?)\s*$")
_BULLET_STEP_RE = re.compile(r"^\s*[-*•]\s+(?P<text>.+?)\s*$")
_ARROW_TOKEN_RE = re.compile(r"→|->|=>")
_ARROW_PREFIX_RE = re.compile(r"^\s*(?:→|->|=>)\s*(?P<text>.+?)\s*$")


def _extract_numbered_steps(content: List[str], start_lineno: int, path: str) -> List[FlowStep]:
    steps: List[FlowStep] = []
    for offset, line in enumerate(content):
        m = _NUMBERED_STEP_RE.match(line)
        if m:
            steps.append(FlowStep(index=len(steps), text=m.group("text").strip(),
                                   evidence=f"{path}:{start_lineno + offset}"))
    return steps if len(steps) >= 2 else []


def _extract_arrow_chain(content: List[str], start_lineno: int, path: str) -> List[FlowStep]:
    """Two real arrow-chain shapes, checked against every non-blank line in
    document order -- NOT only the block's first non-blank line, so a plain
    introductory prose line preceding the real chain (e.g. "Example generic
    form:") is skipped rather than mistaken for the chain's own seed."""
    non_blank = [(offset, line) for offset, line in enumerate(content) if line.strip()]
    if not non_blank:
        return []

    # Case A: a single line already carries 1+ arrow token with 2+ non-empty
    # segments -- a fully inline chain (e.g.
    # "Reset -> Clock/PHY readiness -> Base config"). The FIRST such line in
    # document order wins.
    for offset, line in non_blank:
        if not _ARROW_TOKEN_RE.search(line):
            continue
        segments = [seg.strip() for seg in _ARROW_TOKEN_RE.split(line) if seg.strip()]
        if len(segments) >= 2:
            return [FlowStep(index=i, text=seg, evidence=f"{path}:{start_lineno + offset}")
                    for i, seg in enumerate(segments)]

    # Case B: a plain SEED line (no arrow token of its own) immediately
    # followed by one or more arrow-prefixed CONTINUATION lines -- the
    # multi-line form section 311's own illustration uses.
    for i in range(len(non_blank) - 1):
        seed_offset, seed_line = non_blank[i]
        if _ARROW_TOKEN_RE.search(seed_line):
            continue
        _next_offset, next_line = non_blank[i + 1]
        if not _ARROW_PREFIX_RE.match(next_line):
            continue
        steps = [FlowStep(index=0, text=seed_line.strip(), evidence=f"{path}:{start_lineno + seed_offset}")]
        j = i + 1
        while j < len(non_blank):
            offset, line = non_blank[j]
            m = _ARROW_PREFIX_RE.match(line)
            if not m:
                break
            steps.append(FlowStep(index=len(steps), text=m.group("text").strip(),
                                   evidence=f"{path}:{start_lineno + offset}"))
            j += 1
        return steps if len(steps) >= 2 else []
    return []


def _extract_bulleted_steps(content: List[str], start_lineno: int, path: str) -> List[FlowStep]:
    steps: List[FlowStep] = []
    for offset, line in enumerate(content):
        m = _BULLET_STEP_RE.match(line)
        if m:
            steps.append(FlowStep(index=len(steps), text=m.group("text").strip(),
                                   evidence=f"{path}:{start_lineno + offset}"))
    return steps if len(steps) >= 1 else []


def extract_step_chain(content: List[str], start_lineno: int, path: str) -> List[FlowStep]:
    """Try, in order: a numbered list (>=2 items), an arrow chain (inline or
    multi-line, >=2 items), then a bulleted list (>=1 item). Returns the
    first recognized shape's steps, or `[]` if none of the three shapes is
    present -- an honest "nothing recognizable here", never a guess."""
    steps = _extract_numbered_steps(content, start_lineno, path)
    if steps:
        return steps
    steps = _extract_arrow_chain(content, start_lineno, path)
    if steps:
        return steps
    return _extract_bulleted_steps(content, start_lineno, path)


# ---------------------------------------------------------------------------
# Phase classification -- per-flow-context keyword tables, reusing
# `programming_sequence_ir.PHASE_*` tokens directly (never re-declared).
# ---------------------------------------------------------------------------
_RESET_KW = re.compile(r"\breset\b", re.IGNORECASE)
_CLOCK_PHY_READY_KW = re.compile(
    r"\b(?:clock|phy)\b.{0,40}\b(?:ready|readiness|lock|stable)\b"
    r"|\b(?:ready|readiness|lock|stable)\b.{0,40}\b(?:clock|phy)\b", re.IGNORECASE)
_CONFIG_KW = re.compile(r"\bconfig", re.IGNORECASE)
_SETUP_KW = re.compile(r"\bsetup\b|\bset\s*up\b", re.IGNORECASE)
_BUFFER_DMA_KW = re.compile(r"\b(?:buffer|dma)\b", re.IGNORECASE)
_INTERRUPT_KW = re.compile(r"\binterrupt\b|\birq\b", re.IGNORECASE)
_ENABLE_KW = re.compile(r"\benable\b", re.IGNORECASE)
_WAIT_KW = re.compile(r"\bwait\b", re.IGNORECASE)
_START_RUN_KW = re.compile(r"\bstart\b|\bresume\b|\bbegin\b", re.IGNORECASE)
_STOP_KW = re.compile(r"\bstop\b|\bhalt\b", re.IGNORECASE)
_IDLE_KW = re.compile(r"\bidle\b", re.IGNORECASE)
_DISABLE_KW = re.compile(r"\bdisable\b", re.IGNORECASE)
_CLEAR_KW = re.compile(r"\bclear\b", re.IGNORECASE)
_POWER_CLOCK_TRANSITION_KW = re.compile(
    r"\b(?:power|clock)\b.{0,30}\b(?:transition|gate|gating|off|down)\b"
    r"|\b(?:transition|gate|gating|off|down)\b.{0,30}\b(?:power|clock)\b", re.IGNORECASE)
_VERIFY_KW = re.compile(r"\bverify\b|\bcheck\b|\bconfirm\b", re.IGNORECASE)
_REINIT_KW = re.compile(r"\bre-?init\w*\b|\brestart\b", re.IGNORECASE)


def classify_step_phase(text: str, flow_kind: str) -> Optional[str]:
    """Classify one step's text into a `programming_sequence_ir` canonical
    phase, from real, cited keyword patterns -- never from step position
    alone. Returns `None` (UNCLASSIFIED) when nothing matches. The keyword
    priority and mapping are deliberately DIFFERENT per `flow_kind`: the
    identical word "reset" means the INIT-phase reset-release precondition
    at the start of an initialization flow, and the RESET-phase teardown
    action at the end of a shutdown flow -- real, disclosed, structural
    evidence (which heading the step came from), never an unexplained
    inconsistency."""
    if flow_kind == FLOW_INITIALIZATION:
        if _RESET_KW.search(text) and not _CLOCK_PHY_READY_KW.search(text):
            return PHASE_INIT
        if _CLOCK_PHY_READY_KW.search(text):
            return PHASE_INIT
        if _CONFIG_KW.search(text):
            return PHASE_CONFIGURE
        if _SETUP_KW.search(text) and (_BUFFER_DMA_KW.search(text) or _INTERRUPT_KW.search(text)):
            return PHASE_CONFIGURE
        if _ENABLE_KW.search(text):
            return PHASE_ENABLE
        if _WAIT_KW.search(text):
            return PHASE_WAIT
        if _START_RUN_KW.search(text):
            return PHASE_RUN
        return None

    if flow_kind == FLOW_SHUTDOWN:
        if _STOP_KW.search(text):
            return PHASE_DISABLE
        if _WAIT_KW.search(text) or _IDLE_KW.search(text):
            return PHASE_WAIT
        if _DISABLE_KW.search(text):
            return PHASE_DISABLE
        if _CLEAR_KW.search(text):
            return PHASE_DISABLE
        if _POWER_CLOCK_TRANSITION_KW.search(text):
            return PHASE_DISABLE
        if _RESET_KW.search(text):
            return PHASE_RESET
        return None

    # FLOW_RECOVERY: a recovery ACTION step is classified against the same
    # widened vocabulary a recovery procedure realistically uses -- checked
    # most-specific first so e.g. "reinitialize" outranks a bare "enable".
    if flow_kind == FLOW_RECOVERY:
        if _REINIT_KW.search(text):
            return PHASE_INIT
        if _RESET_KW.search(text):
            return PHASE_RESET
        if _VERIFY_KW.search(text):
            return PHASE_VERIFY
        if _DISABLE_KW.search(text) or _STOP_KW.search(text):
            return PHASE_DISABLE
        if _CONFIG_KW.search(text):
            return PHASE_CONFIGURE
        if _ENABLE_KW.search(text):
            return PHASE_ENABLE
        if _START_RUN_KW.search(text):
            return PHASE_RUN
        if _WAIT_KW.search(text):
            return PHASE_WAIT
        return None

    raise DesignLifecycleFlowError(f"unrecognized flow_kind {flow_kind!r}, must be one of {FLOW_KINDS}")


def classify_steps(steps: Sequence[FlowStep], flow_kind: str) -> List[FlowStep]:
    """Return a NEW list of `FlowStep`s with `.phase` populated via
    `classify_step_phase()` -- the input steps (as produced by
    `extract_step_chain()`) are never mutated in place."""
    out: List[FlowStep] = []
    for s in steps:
        out.append(FlowStep(index=s.index, text=s.text, evidence=s.evidence,
                             phase=classify_step_phase(s.text, flow_kind)))
    return out


# ---------------------------------------------------------------------------
# Phase-order check -- reuses `PHASE_RANK` (imported from
# `programming_sequence_ir.py`) directly. See the module docstring's "WHY NOT
# A DIRECT CALL INTO validate_step_ordering()" note for why this is a small,
# local, register-free monotonicity check rather than a call into that
# function.
# ---------------------------------------------------------------------------
def check_phase_order(steps: Sequence[FlowStep]) -> dict:
    """Non-decreasing PHASE_RANK check over `steps`' own classified phases,
    in document order. An UNCLASSIFIED step (`phase is None`) is skipped for
    this check -- it contributes no rank claim either way, since it was
    never mapped onto the canonical vocabulary at all; it is still visible
    in the caller's own `steps` list with `phase_status: "UNCLASSIFIED"`.
    Fewer than two classified steps is `PHASE_ORDER_NOT_APPLICABLE` -- there
    is nothing to order."""
    classified = [s for s in steps if s.phase is not None]
    if len(classified) < 2:
        return {"status": PHASE_ORDER_NOT_APPLICABLE, "violations": [],
                "reason": f"only {len(classified)} classified step(s) -- nothing to order"}

    violations: List[dict] = []
    highest_rank = -1
    highest_phase: Optional[str] = None
    highest_step_index: Optional[int] = None
    for s in classified:
        rank = PHASE_RANK[s.phase]
        if rank < highest_rank:
            violations.append({
                "step_index": s.index, "phase": s.phase, "rank": rank,
                "after_step_index": highest_step_index, "after_phase": highest_phase,
                "after_rank": highest_rank,
                "message": (f"step {s.index} is phase {s.phase!r} (rank {rank}), which comes "
                            f"after phase {highest_phase!r} (rank {highest_rank}) already seen "
                            f"at step {highest_step_index} -- canonical order is {CANONICAL_PHASES}"),
            })
        else:
            highest_rank = rank
            highest_phase = s.phase
            highest_step_index = s.index

    status = PHASE_ORDER_VIOLATION if violations else PHASE_ORDER_VALID
    return {"status": status, "violations": violations, "reason": None}


def to_programming_sequence_ir(name: str, steps: Sequence[FlowStep]) -> ProgrammingSequenceIR:
    """Build a REAL `programming_sequence_ir.ProgrammingSequenceIR` out of
    `steps` -- the imported dataclass types, never re-declared here -- so a
    caller holding real register facts for this flow (once a step is tied to
    a concrete register) can pass the result straight into
    `programming_sequence_ir.validate_step_ordering()` for the fuller
    access-type/`depends_on` check. Every step is emitted with
    `action=ACTION_WAIT` and `register=None`: a prose lifecycle step names no
    concrete register by construction, and `ACTION_WAIT` is the one action
    `programming_sequence_ir`'s own schema allows without one -- this is
    never presented as "these are wait/poll steps"; `description` carries
    the real extracted text and `phase` carries this module's own real
    classification (an UNCLASSIFIED step is emitted with the literal phase
    string `"UNCLASSIFIED"`, which is NOT a member of `PHASE_RANK` and so
    correctly reports as an unknown-phase finding rather than being silently
    dropped or coerced onto a real phase)."""
    out_steps = [
        ProgrammingSequenceStep(
            index=i, phase=(s.phase or _UNCLASSIFIED_PHASE_TOKEN), action=ACTION_WAIT,
            register=None, value=None, description=s.text,
        )
        for i, s in enumerate(steps)
    ]
    return ProgrammingSequenceIR(name=name, steps=out_steps)


# ---------------------------------------------------------------------------
# Recovery: per-trigger extraction. Two real shapes are recognized: (a) a
# trigger's own sub-heading inside the recovery section (recurses through
# `_find_flow_sections()`-style heading detection restricted to the
# recovery block's own content), and (b) an inline "<Trigger phrase>:
# <action text>" line. Both require the trigger's real, cited pattern
# (`TRIGGER_PATTERNS`) to match; a trigger this module has no pattern for
# contributes nothing rather than a guess.
# ---------------------------------------------------------------------------
def _extract_recovery_trigger_subsections(content: List[str], start_lineno: int) -> Dict[str, List[Tuple[int, List[str]]]]:
    """Mirrors `_find_flow_sections()`'s heading-split discipline, scoped to
    ONE recovery block's own content lines, keyed by real trigger name
    rather than by `FLOW_KINDS`."""
    sections: Dict[str, List[Tuple[int, List[str]]]] = {t: [] for t in RECOVERY_TRIGGERS}
    current_trigger: Optional[str] = None
    current_start: Optional[int] = None
    current_content: List[str] = []

    def _flush() -> None:
        if current_trigger is not None:
            sections[current_trigger].append((current_start, current_content[:]))

    for offset, line in enumerate(content):
        lineno = start_lineno + offset
        title = _heading_title(line)
        if title is not None:
            _flush()
            current_trigger = None
            for trig, pattern in TRIGGER_PATTERNS.items():
                if pattern.search(title):
                    current_trigger = trig
                    break
            current_start = lineno
            current_content = []
            continue
        if current_trigger is not None:
            current_content.append("" if _FENCE_LINE_RE.match(line) else line)
    _flush()
    return sections


_INLINE_TRIGGER_LINE_RE = re.compile(r"^\s*(?P<label>[^:]{2,60}):\s*(?P<rest>.+?)\s*$")


def _extract_inline_trigger_lines(content: List[str], start_lineno: int, path: str) -> Dict[str, List[FlowStep]]:
    """A single line of the form `<Trigger phrase>: <action text>` -- the
    action text is then itself parsed as an arrow chain if it contains
    arrow tokens, else treated as one single step."""
    out: Dict[str, List[FlowStep]] = {t: [] for t in RECOVERY_TRIGGERS}
    for offset, line in enumerate(content):
        m = _INLINE_TRIGGER_LINE_RE.match(line)
        if not m:
            continue
        label = m.group("label")
        rest = m.group("rest")
        matched_trigger = None
        for trig, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(label):
                matched_trigger = trig
                break
        if matched_trigger is None or out[matched_trigger]:
            continue
        lineno = start_lineno + offset
        segments = [seg.strip() for seg in _ARROW_TOKEN_RE.split(rest) if seg.strip()]
        if not segments:
            continue
        out[matched_trigger] = [
            FlowStep(index=i, text=seg, evidence=f"{path}:{lineno}") for i, seg in enumerate(segments)
        ]
    return out


def _strip_foreign_inline_trigger_lines(block: List[str], own_trigger: str) -> List[str]:
    """A trigger's own SUB-HEADING block can legitimately contain a
    different, unrelated trigger's own inline `<Trigger>: <action>`
    restatement nested in it with no sub-heading of its own to separate the
    two (real docs are not always perfectly hierarchical). Such a line is
    blanked (never dropped -- see `_FENCE_LINE_RE`'s own reasoning) before
    `own_trigger`'s step chain is extracted, so it can never be mistaken for
    part of `own_trigger`'s own chain; `_extract_inline_trigger_lines()`
    still reads the ORIGINAL, unfiltered content separately, so the foreign
    trigger's own real evidence is still captured under its own name."""
    out: List[str] = []
    for line in block:
        m = _INLINE_TRIGGER_LINE_RE.match(line)
        if m:
            label = m.group("label")
            for trig, pattern in TRIGGER_PATTERNS.items():
                if trig != own_trigger and pattern.search(label):
                    line = ""
                    break
        out.append(line)
    return out


def extract_recovery_triggers(content: List[str], start_lineno: int, path: str) -> Dict[str, dict]:
    """For every one of `RECOVERY_TRIGGERS`, extract its documented recovery
    action step chain (sub-heading form preferred over the inline form when
    both are present for the same trigger), classify each step's phase in
    the `FLOW_RECOVERY` context, and run `check_phase_order()` over that
    trigger's own steps (independent of every other trigger -- different
    triggers are alternative, not sequential, flows). A trigger with no real
    evidence anywhere in `content` is honestly `NOT_AVAILABLE`."""
    subsections = _extract_recovery_trigger_subsections(content, start_lineno)
    inline = _extract_inline_trigger_lines(content, start_lineno, path)

    result: Dict[str, dict] = {}
    for trig in RECOVERY_TRIGGERS:
        steps: List[FlowStep] = []
        for heading_lineno, block in subsections[trig]:
            filtered_block = _strip_foreign_inline_trigger_lines(block, trig)
            steps = extract_step_chain(filtered_block, heading_lineno + 1, path)
            if steps:
                break
        if not steps:
            steps = inline[trig]

        if not steps:
            result[trig] = {
                "status": STATUS_NOT_AVAILABLE, "reason":
                    f"no documented recovery action for trigger {trig!r} was found in the "
                    "supplied sources -- neither a sub-heading naming this trigger nor an inline "
                    "'<trigger>: <action>' line was recognized",
                "steps": [], "phase_order_check": {
                    "status": PHASE_ORDER_NOT_APPLICABLE, "violations": [],
                    "reason": "no steps to order"},
            }
            continue

        classified = classify_steps(steps, FLOW_RECOVERY)
        result[trig] = {
            "status": STATUS_LOADED, "reason": None,
            "steps": [s.to_dict() for s in classified],
            "phase_order_check": check_phase_order(classified),
        }
    return result


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------
def classify_source(path) -> str:
    suffix = Path(path).suffix.lower()
    return "text" if suffix in TEXT_SUFFIXES else "unknown"


def _extract_single_flow(sections: Dict[str, List[Tuple[int, List[str]]]], flow_kind: str, path: str) -> dict:
    blocks = sections[flow_kind]
    if not blocks:
        return {
            "status": STATUS_NOT_AVAILABLE, "reason":
                f"no heading naming a {flow_kind} flow was found in the supplied sources",
            "steps": [], "phase_order_check": {
                "status": PHASE_ORDER_NOT_APPLICABLE, "violations": [], "reason": "no heading found"},
        }
    steps: List[FlowStep] = []
    for heading_lineno, block in blocks:
        steps = extract_step_chain(block, heading_lineno + 1, path)
        if steps:
            break
    if not steps:
        return {
            "status": STATUS_NOT_AVAILABLE, "reason":
                f"a {flow_kind} heading was found but no recognizable step chain (a numbered "
                "list, a bulleted list, or an arrow chain) was found beneath it",
            "steps": [], "phase_order_check": {
                "status": PHASE_ORDER_NOT_APPLICABLE, "violations": [],
                "reason": "no step chain found"},
        }
    classified = classify_steps(steps, flow_kind)
    return {
        "status": STATUS_LOADED, "reason": None,
        "steps": [s.to_dict() for s in classified],
        "phase_order_check": check_phase_order(classified),
    }


def extract_design_lifecycle_flow(source_paths) -> dict:
    """Extract the initialization/shutdown/recovery lifecycle flows from real
    spec/programming-guide TEXT files a caller supplies. `source_paths` is a
    list of str/Path; every file is read (never fabricated), and a
    missing/unreadable file is recorded as an honest per-source failure
    rather than silently skipped or raised past the caller."""
    source_paths = list(source_paths or [])
    read_sources: List[str] = []
    missing_sources: List[str] = []
    unrecognized_sources: List[str] = []

    init_result = {"status": STATUS_NOT_AVAILABLE, "reason": "no sources supplied", "steps": [],
                    "phase_order_check": {"status": PHASE_ORDER_NOT_APPLICABLE, "violations": [],
                                           "reason": "no sources supplied"}}
    shutdown_result = dict(init_result)
    recovery_triggers = {t: {"status": STATUS_NOT_AVAILABLE, "reason": "no sources supplied",
                              "steps": [], "phase_order_check":
                                  {"status": PHASE_ORDER_NOT_APPLICABLE, "violations": [],
                                   "reason": "no sources supplied"}}
                         for t in RECOVERY_TRIGGERS}
    any_recovery_heading = False

    for raw_path in source_paths:
        p = Path(raw_path)
        if not p.is_file():
            missing_sources.append(str(raw_path))
            continue
        kind = classify_source(p)
        if kind == "unknown":
            unrecognized_sources.append(str(raw_path))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            missing_sources.append(f"{raw_path} ({exc})")
            continue
        lines = text.splitlines()
        path_str = str(raw_path)
        read_sources.append(path_str)

        sections = _find_flow_sections(lines)

        # A real per-file result -- LOADED or a specific NOT_AVAILABLE
        # (a heading was/wasn't found, a step chain was/wasn't recognized)
        # -- always REPLACES the generic "no sources supplied" placeholder
        # above; once a real LOADED result has been found, a later file's
        # weaker NOT_AVAILABLE result never downgrades it.
        this_init = _extract_single_flow(sections, FLOW_INITIALIZATION, path_str)
        if init_result["status"] != STATUS_LOADED:
            init_result = this_init
        this_shutdown = _extract_single_flow(sections, FLOW_SHUTDOWN, path_str)
        if shutdown_result["status"] != STATUS_LOADED:
            shutdown_result = this_shutdown

        if sections[FLOW_RECOVERY]:
            any_recovery_heading = True
            for heading_lineno, block in sections[FLOW_RECOVERY]:
                this_triggers = extract_recovery_triggers(block, heading_lineno + 1, path_str)
                for trig, entry in this_triggers.items():
                    if recovery_triggers[trig]["status"] != STATUS_LOADED:
                        recovery_triggers[trig] = entry

    if not any_recovery_heading:
        for trig in RECOVERY_TRIGGERS:
            if recovery_triggers[trig]["status"] != STATUS_LOADED:
                recovery_triggers[trig] = {
                    "status": STATUS_NOT_AVAILABLE,
                    "reason": "no heading naming a recovery flow was found in the supplied sources",
                    "steps": [], "phase_order_check": {
                        "status": PHASE_ORDER_NOT_APPLICABLE, "violations": [], "reason": "no heading found"},
                }

    if not source_paths:
        top_status, top_reason = STATUS_NOT_AVAILABLE, "no source files were supplied"
    elif not read_sources:
        top_status = STATUS_NOT_AVAILABLE
        top_reason = f"none of the {len(source_paths)} supplied source path(s) could be read: {missing_sources}"
    else:
        any_loaded = (init_result["status"] == STATUS_LOADED
                      or shutdown_result["status"] == STATUS_LOADED
                      or any(v["status"] == STATUS_LOADED for v in recovery_triggers.values()))
        if any_loaded:
            top_status, top_reason = STATUS_LOADED, None
        else:
            top_status = STATUS_NOT_AVAILABLE
            top_reason = ("supplied sources were read but none of the initialization, shutdown, "
                          "or recovery flows could be extracted from them")

    recovery_status = STATUS_LOADED if any(v["status"] == STATUS_LOADED for v in recovery_triggers.values()) \
        else STATUS_NOT_AVAILABLE
    recovery_reason = None if recovery_status == STATUS_LOADED else \
        "no heading naming a recovery flow was found, or no recognized trigger evidence was found beneath it"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": top_status,
        "source": {"kind": "design_lifecycle_flow_source_text", "paths": read_sources,
                   "missing": missing_sources, "unrecognized": unrecognized_sources},
        "reason": top_reason,
        "initialization_flow": init_result,
        "shutdown_flow": shutdown_result,
        "recovery_flow": {"status": recovery_status, "reason": recovery_reason,
                          "triggers": recovery_triggers},
    }


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's status/phase-order vocabulary must share no token with
    `models.Status` -- the same guarantee several sibling extraction/analysis
    modules already hold for their own vocabularies."""
    from .models import Status

    verdicts = {s.value for s in Status}
    own = {STATUS_LOADED, STATUS_NOT_AVAILABLE, PHASE_STATUS_CLASSIFIED, PHASE_STATUS_UNCLASSIFIED,
           PHASE_ORDER_VALID, PHASE_ORDER_VIOLATION, PHASE_ORDER_NOT_APPLICABLE}
    overlap = own & verdicts
    if overlap:
        raise AssertionError(
            f"design_lifecycle_flow vocabulary collides with models.Status: {sorted(overlap)}")


assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Ad hoc entry point -- same shared convention as
# `interrupt_dma_clock_reset_extraction.py`. Not wired into cli.py (per this
# batch's file-safety scope); the integrator may add a
# `dv-harness design-lifecycle-flow --sources <f> [<f> ...] [--json]` verb
# calling `execute_verb()` below.
# ---------------------------------------------------------------------------
def execute_verb(argv: list) -> int:
    import sys as _sys

    if not argv or argv[0] not in ("extract",):
        print("usage: design_lifecycle_flow extract --sources <f> [<f> ...] [--json]",
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
    report = extract_design_lifecycle_flow(sources)
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}" + (f" ({report['reason']})" if report["reason"] else ""))
        for name, key in (("initialization", "initialization_flow"), ("shutdown", "shutdown_flow")):
            block = report[key]
            print(f"  {name} flow: {block['status']} ({len(block['steps'])} step(s)) "
                  f"phase_order={block['phase_order_check']['status']}")
        rec = report["recovery_flow"]
        print(f"  recovery flow: {rec['status']}")
        for trig in RECOVERY_TRIGGERS:
            entry = rec["triggers"][trig]
            print(f"    {trig}: {entry['status']} ({len(entry['steps'])} step(s))")
    return 0 if report["status"] == STATUS_LOADED else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(execute_verb(sys.argv[1:]))
