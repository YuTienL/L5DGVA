"""DE command.txt style-and-registry learning (gap closure, 2026-09-06).

This module answers a question `reference_pattern_audit.py`'s SYS-7 layer
does not ask: not "what does this statement DO" (that is SYS-7's job, and
this module reuses `extract_command_statements`/`classify_wait` rather than
re-deriving statement classification -- see REUSE OVER REINVENT below), but
two new questions:

1. **`CommandStyleIR`** -- what FORMATTING convention does this specific
   real `command.txt`-style file actually use (separator convention,
   argument format, comment format, phase markers, ordering rules)? This is
   pattern-DETECTED from the real file's own text every time this module
   runs -- never assumed from any other project's convention, and never
   hardcoded to the USB-shaped macro idiom SYS-7 was grounded against. A
   file with no evidence for a given style facet reports that facet
   `NOT_AVAILABLE`/`NOT_FOUND` with the search actually performed, exactly
   as `analyze_command_file`'s aspects do for a missing SYS-7 facet.

2. **`DECommandRegistryIR`** -- one entry per DISTINCT command found in the
   file (grouped by (kind, name) so two different macros never collapse
   into one entry, and so a genuinely unclassifiable line never collapses
   with another unclassifiable line unless its raw text is identical),
   each carrying a best-effort `semantic_operation` label, its `arguments`,
   a `branch_owner` GUESS in {GLOBAL, DUT, FW, VIP, UNKNOWN} (the four real
   layers named in `.claude/skills/CORE/branch-mapper/SKILL.md`'s
   "Initialization Task Hierarchy" -- `block`=GLOBAL, `branch_a*`=DUT,
   `branch_fw`=FW, `branch_b*`=VIP), and a `status` in {KNOWN, PARTIAL,
   AMBIGUOUS, UNSUPPORTED, DEPRECATED, UNKNOWN}.

EVIDENCE TRUTH RULE, applied here specifically: a `branch_owner` is always a
GUESS (the module's own docstring and every entry's `basis` field say so),
and its confidence is exactly what `status` communicates -- KNOWN only when
a real, cited textual feature of the statement settles it (e.g. a
`HOSTWRITE*`/`CPUWRITE*` prefix, per `reference_pattern_audit`'s own real
HOST-vs-DUT naming convention), AMBIGUOUS/PARTIAL when the guess is a
genuine guess, and UNKNOWN (never a confident-sounding default) when the
parser could not classify the line into any known DE command shape at all
-- that case's `command_name`/`raw_text` is the literal source text, cited
verbatim, never paraphrased into invented semantics.

REUSE OVER REINVENT: statement extraction and classification is entirely
`reference_pattern_audit.extract_command_statements` (its `CommandStatement`,
`kind`/`category` vocabulary, `classify_wait`, and its
`INTERRUPT_NAME_TOKENS`/`INIT_NAME_TOKENS`/`MEMORY_MODEL_NAME_TOKENS` token
sets). That module is pre-existing, tested, dated 2026-09-03/04 -- it is not
one of the concurrently-running batch's new modules this task is scoped
away from, and importing its PUBLIC surface (not its underscore-prefixed
helpers) is exactly the reuse this project's house rule requires. This
module owns only what SYS-7 does not: file-level FORMATTING-style detection,
and the per-distinct-command REGISTRY view with branch-ownership guesses.

Grounded example fixture: this module's own test builds a small synthetic
command.txt-style file inline (never real project content, matching
`test_reference_pattern_audit.py`'s own synthetic-fixture precedent) that
exercises a KNOWN case (an unambiguous HOST-context register write), an
AMBIGUOUS case (a plain, non-interrupt signal wait), and an UNKNOWN case (a
line matching no recognized DE command shape at all).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from dv_harness.reference_pattern_audit import (
    CommandStatement,
    C_INITIALIZATION,
    C_MEMORY_BACKDOOR,
    INTERRUPT_NAME_TOKENS,
    K_ASSIGNMENT,
    K_BACKDOOR_ASSIGN,
    K_BLOCK_BEGIN,
    K_BLOCK_END,
    K_CONDITIONAL,
    K_DECLARATION,
    K_DELAY,
    K_DIRECTIVE,
    K_DISABLE,
    K_DISPLAY,
    K_ERROR_REPORT,
    K_EVENT_WAIT,
    K_FORCE,
    K_FORK,
    K_JOIN,
    K_LOOP,
    K_MACRO_CALL,
    K_MEMORY_LOAD,
    K_MODEL_TASK_CALL,
    K_PROCESS,
    K_REGISTER_READ,
    K_REGISTER_WRITE,
    K_RELEASE,
    K_TERMINATION,
    K_UNCLASSIFIED,
    K_WAIT_CONDITION,
    extract_command_statements,
)

# --- branch-owner / status vocabulary ---------------------------------------

BRANCH_OWNER_GLOBAL = "GLOBAL"
BRANCH_OWNER_DUT = "DUT"
BRANCH_OWNER_FW = "FW"
BRANCH_OWNER_VIP = "VIP"
BRANCH_OWNER_UNKNOWN = "UNKNOWN"
BRANCH_OWNERS: tuple = (BRANCH_OWNER_GLOBAL, BRANCH_OWNER_DUT, BRANCH_OWNER_FW,
                        BRANCH_OWNER_VIP, BRANCH_OWNER_UNKNOWN)

STATUS_KNOWN = "KNOWN"
STATUS_PARTIAL = "PARTIAL"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_DEPRECATED = "DEPRECATED"
STATUS_UNKNOWN = "UNKNOWN"
STATUSES: tuple = (STATUS_KNOWN, STATUS_PARTIAL, STATUS_AMBIGUOUS,
                   STATUS_UNSUPPORTED, STATUS_DEPRECATED, STATUS_UNKNOWN)

# Name-token evidence for a MODEL_TASK_CALL that is neither an
# initialization call nor a memory-backdoor call (both already resolved by
# reference_pattern_audit's own category). This is the ONLY extra token set
# this module adds on top of reference_pattern_audit's real ones, and it is
# named-evidence exactly like INTERRUPT_NAME_TOKENS is -- a match is real
# evidence, not proof, and is cited via `matched_tokens`.
VIP_TASK_NAME_TOKENS: tuple = ("seq", "sequence", "vip", "xfer", "scenario")

# Comment tokens that flag a command DEPRECATED. Real evidence lives in the
# statement's OWN comment text (never inferred from the command name alone).
DEPRECATED_COMMENT_TOKENS: tuple = (
    "deprecated", "obsolete", "do not use", "no longer used", "legacy",
)

_HOST_ROOT_TOKENS = ("host",)
_DUT_ROOT_TOKENS = ("dut", "dev", "cpu", "chip")


def _matched(text: str, tokens) -> list:
    lowered = (text or "").lower()
    return [t for t in tokens if t in lowered]


# --- per-statement semantic_operation / branch_owner / status ---------------

@dataclass
class DECommandClassification:
    semantic_operation: str
    branch_owner: str
    status: str
    basis: str


def _classify_register_access(kind: str, stmt: CommandStatement) -> DECommandClassification:
    verb = "write" if kind == K_REGISTER_WRITE else "read"
    if stmt.context == "HOST":
        return DECommandClassification(
            semantic_operation=f"register {verb} (host-side)",
            branch_owner=BRANCH_OWNER_VIP, status=STATUS_KNOWN,
            basis=(f"macro prefix classified HOST by "
                   f"reference_pattern_audit._classify_context; host-side "
                   f"register access is driven through the VIP-testing "
                   f"branch (branch_b*) per branch-mapper's real-world "
                   f"mapping"))
    if stmt.context == "DUT":
        return DECommandClassification(
            semantic_operation=f"register {verb} (DUT-side)",
            branch_owner=BRANCH_OWNER_DUT, status=STATUS_KNOWN,
            basis=(f"macro prefix classified DUT by "
                   f"reference_pattern_audit._classify_context; DUT-side "
                   f"register access belongs to the DUT+PHY bring-up "
                   f"branch (branch_a*)"))
    return DECommandClassification(
        semantic_operation=f"register {verb} (context undetermined)",
        branch_owner=BRANCH_OWNER_UNKNOWN, status=STATUS_AMBIGUOUS,
        basis=(f"macro prefix '{stmt.name}' matched neither the HOST nor "
               f"the DUT naming convention; real evidence is insufficient "
               f"to guess a branch owner"))


def _classify_model_task(stmt: CommandStatement) -> DECommandClassification:
    if stmt.category == C_INITIALIZATION:
        return DECommandClassification(
            semantic_operation="global/model initialization call",
            branch_owner=BRANCH_OWNER_GLOBAL, status=STATUS_KNOWN,
            basis=(f"model task '{stmt.name}' matched an INIT_NAME_TOKENS "
                   f"token (reference_pattern_audit category "
                   f"INITIALIZATION); this project's `block` layer is the "
                   f"single non-per-port SoC-global init task"))
    if stmt.category == C_MEMORY_BACKDOOR:
        return DECommandClassification(
            semantic_operation="memory-model backdoor load",
            branch_owner=BRANCH_OWNER_DUT, status=STATUS_KNOWN,
            basis=(f"model task '{stmt.name}' matched a "
                   f"MEMORY_MODEL_NAME_TOKENS token; a memory model backs "
                   f"DUT-visible memory content"))
    tokens = _matched(stmt.name, VIP_TASK_NAME_TOKENS)
    if tokens:
        return DECommandClassification(
            semantic_operation="VIP sequence start (name-evidence)",
            branch_owner=BRANCH_OWNER_VIP, status=STATUS_PARTIAL,
            basis=(f"model task '{stmt.name}' matched VIP-task name "
                   f"token(s) {tokens}; this is name evidence, not proof, "
                   f"of a VIP-sequence dispatch"))
    return DECommandClassification(
        semantic_operation="model/VIP task call (operation undetermined)",
        branch_owner=BRANCH_OWNER_UNKNOWN, status=STATUS_AMBIGUOUS,
        basis=(f"model task '{stmt.name}' matched neither an "
               f"initialization, memory-backdoor, nor VIP-task-name token "
               f"set; branch ownership cannot be confidently assigned "
               f"from the command text alone"))


def _classify_wait(kind: str, stmt: CommandStatement) -> DECommandClassification:
    condition = " ".join(stmt.arguments) or stmt.text
    tokens = _matched(condition + " " + stmt.comment, INTERRUPT_NAME_TOKENS)
    if tokens:
        return DECommandClassification(
            semantic_operation="wait for event (interrupt/status)",
            branch_owner=BRANCH_OWNER_FW, status=STATUS_KNOWN,
            basis=(f"matched interrupt-name token(s) {tokens} "
                   f"(reference_pattern_audit.INTERRUPT_NAME_TOKENS); "
                   f"branch_fw owns the ARM/WAIT/WAKE/DECODE/CLEAR event "
                   f"loop per interrupt-event-dispatch"))
    label = "wait for event" if kind == K_EVENT_WAIT else "wait for signal level"
    return DECommandClassification(
        semantic_operation=f"{label} (non-interrupt)",
        branch_owner=BRANCH_OWNER_UNKNOWN, status=STATUS_AMBIGUOUS,
        basis=("no interrupt-name token matched the wait condition or its "
               "comment; a plain wait can belong to block/branch_a or "
               "branch_fw depending on which signal it targets, and the "
               "command text does not say which"))


def _classify_hierarchy_touch(kind: str, stmt: CommandStatement) -> DECommandClassification:
    label = {K_FORCE: "force override of a hierarchy path",
              K_RELEASE: "release of a forced hierarchy path",
              K_BACKDOOR_ASSIGN: "backdoor assignment",
              K_MEMORY_LOAD: "backdoor memory load"}[kind]
    roots = " ".join(stmt.hierarchy_roots).lower()
    if any(t in roots for t in _HOST_ROOT_TOKENS):
        return DECommandClassification(
            semantic_operation=label, branch_owner=BRANCH_OWNER_VIP,
            status=STATUS_PARTIAL,
            basis=(f"hierarchy root(s) {stmt.hierarchy_roots} contain a "
                   f"HOST-side name token"))
    if any(t in roots for t in _DUT_ROOT_TOKENS):
        return DECommandClassification(
            semantic_operation=label, branch_owner=BRANCH_OWNER_DUT,
            status=STATUS_KNOWN,
            basis=(f"hierarchy root(s) {stmt.hierarchy_roots} contain a "
                   f"DUT-side name token"))
    return DECommandClassification(
        semantic_operation=label, branch_owner=BRANCH_OWNER_DUT,
        status=STATUS_PARTIAL,
        basis=("force/release/backdoor statements directly drive a "
               "hierarchy path; default guess is DUT-side per "
               "pattern-architecture's block/branch_a DUT+PHY role, but no "
               "HOST/DUT name token was found in the hierarchy root to "
               "confirm it"))


def _classify_statement(stmt: CommandStatement) -> DECommandClassification:
    kind = stmt.kind
    if kind in (K_REGISTER_WRITE, K_REGISTER_READ):
        return _classify_register_access(kind, stmt)
    if kind == K_MODEL_TASK_CALL:
        return _classify_model_task(stmt)
    if kind in (K_WAIT_CONDITION, K_EVENT_WAIT):
        return _classify_wait(kind, stmt)
    if kind == K_DELAY:
        return DECommandClassification(
            semantic_operation="fixed delay", branch_owner=BRANCH_OWNER_UNKNOWN,
            status=STATUS_AMBIGUOUS,
            basis="a bare delay carries no signal/register evidence "
                  "indicating which branch owns it")
    if kind in (K_FORCE, K_RELEASE, K_BACKDOOR_ASSIGN, K_MEMORY_LOAD):
        return _classify_hierarchy_touch(kind, stmt)
    if kind in (K_DISPLAY, K_ERROR_REPORT, K_TERMINATION):
        label = {K_DISPLAY: "observation/logging", K_ERROR_REPORT: "error report",
                 K_TERMINATION: "pattern termination"}[kind]
        return DECommandClassification(
            semantic_operation=label, branch_owner=BRANCH_OWNER_GLOBAL,
            status=STATUS_KNOWN,
            basis="observation/termination statements are pattern-level "
                  "reporting owned by the verdict layer, per "
                  "pattern-architecture's block/verdict role, not any "
                  "per-port branch_a*/branch_b*")
    if kind == K_DIRECTIVE:
        return DECommandClassification(
            semantic_operation="preprocessor directive", branch_owner=BRANCH_OWNER_GLOBAL,
            status=STATUS_KNOWN,
            basis="preprocessor directives are file-structural, attributed "
                  "to the GLOBAL/file-composition layer")
    if kind in (K_LOOP, K_CONDITIONAL, K_FORK, K_JOIN, K_BLOCK_BEGIN,
                K_BLOCK_END, K_PROCESS, K_DISABLE):
        return DECommandClassification(
            semantic_operation=f"control-flow construct ({kind})",
            branch_owner=BRANCH_OWNER_UNKNOWN, status=STATUS_PARTIAL,
            basis="control-flow keywords are structural; ownership depends "
                  "on which branch's body encloses this construct, which "
                  "is not tracked by this file-local statement pass")
    if kind == K_DECLARATION:
        return DECommandClassification(
            semantic_operation="variable/type declaration",
            branch_owner=BRANCH_OWNER_UNKNOWN, status=STATUS_PARTIAL,
            basis="declarations are structural and carry no branch-"
                  "ownership evidence themselves")
    if kind == K_ASSIGNMENT:
        return DECommandClassification(
            semantic_operation="plain assignment", branch_owner=BRANCH_OWNER_UNKNOWN,
            status=STATUS_AMBIGUOUS,
            basis="a plain (non-hierarchical) assignment has no signal-"
                  "hierarchy evidence indicating which branch it belongs to")
    if kind == K_MACRO_CALL:
        return DECommandClassification(
            semantic_operation="UNSUPPORTED_MACRO_OPERATION",
            branch_owner=BRANCH_OWNER_UNKNOWN, status=STATUS_UNSUPPORTED,
            basis=(f"macro invocation '{stmt.name}' was recognized as a "
                   f"bare macro-call shape but matches none of this "
                   f"registry's known semantic operations (register "
                   f"write/read, model task call)"))
    # K_UNCLASSIFIED and anything not enumerated above.
    return DECommandClassification(
        semantic_operation="UNKNOWN", branch_owner=BRANCH_OWNER_UNKNOWN,
        status=STATUS_UNKNOWN,
        basis="parser could not classify this statement into any known DE "
              "command shape; raw text cited verbatim, no semantics guessed")


def _apply_deprecated_override(cls: DECommandClassification, comment: str) -> DECommandClassification:
    tokens = _matched(comment, DEPRECATED_COMMENT_TOKENS)
    if not tokens:
        return cls
    return DECommandClassification(
        semantic_operation=cls.semantic_operation, branch_owner=cls.branch_owner,
        status=STATUS_DEPRECATED,
        basis=(cls.basis + f" | DEPRECATED: comment '{comment}' matched "
               f"token(s) {tokens}"))


# --- DECommandRegistryIR -----------------------------------------------------

@dataclass
class DECommandEntry:
    """One distinct command found in the file. Grouped by (kind, name) so
    two macros never collapse, and an UNCLASSIFIED line is grouped only with
    another line carrying the IDENTICAL raw text (its `command_name` field
    below IS that raw text -- there is no other real name to key it by)."""
    command_name: str
    kind: str
    category: str
    semantic_operation: str
    branch_owner: str
    status: str
    occurrence_count: int
    arguments: list = field(default_factory=list)
    distinct_argument_counts: list = field(default_factory=list)
    first_evidence: str = ""
    evidence: list = field(default_factory=list)
    example_text: str = ""
    raw_text: str = ""
    basis: str = ""
    mixed_classifications: bool = False


_MAX_EVIDENCE_PER_ENTRY = 20


def _entry_key(stmt: CommandStatement) -> str:
    if stmt.kind == K_UNCLASSIFIED:
        return f"UNCLASSIFIED::{stmt.text}"
    return f"{stmt.kind}::{stmt.name or '<unnamed>'}"


@dataclass
class DECommandRegistryIR:
    source_file: str
    entries: list = field(default_factory=list)
    statement_count: int = 0
    distinct_command_count: int = 0
    generated_from: str = "reference_pattern_audit.extract_command_statements"


def build_de_command_registry(path: Path, statements: Optional[list] = None) -> DECommandRegistryIR:
    """Build one `DECommandRegistryIR` for a real DE command.txt-style file.

    `statements` may be pre-computed `CommandStatement`s (e.g. reused from a
    caller that already ran `extract_command_statements`); when omitted,
    this function calls it itself. Read-only, exactly like the module it
    reuses.
    """
    path = Path(path)
    if statements is None:
        statements = extract_command_statements(path)

    # `cls0` (per group) is always the RAW classification (before any
    # DEPRECATED override) of the group's first occurrence -- mixed-
    # classification detection compares raw classifications across
    # occurrences, so a later occurrence's comment happening to say
    # "deprecated" never gets confused with that occurrence's classifier
    # disagreeing with the first one. Deprecation is tracked separately and
    # takes priority over the mixed-classification AMBIGUOUS downgrade when
    # the final status is decided below -- a command flagged deprecated by
    # even one real, cited comment should read DEPRECATED, not merely
    # AMBIGUOUS because its occurrences additionally disagreed on something
    # else.
    grouped: dict = {}
    order: list = []
    for stmt in statements:
        raw_cls = _classify_statement(stmt)
        dep_cls = _apply_deprecated_override(raw_cls, stmt.comment)
        key = _entry_key(stmt)
        if key not in grouped:
            order.append(key)
            name = (stmt.text if stmt.kind == K_UNCLASSIFIED
                    else (stmt.name or f"<{stmt.kind}>"))
            grouped[key] = {
                "stmt0": stmt, "cls0": raw_cls, "count": 0,
                "arguments": stmt.arguments, "arg_counts": set(),
                "evidence": [], "mixed": False, "name": name,
                "deprecated_evidence": [],
            }
        g = grouped[key]
        g["count"] += 1
        g["arg_counts"].add(len(stmt.arguments))
        if len(g["evidence"]) < _MAX_EVIDENCE_PER_ENTRY:
            g["evidence"].append(f"{stmt.file}:{stmt.line}")
        if (raw_cls.branch_owner != g["cls0"].branch_owner
                or raw_cls.status != g["cls0"].status):
            g["mixed"] = True
        if dep_cls.status == STATUS_DEPRECATED:
            g["deprecated_evidence"].append(f"{stmt.file}:{stmt.line}: {dep_cls.basis}")

    entries: list = []
    for key in order:
        g = grouped[key]
        stmt0, cls0 = g["stmt0"], g["cls0"]
        basis = cls0.basis
        if g["mixed"]:
            basis += " | mixed classifications across occurrences of this command"
        if g["deprecated_evidence"]:
            status = STATUS_DEPRECATED
            basis += " | " + " ; ".join(g["deprecated_evidence"])
        elif g["mixed"] and cls0.status == STATUS_KNOWN:
            status = STATUS_AMBIGUOUS
        else:
            status = cls0.status
        entries.append(DECommandEntry(
            command_name=g["name"], kind=stmt0.kind, category=stmt0.category,
            semantic_operation=cls0.semantic_operation, branch_owner=cls0.branch_owner,
            status=status, occurrence_count=g["count"], arguments=list(g["arguments"]),
            distinct_argument_counts=sorted(g["arg_counts"]),
            first_evidence=g["evidence"][0] if g["evidence"] else "",
            evidence=g["evidence"], example_text=stmt0.text, raw_text=stmt0.text,
            basis=basis, mixed_classifications=g["mixed"],
        ))

    return DECommandRegistryIR(
        source_file=str(path), entries=entries, statement_count=len(statements),
        distinct_command_count=len(entries),
    )


# --- CommandStyleIR: real formatting-convention pattern detection ----------

_LINE_COMMENT_RE = re.compile(r"//(.*)$")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_CALL_RE = re.compile(r"[\w`.]+\s*\(([^()]*)\)")
_HEX_LITERAL_RE = re.compile(r"\d+'[hH]([0-9A-Fa-f_]+)")
_PHASE_MARKER_RE = re.compile(
    r"\b(PHASE|STAGE|STEP|SECTION)\b\s*[:=]?\s*([A-Za-z0-9_]+)", re.I)
_ORDERING_TOKENS: tuple = (
    "must happen before", "must precede", "depends on", "sequence:", "order:",
    "before", "after",
)
_FORK_RE = re.compile(r"\bfork\b")
_JOIN_RE = re.compile(r"\bjoin(_any|_none)?\b")


def _strip_inline_comment(line: str) -> tuple:
    """(code_part, comment_part) for one physical line, splitting on the
    first `//`. A simple, honest heuristic (documented in the module
    docstring) -- it can mis-split a `//` embedded in a string literal, and
    that limitation is accepted rather than hidden, same as this module's
    other heuristic passes.
    """
    m = _LINE_COMMENT_RE.search(line)
    if m:
        return line[: m.start()], m.group(1)
    return line, ""


@dataclass
class CommandStyleIR:
    source_file: str
    separator_convention: dict = field(default_factory=dict)
    argument_format: dict = field(default_factory=dict)
    comment_format: dict = field(default_factory=dict)
    phase_markers: dict = field(default_factory=dict)
    ordering_rules: dict = field(default_factory=dict)


def _detect_separator_convention(lines: list) -> dict:
    code_lines = 0
    semicolon_lines = 0
    single_stmt_semicolon_lines = 0
    for raw in lines:
        code, _ = _strip_inline_comment(raw)
        code = code.strip()
        if not code:
            continue
        code_lines += 1
        if code.endswith(";"):
            semicolon_lines += 1
            if code.count(";") == 1:
                single_stmt_semicolon_lines += 1
    if semicolon_lines == 0:
        return {"dominant_terminator": None, "code_lines": code_lines,
                "semicolon_terminated_lines": 0, "one_statement_per_line_ratio": None,
                "convention": "NOT_AVAILABLE",
                "basis": "no code line ending in ';' was found"}
    ratio = single_stmt_semicolon_lines / semicolon_lines
    convention = ("SEMICOLON_TERMINATED_ONE_PER_LINE" if ratio >= 0.85
                  else "SEMICOLON_TERMINATED_MULTI_STATEMENT_OR_MULTI_LINE")
    return {"dominant_terminator": ";", "code_lines": code_lines,
            "semicolon_terminated_lines": semicolon_lines,
            "one_statement_per_line_ratio": round(ratio, 3),
            "convention": convention,
            "basis": f"{single_stmt_semicolon_lines}/{semicolon_lines} "
                     f"semicolon-terminated lines contain exactly one ';'"}


def _detect_argument_format(text_no_comments: str) -> dict:
    calls = _CALL_RE.findall(text_no_comments)
    if not calls:
        return {"call_count": 0, "comma_separated_calls": 0, "hex_literal_calls": 0,
                "underscore_grouped_hex_calls": 0, "convention": "NOT_AVAILABLE",
                "basis": "no <name>(...) call-shaped text was found"}
    comma_calls = sum(1 for a in calls if "," in a)
    hex_literals = _HEX_LITERAL_RE.findall(text_no_comments)
    underscore_grouped = sum(1 for h in hex_literals if "_" in h)
    parts = []
    parts.append("PAREN_COMMA_SEPARATED_ARGS" if comma_calls >= len(calls) * 0.5
                 else "PAREN_SINGLE_ARG_OR_MIXED")
    if hex_literals:
        parts.append("UNDERSCORE_GROUPED_HEX"
                     if underscore_grouped >= len(hex_literals) * 0.5
                     else "PLAIN_HEX")
    return {"call_count": len(calls), "comma_separated_calls": comma_calls,
            "hex_literal_calls": len(hex_literals),
            "underscore_grouped_hex_calls": underscore_grouped,
            "convention": "_".join(parts),
            "basis": f"{len(calls)} '(...)' calls, {len(hex_literals)} "
                     f"N'h-style hex literals found"}


def _detect_comment_format(lines: list, whole_text: str) -> dict:
    block_comments = _BLOCK_COMMENT_RE.findall(whole_text)
    trailing = 0
    standalone = 0
    for raw in lines:
        code, comment = _strip_inline_comment(raw)
        if not comment and not _LINE_COMMENT_RE.search(raw):
            continue
        if code.strip():
            trailing += 1
        else:
            standalone += 1
    line_comment_total = trailing + standalone
    if line_comment_total == 0 and not block_comments:
        return {"line_comments": 0, "block_comments": 0, "trailing_comments": 0,
                "standalone_comments": 0, "convention": "NOT_FOUND",
                "basis": "no // or /* */ comment was found"}
    if line_comment_total and not block_comments:
        convention = ("LINE_COMMENT_TRAILING" if trailing >= standalone
                     else "LINE_COMMENT_STANDALONE")
    elif block_comments and not line_comment_total:
        convention = "BLOCK_COMMENT"
    else:
        convention = "MIXED"
    return {"line_comments": line_comment_total, "block_comments": len(block_comments),
            "trailing_comments": trailing, "standalone_comments": standalone,
            "convention": convention,
            "basis": f"{line_comment_total} '//' line comments "
                     f"({trailing} trailing, {standalone} standalone), "
                     f"{len(block_comments)} '/* */' block comments"}


def _detect_phase_markers(lines: list) -> dict:
    found = []
    for lineno, raw in enumerate(lines, start=1):
        for m in _PHASE_MARKER_RE.finditer(raw):
            found.append({"line": lineno, "marker_kind": m.group(1).upper(),
                          "matched_text": m.group(0).strip(), "evidence": f":{lineno}"})
    if not found:
        return {"markers": [], "convention": "NOT_FOUND",
                "basis": "no PHASE/STAGE/STEP/SECTION-style marker was found"}
    return {"markers": found, "convention": "EXPLICIT_PHASE_MARKERS_FOUND",
            "basis": f"{len(found)} phase-marker token(s) found"}


def _detect_ordering_rules(lines: list) -> dict:
    fork_lines = []
    join_lines = []
    ordering_comments = []
    for lineno, raw in enumerate(lines, start=1):
        code, comment = _strip_inline_comment(raw)
        if _FORK_RE.search(code):
            fork_lines.append(lineno)
        if _JOIN_RE.search(code):
            join_lines.append(lineno)
        tokens = _matched(comment, _ORDERING_TOKENS)
        if tokens:
            ordering_comments.append({"line": lineno, "comment": comment.strip(),
                                      "matched_tokens": tokens})
    if fork_lines and join_lines:
        convention = "PARALLEL_FORK_JOIN"
    elif not fork_lines and not join_lines and not ordering_comments:
        convention = "NOT_AVAILABLE"
    else:
        convention = "SEQUENTIAL_ONLY"
    return {"fork_lines": fork_lines, "join_lines": join_lines,
            "explicit_ordering_comments": ordering_comments, "convention": convention,
            "basis": (f"{len(fork_lines)} fork / {len(join_lines)} join keyword(s), "
                      f"{len(ordering_comments)} explicit ordering-language comment(s)")}


def learn_command_style(path: Path) -> CommandStyleIR:
    """Pattern-detect a `CommandStyleIR` from one real DE command.txt-style
    file's own text. Never assumes a style; every facet is derived from
    what this specific file's text actually contains, and reports
    NOT_FOUND/NOT_AVAILABLE with the real search performed when a facet has
    no evidence.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    text_no_comments = _BLOCK_COMMENT_RE.sub(" ", text)
    text_no_comments = "\n".join(_strip_inline_comment(l)[0] for l in text_no_comments.splitlines())

    return CommandStyleIR(
        source_file=str(path),
        separator_convention=_detect_separator_convention(lines),
        argument_format=_detect_argument_format(text_no_comments),
        comment_format=_detect_comment_format(lines, text),
        phase_markers=_detect_phase_markers(lines),
        ordering_rules=_detect_ordering_rules(lines),
    )


# --- combined entry point ----------------------------------------------------

def analyze_de_command_file(path: Path) -> dict:
    """Run both learners over one real file and return a plain dict (JSON-
    friendly, matching `analyze_command_file`'s own return shape)."""
    path = Path(path)
    statements = extract_command_statements(path)
    style = learn_command_style(path)
    registry = build_de_command_registry(path, statements=statements)
    return {
        "source_file": str(path),
        "style": asdict(style),
        "registry": {
            "source_file": registry.source_file,
            "statement_count": registry.statement_count,
            "distinct_command_count": registry.distinct_command_count,
            "generated_from": registry.generated_from,
            "entries": [asdict(e) for e in registry.entries],
        },
    }


def format_de_command_analysis(analysis: dict) -> str:
    """Human-readable rendering of one `analyze_de_command_file()` result."""
    reg = analysis["registry"]
    style = analysis["style"]
    lines = [f"DE command style/registry learning: {analysis['source_file']}",
             f"  statements: {reg['statement_count']}  "
             f"distinct commands: {reg['distinct_command_count']}",
             f"  separator: {style['separator_convention']['convention']}",
             f"  argument_format: {style['argument_format']['convention']}",
             f"  comment_format: {style['comment_format']['convention']}",
             f"  phase_markers: {style['phase_markers']['convention']}",
             f"  ordering_rules: {style['ordering_rules']['convention']}"]
    by_status: dict = {}
    for e in reg["entries"]:
        by_status.setdefault(e["status"], []).append(e)
    for status in STATUSES:
        entries = by_status.get(status, [])
        if not entries:
            continue
        lines.append(f"  {status} ({len(entries)}):")
        for e in entries[:20]:
            lines.append(f"    {e['command_name']!r} -> {e['semantic_operation']} "
                         f"owner={e['branch_owner']} [{e['first_evidence']}]")
    return "\n".join(lines)
