"""dv_harness/power_intent.py -- a REAL UPF (IEEE 1801 Unified Power Format)
parser and structured power-intent extractor, plus a self-consistency
analysis of the extracted intent.

WHY THIS EXISTS, and what it deliberately does NOT claim
--------------------------------------------------------
CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md section 224 ("LOW-POWER
INTEGRATION") asks for power-state / isolation / retention / reset-interaction
/ clock-gating / wake-up handling "where the project contains power-intent
evidence", and ends with two rules this module is written to obey literally:

    If low-power infrastructure/evidence is absent:  UNSUPPORTED / UNKNOWN
    Do not fabricate a low-power verification flow.

Re-verified by grep before this file was written (not restated from an audit):
`upf`, `power_domain`, `set_isolation`, `set_retention`, `power_intent` and
`create_supply` matched NOTHING executable in `dv_harness/` or `tools/`. The
only power-shaped thing in the whole repo was the `"power_domains": []`
field that `tools/dut_architecture/build_architecture_model.py` hardcodes as
an empty list and that `.dv-harness/dut-architecture/architecture_model.schema.json`
declares with no item shape -- i.e. a field nothing has ever populated.
`tools/verification_flow/reset_clock_power_sequence_gate.py` and
`reset_power_cdc_corner_gate.py` are self-attested reset/CDC evidence-block
checks; neither reads a power-intent file.

So the missing capability was the FRONT of that chain: turning a real UPF file
into a structured model something else can reason over. That is what this
module is, and it stops exactly there.

BOUNDARY, stated rather than implied closed
-------------------------------------------
  * This is a UPF READER and a UPF SELF-CONSISTENCY analysis. Every finding
    `analyze_power_intent()` produces is decidable from the power intent's own
    text -- a strategy naming a domain that was never created, a supply net
    referenced but never declared, a switchable domain with no isolation
    strategy. NOTHING here is checked against RTL, a netlist, a simulation, or
    a DUT: this project owns no low-power DUT and no real UPF of its own, and
    a "check" against nothing would be exactly the fabricated low-power flow
    section 224 forbids.
  * It does NOT verify isolation/retention/clock-gating/wake-up BEHAVIOR. No
    power-aware simulation, no UPF-to-simulator handoff, no assertion
    generation. Those need a real low-power DUT and a power-aware simulator.
  * It is a Tcl-SUBSET parser, not a Tcl interpreter. `set` + `$var` /`${var}`
    substitution is implemented because that is real, correct Tcl semantics
    and real UPF files use it; command substitution (`[...]`), `if`/`foreach`/
    `proc` control flow, `expr`, and `source`/`load_upf` file inclusion are
    NOT executed. A command this module does not model is never silently
    dropped -- it is recorded in `unsupported_commands` with its file and line
    so a reader can see exactly what was skipped.
  * Power STATE tables (`add_power_state`, `create_pst`, `add_pst_state`) are
    parsed as unsupported-but-recorded rather than modelled. Their value
    expressions are supply-expression mini-language, not the flat option/value
    shape the modelled commands share, and modelling them badly would be worse
    than reporting them honestly as unmodelled.

MODELLED COMMANDS (the bounded subset, chosen because each maps cleanly onto a
flat option/value structure and together they carry the power topology):

    upf_version / set_design_top / set_scope     file-level context
    set                                          variable binding (Tcl)
    create_power_domain                          the domains themselves
    create_supply_port / create_supply_net       the supply topology
    create_supply_set                            supply-set abstraction
    connect_supply_net / set_domain_supply_net   supply connectivity
    create_power_switch                          which domains can power down
    set_isolation / set_isolation_control        isolation strategies
    set_retention / set_retention_control        retention strategies

Both UPF-1.0 style (a separate `set_isolation_control` / `set_retention_control`
command) and UPF-2.x style (the control options folded into `set_isolation` /
`set_retention` itself) are accepted, and merged into one strategy record --
because they are the same strategy expressed two ways, and a reader asking
"does this strategy have a control signal" must get one answer, not two.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "UpfParseError",
    "Word",
    "UpfCommand",
    "PowerDomain",
    "SupplyPort",
    "SupplyNet",
    "SupplySet",
    "PowerSwitch",
    "IsolationStrategy",
    "RetentionStrategy",
    "PowerIntentIssue",
    "PowerIntent",
    "PowerIntentFinding",
    "PowerIntentReport",
    "tokenize_upf",
    "parse_upf_text",
    "extract_power_intent",
    "analyze_power_intent",
    "format_report",
]


class UpfParseError(Exception):
    """Raised only for a structurally unrecoverable file (unbalanced brace or
    quote). Everything a reader could still make sense of is reported as an
    issue on the model instead, so one bad command never discards a whole
    file's worth of real power intent."""


# ---------------------------------------------------------------------------
# Tcl-subset tokenizer
# ---------------------------------------------------------------------------

@dataclass
class Word:
    """One argument word of a Tcl command, with the provenance a later check
    needs: `braced` words are literal (Tcl performs no substitution inside
    braces) and are the shape UPF uses for lists (`-elements {a b c}`)."""
    text: str
    braced: bool = False
    quoted: bool = False
    line: int = 0

    @property
    def is_option(self) -> bool:
        # A braced/quoted word is a VALUE even if its text starts with '-'
        # (e.g. an on_state boolean expression); only a bare word can be an
        # option name.
        return (not self.braced) and (not self.quoted) and self.text.startswith("-")


@dataclass
class UpfCommand:
    name: str
    words: List[Word]
    line: int
    file: str = ""


def _read_braced(text: str, i: int) -> Tuple[str, int]:
    """Read a `{...}` group starting at text[i] == '{'. Returns (inner, index
    just past the closing brace). Braces nest; a backslash escapes the next
    character (which is how a literal unbalanced brace is written in Tcl)."""
    assert text[i] == "{"
    depth = 0
    j = i
    out: List[str] = []
    while j < len(text):
        c = text[j]
        if c == "\\" and j + 1 < len(text):
            out.append(c)
            out.append(text[j + 1])
            j += 2
            continue
        if c == "{":
            depth += 1
            if depth == 1:
                j += 1
                continue
        elif c == "}":
            depth -= 1
            if depth == 0:
                return "".join(out), j + 1
        out.append(c)
        j += 1
    raise UpfParseError("unbalanced '{' -- no matching '}' before end of file")


def _read_quoted(text: str, i: int) -> Tuple[str, int]:
    """Read a `"..."` group starting at text[i] == '"'."""
    assert text[i] == '"'
    j = i + 1
    out: List[str] = []
    while j < len(text):
        c = text[j]
        if c == "\\" and j + 1 < len(text):
            nxt = text[j + 1]
            # backslash-newline collapses to a single space, per Tcl
            out.append(" " if nxt == "\n" else nxt)
            j += 2
            continue
        if c == '"':
            return "".join(out), j + 1
        out.append(c)
        j += 1
    raise UpfParseError('unbalanced \'"\' -- no matching quote before end of file')


def _read_bare(text: str, i: int) -> Tuple[str, int]:
    """Read a bare (unquoted, unbraced) word. Ends at whitespace, ';' or a
    newline. A backslash-newline inside a bare word ends the word (Tcl turns
    it into whitespace)."""
    j = i
    out: List[str] = []
    while j < len(text):
        c = text[j]
        if c == "\\" and j + 1 < len(text):
            if text[j + 1] == "\n":
                break  # backslash-newline == word separator
            out.append(text[j + 1])
            j += 2
            continue
        if c in " \t\r\n;":
            break
        out.append(c)
        j += 1
    return "".join(out), j


def tokenize_upf(text: str, file_label: str = "") -> List[UpfCommand]:
    """Split UPF/Tcl source into commands and words.

    Handles: `#` comments (only at a command position, per Tcl), `;` command
    separation, backslash-newline continuation, `{...}` nesting and `"..."`
    quoting. Command substitution `[...]` is NOT executed -- a word containing
    it is kept verbatim so the caller can report it rather than mis-read it.
    """
    commands: List[UpfCommand] = []
    i = 0
    line = 1
    n = len(text)
    words: List[Word] = []
    cmd_line = 1

    def flush() -> None:
        nonlocal words, cmd_line
        if words:
            commands.append(UpfCommand(name=words[0].text, words=words[1:],
                                       line=cmd_line, file=file_label))
        words = []

    while i < n:
        c = text[i]
        if c == "\n":
            flush()
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == ";":
            flush()
            i += 1
            continue
        if c == "\\" and i + 1 < n and text[i + 1] == "\n":
            # explicit line continuation between words
            line += 1
            i += 2
            continue
        if c == "#" and not words:
            # comment runs to end of line, but a backslash-newline continues it
            while i < n and text[i] != "\n":
                if text[i] == "\\" and i + 1 < n and text[i + 1] == "\n":
                    line += 1
                    i += 2
                    continue
                i += 1
            continue
        if not words:
            cmd_line = line
        if c == "{":
            inner, j = _read_braced(text, i)
            words.append(Word(text=inner, braced=True, line=line))
        elif c == '"':
            inner, j = _read_quoted(text, i)
            words.append(Word(text=inner, quoted=True, line=line))
        else:
            inner, j = _read_bare(text, i)
            words.append(Word(text=inner, line=line))
        line += text.count("\n", i, j)
        i = j
    flush()
    return [c for c in commands if c.name]


# ---------------------------------------------------------------------------
# Option-shape handling
# ---------------------------------------------------------------------------

# UPF options that are pure flags and never consume the following word. Kept
# deliberately CONSERVATIVE: anything not listed here is treated as taking a
# value, and the value-taking path itself refuses to swallow a following
# option name (see _parse_options), so a flag missing from this set degrades
# into a recorded issue rather than a silently mis-parsed command.
BOOLEAN_OPTIONS = frozenset({
    "-include_scope", "-reuse", "-update", "-simple", "-atomic",
    "-diff_supply_only", "-no_isolation", "-force_isolation",
    "-resolve", "-sim_only", "-transitive",
})

_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _parse_options(words: Sequence[Word]) -> Tuple[List[Word], Dict[str, List[Word]], List[str]]:
    """Split a command's words into (positionals, options, problems).

    `options` maps an option name to the LIST of its values, because UPF
    genuinely repeats options (`create_power_switch -input_supply_port {...}
    -input_supply_port {...}`). A boolean flag maps to a list containing one
    Word whose text is "" -- present, no value.
    """
    positionals: List[Word] = []
    options: Dict[str, List[Word]] = {}
    problems: List[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if not w.is_option:
            positionals.append(w)
            i += 1
            continue
        name = w.text
        if name in BOOLEAN_OPTIONS:
            options.setdefault(name, []).append(Word(text="", line=w.line))
            i += 1
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        takes_value = (
            nxt is not None
            and (nxt.braced or nxt.quoted
                 or not nxt.text.startswith("-")
                 or bool(_NUMBER_RE.match(nxt.text)))
        )
        if takes_value:
            options.setdefault(name, []).append(nxt)
            i += 2
        else:
            problems.append(f"option {name} has no value")
            options.setdefault(name, []).append(Word(text="", line=w.line))
            i += 1
    return positionals, options, problems


def _opt(options: Dict[str, List[Word]], name: str) -> Optional[str]:
    vals = options.get(name)
    if not vals:
        return None
    return vals[0].text or None


def _opt_all(options: Dict[str, List[Word]], name: str) -> List[str]:
    return [w.text for w in options.get(name, []) if w.text]


def _as_list(value: Optional[str]) -> List[str]:
    """A UPF list option is a braced group of whitespace-separated names."""
    if not value:
        return []
    return [t for t in value.replace("\n", " ").split() if t]


def _first_token(value: Optional[str]) -> Optional[str]:
    """`-save_signal {pmu_save posedge}` -- the SIGNAL is the first token, the
    second is the sense. Callers that only need "is there a signal at all"
    use this."""
    toks = _as_list(value)
    return toks[0] if toks else None


# ---------------------------------------------------------------------------
# Structured power-intent model
# ---------------------------------------------------------------------------

@dataclass
class PowerDomain:
    name: str
    scope: Optional[str] = None
    elements: List[str] = field(default_factory=list)
    include_scope: bool = False
    supply_sets: List[str] = field(default_factory=list)
    primary_power_net: Optional[str] = None
    primary_ground_net: Optional[str] = None
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"name": self.name, "scope": self.scope, "elements": list(self.elements),
                "include_scope": self.include_scope, "supply_sets": list(self.supply_sets),
                "primary_power_net": self.primary_power_net,
                "primary_ground_net": self.primary_ground_net,
                "file": self.file, "line": self.line}


@dataclass
class SupplyPort:
    name: str
    domain: Optional[str] = None
    direction: Optional[str] = None
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"name": self.name, "domain": self.domain, "direction": self.direction,
                "file": self.file, "line": self.line}


@dataclass
class SupplyNet:
    name: str
    domain: Optional[str] = None
    resolve: Optional[str] = None
    reuse: bool = False
    connected_ports: List[str] = field(default_factory=list)
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"name": self.name, "domain": self.domain, "resolve": self.resolve,
                "reuse": self.reuse, "connected_ports": list(self.connected_ports),
                "file": self.file, "line": self.line}


@dataclass
class SupplySet:
    name: str
    functions: List[str] = field(default_factory=list)
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"name": self.name, "functions": list(self.functions),
                "file": self.file, "line": self.line}


@dataclass
class PowerSwitch:
    name: str
    domain: Optional[str] = None
    input_supply_ports: List[str] = field(default_factory=list)
    output_supply_ports: List[str] = field(default_factory=list)
    control_ports: List[str] = field(default_factory=list)
    on_states: List[str] = field(default_factory=list)
    off_state: Optional[str] = None
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"name": self.name, "domain": self.domain,
                "input_supply_ports": list(self.input_supply_ports),
                "output_supply_ports": list(self.output_supply_ports),
                "control_ports": list(self.control_ports),
                "on_states": list(self.on_states), "off_state": self.off_state,
                "file": self.file, "line": self.line}


@dataclass
class IsolationStrategy:
    name: str
    domain: Optional[str] = None
    isolation_power_net: Optional[str] = None
    isolation_ground_net: Optional[str] = None
    isolation_supply_set: Optional[str] = None
    isolation_signal: Optional[str] = None
    isolation_sense: Optional[str] = None
    clamp_value: Optional[str] = None
    applies_to: Optional[str] = None
    location: Optional[str] = None
    elements: List[str] = field(default_factory=list)
    no_isolation: bool = False
    file: str = ""
    line: int = 0
    control_line: Optional[int] = None

    @property
    def has_control(self) -> bool:
        return bool(self.isolation_signal)

    def to_dict(self) -> dict:
        return {"name": self.name, "domain": self.domain,
                "isolation_power_net": self.isolation_power_net,
                "isolation_ground_net": self.isolation_ground_net,
                "isolation_supply_set": self.isolation_supply_set,
                "isolation_signal": self.isolation_signal,
                "isolation_sense": self.isolation_sense,
                "clamp_value": self.clamp_value, "applies_to": self.applies_to,
                "location": self.location, "elements": list(self.elements),
                "no_isolation": self.no_isolation,
                "file": self.file, "line": self.line, "control_line": self.control_line}


@dataclass
class RetentionStrategy:
    name: str
    domain: Optional[str] = None
    retention_power_net: Optional[str] = None
    retention_ground_net: Optional[str] = None
    retention_supply_set: Optional[str] = None
    save_signal: Optional[str] = None
    save_sense: Optional[str] = None
    restore_signal: Optional[str] = None
    restore_sense: Optional[str] = None
    retention_condition: Optional[str] = None
    elements: List[str] = field(default_factory=list)
    file: str = ""
    line: int = 0
    control_line: Optional[int] = None

    @property
    def has_control(self) -> bool:
        return bool(self.save_signal or self.restore_signal or self.retention_condition)

    def to_dict(self) -> dict:
        return {"name": self.name, "domain": self.domain,
                "retention_power_net": self.retention_power_net,
                "retention_ground_net": self.retention_ground_net,
                "retention_supply_set": self.retention_supply_set,
                "save_signal": self.save_signal, "save_sense": self.save_sense,
                "restore_signal": self.restore_signal, "restore_sense": self.restore_sense,
                "retention_condition": self.retention_condition,
                "elements": list(self.elements),
                "file": self.file, "line": self.line, "control_line": self.control_line}


@dataclass
class PowerIntentIssue:
    """A problem with READING the file (an unmodelled command, an option with
    no value, an unresolved `$var`) -- distinct from a
    `PowerIntentFinding`, which is a problem with the power intent ITSELF."""
    code: str
    detail: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "file": self.file, "line": self.line}


@dataclass
class PowerIntent:
    source_files: List[str] = field(default_factory=list)
    upf_version: Optional[str] = None
    design_top: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    domains: List[PowerDomain] = field(default_factory=list)
    supply_ports: List[SupplyPort] = field(default_factory=list)
    supply_nets: List[SupplyNet] = field(default_factory=list)
    supply_sets: List[SupplySet] = field(default_factory=list)
    switches: List[PowerSwitch] = field(default_factory=list)
    isolation: List[IsolationStrategy] = field(default_factory=list)
    retention: List[RetentionStrategy] = field(default_factory=list)
    unsupported_commands: List[PowerIntentIssue] = field(default_factory=list)
    issues: List[PowerIntentIssue] = field(default_factory=list)

    # -- lookups -----------------------------------------------------------
    def domain(self, name: str) -> Optional[PowerDomain]:
        return next((d for d in self.domains if d.name == name), None)

    @property
    def domain_names(self) -> List[str]:
        return [d.name for d in self.domains]

    @property
    def declared_supply_names(self) -> set:
        """Every name that can legally be referenced as a supply: supply nets,
        supply ports, and supply-set function handles (`SS.power`)."""
        names = {n.name for n in self.supply_nets} | {p.name for p in self.supply_ports}
        for s in self.supply_sets:
            names.add(s.name)
        return names

    def switchable_domains(self) -> List[str]:
        """A domain is switchable when a power switch drives it -- either the
        switch declares `-domain PD`, or one of its output supply ports feeds a
        net that PD uses as its primary power net."""
        out: List[str] = []
        net_to_domain: Dict[str, List[str]] = {}
        for d in self.domains:
            if d.primary_power_net:
                net_to_domain.setdefault(d.primary_power_net, []).append(d.name)
        for sw in self.switches:
            if sw.domain:
                out.append(sw.domain)
            for spec in sw.output_supply_ports:
                toks = _as_list(spec)
                # `-output_supply_port {vout VDD_SW}`: port name, then net
                for tok in toks[1:]:
                    out.extend(net_to_domain.get(tok, []))
        seen: List[str] = []
        for name in out:
            if name not in seen:
                seen.append(name)
        return seen

    def to_dict(self) -> dict:
        return {
            "source_files": list(self.source_files),
            "upf_version": self.upf_version,
            "design_top": self.design_top,
            "scopes": list(self.scopes),
            "variables": dict(self.variables),
            "domains": [d.to_dict() for d in self.domains],
            "supply_ports": [p.to_dict() for p in self.supply_ports],
            "supply_nets": [n.to_dict() for n in self.supply_nets],
            "supply_sets": [s.to_dict() for s in self.supply_sets],
            "switches": [s.to_dict() for s in self.switches],
            "isolation_strategies": [s.to_dict() for s in self.isolation],
            "retention_strategies": [s.to_dict() for s in self.retention],
            "unsupported_commands": [i.to_dict() for i in self.unsupported_commands],
            "issues": [i.to_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\$\{(?P<braced>[^}]*)\}|\$(?P<bare>[A-Za-z0-9_:]+)")

MODELLED_COMMANDS = frozenset({
    "upf_version", "set_design_top", "set_scope", "set",
    "create_power_domain", "create_supply_port", "create_supply_net",
    "create_supply_set", "connect_supply_net", "set_domain_supply_net",
    "create_power_switch", "set_isolation", "set_isolation_control",
    "set_retention", "set_retention_control",
})


def _substitute(word: Word, variables: Dict[str, str],
                intent: PowerIntent, file_label: str) -> Word:
    """Apply Tcl `$var` substitution. Braced words are literal -- Tcl performs
    no substitution inside `{}` -- so they are returned untouched."""
    if word.braced or "$" not in word.text:
        return word
    missing: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        name = m.group("braced") if m.group("braced") is not None else m.group("bare")
        if name in variables:
            return variables[name]
        missing.append(name)
        return m.group(0)

    new_text = _VAR_RE.sub(repl, word.text)
    for name in missing:
        intent.issues.append(PowerIntentIssue(
            code="UNRESOLVED_UPF_VARIABLE",
            detail=f"${name} is not bound by any `set` in the parsed sources; "
                   f"kept verbatim in {word.text!r}",
            file=file_label, line=word.line))
    return Word(text=new_text, braced=word.braced, quoted=word.quoted, line=word.line)


def _record_problems(intent: PowerIntent, cmd: UpfCommand, problems: Iterable[str]) -> None:
    for p in problems:
        intent.issues.append(PowerIntentIssue(
            code="MALFORMED_UPF_OPTION", detail=f"{cmd.name}: {p}",
            file=cmd.file, line=cmd.line))


def parse_upf_text(text: str, file_label: str = "<text>",
                   intent: Optional[PowerIntent] = None) -> PowerIntent:
    """Parse one UPF source into a PowerIntent. Pass an existing `intent` to
    accumulate several files into one model (a real design's power intent is
    routinely split across files)."""
    intent = intent if intent is not None else PowerIntent()
    if file_label not in intent.source_files:
        intent.source_files.append(file_label)

    for cmd in tokenize_upf(text, file_label):
        if "[" in cmd.name:
            intent.issues.append(PowerIntentIssue(
                code="COMMAND_SUBSTITUTION_NOT_EVALUATED",
                detail=f"command name contains '[...]': {cmd.name!r}",
                file=file_label, line=cmd.line))
        words = [_substitute(w, intent.variables, intent, file_label) for w in cmd.words]
        cmd = UpfCommand(name=cmd.name, words=words, line=cmd.line, file=file_label)

        if cmd.name not in MODELLED_COMMANDS:
            intent.unsupported_commands.append(PowerIntentIssue(
                code="UNMODELLED_UPF_COMMAND",
                detail=cmd.name + (" " + " ".join(w.text for w in cmd.words[:3]) if cmd.words else ""),
                file=file_label, line=cmd.line))
            continue

        handler = _HANDLERS[cmd.name]
        handler(intent, cmd, file_label)
    return intent


def _h_upf_version(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    if cmd.words:
        intent.upf_version = cmd.words[0].text


def _h_set_design_top(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    if cmd.words:
        intent.design_top = cmd.words[0].text


def _h_set_scope(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    scope = cmd.words[0].text if cmd.words else "."
    if scope not in intent.scopes:
        intent.scopes.append(scope)


def _h_set(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    if len(cmd.words) >= 2:
        intent.variables[cmd.words[0].text] = cmd.words[1].text


def _h_create_power_domain(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        intent.issues.append(PowerIntentIssue(
            code="MALFORMED_UPF_COMMAND", detail="create_power_domain without a domain name",
            file=f, line=cmd.line))
        return
    name = pos[0].text
    if intent.domain(name) is not None and "-update" not in opts:
        intent.issues.append(PowerIntentIssue(
            code="DUPLICATE_POWER_DOMAIN",
            detail=f"power domain {name} created more than once without -update",
            file=f, line=cmd.line))
    dom = intent.domain(name)
    if dom is None:
        dom = PowerDomain(name=name, file=f, line=cmd.line)
        intent.domains.append(dom)
    if "-scope" in opts:
        dom.scope = _opt(opts, "-scope")
    for spec in _opt_all(opts, "-elements"):
        for el in _as_list(spec):
            if el not in dom.elements:
                dom.elements.append(el)
    if "-include_scope" in opts:
        dom.include_scope = True
    for spec in _opt_all(opts, "-supply"):
        toks = _as_list(spec)
        if toks and toks[0] not in dom.supply_sets:
            dom.supply_sets.append(toks[0])


def _h_create_supply_port(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        intent.issues.append(PowerIntentIssue(
            code="MALFORMED_UPF_COMMAND", detail="create_supply_port without a port name",
            file=f, line=cmd.line))
        return
    intent.supply_ports.append(SupplyPort(
        name=pos[0].text, domain=_opt(opts, "-domain"),
        direction=_opt(opts, "-direction"), file=f, line=cmd.line))


def _h_create_supply_net(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        intent.issues.append(PowerIntentIssue(
            code="MALFORMED_UPF_COMMAND", detail="create_supply_net without a net name",
            file=f, line=cmd.line))
        return
    name = pos[0].text
    existing = next((n for n in intent.supply_nets if n.name == name), None)
    if existing is not None and "-reuse" not in opts:
        intent.issues.append(PowerIntentIssue(
            code="DUPLICATE_SUPPLY_NET",
            detail=f"supply net {name} created more than once without -reuse",
            file=f, line=cmd.line))
    if existing is None:
        intent.supply_nets.append(SupplyNet(
            name=name, domain=_opt(opts, "-domain"), resolve=_opt(opts, "-resolve"),
            reuse="-reuse" in opts, file=f, line=cmd.line))


def _h_create_supply_set(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        return
    funcs: List[str] = []
    for spec in _opt_all(opts, "-function"):
        toks = _as_list(spec)
        if toks:
            funcs.append(toks[0])
    intent.supply_sets.append(SupplySet(name=pos[0].text, functions=funcs,
                                        file=f, line=cmd.line))


def _h_connect_supply_net(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        return
    net_name = pos[0].text
    net = next((n for n in intent.supply_nets if n.name == net_name), None)
    if net is None:
        intent.issues.append(PowerIntentIssue(
            code="CONNECT_SUPPLY_NET_UNDECLARED_NET",
            detail=f"connect_supply_net names supply net {net_name}, never created",
            file=f, line=cmd.line))
        return
    for spec in _opt_all(opts, "-ports"):
        for p in _as_list(spec):
            if p not in net.connected_ports:
                net.connected_ports.append(p)


def _h_set_domain_supply_net(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        return
    dom = intent.domain(pos[0].text)
    if dom is None:
        intent.issues.append(PowerIntentIssue(
            code="DOMAIN_SUPPLY_FOR_UNDECLARED_DOMAIN",
            detail=f"set_domain_supply_net names power domain {pos[0].text}, never created",
            file=f, line=cmd.line))
        return
    dom.primary_power_net = _opt(opts, "-primary_power_net") or dom.primary_power_net
    dom.primary_ground_net = _opt(opts, "-primary_ground_net") or dom.primary_ground_net


def _h_create_power_switch(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        return
    intent.switches.append(PowerSwitch(
        name=pos[0].text, domain=_opt(opts, "-domain"),
        input_supply_ports=_opt_all(opts, "-input_supply_port"),
        output_supply_ports=_opt_all(opts, "-output_supply_port"),
        control_ports=_opt_all(opts, "-control_port"),
        on_states=_opt_all(opts, "-on_state"),
        off_state=_opt(opts, "-off_state"), file=f, line=cmd.line))


def _iso_for(intent: PowerIntent, name: str, domain: Optional[str]) -> Optional[IsolationStrategy]:
    """A strategy name is unique per DOMAIN in UPF, so both are matched. A
    control command that omits -domain matches on name alone."""
    for s in intent.isolation:
        if s.name == name and (domain is None or s.domain == domain):
            return s
    return None


def _apply_iso_control(s: IsolationStrategy, opts: Dict[str, List[Word]]) -> None:
    sig = _opt(opts, "-isolation_signal")
    if sig:
        s.isolation_signal = sig
    sense = _opt(opts, "-isolation_sense")
    if sense:
        s.isolation_sense = sense
    loc = _opt(opts, "-location")
    if loc:
        s.location = loc
    clamp = _opt(opts, "-clamp_value")
    if clamp is not None:
        s.clamp_value = clamp


def _h_set_isolation(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        intent.issues.append(PowerIntentIssue(
            code="MALFORMED_UPF_COMMAND", detail="set_isolation without a strategy name",
            file=f, line=cmd.line))
        return
    name = pos[0].text
    domain = _opt(opts, "-domain")
    existing = _iso_for(intent, name, domain)
    if existing is not None and "-update" not in opts:
        intent.issues.append(PowerIntentIssue(
            code="DUPLICATE_ISOLATION_STRATEGY",
            detail=f"isolation strategy {name} on domain {domain} defined more "
                   f"than once without -update",
            file=f, line=cmd.line))
    s = existing if existing is not None else IsolationStrategy(
        name=name, domain=domain, file=f, line=cmd.line)
    if existing is None:
        intent.isolation.append(s)
    s.isolation_power_net = _opt(opts, "-isolation_power_net") or s.isolation_power_net
    s.isolation_ground_net = _opt(opts, "-isolation_ground_net") or s.isolation_ground_net
    s.isolation_supply_set = _opt(opts, "-isolation_supply_set") or s.isolation_supply_set
    s.applies_to = _opt(opts, "-applies_to") or s.applies_to
    if "-no_isolation" in opts:
        s.no_isolation = True
    for spec in _opt_all(opts, "-elements"):
        for el in _as_list(spec):
            if el not in s.elements:
                s.elements.append(el)
    # UPF 2.x folds the control options into set_isolation itself.
    _apply_iso_control(s, opts)


def _h_set_isolation_control(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        return
    name = pos[0].text
    domain = _opt(opts, "-domain")
    s = _iso_for(intent, name, domain)
    if s is None:
        intent.issues.append(PowerIntentIssue(
            code="ISOLATION_CONTROL_WITHOUT_STRATEGY",
            detail=f"set_isolation_control names isolation strategy {name}"
                   + (f" on domain {domain}" if domain else "")
                   + ", which no set_isolation created",
            file=f, line=cmd.line))
        return
    _apply_iso_control(s, opts)
    s.control_line = cmd.line


def _ret_for(intent: PowerIntent, name: str, domain: Optional[str]) -> Optional[RetentionStrategy]:
    for s in intent.retention:
        if s.name == name and (domain is None or s.domain == domain):
            return s
    return None


def _apply_ret_control(s: RetentionStrategy, opts: Dict[str, List[Word]]) -> None:
    save = _opt(opts, "-save_signal")
    if save:
        toks = _as_list(save)
        s.save_signal = toks[0] if toks else None
        s.save_sense = toks[1] if len(toks) > 1 else s.save_sense
    restore = _opt(opts, "-restore_signal")
    if restore:
        toks = _as_list(restore)
        s.restore_signal = toks[0] if toks else None
        s.restore_sense = toks[1] if len(toks) > 1 else s.restore_sense
    cond = _opt(opts, "-retention_condition")
    if cond:
        s.retention_condition = cond


def _h_set_retention(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        intent.issues.append(PowerIntentIssue(
            code="MALFORMED_UPF_COMMAND", detail="set_retention without a strategy name",
            file=f, line=cmd.line))
        return
    name = pos[0].text
    domain = _opt(opts, "-domain")
    existing = _ret_for(intent, name, domain)
    if existing is not None and "-update" not in opts:
        intent.issues.append(PowerIntentIssue(
            code="DUPLICATE_RETENTION_STRATEGY",
            detail=f"retention strategy {name} on domain {domain} defined more "
                   f"than once without -update",
            file=f, line=cmd.line))
    s = existing if existing is not None else RetentionStrategy(
        name=name, domain=domain, file=f, line=cmd.line)
    if existing is None:
        intent.retention.append(s)
    s.retention_power_net = _opt(opts, "-retention_power_net") or s.retention_power_net
    s.retention_ground_net = _opt(opts, "-retention_ground_net") or s.retention_ground_net
    s.retention_supply_set = _opt(opts, "-retention_supply_set") or s.retention_supply_set
    for spec in _opt_all(opts, "-elements"):
        for el in _as_list(spec):
            if el not in s.elements:
                s.elements.append(el)
    _apply_ret_control(s, opts)


def _h_set_retention_control(intent: PowerIntent, cmd: UpfCommand, f: str) -> None:
    pos, opts, probs = _parse_options(cmd.words)
    _record_problems(intent, cmd, probs)
    if not pos:
        return
    name = pos[0].text
    domain = _opt(opts, "-domain")
    s = _ret_for(intent, name, domain)
    if s is None:
        intent.issues.append(PowerIntentIssue(
            code="RETENTION_CONTROL_WITHOUT_STRATEGY",
            detail=f"set_retention_control names retention strategy {name}"
                   + (f" on domain {domain}" if domain else "")
                   + ", which no set_retention created",
            file=f, line=cmd.line))
        return
    _apply_ret_control(s, opts)
    s.control_line = cmd.line


_HANDLERS = {
    "upf_version": _h_upf_version,
    "set_design_top": _h_set_design_top,
    "set_scope": _h_set_scope,
    "set": _h_set,
    "create_power_domain": _h_create_power_domain,
    "create_supply_port": _h_create_supply_port,
    "create_supply_net": _h_create_supply_net,
    "create_supply_set": _h_create_supply_set,
    "connect_supply_net": _h_connect_supply_net,
    "set_domain_supply_net": _h_set_domain_supply_net,
    "create_power_switch": _h_create_power_switch,
    "set_isolation": _h_set_isolation,
    "set_isolation_control": _h_set_isolation_control,
    "set_retention": _h_set_retention,
    "set_retention_control": _h_set_retention_control,
}


def extract_power_intent(paths: Sequence) -> PowerIntent:
    """Parse one or more real UPF files into a single structured model. Files
    are parsed in the order given, which is the order UPF itself depends on
    (a `set_isolation_control` must follow its `set_isolation`)."""
    intent = PowerIntent()
    for p in paths:
        path = Path(p)
        label = str(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            intent.issues.append(PowerIntentIssue(
                code="UPF_FILE_UNREADABLE", detail=str(exc), file=label, line=0))
            if label not in intent.source_files:
                intent.source_files.append(label)
            continue
        try:
            parse_upf_text(text, file_label=label, intent=intent)
        except UpfParseError as exc:
            intent.issues.append(PowerIntentIssue(
                code="UPF_FILE_UNPARSEABLE", detail=str(exc), file=label, line=0))
            if label not in intent.source_files:
                intent.source_files.append(label)
    return intent


# ---------------------------------------------------------------------------
# Self-consistency analysis of the extracted intent
# ---------------------------------------------------------------------------

@dataclass
class PowerIntentFinding:
    severity: str          # ERROR | WARNING | INFO
    code: str
    message: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message,
                "file": self.file, "line": self.line}


@dataclass
class PowerIntentReport:
    status: str            # PASS | FAIL | NOT_AVAILABLE
    reason: Optional[str]
    intent: PowerIntent
    findings: List[PowerIntentFinding] = field(default_factory=list)

    @property
    def errors(self) -> List[PowerIntentFinding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> List[PowerIntentFinding]:
        return [f for f in self.findings if f.severity == "WARNING"]

    def to_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason,
                "findings": [f.to_dict() for f in self.findings],
                "power_intent": self.intent.to_dict()}


def analyze_power_intent(intent: PowerIntent) -> PowerIntentReport:
    """Check the extracted power intent against ITSELF.

    Every rule here is decidable from the UPF text alone. None of them looks
    at RTL, a netlist or a simulation -- section 224's "do not fabricate a
    low-power verification flow" means this analysis must not present itself
    as having verified low-power BEHAVIOR, and it does not.

    An empty model is NOT_AVAILABLE, never PASS -- "no power intent was found"
    is section 224's UNSUPPORTED/UNKNOWN outcome, not a clean bill of health.
    """
    if not intent.domains and not intent.isolation and not intent.retention \
            and not intent.supply_nets and not intent.supply_ports:
        return PowerIntentReport(
            status="NOT_AVAILABLE",
            reason="no power-intent constructs found in the parsed sources "
                   f"({len(intent.source_files)} file(s), "
                   f"{len(intent.unsupported_commands)} unmodelled command(s))",
            intent=intent, findings=[])

    findings: List[PowerIntentFinding] = []
    domain_names = set(intent.domain_names)
    supply_names = intent.declared_supply_names

    def check_supply(ref: Optional[str], what: str, f: str, line: int) -> None:
        if not ref:
            return
        # a supply-set function handle is written `SS.power`
        base = ref.split(".", 1)[0]
        if base not in supply_names:
            findings.append(PowerIntentFinding(
                "ERROR", "SUPPLY_NET_UNDECLARED",
                f"{what} references supply {ref!r}, which no create_supply_net / "
                f"create_supply_port / create_supply_set declares", f, line))

    # -- domains -----------------------------------------------------------
    for d in intent.domains:
        if not d.primary_power_net and not d.supply_sets:
            findings.append(PowerIntentFinding(
                "WARNING", "DOMAIN_WITHOUT_PRIMARY_SUPPLY",
                f"power domain {d.name} has neither a set_domain_supply_net "
                f"-primary_power_net nor a -supply supply set",
                d.file, d.line))
        check_supply(d.primary_power_net, f"power domain {d.name}", d.file, d.line)
        check_supply(d.primary_ground_net, f"power domain {d.name}", d.file, d.line)
        if not d.elements and not d.include_scope:
            findings.append(PowerIntentFinding(
                "WARNING", "DOMAIN_WITHOUT_ELEMENTS",
                f"power domain {d.name} lists no -elements and does not "
                f"-include_scope, so it contains nothing",
                d.file, d.line))

    for p in intent.supply_ports:
        if p.domain and p.domain not in domain_names:
            findings.append(PowerIntentFinding(
                "ERROR", "SUPPLY_PORT_DOMAIN_UNDECLARED",
                f"supply port {p.name} is placed in power domain {p.domain}, "
                f"which no create_power_domain declares", p.file, p.line))
    for n in intent.supply_nets:
        if n.domain and n.domain not in domain_names:
            findings.append(PowerIntentFinding(
                "ERROR", "SUPPLY_NET_DOMAIN_UNDECLARED",
                f"supply net {n.name} is placed in power domain {n.domain}, "
                f"which no create_power_domain declares", n.file, n.line))

    # -- switches ----------------------------------------------------------
    for sw in intent.switches:
        if sw.domain and sw.domain not in domain_names:
            findings.append(PowerIntentFinding(
                "ERROR", "SWITCH_DOMAIN_UNDECLARED",
                f"power switch {sw.name} drives power domain {sw.domain}, "
                f"which no create_power_domain declares", sw.file, sw.line))
        if not sw.control_ports:
            findings.append(PowerIntentFinding(
                "ERROR", "SWITCH_WITHOUT_CONTROL_PORT",
                f"power switch {sw.name} declares no -control_port, so nothing "
                f"can turn it off or on", sw.file, sw.line))
        if not sw.on_states:
            findings.append(PowerIntentFinding(
                "WARNING", "SWITCH_WITHOUT_ON_STATE",
                f"power switch {sw.name} declares no -on_state condition",
                sw.file, sw.line))
        for spec in sw.input_supply_ports + sw.output_supply_ports:
            toks = _as_list(spec)
            for net in toks[1:]:
                check_supply(net, f"power switch {sw.name}", sw.file, sw.line)

    # -- isolation ---------------------------------------------------------
    iso_by_domain: Dict[str, List[IsolationStrategy]] = {}
    for s in intent.isolation:
        if s.domain:
            iso_by_domain.setdefault(s.domain, []).append(s)
        if s.domain and s.domain not in domain_names:
            findings.append(PowerIntentFinding(
                "ERROR", "ISOLATION_DOMAIN_UNDECLARED",
                f"isolation strategy {s.name} names power domain {s.domain}, "
                f"which no create_power_domain declares", s.file, s.line))
        if not s.domain:
            findings.append(PowerIntentFinding(
                "ERROR", "ISOLATION_WITHOUT_DOMAIN",
                f"isolation strategy {s.name} declares no -domain", s.file, s.line))
        if s.no_isolation:
            continue
        if not s.has_control:
            findings.append(PowerIntentFinding(
                "ERROR", "ISOLATION_WITHOUT_CONTROL_SIGNAL",
                f"isolation strategy {s.name} has no -isolation_signal, from "
                f"set_isolation or set_isolation_control -- nothing asserts it",
                s.file, s.line))
        elif not s.isolation_sense:
            findings.append(PowerIntentFinding(
                "WARNING", "ISOLATION_CONTROL_WITHOUT_SENSE",
                f"isolation strategy {s.name} names control signal "
                f"{s.isolation_signal} but no -isolation_sense, so its active "
                f"polarity is implementation-defaulted", s.file, s.line))
        if s.clamp_value is None:
            findings.append(PowerIntentFinding(
                "WARNING", "ISOLATION_WITHOUT_CLAMP_VALUE",
                f"isolation strategy {s.name} declares no -clamp_value",
                s.file, s.line))
        if not (s.isolation_power_net or s.isolation_supply_set):
            findings.append(PowerIntentFinding(
                "ERROR", "ISOLATION_WITHOUT_SUPPLY",
                f"isolation strategy {s.name} declares neither "
                f"-isolation_power_net nor -isolation_supply_set, so its cells "
                f"have no always-on supply", s.file, s.line))
        check_supply(s.isolation_power_net, f"isolation strategy {s.name}", s.file, s.line)
        check_supply(s.isolation_ground_net, f"isolation strategy {s.name}", s.file, s.line)
        check_supply(s.isolation_supply_set, f"isolation strategy {s.name}", s.file, s.line)

    # -- retention ---------------------------------------------------------
    ret_by_domain: Dict[str, List[RetentionStrategy]] = {}
    for s in intent.retention:
        if s.domain:
            ret_by_domain.setdefault(s.domain, []).append(s)
        if s.domain and s.domain not in domain_names:
            findings.append(PowerIntentFinding(
                "ERROR", "RETENTION_DOMAIN_UNDECLARED",
                f"retention strategy {s.name} names power domain {s.domain}, "
                f"which no create_power_domain declares", s.file, s.line))
        if not s.domain:
            findings.append(PowerIntentFinding(
                "ERROR", "RETENTION_WITHOUT_DOMAIN",
                f"retention strategy {s.name} declares no -domain", s.file, s.line))
        if not s.has_control:
            findings.append(PowerIntentFinding(
                "ERROR", "RETENTION_WITHOUT_SAVE_RESTORE",
                f"retention strategy {s.name} has neither -save_signal/"
                f"-restore_signal nor -retention_condition -- nothing sequences "
                f"its save and restore", s.file, s.line))
        elif s.retention_condition is None and not (s.save_signal and s.restore_signal):
            missing = "-save_signal" if not s.save_signal else "-restore_signal"
            findings.append(PowerIntentFinding(
                "ERROR", "RETENTION_CONTROL_INCOMPLETE",
                f"retention strategy {s.name} is missing {missing}; save and "
                f"restore must both be sequenced", s.file, s.line))
        if not (s.retention_power_net or s.retention_supply_set):
            findings.append(PowerIntentFinding(
                "ERROR", "RETENTION_WITHOUT_SUPPLY",
                f"retention strategy {s.name} declares neither "
                f"-retention_power_net nor -retention_supply_set, so its "
                f"registers have no always-on supply", s.file, s.line))
        check_supply(s.retention_power_net, f"retention strategy {s.name}", s.file, s.line)
        check_supply(s.retention_ground_net, f"retention strategy {s.name}", s.file, s.line)
        check_supply(s.retention_supply_set, f"retention strategy {s.name}", s.file, s.line)

    # -- switchable domains vs. their strategies ---------------------------
    for dname in intent.switchable_domains():
        if dname not in domain_names:
            continue  # already reported as SWITCH_DOMAIN_UNDECLARED
        if not [s for s in iso_by_domain.get(dname, []) if not s.no_isolation]:
            findings.append(PowerIntentFinding(
                "ERROR", "SWITCHABLE_DOMAIN_WITHOUT_ISOLATION",
                f"power domain {dname} is driven by a power switch (it can be "
                f"powered down) but has no isolation strategy -- its outputs "
                f"would float into always-on logic",
                *_domain_site(intent, dname)))
        if not ret_by_domain.get(dname):
            findings.append(PowerIntentFinding(
                "INFO", "SWITCHABLE_DOMAIN_WITHOUT_RETENTION",
                f"power domain {dname} is switchable and has no retention "
                f"strategy -- correct if the domain is meant to lose state, "
                f"and worth confirming against the design intent",
                *_domain_site(intent, dname)))

    # -- reading problems surfaced as findings -----------------------------
    for issue in intent.issues:
        sev = "ERROR" if issue.code in _READ_ISSUE_ERRORS else "WARNING"
        findings.append(PowerIntentFinding(sev, issue.code, issue.detail,
                                            issue.file, issue.line))
    for cmd in intent.unsupported_commands:
        findings.append(PowerIntentFinding(
            "INFO", "UNMODELLED_UPF_COMMAND",
            f"{cmd.detail} -- present in the source, not modelled by this "
            f"parser and therefore NOT analysed", cmd.file, cmd.line))

    status = "FAIL" if any(f.severity == "ERROR" for f in findings) else "PASS"
    findings.sort(key=lambda f: (_SEV_ORDER[f.severity], f.file, f.line, f.code))
    return PowerIntentReport(status=status, reason=None, intent=intent, findings=findings)


_SEV_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}

_READ_ISSUE_ERRORS = frozenset({
    "MALFORMED_UPF_COMMAND", "DUPLICATE_POWER_DOMAIN", "DUPLICATE_SUPPLY_NET",
    "DUPLICATE_ISOLATION_STRATEGY", "DUPLICATE_RETENTION_STRATEGY",
    "ISOLATION_CONTROL_WITHOUT_STRATEGY", "RETENTION_CONTROL_WITHOUT_STRATEGY",
    "CONNECT_SUPPLY_NET_UNDECLARED_NET", "DOMAIN_SUPPLY_FOR_UNDECLARED_DOMAIN",
    "UPF_FILE_UNREADABLE", "UPF_FILE_UNPARSEABLE",
})


def _domain_site(intent: PowerIntent, name: str) -> Tuple[str, int]:
    d = intent.domain(name)
    return (d.file, d.line) if d else ("", 0)


# ---------------------------------------------------------------------------
# Architecture-model bridge
# ---------------------------------------------------------------------------

def power_domains_for_architecture_model(intent: PowerIntent) -> List[dict]:
    """The `power_domains` rows for `.dv-harness/dut-architecture/
    architecture_model.schema.json`.

    That field has been hardcoded to `[]` by
    `tools/dut_architecture/build_architecture_model.py` since it was written,
    because nothing in this repo could produce a power domain. This is the
    producer. Every value is derived from the parsed UPF -- there is no
    inference and no default filled in for something the UPF did not say.
    """
    switchable = set(intent.switchable_domains())
    rows: List[dict] = []
    for d in intent.domains:
        rows.append({
            "name": d.name,
            "scope": d.scope,
            "elements": list(d.elements),
            "include_scope": d.include_scope,
            "primary_power_net": d.primary_power_net,
            "primary_ground_net": d.primary_ground_net,
            "supply_sets": list(d.supply_sets),
            "switchable": d.name in switchable,
            "isolation_strategies": [s.name for s in intent.isolation if s.domain == d.name],
            "retention_strategies": [s.name for s in intent.retention if s.domain == d.name],
            "source": "UPF",
            "evidence": f"{d.file}:{d.line}",
        })
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def format_report(report: PowerIntentReport) -> str:
    i = report.intent
    lines: List[str] = []
    lines.append(f"power-intent: {report.status}"
                 + (f" -- {report.reason}" if report.reason else ""))
    lines.append(f"  sources           : {', '.join(i.source_files) or '(none)'}")
    lines.append(f"  upf_version       : {i.upf_version or 'UNKNOWN'}")
    lines.append(f"  design top        : {i.design_top or 'UNKNOWN'}")
    lines.append(f"  power domains     : {len(i.domains)}"
                 + (f"  ({', '.join(i.domain_names)})" if i.domains else ""))
    switchable = i.switchable_domains()
    lines.append(f"  switchable domains: {len(switchable)}"
                 + (f"  ({', '.join(switchable)})" if switchable else ""))
    lines.append(f"  supply ports/nets : {len(i.supply_ports)} / {len(i.supply_nets)}")
    lines.append(f"  power switches    : {len(i.switches)}")
    lines.append(f"  isolation         : {len(i.isolation)}")
    lines.append(f"  retention         : {len(i.retention)}")
    lines.append(f"  unmodelled cmds   : {len(i.unsupported_commands)}")
    if report.findings:
        lines.append("")
        lines.append(f"findings: {len(report.errors)} ERROR, "
                     f"{len(report.warnings)} WARNING, "
                     f"{len(report.findings) - len(report.errors) - len(report.warnings)} INFO")
        for f in report.findings:
            where = f"{f.file}:{f.line}" if f.file else "-"
            lines.append(f"  [{f.severity:<7}] {f.code:<38} {where}")
            lines.append(f"            {f.message}")
    else:
        lines.append("")
        lines.append("findings: none")
    lines.append("")
    lines.append("SCOPE: this is a UPF reader and a self-consistency analysis of the power")
    lines.append("intent's own text. Nothing here is checked against RTL, a netlist or a")
    lines.append("simulation, and no low-power BEHAVIOR has been verified.")
    return "\n".join(lines)


def execute_verb(upf_paths: Sequence, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness power-intent` and
    `python -m dv_harness.power_intent`. Returns (text, exit_code)."""
    intent = extract_power_intent(upf_paths)
    report = analyze_power_intent(intent)
    text = json.dumps(report.to_dict(), indent=2) if as_json else format_report(report)
    code = {"PASS": 0, "FAIL": 1, "NOT_AVAILABLE": 2}[report.status]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.power_intent",
        description="Parse real UPF (IEEE 1801) power intent into a structured model and "
                    "check it against itself. Reads files only; verifies no behavior.")
    ap.add_argument("--upf", action="append", required=True, dest="upf_paths",
                    help="A UPF file to parse (repeatable, parsed in order).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    ap.add_argument("--fail-on-error", action="store_true",
                    help="Exit non-zero when the analysis reports ERROR findings.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.upf_paths, as_json=a.json)
    print(text)
    if code == 1 and not a.fail_on_error:
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
