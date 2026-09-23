"""dv_harness/reference_uvm_dut_top_integration_manifest.py -- DISCOVERY-ONLY
manifest for whether a project already has a DE (design-engineer-authored)
top-level testbench, and what it would agree/disagree with a generated
`soc_tb_top.sv` about.

WHY THIS MODULE EXISTS. The L5DGVA audit (`.dv-harness/l5dgva_audit_result_C.md`,
"C13" cluster, its largest single finding) found that
`dv_harness/uvm_generator/soc_environment_composer.py`'s `_soc_tb_top()`
always emits a fresh `soc_tb_top.sv` from scratch. Nothing in this repo ever
asks "does this project already have a real top TB?" before that happens,
even though CLAUDE.md's own design principle is that a known-good existing
top TB should normally be preserved/integrated, not silently replaced. This
module is the missing DISCOVER-and-REPORT step -- modeled directly on
`dv_harness/phy_boundary.py`'s own shape ("discover which layer/boundary
applies, before deciding anything about generation").

THIS MODULE DOES NOT CHANGE GENERATION BEHAVIOR. It does not modify
`soc_environment_composer.py`, does not change what `_soc_tb_top()` emits,
and does not decide whether an existing top TB should be preserved,
integrated, or replaced -- it only surfaces the facts a human (or a future,
separately-approved change) would need to make that decision. Per
CLAUDE.md's `change_blast_radius.py` governance, changing
`soc_environment_composer.py`'s real generated output is a deliberately
DEFERRED follow-on task, gated on an explicit human design decision and
recorded human approval -- not something this discovery module may do or
imply doing.

WHAT IT DERIVES FROM (never invents):
  * the SAME "top TB" naming convention this repo already established --
    `dv_harness/subsystem_discovery.py`'s `ARTIFACT_GLOBS["top_hierarchy"]`
    (`"*tb_top.sv"`, `"*_top.sv"`, `"top.sv"`, `"*hierarchy.json"`), reused
    verbatim rather than re-invented. That constant is SYS-2's own real
    evidence vocabulary for "is there a top hierarchy artifact here", so
    reusing it means a project that already passes SYS-2/SYS-4 discovery for
    `top_hierarchy` is found by this module through the identical evidence,
    not a second, silently-different heuristic that could disagree with it.
  * `dv_harness/uvm_generator/bind_mechanism_generator.py`'s own real
    Two-Hooks convention: Hook 1 is a literal `` `ifdef DV_UVM `` guard that
    swaps in a `dv_uvm_hook.svh` include (see that module's docstring and
    `emit_hook_svh()`). This module looks for that EXACT textual convention
    in an existing top TB, rather than inventing a different hook-detection
    heuristic.
  * `dv_harness/uvm_generator/soc_environment_composer.py`'s own real,
    already-generated `soc_tb_top.sv` text -- `generated_top_tb_facts()`
    below calls that module's real `_soc_tb_top()` (read, not modified) and
    runs the exact same textual fact-extraction over its output that
    `extract_existing_top_tb_facts()` runs over a real existing file, so
    "generated" facts are read from real generated text, never a second,
    hand-described approximation of what the generator does.

WHAT IT DOES NOT DECIDE. `compare_against_generated_top()` reports, per
fact, one of MATCH / DIVERGENT / EXISTING_ONLY / GENERATED_ONLY (plus the
honest `NOT_COMPARABLE` state below) -- never whether a divergence is
acceptable, never which side should win. That is exactly the follow-on
design decision this module's own docstring names as deliberately out of
scope: changing `soc_environment_composer.py` to actually preserve an
existing top TB is a separate task, pending a human decision informed by
this manifest, not decided or implemented here.

HONESTY OF THE FACT EXTRACTION. `extract_existing_top_tb_facts()` is a
regex-based textual scan, not a real elaboration or even a real
`verible-verilog-syntax` parse (the RTL-parsing mechanism
`dv_harness/verible_parser.py`/`dv_harness/env_manifest.py` already own for
real DUT RTL). A hand-authored top TB is testbench source, not DUT RTL, and
this module's own facts are deliberately narrow (DUT instantiation, a small
set of declared clock/reset-shaped identifiers, and the literal DV_UVM hook
convention) -- exactly the shape `phy_boundary.py`'s own `_STRONG_CORE_RE`/
`_WEAK_CORE_RE` token-boundary discipline already uses for a similar
"real signal name, not a guess" problem, applied independently here so this
module carries no import-time coupling to `phy_boundary.py`'s private
internals. Every fact reports its own `status` (`PRESENT`/`ABSENT`/
`NOT_DECLARED`/`UNKNOWN`) and cites the matched text -- never a bare bool
with no evidence attached.

Which module is the real DUT is a declared project fact, never guessed from
a file or instance name -- the same discipline `phy_boundary.py` applies to
which module is the PHY/controller pair. `dut_module_name` is therefore a
caller-supplied input; when it is absent, DUT-instantiation comparison
reports `NOT_DECLARED`, not a guessed match.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .subsystem_discovery import (
    ARTIFACT_GLOBS,
    MAX_WALK_DEPTH,
    MAX_WALK_FILES,
)

# --- comparison-verdict vocabulary ------------------------------------------
MATCH = "MATCH"
DIVERGENT = "DIVERGENT"
EXISTING_ONLY = "EXISTING_ONLY"
GENERATED_ONLY = "GENERATED_ONLY"
# Not one of the four the task names -- an honest fifth state for "one or
# both sides could not be determined at all", so a caller can never mistake
# "we could not tell" for "we checked and they agree" (the same ABSENT-vs-
# UNKNOWN discipline subsystem_discovery.py already applies to its own
# per-factor statuses).
NOT_COMPARABLE = "NOT_COMPARABLE"
COMPARISON_VALUES: tuple = (MATCH, DIVERGENT, EXISTING_ONLY, GENERATED_ONLY, NOT_COMPARABLE)

# Only the SV-source-shaped patterns from ARTIFACT_GLOBS["top_hierarchy"] are
# candidate TOP TB FILES; "*hierarchy.json" (also in that tuple) is real
# top-hierarchy evidence but is a topology-dump artifact, not a testbench
# source file this module can extract DUT-instantiation/clock-reset/hook
# facts from.
_TOP_TB_FILE_GLOBS = tuple(g for g in ARTIFACT_GLOBS["top_hierarchy"] if g.endswith(".sv"))

# The literal DV_UVM two-hook convention (bind_mechanism_generator.py's own
# `emit_hook_svh()` docstring/output), matched textually rather than parsed,
# since it is itself a textual preprocessor convention, not a structural one.
_DV_UVM_IFDEF_RE = re.compile(r"`ifdef\s+DV_UVM\b")
_DV_UVM_HOOK_INCLUDE_RE = re.compile(r'`include\s+"([^"]*dv_uvm_hook\.svh)"')

# A declared clock/reset identifier match: a case-insensitive substring
# match for "clk"/"clock" or "rst"/"reset" anywhere in an already-isolated
# identifier (the _DECL_RE capture group below already isolates one bare
# name, so no additional word-boundary machinery is needed here) -- so
# "sys_clk", "clkgen_enable" and "reset_value_field" all match. Deliberately
# simpler than phy_boundary.py's own _STRONG_CORE_RE/_WEAK_CORE_RE (which
# additionally separates "unambiguous" from "needs a prefix" cores to decide
# a BIND location) -- this module only enumerates candidate declarations, it
# does not decide a mount layer, so that extra precision is not owed here.
_CLOCK_NAME_RE = re.compile(r"(?i)clk|clock")
_RESET_NAME_RE = re.compile(r"(?i)rst|reset")

# One declaration per line, ANSI port or plain net: [input|output|inout]
# (logic|wire|reg) [bit-range] <name> , or ;
_DECL_RE = re.compile(
    r"\b(?:input\s+|output\s+|inout\s+)?(?:logic|wire|reg)\s+"
    r"(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)\s*[,;)]"
)

_MODULE_NAME_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- SYS-2-vocabulary-reusing discovery --------------------------------------

def discover_existing_top_tb(project_root, *, declared_path=None) -> Dict[str, Any]:
    """Search `project_root` for a plausible pre-existing DE top-level
    testbench file, using the EXACT same `top_hierarchy` naming-convention
    globs `subsystem_discovery.py`'s own SYS-2 evidence probe already
    established (`_TOP_TB_FILE_GLOBS`, filtered to the `.sv` subset of
    `ARTIFACT_GLOBS["top_hierarchy"]`) -- never a second, independently
    invented set of patterns.

    `declared_path` -- a project-relative path -- BEATS the name convention
    entirely when supplied and exists on disk, same "declared path wins"
    precedent as `subsystem_discovery.probe_environment_artifacts()`'s own
    `declared` parameter: a project that already knows its own top TB's real
    path is never at the mercy of a name-convention guess.

    Returns:
        {"status": "FOUND" | "NOT_FOUND" | "UNKNOWN",
         "candidates": [relative POSIX path, ...],  # newest-first by mtime
         "basis": str}
    `FOUND` names every match (a caller decides which, if more than one);
    `NOT_FOUND` is a real negative (the tree was walked and nothing
    matched); `UNKNOWN` means the tree itself could not be walked (absent or
    unreadable root) -- never conflated with a real NOT_FOUND, matching
    `subsystem_discovery.py`'s own ABSENT-vs-UNKNOWN discipline.
    """
    root = Path(project_root) if project_root else None
    if declared_path:
        target = (root / declared_path) if root else Path(declared_path)
        if target.exists():
            return {
                "status": "FOUND",
                "candidates": [str(Path(declared_path).as_posix())],
                "basis": "DECLARED_PATH",
            }
        return {
            "status": "NOT_FOUND",
            "candidates": [],
            "basis": f"DECLARED_PATH_NOT_ON_DISK: {declared_path}",
        }
    if root is None or not root.exists() or not root.is_dir():
        return {"status": "UNKNOWN", "candidates": [],
                "basis": f"PROJECT_ROOT_UNREADABLE: {root}"}

    import fnmatch
    import os

    hits: List[Path] = []
    truncated = False
    files_walked = 0
    base_depth = len(root.resolve().parts)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            if len(here.resolve().parts) - base_depth >= MAX_WALK_DEPTH:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".svn"}]
            for fn in filenames:
                rel = (here / fn).relative_to(root).as_posix()
                if any(fnmatch.fnmatch(rel, g) for g in _TOP_TB_FILE_GLOBS):
                    hits.append(here / fn)
                files_walked += 1
                if files_walked >= MAX_WALK_FILES:
                    truncated = True
                    break
            if truncated:
                break
    except OSError as exc:
        return {"status": "UNKNOWN", "candidates": [],
                "basis": f"PROJECT_ROOT_WALK_FAILED: {exc}"}

    if not hits:
        basis = f"NO_MATCH_FOR {list(_TOP_TB_FILE_GLOBS)}"
        if truncated:
            return {"status": "UNKNOWN", "candidates": [],
                    "basis": f"WALK_TRUNCATED_AT_{MAX_WALK_FILES}_FILES"}
        return {"status": "NOT_FOUND", "candidates": [], "basis": basis}

    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    basis = (f"NAME_CONVENTION {list(_TOP_TB_FILE_GLOBS)} "
             "(dv_harness/subsystem_discovery.py ARTIFACT_GLOBS['top_hierarchy'])")
    if truncated:
        basis += f" -- WALK_TRUNCATED_AT_{MAX_WALK_FILES}_FILES, more candidates may exist unwalked"
    return {
        "status": "FOUND",
        "candidates": [p.relative_to(root).as_posix() for p in hits],
        "basis": basis,
    }


# --- fact extraction ---------------------------------------------------------

def _find_dut_instantiation(text: str, dut_module_name: Optional[str]) -> Dict[str, Any]:
    if not dut_module_name:
        # Which module is the real DUT is a declared project fact (same
        # discipline phy_boundary.py applies to the PHY/controller pair) --
        # never guessed from an instance/module name. Report what generic
        # instantiation-shaped text exists, but do not resolve any of it as
        # "the DUT".
        candidates = sorted(set(re.findall(
            r"^\s*([A-Za-z_]\w*)\s+(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*\(",
            text, re.MULTILINE,
        )))
        return {"status": "NOT_DECLARED", "dut_module_name": None,
                "instance_name": None, "evidence": None,
                "other_instantiations_seen": candidates}
    pattern = re.compile(
        rf"\b{re.escape(dut_module_name)}\b\s*(?:#\s*\([^;]*?\)\s*)?"
        rf"([A-Za-z_]\w*)\s*\(",
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return {"status": "ABSENT", "dut_module_name": dut_module_name,
                "instance_name": None, "evidence": None,
                "other_instantiations_seen": []}
    line_no = text.count("\n", 0, m.start()) + 1
    return {"status": "PRESENT", "dut_module_name": dut_module_name,
            "instance_name": m.group(1), "evidence": f"line {line_no}: {m.group(0).strip()}",
            "other_instantiations_seen": []}


def _find_clock_reset_declarations(text: str) -> Dict[str, List[Dict[str, str]]]:
    clocks: List[Dict[str, str]] = []
    resets: List[Dict[str, str]] = []
    seen_c, seen_r = set(), set()
    for m in _DECL_RE.finditer(text):
        name = m.group(1)
        line_no = text.count("\n", 0, m.start()) + 1
        decl = m.group(0).rstrip(",;)")
        if _RESET_NAME_RE.search(name) and name not in seen_r:
            resets.append({"name": name, "declaration": f"line {line_no}: {decl}"})
            seen_r.add(name)
        elif _CLOCK_NAME_RE.search(name) and name not in seen_c:
            clocks.append({"name": name, "declaration": f"line {line_no}: {decl}"})
            seen_c.add(name)
    return {"clocks": clocks, "resets": resets}


def _find_dv_uvm_hooks(text: str) -> Dict[str, Any]:
    ifdef_m = _DV_UVM_IFDEF_RE.search(text)
    include_m = _DV_UVM_HOOK_INCLUDE_RE.search(text)
    evidence = []
    if ifdef_m:
        line_no = text.count("\n", 0, ifdef_m.start()) + 1
        evidence.append(f"line {line_no}: {ifdef_m.group(0)}")
    if include_m:
        line_no = text.count("\n", 0, include_m.start()) + 1
        evidence.append(f"line {line_no}: {include_m.group(0)}")
    return {
        "dv_uvm_ifdef_present": bool(ifdef_m),
        "dv_uvm_hook_svh_included": bool(include_m),
        "evidence": evidence,
    }


def extract_top_tb_facts_from_text(text: str, *, source_label: str,
                                    dut_module_name: Optional[str] = None) -> Dict[str, Any]:
    """The real fact-extraction core, over already-read SystemVerilog TEXT --
    factored out from file-reading so `generated_top_tb_facts()` below can
    run the identical extraction over `_soc_tb_top()`'s real generated
    string without writing it to disk first.

    Returns the fixed fact shape both `extract_existing_top_tb_facts()` and
    `generated_top_tb_facts()` produce, so `compare_against_generated_top()`
    can compare two dicts of the SAME shape regardless of which side
    produced them."""
    module_m = _MODULE_NAME_RE.search(text)
    clk_rst = _find_clock_reset_declarations(text)
    return {
        "source_label": source_label,
        "source_sha256": _sha256_text(text),
        "module_name": module_m.group(1) if module_m else None,
        "dut_instantiation": _find_dut_instantiation(text, dut_module_name),
        "clock_signals": clk_rst["clocks"],
        "reset_signals": clk_rst["resets"],
        "uvm_hooks": _find_dv_uvm_hooks(text),
    }


def extract_existing_top_tb_facts(file_path, *, dut_module_name: Optional[str] = None) -> Dict[str, Any]:
    """Reads a real, on-disk candidate top TB file (one of
    `discover_existing_top_tb()`'s `candidates`) and extracts its real,
    inspectable facts -- never a fabricated guess about a file this module
    did not actually read."""
    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return extract_top_tb_facts_from_text(
        text, source_label=str(path), dut_module_name=dut_module_name,
    )


def generated_top_tb_facts(subsystems: Sequence[Dict[str, Any]], manifest: Dict[str, Any],
                            *, dut_module_name: Optional[str] = None) -> Dict[str, Any]:
    """Runs the IDENTICAL fact extraction `extract_existing_top_tb_facts()`
    uses, over the real text `soc_environment_composer._soc_tb_top()` itself
    generates for the same `subsystems`/`manifest` inputs a composition run
    would use -- read-only: this module imports and calls that function, it
    does not alter it or what it emits.

    `_soc_tb_top()` is a module-private helper by convention (leading
    underscore), which this module deliberately does NOT change; importing
    and calling it for its real generated text (rather than re-describing
    what it does) is what keeps GENERATED_ONLY/DIVERGENT facts below tied to
    the composer's REAL current output instead of a second, driftable
    description of it."""
    from .uvm_generator.soc_environment_composer import _soc_tb_top

    text = _soc_tb_top(subsystems, manifest)
    return extract_top_tb_facts_from_text(
        text, source_label="soc_environment_composer._soc_tb_top() (generated)",
        dut_module_name=dut_module_name,
    )


# --- comparison ---------------------------------------------------------------

def _compare_bool_fact(existing: bool, generated: bool) -> str:
    if existing and generated:
        return MATCH
    if not existing and not generated:
        return MATCH
    return EXISTING_ONLY if existing else GENERATED_ONLY


def _compare_name_set(existing_names: Sequence[str], generated_names: Sequence[str]) -> str:
    e, g = set(existing_names), set(generated_names)
    if e == g:
        return MATCH
    if e and not g:
        return EXISTING_ONLY
    if g and not e:
        return GENERATED_ONLY
    return DIVERGENT


def compare_against_generated_top(existing_top_facts: Dict[str, Any],
                                   generated_top_facts: Dict[str, Any]) -> Dict[str, Any]:
    """Per-fact structural comparison of two fact dicts produced by
    `extract_top_tb_facts_from_text()` (or its two callers above) -- reports
    MATCH / DIVERGENT / EXISTING_ONLY / GENERATED_ONLY / NOT_COMPARABLE per
    fact, and cites both sides' evidence. Never decides whether a divergence
    is acceptable, never picks a "winner" -- that decision belongs to the
    deliberately-deferred follow-on task this module's own docstring names
    (changing `soc_environment_composer.py` to actually preserve/integrate
    an existing top TB), gated on an explicit human design decision."""
    existing_dut = existing_top_facts.get("dut_instantiation") or {}
    generated_dut = generated_top_facts.get("dut_instantiation") or {}
    e_status, g_status = existing_dut.get("status"), generated_dut.get("status")
    if e_status == "NOT_DECLARED" or g_status == "NOT_DECLARED":
        dut_verdict = NOT_COMPARABLE
    elif e_status == "PRESENT" and g_status == "PRESENT":
        dut_verdict = (MATCH if existing_dut.get("dut_module_name") == generated_dut.get("dut_module_name")
                       else DIVERGENT)
    elif e_status == "ABSENT" and g_status == "ABSENT":
        dut_verdict = MATCH
    else:
        dut_verdict = EXISTING_ONLY if e_status == "PRESENT" else GENERATED_ONLY

    clock_verdict = _compare_name_set(
        [c["name"] for c in existing_top_facts.get("clock_signals", [])],
        [c["name"] for c in generated_top_facts.get("clock_signals", [])],
    )
    reset_verdict = _compare_name_set(
        [r["name"] for r in existing_top_facts.get("reset_signals", [])],
        [r["name"] for r in generated_top_facts.get("reset_signals", [])],
    )

    existing_hooks = existing_top_facts.get("uvm_hooks") or {}
    generated_hooks = generated_top_facts.get("uvm_hooks") or {}
    hooks_verdict = _compare_bool_fact(
        bool(existing_hooks.get("dv_uvm_ifdef_present") or existing_hooks.get("dv_uvm_hook_svh_included")),
        bool(generated_hooks.get("dv_uvm_ifdef_present") or generated_hooks.get("dv_uvm_hook_svh_included")),
    )

    return {
        "dut_instantiation": {
            "verdict": dut_verdict,
            "existing": existing_dut,
            "generated": generated_dut,
        },
        "clock_signals": {
            "verdict": clock_verdict,
            "existing": existing_top_facts.get("clock_signals", []),
            "generated": generated_top_facts.get("clock_signals", []),
        },
        "reset_signals": {
            "verdict": reset_verdict,
            "existing": existing_top_facts.get("reset_signals", []),
            "generated": generated_top_facts.get("reset_signals", []),
        },
        "uvm_hooks": {
            "verdict": hooks_verdict,
            "existing": existing_hooks,
            "generated": generated_hooks,
        },
    }
