"""dv_harness/system_build_proof.py -- spec section 206 "SYSTEM BUILD & PROOF
AGENT": the SMOKE-PROOF LADDER, driven for real, plus the static SYSTEM MERGE
COLLISION check that section's own responsibility list names.

WHAT WAS ACTUALLY MISSING (re-verified by grep before this module was written,
not restated from an audit):

  - `grep -rn "smoke_proof\\|SMOKE_PROOF\\|system_smoke" --include=*.py .`
    matched NOTHING. No code anywhere executed section 206's ladder
    (Build -> Elaborate -> Boot/Reset/Init -> Shared-Resource-Access ->
    One-Subsystem -> Two-Subsystem-Interaction -> One-End-to-End-Scenario ->
    WAVE=1/fsdbreport -> Scoreboard/Assertion -> SYSTEM_READY).
  - `system_readiness.derive_system_readiness()` is a STATIC METADATA ROLLUP
    and says so in its own docstring ("Build integration at Phase 1 is a
    question about INPUTS, not about a build: no System-Level filelist exists
    to compile"). Its `build_integration` input asks whether each subsystem has
    its own build scripts on disk. That is a real and useful question and it is
    NOT this one: nothing anywhere ever merged the composed sources and asked
    whether they can coexist.
  - `uvm_structural_lint.py` (2026-09-06) lints ONE environment. Its own
    docstring lists "package/import dependencies, duplicate definitions,
    duplicate active drivers" as NOT implemented. A duplicate class or an
    identically-named package across TWO subsystem environments is invisible to
    a per-environment lint by construction.

WHAT THIS MODULE IS NOT
-----------------------
  * It generates NOTHING. No system filelist, no command.txt, no scenario body,
    no shared driver code. SYS-39/40's stop-before-generating-real-system-
    artifacts boundary is untouched: where a rung needs an artifact only SYS-40
    may write, the rung reports NOT_AVAILABLE naming that boundary.
  * It ARBITRATES nothing. The SHARED_RESOURCE_ACCESS rung reads the existing
    Track-B analysis (`system_resource_inventory.real_cross_subsystem_findings()`
    -- the same front door the two real gate scripts and the SoC composer
    already cross-check against) and FAILS the ladder on an unresolved
    active-driver ownership conflict. Picking a winner between two conflicting
    drivers stays a HUMAN decision; SYS-12's preferred model is carried through
    as text for that human and nothing here resolves it.
  * It runs NO simulation and starts NO waveform dump. The WAVE_FSDBREPORT rung
    READS an fsdb the caller already has (via the existing
    `fsdb_report.run_fsdbreport()`); it never enables dumping, which would
    require CLAUDE.md's Waveform Dump User Gate.
  * It never fabricates a PASS. Every rung that needs a tool this environment
    does not have (slang/vcs, a live simv, fsdbreport) reports NOT_AVAILABLE
    with its real reason -- the same convention `connectivity.py`'s own three
    machine gates already established, and reached by CALLING those gates
    rather than by re-implementing them.

THE LADDER, AND WHAT EACH RUNG REALLY RUNS
------------------------------------------
  BUILD                    `analyze_system_merge()` below -- REAL and fully
                           runnable here. Section 206's own "build merge /
                           duplicate package / config_db conflicts /
                           virtual-interface conflict / factory collision"
                           list, decided by a real verible parse of the merged
                           source set.
  ELABORATE                `connectivity.run_gate1_elaboration_check()`, the
                           existing real slang/vcs subprocess wrapper, over the
                           composed system filelist and top module.
  BOOT_RESET_INIT          `connectivity.evaluate_zero_time_connectivity()` over
                           a real `SignalTrace` of the composed top's clocks and
                           resets; without one,
                           `connectivity.run_gate2_against_live_simv()`'s honest
                           NOT_AVAILABLE.
  SHARED_RESOURCE_ACCESS   `system_resource_inventory.real_cross_subsystem_findings()`
                           -- REAL and runnable here whenever two subsystem
                           environments are registered and on disk.
  ONE_SUBSYSTEM            `connectivity.evaluate_transaction_activity_status()`
                           over ONE subsystem's monitors: PENDING until a real
                           pattern completes, never FAIL-by-absence.
  TWO_SUBSYSTEM_INTERACTION  the same real check, additionally requiring live
                           monitors in at least TWO subsystems -- the first rung
                           that proves anything a subsystem run does not.
  END_TO_END_SCENARIO      needs a real cross-subsystem scenario. The composer's
                           `cross_subsystem_scenarios()` deliberately raises
                           NotImplementedError (CLAUDE.md "No Golden-Reference
                           Content Mining"), so absent caller-supplied evidence
                           of a real completed scenario this is NOT_AVAILABLE
                           naming that boundary.
  WAVE_FSDBREPORT          `fsdb_report.run_fsdbreport()` + `parse_fsdbreport_output()`
                           against an fsdb the caller already has.
  SCOREBOARD_ASSERTION     the REAL `evidence_db.EvidenceStore`'s
                           `normalized_evidence` rows (the `vip_distill.py`
                           envelope) for the system run's job.
  SYSTEM_READY             aggregate only. PASS requires every rung PASS.
                           Anything NOT_AVAILABLE/PENDING is SMOKE_NOT_PROVEN,
                           never READY -- GF-AT-28, "UNKNOWN never becomes
                           PASS/READY automatically".

A FAIL halts the ladder (spec section 209's own `SMOKE_FAIL -> TRIAGE` edge):
the rungs after it are NOT_YET_RUN, which is a different fact from "checked and
clean". A NOT_AVAILABLE does not halt it -- knowing which of the remaining
rungs are also unrunnable is exactly the inventory a human needs.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import connectivity as conn
from . import uvm_structural_lint as usl
from .uvm_structural_lint import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    LintFinding,
)
from .verible_parser import (
    DEFAULT_VERIBLE_BIN,
    VeribleParseError,
    VeribleUnavailableError,
)

SCHEMA_VERSION = "1.0"

#: The identifier pattern `uvm_structural_lint` already uses to read the
#: leading type name out of a parameterized factory macro argument
#: (`my_seq#(T)` -> `my_seq`). Aliased, never re-declared, so the two modules
#: cannot drift on what an identifier is.
_IDENT_RE = usl._IDENT_RE

# ===========================================================================
# Merge-collision vocabulary
# ===========================================================================

#: Section 206's own words, one rule each. A name that exists twice in the
#: merged source set is a COMPILE-time merge failure; a config_db scope that is
#: written twice is an ELABORATION-time one (last writer wins, and the loser
#: silently gets the other subsystem's handle).
RULE_DUPLICATE_PACKAGE = "DUPLICATE_PACKAGE_DECLARATION"
RULE_DUPLICATE_TYPE = "DUPLICATE_TYPE_DEFINITION"
RULE_FACTORY_COLLISION = "FACTORY_TYPE_NAME_COLLISION"
RULE_CONFIG_DB_SCOPE_COLLISION = "CONFIG_DB_SET_SCOPE_COLLISION"
RULE_VIRTUAL_INTERFACE_CONFLICT = "VIRTUAL_INTERFACE_CONFLICT"
RULE_CONFIG_DB_SCOPE_NOT_RESOLVABLE = "CONFIG_DB_SET_SCOPE_NOT_STATICALLY_RESOLVABLE"

#: A `uvm_config_db#(T)::set` whose FIRST argument is one of these writes into
#: the GLOBAL config space rather than a component-relative one. Only a pair of
#: global sets can be PROVEN to collide from the sources alone: a set rooted at
#: `this` resolves to whatever component path that instance ends up at, which
#: this analysis (a parse, not an elaboration) cannot know.
GLOBAL_CONFIG_CONTEXTS = frozenset({"null", "uvm_root::get()", "uvm_top"})

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass
class MergeFinding(LintFinding):
    """A lint finding plus the SUBSYSTEMS it spans -- the one fact a
    per-environment `LintFinding` has no field for and the only reason this
    extends it rather than reusing it verbatim."""
    subsystems: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["subsystems"] = list(self.subsystems)
        return data


@dataclass
class SystemMergeReport:
    status: str = STATUS_PASS
    reason: Optional[str] = None
    verible_version: Optional[str] = None
    subsystems: List[str] = field(default_factory=list)
    files: List[Dict[str, str]] = field(default_factory=list)
    declarations_analyzed: int = 0
    config_db_sets_analyzed: int = 0
    findings: List[MergeFinding] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_WARNING)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "reason": self.reason,
            "verible_version": self.verible_version,
            "subsystems": list(self.subsystems),
            "files": list(self.files),
            "declarations_analyzed": self.declarations_analyzed,
            "config_db_sets_analyzed": self.config_db_sets_analyzed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "findings": [f.to_dict() for f in self.findings],
        }


def _scopes_overlap(a: Optional[str], b: Optional[str]) -> bool:
    """Two `uvm_config_db` inst_name patterns overlap when either matches the
    other as a glob. UVM's own matcher is glob-shaped (`*`/`?`), so `fnmatch`
    is the right shape rather than an approximation; `[`-class syntax is
    matched more liberally than UVM would, which makes this analysis's failure
    mode "reports an overlap that UVM would not", never the reverse."""
    if a is None or b is None:
        return False
    return a == b or fnmatch.fnmatchcase(a, b) or fnmatch.fnmatchcase(b, a)


def _is_global_context(text: Optional[str]) -> bool:
    if text is None:
        return False
    return "".join(text.split()).lower() in GLOBAL_CONFIG_CONTEXTS


def _is_virtual_interface_type(type_text: Optional[str]) -> bool:
    return bool(type_text) and type_text.strip().lower().startswith("virtual")


def analyze_system_merge(sources: Mapping[str, Sequence[Any]], *,
                         verible_bin: str = DEFAULT_VERIBLE_BIN) -> SystemMergeReport:
    """Section 206's static merge check over N subsystems' UVM sources analysed
    TOGETHER, which is the only way these defects are visible at all.

    `sources` maps a subsystem name -> its source files. The composed
    system-level files (Track A's `soc_tb_top.sv` /
    `soc_virtual_sequencer.sv`) belong in that mapping too, under their own
    key -- a system top that redeclares a subsystem's package is the same
    defect as two subsystems doing it.

    Parses with the REAL verible front end via
    `uvm_structural_lint.parse_uvm_file()` -- there is no second SystemVerilog
    parser here. When verible cannot be run the report is NOT_AVAILABLE with
    a real reason, never PASS: a merge check that could not read the sources
    has proven nothing about them.
    """
    names = [str(s) for s in sources]
    # "Nothing to check" is never evidence that a merge is clean -- the same
    # rule `uvm_structural_lint.lint_uvm_environment()` applies to an empty
    # environment directory, and the same shape Track B's
    # FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE uses. This repo's own subsystem
    # registry is legitimately EMPTY, so without this the headline verb would
    # report a clean merge of nothing.
    if len(names) < 2:
        return SystemMergeReport(
            status=STATUS_NOT_AVAILABLE, subsystems=names,
            reason=("FEWER_THAN_TWO_SOURCE_SETS_TO_MERGE: a system merge check "
                    f"needs at least two source sets to merge, got {names or 'none'}"))
    if not any(list(paths) for paths in sources.values()):
        return SystemMergeReport(
            status=STATUS_NOT_AVAILABLE, subsystems=names,
            reason=("NO_SOURCES_ON_DISK: none of "
                    f"{names} contributed a .sv/.svh source file to analyse"))

    report = SystemMergeReport(subsystems=names)
    parsed: List[tuple] = []          # (subsystem, UvmFileInfo)
    for subsystem, paths in sources.items():
        for path in paths:
            try:
                parsed.append((str(subsystem), usl.parse_uvm_file(path, verible_bin=verible_bin)))
            except VeribleUnavailableError as exc:
                return SystemMergeReport(
                    status=STATUS_NOT_AVAILABLE,
                    reason=f"verible-verilog-syntax could not be run: {exc}",
                    subsystems=names)
            except VeribleParseError as exc:
                # Identical treatment to `uvm_structural_lint.lint_uvm_sources()`:
                # a `.svh` is an include FRAGMENT by convention and is not
                # required to parse standalone; a `.sv` is a compilation unit,
                # so a parse failure there is a real defect. Either way the
                # file's contents really were left out, which narrows what a
                # clean report covers, so it is surfaced rather than dropped.
                is_fragment = Path(path).suffix.lower() == ".svh"
                report.findings.append(MergeFinding(
                    rule=("SOURCE_NOT_STANDALONE_PARSEABLE" if is_fragment
                          else "SOURCE_PARSE_ERROR"),
                    severity=(SEVERITY_WARNING if is_fragment else SEVERITY_ERROR),
                    file_path=str(path),
                    line=(exc.errors[0].get("line", 0) if exc.errors else 0),
                    subject=Path(path).name,
                    message=(
                        (f"include fragment did not parse as a standalone "
                         f"compilation unit and was NOT analysed by this merge "
                         f"check: {exc}")
                        if is_fragment else
                        f"verible reported syntax error(s): {exc}"),
                    subsystems=[str(subsystem)]))

    report.verible_version = usl.verible_parser.get_verible_version(verible_bin)
    report.files = [{"subsystem": s, "file_path": f.file_path,
                     "source_sha256": f.source_sha256} for s, f in parsed]

    # --- name index over the MERGED set ------------------------------------
    # keyed (kind, name) -> [{subsystem, file_path, line}], deduped by file so
    # a name seen twice inside ONE file (verible does not expand `include`, so
    # this does not happen for the include-into-package idiom real generated
    # environments use) cannot masquerade as a merge collision.
    declarations: Dict[tuple, List[Dict[str, Any]]] = {}

    def _record(kind: str, name: Optional[str], subsystem: str,
                file_path: str, line: int) -> None:
        if not name:
            return
        rows = declarations.setdefault((kind, name), [])
        if any(r["file_path"] == file_path for r in rows):
            return
        rows.append({"subsystem": subsystem, "file_path": file_path, "line": line})

    classes_by_subsystem: List[tuple] = []
    for subsystem, info in parsed:
        for decl in info.top_declarations:
            _record(decl.kind, decl.name, subsystem, info.file_path, decl.line)
        for cls in info.classes:
            _record("class", cls.name, subsystem, cls.file_path, cls.line)
            classes_by_subsystem.append((subsystem, cls))
    report.declarations_analyzed = sum(len(v) for v in declarations.values())

    duplicate_names: set = set()
    for (kind, name), rows in sorted(declarations.items()):
        if len(rows) < 2:
            continue
        duplicate_names.add(name)
        owners = sorted({r["subsystem"] for r in rows})
        rule = RULE_DUPLICATE_PACKAGE if kind == "package" else RULE_DUPLICATE_TYPE
        where = ", ".join(f"{r['subsystem']}:{Path(r['file_path']).name}:{r['line']}"
                          for r in rows)
        report.findings.append(MergeFinding(
            rule=rule, severity=SEVERITY_ERROR,
            file_path=rows[-1]["file_path"], line=rows[-1]["line"], subject=name,
            message=(f"{kind} {name!r} is declared {len(rows)} times across the merged "
                     f"system source set ({where}); compiling these subsystems into one "
                     f"simulation is a duplicate-definition error"
                     + ("" if len(owners) > 1 else
                        " -- both declarations belong to the same subsystem, so this "
                        "breaks that environment on its own too")),
            subsystems=owners))

    # --- factory type-name collisions --------------------------------------
    factory_names: Dict[str, List[Dict[str, Any]]] = {}
    for subsystem, cls in classes_by_subsystem:
        for macro in cls.factory_macros:
            args = macro.get("args") or []
            if not args:
                continue
            declared = _IDENT_RE.search(args[0])
            if not declared:
                continue
            rows = factory_names.setdefault(declared.group(0), [])
            if any(r["file_path"] == cls.file_path and r["class"] == cls.name
                   for r in rows):
                continue
            rows.append({"subsystem": subsystem, "file_path": cls.file_path,
                         "line": macro.get("line", cls.line), "class": cls.name,
                         "macro": macro.get("macro")})
    for type_name, rows in sorted(factory_names.items()):
        if len(rows) < 2:
            continue
        if type_name in duplicate_names:
            # Already reported as a duplicate DEFINITION; the factory
            # registration is the same defect seen from the other side, and
            # reporting it twice would inflate the error count.
            continue
        owners = sorted({r["subsystem"] for r in rows})
        report.findings.append(MergeFinding(
            rule=RULE_FACTORY_COLLISION, severity=SEVERITY_ERROR,
            file_path=rows[-1]["file_path"], line=rows[-1]["line"], subject=type_name,
            message=(f"factory type name {type_name!r} is registered by "
                     + ", ".join(f"{r['subsystem']}:{r['class']}" for r in rows)
                     + "; the UVM factory keys on this STRING, so the second "
                       "registration collides with the first and type_id::create()/"
                       "type overrides become ambiguous"),
            subsystems=owners))

    # --- config_db set-scope collisions ------------------------------------
    set_sites: List[Dict[str, Any]] = []
    for subsystem, info in parsed:
        for site in usl.config_db_call_sites(info.classes):
            if site["op"] != "set":
                continue
            site = dict(site)
            site["subsystem"] = subsystem
            set_sites.append(site)
    report.config_db_sets_analyzed = len(set_sites)

    by_field: Dict[str, List[Dict[str, Any]]] = {}
    for site in set_sites:
        if site["field"] is None or site["inst_name"] is None:
            report.findings.append(MergeFinding(
                rule=RULE_CONFIG_DB_SCOPE_NOT_RESOLVABLE, severity=SEVERITY_INFO,
                file_path=site["call"].file_path, line=site["call"].line,
                subject=site["field"] or site["field_text"] or "<unknown>",
                message=("uvm_config_db set scope is built at run time "
                         f"(inst_name={site['inst_name_text']!r}, "
                         f"field={site['field_text']!r}); this set is excluded from "
                         "cross-subsystem scope-collision matching"),
                subsystems=[site["subsystem"]]))
            continue
        by_field.setdefault(site["field"], []).append(site)

    for field_name, sites in sorted(by_field.items()):
        for i in range(len(sites)):
            for j in range(i + 1, len(sites)):
                a, b = sites[i], sites[j]
                if a["subsystem"] == b["subsystem"]:
                    # One environment's own internal scoping already worked as a
                    # standalone subsystem; this check is about the MERGE.
                    continue
                if not (_is_global_context(a["cntxt"]) and _is_global_context(b["cntxt"])):
                    # Not provable from a parse: a set rooted at `this` resolves
                    # to wherever that component is instantiated. Reporting it
                    # would make this check's ERRORs untrustworthy.
                    continue
                if not _scopes_overlap(a["inst_name"], b["inst_name"]):
                    continue
                virtual_if = (_is_virtual_interface_type(a["type_text"])
                              or _is_virtual_interface_type(b["type_text"]))
                report.findings.append(MergeFinding(
                    rule=(RULE_VIRTUAL_INTERFACE_CONFLICT if virtual_if
                          else RULE_CONFIG_DB_SCOPE_COLLISION),
                    severity=SEVERITY_ERROR,
                    file_path=b["call"].file_path, line=b["call"].line,
                    subject=f"{b['inst_name']}::{field_name}",
                    message=(
                        f"{a['subsystem']} sets uvm_config_db#({a['type_text']}) "
                        f"{field_name!r} at global scope {a['inst_name']!r} "
                        f"({Path(a['call'].file_path).name}:{a['call'].line}) and "
                        f"{b['subsystem']} sets uvm_config_db#({b['type_text']}) "
                        f"{field_name!r} at overlapping global scope "
                        f"{b['inst_name']!r}"
                        + (f"; the two virtual interface types differ, so whichever "
                           f"set runs last hands the other subsystem the wrong "
                           f"interface handle"
                           if virtual_if and a["type_text"] != b["type_text"] else
                           "; last writer wins, so one subsystem reads the other's "
                           "value")),
                    subsystems=sorted({a["subsystem"], b["subsystem"]})))

    report.findings.sort(key=lambda f: (f.rule, f.file_path, f.line, f.subject))
    report.status = STATUS_FAIL if report.error_count else STATUS_PASS
    return report


def subsystem_source_sets(root, names: Optional[Sequence[str]] = None,
                          ) -> Dict[str, List[Path]]:
    """Map each REGISTERED subsystem to the .sv/.svh sources of its real
    environment on disk.

    Reads the real registry through `environment_mode_router.
    read_registered_subsystem_entries()` -- harness evidence written only by
    engine.py on a gate-validated SIGNOFF PASS, never a caller's claim -- and
    discovers files with `uvm_structural_lint.discover_uvm_sources()`. A
    subsystem whose environment directory is not on disk contributes an EMPTY
    list rather than being dropped, so a caller can see that it was selected
    and could not be read."""
    from .environment_mode_router import read_registered_subsystem_entries

    wanted = {str(n).lower() for n in names} if names else None
    out: Dict[str, List[Path]] = {}
    for entry in read_registered_subsystem_entries(Path(root)):
        name = str(entry.get("name"))
        if wanted is not None and name.lower() not in wanted:
            continue
        env_dir: Optional[Path] = None
        if entry.get("environment_path"):
            env_dir = Path(str(entry["environment_path"]))
        elif entry.get("environment_manifest"):
            # <env>/.dv-harness/env.manifest.json -- the shape
            # _persist_subsystem_registry_entry() writes.
            manifest = Path(str(entry["environment_manifest"]))
            env_dir = manifest.parents[1] if len(manifest.parents) >= 2 else None
        out[name] = (usl.discover_uvm_sources(env_dir)
                     if env_dir is not None and env_dir.is_dir() else [])
    return out


# ===========================================================================
# The smoke-proof ladder
# ===========================================================================

RUNG_BUILD = "BUILD"
RUNG_ELABORATE = "ELABORATE"
RUNG_BOOT_RESET_INIT = "BOOT_RESET_INIT"
RUNG_SHARED_RESOURCE_ACCESS = "SHARED_RESOURCE_ACCESS"
RUNG_ONE_SUBSYSTEM = "ONE_SUBSYSTEM"
RUNG_TWO_SUBSYSTEM_INTERACTION = "TWO_SUBSYSTEM_INTERACTION"
RUNG_END_TO_END_SCENARIO = "END_TO_END_SCENARIO"
RUNG_WAVE_FSDBREPORT = "WAVE_FSDBREPORT"
RUNG_SCOREBOARD_ASSERTION = "SCOREBOARD_ASSERTION"

#: Section 206's ladder, in its own order. SYSTEM_READY is the aggregate and is
#: deliberately not a rung -- it is what the nine rungs above add up to.
SMOKE_PROOF_LADDER: tuple = (
    RUNG_BUILD, RUNG_ELABORATE, RUNG_BOOT_RESET_INIT, RUNG_SHARED_RESOURCE_ACCESS,
    RUNG_ONE_SUBSYSTEM, RUNG_TWO_SUBSYSTEM_INTERACTION, RUNG_END_TO_END_SCENARIO,
    RUNG_WAVE_FSDBREPORT, RUNG_SCOREBOARD_ASSERTION,
)

#: The three verdicts the ladder itself produces. Deliberately NOT
#: `subsystem_discovery`'s READY/PARTIAL/BLOCKED/UNKNOWN, which
#: `system_readiness.derive_system_readiness()` already uses for the STATIC
#: question ("can this composition be integrated at all"). This is the DYNAMIC
#: one ("has the composed system actually been proven to boot and run"), and
#: giving two different questions one vocabulary is how a metadata rollup
#: starts reading as a simulation result.
SYSTEM_READY = "SYSTEM_READY"
SMOKE_FAIL = "SMOKE_FAIL"
SMOKE_NOT_PROVEN = "SMOKE_NOT_PROVEN"
SMOKE_VERDICTS: tuple = (SYSTEM_READY, SMOKE_FAIL, SMOKE_NOT_PROVEN)


@dataclass
class RungResult:
    rung: str
    status: str                     # a connectivity.GateStatus VALUE
    reason: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"rung": self.rung, "status": self.status, "reason": self.reason,
                "detail": self.detail}


@dataclass
class SmokeProofReport:
    verdict: str
    evidence: str
    rungs: List[RungResult] = field(default_factory=list)
    merge_report: Optional[SystemMergeReport] = None

    def rung(self, name: str) -> RungResult:
        for r in self.rungs:
            if r.rung == name:
                return r
        raise KeyError(name)

    @property
    def triage_required(self) -> bool:
        """Spec section 209's `SMOKE_FAIL -> TRIAGE` edge, as a real property
        rather than a caller's string comparison."""
        return self.verdict == SMOKE_FAIL

    def to_dict(self) -> Dict[str, Any]:
        by_status: Dict[str, List[str]] = {}
        for r in self.rungs:
            by_status.setdefault(r.status, []).append(r.rung)
        return {
            "schema_version": SCHEMA_VERSION,
            "ladder": list(SMOKE_PROOF_LADDER),
            "verdict": self.verdict,
            "evidence": self.evidence,
            "triage_required": self.triage_required,
            "authorizes": ("NOTHING -- a SYSTEM_READY smoke proof is the "
                           "PRECONDITION for large LSF system regression "
                           "(section 206), not an authorization to launch one, "
                           "and SYS-39 still stops for explicit human approval"),
            "rungs": [r.to_dict() for r in self.rungs],
            "by_status": by_status,
            "merge_report": self.merge_report.to_dict() if self.merge_report else None,
        }


def _na(rung: str, reason: str, /, **detail) -> RungResult:
    """NOT_AVAILABLE with a real reason. Positional-only so a `**detail` dict
    carrying its own `reason`/`status` keys (every `real_cross_subsystem_
    findings()` result does) cannot collide with these parameters."""
    return RungResult(rung, conn.GateStatus.NOT_AVAILABLE.value, reason, detail)


def _from_gate(rung: str, result: conn.GateResult) -> RungResult:
    """Carry an existing `connectivity` gate verdict through unchanged. The
    ladder never re-derives a status those gates already decided."""
    detail = dict(result.detail or {})
    reason = str(detail.get("reason") or "")
    if not reason:
        reason = (f"{result.gate} reported {result.status.value}"
                  + (f": {detail.get('problems')}" if detail.get("problems") else ""))
    return RungResult(rung, result.status.value, reason,
                      {"connectivity_gate": result.gate, **detail})


def _build_rung(merge: SystemMergeReport) -> RungResult:
    if merge.status == STATUS_NOT_AVAILABLE:
        return _na(RUNG_BUILD, merge.reason or "system merge check could not run",
                   merge_status=merge.status)
    errors = [f.to_dict() for f in merge.findings if f.severity == SEVERITY_ERROR]
    if errors:
        return RungResult(
            RUNG_BUILD, conn.GateStatus.FAIL.value,
            f"{len(errors)} system merge collision(s) across "
            f"{len(merge.subsystems)} subsystem source set(s)",
            {"errors": errors, "error_count": len(errors),
             "warning_count": merge.warning_count})
    return RungResult(
        RUNG_BUILD, conn.GateStatus.PASS.value,
        f"{merge.declarations_analyzed} declaration(s) and "
        f"{merge.config_db_sets_analyzed} uvm_config_db set(s) merged from "
        f"{len(merge.subsystems)} source set(s) with no duplicate package/type, "
        f"factory collision or overlapping global config_db set",
        {"warning_count": merge.warning_count,
         "warnings": [f.to_dict() for f in merge.findings
                      if f.severity != SEVERITY_ERROR]})


def _shared_resource_rung(root, subsystems: Optional[Sequence[str]]) -> RungResult:
    from . import system_resource_inventory as sri

    if root is None:
        return _na(RUNG_SHARED_RESOURCE_ACCESS,
                   "no project root supplied, so the real SYS-9..SYS-14 "
                   "cross-subsystem analysis could not be run")
    findings = sri.real_cross_subsystem_findings(
        root, list(subsystems) if subsystems else None)
    if findings.get("status") != sri.CROSSCHECK_AVAILABLE:
        return _na(RUNG_SHARED_RESOURCE_ACCESS,
                   f"Track-B cross-subsystem analysis unavailable: "
                   f"{findings.get('reason')}", **findings)
    if not findings.get("automatic_integration_allowed"):
        return RungResult(
            RUNG_SHARED_RESOURCE_ACCESS, conn.GateStatus.FAIL.value,
            "the real cross-subsystem analysis stopped automatic integration: "
            f"{findings.get('driver_conflicts')} active-driver conflict(s) on "
            f"{findings.get('stopped_resource_ids')}",
            {**findings,
             # DETECTION only. Nothing here picks a winner between two ACTIVE
             # drivers -- SYS-12's preferred model is carried through as text
             # for the human who must.
             "human_arbitration_required": True})
    return RungResult(
        RUNG_SHARED_RESOURCE_ACCESS, conn.GateStatus.PASS.value,
        f"{findings.get('resource_count')} resource(s) across "
        f"{findings.get('subsystems')}: no unresolved active-driver ownership "
        f"conflict; {len(findings.get('shared_resource_ids') or [])} shared "
        f"resource(s) reachable from more than one subsystem",
        dict(findings))


def _transaction_rung(rung: str, counts_by_subsystem: Optional[Mapping[str, Mapping[str, int]]],
                      pattern_completed: Optional[bool],
                      *, min_subsystems: int) -> RungResult:
    """ONE_SUBSYSTEM / TWO_SUBSYSTEM_INTERACTION, both decided by the EXISTING
    `connectivity.evaluate_transaction_activity_status()`. The only thing this
    adds is the subsystem-count precondition that makes the two rungs
    different: a two-subsystem interaction is not proven by traffic in one."""
    live = {s: dict(c) for s, c in (counts_by_subsystem or {}).items() if c}
    if not live:
        if pattern_completed is False:
            return RungResult(
                rung, conn.GateStatus.PENDING.value,
                "no pattern has completed on the composed system yet, so no VIP "
                "monitor transaction counts exist to tally",
                {"prerequisite": "a completed (terminal PASS or FAIL) system pattern"})
        return _na(rung,
                   "no per-subsystem VIP monitor transaction counts were supplied "
                   "for the composed system; there is no live system simv here to "
                   "source them from")
    if len(live) < min_subsystems:
        return _na(rung,
                   f"monitor counts were supplied for {sorted(live)} only; this rung "
                   f"needs live monitors in at least {min_subsystems} subsystems to "
                   f"prove anything a single-subsystem run does not")
    merged: Dict[str, int] = {}
    for subsystem, counts in live.items():
        for monitor, value in counts.items():
            merged[f"{subsystem}:{monitor}"] = int(value)
    result = conn.evaluate_transaction_activity_status(
        True if pattern_completed is None else bool(pattern_completed), merged)
    carried = _from_gate(rung, result)
    carried.detail["subsystems_with_monitors"] = sorted(live)
    if carried.status == conn.GateStatus.PASS.value:
        carried.reason = (f"every one of {len(merged)} VIP monitor(s) across "
                          f"{sorted(live)} received at least one real transaction")
    elif carried.status == conn.GateStatus.FAIL.value:
        carried.reason = (f"silent VIP monitor(s) on the composed system: "
                          f"{sorted(result.detail.get('silent_monitors') or {})}")
    return carried


def _end_to_end_rung(scenario_evidence: Optional[Mapping[str, Any]]) -> RungResult:
    if not scenario_evidence:
        return _na(RUNG_END_TO_END_SCENARIO,
                   "no completed cross-subsystem end-to-end scenario evidence was "
                   "supplied. soc_environment_composer.cross_subsystem_scenarios() "
                   "deliberately raises NotImplementedError (CLAUDE.md 'No "
                   "Golden-Reference Content Mining': a scenario body must come from "
                   "primary per-subsystem VIP/DUT evidence), and SYS-40 -- which "
                   "writes real scenario bodies -- stops for human approval, so this "
                   "harness cannot generate one to run",
                   boundary="SYS-40_REQUIRES_HUMAN_APPROVAL")
    name = str(scenario_evidence.get("scenario") or "<unnamed>")
    subsystems = list(scenario_evidence.get("subsystems") or [])
    verdict = str(scenario_evidence.get("verdict") or "").strip().upper()
    if len(subsystems) < 2:
        return _na(RUNG_END_TO_END_SCENARIO,
                   f"scenario {name!r} names {subsystems}; an end-to-end scenario "
                   "must span at least two subsystems to be one")
    if not verdict:
        return RungResult(
            RUNG_END_TO_END_SCENARIO, conn.GateStatus.PENDING.value,
            f"scenario {name!r} has no terminal verdict yet",
            dict(scenario_evidence))
    from .golden_scenario import PASS_VERDICTS
    if verdict in PASS_VERDICTS:
        return RungResult(RUNG_END_TO_END_SCENARIO, conn.GateStatus.PASS.value,
                          f"end-to-end scenario {name!r} across {subsystems} "
                          f"completed with verdict {verdict}",
                          dict(scenario_evidence))
    return RungResult(RUNG_END_TO_END_SCENARIO, conn.GateStatus.FAIL.value,
                      f"end-to-end scenario {name!r} across {subsystems} recorded "
                      f"verdict {verdict}", dict(scenario_evidence))


def _wave_rung(fsdb_path: Optional[str], fsdbreport_bin: str,
               signals: Optional[Sequence[str]]) -> RungResult:
    from . import fsdb_report as fr

    if not fsdb_path:
        return _na(RUNG_WAVE_FSDBREPORT,
                   "no system-level FSDB was supplied. This rung READS an existing "
                   "dump; it never enables one, because enabling waveform dumping "
                   "requires CLAUDE.md's Waveform Dump User Gate (a real human "
                   "decision on scope and level/depth)")
    extra = ["-s", *signals] if signals else None
    result = fr.run_fsdbreport(str(fsdb_path), fsdbreport_bin=fsdbreport_bin,
                               extra_args=extra)
    if not result.get("ok"):
        error = str(result.get("error"))
        if error in ("FSDBREPORT_BINARY_NOT_FOUND", "FSDB_FILE_NOT_FOUND",
                     "FSDBREPORT_TIMEOUT"):
            return _na(RUNG_WAVE_FSDBREPORT,
                       f"fsdbreport could not produce a report: {error}", **result)
        return RungResult(RUNG_WAVE_FSDBREPORT, conn.GateStatus.FAIL.value,
                          f"fsdbreport failed: {error}", dict(result))
    parsed = fr.parse_fsdbreport_output(result.get("report_text") or "")
    if not parsed.get("parsed"):
        return _na(RUNG_WAVE_FSDBREPORT,
                   f"fsdbreport ran but its output could not be parsed: "
                   f"{parsed.get('note')}",
                   parsed=False, note=parsed.get("note"))
    records = parsed.get("records") or []
    if not records:
        return RungResult(RUNG_WAVE_FSDBREPORT, conn.GateStatus.FAIL.value,
                          "fsdbreport parsed the system FSDB and found no recorded "
                          "activity at all in the reported window",
                          {"fieldnames": parsed.get("fieldnames"), "record_count": 0})
    return RungResult(RUNG_WAVE_FSDBREPORT, conn.GateStatus.PASS.value,
                      f"fsdbreport read {len(records)} record(s) of real activity out "
                      f"of the system FSDB",
                      {"fieldnames": parsed.get("fieldnames"),
                       "record_count": len(records)})


def _scoreboard_rung(evidence_db_path, job_id: Optional[int]) -> RungResult:
    """Scoreboard/Assertion evidence read from the REAL
    `evidence_db.EvidenceStore` `normalized_evidence` table -- the same
    `vip_distill.py` envelope `golden_scenario.py` reads, and the same
    PASS vocabulary, rather than a second notion of "the run was clean"."""
    from .golden_scenario import PASS_VERDICTS

    if not evidence_db_path or not Path(evidence_db_path).exists():
        return _na(RUNG_SCOREBOARD_ASSERTION,
                   "no evidence database on disk, so no system-run scoreboard/"
                   "assertion evidence could be read")
    if job_id is None:
        return _na(RUNG_SCOREBOARD_ASSERTION,
                   "no system-run job id supplied to read normalized evidence for")
    from .evidence_db import EvidenceStore
    try:
        with EvidenceStore(evidence_db_path, read_only=True) as store:
            rows = store.query(
                "SELECT evidence_id, source_kind, pattern, verdict, counts_json, "
                "detail_json FROM normalized_evidence WHERE job_id = ?", [int(job_id)])
    except Exception as exc:  # pragma: no cover - unreadable/older db
        return _na(RUNG_SCOREBOARD_ASSERTION,
                   f"evidence database could not be read: {type(exc).__name__}: {exc}")
    if not rows:
        return _na(RUNG_SCOREBOARD_ASSERTION,
                   f"no normalized evidence recorded for system job {job_id}")

    errors: List[Dict[str, Any]] = []
    verdicts: List[str] = []
    for row in rows:
        record = dict(zip(("evidence_id", "source_kind", "pattern", "verdict",
                           "counts_json", "detail_json"), row))
        verdict = str(record.get("verdict") or "").strip().upper()
        verdicts.append(verdict or "NONE")
        counts = json.loads(record["counts_json"]) if record.get("counts_json") else {}
        detail = json.loads(record["detail_json"]) if record.get("detail_json") else {}
        failures = {k: v for k, v in (counts or {}).items()
                    if k in ("uvm_error", "uvm_fatal") and v}
        assertion_failure = (detail.get("job_record") or detail).get("assertion_failure")
        if failures or assertion_failure or (verdict and verdict not in PASS_VERDICTS):
            errors.append({"evidence_id": record["evidence_id"],
                           "pattern": record.get("pattern"), "verdict": verdict,
                           "counts": failures,
                           "assertion_failure": assertion_failure})
    if errors:
        return RungResult(RUNG_SCOREBOARD_ASSERTION, conn.GateStatus.FAIL.value,
                          f"{len(errors)} of {len(rows)} system evidence row(s) record "
                          f"a UVM error/fatal, an assertion failure or a non-PASS "
                          f"verdict", {"failing_rows": errors, "row_count": len(rows)})
    if not any(v in PASS_VERDICTS for v in verdicts):
        return _na(RUNG_SCOREBOARD_ASSERTION,
                   f"{len(rows)} evidence row(s) for system job {job_id} record no "
                   f"terminal PASS verdict ({verdicts}); an absent verdict is not a "
                   f"clean scoreboard",
                   verdicts=verdicts, row_count=len(rows))
    return RungResult(RUNG_SCOREBOARD_ASSERTION, conn.GateStatus.PASS.value,
                      f"{len(rows)} normalized evidence row(s) for system job "
                      f"{job_id}: verdicts {verdicts}, zero UVM error/fatal, no "
                      f"assertion failure", {"row_count": len(rows),
                                             "verdicts": verdicts})


def run_system_smoke_proof(
    *,
    sources: Mapping[str, Sequence[Any]],
    root: Any = None,
    subsystems: Optional[Sequence[str]] = None,
    filelist_paths: Optional[Sequence[Any]] = None,
    top_module: str = "soc_tb_top",
    signal_trace: Optional[conn.SignalTrace] = None,
    clock_signal: str = "clk",
    reset_signal: str = "rst_n",
    required_nonx_signals: Optional[Sequence[str]] = None,
    monitor_transaction_counts: Optional[Mapping[str, Mapping[str, int]]] = None,
    pattern_completed: Optional[bool] = None,
    end_to_end_scenario: Optional[Mapping[str, Any]] = None,
    fsdb_path: Optional[str] = None,
    fsdbreport_bin: str = "fsdbreport",
    fsdb_signals: Optional[Sequence[str]] = None,
    evidence_db_path: Any = None,
    system_job_id: Optional[int] = None,
    verible_bin: str = DEFAULT_VERIBLE_BIN,
    which_fn: Callable[[str], Optional[str]] = None,
    run_fn: Callable[..., Any] = None,
) -> SmokeProofReport:
    """Drive section 206's smoke-proof ladder over a composed system.

    Every rung either runs a REAL existing mechanism or reports NOT_AVAILABLE
    with its real reason. Nothing here generates a system artifact, starts a
    build, submits an LSF job, enables a waveform dump or resolves a driver
    conflict.
    """
    import shutil
    import subprocess

    which_fn = which_fn or shutil.which
    run_fn = run_fn or subprocess.run

    merge = analyze_system_merge(sources, verible_bin=verible_bin)
    rungs: List[RungResult] = [_build_rung(merge)]

    def _halted() -> bool:
        return any(r.status == conn.GateStatus.FAIL.value for r in rungs)

    def _blocked(rung: str) -> RungResult:
        failed = next(r.rung for r in rungs if r.status == conn.GateStatus.FAIL.value)
        return RungResult(
            rung, conn.GateStatus.NOT_YET_RUN.value,
            f"the ladder halted at {failed}; this rung was never attempted "
            f"(spec section 209: SMOKE_FAIL -> TRIAGE)",
            {"halted_at": failed})

    for rung in SMOKE_PROOF_LADDER[1:]:
        if _halted():
            rungs.append(_blocked(rung))
            continue
        if rung == RUNG_ELABORATE:
            if not filelist_paths:
                rungs.append(_na(
                    RUNG_ELABORATE,
                    "no system-level filelist was supplied. Writing one is SYS-40, "
                    "which stops for explicit human approval; this rung never "
                    "writes one itself",
                    boundary="SYS-40_REQUIRES_HUMAN_APPROVAL"))
            else:
                rungs.append(_from_gate(RUNG_ELABORATE, conn.run_gate1_elaboration_check(
                    list(filelist_paths), top_module, which_fn=which_fn, run_fn=run_fn)))
        elif rung == RUNG_BOOT_RESET_INIT:
            if signal_trace is None:
                rungs.append(_from_gate(RUNG_BOOT_RESET_INIT,
                                        conn.run_gate2_against_live_simv()))
            else:
                rungs.append(_from_gate(RUNG_BOOT_RESET_INIT,
                                        conn.evaluate_zero_time_connectivity(
                                            signal_trace, clock_signal, reset_signal,
                                            list(required_nonx_signals or []))))
        elif rung == RUNG_SHARED_RESOURCE_ACCESS:
            rungs.append(_shared_resource_rung(root, subsystems))
        elif rung == RUNG_ONE_SUBSYSTEM:
            rungs.append(_transaction_rung(RUNG_ONE_SUBSYSTEM, monitor_transaction_counts,
                                           pattern_completed, min_subsystems=1))
        elif rung == RUNG_TWO_SUBSYSTEM_INTERACTION:
            rungs.append(_transaction_rung(RUNG_TWO_SUBSYSTEM_INTERACTION,
                                           monitor_transaction_counts,
                                           pattern_completed, min_subsystems=2))
        elif rung == RUNG_END_TO_END_SCENARIO:
            rungs.append(_end_to_end_rung(end_to_end_scenario))
        elif rung == RUNG_WAVE_FSDBREPORT:
            rungs.append(_wave_rung(fsdb_path, fsdbreport_bin, fsdb_signals))
        elif rung == RUNG_SCOREBOARD_ASSERTION:
            rungs.append(_scoreboard_rung(evidence_db_path, system_job_id))
        else:  # pragma: no cover - SMOKE_PROOF_LADDER is a closed tuple
            raise ValueError(f"unhandled smoke-proof rung {rung!r}")

    failed = [r for r in rungs if r.status == conn.GateStatus.FAIL.value]
    unproven = [r for r in rungs if r.status not in (conn.GateStatus.PASS.value,
                                                     conn.GateStatus.FAIL.value)]
    if failed:
        verdict = SMOKE_FAIL
        evidence = ("smoke proof FAILED at " + failed[0].rung + ": " + failed[0].reason)
    elif unproven:
        verdict = SMOKE_NOT_PROVEN
        evidence = (f"{len(rungs) - len(unproven)}/{len(rungs)} rung(s) PASS; "
                    + "; ".join(f"{r.rung}={r.status}" for r in unproven)
                    + ". No rung failed, and the ladder is NOT proven: an "
                      "unrunnable rung never rounds up to SYSTEM_READY")
    else:
        verdict = SYSTEM_READY
        evidence = (f"every one of the {len(rungs)} smoke-proof rungs PASSED against "
                    "real evidence")
    return SmokeProofReport(verdict=verdict, evidence=evidence, rungs=rungs,
                            merge_report=merge)


# ===========================================================================
# Reporting / CLI
# ===========================================================================

def format_merge_report(report: SystemMergeReport) -> str:
    lines = [f"System merge check: {report.status}"]
    if report.reason:
        lines.append(f"  reason: {report.reason}")
    if report.status != STATUS_NOT_AVAILABLE:
        lines.append(f"  subsystems={report.subsystems} files={len(report.files)} "
                     f"declarations={report.declarations_analyzed} "
                     f"config_db_sets={report.config_db_sets_analyzed} "
                     f"errors={report.error_count} warnings={report.warning_count}")
    for finding in report.findings:
        lines.append(f"  [{finding.severity}] {finding.rule} {finding.file_path}:"
                     f"{finding.line} ({finding.subject}) {finding.subsystems}: "
                     f"{finding.message}")
    return "\n".join(lines)


def format_smoke_proof_report(report: SmokeProofReport) -> str:
    lines = [f"SYSTEM SMOKE PROOF: {report.verdict}",
             f"  {report.evidence}", ""]
    width = max(len(r.rung) for r in report.rungs)
    for i, rung in enumerate(report.rungs, start=1):
        lines.append(f"  {i}. {rung.rung.ljust(width)}  {rung.status}")
        lines.append(f"       {rung.reason}")
    lines += ["",
              "This verdict authorizes NOTHING: a SYSTEM_READY smoke proof is the "
              "precondition for large LSF system regression, and SYS-39 still stops "
              "for explicit human approval."]
    return "\n".join(lines)


def execute_verb(root, *, subsystems: Optional[Sequence[str]] = None,
                 composed_dir: Any = None, filelist_paths: Optional[Sequence[Any]] = None,
                 top_module: str = "soc_tb_top", merge_only: bool = False,
                 evidence_db_path: Any = None, system_job_id: Optional[int] = None,
                 fsdb_path: Optional[str] = None,
                 as_json: bool = False,
                 verible_bin: str = DEFAULT_VERIBLE_BIN) -> tuple:
    """One shared implementation for `dv-harness system-smoke-proof` and
    `python -m dv_harness.system_build_proof` -- the same convention
    `power_intent.execute_verb()`/`golden_scenario.execute_verb()` use.

    Exit codes: 0 SYSTEM_READY, 1 SMOKE_FAIL, 2 SMOKE_NOT_PROVEN (or a merge
    check that could not run). Anything short of proven never exits 0.
    """
    sources: Dict[str, List[Path]] = dict(subsystem_source_sets(root, subsystems))
    if composed_dir:
        sources["__system__"] = usl.discover_uvm_sources(composed_dir)
    if evidence_db_path is None:
        # The same default `golden-scenario` uses, so "the evidence database"
        # means one path in this codebase.
        from .evidence_db import default_db_path
        candidate = default_db_path(Path(root))
        evidence_db_path = candidate if candidate.exists() else None

    if merge_only:
        merge = analyze_system_merge(sources, verible_bin=verible_bin)
        text = (json.dumps(merge.to_dict(), indent=2) if as_json
                else format_merge_report(merge))
        return text, (0 if merge.status == STATUS_PASS
                      else 1 if merge.status == STATUS_FAIL else 2)

    report = run_system_smoke_proof(
        sources=sources, root=root, subsystems=subsystems,
        filelist_paths=filelist_paths, top_module=top_module,
        fsdb_path=fsdb_path, evidence_db_path=evidence_db_path,
        system_job_id=system_job_id, verible_bin=verible_bin)
    text = (json.dumps(report.to_dict(), indent=2) if as_json
            else format_smoke_proof_report(report))
    return text, (0 if report.verdict == SYSTEM_READY
                  else 1 if report.verdict == SMOKE_FAIL else 2)


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - thin
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.system_build_proof",
        description="Spec section 206 system build & smoke proof.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--subsystem", action="append", default=None, dest="subsystems")
    parser.add_argument("--composed-dir", default=None)
    parser.add_argument("--filelist", action="append", default=None, dest="filelists")
    parser.add_argument("--top-module", default="soc_tb_top")
    parser.add_argument("--merge-only", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--system-job-id", type=int, default=None)
    parser.add_argument("--fsdb", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verible-bin", default=DEFAULT_VERIBLE_BIN)
    args = parser.parse_args(argv)
    text, code = execute_verb(
        args.root, subsystems=args.subsystems, composed_dir=args.composed_dir,
        filelist_paths=args.filelists, top_module=args.top_module,
        merge_only=args.merge_only, evidence_db_path=args.db,
        system_job_id=args.system_job_id, fsdb_path=args.fsdb,
        as_json=args.json, verible_bin=args.verible_bin)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
