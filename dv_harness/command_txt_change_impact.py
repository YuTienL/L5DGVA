"""dv_harness/command_txt_change_impact.py -- semantic diff between two
DE command.txt / command-registry snapshots (2026-09-06).

WHAT THIS CLOSES. The Engineering Discipline Rules' "command.txt change-impact
check" (`CLAUDE.md`, restated from `.claude/skills/CORE/command-inventory/
SKILL.md`'s "Change-Impact Check") already requires re-checking a modified
`.dv-workflow/command_inventory.csv` against existing command.txt/scenario
cases after every generator/schema change. That check is a FILE-PRESENCE /
regression-selection question ("which COMMAND_IDs are potentially affected,
re-run their tests"), answered by `change_impact.py`'s real git-diff-driven
selection machinery over RTL/requirement traceability. It has never asked the
narrower, DE-command-specific question this module answers: given two actual
SNAPSHOTS of a DE command registry (one before, one after some edit to the
generator/schema/command.txt corpus), which individual commands' own
DEFINITIONS changed, and how -- same arguments and same effect (UNCHANGED),
same effect but a different call signature (ARGUMENT_CHANGE), a different
underlying effect regardless of signature (SEMANTIC_CHANGE), a command that
did not exist before (NEW_COMMAND) or no longer exists (REMOVED_COMMAND), one
explicitly retired (DEPRECATED), or one this module genuinely cannot classify
from the evidence it was given (AMBIGUOUS). Nothing in this repo answered
that: a full-repo grep for `command_txt_change_impact`/`DECommandRegistryIR`/
a per-dispatch command-diff vocabulary matched nothing before this file.

WHERE THE INPUT COMES FROM, AND WHY IT IS DUCK-TYPED HERE. A concurrent batch
in this same session owns `dv_harness/de_command_style_learning.py`, whose
real `DECommandRegistryIR`-shaped output this module is meant to consume. Per
this batch's own file-safety scope, that module is neither imported nor
touched here -- so every snapshot this module reads is accepted as a plain
dict/list (a JSON-shaped registry snapshot), never as an imported class
instance, and every field is resolved through a small alias table rather than
one fixed attribute name. This is deliberate duck-typing, not laziness: a
producer built by a different, concurrently-running effort may spell a
command's identifier `command_id`, `id`, `name` or `command`; this module
tries each in turn and records, per command, which fields it could and could
not resolve on each side, so a schema the producer has not yet stabilized
never gets silently misread as "unchanged".

WHAT PATTERN THIS FOLLOWS. A second concurrent batch owns
`dv_harness/spec_vplan_delta.py`, whose own job is described as the semantic
diff between two structured before/after documents (spec vs. vPlan) with a
graded, evidence-grounded verdict per item. That module is likewise neither
imported nor touched here -- this module reimplements the SAME PATTERN (worst-
first precedence over a small set of independently-checkable facets, never
guessing a verdict a facet's own evidence cannot support) with its own
parallel logic, because the two modules diff structurally different things
(a spec/vPlan item pair vs. a DE command registry entry pair) and sharing code
between them would either force one shape onto the other or import a module
this batch's own scope forbids.

WHAT THIS MODULE DOES NOT DO, stated rather than left implicit. It never
fabricates a rename: a command whose id disappears from the old snapshot and
whose (differently-named) replacement appears in the new one is reported as
one REMOVED_COMMAND and one NEW_COMMAND, never as a guessed rename -- matching
two differently-spelled ids by similarity would be exactly the invented
linkage the Evidence Truth Rule forbids. It never runs a build, a regression,
or an LSF submission, and it decides nothing about VIP API validity, RTL
content, protocol timing or interrupt priority -- see
`.claude/skills/CORE/pattern-architecture/SKILL.md` and `branch-mapper/
SKILL.md` for the real `block`/`branch_a*`/`branch_fw`/`branch_b*` task-
composition vocabulary and the real AMBA M x N arbitration prose this module
is scoped around but never invents content for; a `semantic_role`/
`branch_role` field found in a snapshot is compared as opaque text, never
validated against that vocabulary, because doing so would require content
this module was never given.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# -- the seven-value classification vocabulary ------------------------------
#
# Deliberately its OWN vocabulary, disjoint from `dv_harness.models.Status`
# (the harness's stage-gate verification verdict) -- checked, not merely
# claimed, by `assert_no_verification_verdict_vocabulary()` below. It is also
# a DIFFERENT, more granular per-dispatch vocabulary from
# `loop_budget.FailureType` (a retry-classification taxonomy for a FAILED
# stage's own cause), used here only as a contrast, never merged with or
# imported from.

UNCHANGED = "UNCHANGED"
ARGUMENT_CHANGE = "ARGUMENT_CHANGE"
SEMANTIC_CHANGE = "SEMANTIC_CHANGE"
NEW_COMMAND = "NEW_COMMAND"
REMOVED_COMMAND = "REMOVED_COMMAND"
DEPRECATED = "DEPRECATED"
AMBIGUOUS = "AMBIGUOUS"

COMMAND_DIFF_STATUSES = frozenset({
    UNCHANGED, ARGUMENT_CHANGE, SEMANTIC_CHANGE, NEW_COMMAND,
    REMOVED_COMMAND, DEPRECATED, AMBIGUOUS,
})

#: Statuses that mean "a human/downstream re-verification pass should look at
#: this command" -- everything except a plain UNCHANGED or a brand-new
#: command with nothing yet to compare against.
CONCERNING_STATUSES = frozenset({
    ARGUMENT_CHANGE, SEMANTIC_CHANGE, REMOVED_COMMAND, DEPRECATED, AMBIGUOUS,
})


class CommandTxtChangeImpactError(Exception):
    """Raised for a snapshot this module cannot honestly interpret at all --
    never raised merely because a registry is legitimately empty."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's COMMAND_DIFF_STATUSES must share no token with
    `dv_harness.models.Status`, the harness's verification-verdict
    vocabulary, and no token with `dv_harness.loop_budget.FailureType`
    either (the neighbouring per-dispatch taxonomy this module is a
    deliberately different, more granular vocabulary from). Checked here
    rather than only claimed in the docstring above, the same discipline
    `capability_evolution.assert_no_verification_verdict_vocabulary()`
    already applies to its own three decision vocabularies."""
    from . import models
    verdict_tokens = {s.value for s in models.Status}
    overlap = COMMAND_DIFF_STATUSES & verdict_tokens
    if overlap:
        raise AssertionError(
            "command_txt_change_impact vocabulary collides with "
            f"models.Status: {sorted(overlap)}")
    try:
        from . import loop_budget
    except Exception:
        return
    failure_tokens = {t.value for t in loop_budget.FailureType}
    overlap2 = COMMAND_DIFF_STATUSES & failure_tokens
    if overlap2:
        raise AssertionError(
            "command_txt_change_impact vocabulary collides with "
            f"loop_budget.FailureType: {sorted(overlap2)}")


# -- duck-typed field resolution --------------------------------------------
#
# Every alias tuple below is a GUESS AT SPELLING, not a schema this module
# asserts is correct. A snapshot whose producer used none of these spellings
# for a given logical field reads as that field being absent on that side --
# never as the field having some default value -- which is what lets
# `_classify()` below tell "this field genuinely did not change" apart from
# "this module could not find this field to compare it".

ID_ALIASES: Tuple[str, ...] = ("command_id", "id", "name", "command", "cmd_id", "cmd")
PARAMETER_ALIASES: Tuple[str, ...] = ("parameters", "params", "args", "arguments", "parameter_list")
SOURCE_ALIASES: Tuple[str, ...] = ("source", "source_file", "file", "path")
DEPRECATED_FLAG_ALIASES: Tuple[str, ...] = ("deprecated",)
DEPRECATED_STATUS_ALIASES: Tuple[str, ...] = ("status", "state", "lifecycle")

#: Fields whose disagreement means the command's underlying EFFECT changed,
#: never merely its call signature. `protocol` is included because a command
#: retargeted to a different protocol is not the "same command, new
#: arguments" case ARGUMENT_CHANGE exists for.
SEMANTIC_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "protocol": ("protocol",),
    "semantic_role": ("semantic_role", "branch_role", "role", "layer", "branch_tag", "task_layer"),
    "handler": ("handler", "handler_task", "task", "handler_name"),
    "vip_sequence": ("vip_sequence", "sequence", "vip_seq", "sequence_name"),
    "effects": ("effects", "behavior", "description", "semantics", "effect_summary"),
}

_DEPRECATED_STATUS_TOKENS = frozenset({"deprecated", "obsolete", "retired"})


def _resolve(record: Dict[str, Any], aliases: Sequence[str]) -> Tuple[bool, Any]:
    """Return (found, value) for the first alias present as a KEY in
    `record` -- a key present with value None/"" is still `found=True`
    (an explicit empty is real evidence); a key absent from every alias is
    `found=False` (this module has no evidence for this field on this
    side)."""
    for key in aliases:
        if key in record:
            return True, record[key]
    return False, None


def _normalize_scalar(value: Any) -> Any:
    """Whitespace-only normalization for string values: collapses internal
    whitespace runs and strips ends, so re-extracting the identical free-text
    `effects`/`description` with different line-wrapping does not read as a
    SEMANTIC_CHANGE. Deliberately does NOT lowercase or otherwise alter
    content -- a real casing/content difference in a handler or VIP sequence
    name is exactly the fact this module exists to surface, never to hide."""
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _normalize_parameter(entry: Any) -> Tuple[Optional[str], Any, Any, Any]:
    """A parameter entry may be a bare name (string) or a descriptor dict
    carrying name/type/default/required under any of a few common spellings.
    Normalizes to (name, type, default, required); an entry that is neither
    is stringified as its own "name" with the other three fields None rather
    than raising, so one malformed entry does not abort a whole diff."""
    if isinstance(entry, str):
        return (entry, None, None, None)
    if isinstance(entry, dict):
        name = entry.get("name")
        if name is None:
            name = entry.get("param")
        if name is None:
            name = entry.get("id")
        type_ = entry.get("type")
        if "default" in entry:
            default = entry.get("default")
        else:
            default = entry.get("default_value")
        required = entry.get("required")
        return (name, _normalize_scalar(type_), _normalize_scalar(default), required)
    return (repr(entry), None, None, None)


def _diff_parameter_lists(old_list: Any, new_list: Any) -> List[str]:
    """Positional comparison -- parameter ORDER is load-bearing for a
    command.txt macro/task call, so this never sorts by name before
    comparing. Returns one finding string per position that differs; an
    empty return means the two lists are positionally identical."""
    if not isinstance(old_list, list) or not isinstance(new_list, list):
        return ["parameters field is not a list on at least one side -- "
                "cannot compare positionally"]
    old_norm = [_normalize_parameter(p) for p in old_list]
    new_norm = [_normalize_parameter(p) for p in new_list]
    findings: List[str] = []
    for i in range(max(len(old_norm), len(new_norm))):
        o = old_norm[i] if i < len(old_norm) else None
        n = new_norm[i] if i < len(new_norm) else None
        if o is None:
            findings.append(f"parameter added at position {i}: {n[0]!r}")
        elif n is None:
            findings.append(f"parameter removed at position {i}: {o[0]!r}")
        elif o != n:
            parts = []
            if o[0] != n[0]:
                parts.append(f"name {o[0]!r} -> {n[0]!r}")
            if o[1] != n[1]:
                parts.append(f"type {o[1]!r} -> {n[1]!r}")
            if o[2] != n[2]:
                parts.append(f"default {o[2]!r} -> {n[2]!r}")
            if o[3] != n[3]:
                parts.append(f"required {o[3]!r} -> {n[3]!r}")
            findings.append(f"parameter at position {i}: " + "; ".join(parts))
    return findings


def _is_deprecated_record(record: Dict[str, Any]) -> Tuple[bool, bool]:
    """Returns (found_any_lifecycle_field, is_deprecated). A record carrying
    neither a `deprecated` flag nor a status/state/lifecycle field reports
    found_any=False -- this module never assumes "not deprecated" from
    silence, it reports it could not check."""
    found_any = False
    for key in DEPRECATED_FLAG_ALIASES:
        if key in record:
            found_any = True
            if bool(record[key]):
                return True, True
    for key in DEPRECATED_STATUS_ALIASES:
        if key in record:
            found_any = True
            val = record[key]
            if isinstance(val, str) and val.strip().lower() in _DEPRECATED_STATUS_TOKENS:
                return True, True
    return found_any, False


def _source_of(record: Dict[str, Any]) -> Optional[str]:
    found, val = _resolve(record, SOURCE_ALIASES)
    return val if found and val is not None else None


# -- snapshot container parsing ----------------------------------------------

#: Common container-key spellings for "the list of command records" inside a
#: wrapping dict. Tried in order; the first present list wins.
_CONTAINER_KEYS: Tuple[str, ...] = ("commands", "command_registry", "registry", "entries", "items")


def _extract_records(snapshot: Any) -> List[Tuple[Optional[str], Dict[str, Any]]]:
    """Returns a list of (mapping_key_or_None, record) pairs from one of three
    accepted DECommandRegistryIR-shaped container forms: a bare list of
    command dicts, a wrapping dict carrying one of `_CONTAINER_KEYS` as a
    list, or a dict that is ITSELF an id -> record mapping (every value a
    dict, none of the wrapper keys present). Raises for anything else --
    a string/int/None snapshot is not a registry this module can honestly
    read, and returning an empty list for it would misreport a malformed
    input as a legitimately empty registry."""
    if isinstance(snapshot, list):
        out = []
        for r in snapshot:
            if isinstance(r, dict):
                out.append((None, r))
            else:
                out.append((None, {"_unindexable_raw": repr(r)[:200]}))
        return out
    if isinstance(snapshot, dict):
        for key in _CONTAINER_KEYS:
            val = snapshot.get(key)
            if isinstance(val, list):
                out = []
                for r in val:
                    if isinstance(r, dict):
                        out.append((None, r))
                    else:
                        out.append((None, {"_unindexable_raw": repr(r)[:200]}))
                return out
        if snapshot and all(isinstance(v, dict) for v in snapshot.values()):
            return [(k, v) for k, v in snapshot.items()]
        if not snapshot:
            return []
        # A dict with no recognised container key and values that are not
        # all dicts is not a shape this module can honestly parse.
        raise CommandTxtChangeImpactError(
            "UNRECOGNIZED_SNAPSHOT_SHAPE: dict has none of "
            f"{_CONTAINER_KEYS} as a list and is not an id->record mapping "
            f"(keys={sorted(snapshot.keys())})")
    raise CommandTxtChangeImpactError(
        f"UNRECOGNIZED_SNAPSHOT_SHAPE: expected a list or dict, got "
        f"{type(snapshot).__name__}")


def _index_snapshot(snapshot: Any) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], frozenset]:
    """Builds {command_id: record} plus a list of records this module could
    not index (never silently dropped) and a set of ids that appeared more
    than once in this one snapshot (a real data-quality fact, reported as
    AMBIGUOUS for that id rather than silently keeping "whichever record
    happened to be seen last")."""
    raw = _extract_records(snapshot)
    index: Dict[str, Dict[str, Any]] = {}
    seen_twice: set = set()
    unindexed: List[Dict[str, Any]] = []
    for mapping_key, record in raw:
        if "_unindexable_raw" in record and len(record) == 1:
            unindexed.append({"reason": "record is not a dict",
                               "raw": record["_unindexable_raw"]})
            continue
        cid = mapping_key
        if cid is None:
            found, val = _resolve(record, ID_ALIASES)
            cid = val if found and val not in (None, "") else None
        if cid is None:
            unindexed.append({
                "reason": "no command identifier resolvable via "
                          f"{ID_ALIASES}",
                "record_keys": sorted(record.keys()),
            })
            continue
        cid = str(cid)
        if cid in index:
            seen_twice.add(cid)
            continue
        index[cid] = record
    return index, unindexed, frozenset(seen_twice)


# -- per-command classification ----------------------------------------------

@dataclass
class CommandDiffEntry:
    command_id: str
    verdict: str
    findings: List[str] = field(default_factory=list)
    old_present: bool = False
    new_present: bool = False
    old_source: Optional[str] = None
    new_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_command_diff(command_id: str, old_rec: Dict[str, Any],
                           new_rec: Dict[str, Any]) -> CommandDiffEntry:
    """Classifies one command present in BOTH snapshots. Precedence,
    worst-first over what a lifecycle signal, then real content, actually
    supports -- mirroring `waiver_store.derive_status()`'s "a stored status
    is wrong the instant the underlying fact moves, so derive it every time"
    discipline applied to a command registry instead of a waiver ledger:

    1. Newly marked deprecated in the new snapshot, or still marked
       deprecated in both -> DEPRECATED (an explicit lifecycle signal
       outranks whatever else also changed underneath it).
    2. Otherwise, a real difference in any SEMANTIC_FIELD_ALIASES facet
       (including a reinstatement out of deprecation, folded in here rather
       than given a status of its own -- this vocabulary has no
       "un-deprecated" value, and the underlying facet difference is what
       actually changed) -> SEMANTIC_CHANGE.
    3. Otherwise, a real positional difference in the parameter list ->
       ARGUMENT_CHANGE.
    4. Otherwise, any facet this module could not compare on both sides
       (present in one snapshot's record, absent from the other's) ->
       AMBIGUOUS -- reported rather than silently assumed unchanged.
    5. Otherwise -> UNCHANGED.
    """
    dep_found_old, dep_old = _is_deprecated_record(old_rec)
    dep_found_new, dep_new = _is_deprecated_record(new_rec)

    semantic_diffs: List[str] = []
    incomparable: List[str] = []
    argument_diffs: List[str] = []

    for logical_field, aliases in SEMANTIC_FIELD_ALIASES.items():
        found_old, val_old = _resolve(old_rec, aliases)
        found_new, val_new = _resolve(new_rec, aliases)
        if found_old and found_new:
            norm_old, norm_new = _normalize_scalar(val_old), _normalize_scalar(val_new)
            if norm_old != norm_new:
                semantic_diffs.append(f"{logical_field} changed: {norm_old!r} -> {norm_new!r}")
        elif found_old != found_new:
            side = "old" if found_old else "new"
            incomparable.append(
                f"{logical_field} present in the {side} snapshot's record only "
                "(schema gap, not a confirmed change)")

    found_params_old, params_old = _resolve(old_rec, PARAMETER_ALIASES)
    found_params_new, params_new = _resolve(new_rec, PARAMETER_ALIASES)
    if found_params_old and found_params_new:
        argument_diffs.extend(_diff_parameter_lists(params_old, params_new))
    elif found_params_old != found_params_new:
        side = "old" if found_params_old else "new"
        incomparable.append(
            f"parameters present in the {side} snapshot's record only "
            "(schema gap, not a confirmed change)")

    old_source, new_source = _source_of(old_rec), _source_of(new_rec)
    common = dict(command_id=command_id, old_present=True, new_present=True,
                  old_source=old_source, new_source=new_source)

    if dep_new and not dep_old:
        findings = ["newly marked deprecated in the new snapshot"]
        findings.extend(semantic_diffs)
        findings.extend(argument_diffs)
        findings.extend(f"[unresolved: {x}]" for x in incomparable)
        return CommandDiffEntry(verdict=DEPRECATED, findings=findings, **common)
    if dep_old and dep_new:
        findings = ["remains marked deprecated in both snapshots"]
        findings.extend(semantic_diffs)
        findings.extend(argument_diffs)
        findings.extend(f"[unresolved: {x}]" for x in incomparable)
        return CommandDiffEntry(verdict=DEPRECATED, findings=findings, **common)
    if dep_old and not dep_new:
        semantic_diffs = ["no longer marked deprecated in the new snapshot (reinstated)"] + semantic_diffs

    if semantic_diffs:
        findings = list(semantic_diffs)
        findings.extend(argument_diffs)
        findings.extend(f"[unresolved: {x}]" for x in incomparable)
        return CommandDiffEntry(verdict=SEMANTIC_CHANGE, findings=findings, **common)
    if argument_diffs:
        findings = list(argument_diffs)
        findings.extend(f"[unresolved: {x}]" for x in incomparable)
        return CommandDiffEntry(verdict=ARGUMENT_CHANGE, findings=findings, **common)
    if incomparable:
        return CommandDiffEntry(verdict=AMBIGUOUS, findings=list(incomparable), **common)
    return CommandDiffEntry(
        verdict=UNCHANGED,
        findings=["no differences detected across every field this module could resolve on both sides"],
        **common)


# -- top-level registry diff -------------------------------------------------

def diff_command_registries(old_snapshot: Any, new_snapshot: Any) -> Dict[str, Any]:
    """Semantic diff between two DECommandRegistryIR-shaped snapshots
    (duck-typed dicts/lists -- see module docstring). Returns a report dict
    with one entry per command_id seen on either side, a status summary, and
    honest diagnostics for any record neither snapshot could index. Never
    writes anything, never runs anything, and never guesses a rename."""
    old_index, old_unindexed, old_dupes = _index_snapshot(old_snapshot)
    new_index, new_unindexed, new_dupes = _index_snapshot(new_snapshot)

    all_ids = sorted(set(old_index) | set(new_index))
    entries: List[CommandDiffEntry] = []
    for cid in all_ids:
        in_old, in_new = cid in old_index, cid in new_index
        if in_old and not in_new:
            entries.append(CommandDiffEntry(
                command_id=cid, verdict=REMOVED_COMMAND,
                findings=["command present in the old snapshot, absent from the new snapshot"],
                old_present=True, new_present=False,
                old_source=_source_of(old_index[cid])))
            continue
        if in_new and not in_old:
            entries.append(CommandDiffEntry(
                command_id=cid, verdict=NEW_COMMAND,
                findings=["command present in the new snapshot, absent from the old snapshot"],
                old_present=False, new_present=True,
                new_source=_source_of(new_index[cid])))
            continue
        if cid in old_dupes or cid in new_dupes:
            findings = []
            if cid in old_dupes:
                findings.append("duplicate command_id encountered more than once in the "
                                "old snapshot; diffing skipped for this id")
            if cid in new_dupes:
                findings.append("duplicate command_id encountered more than once in the "
                                "new snapshot; diffing skipped for this id")
            entries.append(CommandDiffEntry(
                command_id=cid, verdict=AMBIGUOUS, findings=findings,
                old_present=True, new_present=True))
            continue
        entries.append(classify_command_diff(cid, old_index[cid], new_index[cid]))

    summary = {status: 0 for status in COMMAND_DIFF_STATUSES}
    for e in entries:
        summary[e.verdict] += 1

    return {
        "entries": [e.to_dict() for e in entries],
        "summary": summary,
        "old_command_count": len(old_index),
        "new_command_count": len(new_index),
        "old_unindexed_records": old_unindexed,
        "new_unindexed_records": new_unindexed,
        "concerning_count": sum(summary[s] for s in CONCERNING_STATUSES),
    }


def render_command_impact_markdown(report: Dict[str, Any]) -> str:
    """Renders `diff_command_registries()`'s report as one markdown table
    plus a summary block, reusing `connectivity.render_markdown_table()` --
    this repo's own single parameterized markdown-table renderer -- rather
    than a fourth hand-rolled `"| " + " | ".join(...)` loop."""
    from .connectivity import render_markdown_table

    columns = [("command_id", "Command ID"), ("verdict", "Verdict"),
               ("findings_text", "Findings")]
    rows = []
    for e in report["entries"]:
        rows.append({
            "command_id": e["command_id"],
            "verdict": e["verdict"],
            "findings_text": "; ".join(e["findings"]) if e["findings"] else "",
        })
    table = render_markdown_table(
        columns, rows, empty_note="(no commands found in either snapshot)")

    lines = [table, "", "**Summary**"]
    for status in sorted(report["summary"]):
        lines.append(f"- {status}: {report['summary'][status]}")
    if report["old_unindexed_records"]:
        lines.append("")
        lines.append(f"**Old snapshot: {len(report['old_unindexed_records'])} unindexed "
                      "record(s)** (present in the snapshot but this module could not "
                      "resolve a command identifier for them):")
        for u in report["old_unindexed_records"]:
            lines.append(f"- {u['reason']}")
    if report["new_unindexed_records"]:
        lines.append("")
        lines.append(f"**New snapshot: {len(report['new_unindexed_records'])} unindexed "
                      "record(s)**:")
        for u in report["new_unindexed_records"]:
            lines.append(f"- {u['reason']}")
    return "\n".join(lines)


# -- ad hoc front door --------------------------------------------------------
#
# There is no `dv-harness` CLI verb for this module: `cli.py` is out of scope
# for this batch (three other batches are concurrently editing files in this
# session). This module is REACHED, not WIRED -- callable directly as
# `python -m dv_harness.command_txt_change_impact`, or by importing
# `diff_command_registries()` from any caller that has two real snapshots.

def execute_verb(old_path: str, new_path: str, *, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for the CLI below and any future `dv-harness`
    wiring. Reads two JSON files, each containing one DECommandRegistryIR-
    shaped snapshot, and returns (text, exit_code): 0 nothing concerning,
    1 at least one ARGUMENT_CHANGE/SEMANTIC_CHANGE/REMOVED_COMMAND/
    DEPRECATED/AMBIGUOUS finding, 2 a snapshot this module could not parse
    or read at all."""
    try:
        old_snapshot = json.loads(Path(old_path).read_text(encoding="utf-8"))
        new_snapshot = json.loads(Path(new_path).read_text(encoding="utf-8"))
    except OSError as e:
        return f"NOT_AVAILABLE: could not read a snapshot file: {e}", 2
    except json.JSONDecodeError as e:
        return f"NOT_AVAILABLE: a snapshot file is not valid JSON: {e}", 2
    try:
        report = diff_command_registries(old_snapshot, new_snapshot)
    except CommandTxtChangeImpactError as e:
        return f"{type(e).__name__}: {e}", 2
    text = json.dumps(report, indent=2) if as_json else render_command_impact_markdown(report)
    code = 1 if report["concerning_count"] else 0
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.command_txt_change_impact",
        description="Semantic diff between two DECommandRegistryIR-shaped DE command "
                    "registry snapshots. Reads two JSON files; runs, builds and "
                    "approves nothing.")
    ap.add_argument("--old", required=True, help="Path to the OLD (before) snapshot JSON file.")
    ap.add_argument("--new", required=True, help="Path to the NEW (after) snapshot JSON file.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.old, a.new, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
