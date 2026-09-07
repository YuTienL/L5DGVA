"""SystemCommandGrammarIR: system-scope command grammar composition
(gap closure, 2026-09-06).

WHAT THIS MODULE IS
--------------------
A SYSTEM-level record answering one question no existing module answers:
when several subsystems each carry their own real DE `command.txt`-style
FORMATTING convention (separator style, argument format, comment format,
phase markers, ordering rules -- exactly the five facets
`de_command_style_learning.CommandStyleIR` already pattern-detects, one IR
per subsystem's own file), do those subsystems' conventions actually AGREE
closely enough to call the composed SYSTEM one coherent grammar, or do two
or more of them genuinely DISAGREE?

REUSE OVER REINVENT -- checked before writing a line of this module. A
repo-wide grep for `CommandStyleIR`/`command_style`/`grammar` found no
existing system-scope grammar composer. The two nearest-looking modules are
the wrong grain for this question, and neither is duplicated here:

  * `de_command_style_learning.py` (same-session sibling) is exactly what
    this module COMPOSES -- it pattern-detects ONE `CommandStyleIR` per
    real file, never compares two files' styles against each other. This
    module imports its `CommandStyleIR` shape and its `learn_command_style`
    reader directly rather than re-deriving either.
  * `system_command_plan.py` (SYS-18..22) answers "which existing subsystem
    parser would a System-level command NAME route to" and "does a
    command's SEMANTICS collide across subsystems" (SYS-22's twelve
    collision classes) -- both about command MEANING and ROUTING, never
    about FORMATTING STYLE. A system whose subsystems all route cleanly and
    never collide semantically can still disagree on whether commands are
    written one-per-line with semicolons or several-per-line, whether hex
    literals are underscore-grouped, whether comments trail or stand alone
    -- SYS-18..22 has no field for any of that, and this module adds
    nothing to SYS-22's own collision vocabulary; it never imports or
    extends `system_command_plan.py`.

EVIDENCE TRUTH RULE, applied here specifically
-----------------------------------------------
Every one of the five composed facets is EITHER:

  * UNIFORM   -- every subsystem that has REAL evidence for this facet
                 (i.e. its own `CommandStyleIR` did not report that
                 facet's own absence token, `NOT_AVAILABLE`/`NOT_FOUND`)
                 agrees on one convention value. That value is reported as
                 the system-wide convention.
  * AMBIGUOUS -- the subsystems that DO have real evidence for this facet
                 all agree, but at least one OTHER subsystem has no
                 evidence for it at all. The single agreed value is
                 reported alongside the status (it is real evidence, not a
                 fabrication), but the status makes clear that system-wide
                 uniformity is NOT confirmed -- a caller must never read
                 AMBIGUOUS as UNIFORM.
  * CONFLICTING -- two or more subsystems that each have real evidence for
                 this facet report GENUINELY DIFFERENT convention values.
                 `system_convention` is `None` in this case: this module
                 never silently picks one subsystem's convention over
                 another's, and never averages, votes, or defaults to the
                 first alphabetically.
  * NOT_AVAILABLE -- no subsystem has any real evidence for this facet at
                 all.

WORST-WINS COMPOSITE GATE (per this project's own house rule): the
system-level `system_status` is CONFLICTING the instant any single facet
is CONFLICTING, and AMBIGUOUS the instant any single facet is AMBIGUOUS
(with no facet CONFLICTING) -- either one facet's genuine problem fails
the whole composite verdict regardless of how many of the other facets
are clean; it is never averaged or diluted by the other facets'
cleanliness. A per-facet NOT_AVAILABLE is different in kind from those
two: it means every subsystem's own `CommandStyleIR` genuinely SEARCHED
for that facet and confirmed none of them use it (e.g. nobody in this
system happens to use PHASE-style markers) -- a confirmed, benign
absence, not an unresolved question, and it is NOT treated as a defect
that drags a clean composite down. The system-level verdict is only
NOT_AVAILABLE when EVERY facet is NOT_AVAILABLE, i.e. there is no real
grammar evidence to compose at all.

Grounded example fixtures: this module's own test file builds several small
synthetic `command.txt`-style files inline (never real project content,
matching `test_de_command_style_learning.py`'s own precedent), covering a
uniform two-subsystem system, a genuinely conflicting separator convention
between two subsystems, a partial-evidence AMBIGUOUS case, and the total
absence of any evidence for a facet across every subsystem supplied.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Union

from dv_harness.de_command_style_learning import CommandStyleIR, learn_command_style

# --- facet vocabulary --------------------------------------------------------

#: The five facets `CommandStyleIR` carries, in its own field order. This
#: module composes exactly these five and no others -- it invents no new
#: style facet of its own.
FACET_NAMES: tuple = (
    "separator_convention",
    "argument_format",
    "comment_format",
    "phase_markers",
    "ordering_rules",
)

#: Each facet's own real "no evidence found" token, exactly as
#: `de_command_style_learning.py` emits it -- read from that module's
#: source rather than re-guessed, since two of the five facets
#: (`comment_format`, `phase_markers`) use `NOT_FOUND` while the other
#: three use `NOT_AVAILABLE`. A future drift between the two modules'
#: vocabularies is caught at import by `_assert_absence_tokens_current()`
#: below rather than silently producing a wrong composite.
_ABSENCE_TOKEN: Dict[str, str] = {
    "separator_convention": "NOT_AVAILABLE",
    "argument_format": "NOT_AVAILABLE",
    "comment_format": "NOT_FOUND",
    "phase_markers": "NOT_FOUND",
    "ordering_rules": "NOT_AVAILABLE",
}


def _assert_absence_tokens_current() -> None:
    """Verify `_ABSENCE_TOKEN` still matches `de_command_style_learning.py`'s
    own real output on an evidence-free file, rather than trusting a
    hand-copied table to stay in sync forever."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as fh:
        fh.write("")
        empty_path = Path(fh.name)
    try:
        style = learn_command_style(empty_path)
        for facet in FACET_NAMES:
            actual = getattr(style, facet)["convention"]
            expected = _ABSENCE_TOKEN[facet]
            if actual != expected:
                raise AssertionError(
                    f"system_command_grammar_ir._ABSENCE_TOKEN[{facet!r}] "
                    f"= {expected!r} no longer matches "
                    f"de_command_style_learning's real empty-file output "
                    f"{actual!r} -- update the table above")
    finally:
        try:
            empty_path.unlink()
        except OSError:
            pass


_assert_absence_tokens_current()

# --- status vocabulary --------------------------------------------------------

FACET_STATUS_UNIFORM = "UNIFORM"
FACET_STATUS_AMBIGUOUS = "AMBIGUOUS"
FACET_STATUS_CONFLICTING = "CONFLICTING"
FACET_STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
FACET_STATUSES: tuple = (
    FACET_STATUS_UNIFORM, FACET_STATUS_AMBIGUOUS,
    FACET_STATUS_CONFLICTING, FACET_STATUS_NOT_AVAILABLE,
)

# The system-level verdict reuses the identical four-value vocabulary --
# there is exactly one status vocabulary in this module, not two.
SYSTEM_STATUS_UNIFORM = FACET_STATUS_UNIFORM
SYSTEM_STATUS_AMBIGUOUS = FACET_STATUS_AMBIGUOUS
SYSTEM_STATUS_CONFLICTING = FACET_STATUS_CONFLICTING
SYSTEM_STATUS_NOT_AVAILABLE = FACET_STATUS_NOT_AVAILABLE
SYSTEM_STATUSES: tuple = FACET_STATUSES


# --- data shapes --------------------------------------------------------------

@dataclass
class FacetGrammar:
    """One composed facet (e.g. `separator_convention`) across every
    subsystem supplied. `system_convention` is the single agreed value
    when `status` is UNIFORM or AMBIGUOUS (real evidence, cited honestly
    even when not system-wide confirmed); it is `None` whenever `status`
    is CONFLICTING or NOT_AVAILABLE -- this module never fabricates a
    system-wide answer those two statuses explicitly say does not exist.
    """
    facet: str
    status: str
    system_convention: Optional[str] = None
    subsystem_conventions: dict = field(default_factory=dict)
    evidenced_subsystems: list = field(default_factory=list)
    absent_subsystems: list = field(default_factory=list)
    distinct_conventions: dict = field(default_factory=dict)
    basis: str = ""


@dataclass
class SystemCommandGrammarIR:
    """The composed system-level grammar over every subsystem supplied.
    `system_status` is CONFLICTING/AMBIGUOUS the instant any one facet is,
    else UNIFORM once at least one facet has real, agreeing evidence, else
    NOT_AVAILABLE only when every facet has none -- see the module
    docstring's WORST-WINS COMPOSITE GATE section for the full rule.
    """
    system_status: str
    subsystem_ids: list = field(default_factory=list)
    facets: dict = field(default_factory=dict)  # facet_name -> FacetGrammar
    source_files: dict = field(default_factory=dict)  # subsystem_id -> path
    basis: str = ""


class SystemCommandGrammarError(ValueError):
    """A caller-supplied subsystem style record could not be read at all
    (malformed shape) -- distinct from a subsystem legitimately reporting
    NO_EVIDENCE for a facet, which is not an error, just an absence."""


# --- composition ----------------------------------------------------------


def _get_facet(style: Union[CommandStyleIR, Mapping], facet_name: str) -> dict:
    """Read one facet dict off a subsystem's own style record, accepting
    either a real `CommandStyleIR` instance (the direct
    `learn_command_style()` result) or an already-serialized plain dict
    (e.g. `analyze_de_command_file(...)["style"]`, or a record read back
    from JSON) -- both are real ways a caller legitimately already holds
    this evidence in this codebase.
    """
    if isinstance(style, CommandStyleIR):
        facet = getattr(style, facet_name, None)
    elif isinstance(style, Mapping):
        facet = style.get(facet_name)
    else:
        raise SystemCommandGrammarError(
            f"subsystem style record must be a CommandStyleIR instance or a "
            f"mapping, got {type(style).__name__}")
    if facet is None:
        return {}
    if not isinstance(facet, Mapping):
        raise SystemCommandGrammarError(
            f"subsystem style record's {facet_name!r} facet must itself be a "
            f"mapping, got {type(facet).__name__}")
    return dict(facet)


def _source_file(style: Union[CommandStyleIR, Mapping]) -> str:
    if isinstance(style, CommandStyleIR):
        return style.source_file
    if isinstance(style, Mapping):
        return str(style.get("source_file") or "")
    return ""


def _compose_facet(
    facet_name: str, subsystem_styles: Mapping[str, Union[CommandStyleIR, Mapping]],
) -> FacetGrammar:
    absence_token = _ABSENCE_TOKEN[facet_name]
    subsystem_conventions: Dict[str, Optional[str]] = {}
    evidenced: Dict[str, str] = {}
    absent: List[str] = []

    for sid in sorted(subsystem_styles.keys()):
        facet_dict = _get_facet(subsystem_styles[sid], facet_name)
        convention = facet_dict.get("convention")
        subsystem_conventions[sid] = convention
        if convention is None or convention == absence_token:
            absent.append(sid)
        else:
            evidenced[sid] = convention

    if not evidenced:
        return FacetGrammar(
            facet=facet_name, status=FACET_STATUS_NOT_AVAILABLE,
            system_convention=None, subsystem_conventions=subsystem_conventions,
            evidenced_subsystems=[], absent_subsystems=list(absent),
            distinct_conventions={},
            basis=(f"no subsystem provided real evidence for {facet_name}; "
                   f"{len(absent)} subsystem(s) reported the facet's own "
                   f"absence token ({absence_token!r}) or nothing at all"),
        )

    distinct_conventions: Dict[str, list] = {}
    for sid, convention in evidenced.items():
        distinct_conventions.setdefault(convention, []).append(sid)

    if len(distinct_conventions) == 1:
        (only_convention,) = distinct_conventions.keys()
        if absent:
            return FacetGrammar(
                facet=facet_name, status=FACET_STATUS_AMBIGUOUS,
                system_convention=only_convention,
                subsystem_conventions=subsystem_conventions,
                evidenced_subsystems=sorted(evidenced), absent_subsystems=list(absent),
                distinct_conventions=distinct_conventions,
                basis=(f"{len(evidenced)} subsystem(s) with real evidence agree on "
                       f"{only_convention!r}, but {len(absent)} subsystem(s) "
                       f"({', '.join(absent)}) have no evidence for this facet at "
                       f"all -- system-wide uniformity is not confirmed"),
            )
        return FacetGrammar(
            facet=facet_name, status=FACET_STATUS_UNIFORM,
            system_convention=only_convention,
            subsystem_conventions=subsystem_conventions,
            evidenced_subsystems=sorted(evidenced), absent_subsystems=[],
            distinct_conventions=distinct_conventions,
            basis=f"all {len(evidenced)} subsystem(s) with real evidence agree on "
                  f"{only_convention!r}",
        )

    # Two or more DISTINCT real conventions among subsystems that each have
    # real evidence -- a genuine disagreement. Never picked between.
    detail = "; ".join(
        f"{convention!r} <- {sorted(sids)}"
        for convention, sids in sorted(distinct_conventions.items()))
    return FacetGrammar(
        facet=facet_name, status=FACET_STATUS_CONFLICTING,
        system_convention=None,
        subsystem_conventions=subsystem_conventions,
        evidenced_subsystems=sorted(evidenced), absent_subsystems=list(absent),
        distinct_conventions=distinct_conventions,
        basis=(f"{len(distinct_conventions)} distinct conventions found among "
               f"subsystems with real evidence for {facet_name}: {detail}"),
    )


def build_system_command_grammar_ir(
    subsystem_styles: Mapping[str, Union[CommandStyleIR, Mapping]],
) -> SystemCommandGrammarIR:
    """Compose N subsystems' own `CommandStyleIR` records (or their
    already-serialized dict form) into one `SystemCommandGrammarIR`.

    `subsystem_styles` maps a subsystem id to that subsystem's own style
    record. Read-only over its inputs; builds no file, runs no build, and
    reuses `de_command_style_learning`'s own pattern-detected facets
    verbatim rather than re-deriving any of them.
    """
    if not subsystem_styles:
        return SystemCommandGrammarIR(
            system_status=SYSTEM_STATUS_NOT_AVAILABLE,
            subsystem_ids=[], facets={}, source_files={},
            basis="no subsystem CommandStyleIR records were supplied",
        )

    subsystem_ids = sorted(subsystem_styles.keys())
    facets: Dict[str, FacetGrammar] = {
        facet_name: _compose_facet(facet_name, subsystem_styles)
        for facet_name in FACET_NAMES
    }
    source_files = {sid: _source_file(subsystem_styles[sid]) for sid in subsystem_ids}

    statuses = [f.status for f in facets.values()]
    conflicting = [f.facet for f in facets.values() if f.status == FACET_STATUS_CONFLICTING]
    ambiguous = [f.facet for f in facets.values() if f.status == FACET_STATUS_AMBIGUOUS]
    not_available = [f.facet for f in facets.values() if f.status == FACET_STATUS_NOT_AVAILABLE]
    uniform = [f.facet for f in facets.values() if f.status == FACET_STATUS_UNIFORM]

    # Worst-wins, but a per-facet NOT_AVAILABLE (every subsystem confirmed
    # it genuinely does not use that facet) is never treated as a defect
    # dragging a clean composite down -- see the module docstring's own
    # WORST-WINS COMPOSITE GATE section for why this differs from a plain
    # max-severity fold.
    if conflicting:
        system_status = FACET_STATUS_CONFLICTING
        basis = (f"worst-wins over {len(FACET_NAMES)} facets: "
                  f"{len(conflicting)} facet(s) genuinely CONFLICT across "
                  f"subsystems -- {conflicting}")
    elif ambiguous:
        system_status = FACET_STATUS_AMBIGUOUS
        basis = (f"worst-wins over {len(FACET_NAMES)} facets: no facet "
                  f"CONFLICTS, but {len(ambiguous)} facet(s) are AMBIGUOUS "
                  f"(agreed among evidenced subsystems, unconfirmed for the "
                  f"whole system) -- {ambiguous}")
    elif all(s == FACET_STATUS_NOT_AVAILABLE for s in statuses):
        system_status = FACET_STATUS_NOT_AVAILABLE
        basis = (f"no subsystem provided real evidence for any of the "
                  f"{len(FACET_NAMES)} facets")
    elif not_available:
        system_status = FACET_STATUS_UNIFORM
        basis = (f"every facet with real evidence is UNIFORM -- {uniform}; "
                  f"{len(not_available)} facet(s) ({not_available}) have no "
                  f"evidence anywhere and are excluded from this verdict "
                  f"rather than treated as a defect")
    else:
        system_status = FACET_STATUS_UNIFORM
        basis = (f"every one of {len(FACET_NAMES)} facets is UNIFORM across "
                  f"all {len(subsystem_ids)} subsystem(s) with real evidence")

    return SystemCommandGrammarIR(
        system_status=system_status, subsystem_ids=subsystem_ids,
        facets=facets, source_files=source_files, basis=basis,
    )


def learn_system_command_grammar(
    subsystem_command_files: Mapping[str, Union[str, Path]],
) -> SystemCommandGrammarIR:
    """Read one real DE `command.txt`-style file per subsystem via
    `de_command_style_learning.learn_command_style()` (reused, never
    re-parsed) and compose the resulting `CommandStyleIR`s into one
    `SystemCommandGrammarIR`.
    """
    styles = {
        sid: learn_command_style(Path(path))
        for sid, path in subsystem_command_files.items()
    }
    return build_system_command_grammar_ir(styles)


# --- rendering ----------------------------------------------------------------


def system_command_grammar_to_dict(ir: SystemCommandGrammarIR) -> dict:
    """JSON-friendly plain-dict rendering (no dataclass instances)."""
    return asdict(ir)


def format_system_command_grammar(ir: SystemCommandGrammarIR) -> str:
    """Human-readable rendering of one `SystemCommandGrammarIR`."""
    lines = [
        f"System command grammar ({len(ir.subsystem_ids)} subsystem(s)): "
        f"{ir.system_status}",
        f"  subsystems: {', '.join(ir.subsystem_ids) or '(none)'}",
    ]
    for facet_name in FACET_NAMES:
        f = ir.facets.get(facet_name)
        if f is None:
            continue
        convention = f.system_convention if f.system_convention is not None else "(none)"
        lines.append(f"  {facet_name}: {f.status} -> {convention}")
        if f.status in (FACET_STATUS_CONFLICTING, FACET_STATUS_AMBIGUOUS):
            for sid in sorted(f.subsystem_conventions):
                lines.append(f"      {sid}: {f.subsystem_conventions[sid]!r}")
    lines.append(f"  basis: {ir.basis}")
    return "\n".join(lines)


# --- standalone front door (disclosed residual: no `dv-harness` CLI verb) ----
#
# Per this project's own house rule 8, this task does not edit `cli.py`
# (a large file under concurrent edit pressure from many items in this same
# batch). `python -m dv_harness.system_command_grammar_ir` is the front
# door instead, matching the disclosed choice several recent modules in
# this codebase already made (e.g. `power_intent.py`, `golden_scenario.py`).


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.system_command_grammar_ir",
        description="Compose several subsystems' own command.txt style "
                     "learning into one system-level grammar verdict.")
    parser.add_argument(
        "--subsystem", action="append", default=[], metavar="ID=PATH",
        help="one subsystem's id and its real command.txt-style file path, "
             "e.g. --subsystem usb0=usb0/command.txt (repeatable)")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if not args.subsystem:
        print("error: at least one --subsystem ID=PATH is required", file=sys.stderr)
        return 2
    files: Dict[str, str] = {}
    for entry in args.subsystem:
        if "=" not in entry:
            print(f"error: --subsystem entry {entry!r} must be ID=PATH", file=sys.stderr)
            return 2
        sid, _, path = entry.partition("=")
        files[sid.strip()] = path.strip()

    ir = learn_system_command_grammar(files)
    if args.json:
        print(json.dumps(system_command_grammar_to_dict(ir), indent=2, sort_keys=True))
    else:
        print(format_system_command_grammar(ir))

    if ir.system_status == SYSTEM_STATUS_CONFLICTING:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
