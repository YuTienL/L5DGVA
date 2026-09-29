"""Reverse-derive a run_profile.json from a real generated-environment
Makefile -- the "whole chip script" / execution-authority asset described in
the asset-processing design (see docs/RUN_PROFILE.md).

Scope and honesty policy: this extractor recognizes the concrete Make
idioms actually used by dv_harness/uvm_generator/templates/sim_scripts/Makefile
(itself reverse-derived from the real USB_UVM_Handoff proving-ground
Makefile -- see CLAUDE.md's Makefile/sim-scripts migration note). It is a
pattern extractor, not a Make-language interpreter: anything it cannot
confidently classify is collected into the profile's own
`source.unparsed_hints` list (outside the strict schema, dropped before
validation, but reported to the caller) rather than silently skipped or
guessed. A field this tool cannot find is simply absent from the output --
never filled with an invented default.
"""
from __future__ import annotations

import re
from pathlib import Path

from dv_harness.uvm_generator.run_profile import (
    SCHEMA_VERSION,
    sha256_of_file,
    validate_run_profile,
)

# --- regexes for the idioms confirmed present in the real template Makefile ---

_RE_VAR_DEFAULT = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*\?=\s*(.*?)\s*$")
_RE_VAR_SIMPLE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*:=\s*(.*?)\s*$")
_RE_IFNDEF_ERROR = re.compile(r"^\s*ifndef\s+([A-Z][A-Z0-9_]*)\s*$")
_RE_ENUM_GUARD = re.compile(
    r"\$\(filter\s+\$\(([A-Z][A-Z0-9_]*)\),\s*([^)]+)\)\s*,\s*\)"
)
_RE_ERROR_MSG = re.compile(r"\$\(error\s+(.*?)\)\s*$")
_RE_RETIRED_LIST = re.compile(r"^([A-Z][A-Z0-9_]*)\s*:=\s*(.+)$")
_RE_PLUSARG_BINDING = re.compile(r"\+([A-Za-z0-9_]+)=\$\(([A-Z][A-Z0-9_]*)\)")
_RE_PLUSARG_BARE = re.compile(r"\+\$\(([A-Z][A-Z0-9_]*)\)(?!\w)")
_RE_PHONY = re.compile(r"^\.PHONY:\s*(.+)$")
_RE_MAKE_INVOCATION = re.compile(r"make\s+(\w[\w-]*)(?:\s+([A-Z0-9_=<>\s]+))?")

# Section banners the template's own comment headers use, in order. A line
# containing one of these (case-sensitive substring match) flips the
# section state machine used to classify subsequent `?=` params.
_SECTION_MARKERS = [
    ("Runtime variables (no rebuild needed)", "runtime"),
    ("DUT specification variables (rebuild required)", "compile_time"),
    ("RETIRED KNOBS", "retired"),
    ("Compile flags", "compile_flags"),
]

# Primary user-facing targets, named in the template's own header-comment
# usage block ("make compile", "make sim PATTERN=<name>", ...). Anything in
# .PHONY not in this map is still a real, invocable target -- it is
# included in the output targets list, just without a description or a
# curated params list, so an agent sees it exists without this tool
# pretending to know what it does.
_DOCUMENTED_TARGETS = {
    "compile": "Build simv (FLOW=onestep by default).",
    "elab": "Alias: elaboration stage of compile.",
    "sim": "Run one pattern.",
    "regress": "Run a suite against one shared elaboration.",
    "check": "Static checks, seconds not minutes.",
    "help": "Print every target and variable.",
    "list_patterns": "List every registered PATTERN= value.",
    "clean": "Remove per-run outputs, keep the compiled simv.",
    "distclean": "Remove everything under SIM_ROOT_PATH except scripts/.",
    "verdi": "Open the last run's FSDB in Verdi.",
    "debug": "Alias: interactive debug run.",
    "cov": "Merge coverage databases.",
    "cov_gui": "Open the merged coverage database in a GUI.",
}

# Params whose real run-time forwarding this extractor already knows how to
# find (RUN_FLAGS-style `+NAME=$(VAR)` or bare `+$(VAR)`) get their plusarg
# field filled from that real evidence. A var with no such occurrence in the
# file gets plusarg=None -- never a guessed `+VAR=`.


def _strip_comment_and_continuation(line: str) -> str:
    return line.rstrip("\n").rstrip("\\").rstrip()


def _collect_preceding_comment(lines: list[str], idx: int) -> str:
    """Walk upward from lines[idx-1] collecting a contiguous `#`-comment
    block directly above a var definition, as that var's description.
    Stops at the first blank or non-comment line. Returns the block, most
    recent line last, joined with spaces and de-hashed.
    """
    out: list[str] = []
    i = idx - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            if any(marker in text for marker, _sect in _SECTION_MARKERS):
                # A section banner is a boundary, not this var's own prose --
                # stop collecting before absorbing it into the description.
                break
            if text and not set(text) <= {"-", "="}:
                out.append(text)
            i -= 1
            continue
        break
    out.reverse()
    return " ".join(out)[:500]


def _classify_type(name: str, default: str) -> str:
    if name.endswith(("_PATH", "_DIR", "_HOME")):
        return "path"
    if default in ("0", "1"):
        return "bool01"
    if re.fullmatch(r"-?\d+", default or ""):
        return "int"
    return "string"


def extract_run_profile(makefile_path: Path, target_ip: str, ip_prefix: str) -> dict:
    """Parse `makefile_path` and return a run_profile.json-shaped dict.
    Raises RunProfileValidationError (via the caller's validate step) if the
    result is somehow not schema-valid -- this function itself does not
    validate, so a caller can inspect a rejected draft before deciding what
    to do with it.
    """
    raw_text = makefile_path.read_text(encoding="utf-8", errors="replace")
    # Make joins a trailing backslash-newline into one logical line (GNU Make
    # manual, "Splitting Long Lines") -- multi-line .PHONY declarations and
    # multi-line variable assignments in the real template Makefile both rely
    # on this. Join them before line-based scanning so e.g. `.PHONY: help \`
    # newline `compile sim ...` is seen as one line, not two.
    text = raw_text.replace("\\\n", " ")
    lines = text.splitlines()

    profile: dict = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "kind": "makefile",
            "path": str(makefile_path),
            "content_sha256": sha256_of_file(makefile_path),
        },
        "target": {"target_ip": target_ip, "ip_prefix": ip_prefix},
        "required_paths": [],
        "compile_time_params": [],
        "runtime_params": [],
        "defines": [],
        "compile_flags": {},
        "lsf": {},
        "pattern_registry": {},
        "constraints": [],
        "targets": [],
    }

    section = None
    seen_params: dict[str, dict] = {}
    ifndef_required: set[str] = set()

    for i, raw in enumerate(lines):
        for marker, sect in _SECTION_MARKERS:
            if marker in raw:
                section = sect

        m = _RE_IFNDEF_ERROR.match(raw)
        if m:
            # Look ahead a few lines for the matching $(error ...) to confirm
            # this ifndef really is a hard requirement (not, e.g., a no-op
            # guard for a goal-filtered block).
            for look in lines[i + 1 : i + 4]:
                if "$(error" in look:
                    ifndef_required.add(m.group(1))
                    break

        m = _RE_VAR_DEFAULT.match(raw)
        if m:
            name, default = m.group(1), m.group(2)
            if name in seen_params:
                continue
            desc = _collect_preceding_comment(lines, i)
            ptype = _classify_type(name, default)
            entry = {"name": name, "type": ptype, "default": default, "description": desc}
            seen_params[name] = entry
            if section in ("runtime", "compile_time"):
                entry["requires_rebuild"] = section == "compile_time"

    # --- enum constraints: ifeq ($(filter $(NAME),a b c),) blocks ---
    for i, raw in enumerate(lines):
        m = _RE_ENUM_GUARD.search(raw)
        if not m:
            continue
        name, values_str = m.group(1), m.group(2)
        values = values_str.split()
        # Find the $(error ...) on the following lines (may wrap).
        msg_lines = []
        for look in lines[i + 1 : i + 6]:
            msg_lines.append(look.strip())
            if "$(error" in look and look.count("(") <= look.count(")"):
                break
        msg = " ".join(msg_lines)
        err_m = _RE_ERROR_MSG.search(msg.replace("\\", " "))
        message = err_m.group(1).strip() if err_m else msg.strip()
        if name in seen_params:
            seen_params[name]["type"] = "enum"
            seen_params[name]["enum"] = values
        profile["constraints"].append(
            {
                "id": f"enum_{name.lower()}",
                "kind": "enum_membership",
                "params": [name],
                "message": message[:400],
            }
        )

    # --- retired knobs ---
    for i, raw in enumerate(lines):
        if "RETIRED_VIP_KNOBS" in raw and ":=" in raw and "$(foreach" not in raw:
            m = _RE_RETIRED_LIST.match(raw.strip())
            if m and m.group(1) == "RETIRED_VIP_KNOBS":
                retired_names = m.group(2).split()
                profile["constraints"].append(
                    {
                        "id": "retired_vip_knobs",
                        "kind": "retired",
                        "params": retired_names,
                        "message": "These knobs are a hard $(error) if set -- see the source "
                        "Makefile's own RETIRED KNOBS comment for the replacement mechanism.",
                    }
                )

    # --- real plusarg bindings: +NAME=$(VAR) or bare +$(VAR) ---
    plusarg_map: dict[str, str] = {}
    for raw in lines:
        for pm in _RE_PLUSARG_BINDING.finditer(raw):
            plusarg_name, var_name = pm.group(1), pm.group(2)
            plusarg_map.setdefault(var_name, f"+{plusarg_name}=")
        for pm in _RE_PLUSARG_BARE.finditer(raw):
            var_name = pm.group(1)
            plusarg_map.setdefault(var_name, f"+{var_name}")

    for name, entry in seen_params.items():
        if name in plusarg_map:
            entry["plusarg"] = plusarg_map[name]

    # --- required paths ---
    path_like = {n for n in seen_params if n.endswith(("_PATH", "_HOME", "_DIR"))}
    path_like |= ifndef_required
    for name in sorted(path_like):
        entry = seen_params.get(name, {})
        profile["required_paths"].append(
            {
                "name": name,
                "required": name in ifndef_required or entry.get("default") in (None, ""),
                "default": entry.get("default") or None,
                "description": entry.get("description", ""),
            }
        )

    # --- split remaining params into compile_time vs runtime buckets ---
    for name, entry in seen_params.items():
        if name in path_like:
            continue
        requires_rebuild = entry.pop("requires_rebuild", None)
        entry.setdefault("plusarg", None)
        entry = {k: v for k, v in entry.items() if v not in (None, "") or k in ("name", "type")}
        if entry.get("plusarg") is None:
            entry.pop("plusarg", None)
        if requires_rebuild:
            profile["compile_time_params"].append(entry)
        elif requires_rebuild is False:
            profile["runtime_params"].append(entry)
        # requires_rebuild is None: the var was never inside a recognized
        # section banner (e.g. LSF_NCORE) -- handled by dedicated blocks
        # below instead of falling into either generic bucket.

    # --- LSF block ---
    if "LSF" in seen_params:
        profile["lsf"] = {
            "enabled_by": "LSF",
            "default": seen_params["LSF"].get("default"),
            "ncore_var": "LSF_NCORE",
            "ncore_default": int(seen_params.get("LSF_NCORE", {}).get("default", 0) or 0) or None,
            "required_scripts": ["lsf_regress.sh", "lsf_wait.sh"],
        }

    # --- pattern registry ---
    if "tb/patterns/pattern_list.txt" in text or "pattern_list.txt" in text:
        profile["pattern_registry"] = {
            "path": "tb/patterns/pattern_list.txt",
            "selector_param": "PATTERN" if "PATTERN" in seen_params else None,
        }

    # --- targets, from the real .PHONY line(s) ---
    phony_names: list[str] = []
    for raw in lines:
        m = _RE_PHONY.match(raw.strip())
        if m:
            phony_names.extend(m.group(1).replace("\\", " ").split())
    seen_target_names: set[str] = set()
    for name in phony_names:
        if name in seen_target_names:
            continue
        seen_target_names.add(name)
        target_entry = {"name": name}
        if name in _DOCUMENTED_TARGETS:
            target_entry["description"] = _DOCUMENTED_TARGETS[name]
        if name == "sim":
            target_entry["params"] = [
                p for p in ("PATTERN", "TEST", "SEED", "WAVE", "VERB", "VERB_LEVEL", "VERB_COMP", "TOTAL_RUNTIME")
                if p in seen_params
            ]
        elif name == "compile":
            target_entry["params"] = [
                p["name"] for p in profile["compile_time_params"]
            ]
            target_entry["requires_rebuild"] = True
        elif name == "regress":
            target_entry["params"] = ["SUITE"] if "SUITE" in text else []
        profile["targets"].append(target_entry)

    return profile


def extract_and_write(makefile_path: Path, out_path: Path, target_ip: str, ip_prefix: str) -> dict:
    """Extract, validate, and write run_profile.json. Returns the profile
    dict on success. Raises RunProfileValidationError if extraction produced
    a profile that fails schema validation -- the caller must not write a
    file that failed validation, since downstream tooling trusts any
    run_profile.json on disk to already be schema-valid.
    """
    profile = extract_run_profile(makefile_path, target_ip=target_ip, ip_prefix=ip_prefix)
    validate_run_profile(profile)
    out_path.write_text(
        __import__("json").dumps(profile, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return profile
